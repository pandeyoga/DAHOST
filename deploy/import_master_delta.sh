#!/usr/bin/env bash
# import_master_delta.sh — timpa HANYA koleksi master produk di VPS dengan isi seed/DA_SEED_GOLIVE.archive.gz
# (BOM aksesoris + harga jual SKU + SKU nonaktif + rekening pencairan toko + HPP). Koleksi operasional
# (pesanan, stok, jurnal, user, notifikasi, log) TIDAK disentuh.
#
#   bash /opt/dahost/deploy/import_master_delta.sh            # pakai seed/DA_SEED_GOLIVE.archive.gz
#   bash /opt/dahost/deploy/import_master_delta.sh <arsip>    # arsip lain hasil mongodump --archive --gzip
#   DRY_RUN=1 bash /opt/dahost/deploy/import_master_delta.sh  # hanya cetak yang akan dilakukan
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR/deploy"
FILE="${1:-$APP_DIR/seed/DA_SEED_GOLIVE.archive.gz}"
[ -f "$FILE" ] || { echo "✗ arsip tidak ada: $FILE"; exit 1; }
DB_NAME="$(grep '^DB_NAME=' .env | cut -d= -f2)"
SRC_DB="${SRC_DB:-dahost_erp}"

# Koleksi yang berubah dibanding backup VPS 2026-09-17 13:02 (dihitung dengan membandingkan isi dokumen):
COLLS=(rahaza_boms rahaza_materials rahaza_model_variants rahaza_models dewi_rnd_styles
       marketing_catalog_items marketing_platform_accounts rahaza_channel_gl_mapping product_cost_snapshots)

NS=(); for c in "${COLLS[@]}"; do NS+=(--nsInclude="$SRC_DB.$c"); done
echo "==> arsip : $FILE"
echo "==> target: db $DB_NAME (koleksi: ${COLLS[*]})"
if [ "${DRY_RUN:-0}" = "1" ]; then echo "(dry-run) mongorestore --drop ${NS[*]} --nsFrom=$SRC_DB.* --nsTo=$DB_NAME.*"; exit 0; fi

echo "==> backup penuh dulu"
bash "$APP_DIR/deploy/backup.sh"
echo "==> restore koleksi master (koleksi lama di-drop lalu diisi ulang)"
docker compose --env-file .env exec -T mongo mongorestore --archive --gzip --drop \
  "${NS[@]}" --nsFrom="$SRC_DB.*" --nsTo="$DB_NAME.*" < "$FILE"
docker compose --env-file .env restart backend >/dev/null
echo "==> verifikasi"
docker compose --env-file .env exec -T mongo mongosh --quiet "$DB_NAME" --eval '
const c = (n, q) => db.getCollection(n).countDocuments(q || {});
print("model            :", c("rahaza_models"));
print("varian aktif     :", c("rahaza_model_variants", {active: {$ne: false}}), "| nonaktif:", c("rahaza_model_variants", {active: false}));
print("barang jadi      :", c("rahaza_materials", {type: "fg"}), "| berharga:", c("rahaza_materials", {type: "fg", retail_price_master: {$gt: 0}}));
print("BOM aktif        :", c("rahaza_boms", {active: {$ne: false}}), "| dgn aksesoris:", c("rahaza_boms", {active: {$ne: false}, "materials.material_type": "accessory"}));
print("toko → rekening  :", c("marketing_platform_accounts", {coa_cash_code: {$exists: true, $ne: ""}}));'
echo "selesai — angka yang diharapkan: model 104 · varian aktif 615 / nonaktif 30 · FG 645 / berharga 583 · BOM aktif 604 · toko 7"
