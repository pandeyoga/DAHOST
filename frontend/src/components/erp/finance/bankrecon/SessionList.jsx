import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { GlassCard } from '@/components/ui/glass';
import { EmptyState } from '../../moduleAtoms';
import FilterChips from '@/components/ui/filter-chips';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import PaginationBar from '@/components/ui/PaginationBar';
import { Loader2, Plus, AlertCircle, Trash2, ChevronRight, Scale } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah as fmt } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { thisMonthWIB } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;
const LIMIT = 15;

export const STATUS_CFG = {
  draft:       { label: 'Draf',      color: 'bg-muted text-foreground border-border' },
  in_progress: { label: 'Diproses',  color: 'bg-blue-100 text-blue-700 border-blue-200' },
  approved:    { label: 'Disetujui', color: 'bg-green-100 text-green-700 border-green-200' },
};

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
      toast({ title: 'Sesi dibuat', description: `${data.period} · ${data.account_name} (${data.gl_account_code})` });
      onCreated(data);
    } catch (e) {
      toast({ title: 'Gagal membuat sesi', description: e?.response?.data?.detail || e.message, variant: 'destructive' });
    } finally { setSaving(false); }
  };

  return (
    <Card className="border-primary/30 bg-primary/5" data-testid="recon-create-form">
      <CardHeader className="pb-2"><CardTitle className="text-sm">Buat Sesi Rekonsiliasi</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-medium mb-1 block">Periode *</label>
            <input type="month" data-testid="recon-input-period" className="w-full border rounded-lg px-3 py-2 text-sm"
              value={form.period} onChange={set('period')} />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Rekening Kas/Bank * (Master Rekening)</label>
            <select data-testid="recon-select-cash-account" className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              value={form.cash_account_id} onChange={set('cash_account_id')}>
              <option value="">— pilih rekening —</option>
              {accounts.map(a => (
                <option key={a.id} value={a.id}>{a.name} · {a.code} → GL {a.gl_account_code || '(belum ada)'}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Saldo Awal Rekening Koran</label>
            <MoneyInput unstyled decimals={2} allowNegative data-testid="recon-input-opening" className="w-full border rounded-lg px-3 py-2 text-sm"
              value={form.opening_balance} onChange={set('opening_balance')} />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Saldo Akhir Rekening Koran</label>
            <MoneyInput unstyled decimals={2} allowNegative data-testid="recon-input-closing" className="w-full border rounded-lg px-3 py-2 text-sm"
              value={form.closing_balance} onChange={set('closing_balance')} />
          </div>
        </div>
        <input data-testid="recon-input-notes" className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="Catatan (opsional)"
          value={form.notes} onChange={set('notes')} />
        <div className="flex gap-2 justify-end">
          <Button variant="outline" size="sm" onClick={onCancel}>Batal</Button>
          <Button size="sm" data-testid="recon-create-submit" onClick={submit} disabled={saving}>
            {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />} Simpan Sesi
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function SessionList({ headers, onOpen }) {
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
  }, [headers, skip, status, toast]);

  useEffect(() => { load(); }, [load]);

  const remove = async (s) => {
    if (!(await confirmDialog(`Hapus sesi ${s.period} · ${s.account_name}?`))) return;
    try {
      await axios.delete(`${API}/api/finance/bank-recon/sessions/${s.id}`, { headers });
      toast({ title: 'Sesi dihapus' }); load();
    } catch (e) {
      toast({ title: 'Gagal hapus', description: e?.response?.data?.detail || e.message, variant: 'destructive' });
    }
  };

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin" /></div>;

  return (
    <div className="space-y-4">
      {summary && (
        <FilterChips value={status} onChange={(k) => { setStatus(k); setSkip(0); }} testId="recon-status-tabs" ariaLabel="Status sesi"
          options={[{ key: '', label: 'Semua', count: summary.total_sessions || 0 }, { key: 'draft', label: 'Draf', count: summary.draft || 0 },
            { key: 'in_progress', label: 'Diproses', count: summary.in_progress || 0 }, { key: 'approved', label: 'Disetujui', count: summary.approved || 0 }]} />
      )}
      {summary?.total_unmatched > 0 && (
        <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2 text-sm" data-testid="recon-unmatched-alert">
          <AlertCircle className="w-4 h-4 text-amber-600" />
          <span className="text-amber-800">Ada <strong>{summary.total_unmatched}</strong> mutasi bank yang belum dicocokkan di sesi aktif.</span>
        </div>
      )}

      <div className="flex items-center justify-between">
        <span />
        <Button data-testid="btn-create-session" onClick={() => setShowCreate(v => !v)}>
          <Plus className="w-4 h-4" /> Sesi baru
        </Button>
      </div>

      {showCreate && (
        <CreateForm headers={headers} accounts={accounts} onCancel={() => setShowCreate(false)}
          onCreated={(s) => { setShowCreate(false); onOpen(s); }} />
      )}

      {items.length === 0 ? (
        <GlassCard className="p-0" data-testid="recon-empty">
          <EmptyState icon={Scale} title="Belum ada sesi rekonsiliasi"
            description="Satu sesi = satu rekening bank untuk satu bulan. Unggah rekening koran, lalu cocokkan dengan buku besar."
            action={{ label: 'Mulai sesi', onClick: () => setShowCreate(true) }} />
        </GlassCard>
      ) : (
        <div className="space-y-2" data-testid="recon-session-list">
          {items.map(s => {
            const st = STATUS_CFG[s.status] || STATUS_CFG.draft;
            return (
              <div key={s.id} data-testid={`recon-session-${s.id}`}
                className="flex items-center justify-between border rounded-lg px-4 py-3 hover:bg-muted/40 cursor-pointer"
                onClick={() => onOpen(s)}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-sm">{s.period}</span>
                    <span className="text-sm">{s.account_name}</span>
                    <span className="text-xs text-muted-foreground font-mono">{s.gl_account_code}</span>
                    <Badge variant="outline" className={`text-[10px] ${st.color}`}>{st.label}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {s.total_bank_txns || 0} mutasi · {s.matched_count || 0} cocok · {s.unmatched_count || 0} belum · saldo akhir {fmt(s.closing_balance || 0)}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  {s.status !== 'approved' && (
                    <Button variant="ghost" size="icon" data-testid={`recon-delete-${s.id}`}
                      onClick={(e) => { e.stopPropagation(); remove(s); }}><Trash2 className="w-4 h-4 text-red-500" /></Button>
                  )}
                  <ChevronRight className="w-4 h-4 text-muted-foreground" />
                </div>
              </div>
            );
          })}
          <PaginationBar total={total} skip={skip} limit={LIMIT} onPageChange={setSkip} />
        </div>
      )}
    </div>
  );
}
