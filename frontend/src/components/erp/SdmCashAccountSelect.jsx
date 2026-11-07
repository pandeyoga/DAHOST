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
 * berlabel "nama · kode akun"; dulu kotak pilihan polos bawaan browser (PANDUAN_UI G6). API & testid tetap:
 * `testId` = akar, `${testId}-trigger` = tombol, `${testId}-option-<nilai>` = opsi.
 */
import { useEffect, useMemo, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { CV_ALL, CV_DA, normalizeCv, useCv } from '@/lib/entitas';

const API = process.env.REACT_APP_BACKEND_URL || '';

/**
 * Tahap 8 (dua CV): rekening kas/bank punya pemilik (`entity`; kosong = DA, data lama).
 * Rekening ditampilkan bila milik CV `entity`; 'ALL' / null = semua rekening.
 */
export function filterCashAccountsByCv(accounts, entity) {
  const cv = entity ? normalizeCv(entity, null) : null;
  if (!cv || cv === CV_ALL) return accounts || [];
  return (accounts || []).filter((a) => normalizeCv(a?.entity, CV_DA) === cv);
}

/**
 * CV yang dipakai menyaring rekening: `entity` eksplisit menang; bila tidak dikirim → CV terpilih di
 * Portal Keuangan; di luar keuangan → DA (modul HR hanya memegang staf DA).
 */
function useEffectiveCv(entity) {
  const ctx = useCv();
  if (entity) return normalizeCv(entity);
  return ctx ? ctx.cv : CV_DA;
}

/** Rekening kas/bank aktif milik CV yang berlaku. `accounts` = [] selama memuat / bila gagal (form menahan tombol bayar). */
export function usePaymentCashAccounts(token, entity) {
  const cv = useEffectiveCv(entity);
  const [all, setAccounts] = useState([]);
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
  const accounts = useMemo(() => filterCashAccountsByCv(all, cv), [all, cv]);
  return { accounts, loaded, entity: cv };
}

/** Label rekening: "Bank BCA · 1-1201" (kode akun buku besar di belakang supaya nama bisa dicari dulu). */
export const cashAccountLabel = (a) => (a.gl_account_code ? `${a.name} · ${a.gl_account_code}` : a.name);

/**
 * Pilihan rekening. `valueKey` = 'id' (kirim cash_account_id/bank_account_id) atau
 * 'gl_account_code' (kirim bank_account_code, mis. bayar gaji).
 */
export default function CashAccountSelect({
  accounts: accountsIn, loaded = true, value, onChange, valueKey = 'id', className = '', testId, disabled = false,
  entity,
}) {
  // `entity` (opsional): tampilkan hanya rekening milik CV itu (DA/SMU); kosong = sesuai daftar yang dikirim.
  const accounts = useMemo(() => (entity ? filterCashAccountsByCv(accountsIn, entity) : (accountsIn || [])),
    [accountsIn, entity]);
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
