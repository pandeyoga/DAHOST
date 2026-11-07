/**
 * RollLinesEditor — pengisi RINCIAN GULUNGAN saat kain masuk (FASE H-5).
 *
 * Aturan yang ditegakkan di layar (sama dengan backend, supaya penolakan tidak
 * datang sebagai kejutan setelah tombol simpan ditekan):
 *   · nomor roll TIDAK diketik — diterbitkan otomatis (RL-YYYYMM-####)
 *   · total berat/panjang seluruh gulungan HARUS sama dengan qty yang diterima,
 *     karena angka yang dipakai orang saat mencari kain adalah gulungannya,
 *     sementara laporan memakai stoknya. Dua angka berbeda = gudang berdebat
 *     dengan dirinya sendiri.
 *   · maksimum 200 gulungan per baris penerimaan
 *
 * Standar UI/UX v2 (8 Nov 2026): kotak netral (dulu latar ungu pekat 70%), tabel & isian komponen bersama,
 * semua tombol `type="button"` karena editor ini dipakai di dalam FormPopup (tidak boleh mengirim form).
 */
import { Trash2, Plus, CheckCircle2, AlertTriangle, Wand2 } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  rollLine, rollLinesState, splitEvenly, fmtQty, rollUomOf, num,
} from './rollLines';

export default function RollLinesEditor({
  lines = [],
  accepted = 0,
  unit = '',
  onChange,
  testPrefix = 'roll-lines',
  nextNumberHint = '',
  disabled = false,
  title = 'Rincian gulungan',
  subtitle = '',
}) {
  const [bulk, setBulk] = useState('');
  const uom = rollUomOf(unit) || unit || '';
  const st = rollLinesState(lines, accepted);

  const set = (next) => !disabled && onChange?.(next);
  const update = (i, field, val) => set(lines.map((l, idx) => (idx === i ? { ...l, [field]: val } : l)));
  const add = () => set([...lines, rollLine('')]);
  const remove = (i) => set(lines.filter((_, idx) => idx !== i));
  const doSplit = () => {
    const n = Math.max(1, Math.floor(num(bulk) || 1));
    set(splitEvenly(accepted, n));
  };

  const badge = {
    empty: {
      cls: 'text-[hsl(var(--warning-text))]',
      icon: AlertTriangle,
      text: 'Belum ada gulungan — kain ini akan masuk daftar "Penerimaan tanpa roll"',
    },
    match: {
      cls: 'text-[hsl(var(--success-text))]',
      icon: CheckCircle2,
      text: `Cocok — ${st.count} gulungan = ${fmtQty(st.total)} ${uom}`,
    },
    over: {
      cls: 'text-[hsl(var(--danger-text))]',
      icon: AlertTriangle,
      text: `Kelebihan ${fmtQty(Math.abs(st.diff), 3)} ${uom} — total gulungan ${fmtQty(st.total)} vs diterima ${fmtQty(accepted)}`,
    },
    under: {
      cls: 'text-[hsl(var(--danger-text))]',
      icon: AlertTriangle,
      text: st.hasZero
        ? 'Ada gulungan yang berat/panjangnya masih 0 — isi angkanya'
        : `Kurang ${fmtQty(Math.abs(st.diff), 3)} ${uom} — total gulungan ${fmtQty(st.total)} vs diterima ${fmtQty(accepted)}`,
    },
  }[st.state];
  const BadgeIcon = badge.icon;

  return (
    // Enter di isian gulungan tidak mengirim form popup di sekelilingnya (mengetik berat lalu Enter ≠ Simpan).
    <div className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3" data-testid={`${testPrefix}-panel`}
      onKeyDown={(e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault(); }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">
            {title} <span className="font-normal text-muted-foreground">· nomor roll otomatis{nextNumberHint ? ` (berikutnya ${nextNumberHint})` : ''}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {subtitle || `Isi berat/panjang tiap gulungan. Totalnya harus sama dengan qty diterima (${fmtQty(accepted)} ${uom}).`}
          </p>
        </div>
        {!disabled && (
          <div className="flex items-center gap-2">
            <Input type="number" min="1" max="200" value={bulk} onChange={(e) => setBulk(e.target.value)}
              placeholder="Jumlah roll" aria-label="Jumlah gulungan untuk dibagi rata" className="h-8 w-28"
              data-testid={`${testPrefix}-bulk-count`} />
            <Button type="button" size="sm" variant="outline" onClick={doSplit} data-testid={`${testPrefix}-split`}>
              <Wand2 />Bagi rata
            </Button>
          </div>
        )}
      </div>

      {lines.length > 0 && (
        <div className="overflow-x-auto">
          <Table data-testid={`${testPrefix}-table`} className="min-w-[34rem]">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Nomor roll</TableHead>
                <TableHead className="w-32">{uom === 'kg' ? 'Berat (kg)' : `Panjang (${uom || 'm'})`}</TableHead>
                <TableHead className="w-32">Lot warna</TableHead>
                <TableHead>Catatan</TableHead>
                {!disabled && <TableHead className="w-10" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((l, i) => (
                <TableRow key={i} data-testid={`${testPrefix}-row-${i}`}>
                  <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                  <TableCell className="tabular-nums text-muted-foreground">{l.roll_no || 'otomatis'}</TableCell>
                  <TableCell>
                    <Input type="number" step="0.001" min="0" value={l.qty} disabled={disabled}
                      onChange={(e) => update(i, 'qty', e.target.value)} aria-label={`Qty gulungan ${i + 1}`}
                      className={`h-8 tabular-nums ${num(l.qty) > 0 ? '' : 'border-[hsl(var(--destructive)/0.5)]'}`}
                      data-testid={`${testPrefix}-qty-${i}`} />
                  </TableCell>
                  <TableCell>
                    <Input value={l.color_lot || ''} disabled={disabled} onChange={(e) => update(i, 'color_lot', e.target.value)}
                      placeholder="LOT-A" aria-label={`Lot warna gulungan ${i + 1}`} className="h-8"
                      data-testid={`${testPrefix}-lot-${i}`} />
                  </TableCell>
                  <TableCell>
                    <Input value={l.notes || ''} disabled={disabled} onChange={(e) => update(i, 'notes', e.target.value)}
                      placeholder="mis. ujung basah" aria-label={`Catatan gulungan ${i + 1}`} className="h-8"
                      data-testid={`${testPrefix}-notes-${i}`} />
                  </TableCell>
                  {!disabled && (
                    <TableCell className="text-right">
                      <Button type="button" variant="ghost" size="icon-sm" onClick={() => remove(i)}
                        aria-label={`Hapus gulungan ${i + 1}`} title={`Hapus gulungan ${i + 1}`}
                        data-testid={`${testPrefix}-remove-${i}`}>
                        <Trash2 className="text-[hsl(var(--danger-text))]" />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        {!disabled ? (
          <Button type="button" size="sm" variant="outline" onClick={add} data-testid={`${testPrefix}-add`}>
            <Plus />Tambah gulungan
          </Button>
        ) : <span />}
        <p className={`inline-flex items-center gap-1.5 text-xs font-medium ${badge.cls}`} data-testid={`${testPrefix}-status`}>
          <BadgeIcon className="h-3.5 w-3.5 shrink-0" /> {badge.text}
        </p>
      </div>
    </div>
  );
}
