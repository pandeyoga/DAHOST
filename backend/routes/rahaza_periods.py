"""
PT Rahaza — Phase F1 Accounting Core
Fiscal Periods (month-based). status: open | closed | locked.
Closed = no new posting; Locked = no open/close anymore (final audit lock, admin only).

Collection: rahaza_periods
  id, entity (DA|SMU, Tahap 8), period_code (YYYY-MM), period_label, year, month,
  status, closed_at, closed_by, locked_at, locked_by

Tahap 8 (dua CV): periode dikunci per (CV, kode periode). CV dibaca dari query/body/header X-CV
(core.entities.entity_from_request); dokumen lama tanpa entity = DA.
"""
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity
import uuid
from datetime import datetime, timezone, date
from core.roles import FINANCE_ROLES  # FIN-02
from utils.waktu import today_wib
from core import entities as ent_mod
from core.entities import entity_from_request, entity_match

router = APIRouter(prefix="/api/rahaza/periods", tags=["rahaza-periods"])


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)


async def _require_fin_mgr(request: Request):
    user = await require_auth(request)
    from routes.shared import lolos_centang
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    role = (user.get("role") or "").lower()
    if role in FINANCE_ROLES:  # FIN-02
        return user
    perms = user.get("_permissions") or []
    if "*" in perms or "finance.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh role finance/accounting.")


def period_end_date(period_code: str) -> date:
    """Tanggal terakhir periode YYYY-MM."""
    from calendar import monthrange
    y, m = int(period_code[:4]), int(period_code[5:7])
    return date(y, m, monthrange(y, m)[1])


def period_not_ended_error(period_code: str, today: date, action: str) -> str | None:
    """2026-11-02 (audit No.34): tutup/kunci periode yang BELUM berakhir (tanggal akhir ≥ hari ini
    WIB) membuat semua jurnal otomatis bulan berjalan gagal diam-diam, dan kunci periode masa
    depan tidak bisa dibuka lagi. Murni, agar bisa diuji tanpa DB."""
    try:
        end = period_end_date(period_code)
    except (ValueError, IndexError):
        return f"Kode periode '{period_code}' tidak valid."
    if end >= today:
        return (f"Periode {period_code} belum berakhir (tanggal akhir {end.isoformat()}, hari ini "
                f"{today.isoformat()} WIB). {action} hanya boleh setelah periodenya selesai.")
    return None


@router.get("")
async def list_periods(request: Request, year: int = 0):
    await require_auth(request)
    db = get_db()
    ent = entity_from_request(request, allow_all=True)
    q = dict(entity_match(ent))
    if year:
        q["year"] = year
    rows = await db.rahaza_periods.find(q, {"_id": 0}).sort("period_code", -1).to_list(1000)
    for r in rows:
        r["entity"] = ent_mod.entity_of_value(r.get("entity"))
        r["entity_label"] = ent_mod.entity_short(r["entity"])
    return serialize_doc(rows)


@router.post("/ensure-year")
async def ensure_year(request: Request):
    """Create 12 monthly periods for given year (idempotent)."""
    user = await _require_fin_mgr(request)
    db = get_db()
    try:
        body = await request.json()
    except Exception:
        body = {}
    year = int((body or {}).get("year") or today_wib().year)
    ent = entity_from_request(request, body if isinstance(body, dict) else None)
    from routes.rahaza_posting import ensure_year_periods
    created = await ensure_year_periods(db, year, ent)
    # Iter 114: peringatan "periode belum dibuka" utk tahun ini otomatis selesai
    await db.rahaza_period_alerts.update_many(
        {"year": year, "status": "open", **entity_match(ent)},
        {"$set": {"status": "resolved", "resolved_at": _now(), "resolved_by": user.get("name", ""), "resolved_via": "ensure-year"}})
    await log_activity(user["id"], user.get("name", ""), "ensure_periods", "periods", f"{ent} year={year} created={created}")
    return {"ok": True, "year": year, "created": created, "entity": ent}


@router.get("/policy")
async def period_policy(request: Request):
    """H-08: aturan tanggal posting yang berlaku (dibaca layar Periode Fiskal)."""
    await require_auth(request)
    from routes.rahaza_posting import POSTING_FUTURE_DAYS, PERIOD_AUTO_CREATE_YEARS
    y = today_wib().year
    return {"future_days_max": POSTING_FUTURE_DAYS, "auto_create_years": PERIOD_AUTO_CREATE_YEARS,
            "auto_years": list(range(y - PERIOD_AUTO_CREATE_YEARS, y + PERIOD_AUTO_CREATE_YEARS + 1))}


@router.get("/alerts")
async def list_period_alerts(request: Request, status: str = "open"):
    """Iter 114: peringatan jurnal ditolak karena periode belum dibuka (utk Finance)."""
    await require_auth(request)
    db = get_db()
    q = {} if status == "all" else {"status": status}
    rows = await db.rahaza_period_alerts.find(q, {"_id": 0}).sort("last_at", -1).to_list(200)
    return {"alerts": serialize_doc(rows), "open_count": await db.rahaza_period_alerts.count_documents({"status": "open"})}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_period_alert(alert_id: str, request: Request):
    user = await _require_fin_mgr(request)
    db = get_db()
    r = await db.rahaza_period_alerts.update_one(
        {"id": alert_id, "status": "open"},
        {"$set": {"status": "resolved", "resolved_at": _now(), "resolved_by": user.get("name", "")}})
    if not r.matched_count:
        raise HTTPException(404, "Peringatan tidak ditemukan / sudah selesai.")
    return {"ok": True}


def _per_key(per: dict) -> dict:
    """Kunci SATU dokumen periode (bukan period_code saja: DA dan CV Sukma punya kode yang sama)."""
    return {"_id": per["_id"]} if "_id" in per else {"id": per.get("id")}


async def _period_entity(request: Request) -> str:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 (tanpa body)
        body = None
    return entity_from_request(request, body if isinstance(body, dict) else None)


@router.post("/{period_code}/close")
async def close_period(period_code: str, request: Request):
    user = await _require_fin_mgr(request)
    db = get_db()
    ent = await _period_entity(request)
    per = await db.rahaza_periods.find_one({"period_code": period_code, **entity_match(ent)})
    if not per:
        raise HTTPException(404, "Periode tidak ditemukan.")
    if per["status"] in ("closed", "locked"):
        raise HTTPException(400, f"Periode sudah {per['status']}.")
    from utils.waktu import today_wib
    err = period_not_ended_error(period_code, today_wib(), "Tutup periode")
    if err:
        raise HTTPException(400, err)
    # check draft journals in this period: warn but allow
    drafts = await db.rahaza_journal_entries.count_documents({"date": {"$regex": f"^{period_code}"}, "status": "draft",
                                                              **entity_match(ent)})
    res = await db.rahaza_periods.update_one(
        {**_per_key(per), "status": per["status"]},   # 2026-11-06 (pola P9); Tahap 8: dokumen CV ini
        {"$set": {"status": "closed", "closed_at": _now(), "closed_by": user["id"], "closed_by_name": user.get("name", "")}},
    )
    if not res.matched_count:
        raise HTTPException(409, "Status periode ini baru saja diubah pengguna lain — muat ulang halaman.")
    await log_activity(user["id"], user.get("name", ""), "close_period", "periods", f"{ent} {period_code}")
    return {"ok": True, "period_code": period_code, "entity": ent, "status": "closed", "draft_journals_left": drafts}


@router.post("/{period_code}/reopen")
async def reopen_period(period_code: str, request: Request):
    user = await _require_fin_mgr(request)
    db = get_db()
    ent = await _period_entity(request)
    per = await db.rahaza_periods.find_one({"period_code": period_code, **entity_match(ent)})
    if not per:
        raise HTTPException(404, "Periode tidak ditemukan.")
    if per["status"] == "locked":
        raise HTTPException(423, "Periode terkunci (locked) dan tidak bisa di-reopen.")
    if per["status"] != "closed":
        raise HTTPException(400, f"Hanya periode closed yang bisa reopen. Status sekarang: {per['status']}")
    # 2026-11-06 (pola P9): hanya dari 'closed' — dulu "buka" yang membaca status lama bisa membuka lagi
    # periode yang baru saja DIKUNCI (kunci final audit jebol).
    res = await db.rahaza_periods.update_one(
        {**_per_key(per), "status": "closed"},
        {"$set": {"status": "open", "closed_at": None, "closed_by": None}},
    )
    if not res.matched_count:
        raise HTTPException(409, "Status periode ini baru saja diubah pengguna lain — muat ulang halaman.")
    await log_activity(user["id"], user.get("name", ""), "reopen_period", "periods", f"{ent} {period_code}")
    return {"ok": True, "period_code": period_code, "entity": ent, "status": "open"}


@router.post("/{period_code}/lock")
async def lock_period(period_code: str, request: Request):
    """Final lock (audit). Only admin/superadmin."""
    user = await require_auth(request)
    if (user.get("role") or "").lower() not in ("superadmin", "admin", "owner"):
        raise HTTPException(403, "Hanya admin/superadmin yang boleh lock periode.")
    db = get_db()
    ent = await _period_entity(request)
    per = await db.rahaza_periods.find_one({"period_code": period_code, **entity_match(ent)})
    if not per:
        raise HTTPException(404, "Periode tidak ditemukan.")
    if per["status"] == "locked":
        raise HTTPException(400, "Periode sudah locked.")
    if per["status"] != "closed":
        raise HTTPException(400, "Hanya periode closed yang bisa di-lock.")
    # 2026-11-02 (audit No.34): kunci periode masa depan = jalan buntu permanen (locked tidak bisa
    # di-reopen, dan tutup tahun tidak bisa dibatalkan bila Desember terkunci).
    from utils.waktu import today_wib
    err = period_not_ended_error(period_code, today_wib(), "Kunci (lock) periode")
    if err:
        raise HTTPException(400, err)
    res = await db.rahaza_periods.update_one(
        {**_per_key(per), "status": "closed"},   # 2026-11-06 (pola P9); Tahap 8: dokumen CV ini
        {"$set": {"status": "locked", "locked_at": _now(), "locked_by": user["id"], "locked_by_name": user.get("name", "")}},
    )
    if not res.matched_count:
        raise HTTPException(409, "Status periode ini baru saja diubah pengguna lain — muat ulang halaman.")
    await log_activity(user["id"], user.get("name", ""), "lock_period", "periods", f"{ent} {period_code}")
    return {"ok": True, "period_code": period_code, "entity": ent, "status": "locked"}
