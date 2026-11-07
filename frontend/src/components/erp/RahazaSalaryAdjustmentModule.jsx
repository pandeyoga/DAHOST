/**
 * Penyesuaian gaji (tab di hub Penggajian) — usulan kenaikan gaji dengan persetujuan atasan lalu HR.
 *
 * Standar UI/UX v2 (8 Nov 2026), tampilan saja — alur, endpoint, dan data yang dikirim TIDAK berubah:
 *  • cetakan PageLayout (dulu judul buatan sendiri berbahasa Inggris + `p-6` + kartu bergradasi warna);
 *  • 5 kartu angka → pil status berangka di penyaring. Angkanya kini dihitung dari daftar yang sama dengan tabel
 *    (dulu dari `/stats/summary` = seluruh usulan semua orang, sedangkan atasan hanya melihat usulan timnya);
 *  • daftar = TabelData + unduh Excel/CSV; aksi baris paling banyak 2 tampak, sisanya di "Lainnya" & popup detail;
 *  • form = FormPopup standar; Tolak/Batalkan = dialog konfirmasi; detail = DetailPopup; tanggal = DatePicker.
 * Perbaikan pemilih: periode KPI dulu dibaca sebagai larik padahal API membalas `{ periods: [...] }` → daftar selalu
 * kosong dan "Buat dari KPI" tidak pernah bisa dipakai. Kini dibaca dari `periods` (hanya periode berstatus final).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { CheckCircle2, Eye, MoreHorizontal, Plus, RefreshCw, Search, Trash2, Wand2, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge as Lencana } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

const fetchAPI = (path, opts = {}, token) =>
  fetch(`${API}/api/rahaza${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(opts.headers || {}),
    },
  });

// Status → label & warna token (StatusBadge bersama)
const STATUS_CFG = {
  pending_manager: { label: 'Menunggu atasan', tone: 'warning' },
  pending_hr: { label: 'Menunggu HR', tone: 'info' },
  approved: { label: 'Disetujui', tone: 'success' },
  rejected: { label: 'Ditolak', tone: 'danger' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
};

const TYPE_LABELS = {
  kpi_raise: 'Kenaikan dari KPI',
  performance_raise: 'Kenaikan kinerja',
  promotion: 'Promosi',
  annual_increment: 'Kenaikan tahunan',
  manual: 'Manual oleh HR',
};
const PERAN_LABEL = { manager: 'atasan', Manager: 'atasan', hr: 'HR', HR: 'HR' };

const fmtCurrency = (n) => {
  if (n === null || n === undefined) return '—';
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(n);
};

const fmtDate = (d) => {
  if (!d) return '—';
  try {
    return new Date(d).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Jakarta' });
  } catch {
    return d;
  }
};
const pctLabel = (v, digit = 1) => `+${Number(v || 0).toFixed(digit).replace('.', ',')}%`;

function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.cancelled;
  return <Lencana status={status} label={cfg.label} tone={cfg.tone} testId={`adj-status-badge-${status}`} />;
}

/** Aksi yang boleh untuk satu usulan (aturan tampil sama dengan versi lama). */
function aksiUsulan(a, isHR) {
  const out = [];
  if (a.status === 'pending_manager') out.push('approve_manager');
  if ((a.status === 'pending_hr' || (a.status === 'pending_manager' && isHR)) && isHR) out.push('approve_hr');
  if (['pending_manager', 'pending_hr'].includes(a.status)) out.push('reject');
  if (isHR && ['pending_manager', 'pending_hr'].includes(a.status)) out.push('cancel');
  return out;
}
const AKSI_LABEL = {
  approve_manager: 'Setujui sebagai atasan', approve_hr: 'Setujui sebagai HR', reject: 'Tolak', cancel: 'Batalkan usulan',
};
const AKSI_TESTID = { approve_manager: 'adj-approve-mgr', approve_hr: 'adj-approve-hr', reject: 'adj-reject', cancel: 'adj-cancel' };

export default function RahazaSalaryAdjustmentModule({ token, user }) {
  const [adjustments, setAdjustments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [kpiPeriods, setKpiPeriods] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterType, setFilterType] = useState('all');
  const [search, setSearch] = useState('');

  // Dialogs
  const [createOpen, setCreateOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [approveDialog, setApproveDialog] = useState(null); // { type: 'approve_manager' | 'approve_hr', adj }

  const userRole = useMemo(() => (user?.role || '').toLowerCase(), [user]);
  const isHR = ['superadmin', 'admin', 'owner', 'hr'].includes(userRole);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [adjRes, empsRes, periodsRes] = await Promise.all([
        fetchAPI('/salary-adjustments', {}, token),
        fetchAPI('/employees?active_only=true&limit=500', {}, token),
        fetch(`${API}/api/dewi/kpi/periods`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      const adjs = adjRes.ok ? await adjRes.json() : [];
      const emps = empsRes.ok ? await empsRes.json() : [];
      const periods = periodsRes.ok ? await periodsRes.json() : [];

      setAdjustments(Array.isArray(adjs) ? adjs : []);
      // Tahap 5 (2026-11-07): API karyawan membalas {items: [...]} — dulu dibaca sebagai array → daftar
      // karyawan di "Buat Usulan Manual" SELALU kosong dan usulan manual tidak bisa dibuat.
      setEmployees(Array.isArray(emps) ? emps : (emps?.items || []));
      // UI v2: API periode KPI membalas { ok, periods: [...] } (dulu dibaca sebagai larik → selalu kosong).
      const daftarPeriode = Array.isArray(periods) ? periods : (periods?.periods || []);
      setKpiPeriods(daftarPeriode.filter(p => p.status === 'finalized'));
    } catch (e) {
      toast.error('Gagal memuat data: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Pil status: angka dari daftar yang sama dengan tabel (setelah saringan jenis & cari).
  const q = search.trim().toLowerCase();
  const cocokLain = useCallback((a) => {
    if (filterType !== 'all' && a.adjustment_type !== filterType) return false;
    if (q) {
      const text = `${a.employee_name || ''} ${a.employee_code || ''} ${a.department || ''} ${a.reason || ''}`.toLowerCase();
      if (!text.includes(q)) return false;
    }
    return true;
  }, [filterType, q]);
  const dasar = useMemo(() => adjustments.filter(cocokLain), [adjustments, cocokLain]);
  const filtered = useMemo(() => dasar.filter(a => !filterStatus || a.status === filterStatus), [dasar, filterStatus]);
  const opsiStatus = [
    { key: '', label: 'Semua', count: dasar.length },
    ...Object.entries(STATUS_CFG).map(([k, c]) => ({ key: k, label: c.label, count: dasar.filter(a => a.status === k).length }))
      .filter(o => o.count > 0 || o.key === filterStatus),
  ];
  const disetujui = adjustments.filter(a => a.status === 'approved');
  const rataNaik = disetujui.length ? disetujui.reduce((s, a) => s + Number(a.raise_pct || 0), 0) / disetujui.length : null;
  const { page, setPage, totalPages, total, paged } = useClientPagination(filtered, 10);

  const jalankan = async (type, adj) => {
    if (type === 'approve_manager' || type === 'approve_hr') { setApproveDialog({ type, adj }); return; }
    const ringkas = `${adj.employee_name} (${adj.employee_code}): ${fmtCurrency(adj.current_base)} → ${fmtCurrency(adj.proposed_base)}, ${pctLabel(adj.raise_pct)}.`;
    let opts;
    if (type === 'reject') {
      const alasan = await confirmDialog({
        title: 'Tolak usulan kenaikan gaji?', body: ringkas,
        input: { label: 'Alasan penolakan', placeholder: 'Tulis alasan penolakan' },
        confirmLabel: 'Tolak', danger: true,
      });
      if (!alasan) return;
      opts = { endpoint: `/salary-adjustments/${adj.id}/reject`, method: 'POST', body: { reason: alasan } };
    } else {
      const ok = await confirmDialog({
        title: 'Batalkan usulan ini?', body: `${ringkas} Usulan yang dibatalkan tidak bisa disetujui lagi.`,
        confirmLabel: 'Batalkan usulan', cancelLabel: 'Kembali', danger: true,
      });
      if (!ok) return;
      opts = { endpoint: `/salary-adjustments/${adj.id}`, method: 'DELETE' };
    }
    try {
      const res = await fetchAPI(opts.endpoint, { method: opts.method, ...(opts.body ? { body: JSON.stringify(opts.body) } : {}) }, token);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Gagal');
      toast.success(data.message || 'Berhasil');
      setDetail(null);
      loadData();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (a) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{a.employee_name}</p>
        <p className="text-xs text-muted-foreground">{a.employee_code} · {a.department || '—'}</p>
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (a) => (
      <span className="text-sm">{TYPE_LABELS[a.adjustment_type] || a.adjustment_type}{a.kpi_grade ? ` · nilai ${a.kpi_grade}` : ''}</span>) },
    { kunci: 'atasan', label: 'Atasan', isi: (a) => (a.manager_name
      ? <span className="text-sm">{a.manager_name}</span> : <span className="text-sm text-muted-foreground">Tidak ada</span>) },
    { kunci: 'kini', label: 'Gaji saat ini', rata: 'kanan', isi: (a) => <span className="tabular-nums">{fmtCurrency(a.current_base)}</span> },
    { kunci: 'usul', label: 'Gaji usulan', rata: 'kanan', isi: (a) => <span className="font-medium tabular-nums">{fmtCurrency(a.proposed_base)}</span> },
    { kunci: 'naik', label: 'Kenaikan', rata: 'kanan', isi: (a) => <span className="tabular-nums text-[hsl(var(--success-text))]">{pctLabel(a.raise_pct)}</span> },
    { kunci: 'status', label: 'Status', isi: (a) => <StatusBadge status={a.status} /> },
    { kunci: 'tgl', label: 'Tanggal', isi: (a) => <span className="text-sm text-muted-foreground md:whitespace-nowrap">{fmtDate(a.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => {
      const daftar = aksiUsulan(a, isHR);
      const utama = daftar.find(t => t.startsWith('approve'));
      const lain = daftar.filter(t => t !== utama);
      return (
        <div className="flex items-center justify-end gap-1">
          {utama && (
            <Button size="sm" variant="success" onClick={() => jalankan(utama, a)} data-testid={`${AKSI_TESTID[utama]}-${a.id}`}>
              <CheckCircle2 />{utama === 'approve_hr' ? 'Setujui HR' : 'Setujui atasan'}
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label="Lainnya" data-testid={`adj-more-${a.id}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setDetail(a)} data-testid={`adj-view-${a.id}`}>
                <Eye className="mr-2 h-4 w-4" />Lihat rincian
              </DropdownMenuItem>
              {lain.map(t => (
                <DropdownMenuItem key={t} onSelect={() => jalankan(t, a)} data-testid={`${AKSI_TESTID[t]}-${a.id}`}
                  className={t === 'reject' || t === 'cancel' ? 'text-[hsl(var(--danger-text))]' : undefined}>
                  {t === 'reject' ? <XCircle className="mr-2 h-4 w-4" /> : t === 'cancel' ? <Trash2 className="mr-2 h-4 w-4" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                  {AKSI_LABEL[t]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      );
    } },
  ];

  return (
    <PageLayout testId="salary-adjustment-module" headerTestId="salary-adjustment-title" title="Penyesuaian gaji"
      subtitle="Usulan kenaikan gaji dengan persetujuan atasan lalu HR; dibuat manual atau dari hasil KPI."
      actions={isHR && <>
        <Button variant="outline" onClick={() => setGenerateOpen(true)} data-testid="adj-generate-from-kpi-btn"><Wand2 />Buat dari KPI</Button>
        <Button onClick={() => setCreateOpen(true)} data-testid="adj-create-btn"><Plus />Buat usulan</Button>
      </>}
      filters={<>
        <FilterChips options={opsiStatus} value={filterStatus} onChange={setFilterStatus} testId="adj-filter-status" ariaLabel="Status usulan" />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nama, kode, atau alasan" value={search} onChange={(e) => setSearch(e.target.value)}
            className="pl-8" data-testid="adj-search-input" />
        </div>
        <SmartNativeSelect value={filterType} onChange={(e) => setFilterType(e.target.value)} searchable={false}
          className="w-full sm:w-48" aria-label="Jenis penyesuaian" data-testid="adj-filter-type">
          <option value="all">Semua jenis</option>
          {Object.entries(TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="usulan-kenaikan-gaji" namaLembar="Usulan kenaikan" baris={filtered} testId="adj-unduh"
          kolom={[
            { label: 'Kode karyawan', nilai: (a) => a.employee_code || '' },
            { label: 'Nama', nilai: (a) => a.employee_name || '' },
            { label: 'Departemen', nilai: (a) => a.department || '' },
            { label: 'Jenis', nilai: (a) => TYPE_LABELS[a.adjustment_type] || a.adjustment_type || '' },
            { label: 'Nilai KPI', nilai: (a) => a.kpi_grade || '' },
            { label: 'Atasan', nilai: (a) => a.manager_name || '' },
            { label: 'Gaji saat ini (Rp)', nilai: (a) => Number(a.current_base || 0) },
            { label: 'Gaji usulan (Rp)', nilai: (a) => Number(a.proposed_base || 0) },
            { label: 'Kenaikan (%)', nilai: (a) => Number(Number(a.raise_pct || 0).toFixed(2)) },
            { label: 'Status', nilai: (a) => (STATUS_CFG[a.status] || STATUS_CFG.cancelled).label },
            { label: 'Tanggal', nilai: (a) => fmtDate(a.created_at) },
            { label: 'Alasan', nilai: (a) => a.reason || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={loadData} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="adj-refresh-btn"><RefreshCw className={loading ? 'animate-spin' : ''} /></Button>
      </>}
      summary={rataNaik !== null && (
        <p className="text-sm text-muted-foreground" data-testid="stat-avg-raise">
          Rata-rata kenaikan yang disetujui: <span className="font-medium text-foreground">{pctLabel(rataNaik)}</span> dari {disetujui.length} usulan.
        </p>
      )}
      footer={filtered.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
    >
      {adjustments.length >= 100 && (
        <Notice tone="info" title="Menampilkan 100 usulan terbaru.">Usulan yang lebih lama tidak ikut dimuat dan tidak ikut dihitung.</Notice>
      )}
      {loading && adjustments.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat usulan…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="adj-table"
          kosong={<EmptyState testId="adj-empty-state"
            title={adjustments.length ? 'Tidak ada usulan yang cocok' : 'Belum ada usulan kenaikan gaji'}
            description={adjustments.length ? 'Ubah saringan atau kata pencarian.'
              : isHR ? 'Tekan "Buat usulan" atau "Buat dari KPI" untuk memulai.' : 'Belum ada usulan yang menunggu persetujuan Anda.'} />} />
      )}

      {/* Create Manual Dialog */}
      <CreateManualDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        token={token}
        employees={employees}
        onSuccess={() => {
          setCreateOpen(false);
          loadData();
        }}
      />

      {/* Generate from KPI Dialog */}
      <GenerateFromKPIDialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        token={token}
        kpiPeriods={kpiPeriods}
        onSuccess={() => {
          setGenerateOpen(false);
          loadData();
        }}
      />

      {/* Persetujuan (atasan / HR) */}
      <ApproveDialog
        action={approveDialog}
        token={token}
        onClose={() => setApproveDialog(null)}
        onSuccess={() => {
          setApproveDialog(null);
          setDetail(null);
          loadData();
        }}
      />

      {/* Detail */}
      <DetailDialog adj={detail} isHR={isHR} onClose={() => setDetail(null)} onAksi={(t, a) => jalankan(t, a)} />
    </PageLayout>
  );
}

// ─── Create Manual Dialog ────────────────────────────────────────────────────
function CreateManualDialog({ open, onClose, token, employees, onSuccess }) {
  const [employeeId, setEmployeeId] = useState('');
  const [proposedBase, setProposedBase] = useState('');
  const [adjType, setAdjType] = useState('manual');
  const [reason, setReason] = useState('');
  const [effectiveDate, setEffectiveDate] = useState('');
  const [currentBase, setCurrentBase] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [galat, setGalat] = useState('');

  const selectedEmp = employees.find((e) => e.id === employeeId);

  // Fetch current payroll profile for selected employee
  useEffect(() => {
    if (!employeeId) {
      setCurrentBase(0);
      return;
    }
    fetchAPI(`/payroll-profiles?employee_id=${employeeId}`, {}, token)
      .then((r) => (r.ok ? r.json() : []))
      .then((profiles) => {
        const active = profiles.find((p) => p.active) || profiles[0];
        setCurrentBase(active?.base_rate || 0);
      })
      .catch(() => setCurrentBase(0));
  }, [employeeId, token]);

  const reset = () => {
    setEmployeeId('');
    setProposedBase('');
    setAdjType('manual');
    setReason('');
    setEffectiveDate('');
    setCurrentBase(0);
    setGalat('');
  };

  const handleSubmit = async () => {
    if (!employeeId) {
      setGalat('Pilih karyawan.');
      return;
    }
    const proposed = parseFloat(proposedBase);
    if (!proposed || proposed <= currentBase) {
      setGalat(`Gaji usulan harus lebih besar dari gaji saat ini (${fmtCurrency(currentBase)}).`);
      return;
    }
    setGalat('');
    setSubmitting(true);
    try {
      const res = await fetchAPI(
        '/salary-adjustments',
        {
          method: 'POST',
          body: JSON.stringify({
            employee_id: employeeId,
            proposed_base: proposed,
            adjustment_type: adjType,
            reason: reason || 'Manual adjustment by HR',
            effective_date: effectiveDate || null,
          }),
        },
        token
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Gagal membuat usulan');

      const noManager = !data.manager_id;
      toast.success(
        noManager
          ? 'Usulan dibuat. Karyawan belum punya atasan, langsung menunggu HR.'
          : 'Usulan dibuat. Menunggu persetujuan atasan.'
      );
      reset();
      onSuccess();
    } catch (e) {
      setGalat(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const naik = proposedBase && currentBase > 0 && parseFloat(proposedBase) > currentBase;
  return (
    <FormPopup open={open} onClose={() => { reset(); onClose(); }} ukuran="pendek" onSimpan={handleSubmit} menyimpan={submitting}
      judul="Buat usulan kenaikan gaji" keterangan="Usulan masuk persetujuan dua tahap: atasan, lalu HR."
      labelSimpan="Buat usulan" galat={galat} testId="create-adj-dialog">
      <Isian label="Karyawan" wajib htmlFor="emp-select"
        petunjuk={selectedEmp && !selectedEmp.manager_id ? 'Karyawan belum punya atasan. Usulan langsung menunggu persetujuan HR.' : undefined}>
        <SmartNativeSelect id="emp-select" value={employeeId} onChange={(ev) => setEmployeeId(ev.target.value)}
          searchable={true} searchPlaceholder="Cari kode atau nama..." data-testid="create-adj-employee-select">
          <option value="">Pilih karyawan</option>
          {employees
            .filter((e) => e.active !== false)
            .map((e) => (
              <option key={e.id} value={e.id}>
                {`${e.employee_code} · ${e.name} ${e.manager_name ? `(atasan: ${e.manager_name})` : '(tanpa atasan)'}`}
              </option>
            ))}
        </SmartNativeSelect>
      </Isian>

      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Gaji saat ini" petunjuk="Dari profil gaji aktif.">
          <Input value={fmtCurrency(currentBase)} readOnly tabIndex={-1} data-testid="create-adj-current-base" />
        </Isian>
        <Isian label="Gaji usulan (Rp)" wajib htmlFor="proposed-base"
          petunjuk={naik ? `${pctLabel(((parseFloat(proposedBase) - currentBase) / currentBase) * 100)} (${fmtCurrency(parseFloat(proposedBase) - currentBase)})` : undefined}>
          <MoneyInput
            id="proposed-base"
            value={proposedBase}
            onChange={(e) => setProposedBase(e.target.value)}
            placeholder="contoh: 5.500.000"
            data-testid="create-adj-proposed-base"
          />
        </Isian>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Jenis penyesuaian" htmlFor="adj-type">
          <SmartNativeSelect id="adj-type" value={adjType} onChange={(e) => setAdjType(e.target.value)} searchable={false}
            data-testid="create-adj-type-select">
            {Object.entries(TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tanggal berlaku (opsional)">
          <DatePicker value={effectiveDate} onChange={setEffectiveDate} placeholder="Saat disetujui HR"
            testId="create-adj-effective-date" />
        </Isian>
      </div>

      <Isian label="Alasan" htmlFor="reason">
        <Textarea
          id="reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Misal: promosi, kinerja menonjol."
          rows={3}
          data-testid="create-adj-reason"
        />
      </Isian>
    </FormPopup>
  );
}

// ─── Generate from KPI Dialog ────────────────────────────────────────────────
const periodeLabel = (p) => {
  const nama = p.period_label || p.name || 'Periode KPI';
  if (p.month && p.year) return `${nama} (${p.month}/${p.year})`;
  if (p.period_from || p.period_to) return `${nama} (${fmtDate(p.period_from)} – ${fmtDate(p.period_to)})`;
  return nama;
};

function GenerateFromKPIDialog({ open, onClose, token, kpiPeriods, onSuccess }) {
  const [periodId, setPeriodId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [galat, setGalat] = useState('');

  const handleGenerate = async () => {
    if (!periodId) {
      setGalat('Pilih periode KPI dulu.');
      return;
    }
    setGalat('');
    setSubmitting(true);
    setResult(null);
    try {
      const res = await fetchAPI(
        `/salary-adjustments/generate-from-kpi/${periodId}`,
        { method: 'POST' },
        token
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Gagal membuat usulan');
      setResult(data);
      toast.success(data.message || `Berhasil membuat ${data.created} usulan`);
    } catch (e) {
      setGalat(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const reset = () => {
    setPeriodId('');
    setResult(null);
    setGalat('');
  };

  if (open && result) {
    const sr = result.skipped_reasons || {};
    return (
      <DetailPopup open onClose={() => { reset(); onSuccess(); }} judul="Usulan dari KPI selesai dibuat" testId="generate-kpi-dialog"
        keterangan={`Berhasil dibuat: ${result.created ?? 0} · dilewati: ${result.skipped ?? 0}`}
        aksi={<Button size="sm" onClick={() => { reset(); onSuccess(); }} data-testid="generate-close-btn">Tutup &amp; muat ulang</Button>}>
        {Object.values(sr).some((v) => v > 0) && (
          <dl className="divide-y divide-[var(--glass-border)]">
            {sr.duplicate_active > 0 && <BarisDetail label="Sudah ada usulan aktif">{sr.duplicate_active}</BarisDetail>}
            {sr.no_payroll_profile > 0 && <BarisDetail label="Belum punya profil gaji">{sr.no_payroll_profile}</BarisDetail>}
            {sr.employee_not_found > 0 && <BarisDetail label="Karyawan tidak ditemukan">{sr.employee_not_found}</BarisDetail>}
            {sr.raise_pct_zero > 0 && <BarisDetail label="Nilai KPI tidak memenuhi">{sr.raise_pct_zero}</BarisDetail>}
          </dl>
        )}
        {result.created_items && result.created_items.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow><TableHead>Karyawan</TableHead><TableHead className="text-right">Kenaikan</TableHead><TableHead>Status</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {result.created_items.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>{c.employee_name}</TableCell>
                  <TableCell className="text-right tabular-nums text-[hsl(var(--success-text))]">{pctLabel(c.raise_pct, 0)}</TableCell>
                  <TableCell><StatusBadge status={c.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DetailPopup>
    );
  }

  return (
    <FormPopup open={open} onClose={() => { reset(); onClose(); }} ukuran="pendek" onSimpan={handleGenerate} menyimpan={submitting}
      judul="Buat usulan kenaikan dari KPI" labelSimpan="Buat usulan" galat={galat} bisaSimpan={kpiPeriods.length > 0}
      keterangan="Untuk semua karyawan dengan nilai KPI A (naik 10%) atau B (naik 7%) pada periode terpilih. Karyawan yang sudah punya usulan aktif dilewati."
      testId="generate-kpi-form">
      <Isian label="Periode KPI (yang sudah final)" htmlFor="kpi-period">
        <SmartNativeSelect id="kpi-period" value={periodId} onChange={(e) => setPeriodId(e.target.value)} disabled={kpiPeriods.length === 0}
          data-testid="generate-period-select">
          <option value="">{kpiPeriods.length ? 'Pilih periode KPI' : 'Belum ada periode KPI yang final'}</option>
          {kpiPeriods.map((p) => <option key={p.period_id} value={p.period_id}>{periodeLabel(p)}</option>)}
        </SmartNativeSelect>
      </Isian>
      {kpiPeriods.length === 0 && (
        <Notice tone="warning" title="Belum ada periode KPI yang final.">
          Buka modul KPI dan selesaikan dulu hasil periode yang ingin dipakai.
        </Notice>
      )}
    </FormPopup>
  );
}

// ─── Persetujuan atasan / HR ─────────────────────────────────────────────────
function ApproveDialog({ action, token, onClose, onSuccess }) {
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [galat, setGalat] = useState('');

  useEffect(() => {
    setNotes('');
    setGalat('');
  }, [action]);

  if (!action) return null;
  const { type, adj } = action;
  const config = {
    approve_manager: {
      title: 'Setujui sebagai atasan',
      description: 'Sesudah disetujui, usulan diteruskan ke HR untuk persetujuan akhir.',
      endpoint: `/salary-adjustments/${adj.id}/approve-manager`,
      submitLabel: 'Setujui',
    },
    approve_hr: {
      title: 'Setujui sebagai HR (akhir)',
      description: `Sesudah disetujui HR, gaji ${adj.employee_name} di profil gaji otomatis menjadi ${fmtCurrency(adj.proposed_base)}.`,
      endpoint: `/salary-adjustments/${adj.id}/approve-hr`,
      submitLabel: 'Setujui & terapkan',
    },
  }[type];
  if (!config) return null;

  const handleSubmit = async () => {
    setSubmitting(true);
    setGalat('');
    try {
      const res = await fetchAPI(config.endpoint, { method: 'POST', body: JSON.stringify({ notes }) }, token);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Gagal');
      toast.success(data.message || 'Berhasil');
      onSuccess();
    } catch (e) {
      setGalat(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <FormPopup open={!!action} onClose={onClose} ukuran="pendek" onSimpan={handleSubmit} menyimpan={submitting}
      judul={config.title} keterangan={config.description} labelSimpan={config.submitLabel} galat={galat} testId="action-dialog">
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Karyawan">{adj.employee_name} ({adj.employee_code})</BarisDetail>
        <BarisDetail label="Gaji saat ini"><span className="tabular-nums">{fmtCurrency(adj.current_base)}</span></BarisDetail>
        <BarisDetail label="Gaji usulan"><span className="font-medium tabular-nums">{fmtCurrency(adj.proposed_base)}</span></BarisDetail>
        <BarisDetail label="Kenaikan"><span className="text-[hsl(var(--success-text))]">{pctLabel(adj.raise_pct)}</span></BarisDetail>
      </dl>
      <Isian label="Catatan (opsional)" htmlFor="action-notes">
        <Textarea id="action-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
          placeholder="Catatan" data-testid="action-notes-input" />
      </Isian>
    </FormPopup>
  );
}

// ─── Detail ──────────────────────────────────────────────────────────────────
function DetailDialog({ adj, isHR, onClose, onAksi }) {
  if (!adj) return null;
  const daftar = aksiUsulan(adj, isHR);
  return (
    <DetailPopup open onClose={onClose} judul={`Usulan kenaikan gaji — ${adj.employee_name}`} testId="detail-dialog"
      keterangan={`${adj.employee_code} · ${adj.department || 'tanpa departemen'}`}
      status={<StatusBadge status={adj.status} />}
      aksi={daftar.length > 0 && daftar.map((t) => (
        <Button key={t} size="sm" data-testid={`detail-${AKSI_TESTID[t]}`}
          variant={t.startsWith('approve') ? 'success' : t === 'reject' ? 'destructive' : 'outline'}
          onClick={() => onAksi(t, adj)}>{AKSI_LABEL[t]}</Button>
      ))}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Jenis">{TYPE_LABELS[adj.adjustment_type] || adj.adjustment_type}</BarisDetail>
        <BarisDetail label="Atasan">{adj.manager_name || '—'}</BarisDetail>
        {adj.kpi_grade && <BarisDetail label="Nilai KPI">{adj.kpi_grade} (skor {Number(adj.kpi_final_score || 0).toFixed(1).replace('.', ',')})</BarisDetail>}
        <BarisDetail label="Gaji saat ini"><span className="tabular-nums">{fmtCurrency(adj.current_base)}</span></BarisDetail>
        <BarisDetail label="Gaji usulan"><span className="font-medium tabular-nums">{fmtCurrency(adj.proposed_base)}</span></BarisDetail>
        <BarisDetail label="Kenaikan">{pctLabel(adj.raise_pct)} ({fmtCurrency(adj.raise_amount)})</BarisDetail>
        {adj.effective_date && <BarisDetail label="Tanggal berlaku">{fmtDate(adj.effective_date)}</BarisDetail>}
        <BarisDetail label="Alasan">{adj.reason || '—'}</BarisDetail>
        <BarisDetail label="Dibuat">{adj.created_by_name || '—'} · {fmtDate(adj.created_at)}</BarisDetail>
        {adj.manager_approved_at && (
          <BarisDetail label="Disetujui atasan">
            {adj.manager_approved_by_name} · {fmtDate(adj.manager_approved_at)}
            {adj.manager_notes && <span className="block text-muted-foreground">“{adj.manager_notes}”</span>}
          </BarisDetail>
        )}
        {adj.hr_approved_at && (
          <BarisDetail label="Disetujui HR">
            {adj.hr_approved_by_name} · {fmtDate(adj.hr_approved_at)}
            {adj.hr_notes && <span className="block text-muted-foreground">“{adj.hr_notes}”</span>}
          </BarisDetail>
        )}
        {adj.applied_at && (
          <BarisDetail label="Diterapkan ke profil gaji"><span className="text-[hsl(var(--success-text))]">{fmtDate(adj.applied_at)}</span></BarisDetail>
        )}
        {adj.rejected_at && (
          <BarisDetail label={`Ditolak oleh ${PERAN_LABEL[adj.rejected_by_role] || adj.rejected_by_role || '—'}`}>
            <span className="text-[hsl(var(--danger-text))]">{adj.rejected_by_name} · {fmtDate(adj.rejected_at)}</span>
            {adj.rejection_reason && <span className="block text-muted-foreground">“{adj.rejection_reason}”</span>}
          </BarisDetail>
        )}
      </dl>
    </DetailPopup>
  );
}
