import { useEffect, useState } from "react"
import { Textarea } from "./textarea"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "./alert-dialog"
import { cn } from "@/lib/utils"
import { buttonVariants } from "./button"

/**
 * confirmDialog — konfirmasi bergaya aplikasi pengganti `window.confirm` (PANDUAN_UI G9, 2026-11-04).
 *
 *   if (!(await confirmDialog('Hapus sesi Okt 2026?'))) return;
 *   if (!(await confirmDialog({ title: 'Nonaktifkan BCA?', body: 'Riwayat tetap ada.', confirmLabel: 'Nonaktifkan', danger: true }))) return;
 *
 * `<ConfirmDialogHost />` dipasang sekali di App. Tanpa host (mis. uji unit) jatuh ke window.confirm.
 *
 * 2026-11-06 (Tahap 2): `input: { label, placeholder, minLength }` → dialog meminta teks (mis. alasan
 * kelebihan qty). Hasilnya teks yang diisi (string) atau `false` bila dibatalkan.
 */
let enqueue = null

export function confirmDialog(opts) {
  const o = typeof opts === "string" ? { title: opts } : (opts || {})
  if (!enqueue) return Promise.resolve(o.input ? false : window.confirm([o.title, o.body].filter(Boolean).join("\n\n")))
  return new Promise((resolve) => enqueue({ ...o, resolve }))
}

export function ConfirmDialogHost() {
  const [item, setItem] = useState(null)
  useEffect(() => {
    enqueue = (it) => setItem(it)
    return () => { enqueue = null }
  }, [])
  const [text, setText] = useState("")
  useEffect(() => { setText(item?.input?.value || "") }, [item])
  const close = (v) => {
    if (item) item.resolve(v)
    setItem(null)
  }
  const minLen = Number(item?.input?.minLength || 1)
  const textOk = !item?.input || text.trim().length >= minLen
  return (
    <AlertDialog open={!!item} onOpenChange={(o) => { if (!o) close(false) }}>
      <AlertDialogContent data-testid="confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{item?.title || "Lanjutkan?"}</AlertDialogTitle>
          {item?.body && <AlertDialogDescription>{item.body}</AlertDialogDescription>}
        </AlertDialogHeader>
        {item?.input && (
          <div className="space-y-1">
            {item.input.label && <label className="text-xs text-muted-foreground" htmlFor="confirm-dialog-input">{item.input.label}</label>}
            <Textarea id="confirm-dialog-input" rows={3} value={text} onChange={(e) => setText(e.target.value)}
              placeholder={item.input.placeholder || ""} data-testid="confirm-dialog-input" />
          </div>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => close(false)} data-testid="confirm-dialog-cancel">{item?.cancelLabel || "Batal"}</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => { if (!textOk) { e.preventDefault(); return } close(item?.input ? text.trim() : true) }}
            disabled={!textOk}
            data-testid="confirm-dialog-ok"
            className={cn(item?.danger && buttonVariants({ variant: "destructive" }))}
          >
            {item?.confirmLabel || "Lanjutkan"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
