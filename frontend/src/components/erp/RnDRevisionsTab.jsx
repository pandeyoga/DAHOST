/**
 * Revisi & persetujuan (Portal RnD › Style & Desain › tab "Revisi").
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, linimasa kartu → tabel (kartu ringkas di HP) + unduh
 * Excel/CSV, rincian = popup, form = FormPopup, hapus lewat confirmDialog, jenis revisi = StatusBadge.
 * Hanya tampilan yang berubah — API, isian, dan perbandingan revisi sama seperti sebelumnya.
 */
import { useState, useEffect } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GitBranch, Plus, Trash2, Search, GitCompare, RefreshCw } from 'lucide-react';
import { toast } from '../ui/sonner';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import RnDRevisionCompare from './RnDRevisionCompare';
import { apiPost, apiDelete } from '@/lib/api';

const API = process.env.REACT_APP_BACKEND_URL || '';

const TYPE_CONF = {
  'design':    { label: 'Desain',   tone: 'primary' },
  'material':  { label: 'Material', tone: 'warning' },
  'fit':       { label: 'Fit',      tone: 'info' },
  'costing':   { label: 'Biaya',    tone: 'success' },
  'other':     { label: 'Lainnya',  tone: 'muted' },
};
const jenis = (t) => TYPE_CONF[t] || TYPE_CONF.other;

const emptyForm = {
  style_id: '', style_code: '', style_name: '',
  revision_name: '',
  revision_type: 'design',
  changes_summary: '',
  old_value: '',
  new_value: '',
  notes: '',
};

function JenisBadge({ type }) {
  const j = jenis(type);
  return <StatusBadge status={type} label={j.label} tone={j.tone} />;
}

export default function RnDRevisionsTab({ token }) {
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  const [revisions, setRevisions] = useState([]);
  const [styles,    setStyles]    = useState([]);
  const [loading,   setLoading]   = useState(false);
  const [search,    setSearch]    = useState('');
  const [filterStyle, setFilterStyle] = useState('');
  const [showForm,  setShowForm]  = useState(false);
  const [form,      setForm]      = useState({ ...emptyForm });
  const [compare,   setCompare]   = useState(null); // {styleId, left}
  const [detail,    setDetail]    = useState(null);

  const f = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const fetchRevisions = async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (filterStyle) qs.set('style_id', filterStyle);
      const res = await fetch(`${API}/api/dewi/rnd/revisions${qs.toString() ? '?' + qs : ''}`, { headers: h });
      if (res.ok) setRevisions(await res.json());
    } catch { toast.error('Gagal memuat revisi'); }
    finally { setLoading(false); }
  };

  const fetchStyles = async () => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles`, { headers: h });
      if (res.ok) setStyles(await res.json());
    } catch { /* ignore */ }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchRevisions(); }, [filterStyle]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchStyles(); }, []);

  const setStyleField = sid => {
    const sel = styles.find(s => s.id === sid);
    setForm(p => ({ ...p, style_id: sid, style_code: sel?.style_code || '', style_name: sel?.style_name || '' }));
  };

  const openNew = () => { setForm({ ...emptyForm }); setShowForm(true); };

  const handleSave = async () => {
    if (!form.style_id) return toast.error('Pilih style terlebih dahulu');
    if (!form.revision_name.trim()) return toast.error('Nama revisi wajib diisi');
    try {
      // 2026-11-06 (pola P6): helper lib/api melempar bila server menolak → pesan sukses hanya bila benar tersimpan
      await apiPost('/api/dewi/rnd/revisions', form);
      toast.success('Revisi berhasil ditambahkan');
      setShowForm(false);
      setForm({ ...emptyForm });
      fetchRevisions();
    } catch { toast.error('Gagal menyimpan revisi'); }
  };

  const handleDelete = async (r) => {
    const ok = await confirmDialog({
      title: 'Hapus revisi ini?',
      body: `Revisi "${r.revision_name || ''}" dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      await apiDelete(`/api/dewi/rnd/revisions/${r.id}`);  // 2026-11-06 (pola P6): lihat simpan revisi
      toast.success('Revisi dihapus');
      setDetail(null);
      fetchRevisions();
    } catch { toast.error('Gagal menghapus'); }
  };

  const filtered = revisions.filter(r => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (r.style_code || '').toLowerCase().includes(q)
      || (r.revision_name || '').toLowerCase().includes(q)
      || (r.changes_summary || '').toLowerCase().includes(q);
  });

  const bandingkan = (r) => setCompare({ styleId: r.style_id, left: r.id });

  const kolom = [
    { kunci: 'revisi', label: 'Revisi', hp: 'judul', isi: (r) => (
      <div className="min-w-0 md:max-w-[18rem]">
        <p className="truncate font-medium text-foreground" title={r.revision_name}>{r.revision_name}</p>
        <p className="text-xs text-muted-foreground">#{r.revision_number}</p>
      </div>) },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (r) => r.style_code || '—' },
    { kunci: 'jenis', label: 'Jenis', isi: (r) => <JenisBadge type={r.revision_type} /> },
    { kunci: 'ringkasan', label: 'Perubahan', isi: (r) => (
      <div className="min-w-0 md:max-w-[22rem]">
        {r.changes_summary && <p className="truncate text-sm" title={r.changes_summary}>{r.changes_summary}</p>}
        {(r.old_value || r.new_value) && (
          <p className="truncate text-xs text-muted-foreground" title={`${r.old_value || '—'} → ${r.new_value || '—'}`}>
            {r.old_value || '—'} → {r.new_value || '—'}
          </p>
        )}
        {!r.changes_summary && !r.old_value && !r.new_value && <span className="text-muted-foreground">—</span>}
      </div>) },
    { kunci: 'oleh', label: 'Dicatat oleh', isi: (r) => r.created_by_name || '—' },
    { kunci: 'tanggal', label: 'Tanggal', isi: (r) => <span className="md:whitespace-nowrap">{formatDateID(r.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-1">
        <Button variant="outline" size="sm" onClick={() => bandingkan(r)}
          data-testid={`compare-revision-${r.id}`} title="Bandingkan revisi ini dengan versi lain">
          <GitCompare />Bandingkan
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => handleDelete(r)} title="Hapus" aria-label="Hapus"
          data-testid={`delete-revision-${r.id}`}>
          <Trash2 className="text-[hsl(var(--danger-text))]" />
        </Button>
      </div>) },
  ];

  return (
    <PageLayout testId="rnd-revisions-tab" title="Revisi & persetujuan"
      subtitle="Riwayat perubahan desain per style, bisa dibandingkan antarversi."
      actions={<>
        <Button variant="outline" disabled={!filterStyle}
          title={filterStyle ? 'Bandingkan dua revisi style ini' : 'Pilih satu style dulu'}
          onClick={() => setCompare({ styleId: filterStyle, left: '' })}
          data-testid="compare-revisions-btn">
          <GitCompare />Bandingkan revisi
        </Button>
        <Button onClick={openNew} data-testid="create-revision-btn"><Plus />Tambah revisi</Button>
      </>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Cari revisi atau style" className="pl-8" data-testid="revision-search" />
        </div>
        <SmartNativeSelect value={filterStyle} onChange={e => setFilterStyle(e.target.value)}
          className="w-full sm:w-56" data-testid="revision-style-filter">
          <option value="">Semua style</option>
          {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="revisi-desain" namaLembar="Revisi" baris={filtered} testId="revision-unduh"
          kolom={[
            { label: 'No. revisi', nilai: (r) => r.revision_number ?? '' },
            { label: 'Nama revisi', nilai: (r) => r.revision_name || '' },
            { label: 'Kode style', nilai: (r) => r.style_code || '' },
            { label: 'Nama style', nilai: (r) => r.style_name || '' },
            { label: 'Jenis', nilai: (r) => jenis(r.revision_type).label },
            { label: 'Ringkasan perubahan', nilai: (r) => r.changes_summary || '' },
            { label: 'Sebelum', nilai: (r) => r.old_value || '' },
            { label: 'Sesudah', nilai: (r) => r.new_value || '' },
            { label: 'Catatan', nilai: (r) => r.notes || '' },
            { label: 'Dicatat oleh', nilai: (r) => r.created_by_name || '' },
            { label: 'Tanggal', nilai: (r) => (r.created_at ? formatDateID(r.created_at) : '') },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchRevisions} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && revisions.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat revisi…</p>
      ) : (
        <TabelData kolom={kolom} baris={filtered} onKlikBaris={setDetail} testId="revision-table"
          kosong={<EmptyState icon={GitBranch}
            title={revisions.length ? 'Tidak ada revisi yang cocok' : 'Belum ada revisi'}
            description={revisions.length ? 'Ubah kata pencarian.' : 'Catat perubahan desain, material, fit, atau biaya per style.'}
            action={!revisions.length && <Button onClick={openNew}><Plus />Catat revisi pertama</Button>} />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="revision-detail"
          judul={detail.revision_name}
          keterangan={[detail.style_code, detail.style_name].filter(Boolean).join(' · ') || undefined}
          status={<JenisBadge type={detail.revision_type} />}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { bandingkan(detail); setDetail(null); }}><GitCompare />Bandingkan</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="No. revisi">#{detail.revision_number}</BarisDetail>
            <BarisDetail label="Ringkasan perubahan">{detail.changes_summary || '—'}</BarisDetail>
            <BarisDetail label="Sebelum">{detail.old_value || '—'}</BarisDetail>
            <BarisDetail label="Sesudah">{detail.new_value || '—'}</BarisDetail>
            {detail.notes && <BarisDetail label="Catatan">{detail.notes}</BarisDetail>}
            <BarisDetail label="Dicatat">{formatDateID(detail.created_at)}{detail.created_by_name ? ` · ${detail.created_by_name}` : ''}</BarisDetail>
          </dl>
        </DetailPopup>
      )}

      {/* Form catat revisi (popup standar) */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} onSimpan={handleSave}
        judul="Catat revisi baru" keterangan="Riwayat perubahan desain untuk satu style."
        labelSimpan="Simpan revisi" testId="revision-form">
        <Isian label="Style" wajib>
          <SmartNativeSelect value={form.style_id} onChange={e => setStyleField(e.target.value)}
            className="w-full" data-testid="revision-style-select">
            <option value="">Pilih style</option>
            {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
          </SmartNativeSelect>
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Nama revisi" wajib htmlFor="rev-nama">
            <Input id="rev-nama" value={form.revision_name}
              onChange={e => f('revision_name', e.target.value)}
              placeholder="Contoh: Ubah kancing depan" data-testid="revision-name-input" />
          </Isian>
          <Isian label="Jenis revisi">
            <SmartNativeSelect value={form.revision_type} onChange={e => f('revision_type', e.target.value)}
              searchable={false} className="w-full" data-testid="revision-type-select">
              {Object.entries(TYPE_CONF).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Ringkasan perubahan" htmlFor="rev-ringkas">
          <Textarea id="rev-ringkas" rows={3} value={form.changes_summary} onChange={e => f('changes_summary', e.target.value)}
            placeholder="Jelaskan apa yang berubah…" />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Nilai sebelumnya" htmlFor="rev-lama">
            <Input id="rev-lama" value={form.old_value}
              onChange={e => f('old_value', e.target.value)} placeholder="Kondisi lama" />
          </Isian>
          <Isian label="Nilai baru" htmlFor="rev-baru">
            <Input id="rev-baru" value={form.new_value}
              onChange={e => f('new_value', e.target.value)} placeholder="Kondisi baru" />
          </Isian>
        </div>
        <Isian label="Catatan tambahan" htmlFor="rev-catatan">
          <Input id="rev-catatan" value={form.notes} onChange={e => f('notes', e.target.value)} />
        </Isian>
      </FormPopup>

      {compare && (
        <RnDRevisionCompare
          token={token}
          styleId={compare.styleId}
          initialLeft={compare.left}
          onClose={() => setCompare(null)}
        />
      )}
    </PageLayout>
  );
}
