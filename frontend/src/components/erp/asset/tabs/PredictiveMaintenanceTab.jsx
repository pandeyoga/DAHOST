/**
 * PredictiveMaintenanceTab — peringatan pemeliharaan (lewat jadwal, segera jatuh tempo, perbaikan berulang,
 * perkiraan jadwal, lama tidak dirawat). Dihitung server dari riwayat pemeliharaan.
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • kotak 4 isian angka berlabel Inggris di atas halaman → tombol "Atur batas" yang membuka popup form;
 *    batas yang berlaku ditulis dalam satu kalimat;
 *  • 5 kartu gradasi → 4 StatTile (semua 0 → tampilan kosong);
 *  • kartu berwarna per peringatan (maks. 20 per bagian) → SATU tabel, disaring pil jenis;
 *  • "Snooze" → "Tunda 30 hari"; istilah Overdue/Upcoming/Stale/Predicted/High Frequency → Indonesia.
 */
import { useState, useEffect, useCallback } from 'react';
import { BellOff, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatusBadge as Lencana } from '../../moduleAtoms';
import { SEVERITY_CONFIG } from '../constants';
import { apicall, fmtDate, useHP } from '../utils';
import { KPICard, BarisKartu } from '../components/KPICard';
import { JENIS_PERINGATAN, URUTAN_JENIS, keteranganPeringatan } from '../components/PMAlertCard';

const BAWAAN = {
  upcoming_window_days: 30,
  stale_months: 6,
  high_frequency_window_days: 90,
  high_frequency_threshold: 3,
  category_id: 'all',
};

const ISIAN_BATAS = [
  { key: 'upcoming_window_days', label: 'Segera jatuh tempo (hari)', min: 1, max: 365, bawaan: 30, testId: 'pm-config-upcoming-days',
    petunjuk: 'Peringatan muncul bila jadwal pemeliharaan jatuh dalam sekian hari ke depan.' },
  { key: 'stale_months', label: 'Lama tidak dirawat (bulan)', min: 1, max: 36, bawaan: 6, testId: 'pm-config-stale-months',
    petunjuk: 'Aset tanpa pemeliharaan selama sekian bulan.' },
  { key: 'high_frequency_window_days', label: 'Jendela perbaikan berulang (hari)', min: 7, max: 365, bawaan: 90, testId: 'pm-config-hf-days',
    petunjuk: 'Rentang hari untuk menghitung perbaikan berulang.' },
  { key: 'high_frequency_threshold', label: 'Batas perbaikan berulang (kali)', min: 2, max: 20, bawaan: 3, testId: 'pm-config-hf-threshold',
    petunjuk: 'Peringatan muncul bila aset dirawat sekian kali atau lebih dalam jendela di atas.' },
];

export function PredictiveMaintenanceTab({ token }) {
  const [config, setConfig] = useState(BAWAAN);
  const [draft, setDraft] = useState(null);       // null = popup "Atur batas" tertutup
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('all'); // all | overdue | upcoming | stale | high_frequency | predicted
  const [ackBusy, setAckBusy] = useState(false);
  const hp = useHP();

  const load = useCallback(async (cfg = config) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        upcoming_window_days: String(cfg.upcoming_window_days),
        stale_months: String(cfg.stale_months),
        high_frequency_window_days: String(cfg.high_frequency_window_days),
        high_frequency_threshold: String(cfg.high_frequency_threshold),
      });
      if (cfg.category_id && cfg.category_id !== 'all') params.append('category_id', cfg.category_id);
      const data = await apicall('GET', `/api/assets/predictive-maintenance/alerts?${params}`, token);
      setReport(data);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat peringatan pemeliharaan');
    } finally {
      setLoading(false);
    }
  }, [token, config]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const terapkan = () => {
    setConfig(draft);
    setDraft(null);
    load(draft);
  };

  const acknowledge = async (alert) => {
    setAckBusy(true);
    try {
      await apicall('POST', '/api/assets/predictive-maintenance/acknowledge', token, {
        asset_id: alert.asset_id,
        alert_kind: alert.kind,
        note: '',
      });
      toast.success(`Peringatan "${alert.asset_name}" ditunda 30 hari`);
      await load();
    } catch (e) {
      toast.error(e.message || 'Gagal menunda peringatan');
    } finally {
      setAckBusy(false);
    }
  };

  const summary = report?.summary || {};
  const semua = URUTAN_JENIS.flatMap((k) => report?.[k] || []);
  const baris = filter === 'all' ? semua : semua.filter((a) => a.kind === filter);
  const adaPeringatan = (summary.total_alerts || 0) > 0;
  const alatDiPenyaring = hp && adaPeringatan;
  const kalimatBatas = `Batas: jatuh tempo ≤ ${config.upcoming_window_days} hari · tidak dirawat ≥ ${config.stale_months} bulan · `
    + `berulang ≥ ${config.high_frequency_threshold} kali dalam ${config.high_frequency_window_days} hari.`;

  const alat = (
    <>
      <Button variant="outline" onClick={() => setDraft({ ...config })} data-testid="pm-atur-batas">
        <SlidersHorizontal />Atur batas
      </Button>
      <TombolUnduh namaBerkas="peringatan-pemeliharaan" namaLembar="Peringatan" baris={baris} testId="pm-unduh"
        kolom={[
          { label: 'No. aset', nilai: (a) => a.asset_number },
          { label: 'Aset', nilai: (a) => a.asset_name },
          { label: 'Peringatan', nilai: (a) => JENIS_PERINGATAN[a.kind]?.label || a.kind },
          { label: 'Tingkat', nilai: (a) => SEVERITY_CONFIG[a.severity]?.label || a.severity },
          { label: 'Keterangan', nilai: keteranganPeringatan },
          { label: 'Kategori', nilai: (a) => a.category_name || '' },
          { label: 'Pemegang', nilai: (a) => a.current_assignee || '' },
          { label: 'Pemeliharaan terakhir', nilai: (a) => (a.last_maintenance_date ? fmtDate(a.last_maintenance_date) : '') },
        ]} />
      <Button variant="outline" size="icon" onClick={() => load()} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
        data-testid="pm-apply-button">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </>
  );

  return (
    <PageLayout testId="pm-alerts-tab" title="Peringatan pemeliharaan"
      subtitle="Aset yang perlu dirawat, dihitung dari riwayat pemeliharaan."
      filters={adaPeringatan ? (<>
        <FilterChips value={filter} onChange={setFilter} testId="pm-filter" ariaLabel="Jenis peringatan"
          options={[
            { key: 'all', label: 'Semua', count: summary.total_alerts || 0 },
            ...URUTAN_JENIS.map((k) => ({ key: k, label: JENIS_PERINGATAN[k].label, count: (report?.[k] || []).length })),
          ]} />
        {alatDiPenyaring && alat}
      </>) : null}
      tools={alatDiPenyaring ? null : alat}
      summary={adaPeringatan ? (
        <BarisKartu testId="pm-kpi">
          <KPICard label="Mendesak" value={summary.critical_count || 0} accent={summary.critical_count ? 'danger' : 'default'}
            sub="Perlu tindakan segera" testId="pm-kpi-critical"
            hint="Lewat jadwal lebih dari 14 hari, atau perbaikan berulang dua kali batas." />
          <KPICard label="Lewat jadwal" value={summary.overdue_count || 0} testId="pm-kpi-overdue"
            sub="Jadwal pemeliharaan sudah lewat" hint="Jadwal pemeliharaan berikutnya sudah lewat hari ini." />
          <KPICard label="Segera jatuh tempo" value={summary.upcoming_count || 0} testId="pm-kpi-upcoming"
            sub={`Dalam ${config.upcoming_window_days} hari ke depan`} hint="Jadwal pemeliharaan jatuh dalam jendela hari yang diatur." />
          <KPICard label="Perbaikan berulang" value={summary.high_frequency_count || 0} testId="pm-kpi-hf"
            sub={`≥ ${config.high_frequency_threshold} kali dalam ${config.high_frequency_window_days} hari`}
            hint="Pola pemeliharaan tidak wajar: terlalu sering dalam jendela hari yang diatur." />
        </BarisKartu>
      ) : null}>
      <p className="text-sm text-muted-foreground" data-testid="pm-batas">{kalimatBatas}</p>
      {!report ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat peringatan…</p>
      ) : !adaPeringatan ? (
        <EmptyState title="Tidak ada peringatan pemeliharaan" testId="pm-empty-state"
          description={'Semua aset terkendali menurut batas yang berlaku. Ubah batas lewat tombol "Atur batas" bila perlu.'} />
      ) : (
        <TabelData baris={baris} kunci={(a) => `${a.kind}-${a.asset_id}`} testId="pm-table"
          kosong={<p className="py-6 text-center text-sm text-muted-foreground">Tidak ada peringatan jenis ini.</p>}
          kolom={[
            { kunci: 'aset', label: 'Aset', hp: 'judul', isi: (a) => (
              <div className="min-w-0">
                <p className="font-medium">{a.asset_name}</p>
                <p className="text-xs tabular-nums text-muted-foreground">{a.asset_number}</p>
              </div>) },
            { kunci: 'jenis', label: 'Peringatan', isi: (a) => {
              const j = JENIS_PERINGATAN[a.kind] || { label: a.kind, tone: 'muted' };
              return <Lencana status={a.kind} label={j.label} tone={j.tone} />;
            } },
            { kunci: 'tingkat', label: 'Tingkat', isi: (a) => {
              const s = SEVERITY_CONFIG[a.severity] || SEVERITY_CONFIG.info;
              return <Lencana status={a.severity} label={s.label} tone={s.tone} />;
            } },
            { kunci: 'ket', label: 'Keterangan', hp: 'keterangan', isi: (a) => (
              <span className="block text-sm md:max-w-[26rem]">{keteranganPeringatan(a)}</span>) },
            { kunci: 'kat', label: 'Kategori', isi: (a) => a.category_name || '—' },
            { kunci: 'pemegang', label: 'Pemegang', isi: (a) => a.current_assignee || '—' },
            { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => (
              <Button size="sm" variant="outline" onClick={() => acknowledge(a)} disabled={ackBusy}
                title="Sembunyikan peringatan ini selama 30 hari" data-testid={`pm-ack-${a.kind}-${a.asset_id}`}>
                <BellOff />Tunda 30 hari
              </Button>) },
          ]} />
      )}

      <FormPopup open={!!draft} onClose={() => setDraft(null)} ukuran="pendek" testId="pm-batas-form"
        judul="Atur batas peringatan" keterangan="Batas dipakai untuk menghitung ulang peringatan di layar ini."
        labelSimpan="Terapkan" menyimpan={loading} onSimpan={terapkan}>
        {draft && ISIAN_BATAS.map((f) => (
          <Isian key={f.key} label={f.label} petunjuk={`${f.petunjuk} Antara ${f.min}–${f.max}.`} htmlFor={`pm-${f.key}`}>
            <Input id={`pm-${f.key}`} type="number" inputMode="numeric" min={f.min} max={f.max} value={draft[f.key]}
              onChange={(e) => setDraft((p) => ({ ...p, [f.key]: parseInt(e.target.value || String(f.bawaan), 10) }))}
              data-testid={f.testId} />
          </Isian>
        ))}
      </FormPopup>
    </PageLayout>
  );
}
