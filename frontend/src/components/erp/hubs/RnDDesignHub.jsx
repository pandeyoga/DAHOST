import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// PHASE B (6.1.4 #5) — modul desain & dokumentasi RnD → 1 hub.
// Standar UI/UX v2 (8 Nov 2026): judul hub = label menu "Style & Desain"; nama tab bahasa Indonesia,
// huruf besar hanya di awal. Kunci tab TIDAK diubah (dipakai deep-link makeRedirect).
const RnDStylesTab      = lazyRetry(() => import('../RnDStylesTab'));
const RnDVariantModule  = lazyRetry(() => import('../RnDVariantModule'));
const RnDSizeMappingModule = lazyRetry(() => import('../RnDSizeMappingModule'));
const RnDTechPackModule = lazyRetry(() => import('../RnDTechPackModule'));
const RnDPatternModule  = lazyRetry(() => import('../RnDPatternModule'));
const RnDRevisionsTab   = lazyRetry(() => import('../RnDRevisionsTab'));

export default function RnDDesignHub(props) {
  return (
    <HubTabs
      hubId="rnd-design-hub"
      title="Style & Desain"
      subtitle="Style, varian, ukuran, tech pack, pola, dan revisi desain dalam satu tempat."
      tabs={[
        { key: 'styles', label: 'Daftar style', Component: RnDStylesTab },
        { key: 'variants', label: 'Varian produk', Component: RnDVariantModule },
        { key: 'sizemap', label: 'Padankan ukuran', Component: RnDSizeMappingModule },
        { key: 'techpack', label: 'Tech pack', Component: RnDTechPackModule },
        { key: 'patterns', label: 'Pola & marking', Component: RnDPatternModule },
        { key: 'revisions', label: 'Revisi & persetujuan', Component: RnDRevisionsTab },
      ]}
      {...props}
    />
  );
}
