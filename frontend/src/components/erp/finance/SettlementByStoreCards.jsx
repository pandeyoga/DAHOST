/**
 * SettlementByStoreCards — kartu ringkas per toko untuk satu bulan: berapa persen omzet bruto
 * yang dipotong platform, dipecah komisi/iklan/refund, supaya Shopee vs TikTok bisa dibandingkan.
 * 2026-11-08 (Standar UI/UX v2): satu TABEL (dulu satu kartu abu per toko), bisa diunduh Excel/CSV; tanpa kapital.
 */
import { useCallback, useEffect, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { ChevronLeft, ChevronRight, Store, Loader2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { formatRupiah as rp } from '@/lib/format';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState } from '../moduleAtoms';
import { namaPlatform } from './PlatformBalanceCards';

const API = process.env.REACT_APP_BACKEND_URL;

function monthLabel(m) {
  if (!m) return '—';
  const [y, mo] = m.split('-');
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  return `${names[parseInt(mo, 10) - 1] || mo} ${y}`;
}

// 2026-11-05 (PANDUAN_UI G8): warna hanya token — merah = potongan jauh di atas rata-rata.
function pctTone(p, avg) {
  if (p > avg + 2) return 'text-[hsl(var(--danger-text))]';
  if (p < avg - 2) return 'text-[hsl(var(--success-text))]';
  return 'text-foreground';
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
    <GlassCard className="p-0 overflow-hidden" data-testid="fin-settlement-by-store">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3 pb-2">
        <div className="min-w-0">
          <p className="font-semibold text-base text-foreground flex items-center gap-2">
            <Store className="w-4 h-4 text-muted-foreground" /> Potongan per toko
          </p>
          <p className="text-sm text-muted-foreground tabular-nums">
            Rata-rata {String(res?.average_deduction_pct ?? 0).replace('.', ',')}% dari bruto · merah = jauh di atas rata-rata
          </p>
        </div>
        <div className="flex items-center gap-1">
          <TombolUnduh namaBerkas={`potongan-per-toko-${res?.month || ''}`} namaLembar="Potongan per toko" baris={res?.data || []} testId="fin-settlement-by-store-unduh"
            kolom={[
              { label: 'Bulan', nilai: () => monthLabel(res?.month) },
              { label: 'Toko', nilai: (x) => x.account_name },
              { label: 'Platform', nilai: (x) => namaPlatform(x.platform) },
              { label: 'Jumlah pencairan', nilai: (x) => Number(x.count) || 0 },
              { label: 'Omzet bruto', nilai: (x) => Number(x.gross_sales) || 0 },
              { label: 'Potongan %', nilai: (x) => Number(x.deduction_pct) || 0 },
              { label: 'Komisi %', nilai: (x) => Number(x.commission_pct) || 0 },
              { label: 'Iklan %', nilai: (x) => Number(x.ads_pct) || 0 },
              { label: 'Refund %', nilai: (x) => Number(x.refund_pct) || 0 },
              { label: 'Masuk saldo', nilai: (x) => Number(x.net_payout) || 0 },
              { label: 'Belum seimbang', nilai: (x) => Number(x.unverified_count) || 0 },
            ]} />
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
        <div className="py-6 text-center text-sm text-muted-foreground flex items-center justify-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> memuat…
        </div>
      ) : !res?.data?.length ? (
        <EmptyState icon={Store} className="py-6" testId="fin-settlement-by-store-empty"
          title={`Belum ada dana dilepas tercatat untuk ${monthLabel(res?.month)}`}
          description="Potongan per toko muncul setelah laporan dana dilepas dicatat." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="text-left">Toko</th>
                <th className="text-right">Potongan</th>
                <th className="text-right hidden md:table-cell">Komisi</th>
                <th className="text-right hidden md:table-cell">Iklan</th>
                <th className="text-right hidden md:table-cell">Refund</th>
                <th className="text-right hidden sm:table-cell">Omzet bruto</th>
                <th className="text-right">Masuk saldo</th>
              </tr>
            </thead>
            <tbody>
              {res.data.map((x) => (
                <tr key={x.account_id} data-testid={`fin-settlement-store-card-${x.account_id}`}>
                  <td>
                    <span className="font-medium text-foreground">{x.account_name}</span>
                    <span className="block text-xs text-muted-foreground">{namaPlatform(x.platform)} · {x.count} pencairan
                      {x.unverified_count > 0 ? (
                        <span className="ml-1 inline-flex items-center gap-1 text-[hsl(var(--danger-text))]">
                          <AlertTriangle className="w-3 h-3" /> {x.unverified_count} belum seimbang
                        </span>
                      ) : null}
                    </span>
                  </td>
                  <td className={`text-right tabular-nums font-semibold ${pctTone(x.deduction_pct, res.average_deduction_pct)}`}>{String(x.deduction_pct).replace('.', ',')}%</td>
                  <td className="text-right tabular-nums hidden md:table-cell">{String(x.commission_pct).replace('.', ',')}%</td>
                  <td className="text-right tabular-nums hidden md:table-cell">{String(x.ads_pct).replace('.', ',')}%</td>
                  <td className="text-right tabular-nums hidden md:table-cell">{String(x.refund_pct).replace('.', ',')}%</td>
                  <td className="text-right tabular-nums whitespace-nowrap hidden sm:table-cell">{rp(x.gross_sales)}</td>
                  <td className="text-right tabular-nums whitespace-nowrap font-medium">{rp(x.net_payout)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassCard>
  );
}
