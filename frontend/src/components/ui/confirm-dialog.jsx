import { useEffect, useState } from "react"
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
 */
let enqueue = null

export function confirmDialog(opts) {
  const o = typeof opts === "string" ? { title: opts } : (opts || {})
  if (!enqueue) return Promise.resolve(window.confirm([o.title, o.body].filter(Boolean).join("\n\n")))
  return new Promise((resolve) => enqueue({ ...o, resolve }))
}

export function ConfirmDialogHost() {
  const [item, setItem] = useState(null)
  useEffect(() => {
    enqueue = (it) => setItem(it)
    return () => { enqueue = null }
  }, [])
  const close = (v) => {
    if (item) item.resolve(v)
    setItem(null)
  }
  return (
    <AlertDialog open={!!item} onOpenChange={(o) => { if (!o) close(false) }}>
      <AlertDialogContent data-testid="confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{item?.title || "Lanjutkan?"}</AlertDialogTitle>
          {item?.body && <AlertDialogDescription>{item.body}</AlertDialogDescription>}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => close(false)} data-testid="confirm-dialog-cancel">{item?.cancelLabel || "Batal"}</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => close(true)}
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
