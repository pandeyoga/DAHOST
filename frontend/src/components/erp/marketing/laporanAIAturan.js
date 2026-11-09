/** Pilihan periode Laporan AI (pekan Senin–Minggu / bulan penuh) — tanpa React, dipakai layar & uji. */
const BLN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober',
  'November', 'Desember'];
const pad = (n) => String(n).padStart(2, '0');
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** 8 pekan terakhir yang sudah lewat (Senin–Minggu), terbaru dulu. */
export function pilihanPekan(hariIni = new Date(), n = 8) {
  const d = new Date(hariIni.getFullYear(), hariIni.getMonth(), hariIni.getDate());
  const geser = (d.getDay() + 6) % 7;            // 0 = Senin
  const seninIni = new Date(d); seninIni.setDate(d.getDate() - geser);
  const out = [];
  for (let i = 1; i <= n; i += 1) {
    const a = new Date(seninIni); a.setDate(seninIni.getDate() - 7 * i);
    const b = new Date(a); b.setDate(a.getDate() + 6);
    out.push({ dari: iso(a), sampai: iso(b),
      label: `${a.getDate()} ${BLN[a.getMonth()].slice(0, 3)} – ${b.getDate()} ${BLN[b.getMonth()].slice(0, 3)} ${b.getFullYear()}` });
  }
  return out;
}

/** 6 bulan terakhir yang sudah lewat, terbaru dulu. */
export function pilihanBulan(hariIni = new Date(), n = 6) {
  const out = [];
  for (let i = 1; i <= n; i += 1) {
    const a = new Date(hariIni.getFullYear(), hariIni.getMonth() - i, 1);
    const b = new Date(a.getFullYear(), a.getMonth() + 1, 0);
    out.push({ dari: iso(a), sampai: iso(b), label: `${BLN[a.getMonth()]} ${a.getFullYear()}` });
  }
  return out;
}

/** Kalimat anomali dari paket fakta (angka dari server, tanpa hitungan baru). */
export function kalimatAnomali(a, rp) {
  switch (a.jenis) {
    case 'omzet_harian':
      return `Omzet ${a.tanggal} ${a.arah} tajam: ${rp(a.omzet)} (rata-rata ${rp(a.rata)}).`;
    case 'toko_tanpa_data':
      return `${a.toko}: data hanya ${a.hari_ada_data} dari ${a.hari} hari.`;
    case 'batal_melonjak':
      return `Pesanan batal ${a.persen_batal}% (sebelumnya ${a.persen_batal_sebelumnya}%).`;
    case 'kampanye_rugi':
      return `Kampanye “${a.kampanye}” berbiaya ${rp(a.belanja)} dengan ROAS ${a.roas ?? '—'}.`;
    case 'selisih_setoran':
      return `Penjualan di laporan penghasilan ${rp(a.bruto_setoran)} vs omzet ${rp(a.omzet)} (selisih ${a.selisih_persen}%).`;
    default:
      return '';
  }
}
