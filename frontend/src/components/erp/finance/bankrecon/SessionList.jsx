import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { EmptyState, Notice, StatusBadge } from '../../moduleAtoms';
import FilterChips from '@/components/ui/filter-chips';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationBar from '@/components/ui/PaginationBar';
import { Loader2, Plus, AlertCircle, Trash2, Scale, RefreshCw } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah as fmt } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { thisMonthWIB } from '@/lib/waktu';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { monthOptions } from '../PeriodPicker';

const API = process.env.REACT_APP_BACKEND_URL;
const LIMIT = 15;

// Status sesi → label & nada StatusBadge (PANDUAN_UI G8: token warna, bukan palet langsung).
export const STATUS_CFG = {
  draft:       { label: 'Draf',      tone: 'muted' },
  in_progress: { label: 'Diproses',  tone: 'info' },
  approved:    { label: 'Disetujui', tone: 'success' },
};
export function SessionStatusBadge({ status }) {
  const st = STATUS_CFG[status] || STATUS_CFG.draft;
  return <StatusBadge status={status} label={st.label} tone={st.tone} />;
}
/** "2026-10" → "Oktober 2026". */
export function fmtPeriod(ym) {
  const [y, m] = String(ym || '').split('-').map(Number);
  if (!y || !m) return ym || '—';
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('id-ID', { month: 'long', year: 'numeric', timeZone: 'UTC' });
}

// Formulir isian pendek — popup. Dulu kartu bergaris ungu di tengah halaman dengan pilihan polos & pemilih bulan bawaan.
function CreateForm({ headers, accounts, onCreated, onCancel }) {
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    period: thisMonthWIB(), cash_account_id: '', opening_balance: 0, closing_balance: 0, notes: '',
  });
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const submit = async () => {
    if (!form.cash_account_id) return toast({ title: 'Pilih rekening kas/bank dulu', variant: 'destructive' });
    setSaving(true);
    try {
      const { data } = await axios.post(`${API}/api/finance/bank-recon/sessions`, form, { headers });
      toast({ title: 'Sesi dibuat', description: `${fmtPeriod(data.period)} · ${data.account_name} (akun ${data.gl_account_code})` });
      onCreated(data);
    } catch (e) {
      toast({ title: 'Gagal membuat sesi', description: e?.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setSaving(false); }
  };

  // 2026-11-08 (Standar UI/UX v2): popup form standar (FormPopup pendek, Isian, Simpan hijau).
  return (
    <FormPopup open onClose={onCancel} ukuran="pendek" testId="recon-create-form"
      judul="Sesi rekonsiliasi baru" keterangan="Satu sesi = satu rekening untuk satu bulan."
      onSimpan={submit} menyimpan={saving} labelSimpan="Simpan sesi" bisaSimpan={!!form.cash_account_id}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Periode" wajib>
          <SmartNativeSelect data-testid="recon-input-period" className="h-9 w-full" searchable={false}
            value={form.period} onChange={set('period')} aria-label="Periode">
            {monthOptions(24).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Rekening kas/bank" wajib>
          <SmartNativeSelect data-testid="recon-select-cash-account" className="h-9 w-full"
            value={form.cash_account_id} onChange={set('cash_account_id')} aria-label="Rekening kas/bank">
            <option value="">— pilih rekening —</option>
            {accounts.map(a => (
              <option key={a.id} value={a.id}>{a.name} · {a.code} · akun {a.gl_account_code || 'belum ada'}</option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Saldo awal rekening koran">
          <MoneyInput glass decimals={2} allowNegative data-testid="recon-input-opening"
            value={form.opening_balance} onChange={set('opening_balance')} />
        </Isian>
        <Isian label="Saldo akhir rekening koran">
          <MoneyInput glass decimals={2} allowNegative data-testid="recon-input-closing"
            value={form.closing_balance} onChange={set('closing_balance')} />
        </Isian>
      </div>
      <Isian label="Catatan" htmlFor="recon-notes">
        <GlassInput id="recon-notes" data-testid="recon-input-notes" placeholder="Opsional"
          value={form.notes} onChange={set('notes')} />
      </Isian>
    </FormPopup>
  );
}

/**
 * Daftar sesi rekonsiliasi — mengisi slot cetakan `Page` (PageLayout dari BankReconciliation).
 * 2026-11-05 (PANDUAN_UI G1/G5): "Sesi baru" di kepala/baris tab (dulu sendirian di satu baris), pil status di
 * toolbar, daftar sesi = tabel (dulu satu kotak bergaris per sesi), sesi yang dibuka di slot `detail`.
 */
export function SessionList({ Page, headers, onOpen, activeId, detail, reloadKey }) {
  const { toast } = useToast();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [summary, setSummary] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [status, setStatus] = useState('');   // 2026-11-04: tab status menggantikan 4 kartu hitungan

  const load = useCallback(async () => {
    try {
      const [sRes, sumRes, accRes] = await Promise.all([
        axios.get(`${API}/api/finance/bank-recon/sessions`, { headers, params: { skip, limit: LIMIT, ...(status ? { status } : {}) } }),
        axios.get(`${API}/api/finance/bank-recon/summary`, { headers }),
        axios.get(`${API}/api/rahaza/cash-accounts`, { headers }),
      ]);
      setItems(sRes.data.items || []); setTotal(sRes.data.total || 0); setSummary(sumRes.data);
      const acc = Array.isArray(accRes.data) ? accRes.data : (accRes.data.items || []);
      setAccounts(acc.filter(a => a.active !== false));
    } catch (e) {
      toast({ title: 'Gagal memuat', description: e?.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setLoading(false); }
    // reloadKey: muat ulang setelah sesi yang dibuka berubah (cocok/setujui) atau ditutup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headers, skip, status, toast, reloadKey]);

  useEffect(() => { load(); }, [load]);

  const remove = async (s) => {
    const ok = await confirmDialog({ title: `Hapus sesi ${fmtPeriod(s.period)} · ${s.account_name}?`, confirmLabel: 'Hapus', danger: true });
    if (!ok) return;
    try {
      await axios.delete(`${API}/api/finance/bank-recon/sessions/${s.id}`, { headers });
      toast({ title: 'Sesi dihapus' }); load();
    } catch (e) {
      toast({ title: 'Gagal hapus', description: e?.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  const actions = (
    <Button data-testid="btn-create-session" onClick={() => setShowCreate(v => !v)}>
      <Plus className="w-4 h-4" /> Sesi baru
    </Button>
  );
  const filters = summary && (
    <FilterChips value={status} onChange={(k) => { setStatus(k); setSkip(0); }} testId="recon-status-tabs" ariaLabel="Status sesi"
      options={[{ key: '', label: 'Semua', count: summary.total_sessions || 0 }, { key: 'draft', label: 'Draf', count: summary.draft || 0 },
        { key: 'in_progress', label: 'Diproses', count: summary.in_progress || 0 }, { key: 'approved', label: 'Disetujui', count: summary.approved || 0 }]} />
  );
  const alert = summary?.total_unmatched > 0 && (
    <Notice tone="warning" icon={AlertCircle} testId="recon-unmatched-alert">
      Ada <strong>{summary.total_unmatched}</strong> mutasi bank yang belum dicocokkan di sesi aktif.
    </Notice>
  );
  // Unduh: semua sesi sesuai pil status (bukan hanya 15 di halaman ini).
  const ambilSemua = async () => {
    const { data } = await axios.get(`${API}/api/finance/bank-recon/sessions`, { headers, params: { skip: 0, limit: 5000, ...(status ? { status } : {}) } });
    return data.items || [];
  };
  const tools = <>
    <TombolUnduh namaBerkas="sesi-rekonsiliasi-bank" namaLembar="Sesi" baris={items} ambilSemua={ambilSemua} testId="recon-unduh"
      kolom={[
        { label: 'Periode', nilai: (s) => fmtPeriod(s.period) },
        { label: 'Rekening', nilai: (s) => s.account_name },
        { label: 'Akun buku besar', nilai: (s) => s.gl_account_code || '' },
        { label: 'Status', nilai: (s) => (STATUS_CFG[s.status] || STATUS_CFG.draft).label },
        { label: 'Mutasi', nilai: (s) => Number(s.total_bank_txns) || 0 },
        { label: 'Cocok', nilai: (s) => Number(s.matched_count) || 0 },
        { label: 'Belum cocok', nilai: (s) => Number(s.unmatched_count) || 0 },
        { label: 'Saldo akhir', nilai: (s) => Number(s.closing_balance) || 0 },
      ]} />
    <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="recon-list-refresh"><RefreshCw className="w-4 h-4" /></Button>
  </>;

  return (
    <Page
      actions={actions}
      filters={filters}
      tools={tools}
      summary={alert}
      detail={detail}
      footer={items.length > 0 && <PaginationBar total={total} skip={skip} limit={LIMIT} onPageChange={setSkip} />}
    >
      {loading ? (
        <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : items.length === 0 ? (
        <GlassCard className="p-0" data-testid="recon-empty">
          <EmptyState icon={Scale} title="Belum ada sesi rekonsiliasi"
            description="Satu sesi = satu rekening bank untuk satu bulan. Unggah rekening koran, lalu cocokkan dengan buku besar."
            action={{ label: 'Mulai sesi', variant: 'outline', onClick: () => setShowCreate(true) }} />
        </GlassCard>
      ) : (
        <GlassCard className="p-0 overflow-hidden" data-testid="recon-session-list">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-[var(--glass-border)]">
                  <th className="px-4 py-2">Periode</th>
                  <th className="px-3 py-2">Rekening</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2 text-right">Mutasi</th>
                  <th className="px-3 py-2 text-right">Cocok</th>
                  <th className="px-3 py-2 text-right">Belum cocok</th>
                  <th className="px-3 py-2 text-right">Saldo akhir</th>
                  <th className="px-4 py-2 text-right"><span className="sr-only">Aksi</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map(s => {
                  const open = activeId === s.id;
                  return (
                    <tr key={s.id} data-testid={`recon-session-${s.id}`}
                      className={`border-b border-[var(--glass-border)] last:border-0 hover:bg-foreground/[0.03] cursor-pointer ${open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}
                      onClick={() => onOpen(s)}>
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <Button variant="link" size="sm" className="h-auto p-0 font-semibold"
                          onClick={(e) => { e.stopPropagation(); onOpen(s); }}>{fmtPeriod(s.period)}</Button>
                      </td>
                      <td className="px-3 py-2.5">
                        {s.account_name} <span className="text-xs text-muted-foreground whitespace-nowrap">· akun {s.gl_account_code}</span>
                      </td>
                      <td className="px-3 py-2.5"><SessionStatusBadge status={s.status} /></td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{s.total_bank_txns || 0}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{s.matched_count || 0}</td>
                      <td className={`px-3 py-2.5 text-right tabular-nums ${s.unmatched_count ? 'text-[hsl(var(--warning-text))] font-medium' : ''}`}>{s.unmatched_count || 0}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums whitespace-nowrap">{fmt(s.closing_balance || 0)}</td>
                      <td className="px-4 py-2.5 text-right">
                        {s.status !== 'approved' && (
                          <Button variant="ghost" size="icon-sm" data-testid={`recon-delete-${s.id}`} title="Hapus sesi" aria-label="Hapus sesi"
                            onClick={(e) => { e.stopPropagation(); remove(s); }}><Trash2 className="w-4 h-4 text-[hsl(var(--destructive))]" /></Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      {showCreate && (
        <CreateForm headers={headers} accounts={accounts} onCancel={() => setShowCreate(false)}
          onCreated={(s) => { setShowCreate(false); load(); onOpen(s); }} />
      )}
    </Page>
  );
}
