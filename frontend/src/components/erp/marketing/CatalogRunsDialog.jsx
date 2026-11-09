/**
 * CatalogRunsDialog — RIWAYAT AKSI MASSAL katalog + tombol Batalkan (klarifikasi owner 9 Nov 2026 §D).
 *
 * Setiap aksi massal (isi harga dari master, tayangkan yang ber-URL, arsipkan, kembalikan, rapikan item
 * tersembunyi, unggah harga & URL) tercatat: siapa, kapan, berapa item. "Batalkan" mengembalikan nilai sebelumnya
 * — item yang sudah diubah orang lain sesudahnya dilewati dan disebut, tidak ditimpa.
 */
import { useCallback, useEffect, useState } from 'react';
import { History, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import DetailPopup from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { alatUrl, batalkanAksi, panggil } from './catalogToolsApi';
import { toast } from 'sonner';

const jam = (v) => formatDateTimeID(parseServerTime(v), { fallback: '—' });
const angka = (n) => Number(n || 0).toLocaleString('id-ID');

export default function CatalogRunsDialog({ open, token, catalog, onClose, onUndone }) {
  const [runs, setRuns] = useState([]);
  const [memuat, setMemuat] = useState(false);
  const [sibuk, setSibuk] = useState('');

  const muat = useCallback(async () => {
    setMemuat(true);
    try {
      const q = catalog?.id ? `?catalog_id=${catalog.id}&limit=30` : '?limit=30';
      const b = await panggil(token, alatUrl(`/runs${q}`), { method: 'GET' });
      setRuns(b.runs || []);
    } catch (e) { toast.error(e.message, { duration: 9000 }); } finally { setMemuat(false); }
  }, [token, catalog?.id]);

  useEffect(() => { if (open) muat(); }, [open, muat]);

  const batalkan = async (r) => {
    const ok = await confirmDialog({
      title: `Batalkan "${r.kind_label}"?`,
      body: `${angka(r.n_changes)} item dikembalikan seperti sebelum aksi ini (${jam(r.at)}). Item yang sudah diubah orang lain sesudahnya tidak ditimpa.`,
      confirmLabel: 'Batalkan aksi',
    });
    if (!ok) return;
    setSibuk(r.id);
    try {
      const b = await batalkanAksi(token, r.id);
      toast.success(b.message, { duration: 10000 });
      onUndone?.();
      muat();
    } catch (e) { toast.error(e.message, { duration: 9000 }); } finally { setSibuk(''); }
  };

  return (
    <DetailPopup open={open} onClose={onClose} judul="Riwayat aksi massal" testId="catalog-runs-dialog"
      keterangan={catalog?.name ? `Aksi massal yang menyentuh ${catalog.name}.` : 'Aksi massal di katalog toko yang boleh Anda lihat.'}>
      <TabelData baris={runs} testId="catalog-runs-table"
        kolom={[
          { kunci: 'at', label: 'Waktu', isi: (r) => <span className="text-sm md:whitespace-nowrap">{jam(r.at)}</span> },
          { kunci: 'aksi', label: 'Aksi', hp: 'judul', isi: (r) => <span className="font-medium">{r.kind_label}</span> },
          { kunci: 'oleh', label: 'Oleh', isi: (r) => r.actor_name || '—' },
          { kunci: 'n', label: 'Item', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.n_changes)}</span> },
          { kunci: 'status', label: 'Status', isi: (r) => (r.undone
            ? <StatusBadge status="batal" label="Dibatalkan" tone="muted" />
            : <StatusBadge status="aktif" label="Berlaku" tone="success" />) },
          { kunci: 'aksi2', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (!r.undone && (
            <Button size="sm" variant="outline" disabled={!!sibuk} onClick={() => batalkan(r)} data-testid={`catalog-run-undo-${r.id}`}>
              <RotateCcw />Batalkan
            </Button>)) },
        ]}
        kosong={<EmptyState icon={History} title={memuat ? 'Memuat…' : 'Belum ada aksi massal'}
          description="Aksi massal di tab Item (isi harga, tayangkan, arsipkan, unggah Excel) dan Rapikan tercatat di sini." />} />
    </DetailPopup>
  );
}
