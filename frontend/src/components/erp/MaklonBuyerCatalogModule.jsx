/**
 * MaklonBuyerCatalogModule — tab "Katalog" di menu Klien & Katalog Buyer (Portal Maklon).
 * Master artikel buyer: spesifikasi, harga bawaan, varian SKU, templat BOM, panduan produksi.
 *
 * Tahap 9 (7 Nov 2026, keputusan owner "menu & tampilan dua portal identik"):
 *   • Cetakan PageLayout + TABEL (cari, penyaring buyer & status, halaman) — dulu kartu angka warna-warni,
 *     kartu penyaring, dan satu kartu per artikel.
 *   • Rincian artikel (maklon/KatalogArtikelDetail): ringkasan + riwayat sampel, varian SKU, riwayat harga, templat BOM.
 *   • Standar UI/UX v2 (8 Nov 2026): rincian = popup, artikel baru/ubah = FormPopup, tabel bisa diunduh, cari ± 16 rem.
 *   • Panduan produksi (SOP) tetap editor yang sama (ProductionGuideDialog) — dibuka dari rincian artikel.
 *
 *   GET /api/dewi/maklon/buyer-catalog?client_id&status&search · GET /api/dewi/maklon/clients
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, Plus, RefreshCw, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { apiGet, getToken } from '../../lib/api';
import { formatRupiah } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice } from './moduleAtoms';
import ProductionGuideDialog from './ProductionGuideDialog';
import KatalogArtikelForm, { ARTIKEL_STATUS } from './maklon/KatalogArtikelForm';
import KatalogArtikelDetail, { ArtikelStatusBadge } from './maklon/KatalogArtikelDetail';

const fmtRp = (v) => formatRupiah(v || 0);

export default function MaklonBuyerCatalogModule({ token, onNavigate }) {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [clientId, setClientId] = useState('');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [panel, setPanel] = useState(null); // {mode:'view'|'edit', id} | {mode:'new'}
  const [sopFor, setSopFor] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const qs = new URLSearchParams();
      if (clientId) qs.append('client_id', clientId);
      if (search.trim()) qs.append('search', search.trim());
      qs.append('limit', '500');
      const d = await apiGet(`/dewi/maklon/buyer-catalog?${qs}`);
      setItems(Array.isArray(d) ? d : []);
    } catch (e) { setError(e.message || 'Gagal memuat Katalog Buyer'); setItems([]); }
    finally { setLoading(false); }
  }, [clientId, search]);
  useEffect(() => { apiGet('/dewi/maklon/clients').then((d) => setClients(Array.isArray(d) ? d : [])).catch(() => {}); }, []);
  useEffect(() => { const t = setTimeout(load, search ? 300 : 0); return () => clearTimeout(t); }, [load]); // eslint-disable-line react-hooks/exhaustive-deps

  const counts = useMemo(() => ({
    all: items.length, active: items.filter((x) => x.status === 'active').length,
    inactive: items.filter((x) => x.status === 'inactive').length, discontinued: items.filter((x) => x.status === 'discontinued').length,
  }), [items]);
  const filtered = useMemo(() => (status ? items.filter((x) => x.status === status) : items), [items, status]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);
  const current = panel?.id ? items.find((x) => x.id === panel.id) : null;
  const afterSave = async (id) => { await load(); setPanel(id ? { mode: 'view', id } : null); };
  const resetFilters = () => { setClientId(''); setStatus(''); setSearch(''); };
  const openRnd = onNavigate ? () => onNavigate('rnd-master-product-hub') : null;

  let detail = null;
  if (panel?.mode === 'new') detail = <KatalogArtikelForm clients={clients} onCancel={() => setPanel(null)} onSaved={afterSave} onOpenRnd={openRnd} />;
  else if (panel?.mode === 'edit' && current) {
    detail = <KatalogArtikelForm data={current} clients={clients} onCancel={() => setPanel({ mode: 'view', id: current.id })} onSaved={afterSave} onOpenRnd={openRnd} />;
  } else if (panel?.mode === 'view' && current) {
    detail = <KatalogArtikelDetail catalog={current} onClose={() => setPanel(null)} onEdit={() => setPanel({ mode: 'edit', id: current.id })}
      onSop={() => setSopFor(current)} onChanged={afterSave} />;
  }

  return (
    <PageLayout testId="maklon-buyer-catalog-module" title="Katalog buyer"
      subtitle="Artikel klien maklon: spesifikasi, harga bawaan, varian SKU, templat BOM, dan riwayat sampel."
      actions={<Button onClick={() => setPanel({ mode: 'new' })} data-testid="buyer-catalog-add-btn"><Plus className="w-4 h-4" />Artikel baru</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari kode artikel, kode buyer, nama"
            className="pl-8" data-testid="buyer-catalog-search-input" />
        </div>
        <SmartNativeSelect value={clientId} onChange={(e) => setClientId(e.target.value)} className="h-9 w-48" wrapperClassName="w-48"
          data-testid="buyer-catalog-filter-client" aria-label="Buyer">
          <option value="">Semua buyer</option>
          {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </SmartNativeSelect>
        <FilterChips value={status} onChange={setStatus} testId="buyer-catalog-filter-status" ariaLabel="Status artikel"
          options={[{ key: '', label: 'Semua', count: counts.all }, { key: 'active', label: 'Aktif', count: counts.active },
            { key: 'inactive', label: 'Nonaktif', count: counts.inactive }, { key: 'discontinued', label: 'Dihentikan', count: counts.discontinued }]} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="katalog-buyer" namaLembar="Katalog buyer" baris={filtered} testId="buyer-catalog-unduh"
          kolom={[
            { label: 'Kode artikel', nilai: (it) => it.artikel_code || '' }, { label: 'Kode buyer', nilai: (it) => it.buyer_ref_code || '' },
            { label: 'Nama produk', nilai: (it) => it.product_name || '' }, { label: 'Buyer', nilai: (it) => it.client_name || '' },
            { label: 'Kategori', nilai: (it) => it.category || '' }, { label: 'Upah CMT', nilai: (it) => Number(it.default_cmt_price || 0) },
            { label: 'Harga jasa', nilai: (it) => Number(it.default_selling_price || 0) }, { label: 'Varian', nilai: (it) => (it.variants || []).length },
            { label: 'Produksi (pcs)', nilai: (it) => Number(it.total_qty_produced || 0) },
            { label: 'Status', nilai: (it) => ARTIKEL_STATUS[it.status] || it.status || '' },
          ]} />
        <Button size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="buyer-catalog-refresh-btn">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={error && <Notice tone="danger" title="Gagal memuat Katalog Buyer">{error}</Notice>}
      detail={sopFor ? null : detail /* panduan produksi menggantikan popup rincian sementara (tidak bertumpuk) */}
      footer={filtered.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      <GlassCard className="p-0 overflow-hidden">
        {loading && !items.length ? (
          <div className="p-4 text-sm text-muted-foreground">Memuat artikel…</div>
        ) : !paged.length ? (
          (clientId || status || search) ? (
            <EmptyState icon={BookOpen} title="Tidak ada artikel yang cocok" description="Ubah atau hapus penyaring untuk melihat artikel lain."
              action={<Button variant="outline" size="sm" onClick={resetFilters}><X className="w-3.5 h-3.5" />Tampilkan semua artikel</Button>} />
          ) : (
            <EmptyState icon={BookOpen} title="Belum ada artikel buyer"
              description="Buat artikel pertama untuk menyimpan spesifikasi & harga bawaan dari klien maklon." />
          )
        ) : (
          <Table data-testid="buyer-catalog-table">
            <TableHeader><TableRow>
              <TableHead>Artikel</TableHead><TableHead>Buyer</TableHead><TableHead>Kategori</TableHead>
              <TableHead className="text-right">Upah CMT</TableHead><TableHead className="text-right">Harga jasa</TableHead>
              <TableHead className="text-right">Varian</TableHead><TableHead className="text-right">Produksi (pcs)</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((it) => (
                <TableRow key={it.id} data-testid={`buyer-catalog-row-${it.id}`} className={panel?.id === it.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell>
                    <Button variant="link" size="sm" className="h-auto p-0 font-semibold text-left" onClick={() => setPanel({ mode: 'view', id: it.id })}
                      data-testid={`buyer-catalog-detail-${it.id}`}>{it.product_name}</Button>
                    <span className="block text-xs text-muted-foreground">{it.artikel_code}{it.buyer_ref_code ? ` · ${it.buyer_ref_code}` : ''}</span>
                  </TableCell>
                  <TableCell className="text-sm">{it.client_name || '—'}</TableCell>
                  <TableCell className="text-sm">{it.category || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(it.default_cmt_price)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{it.default_selling_price > 0 ? fmtRp(it.default_selling_price) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{(it.variants || []).length}</TableCell>
                  <TableCell className="text-right tabular-nums">{Number(it.total_qty_produced || 0).toLocaleString('id-ID')}</TableCell>
                  <TableCell><ArtikelStatusBadge status={it.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      {sopFor && (
        <ProductionGuideDialog entity={sopFor} token={token || getToken()}
          title={`Panduan produksi · ${sopFor.artikel_code || ''} — ${sopFor.product_name || ''}`}
          endpoints={{ sop: `/api/dewi/maklon/buyer-catalog/${sopFor.id}/sop`, sopImage: `/api/dewi/maklon/buyer-catalog/${sopFor.id}/sop-image` }}
          onClose={() => setSopFor(null)} onUpdated={load} />
      )}
    </PageLayout>
  );
}
