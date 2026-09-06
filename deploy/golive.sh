#!/usr/bin/env bash
# golive.sh — muat DATA NYATA (workbook master klien) ke VPS. Mengikuti docs/GO_LIVE_RUNBOOK.md;
# semua skrip Python dijalankan DI DALAM container backend (env MONGO_URL/DB_NAME sudah ada di sana).
#
# Berkas Excel TIDAK ada di GitHub (folder private/ di-gitignore) → unggah dulu dari laptop:
#   scp MASTER_DATA_DA_PERBAIKAN_2.xlsx root@187.77.116.148:/opt/dahost/deploy/golive/
#
# Urutan di VPS (dari folder repo):
#   bash deploy/golive.sh prepare MASTER_DATA_DA_PERBAIKAN_2.xlsx   # → golive/MASTER_DATA_DA_GOLIVE.xlsx (+ sheet DAFTAR_PERBAIKAN)
#   bash deploy/golive.sh gate                                      # gate importir (harus hijau)
#   bash deploy/golive.sh audit                                     # inventaris data sekarang (read-only)
#   bash deploy/golive.sh check                                     # dry-run impor → harus 0 kesalahan
#   bash deploy/golive.sh reset                                     # kosongkan data demo (mongodump dulu), restart backend
#   bash deploy/golive.sh apply                                     # impor --apply 2× (uji idempoten)
# Bila workbook go-live sudah jadi, langsung taruh sebagai golive/MASTER_DATA_DA_GOLIVE.xlsx dan lewati `prepare`.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
GOLIVE_DIR="$DIR/golive"
mkdir -p "$GOLIVE_DIR"
WB="${WORKBOOK:-MASTER_DATA_DA_GOLIVE.xlsx}"   # nama workbook go-live (override: WORKBOOK=nama.xlsx)
C_DIR=/app/private/golive                        # mount dari deploy/golive (lihat docker-compose.yml)

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mXX  %s\033[0m\n' "$*" >&2; exit 1; }
dc()   { docker compose --env-file .env "$@"; }
be()   { dc exec -T backend "$@"; }
need_wb() { [ -f "$GOLIVE_DIR/$WB" ] || die "Tidak ada $GOLIVE_DIR/$WB. Unggah berkas (scp) atau jalankan: bash deploy/golive.sh prepare <SUMBER.xlsx>"; }
wait_backend() {
  echo -n "menunggu backend "
  for _ in $(seq 1 60); do
    if be curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then echo "OK"; return 0; fi
    echo -n "."; sleep 4
  done
  die "backend belum sehat: cd $DIR && docker compose logs --tail=80 backend"
}

[ -f .env ] || die "deploy/.env tidak ada — jalankan install_vps.sh dulu."
be true 2>/dev/null || die "Container backend tidak berjalan: cd $DIR && docker compose up -d"

case "${1:-}" in
  prepare)
    SRC="${2:?contoh: bash deploy/golive.sh prepare MASTER_DATA_DA_PERBAIKAN_2.xlsx}"
    [ -f "$GOLIVE_DIR/$SRC" ] || die "Tidak ada $GOLIVE_DIR/$SRC — scp berkas ke folder itu dulu."
    log "Menyusun workbook go-live dari $SRC (berkas asli tidak diubah)"
    be python3 /app/scripts/prepare_golive_workbook.py "$C_DIR/$SRC" "$C_DIR/$WB"
    echo "Hasil: $GOLIVE_DIR/$WB — periksa sheet DAFTAR_PERBAIKAN (24 baris katalog DA-4401-* menunggu jawaban klien)."
    ;;
  gate)
    log "Gate importir (hanya menyentuh dokumen ber-TAG uji)"
    be python3 /app/scripts/verify_impor_master_template.py
    ;;
  audit)
    OUT="audit_$(date +%F_%H%M).json"
    log "Inventaris data (read-only) → $GOLIVE_DIR/$OUT"
    be python3 /app/scripts/audit_data_demo.py --json "$C_DIR/$OUT"
    ;;
  check)
    need_wb
    log "Dry-run impor $WB (tidak menulis DB) — laporan: $GOLIVE_DIR/laporan_check.xlsx"
    be python3 /app/scripts/import_master_template.py "$C_DIR/$WB" --report "$C_DIR/laporan_check.xlsx"
    ;;
  reset)
    log "Rencana reset (dry-run)"
    be python3 /app/scripts/reset_for_golive.py
    be sh -c 'command -v mongodump >/dev/null' \
      || die "mongodump tidak ada di image backend (dibutuhkan untuk backup sebelum reset). Rebuild: cd $DIR && docker compose build --no-cache backend && docker compose up -d backend"
    printf '\n\033[1;33mSemua data operasional/demo akan DIHAPUS (konfigurasi & superadmin utuh; mongodump ke volume backups dulu).\033[0m\n'
    read -r -p "Ketik HAPUS untuk melanjutkan: " ans
    [ "$ans" = "HAPUS" ] || { echo "Dibatalkan."; exit 1; }
    be python3 /app/scripts/reset_for_golive.py --apply --yes
    log "Restart backend agar seed startup (COA/roles/proses) berjalan ulang TANPA lokasi bawaan (SEED_DEFAULT_LOCATIONS=false)"
    dc restart backend
    wait_backend
    ;;
  apply)
    need_wb
    log "Impor --apply (1/2)"
    be python3 /app/scripts/import_master_template.py "$C_DIR/$WB" --apply --report "$C_DIR/laporan_apply_1.xlsx"
    log "Impor --apply (2/2) — uji idempoten: semua angka harus pindah ke kolom 'diperbarui'"
    be python3 /app/scripts/import_master_template.py "$C_DIR/$WB" --apply --report "$C_DIR/laporan_apply_2.xlsx"
    PW="$(grep '^MASTER_IMPORT_INITIAL_PASSWORD=' .env | cut -d= -f2-)"
    cat <<DONE

Selesai. Langkah berikutnya:
  · Portal Produksi → Costing → Terapkan HPP
  · 25 akun 17_USER login dengan sandi awal '${PW:-Dewi@123}' → wajib ganti sandi saat login pertama
  · Email usulan (nama@dewiaditya.id) di 17_USER → perbaiki di Excel lalu 'apply' ulang sebelum dibagikan
DONE
    ;;
  *)
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
