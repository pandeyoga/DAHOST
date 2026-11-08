import { useEffect, useState } from 'react';
import { Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { apiGet, apiPost } from '../../lib/api';
import { formatDateTimeID } from '@/lib/format';

const PEMICU = { manual: 'dijalankan manual', schedule: 'terjadwal', scheduled: 'terjadwal', cron: 'terjadwal', startup: 'saat server mulai' };
const STATUS = { success: 'berhasil', ok: 'berhasil', error: 'gagal', failed: 'gagal', running: 'sedang berjalan' };

/**
 * Baris status cron platform (jalankan sekarang + hasil terakhir). job: 'mark-overdue' | 'fg-valuation-check'.
 * Standar UI/UX v2 (8 Nov 2026): tampil sebagai BARIS di daftar tugas (dulu kartu sendiri; judul & keterangan
 * bertumpuk di HP), waktu dalam WIB, pemicu/status dalam bahasa Indonesia. Props tetap sama.
 */
export default function CronJobCard({ job, title, description, renderResult, onRan }) {
  const [runs, setRuns] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = () => apiGet(`/cron/runs?job=${job}&limit=3`).then(setRuns).catch(() => {});
  useEffect(() => { load(); }, [job]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async () => {
    setBusy(true);
    try { const r = await apiPost(`/cron/${job}/run-now`, {}); toast.success('Selesai dijalankan'); load(); onRan?.(r.result); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const last = runs[0];
  return (
    <div className="grid gap-2 py-3 md:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] md:gap-4" data-testid={`cron-card-${job}`}>
      <div className="min-w-0">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">Berjalan {description}</p>
      </div>
      <div className="min-w-0 space-y-1">
        <Button size="sm" variant="outline" disabled={busy} onClick={run} data-testid={`cron-run-${job}`}><Play />Jalankan sekarang</Button>
        <p className="text-xs text-muted-foreground" data-testid={`cron-last-${job}`}>
          {last ? <>Terakhir: {formatDateTimeID(last.started_at)} · {PEMICU[last.trigger] || last.trigger} · {STATUS[last.status] || last.status}{last.result && renderResult ? ` · ${renderResult(last.result)}` : ''}{last.error ? ` · ${last.error}` : ''}</> : 'Belum pernah dijalankan.'}
        </p>
      </div>
    </div>
  );
}
