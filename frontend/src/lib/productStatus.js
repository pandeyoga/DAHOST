/**
 * Status produk per varian SKU (keputusan owner 6 Nov 2026). Kode = kontrak backend
 * `core/product_status.py` (`rahaza_model_variants.product_status`); kosong = belum diisi.
 * Warna hanya token (PANDUAN_UI G8) lewat `tone` StatusBadge.
 */
export const PRODUCT_STATUS_OPTIONS = [
  { value: 'new', label: 'Baru', tone: 'primary' },
  { value: 'best_seller', label: 'Best Seller', tone: 'success' },
  { value: 'slow', label: 'Slow', tone: 'warning' },
  { value: 'dead', label: 'Dead', tone: 'danger' },
  { value: 'stop', label: 'Stop', tone: 'muted' },
];

export const PRODUCT_STATUS_UNSET = 'belum_diisi';
export const PRODUCT_STATUS_MIXED = 'campuran';

const BY_CODE = Object.fromEntries(PRODUCT_STATUS_OPTIONS.map((o) => [o.value, o]));

export function productStatusLabel(code) {
  if (!code) return 'Belum diisi';
  if (code === PRODUCT_STATUS_MIXED) return 'Campuran';
  return BY_CODE[code]?.label || code;
}

export function productStatusTone(code) {
  if (!code || code === PRODUCT_STATUS_MIXED) return 'default';
  return BY_CODE[code]?.tone || 'default';
}
