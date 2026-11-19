/**
 * Order Cutting × resep kain (owner 18 Nov 2026: produk lebih dari satu kain — "bomnya harus ada dua kain atau lebih
 * otomatis menyesuaikan roll kainnya").
 *   • kebutuhan kain dijumlah per kain dari resep semua hasil (perkiraan × target), perkiraan kosong ditandai;
 *   • gulungan dicentang FIFO sampai sisa terpilih cukup untuk rencana;
 *   • hasil tanpa resep dianggap memakai semua kain (tautan gulungan tidak hilang).
 */
import { kebutuhanResep, pakaiKain, pilihGulunganFifo, bagiNilaiPerKain, hppPerBaris } from '../cutting/cuttingLines';
import { isianKeResep, resepKeIsian, ringkasResep } from '../bom/ResepKainEditor';

const SLR = { material_id: 'f-slr', code: 'KN-SLR-CRM', role: 'Utama', unit: 'kg' };
const K24 = { material_id: 'f-k24', code: 'KN-K24-CRM', role: 'Kerah', unit: 'kg' };

describe('resep kain di Order Cutting', () => {
  it('menjumlah kebutuhan per kain dari semua hasil', () => {
    const rows = kebutuhanResep([
      [{ ...SLR, qty_total: 35 }, { ...K24, qty_total: 5 }],
      [{ ...SLR, qty_total: 17.5 }, { ...K24, qty_total: 0 }],
      [],
    ]);
    expect(rows.map((r) => [r.code, r.qty, r.unknown, r.roles.join()])).toEqual([
      ['KN-SLR-CRM', 52.5, false, 'Utama'],
      ['KN-K24-CRM', 5, true, 'Kerah'],
    ]);
  });

  it('memilih gulungan FIFO sampai cukup', () => {
    const items = [{ id: 'r1', remaining: 20 }, { id: 'r2', remaining: 0 }, { id: 'r3', remaining: 25 }, { id: 'r4', remaining: 30 }];
    expect(pilihGulunganFifo(items, 40)).toEqual(['r1', 'r3']);
    expect(pilihGulunganFifo(items, 20)).toEqual(['r1']);
    expect(pilihGulunganFifo(items, 0)).toEqual([]);
    expect(pilihGulunganFifo(items, 999)).toEqual(['r1', 'r3', 'r4']);
  });

  it('hasil tanpa resep dianggap memakai semua kain', () => {
    expect(pakaiKain([], 'f-k24')).toBe(true);
    expect(pakaiKain([SLR], 'f-k24')).toBe(false);
    expect(pakaiKain([SLR, K24], 'f-k24')).toBe(true);
  });

  it('editor resep: angka kosong tetap kosong dan ringkasan terbaca', () => {
    const isian = resepKeIsian([{ ...SLR, qty_per_pcs: 0.35 }, { ...K24, qty_per_pcs: null }]);
    expect(isian.map((r) => r.qty_per_pcs)).toEqual(['0.35', '']);
    expect(isianKeResep(isian).map((r) => r.qty_per_pcs)).toEqual([0.35, null]);
    expect(ringkasResep(isian)).toBe('KN-SLR-CRM (Utama) 0,35 kg/pcs · KN-K24-CRM (Kerah)');
  });

  it('HPP per baris sama dengan aturan server (nilai tiap kain ke pemakainya)', () => {
    const S = { ...SLR, qty_per_pcs: 0.35 };
    const K = { ...K24, qty_per_pcs: 0.05 };
    // Ona (Rib Salur + Knit 24) 40 pcs, produk lain hanya Rib Salur 20 pcs
    expect(bagiNilaiPerKain({ 'f-slr': 1200, 'f-k24': 300 }, [{ qty: 40 }, { qty: 20 }], [[S, K], [S]]))
      .toEqual([1100, 400]);
    expect(hppPerBaris({ 'f-slr': 1200, 'f-k24': 300 }, [{ qty: 40 }, { qty: 20 }], [[S, K], [S]])).toEqual([27.5, 20]);
    // tanpa resep → null (layar memakai aturan rata lama)
    expect(hppPerBaris({ 'f-slr': 1200 }, [{ qty: 40 }, { qty: 20 }], [[], []])).toBeNull();
    // kain di luar resep mana pun tidak hilang
    const v = bagiNilaiPerKain({ 'f-lain': 90 }, [{ qty: 10 }, { qty: 20 }], [[S], [K]]);
    expect(v[0] + v[1]).toBeCloseTo(90);
  });
});
