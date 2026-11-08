/**
 * StatusBadge (lama) — lencana status untuk layar PO/WO/faktur lama. Props tetap `{ status }`.
 *
 * Standar UI/UX v2 (8 Nov 2026): warna memakai token tema (dulu palet mentah emerald/sky/amber/red… dengan kontras
 * rendah di tema terang) dan teks status berbahasa Indonesia (dulu "Draft", "In Production", "Unpaid"…).
 * Status yang tidak dikenal tampil apa adanya dengan gaya netral.
 */
const NETRAL = 'bg-[var(--glass-bg)] text-muted-foreground border border-[var(--glass-border)]';
const NADA = {
  sukses: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] border border-[hsl(var(--success)/0.3)]',
  info: 'bg-[hsl(var(--info)/0.12)] text-[hsl(var(--info-text))] border border-[hsl(var(--info)/0.3)]',
  peringatan: 'bg-[hsl(var(--warning)/0.14)] text-[hsl(var(--warning-text))] border border-[hsl(var(--warning)/0.35)]',
  bahaya: 'bg-[hsl(var(--destructive)/0.10)] text-[hsl(var(--danger-text))] border border-[hsl(var(--destructive)/0.3)]',
  utama: 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border border-[hsl(var(--primary)/0.25)]',
  netral: NETRAL,
};

const STATUS = {
  // Umum
  active: ['Aktif', 'sukses'],
  inactive: ['Nonaktif', 'netral'],
  // Status PO
  Draft: ['Draf', 'netral'],
  Confirmed: ['Dikonfirmasi', 'info'],
  Distributed: ['Didistribusikan', 'info'],
  'In Production': ['Sedang diproduksi', 'peringatan'],
  'Production Complete': ['Produksi selesai', 'sukses'],
  Completed: ['Selesai', 'sukses'],
  Closed: ['Ditutup', 'netral'],
  // Status perintah kerja
  Waiting: ['Menunggu', 'netral'],
  'In Progress': ['Sedang berjalan', 'info'],
  // Status faktur
  Unpaid: ['Belum dibayar', 'bahaya'],
  Partial: ['Dibayar sebagian', 'peringatan'],
  Paid: ['Lunas', 'sukses'],
  // Selisih
  'Variance Review': ['Tinjau selisih', 'utama'],
  'Return Review': ['Tinjau retur', 'peringatan'],
  'Ready to Close': ['Siap ditutup', 'sukses'],
};

export default function StatusBadge({ status }) {
  const [label, nada] = STATUS[status] || [status, 'netral'];
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${NADA[nada] || NETRAL}`}>
      {label}
    </span>
  );
}
