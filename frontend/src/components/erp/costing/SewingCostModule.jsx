/**
 * SewingCostModule — DIPENSIUNKAN (Tahap 9, keputusan owner 7 Nov 2026).
 *
 * Dulu menu "Biaya Jahit": rekap upah jahit & HPP batch per SPK. Upah jahit kini diisi per baris di form PO
 * (`po_items.cmt_price_snapshot`, penjaga kunci yang sama) dan rekapnya — tarif per baris, pcs dikirim/lolos QC,
 * upah CMT dari tagihan, bahan per pcs — ada di HPP › HPP per PO (rincian PO). Menu/tautan lama
 * `prod-sewing-cost` tetap bekerja dan membuka hub HPP (tab HPP per PO). Endpoint lama
 * `/api/production/sewing-cost/*` tidak diubah.
 */
import HubTabs from '../hubs/HubTabs';
import { hppTabsFor } from '../hubs/FinanceHppHub';
import { lazyRetry } from '../../../lib/lazyRetry';

const RahazaHPPModule = lazyRetry(() => import('../RahazaHPPModule'));

export default function SewingCostModule(props) {
  const tabs = hppTabsFor(props.portalId).map((t) => (t.key === 'actual' ? { ...t, Component: RahazaHPPModule } : t));
  return <HubTabs hubId="fin-hpp" title="HPP" compactHeaders tabs={tabs} {...props} />;
}
