/**
 * Papan kelengkapan data produk (Ringkasan RnD — Portal Manajemen & Portal RnD).
 * Standar UI/UX v2 (8 Nov 2026): satu kartu, pil penyaring per kriteria (dengan jumlah model kurang; dulu 7 kartu
 * kecil HURUF BESAR), tabel standar + unduh Excel/CSV (semua model hasil saringan), ikon centang/silang warna token,
 * tombol standar (dulu <button> polos). Fitur tetap: saring per kriteria, lompat ke layar pengisian, tampilkan semua.
 */
import { useEffect, useState, useMemo } from 'react';
import { ArrowUpRight, CheckCircle2, XCircle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';

const API = process.env.REACT_APP_BACKEND_URL || '';
// Tujuan navigasi per jenis kekurangan (hub + tab)
const TARGET = {
  bom: ['rnd-master-product-hub', 'bom'], accessories: ['rnd-master-product-hub', 'bom'], hpp: ['rnd-master-product-hub', 'bom'],
  techpack: ['rnd-design-hub', 'techpack'], photo: ['rnd-master-product-hub', 'models'], weight: ['rnd-master-product-hub', 'models'], sop: ['rnd-master-product-hub', 'models'],
};
const kalimat = (s) => { const t = String(s || '').toLowerCase(); return t.charAt(0).toUpperCase() + t.slice(1); };

export function RnDCompletenessBoard({ token, onNavigate }) {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState('all');
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/dewi/rnd/completeness`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null)).then(setData).catch(() => setData(null));
  }, [token]);

  const semuaBaris = useMemo(() => {
    if (!data) return [];
    return filter === 'all' ? data.rows.filter((x) => x.missing.length) : data.rows.filter((x) => x.missing.includes(filter));
  }, [data, filter]);
  const rows = showAll ? semuaBaris : semuaBaris.slice(0, 12);

  const go = (key, modelId) => {
    const [hub, tab] = TARGET[key] || ['rnd-master-product-hub', 'models'];
    try { sessionStorage.setItem(`hub_tab_${hub}`, tab); if (modelId) sessionStorage.setItem('bom_jump_model', modelId); } catch { /* abaikan */ }
    onNavigate && onNavigate(hub);
  };

  if (!data) return <Skeleton className="h-40 rounded-xl" />;
  const pct = data.total_models ? Math.round((100 * data.complete_models) / data.total_models) : 0;
  const opsi = [
    { key: 'all', label: 'Semua kekurangan', count: data.rows.filter((x) => x.missing.length).length },
    ...data.checks.map((c) => ({ key: c.key, label: kalimat(c.label), count: data.missing_counts[c.key] || 0 })),
  ];

  return (
    <GlassCard className="space-y-3 p-4" data-testid="rnd-completeness-board">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-base font-semibold text-foreground">Kelengkapan data produk</p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground tabular-nums" data-testid="rnd-completeness-summary">{data.complete_models}/{data.total_models}</span>{' '}
            model lengkap ({pct}%). Pilih kriteria untuk melihat model yang kurang; klik silang untuk langsung mengisinya.
            {data.discontinued_models > 0 && (
              <span className="ml-1" data-testid="rnd-completeness-discontinued">
                {data.discontinued_models} model dihentikan (semua SKU nonaktif) tidak dihitung kurang.
              </span>
            )}
          </p>
        </div>
        <TombolUnduh namaBerkas={`kelengkapan-produk-${filter}`} namaLembar="Kelengkapan produk" baris={semuaBaris}
          testId="rnd-completeness-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.code },
            { label: 'Model', nilai: (r) => r.name },
            { label: 'Kategori', nilai: (r) => r.category || '' },
            ...data.checks.map((c) => ({ label: kalimat(c.label), nilai: (r) => (r.flags[c.key] ? 'Lengkap' : 'Kurang') })),
            { label: 'Skor (%)', nilai: (r) => r.score },
          ]} />
      </div>
      <FilterChips options={opsi} value={filter} onChange={(k) => { setFilter(k); setShowAll(false); }} hideWhenEmpty={false}
        ariaLabel="Kriteria kelengkapan" testId="rnd-completeness-filter" />
      <div className="max-h-[46vh] overflow-auto">
        <Table data-testid="rnd-completeness-table">
          <TableHeader>
            <TableRow>
              <TableHead>Model</TableHead>
              <TableHead className="hidden md:table-cell">Kategori</TableHead>
              {data.checks.map((c) => <TableHead key={c.key} className="hidden whitespace-nowrap text-center lg:table-cell">{kalimat(c.label)}</TableHead>)}
              <TableHead className="text-right">Skor</TableHead>
              <TableHead><span className="sr-only">Aksi</span></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.model_id} data-testid={`rnd-completeness-row-${r.code}`}>
                <TableCell className="whitespace-nowrap">
                  <span className="mr-2 text-xs text-muted-foreground">{r.code}</span>{r.name}
                  <span className="block text-xs text-muted-foreground lg:hidden">
                    Kurang: {r.missing.map((k) => kalimat(data.checks.find((c) => c.key === k)?.label || k)).join(', ') || '—'}
                  </span>
                </TableCell>
                <TableCell className="hidden text-muted-foreground md:table-cell">{r.category}</TableCell>
                {data.checks.map((c) => (
                  <TableCell key={c.key} className="hidden text-center lg:table-cell">
                    {r.flags[c.key] ? (
                      <CheckCircle2 className="inline h-4 w-4 text-[hsl(var(--success-text))]" aria-label="Lengkap" />
                    ) : (
                      <Button variant="ghost" size="icon-sm" onClick={() => go(c.key, r.model_id)} title={`Isi ${c.label} untuk ${r.code}`}
                        aria-label={`Isi ${c.label} untuk ${r.code}`} data-testid={`rnd-completeness-fix-${r.code}-${c.key}`}>
                        <XCircle className="text-[hsl(var(--danger-text))]" />
                      </Button>
                    )}
                    {c.key === 'bom' && r.variants_without_bom > 0 && (
                      <span className="block text-xs text-[hsl(var(--warning-text))]">{r.variants_without_bom}/{r.variants} varian</span>
                    )}
                  </TableCell>
                ))}
                <TableCell className="text-right tabular-nums">{r.score}%</TableCell>
                <TableCell className="text-right">
                  <Button variant="link" size="sm" onClick={() => go(r.missing[0] || 'bom', r.model_id)} data-testid={`rnd-completeness-go-${r.code}`}>
                    Isi<ArrowUpRight />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow><TableCell colSpan={data.checks.length + 4} className="py-6 text-center text-sm text-muted-foreground">
                Tidak ada model yang kurang pada kriteria ini.
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {!showAll && semuaBaris.length > 12 && (
        <Button variant="link" size="sm" className="px-0" onClick={() => setShowAll(true)} data-testid="rnd-completeness-more">
          Tampilkan semua {semuaBaris.length} model
        </Button>
      )}
    </GlassCard>
  );
}
