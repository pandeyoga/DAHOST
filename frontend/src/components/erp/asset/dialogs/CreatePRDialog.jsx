/**
 * CreatePRDialog — buat permintaan pengadaan beserta daftar barang.
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar ukuran panjang; setiap isian berlabel (dulu hanya
 * placeholder); kotak abu per barang → baris bergaris tipis; konfirmasi "tutup tanpa simpan" memakai dialog
 * aplikasi (dulu konfirmasi bawaan peramban); Enter di isian = simpan (dulu Ctrl+Enter). Isian & data yang dikirim sama.
 */
import { useState, useEffect } from 'react';
import { Plus, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apicall, fmtCurrency } from '../utils';
import { DepartmentSelect } from '../../hr/hrPickers';

const barisBaru = () => ({ name: '', specification: '', qty: 1, unit: 'pcs', estimated_price: '', notes: '' });

export function CreatePRDialog({ open, onClose, token, onCreated }) {
  const initialForm = {
    title: '', description: '', justification: '', priority: 'medium',
    request_type: 'asset', department: '',
    items: [barisBaru()],
  };
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [galat, setGalat] = useState('');
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  // Reset form whenever dialog re-opens (clear stale data)
  useEffect(() => {
    if (open) {
      setForm(initialForm);
      setLoading(false);
      setGalat('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const setItem = (idx, k, v) => setForm(p => ({
    ...p,
    items: p.items.map((it, i) => i === idx ? { ...it, [k]: v } : it),
  }));

  const addItem = () => setForm(p => ({ ...p, items: [...p.items, barisBaru()] }));
  const removeItem = (idx) => setForm(p => ({ ...p, items: p.items.filter((_, i) => i !== idx) }));

  const totalEst = form.items.reduce((s, i) => s + (Number(i.estimated_price) || 0) * (Number(i.qty) || 1), 0);

  const isValid = form.title.trim() !== '' && form.items.every(i => i.name && i.name.trim() !== '');

  const isDirty =
    form.title.trim() !== '' ||
    form.description.trim() !== '' ||
    form.justification.trim() !== '' ||
    form.items.some(i => (i.name || '').trim() !== '' || (i.specification || '').trim() !== '' || Number(i.estimated_price) > 0);

  const safeClose = async () => {
    if (loading) return; // tidak boleh close saat submit
    if (isDirty) {
      const ok = await confirmDialog({
        title: 'Tutup tanpa menyimpan?', body: 'Isian permintaan ini belum disimpan dan akan hilang.',
        confirmLabel: 'Tutup', danger: true,
      });
      if (!ok) return;
    }
    onClose();
  };

  const submit = async () => {
    if (!form.title.trim()) { setGalat('Judul wajib diisi.'); return; }
    if (form.items.some(i => !i.name)) { setGalat('Nama barang wajib diisi.'); return; }
    setGalat('');
    setLoading(true);
    try {
      const data = await apicall('POST', '/api/procurement/requests', token, {
        ...form,
        items: form.items.map(i => ({ ...i, qty: Number(i.qty) || 1, estimated_price: Number(i.estimated_price) || 0 })),
      });
      if (data.id) {
        toast.success(`Permintaan ${data.request_number} berhasil dibuat`);
        // Close dialog FIRST so UI updates immediately, then trigger reload.
        onClose();
        // defer onCreated to next tick so dialog close animation can start
        setTimeout(() => onCreated && onCreated(data), 0);
      } else {
        setGalat(data.detail || 'Gagal membuat permintaan.');
      }
    } catch (e) {
      setGalat(e.message || 'Gagal membuat permintaan.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <FormPopup open={open} onClose={safeClose} ukuran="panjang" testId="create-pr-dialog"
      judul="Buat permintaan pengadaan"
      keterangan="Ajukan permintaan pengadaan beserta daftar barang, perkiraan harga, dan prioritas."
      onSimpan={submit} labelSimpan="Buat permintaan" menyimpan={loading} bisaSimpan={isValid} galat={galat}>
      <Isian label="Judul" wajib htmlFor="pr-title">
        <Input id="pr-title" placeholder="Contoh: Mesin obras tambahan line 3" value={form.title}
          onChange={e => set('title', e.target.value)} data-testid="pr-title-input" autoFocus />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-3">
        <Isian label="Prioritas">
          <SmartNativeSelect value={form.priority} onChange={e => set('priority', e.target.value)} searchable={false}
            className="h-9 w-full" aria-label="Prioritas" data-testid="pr-priority">
            <option value="low">Rendah</option>
            <option value="medium">Sedang</option>
            <option value="high">Tinggi</option>
            <option value="urgent">Mendesak</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Jenis">
          <SmartNativeSelect value={form.request_type} onChange={e => set('request_type', e.target.value)} searchable={false}
            className="h-9 w-full" aria-label="Jenis" data-testid="pr-type">
            <option value="asset">Aset</option>
            <option value="consumable">Habis pakai</option>
            <option value="service">Jasa/layanan</option>
            <option value="other">Lainnya</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Departemen">
          {/* 2026-11-07 (OR1): Struktur Organisasi; bawaan = departemen karyawan pemohon (isian bawaan
              tidak dihitung "belum disimpan") */}
          {open && <DepartmentSelect token={token} value={form.department} defaultToMine testId="asset-pr-department"
            onChange={v => set('department', v)} />}
        </Isian>
      </div>
      <Isian label="Justifikasi" htmlFor="pr-justification" petunjuk="Mengapa barang ini dibutuhkan.">
        <Input id="pr-justification" placeholder="Justifikasi kebutuhan…" value={form.justification}
          onChange={e => set('justification', e.target.value)} />
      </Isian>

      {/* Daftar barang */}
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Daftar barang <span className="text-[hsl(var(--danger-text))]">*</span></p>
          <Button type="button" variant="outline" size="sm" onClick={addItem} data-testid="pr-add-item"><Plus />Tambah barang</Button>
        </div>
        {form.items.map((item, idx) => (
          <div key={idx} className="space-y-2 rounded-lg border border-[var(--glass-border)] p-3" data-testid={`pr-item-${idx}`}>
            <div className="flex items-center gap-2">
              <Input placeholder={`Nama barang ${idx + 1}`} aria-label={`Nama barang ${idx + 1}`} value={item.name}
                onChange={e => setItem(idx, 'name', e.target.value)} className="flex-1" />
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeItem(idx)}
                disabled={form.items.length === 1} title="Hapus barang" aria-label={`Hapus barang ${idx + 1}`}>
                <X />
              </Button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Input placeholder="Jumlah" aria-label="Jumlah" type="number" inputMode="numeric" value={item.qty}
                onChange={e => setItem(idx, 'qty', e.target.value)} />
              <Input placeholder="Satuan (pcs)" aria-label="Satuan" value={item.unit}
                onChange={e => setItem(idx, 'unit', e.target.value)} />
              <MoneyInput placeholder="Perkiraan harga (Rp)" aria-label="Perkiraan harga satuan" value={item.estimated_price}
                onChange={e => setItem(idx, 'estimated_price', e.target.value)} />
            </div>
            <Input placeholder="Spesifikasi / catatan" aria-label="Spesifikasi" value={item.specification}
              onChange={e => setItem(idx, 'specification', e.target.value)} />
          </div>
        ))}
        <p className="text-right text-sm">
          Perkiraan total: <span className="font-semibold tabular-nums">{fmtCurrency(totalEst)}</span>
        </p>
      </div>
    </FormPopup>
  );
}
