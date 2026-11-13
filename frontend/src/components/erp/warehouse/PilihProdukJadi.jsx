/**
 * PilihProdukJadi — cari barang jadi lalu centang BANYAK sekaligus, TANPA scan (permintaan owner 10 Nov 2026:
 * "barang keluar product di gudang tanpa scan bisa dicari dan bisa pilih multiple").
 *
 * Dipakai di dalam FormPopup dua layar yang sudah ada (bukan layar baru):
 *   • Gudang › Scan Keluar Penjualan › "Pilih tanpa scan"   (lokasiId diisi → stok di lokasi itu)
 *   • Gudang › Master Item › Produk jadi › "Keluarkan stok"  (adaStok → hanya yang punya stok di suatu lokasi)
 *
 * Data: GET /api/rahaza/fg-pick (backend/core/fg_pick.py). Stok per lokasi dan alasan "bukan stok jual" dihitung
 * server dengan aturan yang sama dengan scan — layar ini tidak menghitung ulang. Hasil cari = tabel (TabelData,
 * kartu ringkas di HP); baris diklik atau kotaknya dicentang untuk memilih.
 *
 * Props: terpilih = { [id]: any } (yang sudah dipilih) · onUbah(item, centang) · alasanTolak(item) → teks | null
 *        · cari + onCari (opsional) → kata cari dipegang induk, mis. untuk draf yang bertahan saat popup ditutup
 */
import { useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import TabelData from '@/components/ui/tabel-data';
import { apiFetch } from '@/lib/api';
import { EmptyState, Notice } from '../moduleAtoms';

const pcs = (n) => Number(n || 0).toLocaleString('id-ID');
/** Warna · ukuran yang BELUM tertulis di nama (nama master FG sering sudah memuat "[Hitam · M]"). */
const tanpaSpasi = (s) => String(s).replace(/\s+/g, '');
const memuat = (nama, v) => {
  const e = tanpaSpasi(v).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // kata utuh (bukan "m" di "Lumi"); spasi diabaikan ("ALL SIZE" di nama = "ALLSIZE" di varian)
  return !!e && new RegExp(`(^|[^\\p{L}\\p{N}])${e}([^\\p{L}\\p{N}]|$)`, 'iu').test(tanpaSpasi(nama));
};
export const varianTeks = (it) => {
  const nama = String(it?.name || '');
  return [it?.color, it?.size].filter((v) => v && !memuat(nama, v)).join(' · ');
};
export const namaBarang = (it) => [it?.name, varianTeks(it)].filter(Boolean).join(' · ');
/** Stok yang ditampilkan: di lokasi terpilih, atau jumlah semua lokasi yang memegangnya. */
export const stokTampil = (it, lokasiId) => (lokasiId
  ? Number(it?.stok_lokasi || 0)
  : (it?.lokasi || []).reduce((a, l) => a + Number(l.qty || 0), 0));

/**
 * Kolom "Barang" untuk TabelData di dalam popup: SKU + nama (dipotong, nama lengkap di tooltip) dalam SATU sel —
 * tabel bersama memakai lebar isi (min-w-max), jadi teks panjang tidak boleh melebarkan popup. Di HP: SKU = judul
 * kartu, nama (+ catatan) = keterangan. `ambil(baris)` → item; `catatan(baris)` → teks merah opsional.
 */
export function kolomBarang(ambil, catatan) {
  const ket = (b) => [namaBarang(ambil(b)), catatan?.(b)].filter(Boolean).join(' — ');
  return [
    { kunci: 'barang', label: 'Barang', hp: false, isi: (b) => {
      const it = ambil(b);
      const c = catatan?.(b);
      return (
        <div className="min-w-0">
          <div className="tabular-nums font-medium">{it.code}</div>
          <div className="max-w-[17rem] truncate text-xs text-muted-foreground" title={namaBarang(it)}>{namaBarang(it)}</div>
          {c && <div className="max-w-[17rem] truncate text-xs text-[hsl(var(--danger-text))]" title={c}>{c}</div>}
        </div>
      );
    } },
    { kunci: 'hp-sku', label: '', hp: 'judul', lebar: 'hidden', isi: (b) => <span className="tabular-nums">{ambil(b).code}</span> },
    { kunci: 'hp-ket', label: '', hp: 'keterangan', lebar: 'hidden', isi: ket },
  ];
}

export default function PilihProdukJadi({
  lokasiId = '', adaStok = false, terpilih = {}, onUbah, alasanTolak, testId = 'pilih-produk',
  cari: cariLuar, onCari,
}) {
  // 14 Nov 2026: kata cari boleh dipegang induk (`cari` + `onCari`) supaya ikut tersimpan sebagai draf
  // (Scan Keluar). Tanpa kedua prop itu, kata cari tetap milik komponen ini seperti dulu.
  const terkontrol = cariLuar !== undefined;
  const [cariSendiri, setCariSendiri] = useState('');
  const cari = terkontrol ? (cariLuar || '') : cariSendiri;
  const setCari = (v) => { if (terkontrol) onCari?.(v); else setCariSendiri(v); };
  const [q, setQ] = useState(() => cari.trim());
  const [hasil, setHasil] = useState({ items: [], total: 0, terpotong: false });
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  // Jawaban lama tidak boleh menimpa hasil cari yang lebih baru (pelajaran FGProductPickerDialog, Tahap 5).
  const urutan = useRef(0);

  useEffect(() => {
    const t = setTimeout(() => setQ(cari.trim()), 300);
    return () => clearTimeout(t);
  }, [cari]);

  useEffect(() => {
    const n = ++urutan.current;
    setMemuat(true);
    setGalat('');
    const qs = new URLSearchParams({ limit: '50' });
    if (q) qs.set('q', q);
    if (lokasiId) qs.set('location_id', lokasiId);
    if (adaStok) qs.set('ada_stok', 'true');
    apiFetch(`/api/rahaza/fg-pick?${qs}`)
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (n !== urutan.current) return;
        if (!r.ok) {
          setGalat(d.detail || 'Daftar barang gagal dimuat.');
          setHasil({ items: [], total: 0, terpotong: false });
        } else {
          setHasil({ items: d.items || [], total: d.total || 0, terpotong: !!d.terpotong });
        }
      })
      .catch(() => { if (n === urutan.current) setGalat('Jaringan putus — daftar barang gagal dimuat. Ketik ulang kata cari.'); })
      .finally(() => { if (n === urutan.current) setMemuat(false); });
  }, [q, lokasiId, adaStok]);

  const tolak = (it) => (alasanTolak ? alasanTolak(it) : null);
  const balik = (it) => { if (!tolak(it)) onUbah?.(it, !terpilih[it.id]); };

  const kolom = [
    { kunci: 'pilih', label: '', lebar: 'w-10', hp: 'aksi', isi: (it) => (
      <Checkbox checked={!!terpilih[it.id]} disabled={!!tolak(it)} aria-label={`Pilih ${it.code}`}
        data-testid={`${testId}-centang-${it.code}`} onCheckedChange={(c) => onUbah?.(it, c === true)} />
    ) },
    ...kolomBarang((it) => it, tolak),
    { kunci: 'stok', label: lokasiId ? 'Stok lokasi' : 'Stok', rata: 'kanan', isi: (it) => {
      const s = stokTampil(it, lokasiId);
      return <span className={`tabular-nums ${s <= 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>{pcs(s)} {it.unit || 'pcs'}</span>;
    } },
  ];

  const judulKosong = memuat ? 'Memuat barang jadi…'
    : q ? 'Tidak ada barang jadi yang cocok'
      : lokasiId ? 'Lokasi ini belum memegang stok barang jadi' : 'Belum ada barang jadi yang punya stok';

  return (
    <div className="space-y-2" data-testid={testId}>
      <div className="relative w-full">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={cari} onChange={(e) => setCari(e.target.value)} autoFocus
          onKeyDown={(e) => { if (e.key === 'Enter') e.preventDefault(); }}   // Enter = cari, bukan Simpan formulir
          placeholder="Cari nama, SKU, warna, atau ukuran" aria-label="Cari barang jadi" className="pl-8 pr-9"
          data-testid={`${testId}-cari`} />
        {cari && (
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => setCari('')}
            aria-label="Kosongkan pencarian" title="Kosongkan pencarian"
            className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground">
            <X />
          </Button>
        )}
      </div>
      {galat && <Notice tone="danger" testId={`${testId}-galat`}>{galat}</Notice>}
      <div className="max-h-[40vh] overflow-y-auto">
        <TabelData kolom={kolom} baris={hasil.items} testId={`${testId}-hasil`} onKlikBaris={balik}
          kosong={<EmptyState title={judulKosong}
            description={memuat ? undefined : 'Ketik nama, SKU, warna, atau ukuran. Setiap kata harus cocok.'} />} />
      </div>
      {!memuat && hasil.items.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid={`${testId}-jumlah`}>
          {hasil.terpotong
            ? `${pcs(hasil.items.length)} dari ${pcs(hasil.total)} barang ditampilkan — ketik kata lain untuk mempersempit.`
            : `${pcs(hasil.items.length)} barang ditampilkan.`}
          {!q && (lokasiId ? ' Tanpa kata cari: hanya barang yang punya stok di lokasi ini.' : '')}
        </p>
      )}
    </div>
  );
}
