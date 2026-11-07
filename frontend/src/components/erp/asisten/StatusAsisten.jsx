/**
 * StatusAsisten — tampilan Asisten AI saat belum bisa menjawab (`GET /api/asisten-ai/status`: kunci API kosong,
 * AI dimatikan, anggaran habis, server tidak menjawab) dan tempat "Tindakan AI" / "Ingatan AI" (Tahap B/D).
 */
import { Brain, CloudOff, KeyRound, ListChecks, Power, Wallet } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '../moduleAtoms';
import { canAccessPortal } from '../portalAccess';

const PERAN_MONITOR = ['superadmin', 'admin', 'manager', 'owner'];

export function StatusBelumSiap({ status, peran, onNavigate, onCobaLagi }) {
  if (status.memuat) {
    return (
      <div className="space-y-3 p-4" data-testid="asisten-status-memuat">
        <Skeleton className="h-6 w-1/3" /><Skeleton className="h-20 w-full" />
      </div>
    );
  }
  const admin = canAccessPortal(peran, 'sysadmin');
  const bolehMonitor = PERAN_MONITOR.includes(String(peran || '').toLowerCase());
  const keMonitor = bolehMonitor && onNavigate ? { label: 'Buka Monitor AI', variant: 'outline', onClick: () => onNavigate('ai-usage-monitor') } : undefined;
  if (status.galat) {
    return (
      <EmptyState icon={CloudOff} title="Asisten AI belum bisa dihubungi" testId="asisten-status-galat"
        description={`${status.galat} Periksa koneksi, lalu coba lagi.`}
        action={{ label: 'Coba lagi', variant: 'outline', onClick: onCobaLagi, testId: 'asisten-status-coba' }} />
    );
  }
  const alasan = status.data?.alasan;
  if (alasan === 'kunci_kosong') {
    return (
      <EmptyState icon={KeyRound} title="Kunci API AI belum diisi" testId="asisten-status-kunci-kosong"
        description="Minta admin mengisi kunci API di Administrasi Sistem › Pengaturan Sistem › API Keys. Setelah diisi, Asisten AI langsung bisa dipakai."
        action={admin && onNavigate ? { label: 'Buka API Keys', variant: 'outline', onClick: () => onNavigate('mgmt-system-hub', { tab: 'api' }), testId: 'asisten-buka-api-keys' } : undefined} />
    );
  }
  if (alasan === 'anggaran_habis') {
    return (
      <EmptyState icon={Wallet} title="Anggaran AI sudah habis" testId="asisten-status-anggaran-habis"
        description="Batas biaya harian atau bulanan sudah tercapai. Admin bisa menaikkan batas di Monitor AI › Pengaturan, atau coba lagi besok."
        action={keMonitor} />
    );
  }
  return (
    <EmptyState icon={Power} title="Asisten AI sedang dimatikan" testId="asisten-status-ai-nonaktif"
      description="Fitur AI dimatikan admin di Monitor AI › Pengaturan. Hubungi admin untuk menyalakannya."
      action={keMonitor} />
  );
}

export const PLACEHOLDER_BELUM_SIAP = {
  kunci_kosong: 'Asisten AI belum siap: kunci API belum diisi',
  ai_nonaktif: 'Asisten AI sedang dimatikan admin',
  anggaran_habis: 'Anggaran AI sudah habis',
};

export function TahapBerikut({ jenis, onKembali }) {
  const tindakan = jenis === 'tindakan';
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto">
      <EmptyState
        icon={tindakan ? ListChecks : Brain}
        testId={tindakan ? 'asisten-tindakan-kosong' : 'asisten-ingatan-kosong'}
        title={tindakan ? 'Tindakan AI hadir di tahap berikutnya' : 'Ingatan AI hadir di tahap berikutnya'}
        description={tindakan
          ? 'Nanti di sini tampil perubahan data yang diusulkan Asisten AI dan menunggu persetujuan Anda, lengkap dengan riwayat dan tombol batalkan.'
          : 'Nanti di sini Anda bisa melihat, mengubah, dan menghapus hal yang diingat Asisten AI, mis. target pertumbuhan atau toko prioritas.'}
        action={{ label: 'Kembali ke percakapan', variant: 'outline', onClick: onKembali, testId: 'asisten-kembali-chat' }}
      />
    </div>
  );
}
