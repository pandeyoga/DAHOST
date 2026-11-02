/**
 * MoneyInput — input nominal uang dengan pemisah ribuan otomatis (keputusan owner No.45).
 * =============================================================================
 * Pengguna mengetik ANGKA SAJA; titik ribuan muncul sendiri ("1500000" → "1.500.000").
 *
 * Drop-in pengganti input angka uang:
 *   <Input type="number" value={v} onChange={(e) => set(e.target.value)} />
 *   <MoneyInput           value={v} onChange={(e) => set(e.target.value)} />
 *
 * Kontrak nilai:
 *   - `value` boleh number atau string angka POLOS ('1500000', '12.5', '').
 *   - `onChange` dipanggil gaya native: `e.target.value` = string angka POLOS bergaya JS
 *     ('1500000', '12.5', '' bila kosong) — handler lama yang memakai Number()/parseFloat()
 *     tetap benar tanpa diubah. `e.target.name` ikut bila `name` diberikan.
 *   - `onValueChange(number|null)` opsional bila lebih praktis menerima angka.
 *
 * Opsi:
 *   - decimals (default 0)    — jumlah desimal yang boleh diketik (koma). Rupiah = 0;
 *                               USD/harga per meter bisa 2. Titik yang baru diketik di
 *                               keyboard HP (tanpa koma) dibaca sebagai koma desimal.
 *   - allowNegative (false)   — izinkan minus (mis. penyesuaian).
 *   - prefix                  — teks di kiri kotak, mis. "Rp" / "$" (opsional).
 *   - glass                   — gaya kotak GlassInput (form bergaya glass), bukan gaya `Input`.
 *   - unstyled                — jangan pakai gaya bawaan apa pun (untuk <input> polos yang
 *                               sudah punya className sendiri).
 * Atribut lain (id, name, placeholder, disabled, required, className, data-testid,
 * onBlur, onKeyDown, autoFocus, …) diteruskan. `type`, `step`, `min`, `max` dari
 * input number lama diabaikan dengan aman (min/max tidak memblokir ketikan).
 */
import * as React from 'react';

import { cn } from '@/lib/utils';
import { GLASS_INPUT_CLASS } from '@/components/ui/glass';
import {
  moneyDisplay, moneyTyping, moneyCaret, moneyMeaningfulBefore, parseIDNumber,
} from '@/lib/format';

const BASE_CLASS =
  'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm';

const samePlain = (a, b) => {
  if ((a === '' || a === null || a === undefined) && (b === '' || b === null || b === undefined)) return true;
  return Number(a) === Number(b);
};

const MoneyInput = React.forwardRef(function MoneyInput(
  {
    value, onChange, onValueChange, decimals = 0, allowNegative = false, prefix,
    unstyled = false, glass = false, className, name,
    // atribut input number lama — sengaja dibuang
    type: _type, step: _step, min: _min, max: _max, // eslint-disable-line no-unused-vars
    ...rest
  },
  forwardedRef,
) {
  const opts = React.useMemo(() => ({ decimals, allowNegative }), [decimals, allowNegative]);
  const innerRef = React.useRef(null);
  const setRefs = React.useCallback((el) => {
    innerRef.current = el;
    if (typeof forwardedRef === 'function') forwardedRef(el);
    else if (forwardedRef) forwardedRef.current = el;
  }, [forwardedRef]);

  const [display, setDisplay] = React.useState(() => moneyDisplay(value, opts));
  const plainRef = React.useRef(moneyTyping(display, opts).plain);
  const caretRef = React.useRef(null);

  // Nilai diubah dari LUAR (reset form, isi otomatis) → tampilkan ulang. Selama nilainya
  // sama dengan yang sedang diketik, biarkan teks ketikan apa adanya ("12," / "12,50").
  React.useEffect(() => {
    if (!samePlain(value, plainRef.current)) {
      const next = moneyDisplay(value, opts);
      plainRef.current = moneyTyping(next, opts).plain;
      setDisplay(next);
    }
  }, [value, opts]);

  React.useLayoutEffect(() => {
    if (caretRef.current !== null && innerRef.current && document.activeElement === innerRef.current) {
      const pos = caretRef.current;
      innerRef.current.setSelectionRange(pos, pos);
    }
    caretRef.current = null;
  }, [display]);

  const commit = (rawText, caretPos) => {
    const meaningful = moneyMeaningfulBefore(rawText, caretPos);
    const { plain, display: nextDisplay } = moneyTyping(rawText, opts);
    caretRef.current = moneyCaret(nextDisplay, meaningful);
    setDisplay(nextDisplay);
    if (plain !== plainRef.current) {
      plainRef.current = plain;
      onChange?.({ target: { value: plain, name }, currentTarget: { value: plain, name } });
      if (onValueChange) {
        const n = plain === '' || plain === '-' ? null : Number(plain);
        onValueChange(Number.isFinite(n) ? n : null);
      }
    }
  };

  const handleChange = (e) => {
    let text = e.target.value;
    let caret = e.target.selectionStart ?? text.length;
    // Keyboard HP yang hanya punya titik: titik yang BARU diketik = koma desimal.
    if (decimals > 0 && e.nativeEvent?.data === '.' && !display.includes(',')) {
      const at = caret - 1;
      if (text[at] === '.') text = `${text.slice(0, at)},${text.slice(at + 1)}`;
    }
    commit(text, caret);
  };

  // Tempel "1.500.000" / "Rp 1.500.000" / "0.50" / "1500000" → dibaca dengan parser id-ID
  // yang sama dengan impor (parseIDNumber), lalu disisipkan sebagai teks tampilan.
  const handlePaste = (e) => {
    const pasted = e.clipboardData?.getData('text') ?? '';
    const n = parseIDNumber(pasted);
    if (n === null) return; // biarkan perilaku biasa (akan disaring)
    e.preventDefault();
    const el = e.currentTarget;
    const start = el.selectionStart ?? display.length;
    const end = el.selectionEnd ?? display.length;
    const insert = moneyDisplay(allowNegative ? n : Math.abs(n), opts);
    const text = display.slice(0, start) + insert + display.slice(end);
    commit(text, start + insert.length);
  };

  const input = (
    <input
      {...rest}
      ref={setRefs}
      name={name}
      type="text"
      inputMode={decimals > 0 ? 'decimal' : 'numeric'}
      autoComplete="off"
      value={display}
      onChange={handleChange}
      onPaste={handlePaste}
      className={unstyled ? className : cn(glass ? GLASS_INPUT_CLASS : BASE_CLASS, prefix && 'pl-9', 'tabular-nums', className)}
    />
  );

  if (!prefix) return input;
  return (
    <div className="relative w-full">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
        {prefix}
      </span>
      {input}
    </div>
  );
});

MoneyInput.displayName = 'MoneyInput';

export { MoneyInput };
export default MoneyInput;
