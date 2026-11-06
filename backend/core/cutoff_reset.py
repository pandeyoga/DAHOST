"""core.cutoff_reset — mode cutoff "HAPUS TRANSAKSI SAJA" (T5, keputusan owner 2026-11-06).

Dipakai `scripts/reset_for_golive.py --transaksi-saja`. Berbeda dengan reset go-live bawaan
(yang mengosongkan SEMUA kecuali konfigurasi), mode ini:

  * MENGHAPUS isi koleksi berjenis `transaksi` dan `log`;
  * MEMPERTAHANKAN koleksi `konfigurasi` dan `master` (barang, BOM, mitra, karyawan, akun, ...);
  * mengembalikan field TURUNAN di master ke keadaan pembukaan yang bersih
    (`collection_registry.DERIVED_FIELDS` — keputusan per field tercatat di sana);
  * nomor dokumen dilanjutkan, kecuali `reset_nomor=True` (penghitung milik koleksi transaksi/log
    dihapus sehingga nomor mulai dari 1 lagi; kode master TIDAK pernah direset).

Jenis setiap koleksi dibaca dari `core.collection_registry.KIND`. Koleksi yang ada di basis data
tetapi belum diklasifikasi membuat rencana DITOLAK (`unknown`) — tidak ada tebakan pola nama.
"""
from __future__ import annotations

from core import collection_registry as cr


class CutoffRefused(ValueError):
    """Rencana tidak boleh dijalankan (koleksi/penghitung belum diklasifikasi)."""


async def _count(db, name: str) -> int:
    return int(await db[name].count_documents({}))


async def build_plan(db, *, reset_nomor: bool = False) -> dict:
    """Rencana cutoff (TANPA menulis apa pun): koleksi per jenis + jumlah dokumen, field turunan
    yang akan direset, dan penghitung nomor yang direset/dipertahankan."""
    names = sorted(n for n in await db.list_collection_names() if not n.startswith("system."))
    present = set(names)
    classes: dict[str, list] = {k: [] for k in cr.KINDS}
    unknown: list = []
    for n in names:
        row = {"name": n, "count": await _count(db, n)}
        kind = cr.kind_of(n)
        if kind is None:
            unknown.append(row)
        else:
            classes[kind].append(row)

    derived = []
    for rule in cr.DERIVED_FIELDS:
        coll = rule["collection"]
        if coll not in present:
            continue
        action = "reset" if (rule.get("reset") or rule.get("unset") or rule.get("special")) else "keep"
        derived.append({"collection": coll, "action": action,
                        "fields": sorted(list((rule.get("reset") or {}).keys()) + list(rule.get("unset") or [])),
                        "special": rule.get("special"), "keep": list(rule.get("keep") or []),
                        "docs": await _count(db, coll), "alasan": rule.get("alasan", "")})

    counters = {"reset": [], "keep": [], "unknown": []}
    if "counters" in present:
        async for c in db.counters.find({}, {"_id": 1, "seq": 1}):
            key = str(c.get("_id"))
            kind = cr.counter_kind(key)
            row = {"key": key, "seq": c.get("seq"), "kind": kind}
            if kind is None:
                counters["unknown"].append(row)
            elif kind in cr.KINDS_DIHAPUS and reset_nomor:
                counters["reset"].append(row)
            else:
                counters["keep"].append(row)

    total_delete = sum(r["count"] for k in cr.KINDS_DIHAPUS for r in classes[k])
    total_keep = sum(r["count"] for k in cr.KINDS if k not in cr.KINDS_DIHAPUS for r in classes[k])
    return {"classes": classes, "unknown": unknown, "derived": derived, "counters": counters,
            "reset_nomor": bool(reset_nomor),
            "totals": {"hapus": total_delete, "pertahankan": total_keep,
                       "koleksi": len(names)}}


def refusal_reasons(plan: dict) -> list[str]:
    out = []
    if plan["unknown"]:
        out.append("Koleksi belum diklasifikasi di core/collection_registry.py (KIND): "
                   + ", ".join(r["name"] for r in plan["unknown"]))
    if plan["reset_nomor"] and plan["counters"]["unknown"]:
        out.append("Penghitung nomor tidak dikenal (tambahkan di COUNTER_KEY_*): "
                   + ", ".join(r["key"] for r in plan["counters"]["unknown"][:20]))
    return out


async def _reset_catalog_stats(db) -> int:
    """Rekap katalog sesudah stok item nol: rumus sama dengan `_refresh_catalog_stats` (item aktif;
    stok total = Σ stok item = 0; semua item aktif berstatus habis)."""
    n = 0
    async for cat in db.marketing_catalogs.find({}, {"_id": 0, "id": 1}):
        active = await db.marketing_catalog_items.count_documents(
            {"catalog_id": cat.get("id"), "is_active": True})
        await db.marketing_catalogs.update_one({"id": cat.get("id")}, {"$set": {
            "item_count": active, "total_stock": 0.0, "low_stock_count": 0,
            "out_of_stock_count": active}})
        n += 1
    return n


async def apply_derived(db, present: set) -> list:
    out = []
    for rule in cr.DERIVED_FIELDS:
        coll = rule["collection"]
        if coll not in present:
            continue
        if rule.get("special") == "catalog_stats":
            out.append({"collection": coll, "updated": await _reset_catalog_stats(db)})
            continue
        upd: dict = {}
        if rule.get("reset"):
            upd["$set"] = dict(rule["reset"])
        if rule.get("unset"):
            upd["$unset"] = {f: "" for f in rule["unset"]}
        if not upd:
            continue
        flt = {} if rule.get("reset") else {"$or": [{f: {"$exists": True}} for f in rule["unset"]]}
        res = await db[coll].update_many(flt, upd)
        out.append({"collection": coll, "updated": int(getattr(res, "modified_count", 0) or 0)})
    return out


async def apply_plan(db, plan: dict) -> dict:
    """Jalankan rencana `build_plan`. Pemanggil WAJIB sudah membuat cadangan (mongodump)."""
    reasons = refusal_reasons(plan)
    if reasons:
        raise CutoffRefused(" · ".join(reasons))
    deleted: dict = {}
    for kind in cr.KINDS_DIHAPUS:
        for row in plan["classes"][kind]:
            # tanpa melihat jumlah saat rencana: dokumen yang lahir sesudahnya ikut terhapus
            res = await db[row["name"]].delete_many({})
            if res.deleted_count:
                deleted[row["name"]] = int(res.deleted_count)
    present = {r["name"] for k in cr.KINDS for r in plan["classes"][k]}
    derived = await apply_derived(db, present)
    counters_reset = 0
    if plan["reset_nomor"] and plan["counters"]["reset"]:
        keys = [r["key"] for r in plan["counters"]["reset"]]
        counters_reset = int((await db.counters.delete_many({"_id": {"$in": keys}})).deleted_count)
    return {"deleted": deleted, "deleted_total": sum(deleted.values()), "derived": derived,
            "counters_reset": counters_reset}
