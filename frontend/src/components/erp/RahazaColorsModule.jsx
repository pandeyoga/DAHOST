import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Plus, Edit2, Trash2, Palette } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';

// Nilai awal pemilih warna (data, bukan gaya layar).
const DEFAULT_FORM = { code: '', name: '', hex: '#3B82F6', order_seq: 50, active: true };

/* Master Warna (DINAMIS) — Fase 2 Master Product Refactor.
   Palet techpack ter-seed otomatis; user bisa tambah/edit/hapus.
   `code` (singkatan) dipakai di SKU varian: KODE-WARNA-SIZE. */
export function RahazaColorsModule({ token }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [saving, setSaving] = useState(false);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/colors?include_inactive=true', { headers });
      if (r.ok) setRows(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const openCreate = () => { setEditing(null); setForm(DEFAULT_FORM); setModalOpen(true); };
  const openEdit = (row) => {
    setEditing(row);
    setForm({
      code: row.code || '', name: row.name || '', hex: row.hex || '#CCCCCC',
      order_seq: row.order_seq ?? 50, active: row.active !== false,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!form.name) { toast.error('Nama warna wajib diisi'); return; }
    setSaving(true);
    try {
      const url = editing ? `/api/rahaza/colors/${editing.id}` : '/api/rahaza/colors';
      const method = editing ? 'PUT' : 'POST';
      const r = await fetch(url, { method, headers, body: JSON.stringify(form) });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        toast.error(err.detail || `Gagal (HTTP ${r.status})`);
        return;
      }
      toast.success(editing ? 'Warna diperbarui' : 'Warna ditambahkan');
      setModalOpen(false);
      fetchRows();
    } finally { setSaving(false); }
  };

  const handleDelete = async (row) => {
    if (!(await confirmDialog({ title: `Nonaktifkan warna ${row.name} (${row.code})?`, confirmLabel: 'Nonaktifkan', danger: true }))) return;
    const r = await fetch(`/api/rahaza/colors/${row.id}`, { method: 'DELETE', headers });
    if (r.ok) { toast.success('Warna dinonaktifkan'); fetchRows(); }
    else {
      const err = await r.json().catch(() => ({}));
      toast.error(err.detail || 'Gagal menonaktifkan');
    }
  };

  // Standar UI/UX v2 (8 Nov 2026): PageLayout (di hub judul tersembunyi), TabelData + unduh, form = FormPopup.
  const kolom = [
    { kunci: 'warna', label: 'Warna', hp: false, isi: (row) => (
      <span className="inline-block w-7 h-7 rounded-md border border-[var(--glass-border)]" style={{ backgroundColor: row.hex || 'transparent' }} title={row.hex} />) },
    { kunci: 'kode', label: 'Kode', hp: 'judul', isi: (row) => <span className="tabular-nums font-medium">{row.code}</span> },
    { kunci: 'nama', label: 'Nama', hp: 'keterangan', isi: (row) => row.name },
    { kunci: 'hex', label: 'Hex', isi: (row) => <span className="tabular-nums text-xs text-muted-foreground">{row.hex}</span> },
    { kunci: 'status', label: 'Status', isi: (row) => (row.active === false
      ? <StatusBadge status="inactive" tone="muted" label="Nonaktif" /> : <StatusBadge status="active" tone="success" label="Aktif" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (row) => (
      <div className="inline-flex items-center gap-1">
        <Button type="button" variant="ghost" size="icon-sm" onClick={() => openEdit(row)} title="Ubah" aria-label="Ubah" data-testid={`color-edit-${row.code}`}><Edit2 className="w-3.5 h-3.5" /></Button>
        {row.active !== false && (
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => handleDelete(row)} title="Nonaktifkan" aria-label="Nonaktifkan" data-testid={`color-delete-${row.code}`}><Trash2 className="w-3.5 h-3.5" /></Button>
        )}
      </div>) },
  ];
  return (
    <PageLayout testId="rahaza-colors-module" title="Master warna"
      subtitle="Palet warna (gaya techpack). Kode singkatan dipakai di SKU varian: KODE-WARNA-UKURAN."
      actions={<Button type="button" onClick={openCreate} data-testid="color-create-btn"><Plus className="w-4 h-4" /> Tambah warna</Button>}
      tools={<TombolUnduh namaBerkas="master-warna" baris={rows} testId="color-unduh" kolom={[
        { label: 'Kode', nilai: (r) => r.code || '' }, { label: 'Nama', nilai: (r) => r.name || '' }, { label: 'Hex', nilai: (r) => r.hex || '' },
        { label: 'Urutan', nilai: (r) => Number(r.order_seq) || 0 }, { label: 'Status', nilai: (r) => (r.active === false ? 'Nonaktif' : 'Aktif') },
      ]} />}>
      {loading ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <TabelData kolom={kolom} baris={rows} testId="color-table"
          kosong={<EmptyState icon={Palette} title="Belum ada warna" description="Klik Tambah warna untuk menambah palet." />} />
      )}

      {modalOpen && (
        <FormPopup open onClose={() => setModalOpen(false)} ukuran="pendek" testId="color-form-popup"
          judul={editing ? 'Ubah warna' : 'Tambah warna'} onSimpan={handleSave} menyimpan={saving}>
          <div className="space-y-4" data-testid="color-form">
            <Isian label="Nama warna" wajib>
              <GlassInput value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="Contoh: Merah Marun" data-testid="color-form-name" />
            </Isian>
            <div className="grid grid-cols-2 gap-4">
              <Isian label="Kode (singkatan)" wajib petunjuk="Dipakai di SKU. Kosongkan = otomatis 3 huruf.">
                <GlassInput value={form.code} onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })}
                  placeholder="Contoh: MRN" maxLength={6} data-testid="color-form-code" />
              </Isian>
              <Isian label="Warna (hex)">
                <div className="flex items-center gap-2">
                  <input type="color" value={form.hex} onChange={e => setForm({ ...form, hex: e.target.value })} aria-label="Pilih warna"
                    className="w-10 h-9 shrink-0 rounded-md border border-[var(--glass-border)] bg-transparent cursor-pointer p-0.5"
                    data-testid="color-form-hex-picker" />
                  <GlassInput value={form.hex} onChange={e => setForm({ ...form, hex: e.target.value })}
                    placeholder="#RRGGBB" data-testid="color-form-hex" />
                </div>
              </Isian>
            </div>
            <Isian label="Urutan">
              <GlassInput type="number" value={form.order_seq}
                onChange={e => setForm({ ...form, order_seq: parseInt(e.target.value) || 50 })} data-testid="color-form-order" />
            </Isian>
            {editing && (
              <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
                <Checkbox checked={form.active} onCheckedChange={(v) => setForm({ ...form, active: !!v })} data-testid="color-form-active" />
                Aktif
              </label>
            )}
          </div>
        </FormPopup>
      )}
    </PageLayout>
  );
}

export default RahazaColorsModule;
