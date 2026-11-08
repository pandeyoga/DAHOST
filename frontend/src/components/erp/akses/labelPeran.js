/**
 * Nama peran untuk layar (Standar UI/UX v2, 8 Nov 2026): kode peran seperti `admin_gudang` / `hr_manager`
 * tidak ditampilkan ke staf. Urutan sumber:
 *   1. keterangan peran dari data (`roles.description`, mis. "Admin Gudang") bila ada;
 *   2. terjemahan kode kata per kata ("manager_keuangan" → "Manajer keuangan").
 * Kode asli tetap dipakai untuk menyimpan; fungsi ini hanya untuk tampilan.
 */
const KHUSUS = {
  superadmin: 'Superadmin', super_admin: 'Superadmin', admin: 'Admin', owner: 'Owner/Pemilik', ceo: 'CEO', cfo: 'CFO',
  dept_head: 'Kepala departemen', director: 'Direktur', hr: 'Tim SDM', cs_staff: 'Customer service', ppic: 'PPIC',
  vendor: 'Vendor', klien_maklon: 'Klien maklon', operator: 'Operator lantai',
};
const KATA = {
  admin: 'admin', manager: 'manajer', hr: 'SDM', keuangan: 'keuangan', marketing: 'marketing', pengadaan: 'pengadaan',
  produksi: 'produksi', gudang: 'gudang', aksesoris: 'aksesoris', maklon: 'maklon', sales: 'penjualan', staff: 'staf',
  cs: 'CS', rnd: 'R&D', kol: 'KOL', pic: 'PIC', toko: 'toko', operator: 'operator', cuting: 'cutting', cutting: 'cutting',
  spv: 'supervisor', supervisor: 'supervisor', tim: 'tim', packing: 'packing', purchasing: 'pembelian', accounting: 'akuntansi',
  klien: 'klien', head: 'kepala', dept: 'departemen', qc: 'QC', ppic: 'PPIC', it: 'TI', viewer: 'pemantau',
};

export function labelKodePeran(kode) {
  const k = String(kode || '').trim();
  if (!k) return '—';
  if (KHUSUS[k]) return KHUSUS[k];
  const kata = k.toLowerCase().split(/[_\-.\s]+/).filter(Boolean).map((w) => KATA[w] || w);
  const s = kata.join(' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** `deskripsi` = keterangan peran dari data (opsional). */
const RAPIKAN = [[/\(View Only\)/gi, '(lihat saja)'], [/\(Legacy\)/gi, '(lama)']];

export function labelPeran(kode, deskripsi) {
  const d = RAPIKAN.reduce((t, [re, ke]) => t.replace(re, ke), String(deskripsi || '').trim());
  return d || labelKodePeran(kode);
}

/** Peta kode → label dari daftar peran API (`[{name, description}]`). */
export function petaLabelPeran(daftar) {
  const peta = {};
  (Array.isArray(daftar) ? daftar : []).forEach((r) => { if (r?.name) peta[r.name] = labelPeran(r.name, r.description); });
  return (kode) => peta[kode] || labelKodePeran(kode);
}
