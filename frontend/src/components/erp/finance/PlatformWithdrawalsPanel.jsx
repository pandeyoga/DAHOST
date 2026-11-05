/**
 * PlatformWithdrawalsPanel — TAHAP 2: penarikan saldo platform ke rekening bank.
 * Jurnal: Dr Rekening Pencairan toko / Cr Piutang Toko (1-1303-xxx). Dokumen inilah
 * yang dicocokkan ke mutasi bank di Rekonsiliasi Bank.
 *
 * 2026-11-05 (PANDUAN_UI G1/G7): isi tab Marketplace › Penarikan ke bank memakai cetakan PageLayout.
 * Penyaring toko dikirim dari FinanceSettlementModule (`filters`); tombol impor & catat di slot `actions`
 * (di hub pindah ke baris tab), muat ulang di `tools`. Dulu toolbar menempel di kanan dan kepala "Tahap 2"
 * + tombol ada di dalam kartu tabel. Nomor penarikan, tanggal, dan nominal tidak lagi dipatah ke dua baris.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatDateID } from '@/lib/format';
import { Button } from '@/components/ui/button';
import {
  ArrowDownToLine, Plus, X, Loader2, CheckCircle2, BookCheck, Send, Pencil, Trash2, Landmark, Upload, RefreshCw,
} from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { toast } from 'sonner';
import { formatRupiah as rp } from '@/lib/format';
import { finStatus } from '@/lib/financeLabels';
import { MoneyInput } from '@/components/ui/money-input';
import { EmptyState, Notice } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import { WithdrawalImportPanel, previewWithdrawalFile } from './WithdrawalImportPanel';
import { BankSelect } from './PayoutBankLinks';

const API = process.env.REACT_APP_BACKEND_URL;
const BASE = `${API}/api/marketing/withdrawals`;

async function call(path, opts = {}) {
  const r = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('erp_token')}` },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || d.message || `Gagal (HTTP ${r.status})`);
  return d;
}

const EMPTY = { account_id: '', withdrawal_date: '', amount: '', reference: '', notes: '', cash_code: '' };

export function PlatformWithdrawalsPanel({ accounts, accountId, balances, banks = [], onChanged, filters, testId = 'platform-withdrawals-page' }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState('');
  const [importRes, setImportRes] = useState(null);
  const [importFile, setImportFile] = useState(null);
  const [importAccount, setImportAccount] = useState('');
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ page_size: '50' });
      if (accountId) qs.set('account_id', accountId);
      const d = await call(`?${qs}`);
      setRows(d.data || []); setSummary(d.summary || null);
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [accountId]);
  useEffect(() => { load(); }, [load]);

  const accName = (id) => accounts.find((a) => a.id === id)?.account_name || id || '—';
  const accCash = (id) => accounts.find((a) => a.id === id)?.coa_cash_code || '';
  const bankName = (code) => banks.find((b) => b.code === code)?.name || '';
  const balanceOf = useMemo(() => {
    const m = {};
    (balances || []).forEach((b) => { m[b.account_id] = b; });
    return m;
  }, [balances]);
  const selBal = balanceOf[form.account_id];
  const available = selBal ? selBal.balance + (editId ? (rows.find((r) => r.id === editId)?.amount || 0) : 0) : null;

  const openCreate = () => {
    setForm({ ...EMPTY, account_id: accountId || '', cash_code: accCash(accountId) }); setEditId(''); setFormOpen(true);
  };
  const openEdit = (r) => {
    setForm({ account_id: r.account_id, withdrawal_date: r.withdrawal_date || '', amount: String(r.amount ?? ''),
      reference: r.reference || '', notes: r.notes || '', cash_code: r.cash_code || accCash(r.account_id) });
    setEditId(r.id); setFormOpen(true);
  };

  const refresh = async () => { await load(); onChanged?.(); };

  const startImport = async (file) => {
    if (!file) return;
    setBusy('import');
    try {
      let acc = accountId || '';
      let d = await previewWithdrawalFile(file, acc);
      if (!acc && d.platform_guess) {
        const cand = accounts.filter((a) => a.platform === d.platform_guess);
        if (cand.length === 1) { acc = cand[0].id; d = await previewWithdrawalFile(file, acc); }
      }
      setImportFile(file); setImportAccount(acc); setImportRes(d); setFormOpen(false);
      toast.success(`${d.ok_count} dari ${d.row_count} baris siap disimpan — periksa kolom & toko lalu simpan.`);
      if (!acc) toast.warning('Toko belum dipilih — pilih toko yang benar sebelum menyimpan.');
    } catch (e) { toast.error(e.message); } finally {
      setBusy('');
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const save = async () => {
    if (!form.account_id) { toast.error('Pilih toko dulu.'); return; }
    if (!form.withdrawal_date) { toast.error('Tanggal uang masuk bank wajib diisi.'); return; }
    if (!(parseFloat(form.amount) > 0)) { toast.error('Nominal penarikan harus lebih dari 0.'); return; }
    if (!form.cash_code) { toast.error('Pilih rekening bank tujuan.'); return; }
    setBusy('save');
    try {
      const body = { ...form, amount: parseFloat(form.amount) };
      await (editId ? call(`/${editId}`, { method: 'PUT', body: JSON.stringify(body) })
        : call('', { method: 'POST', body: JSON.stringify(body) }));
      toast.success(editId ? 'Penarikan diperbarui.' : 'Penarikan saldo tercatat — saldo platform toko berkurang.');
      setFormOpen(false);
      await refresh();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  const act = async (r, kind) => {
    setBusy(`${kind}:${r.id}`);
    try {
      if (kind === 'journal') toast.success((await call(`/${r.id}/journal`, { method: 'POST' })).message);
      else if (kind === 'post') toast.success((await call(`/${r.id}/post`, { method: 'POST' })).message);
      else if (kind === 'delete') { await call(`/${r.id}`, { method: 'DELETE' }); toast.success('Penarikan dihapus.'); }
      await refresh();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  const over = available != null && parseFloat(form.amount || 0) > available + 0.01;

  return (
    <PageLayout
      testId={testId}
      title="Marketplace"
      subtitle="Penarikan saldo platform ke rekening bank — dokumen yang dicocokkan ke mutasi bank."
      actions={<>
        <Button variant="outline" data-testid="wd-import" disabled={busy === 'import'} onClick={() => fileRef.current?.click()}
          title="Unggah laporan penarikan Shopee atau TikTok">
          {busy === 'import' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Impor laporan penarikan
        </Button>
        <Button data-testid="wd-new" onClick={openCreate}>
          <Plus className="w-4 h-4" /> Catat penarikan
        </Button>
      </>}
      filters={filters}
      tools={
        <Button variant="outline" size="icon" data-testid="fin-settlement-refresh" onClick={refresh} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className="w-4 h-4" />
        </Button>
      }
      summary={
        <p className="text-sm text-muted-foreground" data-testid="wd-summary">
          Total ditarik <b className="text-foreground tabular-nums">{rp(summary?.amount || 0)}</b>
          {summary ? ` · ${summary.bank_linked_count} tertaut mutasi bank` : ''}
          {' · '}jurnal: Dr Rekening pencairan / Cr Piutang toko
        </p>
      }
    >
      <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.tsv" className="hidden" data-testid="wd-import-file"
        onChange={(e) => startImport(e.target.files?.[0])} />

      <WithdrawalImportPanel result={importRes} file={importFile} accounts={accounts} accountId={importAccount} banks={banks}
        onAccountChange={setImportAccount} onResult={setImportRes} onClose={() => setImportRes(null)}
        onCommitted={async () => { setImportRes(null); await refresh(); }} />

      {formOpen ? (
        <GlassCard className="p-4 space-y-3" data-testid="wd-form">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium">{editId ? 'Koreksi penarikan' : 'Catat penarikan saldo'}</h4>
            <Button variant="outline" size="icon" data-testid="wd-form-close" onClick={() => setFormOpen(false)} title="Tutup" aria-label="Tutup">
              <X className="w-4 h-4" />
            </Button>
          </div>
          <div className="grid md:grid-cols-3 xl:grid-cols-6 gap-3">
            <label className="text-xs space-y-1">
              <span className="text-muted-foreground">Toko</span>
              <SmartNativeSelect data-testid="wd-input-account" value={form.account_id}
                onChange={(e) => setForm({ ...form, account_id: e.target.value, cash_code: accCash(e.target.value) || form.cash_code })}
                className="h-9 w-full">
                <option value="">— pilih toko —</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name} · {a.platform}</option>)}
              </SmartNativeSelect>
            </label>
            <label className="text-xs space-y-1">
              <span className="text-muted-foreground">Rekening bank tujuan</span>
              <BankSelect banks={banks} value={form.cash_code} testId="wd-input-bank"
                onChange={(v) => setForm({ ...form, cash_code: v })} />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-muted-foreground">Tanggal masuk bank</span>
              <GlassInput type="date" data-testid="wd-input-date" value={form.withdrawal_date}
                onChange={(e) => setForm({ ...form, withdrawal_date: e.target.value })} className="h-9" />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-muted-foreground">Nominal (menurut mutasi bank)</span>
              <MoneyInput glass data-testid="wd-input-amount" value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="h-9 text-right tabular-nums font-semibold" />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-muted-foreground">No. penarikan (platform, opsional)</span>
              <GlassInput data-testid="wd-input-reference" value={form.reference}
                onChange={(e) => setForm({ ...form, reference: e.target.value })} className="h-9" />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-muted-foreground">Catatan</span>
              <GlassInput data-testid="wd-input-notes" value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} className="h-9" />
            </label>
          </div>
          {form.account_id ? (
            <Notice tone={over ? 'danger' : 'info'} className="text-xs" testId="wd-available">
              Saldo platform toko yang bisa ditarik: <b className="tabular-nums">{rp(available || 0)}</b>
              {form.cash_code ? <> · masuk ke rekening {form.cash_code} {bankName(form.cash_code)}</> : <> · <span className="text-[hsl(var(--warning))]">rekening bank tujuan belum dipilih</span></>}
              {over ? ' — melebihi saldo; catat dulu laporan dana dilepas yang belum masuk.' : ''}
            </Notice>
          ) : null}
          <div className="flex gap-2">
            <Button data-testid="wd-save" disabled={busy === 'save'} onClick={save}>
              {busy === 'save' ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} Simpan
            </Button>
            <Button variant="outline" data-testid="wd-cancel" onClick={() => setFormOpen(false)}>Batal</Button>
          </div>
        </GlassCard>
      ) : null}

      <GlassCard className="p-0 overflow-hidden" data-testid="platform-withdrawals-panel">
        {loading ? (
          <div className="py-8 text-center text-xs text-muted-foreground flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> memuat penarikan…</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={ArrowDownToLine} testId="wd-empty"
            title={accountId ? 'Belum ada penarikan saldo untuk toko ini' : 'Belum ada penarikan saldo tercatat'}
            description="Tekan “Catat penarikan” atau “Impor laporan penarikan” setelah saldo platform masuk ke rekening bank." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="wd-table">
              <thead>
                <tr className="border-b border-[var(--glass-border)]">
                  <th className="text-left">Tanggal</th>
                  <th className="text-left">No. penarikan</th>
                  <th className="text-left">Toko</th>
                  <th className="text-right">Nominal</th>
                  <th className="text-left">Bank</th>
                  <th className="text-left">Jurnal</th>
                  <th className="text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const cash = r.cash_code || accCash(r.account_id);
                  return (
                    <tr key={r.id} className="border-b border-[var(--glass-border)]" data-testid={`wd-row-${r.reference}`}>
                      <td className="whitespace-nowrap">{formatDateID(r.withdrawal_date)}</td>
                      <td className="whitespace-nowrap">{r.reference}</td>
                      <td>{accName(r.account_id)} <span className="text-xs text-muted-foreground uppercase">{r.platform}</span></td>
                      <td className="text-right tabular-nums whitespace-nowrap font-medium">{rp(r.amount)}</td>
                      <td data-testid={`wd-bank-${r.reference}`}>
                        <div className="text-xs">{cash || '—'} {bankName(cash)}</div>
                        {r.bank_txn_id
                          ? <span className="text-[10px] text-[hsl(var(--success))] flex items-center gap-0.5 whitespace-nowrap"><Landmark className="w-3 h-3" /> mutasi {formatDateID(r.bank_txn_date)}</span>
                          : <span className="text-[10px] text-muted-foreground">belum tertaut</span>}
                      </td>
                      <td className="text-xs whitespace-nowrap">
                        {r.je_number ? <>{r.je_number} <span className="text-muted-foreground">({finStatus(r.je_status).label.toLowerCase()})</span></>
                          : <span className="text-muted-foreground">belum</span>}
                      </td>
                      <td>
                        <div className="flex items-center justify-end gap-1">
                          {!r.je_id ? (
                            <Button variant="ghost" size="icon-sm" title="Buat jurnal draf" aria-label="Buat jurnal draf" data-testid={`wd-journal-${r.reference}`}
                              disabled={busy === `journal:${r.id}`} onClick={() => act(r, 'journal')}><BookCheck className="w-4 h-4" /></Button>
                          ) : null}
                          {r.je_status === 'draft' ? (
                            <Button variant="ghost" size="icon-sm" title="Posting jurnal" aria-label="Posting jurnal" data-testid={`wd-post-${r.reference}`}
                              disabled={busy === `post:${r.id}`} onClick={() => act(r, 'post')} className="text-[hsl(var(--success))]"><Send className="w-4 h-4" /></Button>
                          ) : null}
                          {!r.je_id ? (
                            <>
                              <Button variant="ghost" size="icon-sm" title="Koreksi" aria-label="Koreksi" data-testid={`wd-edit-${r.reference}`}
                                onClick={() => openEdit(r)}><Pencil className="w-4 h-4" /></Button>
                              {!r.bank_txn_id ? (
                                <Button variant="ghost" size="icon-sm" title="Hapus" aria-label="Hapus" data-testid={`wd-delete-${r.reference}`}
                                  disabled={busy === `delete:${r.id}`} className="text-[hsl(var(--destructive))]"
                                  onClick={async () => { if (await confirmDialog({ title: `Hapus penarikan ${r.reference || formatDateID(r.withdrawal_date)}?`, confirmLabel: 'Hapus', danger: true })) act(r, 'delete'); }}>
                                  <Trash2 className="w-4 h-4" />
                                </Button>
                              ) : null}
                            </>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}
