#!/usr/bin/env python3
"""scripts/cleanup_demo_data.py — K7 (keputusan owner 2026-11-02): BERSIHKAN DATA DEMO.

Audit m.md §P-3: data go-live memuat dokumen buatan SEEDER demo (30 retur, 40 komplain,
80 ulasan, 70 sampel, 30 kalender konten, 10 diskon, 8 peluncuran, 36 sesi live,
70 kesehatan akun, katalog demo) + 3 sub-akun COA uji `1-1303-GATE42-…`.

ATURAN KERAS
  * DRY-RUN BAWAAN — tanpa `--terapkan` tidak ada satu dokumen pun yang diubah.
  * BACKUP JSON per koleksi (bson json_util, bisa di-`mongoimport`) DITULIS LEBIH DULU
    sebelum penghapusan; bila backup gagal, tidak ada yang dihapus.
  * KRITERIA DEMO TEGAS per koleksi (tabel RULES di bawah): penanda seeder
    (`_seed_origin`, `created_by=system`, `_import_session_id=seed-demo`, `source=seed_demo`)
    DIGABUNG pola seeder (teks template/nama fiktif). Dokumen yang hanya cocok sebagian
    TIDAK dihapus — dilaporkan sebagai "ragu".
  * Retur demo yang sudah punya keputusan Retur Fisik gudang (stok/jurnal bergerak) TIDAK
    dihapus; pekerjaan gudang Pending yang menempel ikut dihapus.
  * Sub-akun COA uji hanya dihapus bila TIDAK punya baris jurnal & tidak dirujuk toko.
  * Hanya DB dari env `DB_NAME` (+ `MONGO_URL`). Jangan jalankan di DB produksi tanpa
    membaca laporan dry-run dan menyimpan backupnya.

Pakai:
    python3 scripts/cleanup_demo_data.py                       # laporan (dry-run)
    python3 scripts/cleanup_demo_data.py --out-dir /tmp/demo   # laporan + backup ke folder itu
    python3 scripts/cleanup_demo_data.py --terapkan            # backup DULU, lalu hapus
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# ── pola seeder (disalin dari seeder yang membuatnya; jangan diperluas tanpa bukti) ──
DEMO_PRODUCTS = [  # routes/marketing_returns_routes.seed_returns_if_empty + marketing_reviews_routes
    "Gamis Daluna Basic", "Khimar Syari Premium", "Tunik Busui Friendly", "Set Gamis + Khimar",
    "Outer Cardigan", "Rok Plisket Panjang", "Dress Casual", "Hijab Segiempat", "Inner Manset",
    "Celana Kulot",
]
DEMO_RETURN_DETAILS = [  # seed_returns_if_empty.return_templates[].detail
    "Terlalu kecil, size XL seperti M", "Warna berbeda dari foto", "Ada bolong di bagian jahitan",
    "Lebih gelap dari gambar", "Bahan lebih tipis dari yang diharapkan",
]
NO_IMPORT = {"$in": [None, ""]}

# (koleksi, kueri penanda TEGAS, kueri "penanda sebagian" untuk laporan ragu, keterangan)
RULES = [
    ("marketing_returns",
     {"created_by": "system", "reason_detail": {"$in": DEMO_RETURN_DETAILS}},
     {"created_by": "system"},
     "seed_returns_if_empty: created_by=system + teks alasan template seeder"),
    ("marketing_complaints",
     {"_import_session_id": "seed-demo"},
     {"_import_session_id": "seed-demo"},
     "seed_complaints_if_empty: _import_session_id=seed-demo"),
    ("marketing_reviews",
     {"created_by": "system", "product": {"$in": DEMO_PRODUCTS}, "_import_session_id": NO_IMPORT},
     {"created_by": "system"},
     "seed_reviews_if_empty: created_by=system + nama produk fiktif seeder"),
    ("marketing_samples", {"_seed_origin": True, "created_by": "system"}, {"_seed_origin": True},
     "seed_samples_if_empty: _seed_origin + created_by=system"),
    ("marketing_content_calendar", {"_seed_origin": True, "created_by": "system"}, {"_seed_origin": True},
     "seed_content_calendar_if_empty: _seed_origin + created_by=system"),
    ("marketing_discounts", {"_seed_origin": True, "created_by": "system"}, {"_seed_origin": True},
     "seed_discounts_if_empty: _seed_origin + created_by=system"),
    ("marketing_live_sessions", {"_seed_origin": True, "created_by": "system"}, {"_seed_origin": True},
     "seed_live_if_empty: _seed_origin + created_by=system"),
    ("marketing_product_launches", {"_seed_origin": True, "created_by": "system"}, {"_seed_origin": True},
     "seed_product_launches_if_empty: _seed_origin + created_by=system"),
    ("marketing_ads_data", {"_seed_origin": True, "created_by": "system"}, {"_seed_origin": True},
     "seed_ads_if_empty: _seed_origin + created_by=system (kampanye 'Summer Fashion Collection'…)"),
    ("marketing_account_health",
     {"source": {"$exists": False}, "_import_session_id": {"$exists": False},
      "created_by": {"$exists": False}, "notes": []},
     {"source": {"$exists": False}, "_import_session_id": {"$exists": False}},
     "seed_health_if_empty: tanpa source/impor/pembuat (entri manual ber-source=manual, impor ber-sesi)"),
    ("marketing_catalog_items",
     {"_seed_origin": True, "source": "seed_demo", "created_by": "system"},
     {"_seed_origin": True},
     "ensure_demo_catalogs: item katalog demo (source=seed_demo, nama fiktif, tanpa FG)"),
]
COA_TEST_REGEX = "^1-1303-GATE42-"
# Rujukan yang membuat item katalog demo TIDAK boleh dihapus (transaksi nyata memakainya).
CATALOG_REFS = (("marketing_orders", "items.catalog_item_id"), ("marketing_orders", "catalog_item_id"),
                ("marketing_returns", "catalog_item_id"), ("marketing_reviews", "catalog_item_id"),
                ("marketing_samples", "catalog_item_id"))


async def plan(db) -> dict:
    out = {"collections": {}, "coa": {}, "wh_returns": {}, "skipped": []}
    for coll, q, loose, why in RULES:
        rows = await db[coll].find(q, {"_id": 0}).to_list(100000)
        loose_n = await db[coll].count_documents(loose)
        if coll == "marketing_catalog_items" and rows:
            keep = set()
            ids = [r["id"] for r in rows if r.get("id")]
            for rc, f in CATALOG_REFS:
                for d in await db[rc].find({f: {"$in": ids}}, {"_id": 0, f.split(".")[0]: 1}).to_list(100000):
                    v = d.get(f.split(".")[0])
                    vals = [x.get("catalog_item_id") for x in v] if isinstance(v, list) else [v]
                    keep |= {x for x in vals if x in ids}
            if keep:
                out["skipped"].append({"collection": coll, "count": len(keep),
                                       "why": "item katalog demo dirujuk transaksi — tidak dihapus"})
                rows = [r for r in rows if r.get("id") not in keep]
        if coll == "marketing_returns" and rows:
            decided, pending_wh = [], []
            for r in rows:
                whs = await db.wh_returns.find({"source_marketing_return_id": r["id"]}, {"_id": 0}).to_list(10)
                if any(w.get("status") in ("Resolved", "Reversed") for w in whs):
                    decided.append(r["id"])
                else:
                    pending_wh += whs
            if decided:
                out["skipped"].append({"collection": coll, "count": len(decided),
                                       "why": "retur demo sudah diputuskan gudang (stok/jurnal) — tidak dihapus"})
                rows = [r for r in rows if r["id"] not in set(decided)]
            out["wh_returns"] = {"docs": pending_wh, "why": "pekerjaan Retur Fisik milik retur demo (belum diputuskan)"}
        out["collections"][coll] = {"docs": rows, "why": why, "loose_match": loose_n,
                                    "ragu": max(loose_n - len(rows), 0)}
    accs = await db.rahaza_coa_accounts.find({"code": {"$regex": COA_TEST_REGEX}}, {"_id": 0}).to_list(1000)
    used = set(await db.marketing_platform_accounts.distinct("ar_account_code"))
    coa_del, coa_keep = [], []
    for a in accs:
        n = await db.rahaza_journal_lines.count_documents({"account_code": a["code"]})
        (coa_keep if (n or a["code"] in used) else coa_del).append({**a, "_journal_lines": n})
    out["coa"] = {"docs": coa_del, "kept": coa_keep, "why": "sub-akun COA uji GATE42 tanpa jurnal & tanpa toko"}
    return out


def summary(p: dict) -> list:
    lines = []
    for coll, c in p["collections"].items():
        lines.append(f"  {coll:30s} hapus {len(c['docs']):4d}  (penanda sebagian {c['loose_match']:4d}, "
                     f"ragu {c['ragu']:3d}) — {c['why']}")
        for d in c["docs"][:3]:
            label = d.get("product") or d.get("name") or d.get("title") or d.get("campaign_name") \
                or d.get("account_name") or d.get("customer_name") or d.get("id")
            lines.append(f"      · {str(label)[:70]}")
    lines.append(f"  {'wh_returns':30s} hapus {len(p['wh_returns'].get('docs') or []):4d} — "
                 f"{p['wh_returns'].get('why', 'pekerjaan gudang milik retur demo')}")
    lines.append(f"  {'rahaza_coa_accounts':30s} hapus {len(p['coa']['docs']):4d} — {p['coa']['why']}: "
                 f"{', '.join(a['code'] for a in p['coa']['docs']) or '-'}"
                 + (f" · DIPERTAHANKAN (ada jurnal/dirujuk): {', '.join(a['code'] for a in p['coa']['kept'])}"
                    if p["coa"]["kept"] else ""))
    for s in p["skipped"]:
        lines.append(f"  ! {s['collection']}: {s['count']} dilewati — {s['why']}")
    return lines


def write_backup(p: dict, out_dir: Path) -> dict:
    from bson import json_util
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    groups = {k: v["docs"] for k, v in p["collections"].items()}
    groups["wh_returns"] = p["wh_returns"].get("docs") or []
    groups["rahaza_coa_accounts"] = [{k: v for k, v in a.items() if k != "_journal_lines"}
                                     for a in p["coa"]["docs"]]
    for coll, docs in groups.items():
        if not docs:
            continue
        f = out_dir / f"{coll}.json"
        f.write_text(json_util.dumps(docs, indent=1, ensure_ascii=False), encoding="utf-8")
        files[coll] = {"file": str(f), "count": len(docs)}
    (out_dir / "MANIFEST.json").write_text(json.dumps(
        {"created_at": datetime.now(timezone.utc).isoformat(), "db": os.environ.get("DB_NAME"),
         "files": files}, indent=1), encoding="utf-8")
    return files


async def apply(db, p: dict) -> dict:
    res = {}
    for coll, c in p["collections"].items():
        ids = [d["id"] for d in c["docs"] if d.get("id")]
        if ids:
            r = await db[coll].delete_many({"id": {"$in": ids}})
            res[coll] = r.deleted_count
    wh_ids = [d["id"] for d in (p["wh_returns"].get("docs") or []) if d.get("id")]
    if wh_ids:
        res["wh_returns"] = (await db.wh_returns.delete_many(
            {"id": {"$in": wh_ids}, "status": {"$nin": ["Resolved", "Reversed"]}})).deleted_count
    codes = [a["code"] for a in p["coa"]["docs"]]
    if codes:
        res["rahaza_coa_accounts"] = (await db.rahaza_coa_accounts.delete_many({"code": {"$in": codes}})).deleted_count
    return res


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--terapkan", action="store_true", help="hapus sungguhan (setelah backup)")
    ap.add_argument("--out-dir", default="", help="folder backup/laporan (bawaan: ./cleanup_demo_<waktu>)")
    a = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "backend" / ".env")
    except Exception:  # noqa: BLE001 — env dari container juga cukup
        pass
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    db = client[os.environ["DB_NAME"]]
    try:
        p = await plan(db)
        mode = "TERAPKAN" if a.terapkan else "DRY-RUN (tidak ada yang diubah)"
        print(f"[K7] Pembersih data demo · DB {os.environ['DB_NAME']} · {mode}")
        print("\n".join(summary(p)))
        total = sum(len(c["docs"]) for c in p["collections"].values()) \
            + len(p["wh_returns"].get("docs") or []) + len(p["coa"]["docs"])
        print(f"  TOTAL akan dihapus: {total} dokumen")
        out_dir = Path(a.out_dir or f"cleanup_demo_{datetime.now():%Y%m%d_%H%M%S}")
        if not a.terapkan:
            if a.out_dir:
                files = write_backup(p, out_dir)
                print(f"  (dry-run) salinan calon hapus ditulis ke {out_dir} — {len(files)} berkas")
            print("\nJalankan ulang dengan --terapkan untuk backup + hapus.")
            return 0
        files = write_backup(p, out_dir)
        print(f"  BACKUP: {out_dir} ({sum(f['count'] for f in files.values())} dokumen, {len(files)} berkas)")
        res = await apply(db, p)
        print(f"  DIHAPUS: {res}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
