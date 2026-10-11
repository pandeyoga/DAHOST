// Notifikasi seragam saat backend menolak aksi karena izin granular per modul
// (header `x-rbac-denied`, dari backend/middleware/module_permission_gate.py).
import axios from 'axios';
import { toast } from 'sonner';

let lastShown = { msg: '', at: 0 };

function notify(detail) {
  const msg = detail || 'Akses ditolak: Anda tidak punya izin untuk aksi ini.';
  const now = Date.now();
  if (msg === lastShown.msg && now - lastShown.at < 4000) return;
  lastShown = { msg, at: now };
  toast.error('Akses ditolak', { description: msg, id: 'rbac-denied' });
}

export function installRbacDeniedGuard() {
  if (typeof window === 'undefined' || window.__rbacGuardInstalled) return;
  window.__rbacGuardInstalled = true;

  const origFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const res = await origFetch(...args);
    if (res.status === 403 && res.headers.get('x-rbac-denied')) {
      res.clone().json().then((b) => notify(b?.detail)).catch(() => notify());
    }
    return res;
  };

  axios.interceptors.response.use(undefined, (error) => {
    const r = error?.response;
    if (r?.status === 403 && r.headers?.['x-rbac-denied']) notify(r.data?.detail);
    return Promise.reject(error);
  });
}
