/**
 * HROrgChartModule — Portal SDM › Struktur Organisasi: bagan unit, daftar unit, jabatan, dan target karyawan.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026; owner menunjuk layar ini: ruang kosong, kartu boros tempat):
 *  • cetakan PageLayout: kepala tipis, tab di baris penyaring, 4 kartu angka dengan keterangan;
 *  • bagan = baris rapat bertingkat dalam satu kartu (dulu kotak berwarna per unit), klik → popup detail unit;
 *  • unit / jabatan / target karyawan = TabelData + unduh Excel/CSV; aksi baris Ubah + "Lainnya" (Hapus);
 *  • tab "Target karyawan" tidak lagi mengulang 3 kartu angka (sudah ada di atas) — kini tabel per unit;
 *  • form unit & jabatan = FormPopup pendek; hapus lewat konfirmasi.
 * Kartu "Karyawan Aktual" dulu terbaca sebagai seluruh karyawan aktif, padahal hanya karyawan yang departemennya
 * cocok dengan nama unit → kini "Karyawan di unit" + "dari N karyawan aktif" (N = `total_employees` dari /chart).
 * Data yang dikirim ke server dan alurnya tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, RefreshCw, Pencil, Trash2, MoreHorizontal, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { OrgNode, TypeBadge, TYPE_LABEL, statusTarget } from './OrgNode';
import { EmployeeSelect, useActiveEmployees } from './hr/hrPickers';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = (path, opts = {}) => fetch(`${BACKEND_URL}/api/dewi/org${path}`, opts);

const TYPE_LEVELS = ['company', 'division', 'department', 'team', 'section'];
const UNIT_KOSONG = { name: '', code: '', type: 'department', parent_id: '', head_employee_id: '', head_employee_name: '', headcount_target: 0, color: '', description: '' };
const POS_KOSONG = { title: '', unit_id: '', grade: 1, headcount_target: 1, salary_grade: '' };

export default function HROrgChartModule({ token }) {
  const [tab, setTab] = useState('chart'); // chart | units | positions | headcount
  const [chart, setChart] = useState(null);
  const [units, setUnits] = useState([]);
  const [positions, setPositions] = useState([]);
  const [headcount, setHeadcount] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [seeding, setSeeding] = useState(false);
  const [showUnitForm, setShowUnitForm] = useState(false);
  const [showPosForm, setShowPosForm] = useState(false);
  const [editUnit, setEditUnit] = useState(null);
  const [detailUnit, setDetailUnit] = useState(null);
  const [unitForm, setUnitForm] = useState(UNIT_KOSONG);
  const [posForm, setPosForm] = useState(POS_KOSONG);
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  // Tahap 5 (2026-11-07): kepala unit dipilih dari karyawan aktif (dulu nama diketik bebas);
  // grade gaji jabatan dipilih dari master Struktur Gaji (Pengaturan SDM), dulu diketik bebas.
  const { employees } = useActiveEmployees(token);
  const [salaryGrades, setSalaryGrades] = useState([]);
  useEffect(() => {
    fetch(`${BACKEND_URL}/api/rahaza/salary-grades`, { headers })
      .then(r => (r.ok ? r.json() : {})).then(d => setSalaryGrades(d.grades || [])).catch(() => setSalaryGrades([]));
  }, [headers]);

  const fetchAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [cRes, uRes, pRes, hRes] = await Promise.all([
        API(`/chart`, { headers }),
        API(`/units`, { headers }),
        API(`/positions`, { headers }),
        API(`/headcount`, { headers }),
      ]);
      const [cd, ud, pd, hd] = await Promise.all([cRes.json(), uRes.json(), pRes.json(), hRes.json()]);
      setChart(cd);
      setUnits(ud.units || []);
      setPositions(pd.positions || []);
      setHeadcount(hd);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleSeed = async () => {
    // Tahap 5 (2026-11-07): demo MENGHAPUS seluruh unit & jabatan lalu mengisi data contoh — kini hanya untuk
    // struktur kosong (server menolak bila sudah ada unit) dan selalu dikonfirmasi.
    if (!(await confirmDialog({ title: 'Muat struktur contoh?', body: 'Hanya untuk struktur yang masih kosong. Data contoh bisa diubah atau dihapus setelahnya.', confirmLabel: 'Muat contoh' }))) return;
    setSeeding(true);
    const r = await API(`/seed`, { method: 'POST', headers });
    if (!r.ok) { const d = await r.json().catch(() => ({})); toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal memuat contoh'); }
    setSeeding(false);
    fetchAll();
  };

  const openUnitForm = (u = null) => {
    setDetailUnit(null);
    setGalat('');
    setEditUnit(u);
    setUnitForm(u ? {
      name: u.name, code: u.code, type: u.type, parent_id: u.parent_id || '',
      head_employee_id: u.head_employee_id || '', head_employee_name: u.head_employee_name, headcount_target: u.headcount_target, color: u.color, description: u.description
    } : UNIT_KOSONG);
    setShowUnitForm(true);
  };

  const openPosForm = () => { setGalat(''); setShowPosForm(true); };

  const handleSaveUnit = async () => {
    setSaving(true); setGalat('');
    try {
      const body = { ...unitForm, parent_id: unitForm.parent_id || null };
      const r = editUnit
        ? await API(`/units/${editUnit.unit_id}`, { method: 'PUT', headers, body: JSON.stringify(body) })
        : await API(`/units`, { method: 'POST', headers, body: JSON.stringify(body) });
      // 2026-11-06 (pola P6): dulu form ditutup walau server menolak, tanpa pesan apa pun
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setGalat(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan unit');
        return;
      }
      toast.success(editUnit ? 'Unit disimpan' : 'Unit ditambahkan');
      setShowUnitForm(false);
      fetchAll();
    } catch { setGalat('Gagal menyimpan unit'); } finally { setSaving(false); }
  };

  const handleDeleteUnit = async (u) => {
    if (!(await confirmDialog({ title: `Hapus unit ${u.name}?`, body: 'Unit yang masih punya sub-unit atau jabatan tidak bisa dihapus.', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const r = await API(`/units/${u.unit_id}`, { method: 'DELETE', headers });
      const d = await r.json();
      if (!d.ok) { toast.error(d.detail || 'Tidak bisa dihapus'); return; }
      toast.success('Unit dihapus');
      setDetailUnit(null);
      fetchAll();
    } catch { toast.error('Gagal menghapus unit'); }
  };

  const handleSavePos = async () => {
    setSaving(true); setGalat('');
    try {
      const unit = units.find(u => u.unit_id === posForm.unit_id);
      const body = { ...posForm, unit_name: unit?.name || '' };
      const r = await API(`/positions`, { method: 'POST', headers, body: JSON.stringify(body) });
      // 2026-11-06 (pola P6): dulu form ditutup walau server menolak, tanpa pesan apa pun
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setGalat(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan jabatan');
        return;
      }
      toast.success('Jabatan ditambahkan');
      setShowPosForm(false);
      setPosForm(POS_KOSONG);
      fetchAll();
    } catch { setGalat('Gagal menyimpan jabatan'); } finally { setSaving(false); }
  };

  // RC-UI-03: client-side pagination (10/page) for units & positions tables
  const unitsPg     = useClientPagination(units, 10);
  const positionsPg = useClientPagination(positions, 10);

  const chartTree = chart?.tree ? (Array.isArray(chart.tree) ? chart.tree : [chart.tree]) : [];
  const namaUnit = useMemo(() => Object.fromEntries(units.map(u => [u.unit_id, u.name])), [units]);
  const hcUnits = headcount?.units || [];
  const sum = headcount?.summary || {};
  // Kekurangan = jumlah kekurangan per unit yang belum memenuhi target (unit yang kelebihan tidak menutup kekurangan unit lain).
  const kekurangan = hcUnits.reduce((s, u) => s + Math.max(0, Number(u.gap) || 0), 0);
  const totalAktif = chart?.total_employees;

  // ─── Kolom tabel ────────────────────────────────────────────────────────────
  const aksiUnit = (u) => (
    <div className="flex items-center justify-end gap-1">
      <Button size="sm" variant="outline" onClick={() => openUnitForm(u)} data-testid={`org-unit-edit-${u.unit_id}`}>
        <Pencil />Ubah
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya"><MoreHorizontal /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => handleDeleteUnit(u)} className="text-[hsl(var(--danger-text))]">
            <Trash2 className="mr-2 h-4 w-4" />Hapus unit
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  const kolomUnit = [
    { kunci: 'nama', label: 'Unit', hp: 'judul', isi: (u) => (
      <span className="font-medium text-foreground" style={{ paddingLeft: `${(u.level || 0)}rem` }}>{u.name}</span>) },
    { kunci: 'tipe', label: 'Tipe', isi: (u) => <TypeBadge type={u.type} /> },
    { kunci: 'induk', label: 'Induk', isi: (u) => namaUnit[u.parent_id] || '—' },
    { kunci: 'kepala', label: 'Kepala', isi: (u) => u.head_employee_name || '—' },
    { kunci: 'terisi', label: 'Terisi', rata: 'kanan', isi: (u) => <span className="tabular-nums">{u.headcount_actual || 0}</span> },
    { kunci: 'target', label: 'Target', rata: 'kanan', isi: (u) => <span className="tabular-nums">{u.headcount_target || 0}</span> },
    { kunci: 'status', label: 'Keadaan', isi: (u) => { const s = statusTarget(u.headcount_actual, u.headcount_target); return <StatusBadge status="target" label={s.label} tone={s.tone} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiUnit },
  ];
  const unduhUnit = [
    { label: 'Unit', nilai: (u) => u.name },
    { label: 'Kode', nilai: (u) => u.code || '' },
    { label: 'Tipe', nilai: (u) => TYPE_LABEL[u.type] || '' },
    { label: 'Induk', nilai: (u) => namaUnit[u.parent_id] || '' },
    { label: 'Kepala', nilai: (u) => u.head_employee_name || '' },
    { label: 'Terisi', nilai: (u) => Number(u.headcount_actual || 0) },
    { label: 'Target', nilai: (u) => Number(u.headcount_target || 0) },
    { label: 'Keadaan', nilai: (u) => statusTarget(u.headcount_actual, u.headcount_target).label },
  ];

  const kolomPos = [
    { kunci: 'jabatan', label: 'Jabatan', hp: 'judul', isi: (p) => <span className="font-medium text-foreground">{p.title}</span> },
    { kunci: 'unit', label: 'Unit', hp: 'keterangan', isi: (p) => p.unit_name || '—' },
    { kunci: 'tingkat', label: 'Tingkat', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.grade ?? '—'}</span> },
    { kunci: 'terisi', label: 'Terisi', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.headcount_actual ?? 0}</span> },
    { kunci: 'target', label: 'Target', rata: 'kanan', isi: (p) => <span className="tabular-nums">{p.headcount_target ?? 0}</span> },
    { kunci: 'golongan', label: 'Golongan gaji', isi: (p) => p.salary_grade || '—' },
  ];
  const unduhPos = [
    { label: 'Jabatan', nilai: (p) => p.title },
    { label: 'Unit', nilai: (p) => p.unit_name || '' },
    { label: 'Tingkat', nilai: (p) => (p.grade ?? '') },
    { label: 'Terisi', nilai: (p) => Number(p.headcount_actual || 0) },
    { label: 'Target', nilai: (p) => Number(p.headcount_target || 0) },
    { label: 'Golongan gaji', nilai: (p) => p.salary_grade || '' },
  ];

  const statusHc = (u) => (u.status === 'ok' ? { label: 'Sesuai target', tone: 'success' }
    : u.status === 'under' ? { label: `Kurang ${u.gap}`, tone: 'warning' }
      : { label: `Lebih ${Math.abs(u.gap)}`, tone: 'info' });
  const hcBaris = hcUnits.filter(u => u.target > 0);
  const kolomHc = [
    { kunci: 'unit', label: 'Unit', hp: 'judul', isi: (u) => <span className="font-medium text-foreground">{u.name}</span> },
    { kunci: 'tipe', label: 'Tipe', isi: (u) => <TypeBadge type={u.type} /> },
    { kunci: 'terisi', label: 'Terisi', rata: 'kanan', isi: (u) => <span className="tabular-nums">{u.actual}</span> },
    { kunci: 'target', label: 'Target', rata: 'kanan', isi: (u) => <span className="tabular-nums">{u.target}</span> },
    { kunci: 'persen', label: 'Terpenuhi', rata: 'kanan', isi: (u) => <span className="tabular-nums">{Math.round((u.actual / u.target) * 100)}%</span> },
    { kunci: 'status', label: 'Keadaan', isi: (u) => { const s = statusHc(u); return <StatusBadge status={u.status} label={s.label} tone={s.tone} />; } },
  ];
  const unduhHc = [
    { label: 'Unit', nilai: (u) => u.name },
    { label: 'Tipe', nilai: (u) => TYPE_LABEL[u.type] || '' },
    { label: 'Terisi', nilai: (u) => Number(u.actual || 0) },
    { label: 'Target', nilai: (u) => Number(u.target || 0) },
    { label: 'Terpenuhi (%)', nilai: (u) => Math.round((u.actual / u.target) * 100) },
    { label: 'Keadaan', nilai: (u) => statusHc(u).label },
  ];

  const unduh = {
    chart: <TombolUnduh namaBerkas="struktur-organisasi-unit" namaLembar="Unit" baris={units} kolom={unduhUnit} testId="org-unduh" />,
    units: <TombolUnduh namaBerkas="struktur-organisasi-unit" namaLembar="Unit" baris={units} kolom={unduhUnit} testId="org-unduh" />,
    positions: <TombolUnduh namaBerkas="struktur-organisasi-jabatan" namaLembar="Jabatan" baris={positions} kolom={unduhPos} testId="org-unduh" />,
    headcount: <TombolUnduh namaBerkas="target-karyawan-per-unit" namaLembar="Target karyawan" baris={hcBaris} kolom={unduhHc} testId="org-unduh" />,
  };

  const kosongStruktur = (
    <EmptyState title="Belum ada struktur organisasi"
      description="Tambahkan unit pertama, atau muat struktur contoh lalu ubah sesuai perusahaan."
      action={<div className="flex flex-wrap justify-center gap-2">
        <Button variant="outline" onClick={handleSeed} disabled={seeding} data-testid="org-seed-empty">{seeding ? 'Memuat…' : 'Muat contoh'}</Button>
        <Button onClick={() => openUnitForm()}><Plus />Tambah unit</Button>
      </div>} />
  );

  const posUnitDetail = detailUnit ? positions.filter(p => p.unit_id === detailUnit.unit_id) : [];
  const subUnit = detailUnit ? units.filter(u => u.parent_id === detailUnit.unit_id) : [];

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <PageLayout testId="hr-org-module" title="Struktur Organisasi"
        subtitle="Bagan unit, jabatan, dan target jumlah karyawan per unit."
        actions={<>
          {units.length === 0 && !loading && (
            <Button variant="outline" onClick={handleSeed} disabled={seeding} data-testid="org-seed">
              {seeding ? 'Memuat…' : 'Muat contoh'}
            </Button>
          )}
          {tab === 'positions'
            ? <Button onClick={openPosForm} data-testid="org-add-position"><Plus />Tambah jabatan</Button>
            : <Button onClick={() => openUnitForm()} data-testid="org-add-unit"><Plus />Tambah unit</Button>}
        </>}
        filters={<>
          <TabsList className="h-auto max-w-full justify-start max-sm:flex-nowrap max-sm:overflow-x-auto">
            <TabsTrigger value="chart" className="shrink-0" data-testid="org-tab-chart">Bagan</TabsTrigger>
            <TabsTrigger value="units" className="shrink-0" data-testid="org-tab-units">Unit</TabsTrigger>
            <TabsTrigger value="positions" className="shrink-0" data-testid="org-tab-positions">Jabatan</TabsTrigger>
            <TabsTrigger value="headcount" className="shrink-0" data-testid="org-tab-headcount">Target karyawan</TabsTrigger>
          </TabsList>
          {/* Alat di ujung baris tab (bukan kepala/slot tools): di HP kepala dengan 3 tombol menimpa judul. */}
          <div className="ml-auto flex items-center gap-2">
            {unduh[tab]}
            <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </div>
        </>}
        summary={units.length > 0 && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="org-summary">
            <StatTile label="Unit" value={units.length} sub="Unit aktif di struktur" />
            <StatTile label="Jabatan" value={positions.length} sub="Terdaftar di semua unit" />
            <StatTile label="Karyawan di unit" value={sum.total_actual ?? '—'}
              sub={totalAktif !== undefined ? `dari ${totalAktif} karyawan aktif; dicocokkan lewat nama departemen` : 'Dicocokkan lewat nama departemen'} />
            <StatTile label="Kekurangan karyawan" value={headcount ? kekurangan : '—'} accent={kekurangan > 0 ? 'warning' : 'default'}
              sub={headcount ? `Target ${sum.total_target ?? 0}, terisi ${sum.total_actual ?? 0}` : 'Data target belum termuat'} />
          </div>
        )}
        footer={
          tab === 'units' && unitsPg.total > 0 ? <PaginationLite page={unitsPg.page} totalPages={unitsPg.totalPages} total={unitsPg.total} onPageChange={unitsPg.setPage} />
            : tab === 'positions' && positionsPg.total > 0 ? <PaginationLite page={positionsPg.page} totalPages={positionsPg.totalPages} total={positionsPg.total} onPageChange={positionsPg.setPage} />
              : null
        }>

        {error && <Notice tone="danger" icon={AlertCircle} title="Gagal memuat struktur organisasi">{error}</Notice>}

        {loading && !chart ? (
          <p className="py-10 text-center text-sm text-muted-foreground" data-testid="hr-org-skeleton">Memuat struktur organisasi…</p>
        ) : (<>
          {/* ─── Bagan ─── */}
          {tab === 'chart' && (chartTree.length === 0 ? kosongStruktur : (
            <GlassCard hover={false} className="divide-y divide-[var(--glass-border)] overflow-hidden" data-testid="org-chart">
              {chartTree.map(node => <OrgNode key={node.unit_id} node={node} onPilih={setDetailUnit} adaCabang={units.some(u => u.parent_id)} />)}
            </GlassCard>
          ))}

          {/* ─── Unit ─── */}
          {tab === 'units' && (
            <TabelData kolom={kolomUnit} baris={unitsPg.paged} kunci={(u) => u.unit_id} onKlikBaris={setDetailUnit}
              testId="org-units-table" kosong={kosongStruktur} />
          )}

          {/* ─── Jabatan ─── */}
          {tab === 'positions' && (
            <TabelData kolom={kolomPos} baris={positionsPg.paged} kunci={(p) => p.position_id} testId="org-positions-table"
              kosong={<EmptyState title="Belum ada jabatan" description="Tambahkan jabatan untuk tiap unit, lalu pilih jabatan di Data Karyawan."
                action={<Button onClick={openPosForm}><Plus />Tambah jabatan</Button>} />} />
          )}

          {/* ─── Target karyawan ─── */}
          {tab === 'headcount' && (
            <TabelData kolom={kolomHc} baris={hcBaris} kunci={(u) => u.unit_id} testId="org-headcount-table"
              onKlikBaris={(u) => setDetailUnit(units.find(x => x.unit_id === u.unit_id) || null)}
              kosong={<EmptyState title="Belum ada unit bertarget" description="Isi target jumlah karyawan di form unit untuk melihat kekurangan per unit." />} />
          )}
        </>)}

        {/* ─── Detail unit (popup) ─── */}
        {detailUnit && (
          <DetailPopup open onClose={() => setDetailUnit(null)} judul={detailUnit.name} testId="org-unit-detail"
            keterangan={detailUnit.code ? `Kode ${detailUnit.code}` : undefined}
            status={<><TypeBadge type={detailUnit.type} />
              {(() => { const s = statusTarget(detailUnit.headcount_actual, detailUnit.headcount_target); return <StatusBadge status="target" label={s.label} tone={s.tone} />; })()}</>}
            aksi={<>
              <Button size="sm" variant="outline" onClick={() => openUnitForm(units.find(u => u.unit_id === detailUnit.unit_id) || detailUnit)}><Pencil />Ubah</Button>
              <Button size="sm" variant="destructive" onClick={() => handleDeleteUnit(detailUnit)}><Trash2 />Hapus</Button>
            </>}>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Induk">{namaUnit[detailUnit.parent_id] || 'Tidak ada (unit teratas)'}</BarisDetail>
              <BarisDetail label="Kepala unit">{detailUnit.head_employee_name || '—'}</BarisDetail>
              <BarisDetail label="Karyawan terisi">{detailUnit.headcount_actual || 0} dari target {detailUnit.headcount_target || 0}</BarisDetail>
              <BarisDetail label="Sub-unit">{subUnit.length ? subUnit.map(u => u.name).join(', ') : '—'}</BarisDetail>
              {detailUnit.description && <BarisDetail label="Keterangan">{detailUnit.description}</BarisDetail>}
            </dl>
            <div>
              <p className="mb-2 text-base font-semibold text-foreground">Jabatan di unit ini</p>
              <TabelData kolom={kolomPos.filter(k => k.kunci !== 'unit')} baris={posUnitDetail} kunci={(p) => p.position_id}
                testId="org-unit-positions"
                kosong={<p className="text-sm text-muted-foreground">Belum ada jabatan di unit ini.</p>} />
            </div>
          </DetailPopup>
        )}

        {/* ─── Form unit ─── */}
        <FormPopup open={showUnitForm} onClose={() => setShowUnitForm(false)} ukuran="pendek" testId="org-unit-form"
          judul={editUnit ? `Ubah unit ${editUnit.name}` : 'Tambah unit'}
          keterangan="Nama unit dipakai sebagai pilihan departemen di Data Karyawan."
          onSimpan={handleSaveUnit} menyimpan={saving} bisaSimpan={!!unitForm.name} galat={galat}
          labelSimpan={editUnit ? 'Simpan perubahan' : 'Tambah unit'}>
          <Isian label="Nama unit" wajib htmlFor="org-unit-name">
            <Input id="org-unit-name" value={unitForm.name} onChange={e => setUnitForm(p => ({ ...p, name: e.target.value }))} data-testid="org-unit-name" />
          </Isian>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Isian label="Kode" htmlFor="org-unit-code">
              <Input id="org-unit-code" value={unitForm.code} onChange={e => setUnitForm(p => ({ ...p, code: e.target.value }))} />
            </Isian>
            <Isian label="Tipe">
              <SmartNativeSelect value={unitForm.type} onChange={e => setUnitForm(p => ({ ...p, type: e.target.value }))} searchable={false}
                data-testid="org-unit-type" className="w-full">
                {TYPE_LEVELS.map(t => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Unit induk">
              <SmartNativeSelect value={unitForm.parent_id} onChange={e => setUnitForm(p => ({ ...p, parent_id: e.target.value }))} className="w-full">
                <option value="">Tidak ada (unit teratas)</option>
                {units.filter(u => !editUnit || u.unit_id !== editUnit.unit_id).map(u => <option key={u.unit_id} value={u.unit_id}>{u.name}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Kepala unit" petunjuk="Dipilih dari karyawan aktif.">
              <EmployeeSelect employees={employees} value={unitForm.head_employee_id} testId="org-unit-head"
                placeholder={unitForm.head_employee_name && !unitForm.head_employee_id ? `${unitForm.head_employee_name} (belum dipilih)` : '— Belum ditentukan —'}
                onChange={v => { const e = employees.find(x => x.id === v); setUnitForm(p => ({ ...p, head_employee_id: v, head_employee_name: e ? e.name : (v ? p.head_employee_name : '') })); }}
                className="w-full" />
            </Isian>
            <Isian label="Target jumlah karyawan" htmlFor="org-unit-target">
              <Input id="org-unit-target" type="number" min={0} value={unitForm.headcount_target}
                onChange={e => setUnitForm(p => ({ ...p, headcount_target: +e.target.value }))} />
            </Isian>
          </div>
        </FormPopup>

        {/* ─── Form jabatan ─── */}
        <FormPopup open={showPosForm} onClose={() => setShowPosForm(false)} ukuran="pendek" testId="org-pos-form"
          judul="Tambah jabatan" keterangan="Jabatan muncul sebagai pilihan di Data Karyawan untuk unitnya."
          onSimpan={handleSavePos} menyimpan={saving} bisaSimpan={!!posForm.title} galat={galat} labelSimpan="Tambah jabatan">
          <Isian label="Nama jabatan" wajib htmlFor="org-pos-title">
            <Input id="org-pos-title" value={posForm.title} onChange={e => setPosForm(p => ({ ...p, title: e.target.value }))} data-testid="org-pos-title" />
          </Isian>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Isian label="Unit">
              <SmartNativeSelect value={posForm.unit_id} onChange={e => setPosForm(p => ({ ...p, unit_id: e.target.value }))} data-testid="org-pos-unit" className="w-full">
                <option value="">Pilih unit</option>
                {units.map(u => <option key={u.unit_id} value={u.unit_id}>{`${u.code ? `${u.code} · ` : ''}${u.name}`}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Tingkat jabatan (1–10)" htmlFor="org-pos-grade">
              <Input id="org-pos-grade" type="number" min={1} max={10} value={posForm.grade}
                onChange={e => setPosForm(p => ({ ...p, grade: +e.target.value }))} />
            </Isian>
            <Isian label="Target jumlah karyawan" htmlFor="org-pos-target">
              <Input id="org-pos-target" type="number" min={1} value={posForm.headcount_target}
                onChange={e => setPosForm(p => ({ ...p, headcount_target: +e.target.value }))} />
            </Isian>
            <Isian label="Golongan gaji">
              <SmartNativeSelect value={posForm.salary_grade} onChange={e => setPosForm(p => ({ ...p, salary_grade: e.target.value }))}
                data-testid="org-pos-salary-grade" className="w-full">
                <option value="">{salaryGrades.length ? '— Tanpa golongan —' : '— Belum ada golongan (Pengaturan SDM) —'}</option>
                {salaryGrades.map(g => <option key={g.id} value={g.grade_code}>{`${g.grade_code}${g.grade_name ? ` · ${g.grade_name}` : ''}`}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>
        </FormPopup>
      </PageLayout>
    </Tabs>
  );
}
