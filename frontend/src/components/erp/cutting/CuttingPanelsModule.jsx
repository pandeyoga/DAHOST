/**
 * CuttingPanelsModule — Master Potongan (kain pola) hasil cutting.
 *
 * Ini BUKAN master material baru yang terpisah: isinya adalah dokumen
 * `rahaza_materials` bertanda `is_cut_panel`, jadi item yang tampil di sini
 * juga tampil di Master Item Gudang, dropdown BOM, dan Pengeluaran Material.
 * Layar ini hanya menyaringnya supaya tim cutting/gudang mudah melihat
 * stok potongan per style/warna/size beserta kain asalnya.
 *
 * SESI #32: NILAI (HPP/pcs, nilai persediaan, status nilai) + potongan YATIM yang bisa dibersihkan
 * (hanya yang terbukti belum pernah dipakai).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, tabel standar berhalaman (dulu 596 baris sekaligus) yang bisa
 * diunduh, Bersihkan = konfirmasi. Status nilai "standar" (biaya standar dari BOM, belum dari cutting nyata)
 * kini tampil apa adanya — dulu terbaca "belum bernilai" padahal kartu "Belum bernilai" = 0.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Package, RefreshCw, Scissors, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { cuttingApi, fmtNum, fmtRp, fmtDate } from './cuttingApi';

const VALUE_BADGE = {
  valued: { text: 'Bernilai', tone: 'success' },
  standard: { text: 'Biaya standar', tone: 'info' },
  unvalued: { text: 'Belum bernilai', tone: 'warning' },
};
const statusNilai = (m) => m.value_status || (Number(m.unit_cost || 0) > 0 ? 'valued' : 'unvalued');
const nilaiBaris = (m) => Number(m.stock_value ?? (Number(m.stock_qty || 0) * Number(m.unit_cost || 0)));

export default function CuttingPanelsModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');
  const [health, setHealth] = useState(null);
  const [cleaning, setCleaning] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setErr('');
    try {
      const [list, h] = await Promise.all([
        cuttingApi('GET', '/output-materials', token),
        cuttingApi('GET', '/panels/health', token).catch(() => null),
      ]);
      setRows(Array.isArray(list) ? list : []);
      setHealth(h);
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return rows;
    return rows.filter((r) =>
      [r.code, r.name, r.color, r.style_name, r.style_sku, r.source_material_code, r.cutting_order_number]
        .filter(Boolean).some((v) => String(v).toLowerCase().includes(s)));
  }, [rows, q]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);

  const totalStock = filtered.reduce((a, r) => a + Number(r.stock_qty || 0), 0);
  const totalValue = filtered.reduce((a, r) => a + nilaiBaris(r), 0);
  const unvaluedCount = filtered.filter((r) => statusNilai(r) === 'unvalued').length;
  const standardCount = filtered.filter((r) => statusNilai(r) === 'standard').length;
  const disaring = !!q.trim();

  const orphans = useMemo(() => (health?.items || []).filter((r) => r.orphan), [health]);
  const cleanable = orphans.filter((r) => r.cleanable);

  const runCleanup = async () => {
    if (!(await confirmDialog({
      title: `Bersihkan ${cleanable.length} master potongan yatim?`,
      body: 'Hanya master yang belum pernah dipakai (stok 0, tanpa kartu stok, tidak dirujuk dokumen) yang dihapus. Yang masih dipakai dipertahankan.',
      confirmLabel: 'Ya, bersihkan', danger: true,
    }))) return;
    setCleaning(true);
    try {
      const res = await cuttingApi('POST', '/panels/cleanup', token, { ids: cleanable.map((r) => r.id) });
      if (res.removed) toast.success(`${res.removed} master potongan yatim dibersihkan.`);
      else toast.info('Tidak ada yang bisa dibersihkan — semuanya masih dipakai.');
      if (res.kept) toast.warning(`${res.kept} dipertahankan karena masih dipakai (lihat alasannya).`);
      await load();
    } catch (e) {
      toast.error(`Gagal membersihkan: ${e.message}`);
    } finally {
      setCleaning(false);
    }
  };

  const kolom = [
    { kunci: 'code', label: 'Kode potongan', hp: 'judul', isi: (m) => (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className="tabular-nums font-medium text-foreground">{m.code}</span>
        {m.orphan && <span title={m.orphan_reason_text || 'yatim'}><StatusBadge status="yatim" label="Yatim" tone="warning" /></span>}
      </span>) },
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (m) => m.name },
    { kunci: 'varian', label: 'Warna / ukuran', isi: (m) => <span className="text-muted-foreground">{m.color || '—'}{m.size ? ` · ${m.size}` : ''}</span> },
    { kunci: 'asal', label: 'Kain asal', hp: false, isi: (m) => <span className="tabular-nums text-muted-foreground">{m.source_material_code || '—'}</span> },
    { kunci: 'order', label: 'Order cutting', hp: false, isi: (m) => <span className="tabular-nums text-muted-foreground">{m.cutting_order_number || '—'}</span> },
    { kunci: 'stok', label: 'Stok', rata: 'kanan', isi: (m) => <span className="tabular-nums font-medium whitespace-nowrap">{fmtNum(m.stock_qty)} pcs</span> },
    { kunci: 'hpp', label: 'HPP / pcs', rata: 'kanan', isi: (m) => (Number(m.unit_cost || 0) > 0
      ? <span className="tabular-nums whitespace-nowrap">{fmtRp(m.unit_cost)}</span>
      : <span className="text-xs text-muted-foreground">Belum ada</span>) },
    { kunci: 'nilai', label: 'Nilai', rata: 'kanan', hp: false, isi: (m) => (
      <span className="tabular-nums font-semibold whitespace-nowrap" data-testid={`cutting-panels-value-${m.code}`}>{fmtRp(nilaiBaris(m))}</span>) },
    { kunci: 'status', label: 'Status nilai', isi: (m) => {
      const b = VALUE_BADGE[statusNilai(m)] || VALUE_BADGE.unvalued;
      return (
        <span title={m.value_note || (statusNilai(m) === 'unvalued' ? 'Harga kain asalnya belum ada — nilai belum bisa dihitung' : undefined)}>
          <StatusBadge status={statusNilai(m)} label={b.text} tone={b.tone} />
        </span>
      );
    } },
    { kunci: 'dibuat', label: 'Dibuat', hp: false, isi: (m) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(m.created_at)}</span> },
  ];

  return (
    <PageLayout testId="cutting-panels-module" title="Master Potongan"
      subtitle="Item material hasil cutting (kain pola), siap dipakai sebagai BOM produksi dan dikirim ke CMT."
      actions={<Button variant="outline" onClick={() => onNavigate?.('cutting-orders')} data-testid="cutting-panels-goto-orders">
        <Scissors />Order cutting
      </Button>}
      filters={<div className="relative w-full sm:w-64">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode, style, warna, kain asal"
          className="pl-8" data-testid="cutting-panels-search" />
      </div>}
      tools={<>
        <TombolUnduh namaBerkas="master-potongan" namaLembar="Master potongan" baris={filtered} testId="cutting-panels-unduh"
          kolom={[
            { label: 'Kode potongan', nilai: (m) => m.code }, { label: 'Nama', nilai: (m) => m.name },
            { label: 'Warna', nilai: (m) => m.color || '' }, { label: 'Ukuran', nilai: (m) => m.size || '' },
            { label: 'Kain asal', nilai: (m) => m.source_material_code || '' },
            { label: 'Order cutting', nilai: (m) => m.cutting_order_number || '' },
            { label: 'Stok (pcs)', nilai: (m) => Number(m.stock_qty || 0) },
            { label: 'HPP / pcs', nilai: (m) => Number(m.unit_cost || 0) },
            { label: 'Nilai', nilai: (m) => nilaiBaris(m) },
            { label: 'Status nilai', nilai: (m) => (VALUE_BADGE[statusNilai(m)] || VALUE_BADGE.unvalued).text },
            { label: 'Keterangan nilai', nilai: (m) => m.value_note || '' },
            { label: 'Yatim', nilai: (m) => (m.orphan ? 'Ya' : 'Tidak') },
            { label: 'Dibuat', nilai: (m) => fmtDate(m.created_at) },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="cutting-panels-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {err && <Notice tone="danger" icon={AlertTriangle}>{err}</Notice>}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Jenis potongan" value={fmtNum(filtered.length)}
            sub={disaring ? `Sesuai pencarian · dari ${fmtNum(rows.length)}` : 'Semua master potongan aktif'} />
          <StatTile label="Total stok potongan" value={`${fmtNum(totalStock)} pcs`} sub={disaring ? 'Sesuai pencarian' : 'Semua gudang'} />
          <StatTile label="Nilai persediaan" value={fmtRp(totalValue)} testId="cutting-panels-total-value"
            sub="Stok × HPP hasil potong" />
          <StatTile label="Belum bernilai" value={fmtNum(unvaluedCount)} accent={unvaluedCount ? 'warning' : 'default'}
            testId="cutting-panels-unvalued-count"
            sub={standardCount ? `${fmtNum(standardCount)} lain memakai biaya standar BOM` : 'Harga kain asalnya belum ada'} />
        </div>
        {orphans.length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="cutting-panels-orphan-card"
            title={`${orphans.length} master potongan yatim`}
            action={<Button variant="destructive" size="sm" onClick={runCleanup} disabled={cleaning || !cleanable.length}
              title={cleanable.length ? 'Hapus master potongan yang belum pernah dipakai' : 'Tidak ada yang bisa dibersihkan — semuanya masih dipakai'}
              data-testid="cutting-panels-cleanup-btn">
              <Trash2 />Bersihkan yang aman ({cleanable.length})
            </Button>}>
            <p>
              Order cutting atau kain asalnya sudah tidak ada (biasanya sisa uji atau order batal). Yang masih berstok
              tidak dihapus supaya stok tidak jadi hantu; alasannya ada per baris.
            </p>
            <div className="mt-2 overflow-x-auto">
              <Table data-testid="cutting-panels-orphan-table">
                <TableHeader><TableRow>
                  <TableHead>Kode</TableHead><TableHead>Alasan yatim</TableHead><TableHead>Kain asal</TableHead>
                  <TableHead className="text-right">Stok</TableHead><TableHead className="text-right">Nilai</TableHead>
                  <TableHead>Bisa dibersihkan?</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {orphans.map((r) => (
                    <TableRow key={r.id} data-testid={`cutting-panels-orphan-row-${r.code}`}>
                      <TableCell className="tabular-nums">{r.code}</TableCell>
                      <TableCell>{r.reason_text}</TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">{r.source_material_code || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(r.stock_qty)} {r.unit || 'pcs'}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtRp(r.stock_value)}</TableCell>
                      <TableCell>{r.cleanable
                        ? <StatusBadge status="aman" label="Aman dihapus" tone="success" />
                        : <span className="text-[hsl(var(--warning-text))]">{r.block_reason || 'Masih dipakai'}</span>}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Notice>
        )}
      </>}
      footer={filtered.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && rows.length === 0 ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="cutting-panels-table"
          kosong={<EmptyState icon={Package} testId="cutting-panels-empty"
            title={rows.length ? 'Tidak ada potongan yang cocok' : 'Belum ada master potongan'}
            description={rows.length ? 'Ubah kata pencarian.' : 'Item potongan otomatis dibuat saat sebuah order cutting dimulai.'} />} />
      )}
    </PageLayout>
  );
}
