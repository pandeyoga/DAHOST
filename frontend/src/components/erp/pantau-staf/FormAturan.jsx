/**
 * Form popup ubah aturan kewajiban (owner/admin): pemegang (akun tertentu / peran / dari dokumen), cadangan saat
 * cuti/izin, batas waktu, saringan, bobot, aktif. Validasi akhir di backend (`core/pantau_staf/aturan.py`).
 */
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Checkbox } from '@/components/ui/checkbox';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Switch } from '@/components/ui/switch';
import { apiPut } from '../../../lib/api';
import { namaPeran } from './pantauStafShared';

const JAM = ['07:00', '08:00', '09:00', '10:00', '12:00', '14:00', '15:00', '16:00', '17:00', '20:00', '23:55', '23:59'];

/** Daftar centang dengan kotak cari — untuk memilih beberapa akun / peran / lokasi / toko. */
export function PilihBanyak({ opsi, nilai, onChange, testId, placeholder = 'Cari…' }) {
  const [cari, setCari] = useState('');
  const kata = cari.trim().toLowerCase();
  const daftar = opsi.filter((o) => !kata || `${o.nama} ${o.sub || ''}`.toLowerCase().includes(kata));
  const alih = (id) => onChange(nilai.includes(id) ? nilai.filter((x) => x !== id) : [...nilai, id]);
  return (
    <div className="space-y-2" data-testid={testId}>
      {opsi.length > 6 && <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder={placeholder} />}
      <div className="max-h-48 space-y-1 overflow-y-auto rounded-[var(--radius-md)] border p-2">
        {daftar.length === 0 && <p className="px-1 text-sm text-muted-foreground">Tidak ada pilihan.</p>}
        {daftar.map((o) => (
          <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-[var(--glass-bg)]">
            <Checkbox checked={nilai.includes(o.id)} onCheckedChange={() => alih(o.id)} />
            <span className="min-w-0 truncate">{o.nama}</span>
            {o.sub && <span className="truncate text-xs text-muted-foreground">{o.sub}</span>}
          </label>
        ))}
      </div>
      {nilai.length > 0 && <p className="text-xs text-muted-foreground">{nilai.length} dipilih</p>}
    </div>
  );
}

function awalForm(a) {
  const p = a?.pemegang || {};
  const t = a?.tenggat || a?.tenggat_bawaan || {};
  return {
    aktif: !!a?.aktif, jenis: p.jenis || 'akun', akun_ids: p.akun_ids || [], peran: p.peran || [],
    cadangan_ids: a?.cadangan_ids || [], bobot: String(a?.bobot || 1),
    tg_jenis: t.jenis || 'hari_kerja', tg_nilai: String(t.nilai ?? 1), tg_hari: String(t.hari ?? 1), tg_jam: t.jam || '10:00',
    business_type: a?.saringan?.business_type || '', location_id: a?.saringan?.location_id || [],
    account_id: a?.saringan?.account_id || [],
  };
}

export default function FormAturan({ aturan, pilihan, onClose, onTersimpan }) {
  const [f, setF] = useState(() => awalForm(aturan));
  const [galat, setGalat] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);
  useEffect(() => { setF(awalForm(aturan)); setGalat(''); }, [aturan]);
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }));
  const dariData = aturan?.pemegang_bawaan?.jenis === 'data';
  const berkala = aturan?.jenis === 'berkala';
  const bolehDokumen = aturan?.tenggat_bawaan?.jenis === 'dokumen';
  const boleh = new Set(aturan?.saringan_boleh || []);
  const akunOpsi = useMemo(() => (pilihan?.akun || []).map((a) => ({ id: a.id, nama: a.nama, sub: namaPeran(a.peran) })), [pilihan]);
  const peranOpsi = useMemo(() => (pilihan?.peran || []).map((r) => ({ id: r, nama: namaPeran(r) })), [pilihan]);

  const simpan = async () => {
    setGalat('');
    let tenggat;
    if (f.tg_jenis === 'jam_tetap') tenggat = { jenis: 'jam_tetap', hari: Number(f.tg_hari), jam: f.tg_jam };
    else if (f.tg_jenis === 'dokumen') tenggat = { jenis: 'dokumen' };
    else tenggat = { jenis: f.tg_jenis, nilai: Number(f.tg_nilai) };
    const saringan = { ...(aturan?.saringan || {}) };
    if (boleh.has('business_type')) saringan.business_type = f.business_type || null;
    if (boleh.has('location_id')) saringan.location_id = f.location_id;
    if (boleh.has('account_id')) saringan.account_id = f.account_id;
    const body = {
      aktif: f.aktif, pemegang: { jenis: f.jenis, akun_ids: f.akun_ids, peran: f.peran },
      cadangan_ids: f.cadangan_ids, tenggat, bobot: Number(f.bobot), saringan,
    };
    setMenyimpan(true);
    try {
      await apiPut(`/pantau-staf/aturan/${aturan.id}`, body);
      toast.success('Aturan disimpan. Berlaku pada pemeriksaan berikutnya.');
      onTersimpan?.();
      onClose();
    } catch (e) {
      setGalat(e.message);
    } finally {
      setMenyimpan(false);
    }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={simpan} menyimpan={menyimpan} galat={galat}
      judul={`Aturan: ${aturan?.nama || ''}`} keterangan={`Mulai: ${aturan?.pemicu}. Selesai bila ${aturan?.bukti}.`}
      labelSimpan="Simpan aturan" testId="form-aturan">
      <label className="flex items-center gap-3 text-sm" htmlFor="aturan-aktif">
        <Switch id="aturan-aktif" checked={f.aktif} onCheckedChange={set('aktif')} data-testid="aturan-aktif" />
        <span>Aktif — kewajiban dibuat dan dipantau untuk langkah ini</span>
      </label>
      <Isian label="Penanggung jawab" wajib htmlFor="aturan-jenis">
        <SmartNativeSelect id="aturan-jenis" value={f.jenis} onChange={(e) => set('jenis')(e.target.value)} data-testid="aturan-jenis">
          <option value="akun">Akun tertentu</option>
          <option value="peran">Semua akun dengan peran tertentu</option>
          {dariData && <option value="data">Dari dokumen: {aturan?.pemegang_bawaan?.label}</option>}
        </SmartNativeSelect>
      </Isian>
      {f.jenis === 'akun' && (
        <Isian label="Akun penanggung jawab" wajib>
          <PilihBanyak opsi={akunOpsi} nilai={f.akun_ids} onChange={set('akun_ids')} testId="aturan-akun" placeholder="Cari nama atau peran" />
        </Isian>
      )}
      {f.jenis === 'peran' && (
        <Isian label="Peran penanggung jawab" wajib>
          <PilihBanyak opsi={peranOpsi} nilai={f.peran} onChange={set('peran')} testId="aturan-peran" placeholder="Cari peran" />
        </Isian>
      )}
      <Isian label="Cadangan saat penanggung jawab cuti atau izin" petunjuk="Kosong = kewajiban dimaafkan otomatis bila penanggung jawab cuti/izin.">
        <PilihBanyak opsi={akunOpsi} nilai={f.cadangan_ids} onChange={set('cadangan_ids')} testId="aturan-cadangan" placeholder="Cari nama" />
      </Isian>
      <Isian label="Batas waktu" wajib>
        {berkala ? (
          <div className="flex flex-wrap gap-2">
            <SmartNativeSelect value={f.tg_jenis === 'jam_tetap' ? f.tg_hari : '1'} wrapperClassName="w-56"
              onChange={(e) => setF((s) => ({ ...s, tg_jenis: 'jam_tetap', tg_hari: e.target.value }))} data-testid="aturan-tg-hari">
              <option value="0">Hari itu juga</option>
              <option value="1">Hari kerja berikutnya</option>
              {[2, 3, 5, 7].map((n) => <option key={n} value={String(n)}>{n} hari kerja kemudian</option>)}
            </SmartNativeSelect>
            <SmartNativeSelect value={f.tg_jam} wrapperClassName="w-32"
              onChange={(e) => setF((s) => ({ ...s, tg_jenis: 'jam_tetap', tg_jam: e.target.value }))} data-testid="aturan-tg-jam">
              {JAM.map((j) => <option key={j} value={j}>pukul {j.replace(':', '.')}</option>)}
            </SmartNativeSelect>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {f.tg_jenis !== 'dokumen' && (
              <Input type="number" min={1} max={f.tg_jenis === 'jam' ? 240 : 30} value={f.tg_nilai} className="w-24"
                onChange={(e) => set('tg_nilai')(e.target.value)} data-testid="aturan-tg-nilai" />
            )}
            <SmartNativeSelect value={f.tg_jenis} wrapperClassName="w-60" onChange={(e) => set('tg_jenis')(e.target.value)} data-testid="aturan-tg-jenis">
              <option value="hari_kerja">hari kerja sejak langkah terpicu</option>
              <option value="jam">jam sejak langkah terpicu</option>
              {bolehDokumen && <option value="dokumen">tanggal jatuh tempo di dokumen</option>}
            </SmartNativeSelect>
          </div>
        )}
      </Isian>
      {boleh.has('business_type') && (
        <Isian label="Berlaku untuk PO">
          <SmartNativeSelect value={f.business_type} onChange={(e) => set('business_type')(e.target.value)} data-testid="aturan-jenis-po">
            <option value="">PO internal dan maklon</option>
            <option value="internal">PO internal saja</option>
            <option value="maklon">PO maklon saja</option>
          </SmartNativeSelect>
        </Isian>
      )}
      {boleh.has('location_id') && (
        <Isian label="Hanya lokasi tertentu" petunjuk="Kosong = semua lokasi.">
          <PilihBanyak opsi={(pilihan?.lokasi || []).map((l) => ({ id: l.id, nama: l.nama }))} nilai={f.location_id}
            onChange={set('location_id')} testId="aturan-lokasi" placeholder="Cari lokasi" />
        </Isian>
      )}
      {boleh.has('account_id') && (
        <Isian label="Hanya toko tertentu" petunjuk="Kosong = semua toko aktif.">
          <PilihBanyak opsi={(pilihan?.toko || []).map((t) => ({ id: t.id, nama: t.nama }))} nilai={f.account_id}
            onChange={set('account_id')} testId="aturan-toko" placeholder="Cari toko" />
        </Isian>
      )}
      <Isian label="Bobot di skor" petunjuk="Langkah yang memblokir banyak orang bisa diberi bobot lebih besar.">
        <SmartNativeSelect value={f.bobot} wrapperClassName="w-32" onChange={(e) => set('bobot')(e.target.value)} data-testid="aturan-bobot">
          {[1, 2, 3, 4, 5].map((n) => <option key={n} value={String(n)}>{n}</option>)}
        </SmartNativeSelect>
      </Isian>
    </FormPopup>
  );
}
