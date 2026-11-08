/**
 * CuttingDashboard — ringkasan Portal Cutting.
 * Menjawab 3 pertanyaan operasional: berapa yang jalan, berapa hasilnya,
 * dan seberapa efisien kain dipakai (hasil pcs per satuan kain).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, 4 kartu StatTile (7 angka lama tetap ada — sebagian di keterangan
 * kartu), cutting terbaru = tabel standar yang bisa diunduh. Sumber: GET /api/cutting/dashboard.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Plus, RefreshCw, Scissors } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Skeleton } from '@/components/ui/skeleton';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { cuttingApi, StatusPill, STATUS_META, fmtNum, fmtPerUnit, fmtDateTime } from './cuttingApi';

export default function CuttingDashboard({ token, onNavigate }) {
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setErr('');
    try {
      setD(await cuttingApi('GET', '/dashboard', token));
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const by = d?.by_status || {};
  const recent = d?.recent || [];
  const adaKain = (d?.by_unit || []).length > 0;

  const kolom = [
    { kunci: 'number', label: 'Nomor', hp: 'judul', isi: (r) => <span className="font-medium tabular-nums">{r.number}</span> },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (r) => r.style_name || '—' },
    { kunci: 'kain', label: 'Kain', isi: (r) => <span className="text-muted-foreground">{r.input_material_name}</span> },
    { kunci: 'hasil', label: 'Hasil', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums whitespace-nowrap">{fmtNum(r.produced_qty)} / {fmtNum(r.planned_output_qty)} pcs</span>) },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusPill status={r.status} /> },
    { kunci: 'dibuat', label: 'Dibuat', hp: false, isi: (r) => <span className="whitespace-nowrap text-muted-foreground">{fmtDateTime(r.created_at)}</span> },
  ];

  return (
    <PageLayout testId="cutting-dashboard" title="Dashboard Cutting"
      subtitle="Roll kain dipotong menjadi kain pola (potongan) yang siap jadi BOM produksi."
      tools={<>
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="cutting-dash-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}
        {loading && !d ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20 rounded-lg" />)}</div>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Sedang berjalan" value={fmtNum(by.in_progress)} testId="cutting-kpi-running"
              sub={`Dari ${fmtNum(d?.total_orders)} order · ${fmtNum(by.draft)} draf · ${fmtNum(by.cancelled)} batal`} />
            <StatTile label="Potongan dihasilkan" value={`${fmtNum(d?.produced_qty)} pcs`} testId="cutting-kpi-produced"
              sub={`Dari rencana ${fmtNum(d?.planned_output_qty)} pcs · ${fmtNum(d?.output_material_count)} jenis di Master Potongan`} />
            <StatTile label="Rata-rata hasil" value={fmtPerUnit(d?.by_unit, 'yield')} testId="cutting-kpi-yield"
              sub={adaKain ? 'Pcs potongan per satuan kain' : 'Belum ada progres potong yang tercatat'} />
            <StatTile label="Kain terpakai" value={fmtPerUnit(d?.by_unit, 'consumed')} testId="cutting-kpi-consumed"
              sub={adaKain ? `Tanpa order batal · limbah ${fmtPerUnit(d?.by_unit, 'waste')}` : 'Belum ada progres potong yang tercatat'} />
          </div>
        )}
      </>}>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-base font-semibold text-foreground">Cutting terbaru</p>
          <div className="flex flex-wrap items-center gap-2">
            <TombolUnduh namaBerkas="cutting-terbaru" namaLembar="Cutting terbaru" baris={recent} testId="cutting-dash-unduh"
          kolom={[
            { label: 'Nomor', nilai: (r) => r.number }, { label: 'Style', nilai: (r) => r.style_name || '' },
            { label: 'Kain', nilai: (r) => r.input_material_name || '' },
            { label: 'Potongan jadi (pcs)', nilai: (r) => Number(r.produced_qty || 0) },
            { label: 'Rencana (pcs)', nilai: (r) => Number(r.planned_output_qty || 0) },
            { label: 'Status', nilai: (r) => (STATUS_META[r.status] || STATUS_META.draft).label },
            { label: 'Dibuat', nilai: (r) => fmtDateTime(r.created_at) },
          ]} />
            <Button variant="outline" onClick={() => onNavigate?.('cutting-orders')} data-testid="cutting-dash-goto-orders">
              Lihat semua order
            </Button>
          </div>
        </div>
        {loading && !d ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : (
          <TabelData kolom={kolom} baris={recent} testId="cutting-dash-recent"
            kosong={<EmptyState icon={Scissors} title="Belum ada order cutting"
              description="Order cutting pertama dibuat di menu Order Cutting."
              action={<Button onClick={() => onNavigate?.('cutting-orders')} data-testid="cutting-dash-create-first"><Plus />Buat cutting pertama</Button>} />} />
        )}
      </div>

      <GlassCard className="p-4">
        <p className="mb-2 text-sm font-semibold text-foreground">Alur cutting</p>
        <ol className="list-inside list-decimal space-y-1.5 text-sm text-muted-foreground">
          <li><b className="text-foreground">Buat cutting</b> — pilih kain dari master material Gudang, rencana pemakaian, dan target potongan.</li>
          <li><b className="text-foreground">Mulai</b> — sistem membuat item master potongan baru (satuan pcs) untuk style, warna, dan ukuran ini.</li>
          <li><b className="text-foreground">Catat progres</b> — tiap kali memotong: stok kain berkurang, stok potongan bertambah (tercatat di kartu stok gudang).</li>
          <li><b className="text-foreground">Selesai</b> — HPP potongan dihitung otomatis dari biaya kain terpakai.</li>
          <li>Potongan siap dipakai sebagai <b className="text-foreground">BOM produksi</b> dan dikeluarkan lewat <b className="text-foreground">Pengeluaran Material</b> atau Kirim Material CMT.</li>
        </ol>
      </GlassCard>
    </PageLayout>
  );
}
