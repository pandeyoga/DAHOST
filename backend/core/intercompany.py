"""core.intercompany — transaksi ANTAR CV (Tahap 8 fase 2 & 3, keputusan owner 7 Nov 2026).

Dua buku di satu aplikasi (``core.entities``): CV Dewi Aditya (DA) dan CV Sukma (SMU). Modul ini satu-satunya
tempat aturan transaksi di antara keduanya:

* **Tim jahit CV Sukma** = vendor CMT bertanda ``vendor_partners.owner_entity == 'SMU'`` (diatur di master
  Vendor CMT; migrasi ``2026_11_08_antar_cv --vendor-code``). Nama vendor TIDAK pernah dipakai sebagai kunci.
* **Hutang/piutang antar CV = hutang/piutang biasa + label "antar CV"** (K9) — tanpa modul/akun kontrol baru.
  Lawan transaksi memakai master yang sudah ada, ditandai ``intercompany_entity`` (CV yang diwakili):
    - buku DA : pelanggan "CV Sukma Mitra Utama" (``rahaza_customers``) → piutang 1-1301-<kode>;
                hutang DA ke Sukma = sub-ledger hutang CMT vendor tim Sukma (2-1110-<kode vendor>);
    - buku SMU: klien maklon "CV Dewi Aditya Official" (``dewi_maklon_clients``) → 1-1305-<kode> / 4-1500-<kode>;
                pemasok "CV Dewi Aditya Official" (``rahaza_suppliers``) → hutang 2-1100-<kode>.
* Diinput SEKALI; pasangan di buku CV lain dibuat otomatis, berlabel di kepala jurnal, baris jurnal, dan
  dokumen: ``intercompany: true`` + ``counterparty_entity`` (+ ``ic_kind``, ``ic_pair_id``).
* Empat kemungkinan penjahit (desain §2): PO internal + tim Sukma → tagihan DA (seperti biasa, berlabel) +
  piutang Sukma otomatis per penerimaan lolos QC; PO maklon + tim Sukma → TIDAK ada tagihan CMT; CMT luar →
  tidak berubah.
* Aksesoris/bahan DA untuk PO maklon = DA menjual ke Sukma seharga HPP (+ margin yang bisa diatur, bawaan 0%).
* Pembayaran antar CV (bayar tagihan/hutang/piutang berlabel) membuat pasangan otomatis; Transaksi antar CV
  (talangan, pinjaman, uang nyasar, pelunasan) membuat dua jurnal sekaligus.
* Laporan Gabungan (fase 3) mengeliminasi saldo hutang/piutang antar CV dan margin aksesoris; yang tidak bisa
  dicocokkan persis ditampilkan sebagai "Selisih antar CV yang belum tereliminasi", tidak disembunyikan.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from core.entities import (
    ALL, DA, SMU, entity_match, entity_name, entity_of_value, entity_short,
)

log = logging.getLogger(__name__)

OWNER_FIELD = "owner_entity"          # vendor_partners: CV pemilik tim jahit
IC_FLAG = "intercompany_entity"       # master lawan transaksi: CV yang diwakili
IC_LABEL = "antar CV"
OWN_TEAM_MSG = "Dijahit tim sendiri — tanpa tagihan CMT"
MARGIN_KEY = "intercompany_accessory_margin_pct"
MARGIN_ACCOUNT = {"code": "4-9300", "name": "Penjualan Aksesoris ke CV Sukma (antar CV)", "type": "OTHER_INCOME",
                  "parent_code": "4-0000", "normal_balance": "CREDIT"}
UNRECONCILED_LABEL = "Selisih antar CV yang belum tereliminasi"

KIND_SEWING = "sewing"
KIND_ACCESSORY = "accessory"
KIND_MARGIN = "accessory_margin"
KIND_PAYMENT = "payment"
KIND_TXN = "transaction"
KIND_LABELS = {KIND_SEWING: "Tagihan jasa jahit", KIND_ACCESSORY: "Nota aksesoris", KIND_MARGIN: "Margin aksesoris",
               KIND_PAYMENT: "Pembayaran antar CV", KIND_TXN: "Transaksi antar CV"}

SRC_SEWING_AR = "ic_sewing_ar"            # buku SMU: Dr 1-1305-DA / Cr 4-1500-DA
SRC_ACCESSORY_AP = "ic_accessory_ap"      # buku SMU: Dr 5-4100 / Cr 2-1100-DA
SRC_TXN = "ic_transaction"                # dua buku, ref sama (idempotensi per CV)
DOC_SEWING = "ic_sewing"                  # rahaza_ar_invoices.source_module (SMU)
DOC_ACCESSORY = "ic_accessory"            # rahaza_ar_invoices (DA) & rahaza_ap_invoices (SMU)
TXN_COLL = "rahaza_intercompany_txns"

_VOID = ("cancelled", "void", "voided", "rejected", "batal")


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2(v) -> float:
    return round(_f(v), 2)


def fmt_rp(v) -> str:
    return "Rp " + f"{_f(v):,.0f}".replace(",", ".")


def other_entity(ent) -> str:
    return SMU if entity_of_value(ent) == DA else DA


def ic_labels(counterparty: str, kind: str, pair_id: Optional[str] = None) -> dict:
    """Label antar CV untuk `_create_posted_je(labels=…)` dan dokumen."""
    out = {"intercompany": True, "counterparty_entity": entity_of_value(counterparty), "ic_kind": kind}
    if pair_id:
        out["ic_pair_id"] = pair_id
    return out


def _to_date(v) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        from utils.waktu import today_wib
        return today_wib()


# ══════════════════════════════════════════════════════════════════════════════
# 1. TIM JAHIT CV SUKMA (vendor bertanda)
# ══════════════════════════════════════════════════════════════════════════════
def normalize_owner(value) -> Optional[str]:
    """Isian "pemilik penjahit" di master Vendor CMT: kosong/'luar' = vendor luar (None), SMU = tim CV Sukma.
    ValueError bila CV lain (DA tidak punya tim jahit sendiri)."""
    v = str(value or "").strip().upper()
    if v in ("", "NONE", "LUAR", "EXTERNAL", "VENDOR_LUAR"):
        return None
    if v in (SMU, "SUKMA", "CV SUKMA"):
        return SMU
    raise ValueError("Pemilik penjahit hanya boleh kosong (vendor luar) atau CV Sukma.")


async def _canon_vendor(db, vendor_id: Optional[str]) -> Optional[str]:
    if not vendor_id:
        return None
    try:
        from core import cmt_vendor_master
        return await cmt_vendor_master.canonical_id(db, vendor_id) or vendor_id
    except Exception:  # noqa: BLE001 — master CMT lama tidak boleh mematahkan pembacaan
        return vendor_id


async def vendor_owner(db, vendor_id: Optional[str]) -> Optional[str]:
    """CV pemilik vendor CMT (SMU = tim jahit CV Sukma), None = vendor luar / tidak dikenal."""
    vid = await _canon_vendor(db, vendor_id)
    if not vid:
        return None
    v = await db.vendor_partners.find_one({"id": vid}, {"_id": 0, OWNER_FIELD: 1})
    own = (v or {}).get(OWNER_FIELD)
    return SMU if str(own or "").upper() == SMU else None


async def own_team_vendor(db) -> Optional[dict]:
    """Vendor tim jahit CV Sukma (aktif dulu). Dipakai sebagai sub-ledger hutang DA ke Sukma."""
    rows = [v async for v in db.vendor_partners.find({OWNER_FIELD: SMU}, {"_id": 0})]
    rows.sort(key=lambda v: (v.get("is_active") is False, str(v.get("code") or ""), str(v.get("id"))))
    return rows[0] if rows else None


async def bill_vendor_owner(db, bill: dict) -> Optional[str]:
    return await vendor_owner(db, (bill or {}).get("vendor_id") or (bill or {}).get("cmt_partner_id"))


async def po_vendor_is_own_team(db, po: dict, vendor_id: Optional[str]) -> bool:
    return await vendor_owner(db, vendor_id or (po or {}).get("vendor_id")) == SMU


# ══════════════════════════════════════════════════════════════════════════════
# 2. LAWAN TRANSAKSI (master yang sudah ada, ditandai `intercompany_entity`)
# ══════════════════════════════════════════════════════════════════════════════
COUNTERPARTS = {
    # kunci: (koleksi, buku pemakai, CV yang diwakili, kode pilihan)
    "da_customer": {"collection": "rahaza_customers", "book": DA, "represents": SMU, "codes": ("SMU", "CV-SMU"),
                    "label": "Pelanggan CV Sukma di buku CV Dewi Aditya"},
    "smu_client": {"collection": "dewi_maklon_clients", "book": SMU, "represents": DA, "codes": ("DA", "CV-DA"),
                   "label": "Klien maklon CV Dewi Aditya di buku CV Sukma"},
    "smu_supplier": {"collection": "rahaza_suppliers", "book": SMU, "represents": DA, "codes": ("DA", "CV-DA"),
                     "label": "Pemasok CV Dewi Aditya di buku CV Sukma"},
}


async def find_counterpart(db, key: str) -> Optional[dict]:
    spec = COUNTERPARTS[key]
    return await db[spec["collection"]].find_one({IC_FLAG: spec["represents"]}, {"_id": 0})


async def _free_code(db, coll: str, codes: tuple) -> str:
    for c in codes:
        if not await db[coll].find_one({"code": c}, {"_id": 1}):
            return c
    base = codes[-1]
    n = 2
    while await db[coll].find_one({"code": f"{base}-{n}"}, {"_id": 1}):
        n += 1
    return f"{base}-{n}"


def _counterpart_doc(key: str, code: str, user: Optional[dict]) -> dict:
    spec = COUNTERPARTS[key]
    name = entity_name(spec["represents"])
    base = {"id": _uid(), "code": code, "name": name, IC_FLAG: spec["represents"], "intercompany_book": spec["book"],
            "notes": f"Lawan transaksi {IC_LABEL} (dibuat otomatis Tahap 8). Jangan dipakai untuk pihak lain.",
            "created_at": _now(), "updated_at": _now(), "created_by": (user or {}).get("id") or "system"}
    if key == "da_customer":
        base.update({"company_type": "company", "npwp": "", "phone": "", "email": "", "address": "",
                     "payment_terms": "net_30", "credit_limit": 0, "active": True})
    elif key == "smu_client":
        base.update({"pic_name": None, "pic_phone": None, "pic_email": None, "address": None, "city": None,
                     "contract_type": "per_order", "standard_rate_per_pcs": 0, "payment_terms": "net_30",
                     "product_specialization": [], "quality_standard": "standard", "status": "active",
                     "rating": 4.0, "created_by": (user or {}).get("name") or "system"})
    else:
        from routes.procurement_suppliers import name_key
        base.update({"name_key": name_key(name) + "-antar-cv", "npwp": "", "tax_name": "", "tax_type": "non_ppn",
                     "address": "", "city": "", "payment_terms": "net30", "currency": "IDR", "is_active": True,
                     "source": "intercompany"})
    return base


async def _set_account_entities(db, code: Optional[str], ents: list) -> None:
    if code:
        await db.rahaza_coa_accounts.update_one({"code": code}, {"$set": {"entities": list(ents), "updated_at": _now()}})


async def ensure_counterparts(db, user: Optional[dict] = None, *, apply: bool = True) -> dict:
    """Buat (bila belum ada) tiga master lawan transaksi + sub-ledger-nya lewat jalur Auto Akun yang sudah ada.
    Idempoten. ``apply=False`` = hanya melaporkan apa yang akan dibuat (pratinjau migrasi)."""
    from routes.coa_auto import ensure_subledger_for_entity
    out = {}
    for key, spec in COUNTERPARTS.items():
        doc = await find_counterpart(db, key)
        created = False
        if not doc:
            if not apply:
                out[key] = {"exists": False, "would_create": True}
                continue
            code = await _free_code(db, spec["collection"], spec["codes"])
            doc = _counterpart_doc(key, code, user)
            await db[spec["collection"]].insert_one(dict(doc))
            created = True
        accounts = {}
        if apply:
            if key == "da_customer":
                res = await ensure_subledger_for_entity(db, "customer", doc, user)
                accounts["ar"] = res.get("code") if res.get("ok") else doc.get("ar_account_code")
                await _set_account_entities(db, accounts["ar"], [DA])
            elif key == "smu_client":
                from core.maklon_ledger import ensure_client_accounts
                acc = await ensure_client_accounts(db, doc, user)
                accounts = {"ar": acc.get("maklon_client"), "revenue": acc.get("maklon_revenue")}
                for c in accounts.values():
                    await _set_account_entities(db, c, [SMU])
            else:
                res = await ensure_subledger_for_entity(db, "supplier", doc, user)
                accounts["ap"] = res.get("code") if res.get("ok") else doc.get("ap_account_code")
                await _set_account_entities(db, accounts["ap"], [SMU])
        out[key] = {"exists": True, "created": created, "id": doc["id"], "code": doc.get("code"),
                    "name": doc.get("name"), "accounts": accounts}
    return out


async def ic_accounts(db, user: Optional[dict] = None, *, create: bool = True) -> dict:
    """Kode akun lawan transaksi per buku:
        {'DA': {'ar': 1-1301-<SMU>, 'ap': 2-1110-<vendor tim Sukma>},
         'SMU': {'ar': 1-1305-<DA>, 'revenue': 4-1500-<DA>, 'ap': 2-1100-<DA>}, 'records': {...}, 'vendor': {...}}
    ``create=False`` (laporan) hanya membaca; tidak membuat master/akun."""
    recs = {}
    if create:
        info = await ensure_counterparts(db, user, apply=True)
        for k, v in info.items():
            recs[k] = await find_counterpart(db, k) or {}
            recs[k]["_accounts"] = v.get("accounts") or {}
    else:
        for k in COUNTERPARTS:
            recs[k] = await find_counterpart(db, k) or {}
            recs[k]["_accounts"] = {}
    cust, client, supp = recs["da_customer"], recs["smu_client"], recs["smu_supplier"]
    vendor = await own_team_vendor(db)
    da_ap = (vendor or {}).get("ap_account_code")
    if vendor and create:
        try:
            from routes.coa_auto import resolve_ap_account_for_cmt
            da_ap = await resolve_ap_account_for_cmt(db, vendor["id"], vendor.get("name", ""), user) or da_ap
        except Exception:  # noqa: BLE001
            log.exception("[antar-cv] sub-ledger hutang vendor tim Sukma gagal dibuat")
    return {
        DA: {"ar": cust["_accounts"].get("ar") or cust.get("ar_account_code"), "ap": da_ap},
        SMU: {"ar": client["_accounts"].get("ar") or client.get("ar_account_code"),
              "revenue": client["_accounts"].get("revenue") or client.get("revenue_account_code"),
              "ap": supp["_accounts"].get("ap") or supp.get("ap_account_code")},
        "records": {k: {"id": v.get("id"), "code": v.get("code"), "name": v.get("name")} for k, v in recs.items()},
        "vendor": {"id": (vendor or {}).get("id"), "code": (vendor or {}).get("code"),
                   "name": (vendor or {}).get("name")} if vendor else None,
    }


def ar_code(accs: dict, ent: str) -> Optional[str]:
    """Piutang buku ``ent`` atas CV lain."""
    return (accs.get(entity_of_value(ent)) or {}).get("ar")


def ap_code(accs: dict, ent: str) -> Optional[str]:
    """Hutang buku ``ent`` kepada CV lain."""
    return (accs.get(entity_of_value(ent)) or {}).get("ap")


def missing_accounts_message(accs: dict, need: list) -> Optional[str]:
    """Pesan bila akun lawan transaksi yang dibutuhkan belum ada. ``need`` = [(CV, 'ar'|'ap'|'revenue')]."""
    labels = {(DA, "ar"): "piutang CV Dewi Aditya atas CV Sukma",
              (DA, "ap"): "hutang CV Dewi Aditya ke CV Sukma (vendor tim jahit CV Sukma belum ditandai di master "
                          "Vendor CMT)",
              (SMU, "ar"): "piutang CV Sukma atas CV Dewi Aditya", (SMU, "revenue"): "pendapatan jasa jahit CV Sukma",
              (SMU, "ap"): "hutang CV Sukma ke CV Dewi Aditya"}
    miss = [labels[(e, k)] for e, k in need if not (accs.get(e) or {}).get(k)]
    if not miss:
        return None
    return "Akun antar CV belum lengkap: " + "; ".join(miss) + "."


# ══════════════════════════════════════════════════════════════════════════════
# 3. TAGIHAN JASA JAHIT (PO internal + tim Sukma) — piutang Sukma otomatis per tagihan
# ══════════════════════════════════════════════════════════════════════════════
def bill_net_amount(bill: dict) -> float:
    for k in ("net_amount", "total_amount", "subtotal"):
        if (bill or {}).get(k) not in (None, ""):
            return _r2(bill.get(k))
    return 0.0


async def sewing_bill_is_ic(db, bill: dict) -> bool:
    """Tagihan CMT DA (PO internal / tanpa jenis / alur job) kepada vendor tim jahit CV Sukma."""
    if (bill or {}).get("intercompany") is True:
        return True
    if await bill_vendor_owner(db, bill) != SMU:
        return False
    from routes.dewi_maklon_finance import cmt_bill_entity
    return await cmt_bill_entity(db, bill) == DA


async def find_sewing_ar(db, bill_id: str) -> Optional[dict]:
    return await db.rahaza_ar_invoices.find_one(
        {"source_module": DOC_SEWING, "ic_bill_id": bill_id, "status": {"$nin": list(_VOID)}}, {"_id": 0})


async def _doc_number(db, coll: str, prefix: str, d: date) -> str:
    from utils.counters import gen_prefixed_number
    return await gen_prefixed_number(db, coll, "invoice_number", f"{prefix}-{d.strftime('%Y%m%d')}-", 3)


async def post_sewing_mirror(db, bill: dict, user: dict) -> dict:
    """Piutang CV Sukma atas CV Dewi Aditya untuk SATU tagihan CMT tim Sukma (idempoten per tagihan):
    dokumen ``rahaza_ar_invoices`` (CV Sukma, "Tagihan Jasa Jahit") + jurnal Dr 1-1305-DA / Cr 4-1500-DA."""
    from routes.rahaza_posting import _create_posted_je, _find_existing_je
    bill_id = bill.get("id")
    amount = bill_net_amount(bill)
    if amount <= 0:
        return {"ok": True, "skipped": True, "reason": "tagihan bernilai 0"}
    accs = await ic_accounts(db, user)
    miss = missing_accounts_message(accs, [(SMU, "ar"), (SMU, "revenue")])
    if miss:
        return {"ok": False, "error": miss}
    client = (accs["records"].get("smu_client") or {})
    d = _to_date(bill.get("invoice_date") or bill.get("period_to") or bill.get("payment_date")
                 or str(bill.get("created_at") or "")[:10])
    ar = await find_sewing_ar(db, bill_id)
    if not ar:
        number = await _doc_number(db, "rahaza_ar_invoices", "TJ-SMU", d)
        items = [{"description": f"Jasa jahit {b.get('sku_code') or b.get('sku') or ''}".strip(),
                  "sku": b.get("sku_code") or b.get("sku") or "", "qty": int(b.get("qty_billed", b.get("qty_actual", 0)) or 0),
                  "unit": "pcs", "unit_price": _r2(b.get("cmt_rate_per_pcs")), "total": _r2(b.get("line_amount"))}
                 for b in bill.get("breakdown") or []]
        ar = {
            "id": _uid(), "invoice_number": number, "entity": SMU, "source_module": DOC_SEWING,
            **ic_labels(DA, KIND_SEWING, bill_id),
            "ic_bill_id": bill_id, "ic_bill_code": bill.get("payment_code") or "",
            "po_id": bill.get("po_id") or "", "po_number": bill.get("po_number") or "",
            "source_receipt_code": bill.get("source_receipt_code") or "",
            "customer_id": client.get("id"), "customer_name": client.get("name") or entity_name(DA),
            "client_code": client.get("code") or "",
            "issue_date": d.isoformat(), "invoice_date": d.isoformat(), "due_date": (d + timedelta(days=30)).isoformat(),
            "items": items, "subtotal": amount, "tax_pct": 0, "tax_amount": 0, "discount_amount": 0,
            "total": amount, "paid_amount": 0, "balance": amount, "total_amount": amount, "amount_paid": 0,
            "amount_due": amount, "status": "sent", "gl_ar_account_code": accs[SMU]["ar"],
            "revenue_account_code": accs[SMU]["revenue"],
            "notes": (f"Tagihan jasa jahit tim CV Sukma ke CV Dewi Aditya atas tagihan CMT "
                      f"{bill.get('payment_code') or ''} (PO {bill.get('po_number') or '-'}) — {IC_LABEL}."),
            "created_at": _now(), "updated_at": _now(), "created_by": (user or {}).get("id") or "system",
        }
        await db.rahaza_ar_invoices.insert_one(dict(ar))
    ref = f"icsew:{bill_id}"
    je = await _find_existing_je(db, SRC_SEWING_AR, ref, entity=SMU)
    if je:
        res = {"ok": True, "je_id": je["id"], "je_number": je.get("je_number"), "already_posted": True}
    else:
        memo = f"Tagihan jasa jahit {ar['invoice_number']} ke {entity_short(DA)} · CMT {bill.get('payment_code') or ''}"
        res = await _create_posted_je(
            db, d, memo, SRC_SEWING_AR, ref,
            [{"account_code": accs[SMU]["ar"], "debit": amount, "credit": 0, "description": memo},
             {"account_code": accs[SMU]["revenue"], "debit": 0, "credit": amount, "description": memo}],
            user, entity=SMU, labels=ic_labels(DA, KIND_SEWING, bill_id))
    upd_ar = ({"gl_je_id": res["je_id"], "gl_je_number": res.get("je_number"), "gl_posted_at": _now(),
               "post_error": None} if res.get("ok") else {"post_error": res.get("error"), "post_error_at": _now()})
    await db.rahaza_ar_invoices.update_one({"id": ar["id"]}, {"$set": upd_ar})
    await db.dewi_cmt_payments.update_one({"id": bill_id}, {"$set": {
        **ic_labels(SMU, KIND_SEWING, bill_id), "ic_ar_invoice_id": ar["id"],
        "ic_ar_invoice_number": ar["invoice_number"], "updated_at": _now()}})
    return {**res, "ar_invoice_id": ar["id"], "ar_invoice_number": ar["invoice_number"], "amount": amount}


async def adjust_sewing_mirror(db, bill: dict, reduce_by: float, user: dict, ref: str, memo: str) -> dict:
    """Pasangan potongan tagihan CMT tim Sukma (selisih "potong"): Dr 4-1500-DA / Cr 1-1305-DA + piutang berkurang."""
    from routes.rahaza_posting import _create_posted_je, _find_existing_je
    amt = _r2(reduce_by)
    ar = await find_sewing_ar(db, bill.get("id"))
    if amt <= 0 or not ar:
        return {"ok": True, "skipped": True}
    if await _find_existing_je(db, SRC_SEWING_AR, ref, entity=SMU):
        return {"ok": True, "already_posted": True}
    res = await _create_posted_je(
        db, _to_date(None), memo, SRC_SEWING_AR, ref,
        [{"account_code": ar.get("revenue_account_code"), "debit": amt, "credit": 0, "description": memo},
         {"account_code": ar.get("gl_ar_account_code"), "debit": 0, "credit": amt, "description": memo}],
        user, entity=SMU, labels=ic_labels(DA, KIND_SEWING, bill.get("id")))
    if res.get("ok"):
        total = _r2(_f(ar.get("total")) - amt)
        bal = _r2(max(0.0, total - _f(ar.get("paid_amount"))))
        await db.rahaza_ar_invoices.update_one({"id": ar["id"]}, {"$set": {
            "total": total, "total_amount": total, "subtotal": total, "balance": bal, "amount_due": bal,
            "status": "paid" if bal <= 0.01 and _f(ar.get("paid_amount")) > 0 else ar.get("status"),
            "adjusted_amount": _r2(_f(ar.get("adjusted_amount")) + amt), "updated_at": _now()}})
    return res


# ══════════════════════════════════════════════════════════════════════════════
# 4. NOTA AKSESORIS (DA → CV Sukma untuk PO maklon) — HPP + margin
# ══════════════════════════════════════════════════════════════════════════════
def parse_margin(value) -> float:
    """Margin aksesoris antar CV dalam persen: 0–100. ValueError bila di luar itu."""
    try:
        v = float(value if value not in (None, "") else 0)
    except (TypeError, ValueError):
        raise ValueError("Margin aksesoris antar CV harus angka persen (0–100).") from None
    if v != v or v < 0 or v > 100:
        raise ValueError("Margin aksesoris antar CV harus di antara 0 dan 100 persen.")
    return round(v, 4)


async def margin_pct(db) -> float:
    from routes.dewi_system_config import get_config_value
    try:
        return parse_margin(await get_config_value(db, MARGIN_KEY, 0))
    except ValueError:
        log.warning("[antar-cv] setelan %s tidak sah — dipakai 0%%", MARGIN_KEY)
        return 0.0


def price_split(cost: float, pct: float) -> tuple[float, float, float]:
    """(harga pokok, margin, harga jual) — murni, dibulatkan ke sen."""
    c = _r2(cost)
    m = _r2(c * _f(pct) / 100.0)
    return c, m, _r2(c + m)


async def ensure_margin_account(db) -> str:
    """4-9300 "Penjualan Aksesoris ke CV Sukma (antar CV)" — DA saja; dibuat hanya bila dibutuhkan."""
    code = MARGIN_ACCOUNT["code"]
    acc = await db.rahaza_coa_accounts.find_one({"code": code}, {"_id": 0})
    if acc:
        if acc.get("active") is False:
            await db.rahaza_coa_accounts.update_one({"code": code}, {"$set": {"active": True, "updated_at": _now()}})
        return code
    parent = MARGIN_ACCOUNT["parent_code"]
    if not await db.rahaza_coa_accounts.find_one({"code": parent}, {"_id": 1}):
        parent = None
    await db.rahaza_coa_accounts.insert_one({
        "id": _uid(), "code": code, "name": MARGIN_ACCOUNT["name"], "type": MARGIN_ACCOUNT["type"],
        "parent_code": parent, "is_group": False, "normal_balance": MARGIN_ACCOUNT["normal_balance"],
        "active": True, "entities": [DA], "flags": {"intercompany": True}, "cash_flow_group": "OPR",
        "created_at": _now(), "updated_at": _now(), "created_by": "system", "created_by_name": "Tahap 8 antar CV"})
    return code


async def find_accessory_docs(db, source_ref: str) -> tuple[Optional[dict], Optional[dict]]:
    ar = await db.rahaza_ar_invoices.find_one({"source_module": DOC_ACCESSORY, "ic_source_ref": source_ref,
                                               "status": {"$nin": list(_VOID)}}, {"_id": 0})
    ap = await db.rahaza_ap_invoices.find_one({"source": DOC_ACCESSORY, "ic_source_ref": source_ref,
                                               "status": {"$nin": list(_VOID)}}, {"_id": 0})
    return ar, ap


async def precheck_period(db, d: date, ent: str) -> Optional[str]:
    from routes.rahaza_posting import _period_is_closed
    if await _period_is_closed(db, d, ent):
        return f"Periode {d.strftime('%Y-%m')} {entity_short(ent)} sudah ditutup."
    return None


async def post_accessory_sale(db, *, source_ref: str, je_date: date, credits: dict, memo: str, user: dict,
                              po_id: Optional[str] = None, po_number: str = "", lines_desc: Optional[list] = None,
                              cost_debit_code: Optional[str] = None) -> dict:
    """DA menjual aksesoris/bahan ke CV Sukma untuk PO maklon (idempoten per ``source_ref``):

        buku DA : Dr 1-1301-<CV Sukma> (harga) / Cr persediaan per akun (HPP) [/ Cr 4-9300 margin]
        buku SMU: Dr 5-4100 (HPP) [+ Dr 5-4100 margin, ic_kind=accessory_margin] / Cr 2-1100-<CV DA> (harga)
        dokumen : nota aksesoris DA (``rahaza_ar_invoices``) + tagihan pemasok Sukma (``rahaza_ap_invoices``)

    ``credits`` = {akun persediaan: nilai HPP}. Jurnal DA memakai modul/ref yang SAMA dengan pengeluaran biasa
    (``inventory_issue`` + ``source_ref``) supaya retur & idempotensi lama tetap bekerja."""
    from routes.rahaza_posting import _create_posted_je, _find_existing_je
    from routes.rahaza_posting_profiles import get_mapping
    cost = _r2(sum(_f(v) for v in credits.values()))
    if cost <= 0:
        return {"ok": False, "error": "Nilai aksesoris = 0 (HPP belum diisi)."}
    accs = await ic_accounts(db, user)
    miss = missing_accounts_message(accs, [(DA, "ar"), (SMU, "ap")])
    if miss:
        return {"ok": False, "error": miss}
    exp_code = cost_debit_code or (await get_mapping(db, "inventory_issue") or {}).get("debit_maklon_material")
    if not exp_code:
        return {"ok": False, "error": "Mapping 'inventory_issue.debit_maklon_material' (biaya bahan maklon CV Sukma) "
                                      "belum diisi — lengkapi di Profil Posting."}
    for ent in (DA, SMU):
        err = await precheck_period(db, je_date, ent)
        if err:
            return {"ok": False, "error": err}
    ar_doc, ap_doc = await find_accessory_docs(db, source_ref)
    pct = _f((ar_doc or {}).get("margin_pct")) if ar_doc else await margin_pct(db)
    cost, margin, price = price_split(cost, pct)
    mcode = await ensure_margin_account(db) if margin > 0 else None
    pair = (ar_doc or {}).get("ic_pair_id") or _uid()

    da_je = await _find_existing_je(db, "inventory_issue", source_ref, entity=DA)
    if not da_je:
        da_lines = [{"account_code": accs[DA]["ar"], "debit": price, "credit": 0, "description": memo}]
        rounded = {c: _r2(v) for c, v in credits.items() if _r2(v) > 0}
        if rounded:
            big = max(rounded, key=rounded.get)
            rounded[big] = _r2(rounded[big] + cost - sum(rounded.values()))
        da_lines += [{"account_code": c, "debit": 0, "credit": v, "description": memo} for c, v in rounded.items()]
        if margin > 0:
            da_lines.append({"account_code": mcode, "debit": 0, "credit": margin, "description": f"{memo} — margin",
                             "ic_kind": KIND_MARGIN})
        da_res = await _create_posted_je(db, je_date, memo, "inventory_issue", source_ref, da_lines, user, entity=DA,
                                         labels=ic_labels(SMU, KIND_ACCESSORY, pair))
        if not da_res.get("ok"):
            return da_res
    else:
        da_res = {"ok": True, "je_id": da_je["id"], "je_number": da_je.get("je_number"), "already_posted": True}

    smu_ref = f"icacc:{source_ref}"
    smu_je = await _find_existing_je(db, SRC_ACCESSORY_AP, smu_ref, entity=SMU)
    if not smu_je:
        smu_lines = [{"account_code": exp_code, "debit": cost, "credit": 0, "description": memo}]
        if margin > 0:
            smu_lines.append({"account_code": exp_code, "debit": margin, "credit": 0,
                              "description": f"{memo} — margin CV Dewi Aditya", "ic_kind": KIND_MARGIN})
        smu_lines.append({"account_code": accs[SMU]["ap"], "debit": 0, "credit": price, "description": memo})
        smu_res = await _create_posted_je(db, je_date, memo, SRC_ACCESSORY_AP, smu_ref, smu_lines, user, entity=SMU,
                                          labels=ic_labels(DA, KIND_ACCESSORY, pair))
    else:
        smu_res = {"ok": True, "je_id": smu_je["id"], "je_number": smu_je.get("je_number"), "already_posted": True}

    if not ar_doc:
        number = await _doc_number(db, "rahaza_ar_invoices", "NA-DA", je_date)
        common = {"issue_date": je_date.isoformat(), "invoice_date": je_date.isoformat(),
                  "due_date": (je_date + timedelta(days=30)).isoformat(), "items": lines_desc or [],
                  "subtotal": price, "tax_pct": 0, "tax_amount": 0, "total": price, "paid_amount": 0,
                  "balance": price, "status": "sent", "ic_source_ref": source_ref, "ic_pair_id": pair,
                  "po_id": po_id or "", "po_number": po_number or "", "cost_amount": cost, "margin_amount": margin,
                  "margin_pct": pct, "created_at": _now(), "updated_at": _now(),
                  "created_by": (user or {}).get("id") or "system"}
        cust, supp = accs["records"]["da_customer"], accs["records"]["smu_supplier"]
        ar_doc = {"id": _uid(), "invoice_number": number, "entity": DA, "source_module": DOC_ACCESSORY,
                  **ic_labels(SMU, KIND_ACCESSORY, pair), **common,
                  "customer_id": cust.get("id"), "customer_name": cust.get("name") or entity_name(SMU),
                  "total_amount": price, "amount_paid": 0, "amount_due": price, "gl_ar_account_code": accs[DA]["ar"],
                  "notes": f"Nota aksesoris untuk PO maklon {po_number or '-'} — {IC_LABEL}."}
        ap_doc = {"id": _uid(), "invoice_number": number, "entity": SMU, "source": DOC_ACCESSORY,
                  **ic_labels(DA, KIND_ACCESSORY, pair), **common,
                  "vendor_name": supp.get("name") or entity_name(DA), "vendor_code": supp.get("code") or "",
                  "supplier_id": supp.get("id"), "supplier_code": supp.get("code") or "",
                  "supplier_faktur_number": number, "gl_ap_account_code": accs[SMU]["ap"],
                  "notes": f"Pembelian aksesoris dari CV Dewi Aditya untuk PO maklon {po_number or '-'} — {IC_LABEL}."}
        ar_doc["ic_pair_doc_id"], ap_doc["ic_pair_doc_id"] = ap_doc["id"], ar_doc["id"]
        await db.rahaza_ar_invoices.insert_one(dict(ar_doc))
        await db.rahaza_ap_invoices.insert_one(dict(ap_doc))
    upd = lambda r: ({"gl_je_id": r["je_id"], "gl_je_number": r.get("je_number"), "gl_posted_at": _now(),  # noqa: E731
                      "post_error": None} if r.get("ok") else {"post_error": r.get("error")})
    await db.rahaza_ar_invoices.update_one({"id": ar_doc["id"]}, {"$set": upd(da_res)})
    if ap_doc:
        await db.rahaza_ap_invoices.update_one({"id": ap_doc["id"]}, {"$set": upd(smu_res)})
    out = dict(da_res)
    out.update({"amount": cost, "intercompany": {"nota_number": ar_doc["invoice_number"], "price": price,
                                                  "margin": margin, "margin_pct": pct, "smu_je_number": smu_res.get("je_number"),
                                                  "smu_ok": bool(smu_res.get("ok")), "smu_error": smu_res.get("error")}})
    if not smu_res.get("ok"):
        log.error("[antar-cv] jurnal pasangan nota aksesoris %s di CV Sukma gagal: %s", source_ref, smu_res.get("error"))
    return out


async def reverse_accessory_sale(db, *, source_ref: str, mi_ref: str, je_date: date, debits: dict, memo: str,
                                 user: dict) -> dict:
    """Balikan nota aksesoris saat bahan diretur ke gudang DA (idempoten per ``source_ref`` retur):
        DA : Dr persediaan (HPP) [+ Dr 4-9300 margin] / Cr 1-1301-<CV Sukma> (harga)
        SMU: Dr 2-1100-<CV DA> (harga) / Cr 5-4100 (HPP) [+ Cr 5-4100 margin]
    Margin mengikuti persen di nota asal (``mi_ref`` = ref jurnal pengeluaran)."""
    from routes.rahaza_posting import _create_posted_je, _find_existing_je
    ar_doc, ap_doc = await find_accessory_docs(db, mi_ref)
    cost = _r2(sum(_f(v) for v in debits.values()))
    if cost <= 0:
        return {"ok": True, "skipped": True, "reason": "nilai retur 0"}
    accs = await ic_accounts(db, user)
    pct = _f((ar_doc or {}).get("margin_pct"))
    cost, margin, price = price_split(cost, pct)
    from routes.rahaza_posting_profiles import get_mapping
    exp_code = (await get_mapping(db, "inventory_issue") or {}).get("debit_maklon_material")
    pair = (ar_doc or {}).get("ic_pair_id") or _uid()
    da_je = await _find_existing_je(db, "inventory_issue_return", source_ref, entity=DA)
    if da_je:
        da_res = {"ok": True, "je_id": da_je["id"], "je_number": da_je.get("je_number"), "already_posted": True}
    else:
        lines = [{"account_code": c, "debit": _r2(v), "credit": 0, "description": memo} for c, v in debits.items() if _r2(v) > 0]
        if margin > 0:
            lines.append({"account_code": await ensure_margin_account(db), "debit": margin, "credit": 0,
                          "description": f"{memo} — margin", "ic_kind": KIND_MARGIN})
        lines.append({"account_code": accs[DA]["ar"], "debit": 0, "credit": price, "description": memo})
        da_res = await _create_posted_je(db, je_date, memo, "inventory_issue_return", source_ref, lines, user, entity=DA,
                                         labels=ic_labels(SMU, KIND_ACCESSORY, pair))
        if not da_res.get("ok"):
            return da_res
    smu_ref = f"icacc:{source_ref}"
    if not await _find_existing_je(db, SRC_ACCESSORY_AP, smu_ref, entity=SMU):
        lines = [{"account_code": accs[SMU]["ap"], "debit": price, "credit": 0, "description": memo},
                 {"account_code": exp_code, "debit": 0, "credit": cost, "description": memo}]
        if margin > 0:
            lines.append({"account_code": exp_code, "debit": 0, "credit": margin, "description": f"{memo} — margin",
                          "ic_kind": KIND_MARGIN})
        smu_res = await _create_posted_je(db, je_date, memo, SRC_ACCESSORY_AP, smu_ref, lines, user, entity=SMU,
                                          labels=ic_labels(DA, KIND_ACCESSORY, pair))
        if not smu_res.get("ok"):
            log.error("[antar-cv] jurnal balik nota aksesoris %s di CV Sukma gagal: %s", source_ref, smu_res.get("error"))
        for coll, doc in (("rahaza_ar_invoices", ar_doc), ("rahaza_ap_invoices", ap_doc)):
            if doc:
                total = _r2(max(0.0, _f(doc.get("total")) - price))
                bal = _r2(max(0.0, total - _f(doc.get("paid_amount"))))
                await db[coll].update_one({"id": doc["id"]}, {"$set": {
                    "total": total, "subtotal": total, "balance": bal, "amount_due": bal,
                    **({"total_amount": total} if coll == "rahaza_ar_invoices" else {}),
                    "returned_amount": _r2(_f(doc.get("returned_amount")) + price), "updated_at": _now()},
                    "$push": {"returns": {"ref": source_ref, "amount": price, "cost": cost, "margin": margin,
                                          "date": je_date.isoformat()}}})
    out = dict(da_res)
    out["intercompany"] = {"price": price, "margin": margin}
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 5. PEMBAYARAN ANTAR CV — sisi asal + pasangan otomatis (dibatalkan bila pasangan gagal)
# ══════════════════════════════════════════════════════════════════════════════
KIND_AR, KIND_AP, KIND_CMT = "ar", "ap", "cmt_bill"


def doc_outstanding(kind: str, doc: dict) -> float:
    if kind == KIND_CMT:
        from core.maklon_ledger import cmt_bill_payable
        return cmt_bill_payable(doc)
    if kind == KIND_AR:
        return _r2(max(0.0, _f(doc.get("total")) - _f(doc.get("credited_amount")) - _f(doc.get("paid_amount"))))
    return _r2(max(0.0, _f(doc.get("total")) - _f(doc.get("paid_amount"))))


def doc_entity(kind: str, doc: dict) -> str:
    if kind == KIND_CMT:
        return DA
    return entity_of_value(doc.get("entity"))


async def counterpart_of(db, kind: str, doc: dict) -> tuple[Optional[str], Optional[dict]]:
    """Dokumen pasangan di buku CV lain untuk pembayaran antar CV (None bila bukan dokumen antar CV)."""
    if kind == KIND_CMT:
        return KIND_AR, await find_sewing_ar(db, doc.get("id"))
    if not doc.get("intercompany"):
        return None, None
    if doc.get("ic_kind") == KIND_SEWING and doc.get("ic_bill_id"):
        bill = await db.dewi_cmt_payments.find_one({"id": doc["ic_bill_id"]}, {"_id": 0})
        return KIND_CMT, bill
    if doc.get("ic_kind") == KIND_ACCESSORY and doc.get("ic_pair_doc_id"):
        coll = "rahaza_ap_invoices" if kind == KIND_AR else "rahaza_ar_invoices"
        other = await db[coll].find_one({"id": doc["ic_pair_doc_id"]}, {"_id": 0})
        return (KIND_AP if kind == KIND_AR else KIND_AR), other
    return None, None


async def is_ic_payable(db, kind: str, doc: dict) -> bool:
    if kind == KIND_CMT:
        return bool(await find_sewing_ar(db, (doc or {}).get("id")))
    return bool((doc or {}).get("intercompany")) and (await counterpart_of(db, kind, doc))[1] is not None


async def _cash_account(db, account_id: Optional[str]) -> Optional[dict]:
    if not account_id:
        return None
    return await db.rahaza_cash_accounts.find_one({"id": account_id, "active": {"$ne": False}}, {"_id": 0})


async def _apply_side(db, kind: str, doc: dict, amount: float, acc: dict, pay_date: str, user: dict, labels: dict,
                      notes: str, reference_no: str = "") -> dict:
    """Satu sisi pembayaran (piutang diterima / hutang dibayar / tagihan CMT dibayar). Kembalikan jejak untuk batal."""
    from routes.rahaza_posting import post_ap_payment, post_ar_payment
    coll = {KIND_AR: "rahaza_ar_invoices", KIND_AP: "rahaza_ap_invoices", KIND_CMT: "dewi_cmt_payments"}[kind]
    fresh = await db[coll].find_one({"id": doc["id"]}, {"_id": 0})
    if not fresh:
        raise ValueError("Dokumen pasangan tidak ditemukan.")
    if doc_outstanding(kind, fresh) < amount - 0.01:
        raise ValueError(f"Sisa {'tagihan' if kind != KIND_AR else 'piutang'} {fresh.get('invoice_number') or fresh.get('payment_code')} "
                         f"hanya {fmt_rp(doc_outstanding(kind, fresh))}.")
    old_paid = _f(fresh.get("paid_amount"))
    new_paid = _r2(old_paid + amount)
    total = bill_net_amount(fresh) if kind == KIND_CMT else _f(fresh.get("total"))
    owed = total - (_f(fresh.get("credited_amount")) if kind == KIND_AR else 0)
    status = "paid" if new_paid >= owed - 0.01 else "partial_paid"
    guard = {"id": fresh["id"], "paid_amount": fresh["paid_amount"]} if "paid_amount" in fresh else \
        {"id": fresh["id"], "paid_amount": {"$exists": False}}
    upd = {"paid_amount": new_paid, "status": status, "updated_at": _now()}
    if kind == KIND_CMT:
        upd.update({"outstanding_amount": _r2(total - new_paid), "last_payment_date": pay_date,
                    "paid_at": _now() if status == "paid" else None})
    else:
        bal = _r2(max(0.0, owed - new_paid))
        upd.update({"balance": bal})
        if kind == KIND_AR:
            upd.update({"amount_paid": new_paid, "amount_due": bal, "total_amount": total})
    r = await db[coll].update_one(guard, {"$set": upd})
    if not getattr(r, "matched_count", 1):
        raise ValueError("Dokumen sedang diubah pengguna lain. Muat ulang lalu coba lagi.")
    trail = {"kind": kind, "coll": coll, "doc_id": fresh["id"], "amount": amount, "old_paid": old_paid,
             "old_status": fresh.get("status"), "old_balance": fresh.get("balance"),
             "old_outstanding": fresh.get("outstanding_amount")}
    mv_id = _uid()
    direction = "in" if kind == KIND_AR else "out"
    await db.rahaza_cash_movements.insert_one({
        "id": mv_id, "account_id": acc["id"], "account_name": acc.get("name"), "direction": direction,
        "amount": round(amount), "category": "ar_payment" if kind == KIND_AR else "ap_payment",
        "ref_id": fresh["id"], "ref_label": fresh.get("invoice_number") or fresh.get("payment_code"),
        "source_module": "cmt_payment" if kind == KIND_CMT else None, "date": pay_date, "notes": notes or "",
        **labels, "timestamp": _now(), "created_by": user.get("id"), "created_by_name": user.get("name", "")})
    trail["movement_id"] = mv_id
    if kind == KIND_CMT:
        pseudo = {"id": fresh["id"], "invoice_number": fresh.get("payment_code"), "vendor_name": fresh.get("cmt_name"),
                  "gl_ap_account_code": fresh.get("gl_ap_account_code"), "entity": DA}
        gl = await post_ap_payment(db, pseudo, amount, acc["id"], pay_date, user, movement_id=mv_id, labels=labels)
        trail["je_ref"] = ("ap_payment", f"appay:{mv_id}:{int(round(amount))}")
        pay_doc = {"id": mv_id, "payment_id": fresh["id"], "payment_code": fresh.get("payment_code"),
                   "cmt_name": fresh.get("cmt_name"), "amount": amount, "payment_date": pay_date,
                   "cash_account_id": acc["id"], "cash_account_name": acc.get("name"),
                   "reference_no": reference_no or "", "notes": notes or "", "status": "posted",
                   "gl_je_id": gl.get("je_id"), "gl_je_number": gl.get("je_number"), "post_error": gl.get("error"),
                   **labels, "created_at": _now(), "created_by": user.get("id"), "created_by_name": user.get("name", "")}
        await db.dewi_cmt_disbursements.insert_one(dict(pay_doc))
        trail["payment_coll"], trail["payment_id"] = "dewi_cmt_disbursements", mv_id
    else:
        pcoll = "rahaza_ar_payments" if kind == KIND_AR else "rahaza_ap_payments"
        pay_id = _uid()
        await db[pcoll].insert_one({
            "id": pay_id, "invoice_id": fresh["id"], "invoice_number": fresh.get("invoice_number"),
            "amount": round(amount), "date": pay_date, "account_id": acc["id"], "movement_id": mv_id,
            "notes": notes or "", **labels, "created_at": _now(), "created_by": user.get("id"),
            "created_by_name": user.get("name", "")})
        inv_after = await db[coll].find_one({"id": fresh["id"]}, {"_id": 0})
        poster = post_ar_payment if kind == KIND_AR else post_ap_payment
        gl = await poster(db, inv_after, amount, acc["id"], pay_date, user, movement_id=mv_id, labels=labels)
        trail["je_ref"] = (("ar_payment", f"arpay:{mv_id}:{int(round(amount))}") if kind == KIND_AR
                           else ("ap_payment", f"appay:{mv_id}:{int(round(amount))}"))
        await db[pcoll].update_one({"id": pay_id}, {"$set": {
            "gl_je_id": gl.get("je_id"), "gl_je_number": gl.get("je_number"),
            "post_error": None if gl.get("ok") else gl.get("error")}})
        trail["payment_coll"], trail["payment_id"] = pcoll, pay_id
    trail["gl"] = gl
    trail["entity"] = doc_entity(kind, fresh)
    if not gl.get("ok"):
        raise _SideFailed(trail, gl.get("error") or "jurnal gagal")
    return trail


class _SideFailed(Exception):
    def __init__(self, trail: dict, msg: str):
        super().__init__(msg)
        self.trail = trail


async def _undo_side(db, trail: dict, user: dict) -> None:
    """Batalkan satu sisi pembayaran yang sudah ditulis (dipakai bila pasangannya gagal)."""
    from routes.rahaza_posting import _void_je_by_source
    if not trail:
        return
    if trail.get("je_ref"):
        try:
            await _void_je_by_source(db, trail["je_ref"][0], trail["je_ref"][1], user,
                                     "Pembayaran antar CV dibatalkan (pasangan gagal)", entity=trail.get("entity"))
        except Exception:  # noqa: BLE001
            log.exception("[antar-cv] void jurnal %s gagal", trail.get("je_ref"))
    if trail.get("movement_id"):
        await db.rahaza_cash_movements.delete_one({"id": trail["movement_id"]})
    if trail.get("payment_id"):
        await db[trail["payment_coll"]].update_one({"id": trail["payment_id"]}, {"$set": {
            "status": "voided", "voided_at": _now(), "void_reason": "pasangan antar CV gagal"}})
    restore = {"paid_amount": trail.get("old_paid") or 0, "status": trail.get("old_status"), "updated_at": _now()}
    if trail.get("old_balance") is not None:
        restore["balance"] = trail["old_balance"]
        if trail["kind"] == KIND_AR:
            restore.update({"amount_paid": trail.get("old_paid") or 0, "amount_due": trail["old_balance"]})
    if trail["kind"] == KIND_CMT and trail.get("old_outstanding") is not None:
        restore["outstanding_amount"] = trail["old_outstanding"]
    await db[trail["coll"]].update_one({"id": trail["doc_id"]}, {"$set": restore})


async def settle(db, *, kind: str, doc: dict, amount: float, cash_account_id: str,
                 counter_cash_account_id: Optional[str], pay_date: Optional[str], user: dict, notes: str = "",
                 reference_no: str = "") -> dict:
    """Bayar dokumen antar CV di satu buku + pasangan OTOMATIS di buku CV lain (nilai sama, termasuk cicilan).

    Diperiksa dulu semuanya (rekening dua CV, sisa dua dokumen, periode dua CV); bila pasangan gagal ditulis,
    sisi asal dibatalkan lagi (void jurnal, hapus mutasi kas, kembalikan sisa) supaya dua buku tidak pernah
    timpang. ValueError = pesan untuk pengguna."""
    from utils.waktu import today_wib
    amount = _r2(amount)
    if amount <= 0:
        raise ValueError("Jumlah pembayaran harus lebih dari 0.")
    pay_date = (pay_date or today_wib().isoformat())[:10]
    ent = doc_entity(kind, doc)
    oth = other_entity(ent)
    kind2, doc2 = await counterpart_of(db, kind, doc)
    if not doc2:
        raise ValueError("Dokumen pasangan di buku CV lain belum ada — jalankan sinkron antar CV dulu.")
    acc1 = await _cash_account(db, cash_account_id)
    if not acc1:
        raise ValueError("Rekening kas/bank tidak ditemukan atau nonaktif. Pilih rekening dari daftar.")
    if entity_of_value(acc1.get("entity")) != ent:
        raise ValueError(f"Rekening {acc1.get('name')} milik {entity_short(entity_of_value(acc1.get('entity')))}, "
                         f"bukan {entity_short(ent)}.")
    acc2 = await _cash_account(db, counter_cash_account_id)
    if not acc2:
        raise ValueError(f"Pilih rekening {entity_short(oth)} yang {'menerima' if kind != KIND_AR else 'membayar'} "
                         "uang ini — pasangan di buku CV lain dibuat otomatis.")
    if entity_of_value(acc2.get("entity")) != oth:
        raise ValueError(f"Rekening pasangan {acc2.get('name')} harus milik {entity_short(oth)}.")
    if doc_outstanding(kind, doc) < amount - 0.01:
        raise ValueError(f"Bisa dibayar paling banyak {fmt_rp(doc_outstanding(kind, doc))}.")
    if doc_outstanding(kind2, doc2) < amount - 0.01:
        raise ValueError(f"Sisa dokumen pasangan di {entity_short(oth)} hanya {fmt_rp(doc_outstanding(kind2, doc2))} "
                         "— periksa Laporan Saldo antar CV.")
    for e in (ent, oth):
        err = await precheck_period(db, _to_date(pay_date), e)
        if err:
            raise ValueError(err)
    pair = _uid()
    t1 = None
    try:
        t1 = await _apply_side(db, kind, doc, amount, acc1, pay_date, user, ic_labels(oth, KIND_PAYMENT, pair), notes,
                               reference_no)
        t2 = await _apply_side(db, kind2, doc2, amount, acc2, pay_date, user, ic_labels(ent, KIND_PAYMENT, pair),
                               (notes or "") + f" · pasangan otomatis dari {entity_short(ent)}", reference_no)
    except _SideFailed as e:
        await _undo_side(db, e.trail, user)
        if t1 and e.trail is not t1:
            await _undo_side(db, t1, user)
        raise ValueError(f"Pembayaran antar CV dibatalkan: {e}") from None
    except ValueError:
        if t1:
            await _undo_side(db, t1, user)
        raise
    for t in (t1, t2):
        await db[t["payment_coll"]].update_one({"id": t["payment_id"]}, {"$set": {
            "ic_pair_payment_id": (t2 if t is t1 else t1)["payment_id"],
            "ic_pair_payment_coll": (t2 if t is t1 else t1)["payment_coll"]}})
    if kind2 == KIND_CMT or kind == KIND_CMT:
        bill_id = doc["id"] if kind == KIND_CMT else doc2["id"]
        try:
            from core.maklon_ledger import refresh_ap_schedules
            bill = await db.dewi_cmt_payments.find_one({"id": bill_id}, {"_id": 0, "po_id": 1})
            if (bill or {}).get("po_id"):
                await refresh_ap_schedules(db, bill["po_id"], user)
        except Exception:  # noqa: BLE001
            log.exception("[antar-cv] segarkan jadwal hutang gagal")
    return {"ok": True, "pair_id": pair, "amount": amount,
            "origin": {"kind": kind, "entity": ent, "payment_id": t1["payment_id"], "je_number": t1["gl"].get("je_number"),
                       "je_id": t1["gl"].get("je_id"), "movement_id": t1["movement_id"]},
            "mirror": {"kind": kind2, "entity": oth, "payment_id": t2["payment_id"], "je_number": t2["gl"].get("je_number"),
                       "doc_id": doc2["id"], "doc_number": doc2.get("invoice_number") or doc2.get("payment_code")}}


async def void_pair_of(db, pay_doc: dict, user: dict) -> Optional[dict]:
    """Pembayaran antar CV dibatalkan di satu buku → pasangannya di buku CV lain ikut dibatalkan (void jurnal,
    hapus mutasi kas, sisa dokumen dikembalikan). None bila pembayaran itu bukan pembayaran antar CV."""
    from routes.rahaza_posting import _void_je_by_source
    coll, pid = (pay_doc or {}).get("ic_pair_payment_coll"), (pay_doc or {}).get("ic_pair_payment_id")
    if not coll or not pid:
        return None
    p = await db[coll].find_one({"id": pid, "status": {"$ne": "voided"}}, {"_id": 0})
    if not p:
        return None
    amt = _r2(p.get("amount"))
    if coll == "dewi_cmt_disbursements":
        kind, dcoll, doc_id, mv = KIND_CMT, "dewi_cmt_payments", p.get("payment_id"), p.get("id")
        je = ("ap_payment", f"appay:{mv}:{int(round(amt))}")
    elif coll == "rahaza_ar_payments":
        kind, dcoll, doc_id, mv = KIND_AR, "rahaza_ar_invoices", p.get("invoice_id"), p.get("movement_id")
        je = ("ar_payment", f"arpay:{mv}:{int(round(amt))}")
    else:
        kind, dcoll, doc_id, mv = KIND_AP, "rahaza_ap_invoices", p.get("invoice_id"), p.get("movement_id")
        je = ("ap_payment", f"appay:{mv}:{int(round(amt))}")
    doc = await db[dcoll].find_one({"id": doc_id}, {"_id": 0}) or {}
    ent = doc_entity(kind, doc) if doc else None
    v = await _void_je_by_source(db, je[0], je[1], user, "Pembayaran antar CV dibatalkan", entity=ent)
    if not v.get("ok"):
        raise ValueError(f"Jurnal pasangan tidak bisa dibatalkan: {v.get('error')}")
    if mv:
        await db.rahaza_cash_movements.delete_one({"id": mv})
    await db[coll].update_one({"id": pid}, {"$set": {"status": "voided", "voided_at": _now(),
                                                    "voided_by": (user or {}).get("id")}})
    if doc:
        paid = _r2(max(0.0, _f(doc.get("paid_amount")) - amt))
        total = bill_net_amount(doc) if kind == KIND_CMT else _f(doc.get("total"))
        owed = total - (_f(doc.get("credited_amount")) if kind == KIND_AR else 0)
        status = "paid" if paid >= owed - 0.01 and paid > 0 else ("partial_paid" if paid > 0 else
                                                                   ("posted" if kind == KIND_CMT else "sent"))
        upd = {"paid_amount": paid, "status": status, "updated_at": _now()}
        if kind == KIND_CMT:
            upd.update({"outstanding_amount": _r2(total - paid), "paid_at": None})
        else:
            bal = _r2(max(0.0, owed - paid))
            upd["balance"] = bal
            if kind == KIND_AR:
                upd.update({"amount_paid": paid, "amount_due": bal})
        await db[dcoll].update_one({"id": doc_id}, {"$set": upd})
    return {"ok": True, "voided_payment_id": pid, "je_number": v.get("je_number")}


# ══════════════════════════════════════════════════════════════════════════════
# 6. TRANSAKSI ANTAR CV (talangan, pinjaman, uang nyasar, pelunasan)
# ══════════════════════════════════════════════════════════════════════════════
# dir: give    = CV asal memberi nilai (CV lain berutang):  asal Dr piutang-CV-lain / Cr akun asal;
#                                                           lain Dr akun lain / Cr hutang-ke-asal
#      receive = CV asal menerima untuk CV lain (asal berutang): asal Dr akun asal / Cr hutang-ke-lain;
#                                                           lain Dr piutang-atas-asal / Cr akun lain
#      settle  = CV asal melunasi utangnya:                 asal Dr hutang-ke-lain / Cr akun asal;
#                                                           lain Dr akun lain / Cr piutang-atas-asal
#      collect = CV asal menerima pelunasan piutangnya:     asal Dr akun asal / Cr piutang-atas-lain;
#                                                           lain Dr hutang-ke-asal / Cr akun lain
TXN_KINDS = {
    "talangan": {"dir": "give", "label": "Talangan — CV asal membayarkan biaya CV lain",
                 "src_hint": "rekening yang membayar", "oth_hint": "akun biaya CV lain"},
    "pinjaman": {"dir": "give", "label": "Pinjaman — CV asal meminjamkan uang ke CV lain",
                 "src_hint": "rekening pemberi pinjaman", "oth_hint": "rekening penerima pinjaman"},
    "uang_nyasar": {"dir": "receive", "label": "Uang nyasar — uang milik CV lain masuk ke rekening CV asal",
                    "src_hint": "rekening yang menerima uang", "oth_hint": "akun lawan di CV lain (mis. piutang klien)"},
    "pelunasan": {"dir": "settle", "label": "Pelunasan — CV asal melunasi utangnya ke CV lain",
                  "src_hint": "rekening yang membayar", "oth_hint": "rekening yang menerima"},
    "terima_pelunasan": {"dir": "collect", "label": "Terima pelunasan — CV lain melunasi utangnya ke CV asal",
                         "src_hint": "rekening yang menerima", "oth_hint": "rekening yang membayar"},
}


def txn_lines(direction: str, *, amount: float, src_code: str, oth_code: str, src_ar: str, src_ap: str,
              oth_ar: str, oth_ap: str, memo: str) -> tuple[list, list]:
    """Baris jurnal dua buku untuk satu transaksi antar CV (murni). ``src_ar`` = piutang CV asal atas CV lain,
    ``src_ap`` = hutang CV asal ke CV lain, ``oth_ar``/``oth_ap`` = sama dari sisi CV lain."""
    a = _r2(amount)

    def j(dr, cr):
        return [{"account_code": dr, "debit": a, "credit": 0, "description": memo},
                {"account_code": cr, "debit": 0, "credit": a, "description": memo}]
    if direction == "give":
        return j(src_ar, src_code), j(oth_code, oth_ap)
    if direction == "receive":
        return j(src_code, src_ap), j(oth_ar, oth_code)
    if direction == "settle":
        return j(src_ap, src_code), j(oth_code, oth_ar)
    if direction == "collect":
        return j(src_code, src_ar), j(oth_ap, oth_code)
    raise ValueError(f"Arah transaksi '{direction}' tidak dikenal.")


def needed_accounts(direction: str, src: str) -> list:
    oth = other_entity(src)
    return {"give": [(src, "ar"), (oth, "ap")], "receive": [(src, "ap"), (oth, "ar")],
            "settle": [(src, "ap"), (oth, "ar")], "collect": [(src, "ar"), (oth, "ap")]}[direction]


async def _account_for_book(db, code: str, ent: str, ic_codes: set, what: str) -> dict:
    from core.entities import validate_manual_lines
    code = str(code or "").strip()
    if not code:
        raise ValueError(f"Pilih {what}.")
    acc = await db.rahaza_coa_accounts.find_one({"code": code, "active": {"$ne": False}}, {"_id": 0})
    if not acc:
        raise ValueError(f"Akun {code} tidak ditemukan atau nonaktif.")
    if acc.get("is_group"):
        raise ValueError(f"Akun {code} adalah akun kelompok — pilih akun rinci.")
    if code in ic_codes:
        raise ValueError(f"Akun {code} adalah akun antar CV — dipakai otomatis; pilih akun biaya/bank/lainnya.")
    from fastapi import HTTPException
    try:
        await validate_manual_lines(db, [{"account_code": code}], ent, what=what[:1].upper() + what[1:])
    except HTTPException as e:
        raise ValueError(str(e.detail)) from None
    return acc


async def create_transaction(db, body: dict, src: str, user: dict) -> dict:
    """Satu transaksi antar CV → dua jurnal berlabel (buku asal + buku CV lain), atomik & idempoten."""
    from routes.rahaza_posting import _create_posted_je, _find_existing_je, _void_je_by_source
    from utils.counters import gen_prefixed_number
    from utils.waktu import today_wib
    kind = str(body.get("kind") or "").strip()
    if kind not in TXN_KINDS:
        raise ValueError("Pilih jenis transaksi antar CV.")
    direction = TXN_KINDS[kind]["dir"]
    try:
        amount = _r2(float(body.get("amount") or 0))
    except (TypeError, ValueError):
        raise ValueError("Jumlah harus angka.") from None
    if amount <= 0:
        raise ValueError("Jumlah harus lebih dari 0.")
    desc = str(body.get("description") or "").strip()
    if len(desc) < 3:
        raise ValueError("Isi keterangan (minimal 3 huruf), mis. 'talangan listrik Oktober'.")
    d = _to_date(body.get("date") or today_wib().isoformat())
    src = entity_of_value(src)
    oth = other_entity(src)
    key = str(body.get("client_ref") or "").strip()[:64]
    if key:
        dup = await db[TXN_COLL].find_one({"client_ref": key, "status": {"$ne": "voided"}}, {"_id": 0})
        if dup:
            return {**dup, "already": True}
    accs = await ic_accounts(db, user)
    miss = missing_accounts_message(accs, needed_accounts(direction, src))
    if miss:
        raise ValueError(miss)
    ic_codes = {c for b in (DA, SMU) for c in (accs[b] or {}).values() if c}
    src_acc = await _account_for_book(db, body.get("source_account_code"), src, ic_codes,
                                      f"akun {entity_short(src)} ({TXN_KINDS[kind]['src_hint']})")
    oth_acc = await _account_for_book(db, body.get("other_account_code"), oth, ic_codes,
                                      f"akun {entity_short(oth)} ({TXN_KINDS[kind]['oth_hint']})")
    for e in (src, oth):
        err = await precheck_period(db, d, e)
        if err:
            raise ValueError(err)
    number = await gen_prefixed_number(db, TXN_COLL, "number", f"ICT-{d.strftime('%Y%m%d')}-", 3)
    tid = _uid()
    memo = f"{IC_LABEL.capitalize()} {number} · {TXN_KINDS[kind]['label'].split(' — ')[0]} · {desc}"
    src_lines, oth_lines = txn_lines(direction, amount=amount, src_code=src_acc["code"], oth_code=oth_acc["code"],
                                     src_ar=ar_code(accs, src), src_ap=ap_code(accs, src),
                                     oth_ar=ar_code(accs, oth), oth_ap=ap_code(accs, oth), memo=memo)
    ref = f"ictx:{tid}"
    r1 = await _create_posted_je(db, d, memo, SRC_TXN, ref, src_lines, user, entity=src,
                                 labels=ic_labels(oth, KIND_TXN, tid))
    if not r1.get("ok"):
        raise ValueError(f"Jurnal {entity_short(src)} gagal: {r1.get('error')}")
    r2 = await _create_posted_je(db, d, memo, SRC_TXN, ref, oth_lines, user, entity=oth,
                                 labels=ic_labels(src, KIND_TXN, tid))
    if not r2.get("ok"):
        await _void_je_by_source(db, SRC_TXN, ref, user, "pasangan antar CV gagal", entity=src)
        raise ValueError(f"Jurnal pasangan {entity_short(oth)} gagal: {r2.get('error')} — transaksi dibatalkan.")
    if not await _find_existing_je(db, SRC_TXN, ref, entity=oth):
        log.warning("[antar-cv] pasangan %s tidak terbaca ulang", ref)
    doc = {"id": tid, "number": number, "kind": kind, "kind_label": TXN_KINDS[kind]["label"], "direction": direction,
           "source_entity": src, "other_entity": oth, "date": d.isoformat(), "amount": amount, "description": desc,
           "source_account_code": src_acc["code"], "source_account_name": src_acc.get("name"),
           "other_account_code": oth_acc["code"], "other_account_name": oth_acc.get("name"),
           "source_ic_account": src_lines[0]["account_code"] if direction in ("give", "settle") else src_lines[1]["account_code"],
           "other_ic_account": oth_lines[1]["account_code"] if direction in ("give", "settle") else oth_lines[0]["account_code"],
           "source_je_id": r1["je_id"], "source_je_number": r1.get("je_number"),
           "other_je_id": r2["je_id"], "other_je_number": r2.get("je_number"),
           "status": "posted", "intercompany": True, "client_ref": key or None,
           "created_at": _now(), "created_by": user.get("id"), "created_by_name": user.get("name", "")}
    await db[TXN_COLL].insert_one(dict(doc))
    return doc


async def void_transaction(db, tid: str, user: dict, reason: str = "") -> dict:
    from routes.rahaza_posting import _void_je_by_source
    t = await db[TXN_COLL].find_one({"id": tid}, {"_id": 0})
    if not t:
        raise ValueError("Transaksi antar CV tidak ditemukan.")
    if t.get("status") == "voided":
        return t
    for e in (t["source_entity"], t["other_entity"]):
        err = await precheck_period(db, _to_date(t.get("date")), e)
        if err:
            raise ValueError(err)
    for e in (t["source_entity"], t["other_entity"]):
        res = await _void_je_by_source(db, SRC_TXN, f"ictx:{tid}", user, reason or "dibatalkan", entity=e)
        if not res.get("ok"):
            raise ValueError(res.get("error") or "Jurnal tidak bisa dibatalkan.")
    await db[TXN_COLL].update_one({"id": tid}, {"$set": {"status": "voided", "voided_at": _now(),
                                                         "voided_by": user.get("id"), "void_reason": reason}})
    return await db[TXN_COLL].find_one({"id": tid}, {"_id": 0})


# ══════════════════════════════════════════════════════════════════════════════
# 7. LAPORAN SALDO ANTAR CV + ELIMINASI GABUNGAN (fase 3)
# ══════════════════════════════════════════════════════════════════════════════
def _date_q(from_date: Optional[str], to_date: Optional[str]) -> dict:
    q = {}
    if from_date:
        q["$gte"] = from_date
    if to_date:
        q["$lte"] = to_date
    return {"date": q} if q else {}


async def _lines(db, code: Optional[str], ent: str, *, from_date=None, to_date=None, extra: Optional[dict] = None) -> list:
    if not code:
        return []
    q = {"account_code": code, **entity_match(ent), **_date_q(from_date, to_date), **(extra or {})}
    return [ln async for ln in db.rahaza_journal_lines.find(q, {"_id": 0})]


def _net(lines: list, side: str) -> float:
    """Saldo normal: side='debit' → Σdebit−Σkredit; 'credit' → sebaliknya."""
    d = sum(_f(ln.get("debit")) for ln in lines)
    c = sum(_f(ln.get("credit")) for ln in lines)
    return _r2(d - c if side == "debit" else c - d)


PAIRS = (
    {"key": "da_to_smu", "label": "Hutang CV Dewi Aditya ke CV Sukma ↔ Piutang CV Sukma atas CV Dewi Aditya",
     "hint": "jasa jahit tim CV Sukma, uang nyasar, pinjaman dari CV Sukma",
     "left": (DA, "ap", "credit", "Hutang di buku CV Dewi Aditya"),
     "right": (SMU, "ar", "debit", "Piutang di buku CV Sukma")},
    {"key": "smu_to_da", "label": "Piutang CV Dewi Aditya atas CV Sukma ↔ Hutang CV Sukma ke CV Dewi Aditya",
     "hint": "nota aksesoris, talangan & pinjaman dari CV Dewi Aditya",
     "left": (DA, "ar", "debit", "Piutang di buku CV Dewi Aditya"),
     "right": (SMU, "ap", "credit", "Hutang di buku CV Sukma")},
)


async def balance_report(db, as_of: str, *, with_lines: bool = True, accs: Optional[dict] = None) -> dict:
    """Saldo antar CV per pasangan per tanggal: dua sisi harus sama; selisih + rincian baris jurnal."""
    accs = accs or await ic_accounts(db, create=False)
    out = []
    for p in PAIRS:
        sides = {}
        for pos in ("left", "right"):
            ent, k, side, label = p[pos]
            code = (accs.get(ent) or {}).get(k)
            lines = await _lines(db, code, ent, to_date=as_of)
            sides[pos] = {"entity": ent, "entity_label": entity_short(ent), "account_code": code, "label": label,
                          "balance": _net(lines, side), "line_count": len(lines)}
            if with_lines:
                lines.sort(key=lambda x: (str(x.get("date")), str(x.get("je_number"))))
                sides[pos]["lines"] = [{"date": ln.get("date"), "je_number": ln.get("je_number"),
                                        "description": ln.get("description"), "debit": _r2(ln.get("debit")),
                                        "credit": _r2(ln.get("credit")), "ic_kind": ln.get("ic_kind"),
                                        "intercompany": bool(ln.get("intercompany")),
                                        "source_module": ln.get("source_module")} for ln in lines[-500:]]
        diff = _r2(sides["left"]["balance"] - sides["right"]["balance"])
        out.append({"key": p["key"], "label": p["label"], "hint": p["hint"], **sides, "difference": diff,
                    "balanced": abs(diff) < 0.5})
    return {"as_of": as_of, "pairs": out, "balanced": all(x["balanced"] for x in out),
            "accounts": {DA: accs.get(DA), SMU: accs.get(SMU)}, "vendor": accs.get("vendor")}


def _add(elim: dict, code: Optional[str], debit: float = 0.0, credit: float = 0.0) -> None:
    if not code or (abs(debit) < 0.005 and abs(credit) < 0.005):
        return
    e = elim.setdefault(code, {"debit": 0.0, "credit": 0.0})
    e["debit"] = _r2(e["debit"] + debit)
    e["credit"] = _r2(e["credit"] + credit)


async def bs_elimination(db, as_of: str, accs: Optional[dict] = None) -> dict:
    """Eliminasi saldo hutang/piutang antar CV per tanggal (dua sisi dikurangi nilai yang SAMA → neraca tetap
    seimbang). Sisa yang tidak cocok = catatan "Selisih antar CV yang belum tereliminasi"."""
    accs = accs or await ic_accounts(db, create=False)
    rep = await balance_report(db, as_of, with_lines=False, accs=accs)
    elim, notes = {}, []
    for p in rep["pairs"]:
        lb, rb = p["left"]["balance"], p["right"]["balance"]
        if lb > 0 and rb > 0:
            e = _r2(min(lb, rb))
        elif lb < 0 and rb < 0:
            e = _r2(max(lb, rb))
        else:
            e = 0.0
        for pos in ("left", "right"):
            s = p[pos]
            if not s["account_code"] or not e:
                continue
            side = PAIRS[0][pos][2] if p["key"] == "da_to_smu" else PAIRS[1][pos][2]
            # saldo normal debit (piutang) dikurangi lewat kredit; saldo normal kredit (hutang) lewat debit
            if side == "debit":
                _add(elim, s["account_code"], credit=e) if e > 0 else _add(elim, s["account_code"], debit=-e)
            else:
                _add(elim, s["account_code"], debit=e) if e > 0 else _add(elim, s["account_code"], credit=-e)
        if not p["balanced"]:
            notes.append({"key": p["key"], "label": f"{UNRECONCILED_LABEL}: {fmt_rp(abs(p['difference']))}",
                          "amount": abs(p["difference"]),
                          "detail": f"{p['label']} — {p['left']['label']} {fmt_rp(lb)} vs {p['right']['label']} "
                                    f"{fmt_rp(rb)}. Periksa Laporan Saldo antar CV."})
    return {"lines": elim, "notes": notes, "pairs": rep["pairs"]}


async def pl_elimination(db, from_date: Optional[str], to_date: Optional[str], accs: Optional[dict] = None) -> dict:
    """Eliminasi laba rugi antar CV untuk satu rentang:
      * margin aksesoris: 4-9300 (DA) ↔ bagian margin 5-4100 (SMU, ``ic_kind=accessory_margin``) — persis;
      * jasa jahit: pendapatan Sukma 4-1500-<DA> ↔ biaya yang DA kapitalisasi ke persediaan (WIP → barang jadi →
        HPP saat terjual). Tidak bisa dicocokkan per baris → TIDAK dieliminasi, ditampilkan sebagai catatan
        "Selisih antar CV yang belum tereliminasi" (bukan disembunyikan)."""
    accs = accs or await ic_accounts(db, create=False)
    elim, notes = {}, []
    m_da_lines = await _lines(db, MARGIN_ACCOUNT["code"], DA, from_date=from_date, to_date=to_date)
    m_da = _net(m_da_lines, "credit")
    m_smu_lines = [ln async for ln in db.rahaza_journal_lines.find(
        {"ic_kind": KIND_MARGIN, **entity_match(SMU), **_date_q(from_date, to_date)}, {"_id": 0})]
    by_code: dict = {}
    for ln in m_smu_lines:
        by_code[ln["account_code"]] = by_code.get(ln["account_code"], 0.0) + _f(ln.get("debit")) - _f(ln.get("credit"))
    m_smu = _r2(sum(by_code.values()))
    e = _r2(min(m_da, m_smu)) if m_da > 0 and m_smu > 0 else 0.0
    if e:
        _add(elim, MARGIN_ACCOUNT["code"], debit=e)
        rest = e
        for code, v in sorted(by_code.items(), key=lambda kv: -kv[1]):
            take = _r2(min(rest, v))
            if take > 0:
                _add(elim, code, credit=take)
                rest = _r2(rest - take)
    if abs(m_da - m_smu) >= 0.5:
        notes.append({"key": "accessory_margin", "amount": _r2(abs(m_da - m_smu)),
                      "label": f"{UNRECONCILED_LABEL}: {fmt_rp(abs(m_da - m_smu))}",
                      "detail": f"Margin aksesoris di CV Dewi Aditya {fmt_rp(m_da)} vs bagian margin di biaya bahan "
                                f"CV Sukma {fmt_rp(m_smu)}."})
    rev = (accs.get(SMU) or {}).get("revenue")
    sew = _net(await _lines(db, rev, SMU, from_date=from_date, to_date=to_date), "credit") if rev else 0.0
    if abs(sew) >= 0.5:
        notes.append({"key": "sewing", "amount": sew, "label": f"{UNRECONCILED_LABEL}: {fmt_rp(sew)}",
                      "detail": ("Pendapatan jasa jahit CV Sukma dari CV Dewi Aditya. Di buku CV Dewi Aditya biayanya "
                                 "masuk persediaan (barang dalam proses → barang jadi → HPP saat terjual), jadi tidak "
                                 "bisa dicocokkan baris per baris. Laba gabungan masih memuat bagian ini sampai barangnya "
                                 "terjual.")})
    return {"lines": elim, "notes": notes, "accessory_margin_da": m_da, "accessory_margin_smu": m_smu,
            "sewing_revenue": sew}


def apply_elimination(per_acc: dict, elim_lines: dict, sign: int = 1) -> dict:
    """Tambahkan baris eliminasi ke agregat {akun: {debit, credit}} (murni; ``sign=-1`` untuk membalik)."""
    out = {k: dict(v) for k, v in (per_acc or {}).items()}
    for code, v in (elim_lines or {}).items():
        cur = out.setdefault(code, {"_id": code, "debit": 0.0, "credit": 0.0})
        cur["debit"] = _r2(_f(cur.get("debit")) + sign * _f(v.get("debit")))
        cur["credit"] = _r2(_f(cur.get("credit")) + sign * _f(v.get("credit")))
    return out


def merge_elims(*elims: dict) -> dict:
    out: dict = {}
    for el in elims:
        for code, v in (el or {}).items():
            _add(out, code, debit=_f(v.get("debit")), credit=_f(v.get("credit")))
    return out


async def consolidation(db, *, from_date: Optional[str], to_date: str, include_bs: bool = True) -> dict:
    """Paket eliminasi Gabungan: baris eliminasi (BS per ``to_date`` + L/R rentang) + catatan untuk layar."""
    accs = await ic_accounts(db, create=False)
    pl = await pl_elimination(db, from_date, to_date, accs)
    bs = await bs_elimination(db, to_date, accs) if include_bs else {"lines": {}, "notes": []}
    lines = merge_elims(bs["lines"], pl["lines"])
    rows = [{"code": c, "debit": v["debit"], "credit": v["credit"]} for c, v in sorted(lines.items())]
    return {"lines": lines, "rows": rows, "notes": bs["notes"] + pl["notes"],
            "unreconciled_total": _r2(sum(_f(n.get("amount")) for n in bs["notes"] + pl["notes"])),
            "label": "Gabungan setelah eliminasi antar CV"}


def is_all(entity) -> bool:
    return str(entity or "").upper() == ALL


def net_of(lines: dict) -> dict:
    """{akun: {debit, credit}} → {akun: debit − credit} (murni)."""
    return {c: _r2(_f(v.get("debit")) - _f(v.get("credit"))) for c, v in (lines or {}).items()}


async def elimination_net(db, as_of: Optional[str]) -> dict:
    """Eliminasi KUMULATIF sampai ``as_of`` (neraca per tanggal + laba rugi seluruh histori) sebagai netto per akun.
    Dipakai laporan berkolom (neraca saldo, neraca 12 bulan) supaya saldo awal + mutasi = saldo akhir."""
    if not as_of:
        return {}
    c = await consolidation(db, from_date=None, to_date=as_of)
    return net_of(c["lines"])


def split_net(net: float) -> dict:
    n = _r2(net)
    return {"debit": n, "credit": 0.0} if n >= 0 else {"debit": 0.0, "credit": -n}


def ic_report_block(c: dict) -> dict:
    """Bagian `intercompany` pada respons laporan Gabungan (untuk layar)."""
    return {"eliminated": True, "label": c.get("label"), "rows": c.get("rows") or [], "notes": c.get("notes") or [],
            "unreconciled_total": c.get("unreconciled_total") or 0.0}
