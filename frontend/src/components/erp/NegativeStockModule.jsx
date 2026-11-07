/**
 * NegativeStockModule — laporan "Stok minus" (mode sementara sebelum stock opname).
 *
 * 2026-09-23, keputusan owner: klien belum opname tetapi produksi harus jalan, jadi
 * pengeluaran material boleh membuat saldo minus (setelan `inventory_allow_negative`).
 * Layar ini = daftar yang HARUS dibetulkan lewat opname; saat opname, qty aktual
 * menimpa nilai minus.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, TabelData (kartu di HP), unduh Excel/CSV, pemberitahuan mode
 * memakai Notice (dulu kotak berwarna buatan sendiri), baris tidak lagi berlatar merah tebal.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice } from './moduleAtoms';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

export default function NegativeStockModule({ token }) {
  const [rows, setRows] = useState([]);
  const [flag, setFlag] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const headers = { Authorization: `Bearer ${token}` };
    try {
      const [r, c] = await Promise.all([
        fetch('/api/rahaza/material-stock?negative=1', { headers }).then(x => (x.ok ? x.json() : [])),
        fetch('/api/dewi/system/config/inventory_allow_negative', { headers }).then(x => (x.ok ? x.json() : null)),
      ]);
      setRows(Array.isArray(r) ? r : []);
      setFlag(c);
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const on = flag ? (flag.value === true || String(flag.value).toLowerCase() === 'true') : null;
  const lokasi = (r) => `${r.location_code || '—'}${r.location_name ? ` · ${r.location_name}` : ''}`;

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (r) => (
      <span className="md:whitespace-nowrap" data-testid={`negative-stock-row-${r.material_code}`}>{r.material_code}</span>) },
    { kunci: 'nama', label: 'Material', hp: 'judul', isi: (r) => <span className="font-medium">{r.material_name}</span> },
    { kunci: 'lokasi', label: 'Lokasi', isi: (r) => <span className="text-sm">{lokasi(r)}</span> },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums font-semibold text-[hsl(var(--danger-text))]">{fmt(r.qty)} {r.unit || ''}</span>) },
    { kunci: 'waktu', label: 'Terakhir berubah', isi: (r) => (
      <span className="text-sm text-muted-foreground md:whitespace-nowrap">{formatDateTimeID(r.updated_at)}</span>) },
  ];

  return (
    <PageLayout testId="negative-stock-module" title="Stok minus"
      subtitle="Baris stok bersaldo negatif. Betulkan lewat Opname stok — qty hitung fisik menimpa nilai minus."
      tools={<>
        <TombolUnduh namaBerkas="stok-minus" namaLembar="Stok minus" baris={rows} testId="negative-stock-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.material_code },
            { label: 'Material', nilai: (r) => r.material_name },
            { label: 'Lokasi', nilai: (r) => lokasi(r) },
            { label: 'Qty', nilai: (r) => Number(r.qty || 0) },
            { label: 'Satuan', nilai: (r) => r.unit || '' },
            { label: 'Terakhir berubah', nilai: (r) => formatDateTimeID(r.updated_at) },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="negative-stock-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {on !== null && (
          <Notice tone={on ? 'warning' : 'success'} icon={on ? AlertTriangle : CheckCircle2} testId="negative-stock-mode"
            title={on ? 'Mode "Stok boleh minus" aktif' : 'Mode "Stok boleh minus" nonaktif'}>
            {on
              ? 'Pengeluaran material tidak ditolak walau stok kurang. Matikan di Administrasi Sistem › Konfigurasi Sistem › Gudang & Stok setelah opname selesai.'
              : 'Pengeluaran material ditolak bila stok kurang.'}
          </Notice>
        )}
        {rows.length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="negative-stock-count">
            <span className="font-medium tabular-nums text-foreground">{fmt(rows.length)}</span> baris stok minus.
          </p>
        )}
      </>}>
      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(r) => r.id || `${r.material_id}-${r.location_id}`} testId="negative-stock-table"
          kosong={<div data-testid="negative-stock-empty"><EmptyState title="Tidak ada stok minus"
            description="Semua baris stok bersaldo 0 atau lebih." /></div>} />
      )}
    </PageLayout>
  );
}
