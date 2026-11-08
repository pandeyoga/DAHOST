import React from 'react';
import { lazyRetry } from '../../../lib/lazyRetry';
import HubTabs from './HubTabs';

// PHASE B (6.1.4 #3) — 3 menu absensi → 1 hub "Absensi".
// Standar UI/UX v2 (8 Nov 2026): empat bagian Absen otomatis (dulu tab di dalam tab) dinaikkan jadi tab hub.
// Kunci tab lama tetap: 'manual', 'auto' (= absen otomatis hari ini), 'approval' — dipakai pengalihan menu lama.
const RahazaAttendanceModule         = lazyRetry(() => import('../RahazaAttendanceModule'));
const AbsenOtomatisHariIni           = lazyRetry(() => import('../RahazaAutoAttendanceModule').then((m) => ({ default: m.AbsenOtomatisHariIni })));
const MesinSidikJari                 = lazyRetry(() => import('../RahazaAutoAttendanceModule').then((m) => ({ default: m.MesinSidikJari })));
const BiometrikHP                    = lazyRetry(() => import('../RahazaAutoAttendanceModule').then((m) => ({ default: m.BiometrikHP })));
const PengaturanAbsenOtomatis        = lazyRetry(() => import('../RahazaAutoAttendanceModule').then((m) => ({ default: m.PengaturanAbsenOtomatis })));
const RahazaAttendanceApprovalModule = lazyRetry(() => import('../RahazaAttendanceApprovalModule'));

export default function HRAttendanceHub(props) {
  return (
    <HubTabs
      hubId="hr-attendance-hub"
      title="Absensi"
      subtitle="Absensi harian, absen otomatis lewat HP dan mesin, serta pemeriksaan absen selfie."
      tabs={[
        { key: 'manual', label: 'Absensi harian', Component: RahazaAttendanceModule },
        { key: 'auto', label: 'Absen otomatis', Component: AbsenOtomatisHariIni },
        { key: 'approval', label: 'Persetujuan absen', Component: RahazaAttendanceApprovalModule },
        { key: 'device', label: 'Mesin sidik jari', Component: MesinSidikJari },
        { key: 'webauthn', label: 'Biometrik HP', Component: BiometrikHP },
        { key: 'config', label: 'Pengaturan absen', Component: PengaturanAbsenOtomatis },
      ]}
      {...props}
    />
  );
}
