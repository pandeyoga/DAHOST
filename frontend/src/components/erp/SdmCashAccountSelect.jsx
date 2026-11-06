/**
 * SdmCashAccountSelect — pemilih rekening kas/bank + tanggal WIB untuk form pembayaran SDM↔Keuangan
 * (gaji, kasbon, uang muka dinas, klaim biaya).
 *
 * 2026-11-02 (paket P5): menggantikan daftar rekening hard-code (berisi 1-1200 = akun header dan
 * 1-1203 = tidak ada di bagan akun) dengan rekening kas/bank AKTIF yang nyata dari backend
 * (`GET /api/rahaza/payment-cash-accounts`, terbuka untuk portal SDM & Keuangan). Tanggal bawaan
 * dihitung di zona WIB (keputusan owner No.54(a)), bukan `toISOString()` (UTC) — helper-nya di `lib/waktu.js`.
 *
 * 2026-11-07 (audit form Tahap 5): pilihan memakai SmartNativeSelect (bisa dicari — 20 rekening) dan
 * berlabel "nama · kode akun"; dulu <select> polos bawaan browser (PANDUAN_UI G6). API & testid tetap:
 * `testId` = akar, `${testId}-trigger` = tombol, `${testId}-option-<nilai>` = opsi.
 */
import { useEffect, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';

const API = process.env.REACT_APP_BACKEND_URL || '';

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

/** Label rekening: "Bank BCA · 1-1201" (kode akun buku besar di belakang supaya nama bisa dicari dulu). */
export const cashAccountLabel = (a) => (a.gl_account_code ? `${a.name} · ${a.gl_account_code}` : a.name);

/**
 * Pilihan rekening. `valueKey` = 'id' (kirim cash_account_id/bank_account_id) atau
 * 'gl_account_code' (kirim bank_account_code, mis. bayar gaji).
 */
export default function CashAccountSelect({
  accounts, loaded = true, value, onChange, valueKey = 'id', className = '', testId, disabled = false,
}) {
  return (
    <SmartNativeSelect
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testId}
      aria-label="Rekening kas/bank"
      disabled={disabled}
      searchPlaceholder="Cari nama rekening atau kode akun…"
      className={className || 'w-full h-9'}
    >
      <option value="" disabled>
        {!loaded ? 'Memuat rekening…' : (accounts.length ? '— Pilih rekening kas/bank —' : 'Tidak ada rekening kas/bank aktif')}
      </option>
      {accounts.map((a) => (
        <option key={a.id || a.gl_account_code} value={a[valueKey]}>{cashAccountLabel(a)}</option>
      ))}
    </SmartNativeSelect>
  );
}
