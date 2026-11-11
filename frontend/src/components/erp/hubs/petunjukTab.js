/**
 * Petunjuk tab dari tautan lama (makeRedirect → sessionStorage `hub_tab_<hubId>`) untuk layar yang dulu ber-tab dan
 * kini satu daftar dengan penyaring (Keuangan › Hutang / Piutang, 11 Nov 2026). Petunjuk dihapus TERTUNDA 1,5 detik
 * — pola yang sama dengan HubTabs: layar bisa terpasang dua kali saat alur login, pemasangan kedua tetap kebagian.
 */
export function ambilPetunjukTab(hubId) {
  try {
    const key = `hub_tab_${hubId}`;
    const nilai = sessionStorage.getItem(key);
    if (nilai) {
      setTimeout(() => {
        try { sessionStorage.removeItem(key); } catch (e) { /* noop */ }
      }, 1500);
    }
    return nilai || '';
  } catch (e) {
    return '';   // sessionStorage tidak tersedia
  }
}
