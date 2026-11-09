"""
CV. Dewi Aditya — Approval Badge Endpoint
==========================================
Endpoint ringan yang mengembalikan jumlah item yang memerlukan tindakan
berdasarkan peran pengguna yang sedang login.

2026-11-02 (K30) — ikon Approval Inbox terpisah di TopBar DILEBUR ke kotak masuk
bel (tab "Perlu Tindakan"). Hitungan di berkas ini sekarang menjadi SUMBER
"Perlu Tindakan" yang dihitung langsung dari dokumen (`approval_groups`), dipakai
bel (`routes/notification_categories.py`) dengan pengecualian dokumen yang sudah
diwakili notifikasi action terbuka ⇒ satu pekerjaan tidak pernah dihitung dua kali.
Definisi "masih menunggu" diambil dari SATU tabel `utils.notif_unified.SOURCE_RULES`
(dipakai juga resolver yang menutup notifikasi). Endpoint lama tetap ada untuk
kompatibilitas.

GET /api/approval-inbox/badge
  Response:
    {
      "total": 5,
      "pr_pending": 2,         # PR menunggu persetujuan (submitted)
      "ap_pending": 3,         # AP Invoice belum dibayar (sent/partial_paid)
      "hr_pending": 0,         # HR requests (cuti, lembur, dll)
      "categories": [
        {"key": "pr",   "label": "PR Menunggu",     "count": 2, "module_id": "fin-procurement-requests"},
        {"key": "ap",   "label": "AP Belum Bayar",  "count": 3, "module_id": "fin-ap-aging"},
        {"key": "hr",   "label": "HR Persetujuan",  "count": 0, "module_id": "hr-inbox"},
      ]
    }
"""
import logging

from fastapi import APIRouter, Request
from database import get_db
from auth import require_auth, check_role
from utils.notif_unified import SOURCE_RULES, alert_roles_for_portal, rule_open_filter

router = APIRouter(prefix="/api/approval-inbox", tags=["approval-badge"])
logger = logging.getLogger(__name__)

# Peran yang bisa lihat AP invoices (finance-related)
_FINANCE_ROLES = {"superadmin", "admin", "owner", "accounting", "finance",
                  "staff_keuangan", "manager_keuangan"}

# Peran yang bisa lihat & approve PR
_PROCUREMENT_ROLES = {"superadmin", "admin", "owner", "accounting", "finance",
                      "staff_keuangan", "manager_keuangan", "admin_gudang",
                      "supervisor_produksi", "admin_produksi", "manager_produksi"}

# Peran yang bisa lihat HR inbox
_HR_ROLES = {"superadmin", "admin", "owner", "hr", "hr_manager", "staff_hr"}

_SUPER = {"superadmin", "admin", "owner"}


def _warehouse_roles() -> set:
    """Pemutus retur fisik = peran nyata Portal Gudang (SSOT PORTAL_ACCESS ∩ core.roles)."""
    return _SUPER | set(alert_roles_for_portal("warehouse"))


async def _open_keys(db, rule_key: str, *, extra: dict | None = None, limit: int = 2000) -> list:
    """[(koleksi, id)] dokumen yang MASIH menunggu menurut SOURCE_RULES[rule_key]."""
    rule = SOURCE_RULES[rule_key]
    coll = rule["collection"]
    q = rule_open_filter(rule)
    q.update(extra or {})
    rows = await db[coll].find(q, {"_id": 0, "id": 1}).to_list(limit)
    return [(coll, r["id"]) for r in rows if r.get("id")]


def _group(key, label, module_id, icon, keys, exclude, *, tab=None, with_keys=False) -> dict:
    left = [k for k in keys if k not in exclude]
    out = {"key": key, "label": label, "count": len(left), "raw_count": len(keys),
           "module_id": module_id, "icon": icon}
    if tab:
        out["tab"] = tab
    if with_keys:   # Monitoring Staf (10 Nov 2026): dokumen per butir, untuk kewajiban "menunggu siapa"
        out["keys"] = [list(k) for k in keys]
    return out


async def approval_groups(db, user: dict, *, exclude=frozenset(), with_keys: bool = False) -> list:
    """Butir "Perlu Tindakan" yang dihitung LANGSUNG dari dokumen sumber.

    `exclude` = {(koleksi, id)} yang sudah diwakili notifikasi action terbuka
    milik user ini — tidak dihitung lagi di sini (tanpa hitung dobel).
    Grup tetap dikembalikan walau 0 bila peran itu memang pemegang antreannya
    (kompatibel dengan kategori lencana lama).

    `with_keys=True` (Monitoring Staf, 10 Nov 2026) menambah `keys` = [[koleksi, id], ...] per grup — SATU sumber
    "menunggu siapa" untuk kewajiban persetujuan (`core.pantau_staf.katalog`), tidak dihitung ulang di sana."""
    role = (user.get("role") or "").lower()
    uid = user.get("id")
    groups = []
    # 2026-11-02 — ajuan MILIK SENDIRI bukan pekerjaan "Perlu Tindakan" (sama dengan notifikasinya,
    # yang mengecualikan pengaju lewat `exclude_user_ids`).
    not_mine_uid = {"submitted_by": {"$ne": uid}} if uid else {}
    not_mine_email = {"submitted_by": {"$ne": user.get("email")}} if user.get("email") else {}

    # PR menunggu KEPUTUSAN SAYA.
    # 2026-08-07 — dulu: `count_documents({"status": "submitted"})` disaring
    # daftar peran ke-EMPAT yang ditulis ulang di berkas ini. Sekarang memakai
    # mesin yang SAMA dengan inbox (`_eval_approval`).
    pr_keys = []
    try:
        from core.pr_approval import _MODULE_COLLECTION, pending_for_user
        for it in await pending_for_user(db, user):
            coll = _MODULE_COLLECTION.get(it.get("module_id") or "proc-requests") or "dewi_procurement_requests"
            if it.get("id"):
                pr_keys.append((coll, it["id"]))
    except Exception:  # noqa: BLE001 — lencana tidak boleh mematikan TopBar
        logger.debug("[approval-badge] pending_for_user gagal", exc_info=True)
    if pr_keys or role in _PROCUREMENT_ROLES:
        groups.append(_group("pr", "Pembelian menunggu persetujuan Anda", "proc-requests",
                             "shopping-cart", pr_keys, exclude, with_keys=with_keys))

    if role in _FINANCE_ROLES:
        groups.append(_group("ap", "AP Invoice belum dibayar", "fin-ap-aging", "hourglass",
                             await _open_keys(db, "ap_invoice"), exclude, with_keys=with_keys))

    # 2026-11-08: kode peran lama ATAU izin yang sama dengan gerbang HR Inbox (`hr.approve` / `hr.manage`),
    # supaya peran buatan owner yang bisa menyetujui juga melihat hitungannya.
    if role in _HR_ROLES or check_role(user, [], ("hr.approve", "hr.manage")):
        hr_keys = []
        for key in ("leave_manager", "leave_hr", "overtime", "salary_manager", "salary_hr"):
            hr_keys += await _open_keys(db, key, extra=not_mine_uid if key == "overtime" else None)
        groups.append(_group("hr", "SDM perlu persetujuan (cuti, lembur, gaji)", "hr-inbox", "users",
                             hr_keys, exclude, with_keys=with_keys))
        kas = await _open_keys(db, "kasbon_review", extra=not_mine_email)
        if kas:
            groups.append(_group("kasbon_review", "Kasbon menunggu keputusan SDM", "hr-kasbon",
                                 "wallet", kas, exclude, with_keys=with_keys))

    # 2026-11-08: ATAU izin bayar yang sama dengan gerbang pencairan klaim/kasbon (`core.roles.FINANCE_PAY_PERMS`).
    from core.roles import FINANCE_PAY_PERMS
    if role in _FINANCE_ROLES or check_role(user, [], FINANCE_PAY_PERMS):
        # K37 — klaim karyawan yang sudah disetujui menunggu pencairan di Pengeluaran Keuangan.
        exp = await _open_keys(db, "expense_disburse")
        if exp:
            groups.append(_group("expense_disburse", "Klaim karyawan disetujui — menunggu pencairan",
                                 "fin-expenses", "wallet", exp, exclude, tab="settlement", with_keys=with_keys))
        dis = await _open_keys(db, "kasbon_disburse", extra=not_mine_email)
        if dis:
            groups.append(_group("kasbon_disburse", "Kasbon disetujui — menunggu pencairan",
                                 "fin-kasbon", "wallet", dis, exclude, with_keys=with_keys))
        # K34 — pembatalan run gaji FINAL menunggu Keuangan (pengaju tidak boleh menyetujui sendiri).
        pc = await _open_keys(db, "payroll_cancel", extra={"cancel_request.requested_by": {"$ne": uid}})
        if pc:
            groups.append(_group("payroll_cancel", "Pembatalan run gaji menunggu persetujuan",
                                 "hr-payroll-run", "banknote", pc, exclude, with_keys=with_keys))
        # K17 — tagihan CMT bertanda selisih menunggu pemeriksaan Keuangan.
        var = await _open_keys(db, "cmt_variance")
        if var:
            groups.append(_group("cmt_variance", "Tagihan CMT bertanda selisih", "prod-cmt-billing",
                                 "alert-triangle", var, exclude, with_keys=with_keys))

    # K1 — retur menunggu keputusan gudang.
    if role in _warehouse_roles():
        rt = await _open_keys(db, "wh_return")
        if rt:
            groups.append(_group("wh_return", "Retur menunggu keputusan gudang", "wh-returns",
                                 "rotate-ccw", rt, exclude, with_keys=with_keys))
    return groups


@router.get("/badge")
async def get_approval_badge(request: Request):
    """
    Mengembalikan jumlah item yang memerlukan tindakan berdasarkan peran.
    Dulu dipakai ApprovalBadge di TopBar; kini kompatibilitas (lihat docstring modul).
    """
    user = await require_auth(request)
    db = get_db()
    groups = await approval_groups(db, user)
    by_key = {g["key"]: g for g in groups}
    pr_pending = by_key.get("pr", {}).get("count", 0)
    ap_pending = by_key.get("ap", {}).get("count", 0)
    hr_pending = by_key.get("hr", {}).get("count", 0)
    return {
        "total": sum(g["count"] for g in groups),
        "pr_pending": pr_pending,
        "ap_pending": ap_pending,
        "hr_pending": hr_pending,
        "categories": groups,
    }
