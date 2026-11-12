/**
 * adapterTahapCD — SATU tempat untuk BENTUK DATA Asisten AI Tahap C + D (8 Nov 2026).
 *
 * Layar Tahap D dibangun paralel dengan backend (agen proaktif). Semua bentuk data ada di berkas ini; komponen
 * (IngatanAIModule, ChipIngatan, RiwayatPercakapan, UtasPesan, AsistenAIModule, PengaturanProaktif) hanya memakai hasil
 * normalnya. Bentuk di bawah = bentuk NYATA backend proaktif (worktree ascd-proaktif, catatan ascd_proaktif.md §2);
 * pembaca tetap toleran (array polos, {data}) supaya server lama/beda versi tidak merusak layar. Logika murni (tanpa
 * jaringan/React), diuji di `__tests__/tahapCD.test.js`.
 *
 * Bentuk:
 *   A1  GET /api/asisten-ai/ingatan → {items, total, aktif, batas_aktif: 50, maks_isi: 300, kategori: [{nilai, label}],
 *       ingatan_aktif}. Item: {id, isi, kategori, kategori_label, sumber: {sesi_id, pesan_id} | "manual", aktif, dibuat,
 *       diperbarui}. `aktif: false` = dinonaktifkan pengguna (disimpan, tidak dipakai AI) → tetap tampil, bisa diaktifkan.
 *   A2  POST /ingatan {isi, kategori} → item + `sudah_ada` (isi sama → yang lama, 200). PATCH /ingatan/{id}
 *       {isi?, kategori?, aktif?} → item (400 bila tanpa perubahan → layar hanya mengirim yang berubah). DELETE → {ok}
 *       (permanen). Galat 400/404/409 (50 aktif / 200 total) membawa `detail` kalimat Indonesia.
 *   A3  SSE `ingatan` {id: "ing-<12hex>", isi, kategori, aksi: "disimpan"|"dihapus"} dan blok tersimpan
 *       {jenis: "ingatan", …sama}. Isi sama disimpan dua kali → tidak ada peristiwa (tidak ada chip).
 *       (Sinonim aksi tetap diterima: simpan/diperbarui/hapus/dilupakan; boleh bersarang {ingatan: {...}, aksi}.)
 *   A4  GET /sessions dan /sessions/{id} → `jenis`: "chat" | "briefing" | "laporan_mingguan". Pesan pengguna buatan
 *       sistem (permintaan briefing) membawa `otomatis: true` → gelembung redup "Permintaan otomatis".
 *   A5  Tautan langsung `?portal=management&module=asisten-ai&sesi=<id>`. Dari notifikasi (link_module "asisten-ai",
 *       lewat `navigateToNotification` → App.handleNavigate → prop `deepLinkParams`) id sesi datang sebagai `sesi`
 *       (link_params / source_url) atau `link_id`/`record_id` (notifNavParams). `link_id`/`record_id` hanya dipakai bila
 *       `tujuan_modul` = "asisten-ai" (ditandai bel), karena App menyimpan parameter terakhir sampai navigasi berikutnya
 *       dan menu samping tidak menghapusnya — parameter notifikasi layar lain tidak boleh dibaca sebagai id percakapan.
 *   A6  GET/PUT /api/ai/usage/settings membawa 8 kunci `asisten_*` (KUNCI_PROAKTIF); jam "H:MM"/"HH:MM" (disimpan
 *       "HH:MM", WIB); `asisten_briefing_penerima` = ≤ 20 id pengguna aktif (kosong = semua owner aktif). Server lama
 *       tanpa kunci → PROAKTIF_BAWAAN. Kunci yang tidak dikenal server diabaikan PUT.
 *   A7  POST /proaktif/{jenis}/jalankan-sekarang (owner/superadmin; lainnya 403; jenis salah 404; 409 = gerbang AI /
 *       jalan yang sama masih berjalan):
 *       briefing | laporan_mingguan → 202 {jenis, status: "berjalan", sesi_id, tautan, pesan} (disusun di latar untuk
 *       PEMICU sendiri; notifikasi menyusul);
 *       peringatan → 200 {jenis, tanggal, pemicu, pemeriksa: {omzet|stok|po_piutang: "ok"|"gagal"},
 *       kondisi: [{kondisi: omzet|stok|po|piutang, penerima, jumlah, dikirim, alasan?}], notifikasi: n}.
 *       (Bentuk lain yang tetap dibaca: {hasil: [{user_id, sesi_id}]}, {terkirim}, {dilewati, alasan}.)
 *   A8  GET /status → `ingatan_aktif` (bool, opsional; tidak ada = dianggap aktif). GET /ingatan juga membawanya.
 *   A9  GET /api/auth/users?portal=management&status=active → [{id, name, role}] (sudah ada; pemilih penerima).
 *   A10 GET /proaktif (owner/superadmin; lainnya 403) → {jadwal: {<jenis>: {aktif, jam, berikutnya (ISO WIB)|null,
 *       label}}, penerima, ai_aktif, riwayat: [{id, jenis, tanggal, user_id?, kondisi?, pemicu, status, alasan?,
 *       sesi_id?, jumlah?, notifikasi?, dibuat, diperbarui}]} (20 terakhir).
 */

const teks = (v) => (v === null || v === undefined ? '' : String(v));
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const POLA_ID = /^[A-Za-z0-9_-]{1,80}$/;

// ─── Ingatan AI (D1) ─────────────────────────────────────────────────────────
export const BATAS_ISI_INGATAN = 300;
export const BATAS_INGATAN_AKTIF = 50;
export const MIN_ISI_INGATAN = 3;

/** Kategori ingatan → label layar + contoh singkat (untuk dialog). */
export const KATEGORI_INGATAN = [
  { kunci: 'preferensi', label: 'Preferensi', contoh: 'Mis. target minimal tumbuh 8% per bulan.' },
  { kunci: 'fakta', label: 'Fakta', contoh: 'Mis. Toko A fokus menjual pakaian anak.' },
  { kunci: 'gaya', label: 'Gaya jawaban', contoh: 'Mis. tampilkan angka dalam juta rupiah.' },
];
const KUNCI_KATEGORI = new Set(KATEGORI_INGATAN.map((k) => k.kunci));
export const labelKategori = (k, cadangan) => KATEGORI_INGATAN.find((x) => x.kunci === k)?.label || teks(cadangan) || 'Lainnya';

/** `sumber` ingatan → {jenis: "percakapan", sesi_id, pesan_id} | {jenis: "manual"}. */
export function bacaSumber(s) {
  const o = obj(s);
  const sesi = o ? teks(o.sesi_id ?? o.sesi ?? o.session_id).trim() : '';
  if (sesi && POLA_ID.test(sesi)) return { jenis: 'percakapan', sesi_id: sesi, pesan_id: teks(o.pesan_id) || null };
  return { jenis: 'manual' };
}

/** Satu ingatan (polos, {ingatan: …} atau {data: …}) → bentuk layar; null bila tanpa id. */
export function bacaIngatan(d) {
  const o = obj(d);
  if (!o) return null;
  const x = obj(o.ingatan) || (obj(o.data) && obj(o.data).id ? obj(o.data) : null) || o;
  if (!x.id) return null;
  return {
    id: String(x.id),
    isi: teks(x.isi).trim(),
    kategori: teks(x.kategori) || 'preferensi',
    kategoriLabel: labelKategori(teks(x.kategori), x.kategori_label),
    sumber: bacaSumber(x.sumber),
    aktif: x.aktif !== false,
    sudahAda: x.sudah_ada === true || o.sudah_ada === true,
    dibuat: x.dibuat || x.created_at || null,
    diperbarui: x.diperbarui || x.updated_at || x.dibuat || x.created_at || null,
  };
}

const waktuMs = (v) => {
  const t = Date.parse(teks(v));
  return Number.isFinite(t) ? t : 0;
};

/**
 * Daftar ingatan → {items (aktif dulu, lalu terbaru), batas (maks. aktif), maksIsi, ingatanAktif (saklar admin;
 * null = tidak dikirim)}. Ingatan nonaktif tetap ikut (bisa diaktifkan lagi atau dihapus).
 */
export function bacaDaftarIngatan(d) {
  const o = obj(d);
  let rows = [];
  if (Array.isArray(d)) rows = d;
  else if (o) rows = [o.items, o.ingatan, o.data].find(Array.isArray) || [];
  const items = rows.map(bacaIngatan).filter(Boolean)
    .sort((a, b) => (Number(b.aktif) - Number(a.aktif)) || (waktuMs(b.diperbarui) - waktuMs(a.diperbarui)));
  const batas = Number(o?.batas_aktif ?? o?.batas ?? o?.maks);
  const maksIsi = Number(o?.maks_isi);
  return {
    items,
    batas: Number.isFinite(batas) && batas > 0 ? batas : BATAS_INGATAN_AKTIF,
    maksIsi: Number.isFinite(maksIsi) && maksIsi > 0 ? maksIsi : BATAS_ISI_INGATAN,
    ingatanAktif: typeof o?.ingatan_aktif === 'boolean' ? o.ingatan_aktif : null,
  };
}

/** Jumlah ingatan aktif (yang dipakai AI). */
export const jumlahAktif = (items) => (items || []).filter((x) => x.aktif).length;

/** Badan PATCH hanya berisi yang berubah (backend menolak PATCH tanpa perubahan). null = tidak ada perubahan. */
export function ubahanIngatan(lama, nilai) {
  const out = {};
  if (nilai.isi !== undefined && nilai.isi !== lama?.isi) out.isi = nilai.isi;
  if (nilai.kategori !== undefined && nilai.kategori !== lama?.kategori) out.kategori = nilai.kategori;
  if (nilai.aktif !== undefined && !!nilai.aktif !== lama?.aktif) out.aktif = !!nilai.aktif;
  return Object.keys(out).length ? out : null;
}

/** Jumlah per kategori (untuk pil penyaring). */
export function hitungKategori(items) {
  const out = Object.fromEntries(KATEGORI_INGATAN.map((k) => [k.kunci, 0]));
  (items || []).forEach((x) => { if (x.kategori in out) out[x.kategori] += 1; });
  return out;
}

/** Periksa isian dialog → {ok, nilai: {isi, kategori}} atau {ok: false, galat} (kalimat ramah). */
export function periksaIngatan({ isi, kategori } = {}, maksIsi = BATAS_ISI_INGATAN) {
  const t = teks(isi).replace(/\s+/g, ' ').trim();
  if (t.length < MIN_ISI_INGATAN) return { ok: false, galat: `Tulis isi ingatan, minimal ${MIN_ISI_INGATAN} huruf.` };
  if (t.length > maksIsi) {
    return { ok: false, galat: `Isi ingatan paling banyak ${maksIsi} huruf (sekarang ${t.length}).` };
  }
  if (!KUNCI_KATEGORI.has(kategori)) return { ok: false, galat: 'Pilih kategori ingatan.' };
  return { ok: true, nilai: { isi: t, kategori } };
}

// ─── Chip "Diingat: …" di chat (A3) ──────────────────────────────────────────
const AKSI_INGATAN = {
  disimpan: 'disimpan', simpan: 'disimpan', diingat: 'disimpan', dibuat: 'disimpan', baru: 'disimpan',
  diperbarui: 'diperbarui', perbarui: 'diperbarui', diubah: 'diperbarui',
  dihapus: 'dihapus', hapus: 'dihapus', dilupakan: 'dihapus', lupakan: 'dihapus',
};

/** Peristiwa SSE `ingatan` ATAU blok tersimpan {jenis: "ingatan"} → blok layar; null bila kosong. */
export function blokIngatan(d) {
  const o = obj(d);
  if (!o) return null;
  const dalam = obj(o.ingatan);
  const src = dalam ? { ...dalam, aksi: o.aksi ?? dalam.aksi } : o;
  const isi = teks(src.isi).trim();
  const id = src.id ? String(src.id) : null;
  if (!isi && !id) return null;
  return {
    jenis: 'ingatan',
    id,
    isi,
    kategori: src.kategori ? String(src.kategori) : null,
    aksi: AKSI_INGATAN[teks(src.aksi || 'disimpan').toLowerCase()] || 'disimpan',
  };
}

/** Kalimat chip: "Diingat: …" / "Diperbarui: …" / "Dilupakan: …". */
export function teksChipIngatan(b) {
  const awal = b?.aksi === 'dihapus' ? 'Dilupakan' : (b?.aksi === 'diperbarui' ? 'Diperbarui' : 'Diingat');
  return `${awal}: ${b?.isi || 'satu ingatan'}`;
}

// ─── Jenis percakapan di riwayat (A4) ────────────────────────────────────────
export const JENIS_SESI = { briefing: 'Briefing', laporan_mingguan: 'Laporan mingguan' };

export function jenisSesi(s) {
  const j = teks(s?.jenis ?? s?.tipe).toLowerCase();
  return Object.prototype.hasOwnProperty.call(JENIS_SESI, j) ? j : null;
}
export const labelJenisSesi = (s) => JENIS_SESI[jenisSesi(s)] || null;

// ─── Tautan langsung ke satu percakapan (A5) ─────────────────────────────────
/**
 * Id sesi dari parameter navigasi (notifikasi/onNavigate): `sesi` > `sesi_id`; `link_id` > `record_id` hanya bila
 * parameter itu dibuat untuk Asisten AI (`tujuan_modul` = "asisten-ai").
 */
export function sesiDariParams(params) {
  const p = obj(params);
  if (!p) return null;
  const untukSaya = p.tujuan_modul === 'asisten-ai';
  const id = teks(p.sesi ?? p.sesi_id ?? (untukSaya ? (p.link_id ?? p.record_id) : '')).trim();
  return POLA_ID.test(id) ? id : null;
}

/** Id sesi dari alamat halaman `?…module=asisten-ai&sesi=<id>` (modul lain di alamat = bukan untuk layar ini). */
export function sesiDariAlamat(search) {
  let q;
  try { q = new URLSearchParams(teks(search)); } catch { return null; }
  const m = q.get('module');
  if (m && m !== 'asisten-ai') return null;
  const id = teks(q.get('sesi')).trim();
  return POLA_ID.test(id) ? id : null;
}

/** Alamat yang sama tanpa `sesi` (supaya muat ulang halaman tidak membuka tautan lama lagi). */
export function alamatTanpaSesi(pathname, search, hash) {
  let q;
  try { q = new URLSearchParams(teks(search)); } catch { return `${teks(pathname)}${teks(hash)}`; }
  q.delete('sesi');
  const s = q.toString();
  return `${teks(pathname)}${s ? `?${s}` : ''}${teks(hash)}`;
}

/** Alamat tautan langsung ke satu percakapan (dipakai notifikasi). */
export const tautanSesi = (id) => `/?portal=management&module=asisten-ai&sesi=${encodeURIComponent(id)}`;

// ─── Pengaturan Asisten AI proaktif (A6) ─────────────────────────────────────
export const PROAKTIF_BAWAAN = {
  asisten_ingatan_aktif: true,
  asisten_briefing_aktif: true,
  asisten_briefing_jam: '07:00',
  asisten_briefing_penerima: [],
  asisten_peringatan_aktif: true,
  asisten_peringatan_jam: '07:00',
  asisten_laporan_mingguan_aktif: true,
  asisten_laporan_mingguan_jam: '07:30',
};
export const KUNCI_PROAKTIF = Object.keys(PROAKTIF_BAWAAN);
/** Penerima briefing/laporan mingguan paling banyak 20 pengguna aktif (validasi backend proaktif). */
export const BATAS_PENERIMA = 20;
const KUNCI_SAKLAR = KUNCI_PROAKTIF.filter((k) => k.endsWith('_aktif'));

/** Tiga jadwal proaktif (urutan tampil) — `jenis` = segmen jalur `/proaktif/{jenis}/jalankan-sekarang` (A7). */
export const JADWAL_PROAKTIF = [
  {
    jenis: 'briefing', judul: 'Briefing pagi', kunciAktif: 'asisten_briefing_aktif', kunciJam: 'asisten_briefing_jam',
    keterangan: 'Setiap hari: omzet kemarin dan bulan ini terhadap target, kas, piutang jatuh tempo, stok, PO produksi terlambat, dan persetujuan menunggu.',
    adaSesi: true,
  },
  {
    jenis: 'peringatan', judul: 'Peringatan harian', kunciAktif: 'asisten_peringatan_aktif', kunciJam: 'asisten_peringatan_jam',
    keterangan: 'Pemeriksaan aturan tanpa AI: omzet tertinggal target, stok di bawah titik pesan ulang, PO produksi lewat tenggat, piutang jatuh tempo.',
    adaSesi: false,
  },
  {
    jenis: 'laporan_mingguan', judul: 'Laporan mingguan', kunciAktif: 'asisten_laporan_mingguan_aktif',
    kunciJam: 'asisten_laporan_mingguan_jam',
    keterangan: 'Setiap Senin: laporan PDF dan Excel minggu sebelumnya (Senin–Minggu) untuk penerima briefing.',
    adaSesi: true,
  },
];

/** "7", "7.00", "0700", "07:00" → "07:00"; jam tidak sah → null. */
export function normalJam(raw) {
  const s = teks(raw).trim().replace(/[.,]/g, ':');
  let j;
  let m;
  let r;
  if ((r = /^(\d{1,2}):(\d{2})$/.exec(s)) || (r = /^(\d{2})(\d{2})$/.exec(s))) {
    [, j, m] = r;
  } else if (/^\d{1,2}$/.test(s)) {
    j = s;
    m = '00';
  } else {
    return null;
  }
  const jj = Number(j);
  const mm = Number(m);
  if (jj > 23 || mm > 59) return null;
  return `${String(jj).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

const daftarId = (v) => (Array.isArray(v) ? [...new Set(v.map((x) => teks(obj(x) ? x.id : x).trim()).filter(Boolean))] : []);

/** Nilai pengaturan dari GET → isian formulir (bawaan bila server belum mengirim kunci). */
export function bacaPengaturanProaktif(d) {
  const x = obj(d) || {};
  const out = {};
  KUNCI_SAKLAR.forEach((k) => { out[k] = typeof x[k] === 'boolean' ? x[k] : PROAKTIF_BAWAAN[k]; });
  JADWAL_PROAKTIF.forEach(({ kunciJam }) => { out[kunciJam] = normalJam(x[kunciJam]) || PROAKTIF_BAWAAN[kunciJam]; });
  out.asisten_briefing_penerima = daftarId(x.asisten_briefing_penerima);
  return out;
}

/** Isian formulir → {ok, nilai (untuk badan PUT), galat: {kunci: kalimat}, pesan} — jam wajib JJ:MM. */
export function susunPengaturanProaktif(form) {
  const f = obj(form) || {};
  const nilai = {};
  const galat = {};
  KUNCI_SAKLAR.forEach((k) => { nilai[k] = f[k] === undefined ? PROAKTIF_BAWAAN[k] : !!f[k]; });
  JADWAL_PROAKTIF.forEach(({ kunciJam, judul }) => {
    const v = normalJam(f[kunciJam]);
    if (v) nilai[kunciJam] = v;
    else galat[kunciJam] = `Jam ${judul.toLowerCase()} harus berformat JJ:MM (00:00–23:59), mis. 07:00.`;
  });
  nilai.asisten_briefing_penerima = daftarId(f.asisten_briefing_penerima);
  if (nilai.asisten_briefing_penerima.length > BATAS_PENERIMA) {
    galat.asisten_briefing_penerima = `Penerima briefing paling banyak ${BATAS_PENERIMA} orang.`;
  }
  const pesan = Object.values(galat)[0] || '';
  return { ok: !pesan, nilai, galat, pesan };
}

/** Apakah isian proaktif berbeda dengan yang tersimpan di server (untuk peringatan "belum disimpan"). */
export function proaktifBerubah(form, tersimpan) {
  const a = susunPengaturanProaktif(form).nilai;
  const b = bacaPengaturanProaktif(tersimpan);
  return KUNCI_PROAKTIF.some((k) => (Array.isArray(a[k])
    ? [...a[k]].sort().join('|') !== [...(b[k] || [])].sort().join('|')
    : teks(a[k]) !== teks(b[k])));
}

/** Hanya owner/superadmin yang boleh "Jalankan sekarang" (D2). */
export const bolehJalankanProaktif = (role) => ['owner', 'superadmin'].includes(teks(role).toLowerCase());

// ─── Hasil "Jalankan sekarang" (A7) ──────────────────────────────────────────
const ALASAN_LEWAT = {
  kunci_kosong: 'kunci API AI belum diisi',
  ai_nonaktif: 'AI sedang dimatikan',
  anggaran_habis: 'anggaran AI sudah habis',
  nonaktif: 'jadwal ini sedang dimatikan',
  dimatikan: 'jadwal ini sedang dimatikan',
  sudah_ada: 'sudah dibuat hari ini',
  sudah_jalan: 'sudah dibuat hari ini',
  sudah_dijalankan: 'sudah dibuat hari ini',
  tanpa_penerima: 'belum ada penerima',
};
const LABEL_KONDISI = {
  omzet: 'Omzet tertinggal target', stok: 'Stok di bawah titik pesan ulang', po: 'PO produksi lewat tenggat',
  piutang: 'Piutang jatuh tempo', laris_habis: 'Model laris akan habis',
  merchandiser_senin: 'Ringkasan Merchandiser mingguan',
};
const LABEL_PEMERIKSA = {
  omzet: 'omzet', stok: 'stok', po_piutang: 'PO produksi dan piutang', merchandiser: 'merchandiser',
};

const sesiDari = (h) => {
  const o = obj(h);
  if (!o) return '';
  const id = teks(o.sesi_id ?? obj(o.sesi)?.id ?? o.session_id ?? (jenisSesi(o) ? o.id : '')).trim();
  return POLA_ID.test(id) ? id : '';
};

/**
 * Jawaban jalankan-sekarang → {sesiId, jumlahSesi, terkirim, dilewati, alasan, pesan}. Bila ada beberapa sesi
 * (satu per penerima) dipilih milik pengguna yang menekan tombol.
 */
export function bacaHasilJalankan(d, userId) {
  const x = obj(d) || {};
  const daftar = [x.hasil, x.items, x.sesi_dibuat].find(Array.isArray) || [];
  const punyaSesi = daftar.filter((h) => sesiDari(h));
  const milikSaya = userId ? punyaSesi.find((h) => teks(h.user_id ?? h.pengguna_id ?? obj(h.pengguna)?.id) === teks(userId)) : null;
  const sesiId = sesiDari(x) || sesiDari(milikSaya || punyaSesi[0]) || null;
  // peringatan (A7): `notifikasi` = jumlah notifikasi terkirim; `kondisi` = rincian per kondisi
  const kondisi = Array.isArray(x.kondisi) ? x.kondisi.filter((k) => obj(k)) : [];
  const nNotif = typeof x.notifikasi === 'number' ? x.notifikasi : (Array.isArray(x.notifikasi) ? x.notifikasi.length : null);
  const nKondisi = kondisi.length ? kondisi.filter((k) => k.dikirim === true).length : null;
  const n = Number(x.terkirim ?? x.jumlah_notifikasi ?? x.notifikasi_terkirim ?? nNotif ?? nKondisi);
  const dilewati = x.dilewati === true || x.skipped === true;
  return {
    sesiId,
    jumlahSesi: punyaSesi.length || (sesiId ? 1 : 0),
    terkirim: Number.isFinite(n) ? n : null,
    dilewati,
    berjalan: x.status === 'berjalan',
    alasan: teks(x.alasan),
    pesan: teks(x.pesan ?? x.ringkas).trim(),
    sudahHariIni: kondisi.filter((k) => k.alasan === 'sudah_dikirim_hari_ini').length,
    gagalKirim: kondisi.filter((k) => k.alasan === 'kirim_gagal').length,
    pemeriksaGagal: Object.entries(obj(x.pemeriksa) || {}).filter(([, v]) => v === 'gagal')
      .map(([k]) => LABEL_PEMERIKSA[k] || k.replace(/_/g, ' ')),
  };
}

/** Kalimat toast untuk hasil jalankan-sekarang. */
export function teksHasilJalankan(jadwal, h) {
  const judul = jadwal?.judul || 'Jadwal';
  if (h.dilewati) return h.pesan || `${judul} tidak dijalankan: ${ALASAN_LEWAT[h.alasan] || 'syaratnya belum terpenuhi'}.`;
  if (!jadwal?.adaSesi) {
    if (h.terkirim === null) return h.pesan || `${judul} sudah diperiksa.`;
    const bagian = [h.terkirim > 0
      ? `${judul} diperiksa: ${h.terkirim} notifikasi dikirim.`
      : `${judul} diperiksa: ${h.sudahHariIni ? 'tidak ada notifikasi baru.' : 'tidak ada yang perlu diperingatkan.'}`];
    if (h.sudahHariIni) bagian.push(`${h.sudahHariIni} kondisi sudah dikabarkan hari ini.`);
    if (h.gagalKirim) bagian.push(`${h.gagalKirim} notifikasi gagal dikirim.`);
    if (h.pemeriksaGagal?.length) bagian.push(`Pemeriksaan ${h.pemeriksaGagal.join(', ')} gagal.`);
    return bagian.join(' ');
  }
  if (h.pesan) return h.pesan;
  if (h.berjalan) return `${judul} sedang disusun; notifikasi dikirim setelah selesai.`;
  if (h.sesiId) return h.jumlahSesi > 1 ? `${judul} dibuat untuk ${h.jumlahSesi} penerima.` : `${judul} sudah dibuat.`;
  return `${judul} sedang disusun; notifikasi dikirim setelah selesai.`;
}

// ─── Jadwal berikutnya + riwayat jalan (A10, GET /proaktif) ───────────────────
const STATUS_JALAN = {
  berjalan: { label: 'Berjalan', tone: 'primary' },
  selesai: { label: 'Selesai', tone: 'success' },
  terkirim: { label: 'Terkirim', tone: 'success' },
  gagal: { label: 'Gagal', tone: 'danger' },
  dilewati: { label: 'Dilewati', tone: 'muted' },
  sudah: { label: 'Sudah jalan', tone: 'muted' },
};
const ALASAN_JALAN = {
  ...ALASAN_LEWAT,
  internal: 'galat sistem',
  aplikasi_tidak_tersedia: 'aplikasi belum siap',
  tanpa_akses: 'penerima tidak punya akses Asisten AI',
  cek_gagal: 'akses penerima gagal diperiksa',
  sudah_dikirim_hari_ini: 'sudah dikabarkan hari ini',
  kirim_gagal: 'notifikasi gagal dikirim',
  terhenti: 'dihentikan',
};

/** Satu baris riwayat jalan → bentuk layar (tanpa kode program: alasan tak dikenal = "alasan lain"). */
export function bacaRiwayatProaktif(r) {
  const o = obj(r) || {};
  const jadwal = JADWAL_PROAKTIF.find((j) => j.jenis === o.jenis);
  const st = STATUS_JALAN[o.status] || { label: 'Tidak dikenal', tone: 'default' };
  const sesi = teks(o.sesi_id).trim();
  const jumlah = o.jumlah === null || o.jumlah === undefined ? NaN : Number(o.jumlah);
  return {
    id: teks(o.id) || `${o.jenis}-${o.dibuat}`,
    jenis: teks(o.jenis),
    judul: jadwal?.judul || 'Jadwal',
    rincian: LABEL_KONDISI[o.kondisi] || null,
    waktu: o.diperbarui || o.dibuat || null,
    userId: teks(o.user_id) || null,
    sesiId: POLA_ID.test(sesi) ? sesi : null,
    pemicu: o.pemicu === 'manual' ? 'Manual' : 'Terjadwal',
    status: teks(o.status),
    statusLabel: st.label,
    tone: st.tone,
    alasan: o.alasan ? (ALASAN_JALAN[o.alasan] || 'alasan lain') : '',
    jumlah: Number.isFinite(jumlah) ? jumlah : null,
  };
}

/** GET /proaktif → {jadwal: {<jenis>: {aktif, jam, berikutnya} | null}, aiAktif, riwayat: [...]}. */
export function bacaRingkasanProaktif(d) {
  const x = obj(d) || {};
  const jadwal = {};
  JADWAL_PROAKTIF.forEach(({ jenis }) => {
    const j = obj(obj(x.jadwal)?.[jenis]);
    jadwal[jenis] = j ? { aktif: j.aktif !== false, jam: normalJam(j.jam), berikutnya: teks(j.berikutnya) || null } : null;
  });
  return {
    jadwal,
    aiAktif: x.ai_aktif !== false,
    riwayat: (Array.isArray(x.riwayat) ? x.riwayat : []).filter((r) => obj(r)).map(bacaRiwayatProaktif),
  };
}

/** "Senin, 09 Nov 2026 07.30" (WIB) dari waktu ISO; '' bila kosong/tidak sah. */
export function teksWaktuJadwal(iso) {
  const t = Date.parse(teks(iso));
  if (!Number.isFinite(t)) return '';
  const d = new Date(t);
  const hari = d.toLocaleDateString('id-ID', { timeZone: 'Asia/Jakarta', weekday: 'long' });
  const tgl = d.toLocaleDateString('id-ID', { timeZone: 'Asia/Jakarta', day: '2-digit', month: 'short', year: 'numeric' });
  const jam = d.toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', hour12: false });
  return `${hari}, ${tgl} ${jam}`;
}

// ─── Pemilih penerima (A9) ───────────────────────────────────────────────────
const PERAN = { owner: 'Owner', superadmin: 'Super admin', admin: 'Admin', manager: 'Manajer' };
export function labelPeran(role) {
  const r = teks(role).trim().toLowerCase();
  if (!r) return '';
  if (PERAN[r]) return PERAN[r];
  const t = r.replace(/[_-]+/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** Daftar pengguna (array atau {items|users|data}) → [{id, nama, peran}] urut nama. */
export function bacaDaftarPengguna(d) {
  const o = obj(d);
  const rows = Array.isArray(d) ? d : ([o?.items, o?.users, o?.data].find(Array.isArray) || []);
  return rows.filter((u) => obj(u) && u.id)
    .map((u) => ({ id: String(u.id), nama: teks(u.name ?? u.nama ?? u.email).trim() || 'Tanpa nama', peran: labelPeran(u.role) }))
    .sort((a, b) => a.nama.localeCompare(b.nama, 'id'));
}

/** Status Asisten AI: Ingatan AI menyala? (A8; tidak dikirim = dianggap menyala). */
export const ingatanAktifDariStatus = (st) => obj(st)?.ingatan_aktif !== false;
