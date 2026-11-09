/**
 * Portal Saya › Tanya Asisten (audit HR Tahap D, 9 Nov 2026): Asisten AI ruang `saya` — hanya alat data MILIK
 * pengguna sendiri (absen, cuti & saldo, slip gaji final, jadwal shift). Satu modul chat yang sama dengan Portal
 * Manajemen/SDM (`asisten/AsistenAIModule`), riwayat percakapan terpisah per ruang.
 */
import AsistenAIModule from '../asisten/AsistenAIModule';

export default function TanyaAsistenSaya(props) {
  return <AsistenAIModule {...props} ruang="saya" />;
}
