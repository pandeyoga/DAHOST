import { useEffect, useState } from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import { apiFetch } from '../../../lib/apiFetch';
import HubTabs from './HubTabs';

// T3.5 — modul HR AI → 1 hub
// Standar UI/UX v2 (8 Nov 2026): judul hub = nama menu, nama tab berbahasa Indonesia (kunci tab tetap — dipakai
// tautan lama makeRedirect('hr-ai-hub', …)).
// Audit HR Tahap D (9 Nov 2026): tab pertama = Asisten AI ruang SDM (alat SDM: rekap absensi & pengecualian, koreksi
// absen berkartu, draf shift, cek payroll). DIPENSIUNKAN dari hub: "Wawasan AI" (isinya AI produksi — RahazaAIModule
// dihapus) dan "Tindak lanjut" (daftar tugas manual, bukan AI). Prediksi keluar, Kesenjangan keahlian, dan Coaching AI
// baru tampil bila datanya cukup (`GET /api/hr/ai/kesiapan`) — dulu tampil kosong/tebakan karena KPI, LMS, skill = 0.
const AsistenAIModule = lazyRetry(() => import('../asisten/AsistenAIModule'));
const HRAttritionModule = lazyRetry(() => import('../hr/HRAttritionModule'));
const HRSkillGapModule = lazyRetry(() => import('../hr/HRSkillGapModule'));
const HRCoachingModule = lazyRetry(() => import('../hr/HRCoachingModule'));

const TAMBAHAN = [
  { key: 'attrition', label: 'Prediksi keluar', Component: HRAttritionModule },
  { key: 'skill-gap', label: 'Kesenjangan keahlian', Component: HRSkillGapModule },
  { key: 'coaching', label: 'Coaching AI', Component: HRCoachingModule },
];

export default function HRAIHub(props) {
  const [siap, setSiap] = useState({});
  useEffect(() => {
    let off = false;
    apiFetch('/hr/ai/kesiapan').then((d) => { if (!off) setSiap(d || {}); }).catch(() => { if (!off) setSiap({}); });
    return () => { off = true; };
  }, []);
  const tabs = [
    { key: 'asisten', label: 'Asisten AI', Component: AsistenAIModule, props: { ruang: 'sdm' } },
    ...TAMBAHAN.filter((t) => siap[t.key]?.siap),
  ];
  return (
    <HubTabs
      key={tabs.map((t) => t.key).join('|')}
      hubId="hr-ai-hub"
      title="AI SDM"
      subtitle="Asisten AI untuk data SDM: pengecualian absensi, koreksi absen, draf shift, dan cek gaji sebelum finalisasi."
      tabs={tabs}
      {...props}
    />
  );
}
