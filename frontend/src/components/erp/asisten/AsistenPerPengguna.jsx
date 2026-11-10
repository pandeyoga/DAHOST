/**
 * Asisten AI per pengguna (Monitor AI › Pengaturan) — keputusan owner 10 Nov 2026.
 *
 * Siapa yang boleh memakai Asisten AI (chat Portal Manajemen, AI SDM, Tanya Asisten) + batas pertanyaan & tindakan per
 * hari per akun, dengan pemakaian hari ini. Data: GET /api/ai/usage/asisten-pengguna (owner/superadmin/admin),
 * ubah: PUT /api/ai/usage/asisten-pengguna/{id} (HANYA owner/superadmin; server juga memeriksa).
 * Akun yang belum diatur ikut bawaan (Monitor AI › Ubah pengaturan). Owner & superadmin selalu aktif.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Pencil, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { formatDateTimeID } from '@/lib/format';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { labelKodePeran } from '../akses/labelPeran';

const BATAS_MAKS = 1000;
const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const fmtUSD = (v) => `$${Number(v || 0).toFixed(4)}`;

/** "3 / 20" atau "3 · tanpa batas" (batas 0 = tanpa batas). */
export function teksPakai(pakai, batas) {
  return Number(batas) > 0 ? `${fmtNum(pakai)} / ${fmtNum(batas)}` : `${fmtNum(pakai)} · tanpa batas`;
}

/** Keterangan asal status: diatur di akun, ikut bawaan, atau selalu aktif (owner/superadmin). */
export function asalStatus(row) {
  if (row?.selalu_aktif) return 'Selalu aktif (owner/superadmin)';
  return row?.sumber === 'akun' ? 'Diatur untuk akun ini' : 'Ikut bawaan';
}

/** Isian batas → angka 0..1000, null (kosong = ikut bawaan), atau undefined (tidak sah). */
export function bacaBatas(v) {
  const s = String(v ?? '').trim();
  if (!s) return null;
  if (!/^\d+$/.test(s)) return undefined;
  const n = Number(s);
  return n <= BATAS_MAKS ? n : undefined;
}

const KOSONG_FORM = { aktif: '', batas_pertanyaan_harian: '', batas_tindakan_harian: '' };

export default function AsistenPerPengguna({ token, onBawaan }) {
  const BASE = process.env.REACT_APP_BACKEND_URL;
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [data, setData] = useState(null);
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  const [cari, setCari] = useState('');
  const [saring, setSaring] = useState('');
  const [ubah, setUbah] = useState(null);
  const [form, setForm] = useState(KOSONG_FORM);
  const [menyimpan, setMenyimpan] = useState(false);

  const muat = useCallback(async () => {
    setMemuat(true);
    try {
      const r = await fetch(`${BASE}/api/ai/usage/asisten-pengguna`, { headers });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setGalat(typeof d?.detail === 'string' ? d.detail : 'Daftar Asisten AI per pengguna gagal dimuat.');
        setData(null);
      } else {
        setGalat('');
        setData(d?.data || null);
        if (onBawaan && d?.data?.bawaan) onBawaan(d.data.bawaan);
      }
    } catch (e) {
      setGalat('Server tidak menjawab. Coba muat ulang.');
    } finally {
      setMemuat(false);
    }
  }, [BASE, headers, onBawaan]);

  useEffect(() => { muat(); }, [muat]);

  const items = useMemo(() => data?.items || [], [data]);
  const bawaan = data?.bawaan || { aktif: false, batas_pertanyaan: 0, batas_tindakan: 30 };
  const bolehUbah = !!data?.boleh_ubah;
  const q = cari.trim().toLowerCase();
  const tampil = useMemo(() => items
    .filter((x) => !saring || (saring === 'aktif' ? x.aktif : !x.aktif))
    .filter((x) => !q || `${x.name} ${x.email} ${labelKodePeran(x.role)}`.toLowerCase().includes(q)),
  [items, saring, q]);
  const nAktif = items.filter((x) => x.aktif).length;

  const buka = (row) => {
    const a = row.atur || {};
    setForm({
      aktif: a.aktif === true ? 'aktif' : a.aktif === false ? 'mati' : '',
      batas_pertanyaan_harian: a.batas_pertanyaan_harian ?? '',
      batas_tindakan_harian: a.batas_tindakan_harian ?? '',
    });
    setUbah(row);
  };

  const simpan = async () => {
    if (!ubah) return;
    const bp = bacaBatas(form.batas_pertanyaan_harian);
    const bt = bacaBatas(form.batas_tindakan_harian);
    if (bp === undefined || bt === undefined) {
      toast.error(`Batas harus angka bulat 0–${BATAS_MAKS}, atau kosongkan untuk ikut bawaan.`);
      return;
    }
    const body = { batas_pertanyaan_harian: bp, batas_tindakan_harian: bt };
    if (!ubah.selalu_aktif) body.aktif = form.aktif === 'aktif' ? true : form.aktif === 'mati' ? false : null;
    setMenyimpan(true);
    try {
      const r = await fetch(`${BASE}/api/ai/usage/asisten-pengguna/${encodeURIComponent(ubah.id)}`, {
        method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        toast.error(typeof d?.detail === 'string' ? d.detail : 'Pengaturan Asisten AI gagal disimpan.');
        return;
      }
      toast.success(`Asisten AI untuk ${ubah.name} disimpan.`);
      setUbah(null);
      muat();
    } catch (e) {
      toast.error('Pengaturan Asisten AI gagal disimpan.');
    } finally {
      setMenyimpan(false);
    }
  };

  const teksBawaanPertanyaan = Number(bawaan.batas_pertanyaan) > 0 ? `${fmtNum(bawaan.batas_pertanyaan)} per hari` : 'tanpa batas';

  return (
    // Tanpa kartu pembungkus (pola layar Pengguna): TabelData sudah menjadi kartu per baris di HP.
    <section className="space-y-3" data-testid="ai-asisten-pengguna">
      <div className="min-w-0">
        <p className="text-base font-semibold text-foreground">Asisten AI per pengguna</p>
        <p className="text-sm text-muted-foreground">
          Siapa yang boleh memakai Asisten AI (chat Manajemen, AI SDM, Tanya Asisten) dan batas hariannya.
          Akun yang belum diatur: <span className="font-medium text-foreground">{bawaan.aktif ? 'aktif' : 'mati'}</span>,
          {' '}pertanyaan {teksBawaanPertanyaan}, tindakan {fmtNum(bawaan.batas_tindakan)} per hari. Owner dan superadmin selalu aktif.
        </p>
      </div>

      {galat ? (
        <Notice tone="warning">{galat}</Notice>
      ) : (
        <>
          {/* penyaring di kiri, alat (unduh, muat ulang) di kanan */}
          <div className="flex flex-wrap items-center gap-2">
            <FilterChips value={saring} onChange={setSaring} hideWhenEmpty={false} testId="ai-asisten-pengguna-saring"
              className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" options={[
                { key: '', label: 'Semua', count: items.length },
                { key: 'aktif', label: 'Aktif', count: nAktif },
                { key: 'mati', label: 'Mati', count: items.length - nAktif },
              ]} />
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari nama, email, peran" className="pl-8"
                aria-label="Cari pengguna" data-testid="ai-asisten-pengguna-cari" />
            </div>
            <div className="ml-auto flex items-center gap-2">
              <TombolUnduh namaBerkas="asisten-ai-per-pengguna" namaLembar="Asisten AI per pengguna" baris={tampil}
                testId="ai-asisten-pengguna-unduh"
                kolom={[
                  { label: 'Nama', nilai: (x) => x.name },
                  { label: 'Email', nilai: (x) => x.email },
                  { label: 'Peran', nilai: (x) => labelKodePeran(x.role) },
                  { label: 'Asisten AI', nilai: (x) => (x.aktif ? 'Aktif' : 'Mati') },
                  { label: 'Asal status', nilai: (x) => asalStatus(x) },
                  { label: 'Pertanyaan hari ini', nilai: (x) => x.pertanyaan_hari_ini },
                  { label: 'Batas pertanyaan per hari (0 = tanpa batas)', nilai: (x) => x.batas_pertanyaan },
                  { label: 'Tindakan hari ini', nilai: (x) => x.tindakan_hari_ini },
                  { label: 'Batas tindakan per hari', nilai: (x) => x.batas_tindakan },
                  { label: 'Biaya hari ini (USD)', nilai: (x) => x.biaya_hari_ini_usd },
                ]} />
              <Button variant="outline" size="icon" onClick={muat} disabled={memuat} title="Muat ulang daftar" aria-label="Muat ulang daftar"
                data-testid="ai-asisten-pengguna-muat">
                <RefreshCw className={memuat ? 'animate-spin' : ''} />
              </Button>
            </div>
          </div>
          <TabelData baris={tampil} testId="ai-asisten-pengguna-tabel" onKlikBaris={bolehUbah ? buka : undefined}
            kosong={<EmptyState title={memuat ? 'Memuat pengguna…' : (items.length ? 'Tidak ada pengguna yang cocok' : 'Belum ada pengguna')}
              description={memuat ? undefined : (items.length ? 'Ubah saringan atau kata pencarian.' : 'Akun internal yang aktif akan tampil di sini.')} />}
            kolom={[
              { kunci: 'name', label: 'Pengguna', hp: 'judul', isi: (x) => (
                <div className="min-w-0">
                  <p className="font-medium text-foreground">{x.name}</p>
                  <p className="break-all text-xs text-muted-foreground">{x.email}</p>
                </div>) },
              { kunci: 'role', label: 'Peran', isi: (x) => <span className="text-sm">{labelKodePeran(x.role)}</span> },
              { kunci: 'aktif', label: 'Asisten AI', isi: (x) => (
                <div className="flex flex-col items-start gap-0.5">
                  <StatusBadge status={x.aktif ? 'aktif' : 'mati'} label={x.aktif ? 'Aktif' : 'Mati'} tone={x.aktif ? 'success' : 'muted'} />
                  <span className="text-xs text-muted-foreground">{asalStatus(x)}</span>
                </div>) },
              { kunci: 'pertanyaan', label: 'Pertanyaan hari ini', rata: 'kanan',
                isi: (x) => <span className="tabular-nums">{teksPakai(x.pertanyaan_hari_ini, x.batas_pertanyaan)}</span> },
              { kunci: 'tindakan', label: 'Tindakan hari ini', rata: 'kanan',
                isi: (x) => <span className="tabular-nums">{teksPakai(x.tindakan_hari_ini, x.batas_tindakan)}</span> },
              { kunci: 'biaya', label: 'Biaya hari ini', rata: 'kanan',
                isi: (x) => <span className="tabular-nums">{fmtUSD(x.biaya_hari_ini_usd)}</span> },
              // HP: ketuk kartu untuk mengubah (tanpa tombol sendirian di kaki kartu)
              ...(bolehUbah ? [{ kunci: 'aksi', label: '', rata: 'kanan', hp: false, isi: (x) => (
                <Button size="sm" variant="outline" onClick={() => buka(x)} data-testid={`ai-asisten-pengguna-ubah-${x.id}`}>
                  <Pencil />Ubah
                </Button>) }] : []),
            ]} />
          {!bolehUbah && items.length > 0 && (
            <p className="text-xs text-muted-foreground">Hanya owner dan superadmin yang bisa mengubah Asisten AI per pengguna.</p>
          )}
        </>
      )}

      <FormPopup open={!!ubah} onClose={() => setUbah(null)} ukuran="pendek" testId="ai-asisten-pengguna-form"
        judul="Asisten AI untuk pengguna" keterangan={ubah ? `${ubah.name} · ${labelKodePeran(ubah.role)}` : undefined}
        onSimpan={simpan} menyimpan={menyimpan} labelSimpan="Simpan">
        <Isian label="Asisten AI" htmlFor="ai-ap-aktif"
          petunjuk={ubah?.selalu_aktif ? 'Owner dan superadmin selalu aktif.' : `Ikut bawaan = ${bawaan.aktif ? 'aktif' : 'mati'} (diatur di Ubah pengaturan).`}>
          <SmartNativeSelect id="ai-ap-aktif" value={ubah?.selalu_aktif ? 'aktif' : form.aktif} disabled={!!ubah?.selalu_aktif}
            searchable={false} onChange={(e) => setForm((f) => ({ ...f, aktif: e.target.value }))} data-testid="ai-ap-aktif">
            <option value="">{`Ikut bawaan (${bawaan.aktif ? 'aktif' : 'mati'})`}</option>
            <option value="aktif">Aktif</option>
            <option value="mati">Mati</option>
          </SmartNativeSelect>
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Batas pertanyaan per hari" htmlFor="ai-ap-pertanyaan"
            petunjuk={`Kosong = ikut bawaan (${teksBawaanPertanyaan}). 0 = tanpa batas.`}>
            <Input id="ai-ap-pertanyaan" inputMode="numeric" value={form.batas_pertanyaan_harian}
              onChange={(e) => setForm((f) => ({ ...f, batas_pertanyaan_harian: e.target.value }))} data-testid="ai-ap-pertanyaan" />
          </Isian>
          <Isian label="Batas tindakan per hari" htmlFor="ai-ap-tindakan"
            petunjuk={`Kosong = ikut bawaan (${fmtNum(bawaan.batas_tindakan)} per hari).`}>
            <Input id="ai-ap-tindakan" inputMode="numeric" value={form.batas_tindakan_harian}
              onChange={(e) => setForm((f) => ({ ...f, batas_tindakan_harian: e.target.value }))} data-testid="ai-ap-tindakan" />
          </Isian>
        </div>
        <Notice tone="info">
          Ruang yang bisa dibuka tetap mengikuti portal dan izin peran akun ini (termasuk centang “Asisten AI” di
          Peran &amp; Hak Akses). Aktif di sini tidak membuka portal baru.
          {ubah?.diubah_at ? ` Terakhir diubah ${formatDateTimeID(new Date(ubah.diubah_at))}${ubah.diubah_oleh ? ` oleh ${ubah.diubah_oleh}` : ''}.` : ''}
        </Notice>
      </FormPopup>
    </section>
  );
}
