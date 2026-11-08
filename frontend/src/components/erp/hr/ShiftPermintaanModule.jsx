/**
 * ShiftPermintaanModule — Portal SDM › Shift › Permintaan shift (Tahap C audit HR, 9 Nov 2026).
 *
 * Permintaan ganti/tukar shift dari Portal Saya › Jadwal Shift. Alur: (tukar) rekan setuju → atasan langsung
 * (dari data karyawan) → SDM. Di sini SDM memutus tahap terakhir; disetujui = jadwal hari itu langsung berubah
 * (jadwal terbit "perubahan"). Server: `/api/hr/shift-scheduler/permintaan`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, RefreshCw, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { checkPerm } from '@/lib/rbac';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { TitikShift, pesanGalat, shiftApi } from './shiftShared';

const P = '/api/hr/shift-scheduler';
export const NADA_STATUS = { menunggu_rekan: 'warning', menunggu_atasan: 'warning', menunggu_hr: 'warning', disetujui: 'success', ditolak: 'danger', dibatalkan: 'muted' };

/** "PAGI → SIANG" (ganti) atau "Ani PAGI ↔ Budi SIANG" (tukar). */
export function PerubahanShift({ r }) {
  if (r.jenis === 'tukar') {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-foreground">{r.employee_name}</span><TitikShift kode={r.shift_asal?.kode || 'Libur'} warna={r.shift_asal?.warna} />
        <span aria-hidden="true">↔</span>
        <span className="text-xs text-muted-foreground">{r.rekan_name}</span><TitikShift kode={r.rekan_shift_asal?.kode || 'Libur'} warna={r.rekan_shift_asal?.warna} />
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <TitikShift kode={r.shift_asal?.kode || 'Libur'} warna={r.shift_asal?.warna} /><span aria-hidden="true">→</span>
      <TitikShift kode={r.shift_diminta?.kode} warna={r.shift_diminta?.warna} />
    </span>
  );
}

export default function ShiftPermintaanModule({ user }) {
  const bolehTulis = checkPerm({ user, roles: ['superadmin', 'admin', 'owner', 'hr', 'manager', 'hr_manager', 'staff_hr'], keys: ['hr.attendance.manage', 'hr.manage'] });
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState('menunggu_hr');
  const [memuat, setMemuat] = useState(false);

  const muat = useCallback(async () => {
    setMemuat(true);
    try { setRows((await shiftApi('get', `${P}/permintaan`, { params: { status: 'semua' } }))?.data || []); }
    catch (e) { toast.error(pesanGalat(e, 'Permintaan gagal dimuat.')); } finally { setMemuat(false); }
  }, []);
  useEffect(() => { muat(); }, [muat]);

  const hitung = useMemo(() => rows.reduce((a, r) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {}), [rows]);
  const tampil = filter === 'semua' ? rows : filter === 'proses' ? rows.filter((r) => ['menunggu_rekan', 'menunggu_atasan'].includes(r.status)) : rows.filter((r) => r.status === filter);

  const putuskan = async (r, setujui) => {
    const jenis = (r.label_jenis || 'permintaan').toLowerCase();
    const catatan = await confirmDialog(setujui ? {
      title: `Setujui ${jenis} ${r.employee_name}?`, body: 'Jadwal tanggal itu langsung berubah dan dipakai absensi.',
      confirmLabel: 'Setujui',
    } : {
      title: `Tolak ${jenis} ${r.employee_name}?`, body: 'Pemohon menerima kabar penolakan beserta alasannya.',
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan', minLength: 5, placeholder: 'Mis. orang di shift pagi kurang' },
    });
    if (!catatan) return;
    try {
      const d = await shiftApi('post', `${P}/permintaan/${r.id}/putuskan`, { data: { setujui, catatan: typeof catatan === 'string' ? catatan : '' } });
      toast.success(d?.message || 'Keputusan disimpan.');
      muat();
    } catch (e) { toast.error(pesanGalat(e, 'Keputusan gagal disimpan.')); }
  };

  const kolom = [
    { kunci: 'tgl', label: 'Tanggal shift', isi: (r) => formatTanggalID(r.tanggal) },
    { kunci: 'pemohon', label: 'Pemohon', hp: 'judul', isi: (r) => <span className="font-medium text-foreground">{r.employee_name}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (r) => r.label_jenis },
    { kunci: 'ubah', label: 'Perubahan', hp: 'keterangan', isi: (r) => <PerubahanShift r={r} /> },
    { kunci: 'alasan', label: 'Alasan', isi: (r) => <span className="line-clamp-2 max-w-[18rem]">{r.alasan}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={r.label_status} tone={NADA_STATUS[r.status]} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (bolehTulis && r.status === 'menunggu_hr' ? (
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="success" onClick={() => putuskan(r, true)} data-testid="permintaan-setujui"><Check />Setujui</Button>
        <Button size="sm" variant="destructive" onClick={() => putuskan(r, false)} data-testid="permintaan-tolak"><X />Tolak</Button>
      </div>) : null) },
  ];

  return (
    <PageLayout testId="shift-permintaan" title="Permintaan shift" subtitle="Ganti dan tukar shift yang diajukan karyawan dari Portal Saya."
      filters={<FilterChips value={filter} onChange={setFilter} hideWhenEmpty={false} testId="permintaan-filter" options={[
        { key: 'menunggu_hr', label: 'Menunggu SDM', count: hitung.menunggu_hr || 0 },
        { key: 'proses', label: 'Di rekan/atasan', count: (hitung.menunggu_rekan || 0) + (hitung.menunggu_atasan || 0) },
        { key: 'disetujui', label: 'Disetujui', count: hitung.disetujui || 0 },
        { key: 'ditolak', label: 'Ditolak', count: hitung.ditolak || 0 },
        { key: 'semua', label: 'Semua', count: rows.length },
      ]} />}
      tools={<>
        <TombolUnduh namaBerkas="permintaan-shift" namaLembar="Permintaan shift" baris={tampil} testId="permintaan-unduh"
          kolom={[{ label: 'Tanggal', nilai: (r) => formatTanggalID(r.tanggal) }, { label: 'Pemohon', nilai: (r) => r.employee_name },
            { label: 'Jenis', nilai: (r) => r.label_jenis }, { label: 'Shift asal', nilai: (r) => r.shift_asal?.kode || 'Libur' },
            { label: 'Shift diminta / rekan', nilai: (r) => (r.jenis === 'tukar' ? `${r.rekan_name} (${r.rekan_shift_asal?.kode || 'Libur'})` : r.shift_diminta?.kode || '') },
            { label: 'Alasan', nilai: (r) => r.alasan }, { label: 'Status', nilai: (r) => r.label_status }]} />
        <Button variant="outline" size="icon" onClick={muat} disabled={memuat} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className={memuat ? 'animate-spin' : ''} /></Button>
      </>}>
      <TabelData kolom={kolom} baris={tampil} testId="permintaan-tabel"
        kosong={<EmptyState title="Tidak ada permintaan di daftar ini" description="Karyawan mengajukan dari Portal Saya › Jadwal Shift." />} />
    </PageLayout>
  );
}
