/**
 * PesanAsisten — satu jawaban Asisten AI, dirender dari `blok` (riwayat) atau dari peristiwa SSE yang sedang mengalir
 * (bentuknya sama, lihat `peristiwaSse.terapkanPeristiwa`). Urutan isi = urutan datang.
 *
 *   ┌ "Menganalisis…" (bisa dibuka): langkah alat (`alat`) + ringkasan pemikiran (`pikir_ringkas`)
 *   ├ teks markdown aman · grafik · tabel · tombol unduh laporan (PDF/Excel) · kartu tindakan (Tahap B, KartuTindakan)
 *   ├ chip ingatan (Tahap D): "Diingat: …" / "Dilupakan: …" + tautan ke halaman Ingatan AI (ChipIngatan)
 *   ├ sumber: data internal (label) & web (tautan, tab baru)
 *   └ galat ramah + "Coba lagi" · catatan "dihentikan"
 */
import { memo, useMemo, useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Database, Download, FileSpreadsheet, FileText, Globe,
  Loader2, RotateCcw, Sparkles, X,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import MarkdownAman, { isSafeUrl } from '@/components/ui/markdown-aman';
import { cn } from '@/lib/utils';
import { blokIngatan } from './adapterTahapCD';
import { unduhLaporan } from './asistenApi';
import ChipIngatan from './ChipIngatan';
import GrafikAsisten from './GrafikAsisten';
import KartuTindakan from './KartuTindakan';
import { JENIS_ISI as KONTEN } from './peristiwaSse';
import TabelAsisten from './TabelAsisten';

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

/** Baris "Menganalisis…" yang bisa dibuka: langkah alat + ringkasan pemikiran. */
function LangkahAnalisis({ langkah, pikir, mengalir, statusTeks, adaIsi }) {
  const [buka, setBuka] = useState(false);
  const jalan = langkah.filter((l) => l.keadaan === 'mulai').length;
  const gagal = langkah.filter((l) => l.keadaan === 'gagal').length;
  if (!mengalir && !langkah.length && !pikir) return null;
  const sibuk = mengalir && (!adaIsi || jalan > 0);
  const aktif = langkah.filter((l) => l.keadaan === 'mulai').slice(-1)[0];
  const judul = sibuk
    ? (statusTeks || aktif?.label || 'Menganalisis…')
    : `Langkah analisis${langkah.length ? ` · ${langkah.length} langkah` : ''}${gagal ? ` · ${gagal} gagal` : ''}`;
  const Panah = buka ? ChevronDown : ChevronRight;
  const bisaDibuka = langkah.length > 0 || !!pikir;
  return (
    <div className="space-y-1.5" data-testid="asisten-langkah">
      <button type="button" onClick={() => bisaDibuka && setBuka((b) => !b)} aria-expanded={buka}
        disabled={!bisaDibuka}
        className="inline-flex max-w-full items-center gap-1.5 text-left text-xs text-muted-foreground hover:text-foreground disabled:cursor-default"
        data-testid="asisten-langkah-toggle">
        {sibuk
          ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-hidden="true" />
          : <Panah className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
        <span className={cn('truncate', sibuk && 'text-foreground/80')} data-testid="asisten-langkah-judul">{judul}</span>
      </button>
      {buka && (
        <div className="ml-1.5 space-y-2 border-l-2 border-[var(--glass-border)] pl-3" data-testid="asisten-langkah-isi">
          {langkah.length > 0 && (
            <ol className="space-y-1">
              {langkah.map((l, i) => (
                <li key={l.id || i} className="flex items-start gap-1.5 text-xs" data-testid="asisten-langkah-item" data-keadaan={l.keadaan}>
                  {l.keadaan === 'mulai' && <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin text-primary" aria-label="Berjalan" />}
                  {l.keadaan === 'selesai' && <Check className="mt-0.5 h-3 w-3 shrink-0 text-[hsl(var(--success))]" aria-label="Selesai" />}
                  {l.keadaan === 'gagal' && <X className="mt-0.5 h-3 w-3 shrink-0 text-destructive" aria-label="Gagal" />}
                  <span className="min-w-0 text-foreground/80">
                    {l.label || 'Membaca data'}
                    {l.keadaan === 'gagal' && l.pesan && <span className="block text-muted-foreground">{l.pesan}</span>}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {pikir && (
            <p className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground" data-testid="asisten-pikir">
              {pikir}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function SumberChips({ item }) {
  if (!item.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="asisten-sumber">
      <span className="text-xs text-muted-foreground">Sumber:</span>
      {item.map((s, i) => {
        const web = s.jenis === 'web' && isSafeUrl(s.url);
        const Ikon = s.jenis === 'web' ? Globe : Database;
        const label = s.label || (web ? hostOf(s.url) : 'Data internal');
        const kelas = 'inline-flex max-w-[16rem] items-center gap-1 rounded-full border border-[var(--glass-border)] px-2 py-0.5 text-xs';
        return web ? (
          <a key={i} href={s.url} target="_blank" rel="noopener noreferrer" title={s.url}
            className={cn(kelas, 'text-primary hover:border-[hsl(var(--primary)/0.4)]')} data-testid="asisten-sumber-web">
            <Ikon className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="truncate">{label}</span>
          </a>
        ) : (
          <span key={i} className={cn(kelas, 'text-foreground/75')} data-testid="asisten-sumber-data" title={label}>
            <Ikon className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="truncate">{label}</span>
          </span>
        );
      })}
    </div>
  );
}

function TombolLaporan({ laporan }) {
  const [sibuk, setSibuk] = useState(false);
  const xlsx = String(laporan.format || '').toLowerCase() === 'xlsx';
  const Ikon = xlsx ? FileSpreadsheet : FileText;
  const unduh = async () => {
    setSibuk(true);
    try {
      await unduhLaporan(laporan);
    } catch (e) {
      toast.error(e?.message || 'Laporan gagal diunduh.');
    } finally {
      setSibuk(false);
    }
  };
  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--glass-border)] px-3 py-2" data-testid="asisten-laporan">
      <Ikon className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{laporan.judul || 'Laporan'}</p>
        <p className="text-xs text-muted-foreground">{xlsx ? 'Excel' : 'PDF'}</p>
      </div>
      <Button variant="outline" size="sm" onClick={unduh} disabled={sibuk || !laporan.url}
        data-testid={`asisten-laporan-unduh-${xlsx ? 'xlsx' : 'pdf'}`}>
        {sibuk ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        {xlsx ? 'Unduh Excel' : 'Unduh PDF'}
      </Button>
    </div>
  );
}

function PesanAsisten({ pesan, onCobaLagi, onPutuskan, onNavigate, sibukUtas = false, tindakanAktif = true }) {
  const { blok = [], keadaan, statusTeks, galat } = pesan;
  const mengalir = keadaan === 'mengalir';
  const { langkah, pikir, konten, sumber, ingatan } = useMemo(() => {
    const seen = new Set();
    const src = [];
    blok.filter((b) => b.jenis === 'sumber').forEach((b) => (b.item || []).forEach((it) => {
      const k = `${it.jenis}|${it.url || ''}|${it.label || ''}`;
      if (!seen.has(k)) { seen.add(k); src.push(it); }
    }));
    return {
      langkah: blok.filter((b) => b.jenis === 'alat'),
      pikir: blok.filter((b) => b.jenis === 'pikir_ringkas').map((b) => b.isi || '').join('\n').trim(),
      konten: blok.filter((b) => KONTEN.has(b.jenis)),
      sumber: src,
      ingatan: blok.filter((b) => b.jenis === 'ingatan').map(blokIngatan).filter(Boolean),
    };
  }, [blok]);
  const adaIsi = konten.length > 0;

  return (
    <article className="flex items-start gap-3" data-testid="asisten-pesan-asisten" data-keadaan={keadaan} aria-busy={mengalir}>
      <span className="mt-0.5 hidden h-7 w-7 shrink-0 place-items-center rounded-full bg-[hsl(var(--primary)/0.12)] text-primary sm:grid" aria-hidden="true">
        <Sparkles className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1 space-y-3">
        <LangkahAnalisis langkah={langkah} pikir={pikir} mengalir={mengalir} statusTeks={statusTeks} adaIsi={adaIsi} />
        {konten.map((b, i) => {
          if (b.jenis === 'teks') {
            return (
              <MarkdownAman key={i} text={b.isi} className="leading-relaxed" testId="asisten-teks" />
            );
          }
          if (b.jenis === 'grafik') return <GrafikAsisten key={b.id || i} spec={b.spec} />;
          if (b.jenis === 'tabel') return <TabelAsisten key={b.id || i} judul={b.judul} kolom={b.kolom} baris={b.baris} catatan={b.catatan} />;
          if (b.jenis === 'tindakan') {
            return (
              <KartuTindakan key={b.id || i} blok={b} onPutuskan={onPutuskan} onNavigate={onNavigate}
                nonaktif={sibukUtas || !onPutuskan} tindakanAktif={tindakanAktif} />
            );
          }
          return <TombolLaporan key={b.id || i} laporan={b} />;
        })}
        <ChipIngatan item={ingatan} onNavigate={onNavigate} />
        <SumberChips item={sumber} />
        {keadaan === 'galat' && (
          <div className="flex flex-wrap items-center gap-2" role="alert" data-testid="asisten-galat">
            <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
            <span className="min-w-0 flex-1 text-sm text-foreground/85">{galat?.pesan || 'Asisten AI gagal menjawab.'}</span>
            {onCobaLagi && (
              <Button variant="outline" size="sm" onClick={() => onCobaLagi(pesan)} data-testid="asisten-coba-lagi">
                <RotateCcw className="h-4 w-4" /> Coba lagi
              </Button>
            )}
          </div>
        )}
        {keadaan === 'terhenti' && (
          <p className="text-xs text-muted-foreground" data-testid="asisten-terhenti">
            {adaIsi ? 'Jawaban dihentikan.' : 'Jawaban dihentikan sebelum ada isi.'}
          </p>
        )}
      </div>
    </article>
  );
}

export default memo(PesanAsisten);
