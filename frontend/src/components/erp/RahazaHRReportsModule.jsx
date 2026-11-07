/**
 * Laporan SDM — kehadiran, lembur, penggajian, dan karyawan keluar-masuk per periode.
 *
 * Standar UI/UX v2 (8 Nov 2026): tab halaman (HubTabs) + cetakan PageLayout, penyaring satu baris (periode =
 * pilihan cepat + pemilih tanggal seragam, bukan input tanggal bawaan), tabel standar + unduh Excel/CSV,
 * kartu angka StatTile dengan keterangan, warna token, bahasa Indonesia.
 * Label yang diluruskan: "Rp 3,2M" dulu berarti JUTA (M = miliar dalam bahasa Indonesia) → "Rp 3,2 jt";
 * "Total Hadir" = hari hadir (orang × hari); tingkat keluar = keluar ÷ karyawan aktif saat ini (perkiraan server).
 * Grafik pai "kotor vs potongan" disembunyikan: potongan adalah bagian dari kotor, persentasenya menyesatkan.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileSpreadsheet } from 'lucide-react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatDateID, formatRupiah, formatRupiahShort } from '@/lib/format';
import { PERIOD_PRESETS, periodFromPreset } from './finance/PeriodPicker';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import { EmptyState, StatTile } from './moduleAtoms';

const API_BASE = process.env.REACT_APP_BACKEND_URL;

const WARNA = {
  hadir: 'hsl(var(--success))', izin: 'hsl(var(--warning))', sakit: 'hsl(var(--info))',
  cuti: 'hsl(var(--primary))', alfa: 'hsl(var(--destructive))',
};
const SUMBU = { fontSize: 12, fill: 'hsl(var(--muted-foreground))' };
const TOOLTIP = { background: 'var(--card-surface)', border: '1px solid var(--glass-border)', borderRadius: 8, fontSize: 12 };
const tglPendek = (d) => (d ? `${String(d).slice(8, 10)}/${String(d).slice(5, 7)}` : '');
const fmtDate = (d) => (d ? formatDateID(d) : '—');
const angka = (v) => Number(v || 0).toLocaleString('id-ID');

/** Isi satu tab: cetakan PageLayout di dalam hub (judul hub di atas). */
function IsiTab({ filters, tools, summary, children }) {
  return <PageLayout filters={filters} tools={tools} summary={summary}>{children}</PageLayout>;
}

function Bagian({ judul, alat, children }) {
  return (
    <GlassCard hover={false} className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-base font-semibold text-foreground">{judul}</p>
        {alat}
      </div>
      {children}
    </GlassCard>
  );
}

const kolomKaryawan = { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (e) => (
  <div className="min-w-0">
    <p className="font-medium text-foreground">{e.employee_name || e.name || '—'}</p>
    <p className="text-xs text-muted-foreground">{e.employee_code || ''}</p>
  </div>) };
const kolomDept = { kunci: 'dept', label: 'Departemen', isi: (e) => <span className="text-sm">{e.department_name || '—'}</span> };
const kanan = (kunci, label, isi) => ({ kunci, label, rata: 'kanan', isi: (e) => <span className="tabular-nums">{isi(e)}</span> });

export default function RahazaHRReportsModule({ token }) {
  const [activeTab, setActiveTab] = useState('attendance');
  const [loading, setLoading] = useState(false);

  // Filters
  const [periode, setPeriode] = useState(() => periodFromPreset('month'));
  const dateFrom = periode.from;
  const dateTo = periode.to;
  const [departmentId, setDepartmentId] = useState('');
  const [locationId, setLocationId] = useState('');
  const [shiftId, setShiftId] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [periodCode, setPeriodCode] = useState('');

  // Master data
  const [departments, setDepartments] = useState([]);
  const [locations, setLocations] = useState([]);
  const [shifts, setShifts] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [payrollRuns, setPayrollRuns] = useState([]);

  // Report data
  const [attendanceData, setAttendanceData] = useState(null);
  const [overtimeData, setOvertimeData] = useState(null);
  const [payrollData, setPayrollData] = useState(null);
  const [turnoverData, setTurnoverData] = useState(null);

  // Fetch master data
  useEffect(() => {
    const fetchMasterData = async () => {
      try {
        const [locRes, shiftRes, empRes, payrollRes] = await Promise.all([
          fetch(`${API_BASE}/api/rahaza/locations`, { headers: { Authorization: `Bearer ${token}` } }),
          fetch(`${API_BASE}/api/rahaza/shifts`, { headers: { Authorization: `Bearer ${token}` } }),
          fetch(`${API_BASE}/api/rahaza/employees?limit=500`, { headers: { Authorization: `Bearer ${token}` } }),
          fetch(`${API_BASE}/api/rahaza/payroll-runs`, { headers: { Authorization: `Bearer ${token}` } }),
        ]);

        if (locRes.ok) {
          const data = await locRes.json();
          setLocations(Array.isArray(data) ? data : data.items || []);
        }
        if (shiftRes.ok) {
          const data = await shiftRes.json();
          setShifts(Array.isArray(data) ? data : data.items || []);
        }
        if (empRes.ok) {
          const data = await empRes.json();
          const emps = Array.isArray(data) ? data : data.items || [];
          setEmployees(emps.filter(e => e.active));
          // 2026-11-06 (pola P3): departemen = nama di master karyawan (dulu daftar ini diisi LOKASI)
          const names = [...new Set(emps.map(e => (e.department || '').trim()).filter(Boolean))].sort();
          setDepartments(names.map(n => ({ id: n, name: n })));
        }
        if (payrollRes.ok) {
          const data = await payrollRes.json();
          setPayrollRuns(Array.isArray(data) ? data : data.items || []);
        }
      } catch (e) {
        console.error('Failed to fetch master data:', e);
      }
    };
    fetchMasterData();
  }, [token]);

  const buatParams = useCallback(() => {
    const params = new URLSearchParams();
    if (dateFrom) params.append('from_date', dateFrom);
    if (dateTo) params.append('to_date', dateTo);
    if (departmentId) params.append('department_id', departmentId);
    if (locationId) params.append('location_id', locationId);
    if (shiftId) params.append('shift_id', shiftId);
    if (employeeId) params.append('employee_id', employeeId);
    if (periodCode) params.append('period_code', periodCode);
    return params;
  }, [dateFrom, dateTo, departmentId, locationId, shiftId, employeeId, periodCode]);

  const ENDPOINT = { attendance: 'attendance-summary', overtime: 'overtime-summary', payroll: 'payroll-summary', turnover: 'turnover' };

  // Fetch report data based on active tab
  const fetchReportData = useCallback(async () => {
    const ep = ENDPOINT[activeTab];
    if (!ep) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/rahaza/hr/reports/${ep}?${buatParams()}`,
        { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
      if (res.ok) {
        const data = await res.json();
        if (activeTab === 'attendance') setAttendanceData(data);
        else if (activeTab === 'overtime') setOvertimeData(data);
        else if (activeTab === 'payroll') setPayrollData(data);
        else setTurnoverData(data);
      } else {
        toast.error('Gagal memuat data laporan');
      }
    } catch (e) {
      console.error('Failed to fetch report:', e);
      toast.error('Terjadi kesalahan saat memuat laporan');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, buatParams, token]);

  useEffect(() => {
    fetchReportData();
  }, [fetchReportData]);

  // Excel lengkap buatan server (dengan baris ringkasan) — tetap tersedia di samping unduhan tabel.
  const exportExcel = async () => {
    const ep = ENDPOINT[activeTab];
    if (!ep) return;
    try {
      const res = await fetch(`${API_BASE}/api/rahaza/hr/reports/${ep}.xlsx?${buatParams()}`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `hr_report_${activeTab}_${dateFrom}_${dateTo}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        toast.success('Berkas Excel berhasil diunduh');
      } else {
        toast.error('Gagal mengunduh Excel');
      }
    } catch (e) {
      console.error('Export failed:', e);
      toast.error('Terjadi kesalahan saat mengunduh');
    }
  };

  // ─── Penyaring (satu baris) ───
  const penyaring = (
    <>
      <SmartNativeSelect value={periode.preset || 'custom'} searchable={false} className="w-40" aria-label="Periode"
        onChange={(e) => setPeriode(periodFromPreset(e.target.value, periode))} data-testid="filter-period-preset">
        {PERIOD_PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
      </SmartNativeSelect>
      {periode.preset === 'custom' ? (
        <>
          <div className="w-36"><DatePicker value={dateFrom} max={dateTo || undefined} bolehKosong={false} testId="filter-date-from"
            onChange={(v) => setPeriode((p) => ({ ...p, preset: 'custom', from: v }))} /></div>
          <span className="text-sm text-muted-foreground">s/d</span>
          <div className="w-36"><DatePicker value={dateTo} min={dateFrom || undefined} bolehKosong={false} testId="filter-date-to"
            onChange={(v) => setPeriode((p) => ({ ...p, preset: 'custom', to: v }))} /></div>
        </>
      ) : null}
      <SmartNativeSelect value={departmentId} onChange={e => setDepartmentId(e.target.value)} className="w-48" data-testid="filter-department">
        <option value="">Semua departemen</option>
        {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
      </SmartNativeSelect>
      <SmartNativeSelect value={locationId} onChange={e => setLocationId(e.target.value)} className="w-40" data-testid="filter-location">
        <option value="">Semua lokasi</option>
        {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
      </SmartNativeSelect>
      {activeTab !== 'turnover' && (
        <>
          <SmartNativeSelect value={shiftId} onChange={e => setShiftId(e.target.value)} className="w-40" data-testid="filter-shift">
            <option value="">Semua shift</option>
            {shifts.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect value={employeeId} onChange={e => setEmployeeId(e.target.value)} className="w-44" data-testid="filter-employee">
            <option value="">Semua karyawan</option>
            {employees.map(emp => <option key={emp.id} value={emp.id}>{`${emp.employee_code} - ${emp.name}`}</option>)}
          </SmartNativeSelect>
        </>
      )}
      {activeTab === 'payroll' && (
        <SmartNativeSelect value={periodCode} onChange={e => setPeriodCode(e.target.value)} className="w-52" data-testid="filter-period">
          <option value="">Periode gaji terakhir</option>
          {payrollRuns.map(pr => <option key={pr.id} value={pr.period_code}>{pr.period_code}</option>)}
        </SmartNativeSelect>
      )}
    </>
  );
  const alat = (unduh) => (
    <>
      {unduh}
      <Button variant="outline" size="icon" onClick={exportExcel} disabled={loading} data-testid="export-excel-btn"
        title="Unduh laporan Excel lengkap dari server (dengan baris ringkasan)" aria-label="Unduh laporan Excel lengkap">
        <FileSpreadsheet />
      </Button>
      <Button variant="outline" size="icon" onClick={fetchReportData} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </>
  );
  const memuat = <p className="py-6 text-center text-sm text-muted-foreground">Memuat laporan…</p>;
  const labelPeriodeAktif = `Periode ${fmtDate(dateFrom)} – ${fmtDate(dateTo)}.`;
  const namaBerkas = (j) => `laporan-sdm-${j}-${dateFrom || ''}-${dateTo || ''}`;

  // ─── Kehadiran ───
  const att = attendanceData;
  const attAgg = att?.aggregates || {};
  const attRows = att?.summary || [];
  const attAdaGrafik = (att?.chart_data || []).some((d) => d.hadir || d.izin || d.sakit || d.cuti || d.alfa);
  // Karyawan tanpa satu pun catatan absen di periode ini: persentase tidak bisa dihitung → "—", bukan 0% merah.
  const attTercatat = attRows.reduce((a, e) => a + (e.recorded_days || 0), 0);
  const kolomAtt = [kolomKaryawan, kolomDept,
    kanan('hadir', 'Hadir', (e) => e.hadir), kanan('izin', 'Izin', (e) => e.izin), kanan('sakit', 'Sakit', (e) => e.sakit),
    kanan('cuti', 'Cuti', (e) => e.cuti), kanan('alfa', 'Alfa', (e) => e.alfa ?? e.alpha),
    { kunci: 'rate', label: 'Kehadiran', rata: 'kanan', isi: (e) => (!e.recorded_days
      ? <span className="text-muted-foreground" title="Belum ada catatan absen di periode ini">—</span> : (
      <span className={`font-semibold tabular-nums ${e.attendance_rate >= 90 ? 'text-[hsl(var(--success-text))]' : e.attendance_rate >= 80 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]'}`}>
        {e.attendance_rate}%
      </span>)) },
  ];
  const tabKehadiran = !att ? memuat : (
    <div className="space-y-4">
      {attAdaGrafik && (
      <Bagian judul="Tren kehadiran harian">
        {(
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={att.chart_data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--glass-border)" vertical={false} />
              <XAxis dataKey="date" tick={SUMBU} tickFormatter={tglPendek} />
              <YAxis allowDecimals={false} tick={SUMBU} />
              <Tooltip contentStyle={TOOLTIP} labelFormatter={fmtDate} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="hadir" stroke={WARNA.hadir} name="Hadir" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="izin" stroke={WARNA.izin} name="Izin" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="sakit" stroke={WARNA.sakit} name="Sakit" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="cuti" stroke={WARNA.cuti} name="Cuti" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="alfa" stroke={WARNA.alfa} name="Alfa" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Bagian>
      )}
      <TabelData kolom={kolomAtt} baris={attRows} kunci={(e) => e.employee_id} testId="hr-report-attendance"
        kosong={<EmptyState title="Tidak ada karyawan yang cocok" description="Ubah saringan departemen, lokasi, shift, atau karyawan." />} />
    </div>
  );

  // ─── Lembur ───
  const ot = overtimeData;
  const otAgg = ot?.aggregates || {};
  const otRows = ot?.summary || [];
  const otAdaGrafik = (ot?.chart_data || []).some((d) => d.ot_hours);
  const tabLembur = !ot ? memuat : (
    <div className="space-y-4">
      {otAdaGrafik && (
      <Bagian judul="Jam lembur harian">
        {(
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={ot.chart_data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--glass-border)" vertical={false} />
              <XAxis dataKey="date" tick={SUMBU} tickFormatter={tglPendek} />
              <YAxis tick={SUMBU} />
              <Tooltip contentStyle={TOOLTIP} labelFormatter={fmtDate} formatter={(v) => [`${v} jam`, 'Lembur']} />
              <Bar dataKey="ot_hours" fill="hsl(var(--primary))" name="Jam lembur" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Bagian>
      )}
      <TabelData kunci={(e) => e.employee_id} baris={otRows} testId="hr-report-overtime"
        kolom={[kolomKaryawan, kolomDept, kanan('jam', 'Total jam', (e) => e.total_ot_hours), kanan('hari', 'Hari lembur', (e) => e.ot_days),
          kanan('rata', 'Rata-rata per hari', (e) => e.avg_ot_per_day)]}
        kosong={<EmptyState title="Tidak ada karyawan yang lembur" description="Ubah periode atau saringan." />} />
    </div>
  );

  // ─── Penggajian ───
  const pr = payrollData;
  const prAgg = pr?.aggregates || {};
  const prRows = pr?.summary || [];
  const tabGaji = !pr ? memuat : (
    <TabelData kunci={(e) => e.employee_id} baris={prRows} testId="hr-report-payroll"
      kolom={[kolomKaryawan, kolomDept, kanan('kotor', 'Kotor', (e) => formatRupiah(e.gross_salary)),
        { kunci: 'potongan', label: 'Potongan', rata: 'kanan', isi: (e) => <span className="tabular-nums text-[hsl(var(--danger-text))]">{formatRupiah(e.total_deductions)}</span> },
        { kunci: 'bersih', label: 'Bersih', rata: 'kanan', isi: (e) => <span className="font-semibold tabular-nums">{formatRupiah(e.net_salary)}</span> },
        kanan('hadir', 'Hari hadir', (e) => e.attendance_days)]}
      kosong={<EmptyState title="Belum ada data gaji" description={pr.period ? 'Ubah saringan.' : 'Belum ada proses penggajian untuk periode ini.'} />} />
  );

  // ─── Keluar-masuk ───
  const to = turnoverData;
  const toAgg = to?.aggregates || {};
  const toAdaGrafik = (to?.chart_data || []).some((d) => d.hires || d.resignations);
  const tabelOrang = (rows, kolomTanggal, labelTanggal, testId, judulKosong) => (
    <TabelData baris={rows} kunci={(e) => e.id} testId={testId}
      kolom={[
        { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (e) => <span className="font-medium text-foreground">{e.name || '—'}</span> },
        { kunci: 'kode', label: 'Kode', isi: (e) => <span className="text-sm">{e.employee_code || '—'}</span> },
        { kunci: 'dept', label: 'Departemen', isi: (e) => <span className="text-sm">{e.department_name || '—'}</span> },
        { kunci: 'tgl', label: labelTanggal, isi: (e) => <span className="text-sm">{fmtDate(e[kolomTanggal])}</span> },
      ]}
      kosong={<EmptyState className="py-8" title={judulKosong} />} />
  );
  const tabTurnover = !to ? memuat : (
    <div className="space-y-4">
      {toAdaGrafik && (
      <Bagian judul="Masuk dan keluar per bulan">
        {(
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={to.chart_data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--glass-border)" vertical={false} />
              <XAxis dataKey="month" tick={SUMBU} />
              <YAxis allowDecimals={false} tick={SUMBU} />
              <Tooltip contentStyle={TOOLTIP} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="hires" fill="hsl(var(--success))" name="Masuk" radius={[4, 4, 0, 0]} />
              <Bar dataKey="resignations" fill="hsl(var(--destructive))" name="Keluar" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </Bagian>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Bagian judul={`Karyawan baru (${to.new_hires.length})`}
          alat={<TombolUnduh namaBerkas={namaBerkas('karyawan-baru')} namaLembar="Karyawan baru" baris={to.new_hires} testId="unduh-karyawan-baru"
            kolom={[{ label: 'Kode', nilai: (e) => e.employee_code || '' }, { label: 'Nama', nilai: (e) => e.name || '' },
              { label: 'Departemen', nilai: (e) => e.department_name || '' }, { label: 'Tanggal masuk', nilai: (e) => fmtDate(e.join_date) }]} />}>
          {tabelOrang(to.new_hires, 'join_date', 'Tanggal masuk', 'hr-report-new-hires', 'Tidak ada karyawan baru')}
        </Bagian>
        <Bagian judul={`Karyawan keluar (${to.resignations.length})`}
          alat={<TombolUnduh namaBerkas={namaBerkas('karyawan-keluar')} namaLembar="Karyawan keluar" baris={to.resignations} testId="unduh-karyawan-keluar"
            kolom={[{ label: 'Kode', nilai: (e) => e.employee_code || '' }, { label: 'Nama', nilai: (e) => e.name || '' },
              { label: 'Departemen', nilai: (e) => e.department_name || '' }, { label: 'Tanggal keluar', nilai: (e) => fmtDate(e.resign_date) }]} />}>
          {tabelOrang(to.resignations, 'resign_date', 'Tanggal keluar', 'hr-report-resignations', 'Tidak ada karyawan keluar')}
        </Bagian>
      </div>
    </div>
  );

  return (
    <div data-testid="hr-reports-page">
      {/* Tanpa subjudul: nama tab sudah menjelaskan isinya, dan tabel tidak terdorong ke bawah. */}
      <HubTabs hubId="hr-reports" title="Laporan SDM"
        value={activeTab} onValueChange={setActiveTab}
        tabs={[
          { key: 'attendance', label: 'Kehadiran', Component: IsiTab, props: {
            filters: penyaring, children: tabKehadiran,
            tools: alat(<TombolUnduh namaBerkas={namaBerkas('kehadiran')} namaLembar="Kehadiran" baris={attRows} testId="unduh-kehadiran"
              kolom={[
                { label: 'Kode', nilai: (e) => e.employee_code || '' }, { label: 'Karyawan', nilai: (e) => e.employee_name || '' },
                { label: 'Departemen', nilai: (e) => e.department_name || '' }, { label: 'Hari kerja', nilai: (e) => e.working_days },
                { label: 'Hadir', nilai: (e) => e.hadir }, { label: 'Izin', nilai: (e) => e.izin }, { label: 'Sakit', nilai: (e) => e.sakit },
                { label: 'Cuti', nilai: (e) => e.cuti }, { label: 'Alfa', nilai: (e) => e.alfa ?? e.alpha },
                { label: 'Terlambat', nilai: (e) => e.terlambat }, { label: 'Kehadiran (%)', nilai: (e) => e.attendance_rate },
              ]} />),
            summary: att && (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label="Karyawan dalam laporan" value={angka(attAgg.total_employees)} sub={labelPeriodeAktif} />
                <StatTile label="Hari hadir" value={angka(attAgg.total_hadir)}
                  sub={attTercatat ? `Rata-rata kehadiran ${attAgg.avg_attendance_rate ?? 0}% dari ${attAgg.working_days ?? '—'} hari kerja.`
                    : 'Belum ada catatan absen di periode ini.'} />
                <StatTile label="Izin, cuti, sakit" value={angka((attAgg.total_izin || 0) + (attAgg.total_cuti || 0) + (attAgg.total_sakit || 0))}
                  sub={`Izin ${attAgg.total_izin || 0} · cuti ${attAgg.total_cuti || 0} · sakit ${attAgg.total_sakit || 0} (hari).`} />
                <StatTile label="Alfa" value={angka(attAgg.total_alfa)} accent={attAgg.total_alfa ? 'danger' : 'default'}
                  sub={`Hari tanpa keterangan. Terlambat ${attAgg.total_terlambat || 0} kali.`} />
              </div>
            ),
          } },
          { key: 'overtime', label: 'Lembur', Component: IsiTab, props: {
            filters: penyaring, children: tabLembur,
            tools: alat(<TombolUnduh namaBerkas={namaBerkas('lembur')} namaLembar="Lembur" baris={otRows} testId="unduh-lembur"
              kolom={[
                { label: 'Kode', nilai: (e) => e.employee_code || '' }, { label: 'Karyawan', nilai: (e) => e.employee_name || '' },
                { label: 'Departemen', nilai: (e) => e.department_name || '' }, { label: 'Total jam', nilai: (e) => e.total_ot_hours },
                { label: 'Hari lembur', nilai: (e) => e.ot_days }, { label: 'Rata-rata per hari', nilai: (e) => e.avg_ot_per_day },
              ]} />),
            summary: ot && (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                <StatTile label="Karyawan yang lembur" value={angka(otAgg.total_employees_with_ot)} sub={`Punya lembur disetujui. ${labelPeriodeAktif}`} />
                <StatTile label="Total jam lembur" value={`${angka(otAgg.total_ot_hours)} jam`} sub="Semua karyawan dalam saringan." />
                <StatTile label="Rata-rata per karyawan" value={otAgg.total_employees_with_ot ? `${angka(otAgg.avg_ot_per_emp)} jam` : '—'}
                  sub={otAgg.total_employees_with_ot ? 'Dibagi karyawan yang lembur saja.' : 'Belum ada karyawan yang lembur.'} />
              </div>
            ),
          } },
          { key: 'payroll', label: 'Penggajian', Component: IsiTab, props: {
            filters: penyaring, children: tabGaji,
            tools: alat(<TombolUnduh namaBerkas={namaBerkas('penggajian')} namaLembar="Penggajian" baris={prRows} testId="unduh-penggajian"
              kolom={[
                { label: 'Kode', nilai: (e) => e.employee_code || '' }, { label: 'Karyawan', nilai: (e) => e.employee_name || '' },
                { label: 'Departemen', nilai: (e) => e.department_name || '' }, { label: 'Kotor', nilai: (e) => Number(e.gross_salary || 0) },
                { label: 'Potongan', nilai: (e) => Number(e.total_deductions || 0) }, { label: 'Bersih', nilai: (e) => Number(e.net_salary || 0) },
                { label: 'Hari hadir', nilai: (e) => e.attendance_days },
              ]} />),
            summary: pr && (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label="Karyawan digaji" value={angka(prAgg.total_employees)}
                  sub={pr.period ? `Periode gaji ${typeof pr.period === 'string' ? pr.period : (pr.period.period_code || '')}.` : 'Belum ada proses penggajian.'} />
                <StatTile label="Total kotor" value={pr.period ? formatRupiahShort(prAgg.total_gross) : '—'} sub={pr.period ? formatRupiah(prAgg.total_gross) : 'Belum ada data gaji.'} />
                <StatTile label="Total potongan" value={pr.period ? formatRupiahShort(prAgg.total_deductions) : '—'} sub={pr.period ? formatRupiah(prAgg.total_deductions) : 'Belum ada data gaji.'} />
                <StatTile label="Total bersih" value={pr.period ? formatRupiahShort(prAgg.total_net) : '—'}
                  sub={pr.period ? `Rata-rata ${formatRupiah(prAgg.avg_net)} per karyawan.` : 'Belum ada data gaji.'} />
              </div>
            ),
          } },
          { key: 'turnover', label: 'Keluar-masuk', Component: IsiTab, props: {
            filters: penyaring, children: tabTurnover, tools: alat(null),
            summary: to && (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label="Karyawan baru" value={angka(toAgg.new_hires_count)} sub={`Tanggal masuk di ${labelPeriodeAktif.charAt(0).toLowerCase()}${labelPeriodeAktif.slice(1)}`} />
                <StatTile label="Karyawan keluar" value={angka(toAgg.resignations_count)} accent={toAgg.resignations_count ? 'warning' : 'default'}
                  sub="Tanggal keluar di periode ini." />
                <StatTile label="Karyawan aktif" value={angka(toAgg.active_employees)} sub="Jumlah saat ini, bukan awal periode." />
                <StatTile label="Tingkat keluar" value={`${toAgg.turnover_rate ?? 0}%`} sub="Keluar ÷ karyawan aktif saat ini (perkiraan)." />
              </div>
            ),
          } },
        ]} />
    </div>
  );
}
