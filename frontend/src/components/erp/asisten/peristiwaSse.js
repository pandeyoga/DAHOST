/**
 * peristiwaSse — logika MURNI Asisten AI (tanpa jaringan/React): penyusun pesan dari peristiwa SSE Kontrak B,
 * pesan dari riwayat server, kelompok riwayat per tanggal WIB, dan judul percakapan baru. Diuji di
 * `__tests__/asisten.test.js`.
 */
import { parseServerTime, todayWIB, toWIBDate, addDaysISO } from '@/lib/waktu';
import { blokTindakan, terapkanStatusKeBlok } from './tindakanAsisten';
import { blokIngatan } from './adapterTahapCD';
import { blokBerkas, normalLampiran } from './lampiranAsisten';

/** Jenis blok yang dihitung sebagai ISI jawaban (bukan langkah/sumber). Kartu tindakan (Tahap B) dan berkas buatan AI
 * (Tahap E) termasuk. */
export const JENIS_ISI = new Set(['teks', 'grafik', 'tabel', 'laporan', 'tindakan', 'berkas']);

/** Kelompok riwayat: Hari ini / Kemarin / Lebih lama (tanggal WIB dari `updated_at`, cadangan `created_at`). */
export function kelompokkanSesi(sessions, now = new Date()) {
  const today = todayWIB(now);
  const kemarin = addDaysISO(today, -1);
  const groups = [
    { key: 'hari-ini', label: 'Hari ini', items: [] },
    { key: 'kemarin', label: 'Kemarin', items: [] },
    { key: 'lama', label: 'Lebih lama', items: [] },
  ];
  for (const s of sessions) {
    const d = toWIBDate(parseServerTime(s.updated_at || s.created_at));
    if (d === today) groups[0].items.push(s);
    else if (d === kemarin) groups[1].items.push(s);
    else groups[2].items.push(s);
  }
  return groups.filter((g) => g.items.length);
}

/** Judul percakapan baru dari pertanyaan pertama (≤ 60 huruf, satu baris). */
export function judulDariTeks(teks) {
  const t = String(teks || '').replace(/\s+/g, ' ').trim();
  return t.length > 60 ? `${t.slice(0, 57).trimEnd()}…` : t;
}

// ─── Penyusun pesan dari peristiwa SSE (Kontrak B) ───────────────────────────
// Bentuk pesan di layar = bentuk pesan tersimpan (`GET /sessions/{id}` → pesan[].blok) supaya jawaban yang sedang
// mengalir dan jawaban dari riwayat dirender oleh komponen yang SAMA.

export function pesanAsistenBaru(tempId) {
  return { id: tempId, peran: 'asisten', blok: [], keadaan: 'mengalir', statusTeks: '', galat: null, pemakaian: null };
}

/** Terapkan satu peristiwa SSE ke pesan asisten; mengembalikan pesan BARU (tidak mengubah yang lama). */
export function terapkanPeristiwa(pesan, event, data) {
  const d = data && typeof data === 'object' ? data : {};
  const blok = pesan.blok.slice();
  const last = blok[blok.length - 1];
  switch (event) {
    case 'mulai':
      return { ...pesan, id: d.pesan_id || pesan.id };
    case 'status':
      return { ...pesan, statusTeks: String(d.teks || '') };
    case 'pikir': {
      const tambah = String(d.teks ?? d.delta ?? '');
      const i = blok.findIndex((b) => b.jenis === 'pikir_ringkas');
      if (i >= 0) blok[i] = { ...blok[i], isi: `${blok[i].isi || ''}${tambah}` };
      else blok.push({ jenis: 'pikir_ringkas', isi: tambah });
      return { ...pesan, blok };
    }
    case 'teks': {
      const delta = String(d.delta ?? d.teks ?? '');
      if (!delta) return pesan;
      if (last && last.jenis === 'teks') blok[blok.length - 1] = { ...last, isi: `${last.isi || ''}${delta}` };
      else blok.push({ jenis: 'teks', isi: delta });
      return { ...pesan, blok };
    }
    case 'alat': {
      const i = blok.findIndex((b) => b.jenis === 'alat' && b.id && b.id === d.id);
      const step = { jenis: 'alat', id: d.id, nama: d.nama, label: d.label, keadaan: d.keadaan || 'mulai', pesan: d.pesan };
      if (i >= 0) blok[i] = { ...blok[i], ...step, label: d.label || blok[i].label };
      else blok.push(step);
      return { ...pesan, blok };
    }
    case 'grafik':
      blok.push({ jenis: 'grafik', id: d.id, spec: d.spec });
      return { ...pesan, blok };
    case 'tabel':
      blok.push({ jenis: 'tabel', ...d });
      return { ...pesan, blok };
    case 'sumber':
      blok.push({ jenis: 'sumber', item: Array.isArray(d.item) ? d.item : [] });
      return { ...pesan, blok };
    case 'laporan':
      blok.push({ jenis: 'laporan', ...d });
      return { ...pesan, blok };
    // Tahap E (Kontrak K3): berkas keluaran hitung-dengan-kode → kartu unduh. Id yang sama tidak digandakan.
    case 'berkas': {
      const b = blokBerkas(d);
      if (!b) return pesan;
      const i = blok.findIndex((x) => x.jenis === 'berkas' && x.id === b.id);
      if (i >= 0) blok[i] = b;
      else blok.push(b);
      return { ...pesan, blok };
    }
    // Tahap B (Kontrak E): kartu konfirmasi. `tindakan` = rencana baru (keadaan menunggu); `tindakan_status` =
    // keadaan kartu berubah. Kartu bisa ada di jawaban SEBELUMNYA → layar memakai `terapkanStatusTindakan`
    // untuk seluruh utas; di sini hanya blok milik pesan ini.
    case 'tindakan': {
      if (!d.id) return pesan;
      const i = blok.findIndex((b) => b.jenis === 'tindakan' && b.id === d.id);
      if (i >= 0) blok[i] = { ...blok[i], ...blokTindakan(d) };
      else blok.push(blokTindakan(d));
      return { ...pesan, blok };
    }
    case 'tindakan_status': {
      const baru = terapkanStatusKeBlok(pesan.blok, d);
      return baru === pesan.blok ? pesan : { ...pesan, blok: baru };
    }
    // Tahap D (D1): AI menyimpan/melupakan ingatan → chip "Diingat: …" / "Dilupakan: …" (bukan isi jawaban; bentuk
    // sama dengan blok tersimpan {jenis: "ingatan"}, lihat adapterTahapCD A3).
    case 'ingatan': {
      const b = blokIngatan(d);
      if (!b) return pesan;
      blok.push(b);
      return { ...pesan, blok };
    }
    case 'selesai':
      return { ...pesan, id: d.pesan_id || pesan.id, keadaan: 'selesai', statusTeks: '', pemakaian: d.pemakaian || null };
    case 'galat':
      return {
        ...pesan,
        keadaan: 'galat',
        statusTeks: '',
        galat: { kode: d.kode || 'galat', pesan: d.pesan || 'Asisten AI gagal menjawab. Coba lagi sebentar lagi.' },
      };
    default:
      return pesan;
  }
}

/** Pesan dari riwayat server → bentuk layar (keadaan selesai/terhenti). */
export function dariRiwayat(p) {
  const blok = Array.isArray(p?.blok) ? p.blok : [];
  // Backend menyimpan `status`: selesai | berjalan | terhenti | gagal (Kontrak B, simpan.py), Tahap B juga
  // `menunggu_konfirmasi` (jawaban berhenti di kartu tindakan) → pesannya selesai; kartunya membawa keadaan sendiri.
  const st = p?.keadaan || p?.status;
  const keadaan = st === 'terhenti' || p?.terhenti ? 'terhenti' : (st === 'galat' || st === 'gagal' ? 'galat' : 'selesai');
  return {
    id: p?.id,
    peran: p?.peran === 'user' ? 'user' : 'asisten',
    dibuat: p?.dibuat,
    blok,
    keadaan,
    statusTeks: '',
    galat: p?.galat || null,
    pemakaian: p?.pemakaian || null,
    teks: p?.peran === 'user' ? (p?.teks ?? blok.filter((b) => b.jenis === 'teks').map((b) => b.isi).join('\n')) : undefined,
    // Tahap D: permintaan yang ditulis sistem (briefing pagi / laporan mingguan otomatis), bukan oleh pengguna
    otomatis: p?.peran === 'user' && p?.otomatis === true ? true : undefined,
    // Tahap E (Kontrak K2): berkas yang dilampirkan pengguna pada pertanyaan ini
    lampiran: p?.peran === 'user' ? normalLampiran(p?.lampiran) : undefined,
  };
}
