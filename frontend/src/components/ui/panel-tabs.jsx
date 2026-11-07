import { Tabs, TabsList, TabsTrigger } from "./tabs"
import { cn } from "@/lib/utils"

/**
 * PanelTabs — tab standar DI DALAM rincian satu baris (DetailPanel), PANDUAN_UI G4/G13 (Tahap 9, 7 Nov 2026).
 *
 * Satu bentuk tab untuk rincian di halaman (mis. rincian PO: Ringkasan · Barang · …), dibangun dari `ui/tabs`
 * (Radix) — jadi rata kiri, selebar isi, dan otomatis tampil sebagai pil bila modulnya dibuka di dalam hub
 * (NestedTabsContext). Isi tab dirender pemanggil berdasarkan `value`.
 *
 *   <PanelTabs value={tab} onChange={setTab} testId="po-detail-tab"
 *     tabs={[{ key: 'ringkasan', label: 'Ringkasan' }, { key: 'sampel', label: 'Sampel', count: 2 }]} />
 */
export default function PanelTabs({ tabs, value, onChange, className, testId, ariaLabel = "Bagian rincian" }) {
  return (
    <Tabs value={value} onValueChange={onChange}>
      <div className={cn("max-w-full overflow-x-auto", className)}>
        <TabsList aria-label={ariaLabel} data-testid={testId} className="h-auto flex-wrap justify-start">
          {tabs.map((t) => (
            <TabsTrigger key={t.key} value={t.key} data-testid={testId ? `${testId}-${t.key}` : undefined}>
              {t.label}
              {t.count !== undefined && t.count !== null && <span className="ml-1 tabular-nums">({t.count})</span>}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
    </Tabs>
  )
}
