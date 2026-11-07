import React, { Suspense, useState } from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent, NestedTabsContext } from '../../ui/tabs';
import { CompactHubContext, HubActionsContext } from '../moduleAtoms';

/**
 * BACKLOG-A (T3.3/T3.4/T3.5/T3.6/T3.9) — Hub generik konsolidasi modul.
 * Merender modul-modul existing sebagai tab TANPA mengubah logika modulnya.
 * Deep-link tab: makeRedirect(hubId, tabKey) menyimpan sessionStorage `hub_tab_<hubId>`.
 */
const Spinner = () => (
  <div className="flex items-center justify-center h-40">
    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[hsl(var(--primary))]" />
  </div>
);

/**
 * `compactHeaders` (2026-11-04, hub Keuangan): modul di dalam tab tidak mengulang judul & penjelasannya
 * (lihat CompactHubContext di moduleAtoms) — dulu judul hub + penjelasan + tab + judul modul + penjelasan
 * menumpuk sehingga angka pertama baru muncul di tengah layar.
 */
export default function HubTabs({ hubId, title, subtitle, tabs, compactHeaders = false, value, onValueChange, ...rest }) {
  // PANDUAN_UI G4 (2026-11-04): tab rata kiri selebar isi; aksi tab aktif di kanan baris yang sama
  const [actionsSlot, setActionsSlot] = useState(null);
  // Tahap 9 (7 Nov 2026): mode terkendali opsional (`value` + `onValueChange`) — dipakai Input atas nama CMT,
  // yang modul di dalamnya memindah tab sendiri (mis. Ringkasan → "Penerimaan Material"). Tanpa prop = seperti dulu.
  const [ownTab, setOwnTab] = useState(() => {
    try {
      const saved = sessionStorage.getItem(`hub_tab_${hubId}`);
      if (saved && tabs.some((t) => t.key === saved)) {
        // SESI #19 — petunjuk tab dihapus TERTUNDA (1,5 detik), bukan seketika.
        // Terukur: membuka deep-link tab (mis. `#mgmt-pdf` → hub tab 'pdf') SEBELUM
        // login membuat hub ter-mount dua kali (sekali saat alur login, sekali
        // setelahnya). Mount pertama MENGHABISKAN petunjuknya, sehingga mount kedua
        // jatuh ke tab pertama — pemakai mengklik "PDF & Kop Surat" lalu mendarat di
        // "Perusahaan" tanpa tahu kenapa. Jeda singkat membuat mount ulang tetap
        // terlayani, tanpa membuat petunjuk itu menempel selamanya.
        setTimeout(() => {
          try { sessionStorage.removeItem(`hub_tab_${hubId}`); } catch (e) { /* noop */ }
        }, 1500);
        return saved;
      }
    } catch (e) { /* sessionStorage tidak tersedia */ }
    return tabs[0]?.key;
  });
  const controlled = value !== undefined && typeof onValueChange === 'function';
  const tab = controlled ? value : ownTab;
  const setTab = controlled ? onValueChange : setOwnTab;

  return (
    <div className="space-y-4" data-testid={`${hubId}`}>
      {title && (
        <div>
          <h2 className="text-2xl font-bold text-foreground tracking-tight leading-tight">{title}</h2>
          {subtitle && <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>}
        </div>
      )}
      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <div className="flex items-center gap-3 flex-wrap">
          <TabsList className="h-auto flex-wrap justify-start gap-1">
            {tabs.map((t) => (
              <TabsTrigger key={t.key} value={t.key} data-testid={`hub-tab-${t.key}`}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <div ref={setActionsSlot} className="ml-auto flex items-center gap-2 flex-wrap" data-testid={`${hubId}-actions`} />
        </div>
        {tabs.map((t) => (
          <TabsContent key={t.key} value={t.key} className="mt-4">
            {tab === t.key && (
              <CompactHubContext.Provider value={compactHeaders}>
                <HubActionsContext.Provider value={compactHeaders ? actionsSlot : null}>
                  <NestedTabsContext.Provider value>
                    <Suspense fallback={<Spinner />}>
                      <t.Component {...rest} {...(t.props || {})} />
                    </Suspense>
                  </NestedTabsContext.Provider>
                </HubActionsContext.Provider>
              </CompactHubContext.Provider>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
