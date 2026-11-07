/**
 * AdditionalRequestModal — Phase 16
 *
 * Reusable modal untuk membuat permintaan material ADDITIONAL (tambahan).
 * Digunakan di 3 entry point:
 *   1) Auto-prompt setelah Inspeksi Material (jika ada missing qty)
 *   2) "Ajukan Ulang" dari permintaan yang Rejected
 *   3) "Buat Permintaan Manual" pada kiriman yang sudah diinspeksi
 *
 * Props:
 *   - shipment: { id, shipment_number, vendor_name, po_id, po_number, ... }
 *   - defaultItems: array of items dengan field
 *       { shipment_item_id?, po_item_id?, sku, product_name, size, color,
 *         serial_number, requested_qty, reason, max_qty? }
 *   - defaultReason: string (alasan overall default, optional)
 *   - previousRequestId: string optional (untuk mode "Ajukan Ulang")
 *   - previousRequestNumber: string optional (untuk display)
 *   - inspectionId: string optional (link ke inspeksi)
 *   - mode: 'inspection' | 'resubmit' | 'manual'
 *   - onClose: () => void
 *   - onSuccess: (newRequest) => void
 */
import { useState } from 'react';
import { AlertCircle, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { StatusBadge } from '../moduleAtoms';
import { apiPost } from '../../../lib/api';

const MODE_LABELS = {
  inspection: {
    title: 'Ajukan permintaan bahan tambahan',
    subtitle: 'Material yang hilang/kurang saat inspeksi akan diajukan ke ERP untuk dikirim ulang.',
    submitLabel: 'Ajukan ke DA',
    badge: 'Dari inspeksi',
    badgeColor: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))]',
  },
  resubmit: {
    title: 'Ajukan ulang permintaan',
    subtitle: 'Permintaan sebelumnya ditolak. Anda dapat merevisi qty/alasan dan mengajukan ulang.',
    submitLabel: 'Kirim permintaan baru',
    badge: 'Ajukan ulang',
    badgeColor: 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]',
  },
  manual: {
    title: 'Buat permintaan bahan tambahan',
    subtitle: 'Buat permintaan tambahan secara manual untuk kiriman yang sudah diinspeksi.',
    submitLabel: 'Kirim permintaan',
    badge: 'Manual',
    badgeColor: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))]',
  },
};

// ── PERMINTAAN PENGGANTI (REPLACEMENT) — 2026-06 ────────────────────────────
// Jenis permintaan ini SUDAH didukung backend (`POST /api/material-requests`
// request_type='REPLACEMENT' → approval membuat surat jalan anak "-R1"), tetapi
// tidak punya satu pun pintu di layar: tombol buat hanya dirender untuk tab
// TAMBAHAN, dan jalur lamanya (Laporan Cacat Material) sudah dimatikan backend
// dengan HTTP 410. Label dipisah supaya vendor tahu ini untuk barang CACAT/RUSAK
// (bukan kurang kirim) — dua hal yang penanganannya berbeda.
const REPLACEMENT_LABELS = {
  inspection: {
    title: 'Ajukan permintaan bahan pengganti',
    subtitle: 'Material cacat/rusak diajukan ke ERP untuk DIGANTI dengan kiriman baru.',
    submitLabel: 'Ajukan ke DA',
    badge: 'Pengganti',
    badgeColor: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))]',
  },
  resubmit: {
    title: 'Ajukan Ulang Permintaan Pengganti',
    subtitle: 'Permintaan sebelumnya ditolak. Anda dapat merevisi qty/alasan dan mengajukan ulang.',
    submitLabel: 'Kirim permintaan baru',
    badge: 'PENGGANTI · AJUKAN ULANG',
    badgeColor: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))]',
  },
  manual: {
    title: 'Buat Permintaan Material Pengganti',
    subtitle: 'Untuk material yang CACAT/RUSAK (bukan kurang kirim). Sebutkan cacatnya pada alasan per-item.',
    submitLabel: 'Kirim permintaan',
    badge: 'Pengganti',
    badgeColor: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))]',
  },
};

export default function AdditionalRequestModal({
  shipment,
  defaultItems = [],
  defaultReason = '',
  previousRequestId = '',
  previousRequestNumber = '',
  inspectionId = '',
  mode = 'inspection',
  requestType = 'ADDITIONAL',
  onClose,
  onSuccess,
}) {
  const isReplacement = requestType === 'REPLACEMENT';
  const cfg = (isReplacement ? REPLACEMENT_LABELS : MODE_LABELS)[mode]
    || (isReplacement ? REPLACEMENT_LABELS.manual : MODE_LABELS.manual);
  const [overallReason, setOverallReason] = useState(
    defaultReason || (isReplacement
      ? `Material cacat/rusak pada shipment ${shipment?.shipment_number || ''} — mohon diganti`
      : `Material missing/kurang dari shipment ${shipment?.shipment_number || ''}`)
  );
  const [items, setItems] = useState(
    (defaultItems || []).map((it) => ({
      shipment_item_id: it.shipment_item_id || '',
      po_item_id: it.po_item_id || '',
      sku: it.sku || '',
      product_name: it.product_name || '',
      size: it.size || '',
      color: it.color || '',
      serial_number: it.serial_number || '',
      requested_qty: Number(it.requested_qty || 0),
      max_qty: it.max_qty != null ? Number(it.max_qty) : null,
      reason: it.reason || '',
    }))
  );
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});

  const updateItem = (idx, field, value) => {
    const next = [...items];
    next[idx] = { ...next[idx], [field]: value };
    setItems(next);
    // Clear field-level error when user types
    if (errors[`item-${idx}-${field}`]) {
      const e = { ...errors };
      delete e[`item-${idx}-${field}`];
      setErrors(e);
    }
  };

  const removeItem = (idx) => {
    setItems(items.filter((_, i) => i !== idx));
  };

  const validate = () => {
    const e = {};
    if (!overallReason.trim()) {
      e.overallReason = 'Alasan keseluruhan wajib diisi';
    }
    const validItems = items.filter((it) => Number(it.requested_qty) > 0);
    if (validItems.length === 0) {
      e.items = 'Minimal harus ada 1 item dengan qty > 0';
    }
    items.forEach((it, idx) => {
      if (Number(it.requested_qty) <= 0) return; // skip 0-qty rows (treated as removed)
      if (it.max_qty != null && Number(it.requested_qty) > it.max_qty) {
        e[`item-${idx}-requested_qty`] = `Maks. ${it.max_qty} pcs`;
      }
      if (!it.reason || !it.reason.trim()) {
        e[`item-${idx}-reason`] = 'Alasan per-item wajib diisi';
      }
    });
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) {
      toast.error('Mohon perbaiki kolom yang ditandai');
      return;
    }
    setLoading(true);
    try {
      const payloadItems = items
        .filter((it) => Number(it.requested_qty) > 0)
        .map((it) => ({
          shipment_item_id: it.shipment_item_id,
          po_item_id: it.po_item_id,
          sku: it.sku,
          product_name: it.product_name,
          size: it.size,
          color: it.color,
          serial_number: it.serial_number,
          requested_qty: Number(it.requested_qty),
          reason: it.reason.trim(),
        }));
      const body = {
        request_type: requestType,
        original_shipment_id: shipment.id,
        po_id: shipment.po_id || '',
        po_number: shipment.po_number || '',
        reason: overallReason.trim(),
        items: payloadItems,
        inspection_id: inspectionId,
        previous_request_id: previousRequestId,
      };
      const data = await apiPost('/material-requests', body);
      toast.success(`Permintaan ${data.request_number} berhasil diajukan ke ERP`);
      if (onSuccess) onSuccess(data);
      onClose();
    } catch (err) {
      toast.error(err.message || 'Gagal mengajukan permintaan');
    } finally {
      setLoading(false);
    }
  };

  // Standar UI/UX v2 (8 Nov 2026): FormPopup panjang — kaki galat · Batal · kirim (hijau); isi & validasi sama.
  const nKesalahan = Object.keys(errors).length;
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="additional-request-modal" judul={cfg.title}
      keterangan={cfg.subtitle} onSimpan={handleSubmit} menyimpan={loading} labelSimpan={cfg.submitLabel}
      galat={nKesalahan ? 'Periksa isian yang ditandai merah.' : null}>
        <div className="flex items-center gap-3 flex-wrap">
          <span data-testid="additional-request-mode-badge"><StatusBadge status={mode} label={cfg.badge} tone="warning" /></span>
          {previousRequestNumber && (
            <span className="text-xs text-muted-foreground">
              Asal dari permintaan: <span className="tabular-nums font-semibold text-foreground">{previousRequestNumber}</span>
            </span>
          )}
        </div>

        <dl className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div><dt className="text-xs text-muted-foreground">Kiriman asal</dt><dd className="tabular-nums font-medium">{shipment?.shipment_number || '—'}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Vendor</dt><dd className="font-medium">{shipment?.vendor_name || '—'}</dd></div>
          <div><dt className="text-xs text-muted-foreground">PO</dt><dd className="tabular-nums">{shipment?.po_number || '—'}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Total qty diminta</dt>
            <dd className="font-semibold tabular-nums">{items.reduce((s, it) => s + Number(it.requested_qty || 0), 0).toLocaleString('id-ID')} pcs</dd></div>
        </dl>

        <Isian label="Alasan keseluruhan" wajib galat={errors.overallReason}>
          <Textarea rows={2} value={overallReason}
            onChange={(e) => {
              setOverallReason(e.target.value);
              if (errors.overallReason) {
                const ne = { ...errors };
                delete ne.overallReason;
                setErrors(ne);
              }
            }}
            placeholder="Jelaskan alasan utama permintaan bahan tambahan…"
            data-testid="additional-request-overall-reason" />
        </Isian>

        <section className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-foreground">Barang yang diminta ({items.filter((i) => Number(i.requested_qty) > 0).length})</p>
            {errors.items && (
              <p className="text-xs text-[hsl(var(--danger-text))] flex items-center gap-1"><AlertCircle className="w-3 h-3" /> {errors.items}</p>
            )}
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>
                <TableHead>Produk</TableHead><TableHead>SKU</TableHead><TableHead>No. seri</TableHead><TableHead>Ukuran / warna</TableHead>
                <TableHead className="text-right">Qty diminta</TableHead><TableHead>Alasan *</TableHead><TableHead className="w-10" />
              </TableRow></TableHeader>
              <TableBody>
                {items.length === 0 && (
                  <TableRow><TableCell colSpan={7} className="py-6 text-center text-muted-foreground">Tidak ada baris. Tambahkan dari kiriman asal.</TableCell></TableRow>
                )}
                {items.map((it, idx) => {
                  const qtyErr = errors[`item-${idx}-requested_qty`];
                  const reasonErr = errors[`item-${idx}-reason`];
                  return (
                    <TableRow key={idx}>
                      <TableCell className="font-medium">{it.product_name || '—'}</TableCell>
                      <TableCell className="tabular-nums">{it.sku || '—'}</TableCell>
                      <TableCell className="tabular-nums">{it.serial_number || '—'}</TableCell>
                      <TableCell>{it.size || '—'}/{it.color || '—'}</TableCell>
                      <TableCell className="text-right">
                        <Input type="number" min={0} max={it.max_qty != null ? it.max_qty : undefined}
                          className={`h-8 w-24 ml-auto text-right ${qtyErr ? 'border-[hsl(var(--destructive))]' : ''}`}
                          value={it.requested_qty} onChange={(e) => updateItem(idx, 'requested_qty', e.target.value)}
                          aria-label={`Qty diminta ${it.product_name || ''}`} data-testid={`additional-request-item-qty-${idx}`} />
                        {it.max_qty != null && <p className="text-xs text-muted-foreground mt-0.5">maks {it.max_qty}</p>}
                        {qtyErr && <p className="text-xs text-[hsl(var(--danger-text))] mt-0.5">{qtyErr}</p>}
                      </TableCell>
                      <TableCell>
                        <Input className={`h-8 min-w-[12rem] ${reasonErr ? 'border-[hsl(var(--destructive))]' : ''}`} value={it.reason}
                          onChange={(e) => updateItem(idx, 'reason', e.target.value)} placeholder="Alasan untuk baris ini…"
                          aria-label={`Alasan ${it.product_name || ''}`} data-testid={`additional-request-item-reason-${idx}`} />
                        {reasonErr && <p className="text-xs text-[hsl(var(--danger-text))] mt-0.5">{reasonErr}</p>}
                      </TableCell>
                      <TableCell className="text-center">
                        <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeItem(idx)} title="Hapus baris" aria-label="Hapus baris"
                          data-testid={`additional-request-item-remove-${idx}`}><Trash2 className="w-3.5 h-3.5" /></Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">Setel qty ke 0 atau hapus baris untuk mengeluarkan barang dari permintaan ini.</p>
        </section>
    </FormPopup>
  );
}
