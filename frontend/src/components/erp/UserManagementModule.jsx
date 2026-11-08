/**
 * Pengguna (Kontrol Akses › tab Pengguna).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di hub judul disembunyikan, tombol pindah ke baris tab),
 * penyaring satu baris, tabel (kartu ringkas di HP), nama peran manusiawi (dulu kode `admin_gudang` + deret pil
 * semua peran), form tambah/ubah & hubungkan karyawan = FormPopup, hapus lewat confirmDialog, aksi baris:
 * Ubah + "Lainnya". Logika simpan/izin tidak berubah.
 * Perbaikan pemilih karyawan: dulu hanya memuat 50 karyawan pertama (bawaan API) → kini `limit=500`.
 */
import { useState, useEffect, useMemo } from 'react';
import { toast } from 'sonner';
import { Link as LinkIcon, MoreHorizontal, Pencil, Plus, Search, Trash2, UserCheck, UserX } from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import ImportExportToolbar from './ImportExportToolbar';
import { labelKodePeran, labelPeran, peranTidakDitawarkan } from './akses/labelPeran';

// Peran bawaan berizin tetap (backend `auth.FIXED_ROLE_PERMS`) — tidak ada di master Peran.
// 2026-11-07 (Tahap 5): `cmt_vendor` dulu tidak ada di daftar, sehingga 12 akun vendor CMT
// tampil sebagai "admin" saat diubah. Peran lain diambil dari master Peran (/api/roles).
const SYSTEM_ROLES = ['superadmin', 'admin', 'vendor', 'cmt_vendor', 'buyer'];
const SYSTEM_ROLE_LABEL = {
  superadmin: 'Super admin', admin: 'Admin', vendor: 'Vendor garmen (lama)',
  cmt_vendor: 'Vendor CMT', buyer: 'Buyer',
};
const API = process.env.REACT_APP_BACKEND_URL;
const instan = (ts) => (typeof ts === 'string' && /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(ts) ? `${ts}Z` : ts);

export default function UserManagementModule({ token }) {
  const [users, setUsers] = useState([]);
  const [customRoles, setCustomRoles] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [buyersList, setBuyersList] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editData, setEditData] = useState(null);
  const [saving, setSaving] = useState(false);
  // 2026-11-07 (Tahap 6, SY3): tanpa peran bawaan — dulu 'admin' terpilih otomatis. Peran wajib dipilih.
  // Tahap 8 fase 3: cv_access '' = kedua CV (bawaan), 'DA' / 'SMU' = hanya CV itu di Portal Keuangan
  const EMPTY_FORM = { name: '', email: '', password: '', role: '', status: 'active', vendor_id: '', buyer_id: '', customer_name: '', cv_access: '' };
  const [form, setForm] = useState(EMPTY_FORM);
  const [showLinkModal, setShowLinkModal] = useState(null); // user to link
  const [linkEmployeeId, setLinkEmployeeId] = useState('');
  const [linkLoading, setLinkLoading] = useState(false);
  const [cari, setCari] = useState('');
  const [saringPeran, setSaringPeran] = useState('');
  const [saringStatus, setSaringStatus] = useState('');

  const headers = { Authorization: `Bearer ${token}` };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchUsers(); fetchRoles(); fetchVendors(); fetchBuyers(); fetchEmployees(); }, []);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/users', { headers });
      const data = await res.json();
      setUsers(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const fetchRoles = async () => {
    try {
      const res = await fetch('/api/roles', { headers });
      const data = await res.json();
      setCustomRoles(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
  };

  const fetchVendors = async () => {
    try {
      const res = await fetch('/api/garments', { headers });
      const data = await res.json();
      setVendors(Array.isArray(data) ? data.filter(v => v.status === 'active') : []);
    } catch (e) { console.error(e); }
  };

  const fetchBuyers = async () => {
    try {
      const res = await fetch('/api/buyers', { headers });
      const data = await res.json();
      setBuyersList(Array.isArray(data) ? data.filter(b => b.status === 'active') : []);
    } catch (e) { console.error(e); }
  };

  const fetchEmployees = async () => {
    try {
      // Bawaan API hanya 50 baris → karyawan ke-51 dst. tidak bisa dipilih. Ambil sampai batas API (500).
      const { data } = await axios.get(`${API}/api/rahaza/employees?limit=500`, { headers });
      setEmployees(Array.isArray(data) ? data : (data.items || data.rows || []));
    } catch (e) { console.error(e); }
  };

  const handleLinkEmployee = async () => {
    if (!showLinkModal) return;
    setLinkLoading(true);
    try {
      await axios.put(`${API}/api/rahaza/self/admin/link-employee`, {
        user_id: showLinkModal.id,
        employee_id: linkEmployeeId || null,
      }, { headers });
      toast.success(linkEmployeeId ? 'Akun dihubungkan ke karyawan.' : 'Hubungan ke karyawan dilepas.');
      setShowLinkModal(null);
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menghubungkan.');
    } finally { setLinkLoading(false); }
  };

  // Peran dari master (tanpa nama yang sama dengan peran bawaan), urut nama.
  const masterRoles = customRoles
    .filter(r => r && r.name && !SYSTEM_ROLES.includes(r.name))
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  // Pilihan di formulir: tanpa peran bawaan yang belum diatur & tidak dipakai (keputusan owner 8 Nov 2026),
  // kecuali peran yang sedang terpasang pada akun yang diubah.
  const pilihanPeran = masterRoles.filter(r => !peranTidakDitawarkan(r) || r.name === form.role);
  const knownRole = (name) => SYSTEM_ROLES.includes(name) || masterRoles.some(r => r.name === name);
  const roleLabel = (r) => (r.display_name || r.label || labelPeran(r.name, r.description));
  const namaPeran = (kode) => {
    if (SYSTEM_ROLE_LABEL[kode]) return SYSTEM_ROLE_LABEL[kode];
    const r = masterRoles.find((x) => x.name === kode);
    return r ? roleLabel(r) : labelKodePeran(kode);
  };

  const openCreate = () => {
    setEditData(null);
    setForm(EMPTY_FORM);
    setShowModal(true);
  };

  const openEdit = (row) => {
    setEditData(row);
    setForm({ name: row.name, email: row.email, password: '', role: row.role, status: row.status,
              vendor_id: row.vendor_id || '', buyer_id: row.buyer_id || '', customer_name: row.customer_name || '',
              cv_access: Array.isArray(row.allowed_entities) && row.allowed_entities.length === 1 ? row.allowed_entities[0] : '' });
    setShowModal(true);
  };

  // 2026-11-06 (pola P6): jawaban server diperiksa; bila ditolak pesan server ditampilkan.
  const okOrToast = async (r, fallback) => {
    if (r.ok) return true;
    const d = await r.json().catch(() => ({}));
    toast.error(typeof d.detail === 'string' ? d.detail : fallback);
    return false;
  };

  const handleSubmit = async () => {
    if (!String(form.name || '').trim() || !String(form.email || '').trim()) { toast.error('Nama dan email wajib diisi'); return; }
    if (!String(form.role || '').trim()) { toast.error('Peran wajib dipilih'); return; }
    const { cv_access: cvAccess, ...payload } = form;
    if (editData && !payload.password) delete payload.password;
    if (editData) payload.allowed_entities = cvAccess ? [cvAccess] : null;
    // Set customer_name from buyer if buyer role
    if (payload.role === 'buyer' && payload.buyer_id) {
      const buyer = buyersList.find(b => b.id === payload.buyer_id);
      if (buyer) payload.customer_name = buyer.buyer_name;
    }
    const url = editData ? `/api/users/${editData.id}` : '/api/users';
    const method = editData ? 'PUT' : 'POST';
    setSaving(true);
    try {
      const r = await fetch(url, {
        method, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload)
      });
      // 2026-11-06 (pola P6): dulu popup langsung ditutup walau server menolak (email dobel, tidak berhak)
      if (!(await okOrToast(r, 'Gagal menyimpan pengguna'))) return;
      toast.success(editData ? 'Pengguna disimpan.' : 'Pengguna ditambahkan.');
      setShowModal(false);
      fetchUsers();
    } finally { setSaving(false); }
  };

  const toggleStatus = async (row) => {
    const newStatus = row.status === 'active' ? 'inactive' : 'active';
    const r = await fetch(`/api/users/${row.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ status: newStatus })
    });
    if (await okOrToast(r, 'Gagal mengubah status pengguna')) {
      toast.success(newStatus === 'active' ? 'Pengguna diaktifkan.' : 'Pengguna dinonaktifkan.');
    }
    fetchUsers();
  };

  const handleDelete = async (row) => {
    const ok = await confirmDialog({
      title: 'Hapus pengguna?',
      body: `Pengguna "${row.name}" (${row.email}) akan dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    const r = await fetch(`/api/users/${row.id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
    if (!(await okOrToast(r, 'Gagal menghapus pengguna'))) return;
    toast.success('Pengguna dihapus.');
    fetchUsers();
  };

  const namaVendor = (id) => vendors.find((v) => v.id === id)?.garment_name;
  const namaKaryawan = (id) => employees.find((e) => e.id === id)?.name;
  const tautan = (row) => {
    if (row.role === 'vendor' && row.vendor_id) return `Vendor: ${namaVendor(row.vendor_id) || 'tertaut'}`;
    if (row.role === 'buyer' && row.buyer_id) return `Buyer: ${row.customer_name || 'tertaut'}`;
    if (row.employee_id) return `Karyawan: ${namaKaryawan(row.employee_id) || 'tertaut'}`;
    return '';
  };

  const q = cari.trim().toLowerCase();
  const tampil = useMemo(() => users
    .filter((u) => !saringPeran || u.role === saringPeran)
    .filter((u) => !saringStatus || (u.status === 'active' ? 'active' : 'inactive') === saringStatus)
    .filter((u) => !q || `${u.name} ${u.email} ${u.role} ${namaPeran(u.role)}`.toLowerCase().includes(q)),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [users, saringPeran, saringStatus, q, customRoles]);
  const perPeran = useMemo(() => [...new Set(users.map((u) => u.role).filter(Boolean))]
    .sort((a, b) => namaPeran(a).localeCompare(namaPeran(b), 'id')),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [users, customRoles]);
  const nAktif = users.filter((u) => u.status === 'active').length;

  const columns = [
    { kunci: 'name', label: 'Nama & email', hp: 'judul', isi: (row) => (
      <div className="min-w-0 md:max-w-[18rem]">
        <p className="font-medium text-foreground">{row.name}</p>
        <p className="break-all text-xs text-muted-foreground">{row.email}</p>
      </div>) },
    { kunci: 'role', label: 'Peran', isi: (row) => <span className="text-sm">{namaPeran(row.role)}</span> },
    { kunci: 'link', label: 'Tautan', isi: (row) => <span className="text-sm text-muted-foreground md:max-w-[14rem] md:inline-block">{tautan(row) || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (row) => (
      <StatusBadge status={row.status} label={row.status === 'active' ? 'Aktif' : 'Nonaktif'} tone={row.status === 'active' ? 'success' : 'muted'} />) },
    { kunci: 'created_at', label: 'Dibuat', isi: (row) => <span className="whitespace-nowrap text-sm">{formatDateID(instan(row.created_at))}</span> },
    { kunci: 'actions', label: '', rata: 'kanan', hp: 'aksi', isi: (row) => (
      row.role !== 'superadmin' ? (
        <div className="flex items-center justify-end gap-1">
          <Button size="sm" variant="outline" onClick={() => openEdit(row)} data-testid={`user-edit-${row.id}`}><Pencil />Ubah</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label="Lainnya" data-testid={`user-more-${row.id}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => toggleStatus(row)}>
                {row.status === 'active' ? <UserX className="mr-2 h-4 w-4" /> : <UserCheck className="mr-2 h-4 w-4" />}
                {row.status === 'active' ? 'Nonaktifkan' : 'Aktifkan'}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => { setShowLinkModal(row); setLinkEmployeeId(row.employee_id || ''); }}>
                <LinkIcon className="mr-2 h-4 w-4" />{row.employee_id ? 'Ubah hubungan karyawan' : 'Hubungkan ke karyawan'}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => handleDelete(row)} className="text-[hsl(var(--danger-text))]">
                <Trash2 className="mr-2 h-4 w-4" />Hapus
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ) : <span className="text-xs text-muted-foreground">Dilindungi</span>
    ) },
  ];

  const catatan = form.role === 'vendor' ? 'Akun vendor biasanya dibuat otomatis dari Data Vendor/Garmen.'
    : form.role === 'buyer' ? 'Akun buyer biasanya dibuat otomatis dari Data Buyer.'
      : form.role === 'cmt_vendor' ? 'Akun vendor CMT sebaiknya dibuat dari menu Vendor CMT supaya tertaut ke vendornya.'
        : !editData ? 'Password kosong = password bawaan User@123 — minta pengguna menggantinya setelah masuk.'
          : 'Kosongkan password bila tidak diubah.';

  return (
    <PageLayout testId="user-management-module" title="Pengguna"
      subtitle="Kelola akun pengguna, perannya, dan tautan ke karyawan/vendor."
      actions={<Button onClick={openCreate} data-testid="add-user-btn"><Plus />Tambah pengguna</Button>}
      filters={<>
        <FilterChips className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" value={saringStatus} onChange={setSaringStatus} hideWhenEmpty={false} testId="user-status-filter" options={[
          { key: '', label: 'Semua', count: users.length },
          { key: 'active', label: 'Aktif', count: nAktif },
          { key: 'inactive', label: 'Nonaktif', count: users.length - nAktif },
        ]} />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari nama, email, peran" className="pl-8"
            data-testid="user-search" />
        </div>
        <SmartNativeSelect value={saringPeran} onChange={(e) => setSaringPeran(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-52"
          aria-label="Peran" data-testid="user-role-filter">
          <option value="">Semua peran</option>
          {perPeran.map((r) => <option key={r} value={r}>{namaPeran(r)}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<ImportExportToolbar collectionKey="users" label="Pengguna Sistem" onImported={fetchUsers} />}>
      {loading && users.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat pengguna…</p>
      ) : (
        <TabelData kolom={columns} baris={tampil} testId="user-table"
          kosong={<EmptyState title={users.length ? 'Tidak ada pengguna yang cocok' : 'Belum ada pengguna'}
            description={users.length ? 'Ubah saringan atau kata pencarian.' : 'Tambahkan pengguna pertama.'} />} />
      )}

      <FormPopup open={showModal} onClose={() => setShowModal(false)} ukuran="pendek" testId="user-form"
        judul={editData ? 'Ubah pengguna' : 'Tambah pengguna'} menyimpan={saving} onSimpan={handleSubmit}
        labelSimpan={editData ? 'Simpan perubahan' : 'Tambah pengguna'}>
        <Isian label="Nama lengkap" wajib htmlFor="user-name">
          <Input id="user-name" required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="user-name" />
        </Isian>
        <Isian label="Email" wajib htmlFor="user-email">
          <Input id="user-email" required type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} data-testid="user-email" />
        </Isian>
        <Isian label="Password" htmlFor="user-password" petunjuk={editData ? 'Kosongkan jika tidak diubah.' : 'Minimal 6 karakter.'}>
          <Input id="user-password" type="password" autoComplete="new-password" value={form.password}
            onChange={e => setForm({ ...form, password: e.target.value })} placeholder={editData ? '••••••••' : 'Minimal 6 karakter'} />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Peran" wajib htmlFor="user-role">
            <SmartNativeSelect id="user-role" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} data-testid="user-role">
              <option value="">— Pilih peran —</option>
              {form.role && !knownRole(form.role) && (
                <option value={form.role}>{`${labelKodePeran(form.role)} (tidak ada di master Peran)`}</option>
              )}
              <optgroup label="Peran bawaan">
                {SYSTEM_ROLES.map(r => <option key={r} value={r}>{SYSTEM_ROLE_LABEL[r] || r}</option>)}
              </optgroup>
              {pilihanPeran.length > 0 && (
                <optgroup label="Master Peran">
                  {pilihanPeran.map(r => <option key={r.name} value={r.name}>{roleLabel(r)}</option>)}
                </optgroup>
              )}
            </SmartNativeSelect>
          </Isian>
          {/* Akun baru selalu aktif (server) — status hanya bisa diubah saat mengedit. */}
          {editData && (
            <Isian label="Status" htmlFor="user-status">
              <SmartNativeSelect id="user-status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} data-testid="user-status">
                <option value="active">Aktif</option>
                <option value="inactive">Nonaktif</option>
              </SmartNativeSelect>
            </Isian>
          )}
          {editData && (
            <Isian label="Akses CV keuangan" htmlFor="user-cv-access">
              <SmartNativeSelect id="user-cv-access" value={form.cv_access} onChange={e => setForm({ ...form, cv_access: e.target.value })} data-testid="user-cv-access">
                <option value="">Kedua CV (bawaan)</option>
                <option value="DA">Hanya CV Dewi Aditya</option>
                <option value="SMU">Hanya CV Sukma</option>
              </SmartNativeSelect>
            </Isian>
          )}
        </div>

        {/* Vendor link for vendor role */}
        {form.role === 'vendor' && (
          <Isian label="Tautkan ke vendor" htmlFor="user-vendor">
            <SmartNativeSelect id="user-vendor" value={form.vendor_id} onChange={e => setForm({ ...form, vendor_id: e.target.value })}>
              <option value="">— Pilih vendor —</option>
              {vendors.map(v => <option key={v.id} value={v.id}>{`${v.garment_name} (${v.garment_code})`}</option>)}
            </SmartNativeSelect>
          </Isian>
        )}

        {/* Buyer link for buyer role */}
        {form.role === 'buyer' && (
          <Isian label="Tautkan ke buyer" htmlFor="user-buyer">
            <SmartNativeSelect id="user-buyer" value={form.buyer_id} onChange={e => {
              const buyer = buyersList.find(b => b.id === e.target.value);
              setForm({ ...form, buyer_id: e.target.value, customer_name: buyer?.buyer_name || '' });
            }}>
              <option value="">— Pilih buyer —</option>
              {buyersList.map(b => <option key={b.id} value={b.id}>{`${b.buyer_name} (${b.buyer_code})`}</option>)}
            </SmartNativeSelect>
          </Isian>
        )}

        <Notice tone="info">{catatan}</Notice>
      </FormPopup>

      <FormPopup open={!!showLinkModal} onClose={() => setShowLinkModal(null)} ukuran="pendek" testId="user-link-form"
        judul="Hubungkan ke karyawan" keterangan={showLinkModal ? `Pengguna: ${showLinkModal.name}` : undefined}
        menyimpan={linkLoading} onSimpan={handleLinkEmployee}>
        <Isian label="Karyawan" htmlFor="user-link-employee" petunjuk="Pilih “Tidak terhubung” untuk melepas hubungan.">
          <SmartNativeSelect id="user-link-employee" value={linkEmployeeId} onChange={e => setLinkEmployeeId(e.target.value)}>
            <option value="">— Tidak terhubung —</option>
            {employees.map(emp => (
              <option key={emp.id} value={emp.id}>
                {`${emp.employee_code} — ${emp.name}${emp.job_title ? ` (${emp.job_title})` : ''}`}
              </option>
            ))}
          </SmartNativeSelect>
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}
