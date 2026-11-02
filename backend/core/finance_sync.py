"""core.finance_sync — SATU mesin sinkron master keuangan ↔ bagan akun (idempoten, aman diulang).

Dijalankan saat start server dan lewat POST /api/rahaza/finance/sync-masters. Menjaga:
1. Tiap akun kas/bank/dompet di CoA punya SATU rekening di Kas & Bank (kode rekening = kode akun) → tidak ada duplikat GL.
2. Auto Akun: vendor CMT menunjuk SSOT `vendor_partners` dgn induk 2-1110 (Hutang Vendor CMT); klien maklon → 1-1305.
3. Profil posting `cmt_ap_invoice.credit_ap` = 2-1110 — hanya bila kosong/bawaan lama (2026-11-02:
   pilihan pengguna di layar Profil Posting tidak lagi ditimpa).
4. Backfill sub-ledger untuk semua entitas yang belum punya (vendor CMT, supplier, pelanggan, toko, klien maklon, rekening).
5. Toko online: akun pendapatan per toko (4-11xx) + sub-ledger piutang 1-1303-<toko>;
   akun pendapatan toko lama tanpa toko & tanpa jurnal dinonaktifkan.
   2026-11-02 (D3) — TIDAK LAGI membuat/menghidupkan baris Peta Akun Channel untuk toko:
   COA per toko sudah ada di master toko (`coa_revenue_code`, `ar_account_code`) dan
   owner memutuskan "Peta Akun Channel seharusnya tidak ada" (peta COA kedua).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

CMT_AP_PARENT = "2-1110"
MAKLON_AR_PARENT = "1-1305"
CHANNEL_AR_PARENT = "1-1303"
REVENUE_GROUP = {"shopee": "4-1110", "tiktok": "4-1120", "tokopedia": "4-1130"}
# 2026-11-02 (No.10) — kosakata platform terbelah: layar Kelola Akun menyimpan
# `tiktokshop`, 3 toko seed memakai `tiktok`. Dulu toko `tiktokshop` DILEWATI
# seluruhnya oleh sinkron ini (tanpa akun pendapatan sendiri & piutang tetap
# 1-1303). Satu peta alias di sini; nilai yang tersimpan di master tidak diubah.
PLATFORM_ALIASES = {"tiktokshop": "tiktok", "tiktok_shop": "tiktok", "tiktok shop": "tiktok"}
NAME_ALIASES = {"ghs": "grosirhijabsragen"}


def canonical_platform(platform: str) -> str:
    p = (platform or "").strip().lower()
    return PLATFORM_ALIASES.get(p, p)


def revenue_group_for(platform: str) -> str | None:
    """Kode kelompok akun pendapatan platform (4-1110/4-1120/4-1130) atau None."""
    return REVENUE_GROUP.get(canonical_platform(platform))


def _now():
    return datetime.now(timezone.utc)


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\b(shopee|tiktok|tokopedia|penjualan|toko)\b", " ", s)
    s = " ".join(s.split())
    return NAME_ALIASES.get(s, s)


async def _sync_cash_accounts(db, report: dict):
    from core.fin_statements import cash_account_codes
    codes = await cash_account_codes(db)
    linked = {r["gl_account_code"] async for r in db.rahaza_cash_accounts.find({"gl_account_code": {"$ne": None}}, {"gl_account_code": 1})}
    created = []
    async for acc in db.rahaza_coa_accounts.find({"code": {"$in": sorted(codes)}, "active": True, "is_group": False}, {"_id": 0}):
        if acc["code"] in linked:
            continue
        is_cash = acc["code"].startswith("1-11")
        name = acc["name"]
        bank_name = "" if is_cash else (name.split("–")[0].split("-")[0].strip() if name.lower().startswith("bank") else name.split("–")[0].strip())
        if await db.rahaza_cash_accounts.find_one({"code": acc["code"]}):
            await db.rahaza_cash_accounts.update_one({"code": acc["code"]}, {"$set": {"gl_account_code": acc["code"], "updated_at": _now()}})
        else:
            await db.rahaza_cash_accounts.insert_one({
                "id": str(uuid.uuid4()), "code": acc["code"], "name": name, "type": "cash" if is_cash else "bank",
                "bank_name": bank_name, "account_number": "", "opening_balance": 0.0, "notes": "dibuat otomatis dari Bagan Akun",
                "gl_account_code": acc["code"], "active": True, "created_at": _now(), "updated_at": _now(), "created_from": "coa_sync"})
        created.append(acc["code"])
    report["cash_accounts_created"] = created


async def _sync_auto_settings(db, report: dict):
    from routes.coa_auto import DEFAULT_ENTITY_TYPES, get_auto_settings
    settings = await get_auto_settings(db)
    et = settings.get("entity_types") or {}
    changed = {}
    cv = et.get("cmt_vendor") or {}
    if cv.get("collection") != "vendor_partners" or cv.get("parent_code") == "2-1100":
        et["cmt_vendor"] = {**DEFAULT_ENTITY_TYPES["cmt_vendor"], "enabled": cv.get("enabled", True)}
        changed["cmt_vendor"] = et["cmt_vendor"]["parent_code"]
    if "maklon_client" not in et:
        et["maklon_client"] = dict(DEFAULT_ENTITY_TYPES["maklon_client"])
        changed["maklon_client"] = MAKLON_AR_PARENT
    if changed:
        await db.rahaza_coa_auto_settings.update_one({"id": "default"}, {"$set": {"entity_types": et, "updated_at": _now()}})
    report["auto_settings_changed"] = changed
    prof = await db.rahaza_posting_profiles.find_one(
        {"event_type": "cmt_ap_invoice"},
        {"_id": 0, "mapping": 1, "user_roles": 1, "user_removed_roles": 1, "updated_by": 1})
    if prof and cmt_ap_credit_needs_fix(prof):
        await db.rahaza_posting_profiles.update_one({"event_type": "cmt_ap_invoice"}, {"$set": {"mapping.credit_ap": CMT_AP_PARENT, "updated_at": _now()}})
        report["posting_profile_fixed"] = {"cmt_ap_invoice.credit_ap": CMT_AP_PARENT}


# 2026-11-02 (audit No.47 lanjutan): dulu `cmt_ap_invoice.credit_ap` DITIMPA 2-1110 setiap kali
# backend menyala, jadi akun hutang yang dipilih Finance di layar Profil Posting hilang tiap
# restart. Kini hanya diisi bila kosong, masih bawaan LAMA (2-1100 Hutang Usaha), atau profilnya
# belum pernah disentuh pengguna — pola penanda `user_roles` yang sama dengan
# `routes.rahaza_posting_profiles.upgrade_profile_mapping`.
CMT_AP_OLD_DEFAULTS = {"2-1100"}


def cmt_ap_credit_needs_fix(prof: dict) -> bool:
    """Murni (tanpa DB): perlukah `credit_ap` profil cmt_ap_invoice diisi CMT_AP_PARENT?"""
    from routes.rahaza_posting_profiles import profile_untouched
    cur = (prof.get("mapping") or {}).get("credit_ap")
    if cur == CMT_AP_PARENT:
        return False
    if "credit_ap" in (prof.get("user_roles") or []) or "credit_ap" in (prof.get("user_removed_roles") or []):
        return False  # dipilih/dihapus pengguna lewat layar Profil Posting → jangan disentuh
    return not cur or cur in CMT_AP_OLD_DEFAULTS or profile_untouched(prof)


async def _backfill_subledgers(db, report: dict, user):
    from routes.coa_auto import ensure_subledger_for_entity, get_auto_settings
    settings = await get_auto_settings(db)
    done = {}
    for etype, cfg in (settings.get("entity_types") or {}).items():
        if not cfg.get("enabled") or not cfg.get("collection"):
            continue
        tf = cfg.get("target_field") or "gl_account_code"
        n = 0
        async for ent in db[cfg["collection"]].find({"$or": [{tf: None}, {tf: {"$exists": False}}, {tf: ""}], "active": {"$ne": False}}, {"_id": 0}):
            if cfg["collection"] == "marketing_platform_accounts":
                ent = {**ent, "code": ent.get("account_code") or ent.get("code"), "name": ent.get("account_name") or ent.get("name")}
            res = await ensure_subledger_for_entity(db, etype, ent, user)
            if res.get("ok"):
                n += 1
        done[etype] = n
    report["subledgers_created"] = done


async def _next_code(db, group: str) -> str:
    codes = [a["code"] async for a in db.rahaza_coa_accounts.find({"code": {"$regex": f"^{group[:5]}\\d$"}}, {"code": 1})]
    nums = [int(c[-1]) for c in codes if c[-1].isdigit()]
    nxt = max(nums + [0]) + 1
    if nxt > 9:
        raise ValueError(f"kelompok {group} penuh")
    return f"{group[:5]}{nxt}"


async def _store_revenue_accounts(db) -> dict:
    return {a["code"]: a async for a in db.rahaza_coa_accounts.find(
        {"code": {"$regex": "^4-11[123]\\d$"}, "is_group": False}, {"_id": 0})}


async def ensure_store_revenue_account(db, store: dict, *, rev_accounts: dict | None = None,
                                       used: set | None = None) -> dict:
    """Akun pendapatan SENDIRI untuk satu toko, di bawah kelompok platformnya.

    2026-11-02 (No.10b) — keputusan owner: toko baru OTOMATIS dibuatkan akun
    pendapatan sendiri (seperti piutang 1-1303-<kode toko> yang sudah otomatis),
    BUKAN akun penampung "Lain-lain". Dipakai saat toko dibuat
    (`routes.marketing_accounts`) dan oleh sinkron ini — satu aturan, satu tempat:
      * akun lama bernama sama (mis. dinonaktifkan karena tokonya pernah dihapus)
        & belum dipakai toko lain ⇒ dipakai lagi dan dihidupkan;
      * selain itu ⇒ akun baru ``Penjualan – <nama toko>`` dengan nomor berikutnya
        di kelompok (4-111x Shopee · 4-112x TikTok · 4-113x Tokopedia);
      * akun penampung ("Lain-lain") TIDAK PERNAH dipakai sebagai akun toko.

    → ``{"code", "created": bool}``. ``ValueError`` bila platform tak dikenal atau
    kelompoknya penuh (maks. 9 akun per kelompok).
    """
    group = revenue_group_for(store.get("platform"))
    if not group:
        raise ValueError(f"platform '{store.get('platform')}' tidak punya kelompok akun pendapatan")
    if rev_accounts is None:
        rev_accounts = await _store_revenue_accounts(db)
    if used is None:
        used = {c for c in await db.marketing_platform_accounts.distinct("coa_revenue_code") if c}
    key = _norm(store.get("account_name"))
    match = next((c for c, a in rev_accounts.items()
                  if c.startswith(group[:5]) and c[-1] != "0" and key and _norm(a["name"]) == key
                  and "lain" not in (a.get("name") or "").lower() and c not in used), None)
    flags = {"flags.store_account_code": store.get("account_code"), "flags.is_sales": True,
             "flags.channel": canonical_platform(store.get("platform"))}
    if match:
        await db.rahaza_coa_accounts.update_one({"code": match}, {"$set": {"active": True, **flags, "updated_at": _now()}})
        return {"code": match, "created": False}
    code = await _next_code(db, group)
    doc = {"id": str(uuid.uuid4()), "code": code, "name": f"Penjualan – {store.get('account_name')}", "type": "REVENUE",
           "parent_code": group, "is_group": False, "normal_balance": "CREDIT",
           "flags": {"store_account_code": store.get("account_code"), "is_sales": True,
                     "channel": canonical_platform(store.get("platform"))},
           "cash_flow_group": "OPR", "active": True, "created_at": _now(), "updated_at": _now(),
           "created_by": "system", "created_by_name": "finance_sync"}
    await db.rahaza_coa_accounts.insert_one(doc)
    doc.pop("_id", None)
    rev_accounts[code] = doc
    return {"code": code, "created": True}


async def _sync_stores(db, report: dict):
    stores = await db.marketing_platform_accounts.find({"active": {"$ne": False}}, {"_id": 0}).to_list(500)
    rev_accounts = await _store_revenue_accounts(db)
    used, created, mapped = set(), [], []
    for s in stores:
        group = revenue_group_for(s.get("platform"))   # 2026-11-02: `tiktokshop` dikenali
        if not group:
            continue
        code = s.get("coa_revenue_code")
        if not code or code not in rev_accounts:
            res = await ensure_store_revenue_account(db, s, rev_accounts=rev_accounts, used=used)
            code = res["code"]
            if res["created"]:
                created.append(code)
            await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_revenue_code": code, "updated_at": _now()}})
        used.add(code)
        ar = (await db.marketing_platform_accounts.find_one({"id": s["id"]}, {"_id": 0, "ar_account_code": 1}) or {}).get("ar_account_code") or CHANNEL_AR_PARENT
        await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_receivable_code": ar}})
        # Rekening pencairan default (1-1201) supaya penarikan saldo bisa dijurnal; owner boleh mengganti di Kelola Akun.
        if not (s.get("coa_cash_code") or "").strip() and await db.rahaza_coa_accounts.find_one({"code": "1-1201", "active": True}, {"_id": 0}):
            await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_cash_code": "1-1201", "coa_cash_source": "default"}})
        # 2026-11-02 (D3) — baris Peta Akun Channel untuk toko TIDAK lagi dibuat/
        # dihidupkan/ditimpa di sini. `mapped` tetap dilaporkan (toko → akun) untuk
        # jejak sinkron; sumber COA toko adalah master toko itu sendiri.
        mapped.append((s.get("account_code"), code, ar))
    deactivated = []
    for c, a in rev_accounts.items():
        if c in used or not a.get("active", True) or c[-1] == "0" or "lain" in a["name"].lower():
            continue  # sub-total/header, "Lain-lain" (penampung) tetap hidup
        if await db.rahaza_journal_lines.count_documents({"account_code": c}) or await db.marketing_platform_accounts.count_documents({"coa_revenue_code": c}):
            continue
        await db.rahaza_coa_accounts.update_one({"code": c}, {"$set": {"active": False, "updated_at": _now(), "deactivated_reason": "toko tidak ada di master (finance_sync)"}})
        deactivated.append(c)
    stale = await db.rahaza_channel_gl_mapping.update_many({"channel_key": {"$nin": [s.get("account_code") for s in stores]}, "active": True},
                                                            {"$set": {"active": False, "updated_at": _now()}})
    report["stores"] = {"mapped": mapped, "revenue_created": created, "revenue_deactivated": deactivated, "channel_map_deactivated": stale.modified_count}


async def _sync_revenue_flags(db, report: dict) -> None:
    """Akun penjualan per toko 4-11xx: flags is_sales/channel hilang saat migrasi 4-digit
    → validator Kelola Akun menolak akun pendapatan toko. Pulihkan dari namanya (idempoten)."""
    n = 0
    async for a in db.rahaza_coa_accounts.find(
            {"type": "REVENUE", "code": {"$regex": r"^4-11\d\d$"}, "is_group": {"$ne": True}},
            {"_id": 0, "code": 1, "name": 1, "flags": 1}):
        flags = a.get("flags") or {}
        nm = (a.get("name") or "").lower()
        ch = next((c for c in ("shopee", "tiktok", "tokopedia", "lazada") if c in nm), None)
        upd = {}
        if not flags.get("is_sales"):
            upd["flags.is_sales"] = True
        if ch and flags.get("channel") != ch:
            upd["flags.channel"] = ch
        if upd:
            await db.rahaza_coa_accounts.update_one({"code": a["code"]}, {"$set": upd})
            n += 1
    report["revenue_flags_fixed"] = n


async def sync_finance_masters(db, user: dict | None = None) -> dict:
    report: dict = {}
    await _sync_auto_settings(db, report)
    await _sync_revenue_flags(db, report)
    await _sync_cash_accounts(db, report)
    await _backfill_subledgers(db, report, user)
    await _sync_stores(db, report)
    return report
