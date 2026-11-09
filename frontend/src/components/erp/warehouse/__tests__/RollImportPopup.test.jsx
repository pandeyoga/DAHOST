// 2026-11-09 — impor roll kain stok awal: Periksa (pratinjau) dulu, baru Terapkan; galat tampil, tidak menulis.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import RollImportPopup from '../RollImportPopup';
import { apiFetch } from '@/lib/api';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock('@/lib/api', () => ({ apiFetch: jest.fn() }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const tunggu = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const jawab = (body, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 400, json: async () => body });

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  apiFetch.mockReset();
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; });

function pilihBerkas() {
  const input = q('roll-import-file');
  const file = new File(['x'], 'roll.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  Object.defineProperty(input, 'files', { value: [file] });
  act(() => { input.dispatchEvent(new Event('change', { bubbles: true })); });
}

test('pratinjau dengan galat: tombol tetap "Periksa berkas", galat & ringkasan tampil, apply tidak dipanggil', async () => {
  apiFetch.mockReturnValueOnce(jawab({
    ok: false, errors: ['baris 4: KN-0 belum berharga'], warnings: ['2 roll memakai rata-rata (25 kg / 115 yard)'],
    totals: { rolls: 5, groups: 1, locations: 1, value: 5866250, average_rolls: 2 },
    groups: [{ material_id: 'k', location_id: 'l', code: 'KN-K20-TRC', name: 'Katun', location_code: 'GD-L2', rolls: 5,
      qty: 123.5, uom: 'kg', average_rolls: 2, value: 5866250 }],
  }));
  act(() => { root.render(<RollImportPopup open onClose={() => {}} />); });
  pilihBerkas();
  await act(async () => { q('roll-import-dialog-simpan').click(); });
  await tunggu();
  expect(apiFetch.mock.calls[0][0]).toBe('/api/wms/fabric-rolls/import/preview');
  expect(q('roll-import-errors').textContent).toContain('KN-0 belum berharga');
  expect(q('roll-import-summary').textContent).toContain('2 roll memakai rata-rata');
  expect(q('roll-import-groups').textContent).toContain('KN-K20-TRC');
  expect(q('roll-import-dialog-simpan').textContent).toBe('Periksa berkas');
});

test('pratinjau bersih → Terapkan memanggil apply lalu onDone', async () => {
  apiFetch
    .mockReturnValueOnce(jawab({ ok: true, errors: [], warnings: [], totals: { rolls: 1, groups: 1, locations: 1, value: 10 },
      groups: [] }))
    .mockReturnValueOnce(jawab({ already: false, message: '1 roll dibuat' }));
  const onDone = jest.fn();
  const onClose = jest.fn();
  act(() => { root.render(<RollImportPopup open onClose={onClose} onDone={onDone} />); });
  pilihBerkas();
  await act(async () => { q('roll-import-dialog-simpan').click(); });
  await tunggu();
  expect(q('roll-import-dialog-simpan').textContent).toBe('Terapkan');
  await act(async () => { q('roll-import-dialog-simpan').click(); });
  await tunggu();
  expect(apiFetch.mock.calls[1][0]).toBe('/api/wms/fabric-rolls/import/apply');
  expect(apiFetch.mock.calls[1][1].body).toBeInstanceOf(FormData);
  expect(onDone).toHaveBeenCalled();
  expect(onClose).toHaveBeenCalled();
});
