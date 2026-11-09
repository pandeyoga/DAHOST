"""
PT Rahaza — Finance Enhancement (Fase 8.5)

Scope (MVP):
  - Cost Centers: CRUD (dipakai tagging expense/HPP)
  - AR Invoices: draft -> sent -> partial_paid -> paid | overdue (manual check)
  - AP Invoices: draft -> sent -> partial_paid -> paid
  - Payments: record payment -> update AR/AP status otomatis
  - Cash Accounts: CRUD rekening kas/bank + saldo via movements ledger
  - Cash Movements: in/out, dilink ke AR payment, AP payment, expense
  - Expenses: entry biaya operasional (manual)
  - Aging Report AR: bucket 0-30, 31-60, 61-90, 90+
"""
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from routes.shared import require_portal_dep
from database import get_db
from utils.counters import gen_prefixed_number
from auth import require_auth, serialize_doc, log_activity
from utils.data_quality import SkipTracker
from pymongo import ReturnDocument
import uuid
import logging
from datetime import datetime, timezone, date
from typing import Optional
from utils.waktu import today_wib

logger = logging.getLogger(__name__)

from core.roles import FINANCE_ROLES  # FIN-02
from core import entities as ent_mod
from core.entities import (DA, SMU, ALL, entity_from_request, explicit_entity, entity_match, entity_of_doc,
                           matches_entity, validate_cash_account_owner, validate_manual_lines)
from routes.rahaza_posting import (
    post_ar_invoice,
    post_ar_payment,
    post_ap_invoice,
    post_ap_payment,
    post_expense,
    void_ar_invoice_posting,
    void_ap_invoice_posting,
    post_cash_opening_balance,
    cash_accounts_with_gl,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rahaza", tags=["rahaza-finance"],
                   dependencies=[Depends(require_portal_dep("finance"))])  # RBAC: portal finance (BUG-RBAC-1)

AR_STATUS = ["draft", "issued", "sent", "partial_paid", "paid", "overdue", "written_off", "cancelled"]
AP_STATUS = ["draft", "sent", "partial_paid", "paid", "overdue", "cancelled"]
AP_DEBIT_TYPES = ("EXPENSE", "COGS", "ASSET", "OTHER_EXPENSE")   # akun yang boleh didebit faktur supplier manual
EXPENSE_DEBIT_TYPES = ("EXPENSE", "COGS", "OTHER_EXPENSE")       # akun beban yang boleh dipilih di Pengeluaran


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _today_iso(): return today_wib().isoformat()


def _to_amount(v):
    """Coerce a payment amount to float; reject non-numeric input with 400 (not 500)."""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "amount harus berupa angka.")


def _to_num(v, field="nilai"):
    """Coerce optional numeric body field to float (default 0); reject non-numeric/NaN/inf → 400."""
    import math
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} harus berupa angka.")
    if math.isnan(f) or math.isinf(f):
        raise HTTPException(400, f"{field} tidak valid (NaN/inf).")
    return f


def _norm_invoice_items(items, unit_default="pcs"):
    """Normalize & validate invoice line items.

    BUG-NUM-2/4 guard: qty & price WAJIB >= 0 (tolak negatif → total korup) dan numerik valid.
    Returns (subtotal, norm_items).
    """
    import math
    subtotal = 0.0
    norm = []
    for idx, it in enumerate(items or []):
        if not isinstance(it, dict):
            raise HTTPException(400, f"item ke-{idx + 1} tidak valid.")
        try:
            qty = float(it.get("qty") or it.get("quantity") or 0)
            price = float(it.get("price") or it.get("unit_price") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, f"qty/price item ke-{idx + 1} harus berupa angka.")
        if math.isnan(qty) or math.isinf(qty) or math.isnan(price) or math.isinf(price):
            raise HTTPException(400, f"qty/price item ke-{idx + 1} tidak valid (NaN/inf).")
        if qty < 0 or price < 0:
            raise HTTPException(400, f"qty/price item ke-{idx + 1} tidak boleh negatif.")
        amount = qty * price
        subtotal += amount
        norm.append({"description": it.get("description") or "", "qty": qty,
                     "unit": it.get("unit") or unit_default, "price": price, "amount": round(amount)})
    return subtotal, norm


def _validate_tax_discount(tax_pct, discount_amount, subtotal):
    """BUG-NUM-2 guard: tax_pct & discount >= 0, dan discount <= subtotal (DPP tak boleh negatif)."""
    if tax_pct < 0:
        raise HTTPException(400, "tax_pct tidak boleh negatif.")
    if discount_amount < 0:
        raise HTTPException(400, "discount_amount tidak boleh negatif.")
    if discount_amount > subtotal + 0.01:
        raise HTTPException(400, "discount_amount melebihi subtotal (DPP tidak boleh negatif).")


def _invoice_totals(subtotal: float, discount_amount: float, profile: dict, *, apply_tax: bool) -> dict:
    """Konvensi tunggal AR: subtotal = bruto item; DPP = subtotal − diskon; total = DPP + PPN.
    Iter 119 (B-01): dulu PPN dihitung dari bruto & total = subtotal + PPN − diskon → jurnal tak seimbang.
    2026-11-03 (saklar PKP): PPN dari SSOT `core.tax_status.output_tax` — non-PKP selalu 0;
    PKP = 12% × DPP nilai lain 11/12 (kode 04)."""
    from core.tax_status import output_tax
    taxable = max(subtotal - discount_amount, 0.0)
    t = output_tax(profile, taxable, apply=apply_tax)
    return {"taxable_base": round(taxable), "tax_amount": t["tax_amount"], "total": round(taxable + t["tax_amount"]), "tax": t}


def ar_payment_guard_and_update(amount: float) -> tuple:
    """2026-11-02 (audit No.49): SATU rumus sisa piutang untuk semua jalur pembayaran AR
    (Keuangan & Penjualan Langsung): terutang = total − nota kredit (`credited_amount`);
    sisa = terutang − dibayar; lunas bila sisa ≤ 0; pembayaran melebihi sisa DITOLAK.
    Dulu nota kredit diabaikan → faktur yang sudah dibayar penuh tetap `partial_paid` dan
    pembayaran ganda diterima (lebih bayar tanpa dokumen).
    Mengembalikan (ekspresi `$expr` penjaga, pipeline update) untuk find_one_and_update."""
    new_paid = {"$add": [{"$ifNull": ["$paid_amount", 0]}, amount]}
    owed = {"$subtract": [{"$ifNull": ["$total", 0]}, {"$ifNull": ["$credited_amount", 0]}]}
    guard = {"$lte": [new_paid, {"$add": [owed, 0.01]}]}
    pipeline = [
        {"$set": {
            "paid_amount": {"$round": [new_paid, 0]},
            "balance": {"$max": [0, {"$round": [{"$subtract": [owed, new_paid]}, 0]}]},
            "status": {"$cond": [{"$gte": [new_paid, {"$subtract": [owed, 0.01]}]}, "paid", "partial_paid"]},
            "updated_at": _now(),
        }},
        # cermin kanonik (H-01)
        {"$set": {"total_amount": {"$ifNull": ["$total", 0]}, "amount_paid": "$paid_amount", "amount_due": "$balance"}},
    ]
    return guard, pipeline


def ar_remaining(inv: dict) -> float:
    """Sisa tagihan menurut rumus yang sama (untuk pesan galat)."""
    return max(0.0, float(inv.get("total") or 0) - float(inv.get("credited_amount") or 0)
               - float(inv.get("paid_amount") or 0))


async def _record_payment_doc(db, coll: str, inv: dict, amount: float, account_id, movement_id, payment_date, notes, user):
    """Iter 119 (B-02): setiap pembayaran AR/AP punya ID unik sendiri → jurnal tidak pernah 'termakan' idempotensi
    walau nilai & tanggal sama dan tanpa rekening kas. Dokumen ini juga jadi riwayat pembayaran per invoice."""
    pay_id = _uid()
    await db[coll].insert_one({
        "id": pay_id, "invoice_id": inv.get("id"), "invoice_number": inv.get("invoice_number"),
        "amount": round(amount), "date": payment_date, "account_id": account_id or None,
        "movement_id": movement_id, "notes": notes or "",
        "created_at": _now(), "created_by": user["id"], "created_by_name": user.get("name", ""),
    })
    return pay_id


async def _check_debit_account(db, code: str, allowed_types: tuple, doc_label: str, allowed_label: str):
    """Akun debit pilihan pengguna harus ada, aktif, bukan header, dan bertipe yang diizinkan."""
    acc = await db.rahaza_coa_accounts.find_one({"code": code, "active": True}, {"_id": 0, "is_group": 1, "type": 1})
    if not acc:
        raise HTTPException(400, f"Akun '{code}' tidak ditemukan atau non-aktif.")
    if acc.get("is_group"):
        raise HTTPException(400, f"Akun '{code}' adalah header (non-postable). Pilih akun leaf.")
    if acc.get("type") not in allowed_types:
        raise HTTPException(400, f"Akun '{code}' bertipe {acc.get('type')} — {doc_label} hanya boleh "
                                 f"mendebit {allowed_label}.")


async def _validate_mapping_for_entity(db, event: str, roles: tuple, ent: str, what: str, extra: tuple = ()):
    """Tahap 8: dokumen MANUAL (faktur, pengeluaran) ditolak bila akun yang akan dijurnal tidak berlaku
    untuk CV-nya. Akun diambil dari Profil Posting (+ akun pilihan pengguna di `extra`)."""
    from routes.rahaza_posting_profiles import get_mapping
    mapping = await get_mapping(db, event) or {}
    codes = [c for c in [*(mapping.get(r) for r in roles), *extra] if c]
    if codes:
        await validate_manual_lines(db, [{"account_code": c} for c in codes], ent, what=what)


async def _reject_unknown_cash_account(db, account_id):
    """Pembayaran hutang/piutang: `account_id` yang dikirim harus rekening kas/bank yang ada & aktif.

    2026-11-03 (uji tugas): dulu rekening yang tidak ada/nonaktif diam-diam diabaikan — saldo faktur
    tetap berubah, mutasi kas tidak dibuat, dan jurnal jatuh ke rekening bawaan profil posting.
    Kosong tetap boleh (pemanggil API lama) dan memakai rekening bawaan seperti sebelumnya."""
    if account_id and not await db.rahaza_cash_accounts.find_one(
            {"id": account_id, "active": {"$ne": False}}, {"_id": 0, "id": 1}):
        raise HTTPException(400, "Rekening kas/bank tidak ditemukan atau nonaktif. Pilih rekening dari daftar.")


async def _require_fin(request: Request):
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in FINANCE_ROLES:  # FIN-02
        return user
    perms = user.get("_permissions") or []
    if "*" in perms or "finance.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh permission finance.")


async def _gen_number(db, coll, prefix, requested: str = ""):
    """Nomor dokumen keuangan.

    FASE G (sesi #18): untuk jenis dokumen yang KEBIJAKANNYA sudah ditegakkan
    (`policy_enforced` di `data/doc_number_registry.py`) nomor lewat SATU pintu
    `core.doc_number_policy.issue_number` supaya mode OTOMATIS/MANUAL yang disetel
    System Admin benar-benar berlaku. Jenis lain tetap seperti sebelumnya —
    lebih baik jujur "belum ditegakkan" daripada menegakkan separuh jalan.
    """
    _POLICY_KEYS = {"rahaza_ar_invoices": "rahaza_ar_invoices.invoice_number"}
    key = _POLICY_KEYS.get(coll)
    if key:
        from core.doc_number_policy import issue_number
        return await issue_number(db, key, requested=(requested or "").strip())
    today = today_wib().strftime("%Y%m%d")
    p = f"{prefix}-{today}-"
    # RC-5 fix: atomic race-safe numbering (was count_documents()+1)
    field = "invoice_number" if "invoice" in coll else "number"
    return await gen_prefixed_number(db, coll, field, p, 3)


# ── COST CENTERS ─────────────────────────────────────────────────────────────

@router.get("/cost-centers")
async def list_cost_centers(request: Request, active_only: bool = True):
    await require_auth(request)
    db = get_db()
    q = {"active": True} if active_only else {}
    rows = await db.rahaza_cost_centers.find(q, {"_id": 0}).sort("code", 1).to_list(500)
    return serialize_doc(rows)


@router.post("/cost-centers")
async def create_cost_center(request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code & name wajib.")
    if await db.rahaza_cost_centers.find_one({"code": code, "active": True}):
        raise HTTPException(409, f"Kode '{code}' sudah dipakai.")
    from core.reference_dedup import assert_unique_ref  # 2026-11-06 (pola P8)
    await assert_unique_ref(db, "rahaza_cost_centers", name=name, label="Pusat biaya")
    doc = {
        "id": _uid(), "code": code, "name": name,
        "category": body.get("category") or "umum",
        "overhead_rate_per_pcs": float(body.get("overhead_rate_per_pcs") or 0),
        "notes": body.get("notes") or "",
        "active": True,
        "created_at": _now(), "updated_at": _now(),
        "created_by": user["id"], "created_by_name": user.get("name", ""),
    }
    await db.rahaza_cost_centers.insert_one(doc)
    return serialize_doc(doc)


@router.put("/cost-centers/{cid}")
async def update_cost_center(cid: str, request: Request):
    await _require_fin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body["updated_at"] = _now()
    res = await db.rahaza_cost_centers.update_one({"id": cid}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "Cost center tidak ditemukan.")
    out = await db.rahaza_cost_centers.find_one({"id": cid}, {"_id": 0})
    return serialize_doc(out)


async def cost_center_usage(db, cid: str) -> dict:
    """Di mana pusat biaya dipakai (label → jumlah). 10 Nov 2026 — hapus permanen master."""
    from core.hapus_master import hitung_pemakaian
    return await hitung_pemakaian(db, [
        ("baris jurnal", "rahaza_journal_lines", {"cost_center_id": cid}),
        ("jurnal", "rahaza_journal_entries", {"lines.cost_center_id": cid}),
        ("pengeluaran", "rahaza_expenses", {"cost_center_id": cid}),
        ("faktur pemasok", "rahaza_ap_invoices", {"cost_center_id": cid}),
        ("klaim biaya", "rahaza_expense_claims", {"cost_center_id": cid}),
        ("anggaran", "rahaza_budgets", {"cost_center_id": cid}),
        ("baris anggaran", "rahaza_budget_items", {"cost_center_id": cid}),
    ])


@router.delete("/cost-centers/{cid}")
async def delete_cost_center(cid: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026, owner "master data bisa dihapus"):
    hapus permanen bila belum dipakai jurnal, pengeluaran, faktur, klaim, atau anggaran; selain itu 409 dan layar
    menawarkan Nonaktifkan."""
    user = await _require_fin(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        cc = await db.rahaza_cost_centers.find_one({"id": cid}, {"_id": 0})
        if not cc:
            raise HTTPException(404, "Pusat biaya tidak ditemukan.")
        tolak_bila_dipakai("Pusat biaya", cc.get("name") or cc.get("code") or "", await cost_center_usage(db, cid))
        await db.rahaza_cost_centers.delete_one({"id": cid})
        await log_activity(user.get("id") or "", user.get("name") or "", "delete", "rahaza.cost_center", cc.get("code") or cid)
        return {"status": "deleted", "deleted": True}
    res = await db.rahaza_cost_centers.update_one({"id": cid, "active": True}, {"$set": {"active": False, "updated_at": _now()}})
    if res.matched_count == 0:
        raise HTTPException(404, "Cost center tidak ditemukan.")
    return {"status": "deleted"}


# ── AR INVOICES ──────────────────────────────────────────────────────────────
@router.get("/ar-invoices")
async def list_ar(request: Request, status: Optional[str] = None, customer_id: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    ent = entity_from_request(request, allow_all=True)   # Tahap 8
    q = {}
    if status:
        q["status"] = status
    if customer_id:
        q["customer_id"] = customer_id
    rows = await db.rahaza_ar_invoices.find(q, {"_id": 0}).sort("issue_date", -1).to_list(2000)
    rows = [r for r in rows if matches_entity(entity_of_doc(r), ent)][:500]
    for r in rows:
        r["entity"] = entity_of_doc(r)
    # enrich customer
    cids = list({r.get("customer_id") for r in rows if r.get("customer_id")})
    cs = await db.rahaza_customers.find({"id": {"$in": cids}}, {"_id": 0}).to_list(500) if cids else []
    cmap = {c["id"]: c for c in cs}
    for r in rows:
        c = cmap.get(r.get("customer_id")) or {}
        # 2026-11-06 (Tahap 2): piutang maklon memakai klien maklon (bukan master pelanggan) — nama
        # yang tersimpan di dokumen dipertahankan (dulu jadi kosong).
        r["customer_name"] = c.get("name") or r.get("customer_name")
    return serialize_doc(rows)


# 2026-11-06 (Tahap 2): piutang maklon TERJADWAL (`schedule_mode='v2'`) — pendapatan dibukukan otomatis
# per kiriman ke klien (core.maklon_ledger), jadi tidak ada "terbitkan/posting" manual di sini.
MAKLON_SCHEDULE_MSG = ("Piutang maklon terjadwal: pendapatan dicatat otomatis setiap barang dikirim ke klien — "
                       "tidak perlu diterbitkan atau diposting manual.")


def _is_maklon_schedule(inv: dict) -> bool:
    return (inv or {}).get("schedule_mode") == "v2"


# 2026-11-02 (D2, butir 15): pendapatan toko marketplace hanya masuk buku lewat PENCAIRAN
# (marketing_settlements). Invoice AR manual ber-channel toko e-commerce menggandakan pendapatan
# & piutang platform → ditolak. Penjualan non-marketplace (Portal Penjualan, AR biasa) tetap jalan.
MARKETPLACE_PLATFORMS = {"shopee", "tiktok", "tiktokshop", "tokopedia", "lazada", "blibli"}


def marketplace_channel_reason(channel: str, mapping: Optional[dict], store: Optional[dict]) -> Optional[str]:
    """Murni: alasan bila `channel` = toko/channel marketplace; None bila bukan."""
    ch = (channel or "").strip()
    if not ch:
        return None
    if store and (store.get("platform") or "").lower() in MARKETPLACE_PLATFORMS:
        return f"toko {store.get('platform')} '{store.get('account_name') or ch}'"
    m = mapping or {}
    if (m.get("platform") or "").lower() in MARKETPLACE_PLATFORMS:
        return f"channel {m.get('platform')} '{m.get('channel_label') or ch}'"
    if str(m.get("debit_ar") or "").startswith("1-1303"):
        return f"channel '{m.get('channel_label') or ch}' (piutang platform online shop)"
    head = ch.lower().replace("-", "_").split("_")[0]
    if head in MARKETPLACE_PLATFORMS:
        return f"channel '{ch}'"
    return None


async def _marketplace_channel_reason(db, channel: str) -> Optional[str]:
    ch = (channel or "").strip()
    if not ch:
        return None
    mapping = await db.rahaza_channel_gl_mapping.find_one({"channel_key": ch}, {"_id": 0})
    store = await db.marketing_platform_accounts.find_one(
        {"$or": [{"account_code": ch}, {"id": ch}]}, {"_id": 0, "platform": 1, "account_name": 1})
    return marketplace_channel_reason(ch, mapping, store)


async def _reject_marketplace_ar(db, inv: dict):
    _mp = await _marketplace_channel_reason(db, inv.get("sales_channel") or "")
    if _mp:
        raise HTTPException(400, f"Invoice AR tidak boleh memakai {_mp}. Pendapatan marketplace hanya dicatat "
                                 f"lewat pencairan (Portal Keuangan → Saldo & Pencairan Marketplace).")


# Tahap 8 fase 2: dokumen antar CV lahir & dijurnal otomatis dari sumbernya (tagihan CMT tim Sukma, nota aksesoris).
IC_DOC_MSG = ("Dokumen antar CV dibuat dan dijurnal otomatis dari tagihan CMT / nota aksesoris — statusnya "
              "tidak diubah di sini. Pembayarannya dicatat seperti biasa (pasangan di CV lain otomatis).")


@router.post("/ar-invoices")
async def create_ar(request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    customer_id = body.get("customer_id")
    if not customer_id:
        raise HTTPException(400, "customer_id wajib.")
    customer = await db.rahaza_customers.find_one({"id": customer_id}, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer tidak ditemukan.")
    await _reject_marketplace_ar(db, {"sales_channel": body.get("sales_channel")})  # 2026-11-02 (D2)
    ent = entity_from_request(request, body)   # Tahap 8: CV faktur (Gabungan ditolak)
    if ent != DA and (body.get("sales_channel") or "").strip():
        raise HTTPException(400, "Faktur ber-channel toko hanya untuk CV Dewi Aditya (semua toko milik DA).")
    await _validate_mapping_for_entity(db, "ar_invoice", ("debit_ar", "credit_revenue"), ent, "Faktur penjualan")
    items = body.get("items") or []
    subtotal, norm_items = _norm_invoice_items(items, unit_default="pcs")
    from core.tax_status import faktur_fields, get_tax_profile, wants_output_tax
    tax_profile = await get_tax_profile(db, ent)   # Tahap 8: status pajak CV faktur
    apply_tax = wants_output_tax(tax_profile, body.get("tax_pct"), body.get("kena_ppn"))
    discount_amount = round(_to_num(body.get("discount_amount"), "discount_amount"))  # Phase 9C
    _validate_tax_discount(0, discount_amount, subtotal)
    tot = _invoice_totals(subtotal, discount_amount, tax_profile, apply_tax=apply_tax)
    tax = tot["tax_amount"]
    total = tot["total"]
    tax_pct = tot["tax"]["tax_pct"]
    invoice_number = await _gen_number(db, "rahaza_ar_invoices", "AR",
                                       requested=(body.get("invoice_number") or ""))
    doc = {
        "id": _uid(), "invoice_number": invoice_number,
        "customer_id": customer_id,
        "order_id": body.get("order_id") or None,
        "issue_date": body.get("issue_date") or _today_iso(),
        "due_date": body.get("due_date") or _today_iso(),
        "items": norm_items, "subtotal": round(subtotal), "tax_pct": tax_pct, "tax_amount": tax,
        "discount_amount": discount_amount,  # Phase 9C
        "taxable_base": tot["taxable_base"],
        "kena_ppn": tot["tax"]["kena_ppn"], "ppn_rate": tot["tax"]["ppn_rate"],
        "dpp_nilai_lain": tot["tax"]["dpp_nilai_lain"], "kode_transaksi": tot["tax"]["kode_transaksi"],
        **(faktur_fields(body) if tot["tax"]["kena_ppn"] else {"faktur_number": "", "faktur_date": ""}),
        "total": total, "paid_amount": 0, "balance": total,
        "total_amount": total, "amount_paid": 0, "amount_due": total,  # skema kanonik (H-01)
        "status": "draft", "notes": body.get("notes") or "",
        "sales_channel": (body.get("sales_channel") or "").strip() or None,
        "entity": ent,
        "created_at": _now(), "updated_at": _now(),
        "created_by": user["id"], "created_by_name": user.get("name", ""),
    }
    await db.rahaza_ar_invoices.insert_one(doc)
    return serialize_doc(doc)


@router.post("/ar-invoices/{iid}/status")
async def change_ar_status(iid: str, request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    new_status = (body.get("status") or "").lower()
    if new_status not in AR_STATUS:
        raise HTTPException(400, f"status invalid: {AR_STATUS}")
    inv = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    if _is_maklon_schedule(inv):
        raise HTTPException(400, MAKLON_SCHEDULE_MSG)
    if inv.get("intercompany"):
        raise HTTPException(400, IC_DOC_MSG)   # Tahap 8 fase 2
    old_status = inv.get("status")
    if new_status == "sent":
        new_status = "issued"   # kanonik (H-01)
    if new_status == "issued" and old_status not in ("issued", "sent"):
        await _reject_marketplace_ar(db, inv)  # 2026-11-02 (D2): draft lama ber-channel marketplace
    # 2026-11-06 (pola P9): status lama di filter — dulu "batal" bisa menimpa faktur yang baru saja
    # menerima pembayaran (pembayaran atomik mengubah status ke partial_paid/paid).
    _res = await db.rahaza_ar_invoices.update_one({"id": iid, "status": old_status},
                                                  {"$set": {"status": new_status, "updated_at": _now()}})
    if not _res.matched_count:
        raise HTTPException(409, "Faktur ini baru saja diubah pengguna lain (mis. pembayaran tercatat) — muat ulang lalu ulangi.")
    out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})

    # ── F2 Auto-post hook ────────────────────────────────────────────────────
    posting_result = None
    try:
        if new_status == "issued" and old_status not in ("issued", "sent") and not out.get("gl_je_id"):
            posting_result = await post_ar_invoice(db, out, user)
        elif new_status == "cancelled" and out.get("gl_je_id"):
            posting_result = await void_ar_invoice_posting(db, iid, user, reason="AR cancelled")
    except Exception as e:
        log.exception("AR auto-post failed")
        posting_result = {"ok": False, "error": str(e)}

    # refresh after posting (posting may have updated gl_* fields)
    out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    if posting_result is not None:
        out["_posting_result"] = posting_result
    return serialize_doc(out)


@router.post("/ar-invoices/{iid}/send")
async def send_ar_invoice(iid: str, request: Request):
    """F2: explicit 'send' action → status=sent + auto-post JE."""
    user = await _require_fin(request)
    db = get_db()
    inv = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    if _is_maklon_schedule(inv):
        raise HTTPException(400, MAKLON_SCHEDULE_MSG)
    if inv.get("status") not in ("draft", "sent", "issued"):
        raise HTTPException(400, f"Hanya draft/issued yang bisa di-send. Status: {inv.get('status')}")
    if inv.get("status") == "draft":
        await _reject_marketplace_ar(db, inv)  # 2026-11-02 (D2)
    # 2026-11-06 (pola P9): status lama di filter — "kirim" ulang tidak menimpa status pembayaran yang baru masuk.
    _res = await db.rahaza_ar_invoices.update_one({"id": iid, "status": inv.get("status")},
                                                  {"$set": {"status": "issued", "updated_at": _now()}})
    if not _res.matched_count:
        raise HTTPException(409, "Faktur ini baru saja diubah pengguna lain (mis. pembayaran tercatat) — muat ulang lalu ulangi.")
    out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    posting_result = None
    try:
        posting_result = await post_ar_invoice(db, out, user)
    except Exception as e:
        log.exception("AR send auto-post failed")
        posting_result = {"ok": False, "error": str(e)}
    out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = posting_result
    return serialize_doc(out)


@router.post("/ar-invoices/{iid}/post-to-gl")
async def retry_post_ar(iid: str, request: Request):
    """F2: manual retry posting AR invoice to GL (idempotent)."""
    user = await _require_fin(request)
    db = get_db()
    inv = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    if _is_maklon_schedule(inv):
        raise HTTPException(400, MAKLON_SCHEDULE_MSG)
    result = await post_ar_invoice(db, inv, user)
    out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = result
    return serialize_doc(out)


@router.post("/ar-invoices/{iid}/payment")
async def record_ar_payment(iid: str, request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    amount = _to_amount(body.get("amount"))
    if amount <= 0:
        raise HTTPException(400, "amount harus > 0")
    inv = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    account_id = body.get("account_id")
    await _reject_unknown_cash_account(db, account_id)  # sebelum piutang berkurang
    await validate_cash_account_owner(db, account_id, entity_of_doc(inv), what="Pembayaran piutang")  # Tahap 8
    # Tahap 8 fase 2: piutang ANTAR CV (tagihan jasa jahit / nota aksesoris) — pembayaran di buku CV lain
    # (tagihan CMT / hutang pemasok) dibuat otomatis, nilai sama, dua buku sekaligus.
    ic_out = await _settle_intercompany(db, "ar", inv, amount, account_id, body, user)
    if ic_out is not None:
        return ic_out
    if _is_maklon_schedule(inv):
        # 2026-11-06 (Tahap 2): pembayaran klien maklon — tutup piutang yang sudah jatuh, sisanya uang
        # muka (otomatis dipakai saat barang dikirim). Satu mesin dengan layar Piutang klien maklon.
        from core import maklon_ledger
        try:
            pay = await maklon_ledger.record_client_payment(
                db, iid, amount=amount, cash_account_id=account_id, payment_date=body.get("date"),
                notes=body.get("notes") or "", user=user)
        except ValueError as e:
            raise HTTPException(400, str(e))
        out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
        out["_posting_result"] = {"ok": True, "je_number": pay.get("gl_je_number")}
        out["_payment_id"] = pay["id"]
        return serialize_doc(out)
    # ── R10 concurrency hardening (TOCTOU-safe): state-check + overpay guard live
    # INSIDE the filter; paid/balance/status recomputed atomically via aggregation
    # pipeline. Prevents lost-update & overpay under parallel requests (CC3).
    _guard, _pipeline = ar_payment_guard_and_update(amount)  # 2026-11-02: nota kredit ikut dihitung
    updated = await db.rahaza_ar_invoices.find_one_and_update(
        {"id": iid, "status": {"$nin": ["cancelled", "void", "written_off"]}, "$expr": _guard},
        _pipeline,
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        # No write happened — re-read to return the precise 404/400 reason.
        inv2 = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
        if not inv2:
            raise HTTPException(404, "Invoice tidak ditemukan.")
        _st = (inv2.get("status") or "").lower()
        if _st in ("cancelled", "void", "written_off"):
            raise HTTPException(400, f"Tidak bisa mencatat pembayaran untuk invoice berstatus '{_st}'.")
        raise HTTPException(400, f"Pembayaran melebihi sisa tagihan (sisa setelah nota kredit: "
                                 f"{ar_remaining(inv2):.0f})")
    inv = updated
    # Record cash movement
    payment_date = body.get("date") or _today_iso()
    movement_id = None
    if account_id:
        acc = await db.rahaza_cash_accounts.find_one({"id": account_id}, {"_id": 0})
        if acc:
            movement_id = _uid()
            await db.rahaza_cash_movements.insert_one({
                "id": movement_id, "account_id": account_id, "account_name": acc.get("name"),
                "direction": "in", "amount": round(amount),
                "category": "ar_payment", "ref_id": iid, "ref_label": inv.get("invoice_number"),
                "date": payment_date, "notes": body.get("notes") or "",
                "timestamp": _now(), "created_by": user["id"], "created_by_name": user.get("name", ""),
            })
    payment_id = await _record_payment_doc(db, "rahaza_ar_payments", inv, amount, account_id, movement_id,
                                           payment_date, body.get("notes"), user)

    # ── F2 Auto-post: ensure AR invoice posted first (if not), then post payment receipt
    posting_result = None
    try:
        inv_refresh = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
        if not inv_refresh.get("gl_je_id"):
            await post_ar_invoice(db, inv_refresh, user)
            inv_refresh = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
        posting_result = await post_ar_payment(
            db, inv_refresh, amount, account_id, payment_date, user, movement_id=movement_id or payment_id
        )
    except Exception as e:
        log.exception("AR payment auto-post failed")
        posting_result = {"ok": False, "error": str(e)}
    await db.rahaza_ar_payments.update_one({"id": payment_id}, {"$set": {
        "gl_je_id": (posting_result or {}).get("je_id"), "gl_je_number": (posting_result or {}).get("je_number"),
        "post_error": None if (posting_result or {}).get("ok") else (posting_result or {}).get("error")}})

    out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = posting_result
    out["_movement_id"] = movement_id
    out["_payment_id"] = payment_id
    return serialize_doc(out)


async def _settle_intercompany(db, kind: str, inv: dict, amount: float, account_id, body: dict, user: dict):
    """Tahap 8 fase 2: dokumen berlabel antar CV dibayar lewat `core.intercompany.settle` (sisi ini + pasangan di
    buku CV lain, atomik). None = bukan dokumen antar CV (alur biasa berjalan)."""
    from core import intercompany as ic
    if not inv.get("intercompany") or not await ic.is_ic_payable(db, kind, inv):
        return None
    try:
        res = await ic.settle(db, kind=kind, doc=inv, amount=amount, cash_account_id=account_id,
                              counter_cash_account_id=body.get("counter_cash_account_id"), pay_date=body.get("date"),
                              user=user, notes=body.get("notes") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    coll = "rahaza_ar_invoices" if kind == "ar" else "rahaza_ap_invoices"
    out = await db[coll].find_one({"id": inv["id"]}, {"_id": 0})
    out["_posting_result"] = {"ok": True, "je_number": res["origin"]["je_number"]}
    out["_movement_id"] = res["origin"]["movement_id"]
    out["_payment_id"] = res["origin"]["payment_id"]
    out["_intercompany"] = res
    return serialize_doc(out)


async def _enrich_payments(db, rows: list) -> list:
    """Riwayat pembayaran per invoice: tambahkan nama rekening kas untuk layar AR/AP."""
    acc_ids = list({r.get("account_id") for r in rows if r.get("account_id")})
    accs = {a["id"]: a for a in await db.rahaza_cash_accounts.find({"id": {"$in": acc_ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(200)} if acc_ids else {}
    for r in rows:
        a = accs.get(r.get("account_id")) or {}
        r["account_code"] = a.get("code")
        r["account_name"] = a.get("name") or ("—" if not r.get("account_id") else None)
    return rows


@router.get("/ar-invoices/{iid}/payments")
async def list_ar_payments(iid: str, request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_ar_payments.find({"invoice_id": iid}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return serialize_doc(await _enrich_payments(db, rows))


# 2026-08-07 — DI SINI DULU ADA DEKORATOR MENGGANTUNG: `@router.get("/ar-aging")`
# berdiri sendiri tanpa fungsi di bawahnya. Python MENUMPUK dekorator yang
# terpisah baris kosong/komentar, jadi dekorator itu menempel ke
# `write_off_bad_debt` di bawah. Akibatnya DUA hal serius:
#   1. `GET /api/rahaza/ar-aging` sebenarnya memanggil **write-off piutang macet**
#      — sebuah operasi yang MEMPOSTING JURNAL GL (Dr Beban Piutang Macet /
#      Cr Piutang) lewat metode GET; dan karena path `/ar-aging` tak punya
#      `{iid}`, FastAPI menjadikan `iid` sebagai query parameter wajib (itulah
#      sebabnya endpoint ini "minta iid" dan tampak rusak).
#   2. Fungsi `ar_aging()` yang sesungguhnya TIDAK PERNAH terdaftar ⇒ laporan
#      aging AR adalah KODE MATI selama ini.
# Dekoratornya sekarang dipindahkan ke fungsi `ar_aging()` yang benar (lihat di
# bawah). Gate `verify_unreachable_code` tidak menangkap pola ini — dekorator
# menggantung yang dipisahkan baris kosong + komentar adalah titik butanya.


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 9A: BAD DEBT WRITE-OFF
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/ar-invoices/{iid}/write-off-bad-debt")
async def write_off_bad_debt(iid: str, request: Request):
    """
    Phase 9A: Write off AR invoice as bad debt.
    
    Requirements:
    - Invoice status must be 'overdue' or 'sent'
    - Auto-post GL: Dr. Bad Debt Expense (6-2600) / Cr. AR (1-1301)
    - Update invoice status to 'written_off'
    - Record balance at write-off date
    
    Body:
    {
        "reason": "Customer bangkrut / tidak tertagih > 180 hari",
        "write_off_date": "2026-06-01"  // Optional, default: today
    }
    """
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    
    inv = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan")
    
    current_status = inv.get("status")
    if current_status in ("written_off", "cancelled", "paid", "draft", "void"):  # FIN-20c: draft belum pernah mendebit piutang
        raise HTTPException(400, f"Invoice dengan status '{current_status}' tidak bisa di-write off")
    
    balance = float(inv.get("balance") or 0)
    if balance <= 0:
        raise HTTPException(400, "Invoice sudah lunas, tidak bisa di-write off")
    
    write_off_date = body.get("write_off_date") or _today_iso()
    reason = body.get("reason", "").strip()
    
    if not reason:
        raise HTTPException(400, "Reason wajib diisi untuk audit trail")
    
    # Update invoice status
    await db.rahaza_ar_invoices.update_one(
        {"id": iid},
        {"$set": {
            "status": "written_off",
            "write_off_date": write_off_date,
            "write_off_reason": reason,
            "write_off_amount": round(balance, 2),
            "amount_due": 0, "balance": 0,
            "write_off_by": user.get("id"),
            "write_off_by_name": user.get("name", ""),
            "write_off_at": _now(),
            "updated_at": _now(),
        }}
    )
    
    # Auto-post bad debt expense
    posting_result = None
    try:
        from routes.rahaza_posting import post_bad_debt_writeoff
        inv_refresh = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
        posting_result = await post_bad_debt_writeoff(db, inv_refresh, user)
    except Exception as e:
        log.exception("Bad debt write-off GL posting failed")
        posting_result = {"ok": False, "error": str(e)}
    
    # Get final state
    out = await db.rahaza_ar_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = posting_result
    
    from auth import log_activity
    await log_activity(
        user.get("id", "system"),
        user.get("name", "system"),
        "write_off_bad_debt",
        "ar_invoices",
        f"Write-off bad debt: {inv.get('invoice_number')} - Rp {balance:,.0f} - Reason: {reason}"
    )
    
    return serialize_doc(out)


@router.get("/ar-invoices/overdue-report")
async def get_overdue_ar_report(request: Request, days: int = 30):
    """
    Phase 9A: Get overdue AR invoices untuk bad debt review.
    
    Query params:
    - days: minimum overdue days (default: 30)
    
    Returns: List of overdue invoices sorted by overdue days (oldest first)
    """
    await _require_fin(request)
    db = get_db()
    
    today = today_wib()
    
    # Get all sent/overdue/partial_paid invoices with balance > 0
    query = {
        "status": {"$in": ["sent", "issued", "overdue", "partial_paid"]},
        "balance": {"$gt": 0}
    }
    
    invoices = await db.rahaza_ar_invoices.find(query, {"_id": 0}).to_list(1000)
    
    # 2026-08-07 — DULU invoice yang `due_date`-nya kosong/rusak di-`continue`
    # DIAM-DIAM. Akibatnya invoice itu HILANG dari daftar jatuh tempo: tidak ada
    # yang menagih, dan `total_overdue_amount` tetap tampak wajar sehingga tak ada
    # yang curiga. Sekarang setiap baris yang dilewati dicatat + dikembalikan ke
    # layar lewat `data_quality` supaya bisa diperbaiki.
    dq = SkipTracker("daftar AR jatuh tempo")
    overdue_list = []
    for inv in invoices:
        due_date_str = inv.get("due_date")
        if not due_date_str:
            dq.skip(doc_id=inv.get("id"), label=inv.get("invoice_number"),
                    field="due_date", value=due_date_str,
                    reason="tanggal jatuh tempo kosong")
            continue
        
        try:
            due_date = date.fromisoformat(due_date_str[:10])
            overdue_days = (today - due_date).days

            # 8 Nov 2026 (keputusan owner): lewat jatuh tempo = jatuh tempo SEBELUM hari ini (WIB), jadi
            # terlambat minimal 1 hari — juga untuk ?days=0. Dulu faktur yang jatuh tempo HARI INI ikut terhitung.
            if overdue_days >= max(int(days or 0), 1):
                overdue_list.append({
                    "id": inv.get("id"),
                    "invoice_number": inv.get("invoice_number"),
                    "customer_id": inv.get("customer_id"),
                    "issue_date": inv.get("issue_date"),
                    "due_date": due_date_str,
                    "overdue_days": overdue_days,
                    "total": inv.get("total"),
                    "paid_amount": inv.get("paid_amount"),
                    "balance": inv.get("balance"),
                    "status": inv.get("status"),
                    "aging_bucket": (
                        "0-30 days" if overdue_days <= 30 else
                        "31-60 days" if overdue_days <= 60 else
                        "61-90 days" if overdue_days <= 90 else
                        "91-180 days" if overdue_days <= 180 else
                        ">180 days (bad debt candidate)"
                    )
                })
        except (ValueError, TypeError) as e:
            dq.skip(doc_id=inv.get("id"), label=inv.get("invoice_number"),
                    field="due_date", value=due_date_str, error=e)
            continue
    dq.log(logger)
    
    # Sort by overdue_days (oldest first)
    overdue_list.sort(key=lambda x: x["overdue_days"], reverse=True)
    
    # Calculate summary
    total_overdue = sum(inv["balance"] for inv in overdue_list)
    count_high_risk = sum(1 for inv in overdue_list if inv["overdue_days"] > 180)
    
    return serialize_doc({
        "summary": {
            "total_overdue_invoices": len(overdue_list),
            "total_overdue_amount": round(total_overdue, 2),
            "high_risk_count": count_high_risk,
            "high_risk_amount": round(sum(inv["balance"] for inv in overdue_list if inv["overdue_days"] > 180), 2),
        },
        "invoices": overdue_list,
        "data_quality": dq.as_dict(),
    })

@router.get("/ar-aging")
async def ar_aging(request: Request, source: Optional[str] = None):
    """Aging piutang TUNGGAL (internal + maklon) — skema kanonik (H-01). ?source=internal|maklon."""
    await require_auth(request)
    db = get_db()
    from routes.rahaza_ar_canonical import compute_ar_aging
    ent = entity_from_request(request, allow_all=True)
    if not source and ent != ALL:
        # Tahap 8 fase 1: piutang maklon = buku CV Sukma, piutang lain = buku CV Dewi Aditya
        source = "maklon" if ent == SMU else "internal"
    res = await compute_ar_aging(db, source=source or None)
    return {"buckets": {k: round(v) for k, v in res["buckets"].items()}, "total": round(res["total"]),
            "count": res["count"], "details": serialize_doc(res["rows"]), "data_quality": res["data_quality"]}


# ── AP INVOICES ──────────────────────────────────────────────────────────────
@router.get("/ap-invoices")
async def list_ap(request: Request, status: Optional[str] = None, limit: int = Query(500, ge=1, le=5000)):
    await require_auth(request)
    db = get_db()
    ent = entity_from_request(request, allow_all=True)   # Tahap 8
    q = dict(entity_match(ent))
    if status:
        q["status"] = status
    # 2026-11-04: `limit` (dulu tetap 500 → faktur lama hilang diam-diam dari daftar Tagihan)
    rows = await db.rahaza_ap_invoices.find(q, {"_id": 0}).sort("issue_date", -1).limit(limit).to_list(limit)
    for r in rows:
        r["entity"] = entity_of_doc(r)
    return serialize_doc(rows)


@router.post("/ap-invoices")
async def create_ap(request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    vendor_name = (body.get("vendor_name") or "").strip()
    if not vendor_name:
        raise HTTPException(400, "vendor_name wajib.")
    items = body.get("items") or []
    subtotal, norm = _norm_invoice_items(items, unit_default="")
    tax_pct = _to_num(body.get("tax_pct"), "tax_pct")  # PPN yang DITAGIH supplier (sesuai fakturnya)
    if tax_pct < 0:
        raise HTTPException(400, "tax_pct tidak boleh negatif.")
    tax = round(subtotal * tax_pct / 100)
    total = round(subtotal + tax)
    # 2026-11-03: akun debit faktur manual (mis. 5-2200 ongkos jahit, 5-1100 kain). Kosong = bawaan
    # mapping 'ap_invoice.debit_expense_default'. `post_ap_invoice` sudah membaca `gl_debit_code`.
    gl_debit_code = str(body.get("gl_debit_code") or "").strip()
    if gl_debit_code:
        await _check_debit_account(db, gl_debit_code, AP_DEBIT_TYPES, "faktur supplier", "akun beban, HPP, atau aset")
    ent = entity_from_request(request, body)   # Tahap 8: CV faktur (Gabungan ditolak)
    await _validate_mapping_for_entity(db, "ap_invoice", ("credit_ap",) + (() if gl_debit_code else ("debit_expense_default",)),
                                       ent, "Faktur pemasok", extra=(gl_debit_code,) if gl_debit_code else ())
    from core.tax_status import get_tax_profile, input_tax_treatment
    treatment = input_tax_treatment(await get_tax_profile(db, ent))  # non-PKP → PPN = bagian harga beli
    invoice_number = await _gen_number(db, "rahaza_ap_invoices", "AP")
    doc = {
        "id": _uid(), "invoice_number": invoice_number,
        "vendor_name": vendor_name, "vendor_code": body.get("vendor_code") or "",
        "issue_date": body.get("issue_date") or _today_iso(),
        "due_date": body.get("due_date") or _today_iso(),
        "items": norm, "subtotal": round(subtotal), "tax_pct": tax_pct, "tax_amount": tax,
        "input_tax_treatment": treatment,
        "supplier_faktur_number": str(body.get("supplier_faktur_number") or "").strip()[:40],
        "total": total, "paid_amount": 0, "balance": total,
        "status": "draft", "notes": body.get("notes") or "",
        "cost_center_id": body.get("cost_center_id") or None,
        "gl_debit_code": gl_debit_code or None,
        "entity": ent,
        "created_at": _now(), "updated_at": _now(),
        "created_by": user["id"], "created_by_name": user.get("name", ""),
    }
    await db.rahaza_ap_invoices.insert_one(doc)
    # 2026-11-02 (K11): faktur MANUAL untuk pemasok yang masih punya GR belum ditagih → peringatan
    # "gunakan Tagihan dari GR" (faktur manual tidak menutup GRNI; barang yang sama bisa tertagih dua kali).
    # Hanya peringatan — faktur tetap tersimpan (biaya non-GR seperti jasa tetap lewat jalur ini).
    from routes.rahaza_ap_from_gr import uninvoiced_gr_warning
    try:
        warn = await uninvoiced_gr_warning(db, vendor_name=vendor_name, supplier_id=body.get("supplier_id"))
    except Exception:  # noqa: BLE001 — peringatan tidak boleh menggagalkan faktur yang sudah tersimpan
        warn = {"warning": None, "grs": [], "amount": 0.0}
    out = serialize_doc(doc)
    out["warning"] = warn.get("warning")
    out["uninvoiced_grs"] = serialize_doc(warn.get("grs") or [])
    return out


@router.post("/ap-invoices/{iid}/payment")
async def record_ap_payment(iid: str, request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    amount = _to_amount(body.get("amount"))
    if amount <= 0:
        raise HTTPException(400, "amount harus > 0")
    # FIN-07: diskon pembelian dari layar (amount = kas bersih, discount_amount = potongan) → hutang berkurang bruto
    discount = _to_amount(body.get("discount_amount") or 0)
    if discount < 0:
        raise HTTPException(400, "discount_amount tidak boleh negatif")
    gross = round(amount + discount)
    inv = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    if (inv.get("status") or "").lower() == "draft":
        # B-11: pembayaran atas invoice draft dulu ikut memposting invoice diam-diam
        raise HTTPException(400, "Invoice masih draft — approve/kirim (send) invoice terlebih dahulu sebelum mencatat pembayaran.")
    account_id = body.get("account_id")
    await _reject_unknown_cash_account(db, account_id)  # sebelum hutang berkurang
    await validate_cash_account_owner(db, account_id, entity_of_doc(inv), what="Pembayaran hutang")  # Tahap 8
    if inv.get("intercompany") and discount > 0:
        raise HTTPException(400, "Hutang antar CV tidak memakai potongan pembayaran.")
    ic_out = await _settle_intercompany(db, "ap", inv, amount, account_id, body, user)   # Tahap 8 fase 2
    if ic_out is not None:
        return ic_out
    # ── R10 concurrency hardening (TOCTOU-safe): atomic conditional payment (CC3).
    updated = await db.rahaza_ap_invoices.find_one_and_update(
        {
            "id": iid,
            "status": {"$nin": ["cancelled", "void", "written_off"]},
            "$expr": {"$lte": [
                {"$add": [{"$ifNull": ["$paid_amount", 0]}, gross]},
                {"$add": [{"$ifNull": ["$total", 0]}, 0.01]},
            ]},
        },
        [{"$set": {
            "paid_amount": {"$round": [{"$add": [{"$ifNull": ["$paid_amount", 0]}, gross]}, 0]},
            "balance": {"$max": [0, {"$round": [
                {"$subtract": [{"$ifNull": ["$total", 0]},
                               {"$add": [{"$ifNull": ["$paid_amount", 0]}, gross]}]}, 0]}]},
            "status": {"$cond": [
                {"$gte": [{"$add": [{"$ifNull": ["$paid_amount", 0]}, gross]},
                          {"$subtract": [{"$ifNull": ["$total", 0]}, 0.01]}]},
                "paid", "partial_paid"]},
            "updated_at": _now(),
        }}],
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        inv2 = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
        if not inv2:
            raise HTTPException(404, "Invoice tidak ditemukan.")
        _st = (inv2.get("status") or "").lower()
        if _st in ("cancelled", "void", "written_off"):
            raise HTTPException(400, f"Tidak bisa mencatat pembayaran untuk invoice berstatus '{_st}'.")
        raise HTTPException(400, "Pembayaran + diskon melebihi sisa hutang invoice.")
    inv = updated
    payment_date = body.get("date") or _today_iso()
    movement_id = None
    if account_id:
        acc = await db.rahaza_cash_accounts.find_one({"id": account_id}, {"_id": 0})
        if acc:
            movement_id = _uid()
            await db.rahaza_cash_movements.insert_one({
                "id": movement_id, "account_id": account_id, "account_name": acc.get("name"),
                "direction": "out", "amount": round(amount),
                "category": "ap_payment", "ref_id": iid, "ref_label": inv.get("invoice_number"),
                "date": payment_date, "notes": body.get("notes") or "",
                "timestamp": _now(), "created_by": user["id"], "created_by_name": user.get("name", ""),
            })
    payment_id = await _record_payment_doc(db, "rahaza_ap_payments", inv, amount, account_id, movement_id,
                                           payment_date, body.get("notes"), user)
    if discount > 0:
        await db.rahaza_ap_payments.update_one({"id": payment_id}, {"$set": {"discount_amount": discount, "gross_amount": gross}})

    # ── F2 Auto-post: ensure AP invoice posted first, then post payment disbursement
    posting_result = None
    try:
        inv_refresh = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
        if not inv_refresh.get("gl_je_id"):
            await post_ap_invoice(db, inv_refresh, user)
            inv_refresh = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
        posting_result = await post_ap_payment(
            db, inv_refresh, gross, account_id, payment_date, user, movement_id=movement_id or payment_id,
            discount_taken=discount,  # FIN-07: Dr Hutang bruto / Cr Kas bersih / Cr Diskon Pembelian
        )
    except Exception as e:
        log.exception("AP payment auto-post failed")
        posting_result = {"ok": False, "error": str(e)}
    await db.rahaza_ap_payments.update_one({"id": payment_id}, {"$set": {
        "gl_je_id": (posting_result or {}).get("je_id"), "gl_je_number": (posting_result or {}).get("je_number"),
        "post_error": None if (posting_result or {}).get("ok") else (posting_result or {}).get("error")}})

    out = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = posting_result
    out["_movement_id"] = movement_id
    out["_payment_id"] = payment_id
    return serialize_doc(out)


@router.get("/ap-invoices/{iid}/payments")
async def list_ap_payments(iid: str, request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_ap_payments.find({"invoice_id": iid}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return serialize_doc(await _enrich_payments(db, rows))


@router.post("/ap-invoices/{iid}/status")
async def change_ap_status(iid: str, request: Request):
    """F2: AP status change (draft → sent → cancelled). Auto-post JE on sent."""
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    new_status = (body.get("status") or "").lower()
    if new_status not in AP_STATUS:
        raise HTTPException(400, f"status invalid: {AP_STATUS}")
    inv = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    if inv.get("intercompany"):
        raise HTTPException(400, IC_DOC_MSG)   # Tahap 8 fase 2
    old_status = inv.get("status")
    # 2026-11-02 (audit No.44a): batal faktur yang sudah dibayar mem-void jurnal faktur tetapi jurnal
    # pembayaran tetap → hutang 2-1100 bersaldo debit tanpa dokumen. Aturan sama dengan faktur maklon.
    if new_status == "cancelled" and float(inv.get("paid_amount") or 0) > 0.009:
        _paid = f"{float(inv.get('paid_amount') or 0):,.0f}".replace(",", ".")
        raise HTTPException(400, f"Faktur {inv.get('invoice_number')} sudah dibayar Rp {_paid} — tidak bisa "
                                 f"dibatalkan. Batalkan/void pembayarannya dulu atau buat nota debit/retur pemasok.")
    if new_status == "cancelled" and (inv.get("source") == "gr" or inv.get("gr_ids")):
        return await _cancel_ap_from_gr(db, inv, user)
    # 2026-11-06 (pola P9): status lama di filter — pemeriksaan "sudah dibayar" di atas tidak lagi bisa
    # disalip pembayaran yang masuk di sela baca & tulis.
    _res = await db.rahaza_ap_invoices.update_one({"id": iid, "status": old_status},
                                                  {"$set": {"status": new_status, "updated_at": _now()}})
    if not _res.matched_count:
        raise HTTPException(409, "Faktur ini baru saja diubah pengguna lain (mis. pembayaran tercatat) — muat ulang lalu ulangi.")
    out = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})

    posting_result = None
    try:
        if new_status == "sent" and old_status != "sent" and not out.get("gl_je_id"):
            posting_result = await post_ap_invoice(db, out, user)
        elif new_status == "cancelled" and out.get("gl_je_id"):
            posting_result = await void_ap_invoice_posting(db, iid, user, reason="AP cancelled")
    except Exception as e:
        log.exception("AP auto-post failed")
        posting_result = {"ok": False, "error": str(e)}

    out = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    if posting_result is not None:
        out["_posting_result"] = posting_result
    return serialize_doc(out)


async def _cancel_ap_from_gr(db, inv: dict, user: dict) -> dict:
    """2026-11-06 (Tahap 1): batal faktur dari GR = klaim status atomik → void jurnal (GRNI terbuka
    lagi) → baris GR dilepas supaya bisa ditagih ulang. Void gagal (mis. periode tertutup) ⇒ batal
    DITOLAK dan status dikembalikan, supaya GR tidak dilepas sementara jurnalnya masih mendebit GRNI."""
    iid, old_status = inv["id"], inv.get("status")
    if old_status == "cancelled":
        raise HTTPException(400, f"Faktur {inv.get('invoice_number')} sudah dibatalkan.")
    claim = await db.rahaza_ap_invoices.update_one(
        {"id": iid, "status": old_status}, {"$set": {"status": "cancelled", "updated_at": _now()}})
    if not claim.matched_count:
        raise HTTPException(409, f"Faktur {inv.get('invoice_number')} sedang diubah pengguna lain. Muat ulang.")
    try:
        posting_result = await void_ap_invoice_posting(db, iid, user, reason="AP cancelled")
    except Exception as e:  # noqa: BLE001
        log.exception("void jurnal faktur dari GR gagal")
        posting_result = {"ok": False, "error": str(e)}
    if not posting_result.get("ok"):
        await db.rahaza_ap_invoices.update_one({"id": iid, "status": "cancelled"},
                                               {"$set": {"status": old_status, "updated_at": _now()}})
        raise HTTPException(400, f"Faktur {inv.get('invoice_number')} tidak bisa dibatalkan: jurnalnya tidak bisa "
                                 f"dibalik ({posting_result.get('error')}). Buka periodenya dulu lalu ulangi.")
    from routes.rahaza_ap_from_gr import release_gr_for_cancelled_invoice
    released = await release_gr_for_cancelled_invoice(db, inv)
    out = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = posting_result
    out["_released_grs"] = released
    return serialize_doc(out)


@router.post("/ap-invoices/{iid}/send")
async def send_ap_invoice(iid: str, request: Request):
    """F2: explicit 'send' action → status=sent + auto-post JE."""
    user = await _require_fin(request)
    db = get_db()
    inv = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    if inv.get("status") not in ("draft", "sent"):
        raise HTTPException(400, f"Hanya draft/sent yang bisa di-send. Status: {inv.get('status')}")
    # 2026-11-06 (pola P9): status lama di filter — "kirim" ulang tidak menimpa status pembayaran yang baru masuk.
    _res = await db.rahaza_ap_invoices.update_one({"id": iid, "status": inv.get("status")},
                                                  {"$set": {"status": "sent", "updated_at": _now()}})
    if not _res.matched_count:
        raise HTTPException(409, "Faktur ini baru saja diubah pengguna lain (mis. pembayaran tercatat) — muat ulang lalu ulangi.")
    out = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    posting_result = None
    try:
        posting_result = await post_ap_invoice(db, out, user)
    except Exception as e:
        log.exception("AP send auto-post failed")
        posting_result = {"ok": False, "error": str(e)}
    out = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = posting_result
    return serialize_doc(out)


@router.post("/ap-invoices/{iid}/post-to-gl")
async def retry_post_ap(iid: str, request: Request):
    """F2: manual retry posting AP invoice to GL (idempotent)."""
    user = await _require_fin(request)
    db = get_db()
    inv = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice tidak ditemukan.")
    result = await post_ap_invoice(db, inv, user)
    out = await db.rahaza_ap_invoices.find_one({"id": iid}, {"_id": 0})
    out["_posting_result"] = result
    return serialize_doc(out)


@router.get("/ap-aging")
async def ap_aging(request: Request):
    """F2: AP Aging report (bucket 0, 1-30, 31-60, 61-90, 90+).

    2026-11-04 (audit Keuangan): SSOT `core.payables` — tagihan pemasok DAN tagihan CMT, tanpa batas
    500 baris (dulu total salah di atas 500 dan tagihan CMT tidak ikut). Total = hutang yang sudah
    dijurnal (sama dengan buku besar); tagihan CMT yang belum dijurnal dikembalikan terpisah."""
    await require_auth(request)
    db = get_db()
    from core.payables import aging, open_payable_rows
    ent = entity_from_request(request, allow_all=True)   # Tahap 8
    out = aging(await open_payable_rows(db, entity=ent), today_wib())
    out["entity"] = ent
    return serialize_doc(out)


# ── CASH ACCOUNTS & MOVEMENTS ────────────────────────────────────────────────
# Iter 121/122: saldo kartu kas = Buku Besar (lihat rahaza_posting.cash_accounts_with_gl).
_cash_accounts_with_gl = cash_accounts_with_gl


async def _decorate_cash_balances(db, rows: list) -> list:
    ids = [r["id"] for r in rows]
    fresh = {r["id"]: r for r in await cash_accounts_with_gl(db, {"id": {"$in": ids}})}
    for r in rows:
        r.update(fresh.get(r["id"], {}))
    return rows


@router.get("/cash-accounts")
async def list_cash_accounts(request: Request, active_only: bool = True):
    """Tahap 8: hanya rekening milik CV terpilih (`entity`/header X-CV; ALL = semua). Setiap baris membawa
    `entity` (pemilik; dokumen lama = DA)."""
    await require_auth(request)
    db = get_db()
    ent = entity_from_request(request, allow_all=True)
    q = {"active": True} if active_only else {}
    q.update(entity_match(ent))
    rows = await _cash_accounts_with_gl(db, q)
    for r in rows:
        r["entity"] = ent_mod.entity_of_value(r.get("entity"))
    return serialize_doc(rows)


@router.get("/cash-accounts/gl-candidates")
async def cash_gl_candidates(request: Request):
    """Akun kas/bank/dompet di Bagan Akun yang BELUM tertaut ke rekening — pilihan saat Tambah rekening."""
    await _require_fin(request)
    db = get_db()
    from core.fin_statements import cash_account_codes
    codes = await cash_account_codes(db)
    linked = {r["gl_account_code"] async for r in db.rahaza_cash_accounts.find({"gl_account_code": {"$ne": None}}, {"gl_account_code": 1})}
    rows = await db.rahaza_coa_accounts.find({"code": {"$in": sorted(codes - linked)}, "active": True, "is_group": False},
                                             {"_id": 0, "code": 1, "name": 1}).sort("code", 1).to_list(500)
    return rows


@router.post("/finance/sync-masters")
async def sync_masters(request: Request):
    """Sinkron master keuangan ↔ bagan akun (rekening dari CoA, sub-ledger vendor/toko/klien, peta channel, profil CMT)."""
    user = await _require_fin(request)
    from core.finance_sync import sync_finance_masters
    return await sync_finance_masters(get_db(), user)


@router.post("/cash-accounts/sync-gl")
async def sync_cash_accounts_gl(request: Request):
    """Sinkron rekening dari Bagan Akun, pastikan tiap rekening punya akun GL + jurnal saldo awal, kembalikan saldo GL vs mutasi."""
    user = await _require_fin(request)
    db = get_db()
    from routes.coa_auto import ensure_subledger_for_entity
    from core.finance_sync import sync_finance_masters
    sync = await sync_finance_masters(db, user)
    report = []
    for acc in await db.rahaza_cash_accounts.find({"active": True}, {"_id": 0}).to_list(500):
        if not acc.get("gl_account_code"):
            try:
                await ensure_subledger_for_entity(db, "bank", acc, user)
            except Exception as e:  # noqa: BLE001
                log.error("[cash-sync] subledger %s gagal: %s", acc.get("code"), e)
            acc = await db.rahaza_cash_accounts.find_one({"id": acc["id"]}, {"_id": 0})
        res = await post_cash_opening_balance(db, acc, user)
        report.append({"code": acc.get("code"), "gl_account_code": acc.get("gl_account_code"),
                       "opening": res.get("je_number"), "error": res.get("error")})
    return {"report": report, "sync": sync, "accounts": serialize_doc(await _cash_accounts_with_gl(db, {"active": True}))}


@router.post("/cash-accounts")
async def create_cash_account(request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(400, "code & name wajib.")
    dup = await db.rahaza_cash_accounts.find_one({"code": code}, {"_id": 0, "active": 1})
    if dup:
        raise HTTPException(409, f"Kode '{code}' sudah terpakai." + ("" if dup.get("active", True) else
                            " Rekening dengan kode ini sudah dinonaktifkan — aktifkan kembali lewat Edit, jangan buat baru (akun GL-nya sudah ada)."))
    gl_code = (body.get("gl_account_code") or "").strip()
    if gl_code:
        from core.fin_statements import cash_account_codes
        gl_acc = await db.rahaza_coa_accounts.find_one({"code": gl_code, "active": True, "is_group": False}, {"_id": 0})
        if not gl_acc or gl_code not in await cash_account_codes(db):
            raise HTTPException(400, f"Akun GL '{gl_code}' bukan akun kas/bank postable di Bagan Akun.")
        if await db.rahaza_cash_accounts.find_one({"gl_account_code": gl_code}, {"_id": 0}):
            raise HTTPException(409, f"Akun GL '{gl_code}' sudah tertaut ke rekening lain — pilih akun lain atau pakai rekening yang ada.")
    owner = entity_from_request(request, body)   # Tahap 8: pemilik rekening (bawaan = CV terpilih)
    doc = {
        "id": _uid(), "code": code, "name": name,
        "entity": owner,
        "gl_account_code": gl_code or None,
        "type": body.get("type") or "cash",  # cash | bank
        "bank_name": body.get("bank_name") or "",
        "account_number": body.get("account_number") or "",
        "opening_balance": float(body.get("opening_balance") or 0),
        "notes": body.get("notes") or "",
        "active": True,
        "created_at": _now(), "updated_at": _now(),
    }
    await db.rahaza_cash_accounts.insert_one(doc)
    # Phase 6: auto-create COA subledger (Bank) — idempotent, non-fatal.
    # 2026-08-07 — DULU `except Exception: pass`. Rekening bank tanpa subledger
    # COA berarti mutasi kasnya tidak punya tempat di Buku Besar; ini ketahuan
    # jauh kemudian saat neraca tidak seimbang. Tetap non-fatal (pembuatan
    # rekening tidak boleh gagal karena COA), tapi WAJIB tercatat.
    try:
        from routes.coa_auto import ensure_subledger_for_entity
        if not gl_code:
            await ensure_subledger_for_entity(db, "bank", doc, user, parent_code="1-1100" if doc["type"] == "cash" else None)
    except Exception as e:  # noqa: BLE001
        log.error("[coa] subledger COA bank GAGAL dibuat untuk rekening %s (%s) — "
                  "mutasi kas rekening ini tidak punya akun Buku Besar: %s",
                  doc.get("name") or doc.get("id"), doc.get("account_number"), e)
    out = await db.rahaza_cash_accounts.find_one({"id": doc["id"]}, {"_id": 0})
    await _sync_cash_gl_entities(db, out)   # Tahap 8: akun GL rekening berlaku untuk pemiliknya saja
    # Iter 121 (B-06): saldo awal ikut ke GL supaya kartu kas (dibaca dari GL) = mutasi
    out["_opening_post"] = await post_cash_opening_balance(db, out, user)
    out = await db.rahaza_cash_accounts.find_one({"id": doc["id"]}, {"_id": 0}) | {"_opening_post": out["_opening_post"]}
    await _decorate_cash_balances(db, [out])
    return serialize_doc(out)


async def _sync_cash_gl_entities(db, acc: Optional[dict]):
    """Akun GL rekening kas/bank "berlaku untuk" = pemilik rekening (aturan migrasi Tahap 8)."""
    if acc and acc.get("gl_account_code"):
        await db.rahaza_coa_accounts.update_one(
            {"code": acc["gl_account_code"]},
            {"$set": {"entities": [ent_mod.entity_of_value(acc.get("entity"))], "updated_at": _now()}})


@router.put("/cash-accounts/{aid}")
async def update_cash_account(aid: str, request: Request):
    await _require_fin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body.pop("balance", None)
    if "entity" in body:
        # Tahap 8: pemilik rekening hanya DA | SMU (Gabungan/teks lain ditolak 400)
        try:
            body["entity"] = ent_mod.normalize_entity(body.get("entity"), default=DA)
        except ValueError as e:
            raise HTTPException(400, str(e))
    body["updated_at"] = _now()
    await db.rahaza_cash_accounts.update_one({"id": aid}, {"$set": body})
    if "entity" in body:
        await _sync_cash_gl_entities(db, await db.rahaza_cash_accounts.find_one({"id": aid}, {"_id": 0}))
    return {"status": "ok"}


async def cash_account_usage(db, acc: dict) -> dict:
    """Di mana rekening kas/bank dipakai: mutasi kas, jurnal di akun buku besar rekening (termasuk jurnal saldo awal),
    transfer, rekonsiliasi, dan dokumen yang memilih rekening ini sebagai sumber bayar. 10 Nov 2026."""
    from core.hapus_master import hitung_pemakaian
    aid, gl = acc["id"], acc.get("gl_account_code")
    cek = [
        ("mutasi kas", "rahaza_cash_movements", {"account_id": aid}),
        ("sesi rekonsiliasi bank", "bank_recon_sessions", {"cash_account_id": aid}),
        ("penyesuaian rekonsiliasi", "rahaza_bank_recon_adjustments", {"bank_account_id": aid}),
        ("klaim biaya", "rahaza_expense_claims", {"bank_account_id": aid}),
        ("penyelesaian perjalanan dinas", "employee_travel_settlements", {"bank_account_id": aid}),
        ("pencairan kasbon", "dewi_kasbon_requests", {"disbursement_cash_account_id": aid}),
    ]
    if gl:
        cek += [
            ("baris jurnal", "rahaza_journal_lines", {"account_code": gl}),
            ("transfer bank", "rahaza_bank_transfers", {"$or": [{"from_account_code": gl}, {"to_account_code": gl}]}),
        ]
    pakai = await hitung_pemakaian(db, cek)
    # saldo awal yang belum sempat dijurnal tetap saldo — rekening bersaldo tidak dihapus
    if abs(float(acc.get("opening_balance") or 0)) >= 0.005 and not pakai.get("baris jurnal"):
        pakai["saldo awal"] = 1
    return pakai


@router.delete("/cash-accounts/{aid}")
async def delete_cash_account(aid: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026, owner "master data bisa dihapus"):
    hapus permanen rekening yang belum pernah dipakai (tanpa mutasi, jurnal, saldo awal, transfer, rekonsiliasi);
    akun buku besar yang DIBUAT OTOMATIS untuk rekening itu ikut dihapus (akun pilihan dari Bagan Akun tidak
    disentuh). Selain itu 409 dan layar menawarkan Nonaktifkan."""
    user = await _require_fin(request)
    db = get_db()
    if hard:
        from core.hapus_master import tolak_bila_dipakai
        acc = await db.rahaza_cash_accounts.find_one({"id": aid}, {"_id": 0})
        if not acc:
            raise HTTPException(404, "Rekening tidak ditemukan.")
        tolak_bila_dipakai("Rekening", acc.get("name") or acc.get("code") or "", await cash_account_usage(db, acc))
        akun = await db.rahaza_coa_accounts.delete_many({"flags.subledger_entity_type": "bank",
                                                         "flags.subledger_entity_id": aid})
        await db.rahaza_cash_accounts.delete_one({"id": aid})
        await log_activity(user.get("id") or "", user.get("name") or "", "delete", "rahaza.cash_account",
                           f"{acc.get('code')} {acc.get('name')} akun_gl_otomatis={akun.deleted_count}")
        return {"status": "deleted", "deleted": True}
    await db.rahaza_cash_accounts.update_one({"id": aid, "active": True}, {"$set": {"active": False}})
    return {"status": "deleted"}


@router.get("/cash-movements")
async def list_movements(request: Request, account_id: Optional[str] = None, from_: Optional[str] = None, to: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    q = {}
    if account_id:
        q["account_id"] = account_id
    if from_ or to:
        rg = {}
        if from_:
            rg["$gte"] = from_
        if to:
            rg["$lte"] = to
        q["date"] = rg
    rows = await db.rahaza_cash_movements.find(q, {"_id": 0}).sort("timestamp", -1).to_list(500)
    return serialize_doc(rows)


# ── EXPENSES ─────────────────────────────────────────────────────────────────
@router.get("/expenses")
async def list_expenses(request: Request, from_: Optional[str] = None, to: Optional[str] = None, cost_center_id: Optional[str] = None,
                        limit: int = Query(500, ge=1, le=5000)):
    # 2026-11-04 (audit Keuangan): layar memilih periode + limit; bila hasil = limit layar memberi peringatan.
    await require_auth(request)
    db = get_db()
    q = dict(entity_match(entity_from_request(request, allow_all=True)))   # Tahap 8
    if cost_center_id:
        q["cost_center_id"] = cost_center_id
    if from_ or to:
        rg = {}
        if from_:
            rg["$gte"] = from_
        if to:
            rg["$lte"] = to
        q["date"] = rg
    rows = await db.rahaza_expenses.find(q, {"_id": 0}).sort("date", -1).to_list(limit)
    # enrich cost center
    ccids = list({r.get("cost_center_id") for r in rows if r.get("cost_center_id")})
    ccs = await db.rahaza_cost_centers.find({"id": {"$in": ccids}}, {"_id": 0}).to_list(500) if ccids else []
    ccmap = {c["id"]: c for c in ccs}
    for r in rows:
        cc = ccmap.get(r.get("cost_center_id")) or {}
        r["cost_center_code"] = cc.get("code")
        r["cost_center_name"] = cc.get("name")
    return serialize_doc(rows)


@router.post("/expenses")
async def create_expense(request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    amount = _to_amount(body.get("amount"))
    if amount <= 0:
        raise HTTPException(400, "amount harus > 0")
    # 2026-11-04 (owner: akun beban wajib dipilih di layar): akun yang dikirim dicek dulu. Kosong tetap
    # diterima untuk pemanggil API lama → jatuh ke `expense.debit_expense_default` seperti sebelumnya.
    gl_debit_code = str(body.get("gl_debit_code") or "").strip()
    if gl_debit_code:
        await _check_debit_account(db, gl_debit_code, EXPENSE_DEBIT_TYPES, "pengeluaran", "akun beban atau HPP")
    await _reject_unknown_cash_account(db, body.get("account_id"))
    # Tahap 8: CV pengeluaran = CV yang dikirim layar, atau pemilik rekening yang dipakai.
    ent = explicit_entity(request, body) or await ent_mod.cash_account_entity(db, account_id=body.get("account_id")) or DA
    await validate_cash_account_owner(db, body.get("account_id"), ent, what="Pengeluaran")
    await _validate_mapping_for_entity(db, "expense", () if gl_debit_code else ("debit_expense_default",), ent,
                                       "Pengeluaran", extra=(gl_debit_code,) if gl_debit_code else ())
    doc = {
        "id": _uid(),
        "entity": ent,
        "date": body.get("date") or _today_iso(),
        "category": body.get("category") or "operasional",
        "description": body.get("description") or "",
        "amount": round(amount),
        "cost_center_id": body.get("cost_center_id") or None,
        "account_id": body.get("account_id") or None,
        "gl_debit_code": gl_debit_code or None,  # F2: akun beban pilihan (wajib di layar sejak 2026-11-04)
        "notes": body.get("notes") or "",
        "created_at": _now(), "created_by": user["id"], "created_by_name": user.get("name", ""),
    }
    await db.rahaza_expenses.insert_one(doc)
    # If account_id provided, record cash movement
    if doc["account_id"]:
        acc = await db.rahaza_cash_accounts.find_one({"id": doc["account_id"]}, {"_id": 0})
        if acc:
            await db.rahaza_cash_movements.insert_one({
                "id": _uid(), "account_id": doc["account_id"], "account_name": acc.get("name"),
                "direction": "out", "amount": doc["amount"],
                "category": "expense", "ref_id": doc["id"], "ref_label": doc["description"][:40],
                "date": doc["date"], "notes": doc["notes"],
                "timestamp": _now(), "created_by": user["id"], "created_by_name": user.get("name", ""),
            })
    # ── F2 Auto-post
    posting_result = None
    try:
        posting_result = await post_expense(db, doc, user)
    except Exception as e:
        log.exception("Expense auto-post failed")
        posting_result = {"ok": False, "error": str(e)}
    out = await db.rahaza_expenses.find_one({"id": doc["id"]}, {"_id": 0})
    out["_posting_result"] = posting_result
    return serialize_doc(out)


@router.post("/expenses/{eid}/post-to-gl")
async def retry_post_expense(eid: str, request: Request):
    """F2: manual retry post expense to GL."""
    user = await _require_fin(request)
    db = get_db()
    exp = await db.rahaza_expenses.find_one({"id": eid}, {"_id": 0})
    if not exp:
        raise HTTPException(404, "Expense tidak ditemukan.")
    result = await post_expense(db, exp, user)
    out = await db.rahaza_expenses.find_one({"id": eid}, {"_id": 0})
    out["_posting_result"] = result
    return serialize_doc(out)


@router.get("/finance-summary")
async def finance_summary(request: Request):
    """Ringkasan Finance utk dashboard."""
    await require_auth(request)
    db = get_db()
    # AR outstanding
    ar = await db.rahaza_ar_invoices.aggregate([
        {"$match": {"status": {"$in": ["sent", "issued", "partial_paid", "overdue"]}}},
        {"$group": {"_id": None, "outstanding": {"$sum": "$balance"}, "count": {"$sum": 1}}},
    ]).to_list(500)
    # 2026-11-06 (pola P4): status hutang terbuka = core.payables.AP_OPEN (cron menandai `overdue`;
    # dulu tagihan jatuh tempo hilang dari angka hutang di ringkasan ini)
    from core.payables import AP_OPEN
    ap = await db.rahaza_ap_invoices.aggregate([
        {"$match": {"status": {"$in": list(AP_OPEN)}}},
        {"$group": {"_id": None, "outstanding": {"$sum": "$balance"}, "count": {"$sum": 1}}},
    ]).to_list(500)
    cash_rows = await _cash_accounts_with_gl(db, {"active": True})
    return {
        "ar_outstanding": round((ar[0] if ar else {}).get("outstanding", 0) or 0),
        "ar_count": (ar[0] if ar else {}).get("count", 0),
        "ap_outstanding": round((ap[0] if ap else {}).get("outstanding", 0) or 0),
        "ap_count": (ap[0] if ap else {}).get("count", 0),
        "cash_balance": round(sum(float(r.get("balance") or 0) for r in cash_rows)),
        "cash_balance_source": "gl",
        "cash_accounts_count": len(cash_rows),
    }



# ══════════════════════════════════════════════════════════════════════════════
# CUSTOMER STATEMENT (rekening koran piutang) — dipindah dari rahaza_shipments
# (deprecated) ke engine AR. Hanya membaca rahaza_ar_invoices + rahaza_customers.
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/customer-statement/{customer_id}")
async def customer_statement(customer_id: str, request: Request):
    """
    Statement piutang customer dengan rentang tanggal.
    Response: {customer, period, invoices, summary:{count,total_billed,total_paid,outstanding}}
    """
    await require_auth(request)
    db = get_db()
    sp = request.query_params
    date_from = sp.get("date_from")
    date_to = sp.get("date_to")

    cust = await db.rahaza_customers.find_one({"id": customer_id}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer tidak ditemukan")

    # 2026-11-02 (audit No.49): dulu membaca field `paid` yang tidak pernah ditulis (total_paid
    # selalu 0), memuat faktur draft/batal, dan mengabaikan nota kredit.
    q = {"customer_id": customer_id, "status": {"$nin": list(STATEMENT_EXCLUDED)}}
    if date_from and date_to:
        q["issue_date"] = {"$gte": date_from, "$lte": date_to}
    invoices = await db.rahaza_ar_invoices.find(q, {"_id": 0}).sort("issue_date", 1).to_list(500)
    summ = statement_summary(invoices)

    return {
        "customer": {
            "id": cust.get("id"),
            "code": cust.get("code"),
            "name": cust.get("name"),
            "address": cust.get("address"),
            "phone": cust.get("phone"),
        },
        "period": {"from": date_from, "to": date_to},
        "invoices": invoices,
        "summary": summ,
    }


STATEMENT_EXCLUDED = ("draft", "cancelled", "void")


def statement_summary(invoices: list) -> dict:
    """Ringkasan statement: tagihan, dibayar (`paid_amount`), nota kredit, dihapusbukukan, sisa."""
    billed = paid = credited = written_off = outstanding = 0.0
    for i in invoices:
        t = float(i.get("total") or 0)
        p = float(i.get("paid_amount") or 0)
        c = float(i.get("credited_amount") or 0)
        rest = max(0.0, t - p - c)
        billed += t
        paid += p
        credited += c
        if (i.get("status") or "") == "written_off":
            written_off += rest
        else:
            outstanding += rest
    return {"count": len(invoices), "total_billed": round(billed, 2), "total_paid": round(paid, 2),
            "total_credited": round(credited, 2), "total_written_off": round(written_off, 2),
            "outstanding": round(outstanding, 2)}
