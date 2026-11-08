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


# ── CAKUPAN (2026-11-07, keputusan owner Tahap 9 lanjutan) ──────────────────────────────────────────────
#   semua        transaksi + log dihapus (perilaku T5 semula).
#   operasional  HANYA transaksi produksi, gudang/stok, pembelian, dan keuangan — bagian yang diisi ulang dari
#                Excel. Data Marketing (tugas, kalender, live, ulasan, sampel, komplain, pesanan), SDM (absensi,
#                cuti, gaji, kasbon), aset, RnD, dan SEMUA log tetap ada. Pencairan dana marketplace ikut dihapus
#                karena ia transaksi keuangan berjurnal (jurnalnya ikut dihapus).
#   Penentuan memakai DAFTAR EKSPLISIT (domain + nama), bukan tebakan pola: koleksi transaksi yang tidak ada di
#   daftar = DIPERTAHANKAN.
SCOPE_SEMUA = "semua"
SCOPE_OPERASIONAL = "operasional"
SCOPES = (SCOPE_SEMUA, SCOPE_OPERASIONAL)
SCOPE_LABEL = {SCOPE_SEMUA: "semua transaksi + log",
               SCOPE_OPERASIONAL: "produksi, gudang/stok, pembelian & keuangan saja"}
OPERASIONAL_DOMAINS = frozenset({"produksi", "maklon", "vendor", "pengadaan", "penjualan", "inventory",
                                 "gudang", "finance"})
OPERASIONAL_NAMES = frozenset({
    # produksi / CMT / cutting
    "cmt_receipts", "cmt_receipt_lines", "cmt_short_shipments", "cutting_orders", "cutting_progress",
    "dewi_cutting_batches", "dewi_cutting_requests", "rahaza_bundles", "rahaza_wip_events", "rahaza_qc_events",
    "rahaza_work_orders", "work_orders", "rahaza_orders", "rahaza_shipments", "dewi_delivery_orders",
    "dewi_hpp_snapshots_po", "dewi_hpp_snapshots_maklon", "rahaza_hpp_snapshots", "dewi_maklon_orders",
    # bahan, aksesoris, barang jadi, stok
    "accessory_shipments", "accessory_shipment_items", "dewi_accessory_requests", "dewi_material_issues",
    "material_requests", "material_request_items", "material_defect_reports", "rahaza_fg_inventory",
    "rahaza_fg_issues", "rahaza_fg_movements", "rahaza_fg_reservations", "warehouse_receiving",
    "rahaza_grn_inspections", "rahaza_goods_receipts", "acc_stock_movements", "acc_opname_sessions",
    "acc_opname_lines", "acc_loans", "warehouse_opname", "wh_opname_sessions", "wh_opname_lines",
    # pembelian
    "dewi_procurement_requests", "rahaza_purchase_orders",
    # keuangan
    "invoices", "invoice_adjustments", "invoice_change_history", "invoice_edit_requests", "payments",
    "rahaza_accruals", "rahaza_bank_transfers", "rahaza_bank_recon_adjustments", "bank_recon_sessions",
    "bank_recon_txns", "rahaza_cash_movements", "rahaza_petty_cash_txns", "rahaza_credit_notes",
    "rahaza_expenses", "fx_revaluation_runs",
    # pencairan dana marketplace (berjurnal)
    "marketing_settlements", "marketing_platform_withdrawals",
})
# field turunan milik bagian yang DIPERTAHANKAN pada cakupan operasional: kesehatan akun marketplace, cuti
# terpakai (pengajuan cuti tetap ada), statistik LMS/rekrutmen, dan aset tetap (penyusutan tidak ikut cutoff ini)
OPERASIONAL_KEEP_DERIVED = frozenset({"marketing_platform_accounts", "rahaza_leave_balances", "dewi_lms_courses",
                                      "rahaza_job_postings", "dewi_recruitment_jobs", "rahaza_fixed_assets"})


def deleted_in_scope(name: str, kind: str | None, scope: str = SCOPE_SEMUA) -> bool:
    """True bila koleksi `name` (berjenis `kind`) DIKOSONGKAN pada cakupan `scope` (fungsi murni)."""
    if kind not in cr.KINDS_DIHAPUS:
        return False
    if scope == SCOPE_SEMUA:
        return True
    if kind == cr.KIND_LOG:
        return False
    return name in OPERASIONAL_NAMES or cr.domain_of(name) in OPERASIONAL_DOMAINS


async def _count(db, name: str) -> int:
    return int(await db[name].count_documents({}))


async def build_plan(db, *, reset_nomor: bool = False, scope: str = SCOPE_SEMUA) -> dict:
    """Rencana cutoff (TANPA menulis apa pun): koleksi per jenis + jumlah dokumen, field turunan
    yang akan direset, dan penghitung nomor yang direset/dipertahankan.

    `scope=operasional`: koleksi transaksi/log di luar cakupan dipindah ke `classes["dipertahankan"]`
    (tetap dicetak, tidak dihapus) — `apply_plan` hanya menghapus `classes[transaksi|log]`."""
    if scope not in SCOPES:
        raise CutoffRefused(f"Cakupan tidak dikenal: {scope} (pilihan: {', '.join(SCOPES)})")
    names = sorted(n for n in await db.list_collection_names() if not n.startswith("system."))
    present = set(names)
    classes: dict[str, list] = {k: [] for k in cr.KINDS}
    classes["dipertahankan"] = []          # transaksi/log di luar cakupan (hanya scope operasional)
    unknown: list = []
    for n in names:
        row = {"name": n, "count": await _count(db, n)}
        kind = cr.kind_of(n)
        if kind is None:
            unknown.append(row)
        elif kind in cr.KINDS_DIHAPUS and not deleted_in_scope(n, kind, scope):
            classes["dipertahankan"].append({**row, "kind": kind})
        else:
            classes[kind].append(row)

    derived = []
    for rule in cr.DERIVED_FIELDS:
        coll = rule["collection"]
        if coll not in present:
            continue
        action = "reset" if (rule.get("reset") or rule.get("unset") or rule.get("special")) else "keep"
        if scope == SCOPE_OPERASIONAL and coll in OPERASIONAL_KEEP_DERIVED:
            action = "keep"
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
            elif kind in cr.KINDS_DIHAPUS and reset_nomor and scope == SCOPE_SEMUA:
                counters["reset"].append(row)
            else:
                counters["keep"].append(row)

    total_delete = sum(r["count"] for k in cr.KINDS_DIHAPUS for r in classes[k])
    total_keep = (sum(r["count"] for k in cr.KINDS if k not in cr.KINDS_DIHAPUS for r in classes[k])
                  + sum(r["count"] for r in classes["dipertahankan"]))
    return {"classes": classes, "unknown": unknown, "derived": derived, "counters": counters,
            "reset_nomor": bool(reset_nomor) and scope == SCOPE_SEMUA, "scope": scope,
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


async def apply_derived(db, present: set, skip: frozenset = frozenset()) -> list:
    out = []
    for rule in cr.DERIVED_FIELDS:
        coll = rule["collection"]
        if coll not in present or coll in skip:
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
    present |= {r["name"] for r in plan["classes"].get("dipertahankan", [])}
    skip = OPERASIONAL_KEEP_DERIVED if plan.get("scope") == SCOPE_OPERASIONAL else frozenset()
    derived = await apply_derived(db, present, skip)
    counters_reset = 0
    if plan["reset_nomor"] and plan["counters"]["reset"]:
        keys = [r["key"] for r in plan["counters"]["reset"]]
        counters_reset = int((await db.counters.delete_many({"_id": {"$in": keys}})).deleted_count)
    return {"deleted": deleted, "deleted_total": sum(deleted.values()), "derived": derived,
            "counters_reset": counters_reset}
