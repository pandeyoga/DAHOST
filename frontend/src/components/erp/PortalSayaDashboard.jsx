/**
 * Portal Saya › Dashboard — ringkasan cuti, gaji, absen, training, KPI, dan tugas pribadi.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (dulu kepala buatan + pembungkus `p-6 max-w-5xl` ganda), kartu angka
 * StatTile (dulu 6 warna kartu berbeda), angka yang belum bisa dihitung tampil "—" + alasan (dulu "0 hadir" dan
 * "0/0 · Semua selesai" untuk akun yang belum terhubung ke data karyawan), saldo cuti = tabel, aksi cepat = tombol.
 */
import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Banknote, Bell, BookOpen, Calendar, Target, User } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import { formatDateTimeID, formatRupiah } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

export default function PortalSayaDashboard({ user, headers, onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const { data: d } = await axios.get(`${API}/api/portal/dashboard`, { headers });
      setData(d);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const nama = user?.name?.split(' ')[0] || 'Karyawan';
  const keterangan = data?.job_title || data?.employee_code
    ? `${data.job_title || ''}${data.employee_code ? ` · ${data.employee_code}` : ''}`.replace(/^ · /, '')
    : null;

  if (loading || !data) {
    return (
      <PageLayout testId="portal-saya-dashboard" title="Dashboard" subtitle={`Selamat datang, ${nama}.`}>
        {loading
          ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat ringkasan…</p>
          : <EmptyState title="Ringkasan belum bisa dimuat" description="Periksa koneksi lalu muat ulang halaman." />}
      </PageLayout>
    );
  }

  const linked = !!data.is_linked;
  const mainLeave = data.leave_balance?.[0];
  const att = data.absensi_bulan_ini || {};
  const training = data.training_stats || {};
  const kpi = data.kpi_score;
  const todos = data.todos || {};
  const reminders = data.upcoming_reminders || [];
  const belumTerhubung = 'Akun belum terhubung ke data karyawan';

  return (
    <PageLayout testId="portal-saya-dashboard" title="Dashboard"
      subtitle={`Selamat datang, ${nama}${keterangan ? ` — ${keterangan}` : ''}. Ringkasan cuti, gaji, absen, dan tugas Anda.`}>
      {!linked && (
        <Notice tone="warning" title="Akun belum terhubung ke data karyawan" testId="portal-not-linked">
          Angka cuti, gaji, dan absen baru tampil setelah SDM menghubungkan akun ini ke data karyawan Anda.
        </Notice>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="portal-dashboard-stats">
        <StatTile label="Sisa cuti" value={mainLeave ? `${mainLeave.remaining} hari` : '—'}
          sub={mainLeave ? `Terpakai ${mainLeave.used} dari ${mainLeave.quota} hari${data.pending_leave > 0 ? ` · ${data.pending_leave} menunggu` : ''}`
            : (linked ? 'Belum ada jatah cuti' : belumTerhubung)}
          onClick={() => onNavigate?.('portal-cuti')} hint="Buka Cuti & Lembur" testId="stat-sisa-cuti" />
        <StatTile label="Gaji bersih terakhir" value={data.last_payslip ? formatRupiah(data.last_payslip.net_pay) : '—'}
          sub={data.last_payslip ? `Periode ${data.last_payslip.period}` : (linked ? 'Belum ada slip gaji' : belumTerhubung)}
          onClick={() => onNavigate?.('portal-payslip')} hint="Buka Slip Gaji" testId="stat-gaji" />
        <StatTile label="Hadir bulan ini" value={linked ? `${att.hadir ?? 0} hari` : '—'}
          sub={linked ? `Izin ${att.izin ?? 0} · sakit ${att.sakit ?? 0} · alfa ${att.alfa ?? 0}` : belumTerhubung}
          onClick={() => onNavigate?.('portal-absen')} hint="Buka Absen Saya" testId="stat-hadir" />
        <StatTile label="Training selesai" value={training.enrolled ? `${training.completed ?? 0} dari ${training.enrolled}` : '—'}
          sub={training.enrolled ? `${training.pct ?? 0}% selesai` : 'Belum terdaftar di training'}
          onClick={() => onNavigate?.('portal-training')} hint="Buka Training" testId="stat-training" />
        {kpi && (
          <StatTile label="Skor KPI" value={kpi.score} sub={`Nilai ${kpi.grade} · ${kpi.period}`}
            onClick={() => onNavigate?.('kpi-portal')} hint="Buka KPI" testId="stat-kpi" />
        )}
        <StatTile label="Tugas saya" value={todos.total ? `${todos.done ?? 0} dari ${todos.total}` : '—'}
          accent={todos.overdue > 0 ? 'danger' : 'default'}
          sub={!todos.total ? 'Belum ada tugas' : todos.overdue > 0 ? `${todos.overdue} lewat tenggat` : 'Tidak ada yang lewat tenggat'}
          onClick={() => onNavigate?.('portal-workspace')} hint="Buka Ruang Kerja" testId="stat-tugas" />
        {reminders.length > 0 && (
          <StatTile label="Pengingat mendatang" value={reminders.length} sub={reminders[0]?.title || ''} testId="stat-pengingat" />
        )}
      </div>

      {data.leave_balance?.length > 1 && (
        <GlassCard className="space-y-3 p-4">
          <h3 className="text-lg font-semibold text-foreground">Saldo cuti tahun ini</h3>
          <TabelData baris={data.leave_balance} kunci={(lb) => lb.type_name} testId="portal-leave-balance" kolom={[
            { kunci: 'type_name', label: 'Jenis cuti', hp: 'judul' },
            { kunci: 'used', label: 'Terpakai', rata: 'kanan', isi: (lb) => <span className="tabular-nums">{lb.used} hari</span> },
            { kunci: 'quota', label: 'Jatah', rata: 'kanan', isi: (lb) => <span className="tabular-nums">{lb.quota} hari</span> },
            { kunci: 'remaining', label: 'Sisa', rata: 'kanan', isi: (lb) => <span className="font-semibold tabular-nums">{lb.remaining} hari</span> },
          ]} />
        </GlassCard>
      )}

      {reminders.length > 0 && (
        <GlassCard className="space-y-2 p-4">
          <h3 className="text-lg font-semibold text-foreground">Pengingat mendatang</h3>
          <ul className="divide-y divide-[var(--glass-border)]">
            {reminders.slice(0, 5).map((r, i) => (
              <li key={i} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2">
                <span className="text-sm font-medium">{r.title}</span>
                <span className="text-xs text-muted-foreground">{formatDateTimeID(r.remind_at)}</span>
              </li>
            ))}
          </ul>
        </GlassCard>
      )}

      <GlassCard className="space-y-3 p-4">
        <h3 className="text-lg font-semibold text-foreground">Aksi cepat</h3>
        <div className="flex flex-wrap gap-2">
          {[
            { id: 'portal-cuti', label: 'Ajukan cuti', icon: Calendar },
            { id: 'portal-payslip', label: 'Slip gaji', icon: Banknote },
            { id: 'kpi-portal', label: 'KPI saya', icon: Target },
            { id: 'portal-training', label: 'Training', icon: BookOpen },
            { id: 'portal-notifikasi', label: 'Notifikasi', icon: Bell },
            { id: 'portal-profile', label: 'Profil saya', icon: User },
          ].map(({ id, label, icon: Icon }) => (
            <Button key={id} variant="outline" onClick={() => onNavigate?.(id)} data-testid={`quick-action-${id}`}>
              <Icon />{label}
            </Button>
          ))}
        </div>
      </GlassCard>
    </PageLayout>
  );
}
