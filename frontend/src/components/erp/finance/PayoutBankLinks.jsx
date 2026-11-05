/**
 * PayoutBankLinks — Finance menautkan rekening pencairan default tiap toko.
 * Daftar rekening = master Kas & Bank + COA kas/bank/e-wallet aktif (semua bank, bukan cuma yang ber-flag).
 *
 * 2026-11-05 (PANDUAN_UI G5/G6): daftar toko = tabel (dulu grid kartu per toko); pilihan rekening memakai
 * SmartNativeSelect (bisa dicari) — dulu <select> bawaan browser. Kepala & penjelasan ada di cetakan
 * PageLayout milik layar (StorePayoutLinksModule).
 */
import { useEffect, useState } from 'react';
import { Store, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { EmptyState } from '../moduleAtoms';
import { cn } from '@/lib/utils';
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
    <SmartNativeSelect data-testid={testId} value={value || ''} onChange={(e) => onChange(e.target.value)}
      className={cn('h-9 w-full', className)} aria-label="Rekening bank">
      <option value="">{emptyLabel}</option>
      {banks.map((b) => <option key={b.code} value={b.code}>{bankLabel(b)}</option>)}
    </SmartNativeSelect>
  );
}

// 2026-11-02 (K4) — rekening yang dipilih Finance (layar ini / impor Excel master) vs bawaan
// sistem. Bawaan (`coa_cash_source=default`, atau data lama tanpa sumber) ditandai
// "belum diatur" supaya tidak terbaca seolah sudah dipilih (dulu centang hijau untuk keduanya).
export const cashIsConfirmed = (a) => ['finance', 'excel_master'].includes(a?.coa_cash_source);

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
    <GlassCard className="p-0 overflow-hidden" data-testid="payout-bank-links">
      {active.length === 0 ? (
        <EmptyState icon={Store} title="Belum ada toko aktif"
          description="Toko marketplace yang aktif akan muncul di sini untuk ditautkan ke rekening bank." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Toko</TableHead>
              <TableHead>Platform</TableHead>
              <TableHead>Rekening tujuan penarikan</TableHead>
              <TableHead>Keterangan</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {active.map((a) => (
              <TableRow key={a.id} data-testid={`payout-bank-${a.account_code}`}>
                <TableCell className="font-medium">{a.account_name}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground capitalize">{a.platform}</TableCell>
                <TableCell>
                  <BankSelect banks={banks} value={a.coa_cash_code} onChange={(v) => save(a, v)}
                    testId={`payout-bank-select-${a.account_code}`} emptyLabel="— belum ditautkan —" className="w-80 max-w-full" />
                </TableCell>
                <TableCell className="text-xs">
                  {busy === a.id ? (
                    <span className="inline-flex items-center gap-1 text-muted-foreground"><Loader2 className="w-3.5 h-3.5 animate-spin" /> menyimpan…</span>
                  ) : !a.coa_cash_code ? (
                    <span className="text-muted-foreground">Belum ditautkan</span>
                  ) : cashIsConfirmed(a) ? (
                    <span className="inline-flex items-center gap-1 text-[hsl(var(--success))]"><CheckCircle2 className="w-3.5 h-3.5" /> Sudah diatur</span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[hsl(var(--warning))]" data-testid={`payout-bank-default-${a.account_code}`}>
                      <AlertTriangle className="w-3.5 h-3.5" /> Rekening bawaan {a.coa_cash_code} — belum diatur
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </GlassCard>
  );
}
