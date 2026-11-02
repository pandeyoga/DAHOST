// Uji perilaku MoneyInput tanpa @testing-library/dom (tidak terpasang di proyek):
// render lewat react-dom/client + act, ketikan disimulasikan seperti browser
// (setter nilai native + event `input`).
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { MoneyInput } from '../money-input';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let host;
let root;
beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function Harness({ initial = '', decimals = 0, onSeen = () => {} }) {
  const [v, setV] = useState(initial);
  return (
    <>
      <MoneyInput
        aria-label="nominal"
        decimals={decimals}
        value={v}
        onChange={(e) => { setV(e.target.value); onSeen(e.target.value); }}
      />
      <output>{String(v)}</output>
      <button type="button" onClick={() => setV(0)}>reset</button>
    </>
  );
}

const box = () => host.querySelector('input');
const state = () => host.querySelector('output').textContent;
const setNative = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;

// Ketik satu karakter di ujung, seperti browser: nilai baru + event input dengan `data`.
function typeChar(ch) {
  const el = box();
  el.focus();
  const next = el.value + ch;
  setNative.call(el, next);
  el.setSelectionRange(next.length, next.length);
  const ev = new Event('input', { bubbles: true });
  Object.defineProperty(ev, 'data', { value: ch });
  act(() => { el.dispatchEvent(ev); });
}
const type = (text) => [...text].forEach(typeChar);

function setText(text) {
  const el = box();
  setNative.call(el, text);
  el.setSelectionRange(text.length, text.length);
  act(() => { el.dispatchEvent(new Event('input', { bubbles: true })); });
}

test('mengetik angka polos: tampil 1.500.000, state tetap polos', () => {
  act(() => root.render(<Harness />));
  type('1500000');
  expect(box().value).toBe('1.500.000');
  expect(state()).toBe('1500000');
});

test('handler lama parseFloat(e.target.value) tetap benar', () => {
  const seen = [];
  act(() => root.render(<Harness onSeen={(x) => seen.push(parseFloat(x) || 0)} />));
  type('25000');
  expect(seen[seen.length - 1]).toBe(25000);
});

test('nilai awal number ditampilkan berformat; reset dari luar ikut', () => {
  act(() => root.render(<Harness initial={2750000} />));
  expect(box().value).toBe('2.750.000');
  act(() => { host.querySelector('button').click(); });
  expect(box().value).toBe('0');
});

test('hapus semua → kosong, bukan "0" yang tak bisa dihapus', () => {
  act(() => root.render(<Harness initial={500} />));
  setText('');
  expect(box().value).toBe('');
  expect(state()).toBe('');
});

test('hapus satu digit dari 1.500 → 150', () => {
  act(() => root.render(<Harness initial={1500} decimals={2} />));
  setText('1.50');
  expect(box().value).toBe('150');
  expect(state()).toBe('150');
});

test('desimal dengan koma (mis. anggaran USD); titik yang diketik = koma', () => {
  act(() => root.render(<Harness decimals={2} />));
  type('1250,75');
  expect(box().value).toBe('1.250,75');
  expect(state()).toBe('1250.75');
  setText('');
  type('0.5'); // keyboard HP tanpa koma
  expect(box().value).toBe('0,5');
  expect(state()).toBe('0.5');
});

test('tempel "Rp 1.500.000" terbaca 1500000', () => {
  act(() => root.render(<Harness />));
  const el = box();
  el.focus();
  const ev = new Event('paste', { bubbles: true, cancelable: true });
  Object.defineProperty(ev, 'clipboardData', { value: { getData: () => 'Rp 1.500.000' } });
  act(() => { el.dispatchEvent(ev); });
  expect(el.value).toBe('1.500.000');
  expect(state()).toBe('1500000');
});

test('kotak teks dengan keyboard angka, bukan type=number', () => {
  act(() => root.render(<Harness />));
  expect(box().getAttribute('type')).toBe('text');
  expect(box().getAttribute('inputmode')).toBe('numeric');
});
