/**
 * DisposalRequestDialog — ajukan pelepasan aset bernilai buku tinggi (perlu persetujuan).
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar pendek, DatePicker, kotak kuning ber-emoji → Notice,
 * tombol kirim hijau (dulu kuning buatan sendiri). Isian & data yang dikirim sama.
 */
import { useState } from 'react';
import { toast } from 'sonner';
import { Textarea } from '@/components/ui/textarea';
import { MoneyInput } from '@/components/ui/money-input';
import DatePicker from '@/components/ui/date-picker';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { Notice } from '../../moduleAtoms';
import { apicall, fmtCurrency } from '../utils';
import { todayWIB } from '@/lib/waktu';

export function DisposalRequestDialog({ open, onClose, token, asset, onRequested }) {
  const [form, setForm] = useState({
    disposal_date: todayWIB(),
    disposal_value: '',
    reason: '',
  });
  const [loading, setLoading] = useState(false);
  const [galat, setGalat] = useState('');
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));
  const nbv = asset ? (parseFloat(asset.purchase_cost || 0) - parseFloat(asset.accumulated_depreciation || 0)) : 0;

  const submit = async () => {
    if (!form.reason.trim()) { setGalat('Alasan pelepasan wajib diisi.'); return; }
    setGalat('');
    setLoading(true);
    try {
      const data = await apicall('POST', `/api/assets/${asset.id}/request-disposal`, token, form);
      if (data?.id) {
        toast.success('Pengajuan pelepasan dikirim untuk persetujuan');
        onRequested?.();
        onClose();
      } else {
        setGalat(data?.detail || 'Gagal mengirim pengajuan.');
      }
    } catch (e) { setGalat(e.message || 'Gagal mengirim pengajuan.'); }
    finally { setLoading(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="disposal-request-form"
      judul="Ajukan pelepasan aset"
      keterangan={asset ? `${asset.name} · ${asset.asset_number}` : undefined}
      onSimpan={submit} labelSimpan="Kirim pengajuan" menyimpan={loading} galat={galat}>
      {asset && (
        <Notice tone="warning" title={`Nilai buku ${fmtCurrency(nbv)}`}>
          Aset bernilai tinggi — perlu persetujuan Keuangan/Admin sebelum dilepas.
        </Notice>
      )}
      <Isian label="Tanggal pelepasan">
        <DatePicker value={form.disposal_date} onChange={v => set('disposal_date', v)} bolehKosong={false}
          testId="disposal-date" />
      </Isian>
      <Isian label="Nilai jual (Rp)" petunjuk="Isi 0 bila aset dibuang." htmlFor="disposal-value">
        <MoneyInput id="disposal-value" placeholder="0" value={form.disposal_value} onChange={e => set('disposal_value', e.target.value)} />
      </Isian>
      <Isian label="Alasan pelepasan" wajib htmlFor="disposal-reason">
        <Textarea id="disposal-reason" rows={3} placeholder="Rusak total, tidak ekonomis diperbaiki…"
          value={form.reason} onChange={e => set('reason', e.target.value)} />
      </Isian>
    </FormPopup>
  );
}
