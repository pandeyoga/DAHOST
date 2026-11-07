/**
 * MaklonPO360Module — DIPENSIUNKAN (Tahap 9, 7 Nov 2026, keputusan 8).
 *
 * Menu "Detail PO" dihapus owner: isinya kini rincian di bawah tabel PO yang sama di kedua portal
 * (engine/PODetailPanel di PO Maklon / PO Internal), dengan data dari PO utama (`production_pos`).
 * Id modul `maklon-po-360` tetap hidup supaya tautan lama (Pusat Kendali, notifikasi, bookmark) tidak putus:
 * layar ini langsung meneruskan ke `maklon-pos-engine` dan membuka rincian PO yang diminta.
 *   { po_id, tab }  →  maklon-pos-engine { open_po_id, detail_tab }
 */
import { useEffect } from 'react';
import { Layers } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PageLayout from './layout/PageLayout';
import { EmptyState } from './moduleAtoms';

// tab layar lama → tab rincian PO baru
export const OLD_TAB_TO_DETAIL = {
  detail: 'ringkasan', bom: 'bahan', samples: 'sampel', production: 'barang', qc: 'kirim',
  billing: 'tagihan', hpp: 'tagihan', timeline: 'riwayat',
};

export default function MaklonPO360Module({ deepLinkParams, onNavigate }) {
  const poId = deepLinkParams?.po_id || deepLinkParams?.open_po_id || '';
  const params = poId ? { open_po_id: poId, detail_tab: OLD_TAB_TO_DETAIL[deepLinkParams?.tab] || 'ringkasan' } : {};
  useEffect(() => {
    onNavigate?.('maklon-pos-engine', params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <PageLayout title="Detail PO" subtitle="Rincian PO sekarang dibuka langsung di bawah tabel PO Maklon.">
      <EmptyState icon={Layers} title="Mengarahkan ke PO Maklon…"
        description="Klik nomor PO di tabel untuk membuka ringkasan, barang, bahan, kiriman, tagihan, sampel, dan riwayat."
        action={<Button variant="outline" onClick={() => onNavigate?.('maklon-pos-engine', params)} data-testid="po360-open-po">Buka PO Maklon</Button>} />
    </PageLayout>
  );
}
