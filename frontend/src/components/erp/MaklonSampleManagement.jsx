/**
 * MaklonSampleManagement — DIPENSIUNKAN (Tahap 9, 7 Nov 2026, keputusan 9).
 *
 * Owner: sampel dibuat SESUDAH PO ada, jadi menu "Kelola Sampel" dihapus. Sampel kini tab "Sampel" di rincian
 * PO maklon (engine/PODetailPanel → SamplesTab): buat, ubah, kirim ke klien, setujui, tolak, minta revisi.
 * Riwayat sampel per artikel tetap tampil di Katalog Buyer.
 * Id modul `maklon-samples` tetap hidup untuk tautan lama: diteruskan ke `maklon-pos-engine`
 *   { po_id | order_id }  →  { open_po_id, detail_tab: 'sampel' }   (tanpa PO: daftar PO maklon).
 */
import { useEffect } from 'react';
import { FileCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PageLayout from './layout/PageLayout';
import { EmptyState } from './moduleAtoms';

export default function MaklonSampleManagement({ deepLinkParams, onNavigate }) {
  const poId = deepLinkParams?.po_id || deepLinkParams?.order_id || deepLinkParams?.open_po_id || '';
  const params = poId ? { open_po_id: poId, detail_tab: 'sampel' } : {};
  useEffect(() => {
    onNavigate?.('maklon-pos-engine', params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <PageLayout title="Sampel" subtitle="Sampel sekarang dikelola di tab Sampel pada rincian PO maklon.">
      <EmptyState icon={FileCheck} title="Mengarahkan ke PO Maklon…"
        description="Buka PO di tabel, lalu pilih tab Sampel untuk membuat sampel dan mengirimnya ke klien."
        action={<Button variant="outline" onClick={() => onNavigate?.('maklon-pos-engine', params)} data-testid="samples-open-po">Buka PO Maklon</Button>} />
    </PageLayout>
  );
}
