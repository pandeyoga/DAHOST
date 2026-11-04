import { cn } from "@/lib/utils"
import { CHIP_CLASS, CHIP_ACTIVE_CLASS } from "./tabs"

/**
 * FilterChips — penyaring status/jenis berbentuk pil (PANDUAN_UI G4, 2026-11-04).
 *
 * Satu bentuk untuk semua "Semua · Draf · Disetujui" di toolbar, menggantikan deret tombol buatan
 * sendiri (pil toska, garis bawah, segmen). Bedanya dengan tab halaman (HubTabs): penyaring hanya
 * menyaring isi yang sama.
 *
 *   <FilterChips value={status} onChange={setStatus} testId="recon-status"
 *     options={[{ key: '', label: 'Semua', count: 12 }, { key: 'draft', label: 'Draf', count: 3 }]} />
 *
 * - `count` opsional; tampil sebagai "(n)".
 * - `hideWhenEmpty` (bawaan true): bila SEMUA count = 0, penyaring tidak ditampilkan (G10).
 */
export default function FilterChips({ options, value, onChange, hideWhenEmpty = true, className, testId, ariaLabel = "Penyaring" }) {
  const counted = options.filter((o) => o.count !== undefined && o.count !== null)
  if (hideWhenEmpty && counted.length === options.length && counted.every((o) => !Number(o.count))) return null
  return (
    <div role="group" aria-label={ariaLabel} className={cn("inline-flex flex-wrap items-center gap-1.5", className)} data-testid={testId}>
      {options.map((o) => {
        const active = String(value ?? "") === String(o.key ?? "")
        return (
          <button
            key={String(o.key)}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.key)}
            data-testid={testId ? `${testId}-${o.key || "all"}` : undefined}
            className={cn(CHIP_CLASS, active && CHIP_ACTIVE_CLASS)}
          >
            {o.icon && <o.icon className="w-3.5 h-3.5" />}
            {o.label}
            {o.count !== undefined && o.count !== null && <span className="tabular-nums">({o.count})</span>}
          </button>
        )
      })}
    </div>
  )
}
