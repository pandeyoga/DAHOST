/**
 * ReturnLoanDialog — Terima kembali aset yang dipinjam (ACC-3).
 *
 * Kondisi saat kembali menentukan status aset setelahnya:
 *   Baik   → aset kembali `Aktif` (siap dipinjam lagi)
 *   Rusak  → aset jadi `Pemeliharaan` + otomatis dibuatkan catatan maintenance
 *            (supaya kerusakan tidak hilang jejak)
 *   Hilang → aset jadi `Hilang` (tidak bisa dipinjam, perlu tindak lanjut)
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar pendek, DatePicker, peringatan terlambat = Notice,
 * pesan sukses memakai label kondisi (dulu kode mentah "good/damaged/lost").
 */
import { useState, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import DatePicker from '@/components/ui/date-picker';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Notice } from '../../moduleAtoms';
import { apicall, fmtDate } from '../utils';
import { RETURN_CONDITION_LABEL } from '../constants';
import { todayWIB } from '@/lib/waktu';

const CONDITION_HINT = {
  good: 'Aset akan kembali berstatus Aktif dan siap dipinjam lagi.',
  damaged: 'Aset akan berstatus Pemeliharaan dan otomatis dibuatkan catatan perbaikan.',
  lost: 'Aset akan berstatus Hilang dan tidak bisa dipinjam lagi sampai ada tindak lanjut.',
};

export function ReturnLoanDialog({ open, onClose, token, loan, onReturned }) {
  const [form, setForm] = useState({ return_date: todayWIB(), condition: 'good', return_notes: '' });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open) {
      setForm({ return_date: todayWIB(), condition: 'good', return_notes: '' });
      setErr('');
    }
  }, [open, loan]);

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const submit = async () => {
    if (!loan) return;
    if (form.condition !== 'good' && !form.return_notes.trim()) {
      setErr('Catatan wajib diisi untuk kondisi rusak/hilang (untuk jejak audit).');
      return;
    }
    setSaving(true); setErr('');
    try {
      const d = await apicall('POST', `/api/assets/loans/${loan.id}/return`, token, form);
      toast.success(`${loan.asset_number} dikembalikan (${RETURN_CONDITION_LABEL[form.condition] || form.condition})`);
      onReturned?.(d);
      onClose();
    } catch (e) {
      setErr(e.message || 'Gagal mencatat pengembalian');
    } finally { setSaving(false); }
  };

  if (!loan) return null;

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="asset-loan-return-dialog"
      judul="Kembalikan aset"
      keterangan={`${loan.loan_number} · ${loan.asset_number} — ${loan.asset_name}. Dipinjam ${loan.borrower_name}`
        + `${loan.borrower_divisi ? ` (${loan.borrower_divisi})` : ''} sejak ${fmtDate(loan.loan_date)}.`}
      onSimpan={submit} labelSimpan="Kembalikan" menyimpan={saving}
      galat={err && <span data-testid="asset-return-error">{err}</span>}>
      {loan.is_overdue && (
        <Notice tone="warning" icon={AlertTriangle} title={`Terlambat ${loan.days_overdue} hari`}>
          Target kembali {fmtDate(loan.expected_return_date)}.
        </Notice>
      )}
      <Isian label="Tanggal kembali" wajib>
        <DatePicker value={form.return_date} onChange={v => set('return_date', v)} bolehKosong={false}
          testId="asset-return-date" />
      </Isian>
      <Isian label="Kondisi aset" wajib petunjuk={CONDITION_HINT[form.condition]}>
        <SmartNativeSelect value={form.condition} onChange={e => set('condition', e.target.value)}
          className="w-full" searchable={false} data-testid="asset-return-condition">
          <option value="good">Baik — siap dipakai lagi</option>
          <option value="damaged">Rusak — perlu perbaikan</option>
          <option value="lost">Hilang — tidak kembali</option>
        </SmartNativeSelect>
      </Isian>
      <Isian label="Catatan" wajib={form.condition !== 'good'} htmlFor="return-notes">
        <Input id="return-notes" value={form.return_notes} onChange={e => set('return_notes', e.target.value)}
          placeholder={form.condition === 'good' ? 'Opsional' : 'Jelaskan kerusakan / kronologi hilang'}
          data-testid="asset-return-notes" />
      </Isian>
    </FormPopup>
  );
}
