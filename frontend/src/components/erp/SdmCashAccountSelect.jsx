/**
 * SdmCashAccountSelect — pemilih rekening kas/bank + tanggal WIB untuk form pembayaran SDM↔Keuangan
 * (gaji, kasbon, uang muka dinas, klaim biaya).
 *
 * 2026-11-02 (paket P5): menggantikan daftar rekening hard-code (berisi 1-1200 = akun header dan
 * 1-1203 = tidak ada di bagan akun) dengan rekening kas/bank AKTIF yang nyata dari backend
 * (`GET /api/rahaza/payment-cash-accounts`, terbuka untuk portal SDM & Keuangan). Tanggal bawaan
 * dihitung di zona WIB (keputusan owner No.54(a)), bukan `toISOString()` (UTC).
 */
import { useEffect, useState } from 'react';

const API = process.env.REACT_APP_BACKEND_URL || '';

/** Bagian tanggal (y, m, d) hari ini menurut WIB — tidak bergantung zona waktu browser. */
export function wibDateParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Jakarta', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const get = (t) => Number(parts.find((p) => p.type === t)?.value);
  return { y: get('year'), m: get('month'), d: get('day') };
}

const pad = (n) => String(n).padStart(2, '0');

/** 'YYYY-MM-DD' hari ini (WIB). */
export function todayWIB(now = new Date()) {
  const { y, m, d } = wibDateParts(now);
  return `${y}-${pad(m)}-${pad(d)}`;
}

/** 'YYYY-MM' bulan ini (WIB). */
export function thisMonthWIB(now = new Date()) {
  return todayWIB(now).slice(0, 7);
}

/** Rekening kas/bank aktif. `accounts` = [] selama memuat / bila gagal (form menahan tombol bayar). */
export function usePaymentCashAccounts(token) {
  const [accounts, setAccounts] = useState([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let off = false;
    const tok = token || localStorage.getItem('erp_token');
    fetch(`${API}/api/rahaza/payment-cash-accounts`, { headers: { Authorization: `Bearer ${tok}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => { if (!off) setAccounts(Array.isArray(d) ? d : []); })
      .catch(() => { if (!off) setAccounts([]); })
      .finally(() => { if (!off) setLoaded(true); });
    return () => { off = true; };
  }, [token]);
  return { accounts, loaded };
}

/**
 * <select> rekening. `valueKey` = 'id' (kirim cash_account_id/bank_account_id) atau
 * 'gl_account_code' (kirim bank_account_code, mis. bayar gaji).
 */
export default function CashAccountSelect({
  accounts, loaded = true, value, onChange, valueKey = 'id', className = '', testId,
}) {
  return (
    <select
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testId}
      className={className || 'w-full h-9 px-3 rounded-xl border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm'}
    >
      <option value="" disabled>
        {!loaded ? 'Memuat rekening…' : (accounts.length ? '— Pilih rekening kas/bank —' : 'Tidak ada rekening kas/bank aktif')}
      </option>
      {accounts.map((a) => (
        <option key={a.id || a.gl_account_code} value={a[valueKey]}>
          {a.name} ({a.gl_account_code})
        </option>
      ))}
    </select>
  );
}
