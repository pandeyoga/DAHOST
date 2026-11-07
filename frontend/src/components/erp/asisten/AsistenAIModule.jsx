/**
 * Asisten AI — Portal Management (Tahap A, keputusan owner 7 Nov 2026; menggantikan "AI Business Intelligence").
 *
 * Chat analis data internal: jawaban mengalir (SSE), langkah analisis yang bisa dibuka, grafik, tabel, sumber
 * data/web, dan unduhan laporan PDF/Excel. Data selalu mengikuti hak akses pengguna yang bertanya (backend
 * memanggil endpoint aplikasi dengan token pengguna). Tahap A hanya MEMBACA; tindakan tulis (kartu
 * konfirmasi) datang di Tahap B — "Tindakan AI" dan "Ingatan AI" sudah ada tempatnya.
 *
 * Tata letak (PANDUAN_UI G1): cetakan PageLayout — judul, pilihan CV & periode di `filters`, isi = jendela chat:
 *   [riwayat percakapan | kepala utas · utas pesan · kotak tanya]. Di HP riwayat pindah ke laci (Sheet).
 * Kontrak HTTP + SSE: lihat `asistenApi.js` (Kontrak B, `/api/asisten-ai`).
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { PanelLeft, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { CV_ALL, CV_DEFAULT, CV_OPTIONS_FALLBACK, loadCvOptions, normalizeCv } from '@/lib/entitas';
import { thisMonthWIB } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { EmptyState } from '../moduleAtoms';
import { monthOptions } from '../finance/PeriodPicker';
import { asistenApi } from './asistenApi';
import { dariRiwayat, judulDariTeks, pesanAsistenBaru, terapkanPeristiwa } from './peristiwaSse';
import KomposerAsisten from './KomposerAsisten';
import { PLACEHOLDER_BELUM_SIAP, StatusBelumSiap, TahapBerikut } from './StatusAsisten';
import RiwayatPercakapan from './RiwayatPercakapan';
import UtasPesan from './UtasPesan';

const KUNCI_SESI = 'asisten_ai_sesi_aktif';
const KUNCI_CV = 'asisten_ai_cv';
const MODEL_BAWAAN = 'Claude Opus 5.5';
// 4 analisis lama "AI Business Intelligence" jadi saran (audit AI §4) — dipakai bila server belum memberi saran.
const SARAN_CADANGAN = ['Ringkasan hari ini', 'Omzet bulan ini per toko', 'Prakiraan omzet bulan depan',
  'Cek kejanggalan transaksi', 'Rekomendasi produksi'];
const KONTEN = new Set(['teks', 'grafik', 'tabel', 'laporan']);

const baca = (k) => { try { return window.sessionStorage.getItem(k); } catch { return null; } };
const tulis = (k, v) => { try { if (v) window.sessionStorage.setItem(k, v); else window.sessionStorage.removeItem(k); } catch { /* diblokir */ } };
const bacaCv = () => { try { return normalizeCv(window.localStorage.getItem(KUNCI_CV), CV_DEFAULT); } catch { return CV_DEFAULT; } };
const tulisCv = (v) => { try { window.localStorage.setItem(KUNCI_CV, v); } catch { /* diblokir */ } };
let urut = 0;
const kunciBaru = (p) => `${p}-${Date.now().toString(36)}-${(urut += 1)}`;

/** Label CV untuk Asisten AI: Gabungan tanpa "(lihat saja)" — seluruh Tahap A memang hanya membaca. */
const labelCv = (o) => (o.code === CV_ALL ? 'Gabungan' : o.label);

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

/** Tinggi jendela chat = sisa tinggi area kerja (tanpa gulir ganda), menyisakan ruang bawah cetakan (G12). */
function useTinggiPenuh(ref, min = 440) {
  const [tinggi, setTinggi] = useState(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const main = el.closest('main');
    const hitung = () => {
      const r = el.getBoundingClientRect();
      if (!main) { setTinggi(Math.max(min, Math.floor(window.innerHeight - r.top - 16))); return; }
      const wrap = main.firstElementChild;
      const pb = wrap ? parseFloat(getComputedStyle(wrap).paddingBottom) || 0 : 16;
      const atas = r.top - main.getBoundingClientRect().top + main.scrollTop;
      setTinggi(Math.max(min, Math.floor(main.clientHeight - atas - pb)));
    };
    hitung();
    window.addEventListener('resize', hitung);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(hitung) : null;
    if (ro) { if (main) ro.observe(main); if (el.parentElement) ro.observe(el.parentElement); }
    return () => { window.removeEventListener('resize', hitung); if (ro) ro.disconnect(); };
  }, [ref, min]);
  return tinggi;
}

export default function AsistenAIModule({ user, onNavigate }) {
  const peran = user?.role;
  const [status, setStatus] = useState({ memuat: true, data: null, galat: null });
  const [saran, setSaran] = useState([]);
  const [sesi, setSesi] = useState([]);
  const [memuatSesi, setMemuatSesi] = useState(true);
  const [galatSesi, setGalatSesi] = useState(null);
  const [cari, setCari] = useState('');
  const [aktifId, setAktifId] = useState(() => baca(KUNCI_SESI));
  const [pesan, setPesan] = useState([]);
  const [memuatPesan, setMemuatPesan] = useState(false);
  const [mengalir, setMengalir] = useState(false);
  const [tampilan, setTampilan] = useState('chat');
  const [laci, setLaci] = useState(false);
  const [cvOpsi, setCvOpsi] = useState(CV_OPTIONS_FALLBACK);
  const [cv, setCvState] = useState(bacaCv);
  const [periode, setPeriode] = useState(() => thisMonthWIB());

  const aktifRef = useRef(aktifId);
  const abortRef = useRef(null);
  const mengalirRef = useRef(false);
  const komposerRef = useRef(null);
  const wadahRef = useRef(null);
  const tinggi = useTinggiPenuh(wadahRef);
  const sempit = useSempit();

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
      const rows = await asistenApi.listSessions();
      setSesi(rows);
      setGalatSesi(null);
    } catch (e) {
      if (!diam) setGalatSesi(e?.message || 'Coba muat ulang halaman.');
    } finally {
      if (!diam) setMemuatSesi(false);
    }
  }, []);

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
  }, []);

  useEffect(() => {
    muatStatus();
    muatDaftar();
    asistenApi.saran(peran)
      .then((rows) => setSaran(rows.map((r) => (typeof r === 'string' ? r : r?.teks)).filter(Boolean)))
      .catch(() => setSaran(SARAN_CADANGAN));
    loadCvOptions().then((m) => { if (m) setCvOpsi(m); });
    if (aktifRef.current) bukaSesi(aktifRef.current);
    return () => { abortRef.current?.abort(); };
  }, [muatStatus, muatDaftar, bukaSesi, peran]);

  // CV tersimpan yang tidak diizinkan → CV pertama yang diizinkan
  useEffect(() => {
    if (cvOpsi.length && !cvOpsi.some((o) => o.code === cv)) setCvState(cvOpsi[0].code);
  }, [cvOpsi, cv]);

  const gantiCv = (v) => { const c = normalizeCv(v); setCvState(c); tulisCv(c); };

  // ── percakapan ─────────────────────────────────────────────────────────────
  const hentikan = useCallback(() => { abortRef.current?.abort(); }, []);

  const pilih = useCallback((id) => {
    setLaci(false);
    setTampilan('chat');
    if (id === aktifRef.current) return;
    abortRef.current?.abort();
    aktifRef.current = id;
    setAktifId(id);
    tulis(KUNCI_SESI, id);
    bukaSesi(id);
  }, [bukaSesi]);

  const baru = useCallback(() => {
    abortRef.current?.abort();
    aktifRef.current = null;
    setAktifId(null);
    tulis(KUNCI_SESI, null);
    setPesan([]);
    setMemuatPesan(false);
    setTampilan('chat');
    setLaci(false);
    requestAnimationFrame(() => komposerRef.current?.fokus());
  }, []);

  const kirim = useCallback(async (teks) => {
    if (mengalirRef.current || !siap) return;
    setTampilan('chat');
    mengalirRef.current = true;
    setMengalir(true);
    const kA = kunciBaru('a');
    setPesan((prev) => [...prev, { kunci: kunciBaru('u'), peran: 'user', teks }, { ...pesanAsistenBaru(kA), kunci: kA }]);
    const ubah = (fn) => setPesan((prev) => prev.map((p) => (p.kunci === kA ? fn(p) : p)));
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      let sid = aktifRef.current;
      if (!sid) {
        const s = await asistenApi.createSession(judulDariTeks(teks));
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
      const hasil = await asistenApi.kirimPesan(sid, { teks, cv, periode }, {
        signal: ctrl.signal,
        onEvent: ({ event, data }) => ubah((p) => terapkanPeristiwa(p, event, data)),
      });
      ubah((p) => {
        if (p.keadaan !== 'mengalir') return p;
        if (hasil.aborted) return { ...p, keadaan: 'terhenti', statusTeks: '' };
        const adaIsi = p.blok.some((b) => KONTEN.has(b.jenis));
        return adaIsi
          ? { ...p, keadaan: 'selesai', statusTeks: '' }
          : { ...p, keadaan: 'galat', statusTeks: '', galat: { kode: 'terputus', pesan: 'Jawaban terputus sebelum selesai. Coba lagi.' } };
      });
    } catch (e) {
      ubah((p) => ({ ...p, keadaan: 'galat', statusTeks: '', galat: { kode: e?.status || 'galat', pesan: e?.message || 'Asisten AI gagal menjawab.' } }));
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
      mengalirRef.current = false;
      setMengalir(false);
      muatDaftar(true);
    }
  }, [siap, cv, periode, muatDaftar]);

  // "Coba lagi" = kirim ulang pertanyaan sebelum jawaban yang gagal, sebagai giliran baru (riwayat server append-only).
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
  const judulUtas = tampilan === 'tindakan' ? 'Tindakan AI'
    : tampilan === 'ingatan' ? 'Ingatan AI'
      : (sesiAktif?.judul || (aktifId ? 'Percakapan' : 'Percakapan baru'));

  const riwayat = (
    <RiwayatPercakapan sesi={sesi} memuat={memuatSesi} galat={galatSesi} aktifId={aktifId} cari={cari} onCari={setCari}
      onPilih={pilih} onBaru={baru} tampilan={tampilan} onTampilan={(t) => { setTampilan(t); setLaci(false); }} />
  );

  const sambutan = siap ? (
    <div className="flex h-full items-center justify-center">
      <EmptyState icon={Sparkles} testId="asisten-sambutan" title="Mau tanya apa hari ini?"
        description="Tanyakan omzet per toko, produk terlaris, piutang jatuh tempo, atau stok menipis. Jawaban mengikuti CV dan periode yang dipilih di atas." />
    </div>
  ) : (
    <div className="flex h-full items-center justify-center">
      <StatusBelumSiap status={status} peran={peran} onNavigate={onNavigate} onCobaLagi={muatStatus} />
    </div>
  );

  return (
    <PageLayout
      testId="asisten-ai-page"
      title="Asisten AI"
      subtitle={sempit ? undefined : 'Tanya data penjualan, keuangan, stok, dan produksi; dijawab dengan grafik, tabel, dan sumber.'}
      filters={(
        <>
          <div className="w-40 shrink-0 sm:w-48">
            <SmartNativeSelect value={cv} onChange={(e) => gantiCv(e.target.value)} searchable={false}
              className="h-9 w-full" aria-label="CV yang dianalisis" title="CV yang dianalisis" data-testid="asisten-cv">
              {cvOpsi.map((o) => <option key={o.code} value={o.code}>{labelCv(o)}</option>)}
            </SmartNativeSelect>
          </div>
          <div className="w-44 shrink-0">
            <SmartNativeSelect value={periode} onChange={(e) => setPeriode(e.target.value)} searchable={false}
              className="h-9 w-full" aria-label="Periode bawaan" title="Periode bawaan jawaban" data-testid="asisten-periode">
              {periodeOpsi.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </SmartNativeSelect>
          </div>
        </>
      )}
    >
      <div ref={wadahRef} className="min-h-[440px]" style={tinggi ? { height: tinggi } : { height: 'calc(100dvh - 15rem)' }}
        data-testid="asisten-wadah">
        <GlassCard className="flex h-full overflow-hidden" data-testid="asisten-jendela">
          <aside className="hidden w-72 shrink-0 flex-col border-r border-[var(--glass-border)] md:flex" aria-label="Riwayat percakapan">
            {riwayat}
          </aside>
          <section className="flex min-w-0 flex-1 flex-col" aria-label="Percakapan">
            <div className="flex min-h-[52px] items-center gap-2 border-b border-[var(--glass-border)] px-3 py-2 sm:px-4">
              <Button variant="outline" size="icon" className="shrink-0 md:hidden" onClick={() => setLaci(true)}
                title="Riwayat percakapan" aria-label="Riwayat percakapan" data-testid="asisten-buka-riwayat">
                <PanelLeft className="h-4 w-4" />
              </Button>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground" data-testid="asisten-judul">{judulUtas}</p>
                <p className="truncate text-xs text-muted-foreground" data-testid="asisten-konteks">{model} · {cvTeks} · {periodeTeks}</p>
              </div>
              {sesiAktif && tampilan === 'chat' && (
                <>
                  <Button variant="outline" size="icon" className="shrink-0" onClick={ubahJudul} disabled={mengalir}
                    title="Ubah judul" aria-label="Ubah judul" data-testid="asisten-ubah-judul">
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button variant="outline" size="icon" className="shrink-0" onClick={hapus} disabled={mengalir}
                    title="Hapus percakapan" aria-label="Hapus percakapan" data-testid="asisten-hapus-sesi">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </>
              )}
              <Button variant="outline" size="icon" className="shrink-0 md:hidden" onClick={baru}
                title="Percakapan baru" aria-label="Percakapan baru" data-testid="asisten-baru-hp">
                <Plus className="h-4 w-4" />
              </Button>
            </div>
            {tampilan === 'chat' ? (
              <>
                <UtasPesan pesan={pesan} memuat={memuatPesan} kosong={sambutan} onCobaLagi={cobaLagi} />
                <KomposerAsisten ref={komposerRef} saran={pesan.length ? saran.slice(0, 4) : saran} saranRingkas={pesan.length > 0}
                  onKirim={kirim} onHentikan={hentikan} mengalir={mengalir} nonaktif={!siap}
                  placeholder={!siap ? (PLACEHOLDER_BELUM_SIAP[status.data?.alasan] || 'Asisten AI belum siap')
                    : (sempit ? 'Tanya soal penjualan, stok…' : undefined)} />
              </>
            ) : (
              <TahapBerikut jenis={tampilan} onKembali={() => setTampilan('chat')} />
            )}
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
