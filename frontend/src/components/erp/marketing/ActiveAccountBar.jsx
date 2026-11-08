/**
 * ActiveAccountBar
 * Pemilih "akun aktif" untuk modul marketing: akun mana yang sedang difokuskan (data & isian).
 * State disimpan via useActiveMarketingAccount (localStorage).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu bilah selebar halaman berlatar abu/berwarna platform dengan tombol
 * "Ganti Akun" di ujung kanan. Kini satu tombol pilihan ringkas yang muat di baris penyaring (`filters`)
 * PageLayout. Props tidak berubah (juga dipakai Live, KOL, Ulasan, Komplain/Retur, Input Sales, Iklan).
 */
import { ChevronDown, Store, X, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { getPlatformConfig } from './AccountBadge';

/**
 * @param {object[]} accounts        - daftar semua akun platform
 * @param {object|null} activeAccount - akun yang sedang aktif (atau null)
 * @param {function} onAccountChange - dipanggil dengan object akun baru atau null
 * @param {string} [hint]            - teks keterangan singkat (tampil sebagai judul menu & tooltip)
 */
export function ActiveAccountBar({ accounts = [], activeAccount, onAccountChange, hint }) {
  const activeAccounts = accounts.filter(a => a.status === 'active' || !a.status);
  const keterangan = hint || 'Akun aktif';

  return (
    <div data-testid="active-account-bar" className="flex min-w-0 items-center">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" className="w-full justify-start sm:w-56" title={keterangan}
            data-testid="switch-account-btn">
            <Store className="text-muted-foreground" />
            <span className="truncate">{activeAccount ? activeAccount.account_name : 'Semua akun'}</span>
            <ChevronDown className="ml-auto text-muted-foreground" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">{keterangan}</DropdownMenuLabel>
          {activeAccounts.length === 0 && (
            <DropdownMenuItem disabled className="text-sm text-muted-foreground">
              Belum ada akun aktif
            </DropdownMenuItem>
          )}
          {activeAccounts.map(acc => {
            const c = getPlatformConfig(acc.platform);
            const isSelected = activeAccount?.id === acc.id;
            return (
              <DropdownMenuItem
                key={acc.id}
                onClick={() => onAccountChange(acc)}
                className="flex cursor-pointer items-center gap-2"
                data-testid={`switch-to-${acc.id}`}
              >
                <div className="min-w-0 flex-1">
                  <div className={`truncate text-sm ${isSelected ? 'font-medium text-[hsl(var(--primary))]' : ''}`}>
                    {acc.account_name}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {c.label} · {acc.account_code}
                  </div>
                </div>
                {isSelected && <Check size={14} className="shrink-0 text-[hsl(var(--primary))]" />}
              </DropdownMenuItem>
            );
          })}

          {activeAccount && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onAccountChange(null)}
                className="cursor-pointer text-sm text-muted-foreground"
                data-testid="clear-active-account"
              >
                <X size={14} className="mr-2" /> Lihat semua akun
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
