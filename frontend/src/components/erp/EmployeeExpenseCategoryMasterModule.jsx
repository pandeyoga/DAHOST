/**
 * EmployeeExpenseCategoryMasterModule — Master Kategori Expense (EEM)
 * CV. Dewi Aditya — EEM Phase 5D
 *
 * CRUD master data kategori expense yang bisa dikelola Admin/Finance.
 * Backend: /api/hr/expenses/master-categories + /seed-default
 * Roles: superadmin, admin, owner, finance
 *
 * 2026-11-05 (PANDUAN_UI G1/G5/G10): cetakan PageLayout — tanpa pembungkus `p-4` sendiri (pita kosong di bawah
 * tab hub), satu kartu tabel (dulu dua Card shadcn: kartu penyaring + kartu tabel), tampilan kosong EmptyState.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { FINANCE_ROLES as ADMIN_ROLES } from '../../lib/financeRoles'; // FIN-02
import {
  Plus, Pencil, Trash2, RefreshCw, Tag,
  Search, Database, Loader2
} from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { EmptyState, StatusBadge } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL || import.meta?.env?.REACT_APP_BACKEND_URL;


function getToken() {
  return localStorage.getItem('erp_token');
}

function getUserRole() {
  try {
    const raw = localStorage.getItem('erp_user');
    if (!raw) return null;
    const u = JSON.parse(raw);
    return u?.role || null;
  } catch {
    return null;
  }
}

// ── Category Form Dialog ─────────────────────────────────────────────────────
function CategoryFormDialog({ open, onClose, category, onSaved }) {
  const [form, setForm] = useState({ name: '', code: '', description: '', is_active: true });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      if (category) {
        setForm({
          name: category.name || '',
          code: category.code || '',
          description: category.description || '',
          is_active: category.is_active !== false,
        });
      } else {
        setForm({ name: '', code: '', description: '', is_active: true });
      }
      setError('');
    }
  }, [open, category]);

  const handleSave = async () => {
    if (!form.name.trim()) {
      setError('Nama kategori wajib diisi.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const token = getToken();
      const url = category
        ? `${API}/api/hr/expenses/master-categories/${category.id}`
        : `${API}/api/hr/expenses/master-categories`;
      const method = category ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Gagal menyimpan');
      toast.success(category ? 'Kategori berhasil diperbarui.' : 'Kategori berhasil ditambahkan.');
      onSaved(data);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="category-form"
      judul={category ? 'Ubah kategori' : 'Kategori baru'}
      keterangan={category ? 'Perbarui data kategori klaim.' : 'Tambahkan kategori klaim biaya baru.'}
      onSimpan={handleSave} menyimpan={saving} galat={error}
      labelSimpan={category ? 'Simpan perubahan' : 'Tambah kategori'}>
      <Isian label="Nama kategori" wajib htmlFor="cat-name">
        <Input id="cat-name" data-testid="category-name-input" placeholder="mis. Biaya Training, Sewa Kendaraan"
          value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} />
      </Isian>
      <Isian label="Kode kategori" htmlFor="cat-code" petunjuk="Opsional.">
        <Input id="cat-code" data-testid="category-code-input" placeholder="mis. CAT-014"
          value={form.code} onChange={e => setForm(p => ({ ...p, code: e.target.value }))} />
      </Isian>
      <Isian label="Deskripsi" htmlFor="cat-desc" petunjuk="Opsional.">
        <Input id="cat-desc" data-testid="category-description-input" placeholder="Penjelasan singkat kategori ini"
          value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
      </Isian>
      <label className="flex items-center justify-between gap-3 text-sm" htmlFor="cat-active">
        <span>
          <span className="font-medium">Aktif</span>
          <span className="block text-xs text-muted-foreground">Kategori nonaktif tidak muncul di pilihan klaim.</span>
        </span>
        <Switch id="cat-active" data-testid="category-active-switch" checked={form.is_active}
          onCheckedChange={v => setForm(p => ({ ...p, is_active: v }))} />
      </label>
    </FormPopup>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function EmployeeExpenseCategoryMasterModule() {
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [search, setSearch] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingCat, setEditingCat] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const userRole = getUserRole();
  const canEdit = ADMIN_ROLES.includes(userRole);

  const fetchCategories = useCallback(async () => {
    setLoading(true);
    try {
      const token = getToken();
      const url = `${API}/api/hr/expenses/master-categories?include_inactive=${showInactive}`;
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = await res.json();
        setCategories(data.items || []);
      } else {
        toast.error('Gagal memuat master kategori');
      }
    } catch (err) {
      toast.error('Koneksi bermasalah');
    } finally {
      setLoading(false);
    }
  }, [showInactive]);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  const handleSeedDefault = async () => {
    setSeeding(true);
    try {
      const token = getToken();
      const res = await fetch(`${API}/api/hr/expenses/master-categories/seed-default`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        toast.success(`${data.message}`);
        await fetchCategories();
      } else {
        toast.error(data.detail || 'Gagal mengisi kategori bawaan');
      }
    } catch (err) {
      toast.error('Koneksi bermasalah');
    } finally {
      setSeeding(false);
    }
  };

  const handleOpenCreate = () => {
    setEditingCat(null);
    setDialogOpen(true);
  };

  const handleOpenEdit = (cat) => {
    setEditingCat(cat);
    setDialogOpen(true);
  };

  const handleDeactivate = async () => {
    if (!deleteTarget) return;
    try {
      const token = getToken();
      const res = await fetch(`${API}/api/hr/expenses/master-categories/${deleteTarget.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        toast.success(data.message);
        await fetchCategories();
      } else {
        toast.error(data.detail || 'Gagal menonaktifkan kategori');
      }
    } catch (err) {
      toast.error('Koneksi bermasalah');
    } finally {
      setDeleteTarget(null);
    }
  };

  const filtered = categories.filter(c =>
    c.name?.toLowerCase().includes(search.toLowerCase()) ||
    c.code?.toLowerCase().includes(search.toLowerCase()) ||
    c.description?.toLowerCase().includes(search.toLowerCase())
  );

  const activeCount = categories.filter(c => c.is_active !== false).length;
  const seedButton = (variant, testId = 'category-seed-button') => (
    <Button
      variant={variant}
      data-testid={testId}
      onClick={handleSeedDefault}
      disabled={seeding}
    >
      {seeding ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
      Isi kategori bawaan
    </Button>
  );

  return (
    <PageLayout
      testId="expense-category-master"
      title="Kategori klaim biaya"
      subtitle="Daftar kategori untuk klaim biaya karyawan."
      actions={canEdit && <>
        {seedButton('outline')}
        <Button data-testid="category-create-button" onClick={handleOpenCreate}>
          <Plus size={14} />
          Tambah kategori
        </Button>
      </>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <GlassInput
            data-testid="category-search-input"
            placeholder="Cari nama atau kode kategori…"
            aria-label="Cari"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="h-9 pl-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="show-inactive"
            checked={showInactive}
            onCheckedChange={setShowInactive}
            data-testid="category-show-inactive-switch"
          />
          <Label htmlFor="show-inactive" className="text-sm cursor-pointer">
            Tampilkan nonaktif
          </Label>
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="kategori-klaim-biaya" namaLembar="Kategori klaim" baris={filtered} testId="category-unduh"
          kolom={[
            { label: 'Kode', nilai: (c) => c.code || '' },
            { label: 'Nama kategori', nilai: (c) => c.name },
            { label: 'Deskripsi', nilai: (c) => c.description || '' },
            { label: 'Status', nilai: (c) => (c.is_active === false ? 'Nonaktif' : 'Aktif') },
          ]} />
        <Button
          variant="outline"
          size="icon"
          title="Muat ulang"
          aria-label="Muat ulang"
          data-testid="category-refresh-button"
          onClick={fetchCategories}
          disabled={loading}
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={!loading && categories.length > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="category-summary">
          {activeCount} aktif dari {categories.length} kategori
          {search && <> · {filtered.length} cocok dengan pencarian</>}
        </p>
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-32 gap-3 text-muted-foreground">
            <Loader2 size={20} className="animate-spin" />
            <span className="text-sm">Memuat data…</span>
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={Tag} testId="category-empty"
            title={search ? 'Tidak ada kategori yang cocok' : 'Belum ada kategori'}
            description={search ? 'Ubah atau kosongkan pencarian.' : 'Isi kategori bawaan untuk memulai, atau tambahkan kategori sendiri.'}
            action={canEdit && !search ? seedButton('default', 'category-seed-empty-button') : null} />
        ) : (
          <Table className="md:min-w-0">
            <TableHeader>
              <TableRow>
                <TableHead className="w-24">Kode</TableHead>
                <TableHead>Nama kategori</TableHead>
                <TableHead className="hidden md:table-cell">Deskripsi</TableHead>
                <TableHead className="w-24">Status</TableHead>
                {canEdit && (
                  <TableHead className="w-24 text-right">Aksi</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(cat => (
                <TableRow
                  key={cat.id}
                  className="hover:bg-[hsl(var(--muted)/0.35)] transition-colors"
                  data-testid={`category-row-${cat.id}`}
                >
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {cat.code || '—'}
                  </TableCell>
                  <TableCell className="font-medium text-sm">
                    {cat.name}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground hidden md:table-cell max-w-xs truncate">
                    {cat.description || '—'}
                  </TableCell>
                  <TableCell>
                    {cat.is_active !== false
                      ? <StatusBadge status="active" label="Aktif" tone="success" />
                      : <StatusBadge status="inactive" label="Nonaktif" tone="muted" />}
                  </TableCell>
                  {canEdit && (
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Ubah"
                          aria-label="Ubah"
                          data-testid={`category-edit-${cat.id}`}
                          onClick={() => handleOpenEdit(cat)}
                        >
                          <Pencil size={13} />
                        </Button>
                        {cat.is_active !== false && (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            title="Nonaktifkan"
                            aria-label="Nonaktifkan"
                            className="text-destructive hover:text-destructive"
                            data-testid={`category-delete-${cat.id}`}
                            onClick={() => setDeleteTarget(cat)}
                          >
                            <Trash2 size={13} />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      {/* Form Dialog */}
      <CategoryFormDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        category={editingCat}
        onSaved={() => fetchCategories()}
      />

      {/* Deactivate Confirm Dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={v => !v && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Nonaktifkan kategori?</AlertDialogTitle>
            <AlertDialogDescription>
              Kategori <strong>{deleteTarget?.name}</strong> akan dinonaktifkan dan tidak akan muncul di pilihan klaim baru.
              Data klaim yang sudah ada tidak terpengaruh. Kategori dapat diaktifkan kembali kapan saja.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Batal</AlertDialogCancel>
            <AlertDialogAction
              data-testid="category-deactivate-confirm"
              onClick={handleDeactivate}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Nonaktifkan
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageLayout>
  );
}
