/**
 * ShiftPolaModule — Portal SDM › Shift › Pola rotasi (Tahap C audit HR, 9 Nov 2026).
 *
 * Pola = urutan shift per hari (1–8 minggu) yang diulang, mis. "2 minggu pagi lalu 2 minggu siang". Pola memakai
 * shift dari Daftar shift (satu master shift) — menggantikan "Pola jadwal" lama yang menyimpan jam shift sendiri.
 * Isi cepat per minggu memakai hari kerja shift (hari di luar hari kerja = libur); tiap hari bisa diubah.
 * Dipakai Roster › Susun jadwal › "Dari pola rotasi". Server: `/api/hr/shift-scheduler/pola`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, Power, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { checkPerm } from '@/lib/rbac';
import PageLayout from '../layout/PageLayout';
import { EmptyState } from '../moduleAtoms';
import { HARI_KODE, HARI_PENDEK, TitikShift, jamShift, pesanGalat, shiftApi } from './shiftShared';

const P = '/api/hr/shift-scheduler';

/** "M1: PAGI 6 hari, libur 1 · M2: SIANG 6 hari, libur 1" */
export function ringkasPola(urutan = [], kodeById = {}) {
  const minggu = [];
  for (let w = 0; w < urutan.length / 7; w += 1) {
    const hit = {};
    urutan.slice(w * 7, w * 7 + 7).forEach((sid) => { const k = sid ? (kodeById[sid] || '?') : 'libur'; hit[k] = (hit[k] || 0) + 1; });
    minggu.push(`M${w + 1}: ${Object.entries(hit).map(([k, n]) => `${k} ${n}`).join(', ')}`);
  }
  return minggu.join(' · ');
}

/** Isi satu minggu dari satu shift: hari kerja shift → shift, hari lain → libur. */
export function mingguDariShift(shift) {
  return HARI_KODE.map((h) => (shift && (shift.hari_aktif || shift.days_active || HARI_KODE.slice(0, 6)).includes(h) ? shift.id : null));
}

function FormPola({ open, awal, shifts, onClose, onSimpan }) {
  const kosong = () => ({ nama: '', keterangan: '', urutan: Array(7).fill(null) });
  const [f, setF] = useState(kosong);
  const [menyimpan, setMenyimpan] = useState(false);
  const [galat, setGalat] = useState('');
  useEffect(() => { if (open) { setF(awal ? { nama: awal.nama, keterangan: awal.keterangan || '', urutan: [...awal.urutan] } : kosong()); setGalat(''); } }, [open, awal]);
  const minggu = f.urutan.length / 7;
  const shiftById = useMemo(() => Object.fromEntries(shifts.map((s) => [s.id, s])), [shifts]);
  const setMinggu = (n) => setF((p) => {
    const u = p.urutan.slice(0, n * 7);
    // minggu baru = salinan minggu terakhir (biasanya hanya perlu diganti shiftnya)
    while (u.length < n * 7) {
      const terakhir = u.length >= 7 ? u.slice(-7) : Array(7).fill(null);
      u.push(...terakhir);
    }
    return { ...p, urutan: u };
  });
  const isiMinggu = (w, sid) => setF((p) => {
    const u = [...p.urutan];
    mingguDariShift(shiftById[sid]).forEach((v, i) => { u[w * 7 + i] = v; });
    return { ...p, urutan: u };
  });
  const ubahHari = (i, v) => setF((p) => { const u = [...p.urutan]; u[i] = v || null; return { ...p, urutan: u }; });
  const simpan = async () => {
    if (f.nama.trim().length < 2) { setGalat('Nama pola wajib diisi.'); return; }
    if (!f.urutan.some(Boolean)) { setGalat('Isi minimal satu hari dengan shift.'); return; }
    setMenyimpan(true); setGalat('');
    try { await onSimpan(f); } catch (e) { setGalat(pesanGalat(e, 'Pola gagal disimpan.')); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="pola-form" judul={awal ? `Ubah pola ${awal.nama}` : 'Pola rotasi baru'}
      keterangan="Pola diulang terus dari hari pertama yang dipilih saat menyusun jadwal."
      onSimpan={simpan} menyimpan={menyimpan} galat={galat} labelSimpan={awal ? 'Simpan perubahan' : 'Buat pola'}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Nama pola" wajib htmlFor="pola-nama">
          <Input id="pola-nama" value={f.nama} onChange={(e) => setF((p) => ({ ...p, nama: e.target.value }))} placeholder="Rotasi pagi–siang 2 minggu" />
        </Isian>
        <Isian label="Lama satu putaran">
          <SmartNativeSelect value={String(minggu)} onChange={(e) => setMinggu(Number(e.target.value))} searchable={false} className="w-full" data-testid="pola-minggu">
            {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => <option key={n} value={n}>{`${n} minggu`}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
      {Array.from({ length: minggu }, (_, w) => (
        <Isian key={w} label={`Minggu ke-${w + 1}`}>
          <div className="space-y-2">
            <SmartNativeSelect value="" onChange={(e) => e.target.value && isiMinggu(w, e.target.value)} searchable={false}
              className="w-full sm:w-72" aria-label={`Isi minggu ke-${w + 1} dengan satu shift`} data-testid={`pola-isi-minggu-${w}`}>
              <option value="">Isi cepat seminggu dengan…</option>
              {shifts.map((s) => <option key={s.id} value={s.id}>{`${s.kode} (${jamShift(s)})`}</option>)}
            </SmartNativeSelect>
            <div className="grid grid-cols-7 gap-1">
              {HARI_PENDEK.map((h, i) => {
                const idx = w * 7 + i;
                return (
                  <div key={h} className="min-w-0">
                    <p className="text-center text-xs text-muted-foreground">{h}</p>
                    <SmartNativeSelect value={f.urutan[idx] || ''} onChange={(e) => ubahHari(idx, e.target.value)} searchable={false}
                      className="h-9 w-full px-1 text-xs" aria-label={`Minggu ${w + 1} ${h}`} data-testid="pola-hari">
                      <option value="">Libur</option>
                      {shifts.map((s) => <option key={s.id} value={s.id}>{s.kode}</option>)}
                    </SmartNativeSelect>
                  </div>
                );
              })}
            </div>
          </div>
        </Isian>
      ))}
      <Isian label="Keterangan" htmlFor="pola-ket">
        <Input id="pola-ket" value={f.keterangan} onChange={(e) => setF((p) => ({ ...p, keterangan: e.target.value }))} placeholder="Untuk tim packing" />
      </Isian>
    </FormPopup>
  );
}

export default function ShiftPolaModule({ user }) {
  const bolehTulis = checkPerm({ user, roles: ['superadmin', 'admin', 'owner', 'hr', 'manager', 'hr_manager', 'staff_hr'], keys: ['hr.attendance.manage', 'hr.manage'] });
  const [pola, setPola] = useState([]);
  const [shifts, setShifts] = useState([]);
  const [memuat, setMemuat] = useState(false);
  const [form, setForm] = useState(null);   // null | {} baru | pola
  const kodeById = useMemo(() => Object.fromEntries(shifts.map((s) => [s.id, s.kode])), [shifts]);

  const muat = useCallback(async () => {
    setMemuat(true);
    try {
      const [p, s] = await Promise.all([shiftApi('get', `${P}/pola`), shiftApi('get', '/api/hr/shifts', { params: { include_default: false } })]);
      setPola(p?.data || []);
      setShifts((s?.data || []).map((x) => ({ id: String(x.id), kode: x.shift_code, nama: x.shift_name, mulai: x.start_time, selesai: x.end_time, warna: x.color, hari_aktif: x.days_active })));
    } catch (e) { toast.error(pesanGalat(e, 'Pola gagal dimuat.')); } finally { setMemuat(false); }
  }, []);
  useEffect(() => { muat(); }, [muat]);

  const simpan = async (f) => {
    const body = { nama: f.nama.trim(), keterangan: f.keterangan, urutan: f.urutan };
    if (form?.id) await shiftApi('put', `${P}/pola/${form.id}`, { data: body });
    else await shiftApi('post', `${P}/pola`, { data: body });
    toast.success('Pola disimpan.');
    setForm(null);
    muat();
  };

  const nonaktif = async (p) => {
    if (!(await confirmDialog({ title: `Nonaktifkan pola ${p.nama}?`, body: 'Jadwal yang sudah dibuat dari pola ini tidak berubah.', confirmLabel: 'Nonaktifkan', danger: true }))) return;
    try { await shiftApi('delete', `${P}/pola/${p.id}`); toast.success('Pola dinonaktifkan.'); muat(); } catch (e) { toast.error(pesanGalat(e)); }
  };

  const kolom = [
    { kunci: 'nama', label: 'Nama pola', hp: 'judul', isi: (p) => <span className="font-medium text-foreground">{p.nama}</span> },
    { kunci: 'lama', label: 'Satu putaran', isi: (p) => `${p.minggu} minggu` },
    { kunci: 'urutan', label: 'Isi pola', hp: 'keterangan', isi: (p) => (
      <div className="flex flex-wrap items-center gap-2">
        {[...new Set(p.urutan.filter(Boolean))].map((sid) => { const s = shifts.find((x) => x.id === sid); return <TitikShift key={sid} kode={s?.kode || '?'} warna={s?.warna} />; })}
        <span className="text-xs text-muted-foreground">{ringkasPola(p.urutan, kodeById)}</span>
      </div>) },
    { kunci: 'ket', label: 'Keterangan', isi: (p) => p.keterangan || '—' },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => (bolehTulis ? (
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => setForm(p)}><Pencil />Ubah</Button>
        <Button size="icon-sm" variant="ghost" onClick={() => nonaktif(p)} title="Nonaktifkan" aria-label="Nonaktifkan"><Power /></Button>
      </div>) : null) },
  ];

  return (
    <PageLayout testId="shift-pola" title="Pola rotasi" subtitle="Urutan shift berulang per minggu, dipakai saat menyusun roster."
      actions={bolehTulis && <Button onClick={() => setForm({})} disabled={!shifts.length} data-testid="pola-baru"><Plus />Pola baru</Button>}
      tools={<>
        <TombolUnduh namaBerkas="pola-rotasi-shift" namaLembar="Pola rotasi" baris={pola} testId="pola-unduh"
          kolom={[{ label: 'Nama pola', nilai: (p) => p.nama }, { label: 'Minggu', nilai: (p) => p.minggu },
            { label: 'Isi pola', nilai: (p) => ringkasPola(p.urutan, kodeById) }, { label: 'Keterangan', nilai: (p) => p.keterangan || '' }]} />
        <Button variant="outline" size="icon" onClick={muat} disabled={memuat} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className={memuat ? 'animate-spin' : ''} /></Button>
      </>}>
      <TabelData kolom={kolom} baris={pola} testId="pola-tabel" onKlikBaris={bolehTulis ? (p) => setForm(p) : undefined}
        kosong={<EmptyState title="Belum ada pola rotasi"
          description={shifts.length ? 'Buat pola, mis. 2 minggu shift pagi lalu 2 minggu shift siang.' : 'Isi Daftar shift dulu, lalu buat pola.'} />} />
      <FormPola open={form !== null} awal={form?.id ? form : null} shifts={shifts} onClose={() => setForm(null)} onSimpan={simpan} />
    </PageLayout>
  );
}
