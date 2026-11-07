/**
 * ProductionDashboardModule — Dashboard Produksi (menu `production-dashboard`).
 *
 * Tahap 9 (7 Nov 2026, keputusan owner no. 2 & 7): bentuknya SAMA dengan Dashboard Maklon — cetakan
 * PageLayout dengan isi dari `useDashboardAlur` (satu definisi untuk dua portal), alur barang ditampilkan
 * langsung, angka dari /api/pantau/ringkasan (satu sumber dengan Pantau Produksi). Jenis PO mengikuti portal
 * yang dibuka (dulu modul ini tidak pernah mengirim `business_type`).
 * Riwayat: FASE IA-1 menghapus tab Monitoring/AI; 2026-07-27 isi diganti alur nyata (Rencana → Cutting →
 * Vendor CMT → QC → Permak → Serah Terima).
 */
import PageLayout from './layout/PageLayout';
import { useDashboardAlur } from './pantau/DashboardAlurModule';
import { portalBusinessType } from './pantau/pantauShared';

export default function ProductionDashboardModule(props) {
  const page = useDashboardAlur({ ...props, businessType: portalBusinessType(props) });
  return <PageLayout {...page} />;
}
