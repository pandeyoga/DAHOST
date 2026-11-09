/**
 * Dashboard SDM — ringkasan karyawan & kehadiran hari ini (GET /api/rahaza/hr/dashboard).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, kartu angka StatTile dengan keterangan, daftar = tabel
 * + unduh Excel/CSV, warna token (dulu hex per status), satu gaya kartu.
 * Label yang diluruskan: "Sebaran per jabatan" → per departemen (server mengelompokkan per departemen);
 * "Lainnya" = karyawan tanpa departemen; "Alfa (7 hari)" = jumlah catatan alfa (orang × hari).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Skeleton } from '@/components/ui/skeleton';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatRupiah, formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const fmtDate = (d) => (d ? formatDateID(d) : '—');

const STATUS = {
  hadir: { label: 'Hadir', warna: 'hsl(var(--success))', tone: 'success' },
  izin:  { label: 'Izin',  warna: 'hsl(var(--warning))', tone: 'warning' },
  sakit: { label: 'Sakit', warna: 'hsl(var(--info))', tone: 'info' },
  alfa:  { label: 'Alfa',  warna: 'hsl(var(--destructive))', tone: 'danger' },
  cuti:  { label: 'Cuti',  warna: 'hsl(var(--primary))', tone: 'primary' },
  libur: { label: 'Libur', warna: 'hsl(var(--muted-foreground))', tone: 'muted' },
};
const RUN_STATUS = { finalized: { label: 'Final', tone: 'success' }, draft: { label: 'Draf', tone: 'muted' } };
const labelDept = (d) => (!d || d === 'Lainnya' ? 'Tanpa departemen' : d);

function KehadiranHariIni({ data, total }) {
  return (
    <div className="space-y-2">
      {Object.entries(STATUS).map(([k, s]) => {
        const val = data[k] || 0;
        const pct = total > 0 ? Math.round((val / total) * 100) : 0;
        return (
          <div key={k} className="flex items-center gap-3">
            <span className="w-14 shrink-0 text-sm text-muted-foreground">{s.label}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--glass-border)]">
              <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: s.warna }} />
            </div>
            <span className="w-8 text-right text-sm font-medium tabular-nums text-foreground">{val}</span>
          </div>
        );
      })}
    </div>
  );
}

function Bagian({ judul, keterangan, alat, children, testId }) {
  return (
    <GlassCard hover={false} className="space-y-3 p-4" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-base font-semibold text-foreground">{judul}</p>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {alat}
      </div>
      {children}
    </GlassCard>
  );
}

export default function HRDashboard({ token }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const fetchDashboard = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/rahaza/hr/dashboard`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchDashboard(); }, [fetchDashboard]);

  const hariIni = new Date().toLocaleDateString('id-ID', { timeZone: 'Asia/Jakarta', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const muatUlang = (
    <Button variant="outline" size="icon" onClick={fetchDashboard} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
      data-testid="hr-dashboard-refresh">
      <RefreshCw className={loading ? 'animate-spin' : ''} />
    </Button>
  );
  const layout = (children, summary) => (
    <PageLayout testId="hr-dashboard" title="Dashboard SDM" subtitle={`Ringkasan karyawan dan kehadiran — ${hariIni}.`}
      tools={muatUlang} summary={summary}>
      {children}
    </PageLayout>
  );

  if (loading && !data) return layout(
    <div className="space-y-4" data-testid="hr-dashboard-skeleton">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Skeleton className="h-52 rounded-xl" />
        <Skeleton className="h-52 rounded-xl" />
      </div>
    </div>
  );

  if (error && !data) return layout(
    <EmptyState icon={AlertTriangle} title="Dashboard gagal dimuat" description={`Server menjawab: ${error}. Coba muat ulang.`}
      action={<Button variant="outline" onClick={fetchDashboard}>Coba lagi</Button>} />
  );

  const att = data?.attendance_today || {};
  const total = data?.total_employees || 0;
  const run   = data?.latest_payroll_run;
  const tren  = data?.attendance_trend || [];
  const terbaru = data?.recent_attendance || [];
  const dept = data?.dept_breakdown || [];
  const runStatus = RUN_STATUS[run?.status] || { label: run?.status ? 'Diproses' : '—', tone: 'warning' };

  return layout(
    <>
      {/* Baris 1: kehadiran hari ini + sebaran departemen (tabel di atas — isi utama tidak terdorong ke bawah) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Bagian judul="Kehadiran hari ini" keterangan={`${att.recorded || 0} dari ${total} karyawan aktif sudah tercatat.`}>
          <KehadiranHariIni data={att} total={total} />
          {att.not_recorded > 0 && (
            <p className="flex items-center gap-1 text-sm text-[hsl(var(--warning-text))]">
              <AlertTriangle className="h-4 w-4" />
              {att.not_recorded} karyawan belum dicatat kehadirannya hari ini
            </p>
          )}
        </Bagian>

        {/* Sebaran per departemen */}
        <Bagian judul="Karyawan per departemen"
          keterangan={dept.length >= 8 ? '8 departemen dengan karyawan aktif terbanyak.' : 'Karyawan aktif menurut departemen.'}
          alat={<TombolUnduh namaBerkas="karyawan-per-departemen" namaLembar="Per departemen" baris={dept} testId="hr-dashboard-unduh-dept"
            kolom={[{ label: 'Departemen', nilai: (d) => labelDept(d.dept) }, { label: 'Karyawan aktif', nilai: (d) => d.count }]} />}>
          <TabelData baris={dept} kunci={(d) => d.dept || 'tanpa'} testId="hr-dashboard-dept"
            kolom={[
              { kunci: 'dept', label: 'Departemen', hp: 'judul', isi: (d) => <span className="text-foreground">{labelDept(d.dept)}</span> },
              { kunci: 'jumlah', label: 'Karyawan aktif', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.count}</span> },
              { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (d) => <span className="tabular-nums text-muted-foreground">{total ? Math.round((d.count / total) * 100) : 0}%</span> },
            ]}
            kosong={<EmptyState className="py-8" title="Belum ada karyawan aktif" />} />
        </Bagian>
      </div>

      {/* Baris 2: tren 7 hari + kehadiran terbaru */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Bagian judul="Tren kehadiran 7 hari" keterangan="Jumlah karyawan hadir per hari.">
          {tren.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={tren} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--glass-border)" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }}
                  tickFormatter={(d) => (d ? `${d.slice(8, 10)}/${d.slice(5, 7)}` : '')} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} />
                <Tooltip formatter={(v) => [v, 'Hadir']} labelFormatter={(d) => fmtDate(d)}
                  contentStyle={{ background: 'var(--card-surface)', border: '1px solid var(--glass-border)', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="hadir" fill="hsl(var(--success))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState className="py-8" title="Belum ada data absensi 7 hari terakhir" description="Grafik muncul setelah ada catatan hadir." />
          )}
        </Bagian>
        {/* Kehadiran terbaru */}
        <Bagian judul="Kehadiran terbaru" keterangan="10 catatan kehadiran yang terakhir masuk."
          alat={<TombolUnduh namaBerkas="kehadiran-terbaru" namaLembar="Kehadiran" baris={terbaru} testId="hr-dashboard-unduh-kehadiran"
            kolom={[
              { label: 'Karyawan', nilai: (r) => r.employee_name || '' },
              { label: 'Tanggal', nilai: (r) => fmtDate(r.date) },
              { label: 'Status', nilai: (r) => STATUS[r.status]?.label || r.status || '' },
              { label: 'Jam kerja', nilai: (r) => r.hours_worked ?? '' },
            ]} />}>
          <TabelData baris={terbaru} kunci={(r) => `${r.employee_id}-${r.date}`} testId="hr-dashboard-recent"
            kolom={[
              { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (r) => <span className="font-medium text-foreground">{r.employee_name || '—'}</span> },
              { kunci: 'tanggal', label: 'Tanggal', isi: (r) => <span className="text-sm">{fmtDate(r.date)}</span> },
              { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={STATUS[r.status]?.label} tone={STATUS[r.status]?.tone} /> },
              { kunci: 'jam', label: 'Jam kerja', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.hours_worked > 0 ? `${r.hours_worked} jam` : '—'}</span> },
            ]}
            kosong={<EmptyState className="py-8" title="Belum ada catatan kehadiran" description="Catatan absen terbaru akan tampil di sini." />} />
        </Bagian>

      </div>

      {/* Penggajian terbaru */}
      {run && (
        <Bagian judul="Penggajian terbaru" keterangan="Proses gaji yang paling akhir dibuat.">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-muted-foreground">Periode</p>
              <p className="text-sm font-medium text-foreground">{fmtDate(run.period_from)} — {fmtDate(run.period_to)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Status</p>
              <StatusBadge status={run.status} label={runStatus.label} tone={runStatus.tone} />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Total gaji bersih</p>
              {/* 2026-11-09 (Q8): total gaji hanya untuk peran penggajian/Keuangan — server tidak mengirimnya ke peran lain. */}
              <p className="text-sm font-semibold tabular-nums text-foreground">
                {run.total_net == null && run.total_payout == null ? 'Khusus penggajian' : formatRupiah(run.total_net ?? run.total_payout)}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Jumlah karyawan</p>
              <p className="text-sm font-medium tabular-nums text-foreground">{run.total_employees ?? run.employee_count ?? '—'}</p>
            </div>
          </div>
        </Bagian>
      )}

    </>,
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile label="Karyawan aktif" value={total} sub="Berstatus aktif di data karyawan." />
      <StatTile label="Hadir hari ini" value={att.hadir || 0}
        sub={!total ? 'Belum ada karyawan aktif.' : att.recorded ? `${att.attendance_rate || 0}% dari ${total} karyawan aktif.` : 'Belum ada catatan absen hari ini.'} />
      <StatTile label="Belum absen hari ini" value={att.not_recorded || 0} accent={att.not_recorded ? 'warning' : 'default'}
        sub="Belum ada catatan kehadiran hari ini." />
      <StatTile label="Alfa 7 hari terakhir" value={data?.alfa_last_7d || 0} accent={data?.alfa_last_7d ? 'danger' : 'default'}
        sub="Jumlah catatan alfa (orang × hari)." />
    </div>
  );
}
