/**
 * PlatformBalanceCards — saldo tiap toko yang MASIH di platform (Shopee/TikTok).
 * saldo = Σ dana dilepas (tahap 1) − Σ penarikan ke bank (tahap 2).
 * `gl_balance` = saldo akun 1-1303-xxx di buku besar (hanya jurnal yang sudah posting).
 */
import { useEffect, useState } from 'react';
import { Wallet, Loader2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { formatRupiah as rp } from '@/lib/format';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

export function usePlatformBalances(refreshKey) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch(`${API}/api/marketing/settlements/platform-balance`,
      { headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` } })
      .then((r) => r.json())
      .then((d) => { if (alive) setData(d); })
      .catch(() => { if (alive) setData(null); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [refreshKey]);
  return { data, loading };
}

const PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
export const namaPlatform = (p) => PLATFORM[String(p || '').toLowerCase()]
  || (p ? String(p).charAt(0).toUpperCase() + String(p).slice(1).toLowerCase() : '');

/**
 * 2026-11-08 (Standar UI/UX v2, keluhan owner "daftar kartu berulang"): saldo per toko = TABEL (dulu satu kartu
 * abu per toko), bisa diunduh Excel/CSV; platform ditulis "Shopee/TikTok" (dulu SHOPEE kapital).
 * Ekspor `usePlatformBalances` tetap (dipakai Toko › Akun marketplace).
 */
export function PlatformBalanceCards({ refreshKey }) {
  const { data, loading } = usePlatformBalances(refreshKey);
  const rows = (data?.data || []).filter((r) => r.status !== 'archived');
  const glDiffOf = (r) => (r.gl_balance == null ? 0 : Math.round((r.balance - r.gl_balance) * 100) / 100);

  return (
    <GlassCard className="p-0 overflow-hidden" data-testid="platform-balance-cards">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3 pb-2">
        <div className="min-w-0">
          <p className="font-semibold text-base text-foreground flex items-center gap-2">
            <Wallet className="w-4 h-4 text-muted-foreground" /> Saldo di platform per toko
          </p>
          <p className="text-sm text-muted-foreground" data-testid="platform-balance-total">
            Yang masih bisa ditarik ke bank: <b className="text-foreground tabular-nums">{rp(data?.total_balance || 0)}</b>
            <span className="block sm:inline sm:ml-1 tabular-nums">(dilepas {rp(data?.total_released || 0)} − ditarik {rp(data?.total_withdrawn || 0)})</span>
          </p>
        </div>
        <TombolUnduh namaBerkas="saldo-platform-per-toko" namaLembar="Saldo platform" baris={rows} testId="platform-balance-unduh"
          kolom={[
            { label: 'Toko', nilai: (r) => r.account_name },
            { label: 'Platform', nilai: (r) => namaPlatform(r.platform) },
            { label: 'Saldo di platform', nilai: (r) => Number(r.balance) || 0 },
            { label: 'Dilepas', nilai: (r) => Number(r.released_total) || 0 },
            { label: 'Jumlah dilepas', nilai: (r) => Number(r.released_count) || 0 },
            { label: 'Ditarik', nilai: (r) => Number(r.withdrawn_total) || 0 },
            { label: 'Jumlah ditarik', nilai: (r) => Number(r.withdrawn_count) || 0 },
            { label: 'Akun piutang toko', nilai: (r) => r.receivable_code || '' },
            { label: 'Saldo buku besar', nilai: (r) => (r.gl_balance == null ? '' : Number(r.gl_balance) || 0) },
            { label: 'Belum diposting', nilai: (r) => glDiffOf(r) },
          ]} />
      </div>
      {loading ? (
        <div className="px-4 py-4 text-sm text-muted-foreground flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> memuat saldo…</div>
      ) : rows.length === 0 ? (
        <EmptyState icon={Wallet} title="Belum ada toko" className="py-6"
          description="Saldo muncul setelah toko marketplace dibuat dan dana dilepas dicatat." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="text-left">Toko</th>
                <th className="text-right">Saldo di platform</th>
                <th className="text-right hidden md:table-cell">Dilepas</th>
                <th className="text-right hidden md:table-cell">Ditarik</th>
                <th className="text-left hidden lg:table-cell">Akun · buku besar</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const glDiff = glDiffOf(r);
                return (
                  <tr key={r.account_id} data-testid={`platform-balance-${r.account_code || r.account_id}`}>
                    <td>
                      <span className="font-medium text-foreground">{r.account_name}</span>
                      <span className="block text-xs text-muted-foreground">{namaPlatform(r.platform)}</span>
                    </td>
                    <td className={`text-right tabular-nums whitespace-nowrap font-semibold ${r.balance < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`}
                      data-testid={`platform-balance-amount-${r.account_code || r.account_id}`}>{rp(r.balance)}</td>
                    <td className="text-right tabular-nums whitespace-nowrap hidden md:table-cell">{rp(r.released_total)} <span className="text-muted-foreground">({r.released_count})</span></td>
                    <td className="text-right tabular-nums whitespace-nowrap hidden md:table-cell">{rp(r.withdrawn_total)} <span className="text-muted-foreground">({r.withdrawn_count})</span></td>
                    <td className="text-muted-foreground hidden lg:table-cell">
                      {r.receivable_code || 'akun piutang toko belum ada'}
                      {r.gl_balance != null ? <span className="tabular-nums"> · {rp(r.gl_balance)}</span> : ''}
                      {Math.abs(glDiff) >= 1 ? (
                        <span className="ml-1 inline-flex items-center gap-1 text-[hsl(var(--warning-text))]" title="Ada dokumen yang belum dijurnal/diposting">
                          <AlertTriangle className="w-3.5 h-3.5" /> belum diposting {rp(glDiff)}
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </GlassCard>
  );
}
