/**
 * Monitoring Staf › Macet sekarang — "menunggu input siapa, sejak kapan".
 * Satu baris = satu kewajiban yang batasnya lewat (atau, bila dipilih, yang masih menunggu). Klik baris → rantai
 * langkah dokumen itu (siapa mengerjakan langkah sebelumnya, kapan). Ingatkan = satu pesan ke pemegang per hari.
 */
import { useState } from 'react';
import { BellRing, ExternalLink, HandHeart } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import DetailPopup from '@/components/ui/detail-popup';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TabelData from '@/components/ui/tabel-data';
import { Textarea } from '@/components/ui/textarea';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { RefreshButton } from '../pantau/pantauShared';
import { apiPost } from '../../../lib/api';
import { TombolPeriksa } from './PerStafTab';
import { StatusKewajiban, labelDokumen, lamaTerlambat, pemegangLabel, qs, useApi, waktu } from './pantauStafShared';

const ALUR = [
  { key: '', label: 'Semua alur' }, { key: 'po', label: 'PO Produksi & Maklon' },
  { key: 'persetujuan', label: 'Persetujuan' }, { key: 'pengadaan', label: 'Pengadaan' },
  { key: 'gudang', label: 'Gudang' }, { key: 'keuangan', label: 'Keuangan' }, { key: 'sdm', label: 'SDM' },
  { key: 'marketing', label: 'Marketing' }, { key: 'umum', label: 'Aktif harian' },
];

export async function ingatkan(k, onSelesai) {
  try {
    const r = await apiPost(`/pantau-staf/kejadian/${encodeURIComponent(k.id)}/ingatkan`, {});
    toast.success(r.pesan || 'Pengingat terkirim.');
    onSelesai?.();
  } catch (e) {
    toast.error(e.message || 'Gagal mengirim pengingat.');
  }
}

export function FormMaafkan({ kejadian, onClose, onTersimpan }) {
  const ids = kejadian.ids?.length ? kejadian.ids : [kejadian.id];
  const [alasan, setAlasan] = useState('');
  const [galat, setGalat] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);
  const simpan = async () => {
    if (alasan.trim().length < 3) { setGalat('Tulis alasannya (minimal 3 huruf).'); return; }
    setMenyimpan(true);
    try {
      await Promise.all(ids.map((id) => apiPost(`/pantau-staf/kejadian/${encodeURIComponent(id)}/maafkan`,
        { alasan: alasan.trim() })));
      toast.success(ids.length > 1 ? `${ids.length} kewajiban dimaafkan dan tidak dihitung di skor.`
        : 'Kewajiban dimaafkan dan tidak dihitung di skor.');
      onTersimpan?.();
      onClose();
    } catch (e) {
      setGalat(e.message);
    } finally {
      setMenyimpan(false);
    }
  };
  return (
    <FormPopup open onClose={onClose} judul="Maafkan kewajiban ini" onSimpan={simpan} menyimpan={menyimpan}
      keterangan={`${kejadian.nama} · ${labelDokumen(kejadian)}. Tidak dihitung di skor penanggung jawabnya.`}
      labelSimpan="Maafkan" galat={galat} testId="form-maafkan">
      <Isian label="Alasan" wajib htmlFor="maaf-alasan">
        <Textarea id="maaf-alasan" value={alasan} maxLength={300} onChange={(e) => setAlasan(e.target.value)}
          placeholder="Contoh: menunggu bahan dari pemasok, bukan kelalaian staf" data-testid="maaf-alasan" />
      </Isian>
    </FormPopup>
  );
}

export function RantaiPopup({ kejadianId, onClose, onNavigate }) {
  const { data, loading, error } = useApi(`/pantau-staf/kejadian/${encodeURIComponent(kejadianId)}`);
  const k = data?.kejadian;
  return (
    <DetailPopup open onClose={onClose} judul={k ? `${k.nama} · ${labelDokumen(k)}` : 'Rincian kewajiban'}
      keterangan={k?.keterangan || k?.alur_label} status={k && <StatusKewajiban k={k} />} testId="pantau-staf-rantai"
      aksi={k?.link_module && (
        <Button size="sm" variant="outline" onClick={() => { onClose(); onNavigate?.(k.link_module, k.link_params || undefined); }}>
          <ExternalLink />Buka layar asal
        </Button>)}>
      {error && <Notice tone="danger">{error}</Notice>}
      {loading && !data ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p> : data && (
        <ol className="space-y-0 divide-y divide-[var(--glass-border)]" data-testid="rantai-langkah">
          {data.rantai.map((x) => (
            <li key={x.id} className="flex flex-wrap items-start justify-between gap-2 py-3">
              <div className="min-w-0">
                <p className="font-medium">{x.nama}{x.id === k.id ? ' (dipilih)' : ''}</p>
                <p className="text-xs text-muted-foreground">
                  {x.status === 'selesai'
                    ? `Dikerjakan ${x.pelaku_nama || 'pelaku tidak tercatat'} · ${waktu(x.selesai_at)}`
                    : `Menunggu ${pemegangLabel(x) || 'penanggung jawab belum ditetapkan'} sejak ${waktu(x.mulai)} · batas ${waktu(x.tenggat)}`}
                </p>
                {x.dimaafkan?.alasan && <p className="text-xs text-muted-foreground">Dimaafkan: {x.dimaafkan.alasan}</p>}
              </div>
              <StatusKewajiban k={x} />
            </li>
          ))}
        </ol>
      )}
    </DetailPopup>
  );
}

/** Kewajiban harian yang digabung: daftar harinya (tanggal, batas, status). */
export function GrupPopup({ grup, onClose, onNavigate }) {
  return (
    <DetailPopup open onClose={onClose} judul={`${grup.nama} · ${labelDokumen(grup)}`}
      keterangan={`Menunggu ${pemegangLabel(grup) || 'penanggung jawab belum ditetapkan'}`} status={<StatusKewajiban k={grup} />}
      testId="pantau-staf-grup"
      aksi={grup.link_module && (
        <Button size="sm" variant="outline" onClick={() => { onClose(); onNavigate?.(grup.link_module, grup.link_params || undefined); }}>
          <ExternalLink />Buka layar asal
        </Button>)}>
      <TabelData kunci={(a) => a.id} baris={grup.anggota || []} testId="grup-hari" kolom={[
        { kunci: 'hari', label: 'Tanggal', hp: 'judul', isi: (a) => labelDokumen({ periode: a.periode }) },
        { kunci: 'batas', label: 'Batas', isi: (a) => <span className="text-sm">{waktu(a.tenggat)}</span> },
        { kunci: 'status', label: 'Status', isi: (a) => <StatusKewajiban k={a} /> },
        { kunci: 'lama', label: 'Terlambat', rata: 'kanan', isi: (a) => <span className="text-sm">{lamaTerlambat(a)}</span> },
      ]} />
    </DetailPopup>
  );
}

export default function MacetTab({ onNavigate }) {
  const [alur, setAlur] = useState('');
  const [cakupan, setCakupan] = useState('terlambat');
  const [pilih, setPilih] = useState(null);
  const [maaf, setMaaf] = useState(null);
  const { data, loading, error, reload } = useApi(`/pantau-staf/macet${qs({ alur, menunggu: cakupan === 'semua' ? 1 : '' })}`);
  const baris = data?.items || [];

  const kolom = [
    { kunci: 'dok', label: 'Dokumen', hp: 'judul', isi: (k) => (
      <div className="min-w-0"><p className="font-medium">{labelDokumen(k)}</p>
        {k.keterangan && <p className="truncate text-xs text-muted-foreground md:max-w-[14rem]">{k.keterangan}</p>}</div>) },
    { kunci: 'langkah', label: 'Langkah', isi: (k) => (
      <div className="min-w-0"><p>{k.nama}</p><p className="text-xs text-muted-foreground">{k.alur_label}</p></div>) },
    { kunci: 'menunggu', label: 'Penanggung jawab', isi: (k) => (pemegangLabel(k)
      ? <span className="text-sm">{pemegangLabel(k)}</span>
      : <StatusBadge status="kosong" label="Belum ada penanggung jawab" tone="warning" />) },
    { kunci: 'sejak', label: 'Sejak', isi: (k) => <span className="text-sm md:whitespace-nowrap">{waktu(k.mulai)}{k.tanpa_waktu ? '*' : ''}</span> },
    { kunci: 'lama', label: 'Terlambat', rata: 'kanan', isi: (k) => (k.status === 'terlambat'
      ? <span className="font-semibold text-[hsl(var(--danger-text))]">{lamaTerlambat(k)}</span> : <StatusKewajiban k={k} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (k) => (
      <div className="flex justify-end gap-1">
        <Button size="icon-sm" variant="outline" disabled={!k.pemegang?.length} onClick={() => ingatkan(k, reload)}
          title="Ingatkan penanggung jawab" aria-label="Ingatkan penanggung jawab" data-testid={`ingatkan-${k.id}`}><BellRing /></Button>
        <Button size="icon-sm" variant="outline" onClick={() => setMaaf(k)} title="Maafkan (tidak dihitung di skor)"
          aria-label="Maafkan" data-testid={`maafkan-${k.id}`}><HandHeart /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="pantau-staf-macet" title="Kewajiban terlambat"
      subtitle="Langkah yang batas waktunya lewat: menunggu siapa, sejak kapan, dan siapa mengerjakan langkah sebelumnya."
      filters={<>
        <FilterChips options={[{ key: 'terlambat', label: 'Terlambat' }, { key: 'semua', label: 'Terlambat & menunggu' }]}
          value={cakupan} onChange={setCakupan} hideWhenEmpty={false} testId="macet-cakupan" />
        <SmartNativeSelect value={alur} onChange={(e) => setAlur(e.target.value)} wrapperClassName="w-56" data-testid="macet-alur">
          {ALUR.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
        </SmartNativeSelect>
      </>}
      actions={<TombolPeriksa onSelesai={reload} />}
      tools={<>
        <TombolUnduh namaBerkas="kewajiban-terlambat" namaLembar="Kewajiban terlambat" baris={baris} testId="macet-unduh" kolom={[
          { label: 'Dokumen', nilai: (k) => labelDokumen(k) }, { label: 'Keterangan', nilai: (k) => k.keterangan || '' },
          { label: 'Langkah', nilai: (k) => k.nama }, { label: 'Alur', nilai: (k) => k.alur_label },
          { label: 'Penanggung jawab', nilai: (k) => pemegangLabel(k) || 'Belum ada penanggung jawab' },
          { label: 'Sejak', nilai: (k) => waktu(k.mulai) }, { label: 'Batas', nilai: (k) => waktu(k.tenggat) },
          { label: 'Terlambat', nilai: (k) => lamaTerlambat(k) },
        ]} />
        <RefreshButton onClick={reload} loading={loading} testId="macet-muat" />
      </>}
      summary={error && <Notice tone="danger">{error}</Notice>}>
      {loading && !data ? <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <TabelData kolom={kolom} baris={baris} onKlikBaris={(k) => setPilih(k)} testId="macet-tabel"
          kosong={<EmptyState title={cakupan === 'semua' ? 'Tidak ada kewajiban yang menunggu' : 'Tidak ada yang terlambat'}
            description="Kewajiban muncul di sini setelah aturannya aktif dan langkahnya terpicu oleh data." />} />
      )}
      {baris.some((k) => k.tanpa_waktu) && (
        <p className="text-xs text-muted-foreground">* Dokumen tidak menyimpan waktu masuk tahap ini; dipakai waktu pertama kali terlihat oleh sistem.</p>
      )}
      {pilih && (pilih.gabungan > 1
        ? <GrupPopup grup={pilih} onClose={() => setPilih(null)} onNavigate={onNavigate} />
        : <RantaiPopup kejadianId={pilih.id} onClose={() => setPilih(null)} onNavigate={onNavigate} />)}
      {maaf && <FormMaafkan kejadian={maaf} onClose={() => setMaaf(null)} onTersimpan={reload} />}
    </PageLayout>
  );
}
