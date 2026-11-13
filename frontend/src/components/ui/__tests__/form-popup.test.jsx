/**
 * FormPopup (14 Nov 2026, keluhan owner di Scan Keluar: "klik diluar popup maka saya harus mulai dari awal karena
 * hilang"): klik di luar TIDAK menutup formulir; × / Esc / Batal dengan `adaIsian` meminta konfirmasi dulu.
 * Tanpa @testing-library/react (peer @testing-library/dom tidak terpasang) — createRoot + act.
 */
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import FormPopup from '../form-popup';
import { Dialog, DialogContent, DialogTitle } from '../dialog';
import { ConfirmDialogHost } from '../confirm-dialog';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let container;
let luar;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
// Radix memasang pendengar "klik di luar" sesudah satu putaran timer — tunggu sebentar sebelum mengetuk.
const jeda = () => act(async () => { await new Promise((r) => setTimeout(r, 30)); });
const ketukLuar = async () => {
  await jeda();
  act(() => {
    luar.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, cancelable: true, button: 0 }));
    luar.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
    luar.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
  });
  await jeda();
};
const tekanEsc = async () => {
  await jeda();
  act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); });
  await jeda();
};
const tombolTutup = () => [...document.querySelectorAll('[data-testid="f"] button')]
  .find((b) => b.textContent.includes('Tutup'));

function Formulir({ onClose = jest.fn(), adaIsianDariTeks = false, menyimpan = false, konfirmasiTutup }) {
  const [buka, setBuka] = useState(true);
  const [teks, setTeks] = useState('');
  return (
    <FormPopup open={buka} testId="f" judul="Formulir uji" menyimpan={menyimpan}
      adaIsian={adaIsianDariTeks && teks.length > 0} konfirmasiTutup={konfirmasiTutup}
      onClose={() => { onClose(); setBuka(false); }} onSimpan={() => {}}>
      <input data-testid="f-teks" value={teks} onChange={(e) => setTeks(e.target.value)} />
    </FormPopup>
  );
}

beforeEach(() => {
  luar = document.createElement('button');
  luar.setAttribute('data-testid', 'di-luar');
  document.body.appendChild(luar);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = '';
});

describe('FormPopup — klik di luar', () => {
  test('pembanding: Dialog biasa memang tertutup oleh klik di luar (alat uji mendeteksi klik luar)', async () => {
    const tutup = jest.fn();
    act(() => root.render(
      <Dialog open onOpenChange={(o) => { if (!o) tutup(); }}>
        <DialogContent data-testid="biasa"><DialogTitle>Biasa</DialogTitle></DialogContent>
      </Dialog>,
    ));
    await ketukLuar();
    expect(tutup).toHaveBeenCalledTimes(1);
  });

  test('klik di luar tidak menutup formulir dan isian tetap utuh', async () => {
    const tutup = jest.fn();
    act(() => root.render(<><ConfirmDialogHost /><Formulir onClose={tutup} adaIsianDariTeks /></>));
    ketik(q('f-teks'), 'SKU-1 × 3');
    await ketukLuar();
    await ketukLuar();
    expect(tutup).not.toHaveBeenCalled();
    expect(q('f')).not.toBeNull();
    expect(q('f-teks').value).toBe('SKU-1 × 3');
    expect(q('confirm-dialog')).toBeNull();   // klik luar juga tidak memunculkan konfirmasi
  });
});

describe('FormPopup — tutup lewat ×, Esc, Batal', () => {
  test('tanpa isian: Batal langsung menutup, tanpa konfirmasi', async () => {
    const tutup = jest.fn();
    act(() => root.render(<><ConfirmDialogHost /><Formulir onClose={tutup} adaIsianDariTeks /></>));
    klik(q('f-batal'));
    await jeda();
    expect(q('confirm-dialog')).toBeNull();
    expect(tutup).toHaveBeenCalledTimes(1);
    expect(q('f')).toBeNull();
  });

  test('ada isian: Batal meminta konfirmasi; "Kembali ke formulir" membiarkan isian, "Buang" menutup', async () => {
    const tutup = jest.fn();
    act(() => root.render(
      <><ConfirmDialogHost />
        <Formulir onClose={tutup} adaIsianDariTeks
          konfirmasiTutup={{ judul: 'Buang pilihan barang?', isi: '1 barang belum disimpan.', labelBuang: 'Buang pilihan' }} />
      </>,
    ));
    ketik(q('f-teks'), 'isi');
    klik(q('f-batal'));
    await jeda();
    expect(q('confirm-dialog')).not.toBeNull();
    expect(q('confirm-dialog').textContent).toContain('Buang pilihan barang?');
    expect(q('confirm-dialog-ok').textContent).toBe('Buang pilihan');
    expect(q('confirm-dialog-cancel').textContent).toBe('Kembali ke formulir');
    klik(q('confirm-dialog-cancel'));
    await jeda();
    expect(tutup).not.toHaveBeenCalled();
    expect(q('f-teks').value).toBe('isi');

    // × juga lewat konfirmasi yang sama
    klik(tombolTutup());
    await jeda();
    expect(q('confirm-dialog')).not.toBeNull();
    klik(q('confirm-dialog-ok'));
    await jeda();
    expect(tutup).toHaveBeenCalledTimes(1);
    expect(q('f')).toBeNull();
  });

  test('ada isian: Esc meminta konfirmasi, tidak langsung menutup', async () => {
    const tutup = jest.fn();
    act(() => root.render(<><ConfirmDialogHost /><Formulir onClose={tutup} adaIsianDariTeks /></>));
    ketik(q('f-teks'), 'isi');
    await tekanEsc();
    expect(q('confirm-dialog')).not.toBeNull();
    expect(q('confirm-dialog').textContent).toContain('Buang isian yang belum disimpan?');
    expect(tutup).not.toHaveBeenCalled();
    klik(q('confirm-dialog-cancel'));
    await jeda();
    expect(q('f')).not.toBeNull();
    expect(q('f-teks').value).toBe('isi');
  });

  test('sedang menyimpan: Esc dan klik luar tidak menutup, Batal terkunci', async () => {
    const tutup = jest.fn();
    act(() => root.render(<><ConfirmDialogHost /><Formulir onClose={tutup} menyimpan /></>));
    await tekanEsc();
    await ketukLuar();
    expect(tutup).not.toHaveBeenCalled();
    expect(q('f-batal').disabled).toBe(true);
  });
});
