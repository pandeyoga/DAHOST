/**
 * AccessBadge — penanda tingkat akses dokumen (pemilik | admin | ubah | lihat).
 * Standar UI/UX v2: memakai StatusBadge (token warna) — dulu kelas warna & ukuran huruf 10px buatan sendiri.
 */
import { StatusBadge } from '../moduleAtoms';
import { ACCESS_CONFIG } from './utils';

export default function AccessBadge({ level }) {
  const cfg = ACCESS_CONFIG[level] || ACCESS_CONFIG.view;
  const Icon = cfg.icon;
  return (
    <StatusBadge status={level || 'view'} tone={cfg.tone}
      label={<><Icon className="h-3 w-3" aria-hidden="true" />{cfg.label}</>} />
  );
}
