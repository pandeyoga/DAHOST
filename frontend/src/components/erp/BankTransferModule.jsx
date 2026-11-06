/**
 * BankTransferModule — Transfer Bank Antar Rekening
 * CV. Dewi Aditya — Phase 6C
 *
 * Fitur:
 *  - Form transfer dari akun A ke akun B
 *  - Auto-posting GL (Dr Bank Tujuan / Cr Bank Sumber)
 *  - History transfer dengan status GL
 *  - Void transfer + retry posting
 *
 * 2026-11-05 (PANDUAN_UI G1/G5/G7/G13): cetakan PageLayout; satu kartu tabel (dulu Card shadcn berisi kotak
 * bergaris = kartu di dalam kartu); nomor jurnal dibuka di bawah barisnya (JournalLinesInline); sel nomor,
 * tanggal, dan uang tidak turun baris; label Indonesia ("Void" → "Batalkan", "Unposted" → "Belum dijurnal").
 */
import { Fragment, useState, useEffect, useCallback } from 'react';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import PageLayout, { RowDetail } from './layout/PageLayout';
import JournalLinesInline from './finance/JournalLinesInline';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { FINANCE_ROLES } from '../../lib/financeRoles'; // FIN-02
import {
  ArrowRightLeft, Plus, RefreshCw, CheckCircle2,
  Loader2, RotateCcw, AlertCircle, ArrowRight,
} from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { usePaymentCashAccounts } from './SdmCashAccountSelect';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';

const API = process.env.REACT_APP_BACKEND_URL;
const BASE = `${API}/api/finance/bank-transfers`;

const fmt = formatRupiah;
const fmtDate = (s) => s ? new Date(s).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : '-';

function token() { return localStorage.getItem('erp_token'); }
function userRole() {
  try { return JSON.parse(localStorage.getItem('erp_user') || '{}').role; } catch { return null; }
}


// Rekening sumber/tujuan = master rekening kas/bank AKTIF (SSOT `usePaymentCashAccounts`, sama dengan form
// bayar piutang/hutang/gaji). 2026-11-07 (audit form Tahap 5): daftar cadangan hard-code (Kas Kecil/BCA/Mandiri)
// dan bawaan 1-1201 → 1-1202 dilepas — dulu transfer bisa tersimpan dari/ke rekening yang tidak dipilih staf.
const BLANK = () => ({ from_account_code: '', to_account_code: '', amount: '', transfer_date: todayWIB(), memo: '', ref_external: '' });

// ── Transfer Form Dialog (formulir isian pendek — boleh popup, G13) ──────────
function TransferDialog({ open, onClose, onCreated }) {
  const [form, setForm] = useState(BLANK);
  const { accounts: cashAccounts, loaded } = usePaymentCashAccounts(token());
  const BANK_ACCOUNTS = cashAccounts.map(a => ({ code: a.gl_account_code, name: a.name }));
  const [saving, setSaving] = useState(false);
  const [err, setErr]   = useState('');
  const [result, setResult] = useState(null);
  // SESI #27 — kolom nomor dokumen mengikuti kebijakan Otomatis/Manual milik owner.
  // Tanpa ini, mode MANUAL berarti transfer TIDAK BISA dibuat (backend minta nomor
  // yang layarnya tak pernah tampilkan).
  const numPolicy = useDocNumberPolicy('rahaza_bank_transfers.ref_number', token());
  const [refNumber, setRefNumber] = useState('');

  useEffect(() => {
    if (open) {
      setForm(BLANK());
      setRefNumber('');
      setErr('');
      setResult(null);
    }
  }, [open]);

  const fromName = BANK_ACCOUNTS.find(a => a.code === form.from_account_code)?.name || form.from_account_code;
  const toName   = BANK_ACCOUNTS.find(a => a.code === form.to_account_code)?.name || form.to_account_code;

  const save = async () => {
    if (!form.from_account_code || !form.to_account_code) return setErr('Pilih rekening sumber dan rekening tujuan.');
    if (!form.amount || parseFloat(form.amount) <= 0) return setErr('Jumlah transfer harus lebih dari 0.');
    if (form.from_account_code === form.to_account_code) return setErr('Rekening sumber dan tujuan tidak boleh sama.');
    setSaving(true); setErr('');
    try {
      const res = await fetch(BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({
          ...form,
          ...docNumberPayload(numPolicy, 'ref_number', refNumber),
          amount: parseFloat(form.amount),
          from_account_name: fromName,
          to_account_name: toName,
        }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || 'Gagal membuat transfer');
      setResult(d);
      if (d.gl_posting?.ok) {
        toast.success(`Transfer ${d.transfer?.ref_number} tercatat · jurnal ${d.gl_posting.je_number || ''}`.trim());
      } else {
        toast.warning(`Transfer dicatat, tetapi jurnal gagal: ${d.gl_posting?.error || '?'}`);
      }
      onCreated();
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Transfer antar rekening</DialogTitle>
          <DialogDescription>
            Jurnal otomatis: debit {toName || 'rekening tujuan'} / kredit {fromName || 'rekening sumber'}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="py-4 space-y-3">
            <Notice tone={result.gl_posting?.ok ? 'success' : 'warning'} icon={result.gl_posting?.ok ? CheckCircle2 : AlertCircle}
              title={result.transfer?.ref_number}>
              <span className="text-xs">
                {result.gl_posting?.ok
                  ? `Jurnal ${result.gl_posting.je_number}`
                  : `Jurnal gagal: ${result.gl_posting?.error}`}
              </span>
            </Notice>
            <div className="text-sm text-muted-foreground space-y-1">
              <div className="flex justify-between">
                <span>Dari:</span><span className="font-medium">{result.transfer?.from_account_name}</span>
              </div>
              <div className="flex justify-between">
                <span>Ke:</span><span className="font-medium">{result.transfer?.to_account_name}</span>
              </div>
              <div className="flex justify-between">
                <span>Jumlah:</span><span className="font-bold text-foreground tabular-nums">{fmt(result.transfer?.amount)}</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-3 py-2">
            {err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}

            {/* Preview JE */}
            {form.amount > 0 && (
              <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/40 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{fromName}</span>
                <ArrowRight size={12} />
                <span className="font-medium text-foreground">{toName}</span>
                <span className="ml-auto font-bold text-foreground tabular-nums">{fmt(parseFloat(form.amount || 0))}</span>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Rekening sumber *</Label>
                <SmartNativeSelect value={form.from_account_code} onChange={e => setForm(p => ({ ...p, from_account_code: e.target.value }))}
                  className="w-full h-9" searchPlaceholder="Cari rekening…" data-testid="transfer-from">
                  <option value="">{loaded ? '— Pilih rekening sumber —' : 'Memuat rekening…'}</option>
                  {BANK_ACCOUNTS.map(a => (
                    <option key={a.code} value={a.code} disabled={a.code === form.to_account_code}>{`${a.name} · ${a.code}`}</option>
                  ))}
                </SmartNativeSelect>
              </div>
              <div className="space-y-1">
                <Label>Rekening tujuan *</Label>
                <SmartNativeSelect value={form.to_account_code} onChange={e => setForm(p => ({ ...p, to_account_code: e.target.value }))}
                  className="w-full h-9" searchPlaceholder="Cari rekening…" data-testid="transfer-to">
                  <option value="">{loaded ? '— Pilih rekening tujuan —' : 'Memuat rekening…'}</option>
                  {BANK_ACCOUNTS.map(a => (
                    <option key={a.code} value={a.code} disabled={a.code === form.from_account_code}>{`${a.name} · ${a.code}`}</option>
                  ))}
                </SmartNativeSelect>
              </div>
            </div>

            <div className="space-y-1">
              <Label>Jumlah (Rp) *</Label>
              <MoneyInput
                data-testid="transfer-amount"
                placeholder="5.000.000"
                value={form.amount}
                onChange={e => setForm(p => ({ ...p, amount: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Tanggal transfer</Label>
                <Input type="date" value={form.transfer_date} onChange={e => setForm(p => ({ ...p, transfer_date: e.target.value }))} data-testid="transfer-date" />
              </div>
              <div className="space-y-1">
                <Label>No. referensi bank</Label>
                <Input data-testid="transfer-ref" placeholder="opsional" value={form.ref_external} onChange={e => setForm(p => ({ ...p, ref_external: e.target.value }))} />
              </div>
            </div>
            <div className="space-y-1">
              <Label>Keterangan</Label>
              <Input data-testid="transfer-memo" placeholder="Tujuan transfer" value={form.memo} onChange={e => setForm(p => ({ ...p, memo: e.target.value }))} />
            </div>

            <DocNumberField
              policy={numPolicy} value={refNumber} onChange={setRefNumber}
              testId="transfer-docnum" label="Nomor dokumen transfer" />
          </div>
        )}

        <DialogFooter>
          {result ? (
            <Button onClick={onClose}>Tutup</Button>
          ) : (
            <>
              <Button variant="outline" onClick={onClose} disabled={saving}>Batal</Button>
              <Button data-testid="transfer-submit" onClick={save} disabled={saving}>
                {saving && <Loader2 size={13} className="animate-spin" />}
                Transfer & catat jurnal
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Module ────────────────────────────────────────────────────────────────
export default function BankTransferModule() {
  const [transfers, setTransfers] = useState([]);
  const [total, setTotal]   = useState(0);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [openJe, setOpenJe] = useState(null);

  const role = userRole();
  const canManage = FINANCE_ROLES.includes(role);

  const fetchTransfers = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${BASE}?limit=50`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      const d = await r.json();
      setTransfers(d.items || []);
      setTotal(d.total || 0);
    } catch { toast.error('Gagal memuat data transfer'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchTransfers(); }, [fetchTransfers]);

  const handleRetry = async (id) => {
    try {
      const r = await fetch(`${BASE}/${id}/retry-posting`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      const d = await r.json();
      if (d.ok || d.already_posted) { toast.success('Jurnal berhasil dibuat.'); fetchTransfers(); }
      else toast.error(`Jurnal gagal: ${d.error}`);
    } catch { toast.error('Koneksi bermasalah'); }
  };

  const handleVoid = async (tf) => {
    const ok = await confirmDialog({
      title: `Batalkan transfer ${tf.ref_number}?`,
      body: 'Jurnal pembalik akan dibuat otomatis.',
      confirmLabel: 'Batalkan transfer', cancelLabel: 'Tidak', danger: true,
    });
    if (!ok) return;
    try {
      const r = await fetch(`${BASE}/${tf.id}/void`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      const d = await r.json();
      if (d.ok) { toast.success(`Transfer ${tf.ref_number} dibatalkan${d.je_number ? ` · jurnal pembalik ${d.je_number}` : ''}`); fetchTransfers(); }
      else toast.error(d.error || 'Gagal membatalkan transfer');
    } catch { toast.error('Koneksi bermasalah'); }
  };

  const unpostedCount = transfers.filter(t => !t.gl_posted && t.status !== 'voided').length;
  const cols = canManage ? 8 : 7;

  return (
    <PageLayout
      testId="bank-transfer-page"
      title="Transfer Antar Rekening"
      subtitle="Memindah uang antar rekening sendiri (mis. bank → Kas Kecil). Jurnal terbentuk otomatis."
      actions={canManage && (
        <Button data-testid="create-transfer-btn" onClick={() => setDialogOpen(true)}>
          <Plus className="w-4 h-4" /> Transfer baru
        </Button>
      )}
      tools={
        <Button variant="outline" size="icon" onClick={fetchTransfers} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      }
      summary={<>
        {/* 2026-11-04: 3 kartu hitungan dilepas — jumlah ada di daftar, yang belum terjurnal di peringatan bawah */}
        <p className="text-sm text-muted-foreground" data-testid="transfer-count">
          {total} transfer{total > 50 ? ' · menampilkan 50 transfer terbaru' : ''}
        </p>
        {unpostedCount > 0 && (
          <Notice tone="warning" icon={AlertCircle}>
            {unpostedCount} transfer belum masuk buku besar. Tekan “Coba lagi” di baris yang bermasalah.
          </Notice>
        )}
      </>}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="animate-spin text-muted-foreground" />
          </div>
        ) : transfers.length === 0 ? (
          <EmptyState icon={ArrowRightLeft} title="Belum ada transfer antar rekening"
            description={canManage ? 'Tekan “Transfer baru” untuk memindah uang antar rekening sendiri.' : 'Transfer antar rekening akan tampil di sini.'} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>No. ref</TableHead>
                <TableHead>Tanggal</TableHead>
                <TableHead>Dari</TableHead>
                <TableHead>Ke</TableHead>
                <TableHead className="text-right">Jumlah</TableHead>
                <TableHead>Jurnal</TableHead>
                <TableHead>Status</TableHead>
                {canManage && <TableHead className="text-right">Aksi</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {transfers.map(tf => {
                const jeOpen = openJe === tf.id;
                const toggleJe = () => setOpenJe(jeOpen ? null : tf.id);
                return (
                  <Fragment key={tf.id}>
                    <TableRow data-testid={`transfer-row-${tf.id}`} className={jeOpen ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                      <TableCell className="text-xs whitespace-nowrap">{tf.ref_number}</TableCell>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{fmtDate(tf.transfer_date)}</TableCell>
                      <TableCell className="text-sm">{tf.from_account_name || tf.from_account_code}</TableCell>
                      <TableCell className="text-sm">
                        <span className="inline-flex items-center gap-1.5"><ArrowRight size={12} className="text-muted-foreground shrink-0" />{tf.to_account_name || tf.to_account_code}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap font-semibold text-sm">{fmt(tf.amount)}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        {tf.gl_posted ? (
                          tf.gl_je_id ? (
                            <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={toggleJe} aria-expanded={jeOpen}
                              title={jeOpen ? 'Tutup isi jurnal' : 'Lihat isi jurnal'} data-testid={`transfer-je-${tf.id}`}>
                              {tf.gl_je_number || 'Terjurnal'}
                            </Button>
                          ) : <span className="text-xs">{tf.gl_je_number || 'Terjurnal'}</span>
                        ) : (
                          <StatusBadge status="unposted" label="Belum dijurnal" tone="danger" />
                        )}
                      </TableCell>
                      <TableCell>
                        {tf.status === 'voided'
                          ? <StatusBadge status="voided" />
                          : <StatusBadge status="completed" label="Selesai" tone="default" />}
                      </TableCell>
                      {canManage && (
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            {!tf.gl_posted && tf.status !== 'voided' && (
                              <Button
                                variant="outline" size="sm"
                                data-testid={`retry-posting-${tf.id}`}
                                onClick={() => handleRetry(tf.id)}
                              >
                                <RotateCcw className="w-3.5 h-3.5" /> Coba lagi
                              </Button>
                            )}
                            {tf.status !== 'voided' && (
                              <Button
                                variant="outline" size="sm"
                                data-testid={`void-transfer-${tf.id}`}
                                onClick={() => handleVoid(tf)}
                                title="Batalkan transfer dan buat jurnal pembalik"
                              >
                                Batalkan
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      )}
                    </TableRow>
                    {jeOpen && tf.gl_je_id && (
                      <RowDetail colSpan={cols} testId={`transfer-je-detail-${tf.id}`}>
                        <JournalLinesInline jeId={tf.gl_je_id} token={token()} />
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      <TransferDialog open={dialogOpen} onClose={() => setDialogOpen(false)} onCreated={fetchTransfers} />
    </PageLayout>
  );
}
