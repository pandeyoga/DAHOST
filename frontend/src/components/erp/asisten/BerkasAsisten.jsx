/**
 * BerkasAsisten — tampilan berkas di Asisten AI (Tahap E, 9 Nov 2026):
 *   - `ChipLampiran`: berkas yang dilampirkan pengguna — di kotak tanya (mengunggah / gagal / siap + tombol hapus) dan
 *     di gelembung pertanyaan pada riwayat:   [▦ laporan-okt….xlsx  48 KB  ×]
 *   - `KartuBerkas`: berkas buatan AI (hasil hitung dengan kode, Kontrak K3) — ikon menurut format, nama, format &
 *     ukuran, tombol "Unduh" (fetch bertoken → blob). Gambar PNG/JPG diberi pratinjau kecil di bawahnya (dimuat
 *     dengan token yang sama; alamat sementara dibersihkan saat kartu hilang).
 * Logika murni (jenis, ukuran, format): `lampiranAsisten.js`. Nama berkas dari server selalu teks biasa (React meng-escape).
 */
import { memo, useEffect, useState } from 'react';
import {
  AlertTriangle, Download, File as IkonBerkasLain, FileImage, FileSpreadsheet, FileText, FileType, FileType2, Loader2,
  Presentation, X,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { ambilBlobBerkas, unduhBerkas } from './asistenApi';
import { bisaPratinjau, blokBerkas, infoFormat, potongNama, teksUkuranKb } from './lampiranAsisten';

/** Ikon per jenis lampiran (Kontrak K2) dan per kelompok format berkas keluaran (Kontrak K3). */
const IKON = {
  tabel: FileSpreadsheet,
  pdf: FileText,
  gambar: FileImage,
  teks: FileType,
  dokumen: FileType2,
  presentasi: Presentation,
};
export const ikonBerkas = (kelompok) => IKON[kelompok] || IkonBerkasLain;

/**
 * Satu lampiran. `keadaan`: siap | mengunggah | gagal. `onHapus` → tombol × (hanya di kotak tanya). `ringkas` = ringkasan
 * isi dari server (mis. "Excel, 2 lembar · …"), tampil sebagai keterangan saat kursor di atas chip.
 */
export const ChipLampiran = memo(function ChipLampiran({
  nama, jenis, ukuranKb, keadaan = 'siap', persen = null, galat, ringkas, onHapus, testId = 'asisten-lampiran-chip',
}) {
  const unggah = keadaan === 'mengunggah';
  const gagal = keadaan === 'gagal';
  const Ikon = unggah ? Loader2 : (gagal ? AlertTriangle : ikonBerkas(jenis));
  let status = teksUkuranKb(ukuranKb);
  if (unggah) status = persen !== null && persen < 100 ? `Mengunggah ${persen}%` : 'Mengunggah…';
  if (gagal) status = 'Gagal';
  return (
    <span title={(gagal && galat) || (!unggah && ringkas) ? `${nama} — ${gagal ? galat : ringkas}` : nama}
      data-testid={testId} data-keadaan={keadaan}
      className={cn('inline-flex max-w-full items-center gap-1.5 rounded-full border py-0.5 pl-2 text-xs sm:max-w-[20rem]',
        onHapus ? 'pr-0.5' : 'pr-2',
        gagal ? 'border-[hsl(var(--destructive)/0.45)]' : 'border-[var(--glass-border)]')}>
      <Ikon className={cn('h-3.5 w-3.5 shrink-0', gagal ? 'text-destructive' : 'text-primary', unggah && 'animate-spin')}
        aria-hidden="true" />
      <span className="truncate text-foreground/85" data-testid={`${testId}-nama`}>{potongNama(nama)}</span>
      {status && (
        <span className={cn('shrink-0 tabular-nums', gagal ? 'text-destructive' : 'text-muted-foreground')}
          data-testid={`${testId}-status`}>{status}</span>
      )}
      {onHapus && (
        <Button type="button" variant="ghost" size="icon-sm" onClick={onHapus}
          title={`Hapus lampiran ${nama}`} aria-label={`Hapus lampiran ${nama}`}
          className="h-5 w-5 shrink-0 rounded-full text-muted-foreground [&_svg]:size-3.5" data-testid={`${testId}-hapus`}>
          <X />
        </Button>
      )}
    </span>
  );
});

/** Pratinjau gambar buatan AI: dimuat lewat fetch bertoken → alamat sementara (dibersihkan saat unmount). */
function PratinjauGambar({ id, url, nama }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let hidup = true;
    let href = null;
    Promise.resolve()
      .then(() => ambilBlobBerkas({ id, url }))
      .then((blob) => {
        if (!hidup || !blob || typeof URL.createObjectURL !== 'function') return;
        href = URL.createObjectURL(blob);
        setSrc(href);
      })
      .catch(() => { /* pratinjau tidak wajib; tombol Unduh tetap ada */ });
    return () => {
      hidup = false;
      if (href) URL.revokeObjectURL(href);
    };
  }, [id, url]);
  if (!src) return null;
  return (
    <img src={src} alt={`Pratinjau ${nama}`} loading="lazy" data-testid="asisten-berkas-pratinjau"
      className="block max-h-64 w-auto max-w-full border-t border-[var(--glass-border)] object-contain" />
  );
}

/** Kartu unduh berkas buatan AI (blok `{jenis: "berkas", id, nama, format, ukuran_kb, url}`). */
export const KartuBerkas = memo(function KartuBerkas({ berkas }) {
  const [sibuk, setSibuk] = useState(false);
  const b = blokBerkas(berkas);
  if (!b) return null;
  const { kelompok, label } = infoFormat(b.format);
  const Ikon = ikonBerkas(kelompok);
  const ukuran = teksUkuranKb(b.ukuran_kb);
  const unduh = async () => {
    setSibuk(true);
    try {
      await unduhBerkas(b);
    } catch (e) {
      toast.error(e?.message || 'Berkas gagal diunduh.');
    } finally {
      setSibuk(false);
    }
  };
  return (
    <div className="overflow-hidden rounded-[var(--radius-md)] border border-[var(--glass-border)]"
      data-testid="asisten-berkas" data-format={b.format}>
      <div className="flex items-center gap-3 px-3 py-2">
        <Ikon className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" data-testid="asisten-berkas-ikon" data-kelompok={kelompok} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground" title={b.nama} data-testid="asisten-berkas-nama">{b.nama}</p>
          <p className="text-xs text-muted-foreground" data-testid="asisten-berkas-info">{ukuran ? `${label} · ${ukuran}` : label}</p>
        </div>
        <Button variant="outline" size="sm" onClick={unduh} disabled={sibuk} aria-label={`Unduh ${b.nama}`}
          data-testid="asisten-berkas-unduh">
          {sibuk ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Unduh
        </Button>
      </div>
      {bisaPratinjau(b.format) && <PratinjauGambar id={b.id} url={b.url} nama={b.nama} />}
    </div>
  );
});
