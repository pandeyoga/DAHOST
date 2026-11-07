/**
 * ProcurementTab — permintaan pengadaan + kotak persetujuan (saringan peran dari server).
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • tab di dalam tab ("Semua Request" / "Inbox Approval") → pil penyaring satu baris dengan angka;
 *  • daftar kartu berulang → tabel TabelData, klik baris membuka detail popup;
 *  • kotak penyaring abu + emoji pada pilihan → pilihan biasa di baris penyaring;
 *  • unduh Excel/CSV; daftar semua permintaan berhalaman (dulu diam-diam hanya 50 pertama).
 */
import { Plus, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite from '@/components/ui/pagination-lite';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, StatusBadge as Lencana } from '../../moduleAtoms';
import { PR_STATUS_CONFIG, PR_PRIORITY_LABEL } from '../constants';
import { angka, ambilSemuaHalaman, fmtCurrency, fmtDate, useHP } from '../utils';
import { StatusBadge } from '../components/StatusBadge';

const labelStatus = (s) => PR_STATUS_CONFIG[s]?.label || PR_STATUS_CONFIG[String(s || '').toLowerCase()]?.label || s || '';

const KOLOM_UNDUH = [
  { label: 'No. permintaan', nilai: (p) => p.request_number },
  { label: 'Judul', nilai: (p) => p.title },
  { label: 'Pemohon', nilai: (p) => p.requested_by_name || '' },
  { label: 'Departemen', nilai: (p) => p.department || '' },
  { label: 'Prioritas', nilai: (p) => PR_PRIORITY_LABEL[p.priority] || p.priority || '' },
  { label: 'Tanggal dibuat', nilai: (p) => fmtDate(p.created_at) },
  { label: 'Perkiraan total', nilai: (p) => angka(p.total_estimated) },
  { label: 'Status', nilai: (p) => labelStatus(p.status) },
];

export function ProcurementTab({
  prTab, setPrTab,
  prData, prInbox, prPagination, loading,
  prSearch, setPrSearch,
  loadPRs, fetchPRPage,
  onSelectPR, onBuatPR,
  isAdminLike,
  inboxScope, setInboxScope,
  inboxDept, setInboxDept,
  uniqueDepartments,
}) {
  const kotak = prTab === 'inbox';
  const hp = useHP();
  const halaman = prPagination?.page || 1;
  const muatUlang = () => loadPRs(kotak ? 1 : halaman);

  const kolomUmum = [
    { kunci: 'no', label: 'No. permintaan', hp: 'keterangan', isi: (p) => <span className="tabular-nums text-muted-foreground">{p.request_number}</span> },
    { kunci: 'judul', label: 'Judul', hp: 'judul', isi: (p) => (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className="font-medium">{p.title}</span>
        {kotak && p.can_approve === false && <Lencana status="muted" label="Hanya lihat" tone="muted" />}
        {kotak && p.kind_label && p.kind !== 'pr' && <Lencana status="info" label={p.kind_label} tone="info" />}
      </span>) },
    { kunci: 'pemohon', label: 'Pemohon', isi: (p) => p.requested_by_name || '—' },
    { kunci: 'dept', label: 'Departemen', isi: (p) => p.department || '—' },
    { kunci: 'tgl', label: 'Tanggal', isi: (p) => fmtDate(p.created_at) },
    { kunci: 'total', label: 'Perkiraan total', rata: 'kanan', isi: (p) => <span className="tabular-nums">{fmtCurrency(p.total_estimated)}</span> },
    { kunci: 'status', label: 'Status', isi: (p) => <StatusBadge status={p.status} configMap={PR_STATUS_CONFIG} /> },
  ];

  const pesanKosongKotak = inboxScope === 'mine'
    ? 'Anda belum memiliki permintaan yang menunggu persetujuan.'
    : inboxScope === 'all'
      ? 'Tidak ada permintaan yang menunggu persetujuan.'
      : 'Tidak ada permintaan yang menunggu persetujuan Anda.';

  // Alat dibungkus satu kelompok supaya Unduh & muat ulang tidak terpisah baris di HP.
  const alat = (
    <div className="flex items-center gap-2">
      {kotak ? (
        <TombolUnduh namaBerkas="pengadaan-menunggu-persetujuan" namaLembar="Menunggu persetujuan" baris={prInbox}
          kolom={[...KOLOM_UNDUH, { label: 'Bisa saya setujui', nilai: (p) => (p.can_approve === false ? 'Tidak' : 'Ya') }]}
          testId="inbox-unduh" />
      ) : (
        <TombolUnduh namaBerkas="permintaan-pengadaan" namaLembar="Permintaan pengadaan" baris={prData}
          kolom={KOLOM_UNDUH} testId="pr-unduh" ambilSemua={() => ambilSemuaHalaman(fetchPRPage)} />
      )}
      <Button variant="outline" size="icon" onClick={muatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
        data-testid={kotak ? 'inbox-refresh-btn' : 'pr-refresh-btn'}>
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </div>
  );

  return (
    <PageLayout testId="asset-procurement" title="Pengadaan" subtitle="Permintaan pengadaan dan persetujuannya."
      actions={<Button onClick={onBuatPR} data-testid="asset-pr-new-btn"><Plus />Buat permintaan</Button>}
      filters={<>
        <FilterChips value={prTab} onChange={setPrTab} hideWhenEmpty={false} testId="pr-view" ariaLabel="Tampilan"
          options={[
            { key: 'all', label: 'Semua permintaan', count: prPagination?.total ?? prData.length },
            { key: 'inbox', label: 'Menunggu persetujuan', count: prInbox.length },
          ]} />
        {!kotak ? (
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="Cari judul atau nomor" className="pl-8" value={prSearch}
              onChange={e => setPrSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && loadPRs(1)}
              data-testid="pr-search-input" />
          </div>
        ) : (
          <>
            <SmartNativeSelect value={inboxScope} onChange={e => setInboxScope(e.target.value)} searchable={false}
              className="w-56" aria-label="Tampilkan" data-testid="inbox-scope-select">
              <option value="relevant">Untuk saya (sesuai peran)</option>
              {isAdminLike && <option value="all">Semua yang menunggu</option>}
              <option value="mine">Permintaan saya</option>
            </SmartNativeSelect>
            {isAdminLike && uniqueDepartments.length > 0 && (
              <SmartNativeSelect value={inboxDept} onChange={e => setInboxDept(e.target.value)}
                className="w-48" aria-label="Departemen" data-testid="inbox-dept-select">
                <option value="">Semua departemen</option>
                {uniqueDepartments.map(d => <option key={d} value={d}>{d}</option>)}
              </SmartNativeSelect>
            )}
          </>
        )}
        {hp && alat}
      </>}
      tools={hp ? null : alat}
      footer={!kotak && prPagination?.total > 0 ? (
        <PaginationLite page={halaman} totalPages={prPagination.total_pages} total={prPagination.total}
          pageSize={prPagination.page_size || 50} onPageChange={(p) => loadPRs(p)} />
      ) : null}>
      {kotak ? (
        <TabelData baris={prInbox} kolom={kolomUmum} onKlikBaris={onSelectPR} testId="inbox-table"
          kunci={(p) => `${p.kind || 'pr'}-${p.id}`}
          kosong={<EmptyState title="Kotak persetujuan kosong" description={pesanKosongKotak} testId="inbox-kosong" />} />
      ) : loading && prData.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat permintaan…</p>
      ) : (
        <TabelData baris={prData} kolom={kolomUmum} onKlikBaris={onSelectPR} testId="pr-table"
          kosong={<EmptyState title={prSearch ? 'Tidak ada permintaan yang cocok' : 'Belum ada permintaan pengadaan'}
            description={prSearch ? 'Ubah kata pencarian.' : 'Buat permintaan lewat tombol "Buat permintaan".'} />} />
      )}
    </PageLayout>
  );
}
