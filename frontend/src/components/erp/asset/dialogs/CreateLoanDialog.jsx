/**
 * CreateLoanDialog — Pinjamkan 1 unit aset (ACC-3).
 *
 * Kenapa 1 unit (bukan qty): peminjaman itu domain ASET — yang dipinjam adalah
 * unit fisik ber-nomor (AST-xx-2026-0001), bukan barang habis pakai. Dropdown
 * hanya menampilkan aset yang benar-benar SIAP dipinjam (endpoint
 * /api/assets/loanable-assets sudah mengecualikan aset yang sedang dipinjam,
 * dalam pemeliharaan, atau sudah dilepas).
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar (panjang, 8 isian), pemilih tanggal seragam
 * (dulu isian tanggal bawaan peramban), galat di kaki form. Isian & aturan sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { Input } from '@/components/ui/input';
import DatePicker from '@/components/ui/date-picker';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { toast } from 'sonner';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { apicall } from '../utils';
import { todayWIB } from '@/lib/waktu';

export function CreateLoanDialog({ open, onClose, token, onCreated }) {
  const [assets, setAssets] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loadingRef, setLoadingRef] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [form, setForm] = useState({
    asset_id: '', borrower_id: '', borrower_name: '', borrower_divisi: '',
    purpose: '', loan_date: todayWIB(), expected_return_date: '', notes: '',
  });

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const loadRef = useCallback(async () => {
    setLoadingRef(true);
    try {
      const [as, emp] = await Promise.all([
        apicall('GET', '/api/assets/loanable-assets', token),
        apicall('GET', '/api/rahaza/employees?active_only=true&limit=500', token).catch(() => ({ items: [] })),
      ]);
      setAssets(Array.isArray(as) ? as : []);
      setEmployees(Array.isArray(emp) ? emp : (emp.items || []));
    } catch (e) {
      setErr(e.message || 'Gagal memuat daftar aset');
    } finally { setLoadingRef(false); }
  }, [token]);

  useEffect(() => {
    if (!open) return;
    setErr('');
    setForm({
      asset_id: '', borrower_id: '', borrower_name: '', borrower_divisi: '',
      purpose: '', loan_date: todayWIB(), expected_return_date: '', notes: '',
    });
    loadRef();
  }, [open, loadRef]);

  // Pilih karyawan → isi otomatis nama + divisi (tetap bisa diubah manual
  // supaya peminjam eksternal/vendor juga bisa dicatat).
  const pickEmployee = (id) => {
    const e = employees.find(x => x.id === id);
    setForm(p => ({
      ...p,
      borrower_id: id,
      borrower_name: e ? e.name : p.borrower_name,
      borrower_divisi: e ? (e.department || p.borrower_divisi) : p.borrower_divisi,
    }));
  };

  const submit = async () => {
    // Kumpulkan SEMUA field wajib yang kosong sekaligus supaya user tidak
    // menebak satu-satu (submit → perbaiki → submit → error lain).
    const missing = [];
    if (!form.asset_id) missing.push('Aset');
    if (!form.borrower_name.trim()) missing.push('Nama peminjam');
    if (missing.length) {
      setErr(`${missing.join(' & ')} wajib diisi.`);
      return;
    }
    setSaving(true); setErr('');
    try {
      const d = await apicall('POST', '/api/assets/loans', token, form);
      toast.success(`Peminjaman ${d.loan_number} dicatat`);
      onCreated?.(d);
      onClose();
    } catch (e) {
      setErr(e.message || 'Gagal mencatat peminjaman');
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="asset-loan-create-dialog"
      judul="Pinjamkan aset"
      keterangan="Catat alat/aset yang dibawa keluar. Aset berstatus Dipinjam sampai dikembalikan."
      onSimpan={submit} labelSimpan="Catat peminjaman" menyimpan={saving} galat={err && <span data-testid="asset-loan-error">{err}</span>}>
      <Isian label="Aset" wajib
        petunjuk={!loadingRef && assets.length === 0
          ? 'Tidak ada aset yang siap dipinjam. Tambah aset baru di tab Aset, atau kembalikan aset yang sedang dipinjam / selesaikan pemeliharaannya.'
          : 'Hanya aset yang siap dipinjam.'}>
        <SmartNativeSelect value={form.asset_id} onChange={e => set('asset_id', e.target.value)}
          className="w-full" data-testid="asset-loan-asset">
          <option value="">{loadingRef ? 'Memuat aset…' : '— pilih aset —'}</option>
          {assets.map(a => (
            <option key={a.id} value={a.id}>
              {a.asset_number} · {a.name}{a.category_name ? ` (${a.category_name})` : ''}
            </option>
          ))}
        </SmartNativeSelect>
      </Isian>

      <Isian label="Peminjam (karyawan)" petunjuk="Opsional. Nama dan divisi terisi otomatis; peminjam luar (vendor) cukup diketik.">
        <SmartNativeSelect value={form.borrower_id} onChange={e => pickEmployee(e.target.value)}
          className="w-full" data-testid="asset-loan-employee">
          <option value="">— pilih karyawan (opsional) —</option>
          {employees.map(e => (
            <option key={e.id} value={e.id}>
              {e.employee_code ? `${e.employee_code} · ` : ''}{e.name}{e.department ? ` (${e.department})` : ''}
            </option>
          ))}
        </SmartNativeSelect>
      </Isian>

      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Nama peminjam" wajib htmlFor="loan-borrower">
          <Input id="loan-borrower" value={form.borrower_name} onChange={e => set('borrower_name', e.target.value)}
            placeholder="Nama lengkap / vendor" data-testid="asset-loan-borrower" />
        </Isian>
        <Isian label="Divisi / unit" htmlFor="loan-divisi">
          <Input id="loan-divisi" value={form.borrower_divisi} onChange={e => set('borrower_divisi', e.target.value)}
            placeholder="Contoh: Produksi" data-testid="asset-loan-divisi" />
        </Isian>
      </div>

      <Isian label="Tujuan pemakaian" htmlFor="loan-purpose">
        <Input id="loan-purpose" value={form.purpose} onChange={e => set('purpose', e.target.value)}
          placeholder="Contoh: perbaikan mesin jahit line 2" data-testid="asset-loan-purpose" />
      </Isian>

      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Tanggal pinjam" wajib>
          <DatePicker value={form.loan_date} onChange={v => set('loan_date', v)} bolehKosong={false}
            testId="asset-loan-date" />
        </Isian>
        <Isian label="Target kembali" petunjuk="Kosong = tidak ditentukan.">
          <DatePicker value={form.expected_return_date} onChange={v => set('expected_return_date', v)}
            placeholder="Tidak ditentukan" testId="asset-loan-expected" />
        </Isian>
      </div>

      <Isian label="Catatan" htmlFor="loan-notes">
        <Input id="loan-notes" value={form.notes} onChange={e => set('notes', e.target.value)}
          placeholder="Kondisi saat keluar, kelengkapan, dll." data-testid="asset-loan-notes" />
      </Isian>
    </FormPopup>
  );
}
