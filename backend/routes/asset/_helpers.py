"""
Shared helpers, constants, and the FastAPI router instance for Asset Management.

All sub-modules import `router` from here and attach @router.<method>(...)
decorators to register their endpoints.
"""
from fastapi import APIRouter
from datetime import datetime, timezone, date
import uuid
import logging
from typing import Optional  # noqa: F401  (re-exported for sub-modules)

logger = logging.getLogger("asset_mgmt")

# ─── Router (shared across all asset sub-modules) ─────────────────────────
router = APIRouter(prefix="/api/assets", tags=["asset-management"])


# ─── Tiny utilities ──────────────────────────────────────────────────────
def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ser(doc):
    """Strip Mongo `_id` and stringify datetimes."""
    if not doc:
        return doc
    doc = {k: v for k, v in doc.items() if k != "_id"}
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


# ─── Category seed ────────────────────────────────────────────────────────
DEFAULT_CATEGORIES = [
    {"name": "Peralatan IT",    "code": "IT",  "useful_life_years": 4,  "depr_method": "straight_line"},
    {"name": "Mesin Produksi",  "code": "MP",  "useful_life_years": 10, "depr_method": "straight_line"},
    {"name": "Kendaraan",       "code": "KD",  "useful_life_years": 5,  "depr_method": "double_declining"},
    {"name": "Bangunan",        "code": "BG",  "useful_life_years": 20, "depr_method": "straight_line"},
    {"name": "Perabot & Mebel", "code": "PM",  "useful_life_years": 8,  "depr_method": "straight_line"},
    {"name": "Alat & Perkakas", "code": "AP",  "useful_life_years": 5,  "depr_method": "straight_line"},
    {"name": "Lain-lain",       "code": "LN",  "useful_life_years": 5,  "depr_method": "straight_line"},
]

DISPOSAL_APPROVAL_THRESHOLD = 5_000_000  # 5 juta IDR


async def _ensure_default_categories(db):
    cnt = await db.dewi_asset_categories.count_documents({})
    if cnt == 0:
        seed = []
        for cat in DEFAULT_CATEGORIES:
            d = dict(cat)
            d["id"] = _uid()
            d["created_at"] = _now()
            seed.append(d)
        await db.dewi_asset_categories.insert_many(seed)


async def _gen_asset_number(db, category_code: str, requested: str = "") -> str:
    """Nomor aset inventaris — SATU PINTU kebijakan penomoran (SESI #27).

    `{KATEGORI}` menjaga satu seri per kategori aset seperti sebelumnya
    (`AST-<KATEGORI>-<TAHUN>-0001`) dan membuat formatnya bisa diatur owner.
    """
    from core.doc_number_policy import issue_number
    return await issue_number(db, "dewi_assets.asset_number",
                              ctx={"KATEGORI": category_code}, requested=requested)


def _calc_straight_line_monthly(cost: float, residual: float, life_months: int) -> float:
    if life_months <= 0:
        return 0.0
    return round((cost - residual) / life_months, 2)


def _calc_nbv(asset: dict) -> float:
    """Net Book Value = purchase_cost − accumulated_depreciation."""
    return round(
        float(asset.get("purchase_cost", 0)) - float(asset.get("accumulated_depreciation", 0)),
        2,
    )


# ─── K18 (2026-11-02): Portal Aset = TAMPILAN OPERASIONAL registri Keuangan ──────
# Keputusan owner: satu registri induk aset tetap = `rahaza_fixed_assets` (Keuangan › Aset Tetap).
# Portal Aset (`dewi_assets`) mencatat lokasi, pemegang, perawatan, peminjaman, dan MENAUT id aset
# Keuangan (`fixed_asset_id`). SEMUA jurnal dari Portal Aset dimatikan — dulu pembelian membuat jurnal
# draft Dr 1-2500 / Cr 1-1201 (selalu dianggap tunai BCA) dan penyusutan memakai akun hantu 6200/1590
# yang gagal E11000 diam-diam. Nilai buku, penyusutan, dan jurnal pelepasan hanya dari registri Keuangan.
DEPRECIATION_MOVED_MSG = ("Penyusutan hanya dari registri Keuangan › Aset Tetap (keputusan owner K18). "
                          "Portal Aset tidak lagi membuat jurnal; tautkan aset ini ke aset Keuangan untuk melihat "
                          "nilai buku & jadwal penyusutannya.")


async def load_finance_assets(db, ids) -> dict:
    """{fixed_asset_id: ringkasan nilai dari registri Keuangan} (harga, akumulasi, nilai buku, status)."""
    ids = [i for i in set(ids or []) if i]
    if not ids:
        return {}
    from routes.rahaza_fixed_assets import _posted_depr_by_asset, accumulated_of
    fas = await db.rahaza_fixed_assets.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 5)
    posted = await _posted_depr_by_asset(db, [f["id"] for f in fas], date.today().strftime("%Y-%m"))
    out = {}
    for f in fas:
        acc = accumulated_of(f, posted.get(f["id"], 0))
        cost = float(f.get("purchase_cost") or 0)
        out[f["id"]] = {"id": f["id"], "code": f.get("code"), "name": f.get("name"), "category": f.get("category"),
                        "status": f.get("status"), "purchase_date": f.get("purchase_date"),
                        "purchase_cost": cost, "accumulated_depreciation": acc,
                        "book_value": round(cost - acc, 2), "acquisition_type": f.get("acquisition_type")}
    return out


def apply_finance_overlay(asset: dict, fin: Optional[dict]) -> dict:
    """Nilai keuangan aset tertaut DIAMBIL dari registri Keuangan (bukan angka Portal Aset)."""
    if not asset:
        return asset
    if fin:
        asset["finance_asset"] = fin
        asset["purchase_cost"] = fin["purchase_cost"]
        asset["accumulated_depreciation"] = fin["accumulated_depreciation"]
        asset["nbv"] = fin["book_value"]
        asset["value_source"] = "finance_registry"
    else:
        asset["finance_asset"] = None
        asset["value_source"] = "unlinked" if not asset.get("fixed_asset_id") else "finance_missing"
    return asset


async def validate_finance_link(db, fixed_asset_id: str, own_asset_id: Optional[str] = None) -> dict:
    """Aset Keuangan yang akan ditaut: wajib ada, belum dilepas, dan belum ditaut aset Portal Aset lain."""
    from fastapi import HTTPException
    fa = await db.rahaza_fixed_assets.find_one({"id": fixed_asset_id}, {"_id": 0})
    if not fa:
        raise HTTPException(400, "Aset Keuangan (registri Aset Tetap) tidak ditemukan.")
    if fa.get("status") == "disposed":
        raise HTTPException(400, f"Aset Keuangan {fa.get('code')} sudah dilepas.")
    q = {"fixed_asset_id": fixed_asset_id}
    if own_asset_id:
        q["id"] = {"$ne": own_asset_id}
    other = await db.dewi_assets.find_one(q, {"_id": 0, "asset_number": 1})
    if other:
        raise HTTPException(409, f"Aset Keuangan {fa.get('code')} sudah ditaut ke {other.get('asset_number')}.")
    return fa


# ─── Utilization-report date helpers ──────────────────────────────────────
def _parse_date_yyyymmdd(s: Optional[str], default: date) -> date:
    if not s:
        return default
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return default


def _days_between(d1: date, d2: date) -> int:
    """Inclusive day count between d1 and d2 (d2 >= d1)."""
    if d2 < d1:
        return 0
    return (d2 - d1).days + 1


def _intersect_days(a_start: date, a_end: date, b_start: date, b_end: date) -> int:
    """Overlap days between [a_start..a_end] and [b_start..b_end]."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end < start:
        return 0
    return (end - start).days + 1


def _safe_avg_interval_days(dates_iso_desc):
    """Given maintenance date strings (YYYY-MM-DD), compute avg interval (days).
    Returns None if < 2 valid dates."""
    if len(dates_iso_desc) < 2:
        return None
    parsed = []
    for d in dates_iso_desc:
        try:
            parsed.append(datetime.strptime(str(d)[:10], "%Y-%m-%d").date())
        except Exception:
            continue
    if len(parsed) < 2:
        return None
    parsed.sort(reverse=True)
    diffs = [(parsed[i] - parsed[i + 1]).days for i in range(len(parsed) - 1)]
    diffs = [d for d in diffs if d > 0]
    if not diffs:
        return None
    return sum(diffs) / len(diffs)


# ─── Index creation (called at server startup if wired) ──────────────────
async def create_asset_indexes(db):
    await db.dewi_assets.create_index([("status", 1), ("category_id", 1)])
    await db.dewi_assets.create_index([("asset_number", 1)], unique=True, sparse=True)
    await db.dewi_assets.create_index([("assigned_to_id", 1)])
    await db.dewi_asset_depreciation.create_index([("asset_id", 1), ("period", 1)], unique=True)
    await db.dewi_asset_assignments.create_index([("asset_id", 1), ("status", 1)])
    await db.dewi_asset_maintenance.create_index([("asset_id", 1), ("maintenance_date", -1)])
    await db.dewi_asset_pm_acknowledgments.create_index([("asset_id", 1), ("acknowledged_at", -1)])
    # ACC-3 — peminjaman aset (dewi_asset_loans)
    await db.dewi_asset_loans.create_index([("status", 1), ("expected_return_date", 1)])
    await db.dewi_asset_loans.create_index([("asset_id", 1), ("status", 1)])
    await db.dewi_asset_loans.create_index([("loan_number", 1)], unique=True, sparse=True)
