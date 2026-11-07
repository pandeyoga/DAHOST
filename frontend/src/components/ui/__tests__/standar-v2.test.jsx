/**
 * Standar UI/UX v2 (8 Nov 2026) — komponen bersama & aturan tanggal/keadaan pengumuman.
 */
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import TabelData from '../tabel-data';
import { formatTanggalID } from '../date-picker';
import { keadaanPengumuman, labelPeriode, labelTujuan } from '../../erp/pengumuman/aturan';

global.IS_REACT_ACT_ENVIRONMENT = true;

function render(el) {
  const div = document.createElement('div');
  document.body.appendChild(div);
  const root = createRoot(div);
  act(() => { root.render(el); });
  return { div, unmount: () => act(() => root.unmount()) };
}

describe('formatTanggalID', () => {
  it('menampilkan tanggal kalender apa adanya, tanpa geser zona waktu', () => {
    expect(formatTanggalID('2026-12-01')).toBe('1 Des 2026');
    expect(formatTanggalID('2026-11-10T23:59:59')).toBe('10 Nov 2026');
    expect(formatTanggalID('')).toBe('');
  });
});

describe('pengumuman: keadaan, periode, tujuan', () => {
  const sekarang = Date.parse('2026-11-08T03:00:00Z'); // 8 Nov 10.00 WIB
  it('membaca waktu tanpa zona sebagai UTC (data lama) dan menentukan keadaan', () => {
    expect(keadaanPengumuman({ is_active: false }, sekarang)).toBe('nonaktif');
    expect(keadaanPengumuman({ is_active: true, start_date: '2026-11-30T17:00:00' }, sekarang)).toBe('terjadwal');
    expect(keadaanPengumuman({ is_active: true, end_date: '2026-11-07T16:59:59' }, sekarang)).toBe('berakhir');
    // berakhir 8 Nov 23.59 WIB → masih tampil pukul 10.00 WIB (dulu sudah hilang 07.00)
    expect(keadaanPengumuman({ is_active: true, end_date: '2026-11-08T16:59:59+00:00' }, sekarang)).toBe('tampil');
  });
  it('periode dalam tanggal WIB', () => {
    expect(labelPeriode({ start_date: '2026-11-30T17:00:00', end_date: '2026-12-12T16:59:59' })).toBe('1 Des 2026 – 12 Des 2026');
    expect(labelPeriode({})).toBe('Tanpa batas waktu');
  });
  it('tujuan: semua portal / nama portal / ringkas', () => {
    expect(labelTujuan(['all'])).toBe('Semua portal');
    expect(labelTujuan(['warehouse', 'production', 'finance'])).toBe('Gudang, Produksi +1');
  });
});

describe('TabelData', () => {
  it('menampilkan tabel di layar lebar & kartu di HP dari kolom yang sama, aksi tidak memicu klik baris', () => {
    const klik = jest.fn();
    const aksi = jest.fn();
    const { div, unmount } = render(
      <TabelData testId="t" onKlikBaris={klik}
        baris={[{ id: 1, nama: 'A', n: 2 }, { id: 2, nama: 'B', n: 5 }]}
        kolom={[
          { kunci: 'nama', label: 'Nama', hp: 'judul' },
          { kunci: 'n', label: 'Jumlah', rata: 'kanan' },
          { kunci: 'aksi', label: '', hp: 'aksi', isi: (b) => <button type="button" data-aksi={b.id} onClick={aksi}>Ubah</button> },
        ]} />,
    );
    expect(div.querySelectorAll('[data-testid="t-baris"]').length).toBe(2);
    expect(div.querySelectorAll('[data-testid="t-kartu"]').length).toBe(2);
    act(() => { div.querySelector('[data-testid="t-baris"]').click(); });
    expect(klik).toHaveBeenCalledWith({ id: 1, nama: 'A', n: 2 });
    act(() => { div.querySelector('[data-aksi="2"]').click(); });
    expect(aksi).toHaveBeenCalled();
    expect(klik).toHaveBeenCalledTimes(1);
    unmount();
  });
  it('tanpa baris → menampilkan isi kosong', () => {
    const { div, unmount } = render(<TabelData kolom={[]} baris={[]} kosong={<p>kosong</p>} />);
    expect(div.textContent).toBe('kosong');
    unmount();
  });
});
