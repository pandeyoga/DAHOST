/**
 * dashboardGrafikData — logika murni grafik Dashboard Marketing (owner 13 Nov 2026: "grafik hanya sales saja padahal
 * bisa ada ads, anggaran realisasi dll."). Tanpa React/Recharts supaya bisa diuji sendiri.
 *
 * Aturan: layar TIDAK menghitung angka bisnis sendiri. Semua jumlah datang dari endpoint layar sumbernya
 * (`/dashboard/overview`, `/ads/summary` + `/ads/performance-trend`, `/cycle/overview`, `/budget/summary`,
 * `/targets/creator/monthly-summary`). Berkas ini hanya MEMBENTUK spesifikasi grafik (`GrafikAsisten`) dari angka itu;
 * satu-satunya penjumlahan adalah pengelompokan hari → minggu/bulan bila titiknya > 31, yang tidak mengubah total.
 */
import { addDaysISO, bulanMarketingDari, labelRentangBulanMarketing, rentangBulanMarketing, seninDari } from '@/lib/waktu';

export const MAKS_TITIK = 31;   // sama dengan batas `GrafikAsisten` (Kontrak B)

/** Kategori anggaran — urutan & label sama dengan Target & Anggaran › Anggaran (`BudgetAllocationTab`). */
export const KATEGORI_ANGGARAN = [
  { key: 'ads', label: 'Iklan' },
  { key: 'kol', label: 'KOL / kreator' },
  { key: 'komisi', label: 'Komisi kreator' },
  { key: 'livehost', label: 'Host live' },
  { key: 'sample', label: 'Sampel' },
  { key: 'diskon', label: 'Diskon / promo' },
];
const LABEL_KATEGORI = Object.fromEntries(KATEGORI_ANGGARAN.map((k) => [k.key, k.label]));
export const labelKategori = (k) => LABEL_KATEGORI[k] || 'Lainnya';

const BLN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const BULAN_PANJANG = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September',
  'Oktober', 'November', 'Desember'];

/** '2026-08-11' → '11 Agu'. */
export const tglPendek = (iso) => {
  const [, m, d] = String(iso || '').split('-').map(Number);
  return m && d ? `${d} ${BLN[m - 1]}` : String(iso || '');
};

/** '2026-11' → 'November 2026'. */
export const namaBulan = (ym) => {
  const y = Number(String(ym).slice(0, 4)); const m = Number(String(ym).slice(5, 7));
  return m ? `${BULAN_PANJANG[m - 1]} ${y}` : String(ym || '');
};

/** Bulan Marketing 'YYYY-MM' → 'November 2026 (26 Okt – 25 Nov 2026)'. */
export const labelBulanMarketing = (ym) => {
  const y = Number(String(ym).slice(0, 4)); const m = Number(String(ym).slice(5, 7));
  return `${namaBulan(ym)} (${labelRentangBulanMarketing(y, m)})`;
};

/** Senin 'YYYY-MM-DD' → '10 Agu – 16 Agu 2026'. */
export const labelMinggu = (senin) => {
  const akhir = addDaysISO(senin, 6);
  return `${tglPendek(senin)} – ${tglPendek(akhir)} ${akhir.slice(0, 4)}`;
};

/**
 * Jenis periode yang dipilih di layar.
 *   • 'bulan'   = tepat satu bulan Marketing (26–25), atau awal bulan Marketing s/d hari ini;
 *   • 'minggu'  = tepat Senin–Minggu, atau Senin s/d hari ini;
 *   • 'rentang' = lainnya (hari ini, 7/30/90 hari, pilih tanggal).
 * `bulan` selalu = bulan Marketing tempat tanggal akhir berada — dipakai angka RESMI bulanan (target, anggaran
 * bulanan, KOL), sama dengan kartu siklus yang sudah ada.
 */
export function klasifikasiPeriode(value, today) {
  const { date_from: dari, date_to: sampai } = value || {};
  const bulan = bulanMarketingDari(sampai);
  if (!dari || !sampai) return { jenis: 'rentang', bulan, minggu: null };
  const dalam = (t, a, b) => !!t && t >= a && t <= b;
  const r = rentangBulanMarketing(bulan);
  if (dari === r.dari && (sampai === r.sampai || (sampai === today && dalam(today, r.dari, r.sampai)))) {
    return { jenis: 'bulan', bulan, minggu: null };
  }
  const senin = seninDari(dari);
  const minggu = addDaysISO(senin, 6);
  if (dari === senin && (sampai === minggu || (sampai === today && dalam(today, senin, minggu)))) {
    return { jenis: 'minggu', bulan, minggu: senin };
  }
  return { jenis: 'rentang', bulan, minggu: null };
}

/**
 * Baris harian [{date, …angka}] → titik grafik. ≤ 31 hari: per hari. Lebih: dijumlah per minggu (Senin), lalu per
 * bulan Marketing bila masih > 31 titik. Total tidak berubah — hanya pengelompokan.
 */
export function rapikanHarian(rows, kunci) {
  const urut = [...(rows || [])].filter((r) => r && r.date).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const kelompok = (keyOf, labelOf) => {
    const map = new Map();
    urut.forEach((r) => {
      const k = keyOf(r.date);
      if (!map.has(k)) map.set(k, { key: k, label: labelOf(k), ...Object.fromEntries(kunci.map((f) => [f, 0])) });
      const b = map.get(k);
      kunci.forEach((f) => { b[f] += Number(r[f] || 0); });
    });
    return [...map.values()];
  };
  if (urut.length <= MAKS_TITIK) {
    return { satuan: 'hari', baris: urut.map((r) => ({ key: r.date, label: tglPendek(r.date), ...Object.fromEntries(kunci.map((f) => [f, Number(r[f] || 0)])) })) };
  }
  const mingguan = kelompok(seninDari, (k) => `Minggu ${tglPendek(k)}`);
  if (mingguan.length <= MAKS_TITIK) return { satuan: 'minggu', baris: mingguan };
  return { satuan: 'bulan', baris: kelompok(bulanMarketingDari, (k) => namaBulan(k)) };
}

export const CATATAN_KELOMPOK = {
  hari: '',
  minggu: 'Dijumlah per minggu (Senin–Minggu) karena rentang lebih dari 31 hari.',
  bulan: 'Dijumlah per bulan Marketing (26–25) karena rentangnya panjang.',
};

/** Spesifikasi `GrafikAsisten` dari baris + daftar seri [{kunci, nama}]. */
export function spec(jenis, baris, seri, { satuan = 'Rp', catatan = '', label = 'label' } = {}) {
  return {
    jenis, satuan, catatan,
    x: (baris || []).map((b) => String(b[label] ?? '')),
    seri: seri.map((s) => ({ nama: s.nama, nilai: (baris || []).map((b) => Number(b[s.kunci] || 0)) })),
  };
}

/** Ada angka bukan nol di grafik? (semua nol = tampilkan keadaan kosong, bukan garis datar di 0). */
export const adaNilai = (sp) => !!sp && (sp.seri || []).some((s) => (s.nilai || []).some((v) => Number(v) !== 0 && Number.isFinite(Number(v))));

/** Anggaran per kategori dari siklus (`plan`) atau ringkasan anggaran (`budget`) → bentuk baku layar. */
export function barisAnggaran(categories) {
  const per = Object.fromEntries((categories || []).map((c) => [c.category, c]));
  return KATEGORI_ANGGARAN.filter((k) => per[k.key]).map((k) => {
    const c = per[k.key];
    const plan = Number(c.plan ?? c.budget ?? 0);
    const spend = Number(c.spend || 0);
    return {
      category: k.key, label: k.label, plan, spend,
      remaining: Number(c.remaining ?? c.variance ?? plan - spend),
      used_pct: plan > 0 ? Number(c.used_pct || 0) : null,
      mode: c.mode,
    };
  });
}

/** Status capaian siklus (`core.marketing_cycle.cycle_summary`) → label & nada. */
export const STATUS_CAPAIAN = {
  on_track: { label: 'Sesuai laju', tone: 'success' },
  warning: { label: 'Perlu perhatian', tone: 'warning' },
  behind: { label: 'Tertinggal', tone: 'danger' },
  no_target: { label: 'Belum ada target', tone: 'muted' },
};

/** Baris siklus (`/cycle/overview` rows) → pencapaian target per toko. */
export function barisTarget(rows) {
  return (rows || []).map((r) => {
    const target = Number(r?.target?.revenue || 0);
    return {
      account_id: r?.account?.id,
      toko: r?.account?.account_name || r?.account?.account_code || '—',
      kode: r?.account?.account_code || '',
      target,
      omzet: Number(r?.actual?.revenue || 0),
      capaian: target > 0 ? Number(r?.achievement?.revenue_pct || 0) : null,
      laju: Number(r?.achievement?.pace_pct || 0),
      status: r?.achievement?.status || 'no_target',
    };
  });
}

/** Kreator (`/targets/creator/monthly-summary`) → baris, disaring toko seperti tab Target KOL, urut omzet. */
export function barisKreator(creators, tokoId) {
  return (creators || [])
    .filter((c) => !tokoId || (c.accounts || []).some((a) => a.id === tokoId))
    .map((c) => ({
      id: c.creator_id,
      nama: c.creator_name || c.creator_code || '—',
      kode: c.creator_code || '',
      toko: (c.accounts || []).map((a) => a.name).join(', '),
      omzet: Number(c?.actual?.revenue || 0),
      target: c?.target?.revenue == null ? null : Number(c.target.revenue),
      capaian: c?.achievement?.revenue_pct ?? null,
      sesi: Number(c?.actual?.sessions || 0),
      status: c?.achievement?.revenue_status || 'no_target',
    }))
    .sort((a, b) => b.omzet - a.omzet || a.nama.localeCompare(b.nama));
}

const SALURAN_IKLAN = {
  shopee_ads: 'Iklan Shopee', shopee_ads_cpc: 'Iklan Shopee (CPC)', tiktok_ads: 'Iklan TikTok', gmv_max: 'TikTok GMV Max',
  meta_ads: 'Meta (Facebook/Instagram)', google_ads: 'Google', affiliate: 'Afiliasi', lainnya: 'Lainnya',
  shopee: 'Shopee', tiktok: 'TikTok', meta: 'Meta', google: 'Google',
};
/** Kode saluran iklan → nama yang dipahami staf (tanpa garis bawah). */
export const labelSaluranIklan = (k) => {
  const s = String(k || '').toLowerCase();
  if (SALURAN_IKLAN[s]) return SALURAN_IKLAN[s];
  const t = s.replace(/[_-]+/g, ' ').trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : 'Lainnya';
};

/** Pesan gagal muat yang bisa ditindaklanjuti staf (403 = belum dicentang owner). */
export function pesanGagal(status, modul, detail) {
  if (status === 403) {
    return typeof detail === 'string' && detail
      ? detail
      : `Anda belum diberi izin melihat data ini. Minta owner mencentang "Lihat" pada ${modul} di Administrasi Sistem › Kontrol Akses › Peran & Hak Akses.`;
  }
  return `Data tidak bisa dimuat${status ? ` (kode ${status})` : ''}. Coba muat ulang.`;
}
