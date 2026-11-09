/**
 * ShiftRosterModule — Portal SDM › Shift › Roster (Tahap C audit HR, 9 Nov 2026).
 *
 * Roster kalender: baris karyawan × kolom tanggal, sel berwarna shift. Sel = shift yang BERLAKU (draf yang dipilih →
 * jadwal terbit → penugasan → shift utama), sel cuti/izin/sakit disetujui & hari libur terkunci, sel bentrok ditandai.
 * Alur staf SDM: "Susun jadwal" (dari pola rotasi / satu shift / shift yang berlaku / salin minggu) → draf → pilih
 * baris karyawan dan kolom tanggal → "Isi shift" (penugasan massal) → "Salin minggu" → periksa bentrok → Terbitkan.
 * Menggantikan "Jadwal otomatis" yang tidak pernah bisa membuat jadwal (audit H7). Server: `/api/hr/shift-scheduler`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, ListChecks, Plus, RefreshCw, Send, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { todayWIB } from '@/lib/waktu';
import { checkPerm } from '@/lib/rbac';
import { cn } from '@/lib/utils';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { useActiveEmployees, useDepartmentFilterOptions, useHrMasters } from './hrPickers';
import { TitikShift, jamShift, labelSumber, pesanGalat, seninDari, shiftApi, tambahHari, teksDiAtas } from './shiftShared';

const P = '/api/hr/shift-scheduler';
const LAMA = [{ v: '7', l: '1 minggu' }, { v: '14', l: '2 minggu' }, { v: '28', l: '4 minggu' }];
const CARA = [
  { v: 'pola', l: 'Dari pola rotasi' }, { v: 'shift', l: 'Satu shift untuk semua' },
  { v: 'berlaku', l: 'Salin shift yang berlaku sekarang' }, { v: 'salin', l: 'Salin satu minggu' },
];
const TINGKAT = { berat: { label: 'Berat', tone: 'danger' }, peringatan: { label: 'Peringatan', tone: 'warning' }, info: { label: 'Info', tone: 'muted' } };
const STATUS_JADWAL = { draft: { label: 'Draf', tone: 'muted' }, published: { label: 'Terbit', tone: 'success' }, dibatalkan: { label: 'Ditarik', tone: 'muted' } };
const kunciSel = (eid, t) => `${eid}|${t}`;

function useLokasi() {
  const [lokasi, setLokasi] = useState([]);
  useEffect(() => {
    shiftApi('get', '/api/rahaza/locations').then((d) => setLokasi(Array.isArray(d) ? d : (d?.items || []))).catch(() => setLokasi([]));
  }, []);
  return lokasi;
}

/** Satu sel roster: warna shift, kunci cuti/libur, tanda bentrok, tanda terpilih. */
function SelRoster({ sel, shift, terpilih, onKlik }) {
  const warna = shift?.warna;
  const kunci = sel.kunci;
  const isi = shift ? shift.kode : (kunci === 'cuti' ? 'Cuti' : (sel.lj || kunci === 'libur' || sel.ket === 'Libur mingguan' ? 'Libur' : '—'));
  return (
    <TableCell className="p-1 text-center" title={[shift && `${shift.kode} ${jamShift(shift)}`, sel.ket, labelSumber(sel.src)].filter(Boolean).join(' · ')}>
      <span role="button" tabIndex={0} onClick={onKlik} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onKlik(); } }}
        data-testid="roster-sel" aria-pressed={terpilih}
        className={cn('flex h-8 min-w-[3.25rem] cursor-pointer select-none items-center justify-center rounded-md text-xs font-medium',
          !shift && 'text-muted-foreground', kunci && 'bg-muted', sel.setengah && 'italic',
          sel.bentrok === 'berat' && 'ring-2 ring-destructive', sel.bentrok === 'peringatan' && 'ring-2 ring-[hsl(var(--warning))]',
          terpilih && 'outline outline-2 outline-offset-1 outline-primary')}
        style={shift && !kunci ? { backgroundColor: warna, color: teksDiAtas(warna) } : undefined}>
        {isi}
      </span>
    </TableCell>
  );
}

export default function ShiftRosterModule({ user }) {
  const token = localStorage.getItem('erp_token');
  const bolehTulis = checkPerm({ user, roles: ['superadmin', 'admin', 'owner', 'hr', 'manager', 'hr_manager', 'staff_hr'], keys: ['hr.attendance.manage', 'hr.manage'] });
  const [mulai, setMulai] = useState(() => seninDari(todayWIB()));
  const [lama, setLama] = useState('14');
  const [dept, setDept] = useState('');
  const [lok, setLok] = useState('');
  const [cari, setCari] = useState('');
  const [jadwalId, setJadwalId] = useState('');
  const [jadwalList, setJadwalList] = useState([]);
  const [data, setData] = useState(null);
  const [memuat, setMemuat] = useState(false);
  const [pilihBaris, setPilihBaris] = useState(() => new Set());
  const [pilihTgl, setPilihTgl] = useState(() => new Set());
  const [pilihSel, setPilihSel] = useState(() => new Set());
  const [popup, setPopup] = useState(null);   // susun | isi | salin | bentrok | daftar
  const [pola, setPola] = useState([]);
  const { units } = useHrMasters(token, { positions: false, shifts: false });
  const { employees } = useActiveEmployees(token);
  const deptOpsi = useDepartmentFilterOptions(units, employees);
  const lokasi = useLokasi();
  const sampai = tambahHari(mulai, Number(lama) - 1);

  const muatJadwal = useCallback(() => shiftApi('get', `${P}/schedules`, { params: { limit: 200 } })
    .then((d) => setJadwalList(d?.data || [])).catch(() => setJadwalList([])), []);

  const muat = useCallback(async () => {
    setMemuat(true);
    try {
      const d = await shiftApi('get', `${P}/roster`, {
        params: { dari: mulai, sampai, department: dept || undefined, location_id: lok || undefined, jadwal_id: jadwalId || undefined, q: cari || undefined },
      });
      setData(d?.data || null);
    } catch (e) {
      toast.error(pesanGalat(e, 'Roster gagal dimuat.'));
    } finally { setMemuat(false); }
  }, [mulai, sampai, dept, lok, jadwalId, cari]);

  useEffect(() => { muat(); }, [muat]);
  useEffect(() => { muatJadwal(); shiftApi('get', `${P}/pola`).then((d) => setPola(d?.data || [])).catch(() => setPola([])); }, [muatJadwal]);

  const shiftById = useMemo(() => Object.fromEntries((data?.shift || []).map((s) => [s.id, s])), [data]);
  const draf = jadwalList.filter((j) => j.status === 'draft');
  const jadwalAktif = data?.jadwal || null;
  const karyawan = useMemo(() => data?.karyawan || [], [data]);
  const tanggal = useMemo(() => data?.tanggal || [], [data]);
  const jb = data?.jumlah_bentrok || {};

  const kosongkanPilihan = () => { setPilihBaris(new Set()); setPilihTgl(new Set()); setPilihSel(new Set()); };
  const toggle = (set, setter, k) => { const n = new Set(set); if (n.has(k)) n.delete(k); else n.add(k); setter(n); };

  /** Sel sasaran: (baris terpilih × tanggal terpilih) ∪ sel yang diklik satu per satu. */
  const sasaran = useMemo(() => {
    const out = new Set(pilihSel);
    const baris = pilihBaris.size ? [...pilihBaris] : (pilihTgl.size ? karyawan.map((k) => k.id) : []);
    const tgl = pilihTgl.size ? [...pilihTgl] : (pilihBaris.size ? tanggal.map((t) => t.t) : []);
    baris.forEach((eid) => tgl.forEach((t) => out.add(kunciSel(eid, t))));
    return [...out].map((k) => { const [employee_id, date] = k.split('|'); return { employee_id, date }; });
  }, [pilihSel, pilihBaris, pilihTgl, karyawan, tanggal]);

  const terbitkan = async () => {
    if (!jadwalAktif) return;
    const go = async (paksa) => {
      try {
        await shiftApi('patch', `${P}/schedules/${jadwalAktif.id}/publish`, { data: { paksa } });
        toast.success('Jadwal diterbitkan dan mulai dipakai absensi.');
        setJadwalId(''); muatJadwal(); muat();
      } catch (e) {
        const d = e?.response?.data?.detail;
        if (e?.response?.status === 409 && d?.jumlah?.berat && !paksa) {
          if (await confirmDialog({ title: 'Ada jadwal pada hari cuti', body: `${d.message} Terbitkan tetap?`, confirmLabel: 'Terbitkan tetap', danger: true })) go(true);
        } else toast.error(pesanGalat(e, 'Jadwal gagal diterbitkan.'));
      }
    };
    const peringatan = jb.peringatan ? ` Ada ${jb.peringatan} peringatan (lihat Bentrok).` : '';
    if (await confirmDialog({ title: 'Terbitkan jadwal ini?', body: `Jadwal mulai dipakai untuk absen dan hitung terlambat.${peringatan}`, confirmLabel: 'Terbitkan' })) go(false);
  };

  const hapusDraf = async (j) => {
    if (!(await confirmDialog({ title: 'Hapus draf jadwal?', body: j.judul, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await shiftApi('delete', `${P}/schedules/${j.id}`);
      toast.success('Draf dihapus.');
      if (jadwalId === j.id) setJadwalId('');
      muatJadwal(); muat();
    } catch (e) { toast.error(pesanGalat(e)); }
  };

  const tarik = async (j) => {
    if (!(await confirmDialog({ title: 'Tarik jadwal terbit?', body: 'Jadwal belum berlaku; sesudah ditarik absensi kembali memakai penugasan shift.', confirmLabel: 'Tarik', danger: true }))) return;
    try {
      await shiftApi('post', `${P}/schedules/${j.id}/batalkan`);
      toast.success('Jadwal ditarik.');
      muatJadwal(); muat();
    } catch (e) { toast.error(pesanGalat(e)); }
  };

  // ── kepala tabel ──────────────────────────────────────────────────────────
  const semuaTerpilih = karyawan.length > 0 && karyawan.every((k) => pilihBaris.has(k.id));
  const grid = (
    <Table stickyFirstCol data-testid="roster-grid">
      <TableHeader>
        <TableRow>
          <TableHead className="min-w-[13rem]">
            <span className="inline-flex items-center gap-2">
              <Checkbox checked={semuaTerpilih} aria-label="Pilih semua karyawan"
                onCheckedChange={(v) => setPilihBaris(v ? new Set(karyawan.map((k) => k.id)) : new Set())} />
              Karyawan
            </span>
          </TableHead>
          {tanggal.map((t) => (
            <TableHead key={t.t} className={cn('p-1 text-center', t.libur && 'text-muted-foreground')}>
              <Button type="button" size="sm" variant={pilihTgl.has(t.t) ? 'default' : 'outline'} className="w-full px-1"
                onClick={() => toggle(pilihTgl, setPilihTgl, t.t)} title={t.libur || 'Pilih tanggal ini'} data-testid="roster-tanggal">
                {t.label.replace(/ \w+$/, '')}
              </Button>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {karyawan.length === 0 && (
          <TableRow className="hover:bg-transparent">
            <TableCell colSpan={tanggal.length + 1} className="p-0 [&>div]:py-8">
              <EmptyState title="Belum ada karyawan aktif" description="Ubah penyaring departemen/lokasi, atau tambah karyawan di Data Karyawan." />
            </TableCell>
          </TableRow>
        )}
        {karyawan.map((k) => (
          <TableRow key={k.id} data-testid="roster-baris">
            <TableCell className="min-w-[13rem]">
              <label className="flex cursor-pointer items-center gap-2">
                <Checkbox checked={pilihBaris.has(k.id)} onCheckedChange={() => toggle(pilihBaris, setPilihBaris, k.id)} aria-label={`Pilih ${k.nama}`} />
                <span className="min-w-0">
                  <span className="block truncate font-medium text-foreground">{k.nama}</span>
                  <span className="block truncate text-xs text-muted-foreground">{[k.kode, k.departemen].filter(Boolean).join(' · ')}</span>
                </span>
              </label>
            </TableCell>
            {k.sel.map((c) => (
              <SelRoster key={c.t} sel={c} shift={c.s ? shiftById[c.s] : null} terpilih={pilihSel.has(kunciSel(k.id, c.t)) || (pilihBaris.has(k.id) && pilihTgl.has(c.t))}
                onKlik={() => toggle(pilihSel, setPilihSel, kunciSel(k.id, c.t))} />
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );

  const unduhKolom = useMemo(() => [
    { label: 'Kode', nilai: (k) => k.kode }, { label: 'Karyawan', nilai: (k) => k.nama }, { label: 'Departemen', nilai: (k) => k.departemen },
    ...tanggal.map((t, i) => ({ label: t.label, nilai: (k) => { const c = k.sel[i]; const s = c?.s ? shiftById[c.s] : null; return s ? s.kode : (c?.ket || ''); } })),
  ], [tanggal, shiftById]);

  const ringkasan = data && (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground" data-testid="roster-ringkasan">
      <span>
        {jadwalAktif ? <>Menyusun draf <span className="font-medium text-foreground">{jadwalAktif.judul}</span> · </> : 'Menampilkan shift yang berlaku · '}
        <span className="font-medium text-foreground">{karyawan.length}</span> karyawan
        {sasaran.length > 0 && <> · <span className="font-medium text-foreground">{sasaran.length}</span> sel terpilih</>}
      </span>
      {(jb.berat || jb.peringatan) ? (
        <Button variant="link" className="h-auto p-0" onClick={() => setPopup('bentrok')} data-testid="roster-bentrok">
          <AlertTriangle />Bentrok: {jb.berat || 0} berat, {jb.peringatan || 0} peringatan
        </Button>
      ) : <span>Tidak ada bentrok.</span>}
      <span className="flex flex-wrap items-center gap-3">
        {(data.shift || []).map((s) => <TitikShift key={s.id} kode={s.kode} warna={s.warna} />)}
      </span>
    </div>
  );

  const aksi = bolehTulis && (jadwalAktif ? (<>
    <Button variant="outline" onClick={() => setPopup('isi')} disabled={!sasaran.length} data-testid="roster-isi">Isi shift{sasaran.length ? ` (${sasaran.length})` : ''}</Button>
    <Button variant="outline" onClick={() => setPopup('salin')} data-testid="roster-salin">Salin minggu</Button>
    <Button onClick={terbitkan} data-testid="roster-terbit"><Send />Terbitkan</Button>
  </>) : (
    <Button onClick={() => setPopup('susun')} data-testid="roster-susun"><Plus />Susun jadwal</Button>
  ));

  return (
    <PageLayout testId="shift-roster" title="Roster shift"
      subtitle="Siapa masuk shift apa per tanggal. Sel abu = cuti atau libur (terkunci)."
      actions={aksi}
      filters={<>
        <Button variant="outline" size="icon" onClick={() => setMulai(tambahHari(mulai, -7))} title="Minggu sebelumnya" aria-label="Minggu sebelumnya"><ChevronLeft /></Button>
        <div className="w-40"><DatePicker value={mulai} onChange={(v) => v && setMulai(v)} bolehKosong={false} testId="roster-mulai" /></div>
        <Button variant="outline" size="icon" onClick={() => setMulai(tambahHari(mulai, 7))} title="Minggu berikutnya" aria-label="Minggu berikutnya"><ChevronRight /></Button>
        <SmartNativeSelect value={lama} onChange={(e) => setLama(e.target.value)} searchable={false} className="h-9 w-32" aria-label="Lama tampilan">
          {LAMA.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={dept} onChange={(e) => setDept(e.target.value)} className="h-9 w-44" aria-label="Departemen" data-testid="roster-dept">
          <option value="">Semua departemen</option>
          {deptOpsi.map((d) => <option key={d.value} value={d.value}>{d.legacy ? d.value : d.label}</option>)}
        </SmartNativeSelect>
        {lokasi.length > 1 && (
          <SmartNativeSelect value={lok} onChange={(e) => setLok(e.target.value)} className="h-9 w-40" aria-label="Lokasi">
            <option value="">Semua lokasi</option>
            {lokasi.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </SmartNativeSelect>
        )}
        <SmartNativeSelect value={jadwalId} onChange={(e) => { setJadwalId(e.target.value); kosongkanPilihan(); }} className="h-9 w-56" aria-label="Draf jadwal" data-testid="roster-draf">
          <option value="">Jadwal berlaku (tanpa draf)</option>
          {draf.map((j) => <option key={j.id} value={j.id}>{`Draf: ${j.judul}`}</option>)}
        </SmartNativeSelect>
        <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari karyawan" className="h-9 w-48" aria-label="Cari karyawan" />
      </>}
      tools={<>
        {(sasaran.length > 0) && <Button variant="outline" onClick={kosongkanPilihan}>Batal pilih</Button>}
        <Button variant="outline" size="icon" onClick={() => setPopup('daftar')} title="Daftar jadwal" aria-label="Daftar jadwal"><ListChecks /></Button>
        <TombolUnduh namaBerkas={`roster-shift-${mulai}`} namaLembar="Roster" baris={karyawan} kolom={unduhKolom} testId="roster-unduh" />
        <Button variant="outline" size="icon" onClick={() => { muat(); muatJadwal(); }} disabled={memuat} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={ringkasan}>
      {memuat && !data ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat roster…</p> : grid}

      <SusunJadwal open={popup === 'susun'} onClose={() => setPopup(null)} pola={pola} shifts={data?.shift || []} deptOpsi={deptOpsi}
        lokasi={lokasi} mulaiAwal={mulai} sampaiAwal={sampai} dept={dept} terpilih={[...pilihBaris]}
        onSelesai={(j) => { setPopup(null); muatJadwal(); setJadwalId(j.id); kosongkanPilihan(); }} />
      <IsiShift open={popup === 'isi'} onClose={() => setPopup(null)} shifts={data?.shift || []} sasaran={sasaran} jadwal={jadwalAktif}
        onSelesai={() => { setPopup(null); kosongkanPilihan(); muat(); }} />
      <SalinMinggu open={popup === 'salin'} onClose={() => setPopup(null)} jadwal={jadwalAktif} mulai={mulai}
        onSelesai={() => { setPopup(null); muat(); muatJadwal(); }} />
      <DetailPopup open={popup === 'bentrok'} onClose={() => setPopup(null)} judul="Bentrok jadwal" testId="roster-bentrok-popup"
        keterangan="Berat = jadwal pada cuti/izin yang sudah disetujui (tidak berlaku hari itu). Peringatan boleh diterbitkan.">
        <TabelData baris={data?.bentrok || []} kunci={(b) => `${b.employee_id}-${b.date}-${b.jenis}`} testId="roster-bentrok-tabel"
          kolom={[
            { kunci: 'tingkat', label: 'Tingkat', isi: (b) => <StatusBadge status={b.tingkat} label={TINGKAT[b.tingkat]?.label} tone={TINGKAT[b.tingkat]?.tone} /> },
            { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (b) => b.karyawan },
            { kunci: 'tanggal', label: 'Tanggal', isi: (b) => b.tanggal },
            { kunci: 'pesan', label: 'Masalah', hp: 'keterangan', isi: (b) => b.pesan },
          ]}
          kosong={<EmptyState title="Tidak ada bentrok" />} />
      </DetailPopup>
      <DetailPopup open={popup === 'daftar'} onClose={() => setPopup(null)} judul="Daftar jadwal" testId="roster-daftar-popup"
        keterangan="Draf belum dipakai absensi. Jadwal terbit terbaru menang bila tanggalnya bertumpuk.">
        <TabelData baris={jadwalList} testId="roster-daftar-tabel"
          kolom={[
            { kunci: 'judul', label: 'Jadwal', hp: 'judul', isi: (j) => <span className="font-medium text-foreground">{j.judul || `${j.start_date} – ${j.end_date}`}</span> },
            { kunci: 'periode', label: 'Periode', hp: 'keterangan', isi: (j) => `${j.start_date} s.d. ${j.end_date}` },
            { kunci: 'shift', label: 'Shift terjadwal', rata: 'kanan', isi: (j) => <span className="tabular-nums">{j.metadata?.total_shifts ?? '—'}</span> },
            { kunci: 'status', label: 'Status', isi: (j) => { const s = STATUS_JADWAL[j.status] || { label: j.status, tone: 'muted' }; return <StatusBadge status={j.status} label={s.label} tone={s.tone} />; } },
            { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (j) => (
              <div className="flex justify-end gap-1">
                {j.status === 'draft' && <Button size="sm" variant="outline" onClick={() => { setJadwalId(j.id); setPopup(null); setMulai(seninDari(j.start_date)); }}>Buka</Button>}
                {bolehTulis && j.status === 'draft' && <Button size="icon-sm" variant="ghost" onClick={() => hapusDraf(j)} title="Hapus draf" aria-label="Hapus draf"><Trash2 /></Button>}
                {bolehTulis && j.status === 'published' && j.start_date > todayWIB() && <Button size="sm" variant="outline" onClick={() => tarik(j)}>Tarik</Button>}
              </div>) },
          ]}
          kosong={<EmptyState title="Belum ada jadwal" description="Klik Susun jadwal untuk membuat draf pertama." />} />
      </DetailPopup>
    </PageLayout>
  );
}

function SusunJadwal({ open, onClose, pola, shifts, deptOpsi, lokasi, mulaiAwal, sampaiAwal, dept, terpilih, onSelesai }) {
  const awal = () => ({ judul: '', start_date: mulaiAwal, end_date: sampaiAwal, lingkup: terpilih.length ? 'pilihan' : 'departemen',
    department: dept, location_id: '', cara: pola.length ? 'pola' : 'shift', pola_id: pola[0]?.id || '', mulai_pola: mulaiAwal,
    shift_id: '', salin_dari: tambahHari(mulaiAwal, -7), isi_libur: false });
  const [f, setF] = useState(awal);
  const [pratinjau, setPratinjau] = useState(null);
  const [menyimpan, setMenyimpan] = useState(false);
  const [galat, setGalat] = useState('');
  useEffect(() => { if (open) { setF(awal()); setPratinjau(null); setGalat(''); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const ubah = (k, v) => { setF((p) => ({ ...p, [k]: v })); setPratinjau(null); };
  const isian = () => ({
    start_date: f.start_date, end_date: f.end_date, cara: f.cara,
    department: f.lingkup === 'departemen' ? (f.department || undefined) : undefined,
    location_id: f.lingkup === 'lokasi' ? (f.location_id || undefined) : undefined,
    employee_ids: f.lingkup === 'pilihan' ? terpilih : undefined,
    pola_id: f.cara === 'pola' ? f.pola_id : undefined, mulai_pola: f.cara === 'pola' ? f.mulai_pola : undefined,
    shift_id: f.cara === 'shift' ? f.shift_id : undefined, salin_dari: f.cara === 'salin' ? f.salin_dari : undefined,
    isi_libur: f.isi_libur,
  });
  const lihat = async () => {
    setGalat('');
    try {
      const b = isian();
      const d = await shiftApi('get', `${P}/schedules/pratinjau`, { params: { ...b, employee_ids: b.employee_ids ? b.employee_ids.join(',') : undefined } });
      setPratinjau(d?.data || null);
    } catch (e) { setGalat(pesanGalat(e, 'Pratinjau gagal.')); }
  };
  const simpan = async () => {
    setMenyimpan(true); setGalat('');
    try {
      const d = await shiftApi('post', `${P}/schedules`, { data: { ...isian(), judul: f.judul || undefined } });
      toast.success(d?.message || 'Draf jadwal dibuat.');
      onSelesai(d?.data || {});
    } catch (e) { setGalat(pesanGalat(e, 'Jadwal gagal disusun.')); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="roster-susun-form" judul="Susun jadwal"
      keterangan="Hasilnya draf: belum dipakai absensi sampai diterbitkan. Hari cuti disetujui dilewati."
      onSimpan={simpan} menyimpan={menyimpan} galat={galat} labelSimpan="Buat draf"
      aksiKiri={<Button type="button" variant="outline" onClick={lihat} data-testid="roster-pratinjau">Pratinjau</Button>}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Mulai" wajib><DatePicker value={f.start_date} onChange={(v) => ubah('start_date', v)} bolehKosong={false} testId="susun-mulai" /></Isian>
        <Isian label="Selesai" wajib petunjuk="Paling panjang 62 hari."><DatePicker value={f.end_date} min={f.start_date} onChange={(v) => ubah('end_date', v)} bolehKosong={false} testId="susun-selesai" /></Isian>
        <Isian label="Karyawan">
          <SmartNativeSelect value={f.lingkup} onChange={(e) => ubah('lingkup', e.target.value)} searchable={false} className="w-full" data-testid="susun-lingkup">
            <option value="departemen">Per departemen</option>
            <option value="lokasi">Per lokasi</option>
            {terpilih.length > 0 && <option value="pilihan">{`Baris terpilih (${terpilih.length} karyawan)`}</option>}
          </SmartNativeSelect>
        </Isian>
        {f.lingkup === 'departemen' && (
          <Isian label="Departemen" petunjuk="Kosong = semua karyawan aktif.">
            <SmartNativeSelect value={f.department} onChange={(e) => ubah('department', e.target.value)} className="w-full">
              <option value="">Semua departemen</option>
              {deptOpsi.map((d) => <option key={d.value} value={d.value}>{d.legacy ? d.value : d.label}</option>)}
            </SmartNativeSelect>
          </Isian>
        )}
        {f.lingkup === 'lokasi' && (
          <Isian label="Lokasi">
            <SmartNativeSelect value={f.location_id} onChange={(e) => ubah('location_id', e.target.value)} className="w-full">
              <option value="">— Pilih lokasi —</option>
              {lokasi.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </SmartNativeSelect>
          </Isian>
        )}
        <Isian label="Cara menyusun" wajib>
          <SmartNativeSelect value={f.cara} onChange={(e) => ubah('cara', e.target.value)} searchable={false} className="w-full" data-testid="susun-cara">
            {CARA.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}
          </SmartNativeSelect>
        </Isian>
        {f.cara === 'pola' && (<>
          <Isian label="Pola rotasi" wajib petunjuk={pola.length ? '' : 'Belum ada pola — buat di tab Pola rotasi.'}>
            <SmartNativeSelect value={f.pola_id} onChange={(e) => ubah('pola_id', e.target.value)} className="w-full" data-testid="susun-pola">
              <option value="">— Pilih pola —</option>
              {pola.map((p) => <option key={p.id} value={p.id}>{`${p.nama} (${p.minggu} minggu)`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Hari pertama pola" petunjuk="Tanggal yang memakai hari ke-1 pola."><DatePicker value={f.mulai_pola} onChange={(v) => ubah('mulai_pola', v)} bolehKosong={false} testId="susun-mulai-pola" /></Isian>
        </>)}
        {f.cara === 'shift' && (
          <Isian label="Shift" wajib petunjuk="Hari di luar hari kerja shift menjadi libur.">
            <SmartNativeSelect value={f.shift_id} onChange={(e) => ubah('shift_id', e.target.value)} className="w-full" data-testid="susun-shift">
              <option value="">— Pilih shift —</option>
              {shifts.map((s) => <option key={s.id} value={s.id}>{`${s.kode} — ${s.nama} (${jamShift(s)})`}</option>)}
            </SmartNativeSelect>
          </Isian>
        )}
        {f.cara === 'salin' && (
          <Isian label="Minggu sumber" petunjuk="Tanggal mana saja di minggu yang disalin."><DatePicker value={f.salin_dari} onChange={(v) => ubah('salin_dari', v)} bolehKosong={false} testId="susun-salin" /></Isian>
        )}
      </div>
      <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
        <Checkbox checked={f.isi_libur} onCheckedChange={(v) => ubah('isi_libur', !!v)} />
        Tetap jadwalkan di hari libur kalender (libur nasional/perusahaan)
      </label>
      <Isian label="Judul" petunjuk="Kosong = dibuat otomatis dari periode dan cara."><Input value={f.judul} onChange={(e) => ubah('judul', e.target.value)} /></Isian>
      {pratinjau && (
        <div className="space-y-1 text-sm" data-testid="roster-pratinjau-hasil">
          <p className="text-foreground">
            {pratinjau.karyawan} karyawan · {pratinjau.metadata?.total_shifts} shift terjadwal · {pratinjau.metadata?.hari_libur} hari libur
            {pratinjau.dilewati?.length ? ` · ${pratinjau.dilewati.length} hari cuti dilewati` : ''}
          </p>
          <p className="text-muted-foreground">
            Bentrok: {pratinjau.jumlah_bentrok?.berat || 0} berat, {pratinjau.jumlah_bentrok?.peringatan || 0} peringatan.
            {' '}Per shift: {(pratinjau.metadata?.per_shift || []).map((p) => `${p.kode} ${p.jumlah}`).join(', ') || '—'}.
          </p>
        </div>
      )}
    </FormPopup>
  );
}

function IsiShift({ open, onClose, shifts, sasaran, jadwal, onSelesai }) {
  const [shiftId, setShiftId] = useState('');
  const [isiLibur, setIsiLibur] = useState(false);
  const [menyimpan, setMenyimpan] = useState(false);
  const [galat, setGalat] = useState('');
  useEffect(() => { if (open) { setShiftId(''); setIsiLibur(false); setGalat(''); } }, [open]);
  const simpan = async () => {
    if (!shiftId) { setGalat('Pilih shift atau Libur.'); return; }
    setMenyimpan(true); setGalat('');
    try {
      const d = await shiftApi('patch', `${P}/schedules/${jadwal.id}/sel`, {
        data: { perubahan: sasaran.map((s) => ({ ...s, shift_id: shiftId === 'LIBUR' ? null : shiftId })), isi_libur: isiLibur },
      });
      toast.success(d?.message || 'Sel diubah.');
      onSelesai();
    } catch (e) { setGalat(pesanGalat(e, 'Sel gagal diubah.')); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open={open && !!jadwal} onClose={onClose} testId="roster-isi-form" judul={`Isi ${sasaran.length} sel`}
      keterangan="Sel cuti yang sudah disetujui dilewati." onSimpan={simpan} menyimpan={menyimpan} galat={galat} labelSimpan="Isi">
      <Isian label="Shift" wajib>
        <SmartNativeSelect value={shiftId} onChange={(e) => setShiftId(e.target.value)} className="w-full" data-testid="isi-shift">
          <option value="">— Pilih —</option>
          <option value="LIBUR">Libur</option>
          {shifts.map((s) => <option key={s.id} value={s.id}>{`${s.kode} — ${s.nama} (${jamShift(s)})`}</option>)}
        </SmartNativeSelect>
      </Isian>
      <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
        <Checkbox checked={isiLibur} onCheckedChange={(v) => setIsiLibur(!!v)} />
        Isi juga sel hari libur kalender
      </label>
    </FormPopup>
  );
}

function SalinMinggu({ open, onClose, jadwal, mulai, onSelesai }) {
  const [dari, setDari] = useState(mulai);
  const [ke, setKe] = useState(tambahHari(mulai, 7));
  const [menyimpan, setMenyimpan] = useState(false);
  const [galat, setGalat] = useState('');
  useEffect(() => { if (open) { setDari(jadwal?.start_date || mulai); setKe(tambahHari(seninDari(jadwal?.start_date || mulai), 7)); setGalat(''); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const simpan = async () => {
    setMenyimpan(true); setGalat('');
    try {
      const d = await shiftApi('post', `${P}/schedules/${jadwal.id}/salin-minggu`, { data: { dari, ke } });
      toast.success(d?.message || 'Minggu disalin.');
      onSelesai();
    } catch (e) { setGalat(pesanGalat(e, 'Minggu gagal disalin.')); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open={open && !!jadwal} onClose={onClose} testId="roster-salin-form" judul="Salin minggu"
      keterangan="Isi Senin–Minggu disalin ke minggu tujuan; rentang draf diperpanjang bila perlu."
      onSimpan={simpan} menyimpan={menyimpan} galat={galat} labelSimpan="Salin">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Dari minggu" wajib><DatePicker value={dari} onChange={(v) => v && setDari(v)} bolehKosong={false} testId="salin-dari" /></Isian>
        <Isian label="Ke minggu" wajib><DatePicker value={ke} onChange={(v) => v && setKe(v)} bolehKosong={false} testId="salin-ke" /></Isian>
      </div>
    </FormPopup>
  );
}
