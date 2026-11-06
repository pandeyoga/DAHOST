"""core.store_cleanup — SATU aturan "toko ini sudah punya data atau belum" (2026-11-05).

Dipakai dua pintu supaya keputusannya tidak pernah berbeda:
  * migrasi `scripts/migrations/2026_11_05_toko_dobel.py` (menonaktifkan toko yang tercatat dua kali);
  * tombol **Hapus permanen** (super admin) di Kelola Akun — `routes.marketing_accounts`.

"Data toko" = dokumen mana pun yang menunjuk `account_id` toko itu (pesanan, item katalog, sales,
iklan, sesi live, target, kalender konten, …) + baris jurnal di akun COA MILIK toko itu (sub-ledger toko;
akun pendapatan bersama tidak dihitung — `own_coa_codes`, 7 Nov 2026). BUKAN data:
koleksi jejak/riwayat (log, history, audit, notifikasi) dan sesi impor yang belum pernah disimpan
(pratinjau/draf — tidak memasukkan satu baris pun). Katalog KOSONG juga bukan data.
"""
from __future__ import annotations

import re
from typing import Optional

ACCOUNTS = "marketing_platform_accounts"
LOG_LIKE = re.compile(r"(_log|_logs|history|audit|activity|notification|_syncs$)")
# Penyaring per koleksi: hanya yang sungguh data yang dihitung.
REAL_DATA_FILTER = {"marketing_data_import_sessions": {"committed_count": {"$gt": 0}}}
SKIP = {ACCOUNTS, "marketing_catalogs"}          # katalog dihitung lewat item-nya
LABELS = {
    "marketing_orders": "pesanan", "marketing_catalog_items": "item katalog",
    "marketing_sales_data": "data sales", "marketing_ads_data": "data iklan",
    "marketing_live_sessions": "sesi live", "marketing_content_calendar": "jadwal konten",
    "marketing_data_import_sessions": "impor data yang sudah disimpan", "marketing_returns": "retur",
    "marketing_reviews": "ulasan", "marketing_complaints": "komplain", "marketing_settlements": "pencairan",
    "marketing_account_targets": "target", "marketing_platform_kpi_daily": "KPI platform",
    "marketing_samples": "kiriman sample", "marketing_discounts": "kampanye diskon",
    "marketing_account_health": "catatan kesehatan toko", "marketing_live_session_products": "produk sesi live",
    "marketing_platform_withdrawals": "penarikan saldo", "marketing_product_launches": "peluncuran produk",
    "marketing_tasks": "tugas", "marketing_livehost_shifts": "jadwal host live",
}
OTHER = "data lain"   # koleksi tanpa nama tampilan — nama program tidak ditampilkan ke staf


def store_coa_codes(store: dict) -> list:
    return sorted({c for c in (store.get("coa_revenue_code"), store.get("coa_receivable_code"),
                               store.get("ar_account_code")) if c})


async def own_coa_codes(db, store: dict) -> list:
    """Kode akun COA MILIK toko ini sendiri (sub-ledger toko), dari yang tertaut di toko itu.

    2026-11-07 (Tahap 6, MK4 — keputusan owner): dulu SEMUA akun yang tertaut dihitung, termasuk akun
    pendapatan BERSAMA (mis. 4-1100 Penjualan Garment) yang dijurnal toko lain / penjualan langsung —
    toko baru tanpa transaksi pun ditolak dihapus ("62 jurnal di akun COA toko ini"). Milik toko =
    akun penjualan bertanda kode toko ini (`flags.store_account_code`) atau piutang sub-ledger toko ini
    (`flags.subledger_entity_id`), yaitu akun yang dibuat untuk toko itu saja.
    """
    codes = store_coa_codes(store)
    if not codes:
        return []
    rows = await db.rahaza_coa_accounts.find(
        {"code": {"$in": codes}}, {"_id": 0, "code": 1, "flags": 1}).to_list(len(codes) * 4)
    own = set()
    for a in rows:
        fl = a.get("flags") or {}
        if ((store.get("account_code") and fl.get("store_account_code") == store.get("account_code"))
                or (store.get("id") and fl.get("subledger_entity_id") == store.get("id"))):
            own.add(a["code"])
    return sorted(own)


async def store_data_refs(db, store: dict, collections: Optional[list] = None) -> dict:
    """{nama tampilan: jumlah} data yang menunjuk toko ini. Kosong = toko belum punya data."""
    if collections is None:
        collections = sorted(await db.list_collection_names())
    refs: dict = {}
    for c in collections:
        if c in SKIP or LOG_LIKE.search(c):
            continue
        n = await db[c].count_documents({"account_id": store["id"], **REAL_DATA_FILTER.get(c, {})})
        if n:
            label = LABELS.get(c, OTHER)
            refs[label] = refs.get(label, 0) + n
    codes = await own_coa_codes(db, store)   # MK4: hanya sub-ledger milik toko ini, bukan akun bersama
    if codes:
        n = (await db.rahaza_journal_lines.count_documents({"account_code": {"$in": codes}})
             + await db.rahaza_journal_entries.count_documents({"lines.account_code": {"$in": codes}}))
        if n:
            refs["jurnal di akun COA toko ini"] = n
    return refs


def describe_refs(refs: dict) -> str:
    return ", ".join(f"{n} {label}" for label, n in refs.items())


async def owned_coa(db, store: dict) -> list:
    """Akun COA yang DIBUAT SISTEM khusus untuk toko ini (Penjualan otomatis + Piutang subledger)."""
    from core.finance_sync import _system_created
    out = []
    rc = store.get("coa_revenue_code")
    if rc:
        a = await db.rahaza_coa_accounts.find_one(
            {"code": rc, "flags.store_account_code": store.get("account_code")}, {"_id": 0})
        if a and _system_created(a):
            out.append(a)
    for ar in {store.get("coa_receivable_code"), store.get("ar_account_code")} - {None, ""}:
        a = await db.rahaza_coa_accounts.find_one(
            {"code": ar, "flags.subledger_entity_id": store["id"]}, {"_id": 0})
        if a:
            out.append(a)
    return out


async def coa_unused_elsewhere(db, store: dict, code: str) -> bool:
    """Tidak dipakai toko lain dan belum pernah dijurnal."""
    other = await db[ACCOUNTS].count_documents({"id": {"$ne": store["id"]}, "$or": [
        {"coa_revenue_code": code}, {"coa_receivable_code": code}, {"ar_account_code": code}]})
    jl = (await db.rahaza_journal_lines.count_documents({"account_code": code})
          + await db.rahaza_journal_entries.count_documents({"lines.account_code": code}))
    return not other and not jl


async def delete_store_permanently(db, store: dict, user: dict) -> dict:
    """Hapus permanen toko yang BELUM punya data. ValueError (berisi alasan) bila sudah punya data.

    Ikut dibereskan: draf impor & katalog kosong milik toko itu, lalu akun COA yang dibuat sistem
    untuknya — DIHAPUS bila bebas (aturan Bagan Akun `coa_bindings.check_action`), dinonaktifkan bila
    hanya itu yang boleh, dibiarkan bila masih terikat. Akun pendapatan toko & piutang sub-ledger buatan
    sistem menurut aturan Bagan Akun hanya boleh DINONAKTIFKAN (dicek 5 Nov 2026) — aturan itu tidak
    dilangkahi di sini. Jejaknya ditulis di `marketing_change_log`.
    """
    refs = await store_data_refs(db, store)
    if refs:
        raise ValueError(
            f"Toko {store.get('account_code')} · {store.get('account_name')} tidak bisa dihapus permanen "
            f"karena sudah punya data: {describe_refs(refs)}. Arsipkan saja, atau hapus/pindahkan datanya dulu.")
    coa = await owned_coa(db, store)
    drafts = await db.marketing_data_import_sessions.delete_many(
        {"account_id": store["id"], "committed_count": {"$in": [0, None]}})
    cats = await db.marketing_catalogs.delete_many({"account_id": store["id"]})
    await db[ACCOUNTS].delete_one({"id": store["id"]})

    from core import coa_bindings as cb
    deleted, deactivated, kept = [], [], []
    for a in coa:
        if not await coa_unused_elsewhere(db, store, a["code"]):
            kept.append(a["code"])
            continue
        bindings = (await cb.collect_bindings(db, [a["code"]])).get(a["code"], [])
        if not cb.check_action(a, "delete", bindings):
            await db.rahaza_coa_accounts.delete_one({"code": a["code"]})
            deleted.append(a["code"])
        elif a.get("active", True) is not False and not cb.check_action(a, "deactivate", bindings):
            await db.rahaza_coa_accounts.update_one({"code": a["code"]}, {"$set": {"active": False}})
            deactivated.append(a["code"])
        else:
            kept.append(a["code"])

    from core import marketing_cycle as cycle
    snapshot = {k: store.get(k) for k in ("account_code", "account_name", "platform", "username", "status",
                                          "pic_user_name", "coa_revenue_code", "coa_receivable_code",
                                          "created_by", "created_at")}
    await cycle.log_change(
        db, account_id=store["id"], entity=ACCOUNTS, entity_id=store["id"], action="store_deleted",
        before=snapshot, after={"coa_deleted": deleted, "coa_deactivated": deactivated, "coa_kept": kept,
                                "catalogs_deleted": cats.deleted_count, "drafts_deleted": drafts.deleted_count},
        reason="hapus permanen oleh super admin", user=user)
    return {"coa_deleted": deleted, "coa_deactivated": deactivated, "coa_kept": kept,
            "catalogs_deleted": cats.deleted_count, "drafts_deleted": drafts.deleted_count}
