/**
 * Transaksi antar CV (Portal Keuangan, Tahap 8 fase 2 — keputusan owner K9, 7 Nov 2026).
 *
 * Talangan, pinjaman, uang nyasar, dan pelunasan di antara CV Dewi Aditya dan CV Sukma diinput SEKALI di CV
 * yang sedang dipilih (CV asal); sistem membuat DUA jurnal berlabel "antar CV" — satu di tiap buku — memakai
 * piutang/hutang lawan transaksi yang sudah ada (bukan akun atau modul tersendiri).
 *
 *   GET  /api/rahaza/intercompany/status                 akun lawan transaksi + jenis transaksi
 *   GET  /api/rahaza/intercompany/transactions           daftar (CV terpilih / Gabungan)
 *   POST /api/rahaza/intercompany/transactions           simpan (dua jurnal)
 *   POST /api/rahaza/intercompany/transactions/{id}/void batalkan (dua jurnal di-void)
 *
 * PANDUAN_UI: PageLayout; jurnal dibuka di bawah barisnya (RowDetail).
 * 2026-11-08 (Standar UI/UX v2): form = FormPopup standar + DatePicker; daftar bisa diunduh Excel/CSV.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, ArrowRightLeft, Loader2, Plus, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { MoneyInput } from '@/components/ui/money-input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { formatDateID, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { CV_DA, CV_SMU, cvLabel, useCv } from '@/lib/entitas';
import { apiGet, apiPost } from '../../../lib/api';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';

const fmt = formatRupiah;
const otherCv = (cv) => (cv === CV_SMU ? CV_DA : CV_SMU);
const BLANK = () => ({ kind: 'talangan', amount: '', date: todayWIB(), description: '', source_account_code: '', other_account_code: '' });

function useAccounts(cv) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    let off = false;
    if (!cv) return undefined;
    apiGet(`/rahaza/coa/accounts?entity=${cv}`)
      .then((d) => { if (!off) setRows((Array.isArray(d) ? d : d?.items || []).filter((a) => !a.is_group)); })
      .catch(() => { if (!off) setRows([]); });
    return () => { off = true; };
  }, [cv]);
  return rows;
}

function AccountSelect({ cv, value, onChange, exclude, testId, placeholder }) {
  const rows = useAccounts(cv);
  const options = rows.filter((a) => !exclude.has(a.code));
  return (
    <SmartNativeSelect value={value} onChange={(e) => onChange(e.target.value)} className="w-full h-9"
      searchPlaceholder="Cari kode atau nama akun…" data-testid={testId} aria-label={placeholder}>
      <option value="">{rows.length ? placeholder : 'Memuat akun…'}</option>
      {options.map((a) => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
    </SmartNativeSelect>
  );
}

function TransactionDialog({ open, cv, status, onClose, onSaved }) {
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [clientRef, setClientRef] = useState('');
  useEffect(() => {
    if (open) { setForm(BLANK()); setErr(''); setClientRef(`${Date.now()}-${Math.random().toString(36).slice(2, 8)}`); }
  }, [open]);
  const kinds = status?.kinds || [];
  const kind = kinds.find((k) => k.value === form.kind) || {};
  const oth = otherCv(cv);
  const exclude = useMemo(() => new Set(Object.values(status?.accounts || {}).flatMap((x) => Object.values(x || {})).filter(Boolean)), [status]);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const save = async () => {
    if (!form.source_account_code || !form.other_account_code) { setErr('Pilih akun di kedua CV.'); return; }
    if (!(Number(form.amount) > 0)) { setErr('Jumlah harus lebih dari 0.'); return; }
    if ((form.description || '').trim().length < 3) { setErr('Isi keterangan, mis. "talangan listrik Oktober".'); return; }
    setSaving(true); setErr('');
    try {
      const d = await apiPost('/rahaza/intercompany/transactions', { ...form, amount: Number(form.amount), client_ref: clientRef });
      toast.success(`${d.number} tersimpan · jurnal ${d.source_je_number} (${cvLabel(d.source_entity)}) dan ${d.other_je_number} (${cvLabel(d.other_entity)})`);
      onSaved();
      onClose();
    } catch (e) { setErr(e.message || 'Gagal menyimpan'); }
    finally { setSaving(false); }
  };
  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" testId="ic-txn-dialog"
      judul="Transaksi antar CV baru"
      keterangan={`Dicatat dari ${cvLabel(cv)}. Jurnal pasangan di ${cvLabel(oth)} dibuat otomatis memakai piutang/hutang antar CV.`}
      onSimpan={save} menyimpan={saving} galat={err} labelSimpan="Simpan & catat dua jurnal">
      <Isian label="Jenis">
        <SmartNativeSelect value={form.kind} onChange={(e) => set('kind', e.target.value)} className="w-full h-9" data-testid="ic-txn-kind">
          {kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </SmartNativeSelect>
      </Isian>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Jumlah (Rp)" wajib>
          <MoneyInput value={form.amount} onChange={(e) => set('amount', e.target.value)} data-testid="ic-txn-amount" />
        </Isian>
        <Isian label="Tanggal">
          <DatePicker id="ic-txn-date" value={form.date} onChange={(v) => set('date', v)} bolehKosong={false} testId="ic-txn-date" />
        </Isian>
      </div>
      <Isian label={`Akun ${cvLabel(cv)} (${kind.source_hint || 'akun asal'})`} wajib>
        <AccountSelect cv={cv} value={form.source_account_code} onChange={(v) => set('source_account_code', v)}
          exclude={exclude} testId="ic-txn-source-account" placeholder="— Pilih akun —" />
      </Isian>
      <Isian label={`Akun ${cvLabel(oth)} (${kind.other_hint || 'akun lawan'})`} wajib>
        <AccountSelect cv={oth} value={form.other_account_code} onChange={(v) => set('other_account_code', v)}
          exclude={exclude} testId="ic-txn-other-account" placeholder="— Pilih akun —" />
      </Isian>
      <Isian label="Keterangan" wajib htmlFor="ic-txn-desc">
        <GlassInput id="ic-txn-desc" value={form.description} onChange={(e) => set('description', e.target.value)}
          placeholder="mis. talangan listrik Oktober" data-testid="ic-txn-desc" />
      </Isian>
    </FormPopup>
  );
}

export default function IntercompanyTransactionsModule() {
  const cvCtx = useCv();
  const cv = cvCtx?.cv || CV_DA;
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dialog, setDialog] = useState(false);
  const [openId, setOpenId] = useState(null);
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [st, tx] = await Promise.all([apiGet('/rahaza/intercompany/status'), apiGet('/rahaza/intercompany/transactions')]);
      setStatus(st); setRows(tx.items || []);
    } catch (e) { setError(e.message || 'Gagal memuat'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const setup = async () => {
    try { await apiPost('/rahaza/intercompany/setup', {}); toast.success('Akun antar CV disiapkan'); load(); }
    catch (e) { toast.error(e.message || 'Gagal'); }
  };
  const voidTxn = async (t) => {
    const reason = await confirmDialog({
      title: `Batalkan ${t.number}?`, body: 'Dua jurnalnya (di CV Dewi Aditya dan CV Sukma) dibatalkan bersama.',
      confirmLabel: 'Batalkan transaksi', cancelLabel: 'Kembali', danger: true,
      input: { label: 'Alasan', placeholder: 'mis. salah input jumlah', minLength: 3 },
    });
    if (!reason) return;
    try { await apiPost(`/rahaza/intercompany/transactions/${t.id}/void`, { reason }); toast.success(`${t.number} dibatalkan`); load(); }
    catch (e) { toast.error(e.message || 'Gagal membatalkan'); }
  };
  const missing = status?.missing;
  return (
    <PageLayout
      testId="ic-txn-page"
      title="Transaksi antar CV"
      subtitle="Talangan, pinjaman, uang nyasar, dan pelunasan antar CV — diinput sekali, jurnal di dua buku."
      actions={<Button onClick={() => setDialog(true)} disabled={!!missing || !status} data-testid="ic-txn-new"><Plus className="w-4 h-4" />Transaksi baru</Button>}
      tools={<>
        <TombolUnduh namaBerkas="transaksi-antar-cv" namaLembar="Antar CV" baris={rows} testId="ic-txn-unduh"
          kolom={[
            { label: 'Nomor', nilai: (t) => t.number },
            { label: 'Tanggal', nilai: (t) => formatDateID(t.date) },
            { label: 'Jenis', nilai: (t) => (t.kind_label || t.kind || '').split(' — ')[0] },
            { label: 'Dari', nilai: (t) => cvLabel(t.source_entity) },
            { label: 'Ke', nilai: (t) => cvLabel(t.other_entity) },
            { label: 'Keterangan', nilai: (t) => t.description || '' },
            { label: 'Jumlah', nilai: (t) => Number(t.amount) || 0 },
            { label: 'Status', nilai: (t) => (t.status === 'voided' ? 'Dibatalkan' : 'Terjurnal') },
            { label: 'Jurnal CV asal', nilai: (t) => t.source_je_number || '' },
            { label: 'Jurnal CV lawan', nilai: (t) => t.other_je_number || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /></Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {missing && (
          <Notice tone="warning" icon={AlertCircle} testId="ic-missing"
            action={!cvCtx?.readOnly && <Button size="sm" variant="outline" onClick={setup} data-testid="ic-setup">Siapkan akun antar CV</Button>}>
            {missing}
          </Notice>
        )}
        {status && !missing && (
          <p className="text-sm text-muted-foreground" data-testid="ic-accounts">
            Piutang/hutang antar CV: CV Dewi Aditya {status.accounts?.DA?.ar} / {status.accounts?.DA?.ap} · CV Sukma {status.accounts?.SMU?.ar} / {status.accounts?.SMU?.ap}
            {status.vendor ? ` · tim jahit CV Sukma: ${status.vendor.name}` : ''}
          </p>
        )}
      </>}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-8"><Loader2 className="animate-spin text-muted-foreground" /></div>
        ) : rows.length === 0 ? (
          <EmptyState icon={ArrowRightLeft} title="Belum ada transaksi antar CV"
            description="Tekan “Transaksi baru” untuk mencatat talangan, pinjaman, uang nyasar, atau pelunasan." testId="ic-txn-empty" />
        ) : (
          <Table className="min-w-[760px] md:min-w-0">
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Nomor</TableHead>
                <TableHead>Tanggal</TableHead>
                <TableHead>Jenis</TableHead>
                <TableHead>Arah</TableHead>
                <TableHead>Keterangan</TableHead>
                <TableHead className="text-right">Jumlah</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((t) => {
                const open = openId === t.id;
                return (
                  <Fragment key={t.id}>
                    <TableRow data-testid={`ic-txn-row-${t.number}`}>
                      <TableCell><RowToggle open={open} onClick={() => setOpenId(open ? null : t.id)} testId={`ic-txn-toggle-${t.number}`} /></TableCell>
                      <TableCell className="whitespace-nowrap">{t.number}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateID(t.date)}</TableCell>
                      <TableCell>{(t.kind_label || t.kind).split(' — ')[0]}</TableCell>
                      <TableCell className="whitespace-nowrap">{cvLabel(t.source_entity)} → {cvLabel(t.other_entity)}</TableCell>
                      <TableCell className="min-w-[12rem]">{t.description}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(t.amount)}</TableCell>
                      <TableCell>{t.status === 'voided' ? <StatusBadge status="voided" label="Dibatalkan" tone="muted" /> : <StatusBadge status="posted" label="Terjurnal" tone="success" />}</TableCell>
                      <TableCell className="text-right">
                        {t.status !== 'voided' && (
                          <Button size="sm" variant="destructive" onClick={() => voidTxn(t)} data-testid={`ic-txn-void-${t.number}`}>Batalkan</Button>
                        )}
                      </TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={9} testId={`ic-txn-detail-${t.number}`}>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 text-sm whitespace-normal">
                          <p>{cvLabel(t.source_entity)}: jurnal <b>{t.source_je_number}</b> · {t.source_account_code} {t.source_account_name} ↔ {t.source_ic_account}</p>
                          <p>{cvLabel(t.other_entity)}: jurnal <b>{t.other_je_number}</b> · {t.other_account_code} {t.other_account_name} ↔ {t.other_ic_account}</p>
                        </div>
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      <TransactionDialog open={dialog} cv={cv} status={status} onClose={() => setDialog(false)} onSaved={load} />
    </PageLayout>
  );
}
