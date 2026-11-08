/**
 * Modal (engine) — Standar UI/UX v2 (8 Nov 2026): dulu popup buatan sendiri (div tetap + tombol × polos, tanpa Esc,
 * tanpa kunci fokus, tidak penuh layar di HP). Sekarang meneruskan ke `erp/Modal` (Radix Dialog) yang tampil sama
 * dengan FormPopup: kepala tipis, isi bergulir, layar penuh di HP. API tidak berubah:
 *   <Modal title="…" onClose={fn} size="sm|md|lg|xl|2xl|3xl">…</Modal>
 * Form baru memakai `ui/form-popup` langsung; komponen ini hanya untuk pemakai lama yang belum dipindah.
 */
export { default } from '../Modal';
