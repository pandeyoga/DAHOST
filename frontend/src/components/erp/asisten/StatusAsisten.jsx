/**
 * StatusAsisten — tampilan Asisten AI saat belum bisa menjawab (`GET /api/asisten-ai/status`: kunci API kosong,
 * AI dimatikan, anggaran habis, server tidak menjawab). "Tindakan AI" (Tahap B) dan "Ingatan AI" (Tahap D) kini halaman
 * sendiri (`asisten-ai-tindakan`, `asisten-ai-ingatan`), jadi tempat "tahap berikutnya" sudah dihapus.
 */
import { CloudOff, Hourglass, KeyRound, Power, UserX, Wallet } from 'lucide-react';
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
  // Asisten AI per pengguna (10 Nov 2026): akun ini dimatikan owner / batas pertanyaan hari ini tercapai.
  if (alasan === 'pengguna_nonaktif') {
    return (
      <EmptyState icon={UserX} title="Asisten AI belum aktif untuk akun Anda" testId="asisten-status-pengguna-nonaktif"
        description="Owner mengatur siapa yang boleh memakai Asisten AI. Minta owner menyalakannya untuk akun Anda di Monitor AI › Pengaturan › Asisten AI per pengguna. Riwayat percakapan Anda tetap bisa dibuka."
        action={keMonitor} />
    );
  }
  if (alasan === 'batas_pertanyaan') {
    return (
      <EmptyState icon={Hourglass} title="Batas pertanyaan hari ini sudah tercapai" testId="asisten-status-batas-pertanyaan"
        description={`${status.data?.pesan || 'Batas pertanyaan Asisten AI untuk akun Anda hari ini sudah tercapai.'} Riwayat percakapan tetap bisa dibuka.`} />
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
  pengguna_nonaktif: 'Asisten AI belum aktif untuk akun Anda',
  batas_pertanyaan: 'Batas pertanyaan hari ini sudah tercapai',
};

/** Galat jawaban yang berarti status AKUN berubah (Asisten AI per pengguna) → layar memuat ulang status. */
export const KODE_GALAT_AKUN = ['pengguna_nonaktif', 'batas_pertanyaan'];
