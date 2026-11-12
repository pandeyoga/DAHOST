/**
 * Pengaman Merchandiser (K-M2, 12 Nov 2026): 428 "Pengaman Merchandiser" → dialog alasan → kirim ulang dengan
 * `alasan_merchandiser`; galat lain (termasuk 428 kelebihan qty) diteruskan apa adanya.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { denganAlasanMerchandiser, perluAlasanMerchandiser, galatDariRespons } from '../alasanMerchandiser';

jest.mock('@/components/ui/confirm-dialog', () => ({ confirmDialog: jest.fn() }));

const galat = (status, detail, axios = false) => {
  const e = new Error(detail);
  if (axios) e.response = { status, data: { detail } };
  else e.status = status;
  return e;
};
const PESAN = 'Pengaman Merchandiser: PO produksi ini menambah persediaan yang sulit terjual — DA-2 Mave +100 pcs';

beforeEach(() => confirmDialog.mockReset());

test('mengenali penolakan pengaman, bukan 428 kelebihan qty', () => {
  expect(perluAlasanMerchandiser(galat(428, PESAN))).toBe(true);
  expect(perluAlasanMerchandiser(galat(428, PESAN, true))).toBe(true);
  expect(perluAlasanMerchandiser(galat(428, 'Qty melebihi pesanan'))).toBe(false);
  expect(perluAlasanMerchandiser(galat(400, PESAN))).toBe(false);
});

test('tanpa penolakan: dikirim sekali tanpa dialog', async () => {
  const kirim = jest.fn().mockResolvedValue({ id: 'po1' });
  await expect(denganAlasanMerchandiser(kirim)).resolves.toEqual({ id: 'po1' });
  expect(kirim).toHaveBeenCalledTimes(1);
  expect(kirim).toHaveBeenCalledWith({});
  expect(confirmDialog).not.toHaveBeenCalled();
});

test('428 pengaman: dialog berisi angkanya, lalu kirim ulang dengan alasan', async () => {
  confirmDialog.mockResolvedValue('  Pesanan khusus toko offline  ');
  const kirim = jest.fn().mockRejectedValueOnce(galat(428, PESAN, true)).mockResolvedValueOnce({ ok: true });
  await expect(denganAlasanMerchandiser(kirim)).resolves.toEqual({ ok: true });
  expect(kirim).toHaveBeenLastCalledWith({ alasan_merchandiser: 'Pesanan khusus toko offline' });
  const opsi = confirmDialog.mock.calls[0][0];
  expect(opsi.body).toContain('DA-2 Mave +100 pcs');
  expect(opsi.body).not.toMatch(/^Pengaman Merchandiser/);
  expect(opsi.input.minLength).toBe(10);
});

test('kalimat dialog diawali huruf besar', async () => {
  confirmDialog.mockResolvedValue('Stok kain untuk model baru');
  const pesan = 'Pengaman Merchandiser: permintaan pembelian bahan ini menambah persediaan yang sulit terjual — K-01';
  const kirim = jest.fn().mockRejectedValueOnce(galat(428, pesan)).mockResolvedValueOnce({});
  await denganAlasanMerchandiser(kirim);
  expect(confirmDialog.mock.calls[0][0].body).toMatch(/^Permintaan pembelian bahan ini/);
});

test('dialog dibatalkan: tidak dikirim ulang, galat bertanda dibatalkan', async () => {
  confirmDialog.mockResolvedValue(false);
  const kirim = jest.fn().mockRejectedValue(galat(428, PESAN));
  await expect(denganAlasanMerchandiser(kirim)).rejects.toMatchObject({ dibatalkan: true });
  expect(kirim).toHaveBeenCalledTimes(1);
});

test('galat lain diteruskan apa adanya', async () => {
  const kirim = jest.fn().mockRejectedValue(galat(400, 'Supplier wajib diisi'));
  await expect(denganAlasanMerchandiser(kirim)).rejects.toThrow('Supplier wajib diisi');
  expect(confirmDialog).not.toHaveBeenCalled();
});

test('galatDariRespons membawa status & detail dari fetch', async () => {
  const res = { status: 428, json: async () => ({ detail: PESAN }) };
  const e = await galatDariRespons(res, 'cadangan');
  expect(e.status).toBe(428);
  expect(perluAlasanMerchandiser(e)).toBe(true);
});
