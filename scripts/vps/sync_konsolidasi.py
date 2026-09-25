"""Sinkron master data konsolidasi ke VPS TANPA menghapus data lain & TANPA duplikasi.

  EKSPOR (di lingkungan ini):
    cd /app/backend && set -a && . .env && set +a && python ../scripts/vps/sync_konsolidasi.py export --file /app/private/konsolidasi_master.json.gz
  PRATINJAU di VPS (tidak menulis):
    MONGO_URL=... DB_NAME=... python scripts/vps/sync_konsolidasi.py import --file konsolidasi_master.json.gz --dry-run
  TERAPKAN di VPS:
    MONGO_URL=... DB_NAME=... python scripts/vps/sync_konsolidasi.py import --file konsolidasi_master.json.gz

Aturan (anti-hapus, anti-duplikat):
  • Hanya koleksi MASTER di bawah ini yang disentuh; transaksi (stok, ledger, order, keuangan, user) TIDAK disentuh.
  • Dokumen dicari lewat KUNCI ALAMI (code / sku / model+warna+ukuran), bukan _id → data awal yang belum lengkap
    di VPS akan DIPERBARUI, bukan digandakan. Dokumen VPS yang tidak ada di berkas TIDAK dihapus.
  • Mode `merge`: hanya kolom konsolidasi yang ditimpa (kolom lain yang sudah diisi di VPS — foto, berat, SOP — tetap).
  • Mode `replace`: seluruh dokumen ditimpa (untuk data yang sepenuhnya milik konsolidasi: material, BOM, warna, ukuran).
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

from bson import json_util
from pymongo import MongoClient, UpdateOne

# (koleksi, kunci alami, mode, kolom yang di-merge [None = semua])
SPEC = [
    ("rahaza_colors", ["code"], "replace", None),
    ("rahaza_sizes", ["code"], "replace", None),
    ("rahaza_materials", ["code"], "replace", None),
    ("rahaza_models", ["code"], "merge", ["id", "name", "category", "category_id", "category_name", "active", "rnd_style_id",
                                          "hpp", "hpp_source", "hpp_validation", "hpp_updated_at", "size_list", "size_ids", "updated_at"]),
    ("rahaza_model_variants", ["sku"], "merge", ["id", "model_id", "model_code", "model_name", "size_id", "size_code", "color_id", "color_code",
                                                 "color_name", "color_hex", "active", "created_from", "updated_at"]),
    ("rahaza_boms", ["model_id", "color_code", "size_id", "version"], "replace", None),
    ("dewi_rnd_styles", ["style_code"], "merge", ["id", "style_name", "status", "promoted_to_model_id", "techpack_name", "category", "updated_at"]),
    ("dewi_rnd_variants", ["style_code", "color_code"], "merge", None),
    ("dewi_rnd_tech_packs", ["style_id", "version"], "merge", None),
    ("dewi_rnd_materials", ["material_code"], "merge", None),
    ("rahaza_material_cost_history", ["id"], "insert_only", None),
]
SKIP_FIELDS = {"_id"}


def export(db, path):
    out = {"exported_at": datetime.now(timezone.utc).isoformat(), "db": db.name, "collections": {}}
    for coll, keys, mode, fields in SPEC:
        docs = list(db[coll].find({}, {"_id": 0}))
        out["collections"][coll] = docs
        print(f"  {coll:32s} {len(docs)}")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json_util.dumps(out))
    print("→", path)


def _key(doc, keys):
    return {k: doc.get(k) for k in keys}


def import_(db, path, dry_run: bool):
    data = json_util.loads(gzip.open(path, "rt", encoding="utf-8").read())
    print(f"Berkas dari DB '{data['db']}' @ {data['exported_at']} → target '{db.name}' {'(DRY-RUN)' if dry_run else ''}")
    summary = {}
    for coll, keys, mode, fields in SPEC:
        docs = data["collections"].get(coll, [])
        existing = {}
        proj = {k: 1 for k in keys} | {"_id": 0, "id": 1}
        for d in db[coll].find({}, proj):
            existing[json.dumps(_key(d, keys), sort_keys=True, default=str)] = d
        ops, c = [], Counter()
        for doc in docs:
            k = _key(doc, keys)
            if any(v in (None, "") for v in k.values()):
                c["kunci_kosong_dilewati"] += 1
                continue
            body = {kk: v for kk, v in doc.items() if kk not in SKIP_FIELDS}
            hit = existing.get(json.dumps(k, sort_keys=True, default=str))
            if hit is None:
                ops.append(UpdateOne(k, {"$setOnInsert": body}, upsert=True))
                c["baru"] += 1
            elif mode == "insert_only":
                c["sudah_ada"] += 1
            elif mode == "replace":
                if hit.get("id") and hit["id"] != body.get("id"):
                    body["id"] = hit["id"]  # jaga id VPS agar relasi lain di VPS tidak putus
                ops.append(UpdateOne(k, {"$set": body}))
                c["ditimpa"] += 1
            else:  # merge
                sub = {kk: v for kk, v in body.items() if (fields is None or kk in fields) and kk != "id"}
                ops.append(UpdateOne(k, {"$set": sub}))
                c["digabung"] += 1
        # duplikat kunci alami yang SUDAH ada di VPS → laporkan (tidak dihapus otomatis)
        dup = [k for k, n in Counter(json.dumps(_key(d, keys), sort_keys=True, default=str) for d in db[coll].find({}, proj)).items() if n > 1]
        if dup:
            c["DUPLIKAT_DI_VPS"] = len(dup)
        if ops and not dry_run:
            db[coll].bulk_write(ops, ordered=False)
        summary[coll] = dict(c)
        print(f"  {coll:32s} {dict(c)}")
    if not dry_run:
        db.sync_log.insert_one({"type": "konsolidasi_master", "file": os.path.basename(path), "from_db": data["db"],
                                "exported_at": data["exported_at"], "applied_at": datetime.now(timezone.utc), "summary": summary})
    return summary


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("export", "import"):
        print(__doc__)
        sys.exit(1)
    path = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else "/app/private/konsolidasi_master.json.gz"
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    if sys.argv[1] == "export":
        export(db, path)
    else:
        import_(db, path, "--dry-run" in sys.argv)


if __name__ == "__main__":
    main()
