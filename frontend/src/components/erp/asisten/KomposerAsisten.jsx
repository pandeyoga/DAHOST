/**
 * KomposerAsisten — kotak tanya Asisten AI.
 *   - tombol saran menurut peran (`GET /api/asisten-ai/saran`), satu baris yang bisa digeser; di HP disembunyikan
 *     setelah pertanyaan pertama (`saranRingkas`) supaya utas pesan mendapat ruang;
 *   - kotak teks yang memanjang sendiri: Enter = kirim, Shift+Enter = baris baru (tidak mengirim saat IME menyusun huruf);
 *   - tombol Kirim berganti jadi Hentikan selama jawaban mengalir (memutus fetch);
 *   - `sibuk` = menunggu jawaban tanpa streaming (Asisten ERP): kirim ditahan, kotak tetap bisa diketik;
 *   - huruf 16 px di HP supaya iOS tidak memperbesar layar saat kotak disentuh.
 *   - Tahap E (`lampiranAktif`, hanya Asisten AI): tombol klip / seret-dan-lepas → berkas diunggah satu per satu ke
 *     `POST /api/asisten-ai/lampiran` dan tampil sebagai chip (mengunggah · gagal · siap, tombol × menghapusnya di
 *     server). Batas 5 berkas & 20 MB per berkas dicek di sini dulu (toast). Kirim ditahan selama ada unggahan;
 *     pertanyaan tetap wajib diketik. `onKirim(teks, { lampiran: [{id, nama, jenis, ukuran_kb}] })`, lalu chip dikosongkan.
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Paperclip, SendHorizontal, Square } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { asistenApi } from './asistenApi';
import { ChipLampiran } from './BerkasAsisten';
import {
  ACCEPT_LAMPIRAN, MAKS_LAMPIRAN, MAKS_UKURAN_MB, jenisLampiran, normalLampiran, saringBerkas,
} from './lampiranAsisten';

const TINGGI_MAKS = 200;
const CATATAN_BAWAAN = 'AI bisa keliru, periksa angka penting. Setiap perubahan data selalu menunggu persetujuan Anda.';
const JUDUL_LAMPIR = `Lampirkan berkas (Excel, CSV, PDF, gambar, atau teks; paling banyak ${MAKS_LAMPIRAN} berkas, ${MAKS_UKURAN_MB} MB per berkas)`;
const PESAN_PENUH = `Paling banyak ${MAKS_LAMPIRAN} berkas untuk satu pertanyaan.`;
const PESAN_TUNGGU = 'Tunggu sampai berkas selesai diunggah.';

let urut = 0;
const kunciBaru = () => `lmp-${Date.now().toString(36)}-${(urut += 1)}`;
const adaBerkasDiseret = (e) => Array.from(e.dataTransfer?.types || []).includes('Files');

const KomposerAsisten = forwardRef(function KomposerAsisten({
  saran = [], onKirim, onHentikan, mengalir = false, nonaktif = false, placeholder, catatan = CATATAN_BAWAAN, testId = 'asisten',
  sibuk = false, labelInput = 'Pertanyaan untuk Asisten AI', saranRingkas = false, lampiranAktif = false,
}, ref) {
  const [teks, setTeks] = useState('');
  const [lampiran, setLampiran] = useState([]);
  const [seret, setSeret] = useState(false);
  const area = useRef(null);
  const pilihRef = useRef(null);
  // Cermin `lampiran` yang selalu terbaru (pilihan berkas beruntun sebelum render ulang; dibaca saat kirim/hapus).
  const lampiranRef = useRef([]);
  const antrianRef = useRef(Promise.resolve()); // unggahan berjalan satu per satu
  const kendaliRef = useRef(new Map()); // kunci chip → AbortController unggahan yang berjalan
  const dibuangRef = useRef(new Set()); // kunci chip yang dihapus sebelum/selama diunggah
  const hidupRef = useRef(true);

  const ubahLampiran = useCallback((fn) => {
    lampiranRef.current = fn(lampiranRef.current);
    setLampiran(lampiranRef.current);
  }, []);
  const ubahItem = useCallback((kunci, ubahan) => {
    ubahLampiran((prev) => prev.map((l) => (l.kunci === kunci ? { ...l, ...ubahan } : l)));
  }, [ubahLampiran]);

  // kotak memanjang sendiri mengikuti isi (maks 200 px, lalu menggulir)
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, TINGGI_MAKS)}px`;
  }, [teks]);

  // Keluar dari halaman: unggahan yang berjalan diputus, lampiran yang sudah diunggah tapi belum dikirim dihapus di server.
  useEffect(() => {
    hidupRef.current = true;
    const kendali = kendaliRef.current;
    return () => {
      hidupRef.current = false;
      kendali.forEach((c) => c.abort());
      lampiranRef.current.filter((l) => l.keadaan === 'siap' && l.id)
        .forEach((l) => { Promise.resolve().then(() => asistenApi.hapusLampiran(l.id)).catch(() => {}); });
    };
  }, []);

  const unggahSatu = useCallback(async (item) => {
    if (dibuangRef.current.has(item.kunci) || !hidupRef.current) return;
    const ctrl = new AbortController();
    kendaliRef.current.set(item.kunci, ctrl);
    try {
      const hasil = await asistenApi.unggahLampiran(item.file, {
        signal: ctrl.signal,
        onProgress: (persen) => { if (hidupRef.current && !dibuangRef.current.has(item.kunci)) ubahItem(item.kunci, { persen }); },
      });
      const [l] = normalLampiran([hasil]);
      if (!l) throw new Error('Jawaban server tidak lengkap.');
      if (dibuangRef.current.has(item.kunci) || !hidupRef.current) {
        asistenApi.hapusLampiran(l.id).catch(() => {});
        return;
      }
      ubahItem(item.kunci, {
        ...l, ukuran_kb: l.ukuran_kb ?? item.ukuran_kb, ringkas: typeof hasil?.ringkas === 'string' ? hasil.ringkas : '',
        keadaan: 'siap', persen: 100, file: null,
      });
    } catch (e) {
      if (e?.dibatalkan || dibuangRef.current.has(item.kunci) || !hidupRef.current) return;
      const pesan = e?.message || 'Berkas gagal diunggah.';
      ubahItem(item.kunci, { keadaan: 'gagal', galat: pesan, file: null });
      toast.error(`"${item.nama}" gagal diunggah. ${pesan}`);
    } finally {
      kendaliRef.current.delete(item.kunci);
    }
  }, [ubahItem]);

  const bisaLampir = lampiranAktif && !nonaktif;
  const jumlahTerpakai = () => lampiranRef.current.filter((l) => l.keadaan !== 'gagal').length;

  const tambahBerkas = useCallback((files) => {
    if (!bisaLampir) return;
    const { diterima, ditolak } = saringBerkas(files, lampiranRef.current.filter((l) => l.keadaan !== 'gagal').length);
    ditolak.forEach((t) => toast.error(t.pesan));
    if (!diterima.length) return;
    const baru = diterima.map((f) => ({
      kunci: kunciBaru(), file: f, nama: f.name, jenis: jenisLampiran(f.name), ukuran_kb: f.size / 1024,
      keadaan: 'mengunggah', persen: null,
    }));
    ubahLampiran((prev) => [...prev, ...baru]);
    baru.forEach((item) => {
      antrianRef.current = antrianRef.current.then(() => unggahSatu(item)).catch(() => {});
    });
  }, [bisaLampir, ubahLampiran, unggahSatu]);

  const hapusLampiran = useCallback((kunci) => {
    const item = lampiranRef.current.find((l) => l.kunci === kunci);
    if (!item) return;
    dibuangRef.current.add(kunci);
    kendaliRef.current.get(kunci)?.abort();
    ubahLampiran((prev) => prev.filter((l) => l.kunci !== kunci));
    if (item.keadaan === 'siap' && item.id) asistenApi.hapusLampiran(item.id).catch(() => { /* sisa di server dibersihkan server */ });
  }, [ubahLampiran]);

  const mengunggah = lampiran.some((l) => l.keadaan === 'mengunggah');

  const kirim = (t = teks) => {
    const isi = String(t || '').trim();
    if (!isi || mengalir || nonaktif || sibuk) return;
    if (lampiranRef.current.some((l) => l.keadaan === 'mengunggah')) { toast.info(PESAN_TUNGGU); return; }
    if (lampiranAktif) {
      const siap = lampiranRef.current.filter((l) => l.keadaan === 'siap' && l.id)
        .map(({ id, nama, jenis, ukuran_kb: kb }) => ({ id, nama, jenis, ukuran_kb: kb }));
      onKirim?.(isi, { lampiran: siap });
      ubahLampiran(() => []);
    } else {
      onKirim?.(isi);
    }
    setTeks('');
  };
  // Pegangan `kirim` untuk halaman (saran di tengah utas) selalu memakai keadaan terbaru (teks & lampiran).
  const kirimRef = useRef(kirim);
  kirimRef.current = kirim;

  useImperativeHandle(ref, () => ({
    fokus: () => area.current?.focus(),
    isi: (t) => { setTeks(t); requestAnimationFrame(() => area.current?.focus()); },
    kirim: (t) => kirimRef.current(t),
  }), []);

  const onKeyDown = (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent?.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    kirim();
  };

  const bukaPemilih = () => {
    if (!bisaLampir) return;
    if (jumlahTerpakai() >= MAKS_LAMPIRAN) { toast.error(PESAN_PENUH); return; }
    pilihRef.current?.click();
  };

  // seret-dan-lepas berkas ke kotak tanya
  const onDragOver = (e) => {
    if (!bisaLampir || !adaBerkasDiseret(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    if (!seret) setSeret(true);
  };
  const onDragLeave = (e) => {
    if (!seret || e.currentTarget.contains(e.relatedTarget)) return;
    setSeret(false);
  };
  const onDrop = (e) => {
    if (!bisaLampir || !adaBerkasDiseret(e)) return;
    e.preventDefault();
    setSeret(false);
    tambahBerkas(e.dataTransfer.files);
  };

  return (
    <div className="space-y-2 border-t border-[var(--glass-border)] px-3 pb-2 pt-3 sm:px-4" data-testid={`${testId}-komposer`}>
      {saran.length > 0 && !nonaktif && (
        <div className={cn('-mx-1 gap-2 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none]', saranRingkas ? 'hidden sm:flex' : 'flex')}
          data-testid={`${testId}-saran`}>
          {saran.slice(0, 6).map((s) => (
            <Button key={s} variant="outline" size="sm" className="shrink-0 rounded-full font-normal"
              disabled={mengalir || sibuk || mengunggah} onClick={() => kirim(s)} data-testid={`${testId}-saran-item`}>
              {s}
            </Button>
          ))}
        </div>
      )}
      <div
        className={cn('rounded-xl border border-input px-2 py-1.5 focus-within:ring-1 focus-within:ring-ring',
          seret && 'border-primary ring-1 ring-primary')}
        onDragEnter={lampiranAktif ? onDragOver : undefined}
        onDragOver={lampiranAktif ? onDragOver : undefined}
        onDragLeave={lampiranAktif ? onDragLeave : undefined}
        onDrop={lampiranAktif ? onDrop : undefined}
        data-seret={seret ? '1' : undefined}
        data-testid={`${testId}-kotak`}
      >
        {lampiranAktif && (seret || lampiran.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 px-1 pb-1.5 pt-0.5" data-testid={`${testId}-lampiran`}>
            {lampiran.map((l) => (
              <ChipLampiran key={l.kunci} nama={l.nama} jenis={l.jenis} ukuranKb={l.ukuran_kb} keadaan={l.keadaan}
                persen={l.persen} galat={l.galat} ringkas={l.ringkas} onHapus={() => hapusLampiran(l.kunci)}
                testId={`${testId}-lampiran-chip`} />
            ))}
            {seret && <span className="text-xs text-primary" data-testid={`${testId}-lepas`}>Lepaskan berkas di sini untuk melampirkan</span>}
          </div>
        )}
        <div className="flex items-end gap-2">
          {lampiranAktif && (
            <>
              <input ref={pilihRef} type="file" multiple accept={ACCEPT_LAMPIRAN} className="hidden" tabIndex={-1} aria-hidden="true"
                onChange={(e) => { tambahBerkas(e.target.files); e.target.value = ''; }} data-testid={`${testId}-berkas-input`} />
              <Button type="button" variant="outline" size="icon" onClick={bukaPemilih} disabled={nonaktif}
                title={JUDUL_LAMPIR} aria-label="Lampirkan berkas" className="shrink-0" data-testid={`${testId}-lampirkan`}>
                <Paperclip className="h-4 w-4" />
              </Button>
            </>
          )}
          <Textarea
            ref={area}
            rows={1}
            value={teks}
            onChange={(e) => setTeks(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder || 'Tanya soal penjualan, keuangan, stok, atau produksi…'}
            disabled={nonaktif}
            aria-label={labelInput}
            className="min-h-[36px] resize-none border-0 bg-transparent px-1 py-1.5 shadow-none focus-visible:ring-0"
            style={{ maxHeight: TINGGI_MAKS }}
            data-testid={`${testId}-input`}
          />
          {mengalir ? (
            <Button variant="outline" size="icon" onClick={onHentikan} title="Hentikan jawaban" aria-label="Hentikan jawaban"
              className="shrink-0" data-testid={`${testId}-hentikan`}>
              <Square className="h-3.5 w-3.5 fill-current" />
            </Button>
          ) : (
            <Button size="icon" onClick={() => kirim()} disabled={nonaktif || sibuk || mengunggah || !teks.trim()}
              title={mengunggah ? PESAN_TUNGGU : 'Kirim (Enter)'} aria-label="Kirim"
              className="shrink-0" data-testid={`${testId}-kirim`}>
              <SendHorizontal className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
      {catatan && <p className="text-center text-xs leading-snug text-muted-foreground" data-testid={`${testId}-catatan`}>{catatan}</p>}
    </div>
  );
});

export default KomposerAsisten;
