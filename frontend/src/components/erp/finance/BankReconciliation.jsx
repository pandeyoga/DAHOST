import { useState } from 'react';
import PageLayout from '../layout/PageLayout';
import { SessionList } from './bankrecon/SessionList';
import { SessionDetail } from './bankrecon/SessionDetail';

/**
 * Cetakan layar Rekonsiliasi Bank. Daftar sesi mengisi slot-slotnya sendiri (Sesi baru, pil status, ringkasan,
 * paginasi); sesi yang dibuka tampil di slot `detail` — DI ATAS daftar (PANDUAN_UI G13).
 */
function ReconPage(props) {
  return (
    <PageLayout
      testId="bank-recon-module"
      title="Rekonsiliasi Bank"
      subtitle="Cocokkan mutasi rekening koran dengan buku besar, per rekening per bulan."
      {...props}
    />
  );
}

// Rekonsiliasi Bank (H-05/H-06): mutasi rekening koran ↔ baris jurnal GL akun bank per rekening kas/bank.
// 2026-11-05 (PANDUAN_UI G1/G13): cetakan PageLayout. Dulu tombol "Sesi baru" sendirian di satu baris, dan sesi
// yang dibuka mengganti seluruh layar (tombol panah kembali) — kini panel di atas daftar sesi.
export default function BankReconciliation({ headers }) {
  const [activeSession, setActiveSession] = useState(null);
  const [listTick, setListTick] = useState(0);

  return (
    <SessionList
      Page={ReconPage}
      headers={headers}
      activeId={activeSession?.id}
      reloadKey={listTick}
      onOpen={(s) => setActiveSession((cur) => (cur?.id === s.id ? null : s))}
      detail={activeSession && (
        <SessionDetail key={activeSession.id} sessionId={activeSession.id} headers={headers}
          onBack={() => { setActiveSession(null); setListTick((t) => t + 1); }}
          onChanged={() => setListTick((t) => t + 1)} />
      )}
    />
  );
}
