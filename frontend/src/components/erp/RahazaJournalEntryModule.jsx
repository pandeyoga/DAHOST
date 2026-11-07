import { Fragment, useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Plus, RefreshCw, Trash2, FileText, Check, Ban, Search } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState, StatusBadge as AtomStatusBadge } from './moduleAtoms';
import PageLayout, { RowDetail, RowToggle } from './layout/PageLayout';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import JournalLinesInline from './finance/JournalLinesInline';
import PaginationBar from '@/components/ui/PaginationBar';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { JOURNAL_SOURCE_LABELS, journalSourceLabel, finStatus, humanMemo } from '../../lib/financeLabels';
import { formatDateID, formatNumber } from '@/lib/format';
import { formatRupiah } from '@/lib/format';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';
import { cvAccountParam, useCv } from '@/lib/entitas';

const fmt = formatRupiah;

// PANDUAN_UI G8: label & nada status dari financeLabels (dulu palet langsung amber/emerald/red).
function StatusBadge({ status }) {
  const s = finStatus(status);
  return <AtomStatusBadge status={status} label={s.label} tone={status === 'draft' ? 'warning' : s.tone} />;
}

// Memo jurnal otomatis dari server ("AR Invoice …") ditampilkan dalam bahasa Indonesia lewat `humanMemo`
// (lib/financeLabels — satu sumber, 2026-11-05); data & unduhan CSV tetap memakai teks aslinya.
// 2026-11-08: memo pengeluaran "Expense: …" belum dikenali humanMemo (butuh spasi, bukan titik dua) → ditangani di sini.
const memoID = (m) => humanMemo(String(m || '').replace(/^Expense:\s*/, 'Pengeluaran: '));

function JournalEditor({ accounts, onSave, onClose, token }) {
  const [form, setForm] = useState({
    date: todayWIB(),
    memo: '',
    je_number: '',
    post: false,
    lines: [
      { account_code: '', debit: 0, credit: 0, description: '' },
      { account_code: '', debit: 0, credit: 0, description: '' },
    ],
  });
  // SESI #19 — kebijakan penomoran Jurnal Umum (Otomatis/Manual) dari Administrasi
  // Sistem → Penomoran Dokumen. Jurnal hasil posting otomatis dokumen lain tetap
  // bernomor otomatis; yang diatur di sini adalah jurnal yang diketik orang.
  const numPolicy = useDocNumberPolicy('rahaza_journal_entries.je_number', token);
  const handle = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const setLine = (i, k, v) => setForm(f => ({ ...f, lines: f.lines.map((ln, idx) => idx === i ? { ...ln, [k]: v } : ln) }));
  const addLine = () => setForm(f => ({ ...f, lines: [...f.lines, { account_code: '', debit: 0, credit: 0, description: '' }] }));
  const removeLine = (i) => setForm(f => ({ ...f, lines: f.lines.filter((_, idx) => idx !== i) }));

  const totalD = form.lines.reduce((s, l) => s + (Number(l.debit) || 0), 0);
  const totalC = form.lines.reduce((s, l) => s + (Number(l.credit) || 0), 0);
  const balanced = totalD === totalC && totalD > 0;
  const nomorSiap = numPolicy?.mode !== 'manual' || !!form.je_number.trim();
  // 2026-11-07 (audit form Tahap 5): baris berangka tanpa akun dulu DIBUANG diam-diam saat simpan (indikator
  // "Seimbang" tetap hijau, lalu server menolak "tidak seimbang"/"minimal 2 baris"). Kini disebut per baris.
  const lineProblem = (() => {
    const filled = form.lines.filter(l => l.account_code);
    for (let i = 0; i < form.lines.length; i += 1) {
      const l = form.lines[i];
      const amt = (Number(l.debit) || 0) + (Number(l.credit) || 0);
      if (!l.account_code && amt > 0) return `Baris ${i + 1}: pilih akunnya.`;
      if (l.account_code && amt <= 0) return `Baris ${i + 1}: isi debit atau kredit.`;
    }
    return filled.length < 2 ? 'Isi minimal 2 baris berakun.' : '';
  })();

  const submit = (asDraft) => {
    const body = {
      date: form.date,
      memo: form.memo,
      post: !asDraft,
      ...docNumberPayload(numPolicy, 'je_number', form.je_number),
      lines: form.lines.filter(l => l.account_code).map(l => ({
        account_code: l.account_code,
        debit: Number(l.debit) || 0,
        credit: Number(l.credit) || 0,
        description: l.description || '',
      })),
    };
    onSave(body);
  };

  const postableAccounts = accounts.filter(a => !a.is_group);
  // 2026-11-07 (Tahap 6, KU4): baris ke akun kontrol piutang/hutang (penanda server `control_kind`, dari penanda
  // akun / induk sub-ledger) diberi PERINGATAN — tidak memblokir simpan.
  const controlKindOf = (code) => (code && accounts.find(a => a.code === code)?.control_kind) || '';

  // 2026-11-08 (Standar UI/UX v2): form SELALU popup — FormPopup panjang (dulu panel di atas daftar).
  // Kaki: [Simpan draf] · Batal · Simpan & posting (hijau).
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="je-editor"
      judul="Jurnal baru" keterangan="Minimal 2 baris; total debit harus sama dengan total kredit."
      onSimpan={() => submit(false)} labelSimpan="Simpan & posting" bisaSimpan={balanced && nomorSiap && !lineProblem}
      aksiKiri={<Button type="button" variant="outline" onClick={() => submit(true)} disabled={!balanced || !nomorSiap || !!lineProblem} data-testid="je-save-draft">Simpan draf</Button>}>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Isian label="Tanggal" wajib>
          <DatePicker id="je-input-date" value={form.date} onChange={v => handle('date', v)} bolehKosong={false} testId="je-input-date" />
        </Isian>
        <Isian label="Memo / keterangan" htmlFor="je-input-memo" className="md:col-span-2">
          <GlassInput id="je-input-memo" value={form.memo} onChange={e => handle('memo', e.target.value)} placeholder="Mis. Setoran modal awal" data-testid="je-input-memo" />
        </Isian>
        <div className="md:col-span-3">
          <DocNumberField
            policy={numPolicy}
            value={form.je_number}
            onChange={v => handle('je_number', v)}
            label="Nomor jurnal"
            testId="je-number"
          />
        </div>
      </div>

      <p className="text-sm font-medium text-foreground">Baris jurnal</p>
      <div className="space-y-3 sm:space-y-2">
        {form.lines.map((ln, i) => {
          const ctl = controlKindOf(ln.account_code);
          return (
          <div key={i} className="grid grid-cols-2 sm:grid-cols-12 gap-2 items-start">
            <div className="col-span-2 sm:col-span-5">
              <SmartNativeSelect
                value={ln.account_code}
                onChange={e => setLine(i, 'account_code', e.target.value)}
                className="w-full h-9"
                aria-label={`Akun baris ${i + 1}`}
                data-testid={`je-line-${i}-account`}
              >
                <option value="">— Pilih akun —</option>
                {postableAccounts.map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
              </SmartNativeSelect>
            </div>
            <div className="sm:col-span-2">
              <MoneyInput decimals={2} glass value={ln.debit} onChange={e => { setLine(i, 'debit', e.target.value); if (Number(e.target.value) > 0) setLine(i, 'credit', 0); }} placeholder="Debit" aria-label={`Debit baris ${i + 1}`} data-testid={`je-line-${i}-debit`} />
            </div>
            <div className="sm:col-span-2">
              <MoneyInput decimals={2} glass value={ln.credit} onChange={e => { setLine(i, 'credit', e.target.value); if (Number(e.target.value) > 0) setLine(i, 'debit', 0); }} placeholder="Kredit" aria-label={`Kredit baris ${i + 1}`} data-testid={`je-line-${i}-credit`} />
            </div>
            <div className="sm:col-span-2">
              <GlassInput value={ln.description} onChange={e => setLine(i, 'description', e.target.value)} placeholder="Uraian" aria-label={`Uraian baris ${i + 1}`} data-testid={`je-line-${i}-desc`} />
            </div>
            <div className="sm:col-span-1 flex items-center justify-end sm:justify-center">
              {form.lines.length > 2 && (
                <Button variant="ghost" size="icon-sm" onClick={() => removeLine(i)} title="Hapus baris" aria-label="Hapus baris" data-testid={`je-line-${i}-remove`}>
                  <Trash2 className="w-3.5 h-3.5 text-[hsl(var(--danger-text))]" />
                </Button>
              )}
            </div>
            {ctl && (
              <p className="col-span-2 sm:col-span-12 -mt-1 text-xs text-[hsl(var(--warning-text))]" data-testid={`je-line-${i}-control-warning`}>
                {ctl === 'ap'
                  ? 'Akun hutang usaha: sebaiknya dicatat lewat faktur pemasok dan pembayarannya, supaya rincian hutang per pemasok tetap benar. Jurnal tetap bisa disimpan.'
                  : 'Akun piutang usaha: sebaiknya dicatat lewat faktur penjualan dan penerimaan pembayarannya, supaya rincian piutang per pelanggan tetap benar. Jurnal tetap bisa disimpan.'}
              </p>
            )}
          </div>
          );
        })}
      </div>
      <Button type="button" size="sm" variant="outline" onClick={addLine} data-testid="je-add-line"><Plus className="w-3.5 h-3.5" />Tambah baris</Button>

      <div className="flex gap-4 text-sm flex-wrap pt-3 border-t border-[var(--glass-border)]">
        <div><span className="text-muted-foreground">Total debit </span><span className="font-semibold tabular-nums">{fmt(totalD)}</span></div>
        <div><span className="text-muted-foreground">Total kredit </span><span className="font-semibold tabular-nums">{fmt(totalC)}</span></div>
        <div className={`font-semibold ${balanced ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}`} data-testid="je-balanced-indicator">
          {balanced ? 'Seimbang' : 'Tidak seimbang (selisih ' + fmt(Math.abs(totalD - totalC)) + ')'}
        </div>
        {lineProblem && <div className="text-[hsl(var(--warning-text))]" data-testid="je-line-problem">{lineProblem}</div>}
      </div>
    </FormPopup>
  );
}

/** Aksi & keterangan satu jurnal — di bawah isi jurnal yang dibuka di bawah barisnya (dulu kartu di atas tabel). */
function JournalRowActions({ je, onPost, onVoid, onDelete }) {
  return (
    <div className="flex items-center justify-between gap-3 flex-wrap mt-3 pt-3 border-t border-[var(--glass-border)]">
      <div className="text-xs text-muted-foreground">
        Dibuat oleh <span className="text-foreground/80">{je.created_by_name || '-'}</span> · Sumber: {journalSourceLabel(je.source_module)}
        {je.voided_at && <span className="ml-1 text-[hsl(var(--danger-text))]">· Dibatalkan</span>}
      </div>
      <div className="flex gap-2">
        {je.status === 'draft' && (
          <>
            <Button size="sm" variant="destructive" onClick={() => onDelete(je)} data-testid="je-delete"><Trash2 className="w-3.5 h-3.5" />Hapus draf</Button>
            <Button size="sm" variant="success" onClick={() => onPost(je)} data-testid="je-post"><Check className="w-3.5 h-3.5" />Posting jurnal</Button>
          </>
        )}
        {je.status === 'posted' && je.hub_voidable !== false && (
          <Button size="sm" variant="destructive" onClick={() => onVoid(je)} data-testid="je-void"><Ban className="w-3.5 h-3.5" />Batalkan</Button>
        )}
        {je.status === 'posted' && je.hub_voidable === false && (
          <span className="text-xs text-[hsl(var(--warning-text))] max-w-md text-right" data-testid="je-void-locked">
            Jurnal otomatis dari {journalSourceLabel(je.source_module)} — batalkan lewat dokumen sumbernya (batal faktur / batalkan pembayaran) supaya buku pembantu ikut berubah.
          </span>
        )}
      </div>
    </div>
  );
}

const PAGE = 25;
const STATUS_TABS = [
  { key: '', label: 'Semua' },
  { key: 'draft', label: 'Draf' },
  { key: 'posted', label: 'Terposting' },
  { key: 'voided', label: 'Dibatalkan' },
];

/**
 * Jurnal — SATU daftar semua jurnal (manual + otomatis), berpaginasi server.
 * 2026-11-04 (audit Keuangan): dulu ada dua daftar yang sama (tab "Jurnal Umum" bertajuk "Manual Journal
 * Entry" yang merender semua baris sekaligus — ±24 layar untuk 4 bulan — dan tab "Daftar Jurnal"), keduanya
 * dipotong diam-diam di 500 baris, dibuka di bulan berjalan (kosong di awal bulan), sumber berupa kode mentah.
 * Kini: pemilih periode bersama (bawaan 3 bulan), tab status berangka menggantikan 4 kartu hitungan,
 * penyaring sumber/akun/cari, Unduh CSV, dan "+ Jurnal baru" di halaman yang sama.
 * 2026-11-05 (PANDUAN_UI G1/G4/G13, arahan owner): cetakan PageLayout; status = pil penyaring (dulu tab garis
 * bawah); klik nomor jurnal membuka baris-barisnya DI BAWAH barisnya (dulu kartu detail di atas tabel).
 * 2026-11-08 (Standar UI/UX v2): jurnal baru = FormPopup panjang + DatePicker; alasan batal lewat dialog konfirmasi;
 * unduh Excel/CSV semua jurnal tersaring; Posting hijau / Hapus & Batalkan merah; memo "Expense:" → "Pengeluaran:".
 */
export default function RahazaJournalEntryModule({ token }) {
  // Tahap 8: pemilih akun hanya menampilkan akun yang berlaku untuk CV terpilih
  const coaCv = cvAccountParam(useCv()?.cv);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState({});
  const [skip, setSkip] = useState(0);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [detailId, setDetailId] = useState(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [period, setPeriod] = useState(() => periodFromPreset('3m'));
  const [source, setSource] = useState('');
  const [accountCode, setAccountCode] = useState('');
  const [search, setSearch] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  // cari dikirim ke server setelah berhenti mengetik (bukan menyaring halaman yang sudah dimuat)
  useEffect(() => { const t = setTimeout(() => setSearchQ(search.trim()), 350); return () => clearTimeout(t); }, [search]);
  useEffect(() => { setSkip(0); }, [period.from, period.to, filterStatus, source, accountCode, searchQ]);

  const params = useCallback((page, pageSize) => {
    const p = new URLSearchParams({ from: period.from, to: period.to, page: String(page), page_size: String(pageSize) });
    if (filterStatus) p.set('status', filterStatus);
    if (source) p.set('source', source);
    if (accountCode) p.set('account_code', accountCode);
    if (searchQ) p.set('q', searchQ);
    return p;
  }, [period.from, period.to, filterStatus, source, accountCode, searchQ]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/journals?${params(Math.floor(skip / PAGE) + 1, PAGE)}`, { headers });
      const d = r.ok ? await r.json() : {};
      setRows(d.items || []); setTotal(d.total || 0); setCounts(d.status_counts || {});
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, params, skip]);
  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    // with_control (KU4): server menandai akun kontrol piutang/hutang untuk peringatan di baris jurnal baru
    fetch(`/api/rahaza/coa/accounts?with_control=true${coaCv ? `&${coaCv}` : ''}`, { headers }).then(r => (r.ok ? r.json() : [])).then(a => setAccounts(Array.isArray(a) ? a : []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const save = async (body) => {
    const r = await fetch('/api/rahaza/journals', { method: 'POST', headers, body: JSON.stringify(body) });
    if (r.ok) { setEditing(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Gagal menyimpan jurnal'); }
  };

  const postJE = async (je) => {
    const ok = await confirmDialog({
      title: `Posting jurnal ${je.je_number}?`, body: 'Setelah diposting, jurnal hanya bisa dibatalkan.', confirmLabel: 'Posting',
    });
    if (!ok) return;
    const r = await fetch(`/api/rahaza/journals/${je.id}/post`, { method: 'POST', headers });
    if (r.ok) { setDetailId(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Gagal memposting jurnal'); }
  };

  // Alasan pembatalan lewat dialog konfirmasi berisian (dulu popup buatan sendiri); jurnal pembalik dibuat server.
  const voidJE = async (je) => {
    const reason = await confirmDialog({
      title: `Batalkan jurnal ${je.je_number}?`, body: 'Jurnal pembalik dibuat otomatis. Tulis alasannya untuk jejak audit.',
      confirmLabel: 'Batalkan jurnal', cancelLabel: 'Kembali', danger: true,
      input: { label: 'Alasan', placeholder: 'Alasan membatalkan jurnal' },
    });
    if (!reason) return;
    const r = await fetch(`/api/rahaza/journals/${je.id}/void`, { method: 'POST', headers, body: JSON.stringify({ reason }) });
    if (r.ok) { setDetailId(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Gagal membatalkan jurnal'); }
  };

  const delDraft = async (je) => {
    if (!(await confirmDialog({ title: `Hapus draf ${je.je_number}?`, confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(`/api/rahaza/journals/${je.id}`, { method: 'DELETE', headers });
    if (r.ok) { setDetailId(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Gagal menghapus draf'); }
  };

  // Unduh: SEMUA jurnal sesuai penyaring (bukan hanya halaman ini), dibaca per halaman 200.
  const ambilSemua = async () => {
    const all = [];
    for (let page = 1; page <= 50; page += 1) {
      const r = await fetch(`/api/rahaza/journals?${params(page, 200)}`, { headers });
      const d = r.ok ? await r.json() : {};
      all.push(...(d.items || []));
      if (!d.items || all.length >= (d.total || 0)) break;
    }
    return all;
  };

  const allCount = Object.values(counts).reduce((s, n) => s + n, 0);
  const sources = Object.entries(JOURNAL_SOURCE_LABELS).filter(([k]) => k !== 'manual_journal' && k !== 'excel_import_mapped');
  const filtered = !!(source || accountCode || searchQ || filterStatus);

  const filters = (
    <>
      <PeriodPicker value={period} onChange={setPeriod} testId="je-period" />
      <SmartNativeSelect value={source} onChange={e => setSource(e.target.value)} aria-label="Sumber jurnal"
        className="h-9 w-48" data-testid="je-filter-source">
        <option value="">Semua sumber</option>
        {sources.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
      </SmartNativeSelect>
      {/* 2026-11-07 (audit form Tahap 5): akun dipilih dari Bagan Akun (dulu kotak teks "Kode akun" yang harus
          diketik persis) — kode · nama, bisa dicari. */}
      <SmartNativeSelect value={accountCode} onChange={e => setAccountCode(e.target.value)} aria-label="Akun"
        className="h-9 w-56" searchPlaceholder="Cari kode atau nama akun…" data-testid="je-filter-account">
        <option value="">Semua akun</option>
        {accounts.filter(a => !a.is_group).map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
      </SmartNativeSelect>
      <div className="relative w-full sm:w-64">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <GlassInput value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari nomor jurnal / memo / referensi…" aria-label="Cari jurnal" className="pl-9 h-9" data-testid="je-search" />
      </div>
      {/* status berangka (dulu tab garis bawah; sebelumnya 4 kartu hitungan Total/Posted/Draft/Voided) */}
      <FilterChips value={filterStatus} onChange={setFilterStatus} testId="je-status" ariaLabel="Status jurnal"
        options={STATUS_TABS.map(t => ({ key: t.key, label: t.label, count: t.key ? (counts[t.key] || 0) : allCount }))} />
    </>
  );

  return (
    <PageLayout
      testId="rahaza-je-page"
      title="Jurnal"
      subtitle="Semua jurnal, manual maupun otomatis dari dokumen."
      actions={<Button onClick={() => setEditing({})} disabled={accounts.length === 0} data-testid="je-add"><Plus className="w-4 h-4" />Jurnal baru</Button>}
      filters={filters}
      tools={<>
        <Button size="icon" variant="outline" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="je-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`jurnal-${period.from}-${period.to}`} namaLembar="Jurnal" baris={rows} ambilSemua={ambilSemua} testId="je-export"
          kolom={[
            { label: 'No. jurnal', nilai: (j) => j.je_number },
            { label: 'Tanggal', nilai: (j) => formatDateID(j.date) },
            { label: 'Status', nilai: (j) => finStatus(j.status).label },
            { label: 'Sumber', nilai: (j) => journalSourceLabel(j.source_module) },
            { label: 'Referensi', nilai: (j) => j.source_ref || '' },
            { label: 'Memo', nilai: (j) => memoID(j.memo) },
            { label: 'Debit', nilai: (j) => Number(j.total_debit) || 0 },
            { label: 'Kredit', nilai: (j) => Number(j.total_credit) || 0 },
          ]} />
      </>}

      footer={<PaginationBar total={total} skip={skip} limit={PAGE} onPageChange={setSkip} />}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={FileText} title={filtered ? 'Tidak ada jurnal yang cocok' : 'Belum ada jurnal di periode ini'}
            description={filtered ? 'Ubah penyaring, pencarian, atau periode.' : 'Pilih periode lain, atau buat jurnal baru.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="w-10"><span className="sr-only">Rincian</span></th>
                  <th className="text-left">No. jurnal</th>
                  <th className="text-left">Tanggal</th>
                  <th className="text-left">Memo</th>
                  <th className="text-left hidden md:table-cell">Sumber</th>
                  <th className="text-left">Status</th>
                  <th className="text-right">Total (Rp)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(j => {
                  const open = detailId === j.id;
                  const toggle = () => setDetailId(open ? null : j.id);
                  return (
                    <Fragment key={j.id}>
                      <tr
                        onClick={toggle}
                        className={`border-b border-[var(--glass-border)] hover:bg-foreground/5 cursor-pointer ${open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}
                        data-testid={`je-row-${j.je_number}`}
                      >
                        <td onClick={e => e.stopPropagation()}>
                          <RowToggle open={open} onClick={toggle} label="Lihat isi jurnal" testId={`je-toggle-${j.je_number}`} />
                        </td>
                        <td className="whitespace-nowrap">
                          <Button variant="link" size="sm" className="h-auto p-0" onClick={e => { e.stopPropagation(); toggle(); }}>{j.je_number}</Button>
                        </td>
                        <td className="whitespace-nowrap">{formatDateID(j.date)}</td>
                        <td className="min-w-[12rem]">{j.memo ? memoID(j.memo) : '—'}</td>
                        <td className="text-muted-foreground hidden md:table-cell">{journalSourceLabel(j.source_module)}</td>
                        <td><StatusBadge status={j.status} /></td>
                        <td className="text-right tabular-nums whitespace-nowrap">{formatNumber(j.total_debit)}</td>
                      </tr>
                      {open && (
                        <RowDetail colSpan={7} testId="je-detail">
                          <JournalLinesInline jeId={j.id} token={token} testId={`je-lines-${j.je_number}`} />
                          <JournalRowActions je={j} onPost={postJE} onVoid={voidJE} onDelete={delDraft} />
                        </RowDetail>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      {editing && <JournalEditor accounts={accounts} onSave={save} onClose={() => setEditing(null)} token={token} />}
    </PageLayout>
  );
}
