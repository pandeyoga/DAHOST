"""
CV. Dewi Aditya — Phase 5: Auto-Create COA Subledger + Posting Integration
─────────────────────────────────────────────────────────────────────────────
Tujuan: saat entitas (mis. Vendor CMT, Bank) dibuat, akun COA "subledger"
otomatis dibuat di bawah akun kontrol (parent) → transaksi posting memakai akun
per-entitas tsb → GL menampilkan saldo per-entitas (bukan campur di 1 kontrol).

Prinsip:
- IDEMPOTENT: ditandai lewat flags.subledger_entity_type + subledger_entity_id.
  Panggil berkali-kali → 1 akun saja (tak ada duplikasi).
- NON-FATAL: helper tak pernah raise ke alur bisnis; kembalikan dict {ok,...}.
- Kode akun: "{parent}-{code_hint||seq}" (mis. "2-1100-CMT-001").
- Tipe & normal_balance diwarisi dari parent; is_group=False (postable leaf).

Collection: rahaza_coa_auto_settings (single doc id='default')
Registry entity_type default:
  cmt_vendor → dewi_cmt_partners (parent 2-1100 Hutang Usaha/AP), field ap_account_code
  bank       → rahaza_cash_accounts (parent 1-1200 Bank), field gl_account_code
"""
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from routes.shared import require_portal_dep
from database import get_db
from auth import require_auth, log_activity
import uuid
import re
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/rahaza/coa-auto",
    tags=["rahaza-coa-auto"],
    dependencies=[Depends(require_portal_dep("finance"))],
)

NORMAL_DEBIT = {"ASSET", "COGS", "EXPENSE", "OTHER_EXPENSE"}


def _uid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _normal_balance_for(acc_type: str) -> str:
    return "DEBIT" if (acc_type or "").upper() in NORMAL_DEBIT else "CREDIT"


# ─────────────── Default settings — Phase 6 rollout (5 entitas inti aktif) ──────
# Parent dipilih agar cocok dengan akun kontrol yang dipakai posting profile,
# sehingga akun subledger ROLL-UP ke kontrol yang sama (GL total tak berubah):
#   ap_invoice.credit_ap = 2-1100 (Hutang Usaha)         → supplier + cmt_vendor
#   ar_invoice.debit_ar  = 1-1301 (Piutang Usaha—Dagang) → customer
#   channel/online shop  = 1-1303 (Piutang Platform Online Shop)
#   bank/kas             = 1-1200 (Bank, group)
DEFAULT_ENTITY_TYPES = {
    "cmt_vendor": {
        "enabled": True,
        "parent_code": "2-1110",          # Hutang Vendor CMT (Termin) — Excel owner 2026-09-12
        "label": "Vendor CMT — Hutang (AP)",
        "collection": "vendor_partners",  # SSOT master vendor CMT (core/cmt_vendor_master)
        "target_field": "ap_account_code",
        "name_prefix": "Hutang CMT",
    },
    "supplier": {
        "enabled": True,
        "parent_code": "2-1100",          # Hutang Usaha (AP control)
        "label": "Supplier Bahan/Aksesori — Hutang (AP)",
        "collection": "rahaza_vendors",
        "target_field": "ap_account_code",
        "name_prefix": "Hutang Supplier",
    },
    "customer": {
        "enabled": True,
        "parent_code": "1-1301",          # Piutang Usaha — Dagang (AR control)
        "label": "Pelanggan / Buyer — Piutang (AR)",
        "collection": "rahaza_customers",
        "target_field": "ar_account_code",
        "name_prefix": "Piutang Pelanggan",
    },
    "channel": {
        "enabled": True,
        "parent_code": "1-1303",          # Piutang Platform Online Shop (AR control, 4-digit kanonik)
        "label": "Channel / Toko Online — Piutang (AR)",
        "collection": "marketing_platform_accounts",
        "target_field": "ar_account_code",
        "name_prefix": "Piutang Channel",
    },
    "maklon_client": {
        "enabled": True,
        "parent_code": "1-1305",          # Piutang Usaha — Maklon
        "label": "Klien Maklon — Piutang (AR)",
        "collection": "dewi_maklon_clients",
        "target_field": "ar_account_code",
        "name_prefix": "Piutang Maklon",
    },
    "bank": {
        "enabled": True,
        "parent_code": "1-1200",          # Bank (group control)
        "label": "Bank / Rekening Kas",
        "collection": "rahaza_cash_accounts",
        "target_field": "gl_account_code",
        "name_prefix": "Bank",
    },
    # 2026-11-02 (K35) — PENOMORAN akun pendapatan per toko (bukan subledger biasa).
    # Dibaca `core.finance_sync.ensure_store_revenue_account`. `collection` sengaja
    # kosong ⇒ backfill subledger generik melewatinya (akun pendapatan toko dibuat
    # saat toko dibuat / sinkron master, bukan lewat tombol backfill).
    "store_revenue": {
        "enabled": True,
        "kind": "store_revenue",
        "parent_code": "",
        "parent_by_platform": {"shopee": "4-1110", "tiktok": "4-1120", "tokopedia": "4-1130"},
        "code_format": "{prefix}{seq}",   # pola lama 4-111x (maks. 9 per platform)
        "label": "Toko Online — Akun Pendapatan per Toko (penomoran)",
        "collection": "",
        "target_field": "coa_revenue_code",
        "name_prefix": "Penjualan –",
    },
}

# Kunci lookup entitas per koleksi (id selalu didukung; ini utk lookup by code).
ENTITY_CODE_FIELDS = {
    "dewi_cmt_partners": ["code"],
    "vendor_partners": ["code"],
    "dewi_maklon_clients": ["code"],
    "rahaza_vendors": ["code"],
    "rahaza_customers": ["code"],
    "marketing_platform_accounts": ["account_code", "code"],
    "rahaza_cash_accounts": ["code"],
}


async def get_auto_settings(db) -> dict:
    """Ambil settings (seed default bila belum ada)."""
    doc = await db.rahaza_coa_auto_settings.find_one({"id": "default"}, {"_id": 0})
    if not doc:
        doc = {
            "id": "default",
            "entity_types": DEFAULT_ENTITY_TYPES,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.rahaza_coa_auto_settings.insert_one(dict(doc))
        doc.pop("_id", None)
    else:
        # merge defaults untuk key baru yang belum tersimpan
        et = doc.get("entity_types") or {}
        changed = False
        for k, v in DEFAULT_ENTITY_TYPES.items():
            if k not in et:
                et[k] = v
                changed = True
            else:
                # pastikan field meta (collection/target_field/name_prefix) selalu ada
                for meta in ("collection", "target_field", "name_prefix", "label",
                             "kind", "parent_by_platform", "code_format"):
                    if meta in v and meta not in et[k]:
                        et[k][meta] = v[meta]
                        changed = True
        if changed:
            await db.rahaza_coa_auto_settings.update_one(
                {"id": "default"}, {"$set": {"entity_types": et, "updated_at": _now()}}
            )
        doc["entity_types"] = et
    return doc


def _sanitize_hint(hint: str) -> str:
    h = re.sub(r"[^A-Za-z0-9\-]", "", (hint or "").strip().upper())
    return h[:24]


async def ensure_subledger_account(
    db,
    entity_type: str,
    entity_id: str,
    name: str,
    code_hint: str = None,
    user: dict = None,
    parent_code: str = None,
) -> dict:
    """Buat/temukan akun subledger untuk sebuah entitas. IDEMPOTENT + NON-FATAL.

    Return: {ok, created(bool), code, account, error?}
    """
    try:
        if not entity_id:
            return {"ok": False, "error": "entity_id kosong"}

        settings = await get_auto_settings(db)
        cfg = (settings.get("entity_types") or {}).get(entity_type) or {}
        parent = parent_code or cfg.get("parent_code")
        if not parent:
            return {"ok": False, "error": f"parent_code untuk '{entity_type}' tidak diset"}

        # 1) idempotent: sudah ada akun untuk entitas ini?
        existing = await db.rahaza_coa_accounts.find_one(
            {
                "flags.subledger_entity_type": entity_type,
                "flags.subledger_entity_id": entity_id,
            },
            {"_id": 0},
        )
        if existing:
            # refresh nama bila berubah — 2026-11-02 (S2-H, T15): KECUALI nama yang diubah Finance di
            # Bagan Akun (`name_user_set`); dulu nama itu ditimpa lagi setiap entitas disimpan/startup.
            if name and existing.get("name") != name and not existing.get("name_user_set"):
                await db.rahaza_coa_accounts.update_one(
                    {"id": existing["id"]},
                    {"$set": {"name": name, "updated_at": _now()}},
                )
                existing["name"] = name
            return {"ok": True, "created": False, "code": existing["code"], "account": existing}

        # 2) parent harus ada (dan aktif — 2026-11-02 S2-H: sub-ledger baru tidak dibuat di bawah induk nonaktif)
        parent_acc = await db.rahaza_coa_accounts.find_one({"code": parent}, {"_id": 0})
        if not parent_acc:
            return {"ok": False, "error": f"Akun parent '{parent}' tidak ditemukan di COA"}
        if parent_acc.get("active", True) is False:
            return {"ok": False, "error": f"Akun parent '{parent}' nonaktif di Bagan Akun — aktifkan lagi atau "
                                          f"ganti induk di Auto Akun"}

        acc_type = parent_acc.get("type") or "LIABILITY"
        normal = parent_acc.get("normal_balance") or _normal_balance_for(acc_type)

        # 3) generate kode unik
        hint = _sanitize_hint(code_hint)
        if hint:
            base = f"{parent}-{hint}"
        else:
            seq = await db.rahaza_coa_accounts.count_documents(
                {"flags.subledger_parent": parent}
            )
            base = f"{parent}-{seq + 1:03d}"
        code = base
        n = 1
        while await db.rahaza_coa_accounts.find_one({"code": code}, {"_id": 0}):
            n += 1
            code = f"{base}-{n}"

        doc = {
            "id": _uid(),
            "code": code,
            "name": name or f"{parent_acc.get('name','')} — {entity_id[:8]}",
            "type": acc_type,
            "parent_code": parent,
            "is_group": False,
            "normal_balance": normal,
            "flags": {
                "subledger": True,
                "subledger_entity_type": entity_type,
                "subledger_entity_id": entity_id,
                "subledger_parent": parent,
            },
            "active": True,
            "created_at": _now(),
            "updated_at": _now(),
            "created_by": (user or {}).get("id") or "system",
            "created_by_name": (user or {}).get("name") or "system",
        }
        await db.rahaza_coa_accounts.insert_one(dict(doc))
        doc.pop("_id", None)
        try:
            if user:
                await log_activity(
                    user.get("id", "system"), user.get("name", "system"),
                    "auto_create_coa", "coa", f"{code} ({entity_type})",
                )
        except Exception as e:  # noqa: BLE001 — jejak aktivitas tidak boleh
            # membatalkan pembuatan akun COA yang sudah berhasil, tapi hilangnya
            # jejak audit harus tetap terlihat (dulu `pass` tanpa suara).
            log.warning("[coa_auto] gagal mencatat jejak aktivitas pembuatan COA %s (%s): %s",
                        code, entity_type, e)
        return {"ok": True, "created": True, "code": code, "account": doc}
    except Exception as e:
        log.warning(f"[coa_auto] ensure_subledger_account failed ({entity_type}/{entity_id}): {e}")
        return {"ok": False, "error": str(e)}


async def ensure_subledger_for_entity(db, entity_type: str, entity_doc: dict, user: dict = None, parent_code: str = None) -> dict:
    """Convenience: baca id/code/name dari dokumen entitas, buat subledger, lalu
    tulis kode akun kembali ke field target di koleksi entitas. NON-FATAL."""
    try:
        settings = await get_auto_settings(db)
        cfg = (settings.get("entity_types") or {}).get(entity_type) or {}
        if not cfg.get("enabled"):
            return {"ok": False, "skipped": True, "reason": "disabled"}

        entity_id = entity_doc.get("id")
        code_hint = entity_doc.get("code") or entity_doc.get("account_code") or ""
        ent_name = entity_doc.get("name") or entity_doc.get("account_name") or entity_id
        acc_name = f"{cfg.get('name_prefix','Subledger')} — {ent_name}"

        res = await ensure_subledger_account(
            db, entity_type, entity_id, acc_name, code_hint=code_hint, user=user,
            parent_code=parent_code or cfg.get("parent_code"),
        )
        if res.get("ok"):
            target_field = cfg.get("target_field") or "gl_account_code"
            collection = cfg.get("collection")
            if collection and target_field:
                await db[collection].update_one(
                    {"id": entity_id},
                    {"$set": {target_field: res["code"], "updated_at": _now()}},
                )
        return res
    except Exception as e:
        log.warning(f"[coa_auto] ensure_subledger_for_entity failed: {e}")
        return {"ok": False, "error": str(e)}


async def resolve_subledger_account(
    db,
    entity_type: str,
    entity_id: str = None,
    entity_code: str = None,
    entity_name: str = None,
    user: dict = None,
) -> str:
    """GENERIC posting resolver → kode akun subledger per-entitas, atau None.

    Dipakai saat posting (AR/AP) untuk mengarahkan jurnal ke akun per-entitas.
    Alur (NON-FATAL):
      1) Jika entity_type disabled di settings → None (caller pakai akun kontrol).
      2) Cari dokumen entitas di koleksinya (by id, else by code).
         - Bila tak ada dokumen master → None (tak bisa buat subledger utk entitas
           yang tak ada; caller fallback ke kontrol).
      3) Jika target_field entitas sudah berisi akun valid (aktif, non-group) → pakai.
      4) Else LAZY-CREATE subledger + tulis balik ke target_field → pakai.
    """
    try:
        settings = await get_auto_settings(db)
        cfg = (settings.get("entity_types") or {}).get(entity_type) or {}
        if not cfg.get("enabled"):
            return None
        collection = cfg.get("collection")
        target_field = cfg.get("target_field") or "gl_account_code"
        if not collection:
            return None

        ent = None
        if entity_id:
            ent = await db[collection].find_one({"id": entity_id}, {"_id": 0})
        if not ent and entity_code:
            code_fields = ENTITY_CODE_FIELDS.get(collection, ["code"])
            for f in code_fields:
                ent = await db[collection].find_one({f: entity_code}, {"_id": 0})
                if ent:
                    break
        if not ent:
            return None

        # (3) target_field sudah valid?
        code = ent.get(target_field)
        if code:
            acc = await db.rahaza_coa_accounts.find_one({"code": code, "active": True}, {"_id": 0})
            if acc and not acc.get("is_group"):
                return code

        # (4) lazy-create
        res = await ensure_subledger_for_entity(db, entity_type, ent, user)
        if res.get("ok"):
            return res["code"]
        return None
    except Exception as e:
        log.warning(f"[coa_auto] resolve_subledger_account failed ({entity_type}): {e}")
        return None


async def resolve_ap_account_for_cmt(db, cmt_partner_id: str, cmt_name: str = "", user: dict = None) -> str:
    """Untuk posting cmt_ap_invoice: kembalikan kode akun AP per-vendor CMT.
    (Backward-compat wrapper di atas resolve_subledger_account.)"""
    if not cmt_partner_id:
        return None
    from core.cmt_vendor_master import canonical_id
    vid = await canonical_id(db, cmt_partner_id) or cmt_partner_id  # id lama dewi_cmt_partners → SSOT vendor_partners
    return await resolve_subledger_account(
        db, "cmt_vendor", entity_id=vid, entity_name=cmt_name, user=user
    )


# ────────────────────────────── ENDPOINTS ─────────────────────────────────────
@router.get("/settings")
async def get_settings(request: Request):
    db = get_db()
    return await get_auto_settings(db)


@router.put("/settings")
async def update_settings(request: Request):
    db = get_db()
    user = await require_auth(request)
    body = await request.json()
    incoming = body.get("entity_types") or {}
    settings = await get_auto_settings(db)
    et = settings.get("entity_types") or {}
    # hanya izinkan update field enabled + parent_code per entity_type yang dikenal
    for key, patch in incoming.items():
        if key not in et:
            continue
        if key == "store_revenue":
            # 2026-11-02 (K35) — penomoran akun pendapatan toko: format + kelompok per platform.
            et[key] = await _patch_store_revenue(db, et[key], patch or {})
            continue
        if "enabled" in patch:
            et[key]["enabled"] = bool(patch["enabled"])
        if patch.get("parent_code"):
            pc = str(patch["parent_code"]).strip()
            parent = await db.rahaza_coa_accounts.find_one({"code": pc}, {"_id": 0})
            if not parent:
                raise HTTPException(400, f"Akun parent '{pc}' tidak ada di COA.")
            await _guard_parent(db, key, parent)
            et[key]["parent_code"] = pc
    await db.rahaza_coa_auto_settings.update_one(
        {"id": "default"},
        {"$set": {"entity_types": et, "updated_at": _now(), "updated_by": user.get("id")}},
    )
    await log_activity(user.get("id", ""), user.get("name", ""), "update_coa_auto_settings", "coa_auto", "settings")
    return {"ok": True, "entity_types": et}


def _family(t: str) -> str:
    t = (t or "").upper()
    return t if t in ("ASSET", "LIABILITY", "EQUITY") else ("INCOME" if t in ("REVENUE", "OTHER_INCOME") else "EXPENSE")


async def _guard_parent(db, key: str, parent: dict) -> None:
    """2026-11-02 (S2-H): induk sub-ledger harus AKTIF dan sekeluarga tipe dengan induk bawaannya
    (hutang di bawah liabilitas, piutang/bank di bawah aset). Dulu induk apa pun yang ada diterima →
    sub-ledger hutang vendor bisa lahir di bawah akun beban."""
    if parent.get("active", True) is False:
        raise HTTPException(400, f"Akun induk '{parent.get('code')}' nonaktif di Bagan Akun.")
    dflt = (DEFAULT_ENTITY_TYPES.get(key) or {}).get("parent_code")
    if not dflt:
        return
    ref = await db.rahaza_coa_accounts.find_one({"code": dflt}, {"_id": 0, "type": 1})
    want = (ref or {}).get("type") or ("LIABILITY" if dflt.startswith("2-") else "ASSET")
    if _family(parent.get("type")) != _family(want):
        raise HTTPException(400, f"Akun induk '{parent.get('code')}' bertipe {parent.get('type')}; induk "
                                 f"sub-ledger '{key}' harus bertipe {want} (seperti bawaan {dflt}).")


async def _patch_store_revenue(db, cur: dict, patch: dict) -> dict:
    """Validasi & terapkan setelan penomoran akun pendapatan toko (K35). Toko LAMA tidak
    disentuh — format hanya berlaku untuk akun pendapatan toko BARU."""
    from core import finance_sync as _fs
    out = dict(cur or {})
    if "code_format" in patch:
        try:
            out["code_format"] = _fs.validate_code_format(str(patch.get("code_format") or ""))
        except ValueError as e:
            raise HTTPException(400, f"Format penomoran pendapatan toko: {e}")
    groups = dict(out.get("parent_by_platform") or {})
    for plat, code in (patch.get("parent_by_platform") or {}).items():
        p = _fs.canonical_platform(plat)
        c = str(code or "").strip()
        if not c:
            continue
        acc = await db.rahaza_coa_accounts.find_one({"code": c}, {"_id": 0})
        if not acc:
            raise HTTPException(400, f"Kelompok pendapatan '{c}' ({p}) tidak ada di COA.")
        if (acc.get("type") or "").upper() != "REVENUE":
            raise HTTPException(400, f"Akun '{c}' bukan akun pendapatan (REVENUE).")
        if acc.get("active", True) is False:   # 2026-11-02 (S2-H)
            raise HTTPException(400, f"Kelompok pendapatan '{c}' nonaktif di Bagan Akun.")
        groups[p] = c
    out["parent_by_platform"] = groups
    out["enabled"] = True
    return out


@router.get("/store-revenue/preview")
async def store_revenue_preview(request: Request, code_format: str = Query(""),
                                platform: str = Query("shopee"), store_code: str = Query("SHP-XX")):
    """Nomor akun pendapatan toko BERIKUTNYA bila format ini dipakai (tanpa menulis apa pun)."""
    from core import finance_sync as _fs
    db = get_db()
    cfg = await _fs.store_revenue_settings(db)
    fmt = code_format or cfg["code_format"]
    try:
        fmt = _fs.validate_code_format(fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    group = cfg["parent_by_platform"].get(_fs.canonical_platform(platform))
    if not group:
        raise HTTPException(400, f"Platform '{platform}' tidak punya kelompok pendapatan.")
    try:
        nxt = await _fs._next_code(db, group, code_format=fmt, store_code=store_code)
    except ValueError as e:
        return {"ok": False, "code_format": fmt, "group": group, "error": str(e),
                "capacity": _fs.seq_capacity(fmt)}
    return {"ok": True, "code_format": fmt, "group": group, "next_code": nxt,
            "capacity": _fs.seq_capacity(fmt)}


@router.post("/backfill/{entity_type}")
async def backfill(entity_type: str, request: Request, commit: bool = Query(False)):
    """Backfill subledger untuk semua entitas dari sebuah entity_type.
    dry-run (commit=false) → hanya laporan; commit=true → buat akun + tulis field."""
    db = get_db()
    user = await require_auth(request)
    settings = await get_auto_settings(db)
    cfg = (settings.get("entity_types") or {}).get(entity_type)
    if not cfg:
        raise HTTPException(404, f"entity_type '{entity_type}' tidak dikenal.")
    collection = cfg.get("collection")
    if not collection:
        raise HTTPException(400, f"collection untuk '{entity_type}' tidak diset.")

    total = 0
    would_create = 0
    already = 0
    created = 0
    errors = []
    samples = []
    async for ent in db[collection].find({}, {"_id": 0}):
        total += 1
        entity_id = ent.get("id")
        if not entity_id:
            continue
        existing = await db.rahaza_coa_accounts.find_one(
            {"flags.subledger_entity_type": entity_type, "flags.subledger_entity_id": entity_id},
            {"_id": 0, "code": 1},
        )
        if existing:
            already += 1
            continue
        would_create += 1
        if commit:
            res = await ensure_subledger_for_entity(db, entity_type, ent, user)
            if res.get("ok"):
                created += 1
                if len(samples) < 10:
                    samples.append({"entity": ent.get("code") or entity_id, "account": res.get("code")})
            else:
                errors.append({"entity": ent.get("code") or entity_id, "error": res.get("error")})
        else:
            if len(samples) < 10:
                samples.append({"entity": ent.get("code") or entity_id, "account": "(akan dibuat)"})

    if commit:
        await log_activity(user.get("id", ""), user.get("name", ""), "backfill_coa_subledger", "coa_auto",
                           f"{entity_type}: {created} dibuat")
    return {
        "ok": True,
        "entity_type": entity_type,
        "collection": collection,
        "committed": commit,
        "total_entities": total,
        "already_have_account": already,
        "would_create": would_create,
        "created": created,
        "errors": errors,
        "samples": samples,
    }
