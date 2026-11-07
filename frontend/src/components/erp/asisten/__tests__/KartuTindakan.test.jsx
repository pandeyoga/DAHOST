// Tanpa @testing-library/react: paket @testing-library/dom (peer) tidak terpasang di lockfile — pola sama dengan
// markdown-aman.test.jsx (createRoot + act).
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import KartuTindakan from '../KartuTindakan';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const akar = [];
function render(el) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => { root.render(el); });
  akar.push({ root, container });
  return { container };
}
afterEach(() => {
  akar.splice(0).forEach(({ root, container }) => { act(() => root.unmount()); container.remove(); });
  document.body.innerHTML = '';
});
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const qa = (id) => [...document.querySelectorAll(`[data-testid="${id}"]`)];
const screen = {
  getByTestId: (id) => { const el = q(id); if (!el) throw new Error(`tidak ada [data-testid="${id}"]`); return el; },
  queryByTestId: q,
  getAllByTestId: qa,
  findByTestId: async (id) => { for (let i = 0; i < 40; i += 1) { const el = q(id); if (el) return el; await act(async () => { await new Promise((r) => setTimeout(r, 25)); }); } throw new Error(`tidak muncul: ${id}`); },
};
const within = (el) => ({ getByTestId: (id) => el.querySelector(`[data-testid="${id}"]`) });
const fireEvent = {
  click: (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); }),
  change: (el, { target: { value } }) => act(() => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }),
};
async function waitFor(fn) {
  let galat;
  for (let i = 0; i < 40; i += 1) {
    try { fn(); return; } catch (e) { galat = e; }
    // eslint-disable-next-line no-await-in-loop
    await act(async () => { await new Promise((r) => setTimeout(r, 25)); });
  }
  throw galat;
}

const RENCANA = {
  judul: 'Pasang target toko November 2026',
  ringkas: '2 toko, skenario realistis.',
  perubahan: [
    { label: 'Shopee Toko A', sebelum: 'Rp 120.000.000', sesudah: 'Rp 135.000.000' },
    { label: 'TikTok Toko C', sebelum: '—', sesudah: 'Rp 80.000.000' },
  ],
  catatan: ['Periode November masih terbuka.'],
  peringatan: ['Target TikTok Toko C naik lebih dari 30%.'],
  ubah: [{ kunci: 'toko.0.target', label: 'Target Shopee Toko A', jenis: 'rupiah', nilai: 135000000 }],
  tautan: { label: 'Buka layar Target', menu: 'mkt-targets' },
};
const blok = (extra = {}) => ({ jenis: 'tindakan', id: 'tnd-1', label: 'Memasang target toko', risiko: 'rendah', keadaan: 'menunggu', rencana: RENCANA, ...extra });
const tid = (id) => screen.getByTestId(id);

function tunda() {
  let selesai;
  const janji = new Promise((r) => { selesai = r; });
  return { janji, selesai };
}

describe('KartuTindakan', () => {
  test('menampilkan judul, ringkas, tabel perubahan, catatan, peringatan, status Menunggu', () => {
    render(<KartuTindakan blok={blok()} onPutuskan={jest.fn()} />);
    expect(tid('tindakan-judul')).toHaveTextContent('Pasang target toko November 2026');
    expect(tid('tindakan-ringkas')).toHaveTextContent('2 toko, skenario realistis.');
    expect(screen.getAllByTestId('tindakan-perubahan-baris')).toHaveLength(2);
    expect(screen.getAllByTestId('tindakan-perubahan-sesudah')[0]).toHaveTextContent('Rp 135.000.000');
    expect(tid('tindakan-catatan')).toHaveTextContent('Periode November masih terbuka.');
    expect(tid('tindakan-peringatan')).toHaveTextContent('naik lebih dari 30%');
    expect(tid('tindakan-status')).toHaveTextContent('Menunggu');
    expect(tid('asisten-tindakan')).toHaveAttribute('data-keadaan', 'menunggu');
  });

  test('klik ganda Setujui = satu permintaan; tombol terkunci selama berjalan', async () => {
    const t = tunda();
    const onPutuskan = jest.fn(() => t.janji);
    render(<KartuTindakan blok={blok()} onPutuskan={onPutuskan} />);
    fireEvent.click(tid('tindakan-setujui'));
    fireEvent.click(tid('tindakan-setujui'));
    fireEvent.click(tid('tindakan-batal'));
    expect(onPutuskan).toHaveBeenCalledTimes(1);
    expect(onPutuskan).toHaveBeenCalledWith('tnd-1', { keputusan: 'setujui', ubahan: undefined, alasan: undefined });
    expect(tid('tindakan-setujui')).toBeDisabled();
    expect(tid('tindakan-batal')).toBeDisabled();
    await act(async () => { t.selesai({ ok: true }); });
    expect(tid('tindakan-setujui')).not.toBeDisabled();
  });

  test('Ubah → isian rupiah berformat → Setujui mengirim ubahan berkunci jalur', async () => {
    const onPutuskan = jest.fn(async () => ({ ok: true }));
    render(<KartuTindakan blok={blok()} onPutuskan={onPutuskan} />);
    fireEvent.click(tid('tindakan-ubah-buka'));
    const isian = tid('tindakan-isian-toko.0.target');
    expect(isian).toHaveValue('135.000.000');
    fireEvent.change(isian, { target: { value: '140.000.000' } });
    await act(async () => { fireEvent.click(tid('tindakan-setujui')); });
    expect(onPutuskan).toHaveBeenCalledWith('tnd-1', { keputusan: 'setujui', ubahan: { 'toko.0.target': 140000000 }, alasan: undefined });
  });

  test('isian kosong → galat ramah, tidak ada permintaan; Urungkan menutup isian', () => {
    const onPutuskan = jest.fn();
    render(<KartuTindakan blok={blok()} onPutuskan={onPutuskan} />);
    fireEvent.click(tid('tindakan-ubah-buka'));
    fireEvent.change(tid('tindakan-isian-toko.0.target'), { target: { value: '' } });
    fireEvent.click(tid('tindakan-setujui'));
    expect(onPutuskan).not.toHaveBeenCalled();
    expect(tid('tindakan-galat-toko.0.target')).toHaveTextContent('Isian ini wajib diisi.');
    fireEvent.click(tid('tindakan-ubah-buka'));
    expect(screen.queryByTestId('tindakan-ubah')).toBeNull();
  });

  test('Batal mengirim keputusan batal', async () => {
    const onPutuskan = jest.fn(async () => ({ ok: true }));
    render(<KartuTindakan blok={blok()} onPutuskan={onPutuskan} />);
    await act(async () => { fireEvent.click(tid('tindakan-batal')); });
    expect(onPutuskan).toHaveBeenCalledWith('tnd-1', { keputusan: 'batal' });
  });

  test('risiko menengah: dialog alasan (≥ 10 huruf) lalu konfirmasi kedua; alasan ikut dikirim', async () => {
    const onPutuskan = jest.fn(async () => ({ ok: true }));
    render(<><ConfirmDialogHost /><KartuTindakan blok={blok({ risiko: 'menengah' })} onPutuskan={onPutuskan} /></>);
    fireEvent.click(tid('tindakan-setujui'));
    const dlg = await screen.findByTestId('confirm-dialog');
    expect(dlg).toHaveTextContent('Tulis alasan persetujuan');
    const ok = within(dlg).getByTestId('confirm-dialog-ok');
    fireEvent.change(within(dlg).getByTestId('confirm-dialog-input'), { target: { value: 'pendek' } });
    expect(ok).toBeDisabled();
    fireEvent.change(within(dlg).getByTestId('confirm-dialog-input'), { target: { value: 'Sudah dibahas di rapat' } });
    expect(ok).not.toBeDisabled();
    fireEvent.click(ok);
    await waitFor(() => expect(screen.getByTestId('confirm-dialog')).toHaveTextContent('Setujui dan jalankan sekarang?'));
    expect(onPutuskan).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getByTestId('confirm-dialog-ok')); });
    await waitFor(() => expect(onPutuskan).toHaveBeenCalledWith('tnd-1', { keputusan: 'setujui', ubahan: undefined, alasan: 'Sudah dibahas di rapat' }));
  });

  test('risiko menengah: dialog dibatalkan → tidak ada permintaan', async () => {
    const onPutuskan = jest.fn();
    render(<><ConfirmDialogHost /><KartuTindakan blok={blok({ risiko: 'menengah' })} onPutuskan={onPutuskan} /></>);
    fireEvent.click(tid('tindakan-setujui'));
    await screen.findByTestId('confirm-dialog');
    await act(async () => { fireEvent.click(screen.getByTestId('confirm-dialog-cancel')); });
    expect(onPutuskan).not.toHaveBeenCalled();
    expect(tid('tindakan-setujui')).not.toBeDisabled();
  });

  test('sudah dijalankan: tanpa tombol, ringkas hasil, catatan ubahan, tautan memanggil onNavigate', () => {
    const onNavigate = jest.fn();
    const rencana = { ...RENCANA, diubah: [{ kunci: 'toko.0.target', label: 'Target Shopee Toko A', sesudah: 140000000, jenis: 'rupiah' }] };
    render(<KartuTindakan blok={blok({ keadaan: 'dijalankan', ringkas: 'Target 2 toko November 2026 terpasang.', rencana })}
      onPutuskan={jest.fn()} onNavigate={onNavigate} />);
    expect(screen.queryByTestId('tindakan-setujui')).toBeNull();
    expect(tid('tindakan-status')).toHaveTextContent('Dijalankan');
    expect(tid('tindakan-hasil')).toHaveTextContent('Target 2 toko November 2026 terpasang.');
    expect(tid('tindakan-diubah')).toHaveTextContent('Target Shopee Toko A Rp 140.000.000');
    fireEvent.click(tid('tindakan-tautan'));
    expect(onNavigate).toHaveBeenCalledWith('mkt-targets');
  });

  test.each([
    ['gagal', 'Gagal', 'Toko sudah ditutup.'],
    ['dibatalkan', 'Dibatalkan', 'Tidak ada data yang diubah.'],
    ['kedaluwarsa', 'Kedaluwarsa', 'tidak dijalankan'],
    ['dibalikkan', 'Dibalikkan', 'nilai lama'],
  ])('keadaan %s: badge + kalimat hasil', (keadaan, label, teks) => {
    render(<KartuTindakan blok={blok({ keadaan, pesan: keadaan === 'gagal' ? 'Toko sudah ditutup.' : undefined })} onPutuskan={jest.fn()} />);
    expect(tid('tindakan-status')).toHaveTextContent(label);
    expect(tid('tindakan-hasil')).toHaveTextContent(teks);
    expect(screen.queryByTestId('tindakan-batal')).toBeNull();
  });

  test('dibalikkan: ringkas jalan lama (blok inti) tidak ditampilkan sebagai hasil', () => {
    render(<KartuTindakan blok={blok({ keadaan: 'dibalikkan', ringkas: 'Target 2 toko November 2026 terpasang.', bisa_dibalikkan: false })} onPutuskan={jest.fn()} />);
    expect(tid('tindakan-hasil')).toHaveTextContent('Perubahan sudah dibalikkan ke nilai lama.');
    expect(tid('tindakan-hasil')).not.toHaveTextContent('terpasang');
  });

  test('Tindakan AI dimatikan admin: Setujui ditahan, Batal tetap bisa', () => {
    render(<KartuTindakan blok={blok()} onPutuskan={jest.fn()} tindakanAktif={false} />);
    expect(tid('tindakan-setujui')).toBeDisabled();
    expect(tid('tindakan-batal')).not.toBeDisabled();
    expect(tid('tindakan-mati')).toHaveTextContent('dimatikan admin');
  });

  test('jawaban lain sedang mengalir: semua tombol ditahan', () => {
    render(<KartuTindakan blok={blok()} onPutuskan={jest.fn()} nonaktif />);
    expect(tid('tindakan-setujui')).toBeDisabled();
    expect(tid('tindakan-batal')).toBeDisabled();
  });

  test('teks dari server tidak dirender sebagai HTML', () => {
    const jahat = { ...RENCANA, judul: '<img src=x onerror="window.__xss=1">', perubahan: [{ label: '<b>x</b>', sebelum: '1', sesudah: '2' }] };
    const { container } = render(<KartuTindakan blok={blok({ rencana: jahat })} onPutuskan={jest.fn()} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    expect(tid('tindakan-judul')).toHaveTextContent('<img src=x');
  });
});
