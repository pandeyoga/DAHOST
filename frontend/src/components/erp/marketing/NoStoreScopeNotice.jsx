/**
 * NoStoreScopeNotice — panel MENETAP untuk staf yang **belum dipegangi toko**.
 *
 * KENAPA KOMPONEN INI ADA (sesi #10)
 * ----------------------------------
 * F6 menutup kebocoran: staf berlingkup toko yang belum di-assign toko apa pun
 * sekarang melihat angka NOL di seluruh layar marketing. Tetapi "nol tanpa
 * penjelasan" adalah cacat kedua yang sama mahalnya: staf baru menyimpulkan
 * **aplikasinya rusak** (atau lebih buruk: "tokonya tidak berjualan") dan mulai
 * mencari data di tempat lain. Yang dibutuhkan hanyalah satu kalimat yang
 * menyebut SEBAB dan JALAN KELUARNYA — dan kalimat itu harus MENETAP di layar,
 * bukan toast 5 detik.
 *
 * Komponen ini tidak menampilkan apa pun untuk pemakai yang memang melihat semua
 * toko (owner/admin/SPV/manager), dan tidak menampilkan apa pun bila pemakai
 * berlingkup memang sudah punya toko.
 */
import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { currentRole } from '../portalAccess';
import { Notice } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

// Sama dengan `core.marketing_account_scope.SCOPED_ROLES` (backend = SSOT-nya).
const SCOPED_ROLES = ['staff_marketing', 'pic_toko', 'host_live', 'cs_staff'];

/** Pemakai ini hanya melihat toko yang DIPEGANGNYA (PIC atau Assign Staf)? */
export const isStoreScopedUser = () => SCOPED_ROLES.includes(currentRole());

/** Kalimat jalan keluar yang sama di semua layar (2026-11-05: PIC kini ikut memberi akses). */
export const NO_STORE_HINT = 'Minta SPV Marketing atau owner memilih Anda sebagai PIC toko di Manajemen Akun, '
  + 'atau menambahkan Anda di tab Assign Staf.';

export default function NoStoreScopeNotice({ token, what = 'Angka di layar ini' }) {
  const scoped = isStoreScopedUser();
  const [count, setCount] = useState(null);   // null = belum tahu

  useEffect(() => {
    if (!scoped) return;
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API}/api/marketing/accounts?status=active`, {
          headers: { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` },
        });
        const j = res.ok ? await res.json() : [];
        const list = Array.isArray(j) ? j : (j.accounts || j.data || []);
        if (alive) setCount(list.length);
      } catch {
        if (alive) setCount(null);
      }
    })();
    return () => { alive = false; };
  }, [scoped, token]);

  if (!scoped || count === null || count > 0) return null;

  return (
    <Notice tone="warning" icon={AlertTriangle} testId="marketing-no-scope-notice"
      title="Belum ada toko yang Anda pegang.">
      {what} tetap 0 sampai Anda memegang toko. {NO_STORE_HINT} Ini bukan berarti tokonya tidak
      berjualan — Anda hanya melihat toko yang menjadi tanggung jawab Anda.
    </Notice>
  );
}
