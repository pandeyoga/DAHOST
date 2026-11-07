/**
 * Tindak lanjut AI (Portal SDM › AI SDM) — rekomendasi AI yang disimpan sebagai tugas dan dipantau sampai selesai.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar tugas = tabel + unduh Excel/CSV (dulu kartu
 * berulang), status = pil berjumlah, form = FormPopup, hapus = confirmDialog (dulu window.confirm), tenggat =
 * DatePicker, kartu angka StatTile (dulu 5 kotak berwarna + huruf kapital), bahasa Indonesia.
 * Pemilih penanggung jawab dulu diam-diam 100 karyawan pertama — kini semua (bisa dicari).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { CheckCircle2, ChevronDown, Clock, Edit2, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import { todayWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_CFG = {
  open:        { label: 'Terbuka',    tone: 'info' },
  in_progress: { label: 'Dikerjakan', tone: 'warning' },
  done:        { label: 'Selesai',    tone: 'success' },
  dismissed:   { label: 'Diabaikan',  tone: 'muted' },
};
const PRIORITY_CFG = {
  low:      { label: 'Rendah', tone: 'muted' },
  medium:   { label: 'Sedang', tone: 'info' },
  high:     { label: 'Tinggi', tone: 'warning' },
  critical: { label: 'Kritis', tone: 'danger' },
};
const SOURCE_CFG = {
  'daily-summary':    { label: 'Ringkasan harian' },
  'root-cause':       { label: 'Akar masalah' },
  'predictive-delay': { label: 'Prediksi keterlambatan' },
  'chat':             { label: 'Obrolan AI' },
  'manual':           { label: 'Manual' },
};
const Lencana = ({ cfg, kunci }) => {
  const c = cfg[kunci] || { label: kunci || '—', tone: 'default' };
  return <StatusBadge status={kunci} label={c.label} tone={c.tone} />;
};

export default function AIActionsModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [items, setItems] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [stats, setStats] = useState({});
  const [tab, setTab] = useState('open');
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [editDialog, setEditDialog] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const statusParam = tab === 'all' ? '' : `status=${tab}`;
      const srcParam = sourceFilter ? `&source=${sourceFilter}` : '';
      const [r1, r2, r3] = await Promise.all([
        fetch(`${API}/api/dewi/ai-actions?${statusParam}${srcParam}`, { headers }),
        // FASE 20 — dulu '/api/rahaza/master/employees' (tidak pernah ada di backend
        // ⇒ 404 senyap). Endpoint yang benar mengembalikan {total, items:[...]},
        // jadi `items` WAJIB ikut dibaca — kalau tidak, dropdown karyawan tetap
        // kosong walau HTTP-nya 200.
        fetch(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers }),
        fetch(`${API}/api/dewi/ai-actions/stats`, { headers }),
      ]);
      const d1 = await r1.json();
      const d2 = await r2.json();
      const d3 = await r3.json();
      setItems(d1.actions || []);
      setEmployees(Array.isArray(d2) ? d2 : d2.items || d2.rows || d2.employees || []);
      setStats(d3 || {});
    } catch (e) {
      toast.error('Gagal memuat: ' + (e.message || e));
    } finally { setLoading(false); }
  }, [headers, tab, sourceFilter]);

  useEffect(() => { load(); }, [load]);

  const handleSave = async (form) => {
    const isEdit = !!form.action_id;
    const url = isEdit
      ? `${API}/api/dewi/ai-actions/${form.action_id}`
      : `${API}/api/dewi/ai-actions`;
    const r = await fetch(url, { method: isEdit ? 'PUT' : 'POST', headers, body: JSON.stringify(form) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast.error(d.detail || 'Gagal menyimpan'); return; }
    toast.success(isEdit ? 'Tugas disimpan' : 'Tugas dibuat');
    setEditDialog(null);
    load();
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus tugas ini?', confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(`${API}/api/dewi/ai-actions/${id}`, { method: 'DELETE', headers });
    if (!r.ok) { toast.error('Gagal menghapus'); return; }
    toast.success('Tugas dihapus');
    load();
  };

  const handleStatusChange = async (action, newStatus) => {
    const r = await fetch(`${API}/api/dewi/ai-actions/${action.action_id}`, {
      method: 'PUT', headers, body: JSON.stringify({ status: newStatus }),
    });
    if (!r.ok) { toast.error('Gagal mengubah status'); return; }
    toast.success(`Status: ${STATUS_CFG[newStatus]?.label}`);
    load();
  };

  const filtered = items.filter(a =>
    search
      ? a.title.toLowerCase().includes(search.toLowerCase()) ||
        (a.description || '').toLowerCase().includes(search.toLowerCase())
      : true
  );

  const today = todayWIB();
  const lewat = (a) => a.due_date && a.due_date < today && !['done', 'dismissed'].includes(a.status);
  const semua = ['open', 'in_progress', 'done', 'dismissed'].reduce((n, k) => n + (stats[k] || 0), 0);

  const kolom = [
    { kunci: 'judul', label: 'Tugas', hp: 'judul', isi: (a) => (
      <div className="min-w-0 md:max-w-[24rem]" data-testid={`action-card-${a.action_id}`}>
        <p className="font-medium text-foreground">{a.title}</p>
        {a.description && <p className="hidden truncate text-xs text-muted-foreground md:block" title={a.description}>{a.description}</p>}
      </div>) },
    { kunci: 'sumber', label: 'Sumber', isi: (a) => <span className="text-sm">{(SOURCE_CFG[a.source] || SOURCE_CFG.manual).label}</span> },
    { kunci: 'prioritas', label: 'Prioritas', isi: (a) => <Lencana cfg={PRIORITY_CFG} kunci={a.priority || 'medium'} /> },
    { kunci: 'pj', label: 'Penanggung jawab', isi: (a) => <span className="text-sm">{a.assignee_name || '—'}</span> },
    { kunci: 'tenggat', label: 'Tenggat', isi: (a) => (
      <span className={`text-sm md:whitespace-nowrap ${lewat(a) ? 'font-medium text-[hsl(var(--danger-text))]' : ''}`}>
        {a.due_date ? formatDateID(a.due_date) : '—'}{lewat(a) ? ' · lewat' : ''}
      </span>) },
    { kunci: 'status', label: 'Status', isi: (a) => <Lencana cfg={STATUS_CFG} kunci={a.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => (
      <div className="flex justify-end gap-2">
        {a.status === 'open' && (
          <Button size="sm" variant="outline" onClick={() => handleStatusChange(a, 'in_progress')} data-testid={`action-start-${a.action_id}`}>
            <Clock />Mulai
          </Button>
        )}
        {a.status === 'in_progress' && (
          <Button size="sm" variant="success" onClick={() => handleStatusChange(a, 'done')} data-testid={`action-done-${a.action_id}`}>
            <CheckCircle2 />Selesai
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="ghost" aria-label="Aksi lainnya" title="Aksi lainnya">Lainnya<ChevronDown /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {a.status === 'open' && (
              <DropdownMenuItem onSelect={() => handleStatusChange(a, 'done')}><CheckCircle2 className="mr-2 h-4 w-4" />Tandai selesai</DropdownMenuItem>
            )}
            {a.status !== 'dismissed' && a.status !== 'done' && (
              <DropdownMenuItem onSelect={() => handleStatusChange(a, 'dismissed')} data-testid={`action-dismiss-${a.action_id}`}>
                <X className="mr-2 h-4 w-4" />Abaikan
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => setEditDialog(a)}><Edit2 className="mr-2 h-4 w-4" />Ubah</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => handleDelete(a.action_id)} className="text-[hsl(var(--danger-text))]">
              <Trash2 className="mr-2 h-4 w-4" />Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  return (
    <PageLayout testId="ai-actions-page" title="Tindak lanjut AI"
      subtitle="Rekomendasi AI yang disimpan sebagai tugas dan dipantau sampai selesai."
      actions={<Button onClick={() => setEditDialog({})} data-testid="ai-actions-add"><Plus />Tugas manual</Button>}
      filters={<>
        <FilterChips value={tab} onChange={setTab} hideWhenEmpty={false} testId="ai-actions-status" ariaLabel="Status tugas"
          options={[
            { key: 'open', label: 'Terbuka', count: stats.open || 0 },
            { key: 'in_progress', label: 'Dikerjakan', count: stats.in_progress || 0 },
            { key: 'done', label: 'Selesai', count: stats.done || 0 },
            { key: 'dismissed', label: 'Diabaikan', count: stats.dismissed || 0 },
            { key: 'all', label: 'Semua', count: semua },
          ]} />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari tugas" className="pl-8" />
        </div>
        <SmartNativeSelect searchable={false} value={sourceFilter} onChange={e => setSourceFilter(e.target.value)} className="w-48" aria-label="Sumber">
          <option value="">Semua sumber</option>
          {Object.entries(SOURCE_CFG).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="tindak-lanjut-ai" namaLembar="Tugas" baris={filtered} testId="ai-actions-unduh"
          kolom={[
            { label: 'Tugas', nilai: (a) => a.title }, { label: 'Deskripsi', nilai: (a) => a.description || '' },
            { label: 'Sumber', nilai: (a) => (SOURCE_CFG[a.source] || SOURCE_CFG.manual).label },
            { label: 'Prioritas', nilai: (a) => PRIORITY_CFG[a.priority]?.label || '' },
            { label: 'Penanggung jawab', nilai: (a) => a.assignee_name || '' },
            { label: 'Tenggat', nilai: (a) => (a.due_date ? formatDateID(a.due_date) : '') },
            { label: 'Status', nilai: (a) => STATUS_CFG[a.status]?.label || a.status || '' },
            { label: 'Catatan', nilai: (a) => a.notes || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="ai-actions-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Terbuka" value={stats.open || 0} sub="Belum mulai dikerjakan." />
          <StatTile label="Dikerjakan" value={stats.in_progress || 0} sub="Sedang berjalan." />
          <StatTile label="Tenggat ≤ 3 hari" value={stats.due_soon || 0} accent={stats.due_soon ? 'warning' : 'default'}
            sub="Terbuka/dikerjakan, tenggat hari ini sampai 3 hari lagi." />
          <StatTile label="Lewat tenggat" value={stats.overdue || 0} accent={stats.overdue ? 'danger' : 'default'}
            sub="Terbuka/dikerjakan, tenggat sudah lewat." />
        </div>
      }>
      {loading && items.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat tugas…</p> : (
        <TabelData kolom={kolom} baris={filtered} kunci={(a) => a.action_id} onKlikBaris={setEditDialog} testId="ai-actions"
          kosong={<EmptyState title="Belum ada tugas di kategori ini"
            description='Pakai tombol "Jadikan tugas" di tab Wawasan AI untuk menyimpan rekomendasi AI.' />} />
      )}

      {editDialog !== null && (
        <ActionDialog initial={editDialog} employees={employees} onSave={handleSave} onClose={() => setEditDialog(null)} />
      )}
    </PageLayout>
  );
}

function ActionDialog({ initial, employees, onSave, onClose }) {
  const [form, setForm] = useState({
    title: '',
    description: '',
    source: 'manual',
    priority: 'medium',
    assignee_id: '',
    due_date: '',
    notes: '',
    ...initial,
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.title.trim()) { toast.error('Judul wajib diisi'); return; }
    setSaving(true);
    await onSave(form);
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={submit} menyimpan={saving} testId="ai-action-form"
      judul={form.action_id ? 'Ubah tugas' : 'Tugas AI baru'}>
      <Isian label="Judul" wajib htmlFor="ai-act-judul">
        <Input id="ai-act-judul" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
          placeholder="Contoh: Selidiki rasio gagal QC line A" required data-testid="action-title" />
      </Isian>
      <Isian label="Deskripsi / rekomendasi AI" htmlFor="ai-act-desk">
        <Textarea id="ai-act-desk" value={form.description} rows={4} placeholder="Tempel rekomendasi AI di sini"
          onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Prioritas">
          <SmartNativeSelect searchable={false} value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}>
            {Object.entries(PRIORITY_CFG).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Sumber">
          <SmartNativeSelect searchable={false} value={form.source} onChange={e => setForm(f => ({ ...f, source: e.target.value }))}>
            {Object.entries(SOURCE_CFG).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Penanggung jawab">
          <SmartNativeSelect value={form.assignee_id || ''} searchable onChange={e => {
            const id = e.target.value;
            const emp = employees.find(x => x.id === id);
            setForm(f => ({ ...f, assignee_id: id, assignee_name: emp?.name || '' }));
          }}>
            <option value="">— Tidak ditugaskan —</option>
            {employees.map(e => <option key={e.id} value={e.id}>{`${e.employee_code} — ${e.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tenggat (opsional)">
          <DatePicker value={form.due_date} onChange={v => setForm(f => ({ ...f, due_date: v }))} placeholder="Tanpa tenggat" testId="ai-act-tenggat" />
        </Isian>
        {form.action_id && (
          <Isian label="Status">
            <SmartNativeSelect searchable={false} value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value }))}>
              {Object.entries(STATUS_CFG).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}
            </SmartNativeSelect>
          </Isian>
        )}
      </div>
      <Isian label="Catatan" htmlFor="ai-act-catatan">
        <Textarea id="ai-act-catatan" value={form.notes} rows={2} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
      </Isian>
    </FormPopup>
  );
}
