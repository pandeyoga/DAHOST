import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Plus, Pencil, Ban } from 'lucide-react';
import { toast } from 'sonner';
import DataTable from './DataTable';
import ImportExportToolbar from './ImportExportToolbar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { StatusBadge } from './moduleAtoms';

// Reusable master-data CRUD page (Gudang › Lokasi gudang; Produksi/RnD › master lini, mesin, proses, shift, ukuran, karyawan).
// Props (tidak berubah):
//   title       : judul halaman
//   description : subtitle
//   endpoint    : '/api/rahaza/locations' etc.
//   token       : auth token
//   columns     : [{ key, label, render?, showInForm? }]
//   fields      : [{ key, label, type: 'text'|'select'|'number'|'readonly'|'time', options?:[{value,label}], required?, help?, createOnly?, editOnly? }]
//   defaultItem : initial form state
//   testIdPrefix
//   canEdit     : boolean (default true)
//   ieKey       : kunci registri impor/unduh data master (opsional)
//
// Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di dalam hub judulnya tersembunyi), form = FormPopup
// (pendek ≤ 6 isian, panjang bila lebih), nonaktifkan lewat confirmDialog, status = StatusBadge, unduhan tabel
// (DataTable bawaan) memakai teks yang sama dengan yang tampil — bukan kode mentah (mis. "Zona", bukan "zona").
const teksSel = (out) => (typeof out === 'string' || typeof out === 'number' ? out : null);

export default function MasterDataCRUD({
  title, description, endpoint, token,
  columns = [], fields = [], defaultItem = {},
  testIdPrefix = 'md',
  canEdit = true,
  ieKey = null,
}) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(defaultItem);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(endpoint, { headers });
      if (res.ok) {
        const d = await res.json();
        // Unwrap paginated responses ({items|rows|data|results:[...]}) → always store an array.
        setRows(Array.isArray(d) ? d : (d?.items || d?.rows || d?.data || d?.results || []));
      }
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, token]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const openCreate = () => { setEditing(null); setForm(defaultItem); setError(''); setModalOpen(true); };
  const openEdit = (row) => {
    setEditing(row);
    const f = { ...defaultItem };
    fields.forEach(fld => { f[fld.key] = row[fld.key] ?? defaultItem[fld.key] ?? ''; });
    setForm(f);
    setError('');
    setModalOpen(true);
  };

  const handleSave = async () => {
    setSaving(true); setError('');
    try {
      const url = editing ? `${endpoint}/${editing.id}` : endpoint;
      const method = editing ? 'PUT' : 'POST';
      const res = await fetch(url, { method, headers, body: JSON.stringify(form) });
      if (!res.ok) {
        // Status-based friendly message (body stream may be consumed by
        // third-party scripts like analytics wrappers — don't rely on it).
        const STATUS_MSG = {
          400: 'Data tidak valid. Periksa kembali isian form.',
          401: 'Sesi berakhir. Silakan login ulang.',
          403: 'Anda tidak punya akses untuk aksi ini.',
          404: 'Data tidak ditemukan.',
          409: `Kode "${form.code || form.employee_code || ''}" sudah terpakai. Gunakan kode lain.`,
          422: 'Format data tidak sesuai.',
          500: 'Server error. Coba lagi beberapa saat.',
        };
        let msg = STATUS_MSG[res.status] || `Gagal menyimpan (HTTP ${res.status})`;
        // Try to read body for more detail (may fail if intercepted)
        try {
          const clone = res.clone();
          const data = await clone.json();
          if (data && typeof data.detail === 'string') msg = data.detail;
          else if (data && Array.isArray(data.detail) && data.detail[0]?.msg) msg = data.detail.map(d => d.msg).join(', ');
        } catch (_) { /* body unreadable — keep status-based msg */ }
        throw new Error(msg);
      }
      setModalOpen(false);
      await fetchRows();
    } catch (err) { setError(err.message || 'Terjadi kesalahan tidak terduga'); }
    finally { setSaving(false); }
  };

  const handleDeactivate = async (row) => {
    const ok = await confirmDialog({
      title: `Nonaktifkan "${row.name || row.code}"?`,
      body: 'Data tidak dihapus; hanya tidak dipakai lagi di pilihan baru.',
      confirmLabel: 'Nonaktifkan', danger: true,
    });
    if (!ok) return;
    const res = await fetch(`${endpoint}/${row.id}`, { method: 'DELETE', headers });
    if (!res.ok) toast.error(`Gagal menonaktifkan (HTTP ${res.status}).`);
    fetchRows();
  };

  // Kolom pemanggil: tampilan tetap lewat render(value,row); unduhan & urutan memakai teks yang tampil.
  const tableColumns = useMemo(() => columns.map((c) => {
    if (typeof c.render !== 'function') return c;
    return {
      ...c,
      accessor: (row) => { const t = teksSel(c.render(row[c.key], row)); return t === null ? row[c.key] : t; },
      render: (_v, row) => c.render(row[c.key], row),
    };
  }), [columns]);

  const activeCol = {
    key: 'active', label: 'Status',
    accessor: (row) => (row.active ? 'Aktif' : 'Nonaktif'),
    render: (_v, row) => (row.active
      ? <StatusBadge status="aktif" label="Aktif" tone="success" />
      : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />),
  };

  const actionsCol = canEdit ? {
    key: '_actions', label: '',
    render: (_, row) => (
      <div className="flex items-center justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(row)} title="Ubah" aria-label={`Ubah ${row.name || row.code || ''}`}
          data-testid={`${testIdPrefix}-edit-${row.id}`}><Pencil /></Button>
        {row.active && (
          <Button variant="ghost" size="icon-sm" onClick={() => handleDeactivate(row)} title="Nonaktifkan"
            aria-label={`Nonaktifkan ${row.name || row.code || ''}`}
            data-testid={`${testIdPrefix}-deactivate-${row.id}`}><Ban /></Button>
        )}
      </div>
    ),
  } : null;

  const fullColumns = [...tableColumns, activeCol, ...(actionsCol ? [actionsCol] : [])];
  const visibleFields = fields.filter(f => !(editing && f.createOnly) && !(f.editOnly && !editing));

  return (
    <PageLayout testId={`${testIdPrefix}-page`} title={title} subtitle={description}
      actions={(canEdit || ieKey) ? <>
        {ieKey && <ImportExportToolbar collectionKey={ieKey} label={title} onImported={fetchRows} size="default" caption="master" />}
        {canEdit && (
          <Button onClick={openCreate} data-testid={`${testIdPrefix}-add-btn`}>
            <Plus />Tambah
          </Button>
        )}
      </> : null}>
      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat data…</p>
      ) : (
        <div className="overflow-x-auto">
          <DataTable
            columns={fullColumns}
            data={rows}
            searchKeys={columns.map(c => c.key)}
          />
        </div>
      )}

      <FormPopup open={modalOpen} onClose={() => setModalOpen(false)} onSimpan={handleSave} menyimpan={saving}
        ukuran={visibleFields.length > 6 ? 'panjang' : 'pendek'} galat={error} testId={`${testIdPrefix}-form`}
        judul={editing ? `Ubah ${title}` : `Tambah ${title}`}
        labelSimpan={editing ? 'Simpan perubahan' : 'Simpan'}>
        {visibleFields.map(fld => (
          <Isian key={fld.key} label={fld.label} wajib={!!fld.required} petunjuk={fld.help}
            htmlFor={fld.type === 'select' ? undefined : `${testIdPrefix}-in-${fld.key}`}>
            {fld.type === 'select' ? (
              <SmartNativeSelect
                value={form[fld.key] ?? ''}
                onChange={e => setForm({ ...form, [fld.key]: e.target.value })}
                className="w-full"
                data-testid={`${testIdPrefix}-field-${fld.key}`}
              >
                <option value="">Pilih</option>
                {(fld.options || []).map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </SmartNativeSelect>
            ) : fld.type === 'number' ? (
              <Input
                id={`${testIdPrefix}-in-${fld.key}`}
                type="number"
                value={form[fld.key] ?? ''}
                onChange={e => setForm({ ...form, [fld.key]: e.target.value === '' ? '' : Number(e.target.value) })}
                placeholder={fld.placeholder || ''}
                data-testid={`${testIdPrefix}-field-${fld.key}`}
              />
            ) : (
              <Input
                id={`${testIdPrefix}-in-${fld.key}`}
                type={fld.type === 'time' ? 'time' : 'text'}
                value={form[fld.key] ?? ''}
                onChange={e => setForm({ ...form, [fld.key]: e.target.value })}
                placeholder={fld.placeholder || ''}
                disabled={fld.type === 'readonly'}
                data-testid={`${testIdPrefix}-field-${fld.key}`}
              />
            )}
          </Isian>
        ))}
      </FormPopup>
    </PageLayout>
  );
}
