/**
 * Tunjangan tetap (tab di hub Penggajian) — template tunjangan yang otomatis masuk slip saat run gaji dibuat.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu judul buatan sendiri + kotak info biru + `p-6`),
 * penyaring satu baris, daftar = TabelData + unduh Excel/CSV, tombol baris selalu tampak (dulu hanya saat
 * kursor di atas baris), form = FormPopup standar. API & data yang dikirim tidak berubah.
 * Perbaikan pemilih: daftar "Karyawan tertentu" dulu hanya menampilkan 50 karyawan pertama hasil saringan
 * (karyawan ke-51 dst. tidak bisa dipilih tanpa mencari) — kini semua karyawan aktif tampil (gulir).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Checkbox } from '@/components/ui/checkbox';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState } from './moduleAtoms';
import { useHrMasters, useDepartmentFilterOptions } from './hr/hrPickers';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;

const SCOPE_CFG = {
  all:        { label: 'Semua karyawan' },
  department: { label: 'Per departemen' },
  employee:   { label: 'Karyawan tertentu' },
};
const CALC_LABEL = { fixed: 'Jumlah tetap', percentage_gross: '% dari bruto' };
const jumlahLabel = (it) => (it.calc_type === 'percentage_gross'
  ? `${String(it.amount ?? 0).replace('.', ',')}% dari bruto` : fmtRp(it.amount));
const cakupanLabel = (it) => {
  const s = (SCOPE_CFG[it.applicable_to] || SCOPE_CFG.all).label;
  if (it.applicable_to === 'department' && it.department) return `${s} · ${it.department}`;
  if (it.applicable_to === 'employee') return `${s} · ${(it.employee_ids || []).length} karyawan`;
  return s;
};

export default function RahazaPayrollAllowancesModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [items, setItems] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(false);
  const [editDialog, setEditDialog] = useState(null);
  const [cakupan, setCakupan] = useState('');
  const [cari, setCari] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        fetch(`${API}/api/rahaza/payroll-allowances`, { headers }),
        fetch(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers }),
      ]);
      const d1 = await r1.json();
      const d2 = await r2.json();
      setItems(d1.allowances || []);
      setEmployees(Array.isArray(d2) ? d2 : d2.items || d2.rows || d2.employees || []);
    } catch (e) {
      toast.error('Gagal memuat data: ' + (e.message || e));
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  /** Mengembalikan pesan galat (string) bila gagal, supaya tampil di kaki form. */
  const handleSave = async (form) => {
    const isEdit = !!form.allowance_id;
    const url = isEdit
      ? `${API}/api/rahaza/payroll-allowances/${form.allowance_id}`
      : `${API}/api/rahaza/payroll-allowances`;
    const r = await fetch(url, { method: isEdit ? 'PUT' : 'POST', headers, body: JSON.stringify(form) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return (typeof d.detail === 'string' && d.detail) || 'Gagal menyimpan tunjangan.';
    toast.success(isEdit ? 'Tunjangan disimpan' : 'Tunjangan ditambahkan');
    setEditDialog(null);
    load();
    return null;
  };

  const handleDelete = async (it) => {
    if (!(await confirmDialog({ title: 'Hapus tunjangan ini?', body: `"${it.name}" — gaji yang sudah final tidak berubah.`, confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(`${API}/api/rahaza/payroll-allowances/${it.allowance_id}`, { method: 'DELETE', headers });
    if (!r.ok) { toast.error('Gagal hapus'); return; }
    toast.success('Tunjangan dihapus');
    load();
  };

  const handleToggleActive = async (item) => {
    const r = await fetch(`${API}/api/rahaza/payroll-allowances/${item.allowance_id}`, {
      method: 'PUT', headers,
      body: JSON.stringify({ ...item, is_active: !item.is_active }),
    });
    if (!r.ok) { toast.error('Gagal mengubah status'); return; }
    load();
  };

  // Tahap 5 (2026-11-07): departemen dari master Struktur Organisasi + departemen yang dipakai karyawan
  // (tunjangan per departemen dicocokkan ke `employee.department`). Dulu hanya dari data karyawan.
  const { units } = useHrMasters(token, { positions: false, shifts: false });
  const departments = useDepartmentFilterOptions(units, employees);

  const opsi = [
    { key: '', label: 'Semua', count: items.length },
    ...Object.entries(SCOPE_CFG).map(([k, s]) => ({ key: k, label: s.label, count: items.filter(i => (i.applicable_to || 'all') === k).length }))
      .filter(o => o.count > 0 || o.key === cakupan),
  ];
  const q = cari.trim().toLowerCase();
  const baris = useMemo(() => items
    .filter(i => !cakupan || (i.applicable_to || 'all') === cakupan)
    .filter(i => !q || `${i.name || ''} ${i.description || ''} ${i.code || ''}`.toLowerCase().includes(q)),
  [items, cakupan, q]);
  const { page, setPage, totalPages, total, paged } = useClientPagination(baris, 10);

  const kolom = [
    { kunci: 'nama', label: 'Tunjangan', hp: 'judul', isi: (it) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="font-medium text-foreground">{it.name}</p>
        {it.description && <p className="hidden truncate text-xs text-muted-foreground md:block" title={it.description}>{it.description}</p>}
      </div>) },
    { kunci: 'jumlah', label: 'Jumlah', rata: 'kanan', isi: (it) => <span className="tabular-nums">{jumlahLabel(it)}</span> },
    { kunci: 'jenis', label: 'Cara hitung', isi: (it) => <span className="text-sm">{CALC_LABEL[it.calc_type] || CALC_LABEL.fixed}</span> },
    { kunci: 'cakupan', label: 'Berlaku untuk', isi: (it) => <span className="text-sm">{cakupanLabel(it)}</span> },
    { kunci: 'aktif', label: 'Aktif', hp: 'aksi', isi: (it) => (
      <Switch checked={!!it.is_active} onCheckedChange={() => handleToggleActive(it)}
        aria-label={it.is_active ? `Nonaktifkan ${it.name}` : `Aktifkan ${it.name}`} title={it.is_active ? 'Aktif — klik untuk menonaktifkan' : 'Nonaktif — klik untuk mengaktifkan'}
        data-testid={`allowance-toggle-${it.allowance_id}`} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => setEditDialog(it)} data-testid={`allowance-edit-${it.allowance_id}`}>
          <Pencil />Ubah
        </Button>
        <Button size="icon-sm" variant="ghost" onClick={() => handleDelete(it)} title="Hapus tunjangan" aria-label="Hapus tunjangan"
          data-testid={`allowance-delete-${it.allowance_id}`}><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="payroll-allowances-page" title="Tunjangan tetap"
      subtitle="Tunjangan yang otomatis ditambahkan ke slip gaji saat proses gaji dibuat."
      actions={<Button onClick={() => setEditDialog({})} data-testid="allowances-add"><Plus />Tambah tunjangan</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari nama tunjangan"
            className="pl-8" data-testid="allowances-search" />
        </div>
        <FilterChips options={opsi} value={cakupan} onChange={setCakupan} testId="allowances-scope" ariaLabel="Berlaku untuk" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="tunjangan-tetap" namaLembar="Tunjangan" baris={baris} testId="allowances-unduh"
          kolom={[
            { label: 'Kode', nilai: (it) => it.code || '' },
            { label: 'Nama tunjangan', nilai: (it) => it.name },
            { label: 'Cara hitung', nilai: (it) => CALC_LABEL[it.calc_type] || CALC_LABEL.fixed },
            { label: 'Jumlah (Rp atau %)', nilai: (it) => Number(it.amount || 0) },
            { label: 'Berlaku untuk', nilai: cakupanLabel },
            { label: 'Aktif', nilai: (it) => (it.is_active ? 'Ya' : 'Tidak') },
            { label: 'Keterangan', nilai: (it) => it.description || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="allowances-refresh"><RefreshCw className={loading ? 'animate-spin' : ''} /></Button>
      </>}
      footer={baris.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
    >
      {loading && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat tunjangan…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} kunci={(it) => it.allowance_id} onKlikBaris={setEditDialog} testId="allowances-table"
          kosong={<EmptyState title={items.length ? 'Tidak ada tunjangan yang cocok' : 'Belum ada tunjangan tetap'}
            description={items.length ? 'Ubah saringan atau kata pencarian.' : 'Tunjangan yang dibuat di sini otomatis ditambahkan ke slip gaji.'}
            action={!items.length && <Button onClick={() => setEditDialog({})}><Plus />Tambah tunjangan</Button>} />} />
      )}

      <AllowanceDialog
        open={editDialog !== null}
        initial={editDialog}
        departments={departments}
        employees={employees}
        onSave={handleSave}
        onClose={() => setEditDialog(null)}
      />
    </PageLayout>
  );
}

const KOSONG = {
  name: '', amount: 0, calc_type: 'fixed', applicable_to: 'all', department: '', employee_ids: [], description: '', is_active: true,
};

function AllowanceDialog({ open, initial, departments, employees, onSave, onClose }) {
  const [form, setForm] = useState(KOSONG);
  const [saving, setSaving] = useState(false);
  const [empSearch, setEmpSearch] = useState('');
  const [galat, setGalat] = useState('');

  useEffect(() => {
    if (!open) return;
    setForm({ ...KOSONG, ...(initial || {}), employee_ids: (initial && initial.employee_ids) || [] });
    setEmpSearch('');
    setGalat('');
  }, [open, initial]);

  const submit = async () => {
    if (!form.name.trim()) { setGalat('Nama tunjangan wajib diisi.'); return; }
    if (form.applicable_to === 'department' && !form.department) { setGalat('Pilih departemen.'); return; }
    if (form.applicable_to === 'employee' && (form.employee_ids || []).length === 0) { setGalat('Pilih minimal 1 karyawan.'); return; }
    setGalat('');
    setSaving(true);
    const pesan = await onSave(form);
    setSaving(false);
    if (pesan) setGalat(pesan);
  };

  const toggleEmp = (id) => {
    setForm(f => ({
      ...f,
      employee_ids: f.employee_ids.includes(id)
        ? f.employee_ids.filter(x => x !== id)
        : [...f.employee_ids, id],
    }));
  };

  const filteredEmps = employees.filter(e =>
    empSearch
      ? (e.name || '').toLowerCase().includes(empSearch.toLowerCase()) ||
        (e.employee_code || '').toLowerCase().includes(empSearch.toLowerCase())
      : true
  );

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" onSimpan={submit} menyimpan={saving} galat={galat}
      judul={form.allowance_id ? 'Ubah tunjangan' : 'Tambah tunjangan'}
      keterangan="Dihitung dan ditambahkan ke slip gaji saat proses gaji dibuat." testId="allowance-form">
      <Isian label="Nama tunjangan" wajib htmlFor="tj-nama">
        <Input id="tj-nama" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          placeholder="Contoh: Tunjangan makan, transport, jabatan" data-testid="allowance-name" />
      </Isian>

      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Cara hitung">
          <SmartNativeSelect value={form.calc_type} onChange={e => setForm(f => ({ ...f, calc_type: e.target.value }))}
            searchable={false} data-testid="allowance-calc-type">
            <option value="fixed">Jumlah tetap (Rp)</option>
            <option value="percentage_gross">% dari gaji bruto</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label={form.calc_type === 'percentage_gross' ? 'Persentase (%)' : 'Jumlah (Rp)'}>
          {/* Kolom yang sama melayani % (persen tetap input angka) dan Rp (MoneyInput, No.45). */}
          {form.calc_type === 'percentage_gross' ? (
            <Input type="number" min={0} step={0.1}
              value={form.amount}
              onChange={e => setForm(f => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
              data-testid="allowance-amount" />
          ) : (
            <MoneyInput
              value={form.amount}
              onChange={e => setForm(f => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
              data-testid="allowance-amount" />
          )}
        </Isian>
      </div>

      <Isian label="Berlaku untuk"
        petunjuk="Semua karyawan untuk tunjangan umum; per departemen atau karyawan tertentu untuk tunjangan khusus (mis. jabatan, insentif supervisor).">
        <SmartNativeSelect value={form.applicable_to} onChange={e => setForm(f => ({ ...f, applicable_to: e.target.value }))}
          searchable={false} data-testid="allowance-scope">
          <option value="all">Semua karyawan</option>
          <option value="department">Per departemen</option>
          <option value="employee">Karyawan tertentu</option>
        </SmartNativeSelect>
      </Isian>

      {form.applicable_to === 'department' && (
        <Isian label="Departemen" wajib>
          <SmartNativeSelect value={form.department || ''} onChange={e => setForm(f => ({ ...f, department: e.target.value }))}
            data-testid="allowance-department">
            <option value="">Pilih departemen</option>
            {departments.map(d => <option key={d.value} value={d.value}>{d.legacy ? d.value : d.label}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}

      {form.applicable_to === 'employee' && (
        <Isian label={`Pilih karyawan (${form.employee_ids.length} dipilih)`} wajib>
          <div className="space-y-2">
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input placeholder="Cari kode atau nama" value={empSearch} onChange={e => setEmpSearch(e.target.value)} className="pl-8" />
            </div>
            <div className="max-h-56 divide-y divide-[var(--glass-border)] overflow-y-auto rounded-[var(--radius-md)] border border-[var(--glass-border)]">
              {filteredEmps.map(e => (
                <label key={e.id} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-foreground/5">
                  <Checkbox checked={form.employee_ids.includes(e.id)} onCheckedChange={() => toggleEmp(e.id)} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-foreground">{e.name}</span>
                    <span className="block text-xs text-muted-foreground">{e.employee_code} · {e.department || '—'}</span>
                  </span>
                </label>
              ))}
              {filteredEmps.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">Tidak ada karyawan yang cocok.</p>}
            </div>
          </div>
        </Isian>
      )}

      <Isian label="Keterangan (opsional)">
        <Textarea value={form.description || ''} rows={2}
          onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          placeholder="Keterangan tambahan" />
      </Isian>

      <label className="flex items-center gap-3 text-sm">
        <Switch checked={!!form.is_active} onCheckedChange={v => setForm(f => ({ ...f, is_active: v }))} />
        <span>Aktif — ikut dihitung di proses gaji</span>
      </label>
    </FormPopup>
  );
}
