/**
 * TopBar — sticky header bar of the PortalShell.
 *
 * Contains:
 *   - Mobile menu toggle
 *   - Brand button (click → back to portal selector)
 *   - Section pill nav (THE MENU)
 *   - Global search
 *   - Command palette shortcut button (⌘K hint)
 *   - Notification bell = SATU kotak masuk (Perlu Tindakan + Pemberitahuan)
 *   - Account dropdown
 *
 * 2026-11-02 (K30) — ikon "Approval Inbox" (ApprovalBadge) terpisah dihapus:
 * hitungannya dilebur ke tab "Perlu Tindakan" di bel, tanpa hitung dobel.
 */

import {
  Menu, ChevronLeft, Command as CommandIcon,
} from 'lucide-react';
import { NotificationBell } from '../NotificationBell';
import { ScanLine } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { useCv } from '@/lib/entitas';
import GlobalSearch from './GlobalSearch';
import AccountMenu from './AccountMenu';
import { PORTAL_LABEL, formatSectionLabel } from './portalNav';

/**
 * Tahap 8 (dua CV, keputusan owner K1): pilihan buku di kepala Portal Keuangan —
 * "CV Dewi Aditya" / "CV Sukma" / "Gabungan (lihat saja)". Hanya tampil di dalam CvProvider
 * (Portal Keuangan); pilihan disimpan per peramban dan dikirim ke backend lewat header X-CV.
 */
function CvPicker() {
  const ctx = useCv();
  if (!ctx) return null;
  // shrink-0: tanpa pembungkus ini kotak pilihan menyusut di baris kepala dan tertimpa kotak cari.
  return (
    <div className="shrink-0 w-28 sm:w-48">
      <SmartNativeSelect
        value={ctx.cv}
        onChange={(e) => ctx.setCv(e.target.value)}
        data-testid="cv-picker"
        aria-label="Pilih buku CV"
        title="Buku CV yang sedang dibuka"
        searchable={false}
        className="h-9 w-full text-xs sm:text-sm"
      >
        {ctx.options.map((o) => (
          <option key={o.code} value={o.code}>{o.label}</option>
        ))}
      </SmartNativeSelect>
    </div>
  );
}

export default function TopBar({
  portal,
  nav,
  activeSectionIndex,
  user,
  token,
  onBack,
  onLogout,
  onModuleChange,
  onSectionPillClick,
  onOpenMobile,
  onOpenCmdk,
  onOpenHelp,
  onOpenGuide,
  singleDoor = false,
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--glass-border)] bg-[var(--card-surface)] backdrop-blur-[var(--glass-blur-strong)]">
      <div className="flex items-center gap-3 px-3 sm:px-5 py-2.5">
        {/* Mobile menu toggle — disembunyikan pada portal satu pintu (tidak ada sidebar) */}
        <button
          className={`${singleDoor ? 'hidden' : 'md:hidden'} p-1.5 rounded-lg text-foreground/60 hover:text-foreground hover:bg-[var(--nav-pill-active)] transition-colors duration-150`}
          onClick={onOpenMobile}
          data-testid="mobile-menu-btn"
          aria-label="Buka menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Brand + Portal badge (click brand → back to portal selector) */}
        <button
          onClick={onBack}
          className="flex items-center gap-2.5 shrink-0 group transition-opacity duration-150 hover:opacity-80"
          data-testid="portal-back-btn"
          aria-label="Kembali ke pilih portal"
          title="Klik untuk ganti portal"
        >
          <div className="w-9 h-9 rounded-[12px] bg-gradient-to-br from-[hsl(var(--primary)/0.20)] to-[hsl(var(--accent)/0.20)] border border-[hsl(var(--primary)/0.30)] grid place-items-center text-[hsl(var(--primary))] group-hover:scale-105 transition-transform duration-150 shadow-[var(--shadow-glow-blue)]">
            {/* CV. Dewi Aditya — fashion brand mark (SVG inline) */}
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M20.38 3.46 16 2 12 5.5 8 2 3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z" />
            </svg>
          </div>
          <div className="hidden md:flex flex-col leading-tight text-left">
            <span className="text-[10px] uppercase tracking-wider text-foreground/40 font-semibold">
              Portal
            </span>
            <span className="text-sm font-semibold text-foreground -mt-0.5">
              {PORTAL_LABEL[portal] || portal}
            </span>
          </div>
          <ChevronLeft className="hidden md:block w-3.5 h-3.5 text-foreground/30 ml-0.5 group-hover:text-foreground/60 transition-colors duration-150" />
        </button>

        {/* Section pill nav — THE MENU (sections of current portal).
            IA v4: portal satu pintu tidak menampilkan pill (hanya 1 section, 1 pintu). */}
        {/* 2026-11-04: portal ber-section tunggal (mis. Keuangan 8 grup di menu samping) tidak perlu pill */}
        {!singleDoor && nav.sections.length > 1 && (
        <nav
          className="hidden md:inline-flex items-center gap-1 rounded-full border border-[var(--glass-border)] bg-[var(--nav-pill-bg)] backdrop-blur-xl p-1 overflow-x-auto max-w-[55vw]"
          data-testid="section-pill-nav"
          aria-label="Menu portal"
        >
          {nav.sections.map((s, idx) => {
            const active = idx === activeSectionIndex;
            return (
              <button
                key={s.label}
                onClick={() => onSectionPillClick(s.label)}
                className={`relative inline-flex items-center gap-2 rounded-full px-3 lg:px-4 py-1.5 text-xs lg:text-sm font-medium whitespace-nowrap
                  transition-[background-color,color,box-shadow] duration-200 ease-smooth-out
                  ${
                    active
                      ? 'bg-[var(--nav-pill-active)] text-foreground shadow-[var(--shadow-glow-blue)]'
                      : 'text-foreground/60 hover:text-foreground hover:bg-[var(--nav-pill-active)]/60'
                  }`}
                data-testid={`section-pill-${idx}`}
                aria-pressed={active}
                aria-label={`Menu ${s.label}`}
              >
                <span className={active ? 'text-[hsl(var(--primary))]' : ''}>
                  {formatSectionLabel(s.label)}
                </span>
              </button>
            );
          })}
        </nav>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Tahap 8: pilihan buku CV (hanya Portal Keuangan) */}
        <CvPicker />

        {/* Global Search */}
        <GlobalSearch token={token} onResultSelect={onModuleChange} />

        {/* ── Right side: Notif + Account dropdown ── */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* Command Palette shortcut (keyboard only hint, small) */}
          <button
            onClick={onOpenCmdk}
            className="hidden lg:inline-flex items-center gap-1.5 h-8 px-2.5 rounded-full border border-[var(--glass-border)] bg-[var(--nav-pill-bg)] text-foreground/50 hover:text-foreground hover:bg-[var(--nav-pill-active)] transition-colors duration-150"
            data-testid="topbar-cmdk-trigger"
            title="Command Palette (Ctrl/Cmd + K)"
            aria-label="Buka Command Palette"
          >
            <CommandIcon className="w-3 h-3" />
            <span className="text-[10px] font-semibold tracking-wider uppercase opacity-60">⌘K</span>
          </button>

          {/* 2026-11-06 — Scan universal di kepala halaman (dulu bulatan mengambang yang menutupi isi
              di HP, tepat di bekas tombol chat). Event dibaca `scanner/UniversalScanPortal`. */}
          <Button variant="outline" size="icon" title="Scan barcode (Ctrl+Shift+S)" aria-label="Scan barcode"
            onClick={() => window.dispatchEvent(new CustomEvent('erp-universal-scan'))}
            data-testid="universal-scan-fab">
            <ScanLine className="w-4 h-4" />
          </Button>

          {/* Kotak masuk (bel): Perlu Tindakan + Pemberitahuan */}
          <NotificationBell
            token={token}
            onNavigateModule={(moduleId) => {
              if (moduleId) onModuleChange(moduleId);
            }}
          />

          {/* Account Dropdown */}
          <AccountMenu
            user={user}
            onOpenCmdk={onOpenCmdk}
            onOpenHelp={onOpenHelp}
            onOpenGuide={onOpenGuide}
            onLogout={onLogout}
          />
        </div>
      </div>
    </header>
  );
}
