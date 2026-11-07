/**
 * Approval Bertingkat (Portal SDM) — persetujuan bertingkat lintas departemen.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar = tabel (kartu ringkas di HP) + unduh Excel/CSV,
 * detail = popup (catatan, Setujui hijau, Tolak merah), kartu angka StatTile dengan keterangan, bahasa Indonesia.
 * Dulu: kartu besar berulang (tiga kolom), kotak warna-warni, <select>/<button> buatan sendiri,
 * daftar "Semua" diam-diam hanya 50 ajuan pertama (kini berhalaman, unduhan = semua baris).
 */
import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { CheckCircle, ExternalLink, RefreshCw, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import HubTabs from './hubs/HubTabs';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const UKURAN_HALAMAN = 50;

// Map approval type → module ID untuk link-back
const DOMAIN_MODULE_MAP = {
  leave:             'hr-leave',
  overtime:          'hr-overtime',
  salary_adjustment: 'hr-salary-adjustment',
  material_return:   'prod-material-return',
  purchase_order:    'procurement-po',
  resignation:       'hr-employee',
  expense:           'hr-expense-claims',
  asset_purchase:    'fin-assets',
};

const STATUS = {
  pending:   { label: 'Menunggu',   tone: 'warning' },
  approved:  { label: 'Disetujui',  tone: 'success' },
  rejected:  { label: 'Ditolak',    tone: 'danger' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
  skipped:   { label: 'Dilewati',   tone: 'muted' },
};
const labelStatus = (s) => (STATUS[s] || { label: s || '—' }).label;
function Status({ status }) {
  const c = STATUS[status] || { label: status || '—', tone: 'default' };
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

const TYPE_LABELS = {
  leave: 'Cuti', overtime: 'Lembur', salary_adjustment: 'Penyesuaian gaji',
  expense: 'Klaim biaya', purchase_order: 'PO pembelian',
  material_return: 'Retur material', resignation: 'Pengunduran diri',
  asset_purchase: 'Pembelian aset',
};
const labelJenis = (t) => TYPE_LABELS[t] || 'Lainnya';

// Data tambahan ajuan: kunci program → label yang dipahami staf (kunci teknis disembunyikan).
const META_LABEL = {
  priority: 'Prioritas', amount: 'Jumlah', total_amount: 'Jumlah', days: 'Jumlah hari', reason: 'Alasan',
  note: 'Catatan', start_date: 'Mulai', end_date: 'Selesai', department: 'Departemen', employee_name: 'Karyawan',
};
const META_SEMBUNYI = new Set(['link_module']);
const labelMeta = (k) => META_LABEL[k] || (String(k).charAt(0).toUpperCase() + String(k).slice(1)).replace(/_/g, ' ');
const nilaiMeta = (k, v) => {
  if (k === 'priority') return v === 'urgent' ? 'Mendesak' : v === 'normal' ? 'Biasa' : String(v);
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'object') return Array.isArray(v) ? v.join(', ') : Object.entries(v).map(([a, b]) => `${a}: ${b}`).join(' · ');
  if (typeof v === 'boolean') return v ? 'Ya' : 'Tidak';
  return String(v);
};

const tanggal = (d) => (d ? formatDateID(d) : '—');
const tahap = (it) => {
  if (!it.levels?.length) return '—';
  const aktif = it.levels.find((l) => l.status === 'pending');
  return `${it.current_level || 0}/${it.max_level || it.levels.length}${aktif ? ` · ${aktif.label}` : ''}`;
};

// ── Detail (popup) ────────────────────────────────────────────────────────────
function DetailAjuan({ item, onClose, onApprove, onReject, isManager, onModuleChange }) {
  const [note, setNote] = useState('');
  const [acting, setActing] = useState(false);

  const handleAction = async (action) => {
    setActing(true);
    const ok = await (action === 'approve' ? onApprove : onReject)(item.id, note);
    setActing(false);
    if (ok) onClose();
  };
  const meta = Object.entries(item.meta || {}).filter(([k]) => !META_SEMBUNYI.has(k));

  return (
    <DetailPopup open onClose={onClose} testId="approval-detail-modal"
      judul={item.subject || item.ref_code || 'Ajuan'}
      keterangan={[item.ref_code, item.chain_name].filter(Boolean).join(' · ')}
      status={<Status status={item.status} />}
      aksi={onModuleChange && DOMAIN_MODULE_MAP[item.type] ? (
        <Button size="sm" variant="outline" data-testid="approval-detail-openentity"
          onClick={() => { onClose(); onModuleChange(DOMAIN_MODULE_MAP[item.type]); }}>
          <ExternalLink />Lihat data asli
        </Button>) : null}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Jenis">{labelJenis(item.type)}</BarisDetail>
        <BarisDetail label="Pemohon">{item.requester_name || '—'}</BarisDetail>
        <BarisDetail label="Diajukan">{tanggal(item.created_at)}</BarisDetail>
        {meta.map(([k, v]) => <BarisDetail key={k} label={labelMeta(k)}>{nilaiMeta(k, v)}</BarisDetail>)}
      </dl>

      <div>
        <p className="mb-2 text-sm font-medium text-foreground">
          Alur persetujuan ({item.current_level || 0}/{item.max_level || item.levels?.length || 0})
        </p>
        <ol className="divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
          {(item.levels || []).map((lv) => (
            <li key={lv.level} className="flex items-start gap-3 px-3 py-2">
              <span className="w-6 shrink-0 text-sm font-semibold tabular-nums text-muted-foreground">{lv.level}.</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{lv.label}</p>
                {lv.approver_name && <p className="text-xs text-muted-foreground">{lv.approver_name}</p>}
                {lv.note && <p className="text-xs italic text-muted-foreground">&ldquo;{lv.note}&rdquo;</p>}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <Status status={lv.status} />
                {lv.actioned_at && <span className="text-xs text-muted-foreground">{tanggal(lv.actioned_at)}</span>}
              </div>
            </li>
          ))}
          {!item.levels?.length && <li className="px-3 py-2 text-sm text-muted-foreground">Ajuan ini tidak memiliki tahapan.</li>}
        </ol>
      </div>

      {isManager && item.status === 'pending' && (
        <div className="space-y-2 border-t border-[var(--glass-border)] pt-4">
          <label htmlFor="approval-detail-note" className="block text-sm font-medium text-foreground">Catatan (opsional)</label>
          <Textarea id="approval-detail-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2}
            placeholder="Alasan atau pesan untuk pemohon" data-testid="approval-detail-note" />
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="destructive" onClick={() => handleAction('reject')} disabled={acting} data-testid="approval-detail-reject">
              <XCircle />Tolak
            </Button>
            <Button variant="success" onClick={() => handleAction('approve')} disabled={acting} data-testid="approval-detail-approve">
              {acting ? <RefreshCw className="animate-spin" /> : <CheckCircle />}Setujui
            </Button>
          </div>
        </div>
      )}
    </DetailPopup>
  );
}

// ── Main Module ───────────────────────────────────────────────────────────────
export default function MultiLevelApprovalModule({ user, onModuleChange }) {
  const [requests, setRequests]       = useState([]);
  const [totalRequests, setTotalRequests] = useState(0);
  const [page, setPage]               = useState(1);
  const [myPending, setMyPending]     = useState([]);
  const [summary, setSummary]         = useState(null);
  const [chains, setChains]           = useState([]);
  const [loading, setLoading]         = useState(true);
  const [tab, setTab]                 = useState('pending');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterType, setFilterType]   = useState('');
  const [selectedItem, setSelectedItem] = useState(null);
  const [actingId, setActingId]       = useState(null);
  const token   = localStorage.getItem('erp_token');
  const headers = { Authorization: `Bearer ${token}` };
  const isManager = ['superadmin','admin','owner','manager','hr'].includes((user?.role||'').toLowerCase());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [pendRes, allRes, sumRes, chainRes] = await Promise.all([
        axios.get(`${API}/api/approvals/pending`,  { headers, params: { limit: 200 } }),
        axios.get(`${API}/api/approvals/requests`, { headers, params: {
          status: filterStatus || undefined, type: filterType || undefined,
          limit: UKURAN_HALAMAN, skip: (page - 1) * UKURAN_HALAMAN } }),
        axios.get(`${API}/api/approvals/summary`,  { headers }),
        axios.get(`${API}/api/approvals/chains`,   { headers }),
      ]);
      setMyPending(pendRes.data?.data  || []);
      setRequests(allRes.data?.data    || []);
      setTotalRequests(allRes.data?.total ?? (allRes.data?.data || []).length);
      setSummary(sumRes.data?.data     || null);
      setChains(chainRes.data?.data    || []);
    } catch (e) {
      console.error(e);
      toast.error('Gagal memuat data persetujuan. Coba muat ulang.');
    }
    finally { setLoading(false); }
  }, [filterStatus, filterType, page]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [filterStatus, filterType]);

  // 2026-11-08: server kini menolak peran yang bukan penyetuju level aktif dan menolak penyetujuan ajuan
  // sendiri (403). Dulu galat tidak ditangkap: tombol macet tanpa pesan apa pun.
  const decide = async (id, note, action) => {
    try {
      await axios.post(`${API}/api/approvals/requests/${id}/${action}`, { note }, { headers });
      toast.success(action === 'approve' ? 'Disetujui.' : 'Ditolak.');
      load();
      return true;
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Keputusan gagal disimpan. Coba lagi.');
      return false;
    }
  };
  const handleApprove = (id, note) => decide(id, note, 'approve');
  const handleReject  = (id, note) => decide(id, note, 'reject');
  const putuskanCepat = async (item, action) => {
    setActingId(item.id);
    await decide(item.id, '', action);
    setActingId(null);
  };

  const seedChains = async () => {
    try {
      await axios.post(`${API}/api/approvals/seed-missing-chains`, {}, { headers });
      toast.success('Alur bawaan dipasang.');
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal memasang alur bawaan.');
    }
  };

  // Tab "Perlu tindakan" disaring di layar (data dari /pending); tab "Semua ajuan" disaring di server.
  const pendingTampil = myPending
    .filter((it) => !filterStatus || it.status === filterStatus)
    .filter((it) => !filterType || it.type === filterType);
  const displayItems = tab === 'pending' ? pendingTampil : requests;

  const ambilSemuaAjuan = async () => {
    const semua = [];
    for (let skip = 0; skip < 20000; skip += 200) {
      const r = await axios.get(`${API}/api/approvals/requests`, { headers, params: {
        status: filterStatus || undefined, type: filterType || undefined, limit: 200, skip } });
      const d = r.data?.data || [];
      semua.push(...d);
      if (d.length < 200 || semua.length >= (r.data?.total ?? 0)) break;
    }
    return semua;
  };

  const kolomUnduhAjuan = [
    { label: 'Nomor', nilai: (it) => it.ref_code || '' },
    { label: 'Perihal', nilai: (it) => it.subject || '' },
    { label: 'Jenis', nilai: (it) => labelJenis(it.type) },
    { label: 'Alur', nilai: (it) => it.chain_name || '' },
    { label: 'Pemohon', nilai: (it) => it.requester_name || '' },
    { label: 'Diajukan', nilai: (it) => tanggal(it.created_at) },
    { label: 'Tahap', nilai: (it) => tahap(it) },
    { label: 'Status', nilai: (it) => labelStatus(it.status) },
  ];

  const kolomAjuan = [
    { kunci: 'perihal', label: 'Ajuan', hp: 'judul', isi: (it) => (
      <div className="min-w-0 md:max-w-[24rem]">
        <p className="truncate font-medium text-foreground" title={it.subject || it.ref_code}>
          {it.subject || it.ref_code}
          {it.meta?.priority === 'urgent' && <StatusBadge className="ml-2 align-middle" status="urgent" label="Mendesak" tone="danger" />}
        </p>
        {it.ref_code && it.subject && <p className="truncate text-xs text-muted-foreground">{it.ref_code}</p>}
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (it) => <span className="text-sm">{labelJenis(it.type)}</span> },
    { kunci: 'pemohon', label: 'Pemohon', isi: (it) => <span className="text-sm">{it.requester_name || '—'}</span> },
    { kunci: 'tanggal', label: 'Diajukan', isi: (it) => <span className="text-sm md:whitespace-nowrap">{tanggal(it.created_at)}</span> },
    { kunci: 'tahap', label: 'Tahap', isi: (it) => <span className="text-sm">{tahap(it)}</span> },
    { kunci: 'status', label: 'Status', isi: (it) => <Status status={it.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (isManager && it.status === 'pending' ? (
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="destructive" disabled={actingId === it.id} onClick={() => putuskanCepat(it, 'reject')}
          data-testid={`approval-reject-${it.id}`}><XCircle />Tolak</Button>
        <Button size="sm" variant="success" disabled={actingId === it.id} onClick={() => putuskanCepat(it, 'approve')}
          data-testid={`approval-approve-${it.id}`}>
          {actingId === it.id ? <RefreshCw className="animate-spin" /> : <CheckCircle />}Setujui
        </Button>
      </div>) : (
      <Button size="sm" variant="outline" onClick={() => setSelectedItem(it)} data-testid={`approval-view-${it.id}`}>Rincian</Button>)) },
  ];

  const kolomAlur = [
    { kunci: 'nama', label: 'Alur', hp: 'judul', isi: (ch) => <span className="font-medium text-foreground">{ch.name}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (ch) => <span className="text-sm">{labelJenis(ch.type)}</span> },
    { kunci: 'tahapan', label: 'Tahapan', isi: (ch) => (
      <span className="text-sm">{(ch.levels || []).map((lv) => lv.label).join(' → ') || '—'}</span>) },
    { kunci: 'status', label: 'Status', isi: (ch) => (ch.is_active
      ? <StatusBadge status="active" label="Aktif" tone="success" />
      : <StatusBadge status="inactive" label="Nonaktif" tone="muted" />) },
  ];

  const unduh = tab === 'chains' ? (
    <TombolUnduh namaBerkas="alur-persetujuan" namaLembar="Alur" baris={chains} testId="approval-unduh"
      kolom={[
        { label: 'Alur', nilai: (ch) => ch.name },
        { label: 'Jenis', nilai: (ch) => labelJenis(ch.type) },
        { label: 'Tahapan', nilai: (ch) => (ch.levels || []).map((lv) => lv.label).join(' → ') },
        { label: 'Status', nilai: (ch) => (ch.is_active ? 'Aktif' : 'Nonaktif') },
      ]} />
  ) : tab === 'all' ? (
    <TombolUnduh namaBerkas="semua-ajuan-persetujuan" namaLembar="Ajuan" baris={requests} ambilSemua={ambilSemuaAjuan}
      kolom={kolomUnduhAjuan} testId="approval-unduh" />
  ) : (
    <TombolUnduh namaBerkas="ajuan-perlu-tindakan" namaLembar="Perlu tindakan" baris={pendingTampil}
      kolom={kolomUnduhAjuan} testId="approval-unduh" />
  );

  const totalPages = Math.max(1, Math.ceil(totalRequests / UKURAN_HALAMAN));

  const filterBar = (
    <>
      <SmartNativeSelect value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
        data-testid="approval-filter-status" className="w-40">
        <option value="">Semua status</option>
        <option value="pending">Menunggu</option>
        <option value="approved">Disetujui</option>
        <option value="rejected">Ditolak</option>
        <option value="cancelled">Dibatalkan</option>
      </SmartNativeSelect>
      <SmartNativeSelect value={filterType} onChange={(e) => setFilterType(e.target.value)}
        data-testid="approval-filter-type" className="w-44">
        <option value="">Semua jenis</option>
        {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </SmartNativeSelect>
    </>
  );
  const alat = (
    <>
      {unduh}
      <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
        data-testid="approval-refresh-btn">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </>
  );
  const ringkasan = summary && (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="approval-summary">
      <StatTile testId="approval-stat-my-pending" label="Menunggu keputusan saya" value={summary.my_pending_count ?? 0}
        accent={summary.my_pending_count ? 'warning' : 'default'}
        sub="Ajuan yang tahap aktifnya menunggu peran Anda." />
      <StatTile testId="approval-stat-total-pending" label="Semua yang menunggu" value={summary.total_pending ?? 0}
        sub="Semua ajuan berstatus menunggu, semua jenis." />
      <StatTile testId="approval-stat-approved-today" label="Disetujui hari ini" value={summary.approved_today ?? 0}
        sub="Ajuan yang selesai disetujui sejak pukul 00.00 WIB." />
      <StatTile testId="approval-stat-active-chains" label="Alur aktif" value={chains.length}
        sub="Alur persetujuan yang sedang dipakai." />
    </div>
  );
  const memuatAwal = loading && !summary;
  const tabelAjuan = memuatAwal ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat ajuan…</p> : (
    <TabelData kolom={kolomAjuan} baris={displayItems} onKlikBaris={setSelectedItem} testId="approval-list"
      kosong={<EmptyState testId="approval-empty-state"
        title={tab === 'pending' ? 'Tidak ada ajuan yang menunggu keputusan Anda' : 'Tidak ada ajuan'}
        description={filterStatus || filterType ? 'Ubah saringan status atau jenis.' : 'Ajuan baru akan muncul di sini.'} />} />
  );

  return (
    <div data-testid="multi-level-approval-module">
      <HubTabs hubId="approval-multilevel" title="Persetujuan bertingkat"
        subtitle="Ajuan yang perlu disetujui berjenjang, dari atasan langsung sampai direktur."
        value={tab} onValueChange={setTab}
        tabs={[
          { key: 'pending', label: `Perlu tindakan${myPending.length ? ` (${myPending.length})` : ''}`, Component: IsiTab,
            props: { filters: filterBar, tools: alat, summary: ringkasan, children: tabelAjuan } },
          { key: 'all', label: 'Semua ajuan', Component: IsiTab,
            props: { filters: filterBar, tools: alat, summary: ringkasan, children: tabelAjuan,
              footer: totalRequests > UKURAN_HALAMAN ? (
                <PaginationLite page={page} totalPages={totalPages} total={totalRequests} pageSize={UKURAN_HALAMAN} onPageChange={setPage} />
              ) : null } },
          { key: 'chains', label: 'Alur persetujuan', Component: IsiTab,
            props: { tools: alat, summary: ringkasan, children: memuatAwal
              ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat alur…</p>
              : (
                <TabelData kolom={kolomAlur} baris={chains} testId="approval-chains-list"
                  kosong={<EmptyState title="Belum ada alur persetujuan"
                    description="Pasang alur bawaan (cuti, lembur, klaim biaya, PO, retur material, aset) lalu sesuaikan bila perlu."
                    action={<Button onClick={seedChains} data-testid="approval-seed-chains-btn">Pasang alur bawaan</Button>} />} />
              ) } },
        ]} />

      {selectedItem && (
        <DetailAjuan
          item={selectedItem} onClose={() => setSelectedItem(null)}
          onApprove={handleApprove} onReject={handleReject}
          isManager={isManager} onModuleChange={onModuleChange}
        />
      )}
    </div>
  );
}

/** Isi satu tab: cetakan PageLayout di dalam hub (judul hub di atas, alat ke baris penyaring/tab). */
function IsiTab({ filters, tools, summary, footer, children }) {
  return <PageLayout filters={filters} tools={tools} summary={summary} footer={footer}>{children}</PageLayout>;
}
