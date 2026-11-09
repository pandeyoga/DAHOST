/**
 * Tahap persetujuan cuti/izin/sakit & lembur — 2026-11-09 (Q6, keputusan owner): tingkat 1 ATASAN LANGSUNG, lalu HR;
 * tanpa atasan → langsung HR. Cermin `backend/core/approval_route.py` (`waiting_manager`). Pengajuan lama tanpa
 * `approval_route` mengikuti statusnya saja.
 */
const PERAN_SUPER = ['superadmin', 'owner', 'admin'];

export function menungguAtasan(doc) {
  const rute = (doc && doc.approval_route) || {};
  return rute.level_1 === 'atasan'
    && Number(doc.approval_level_required || 1) > 1
    && Number(doc.current_approval_level || 1) === 1;
}

/** Teks tahap untuk pengajuan yang masih menunggu; null bila sudah diputus atau data lama. */
export function labelTahap(doc) {
  if (!doc) return null;
  const menunggu = ['pending', 'pending_approval', 'pending_hr_approval'].includes(doc.status);
  if (!menunggu) return null;
  if (menungguAtasan(doc)) return `Menunggu atasan: ${(doc.approval_route || {}).manager_name || 'atasan langsung'}`;
  if (doc.approval_route || doc.status === 'pending_hr_approval' || Number(doc.current_approval_level || 1) > 1) return 'Menunggu HR';
  return null;
}

/** HR boleh menyetujui? Tidak selama menunggu atasan (kecuali owner/superadmin/admin sebagai cadangan). */
export function bolehSetujuiHR(doc, user) {
  if (!menungguAtasan(doc)) return true;
  return PERAN_SUPER.includes(String((user && user.role) || '').toLowerCase());
}
