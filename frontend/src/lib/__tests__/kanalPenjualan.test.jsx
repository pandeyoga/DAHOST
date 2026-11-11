/**
 * Kanal penjualan pada input manual Marketing (keputusan owner 11 Nov 2026).
 * Rincian per kanal = BAGIAN dari omzet; sisanya "Lainnya"; lebih besar dari batas ditolak di layar.
 */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import {
  KANAL_PESANAN, KANAL_RINCIAN, hitungRincian, rincianBersih, kanalUtama, labelKanal, adaPecahan,
} from '../kanalPenjualan';
import RincianKanal from '../../components/erp/marketing/RincianKanal';

global.IS_REACT_ACT_ENVIRONMENT = true;

function render(el) {
  const div = document.createElement('div');
  document.body.appendChild(div);
  const root = createRoot(div);
  act(() => { root.render(el); });
  return { div, unmount: () => act(() => root.unmount()) };
}

describe('daftar kanal', () => {
  it('sama dengan kanal pesanan di backend; Lainnya tidak bisa diketik', () => {
    expect(KANAL_PESANAN.map(([k]) => k)).toEqual(
      ['live', 'video', 'product_card', 'affiliate', 'ads', 'campaign', 'search', 'other']);
    expect(KANAL_RINCIAN.map(([k]) => k)).not.toContain('other');
    expect(labelKanal('product_card')).toBe('Kartu produk');
    expect(labelKanal('tidak_ada')).toBe('Lainnya');
  });
});

describe('hitungRincian', () => {
  it('sisa omzet menjadi Lainnya; rincian di atas batas ditandai', () => {
    expect(hitungRincian({ live: '3000000', video: '1000000' }, 10000000))
      .toEqual({ jumlah: 4000000, sisa: 6000000, lebih: false });
    expect(hitungRincian({ live: '11000000' }, 10000000).lebih).toBe(true);
    expect(hitungRincian({}, 0)).toEqual({ jumlah: 0, sisa: 0, lebih: false });
  });
  it('hanya kanal bernilai yang dikirim ke server', () => {
    expect(rincianBersih({ live: '2500000', video: '', ads: '0', other: '9' })).toEqual({ live: 2500000 });
  });
  it('kanal utama + Lainnya gabungan untuk tabel per toko', () => {
    expect(kanalUtama({ live: 5, ads: 2, campaign: 1, other: 3 }))
      .toEqual({ live: 5, video: 0, product_card: 0, affiliate: 0, other: 6 });
    expect(adaPecahan({})).toBe(false);
    expect(adaPecahan({ other: 1 })).toBe(true);
  });
});

describe('RincianKanal (form Input Sales)', () => {
  it('menampilkan sisa Lainnya dan peringatan bila rincian melebihi omzet', () => {
    const nilai = { live: '3000000', video: '', product_card: '', affiliate: '', ads: '', campaign: '', search: '' };
    const { div, unmount } = render(
      <RincianKanal nilai={nilai} rincian={hitungRincian(nilai, 10000000)} batas={10000000}
        kanalPesanan={null} onUbah={() => {}} />);
    expect(div.querySelector('[data-testid="sd-kanal-live"]')).not.toBeNull();
    expect(div.querySelector('[data-testid="sd-kanal-sisa"]').textContent).toContain('7.000.000');
    expect(div.querySelector('[data-testid="sd-kanal-lebih"]')).toBeNull();
    unmount();
    const lebih = { ...nilai, live: '12000000' };
    const r2 = render(
      <RincianKanal nilai={lebih} rincian={hitungRincian(lebih, 10000000)} batas={10000000}
        kanalPesanan={null} onUbah={() => {}} />);
    expect(r2.div.querySelector('[data-testid="sd-kanal-lebih"]').textContent).toContain('lebih besar');
    r2.unmount();
  });

  it('hari berpesanan: kanal dari pesanan ditampilkan, batas = bagian Lainnya pesanan', () => {
    const nilai = { live: '', video: '', product_card: '', affiliate: '', ads: '', campaign: '', search: '' };
    const pesanan = { live: 4000000, video: 1000000, other: 5000000 };
    const { div, unmount } = render(
      <RincianKanal nilai={nilai} rincian={hitungRincian(nilai, 5000000)} batas={5000000}
        kanalPesanan={pesanan} onUbah={() => {}} liveTercatat={2000000} onPakaiLive={() => {}} />);
    const teks = div.querySelector('[data-testid="sd-kanal-pesanan"]').textContent;
    expect(teks).toContain('Live');
    expect(teks).toContain('4.000.000');
    expect(div.querySelector('[data-testid="sd-kanal"]').textContent).toContain('pesanan tanpa kanal');
    expect(div.querySelector('[data-testid="sd-kanal-pakai-live"]')).not.toBeNull();
    unmount();
  });
});
