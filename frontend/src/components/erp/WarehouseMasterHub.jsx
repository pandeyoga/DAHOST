/**
 * WarehouseMasterHub.jsx — Master Item (Portal Gudang): Bahan & aksesoris · Produk jadi · Ambang stok · Lokasi gudang.
 *
 * Standar UI/UX v2 (8 Nov 2026): memakai HubTabs bersama — satu kepala ("Master Item"), tab rata kiri,
 * judul modul di dalam tab otomatis disembunyikan (dulu "Master Item" + "Master Material" bertumpuk) dan
 * tombol modul pindah ke baris tab. Deep-link tab tetap lewat sessionStorage `hub_tab_wh-master`
 * (dipakai tautan dari Alert & Reorder / Belanja Mingguan → tab "thresholds").
 *
 * Angka di label tab (diverifikasi 8 Nov 2026 terhadap DB uji):
 *  • Bahan & aksesoris = `pagination.total` /api/rahaza/materials?exclude_type=fg&page=1&limit=1 (= isi tabel tab itu)
 *  • Produk jadi       = `pagination.total` /api/rahaza/materials?type=fg&page=1&limit=1 (barang jadi aktif)
 *  • Lokasi gudang     = jumlah baris /api/rahaza/locations (= isi tabel tab itu)
 *  • Ambang stok: angka dihapus — dulu "43" tanpa keterangan (43 barang yang sudah berambang dari 1.726);
 *    ringkasan lengkapnya ada di kartu di dalam tab itu.
 */
import { useEffect, useMemo, useState } from 'react';
import HubTabs from './hubs/HubTabs';
import RahazaMaterialsModule from './RahazaMaterialsModule';
import RahazaFGInventoryModule from './RahazaFGInventoryModule';
import StockThresholdsModule from './StockThresholdsModule';
import RahazaLocationsModule from './RahazaLocationsModule'; // 2026-09-12: pindah dari Produksi → Master Produk → Lokasi Kerja

const totalDari = (d) => d?.pagination?.total ?? d?.total ?? (Array.isArray(d) ? d.length : null);
const denganJumlah = (label, n) => (n === null || n === undefined ? label : `${label} (${Number(n).toLocaleString('id-ID')})`);

export default function WarehouseMasterHub(props) {
  const { token } = props;
  const [matCount, setMatCount] = useState(null);
  const [fgCount, setFgCount] = useState(null);
  const [locCount, setLocCount] = useState(null);

  // FASE IA-5: jumlah dibaca dari `pagination.total` (mode berhalaman), bukan panjang array (mentok 500).
  useEffect(() => {
    const h = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
    const ambil = (url, set, fn = totalDari) => fetch(url, { headers: h })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) { const n = fn(d); if (n !== null && n !== undefined) set(n); } })
      .catch(() => {});
    ambil('/api/rahaza/materials?exclude_type=fg&page=1&limit=1', setMatCount);
    ambil('/api/rahaza/materials?type=fg&page=1&limit=1', setFgCount);
    ambil('/api/rahaza/locations', setLocCount, (d) => (Array.isArray(d) ? d.length : (d?.total ?? d?.items?.length ?? null)));
  }, [token]);

  const tabs = useMemo(() => [
    { key: 'material', label: denganJumlah('Bahan & aksesoris', matCount), Component: RahazaMaterialsModule },
    { key: 'fg', label: denganJumlah('Produk jadi', fgCount), Component: RahazaFGInventoryModule },
    // W3 — pintu untuk MENGISI ambang stok. Alert & Reorder tidak akan berbunyi selama ambang kosong.
    { key: 'thresholds', label: 'Ambang stok', Component: StockThresholdsModule },
    { key: 'locations', label: denganJumlah('Lokasi gudang', locCount), Component: RahazaLocationsModule },
  ], [matCount, fgCount, locCount]);

  return (
    <HubTabs
      {...props}
      hubId="wh-master"
      title="Master Item"
      subtitle="Data bahan, aksesoris, produk jadi, ambang stok, dan lokasi gudang."
      tabs={tabs}
    />
  );
}
