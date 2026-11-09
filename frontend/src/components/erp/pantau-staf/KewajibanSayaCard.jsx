/**
 * Portal Saya › Dashboard — "Kewajiban saya di sistem" (Monitoring Staf, keputusan owner 10 Nov 2026).
 * Hanya daftar kewajiban milik sendiri yang masih menunggu/terlambat, dengan tombol ke layarnya. TANPA skor
 * (K4: skor hanya untuk owner & admin). Selesai otomatis begitu datanya diisi — tidak perlu dicentang.
 */
import { ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import { EmptyState } from '../moduleAtoms';
import { StatusKewajiban, labelDokumen, lamaTerlambat, useApi, waktu } from './pantauStafShared';

export default function KewajibanSayaCard({ onNavigate }) {
  const { data, loading } = useApi('/pantau-staf/saya');
  const items = data?.items || [];
  const buka = (k) => k.link_module && onNavigate?.(k.link_module, k.link_params || undefined);
  const kolom = [
    { kunci: 'langkah', label: 'Yang perlu dikerjakan', hp: 'judul', isi: (k) => (
      <div className="min-w-0"><p className="font-medium">{k.nama}</p>
        <p className="truncate text-xs text-muted-foreground">{[labelDokumen(k), k.keterangan].filter(Boolean).join(' · ')}</p></div>) },
    { kunci: 'batas', label: 'Batas', isi: (k) => <span className="text-sm md:whitespace-nowrap">{waktu(k.tenggat)}</span> },
    { kunci: 'status', label: 'Status', isi: (k) => (k.status === 'terlambat'
      ? <span className="text-sm font-semibold text-[hsl(var(--danger-text))]">Terlambat {lamaTerlambat(k)}</span>
      : <StatusKewajiban k={k} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: false, isi: (k) => k.link_module && (
      <Button size="sm" variant="link" onClick={(e) => { e.stopPropagation(); buka(k); }}
        data-testid={`kewajiban-buka-${k.id}`}>Kerjakan<ExternalLink /></Button>) },
  ];
  return (
    <GlassCard className="space-y-3 p-4" data-testid="kewajiban-saya">
      <div>
        <h3 className="text-lg font-semibold text-foreground">Kewajiban saya di sistem</h3>
        <p className="text-sm text-muted-foreground">
          {data ? `${data.terlambat} terlambat · ${data.hari_ini} jatuh tempo hari ini. ` : ''}
          Hilang sendiri begitu datanya diisi di layar terkait.
        </p>
      </div>
      {loading && !data ? <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <TabelData kolom={kolom} baris={items} onKlikBaris={buka} testId="kewajiban-saya-tabel"
          kosong={<EmptyState title="Tidak ada kewajiban yang menunggu" description="Semua langkah yang Anda pegang sudah dikerjakan." />} />
      )}
    </GlassCard>
  );
}
