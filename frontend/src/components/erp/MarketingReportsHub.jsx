/**
 * MarketingReportsHub.jsx
 * Consolidation #8: Marketing Reports — Overview + Sales + Ads + Harian + MINGGUAN + Bulanan
 * Replaces: marketing-overview + marketing-performance + marketing-ads
 *           + marketing-daily-report + marketing-monthly-report (5 entries → 1)
 *
 * 2026-08-12 (F8) — tab **Rapat Mingguan** ditambahkan di sini, BUKAN sebagai pintu
 * menu baru: laporan rapat adalah laporan, dan aturan IA v2.1 melarang dua pintu
 * untuk satu fungsi. Deep-link `marketing-weekly-report` diarahkan ke tab ini lewat
 * `makeRedirect('marketing-reports','weekly')` yang menitipkan kunci tab di
 * sessionStorage (`hub_tab_marketing-reports`) — karena itu hub ini kini MEMBACA
 * kunci tersebut; sebelumnya deep-link tab apa pun ke hub ini selalu mendarat di
 * Overview dan pemakainya harus mencari tabnya sendiri.
 */
import React, { useState, useEffect } from 'react';
import HubTabs from './hubs/HubTabs';
import MarketingOverviewDashboard  from './marketing/MarketingOverviewDashboard';
import SalesPerformanceDashboard   from './marketing/SalesPerformanceDashboard';
import AdsPerformanceDashboard     from './marketing/AdsPerformanceDashboard';
import DailyReportModule           from './marketing/DailyReportModule';
import WeeklyMeetingReportModule   from './marketing/WeeklyMeetingReportModule';
import MonthlyReportModule         from './marketing/MonthlyReportModule';

const HUB_ID = 'marketing-reports';
const TAB_KEYS = ['overview', 'sales', 'ads', 'daily', 'weekly', 'monthly'];
// Deep-link id → tab awal. `moduleId` dikirim App.js ke setiap modul, jadi tab
// yang diminta tidak bergantung pada urutan mount (pola sessionStorage lama
// terbukti mendarat di tab pertama).
const MODULE_TAB = { 'marketing-weekly-report': 'weekly' };

/** Tab yang diminta URL hash — dibaca LANGSUNG di sini, bukan hanya lewat prop.
 *
 * KENAPA DIULANG DI SINI (SESI #11): tab yang diminta tautan sebelumnya hanya
 * sampai lewat `initialTab`/sessionStorage, dan keduanya hanya terbaca **sekali
 * saat mount**. Akibatnya dua keadaan nyata gagal:
 *   1. mengubah hash sementara hub SUDAH terbuka (`#marketing-reports=weekly`
 *      ditempel di address bar) tidak memindahkan tab sama sekali — pemakai
 *      menyimpulkan tautannya rusak;
 *   2. urutan mount vs. `setCurrentModule` bergantung waktu ⇒ hasilnya kadang
 *      Overview, kadang tab yang benar (persis kebingungan yang membuat penguji
 *      sesi lalu melaporkan "tabel Laporan Harian tidak ada").
 * Membaca hash langsung membuat layar ini tidak bergantung pada urutan siapa
 * pun. `HUB_ID` dicocokkan supaya hash untuk modul LAIN tidak ikut dipakai.
 */
function tabFromHash() {
  try {
    const raw = (window.location.hash || '').replace(/^#/, '');
    if (!raw) return null;
    const parts = raw.split(/[=#/]/);
    if (parts[0] !== HUB_ID && !MODULE_TAB[parts[0]]) return null;
    const t = (parts.slice(1).join('') || '').trim();
    return TAB_KEYS.includes(t) ? t : null;
  } catch (e) { return null; }
}

export default function MarketingReportsHub({ token, onNavigate, moduleId, initialTab }) {
  const [activeTab, setActiveTab] = useState(() => {
    const fromHash = tabFromHash();
    if (fromHash) return fromHash;
    if (initialTab && TAB_KEYS.includes(initialTab)) return initialTab;
    if (MODULE_TAB[moduleId]) return MODULE_TAB[moduleId];
    try {
      const saved = sessionStorage.getItem(`hub_tab_${HUB_ID}`);
      if (saved && TAB_KEYS.includes(saved)) {
        sessionStorage.removeItem(`hub_tab_${HUB_ID}`);
        return saved;
      }
    } catch (e) { /* sessionStorage tidak tersedia */ }
    return 'overview';
  });

  // Hash BERUBAH sementara hub sudah terbuka ⇒ pindah tab (lihat `tabFromHash`).
  useEffect(() => {
    const onHash = () => { const t = tabFromHash(); if (t) setActiveTab(t); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // Prop `initialTab` berubah (App.js membaca hash lebih dulu) ⇒ ikut pindah.
  useEffect(() => {
    if (initialTab && TAB_KEYS.includes(initialTab)) setActiveTab(initialTab);
  }, [initialTab]);

  // SESI #11 — TAB YANG AKTIF DITULIS KE URL supaya tautannya BISA DIBAGIKAN.
  // Kenapa: hub ini memuat 6 laporan di satu pintu, tetapi URL-nya selalu
  // `#marketing-reports` — jadi "kirim laporan hariannya ke saya" tidak pernah
  // bisa dijawab dengan menempel tautan; penerima selalu mendarat di Overview
  // dan harus dituntun ("klik tab ke-4"). `replaceState` dipakai (BUKAN
  // `location.hash = …`) supaya tidak memicu `hashchange` → tidak ada
  // re-mount modul yang membuang isi tabel/penyaring yang sedang dilihat.
  const selectTab = (t) => {
    setActiveTab(t);
    try {
      const want = `#${HUB_ID}=${t}`;
      if (window.location.hash !== want) window.history.replaceState(null, '', want);
    } catch (e) { /* history tidak tersedia */ }
  };

  // Standar UI/UX v2 (8 Nov 2026): satu kepala hub tipis + baris tab standar (HubTabs, mode terkendali).
  // Modul di dalam tab tidak mengulang judulnya; tombolnya pindah ke baris tab (dulu kepala ganda + tab beremoji).
  const TABS = [
    { key: 'overview', label: 'Ringkasan', Component: MarketingOverviewDashboard },
    { key: 'sales', label: 'Performa penjualan', Component: SalesPerformanceDashboard },
    { key: 'ads', label: 'Performa iklan', Component: AdsPerformanceDashboard },
    { key: 'daily', label: 'Laporan harian', Component: DailyReportModule },
    { key: 'weekly', label: 'Rapat mingguan', Component: WeeklyMeetingReportModule },
    { key: 'monthly', label: 'Laporan bulanan', Component: MonthlyReportModule },
  ];

  return (
    <div data-testid="marketing-reports-hub">
      <HubTabs hubId={HUB_ID} title="Laporan marketing"
        subtitle="Ringkasan eksekutif, performa penjualan dan iklan, laporan harian, rapat mingguan, dan laporan bulanan PIC."
        tabs={TABS} value={activeTab} onValueChange={selectTab} token={token} onNavigate={onNavigate} />
    </div>
  );
}
