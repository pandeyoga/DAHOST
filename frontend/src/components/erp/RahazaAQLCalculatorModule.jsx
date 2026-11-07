/**
 * RahazaAQLCalculatorModule — tautan lama `prod-aql-calculator` / tab "AQL" Analitik Produksi.
 *
 * Tahap 9 (keputusan owner 11): kalkulator AQL pindah ke Terima & QC ("Hitung sampel AQL"). Layar ini
 * tinggal pembungkus PageLayout atas komponen yang SAMA (`engine/AqlSamplingTool`) supaya tautan lama
 * tetap terbuka tanpa salinan rumus atau tampilan kedua.
 */
import PageLayout from './layout/PageLayout';
import { GlassCard } from '@/components/ui/glass';
import AqlSamplingTool from './engine/AqlSamplingTool';

export default function RahazaAQLCalculatorModule() {
  return (
    <PageLayout
      testId="aql-calculator-module"
      title="Hitung sampel AQL"
      subtitle="Jumlah sampel dan batas lulus/gagal pemeriksaan mutu. Juga tersedia di layar Terima & QC."
    >
      <GlassCard className="p-4">
        <AqlSamplingTool testId="aql-standalone" />
      </GlassCard>
    </PageLayout>
  );
}
