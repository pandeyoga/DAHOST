/**
 * Pemetaan Akun Otomatis — satu pintu untuk tiga pengaturan "akun mana yang dipakai jurnal otomatis".
 *
 * 2026-11-04 (owner, audit Keuangan): dulu tiga tab terpisah di Master Akuntansi (Profil Posting,
 * Auto Akun Subledger, Pemetaan GL klaim) yang mirip dan membingungkan. Isinya tidak diubah — hanya
 * disatukan di bawah satu pilihan.
 */
import { Suspense, useState } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';

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
    <div className="space-y-4" data-testid="account-mapping">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Jenis pemetaan akun">
        {VIEWS.map((v) => (
          <button key={v.key} type="button" role="tab" aria-selected={v.key === view} onClick={() => setView(v.key)}
            className={`px-3 py-1.5 rounded-lg border text-sm ${v.key === view
              ? 'border-[hsl(var(--primary)/0.4)] bg-[hsl(var(--primary)/0.10)] text-[hsl(var(--primary))] font-medium'
              : 'border-[var(--glass-border)] text-foreground/70 hover:bg-[var(--glass-bg-hover)]'}`}
            data-testid={`account-mapping-${v.key}`}>
            {v.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{cur.hint}</p>
      <Suspense fallback={<div className="h-40" />}>
        <cur.Component {...props} />
      </Suspense>
    </div>
  );
}
