/**
 * "Komponen Kurang" — DIGABUNG ke Kirim ke CMT › tab "Permintaan tambahan" (Tahap 9, keputusan owner 12, 7 Nov 2026).
 *
 * Dulu layar ini mencatat permintaan komponen/aksesoris kurang dan "Terkirim" memotong stok TANPA surat jalan,
 * sementara permintaan tambahan/pengganti dari Portal Vendor ada di tab lain dan tidak memotong stok. Sekarang
 * SATU daftar: permintaan vendor + input staf; setelah disetujui menjadi kiriman tambahan yang mengurangi stok.
 * Modul ini tetap ada supaya tautan & menu lama (`cmt-component-requests`, `production-cmt-component-requests`)
 * langsung membuka layar yang sama di tab penggantinya. Endpoint lama `/api/dewi/cmt-component-requests` tetap
 * jalan (mendelegasikan ke `core.kirim_permintaan`).
 */
import { useState } from 'react';
import HubTabs from './hubs/HubTabs';
import { KIRIM_HUB_ID, KIRIM_SUBTITLE, KIRIM_TABS, KIRIM_TITLE, setKirimTab } from './engine/VendorShipmentModule';

export default function CMTComponentRequestModule(props) {
  useState(() => { setKirimTab('permintaan'); return null; });   // sekali, sebelum HubTabs dipasang
  return <HubTabs hubId={KIRIM_HUB_ID} title={KIRIM_TITLE} subtitle={KIRIM_SUBTITLE} compactHeaders tabs={KIRIM_TABS} {...props} />;
}
