/**
 * Label Indonesia + nada warna untuk status PO produksi (`production_pos.status`, routes/shared.PO_STATUSES).
 * Tahap 9: layar proses (Bahan, Tutup PO) menampilkan status PO tanpa kode Inggris (PANDUAN_UI G11).
 *   <StatusBadge status={po.status} label={poStatusLabel(po.status)} tone={poStatusTone(po.status)} />
 */
export const PO_STATUS_LABEL = {
  Draft: 'Draf',
  Confirmed: 'Dikonfirmasi',
  Distributed: 'Dikirim ke CMT',
  'In Production': 'Dalam produksi',
  'Production Complete': 'Produksi selesai',
  'Variance Review': 'Tinjau selisih',
  'Return Review': 'Tinjau retur',
  'Ready to Close': 'Siap ditutup',
  Completed: 'Selesai',
  Closed: 'Ditutup',
  'Closed Short': 'Ditutup kurang',
  Cancelled: 'Dibatalkan',
};
const PO_STATUS_TONE = {
  Draft: 'muted', Confirmed: 'primary', Distributed: 'primary', 'In Production': 'warning',
  'Production Complete': 'success', 'Variance Review': 'warning', 'Return Review': 'warning',
  'Ready to Close': 'primary', Completed: 'success', Closed: 'muted', 'Closed Short': 'warning', Cancelled: 'muted',
};

export const poStatusLabel = (s) => PO_STATUS_LABEL[s] || s || '—';
export const poStatusTone = (s) => PO_STATUS_TONE[s] || 'default';
