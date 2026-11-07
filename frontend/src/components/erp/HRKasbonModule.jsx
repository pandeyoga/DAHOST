/**
 * HRKasbonModule — Portal SDM › Kasbon: tinjau pengajuan kasbon & pinjaman karyawan dan pantau sisanya.
 *
 * F13-B (sesi #12) — antrian kasbon dulu hanya kartu; kini tabel yang bisa diurutkan, berhalaman, dan diunduh.
 * Angka ini adalah UTANG KARYAWAN yang akan dipotong dari gaji; menyalinnya ulang dengan tangan ke Excel adalah
 * sumber salah-ketik yang paling mahal di modul ini.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris (status · urutan · cari), daftar =
 * TabelData (kartu ringkas di HP), detail = popup, tinjauan = FormPopup (Setujui hijau; Tolak merah lewat
 * konfirmasi beralasan), unduh Excel + CSV, kartu angka hanya bila ada isinya.
 * Perbaikan ikut: daftar dulu dimuat `limit=100` — pengajuan ke-101 dst. tidak tampil sama sekali. Kini 500
 * (batas server) + pemberitahuan bila masih ada yang belum termuat.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { toast } from 'sonner';
import { ArrowDownWideNarrow, ArrowUpNarrowWide, CheckCircle2, RefreshCw, Search, XCircle } from 'lucide-react';
import { formatRupiah, formatDateID } from '@/lib/format';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { MoneyInput } from '@/components/ui/money-input';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import ViewToggle from '@/components/ui/view-toggle';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const HRKASBON_VIEW_KEY = 'hr_kasbon_view';
const BATAS_MUAT = 500; // batas `limit` server untuk /api/dewi/kasbon/requests

const API = process.env.REACT_APP_BACKEND_URL;
const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('erp_token')}`, 'Content-Type': 'application/json' });
const fmt = formatRupiah;
const fmtDate = (d) => formatDateID(d);

const STATUS_CFG = {
  submitted:   { label: 'Menunggu HR',       tone: 'warning' },
  hr_approved: { label: 'Disetujui HR',      tone: 'info' },
  hr_rejected: { label: 'Ditolak HR',        tone: 'danger' },
  disbursed:   { label: 'Aktif (dicairkan)', tone: 'primary' },
  paid_off:    { label: 'Lunas',             tone: 'success' },
  cancelled:   { label: 'Dibatalkan',        tone: 'muted' },
};
const labelStatus = (s) => STATUS_CFG[s]?.label || 'Status lain';

function KasbonStatus({ status }) {
  const cfg = STATUS_CFG[status] || { label: labelStatus(status), tone: 'default' };
  return <StatusBadge status={status} label={cfg.label} tone={cfg.tone} />;
}

// Urutan: semua kolom yang dulu bisa diklik di kepala tabel, plus arah naik/turun.
const URUTAN = [
  ['amount', 'Jumlah'], ['created_at', 'Tanggal diajukan'], ['outstanding_balance', 'Sisa'],
  ['installment_amount', 'Cicilan/bulan'], ['employee_name', 'Nama karyawan'], ['employee_code', 'Kode karyawan'],
  ['department', 'Departemen'], ['request_number', 'No. pengajuan'], ['type_label', 'Jenis'],
  ['purpose', 'Keperluan'], ['status', 'Status'],
];

// ─── Tinjau pengajuan (popup form) ────────────────────────────────────────────
function ReviewModal({ req, onClose, onDone }) {
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  // 2026-11-02 (K25): nilai disetujui ≤ nilai diminta (backend juga menegakkan batas kasbon & pengaju ≠ penyetuju).
  const [approvedAmount, setApprovedAmount] = useState(req.amount);
  const tooHigh = Number(approvedAmount) > Number(req.amount);

  const kirim = async (action, catatan) => {
    setSaving(true); setGalat('');
    try {
      const body = { action, notes: catatan };
      if (action === 'approve' && Number(approvedAmount) !== Number(req.amount)) body.approved_amount = Number(approvedAmount);
      const r = await fetch(`${API}/api/dewi/kasbon/requests/${req.id}/hr-review`, {
        method: 'PATCH', headers: authH(),
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.ok) {
        toast.success(action === 'approve' ? 'Pengajuan disetujui' : 'Pengajuan ditolak');
        onDone();
      } else setGalat(typeof d.detail === 'string' ? d.detail : 'Gagal menyimpan tinjauan.');
    } catch (_e) { setGalat('Terjadi kesalahan. Coba lagi.'); }
    finally { setSaving(false); }
  };

  const tolak = async () => {
    const alasan = await confirmDialog({
      title: 'Tolak pengajuan ini?',
      body: `${req.employee_name} · ${fmt(req.amount)}. Alasan dikirim ke karyawan.`,
      input: { label: 'Alasan penolakan', placeholder: 'Jelaskan alasan penolakan…' },
      confirmLabel: 'Tolak', danger: true,
    });
    if (!alasan) return;
    await kirim('reject', alasan);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="kasbon-review"
      judul="Tinjau pengajuan" keterangan="Setujui dengan nilai yang sama atau lebih kecil, atau tolak dengan alasan."
      onSimpan={() => kirim('approve', notes)} labelSimpan="Setujui" menyimpan={saving} galat={galat}
      bisaSimpan={!tooHigh && Number(approvedAmount) > 0}
      aksiKiri={<Button type="button" variant="destructive" onClick={tolak} disabled={saving} data-testid="kasbon-review-reject">
        <XCircle />Tolak</Button>}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Karyawan">{req.employee_name}</BarisDetail>
        <BarisDetail label="Departemen">{req.department || '—'}</BarisDetail>
        <BarisDetail label="Jenis">{req.type_label || req.type}</BarisDetail>
        <BarisDetail label="Jumlah diminta"><span className="font-semibold tabular-nums">{fmt(req.amount)}</span></BarisDetail>
        {req.installment_count > 1 && <BarisDetail label="Cicilan">{req.installment_count}× {fmt(req.installment_amount)}</BarisDetail>}
        <BarisDetail label="Keperluan">{req.purpose || '—'}</BarisDetail>
        {req.documents?.length > 0 && <BarisDetail label="Dokumen">{req.documents.length} berkas</BarisDetail>}
      </dl>
      {(req.limit_warnings || []).length > 0 && (
        <Notice tone="warning" title="Perhatian batas kasbon">{req.limit_warnings.join(' ')}</Notice>
      )}
      <Isian label={`Nilai disetujui (maks ${fmt(req.amount)})`} htmlFor="kasbon-nilai"
        galat={tooHigh ? 'Tidak boleh melebihi nilai yang diminta.' : undefined}>
        {/* Tahap 5 (2026-11-07): nominal uang memakai MoneyInput (pemisah ribuan), bukan input angka polos */}
        <MoneyInput id="kasbon-nilai" value={approvedAmount}
          onChange={e => setApprovedAmount(e.target.value)} data-testid="kasbon-approved-amount" />
      </Isian>
      <Isian label="Catatan" petunjuk="Opsional. Tampil bagi karyawan dan Keuangan." htmlFor="kasbon-catatan">
        <Textarea id="kasbon-catatan" rows={3} value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="Tambahkan catatan…" />
      </Isian>
    </FormPopup>
  );
}

// ─── Kartu ringkas (tampilan kartu) ───────────────────────────────────────────
function RequestCard({ req, onOpen, onReview }) {
  return (
    <div onClick={() => onOpen(req)} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') onOpen(req); }}
      className="cursor-pointer rounded-lg border border-[var(--glass-border)] bg-[var(--card-surface)] p-3 hover:border-[hsl(var(--primary)/0.4)]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{req.employee_name}</p>
          <p className="truncate text-xs text-muted-foreground">{req.request_number} · {req.type_label || req.type}</p>
        </div>
        <KasbonStatus status={req.status} />
      </div>
      <p className="mt-1 truncate text-xs text-muted-foreground" title={req.purpose}>{req.purpose || '—'}</p>
      <div className="mt-2 flex items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold tabular-nums text-foreground">{fmt(req.amount)}</p>
          <p className="text-xs text-muted-foreground">{fmtDate(req.created_at)}</p>
        </div>
        {req.status === 'submitted' && (
          <Button size="sm" onClick={(e) => { e.stopPropagation(); onReview(req); }} data-testid={`hr-review-btn-${req.id}`}>
            Tinjau
          </Button>
        )}
      </div>
    </div>
  );
}

// ─── Halaman ──────────────────────────────────────────────────────────────────
export default function HRKasbonModule() {
  const [requests, setRequests] = useState([]);
  const [totalServer, setTotalServer] = useState(0);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('submitted');
  const [search, setSearch] = useState('');
  const [reviewReq, setReviewReq] = useState(null);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [rReqs, rStats] = await Promise.all([
        fetch(`${API}/api/dewi/kasbon/requests?limit=${BATAS_MUAT}`, { headers: authH() }),
        fetch(`${API}/api/dewi/kasbon/stats`, { headers: authH() }),
      ]);
      const [dReqs, dStats] = await Promise.all([rReqs.json(), rStats.json()]);
      if (dReqs.ok) { setRequests(dReqs.requests || []); setTotalServer(Number(dReqs.total) || 0); }
      if (dStats.ok) setStats(dStats.stats || {});
    } catch (_e) { toast.error('Gagal memuat pengajuan kasbon.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // 2026-11-02 (P5 butir 9): tombol "Muat Demo" (POST /api/dewi/kasbon/seed) DIHAPUS — membuat 5 kasbon
  // palsu atas nama karyawan nyata di data produksi; payroll lalu ikut memotong gaji untuk pinjaman palsu.

  const filtered = requests.filter(r => {
    const matchStatus = !filterStatus || filterStatus === 'all' || r.status === filterStatus;
    const q = search.toLowerCase();
    const matchSearch = !q || r.employee_name?.toLowerCase().includes(q) || r.request_number?.toLowerCase().includes(q) || r.purpose?.toLowerCase().includes(q);
    return matchStatus && matchSearch;
  });

  // Pilihan tampilan DIINGAT antar kunjungan.
  const [view, setView] = useState(() => {
    try { return localStorage.getItem(HRKASBON_VIEW_KEY) || 'table'; } catch { return 'table'; }
  });
  useEffect(() => {
    try { localStorage.setItem(HRKASBON_VIEW_KEY, view); } catch { /* penyimpanan diblokir */ }
  }, [view]);
  const [sort, setSort] = useState({ key: 'amount', dir: 'desc' });

  // Yang diurutkan = yang TERLIHAT, dan yang diunduh = yang terlihat juga.
  const rows = useMemo(() => {
    const list = [...filtered];
    const { key, dir } = sort;
    list.sort((a, b) => {
      const av = a?.[key], bv = b?.[key];
      const num = typeof av === 'number' || typeof bv === 'number';
      const cmp = num ? (Number(av || 0) - Number(bv || 0))
        : String(av ?? '').localeCompare(String(bv ?? ''), 'id');
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [filtered, sort]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 12);

  const hitung = (s) => requests.filter((r) => r.status === s).length;
  const opsiStatus = [
    { key: 'all', label: 'Semua status', count: requests.length },
    ...Object.entries(STATUS_CFG).map(([k, c]) => ({ key: k, label: c.label, count: hitung(k) })),
  ];

  const kolomUnduh = [
    { label: 'No. pengajuan', nilai: (r) => r.request_number },
    { label: 'Karyawan', nilai: (r) => r.employee_name },
    { label: 'Kode', nilai: (r) => r.employee_code || '' },
    { label: 'Departemen', nilai: (r) => r.department || '' },
    { label: 'Jenis', nilai: (r) => r.type_label || r.type || '' },
    { label: 'Keperluan', nilai: (r) => r.purpose || '' },
    { label: 'Status', nilai: (r) => labelStatus(r.status) },
    { label: 'Jumlah', nilai: (r) => Number(r.amount ?? 0) },
    { label: 'Terbayar', nilai: (r) => Number(r.paid_amount ?? 0) },
    { label: 'Sisa', nilai: (r) => Number(r.outstanding_balance ?? 0) },
    { label: 'Cicilan per bulan', nilai: (r) => Number(r.installment_amount ?? 0) },
    { label: 'Jumlah cicilan', nilai: (r) => Number(r.installment_count ?? 0) },
    { label: 'Diajukan', nilai: (r) => fmtDate(r.created_at) },
    { label: 'Catatan HR', nilai: (r) => r.hr_notes || '' },
  ];

  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{r.employee_name}</p>
        <p className="text-xs text-muted-foreground">{[r.employee_code, r.department].filter(Boolean).join(' · ') || '—'}</p>
      </div>) },
    { kunci: 'nomor', label: 'No. pengajuan', hp: 'keterangan', isi: (r) => (
      <span className="whitespace-nowrap font-mono text-xs">{r.request_number}</span>) },
    { kunci: 'jenis', label: 'Jenis', isi: (r) => r.type_label || r.type || '—' },
    { kunci: 'keperluan', label: 'Keperluan', hp: false, isi: (r) => (
      <span className="block max-w-[14rem] truncate" title={r.purpose}>{r.purpose || '—'}</span>) },
    { kunci: 'status', label: 'Status', isi: (r) => <KasbonStatus status={r.status} /> },
    { kunci: 'jumlah', label: 'Jumlah', rata: 'kanan', isi: (r) => (
      <span className="whitespace-nowrap font-semibold tabular-nums">{fmt(r.amount)}</span>) },
    { kunci: 'sisa', label: 'Sisa', rata: 'kanan', isi: (r) => (
      <span className="whitespace-nowrap tabular-nums">{fmt(r.outstanding_balance || 0)}</span>) },
    { kunci: 'cicilan', label: 'Cicilan/bulan', rata: 'kanan', hp: false, isi: (r) => (
      <span className="whitespace-nowrap tabular-nums">{r.installment_amount ? fmt(r.installment_amount) : '—'}</span>) },
    { kunci: 'diajukan', label: 'Diajukan', isi: (r) => <span className="whitespace-nowrap">{fmtDate(r.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (r.status === 'submitted' ? (
      <Button size="sm" onClick={() => setReviewReq(r)} data-testid={`hr-review-btn-${r.id}`}>Tinjau</Button>
    ) : null) },
  ];

  const s = stats || {};
  const adaAngka = stats && [s.pending_hr, s.pending_finance, s.total_outstanding, s.this_month_requests].some((v) => Number(v) > 0);
  const kosong = (
    <EmptyState
      title={requests.length ? 'Tidak ada pengajuan yang cocok' : 'Belum ada pengajuan kasbon'}
      description={requests.length ? 'Ubah status atau kata pencarian.' : 'Pengajuan dari karyawan (Portal Saya › Kasbon) akan muncul di sini.'} />
  );

  return (
    <PageLayout testId="hr-kasbon-module" title="Kasbon"
      subtitle="Tinjau pengajuan kasbon dan pinjaman karyawan, lalu pantau sisa pinjaman yang dipotong dari gaji."
      filters={<>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} searchable={false}
          data-testid="hrkasbon-filter-status" className="h-9 w-full sm:w-48" aria-label="Status">
          {opsiStatus.map((o) => <option key={o.key} value={o.key}>{`${o.label} (${o.count})`}</option>)}
        </SmartNativeSelect>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <SmartNativeSelect value={sort.key} searchable={false} className="h-9 min-w-0 flex-1 sm:w-48 sm:flex-none"
            aria-label="Urutkan menurut" data-testid="hrkasbon-sort"
            onChange={e => setSort((s) => ({ key: e.target.value, dir: s.dir }))}>
            {URUTAN.map(([k, l]) => <option key={k} value={k}>{`Urut: ${l}`}</option>)}
          </SmartNativeSelect>
          <Button variant="outline" size="icon" data-testid="hrkasbon-sort-dir"
            onClick={() => setSort((s) => ({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }))}
            title={sort.dir === 'asc' ? 'Urutan naik (kecil ke besar, A–Z). Klik untuk membalik.' : 'Urutan turun (besar ke kecil, Z–A). Klik untuk membalik.'}
            aria-label={sort.dir === 'asc' ? 'Urutan naik, klik untuk membalik' : 'Urutan turun, klik untuk membalik'}>
            {sort.dir === 'asc' ? <ArrowUpNarrowWide /> : <ArrowDownWideNarrow />}
          </Button>
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari karyawan, nomor, keperluan"
            data-testid="hrkasbon-search" className="pl-8" />
        </div>
      </>}
      tools={<>
        <TombolUnduh label={<span className="hidden sm:inline">Unduh</span>} namaBerkas="pengajuan-kasbon-hr" namaLembar="Kasbon" baris={rows} kolom={kolomUnduh}
          testId="hrkasbon-export" />
        <div className="hidden sm:block"><ViewToggle value={view} onChange={setView} testId="hrkasbon-view" /></div>
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={adaAngka ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="hrkasbon-stats">
          <StatTile label="Menunggu tinjauan HR" value={s.pending_hr || 0} suffix="pengajuan"
            accent={s.pending_hr ? 'warning' : 'default'} sub="Status Menunggu HR, semua karyawan." />
          <StatTile label="Menunggu pencairan" value={s.pending_finance || 0} suffix="pengajuan"
            sub="Sudah disetujui HR, belum dicairkan Keuangan." />
          <StatTile label="Sisa pinjaman aktif" value={fmt(s.total_outstanding || 0)}
            sub="Jumlah sisa kasbon yang sudah dicairkan dan belum lunas." />
          <StatTile label="Diajukan bulan ini" value={s.this_month_requests || 0} suffix="pengajuan"
            sub="Semua status, bulan berjalan (WIB)." />
        </div>
      ) : null}
      footer={rows.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {totalServer > requests.length && (
        <Notice tone="warning" title={`Baru ${requests.length} dari ${totalServer} pengajuan yang termuat`}>
          Pengajuan terlama belum tampil. Saring per status untuk melihatnya.
        </Notice>
      )}
      {loading && requests.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat pengajuan…</p>
      ) : view === 'grid' ? (
        rows.length === 0 ? kosong : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" data-testid="hrkasbon-grid">
            {paged.map((r) => <RequestCard key={r.id} req={r} onOpen={setDetail} onReview={setReviewReq} />)}
          </div>
        )
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={setDetail} testId="hrkasbon-table" kosong={kosong} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="hrkasbon-detail"
          judul={`${detail.request_number} · ${detail.employee_name}`} status={<KasbonStatus status={detail.status} />}
          aksi={detail.status === 'submitted' && (
            <Button size="sm" onClick={() => { setReviewReq(detail); setDetail(null); }}>
              <CheckCircle2 />Tinjau
            </Button>
          )}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Karyawan">{detail.employee_name}{detail.employee_code ? ` · ${detail.employee_code}` : ''}</BarisDetail>
            <BarisDetail label="Departemen">{detail.department || '—'}</BarisDetail>
            <BarisDetail label="Jenis">{detail.type_label || detail.type || '—'}</BarisDetail>
            <BarisDetail label="Keperluan">{detail.purpose || '—'}</BarisDetail>
            <BarisDetail label="Jumlah"><span className="font-semibold tabular-nums">{fmt(detail.amount)}</span></BarisDetail>
            <BarisDetail label="Terbayar"><span className="tabular-nums">{fmt(detail.paid_amount || 0)}</span></BarisDetail>
            <BarisDetail label="Sisa"><span className="tabular-nums">{fmt(detail.outstanding_balance || 0)}</span></BarisDetail>
            <BarisDetail label="Cicilan">
              {detail.installment_amount ? `${detail.installment_count || 1}× ${fmt(detail.installment_amount)}` : '—'}
            </BarisDetail>
            <BarisDetail label="Diajukan">{fmtDate(detail.created_at)}</BarisDetail>
            {detail.documents?.length > 0 && <BarisDetail label="Dokumen">{detail.documents.length} berkas</BarisDetail>}
            {detail.hr_notes && <BarisDetail label="Catatan HR">{detail.hr_notes}</BarisDetail>}
          </dl>
        </DetailPopup>
      )}

      {reviewReq && (
        <ReviewModal req={reviewReq} onClose={() => setReviewReq(null)}
          onDone={() => { setReviewReq(null); load(); }} />
      )}
    </PageLayout>
  );
}
