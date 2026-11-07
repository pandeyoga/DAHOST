/**
 * Pengaturan Sistem › Kunci API — kunci integrasi layanan luar (AI, notifikasi, penyimpanan, email).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (di hub judul disembunyikan), satu tabel (kartu ringkas di HP) dengan
 * penyaring kategori, unduh Excel/CSV TANPA nilai kunci, form tambah/ubah = FormPopup, hapus lewat confirmDialog.
 * Keamanan tidak berubah: nilai kunci tidak pernah ditampilkan utuh (hanya `masked_value` dari server), isian nilai
 * tetap bertipe sandi, izin tambah/ubah (admin) & hapus (superadmin) sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Eye, EyeOff, MoreHorizontal, Pencil, Plus, RefreshCw, TestTube2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const CATEGORY_META = {
  ai: { label: 'AI & LLM' },
  notification: { label: 'Notifikasi' },
  storage: { label: 'Penyimpanan' },
  email: { label: 'Email' },
  custom: { label: 'Kustom' },
};
const labelKategori = (c) => (CATEGORY_META[c] || CATEGORY_META.custom).label;
const statusKunci = (k) => (k.is_configured
  ? `Terpasang (${k.source === 'db' ? 'layar ini' : 'server'})` : 'Belum diisi');
const instan = (ts) => (typeof ts === 'string' && /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(ts) ? `${ts}Z` : ts);

export default function IntegrationSettingsModule({ token, userRole }) {
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [editKey, setEditKey] = useState(null); // key_name being edited
  const [form, setForm] = useState({ key_name: '', value: '', description: '', category: 'ai' });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState({});
  const [testResults, setTestResults] = useState({});
  const [showValues, setShowValues] = useState({});
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');
  const [kategori, setKategori] = useState('');

  const canEdit = ['superadmin', 'admin'].includes(userRole);
  const canDelete = userRole === 'superadmin';

  const fetchKeys = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/rahaza/integration-settings', {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.ok) { setKeys(data.data || []); setError(''); }
      else setError(data.detail || 'Gagal memuat pengaturan.');
    } catch (e) {
      setError('Gagal terhubung ke server.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { fetchKeys(); }, [fetchKeys]);

  const handleSave = async () => {
    if (!form.key_name || !form.value) {
      setFormError('Nama kunci dan nilai wajib diisi.');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      const res = await fetch('/api/rahaza/integration-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (data.ok) {
        toast.success(data.message || 'Berhasil disimpan.');
        setAddOpen(false);
        setEditKey(null);
        setForm({ key_name: '', value: '', description: '', category: 'ai' });
        setShowValues((s) => ({ ...s, _form: false }));
        fetchKeys();
      } else {
        setFormError(data.detail || 'Gagal menyimpan.');
      }
    } catch (e) {
      setFormError('Gagal terhubung ke server.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (keyName) => {
    // 2026-11-02: tanpa istilah teknis "environment variable" di layar.
    if (!(await confirmDialog({
      title: `Hapus kunci ${keyName}?`, danger: true, confirmLabel: 'Hapus',
      body: 'Kunci dihapus dari database. Bila kunci juga diatur di server, nilai server yang dipakai.',
    }))) return;
    try {
      const res = await fetch(`/api/rahaza/integration-settings/${keyName}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.ok) {
        toast.success(data.message || 'Kunci dihapus.');
        fetchKeys();
      } else {
        toast.error(data.detail || 'Gagal menghapus.');
      }
    } catch (e) {
      toast.error('Gagal terhubung ke server.');
    }
  };

  const handleTest = async (keyName) => {
    setTesting(t => ({ ...t, [keyName]: true }));
    try {
      const res = await fetch(`/api/rahaza/integration-settings/test/${keyName}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setTestResults(r => ({ ...r, [keyName]: data }));
    } catch (e) {
      setTestResults(r => ({ ...r, [keyName]: { ok: false, message: 'Gagal menghubungi server.' } }));
    } finally {
      setTesting(t => ({ ...t, [keyName]: false }));
    }
  };

  const openEdit = (key) => {
    setEditKey(key.key_name);
    setForm({
      key_name: key.key_name,
      value: '',
      description: key.description || '',
      category: key.category || 'ai',
    });
    setFormError('');
    setAddOpen(true);
  };

  const openAdd = () => {
    setEditKey(null);
    setForm({ key_name: '', value: '', description: '', category: 'ai' });
    setFormError('');
    setAddOpen(true);
  };

  const tutupForm = () => { setAddOpen(false); setEditKey(null); setFormError(''); setShowValues((s) => ({ ...s, _form: false })); };

  const hitung = (c) => keys.filter((k) => (k.category || 'custom') === c).length;
  const opsiKategori = [
    { key: '', label: 'Semua', count: keys.length },
    ...Object.keys(CATEGORY_META).map((c) => ({ key: c, label: labelKategori(c), count: hitung(c) })).filter((o) => o.count > 0),
  ];
  const baris = keys.filter((k) => !kategori || (k.category || 'custom') === kategori);

  const kolom = [
    { kunci: 'nama', label: 'Kunci', hp: 'judul', isi: (k) => (
      <div className="min-w-0 md:max-w-[22rem]" data-testid={`key-row-${k.key_name}`}>
        <p className="break-all font-mono text-sm font-medium text-foreground">{k.key_name}</p>
        {k.description && <p className="text-xs text-muted-foreground">{k.description}</p>}
      </div>) },
    { kunci: 'kategori', label: 'Kategori', isi: (k) => <span className="text-sm">{labelKategori(k.category || 'custom')}</span> },
    { kunci: 'status', label: 'Status', isi: (k) => (
      <div className="space-y-1">
        <div className="flex flex-wrap gap-1">
          <StatusBadge status={k.is_configured ? 'ok' : 'kosong'} label={statusKunci(k)} tone={k.is_configured ? 'success' : 'muted'} />
          {k.deprecated && <StatusBadge status="lama" label="Tidak dipakai lagi" tone="warning" />}
        </div>
        {testResults[k.key_name] && (
          <p className={`text-xs ${testResults[k.key_name].ok ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}`}>
            {testResults[k.key_name].message}
          </p>
        )}
      </div>) },
    { kunci: 'nilai', label: 'Nilai (disamarkan)', isi: (k) => (k.is_configured
      ? <code className="break-all font-mono text-xs text-muted-foreground">{k.masked_value || '(server)'}</code>
      : <span className="text-sm text-muted-foreground">—</span>) },
    { kunci: 'diperbarui', label: 'Diperbarui', isi: (k) => (k.updated_at
      ? <span className="text-sm">{formatDateID(instan(k.updated_at))}{k.updated_by && <span className="block text-xs text-muted-foreground">{k.updated_by}</span>}</span>
      : <span className="text-sm text-muted-foreground">—</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (k) => (
      <div className="flex items-center justify-end gap-1">
        <Button variant="outline" size="sm" onClick={() => handleTest(k.key_name)} disabled={testing[k.key_name]}
          title="Uji kunci" data-testid={`test-key-${k.key_name}`}>
          <TestTube2 className={testing[k.key_name] ? 'animate-pulse' : ''} />Uji
        </Button>
        {(canEdit || (canDelete && k.source === 'db')) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label="Lainnya" data-testid={`more-key-${k.key_name}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canEdit && (
                <DropdownMenuItem onSelect={() => openEdit(k)} data-testid={`edit-key-${k.key_name}`}>
                  <Pencil className="mr-2 h-4 w-4" />Ganti nilai
                </DropdownMenuItem>
              )}
              {canDelete && k.source === 'db' && (
                <DropdownMenuItem onSelect={() => handleDelete(k.key_name)} className="text-[hsl(var(--danger-text))]"
                  data-testid={`delete-key-${k.key_name}`}>
                  <Trash2 className="mr-2 h-4 w-4" />Hapus dari database
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>) },
  ];

  return (
    <PageLayout testId="integration-settings-module" title="Kunci API"
      subtitle="Kunci layanan luar (AI, notifikasi, penyimpanan, email). Nilai kunci tidak pernah ditampilkan utuh."
      actions={canEdit && <Button onClick={openAdd} data-testid="add-key-btn"><Plus />Tambah kunci</Button>}
      filters={keys.length > 0 && (
        <FilterChips className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" options={opsiKategori} value={kategori} onChange={setKategori} hideWhenEmpty={false} testId="key-category-filter" />
      )}
      tools={<>
        {/* Unduhan TIDAK memuat nilai kunci (juga tidak versi tersamar). */}
        <TombolUnduh namaBerkas="kunci-api" namaLembar="Kunci API" baris={baris} testId="key-unduh" kolom={[
          { label: 'Kunci', nilai: (k) => k.key_name }, { label: 'Kategori', nilai: (k) => labelKategori(k.category || 'custom') },
          { label: 'Keterangan', nilai: (k) => k.description || '' }, { label: 'Status', nilai: (k) => statusKunci(k) },
          { label: 'Tidak dipakai lagi', nilai: (k) => (k.deprecated ? 'Ya' : '') },
          { label: 'Diperbarui', nilai: (k) => (k.updated_at ? formatDateID(instan(k.updated_at)) : '') },
          { label: 'Oleh', nilai: (k) => k.updated_by || '' },
        ]} />
        <Button variant="outline" size="icon" onClick={fetchKeys} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      <Notice tone="info" title="Urutan pemakaian kunci">
        1) Nilai yang disimpan di layar ini diutamakan; 2) pengaturan server dipakai bila belum diisi di sini.
        Fitur AI hanya memakai <span className="font-mono">ANTHROPIC_API_KEY</span>.
      </Notice>
      {error && <Notice tone="danger">{error}</Notice>}

      {loading && keys.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat kunci…</p>
      ) : (
        <TabelData kolom={kolom} baris={baris} kunci={(k) => k.key_name} testId="key-table"
          kosong={<EmptyState title="Belum ada kunci" description="Tambahkan kunci layanan yang dipakai sistem."
            action={canEdit ? { label: 'Tambah kunci', onClick: openAdd } : undefined} />} />
      )}

      <FormPopup open={addOpen} onClose={tutupForm} ukuran="pendek" testId="key-form"
        judul={editKey ? `Ganti nilai ${editKey}` : 'Tambah kunci API'}
        keterangan={editKey ? 'Nilai lama tidak ditampilkan. Isi nilai baru untuk menggantinya.' : 'Nilai disimpan tersamar dan tidak pernah ditampilkan utuh.'}
        onSimpan={handleSave} menyimpan={saving} galat={formError}>
        {!editKey && (
          <Isian label="Nama kunci" wajib htmlFor="key-name" petunjuk="Hanya huruf kapital, angka, dan garis bawah.">
            <Input id="key-name" required className="font-mono" placeholder="CONTOH_API_KEY" value={form.key_name}
              onChange={e => setForm(f => ({ ...f, key_name: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '') }))} />
          </Isian>
        )}
        <Isian label={editKey ? 'Nilai baru' : 'Nilai'} wajib htmlFor="key-value">
          <div className="relative">
            <Input id="key-value" type={showValues['_form'] ? 'text' : 'password'} required autoComplete="off"
              className="pr-10 font-mono" value={form.value}
              placeholder={editKey ? 'Masukkan nilai baru untuk mengganti…' : 'Masukkan nilai kunci…'}
              onChange={e => setForm(f => ({ ...f, value: e.target.value }))} />
            <Button type="button" variant="ghost" size="icon-sm" className="absolute right-1 top-1/2 -translate-y-1/2"
              onClick={() => setShowValues(s => ({ ...s, _form: !s._form }))}
              title={showValues['_form'] ? 'Sembunyikan nilai' : 'Tampilkan nilai yang diketik'}
              aria-label={showValues['_form'] ? 'Sembunyikan nilai' : 'Tampilkan nilai yang diketik'}>
              {showValues['_form'] ? <EyeOff /> : <Eye />}
            </Button>
          </div>
        </Isian>
        <Isian label="Keterangan (opsional)" htmlFor="key-desc">
          <Input id="key-desc" placeholder="Keterangan penggunaan kunci ini…" value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
        </Isian>
        <Isian label="Kategori" htmlFor="key-category">
          <SmartNativeSelect id="key-category" value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}>
            {Object.entries(CATEGORY_META).map(([val, meta]) => (
              <option key={val} value={val}>{meta.label}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}
