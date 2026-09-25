#!/usr/bin/env bash
# =============================================================================
# SEED DATA NYATA (GO-LIVE) — restore snapshot DB klien ke MONGO_URL/DB_NAME.
#
# Sumber: seed/DA_SEED_GOLIVE.archive.gz  (mongodump --archive --gzip, DB 'dahost_erp')
#   = backup VPS klien 2026-09-17 13:02 WIB + SELURUH berkas klien DATA_YANG_PERLU_DIISI_DA (2).xlsx diterapkan
#     (BOM aksesoris 62 model · 229 harga jual SKU · 30 SKU nonaktif · 7 toko→rekening).
#     Angka: model 104 · varian aktif 615/nonaktif 30 · FG 645 (berharga 583) · BOM 634 (aktif 604).
#   Ini BUKAN data demo. Jangan jalankan seeder demo (/api/seed/*) di atasnya.
#
# Pakai:
#   bash scripts/seed_golive_restore.sh            # hanya bila DB kosong (rahaza_models = 0)
#   bash scripts/seed_golive_restore.sh --force    # timpa DB yang ada (backup otomatis dulu)
#   bash scripts/seed_golive_restore.sh --baseline # pakai snapshot VPS murni (sebelum BOM)
#
# Idempoten: restore --drop menghasilkan keadaan yang sama persis setiap kali.
# =============================================================================
set -euo pipefail
APP=$(cd "$(dirname "$0")/.." && pwd)
ARCHIVE="$APP/seed/DA_SEED_GOLIVE.archive.gz"
FORCE=0
for a in "$@"; do case "$a" in
  --force) FORCE=1;;
  --baseline) ARCHIVE="$APP/seed/vps_baseline_20260917_130216.archive.gz";;
esac; done

set -a; . "$APP/backend/.env"; set +a
: "${MONGO_URL:?MONGO_URL wajib ada di backend/.env}"
: "${DB_NAME:?DB_NAME wajib ada di backend/.env}"
[ -f "$ARCHIVE" ] || { echo "✗ arsip seed tidak ada: $ARCHIVE"; exit 1; }
command -v mongorestore >/dev/null || { echo "✗ mongorestore tidak terpasang"; exit 1; }

count(){ python3 - "$1" <<'PY'
import os, sys
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
print(db[sys.argv[1]].count_documents({}))
PY
}
SRC_DB=$(python3 - "$ARCHIVE" <<'PY'
import sys, gzip, struct, bson
with gzip.open(sys.argv[1], "rb") as f:
    f.read(4)  # magic
    for _ in range(3):  # header, lalu metadata koleksi pertama (memuat 'db')
        raw = f.read(4)
        if len(raw) < 4:
            break
        ln = struct.unpack("<i", raw)[0]
        doc = bson.decode(raw + f.read(ln - 4))
        if doc.get("db"):
            print(doc["db"]); break
PY
) 2>/dev/null || SRC_DB=""
[ -n "$SRC_DB" ] || SRC_DB="dahost_erp"

EXISTING=$(count rahaza_models)
if [ "$EXISTING" != "0" ] && [ "$FORCE" = "0" ]; then
  echo "· DB '$DB_NAME' sudah berisi data (rahaza_models=$EXISTING) — tidak disentuh. Pakai --force untuk menimpa."
  exit 0
fi
if [ "$EXISTING" != "0" ]; then
  mkdir -p "$APP/backups"
  BK="$APP/backups/pre_seed_restore_$(date +%Y%m%d_%H%M%S).archive.gz"
  mongodump --uri "$MONGO_URL" --db "$DB_NAME" --gzip --archive="$BK" >/dev/null 2>&1 && echo "· backup DB lama → $BK"
fi

echo "· restore $(basename "$ARCHIVE") ($SRC_DB → $DB_NAME) ..."
python3 - <<'PY'
import os
from pymongo import MongoClient
MongoClient(os.environ["MONGO_URL"]).drop_database(os.environ["DB_NAME"])
PY
mongorestore --uri "$MONGO_URL" --gzip --archive="$ARCHIVE" --drop \
  --nsInclude "$SRC_DB.*" --nsFrom "$SRC_DB.*" --nsTo "$DB_NAME.*" 2>&1 | tail -1
echo "· model=$(count rahaza_models) varian=$(count rahaza_model_variants) material=$(count rahaza_materials) bom=$(count rahaza_boms) user=$(count users) karyawan=$(count rahaza_employees) katalog=$(count marketing_catalog_items)"
if command -v supervisorctl >/dev/null; then sudo supervisorctl restart backend >/dev/null 2>&1 && echo "· backend di-restart"; fi
echo "✓ seed go-live terpasang. Login: admin@garment.com / Admin@123"
