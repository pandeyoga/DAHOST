/**
 * UtilizationReportTab — laporan pemakaian aset (hari ditugaskan ÷ hari dalam periode).
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • kotak penyaring berkartu dengan dua isian tanggal bawaan peramban + tombol Terapkan → satu baris: PeriodPicker,
 *    kategori, batas "jarang dipakai"; laporan dimuat ulang otomatis saat penyaring berubah;
 *  • 4 kartu angka StatTile dengan keterangan; "nilai berisiko" dulu menempel di kartu "Idle" padahal
 *    dihitung dari aset JARANG DIPAKAI → dipindah ke kartu yang benar;
 *  • daftar aset (isi utama) di atas; per kategori & per pemegang di bawahnya sebagai tabel (dulu batang
 *    progres & lingkaran inisial berwarna);
 *  • istilah Inggris (Utilization, Underutilized, Idle, Assignee, Last Activity) → bahasa Indonesia;
 *  • tombol "CSV" (unduhan server berkolom Inggris) → TombolUnduh Excel/CSV berkolom Indonesia.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../../layout/PageLayout';
import PeriodPicker, { periodFromPreset } from '../../finance/PeriodPicker';
import { EmptyState } from '../../moduleAtoms';
import { STATUS_CONFIG } from '../constants';
import { angka, apicall, fmtCurrency, fmtDate, fmtPersen, useHP } from '../utils';
import { KPICard, BarisKartu, Bagian } from '../components/KPICard';

const nadaPemakaian = (p) => (p >= 80 ? 'text-[hsl(var(--success-text))]'
  : p >= 40 ? 'text-foreground'
    : p > 0 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]');
const namaKategori = (n) => (!n || n === 'Uncategorized' ? 'Tanpa kategori' : n);
const angkaID = (v) => Number(v || 0).toLocaleString('id-ID');

export function UtilizationReportTab({ token, categories }) {
  // Bawaan: 3 bulan terakhir (dulu 90 hari ke belakang lewat dua kotak tanggal).
  const [periode, setPeriode] = useState(() => periodFromPreset('3m'));
  const [categoryId, setCategoryId] = useState('all');
  const [threshold, setThreshold] = useState(30);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState('top'); // top | underutilized | idle
  const hp = useHP();

  const params = useCallback((limit) => {
    const p = new URLSearchParams({
      date_from: periode.from,
      date_to: periode.to,
      underutilized_threshold: String(threshold),
      limit: String(limit),
    });
    if (categoryId && categoryId !== 'all') p.append('category_id', categoryId);
    return p;
  }, [periode, threshold, categoryId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apicall('GET', `/api/assets/reports/utilization?${params(100)}`, token);
      setReport(data);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat laporan pemakaian');
    } finally {
      setLoading(false);
    }
  }, [token, params]);

  useEffect(() => { load(); }, [load]);

  const pilihDaftar = (rpt, v) => ((v === 'top' ? rpt?.top_utilized : v === 'underutilized' ? rpt?.underutilized : rpt?.idle_assets) || []);
  /** Unduhan: daftar yang sedang dipilih, sampai 500 aset (batas API) — bukan hanya 100 yang tampil. */
  const ambilSemua = async () => {
    const data = await apicall('GET', `/api/assets/reports/utilization?${params(500)}`, token);
    return pilihDaftar(data, view);
  };

  const summary = report?.summary || {};
  const detailRows = pilihDaftar(report, view);
  const adaAset = (summary.total_assets || 0) > 0;
  const namaView = { top: 'semua-aset', underutilized: 'jarang-dipakai', idle: 'tidak-dipakai' }[view];

  // Alat dibungkus satu kelompok supaya Unduh & muat ulang tidak terpisah baris di HP.
  const alat = (
    <div className="flex items-center gap-2">
      <TombolUnduh namaBerkas={`pemakaian-aset-${namaView}`} namaLembar="Pemakaian aset" baris={detailRows}
        ambilSemua={ambilSemua} testId="util-unduh"
        kolom={[
          { label: 'No. aset', nilai: (r) => r.asset_number },
          { label: 'Nama aset', nilai: (r) => r.asset_name },
          { label: 'Kategori', nilai: (r) => namaKategori(r.category_name) },
          { label: 'Status', nilai: (r) => STATUS_CONFIG[r.status]?.label || r.status || '' },
          { label: 'Pemakaian (%)', nilai: (r) => Number(r.utilization_pct) || 0 },
          { label: 'Hari ditugaskan', nilai: (r) => r.assigned_days },
          { label: 'Hari dalam periode', nilai: (r) => r.effective_window_days },
          { label: 'Jumlah penugasan', nilai: (r) => r.assignment_count },
          { label: 'Pemegang sekarang', nilai: (r) => r.current_assignee || '' },
          { label: 'Terakhir ditugaskan', nilai: (r) => (r.last_assigned_date ? fmtDate(r.last_assigned_date) : '') },
          { label: 'Terakhir dikembalikan', nilai: (r) => (r.last_returned_date ? fmtDate(r.last_returned_date) : '') },
          { label: 'Harga beli', nilai: (r) => angka(r.purchase_cost) },
        ]} />
      <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
        data-testid="util-apply-button">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </div>
  );

  return (
    <PageLayout testId="utilization-report-tab" title="Pemakaian"
      subtitle="Berapa lama tiap aset dipegang karyawan dalam periode terpilih."
      filters={<>
        <PeriodPicker value={periode} onChange={setPeriode} testId="util-periode" />
        <SmartNativeSelect value={categoryId} onChange={e => setCategoryId(e.target.value)}
          className="w-48" aria-label="Kategori" data-testid="util-filter-category">
          <option value="all">Semua kategori</option>
          {(categories || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </SmartNativeSelect>
        <label className="flex items-center gap-2 text-sm text-muted-foreground" htmlFor="util-threshold">
          Jarang dipakai bila &lt;
          <Input id="util-threshold" type="number" min="0" max="100" inputMode="numeric"
            value={threshold} onChange={e => setThreshold(Math.max(0, Math.min(100, parseInt(e.target.value || '0', 10))))}
            data-testid="util-filter-threshold" className="h-9 w-20" />
          %
        </label>
        {hp && alat}
      </>}
      tools={hp ? null : alat}
      summary={adaAset ? (
        <BarisKartu testId="util-kpi">
          <KPICard label="Aset dinilai" value={angkaID(summary.total_assets)} testId="util-kpi-total"
            sub={`${angkaID(summary.assets_in_use_today)} sedang dipegang karyawan`}
            hint="Aset yang belum dilepas (sesuai kategori terpilih)." />
          <KPICard label="Rata-rata pemakaian" value={fmtPersen(summary.avg_utilization_pct)} testId="util-kpi-avg"
            sub={`${angkaID(summary.fully_utilized_count)} aset dipakai ≥ 95%`}
            hint="Hari aset ditugaskan dibagi hari dalam periode (dihitung sejak tanggal beli), dirata-rata semua aset." />
          <KPICard label="Jarang dipakai" value={angkaID(summary.underutilized_count)} testId="util-kpi-under"
            sub={`Pemakaian < ${threshold}% · harga beli ${fmtCurrency(summary.underutilized_value_at_risk || 0)}`}
            hint="Aset dengan pemakaian di bawah batas. Rupiah = jumlah harga beli aset tersebut (termasuk yang tidak dipakai sama sekali)." />
          <KPICard label="Tidak dipakai sama sekali" value={angkaID(summary.idle_in_window_count)} testId="util-kpi-idle"
            sub="Tidak pernah ditugaskan dalam periode"
            hint="Aset tanpa satu hari pun penugasan dalam periode terpilih." />
        </BarisKartu>
      ) : null}>
      {!report ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat laporan pemakaian…</p>
      ) : !adaAset ? (
        <EmptyState title="Belum ada aset untuk dinilai" testId="util-empty"
          description="Laporan pemakaian dihitung dari riwayat penugasan aset. Daftarkan aset dan tugaskan ke karyawan lebih dulu." />
      ) : (
        <>
          <Bagian judul="Daftar aset" testId="util-daftar"
            keterangan={view === 'top' ? 'Diurutkan dari pemakaian tertinggi.' : view === 'underutilized'
              ? `Pemakaian di bawah ${threshold}%, dari yang terendah.` : 'Tidak pernah ditugaskan dalam periode.'}
            alat={<FilterChips value={view} onChange={setView} hideWhenEmpty={false} testId="util-view" ariaLabel="Daftar"
              options={[
                { key: 'top', label: 'Semua aset', count: summary.total_assets || 0 },
                { key: 'underutilized', label: 'Jarang dipakai', count: summary.underutilized_count || 0 },
                { key: 'idle', label: 'Tidak dipakai', count: summary.idle_in_window_count || 0 },
              ]} />}>
            <TabelData baris={detailRows} kunci={(r) => r.asset_id} testId="util-table"
              kosong={<p className="py-6 text-center text-sm text-muted-foreground" data-testid="util-empty-detail">
                Tidak ada aset di daftar ini.</p>}
              kolom={[
                { kunci: 'aset', label: 'Aset', hp: 'judul', isi: (r) => <span className="font-medium">{r.asset_name}</span> },
                { kunci: 'no', label: 'No. aset', hp: 'keterangan', isi: (r) => <span className="tabular-nums text-muted-foreground">{r.asset_number}</span> },
                { kunci: 'kat', label: 'Kategori', isi: (r) => namaKategori(r.category_name) },
                { kunci: 'pakai', label: 'Pemakaian', rata: 'kanan', isi: (r) => (
                  <span className={`tabular-nums font-medium ${nadaPemakaian(r.utilization_pct)}`}>{fmtPersen(r.utilization_pct)}</span>) },
                { kunci: 'hari', label: 'Hari dipakai', rata: 'kanan', isi: (r) => (
                  <span className="tabular-nums">{angkaID(r.assigned_days)} / {angkaID(r.effective_window_days)}</span>) },
                { kunci: 'pemegang', label: 'Pemegang sekarang', isi: (r) => r.current_assignee || '—' },
                { kunci: 'akhir', label: 'Terakhir ditugaskan', isi: (r) => (r.last_assigned_date ? fmtDate(r.last_assigned_date) : '—') },
                { kunci: 'nilai', label: 'Harga beli', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtCurrency(r.purchase_cost)}</span> },
              ]} />
            {detailRows.length >= 100 && (
              <p className="text-xs text-muted-foreground">Menampilkan 100 aset pertama. Unduh untuk daftar lengkap.</p>
            )}
          </Bagian>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Bagian judul="Per kategori" testId="util-per-kategori"
              alat={<TombolUnduh namaBerkas="pemakaian-aset-per-kategori" namaLembar="Per kategori" baris={report.by_category || []}
                testId="util-kategori-unduh" kolom={[
                  { label: 'Kategori', nilai: (c) => namaKategori(c.category_name) },
                  { label: 'Jumlah aset', nilai: (c) => c.asset_count },
                  { label: 'Rata-rata pemakaian (%)', nilai: (c) => Number(c.avg_utilization_pct) || 0 },
                  { label: 'Jarang dipakai', nilai: (c) => c.underutilized_count },
                  { label: 'Tidak dipakai', nilai: (c) => c.idle_count },
                  { label: 'Harga beli', nilai: (c) => angka(c.total_purchase_cost) },
                ]} />}>
              <TabelData baris={report.by_category || []} kunci={(c) => c.category_id} testId="util-kategori-table"
                kosong={<p className="py-6 text-center text-sm text-muted-foreground">Tidak ada data.</p>}
                kolom={[
                  { kunci: 'nama', label: 'Kategori', hp: 'judul', isi: (c) => namaKategori(c.category_name) },
                  { kunci: 'n', label: 'Aset', rata: 'kanan', isi: (c) => <span className="tabular-nums">{angkaID(c.asset_count)}</span> },
                  { kunci: 'avg', label: 'Rata-rata', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmtPersen(c.avg_utilization_pct)}</span> },
                  { kunci: 'under', label: 'Jarang', rata: 'kanan', isi: (c) => <span className="tabular-nums">{angkaID(c.underutilized_count)}</span> },
                  { kunci: 'idle', label: 'Tidak dipakai', rata: 'kanan', isi: (c) => <span className="tabular-nums">{angkaID(c.idle_count)}</span> },
                  { kunci: 'biaya', label: 'Harga beli', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmtCurrency(c.total_purchase_cost)}</span> },
                ]} />
            </Bagian>

            <Bagian judul="Pemegang aset terbanyak" testId="util-per-pemegang"
              keterangan={(report.by_assignee || []).length > 8 ? `8 teratas dari ${report.by_assignee.length} pemegang.` : undefined}
              alat={<TombolUnduh namaBerkas="pemakaian-aset-per-pemegang" namaLembar="Per pemegang" baris={report.by_assignee || []}
                testId="util-pemegang-unduh" kolom={[
                  { label: 'Pemegang', nilai: (a) => a.assignee_name },
                  { label: 'Jumlah aset', nilai: (a) => a.unique_assets },
                  { label: 'Total hari ditugaskan', nilai: (a) => a.total_assigned_days },
                ]} />}>
              <TabelData baris={(report.by_assignee || []).slice(0, 8)} kunci={(a) => a.assignee_id} testId="util-pemegang-table"
                kosong={<p className="py-6 text-center text-sm text-muted-foreground">Belum ada penugasan dalam periode ini.</p>}
                kolom={[
                  { kunci: 'nama', label: 'Pemegang', hp: 'judul', isi: (a) => <span className="font-medium">{a.assignee_name}</span> },
                  { kunci: 'aset', label: 'Aset', rata: 'kanan', isi: (a) => <span className="tabular-nums">{angkaID(a.unique_assets)}</span> },
                  { kunci: 'hari', label: 'Total hari', rata: 'kanan', isi: (a) => <span className="tabular-nums">{angkaID(a.total_assigned_days)}</span> },
                ]} />
            </Bagian>
          </div>
        </>
      )}
    </PageLayout>
  );
}
