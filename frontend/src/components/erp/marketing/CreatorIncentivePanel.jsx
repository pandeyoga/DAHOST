/**
 * CreatorIncentivePanel — **Insentif kreator per pcs + tracker periode** (sesi #34).
 *
 * Keputusan pemilik (2026-08-23):
 *  • hanya kreator **kontrak** & **continue** dapat insentif (tipe `new` tidak);
 *  • bentuknya bisa DUA-DUANYA dan dikonfigurasi per kreator:
 *      Rp per pcs terjual  dan/atau  bonus bila target pcs periode tercapai;
 *  • **pcs terjual diinput STAF MARKETING** (bukan kreator) — supaya angka yang
 *    dibayar tidak lahir dari klaim orang yang menerima uangnya;
 *  • periode **default 3 bulan**, bisa dikonfigurasi; periode habis ⇒ hitungan
 *    kembali 0, tetapi entri periode lama tetap tersimpan sebagai bukti bayar.
 *
 * Standar UI/UX v2 (8 Nov 2026): DetailPopup (dulu jendela buatan sendiri), angka = StatTile, isian = Isian +
 * komponen standar, tanggal = DatePicker, catatan entri = tabel + unduh. Panggilan API tidak berubah.
 */
import { useCallback, useEffect, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Plus, Trash2, RotateCcw, Save, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import DatePicker from '@/components/ui/date-picker';
import DetailPopup from '@/components/ui/detail-popup';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Isian } from '@/components/ui/form-popup';
import { formatDateID } from '@/lib/format';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;
const rp = formatRupiah;

export default function CreatorIncentivePanel({ token, creator, onClose }) {
  const [data, setData] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [entry, setEntry] = useState(() => ({ date: todayWIB(), pcs: '', note: '' }));
  const [busy, setBusy] = useState(false);
  const H = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = useCallback(async () => {
    const r = await fetch(`${API}/api/marketing/kol/creators/${creator.id}/incentive`, { headers: H });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal memuat insentif'); return; }
    setData(d);
    setCfg(d.config);
  }, [creator.id, token]); // eslint-disable-line

  useEffect(() => { load(); }, [load]);

  const saveCfg = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/marketing/kol/creators/${creator.id}/incentive`,
        { method: 'PUT', headers: H, body: JSON.stringify(cfg) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menyimpan');
      setData(d); setCfg(d.config);
      toast.success('Konfigurasi insentif tersimpan.');
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const addEntry = async () => {
    if (!Number(entry.pcs)) { toast.error('Jumlah pcs wajib diisi'); return; }
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/marketing/kol/creators/${creator.id}/incentive/entries`,
        { method: 'POST', headers: H, body: JSON.stringify({ ...entry, pcs: Number(entry.pcs) }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menambah entri');
      setData(d); setEntry({ ...entry, pcs: '', note: '' });
      toast.success(`+${d.entry.pcs} pcs tercatat`);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const delEntry = async (id) => {
    const r = await fetch(`${API}/api/marketing/kol/creators/${creator.id}/incentive/entries/${id}`,
      { method: 'DELETE', headers: H });
    const d = await r.json();
    if (!r.ok) { toast.error(d.detail || 'Gagal menghapus'); return; }
    setData(d); toast.success('Entri dihapus.');
  };

  const closePeriod = async () => {
    if (!(await confirmDialog({ title: 'Tutup periode ini?', body: 'Hitungan mulai dari 0 hari ini. Entri lama tetap tersimpan.', confirmLabel: 'Tutup periode', danger: true }))) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/marketing/kol/creators/${creator.id}/incentive/close-period`,
        { method: 'POST', headers: H });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menutup periode');
      setData(d); setCfg(d.config);
      toast.success(`Periode ditutup pada ${rp(d.closed)} — hitungan dimulai dari 0`);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const TIPE = { new: 'baru', kontrak: 'kontrak', continue: 'lanjutan' };
  const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');
  const kolom = [
    { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (e) => <span className="tabular-nums md:whitespace-nowrap">{tgl(e.date)}</span> },
    { kunci: 'pcs', label: 'Pcs', rata: 'kanan', hp: 'judul', isi: (e) => <span className="tabular-nums font-medium">{e.pcs}</span> },
    { kunci: 'catatan', label: 'Catatan', isi: (e) => e.note || '—' },
    { kunci: 'oleh', label: 'Diinput', isi: (e) => <span className="text-muted-foreground">{e.entered_by || '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (e) => (
      <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--danger-text))]" onClick={() => delEntry(e.id)}
        data-testid={`tracker-del-${e.id}`} title="Hapus entri" aria-label="Hapus entri"><Trash2 /></Button>) },
  ];

  return (
    <DetailPopup open onClose={onClose} testId="creator-incentive-panel"
      judul={`Insentif · ${data?.creator_name || creator.name}`}
      keterangan={data ? `Tipe ${TIPE[data.creator_type] || data.creator_type} · periode ${data.period.period_months} bulan (${tgl(data.period.start)} – ${tgl(data.period.end)})` : undefined}>
      {!data || !cfg ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat insentif…</p>
      ) : (
        <>
          {!data.eligible && (
            <Notice tone="warning" icon={AlertTriangle} testId="incentive-not-eligible">{data.eligible_reason}</Notice>
          )}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Pcs terjual (periode)" value={`${data.pcs_sold} pcs`} testId="incentive-pcs" hint="Dicatat staf marketing di bawah." />
            <StatTile label="Target" value={data.target_pcs ? `${data.target_pcs} pcs` : '—'}
              sub={data.target_pcs ? `${data.progress_pct}% tercapai` : 'Belum ada target'} testId="incentive-target" />
            <StatTile label="Insentif per pcs" value={rp(data.per_pcs_amount)} testId="incentive-perpcs-amount" />
            <StatTile label="Total insentif" value={rp(data.total_incentive)}
              sub={data.bonus_amount ? `termasuk bonus ${rp(data.bonus_amount)}` : undefined} testId="incentive-total" />
          </div>

          <div className="space-y-3 border-t border-[var(--glass-border)] pt-3">
            <p className="text-base font-semibold">Konfigurasi</p>
            <div className="grid gap-4 sm:grid-cols-3">
              <Isian label="Skema" htmlFor="inc-mode">
                <SmartNativeSelect id="inc-mode" data-testid="incentive-mode-select" value={cfg.mode} searchable={false}
                  onChange={(e) => setCfg({ ...cfg, mode: e.target.value })}>
                  <option value="none">Tidak dapat insentif</option>
                  <option value="per_pcs">Rp per pcs terjual</option>
                  <option value="target_bonus">Bonus bila target tercapai</option>
                  <option value="both">Keduanya</option>
                </SmartNativeSelect>
              </Isian>
              <Isian label="Rp per pcs">
                <MoneyInput data-testid="incentive-rate-input" value={cfg.rate_per_pcs}
                  onChange={(e) => setCfg({ ...cfg, rate_per_pcs: Number(e.target.value) })} />
              </Isian>
              <Isian label="Target pcs per periode" htmlFor="inc-target">
                <Input id="inc-target" data-testid="incentive-targetpcs-input" type="number" min="0" value={cfg.target_pcs}
                  onChange={(e) => setCfg({ ...cfg, target_pcs: Number(e.target.value) })} />
              </Isian>
              <Isian label="Bonus target (Rp)">
                <MoneyInput data-testid="incentive-bonus-input" value={cfg.bonus_amount}
                  onChange={(e) => setCfg({ ...cfg, bonus_amount: Number(e.target.value) })} />
              </Isian>
              <Isian label="Panjang periode (bulan)" htmlFor="inc-period">
                <Input id="inc-period" data-testid="incentive-period-input" type="number" min="1" max="24" value={cfg.period_months}
                  onChange={(e) => setCfg({ ...cfg, period_months: Number(e.target.value) })} />
              </Isian>
              <Isian label="Mulai periode">
                <DatePicker value={cfg.period_start || ''} onChange={(v) => setCfg({ ...cfg, period_start: v })} testId="incentive-start-input" />
              </Isian>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="success" data-testid="incentive-save-btn" disabled={busy} onClick={saveCfg}><Save />Simpan konfigurasi</Button>
              <Button variant="outline" data-testid="incentive-close-period-btn" disabled={busy} onClick={closePeriod}><RotateCcw />Tutup periode &amp; mulai dari 0</Button>
            </div>
          </div>

          <div className="space-y-3 border-t border-[var(--glass-border)] pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-base font-semibold">Catatan pcs terjual <span className="text-sm font-normal text-muted-foreground">(diinput staf marketing)</span></p>
              <TombolUnduh namaBerkas={`insentif-${creator.creator_code || 'kreator'}`} namaLembar="Pcs terjual" baris={data.entries || []}
                testId="incentive-unduh" kolom={[
                  { label: 'Tanggal', nilai: (e) => tgl(e.date) }, { label: 'Pcs', nilai: (e) => Number(e.pcs) || 0 },
                  { label: 'Catatan', nilai: (e) => e.note || '' }, { label: 'Diinput', nilai: (e) => e.entered_by || '' },
                ]} />
            </div>
            <div className="grid items-end gap-3 sm:grid-cols-[12rem_7rem_1fr_auto]">
              <Isian label="Tanggal">
                <DatePicker value={entry.date} onChange={(v) => setEntry({ ...entry, date: v })} testId="tracker-date-input" />
              </Isian>
              <Isian label="Pcs" htmlFor="trk-pcs">
                <Input id="trk-pcs" data-testid="tracker-pcs-input" type="number" min="1" value={entry.pcs}
                  onChange={(e) => setEntry({ ...entry, pcs: e.target.value })} />
              </Isian>
              <Isian label="Catatan" htmlFor="trk-note">
                <Input id="trk-note" data-testid="tracker-note-input" value={entry.note} placeholder="mis. live 20/08 toko A"
                  onChange={(e) => setEntry({ ...entry, note: e.target.value })} />
              </Isian>
              <Button data-testid="tracker-add-btn" disabled={busy} onClick={addEntry}><Plus />Tambah</Button>
            </div>
            <TabelData kolom={kolom} baris={data.entries || []} testId="tracker-table"
              kosong={<EmptyState title="Belum ada entri pada periode ini" />} />
          </div>
        </>
      )}
    </DetailPopup>
  );
}
