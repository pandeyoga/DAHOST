/**
 * Tab "Kiriman" — daftar kiriman ke CMT (Tahap 9, 7 Nov 2026). PageLayout + tabel + rincian di halaman.
 * Kiriman tambahan/pengganti tampil di bawah kiriman induknya (RowDetail), bukan baris terpisah.
 * Disaring per portal: Portal Produksi = PO internal, Portal Maklon = PO maklon.
 */
import { useCallback, useEffect, useState } from 'react';
import { BookOpen, Download, Plus, RefreshCw, Search, Truck } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { ambilSemuaHalaman } from '../DataTable';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite from '@/components/ui/pagination-lite';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { apiFetch, apiGet } from '../../../../lib/api';
import PageLayout, { RowDetail, RowToggle } from '../../layout/PageLayout';
import { PageLayoutSatuBaris } from '../DataTable';
import { EmptyState, Notice } from '../../moduleAtoms';
import KirimanDetail, { downloadPdf } from './KirimanDetail';
import KirimanForm from './KirimanForm';
import { ShipStatusBadge, ShipTypeBadge, fmtDate, fmtNum } from './kirimShared';

const PER_PAGE = 25;

export default function KirimanTab({ portalId, userRole, hasPerm = () => false, onNavigate }) {
  const businessType = portalId === 'maklon' ? 'maklon' : portalId === 'production' ? 'internal' : null;
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(null);          // id kiriman yang dirinci
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState({});
  const canCreate = userRole === 'superadmin' || hasPerm('vendor_shipment.create') || hasPerm('shipment.create')
    || ['admin', 'admin_produksi', 'admin_maklon', 'supervisor_produksi', 'owner', 'manager', 'ppic'].includes(userRole);
  const canDelete = userRole === 'superadmin';

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const qs = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE), parent_only: '1' });
      if (businessType) qs.set('business_type', businessType);
      if (status) qs.set('status', status);
      if (search.trim()) qs.set('search', search.trim());
      const env = await apiGet(`/vendor-shipments?${qs}`);
      setRows(Array.isArray(env?.items) ? env.items : (Array.isArray(env) ? env : []));
      setTotal(env?.total ?? (Array.isArray(env) ? env.length : 0));
    } catch (e) { setError(e.message || 'Daftar kiriman gagal dimuat'); setRows([]); }
    finally { setLoading(false); }
  }, [businessType, page, status, search]);
  useEffect(() => { load(); }, [businessType, page, status]); // eslint-disable-line react-hooks/exhaustive-deps

  const [children, setChildren] = useState({});
  const toggle = async (r) => {
    const next = !expanded[r.id];
    setExpanded((x) => ({ ...x, [r.id]: next }));
    if (next && !children[r.id]) {
      try {
        const d = await apiGet(`/kirim-cmt/shipments/${r.id}`);
        setChildren((c) => ({ ...c, [r.id]: d.children || [] }));
      } catch (e) { toast.error(e.message || 'Kiriman anak gagal dimuat'); }
    }
  };
  const pcs = (r) => (r.items || []).reduce((t, i) => t + Number(i.qty_sent || 0), 0);
  // unduhan Excel daftar kiriman (fitur lama ImportExportPanel, jalur `/export-excel?type=vendor-shipments` yang sama)
  const exportExcel = async () => {
    try {
      const res = await apiFetch('/export-excel?type=vendor-shipments');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement('a');
      a.href = url; a.download = `kiriman_cmt_${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) { toast.error(`Unduh gagal: ${e.message}`); }
  };
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <PageLayoutSatuBaris
      testId="kirim-kiriman"
      title="Kirim ke CMT"
      subtitle="Potongan & aksesoris keluar gudang otomatis saat kiriman dibuat; angkanya sama dengan surat jalan."
      actions={canCreate && (
        <Button type="button" onClick={() => { setOpen(null); setCreating(true); }} data-testid="kirim-new"><Plus className="w-4 h-4" />Kiriman baru</Button>
      )}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari kiriman, vendor, PO (Enter)"
            onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); load(); } }} className="pl-8" data-testid="kirim-search" />
        </div>
        <SmartNativeSelect value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }} className="w-44"
          aria-label="Status kiriman" data-testid="kirim-status-filter">
          <option value="">Semua status</option>
          <option value="Sent">Dikirim</option>
          <option value="Received">Diterima CMT</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <Button type="button" title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} data-testid="kirim-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
        {/* Standar UI/UX v2: unduh daftar (Excel/CSV, SEMUA kiriman hasil saringan) + unduh lama per baris barang (server). */}
        <TombolUnduh namaBerkas="kiriman-ke-cmt" namaLembar="Kiriman" baris={rows} testId="kirim-unduh"
          ambilSemua={() => ambilSemuaHalaman(({ page: pg, per_page }) => {
            const qs = new URLSearchParams({ page: String(pg), per_page: String(per_page), parent_only: '1' });
            if (businessType) qs.set('business_type', businessType);
            if (status) qs.set('status', status);
            if (search.trim()) qs.set('search', search.trim());
            return apiGet(`/vendor-shipments?${qs}`);
          })}
          kolom={[
            { label: 'No. kiriman', nilai: (r) => r.shipment_number }, { label: 'Vendor CMT', nilai: (r) => r.vendor_name || '' },
            { label: 'PO', nilai: (r) => r.po_number || '' }, { label: 'Tanggal', nilai: (r) => fmtDate(r.shipment_date) },
            { label: 'Jenis', nilai: (r) => r.shipment_type || '' }, { label: 'Pcs', nilai: (r) => pcs(r) },
            { label: 'Pcs tambahan', nilai: (r) => Number(r.child_qty_total) || 0 },
            { label: 'Pengeluaran gudang', nilai: (r) => r.material_issue_number || (r.opening ? 'saldo awal' : '') },
            { label: 'Status', nilai: (r) => (r.status === 'Received' ? 'Diterima CMT' : r.status === 'Sent' ? 'Dikirim' : (r.status || '')) },
          ]} />
        <Button type="button" variant="outline" onClick={exportExcel} data-testid="kirim-export" title="Excel dari server: satu baris per barang, semua kiriman">
          <Download className="w-4 h-4" />Unduh per barang</Button>
      </>}
      summary={error && <Notice tone="danger" title="Gagal memuat data" testId="kirim-error">{error}</Notice>}
      detail={creating ? (
        <KirimanForm businessType={businessType} onNavigate={onNavigate} onClose={() => setCreating(false)}
          onSaved={(data) => { setCreating(false); setPage(1); load(); setOpen(data.id); }} />
      ) : open && (
        <KirimanDetail id={open} canDelete={canDelete} onClose={() => setOpen(null)} onOpen={setOpen} onNavigate={onNavigate}
          onChanged={load} />
      )}
      footer={total > PER_PAGE && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={PER_PAGE} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground"><RefreshCw className="w-4 h-4 animate-spin inline mr-2" />Memuat kiriman…</div>
        ) : (
          <Table data-testid="kirim-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>No. kiriman</TableHead><TableHead>Vendor CMT</TableHead><TableHead>PO</TableHead>
              <TableHead>Tanggal</TableHead><TableHead>Jenis</TableHead><TableHead className="text-right">Pcs</TableHead>
              <TableHead>Pengeluaran gudang</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={10} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Truck} title={search || status ? 'Tidak ada kiriman yang cocok' : 'Belum ada kiriman ke CMT'}
                      description={search || status ? 'Ubah atau hapus penyaring.' : 'Buat kiriman pertama: pilih vendor CMT dan PO.'}
                      testId="kirim-empty" />
                  </TableCell>
                </TableRow>
              )}
              {rows.map((r) => [
                <TableRow key={r.id} data-testid={`kirim-row-${r.shipment_number}`}
                  className={open === r.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell>{r.child_shipment_count > 0 && (
                    <RowToggle open={!!expanded[r.id]} onClick={() => toggle(r)} label="Lihat kiriman tambahan"
                      testId={`kirim-row-toggle-${r.shipment_number}`} />)}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    <Button type="button" variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => { setCreating(false); setOpen(r.id); }}
                      data-testid={`kirim-open-${r.shipment_number}`}>{r.shipment_number}</Button>
                  </TableCell>
                  <TableCell>{r.vendor_name || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{r.po_number || '—'}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap">{fmtDate(r.shipment_date)}</TableCell>
                  <TableCell><ShipTypeBadge type={r.shipment_type} /></TableCell>
                  <TableCell className="text-right tabular-nums">
                    {fmtNum(pcs(r))}
                    {r.child_qty_total > 0 && <span className="block text-xs text-muted-foreground">+{fmtNum(r.child_qty_total)} tambahan</span>}
                  </TableCell>
                  <TableCell className="text-xs whitespace-nowrap">{r.material_issue_number
                    || <span className="text-muted-foreground">{r.opening ? 'saldo awal' : '—'}</span>}</TableCell>
                  <TableCell><ShipStatusBadge status={r.status} /></TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <Button type="button" variant="ghost" size="icon-sm" title="Surat jalan (PDF)" aria-label="Surat jalan (PDF)"
                      onClick={() => downloadPdf('vendor-shipment', r.id, `SJ-${r.shipment_number}.pdf`, 'Surat jalan')}>
                      <Download className="w-4 h-4" /></Button>
                    {/* Panduan produk (PDF) ada di popup rincian — paling banyak 2 aksi tampil per baris. */}
                    <Button type="button" variant="outline" size="sm" onClick={() => { setCreating(false); setOpen(r.id); }}>Rincian</Button>
                  </TableCell>
                </TableRow>,
                expanded[r.id] && (
                  <RowDetail key={`${r.id}-kids`} colSpan={10} testId={`kirim-row-detail-${r.shipment_number}`}>
                    {!(children[r.id] || []).length ? <p className="text-xs text-muted-foreground">Memuat…</p> : (
                      <div className="space-y-1">
                        {children[r.id].map((c) => (
                          <div key={c.id} className="flex flex-wrap items-center gap-3 text-sm">
                            <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => { setCreating(false); setOpen(c.id); }}>
                              {c.shipment_number}</Button>
                            <ShipTypeBadge type={c.shipment_type} />
                            <span className="text-xs text-muted-foreground">{fmtDate(c.shipment_date)} · {fmtNum(c.total_pcs)} pcs</span>
                            <ShipStatusBadge status={c.status} />
                            {c.material_issue_number && <span className="text-xs text-muted-foreground">{c.material_issue_number}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </RowDetail>
                ),
              ])}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayoutSatuBaris>
  );
}
