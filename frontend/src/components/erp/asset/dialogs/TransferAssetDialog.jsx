/**
 * TransferAssetDialog — Transfer asset to new location/department/employee.
 * Extracted from AssetManagementPortal.jsx (Phase 2 refactor)
 *
 * 2026-11-07 (audit form Tahap 5): penanggung jawab baru DIPILIH dari master karyawan (nama · NIK · departemen,
 * bisa dicari) — dulu dua kotak teks "Employee ID" + "Nama Employee" yang harus diketik cocok sendiri, sehingga
 * `assigned_to_id` bisa berisi teks yang bukan id karyawan. Departemen ikut terisi dari karyawan (tetap bisa diubah).
 *
 * Standar UI/UX v2 (8 Nov 2026): popup form standar pendek; posisi sekarang ditulis sebagai baris detail
 * (dulu kotak abu dengan judul HURUF BESAR); galat di kaki form.
 */
import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Input } from '@/components/ui/input';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import { apicall } from '../utils';
import { DepartmentSelect } from '../../hr/hrPickers';

export function TransferAssetDialog({ open, onClose, token, asset, onTransferred }) {
  const [form, setForm] = useState({
    to_location: '', to_department: '', to_employee_id: '', to_employee_name: '', reason: '', notes: '',
  });
  const [loading, setLoading] = useState(false);
  const [galat, setGalat] = useState('');
  const [employees, setEmployees] = useState([]);
  useEffect(() => {
    if (!open) return;
    setGalat('');
    apicall('GET', '/api/rahaza/employees?active_only=true&limit=500', token)
      .then((d) => setEmployees(Array.isArray(d) ? d : (d.items || [])))
      .catch(() => setEmployees([]));
  }, [open, token]);
  const pickEmployee = (id) => {
    const e = employees.find((x) => x.id === id);
    setForm((p) => ({ ...p, to_employee_id: id, to_employee_name: e ? e.name : '',
      to_department: e?.department || e?.department_name || p.to_department }));
  };

  useEffect(() => {
    if (asset) {
      setForm({
        to_location: asset.location || '',
        to_department: asset.department || '',
        to_employee_id: asset.assigned_to_id || '',
        to_employee_name: asset.assigned_to_name || '',
        reason: '', notes: '',
      });
    }
  }, [asset]);

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const submit = async () => {
    if (!form.to_location.trim() && !form.to_department.trim() && !form.to_employee_id.trim()) {
      setGalat('Isi minimal satu tujuan: lokasi, departemen, atau karyawan.');
      return;
    }
    if (!form.reason.trim()) { setGalat('Alasan pemindahan wajib diisi.'); return; }
    setGalat('');
    setLoading(true);
    try {
      const data = await apicall('POST', `/api/assets/${asset.id}/transfer`, token, form);
      if (data.ok) {
        toast.success('Aset dipindahkan');
        onTransferred();
        onClose();
      } else {
        setGalat(data.detail || 'Gagal memindahkan aset.');
      }
    } catch (e) { setGalat(e.message || 'Gagal memindahkan aset.'); }
    finally { setLoading(false); }
  };

  if (!asset) return null;

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="transfer-asset-form"
      judul="Pindahkan aset" keterangan={`${asset.asset_number} — ${asset.name}`}
      onSimpan={submit} labelSimpan="Pindahkan aset" menyimpan={loading} galat={galat}>
      <div>
        <p className="text-sm font-medium text-foreground">Posisi sekarang</p>
        <dl className="divide-y divide-[var(--glass-border)]">
          <BarisDetail label="Lokasi">{asset.location || '—'}</BarisDetail>
          <BarisDetail label="Departemen">{asset.department || '—'}</BarisDetail>
          <BarisDetail label="Dipegang">{asset.assigned_to_name || '—'}</BarisDetail>
        </dl>
      </div>
      <p className="border-t border-[var(--glass-border)] pt-3 text-sm font-medium text-foreground">Pindah ke</p>
      <Isian label="Lokasi baru" htmlFor="transfer-location">
        <Input id="transfer-location" placeholder="Rak A-12, gudang utama…" value={form.to_location}
          onChange={e => set('to_location', e.target.value)} data-testid="transfer-location-input" />
      </Isian>
      <Isian label="Departemen baru">
        {/* 2026-11-07 (OR1): dari Struktur Organisasi; Lokasi Baru (tempat fisik) tetap isian bebas */}
        <DepartmentSelect token={token} value={form.to_department} testId="transfer-department"
          placeholder="— Tidak diubah —" onChange={v => set('to_department', v)} />
      </Isian>
      <Isian label="Penanggung jawab (karyawan)">
        <SmartNativeSelect value={form.to_employee_id} onChange={e => pickEmployee(e.target.value)} className="h-9 w-full"
          searchPlaceholder="Cari nama / NIK karyawan…" data-testid="transfer-employee">
          <option value="">— Tidak diubah / tanpa penanggung jawab —</option>
          {form.to_employee_id && !employees.some(e => e.id === form.to_employee_id) && (
            <option value={form.to_employee_id}>{form.to_employee_name || 'Penanggung jawab sekarang'}</option>
          )}
          {employees.map(e => (
            <option key={e.id} value={e.id}>{[e.name, e.employee_code || e.nik, e.department || e.department_name].filter(Boolean).join(' · ')}</option>
          ))}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Alasan pemindahan" wajib htmlFor="transfer-reason">
        <Input id="transfer-reason" placeholder="Relokasi departemen, penugasan baru…" value={form.reason}
          onChange={e => set('reason', e.target.value)} data-testid="transfer-reason-input" />
      </Isian>
      <Isian label="Catatan" htmlFor="transfer-notes">
        <Input id="transfer-notes" placeholder="Catatan tambahan…" value={form.notes}
          onChange={e => set('notes', e.target.value)} />
      </Isian>
    </FormPopup>
  );
}
