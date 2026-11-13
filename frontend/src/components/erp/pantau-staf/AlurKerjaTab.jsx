/**
 * Pemantauan staf › Alur kerja (permintaan owner 14 Nov 2026: "grouping aktivitas per alur dan harus sesuai step by
 * step-nya berurutan").
 *
 * Satu hari dipilih. Tiap alur bisnis tampil sebagai rantai langkah BERURUTAN: berapa yang dikerjakan hari itu dan
 * oleh siapa (bukti dari dokumen, bukan centang), yang SEKARANG masih menunggu di langkah itu (dan sejak kapan),
 * catatan kejanggalan, serta kalimat "Macet di langkah N" untuk langkah pertama yang lewat batas.
 * Klik satu langkah → rinciannya terbuka tepat di bawah barisnya (RowDetail): dokumen yang dikerjakan & yang menunggu.
 * Sumber: GET /api/pantau-staf/alur (`core/pantau_staf/alur_kerja.py`, satu sumber dengan Asisten AI).
 */
import { useMemo, useState } from 'react';
import { ExternalLink, Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import DatePicker from '@/components/ui/date-picker';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout, { RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { RefreshButton } from '../pantau/pantauShared';
import { formatDateID } from '@/lib/format';
import { KEADAAN_ALUR, KEADAAN_LANGKAH, angka, hariIniWIB, jamWIB, qs, useApi, waktu } from './pantauStafShared';

const hitung = (n, satuan) => `${angka(n)} ${satuan}`;

function jumlahLabel(x) {
  if (!x.dikerjakan) return null;
  if (x.jumlah_satuan === 'rupiah') return `Rp ${angka(x.jumlah)}`;
  if (x.jumlah_satuan && x.jumlah) return hitung(x.jumlah, x.jumlah_satuan);
  return null;
}

/** "Andi 11×, Bunga 2×" */
const daftarPelaku = (p) => (p || []).map((o) => `${o.nama} ${o.kali}×`).join(', ');

function Keadaan({ x }) {
  const k = KEADAAN_LANGKAH[x.keadaan] || KEADAAN_LANGKAH.kosong;
  return <StatusBadge status={x.keadaan} label={k.label} tone={k.tone} />;
}

/** Catatan kejanggalan langsung terlihat di barisnya (tanpa membuka rincian). */
function CatatanBaris({ catatan }) {
  if (!catatan?.length) return null;
  const c = catatan[0];
  const warna = c.nada === 'danger' ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--warning-text))]';
  return (
    <p className={`mt-1 text-xs ${warna}`} data-testid="alur-catatan-baris">
      {c.nomor ? <span className="font-medium">{c.nomor}: </span> : null}{c.pesan}
      {catatan.length > 1 && <span className="text-muted-foreground"> · {catatan.length - 1} catatan lain</span>}
    </p>
  );
}

function RincianLangkah({ x, onNavigate }) {
  const kerja = x.rincian_kerja || [];
  const tunggu = x.rincian_tunggu || [];
  return (
    <div className="space-y-3" data-testid={`alur-rincian-${x.id}`}>
      {(x.catatan || []).map((c, i) => (
        <Notice key={i} tone={c.nada === 'danger' ? 'danger' : 'warning'} title={c.nomor || undefined}>{c.pesan}</Notice>
      ))}
      <div className="space-y-3">
        <section className="min-w-0 space-y-1.5">
          <p className="text-sm font-medium">Dikerjakan hari itu ({angka(x.dikerjakan)}{x.dibatalkan ? `, ${x.dibatalkan} dibatalkan` : ''})</p>
          <TabelData baris={kerja} kunci={(a) => `${a.waktu}-${a.nomor}-${a.oleh}-${a.keterangan}`} testId={`alur-kerja-${x.id}`}
            kosong={<EmptyState title="Belum ada yang dikerjakan hari itu" />} kolom={[
              { kunci: 'jam', label: 'Jam', isi: (a) => <span className="tabular-nums">{jamWIB(a.waktu)}</span> },
              { kunci: 'nomor', label: 'Dokumen', hp: 'judul', isi: (a) => (
                <div className="min-w-0 whitespace-normal md:max-w-[26rem]">
                  <p className="font-medium">{a.nomor || '—'}</p>
                  {a.keterangan && <p className={`text-xs ${a.batal ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{a.keterangan}</p>}
                </div>) },
              { kunci: 'oleh', label: 'Oleh', isi: (a) => <p className="whitespace-normal text-sm md:max-w-[14rem]">{a.oleh}</p> },
            ]} />
          {x.dikerjakan + x.dibatalkan > kerja.length && (
            <p className="text-xs text-muted-foreground">Ditampilkan {kerja.length} pertama.</p>
          )}
        </section>
        <section className="min-w-0 space-y-1.5">
          <p className="text-sm font-medium">Menunggu sekarang ({angka(x.menunggu)})</p>
          <TabelData baris={tunggu} kunci={(t) => `${t.nomor}-${t.sejak}-${t.keterangan}`} testId={`alur-tunggu-${x.id}`}
            kosong={<EmptyState title="Tidak ada yang menunggu di langkah ini" />} kolom={[
              { kunci: 'nomor', label: 'Dokumen', hp: 'judul', isi: (t) => (
                <div className="min-w-0 whitespace-normal md:max-w-[26rem]">
                  <p className="font-medium">{t.nomor || '—'}</p>
                  {t.keterangan && <p className="text-xs text-muted-foreground">{t.keterangan}</p>}
                </div>) },
              { kunci: 'sejak', label: 'Sejak', isi: (t) => <span className="text-sm md:whitespace-nowrap">{waktu(t.sejak)}</span> },
              { kunci: 'orang', label: 'Terkait', isi: (t) => <p className="whitespace-normal text-sm md:max-w-[14rem]">{t.orang || '—'}</p> },
              { kunci: 'batas', label: 'Batas', isi: (t) => (t.lewat_batas
                ? <StatusBadge status="lewat" label={t.terlambat_hari_kerja ? `Lewat ${t.terlambat_hari_kerja} hari kerja` : 'Lewat batas'} tone="danger" />
                : <span className="text-sm md:whitespace-nowrap">{waktu(t.batas)}</span>) },
            ]} />
        </section>
      </div>
      {x.link_module && (
        <Button variant="link" size="sm" className="px-0" onClick={() => onNavigate?.(x.link_module)}
          data-testid={`alur-buka-${x.id}`}>
          <ExternalLink />Buka layar {x.nama.toLowerCase()}
        </Button>
      )}
    </div>
  );
}

function TabelAlur({ g, buka, setBuka, onNavigate }) {
  const kolom = [
    { kunci: 'langkah', label: 'Langkah', hp: 'judul', isi: (x) => (
      <div className="flex min-w-0 items-start gap-1.5 whitespace-normal md:w-[20rem]">
        <span className="-ml-1 hidden md:block">
          <RowToggle open={buka === x.id} onClick={(e) => { e.stopPropagation(); setBuka(buka === x.id ? '' : x.id); }}
            label={`Lihat rincian ${x.nama}`} testId={`alur-toggle-${x.id}`} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium"><span className="tabular-nums text-muted-foreground">{x.urutan}.</span> {x.nama}</p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-xs text-muted-foreground">{x.bagian}</span>
            <Keadaan x={x} />
          </div>
          <CatatanBaris catatan={x.catatan} />
        </div>
      </div>) },
    { kunci: 'hari', label: 'Dikerjakan hari itu', isi: (x) => (
      <div className="min-w-0 whitespace-normal md:w-[8.5rem]">
        <p className="text-sm">{x.dikerjakan ? hitung(x.dikerjakan, x.satuan) : '—'}</p>
        {jumlahLabel(x) && <p className="text-xs text-muted-foreground">{jumlahLabel(x)}</p>}
        {x.dibatalkan > 0 && <p className="text-xs text-[hsl(var(--danger-text))]">{x.dibatalkan} dibatalkan</p>}
      </div>) },
    { kunci: 'oleh', label: 'Oleh', isi: (x) => (
      <p className="whitespace-normal text-sm md:w-[12rem]">
        {daftarPelaku(x.pelaku) || (x.dibatalkan ? `dibatalkan: ${daftarPelaku(x.pelaku_batal)}` : '—')}
      </p>) },
    { kunci: 'tunggu', label: 'Menunggu sekarang', isi: (x) => (x.menunggu ? (
      <div className="min-w-0 whitespace-normal md:w-[10.5rem]">
        <p className={x.lewat_batas ? 'text-sm font-medium text-[hsl(var(--danger-text))]' : 'text-sm'}>
          {hitung(x.menunggu, x.satuan)}{x.lewat_batas ? ` · ${x.lewat_batas} lewat batas` : ''}
        </p>
        <p className="text-xs text-muted-foreground">terlama sejak {formatDateID(x.terlama_sejak)}</p>
      </div>) : <p className="text-sm text-muted-foreground md:w-[10.5rem]">—</p>) },
    { kunci: 'pj', label: 'Penanggung jawab', isi: (x) => (
      <div className="min-w-0 whitespace-normal md:w-[10rem]">
        <p className="text-sm">{x.penanggung_jawab?.length ? x.penanggung_jawab.join(', ') : '—'}</p>
        {x.batas_label && <p className="text-xs text-muted-foreground">batas {x.batas_label}</p>}
      </div>) },
  ];
  return (
    <TabelData kolom={kolom} baris={g.langkah} kunci={(x) => x.id} testId={`alur-tabel-${g.alur}`}
      onKlikBaris={(x) => setBuka(buka === x.id ? '' : x.id)}
      rincian={(x) => (buka === x.id ? <RincianLangkah x={x} onNavigate={onNavigate} /> : null)} />
  );
}

export default function AlurKerjaTab({ onNavigate }) {
  const [tanggal, setTanggal] = useState(hariIniWIB);
  const [saring, setSaring] = useState('');
  const [buka, setBuka] = useState('');
  const { data, loading, error, reload } = useApi(`/pantau-staf/alur${qs({ tanggal })}`);
  const alur = useMemo(() => data?.alur || [], [data]);
  const r = data?.ringkasan || {};
  const opsi = [
    { key: '', label: 'Semua alur', count: alur.length },
    { key: 'macet', label: 'Macet', count: alur.filter((g) => g.keadaan === 'macet').length },
    { key: 'catatan', label: 'Ada catatan', count: alur.filter((g) => g.catatan > 0).length },
    { key: 'kosong', label: 'Tidak ada kegiatan', count: alur.filter((g) => g.keadaan === 'kosong').length },
  ];
  const tampil = alur.filter((g) => !saring || (saring === 'catatan' ? g.catatan > 0 : g.keadaan === saring));
  const semuaLangkah = alur.flatMap((g) => g.langkah.map((x) => ({ ...x, alur: g.label })));

  return (
    <PageLayout testId="pantau-staf-alur" title="Alur kerja"
      subtitle="Setiap alur dibaca berurutan per langkah: yang dikerjakan hari itu, oleh siapa, dan yang masih menunggu."
      filters={<>
        <div className="w-full sm:w-44">
          <DatePicker value={tanggal} onChange={(v) => v && setTanggal(v)} max={hariIniWIB()} bolehKosong={false}
            testId="alur-tanggal" />
        </div>
        <FilterChips options={opsi} value={saring} onChange={setSaring} hideWhenEmpty={false} testId="alur-saring" />
      </>}
      tools={<>
        <Button type="button" variant="outline" onClick={() => onNavigate?.('aturan-kewajiban')} data-testid="alur-ke-aturan">
          <Settings2 />Atur penanggung jawab
        </Button>
        <TombolUnduh namaBerkas={`alur-kerja-${tanggal}`} namaLembar="Alur kerja" baris={semuaLangkah} testId="alur-unduh"
          kolom={[
            { label: 'Alur', nilai: (x) => x.alur }, { label: 'No', nilai: (x) => x.urutan },
            { label: 'Langkah', nilai: (x) => x.nama }, { label: 'Bagian', nilai: (x) => x.bagian },
            { label: 'Dikerjakan', nilai: (x) => x.dikerjakan }, { label: 'Satuan', nilai: (x) => x.satuan },
            { label: 'Jumlah', nilai: (x) => (x.jumlah_satuan ? x.jumlah : '') },
            { label: 'Satuan jumlah', nilai: (x) => x.jumlah_satuan || '' },
            { label: 'Oleh', nilai: (x) => daftarPelaku(x.pelaku) },
            { label: 'Dibatalkan', nilai: (x) => x.dibatalkan || 0 },
            { label: 'Menunggu sekarang', nilai: (x) => x.menunggu }, { label: 'Lewat batas', nilai: (x) => x.lewat_batas },
            { label: 'Terlama sejak', nilai: (x) => (x.terlama_sejak ? waktu(x.terlama_sejak) : '') },
            { label: 'Penanggung jawab', nilai: (x) => (x.penanggung_jawab || []).join(', ') },
            { label: 'Keadaan', nilai: (x) => (KEADAAN_LANGKAH[x.keadaan] || {}).label || '' },
            { label: 'Catatan', nilai: (x) => (x.catatan || []).map((c) => `${c.nomor ? `${c.nomor}: ` : ''}${c.pesan}`).join(' | ') },
          ]} />
        <RefreshButton onClick={reload} loading={loading} testId="alur-muat" />
      </>}
      summary={<>
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="alur-kartu">
          <StatTile label="Pekerjaan tercatat" value={data ? angka(r.pekerjaan) : '—'}
            sub={data ? `oleh ${r.orang} orang` : ''} testId="alur-kartu-pekerjaan"
            hint="Jumlah langkah yang dikerjakan pada tanggal ini di semua alur, dibaca dari dokumen yang dibuat atau diubah" />
          <StatTile label="Alur macet" value={data ? `${r.alur_macet} / ${alur.length}` : '—'}
            accent={r.alur_macet > 0 ? 'danger' : 'default'} testId="alur-kartu-macet"
            hint="Alur yang punya dokumen menunggu melewati batas waktunya di salah satu langkah" />
          <StatTile label="Menunggu sekarang" value={data ? angka(r.menunggu) : '—'}
            sub={data ? `${r.lewat_batas} lewat batas` : ''} accent={r.lewat_batas > 0 ? 'warning' : 'default'}
            testId="alur-kartu-menunggu"
            hint="Dokumen yang saat ini masih menunggu langkah berikutnya dikerjakan (keadaan sekarang, bukan tanggal yang dipilih)" />
          <StatTile label="Catatan kejanggalan" value={data ? angka(r.catatan) : '—'}
            accent={r.catatan > 0 ? 'warning' : 'default'} testId="alur-kartu-catatan"
            hint="Perlu dicek: hasil potong jauh dari rencana, scan keluar dibatalkan, PO draf sudah dikirim" />
        </div>
      </>}>
      {loading && !data ? <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <>
          {tampil.length === 0 && (
            <EmptyState title="Tidak ada alur yang cocok" description="Ubah saringan untuk melihat alur lain." />
          )}
          {tampil.map((g) => {
            const k = KEADAAN_ALUR[g.keadaan] || KEADAAN_ALUR.kosong;
            return (
              <section key={g.alur} className="space-y-2" data-testid={`alur-${g.alur}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="text-base font-semibold text-foreground">{g.label}</h3>
                    <p className="text-xs text-muted-foreground">{g.urutan_ringkas}</p>
                  </div>
                  <StatusBadge status={g.keadaan} label={k.label} tone={k.tone} />
                </div>
                <p className={`text-sm ${g.keadaan === 'macet' ? 'font-medium text-[hsl(var(--danger-text))]' : 'text-foreground/80'}`}
                  data-testid={`alur-kalimat-${g.alur}`}>
                  {g.kalimat}
                </p>
                <TabelAlur g={g} buka={buka} setBuka={setBuka} onNavigate={onNavigate} />
              </section>
            );
          })}
          <p className="text-xs text-muted-foreground">
            Tanggal {formatDateID(`${tanggal}T00:00:00+07:00`)}. Kolom "Menunggu sekarang" selalu keadaan saat ini.
            Batas waktu mengikuti Aturan kewajiban bila langkah itu sudah diatur penanggung jawabnya.
          </p>
        </>
      )}
    </PageLayout>
  );
}
