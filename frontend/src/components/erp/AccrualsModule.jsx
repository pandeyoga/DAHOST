import { useState, useEffect, useCallback } from 'react';
import { Plus, RefreshCw, Edit2, Trash2, FileText, RotateCcw } from 'lucide-react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, StatusBadge, EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import Modal from './Modal';
import { useToast } from '@/hooks/use-toast';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { monthOptions } from './finance/PeriodPicker';

// 24 bulan terakhir, terbaru di atas
const MONTH_OPTIONS = monthOptions(24);
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const periodLabel = (code) => { const [y, m] = String(code || '').split('-'); return BULAN[Number(m) - 1] ? `${BULAN[Number(m) - 1]} ${y}` : (code || '—'); };
const PAGE_SIZE = 25;

const fmt = formatRupiah;

/**
 * Akrual (menu Akuntansi › Akrual & Tutup Buku).
 * 2026-11-05 (PANDUAN_UI G1): memakai cetakan PageLayout — pilihan bulan & jenis di toolbar kiri, muat ulang di
 * kanan; formulir memakai dialog aplikasi (dulu lapisan buatan sendiri, kotak bulan kosong, dan isian "UUID akun").
 */
export default function AccrualsModule({ token }) {
  const [accruals, setAccruals] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ type: '', period: '' });
  const { toast } = useToast();
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAccruals = useCallback(async () => {
    setLoading(true);
    try {
      let url = '/api/rahaza/finance/accruals';
      const params = [];
      if (filter.type) params.push(`type=${filter.type}`);
      if (filter.period) params.push(`period=${filter.period}`);
      if (params.length) url += '?' + params.join('&');
      const r = await fetch(url, { headers });
      if (r.ok) setAccruals(await r.json());
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal memuat data akrual', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filter]);

  useEffect(() => { fetchAccruals(); }, [fetchAccruals]);

  const save = async (body) => {
    try {
      const url = body.id ? `/api/rahaza/finance/accruals/${body.id}` : '/api/rahaza/finance/accruals';
      const method = body.id ? 'PUT' : 'POST';
      const r = await fetch(url, { method, headers, body: JSON.stringify(body) });
      if (r.ok) {
        toast({ title: 'Berhasil', description: `Akrual ${body.id ? 'diperbarui' : 'dicatat'}` });
        setEditing(null);
        fetchAccruals();
      } else {
        const err = await r.json();
        toast({ title: 'Gagal', description: err.detail || 'Gagal menyimpan', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal menyimpan akrual', variant: 'destructive' });
    }
  };

  const del = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus akrual ini?', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const r = await fetch(`/api/rahaza/finance/accruals/${id}`, { method: 'DELETE', headers });
      if (r.ok) {
        toast({ title: 'Berhasil', description: 'Akrual dihapus' });
        fetchAccruals();
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
    try {
      const r = await fetch(`/api/rahaza/finance/accruals/${id}/reverse`, {
        method: 'POST',
        headers,
      });
      if (r.ok) {
        toast({ title: 'Berhasil', description: 'Akrual dibalik' });
        fetchAccruals();
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal membalik akrual', variant: 'destructive' });
    }
  };

  const totalIncome = accruals.filter(a => a.type === 'income' && a.status === 'active').reduce((s, a) => s + (Number(a.amount) || 0), 0);
  const totalExpense = accruals.filter(a => a.type === 'expense' && a.status === 'active').reduce((s, a) => s + (Number(a.amount) || 0), 0);

  const { page, setPage, totalPages, total, paged } = useClientPagination(accruals, PAGE_SIZE);
  return (
    <PageLayout
      testId="accruals-page"
      title="Akrual"
      subtitle="Pendapatan dan beban yang sudah terjadi tetapi belum dibayar atau diterima."
      actions={
        <Button onClick={() => setEditing({ period: '', type: 'expense', description: '', amount: 0, account_id: '' })} data-testid="accrual-add">
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
          className="h-9 w-40" data-testid="accrual-filter-type">
          <option value="">Semua jenis</option>
          <option value="income">Pendapatan</option>
          <option value="expense">Beban</option>
        </SmartNativeSelect>
      </>}
      tools={
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchAccruals} data-testid="accrual-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      }
      summary={accruals.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <StatTile label="Akrual pendapatan aktif" value={fmt(totalIncome)} />
          <StatTile label="Akrual beban aktif" value={fmt(totalExpense)} />
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
          <EmptyState icon={FileText} title="Belum ada akrual" description="Akrual mencatat beban atau pendapatan yang sudah terjadi tetapi belum dibayar atau diterima." />
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
                {paged.map(a => (
                  <tr key={a.id} data-testid={`accrual-row-${a.id}`}>
                    <td className="whitespace-nowrap">{periodLabel(a.period)}</td>
                    <td>{a.type === 'income' ? 'Pendapatan' : 'Beban'}</td>
                    <td>{a.description}</td>
                    <td className="text-right tabular-nums">{fmt(a.amount)}</td>
                    <td>
                      <StatusBadge tone={a.status === 'active' ? 'info' : 'muted'} label={a.status === 'active' ? 'Aktif' : 'Dibalik'} />
                    </td>
                    <td className="text-right">
                      <div className="flex gap-1 justify-end">
                        {a.status === 'active' && (
                          <>
                            <Button variant="ghost" size="icon-sm" onClick={() => setEditing({ ...a })} title="Ubah" aria-label="Ubah" data-testid={`accrual-edit-${a.id}`}>
                              <Edit2 className="w-4 h-4" />
                            </Button>
                            <Button variant="ghost" size="icon-sm" onClick={() => reverse(a.id)} title="Balik akrual" aria-label="Balik akrual" data-testid={`accrual-reverse-${a.id}`}>
                              <RotateCcw className="w-4 h-4" />
                            </Button>
                            <Button variant="ghost" size="icon-sm" onClick={() => del(a.id)} title="Hapus" aria-label="Hapus" className="text-[hsl(var(--destructive))]" data-testid={`accrual-delete-${a.id}`}>
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      {editing && <AccrualEditor value={editing} headers={headers} onClose={() => setEditing(null)} onSave={save} />}
    </PageLayout>
  );
}

function AccrualEditor({ value, headers, onClose, onSave }) {
  const [s, setS] = useState(value);
  const [accounts, setAccounts] = useState([]);
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  // Akun dipilih dari Bagan Akun (dulu kotak "Account ID (COA)" yang harus diisi UUID)
  useEffect(() => {
    fetch('/api/rahaza/coa/accounts', { headers })
      .then(r => (r.ok ? r.json() : []))
      .then(d => setAccounts((Array.isArray(d) ? d : d.items || []).filter(a => a.active !== false && !a.is_group)))
      .catch(() => setAccounts([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const periodOpts = s.period && !MONTH_OPTIONS.some(m => m.value === s.period)
    ? [{ value: s.period, label: s.period }, ...MONTH_OPTIONS] : MONTH_OPTIONS;
  return (
    <Modal title={s.id ? 'Ubah akrual' : 'Akrual baru'} onClose={onClose} size="md" data-testid="accrual-editor">
      <div className="space-y-3">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Periode</label>
          <SmartNativeSelect value={s.period} onChange={e => upd('period', e.target.value)} className="h-9 w-full" data-testid="accrual-period">
            <option value="">Pilih bulan</option>
            {periodOpts.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </SmartNativeSelect>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Jenis</label>
          <SmartNativeSelect value={s.type} onChange={e => upd('type', e.target.value)} searchable={false} className="h-9 w-full" data-testid="accrual-type">
            <option value="income">Pendapatan</option>
            <option value="expense">Beban</option>
          </SmartNativeSelect>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Keterangan</label>
          <textarea
            value={s.description}
            onChange={e => upd('description', e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"
            rows={3}
            data-testid="accrual-description"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Jumlah (Rp)</label>
          <MoneyInput
            glass
            value={s.amount || 0}
            onChange={e => upd('amount', Number(e.target.value))}
            data-testid="accrual-amount"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Akun (opsional)</label>
          <SmartNativeSelect value={s.account_id || ''} onChange={e => upd('account_id', e.target.value)} className="h-9 w-full" data-testid="accrual-account-id">
            <option value="">Tidak dipilih</option>
            {s.account_id && !accounts.some(a => a.id === s.account_id) && <option value={s.account_id}>Akun tersimpan</option>}
            {accounts.map(a => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
          </SmartNativeSelect>
        </div>
        <div className="flex gap-2 pt-2 justify-end">
          <Button variant="outline" onClick={onClose} data-testid="accrual-cancel">Batal</Button>
          <Button onClick={() => onSave(s)} data-testid="accrual-save">Simpan</Button>
        </div>
      </div>
    </Modal>
  );
}
