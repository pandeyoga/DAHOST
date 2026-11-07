// Tahap D (layar2): chip ingatan di jawaban, lencana Briefing/Laporan mingguan di riwayat, tautan notifikasi.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import PesanAsisten from '../PesanAsisten';
import RiwayatPercakapan from '../RiwayatPercakapan';
import UtasPesan from '../UtasPesan';
import { navigateToNotification, punyaTujuan, tujuanDariTautan } from '../../NotificationBell';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));
jest.mock('../GrafikAsisten', () => () => null);
jest.mock('../../Modal', () => () => null);
jest.mock('../../NotificationPrefsDialog', () => () => null);

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => container.querySelector(`[data-testid="${id}"]`);
const qa = (id) => [...container.querySelectorAll(`[data-testid="${id}"]`)];
const klik = (el) => act(() => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

test('chip "Diingat"/"Dilupakan" dari blok tersimpan; tautan ke Ingatan AI menyorot ingatan terakhir yang disimpan', () => {
  const onNavigate = jest.fn();
  const pesan = {
    id: 'm1', peran: 'asisten', keadaan: 'selesai', blok: [
      { jenis: 'teks', isi: 'Baik, saya ingat target itu.' },
      { jenis: 'ingatan', id: 'i1', isi: 'Target minimal tumbuh 8%', kategori: 'preferensi', aksi: 'disimpan' },
      { jenis: 'ingatan', id: 'i0', isi: '<img src=x onerror=alert(1)>', aksi: 'dihapus' },
    ],
  };
  act(() => { root.render(<PesanAsisten pesan={pesan} onNavigate={onNavigate} />); });
  const chips = qa('asisten-ingatan-chip');
  expect(chips.map((c) => c.textContent)).toEqual(['Diingat: Target minimal tumbuh 8%', 'Dilupakan: <img src=x onerror=alert(1)>']);
  expect(chips[1].dataset.aksi).toBe('dihapus');
  expect(container.querySelector('img')).toBeNull(); // teks biasa, bukan HTML
  klik(q('asisten-ingatan-tautan'));
  expect(onNavigate).toHaveBeenCalledWith('asisten-ai-ingatan', { ingatan: 'i1' });
});

test('tanpa blok ingatan → tidak ada chip', () => {
  act(() => { root.render(<PesanAsisten pesan={{ id: 'm', peran: 'asisten', keadaan: 'selesai', blok: [{ jenis: 'teks', isi: 'Halo' }] }} />); });
  expect(q('asisten-ingatan')).toBeNull();
});

test('riwayat: lencana Briefing / Laporan mingguan; percakapan biasa tanpa lencana; tautan Ingatan AI', () => {
  const onTampilan = jest.fn();
  const kini = new Date().toISOString();
  const sesi = [
    { id: 's1', judul: 'Briefing pagi 08 Nov 2026', jenis: 'briefing', updated_at: kini },
    { id: 's2', judul: 'Laporan mingguan 2–8 Nov', jenis: 'laporan_mingguan', updated_at: kini },
    { id: 's3', judul: 'Omzet bulan ini', updated_at: kini },
  ];
  act(() => {
    root.render(<RiwayatPercakapan sesi={sesi} memuat={false} aktifId="s1" cari="" onCari={() => {}} onPilih={() => {}}
      onBaru={() => {}} tampilan="chat" onTampilan={onTampilan} />);
  });
  const items = qa('asisten-sesi-item');
  expect(items.map((i) => i.dataset.jenis)).toEqual(['briefing', 'laporan_mingguan', undefined]);
  expect(items[0].querySelector('[data-testid="asisten-sesi-jenis"]').textContent).toBe('Briefing');
  expect(items[1].querySelector('[data-testid="asisten-sesi-jenis"]').textContent).toBe('Laporan mingguan');
  expect(items[2].querySelector('[data-testid="asisten-sesi-jenis"]')).toBeNull();
  klik(q('asisten-tautan-ingatan'));
  expect(onTampilan).toHaveBeenCalledWith('ingatan');
});

test('permintaan otomatis (pesan pengguna `otomatis`) tampil sebagai gelembung redup "Permintaan otomatis"', () => {
  const pesan = [
    { kunci: 'u1', peran: 'user', otomatis: true, teks: 'Susun briefing pagi untuk hari ini: omzet, kas, piutang.' },
    { kunci: 'a1', peran: 'asisten', keadaan: 'selesai', blok: [{ jenis: 'teks', isi: 'Briefing pagi.' }] },
    { kunci: 'u2', peran: 'user', teks: 'Terima kasih' },
  ];
  act(() => { root.render(<UtasPesan pesan={pesan} memuat={false} kosong={null} />); });
  const g = qa('asisten-pesan-pengguna');
  expect(g.map((x) => x.dataset.otomatis)).toEqual(['1', undefined]);
  expect(q('asisten-pesan-otomatis').textContent).toContain('Permintaan otomatis');
  expect(q('asisten-pesan-otomatis').textContent).toContain('Susun briefing pagi');
  expect(g[1].textContent).toBe('Terima kasih');
});

describe('notifikasi bertautan', () => {
  const kirim = (n) => {
    const seen = [];
    const h = (e) => { seen.push(e.detail); e.detail.handled = true; };
    window.addEventListener('erp:navigate-module', h);
    const ok = navigateToNotification(n);
    window.removeEventListener('erp:navigate-module', h);
    return { ok, seen };
  };

  test('bentuk NYATA notifikasi briefing: link_module + link_id + link_params {sesi} → params.sesi', () => {
    const { seen } = kirim({ id: 'n7', link_module: 'asisten-ai', link_id: 'sesi-r', link_params: { sesi: 'sesi-r' } });
    expect(seen[0].params).toMatchObject({ sesi: 'sesi-r', link_id: 'sesi-r', tujuan_modul: 'asisten-ai' });
  });

  test('link_module asisten-ai + link_id → params membawa id sesi (dibaca layar sebagai sesi)', () => {
    const { ok, seen } = kirim({ id: 'n1', link_module: 'asisten-ai', link_id: 'sesi-b1' });
    expect(ok).toBe(true);
    expect(seen[0].moduleId).toBe('asisten-ai');
    expect(seen[0].params).toMatchObject({ link_id: 'sesi-b1', record_id: 'sesi-b1', from_notification: 'n1', tujuan_modul: 'asisten-ai' });
  });

  test('tautan alamat aplikasi di source_url → modul + sesi; hash lama & situs lain tidak dianggap tujuan', () => {
    expect(tujuanDariTautan('/?portal=management&module=asisten-ai&sesi=sesi-b2'))
      .toEqual({ moduleId: 'asisten-ai', params: { sesi: 'sesi-b2' } });
    expect(tujuanDariTautan(`${window.location.origin}/?module=asisten-ai&sesi=s9`).params).toEqual({ sesi: 's9' });
    expect(tujuanDariTautan('#wh-accessory')).toBeNull();
    expect(tujuanDariTautan('https://contoh.invalid/?module=asisten-ai&sesi=s')).toBeNull();
    expect(tujuanDariTautan('/?module=Bad Module')).toBeNull();
    expect(punyaTujuan({ source_url: '#wh-accessory' })).toBe(false);
    expect(punyaTujuan({ source_url: '/?portal=management&module=asisten-ai&sesi=s1' })).toBe(true);
    const { ok, seen } = kirim({ id: 'n2', source_url: '/?portal=management&module=asisten-ai&sesi=sesi-b2' });
    expect(ok).toBe(true);
    expect(seen[0]).toMatchObject({ moduleId: 'asisten-ai', params: { sesi: 'sesi-b2', from_notification: 'n2', tujuan_modul: 'asisten-ai' } });
  });

  test('link_module tetap didahulukan dari source_url', () => {
    const { seen } = kirim({ id: 'n3', link_module: 'fin-ap', source_url: '/?module=asisten-ai&sesi=s1' });
    expect(seen[0].moduleId).toBe('fin-ap');
    expect(seen[0].params.sesi).toBeUndefined();
    expect(seen[0].params.tujuan_modul).toBe('fin-ap');
  });
});
