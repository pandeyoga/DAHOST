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

/** Waktu dari server: bila tanpa zona, dianggap UTC (begitu disimpan penjadwal). */
const waktu = (v) => {
  if (!v) return '—';
  const s = String(v);
  const d = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? '—' : formatDateTimeID(d);
};
const namaJob = (id, peta) => peta[id] || String(id || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
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
      <p className="min-w-0 md:max-w-[34rem] line-clamp-2 text-foreground" title={j.description}>{j.description}</p>) },
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
            { label: 'Job', nilai: (j) => j.description },
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
        <DetailPopup open onClose={() => setDetailJob(null)} judul="Rincian job" testId="scheduler-job-detail"
          status={detailJob.enabled ? <StatusBadge status="aktif" label="Aktif" tone="success" /> : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />}
          aksi={tombolJalan(detailJob)}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Keterangan">{detailJob.description}</BarisDetail>
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
