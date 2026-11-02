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

import logging
import re
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

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
    done, restored = {}, []
    codes = {a["code"] async for a in db.rahaza_coa_accounts.find({}, {"_id": 0, "code": 1}) if a.get("code")}
    for etype, cfg in (settings.get("entity_types") or {}).items():
        if not cfg.get("enabled") or not cfg.get("collection"):
            continue
        tf = cfg.get("target_field") or "gl_account_code"
        n = 0
        async for ent in db[cfg["collection"]].find({"active": {"$ne": False}}, {"_id": 0}):
            cur = (ent.get(tf) or "").strip() if isinstance(ent.get(tf), str) else ent.get(tf)
            # 2026-11-02 (S2-H): selain field KOSONG, pulihkan juga rujukan ke akun yang HILANG (dulu toko
            # tetap menunjuk sub-ledger yang terhapus → pencairan ditolak, T12/STARTUP). Dilaporkan, tidak diam.
            missing = bool(cur) and cur not in codes
            if cur and not missing:
                continue
            if missing and not str(cur).startswith(f"{cfg.get('parent_code')}-"):
                # bukan sub-ledger bentukan Auto Akun (mis. rekening → akun bank biasa): jangan diganti
                # diam-diam, cukup dilaporkan (juga tampil di INV-COA-REF Setup Akuntansi).
                restored.append({"entity_type": etype, "entity": ent.get("code") or ent.get("id"),
                                 "was": cur, "now": None, "note": "akun tidak ada — tidak diubah otomatis"})
                continue
            if cfg["collection"] == "marketing_platform_accounts":
                ent = {**ent, "code": ent.get("account_code") or ent.get("code"), "name": ent.get("account_name") or ent.get("name")}
            res = await ensure_subledger_for_entity(db, etype, ent, user)
            if res.get("ok"):
                n += 1
                codes.add(res.get("code"))
                if missing:
                    restored.append({"entity_type": etype, "entity": ent.get("code") or ent.get("id"),
                                     "was": cur, "now": res.get("code")})
        done[etype] = n
    report["subledgers_created"] = done
    report["subledgers_restored"] = restored
    if restored:
        log.warning("[finance_sync] rujukan sub-ledger ke akun yang hilang dipulihkan: %s", restored)


# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-02 (K35) — PENOMORAN AKUN PENDAPATAN PER TOKO = KONFIGURASI
# ══════════════════════════════════════════════════════════════════════════════
# Dulu penomoran DI-HARD-CODE: satu digit terakhir kelompok (4-111x) ⇒ maks. 9 akun
# per platform (Shopee & TikTok tinggal 2 slot) lalu `ValueError`. Owner (K35):
# penomoran bisa dikonfigurasi di pengaturan Auto Akun yang SUDAH ada
# (`rahaza_coa_auto_settings.entity_types.store_revenue`, tab Auto Akun) — tanpa
# layar/koleksi baru. Token format:
#   {prefix}  = 5 karakter pertama kode kelompok (4-111)   — pola lama
#   {parent}  = kode kelompok utuh (4-1110)
#   {seq}     = nomor urut ({seq:02d}/{seq:03d} untuk lebar tetap)
#   {store_code} = kode toko (mis. SHP-09) — pola sub-akun seperti 1-1303-<kode toko>
# Bawaan = pola lama "{prefix}{seq}" (tidak ada nomor yang bergeser). Toko LAMA tidak
# diubah: format hanya dipakai saat akun pendapatan toko BARU dibuat.
STORE_REVENUE_KEY = "store_revenue"
STORE_REVENUE_DEFAULT_FORMAT = "{prefix}{seq}"
STORE_REVENUE_FORMATS = ("{prefix}{seq}", "{parent}-{seq:02d}", "{parent}-{seq:03d}",
                         "{parent}-{store_code}")
_FMT_TOKEN = re.compile(r"\{(prefix|parent|store_code|seq(?::0[1-4]d)?)\}")


def validate_code_format(fmt: str) -> str:
    """Format penomoran sah? → format yang dirapikan, atau ``ValueError``."""
    f = (fmt or "").strip()
    if not f:
        raise ValueError("Format kode akun tidak boleh kosong.")
    leftovers = _FMT_TOKEN.sub("", f)
    if "{" in leftovers or "}" in leftovers:
        raise ValueError("Format hanya boleh memakai token {prefix}, {parent}, {seq}, "
                         "{seq:02d}, {seq:03d}, {store_code}.")
    if not re.fullmatch(r"[0-9A-Za-z\-]*", leftovers):
        raise ValueError("Di luar token, format hanya boleh berisi huruf, angka, dan tanda '-'.")
    if ("{seq" in f) == ("{store_code}" in f):
        raise ValueError("Format wajib memuat SALAH SATU dari {seq} atau {store_code} supaya "
                         "tiap toko bernomor unik.")
    if len(_FMT_TOKEN.findall(f)) != len(set(_FMT_TOKEN.findall(f))):
        raise ValueError("Setiap token hanya boleh dipakai sekali.")
    if not (f.startswith("{prefix}") or f.startswith("{parent}")):
        raise ValueError("Format wajib diawali {prefix} atau {parent} supaya akun tetap di "
                         "bawah kelompok pendapatan platformnya.")
    return f


def _seq_width(fmt: str) -> int | None:
    m = re.search(r"\{seq(?::0([1-4])d)?\}", fmt)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 0          # 0 = tanpa lebar tetap


def render_store_revenue_code(fmt: str, group: str, seq: int | None = None,
                              store_code: str = "") -> str:
    """Kode akun dari format (murni, tanpa DB)."""
    sc = re.sub(r"[^A-Za-z0-9\-]", "", (store_code or "").strip().upper())
    out = fmt.replace("{prefix}", group[:5]).replace("{parent}", group).replace("{store_code}", sc)
    w = _seq_width(fmt)
    if w is not None:
        s = str(int(seq or 0)).zfill(w) if w else str(int(seq or 0))
        out = re.sub(r"\{seq(?::0[1-4]d)?\}", s, out)
    return out


def seq_capacity(fmt: str) -> int | None:
    """Kapasitas nomor per kelompok (None = tak terbatas/berbasis kode toko)."""
    w = _seq_width(fmt)
    if w is None:
        return None
    if w == 0:
        return 9 if fmt == STORE_REVENUE_DEFAULT_FORMAT else None   # pola lama: satu digit
    return 10 ** w - 1


def _seq_regex(fmt: str, group: str) -> re.Pattern:
    """Regex kode berformat ``fmt`` di kelompok ``group``; grup 1 = nomor urut."""
    w = _seq_width(fmt)
    m = re.search(r"\{seq(?::0[1-4]d)?\}", fmt)
    head, tail = fmt[:m.start()], fmt[m.end():]

    def lit(s: str) -> str:
        return re.escape(s.replace("{prefix}", group[:5]).replace("{parent}", group))
    digits = (r"(\d)" if fmt == STORE_REVENUE_DEFAULT_FORMAT
              else (r"(\d{%d})" % w if w else r"(\d+)"))
    return re.compile("^" + lit(head) + digits + lit(tail) + "$")


async def store_revenue_settings(db) -> dict:
    """Setelan penomoran (Auto Akun → `store_revenue`), dengan cadangan bawaan."""
    try:
        from routes.coa_auto import get_auto_settings
        cfg = ((await get_auto_settings(db)).get("entity_types") or {}).get(STORE_REVENUE_KEY) or {}
    except Exception:  # noqa: BLE001 — setelan rusak tidak boleh menghentikan sinkron
        cfg = {}
    groups = dict(REVENUE_GROUP)
    for k, v in (cfg.get("parent_by_platform") or {}).items():
        if v:
            groups[canonical_platform(k)] = str(v).strip()
    fmt = cfg.get("code_format") or STORE_REVENUE_DEFAULT_FORMAT
    try:
        fmt = validate_code_format(fmt)
    except ValueError:
        fmt = STORE_REVENUE_DEFAULT_FORMAT
    return {"code_format": fmt, "parent_by_platform": groups}


async def _next_code(db, group: str, *, code_format: str = STORE_REVENUE_DEFAULT_FORMAT,
                     store_code: str = "") -> str:
    """Nomor akun pendapatan toko berikutnya di kelompok ``group`` menurut format."""
    fmt = code_format or STORE_REVENUE_DEFAULT_FORMAT
    if _seq_width(fmt) is None:                                   # berbasis kode toko
        base = render_store_revenue_code(fmt, group, store_code=store_code)
        code, n = base, 1
        while await db.rahaza_coa_accounts.find_one({"code": code}, {"_id": 0, "code": 1}):
            n += 1
            code = f"{base}-{n}"
        return code
    rx = _seq_regex(fmt, group)
    codes = [a["code"] async for a in db.rahaza_coa_accounts.find(
        {"code": {"$regex": "^" + re.escape(group[:5])}}, {"code": 1})]
    nums = [int(m.group(1)) for c in codes if (m := rx.match(c or ""))]
    nxt = max(nums + [0]) + 1
    cap = seq_capacity(fmt)
    if cap is not None and nxt > cap:
        raise ValueError(f"kelompok {group} penuh untuk format '{fmt}' (maks. {cap}) — ubah format "
                         "penomoran di Auto Akun › Pendapatan Toko")
    return render_store_revenue_code(fmt, group, nxt, store_code)


async def _store_revenue_accounts(db, groups: dict | None = None) -> dict:
    """Akun pendapatan toko (non-header) di semua kelompok platform — pola lama 4-11[123]x
    DAN kode berformat baru (K35) yang induknya kelompok platform."""
    parents = sorted(set((groups or REVENUE_GROUP).values()))
    return {a["code"]: a async for a in db.rahaza_coa_accounts.find(
        {"$or": [{"code": {"$regex": "^4-11[123]\\d$"}}, {"parent_code": {"$in": parents}}],
         "is_group": False}, {"_id": 0})}


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
    cfg = await store_revenue_settings(db)             # 2026-11-02 (K35)
    group = cfg["parent_by_platform"].get(canonical_platform(store.get("platform")))
    if not group:
        raise ValueError(f"platform '{store.get('platform')}' tidak punya kelompok akun pendapatan")
    if rev_accounts is None:
        rev_accounts = await _store_revenue_accounts(db, cfg["parent_by_platform"])
    if used is None:
        used = {c for c in await db.marketing_platform_accounts.distinct("coa_revenue_code") if c}
    key = _norm(store.get("account_name"))
    match = next((c for c, a in rev_accounts.items()
                  if (a.get("parent_code") == group or c.startswith(group[:5])) and c != group
                  and not a.get("is_group") and key and _norm(a["name"]) == key
                  and "lain" not in (a.get("name") or "").lower() and c not in used), None)
    flags = {"flags.store_account_code": store.get("account_code"), "flags.is_sales": True,
             "flags.channel": canonical_platform(store.get("platform"))}
    if match:
        await db.rahaza_coa_accounts.update_one({"code": match}, {"$set": {"active": True, **flags, "updated_at": _now()}})
        return {"code": match, "created": False}
    code = await _next_code(db, group, code_format=cfg["code_format"],
                            store_code=store.get("account_code") or "")
    doc = {"id": str(uuid.uuid4()), "code": code, "name": f"Penjualan – {store.get('account_name')}", "type": "REVENUE",
           "parent_code": group, "is_group": False, "normal_balance": "CREDIT",
           "flags": {"store_account_code": store.get("account_code"), "is_sales": True,
                     "channel": canonical_platform(store.get("platform"))},
           "cash_flow_group": "OPR", "active": True, "created_at": _now(), "updated_at": _now(),
           "created_by": "system", "created_by_name": "finance_sync",
           "code_format": cfg["code_format"]}
    await db.rahaza_coa_accounts.insert_one(doc)
    doc.pop("_id", None)
    rev_accounts[code] = doc
    return {"code": code, "created": True}


SYSTEM_CREATORS = {None, "", "system"}
SYSTEM_CREATOR_NAMES = {"auto-seed", "finance_sync", "system"}


def _system_created(a: dict) -> bool:
    return a.get("created_by") in SYSTEM_CREATORS or a.get("created_by_name") in SYSTEM_CREATOR_NAMES


async def store_revenue_deactivation_plan(db, *, rev_accounts: dict | None = None, used: set | None = None,
                                          parents: set | None = None) -> dict:
    """Akun pendapatan toko yang TIDAK dipakai toko mana pun → {deactivate: [kode], skipped: [{code,…,reason}]}.

    2026-11-02 (S2-H, T13): dulu SEMUA akun di kelompok pendapatan toko yang tak dipakai toko
    dinonaktifkan diam-diam tiap server menyala — termasuk akun yang sengaja dibuat/dihidupkan Finance.
    Kini yang dinonaktifkan hanya akun buatan SISTEM (seed/sinkron) tanpa rujukan konfigurasi lain;
    akun buatan/ubahan pengguna DILEWATI dan dilaporkan (log startup + Setup Akuntansi › Integritas COA).
    Satu fungsi untuk sinkron DAN laporan supaya keduanya tidak pernah berbeda."""
    cfg = await store_revenue_settings(db)
    if rev_accounts is None:
        rev_accounts = await _store_revenue_accounts(db, cfg["parent_by_platform"])
    if used is None:
        used = {s.get("coa_revenue_code") async for s in db.marketing_platform_accounts.find(
            {"active": {"$ne": False}}, {"_id": 0, "coa_revenue_code": 1}) if s.get("coa_revenue_code")}
    if parents is None:
        parents = set(cfg["parent_by_platform"].values())
    deactivate, skipped = [], []
    for c, a in rev_accounts.items():
        if c in used or not a.get("active", True) or c in parents or "lain" in (a.get("name") or "").lower():
            continue  # sub-total/header, "Lain-lain" (penampung) tetap hidup
        if await db.rahaza_journal_lines.count_documents({"account_code": c}) or await db.marketing_platform_accounts.count_documents({"coa_revenue_code": c}):
            continue
        reason = None
        if a.get("active_user_set"):
            reason = "status aktif diatur pengguna di Bagan Akun"
        elif not _system_created(a):
            reason = f"akun buatan pengguna ({a.get('created_by_name') or a.get('created_by')})"
        else:
            from core import coa_bindings as cb
            bl = [b for b in (await cb.collect_bindings(db, [c])).get(c, []) if b["kind"] in cb.CONFIG_KINDS]
            if bl:
                reason = "masih dirujuk — " + cb.describe(bl)
        if reason:
            skipped.append({"code": c, "name": a.get("name"), "reason": reason})
        else:
            deactivate.append(c)
    return {"deactivate": deactivate, "skipped": skipped}


async def _sync_stores(db, report: dict):
    stores = await db.marketing_platform_accounts.find({"active": {"$ne": False}}, {"_id": 0}).to_list(500)
    _cfg = await store_revenue_settings(db)            # 2026-11-02 (K35)
    rev_accounts = await _store_revenue_accounts(db, _cfg["parent_by_platform"])
    used, created, mapped, errors = set(), [], [], []
    for s in stores:
        group = revenue_group_for(s.get("platform"))   # 2026-11-02: `tiktokshop` dikenali
        if not group:
            continue
        code = s.get("coa_revenue_code")
        if not code or code not in rev_accounts:
            try:
                res = await ensure_store_revenue_account(db, s, rev_accounts=rev_accounts, used=used)
            except ValueError as e:
                # 2026-11-02 (S2-H): satu toko gagal (mis. kelompok penuh) tidak boleh menghentikan
                # seluruh sinkron startup (dulu ValueError → langkah sinkron berikutnya terlewati).
                errors.append({"store": s.get("account_code"), "error": str(e)})
                log.warning("[finance_sync] akun pendapatan toko %s gagal: %s", s.get("account_code"), e)
                continue
            code = res["code"]
            if res["created"]:
                created.append(code)
            await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_revenue_code": code, "updated_at": _now()}})
        used.add(code)
        ar = (await db.marketing_platform_accounts.find_one({"id": s["id"]}, {"_id": 0, "ar_account_code": 1}) or {}).get("ar_account_code") or CHANNEL_AR_PARENT
        await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_receivable_code": ar}})
        # Rekening pencairan default (1-1201) supaya penarikan saldo bisa dijurnal. 2026-11-02 (K4):
        # yang boleh menggantinya HANYA Finance lewat "Tautan Rekening Bank per Toko"
        # (`set_store_cash_code`); layar menandai `coa_cash_source=default` sebagai "belum diatur".
        if not (s.get("coa_cash_code") or "").strip() and await db.rahaza_coa_accounts.find_one({"code": "1-1201", "active": True}, {"_id": 0}):
            await db.marketing_platform_accounts.update_one({"id": s["id"]}, {"$set": {"coa_cash_code": "1-1201", "coa_cash_source": "default"}})
        # 2026-11-02 (D3) — baris Peta Akun Channel untuk toko TIDAK lagi dibuat/
        # dihidupkan/ditimpa di sini. `mapped` tetap dilaporkan (toko → akun) untuk
        # jejak sinkron; sumber COA toko adalah master toko itu sendiri.
        mapped.append((s.get("account_code"), code, ar))
    plan = await store_revenue_deactivation_plan(db, rev_accounts=rev_accounts, used=used,
                                                 parents=set(_cfg["parent_by_platform"].values()))
    deactivated = []
    for c in plan["deactivate"]:
        await db.rahaza_coa_accounts.update_one({"code": c}, {"$set": {"active": False, "updated_at": _now(), "deactivated_reason": "toko tidak ada di master (finance_sync)"}})
        deactivated.append(c)
    if deactivated:
        log.warning("[finance_sync] akun pendapatan toko buatan sistem tanpa toko DINONAKTIFKAN: %s", deactivated)
    if plan["skipped"]:
        log.warning("[finance_sync] akun pendapatan toko tanpa toko DILEWATI (buatan/ubahan pengguna): %s",
                    [(x["code"], x["reason"]) for x in plan["skipped"]])
    stale = await db.rahaza_channel_gl_mapping.update_many({"channel_key": {"$nin": [s.get("account_code") for s in stores]}, "active": True},
                                                            {"$set": {"active": False, "updated_at": _now()}})
    report["stores"] = {"mapped": mapped, "revenue_created": created, "revenue_deactivated": deactivated,
                        "revenue_deactivation_skipped": plan["skipped"], "revenue_errors": errors,
                        "channel_map_deactivated": stale.modified_count}


# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-02 (K4) — SATU PINTU REKENING TUJUAN PER TOKO
# ══════════════════════════════════════════════════════════════════════════════
CASH_SOURCES = ("finance", "excel_master", "default")


async def set_store_cash_code(db, store: dict, code: str, *, user: dict | None = None,
                              source: str = "finance") -> dict:
    """Tautkan rekening pencairan (``coa_cash_code``) satu toko — dipakai layar Finance
    "Tautan Rekening Bank per Toko" (`PUT …/payout-bank`) DAN impor Excel master
    (sheet TOKO). Jalur lain (API Kelola Akun) tidak boleh menulis field ini.

    Selalu memperbarui penanda sumber (`coa_cash_source`) + pengubahnya, supaya layar
    bisa membedakan rekening bawaan 1-1201 dari yang sudah dipilih Finance.
    ``ValueError`` bila kode bukan rekening kas/bank aktif.
    """
    from core import payout_banks as _banks
    c = (code or "").strip()
    if source not in CASH_SOURCES:
        raise ValueError(f"sumber rekening '{source}' tidak dikenal")
    if not c or not await _banks.is_bank_code(db, c):
        raise ValueError(f"Rekening '{c}' tidak ada di daftar Kas & Bank / COA kas-bank aktif.")
    who = (user or {}).get("email") or (user or {}).get("name") if isinstance(user, dict) else None
    await db.marketing_platform_accounts.update_one({"id": store["id"]}, {"$set": {
        "coa_cash_code": c, "coa_cash_source": source, "coa_cash_updated_by": who,
        "coa_cash_updated_at": _now(), "updated_at": _now()}})
    return {"code": c, "source": source, "previous": (store.get("coa_cash_code") or "") or None}


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
