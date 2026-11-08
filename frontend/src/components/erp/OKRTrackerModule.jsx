/**
 * OKR Tracker (Portal Manajemen) — objective & key result strategis (kuartalan / tahunan) dengan progres dan kondisi.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (1 tombol utama, pilihan periode di `filters`, unduh di `tools`),
 * kartu angka StatTile (maks. 4), daftar objective = tabel (dulu kartu berulang), form buat objective & ubah nilai KR =
 * FormPopup (isian & simpan sama), detail = DetailPopup, arsip lewat confirmDialog (dulu window.confirm), label
 * berbahasa Indonesia (dulu On Track/At Risk/critical…), warna lewat StatusBadge.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { DepartmentSelect } from './hr/hrPickers';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';
import { Target, Plus, Loader2, Trash2, Pencil } from 'lucide-react';

const PRIORITY_OPTIONS = [
  { value: 'low', label: 'Rendah' },
  { value: 'medium', label: 'Sedang' },
  { value: 'high', label: 'Tinggi' },
  { value: 'critical', label: 'Kritis' },
];
const PRIORITY_LABEL = Object.fromEntries(PRIORITY_OPTIONS.map((o) => [o.value, o.label]));
const PRIORITY_TONE = { critical: 'danger', high: 'warning', medium: 'info', low: 'muted' };

/* 2026-11-07 (Tahap 5) — periode OKR dipilih dari daftar (tahun · semester · kuartal), bukan diketik:
   ejaan bebas ("Q1 2026", "2026 Q1") membuat satu periode terpecah di saringan & dasbor. */
function okrPeriodOptions(existing = []) {
  const y = new Date().getFullYear();
  const out = [];
  for (const yr of [y - 1, y, y + 1]) {
    out.push(String(yr), `${yr}-H1`, `${yr}-H2`, `${yr}-Q1`, `${yr}-Q2`, `${yr}-Q3`, `${yr}-Q4`);
  }
  return [...new Set([...out, ...existing.filter(Boolean)])];
}
const okrPeriodLabel = (p) => {
  const m = /^(\d{4})(?:-(H|Q)(\d))?$/.exec(p || '');
  if (!m) return p || '—';
  if (!m[2]) return `Tahun ${m[1]}`;
  return m[2] === 'H' ? `Semester ${m[3]} ${m[1]}` : `Kuartal ${m[3]} ${m[1]}`;
};

const HEALTH_LABEL = {
  on_track: 'Sesuai jalur',
  at_risk: 'Berisiko',
  off_track: 'Melenceng',
  completed: 'Selesai',
};
const HEALTH_TONE = { on_track: 'success', at_risk: 'warning', off_track: 'danger', completed: 'info' };

const METRIC_TYPES = [
  { value: 'number', label: 'Angka' },
  { value: 'percentage', label: 'Persen (%)' },
  { value: 'currency', label: 'Rupiah (Rp)' },
  { value: 'binary', label: 'Selesai / belum' },
];

const fmtAngka = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 });
function formatMetricValue(val, type) {
  if (val == null) return '—';
  if (type === 'currency') return `Rp ${Number(val).toLocaleString('id-ID')}`;
  if (type === 'percentage') return `${Number(val).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
  return Number(val).toLocaleString('id-ID');
}

export default function OKRTrackerModule({ token }) {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [period, setPeriod] = useState('');
  const [periods, setPeriods] = useState([]);
  const [objectives, setObjectives] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false);

  // create-objective dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({
    title: '',
    description: '',
    period: '',
    department: '',
    owner_id: '',
    owner_name: '',
    priority: 'medium',
    key_results: [{ title: '', metric_type: 'number', target_value: 100, current_value: 0, unit: '' }],
  });

  // penanggung jawab dipilih dari daftar pengguna (owner_id + owner_name), bukan diketik
  const [users, setUsers] = useState([]);
  // detail dialog
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [editingKRId, setEditingKRId] = useState(null);
  const [krEdit, setKrEdit] = useState({ current_value: 0 });

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );
  const BASE = process.env.REACT_APP_BACKEND_URL;

  const fetchPeriods = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/management/okr/periods`, { headers });
      const data = await r.json();
      const arr = data?.data || [];
      setPeriods(arr);
    } catch (e) {
      console.error(e);
    }
  }, [BASE, headers]);

  const fetchDashboard = useCallback(async () => {
    try {
      const q = period ? `?period=${encodeURIComponent(period)}` : '';
      const r = await fetch(`${BASE}/api/management/okr/dashboard${q}`, { headers });
      const data = await r.json();
      setDashboard(data?.data || null);
    } catch (e) {
      console.error(e);
      toast.error('Gagal memuat ringkasan OKR');
    }
  }, [BASE, headers, period]);

  const fetchObjectives = useCallback(async () => {
    try {
      const q = period ? `?period=${encodeURIComponent(period)}` : '';
      const r = await fetch(`${BASE}/api/management/okr/objectives${q}`, { headers });
      const data = await r.json();
      setObjectives(data?.data || []);
    } catch (e) {
      console.error(e);
    }
  }, [BASE, headers, period]);

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchPeriods(), fetchDashboard(), fetchObjectives()]).finally(() => setLoading(false));
  }, [fetchPeriods, fetchDashboard, fetchObjectives]);

  useEffect(() => {
    if (!createOpen || users.length) return;
    fetch(`${BASE}/api/auth/users?limit=500`, { headers })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setUsers(Array.isArray(d) ? d : (d.items || d.users || [])))
      .catch(() => setUsers([]));
  }, [createOpen, users.length, BASE, headers]);

  // ───────────────────── Handlers ─────────────────────
  const addKRRow = () => {
    setForm((f) => ({
      ...f,
      key_results: [...f.key_results, { title: '', metric_type: 'number', target_value: 100, current_value: 0, unit: '' }],
    }));
  };

  const updateKR = (i, key, val) => {
    setForm((f) => {
      const krs = [...f.key_results];
      krs[i] = { ...krs[i], [key]: val };
      return { ...f, key_results: krs };
    });
  };

  const removeKR = (i) => {
    setForm((f) => ({ ...f, key_results: f.key_results.filter((_, idx) => idx !== i) }));
  };

  const handleCreate = async () => {
    if (!form.title?.trim()) {
      toast.error('Judul objective wajib diisi');
      return;
    }
    if (!form.period?.trim()) {
      toast.error('Periode wajib dipilih');
      return;
    }
    if (!form.key_results.length || form.key_results.some((kr) => !kr.title?.trim())) {
      toast.error('Tambahkan minimal 1 key result dengan judul');
      return;
    }
    try {
      const r = await fetch(`${BASE}/api/management/okr/objectives`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          ...form,
          key_results: form.key_results.map((kr) => ({
            ...kr,
            target_value: Number(kr.target_value) || 0,
            current_value: Number(kr.current_value) || 0,
          })),
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(typeof d.detail === 'string' ? d.detail : `HTTP ${r.status}`);
      }
      const created = await r.json();
      const newPeriod = created?.data?.period || form.period;
      toast.success('Objective berhasil dibuat');
      setCreateOpen(false);
      setForm({
        title: '',
        description: '',
        period: '',
        department: '',
        owner_id: '',
        owner_name: '',
        priority: 'medium',
        key_results: [{ title: '', metric_type: 'number', target_value: 100, current_value: 0, unit: '' }],
      });
      // Selaraskan filter periode ke objective yang baru dibuat agar langsung tampil di list.
      // Bila periode berubah, useEffect memuat ulang otomatis; panggilan langsung menutup kasus periode sama.
      setPeriod(newPeriod);
      fetchPeriods();
      fetchObjectives();
      fetchDashboard();
    } catch (e) {
      toast.error(`Gagal: ${e.message}`);
    }
  };

  const openDetail = async (obj) => {
    try {
      const r = await fetch(`${BASE}/api/management/okr/objectives/${obj.id}`, { headers });
      const data = await r.json();
      setDetail(data?.data || obj);
      setDetailOpen(true);
    } catch (e) {
      console.error(e);
      setDetail(obj);
      setDetailOpen(true);
    }
  };

  const beginEditKR = (kr) => {
    setEditingKRId(kr.id);
    setKrEdit({ current_value: kr.current_value, notes: kr.notes || '' });
  };

  const saveKR = async (kr) => {
    try {
      const r = await fetch(`${BASE}/api/management/okr/key-results/${kr.id}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({
          current_value: Number(krEdit.current_value) || 0,
          notes: krEdit.notes,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success('Nilai key result disimpan.');
      setEditingKRId(null);
      openDetail(detail);
      fetchObjectives();
      fetchDashboard();
    } catch (e) {
      toast.error(`Gagal menyimpan: ${e.message}`);
    }
  };

  const archiveObjective = async (id) => {
    const ok = await confirmDialog({
      title: 'Arsipkan objective ini?', body: 'Objective tidak tampil lagi di daftar dan ringkasan.', confirmLabel: 'Arsipkan', danger: true,
    });
    if (!ok) return;
    try {
      const r = await fetch(`${BASE}/api/management/okr/objectives/${id}`, { method: 'DELETE', headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success('Objective diarsipkan.');
      setDetailOpen(false);
      fetchObjectives();
      fetchDashboard();
    } catch (e) {
      toast.error(`Gagal: ${e.message}`);
    }
  };

  // ───────────────────── Render ─────────────────────
  const periodeOpsi = [...new Set([...(periods || []), period].filter(Boolean))];
  const kolomUnduh = [
    { label: 'Objective', nilai: (o) => o.title },
    { label: 'Periode', nilai: (o) => okrPeriodLabel(o.period) },
    { label: 'Departemen', nilai: (o) => o.department || '' },
    { label: 'Penanggung jawab', nilai: (o) => o.owner_name || '' },
    { label: 'Prioritas', nilai: (o) => PRIORITY_LABEL[o.priority] || '' },
    { label: 'Kondisi', nilai: (o) => HEALTH_LABEL[o.health] || '' },
    { label: 'Jumlah KR', nilai: (o) => (typeof o.key_results_count === 'number' ? o.key_results_count : '') },
    { label: 'Progres (%)', nilai: (o) => Number((o.progress ?? 0).toFixed(1)) },
  ];
  const tutupForm = () => setCreateOpen(false);

  return (
    <PageLayout
      testId="okr-tracker"
      title="OKR Tracker"
      subtitle="Objective dan key result strategis (kuartalan/tahunan) beserta progres dan kondisinya."
      actions={<Button onClick={() => setCreateOpen(true)} data-testid="okr-create-btn"><Plus />Objective baru</Button>}
      filters={(
        <SmartNativeSelect value={period} onChange={(e) => setPeriod(e.target.value)} searchable={false}
          className="h-9 w-48" aria-label="Periode" data-testid="okr-period-filter">
          <option value="">Semua periode</option>
          {periodeOpsi.map((p) => <option key={p} value={p}>{okrPeriodLabel(p)}</option>)}
        </SmartNativeSelect>
      )}
      tools={(
        <TombolUnduh namaBerkas="okr-objective" namaLembar="Objective" baris={objectives} kolom={kolomUnduh} testId="okr-unduh" />
      )}
    >
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="h-auto w-auto flex-wrap justify-start">
          <TabsTrigger value="dashboard" data-testid="okr-tab-dashboard">Ringkasan</TabsTrigger>
          <TabsTrigger value="objectives" data-testid="okr-tab-objectives">Daftar objective</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard" className="mt-0 space-y-4">
          {loading || !dashboard ? (
            <p className="py-6 text-center text-sm text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Memuat…</p>
          ) : dashboard.total_objectives === 0 ? (
            <EmptyState icon={Target} title="Belum ada objective" description="Buat objective pertama untuk mulai memantau progres."
              action={<Button onClick={() => setCreateOpen(true)}><Plus />Buat objective</Button>} />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
                <StatTile label="Total objective" value={fmtAngka(dashboard.total_objectives)}
                  sub={`Rata-rata progres ${fmtAngka(dashboard.average_progress)}%${dashboard.completed ? ` · ${fmtAngka(dashboard.completed)} selesai` : ''}`} />
                <StatTile label="Sesuai jalur" value={fmtAngka(dashboard.on_track)} accent={dashboard.on_track ? 'success' : 'default'} />
                <StatTile label="Berisiko" value={fmtAngka(dashboard.at_risk)} accent={dashboard.at_risk ? 'warning' : 'default'} />
                <StatTile label="Melenceng" value={fmtAngka(dashboard.off_track)} accent={dashboard.off_track ? 'danger' : 'default'} />
              </div>

              {dashboard.by_department?.length > 0 && (
                <GlassCard className="space-y-3 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="text-base font-semibold text-foreground">Per departemen</p>
                    <TombolUnduh namaBerkas="okr-per-departemen" namaLembar="Per departemen" baris={dashboard.by_department} testId="okr-dept-unduh"
                      kolom={[
                        { label: 'Departemen', nilai: (d) => d.department },
                        { label: 'Objective', nilai: (d) => d.total },
                        { label: 'Prioritas kritis', nilai: (d) => d.critical_count },
                        { label: 'Rata-rata progres (%)', nilai: (d) => d.average_progress },
                      ]} />
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Departemen</TableHead>
                        <TableHead className="text-right">Objective</TableHead>
                        <TableHead className="hidden text-right sm:table-cell">Kritis</TableHead>
                        <TableHead className="w-1/3">Rata-rata progres</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {dashboard.by_department.map((d) => (
                        <TableRow key={d.department}>
                          <TableCell className="font-medium">{d.department}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtAngka(d.total)}</TableCell>
                          <TableCell className="hidden text-right tabular-nums sm:table-cell">{fmtAngka(d.critical_count)}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Progress value={d.average_progress} className="h-1.5 flex-1" />
                              <span className="w-12 text-right text-sm tabular-nums">{fmtAngka(d.average_progress)}%</span>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </GlassCard>
              )}

              {dashboard.top_objectives?.length > 0 && (
                <GlassCard className="space-y-3 p-4">
                  <p className="text-base font-semibold text-foreground">Objective teratas</p>
                  <TabelObjective baris={dashboard.top_objectives} onBuka={openDetail} />
                </GlassCard>
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="objectives" className="mt-0">
          <TabelObjective baris={objectives} onBuka={openDetail}
            kosong={<EmptyState icon={Target} title="Belum ada objective" description={period ? 'Tidak ada objective di periode ini.' : 'Buat objective pertama untuk mulai memantau progres.'} />} />
        </TabsContent>
      </Tabs>

      {/* Form buat objective — popup panjang (isian & simpan sama seperti sebelumnya) */}
      <FormPopup open={createOpen} onClose={tutupForm} ukuran="panjang" judul="Buat objective dan key result"
        keterangan="Objective = tujuan; key result = ukuran keberhasilannya." onSimpan={handleCreate} labelSimpan="Simpan objective"
        testId="okr-form">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Isian label="Judul objective" wajib htmlFor="okr-judul">
            <Input id="okr-judul" data-testid="okr-form-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Mis. Tingkatkan pendapatan 20% kuartal 1 2026" />
          </Isian>
          <Isian label="Periode" wajib htmlFor="okr-periode">
            <SmartNativeSelect id="okr-periode" data-testid="okr-form-period" className="w-full" value={form.period}
              onChange={(e) => setForm({ ...form, period: e.target.value })}>
              <option value="">— pilih periode —</option>
              {okrPeriodOptions(periods).map((p) => <option key={p} value={p}>{okrPeriodLabel(p)}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Deskripsi" htmlFor="okr-deskripsi">
          <Textarea id="okr-deskripsi" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2}
            placeholder="Penjelasan dan konteks objective…" />
        </Isian>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Isian label="Departemen">
            {/* 2026-11-07 (OR1): departemen dari Struktur Organisasi (satu daftar untuk semua formulir) */}
            <DepartmentSelect token={token} value={form.department} testId="okr-form-department"
              className="w-full" onChange={(v) => setForm((f) => ({ ...f, department: v }))} />
          </Isian>
          <Isian label="Penanggung jawab">
            <SmartNativeSelect data-testid="okr-form-owner" className="w-full" value={form.owner_id}
              onChange={(e) => {
                const u = users.find((x) => x.id === e.target.value);
                setForm({ ...form, owner_id: e.target.value, owner_name: u ? (u.name || u.email) : '' });
              }}>
              <option value="">— belum ditentukan —</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}{u.role ? ` (${String(u.role).replace(/_/g, ' ')})` : ''}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Prioritas">
            <SmartNativeSelect value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} searchable={false}
              className="w-full" data-testid="okr-form-priority">
              {PRIORITY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>

        <div className="space-y-3 border-t border-[var(--glass-border)] pt-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-foreground">Key result ({form.key_results.length})</p>
            <Button type="button" size="sm" variant="outline" onClick={addKRRow}><Plus />Tambah key result</Button>
          </div>
          {form.key_results.map((kr, i) => (
            <div key={i} className="space-y-3 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-muted-foreground">Key result {i + 1}</span>
                {form.key_results.length > 1 && (
                  <Button type="button" variant="ghost" size="icon-sm" onClick={() => removeKR(i)} title="Hapus key result" aria-label="Hapus key result">
                    <Trash2 />
                  </Button>
                )}
              </div>
              <Input data-testid={`okr-form-kr-title-${i}`} value={kr.title} onChange={(e) => updateKR(i, 'title', e.target.value)}
                placeholder="Judul key result (mis. Pendapatan Rp 500 jt/bulan)" aria-label={`Judul key result ${i + 1}`} />
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Isian label="Jenis ukuran">
                  <SmartNativeSelect value={kr.metric_type} onChange={(e) => updateKR(i, 'metric_type', e.target.value)} searchable={false} className="w-full">
                    {METRIC_TYPES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </SmartNativeSelect>
                </Isian>
                <Isian label="Target">
                  <Input type="number" value={kr.target_value} onChange={(e) => updateKR(i, 'target_value', e.target.value)} />
                </Isian>
                <Isian label="Saat ini">
                  <Input type="number" value={kr.current_value} onChange={(e) => updateKR(i, 'current_value', e.target.value)} />
                </Isian>
                <Isian label="Satuan">
                  <Input value={kr.unit || ''} onChange={(e) => updateKR(i, 'unit', e.target.value)} placeholder="%, Rp, pcs" />
                </Isian>
              </div>
            </div>
          ))}
        </div>
      </FormPopup>

      {/* Detail objective — popup */}
      {detailOpen && detail && (
        <DetailPopup open onClose={() => setDetailOpen(false)} judul={detail.title} testId="okr-detail"
          keterangan={[okrPeriodLabel(detail.period), detail.department, detail.owner_name ? `Penanggung jawab ${detail.owner_name}` : null].filter(Boolean).join(' · ')}
          status={<>
            {detail.priority && <StatusBadge status={detail.priority} label={`Prioritas ${(PRIORITY_LABEL[detail.priority] || detail.priority).toLowerCase()}`} tone={PRIORITY_TONE[detail.priority]} />}
            {detail.health && <StatusBadge status={detail.health} label={HEALTH_LABEL[detail.health] || detail.health} tone={HEALTH_TONE[detail.health]} />}
          </>}
          aksi={<Button size="sm" variant="destructive" onClick={() => archiveObjective(detail.id)} data-testid="okr-archive"><Trash2 />Arsipkan</Button>}>
          {detail.description && <p className="text-sm text-muted-foreground">{detail.description}</p>}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-foreground">Progres keseluruhan</span>
              <span className="font-semibold tabular-nums">{fmtAngka(detail.progress ?? 0)}%</span>
            </div>
            <Progress value={detail.progress || 0} className="h-2" />
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Key result ({(detail.key_results || []).length})</p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key result</TableHead>
                  <TableHead className="text-right">Saat ini / target</TableHead>
                  <TableHead className="hidden w-40 sm:table-cell">Progres</TableHead>
                  <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(detail.key_results || []).map((kr) => {
                  const progress = kr.target_value > 0 ? Math.min(100, (kr.current_value / kr.target_value) * 100) : (kr.current_value > 0 ? 100 : 0);
                  return (
                    <TableRow key={kr.id}>
                      <TableCell>{kr.title}{kr.notes && <span className="block text-xs text-muted-foreground">{kr.notes}</span>}</TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {formatMetricValue(kr.current_value, kr.metric_type)} / {formatMetricValue(kr.target_value, kr.metric_type)}
                        {kr.unit && kr.metric_type !== 'currency' && kr.metric_type !== 'percentage' ? ` ${kr.unit}` : ''}
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <div className="flex items-center gap-2"><Progress value={progress} className="h-1.5 flex-1" /><span className="w-10 text-right text-sm tabular-nums">{progress.toFixed(0)}%</span></div>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" variant="outline" onClick={() => beginEditKR(kr)} data-testid={`okr-edit-kr-${kr.id}`}><Pencil />Ubah</Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </DetailPopup>
      )}

      {/* Ubah nilai key result — popup pendek */}
      <FormPopup open={!!editingKRId} onClose={() => setEditingKRId(null)} judul="Ubah nilai key result"
        keterangan={(detail?.key_results || []).find((k) => k.id === editingKRId)?.title}
        onSimpan={() => { const kr = (detail?.key_results || []).find((k) => k.id === editingKRId); if (kr) saveKR(kr); }}
        testId="okr-kr-form">
        <Isian label="Nilai saat ini" htmlFor="okr-kr-nilai">
          <Input id="okr-kr-nilai" type="number" value={krEdit.current_value} onChange={(e) => setKrEdit({ ...krEdit, current_value: e.target.value })} />
        </Isian>
        <Isian label="Catatan" htmlFor="okr-kr-catatan" petunjuk="Opsional.">
          <Input id="okr-kr-catatan" value={krEdit.notes || ''} onChange={(e) => setKrEdit({ ...krEdit, notes: e.target.value })} />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}

/** Daftar objective = tabel (dulu kartu berulang); klik baris membuka detail. */
function TabelObjective({ baris, onBuka, kosong = null }) {
  return (
    <TabelData baris={baris} onKlikBaris={onBuka} kosong={kosong} testId="okr-objective-tabel"
      kolom={[
        { kunci: 'title', label: 'Objective', hp: 'judul', isi: (o) => (
          <span className="block min-w-0 md:max-w-[22rem]" data-testid={`okr-obj-row-${o.id}`}>
            <span className="block truncate font-medium text-foreground" title={o.title}>{o.title}</span>
            {o.description && <span className="hidden truncate text-xs text-muted-foreground md:block">{o.description}</span>}
          </span>) },
        { kunci: 'period', label: 'Periode', hp: 'keterangan', isi: (o) => okrPeriodLabel(o.period) },
        { kunci: 'department', label: 'Departemen', isi: (o) => o.department || '—' },
        { kunci: 'owner', label: 'Penanggung jawab', isi: (o) => o.owner_name || '—' },
        { kunci: 'priority', label: 'Prioritas', isi: (o) => (o.priority
          ? <StatusBadge status={o.priority} label={PRIORITY_LABEL[o.priority] || o.priority} tone={PRIORITY_TONE[o.priority]} /> : '—') },
        { kunci: 'health', label: 'Kondisi', isi: (o) => (o.health
          ? <StatusBadge status={o.health} label={HEALTH_LABEL[o.health] || o.health} tone={HEALTH_TONE[o.health]} /> : '—') },
        { kunci: 'progress', label: 'Progres', rata: 'kanan', isi: (o) => (
          <span className="inline-flex w-32 items-center gap-2"><Progress value={o.progress || 0} className="h-1.5 flex-1" />
            <span className="w-10 text-right tabular-nums">{(o.progress ?? 0).toFixed(0)}%</span></span>) },
      ]} />
  );
}
