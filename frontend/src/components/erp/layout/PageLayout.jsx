/**
 * PageLayout — CETAKAN satu layar (PANDUAN_UI G1, wajib sejak 4 Nov 2026).
 *
 * Layar hanya MENGISI slot; urutan, posisi tombol, dan jarak ditentukan di sini — bukan oleh tiap layar.
 * Dengan begitu tidak ada lagi tombol di tempat acak, baris yang hanya berisi satu tombol, penyaring yang
 * menempel di kanan, atau ruang kosong yang berbeda-beda.
 *
 *   <PageLayout
 *     title="Rekening & Mutasi" subtitle="Saldo tiap rekening dari buku besar."   // disembunyikan di dalam hub
 *     actions={<Button>Rekening baru</Button>}           // kepala kanan; di hub → baris tab (maks 1 tombol utama)
 *     filters={<>…cari, SmartNativeSelect, PeriodPicker, FilterChips…</>}   // toolbar kiri
 *     tools={<>…ikon muat ulang, Unduh, ViewToggle…</>}  // toolbar kanan; tanpa filters → ikut kepala
 *     summary={…StatTile / kalimat ringkasan…}
 *     detail={open && <DetailPanel …/>}                   // detail DI HALAMAN, bukan popup
 *     footer={<PaginationLite …/>}
 *   >
 *     …tabel / laporan / formulir…
 *   </PageLayout>
 *
 * Urutan tetap: kepala → toolbar → ringkasan → detail → isi → kaki. Jarak antarbagian 16 px.
 */
import { Children, useContext } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { CompactHubContext, HubActions, PageHeader } from '../moduleAtoms';
import { toast } from 'sonner';
import { READONLY_HINT, useCv } from '@/lib/entitas';

const filled = (node) => Children.toArray(node).length > 0;

/**
 * Tahap 8 (dua CV): di Portal Keuangan dengan pilihan "Gabungan (lihat saja)", tombol halaman
 * (tambah/ubah) dinonaktifkan + kalimat petunjuk. `fieldset disabled` menonaktifkan semua tombol di
 * dalamnya tanpa mengubah tata letak (`contents`). Alat (muat ulang, unduh) tidak ikut — tetap aktif.
 * Backend juga menolak penulisan dengan CV Gabungan (pengaman kedua).
 */
function ReadOnlyActions({ children }) {
  return (
    <>
      <span className="text-xs text-muted-foreground" data-testid="cv-readonly-hint">{READONLY_HINT}</span>
      <fieldset disabled className="contents" data-testid="cv-readonly-actions" title={READONLY_HINT}>
        {children}
      </fieldset>
    </>
  );
}

/**
 * Tahap 8 fase 3: tombol TULIS di baris tabel / panel detail (Bayar, Ubah, Hapus, Batalkan, Jurnalkan…) juga
 * tidak berlaku di mode Gabungan. Klik ditahan di tingkat cetakan (tanpa mengubah tiap layar) dan diberi petunjuk;
 * tombol baca (Rincian, Lihat, Buka, Unduh, PDF) tetap jalan. Backend tetap menolak tulis Gabungan (pengaman kedua).
 */
const READONLY_WRITE_RX = /^(tambah|ubah|edit|hapus|simpan|bayar|batalkan|batal\b|jurnalkan|posting|terbitkan|setujui|tolak|catat|buat|kirim|void|potong|coba lagi|selesaikan|tutup buku|buka periode|impor|unggah|terima|lunasi|nonaktifkan|aktifkan)/i;

export function readOnlyBlocked(label) {
  return READONLY_WRITE_RX.test(String(label || '').trim());
}

function ReadOnlyContent({ children }) {
  const onClickCapture = (e) => {
    const btn = e.target?.closest?.('button, [role="button"], a[role="menuitem"]');
    if (!btn || btn.closest('[data-cv-allow]')) return;
    const label = btn.getAttribute('aria-label') || btn.textContent || btn.getAttribute('title') || '';
    if (!readOnlyBlocked(label)) return;
    e.preventDefault();
    e.stopPropagation();
    toast.info(READONLY_HINT);
  };
  return <div className="contents" onClickCapture={onClickCapture} data-testid="cv-readonly-content">{children}</div>;
}

/** Baris toolbar: penyaring di kiri, alat di kanan (satu baris, 36 px). Dipakai lewat PageLayout. */
export function Toolbar({ filters, tools, className, testId = 'page-toolbar' }) {
  const compact = useContext(CompactHubContext);
  const hasFilters = filled(filters);
  const hasTools = filled(tools);
  if (!hasFilters && !hasTools) return null;
  // Tanpa penyaring di dalam hub: alat pindah ke baris tab — tidak ada baris yang hanya berisi tombol.
  if (!hasFilters && compact) return <HubActions>{tools}</HubActions>;
  return (
    <div role="toolbar" aria-label="Penyaring dan alat" data-testid={testId} data-page-toolbar=""
      className={cn('flex flex-wrap items-center gap-2 min-h-9', className)}>
      {/* v2: di HP penyaring selebar baris (dulu menyusut ±80 px saat ada alat → kotak cari jadi ikon) */}
      <div className="flex flex-wrap items-center gap-2 min-w-0 flex-1 max-sm:basis-full">{filters}</div>
      {hasTools && <div className="flex items-center gap-2 shrink-0 ml-auto">{tools}</div>}
    </div>
  );
}

export default function PageLayout({
  title, subtitle, actions, filters, tools, summary, detail, footer, children, className, testId, headerTestId,
}) {
  const hasFilters = filled(filters);
  const cvCtx = useCv();
  const pageActions = cvCtx?.readOnly && filled(actions) ? <ReadOnlyActions>{actions}</ReadOnlyActions> : actions;
  // Tanpa penyaring, alat (muat ulang, unduh) ikut kepala/baris tab: [Ikon] [Kedua] [Utama].
  const headerActions = !hasFilters && filled(tools) ? <>{tools}{pageActions}</> : pageActions;
  return (
    <div className={cn('space-y-4 min-w-0', className)} data-testid={testId} data-page-layout="">
      <PageHeader title={title} subtitle={subtitle} testId={headerTestId} actions={filled(headerActions) ? headerActions : null} />
      {hasFilters && <Toolbar filters={filters} tools={tools} />}
      {summary}
      {cvCtx?.readOnly ? <ReadOnlyContent>{detail}{children}</ReadOnlyContent> : <>{detail}{children}</>}
      {footer}
    </div>
  );
}

/**
 * DetailPanel — detail / form satu baris.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026 #1–#2): detail dan form dibuka sebagai POPUP, tidak lagi sebagai
 * panel di atas tabel (dulu G13 lama: panel jauh dari baris yang diklik, halaman melompat, tabel terdorong).
 * Semua layar yang memakai DetailPanel ikut berubah tanpa diubah satu per satu. Lebar 64rem, isi bergulir,
 * di HP penuh layar; × / Esc / klik di luar menutup (memanggil `onClose`).
 * Tanpa `onClose` (panel yang memang bagian tetap halaman) → tetap tampil di halaman seperti dulu.
 * Mode "Gabungan (lihat saja)" tetap berlaku: event klik di dalam popup mengalir ke ReadOnlyContent (React portal).
 */
export function DetailPanel({ title, description, actions, onClose, children, testId = 'detail-panel', closeTestId }) {
  if (!onClose) {
    return (
      <div data-testid={testId} data-detail-panel="">
        <GlassCard className="p-4 space-y-3" role="region" aria-label={typeof title === 'string' ? title : 'Detail'}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-base font-semibold text-foreground leading-tight">{title}</p>
              {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
            </div>
            {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
          </div>
          {children}
        </GlassCard>
      </div>
    );
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent data-testid={testId} data-detail-panel="" closeTestId={closeTestId || `${testId}-close`}
        className={cn(
          'flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-5xl',
          'max-sm:left-0 max-sm:top-0 max-sm:h-[100dvh] max-sm:max-h-none max-sm:max-w-none',
          'max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none',
        )}>
        <div className="flex flex-col gap-3 border-b border-[var(--glass-border)] px-5 py-4 pr-12 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <DialogTitle className="text-base font-semibold leading-tight">{title}</DialogTitle>
            {description && <DialogDescription className="mt-1 text-sm text-muted-foreground">{description}</DialogDescription>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2 sm:justify-end">{actions}</div>}
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">{children}</div>
      </DialogContent>
    </Dialog>
  );
}

/** RowDetail — isi tambahan satu baris tabel, tepat di bawah barisnya (mis. baris-baris jurnal). */
export function RowDetail({ colSpan, children, testId }) {
  return (
    <tr className="row-detail" data-testid={testId} data-row-detail="">
      <td colSpan={colSpan} className="!p-0 bg-foreground/[0.03]">
        <div className="px-4 py-3">{children}</div>
      </td>
    </tr>
  );
}

/** Tombol buka/tutup baris (ikon panah) — pasangan RowDetail. */
export function RowToggle({ open, onClick, label = 'Lihat rincian', testId }) {
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <Button variant="ghost" size="icon-sm" onClick={onClick} aria-expanded={open} title={open ? 'Tutup rincian' : label}
      aria-label={open ? 'Tutup rincian' : label} data-testid={testId}>
      <Icon className="w-4 h-4" />
    </Button>
  );
}
