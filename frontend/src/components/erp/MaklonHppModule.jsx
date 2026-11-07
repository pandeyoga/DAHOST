/**
 * MaklonHppModule — DIPENSIUNKAN (Tahap 9, keputusan owner 7 Nov 2026 No. 13).
 *
 * Dulu "HPP Jasa Jahit Maklon": komponen biaya, overhead %, dan target margin % diketik sendiri. Sekarang HPP
 * maklon dihitung SATU kali dari data nyata (potongan + aksesoris yang diserahkan + upah CMT + permak; margin =
 * harga jasa − HPP) di hub HPP yang sama dengan Portal Produksi (`hubs/FinanceHppHub`, tab HPP per PO, disaring
 * PO maklon). Menu/tautan lama `maklon-hpp` tetap bekerja dan membuka hub itu.
 */
import HubTabs from './hubs/HubTabs';
import { hppTabsFor } from './hubs/FinanceHppHub';
import { lazyRetry } from '../../lib/lazyRetry';

// tab yang sama dengan hub HPP (dibaca pemindai UI sebagai layar tab)
const RahazaHPPModule = lazyRetry(() => import('./RahazaHPPModule'));

export default function MaklonHppModule(props) {
  const portalId = props.portalId || 'maklon';
  const tabs = hppTabsFor(portalId).map((t) => (t.key === 'actual' ? { ...t, Component: RahazaHPPModule } : t));
  return <HubTabs hubId="fin-hpp" title="HPP" compactHeaders tabs={tabs} {...props} portalId={portalId} />;
}
