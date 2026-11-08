/**
 * Umpan balik 360° (Portal SDM › Manajemen Kinerja) — penilaian dari banyak sumber: diri, atasan, rekan, bawahan.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar siklus = tabel + unduh Excel/CSV (dulu kartu
 * berulang), saringan status = pil, form = FormPopup, hasil = DetailPopup, tutup siklus = confirmDialog (dulu
 * window.confirm), bahasa Indonesia, warna token.
 * Perbaikan pemilih: target dulu diam-diam hanya 50 karyawan pertama dan penilai 20 pengguna pertama — kini semua
 * (bisa dicari).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { BarChart3, CheckCircle2, Plus, RefreshCw, Star, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const HUBUNGAN = { self: 'Diri sendiri', manager: 'Atasan', peer: 'Rekan', subordinate: 'Bawahan' };
const STATUS = { open: { label: 'Terbuka', tone: 'warning' }, closed: { label: 'Ditutup', tone: 'success' } };

export default function HR360FeedbackModule({ token, user }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [cycles, setCycles] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [users, setUsers] = useState([]);
  const [tab, setTab] = useState('open');
  const [loading, setLoading] = useState(false);
  const [newDialog, setNewDialog] = useState(false);
  const [reviewDialog, setReviewDialog] = useState(null);
  const [detailDialog, setDetailDialog] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2, r3] = await Promise.all([
        axios.get(`${API}/api/rahaza/360-feedback/cycles?status=${tab === 'all' ? '' : tab}`, { headers }),
        axios.get(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers }),
        axios.get(`${API}/api/users`, { headers }).catch(() => ({ data: [] })),
      ]);
      setCycles(r1.data.cycles || []);
      setEmployees(Array.isArray(r2.data) ? r2.data : (r2.data.items || r2.data.rows || []));
      setUsers(Array.isArray(r3.data) ? r3.data : []);
    } finally { setLoading(false); }
  }, [headers, tab]);

  useEffect(() => { load(); }, [load]);

  const close = async (id) => {
    if (!(await confirmDialog({ title: 'Tutup siklus ini?', body: 'Nilai rata-rata dihitung dan siklus tidak bisa diisi lagi.', confirmLabel: 'Tutup siklus' }))) return;
    try {
      await axios.post(`${API}/api/rahaza/360-feedback/cycles/${id}/close`, {}, { headers });
      toast.success('Siklus ditutup');
      load();
    } catch { toast.error('Gagal menutup siklus'); }
  };

  const kemajuan = (c) => {
    const submitted = c.reviewers?.filter(r => r.status === 'submitted').length || 0;
    return { submitted, total: c.reviewers?.length || 0 };
  };

  const kolom = [
    { kunci: 'target', label: 'Karyawan dinilai', hp: 'judul', isi: (c) => (
      <div><p className="font-medium text-foreground">{c.target_employee_name}</p><p className="text-xs text-muted-foreground">{c.target_employee_code}</p></div>) },
    { kunci: 'periode', label: 'Periode', isi: (c) => <span className="text-sm">{c.period_name || '—'}</span> },
    { kunci: 'kemajuan', label: 'Penilai selesai', rata: 'kanan', isi: (c) => {
      const k = kemajuan(c);
      return <span className="tabular-nums">{k.submitted}/{k.total}</span>;
    } },
    { kunci: 'status', label: 'Status', isi: (c) => {
      const s = STATUS[c.status] || { label: c.status || '—', tone: 'default' };
      return <StatusBadge status={c.status} label={s.label} tone={s.tone} />;
    } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => {
      const myReviewer = c.reviewers?.find(r => r.reviewer_id === user?.id);
      const k = kemajuan(c);
      return (
        <div className="flex justify-end gap-2">
          {myReviewer && myReviewer.status === 'pending' && c.status === 'open' && (
            <Button size="sm" onClick={() => setReviewDialog(c)} data-testid={`360-review-${c.cycle_id}`}><Star />Isi penilaian</Button>
          )}
          {c.status === 'closed' && (
            <Button size="sm" variant="outline" onClick={() => setDetailDialog(c)}><BarChart3 />Lihat hasil</Button>
          )}
          {c.status === 'open' && k.submitted === k.total && k.total > 0 && (
            <Button size="sm" variant="outline" onClick={() => close(c.cycle_id)}><CheckCircle2 />Tutup</Button>
          )}
        </div>
      );
    } },
  ];

  return (
    <PageLayout testId="360-feedback-page" title="Umpan balik 360°"
      subtitle="Penilaian dari banyak sumber: diri sendiri, atasan, rekan, dan bawahan."
      actions={<Button onClick={() => setNewDialog(true)} data-testid="360-new-cycle"><Plus />Buat siklus</Button>}
      filters={
        <FilterChips value={tab} onChange={setTab} testId="360-filter" ariaLabel="Status siklus"
          options={[{ key: 'open', label: 'Terbuka' }, { key: 'closed', label: 'Ditutup' }, { key: 'all', label: 'Semua' }]} />
      }
      tools={<>
        <TombolUnduh namaBerkas="umpan-balik-360" namaLembar="Siklus 360" baris={cycles} testId="360-unduh"
          kolom={[
            { label: 'Karyawan dinilai', nilai: (c) => c.target_employee_name || '' }, { label: 'Kode', nilai: (c) => c.target_employee_code || '' },
            { label: 'Periode', nilai: (c) => c.period_name || '' }, { label: 'Penilai selesai', nilai: (c) => kemajuan(c).submitted },
            { label: 'Jumlah penilai', nilai: (c) => kemajuan(c).total }, { label: 'Status', nilai: (c) => STATUS[c.status]?.label || c.status || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && cycles.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat siklus…</p> : (
        <TabelData kolom={kolom} baris={cycles} kunci={(c) => c.cycle_id} testId="360-cycles"
          kosong={<EmptyState title="Belum ada siklus umpan balik 360°" description='Klik "Buat siklus" untuk memulai.' />} />
      )}

      {newDialog && (
        <NewCycleDialog employees={employees} users={users} headers={headers}
          onClose={() => setNewDialog(false)}
          onCreated={() => { setNewDialog(false); load(); }} />
      )}
      {reviewDialog && (
        <ReviewDialog cycle={reviewDialog} headers={headers}
          onSubmit={() => { setReviewDialog(null); load(); }}
          onClose={() => setReviewDialog(null)} />
      )}
      {detailDialog && (
        <DetailDialog cycle={detailDialog} onClose={() => setDetailDialog(null)} />
      )}
    </PageLayout>
  );
}

function NewCycleDialog({ employees, users, headers, onClose, onCreated }) {
  const [targetId, setTargetId] = useState('');
  const [periodName, setPeriodName] = useState('');
  const [reviewers, setReviewers] = useState([]);
  const [saving, setSaving] = useState(false);
  const [calonUser, setCalonUser] = useState('');
  const [calonHubungan, setCalonHubungan] = useState('peer');

  const addReviewer = (userId, relationship) => {
    const u = users.find(x => x.id === userId);
    if (!u || reviewers.some(r => r.reviewer_id === userId)) return;
    setReviewers([...reviewers, { reviewer_id: userId, reviewer_name: u.name, relationship }]);
  };

  const submit = async () => {
    if (!targetId) { toast.error('Pilih karyawan yang dinilai'); return; }
    if (reviewers.length === 0) { toast.error('Tambahkan minimal 1 penilai'); return; }
    setSaving(true);
    try {
      await axios.post(`${API}/api/rahaza/360-feedback/cycles`,
        { target_employee_id: targetId, period_name: periodName, reviewers }, { headers });
      toast.success('Siklus dibuat');
      onCreated();
    } catch { toast.error('Gagal membuat siklus'); }
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" onSimpan={submit} menyimpan={saving} judul="Buat siklus umpan balik 360°"
      labelSimpan="Buat siklus" testId="360-new-form">
      <Isian label="Karyawan dinilai" wajib>
        <SmartNativeSelect value={targetId} onChange={(e) => setTargetId(e.target.value)} searchable>
          <option value="">Pilih karyawan</option>
          {employees.map(e => <option key={e.id} value={e.id}>{`${e.employee_code} — ${e.name}`}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Nama periode" htmlFor="360-periode">
        <Input id="360-periode" value={periodName} onChange={e => setPeriodName(e.target.value)} placeholder="Penilaian triwulan 1 2026" />
      </Isian>
      <Isian label="Penilai" wajib petunjuk="Pilih pengguna dan hubungannya dengan karyawan yang dinilai, lalu klik Tambah.">
        <div className="flex flex-wrap gap-2">
          <SmartNativeSelect value={calonUser} onChange={(e) => setCalonUser(e.target.value)} className="min-w-0 flex-1" searchable aria-label="Pengguna penilai">
            <option value="">Pilih pengguna</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect value={calonHubungan} onChange={(e) => setCalonHubungan(e.target.value)} className="w-36" searchable={false} aria-label="Hubungan">
            {Object.entries(HUBUNGAN).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
          <Button type="button" variant="outline" disabled={!calonUser}
            onClick={() => { addReviewer(calonUser, calonHubungan); setCalonUser(''); }}><Plus />Tambah</Button>
        </div>
        {reviewers.length > 0 && (
          <ul className="mt-2 divide-y divide-[var(--glass-border)] rounded-lg border border-[var(--glass-border)]">
            {reviewers.map((r, i) => (
              <li key={i} className="flex items-center justify-between px-3 py-1.5 text-sm">
                <span>{r.reviewer_name} <span className="text-muted-foreground">({HUBUNGAN[r.relationship] || r.relationship})</span></span>
                <Button type="button" size="icon-sm" variant="ghost" aria-label="Hapus penilai" title="Hapus penilai"
                  onClick={() => setReviewers(reviewers.filter((_, idx) => idx !== i))}><X /></Button>
              </li>
            ))}
          </ul>
        )}
      </Isian>
    </FormPopup>
  );
}

function ReviewDialog({ cycle, headers, onSubmit, onClose }) {
  const [responses, setResponses] = useState({});
  const [saving, setSaving] = useState(false);

  const set = (qid, val) => setResponses(r => ({ ...r, [qid]: val }));

  const submit = async () => {
    const arr = (cycle.questions || []).map(q => ({
      question_id: q.id,
      score: q.type === 'text' ? null : (responses[q.id + '_score'] ?? 0),
      comment: responses[q.id + '_comment'] || responses[q.id] || '',
    }));
    setSaving(true);
    try {
      await axios.post(`${API}/api/rahaza/360-feedback/cycles/${cycle.cycle_id}/submit`,
        { responses: arr }, { headers });
      toast.success('Umpan balik tersimpan'); onSubmit();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal mengirim'); }
    setSaving(false);
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={submit} menyimpan={saving}
      judul={`Penilaian: ${cycle.target_employee_name}`} keterangan="Nilai 1 = kurang, 5 = sangat baik." labelSimpan="Kirim penilaian"
      testId="360-review-form">
      {(cycle.questions || []).map(q => (
        <Isian key={q.id} label={q.text}>
          {q.type === 'text' ? (
            <Textarea rows={2} onChange={e => set(q.id, e.target.value)} placeholder="Jawaban Anda" />
          ) : (
            <div className="flex items-center gap-2" role="radiogroup" aria-label={q.text}>
              {[1, 2, 3, 4, 5].map(n => (
                <Button key={n} type="button" size="icon-sm" variant={responses[q.id + '_score'] === n ? 'default' : 'outline'}
                  className="rounded-full" aria-pressed={responses[q.id + '_score'] === n} aria-label={`Nilai ${n}`}
                  onClick={() => set(q.id + '_score', n)}>{n}</Button>
              ))}
            </div>
          )}
        </Isian>
      ))}
      {(cycle.questions || []).length === 0 && <p className="text-sm text-muted-foreground">Siklus ini belum punya pertanyaan.</p>}
    </FormPopup>
  );
}

function DetailDialog({ cycle, onClose }) {
  const agg = cycle.aggregate || {};
  const baris = Object.entries(agg).map(([qid, data]) => ({ qid, ...data }));
  return (
    <DetailPopup open onClose={onClose} judul={`Hasil 360°: ${cycle.target_employee_name}`} keterangan={cycle.period_name}
      testId="360-result"
      aksi={<TombolUnduh namaBerkas={`hasil-360-${cycle.target_employee_name}`} namaLembar="Hasil 360" baris={baris}
        kolom={[
          { label: 'Pertanyaan', nilai: (d) => d.question }, { label: 'Rata-rata (1–5)', nilai: (d) => d.avg_score },
          { label: 'Jumlah jawaban', nilai: (d) => d.total_responses },
          { label: 'Per hubungan', nilai: (d) => Object.entries(d.by_relation || {}).map(([k, v]) => `${HUBUNGAN[k] || k}: ${v}`).join('; ') },
        ]} />}>
      <TabelData baris={baris} kunci={(d) => d.qid} testId="360-result-table"
        kolom={[
          { kunci: 'q', label: 'Pertanyaan', hp: 'judul', isi: (d) => <span className="text-sm">{d.question}</span> },
          { kunci: 'avg', label: 'Rata-rata', isi: (d) => (
            <div className="flex items-center gap-2">
              <div className="h-2 w-24 overflow-hidden rounded-full bg-[var(--glass-border)]">
                <div className="h-full bg-primary" style={{ width: `${(d.avg_score / 5) * 100}%` }} />
              </div>
              <span className="text-sm font-semibold tabular-nums">{d.avg_score}/5</span>
            </div>) },
          { kunci: 'n', label: 'Jawaban', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.total_responses}</span> },
          { kunci: 'rel', label: 'Per hubungan', hp: 'keterangan', isi: (d) => (
            <span className="text-sm text-muted-foreground">{Object.entries(d.by_relation || {}).map(([k, v]) => `${HUBUNGAN[k] || k}: ${v}`).join(' · ') || '—'}</span>) },
        ]}
        kosong={<p className="py-6 text-center text-sm text-muted-foreground">Nilai rata-rata belum tersedia.</p>} />
    </DetailPopup>
  );
}
