/**
 * Nama yang dibaca manusia untuk kode internal Keuangan (2026-11-04, audit Keuangan tahap 2).
 * Satu sumber untuk semua layar: dulu layar menampilkan kode mentah (`ap_payment`, `PARTIAL_PAID`,
 * `marketplace_settlement`) atau menerjemahkannya sendiri-sendiri.
 */

export const JOURNAL_SOURCE_LABELS = {
  manual: 'Jurnal manual',
  manual_journal: 'Jurnal manual',
  expense: 'Pengeluaran',
  expense_claim: 'Klaim karyawan',
  marketplace_settlement: 'Dana dilepas marketplace',
  platform_withdrawal: 'Penarikan saldo toko',
  ap_invoice: 'Tagihan pemasok',
  ap_payment: 'Pembayaran hutang',
  cmt_ap_invoice: 'Tagihan CMT',
  ar_invoice: 'Faktur penjualan',
  ar_payment: 'Pembayaran piutang',
  direct_sale: 'Nota penjualan',
  maklon_ar_invoice: 'Faktur maklon',
  maklon_advance_payment: 'Uang muka maklon',
  bank_transfer: 'Transfer antar rekening',
  bank_recon: 'Rekonsiliasi bank',
  payroll_finalize: 'Gaji',
  employee_loan_repayment_payroll: 'Potongan kasbon (gaji)',
  travel_advance: 'Uang muka dinas',
  travel_settlement: 'Penyelesaian dinas',
  depreciation: 'Penyusutan aset',
  asset_disposal: 'Pelepasan aset',
  bad_debt: 'Hapus buku piutang',
  accrual: 'Akrual',
  accrual_reversal: 'Pembalikan akrual',
  opening_balance: 'Saldo awal',
  year_end_close: 'Tutup tahun',
  excel_import: 'Impor Excel',
  excel_import_mapped: 'Impor Excel',
  inventory_receive: 'Penerimaan barang',
  inventory_issue: 'Pengeluaran barang',
  inventory_adjust: 'Penyesuaian stok',
  cogs_shipment: 'HPP pengiriman',
  petty_cash: 'Kas kecil',
  petty_cash_expense: 'Kas kecil / uang muka',
  petty_cash_replenish: 'Pengisian kas kecil',
  cmt_ap_invoice_post: 'Tagihan CMT',
  marketplace_withdrawal: 'Penarikan saldo toko',
};

export function journalSourceLabel(code) {
  if (!code) return '—';
  return JOURNAL_SOURCE_LABELS[code] || String(code).replace(/_/g, ' ');
}

/** Status dokumen keuangan → label + nada warna StatusBadge. */
export const FIN_STATUS = {
  draft:        { label: 'Draf',              tone: 'muted' },
  sent:         { label: 'Terbit',            tone: 'info' },
  issued:       { label: 'Terbit',            tone: 'info' },
  approved:     { label: 'Disetujui',         tone: 'info' },
  overdue:      { label: 'Lewat jatuh tempo', tone: 'danger' },
  partial_paid: { label: 'Dibayar sebagian',  tone: 'warning' },
  partial:      { label: 'Dibayar sebagian',  tone: 'warning' },
  paid:         { label: 'Lunas',             tone: 'success' },
  posted:       { label: 'Terposting',        tone: 'success' },
  voided:       { label: 'Dibatalkan',        tone: 'muted' },
  void:         { label: 'Dibatalkan',        tone: 'muted' },
  cancelled:    { label: 'Dibatalkan',        tone: 'muted' },
  written_off:  { label: 'Dihapusbukukan',    tone: 'danger' },
  completed:    { label: 'Selesai',           tone: 'success' },
  pending:      { label: 'Menunggu',          tone: 'warning' },
  rejected:     { label: 'Ditolak',           tone: 'danger' },
};

export function finStatus(code) {
  const k = String(code || '').toLowerCase();
  return FIN_STATUS[k] || { label: code || '—', tone: 'default' };
}
