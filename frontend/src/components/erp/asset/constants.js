/**
 * Manajemen Aset — label & nada status (Standar UI/UX v2, 8 Nov 2026).
 *
 * Status ditampilkan lewat StatusBadge bersama (moduleAtoms) dengan label Indonesia + nada token
 * (success / warning / danger / info / muted). Dulu tiap status membawa kelas warna palet langsung
 * (emerald/amber/violet/cyan) sehingga satu portal punya tujuh warna lencana yang berbeda.
 */

export const STATUS_CONFIG = {
  active:           { label: 'Aktif',              tone: 'success' },
  in_maintenance:   { label: 'Pemeliharaan',       tone: 'warning' },
  disposed:         { label: 'Dilepas',            tone: 'muted' },
  under_repair:     { label: 'Perbaikan',          tone: 'warning' },
  pending_disposal: { label: 'Menunggu pelepasan', tone: 'warning' },
  // ACC-3 — status dari fitur Peminjaman Alat (routes/asset/loans.py)
  on_loan:          { label: 'Dipinjam',           tone: 'info' },
  lost:             { label: 'Hilang',             tone: 'danger' },
};

/** Pilihan saringan status di tab Aset (urutan sama dengan dulu). */
export const STATUS_FILTER_OPTIONS = [
  { value: '', label: 'Semua status' },
  { value: 'active', label: 'Aktif' },
  { value: 'on_loan', label: 'Dipinjam' },
  { value: 'in_maintenance', label: 'Pemeliharaan' },
  { value: 'lost', label: 'Hilang' },
  { value: 'disposed', label: 'Dilepas' },
];

// ACC-3 — status baris peminjaman aset. `overdue` bukan status tersimpan,
// tapi turunan (status=active DAN target kembali sudah lewat).
export const LOAN_STATUS_CONFIG = {
  active:   { label: 'Dipinjam',      tone: 'info' },
  overdue:  { label: 'Terlambat',     tone: 'danger' },
  returned: { label: 'Sudah kembali', tone: 'success' },
};

export const RETURN_CONDITION_LABEL = {
  good: 'kondisi baik',
  damaged: 'rusak',
  lost: 'hilang',
};

export const PR_STATUS_CONFIG = {
  draft:            { label: 'Draf',                      tone: 'muted' },
  submitted:        { label: 'Menunggu departemen',       tone: 'warning' },
  dept_approved:    { label: 'Menunggu Keuangan',         tone: 'warning' },
  finance_approved: { label: 'Menunggu persetujuan akhir', tone: 'warning' },
  approved:         { label: 'Disetujui',                 tone: 'success' },
  in_procurement:   { label: 'Sedang diadakan',           tone: 'info' },
  completed:        { label: 'Selesai',                   tone: 'success' },
  rejected:         { label: 'Ditolak',                   tone: 'danger' },
  cancelled:        { label: 'Dibatalkan',                tone: 'muted' },
};

export const PR_PRIORITY_LABEL = { low: 'Rendah', medium: 'Sedang', high: 'Tinggi', urgent: 'Mendesak' };
export const PR_TYPE_LABEL = { asset: 'Aset', consumable: 'Habis pakai', service: 'Jasa/layanan', other: 'Lainnya' };
/** Langkah persetujuan di riwayat permintaan pengadaan. */
export const PR_STEP_LABEL = {
  submitted: 'mengajukan', approved: 'menyetujui', rejected: 'menolak', cancelled: 'membatalkan',
};

export const DISPOSAL_STATUS_CONFIG = {
  pending:  { label: 'Menunggu',  tone: 'warning' },
  approved: { label: 'Disetujui', tone: 'success' },
  rejected: { label: 'Ditolak',   tone: 'danger' },
};

export const MAINT_TYPE_LABEL = { scheduled: 'Terjadwal', corrective: 'Korektif', preventive: 'Preventif' };
export const MAINT_STATUS_LABEL = { completed: 'Selesai', in_progress: 'Sedang berjalan', scheduled: 'Terjadwal' };

export const DEPR_METHOD_LABEL = { straight_line: 'Garis lurus', double_declining: 'Saldo menurun ganda' };

/** Peringatan pemeliharaan: tingkat keparahan dari server. */
export const SEVERITY_CONFIG = {
  critical: { label: 'Mendesak',        tone: 'danger' },
  warning:  { label: 'Perlu perhatian', tone: 'warning' },
  info:     { label: 'Informasi',       tone: 'info' },
};

/** 2026-11-08 (keputusan owner): satu kalimat yang sama di menu "Lainnya" dan di detail aset. Sejak K18 penyusutan
 *  hanya diposting dari registri Keuangan (menu `fin-fixed-assets`, tab Penyusutan). */
export const KALIMAT_PENYUSUTAN = 'Penyusutan aset diposting di Keuangan › Aset Tetap, bukan di Portal Aset.';
export const MENU_PENYUSUTAN = { modul: 'fin-fixed-assets', tab: 'depreciation' };
