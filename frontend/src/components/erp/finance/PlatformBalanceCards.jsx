/**
 * PlatformBalanceCards — saldo tiap toko yang MASIH di platform (Shopee/TikTok).
 * saldo = Σ dana dilepas (tahap 1) − Σ penarikan ke bank (tahap 2).
 * `gl_balance` = saldo akun 1-1303-xxx di buku besar (hanya jurnal yang sudah posting).
 */
import { useEffect, useState } from 'react';
import { Wallet, Loader2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { formatRupiah as rp } from '@/lib/format';
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

export function PlatformBalanceCards({ refreshKey }) {
  const { data, loading } = usePlatformBalances(refreshKey);
  const rows = (data?.data || []).filter((r) => r.status !== 'archived');

  // 2026-11-05 (PANDUAN_UI G7/G8): angka tanpa font-mono, warna hanya token; saldo positif netral (hijau = lunas),
  // minus merah. "GL" ditulis "buku besar".
  return (
    <GlassCard className="p-4 space-y-3" data-testid="platform-balance-cards">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-sm flex items-center gap-2">
          <Wallet className="w-4 h-4" /> Saldo di platform per toko
          <span className="text-xs text-muted-foreground font-normal">— yang masih bisa ditarik ke bank</span>
        </h3>
        <div className="text-xs text-muted-foreground" data-testid="platform-balance-total">
          Total saldo platform: <b className="text-foreground tabular-nums">{rp(data?.total_balance || 0)}</b>
          <span className="ml-2 tabular-nums">dilepas {rp(data?.total_released || 0)} · ditarik {rp(data?.total_withdrawn || 0)}</span>
        </div>
      </div>
      {loading ? (
        <div className="py-4 text-xs text-muted-foreground flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> memuat saldo…</div>
      ) : rows.length === 0 ? (
        <EmptyState icon={Wallet} title="Belum ada toko" className="py-6"
          description="Saldo muncul setelah toko marketplace dibuat dan dana dilepas dicatat." />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
          {rows.map((r) => {
            const glDiff = r.gl_balance == null ? 0 : Math.round((r.balance - r.gl_balance) * 100) / 100;
            return (
              <div key={r.account_id} className="rounded-lg bg-foreground/5 p-3 text-xs space-y-1"
                data-testid={`platform-balance-${r.account_code || r.account_id}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium truncate" title={r.account_name}>{r.account_name}</span>
                  <span className="uppercase text-[10px] text-muted-foreground">{r.platform}</span>
                </div>
                <div className={`text-lg font-semibold tabular-nums whitespace-nowrap ${r.balance < 0 ? 'text-[hsl(var(--destructive))]' : 'text-foreground'}`}
                  data-testid={`platform-balance-amount-${r.account_code || r.account_id}`}>{rp(r.balance)}</div>
                <div className="text-muted-foreground tabular-nums">dilepas {rp(r.released_total)} ({r.released_count}) · ditarik {rp(r.withdrawn_total)} ({r.withdrawn_count})</div>
                <div className="text-[10px] text-muted-foreground tabular-nums">
                  {r.receivable_code || 'akun piutang toko belum ada'}
                  {r.gl_balance != null ? ` · buku besar ${rp(r.gl_balance)}` : ''}
                </div>
                {Math.abs(glDiff) >= 1 ? (
                  <div className="text-[10px] text-[hsl(var(--warning))] flex items-center gap-1" title="Ada dokumen yang belum dijurnal/diposting">
                    <AlertTriangle className="w-3 h-3" /> belum diposting {rp(glDiff)}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
