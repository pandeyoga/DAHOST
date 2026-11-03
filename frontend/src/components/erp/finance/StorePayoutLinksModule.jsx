/**
 * Pengaturan Keuangan › Rekening toko — rekening bank tujuan penarikan saldo tiap toko marketplace.
 *
 * 2026-11-04 (owner, audit Keuangan): pengaturan ini dulu ada di tengah halaman Pencairan (±900 px di
 * antara pekerjaan harian). Isinya tidak berubah (komponen PayoutBankLinks yang sama); hanya pindah
 * ke Pengaturan karena jarang disentuh.
 */
import { useCallback, useEffect, useState } from 'react';
import { PayoutBankLinks, useBankOptions } from './PayoutBankLinks';

const API = process.env.REACT_APP_BACKEND_URL;

export default function StorePayoutLinksModule() {
  const [accounts, setAccounts] = useState([]);
  const banks = useBankOptions();
  const loadAccounts = useCallback(() => {
    fetch(`${API}/api/marketing/accounts?limit=200`,
      { headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` } })
      .then((r) => r.json())
      .then((d) => setAccounts(Array.isArray(d) ? d : (d?.accounts || d?.data || [])))
      .catch(() => setAccounts([]));
  }, []);
  useEffect(() => { loadAccounts(); }, [loadAccounts]);
  return <PayoutBankLinks accounts={accounts} banks={banks} onChanged={loadAccounts} />;
}
