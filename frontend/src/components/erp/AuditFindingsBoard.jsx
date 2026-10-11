import { useEffect, useMemo, useState } from 'react';
import { ClipboardCheck, CircleCheck, CircleDashed, Clock3 } from 'lucide-react';

// Papan Temuan Audit 2026-09-23 — status 30 temuan (Finance · Produksi/Maklon · R&D)
const STATUS_META = {
  selesai: { label: 'Selesai', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300', Icon: CircleCheck },
  diterima: { label: 'Diterima (mitigasi)', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300', Icon: Clock3 },
  terbuka: { label: 'Terbuka', cls: 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300', Icon: CircleDashed },
};
const TINGKAT_CLS = { Kritis: 'text-red-600 dark:text-red-300 font-semibold', Tinggi: 'text-orange-600 dark:text-orange-300', Sedang: 'text-yellow-700 dark:text-yellow-300', Rendah: 'text-muted-foreground' };

export default function AuditFindingsBoard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [portal, setPortal] = useState('Semua');
  const [status, setStatus] = useState('Semua');

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('/api/rahaza/admin/audit-findings', { headers: { Authorization: `Bearer ${localStorage.getItem('erp_token')}` } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        setData(await r.json());
      } catch (e) { setErr(e.message || 'Gagal memuat'); }
    })();
  }, []);

  const rows = useMemo(() => (data?.items || []).filter(f => (portal === 'Semua' || f.portal === portal) && (status === 'Semua' || f.status === status)), [data, portal, status]);
  if (err) return <div className="p-4 text-red-600" data-testid="audit-board-error">Papan temuan gagal dimuat: {err}</div>;
  if (!data) return <div className="p-4 text-muted-foreground" data-testid="audit-board-loading">Memuat papan temuan…</div>;

  const done = data.by_status?.selesai || 0;
  const pct = Math.round((done / data.total) * 100);
  return (
    <div className="space-y-4 p-2" data-testid="audit-findings-board">
      <div className="flex items-center gap-3">
        <ClipboardCheck className="w-6 h-6 text-emerald-600" />
        <div>
          <h1 className="text-lg font-semibold">Papan Temuan Audit — 23 Sep 2026</h1>
          <p className="text-xs text-muted-foreground">Sumber: {data.sumber?.join(' · ')}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl border border-[var(--glass-border)] p-3" data-testid="audit-total"><div className="text-xs text-muted-foreground">Total temuan</div><div className="text-2xl font-bold">{data.total}</div></div>
        <div className="rounded-xl border border-[var(--glass-border)] p-3" data-testid="audit-done"><div className="text-xs text-muted-foreground">Selesai</div><div className="text-2xl font-bold text-emerald-600">{done} <span className="text-sm font-normal">({pct}%)</span></div></div>
        <div className="rounded-xl border border-[var(--glass-border)] p-3" data-testid="audit-accepted"><div className="text-xs text-muted-foreground">Diterima (mitigasi)</div><div className="text-2xl font-bold text-sky-600">{data.by_status?.diterima || 0}</div></div>
        <div className="rounded-xl border border-[var(--glass-border)] p-3" data-testid="audit-open"><div className="text-xs text-muted-foreground">Terbuka</div><div className="text-2xl font-bold text-amber-600">{data.by_status?.terbuka || 0}</div></div>
      </div>
      <div className="h-2 rounded bg-muted overflow-hidden"><div className="h-2 bg-emerald-500 transition-all" style={{ width: `${pct}%` }} /></div>
      <div className="flex flex-wrap gap-2 text-sm">
        <select value={portal} onChange={e => setPortal(e.target.value)} className="border rounded px-2 py-1 bg-background" data-testid="audit-filter-portal">
          {['Semua', ...Object.keys(data.by_portal || {})].map(p => <option key={p} value={p}>{p}{p !== 'Semua' ? ` (${data.by_portal[p]})` : ''}</option>)}
        </select>
        <select value={status} onChange={e => setStatus(e.target.value)} className="border rounded px-2 py-1 bg-background" data-testid="audit-filter-status">
          {['Semua', 'selesai', 'diterima', 'terbuka'].map(s => <option key={s} value={s}>{s === 'Semua' ? 'Semua status' : STATUS_META[s].label}</option>)}
        </select>
      </div>
      <div className="overflow-x-auto rounded-xl border border-[var(--glass-border)]">
        <table className="w-full text-sm" data-testid="audit-findings-table">
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide">
            <tr><th className="p-2">ID</th><th className="p-2">Portal</th><th className="p-2">Temuan</th><th className="p-2">Tingkat</th><th className="p-2">Status</th><th className="p-2">Perbaikan</th><th className="p-2">Uji</th></tr>
          </thead>
          <tbody>
            {rows.map(f => {
              const m = STATUS_META[f.status] || STATUS_META.terbuka;
              return (
                <tr key={f.id} className="border-t border-[var(--glass-border)] align-top" data-testid={`audit-row-${f.id}`}>
                  <td className="p-2 font-mono text-xs whitespace-nowrap">{f.id}</td>
                  <td className="p-2 whitespace-nowrap">{f.portal}</td>
                  <td className="p-2 min-w-[220px]">{f.judul}<div className="text-[11px] text-muted-foreground">{f.berkas}</div></td>
                  <td className={`p-2 whitespace-nowrap ${TINGKAT_CLS[f.tingkat] || ''}`}>{f.tingkat}</td>
                  <td className="p-2 whitespace-nowrap"><span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${m.cls}`}><m.Icon className="w-3 h-3" />{m.label}</span></td>
                  <td className="p-2 min-w-[280px] text-xs">{f.perbaikan}</td>
                  <td className="p-2 text-xs whitespace-nowrap">{f.iterasi ? `iter ${f.iterasi}` : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
