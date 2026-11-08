/**
 * Kartu angka Manajemen Aset — Standar UI/UX v2: SATU gaya kartu angka (`StatTile` bersama), paling banyak
 * 4 sebaris. Dulu kartu gradasi berwarna dengan ikon (KPICard buatan sendiri).
 *
 * `sub` = kalimat pendek di bawah angka (selalu tampil); `hint` = penjelasan cara menghitung (muncul saat
 * kursor diarahkan ke kartu).
 */
import { StatTile } from '../../moduleAtoms';

export function KPICard({ label, value, sub, hint, accent, testId }) {
  return (
    <div className="min-w-0" title={hint}>
      <StatTile label={label} value={value} sub={sub} hint={hint} accent={accent} testId={testId} />
    </div>
  );
}

/** Baris kartu angka: 2 kolom di HP, 4 di layar lebar. */
export function BarisKartu({ children, testId }) {
  return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid={testId}>{children}</div>;
}

/**
 * Bagian — satu kelompok isi (judul kecil + alat di kanan + tabel). Polos, bukan kartu: tabel di dalamnya
 * menjadi kartu ringkas di HP, jadi bagian ini tidak boleh berkartu (kartu di dalam kartu).
 */
export function Bagian({ judul, keterangan, alat, children, testId, className }) {
  return (
    <section className={className ? `min-w-0 space-y-2 ${className}` : 'min-w-0 space-y-2'} data-testid={testId}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-foreground">{judul}</h3>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {alat && <div className="flex items-center gap-2">{alat}</div>}
      </div>
      {children}
    </section>
  );
}
