/**
 * Digest Mingguan (Portal Manajemen) — ringkasan mingguan lintas bagian + audit perubahan peran/izin.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, tab standar, ringkasan per bagian dalam satu gaya kartu, tabel
 * (log perubahan & peran pengguna aktif) yang bisa diunduh Excel/CSV, label peran & aksi berbahasa biasa (dulu kode
 * seperti "tim_packing"), tanpa emoji / warna mentah / gradasi.
 * Angka diperiksa (lihat LAPORAN): "Stok rendah" di digest dulu membaca kolom tersimpan `total_qty` (1.111 material).
 * Sejak 8 Nov 2026 server digest memakai pembaca stok resmi (`core.stock_thresholds`, sama dengan Dashboard Gudang &
 * Alert & Reorder), jadi layar ini cukup membaca angka & kondisi dari /management/weekly-digest (satu sumber).
 */
import { useState, useEffect, useCallback } from 'react';
import apiFetch from '@/lib/apiFetch';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { GlassCard } from '@/components/ui/glass';
import { RefreshCw } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const fmtRp = formatRupiah;
const fmtNum = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('id-ID'));

const PERAN = {
  superadmin: 'Super admin', admin: 'Admin', owner: 'Owner', manager: 'Manajer', supervisor: 'Supervisor', staff: 'Staf',
  accounting: 'Akuntansi', staff_keuangan: 'Staf keuangan', hr_manager: 'Manajer SDM', admin_produksi: 'Admin produksi',
  supervisor_produksi: 'Supervisor produksi', admin_gudang: 'Admin gudang', rnd_staff: 'Staf RnD', admin_maklon: 'Admin maklon',
  tim_packing: 'Tim packing', spv_packing: 'Supervisor packing', admin_aksesoris: 'Admin aksesoris',
};
const manusiawi = (s) => {
  const t = String(s ?? '').replace(/[_-]+/g, ' ').trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '—';
};
const labelPeran = (r) => PERAN[r] || manusiawi(r).replace(/^Staff\b/, 'Staf');
const tgl = (v) => (v ? new Date(v).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : '—');
const KONDISI = {
  good: { label: 'Kondisi baik', tone: 'success' },
  warning: { label: 'Ada yang perlu diperhatikan', tone: 'warning' },
  critical: { label: 'Perlu tindakan', tone: 'danger' },
};

function WeeklyDigestTab() {
  const { toast } = useToast();
  const [digest, setDigest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);

  const loadDigest = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/management/weekly-digest?days=${days}`);
      setDigest(res.data);
    } catch (err) {
      toast({ title: 'Gagal memuat digest', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [days, toast]);

  useEffect(() => { loadDigest(); }, [loadDigest]);

  const rak = digest?.alerts?.high_occupancy_racks || 0;
  const stok = digest?.alerts?.low_stock_materials ?? null;
  // kondisi & jumlah peringatan dari server (0 = baik, ≤ 3 = perhatian, lebih = perlu tindakan)
  const peringatan = digest?.alert_count;
  const health = digest?.health;
  const kondisi = KONDISI[health] || KONDISI.good;

  const alat = (
    <div className="flex flex-wrap items-center gap-2">
      <SmartNativeSelect value={String(days)} onChange={(e) => setDays(Number(e.target.value))} searchable={false}
        className="h-9 w-40" aria-label="Rentang hari">
        <option value="7">7 hari terakhir</option>
        <option value="14">14 hari terakhir</option>
        <option value="30">30 hari terakhir</option>
      </SmartNativeSelect>
      <Button variant="outline" size="icon" onClick={loadDigest} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
        data-testid="mgmt-tools-digest-refresh">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </div>
  );

  const barisDigest = digest ? [
    ['Produksi', 'Work order baru', fmtNum(digest.production?.new_work_orders)],
    ['Produksi', 'Work order selesai', fmtNum(digest.production?.completed_work_orders)],
    ['Keuangan', 'Faktur baru', fmtNum(digest.finance?.new_invoices)],
    ['Keuangan', 'Faktur lunas', fmtNum(digest.finance?.paid_invoices)],
    ['Keuangan', 'Nilai faktur baru', fmtRp(digest.finance?.total_invoiced)],
    ['Maklon', 'Order baru', fmtNum(digest.maklon?.new_orders)],
    ['Maklon', 'Order selesai', fmtNum(digest.maklon?.completed_orders)],
    ['SDM', 'Pengajuan cuti', fmtNum(digest.hr?.leave_requests)],
    ['SDM', 'Izin / sakit', fmtNum(digest.hr?.attendance_issues)],
    ['Marketing', 'Sesi live', fmtNum(digest.marketing?.live_sessions)],
    ['Marketing', 'Omzet live', fmtRp(digest.marketing?.live_revenue)],
    ['Marketing', 'Pesanan live', fmtNum(digest.marketing?.live_orders)],
    ['Peringatan sistem', 'Material di bawah stok minimum', stok === null ? '—' : fmtNum(stok)],
    ['Peringatan sistem', 'Rak terisi lebih dari 90%', `${fmtNum(rak)}${digest.alerts?.high_occupancy_rack_codes?.length ? ` (${digest.alerts.high_occupancy_rack_codes.join(', ')})` : ''}`],
  ] : [];

  if (loading && !digest) return <div className="space-y-4">{alat}<p className="py-8 text-center text-sm text-muted-foreground">Memuat digest…</p></div>;
  if (!digest) return <div className="space-y-4">{alat}<EmptyState title="Digest tidak dapat dimuat" description="Coba muat ulang." /></div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {alat}
        <div className="flex flex-wrap items-center gap-2" data-testid="mgmt-tools-kondisi">
          <StatusBadge status={health} label={kondisi.label} tone={kondisi.tone} />
          {peringatan > 0 && <span className="text-sm text-muted-foreground">{fmtNum(peringatan)} peringatan</span>}
        </div>
      </div>

      <GlassCard className="space-y-3 p-4" data-konten-utama="">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-base font-semibold text-foreground">Ringkasan {days} hari terakhir</p>
          <TombolUnduh namaBerkas={`digest-${days}-hari`} namaLembar="Digest" baris={barisDigest} testId="digest-unduh"
            kolom={[{ label: 'Bagian', nilai: (r) => r[0] }, { label: 'Indikator', nilai: (r) => r[1] }, { label: 'Nilai', nilai: (r) => r[2] }]} />
        </div>
        <Table>
          <TableHeader>
            <TableRow><TableHead>Bagian</TableHead><TableHead>Indikator</TableHead><TableHead className="text-right">Nilai</TableHead></TableRow>
          </TableHeader>
          <TableBody>
            {barisDigest.map(([bag, ind, nil], idx) => (
              <TableRow key={`${bag}-${ind}`}>
                <TableCell className="font-medium">{idx === 0 || barisDigest[idx - 1][0] !== bag ? bag : ''}</TableCell>
                <TableCell className="text-muted-foreground">{ind}</TableCell>
                <TableCell className="text-right tabular-nums">{nil}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </GlassCard>
      {stok === null && (
        <Notice tone="info">Jumlah material di bawah stok minimum tidak terbaca dari pembaca stok resmi; muat ulang untuk mencoba lagi.</Notice>
      )}
    </div>
  );
}

function PermissionAuditTab() {
  const { toast } = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  const loadAudit = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/management/audit/permissions?days=${days}`);
      setData(res.data);
    } catch (err) {
      toast({ title: 'Gagal memuat log audit', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [days, toast]);

  useEffect(() => { loadAudit(); }, [loadAudit]);

  const log = data?.permission_changes || [];
  const peran = data?.current_roles || [];
  const ringkasDiff = (d) => Object.entries(d || {}).slice(0, 3)
    .map(([k, v]) => `${manusiawi(k)}: ${JSON.stringify(v?.before)} → ${JSON.stringify(v?.after)}`).join(' · ');

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SmartNativeSelect value={String(days)} onChange={(e) => setDays(Number(e.target.value))} searchable={false}
          className="h-9 w-40" aria-label="Rentang hari">
          <option value="7">7 hari terakhir</option>
          <option value="30">30 hari terakhir</option>
          <option value="90">90 hari terakhir</option>
        </SmartNativeSelect>
        <Button variant="outline" size="icon" onClick={loadAudit} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="mgmt-tools-audit-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </div>

      {loading && !data && <p className="py-8 text-center text-sm text-muted-foreground">Memuat log audit…</p>}
      {data && (
        <>
          <GlassCard className="space-y-3 p-4" data-konten-utama="">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-base font-semibold text-foreground">Perubahan peran / izin ({fmtNum(log.length)})</p>
                <p className="text-sm text-muted-foreground">Dalam {days} hari terakhir.</p>
              </div>
              <TombolUnduh namaBerkas="audit-perubahan-izin" namaLembar="Perubahan izin" baris={log} testId="audit-log-unduh"
                kolom={[
                  { label: 'Tanggal', nilai: (l) => tgl(l.timestamp) },
                  { label: 'Pengguna', nilai: (l) => l.user_name || l.user_id || '' },
                  { label: 'Perubahan', nilai: (l) => `${manusiawi(l.action)} — ${manusiawi(l.entity_type)}` },
                  { label: 'Rincian', nilai: (l) => ringkasDiff(l.diff) },
                ]} />
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tanggal</TableHead>
                    <TableHead>Pengguna</TableHead>
                    <TableHead>Perubahan</TableHead>
                    <TableHead className="hidden md:table-cell">Rincian</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {log.length === 0 && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={4} className="p-0 [&>div]:py-8">
                        <EmptyState title="Tidak ada perubahan izin dalam periode ini" />
                      </TableCell>
                    </TableRow>
                  )}
                  {log.map((l, i) => (
                    <TableRow key={i}>
                      <TableCell className="whitespace-nowrap">{tgl(l.timestamp)}</TableCell>
                      <TableCell>{l.user_name || l.user_id}</TableCell>
                      <TableCell>{manusiawi(l.action)} — {manusiawi(l.entity_type)}</TableCell>
                      <TableCell className="hidden max-w-md text-sm text-muted-foreground md:table-cell">{ringkasDiff(l.diff) || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </GlassCard>

          <GlassCard className="space-y-3 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-base font-semibold text-foreground">Peran pengguna ({fmtNum(peran.length)})</p>
                <p className="text-sm text-muted-foreground">Peran setiap akun saat ini.</p>
              </div>
              <TombolUnduh namaBerkas="peran-pengguna" namaLembar="Peran pengguna" baris={peran} testId="audit-peran-unduh"
                kolom={[
                  { label: 'Nama', nilai: (u) => u.name || '' },
                  { label: 'Email', nilai: (u) => u.email || '' },
                  { label: 'Peran', nilai: (u) => labelPeran(u.role) },
                  { label: 'Status', nilai: (u) => (u.is_active ? 'Aktif' : 'Nonaktif') },
                  { label: 'Terakhir diubah', nilai: (u) => tgl(u.updated_at) },
                ]} />
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Pengguna</TableHead>
                    <TableHead>Peran</TableHead>
                    <TableHead className="hidden sm:table-cell">Status</TableHead>
                    <TableHead className="hidden md:table-cell">Terakhir diubah</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {peran.map((u, i) => (
                    <TableRow key={u.user_id || i}>
                      <TableCell>
                        <span className="block font-medium">{u.name || u.email}</span>
                        <span className="block text-xs text-muted-foreground">{u.email}</span>
                      </TableCell>
                      <TableCell>{labelPeran(u.role)}</TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <StatusBadge status={u.is_active ? 'aktif' : 'nonaktif'} label={u.is_active ? 'Aktif' : 'Nonaktif'} tone={u.is_active ? 'success' : 'muted'} />
                      </TableCell>
                      <TableCell className="hidden whitespace-nowrap md:table-cell">{tgl(u.updated_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </GlassCard>
        </>
      )}
    </div>
  );
}

export default function ManagementToolsModule() {
  // Bagian = pil penyaring di baris penyaring (tanpa tab di dalam modul).
  const [bagian, setBagian] = useState('digest');
  return (
    <PageLayout testId="mgmt-tools" title="Digest Mingguan"
      subtitle="Ringkasan mingguan lintas bagian dan catatan perubahan peran/izin pengguna."
      filters={(
        <FilterChips value={bagian} onChange={setBagian} hideWhenEmpty={false} ariaLabel="Bagian" testId="mgmt-tools-tab"
          options={[{ key: 'digest', label: 'Digest mingguan' }, { key: 'audit', label: 'Audit izin' }]} />
      )}>
      {bagian === 'digest' ? <WeeklyDigestTab /> : <PermissionAuditTab />}
    </PageLayout>
  );
}
