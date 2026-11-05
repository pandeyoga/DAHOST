/**
 * SettlementByStoreCards — kartu ringkas per toko untuk satu bulan: berapa persen omzet bruto
 * yang dipotong platform, dipecah komisi/iklan/refund, supaya Shopee vs TikTok bisa dibandingkan.
 */
import { useCallback, useEffect, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { ChevronLeft, ChevronRight, Store, Loader2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { formatRupiah as rp } from '@/lib/format';
import { EmptyState } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

function monthLabel(m) {
  if (!m) return '—';
  const [y, mo] = m.split('-');
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  return `${names[parseInt(mo, 10) - 1] || mo} ${y}`;
}

// 2026-11-05 (PANDUAN_UI G8): warna hanya token — merah = potongan jauh di atas rata-rata.
function pctTone(p, avg) {
  if (p > avg + 2) return 'text-[hsl(var(--destructive))]';
  if (p < avg - 2) return 'text-[hsl(var(--success))]';
  return 'text-[hsl(var(--warning))]';
}

export function SettlementByStoreCards({ refreshKey, month: monthProp = '' }) {
  const [month, setMonth] = useState(monthProp);
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(true);

  // Filter bulan di daftar pencairan ikut menggerakkan kartu ini (satu periode, satu layar).
  useEffect(() => { setMonth(monthProp); }, [monthProp]);

  const load = useCallback(async (m) => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/marketing/settlements/by-account?month=${m || ''}`,
        { headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` } });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal memuat ringkasan per toko');
      setRes(d);
      if (!m) setMonth(d.month);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(month); }, [month, load, refreshKey]);

  const months = res?.months || [];
  const idx = months.indexOf(res?.month);
  const step = (dir) => {
    const next = months[idx + dir];
    if (next) setMonth(next);
  };

  return (
    <GlassCard className="p-4 space-y-3" data-testid="fin-settlement-by-store">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium text-sm flex items-center gap-2">
          <Store className="w-4 h-4" /> Potongan per toko
          <span className="text-xs text-muted-foreground font-normal tabular-nums">
            rata-rata {res?.average_deduction_pct ?? 0}% dari bruto
          </span>
        </h3>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon-sm" data-testid="fin-settlement-by-store-prev" onClick={() => step(1)}
            disabled={idx < 0 || idx >= months.length - 1} title="Bulan sebelumnya" aria-label="Bulan sebelumnya">
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <SmartNativeSelect data-testid="fin-settlement-by-store-month" value={res?.month || month}
            onChange={(e) => setMonth(e.target.value)} className="h-8 w-36" aria-label="Bulan">
            {(months.length ? months : [res?.month || month].filter(Boolean)).map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </SmartNativeSelect>
          <Button variant="outline" size="icon-sm" data-testid="fin-settlement-by-store-next" onClick={() => step(-1)}
            disabled={idx <= 0} title="Bulan berikutnya" aria-label="Bulan berikutnya">
            <ChevronRight className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="py-6 text-center text-xs text-muted-foreground flex items-center justify-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> memuat…
        </div>
      ) : !res?.data?.length ? (
        <EmptyState icon={Store} className="py-6" testId="fin-settlement-by-store-empty"
          title={`Belum ada dana dilepas tercatat untuk ${monthLabel(res?.month)}`}
          description="Potongan per toko muncul setelah laporan dana dilepas dicatat." />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {res.data.map((s) => (
            <div key={s.account_id} className="rounded-xl bg-foreground/5 p-3 space-y-1.5"
              data-testid={`fin-settlement-store-card-${s.account_id}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">{s.account_name}</div>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    {s.platform} · {s.count} pencairan
                  </div>
                </div>
                <div className={`text-xl font-semibold tabular-nums ${pctTone(s.deduction_pct, res.average_deduction_pct)}`}>
                  {s.deduction_pct}%
                </div>
              </div>
              <div className="h-1.5 rounded-full bg-foreground/10 overflow-hidden">
                <div className="h-full bg-[hsl(var(--warning))]" style={{ width: `${Math.min(100, s.deduction_pct)}%` }} />
              </div>
              <div className="grid grid-cols-3 gap-1 text-[10px] text-muted-foreground tabular-nums">
                <div>komisi <b>{s.commission_pct}%</b></div>
                <div>iklan <b>{s.ads_pct}%</b></div>
                <div>refund <b>{s.refund_pct}%</b></div>
              </div>
              <div className="text-xs text-muted-foreground tabular-nums">
                bruto {rp(s.gross_sales)} → masuk saldo <b className="text-foreground whitespace-nowrap">{rp(s.net_payout)}</b>
              </div>
              {s.unverified_count > 0 ? (
                <div className="text-[10px] text-[hsl(var(--destructive))] flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> {s.unverified_count} belum seimbang
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
