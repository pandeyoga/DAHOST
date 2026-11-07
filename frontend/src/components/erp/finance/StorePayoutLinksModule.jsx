/**
 * Pengaturan Keuangan › Rekening toko — rekening bank tujuan penarikan saldo tiap toko marketplace.
 *
 * 2026-11-04 (owner, audit Keuangan): pengaturan ini dulu ada di tengah halaman Pencairan (±900 px di
 * antara pekerjaan harian). Isinya tidak berubah (komponen PayoutBankLinks yang sama); hanya pindah
 * ke Pengaturan karena jarang disentuh.
 * 2026-11-05 (PANDUAN_UI G1): memakai cetakan PageLayout — penjelasan di ringkasan, daftar toko di tabel.
 * 2026-11-08 (Standar UI/UX v2): daftar rekening toko bisa diunduh Excel/CSV.
 */
import { useCallback, useEffect, useState } from 'react';
import PageLayout from '../layout/PageLayout';
import { PayoutBankLinks, useBankOptions, cashIsConfirmed, bankLabel } from './PayoutBankLinks';
import TombolUnduh from '@/components/ui/tombol-unduh';

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
      tools={
        <TombolUnduh namaBerkas="rekening-toko" namaLembar="Rekening toko" testId="payout-bank-unduh"
          baris={accounts.filter((a) => a.status !== 'archived' && a.status !== 'inactive')}
          kolom={[
            { label: 'Toko', nilai: (a) => a.account_name },
            { label: 'Platform', nilai: (a) => (a.platform ? a.platform.charAt(0).toUpperCase() + a.platform.slice(1) : '') },
            { label: 'Rekening tujuan', nilai: (a) => { const b = banks.find((x) => x.code === a.coa_cash_code); return b ? bankLabel(b) : (a.coa_cash_code || ''); } },
            { label: 'Keterangan', nilai: (a) => (!a.coa_cash_code ? 'Belum ditautkan' : cashIsConfirmed(a) ? 'Sudah diatur' : 'Rekening bawaan — belum diatur') },
          ]} />
      }
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
