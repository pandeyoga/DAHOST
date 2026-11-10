"""core.pantau_staf — Monitoring Staf ERP (Portal Manajemen), keputusan owner 10 Nov 2026.

Tiga lapis (usulan `private/audit/usulan_monitoring_staf_2026-11-10.md`, keputusan K1–K12):

  meter     AKTIVITAS — apa yang dilakukan tiap akun per hari (dicatat gerbang izin
            `middleware/module_permission_gate.py`, tanpa input staf).
  katalog   TITIK AKSI — cara MEMBACA data untuk tiap langkah alur / kewajiban berkala (kode, bukan rumus owner).
  aturan    ATURAN KEWAJIBAN — siapa pemegang, batas waktu, cadangan, bobot, aktif (diatur owner di layar).
  pemindai  KEJADIAN — tiap 15 menit: objek yang sudah terpicu → menunggu / terlambat / selesai (bukti dari data,
            bukan centang staf).
  ringkasan bacaan layar: per staf, macet sekarang, per alur, rincian, skor kepatuhan.
  pengingat pesan ringkas harian ke staf + ringkasan owner/admin (K5: tanpa atasan).

Koleksi: `pantau_aktivitas_harian` (log), `kewajiban_aturan` (konfigurasi), `kewajiban_kejadian` (transaksi turunan).
"""
