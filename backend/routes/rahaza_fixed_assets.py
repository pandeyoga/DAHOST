"""
CV. Dewi Aditya ERP — Fixed Asset & Depreciation (Session 11)

Endpoints (prefix /api/rahaza/finance):
  GET    /fixed-assets                   — list aset tetap
  POST   /fixed-assets                   — daftarkan aset baru
  GET    /fixed-assets/{id}              — detail + jadwal depresiasi
  PUT    /fixed-assets/{id}              — update
  POST   /fixed-assets/{id}/dispose      — disposal aset
  GET    /fixed-assets/{id}/schedule     — jadwal depresiasi lengkap
  POST   /fixed-assets/{id}/post-depr/{period} — posting depresiasi periode YYYY-MM
  GET    /fixed-assets/depreciation-due  — daftar aset perlu posting depresiasi
  GET    /fixed-assets-summary           — ringkasan portfolio (total cost, NBV, akumulasi)

Koleksi: rahaza_fixed_assets, rahaza_depr_schedules
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc
from routes.shared import get_pagination_params, paginated_response
from datetime import datetime, timezone, date
from dateutil.relativedelta import relativedelta
from typing import Optional
import uuid
import logging
from routes.shared import require_portal_dep  # FIN-04
from utils.waktu import today_wib

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rahaza/finance", tags=["rahaza-fixed-assets"],
                   dependencies=[Depends(require_portal_dep("finance"))])  # FIN-04

def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)

ASSET_CATEGORIES = ["tanah", "bangunan", "mesin", "kendaraan", "peralatan", "it", "furnitur", "lain-lain"]
DEPR_METHODS    = ["straight_line", "double_declining", "none", "manual"]  # Phase 8B: added "none" & "manual"
DEPRECIATING_METHODS = ("straight_line", "double_declining")

# 2026-11-02 (K18, keputusan owner): SATU registri induk aset tetap = koleksi ini (Keuangan).
# Portal Aset (`dewi_assets`, routes/asset/*) hanya tampilan operasional yang menaut `fixed_asset_id`;
# jalur GR aset (warehouse.py) mendaftar lewat `register_fixed_asset` yang sama. Form wajib memilih:
#   · "purchase" (Pembelian baru) → sumber dana wajib → jurnal perolehan otomatis ke akun kategori;
#   · "opening"  (Aset lama/saldo awal) → akumulasi per tanggal go-live, TANPA jurnal perolehan
#     (nilainya sudah masuk jurnal Saldo Awal), jadwal penyusutan mulai bulan go-live.
ACQUISITION_TYPES = ("purchase", "opening")
FUNDING_SOURCES = {
    "cash": "Rekening kas/bank",
    "payable": "Hutang pemasok — faktur menyusul (Hutang Belum Ditagih)",
    "ap_invoice": "Faktur pemasok yang sudah dicatat",
    "grni": "Penerimaan barang (GR) — Hutang Belum Ditagih",   # hanya jalur GR (warehouse.py)
}
# Akun bawaan per kategori (kode COA seed DA: aset, akumulasi, beban penyusutan). Dipakai bila akun di
# form dikosongkan; None / kode tidak aktif → profil posting (`asset_acquisition` / `depreciation`).
CATEGORY_ACCOUNTS = {
    "tanah":     ("1-2100", None, None),
    "bangunan":  ("1-2200", "1-2201", "6-2710"),
    "mesin":     ("1-2300", "1-2301", None),
    "kendaraan": ("1-2400", "1-2401", "6-2720"),
    "peralatan": ("1-2500", "1-2501", "6-2730"),
    "it":        ("1-2500", "1-2501", "6-2730"),
    "furnitur":  ("1-2500", "1-2501", "6-2730"),
    "lain-lain": ("1-2500", "1-2501", None),
}
_ACCOUNT_FIELDS = ("account_id_asset", "account_id_accum_depr", "account_id_depr_expense")


def _months_between(a: date, b: date) -> int:
    """Jumlah bulan kalender dari bulan `a` ke bulan `b` (b − a), bisa negatif."""
    return (b.year - a.year) * 12 + (b.month - a.month)


# ─── HELPER: generate depreciation schedule ────────────────────────────────

def _generate_schedule(asset: dict) -> list:
    """
    Generate monthly depreciation schedule for the asset.
    Returns list of {period, depr_amount, accumulated_depr, book_value_start, book_value_end}

    2026-11-02 (K18): aset lama (`acquisition_type=opening`) — jadwal MULAI bulan go-live dengan
    nilai buku awal = harga − akumulasi per go-live, sisa umur = umur − bulan yang sudah lewat
    (bulan beli s.d. sebelum bulan go-live). `accumulated_depr` jadwal = akumulasi kumulatif TERMASUK
    akumulasi awal. Umur 0 tidak lagi diam-diam menjadi 12/60 bulan (jadwal kosong).
    """
    cost       = float(asset.get("purchase_cost") or 0)
    residual   = float(asset.get("residual_value") or 0)
    useful_life = int(asset.get("useful_life_months") or 0)
    method      = asset.get("depreciation_method", "straight_line")
    start_date_str = asset.get("purchase_date") or today_wib().isoformat()
    try:
        start_date = date.fromisoformat(start_date_str[:10])
    except ValueError:
        start_date = today_wib()
    # Start depreciation from the month AFTER purchase (or first day of purchase month)
    depr_start = date(start_date.year, start_date.month, 1)

    schedule = []
    book_value = cost
    accumulated = 0.0
    if asset.get("acquisition_type") == "opening":
        try:
            golive = date.fromisoformat(str(asset.get("golive_date"))[:10])
        except ValueError:
            golive = today_wib()
        elapsed = max(0, _months_between(depr_start, date(golive.year, golive.month, 1)))
        depr_start = date(golive.year, golive.month, 1)
        accumulated = round(float(asset.get("opening_accumulated_depr") or 0), 2)
        book_value = round(cost - accumulated, 2)
        remaining = useful_life - elapsed
        if remaining <= 0 or book_value <= residual:
            return []
        if method == "straight_line":
            monthly = round((book_value - residual) / remaining, 2)
            for i in range(remaining):
                bv_start = round(book_value, 2)
                depr_amt = round(min(monthly, max(0, book_value - residual)), 2)
                if i == remaining - 1:  # bulan terakhir: tutup ke nilai residu (sisa pembulatan)
                    depr_amt = max(0, round(book_value - residual, 2))
                accumulated = round(accumulated + depr_amt, 2)
                book_value = round(book_value - depr_amt, 2)
                schedule.append({"period": (depr_start + relativedelta(months=i)).strftime("%Y-%m"),
                                 "book_value_start": bv_start, "depr_amount": depr_amt,
                                 "accumulated_depr": accumulated, "book_value_end": book_value})
            return schedule
        useful_life = remaining  # double_declining: tarif 2/umur sisa dari nilai buku go-live
    if method == "straight_line":
        monthly_depr = round((cost - residual) / useful_life, 2) if useful_life > 0 else 0
        for i in range(useful_life):
            period_date = depr_start + relativedelta(months=i)
            period_str  = period_date.strftime("%Y-%m")
            bv_start    = round(book_value, 2)
            depr_amt    = min(monthly_depr, max(0, book_value - residual))
            depr_amt    = round(depr_amt, 2)
            accumulated = round(accumulated + depr_amt, 2)
            book_value  = round(book_value - depr_amt, 2)
            schedule.append({
                "period":          period_str,
                "book_value_start": bv_start,
                "depr_amount":     depr_amt,
                "accumulated_depr": accumulated,
                "book_value_end":  book_value,
            })
    elif method == "double_declining":
        rate = 2 / useful_life if useful_life > 0 else 0  # FIN-06(b): useful_life dalam BULAN → tarif bulanan, tidak dibagi 12 lagi
        for i in range(useful_life):
            period_date = depr_start + relativedelta(months=i)
            period_str  = period_date.strftime("%Y-%m")
            bv_start    = round(book_value, 2)
            depr_amt    = round(book_value * rate, 2)
            if book_value - depr_amt < residual or i == useful_life - 1:  # bulan terakhir: tutup ke nilai residu
                depr_amt = max(0, round(book_value - residual, 2))
            accumulated = round(accumulated + depr_amt, 2)
            book_value  = round(book_value - depr_amt, 2)
            schedule.append({
                "period":          period_str,
                "book_value_start": bv_start,
                "depr_amount":     depr_amt,
                "accumulated_depr": accumulated,
                "book_value_end":  book_value,
            })
    return schedule


# ─── CRUD ENDPOINTS ──────────────────────────────────────────────────────────

@router.get("/fixed-assets")
async def list_fixed_assets(request: Request, category: Optional[str] = None,
                             status: Optional[str] = None, search: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    from core.entities import entity_from_request, entity_match
    q = dict(entity_match(entity_from_request(request, allow_all=True)))   # Tahap 8
    if category:
        q["category"] = category
    if status:
        q["status"]   = status
    else:
        q["status"]   = {"$ne": "disposed"}  # default: exclude disposed
    if search:
        import re
        p = re.compile(re.escape(search), re.IGNORECASE)
        q["$or"] = [{"code": p}, {"name": p}, {"serial_number": p}]
    use_pagination = "page" in request.query_params
    if use_pagination:
        page, limit, skip = get_pagination_params(request, default_limit=50)
        total = await db.rahaza_fixed_assets.count_documents(q)
        rows = await db.rahaza_fixed_assets.find(q, {"_id": 0}).sort("purchase_date", -1).skip(skip).limit(limit).to_list(length=10000)
        # Compute current NBV for each
        for r in rows:
            await _enrich_nbv(db, r)
        return paginated_response(serialize_doc(rows), total, page, limit)
    rows = await db.rahaza_fixed_assets.find(q, {"_id": 0}).sort("purchase_date", -1).to_list(500)
    for r in rows:
        await _enrich_nbv(db, r)
    return serialize_doc(rows)


async def _posted_depr_by_asset(db, asset_ids: list, upto_period: Optional[str] = None) -> dict:
    """Σ penyusutan yang SUDAH diposting per aset (opsional s.d. periode YYYY-MM)."""
    if not asset_ids:
        return {}
    match = {"asset_id": {"$in": asset_ids}, "posted": True}
    if upto_period:
        match["period"] = {"$lte": upto_period}
    rows = await db.rahaza_depr_schedules.aggregate([
        {"$match": match}, {"$group": {"_id": "$asset_id", "total": {"$sum": "$depr_amount"}}}]).to_list(len(asset_ids) + 5)
    return {r["_id"]: round(float(r.get("total") or 0), 2) for r in rows}


def accumulated_of(asset: dict, posted_depr: float) -> float:
    """K18: akumulasi = akumulasi awal per go-live (aset lama) + penyusutan yang sudah diposting."""
    return round(float(asset.get("opening_accumulated_depr") or 0) + float(posted_depr or 0), 2)


async def _enrich_nbv(db, asset: dict):
    """Add current NBV and accumulated depreciation to asset dict."""
    aid = asset.get("id", "")
    today = today_wib().strftime("%Y-%m")
    # Sum all posted depreciation up to today (+ akumulasi awal aset lama, K18)
    posted = (await _posted_depr_by_asset(db, [aid], today)).get(aid, 0)
    accum_depr = accumulated_of(asset, posted)
    cost = float(asset.get("purchase_cost") or 0)
    asset["accumulated_depreciation"] = accum_depr
    asset["book_value_current"]       = round(cost - accum_depr, 2)


def _bad(msg: str):
    raise HTTPException(400, msg)


def _parse_amount(v, label: str) -> float:
    import math
    try:
        x = float(v if v not in (None, "") else 0)
    except (TypeError, ValueError):
        _bad(f"{label} harus angka.")
    if not math.isfinite(x):
        _bad(f"{label} tidak valid.")
    return x


async def _coa_ref(db, ref) -> Optional[dict]:
    """Akun COA aktif & postable dari id ATAU kode (form mengirim id, kategori bawaan memakai kode)."""
    if not ref:
        return None
    acc = await db.rahaza_coa_accounts.find_one({"$or": [{"id": ref}, {"code": ref}], "active": True},
                                                {"_id": 0, "id": 1, "code": 1, "name": 1, "is_group": 1})
    return acc if acc and acc.get("code") and not acc.get("is_group") else None


async def resolve_asset_accounts(db, category: str, body: dict) -> dict:
    """K18: akun aset/akumulasi/beban = pilihan form (bila sah) → bawaan kategori → (kosong = profil posting).
    Disimpan sebagai id COA (dibaca post_depreciation/post_asset_disposal/post_asset_acquisition)."""
    defaults = dict(zip(_ACCOUNT_FIELDS, CATEGORY_ACCOUNTS.get(category, (None, None, None))))
    out = {}
    for f in _ACCOUNT_FIELDS:
        chosen = body.get(f)
        acc = await _coa_ref(db, chosen) if chosen else None
        if chosen and not acc:
            _bad(f"Akun '{chosen}' ({f}) tidak ditemukan, tidak aktif, atau akun induk (header).")
        acc = acc or await _coa_ref(db, defaults.get(f))
        out[f] = (acc or {}).get("id") or (acc or {}).get("code")
    return out


async def _master_supplier(db, supplier_id) -> dict:
    """KU2: pemasok dari master `rahaza_suppliers` (aktif) → {supplier, supplier_id, supplier_code}."""
    sid = str(supplier_id or "").strip()
    if not sid:
        _bad("Hutang pemasok (faktur menyusul) wajib memilih pemasok dari Master Pemasok — supaya hutangnya "
             "bisa ditagihkan ke pemasok yang benar saat fakturnya datang.")
    sup = await db.rahaza_suppliers.find_one({"id": sid}, {"_id": 0, "id": 1, "code": 1, "name": 1, "is_active": 1})
    if not sup:
        _bad("Pemasok yang dipilih tidak ada di Master Pemasok.")
    if sup.get("is_active") is False:
        _bad(f"Pemasok '{sup.get('name')}' nonaktif — aktifkan lagi di Master Pemasok atau pilih pemasok lain.")
    return {"supplier": (sup.get("name") or "").strip(), "supplier_id": sup["id"], "supplier_code": sup.get("code") or ""}


async def _funding_credit_code(db, body: dict, cost: float) -> tuple[str, dict]:
    """K18 Pembelian baru: akun KREDIT jurnal perolehan dari sumber dana + metadata tautan."""
    src = (body.get("funding_source") or "").strip()
    if src not in FUNDING_SOURCES or src == "grni" and not body.get("_system_gr"):
        _bad("Pembelian baru wajib memilih sumber dana: rekening kas/bank, hutang pemasok (faktur menyusul), "
             "atau faktur pemasok yang sudah dicatat.")
    from routes.rahaza_posting_profiles import get_mapping
    if src == "cash":
        acc = await db.rahaza_cash_accounts.find_one({"id": body.get("cash_account_id"), "active": True}, {"_id": 0})
        if not acc:
            _bad("Pilih rekening kas/bank aktif untuk pembelian tunai.")
        if not acc.get("gl_account_code"):
            _bad(f"Rekening '{acc.get('name')}' belum tertaut akun GL (Kas & Bank › Sinkron GL).")
        return acc["gl_account_code"], {"cash_account_id": acc["id"], "cash_account_name": acc.get("name")}
    if src in ("payable", "grni"):
        # 2026-11-07 (Tahap 6, KU2 keputusan owner): beli kredit "faktur menyusul" WAJIB memilih pemasok dari
        # master `rahaza_suppliers` (id + nama disimpan). Jurnal perolehan mengkredit Hutang Belum Ditagih
        # (GRNI, tanpa rincian per pemasok); hutang per pemasok (sub-ledger 2-1100-…) lahir saat faktur
        # pemasoknya dicatat — jadi `supplier_id` ini penaut aset ↔ pemasok untuk faktur yang menyusul.
        # Jalur GR (`grni`, sistem) tetap memakai pemasok dari dokumen GR.
        link = {"supplier": (body.get("supplier") or "").strip()}
        if src == "payable":
            link = await _master_supplier(db, body.get("supplier_id"))
        code = (await get_mapping(db, "asset_acquisition")).get("credit_ap_clearing")
        if not code:
            _bad("Profil posting 'asset_acquisition.credit_ap_clearing' (Hutang Belum Ditagih) belum diisi.")
        return code, link
    # ap_invoice — faktur pemasok sudah menjurnal hutang (Dr akun debit faktur / Cr Hutang). Jurnal perolehan
    # MEREKLAS akun debit faktur itu ke akun aset, jadi hutang tidak tercatat dua kali.
    inv = await db.rahaza_ap_invoices.find_one({"id": body.get("ap_invoice_id")}, {"_id": 0})
    if not inv:
        _bad("Faktur pemasok tidak ditemukan.")
    if (inv.get("status") or "").lower() in ("draft", "cancelled", "void"):
        _bad(f"Faktur {inv.get('invoice_number')} berstatus '{inv.get('status')}' — terbitkan dulu.")
    from routes.rahaza_posting import _account_from_issuance_je
    code = await _account_from_issuance_je(db, ["ap_invoice"], f"ap:{inv['id']}", "debit")
    if not code:
        _bad(f"Faktur {inv.get('invoice_number')} belum berjurnal — posting faktur dulu.")
    base = float(inv.get("subtotal") or inv.get("total") or 0)
    used = 0.0
    async for a in db.rahaza_fixed_assets.find({"ap_invoice_id": inv["id"], "status": {"$ne": "deleted"}},
                                               {"_id": 0, "purchase_cost": 1}):
        used += float(a.get("purchase_cost") or 0)
    if cost > round(base - used, 2) + 0.01:
        _bad(f"Harga aset {cost:,.0f} melebihi sisa nilai faktur {inv.get('invoice_number')} "
             f"(DPP {base:,.0f}, sudah dikapitalisasi {used:,.0f}).")
    return code, {"ap_invoice_id": inv["id"], "ap_invoice_number": inv.get("invoice_number"),
                  "supplier": inv.get("vendor_name") or (body.get("supplier") or "").strip()}


async def _golive_default(db) -> Optional[str]:
    """Tanggal go-live = tanggal jurnal Saldo Awal (opening_balance) aktif, bila ada."""
    je = await db.rahaza_journal_entries.find_one({"source_module": "opening_balance", "status": {"$ne": "voided"}},
                                                  {"_id": 0, "date": 1})
    return str(je["date"])[:10] if je and je.get("date") else None


async def register_fixed_asset(db, body: dict, user: dict, *, code: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    """SATU pintu pendaftaran aset tetap (form Keuangan, jalur GR, skrip migrasi). K18 2026-11-02.

    Validasi: harga > 0, umur > 0 (metode menyusut), tanggal beli ≤ hari ini (WIB), jenis perolehan wajib.
    Pembelian baru → jurnal perolehan Dr akun aset (kategori) / Cr sumber dana; gagal jurnal = batal daftar.
    Aset lama → akumulasi per go-live, tanpa jurnal perolehan, jadwal mulai bulan go-live."""
    from utils.waktu import today_wib
    name = (body.get("name") or "").strip()
    if not name:
        _bad("Nama aset wajib diisi")
    cat = body.get("category") or "peralatan"
    if cat not in ASSET_CATEGORIES:
        _bad(f"Kategori harus salah satu dari: {ASSET_CATEGORIES}")
    method = body.get("depreciation_method") or "straight_line"
    if method not in DEPR_METHODS:
        _bad(f"Metode depresiasi: {DEPR_METHODS}")
    acq = (body.get("acquisition_type") or "").strip()
    if acq not in ACQUISITION_TYPES:
        _bad("Pilih jenis perolehan: 'Pembelian baru' (purchase) atau 'Aset lama — saldo awal' (opening).")
    cost = round(_parse_amount(body.get("purchase_cost"), "Harga perolehan"), 2)
    if cost <= 0:
        _bad("Harga perolehan harus lebih dari 0.")
    residual = round(_parse_amount(body.get("residual_value"), "Nilai sisa"), 2)
    if residual < 0 or residual >= cost:
        _bad("Nilai sisa harus ≥ 0 dan lebih kecil dari harga perolehan.")
    try:
        life = int(body.get("useful_life_months") or 0)
    except (TypeError, ValueError):
        _bad("Masa manfaat (bulan) harus bilangan bulat.")
    if method in DEPRECIATING_METHODS and life <= 0:
        _bad("Masa manfaat (bulan) harus lebih dari 0.")
    today = today_wib()
    pdate_raw = (body.get("purchase_date") or today.isoformat())
    try:
        pdate = date.fromisoformat(str(pdate_raw)[:10])
    except ValueError:
        _bad("Tanggal pembelian tidak valid (format YYYY-MM-DD).")
    if pdate > today:
        _bad(f"Tanggal pembelian {pdate.isoformat()} melewati hari ini ({today.isoformat()} WIB).")

    doc_extra: dict = {}
    credit_code = None
    if acq == "opening":
        golive_raw = body.get("golive_date") or await _golive_default(db)
        if not golive_raw:
            _bad("Aset lama wajib mengisi tanggal go-live (atau posting Saldo Awal dulu).")
        try:
            golive = date.fromisoformat(str(golive_raw)[:10])
        except ValueError:
            _bad("Tanggal go-live tidak valid (format YYYY-MM-DD).")
        if pdate > golive:
            _bad("Aset lama: tanggal beli harus sebelum/sama dengan tanggal go-live. Aset yang dibeli "
                 "sesudah go-live didaftarkan sebagai 'Pembelian baru'.")
        opening_acc = round(_parse_amount(body.get("opening_accumulated_depr"), "Akumulasi penyusutan awal"), 2)
        if opening_acc < 0 or opening_acc > round(cost - residual, 2):
            _bad("Akumulasi penyusutan awal harus antara 0 dan (harga − nilai sisa).")
        doc_extra.update({"golive_date": golive.isoformat(), "opening_accumulated_depr": opening_acc})
    else:
        credit_code, link = await _funding_credit_code(db, body, cost)
        doc_extra.update({"funding_source": body.get("funding_source"), "acquisition_credit_code": credit_code, **link})

    accounts = await resolve_asset_accounts(db, cat, body)
    if code is None:
        # SESI #27 — kode aset lewat SATU PINTU kebijakan penomoran (Otomatis/Manual).
        from core.doc_number_policy import issue_number
        code = await issue_number(db, "rahaza_fixed_assets.code", requested=(body.get("code") or "").strip())
    if await db.rahaza_fixed_assets.find_one({"code": code}):
        raise HTTPException(409, f"Kode aset '{code}' sudah digunakan")
    from core.entities import entity_of_value
    doc = {
        "id":                     _uid(),
        "entity":                 entity_of_value(body.get("entity")),   # Tahap 8: CV pemilik aset (bawaan DA)
        "code":                   code,
        "name":                   name,
        "category":               cat,
        "acquisition_type":       acq,
        "purchase_date":          pdate.isoformat(),
        "purchase_cost":          cost,
        "residual_value":         residual,
        "useful_life_months":     life,
        "depreciation_method":    method,
        **accounts,
        "location":               (body.get("location") or "").strip(),
        # KU2: pemasok dari master (hutang faktur menyusul) menang atas teks ketikan
        "supplier":               (doc_extra.get("supplier") if doc_extra.get("supplier_id")
                                   else body.get("supplier") or doc_extra.get("supplier") or "").strip(),
        "serial_number":          (body.get("serial_number") or "").strip(),
        "notes":                  (body.get("notes") or "").strip(),
        "status":                 "active",
        "created_at":             _now(),
        "created_by":             user.get("email") or user.get("id"),
        "disposed_at":            None,
        "disposal_notes":         None,
        **{k: v for k, v in doc_extra.items() if k != "supplier"},
        **(extra or {}),
    }
    await db.rahaza_fixed_assets.insert_one(doc)
    # Auto-generate depreciation schedule
    schedule = _generate_schedule(doc)
    depr_docs = [{
        "id":              _uid(),
        "asset_id":        doc["id"],
        "asset_code":      doc["code"],
        "period":          s["period"],
        "book_value_start":s["book_value_start"],
        "depr_amount":     s["depr_amount"],
        "accumulated_depr":s["accumulated_depr"],
        "book_value_end":  s["book_value_end"],
        "posted":          False,
        "journal_entry_id":None,
        "posted_at":       None,
    } for s in schedule]
    if depr_docs:
        await db.rahaza_depr_schedules.insert_many(depr_docs)

    posting = None
    if acq == "purchase":
        from routes.rahaza_posting import post_asset_acquisition
        try:
            posting = await post_asset_acquisition(db, doc, user)
        except Exception as e:  # noqa: BLE001 — dikembalikan sebagai 400 dengan alasan
            logger.exception("Jurnal perolehan aset gagal")
            posting = {"ok": False, "error": str(e)}
        if not posting.get("ok"):
            # Pembelian baru TANPA jurnal = aset di luar neraca (audit No.37) → batalkan pendaftaran.
            await db.rahaza_depr_schedules.delete_many({"asset_id": doc["id"]})
            await db.rahaza_fixed_assets.delete_one({"id": doc["id"]})
            from routes.rahaza_posting import posting_error_message
            _bad(f"Aset tidak didaftarkan: jurnal perolehan gagal — {posting_error_message(posting)}")
    out = await db.rahaza_fixed_assets.find_one({"id": doc["id"]}, {"_id": 0}) or doc
    out["_posting_result"] = posting
    out["_schedule_periods"] = len(depr_docs)
    return out


@router.get("/fixed-assets/acquisition-options")
async def acquisition_options(request: Request):
    """Pilihan form Daftar Aset (K18): jenis perolehan, sumber dana, akun bawaan kategori, go-live bawaan."""
    await require_auth(request)
    db = get_db()
    cats = {}
    for cat in ASSET_CATEGORIES:
        row = {}
        for f, code in zip(_ACCOUNT_FIELDS, CATEGORY_ACCOUNTS.get(cat, (None, None, None))):
            acc = await _coa_ref(db, code)
            row[f] = {"id": acc.get("id"), "code": acc.get("code"), "name": acc.get("name")} if acc else None
        cats[cat] = row
    from utils.waktu import today_wib
    # KU2 (Tahap 6): pilihan pemasok dari master `rahaza_suppliers` — hanya id/kode/nama pemasok aktif (tanpa
    # rekening, NPWP, termin, harga). Dulu layar membaca /api/procurement/suppliers/options yang menolak staf
    # Keuangan tanpa akses portal Pengadaan (403 → pemasok tidak bisa dipilih).
    sups = await db.rahaza_suppliers.find({"is_active": {"$ne": False}},
                                          {"_id": 0, "id": 1, "code": 1, "name": 1}).sort("name", 1).to_list(2000)
    return {"acquisition_types": [{"value": "purchase", "label": "Pembelian baru"},
                                  {"value": "opening", "label": "Aset lama (saldo awal)"}],
            "funding_sources": [{"value": k, "label": v} for k, v in FUNDING_SOURCES.items() if k != "grni"],
            "category_accounts": cats, "golive_default": await _golive_default(db),
            "suppliers": [{"id": s["id"], "code": s.get("code") or "", "name": s.get("name") or ""}
                          for s in sups if s.get("id") and s.get("name")],
            "today_wib": today_wib().isoformat()}


@router.post("/fixed-assets")
async def create_fixed_asset(request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    body.pop("_system_gr", None)  # penanda internal jalur GR, tidak boleh dari klien
    from core.entities import entity_from_request, validate_cash_account_owner
    body["entity"] = entity_from_request(request, body)   # Tahap 8: CV terpilih (Gabungan ditolak)
    await validate_cash_account_owner(db, body.get("cash_account_id"), body["entity"], what="Aset")
    return serialize_doc(await register_fixed_asset(db, body, user))


@router.get("/fixed-assets/depreciation-due")
async def depreciation_due(request: Request):
    """Aset yang jadwal depresiasinya belum diposting untuk periode ini."""
    await require_auth(request)
    db = get_db()
    cur_period = today_wib().strftime("%Y-%m")
    due = await db.rahaza_depr_schedules.find(
        {"period": cur_period, "posted": False, "depr_amount": {"$gt": 0}},
        {"_id": 0}
    ).to_list(500)
    # Enrich with asset name
    asset_ids = list({d["asset_id"] for d in due})
    assets = {a["id"]: a for a in await db.rahaza_fixed_assets.find({"id": {"$in": asset_ids}}, {"_id": 0}).to_list(500)} if asset_ids else {}
    for d in due:
        a = assets.get(d["asset_id"]) or {}
        d["asset_name"]     = a.get("name", "")
        d["asset_category"] = a.get("category", "")
    return serialize_doc(due)


@router.get("/fixed-assets/{fa_id}/label-pdf")
async def fixed_asset_label_pdf(fa_id: str, request: Request, template: str = "standard"):
    """2026-11-02 (registri aset tunggal): label aset dari registri induk — generator & kode SAMA dengan
    Portal Aset (`routes/asset/scan_label.asset_label_response`)."""
    from routes.asset.scan_label import asset_label_response
    await require_auth(request)
    return await asset_label_response(get_db(), fixed_asset_id=fa_id, template=template)


@router.get("/fixed-assets-summary")
async def fixed_assets_summary(request: Request):
    await require_auth(request)
    db = get_db()
    assets = await db.rahaza_fixed_assets.find({"status": {"$ne": "disposed"}}, {"_id": 0}).to_list(500)
    total_cost = round(sum(float(a.get("purchase_cost") or 0) for a in assets), 2)
    # 2026-11-02 (K18): akumulasi HANYA aset yang masih aktif (dulu ikut jadwal aset yang sudah dilepas →
    # nilai buku ringkasan bisa negatif, audit No.36) + akumulasi awal aset lama per go-live.
    posted = await _posted_depr_by_asset(db, [a["id"] for a in assets])
    total_accum = round(sum(accumulated_of(a, posted.get(a["id"], 0)) for a in assets), 2)
    nbv = round(total_cost - total_accum, 2)
    # Count due this month
    cur_period = today_wib().strftime("%Y-%m")
    due_count = await db.rahaza_depr_schedules.count_documents({"period": cur_period, "posted": False, "depr_amount": {"$gt": 0}})
    by_category = {}
    for a in assets:
        cat = a.get("category", "lain-lain")
        if cat not in by_category:
            by_category[cat] = {"count": 0, "cost": 0}
        by_category[cat]["count"] += 1
        by_category[cat]["cost"]  += float(a.get("purchase_cost") or 0)
    return {
        "total_assets":           len(assets),
        "total_cost":             total_cost,
        "total_accumulated_depr": total_accum,
        "total_nbv":              nbv,
        "depr_due_this_month":    due_count,
        "by_category":            by_category,
    }


@router.get("/fixed-assets/depreciation-summary")
async def get_depreciation_summary(request: Request, period: Optional[str] = None):
    """
    Phase 8B: Summary depreciation per period atau all-time.
    IMPORTANT: This route must be BEFORE /{aid} to avoid route conflict.
    """
    await require_auth(request)
    db = get_db()
    if not period:
        period = today_wib().strftime("%Y-%m")
    pipe = [
        {"$match": {"period": period, "posted": True}},
        {"$group": {"_id": None, "total_depr": {"$sum": "$depr_amount"}, "count": {"$sum": 1}}}
    ]
    agg = await db.rahaza_depr_schedules.aggregate(pipe).to_list(1)
    total_depr = round((agg[0]["total_depr"] if agg else 0), 2)
    count = (agg[0]["count"] if agg else 0)
    assets_active = await db.rahaza_fixed_assets.count_documents({"status": "active"})
    assets_disposed = await db.rahaza_fixed_assets.count_documents({"status": "disposed"})
    return {
        "period": period,
        "total_depreciation": total_depr,
        "assets_count": count,
        "assets_active": assets_active,
        "assets_disposed": assets_disposed,
    }


@router.get("/fixed-assets/{aid}")
async def get_fixed_asset(aid: str, request: Request):
    await require_auth(request)
    db = get_db()
    asset = await db.rahaza_fixed_assets.find_one({"id": aid}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan")
    await _enrich_nbv(db, asset)
    return serialize_doc(asset)


@router.put("/fixed-assets/{aid}")
async def update_fixed_asset(aid: str, request: Request):
    await require_auth(request)
    db = get_db()
    asset = await db.rahaza_fixed_assets.find_one({"id": aid}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan")
    if asset.get("status") == "disposed":
        raise HTTPException(409, "Aset sudah di-dispose")
    body = await request.json()
    allowed = ["name", "location", "supplier", "serial_number", "notes",
               "account_id_asset", "account_id_accum_depr", "account_id_depr_expense"]
    update = {k: body[k] for k in allowed if k in body}
    if asset.get("funding_source") == "payable":
        # KU2: pemasok aset beli kredit tetap dari master — nama mengikuti master, bukan ketikan
        if body.get("supplier_id"):
            update.update(await _master_supplier(db, body.get("supplier_id")))
        elif "supplier" in body and (body.get("supplier") or "") != (asset.get("supplier") or ""):
            _bad("Pemasok aset beli kredit (faktur menyusul) diganti dengan memilih pemasok dari Master Pemasok.")
        else:
            update.pop("supplier", None)
    if update:
        update["updated_at"] = _now()
        await db.rahaza_fixed_assets.update_one({"id": aid}, {"$set": update})
    out = await db.rahaza_fixed_assets.find_one({"id": aid}, {"_id": 0})
    await _enrich_nbv(db, out)
    return serialize_doc(out)


@router.get("/fixed-assets/{aid}/schedule")
async def get_depr_schedule(aid: str, request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_depr_schedules.find({"asset_id": aid}, {"_id": 0}).sort("period", 1).to_list(length=10000)
    return serialize_doc(rows)


@router.post("/fixed-assets/{aid}/post-depr/{period}")
async def post_depreciation(aid: str, period: str, request: Request):
    """
    Posting depresiasi untuk aset pada periode YYYY-MM.
    Membuat jurnal: Dr Depreciation Expense / Cr Accumulated Depreciation.
    """
    user = await require_auth(request)
    db = get_db()
    asset = await db.rahaza_fixed_assets.find_one({"id": aid}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan")
    if asset.get("status") == "disposed":
        raise HTTPException(409, "Aset sudah di-dispose")
    sched = await db.rahaza_depr_schedules.find_one({"asset_id": aid, "period": period}, {"_id": 0})
    if not sched:
        raise HTTPException(404, f"Jadwal depresiasi untuk periode {period} tidak ditemukan")
    if sched.get("posted"):
        raise HTTPException(409, f"Depresiasi periode {period} sudah diposting")
    depr_amt = float(sched.get("depr_amount") or 0)
    if depr_amt <= 0:
        await db.rahaza_depr_schedules.update_one({"asset_id": aid, "period": period},
            {"$set": {"posted": True, "posted_at": _now()}})
        return {"ok": True, "message": "Jumlah depresiasi 0, posting tanpa jurnal"}
    # FIN-06(a): pakai jalur jurnal yang SAMA dengan batch (routes.rahaza_posting.post_depreciation);
    # jangan tandai posted bila jurnal gagal.
    from routes.rahaza_posting import post_depreciation as _post_depr_gl
    posting_result = await _post_depr_gl(db, sched, asset, user)
    if not posting_result.get("ok"):
        raise HTTPException(400, f"Jurnal depresiasi gagal: {posting_result.get('error')}")
    je_id = posting_result.get("je_id")
    await db.rahaza_depr_schedules.update_one({"asset_id": aid, "period": period}, {"$set": {
        "posted": True,
        "posted_at": _now(),
        "posted_by": user.get("id"),
        "journal_entry_id": je_id,
        "je_id": je_id,
        "je_number": posting_result.get("je_number"),
    }})
    return {"ok": True, "depr_amount": depr_amt, "period": period, "journal_entry_id": je_id, "je_number": posting_result.get("je_number")}


@router.post("/fixed-assets/{aid}/dispose")
async def dispose_asset(aid: str, request: Request):
    """Disposal aset — tandai sebagai disposed."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    return await dispose_fixed_asset(db, aid, body, user)


async def dispose_fixed_asset(db, aid: str, body: dict, user: dict) -> dict:
    """SATU jalur pelepasan aset tetap + jurnal (Keuangan & Portal Aset untuk aset tertaut, K18)."""
    asset = await db.rahaza_fixed_assets.find_one({"id": aid}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan")
    if asset.get("status") == "disposed":
        raise HTTPException(409, "Aset sudah di-dispose sebelumnya")
    disposal_date  = body.get("disposal_date") or today_wib().isoformat()
    disposal_value = float(body.get("disposal_value") or 0)
    disposal_notes = (body.get("notes") or body.get("reason") or "").strip()
    try:
        date.fromisoformat(str(disposal_date)[:10])
    except ValueError:
        raise HTTPException(400, "Tanggal pelepasan tidak valid (format YYYY-MM-DD).")
    # 2026-11-02 (audit No.36 opsi A): pelepasan bertanggal SEBELUM periode penyusutan terakhir
    # yang sudah diposting meninggalkan akumulasi yatim & beban lebih saji. Tolak; Finance
    # membatalkan dulu penyusutan sesudah tanggal itu.
    last_posted = await db.rahaza_depr_schedules.find_one(
        {"asset_id": aid, "posted": True, "depr_amount": {"$gt": 0}},
        {"_id": 0, "period": 1}, sort=[("period", -1)])
    if last_posted and str(disposal_date)[:7] < str(last_posted.get("period") or ""):
        raise HTTPException(
            400, f"Tanggal pelepasan {str(disposal_date)[:10]} sebelum periode penyusutan terakhir "
                 f"yang sudah diposting ({last_posted['period']}). Batalkan dulu jurnal penyusutan "
                 f"sesudah tanggal pelepasan, atau pakai tanggal pelepasan di/sesudah periode itu.")
    # FIN-06(c): NBV per TANGGAL PELEPASAN = harga perolehan − akumulasi jadwal yang sudah posted s.d. bulan pelepasan
    acc_agg = await db.rahaza_depr_schedules.aggregate([
        {"$match": {"asset_id": aid, "posted": True, "period": {"$lte": disposal_date[:7]}}},
        {"$group": {"_id": None, "total": {"$sum": "$depr_amount"}}},
    ]).to_list(1)
    accumulated_depr = accumulated_of(asset, float(acc_agg[0]["total"]) if acc_agg else 0.0)  # + akumulasi awal (K18)
    cost = float(asset.get("purchase_cost") or 0)
    nbv = round(cost - accumulated_depr, 2)
    gain_loss = round(disposal_value - nbv, 2)
    await db.rahaza_fixed_assets.update_one({"id": aid}, {"$set": {
        "accumulated_depr_at_disposal": accumulated_depr,
        "status":        "disposed",
        "disposed_at":   _now(),
        "disposal_date": disposal_date,
        "disposal_value": disposal_value,
        "disposal_notes": disposal_notes,
        "disposal_gain_loss": gain_loss,
        "nbv_at_disposal":    nbv,
    }})
    # Cancel future schedule entries
    await db.rahaza_depr_schedules.update_many(
        {"asset_id": aid, "period": {"$gt": disposal_date[:7]}, "posted": False},
        {"$set": {"cancelled": True}}
    )
    
    # Phase 10A: Auto-post GL for asset disposal
    posting_result = None
    try:
        from routes.rahaza_posting import post_asset_disposal
        asset_refresh = await db.rahaza_fixed_assets.find_one({"id": aid}, {"_id": 0})
        posting_result = await post_asset_disposal(db, asset_refresh, user)
    except Exception as e:
        logger.exception("Asset disposal GL posting failed")
        posting_result = {"ok": False, "error": str(e)}
    
    return {"ok": True, "gain_loss": gain_loss, "nbv_at_disposal": nbv, "posting_result": posting_result}



# ══════════════════════════════════════════════════════════════════════════════
# PHASE 8B: BATCH DEPRECIATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/fixed-assets/run-batch-depreciation")
async def run_batch_depreciation(request: Request):
    """
    Phase 8B: Run batch depreciation untuk periode tertentu.
    
    Body:
    {
        "period": "2026-05",  // YYYY-MM
        "asset_ids": [],      // Optional: kosong = semua assets aktif
        "auto_post": true     // Auto-post ke GL
    }
    
    Returns: summary + list asset yang di-depreciate
    """
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    
    period = body.get("period", today_wib().strftime("%Y-%m"))
    asset_ids = body.get("asset_ids", [])
    auto_post = body.get("auto_post", True)
    
    # Validate period format
    try:
        datetime.strptime(period, "%Y-%m")
    except ValueError:
        raise HTTPException(400, "Invalid period format. Use YYYY-MM")
    
    # Build query
    query = {"status": "active"}
    if asset_ids:
        query["id"] = {"$in": asset_ids}
    
    # Exclude assets dengan depreciation_method = "none" atau "manual"
    query["depreciation_method"] = {"$nin": ["none", "manual"]}
    
    assets = await db.rahaza_fixed_assets.find(query, {"_id": 0}).to_list(1000)
    
    if not assets:
        return {
            "ok": True,
            "message": "Tidak ada asset yang perlu di-depreciate untuk periode ini",
            "period": period,
            "assets_processed": 0,
            "total_depreciation": 0,
            "results": []
        }
    
    results = []
    total_depreciation = 0
    posted_count = 0
    
    for asset in assets:
        # Generate schedule if not exists
        asset_id = asset["id"]
        schedule = _generate_schedule(asset)
        
        # Find schedule entry for this period
        period_entry = next((s for s in schedule if s["period"] == period), None)
        
        if not period_entry:
            # Period tidak ada dalam schedule (sudah lewat useful life)
            results.append({
                "asset_id": asset_id,
                "asset_code": asset.get("code"),
                "asset_name": asset.get("name"),
                "status": "skipped",
                "reason": "Period tidak ada dalam schedule (asset sudah fully depreciated)",
                "depr_amount": 0,
            })
            continue
        
        depr_amount = period_entry.get("depr_amount", 0)
        if depr_amount <= 0:
            results.append({
                "asset_id": asset_id,
                "asset_code": asset.get("code"),
                "asset_name": asset.get("name"),
                "status": "skipped",
                "reason": "Depreciation amount = 0",
                "depr_amount": 0,
            })
            continue
        
        # Check if already posted
        existing_schedule = await db.rahaza_depr_schedules.find_one({
            "asset_id": asset_id,
            "period": period,
            "posted": True
        })
        
        if existing_schedule:
            results.append({
                "asset_id": asset_id,
                "asset_code": asset.get("code"),
                "asset_name": asset.get("name"),
                "status": "already_posted",
                "reason": f"Already posted on {existing_schedule.get('posted_at', 'N/A')}",
                "depr_amount": depr_amount,
                "je_number": existing_schedule.get("je_number"),
            })
            total_depreciation += depr_amount
            posted_count += 1
            continue
        
        # Create or update schedule entry
        schedule_id = _uid()
        schedule_doc = {
            "id": schedule_id,
            "asset_id": asset_id,
            "asset_code": asset.get("code"),
            "asset_name": asset.get("name"),
            "period": period,
            "book_value_start": period_entry.get("book_value_start", 0),
            "depr_amount": depr_amount,
            "accumulated_depr": period_entry.get("accumulated_depr", 0),
            "book_value_end": period_entry.get("book_value_end", 0),
            "posted": False,
            "created_at": _now(),
        }
        
        # Upsert schedule
        await db.rahaza_depr_schedules.update_one(
            {"asset_id": asset_id, "period": period},
            {"$setOnInsert": schedule_doc},
            upsert=True
        )
        
        # Auto-post GL if requested
        posting_result = None
        if auto_post:
            try:
                from routes.rahaza_posting import post_depreciation
                schedule_refresh = await db.rahaza_depr_schedules.find_one({"asset_id": asset_id, "period": period}, {"_id": 0})
                posting_result = await post_depreciation(db, schedule_refresh, asset, user)
                
                if posting_result.get("ok"):
                    # Mark as posted
                    await db.rahaza_depr_schedules.update_one(
                        {"asset_id": asset_id, "period": period},
                        {"$set": {
                            "posted": True,
                            "posted_at": _now(),
                            "posted_by": user.get("id"),
                            "je_id": posting_result.get("je_id"),
                            "je_number": posting_result.get("je_number"),
                        }}
                    )
                    posted_count += 1
                    total_depreciation += depr_amount
                    
                    results.append({
                        "asset_id": asset_id,
                        "asset_code": asset.get("code"),
                        "asset_name": asset.get("name"),
                        "status": "posted",
                        "depr_amount": depr_amount,
                        "je_number": posting_result.get("je_number"),
                    })
                else:
                    results.append({
                        "asset_id": asset_id,
                        "asset_code": asset.get("code"),
                        "asset_name": asset.get("name"),
                        "status": "error",
                        "reason": posting_result.get("error", "Unknown error"),
                        "depr_amount": depr_amount,
                    })
            except Exception as e:
                logger.exception(f"Failed to post depreciation for asset {asset_id}")
                results.append({
                    "asset_id": asset_id,
                    "asset_code": asset.get("code"),
                    "asset_name": asset.get("name"),
                    "status": "error",
                    "reason": str(e),
                    "depr_amount": depr_amount,
                })
        else:
            # Schedule created but not posted
            results.append({
                "asset_id": asset_id,
                "asset_code": asset.get("code"),
                "asset_name": asset.get("name"),
                "status": "scheduled",
                "depr_amount": depr_amount,
            })
            total_depreciation += depr_amount
    
    from auth import log_activity
    await log_activity(
        user.get("id", "system"),
        user.get("name", "system"),
        "run_batch_depreciation",
        "fixed_assets",
        f"Batch depreciation {period}: {len(assets)} assets, {posted_count} posted, total Rp {total_depreciation:,.0f}"
    )
    
    return {
        "ok": True,
        "message": f"Batch depreciation completed for period {period}",
        "period": period,
        "assets_processed": len(assets),
        "posted_count": posted_count,
        "total_depreciation": round(total_depreciation, 2),
        "results": results,
    }


# NOTE: GET /fixed-assets/depreciation-summary is defined above (before /{aid}) to avoid route conflict.
