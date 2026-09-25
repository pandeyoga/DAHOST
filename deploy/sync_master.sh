#!/usr/bin/env bash
# sync_master.sh — sinkron master data konsolidasi (BOM · SKU · harga · R&D) ke DB VPS
# TANPA menghapus/menduplikasi data lain (kunci alami: kode material, SKU, model+warna+ukuran).
#
#   bash /opt/dahost/deploy/sync_master.sh --dry-run   # pratinjau (tidak menulis apa pun)
#   bash /opt/dahost/deploy/sync_master.sh             # backup dulu → terapkan → log di koleksi sync_log
#
# Berkas data ikut repo: scripts/vps/data/konsolidasi_master_latest.json.gz (dibuat oleh
# `scripts/vps/sync_konsolidasi.py export` di lingkungan pengembangan, sudah ada di image backend).
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR/deploy"
DATA_IN_CONTAINER="/app/scripts/vps/data/konsolidasi_master_latest.json.gz"
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY="--dry-run"

if [ -z "$DRY" ]; then
  echo "==> backup penuh sebelum sinkron"
  bash "$APP_DIR/deploy/backup.sh"
fi

echo "==> sinkron master data ${DRY:+(DRY-RUN — tidak menulis)}"
docker compose --env-file .env exec -T backend \
  python /app/scripts/vps/sync_konsolidasi.py import --file "$DATA_IN_CONTAINER" $DRY

if [ -z "$DRY" ]; then
  echo "==> master potongan (CUT-*) untuk varian yang belum punya (idempoten)"
  docker compose --env-file .env exec -T backend python /app/scripts/backfill_cut_panels.py || true
  echo "==> bukti: kelengkapan BOM"
  docker compose --env-file .env exec -T backend python /app/scripts/laporan_kekosongan_bom.py 2>/dev/null | tail -5 || true
  echo "==> restart backend agar cache master segar"
  docker compose --env-file .env restart backend >/dev/null
  echo "selesai. Log sinkron tersimpan di koleksi 'sync_log'."
fi
