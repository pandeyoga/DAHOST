import { useState, useEffect, useCallback } from 'react';
import { Plus, RefreshCw, Edit2, Trash2, FileText, RotateCcw, BookCheck, MoreHorizontal } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Textarea } from '@/components/ui/textarea';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, StatusBadge, EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { useToast } from '@/hooks/use-toast';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { monthOptions } from './finance/PeriodPicker';
import { cvAccountParam, useCv } from '@/lib/entitas';

// 24 bulan terakhir, terbaru di atas
const MONTH_OPTIONS = monthOptions(24);
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const periodLabel = (code) => { const [y, m] = String(code || '').split('-'); return BULAN[Number(m) - 1] ? `${BULAN[Number(m) - 1]} ${y}` : (code || '—'); };
const PAGE_SIZE = 25;

const fmt = formatRupiah;

// 2026-11-07 (audit form Tahap 5): jenis, status, dan nama kolom SAMA dengan server (routes/rahaza_accruals.py).
// Dulu layar mengirim `type: income|expense` + `account_id` yang TIDAK dibaca server → setiap akrual tersimpan
// berjenis "other" tanpa akun pilihan; status server (draft/posted/reversed) dibaca sebagai "active", sehingga
// akrual baru tampil "Dibalik" tanpa tombol apa pun dan tidak pernah bisa diposting dari layar ini.
export const ACCRUAL_TYPES = [
  { value: 'utility', label: 'Listrik, air & telepon' },
  { value: 'rent', label: 'Sewa' },
  { value: 'professional_fees', label: 'Jasa profesional' },
  { value: 'interest_payable', label: 'Bunga hutang' },
  { value: 'salary_bonus', label: 'Bonus karyawan' },
  { value: 'tax_payable', label: 'Pajak terutang' },
  { value: 'other', label: 'Lain-lain' },
];
const typeLabel = (v) => ACCRUAL_TYPES.find((t) => t.value === v)?.label || 'Lain-lain';
const STATUS_META = {
  draft: { label: 'Draf', tone: 'warning' },
  posted: { label: 'Terjurnal', tone: 'info' },
  reversed: { label: 'Dibalik', tone: 'muted' },
};
// akun beban (debit) & akun akrual/hutang (kredit) — jurnal akrual: Dr beban / Cr beban yang masih harus dibayar
const EXPENSE_TYPES = ['EXPENSE', 'COGS', 'OTHER_EXPENSE'];
const ACCRUED_TYPES = ['LIABILITY'];

/** Isi kiriman simpan — hanya kolom yang dibaca server. */
export function accrualPayload(s) {
  return {
    period: s.period, accrual_type: s.accrual_type || 'other', description: s.description || '',
    amount: Number(s.amount) || 0, expense_account: s.expense_account || '', accrued_account: s.accrued_account || '',
  };
}

/**
 * Akrual (menu Akuntansi › Akrual & Tutup Buku).
 * 2026-11-05 (PANDUAN_UI G1): memakai cetakan PageLayout — pilihan bulan & jenis di toolbar kiri, muat ulang di
 * kanan; formulir memakai dialog aplikasi (dulu lapisan buatan sendiri, kotak bulan kosong, dan isian "UUID akun").
 * 2026-11-08 (Standar UI/UX v2): FormPopup standar; daftar bisa diunduh Excel/CSV; aksi baris paling banyak 2 terlihat
 * (Posting hijau + menu "Lainnya" berisi Ubah/Hapus); kartu angka berketerangan.
 */
export default function AccrualsModule({ token }) {
  const [accruals, setAccruals] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState({ type: '', period: '' });
  const { toast } = useToast();
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAccruals = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter.type) params.set('accrual_type', filter.type);
      if (filter.period) params.set('period', filter.period);
      const qs = params.toString();
      const r = await fetch(`/api/rahaza/finance/accruals${qs ? `?${qs}` : ''}`, { headers });
      if (r.ok) setAccruals(await r.json());
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal memuat data akrual', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filter]);

  useEffect(() => { fetchAccruals(); }, [fetchAccruals]);

  const save = async (s) => {
    if (saving) return;
    setSaving(true);
    try {
      const url = s.id ? `/api/rahaza/finance/accruals/${s.id}` : '/api/rahaza/finance/accruals';
      const method = s.id ? 'PUT' : 'POST';
      const r = await fetch(url, { method, headers, body: JSON.stringify(accrualPayload(s)) });
      if (r.ok) {
        toast({ title: 'Berhasil', description: `Akrual ${s.id ? 'diperbarui' : 'dicatat sebagai draf'}` });
        setEditing(null);
        fetchAccruals();
      } else {
        const err = await r.json().catch(() => ({}));
        toast({ title: 'Gagal', description: err.detail || 'Gagal menyimpan', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal menyimpan akrual', variant: 'destructive' });
    } finally { setSaving(false); }
  };

  const act = async (url, okText, failText) => {
    try {
      const r = await fetch(url, { method: 'POST', headers });
      const d = await r.json().catch(() => ({}));
      if (r.ok) { toast({ title: 'Berhasil', description: okText(d) }); fetchAccruals(); }
      else toast({ title: 'Gagal', description: d.detail || failText, variant: 'destructive' });
    } catch (e) {
      toast({ title: 'Gagal', description: failText, variant: 'destructive' });
    }
  };

  const post = async (a) => {
    if (!(await confirmDialog({ title: `Posting akrual ${periodLabel(a.period)}?`, body: 'Jurnal dicatat pada tanggal terakhir periode akrual. Sesudah diposting, akrual hanya bisa dibalik.', confirmLabel: 'Posting' }))) return;
    act(`/api/rahaza/finance/accruals/${a.id}/post`, (d) => `Akrual dijurnal${d.je_number ? ` · ${d.je_number}` : ''}`, 'Gagal memposting akrual');
  };

  const del = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus akrual ini?', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const r = await fetch(`/api/rahaza/finance/accruals/${id}`, { method: 'DELETE', headers });
      if (r.ok) {
        toast({ title: 'Berhasil', description: 'Akrual dihapus' });
        fetchAccruals();
      } else {
        const d = await r.json().catch(() => ({}));
        toast({ title: 'Gagal', description: d.detail || 'Gagal menghapus', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal menghapus', variant: 'destructive' });
    }
  };

  const reverse = async (id) => {
    // 2026-11-06 (pola P1): server TIDAK membaca tanggal kiriman layar — jurnal pembalik selalu
    // bertanggal 1 periode pembalik (bulan sesudah periode akrual, rahaza_posting.post_accrual_reversal).
    // Dulu layar mengirim `reversal_date` hari ini dan menulis "dicatat per hari ini" (tidak benar).
    if (!(await confirmDialog({ title: 'Balik akrual ini?', body: 'Jurnal pembalik dicatat pada tanggal 1 bulan sesudah periode akrual.', confirmLabel: 'Balik' }))) return;
    act(`/api/rahaza/finance/accruals/${id}/reverse`, (d) => `Akrual dibalik${d.reversal_je_number ? ` · ${d.reversal_je_number}` : ''}`, 'Gagal membalik akrual');
  };

  const sumBy = (st) => accruals.filter(a => a.status === st).reduce((s, a) => s + (Number(a.amount) || 0), 0);

  const { page, setPage, totalPages, total, paged } = useClientPagination(accruals, PAGE_SIZE);
  return (
    <PageLayout
      testId="accruals-page"
      title="Akrual"
      subtitle="Beban yang sudah terjadi tetapi belum dibayar: dijurnal di akhir periode, dibalik di awal periode berikutnya."
      actions={
        <Button onClick={() => setEditing({ period: '', accrual_type: 'utility', description: '', amount: 0, expense_account: '', accrued_account: '' })} data-testid="accrual-add">
          <Plus className="w-4 h-4" />Akrual baru
        </Button>
      }
      filters={<>
        {/* PANDUAN_UI G6 (2026-11-04): pilihan bulan berlabel (dulu kotak bulan kosong "--------- ----") */}
        <SmartNativeSelect value={filter.period} onChange={e => setFilter(f => ({ ...f, period: e.target.value }))}
          className="h-9 w-44" data-testid="accrual-filter-period">
          <option value="">Semua periode</option>
          {MONTH_OPTIONS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filter.type} onChange={e => setFilter(f => ({ ...f, type: e.target.value }))}
          className="h-9 w-48" data-testid="accrual-filter-type">
          <option value="">Semua jenis</option>
          {ACCRUAL_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="akrual" namaLembar="Akrual" baris={accruals} testId="accrual-unduh"
          kolom={[
            { label: 'Periode', nilai: (a) => periodLabel(a.period) },
            { label: 'Jenis', nilai: (a) => typeLabel(a.accrual_type) },
            { label: 'Keterangan', nilai: (a) => a.description || '' },
            { label: 'Jumlah', nilai: (a) => Number(a.amount) || 0 },
            { label: 'Status', nilai: (a) => (STATUS_META[a.status] || { label: a.status || '' }).label },
            { label: 'Jurnal', nilai: (a) => a.je_number || '' },
            { label: 'Jurnal pembalik', nilai: (a) => a.reversal_je_number || '' },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchAccruals} data-testid="accrual-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </>}
      summary={accruals.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <StatTile label="Draf belum dijurnal" value={fmt(sumBy('draft'))} sub="Jumlah akrual berstatus Draf di daftar (sesuai saringan)" />
          <StatTile label="Terjurnal (belum dibalik)" value={fmt(sumBy('posted'))} sub="Jumlah akrual berstatus Terjurnal di daftar (sesuai saringan)" />
        </div>
      )}
      footer={!loading && accruals.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : accruals.length === 0 ? (
          <EmptyState icon={FileText} title="Belum ada akrual" description="Akrual mencatat beban yang sudah terjadi tetapi belum dibayar." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="accrual-table">
              <thead>
                <tr>
                  <th className="text-left">Periode</th>
                  <th className="text-left">Jenis</th>
                  <th className="text-left">Keterangan</th>
                  <th className="text-right">Jumlah</th>
                  <th className="text-left">Status</th>
                  <th className="text-right">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {paged.map(a => {
                  const st = STATUS_META[a.status] || { label: a.status || '—', tone: 'muted' };
                  return (
                    <tr key={a.id} data-testid={`accrual-row-${a.id}`}>
                      <td className="whitespace-nowrap">{periodLabel(a.period)}</td>
                      <td>{typeLabel(a.accrual_type)}</td>
                      <td>{a.description}{(a.je_number || a.reversal_je_number) && (
                        <div className="text-xs text-muted-foreground">{[a.je_number, a.reversal_je_number && `pembalik ${a.reversal_je_number}`].filter(Boolean).join(' · ')}</div>
                      )}</td>
                      <td className="text-right tabular-nums">{fmt(a.amount)}</td>
                      <td><StatusBadge status={a.status} tone={st.tone} label={st.label} /></td>
                      <td className="text-right">
                        <div className="flex gap-1 justify-end">
                          {a.status === 'draft' && (
                            <>
                              <Button variant="success" size="sm" onClick={() => post(a)} data-testid={`accrual-post-${a.id}`}>
                                <BookCheck className="w-4 h-4" />Posting
                              </Button>
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label="Lainnya" data-testid={`accrual-more-${a.id}`}><MoreHorizontal className="w-4 h-4" /></Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuItem onClick={() => setEditing({ ...a })} data-testid={`accrual-edit-${a.id}`}><Edit2 className="w-4 h-4 mr-2" />Ubah</DropdownMenuItem>
                                  <DropdownMenuItem onClick={() => del(a.id)} className="text-[hsl(var(--danger-text))]" data-testid={`accrual-delete-${a.id}`}><Trash2 className="w-4 h-4 mr-2" />Hapus</DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </>
                          )}
                          {a.status === 'posted' && !a.reversed_at && (
                            <Button variant="ghost" size="icon-sm" onClick={() => reverse(a.id)} title="Balik akrual" aria-label="Balik akrual" data-testid={`accrual-reverse-${a.id}`}>
                              <RotateCcw className="w-4 h-4" />
                            </Button>
                          )}
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
      {editing && <AccrualEditor value={editing} headers={headers} saving={saving} onClose={() => setEditing(null)} onSave={save} />}
    </PageLayout>
  );
}

function AccrualEditor({ value, headers, saving, onClose, onSave }) {
  const [s, setS] = useState(value);
  const [accounts, setAccounts] = useState([]);
  const coaCv = cvAccountParam(useCv()?.cv);  // Tahap 8: akun CV terpilih saja
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  // Akun dipilih dari Bagan Akun (dulu kotak "Account ID (COA)" yang harus diisi UUID)
  useEffect(() => {
    fetch(`/api/rahaza/coa/accounts${coaCv ? `?${coaCv}` : ''}`, { headers })
      .then(r => (r.ok ? r.json() : []))
      .then(d => setAccounts((Array.isArray(d) ? d : d.items || []).filter(a => a.active !== false && !a.is_group)))
      .catch(() => setAccounts([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const periodOpts = s.period && !MONTH_OPTIONS.some(m => m.value === s.period)
    ? [{ value: s.period, label: periodLabel(s.period) }, ...MONTH_OPTIONS] : MONTH_OPTIONS;
  const accOpts = (types, cur) => accounts.filter(a => types.includes(a.type) || a.code === cur);
  // server tidak mengubah periode & jenis draf yang sudah ada (PUT hanya keterangan, jumlah, akun)
  const locked = !!s.id;
  const missing = !s.period ? 'Pilih periode.' : !(Number(s.amount) > 0) ? 'Isi jumlah lebih dari 0.' : '';
  // 2026-11-08 (Standar UI/UX v2): popup form standar (FormPopup pendek, Isian, Simpan hijau).
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="accrual-editor"
      judul={s.id ? 'Ubah akrual' : 'Akrual baru'}
      keterangan="Akun yang dikosongkan diambil dari Pengaturan Keuangan › Pemetaan akun otomatis (Akrual)."
      onSimpan={() => onSave(s)} menyimpan={saving} bisaSimpan={!missing}
      galat={missing && (s.period || Number(s.amount) > 0) ? missing : undefined}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Periode" wajib petunjuk={locked ? 'Tidak bisa diubah — hapus lalu buat ulang bila salah.' : undefined}>
          <SmartNativeSelect value={s.period} onChange={e => upd('period', e.target.value)} disabled={locked} className="h-9 w-full" data-testid="accrual-period">
            <option value="">Pilih bulan</option>
            {periodOpts.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Jenis">
          <SmartNativeSelect value={s.accrual_type || 'other'} onChange={e => upd('accrual_type', e.target.value)} disabled={locked} searchable={false} className="h-9 w-full" data-testid="accrual-type">
            {ACCRUAL_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
      <Isian label="Keterangan" htmlFor="accrual-description">
        <Textarea id="accrual-description" value={s.description} onChange={e => upd('description', e.target.value)} rows={3} data-testid="accrual-description" />
      </Isian>
      <Isian label="Jumlah (Rp)" wajib>
        <MoneyInput glass value={s.amount || 0} onChange={e => upd('amount', Number(e.target.value))} data-testid="accrual-amount" />
      </Isian>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Akun beban (debit)">
          <SmartNativeSelect value={s.expense_account || ''} onChange={e => upd('expense_account', e.target.value)} className="h-9 w-full"
            searchPlaceholder="Cari kode atau nama akun…" data-testid="accrual-expense-account">
            <option value="">Bawaan sesuai jenis</option>
            {accOpts(EXPENSE_TYPES, s.expense_account).map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Akun beban yang masih harus dibayar (kredit)">
          <SmartNativeSelect value={s.accrued_account || ''} onChange={e => upd('accrued_account', e.target.value)} className="h-9 w-full"
            searchPlaceholder="Cari kode atau nama akun…" data-testid="accrual-accrued-account">
            <option value="">Bawaan sesuai jenis</option>
            {accOpts(ACCRUED_TYPES, s.accrued_account).map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
    </FormPopup>
  );
}
