// 2026-11-11 — keluhan owner: "tanggal lahir di karyawan saya tidak bisa pilih langsung tahunnya, menyebabkan saya harus
// klik jauh". DatePicker kini punya mode `pilihTahun`: pilihan bulan + tahun di kepala kalender, dan tanggal bisa diketik.
// Tanggal di bawah ini contoh buatan, bukan data karyawan.
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import DatePicker, { bacaTanggalKetik, rentangTahun, hariIniWIB } from '../date-picker';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const TAHUN_INI = Number(hariIniWIB().slice(0, 4));

let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  for (let i = 0; i < 50; i += 1) {
    if (fn()) return;
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
  throw new Error('waktu habis');
};
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
const ketik = (el, v) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
const enter = (el) => act(() => {
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
});

function Induk({ awal = '', onUbah = () => {}, ...props }) {
  const [v, setV] = useState(awal);
  return <DatePicker value={v} onChange={(x) => { setV(x); onUbah(x); }} testId="tgl" {...props} />;
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

describe('bacaTanggalKetik', () => {
  it('menerima cara ketik yang lazim', () => {
    expect(bacaTanggalKetik('17/08/1995')).toBe('1995-08-17');
    expect(bacaTanggalKetik('7-8-1995')).toBe('1995-08-07');
    expect(bacaTanggalKetik('17.08.1995')).toBe('1995-08-17');
    expect(bacaTanggalKetik('17081995')).toBe('1995-08-17');
    expect(bacaTanggalKetik('17 Agu 1995')).toBe('1995-08-17');
    expect(bacaTanggalKetik('17 Agustus 1995')).toBe('1995-08-17');
    expect(bacaTanggalKetik('1 des 1990')).toBe('1990-12-01');
    expect(bacaTanggalKetik('1995-08-17')).toBe('1995-08-17');
  });
  it('menolak tanggal yang tidak ada atau tidak lengkap', () => {
    expect(bacaTanggalKetik('')).toBeNull();
    expect(bacaTanggalKetik('31/02/1995')).toBeNull();
    expect(bacaTanggalKetik('29/02/1995')).toBeNull();
    expect(bacaTanggalKetik('29/02/1996')).toBe('1996-02-29');
    expect(bacaTanggalKetik('17/13/1995')).toBeNull();
    expect(bacaTanggalKetik('17/08/95')).toBeNull();
    expect(bacaTanggalKetik('17 xyz 1995')).toBeNull();
  });
});

describe('rentangTahun', () => {
  const dasar = { tahunIni: 2026 };
  it('mati tanpa pilihTahun', () => {
    expect(rentangTahun(false, dasar)).toBeNull();
  });
  it('lahir = 80 s.d. 14 tahun lalu; lampau = 50 tahun lalu s.d. tahun depan; umum = −50 s.d. +20', () => {
    expect(rentangTahun('lahir', dasar)).toEqual({ dari: 1946, sampai: 2012 });
    expect(rentangTahun('lampau', dasar)).toEqual({ dari: 1976, sampai: 2027 });
    expect(rentangTahun(true, dasar)).toEqual({ dari: 1976, sampai: 2046 });
  });
  it('min/max mempersempit, tahun nilai tersimpan selalu ikut', () => {
    expect(rentangTahun(true, { ...dasar, min: '2025-03-01' })).toEqual({ dari: 2025, sampai: 2046 });
    expect(rentangTahun('lampau', { ...dasar, max: '2026-11-11' })).toEqual({ dari: 1976, sampai: 2026 });
    expect(rentangTahun('lahir', { ...dasar, nilai: '2020-01-01' })).toEqual({ dari: 1946, sampai: 2020 });
    expect(rentangTahun('lahir', { ...dasar, tahunDari: 1960, tahunSampai: 2008 })).toEqual({ dari: 1960, sampai: 2008 });
  });
});

describe('DatePicker mode pilihTahun', () => {
  it('tanpa pilihTahun tampilan lama: tidak ada pilihan bulan/tahun maupun kotak ketik', async () => {
    act(() => { root.render(<Induk />); });
    klik(q('tgl'));
    await tunggu(() => q('tgl-kalender'));
    expect(q('tgl-tahun')).toBeNull();
    expect(q('tgl-bulan')).toBeNull();
    expect(q('tgl-ketik')).toBeNull();
  });

  it('tahun dan bulan dipilih langsung, lalu klik hari', async () => {
    const onUbah = jest.fn();
    const tahun = TAHUN_INI - 30;
    act(() => { root.render(<Induk pilihTahun="lahir" onUbah={onUbah} />); });
    klik(q('tgl'));
    await tunggu(() => q('tgl-tahun-trigger'));

    // daftar tahun: terbaru (tahun ini −14) di atas, paling lama tahun ini −80
    klik(q('tgl-tahun-trigger'));
    await tunggu(() => q(`tgl-tahun-option-${tahun}`));
    const opsi = [...q('tgl-tahun-list').querySelectorAll('[role="option"]')].map((o) => Number(o.dataset.value));
    expect(opsi[0]).toBe(TAHUN_INI - 14);
    expect(opsi[opsi.length - 1]).toBe(TAHUN_INI - 80);
    expect(opsi).toHaveLength(67);
    klik(q(`tgl-tahun-option-${tahun}`));
    await tunggu(() => q('tgl-tahun-trigger').dataset.value === String(tahun));

    klik(q('tgl-bulan-trigger'));
    await tunggu(() => q('tgl-bulan-option-7'));
    klik(q('tgl-bulan-option-7')); // Agustus
    await tunggu(() => q(`tgl-hari-${tahun}-08-17`));

    klik(q(`tgl-hari-${tahun}-08-17`));
    expect(onUbah).toHaveBeenLastCalledWith(`${tahun}-08-17`);
    await tunggu(() => !q('tgl-kalender'));
    expect(q('tgl').textContent).toContain(`17 Agu ${tahun}`);
  });

  it('tanggal bisa diketik: garis miring otomatis, Enter memakai tanggal', async () => {
    const onUbah = jest.fn();
    const tahun = TAHUN_INI - 31;
    act(() => { root.render(<Induk pilihTahun="lahir" onUbah={onUbah} />); });
    klik(q('tgl'));
    await tunggu(() => q('tgl-ketik'));
    const kotak = q('tgl-ketik');
    ketik(kotak, '17');
    expect(kotak.value).toBe('17/');
    ketik(kotak, '17/08');
    expect(kotak.value).toBe('17/08/');
    ketik(kotak, `17/08/${tahun}`);
    // kalender ikut pindah ke bulan yang diketik
    expect(q('tgl-tahun-trigger').dataset.value).toBe(String(tahun));
    expect(q('tgl-bulan-trigger').dataset.value).toBe('7');
    enter(kotak);
    expect(onUbah).toHaveBeenLastCalledWith(`${tahun}-08-17`);
  });

  it('ketikan salah atau di luar rentang → pesan, nilai tidak berubah', async () => {
    const onUbah = jest.fn();
    act(() => { root.render(<Induk pilihTahun="lahir" onUbah={onUbah} />); });
    klik(q('tgl'));
    await tunggu(() => q('tgl-ketik'));
    ketik(q('tgl-ketik'), '31/02/1995');
    klik(q('tgl-ketik-pakai'));
    expect(q('tgl-ketik-galat').textContent).toContain('tidak dikenali');
    ketik(q('tgl-ketik'), `01/01/${TAHUN_INI}`);
    enter(q('tgl-ketik'));
    expect(q('tgl-ketik-galat').textContent).toBe(`Tahun harus antara ${TAHUN_INI - 80} dan ${TAHUN_INI - 14}.`);
    expect(onUbah).not.toHaveBeenCalled();
    // tanggal lahir: tombol "Hari ini" tidak ditawarkan
    expect([...q('tgl-kalender').querySelectorAll('button')].some((b) => b.textContent === 'Hari ini')).toBe(false);
  });

  it('min tetap berlaku untuk ketikan', async () => {
    const onUbah = jest.fn();
    act(() => { root.render(<Induk pilihTahun min="2024-03-01" onUbah={onUbah} />); });
    klik(q('tgl'));
    await tunggu(() => q('tgl-ketik'));
    ketik(q('tgl-ketik'), '28/02/2024');
    enter(q('tgl-ketik'));
    expect(q('tgl-ketik-galat').textContent).toBe('Tanggal paling awal 1 Mar 2024.');
    expect(onUbah).not.toHaveBeenCalled();
  });

  it('nilai tersimpan tampil di kotak ketik dan kalender terbuka di tahunnya', async () => {
    act(() => { root.render(<Induk pilihTahun="lahir" awal="1988-05-09" />); });
    klik(q('tgl'));
    await tunggu(() => q('tgl-ketik'));
    expect(q('tgl-ketik').value).toBe('09/05/1988');
    expect(q('tgl-tahun-trigger').dataset.value).toBe('1988');
    expect(q('tgl-bulan-trigger').dataset.value).toBe('4');
    expect(q('tgl-hari-1988-05-09').className).toContain('bg-primary');
  });
});
