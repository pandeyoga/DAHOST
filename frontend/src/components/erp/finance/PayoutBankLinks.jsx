/**
 * PayoutBankLinks — Finance menautkan rekening pencairan default tiap toko.
 * Daftar rekening = master Kas & Bank + COA kas/bank/e-wallet aktif (semua bank, bukan cuma yang ber-flag).
 */
import { useEffect, useState } from 'react';
import { Landmark, Loader2, CheckCircle2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;
const BASE = `${API}/api/marketing/withdrawals`;
const auth = () => ({ Authorization: `Bearer ${localStorage.getItem('erp_token')}` });

export function useBankOptions() {
  const [banks, setBanks] = useState([]);
  useEffect(() => {
    fetch(`${BASE}/bank-options`, { headers: auth() })
      .then((r) => r.json())
      .then((d) => setBanks(d.data || []))
      .catch(() => setBanks([]));
  }, []);
  return banks;
}

export const bankLabel = (b) => `${b.code} · ${b.name}${b.account_number ? ` (${b.account_number})` : ''}`;

export function BankSelect({ banks, value, onChange, testId, emptyLabel = '— pilih rekening —', className = '' }) {
  return (
    <select data-testid={testId} value={value || ''} onChange={(e) => onChange(e.target.value)}
      className={`w-full h-9 bg-foreground/5 border border-foreground/10 rounded-lg px-2 text-sm ${className}`}>
      <option value="">{emptyLabel}</option>
      {banks.map((b) => <option key={b.code} value={b.code}>{bankLabel(b)}</option>)}
    </select>
  );
}

export function PayoutBankLinks({ accounts, banks, onChanged }) {
  const [busy, setBusy] = useState('');
  const active = accounts.filter((a) => a.status !== 'archived' && a.status !== 'inactive');

  const save = async (acc, code) => {
    if (!code) return;
    setBusy(acc.id);
    try {
      const r = await fetch(`${BASE}/accounts/${acc.id}/payout-bank`, {
        method: 'PUT', headers: { ...auth(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ coa_cash_code: code }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Gagal (HTTP ${r.status})`);
      toast.success(d.message);
      onChanged?.();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  return (
    <GlassCard className="p-4 space-y-3" data-testid="payout-bank-links">
      <div>
        <h3 className="font-medium text-sm flex items-center gap-2">
          <Landmark className="w-4 h-4" /> Tautan Rekening Bank per Toko
          <span className="text-xs text-foreground/50 font-normal">— {banks.length} rekening terbaca dari Kas & Bank / COA</span>
        </h3>
        <p className="text-xs text-foreground/60 mt-0.5">
          Rekening default tujuan penarikan saldo platform. Bisa diganti per penarikan di form di bawah.
        </p>
      </div>
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-2">
        {active.map((a) => (
          <div key={a.id} className="rounded-lg bg-foreground/5 p-3 text-xs space-y-1.5" data-testid={`payout-bank-${a.account_code}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium truncate" title={a.account_name}>{a.account_name}</span>
              <span className="uppercase text-[10px] text-foreground/50 flex items-center gap-1">
                {busy === a.id ? <Loader2 className="w-3 h-3 animate-spin" />
                  : a.coa_cash_code ? <CheckCircle2 className="w-3 h-3 text-emerald-600" /> : null}
                {a.platform}
              </span>
            </div>
            <BankSelect banks={banks} value={a.coa_cash_code} onChange={(v) => save(a, v)}
              testId={`payout-bank-select-${a.account_code}`} emptyLabel="— belum ditautkan —" className="h-8 text-xs" />
          </div>
        ))}
      </div>
    </GlassCard>
  );
}
