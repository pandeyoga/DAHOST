/**
 * Employee Travel Settlement Module
 * CV. Dewi Aditya — Employee Expense Management (EEM) Phase B
 *
 * Features:
 *  - Karyawan: buat settlement aktual setelah pulang dinas
 *  - Manager/HR: approve settlement
 *  - Finance: post GL + lihat outstanding advance monitoring
 *  - GL Reconciliation: Dr Beban Dinas / Cr Uang Muka / Dr-Cr Bank (selisih)
 *
 * 2026-11-05 (PANDUAN_UI G1/G6/G13, owner): cetakan PageLayout. Dulu kepala halaman berbeda dari layar lain —
 * dua kotak tanggal bawaan browser + "Unduh CSV" di dalam kotak di kanan atas, dan spanduk penjelasan panjang.
 * Kini periode = PeriodPicker di toolbar kiri (menyaring daftar DAN unduhan, tanggal dibuat — sama dengan
 * from_date/to_date unduhan), "Unduh CSV" di kanan, penjelasan satu baris. Rincian penyelesaian dan pilihan
 * perjalanan dibuka DI HALAMAN (DetailPanel), bukan popup; formulir penyelesaian baru tetap dialog.
 * 2026-11-08 (Standar UI/UX v2): rincian & pilih perjalanan = popup (tabel ui/table); form penyelesaian =
 * FormPopup panjang + DatePicker per nota; Setujui/Catat hijau, Tolak merah; semua tabel bisa diunduh Excel/CSV
 * (daftar penyelesaian, rincian biaya, uang muka belum selesai); warna teks token.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { isFinanceRole } from '../../lib/financeRoles'; // FIN-02
import {
  Plus, RefreshCw, FileText, CheckCircle, XCircle,
  Send, Banknote, Eye, Upload, Trash2, Search, MapPin,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { EmptyState, StatusBadge as AtomStatusBadge } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import CashAccountSelect, { usePaymentCashAccounts } from './SdmCashAccountSelect';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = formatRupiah;
const fmtDate = (s) => s ? new Date(s).toLocaleDateString('id-ID', { day:'2-digit', month:'short', year:'numeric' }) : '—';

const EXPENSE_CATEGORIES = [
  'Transportasi', 'Akomodasi', 'Konsumsi / Makan',
  'Representasi / Entertainment', 'Komunikasi', 'ATK / Perlengkapan',
  'Parkir / Tol', 'Lain-lain'
];

// PANDUAN_UI G8: status = StatusBadge bersama dengan nada token (dulu palet warna langsung)
const STATUS_CONFIG = {
  draft:     { label: 'Draf',                       tone: 'muted' },
  submitted: { label: 'Menunggu persetujuan',       tone: 'warning' },
  approved:  { label: 'Disetujui · siap dijurnal',  tone: 'info' },
  rejected:  { label: 'Ditolak',                    tone: 'danger' },
  posted:    { label: 'Terjurnal',                  tone: 'success' },
};

const STL_TYPE_CONFIG = {
  return:     { label: 'Kembalian',    color: 'text-[hsl(var(--success-text))]', note: 'Karyawan kembalikan sisa' },
  additional: { label: 'Kurang bayar', color: 'text-[hsl(var(--danger-text))]',  note: 'Perusahaan bayar tambahan' },
  exact:      { label: 'Tepat',        color: 'text-muted-foreground',          note: 'Uang muka dan biaya aktual sama' },
};

function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status];
  return <AtomStatusBadge status={status} label={c?.label || status} tone={c?.tone || 'default'} />;
}

function ReconciliationCard({ settlement }) {
  const advance = settlement.advance_received || 0;
  const actual  = settlement.total_actual || 0;
  const diff    = settlement.difference || 0;  // advance - actual
  const stlType = settlement.settlement_type || 'exact';
  const stlConf = STL_TYPE_CONFIG[stlType] || STL_TYPE_CONFIG.exact;

  return (
    <div className="space-y-2">
      <p className="text-sm font-semibold">Rekonsiliasi uang muka</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <div className="text-xs text-muted-foreground">Uang muka diterima</div>
          <div className="text-lg font-bold tabular-nums whitespace-nowrap">{fmt(advance)}</div>
          <div className="text-xs text-muted-foreground">Debet 1-1610</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Biaya aktual</div>
          <div className="text-lg font-bold tabular-nums whitespace-nowrap">{fmt(actual)}</div>
          <div className="text-xs text-muted-foreground">Kredit 6-3400</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Selisih</div>
          <div className={`text-lg font-bold tabular-nums whitespace-nowrap ${stlConf.color}`}>{fmt(Math.abs(diff))}</div>
          <div className={`text-xs font-medium ${stlConf.color}`}>{stlConf.label}</div>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {stlType === 'return' && <>Karyawan mengembalikan <b className="text-foreground">{fmt(Math.abs(diff))}</b> ke perusahaan (Dr Bank / Cr 1-1610).</>}
        {stlType === 'additional' && <>Perusahaan perlu membayar tambahan <b className="text-foreground">{fmt(Math.abs(diff))}</b> ke karyawan (Dr 6-3400 / Cr Bank).</>}
        {stlType === 'exact' && <>Uang muka tepat sama dengan biaya aktual — tidak ada selisih.</>}
      </p>
    </div>
  );
}

// 2026-11-02: baris bank pratinjau memakai rekening YANG DIPILIH (dulu teks tetap "1-1201",
// padahal backend menjurnal ke rekening settlement/pilihan — layar dan jurnal bisa berbeda).
function GLPreview({ settlement, bankAccount }) {
  const advance = settlement.advance_received || 0;
  const actual  = settlement.total_actual || 0;
  const diff    = Math.abs(settlement.difference || 0);
  const stlType = settlement.settlement_type || 'exact';
  const bankCode = bankAccount?.gl_account_code || '—';
  const bankName = bankAccount?.name || 'Bank (pilih rekening)';

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 space-y-2">
      <p className="text-sm font-medium text-foreground">Pratinjau jurnal</p>
      <div className="text-xs space-y-1 tabular-nums">
        {actual > 0 && (
          <div className="flex items-center gap-2">
            <span className="w-6 font-bold text-muted-foreground">Dr</span>
            <span className="w-20 text-muted-foreground">6-3400</span>
            <span className="flex-1">Biaya Perjalanan Dinas</span>
            <span className="font-bold whitespace-nowrap">{fmt(actual)}</span>
          </div>
        )}
        {advance > 0 && (
          <div className="flex items-center gap-2">
            <span className="w-6 font-bold text-muted-foreground">Cr</span>
            <span className="w-20 text-muted-foreground">1-1610</span>
            <span className="flex-1">Uang Muka Karyawan</span>
            <span className="font-bold whitespace-nowrap">{fmt(advance)}</span>
          </div>
        )}
        {stlType === 'return' && diff > 0 && (
          <div className="flex items-center gap-2">
            <span className="w-6 font-bold text-muted-foreground">Dr</span>
            <span className="w-20 text-muted-foreground" data-testid="gl-preview-bank-code">{bankCode}</span>
            <span className="flex-1">{bankName} (terima kembalian)</span>
            <span className="font-bold whitespace-nowrap">{fmt(diff)}</span>
          </div>
        )}
        {stlType === 'additional' && diff > 0 && (
          <div className="flex items-center gap-2">
            <span className="w-6 font-bold text-muted-foreground">Cr</span>
            <span className="w-20 text-muted-foreground" data-testid="gl-preview-bank-code">{bankCode}</span>
            <span className="flex-1">{bankName} (bayar tambahan)</span>
            <span className="font-bold whitespace-nowrap">{fmt(diff)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─ Settlement Form (untuk karyawan buat settlement baru) — formulir isian, tetap di dialog
function SettlementForm({ token, travel, onClose, onSaved }) {
  const [items, setItems] = useState([{ date: '', category: '', amount: '', notes: '', receipt_url: '' }]);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  // SESI #27 — kolom nomor mengikuti kebijakan Otomatis/Manual milik owner.
  const numPolicy = useDocNumberPolicy('employee_travel_settlements.settlement_number', token);
  const [stlNumber, setStlNumber] = useState('');

  const addItem = () => setItems(p => [...p, { date: '', category: '', amount: '', notes: '', receipt_url: '' }]);
  const removeItem = (i) => setItems(p => p.filter((_, idx) => idx !== i));
  const setItem = (i, k, v) => setItems(p => p.map((it, idx) => idx === i ? { ...it, [k]: v } : it));

  const handleReceipt = (i, file) => {
    if (!file || file.size > 5 * 1024 * 1024) { setError('Foto struk maksimal 5 MB'); return; }
    const r = new FileReader();
    r.onload = (e) => setItem(i, 'receipt_url', e.target.result);
    r.readAsDataURL(file);
  };

  const totalActual = items.reduce((s, it) => s + (parseFloat(it.amount) || 0), 0);
  const advance = travel?.cash_advance_paid || travel?.cash_advance_approved || 0;
  const diff = advance - totalActual;
  const stlType = diff > 0.01 ? 'return' : diff < -0.01 ? 'additional' : 'exact';

  const handleSave = async () => {
    const validItems = items.filter(it => it.date && it.category && parseFloat(it.amount) > 0);
    if (!validItems.length) { setError('Minimal 1 item dengan tanggal, kategori, dan nominal'); return; }
    setSaving(true); setError('');
    try {
      const r = await fetch(`${API}/api/hr/expenses/travel/${travel.id}/settlements`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          actual_items: validItems.map(it => ({ ...it, amount: parseFloat(it.amount) })),
          ...docNumberPayload(numPolicy, 'settlement_number', stlNumber),
          notes,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal');
      onSaved(d);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="settlement-form"
      judul="Penyelesaian perjalanan dinas" keterangan={`${travel.trip_number} · ${travel.destination || ''}`}
      onSimpan={handleSave} menyimpan={saving} galat={error} labelSimpan="Simpan draf">
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <div><dt className="text-xs text-muted-foreground">Perjalanan</dt><dd className="font-semibold whitespace-nowrap">{travel.trip_number}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Tujuan</dt><dd className="font-medium">{travel.destination}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Tanggal</dt><dd>{fmtDate(travel.start_date)} – {fmtDate(travel.end_date)}</dd></div>
        <div><dt className="text-xs text-muted-foreground">Uang muka diterima</dt><dd className="font-semibold tabular-nums">{fmt(advance)}</dd></div>
      </dl>

      <DocNumberField
        policy={numPolicy} value={stlNumber} onChange={setStlNumber}
        testId="settlement-docnum" label="Nomor Penyelesaian Dinas" />

      {/* Biaya aktual */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-sm font-medium">Biaya aktual<span className="ml-0.5 text-[hsl(var(--danger-text))]">*</span></p>
          <Button type="button" size="sm" variant="outline" onClick={addItem}><Plus className="w-3.5 h-3.5" />Tambah nota</Button>
        </div>
        <div className="space-y-3">
          {items.map((it, i) => (
            <div key={i} className="rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Isian label="Tanggal">
                  <DatePicker value={it.date} onChange={v => setItem(i, 'date', v)} testId={`settlement-item-date-${i}`} />
                </Isian>
                <Isian label="Kategori">
                  <SmartNativeSelect value={it.category} onChange={e => setItem(i, 'category', e.target.value)} searchable={false}
                    className="h-9 w-full" aria-label={`Kategori nota ${i + 1}`} data-testid={`settlement-item-category-${i}`}>
                    <option value="">Pilih</option>
                    {EXPENSE_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </SmartNativeSelect>
                </Isian>
                <Isian label="Nominal (Rp)">
                  <MoneyInput placeholder="0" value={it.amount} onChange={e => setItem(i,'amount',e.target.value)} />
                </Isian>
                <Isian label="Keterangan">
                  <Input placeholder="opsional" value={it.notes} onChange={e => setItem(i,'notes',e.target.value)} />
                </Isian>
              </div>
              <div className="flex items-center gap-3">
                <label className="text-sm text-muted-foreground flex items-center gap-1.5 cursor-pointer">
                  <Upload className="w-4 h-4" />Foto struk
                  <input type="file" accept="image/*" className="hidden" onChange={e => handleReceipt(i, e.target.files[0])} />
                </label>
                {it.receipt_url && <span className="text-xs text-[hsl(var(--success-text))]">Struk terunggah</span>}
                {items.length > 1 && (
                  <Button type="button" size="icon-sm" variant="ghost" className="ml-auto text-[hsl(var(--danger-text))]" onClick={() => removeItem(i)}
                    title="Hapus baris" aria-label="Hapus baris">
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Pratinjau rekonsiliasi */}
      <div className="space-y-2">
        <p className="text-sm font-medium">Pratinjau rekonsiliasi</p>
        <div className="grid grid-cols-3 gap-2 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">Uang muka</div>
            <div className="font-semibold tabular-nums whitespace-nowrap">{fmt(advance)}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Biaya aktual</div>
            <div className="font-semibold tabular-nums whitespace-nowrap">{fmt(totalActual)}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Selisih</div>
            <div className={`font-semibold tabular-nums whitespace-nowrap ${STL_TYPE_CONFIG[stlType].color}`}>{fmt(Math.abs(diff))}</div>
            <div className={`text-xs ${STL_TYPE_CONFIG[stlType].color}`}>
              {stlType === 'return' ? 'Dikembalikan karyawan' : stlType === 'additional' ? 'Diklaim karyawan' : 'Tepat'}
            </div>
          </div>
        </div>
      </div>

      <Isian label="Catatan">
        <Textarea placeholder="Keterangan tambahan (opsional)" value={notes} onChange={e => setNotes(e.target.value)} rows={2} />
      </Isian>
    </FormPopup>
  );
}

// ─ Rincian + tindakan penyelesaian — DI HALAMAN (DetailPanel), dulu popup
function SettlementDetail({ stl, token, onClose, onRefresh, role }) {
  const [loading, setLoading] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [note, setNote] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const isApprover = ['superadmin','admin','owner','hr','manager','finance'].includes(role?.toLowerCase());
  const isFinance  = isFinanceRole(role); // FIN-02
  // 2026-11-02: rekening kas/bank untuk baris selisih dipilih pengguna & DIKIRIM saat posting
  // (`bank_account_id`), bawaan = rekening yang tercatat di settlement bila masih aktif.
  const { accounts: cashAccounts, loaded: cashLoaded } = usePaymentCashAccounts(token, 'DA');  // Tahap 8: dinas staf DA
  const [bankAccountId, setBankAccountId] = useState('');
  useEffect(() => {
    if (bankAccountId || !cashAccounts.length) return;
    if (stl.bank_account_id && cashAccounts.some(a => a.id === stl.bank_account_id)) setBankAccountId(stl.bank_account_id);
  }, [cashAccounts, stl.bank_account_id, bankAccountId]);
  // Settlement yang sudah diposting: tampilkan akun bank dari baris jurnal yang benar-benar dibuat.
  const postedBankLine = stl.status === 'posted'
    ? (stl.gl_je_lines || []).find(l => !['6-3400', '1-1610'].includes(l.account_code)) : null;
  const chosenBank = cashAccounts.find(a => a.id === bankAccountId)
    || (postedBankLine ? { gl_account_code: postedBankLine.account_code, name: 'Bank' } : null);
  const needsBank = (stl.settlement_type === 'return' || stl.settlement_type === 'additional')
    && Math.abs(stl.difference || 0) > 0.01;

  const doAction = async (endpoint, body = {}) => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/hr/expenses/settlements/${stl.id}/${endpoint}`, {
        method: 'POST', headers, body: JSON.stringify(body),
      });
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Gagal'); }
      onRefresh(); onClose();
    } catch (e) { toast.error(e.message); }
    finally { setLoading(false); }
  };

  const canApprove = isApprover && stl.status === 'submitted';
  return (
    <DetailPanel
      title={`${stl.settlement_number || 'Penyelesaian'} — ${stl.destination || ''}`}
      description={`${stl.employee_name || '—'} · perjalanan ${stl.trip_number || '—'}`}
      onClose={onClose}
      testId="settlement-detail-panel"
      actions={<>
        {stl.status === 'draft' && (
          <Button onClick={() => doAction('submit')} disabled={loading}>
            <Send className="w-3.5 h-3.5" />Ajukan
          </Button>
        )}
        {canApprove && !showReject && (
          <>
            <Button variant="destructive" onClick={() => setShowReject(true)} disabled={loading}>
              <XCircle className="w-3.5 h-3.5" />Tolak
            </Button>
            <Button variant="success" onClick={() => doAction('approve', { note })} disabled={loading}>
              <CheckCircle className="w-3.5 h-3.5" />Setujui
            </Button>
          </>
        )}
        {isFinance && stl.status === 'approved' && (
          <Button variant="success"
            onClick={() => doAction('post', { bank_account_id: bankAccountId })}
            disabled={loading || (needsBank && !bankAccountId)}
            title={needsBank && !bankAccountId ? 'Pilih rekening kas/bank untuk selisih dulu' : undefined}
            data-testid="stl-post-gl-btn">
            <Banknote className="w-3.5 h-3.5" />Catat ke jurnal
          </Button>
        )}
      </>}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div><p className="text-xs text-muted-foreground">Status</p><StatusBadge status={stl.status} /></div>
          <div><p className="text-xs text-muted-foreground">Karyawan</p><p className="font-medium">{stl.employee_name}</p></div>
          <div><p className="text-xs text-muted-foreground">Perjalanan</p><p className="whitespace-nowrap">{stl.trip_number}</p></div>
          <div><p className="text-xs text-muted-foreground">Tujuan</p><p className="font-semibold">{stl.destination}</p></div>
        </div>

        {canApprove && !showReject && (
          <Input placeholder="Catatan persetujuan (opsional)" className="text-sm max-w-md" value={note} onChange={e => setNote(e.target.value)} />
        )}

        {/* Tolak */}
        {showReject && (
          <div className="space-y-2 max-w-xl">
            <Textarea placeholder="Alasan penolakan" value={rejectReason} onChange={e => setRejectReason(e.target.value)} rows={3} />
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setShowReject(false)}>Batal</Button>
              <Button variant="destructive" size="sm"
                disabled={!rejectReason.trim() || loading}
                onClick={() => doAction('reject', { reason: rejectReason })}>
                Konfirmasi tolak
              </Button>
            </div>
          </div>
        )}

        <ReconciliationCard settlement={stl} />

        {/* Rekening selisih + pratinjau jurnal (hanya Keuangan) */}
        {isFinance && stl.status === 'approved' && needsBank && (
          <div className="space-y-1 max-w-md">
            <p className="text-sm font-medium text-foreground">Rekening kas/bank untuk selisih<span className="ml-0.5 text-[hsl(var(--danger-text))]">*</span></p>
            <CashAccountSelect accounts={cashAccounts} loaded={cashLoaded} value={bankAccountId}
              onChange={setBankAccountId} valueKey="id" testId="stl-post-bank-account" />
          </div>
        )}
        {isFinance && <GLPreview settlement={stl} bankAccount={chosenBank} />}

        {/* Biaya aktual */}
        {(stl.actual_items || []).length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">Rincian biaya aktual</p>
              <TombolUnduh namaBerkas={`rincian-biaya-${stl.settlement_number || 'dinas'}`} namaLembar="Biaya aktual" baris={stl.actual_items || []} testId="settlement-items-unduh"
                kolom={[
                  { label: 'Tanggal', nilai: (it) => fmtDate(it.date) },
                  { label: 'Kategori', nilai: (it) => it.category || '' },
                  { label: 'Nominal', nilai: (it) => Number(it.amount) || 0 },
                  { label: 'Keterangan', nilai: (it) => it.notes || '' },
                  { label: 'Struk', nilai: (it) => (it.receipt_url ? 'Ada' : 'Tidak ada') },
                ]} />
            </div>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Tanggal</TableHead><TableHead>Kategori</TableHead>
                <TableHead className="text-right">Nominal</TableHead><TableHead>Struk</TableHead>
              </TableRow></TableHeader>
              <TableBody>{(stl.actual_items || []).map((it, i) => (
                <TableRow key={i}>
                  <TableCell className="whitespace-nowrap">{fmtDate(it.date)}</TableCell>
                  <TableCell>{it.category}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap font-medium">{fmt(it.amount)}</TableCell>
                  <TableCell>
                    {it.receipt_url ? <a href={it.receipt_url} target="_blank" rel="noreferrer" className="text-[hsl(var(--primary))] hover:underline">Lihat</a> : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </div>
        )}
        {/* Jurnal bila sudah diposting */}
        {stl.gl_je_number && (
          <p className="text-sm text-muted-foreground">
            Jurnal <strong className="text-foreground whitespace-nowrap">{stl.gl_je_number}</strong>
            {' · '}dicatat oleh {stl.posted_by_name} · {fmtDate(stl.posted_at)}
          </p>
        )}

        {/* Alasan ditolak */}
        {stl.reject_reason && (
          <div className="text-sm">
            <p className="font-medium text-[hsl(var(--danger-text))]">Alasan ditolak</p>
            <p className="text-foreground">{stl.reject_reason}</p>
          </div>
        )}
      </div>
    </DetailPanel>
  );
}

// ─ Uang muka yang belum diselesaikan (Keuangan)
function OutstandingAdvancePanel({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const headers = { Authorization: `Bearer ${token}` };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/hr/expenses/outstanding-advances`, { headers });
      setData(await r.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return (
    <div className="flex items-center justify-center h-48">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[hsl(var(--primary))]" />
    </div>
  );
  if (!data || data.total === 0) return (
    <GlassCard className="p-0 overflow-hidden">
      <EmptyState icon={CheckCircle} title="Tidak ada uang muka yang belum diselesaikan"
        description="Semua uang muka perjalanan dinas sudah diselesaikan." />
    </GlassCard>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {data.total} uang muka belum diselesaikan · total <strong className="text-[hsl(var(--warning-text))] tabular-nums">{fmt(data.total_outstanding)}</strong> · akun 1-1610 Uang Muka Karyawan
        </p>
        <TombolUnduh namaBerkas="uang-muka-dinas-belum-selesai" namaLembar="Uang muka dinas" baris={data.items || []} testId="outstanding-unduh"
          kolom={[
            { label: 'Perjalanan', nilai: (x) => x.trip_number },
            { label: 'Karyawan', nilai: (x) => x.employee_name },
            { label: 'Departemen', nilai: (x) => x.employee_dept || '' },
            { label: 'Tujuan', nilai: (x) => x.destination || '' },
            { label: 'Tanggal kembali', nilai: (x) => fmtDate(x.end_date) },
            { label: 'Uang muka', nilai: (x) => Number(x.cash_advance_paid) || 0 },
            { label: 'Hari belum selesai', nilai: (x) => (x.days_since_return ?? '') },
            { label: 'Status penyelesaian', nilai: (x) => (x.pending_settlement ? `${x.pending_settlement.settlement_number}: ${STATUS_CONFIG[x.pending_settlement.status]?.label || x.pending_settlement.status}` : 'Belum ada penyelesaian') },
          ]} />
      </div>
      <GlassCard className="p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <Table className="w-full text-sm">
            <TableHeader>
              <TableRow>
                <TableHead className="text-left p-3 font-medium">Perjalanan / karyawan</TableHead>
                <TableHead className="text-left p-3 font-medium">Tujuan</TableHead>
                <TableHead className="text-left p-3 font-medium">Tanggal kembali</TableHead>
                <TableHead className="text-right p-3 font-medium">Uang muka</TableHead>
                <TableHead className="text-right p-3 font-medium">Hari belum selesai</TableHead>
                <TableHead className="text-left p-3 font-medium">Status penyelesaian</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data.items || []).map(item => {
                const daysOverdue = item.days_since_return;
                const isOverdue = daysOverdue !== null && daysOverdue > 7;
                return (
                  <TableRow key={item.id} className={`border-t ${ isOverdue ? 'bg-[hsl(var(--destructive)/0.06)]' : '' }`}>
                    <TableCell className="p-3">
                      <div className="text-xs text-muted-foreground whitespace-nowrap">{item.trip_number}</div>
                      <div className="font-medium">{item.employee_name}</div>
                      <div className="text-xs text-muted-foreground">{item.employee_dept}</div>
                    </TableCell>
                    <TableCell className="p-3">{item.destination}</TableCell>
                    <TableCell className="p-3 whitespace-nowrap">{fmtDate(item.end_date)}</TableCell>
                    <TableCell className="p-3 text-right tabular-nums whitespace-nowrap font-bold">{fmt(item.cash_advance_paid)}</TableCell>
                    <TableCell className="p-3 text-right tabular-nums whitespace-nowrap">
                      {daysOverdue !== null ? (
                        <span className={`font-bold ${ isOverdue ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--warning-text))]' }`}>
                          {daysOverdue} hari
                        </span>
                      ) : '—'}
                    </TableCell>
                    <TableCell className="p-3">
                      {item.pending_settlement ? (
                        <AtomStatusBadge status={item.pending_settlement.status} tone="warning"
                          label={`${item.pending_settlement.settlement_number}: ${STATUS_CONFIG[item.pending_settlement.status]?.label || item.pending_settlement.status}`} />
                      ) : (
                        <AtomStatusBadge status="none" tone="danger" label="Belum ada penyelesaian" />
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
            <TableFooter className="border-t">
              <TableRow>
                <TableCell colSpan={3} className="p-3 text-sm font-bold">Total sisa (1-1610)</TableCell>
                <TableCell className="p-3 text-right tabular-nums whitespace-nowrap font-bold text-[hsl(var(--warning-text))]">{fmt(data.total_outstanding)}</TableCell>
                <TableCell colSpan={2} />
              </TableRow>
            </TableFooter>
          </Table>
        </div>
      </GlassCard>
    </div>
  );
}

// ── Main Module ────────────────────────────────────────────────────────────────

export default function EmployeeTravelSettlementModule({ token, user, defaultTab = 'my' }) {
  const [settlements, setSettlements] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState(() => {   // my | queue | outstanding
    const r = (user?.role || '').toLowerCase();
    const canQueue = isFinanceRole(r) || ['superadmin', 'admin', 'owner', 'hr', 'manager', 'finance'].includes(r);
    return defaultTab === 'queue' && !canQueue ? 'my' : defaultTab;
  });
  const [showCreate, setShowCreate] = useState(false);
  const [selectedTravel, setSelectedTravel] = useState(null); // travel request for new settlement
  const [selected, setSelected] = useState(null);              // settlement detail
  const [myTrips, setMyTrips] = useState([]);  // eligible trips to settle
  const [reloadTick, setReloadTick] = useState(0); // muat ulang panel uang muka

  // Phase 4: Bulk selection & Export
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkLoading, setBulkLoading] = useState(false);
  // 2026-11-05: rentang unduhan (from_date/to_date) = PeriodPicker; bawaan 12 bulan terakhir (dulu dua kotak
  // tanggal kosong = semua). Rentang yang sama menyaring daftar menurut tanggal dibuat, sehingga yang terunduh
  // = yang terlihat.
  const [period, setPeriod] = useState(() => periodFromPreset('12m'));

  const role = user?.role || '';
  const isFinance = isFinanceRole(role); // FIN-02
  const isApprover = ['superadmin','admin','owner','hr','manager','finance'].includes(role.toLowerCase());
  const headers = { Authorization: `Bearer ${token}` };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('status', filter);
      if (search) params.set('search', search);
      if (activeTab === 'my') params.set('employee_id', user?.id || '');

      const [stlR, sumR] = await Promise.all([
        fetch(`${API}/api/hr/expenses/settlements?${params}`, { headers }).then(r => r.json()),
        fetch(`${API}/api/hr/expenses/settlement-summary`, { headers }).then(r => r.json()),
      ]);
      setSettlements(Array.isArray(stlR.items) ? stlR.items : []);
      setSummary(sumR);

      // Fetch eligible trips (advance_paid / on_trip) for creating new settlement
      const trR = await fetch(
        `${API}/api/hr/expenses/travel?status=advance_paid,on_trip,approved&employee_id=${user?.id || ''}`,
        { headers }
      ).then(r => r.json());
      setMyTrips(Array.isArray(trR.items) ? trR.items : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [token, filter, search, activeTab, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchData(); }, [fetchData]);
  const refresh = () => { setReloadTick((t) => t + 1); fetchData(); };

  // Phase 4: Bulk approve
  const handleBulkApprove = async () => {
    if (!selectedIds.length) {
      toast.error('Pilih minimal 1 penyelesaian untuk disetujui');
      return;
    }

    if (!(await confirmDialog(`Setujui ${selectedIds.length} penyelesaian?`))) return;

    setBulkLoading(true);
    try {
      const res = await fetch(`${API}/api/hr/expenses/settlements/bulk-approve`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          settlement_ids: selectedIds,
          approval_note: 'Bulk approved from UI'
        })
      });

      const data = await res.json();

      if (res.ok) {
        toast.success(`${data.success_count} penyelesaian disetujui`);
        if (data.failed_count > 0) {
          toast.warning(`${data.failed_count} penyelesaian gagal disetujui.`);
          console.warn('Failed items:', data.results.failed);
        }
        setSelectedIds([]);
        fetchData();
      } else {
        toast.error(data.detail || 'Gagal menyetujui sekaligus');
      }
    } catch (err) {
      console.error('Bulk approve error:', err);
      toast.error('Terjadi kesalahan saat menyetujui sekaligus');
    } finally {
      setBulkLoading(false);
    }
  };

  // Phase 4: Bulk post GL (Finance only)
  const handleBulkPost = async () => {
    if (!selectedIds.length) {
      toast.error('Pilih minimal 1 penyelesaian untuk dicatat ke jurnal');
      return;
    }

    if (!(await confirmDialog(`Catat ${selectedIds.length} penyelesaian ke jurnal? Jurnal dibuat untuk setiap penyelesaian.`))) return;

    setBulkLoading(true);
    try {
      const res = await fetch(`${API}/api/hr/expenses/settlements/bulk-post`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ settlement_ids: selectedIds })
      });

      const data = await res.json();

      if (res.ok) {
        toast.success(`${data.success_count} penyelesaian tercatat ke jurnal`);
        if (data.failed_count > 0) {
          toast.warning(`${data.failed_count} penyelesaian gagal dijurnal.`);
          console.warn('Failed items:', data.results.failed);
        }
        setSelectedIds([]);
        fetchData();
      } else {
        toast.error(data.detail || 'Gagal mencatat ke jurnal sekaligus');
      }
    } catch (err) {
      console.error('Bulk post error:', err);
      toast.error('Terjadi kesalahan saat mencatat ke jurnal');
    } finally {
      setBulkLoading(false);
    }
  };

  // Toggle selection
  const toggleSelect = (id) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const tabs = [
    { id: 'my',          label: 'Penyelesaian saya' },
    // 2026-11-04: peran keuangan kanonik ('accounting'/'staff_keuangan') juga melihat antrean posting
    ...((isApprover || isFinance) ? [{ id: 'queue', label: 'Antrean', count: summary?.pending_post || 0 }] : []),
    ...(isFinance  ? [{ id: 'outstanding', label: 'Uang muka belum selesai', count: summary?.outstanding_advances_count || 0 }] : []),
  ];

  const filteredItems = useMemo(() => settlements.filter(s => {
    if (filter !== 'all' && s.status !== filter) return false;
    if (search && !s.settlement_number?.toLowerCase().includes(search.toLowerCase()) &&
        !s.trip_number?.toLowerCase().includes(search.toLowerCase()) &&
        !s.destination?.toLowerCase().includes(search.toLowerCase())) return false;
    const created = String(s.created_at || '').slice(0, 10);
    if (created && (created < period.from || created > period.to)) return false;
    return true;
  }), [settlements, filter, search, period.from, period.to]);

  const toggleSelectAll = () => {
    const eligibleIds = filteredItems.map(s => s.id);
    setSelectedIds(prev =>
      prev.length === eligibleIds.length ? [] : eligibleIds
    );
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(filteredItems, 10);
  const listTab = activeTab !== 'outstanding';
  const canSelect = isApprover || isFinance;
  const openDetail = (s) => { setShowCreate(false); setSelected((cur) => (cur?.id === s.id ? null : s)); };

  return (
    <PageLayout
      testId="travel-settlement-page"
      title="Perjalanan dinas"
      subtitle="Biaya aktual perjalanan dinas dibandingkan uang mukanya, lalu dijurnal."
      actions={myTrips.length > 0 && (
        <Button onClick={() => { setSelected(null); setShowCreate(true); }} data-testid="btn-new-settlement">
          <Plus className="w-4 h-4" />Penyelesaian baru
        </Button>
      )}
      filters={<>
        {/* 2026-11-04: 4 kartu hitungan dilepas — jumlah antrean & uang muka ada di pil */}
        <FilterChips value={activeTab} onChange={setActiveTab} testId="travel-tab" ariaLabel="Tampilan" hideWhenEmpty={false}
          options={tabs.map((t) => ({ key: t.id, label: t.label, count: t.count }))} />
        {listTab && (
          <>
            <SmartNativeSelect value={filter} onChange={(e) => setFilter(e.target.value)} searchable={false}
              className="h-9 w-48" aria-label="Status" data-testid="travel-status-filter">
              <option value="all">Semua status</option>
              <option value="draft">Draf</option>
              <option value="submitted">Menunggu persetujuan</option>
              <option value="approved">Disetujui</option>
              <option value="posted">Terjurnal</option>
              <option value="rejected">Ditolak</option>
            </SmartNativeSelect>
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <GlassInput placeholder="Cari nomor / tujuan…" aria-label="Cari" value={search} onChange={e => setSearch(e.target.value)}
                className="h-9 pl-9" data-testid="travel-search" />
            </div>
            <PeriodPicker value={period} onChange={setPeriod} testId="travel-period" />
          </>
        )}
      </>}
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={refresh}>
          <RefreshCw className="w-4 h-4" />
        </Button>
        {listTab && (
          <TombolUnduh namaBerkas={`penyelesaian-dinas-${period.from}-${period.to}`} namaLembar="Penyelesaian dinas" baris={filteredItems} testId="travel-export-csv"
            kolom={[
              { label: 'Nomor', nilai: (x) => x.settlement_number || '' },
              { label: 'Perjalanan', nilai: (x) => x.trip_number || '' },
              { label: 'Karyawan', nilai: (x) => x.employee_name || '' },
              { label: 'Departemen', nilai: (x) => x.employee_dept || '' },
              { label: 'Tujuan', nilai: (x) => x.destination || '' },
              { label: 'Berangkat', nilai: (x) => fmtDate(x.start_date) },
              { label: 'Kembali', nilai: (x) => fmtDate(x.end_date) },
              { label: 'Biaya aktual', nilai: (x) => Number(x.total_actual) || 0 },
              { label: 'Uang muka', nilai: (x) => Number(x.advance_received) || 0 },
              { label: 'Selisih', nilai: (x) => Number(x.difference) || 0 },
              { label: 'Jenis selisih', nilai: (x) => (STL_TYPE_CONFIG[x.settlement_type] || STL_TYPE_CONFIG.exact).label },
              { label: 'Status', nilai: (x) => STATUS_CONFIG[x.status]?.label || x.status },
              { label: 'Jurnal', nilai: (x) => x.gl_je_number || '' },
            ]} />
        )}
      </>}
      summary={
        /* RC-IA-2a — klarifikasi pintu bersama HR/Keuangan (dulu spanduk dua kalimat) */
        <p className="text-sm text-muted-foreground" data-testid="travel-shared-note">
          Dipakai bersama SDM &amp; Keuangan: SDM menyetujui, Keuangan menyelesaikan dan menjurnal.
        </p>
      }
      detail={<>
        {showCreate && !selectedTravel && (
          <DetailPanel title="Pilih perjalanan dinas" description="Perjalanan dinas yang uang mukanya belum diselesaikan."
            onClose={() => setShowCreate(false)} testId="settlement-trip-picker">
            {myTrips.length === 0 ? (
              <EmptyState icon={MapPin} title="Tidak ada perjalanan dinas yang bisa diselesaikan"
                description="Perjalanan dinas muncul di sini setelah disetujui atau uang mukanya dibayar." />
            ) : (
              <Table>
                <TableHeader><TableRow>
                  <TableHead>Nomor</TableHead><TableHead>Tujuan</TableHead>
                  <TableHead>Tanggal</TableHead><TableHead className="text-right">Uang muka</TableHead><TableHead />
                </TableRow></TableHeader>
                <TableBody>{myTrips.map(tr => (
                  <TableRow key={tr.id} className="cursor-pointer" onClick={() => setSelectedTravel(tr)}
                    data-testid={`settlement-trip-${tr.id}`}>
                    <TableCell className="whitespace-nowrap">{tr.trip_number}</TableCell>
                    <TableCell className="font-medium">{tr.destination}</TableCell>
                    <TableCell className="whitespace-nowrap">{fmtDate(tr.start_date)} – {fmtDate(tr.end_date)}</TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap font-semibold">{fmt(tr.cash_advance_paid || tr.cash_advance_approved || 0)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setSelectedTravel(tr); }}>Pilih</Button>
                    </TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            )}
          </DetailPanel>
        )}
        {selected && (
          <SettlementDetail
            key={selected.id}
            stl={selected}
            token={token}
            role={role}
            onClose={() => setSelected(null)}
            onRefresh={fetchData}
          />
        )}
      </>}
    >
      {activeTab === 'outstanding' ? (
        <OutstandingAdvancePanel key={reloadTick} token={token} />
      ) : (
        <GlassCard className="p-0 overflow-hidden">
          {/* Phase 4: aksi untuk baris terpilih — di kartu tabel, bukan kartu terpisah */}
          {selectedIds.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border-b border-[var(--glass-border)] bg-[hsl(var(--primary)/0.08)]">
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium">{selectedIds.length} penyelesaian dipilih</span>
                <Button variant="outline" size="sm" onClick={() => setSelectedIds([])}>Batalkan pilihan</Button>
              </div>
              <div className="flex items-center gap-2">
                {isApprover && (
                  <Button variant="success" size="sm" onClick={handleBulkApprove} disabled={bulkLoading} data-testid="bulk-approve-btn">
                    <CheckCircle className="w-3.5 h-3.5" />Setujui yang dipilih
                  </Button>
                )}
                {isFinance && (
                  <Button variant="outline" size="sm" onClick={handleBulkPost} disabled={bulkLoading} data-testid="bulk-post-btn">
                    <Banknote className="w-3.5 h-3.5" />Jurnalkan yang dipilih
                  </Button>
                )}
              </div>
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center h-48">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[hsl(var(--primary))]" />
            </div>
          ) : filteredItems.length === 0 ? (
            settlements.length === 0 ? (
              <EmptyState icon={FileText} title="Belum ada penyelesaian perjalanan dinas"
                description={myTrips.length > 0
                  ? 'Tekan "Penyelesaian baru" untuk mencocokkan biaya aktual dengan uang muka.'
                  : 'Penyelesaian dibuat setelah karyawan pulang dinas.'} />
            ) : (
              <EmptyState icon={Search} title="Tidak ada penyelesaian yang cocok"
                description="Ubah periode, status, atau pencarian." />
            )
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table className="w-full text-sm">
                  <TableHeader>
                    <TableRow>
                      {canSelect && (
                        <TableHead className="text-left p-3 w-12">
                          <Checkbox
                            checked={selectedIds.length === filteredItems.length && filteredItems.length > 0}
                            onCheckedChange={toggleSelectAll}
                            data-testid="select-all-checkbox"
                          />
                        </TableHead>
                      )}
                      <TableHead className="text-left p-3 font-medium">Nomor / perjalanan</TableHead>
                      <TableHead className="text-left p-3 font-medium">Karyawan</TableHead>
                      <TableHead className="text-left p-3 font-medium">Tujuan</TableHead>
                      <TableHead className="text-right p-3 font-medium">Biaya aktual</TableHead>
                      <TableHead className="text-right p-3 font-medium">Uang muka</TableHead>
                      <TableHead className="text-right p-3 font-medium">Selisih</TableHead>
                      <TableHead className="text-left p-3 font-medium">Status</TableHead>
                      <TableHead className="p-3" aria-label="Rincian" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {paged.map(s => {
                      const diff = s.difference || 0;
                      const stlType = s.settlement_type || 'exact';
                      const open = selected?.id === s.id;
                      return (
                        <TableRow key={s.id} className={`border-t hover:bg-muted/30 transition-colors ${open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}>
                          {canSelect && (
                            <TableCell className="p-3">
                              <Checkbox
                                checked={selectedIds.includes(s.id)}
                                onCheckedChange={() => toggleSelect(s.id)}
                                data-testid={`select-checkbox-${s.id}`}
                              />
                            </TableCell>
                          )}
                          <TableCell className="p-3 whitespace-nowrap">
                            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => openDetail(s)}
                              data-testid={`settlement-open-${s.id}`}>
                              {s.settlement_number}
                            </Button>
                            <div className="text-xs text-muted-foreground">{s.trip_number}</div>
                          </TableCell>
                          <TableCell className="p-3">
                            <div className="font-medium">{s.employee_name}</div>
                            <div className="text-xs text-muted-foreground">{s.employee_dept}</div>
                          </TableCell>
                          <TableCell className="p-3">
                            <div>{s.destination}</div>
                            <div className="text-xs text-muted-foreground whitespace-nowrap">{fmtDate(s.start_date)} – {fmtDate(s.end_date)}</div>
                          </TableCell>
                          <TableCell className="p-3 text-right tabular-nums whitespace-nowrap font-bold">{fmt(s.total_actual)}</TableCell>
                          <TableCell className="p-3 text-right tabular-nums whitespace-nowrap">{fmt(s.advance_received)}</TableCell>
                          <TableCell className="p-3 text-right tabular-nums whitespace-nowrap">
                            <span className={`font-semibold ${(STL_TYPE_CONFIG[stlType] || STL_TYPE_CONFIG.exact).color}`}
                              title={(STL_TYPE_CONFIG[stlType] || STL_TYPE_CONFIG.exact).label}>
                              {stlType === 'return' ? '↓' : stlType === 'additional' ? '↑' : '='} {fmt(Math.abs(diff))}
                            </span>
                          </TableCell>
                          <TableCell className="p-3"><StatusBadge status={s.status} /></TableCell>
                          <TableCell className="p-3 text-right">
                            <Button size="icon-sm" variant="ghost" onClick={() => openDetail(s)}
                              title={open ? 'Tutup rincian' : 'Lihat rincian'} aria-label={open ? 'Tutup rincian' : 'Lihat rincian'} aria-expanded={open}>
                              <Eye className="w-3.5 h-3.5" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              {totalPages > 1 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} className="px-3" />}
            </>
          )}
        </GlassCard>
      )}

      {/* Formulir penyelesaian baru — popup form standar (FormPopup panjang) */}
      {selectedTravel && (
        <SettlementForm
          token={token}
          travel={selectedTravel}
          onClose={() => { setSelectedTravel(null); setShowCreate(false); }}
          onSaved={(d) => { setSelectedTravel(null); setShowCreate(false); fetchData(); setSelected(d); }}
        />
      )}
    </PageLayout>
  );
}
