import { useState, useEffect, useCallback, useRef } from 'react';
import { Plus, RefreshCw, Edit2, Trash2, Wallet, AlertTriangle } from 'lucide-react';
import { GlassCard, GlassPanel, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader, StatTile } from './moduleAtoms';
import { formatRupiah, formatDateID, formatNumber } from '@/lib/format';
import PaginationLite from '@/components/ui/pagination-lite';
import { MoneyInput } from '@/components/ui/money-input';
import { toast } from 'sonner';

const fmt = formatRupiah;

const TYPE_LABEL = { cash: 'Kas', bank: 'Bank' };
const MUT_PAGE = 50;

/**
 * Rekening & Mutasi (menu Keuangan › Kas & Bank).
 * 2026-11-04 (audit Keuangan): Kas Kecil = rekening kas biasa di sini (dana kas kecil terpisah dihapus dari
 * menu); mutasi per halaman dari yang terbaru (dulu 2000 baris tertua → mutasi terbaru hilang); rekening
 * bersaldo 0 tanpa mutasi dilipat; tombol "Sinkron Bagan Akun & GL" pindah ke Adm. Sistem.
 */
export default function RahazaCashAccountsModule({ token }) {
  const [accounts, setAccounts] = useState([]);
  const [movements, setMovements] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showIdle, setShowIdle] = useState(false);
  const [mutPage, setMutPage] = useState(1);
  const panelRef = useRef(null);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/cash-accounts', { headers });
      if (r.ok) setAccounts(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  useEffect(() => { fetchAccounts(); }, [fetchAccounts]);

  // K19: daftar mutasi DITURUNKAN DARI BUKU BESAR (baris jurnal akun rekening). Mutasi tercatat lama hanya metadata.
  const [mutInfo, setMutInfo] = useState(null);
  const fetchMovements = async (account_id, page = 1) => {
    setMovements([]); setMutInfo(null); setMutPage(page);
    const r = await fetch(`/api/rahaza/finance/reports/cash-mutations?account_id=${account_id}&page=${page}&page_size=${MUT_PAGE}`, { headers });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast.error(d.detail || `Gagal memuat mutasi (HTTP ${r.status})`); return; }
    setMovements(d.rows || []); setMutInfo(d);
  };
  const openAccount = (a) => { setSelected(a); fetchMovements(a.id, 1); };
  useEffect(() => {
    if (selected && panelRef.current) panelRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [selected]);

  const save = async (body) => {
    const url = body.id ? `/api/rahaza/cash-accounts/${body.id}` : '/api/rahaza/cash-accounts';
    const method = body.id ? 'PUT' : 'POST';
    const r = await fetch(url, { method, headers, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast.error(d.detail || `Gagal menyimpan rekening (HTTP ${r.status})`); return; }
    if (d._opening_post && d._opening_post.je_number) toast.success(`Rekening dibuat · saldo awal dijurnal ${d._opening_post.je_number}`);
    else if (d._opening_post && d._opening_post.error) toast.error(`Rekening dibuat, tetapi jurnal saldo awal GAGAL: ${d._opening_post.error}`);
    setEditing(null); fetchAccounts();
  };
  const del = async (a) => {
    if (!window.confirm(`Nonaktifkan rekening ${a.name}?`)) return;
    await fetch(`/api/rahaza/cash-accounts/${a.id}`, { method: 'DELETE', headers });
    fetchAccounts();
  };

  const total = accounts.reduce((s, a) => s + (Number(a.balance) || 0), 0);
  const mismatch = accounts.filter(a => a.balance_source === 'gl' && a.balance_diff !== 0);
  const noGl = accounts.filter(a => a.balance_source !== 'gl');
  const isIdle = (a) => Math.abs(Number(a.balance) || 0) < 0.5 && !Number(a.mutation_count || 0);
  const idle = accounts.filter(isIdle);
  const shown = showIdle ? accounts : accounts.filter(a => !isIdle(a));
  const mutPages = Math.max(1, Math.ceil((mutInfo?.count || 0) / MUT_PAGE));

  return (
    <div className="space-y-5" data-testid="rahaza-cash-page">
      <PageHeader
        icon={Wallet}
        title="Rekening & Mutasi"
        subtitle="Saldo dan mutasi tiap rekening dibaca dari buku besar. Kas Kecil termasuk di sini."
        actions={
          <>
            <Button variant="ghost" onClick={fetchAccounts} className="h-9 border border-[var(--glass-border)]" title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-3.5 h-3.5" /></Button>
            <Button onClick={() => setEditing({ code: '', name: '', type: 'cash', opening_balance: 0 })} className="h-9" data-testid="ca-add"><Plus className="w-3.5 h-3.5 mr-1.5" />Rekening baru</Button>
          </>
        }
      />
      <StatTile label="Total saldo semua rekening" value={fmt(total)} accent="success" className="md:col-span-3" testId="ca-total-gl" />
      {(mismatch.length > 0 || noGl.length > 0) && (
        <div className="bg-amber-400/8 border border-amber-400/20 rounded-lg px-4 py-3 text-xs text-amber-700 dark:text-amber-300 flex items-start gap-2" data-testid="ca-gl-warning">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            {mismatch.length > 0 && <p>{mismatch.length} rekening saldo buku besar ≠ saldo mutasi ({mismatch.map(a => a.code).join(', ')}). Angka kartu memakai buku besar; selisih berarti ada mutasi yang belum dijurnal.</p>}
            {noGl.length > 0 && <p>{noGl.length} rekening belum punya akun buku besar ({noGl.map(a => a.code).join(', ')}). Minta admin menjalankan “Sinkron Bagan Akun & GL” di Adm. Sistem › Perawatan Data Keuangan.</p>}
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {shown.map(a => (
          <GlassCard key={a.id} className={`p-4 cursor-pointer ${selected?.id === a.id ? 'ring-2 ring-[hsl(var(--primary))]' : ''}`} onClick={() => openAccount(a)} data-testid={`ca-card-${a.code}`}>
            <div className="flex items-start justify-between">
              <div>
                <div className="font-mono text-xs text-muted-foreground">{a.code}{a.gl_account_code && a.gl_account_code !== a.code && <span className="ml-2 text-primary/80">akun {a.gl_account_code}</span>}</div>
                <div className="font-semibold text-foreground">{a.name}</div>
                <div className="text-[11px] text-muted-foreground mt-1">{TYPE_LABEL[a.type] || a.type}{a.bank_name && ` · ${a.bank_name}`}{a.account_number && ` · ${a.account_number}`}</div>
              </div>
              <div className="flex gap-1">
                <button onClick={e => { e.stopPropagation(); setEditing({ ...a }); }} className="text-primary hover:bg-primary/10 rounded p-1" title="Ubah" aria-label="Ubah"><Edit2 className="w-3 h-3" /></button>
                <button onClick={e => { e.stopPropagation(); del(a); }} className="text-red-500 dark:text-red-300 hover:bg-red-400/10 rounded p-1" title="Nonaktifkan" aria-label="Nonaktifkan"><Trash2 className="w-3 h-3" /></button>
              </div>
            </div>
            <div className="mt-3 text-2xl font-bold text-foreground tabular-nums" data-testid={`ca-balance-${a.code}`}>{fmt(a.balance)}</div>
            <div className="mt-1 flex items-center justify-between text-[11px]">
              <span className={a.balance_source === 'gl' ? 'text-muted-foreground' : 'text-amber-600 dark:text-amber-400'} data-testid={`ca-source-${a.code}`}>
                {a.balance_source === 'gl' ? `${a.mutation_count ?? 0} mutasi` : 'Belum tertaut buku besar'}
              </span>
              {a.balance_source === 'gl' && a.balance_diff !== 0 && (
                <span className="text-amber-600 dark:text-amber-400" data-testid={`ca-diff-${a.code}`}>selisih {fmt(a.balance_diff)}</span>
              )}
            </div>
          </GlassCard>
        ))}
        {accounts.length === 0 && !loading && <GlassCard className="p-6 text-center text-muted-foreground col-span-full">Belum ada rekening. Tekan “Rekening baru”.</GlassCard>}
      </div>
      {idle.length > 0 && (
        <button type="button" onClick={() => setShowIdle(v => !v)} className="text-xs text-primary hover:underline" data-testid="ca-toggle-idle">
          {showIdle ? 'Sembunyikan rekening tanpa saldo & mutasi' : `Tampilkan ${idle.length} rekening tanpa saldo & mutasi`}
        </button>
      )}
      {selected && (
        <div ref={panelRef}>
          <GlassCard className="p-4" data-testid="ca-movements-panel">
            <div className="flex items-center justify-between mb-1">
              <h3 className="font-semibold text-foreground">Mutasi {selected.name}</h3>
              <button onClick={() => setSelected(null)} className="text-muted-foreground" title="Tutup" aria-label="Tutup">×</button>
            </div>
            <p className="text-[11px] text-muted-foreground mb-3" data-testid="ca-mutations-source">
              {mutInfo ? `${mutInfo.count} mutasi · masuk ${fmt(mutInfo.total_in)} · keluar ${fmt(mutInfo.total_out)} · saldo ${fmt(mutInfo.closing)}` : 'Memuat…'}
            </p>
            {mutInfo && movements.length === 0 ? <div className="text-xs text-muted-foreground text-center py-8">Belum ada mutasi.</div> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs text-muted-foreground"><th className="pb-2">Tanggal</th><th className="pb-2">Jurnal</th><th className="pb-2">Jenis</th><th className="pb-2">Keterangan</th><th className="pb-2 text-right">Masuk</th><th className="pb-2 text-right">Keluar</th><th className="pb-2 text-right">Saldo</th></tr></thead>
                  <tbody>{movements.map(m => (
                    <tr key={m.id} className="border-t border-[var(--glass-border)]" data-testid={`ca-mut-${m.source_module}`}>
                      <td className="py-2 text-xs whitespace-nowrap">{formatDateID(m.date)}</td>
                      <td className="py-2 text-xs font-mono whitespace-nowrap">{m.je_number || '-'}</td>
                      <td className="py-2 text-xs" title={m.source_module}>{m.category_label || m.category}</td>
                      <td className="py-2 text-xs">{m.ref_label || m.description || '-'}</td>
                      <td className="py-2 text-right tabular-nums text-emerald-600 dark:text-emerald-300 text-xs">{m.direction === 'in' ? formatNumber(m.amount) : ''}</td>
                      <td className="py-2 text-right tabular-nums text-red-600 dark:text-red-300 text-xs">{m.direction === 'out' ? formatNumber(m.amount) : ''}</td>
                      <td className="py-2 text-right tabular-nums text-xs">{formatNumber(m.running_balance)}</td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
            )}
            {mutPages > 1 && (
              <div className="pt-2">
                <PaginationLite page={mutPage} totalPages={mutPages} total={mutInfo?.count || 0} pageSize={MUT_PAGE}
                  onPageChange={(p) => fetchMovements(selected.id, p)} />
              </div>
            )}
          </GlassCard>
        </div>
      )}
      {editing && <CAEditor value={editing} onClose={() => setEditing(null)} onSave={save} headers={headers} />}
    </div>
  );
}

function CAEditor({ value, onClose, onSave, headers }) {
  const [s, setS] = useState(value);
  const [glOptions, setGlOptions] = useState([]);
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  useEffect(() => {
    if (s.id) return;
    fetch('/api/rahaza/cash-accounts/gl-candidates', { headers }).then(r => (r.ok ? r.json() : [])).then(setGlOptions).catch(() => setGlOptions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const pickGl = (code) => {
    const o = glOptions.find(x => x.code === code);
    setS(x => ({ ...x, gl_account_code: code, code: o ? code : x.code, name: o && !x.name ? o.name : x.name, type: o ? (code.startsWith('1-11') ? 'cash' : 'bank') : x.type }));
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <GlassCard className="p-6 max-w-md w-full" onClick={e => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-foreground mb-4">{s.id ? 'Edit' : 'Tambah'} Rekening</h2>
        <div className="space-y-3">
          {!s.id && (
            <div>
              <label className="text-xs uppercase text-muted-foreground">Akun GL (Bagan Akun)</label>
              <select value={s.gl_account_code || ''} onChange={e => pickGl(e.target.value)} className="w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground" data-testid="ca-gl-select">
                <option value="">— Buat akun GL baru otomatis di bawah Kas/Bank —</option>
                {glOptions.map(o => <option key={o.code} value={o.code}>{o.code} · {o.name}</option>)}
              </select>
              <p className="text-[11px] text-muted-foreground mt-1">{glOptions.length ? `${glOptions.length} akun kas/bank di Bagan Akun belum punya rekening — pilih supaya tidak dobel.` : 'Semua akun kas/bank di Bagan Akun sudah punya rekening.'}</p>
            </div>
          )}
          <div><label className="text-xs uppercase text-muted-foreground">Kode</label><GlassInput value={s.code} onChange={e => upd('code', e.target.value.toUpperCase())} disabled={!!s.id} data-testid="ca-code" /></div>
          <div><label className="text-xs uppercase text-muted-foreground">Nama</label><GlassInput value={s.name} onChange={e => upd('name', e.target.value)} data-testid="ca-name" /></div>
          <div><label className="text-xs uppercase text-muted-foreground">Tipe</label><select value={s.type} onChange={e => upd('type', e.target.value)} className="w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"><option value="cash">Kas</option><option value="bank">Bank</option></select></div>
          {s.type === 'bank' && <>
            <div><label className="text-xs uppercase text-muted-foreground">Nama Bank</label><GlassInput value={s.bank_name || ''} onChange={e => upd('bank_name', e.target.value)} /></div>
            <div><label className="text-xs uppercase text-muted-foreground">Nomor Rekening</label><GlassInput value={s.account_number || ''} onChange={e => upd('account_number', e.target.value)} /></div>
          </>}
          {!s.id && <div><label className="text-xs uppercase text-muted-foreground">Saldo Awal</label><MoneyInput glass value={s.opening_balance || 0} onChange={e => upd('opening_balance', Number(e.target.value))} /></div>}
        </div>
        <div className="flex gap-2 mt-6 justify-end"><Button variant="ghost" onClick={onClose} className="border border-[var(--glass-border)]">Batal</Button><Button onClick={() => onSave(s)} data-testid="ca-save">Simpan</Button></div>
      </GlassCard>
    </div>
  );
}
