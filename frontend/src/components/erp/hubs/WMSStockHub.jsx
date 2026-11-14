import React, { lazy } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';
import ModuleActionGuard from '../portal-shell/ModuleActionGuard';
import { aksiCentang } from '../../../lib/rbac';

// RC-IA-warehouse-1 (Opsi A) — konsolidasi 4 modul "STOK & AKURASI" gudang → 1 hub.
// Menghilangkan kebingungan "pintu mana yang benar" untuk stok yang sama (SSOT rahaza_material_stock / unified).
//   - Daftar stok            → UnifiedInventoryModule  (hanya baca; Kepemilikan: milik DA / titipan klien maklon)
//   - Stok & Pergerakan      → RahazaStockModule       (stok kanonik + receive/transfer/adjust rahaza SSOT)
//   - Opname                 → WMSOpnameScanModule    (Fase 4/5: scan-driven /api/wms/opname3 SSOT + finance)
//   - Penyesuaian (Adjust)   → InventoryScrapModule    (jalur adjust RESMI: rahaza/material-adjust + posting GL)
const UnifiedInventoryModule  = lazyRetry(() => import('../UnifiedInventoryModule'));
const RahazaStockModule       = lazyRetry(() => import('../RahazaStockModule'));
const WMSOpnameScanModule = lazyRetry(() => import('../WMSOpnameScanModule'));  // Fase 4: opname scan-driven (SSOT + finance)
const InventoryScrapModule    = lazyRetry(() => import('../InventoryScrapModule'));
// FASE 6.6-A: kesehatan & rekonsiliasi skema baris stok (baris warisan skema A/B/C).
const StockSchemaHealthModule = lazyRetry(() => import('../StockSchemaHealthModule'));
// FASE E: "Posisi & Search" dilipat ke hub Stok & Akurasi (dari monolit Scanner Barcode).
// 2026-09-23: laporan Stok Minus (mode sementara sebelum opname).
const NegativeStockModule = lazyRetry(() => import('../NegativeStockModule'));
const WMSPositionsTab = lazyRetry(() => import('../WMSModule').then(m => ({ default: m.PositionsTab })));

// 14 Nov 2026 (owner: "saya tidak ingin ada seperti ini dimanapun"): Opname dicentang terpisah (modul Opname Stok
// Gudang / Opname Aksesoris). Tab ini mengikuti centang modul itu: tanpa Lihat tab tidak tampil, dan tombolnya
// (Opname baru, Setujui, …) mengikuti aksi yang dicentang — bukan centang menu Stok & Akurasi tempatnya menumpang.
function OpnameTab(props) {
  return (
    <ModuleActionGuard actions={aksiCentang('wh_opname', 'acc_opname')}>
      <WMSOpnameScanModule {...props} />
    </ModuleActionGuard>
  );
}

export default function WMSStockHub(props) {
  return (
    <HubTabs
      hubId="wms-stock-hub"
      title="Stok & Akurasi"
      subtitle="Satu pintu: lihat stok, kelola pergerakan, opname, penyesuaian, dan posisi rak."
      tabs={[
        { key: 'viewer', label: 'Daftar stok', Component: UnifiedInventoryModule },  // Tahap 9C: + Kepemilikan (DA / titipan klien)
        { key: 'stock', label: 'Stok & pergerakan', Component: RahazaStockModule },
        ...(aksiCentang('wh_opname', 'acc_opname').includes('view')
          ? [{ key: 'opname', label: 'Opname stok', Component: OpnameTab }] : []),
        { key: 'negative', label: 'Stok minus', Component: NegativeStockModule },
        { key: 'adjust', label: 'Penyesuaian', Component: InventoryScrapModule },
        { key: 'positions', label: 'Posisi & cari', Component: WMSPositionsTab },
        { key: 'schema', label: 'Kesehatan data stok', Component: StockSchemaHealthModule },
      ]}
      {...props}
    />
  );
}
