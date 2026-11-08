import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, BookLock, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { journalSourceLabel } from '@/lib/financeLabels';
import { Notice, StatusBadge } from './moduleAtoms';
import { todayWIB } from '../../lib/waktu';

const BULAN_PENDEK = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

const fmt =(n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));

export function PeriodAlerts({ headers, onOpened }) {
  const [alerts, setAlerts] = useState([]);
  const load = useCallback(async () => {
    const r = await fetch('/api/rahaza/periods/alerts', { headers });
    if (r.ok) setAlerts((await r.json()).alerts || []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { load(); }, [load]);

  const openYear = async (y) => {
    const r = await fetch('/api/rahaza/periods/ensure-year', { method: 'POST', headers, body: JSON.stringify({ year: y }) });
    if (r.ok) { await load(); onOpened?.(y); } else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };
  const resolve = async (id) => {
    await fetch(`/api/rahaza/periods/alerts/${id}/resolve`, { method: 'POST', headers });
    load();
  };
  if (!alerts.length) return null;
  // 2026-11-08 (Standar UI/UX v2): kotak merah buatan sendiri → Notice; kode modul → label sumber jurnal.
  return (
    <Notice tone="danger" icon={AlertTriangle} testId="period-alerts-card" title={`${alerts.length} jurnal ditolak — periode belum dibuka`}>
      <div className="mt-1 divide-y divide-[var(--glass-border)]">
        {alerts.map(a => (
          <div key={a.id} className="flex flex-wrap items-center gap-3 py-2 text-sm text-foreground" data-testid={`period-alert-${a.id}`}>
            <div className="flex-1 min-w-[240px]">
              <div className="font-medium">Tahun {a.year} · {journalSourceLabel(a.source_module)} · {a.count}× ditolak</div>
              <div className="text-muted-foreground">{a.message}</div>
              {a.memo && <div className="text-muted-foreground">Terakhir: {a.memo}</div>}
            </div>
            <Button size="sm" onClick={() => openYear(a.year)} data-testid={`period-alert-open-${a.id}`}>Buka tahun {a.year}</Button>
            <Button size="sm" variant="outline" onClick={() => resolve(a.id)} data-testid={`period-alert-resolve-${a.id}`}>Abaikan</Button>
          </div>
        ))}
      </div>
    </Notice>
  );
}

export function YearEndClose({ headers, year, onDone }) {
  const [preview, setPreview] = useState(null);
  const [closings, setClosings] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [p, c] = await Promise.all([
      fetch(`/api/rahaza/year-end/preview?year=${year}`, { headers }),
      fetch('/api/rahaza/year-end', { headers }),
    ]);
    if (p.ok) setPreview(await p.json());
    if (c.ok) setClosings((await c.json()).closings || []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year]);
  useEffect(() => { load(); }, [load]);

  const doClose = async () => {
    if (!(await confirmDialog(`Tutup tahun ${year}? Semua akun laba rugi di-nol-kan dan laba bersih Rp ${fmt(preview.net_income)} dipindah ke Laba Ditahan (3-2000).`))) return;
    setBusy(true);
    const r = await fetch('/api/rahaza/year-end/close', { method: 'POST', headers, body: JSON.stringify({ year }) });
    setBusy(false);
    if (r.ok) { await load(); onDone?.(); } else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };
  const doReverse = async () => {
    if (!(await confirmDialog(`Batalkan jurnal penutup tahun ${year}?`))) return;
    const r = await fetch(`/api/rahaza/year-end/${year}/reverse`, { method: 'POST', headers });
    if (r.ok) { await load(); onDone?.(); } else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };
  if (!preview) return null;
  const closed = preview.already_closed;
  // 2026-11-02 (audit No.34): backend menolak tutup tahun sebelum 31 Desember lewat (WIB) —
  // rahaza_year_end.year_end_allowed. Tombol dinonaktifkan + alasan di tooltip.
  const yearNotEnded = Number(todayWIB().slice(0, 4)) <= Number(year);
  const yearBlockReason = yearNotEnded
    ? `Tahun ${year} belum berakhir. Tutup tahun hanya boleh setelah 31 Desember ${year} (WIB).` : '';
  const CLOSING_STATUS = { posted: 'terposting', reversed: 'dibatalkan', voided: 'dibatalkan', draft: 'draf' };
  // 2026-11-08 (Standar UI/UX v2): tanpa kotak abu & lencana KAPITAL berwarna ungu; status = StatusBadge; huruf 12–16 px.
  return (
    <GlassCard className="p-4 space-y-3" data-testid="year-end-card">
      <div className="flex flex-wrap items-center gap-3">
        <BookLock className="w-4 h-4 text-muted-foreground" />
        <p className="text-base font-semibold">Tutup tahun {year}</p>
        <span data-testid="year-end-status">
          <StatusBadge status={closed ? 'closed' : 'open'} tone={closed ? 'success' : 'muted'}
            label={closed ? `Sudah ditutup · ${preview.existing_je?.je_number || ''}` : 'Belum ditutup'} />
        </span>
        <div className="ml-auto flex gap-2">
          {!closed && (
            <span title={yearBlockReason || undefined} className="inline-flex" data-testid="year-end-close-wrap">
              <Button size="sm" disabled={!preview.can_close || busy || yearNotEnded} onClick={doClose} data-testid="year-end-close-btn">Tutup tahun {year}</Button>
            </span>
          )}
          {closed && <Button size="sm" variant="destructive" onClick={doReverse} data-testid="year-end-reverse-btn"><Undo2 className="w-3.5 h-3.5 mr-1" />Batalkan penutupan</Button>}
        </div>
      </div>
      <dl className="grid sm:grid-cols-3 gap-3 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Laba (rugi) bersih {year}</dt>
          <dd className="text-base font-semibold tabular-nums" data-testid="year-end-net-income">Rp {fmt(preview.net_income)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Akun laba rugi bersaldo</dt>
          <dd className="text-base font-semibold">{preview.lines?.length || 0} akun</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Periode belum ditutup</dt>
          <dd className={`text-base font-semibold ${preview.open_periods?.length ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--success-text))]'}`} data-testid="year-end-open-periods">
            {preview.open_periods?.length ? `${preview.open_periods.length} bulan (${preview.open_periods.map(p => BULAN_PENDEK[Number(p.slice(5)) - 1] || p.slice(5)).join(', ')})` : 'Semua sudah ditutup'}
          </dd>
        </div>
      </dl>
      {!closed && (!preview.can_close || yearNotEnded) && (
        <p className="text-xs text-muted-foreground" data-testid="year-end-requirements">
          Syarat: tahun {year} sudah berakhir (setelah 31 Desember, WIB), 12 periode ditutup/dikunci, ada saldo laba rugi, akun Laba Ditahan {preview.retained_earnings_account} aktif.
        </p>
      )}
      {closings.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="year-end-history">
          Riwayat: {closings.map(c => `${c.year} → ${c.je_number} (${CLOSING_STATUS[c.status] || c.status}, Rp ${fmt(c.net_income)})`).join(' · ')}
        </p>
      )}
    </GlassCard>
  );
}
