"""
CV. Dewi Aditya ERP — Kasbon & Pinjaman Karyawan (Phase 12)
Collection: dewi_kasbon_requests

Status Flow:
  submitted → hr_approved | hr_rejected → disbursed (aktif) → paid_off
  
Types:
  kasbon  : Gaji dimuka, lunas 1x potongan gaji
  pinjaman: Cicilan bulanan, auto-potong gaji setiap periode

API:
  POST   /api/dewi/kasbon/requests            — Ajukan kasbon/pinjaman (staff/admin)
  GET    /api/dewi/kasbon/requests            — List semua (HR/Finance) atau milik sendiri
  GET    /api/dewi/kasbon/my-requests         — List milik sendiri (staff)
  GET    /api/dewi/kasbon/requests/{id}       — Detail
  PATCH  /api/dewi/kasbon/requests/{id}/hr-review   — HR approve/reject
  PATCH  /api/dewi/kasbon/requests/{id}/disburse    — Finance cairkan
  POST   /api/dewi/kasbon/requests/{id}/repay       — Catat pembayaran manual
  POST   /api/dewi/kasbon/requests/{id}/cancel      — Batalkan (staff, status submitted)
  GET    /api/dewi/kasbon/stats               — Dashboard stats
  GET    /api/dewi/kasbon/employee/{id}/deductions  — Deductions untuk payroll
  POST   /api/dewi/kasbon/apply-payroll-deductions  — Ulang pencatatan potongan dari run payroll FINAL

2026-11-02 (paket P5):
  · daftar/detail/statistik/potongan hanya untuk HR/Keuangan/owner/super atau karyawan ybs;
  · pencairan & bayar manual memakai rekening + tanggal yang dipilih pengguna;
  · "Potong Gaji" dari Keuangan dihapus — kasbon hanya lunas lewat run payroll FINAL atau uang nyata;
  · endpoint "Muat Demo" (/seed) dihapus (membuat 5 kasbon palsu atas nama karyawan nyata);
  · pemohon diberi notifikasi saat kasbon disetujui/ditolak HR.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from database import get_db
from core.doc_number_policy import issue_number  # FASE G — satu pintu penomoran
from auth import require_auth
from datetime import datetime, timezone, date
from typing import Optional
import logging
import uuid
import math
from utils.waktu import fmt_wib, today_wib

router = APIRouter(prefix="/api/dewi/kasbon", tags=["Kasbon"])

# FIN-03 (temuan 2026-09-23): gerbang peran untuk review HR, pencairan Finance, seeder demo
from core.authz import only  # noqa: E402
from core.roles import FINANCE_ROLES, HR_ROLES  # noqa: E402
from routes.rahaza_payroll_shared import (  # noqa: E402 — 2026-11-02 (P5): helper bersama
    ensure_not_self_approval, notify_requester, parse_ymd, resolve_payment_account,
)
_HR_OR_FIN = tuple(dict.fromkeys(HR_ROLES + FINANCE_ROLES))
_PRIVILEGED_ROLES = {r.lower() for r in _HR_OR_FIN} | {"superadmin", "admin"}


def _is_privileged(user: dict) -> bool:
    """HR/Keuangan/owner/super (atau izin '*', atau izin menu Kasbon SDM/Keuangan yang diberi owner)."""
    if (user.get("role") or "").lower() in _PRIVILEGED_ROLES:
        return True
    perms = set(user.get("_permissions") or [])
    return "*" in perms or any(p.startswith(("mod.hr_kasbon.", "mod.fin_kasbon.")) for p in perms)


async def _own_employee_ids(db, user: dict) -> set:
    """Id karyawan milik akun login (users.employee_id / rahaza_employees.user_id)."""
    ids = {x for x in (user.get("employee_id"),) if x}
    if user.get("id"):
        emp = await db.rahaza_employees.find_one({"user_id": user["id"]}, {"_id": 0, "id": 1})
        if emp and emp.get("id"):
            ids.add(emp["id"])
        u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "employee_id": 1})
        if u and u.get("employee_id"):
            ids.add(u["employee_id"])
    return ids


def _owns(doc: dict, own_ids: set, user: dict) -> bool:
    return bool(doc) and (doc.get("employee_id") in own_ids
                          or (user.get("email") and doc.get("submitted_by") == user.get("email")))


async def _kasbon_requester_user_id(db, doc: dict):
    """User login milik karyawan pemilik kasbon; cadangan: user pengaju (submitted_by email)."""
    emp = await db.rahaza_employees.find_one({"id": doc.get("employee_id")}, {"_id": 0, "user_id": 1})
    if emp and emp.get("user_id"):
        return emp["user_id"]
    u = await db.users.find_one({"employee_id": doc.get("employee_id")}, {"_id": 0, "id": 1})
    if not u and doc.get("submitted_by"):
        u = await db.users.find_one({"email": doc.get("submitted_by")}, {"_id": 0, "id": 1})
    return (u or {}).get("id")

# ── 2026-11-02 (K30) — "PERLU TINDAKAN": kasbon menunggu HR (review) lalu Keuangan (pencairan) ──
# Penerima = peran NYATA portal yang lolos gerbang endpoint keputusannya (hr-review: HR_ROLES,
# disburse: FINANCE_ROLES). Pengaju (submitted_by) dan karyawan pemilik kasbon TIDAK ikut menerima.
# Ditutup otomatis oleh resolver (`SOURCE_RULES['kasbon_review'/'kasbon_disburse']`).
async def _kasbon_owner_user_ids(db, doc: dict) -> list:
    ids = {await _kasbon_requester_user_id(db, doc)}
    if doc.get("submitted_by"):
        u = await db.users.find_one({"email": doc["submitted_by"]}, {"_id": 0, "id": 1})
        ids.add((u or {}).get("id"))
    return sorted(i for i in ids if i)


async def notify_kasbon_stage(db, doc: dict, *, stage: str, actor: dict | None = None):
    """stage: 'review' (→ HR) | 'disburse' (→ Keuangan). Tidak pernah raise."""
    try:
        from utils.notif_unified import decider_roles, notif_insert
        label = doc.get("type_label") or "Kasbon"
        nominal = f"Rp {float(doc.get('amount') or 0):,.0f}".replace(",", ".")
        excl = set(await _kasbon_owner_user_ids(db, doc))
        if stage == "review":
            excl.add((actor or {}).get("id"))   # yang menekan "Ajukan" (bisa HR atas nama karyawan)
        if stage == "review":
            kw = dict(subtype="kasbon_submitted", target_roles=decider_roles("hr", HR_ROLES),
                      title=f"{label} {doc.get('request_number', '')} menunggu review HR".strip(),
                      body=f"{doc.get('employee_name') or 'Karyawan'} mengajukan {label.lower()} {nominal}"
                           + (f" — {doc.get('purpose')}" if doc.get("purpose") else "") + ".",
                      meta={"link_module": "hr-kasbon"})
        else:
            kw = dict(subtype="kasbon_disburse_pending", target_roles=decider_roles("finance", FINANCE_ROLES),
                      title=f"{label} {doc.get('request_number', '')} disetujui HR — menunggu pencairan".strip(),
                      body=f"{label} {doc.get('employee_name') or 'karyawan'} {nominal} siap dicairkan Keuangan.",
                      meta={"link_module": "fin-kasbon"})
        return await notif_insert(db, type="rahaza", severity="warning", source_type="kasbon",
                                  source_id=doc.get("id"), source_ref=doc.get("request_number"),
                                  exclude_user_ids=sorted(x for x in excl if x), status="sent", **kw)
    except Exception:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan transaksi
        _log.warning("[kasbon] notifikasi Perlu Tindakan gagal (%s)", doc.get("request_number"), exc_info=True)
        return None


async def close_kasbon_notifs(db, req_id: str) -> int:
    try:
        from utils.notif_unified import resolve_for_source
        return await resolve_for_source(db, "dewi_kasbon_requests", req_id)
    except Exception:  # noqa: BLE001
        return 0

# F13 — modul ini menyentuh UANG (pencairan kasbon + jurnalnya). Tanpa logger,
# satu-satunya jejak kegagalan posting adalah nilai balik yang sering tidak
# diperiksa pemanggilnya.
_log = logging.getLogger(__name__)


def _gl_flags(gl_result: dict) -> dict:
    if gl_result.get("ok"):
        return {"gl_je_id": gl_result.get("je_id"), "gl_je_number": gl_result.get("je_number"),
                "post_error": None, "updated_at": _now().isoformat()}
    return {"post_error": gl_result.get("error") or "posting GL gagal", "updated_at": _now().isoformat()}


async def _post_kasbon_gl(db, event_type: str, source_ref: str, memo: str, amount: float, user: dict, je_date=None,
                          cash_code: str | None = None):
    """Fire GL posting for kasbon events. Graceful — never raises.

    2026-11-02 (P5 butir 7): `cash_code` = akun GL rekening yang DIPILIH pengguna (sudah divalidasi
    kas/bank oleh pemanggil). Dulu selalu akun profil (1-1201) walau uang keluar dari Kas Kecil/Mandiri."""
    try:
        from routes.rahaza_posting import _create_posted_je
        from routes.rahaza_posting_profiles import get_mapping
        mapping = await get_mapping(db, event_type)
        if not mapping:
            return {"ok": False, "error": f"Posting profile '{event_type}' tidak ditemukan."}
        if event_type == "employee_loan_disbursement":
            lines = [
                {"account_code": mapping.get("debit_employee_loan_receivable") or mapping.get("debit_loan_receivable"),
                 "debit": amount, "credit": 0, "description": memo},
                {"account_code": cash_code or mapping.get("credit_cash"),
                 "debit": 0, "credit": amount, "description": memo},
            ]
        elif event_type == "employee_loan_repayment_payroll":
            lines = [
                {"account_code": mapping.get("debit_salary_payable"),
                 "debit": amount, "credit": 0, "description": memo},
                {"account_code": mapping.get("credit_employee_loan_receivable") or mapping.get("credit_loan_receivable"),
                 "debit": 0, "credit": amount, "description": memo},
            ]
        elif event_type == "employee_loan_repayment_manual":
            lines = [
                {"account_code": cash_code or mapping.get("debit_bank"),
                 "debit": amount, "credit": 0, "description": memo},
                {"account_code": mapping.get("credit_employee_loan_receivable") or mapping.get("credit_loan_receivable"),
                 "debit": 0, "credit": amount, "description": memo},
            ]
        else:
            return {"ok": False, "error": f"Unknown kasbon event_type: {event_type}"}
        if je_date is None:
            je_date = today_wib()
        elif isinstance(je_date, str):
            try:
                je_date = date.fromisoformat(je_date[:10])
            except ValueError:
                je_date = today_wib()
        return await _create_posted_je(db, je_date, memo, event_type, source_ref, lines, user)
    except Exception as exc:
        # F13 — DULU kegagalan posting jurnal kasbon hanya dikembalikan sebagai
        # `{"ok": False}` TANPA satu baris log. Pemanggil di beberapa jalur hanya
        # membaca hasilnya untuk ditampilkan, jadi kasbon bisa CAIR (uang keluar)
        # sementara jurnalnya tidak pernah terbentuk — dan tidak ada jejak untuk
        # menemukannya lagi. Tetap non-blocking supaya pencairan tidak menggantung,
        # tapi kini selalu meninggalkan bukti.
        _log.exception(
            "[kasbon] posting jurnal GAGAL event=%s source_ref=%s — kasbon "
            "berpotensi tercatat tanpa jurnal, perlu penjurnalan manual",
            event_type, source_ref)
        return {"ok": False, "error": str(exc)}


async def kasbon_limit_check(db, employee_id: str, amount: float, installment_count: int) -> dict:
    """K25 (2026-11-02): batas kasbon dari `rahaza_payroll_settings.kasbon`. Bawaan 0 = tanpa batas.

    Return {ok, errors[], warnings[], base_salary, max_amount}. `errors` = melanggar batas yang terisi;
    `warnings` = batas % terisi tetapi gaji pokok karyawan tidak diketahui (bukan skema bulanan) —
    HR yang menilai saat review."""
    from routes.rahaza_payroll_settings import get_kasbon_settings
    cfg = await get_kasbon_settings(db)
    pct = float(cfg.get("max_pct_of_base_salary") or 0)
    max_inst = int(cfg.get("max_installments") or 0)
    out = {"ok": True, "errors": [], "warnings": [], "base_salary": None, "max_amount": None,
           "max_pct_of_base_salary": pct, "max_installments": max_inst}
    if max_inst > 0 and int(installment_count or 1) > max_inst:
        out["errors"].append(f"Jumlah cicilan {installment_count}× melebihi batas {max_inst}×.")
    if pct > 0:
        prof = await db.rahaza_payroll_profiles.find_one(
            {"employee_id": employee_id, "active": True, "pay_scheme": "monthly"}, {"_id": 0, "base_rate": 1})
        base = float((prof or {}).get("base_rate") or 0)
        if base > 0:
            cap = round(base * pct / 100.0)
            out.update(base_salary=base, max_amount=cap)
            if float(amount) > cap + 0.01:
                out["errors"].append(
                    f"Nominal Rp {float(amount):,.0f} melebihi batas {pct:g}% × gaji pokok Rp {base:,.0f} "
                    f"= Rp {cap:,.0f}.".replace(",", "."))
        else:
            out["warnings"].append(f"Batas {pct:g}% gaji pokok tidak bisa dicek: karyawan tidak punya Profil Gaji "
                                   "bulanan aktif. HR menilai saat review.")
    out["ok"] = not out["errors"]
    return out


def _now():
    return datetime.now(timezone.utc)


def _uid():
    return str(uuid.uuid4())[:12]


def _sid():
    return str(uuid.uuid4())[:8]


def _ser(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


# ─── Request Submit ───────────────────────────────────────────────────────────
@router.post("/requests")
async def submit_kasbon_request(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    body = await request.json()

    req_type = body.get("type", "kasbon")
    if req_type not in ("kasbon", "pinjaman"):
        raise HTTPException(400, "type harus 'kasbon' atau 'pinjaman'")

    amount = float(body.get("amount", 0))
    if amount <= 0:
        raise HTTPException(400, "Jumlah harus lebih dari 0")

    installment_count = int(body.get("installment_count", 1))
    if req_type == "kasbon":
        installment_count = 1

    if installment_count < 1:
        raise HTTPException(400, "Jumlah cicilan minimal 1")

    installment_amount = math.ceil(amount / installment_count)

    # Get employee info
    employee_id = body.get("employee_id") or user.get("employee_id") or user.get("id")
    _self_ids = {user.get("employee_id"), user.get("id")}
    if employee_id not in _self_ids and (user.get("role") or "").lower() not in {r.lower() for r in _HR_OR_FIN} | {"superadmin", "admin"}:
        raise HTTPException(403, "Kasbon hanya bisa diajukan untuk diri sendiri; pengajuan atas nama karyawan lain hanya oleh HR/Keuangan.")  # FIN-03
    emp = await db.rahaza_employees.find_one(
        {"$or": [{"id": employee_id}, {"employee_id": employee_id}]}, {"_id": 0}
    )
    if not emp:
        # Try lookup by email
        emp = await db.rahaza_employees.find_one({"email": user.get("email")}, {"_id": 0})

    emp_name = (emp or {}).get("name") or body.get("employee_name") or user.get("name", "")
    emp_code = (emp or {}).get("employee_code") or (emp or {}).get("code") or ""
    department = (emp or {}).get("department") or body.get("department") or ""
    emp_email = (emp or {}).get("email") or user.get("email", "")
    actual_emp_id = (emp or {}).get("id") or (emp or {}).get("employee_id") or employee_id

    # 2026-11-02 (K25): batas kasbon (% gaji pokok, maks cicilan) dari Pengaturan Payroll.
    limit = await kasbon_limit_check(db, actual_emp_id, amount, installment_count)
    if not limit["ok"]:
        raise HTTPException(400, "Pengajuan melebihi batas kasbon: " + " ".join(limit["errors"]))

    # ── FASE G (sesi #18) — KEBIJAKAN PENOMORAN DITEGAKKAN ────────────────────
    # Sebelum ini nomor SELALU dibuat otomatis (`KSB-00001`/`PIN-00001`) sehingga
    # setelan "Otomatis/Manual" di Administrasi Sistem → Penomoran Dokumen tidak
    # berpengaruh apa pun untuk dokumen ini — setelan yang tidak ditegakkan adalah
    # setelan yang BERBOHONG. Sekarang satu pintu `issue_number`:
    #   · mode OTOMATIS → nomor dibuat mengikuti FORMAT yang disetel owner, dan
    #     nomor ketikan DITOLAK (bukan diabaikan diam-diam);
    #   · mode MANUAL  → nomor wajib diisi DAN wajib mengikuti pola formatnya.
    # Kasbon & Pinjaman memakai KUNCI BERBEDA walau satu koleksi, supaya memindah
    # kebijakan kasbon tidak ikut memaksa pinjaman.
    req_number = await issue_number(
        db,
        "dewi_kasbon_requests.request_number" if req_type == "kasbon"
        else "dewi_kasbon_requests.request_number_pinjaman",
        requested=(body.get("request_number") or ""))

    # Documents: [{name, data, mime_type}] — base64 encoded
    documents = body.get("documents") or []

    doc = {
        "id": _uid(),
        "request_number": req_number,
        "employee_id": actual_emp_id,
        "employee_name": emp_name,
        "employee_code": emp_code,
        "employee_email": emp_email,
        "department": department,
        "type": req_type,
        "type_label": "Kasbon" if req_type == "kasbon" else "Pinjaman",
        "amount": amount,
        "purpose": body.get("purpose", ""),
        "notes": body.get("notes", ""),
        "documents": documents,
        "installment_count": installment_count,
        "installment_amount": installment_amount,
        # Status
        "status": "submitted",
        # HR review
        "hr_reviewed_by": None,
        "hr_reviewed_at": None,
        "hr_notes": None,
        # Finance disbursal
        "disbursed_by": None,
        "disbursed_at": None,
        "disbursement_date": None,
        "deduction_start_period": None,
        "finance_notes": None,
        # Repayment tracking
        "paid_amount": 0.0,
        "outstanding_balance": amount,
        "repayments": [],
        "limit_warnings": limit["warnings"],  # 2026-11-02 (K25)
        # Meta
        "submitted_by": user.get("email", ""),
        "submitted_by_name": user.get("name", ""),
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }

    await db.dewi_kasbon_requests.insert_one(doc)
    doc.pop("_id", None)
    await notify_kasbon_stage(db, doc, stage="review", actor=user)   # 2026-11-02 (K30)
    return {"ok": True, "request": doc}


# ─── List ─────────────────────────────────────────────────────────────────────
@router.get("/requests")
async def list_kasbon_requests(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
    status: Optional[str] = None,
    type: Optional[str] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    filt = {}
    if status:
        filt["status"] = status
    if type:
        filt["type"] = type
    if employee_id:
        filt["employee_id"] = employee_id
    if department:
        filt["department"] = department
    # 2026-11-02 (P5 butir 10): selain HR/Keuangan/owner/super HANYA kasbon milik sendiri.
    # Dulu akun packing membaca kasbon semua karyawan (nominal & keperluan), termasuk lewat ?employee_id=.
    if not _is_privileged(user):
        own = sorted(await _own_employee_ids(db, user))
        mine = [{"employee_id": {"$in": own}}] if own else []
        if user.get("email"):
            mine.append({"submitted_by": user["email"]})
        if not mine:
            return {"ok": True, "total": 0, "requests": []}
        filt["$or"] = mine
        if employee_id and employee_id not in own:
            return {"ok": True, "total": 0, "requests": []}

    total = await db.dewi_kasbon_requests.count_documents(filt)
    docs = (
        await db.dewi_kasbon_requests.find(filt, {"_id": 0, "documents": 0})
        .sort("created_at", -1)
        .skip((page - 1) * limit)
        .to_list(limit)
    )
    return {"ok": True, "total": total, "requests": [_ser(d) for d in docs]}


# ─── My Requests (Staff) ──────────────────────────────────────────────────────
@router.get("/my-requests")
async def my_kasbon_requests(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
    status: Optional[str] = None,
):
    emp = await db.rahaza_employees.find_one({"email": user.get("email")}, {"_id": 0})
    emp_id = (emp or {}).get("id") or (emp or {}).get("employee_id") or user.get("employee_id")

    filt = {}
    if emp_id:
        filt["employee_id"] = emp_id
    else:
        filt["submitted_by"] = user.get("email", "")

    if status:
        filt["status"] = status

    docs = (
        await db.dewi_kasbon_requests.find(filt, {"_id": 0, "documents": 0})
        .sort("created_at", -1)
        .to_list(100)
    )
    return {"ok": True, "requests": [_ser(d) for d in docs]}


# ─── Detail ───────────────────────────────────────────────────────────────────
@router.get("/requests/{req_id}")
async def get_kasbon_detail(
    req_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    doc = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Kasbon tidak ditemukan")
    # 2026-11-02 (P5 butir 10): detail kasbon orang lain hanya untuk HR/Keuangan/owner/super.
    if not _is_privileged(user) and not _owns(doc, await _own_employee_ids(db, user), user):
        raise HTTPException(403, "Anda hanya boleh melihat kasbon milik sendiri.")
    return {"ok": True, "request": _ser(doc)}


# ─── HR Review ────────────────────────────────────────────────────────────────
@router.patch("/requests/{req_id}/hr-review", dependencies=only(*HR_ROLES))  # FIN-03
async def hr_review_kasbon(
    req_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    body = await request.json()
    action = body.get("action")  # "approve" | "reject"
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action harus 'approve' atau 'reject'")

    doc = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Kasbon tidak ditemukan")
    if doc.get("status") != "submitted":
        raise HTTPException(400, f"Status saat ini '{doc.get('status')}', hanya bisa review saat 'submitted'")
    # 2026-11-02 (K25): pengaju ≠ penyetuju — HR tidak boleh mereview kasbon miliknya / yang ia ajukan.
    ensure_not_self_approval(doc, user, own_employee_ids=await _own_employee_ids(db, user), what="kasbon")

    new_status = "hr_approved" if action == "approve" else "hr_rejected"
    upd = {
        "status": new_status,
        "hr_reviewed_by": user.get("name", user.get("email", "")),
        "hr_reviewed_by_id": user.get("id"),
        "hr_reviewed_at": _now().isoformat(),
        "hr_notes": body.get("notes", ""),
        "updated_at": _now().isoformat(),
    }
    if action == "approve":
        # K25: nilai disetujui ≤ nilai diminta (opsional `approved_amount`), dan tetap dalam batas kasbon.
        requested = float(doc.get("amount") or 0)
        raw = body.get("approved_amount")
        approved = requested
        if raw not in (None, ""):
            try:
                approved = float(raw)
            except (TypeError, ValueError):
                raise HTTPException(400, "approved_amount harus angka.")
            if approved <= 0:
                raise HTTPException(400, "Nilai disetujui harus > 0 (gunakan Tolak bila tidak disetujui).")
            if approved > requested + 0.01:
                raise HTTPException(400, f"Nilai disetujui (Rp {approved:,.0f}) melebihi nilai diminta "
                                         f"(Rp {requested:,.0f}).".replace(",", "."))
        count = int(doc.get("installment_count") or 1)
        limit = await kasbon_limit_check(db, doc.get("employee_id"), approved, count)
        if not limit["ok"]:
            raise HTTPException(400, "Tidak bisa disetujui — melebihi batas kasbon: " + " ".join(limit["errors"]))
        if abs(approved - requested) > 0.01:
            upd.update({"requested_amount": requested, "amount": approved,
                        "outstanding_balance": approved, "installment_amount": math.ceil(approved / max(count, 1))})
    await db.dewi_kasbon_requests.update_one({"id": req_id, "status": "submitted"}, {"$set": upd})
    updated = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})
    # 2026-11-02 (P5 butir 12): beri tahu karyawan pemohon hasil review (tautan: Portal Saya → Kasbon).
    label = doc.get("type_label") or "Kasbon"
    nominal = f"Rp {float((updated or doc).get('amount') or 0):,.0f}".replace(",", ".")
    approved = action == "approve"
    await notify_requester(
        db, user_id=await _kasbon_requester_user_id(db, doc),
        subtype="kasbon_approved" if approved else "kasbon_rejected",
        severity="success" if approved else "warning",
        title=f"{label} {doc.get('request_number', '')} {'disetujui HR' if approved else 'ditolak HR'}".strip(),
        body=(f"Pengajuan {label.lower()} {nominal} " + ("disetujui HR dan menunggu pencairan Keuangan."
              if approved else "ditolak HR.") + (f" Catatan: {body.get('notes')}" if body.get("notes") else "")),
        link_module="portal-kasbon", source_type="kasbon", source_id=req_id,
        source_ref=doc.get("request_number"))
    await close_kasbon_notifs(db, req_id)   # 2026-11-02 (K30): review HR selesai
    if approved and updated:
        await notify_kasbon_stage(db, updated, stage="disburse", actor=user)
    return {"ok": True, "request": _ser(updated)}


# ─── Finance Disburse ─────────────────────────────────────────────────────────
@router.patch("/requests/{req_id}/disburse", dependencies=only(*FINANCE_ROLES))  # FIN-03
async def finance_disburse(
    req_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    body = await request.json()

    doc = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Kasbon tidak ditemukan")
    if doc.get("status") != "hr_approved":
        raise HTTPException(400, f"Status '{doc.get('status')}', harus 'hr_approved' untuk dicairkan")

    # 2026-11-02 (P5 butir 7): tanggal jurnal = TANGGAL CAIR yang diisi (WIB), rekening = yang DIPILIH.
    # Dulu jurnal bertanggal hari ini & selalu Cr 1-1201 walau dikirim Kas Kecil (kasbon 15 Okt → JE 1 Nov).
    disb_date = parse_ymd(body.get("disbursement_date"), field="tanggal pencairan")
    disbursement_date = disb_date.isoformat()
    deduction_start_period = (body.get("deduction_start_period") or disbursement_date[:7]).strip()[:7]
    from routes.rahaza_posting_profiles import get_mapping
    _map = await get_mapping(db, "employee_loan_disbursement")
    acc = await resolve_payment_account(
        db, cash_account_id=body.get("cash_account_id") or body.get("bank_account_id"),
        gl_code=body.get("bank_account_code"), default_code=_map.get("credit_cash"), purpose="Pencairan kasbon")

    upd = {
        "status": "disbursed",
        "disbursed_by": user.get("name", user.get("email", "")),
        "disbursed_at": _now().isoformat(),
        "disbursement_date": disbursement_date,
        "deduction_start_period": deduction_start_period,
        "finance_notes": body.get("finance_notes", ""),
        "disbursement_cash_account_id": acc.get("cash_account_id"),
        "disbursement_account_code": acc["gl_code"],
        "disbursement_account_name": acc["name"],
        "updated_at": _now().isoformat(),
    }
    res = await db.dewi_kasbon_requests.update_one({"id": req_id, "status": "hr_approved"}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(409, "Kasbon ini baru saja diproses pengguna lain — muat ulang daftar.")
    updated = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})

    # Auto-GL: Dr Kasbon Karyawan / Cr Rekening yang dipilih
    amount_val = float(doc.get("amount", 0))
    emp_name_val = doc.get("employee_name", "")
    gl_result = await _post_kasbon_gl(
        db, "employee_loan_disbursement",
        f"kasbon-disburse-{req_id}",
        f"Kasbon Cair — {emp_name_val} — {doc.get('request_number','')}",
        amount_val, user, je_date=disb_date, cash_code=acc["gl_code"],
    )
    await db.dewi_kasbon_requests.update_one({"id": req_id}, {"$set": _gl_flags(gl_result)})
    await close_kasbon_notifs(db, req_id)   # 2026-11-02 (K30): pencairan selesai
    # T-10: kegagalan posting GL TIDAK boleh tampil sebagai "berhasil" di layar.
    return {"ok": bool(gl_result.get("ok")), "request": _ser(updated), "gl": gl_result,
            "message": None if gl_result.get("ok") else
            f"Kasbon dicairkan tetapi jurnal GL GAGAL: {gl_result.get('error')}"}


# ─── Record Repayment ─────────────────────────────────────────────────────────
@router.post("/requests/{req_id}/repay")
async def record_repayment(
    req_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    body = await request.json()
    amount = float(body.get("amount", 0))
    if amount <= 0:
        raise HTTPException(400, "Jumlah pembayaran harus > 0")

    doc = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Kasbon tidak ditemukan")
    if doc.get("status") not in ("disbursed", "active"):
        raise HTTPException(400, "Kasbon harus berstatus aktif untuk dicatat pembayarannya")

    outstanding = float(doc.get("outstanding_balance", 0))
    if (user.get("role") or "").lower() not in _PRIVILEGED_ROLES:
        raise HTTPException(403, "Hanya HR/Keuangan yang boleh mencatat pembayaran kasbon.")  # FIN-03
    # 2026-11-02 (P5 butir 5): "Potong Gaji" dari Keuangan DIHAPUS. Dulu entri ini langsung melunasi kasbon
    # (Dr 2-1200 / Cr 1-1320) lalu payroll MELEWATI potongan periode itu → gaji dibayar penuh dan uangnya
    # (400.000 pada uji Basah) tidak pernah ditarik. Potongan gaji kini HANYA lewat run payroll FINAL;
    # endpoint ini khusus pembayaran uang nyata (tunai/transfer) ke rekening kas/bank yang dipilih.
    method = body.get("method", "manual")
    if method == "payroll_deduction":
        raise HTTPException(400, (
            "Potong gaji tidak dicatat manual — potongan kasbon tercatat otomatis saat run payroll periode "
            f"{doc.get('deduction_start_period') or 'berjalan'} difinalisasi. Gunakan 'Bayar Manual' hanya bila "
            "karyawan benar-benar membayar tunai/transfer."))
    period = body.get("period") or ""
    pay_date = parse_ymd(body.get("date"), field="tanggal pembayaran")
    from routes.rahaza_posting_profiles import get_mapping
    _map = await get_mapping(db, "employee_loan_repayment_manual")
    acc = await resolve_payment_account(
        db, cash_account_id=body.get("cash_account_id") or body.get("bank_account_id"),
        gl_code=body.get("bank_account_code"), default_code=_map.get("debit_bank"), purpose="Pembayaran kasbon")
    actual = min(amount, outstanding)
    new_paid = float(doc.get("paid_amount", 0)) + actual
    new_outstanding = outstanding - actual
    new_status = "paid_off" if new_outstanding <= 0.01 else doc.get("status")

    repayment_entry = {
        "id": _sid(),
        "amount": round(actual, 2),
        "date": pay_date.isoformat(),
        "method": method,
        "period": period,
        "cash_account_id": acc.get("cash_account_id"),
        "account_code": acc["gl_code"],
        "notes": body.get("notes", ""),
        "by": user.get("name", user.get("email", "")),
        "created_at": _now().isoformat(),
    }

    # 2026-11-02 (P5 butir 5/7): JURNAL DULU (Dr rekening dipilih / Cr piutang kasbon, tanggal bayar);
    # saldo kasbon hanya berkurang bila jurnal uang masuk itu benar-benar terbentuk.
    emp_name_rep = doc.get("employee_name", "")
    gl_result = await _post_kasbon_gl(
        db, "employee_loan_repayment_manual",
        f"kasbon-repay-{repayment_entry['id']}",
        f"Angsuran Kasbon — {emp_name_rep} — {doc.get('request_number','')} ({method})",
        round(actual, 2), user, je_date=pay_date, cash_code=acc["gl_code"],
    )
    if not gl_result.get("ok"):
        raise HTTPException(400, f"Pembayaran TIDAK dicatat — jurnal gagal: {gl_result.get('error')}")

    upd = {
        "paid_amount": round(new_paid, 2),
        "outstanding_balance": round(new_outstanding, 2),
        "status": new_status,
        "updated_at": _now().isoformat(),
    }
    await db.dewi_kasbon_requests.update_one(
        {"id": req_id},
        {"$set": upd, "$push": {"repayments": repayment_entry}},
    )
    await db.dewi_kasbon_requests.update_one({"id": req_id}, {"$set": _gl_flags(gl_result)})
    updated = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})
    return {"ok": bool(gl_result.get("ok")), "request": _ser(updated), "repayment": repayment_entry,
            "gl": gl_result,
            "message": None if gl_result.get("ok") else
            f"Angsuran dicatat tetapi jurnal GL GAGAL: {gl_result.get('error')}"}


# ─── Cancel ───────────────────────────────────────────────────────────────────
@router.post("/requests/{req_id}/cancel")
async def cancel_kasbon(
    req_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    body = await request.json()
    doc = await db.dewi_kasbon_requests.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Kasbon tidak ditemukan")
    if doc.get("status") not in ("submitted",):
        raise HTTPException(400, "Hanya bisa batalkan saat status 'submitted'")

    await db.dewi_kasbon_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "cancelled",
            "cancel_reason": body.get("reason", ""),
            "cancelled_by": user.get("email", ""),
            "updated_at": _now().isoformat(),
        }},
    )
    await close_kasbon_notifs(db, req_id)   # 2026-11-02 (K30)
    return {"ok": True}


# ─── Stats Dashboard ──────────────────────────────────────────────────────────
@router.get("/stats")
async def kasbon_stats(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    # 2026-11-02 (P5 butir 10): statistik + daftar aktif/pending memuat kasbon SEMUA karyawan.
    if not _is_privileged(user):
        raise HTTPException(403, "Statistik kasbon hanya untuk HR/Keuangan.")
    all_docs = await db.dewi_kasbon_requests.find({}, {"_id": 0, "documents": 0}).to_list(1000)

    pending_hr = [d for d in all_docs if d.get("status") == "submitted"]
    pending_finance = [d for d in all_docs if d.get("status") == "hr_approved"]
    active = [d for d in all_docs if d.get("status") == "disbursed"]
    paid_off = [d for d in all_docs if d.get("status") == "paid_off"]

    total_outstanding = sum(float(d.get("outstanding_balance", 0)) for d in active)
    total_disbursed_all = sum(float(d.get("amount", 0)) for d in all_docs if d.get("status") in ("disbursed", "paid_off"))

    # This month (robust: created_at bisa str ISO ATAU datetime — data seed lama menyimpan datetime)
    # 2026-11-02 (No.54a): "bulan ini" = bulan WIB, dan created_at (UTC) dibaca dalam WIB — dulu
    # pengajuan tgl 1 pukul 00:00–06:59 WIB terhitung bulan LALU.
    now_ym = fmt_wib("%Y-%m")

    def _ym(v):
        if isinstance(v, str) and len(v) > 10:
            try:
                v = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return v[:7]
        if isinstance(v, datetime):
            return fmt_wib("%Y-%m", v)
        return str(v or "")[:7]

    this_month = [d for d in all_docs if _ym(d.get("created_at")) == now_ym]

    return {
        "ok": True,
        "stats": {
            "pending_hr": len(pending_hr),
            "pending_finance": len(pending_finance),
            "active_count": len(active),
            "paid_off_count": len(paid_off),
            "total_outstanding": round(total_outstanding, 2),
            "total_disbursed_all": round(total_disbursed_all, 2),
            "this_month_requests": len(this_month),
            "this_month_amount": sum(float(d.get("amount", 0)) for d in this_month),
        },
        "active_list": [_ser(d) for d in active],
        "pending_hr_list": [_ser(d) for d in pending_hr],
    }


# ─── Payroll Deductions (per employee per period) ─────────────────────────────
@router.get("/employee/{emp_id}/deductions")
async def get_employee_deductions(
    emp_id: str,
    period: str = Query(..., description="Format YYYY-MM"),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    """Ambil potongan kasbon/pinjaman untuk karyawan pada periode tertentu."""
    # 2026-11-02 (P5 butir 10): hanya HR/Keuangan/owner/super atau karyawan ybs.
    if not _is_privileged(user) and emp_id not in await _own_employee_ids(db, user):
        raise HTTPException(403, "Anda hanya boleh melihat potongan kasbon milik sendiri.")
    active_ks = await db.dewi_kasbon_requests.find({
        "employee_id": emp_id,
        "status": "disbursed",
        "deduction_start_period": {"$lte": period},
    }, {"_id": 0, "documents": 0}).to_list(50)

    deductions = []
    for ks in active_ks:
        outstanding = float(ks.get("outstanding_balance", 0))
        if outstanding <= 0:
            continue
        if ks.get("type") == "kasbon":
            amt = outstanding
        else:
            amt = min(float(ks.get("installment_amount", 0)), outstanding)
        if amt > 0:
            deductions.append({
                "kasbon_id": ks["id"],
                "request_number": ks.get("request_number", ""),
                "type": ks.get("type"),
                "type_label": ks.get("type_label", ""),
                "amount": round(amt, 2),
                "outstanding_balance": round(outstanding, 2),
                "label": f"Potongan {ks.get('type_label','Kasbon')} {ks.get('request_number','')}",
            })

    return {
        "ok": True,
        "employee_id": emp_id,
        "period": period,
        "deductions": deductions,
        "total_deduction": sum(d["amount"] for d in deductions),
    }


# ─── Apply Payroll Deductions (batch — called after payroll finalized) ─────────
async def apply_payroll_deductions_core(db, period: str, deductions: list, user: dict,
                                        run_id: str | None = None, run_number: str = "",
                                        je_date=None) -> dict:
    """Iter 119 (B-07): SATU mesin untuk memangkas saldo kasbon dari potongan gaji.
    Dipanggil otomatis oleh finalize payroll (dedupe per run_id) dan oleh endpoint batch (dedupe per periode).
    Setiap potongan → repayment entry + JE Dr Hutang Gaji / Cr Piutang Karyawan."""
    results = []
    for ded in deductions or []:
        kasbon_id = ded.get("kasbon_id")
        amount = float(ded.get("amount", 0) or 0)
        if not kasbon_id or amount <= 0:
            continue

        doc = await db.dewi_kasbon_requests.find_one({"id": kasbon_id}, {"_id": 0})
        if not doc or doc.get("status") not in ("disbursed", "active"):
            results.append({"kasbon_id": kasbon_id, "skipped": True, "reason": "Kasbon tidak aktif/ditemukan"})
            continue

        reps = doc.get("repayments") or []
        # FIN-16: dedupe pada (kasbon, periode, method=payroll_deduction) di SEMUA jalur — dengan atau tanpa run_id
        already = any(
            (run_id and r.get("run_id") == run_id)
            or (r.get("period") == period and r.get("method") == "payroll_deduction")
            for r in reps
        )
        if already:
            results.append({"kasbon_id": kasbon_id, "skipped": True, "reason": "Sudah dicatat untuk run/periode ini"})
            continue

        outstanding = float(doc.get("outstanding_balance", 0))
        actual = round(min(amount, outstanding), 2)
        if actual <= 0:
            results.append({"kasbon_id": kasbon_id, "skipped": True, "reason": "Saldo kasbon sudah nol"})
            continue
        new_paid = float(doc.get("paid_amount", 0)) + actual
        new_outstanding = outstanding - actual
        new_status = "paid_off" if new_outstanding <= 0.01 else "disbursed"

        repayment_entry = {
            "id": _sid(),
            "amount": actual,
            "date": (str(je_date)[:10] if je_date else today_wib().isoformat()),
            "method": "payroll_deduction",
            "period": period,
            "run_id": run_id,
            "run_number": run_number,
            "notes": f"Auto-potong gaji periode {period}" + (f" ({run_number})" if run_number else ""),
            "by": user.get("name", "Payroll System"),
            "created_at": _now().isoformat(),
        }

        # 2026-11-02 (P5 butir 3/5): JURNAL DULU, saldo kasbon SESUDAH jurnal sukses. Dulu kasbon
        # ditandai lunas lebih dulu; bila jurnal potongan ditolak, buku pembantu kasbon = 0 sementara
        # GL 1-1320 masih 500.000. Jurnal idempoten per source_ref → aman diulang (retry-post).
        gl_result = await _post_kasbon_gl(
            db, "employee_loan_repayment_payroll",
            f"kasbon-payroll-{kasbon_id}-{run_id or period}",
            f"Potong gaji {period} — Kasbon {doc.get('request_number') or kasbon_id} — {doc.get('employee_name', '')}",
            actual, user, je_date=je_date,
        )
        row = {"kasbon_id": kasbon_id, "request_number": doc.get("request_number"),
               "employee_name": doc.get("employee_name"), "gl": gl_result}
        if not gl_result.get("ok"):
            results.append({**row, "amount_deducted": 0, "new_status": doc.get("status"),
                            "reason": "Jurnal potongan gagal — kasbon TIDAK ditandai terpotong"})
            continue
        # Penjaga balapan: hanya bila belum ada potongan untuk run/periode ini (dua permintaan paralel
        # tidak boleh memotong saldo dua kali).
        dedupe = [{"period": period, "method": "payroll_deduction"}] + ([{"run_id": run_id}] if run_id else [])
        res = await db.dewi_kasbon_requests.update_one(
            {"id": kasbon_id, "status": {"$in": ["disbursed", "active"]},
             "repayments": {"$not": {"$elemMatch": {"$or": dedupe}}}},
            {"$set": {
                "paid_amount": round(new_paid, 2),
                "outstanding_balance": round(new_outstanding, 2),
                "status": new_status,
                "updated_at": _now().isoformat(),
            }, "$push": {"repayments": repayment_entry}},
        )
        if not res.matched_count:
            results.append({**row, "skipped": True, "reason": "Sudah dicatat untuk run/periode ini"})
            continue
        results.append({**row, "amount_deducted": actual, "new_outstanding": round(new_outstanding, 2),
                        "new_status": new_status})
    gl_failed = [r for r in results if not r.get("skipped") and not (r.get("gl") or {}).get("ok")]
    return {"ok": not gl_failed, "period": period, "run_id": run_id, "processed": len(results),
            "gl_failed": len(gl_failed), "results": results,
            "message": None if not gl_failed else
            (f"{len(gl_failed)} potongan kasbon TIDAK dicatat karena jurnalnya gagal: "
             f"{(gl_failed[0].get('gl') or {}).get('error')} — kasbon tetap outstanding; ulangi lewat Retry GL run.")}


async def restore_payroll_deductions_core(db, run_id: str, user: dict, reason: str = "") -> dict:
    """2026-11-02 (K34): kembalikan potongan kasbon dari run payroll yang DIBATALKAN.

    Entri angsuran `payroll_deduction` milik run itu dipindah ke `repayments_reversed` (jejak audit),
    saldo outstanding dikembalikan, status kembali 'disbursed'. Jurnalnya (Dr 2-1200 / Cr 1-1320)
    dibalik oleh pembatalan run (reverse_journal_entry). Karena entri dipindah, run pengganti untuk
    periode yang sama akan memotong kasbon itu lagi (dedupe periode tidak lagi menahannya)."""
    results = []
    docs = await db.dewi_kasbon_requests.find(
        {"repayments": {"$elemMatch": {"run_id": run_id, "method": "payroll_deduction"}}},
        {"_id": 0, "documents": 0}).to_list(500)
    now = _now().isoformat()
    for doc in docs:
        reps = doc.get("repayments") or []
        mine = [r for r in reps if r.get("run_id") == run_id and r.get("method") == "payroll_deduction"]
        keep = [r for r in reps if r not in mine]
        amt = round(sum(float(r.get("amount") or 0) for r in mine), 2)
        new_out = round(float(doc.get("outstanding_balance") or 0) + amt, 2)
        new_paid = round(max(0.0, float(doc.get("paid_amount") or 0) - amt), 2)
        new_status = "disbursed" if new_out > 0.01 else doc.get("status")
        reversed_rows = list(doc.get("repayments_reversed") or []) + [
            {**r, "reversed_at": now, "reversed_reason": reason, "reversed_by": user.get("name", "")} for r in mine]
        res = await db.dewi_kasbon_requests.update_one(
            {"id": doc["id"], "repayments": {"$elemMatch": {"run_id": run_id, "method": "payroll_deduction"}}},
            {"$set": {"repayments": keep, "repayments_reversed": reversed_rows, "outstanding_balance": new_out,
                      "paid_amount": new_paid, "status": new_status, "updated_at": now}})
        if res.matched_count:
            results.append({"kasbon_id": doc["id"], "request_number": doc.get("request_number"),
                            "employee_name": doc.get("employee_name"), "amount_restored": amt,
                            "new_outstanding": new_out, "new_status": new_status})
    return {"ok": True, "run_id": run_id, "results": results}


@router.post("/apply-payroll-deductions")
async def apply_payroll_deductions(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user=Depends(require_auth),
):
    """Ulang pencatatan potongan kasbon dari SATU run payroll yang sudah FINAL.

    2026-11-02 (P5 butir 5): dulu endpoint ini menerima daftar potongan bebas (tanpa run, tanpa cek
    peran) sehingga kasbon bisa ditandai "dipotong gaji" padahal gaji tidak pernah dipotong. Sekarang:
    hanya HR/Keuangan, wajib `run_id` run berstatus finalized, dan potongan diambil dari slip run itu.
    Body: {run_id}
    """
    if (user.get("role") or "").lower() not in _PRIVILEGED_ROLES:
        raise HTTPException(403, "Hanya HR/Keuangan yang boleh mencatat potongan kasbon payroll.")
    body = await request.json()
    run_id = (body.get("run_id") or "").strip()
    if not run_id:
        raise HTTPException(400, "run_id wajib — potongan kasbon hanya dicatat dari run payroll yang sudah final.")
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") != "finalized" or not run.get("gl_je_number"):
        raise HTTPException(400, "Run payroll belum final atau jurnal gajinya belum terbentuk.")
    slips = await db.rahaza_payslips.find({"run_id": run_id}, {"_id": 0, "employee_id": 1, "deductions": 1}).to_list(500)
    deductions = [{"kasbon_id": d.get("kasbon_id"), "amount": d.get("amount"), "employee_id": s.get("employee_id")}
                  for s in slips for d in (s.get("deductions") or [])
                  if (d.get("type") or "").lower() == "kasbon" and d.get("kasbon_id")]
    return await apply_payroll_deductions_core(
        db, (run.get("period_from") or "")[:7], deductions, user,
        run_id=run_id, run_number=run.get("run_number") or "", je_date=run.get("period_to"))


# ─── Seed Demo Data — DIHAPUS 2026-11-02 (P5 butir 9) ─────────────────────────
# Tombol "Muat Demo" di menu Kasbon SDM memanggil POST /api/dewi/kasbon/seed yang membuat 5 kasbon
# PALSU atas nama karyawan NYATA (tanpa jurnal); payroll lalu memotong 1.000.000 dari gaji Ega untuk
# pinjaman palsu. Endpoint & tombolnya dihapus. Data yang sudah ada TIDAK disentuh.
