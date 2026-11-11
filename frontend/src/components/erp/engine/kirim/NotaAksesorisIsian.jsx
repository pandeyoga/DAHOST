/**
 * Isian NOTA AKSESORIS ke CMT — satu komponen untuk form Kirim ke CMT (Portal Produksi = Portal Maklon) dan tombol
 * "Buat nota aksesoris" di rincian kiriman. Permintaan owner 10–11 Nov 2026: aksesoris yang diserahkan DIBELI CMT.
 *
 * Keputusan owner 11 Nov: semua aksesoris ke CMT luar masuk nota; harga jual per satuan serah DIKETIK setiap kiriman
 * (tidak terisi otomatis, bisa beda per CMT dan per waktu); isi 0 bila gratis; HPP aksesoris tampil sebagai acuan.
 * Cara bayar: potong tagihan jahit CMT (bawaan) atau dibayar langsung. Server: backend/core/nota_aksesoris_cmt.py.
 */
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Isian } from '@/components/ui/form-popup';
import { SectionLabel, fmtNum, fmtRp } from './kirimShared';

export const CARA_BAYAR = {
  potong_tagihan: 'Potong tagihan jahit',
  langsung: 'Dibayar langsung',
};
const CARA_KETERANGAN = {
  potong_tagihan: 'Memotong tagihan jahit CMT ini yang masih terbuka (PO ini dulu). Bila belum ada, otomatis memotong tagihan berikutnya.',
  langsung: 'CMT membayar tunai/transfer; Keuangan mencatatnya di Piutang › Bayar.',
};

const kosong = (v) => v === undefined || v === null || String(v).trim() === '';

/** Baris nota dari hitungan form (`calc.aksesoris`) + isian jumlah/satuan serah yang sedang diketik. */
export function barisDariHitungan(aksesoris, accVals = {}) {
  return (aksesoris || []).map((a) => {
    const v = accVals[a.key] || {};
    const qty = Number(v.qty ?? a.qty_handover) || 0;
    const uom = v.uom || a.handover_uom;
    const opt = (a.options || []).find((o) => o.uom === uom);
    const factor = Number(opt ? opt.factor : a.handover_factor) || 1;
    return { key: a.key, material_id: a.material_id, code: a.code, name: a.name, qty_handover: qty,
      handover_label: opt ? opt.label : a.handover_label, hpp_satuan: Number(a.unit_cost || 0) * factor };
  }).filter((r) => r.qty_handover > 0);
}

export const jumlahBaris = (r, harga) => Math.round((Number(r.qty_handover) || 0) * (Number(harga[r.key]) || 0));
export const totalNota = (rows, harga) => rows.reduce((t, r) => t + jumlahBaris(r, harga), 0);

/** Nama aksesoris yang harganya belum diisi ('' = semua terisi; 0 sah = gratis). */
export function notaGalat(rows, harga) {
  const belum = rows.filter((r) => kosong(harga[r.key])).map((r) => r.name || r.code);
  return belum.length ? `Isi harga jual aksesoris (isi 0 bila gratis): ${belum.slice(0, 4).join(', ')}${belum.length > 4 ? ` dan ${belum.length - 4} lainnya` : ''}.` : '';
}

/** Body `nota_aksesoris` untuk server. */
export function notaPayload(rows, harga, caraBayar) {
  return { cara_bayar: caraBayar, harga: rows.map((r) => ({ key: r.key, material_id: r.material_id, nama: r.name,
    harga: kosong(harga[r.key]) ? '' : Number(harga[r.key]) })) };
}

export default function NotaAksesorisIsian({ rows, harga, onHarga, caraBayar, onCaraBayar, vendorName, dariPo = {}, testId = 'nota-aksesoris' }) {
  const total = totalNota(rows, harga);
  return (
    <div className="space-y-2" data-testid={testId}>
      <SectionLabel aside={<span className="text-xs text-muted-foreground">dibeli CMT · harga dari PO bila sudah diisi (bisa diubah), isi 0 bila gratis</span>}>
        Nota aksesoris{vendorName ? ` ke ${vendorName}` : ' ke CMT'}
      </SectionLabel>
      <div className="overflow-x-auto">
        <Table data-testid={`${testId}-tabel`}>
          <TableHeader><TableRow>
            <TableHead>Aksesoris</TableHead>
            <TableHead className="text-right">Diserahkan</TableHead>
            <TableHead className="text-right">HPP per satuan (acuan)</TableHead>
            <TableHead className="text-right">Harga jual per satuan</TableHead>
            <TableHead className="text-right">Jumlah</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows.map((r) => {
              const belum = kosong(harga[r.key]);
              return (
                <TableRow key={r.key} data-testid={`${testId}-row-${r.code || r.key}`}>
                  <TableCell>
                    <span className="block">{r.name}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">{r.code}</span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {fmtNum(r.qty_handover, 4)} <span className="text-xs text-muted-foreground">{r.handover_label}</span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap text-muted-foreground"
                    title="Nilai stok rata-rata per satuan serah — acuan menentukan harga jual">
                    {fmtRp(r.hpp_satuan)}
                  </TableCell>
                  <TableCell className="text-right">
                    <MoneyInput value={harga[r.key] ?? ''} onChange={(e) => onHarga(r.key, e.target.value)}
                      className={`h-8 w-32 ml-auto text-right ${belum ? 'border-[hsl(var(--warning))]' : ''}`}
                      aria-label={`Harga jual ${r.name}`} placeholder="Ketik harga" data-testid={`${testId}-harga-${r.code || r.key}`} />
                    {dariPo[r.key] && <span className="block text-xs text-muted-foreground">dari PO</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {belum ? <span className="text-muted-foreground">—</span> : fmtRp(jumlahBaris(r, harga))}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:items-end">
        <Isian label="Cara bayar" petunjuk={CARA_KETERANGAN[caraBayar]}>
          <SmartNativeSelect value={caraBayar} onChange={(e) => onCaraBayar(e.target.value)} aria-label="Cara bayar nota aksesoris"
            className="w-full" data-testid={`${testId}-cara`}>
            {Object.entries(CARA_BAYAR).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </SmartNativeSelect>
        </Isian>
        <p className="text-sm sm:text-right" data-testid={`${testId}-total`}>
          Total nota: <b className="tabular-nums">{fmtRp(total)}</b>
          {total === 0 && rows.length > 0 && rows.every((r) => !kosong(harga[r.key])) && (
            <span className="block text-xs text-muted-foreground">Total Rp 0 = semua gratis, tidak ada nota.</span>
          )}
        </p>
      </div>
    </div>
  );
}
