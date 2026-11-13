/**
 * Aturan Kewajiban — Portal Manajemen (keputusan owner 10 Nov 2026).
 *
 * Per langkah: siapa pemegang tiap langkah alur / kewajiban harian, batas waktu, cadangan, saringan, bobot, aktif.
 * Per akun: "to-do list" satu akun = semua aturan yang menunjuk akun itu (langsung, lewat peran, atau dari data);
 * akun bisa ditambahkan ke langkah, dilepas, atau dikecualikan.
 * K2: langkah yang pemegangnya akun/peran belum diisi & belum aktif — owner mengisinya di sini.
 */
import { useMemo, useState } from 'react';
import { Pencil, Plus, UserMinus, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { apiPut } from '../../../lib/api';
import HubTabs from '../hubs/HubTabs';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { RefreshButton, SearchBox, primeHubTab } from '../pantau/pantauShared';
import FormAturan from './FormAturan';
import { namaPeran, useApi, waktu } from './pantauStafShared';
import { TombolPeriksa } from './PerStafTab';

function pemegangTeks(a) {
  const p = a.pemegang || {};
  if (p.jenis === 'akun') return a.pemegang_nama?.length ? a.pemegang_nama.join(', ') : null;
  if (p.jenis === 'peran') return p.peran?.length ? `Peran: ${p.peran.map(namaPeran).join(', ')}` : null;
  return `Dari dokumen: ${a.pemegang_bawaan?.label || 'penanggung jawab di dokumen'}`;
}

function StatusAturan({ a }) {
  if (a.aktif) return <StatusBadge status="aktif" label="Aktif" tone="success" />;
  if (!pemegangTeks(a)) return <StatusBadge status="kosong" label="Belum diisi" tone="warning" />;
  return <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />;
}

function PerLangkahTab() {
  const { data, loading, error, reload } = useApi('/pantau-staf/aturan');
  const [alur, setAlur] = useState('');
  const [cari, setCari] = useState('');
  const [detail, setDetail] = useState(null);
  const [ubah, setUbah] = useState(null);
  const items = useMemo(() => data?.items || [], [data]);
  const opsi = [{ key: '', label: 'Semua', count: items.length },
    ...Object.entries(data?.alur || {}).map(([key, label]) => ({ key, label, count: items.filter((a) => a.alur === key).length }))];
  const kata = cari.trim().toLowerCase();
  const baris = items.filter((a) => !alur || a.alur === alur)
    .filter((a) => !kata || `${a.nama} ${pemegangTeks(a) || ''}`.toLowerCase().includes(kata));
  const belumDiisi = items.filter((a) => !a.aktif && !pemegangTeks(a)).length;

  const kolom = [
    { kunci: 'nama', label: 'Langkah', hp: 'judul', isi: (a) => (
      <div className="min-w-0 md:max-w-[20rem]"><p className="font-medium">{a.nama}</p>
        <p className="truncate text-xs text-muted-foreground" title={a.pemicu}>{a.alur_label} · mulai: {a.pemicu}</p></div>) },
    { kunci: 'pemegang', label: 'Penanggung jawab', isi: (a) => <span className="text-sm">{pemegangTeks(a) || '—'}</span> },
    { kunci: 'batas', label: 'Batas waktu', isi: (a) => <span className="text-sm">{a.tenggat_label}</span> },
    { kunci: 'status', label: 'Status', isi: (a) => <StatusAturan a={a} /> },
    { kunci: 'terbuka', label: 'Terbuka', rata: 'kanan', isi: (a) => (
      <span className="tabular-nums" title="menunggu · terlambat">{a.menunggu} · <span className={a.terlambat ? 'font-semibold text-[hsl(var(--danger-text))]' : ''}>{a.terlambat}</span></span>) },
    // HP: kartu diketuk → rincian (berisi tombol Ubah); tidak ada tombol tunggal di kaki kartu
    { kunci: 'aksi', label: '', rata: 'kanan', hp: false, isi: (a) => (
      <Button size="sm" variant="outline" onClick={() => setUbah(a)} data-testid={`ubah-aturan-${a.id}`}><Pencil />Ubah</Button>) },
  ];

  return (
    <PageLayout testId="aturan-per-langkah" title="Per langkah"
      subtitle="Penanggung jawab, batas waktu, dan cadangan untuk setiap langkah alur dan kewajiban harian."
      actions={<TombolPeriksa onSelesai={reload} />}
      filters={<>
        <SmartNativeSelect value={alur} onChange={(e) => setAlur(e.target.value)} wrapperClassName="w-60" data-testid="aturan-alur">
          {opsi.map((o) => <option key={o.key} value={o.key}>{o.key ? o.label : 'Semua alur'} ({o.count})</option>)}
        </SmartNativeSelect>
        <SearchBox value={cari} onChange={setCari} placeholder="Cari langkah atau penanggung jawab" testId="aturan-cari" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="aturan-kewajiban" namaLembar="Aturan" baris={baris} testId="aturan-unduh" kolom={[
          { label: 'Alur', nilai: (a) => a.alur_label }, { label: 'Langkah', nilai: (a) => a.nama },
          { label: 'Mulai', nilai: (a) => a.pemicu }, { label: 'Bukti selesai', nilai: (a) => a.bukti },
          { label: 'Penanggung jawab', nilai: (a) => pemegangTeks(a) || '' },
          { label: 'Cadangan', nilai: (a) => (a.cadangan_nama || []).join(', ') },
          { label: 'Batas waktu', nilai: (a) => a.tenggat_label }, { label: 'Bobot', nilai: (a) => a.bobot },
          { label: 'Aktif', nilai: (a) => (a.aktif ? 'Ya' : 'Tidak') },
        ]} />
        <RefreshButton onClick={reload} loading={loading} testId="aturan-muat" />
      </>}
      summary={<>
        {error && <Notice tone="danger">{error}</Notice>}
        {belumDiisi > 0 && (
          <Notice tone="warning" title={`${belumDiisi} langkah belum punya penanggung jawab`} testId="aturan-belum-diisi">
            Langkah ini belum dipantau. Klik Ubah, pilih akun atau peran penanggung jawabnya, lalu aktifkan.
          </Notice>
        )}
      </>}>
      {loading && !data ? <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <TabelData kolom={kolom} baris={baris} onKlikBaris={setDetail} testId="aturan-tabel"
          kosong={<EmptyState title="Tidak ada langkah yang cocok" description="Ubah saringan atau kata pencarian." />} />
      )}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.nama} keterangan={detail.alur_label}
          status={<StatusAturan a={detail} />} testId="aturan-rincian"
          aksi={<Button size="sm" variant="outline" onClick={() => { setUbah(detail); setDetail(null); }}><Pencil />Ubah</Button>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Mulai menjadi kewajiban">{detail.pemicu}</BarisDetail>
            <BarisDetail label="Dianggap selesai bila">{detail.bukti}</BarisDetail>
            <BarisDetail label="Penanggung jawab">{pemegangTeks(detail) || 'Belum diisi'}</BarisDetail>
            <BarisDetail label="Cadangan">{detail.cadangan_nama?.length ? detail.cadangan_nama.join(', ') : '—'}</BarisDetail>
            <BarisDetail label="Dikecualikan">{detail.dikecualikan_nama?.length ? detail.dikecualikan_nama.join(', ') : '—'}</BarisDetail>
            <BarisDetail label="Batas waktu">{detail.tenggat_label}</BarisDetail>
            <BarisDetail label="Bobot di skor">{detail.bobot}</BarisDetail>
            <BarisDetail label="Berlaku sejak">{detail.berlaku_sejak ? waktu(detail.berlaku_sejak) : 'Belum pernah aktif'}</BarisDetail>
            {detail.diubah_oleh_nama && <BarisDetail label="Terakhir diubah">{waktu(detail.diubah_at)} · {detail.diubah_oleh_nama}</BarisDetail>}
            {detail.tanpa_waktu && <BarisDetail label="Catatan">Dokumen tidak menyimpan waktu masuk tahap ini; dipakai waktu pertama kali terlihat oleh sistem.</BarisDetail>}
          </dl>
        </DetailPopup>
      )}
      {ubah && <FormAturan aturan={ubah} pilihan={data?.pilihan} onClose={() => setUbah(null)} onTersimpan={reload} />}
    </PageLayout>
  );
}

function FormTambahKeAkun({ akun, aturan, onClose, onTersimpan }) {
  const kandidat = aturan.filter((a) => (a.pemegang?.jenis || 'akun') === 'akun' && !(a.pemegang?.akun_ids || []).includes(akun.id));
  const [pilih, setPilih] = useState(kandidat[0]?.id || '');
  const [galat, setGalat] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);
  const simpan = async () => {
    const a = kandidat.find((x) => x.id === pilih);
    if (!a) { setGalat('Pilih langkahnya.'); return; }
    setMenyimpan(true);
    try {
      await apiPut(`/pantau-staf/aturan/${a.id}`, {
        pemegang: { jenis: 'akun', akun_ids: [...(a.pemegang?.akun_ids || []), akun.id], peran: [] }, aktif: true });
      toast.success(`${akun.nama} kini penanggung jawab "${a.nama}".`);
      onTersimpan?.();
      onClose();
    } catch (e) {
      setGalat(e.message);
    } finally {
      setMenyimpan(false);
    }
  };
  return (
    <FormPopup open onClose={onClose} judul={`Tambah kewajiban untuk ${akun.nama}`} onSimpan={simpan} menyimpan={menyimpan}
      keterangan="Akun ini menjadi penanggung jawab langkah yang dipilih, dan langkahnya diaktifkan." labelSimpan="Tambahkan"
      galat={galat} bisaSimpan={kandidat.length > 0} testId="form-tambah-kewajiban">
      <Isian label="Langkah" wajib htmlFor="tambah-langkah">
        <SmartNativeSelect id="tambah-langkah" value={pilih} onChange={(e) => setPilih(e.target.value)} data-testid="tambah-langkah">
          {kandidat.map((a) => <option key={a.id} value={a.id}>{a.alur_label} · {a.nama}</option>)}
        </SmartNativeSelect>
      </Isian>
    </FormPopup>
  );
}

function PerAkunTab() {
  const semua = useApi('/pantau-staf/aturan');
  const akunList = semua.data?.pilihan?.akun || [];
  const [uid, setUid] = useState('');
  const akun = akunList.find((a) => a.id === uid);
  const { data, loading, error, reload } = useApi(uid ? `/pantau-staf/akun/${uid}/kewajiban` : null);
  const [tambah, setTambah] = useState(false);
  const muat = () => { reload(); semua.reload(); };

  const kecualikan = async (a, ya) => {
    try {
      await apiPut(`/pantau-staf/akun/${uid}/pengecualian`, { aturan_id: a.id, dikecualikan: ya });
      toast.success(ya ? 'Akun dikecualikan dari langkah ini.' : 'Akun diikutkan lagi.');
      muat();
    } catch (e) { toast.error(e.message); }
  };
  const lepas = async (a) => {
    const sisa = (a.pemegang?.akun_ids || []).filter((x) => x !== uid);
    try {
      await apiPut(`/pantau-staf/aturan/${a.id}`, { pemegang: { jenis: 'akun', akun_ids: sisa, peran: [] },
        ...(sisa.length ? {} : { aktif: false }) });
      toast.success(sisa.length ? 'Akun dilepas dari langkah ini.' : 'Akun dilepas; langkah dinonaktifkan karena tidak ada penanggung jawab lain.');
      muat();
    } catch (e) { toast.error(e.message); }
  };

  const kolom = [
    { kunci: 'nama', label: 'Kewajiban', hp: 'judul', isi: (a) => (
      <div className="min-w-0"><p className="font-medium">{a.nama}</p><p className="text-xs text-muted-foreground">{a.alur_label}</p></div>) },
    { kunci: 'alasan', label: 'Kenapa akun ini', isi: (a) => <span className="text-sm">{a.alasan}</span> },
    { kunci: 'batas', label: 'Batas waktu', isi: (a) => <span className="text-sm">{a.tenggat_label}</span> },
    { kunci: 'status', label: 'Status', isi: (a) => (a.dikecualikan
      ? <StatusBadge status="kecuali" label="Dikecualikan" tone="muted" /> : <StatusAturan a={a} />) },
    { kunci: 'terbuka', label: 'Menunggu · terlambat', rata: 'kanan', isi: (a) => <span className="tabular-nums">{a.menunggu} · {a.terlambat}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => {
      if (a.dikecualikan) return <Button size="sm" variant="outline" onClick={() => kecualikan(a, false)}><UserPlus />Ikutkan lagi</Button>;
      if (a.alasan === 'langsung ke akun ini') return <Button size="sm" variant="outline" onClick={() => lepas(a)}><UserMinus />Lepas</Button>;
      if (a.alasan === 'sebagai cadangan') return null;
      return <Button size="sm" variant="outline" onClick={() => kecualikan(a, true)}><UserMinus />Kecualikan</Button>;
    } },
  ];

  return (
    <PageLayout testId="aturan-per-akun" title="Per akun"
      subtitle="Daftar kewajiban satu akun: langkah yang dipegangnya langsung, lewat peran, atau dari data dokumen."
      actions={uid && <Button onClick={() => setTambah(true)} data-testid="tambah-kewajiban"><Plus />Tambah kewajiban</Button>}
      filters={
        <SmartNativeSelect value={uid} onChange={(e) => setUid(e.target.value)} wrapperClassName="w-full sm:w-80"
          placeholder="Pilih akun" data-testid="per-akun-pilih">
          <option value="">Pilih akun…</option>
          {akunList.map((a) => <option key={a.id} value={a.id}>{a.nama} · {namaPeran(a.peran)}</option>)}
        </SmartNativeSelect>}
      tools={uid && <RefreshButton onClick={muat} loading={loading} testId="per-akun-muat" />}
      summary={error && <Notice tone="danger">{error}</Notice>}>
      {!uid ? (
        <TabelData kolom={kolom} baris={[]} testId="per-akun-tabel"
          kosong={<EmptyState title="Pilih akun" description="Daftar kewajiban akun yang dipilih tampil di sini." />} />
      ) : loading && !data ? <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <TabelData kolom={kolom} baris={data?.items || []} testId="per-akun-tabel"
          kosong={<EmptyState title="Akun ini belum punya kewajiban"
            description="Tambahkan langkah yang dipegangnya dengan tombol Tambah kewajiban." />} />
      )}
      {tambah && akun && (
        <FormTambahKeAkun akun={akun} aturan={semua.data?.items || []} onClose={() => setTambah(false)} onTersimpan={muat} />
      )}
    </PageLayout>
  );
}

const TABS = [
  { key: 'langkah', label: 'Per langkah', Component: PerLangkahTab },
  { key: 'akun', label: 'Per akun', Component: PerAkunTab },
];

export default function AturanKewajibanModule(props) {
  useState(() => primeHubTab('aturan-kewajiban', props.initialTab || props.defaultTab, TABS.map((t) => t.key)));
  return (
    <HubTabs hubId="aturan-kewajiban" title="Aturan kewajiban"
      subtitle="Siapa penanggung jawab setiap langkah, batas waktunya, dan cadangannya. Hanya owner dan admin yang mengubah."
      compactHeaders tabs={TABS} {...props} />
  );
}
