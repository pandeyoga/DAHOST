/**
 * VendorSerialTracking — Lacak nomor seri (Portal Vendor CMT; juga di Input atas nama CMT).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, saringan status = FilterChips, daftar = tabel, jejak satu nomor seri
 * dibuka sebagai popup, bisa diunduh. Dulu tiga "kartu angka" juga berfungsi sebagai saringan dan angkanya dihitung
 * dari daftar yang SUDAH disaring (saat memilih "Ongoing", angka "Selesai" selalu 0) — diganti satu kalimat jumlah
 * yang tampil. API sama: GET /serial-list?status&search, GET /serial-trace?serial.
 */
import { useEffect, useState } from 'react';
import { Eye, Hash, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';

const STATUS = { ongoing: ['Berjalan', 'info'], completed: ['Selesai', 'success'] };
const statusSeri = (s) => STATUS[s] || ['Menunggu', 'warning'];
const n = (v) => Number(v || 0).toLocaleString('id-ID');

export default function VendorSerialTracking() {
  const [serialList, setSerialList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [detail, setDetail] = useState(null);
  const [traceData, setTraceData] = useState(null);

  const fetchSerials = async () => {
    setLoading(true);
    try {
      let url = `/serial-list?status=${filter}`;
      if (search) url += `&search=${encodeURIComponent(search)}`;
      const d = await apiGet(url);
      setSerialList(Array.isArray(d) ? d : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchSerials(); }, [filter]);
  useEffect(() => { const t = setTimeout(fetchSerials, 400); return () => clearTimeout(t); }, [search]);

  const bukaJejak = async (s) => {
    setDetail(s); setTraceData(null);
    try { setTraceData(await apiGet(`/serial-trace?serial=${encodeURIComponent(s.serial_number)}`)); }
    catch (e) { setTraceData({ timeline: [] }); }
  };

  const kolom = [
    { kunci: 'seri', label: 'No. seri', hp: 'judul', isi: (s) => <span className="font-medium tabular-nums">{s.serial_number}</span> },
    { kunci: 'produk', label: 'Produk', hp: 'keterangan', isi: (s) => <span className="text-sm">{s.product_name} · {s.sku} · {s.size}/{s.color}</span> },
    { kunci: 'order', label: 'Order', rata: 'kanan', isi: (s) => <span className="tabular-nums">{n(s.ordered_qty)}</span> },
    { kunci: 'produksi', label: 'Produksi', rata: 'kanan', isi: (s) => <span className="tabular-nums">{n(s.produced_qty)}</span> },
    { kunci: 'kirim', label: 'Kirim', rata: 'kanan', isi: (s) => <span className="tabular-nums">{n(s.shipped_qty)}</span> },
    { kunci: 'status', label: 'Status', isi: (s) => { const [l, t] = statusSeri(s.status); return <StatusBadge status={s.status} label={l} tone={t} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <Button size="icon-sm" variant="ghost" onClick={() => bukaJejak(s)} title="Lihat jejak" aria-label="Lihat jejak"><Eye className="w-4 h-4" /></Button>) },
  ];

  return (
    <PageLayout testId="vendor-serial-tracking" title="Lacak nomor seri"
      subtitle="Jejak tiap nomor seri: order, produksi, dan kiriman."
      filters={<>
        <FilterChips value={filter} onChange={setFilter} hideWhenEmpty={false} ariaLabel="Saring status" testId="vendor-serial-filter"
          options={[{ key: 'all', label: 'Semua' }, { key: 'ongoing', label: 'Berjalan' }, { key: 'completed', label: 'Selesai' }]} />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nomor seri" className="pl-8" data-testid="vendor-serial-search" />
        </div>
      </>}
      tools={<TombolUnduh namaBerkas="lacak-nomor-seri" baris={serialList} kolom={[
        { label: 'No. seri', nilai: (s) => s.serial_number }, { label: 'Produk', nilai: (s) => s.product_name || '' },
        { label: 'SKU', nilai: (s) => s.sku || '' }, { label: 'Ukuran', nilai: (s) => s.size || '' }, { label: 'Warna', nilai: (s) => s.color || '' },
        { label: 'PO', nilai: (s) => s.po_number || '' }, { label: 'Order', nilai: (s) => Number(s.ordered_qty) || 0 },
        { label: 'Produksi', nilai: (s) => Number(s.produced_qty) || 0 }, { label: 'Kirim', nilai: (s) => Number(s.shipped_qty) || 0 },
        { label: 'Sisa', nilai: (s) => Number(s.remaining_qty) || 0 }, { label: 'Status', nilai: (s) => statusSeri(s.status)[0] },
      ]} />}
      summary={!loading && <p className="text-sm text-muted-foreground">{n(serialList.length)} nomor seri tampil.</p>}>
      {loading ? <p className="py-10 text-center text-sm text-muted-foreground">Memuat nomor seri…</p> : (
        <TabelData kolom={kolom} baris={serialList} kunci={(s) => `${s.serial_number}-${s.po_id}`} onKlikBaris={bukaJejak}
          testId="vendor-serial-table" kosong={<EmptyState icon={Hash} title="Tidak ada nomor seri" description="Ubah saringan atau kata pencarian." />} />
      )}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={`Nomor seri ${detail.serial_number}`} testId="vendor-serial-detail"
          status={(() => { const [l, t] = statusSeri(detail.status); return <StatusBadge status={detail.status} label={l} tone={t} />; })()}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Produk">{detail.product_name} · {detail.sku} · {detail.size}/{detail.color}</BarisDetail>
            <BarisDetail label="PO">{detail.po_number || '—'}</BarisDetail>
            <BarisDetail label="Pelanggan">{detail.customer_name || '—'}</BarisDetail>
            <BarisDetail label="Status PO">{detail.po_status || '—'}</BarisDetail>
            <BarisDetail label="Sisa">{n(detail.remaining_qty)} pcs</BarisDetail>
          </dl>
          <section className="space-y-1">
            <p className="text-sm font-semibold text-foreground">Jejak (10 kejadian terakhir)</p>
            {!traceData ? <p className="text-sm text-muted-foreground">Memuat jejak…</p> : (traceData.timeline || []).length === 0 ? (
              <p className="text-sm text-muted-foreground">Belum ada kejadian.</p>
            ) : (
              <ul className="divide-y divide-[var(--glass-border)] text-sm">
                {traceData.timeline.slice(0, 10).map((ev, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-x-3 py-1.5">
                    <span className="font-medium">{ev.step}</span>
                    {ev.qty > 0 && <span className="tabular-nums text-muted-foreground">Qty {n(ev.qty)}</span>}
                    <span className="ml-auto text-muted-foreground">{formatDateID(ev.date, { fallback: '—' })}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </DetailPopup>
      )}
    </PageLayout>
  );
}
