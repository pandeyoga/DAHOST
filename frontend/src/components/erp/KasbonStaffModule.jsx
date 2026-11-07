/**
 * KasbonStaffModule — Portal Saya: Pengajuan Kasbon & Pinjaman
 * Staff bisa ajukan kasbon/pinjaman, lihat status, dan riwayat cicilan.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, status = pil penyaring berangka, daftar = tabel bisa diurutkan (desktop)
 * / kartu ringkas (HP) — dulu kartu besar per pengajuan + pengalih Tabel/Kartu, rincian & riwayat pembayaran di
 * popup, form pengajuan = FormPopup, unduh Excel + CSV (dulu CSV saja), saldo aktif = StatTile. Logika tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { toast } from 'sonner';
import { ArrowUpDown, Eye, Paperclip, Plus, RefreshCw, Upload, X } from 'lucide-react';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { GlassCard } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
// FASE G (sesi #18) — kolom nomor dokumen yang MENGIKUTI kebijakan Otomatis/Manual
// yang disetel System Admin. Tanpa ini layar & backend bisa berbeda pendapat.
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';

const API = process.env.REACT_APP_BACKEND_URL;
const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('erp_token')}`, 'Content-Type': 'application/json' });

const fmt = formatRupiah;
const fmtDate = (d) => { if (!d) return '-'; try { return new Date(d).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Jakarta' }); } catch { return d; } };

const STATUS_CFG = {
  submitted:   { label: 'Menunggu HR', tone: 'warning' },
  hr_approved: { label: 'Disetujui HR', tone: 'info' },
  hr_rejected: { label: 'Ditolak HR', tone: 'danger' },
  disbursed:   { label: 'Aktif', tone: 'success' },
  paid_off:    { label: 'Lunas', tone: 'success' },
  cancelled:   { label: 'Dibatalkan', tone: 'muted' },
};
const statusLabel = (s) => (STATUS_CFG[s] || STATUS_CFG.submitted).label;
function StatusKasbon({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.submitted;
  return <StatusBadge status={status} label={cfg.label} tone={cfg.tone} />;
}

// Tahap 7: tarik pengajuan yang masih menunggu review HR (409 bila HR baru saja memutusnya).
async function cancelKasbon(req, onDone) {
  if (!(await confirmDialog({ title: `Batalkan pengajuan ${req.request_number || ''}?`.trim(),
    confirmLabel: 'Batalkan pengajuan', cancelLabel: 'Kembali', danger: true }))) return;
  try {
    const r = await fetch(`${API}/api/dewi/kasbon/requests/${req.id}/cancel`, {
      method: 'POST', headers: authH(), body: JSON.stringify({ reason: 'Dibatalkan oleh karyawan' }),
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok) toast.success('Pengajuan dibatalkan');
    else toast.error(d.detail || 'Gagal membatalkan');
  } catch (_e) { toast.error('Gagal membatalkan'); }
  onDone?.();
}

// ─── Rincian pengajuan (popup) ────────────────────────────────────────────────
function RincianKasbon({ req, onClose, onRefresh }) {
  const pct = req.amount > 0 ? Math.min(100, Math.round(((req.paid_amount || 0) / req.amount) * 100)) : 0;
  return (
    <DetailPopup open onClose={onClose} testId="kasbon-detail"
      judul={`${req.type_label || req.type} ${req.request_number || ''}`.trim()} keterangan={req.purpose}
      status={<StatusKasbon status={req.status} />}
      aksi={req.status === 'submitted' && (
        <Button size="sm" variant="destructive" onClick={() => cancelKasbon(req, () => { onClose(); onRefresh(); })}
          data-testid={`kasbon-cancel-${req.id}`}>Batalkan pengajuan</Button>
      )}>
      {req.status === 'hr_rejected' && req.hr_notes && (
        <Notice tone="danger" title="Alasan penolakan">{req.hr_notes}</Notice>
      )}
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Jumlah">{fmt(req.amount)}</BarisDetail>
        <BarisDetail label="Terbayar">{fmt(req.paid_amount || 0)}{req.status === 'disbursed' ? ` (${pct}%)` : ''}</BarisDetail>
        <BarisDetail label="Sisa">{fmt(req.outstanding_balance || 0)}</BarisDetail>
        <BarisDetail label="Cicilan">{req.installment_count || 1}× {req.installment_amount ? fmt(req.installment_amount) : ''}</BarisDetail>
        {req.disbursement_date && <BarisDetail label="Tanggal cair">{fmtDate(req.disbursement_date)}</BarisDetail>}
        {req.deduction_start_period && <BarisDetail label="Mulai potong gaji">{req.deduction_start_period}</BarisDetail>}
        <BarisDetail label="Diajukan">{fmtDate(req.created_at)}</BarisDetail>
        {req.notes && <BarisDetail label="Keterangan">{req.notes}</BarisDetail>}
      </dl>
      <div className="space-y-2">
        <p className="text-sm font-medium">Riwayat pembayaran</p>
        <TabelData baris={req.repayments || []} testId="kasbon-repayments"
          kosong={<p className="text-sm text-muted-foreground">Belum ada pembayaran.</p>}
          kolom={[
            { kunci: 'date', label: 'Tanggal', hp: 'judul', isi: (r) => fmtDate(r.date) },
            { kunci: 'amount', label: 'Jumlah', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.amount)}</span> },
            { kunci: 'method', label: 'Cara', isi: (r) => (r.method === 'payroll_deduction' ? 'Potong gaji' : 'Manual') },
            { kunci: 'period', label: 'Periode', isi: (r) => r.period || '—' },
          ]} />
      </div>
    </DetailPopup>
  );
}

// ─── Request Form ─────────────────────────────────────────────────────────────
function RequestForm({ onSuccess, onClose }) {
  const [form, setForm] = useState({
    type: 'kasbon', amount: '', purpose: '', notes: '', installment_count: 1,
    request_number: '',
  });
  // FASE G — kasbon & pinjaman adalah DUA jenis dokumen dengan kebijakan sendiri.
  const numPolicy = useDocNumberPolicy(
    form.type === 'kasbon'
      ? 'dewi_kasbon_requests.request_number'
      : 'dewi_kasbon_requests.request_number_pinjaman',
    localStorage.getItem('erp_token'),
  );
  const [docs, setDocs] = useState([]);
  const [saving, setSaving] = useState(false);

  const installmentAmt = form.amount && form.installment_count
    ? Math.ceil(Number(form.amount) / Number(form.installment_count))
    : 0;

  const handleFileAdd = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast.error('Ukuran file maks 5MB'); return; }
    const reader = new FileReader();
    reader.onload = (ev) => {
      setDocs(p => [...p, { name: file.name, data: ev.target.result, mime_type: file.type }]);
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  const handleSubmit = async () => {
    if (!form.purpose.trim()) { toast.error('Keperluan harus diisi'); return; }
    if (!form.amount || Number(form.amount) <= 0) { toast.error('Jumlah harus lebih dari 0'); return; }
    // FASE G — mode MANUAL: nomor wajib diisi di layar, jangan biarkan backend
    // yang menolak setelah semua kolom lain diisi.
    if (numPolicy?.mode === 'manual' && !(form.request_number || '').trim()) {
      toast.error(`Nomor ${numPolicy.label} wajib diisi (pola ${numPolicy.format})`);
      return;
    }
    setSaving(true);
    try {
      const { request_number: _rn, ...rest } = form;
      const r = await fetch(`${API}/api/dewi/kasbon/requests`, {
        method: 'POST',
        headers: authH(),
        body: JSON.stringify({
          ...rest,
          amount: Number(form.amount),
          installment_count: Number(form.installment_count),
          documents: docs,
          // nomor HANYA dikirim bila kebijakannya manual (mode otomatis MENOLAK ketikan)
          ...docNumberPayload(numPolicy, 'request_number', form.request_number),
        }),
      });
      const d = await r.json();
      if (d.ok) { toast.success('Pengajuan berhasil dikirim'); onSuccess(); }
      else toast.error(d.detail || 'Gagal mengajukan');
    } catch (_e) { toast.error('Terjadi kesalahan'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="kasbon-form" judul="Ajukan kasbon / pinjaman"
      keterangan="Pengajuan diperiksa HR. Cicilan dipotong dari gaji setelah dana cair."
      onSimpan={handleSubmit} menyimpan={saving} bisaSimpan={!!form.purpose.trim() && !!form.amount}
      labelSimpan="Kirim pengajuan">
      <Isian label="Jenis">
        <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Jenis pengajuan">
          {[['kasbon', 'Kasbon', 'Gaji dimuka, lunas 1× potong gaji'], ['pinjaman', 'Pinjaman', 'Cicilan bulanan, otomatis potong gaji']].map(([k, l, d]) => (
            <label key={k} className={`cursor-pointer rounded-lg border p-3 text-sm ${form.type === k ? 'border-primary bg-primary/5' : 'border-[var(--glass-border)]'}`}>
              <span className="flex items-center gap-2 font-medium">
                <input type="radio" name="kasbon-type" checked={form.type === k} className="accent-[hsl(var(--primary))]"
                  onChange={() => setForm(p => ({ ...p, type: k, installment_count: k === 'kasbon' ? 1 : p.installment_count }))} />
                {l}
              </span>
              <span className="mt-0.5 block text-xs text-muted-foreground">{d}</span>
            </label>
          ))}
        </div>
      </Isian>

      {/* FASE G (sesi #18) — nomor pengajuan mengikuti kebijakan Otomatis/Manual
          yang disetel System Admin. Kasbon & Pinjaman punya kebijakan sendiri. */}
      <DocNumberField
        policy={numPolicy}
        value={form.request_number}
        onChange={(v) => setForm(p => ({ ...p, request_number: v }))}
        testId="kasbon-docnum"
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Jumlah yang diminta" wajib>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">Rp</span>
            <MoneyInput unstyled value={form.amount} onChange={e => setForm(p => ({ ...p, amount: e.target.value }))}
              placeholder="1.000.000"
              className="h-9 w-full rounded-md border border-[var(--glass-border)] bg-[var(--input-surface)] pl-10 pr-3 text-sm" />
          </div>
        </Isian>
        {form.type === 'pinjaman' && (
          <Isian label="Jumlah cicilan (bulan)" wajib
            petunjuk={installmentAmt > 0 ? `Cicilan per bulan ${fmt(installmentAmt)} (dipotong dari gaji).` : undefined}>
            <SmartNativeSelect value={String(form.installment_count)} searchable={false} className="w-full"
              onChange={e => setForm(p => ({ ...p, installment_count: Number(e.target.value) }))}>
              {[1, 2, 3, 4, 5, 6, 8, 10, 12].map(n => <option key={n} value={String(n)}>{n} bulan</option>)}
            </SmartNativeSelect>
          </Isian>
        )}
      </div>

      <Isian label="Keperluan / tujuan" wajib htmlFor="kasbon-purpose">
        <Input id="kasbon-purpose" value={form.purpose} onChange={e => setForm(p => ({ ...p, purpose: e.target.value }))}
          placeholder="Contoh: biaya pengobatan, renovasi rumah, pendidikan…" />
      </Isian>

      <Isian label="Keterangan tambahan" htmlFor="kasbon-notes">
        <Textarea id="kasbon-notes" rows={2} value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
          placeholder="Tambahkan informasi lain bila perlu…" className="resize-none" />
      </Isian>

      <Isian label="Dokumen pendukung" petunjuk="PDF/JPG/PNG, maksimal 5 MB per berkas.">
        <Button type="button" variant="outline" asChild>
          <label className="cursor-pointer">
            <Upload />Unggah dokumen
            <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={handleFileAdd} className="hidden" />
          </label>
        </Button>
        {docs.length > 0 && (
          <ul className="mt-2 divide-y divide-[var(--glass-border)] rounded-md border border-[var(--glass-border)]">
            {docs.map((d, i) => (
              <li key={i} className="flex items-center gap-2 px-2 py-1.5 text-sm">
                <Paperclip className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{d.name}</span>
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => setDocs(p => p.filter((_, j) => j !== i))}
                  title="Hapus berkas" aria-label="Hapus berkas"><X /></Button>
              </li>
            ))}
          </ul>
        )}
      </Isian>
    </FormPopup>
  );
}

// ─── Main Module ──────────────────────────────────────────────────────────────
const KOLOM_URUT = [
  ['request_number', 'No. pengajuan'], ['type_label', 'Jenis'], ['purpose', 'Keperluan'], ['status', 'Status'],
  ['amount', 'Jumlah'], ['outstanding_balance', 'Sisa'], ['created_at', 'Diajukan'],
];

export default function KasbonStaffModule() {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [tab, setTab] = useState('all');
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/dewi/kasbon/my-requests`, { headers: authH() });
      const d = await r.json();
      if (d.ok) setRequests(d.requests || []);
    } catch (_e) { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const kelompok = (r) => (r.status === 'disbursed' ? 'active'
    : ['submitted', 'hr_approved'].includes(r.status) ? 'pending'
      : ['paid_off', 'hr_rejected', 'cancelled'].includes(r.status) ? 'done' : 'other');
  const filtered = tab === 'all' ? requests : requests.filter(r => kelompok(r) === tab);
  const hitung = (k) => requests.filter(r => kelompok(r) === k).length;

  const activeAmt = requests.filter(r => r.status === 'disbursed').reduce((s, r) => s + (r.outstanding_balance || 0), 0);

  // ── F13-B (sesi #12) — riwayat kasbon SAYA harus bisa dibawa (tabel bisa diurutkan + unduh).
  const [sort, setSort] = useState({ key: 'created_at', dir: 'desc' });
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
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 10);
  const toggleSort = (key) => setSort((s) => (
    s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' }));

  const isi = {
    request_number: (r) => <span className="whitespace-nowrap font-mono text-xs">{r.request_number}</span>,
    type_label: (r) => r.type_label || r.type,
    purpose: (r) => <span className="block max-w-[16rem] truncate" title={r.purpose}>{r.purpose}</span>,
    status: (r) => <StatusKasbon status={r.status} />,
    amount: (r) => <span className="whitespace-nowrap font-medium tabular-nums">{fmt(r.amount)}</span>,
    outstanding_balance: (r) => <span className="whitespace-nowrap tabular-nums">{fmt(r.outstanding_balance || 0)}</span>,
    created_at: (r) => <span className="whitespace-nowrap">{fmtDate(r.created_at)}</span>,
  };
  const aksiBaris = (r) => (
    <div className="flex justify-end gap-1">
      <Button size="sm" variant="outline" onClick={() => setDetail(r)}><Eye />Rincian</Button>
      {r.status === 'submitted' && (
        <Button size="sm" variant="outline" onClick={() => cancelKasbon(r, load)} data-testid={`kasbon-cancel-row-${r.id}`}>Batalkan</Button>
      )}
    </div>
  );

  return (
    <PageLayout testId="kasbon-staff" title="Kasbon"
      subtitle="Ajukan kasbon atau pinjaman dan pantau status serta cicilannya."
      actions={<Button onClick={() => setShowForm(true)} data-testid="kasbon-new-btn"><Plus />Ajukan kasbon/pinjaman</Button>}
      filters={(
        <FilterChips className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" value={tab} onChange={(k) => { setTab(k || 'all'); setPage(1); }} hideWhenEmpty={false} testId="kasbon-filter"
          options={[
            { key: 'all', label: 'Semua', count: requests.length },
            { key: 'pending', label: 'Menunggu', count: hitung('pending') },
            { key: 'active', label: 'Aktif', count: hitung('active') },
            { key: 'done', label: 'Selesai', count: hitung('done') },
          ]} />
      )}
      tools={<>
        <TombolUnduh namaBerkas="kasbon-saya" namaLembar="Kasbon" baris={rows} testId="kasbonstaff-export" kolom={[
          { label: 'No. pengajuan', nilai: (r) => r.request_number }, { label: 'Jenis', nilai: (r) => r.type_label || r.type },
          { label: 'Keperluan', nilai: (r) => r.purpose || '' }, { label: 'Status', nilai: (r) => statusLabel(r.status) },
          { label: 'Jumlah', nilai: (r) => r.amount ?? 0 }, { label: 'Terbayar', nilai: (r) => r.paid_amount ?? 0 },
          { label: 'Sisa', nilai: (r) => r.outstanding_balance ?? 0 }, { label: 'Cicilan/bulan', nilai: (r) => r.installment_amount ?? 0 },
          { label: 'Jml cicilan', nilai: (r) => r.installment_count ?? 0 }, { label: 'Mulai potong', nilai: (r) => r.deduction_start_period || '' },
          { label: 'Diajukan', nilai: (r) => fmtDate(r.created_at) },
        ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={activeAmt > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Sisa kasbon/pinjaman aktif" value={fmt(activeAmt)} sub="Dipotong dari gaji berikutnya" testId="kasbon-sisa-aktif" />
        </div>
      )}
      footer={rows.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && requests.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat pengajuan…</p>
      ) : rows.length === 0 ? (
        <EmptyState title={requests.length ? 'Tidak ada pengajuan di status ini' : 'Belum ada pengajuan'}
          description={requests.length ? 'Pilih status lain.' : 'Ajukan kasbon atau pinjaman bila perlu.'}
          action={{ label: 'Buat pengajuan baru', onClick: () => setShowForm(true) }} />
      ) : (
        <>
          {/* Desktop: tabel bisa diurutkan */}
          <GlassCard className="hidden overflow-hidden p-0 md:block">
            <div className="overflow-x-auto">
              <Table data-testid="kasbonstaff-table">
                <TableHeader>
                  <TableRow>
                    {KOLOM_URUT.map(([k, label]) => (
                      <TableHead key={k} className={['amount', 'outstanding_balance'].includes(k) ? 'text-right' : ''}>
                        <Button variant="ghost" size="sm" onClick={() => toggleSort(k)} data-testid={`kasbonstaff-sort-${k}`}
                          className="-ml-2 h-7 px-2" title={`Urutkan menurut ${label.toLowerCase()}`}>
                          {label}<ArrowUpDown className={sort.key === k ? 'text-primary' : 'opacity-40'} />
                        </Button>
                      </TableHead>
                    ))}
                    <TableHead><span className="sr-only">Aksi</span></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {paged.map((r) => (
                    <TableRow key={r.id} className="cursor-pointer" onClick={() => setDetail(r)}>
                      {KOLOM_URUT.map(([k]) => (
                        <TableCell key={k} className={['amount', 'outstanding_balance'].includes(k) ? 'text-right' : ''}>{isi[k](r)}</TableCell>
                      ))}
                      <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>{aksiBaris(r)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </GlassCard>
          {/* HP: kartu ringkas */}
          <div className="md:hidden">
            <TabelData baris={paged} onKlikBaris={setDetail} testId="kasbon-cards" kolom={[
              { kunci: 'purpose', label: 'Keperluan', hp: 'judul', isi: (r) => r.purpose },
              { kunci: 'no', label: 'No.', hp: 'keterangan', isi: (r) => `${r.request_number} · ${r.type_label || r.type}` },
              { kunci: 'status', label: 'Status', isi: isi.status },
              { kunci: 'amount', label: 'Jumlah', isi: (r) => fmt(r.amount) },
              { kunci: 'sisa', label: 'Sisa', isi: (r) => fmt(r.outstanding_balance || 0) },
              { kunci: 'tgl', label: 'Diajukan', isi: (r) => fmtDate(r.created_at) },
              { kunci: 'aksi', label: '', hp: 'aksi', isi: aksiBaris },
            ]} />
          </div>
        </>
      )}

      {detail && <RincianKasbon req={detail} onClose={() => setDetail(null)} onRefresh={load} />}
      {showForm && <RequestForm onSuccess={() => { setShowForm(false); load(); }} onClose={() => setShowForm(false)} />}
    </PageLayout>
  );
}
