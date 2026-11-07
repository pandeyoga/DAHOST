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
 * 2026-11-08 (Standar UI/UX v2): form = popup standar (FormPopup + DatePicker); daftar bisa diunduh Excel/CSV (semua baris).
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
  ArrowRightLeft, Plus, RefreshCw, Loader2, RotateCcw, AlertCircle, ArrowRight,
} from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { usePaymentCashAccounts } from './SdmCashAccountSelect';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
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
const UNDUH_KOLOM = [
  { label: 'No. ref', nilai: (t) => t.ref_number },
  { label: 'Tanggal', nilai: (t) => fmtDate(t.transfer_date) },
  { label: 'Dari', nilai: (t) => t.from_account_name || t.from_account_code },
  { label: 'Ke', nilai: (t) => t.to_account_name || t.to_account_code },
  { label: 'Jumlah', nilai: (t) => Number(t.amount) || 0 },
  { label: 'Jurnal', nilai: (t) => (t.gl_posted ? (t.gl_je_number || 'Terjurnal') : 'Belum dijurnal') },
  { label: 'Status', nilai: (t) => (t.status === 'voided' ? 'Dibatalkan' : 'Selesai') },
  { label: 'No. referensi bank', nilai: (t) => t.ref_external || '' },
  { label: 'Keterangan', nilai: (t) => t.memo || '' },
];

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

  // 2026-11-08 (Standar UI/UX v2): popup form standar. Setelah tersimpan popup ditutup; nomor transfer & jurnal
  // dikabarkan lewat toast dan barisnya langsung tampil di daftar (dulu layar hasil di dalam popup).
  useEffect(() => { if (result) onClose(); }, [result]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="transfer-form"
      judul="Transfer antar rekening"
      keterangan={`Jurnal otomatis: debit ${toName || 'rekening tujuan'} / kredit ${fromName || 'rekening sumber'}.`}
      onSimpan={save} menyimpan={saving} galat={err} labelSimpan="Transfer & catat jurnal">
      {form.amount > 0 && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="transfer-preview">
          <span className="font-medium text-foreground">{fromName || '—'}</span>
          <ArrowRight size={14} />
          <span className="font-medium text-foreground">{toName || '—'}</span>
          <span className="ml-auto font-semibold text-foreground tabular-nums">{fmt(parseFloat(form.amount || 0))}</span>
        </p>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Rekening sumber" wajib>
          <SmartNativeSelect value={form.from_account_code} onChange={e => setForm(p => ({ ...p, from_account_code: e.target.value }))}
            className="w-full h-9" searchPlaceholder="Cari rekening…" data-testid="transfer-from">
            <option value="">{loaded ? '— Pilih rekening sumber —' : 'Memuat rekening…'}</option>
            {BANK_ACCOUNTS.map(a => (
              <option key={a.code} value={a.code} disabled={a.code === form.to_account_code}>{`${a.name} · ${a.code}`}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Rekening tujuan" wajib>
          <SmartNativeSelect value={form.to_account_code} onChange={e => setForm(p => ({ ...p, to_account_code: e.target.value }))}
            className="w-full h-9" searchPlaceholder="Cari rekening…" data-testid="transfer-to">
            <option value="">{loaded ? '— Pilih rekening tujuan —' : 'Memuat rekening…'}</option>
            {BANK_ACCOUNTS.map(a => (
              <option key={a.code} value={a.code} disabled={a.code === form.from_account_code}>{`${a.name} · ${a.code}`}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Jumlah (Rp)" wajib>
          <MoneyInput data-testid="transfer-amount" placeholder="5.000.000" value={form.amount}
            onChange={e => setForm(p => ({ ...p, amount: e.target.value }))} />
        </Isian>
        <Isian label="Tanggal transfer">
          <DatePicker value={form.transfer_date} onChange={(v) => setForm(p => ({ ...p, transfer_date: v }))} bolehKosong={false} testId="transfer-date" />
        </Isian>
        <Isian label="No. referensi bank" htmlFor="transfer-ref">
          <Input id="transfer-ref" data-testid="transfer-ref" placeholder="opsional" value={form.ref_external} onChange={e => setForm(p => ({ ...p, ref_external: e.target.value }))} />
        </Isian>
        <Isian label="Keterangan" htmlFor="transfer-memo">
          <Input id="transfer-memo" data-testid="transfer-memo" placeholder="Tujuan transfer" value={form.memo} onChange={e => setForm(p => ({ ...p, memo: e.target.value }))} />
        </Isian>
      </div>
      <DocNumberField
        policy={numPolicy} value={refNumber} onChange={setRefNumber}
        testId="transfer-docnum" label="Nomor dokumen transfer" />
    </FormPopup>
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

  // Unduh: semua transfer (200 per permintaan, batas server), bukan hanya 50 terbaru yang tampil.
  const ambilSemua = async () => {
    const out = [];
    for (let skip = 0; skip < 20000; skip += 200) {
      const r = await fetch(`${BASE}?limit=200&skip=${skip}`, { headers: { Authorization: `Bearer ${token()}` } });
      if (!r.ok) throw new Error('gagal');
      const d = await r.json();
      out.push(...(d.items || []));
      if (!(d.items || []).length || out.length >= (d.total || 0)) break;
    }
    return out;
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
      tools={<>
        <TombolUnduh namaBerkas="transfer-antar-rekening" namaLembar="Transfer" baris={transfers} testId="transfer-unduh"
          kolom={UNDUH_KOLOM} ambilSemua={ambilSemua} />
        <Button variant="outline" size="icon" onClick={fetchTransfers} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {/* 2026-11-04: 3 kartu hitungan dilepas — jumlah ada di daftar, yang belum terjurnal di peringatan bawah */}
        <p className="text-sm text-muted-foreground" data-testid="transfer-count">
          {total} transfer{total > 50 ? ' · menampilkan 50 transfer terbaru (unduhan berisi semua)' : ''}
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
          <Table className="md:min-w-0">
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
                      <TableCell className="whitespace-nowrap">{tf.ref_number}</TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">{fmtDate(tf.transfer_date)}</TableCell>
                      <TableCell className="text-sm">{tf.from_account_name || tf.from_account_code}</TableCell>
                      <TableCell className="text-sm">
                        <span className="inline-flex items-center gap-1.5"><ArrowRight size={12} className="text-muted-foreground shrink-0" />{tf.to_account_name || tf.to_account_code}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap font-semibold">{fmt(tf.amount)}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        {tf.gl_posted ? (
                          tf.gl_je_id ? (
                            <Button variant="link" size="sm" className="h-auto p-0" onClick={toggleJe} aria-expanded={jeOpen}
                              title={jeOpen ? 'Tutup isi jurnal' : 'Lihat isi jurnal'} data-testid={`transfer-je-${tf.id}`}>
                              {tf.gl_je_number || 'Terjurnal'}
                            </Button>
                          ) : <span>{tf.gl_je_number || 'Terjurnal'}</span>
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
                                variant="destructive" size="sm"
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
