/**
 * KomposerAsisten — kotak tanya Asisten AI.
 *   - tombol saran menurut peran (`GET /api/asisten-ai/saran`), satu baris yang bisa digeser; di HP disembunyikan
 *     setelah pertanyaan pertama (`saranRingkas`) supaya utas pesan mendapat ruang;
 *   - kotak teks yang memanjang sendiri: Enter = kirim, Shift+Enter = baris baru (tidak mengirim saat IME menyusun huruf);
 *   - tombol Kirim berganti jadi Hentikan selama jawaban mengalir (memutus fetch);
 *   - `sibuk` = menunggu jawaban tanpa streaming (Asisten ERP): kirim ditahan, kotak tetap bisa diketik;
 *   - huruf 16 px di HP supaya iOS tidak memperbesar layar saat kotak disentuh.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { SendHorizontal, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

const TINGGI_MAKS = 200;
const CATATAN_BAWAAN = 'AI bisa keliru, periksa angka penting. Setiap perubahan data selalu menunggu persetujuan Anda.';

const KomposerAsisten = forwardRef(function KomposerAsisten({
  saran = [], onKirim, onHentikan, mengalir = false, nonaktif = false, placeholder, catatan = CATATAN_BAWAAN, testId = 'asisten',
  sibuk = false, labelInput = 'Pertanyaan untuk Asisten AI', saranRingkas = false,
}, ref) {
  const [teks, setTeks] = useState('');
  const area = useRef(null);

  // kotak memanjang sendiri mengikuti isi (maks 200 px, lalu menggulir)
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, TINGGI_MAKS)}px`;
  }, [teks]);

  useImperativeHandle(ref, () => ({
    fokus: () => area.current?.focus(),
    isi: (t) => { setTeks(t); requestAnimationFrame(() => area.current?.focus()); },
  }), []);

  const kirim = (t = teks) => {
    const isi = String(t || '').trim();
    if (!isi || mengalir || nonaktif || sibuk) return;
    onKirim?.(isi);
    setTeks('');
  };

  const onKeyDown = (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent?.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    kirim();
  };

  return (
    <div className="space-y-2 border-t border-[var(--glass-border)] px-3 pb-2 pt-3 sm:px-4" data-testid={`${testId}-komposer`}>
      {saran.length > 0 && !nonaktif && (
        <div className={cn('-mx-1 gap-2 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none]', saranRingkas ? 'hidden sm:flex' : 'flex')}
          data-testid={`${testId}-saran`}>
          {saran.slice(0, 6).map((s) => (
            <Button key={s} variant="outline" size="sm" className="shrink-0 rounded-full font-normal"
              disabled={mengalir || sibuk} onClick={() => kirim(s)} data-testid={`${testId}-saran-item`}>
              {s}
            </Button>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border border-input px-2 py-1.5 focus-within:ring-1 focus-within:ring-ring">
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
          <Button size="icon" onClick={() => kirim()} disabled={nonaktif || sibuk || !teks.trim()} title="Kirim (Enter)" aria-label="Kirim"
            className="shrink-0" data-testid={`${testId}-kirim`}>
            <SendHorizontal className="h-4 w-4" />
          </Button>
        )}
      </div>
      {catatan && <p className="text-center text-[11px] leading-snug text-muted-foreground" data-testid={`${testId}-catatan`}>{catatan}</p>}
    </div>
  );
});

export default KomposerAsisten;
