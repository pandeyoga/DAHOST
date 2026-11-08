/**
 * Penjadwal Otomasi (Portal Toko) — status job terjadwal dan riwayat jalannya.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar = tabel (kartu ringkas di HP), detail = popup,
 * unduh Excel/CSV di setiap tabel, bahasa Indonesia. Tampilan "Kartu" lama (kartu besar per job) diganti tabel.
 * Waktu riwayat dari server tersimpan UTC tanpa zona → dibaca sebagai UTC lalu ditampilkan WIB.
 */
import { useState, useEffect, useCallback } from 'react';
import { Play, RefreshCw } from 'lucide-react';
import apiFetch from '@/lib/apiFetch';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { useToast } from '@/hooks/use-toast';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';

/**
 * Nama job dalam bahasa staf (keterangan dari server kadang memuat istilah program/Inggris).
 * [nama singkat, keterangan]. Job baru yang belum ada di sini memakai keterangan server.
 */
export const JOB_LABEL = {
  daily_unvalued_digest: ['Ringkasan aksesoris ber-HPP 0', 'Satu notifikasi harian berisi semua aksesoris yang belum dinilai, ke admin gudang, aksesoris, dan keuangan.'],
  monthly_valuation_report_email: ['Rapor valuasi aksesoris bulanan', 'Kirim rapor valuasi persediaan aksesoris bulan lalu (Excel + PDF) ke email tim keuangan.'],
  management_alerts: ['Peringatan manajemen', 'PO yang mendekati/melewati tenggat dan piutang jatuh tempo. Ambang hari diatur owner. Satu notifikasi per dokumen per hari.'],
  weekly_rnd_decision_report: ['Rapor keputusan RnD mingguan', 'Style yang disetujui, ditolak, dan yang menunggu keputusan terlalu lama. Sekali per pekan.'],
  scan_overdue_invoices: ['Pindai faktur lewat jatuh tempo', 'Cari faktur yang lewat jatuh tempo lalu kirim notifikasi.'],
  birthday_anniversary_reminders: ['Pengingat ulang tahun & masa kerja', 'Karyawan yang berulang tahun atau genap masa kerjanya hari ini, notifikasi ke SDM.'],
  kpi_deadline_reminders: ['Pengingat tenggat KPI', 'Pengingat tenggat KPI ke karyawan & SDM (7, 3, dan 1 hari sebelum penutupan).'],
  auto_create_tasks_from_templates: ['Buat tugas dari templat', 'Setiap pagi membuat tugas dari templat sesuai jadwal ulang (harian/mingguan/bulanan).'],
  marketing_alerts: ['Peringatan marketing', 'Diskon hampir habis, komplain lewat batas waktu, peluncuran mendekat, dan konten hari ini — lalu kirim notifikasi.'],
  auto_create_marketing_tasks: ['Buat tugas marketing otomatis', 'Tugas untuk data penjualan harian yang belum diisi dan skor kesehatan toko yang turun.'],
  cleanup_old_marketing_uploads: ['Bersihkan unggahan marketing lama', 'Hapus berkas unggahan marketing yang lebih dari 30 hari.'],
  scan_overdue_marketing_tasks: ['Pindai tugas marketing terlambat', 'Kirim notifikasi ke penanggung jawab tugas dan PIC toko.'],
  leave_carry_forward: ['Bawa saldo cuti ke tahun baru', 'Setiap 1 Januari sisa cuti tahunan dibawa ke tahun berikutnya.'],
  auto_database_backup: ['Cadangan database harian', 'Cadangan database otomatis setiap hari, disimpan 30 hari.'],
  cmt_daily_recap_reminder: ['Teguran rekap harian CMT', 'Tegur vendor CMT yang belum menyetor rekap harian. Sekali per vendor per tanggal.'],
  asisten_ai_proaktif: ['Asisten AI proaktif', 'Briefing pagi, peringatan harian, dan laporan mingguan. Jam & penerima diatur di Monitor AI.'],
  daily_negative_stock_reminder: ['Pengingat stok minus harian', 'Satu notifikasi ke peran gudang berisi material ber-stok minus.'],
  notif_resolve_actions: ['Tutup notifikasi tindakan yang selesai', 'Tutup otomatis notifikasi "Perlu tindakan" yang sudah beres (PR/cuti/klaim disetujui, stok normal).'],
  notif_retention: ['Hapus notifikasi lama', 'Hapus pemberitahuan yang sudah dibaca dan tindakan yang sudah tertutup setelah jangka waktu tertentu (bawaan 90 hari).'],
  wh_scan_out_auto_close: ['Tutup otomatis scan keluar penjualan', 'Tutup lembar scan keluar penjualan yang lupa ditutup, satu jurnal HPP per lembar.'],
  wh_scan_out_daily_check: ['Pemeriksaan pagi scan keluar', 'Tutup susulan lembar lama dan beri "Perlu tindakan" bila lembar kemarin belum tertutup atau ada selisih.'],
};
export const namaJobID = (id, desc) => JOB_LABEL[id]?.[0] || desc || String(id || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
export const ketJobID = (id, desc) => JOB_LABEL[id]?.[1] || desc || '';

/** Waktu dari server: bila tanpa zona, dianggap UTC (begitu disimpan penjadwal). */
const waktu = (v) => {
  if (!v) return '—';
  const s = String(v);
  const d = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? '—' : formatDateTimeID(d);
};
const namaJob = (id, peta) => namaJobID(id, peta[id]);
const STATUS_RUN = {
  success: { label: 'Berhasil', tone: 'success' },
  running: { label: 'Berjalan', tone: 'info' },
  failed: { label: 'Gagal', tone: 'danger' },
  error: { label: 'Gagal', tone: 'danger' },
};
const statusRun = (s) => STATUS_RUN[s] || { label: s ? 'Gagal' : '—', tone: s ? 'danger' : 'muted' };

export default function MarketingSchedulerModule() {
  const { toast } = useToast();
  const [jobs, setJobs] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [schedulerRunning, setSchedulerRunning] = useState(false);
  const [runningJob, setRunningJob] = useState(null);
  const [detailJob, setDetailJob] = useState(null);
  const [detailRun, setDetailRun] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [jobsRes, runsRes] = await Promise.all([
        apiFetch('/dewi/scheduler/jobs'),
        apiFetch('/dewi/scheduler/runs?limit=20'),
      ]);
      setJobs(jobsRes.jobs || []);
      setSchedulerRunning(jobsRes.scheduler_running || false);
      setRuns(Array.isArray(runsRes) ? runsRes : []);
    } catch (err) {
      toast({ title: 'Gagal memuat status penjadwal', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadData(); }, [loadData]);

  const runNow = async (jobId, desc) => {
    setRunningJob(jobId);
    try {
      await apiFetch(`/dewi/scheduler/jobs/${jobId}/run-now`, { method: 'POST' });
      toast({ title: `Job "${desc}" berhasil dijalankan.` });
      await loadData();
    } catch (err) {
      toast({ title: 'Job gagal dijalankan', description: err.message, variant: 'destructive' });
    } finally {
      setRunningJob(null);
    }
  };

  const peta = Object.fromEntries(jobs.map((j) => [j.id, j.description]));

  const tombolJalan = (job) => (
    <Button size="sm" variant="outline" onClick={() => runNow(job.id, job.description)}
      disabled={runningJob === job.id} data-testid={`run-job-${job.id}`}>
      {runningJob === job.id ? <RefreshCw className="animate-spin" /> : <Play />}Jalankan sekarang
    </Button>
  );

  const kolomJob = [
    { kunci: 'job', label: 'Job', hp: 'judul', isi: (j) => (
      <div className="min-w-0 md:max-w-[34rem]">
        <p className="font-medium text-foreground">{namaJobID(j.id, j.description)}</p>
        {JOB_LABEL[j.id] && <p className="hidden truncate text-xs text-muted-foreground md:block" title={ketJobID(j.id, j.description)}>{ketJobID(j.id, j.description)}</p>}
      </div>) },
    { kunci: 'jadwal', label: 'Jadwal', isi: (j) => <span className="md:whitespace-nowrap">{j.cron_label || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (j) => (j.enabled
      ? <StatusBadge status="aktif" label="Aktif" tone="success" />
      : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />) },
    { kunci: 'berikut', label: 'Jalan berikutnya', isi: (j) => <span className="md:whitespace-nowrap tabular-nums">{waktu(j.next_run_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: tombolJalan },
  ];

  const kolomRun = [
    { kunci: 'mulai', label: 'Waktu mulai', hp: 'keterangan', isi: (r) => <span className="md:whitespace-nowrap tabular-nums">{waktu(r.started_at)}</span> },
    { kunci: 'job', label: 'Job', hp: 'judul', isi: (r) => (
      <p className="min-w-0 md:max-w-[28rem] truncate" title={namaJob(r.job_id, peta)}>{namaJob(r.job_id, peta)}</p>) },
    { kunci: 'status', label: 'Status', isi: (r) => { const s = statusRun(r.status); return <StatusBadge status={r.status} label={s.label} tone={s.tone} />; } },
    { kunci: 'galat', label: 'Galat', isi: (r) => (r.error
      ? <span className="block md:max-w-[20rem] truncate text-[hsl(var(--danger-text))]" title={r.error}>{r.error}</span>
      : <span className="text-muted-foreground">—</span>) },
  ];

  return (
    <PageLayout testId="marketing-scheduler" title="Penjadwal otomasi"
      subtitle="Job terjadwal: pembuatan tugas otomatis, pengingat, dan pembersihan berkas."
      tools={<>
        <TombolUnduh namaBerkas="penjadwal-job" namaLembar="Job" baris={jobs} testId="scheduler-unduh-job"
          label="Unduh job"
          kolom={[
            { label: 'Job', nilai: (j) => namaJobID(j.id, j.description) },
            { label: 'Keterangan', nilai: (j) => ketJobID(j.id, j.description) },
            { label: 'Jadwal', nilai: (j) => j.cron_label || '' },
            { label: 'Status', nilai: (j) => (j.enabled ? 'Aktif' : 'Nonaktif') },
            { label: 'Jalan berikutnya', nilai: (j) => waktu(j.next_run_at) },
          ]} />
        <Button variant="outline" size="icon" onClick={loadData} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={!loading && (
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid="scheduler-ringkas">
          {schedulerRunning
            ? <StatusBadge status="berjalan" label="Penjadwal berjalan" tone="success" />
            : <StatusBadge status="berhenti" label="Penjadwal berhenti" tone="danger" />}
          <span>{jobs.length} job terdaftar · {jobs.filter((j) => j.enabled).length} aktif · waktu dalam WIB.</span>
        </p>
      )}>
      {loading && jobs.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat penjadwal…</p>
      ) : (
        <TabelData kolom={kolomJob} baris={jobs} onKlikBaris={setDetailJob} testId="scheduler-jobs-table"
          kosong={<EmptyState title="Tidak ada job terdaftar" description="Job terjadwal muncul di sini setelah server menyalakan penjadwal." />} />
      )}

      <section className="space-y-2" data-testid="scheduler-runs">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-base font-semibold text-foreground">Riwayat jalan · {runs.length} terakhir</p>
          <TombolUnduh namaBerkas="penjadwal-riwayat" namaLembar="Riwayat" baris={runs} testId="scheduler-unduh-riwayat"
            kolom={[
              { label: 'Waktu mulai', nilai: (r) => waktu(r.started_at) },
              { label: 'Waktu selesai', nilai: (r) => waktu(r.finished_at) },
              { label: 'Job', nilai: (r) => namaJob(r.job_id, peta) },
              { label: 'Status', nilai: (r) => statusRun(r.status).label },
              { label: 'Galat', nilai: (r) => r.error || '' },
            ]} />
        </div>
        <TabelData kolom={kolomRun} baris={runs} kunci={(r) => `${r.job_id}-${r.started_at}`} onKlikBaris={setDetailRun}
          testId="scheduler-runs-table"
          kosong={!loading && <EmptyState title="Belum ada riwayat jalan" description="Riwayat muncul setelah job pertama dijalankan." />} />
      </section>

      {detailJob && (
        <DetailPopup open onClose={() => setDetailJob(null)} judul={namaJobID(detailJob.id, detailJob.description)} testId="scheduler-job-detail"
          status={detailJob.enabled ? <StatusBadge status="aktif" label="Aktif" tone="success" /> : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />}
          aksi={tombolJalan(detailJob)}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Keterangan">{ketJobID(detailJob.id, detailJob.description)}</BarisDetail>
            <BarisDetail label="Jadwal">{detailJob.cron_label || '—'}</BarisDetail>
            <BarisDetail label="Jalan berikutnya">{waktu(detailJob.next_run_at)}</BarisDetail>
            <BarisDetail label="Riwayat terakhir">
              {(() => {
                const r = runs.find((x) => x.job_id === detailJob.id);
                return r ? `${waktu(r.started_at)} · ${statusRun(r.status).label}` : 'Tidak ada di 20 riwayat terakhir';
              })()}
            </BarisDetail>
          </dl>
        </DetailPopup>
      )}
      {detailRun && (
        <DetailPopup open onClose={() => setDetailRun(null)} judul="Rincian riwayat jalan" testId="scheduler-run-detail"
          status={(() => { const s = statusRun(detailRun.status); return <StatusBadge status={detailRun.status} label={s.label} tone={s.tone} />; })()}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Job">{namaJob(detailRun.job_id, peta)}</BarisDetail>
            <BarisDetail label="Mulai">{waktu(detailRun.started_at)}</BarisDetail>
            <BarisDetail label="Selesai">{waktu(detailRun.finished_at)}</BarisDetail>
            {detailRun.error && <BarisDetail label="Galat"><span className="text-[hsl(var(--danger-text))]">{detailRun.error}</span></BarisDetail>}
            {detailRun.message && <BarisDetail label="Catatan sistem"><span className="break-words text-muted-foreground">{detailRun.message}</span></BarisDetail>}
          </dl>
        </DetailPopup>
      )}
    </PageLayout>
  );
}
