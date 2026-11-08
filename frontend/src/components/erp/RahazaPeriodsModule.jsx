import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, CalendarRange, Lock, LockOpen, ShieldCheck } from 'lucide-react';
import { formatDateID } from '@/lib/format';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { StatusBadge as ModuleStatusBadge, EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { PeriodAlerts, YearEndClose } from './RahazaPeriodsExtras';
import { thisMonthWIB } from '../../lib/waktu';

// 2026-11-02 (audit No.34): backend kini menolak tutup/kunci periode yang BELUM berakhir (WIB)
// — rahaza_periods.period_not_ended_error. Tombolnya dinonaktifkan di sini + alasan di tooltip,
// supaya pengguna tidak menekan tombol yang pasti ditolak.
function periodNotEndedReason(periodCode, thisMonth = thisMonthWIB()) {
  if (!periodCode || periodCode < thisMonth) return '';
  return `Periode ${periodLabelID(periodCode)} belum berakhir (WIB). Tutup/kunci hanya boleh setelah tanggal terakhir periode ini lewat.`;
}


const STATUS_LABEL = { open: 'Terbuka', closed: 'Ditutup', locked: 'Dikunci' };
const MONTHS_ID = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
function periodLabelID(code) { const [y, m] = String(code).split('-'); return `${MONTHS_ID[Number(m) - 1] || m} ${y}`; }

function StatusBadge({ status }) {
  const tone = { open: 'success', closed: 'warning', locked: 'danger' }[status];
  return <ModuleStatusBadge status={status} tone={tone} label={STATUS_LABEL[status] || status} />;
}

/**
 * Tutup buku (menu Akuntansi › Akrual & Tutup Buku › Tutup buku).
 * 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout — pilihan tahun di toolbar, aturan posting & peringatan di
 * ringkasan; tanpa istilah Inggris ("Generate", "closed/locked").
 * 2026-11-08 (Standar UI/UX v2): daftar periode bisa diunduh Excel/CSV; "Kunci final" merah; huruf standar.
 */
export default function RahazaPeriodsModule({ token }) {
  const [periods, setPeriods] = useState([]);
  const [loading, setLoading] = useState(true);
  const [year, setYear] = useState(new Date().getFullYear());
  const [policy, setPolicy] = useState(null);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const thisMonth = thisMonthWIB();
  const nowYear = Number(thisMonth.slice(0, 4));
  const yearOptions = [];
  for (let y = Math.min(nowYear - 5, year); y <= Math.max(nowYear + 2, year); y++) yearOptions.push(y);

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
    if (r.ok) { fetchData(); } else { const e = await r.json(); toast.error(e.detail || 'Gagal membuat periode'); }
  };

  const act = async (code, action) => {
    const verb = { close: 'Tutup', reopen: 'Buka kembali', lock: 'Kunci final' }[action];
    if (!(await confirmDialog({ title: `${verb} periode ${periodLabelID(code)}?`, confirmLabel: verb, danger: action === 'lock' }))) return;
    const r = await fetch(`/api/rahaza/periods/${code}/${action}`, { method: 'POST', headers });
    if (r.ok) { fetchData(); }
    else { const e = await r.json(); toast.error(e.detail || 'Gagal'); }
  };

  return (
    <PageLayout
      testId="rahaza-periods-page"
      title="Tutup buku"
      subtitle="Periode bulanan: terbuka, ditutup (jurnal ditolak), atau dikunci final untuk audit."
      actions={<Button variant="outline" onClick={ensureYear} data-testid="pr-ensure">Lengkapi periode {year}</Button>}
      filters={
        <SmartNativeSelect value={String(year)} onChange={e => setYear(Number(e.target.value) || year)} searchable={false}
          className="h-9 w-32" aria-label="Tahun" data-testid="pr-year">
          {yearOptions.map(y => <option key={y} value={String(y)}>{y}</option>)}
        </SmartNativeSelect>
      }
      tools={<>
        <TombolUnduh namaBerkas={`periode-buku-${year}`} namaLembar={`Periode ${year}`} baris={periods} testId="pr-unduh"
          kolom={[
            { label: 'Periode', nilai: (p) => periodLabelID(p.period_code) },
            { label: 'Status', nilai: (p) => STATUS_LABEL[p.status] || p.status },
            { label: 'Ditutup', nilai: (p) => (p.closed_at ? `${formatDateID(p.closed_at)} · ${p.closed_by_name || '-'}` : '') },
            { label: 'Dikunci', nilai: (p) => (p.locked_at ? `${formatDateID(p.locked_at)} · ${p.locked_by_name || '-'}` : '') },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="pr-refresh"><RefreshCw className="w-4 h-4" /></Button>
      </>}
      summary={<>
        {policy && (
          <p className="text-sm text-muted-foreground" data-testid="pr-policy-banner">
            <span className="font-semibold text-foreground">Aturan posting:</span> jurnal ditolak bila tanggalnya lebih dari {policy.future_days_max} hari ke depan;
            periode tahun {policy.auto_years?.[0]}–{policy.auto_years?.[policy.auto_years.length - 1]} dibuka otomatis saat jurnal pertama;
            tahun lain harus dibuat di sini dulu. Periode yang ditutup atau dikunci selalu menolak jurnal.
          </p>
        )}
        <PeriodAlerts headers={headers} onOpened={(y) => { if (y === year) fetchData(); }} />
        <YearEndClose key={`ye-${year}-${periods.map(p => p.status).join('')}`} headers={headers} year={year} onDone={fetchData} />
      </>}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : periods.length === 0 ? (
          <EmptyState icon={CalendarRange} title={`Periode tahun ${year} belum dibuat`}
            description="Buat 12 periode bulanan supaya jurnal tahun ini bisa dicatat."
            action={<Button onClick={ensureYear} data-testid="pr-ensure-empty">Buat periode {year}</Button>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="pr-table">
              <thead><tr><th className="text-left">Periode</th><th className="text-left">Status</th><th className="text-left">Ditutup / dikunci</th><th className="text-right">Aksi</th></tr></thead>
              <tbody>
                {periods.map(p => {
                  const blockReason = periodNotEndedReason(p.period_code, thisMonth);
                  return (
                    <tr key={p.period_code} data-testid={`pr-card-${p.period_code}`}>
                      <td className="text-foreground font-medium whitespace-nowrap">{periodLabelID(p.period_code)}</td>
                      <td><StatusBadge status={p.status} /></td>
                      <td className="text-muted-foreground">
                        {p.locked_at ? `Dikunci ${formatDateID(p.locked_at)} · ${p.locked_by_name || '-'}`
                          : p.closed_at ? `Ditutup ${formatDateID(p.closed_at)} · ${p.closed_by_name || '-'}`
                            : blockReason ? <span data-testid={`pr-not-ended-${p.period_code}`}>Belum berakhir</span> : '—'}
                      </td>
                      <td className="text-right whitespace-nowrap">
                        {p.status === 'open' && (
                          <span title={blockReason || undefined} className="inline-flex" data-testid={`pr-close-wrap-${p.period_code}`}>
                            <Button size="sm" variant="outline" disabled={!!blockReason} onClick={() => act(p.period_code, 'close')} data-testid={`pr-close-${p.period_code}`}>
                              <Lock className="w-4 h-4" />Tutup
                            </Button>
                          </span>
                        )}
                        {p.status === 'closed' && (
                          <span className="inline-flex gap-1.5">
                            <Button size="sm" variant="outline" onClick={() => act(p.period_code, 'reopen')} data-testid={`pr-reopen-${p.period_code}`}>
                              <LockOpen className="w-4 h-4" />Buka lagi
                            </Button>
                            <span title={blockReason || undefined} className="inline-flex" data-testid={`pr-lock-wrap-${p.period_code}`}>
                              <Button size="sm" variant="destructive" disabled={!!blockReason} onClick={() => act(p.period_code, 'lock')} data-testid={`pr-lock-${p.period_code}`}>
                                <ShieldCheck className="w-4 h-4" />Kunci final
                              </Button>
                            </span>
                          </span>
                        )}
                        {p.status === 'locked' && <span className="text-sm text-muted-foreground">Terkunci permanen</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}
