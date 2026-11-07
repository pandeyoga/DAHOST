/**
 * HRLeaveBalancesModule — saldo cuti per karyawan per tahun (Portal SDM › Cuti & Lembur › Saldo cuti,
 * juga menu lama `hr-leave-balances`).
 *
 * Standar UI/UX v2 (8 Nov 2026): dulu kartu per karyawan dua kolom (gulir panjang, batang warna-warni);
 * sekarang satu tabel (karyawan × jenis cuti) dengan cari + penyaring jenis, unduh Excel/CSV, form = FormPopup.
 * Panggilan API (alokasi tahunan, penyesuaian saldo) tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { CalendarDays, Pencil, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

export default function HRLeaveBalancesModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [year, setYear] = useState(new Date().getFullYear());
  const [balances, setBalances] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [allocDialog, setAllocDialog] = useState(false);
  const [editDialog, setEditDialog] = useState(null);
  const [cari, setCari] = useState('');
  const [jenis, setJenis] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const r = await axios.get(`${API}/api/rahaza/leave-balances?year=${year}`, { headers });
      setBalances(r.data.balances || []);
    } catch (e) {
      // RC-22: JANGAN telan error jadi empty-state menyesatkan — tampilkan error nyata
      const msg = e.response?.data?.detail || e.message || 'Gagal memuat saldo cuti';
      setLoadError(`Gagal memuat saldo cuti (${e.response?.status || 'jaringan'}): ${msg}`);
      setBalances([]);
    } finally { setLoading(false); }
  }, [headers, year]);

  useEffect(() => { load(); }, [load]);

  const handleAllocate = async (forceReset) => {
    try {
      const { data } = await axios.post(
        `${API}/api/rahaza/leave-balances/allocate-year`,
        { year, force_reset: forceReset },
        { headers }
      );
      toast.success(`Alokasi: ${data.created} baru, ${data.updated} direset, ${data.total_employees} karyawan × ${data.total_leave_types} jenis cuti`);
      setAllocDialog(false);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Gagal alokasi'); }
  };

  const handleAdjust = async (form) => {
    try {
      await axios.put(`${API}/api/rahaza/leave-balances/${form.id}`,
        { adjust_delta: form.delta, reason: form.reason }, { headers });
      toast.success('Saldo disimpan');
      setEditDialog(null);
      load();
    } catch (e) { toast.error('Gagal menyimpan saldo'); }
  };

  // Baris yang punya data karyawan (sama dengan dulu: saldo tanpa karyawan tidak ditampilkan)
  const baris = useMemo(() => balances.filter((b) => b.employee), [balances]);
  const jumlahKaryawan = useMemo(() => new Set(baris.map((b) => b.employee_id)).size, [baris]);
  const daftarJenis = useMemo(() => {
    const m = new Map();
    baris.forEach((b) => { const n = b.leave_type?.name; if (n) m.set(n, n); });
    return [...m.keys()].sort();
  }, [baris]);
  const q = cari.trim().toLowerCase();
  const tampil = baris
    .filter((b) => !jenis || b.leave_type?.name === jenis)
    .filter((b) => !q || `${b.employee?.name || ''} ${b.employee?.employee_code || ''}`.toLowerCase().includes(q));
  const { page, setPage, totalPages, total, paged } = useClientPagination(tampil, 15);

  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{r.employee?.name}</p>
        <p className="text-xs text-muted-foreground">{r.employee?.employee_code}</p>
      </div>) },
    { kunci: 'jenis', label: 'Jenis cuti', hp: 'keterangan', isi: (r) => r.leave_type?.name || '—' },
    { kunci: 'jatah', label: 'Jatah', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.allocated}</span> },
    { kunci: 'pakai', label: 'Terpakai', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.used}</span> },
    { kunci: 'sisa', label: 'Sisa', rata: 'kanan', isi: (r) => (
      <span className={`font-medium tabular-nums ${r.remaining < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`}>{r.remaining}</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => setEditDialog({ ...r })} data-testid={`balance-edit-${r.id}`}>
        <Pencil />Sesuaikan
      </Button>) },
  ];

  const tahunPilihan = [-2, -1, 0, 1].map((d) => new Date().getFullYear() + d);

  return (
    <PageLayout testId="leave-balances-page" title="Saldo cuti"
      subtitle={`Jatah, pemakaian, dan sisa cuti tiap karyawan per tahun — ${jumlahKaryawan} karyawan tahun ${year}.`}
      actions={<Button onClick={() => setAllocDialog(true)} data-testid="allocate-year"><CalendarDays />Alokasi tahunan</Button>}
      filters={<>
        {/* Tahap 5: tahun dihitung dari tahun berjalan (dulu daftar tetap 2024–2027) */}
        <SmartNativeSelect value={String(year)} onChange={(e) => setYear(Number(e.target.value))} searchable={false}
          className="h-9 w-28" aria-label="Tahun" data-testid="balance-year">
          {tahunPilihan.map((y) => <option key={y} value={String(y)}>{y}</option>)}
        </SmartNativeSelect>
        {daftarJenis.length > 1 && (
          <SmartNativeSelect value={jenis} onChange={(e) => setJenis(e.target.value)} searchable={false}
            className="h-9 w-48" aria-label="Jenis cuti">
            <option value="">Semua jenis cuti</option>
            {daftarJenis.map((n) => <option key={n} value={n}>{n}</option>)}
          </SmartNativeSelect>
        )}
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari nama atau kode karyawan"
            className="pl-8" aria-label="Cari karyawan" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`saldo-cuti-${year}`} namaLembar={`Saldo cuti ${year}`} baris={tampil} testId="balance-unduh"
          kolom={[
            { label: 'Tahun', nilai: () => year },
            { label: 'Kode karyawan', nilai: (r) => r.employee?.employee_code || '' },
            { label: 'Nama karyawan', nilai: (r) => r.employee?.name || '' },
            { label: 'Jenis cuti', nilai: (r) => r.leave_type?.name || '' },
            { label: 'Jatah (hari)', nilai: (r) => Number(r.allocated) || 0 },
            { label: 'Terpakai (hari)', nilai: (r) => Number(r.used) || 0 },
            { label: 'Sisa (hari)', nilai: (r) => Number(r.remaining) || 0 },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={loadError && !loading && (
        /* RC-22: banner error nyata — jangan tampilkan empty-state menyesatkan saat backend gagal */
        <Notice tone="danger" title="Terjadi kesalahan saat memuat data" testId="leave-balances-error">{loadError}</Notice>
      )}
      footer={tampil.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={15} onPageChange={setPage} />}>
      {loading && baris.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat saldo cuti…</p>
      ) : !loadError && (
        <TabelData kolom={kolom} baris={paged} testId="balance-table"
          kosong={<EmptyState icon={CalendarDays}
            title={baris.length ? 'Tidak ada saldo yang cocok' : `Belum ada saldo cuti untuk tahun ${year}`}
            description={baris.length ? 'Ubah kata pencarian atau jenis cuti.' : 'Tekan "Alokasi tahunan" untuk membuat saldo semua karyawan.'} />} />
      )}

      {allocDialog && (
        <AllocateDialog year={year} onSave={handleAllocate} onClose={() => setAllocDialog(false)} />
      )}
      {editDialog && (
        <EditBalanceDialog balance={editDialog} onSave={handleAdjust} onClose={() => setEditDialog(null)} />
      )}
    </PageLayout>
  );
}

function AllocateDialog({ year, onSave, onClose }) {
  const [forceReset, setForceReset] = useState(false);
  const [menyimpan, setMenyimpan] = useState(false);
  const simpan = async () => { setMenyimpan(true); await onSave(forceReset); setMenyimpan(false); };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="allocate-dialog" judul={`Alokasi saldo cuti tahun ${year}`}
      onSimpan={simpan} menyimpan={menyimpan} labelSimpan="Alokasikan">
      <Notice tone="warning">
        Membuat saldo cuti untuk semua karyawan aktif × semua jenis cuti tahun {year}, sesuai kuota bawaan tiap jenis cuti.
      </Notice>
      <label className="flex items-start gap-3 text-sm" htmlFor="alloc-reset">
        <Switch id="alloc-reset" checked={forceReset} onCheckedChange={setForceReset} data-testid="allocate-force-reset" />
        <span>Atur ulang saldo yang sudah ada
          <span className="block text-xs text-[hsl(var(--danger-text))]">Saldo lama diganti dan pemakaian dihitung 0.</span>
        </span>
      </label>
    </FormPopup>
  );
}

function EditBalanceDialog({ balance, onSave, onClose }) {
  const [delta, setDelta] = useState(0);
  const [reason, setReason] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);
  const simpan = async () => { setMenyimpan(true); await onSave({ id: balance.id, delta, reason }); setMenyimpan(false); };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="adjust-dialog"
      judul={`Sesuaikan saldo: ${balance.leave_type?.name || ''}`}
      keterangan={`${balance.employee?.name || ''} — saldo saat ini ${balance.remaining} dari ${balance.allocated} hari (${balance.used} terpakai).`}
      onSimpan={simpan} menyimpan={menyimpan} bisaSimpan={Boolean(delta) && Boolean(reason)}>
      <Isian label="Tambah / kurangi (hari)" htmlFor="adj-delta" petunjuk={`Jatah baru: ${balance.allocated + delta} hari. Angka minus mengurangi.`}>
        <Input id="adj-delta" type="number" value={delta} onChange={e => setDelta(Number(e.target.value))}
          placeholder="Contoh: 3 menambah, -2 mengurangi" data-testid="adjust-delta" />
      </Isian>
      <Isian label="Alasan" wajib htmlFor="adj-reason">
        <Input id="adj-reason" value={reason} onChange={e => setReason(e.target.value)}
          placeholder="Contoh: bonus cuti kinerja, kompensasi hari libur" data-testid="adjust-reason" />
      </Isian>
    </FormPopup>
  );
}
