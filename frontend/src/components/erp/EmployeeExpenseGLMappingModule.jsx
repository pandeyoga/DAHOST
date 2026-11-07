import React, { useState, useEffect } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Plus, Pencil, Trash2, ListTree } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Switch } from '@/components/ui/switch';
import { StatusBadge, EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { toast } from 'sonner';

const BACKEND_URL = import.meta.env.REACT_APP_BACKEND_URL || process.env.REACT_APP_BACKEND_URL;

/**
 * Akun klaim biaya karyawan (Pengaturan Keuangan › Pemetaan akun otomatis; juga menu "GL Mapping").
 * 2026-11-05 (PANDUAN_UI G1/G5/G11): cetakan PageLayout, satu jenis kartu (GlassCard), label Indonesia
 * (dulu "GL Mapping Configuration", "Active/Inactive", judul 30 px buatan sendiri).
 */
export default function EmployeeExpenseGLMappingModule() {
  const [mappings, setMappings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDialog, setShowDialog] = useState(false);
  const [editingMapping, setEditingMapping] = useState(null);
  const [coaAccounts, setCoaAccounts] = useState([]);

  const [formData, setFormData] = useState({
    category: '',
    gl_account_code: '',
    gl_account_name: '',
    is_active: true,
  });

  useEffect(() => {
    fetchMappings();
    fetchCOA();
  }, []);

  const fetchMappings = async () => {
    try {
      const token = localStorage.getItem('erp_token');
      const res = await fetch(`${BACKEND_URL}/api/hr/expenses/gl-mappings`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setMappings(data.items || []);
      }
    } catch (err) {
      console.error('Fetch mappings error:', err);
      toast.error('Gagal memuat pemetaan akun klaim');
    } finally {
      setLoading(false);
    }
  };

  const fetchCOA = async () => {
    try {
      const token = localStorage.getItem('erp_token');
      // FASE 20 — dulu '/api/finance/coa' (tidak pernah ada ⇒ 404 senyap, dropdown
      // akun GL selalu kosong sehingga mapping tak bisa dibuat). SSOT COA ada di
      // '/api/rahaza/coa/accounts' dan membalas ARRAY polos (bukan {items}).
      const res = await fetch(`${BACKEND_URL}/api/rahaza/coa/accounts`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setCoaAccounts(Array.isArray(data) ? data : data.items || []);
      }
    } catch (err) {
      console.error('Fetch COA error:', err);
    }
  };

  const handleCreate = () => {
    setEditingMapping(null);
    setFormData({ category: '', gl_account_code: '', gl_account_name: '', is_active: true });
    setShowDialog(true);
  };

  const handleEdit = (mapping) => {
    setEditingMapping(mapping);
    setFormData({
      category: mapping.category,
      gl_account_code: mapping.gl_account_code,
      gl_account_name: mapping.gl_account_name,
      is_active: mapping.is_active,
    });
    setShowDialog(true);
  };

  const handleSave = async () => {
    if (!formData.category || !formData.gl_account_code || !formData.gl_account_name) {
      toast.error('Semua isian wajib diisi');
      return;
    }

    try {
      const token = localStorage.getItem('erp_token');
      const url = editingMapping
        ? `${BACKEND_URL}/api/hr/expenses/gl-mappings/${editingMapping.id}`
        : `${BACKEND_URL}/api/hr/expenses/gl-mappings`;

      const method = editingMapping ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method,
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });

      const data = await res.json();

      if (res.ok) {
        toast.success(editingMapping ? 'Pemetaan akun diperbarui' : 'Pemetaan akun dibuat');
        setShowDialog(false);
        fetchMappings();
      } else {
        toast.error(data.detail || 'Gagal menyimpan pemetaan akun');
      }
    } catch (err) {
      console.error('Save mapping error:', err);
      toast.error('Terjadi kesalahan saat menyimpan');
    }
  };

  const handleDelete = async (mapping) => {
    if (!(await confirmDialog({ title: `Hapus pemetaan ${mapping.category}?`, confirmLabel: 'Hapus', danger: true }))) return;

    try {
      const token = localStorage.getItem('erp_token');
      const res = await fetch(`${BACKEND_URL}/api/hr/expenses/gl-mappings/${mapping.id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (res.ok) {
        toast.success('Pemetaan akun dihapus');
        fetchMappings();
      } else {
        const data = await res.json();
        toast.error(data.detail || 'Gagal menghapus pemetaan akun');
      }
    } catch (err) {
      console.error('Delete mapping error:', err);
      toast.error('Terjadi kesalahan saat menghapus');
    }
  };

  const handleAccountSelect = (code) => {
    const account = coaAccounts.find(a => a.code === code);
    if (account) {
      setFormData(prev => ({
        ...prev,
        gl_account_code: code,
        gl_account_name: account.name,
      }));
    }
  };

  return (
    <PageLayout
      testId="gl-mapping-admin-page"
      title="Akun klaim biaya karyawan"
      subtitle="Kategori klaim karyawan dan akun beban yang dipakai jurnal saat penyelesaian."
      actions={
        <Button onClick={handleCreate} data-testid="create-mapping-btn">
          <Plus className="h-4 w-4" />
          Pemetaan baru
        </Button>
      }
      tools={
        <TombolUnduh namaBerkas="akun-klaim-biaya-karyawan" namaLembar="Akun klaim" baris={mappings} testId="mapping-unduh"
          kolom={[
            { label: 'Kategori klaim', nilai: (m) => m.category },
            { label: 'Kode akun', nilai: (m) => m.gl_account_code },
            { label: 'Nama akun', nilai: (m) => m.gl_account_name || '' },
            { label: 'Status', nilai: (m) => (m.is_active === false ? 'Nonaktif' : 'Aktif') },
          ]} />
      }
      summary={!loading && (
        <p className="text-sm text-muted-foreground">
          {mappings.length} pemetaan · kategori tanpa pemetaan memakai akun <b className="text-foreground">6-3400 Biaya Perjalanan Dinas</b>.
        </p>
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : mappings.length === 0 ? (
          <EmptyState icon={ListTree} title="Belum ada pemetaan akun klaim"
            description="Tambahkan pemetaan supaya tiap kategori klaim masuk ke akun bebannya sendiri." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kategori klaim</TableHead>
                <TableHead>Kode akun</TableHead>
                <TableHead>Nama akun</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mappings.map((mapping) => (
                <TableRow key={mapping.id} data-testid={`mapping-row-${mapping.id}`}>
                  <TableCell className="font-medium">{mapping.category}</TableCell>
                  <TableCell className="whitespace-nowrap">{mapping.gl_account_code}</TableCell>
                  <TableCell className="text-muted-foreground">{mapping.gl_account_name}</TableCell>
                  <TableCell>
                    <StatusBadge tone={mapping.is_active ? 'success' : 'muted'} label={mapping.is_active ? 'Aktif' : 'Nonaktif'} />
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleEdit(mapping)}
                        title="Ubah" aria-label="Ubah"
                        data-testid={`edit-mapping-${mapping.id}`}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleDelete(mapping)}
                        title="Hapus" aria-label="Hapus"
                        className="text-destructive"
                        data-testid={`delete-mapping-${mapping.id}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      {/* Formulir isian pendek — popup form standar (2026-11-08, Standar UI/UX v2) */}
      <FormPopup open={showDialog} onClose={() => setShowDialog(false)} ukuran="pendek" testId="mapping-form"
        judul={editingMapping ? 'Ubah pemetaan akun' : 'Pemetaan akun baru'}
        keterangan="Kategori klaim karyawan dan akun beban untuk jurnal otomatis."
        onSimpan={handleSave}>
        <Isian label="Kategori klaim" htmlFor="category">
          <Input id="category" placeholder="mis. Transportasi, Konsumsi, Akomodasi" value={formData.category}
            onChange={(e) => setFormData(prev => ({ ...prev, category: e.target.value }))} data-testid="mapping-category-input" />
        </Isian>
        <Isian label="Akun beban" htmlFor="gl_account">
          <SmartNativeSelect id="gl_account" className="w-full h-9" value={formData.gl_account_code}
            onChange={(e) => handleAccountSelect(e.target.value)} data-testid="mapping-account-select">
            <option value="">Pilih akun</option>
            {coaAccounts
              .filter(a => a.code.startsWith('6-') || a.code.startsWith('5-'))
              .map(acc => (
                <option key={acc.code} value={acc.code}>
                  {acc.code} — {acc.name}
                </option>
              ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Nama akun" htmlFor="gl_name">
          <Input id="gl_name" value={formData.gl_account_name} placeholder="Nama akun beban"
            onChange={(e) => setFormData(prev => ({ ...prev, gl_account_name: e.target.value }))} data-testid="mapping-account-name-input" />
        </Isian>
        <label className="flex items-center gap-2 text-sm" htmlFor="is_active">
          <Switch id="is_active" checked={formData.is_active}
            onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_active: checked }))} data-testid="mapping-active-switch" />
          Aktif
        </label>
      </FormPopup>
    </PageLayout>
  );
}
