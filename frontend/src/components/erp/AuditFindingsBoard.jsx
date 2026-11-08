/**
 * Papan Temuan Audit 2026-09-23 — status 30 temuan (Finance · Produksi/Maklon · R&D).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, kartu angka StatTile (dihitung dari daftar yang sama), penyaring satu
 * baris, tabel (kartu ringkas di HP) + unduh Excel/CSV, rincian perbaikan di popup (dulu kolom panjang di tabel),
 * jalur berkas sumber dipindah ke popup "Sumber".
 */
import { useEffect, useMemo, useState } from 'react';
import { FileText, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const STATUS_META = {
  selesai: { label: 'Selesai', tone: 'success' },
  diterima: { label: 'Diterima (mitigasi)', tone: 'info' },
  terbuka: { label: 'Terbuka', tone: 'warning' },
};
const TINGKAT_TONE = { Kritis: 'danger', Tinggi: 'warning', Sedang: 'info', Rendah: 'muted' };
const NAMA_PORTAL = { Finance: 'Keuangan' };
const namaPortal = (p) => NAMA_PORTAL[p] || p;
const metaStatus = (s) => STATUS_META[s] || STATUS_META.terbuka;

export default function AuditFindingsBoard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [portal, setPortal] = useState('Semua');
  const [status, setStatus] = useState('');
  const [cari, setCari] = useState('');
  const [detail, setDetail] = useState(null);
  const [lihatSumber, setLihatSumber] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('/api/rahaza/admin/audit-findings', { headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` } });
        if (!r.ok) throw new Error(`kode ${r.status}`);
        setData(await r.json());
      } catch (e) { setErr(e.message || 'Gagal memuat'); }
    })();
  }, []);

  const items = useMemo(() => data?.items || [], [data]);
  const diPortal = useMemo(() => items.filter((f) => portal === 'Semua' || f.portal === portal), [items, portal]);
  const q = cari.trim().toLowerCase();
  const rows = useMemo(() => diPortal
    .filter((f) => !status || (STATUS_META[f.status] ? f.status : 'terbuka') === status)
    .filter((f) => !q || `${f.id} ${f.judul} ${f.perbaikan}`.toLowerCase().includes(q)), [diPortal, status, q]);

  // Kartu dihitung dari daftar temuan yang sama (mengikuti pilihan portal), bukan dari angka ringkasan terpisah.
  const hitung = (s) => diPortal.filter((f) => (STATUS_META[f.status] ? f.status : 'terbuka') === s).length;
  const total = diPortal.length;
  const done = hitung('selesai');
  const pct = total ? Math.round((done / total) * 100) : 0;
  const portals = Object.keys(data?.by_portal || {});
  const ketPortal = portal === 'Semua' ? 'semua portal' : namaPortal(portal);

  const kolom = [
    { kunci: 'id', label: 'ID', hp: 'keterangan', isi: (f) => <span className="whitespace-nowrap font-mono text-xs">{f.id}</span> },
    { kunci: 'judul', label: 'Temuan', hp: 'judul', isi: (f) => <span className="md:max-w-[28rem] md:block">{f.judul}</span> },
    { kunci: 'portal', label: 'Portal', isi: (f) => <span className="whitespace-nowrap text-sm">{namaPortal(f.portal)}</span> },
    { kunci: 'tingkat', label: 'Tingkat', isi: (f) => <StatusBadge status={f.tingkat} label={f.tingkat} tone={TINGKAT_TONE[f.tingkat] || 'default'} /> },
    { kunci: 'status', label: 'Status', isi: (f) => <StatusBadge status={f.status} label={metaStatus(f.status).label} tone={metaStatus(f.status).tone} /> },
    { kunci: 'uji', label: 'Diuji', isi: (f) => <span className="whitespace-nowrap text-sm text-muted-foreground">{f.iterasi ? `Iterasi ${f.iterasi}` : '—'}</span> },
  ];

  return (
    <PageLayout testId="audit-findings-board" title="Papan temuan audit"
      subtitle="Status temuan audit 23 Sep 2026 untuk Keuangan, Produksi/Maklon, dan R&D beserta perbaikannya."
      filters={data && <>
        <FilterChips value={status} onChange={setStatus} hideWhenEmpty={false} testId="audit-filter-status" className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" options={[
          { key: '', label: 'Semua', count: total },
          { key: 'selesai', label: 'Selesai', count: hitung('selesai') },
          { key: 'diterima', label: 'Diterima', count: hitung('diterima') },
          { key: 'terbuka', label: 'Terbuka', count: hitung('terbuka') },
        ]} />
        <SmartNativeSelect value={portal} onChange={(e) => setPortal(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-44" aria-label="Portal"
          data-testid="audit-filter-portal">
          {['Semua', ...portals].map((p) => (
            <option key={p} value={p}>{p === 'Semua' ? 'Semua portal' : `${namaPortal(p)} (${data.by_portal[p]})`}</option>
          ))}
        </SmartNativeSelect>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari ID, temuan, perbaikan" className="pl-8"
            data-testid="audit-search" />
        </div>
      </>}
      tools={data && <>
        <TombolUnduh namaBerkas="papan-temuan-audit" namaLembar="Temuan" baris={rows} testId="audit-unduh" kolom={[
          { label: 'ID', nilai: (f) => f.id }, { label: 'Portal', nilai: (f) => namaPortal(f.portal) },
          { label: 'Temuan', nilai: (f) => f.judul }, { label: 'Tingkat', nilai: (f) => f.tingkat },
          { label: 'Status', nilai: (f) => metaStatus(f.status).label }, { label: 'Perbaikan', nilai: (f) => f.perbaikan },
          { label: 'Berkas', nilai: (f) => f.berkas }, { label: 'Iterasi uji', nilai: (f) => f.iterasi || '' },
        ]} />
      </>}
      summary={data && total > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Total temuan" value={total} sub={`Untuk ${ketPortal}`} testId="audit-total" />
          <StatTile label="Selesai" value={done} suffix={`(${pct}%)`} accent={done ? 'success' : 'default'}
            sub="Sudah diperbaiki dan diuji" testId="audit-done" />
          <StatTile label="Diterima (mitigasi)" value={hitung('diterima')} sub="Risiko diterima dengan pengaman" testId="audit-accepted" />
          <StatTile label="Terbuka" value={hitung('terbuka')} accent={hitung('terbuka') ? 'warning' : 'default'}
            sub="Belum ditangani" testId="audit-open" />
        </div>
      )}>
      {err ? (
        <Notice tone="danger" title="Papan temuan gagal dimuat" testId="audit-board-error">{err}</Notice>
      ) : !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground" data-testid="audit-board-loading">Memuat papan temuan…</p>
      ) : (<>
        <TabelData kolom={kolom} baris={rows} onKlikBaris={setDetail} testId="audit-findings-table"
          kosong={<EmptyState title="Tidak ada temuan yang cocok" description="Ubah saringan atau kata pencarian." />} />
        <p className="text-xs text-muted-foreground">
          Sumber: {(data.sumber || []).length} dokumen temuan & rencana perbaikan.{' '}
          <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setLihatSumber(true)} data-testid="audit-sumber">
            <FileText />Lihat sumber
          </Button>
        </p>
      </>)}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={`${detail.id} · ${detail.judul}`} testId="audit-detail"
          status={<><StatusBadge status={detail.status} label={metaStatus(detail.status).label} tone={metaStatus(detail.status).tone} />
            <StatusBadge status={detail.tingkat} label={detail.tingkat} tone={TINGKAT_TONE[detail.tingkat] || 'default'} /></>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Portal">{namaPortal(detail.portal)}</BarisDetail>
            <BarisDetail label="Perbaikan">{detail.perbaikan || '—'}</BarisDetail>
            <BarisDetail label="Berkas diubah"><span className="break-words font-mono text-xs">{detail.berkas || '—'}</span></BarisDetail>
            <BarisDetail label="Diuji">{detail.iterasi ? `Iterasi ${detail.iterasi}` : '—'}</BarisDetail>
          </dl>
        </DetailPopup>
      )}
      {lihatSumber && (
        <DetailPopup open onClose={() => setLihatSumber(false)} judul="Sumber papan temuan" testId="audit-sumber-popup"
          keterangan="Dokumen temuan dan rencana perbaikan yang menjadi dasar papan ini.">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {(data?.sumber || []).map((s) => <li key={s} className="break-all font-mono text-xs">{s}</li>)}
          </ul>
        </DetailPopup>
      )}
    </PageLayout>
  );
}
