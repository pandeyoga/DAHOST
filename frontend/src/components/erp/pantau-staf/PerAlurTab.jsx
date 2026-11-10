/**
 * Monitoring Staf › Per alur — tiap alur sebagai rantai langkah: siapa pemegangnya, berapa yang menunggu/terlambat,
 * yang terlama sejak kapan, dan rata-rata waktu penyelesaian (contoh owner "staf 1 langkah a–c, staf 2 d–e").
 */
import { useState } from 'react';
import { Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PeriodPicker, { periodFromPreset } from '../finance/PeriodPicker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { RefreshButton } from '../pantau/pantauShared';
import { PRESET_PERIODE, TombolPeriksa } from './PerStafTab';
import { qs, useApi, waktu } from './pantauStafShared';

const rataJam = (j) => {
  if (j === null || j === undefined) return '—';
  if (j < 24) return `${Number(j).toLocaleString('id-ID', { maximumFractionDigits: 1 })} jam`;
  return `${Number(j / 24).toLocaleString('id-ID', { maximumFractionDigits: 1 })} hari`;
};

export default function PerAlurTab({ onNavigate }) {
  const [periode, setPeriode] = useState(() => periodFromPreset('month'));
  const { data, loading, error, reload } = useApi(`/pantau-staf/alur${qs({ dari: periode.from, sampai: periode.to })}`);
  const alur = data?.alur || [];
  const semuaLangkah = alur.flatMap((g) => g.langkah.map((x) => ({ ...x, alur: g.label })));

  const kolom = [
    { kunci: 'nama', label: 'Langkah', hp: 'judul', isi: (x) => <span className="font-medium">{x.nama}</span> },
    { kunci: 'pemegang', label: 'Pemegang', isi: (x) => (x.aktif
      ? <span className="text-sm">{x.pemegang.join(', ') || '—'}</span>
      : <StatusBadge status="nonaktif" label="Belum aktif" tone="muted" />) },
    { kunci: 'batas', label: 'Batas waktu', isi: (x) => <span className="text-sm">{x.tenggat_label}</span> },
    { kunci: 'menunggu', label: 'Menunggu', rata: 'kanan', isi: (x) => <span className="tabular-nums">{x.menunggu}</span> },
    { kunci: 'terlambat', label: 'Terlambat', rata: 'kanan', isi: (x) => (
      <span className={x.terlambat > 0 ? 'font-semibold tabular-nums text-[hsl(var(--danger-text))]' : 'tabular-nums'}>{x.terlambat}</span>) },
    { kunci: 'terlama', label: 'Terlama sejak', isi: (x) => <span className="text-sm md:whitespace-nowrap">{x.terlama_sejak ? waktu(x.terlama_sejak) : '—'}</span> },
    { kunci: 'rata', label: 'Rata-rata selesai', rata: 'kanan', isi: (x) => <span className="tabular-nums">{rataJam(x.rata_jam)}</span> },
  ];

  return (
    <PageLayout testId="pantau-staf-per-alur" title="Per alur"
      subtitle="Setiap alur sebagai rantai langkah beserta pemegangnya dan berapa yang tertahan di tiap langkah."
      actions={<TombolPeriksa onSelesai={reload} />}
      filters={<PeriodPicker value={periode} onChange={setPeriode} presets={PRESET_PERIODE} testId="alur-periode" />}
      tools={<>
        <Button type="button" variant="outline" onClick={() => onNavigate?.('aturan-kewajiban')} data-testid="alur-ke-aturan">
          <Settings2 />Atur pemegang
        </Button>
        <TombolUnduh namaBerkas={`kewajiban-per-alur-${periode.from}-${periode.to}`} namaLembar="Per alur"
          baris={semuaLangkah} testId="alur-unduh" kolom={[
            { label: 'Alur', nilai: (x) => x.alur }, { label: 'Langkah', nilai: (x) => x.nama },
            { label: 'Aktif', nilai: (x) => (x.aktif ? 'Ya' : 'Tidak') },
            { label: 'Pemegang', nilai: (x) => x.pemegang.join(', ') }, { label: 'Batas waktu', nilai: (x) => x.tenggat_label },
            { label: 'Menunggu', nilai: (x) => x.menunggu }, { label: 'Terlambat', nilai: (x) => x.terlambat },
            { label: 'Rata-rata selesai (jam)', nilai: (x) => x.rata_jam ?? '' },
          ]} />
        <RefreshButton onClick={reload} loading={loading} testId="alur-muat" />
      </>}
      summary={error && <Notice tone="danger">{error}</Notice>}>
      {loading && !data ? <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p> : (
        alur.map((g) => (
          <section key={g.alur} className="space-y-2" data-testid={`alur-${g.alur}`}>
            <h3 className="text-base font-semibold text-foreground">{g.label}</h3>
            <TabelData kolom={kolom} baris={g.langkah} kunci={(x) => x.aturan_id} testId={`alur-tabel-${g.alur}`}
              kosong={<EmptyState title="Belum ada langkah" />} />
          </section>
        ))
      )}
    </PageLayout>
  );
}
