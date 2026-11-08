/**
 * ImportValueMapPanel — "Arti nilai di berkas" di langkah pemetaan Impor Data (2026-11-06, Tahap 2).
 *
 * Dulu kolom pilihan (status, kurir, kanal) hanya bisa dipetakan KOLOMNYA. Nilai yang belum ada
 * di kamus sistem — mis. status Shopee "Telah Dikirim" — menolak seluruh pesanannya, dan satu-satunya
 * jalan keluar adalah meminta programmer menambah kamus. Panel ini menampilkan setiap nilai berbeda
 * di berkas beserta artinya menurut sistem; staf memilih arti nilai yang belum dikenal. Pilihan itu
 * disimpan di entri pemetaan kolomnya (`value_map`), jadi ikut dipakai pratinjau, commit, dan
 * ingatan pemetaan berikutnya.
 *
 * Data: `value_report` dari backend (`core.marketing_import_engine.value_report`).
 */
import React from 'react';
import { ListChecks } from 'lucide-react';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { StatusBadge } from '@/components/erp/moduleAtoms';

/* Dasar arti sebuah nilai, dalam kalimat staf. */
const VALUE_HOW = {
  kamus: 'kamus sistem',
  baku: 'nilai baku',
  awalan: 'kamus (awal teksnya)',
  mirip: 'mirip nilai di kamus — periksa',
};

/* Satu kolom pilihan: nilai berbeda di berkas → arti menurut kamus → pilihan staf.
   Nilai yang belum dikenal ditaruh paling atas (diurutkan backend). */
function ValueMapTable({ vr, onChange, busy }) {
  return (
    <Table data-testid={`value-map-table-${vr.field}`}>
      <TableHeader>
        <TableRow>
          <TableHead>Nilai di berkas</TableHead>
          <TableHead className="text-right">Muncul</TableHead>
          <TableHead>Arti menurut sistem</TableHead>
          <TableHead>Pilihan Anda</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {vr.values.map((v) => {
          const known = v.auto && v.auto_how !== 'cadangan';
          return (
            <TableRow key={v.key} data-testid={`value-row-${vr.field}-${v.key}`}>
              <TableCell className="max-w-[280px]">
                <span className="break-words">{v.raw}</span>
                {v.variants > 1 && (
                  <span className="block text-xs text-muted-foreground">
                    dan {v.variants - 1} variasi lain (beda tanggal/angka)
                  </span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">{v.count}</TableCell>
              <TableCell>
                {known ? (
                  <span>
                    {v.auto_label}
                    <span className="block text-xs text-muted-foreground">
                      menurut {VALUE_HOW[v.auto_how] || 'kamus sistem'}
                    </span>
                  </span>
                ) : v.auto ? (
                  <span className="text-[hsl(var(--warning))]">
                    Belum dikenal — dicatat sebagai {vr.fallback_label || v.auto_label}
                  </span>
                ) : (
                  <span className="text-[hsl(var(--destructive))]">
                    Belum dikenal — barisnya ditolak
                  </span>
                )}
              </TableCell>
              <TableCell>
                <Select value={v.chosen || '__auto__'} disabled={busy}
                  onValueChange={(val) => onChange(vr.field, v.key, val === '__auto__' ? '' : val)}>
                  <SelectTrigger className="h-7 w-full max-w-[220px] text-xs"
                    data-testid={`value-pick-${vr.field}-${v.key}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="max-h-72">
                    <SelectItem value="__auto__">
                      {known ? 'Ikuti arti sistem' : '— pilih artinya —'}
                    </SelectItem>
                    {vr.choices.map((c) => (
                      <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export default function ImportValueMapPanel({ report, onChange, busy }) {
  if (!report || report.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="import-value-map">
      <p className="text-xs font-semibold flex items-center gap-1.5">
        <ListChecks className="w-4 h-4" /> Arti nilai di berkas
      </p>
      <p className="text-xs text-muted-foreground">
        Untuk kolom pilihan (status, kurir, kanal) setiap nilai yang berbeda ditampilkan beserta
        artinya. Nilai yang belum dikenal membuat barisnya ditolak — pilih artinya di kolom
        “Pilihan Anda”. Pilihan ini ikut diingat untuk berkas berikutnya dengan susunan kolom yang sama.
      </p>
      {report.map((vr) => (
        <div key={vr.field} className="space-y-1" data-testid={`value-map-${vr.field}`}>
          <p className="text-xs flex flex-wrap items-center gap-1.5">
            <b>{vr.label}</b>
            <span className="text-muted-foreground">
              dari kolom “{vr.column}” · {vr.distinct} nilai berbeda
            </span>
            {vr.unknown > 0 ? (
              <StatusBadge tone="danger" testId={`value-unknown-${vr.field}`}
                label={`${vr.unknown} belum dikenal · ${vr.unknown_rows} baris`} />
            ) : (
              <StatusBadge tone="success" label="semua dikenal" />
            )}
          </p>
          {vr.unknown > 0 ? (
            <ValueMapTable vr={vr} onChange={onChange} busy={busy} />
          ) : (
            <details className="rounded-[var(--radius-sm)] border border-border">
              <summary className="px-3 py-1.5 text-xs cursor-pointer text-muted-foreground">
                Lihat atau ubah arti {vr.distinct} nilai
              </summary>
              <ValueMapTable vr={vr} onChange={onChange} busy={busy} />
            </details>
          )}
          {vr.truncated && (
            <p className="text-xs text-muted-foreground">
              Hanya {vr.values.length} nilai pertama yang ditampilkan.
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
