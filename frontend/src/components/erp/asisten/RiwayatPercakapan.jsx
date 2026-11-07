/**
 * RiwayatPercakapan — kolom kiri Asisten AI (di HP: isi laci/Sheet).
 *   "Percakapan baru" · cari · kelompok Hari ini / Kemarin / Lebih lama · sorot percakapan aktif ·
 *   tanda kuning bila ada tindakan menunggu persetujuan (`ada_tindakan_menunggu`, Tahap B) ·
 *   tautan "Tindakan AI" (Tahap B: membuka halaman `asisten-ai-tindakan`) dan "Ingatan AI" di bawah (Tahap D: halaman
 *   `asisten-ai-ingatan`) · lencana "Briefing" / "Laporan mingguan" untuk percakapan yang dibuat otomatis (Tahap D, `jenis`).
 */
import { useMemo } from 'react';
import { Brain, ListChecks, MessageSquare, Plus, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { EmptyState } from '../moduleAtoms';
import { jenisSesi, labelJenisSesi } from './adapterTahapCD';
import { kelompokkanSesi } from './peristiwaSse';

function ItemSesi({ sesi, aktif, onPilih }) {
  const jenis = labelJenisSesi(sesi);
  return (
    <li>
      <button type="button" onClick={() => onPilih(sesi.id)} aria-current={aktif ? 'true' : undefined}
        title={sesi.judul || 'Percakapan tanpa judul'}
        className={cn(
          'flex h-9 w-full items-center gap-2 rounded-md pl-2.5 pr-2 text-left text-sm transition-colors',
          aktif ? 'bg-[hsl(var(--primary)/0.12)] font-medium text-foreground' : 'text-foreground/75 hover:bg-foreground/5 hover:text-foreground',
        )}
        data-testid="asisten-sesi-item" data-aktif={aktif ? '1' : '0'} data-jenis={jenisSesi(sesi) || undefined}>
        <MessageSquare className={cn('h-3.5 w-3.5 shrink-0', aktif ? 'text-primary' : 'text-muted-foreground')} aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{sesi.judul || 'Percakapan tanpa judul'}</span>
        {jenis && (
          <span className="shrink-0 rounded-full bg-[hsl(var(--primary)/0.12)] px-1.5 py-px text-[10px] font-medium text-primary"
            title="Dibuat otomatis oleh Asisten AI" data-testid="asisten-sesi-jenis">
            {jenis}
          </span>
        )}
        {sesi.ada_tindakan_menunggu && (
          <span className="h-2 w-2 shrink-0 rounded-full bg-[hsl(var(--warning))]" title="Ada tindakan menunggu persetujuan"
            aria-label="Ada tindakan menunggu persetujuan" data-testid="asisten-sesi-menunggu" />
        )}
      </button>
    </li>
  );
}

export default function RiwayatPercakapan({
  sesi = [], memuat, aktifId, cari, onCari, onPilih, onBaru, tampilan, onTampilan, galat,
}) {
  const kelompok = useMemo(() => {
    const q = String(cari || '').trim().toLowerCase();
    const rows = q ? sesi.filter((s) => String(s.judul || '').toLowerCase().includes(q)) : sesi;
    return kelompokkanSesi(rows);
  }, [sesi, cari]);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="asisten-riwayat">
      <div className="space-y-2 p-3">
        <Button className="w-full" onClick={onBaru} data-testid="asisten-sesi-baru">
          <Plus className="h-4 w-4" /> Percakapan baru
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input value={cari} onChange={(e) => onCari(e.target.value)} placeholder="Cari percakapan"
            aria-label="Cari percakapan" className="h-9 pl-8" data-testid="asisten-sesi-cari" />
        </div>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-2" aria-label="Riwayat percakapan">
        {memuat ? (
          <div className="space-y-2 px-1 pt-1">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
          </div>
        ) : galat ? (
          <EmptyState icon={MessageSquare} title="Riwayat gagal dimuat" description={galat} className="px-3 py-8"
            testId="asisten-sesi-galat" />
        ) : kelompok.length === 0 ? (
          <EmptyState icon={cari ? Search : MessageSquare} className="px-3 py-8" testId="asisten-sesi-kosong"
            title={cari ? 'Tidak ditemukan' : 'Belum ada percakapan'}
            description={cari ? 'Coba kata lain dari judul percakapan.' : 'Pertanyaan pertama Anda membuat percakapan baru di sini.'} />
        ) : (
          kelompok.map((g) => (
            <section key={g.key} className="pt-2" aria-label={g.label}>
              <p className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{g.label}</p>
              <ul className="space-y-0.5">
                {g.items.map((s) => <ItemSesi key={s.id} sesi={s} aktif={tampilan === 'chat' && s.id === aktifId} onPilih={onPilih} />)}
              </ul>
            </section>
          ))
        )}
      </nav>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--glass-border)] px-3 py-2">
        <Button variant="link" size="sm" className={cn('px-0', tampilan === 'tindakan' ? 'text-primary' : 'text-foreground/70')}
          onClick={() => onTampilan('tindakan')} aria-current={tampilan === 'tindakan' ? 'page' : undefined} data-testid="asisten-tautan-tindakan">
          <ListChecks className="h-4 w-4" /> Tindakan AI
        </Button>
        <Button variant="link" size="sm" className={cn('px-0', tampilan === 'ingatan' ? 'text-primary' : 'text-foreground/70')}
          onClick={() => onTampilan('ingatan')} aria-current={tampilan === 'ingatan' ? 'page' : undefined} data-testid="asisten-tautan-ingatan">
          <Brain className="h-4 w-4" /> Ingatan AI
        </Button>
      </div>
    </div>
  );
}
