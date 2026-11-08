/**
 * Dashboard Penjualan (Portal Penjualan).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, 4 kartu StatTile dengan keterangan, SKU terlaris = tabel standar yang
 * bisa diunduh, tombol "langkah berikutnya" di kepala halaman.
 *
 * Perbaikan angka (keputusan 9): penjualan & laba kotor kini dihitung dari sumber yang SAMA dengan Laporan
 * Penjualan (/api/sales/report: bersih = bruto − diskon − retur, tanpa PPN). Dulu kartu memakai total nota
 * (termasuk PPN, retur tidak dikurangi) sehingga "Laba kotor bulan ini" lebih besar dari laporan.
 * Piutang, SKU terlaris, dan jumlah draf tetap dari /api/sales/dashboard.
 */
import { useEffect, useState } from 'react';
import { ChevronDown, Contact, ReceiptText, RefreshCw, TrendingUp, Wallet } from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { todayWIB, monthStartWIB } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';

const fmt = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
const angka = (n) => Number(n || 0).toLocaleString('id-ID');

export default function SalesDashboardModule({ onNavigate }) {
  const [d, setD] = useState(null);
  const [bulan, setBulan] = useState(null);   // totals laporan bulan berjalan
  const [hari, setHari] = useState(null);     // totals laporan hari ini
  const [err, setErr] = useState('');
  const [memuat, setMemuat] = useState(false);
  const load = async () => {
    setMemuat(true);
    setErr('');
    const hariIni = todayWIB();
    try {
      const [dash, rb, rh] = await Promise.all([
        apiGet('/sales/dashboard'),
        apiGet(`/sales/report?group_by=day&date_from=${monthStartWIB()}&date_to=${hariIni}`).catch(() => null),
        apiGet(`/sales/report?group_by=day&date_from=${hariIni}&date_to=${hariIni}`).catch(() => null),
      ]);
      setD(dash);
      setBulan(rb?.totals || null);
      setHari(rh?.totals || null);
    } catch (e) { setErr(e.message); }
    finally { setMemuat(false); }
  };
  useEffect(() => { load(); }, []);

  const top = d?.top_skus || [];
  const kolom = [
    { kunci: 'sku', label: 'SKU', hp: 'judul', isi: (s) => <span className="font-medium tabular-nums">{s.sku}</span> },
    { kunci: 'nama', label: 'Nama', hp: 'keterangan', isi: (s) => s.name },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (s) => <span className="tabular-nums">{angka(s.qty)}</span> },
    { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (s) => <span className="font-semibold tabular-nums whitespace-nowrap">{fmt(s.amount)}</span> },
  ];
  const ke = (module) => onNavigate && onNavigate(module, {});

  return (
    <PageLayout testId="sales-dashboard" title="Dashboard Penjualan"
      subtitle="Hasil penjualan langsung hari ini dan bulan ini, piutang, dan SKU terlaris."
      actions={onNavigate && <>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" data-testid="sales-dash-lainnya">Lainnya<ChevronDown /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => ke('sales-customers')} data-testid="onward-sales-customers"><Contact className="mr-2 h-4 w-4" />Master pelanggan</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => ke('fin-ar-360')} data-testid="onward-fin-ar-360"><Wallet className="mr-2 h-4 w-4" />Umur piutang (Keuangan)</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button onClick={() => ke('sales-direct')} data-testid="onward-sales-direct"><ReceiptText />Nota baru</Button>
      </>}
      tools={<>

        <Button variant="outline" size="icon" onClick={load} disabled={memuat} title="Muat ulang" aria-label="Muat ulang"
          data-testid="sales-dash-refresh">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {err && <Notice tone="danger" testId="sales-dash-error">{err}</Notice>}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Penjualan hari ini" value={hari ? fmt(hari.net_sales) : '—'} accent="primary" testId="sales-kpi-today"
            sub={hari ? `${angka(hari.notes)} nota · bersih, tanpa PPN` : 'Laporan hari ini gagal dimuat'} />
          <StatTile label="Penjualan bulan ini" value={bulan ? fmt(bulan.net_sales) : '—'} testId="sales-kpi-month"
            sub={bulan ? `${angka(bulan.notes)} nota · HPP ${fmt(bulan.cogs)}` : 'Laporan bulan ini gagal dimuat'} />
          <StatTile label="Laba kotor bulan ini" value={bulan ? fmt(bulan.margin) : '—'} testId="sales-kpi-margin"
            accent={(bulan?.margin || 0) >= 0 ? 'success' : 'danger'}
            sub={bulan ? `${bulan.margin_pct || 0}% dari penjualan bersih` : '—'} />
          <StatTile label="Piutang belum lunas" value={fmt(d?.open_ar)} testId="sales-kpi-ar"
            accent={d?.overdue_count ? 'danger' : 'default'}
            sub={`${angka(d?.open_ar_count)} invoice · lewat jatuh tempo ${fmt(d?.overdue_ar)}`} />
        </div>
        <p className="text-sm text-muted-foreground" data-testid="sales-draft-info">
          {angka(d?.draft_count)} nota masih draf — belum mengurangi stok. Saat dikonfirmasi, penjualan, HPP, dan stok barang jadi (FIFO) tercatat otomatis.
        </p>
      </>}>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="inline-flex items-center gap-2 text-base font-semibold text-foreground">
            <TrendingUp className="h-4 w-4 text-muted-foreground" />SKU terlaris bulan ini
          </p>
          <TombolUnduh namaBerkas="sku-terlaris-bulan-ini" namaLembar="SKU terlaris" baris={top} testId="sales-top-unduh"
          kolom={[
            { label: 'SKU', nilai: (s) => s.sku }, { label: 'Nama', nilai: (s) => s.name || '' },
            { label: 'Qty', nilai: (s) => Number(s.qty || 0) }, { label: 'Nilai', nilai: (s) => Number(s.amount || 0) },
          ]} />
        </div>
        <TabelData kolom={kolom} baris={top} kunci={(s) => s.sku} testId="sales-top-table"
          kosong={<EmptyState icon={TrendingUp} testId="sales-top-empty" className="py-10" title="Belum ada penjualan bulan ini"
            description="SKU terlaris tampil setelah ada nota yang dikonfirmasi bulan ini." />} />
      </div>
    </PageLayout>
  );
}
