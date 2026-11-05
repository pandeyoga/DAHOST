/**
 * Pengaturan Keuangan › Rekening toko — rekening bank tujuan penarikan saldo tiap toko marketplace.
 *
 * 2026-11-04 (owner, audit Keuangan): pengaturan ini dulu ada di tengah halaman Pencairan (±900 px di
 * antara pekerjaan harian). Isinya tidak berubah (komponen PayoutBankLinks yang sama); hanya pindah
 * ke Pengaturan karena jarang disentuh.
 * 2026-11-05 (PANDUAN_UI G1): memakai cetakan PageLayout — penjelasan di ringkasan, daftar toko di tabel.
 */
import { useCallback, useEffect, useState } from 'react';
import PageLayout from '../layout/PageLayout';
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
  return (
    <PageLayout
      testId="store-payout-links-page"
      title="Rekening toko"
      subtitle="Rekening bank tujuan penarikan saldo platform tiap toko marketplace."
      summary={
        <p className="text-sm text-muted-foreground" data-testid="payout-bank-summary">
          Penarikan yang belum dijurnal memakai rekening terbaru di sini saat dijurnal, kecuali rekening dipilih
          khusus di formulir penarikan · {banks.length} rekening dari Kas & Bank dan bagan akun.
        </p>
      }
    >
      <PayoutBankLinks accounts={accounts} banks={banks} onChanged={loadAccounts} />
    </PageLayout>
  );
}
