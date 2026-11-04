import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Plus, RefreshCw, Trash2, BookCheck, FileText, X, Check, Ban, Search, Download } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader } from './moduleAtoms';
import PaginationBar from '@/components/ui/PaginationBar';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { JOURNAL_SOURCE_LABELS, journalSourceLabel, finStatus } from '../../lib/financeLabels';
import { formatDateID, formatNumber } from '@/lib/format';
import { IconButton } from './IconButton';
import { formatRupiah } from '@/lib/format';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';

const fmt = formatRupiah;

const STATUS_COLORS = {
  draft: 'text-amber-300 bg-amber-400/10 border-amber-400/25',
  posted: 'text-emerald-300 bg-emerald-400/10 border-emerald-400/25',
  voided: 'text-red-300 bg-red-400/10 border-red-400/25',
};

function StatusBadge({ status }) {
  const cls = STATUS_COLORS[status] || 'text-foreground/70 bg-foreground/5 border-foreground/10';
  return <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${cls}`}>{finStatus(status).label}</span>;
}

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

  return (
    <GlassCard className="p-5" data-testid="je-editor">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-foreground">Jurnal Baru</h3>
        <IconButton label="Tutup editor" onClick={onClose} className="text-muted-foreground hover:text-foreground p-1" data-testid="je-editor-close"><X className="w-4 h-4" /></IconButton>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <div>
          <label className="text-[10px] uppercase text-muted-foreground font-semibold">Tanggal *</label>
          <GlassInput type="date" value={form.date} onChange={e => handle('date', e.target.value)} data-testid="je-input-date" />
        </div>
        <div className="md:col-span-2">
          <label className="text-[10px] uppercase text-muted-foreground font-semibold">Memo / Deskripsi</label>
          <GlassInput value={form.memo} onChange={e => handle('memo', e.target.value)} placeholder="Mis. Setoran modal awal" data-testid="je-input-memo" />
        </div>
        <div className="md:col-span-3">
          <DocNumberField
            policy={numPolicy}
            value={form.je_number}
            onChange={v => handle('je_number', v)}
            label="Nomor Jurnal"
            testId="je-number"
          />
        </div>
      </div>

      <div className="mb-2">
        <label className="text-[10px] uppercase text-muted-foreground font-semibold">Baris Jurnal (minimal 2, debit=credit)</label>
      </div>
      <div className="space-y-2 mb-4">
        {form.lines.map((ln, i) => (
          <div key={i} className="grid grid-cols-12 gap-2 items-start">
            <div className="col-span-5">
              <SmartNativeSelect
                value={ln.account_code}
                onChange={e => setLine(i, 'account_code', e.target.value)}
                className="w-full h-9 rounded-[var(--radius-sm)] bg-[var(--card-surface)] border border-[var(--glass-border)] px-2 text-sm text-foreground backdrop-blur-sm"
                data-testid={`je-line-${i}-account`}
              >
                <option value="">— Pilih akun —</option>
                {postableAccounts.map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
              </SmartNativeSelect>
            </div>
            <div className="col-span-2">
              <MoneyInput decimals={2} glass value={ln.debit} onChange={e => { setLine(i, 'debit', e.target.value); if (Number(e.target.value) > 0) setLine(i, 'credit', 0); }} placeholder="Debit" data-testid={`je-line-${i}-debit`} />
            </div>
            <div className="col-span-2">
              <MoneyInput decimals={2} glass value={ln.credit} onChange={e => { setLine(i, 'credit', e.target.value); if (Number(e.target.value) > 0) setLine(i, 'debit', 0); }} placeholder="Credit" data-testid={`je-line-${i}-credit`} />
            </div>
            <div className="col-span-2">
              <GlassInput value={ln.description} onChange={e => setLine(i, 'description', e.target.value)} placeholder="Uraian" data-testid={`je-line-${i}-desc`} />
            </div>
            <div className="col-span-1 flex items-center justify-center">
              {form.lines.length > 2 && (
                <button onClick={() => removeLine(i)} className="text-red-300 hover:bg-red-400/10 rounded p-1.5" data-testid={`je-line-${i}-remove`}><Trash2 className="w-3.5 h-3.5" /></button>
              )}
            </div>
          </div>
        ))}
      </div>
      <Button size="sm" variant="outline" onClick={addLine} className="text-xs border-dashed" data-testid="je-add-line"><Plus className="w-3 h-3 mr-1" />Tambah Baris</Button>

      <div className="mt-5 flex items-center justify-between flex-wrap gap-3 pt-4 border-t border-[var(--glass-border)]">
        <div className="flex gap-4 text-sm">
          <div><span className="text-muted-foreground text-xs">Total Debit: </span><span className="font-mono font-semibold">{fmt(totalD)}</span></div>
          <div><span className="text-muted-foreground text-xs">Total Credit: </span><span className="font-mono font-semibold">{fmt(totalC)}</span></div>
          <div className={`font-semibold ${balanced ? 'text-emerald-300' : 'text-red-300'}`} data-testid="je-balanced-indicator">
            {balanced ? 'Seimbang ✓' : 'Tidak Seimbang (Δ ' + fmt(Math.abs(totalD - totalC)) + ')'}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onClose} data-testid="je-editor-cancel">Batal</Button>
          <Button variant="outline" onClick={() => submit(true)} disabled={!balanced || !nomorSiap} data-testid="je-save-draft">Simpan Draft</Button>
          <Button onClick={() => submit(false)} disabled={!balanced || !nomorSiap} data-testid="je-save-post">Simpan & Post</Button>
        </div>
      </div>
    </GlassCard>
  );
}

function JournalDetail({ je, onPost, onVoid, onDelete, onClose }) {
  return (
    <GlassCard className="p-5" data-testid="je-detail">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-foreground font-mono">{je.je_number}</h3>
          <div className="text-xs text-muted-foreground mt-0.5">{je.date} · {je.memo || '—'}</div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={je.status} />
          <IconButton label="Tutup detail jurnal" onClick={onClose} className="text-muted-foreground hover:text-foreground p-1" data-testid="je-detail-close"><X className="w-4 h-4" /></IconButton>
        </div>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[10px] uppercase text-muted-foreground border-b border-[var(--glass-border)]">
            <th className="py-2 pr-2">Akun</th>
            <th className="py-2 pr-2">Deskripsi</th>
            <th className="py-2 pr-2 text-right">Debit</th>
            <th className="py-2 pr-2 text-right">Credit</th>
          </tr>
        </thead>
        <tbody>
          {je.lines.map(ln => (
            <tr key={ln.line_id} className="border-b border-[var(--glass-border)]">
              <td className="py-2 pr-2"><span className="font-mono text-xs text-muted-foreground">{ln.account_code}</span> {ln.account_name}</td>
              <td className="py-2 pr-2 text-xs text-foreground/70">{ln.description || '-'}</td>
              <td className="py-2 pr-2 text-right font-mono text-xs">{ln.debit ? fmt(ln.debit) : ''}</td>
              <td className="py-2 pr-2 text-right font-mono text-xs">{ln.credit ? fmt(ln.credit) : ''}</td>
            </tr>
          ))}
          <tr className="font-semibold">
            <td colSpan={2} className="py-2 pr-2 text-right text-xs">TOTAL</td>
            <td className="py-2 pr-2 text-right font-mono">{fmt(je.total_debit)}</td>
            <td className="py-2 pr-2 text-right font-mono">{fmt(je.total_credit)}</td>
          </tr>
        </tbody>
      </table>
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--glass-border)]">
        <div className="text-[11px] text-muted-foreground">
          Dibuat oleh <span className="text-foreground/80">{je.created_by_name || '-'}</span> · Sumber: {je.source_module}
          {je.voided_at && <span className="ml-2 text-red-300">· Voided</span>}
        </div>
        <div className="flex gap-2">
          {je.status === 'draft' && (
            <>
              <Button size="sm" variant="outline" onClick={() => onDelete(je)} className="text-xs border-red-400/25 text-red-300" data-testid="je-delete"><Trash2 className="w-3 h-3 mr-1" />Hapus Draft</Button>
              <Button size="sm" onClick={() => onPost(je)} className="text-xs" data-testid="je-post"><Check className="w-3 h-3 mr-1" />Post Jurnal</Button>
            </>
          )}
          {je.status === 'posted' && je.hub_voidable !== false && (
            <Button size="sm" variant="outline" onClick={() => onVoid(je)} className="text-xs border-red-400/25 text-red-300" data-testid="je-void"><Ban className="w-3 h-3 mr-1" />Void</Button>
          )}
          {je.status === 'posted' && je.hub_voidable === false && (
            <span className="text-[11px] text-amber-300/90 max-w-xs text-right" data-testid="je-void-locked">
              Jurnal otomatis dari modul <span className="font-mono">{je.source_module}</span> — batalkan lewat dokumen sumbernya (batal invoice / void pembayaran) supaya subledger ikut berubah.
            </span>
          )}
        </div>
      </div>
    </GlassCard>
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
 */
export default function RahazaJournalEntryModule({ token }) {
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
    fetch('/api/rahaza/coa/accounts', { headers }).then(r => (r.ok ? r.json() : [])).then(a => setAccounts(Array.isArray(a) ? a : []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const save = async (body) => {
    const r = await fetch('/api/rahaza/journals', { method: 'POST', headers, body: JSON.stringify(body) });
    if (r.ok) { setEditing(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };

  const postJE = async (je) => {
    if (!(await confirmDialog(`Posting jurnal ${je.je_number}? Setelah diposting, jurnal hanya bisa dibatalkan.`))) return;
    const r = await fetch(`/api/rahaza/journals/${je.id}/post`, { method: 'POST', headers });
    if (r.ok) { setDetailId(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };

  const voidJE = async (je) => {
    const reason = window.prompt(`Alasan membatalkan jurnal ${je.je_number}?`);
    if (reason === null) return;
    const r = await fetch(`/api/rahaza/journals/${je.id}/void`, { method: 'POST', headers, body: JSON.stringify({ reason }) });
    if (r.ok) { setDetailId(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };

  const delDraft = async (je) => {
    if (!(await confirmDialog(`Hapus draf ${je.je_number}?`))) return;
    const r = await fetch(`/api/rahaza/journals/${je.id}`, { method: 'DELETE', headers });
    if (r.ok) { setDetailId(null); fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };

  // Unduh CSV: SEMUA jurnal sesuai penyaring (bukan hanya halaman ini), dibaca per halaman 200.
  const exportCSV = async () => {
    const all = [];
    for (let page = 1; page <= 50; page += 1) {
      const r = await fetch(`/api/rahaza/journals?${params(page, 200)}`, { headers });
      const d = r.ok ? await r.json() : {};
      all.push(...(d.items || []));
      if (!d.items || all.length >= (d.total || 0)) break;
    }
    const esc = (c) => { const v = String(c ?? ''); return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; };
    const csv = [['No. jurnal', 'Tanggal', 'Status', 'Sumber', 'Referensi', 'Memo', 'Debit', 'Kredit'],
      ...all.map(j => [j.je_number, j.date, finStatus(j.status).label, journalSourceLabel(j.source_module), j.source_ref || '', j.memo || '', j.total_debit, j.total_credit])]
      .map(r => r.map(esc).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = `jurnal-${period.from}-${period.to}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  const detailJE = detailId ? rows.find(j => j.id === detailId) : null;
  const allCount = Object.values(counts).reduce((s, n) => s + n, 0);
  const sources = Object.entries(JOURNAL_SOURCE_LABELS).filter(([k]) => k !== 'manual_journal' && k !== 'excel_import_mapped');

  return (
    <div className="space-y-4" data-testid="rahaza-je-page">
      <PageHeader
        icon={BookCheck}
        title="Jurnal"
        subtitle="Semua jurnal, manual maupun otomatis dari dokumen."
        actions={
          <>
            <Button size="icon" variant="outline" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="je-refresh"><RefreshCw className="w-3.5 h-3.5" /></Button>
            <Button variant="outline" onClick={exportCSV} disabled={!total} data-testid="je-export"><Download className="w-3.5 h-3.5 mr-1.5" />Unduh CSV</Button>
            <Button onClick={() => setEditing({})} disabled={accounts.length === 0} data-testid="je-add"><Plus className="w-3.5 h-3.5 mr-1.5" />Jurnal baru</Button>
          </>
        }
      />

      {editing && <JournalEditor accounts={accounts} onSave={save} onClose={() => setEditing(null)} token={token} />}
      {detailJE && <JournalDetail je={detailJE} onPost={postJE} onVoid={voidJE} onDelete={delDraft} onClose={() => setDetailId(null)} />}

      <GlassCard className="p-4">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <PeriodPicker value={period} onChange={setPeriod} testId="je-period" />
          <select value={source} onChange={e => setSource(e.target.value)} aria-label="Sumber jurnal"
            className="h-8 rounded-[var(--radius-sm)] bg-[var(--card-surface)] border border-[var(--glass-border)] px-2 text-xs text-foreground" data-testid="je-filter-source">
            <option value="">Semua sumber</option>
            {sources.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <GlassInput value={accountCode} onChange={e => setAccountCode(e.target.value.trim())} placeholder="Kode akun (opsional)" className="h-8 w-40" data-testid="je-filter-account" />
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <GlassInput value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari nomor jurnal / memo / referensi…" className="pl-8 h-8" data-testid="je-search" />
          </div>
        </div>
        {/* tab status berangka (dulu 4 kartu hitungan Total/Posted/Draft/Voided) */}
        <div className="flex gap-1 border-b border-[var(--glass-border)] mb-2" role="tablist" aria-label="Status jurnal">
          {STATUS_TABS.map(t => (
            <button key={t.key || 'all'} type="button" role="tab" aria-selected={filterStatus === t.key}
              onClick={() => setFilterStatus(t.key)} data-testid={`je-status-${t.key || 'all'}`}
              className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px ${filterStatus === t.key ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]' : 'border-transparent text-muted-foreground hover:text-foreground'}`}>
              {t.label} <span className="tabular-nums">{t.key ? (counts[t.key] || 0) : allCount}</span>
            </button>
          ))}
        </div>
        {loading ? (
          <div className="py-12 text-center text-muted-foreground">Memuat…</div>
        ) : rows.length === 0 ? (
          <div className="py-12 text-center text-muted-foreground">
            <FileText className="w-10 h-10 mx-auto mb-2 opacity-40" />
            Belum ada jurnal di periode ini.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-[var(--glass-border)]">
                  <th className="py-2 px-2 font-medium">No. jurnal</th>
                  <th className="py-2 px-2 font-medium">Tanggal</th>
                  <th className="py-2 px-2 font-medium">Memo</th>
                  <th className="py-2 px-2 font-medium">Sumber</th>
                  <th className="py-2 px-2 font-medium">Status</th>
                  <th className="py-2 px-2 font-medium text-right">Total (Rp)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(j => (
                  <tr
                    key={j.id}
                    onClick={() => setDetailId(j.id)}
                    className="border-b border-[var(--glass-border)] hover:bg-foreground/5 cursor-pointer"
                    data-testid={`je-row-${j.je_number}`}
                  >
                    <td className="py-2 px-2 font-mono text-xs">{j.je_number}</td>
                    <td className="py-2 px-2 text-xs whitespace-nowrap">{formatDateID(j.date)}</td>
                    <td className="py-2 px-2 text-xs">{j.memo || '-'}</td>
                    <td className="py-2 px-2 text-xs text-muted-foreground">{journalSourceLabel(j.source_module)}</td>
                    <td className="py-2 px-2"><StatusBadge status={j.status} /></td>
                    <td className="py-2 px-2 text-right font-mono text-xs">{formatNumber(j.total_debit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <PaginationBar total={total} skip={skip} limit={PAGE} onPageChange={setSkip} className="pt-3" />
      </GlassCard>
    </div>
  );
}
