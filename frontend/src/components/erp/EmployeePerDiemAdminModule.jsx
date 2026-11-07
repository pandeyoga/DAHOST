/**
 * Employee Per Diem Admin Module — tab "Tarif uang harian" di menu SDM › Klaim Dinas.
 * CV. Dewi Aditya — Employee Expense Management (EEM)
 *
 * Admin/HR mengatur tarif uang harian (per diem) per jenis perjalanan. Tarif ini dipakai menghitung
 * perkiraan uang harian saat karyawan mengajukan perjalanan dinas.
 *
 * Standar UI/UX v2 (8 Nov 2026): tiga kartu berwarna ber-emoji + kotak info biru → satu tabel (kartu ringkas
 * di HP) dengan unduh Excel/CSV; form ubah tarif = FormPopup pendek dengan DatePicker. Data yang dikirim sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { Pencil, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;

const DEST_TYPES = [
  { value: 'dalam_kota',  label: 'Dalam Kota',  description: 'Perjalanan dalam kota yang sama' },
  { value: 'luar_kota',   label: 'Luar Kota',   description: 'Perjalanan ke kota/provinsi lain' },
  { value: 'luar_negeri', label: 'Luar Negeri', description: 'Perjalanan ke luar negeri' },
];
const jenis = (rate) => DEST_TYPES.find(d => d.value === rate.destination_type) || {};
const namaJenis = (rate) => {
  const s = rate.label || jenis(rate).label || 'Jenis lain';
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
};
const totalHarian = (r) => (Number(r.daily_rate) || 0) + (Number(r.meal_allowance) || 0) + (Number(r.transport_allowance) || 0);
const keadaan = (r) => (r.is_default ? { label: 'Bawaan, belum diatur', tone: 'warning' }
  : r.is_active === false ? { label: 'Nonaktif', tone: 'danger' } : { label: 'Aktif', tone: 'success' });
// Catatan bawaan server ("Default rate — belum dikonfigurasi") tidak ditampilkan apa adanya.
const catatan = (r) => (r.is_default ? 'Tarif bawaan sistem; belum pernah diatur.' : (r.notes || ''));

function RateFormDialog({ rate, onClose, token, onSaved }) {
  const dt = jenis(rate);
  const [form, setForm] = useState({
    daily_rate: rate.daily_rate || 0,
    meal_allowance: rate.meal_allowance || 0,
    transport_allowance: rate.transport_allowance || 0,
    effective_date: rate.effective_date || todayWIB(),
    notes: rate.notes || '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const handleSave = async () => {
    if (form.daily_rate <= 0) { setError('Uang harian harus lebih dari 0'); return; }
    setSaving(true); setError('');
    try {
      const body = {
        destination_type: rate.destination_type,
        label: dt.label,
        daily_rate: parseFloat(form.daily_rate),
        meal_allowance: parseFloat(form.meal_allowance) || 0,
        transport_allowance: parseFloat(form.transport_allowance) || 0,
        effective_date: form.effective_date,
        notes: form.notes,
      };
      const method = rate.is_default || !rate.id ? 'POST' : 'PUT';
      const url = rate.is_default || !rate.id
        ? `${API}/api/hr/expenses/per-diem-rates`
        : `${API}/api/hr/expenses/per-diem-rates/${rate.id}`;
      const r = await fetch(url, {
        method,
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan');
      onSaved();
      onClose();
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="per-diem-form"
      judul={`Tarif uang harian · ${namaJenis(rate)}`} keterangan={dt.description}
      onSimpan={handleSave} labelSimpan="Simpan tarif" menyimpan={saving} galat={error}>
      <Isian label="Uang harian (Rp/hari)" wajib petunjuk="Biaya hidup harian karyawan selama dinas.">
        <MoneyInput value={form.daily_rate} onChange={e => set('daily_rate', e.target.value)} placeholder="Contoh: 300.000"
          data-testid="per-diem-daily" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Uang makan (Rp/hari)">
          <MoneyInput value={form.meal_allowance} onChange={e => set('meal_allowance', e.target.value)} placeholder="Contoh: 75.000" />
        </Isian>
        <Isian label="Tunjangan transport (Rp/hari)">
          <MoneyInput value={form.transport_allowance} onChange={e => set('transport_allowance', e.target.value)} placeholder="Contoh: 100.000" />
        </Isian>
      </div>
      <Isian label="Berlaku sejak">
        <DatePicker value={form.effective_date} onChange={v => set('effective_date', v)} bolehKosong={false}
          testId="per-diem-effective" />
      </Isian>
      <Isian label="Catatan" htmlFor="per-diem-notes">
        <Input id="per-diem-notes" placeholder="Opsional" value={form.notes} onChange={e => set('notes', e.target.value)} />
      </Isian>
      <div className="flex items-center justify-between border-t border-[var(--glass-border)] pt-3">
        <span className="text-sm font-medium">Total per hari</span>
        <span className="text-base font-semibold tabular-nums">{fmt(totalHarian(form))}</span>
      </div>
    </FormPopup>
  );
}

export default function EmployeePerDiemAdminModule({ token, user }) {
  const [rates, setRates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const headers = { Authorization: `Bearer ${token}` };

  const fetchRates = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/hr/expenses/per-diem-rates`, { headers });
      const d = await r.json();
      setRates(Array.isArray(d.items) ? d.items : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchRates(); }, [fetchRates]);

  const kolom = [
    { kunci: 'jenis', label: 'Jenis perjalanan', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{namaJenis(r)}</p>
        <p className="text-xs text-muted-foreground" title={catatan(r)}>{jenis(r).description || ''}</p>
      </div>) },
    { kunci: 'harian', label: 'Uang harian', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.daily_rate)}</span> },
    { kunci: 'makan', label: 'Uang makan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.meal_allowance)}</span> },
    { kunci: 'transport', label: 'Transport', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.transport_allowance)}</span> },
    { kunci: 'total', label: 'Total per hari', rata: 'kanan', isi: (r) => <span className="font-semibold tabular-nums">{fmt(totalHarian(r))}</span> },
    { kunci: 'berlaku', label: 'Berlaku sejak', isi: (r) => (r.effective_date ? formatTanggalID(r.effective_date) || r.effective_date : '—') },
    { kunci: 'status', label: 'Status', isi: (r) => { const k = keadaan(r); return <StatusBadge status={k.label} label={k.label} tone={k.tone} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => setEditing(r)} data-testid={`per-diem-edit-${r.destination_type}`}>
        <Pencil />{r.is_default ? 'Atur' : 'Ubah'}
      </Button>) },
  ];

  return (
    <PageLayout testId="per-diem-admin-page" title="Tarif uang harian"
      subtitle="Tarif per jenis perjalanan, dipakai menghitung perkiraan uang harian saat karyawan mengajukan perjalanan dinas."
      tools={<>
        <TombolUnduh namaBerkas="tarif-uang-harian" namaLembar="Tarif uang harian" baris={rates} testId="per-diem-unduh"
          kolom={[
            { label: 'Jenis perjalanan', nilai: (r) => namaJenis(r) },
            { label: 'Uang harian', nilai: (r) => Number(r.daily_rate || 0) },
            { label: 'Uang makan', nilai: (r) => Number(r.meal_allowance || 0) },
            { label: 'Transport', nilai: (r) => Number(r.transport_allowance || 0) },
            { label: 'Total per hari', nilai: (r) => totalHarian(r) },
            { label: 'Berlaku sejak', nilai: (r) => (r.effective_date ? formatTanggalID(r.effective_date) : '') },
            { label: 'Status', nilai: (r) => keadaan(r).label },
            { label: 'Catatan', nilai: (r) => catatan(r) },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchRates} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && rates.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat tarif…</p>
      ) : (
        <TabelData kolom={kolom} baris={rates} kunci={(r) => r.destination_type} onKlikBaris={setEditing}
          testId="per-diem-table"
          kosong={<EmptyState title="Belum ada tarif" description="Server tidak mengirim tarif uang harian. Muat ulang atau hubungi admin." />} />
      )}

      {editing && (
        <RateFormDialog rate={editing} token={token} onClose={() => setEditing(null)} onSaved={fetchRates} />
      )}
    </PageLayout>
  );
}
