/**
 * rbac.jsx — Role-Based Access Control helpers for CV. Dewi Aditya ERP
 *
 * Satu penjaga UI untuk seluruh aplikasi. Sumber izin (urutan pemeriksaan):
 *   1. `role`/`user.role` termasuk super role  -> selalu lolos
 *   2. izin "*"                                -> selalu lolos
 *   3. `hasPerm(key)` bila disediakan pemanggil
 *   4. `user.permissions` (dikirim `/api/auth/me` & `/api/auth/login`)
 *
 * Kompatibel dua gaya pemakaian:
 *   <RequirePerm perm="hr.view" hasPerm={hasPerm} role={userRole}>...</RequirePerm>
 *   <RequirePerm user={user} keys={['roles.manage']}>...</RequirePerm>
 */
import React from 'react';
import { Shield } from 'lucide-react';

const SUPER_ROLES = ['superadmin', 'super_admin', 'admin', 'owner'];

/**
 * Cek izin tanpa komponen — bisa dipakai di logika biasa.
 *
 * `roles` (opsional): mode "izin, lalu kode peran lama" — cermin `core.authz.izin_atau_peran_lama` /
 * `routes.shared.can_act` di server. Lolos bila peran super, punya izin "*", atau punya salah satu izin
 * `perm`/`keys` (izin lama tersirat dari centang `mod.*`). Kode peran di `roles` hanya berlaku selama peran itu
 * BELUM punya centang sama sekali (14 Nov 2026, owner: centang = penentu; dulu kode peran mengalahkan centang).
 * 2026-11-08: peran buatan owner ("HR Generalist", "Accounting & Finance", …) dulu tidak melihat tombolnya.
 */
export function checkPerm({ user, role, hasPerm, perm, keys, roles }) {
  const effectiveRole = String(role || user?.role || '').toLowerCase();
  if (Array.isArray(roles)) {
    const rawRole = String(role || user?.role || '');
    if (SUPER_ROLES.includes(rawRole.toLowerCase())) return true;
    const ownedPerms = Array.isArray(user?.permissions) ? user.permissions : [];
    if (ownedPerms.includes('*')) return true;
    if ([perm, ...(Array.isArray(keys) ? keys : [])].filter(Boolean).some((k) => ownedPerms.includes(k))) return true;
    // Kode peran lama: hanya selama peran ini belum diatur centangnya (izin kosong), dibandingkan tanpa beda huruf.
    if (ownedPerms.length > 0) return false;
    return roles.map((r) => String(r).toLowerCase()).includes(rawRole.toLowerCase());
  }
  if (SUPER_ROLES.includes(effectiveRole)) return true;

  const wanted = [perm, ...(Array.isArray(keys) ? keys : [])].filter(Boolean);
  if (wanted.length === 0) return true; // tidak ada syarat -> tampilkan

  const owned = Array.isArray(user?.permissions) ? user.permissions : [];
  if (owned.includes('*')) return true;
  if (wanted.some((k) => owned.includes(k))) return true;

  if (typeof hasPerm === 'function') {
    return wanted.some((k) => Boolean(hasPerm(k)));
  }

  // Tidak ada informasi izin sama sekali -> permisif (jangan mematikan UI lama).
  return owned.length === 0;
}

/**
 * Pemakai punya salah satu centang owner `keys` (`mod.<modul>.<aksi>`)? 14 Nov 2026 — untuk tombol yang endpoint-nya
 * dijaga CENTANG (gerbang modul server), bukan kode peran. `hasPerm` = fungsi dari App (izin dari server: peran super
 * & izin "*" selalu lolos); tanpa itu dibaca dari sesi tersimpan (`erp_user`, diperbarui `/auth/me`). Beda dengan
 * `checkPerm`: izin kosong = TIDAK boleh (tidak permisif).
 */
export function punyaCentang(hasPerm, ...keys) {
  const wanted = keys.flat().filter(Boolean);
  if (typeof hasPerm === 'function') return wanted.some((k) => Boolean(hasPerm(k)));
  try {
    const u = JSON.parse(localStorage.getItem('erp_user') || 'null') || {};
    if (SUPER_ROLES.includes(String(u.role || '').toLowerCase())) return true;
    const owned = Array.isArray(u.permissions) ? u.permissions : [];
    return owned.includes('*') || wanted.some((k) => owned.includes(k));
  } catch { return false; }
}

/**
 * RequirePerm — render children hanya bila izin dimiliki.
 */
export function RequirePerm({ perm, keys, user, hasPerm, role, children, fallback = null }) {
  if (checkPerm({ user, role, hasPerm, perm, keys })) return <>{children}</>;
  return fallback !== null ? <>{fallback}</> : <PermissionDenied />;
}

/**
 * PermissionDenied — Default "access denied" UI shown inside a module.
 */
export function PermissionDenied({ message = 'Anda tidak memiliki akses ke fitur ini.' }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 p-12 text-center" data-testid="permission-denied">
      <div className="rounded-full bg-destructive/10 p-4">
        <Shield className="h-8 w-8 text-destructive" />
      </div>
      <h3 className="text-lg font-semibold text-foreground">Akses Ditolak</h3>
      <p className="max-w-xs text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
