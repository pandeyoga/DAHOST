/**
 * AccountBadge & PlatformBadge — lencana akun / platform toko. Dipakai di semua modul Portal Marketing.
 *
 * Standar UI/UX v2 (8 Nov 2026): satu gaya lencana netral (token tema), tanpa emoji dan tanpa warna merek per
 * platform (dulu oranye/merah muda/hijau dengan kontras rendah, mis. "Shopee GHS" 2,45:1). Nama platform tetap
 * tampil sebagai teks. Bentuk `PLATFORM_CONFIG` / `getPlatformConfig` dipertahankan untuk layar lain yang memakainya
 * (label, icon kosong, kelas warna token).
 */

const NETRAL = {
  bg: 'bg-[var(--card-surface)]',
  text: 'text-foreground',
  border: 'border-[var(--glass-border)]',
  dot: 'bg-primary',
  icon: '',
};

export const PLATFORM_CONFIG = {
  shopee: { label: 'Shopee', ...NETRAL },
  tiktokshop: { label: 'TikTok', ...NETRAL },
  tokopedia: { label: 'Tokopedia', ...NETRAL },
  lazada: { label: 'Lazada', ...NETRAL },
  blibli: { label: 'Blibli', ...NETRAL },
};

const DEFAULT_CONFIG = { label: 'Platform', ...NETRAL, text: 'text-muted-foreground' };

export function getPlatformConfig(platform) {
  return PLATFORM_CONFIG[(platform || '').toLowerCase()] || DEFAULT_CONFIG;
}

const SIZE_CLASSES = {
  xs: 'text-xs px-1.5 py-0.5 gap-1',
  sm: 'text-xs px-2 py-0.5 gap-1.5',
  md: 'text-sm px-2.5 py-1 gap-2',
};

/**
 * AccountBadge — lencana nama akun (platform di keterangan arahkan-kursor).
 * Props: account { account_name, platform, account_code? }, size 'xs' | 'sm' | 'md', showIcon (diabaikan: tanpa ikon).
 */
export function AccountBadge({ account, size = 'sm', showIcon: _showIcon = true }) {
  if (!account) return null;
  const cfg = getPlatformConfig(account.platform);
  const sz = SIZE_CLASSES[size] || SIZE_CLASSES.sm;
  return (
    <span title={`${account.account_name} · ${cfg.label}`}
      className={`inline-flex max-w-full items-center whitespace-nowrap rounded-full border font-medium ${cfg.bg} ${cfg.text} ${cfg.border} ${sz}`}>
      <span className="max-w-[160px] truncate">{account.account_name}</span>
    </span>
  );
}

/** PlatformBadge — lencana platform saja (tanpa nama akun). */
export function PlatformBadge({ platform, size = 'sm' }) {
  const cfg = getPlatformConfig(platform);
  const sz = SIZE_CLASSES[size] || SIZE_CLASSES.sm;
  return (
    <span className={`inline-flex items-center rounded-full border font-medium ${cfg.bg} ${cfg.text} ${cfg.border} ${sz}`}>
      {cfg.label}
    </span>
  );
}
