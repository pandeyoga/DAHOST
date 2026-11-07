/**
 * Saringan per portal untuk layar proses Produksi & Maklon (Tahap 9, keputusan 2 — tampilan identik,
 * data disaring per portal). Satu tempat untuk peta portal → jenis PO yang dikirim ke server sebagai
 * `?business_type=` (aturan server: `backend/core/po_portal_scope.py`).
 *   Portal Produksi → 'internal' · Portal Maklon → 'maklon' · portal lain (mis. Gudang) → null (tanpa saringan)
 */
export function portalBusinessType(portalId) {
  return portalId === 'maklon' ? 'maklon' : portalId === 'production' ? 'internal' : null;
}

/** '?business_type=…&k=v' (atau '') — parameter kosong dilewati. */
export function portalQuery(businessType, extra = {}) {
  const p = new URLSearchParams();
  if (businessType) p.set('business_type', businessType);
  Object.entries(extra).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : '';
}
