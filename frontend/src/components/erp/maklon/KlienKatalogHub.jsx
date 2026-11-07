import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from '../hubs/HubTabs';

// Tahap 9 (7 Nov 2026, keputusan owner — tabel menu akhir "Master: Klien & Katalog Buyer"): satu menu bertab
// Klien · Katalog · Estimasi harga. Menggantikan tiga menu lama: Data Klien (`maklon-clients`), Katalog Buyer
// (`maklon-buyer-catalog`), dan Estimasi AI (`maklon-ai-quote`). Ketiga layar memakai cetakan PageLayout;
// di dalam hub judulnya disembunyikan dan tombol utamanya pindah ke baris tab (compactHeaders).
// Deep-link tab: makeRedirect('maklon-klien-katalog', 'klien' | 'katalog' | 'estimasi').
const MaklonClientManagement = lazyRetry(() => import('../MaklonClientManagement'));
const MaklonBuyerCatalogModule = lazyRetry(() => import('../MaklonBuyerCatalogModule'));
const MaklonAIQuoteModule = lazyRetry(() => import('../MaklonAIQuoteModule'));

export const KLIEN_KATALOG_TABS = ['klien', 'katalog', 'estimasi'];

export default function KlienKatalogHub(props) {
  return (
    <HubTabs
      hubId="maklon-klien-katalog"
      title="Klien & Katalog Buyer"
      subtitle="Data klien maklon, artikel buyer beserta BOM dan sampelnya, dan estimasi harga jasa."
      compactHeaders
      tabs={[
        { key: 'klien', label: 'Klien', Component: MaklonClientManagement },
        { key: 'katalog', label: 'Katalog', Component: MaklonBuyerCatalogModule },
        { key: 'estimasi', label: 'Estimasi harga', Component: MaklonAIQuoteModule },
      ]}
      {...props}
    />
  );
}
