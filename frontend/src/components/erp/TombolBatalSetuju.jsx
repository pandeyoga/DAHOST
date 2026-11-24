/**
 * TombolBatalSetuju — tombol "Batalkan persetujuan" yang sama di semua layar (owner 24 Nov 2026).
 *
 *   {doc.status === 'approved' && <TombolBatalSetuju jenis="pr" id={doc.id} onSelesai={muatUlang} />}
 *
 * Tombol hanya tampil bagi yang berhak menyetujui jenis itu (`GET /api/batal-setuju/jenis` → `boleh`).
 * Untuk menu titik tiga pakai `useBolehBatal(jenis)` + `batalkanPersetujuan()` dari `@/lib/batalSetuju`.
 */
import { useEffect, useState } from 'react';
import { Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { batalkanPersetujuan, muatJenisBatal } from '@/lib/batalSetuju';

export default function TombolBatalSetuju({ jenis, id, onSelesai, size = 'sm', label = 'Batalkan persetujuan', ikonSaja = false }) {
  const [jalan, setJalan] = useState(false);
  const [boleh, setBoleh] = useState(null);
  useEffect(() => {
    let hidup = true;
    muatJenisBatal().then((m) => { if (hidup) setBoleh(Boolean(m?.[jenis]?.boleh)); });
    return () => { hidup = false; };
  }, [jenis]);
  const klik = async (e) => {
    e?.stopPropagation?.();
    if (jalan) return;
    setJalan(true);
    try {
      const r = await batalkanPersetujuan({ jenis, id });
      if (r) onSelesai?.(r);
    } finally {
      setJalan(false);
    }
  };
  if (!boleh) return null;   // belum dimuat / tidak berhak menyetujui jenis ini → tidak ditampilkan
  return (
    <Button type="button" variant={ikonSaja ? 'ghost' : 'outline'} size={ikonSaja ? 'icon-sm' : size} onClick={klik}
      disabled={jalan} title="Batalkan persetujuan" aria-label={label} data-testid={`batal-setuju-${jenis}-${id}`}>
      <Undo2 />{!ikonSaja && (jalan ? 'Memeriksa…' : label)}
    </Button>
  );
}
