# ruff: noqa: F401
"""
marketing_accounts.py — Platform Account Management
Extracted from marketing.py (1757 LOC monolith)

Refactored: Session #11.19 Phase 3.2 Batch #3
Endpoints: POST /accounts, GET /accounts, GET /accounts/{id}, PUT /accounts/{id}, DELETE /accounts/{id}
"""
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from database import get_db
from core import marketing_account_scope as scope
from auth import require_auth, serialize_doc, log_activity
from routes.marketing_shared import _uid, _now, _get_user, _sanitize, PlatformAccountCreate, PlatformAccountUpdate, SalesDataEntry
from routes.marketing_shared import refresh_stale_health_scores
from core import marketing_sales_shape as _shape
from core.authz import only  # T-01 2.3

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/marketing', tags=['Marketing-Accounts'])

# ══════════════════════════════════════════════════════════════════════════════
# F0.7 — pembantu tautan Finance (bagan akun `rahaza_coa_accounts`)
# Kenapa di sini: layar Manajemen Akun harus bisa MENGISI & MENAMPILKAN tautan
# COA per toko. Aturan keras: kode COA tidak pernah dikarang — kalau tidak ada
# di bagan akun, field dibiarkan kosong / permintaan ditolak 400.
# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-02 (No.10) — `tiktok` (3 toko seed) dan `tiktokshop` (nilai layar) adalah
# platform yang SAMA. Dulu endpoint menolak `tiktok` (400) dan toko `tiktok` tidak
# mendapat saran akun pendapatan. Nilai yang tersimpan di master tidak diubah.
PLATFORM_TO_COA_CHANNEL = {"shopee": "shopee", "tiktokshop": "tiktok", "tiktok": "tiktok",
                           "tokopedia": "tokopedia"}
VALID_PLATFORMS = ("shopee", "tiktokshop", "tiktok", "tokopedia")
TIKTOK_ALIASES = scope.TIKTOK_PLATFORMS
DEFAULT_CASH_CODE = "1-1201"         # Bank BCA (kanonik 4-digit)
DEFAULT_RECEIVABLE_CODE = "1-1303"   # Piutang Platform Online Shop


def _usable_coa(row: dict) -> bool:
    """Akun yang boleh dipilih manusia: bukan akun grup/header dan masih aktif."""
    return bool(row) and not row.get("is_group") and row.get("active", True)


async def _coa_exists(db, code: str) -> bool:
    return bool(await db.rahaza_coa_accounts.find_one({"code": code}, {"_id": 0, "code": 1}))


def _flag(row: dict, key: str) -> bool:
    return bool((row.get("flags") or {}).get(key))


# Aturan peran akun: bukan cuma "ada di COA", tapi harus AKUN YANG BENAR.
# (Ditemukan lewat test_core_f07_accounts_ui.py: `9-000 BIAYA UMUM & ADMINISTRASI`
#  — akun grup beban — sebelumnya lolos sebagai "rekening pencairan".)
COA_ROLE_RULES = {
    "coa_revenue_code": {
        "field": "Akun Pendapatan",
        "label": "akun pendapatan penjualan",
        "ok": lambda r: r.get("type") == "REVENUE" and _flag(r, "is_sales") and not _flag(r, "is_contra"),
        "lenient": lambda r: r.get("type") == "REVENUE",
        "hint": "pilih akun penjualan toko (mis. 4-122 Penjualan – TikTok Outfit Boutique)",
    },
    "coa_cash_code": {
        "field": "Rekening Pencairan",
        "label": "rekening kas/bank penerima pencairan",
        "ok": lambda r: _flag(r, "is_bank") or _flag(r, "is_cash"),
        "lenient": lambda r: r.get("type") == "ASSET",
        "hint": "pilih rekening kas/bank/e-wallet (mis. 1-1201 Bank BCA)",
    },
    "coa_receivable_code": {
        "field": "Akun Piutang Platform",
        "label": "akun piutang platform",
        "ok": lambda r: _flag(r, "is_ar"),
        "lenient": lambda r: r.get("type") == "ASSET",
        "hint": "pilih akun piutang (mis. 1-1303 Piutang Platform Online Shop)",
    },
}


async def _validate_coa_role(db, fname: str, code: str) -> dict:
    """Pastikan `code` ada, bukan akun grup, masih aktif, dan berperan benar.
    Melempar HTTPException 400 dengan pesan yang bisa ditindaklanjuti staf."""
    rule = COA_ROLE_RULES.get(fname) or {}
    field = rule.get("field") or fname
    row = await db.rahaza_coa_accounts.find_one(
        {"code": code},
        {"_id": 0, "code": 1, "name": 1, "type": 1, "flags": 1, "is_group": 1, "active": 1})
    if not row:
        raise HTTPException(400, f"{field}: akun COA '{code}' tidak ada di bagan akun. "
                                 f"Buat dulu di Portal Keuangan → COA.")
    label = f"{code} — {row.get('name') or ''}".strip(" —")
    if row.get("is_group"):
        raise HTTPException(400, f"{field}: '{label}' adalah akun induk (grup) dan tidak bisa "
                                 f"dipakai untuk posting. Pilih akun rinciannya.")
    if not row.get("active", True):
        raise HTTPException(400, f"{field}: akun '{label}' sudah tidak aktif.")
    if fname == "coa_cash_code":
        from core.payout_banks import is_bank_code
        if not await is_bank_code(db, code):
            raise HTTPException(400, f"{field}: '{label}' bukan {rule['label']}. "
                                     f"Silakan {rule['hint']}.")
        return row
    if rule:
        # Bila bagan akun belum memakai `flags` (DB lama), pakai pemeriksaan longgar
        # berbasis tipe akun supaya akun yang sah tidak ditolak keliru.
        checker = rule["ok"] if (row.get("flags") or {}) else rule["lenient"]
        if not checker(row) and not await _subledger_parent_ok(db, row, rule):
            raise HTTPException(400, f"{field}: '{label}' bukan {rule['label']}. "
                                     f"Silakan {rule['hint']}.")
    return row


async def _subledger_parent_ok(db, row: dict, rule: dict) -> bool:
    """Akun subledger otomatis (mis. `1-1303-TTK-03 Piutang Channel — …`) dibuat tanpa
    flags peran (`is_ar`); perannya diwarisi dari akun induknya (`1-1303`).
    2026-11-04 — dulu subledger ditolak sehingga SEMUA toko gagal disimpan dari Kelola Akun."""
    flags = row.get("flags") or {}
    parent_code = flags.get("subledger_parent") or (row.get("parent_code") if flags.get("subledger") else "")
    if not (flags.get("subledger") and parent_code):
        return False
    parent = await db.rahaza_coa_accounts.find_one(
        {"code": parent_code}, {"_id": 0, "code": 1, "type": 1, "flags": 1, "is_group": 1, "active": 1})
    if not parent:
        return False
    checker = rule["ok"] if (parent.get("flags") or {}) else rule["lenient"]
    return bool(checker(parent))


async def _fallback_revenue_code(db, platform: str) -> str:
    """Akun pendapatan penampung per platform (`4-114` Shopee · `4-126` TikTok ·
    `4-131` Tokopedia). Dipakai HANYA bila toko baru belum punya akun sendiri —
    supaya tidak ada toko tanpa alamat jurnal (RENCANA_EKSEKUSI_MASTER §F0.7).

    2026-11-02 (No.10b) — toko BARU tidak lagi diberi akun ini (lihat
    `create_platform_account`); fungsi ini tinggal sebagai saran di layar untuk
    toko LAMA yang belum bertaut akun pendapatan."""
    channel = PLATFORM_TO_COA_CHANNEL.get(platform or "")
    if not channel:
        return ""
    rows = await db.rahaza_coa_accounts.find(
        {"type": "REVENUE", "flags.is_sales": True, "flags.channel": channel},
        {"_id": 0, "code": 1, "name": 1, "is_group": 1, "active": 1},
    ).sort("code", 1).to_list(100)
    rows = [r for r in rows if _usable_coa(r)]
    if not rows:
        return ""
    catchall = [r for r in rows if "lain" in (r.get("name") or "").lower()]
    return (catchall[0] if catchall else rows[0])["code"]


async def _default_cash_code(db) -> str:
    """Rekening penerima pencairan default (1-1201); fallback ke kas/bank pertama."""
    row = await db.rahaza_coa_accounts.find_one(
        {"code": DEFAULT_CASH_CODE}, {"_id": 0, "code": 1, "is_group": 1, "active": 1})
    if _usable_coa(row):
        return DEFAULT_CASH_CODE
    row = await db.rahaza_coa_accounts.find_one(
        {"$or": [{"flags.is_bank": True}, {"flags.is_cash": True}],
         "is_group": {"$ne": True}},
        {"_id": 0, "code": 1}, sort=[("code", 1)])
    return (row or {}).get("code", "")


# 2026-11-02 (K4) — SATU PINTU rekening tujuan per toko = layar Finance "Tautan Rekening
# Bank per Toko" (`PUT /api/marketing/withdrawals/accounts/{id}/payout-bank`). Dulu API
# Kelola Akun masih menerima `coa_cash_code` tanpa gerbang Finance: manager_marketing
# bisa membelokkan jurnal kas penarikan (uji w2 T4), dan penanda sumber tetap "finance".
CASH_ONE_DOOR_MSG = ("Rekening pencairan toko hanya diatur Finance di Portal Keuangan → Saldo & "
                     "Pencairan Marketplace → 'Tautan Rekening Bank per Toko'.")


def cash_code_change_blocked(current: Optional[str], incoming: Optional[str]) -> bool:
    """True bila permintaan Kelola Akun mencoba MENGUBAH rekening pencairan (ditolak)."""
    if incoming is None:
        return False
    return (incoming or "").strip() != (current or "").strip()


PIC_NEEDS_TOKO_MSG = ("PIC toko harus pengguna yang punya akses Portal Toko. Beri dulu aksesnya di "
                      "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses (atau tab Pengguna), "
                      "atau pilih pengguna lain.")


async def _resolve_pic(db, pic_user_id, current: Optional[str] = None):
    """(pic_user_id, pic_user_name) — 400 bila id pengguna tidak ada.

    2026-11-07 (Tahap 6, MK3 — keputusan owner): PIC BARU wajib punya akses Portal Toko (aturan akses yang
    sama dengan menu: `routes.shared.user_has_portal`). PIC lama yang tidak diganti (`current`) tidak
    diperiksa ulang, supaya menyimpan perubahan lain pada toko itu tidak ditolak.
    """
    pid = (pic_user_id or "").strip()
    if not pid:
        return None, None
    user = await db.users.find_one({"id": pid}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1})
    if not user:
        raise HTTPException(400, f"PIC dengan id '{pid}' tidak ditemukan di daftar pengguna")
    if pid != (current or ""):
        from routes.shared import user_has_portal
        if not await user_has_portal(db, user, "toko"):
            raise HTTPException(400, PIC_NEEDS_TOKO_MSG)
    return pid, (user.get("name") or user.get("email"))


STORE_MANAGE_DENIED = ("Peran Anda belum dicentang \"Kelola Akun\" (Tambah, Ubah, atau Hapus) di "
                       "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses. "
                       "Bila ada data toko yang salah, minta owner atau SPV Marketing memperbaikinya.")


def can_manage_stores(user: Optional[dict], action: Optional[str] = None) -> bool:
    """Boleh menambah/mengubah/menghapus master toko?

    5 Nov 2026: dibatasi ke SPV/manajemen karena PIC toko membuat toko yang SUDAH ADA (satu toko tercatat dua kali,
    plus akun Penjualan + Piutang ganda di Bagan Akun). 13 Nov 2026 (owner: "mana yang bisa menambahkan akun mana
    yang tidak"; Content Creator "bisa menambahkan hak kelola akun"): hak ini kini CENTANG "Kelola Akun"
    (`mod.mkt_accounts.create/edit/delete`) di Manajemen Role, bukan daftar peran di kode. Toko ganda tetap ditolak
    `_find_duplicate_store`.
    `action` None = salah satu aksi (untuk tombol di layar).
    """
    from routes.shared import SUPER_ROLES, user_permissions
    if str((user or {}).get("role") or "").lower() in SUPER_ROLES:
        return True
    perms = user_permissions(user or {})
    if "*" in perms:
        return True
    acts = (action,) if action else ("create", "edit", "delete")
    return any(f"mod.mkt_accounts.{a}" in perms for a in acts)


async def _assert_can_manage_stores(request: Request) -> dict:
    user = await require_auth(request)
    from routes.shared import lolos_centang
    if not lolos_centang(user):
        raise HTTPException(403, STORE_MANAGE_DENIED)
    return user


async def _find_duplicate_store(db, platform, username, account_name, exclude_id=None):
    """Toko lain yang SAMA (`scope.store_identity_keys`: platform sama + username ATAU nama
    sama). Satu toko marketplace hanya boleh tercatat sekali — kode toko berbeda tidak
    membuatnya toko lain."""
    keys = scope.store_identity_keys(platform, username, account_name)
    if not keys:
        return None
    rows = await db.marketing_platform_accounts.find(
        {}, {"_id": 0, "id": 1, "account_code": 1, "account_name": 1, "username": 1,
             "platform": 1, "status": 1}).to_list(2000)
    for a in rows:
        if exclude_id and a.get("id") == exclude_id:
            continue
        if keys & scope.store_identity_keys(a.get("platform"), a.get("username"), a.get("account_name")):
            return a
    return None


def _duplicate_message(a: dict) -> str:
    inactive = str(a.get("status") or "").lower() == "inactive"
    return (f"Toko ini sudah tercatat: {a.get('account_code') or '-'} · {a.get('account_name') or '-'} "
            f"(username {a.get('username') or '-'})."
            + (" Toko itu berstatus nonaktif — aktifkan kembali, jangan dibuat baru." if inactive else "")
            + " Satu toko marketplace hanya boleh tercatat sekali supaya omzet, stok, dan jurnalnya "
              "tidak terbelah.")


async def _assert_not_duplicate_on_update(db, account: dict, data) -> None:
    """Mengganti username/nama tidak boleh membuat toko ini sama dengan toko lain.

    Hanya bagian yang BERUBAH yang dicek: form lama mengirim ulang semua field setiap simpan, dan
    toko asli tidak boleh jadi tidak bisa disimpan hanya karena sudah ada toko dobel lama.
    """
    changed_user = (data.username if data.username is not None
                    and scope.norm(data.username) != scope.norm(account.get("username")) else "")
    changed_name = (data.account_name if data.account_name is not None
                    and scope.norm(data.account_name) != scope.norm(account.get("account_name")) else "")
    if not (changed_user or changed_name):
        return
    dup = await _find_duplicate_store(db, account.get("platform"), changed_user, changed_name,
                                      exclude_id=account.get("id"))
    if dup:
        raise HTTPException(400, _duplicate_message(dup))


@router.post("/accounts")
async def create_platform_account(data: PlatformAccountCreate, request: Request):
    """
    Create new platform account — hanya owner/admin/SPV/manager (`can_manage_stores`).
    """
    await _assert_can_manage_stores(request)
    db = get_db()
    
    # Validate platform (2026-11-02: `tiktok` diterima sebagai alias `tiktokshop`)
    if data.platform not in VALID_PLATFORMS:
        raise HTTPException(400, f"Platform harus salah satu dari: {', '.join(VALID_PLATFORMS)}")
    
    # Check duplicate account_code
    existing = await db.marketing_platform_accounts.find_one({"account_code": data.account_code}, {"_id": 0})
    if existing:
        raise HTTPException(400, f"Kode akun '{data.account_code}' sudah dipakai toko "
                                 f"'{existing.get('account_name') or '-'}'. Pakai kode lain.")
    # 2026-11-05 — toko yang sama (platform + username/nama) tidak boleh dibuat dua kali
    dup = await _find_duplicate_store(db, data.platform, data.username, data.account_name)
    if dup:
        raise HTTPException(400, _duplicate_message(dup))
    
    # ── F0.7 — validasi kode COA harus BENAR-BENAR ada di bagan akun ─────────
    # 2026-11-02 (K4) — rekening pencairan TIDAK diisi dari form toko: toko baru selalu
    # mendapat rekening bawaan (`coa_cash_source=default`), lalu Finance menautkannya.
    if (data.coa_cash_code or "").strip():
        raise HTTPException(400, CASH_ONE_DOOR_MSG + " Simpan toko tanpa rekening dulu.")
    coa_fields = {
        "coa_revenue_code": (data.coa_revenue_code or "").strip(),
        "coa_cash_code": "",
        "coa_receivable_code": (data.coa_receivable_code or "").strip(),
    }
    for fname, code in coa_fields.items():
        if code:
            await _validate_coa_role(db, fname, code)
    # Validasi lain DULU (2026-11-02): permintaan yang ditolak tidak boleh sempat
    # membuat akun COA toko yang tidak pernah punya toko.
    basis = data.revenue_basis or _shape.DEFAULT_BASIS
    if basis not in _shape.VALID_BASIS:
        raise HTTPException(400, "Basis omzet harus salah satu dari: "
                                 f"{', '.join(_shape.VALID_BASIS)}")
    pic_user_id, pic_user_name = await _resolve_pic(db, getattr(data, "pic_user_id", None))
    # Tidak boleh ada toko tanpa alamat jurnal.
    # 2026-11-02 (No.10b, D3) — bila akun pendapatan tidak dipilih, toko baru
    # OTOMATIS dibuatkan akun pendapatan SENDIRI di kelompok platformnya
    # (`core.finance_sync.ensure_store_revenue_account`), bukan lagi akun penampung
    # "Lain-lain" yang membuat omzet beberapa toko tercampur di satu akun.
    revenue_source = "input" if coa_fields["coa_revenue_code"] else "auto_store"
    if not coa_fields["coa_revenue_code"]:
        from core.finance_sync import ensure_store_revenue_account
        try:
            res = await ensure_store_revenue_account(db, {
                "account_code": _sanitize(data.account_code, 100),
                "account_name": _sanitize(data.account_name, 200),
                "platform": data.platform})
        except ValueError as e:
            raise HTTPException(400, f"Akun pendapatan toko ini tidak bisa dibuat otomatis ({e}). "
                                     "Minta Finance membuat akun pendapatan toko di Portal "
                                     "Keuangan → COA, lalu pilih akun itu di form.")
        coa_fields["coa_revenue_code"] = res["code"]
    if not coa_fields["coa_cash_code"]:
        coa_fields["coa_cash_code"] = await _default_cash_code(db)
    if not coa_fields["coa_receivable_code"]:
        coa_fields["coa_receivable_code"] = (
            DEFAULT_RECEIVABLE_CODE if await _coa_exists(db, DEFAULT_RECEIVABLE_CODE) else "")

    account = {
        "id": _uid(),
        "account_code": _sanitize(data.account_code, 100),
        "account_name": _sanitize(data.account_name, 200),
        "platform": data.platform,
        "username": _sanitize(data.username or "", 100),
        "status": "active",
        "group": data.group or "other",
        "credentials": {
            "api_key": "",
            "api_secret": "",
            "has_api_integration": data.has_api_integration
        },
        "import_config": {
            "saved_templates": []
        },
        "assigned_staff": [],
        # 2026-11-05 — pembuat toko TIDAK lagi dicatat sebagai PIC (`pic_id`): PIC hanya
        # `pic_user_id` yang dipilih di form; pembuatnya tercatat di `created_by`.
        "health_score": None,  # None = belum ada data (UI tampilkan "N/A")
        # F0.7 — tautan Finance + basis omzet (SSOT §1)
        **coa_fields,
        "platform_warehouse_name": _sanitize(data.platform_warehouse_name or "", 200),
        "platform_shop_id": _sanitize(data.platform_shop_id or "", 100),
        "revenue_basis": basis,
        "sales_input_mode": _input_mode_or_400(data.sales_input_mode),
        # 'input' | 'auto_store' (2026-11-02) | 'fallback_platform' (data lama) — badge di UI
        "coa_revenue_source": revenue_source,
        # 2026-11-02 (K4) — bawaan; layar Finance menampilkan lencana "belum diatur"
        "coa_cash_source": "default" if coa_fields["coa_cash_code"] else None,
        "pic_user_id": pic_user_id,
        "pic_user_name": pic_user_name,
        "created_at": _now(),
        "created_by": getattr(request.state, 'user', {}).get("email", "system"),
        "updated_at": _now()
    }
    
    await db.marketing_platform_accounts.insert_one(account)
    # Phase 6: auto-create COA subledger (Piutang per-channel) — idempotent, non-fatal.
    # 2026-08-07 — DULU `except Exception: pass`. Channel marketing tanpa subledger
    # piutang berarti penjualan channel itu tidak punya akun Buku Besar sendiri.
    try:
        from routes.coa_auto import ensure_subledger_for_entity
        _u = getattr(request.state, 'user', {}) or {}
        await ensure_subledger_for_entity(db, "channel", account, _u)
    except Exception as e:  # noqa: BLE001
        logger.error(
            "[coa] subledger piutang channel GAGAL dibuat untuk %s — penjualan channel "
            "ini tidak punya akun Buku Besar: %s",
            account.get("account_name") or account.get("id"), e)
    
    await log_activity(
        getattr(request.state, 'user', {}).get("id", "system"),
        getattr(request.state, 'user', {}).get("name") or getattr(request.state, 'user', {}).get("email", "system"),
        "create",
        "marketing_account",
        f"Created platform account: {data.account_name} ({data.platform})"
    )
    
    # Baca ulang: `ensure_subledger_for_entity` menulis `ar_account_code` SETELAH insert.
    # Tanpa ini, UI tidak pernah melihat akun COA otomatis yang baru dibuat.
    saved = await db.marketing_platform_accounts.find_one({"id": account["id"]}, {"_id": 0})
    # `coa_receivable_code` (warisan) = akun piutang toko sendiri, sama seperti sinkron startup
    # (`core.finance_sync._sync_stores`). Dulu baru disamakan setelah backend restart.
    if saved and saved.get("ar_account_code") and saved.get("coa_receivable_code") != saved["ar_account_code"]:
        await db.marketing_platform_accounts.update_one(
            {"id": account["id"]}, {"$set": {"coa_receivable_code": saved["ar_account_code"]}})
        saved["coa_receivable_code"] = saved["ar_account_code"]
    return serialize_doc({"message": "Platform account created", "account": saved or account})


@router.get("/accounts")
async def list_platform_accounts(
    request: Request,
    platform: Optional[str] = Query(None, description="Filter by platform"),
    status: Optional[str] = Query(None, description="Filter by status"),
    group: Optional[str] = Query(None, description="Filter by group")
):
    """
    List all platform accounts with optional filters.
    PIC Marketing sees all, Staff sees assigned only.
    """
    await require_auth(request)
    db = get_db()
    
    query = {}
    
    # Build query filters
    if platform:
        # 2026-11-02 (No.10) — filter TikTok menemukan toko `tiktok` MAUPUN `tiktokshop`.
        query["platform"] = ({"$in": list(TIKTOK_ALIASES)} if platform in TIKTOK_ALIASES
                             else platform)
    if status:
        query["status"] = status
    if group:
        query["group"] = group
    
    # F6 (2026-08-13) — VISIBILITAS PER PEMAKAI ditegakkan di sini.
    # Sebelum ini semua peran melihat 9 toko: staf yang memegang 1 toko ikut melihat
    # omzet, biaya, dan target toko rekan kerjanya, dan setiap pemilih toko di layar
    # menampilkan toko yang bukan tanggung jawabnya — tanpa satu pun galat.
    _user = getattr(request.state, 'user', None) or {}
    query = await scope.scope_filter(db, _user, query, field='id')

    accounts = await db.marketing_platform_accounts.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    # 2026-11-08 (keputusan pemilik): skor sehat toko yang basi dihitung ulang dulu (≤ sekali sehari per toko).
    await refresh_stale_health_scores(db, accounts)
    if not accounts and not scope.sees_all_accounts(_user):
        logger.info('[accounts] pemakai %s tanpa toko ter-assign (role=%s)',
                    _user.get('email'), _user.get('role'))
    return serialize_doc(accounts)


class LearnWarehouseBody(BaseModel):
    """Simpan nama gudang platform yang TERBACA dari ekspor Seller Center."""
    warehouse_name: str = Field(min_length=1, max_length=200)
    session_id: Optional[str] = None      # sesi impor asal (jejak)


@router.post("/accounts/{account_id}/learn-warehouse")
async def learn_platform_warehouse(account_id: str, data: LearnWarehouseBody,
                                   request: Request):
    """Isi `platform_warehouse_name` toko dari nama gudang di berkas ekspor.

    KENAPA ini ada
    --------------
    Penjaga toko (F1) hanya bisa menahan "berkas masuk toko yang salah" kalau
    master toko sudah menyimpan nama gudang platformnya. Dari 9 toko, hanya 1 yang
    terisi — dan meminta pemilik mengetik 8 nama dari ingatan berisiko: satu salah
    ketik membuat penjaga menolak berkas yang BENAR (lebih buruk daripada tidak ada
    penjaga, karena staf akan belajar mengabaikannya).

    Karena itu namanya diambil dari **ekspor platform itu sendiri**: saat impor
    pertama sebuah toko, layar menawarkan tombol "Simpan gudang ini ke master toko".

    Pagar yang dipasang:
      * kalau toko ini SUDAH punya nama gudang lain ⇒ **409** (tidak menimpa
        diam-diam; nama gudang adalah kunci penjaga, bukan catatan bebas);
      * kalau nama gudang itu sudah dipakai toko LAIN ⇒ **409** dengan nama toko
        pemiliknya (dua toko bergudang sama = penjaga jadi tidak ada artinya);
      * perubahan dicatat ke jejak aktivitas beserta sesi impor asalnya.
    """
    await require_auth(request)
    user = _get_user(request)
    db = get_db()

    name = (data.warehouse_name or "").strip()
    if not name:
        raise HTTPException(400, "Nama gudang platform kosong")

    acc = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not acc:
        raise HTTPException(404, "Toko tidak ditemukan")

    current = (acc.get("platform_warehouse_name") or "").strip()
    if current and current.casefold() != name.casefold():
        raise HTTPException(409,
            f"Toko '{acc.get('account_name')}' sudah terdaftar dengan gudang platform "
            f"'{current}'. Kalau memang berubah, ubah lewat menu Kelola Akun "
            f"(Edit toko) supaya perubahannya sadar — bukan otomatis dari berkas.")
    if current:
        return serialize_doc({"ok": True, "changed": False,
                              "account_id": account_id,
                              "platform_warehouse_name": current,
                              "message": f"Gudang platform '{current}' sudah tersimpan "
                                         f"untuk toko ini."})

    owner = await db.marketing_platform_accounts.find_one(
        {"id": {"$ne": account_id}, "platform_warehouse_name": name},
        {"_id": 0, "account_name": 1, "account_code": 1})
    if owner:
        raise HTTPException(409,
            f"Gudang platform '{name}' sudah dipakai toko "
            f"'{owner.get('account_name')}' ({owner.get('account_code')}). "
            f"Satu gudang tidak boleh menempel pada dua toko — periksa dulu berkas "
            f"ini memang milik toko mana.")

    await db.marketing_platform_accounts.update_one(
        {"id": account_id},
        {"$set": {"platform_warehouse_name": name,
                  "platform_warehouse_source": "import_file",
                  "platform_warehouse_learned_at": _now(),
                  "platform_warehouse_learned_from_session": data.session_id or "",
                  "updated_at": _now()}})
    await log_activity(
        user.get("id", ""), user.get("name") or user.get("email", "system"),
        "learn_warehouse", "marketing_platform_accounts",
        f"Gudang platform toko '{acc.get('account_name')}' diisi dari berkas impor: "
        f"'{name}' (sesi {data.session_id or '-'})")
    return serialize_doc({
        "ok": True, "changed": True, "account_id": account_id,
        "platform_warehouse_name": name,
        "message": f"Gudang platform '{name}' disimpan ke toko "
                   f"'{acc.get('account_name')}'. Impor berikutnya untuk toko ini "
                   f"otomatis terjaga dari salah pilih toko."})


class ShipSlaBody(BaseModel):
    """Batas kirim per toko (dasar kolom 'lewat batas' di Monitoring Pengiriman)."""
    ship_sla_days: float = Field(ge=0.25, le=60)
    ship_sla_days_preorder: float = Field(ge=0.25, le=120)


@router.put("/accounts/{account_id}/ship-sla")
async def set_ship_sla(account_id: str, data: ShipSlaBody, request: Request):
    """Ubah batas kirim toko (hari) — normal & pre-order.

    Batas ini yang menentukan pesanan mana yang dihitung **lewat batas** di
    Monitoring Pengiriman. Sengaja disimpan di master toko dan bisa diubah dari
    layar: setiap platform (dan setiap kesepakatan pre-order) punya tenggat
    berbeda, dan aturan yang tersembunyi di kode akan melahirkan laporan "merah"
    yang tidak bisa dipertanggungjawabkan ke siapa pun.
    """
    await require_auth(request)
    user = _get_user(request)
    db = get_db()
    acc = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not acc:
        raise HTTPException(404, "Toko tidak ditemukan")
    if data.ship_sla_days_preorder < data.ship_sla_days:
        raise HTTPException(400, "Batas pre-order tidak boleh lebih pendek daripada "
                                 "batas pesanan normal — pre-order justru butuh waktu "
                                 "lebih panjang.")
    await db.marketing_platform_accounts.update_one(
        {"id": account_id},
        {"$set": {"ship_sla_days": float(data.ship_sla_days),
                  "ship_sla_days_preorder": float(data.ship_sla_days_preorder),
                  "ship_sla_updated_at": _now(),
                  "ship_sla_updated_by": user.get("email", "system"),
                  "updated_at": _now()}})
    await log_activity(
        user.get("id", ""), user.get("name") or user.get("email", "system"),
        "set_ship_sla", "marketing_platform_accounts",
        f"Batas kirim toko '{acc.get('account_name')}' diubah menjadi "
        f"{data.ship_sla_days} hari (pre-order {data.ship_sla_days_preorder} hari)")
    return serialize_doc({"ok": True, "account_id": account_id,
                          "ship_sla_days": data.ship_sla_days,
                          "ship_sla_days_preorder": data.ship_sla_days_preorder,
                          "message": f"Batas kirim toko '{acc.get('account_name')}' "
                                     f"disimpan: {data.ship_sla_days} hari normal · "
                                     f"{data.ship_sla_days_preorder} hari pre-order"})


@router.post("/accounts/health/recompute-all")
async def recompute_all_health(request: Request):
    """Hitung ulang skor sehat (skala 1–5) SEMUA toko dari data 30 hari terakhir.

    Dipakai tombol "Hitung Ulang Skor" di layar Manajemen Akun: toko yang datanya
    baru masuk lewat impor langsung punya skor, bukan "Belum ada data" selamanya.
    """
    await require_auth(request)
    db = get_db()
    from routes.marketing_shared import _recalculate_health_score, health_grade_of

    accounts = await db.marketing_platform_accounts.find(
        {}, {"_id": 0, "id": 1, "account_name": 1}).to_list(500)
    scored = 0
    no_data = 0
    rows = []
    for acc in accounts:
        score = await _recalculate_health_score(db, acc["id"])
        grade, label = health_grade_of(score)
        if score is None:
            no_data += 1
        else:
            scored += 1
        rows.append({"account_id": acc["id"], "account_name": acc.get("account_name"),
                     "health_score": score, "health_grade": grade, "health_label": label})
    return serialize_doc({
        "ok": True, "accounts": len(accounts), "scored": scored, "no_data": no_data,
        "results": rows,
        "message": (f"{scored} toko punya skor sehat, {no_data} toko belum punya data "
                    f"30 hari terakhir")})


@router.get("/accounts/coa-options")
async def coa_options(request: Request):
    """F0.7 — daftar akun COA siap-pakai untuk pemilih di layar Manajemen Akun.

    Dikelompokkan sesuai perannya supaya staf tidak perlu menghafal nomor akun:
      · pendapatan  — akun penjualan per toko (`flags.is_sales`, bukan kontra/grup)
      · kas/bank    — rekening penerima pencairan (`flags.is_bank|is_cash`, termasuk ShopeePay)
      · piutang     — akun piutang platform (`flags.is_ar`, default `1-220`)

    Penyaringan memakai `flags` + `is_group` + `active` (BUKAN awalan kode) supaya
    daftar tidak tercemar akun grup, retur/diskon/potongan platform, persediaan,
    pajak, atau akun subledger otomatis.
    """
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_coa_accounts.find(
        {}, {"_id": 0, "code": 1, "name": 1, "type": 1, "flags": 1,
             "is_group": 1, "active": 1, "parent_code": 1}).sort("code", 1).to_list(2000)

    def flag(r, key):
        return bool((r.get("flags") or {}).get(key))

    def opt(r, extra=None):
        o = {"code": r["code"], "name": r.get("name") or r["code"], "type": r.get("type")}
        if extra:
            o.update(extra)
        return o

    usable = [r for r in rows if _usable_coa(r)]

    revenue = [opt(r, {"channel": (r.get("flags") or {}).get("channel") or ""})
               for r in usable
               if r.get("type") == "REVENUE" and flag(r, "is_sales") and not flag(r, "is_contra")]
    from core.payout_banks import bank_options
    cash = await bank_options(db)
    receivable = [opt(r) for r in usable if flag(r, "is_ar") and not flag(r, "subledger")]

    # Fallback pendapatan per platform (akun penampung) — dihitung dari COA nyata.
    fallback = {}
    for plat in PLATFORM_TO_COA_CHANNEL:
        code = await _fallback_revenue_code(db, plat)
        if code:
            fallback[plat] = code

    default_recv = DEFAULT_RECEIVABLE_CODE if any(
        r["code"] == DEFAULT_RECEIVABLE_CODE for r in receivable) else (
        receivable[0]["code"] if receivable else "")

    return serialize_doc({
        "revenue": revenue,
        "cash": cash,
        "receivable": receivable,
        "default_receivable": default_recv,
        "default_cash": await _default_cash_code(db),
        "fallback_revenue_by_platform": fallback,
        "platform_channel_map": PLATFORM_TO_COA_CHANNEL,
        "sales_input_mode_options": _input_mode_options(),
        "revenue_basis_options": [
            {"value": "produk_setelah_diskon",
             "label": "Omzet produk (setelah diskon penjual, sebelum potongan platform)"},
            {"value": "order_amount",
             "label": "Order Amount (yang dibayar pembeli, termasuk ongkir)"},
        ],
    })


def _input_mode_or_400(mode):
    """Q-5 — cara input omzet toko; kosong = belum dipilih (diturunkan dari data)."""
    from core import marketing_input_mode as _mode
    if mode in (None, ""):
        return None
    if not _mode.valid(mode):
        raise HTTPException(400, "Cara input omzet harus 'impor_pesanan' atau 'rekap_manual'.")
    return mode


def _input_mode_options():
    from core import marketing_input_mode as _mode
    return list(_mode.OPTIONS)


@router.get("/accounts/{account_id}")
async def get_platform_account(account_id: str, request: Request):
    """Get platform account detail"""
    await require_auth(request)
    db = get_db()
    
    account = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(404, "Akun toko tidak ditemukan")
    await refresh_stale_health_scores(db, [account])   # skor sehat segar (keputusan 8 Nov 2026)
    return serialize_doc(account)


@router.put("/accounts/{account_id}")
async def update_platform_account(account_id: str, data: PlatformAccountUpdate, request: Request):
    """Update platform account — hanya owner/admin/SPV/manager (`can_manage_stores`)."""
    await _assert_can_manage_stores(request)
    db = get_db()
    
    account = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(404, "Akun toko tidak ditemukan")
    await _assert_not_duplicate_on_update(db, account, data)
    
    # Build update dict
    update_data = {}
    if data.account_name is not None:
        update_data["account_name"] = data.account_name
    if data.username is not None:
        update_data["username"] = data.username
    if data.group is not None:
        update_data["group"] = data.group
    if data.status is not None:
        valid_status = ["active", "inactive", "suspended"]
        if data.status not in valid_status:
            raise HTTPException(400, f"Status harus salah satu dari: {', '.join(valid_status)}")
        update_data["status"] = data.status
    if data.has_api_integration is not None:
        update_data["credentials.has_api_integration"] = data.has_api_integration
    if data.pic_user_id is not None:
        pid, pname = await _resolve_pic(db, data.pic_user_id, current=account.get("pic_user_id"))
        update_data["pic_user_id"] = pid
        update_data["pic_user_name"] = pname

    # ── F0.7 — tautan Finance & basis omzet (divalidasi, bukan diterima mentah) ──
    # 2026-11-02 (K4) — `coa_cash_code` DITOLAK bila mengubah nilai (satu pintu Finance);
    # nilai sama dengan yang tersimpan diabaikan (layar lama yang mengirim ulang semua field).
    if cash_code_change_blocked(account.get("coa_cash_code"), getattr(data, "coa_cash_code", None)):
        raise HTTPException(400, CASH_ONE_DOOR_MSG)
    for fname in ("coa_revenue_code", "coa_receivable_code"):
        val = getattr(data, fname, None)
        if val is not None:
            # 2026-11-04 — nilai yang sama dengan yang tersimpan = tidak berubah. Layar mengirim
            # ulang semua field; tanpa ini mengganti nama toko ikut memvalidasi ulang akun lama
            # dan menandai akun pendapatan otomatis seolah dipilih manual (`input`).
            if (val or "").strip() == (account.get(fname) or "").strip():
                continue
            if val:
                await _validate_coa_role(db, fname, val)
            update_data[fname] = val
            if fname == "coa_revenue_code" and val:
                update_data["coa_revenue_source"] = "input"
    if data.sales_input_mode is not None:
        update_data["sales_input_mode"] = _input_mode_or_400(data.sales_input_mode)
    if data.revenue_basis is not None:
        if data.revenue_basis not in _shape.VALID_BASIS:
            raise HTTPException(400, "Basis omzet harus salah satu dari: "
                                 f"{', '.join(_shape.VALID_BASIS)}")
        update_data["revenue_basis"] = data.revenue_basis
    if data.platform_warehouse_name is not None:
        update_data["platform_warehouse_name"] = _sanitize(data.platform_warehouse_name, 200)
    if data.platform_shop_id is not None:
        update_data["platform_shop_id"] = _sanitize(data.platform_shop_id, 100)
    # BD-5 — owner sudah mengoreksi nama/PIC/rekening toko hasil seed
    if data.needs_owner_review is not None:
        update_data["needs_owner_review"] = bool(data.needs_owner_review)
        if not data.needs_owner_review:
            update_data["owner_reviewed_at"] = _now()
            update_data["owner_reviewed_by"] = (_get_user(request)).get("email", "system")

    update_data["updated_at"] = _now()
    
    await db.marketing_platform_accounts.update_one(
        {"id": account_id},
        {"$set": update_data}
    )
    
    await log_activity(
        (_get_user(request)).get("id", "system"),
        (_get_user(request)).get("name") or (_get_user(request)).get("email", "system"),
        "update",
        "marketing_account",
        f"Updated platform account: {account['account_name']}"
    )
    
    # Get updated account
    updated = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    return serialize_doc({"message": "Platform account updated", "account": updated})


@router.delete("/accounts/{account_id}/permanent")
async def delete_platform_account_permanently(account_id: str, request: Request):
    """HAPUS PERMANEN toko — hanya super admin, hanya toko yang BELUM punya data (owner, 5 Nov 2026).

    "Punya data" memakai aturan yang sama dengan migrasi toko dobel (`core.store_cleanup`). Toko yang
    sudah punya pesanan/katalog/jurnal/… ditolak 409 dengan daftar datanya — pakai Arsipkan.
    Akun Penjualan & Piutang yang dibuat sistem untuk toko itu ikut dibereskan menurut aturan Bagan Akun
    (akun pendapatan toko & piutang sub-ledger buatan sistem: dinonaktifkan, tidak dihapus).
    """
    user = await require_auth(request)
    from routes.shared import lolos_centang
    if not lolos_centang(user):  # 13 Nov 2026: centang Kelola Akun › Hapus (dulu khusus super admin)
        raise HTTPException(403, "Peran Anda belum dicentang \"Kelola Akun › Hapus\" di "
                                 "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses. "
                                 "Gunakan Arsipkan untuk menonaktifkan toko.")
    db = get_db()
    account = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(404, "Akun toko tidak ditemukan")
    from core import store_cleanup
    try:
        res = await store_cleanup.delete_store_permanently(db, account, user)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    await log_activity(user.get("id", "system"), user.get("name") or user.get("email", "system"),
                       "delete", "marketing_account",
                       f"Hapus permanen toko: {account.get('account_code')} · {account.get('account_name')}")
    coa_note = ""
    if res["coa_deleted"]:
        coa_note += f" Akun COA ikut dihapus: {', '.join(res['coa_deleted'])}."
    if res["coa_deactivated"]:
        coa_note += f" Akun COA dinonaktifkan: {', '.join(res['coa_deactivated'])}."
    if res["coa_kept"]:
        coa_note += f" Akun COA dibiarkan karena masih terikat: {', '.join(res['coa_kept'])}."
    return {"ok": True, "message": f"Toko {account.get('account_code')} dihapus permanen.{coa_note}", **res}


@router.delete("/accounts/{account_id}")
async def archive_platform_account(account_id: str, request: Request):
    """
    Archive (soft delete) platform account.
    Sets status to 'inactive' instead of hard delete.
    2026-11-05 — penjaganya sama dengan tambah/ubah toko (`can_manage_stores`).
    """
    await _assert_can_manage_stores(request)
    db = get_db()
    
    account = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(404, "Akun toko tidak ditemukan")
    
    await db.marketing_platform_accounts.update_one(
        {"id": account_id},
        {"$set": {"status": "inactive", "updated_at": _now()}}
    )
    
    await log_activity(
        (_get_user(request)).get("id", "system"),
        (_get_user(request)).get("name") or (_get_user(request)).get("email", "system"),
        "archive",
        "marketing_account",
        f"Archived platform account: {account['account_name']}"
    )
    
    return serialize_doc({"message": "Platform account archived"})


# ══════════════════════════════════════════════════════════════════════════════
# SALES DATA ENTRY (Manual for Phase 1)
# ══════════════════════════════════════════════════════════════════════════════
