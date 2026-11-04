import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, CalendarRange, Lock, LockOpen, ShieldCheck } from 'lucide-react';
import { formatDateID } from '@/lib/format';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { StatusBadge as ModuleStatusBadge, PageHeader } from './moduleAtoms';
import { PeriodAlerts, YearEndClose } from './RahazaPeriodsExtras';
import { thisMonthWIB } from '../../lib/waktu';

// 2026-11-02 (audit No.34): backend kini menolak tutup/kunci periode yang BELUM berakhir (WIB)
// — rahaza_periods.period_not_ended_error. Tombolnya dinonaktifkan di sini + alasan di tooltip,
// supaya pengguna tidak menekan tombol yang pasti ditolak.
function periodNotEndedReason(periodCode, thisMonth = thisMonthWIB()) {
  if (!periodCode || periodCode < thisMonth) return '';
  return `Periode ${periodCode} belum berakhir (WIB). Tutup/kunci hanya boleh setelah tanggal terakhir periode ini lewat.`;
}


const STATUS_LABEL = { open: 'Terbuka', closed: 'Ditutup', locked: 'Dikunci' };
const MONTHS_ID = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const periodLabelID = (code) => { const [y, m] = String(code).split('-'); return `${MONTHS_ID[Number(m) - 1] || m} ${y}`; };

function StatusBadge({ status }) {
  const tone = { open: 'success', closed: 'warning', locked: 'danger' }[status];
  return <ModuleStatusBadge status={status} tone={tone} label={STATUS_LABEL[status] || status} />;
}

export default function RahazaPeriodsModule({ token }) {
  const [periods, setPeriods] = useState([]);
  const [loading, setLoading] = useState(true);
  const [year, setYear] = useState(new Date().getFullYear());
  const [policy, setPolicy] = useState(null);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const thisMonth = thisMonthWIB();

  useEffect(() => {
    fetch('/api/rahaza/periods/policy', { headers }).then(r => r.ok ? r.json() : null).then(setPolicy).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/periods?year=${year}`, { headers });
      if (r.ok) setPeriods(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, year]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const ensureYear = async () => {
    const r = await fetch('/api/rahaza/periods/ensure-year', { method: 'POST', headers, body: JSON.stringify({ year }) });
    if (r.ok) { fetchData(); } else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };

  const act = async (code, action) => {
    const verb = { close: 'tutup', reopen: 'buka kembali', lock: 'kunci final' }[action];
    if (!(await confirmDialog(`${verb.charAt(0).toUpperCase() + verb.slice(1)} periode ${code}?`))) return;
    const r = await fetch(`/api/rahaza/periods/${code}/${action}`, { method: 'POST', headers });
    if (r.ok) { fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Error'); }
  };

  return (
    <div className="space-y-5" data-testid="rahaza-periods-page">
      <PageHeader
        icon={CalendarRange}
        title="Periode Akuntansi (Fiscal Periods)"
        subtitle="Kelola periode bulanan: Open (default), Closed (stop posting), Locked (final audit, irreversible). Periode closed/locked memblokir posting jurnal di tanggal tersebut."
        actions={
          <>
            <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="pr-refresh"><RefreshCw className="w-3.5 h-3.5" /></Button>
            <Button onClick={ensureYear} data-testid="pr-ensure">Generate {year}</Button>
          </>
        }
      />

      <PeriodAlerts headers={headers} onOpened={(y) => { if (y === year) fetchData(); }} />
      <YearEndClose key={`ye-${year}-${periods.map(p => p.status).join('')}`} headers={headers} year={year} onDone={fetchData} />

      <GlassCard className="p-4">
        {policy && (
          <p className="mb-4 text-xs text-muted-foreground" data-testid="pr-policy-banner">
            <span className="font-semibold text-foreground">Aturan posting:</span> jurnal ditolak bila tanggalnya lebih dari {policy.future_days_max} hari ke depan;
            periode tahun {policy.auto_years?.[0]}–{policy.auto_years?.[policy.auto_years.length - 1]} dibuka otomatis saat posting pertama;
            tahun lain harus di-<em>Generate</em> di sini dulu. Periode <em>closed/locked</em> selalu memblokir posting.
          </p>
        )}
        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs text-muted-foreground">Tahun:</span>
          <GlassInput type="number" value={year} onChange={e => setYear(Number(e.target.value) || year)} className="h-8 w-24" data-testid="pr-year" />
        </div>
        {loading ? (
          <div className="py-10 text-center text-muted-foreground">Memuat…</div>
        ) : periods.length === 0 ? (
          <div className="py-10 text-center space-y-3">
            <div className="text-muted-foreground">Periode tahun {year} belum dibuat.</div>
            <Button onClick={ensureYear} data-testid="pr-ensure-empty">Buat periode {year}</Button>
          </div>
        ) : (
          <div className="overflow-x-auto -mx-4">
            <table className="w-full" data-testid="pr-table">
              <thead><tr><th className="text-left">Periode</th><th className="text-left">Status</th><th className="text-left">Ditutup / dikunci</th><th className="text-right">Aksi</th></tr></thead>
              <tbody>
                {periods.map(p => {
                  const blockReason = periodNotEndedReason(p.period_code, thisMonth);
                  return (
                    <tr key={p.period_code} data-testid={`pr-card-${p.period_code}`}>
                      <td className="text-foreground font-medium whitespace-nowrap">{periodLabelID(p.period_code)}</td>
                      <td><StatusBadge status={p.status} /></td>
                      <td className="text-xs text-muted-foreground">
                        {p.locked_at ? `Dikunci ${formatDateID(p.locked_at)} · ${p.locked_by_name || '-'}`
                          : p.closed_at ? `Ditutup ${formatDateID(p.closed_at)} · ${p.closed_by_name || '-'}`
                            : blockReason ? <span data-testid={`pr-not-ended-${p.period_code}`}>Belum berakhir</span> : '—'}
                      </td>
                      <td className="text-right whitespace-nowrap">
                        {p.status === 'open' && (
                          <span title={blockReason || undefined} className="inline-flex" data-testid={`pr-close-wrap-${p.period_code}`}>
                            <Button size="sm" variant="outline" disabled={!!blockReason} onClick={() => act(p.period_code, 'close')} data-testid={`pr-close-${p.period_code}`}>
                              <Lock className="w-3.5 h-3.5" />Tutup
                            </Button>
                          </span>
                        )}
                        {p.status === 'closed' && (
                          <span className="inline-flex gap-1.5">
                            <Button size="sm" variant="outline" onClick={() => act(p.period_code, 'reopen')} data-testid={`pr-reopen-${p.period_code}`}>
                              <LockOpen className="w-3.5 h-3.5" />Buka lagi
                            </Button>
                            <span title={blockReason || undefined} className="inline-flex" data-testid={`pr-lock-wrap-${p.period_code}`}>
                              <Button size="sm" variant="outline" disabled={!!blockReason} onClick={() => act(p.period_code, 'lock')} className="text-[hsl(var(--destructive))]" data-testid={`pr-lock-${p.period_code}`}>
                                <ShieldCheck className="w-3.5 h-3.5" />Kunci final
                              </Button>
                            </span>
                          </span>
                        )}
                        {p.status === 'locked' && <span className="text-xs text-muted-foreground">Terkunci permanen</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
