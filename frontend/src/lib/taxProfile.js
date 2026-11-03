/**
 * taxProfile.js — status pajak perusahaan (saklar PKP) untuk form transaksi.
 * Pasangan backend `core/tax_status.py` (SSOT). Diubah di Pengaturan Perusahaan › Status Pajak.
 *
 *   NON-PKP : dokumen penjualan tanpa PPN; PPN dari supplier = bagian harga beli.
 *   PKP     : PPN 12% × DPP nilai lain 11/12 (kode 04, efektif 11%); PPN masukan dikreditkan.
 */
import { useEffect, useState } from 'react';
import { getToken } from './api';

const API = process.env.REACT_APP_BACKEND_URL || '';
const NON_PKP = { pkp: false, pkp_since: '', ppn_rate: 12, dpp_ratio: '11/12', kode_transaksi: '04', effective_pct: 11, npwp: '' };

let cache = null;
let inflight = null;

export async function fetchTaxProfile(token, { refresh = false } = {}) {
  if (cache && !refresh) return cache;
  if (!inflight || refresh) {
    inflight = fetch(`${API}/api/tax-profile`, { headers: { Authorization: `Bearer ${token || getToken()}` } })
      .then((r) => (r.ok ? r.json() : NON_PKP))
      .then((p) => { cache = { ...NON_PKP, ...(p || {}) }; return cache; })
      .catch(() => NON_PKP)
      .finally(() => { inflight = null; });
  }
  return inflight;
}

/** Hook: { profile, loading }. Gagal dibaca = dianggap NON-PKP (tidak memungut PPN). */
export function useTaxProfile(token) {
  const [profile, setProfile] = useState(cache || NON_PKP);
  const [loading, setLoading] = useState(!cache);
  useEffect(() => {
    let alive = true;
    fetchTaxProfile(token).then((p) => { if (alive) { setProfile(p); setLoading(false); } });
    return () => { alive = false; };
  }, [token]);
  return { profile, loading };
}

/** Pratinjau PPN keluaran (= backend output_tax): PKP → round(round(DPP×11/12, 2) × 12%). */
export function previewOutputTax(profile, dpp, kenaPpn) {
  if (!profile?.pkp || !kenaPpn) return 0;
  const base = Math.max(Number(dpp) || 0, 0);
  const dppLain = Math.round(base * 11 / 12 * 100) / 100;
  return Math.round(dppLain * (Number(profile.ppn_rate) || 12) / 100);
}

/** Kosongkan cache setelah Status Pajak diubah supaya form berikutnya membaca nilai baru. */
export function resetTaxProfileCache() { cache = null; }
