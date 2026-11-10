import * as React from "react"
import * as PopoverPrimitive from "@radix-ui/react-popover"
import { ChevronDown, Search } from "lucide-react"
import { cn } from "@/lib/utils"

/**
 * SmartNativeSelect — a DROP-IN replacement for a native <select>.
 *
 * Goal: give type-to-filter search to the many native <select> dropdowns that
 * are bound to large reference lists (materials, employees, accounts, ...),
 * WITHOUT changing the caller's data flow.
 *
 * Migration is a tag rename only:
 *   <select value={v} onChange={e => setV(e.target.value)} className="...">
 *     <option value="">All</option>
 *     {items.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
 *   </select>
 *  ->
 *   <SmartNativeSelect value={v} onChange={e => setV(e.target.value)} className="...">
 *     ...same <option> children...
 *   </SmartNativeSelect>
 *
 * - onChange is called native-style: onChange({ target: { value } }).
 * - <option> (and <optgroup>) children are parsed automatically.
 * - Search box appears automatically when options >= searchThreshold (default 8),
 *   or force via searchable={true}. Small enums stay simple (searchable={false} or few opts).
 *
 * TESTABILITY / A11Y (2026-07-25): bila caller mengirim `data-testid="x"`, komponen mengekspos:
 *     x            → root
 *     x-trigger    → tombol pembuka (role=combobox, aria-expanded, data-value)
 *     x-panel      → panel
 *     x-list       → daftar opsi (role=listbox)
 *     x-option-<v> → tiap opsi (role=option, aria-selected, data-value)
 *
 * 2026-11-07 — BUG BESAR "pilihan tidak bisa diklik / tidak bisa dicari" (keluhan owner: supplier di form PO,
 * model & warna di Order Cutting, dan banyak form lain). Panel dulu dirender lewat createPortal ke <body>.
 * Di dalam Dialog/Sheet Radix (modal) seluruh <body> diberi `pointer-events: none` dan fokus dikunci di dalam
 * jendela, sehingga opsi TIDAK BISA DIKLIK dan kotak cari TIDAK BISA DIKETIK (terbukti dengan Playwright:
 * 14 opsi supplier tampil, klik timeout). Panel kini memakai Popover Radix — lapisan Radix yang sama dengan
 * Dialog — sehingga opsi bisa diklik dan dicari di dalam jendela mana pun, posisinya tetap menghindari tepi
 * layar (membuka ke atas bila ruang bawah sempit), dan API/testid TIDAK berubah.
 *
 * 2026-11-07 (Tahap 5, audit form) — daftar sangat panjang (mis. 1.727 material di form PO) membuat panel
 * macet 1–15 detik saat dibuka di dalam jendela, karena SEMUA opsi digambar sekaligus. Kini paling banyak
 * MAX_RENDER opsi yang digambar (opsi terpilih selalu ikut); sisanya diringkas jadi baris "ketik untuk
 * mempersempit". Pencarian tetap atas seluruh daftar.
 *
 * 2026-11-10 (owner: "dropdownnya terlalu kecil jadi sulit untuk dicari", form PO): panel daftar yang bisa dicari
 * kini SELEBAR ISINYA (minimal selebar tombol, maksimal ±40 rem / lebar layar), nama panjang tidak dipotong lagi
 * (dibungkus ke baris berikut, judul lengkap di `title`), daftar lebih tinggi, dan pencarian per KATA dalam urutan
 * bebas ("opp plastik 25" menemukan "Plastik OPP 25 x 35") — dulu satu potongan teks utuh harus persis berurutan.
 */
const MAX_RENDER = 300
function nodeText(node) {
  if (node == null || node === false || node === true) return ""
  if (typeof node === "string" || typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(nodeText).join(" ")
  if (React.isValidElement(node)) return nodeText(node.props?.children)
  return ""
}

function parseOptions(children, acc) {
  React.Children.forEach(children, (ch) => {
    if (!React.isValidElement(ch)) return
    if (ch.type === "option") {
      acc.push({
        value: String(ch.props.value ?? ""),
        label: nodeText(ch.props.children) || String(ch.props.value ?? ""),
        disabled: !!ch.props.disabled,
      })
    } else if (ch.type === "optgroup" || ch.props?.children) {
      parseOptions(ch.props.children, acc)
    }
  })
  return acc
}

export default function SmartNativeSelect({
  value = "",
  onChange,
  children,
  className = "",
  wrapperClassName = "",
  disabled = false,
  searchable = "auto",
  searchThreshold = 8,
  searchPlaceholder = "Cari...",
  placeholder,
  id,
  name,
  "data-testid": dataTestId,
  ...rest
}) {
  const options = React.useMemo(() => parseOptions(children, []), [children])
  const enabled = searchable === true || (searchable === "auto" && options.length >= searchThreshold)

  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")
  const inputRef = React.useRef(null)

  const selected = React.useMemo(
    () => options.find((o) => o.value === String(value)),
    [options, value]
  )

  // Determine placeholder: explicit prop, else the empty-value option's label.
  const emptyOpt = options.find((o) => o.value === "")
  const ph = placeholder || emptyOpt?.label || "— Pilih —"

  const filtered = React.useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    if (!words.length) return options
    return options.filter((o) => {
      const hay = `${o.label} ${o.value}`.toLowerCase()
      return words.every((w) => hay.includes(w))
    })
  }, [options, query])

  // Yang digambar: paling banyak MAX_RENDER opsi; opsi terpilih tetap tampil walau di luar batas.
  const shown = React.useMemo(() => {
    if (filtered.length <= MAX_RENDER) return filtered
    const head = filtered.slice(0, MAX_RENDER)
    const cur = String(value ?? "")
    if (cur !== "" && !head.some((o) => o.value === cur)) {
      const sel = filtered.find((o) => o.value === cur)
      if (sel) head.push(sel)
    }
    return head
  }, [filtered, value])
  const hiddenCount = filtered.length - shown.length

  const setOpenSafe = (o) => {
    if (disabled && o) return
    setOpen(o)
    if (!o) setQuery("")
  }

  const emit = (v) => {
    onChange?.({ target: { value: v, name } })
    setOpenSafe(false)
  }

  // Mirror the caller's width so filter-bar selects (w-40, w-32, ...) don't stretch,
  // while form fields (w-full or none) fill their container.
  const widthMatch = className.match(/\bw-(?:full|\d+(?:\.\d+)?|\[[^\]]+\]|px|screen|min|max|fit|auto)\b/)
  const wrapperWidth = wrapperClassName || (widthMatch ? widthMatch[0] : "w-full")

  return (
    <div className={cn("relative", wrapperWidth)} data-testid={dataTestId} id={id}>
      <PopoverPrimitive.Root open={open} onOpenChange={setOpenSafe} modal={false}>
        <PopoverPrimitive.Trigger asChild>
          <button
            type="button"
            disabled={disabled}
            role="combobox"
            aria-expanded={open}
            aria-haspopup="listbox"
            data-testid={dataTestId ? `${dataTestId}-trigger` : undefined}
            data-value={String(value ?? "")}
            className={cn(
              "flex w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-3 py-2 text-left text-sm text-foreground shadow-sm transition-colors",
              disabled ? "cursor-not-allowed opacity-50" : "hover:border-ring focus:outline-none focus:ring-1 focus:ring-ring",
              open && "ring-1 ring-ring",
              className
            )}
            {...rest}
          >
            {/* 2026-11-04 (galeri Keuangan): pilihan bernilai kosong yang BERARTI ("Semua toko", "Semua status") tampil
                seperti pilihan biasa — dulu abu seperti placeholder, sehingga dua pilihan bersebelahan terlihat beda.
                Abu hanya untuk placeholder sungguhan (prop `placeholder`, atau label "— …" / "Pilih …"). */}
            <span className={cn("truncate", (!selected || (selected.value === "" && (placeholder || /^\s*([—–-]|pilih\b)/i.test(selected.label))))
              ? "text-muted-foreground" : "text-foreground")}>
              {selected ? selected.label : ph}
            </span>
            <ChevronDown className={cn("h-4 w-4 flex-shrink-0 opacity-50 transition-transform", open && "rotate-180")} />
          </button>
        </PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            side="bottom"
            align="start"
            sideOffset={4}
            collisionPadding={8}
            onOpenAutoFocus={(e) => {
              // fokus ke kotak cari (bukan opsi pertama); tanpa kotak cari fokus tetap di tombol
              e.preventDefault()
              if (enabled) requestAnimationFrame(() => inputRef.current?.focus())
            }}
            style={enabled
              // daftar bisa dicari = biasanya daftar master panjang → panel selebar isinya (dibatasi layar)
              ? { minWidth: "max(var(--radix-popover-trigger-width), 18rem)", width: "max-content",
                  maxWidth: "min(40rem, calc(100vw - 16px))" }
              : { width: "var(--radix-popover-trigger-width)", minWidth: 160 }}
            className="z-[9999] overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-lg outline-none"
            data-testid={dataTestId ? `${dataTestId}-panel` : undefined}
          >
            {enabled && (
              <div className="flex items-center gap-2 border-b border-border/60 bg-popover px-3 py-2">
                <Search className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={searchPlaceholder}
                  data-testid="select-search-input"
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    // Enter memilih hasil pertama yang bisa dipilih (cepat untuk daftar panjang)
                    if (e.key === "Enter") {
                      e.preventDefault()
                      const first = filtered.find((o) => !o.disabled)
                      if (first) emit(first.value)
                    }
                  }}
                  className="w-full bg-transparent text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-none"
                />
              </div>
            )}
            <div className="overflow-y-auto p-1" role="listbox"
              style={{ maxHeight: `min(${enabled ? 360 : 240}px, calc(var(--radix-popover-content-available-height, 300px) - 48px))` }}
              data-testid={dataTestId ? `${dataTestId}-list` : "select-option-list"}>
              {filtered.length === 0 ? (
                <div className="px-2 py-3 text-center text-sm text-muted-foreground">Tidak ada hasil</div>
              ) : (
                shown.map((o, i) => (
                  <button
                    key={`${o.value}-${i}`}
                    type="button"
                    disabled={o.disabled}
                    onClick={() => !o.disabled && emit(o.value)}
                    role="option"
                    aria-selected={o.value === String(value)}
                    data-value={o.value}
                    data-testid={dataTestId ? `${dataTestId}-option-${o.value}` : undefined}
                    className={cn(
                      "flex w-full items-center rounded-sm px-2 py-1.5 text-left text-sm transition-colors",
                      o.disabled ? "cursor-not-allowed opacity-50" : "hover:bg-accent hover:text-accent-foreground",
                      o.value === String(value) && "bg-accent/60 font-medium"
                    )}
                  >
                    <span className={enabled ? "whitespace-normal break-words" : "truncate"} title={o.label}>{o.label}</span>
                  </button>
                ))
              )}
              {hiddenCount > 0 && (
                <div className="px-2 py-2 text-center text-xs text-muted-foreground" data-testid="select-more-hint">
                  {hiddenCount.toLocaleString("id-ID")} pilihan lain — ketik untuk mempersempit
                </div>
              )}
            </div>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
    </div>
  )
}
