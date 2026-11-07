/**
 * HRApprovalInboxModule — Inbox SDM (kotak masuk persetujuan SDM terpadu)
 * Phase 26 — P2 Workflow Consolidation #2
 *
 * Satu tempat untuk semua permohonan SDM yang menunggu keputusan: cuti/izin, lembur, penyesuaian gaji,
 * pengunduran diri, absensi, koreksi absen, perubahan data.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar = tabel (kartu ringkas di HP) + unduh Excel/CSV,
 * detail = popup, setujui = form popup (Setujui hijau), tolak = konfirmasi dengan alasan (merah),
 * penyaring jenis = pil satu baris, kartu angka StatTile.
 * Perbaikan angka: kartu & pil dulu menghitung baris yang DIMUAT (paling banyak 50 per jenis) — kini dari
 * /api/hr/inbox/summary (hitungan penuh); daftar dimuat sampai 200 per jenis.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { CalendarCheck, CheckCircle2, ChevronRight, RefreshCw, Search, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { formatNumber, formatDateTimeID } from '@/lib/format';
import { withFileAuth } from '@/lib/fileUrl';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const BATAS_PER_JENIS = 200;

// ─── Helpers ──────────────────────────────────────────────────────────────
function fmtRp(v) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  const sign = n < 0 ? '-' : (n > 0 ? '+' : '');
  return `${sign}Rp ${formatNumber(Math.abs(n))}`;
}
const fmtDate = (v) => (v ? formatDateTimeID(v, { fallback: String(v) }) : '—');

const TYPE_META = {
  leave:                 { label: 'Cuti / izin',       tone: 'info' },
  overtime:              { label: 'Lembur',            tone: 'warning' },
  salary_adjustment:     { label: 'Penyesuaian gaji',  tone: 'primary' },
  resignation:           { label: 'Pengunduran diri',  tone: 'danger' },
  attendance:            { label: 'Persetujuan absen', tone: 'info' },
  // Tahap 2 (2026-11-06): pengajuan koreksi absen dari Portal Saya
  attendance_correction: { label: 'Koreksi absen',     tone: 'warning' },
  // HR1 (2026-11-07): perubahan No. HP / alamat / kontak darurat dari Portal Saya › Profil
  employee_data_change:  { label: 'Perubahan data',    tone: 'primary' },
};
const KIND_LABEL = { cuti: 'Cuti', izin: 'Izin', sakit: 'Sakit' };
const SUB_STATUS = { draft: 'Draf', pending_manager: 'Menunggu atasan', pending_hr: 'Menunggu SDM' };
const labelJenis = (t) => TYPE_META[t]?.label || 'Lainnya';

function TypeBadge({ type }) {
  const m = TYPE_META[type] || { label: 'Lainnya', tone: 'default' };
  return <StatusBadge status={type} label={m.label} tone={m.tone} />;
}

// ─── Detail (popup) ───────────────────────────────────────────────────────
function Lampiran({ url }) {
  return <a className="text-primary underline" href={withFileAuth(`${API}${url}`)} target="_blank" rel="noreferrer">Buka lampiran</a>;
}

function ItemDetail({ item, onClose, onApprove, onReject }) {
  const meta = item.meta || {};
  const raw = item.raw || {};
  return (
    <DetailPopup open onClose={onClose} testId="hr-inbox-detail"
      judul={item.title || '—'} status={<TypeBadge type={item.type} />}
      keterangan={`Dari ${item.requester_name || '—'}${item.requester_dept ? ` · ${item.requester_dept}` : ''}`}
      aksi={<>
        <Button size="sm" variant="destructive" data-testid="hr-inbox-reject-confirm" onClick={() => onReject(item)}>
          <XCircle />Tolak
        </Button>
        <Button size="sm" variant="success" data-testid="hr-inbox-approve-confirm" onClick={() => onApprove(item)}>
          <CheckCircle2 />Setujui
        </Button>
      </>}>
      <div>
        <p className="mb-1 text-sm font-medium text-foreground">Pemohon</p>
        <dl className="divide-y divide-[var(--glass-border)]">
          <BarisDetail label="Nama">{item.requester_name || '—'}</BarisDetail>
          <BarisDetail label="Kode">{item.requester_code || '—'}</BarisDetail>
          <BarisDetail label="Departemen">{item.requester_dept || '—'}</BarisDetail>
          <BarisDetail label="Diajukan">{fmtDate(item.submitted_at)}</BarisDetail>
        </dl>
      </div>

      <div>
        <p className="mb-1 text-sm font-medium text-foreground">Rincian permohonan</p>
        <dl className="divide-y divide-[var(--glass-border)]">
          {item.type === 'leave' && <>
            <BarisDetail label="Jenis cuti">{meta.leave_type || '—'}</BarisDetail>
            <BarisDetail label="Periode">{`${meta.from_date || '—'} → ${meta.to_date || '—'} (${meta.total_days ?? '—'} hari)`}</BarisDetail>
            <BarisDetail label="Dibayar">{meta.is_paid ? 'Ya' : 'Tidak'}</BarisDetail>
            {meta.half_day && <BarisDetail label="Setengah hari">{String(meta.half_day)}</BarisDetail>}
            {meta.approval_level && <BarisDetail label="Tingkat persetujuan">{meta.approval_level}</BarisDetail>}
            {meta.attachment_url && <BarisDetail label="Lampiran"><Lampiran url={meta.attachment_url} /></BarisDetail>}
            {meta.pay_decision_suggestion && (
              <BarisDetail label="Usulan bayar">
                {`${meta.pay_decision_suggestion.decision === 'paid' ? 'Dibayar' : 'Tidak dibayar'} — ${meta.pay_decision_suggestion.reason}`}
              </BarisDetail>
            )}
          </>}
          {item.type === 'overtime' && <>
            <BarisDetail label="Tanggal">{meta.date || '—'}</BarisDetail>
            <BarisDetail label="Jam">{`${meta.start_time || '—'} – ${meta.end_time || '—'}`}</BarisDetail>
            <BarisDetail label="Durasi">{`${meta.hours ?? '—'} jam`}</BarisDetail>
            <BarisDetail label="Pengali tarif">{meta.rate_multiplier != null ? `${meta.rate_multiplier}×` : '—'}</BarisDetail>
          </>}
          {item.type === 'salary_adjustment' && <>
            <BarisDetail label="Jenis">{meta.adjustment_type || '—'}</BarisDetail>
            <BarisDetail label="Nilai lama">{fmtRp(meta.old_value)}</BarisDetail>
            <BarisDetail label="Nilai baru">{fmtRp(meta.new_value)}</BarisDetail>
            <BarisDetail label="Selisih">
              <span className={meta.delta >= 0 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}>{fmtRp(meta.delta)}</span>
            </BarisDetail>
            <BarisDetail label="Berlaku mulai">{meta.effective_date || '—'}</BarisDetail>
            <BarisDetail label="Tahap">{SUB_STATUS[meta.sub_status] || meta.sub_status || '—'}</BarisDetail>
          </>}
          {item.type === 'resignation' && <>
            <BarisDetail label="Posisi">{meta.position || '—'}</BarisDetail>
            <BarisDetail label="Tanggal efektif">{meta.resignation_effective_date || '—'}</BarisDetail>
            <BarisDetail label="Hari kerja terakhir">{meta.last_working_date || '—'}</BarisDetail>
          </>}
          {item.type === 'attendance' && <>
            <BarisDetail label="Tanggal absen">{meta.date || '—'}</BarisDetail>
            <BarisDetail label="Jam masuk">{meta.check_in_time || '—'}</BarisDetail>
            <BarisDetail label="Jam pulang">{meta.check_out_time || '—'}</BarisDetail>
            {meta.work_hours != null && <BarisDetail label="Jam kerja">{`${meta.work_hours} jam`}</BarisDetail>}
            {meta.attendance_type && <BarisDetail label="Cara absen">{meta.attendance_type}</BarisDetail>}
            {meta.location && (
              <BarisDetail label="Lokasi">
                {typeof meta.location === 'string' ? meta.location
                  : [meta.location.lat, meta.location.lng].filter((v) => v != null).join(', ') || '—'}
              </BarisDetail>
            )}
            {meta.face_match != null && <BarisDetail label="Kecocokan wajah">{`${Math.round((Number(meta.face_match) || 0) * 100)}%`}</BarisDetail>}
            {meta.geo_distance_m != null && <BarisDetail label="Jarak ke kantor">{`${meta.geo_distance_m} m`}</BarisDetail>}
          </>}
          {item.type === 'attendance_correction' && <>
            <BarisDetail label="Tanggal">{meta.date || '—'}</BarisDetail>
            <BarisDetail label="Diminta">
              {[meta.requested?.clock_in && `masuk ${meta.requested.clock_in}`, meta.requested?.clock_out && `pulang ${meta.requested.clock_out}`,
                meta.requested?.status && `status ${meta.requested.status}`].filter(Boolean).join(', ') || '—'}
            </BarisDetail>
            {meta.locked && <BarisDetail label="Catatan">Tanggal ini sudah digaji — bila disetujui, selisihnya jadi penyesuaian di gaji berikutnya.</BarisDetail>}
            {meta.attachment_url && <BarisDetail label="Lampiran"><Lampiran url={meta.attachment_url} /></BarisDetail>}
          </>}
          {item.type !== 'employee_data_change' && <BarisDetail label="Alasan">{item.reason || raw.reason || '—'}</BarisDetail>}
        </dl>
        {item.type === 'employee_data_change' && <DataChanges changes={meta.changes} />}
      </div>

      {/* Tahap 2: foto selfie TAMPIL saat diperiksa (dulu hanya tautan, dan sering kosong) */}
      {item.type === 'attendance' && (meta.photo_url || meta.photo_out_url) && (
        <div className="grid max-w-md grid-cols-2 gap-2" data-testid="hr-inbox-selfie">
          {[['Selfie masuk', meta.photo_url], ['Selfie pulang', meta.photo_out_url]].filter(([, u]) => u).map(([lbl, u]) => (
            <a key={lbl} href={withFileAuth(`${API}${u}`)} target="_blank" rel="noreferrer" title={lbl}>
              <img src={withFileAuth(`${API}${u}`)} alt={lbl} className="aspect-[3/4] w-full rounded-[var(--radius-md)] border border-[var(--glass-border)] object-cover" />
              <span className="text-xs text-muted-foreground">{lbl}</span>
            </a>
          ))}
        </div>
      )}
    </DetailPopup>
  );
}

/** HR1: isian lama → baru (lama = data karyawan saat ini, yang akan diganti bila disetujui). */
function DataChanges({ changes = [] }) {
  return (
    <div className="space-y-1.5" data-testid="hr-inbox-data-changes">
      {changes.map((c) => (
        <div key={c.field} className="text-sm" data-testid={`hr-inbox-change-${c.field}`}>
          <div className="text-xs text-muted-foreground">{c.label}</div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground line-through">{c.old || '(kosong)'}</span>
            <ChevronRight className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
            <span className="font-medium text-foreground">{c.new || '(dikosongkan)'}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Setujui (form popup) ─────────────────────────────────────────────────
function ApproveDialog({ open, item, onClose, onConfirm }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  // Tahap 2: cuti/izin/sakit — HR memilih dibayar/tidak (bawaan = usulan sistem)
  const [pay, setPay] = useState('paid');
  useEffect(() => { if (!open) setNote(''); }, [open]);
  useEffect(() => { setPay(item?.meta?.pay_decision_suggestion?.decision || 'paid'); }, [item]);
  if (!item) return null;
  const isLeave = item.type === 'leave';
  const finalStep = isLeave && !(item.meta?.approval_level === '1/2');
  const submit = async () => {
    setBusy(true);
    try {
      await onConfirm(item, note.trim() || null, finalStep ? { pay_decision: pay } : {});
      onClose();
    } finally { setBusy(false); }
  };
  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" onSimpan={submit} menyimpan={busy}
      judul="Setujui permohonan" labelSimpan="Setujui" testId="hr-inbox-approve-form"
      keterangan={`${item.title} dari ${item.requester_name || '—'}`}>
      {item.type === 'employee_data_change' && <DataChanges changes={item.meta?.changes} />}
      {isLeave && (
        <Isian label="Pembayaran" petunjuk={finalStep
          ? `Usulan sistem: ${item.meta?.pay_decision_suggestion?.reason || '—'}`
          : 'Persetujuan tingkat 1 — diteruskan ke SDM.'}>
          <div className="space-y-2" data-testid="hr-inbox-pay-decision">
            <p className="text-sm text-muted-foreground">
              {KIND_LABEL[item.meta?.leave_kind] || 'Cuti'} · {item.reason || 'tanpa alasan'}
              {item.meta?.attachment_url && <> · <a className="text-primary underline" href={withFileAuth(`${API}${item.meta.attachment_url}`)} target="_blank" rel="noreferrer">Buka lampiran</a></>}
            </p>
            {finalStep && (
              <div className="flex gap-2">
                <Button type="button" size="sm" variant={pay === 'paid' ? 'default' : 'outline'} onClick={() => setPay('paid')}
                  aria-pressed={pay === 'paid'} data-testid="hr-inbox-pay-paid">Dibayar</Button>
                <Button type="button" size="sm" variant={pay === 'unpaid' ? 'default' : 'outline'} onClick={() => setPay('unpaid')}
                  aria-pressed={pay === 'unpaid'} data-testid="hr-inbox-pay-unpaid">Tidak dibayar</Button>
              </div>
            )}
          </div>
        </Isian>
      )}
      <Isian label="Catatan (opsional)" htmlFor="hr-inbox-approve-note">
        <Textarea id="hr-inbox-approve-note" data-testid="hr-inbox-approve-note" value={note}
          onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Tambahkan catatan untuk pemohon" />
      </Isian>
    </FormPopup>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────
export default function HRApprovalInboxModule({ token, onNavigate }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [viewItem, setViewItem] = useState(null);
  const [approveItem, setApproveItem] = useState(null);

  const fetchInbox = useCallback(async () => {
    setLoading(true);
    try {
      const [r, rs] = await Promise.all([
        fetch(`${API}/api/hr/inbox?limit_per_type=${BATAS_PER_JENIS}`, { headers }),
        fetch(`${API}/api/hr/inbox/summary`, { headers }),
      ]);
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        toast.error(e.detail || 'Gagal memuat inbox');
        return;
      }
      const data = await r.json();
      setItems(data.items || []);
      setCounts(data.counts || {});
      setSummary(rs.ok ? await rs.json().catch(() => null) : null);
    } catch (e) {
      toast.error('Gagal terhubung ke server: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchInbox(); }, [fetchInbox]);

  const filtered = useMemo(() => {
    let list = items;
    if (tab !== 'all') list = list.filter(i => i.type === tab);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(i =>
        (i.title || '').toLowerCase().includes(q) ||
        (i.requester_name || '').toLowerCase().includes(q) ||
        (i.requester_code || '').toLowerCase().includes(q) ||
        (i.requester_dept || '').toLowerCase().includes(q) ||
        (i.reason || '').toLowerCase().includes(q)
      );
    }
    return list;
  }, [items, tab, search]);

  const doApprove = async (item, note, extra = {}) => {
    try {
      const r = await fetch(`${API}/api/hr/inbox/${item.type}/${item.id}/approve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ note: note || undefined, ...extra }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || 'Gagal menyetujui');
      toast.success(`${labelJenis(item.type)} disetujui`);
      setViewItem(null);
      fetchInbox();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const doReject = async (item, reason) => {
    try {
      const r = await fetch(`${API}/api/hr/inbox/${item.type}/${item.id}/reject`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ reason }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || 'Gagal menolak');
      toast.success(`${labelJenis(item.type)} ditolak`);
      setViewItem(null);
      fetchInbox();
    } catch (e) {
      toast.error(e.message);
    }
  };

  // Tolak = konfirmasi merah dengan alasan wajib (dulu dialog sendiri).
  const mintaTolak = async (item) => {
    const alasan = await confirmDialog({
      title: 'Tolak permohonan ini?',
      body: `${item.title || 'Permohonan'} dari ${item.requester_name || '—'}. Alasan dikirim ke pemohon.`,
      input: { label: 'Alasan penolakan (wajib)', placeholder: 'Tulis alasan penolakan' },
      confirmLabel: 'Tolak', danger: true,
    });
    if (!alasan) return;
    await doReject(item, alasan);
  };

  // Hitungan penuh dari /summary; bila gagal dimuat, jatuh ke jumlah baris yang dimuat.
  const hitung = (k) => (summary ? Number(summary[k] || 0) : Number(counts[k] || 0));
  const total = summary ? Number(summary.total_pending || 0)
    : Object.values(counts).reduce((a, n) => a + (Number(n) || 0), 0);
  const terpotong = Object.keys(TYPE_META).filter((k) => hitung(k) > Number(counts[k] || 0));

  const opsi = [
    { key: 'all', label: 'Semua jenis', count: total },
    ...Object.entries(TYPE_META).map(([k, m]) => ({ key: k, label: m.label, count: hitung(k) })),
  ];

  const kolom = [
    { kunci: 'judul', label: 'Permohonan', hp: 'judul', isi: (i) => (
      <div className="min-w-0 md:max-w-[22rem]" data-testid={`hr-inbox-item-${i.id}`}>
        <p className="truncate font-medium text-foreground" title={i.title}>{i.title || '—'}</p>
        {i.reason && <p className="hidden truncate text-xs text-muted-foreground md:block" title={i.reason}>{i.reason}</p>}
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (i) => <TypeBadge type={i.type} /> },
    { kunci: 'pemohon', label: 'Pemohon', isi: (i) => (
      <div className="min-w-0">
        <p className="text-sm">{i.requester_name || '—'}</p>
        {i.requester_dept && <p className="text-xs text-muted-foreground">{i.requester_dept}</p>}
      </div>) },
    { kunci: 'periode', label: 'Periode', isi: (i) => <span className="text-sm">{i.period || '—'}</span> },
    { kunci: 'diajukan', label: 'Diajukan', isi: (i) => <span className="text-sm md:whitespace-nowrap">{fmtDate(i.submitted_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (i) => (
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="destructive" data-testid={`hr-inbox-reject-btn-${i.id}`} onClick={() => mintaTolak(i)}>
          <XCircle />Tolak
        </Button>
        <Button size="sm" variant="success" data-testid={`hr-inbox-approve-btn-${i.id}`} onClick={() => setApproveItem(i)}>
          <CheckCircle2 />Setujui
        </Button>
      </div>) },
  ];

  return (
    <PageLayout testId="hr-inbox-module" title="Inbox SDM"
      subtitle="Semua permohonan SDM yang menunggu keputusan: cuti, lembur, gaji, absensi, dan perubahan data."
      actions={onNavigate && (
        /* RC-IA T-4: jalan pintas ke hub absensi (kelola lengkap). Kedua modul dipertahankan by-design. */
        <Button variant="outline" onClick={() => onNavigate('hr-attendance-hub', { tab: 'approval' })}
          data-testid="hr-inbox-attendance-hub-link" title="Buka menu Absensi (absen manual, otomatis, dan persetujuan)">
          <CalendarCheck />Buka absensi
        </Button>
      )}
      filters={<>
        {/* 8 jenis sebagai pil memakan dua baris → satu pilihan ringkas berisi jumlah per jenis */}
        <SmartNativeSelect searchable={false} value={tab} onChange={(e) => setTab(e.target.value)} className="w-56"
          aria-label="Jenis permohonan" data-testid="hr-inbox-tab">
          {opsi.map((o) => <option key={o.key} value={o.key}>{`${o.label} (${o.count})`}</option>)}
        </SmartNativeSelect>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nama, departemen, alasan" value={search} onChange={(e) => setSearch(e.target.value)}
            className="pl-8" data-testid="hr-inbox-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="inbox-sdm" namaLembar="Permohonan" baris={filtered} testId="hr-inbox-unduh"
          kolom={[
            { label: 'Permohonan', nilai: (i) => i.title || '' },
            { label: 'Jenis', nilai: (i) => labelJenis(i.type) },
            { label: 'Pemohon', nilai: (i) => i.requester_name || '' },
            { label: 'Kode', nilai: (i) => i.requester_code || '' },
            { label: 'Departemen', nilai: (i) => i.requester_dept || '' },
            { label: 'Periode', nilai: (i) => i.period || '' },
            { label: 'Diajukan', nilai: (i) => fmtDate(i.submitted_at) },
            { label: 'Alasan', nilai: (i) => i.reason || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchInbox} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="hr-inbox-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Semua menunggu" value={formatNumber(total)} accent={total ? 'warning' : 'default'}
            sub="Semua permohonan SDM yang belum diputuskan." />
          <StatTile testId="kpi-leave" label="Cuti / izin" value={formatNumber(hitung('leave'))}
            sub="Menunggu atasan atau SDM." />
          <StatTile testId="kpi-overtime" label="Lembur" value={formatNumber(hitung('overtime'))}
            sub="Ajuan lembur yang menunggu." />
          <StatTile testId="kpi-attendance" label="Absensi & koreksi" value={formatNumber(hitung('attendance') + hitung('attendance_correction'))}
            sub="Absen di luar aturan dan koreksi absen." />
        </div>
      }>
      {/* RC-IA T-4: tautan kontekstual saat melihat persetujuan absen */}
      {tab === 'attendance' && onNavigate && (
        <Notice tone="info" icon={CalendarCheck} testId="hr-inbox-attendance-crosslink-note"
          action={<Button variant="outline" size="sm" onClick={() => onNavigate('hr-attendance-hub', { tab: 'approval' })}
            data-testid="hr-inbox-attendance-hub-link-inline">Buka absensi<ChevronRight /></Button>}>
          Persetujuan absen juga tersedia di menu Absensi — lengkap dengan absen manual dan otomatis.
        </Notice>
      )}
      {terpotong.length > 0 && (
        <Notice tone="warning" testId="hr-inbox-terpotong">
          Daftar menampilkan {BATAS_PER_JENIS} permohonan terbaru per jenis. Jumlah di kartu dan pil adalah hitungan penuh.
        </Notice>
      )}

      {loading && items.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat permohonan…</p>
      ) : (
        <TabelData kolom={kolom} baris={filtered} kunci={(i) => `${i.type}-${i.id}`} onKlikBaris={setViewItem}
          testId="hr-inbox-list"
          kosong={<EmptyState testId="hr-inbox-empty" title="Tidak ada permohonan yang menunggu"
            description={search ? 'Ubah kata pencarian.'
              : tab === 'all' ? 'Semua permohonan sudah diproses.' : `Tidak ada permohonan ${labelJenis(tab).toLowerCase()} yang menunggu.`} />} />
      )}

      {viewItem && (
        <ItemDetail
          item={viewItem}
          onClose={() => setViewItem(null)}
          onApprove={(it) => { setViewItem(null); setApproveItem(it); }}
          onReject={(it) => { setViewItem(null); mintaTolak(it); }}
        />
      )}

      <ApproveDialog
        item={approveItem}
        open={!!approveItem}
        onClose={() => setApproveItem(null)}
        onConfirm={doApprove}
      />
    </PageLayout>
  );
}
