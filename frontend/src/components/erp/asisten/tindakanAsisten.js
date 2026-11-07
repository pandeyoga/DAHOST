/**
 * tindakanAsisten — logika MURNI kartu tindakan Asisten AI (Tahap B, 8 Nov 2026; tanpa jaringan/React).
 *
 * Kontrak D/E (`/api/asisten-ai`): model hanya MENYIAPKAN rencana; data berubah setelah pengguna menekan
 * "Setujui" di kartu. Berkas ini memegang:
 *   - arti tiap keadaan tindakan (label + warna StatusBadge),
 *   - pembacaan isian "Ubah" (`rencana.ubah`) → `ubahan: {kunci: nilai}` untuk `POST /tindakan/{id}/putuskan`
 *     (kunci = jalur bertitik ke `args`, mis. "toko.0.target"; inti menerapkannya lalu menjalankan `siapkan` lagi),
 *   - penerapan `tindakan_status` ke seluruh utas (kartu bisa ada di jawaban sebelumnya),
 *   - pembacaan daftar `GET /tindakan` yang toleran bentuk.
 * Diuji di `__tests__/tindakan.test.js`.
 */
import { formatDateID, formatDateTimeID, formatNumber, formatRupiah, parseIDNumber } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';

// ─── Keadaan ─────────────────────────────────────────────────────────────────
/** Keadaan tindakan (Kontrak E) → label layar + nada StatusBadge (hanya token warna). */
export const KEADAAN_TINDAKAN = {
  menunggu: { label: 'Menunggu', tone: 'warning' },
  disetujui: { label: 'Disetujui', tone: 'primary' }, // sementara: sedang dijalankan
  dijalankan: { label: 'Dijalankan', tone: 'success' },
  dibatalkan: { label: 'Dibatalkan', tone: 'muted' },
  gagal: { label: 'Gagal', tone: 'danger' },
  kedaluwarsa: { label: 'Kedaluwarsa', tone: 'muted' },
  dibalikkan: { label: 'Dibalikkan', tone: 'default' },
};

/** Kalimat bawaan di kartu bila server tidak mengirim `ringkas`/`pesan`. */
export const PESAN_BAWAAN = {
  disetujui: 'Disetujui, sedang dijalankan…',
  dijalankan: 'Perubahan sudah dijalankan.',
  dibatalkan: 'Dibatalkan. Tidak ada data yang diubah.',
  gagal: 'Perubahan gagal dijalankan. Tidak ada data yang diubah.',
  kedaluwarsa: 'Tidak diputuskan, jadi tidak dijalankan. Tidak ada data yang diubah.',
  dibalikkan: 'Perubahan sudah dibalikkan ke nilai lama.',
};

export function keadaanTindakan(k) {
  return KEADAAN_TINDAKAN[k] || { label: 'Tidak dikenal', tone: 'default' };
}

/**
 * Keadaan yang ditampilkan: `menunggu` yang sudah lewat `kedaluwarsa_pada` dianggap `kedaluwarsa`
 * (server memeriksanya saat dibaca/diputuskan; kartu yang lama terbuka tidak menunggu reload).
 */
export function keadaanEfektif(blok, now = new Date()) {
  const k = blok?.keadaan || 'menunggu';
  if (k !== 'menunggu' || !blok?.kedaluwarsa_pada) return k;
  const batas = parseServerTime(blok.kedaluwarsa_pada);
  return batas && batas.getTime() <= now.getTime() ? 'kedaluwarsa' : k;
}

/** Tautan "Buka layar …" hanya ke id modul yang sah (huruf kecil, angka, tanda minus). */
export function tautanAman(tautan) {
  const menu = typeof tautan?.menu === 'string' ? tautan.menu.trim() : '';
  if (!/^[a-z0-9][a-z0-9-]{0,80}$/.test(menu)) return null;
  return { menu, label: String(tautan.label || 'Buka layar terkait') };
}

// ─── Isian "Ubah" ────────────────────────────────────────────────────────────
const JENIS = new Set(['rupiah', 'angka', 'teks', 'tanggal', 'pilihan']);
export const jenisUbah = (f) => (JENIS.has(f?.jenis) ? f.jenis : 'teks');

/** Isian `ubah` yang sah saja (punya `kunci`). */
export function daftarUbah(rencana) {
  return (Array.isArray(rencana?.ubah) ? rencana.ubah : []).filter((f) => f && typeof f.kunci === 'string' && f.kunci);
}

/** Nilai awal kotak isian (string untuk input; MoneyInput menerima angka polos). */
export function nilaiAwalUbah(f) {
  const v = f?.nilai;
  if (v === null || v === undefined) return '';
  if (jenisUbah(f) === 'tanggal') return String(v).slice(0, 10);
  return String(v);
}

/** Baca satu isian → `{ ok, nilai }` atau `{ ok: false, galat }` (pesan ramah, bahasa Indonesia). */
export function bacaNilaiUbah(f, raw) {
  const jenis = jenisUbah(f);
  const s = raw === null || raw === undefined ? '' : String(raw).trim();
  if (!s) return { ok: false, galat: 'Isian ini wajib diisi.' };
  if (jenis === 'rupiah' || jenis === 'angka') {
    const n = typeof raw === 'number' ? raw : (/^-?\d+(\.\d+)?$/.test(s) ? Number(s) : parseIDNumber(s));
    if (n === null || !Number.isFinite(n)) return { ok: false, galat: 'Isi dengan angka.' };
    if (n < 0) return { ok: false, galat: 'Angka tidak boleh minus.' };
    return { ok: true, nilai: jenis === 'rupiah' ? Math.round(n) : n };
  }
  if (jenis === 'tanggal') {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || Number.isNaN(new Date(`${s}T00:00:00Z`).getTime())) {
      return { ok: false, galat: 'Pilih tanggal yang benar.' };
    }
    return { ok: true, nilai: s };
  }
  if (jenis === 'pilihan') {
    const opsi = (Array.isArray(f.pilihan) ? f.pilihan : []).find((o) => String(o?.nilai) === s);
    if (!opsi) return { ok: false, galat: 'Pilih salah satu pilihan.' };
    return { ok: true, nilai: opsi.nilai };
  }
  return { ok: true, nilai: s };
}

const sama = (a, b) => (typeof a === 'number' || typeof b === 'number' ? Number(a) === Number(b) : String(a ?? '') === String(b ?? ''));

/**
 * Susun `ubahan` dari isian yang diketik. Hanya kunci yang NILAINYA BERUBAH yang dikirim; kunci tetap
 * jalur bertitik apa adanya (inti yang menerapkan ke `args`).
 * @returns {{ ok: boolean, ubahan: Object<string, any>, galat: Object<string, string>, jumlah: number }}
 */
export function susunUbahan(fields, isian = {}) {
  const ubahan = {};
  const galat = {};
  for (const f of fields || []) {
    if (!f?.kunci || !(f.kunci in isian)) continue;
    const r = bacaNilaiUbah(f, isian[f.kunci]);
    if (!r.ok) { galat[f.kunci] = r.galat; continue; }
    if (!sama(r.nilai, f.nilai)) ubahan[f.kunci] = r.nilai;
  }
  const jumlah = Object.keys(ubahan).length;
  return { ok: Object.keys(galat).length === 0, ubahan, galat, jumlah };
}

/**
 * Terapkan `ubahan` ke `rencana.ubah` (cocok per `kunci`): nilai baru dipasang dan dicatat di `diubah`
 * supaya kartu yang sudah disetujui menampilkan apa yang diubah pengguna. Rencana lama tidak diubah.
 */
export function terapkanUbahanKeRencana(rencana, ubahan) {
  if (!rencana || !Object.keys(ubahan || {}).length || !daftarUbah(rencana).length) return rencana;
  const diubah = [];
  const ubah = rencana.ubah.map((f) => {
    if (!f || typeof f.kunci !== 'string' || !(f.kunci in ubahan)) return f;
    diubah.push({ kunci: f.kunci, label: f.label || 'Isian', sebelum: f.nilai, sesudah: ubahan[f.kunci], jenis: jenisUbah(f), pilihan: f.pilihan });
    return { ...f, nilai: ubahan[f.kunci] };
  });
  return diubah.length ? { ...rencana, ubah, diubah } : rencana;
}

/** Tampilan nilai isian: "Rp 140.000.000", "1.250", "09 Nov 2026", label pilihan. */
export function formatNilaiUbah(f, nilai) {
  if (nilai === null || nilai === undefined || nilai === '') return '—';
  switch (jenisUbah(f)) {
    case 'rupiah': return formatRupiah(nilai);
    case 'angka': return formatNumber(nilai, { maximumFractionDigits: 2 });
    case 'tanggal': return formatDateID(`${String(nilai).slice(0, 10)}T00:00:00+07:00`);
    case 'pilihan': {
      const o = (Array.isArray(f?.pilihan) ? f.pilihan : []).find((x) => String(x?.nilai) === String(nilai));
      return o ? String(o.label ?? o.nilai) : String(nilai);
    }
    default: return String(nilai);
  }
}

// ─── Utas ────────────────────────────────────────────────────────────────────
/** Blok kartu tindakan dari peristiwa SSE `tindakan` (bentuk = blok tersimpan, Kontrak E). */
export function blokTindakan(d) {
  return {
    jenis: 'tindakan',
    id: d.id,
    nama: d.nama,
    label: d.label,
    risiko: d.risiko === 'menengah' ? 'menengah' : 'rendah',
    keadaan: d.keadaan || 'menunggu',
    rencana: d.rencana && typeof d.rencana === 'object' ? d.rencana : {},
    kedaluwarsa_pada: d.kedaluwarsa_pada,
    ...(typeof d.bisa_dibalikkan === 'boolean' ? { bisa_dibalikkan: d.bisa_dibalikkan } : {}),
    ...(d.ringkas ? { ringkas: d.ringkas } : {}),
    ...(d.pesan ? { pesan: d.pesan } : {}),
  };
}

/** Terapkan `tindakan_status` ke satu daftar blok (blok baru bila ada yang berubah, selain itu yang lama). */
export function terapkanStatusKeBlok(blok, d) {
  if (!d?.id || !Array.isArray(blok)) return blok;
  let berubah = false;
  const baru = blok.map((b) => {
    if (b?.jenis !== 'tindakan' || b.id !== d.id) return b;
    berubah = true;
    const n = { ...b, keadaan: d.keadaan || b.keadaan };
    if (d.ringkas !== undefined) n.ringkas = d.ringkas;
    if (d.pesan !== undefined) n.pesan = d.pesan;
    if (d.rencana && typeof d.rencana === 'object') n.rencana = d.rencana;
    return n;
  });
  return berubah ? baru : blok;
}

/** `tindakan_status` untuk SELURUH utas: kartunya bisa ada di jawaban sebelumnya (alur `putuskan`). */
export function terapkanStatusTindakan(daftarPesan, d) {
  let berubah = false;
  const baru = (daftarPesan || []).map((p) => {
    if (p?.peran === 'user' || !Array.isArray(p?.blok)) return p;
    const blok = terapkanStatusKeBlok(p.blok, d);
    if (blok === p.blok) return p;
    berubah = true;
    return { ...p, blok };
  });
  return berubah ? baru : daftarPesan;
}

/** Ubah satu kartu di utas lewat fungsi (mis. memasang `ubahan` yang dikirim). */
export function ubahKartu(daftarPesan, id, fn) {
  return (daftarPesan || []).map((p) => {
    if (p?.peran === 'user' || !Array.isArray(p?.blok) || !p.blok.some((b) => b?.jenis === 'tindakan' && b.id === id)) return p;
    return { ...p, blok: p.blok.map((b) => (b?.jenis === 'tindakan' && b.id === id ? fn(b) : b)) };
  });
}

/** Semua kartu yang masih bisa diputuskan di utas. */
export function kartuMenunggu(daftarPesan, now = new Date()) {
  const out = [];
  for (const p of daftarPesan || []) {
    if (p?.peran === 'user' || !Array.isArray(p?.blok)) continue;
    for (const b of p.blok) if (b?.jenis === 'tindakan' && keadaanEfektif(b, now) === 'menunggu') out.push(b);
  }
  return out;
}

/**
 * Pertanyaan baru saat masih ada kartu menunggu: inti menandainya `kedaluwarsa` (Kontrak D). Layar
 * menandainya juga supaya tombolnya langsung hilang (server tetap sumber kebenaran saat dimuat ulang).
 */
export function kedaluwarsakanMenunggu(daftarPesan, pesan = 'Tidak diputuskan karena ada pertanyaan baru. Tidak ada data yang diubah.') {
  let utas = daftarPesan;
  for (const b of kartuMenunggu(daftarPesan)) utas = terapkanStatusTindakan(utas, { id: b.id, keadaan: 'kedaluwarsa', pesan });
  return utas;
}

// ─── Halaman Tindakan AI ─────────────────────────────────────────────────────
export const STATUS_PENYARING = ['menunggu', 'dijalankan', 'dibatalkan', 'gagal', 'kedaluwarsa', 'dibalikkan'];
export const PER_HALAMAN = 25;

/** Owner dan superadmin boleh melihat tindakan semua pengguna (`semua=1`). */
export const bolehSemuaPengguna = (peran) => ['owner', 'superadmin'].includes(String(peran || '').toLowerCase());

/** Alamat `GET /tindakan` dari penyaring layar. */
export function queryDaftar({ status, period, halaman, semua }) {
  const q = new URLSearchParams();
  if (status) q.set('status', status);
  if (period && period.preset !== 'all') {
    if (period.from) q.set('dari', period.from);
    if (period.to) q.set('sampai', period.to);
  }
  q.set('halaman', String(Math.max(1, Number(halaman) || 1)));
  if (semua) q.set('semua', '1');
  return q.toString();
}

/**
 * Jawaban `GET /tindakan` → `{ baris, total, halaman, perHalaman, jumlah }`. Toleran: daftar polos atau
 * `{items|tindakan|data}`; jumlah per keadaan opsional (`per_keadaan`/`jumlah_per_keadaan`/`jumlah`).
 */
export function bacaDaftarTindakan(d, halaman = 1) {
  let baris = [];
  if (Array.isArray(d)) baris = d;
  else for (const k of ['items', 'tindakan', 'data', 'baris']) if (Array.isArray(d?.[k])) { baris = d[k]; break; }
  const angka = (v, cadangan) => (Number.isFinite(Number(v)) && v !== null && v !== '' ? Number(v) : cadangan);
  const perHalaman = angka(d?.per_halaman ?? d?.ukuran ?? d?.limit, PER_HALAMAN);
  const total = angka(d?.total ?? d?.jumlah_total, baris.length);
  const sumber = [d?.per_keadaan, d?.jumlah_per_keadaan, d?.jumlah].find((x) => x && typeof x === 'object' && !Array.isArray(x));
  const jumlah = sumber ? Object.fromEntries(STATUS_PENYARING.map((k) => [k, angka(sumber[k], 0)])) : null;
  return { baris, total, halaman: angka(d?.halaman, halaman), perHalaman: perHalaman > 0 ? perHalaman : PER_HALAMAN, jumlah };
}

// ─── Nilai sebelum/sesudah/hasil di rincian ──────────────────────────────────
const KUNCI_TERSEMBUNYI = /^(_.*|id|ids|.*_ids?)$/i;
const ISO_RX = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;

/** "target_omzet" → "Target omzet" (istilah program tidak tampil apa adanya). */
export function labelKunci(k) {
  const s = String(k).replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim().toLowerCase();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '—';
}

function teksNilai(v) {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Ya' : 'Tidak';
  if (typeof v === 'number') return formatNumber(v, { maximumFractionDigits: 2 });
  const s = String(v);
  if (ISO_RX.test(s)) return s.length > 10 ? formatDateTimeID(parseServerTime(s)) : formatDateID(`${s}T00:00:00+07:00`);
  return s;
}

/**
 * Ratakan objek (sebelum/sesudah/hasil) jadi baris `{label, nilai}` untuk dibaca staf: kunci teknis (id,
 * `_…`) disembunyikan, objek bertingkat jadi "Induk › anak", daftar objek diberi nomor. Paling banyak `maks` baris.
 */
export function ratakanNilai(obj, maks = 40) {
  const out = [];
  let lebih = 0;
  const jalan = (v, label, dalam) => {
    if (out.length >= maks) { lebih += 1; return; }
    // bentuk inti (GET /tindakan/{id}): sebelum/sesudah = [{label, nilai}] — label sudah kalimat staf
    if (Array.isArray(v) && v.length && v.every((x) => x && typeof x === 'object' && !Array.isArray(x) && 'label' in x && 'nilai' in x)) {
      v.forEach((x) => {
        if (out.length >= maks) { lebih += 1; return; }
        const nilai = x.nilai && typeof x.nilai === 'object' ? ratakanNilai(x.nilai, 5).baris.map((b) => `${b.label}: ${b.nilai}`).join(' · ') : teksNilai(x.nilai);
        out.push({ label: label ? `${label} › ${String(x.label)}` : String(x.label ?? '—'), nilai: nilai || '—' });
      });
      return;
    }
    if (Array.isArray(v)) {
      if (v.every((x) => x === null || typeof x !== 'object')) { out.push({ label, nilai: v.length ? v.map(teksNilai).join(', ') : '—' }); return; }
      v.forEach((x, i) => jalan(x, label ? `${label} ${i + 1}` : `${i + 1}`, dalam + 1));
      return;
    }
    if (v && typeof v === 'object') {
      const kunci = Object.keys(v).filter((k) => !KUNCI_TERSEMBUNYI.test(k));
      if (!kunci.length) return;
      if (dalam > 3) { out.push({ label, nilai: `${kunci.length} isian` }); return; }
      kunci.forEach((k) => jalan(v[k], label ? `${label} › ${labelKunci(k).toLowerCase()}` : labelKunci(k), dalam + 1));
      return;
    }
    out.push({ label: label || 'Nilai', nilai: teksNilai(v) });
  };
  if (obj !== null && obj !== undefined) jalan(obj, '', 0);
  return { baris: out, lebih };
}
