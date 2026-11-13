// Dashboard Marketing — grafik selain penjualan (owner 13 Nov 2026: "grafik hanya sales saja padahal bisa ada ads,
// anggaran realisasi dll."). Yang dijaga: (1) angka grafik = angka jawaban endpoint sumbernya (tidak dihitung ulang),
// (2) keadaan kosong & tabel tetap tampil, (3) periode bulan Marketing 26–25 / minggu Senin + saringan toko dikirim ke
// semua sumber. Semua angka di bawah SINTETIS. Tanpa @testing-library/react — createRoot + act.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import MarketingDashboard from '../../MarketingDashboard';
import { rentangPreset } from '../../PeriodSelector';
import {
  adaNilai, barisAnggaran, barisKreator, klasifikasiPeriode, labelSaluranIklan, pesanGagal, rapikanHarian, spec,
} from '../dashboardGrafikData';
import { seninDari, todayWIB } from '@/lib/waktu';

jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() } }));
jest.mock('axios', () => ({ __esModule: true, default: { interceptors: { request: { use: jest.fn(), eject: jest.fn() } } } }));
// Recharts tidak bisa mengukur di jsdom — grafik diganti tiruan yang menuliskan spesifikasinya apa adanya.
jest.mock('../../asisten/GrafikAsisten', () => {
  const R = require('react');
  return { __esModule: true, default: ({ spec: s, testId }) => R.createElement('pre', { 'data-testid': testId }, JSON.stringify(s)) };
});

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// ── fungsi murni ──────────────────────────────────────────────────────────────────────────────
describe('periode bulan Marketing 26–25 & minggu Senin', () => {
  const kamis = new Date('2026-11-12T03:00:00Z');        // Kamis 12 Nov 2026 WIB
  const tgl26 = new Date('2026-11-26T03:00:00Z');        // 26 Nov = bulan Desember

  test('pilihan cepat', () => {
    expect(rentangPreset('bulan', kamis)).toEqual({ date_from: '2026-10-26', date_to: '2026-11-12' });
    expect(rentangPreset('bulan-lalu', kamis)).toEqual({ date_from: '2026-09-26', date_to: '2026-10-25' });
    expect(rentangPreset('bulan', tgl26)).toEqual({ date_from: '2026-11-26', date_to: '2026-11-26' });
    expect(rentangPreset('minggu', kamis)).toEqual({ date_from: '2026-11-09', date_to: '2026-11-12' });
    expect(rentangPreset('minggu-lalu', kamis)).toEqual({ date_from: '2026-11-02', date_to: '2026-11-08' });
    expect(rentangPreset('7', kamis)).toEqual({ date_from: '2026-11-06', date_to: '2026-11-12' });
  });

  test('Senin dari tanggal mana pun', () => {
    expect(seninDari('2026-11-09')).toBe('2026-11-09');
    expect(seninDari('2026-11-15')).toBe('2026-11-09');   // Minggu
    expect(seninDari('2026-11-01')).toBe('2026-10-26');
  });

  test('jenis periode', () => {
    const hari = '2026-11-12';
    expect(klasifikasiPeriode({ date_from: '2026-10-26', date_to: '2026-11-12' }, hari)).toEqual({ jenis: 'bulan', bulan: '2026-11', minggu: null });
    expect(klasifikasiPeriode({ date_from: '2026-09-26', date_to: '2026-10-25' }, hari)).toEqual({ jenis: 'bulan', bulan: '2026-10', minggu: null });
    expect(klasifikasiPeriode({ date_from: '2026-11-09', date_to: '2026-11-12' }, hari)).toEqual({ jenis: 'minggu', bulan: '2026-11', minggu: '2026-11-09' });
    expect(klasifikasiPeriode({ date_from: '2026-11-02', date_to: '2026-11-08' }, hari)).toEqual({ jenis: 'minggu', bulan: '2026-11', minggu: '2026-11-02' });
    // minggu yang memotong tanggal 25: angka bulanan ikut bulan tempat minggunya berakhir
    expect(klasifikasiPeriode({ date_from: '2026-11-23', date_to: '2026-11-29' }, hari).bulan).toBe('2026-12');
    expect(klasifikasiPeriode({ date_from: '2026-11-01', date_to: '2026-11-12' }, hari)).toEqual({ jenis: 'rentang', bulan: '2026-11', minggu: null });
    expect(klasifikasiPeriode({ date_from: '2026-10-14', date_to: '2026-11-12' }, hari).jenis).toBe('rentang');
  });
});

describe('penyusun grafik tidak mengubah total', () => {
  test('≤ 31 hari per hari; lebih → per minggu Senin, total tetap', () => {
    const harian = Array.from({ length: 45 }, (_, i) => {
      const d = new Date(Date.UTC(2026, 8, 26 + i));
      return { date: d.toISOString().slice(0, 10), revenue: 1000 + i, revenue_live: i % 3 ? 0 : 50 };
    });
    const pendek = rapikanHarian(harian.slice(0, 31), ['revenue']);
    expect(pendek.satuan).toBe('hari');
    expect(pendek.baris).toHaveLength(31);
    const r = rapikanHarian(harian, ['revenue', 'revenue_live']);
    expect(r.satuan).toBe('minggu');
    expect(r.baris.length).toBeLessThanOrEqual(31);
    const jumlah = (rows, k) => rows.reduce((s, x) => s + x[k], 0);
    expect(jumlah(r.baris, 'revenue')).toBe(jumlah(harian, 'revenue'));
    expect(jumlah(r.baris, 'revenue_live')).toBe(jumlah(harian, 'revenue_live'));
    expect(r.baris[0].key).toBe(seninDari('2026-09-26'));
  });

  test('grafik semua nol = keadaan kosong', () => {
    expect(adaNilai(spec('garis', [{ label: 'a', x: 0 }], [{ kunci: 'x', nama: 'X' }]))).toBe(false);
    expect(adaNilai(spec('garis', [{ label: 'a', x: 5 }], [{ kunci: 'x', nama: 'X' }]))).toBe(true);
    expect(adaNilai(spec('garis', [], [{ kunci: 'x', nama: 'X' }]))).toBe(false);
  });

  test('anggaran dari siklus (plan) maupun ringkasan mingguan (budget)', () => {
    const a = barisAnggaran([{ category: 'diskon', plan: 0, spend: 20, remaining: -20, mode: 'auto' },
      { category: 'ads', plan: 100, spend: 40, remaining: 60, used_pct: 40, mode: 'auto' }]);
    expect(a.map((r) => r.label)).toEqual(['Iklan', 'Diskon / promo']);       // urutan kategori baku
    expect(a[1].used_pct).toBeNull();                                            // tanpa rencana = "—", bukan 0%
    expect(barisAnggaran([{ category: 'sample', budget: 50, spend: 10, remaining: 40, used_pct: 20 }])[0])
      .toMatchObject({ label: 'Sampel', plan: 50, spend: 10, used_pct: 20 });
  });

  test('kreator disaring toko seperti tab Target KOL', () => {
    const cs = [
      { creator_id: 'k1', creator_name: 'A', accounts: [{ id: 'a1', name: 'T1' }], actual: { revenue: 5 } },
      { creator_id: 'k2', creator_name: 'B', accounts: [{ id: 'a2', name: 'T2' }], actual: { revenue: 9 } },
    ];
    expect(barisKreator(cs, '').map((r) => r.id)).toEqual(['k2', 'k1']);
    expect(barisKreator(cs, 'a1').map((r) => r.id)).toEqual(['k1']);
  });

  test('label saluran & pesan izin tanpa istilah program', () => {
    expect(labelSaluranIklan('shopee_ads_cpc')).toBe('Iklan Shopee (CPC)');
    expect(labelSaluranIklan('kanal_baru_x')).toBe('Kanal baru x');
    expect(pesanGagal(403, 'modul "Uji"')).toMatch(/centang "Lihat" pada modul "Uji"/);
    expect(pesanGagal(403, 'x', 'Toko ini tidak di-assign ke Anda')).toBe('Toko ini tidak di-assign ke Anda');
    expect(pesanGagal(500, 'x')).toMatch(/kode 500/);
  });
});

// ── render dengan endpoint tiruan ─────────────────────────────────────────────────────────────
let root;
let container;
const q = (id) => document.querySelector(`[data-testid="${id}"]`);
const semua = (id) => document.querySelectorAll(`[data-testid="${id}"]`);
const tunggu = async (fn) => {
  let galat;
  for (let i = 0; i < 80; i += 1) {
    try { if (fn()) return; } catch (e) { galat = e; }
    await act(async () => { await new Promise((r) => setTimeout(r, 15)); });
  }
  throw galat || new Error('waktu habis');
};
const klik = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); });
};
const specDari = (id) => JSON.parse(q(id).textContent);
const jumlah = (arr) => arr.reduce((s, v) => s + Number(v || 0), 0);

const kat = (category, plan, spend, mode = 'auto') => ({
  category, plan, spend, manual: mode === 'manual' ? spend : 0, auto: mode === 'auto' ? spend : 0, remaining: plan - spend,
  used_pct: plan > 0 ? Math.round(spend / plan * 10000) / 100 : (spend ? 100 : 0), status: spend > plan ? 'over' : 'under', mode,
});
const KATEGORI_KOSONG = ['ads', 'kol', 'komisi', 'livehost', 'sample', 'diskon'].map((c) => kat(c, 0, 0, c === 'sample' ? 'manual' : 'auto'));

const AKUN = [
  { id: 'a1', account_name: 'Toko TikTok', account_code: 'TTK-01', platform: 'tiktok', health_score: null },
  { id: 'a2', account_name: 'Toko Shopee', account_code: 'SHP-01', platform: 'shopee', health_score: 82 },
];
const OV = {
  summary: { total_accounts: 2, active_accounts: 2, total_revenue: 13_727_142, total_revenue_live: 789_427, total_orders: 142, avg_order_value: 96_670 },
  top_account: { account_id: 'a1', account_name: 'Toko TikTok', revenue: 8_855_287 },
  daily: [
    { date: '2026-10-28', revenue: 2_000_000, revenue_live: 500_000, orders: 20 },
    { date: '2026-11-01', revenue: 6_855_287, revenue_live: 289_427, orders: 72 },
    { date: '2026-11-05', revenue: 4_871_855, revenue_live: 0, orders: 50 },
  ],
  per_account: [
    { account_id: 'a1', account_name: 'Toko TikTok', revenue: 8_855_287, revenue_live: 789_427, orders: 92 },
    { account_id: 'a2', account_name: 'Toko Shopee', revenue: 4_871_855, revenue_live: 0, orders: 50 },
  ],
  live: { sessions: 3, orders: 7, recorded_revenue: 900_000 },
};
const SIKLUS = {
  period: '2026-11', progress: { days_elapsed: 20, days_total: 31 },
  rows: [
    { account: { id: 'a1', account_name: 'Toko TikTok', account_code: 'TTK-01' }, target: { revenue: 10_000_000 },
      actual: { revenue: 8_855_287 }, achievement: { revenue_pct: 88.55, pace_pct: 64.52, status: 'on_track' } },
    { account: { id: 'a2', account_name: 'Toko Shopee', account_code: 'SHP-01' }, target: { revenue: 0 },
      actual: { revenue: 4_871_855 }, achievement: { revenue_pct: 0, pace_pct: 64.52, status: 'no_target' } },
  ],
  totals: {
    accounts: 2, accounts_with_target: 1, target_revenue: 10_000_000, revenue: 13_727_142, revenue_pct: 88.6, pace_pct: 64.52,
    total_plan: 1_500_000, total_spend: 640_000, total_remaining: 860_000, total_used_pct: 42.67, roas: 21.45,
    roi_reliable: false, hpp_coverage_pct: 0, flags_red: 0, flags_yellow: 0,
    budget_categories: [kat('ads', 1_000_000, 390_000), kat('kol', 500_000, 0), kat('komisi', 0, 0), kat('livehost', 0, 250_000),
      kat('sample', 0, 0, 'manual'), kat('diskon', 0, 0)],
  },
  attention: [],
};
const IKLAN = {
  success: true,
  data: { total_spend: 140_000, total_revenue: 390_000, overall_roas: 2.79, dibagi_rata: 0,
    by_platform: { meta_ads: { spend: 100_000, revenue: 250_000, roas: 2.5, campaigns: 1 },
      tiktok_ads: { spend: 40_000, revenue: 140_000, roas: 3.5, campaigns: 1 } } },
};
const TREN = { success: true, data: { trend: [{ date: '2026-11-01', spend: 100_000, revenue: 250_000 }, { date: '2026-11-03', spend: 40_000, revenue: 140_000 }] } };
const KREATOR = {
  creators: [
    { creator_id: 'k1', creator_name: 'Kreator A', creator_code: 'KOL-1', accounts: [{ id: 'a1', name: 'Toko TikTok' }],
      target: { revenue: 5_000_000 }, actual: { revenue: 1_200_000, sessions: 4 }, achievement: { revenue_pct: 24, revenue_status: 'behind' } },
    { creator_id: 'k2', creator_name: 'Kreator B', creator_code: 'KOL-2', accounts: [{ id: 'a2', name: 'Toko Shopee' }],
      target: { revenue: null }, actual: { revenue: 0, sessions: 0 }, achievement: { revenue_pct: null, revenue_status: 'no_target' } },
  ],
};
const MINGGUAN = {
  categories: [{ category: 'ads', budget: 200_000, spend: 40_000, remaining: 160_000, used_pct: 20, mode: 'auto' },
    ...KATEGORI_KOSONG.slice(1).map((c) => ({ ...c, budget: 0 }))],
  total_budget: 200_000, total_spend: 40_000,
};

function pasangFetch(timpa = {}) {
  const dasar = {
    '/dashboard/overview': OV, '/marketing/accounts': AKUN, '/cycle/overview': SIKLUS, '/ads/summary': IKLAN,
    '/ads/performance-trend': TREN, '/budget/period-settings': { ok: true, settings: { period_mode: 'weekly', period_days: 7 } },
    '/budget/summary': MINGGUAN, '/targets/creator/monthly-summary': KREATOR,
  };
  const rute = { ...dasar, ...timpa };
  global.fetch = jest.fn((url) => {
    const kunci = Object.keys(rute).find((k) => String(url).includes(k));
    const isi = rute[kunci];
    if (isi && isi.__status) return Promise.resolve({ ok: false, status: isi.__status, json: async () => ({ detail: isi.detail }) });
    return Promise.resolve({ ok: true, status: 200, json: async () => (isi === undefined ? {} : isi) });
  });
}
const dipanggil = (bagian) => global.fetch.mock.calls.map((c) => String(c[0])).filter((u) => u.includes(bagian));

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); document.body.innerHTML = ''; delete global.fetch; });

async function tampil() {
  await act(async () => { root.render(<MarketingDashboard token="t" onNavigate={jest.fn()} />); });
  await tunggu(() => q('revenue-chart') && q('dash-iklan-grafik') && q('dash-anggaran-grafik') && q('dash-target-grafik')
    && q('dash-live-grafik') && q('dash-kreator-grafik'));
}

describe('Dashboard Marketing — grafik dari endpoint sumber', () => {
  test('angka tiap grafik = angka jawaban endpoint layar sumbernya', async () => {
    pasangFetch();
    await tampil();
    const tren = specDari('revenue-chart');
    expect(tren.seri.map((s) => s.nama)).toEqual(['Omzet total', 'Omzet live']);
    expect(jumlah(tren.seri[0].nilai)).toBe(OV.summary.total_revenue);               // = kartu Omzet
    expect(jumlah(tren.seri[1].nilai)).toBe(OV.summary.total_revenue_live);          // = "Termasuk live"

    const iklan = specDari('dash-iklan-grafik');
    expect(jumlah(iklan.seri[0].nilai)).toBe(IKLAN.data.total_spend);                // = kartu Performa iklan
    expect(jumlah(iklan.seri[1].nilai)).toBe(IKLAN.data.total_revenue);
    expect(q('dash-iklan-ringkasan').textContent).toMatch(/140\.000/);
    expect(q('dash-iklan-ringkasan').textContent).toMatch(/2,79×/);
    expect(semua('dash-iklan-saluran-baris')).toHaveLength(2);

    const ang = specDari('dash-anggaran-grafik');
    expect(ang.x).toEqual(['Iklan', 'KOL / kreator', 'Komisi kreator', 'Host live', 'Sampel', 'Diskon / promo']);
    expect(ang.seri[0].nilai).toEqual(SIKLUS.totals.budget_categories.map((c) => c.plan));
    expect(ang.seri[1].nilai).toEqual(SIKLUS.totals.budget_categories.map((c) => c.spend));
    expect(jumlah(ang.seri[1].nilai)).toBe(SIKLUS.totals.total_spend);
    expect(semua('dash-anggaran-tabel-baris')).toHaveLength(6);

    const tgt = specDari('dash-target-grafik');
    expect(tgt.x).toEqual(['Toko TikTok', 'Toko Shopee']);
    expect(tgt.seri[0].nilai).toEqual([10_000_000, 0]);
    expect(tgt.seri[1].nilai).toEqual([8_855_287, 4_871_855]);
    expect(q('dash-target-ringkasan').textContent).toMatch(/88,6%/);

    const live = specDari('dash-live-grafik');
    expect(live.x).toEqual(['Toko TikTok']);
    expect(jumlah(live.seri[0].nilai)).toBe(OV.summary.total_revenue_live);

    const kr = specDari('dash-kreator-grafik');
    expect(kr.x).toEqual(['Kreator A']);                                              // kreator tanpa omzet/target tidak digambar
    expect(semua('dash-kreator-tabel-baris')).toHaveLength(2);                       // …tetapi tetap di tabel

    // satu permintaan siklus untuk kartu siklus + grafik anggaran + grafik target
    expect(dipanggil('/cycle/overview')).toHaveLength(1);
    expect(q('marketing-cycle-strip')).not.toBeNull();
    // tidak lagi menjumlah per toko di browser
    expect(dipanggil('/sales?')).toHaveLength(0);
  });

  test('data kosong: kotak grafik & tabel tetap tampil dengan keadaan kosong', async () => {
    pasangFetch({
      '/dashboard/overview': { summary: { total_accounts: 0, active_accounts: 0, total_revenue: 0, total_revenue_live: 0, total_orders: 0 },
        top_account: null, daily: [], per_account: [], live: { sessions: 0, orders: 0, recorded_revenue: 0 } },
      '/marketing/accounts': [],
      '/cycle/overview': { period: '2026-11', progress: {}, rows: [], attention: [],
        totals: { budget_categories: KATEGORI_KOSONG, total_plan: 0, total_spend: 0, accounts: 0 } },
      '/ads/summary': { success: true, data: { total_spend: 0, total_revenue: 0, overall_roas: 0, by_platform: {} } },
      '/ads/performance-trend': { success: true, data: { trend: [] } },
      '/targets/creator/monthly-summary': { creators: [] },
    });
    await act(async () => { root.render(<MarketingDashboard token="t" onNavigate={jest.fn()} />); });
    await tunggu(() => q('revenue-chart-kosong') && q('dash-iklan-grafik-kosong') && q('dash-anggaran-grafik-kosong')
      && q('dash-target-grafik-kosong') && q('dash-live-grafik-kosong') && q('dash-kreator-grafik-kosong'));
    for (const id of ['dash-iklan-saluran-kosong', 'dash-target-tabel-kosong', 'dash-kreator-tabel-kosong', 'dashboard-accounts-table-kosong']) {
      expect(q(id)).not.toBeNull();
    }
    expect(semua('dash-anggaran-tabel-baris')).toHaveLength(6);                      // 6 kategori tetap terlihat
    expect(q('dash-iklan-ringkasan')).toBeNull();                                     // tanpa biaya: tidak ada "ROAS 0×"
  });

  test('tanpa izin iklan: pesan centang modul, bagian lain tetap jalan', async () => {
    pasangFetch({ '/ads/summary': { __status: 403 }, '/ads/performance-trend': { __status: 403 } });
    await tampil().catch(() => {});
    await tunggu(() => q('dash-iklan-grafik-galat'));
    expect(q('dash-iklan-grafik-galat').textContent).toMatch(/Kalender Konten, Diskon, Iklan & Peluncuran/);
    expect(q('dash-iklan-saluran-kosong').textContent).toMatch(/tidak bisa dimuat/);
    expect(q('revenue-chart')).not.toBeNull();
    expect(q('dash-anggaran-grafik')).not.toBeNull();
  });

  test('saringan toko dikirim ke semua sumber', async () => {
    pasangFetch();
    await tampil();
    await klik(q('dashboard-toko-filter-trigger'));
    await tunggu(() => q('dashboard-toko-filter-option-a2'));
    await klik(q('dashboard-toko-filter-option-a2'));
    await tunggu(() => dipanggil('/cycle/overview').some((u) => u.includes('account_id=a2')));
    await tunggu(() => dipanggil('/dashboard/overview').some((u) => u.includes('account_id=a2'))
      && dipanggil('/ads/summary').some((u) => u.includes('account_id=a2'))
      && dipanggil('/ads/performance-trend').some((u) => u.includes('account_id=a2')));
    await tunggu(() => q('dash-kreator-grafik-kosong'));                              // Kreator B tanpa omzet/target
    expect(semua('dash-kreator-tabel-baris')).toHaveLength(1);
    expect(semua('dashboard-accounts-table-baris')).toHaveLength(1);
  });

  test('minggu ini: anggaran mingguan Senin dari ringkasan anggaran semua toko', async () => {
    // Senin yang jatuh tanggal 26 = awal bulan Marketing juga → dibaca "bulan"; uji ini tidak berlaku hari itu.
    if (klasifikasiPeriode(rentangPreset('minggu'), todayWIB()).jenis !== 'minggu') return;
    pasangFetch();
    await tampil();
    expect(dipanggil('/budget/summary')).toHaveLength(0);                             // bulan: dari siklus
    await klik(q('period-preset-trigger'));
    await tunggu(() => q('period-preset-option-minggu'));
    await klik(q('period-preset-option-minggu'));
    const senin = rentangPreset('minggu').date_from;
    await tunggu(() => dipanggil('/budget/summary').some((u) => u.includes(`period=${senin}`) && !u.includes('account_id')));
    await tunggu(() => specDari('dash-anggaran-grafik').seri[0].nilai[0] === 200_000);
    expect(q('dash-anggaran').textContent).toMatch(/minggu/);
    expect(dipanggil('/dashboard/overview').some((u) => u.includes(`date_from=${senin}`))).toBe(true);
  });
});
