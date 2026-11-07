/**
 * HRAssetModule — Portal SDM › Aset Karyawan: aset perusahaan yang dipinjamkan ke karyawan.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (tab + penyaring satu baris), daftar = TabelData (kartu
 * ringkas di HP), aksi baris maks 2 (Tugaskan/Kembalikan + "Lainnya"), detail aset = popup, form = FormPopup,
 * DatePicker, unduh Excel/CSV per tab. Tab "Per karyawan": dulu daftar tombol nama (hanya 30 karyawan pertama
 * hasil cari) di samping kartu-kartu; kini pemilih karyawan yang bisa dicari (semua karyawan aktif) + tabel.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  Plus, Pencil, Trash2, RefreshCw, Search, UserCheck, ArrowLeftRight, Printer, MoreHorizontal,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { EmployeeSelect } from './hr/hrPickers';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB, toWIBDate } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;
const asset = (path, opts = {}) => fetch(`${API}/api/dewi/assets${path}`, { cache: 'no-store', ...opts });

const CATEGORIES = ['Laptop/PC','Seragam','Helm/APD','ID Card','Kendaraan','Peralatan','Furnitur','Handphone','Kunci/Akses','Lainnya'];
const CONDITIONS = ['Baik', 'Rusak', 'Hilang'];
const STATUSES   = ['Available', 'Assigned', 'Maintenance', 'Disposed'];

const STATUS_CFG = {
  Available:   { tone: 'success', label: 'Tersedia' },
  Assigned:    { tone: 'info',    label: 'Dipinjam' },
  Maintenance: { tone: 'warning', label: 'Perbaikan' },
  Disposed:    { tone: 'muted',   label: 'Dibuang' },
};
const COND_TONE = { Baik: 'success', Rusak: 'warning', Hilang: 'danger' };

const fmtRp = (n) => n ? formatRupiah(n) : '—';
const tgl = (s) => (s ? formatTanggalID(toWIBDate(s)) || s : '—');
const labelStatus = (s) => STATUS_CFG[s]?.label || 'Status lain';

function AssetStatus({ status }) {
  const c = STATUS_CFG[status] || STATUS_CFG.Available;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}
function CondBadge({ cond }) {
  return <StatusBadge status={cond} label={cond || '—'} tone={COND_TONE[cond] || 'default'} />;
}

export default function HRAssetModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [tab, setTab] = useState('assets');

  const [assets, setAssets] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [search, setSearch] = useState('');
  const [filterCat, setFilterCat] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [selectedEmp, setSelectedEmp] = useState(null);
  const [empAssets, setEmpAssets] = useState([]);
  const [detail, setDetail] = useState(null);

  // Dialogs
  const [assetDialog, setAssetDialog] = useState(null);
  const [assignDialog, setAssignDialog] = useState(null);  // {asset, mode: assign|return}

  const loadAssets = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (filterCat) params.set('category', filterCat);
      if (filterStatus) params.set('status', filterStatus);
      const r = await asset(`?${params}`, { headers });
      const d = await r.json();
      setAssets(d.assets || []);
    } catch (e) {
      if (!e?.message?.includes('already read')) console.error('loadAssets:', e);
    }
  }, [headers, search, filterCat, filterStatus]);

  const loadAssignments = useCallback(async () => {
    try {
      const r = await asset('/assignments?status=active', { headers });
      const d = await r.json();
      setAssignments(d.assignments || []);
    } catch (e) {
      if (!e?.message?.includes('already read')) console.error('loadAssignments:', e);
    }
  }, [headers]);

  const loadEmpAssets = useCallback(async (empId) => {
    if (!empId) return;
    try {
      const r = await asset(`/employee/${empId}`, { headers });
      const d = await r.json();
      setEmpAssets(d.assignments || []);
    } catch (e) {
      if (!e?.message?.includes('already read')) console.error('loadEmpAssets:', e);
    }
  }, [headers]);

  useEffect(() => {
    (async () => {
      try {
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        if (filterCat) params.set('category', filterCat);
        if (filterStatus) params.set('status', filterStatus);
        const r = await asset(`?${params}`, { headers, cache: 'no-store' });
        const d = await r.json();
        setAssets(d.assets || []);
      } catch (e) {
        if (!e?.message?.includes('already read')) console.error('loadAssets:', e);
      }
    })();
  }, [headers, search, filterCat, filterStatus]);

  useEffect(() => {
    if (tab !== 'assignments') return;
    (async () => {
      try {
        const r = await asset('/assignments?status=active', { headers, cache: 'no-store' });
        const d = await r.json();
        setAssignments(d.assignments || []);
      } catch (e) {
        if (!e?.message?.includes('already read')) console.error('loadAssignments:', e);
      }
    })();
  }, [tab, headers]);

  useEffect(() => {
    (async () => {
      try {
        // FASE 20 — endpoint karyawan yang benar membalas {total, items:[...]} ⇒ `items` wajib dibaca.
        const r = await fetch(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers, cache: 'no-store' });
        const d = await r.json();
        setEmployees(Array.isArray(d) ? d : d.items || d.rows || d.employees || []);
      } catch (e) {
        if (!e?.message?.includes('already read')) console.error('loadEmployees:', e);
      }
    })();
  }, [headers]);

  useEffect(() => {
    if (!selectedEmp) return;
    (async () => {
      try {
        const r = await asset(`/employee/${selectedEmp.id}`, { headers, cache: 'no-store' });
        const d = await r.json();
        setEmpAssets(d.assignments || []);
      } catch (e) {
        if (!e?.message?.includes('already read')) console.error('loadEmpAssets:', e);
      }
    })();
  }, [selectedEmp, headers]);

  const handleSaveAsset = async (form) => {
    const isEdit = !!form.asset_id;
    const url = isEdit ? `/${form.asset_id}` : '';
    const method = isEdit ? 'PUT' : 'POST';
    const r = await asset(url, { method, headers, body: JSON.stringify(form) });
    const d = await r.json();
    if (!r.ok) { toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan aset'); return; }
    toast.success(isEdit ? 'Aset disimpan' : 'Aset ditambahkan');
    setAssetDialog(null);
    loadAssets();
  };

  const handleDeleteAsset = async (a) => {
    if (!(await confirmDialog({
      title: 'Hapus aset ini?', body: `${a.asset_name}${a.asset_code ? ` (${a.asset_code})` : ''} hilang dari daftar aset karyawan.`,
      confirmLabel: 'Hapus', danger: true,
    }))) return;
    const r = await asset(`/${a.asset_id}`, { method: 'DELETE', headers });
    const d = await r.json();
    if (!r.ok) { toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menghapus'); return; }
    toast.success('Aset dihapus');
    setDetail(null);
    loadAssets();
  };

  const handleAssign = async (form) => {
    const r = await asset(`/${form.asset_id}/assign`, { method: 'POST', headers, body: JSON.stringify(form) });
    const d = await r.json();
    if (!r.ok) { toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal menugaskan'); return; }
    toast.success(`Aset ditugaskan ke ${form.employee_name}`);
    setAssignDialog(null);
    loadAssets();
    loadAssignments();
    if (selectedEmp) loadEmpAssets(selectedEmp.id);
  };

  const handleReturn = async (form) => {
    const r = await asset(`/${form.asset_id}/return`, { method: 'POST', headers, body: JSON.stringify(form) });
    const d = await r.json();
    if (!r.ok) { toast.error(typeof d.detail === 'string' ? d.detail : 'Gagal mengembalikan'); return; }
    toast.success('Aset dikembalikan');
    setAssignDialog(null);
    loadAssets();
    loadAssignments();
    if (selectedEmp) loadEmpAssets(selectedEmp.id);
  };

  // 2026-11-02 (registri aset tunggal): cetak label dipindah ke Portal Aset / Keuangan › Aset Tetap.

  const { page, setPage, totalPages, total, paged } = useClientPagination(assets, 10);
  const buka = (a, mode) => { setDetail(null); setAssignDialog({ asset: a, mode }); };

  // ── Kolom ─────────────────────────────────────────────────────────────────
  const kolomAset = [
    { kunci: 'aset', label: 'Aset', hp: 'judul', isi: (a) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{a.asset_name}</p>
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">{a.asset_code || '—'}</span>{a.serial_number ? ` · S/N ${a.serial_number}` : ''}
        </p>
      </div>) },
    { kunci: 'kategori', label: 'Kategori', isi: (a) => a.category || '—' },
    { kunci: 'kondisi', label: 'Kondisi', isi: (a) => <CondBadge cond={a.condition} /> },
    { kunci: 'status', label: 'Status', isi: (a) => <AssetStatus status={a.status} /> },
    { kunci: 'peminjam', label: 'Dipinjam oleh', isi: (a) => (a.current_assignment ? (
      <div className="min-w-0">
        <p>{a.current_assignment.employee_name}</p>
        <p className="text-xs text-muted-foreground">{tgl(a.current_assignment.assigned_date)}</p>
      </div>) : <span className="text-muted-foreground">—</span>) },
    { kunci: 'harga', label: 'Harga beli', rata: 'kanan', hp: false, isi: (a) => (
      <span className="whitespace-nowrap tabular-nums">{fmtRp(a.purchase_price)}</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => (
      <div className="flex items-center justify-end gap-1">
        {a.status === 'Available' && (
          <Button size="sm" variant="outline" onClick={() => buka(a, 'assign')} data-testid={`assign-asset-${a.asset_id}`}>
            <UserCheck />Tugaskan
          </Button>
        )}
        {a.status === 'Assigned' && (
          <Button size="sm" variant="outline" onClick={() => buka(a, 'return')} data-testid={`return-asset-${a.asset_id}`}>
            <ArrowLeftRight />Kembalikan
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Lainnya" title="Lainnya" data-testid={`asset-more-${a.asset_id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setAssetDialog(a)}><Pencil className="mr-2 h-4 w-4" />Ubah</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => handleDeleteAsset(a)} className="text-[hsl(var(--danger-text))]">
              <Trash2 className="mr-2 h-4 w-4" />Hapus
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>) },
  ];

  const kolomPenugasan = [
    { kunci: 'aset', label: 'Aset', hp: 'judul', isi: (a) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{a.asset_name}</p>
        <p className="font-mono text-xs text-muted-foreground">{a.asset_code || '—'}</p>
      </div>) },
    { kunci: 'karyawan', label: 'Karyawan', isi: (a) => (
      <div className="min-w-0">
        <p>{a.employee_name}</p>
        <p className="text-xs text-muted-foreground">{a.employee_code || ''}</p>
      </div>) },
    { kunci: 'pinjam', label: 'Tanggal pinjam', isi: (a) => <span className="whitespace-nowrap">{tgl(a.assigned_date)}</span> },
    { kunci: 'kembali', label: 'Rencana kembali', isi: (a) => {
      if (!a.expected_return_date) return <span className="text-muted-foreground">—</span>;
      const lewat = toWIBDate(a.expected_return_date) < todayWIB();
      return (
        <span className={`whitespace-nowrap ${lewat ? 'font-medium text-[hsl(var(--danger-text))]' : ''}`}>
          {tgl(a.expected_return_date)}{lewat ? ' · lewat' : ''}
        </span>);
    } },
    { kunci: 'catatan', label: 'Catatan', hp: false, isi: (a) => (
      <span className="block max-w-[14rem] truncate text-muted-foreground" title={a.notes}>{a.notes || '—'}</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => (
      <Button size="sm" variant="outline"
        onClick={() => {
          const ast = assets.find(x => x.asset_id === a.asset_id) || { asset_id: a.asset_id, asset_name: a.asset_name, asset_code: a.asset_code };
          buka(ast, 'return');
        }}
        data-testid={`return-assign-${a.assignment_id}`}>
        <ArrowLeftRight />Kembalikan
      </Button>) },
  ];

  const kolomRiwayat = [
    { kunci: 'aset', label: 'Aset', hp: 'judul', isi: (a) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{a.asset_name}</p>
        <p className="font-mono text-xs text-muted-foreground">{a.asset_code || '—'}</p>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (a) => (
      <StatusBadge status={a.status} label={a.status === 'active' ? 'Dipinjam' : 'Sudah kembali'} tone={a.status === 'active' ? 'info' : 'muted'} />) },
    { kunci: 'pinjam', label: 'Tanggal pinjam', isi: (a) => <span className="whitespace-nowrap">{tgl(a.assigned_date)}</span> },
    { kunci: 'kembali', label: 'Tanggal kembali', isi: (a) => <span className="whitespace-nowrap">{tgl(a.return_date)}</span> },
    { kunci: 'catatan', label: 'Catatan', hp: false, isi: (a) => (
      <span className="block max-w-[14rem] truncate text-muted-foreground" title={a.notes}>{a.notes || '—'}</span>) },
  ];

  const unduh = {
    assets: (
      <TombolUnduh label={<span className="hidden sm:inline">Unduh</span>} namaBerkas="aset-karyawan" namaLembar="Aset" baris={assets} testId="asset-unduh"
        kolom={[
          { label: 'Kode aset', nilai: (a) => a.asset_code || '' },
          { label: 'Nama aset', nilai: (a) => a.asset_name },
          { label: 'Kategori', nilai: (a) => a.category || '' },
          { label: 'Nomor seri', nilai: (a) => a.serial_number || '' },
          { label: 'Kondisi', nilai: (a) => a.condition || '' },
          { label: 'Status', nilai: (a) => labelStatus(a.status) },
          { label: 'Dipinjam oleh', nilai: (a) => a.current_assignment?.employee_name || '' },
          { label: 'Tanggal pinjam', nilai: (a) => (a.current_assignment?.assigned_date ? tgl(a.current_assignment.assigned_date) : '') },
          { label: 'Tanggal beli', nilai: (a) => (a.purchase_date ? tgl(a.purchase_date) : '') },
          { label: 'Harga beli', nilai: (a) => Number(a.purchase_price || 0) },
          { label: 'Catatan', nilai: (a) => a.notes || '' },
        ]} />
    ),
    assignments: (
      <TombolUnduh label={<span className="hidden sm:inline">Unduh</span>} namaBerkas="penugasan-aset-aktif" namaLembar="Penugasan aktif" baris={assignments} testId="assignment-unduh"
        kolom={[
          { label: 'Aset', nilai: (a) => a.asset_name },
          { label: 'Kode aset', nilai: (a) => a.asset_code || '' },
          { label: 'Karyawan', nilai: (a) => a.employee_name || '' },
          { label: 'Kode karyawan', nilai: (a) => a.employee_code || '' },
          { label: 'Tanggal pinjam', nilai: (a) => (a.assigned_date ? tgl(a.assigned_date) : '') },
          { label: 'Rencana kembali', nilai: (a) => (a.expected_return_date ? tgl(a.expected_return_date) : '') },
          { label: 'Catatan', nilai: (a) => a.notes || '' },
        ]} />
    ),
    by_employee: (
      <TombolUnduh label={<span className="hidden sm:inline">Unduh</span>} namaBerkas={`aset-${selectedEmp?.employee_code || 'karyawan'}`} namaLembar="Aset karyawan"
        baris={selectedEmp ? empAssets : []} testId="emp-asset-unduh"
        kolom={[
          { label: 'Karyawan', nilai: () => selectedEmp?.name || '' },
          { label: 'Aset', nilai: (a) => a.asset_name },
          { label: 'Kode aset', nilai: (a) => a.asset_code || '' },
          { label: 'Status', nilai: (a) => (a.status === 'active' ? 'Dipinjam' : 'Sudah kembali') },
          { label: 'Tanggal pinjam', nilai: (a) => (a.assigned_date ? tgl(a.assigned_date) : '') },
          { label: 'Tanggal kembali', nilai: (a) => (a.return_date ? tgl(a.return_date) : '') },
          { label: 'Catatan', nilai: (a) => a.notes || '' },
        ]} />
    ),
  };

  const aktifEmp = empAssets.filter(a => a.status === 'active').length;

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <PageLayout testId="hr-asset-module" title="Aset karyawan"
        subtitle="Aset perusahaan yang dipinjamkan ke karyawan: daftar, penugasan aktif, dan riwayat per karyawan."
        // Alat (muat ulang, unduh) ikut kepala, bukan baris penyaring: baris itu memuat tab, dan di HP cetakan
        // menyempitkan penyaring di samping alat sehingga tab terpotong (lihat laporan, permintaan komponen bersama).
        actions={<>
          <Button variant="outline" size="icon" onClick={() => { loadAssets(); loadAssignments(); if (selectedEmp) loadEmpAssets(selectedEmp.id); }}
            title="Muat ulang" aria-label="Muat ulang">
            <RefreshCw />
          </Button>
          {unduh[tab]}
          <Button onClick={() => setAssetDialog({})} data-testid="asset-add"><Plus />Tambah aset</Button>
        </>}
        filters={<>
          <TabsList className="h-auto max-w-full justify-start max-sm:flex-nowrap max-sm:overflow-x-auto">
            <TabsTrigger value="assets" data-testid="asset-tab-assets">Daftar aset</TabsTrigger>
            <TabsTrigger value="assignments" data-testid="asset-tab-assignments">Penugasan aktif</TabsTrigger>
            <TabsTrigger value="by_employee" data-testid="asset-tab-employee">Per karyawan</TabsTrigger>
          </TabsList>
          {tab === 'assets' && (<>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Cari nama, kode, nomor seri" className="pl-8" data-testid="asset-search" />
            </div>
            <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto">
            <SmartNativeSelect value={filterCat} onChange={e => setFilterCat(e.target.value)} searchable={false}
              className="h-9 w-full sm:w-44" aria-label="Kategori" data-testid="asset-filter-category">
              <option value="">Semua kategori</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </SmartNativeSelect>
            <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} searchable={false}
              className="h-9 w-full sm:w-40" aria-label="Status" data-testid="asset-filter-status">
              <option value="">Semua status</option>
              {STATUSES.map(s => <option key={s} value={s}>{STATUS_CFG[s]?.label || s}</option>)}
            </SmartNativeSelect>
            </div>
          </>)}
          {tab === 'by_employee' && (
            <EmployeeSelect employees={employees} value={selectedEmp?.id || ''} testId="asset-by-employee"
              placeholder="— Pilih karyawan —" className="h-9 w-full sm:w-72"
              onChange={(v) => { const e = employees.find((x) => x.id === v) || null; setSelectedEmp(e); if (!e) setEmpAssets([]); }} />
          )}
        </>}
        footer={tab === 'assets' && assets.length > 0 && (
          <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />
        )}>

        {tab === 'assets' && (<>
          <TabelData kolom={kolomAset} baris={paged} kunci={(a) => a.asset_id} onKlikBaris={setDetail} testId="asset-table"
            kosong={<EmptyState
              title={search || filterCat || filterStatus ? 'Tidak ada aset yang cocok' : 'Belum ada aset terdaftar'}
              description={search || filterCat || filterStatus ? 'Ubah kata pencarian atau penyaring.' : 'Tambahkan aset pertama untuk mulai melacak aset yang dipinjam karyawan.'}
              action={!(search || filterCat || filterStatus) && { label: 'Tambah aset', onClick: () => setAssetDialog({}) }} />} />
          <p className="text-xs text-muted-foreground" data-testid="hr-asset-label-moved">
            <Printer className="mr-1 inline h-3.5 w-3.5" />Label aset dicetak dari Portal Aset (kode registri Aset Tetap).
          </p>
        </>)}

        {tab === 'assignments' && (<>
          {assignments.length > 0 && (
            <p className="text-sm text-muted-foreground" data-testid="assignment-count">{assignments.length} aset sedang dipinjam karyawan.</p>
          )}
          <TabelData kolom={kolomPenugasan} baris={assignments} kunci={(a) => a.assignment_id} testId="assignment-table"
            kosong={<EmptyState title="Tidak ada penugasan aktif" description="Tidak ada aset yang sedang dipinjam karyawan saat ini." />} />
        </>)}

        {tab === 'by_employee' && (selectedEmp ? (<>
          <p className="text-sm text-muted-foreground" data-testid="emp-asset-summary">
            <span className="font-medium text-foreground">{selectedEmp.name}</span>
            {' · '}{selectedEmp.employee_code}{selectedEmp.job_title ? ` · ${selectedEmp.job_title}` : ''}
            {' · '}{aktifEmp} aset sedang dipinjam
          </p>
          <TabelData kolom={kolomRiwayat} baris={empAssets} kunci={(a) => a.assignment_id} testId="emp-asset-table"
            kosong={<EmptyState title="Tidak ada aset dipinjam" description="Karyawan ini belum pernah meminjam aset." />} />
        </>) : (
          <EmptyState title="Pilih karyawan" description="Pilih karyawan di atas untuk melihat aset yang sedang dan pernah dipinjam." />
        ))}

        {detail && (
          <DetailPopup open onClose={() => setDetail(null)} testId="asset-detail"
            judul={detail.asset_name} keterangan={detail.asset_code}
            status={<><AssetStatus status={detail.status} /><CondBadge cond={detail.condition} /></>}
            aksi={<>
              {detail.status === 'Available' && (
                <Button size="sm" onClick={() => buka(detail, 'assign')}><UserCheck />Tugaskan</Button>
              )}
              {detail.status === 'Assigned' && (
                <Button size="sm" onClick={() => buka(detail, 'return')}><ArrowLeftRight />Kembalikan</Button>
              )}
              <Button size="sm" variant="outline" onClick={() => { setAssetDialog(detail); setDetail(null); }}><Pencil />Ubah</Button>
              <Button size="sm" variant="destructive" onClick={() => handleDeleteAsset(detail)}><Trash2 />Hapus</Button>
            </>}>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Kode aset"><span className="font-mono">{detail.asset_code || '—'}</span></BarisDetail>
              <BarisDetail label="Kategori">{detail.category || '—'}</BarisDetail>
              <BarisDetail label="Nomor seri">{detail.serial_number || '—'}</BarisDetail>
              <BarisDetail label="Tanggal beli">{tgl(detail.purchase_date)}</BarisDetail>
              <BarisDetail label="Harga beli"><span className="tabular-nums">{fmtRp(detail.purchase_price)}</span></BarisDetail>
              <BarisDetail label="Dipinjam oleh">
                {detail.current_assignment
                  ? `${detail.current_assignment.employee_name} · sejak ${tgl(detail.current_assignment.assigned_date)}`
                  : '—'}
              </BarisDetail>
              <BarisDetail label="Catatan">{detail.notes || '—'}</BarisDetail>
            </dl>
          </DetailPopup>
        )}

        {/* ── FORM: TAMBAH/UBAH ASET ─────────────────────────── */}
        {assetDialog !== null && (
          <AssetFormDialog initial={assetDialog} employees={employees} onSave={handleSaveAsset} onClose={() => setAssetDialog(null)} />
        )}

        {/* ── FORM: TUGASKAN / KEMBALIKAN ──────────────────────── */}
        {assignDialog !== null && (
          <AssignDialog
            data={assignDialog}
            employees={employees}
            onAssign={handleAssign}
            onReturn={handleReturn}
            onClose={() => setAssignDialog(null)}
          />
        )}
      </PageLayout>
    </Tabs>
  );
}

function AssetFormDialog({ initial, onSave, onClose }) {
  const [form, setForm] = useState({
    asset_code: '', asset_name: '', category: 'Lainnya', serial_number: '',
    purchase_date: '', purchase_price: 0, condition: 'Baik', notes: '',
    ...initial,
  });
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  const handleSubmit = async () => {
    if (!String(form.asset_name || '').trim()) { setGalat('Nama aset wajib diisi.'); return; }
    setGalat('');
    setSaving(true);
    await onSave(form);
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="asset-form"
      judul={form.asset_id ? 'Ubah aset' : 'Tambah aset'} keterangan="Aset perusahaan yang bisa dipinjamkan ke karyawan."
      onSimpan={handleSubmit} menyimpan={saving} galat={galat}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kode aset" htmlFor="asset-code">
          <Input id="asset-code" value={form.asset_code} onChange={e => setForm(f => ({ ...f, asset_code: e.target.value.toUpperCase() }))}
            placeholder="Contoh: AST-001" />
        </Isian>
        <Isian label="Nama aset" wajib htmlFor="asset-name">
          <Input id="asset-name" value={form.asset_name} onChange={e => setForm(f => ({ ...f, asset_name: e.target.value }))}
            placeholder="Contoh: Laptop Lenovo X1" required data-testid="asset-name-input" />
        </Isian>
        <Isian label="Kategori">
          <Select value={form.category} onValueChange={v => setForm(f => ({ ...f, category: v }))}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{CATEGORIES.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
          </Select>
        </Isian>
        <Isian label="Kondisi">
          <Select value={form.condition} onValueChange={v => setForm(f => ({ ...f, condition: v }))}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{CONDITIONS.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
          </Select>
        </Isian>
        <Isian label="Nomor seri" htmlFor="asset-serial">
          <Input id="asset-serial" value={form.serial_number} onChange={e => setForm(f => ({ ...f, serial_number: e.target.value }))}
            placeholder="Contoh: SN-12345678" />
        </Isian>
        <Isian label="Tanggal beli">
          <DatePicker value={form.purchase_date || ''} onChange={v => setForm(f => ({ ...f, purchase_date: v }))}
            max={todayWIB()} testId="asset-purchase-date" />
        </Isian>
        <Isian label="Harga beli (Rp)">
          <MoneyInput value={form.purchase_price}
            onChange={e => setForm(f => ({ ...f, purchase_price: parseFloat(e.target.value) || 0 }))} />
        </Isian>
      </div>
      <Isian label="Catatan" htmlFor="asset-notes">
        <Textarea id="asset-notes" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} rows={2} />
      </Isian>
    </FormPopup>
  );
}

function AssignDialog({ data, employees, onAssign, onReturn, onClose }) {
  const { asset, mode } = data;
  const [form, setForm] = useState({
    asset_id: asset.asset_id,
    employee_id: '',
    employee_name: '',
    assigned_date: todayWIB(),
    expected_return_date: '',
    return_date: todayWIB(),
    condition: 'Baik',
    notes: '',
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    setSaving(true);
    if (mode === 'assign') await onAssign(form);
    else await onReturn(form);
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="asset-assign-form"
      judul={mode === 'assign' ? 'Tugaskan aset' : 'Kembalikan aset'}
      keterangan={`${asset.asset_name || ''}${asset.asset_code ? ` · ${asset.asset_code}` : ''}`}
      onSimpan={handleSubmit} menyimpan={saving} labelSimpan={mode === 'assign' ? 'Tugaskan' : 'Kembalikan'}
      bisaSimpan={!(mode === 'assign' && !form.employee_id)}>
      {mode === 'assign' ? (
        <>
          <Isian label="Karyawan" wajib>
            {/* Tahap 5 (2026-11-07): pemilih karyawan bisa dicari (dulu Select tanpa kotak cari) */}
            <EmployeeSelect employees={employees} value={form.employee_id} testId="asset-assign-employee"
              className="h-9 w-full"
              onChange={v => {
                const emp = employees.find(e => e.id === v);
                setForm(f => ({ ...f, employee_id: v, employee_name: emp?.name || '' }));
              }} />
          </Isian>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Tanggal pinjam">
              <DatePicker value={form.assigned_date} onChange={v => setForm(f => ({ ...f, assigned_date: v }))}
                bolehKosong={false} testId="asset-assigned-date" />
            </Isian>
            <Isian label="Rencana kembali" petunjuk="Opsional.">
              <DatePicker value={form.expected_return_date} onChange={v => setForm(f => ({ ...f, expected_return_date: v }))}
                min={form.assigned_date || undefined} placeholder="Tanpa batas" testId="asset-expected-return" />
            </Isian>
          </div>
        </>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Tanggal kembali">
            <DatePicker value={form.return_date} onChange={v => setForm(f => ({ ...f, return_date: v }))}
              bolehKosong={false} testId="asset-return-date" />
          </Isian>
          <Isian label="Kondisi">
            <Select value={form.condition} onValueChange={v => setForm(f => ({ ...f, condition: v }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{CONDITIONS.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
            </Select>
          </Isian>
        </div>
      )}
      <Isian label="Catatan" htmlFor="asset-assign-notes">
        <Input id="asset-assign-notes" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
          placeholder="Opsional" />
      </Isian>
    </FormPopup>
  );
}
