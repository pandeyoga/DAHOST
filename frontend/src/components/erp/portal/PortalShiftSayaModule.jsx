/**
 * PortalShiftSayaModule — Portal Saya › Jadwal Shift (Tahap C audit HR, 9 Nov 2026).
 *
 * Karyawan melihat shift 2 minggu ke depan (sumber sama dengan hitung terlambat), lalu mengajukan:
 *   • Ganti shift   — pilih shift lain untuk satu tanggal → atasan langsung → SDM;
 *   • Tukar shift   — bertukar dengan rekan satu departemen → rekan setuju → atasan → SDM.
 * Rekan yang diajak menjawab di sini; atasan langsung (dari data karyawan) menyetujui tim-nya di sini juga.
 * Server: `/api/portal/shift` (milik sendiri) — tahap SDM di Portal SDM › Shift › Permintaan shift.
 */
import { useCallback, useEffect, useState } from 'react';
import { Check, Plus, RefreshCw, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { todayWIB } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { TitikShift, jamShift, labelSumber, pesanGalat, shiftApi } from '../hr/shiftShared';
import { NADA_STATUS, PerubahanShift } from '../hr/ShiftPermintaanModule';

const P = '/api/portal/shift';

function FormAjukan({ open, tanggalAwal, onClose, onSelesai }) {
  const kosong = () => ({ jenis: 'ganti', tanggal: tanggalAwal || todayWIB(), shift_id: '', rekan_employee_id: '', alasan: '' });
  const [f, setF] = useState(kosong);
  const [shifts, setShifts] = useState([]);
  const [rekan, setRekan] = useState([]);
  const [menyimpan, setMenyimpan] = useState(false);
  const [galat, setGalat] = useState('');
  useEffect(() => { if (open) { setF(kosong()); setGalat(''); } }, [open, tanggalAwal]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    shiftApi('get', '/api/hr/shifts', { params: { include_default: false } }).then((d) => setShifts(d?.data || [])).catch(() => setShifts([]));
  }, [open]);
  useEffect(() => {
    if (!open || f.jenis !== 'tukar' || !f.tanggal) return;
    shiftApi('get', `${P}/rekan`, { params: { tanggal: f.tanggal } }).then((d) => setRekan(d?.rekan || [])).catch(() => setRekan([]));
  }, [open, f.jenis, f.tanggal]);
  const ubah = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const simpan = async () => {
    if (f.alasan.trim().length < 5) { setGalat('Tulis alasan (minimal 5 huruf).'); return; }
    if (f.jenis === 'ganti' && !f.shift_id) { setGalat('Pilih shift tujuan.'); return; }
    if (f.jenis === 'tukar' && !f.rekan_employee_id) { setGalat('Pilih rekan.'); return; }
    setMenyimpan(true); setGalat('');
    try {
      const d = await shiftApi('post', `${P}/permintaan`, { data: { ...f, shift_id: f.jenis === 'ganti' ? f.shift_id : undefined,
        rekan_employee_id: f.jenis === 'tukar' ? f.rekan_employee_id : undefined } });
      toast.success(d?.message || 'Permintaan terkirim.');
      onSelesai();
    } catch (e) { setGalat(pesanGalat(e, 'Permintaan gagal dikirim.')); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open={open} onClose={onClose} testId="shift-saya-form" judul="Ajukan perubahan shift"
      keterangan="Tukar shift menunggu rekan setuju, lalu atasan langsung dan SDM." onSimpan={simpan} menyimpan={menyimpan}
      galat={galat} labelSimpan="Ajukan">
      <Isian label="Jenis" wajib>
        <SmartNativeSelect value={f.jenis} onChange={(e) => ubah('jenis', e.target.value)} searchable={false} className="w-full" data-testid="shift-saya-jenis">
          <option value="ganti">Ganti ke shift lain</option>
          <option value="tukar">Tukar dengan rekan</option>
        </SmartNativeSelect>
      </Isian>
      <Isian label="Tanggal" wajib>
        <DatePicker value={f.tanggal} min={todayWIB()} onChange={(v) => v && ubah('tanggal', v)} bolehKosong={false} testId="shift-saya-tanggal" />
      </Isian>
      {f.jenis === 'ganti' ? (
        <Isian label="Shift tujuan" wajib>
          <SmartNativeSelect value={f.shift_id} onChange={(e) => ubah('shift_id', e.target.value)} className="w-full" data-testid="shift-saya-shift">
            <option value="">— Pilih shift —</option>
            {shifts.map((s) => <option key={s.id} value={s.id}>{`${s.shift_code} — ${s.shift_name} (${s.start_time}–${s.end_time})`}</option>)}
          </SmartNativeSelect>
        </Isian>
      ) : (
        <Isian label="Rekan" wajib petunjuk={rekan.length ? 'Rekan satu departemen yang tidak cuti pada tanggal itu.' : 'Tidak ada rekan satu departemen yang bisa diajak.'}>
          <SmartNativeSelect value={f.rekan_employee_id} onChange={(e) => ubah('rekan_employee_id', e.target.value)} className="w-full" data-testid="shift-saya-rekan">
            <option value="">— Pilih rekan —</option>
            {rekan.map((r) => <option key={r.employee_id} value={r.employee_id}>{`${r.nama} — ${r.shift ? `${r.shift.kode} ${jamShift(r.shift)}` : 'libur'}`}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}
      <Isian label="Alasan" wajib htmlFor="shift-saya-alasan">
        <Textarea id="shift-saya-alasan" rows={2} value={f.alasan} onChange={(e) => ubah('alasan', e.target.value)} placeholder="Mis. ada jadwal kuliah pagi" />
      </Isian>
    </FormPopup>
  );
}

export default function PortalShiftSayaModule() {
  const [jadwal, setJadwal] = useState(null);
  const [minta, setMinta] = useState({ milik_saya: [], sebagai_rekan: [], perlu_persetujuan_saya: [] });
  const [memuat, setMemuat] = useState(false);
  const [galatMuat, setGalatMuat] = useState('');
  const [form, setForm] = useState(null);   // null | {tanggal}

  const muat = useCallback(async () => {
    setMemuat(true); setGalatMuat('');
    try {
      const [j, m] = await Promise.all([shiftApi('get', `${P}/jadwal-saya`, { params: { hari: 14 } }), shiftApi('get', `${P}/permintaan`)]);
      setJadwal(j); setMinta(m || {});
    } catch (e) { setGalatMuat(pesanGalat(e, 'Jadwal gagal dimuat.')); } finally { setMemuat(false); }
  }, []);
  useEffect(() => { muat(); }, [muat]);

  const jawab = async (r, peran, ya) => {
    const teks = ya
      ? await confirmDialog({ title: peran === 'rekan' ? 'Setuju bertukar shift?' : 'Setujui permintaan ini?', body: `${r.label_jenis} ${r.employee_name} — ${formatTanggalID(r.tanggal)}.`, confirmLabel: 'Setuju' })
      : await confirmDialog({ title: 'Tolak permintaan ini?', confirmLabel: 'Tolak', danger: true, input: { label: 'Alasan', minLength: 3 } });
    if (!teks) return;
    try {
      const d = await shiftApi('post', `${P}/permintaan/${r.id}/${peran}`, { data: { [peran === 'rekan' ? 'setuju' : 'setujui']: ya, catatan: typeof teks === 'string' ? teks : '' } });
      toast.success(d?.message || 'Jawaban terkirim.');
      muat();
    } catch (e) { toast.error(pesanGalat(e)); }
  };

  const batalkan = async (r) => {
    if (!(await confirmDialog({ title: 'Batalkan permintaan ini?', confirmLabel: 'Batalkan', danger: true }))) return;
    try { await shiftApi('post', `${P}/permintaan/${r.id}/batalkan`); toast.success('Permintaan dibatalkan.'); muat(); } catch (e) { toast.error(pesanGalat(e)); }
  };

  const kolomJadwal = [
    { kunci: 'tgl', label: 'Tanggal', hp: 'judul', isi: (h) => <span className={h.hari_ini ? 'font-semibold text-foreground' : ''}>{h.label}{h.hari_ini ? ' (hari ini)' : ''}</span> },
    { kunci: 'shift', label: 'Shift', isi: (h) => (h.shift ? <TitikShift kode={h.shift.kode} warna={h.shift.warna} jam={jamShift(h.shift)} /> : <span className="text-muted-foreground">Libur</span>) },
    { kunci: 'ket', label: 'Keterangan', hp: 'keterangan', isi: (h) => h.keterangan || (h.shift ? labelSumber(h.sumber) : '—') },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (h) => (
      <Button size="sm" variant="outline" onClick={() => setForm({ tanggal: h.date })} data-testid="shift-saya-ajukan-baris">Ajukan perubahan</Button>) },
  ];
  const kolomMinta = (aksi) => [
    { kunci: 'tgl', label: 'Tanggal shift', hp: 'judul', isi: (r) => formatTanggalID(r.tanggal) },
    { kunci: 'jenis', label: 'Jenis', isi: (r) => r.label_jenis },
    { kunci: 'ubah', label: 'Perubahan', hp: 'keterangan', isi: (r) => <PerubahanShift r={r} /> },
    { kunci: 'alasan', label: 'Alasan', isi: (r) => r.alasan },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={r.label_status} tone={NADA_STATUS[r.status]} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksi },
  ];
  const tombolJawab = (peran, tahap) => (r) => (r.status === tahap ? (
    <div className="flex justify-end gap-1">
      <Button size="sm" variant="success" onClick={() => jawab(r, peran, true)}><Check />Setuju</Button>
      <Button size="sm" variant="destructive" onClick={() => jawab(r, peran, false)}><X />Tolak</Button>
    </div>) : null);

  const ajakan = (minta.sebagai_rekan || []).filter((r) => r.status === 'menunggu_rekan');
  const atasan = minta.perlu_persetujuan_saya || [];
  return (
    <PageLayout testId="portal-shift-saya" title="Jadwal shift" subtitle="Shift Anda 2 minggu ke depan. Ajukan ganti atau tukar shift bila perlu."
      actions={<Button onClick={() => setForm({})} data-testid="shift-saya-ajukan"><Plus />Ajukan perubahan</Button>}
      tools={<Button variant="outline" size="icon" onClick={muat} disabled={memuat} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className={memuat ? 'animate-spin' : ''} /></Button>}
      summary={jadwal && (
        <p className="text-sm text-muted-foreground" data-testid="shift-saya-ringkas">
          <span className="font-medium text-foreground">{jadwal.hari.filter((h) => h.shift).length}</span> hari kerja dalam 14 hari ke depan
          {ajakan.length > 0 && <> · <span className="font-medium text-foreground">{ajakan.length}</span> ajakan tukar dari rekan</>}
          {atasan.length > 0 && <> · <span className="font-medium text-foreground">{atasan.length}</span> menunggu persetujuan Anda</>}.
        </p>
      )}>
      {galatMuat
        ? <EmptyState title="Jadwal belum bisa ditampilkan" description={galatMuat} />
        : <TabelData kolom={kolomJadwal} baris={jadwal?.hari || []} kunci={(h) => h.date} testId="shift-saya-jadwal"
            kosong={<EmptyState title="Jadwal belum ada" description="Hubungi SDM bila shift Anda belum diatur." />} />}
      {atasan.length > 0 && (<>
        <p className="text-base font-semibold text-foreground">Perlu persetujuan Anda sebagai atasan</p>
        <TabelData kolom={kolomMinta(tombolJawab('atasan', 'menunggu_atasan'))} baris={atasan} testId="shift-saya-atasan" />
      </>)}
      {ajakan.length > 0 && (<>
        <p className="text-base font-semibold text-foreground">Ajakan tukar shift dari rekan</p>
        <TabelData kolom={kolomMinta(tombolJawab('rekan', 'menunggu_rekan'))} baris={ajakan} testId="shift-saya-rekan-tabel" />
      </>)}
      <p className="text-base font-semibold text-foreground">Permintaan saya</p>
      <TabelData kolom={kolomMinta((r) => (['menunggu_rekan', 'menunggu_atasan', 'menunggu_hr'].includes(r.status)
        ? <Button size="sm" variant="outline" onClick={() => batalkan(r)}>Batalkan</Button> : null))}
        baris={minta.milik_saya || []} testId="shift-saya-permintaan"
        kosong={<EmptyState title="Belum ada permintaan" description="Tekan Ajukan perubahan untuk ganti atau tukar shift." />} />
      <FormAjukan open={form !== null} tanggalAwal={form?.tanggal} onClose={() => setForm(null)} onSelesai={() => { setForm(null); muat(); }} />
    </PageLayout>
  );
}
