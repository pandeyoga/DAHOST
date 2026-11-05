/**
 * Pemetaan Akun Otomatis — satu pintu untuk tiga pengaturan "akun mana yang dipakai jurnal otomatis".
 *
 * 2026-11-04 (owner, audit Keuangan): dulu tiga tab terpisah di Master Akuntansi (Profil Posting,
 * Auto Akun Subledger, Pemetaan GL klaim) yang mirip dan membingungkan. Isinya tidak diubah — hanya
 * disatukan di bawah satu pilihan.
 * 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout. Pilihan jenis pemetaan di toolbar kiri; tiap tampilan juga
 * memakai PageLayout tetapi dirender sebagai BAGIAN layar ini (CompactHubContext) — judulnya tidak diulang dan
 * tombolnya ikut baris tab hub.
 */
import { Suspense, useState } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import { Skeleton } from '@/components/ui/skeleton';
import { lazyRetry } from '../../../lib/lazyRetry';
import PageLayout from '../layout/PageLayout';
import { CompactHubContext } from '../moduleAtoms';

const RahazaPostingProfilesModule    = lazyRetry(() => import('../RahazaPostingProfilesModule'));
const RahazaCoaAutoModule            = lazyRetry(() => import('../RahazaCoaAutoModule'));
const EmployeeExpenseGLMappingModule = lazyRetry(() => import('../EmployeeExpenseGLMappingModule'));

const VIEWS = [
  { key: 'posting', label: 'Jurnal otomatis per transaksi', hint: 'Akun debit/kredit untuk faktur, pembayaran, gaji, persediaan, dll.', Component: RahazaPostingProfilesModule },
  { key: 'subledger', label: 'Akun per pemasok/pelanggan/toko', hint: 'Akun turunan otomatis di bawah akun kontrol (hutang, piutang, saldo toko).', Component: RahazaCoaAutoModule },
  { key: 'claims', label: 'Akun klaim biaya karyawan', hint: 'Kategori klaim karyawan → akun beban.', Component: EmployeeExpenseGLMappingModule },
];

export default function AccountMappingModule(props) {
  // petunjuk tampilan dari tautan "Isi di …" (Bagan Akun / laci pemakaian akun)
  const [view, setView] = useState(() => {
    try {
      const v = sessionStorage.getItem('account_mapping_view');
      if (v) sessionStorage.removeItem('account_mapping_view');
      return VIEWS.some((x) => x.key === v) ? v : 'posting';
    } catch { return 'posting'; }
  });
  const cur = VIEWS.find((v) => v.key === view) || VIEWS[0];
  return (
    <PageLayout
      testId="account-mapping"
      title="Pemetaan akun otomatis"
      subtitle="Akun yang dipakai jurnal otomatis: per transaksi, per pihak, dan per kategori klaim."
      filters={
        <FilterChips value={view} onChange={setView} testId="account-mapping" ariaLabel="Jenis pemetaan akun" hideWhenEmpty={false}
          options={VIEWS.map((v) => ({ key: v.key, label: v.label }))} />
      }
      summary={<p className="text-xs text-muted-foreground">{cur.hint}</p>}
    >
      <Suspense fallback={<Skeleton className="h-40" />}>
        {/* tampilan terpilih = bagian layar ini: judulnya tidak diulang, aksinya ikut baris tab hub */}
        <CompactHubContext.Provider value>
          <cur.Component key={cur.key} {...props} />
        </CompactHubContext.Provider>
      </Suspense>
    </PageLayout>
  );
}
