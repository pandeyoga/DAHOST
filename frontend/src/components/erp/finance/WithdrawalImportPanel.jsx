/**
 * WithdrawalImportPanel — pratinjau impor laporan penarikan Shopee/TikTok (tahap 2).
 * Kolom yang dipakai ditampilkan & bisa diganti; baris bermasalah ditandai, bukan dibuang.
 *
 * 2026-11-05 (PANDUAN_UI G3/G6/G7): pilihan & tombol komponen aplikasi (dulu <select>/<button> buatan),
 * tanggal "04 Nov 2026", nomor & uang tidak dipatah ke dua baris, warna hanya token.
 * 2026-11-08 (Standar UI/UX v2): pratinjau impor = popup form standar (FormPopup panjang; tombol Simpan hijau di
 * kaki); kotak centang aplikasi; platform ditulis Shopee/TikTok.
 */
import { useMemo, useState } from 'react';
import { CheckCircle2, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { formatRupiah as rp, formatDateID } from '@/lib/format';
import { Checkbox } from '@/components/ui/checkbox';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { BankSelect } from './PayoutBankLinks';
import { namaPlatform } from './PlatformBalanceCards';

const API = process.env.REACT_APP_BACKEND_URL;
const ROLES = [['date', 'Tanggal'], ['amount', 'Nominal'], ['reference', 'No. penarikan'], ['status', 'Status'], ['bank', 'Rekening']];

export async function previewWithdrawalFile(file, accountId, mapping) {
  const fd = new FormData();
  fd.append('file', file);
  if (accountId) fd.append('account_id', accountId);
  if (mapping) fd.append('mapping', JSON.stringify(mapping));
  const r = await fetch(`${API}/api/marketing/withdrawals/import/preview`, {
    method: 'POST', headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` }, body: fd,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Gagal membaca berkas (HTTP ${r.status})`);
  return d;
}

export function WithdrawalImportPanel({ result, file, accounts, accountId, banks = [], onAccountChange, onResult, onClose, onCommitted }) {
  const [busy, setBusy] = useState('');
  const [cash, setCash] = useState('');
  const cashCode = cash || result?.cash_code || '';
  const [excluded, setExcluded] = useState({});
  const rows = result?.rows || [];
  const selected = useMemo(() => rows.filter((r) => r.ok && !excluded[r.row]), [rows, excluded]);
  const total = selected.reduce((t, r) => t + (r.amount || 0), 0);

  const remap = async (role, header) => {
    setBusy('map');
    try { onResult(await previewWithdrawalFile(file, accountId, { ...result.mapping, [role]: header || null })); }
    catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const changeAccount = async (id) => {
    onAccountChange(id);
    setBusy('map');
    try { onResult(await previewWithdrawalFile(file, id, result.mapping)); }
    catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const commit = async () => {
    if (!accountId) { toast.error('Pilih toko dulu.'); return; }
    if (!selected.length) { toast.error('Tidak ada baris yang bisa disimpan.'); return; }
    setBusy('commit');
    try {
      const r = await fetch(`${API}/api/marketing/withdrawals/import/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('erp_token')}` },
        body: JSON.stringify({ account_id: accountId, filename: result.filename, cash_code: cashCode,
          rows: selected.map((r) => ({ withdrawal_date: r.withdrawal_date, amount: r.amount, reference: r.reference || '' })) }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Gagal menyimpan (HTTP ${r.status})`);
      toast.success(d.message);
      onCommitted?.(d);
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  if (!result) return null;
  const problemCount = rows.length - rows.filter((r) => r.ok).length;
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="wd-import-panel"
      judul={`Pratinjau impor — ${result.filename}`}
      keterangan={`${result.row_count} baris · terdeteksi ${result.platform_guess ? namaPlatform(result.platform_guess) : 'platform tak dikenal'}. Periksa kolom & toko, lalu simpan.`}
      onSimpan={commit} menyimpan={busy === 'commit'} bisaSimpan={!!selected.length && !!accountId}
      labelSimpan={`Simpan ${selected.length} penarikan`}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <Isian label="Toko" wajib>
          <SmartNativeSelect data-testid="wd-import-account" value={accountId} onChange={(e) => changeAccount(e.target.value)}
            className="h-9 w-full">
            <option value="">— pilih toko —</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name} · {namaPlatform(a.platform)}</option>)}
          </SmartNativeSelect>
        </Isian>
        {ROLES.map(([role, label]) => (
          <Isian key={role} label={`Kolom ${label.toLowerCase()}`}>
            <SmartNativeSelect data-testid={`wd-import-map-${role}`} value={result.mapping?.[role] || ''} disabled={busy === 'map'}
              onChange={(e) => remap(role, e.target.value)} className="h-9 w-full">
              <option value="">— tidak dipakai —</option>
              {(result.headers || []).map((h) => <option key={h} value={h}>{h}</option>)}
            </SmartNativeSelect>
          </Isian>
        ))}
      </div>

      {accountId ? (
        <div className="text-sm text-muted-foreground flex flex-wrap items-center gap-2" data-testid="wd-import-balance">
          <span>Saldo platform toko: <b className="text-foreground tabular-nums">{rp(result.available_balance || 0)}</b> · masuk ke rekening</span>
          <div className="w-full sm:w-72"><BankSelect banks={banks} value={cashCode} onChange={setCash} testId="wd-import-bank" /></div>
        </div>
      ) : null}

      <div className="max-h-72 overflow-auto rounded-lg border border-[var(--glass-border)]">
        <table className="w-full text-sm" data-testid="wd-import-table">
          <thead className="sticky top-0 bg-background">
            <tr className="border-b border-[var(--glass-border)]">
              <th className="px-2 py-1.5 text-left">Simpan</th>
              <th className="px-2 py-1.5 text-left">#</th>
              <th className="px-2 py-1.5 text-left">Tanggal</th>
              <th className="px-2 py-1.5 text-left">No. penarikan</th>
              <th className="px-2 py-1.5 text-right">Nominal</th>
              <th className="px-2 py-1.5 text-left">Status</th>
              <th className="px-2 py-1.5 text-left">Keterangan</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.row} className={`border-b border-[var(--glass-border)] ${r.ok ? '' : 'opacity-60'}`} data-testid={`wd-import-row-${r.row}`}>
                <td className="px-2 py-1"><Checkbox disabled={!r.ok} checked={r.ok && !excluded[r.row]} aria-label={`Simpan baris ${r.row}`}
                  onCheckedChange={(v) => setExcluded({ ...excluded, [r.row]: !v })} data-testid={`wd-import-check-${r.row}`} /></td>
                <td className="px-2 py-1 text-muted-foreground tabular-nums">{r.row}</td>
                <td className="px-2 py-1 whitespace-nowrap">{r.withdrawal_date ? formatDateID(r.withdrawal_date) : '—'}</td>
                <td className="px-2 py-1 whitespace-nowrap">{r.reference || <span className="text-muted-foreground">otomatis</span>}</td>
                <td className="px-2 py-1 text-right tabular-nums whitespace-nowrap">{r.amount != null ? rp(r.amount) : '—'}</td>
                <td className="px-2 py-1">{r.status || '—'}</td>
                <td className="px-2 py-1">
                  {r.ok ? <span className="text-[hsl(var(--success-text))] flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> siap</span>
                    : <span className="text-[hsl(var(--warning-text))] flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> {r.reason}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm" data-testid="wd-import-summary">
        <b>{selected.length}</b> baris akan disimpan · total <b className="tabular-nums">{rp(total)}</b>
        {problemCount ? <span className="text-muted-foreground"> · {problemCount} baris ditandai bermasalah</span> : null}
      </p>
    </FormPopup>
  );
}
