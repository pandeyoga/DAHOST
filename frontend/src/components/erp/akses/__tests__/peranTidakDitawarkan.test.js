// Keputusan owner 8 Nov 2026: peran bawaan yang belum diatur & tidak dipakai tidak ditawarkan di pilihan peran pengguna.
import { peranTidakDitawarkan } from '../labelPeran';

describe('peranTidakDitawarkan', () => {
  test('peran tanpa portal, tanpa izin, tanpa pengguna → tidak ditawarkan', () => {
    expect(peranTidakDitawarkan({ name: 'accounting', portals: [], permission_keys: [], user_count: 0 })).toBe(true);
    expect(peranTidakDitawarkan({ name: 'hr' })).toBe(true);
  });

  test('peran yang sudah diatur atau masih dipakai tetap ditawarkan', () => {
    expect(peranTidakDitawarkan({ name: 'Operator Cuting', portals: ['cutting'], permission_keys: [], user_count: 0 })).toBe(false);
    expect(peranTidakDitawarkan({ name: 'admin_produksi', portals: [], permission_keys: ['mod.x.view'], user_count: 0 })).toBe(false);
    expect(peranTidakDitawarkan({ name: 'tim_packing', portals: [], permission_keys: [], user_count: 4 })).toBe(false);
    expect(peranTidakDitawarkan(null)).toBe(false);
  });
});
