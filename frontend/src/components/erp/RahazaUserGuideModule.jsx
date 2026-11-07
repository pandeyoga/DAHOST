import UserGuideContent from './userGuide/UserGuideContent';
import PageLayout from './layout/PageLayout';
import { GlassCard } from '@/components/ui/glass';

/**
 * Module wrapper untuk Panduan Penggunaan (Portal Administrasi Sistem › Panduan Sistem).
 * Menggunakan komponen UserGuideContent yang sama dengan UserGuideDialog (dipakai di PortalSelector).
 * Standar UI/UX v2 (8 Nov 2026): kepala halaman dari PageLayout (dulu kepala buatan dengan ikon besar).
 */
export default function RahazaUserGuideModule() {
  return (
    <PageLayout testId="user-guide-page" title="Panduan sistem"
      subtitle="Cara memakai tiap portal, skenario kerja langkah demi langkah, serta tips dan tanya jawab."
      tools={<span className="text-xs text-muted-foreground">Versi 2.5 · April 2026</span>}>
      <GlassCard className="overflow-hidden p-0">
        <UserGuideContent />
      </GlassCard>
    </PageLayout>
  );
}
