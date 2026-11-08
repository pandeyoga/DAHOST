/**
 * lampiranAsisten — logika MURNI lampiran & berkas keluaran Asisten AI (Tahap E, 9 Nov 2026; tanpa jaringan/React).
 *
 *   - Lampiran pengguna (Kontrak K2): jenis yang didukung, batas 5 berkas & 20 MB per berkas (dicek di layar sebelum
 *     diunggah; server memeriksa lagi), penyaring berkas yang dipilih/diseret, bentuk lampiran dari riwayat.
 *   - Berkas keluaran AI (Kontrak K3): blok `{jenis: "berkas", id, nama, format, ukuran_kb, url}` dari peristiwa SSE
 *     `berkas` atau dari riwayat, dan kelompok format untuk ikon/label kartu unduh.
 * Diuji di `__tests__/lampiran.test.jsx`.
 */

export const MAKS_LAMPIRAN = 5;
export const MAKS_UKURAN_MB = 20;
export const MAKS_UKURAN = MAKS_UKURAN_MB * 1024 * 1024;

/** Ekstensi → jenis lampiran (sama dengan daftar di server, Kontrak K2). */
const JENIS_EKSTENSI = {
  xlsx: 'tabel', xls: 'tabel', csv: 'tabel',
  pdf: 'pdf',
  png: 'gambar', jpg: 'gambar', jpeg: 'gambar', webp: 'gambar', gif: 'gambar',
  txt: 'teks', md: 'teks', json: 'teks',
};
export const ACCEPT_LAMPIRAN = Object.keys(JENIS_EKSTENSI).map((e) => `.${e}`).join(',');
export const JENIS_LAMPIRAN = new Set(['tabel', 'pdf', 'gambar', 'teks']);
const TEKS_JENIS_DIDUKUNG = 'Excel, CSV, PDF, gambar, atau teks';

export function ekstensi(nama) {
  const m = /\.([a-z0-9]{1,8})$/i.exec(String(nama || '').trim());
  return m ? m[1].toLowerCase() : '';
}

/** Jenis lampiran dari nama berkas; `null` bila tidak didukung. */
export function jenisLampiran(nama) {
  return JENIS_EKSTENSI[ekstensi(nama)] || null;
}

/** Ukuran untuk dibaca orang: "850 KB", "1,5 MB" (dari KB; < 1 KB → "1 KB"). */
export function teksUkuranKb(kb) {
  if (kb === null || kb === undefined || kb === '') return ''; // ukuran tidak diketahui → tidak ditulis
  const n = Number(kb);
  if (!Number.isFinite(n) || n < 0) return '';
  if (n < 1024) return `${Math.max(1, Math.round(n)).toLocaleString('id-ID')} KB`;
  const mb = n / 1024;
  return `${mb.toLocaleString('id-ID', { maximumFractionDigits: mb < 10 ? 1 : 0 })} MB`;
}

/** Nama panjang dipotong di tengah supaya ekstensinya tetap terlihat: "laporan-penj…oktober.xlsx". */
export function potongNama(nama, maks = 28) {
  const s = String(nama || '').trim() || 'Berkas';
  if (s.length <= maks) return s;
  const ext = ekstensi(s);
  const ujung = ext ? Math.min(s.length - 1, ext.length + 1 + 6) : 6;
  const awal = Math.max(4, maks - ujung - 1);
  return `${s.slice(0, awal).trimEnd()}…${s.slice(s.length - ujung)}`;
}

/**
 * Saring berkas yang dipilih/diseret sebelum diunggah. `sudah` = jumlah lampiran yang sudah ada (tidak termasuk yang
 * gagal). Mengembalikan berkas yang boleh diunggah dan pesan penolakan (untuk toast), urut sesuai pilihan pengguna.
 */
export function saringBerkas(files, sudah = 0) {
  const diterima = [];
  const ditolak = [];
  let penuh = false;
  Array.from(files || []).forEach((f) => {
    const nama = f?.name || 'Berkas';
    if (!jenisLampiran(nama)) {
      ditolak.push({ nama, alasan: 'jenis', pesan: `"${nama}" tidak bisa dilampirkan. Jenis yang bisa: ${TEKS_JENIS_DIDUKUNG}.` });
    } else if (Number(f?.size) > MAKS_UKURAN) {
      ditolak.push({ nama, alasan: 'ukuran', pesan: `"${nama}" lebih dari ${MAKS_UKURAN_MB} MB, tidak bisa dilampirkan.` });
    } else if (!Number(f?.size)) {
      ditolak.push({ nama, alasan: 'kosong', pesan: `"${nama}" kosong, tidak bisa dilampirkan.` });
    } else if (sudah + diterima.length >= MAKS_LAMPIRAN) {
      penuh = true;
    } else {
      diterima.push(f);
    }
  });
  if (penuh) {
    ditolak.push({ nama: '', alasan: 'jumlah', pesan: `Paling banyak ${MAKS_LAMPIRAN} berkas untuk satu pertanyaan.` });
  }
  return { diterima, ditolak };
}

/** Lampiran dari server (unggah / riwayat) → `{id, nama, jenis, ukuran_kb}`; yang tanpa id dibuang. */
export function normalLampiran(daftar) {
  if (!Array.isArray(daftar)) return [];
  return daftar.filter((l) => l && typeof l === 'object' && l.id).map((l) => {
    const nama = String(l.nama || 'Berkas');
    const jenis = JENIS_LAMPIRAN.has(l.jenis) ? l.jenis : (jenisLampiran(nama) || 'teks');
    const kb = Number(l.ukuran_kb);
    return { id: String(l.id), nama, jenis, ukuran_kb: Number.isFinite(kb) ? kb : null };
  });
}

// ─── Berkas keluaran AI (Kontrak K3) ─────────────────────────────────────────

const KELOMPOK_FORMAT = {
  xlsx: ['tabel', 'Excel'], xls: ['tabel', 'Excel'], csv: ['tabel', 'CSV'],
  docx: ['dokumen', 'Dokumen Word'], doc: ['dokumen', 'Dokumen Word'],
  pptx: ['presentasi', 'Presentasi PowerPoint'], ppt: ['presentasi', 'Presentasi PowerPoint'],
  png: ['gambar', 'Gambar PNG'], jpg: ['gambar', 'Gambar JPG'], jpeg: ['gambar', 'Gambar JPG'],
  webp: ['gambar', 'Gambar WEBP'], gif: ['gambar', 'Gambar GIF'],
  pdf: ['pdf', 'PDF'],
  txt: ['teks', 'Teks'], md: ['teks', 'Teks'], json: ['teks', 'Teks'],
};

/** Format berkas → `{kelompok, label}` untuk ikon & keterangan kartu unduh. */
export function infoFormat(format) {
  const f = String(format || '').toLowerCase().replace(/^\./, '');
  const [kelompok, label] = KELOMPOK_FORMAT[f] || ['lain', f ? `Berkas ${f.toUpperCase()}` : 'Berkas'];
  return { kelompok, label };
}

/** Gambar yang boleh dipratinjau di kartu (format yang aman dibuka peramban sebagai <img>). */
export const bisaPratinjau = (format) => ['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(String(format || '').toLowerCase());

/** Peristiwa SSE `berkas` / blok riwayat → blok `{jenis: "berkas", …}`; `null` bila tanpa id. */
export function blokBerkas(d) {
  if (!d || typeof d !== 'object' || !d.id) return null;
  const id = String(d.id);
  const nama = String(d.nama || 'Berkas');
  const format = String(d.format || ekstensi(nama) || '').toLowerCase().replace(/^\./, '');
  const kb = Number(d.ukuran_kb);
  return {
    jenis: 'berkas',
    id,
    nama,
    format,
    ukuran_kb: Number.isFinite(kb) ? kb : null,
    url: d.url || `/api/asisten-ai/berkas/${encodeURIComponent(id)}`,
  };
}
