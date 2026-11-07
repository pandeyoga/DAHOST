/**
 * TombolUnduh — unduh isi tabel sebagai Excel (.xlsx) atau CSV (Standar UI/UX v2, permintaan owner 8 Nov 2026:
 * SEMUA tabel bisa diunduh). Letakkan di slot `tools` PageLayout, atau di atas tabel bila tabel ada di dalam tab.
 *
 *   <TombolUnduh namaBerkas="pengumuman" baris={baris}
 *     kolom={[{ label: 'Judul', nilai: (r) => r.title }, { label: 'Prioritas', nilai: (r) => r.priority }]} />
 *
 * Nilai angka tetap angka di Excel (bisa dijumlah); tanggal sebaiknya dikirim sudah berupa teks Indonesia.
 * Tanpa baris → tombol nonaktif dengan keterangan.
 */
import { Download, FileSpreadsheet, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

const bersihNama = (s) => String(s || 'data').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const tanggalBerkas = () => new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 10);

function susun(kolom, baris) {
  const kepala = kolom.map((k) => k.label);
  const isi = baris.map((r) => kolom.map((k) => {
    const v = k.nilai ? k.nilai(r) : r[k.kunci];
    return v === null || v === undefined ? '' : v;
  }));
  return { kepala, isi };
}

export async function unduhExcel({ namaBerkas, kolom, baris, namaLembar = 'Data' }) {
  const XLSX = await import('xlsx');
  const { kepala, isi } = susun(kolom, baris);
  const ws = XLSX.utils.aoa_to_sheet([kepala, ...isi]);
  ws['!cols'] = kepala.map((h, i) => ({
    wch: Math.min(48, Math.max(String(h).length, ...isi.slice(0, 200).map((r) => String(r[i] ?? '').length)) + 2),
  }));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, String(namaLembar).slice(0, 31));
  XLSX.writeFile(wb, `${bersihNama(namaBerkas)}-${tanggalBerkas()}.xlsx`);
}

export function unduhCsv({ namaBerkas, kolom, baris }) {
  const { kepala, isi } = susun(kolom, baris);
  const csv = [kepala, ...isi]
    .map((l) => l.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
    .join('\n');
  const url = URL.createObjectURL(new Blob([`﻿${csv}`], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${bersihNama(namaBerkas)}-${tanggalBerkas()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function TombolUnduh({ namaBerkas, kolom, baris, namaLembar, label = 'Unduh', testId = 'tombol-unduh' }) {
  const kosong = !baris || baris.length === 0;
  const jalan = async (jenis) => {
    try {
      if (jenis === 'excel') await unduhExcel({ namaBerkas, kolom, baris, namaLembar });
      else unduhCsv({ namaBerkas, kolom, baris });
    } catch (e) {
      toast.error('Gagal membuat berkas unduhan.');
    }
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" disabled={kosong} title={kosong ? 'Tidak ada data untuk diunduh' : 'Unduh isi tabel'}
          data-testid={testId}>
          <Download />{label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => jalan('excel')} data-testid={`${testId}-excel`}>
          <FileSpreadsheet className="mr-2 h-4 w-4" />Excel (.xlsx)
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => jalan('csv')} data-testid={`${testId}-csv`}>
          <FileText className="mr-2 h-4 w-4" />CSV
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
