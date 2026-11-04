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
import { Children, useContext, useEffect, useRef } from 'react';
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { cn } from '@/lib/utils';
import { CompactHubContext, HubActions, PageHeader } from '../moduleAtoms';

const filled = (node) => Children.toArray(node).length > 0;

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
      <div className="flex flex-wrap items-center gap-2 min-w-0 flex-1">{filters}</div>
      {hasTools && <div className="flex items-center gap-2 shrink-0 ml-auto">{tools}</div>}
    </div>
  );
}

export default function PageLayout({
  title, subtitle, actions, filters, tools, summary, detail, footer, children, className, testId,
}) {
  const hasFilters = filled(filters);
  // Tanpa penyaring, alat (muat ulang, unduh) ikut kepala/baris tab: [Ikon] [Kedua] [Utama].
  const headerActions = !hasFilters && filled(tools) ? <>{tools}{actions}</> : actions;
  return (
    <div className={cn('space-y-4 min-w-0', className)} data-testid={testId} data-page-layout="">
      <PageHeader title={title} subtitle={subtitle} actions={filled(headerActions) ? headerActions : null} />
      {hasFilters && <Toolbar filters={filters} tools={tools} />}
      {summary}
      {detail}
      {children}
      {footer}
    </div>
  );
}

/**
 * DetailPanel — detail satu baris DI HALAMAN, lebar penuh, di atas tabel (PANDUAN_UI G13).
 * Pengganti popup/Sheet untuk daftar dan detail: isi tidak terpotong, tabel bisa memakai lebar penuh.
 * Esc atau tombol × menutup. Saat dibuka, halaman bergulir ke panel.
 */
export function DetailPanel({ title, description, actions, onClose, children, testId = 'detail-panel' }) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); }, []);
  useEffect(() => {
    if (!onClose) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div ref={ref} data-testid={testId} data-detail-panel="">
      <GlassCard className="p-4 space-y-3" role="region" aria-label={typeof title === 'string' ? title : 'Detail'}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-base font-semibold text-foreground leading-tight">{title}</p>
            {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {actions}
            {onClose && (
              <Button variant="outline" size="icon" onClick={onClose} title="Tutup" aria-label="Tutup" data-testid={`${testId}-close`}>
                <X className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
        {children}
      </GlassCard>
    </div>
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
