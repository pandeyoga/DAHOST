/**
 * Asisten AI — Portal Management (Tahap A, keputusan owner 7 Nov 2026; menggantikan "AI Business Intelligence").
 *
 * Chat analis data internal: jawaban mengalir (SSE), langkah analisis yang bisa dibuka, grafik, tabel, sumber
 * data/web, dan unduhan laporan PDF/Excel. Data selalu mengikuti hak akses pengguna yang bertanya (backend
 * memanggil endpoint aplikasi dengan token pengguna). Tahap B (8 Nov 2026): AI boleh MENYIAPKAN perubahan data
 * berisiko rendah sebagai kartu konfirmasi (KartuTindakan); data baru berubah setelah pengguna menekan "Setujui".
 * Keputusan dikirim ke `POST /tindakan/{id}/putuskan` (aliran SSE) dan lanjutan jawabannya ditambahkan ke utas
 * seperti jawaban biasa (bisa dihentikan). "Tindakan AI" = halaman sendiri (`asisten-ai-tindakan`).
 * Tahap D (8 Nov 2026): "Ingatan AI" = halaman sendiri (`asisten-ai-ingatan`); chip "Diingat: …" di jawaban; lencana
 * Briefing/Laporan mingguan di riwayat; TAUTAN LANGSUNG `?portal=management&module=asisten-ai&sesi=<id>` (dan klik
 * notifikasi → `deepLinkParams`) membuka percakapan itu, juga saat halaman ini sudah terbuka.
 * Tahap E (9 Nov 2026): lampiran berkas di kotak tanya (Excel/CSV/PDF/gambar/teks, dikirim sebagai id `lampiran`) dan
 * kartu unduh berkas buatan AI (hasil hitung dengan kode) — lihat KomposerAsisten & BerkasAsisten.
 *
 * Tata letak (Standar UI/UX v2): cetakan PageLayout — kepala tipis, isi = jendela chat selebar layar; pilihan CV & periode di
 * kepala percakapan (bukan baris penyaring sendiri); sambutan + saran di tengah utas:
 *   [riwayat percakapan | kepala utas · utas pesan · kotak tanya]. Di HP riwayat pindah ke laci (Sheet).
 * Owner 9 Nov 2026: jendela chat mengisi area kerja sampai bawah layar; tombol "Layar penuh" di kepala utas menutupi
 * menu & kepala portal (diingat per peramban, Esc kembali).
 * Kontrak HTTP + SSE: lihat `asistenApi.js` (Kontrak B, `/api/asisten-ai`).
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Maximize2, Minimize2, PanelLeft, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { CV_ALL, CV_DEFAULT, CV_OPTIONS_FALLBACK, loadCvOptions, normalizeCv } from '@/lib/entitas';
import { thisMonthWIB } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { monthOptions } from '../finance/PeriodPicker';
import { KUNCI_SESI_AKTIF, asistenApi } from './asistenApi';
import { JENIS_ISI as KONTEN, dariRiwayat, judulDariTeks, pesanAsistenBaru, terapkanPeristiwa } from './peristiwaSse';
import KomposerAsisten from './KomposerAsisten';
import { KODE_GALAT_AKUN, PLACEHOLDER_BELUM_SIAP, StatusBelumSiap } from './StatusAsisten';
import RiwayatPercakapan from './RiwayatPercakapan';
import {
  kartuMenunggu, kedaluwarsakanMenunggu, terapkanStatusTindakan, terapkanUbahanKeRencana, ubahKartu,
} from './tindakanAsisten';
import UtasPesan from './UtasPesan';
import { alamatTanpaSesi, sesiDariAlamat, sesiDariParams } from './adapterTahapCD';

// Tahap B: halaman "Tindakan AI" (TindakanAIModule) membuka percakapan asal lewat kunci yang sama.
const KUNCI_SESI_UMUM = KUNCI_SESI_AKTIF;
// Audit HR Tahap D (9 Nov 2026): ruang Asisten AI — umum (Portal Manajemen), sdm (Portal SDM › AI SDM),
// saya (Portal Saya › Tanya Asisten, data milik sendiri). Teks layar per ruang; riwayat & saran disaring server.
const TEKS_RUANG = {
  umum: { judul: 'Asisten AI', sub: 'Tanya data penjualan, keuangan, stok, dan produksi; dijawab dengan grafik, tabel, dan sumber.',
    sambut: 'Tanyakan omzet per toko, produk terlaris, piutang jatuh tempo, atau stok menipis. Jawaban mengikuti CV dan periode yang dipilih.',
    hp: 'Tanya soal penjualan, stok…', kotak: 'Tanya soal penjualan, keuangan, stok, atau produksi…' },
  sdm: { judul: 'Asisten AI SDM', sub: 'Tanya absensi, cuti, lembur, shift, dan penggajian; koreksi dan draf shift lewat kartu persetujuan.',
    sambut: 'Tanyakan siapa yang terlambat atau lupa absen pulang, cek gaji sebelum finalisasi, atau minta draf shift minggu depan. Perubahan data selalu lewat kartu yang Anda setujui.',
    hp: 'Tanya soal absensi, shift…', kotak: 'Tanya soal absensi, cuti, lembur, shift, atau penggajian…' },
  saya: { judul: 'Tanya asisten', sub: 'Tanya absen, cuti, slip gaji, dan shift Anda sendiri.',
    sambut: 'Tanyakan sisa cuti, rekap absen, rincian slip gaji, atau shift Anda minggu depan. Asisten hanya membaca data milik Anda.',
    hp: 'Tanya soal absen, cuti, gaji…', kotak: 'Tanya soal absen, cuti, slip gaji, atau shift Anda…' },
};
const CATATAN_TINDAKAN_MATI = 'Tindakan AI sedang dimatikan admin; AI hanya menjawab.';
const CATATAN_ADA_MENUNGGU = 'Ada usulan perubahan yang menunggu keputusan Anda. Pertanyaan baru membuat usulan itu kedaluwarsa.';
const KUNCI_CV = 'asisten_ai_cv';
const MODEL_BAWAAN = 'Claude Opus 5.5';
// 4 analisis lama "AI Business Intelligence" jadi saran (audit AI §4) — dipakai bila server belum memberi saran.
const SARAN_CADANGAN = ['Ringkasan hari ini', 'Omzet bulan ini per toko', 'Prakiraan omzet bulan depan',
  'Cek kejanggalan transaksi', 'Rekomendasi produksi'];

const baca = (k) => { try { return window.sessionStorage.getItem(k); } catch { return null; } };
const tulis = (k, v) => { try { if (v) window.sessionStorage.setItem(k, v); else window.sessionStorage.removeItem(k); } catch { /* diblokir */ } };
const bacaCv = () => { try { return normalizeCv(window.localStorage.getItem(KUNCI_CV), CV_DEFAULT); } catch { return CV_DEFAULT; } };
const tulisCv = (v) => { try { window.localStorage.setItem(KUNCI_CV, v); } catch { /* diblokir */ } };
let urut = 0;
const kunciBaru = (p) => `${p}-${Date.now().toString(36)}-${(urut += 1)}`;

// ── Tahap D: tautan langsung ke satu percakapan (notifikasi briefing / laporan mingguan) ──────────────────────
// App menyimpan `deepLinkParams` terakhir sampai navigasi berikutnya; tanpa catatan ini, membuka Asisten AI lagi
// dari menu samping akan membuka percakapan notifikasi lama. Setiap objek parameter hanya dipakai sekali
// (klik notifikasi berikutnya = objek baru). Alamat `?sesi=` dibersihkan setelah dipakai.
const tautanTerpakai = new WeakSet();
const paramsBaru = (p) => (p && typeof p === 'object' && !tautanTerpakai.has(p) ? p : null);
function sesiTautanAwal(params) {
  const dariParams = sesiDariParams(paramsBaru(params));
  if (dariParams) return dariParams;
  try { return sesiDariAlamat(window.location.search); } catch { return null; }
}
function pakaiTautan(params) {
  if (params && typeof params === 'object') tautanTerpakai.add(params);
  try {
    const { pathname, search, hash } = window.location;
    if (sesiDariAlamat(search)) window.history.replaceState(window.history.state, '', alamatTanpaSesi(pathname, search, hash));
  } catch { /* alamat tidak bisa diubah: tidak apa-apa */ }
}

/** Label CV untuk Asisten AI: Gabungan tanpa "(lihat saja)" — seluruh Tahap A memang hanya membaca. */
const labelCv = (o) => (o.code === CV_ALL ? 'Gabungan' : o.label);

/** Akhir aliran jawaban: selesai bila ada isi, terhenti bila dihentikan, selain itu galat "terputus". */
function akhiriJawaban(p, aborted) {
  if (p.keadaan !== 'mengalir') return p;
  if (aborted) return { ...p, keadaan: 'terhenti', statusTeks: '' };
  return p.blok.some((b) => KONTEN.has(b.jenis))
    ? { ...p, keadaan: 'selesai', statusTeks: '' }
    : { ...p, keadaan: 'galat', statusTeks: '', galat: { kode: 'terputus', pesan: 'Jawaban terputus sebelum selesai. Coba lagi.' } };
}

/** Layar sempit (HP): subjudul & saran disembunyikan supaya utas pesan mendapat ruang. */
function useSempit() {
  const q = '(max-width: 639px)';
  const [sempit, setSempit] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(q).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    if (!mq) return undefined;
    const on = () => setSempit(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return sempit;
}

/**
 * Tinggi jendela chat = SELURUH sisa tinggi area kerja sampai bawah layar (owner 9 Nov 2026: "kotak chat terlalu
 * kecil, ingin full"). Ruang bawah cetakan G12 (pb-24, dulu untuk tombol chat mengambang — sekarang di menu samping)
 * tidak dipakai di halaman ini: jarak bawah = jarak atas cetakan, kelebihannya ditarik dengan margin negatif supaya
 * area kerja tidak ikut bergulir. Hasil: { tinggi, tarik } (px).
 */
function useTinggiPenuh(ref, min = 440) {
  const [ukuran, setUkuran] = useState({ tinggi: null, tarik: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const main = el.closest('main');
    const hitung = () => {
      const r = el.getBoundingClientRect();
      if (!main) { setUkuran({ tinggi: Math.max(min, Math.floor(window.innerHeight - r.top - 16)), tarik: 0 }); return; }
      const wrap = main.firstElementChild;
      const gaya = wrap ? getComputedStyle(wrap) : null;
      const pb = gaya ? parseFloat(gaya.paddingBottom) || 0 : 0;
      const jarak = gaya ? Math.min(pb, parseFloat(gaya.paddingTop) || 0) : 16;
      const atas = r.top - main.getBoundingClientRect().top + main.scrollTop;
      setUkuran({ tinggi: Math.max(min, Math.floor(main.clientHeight - atas - jarak)), tarik: Math.max(0, pb - jarak) });
    };
    hitung();
    window.addEventListener('resize', hitung);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(hitung) : null;
    if (ro) { if (main) ro.observe(main); if (el.parentElement) ro.observe(el.parentElement); }
    return () => { window.removeEventListener('resize', hitung); if (ro) ro.disconnect(); };
  }, [ref, min]);
  return ukuran;
}

/** Pilihan "Layar penuh" (menutupi menu & kepala portal) diingat per peramban; Esc mengembalikan. */
const KUNCI_LAYAR_PENUH = 'asisten-ai-layar-penuh';
function useLayarPenuh() {
  const [penuh, setPenuh] = useState(() => {
    try { return window.localStorage.getItem(KUNCI_LAYAR_PENUH) === '1'; } catch { return false; }
  });
  useEffect(() => {
    try { window.localStorage.setItem(KUNCI_LAYAR_PENUH, penuh ? '1' : '0'); } catch { /* penyimpanan diblokir */ }
    if (!penuh) return undefined;
    const onKey = (e) => {
      // Esc milik dialog/laci yang sedang terbuka didahulukan.
      if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('[role="dialog"][data-state="open"]')) return;
      setPenuh(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [penuh]);
  return [penuh, setPenuh];
}

export default function AsistenAIModule({ user, onNavigate, deepLinkParams, ruang }) {
  const peran = user?.role;
  const teksRuang = TEKS_RUANG[ruang] || TEKS_RUANG.umum;
  const KUNCI_SESI = ruang && ruang !== 'umum' ? `${KUNCI_SESI_UMUM}:${ruang}` : KUNCI_SESI_UMUM;
  const [status, setStatus] = useState({ memuat: true, data: null, galat: null });
  const [saran, setSaran] = useState([]);
  const [sesi, setSesi] = useState([]);
  const [memuatSesi, setMemuatSesi] = useState(true);
  const [galatSesi, setGalatSesi] = useState(null);
  const [cari, setCari] = useState('');
  const [aktifId, setAktifId] = useState(() => sesiTautanAwal(deepLinkParams) || baca(KUNCI_SESI));
  const [pesan, setPesan] = useState([]);
  const [memuatPesan, setMemuatPesan] = useState(false);
  const [mengalir, setMengalir] = useState(false);
  const [laci, setLaci] = useState(false);
  const [cvOpsi, setCvOpsi] = useState(CV_OPTIONS_FALLBACK);
  const [cv, setCvState] = useState(bacaCv);
  const [periode, setPeriode] = useState(() => thisMonthWIB());

  const aktifRef = useRef(aktifId);
  const tautanRef = useRef(sesiTautanAwal(deepLinkParams)); // id sesi yang dibuka lewat tautan (pesan 404 khusus)
  const abortRef = useRef(null);
  const mengalirRef = useRef(false);
  const komposerRef = useRef(null);
  const wadahRef = useRef(null);
  const { tinggi, tarik } = useTinggiPenuh(wadahRef);
  const sempit = useSempit();
  const [penuh, setPenuh] = useLayarPenuh();

  const periodeOpsi = useMemo(() => monthOptions(13), []);
  const siap = status.data?.siap === true;
  const sesiAktif = sesi.find((s) => s.id === aktifId) || null;

  // ── muat awal ──────────────────────────────────────────────────────────────
  const muatStatus = useCallback(async () => {
    setStatus((s) => ({ ...s, memuat: true, galat: null }));
    try {
      const d = await asistenApi.status();
      setStatus({ memuat: false, data: d || {}, galat: null });
    } catch (e) {
      setStatus({ memuat: false, data: null, galat: e?.message || 'Server tidak menjawab.' });
    }
  }, []);

  const muatDaftar = useCallback(async (diam = false) => {
    if (!diam) setMemuatSesi(true);
    try {
      const rows = await asistenApi.listSessions(ruang);
      setSesi(rows);
      setGalatSesi(null);
    } catch (e) {
      if (!diam) setGalatSesi(e?.message || 'Coba muat ulang halaman.');
    } finally {
      if (!diam) setMemuatSesi(false);
    }
  }, [ruang]);

  const bukaSesi = useCallback(async (id) => {
    setMemuatPesan(true);
    setPesan([]);
    try {
      const d = await asistenApi.getSession(id);
      if (aktifRef.current !== id) return;
      setPesan((Array.isArray(d?.pesan) ? d.pesan : []).map((p) => ({ ...dariRiwayat(p), kunci: p.id || kunciBaru('r') })));
    } catch (e) {
      if (aktifRef.current !== id) return;
      if (e?.status === 404) {
        if (tautanRef.current === id) toast.error('Percakapan dari tautan tidak ditemukan atau bukan milik Anda.');
        aktifRef.current = null;
        setAktifId(null);
        tulis(KUNCI_SESI, null);
        setSesi((rows) => rows.filter((s) => s.id !== id));
      } else {
        toast.error(e?.message || 'Percakapan gagal dibuka.');
      }
    } finally {
      if (aktifRef.current === id || aktifRef.current === null) setMemuatPesan(false);
    }
  }, [KUNCI_SESI]);

  useEffect(() => {
    muatStatus();
    muatDaftar();
    asistenApi.saran(peran, ruang)
      .then((rows) => setSaran(rows.map((r) => (typeof r === 'string' ? r : r?.teks)).filter(Boolean)))
      .catch(() => setSaran(SARAN_CADANGAN));
    loadCvOptions().then((m) => { if (m) setCvOpsi(m); });
    if (aktifRef.current) bukaSesi(aktifRef.current);
    return () => { abortRef.current?.abort(); };
  }, [muatStatus, muatDaftar, bukaSesi, peran, ruang]);

  // CV tersimpan yang tidak diizinkan → CV pertama yang diizinkan
  useEffect(() => {
    if (cvOpsi.length && !cvOpsi.some((o) => o.code === cv)) setCvState(cvOpsi[0].code);
  }, [cvOpsi, cv]);

  const gantiCv = (v) => { const c = normalizeCv(v); setCvState(c); tulisCv(c); };

  // ── percakapan ─────────────────────────────────────────────────────────────
  const hentikan = useCallback(() => { abortRef.current?.abort(); }, []);

  const pilih = useCallback((id) => {
    setLaci(false);
    if (id === aktifRef.current) return;
    abortRef.current?.abort();
    aktifRef.current = id;
    setAktifId(id);
    tulis(KUNCI_SESI, id);
    bukaSesi(id);
  }, [bukaSesi, KUNCI_SESI]);

  const baru = useCallback(() => {
    abortRef.current?.abort();
    aktifRef.current = null;
    setAktifId(null);
    tulis(KUNCI_SESI, null);
    setPesan([]);
    setMemuatPesan(false);
    setLaci(false);
    requestAnimationFrame(() => komposerRef.current?.fokus());
  }, [KUNCI_SESI]);

  const kirim = useCallback(async (teks, { lampiran } = {}) => {
    if (mengalirRef.current || !siap) return;
    mengalirRef.current = true;
    setMengalir(true);
    const kA = kunciBaru('a');
    // Tahap E: lampiran yang sudah diunggah dari kotak tanya ({id, nama, jenis, ukuran_kb}); server hanya menerima id.
    const lamp = Array.isArray(lampiran) ? lampiran.filter((l) => l?.id) : [];
    const pengguna = { kunci: kunciBaru('u'), peran: 'user', teks, ...(lamp.length ? { lampiran: lamp } : {}) };
    // Kartu yang masih menunggu menjadi kedaluwarsa begitu ada pertanyaan baru (Kontrak D; server melakukan hal yang sama).
    setPesan((prev) => [...kedaluwarsakanMenunggu(prev), pengguna, { ...pesanAsistenBaru(kA), kunci: kA }]);
    const ubah = (fn) => setPesan((prev) => prev.map((p) => (p.kunci === kA ? fn(p) : p)));
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // Asisten AI per pengguna (10 Nov 2026): akun dimatikan / batas pertanyaan tercapai → muat ulang status supaya
    // kotak tanya ikut terkunci dengan penjelasannya.
    let segarkanStatus = false;
    try {
      let sid = aktifRef.current;
      if (!sid) {
        const s = await asistenApi.createSession(judulDariTeks(teks), ruang);
        sid = s?.id;
        if (!sid) throw new Error('Percakapan baru gagal dibuat.');
        if (ctrl.signal.aborted) { ubah((p) => ({ ...p, keadaan: 'terhenti' })); return; }
        aktifRef.current = sid;
        setAktifId(sid);
        tulis(KUNCI_SESI, sid);
        const kini = new Date().toISOString();
        setSesi((rows) => [{ judul: judulDariTeks(teks), created_at: kini, updated_at: kini, jumlah_pesan: 0, ada_tindakan_menunggu: false, ...s },
          ...rows.filter((r) => r.id !== sid)]);
      }
      const hasil = await asistenApi.kirimPesan(sid, { teks, cv, periode, lampiran: lamp.map((l) => l.id) }, {
        signal: ctrl.signal,
        onEvent: ({ event, data }) => {
          if (event === 'galat' && KODE_GALAT_AKUN.includes(data?.kode)) segarkanStatus = true;
          if (aktifRef.current !== sid) return;
          // keadaan kartu bisa berubah untuk kartu di jawaban sebelumnya → seluruh utas
          if (event === 'tindakan_status') setPesan((prev) => terapkanStatusTindakan(prev, data));
          else ubah((p) => terapkanPeristiwa(p, event, data));
        },
      });
      ubah((p) => akhiriJawaban(p, hasil.aborted));
    } catch (e) {
      if (e?.status === 403) segarkanStatus = true;
      ubah((p) => ({ ...p, keadaan: 'galat', statusTeks: '', galat: { kode: e?.status || 'galat', pesan: e?.message || 'Asisten AI gagal menjawab.' } }));
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
      mengalirRef.current = false;
      setMengalir(false);
      muatDaftar(true);
      if (segarkanStatus) muatStatus();
    }
  }, [siap, cv, periode, muatDaftar, muatStatus, KUNCI_SESI, ruang]);

  /**
   * Muat ulang isi percakapan tanpa kerangka memuat (keadaan & rencana kartu dari server = sumber kebenaran).
   * `ubahanKartu` ({id: ubahan}) memasang lagi catatan "Diubah sebelum disetujui" di kartu yang disegarkan.
   */
  const segarkan = useCallback(async (id, ubahanKartu = null) => {
    if (!id) return;
    try {
      const d = await asistenApi.getSession(id);
      if (aktifRef.current !== id || mengalirRef.current) return;
      let utas = (Array.isArray(d?.pesan) ? d.pesan : []).map((p) => ({ ...dariRiwayat(p), kunci: p.id || kunciBaru('r') }));
      Object.entries(ubahanKartu || {}).forEach(([aid, ub]) => {
        utas = ubahKartu(utas, aid, (b) => ({ ...b, rencana: terapkanUbahanKeRencana(b.rencana, ub) }));
      });
      setPesan(utas);
    } catch { /* tampilan sekarang dibiarkan */ }
  }, []);

  /**
   * Putuskan kartu tindakan (Kontrak E `POST /tindakan/{id}/putuskan`, SSE). `tindakan_status` mengubah kartunya
   * di mana pun di utas; lanjutan jawaban (`mulai` … `selesai`) menjadi pesan asisten BARU di ujung utas — hanya
   * bila semua tindakan giliran itu sudah diputuskan (bila belum, aliran berhenti setelah status).
   * Tombol Hentikan memutus aliran seperti jawaban biasa. Mengembalikan `{ ok }` ke kartu.
   */
  const putuskan = useCallback(async (id, { keputusan, ubahan, alasan, konfirmasi } = {}) => {
    if (!id || mengalirRef.current) return { ok: false };
    const sid = aktifRef.current;
    mengalirRef.current = true;
    setMengalir(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let kA = null;
    let akhir = null;
    let ubahanTerpasang = false;
    let segar = false;
    let ok = true;
    const ubahLanjutan = (fn) => { const k = kA; setPesan((prev) => prev.map((p) => (p.kunci === k ? fn(p) : p))); };
    try {
      const hasil = await asistenApi.putuskan(id, { keputusan, ubahan, alasan, konfirmasi, cv }, {
        signal: ctrl.signal,
        onEvent: ({ event, data }) => {
          if (aktifRef.current !== sid) return;
          if (event === 'tindakan_status') {
            const pasang = data?.id === id && ubahan && !ubahanTerpasang && data.keadaan !== 'dibatalkan';
            if (data?.id === id) akhir = data.keadaan;
            if (pasang) ubahanTerpasang = true;
            setPesan((prev) => {
              const utas = terapkanStatusTindakan(prev, data);
              return pasang ? ubahKartu(utas, id, (b) => ({ ...b, rencana: terapkanUbahanKeRencana(b.rencana, ubahan) })) : utas;
            });
            return;
          }
          if (!kA) {
            const k = kunciBaru('a');
            kA = k;
            setPesan((prev) => [...prev, { ...pesanAsistenBaru(k), kunci: k }]);
          }
          ubahLanjutan((p) => terapkanPeristiwa(p, event, data));
        },
      });
      if (kA) ubahLanjutan((p) => akhiriJawaban(p, hasil.aborted));
      // aliran putus sebelum hasil akhir kartu terlihat → ambil keadaan sebenarnya dari server. Setelah disetujui
      // DENGAN ubahan, inti menjalankan `siapkan` lagi → tabel perubahan terbaru juga diambil dari server.
      segar = !akhir || akhir === 'disetujui' || ubahanTerpasang;
    } catch (e) {
      ok = false;
      if (kA) ubahLanjutan((p) => ({ ...p, keadaan: 'galat', statusTeks: '', galat: { kode: e?.status || 'galat', pesan: e?.message || 'Asisten AI gagal menjawab.' } }));
      else toast.error(e?.message || 'Keputusan gagal dikirim. Coba lagi.');
      // 409 = sudah diputuskan/kedaluwarsa di tempat lain; 404 = bukan milik Anda → tampilkan keadaan server
      // (putus jaringan sebelum status: kartu tetap menunggu; bila ternyata sudah jalan, coba lagi → 409 → disegarkan)
      segar = e?.status === 409 || e?.status === 404;
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
      mengalirRef.current = false;
      setMengalir(false);
      muatDaftar(true);
    }
    if (segar && aktifRef.current === sid) segarkan(sid, ubahanTerpasang ? { [id]: ubahan } : null);
    return { ok };
  }, [cv, muatDaftar, segarkan]);

  // Tahap D: tautan langsung (alamat `?sesi=` atau `deepLinkParams` dari klik notifikasi). Saat halaman baru dipasang,
  // sesi tautan sudah jadi `aktifId` awal (dibuka efek muat awal) — di sini hanya ditandai terpakai. Saat halaman sudah
  // terbuka, parameter baru membuka percakapan itu (percakapan yang sama → isinya disegarkan).
  const awalRef = useRef(true);
  useEffect(() => {
    const pertama = awalRef.current;
    awalRef.current = false;
    const p = paramsBaru(deepLinkParams);
    let id = sesiDariParams(p);
    if (!id && pertama) { try { id = sesiDariAlamat(window.location.search); } catch { id = null; } }
    if (!id) { if (p) tautanTerpakai.add(p); return; }
    pakaiTautan(p);
    tautanRef.current = id;
    tulis(KUNCI_SESI, id);
    if (pertama) return;
    setLaci(false);
    muatDaftar(true);
    if (id === aktifRef.current) { if (!mengalirRef.current) segarkan(id); return; }
    pilih(id);
  }, [deepLinkParams, pilih, segarkan, muatDaftar, KUNCI_SESI]);

  // "Coba lagi" = kirim ulang pertanyaan sebelum jawaban yang gagal, sebagai giliran baru (riwayat server append-only).
  // Lampirannya tidak dikirim ulang: berkas itu sudah tercatat pada pertanyaan sebelumnya di percakapan yang sama.
  const pesanRef = useRef(pesan);
  pesanRef.current = pesan;
  const cobaLagi = useCallback((pesanGagal) => {
    const daftar = pesanRef.current;
    const i = daftar.findIndex((p) => p.kunci === pesanGagal.kunci);
    const tanya = daftar.slice(0, Math.max(0, i)).reverse().find((p) => p.peran === 'user');
    if (tanya?.teks) kirim(tanya.teks);
  }, [kirim]);

  const ubahJudul = async () => {
    if (!sesiAktif) return;
    const judul = await confirmDialog({
      title: 'Ubah judul percakapan',
      confirmLabel: 'Simpan',
      input: { label: 'Judul', value: sesiAktif.judul || '', minLength: 1, placeholder: 'Mis. Omzet November per toko' },
    });
    if (!judul || judul === sesiAktif.judul) return;
    try {
      await asistenApi.renameSession(sesiAktif.id, judul.slice(0, 120));
      setSesi((rows) => rows.map((s) => (s.id === sesiAktif.id ? { ...s, judul: judul.slice(0, 120) } : s)));
      toast.success('Judul percakapan diubah.');
    } catch (e) {
      toast.error(e?.message || 'Judul gagal diubah.');
    }
  };

  const hapus = async () => {
    if (!sesiAktif) return;
    const ok = await confirmDialog({
      title: 'Hapus percakapan ini?',
      body: `"${sesiAktif.judul || 'Percakapan tanpa judul'}" dihapus dari riwayat Anda.`,
      confirmLabel: 'Hapus',
      danger: true,
    });
    if (!ok) return;
    try {
      await asistenApi.deleteSession(sesiAktif.id);
      setSesi((rows) => rows.filter((s) => s.id !== sesiAktif.id));
      baru();
      toast.success('Percakapan dihapus.');
    } catch (e) {
      toast.error(e?.message || 'Percakapan gagal dihapus.');
    }
  };

  // ── tampilan ───────────────────────────────────────────────────────────────
  const model = status.data?.model || MODEL_BAWAAN;
  const cvTeks = labelCv(cvOpsi.find((o) => o.code === cv) || CV_OPTIONS_FALLBACK[0]);
  const periodeTeks = periodeOpsi.find((o) => o.value === periode)?.label || periode;
  const judulUtas = sesiAktif?.judul || (aktifId ? 'Percakapan' : 'Percakapan baru');
  const tindakanAktif = status.data?.tindakan_aktif !== false;
  const adaMenunggu = useMemo(() => kartuMenunggu(pesan).length > 0, [pesan]);
  const catatanKomposer = !tindakanAktif ? CATATAN_TINDAKAN_MATI : (adaMenunggu ? CATATAN_ADA_MENUNGGU : undefined);

  // "Tindakan AI" (Tahap B) dan "Ingatan AI" (Tahap D) = halaman sendiri.
  const gantiTampilan = useCallback((t) => {
    setLaci(false);
    const tujuan = { tindakan: 'asisten-ai-tindakan', ingatan: 'asisten-ai-ingatan' }[t];
    if (tujuan && onNavigate) onNavigate(tujuan);
  }, [onNavigate]);

  const riwayat = (
    <RiwayatPercakapan sesi={sesi} memuat={memuatSesi} galat={galatSesi} aktifId={aktifId} cari={cari} onCari={setCari}
      onPilih={pilih} onBaru={baru} tampilan="chat" onTampilan={!ruang || ruang === 'umum' ? gantiTampilan : undefined} />
  );

  // Sambutan di TENGAH utas: judul + saran sebagai tombol (dulu: ruang kosong besar + saran di bawah).
  const sambutan = siap ? (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-4 py-6 text-center" data-testid="asisten-sambutan">
      <span className="grid h-10 w-10 place-items-center rounded-full bg-[hsl(var(--primary)/0.12)] text-primary" aria-hidden="true">
        <Sparkles className="h-5 w-5" />
      </span>
      <div className="max-w-xl space-y-1">
        <p className="text-lg font-semibold text-foreground">Mau tanya apa hari ini?</p>
        <p className="text-sm text-muted-foreground">{teksRuang.sambut}</p>
      </div>
      {saran.length > 0 && (
        <div className="grid w-full max-w-2xl gap-2 sm:grid-cols-2" data-testid="asisten-saran">
          {saran.slice(0, 6).map((s) => (
            <Button key={s} variant="outline" className="h-auto min-h-9 justify-start whitespace-normal py-2 text-left font-normal"
              disabled={mengalir} onClick={() => (komposerRef.current?.kirim ? komposerRef.current.kirim(s) : kirim(s))}
              data-testid="asisten-saran-item">
              <Sparkles className="text-primary" />{s}
            </Button>
          ))}
        </div>
      )}
    </div>
  ) : (
    <div className="flex h-full items-center justify-center">
      <StatusBelumSiap status={status} peran={peran} onNavigate={onNavigate} onCobaLagi={muatStatus} />
    </div>
  );

  // CV & periode ada di kepala percakapan (dulu satu baris penyaring sendiri di atas jendela chat).
  const pilihan = (
    <div className="flex w-full items-center gap-2 sm:w-auto">
      {/* Portal Saya: data milik sendiri tidak dipisah per CV → pilihan CV tidak ditampilkan */}
      {ruang !== 'saya' && (
        <SmartNativeSelect value={cv} onChange={(e) => gantiCv(e.target.value)} searchable={false}
          className="h-9 w-full sm:w-44" aria-label="CV yang dianalisis" title="CV yang dianalisis" data-testid="asisten-cv">
          {cvOpsi.map((o) => <option key={o.code} value={o.code}>{labelCv(o)}</option>)}
        </SmartNativeSelect>
      )}
      <SmartNativeSelect value={periode} onChange={(e) => setPeriode(e.target.value)} searchable={false}
        className="h-9 w-full sm:w-40" aria-label="Periode bawaan" title="Periode bawaan jawaban" data-testid="asisten-periode">
        {periodeOpsi.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </SmartNativeSelect>
    </div>
  );

  return (
    <PageLayout
      testId="asisten-ai-page"
      title={teksRuang.judul}
      subtitle={sempit ? undefined : teksRuang.sub}
    >
      <div ref={wadahRef}
        className={penuh ? 'fixed inset-0 z-50 !mt-0 bg-background p-2 sm:p-3' : 'min-h-[440px]'}
        style={penuh ? undefined : (tinggi ? { height: tinggi, marginBottom: tarik ? -tarik : undefined } : { height: 'calc(100dvh - 12rem)' })}
        data-layar-penuh={penuh ? '1' : '0'} data-testid="asisten-wadah">
        <GlassCard className="flex h-full overflow-hidden p-0" data-testid="asisten-jendela">
          <aside className="hidden w-64 shrink-0 flex-col border-r border-[var(--glass-border)] md:flex" aria-label="Riwayat percakapan">
            {riwayat}
          </aside>
          <section className="flex min-w-0 flex-1 flex-col" aria-label="Percakapan">
            <div className="flex flex-wrap items-center gap-2 border-b border-[var(--glass-border)] px-3 py-2 sm:px-4">
              <Button variant="outline" size="icon" className="shrink-0 md:hidden" onClick={() => setLaci(true)}
                title="Riwayat percakapan" aria-label="Riwayat percakapan" data-testid="asisten-buka-riwayat">
                <PanelLeft />
              </Button>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground" data-testid="asisten-judul">{judulUtas}</p>
                <p className="truncate text-xs text-muted-foreground" data-testid="asisten-konteks"
                  title={`${model} · ${cvTeks} · ${periodeTeks}`}>{model}</p>
              </div>
              {sesiAktif && (
                <>
                  <Button variant="outline" size="icon" className="shrink-0" onClick={ubahJudul} disabled={mengalir}
                    title="Ubah judul" aria-label="Ubah judul" data-testid="asisten-ubah-judul">
                    <Pencil />
                  </Button>
                  <Button variant="outline" size="icon" className="shrink-0" onClick={hapus} disabled={mengalir}
                    title="Hapus percakapan" aria-label="Hapus percakapan" data-testid="asisten-hapus-sesi">
                    <Trash2 />
                  </Button>
                </>
              )}
              <Button variant="outline" size="icon" className="shrink-0 md:hidden" onClick={baru}
                title="Percakapan baru" aria-label="Percakapan baru" data-testid="asisten-baru-hp">
                <Plus />
              </Button>
              <Button variant="outline" size="icon" className="shrink-0" onClick={() => setPenuh((p) => !p)}
                title={penuh ? 'Keluar dari layar penuh (Esc)' : 'Layar penuh'} aria-label={penuh ? 'Keluar dari layar penuh' : 'Layar penuh'}
                aria-pressed={penuh} data-testid="asisten-layar-penuh">
                {penuh ? <Minimize2 /> : <Maximize2 />}
              </Button>
              <div className="order-last w-full sm:order-none sm:w-auto">{pilihan}</div>
            </div>
            <UtasPesan pesan={pesan} memuat={memuatPesan} kosong={sambutan} onCobaLagi={cobaLagi}
              onPutuskan={putuskan} onNavigate={onNavigate} mengalir={mengalir} tindakanAktif={tindakanAktif} />
            <KomposerAsisten ref={komposerRef} saran={pesan.length ? saran.slice(0, 4) : []} saranRingkas={pesan.length > 0}
              onKirim={kirim} onHentikan={hentikan} mengalir={mengalir} nonaktif={!siap} catatan={catatanKomposer} lampiranAktif
              placeholder={!siap ? (PLACEHOLDER_BELUM_SIAP[status.data?.alasan] || 'Asisten AI belum siap')
                : (sempit ? teksRuang.hp : teksRuang.kotak)} />
          </section>
        </GlassCard>
      </div>

      <Sheet open={laci} onOpenChange={setLaci}>
        <SheetContent side="left" className="flex w-[86vw] max-w-[320px] flex-col gap-0 p-0" data-testid="asisten-laci">
          <div className="flex h-12 shrink-0 items-center border-b border-[var(--glass-border)] pl-4 pr-12">
            <SheetTitle className="text-base">Riwayat percakapan</SheetTitle>
          </div>
          <div className="min-h-0 flex-1">{riwayat}</div>
        </SheetContent>
      </Sheet>
    </PageLayout>
  );
}
