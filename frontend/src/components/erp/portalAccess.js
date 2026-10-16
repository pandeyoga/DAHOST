// Single source of truth for role → portal access (frontend).
// Keep in sync with backend routes/shared.py PORTAL_ACCESS.
// Portal ids match portalNav.js keys.
import { PORTAL_NAV } from './portal-shell/portalNav';

// Roles that can access ALL portals.
export const SUPER_ROLES = ['superadmin', 'admin', 'owner'];

// Portals available to every authenticated user regardless of role.
export const ALL_ROLE_PORTALS = ['self', 'collaboration'];

export const PORTAL_ROLES = {
  management:     ['hr_manager', 'manager_produksi', 'manager_keuangan', 'manager_hr', 'manager_marketing'],
  sysadmin:       [],   // super_admin + admin saja
  production:     ['supervisor_produksi', 'admin_produksi', 'ppic', 'operator', 'spv_cuting', 'operator_cuting', 'supervisor'],
  cutting:        ['spv_cuting', 'operator_cuting', 'supervisor_produksi', 'admin_produksi', 'admin_gudang'],
  // 2026-08-06 — Portal Pengadaan. Peran DISELARASKAN dengan penjaga backend
  // `routes/procurement_suppliers.py::_require_procurement` supaya menu yang
  // tampil tidak berujung 403.
  // 2026-08-06 — `admin_aksesoris`/`spv_aksesoris` ikut karena pintu "Request
  // Aksesoris" (pembelian) pindah ke portal ini dan dihapus dari Portal Aksesoris.
  // 2026-08-07 — approver PR wajib bisa membuka portal ini (cermin backend
  // routes/shared.py PORTAL_ACCESS). Tanpa `supervisor_produksi`/`manager`/
  // `director` dst., approver tahap departemen & final tidak bisa mencapai layar
  // "Permintaan Pengadaan" tempat kotak persetujuan berada.
  procurement:    ['admin_pengadaan', 'manager_pengadaan', 'purchasing', 'admin_gudang', 'accounting', 'staff_keuangan', 'manager_keuangan', 'manager_produksi', 'supervisor', 'admin_aksesoris', 'spv_aksesoris',
                   'supervisor_produksi', 'manager', 'dept_head', 'manager_hr', 'manager_marketing', 'spv_packing', 'spv_cuting', 'director', 'cfo', 'ceo'],
  warehouse:      ['admin_gudang', 'spv_packing', 'tim_packing', 'admin_aksesoris', 'supervisor'],
  accessories:    ['admin_aksesoris', 'admin_gudang', 'spv_aksesoris'],
  finance:        ['accounting', 'staff_keuangan', 'manager_keuangan'],
  // 2026-09 — Portal Penjualan (cermin backend routes/shared.py PORTAL_ACCESS.sales)
  sales:          ['sales', 'admin_sales', 'accounting', 'staff_keuangan', 'manager_keuangan', 'pic_toko', 'cs_staff', 'manager_marketing', 'admin_gudang'],
  hr:             ['hr', 'hr_manager', 'staff_hr'],
  maklon:         ['admin_maklon', 'admin_produksi', 'supervisor_produksi', 'ppic', 'accounting'],
  toko:           ['pic_toko', 'pic_marketing', 'staff_marketing', 'marketing_kol', 'cs_staff', 'manager_marketing'],
  rnd:            ['rnd_staff', 'manager_produksi', 'supervisor_produksi'],
  assets:         ['accounting', 'manager_keuangan', 'staff_keuangan', 'admin_gudang'],
  collaboration:  [],   // allRoles
  self:           [],   // allRoles
};

// Can a given role open a given portal?
// 2026-08-05 — daftar di atas kini BAWAAN. Bila owner sudah mengatur portal pada
// role (Portal Administrasi Sistem → Manajemen Role), backend mengirim daftar
// portal EFEKTIF saat login / `/auth/me` dan itulah yang dipakai. Disimpan di
// localStorage `erp_access` supaya tidak perlu panggilan ekstra tiap render.
export function readEffectiveAccess() {
  try {
    return JSON.parse(localStorage.getItem('erp_access') || 'null') || null;
  } catch { return null; }
}

export function saveEffectiveAccess({ portals, hidden_modules, is_super, module_access } = {}) {
  try {
    localStorage.setItem('erp_access', JSON.stringify({
      portals: portals || [], hidden_modules: hidden_modules || [], is_super: !!is_super,
      module_access: module_access || {},
    }));
  } catch { /* storage penuh/diblokir — jatuh ke bawaan */ }
}

/** Pintu menu yang disembunyikan untuk user aktif (kosong = tampilkan semua). */
export function hiddenModules() {
  const a = readEffectiveAccess();
  return (a && Array.isArray(a.hidden_modules)) ? a.hidden_modules : [];
}

/**
 * Izin granular per menu (Lihat/Tambah/Ubah/Hapus/Approve/Export) dari backend
 * (`data/module_catalog.py`). Menu yang tidak tercantum = portalnya belum diatur
 * granular oleh owner -> diperlakukan boleh (aturan lama berlaku).
 */
export function moduleActions(menuId) {
  const a = readEffectiveAccess();
  if (!a || a.is_super) return null;
  const acts = a.module_access?.[menuId];
  return Array.isArray(acts) ? acts : null;
}

export function canDo(menuId, action = 'view') {
  const acts = moduleActions(menuId);
  return acts === null ? true : acts.includes(action);
}

/**
 * Sinkron ulang akses dari server (`/api/auth/me`): portal, menu tersembunyi, izin per modul,
 * peran & izin di `erp_user`. Memancarkan event `erp-access-updated` agar App/PortalShell
 * langsung memakai akses terbaru tanpa login ulang.
 */
export async function refreshEffectiveAccess(token) {
  if (!token) return null;
  try {
    const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) return null;
    const me = await r.json();
    saveEffectiveAccess({
      portals: me.portals || [], hidden_modules: me.hidden_modules || [],
      is_super: !!me.is_super, module_access: me.module_access || {},
    });
    let merged = me;
    try {
      const prev = JSON.parse(localStorage.getItem('erp_user') || '{}');
      merged = {
        ...prev, role: me.role, name: me.name ?? prev.name, permissions: me.permissions || [],
        portals: me.portals || [], hidden_modules: me.hidden_modules || [],
        module_access: me.module_access || {}, is_super: !!me.is_super,
      };
      localStorage.setItem('erp_user', JSON.stringify(merged));
    } catch { /* noop */ }
    window.dispatchEvent(new CustomEvent('erp-access-updated', { detail: merged }));
    return merged;
  } catch {
    return null;
  }
}

/** Role user aktif (dibaca dari sesi tersimpan, sama pola dgn hiddenModules). */
export function currentRole() {
  try {
    return (JSON.parse(localStorage.getItem('erp_user') || 'null')?.role || '').toLowerCase();
  } catch { return ''; }
}

/**
 * Boleh tidak pintu ini DITAMPILKAN untuk user aktif?
 *
 * Sebagian pintu punya kewenangan lebih sempit daripada portalnya. Contoh nyata:
 * pintu **"Input Vendor CMT"** (mengisi data atas nama vendor CMT) berdampak
 * langsung ke TAGIHAN, jadi owner membatasinya ke admin/admin_produksi/
 * supervisor_produksi/ppic — padahal Portal Produksi juga terbuka untuk
 * `operator`, `spv_cuting`, dan `supervisor`. Tanpa penyaring ini, mereka melihat
 * pintu yang begitu diklik hanya menjawab "tidak berwenang" — menu buntu yang
 * membuat orang mengira sistemnya rusak.
 *
 * Item nav TANPA field `roles` = terbuka untuk semua yang bisa membuka portalnya
 * (perilaku lama, tidak berubah). Ini HANYA soal tampilan; penjaga sungguhan
 * tetap di backend (`core/cmt_override.OVERRIDE_ROLES`).
 */
export function navItemAllowed(item, role) {
  const roles = item?.roles;
  if (!Array.isArray(roles) || roles.length === 0) return true;
  const r = (role || currentRole() || '').toLowerCase();
  if (SUPER_ROLES.includes(r)) return true;
  return roles.map(x => String(x).toLowerCase()).includes(r);
}

/** Pintu menu tampil untuk user aktif di portal ini? (menu tersembunyi owner/izin Lihat + pembatasan peran pintu) */
export function navItemVisible(item, role, portalId) {
  if (!item || item.isHeader) return true;
  const h = hiddenModules();
  return !h.includes(item.id) && !(portalId && h.includes(`${portalId}::${item.id}`)) && navItemAllowed(item, role);
}

const realItems = (list) => (list || []).filter((i) => !i.isHeader);

/** Navigasi portal yang sudah disaring: menu, grup & bagian (tab atas) yang kosong dibuang. */
export function visibleNav(nav, role, portalId) {
  if (!nav) return nav;
  const vis = (list) => (list || []).filter((it) => navItemVisible(it, role, portalId));
  const sections = (nav.sections || []).map((s) => (s.groups?.length
    ? { ...s, groups: s.groups.map((g) => ({ ...g, items: vis(g.items) })).filter((g) => realItems(g.items).length) }
    : { ...s, items: vis(s.items) }))
    .filter((s) => realItems(s.items).length || (s.groups || []).length);
  return { ...nav, sections };
}

export function firstVisibleModule(nav) {
  for (const s of nav?.sections || []) {
    const items = s.items?.length ? s.items : (s.groups || []).flatMap((g) => g.items || []);
    const first = realItems(items)[0];
    if (first) return first.id;
  }
  return null;
}

/** Modul ini pintu menu yang disembunyikan untuk user aktif? (bukan pintu menu = tidak diblok) */
export function moduleBlocked(moduleId, role, portalId) {
  if (!moduleId) return false;
  const h = hiddenModules();
  if (h.includes(moduleId) || (portalId && h.includes(`${portalId}::${moduleId}`))) return true;
  const items = Object.values(PORTAL_NAV).flatMap((n) => (n.sections || []).flatMap((s) => [
    ...(s.items || []), ...(s.groups || []).flatMap((g) => g.items || [])]));
  const matches = items.filter((i) => i.id === moduleId);
  return matches.length > 0 && !matches.some((i) => navItemAllowed(i, role));
}

function portalHasVisibleMenu(portalId, role) {
  const nav = PORTAL_NAV[portalId];
  return !nav || visibleNav(nav, role, portalId).sections.length > 0;
}

export function canAccessPortal(role, portalId) {
  const r = (role || '').toLowerCase();
  if (SUPER_ROLES.includes(r)) return true;
  if (ALL_ROLE_PORTALS.includes(portalId)) return true;
  const acc = readEffectiveAccess();
  const listed = (acc && Array.isArray(acc.portals) && acc.portals.length)
    ? acc.portals.includes(portalId)
    : (PORTAL_ROLES[portalId] || []).includes(r);
  return listed && portalHasVisibleMenu(portalId, r);
}
