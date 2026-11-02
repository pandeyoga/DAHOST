#!/usr/bin/env python3
"""scripts/tidy_material_codes.py — rapikan kode master bahan (keputusan barcode owner, 2026-11-02).

Keputusan owner (sudah disetujui):
  * `KN-CND-DST 2` → `KN-CND-DST-2`   (kode berspasi rawan salah ketik/scan)
  * `KN-RTW-HTM 3` → `KN-RTW-HTM-3`
  * `KN-RTW-` digabung ke `KN-RTW-HTM-3` HANYA bila terbukti barang yang sama (nama sama dan tidak
    ada data yang bertentangan). Bila tidak yakin → hanya DILAPORKAN.

Cara kerja:
  1. Cari SEMUA dokumen di semua koleksi yang merujuk kode lama (nilai string = kode lama, tanpa beda
     huruf/spasi tepi) atau id material lama (`material_id` dsb.) — dilaporkan per koleksi & field.
  2. Ganti nama: `rahaza_materials.code` = kode baru, kode lama disimpan di `code_aliases` (label yang
     sudah tertempel tetap terbaca lewat `core.scan_resolver`). Rujukan yang memakai KODE ikut diganti;
     rujukan ber-id tidak perlu diubah (id material tetap). Koleksi log/riwayat hanya dilaporkan.
  3. Gabung: hanya bila `merge_verdict` lolos DAN material sumber belum punya stok/mutasi (penggabungan
     saldo = keputusan manual). Rujukan kode & id dipindah ke target, sumber dinonaktifkan.
  4. Sebelum mengubah apa pun: backup JSON (dokumen material + setiap dokumen yang akan diubah).

DRY-RUN BAWAAN. Pakai:
    python3 scripts/tidy_material_codes.py                      # laporan saja
    python3 scripts/tidy_material_codes.py --terapkan           # ubah (backup JSON dulu)
    python3 scripts/tidy_material_codes.py --backup-dir /tmp/x  # lokasi backup (bawaan: backups/)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

RENAMES = [("KN-CND-DST 2", "KN-CND-DST-2"), ("KN-RTW-HTM 3", "KN-RTW-HTM-3")]
MERGES = [("KN-RTW-", "KN-RTW-HTM-3")]
# Field identitas barang: beda isi (keduanya terisi) = data bertentangan → tidak digabung.
IDENTITY_FIELDS = ("name", "type", "unit", "base_uom", "category_id", "color", "color_code", "color_name",
                   "composition", "gsm", "width_cm", "supplier_id", "supplier_name", "unit_cost")
# Koleksi riwayat/log: rujukan DILAPORKAN, tidak diubah (riwayat menyimpan apa yang terjadi saat itu).
LOG_MARKERS = ("activity_log", "audit", "_logs", "log_", "notification", "backup", "history", "snapshot")
# Bukti material sudah bertransaksi (stok/mutasi) → penggabungan saldo tidak dilakukan otomatis.
STOCK_COLLECTIONS = ("rahaza_material_stock", "rahaza_stock_ledger", "rahaza_material_movements")


def norm(v) -> str:
    return str(v if v is not None else "").strip().upper()


def is_log_collection(name: str) -> bool:
    n = name.lower()
    return any(m in n for m in LOG_MARKERS)


def find_refs(doc, codes: dict, ids: dict, path: str = "") -> list:
    """Semua rujukan di satu dokumen (fungsi murni).

    `codes` = {KODE_NORMAL: label}, `ids` = {id: label}. Return [(path, nilai, 'kode'|'id', label)]."""
    out = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "_id" and not path:
                continue
            out += find_refs(v, codes, ids, f"{path}.{k}" if path else str(k))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            out += find_refs(v, codes, ids, f"{path}.{i}")
    elif isinstance(doc, str):
        if doc in ids:
            out.append((path, doc, "id", ids[doc]))
        elif norm(doc) in codes:
            out.append((path, doc, "kode", codes[norm(doc)]))
    return out


def merge_verdict(src: dict, dst: dict) -> tuple:
    """(boleh_digabung, [alasan]) — nama sama dan tidak ada field identitas yang bertentangan (murni)."""
    reasons = []
    if not src or not dst:
        return False, ["material sumber/target tidak ditemukan"]
    if norm(src.get("name")) != norm(dst.get("name")):
        reasons.append(f"nama beda: {src.get('name')!r} vs {dst.get('name')!r}")
    for f in IDENTITY_FIELDS[1:]:
        a, b = src.get(f), dst.get(f)
        if a in (None, "") or b in (None, ""):
            continue
        if (norm(a) if isinstance(a, str) else a) != (norm(b) if isinstance(b, str) else b):
            reasons.append(f"{f} bertentangan: {a!r} vs {b!r}")
    return (not reasons), reasons


async def _materials_by_code(db, code: str) -> list:
    import re
    return await db.rahaza_materials.find(
        {"code": {"$regex": f"^\\s*{re.escape(code.strip())}\\s*$", "$options": "i"}}, {"_id": 0}).to_list(10)


async def scan_refs(db, codes: dict, ids: dict, *, only: list | None = None) -> dict:
    """{koleksi: [(_id, path, nilai, jenis, label)]} untuk semua koleksi (kecuali system.*)."""
    found = defaultdict(list)
    names = only or sorted(n for n in await db.list_collection_names() if not n.startswith("system."))
    for coll in names:
        async for d in db[coll].find({}):
            for path, val, kind, label in find_refs(d, codes, ids):
                found[coll].append((d.get("_id"), path, val, kind, label))
    return dict(found)


def summarize(refs: dict) -> dict:
    """{label: {koleksi: {path_tanpa_indeks: n}}} — ringkasan laporan (murni)."""
    import re
    out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for coll, rows in refs.items():
        for _id, path, _val, kind, label in rows:
            generic = re.sub(r"\.\d+", "[]", path)
            out[label][coll][f"{generic} ({kind})"] += 1
    return {k: {c: dict(p) for c, p in v.items()} for k, v in out.items()}


async def plan(db) -> dict:
    """Rencana lengkap (tanpa menulis): rename, merge + verdict, rujukan."""
    res = {"renames": [], "merges": [], "errors": []}
    codes, ids = {}, {}
    for old, new in RENAMES:
        src = await _materials_by_code(db, old)
        exact = [m for m in src if m.get("code") == old] or src
        clash = [m for m in await _materials_by_code(db, new) if not exact or m.get("id") != exact[0].get("id")]
        row = {"old": old, "new": new, "material": exact[0] if exact else None, "clash": clash}
        if not exact:
            row["skip"] = "kode lama tidak ditemukan (sudah dirapikan?)"
        elif len(exact) > 1:
            row["skip"] = f"kode lama kembar ({len(exact)} material) — selesaikan manual"
        elif clash:
            row["skip"] = f"kode baru sudah dipakai material lain ({clash[0].get('id')})"
        else:
            codes[norm(old)] = f"rename:{old}"
            ids[exact[0]["id"]] = f"rename:{old}"
        res["renames"].append(row)
    for src_code, dst_code in MERGES:
        src = next(iter(await _materials_by_code(db, src_code)), None)
        dst = next(iter(await _materials_by_code(db, dst_code)), None)
        if not dst:   # target mungkin belum dirapikan (masih kode lama ber-spasi)
            old_dst = next((o for o, n in RENAMES if n == dst_code), None)
            dst = next(iter(await _materials_by_code(db, old_dst)), None) if old_dst else None
        ok, why = merge_verdict(src, dst)
        stock = {}
        if src:
            for c in STOCK_COLLECTIONS:
                n = await db[c].count_documents({"material_id": src["id"]})
                if n:
                    stock[c] = n
        if ok and stock:
            why.append(f"material sumber sudah bertransaksi {stock} — penggabungan saldo harus manual")
        row = {"src": src_code, "dst": dst_code, "src_material": src, "dst_material": dst,
               "terbukti_sama": ok, "alasan": why, "stok_sumber": stock, "akan_digabung": ok and not stock}
        if src:
            codes[norm(src_code)] = f"merge:{src_code}"
            ids[src["id"]] = f"merge:{src_code}"
        res["merges"].append(row)
    res["refs"] = await scan_refs(db, codes, ids) if codes or ids else {}
    res["ringkasan_rujukan"] = summarize(res["refs"])
    return res


def _jsonable(x):
    try:
        from bson import json_util
        return json.loads(json_util.dumps(x))
    except Exception:  # noqa: BLE001
        return json.loads(json.dumps(x, default=str))


async def apply(db, p: dict, backup_dir: Path) -> dict:
    """Terapkan rencana. Backup JSON ditulis SEBELUM perubahan pertama."""
    now = datetime.now(timezone.utc)
    targets = {}       # label → (kode_baru, id_baru | None)
    for r in p["renames"]:
        if not r.get("skip"):
            targets[f"rename:{r['old']}"] = (r["new"], None)
    for m in p["merges"]:
        if m["akan_digabung"]:
            targets[f"merge:{m['src']}"] = (m["dst"], m["dst_material"]["id"])
    changes = []       # (koleksi, _id, path, nilai_lama, nilai_baru)
    for coll, rows in p["refs"].items():
        if is_log_collection(coll):
            continue
        for _id, path, val, kind, label in rows:
            if label not in targets:
                continue
            new_code, new_id = targets[label]
            if coll == "rahaza_materials" and path in ("code",):
                continue                       # dokumen master ditangani terpisah (alias)
            if kind == "kode":
                changes.append((coll, _id, path, val, new_code))
            elif kind == "id" and new_id and not (coll == "rahaza_materials" and path == "id"):
                changes.append((coll, _id, path, val, new_id))
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = {"dibuat": now.isoformat(), "db": getattr(db, "name", ""), "materials": [], "documents": {}}
    for r in p["renames"]:
        if r.get("material"):
            backup["materials"].append(r["material"])
    for m in p["merges"]:
        backup["materials"] += [x for x in (m.get("src_material"), m.get("dst_material")) if x]
    by_doc = defaultdict(set)
    for coll, _id, *_ in changes:
        by_doc[coll].add(_id)
    for coll, id_set in by_doc.items():
        backup["documents"][coll] = await db[coll].find({"_id": {"$in": list(id_set)}}).to_list(None)
    bfile = backup_dir / f"tidy_material_codes_{now:%Y%m%d_%H%M%S}.json"
    bfile.write_text(json.dumps(_jsonable(backup), ensure_ascii=False, indent=1), encoding="utf-8")

    done = {"backup": str(bfile), "master": 0, "rujukan": 0, "digabung": 0}
    for r in p["renames"]:
        if r.get("skip"):
            continue
        res = await db.rahaza_materials.update_one(
            {"id": r["material"]["id"], "code": r["material"]["code"]},
            {"$set": {"code": r["new"], "updated_at": now, "code_tidied_at": now},
             "$addToSet": {"code_aliases": r["material"]["code"]}})
        done["master"] += res.modified_count
    for coll, _id, path, old, new in changes:
        res = await db[coll].update_one({"_id": _id, path: old}, {"$set": {path: new}})
        done["rujukan"] += res.modified_count
    for m in p["merges"]:
        if not m["akan_digabung"]:
            continue
        await db.rahaza_materials.update_one({"id": m["dst_material"]["id"]},
                                             {"$addToSet": {"code_aliases": m["src_material"]["code"]}})
        await db.rahaza_materials.update_one({"id": m["src_material"]["id"]}, {"$set": {
            "active": False, "merged_into": m["dst_material"]["id"], "updated_at": now}})
        done["digabung"] += 1
    return done


def _print(p: dict, apply_: bool, dbname: str, done: dict | None) -> None:
    print(f"[tidy_material_codes] DB {dbname} · {'TERAPKAN' if apply_ else 'DRY-RUN'}")
    for r in p["renames"]:
        m = r.get("material") or {}
        print(f"  RENAME {r['old']!r} → {r['new']!r}: " + (f"LEWATI — {r['skip']}" if r.get("skip")
                                                          else f"material {m.get('id')} ({m.get('name')})"))
    for m in p["merges"]:
        verdict = "DIGABUNG" if m["akan_digabung"] else "TIDAK digabung (dilaporkan saja)"
        print(f"  GABUNG {m['src']!r} → {m['dst']!r}: {verdict}")
        for a in m["alasan"]:
            print(f"     · {a}")
    print("  Rujukan ditemukan (koleksi → field (jenis): jumlah):")
    if not p["ringkasan_rujukan"]:
        print("     (tidak ada)")
    for label, colls in p["ringkasan_rujukan"].items():
        print(f"   {label}")
        for coll, paths in sorted(colls.items()):
            tag = " [log — tidak diubah]" if is_log_collection(coll) else ""
            for path, n in sorted(paths.items()):
                print(f"     {coll}.{path}: {n}{tag}")
    if done:
        print(f"  backup: {done['backup']}")
        print(f"  diubah: master {done['master']} · rujukan kode/id {done['rujukan']} · digabung {done['digabung']}")
    else:
        print("Jalankan ulang dengan --terapkan untuk menerapkan (backup JSON dibuat dulu).")


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--terapkan", action="store_true", help="ubah data (bawaan: dry-run)")
    ap.add_argument("--backup-dir", default=str(ROOT / "backups"), help="folder backup JSON")
    a = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "backend" / ".env")
    except Exception:  # noqa: BLE001
        pass
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        db = client[os.environ["DB_NAME"]]
        p = await plan(db)
        done = await apply(db, p, Path(a.backup_dir)) if a.terapkan else None
    finally:
        client.close()
    _print(p, a.terapkan, os.environ["DB_NAME"], done)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
