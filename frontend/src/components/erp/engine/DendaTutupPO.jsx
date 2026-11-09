/**
 * DendaTutupPO — isian DENDA di popup Tutup PO (permintaan owner 9–10 Nov 2026).
 *
 * Dua denda yang berdiri sendiri, qty dan nominalnya boleh berbeda:
 *   • Denda dari klien (hanya PO maklon) — klien memotong tagihan jasa maklon (mis. karena retur).
 *     Memotong piutang PO ini; bila piutang sudah lunas, kelebihannya menjadi saldo kredit klien.
 *   • Denda ke CMT — DA memotong upah jahit vendor. Memotong tagihan (bon) CMT vendor yang masih terbuka;
 *     bila tidak ada, nota denda tetap terbuka dan otomatis memotong tagihan berikutnya.
 * Jumlah = qty × denda per pcs (qty bawaan = qty pesanan PO). Server: backend/core/denda_po.py.
 *
 * Dipakai `POClosureModule` (menu Tutup PO) dan `ProductionPOModule` (tombol Tutup PO di daftar PO).
 */
import { useEffect, useState } from 'react';
import { Receipt } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Isian } from '@/components/ui/form-popup';
import { formatRupiah } from '@/lib/format';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { apiGet } from '../../../lib/api';
import { EmptyState, StatusBadge } from '../moduleAtoms';

const BAGIAN = {
  klien: { judul: 'Denda dari klien', keterangan: 'Memotong piutang PO ini. Bila piutang sudah lunas, kelebihannya menjadi saldo kredit klien.',
    contoh: 'mis. klien retur 20 pcs jahitan lepas, denda Rp 5.000/pcs' },
  cmt: { judul: 'Denda ke CMT', keterangan: 'Memotong tagihan CMT vendor yang masih terbuka. Bila tidak ada, nota denda tetap terbuka dan memotong tagihan berikutnya.',
    contoh: 'mis. jahitan lepas ikut diretur klien' },
};

// status nota denda: lunas = seluruhnya sudah memotong tagihan/piutang; terbuka/sebagian = sisa menunggu tagihan berikutnya
const STATUS_DENDA = { lunas: ['Sudah dipotong', 'success'], sebagian: ['Sebagian dipotong', 'warning'], terbuka: ['Menunggu tagihan', 'warning'],
  kredit_klien: ['Sisa jadi kredit klien', 'warning'], batal: ['Batal', 'muted'] };

export const dendaAwal = (qtyPesanan) => ({
  klien: { aktif: false, qty: qtyPesanan || '', per_pcs: '', alasan: '' },
  cmt: { aktif: false, qty: qtyPesanan || '', per_pcs: '', alasan: '' },
});

const jumlahDari = (d) => (Number(d.qty) || 0) * (Number(d.per_pcs) || 0);

/** Body `denda` untuk /close & /close-short — hanya bagian yang dicentang. */
export function dendaPayload(state) {
  const out = {};
  Object.entries(state || {}).forEach(([pihak, d]) => {
    if (d.aktif) out[pihak] = { qty: Number(d.qty) || 0, per_pcs: Number(d.per_pcs) || 0, alasan: String(d.alasan || '').trim() };
  });
  return out;
}

/** Pesan galat isian denda ('' bila sudah benar). */
export function dendaGalat(state) {
  for (const [pihak, d] of Object.entries(state || {})) {
    if (!d.aktif) continue;
    const judul = BAGIAN[pihak].judul;
    if (!(Number(d.qty) > 0)) return `${judul}: qty harus lebih dari 0.`;
    if (!(Number(d.per_pcs) > 0)) return `${judul}: isi denda per pcs.`;
    if (String(d.alasan || '').trim().length < 3) return `${judul}: alasan wajib diisi.`;
  }
  return '';
}

export default function DendaTutupPO({ po, qtyPesanan, value, onChange }) {
  const maklon = (po?.business_type || 'internal') === 'maklon';
  const set = (pihak, k, v) => onChange({ ...value, [pihak]: { ...value[pihak], [k]: v } });
  const pihakList = maklon ? ['klien', 'cmt'] : ['cmt'];
  return (
    <div className="space-y-3" data-testid="po-close-denda">
      {pihakList.map((pihak) => {
        const d = value[pihak];
        const b = BAGIAN[pihak];
        const tanpaVendor = pihak === 'cmt' && !po?.vendor_id;
        return (
          <div key={pihak} className="space-y-2 border-t border-[var(--glass-border)] pt-3">
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium">
              <Checkbox checked={!!d.aktif} disabled={tanpaVendor} onCheckedChange={(v) => set(pihak, 'aktif', !!v)}
                data-testid={`po-close-denda-${pihak}-aktif`} />
              {b.judul}{pihak === 'klien' && po?.customer_name ? ` (${po.customer_name})` : ''}
              {pihak === 'cmt' && po?.vendor_name ? ` (${po.vendor_name})` : ''}
            </label>
            <p className="text-xs text-muted-foreground">{tanpaVendor ? 'PO ini belum punya vendor CMT.' : b.keterangan}</p>
            {d.aktif && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Isian label="Qty (pcs)" wajib htmlFor={`po-close-denda-${pihak}-qty`}
                  petunjuk={qtyPesanan ? `Bawaan: qty pesanan PO ${Number(qtyPesanan).toLocaleString('id-ID')} pcs` : undefined}>
                  <Input id={`po-close-denda-${pihak}-qty`} type="number" min="1" value={d.qty} onChange={(e) => set(pihak, 'qty', e.target.value)}
                    data-testid={`po-close-denda-${pihak}-qty`} />
                </Isian>
                <Isian label="Denda per pcs (Rp)" wajib>
                  <MoneyInput value={d.per_pcs} onChange={(e) => set(pihak, 'per_pcs', e.target.value)} data-testid={`po-close-denda-${pihak}-per_pcs`} />
                </Isian>
                <Isian label="Alasan" wajib htmlFor={`po-close-denda-${pihak}-alasan`} className="sm:col-span-2">
                  <Input id={`po-close-denda-${pihak}-alasan`} value={d.alasan} onChange={(e) => set(pihak, 'alasan', e.target.value)}
                    placeholder={b.contoh} data-testid={`po-close-denda-${pihak}-alasan`} />
                </Isian>
                <p className="text-sm sm:col-span-2" data-testid={`po-close-denda-${pihak}-jumlah`}>
                  Jumlah denda: <span className="font-semibold tabular-nums">{formatRupiah(jumlahDari(d))}</span>
                  <span className="text-muted-foreground"> ({Number(d.qty || 0).toLocaleString('id-ID')} pcs × {formatRupiah(Number(d.per_pcs) || 0)})</span>
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Nota denda satu PO (rincian baris di menu Tutup PO). */
export function DendaDaftarPO({ poId }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let alive = true;
    apiGet(`/production-pos-denda?po_id=${encodeURIComponent(poId)}`)
      .then((d) => { if (alive) setRows(Array.isArray(d) ? d : []); })
      .catch(() => { if (alive) setRows([]); });
    return () => { alive = false; };
  }, [poId]);
  if (rows === null) return <p className="text-sm text-muted-foreground">Memuat denda…</p>;
  return (
    <div className="space-y-1" data-testid={`po-denda-list-${poId}`}>
      <p className="text-sm font-semibold">Denda PO</p>
      <Table>
        <TableHeader><TableRow>
          <TableHead>Nomor</TableHead><TableHead>Jenis</TableHead><TableHead>Pihak</TableHead>
          <TableHead className="text-right">Qty × per pcs</TableHead><TableHead className="text-right">Jumlah</TableHead>
          <TableHead className="text-right">Sudah dipotong</TableHead><TableHead className="text-right">Sisa</TableHead><TableHead>Status</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {!rows.length && (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={8} className="p-0 [&>div]:py-6">
                <EmptyState icon={Receipt} title="Tidak ada denda untuk PO ini" description="Denda dari klien atau ke CMT diisi saat menutup PO." />
              </TableCell>
            </TableRow>
          )}
          {rows.map((r) => {
            const [label, tone] = STATUS_DENDA[r.status] || [r.status, 'default'];
            return (
              <TableRow key={r.id} data-testid={`po-denda-row-${r.id}`}>
                <TableCell className="text-sm font-medium whitespace-nowrap">{r.nomor}</TableCell>
                <TableCell className="text-sm">{BAGIAN[r.pihak]?.judul || r.pihak}
                  <span className="block text-xs text-muted-foreground">{r.alasan}</span></TableCell>
                <TableCell className="text-sm">{r.pihak_nama || '—'}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{Number(r.qty || 0).toLocaleString('id-ID')} × {formatRupiah(r.per_pcs)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatRupiah(r.jumlah)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatRupiah(r.jumlah_dipotong)}
                  {(r.potongan || []).map((p, i) => (
                    <span key={i} className="block text-xs text-muted-foreground">{p.nomor || 'tagihan'} {formatRupiah(p.jumlah)}</span>
                  ))}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatRupiah(r.sisa)}
                  {r.pihak === 'klien' && Number(r.kredit_klien) > 0 && (
                    <span className="block text-xs text-muted-foreground">{formatRupiah(r.kredit_klien)} jadi saldo kredit klien</span>
                  )}
                </TableCell>
                <TableCell><StatusBadge status={r.status} label={label} tone={tone} /></TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
