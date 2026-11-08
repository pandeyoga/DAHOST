/**
 * ProcurementSpendModule — Analisis Belanja Pengadaan
 *
 * Sumber: `/api/procurement/spend-analysis` (agregasi PO + master material).
 * Menjawab pertanyaan pembeli: uang habis ke supplier mana, kategori apa,
 * material apa, dan bagaimana trennya per bulan.
 *
 * Standar UI/UX v2 (8 Nov 2026, keluhan owner "visualisasi data macam apa ini?"): grafik batang tanpa
 * sumbu/angka jelas diganti TABEL ringkas yang menjawab satu pertanyaan per bagian (berapa rupiah, berapa
 * PO, berapa persen dari total), dengan bilah porsi kecil sebagai bantuan baca. Semua tabel bisa diunduh.
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { CATEGORY_LABEL, EP, apiGet, fmtNum, fmtRp } from './procApi';

const BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const labelBulan = (ym) => {
  const [y, m] = String(ym || '').split('-').map(Number);
  return y && m ? `${BULAN[m - 1]} ${y}` : (ym || '—');
};
const persen = (v, total) => (total > 0 ? (Number(v || 0) / total) * 100 : 0);
const fmtPersen = (p) => `${p.toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`;

/** Porsi: angka persen + bilah tipis (bantuan baca, bukan grafik terpisah). */
function Porsi({ p }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <div className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-[hsl(var(--muted))] sm:block" aria-hidden="true">
        <div className="h-full rounded-full bg-[hsl(var(--primary))]" style={{ width: `${Math.min(100, p)}%` }} />
      </div>
      <span className="w-12 text-right tabular-nums">{fmtPersen(p)}</span>
    </div>
  );
}

function Bagian({ judul, keterangan, alat, children, testId }) {
  return (
    <GlassCard className="p-4 space-y-3 min-w-0" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-foreground">{judul}</h3>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {alat && <div className="flex items-center gap-2">{alat}</div>}
      </div>
      {children}
    </GlassCard>
  );
}

export default function ProcurementSpendModule({ token }) {
  const [months, setMonths] = useState(6);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [semuaPemasok, setSemuaPemasok] = useState(false);
  const [semuaMaterial, setSemuaMaterial] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      setData(await apiGet(token, EP.spend(months)));
    } catch (e) {
      setErr(e.message);
      toast.error(`Gagal memuat analisis belanja: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [token, months]);

  useEffect(() => { load(); }, [load]);

  const total = Number(data?.total_value || 0);
  const poCount = data?.po_count ?? 0;
  const bySupplier = (data?.by_supplier || []).map((r) => ({
    ...r,
    _k: r.supplier_id || r.supplier_name,
    label: `${r.supplier_code ? `${r.supplier_code} · ` : ''}${r.supplier_name}`,
  }));
  const byMonth = (data?.by_month || []).map((m) => ({ ...m, _k: m.month, label: labelBulan(m.month) }));
  const byCategory = (data?.by_category || []).map((r) => ({
    ...r,
    _k: r.category,
    label: CATEGORY_LABEL[r.category] || (r.category === 'free_form' ? 'Item bebas / jasa' : r.category),
  }));
  // Kategori & material dihitung dari baris PO (qty × harga satuan) — dasarnya jumlah baris itu sendiri,
  // bukan total PO (yang bisa memuat pajak/ongkos), supaya persennya tetap 100% di tabel itu.
  const totalBaris = byCategory.reduce((s, r) => s + Number(r.value || 0), 0);
  const topMat = (data?.top_materials || []).map((r, i) => ({
    ...r,
    _k: r.material_id || `${r.material_name}-${i}`,
    label: `${r.material_code ? `${r.material_code} · ` : ''}${r.material_name}`,
  }));
  const periodeTeks = `${months} bulan terakhir`;

  const kolomRp = (label = 'Nilai') => ({
    kunci: 'nilai', label, rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtRp(r.value)}</span>,
  });

  return (
    <PageLayout testId="proc-spend-page" title="Analisis Belanja"
      subtitle="Ke mana uang pengadaan mengalir: per pemasok, per bulan, per kategori, dan material terbesar."
      filters={
        <SmartNativeSelect value={String(months)} onChange={(e) => setMonths(Number(e.target.value))}
          className="w-48" data-testid="proc-spend-months" aria-label="Periode">
          <option value="3">3 bulan terakhir</option>
          <option value="6">6 bulan terakhir</option>
          <option value="12">12 bulan terakhir</option>
          <option value="24">24 bulan terakhir</option>
        </SmartNativeSelect>
      }
      tools={
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang"
          aria-label="Muat ulang" data-testid="proc-spend-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }
      summary={!loading && poCount > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatTile label="Total belanja" value={fmtRp(total)} testId="proc-spend-total"
            sub={`Nilai PO ${periodeTeks}, tanpa draf, ditolak, atau dibatalkan`} />
          <StatTile label="Jumlah PO" value={poCount} sub={`PO bertanggal ${periodeTeks}`} />
          <StatTile label="Rata-rata per PO" value={fmtRp(total / poCount)} sub="Total belanja ÷ jumlah PO" />
        </div>
      )}>
      {err && <Notice tone="danger" title="Analisis belanja gagal dimuat">{err}</Notice>}

      {loading && !data ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-48 rounded-[var(--radius-lg)]" />)}
        </div>
      ) : poCount === 0 ? (
        !err && (
          <GlassCard>
            <EmptyState title={`Belum ada PO dalam ${periodeTeks}`} testId="proc-spend-empty"
              description="Analisis dihitung dari PO yang sudah diajukan (bukan draf, ditolak, atau dibatalkan). Coba periode yang lebih panjang." />
          </GlassCard>
        )
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Bagian judul="Belanja per pemasok" testId="proc-spend-by-supplier"
            keterangan="Pemasok dengan nilai PO terbesar dan porsinya dari total belanja."
            alat={
              <TombolUnduh namaBerkas={`belanja-per-pemasok-${months}-bulan`} namaLembar="Per pemasok" baris={bySupplier}
                testId="proc-spend-by-supplier-unduh"
                kolom={[
                  { label: 'Kode pemasok', nilai: (r) => r.supplier_code || '' },
                  { label: 'Pemasok', nilai: (r) => r.supplier_name },
                  { label: 'Jumlah PO', nilai: (r) => r.po_count },
                  { label: 'Nilai (Rp)', nilai: (r) => Number(r.value || 0) },
                  { label: 'Porsi (%)', nilai: (r) => Number(persen(r.value, total).toFixed(1)) },
                ]} />
            }>
            <TabelData baris={semuaPemasok ? bySupplier : bySupplier.slice(0, 10)} kunci={(r) => r._k}
              testId="proc-spend-by-supplier-table"
              kolom={[
                { kunci: 'pemasok', label: 'Pemasok', hp: 'judul', isi: (r) => <span className="line-clamp-1">{r.label}</span> },
                { kunci: 'po', label: 'PO', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.po_count}</span> },
                kolomRp(),
                { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (r) => <Porsi p={persen(r.value, total)} /> },
              ]} />
            {bySupplier.length > 10 && (
              <Button variant="link" size="sm" className="px-0" onClick={() => setSemuaPemasok((v) => !v)}>
                {semuaPemasok ? 'Tampilkan 10 teratas' : `Tampilkan semua (${bySupplier.length})`}
              </Button>
            )}
          </Bagian>

          <Bagian judul="Belanja per bulan" testId="proc-spend-monthly"
            keterangan="Nilai PO per bulan tanggal PO."
            alat={
              <TombolUnduh namaBerkas={`belanja-per-bulan-${months}-bulan`} namaLembar="Per bulan" baris={byMonth}
                testId="proc-spend-monthly-unduh"
                kolom={[
                  { label: 'Bulan', nilai: (r) => r.label },
                  { label: 'Jumlah PO', nilai: (r) => r.po_count },
                  { label: 'Nilai (Rp)', nilai: (r) => Number(r.value || 0) },
                  { label: 'Porsi (%)', nilai: (r) => Number(persen(r.value, total).toFixed(1)) },
                ]} />
            }>
            <TabelData baris={byMonth} kunci={(r) => r._k} testId="proc-spend-monthly-table"
              kolom={[
                { kunci: 'bulan', label: 'Bulan', hp: 'judul', isi: (r) => r.label },
                { kunci: 'po', label: 'PO', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.po_count}</span> },
                kolomRp(),
                { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (r) => <Porsi p={persen(r.value, total)} /> },
              ]} />
          </Bagian>

          <Bagian judul="Belanja per kategori" testId="proc-spend-by-category"
            keterangan="Dari baris PO (jumlah × harga satuan, tanpa pajak dan ongkos)."
            alat={
              <TombolUnduh namaBerkas={`belanja-per-kategori-${months}-bulan`} namaLembar="Per kategori" baris={byCategory}
                testId="proc-spend-by-category-unduh"
                kolom={[
                  { label: 'Kategori', nilai: (r) => r.label },
                  { label: 'Baris PO', nilai: (r) => r.lines },
                  { label: 'Nilai (Rp)', nilai: (r) => Number(r.value || 0) },
                  { label: 'Porsi (%)', nilai: (r) => Number(persen(r.value, totalBaris).toFixed(1)) },
                ]} />
            }>
            <TabelData baris={byCategory} kunci={(r) => r._k} testId="proc-spend-by-category-table"
              kolom={[
                { kunci: 'kategori', label: 'Kategori', hp: 'judul', isi: (r) => r.label },
                { kunci: 'baris', label: 'Baris PO', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.lines}</span> },
                kolomRp(),
                { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (r) => <Porsi p={persen(r.value, totalBaris)} /> },
              ]} />
          </Bagian>

          <Bagian judul="Material dengan belanja terbesar" testId="proc-spend-top-materials"
            keterangan="25 material teratas menurut nilai baris PO."
            alat={
              <TombolUnduh namaBerkas={`material-terbesar-${months}-bulan`} namaLembar="Material" baris={topMat}
                testId="proc-spend-top-materials-unduh"
                kolom={[
                  { label: 'Kode material', nilai: (r) => r.material_code || '' },
                  { label: 'Material', nilai: (r) => r.material_name },
                  { label: 'Jumlah dipesan', nilai: (r) => Number(r.qty_base || 0) },
                  { label: 'Satuan', nilai: (r) => r.base_uom || '' },
                  { label: 'Nilai (Rp)', nilai: (r) => Number(r.value || 0) },
                  { label: 'Porsi (%)', nilai: (r) => Number(persen(r.value, totalBaris).toFixed(1)) },
                ]} />
            }>
            <TabelData baris={semuaMaterial ? topMat : topMat.slice(0, 10)} kunci={(r) => r._k}
              testId="proc-spend-top-materials-table"
              kolom={[
                { kunci: 'material', label: 'Material', hp: 'judul', isi: (r) => <span className="line-clamp-1">{r.label}</span> },
                { kunci: 'qty', label: 'Jumlah dipesan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{`${fmtNum(r.qty_base)} ${r.base_uom || ''}`.trim()}</span> },
                kolomRp(),
                { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (r) => <Porsi p={persen(r.value, totalBaris)} /> },
              ]} />
            {topMat.length > 10 && (
              <Button variant="link" size="sm" className="px-0" onClick={() => setSemuaMaterial((v) => !v)}>
                {semuaMaterial ? 'Tampilkan 10 teratas' : `Tampilkan semua (${topMat.length})`}
              </Button>
            )}
          </Bagian>
        </div>
      )}
    </PageLayout>
  );
}
