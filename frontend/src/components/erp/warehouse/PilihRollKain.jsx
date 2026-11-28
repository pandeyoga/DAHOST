/**
 * PilihRollKain — pemilih ROLL kain untuk penyesuaian (kurang) dan pindah lokasi (28 Nov 2026, owner: "Ya, perbaiki").
 *
 * Stok kain = isi gulungannya. Mengurangi stok kain (rusak/hilang/koreksi) harus menyebut roll mana dan berapa
 * per roll; memindah kain = memindah roll utuh. Data dari GET /api/rahaza/material-stock/{id}/rolls (server menolak
 * bila jumlahnya tidak cocok — layar ini menghitungnya lebih dulu supaya penolakan tidak datang sebagai kejutan).
 */
import { useEffect, useState } from 'react';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { EmptyState } from '../moduleAtoms';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 3 });
export const angka = (v) => {
  const n = Number(String(v ?? '').replace(',', '.'));
  return Number.isFinite(n) ? n : 0;
};

/** Roll terbuka satu kain di satu lokasi. `info.per_roll=false` = barang ini tidak dilacak per roll. */
export function useRollKain(token, materialId, locationId) {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    let batal = false;
    setInfo(null);
    if (!materialId) return undefined;
    (async () => {
      try {
        const qs = locationId ? `?location_id=${encodeURIComponent(locationId)}` : '';
        const r = await fetch(`/api/rahaza/material-stock/${materialId}/rolls${qs}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const d = r.ok ? await r.json() : null;
        if (!batal) setInfo(d);
      } catch {
        if (!batal) setInfo(null);
      }
    })();
    return () => { batal = true; };
  }, [token, materialId, locationId]);
  return info;
}

/** Total yang dipilih: mode kurang = Σ jumlah per roll; mode pindah = Σ sisa roll yang dicentang. */
export function totalPilihan(info, mode, nilai) {
  const rolls = info?.rolls || [];
  if (mode === 'pindah') return rolls.filter((r) => nilai?.[r.id]).reduce((s, r) => s + Number(r.remaining || 0), 0);
  return rolls.reduce((s, r) => s + angka(nilai?.[r.id]), 0);
}

/** Isi body request: kurang → roll_reductions [{roll_id, qty}], pindah → roll_ids. */
export function bodyPilihan(info, mode, nilai) {
  const rolls = info?.rolls || [];
  if (mode === 'pindah') return { roll_ids: rolls.filter((r) => nilai?.[r.id]).map((r) => r.id) };
  return { roll_reductions: rolls.filter((r) => angka(nilai?.[r.id]) > 0).map((r) => ({ roll_id: r.id, qty: angka(nilai[r.id]) })) };
}

export default function PilihRollKain({ info, mode = 'kurang', nilai = {}, onUbah, testId = 'pilih-roll' }) {
  const rolls = info?.rolls || [];
  const unit = info?.unit || '';
  const ubah = (id, v) => onUbah?.({ ...nilai, [id]: v });
  const total = totalPilihan(info, mode, nilai);
  return (
    <div className="space-y-2" data-testid={testId}>
      <p className="text-sm text-muted-foreground">
        {mode === 'pindah'
          ? 'Kain dipindah per roll utuh. Centang roll yang dipindah; jumlahnya mengikuti sisa roll.'
          : 'Kain dilacak per roll. Isi jumlah yang dikurangi pada roll yang rusak atau hilang.'}
      </p>
      <div className="max-h-64 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--glass-border)]">
        <Table className="min-w-0">
          <TableHeader>
            <TableRow>
              {mode === 'pindah' && <TableHead className="w-10"><span className="sr-only">Pilih</span></TableHead>}
              <TableHead>No. roll</TableHead>
              <TableHead className="hidden sm:table-cell">Lot / posisi</TableHead>
              <TableHead className="text-right">Sisa</TableHead>
              {mode !== 'pindah' && <TableHead className="w-32 text-right">Dikurangi</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rolls.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4}>
                  <EmptyState title="Tidak ada roll di lokasi ini"
                    description="Stok kain ini belum punya roll di lokasi terpilih. Periksa di Gudang › Roll Kain." />
                </TableCell>
              </TableRow>
            ) : rolls.map((r) => (
              <TableRow key={r.id} data-testid={`${testId}-${r.roll_no}`}>
                {mode === 'pindah' && (
                  <TableCell>
                    <Checkbox checked={!!nilai[r.id]} onCheckedChange={(c) => ubah(r.id, c === true)}
                      aria-label={`Pilih roll ${r.roll_no}`} />
                  </TableCell>
                )}
                <TableCell className="whitespace-nowrap font-medium">{r.roll_no}</TableCell>
                <TableCell className="hidden text-sm text-muted-foreground sm:table-cell">
                  {[r.color_lot, r.position_barcode].filter(Boolean).join(' · ') || '—'}
                </TableCell>
                <TableCell className="whitespace-nowrap text-right tabular-nums">{fmt(r.remaining)} {unit}</TableCell>
                {mode !== 'pindah' && (
                  <TableCell className="text-right">
                    <Input type="number" inputMode="decimal" min={0} step="0.01" value={nilai[r.id] ?? ''}
                      onChange={(e) => ubah(r.id, e.target.value)} className="h-8 text-right"
                      aria-label={`Dikurangi dari roll ${r.roll_no}`} />
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-sm text-muted-foreground" data-testid={`${testId}-total`}>
        {mode === 'pindah' ? 'Total dipindah' : 'Total dikurangi'}: <span className="font-medium text-foreground tabular-nums">{fmt(total)} {unit}</span>
      </p>
    </div>
  );
}
