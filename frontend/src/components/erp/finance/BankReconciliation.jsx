import { useState } from 'react';
import { PageHeader } from '../moduleAtoms';
import { SessionList } from './bankrecon/SessionList';
import { SessionDetail } from './bankrecon/SessionDetail';

// Rekonsiliasi Bank (H-05/H-06): mutasi rekening koran ↔ baris jurnal GL akun bank per rekening kas/bank.
export default function BankReconciliation({ headers }) {
  const [activeSession, setActiveSession] = useState(null);

  return (
    <div className="space-y-4" data-testid="bank-recon-module">
      {/* PANDUAN_UI G1/G2 (2026-11-04): lebar penuh + kepala halaman standar (dulu bingkai sempit di tengah) */}
      <PageHeader title="Rekonsiliasi Bank" subtitle="Cocokkan mutasi rekening koran dengan buku besar, per rekening per bulan." />

      {activeSession ? (
        <SessionDetail sessionId={activeSession.id} headers={headers} onBack={() => setActiveSession(null)} />
      ) : (
        <SessionList headers={headers} onOpen={setActiveSession} />
      )}
    </div>
  );
}
