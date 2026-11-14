"""
Approval Chain Service — Multi-Level Sequential Approval Engine
CV. Dewi Aditya — Task 2.4

Supports: leave, overtime, salary_adjustment, expense, purchase_order,
          material_request, resignation, asset_purchase

Flow:
  requester submit → Level 1 approver → Level 2 approver → ... → APPROVED/REJECTED

Collections:
  approval_chains         — konfigurasi rantai approval per tipe+threshold
  approval_requests       — instance approval request yang aktif
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from utils.counters import next_counter

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    return str(v)


# ─── Default approval chains ─────────────────────────────────────────────────

DEFAULT_CHAINS: List[Dict] = [
    {
        "type": "leave",
        "name": "Cuti Panjang (≥ 3 hari)",
        "condition": {"days_gte": 3},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer / Supervisor"},
            {"level": 2, "role": "hr",           "label": "HR Department"},
            {"level": 3, "role": "owner",        "label": "Direktur"},
        ],
    },
    {
        "type": "leave",
        "name": "Cuti Pendek (< 3 hari)",
        "condition": {"days_lt": 3},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer / Supervisor"},
        ],
    },
    {
        "type": "overtime",
        "name": "Lembur",
        "condition": {},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer"},
            {"level": 2, "role": "hr",           "label": "HR"},
        ],
    },
    {
        "type": "salary_adjustment",
        "name": "Penyesuaian Gaji",
        "condition": {},
        "levels": [
            {"level": 1, "role": "hr",           "label": "HR Department"},
            {"level": 2, "role": "owner",        "label": "Direktur / Owner"},
        ],
    },
    {
        "type": "expense",
        "name": "Expense Claim ≥ 1jt",
        "condition": {"amount_gte": 1_000_000},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer"},
            {"level": 2, "role": "owner",        "label": "Owner / Direktur"},
        ],
    },
    {
        "type": "expense",
        "name": "Expense Claim < 1jt",
        "condition": {"amount_lt": 1_000_000},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer"},
        ],
    },
    {
        "type": "purchase_order",
        "name": "Purchase Order ≥ 5jt",
        "condition": {"amount_gte": 5_000_000},
        "levels": [
            {"level": 1, "role": "admin",        "label": "Admin Purchasing"},
            {"level": 2, "role": "manager",      "label": "Manajer"},
            {"level": 3, "role": "owner",        "label": "Owner"},
        ],
    },
    {
        "type": "material_return",
        "name": "Return Material Produksi",
        "condition": {},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Supervisor Produksi"},
            {"level": 2, "role": "admin",        "label": "Gudang"},
        ],
    },
    # ── Resignation (Pengunduran Diri) ─────────────────────────────────────────
    {
        "type": "resignation",
        "name": "Pengunduran Diri Karyawan",
        "condition": {},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer / Supervisor Langsung"},
            {"level": 2, "role": "hr",           "label": "HR Department"},
            {"level": 3, "role": "owner",        "label": "Direktur / Owner"},
        ],
    },
    # ── Asset Purchase (Pembelian Aset Baru) ───────────────────────────────────
    {
        "type": "asset_purchase",
        "name": "Pembelian Aset ≥ 10jt",
        "condition": {"amount_gte": 10_000_000},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer Departemen"},
            {"level": 2, "role": "admin",        "label": "Admin Purchasing"},
            {"level": 3, "role": "owner",        "label": "Owner / Direktur"},
        ],
    },
    {
        "type": "asset_purchase",
        "name": "Pembelian Aset < 10jt",
        "condition": {"amount_lt": 10_000_000},
        "levels": [
            {"level": 1, "role": "manager",      "label": "Manajer Departemen"},
            {"level": 2, "role": "admin",        "label": "Admin Purchasing"},
        ],
    },
]


# 2026-11-09 (Q6, keputusan owner): cuti & lembur diputus SATU mesin — `core.leave_engine` (atasan langsung → HR)
# dan `routes.rahaza_overtime` — bukan rantai di sini. Dulu menyetujui cuti di "Persetujuan Bertingkat" tidak
# mengubah status cutinya sama sekali (mesin kedua yang tidak tersambung). Jenis ini disembunyikan dari menu itu,
# tidak di-seed, dan tidak bisa diputus di sini; dokumen lama tetap tersimpan sebagai jejak.
RETIRED_TYPES = ("leave", "overtime")


def active_default_chains() -> List[Dict]:
    return [c for c in DEFAULT_CHAINS if c["type"] not in RETIRED_TYPES]


async def seed_default_chains(db) -> None:
    """Seed default chains jika belum ada (hanya saat collection kosong)."""
    existing = await db.approval_chains.count_documents({})
    if existing > 0:
        return
    for idx, chain in enumerate(active_default_chains()):
        chain_id = await next_counter(db, "approval_chains")
        doc = {
            **chain,
            "id": chain_id,
            "is_active": True,
            "created_at": _now().isoformat(),
            "updated_at": _now().isoformat(),
        }
        await db.approval_chains.insert_one(doc)
    logger.info("Seeded %d default approval chains.", len(active_default_chains()))


async def seed_missing_chains(db) -> dict:
    """Upsert chains yang belum ada by (type, name) — idempotent, aman dijalankan berulang.

    Returns:
        {"added": N, "skipped": M, "types_added": [...]}
    """
    added, skipped = 0, 0
    types_added = []
    for chain in active_default_chains():
        existing = await db.approval_chains.find_one(
            {"type": chain["type"], "name": chain["name"]}
        )
        if existing:
            skipped += 1
            continue
        chain_id = await next_counter(db, "approval_chains")
        doc = {
            **chain,
            "id": chain_id,
            "is_active": True,
            "created_at": _now().isoformat(),
            "updated_at": _now().isoformat(),
        }
        await db.approval_chains.insert_one(doc)
        added += 1
        types_added.append(f"{chain['type']}: {chain['name']}")
        logger.info("Seeded missing chain: type=%s name=%s", chain["type"], chain["name"])
    return {"added": added, "skipped": skipped, "types_added": types_added}


# ─── Chain matching ───────────────────────────────────────────────────────────

def _match_condition(cond: Dict, meta: Dict) -> bool:
    """Check if request metadata matches a chain condition."""
    if not cond:
        return True
    amount = meta.get("amount", 0) or 0
    days   = meta.get("days", 0) or 0
    for key, val in cond.items():
        if key == "amount_gte" and amount < val:
            return False
        if key == "amount_lt" and amount >= val:
            return False
        if key == "days_gte" and days < val:
            return False
        if key == "days_lt" and days >= val:
            return False
    return True


async def find_chain(db, req_type: str, meta: Dict) -> Optional[Dict]:
    """Return the first matching active chain for this type + metadata."""
    chains = await db.approval_chains.find(
        {"type": req_type, "is_active": True}, {"_id": 0}
    ).to_list(length=50)
    for ch in chains:
        if _match_condition(ch.get("condition", {}), meta):
            return ch
    return None


# ─── Create approval request ──────────────────────────────────────────────────

async def create_approval_request(
    db,
    req_type: str,
    ref_id: str,
    ref_code: str,
    requester: Dict,
    meta: Optional[Dict] = None,
    subject: str = "",
) -> Optional[Dict]:
    """Create a multi-level approval request. Returns None if no matching chain."""
    meta = meta or {}
    if req_type in RETIRED_TYPES:
        logger.info("approval_request type=%s tidak dibuat: diputus mesin cuti/lembur (Q6)", req_type)
        return None
    chain = await find_chain(db, req_type, meta)
    if not chain:
        logger.warning("No approval chain found for type=%s meta=%s", req_type, meta)
        return None

    levels_state = [
        {
            "level": lv["level"],
            "role": lv["role"],
            "label": lv["label"],
            "status": "pending" if lv["level"] == 1 else "waiting",
            "approver_id": None,
            "approver_name": None,
            "note": "",
            "actioned_at": None,
        }
        for lv in chain.get("levels", [])
    ]

    request_id = await next_counter(db, "approval_requests")
    now = _now().isoformat()
    doc = {
        "id": request_id,
        "type": req_type,
        "ref_id": ref_id,
        "ref_code": ref_code,
        "subject": subject or f"{req_type} — {ref_code}",
        "chain_id": chain["id"],
        "chain_name": chain["name"],
        "requester_id": requester.get("id") or requester.get("_id") or "",
        "requester_name": requester.get("name") or requester.get("full_name") or requester.get("email") or "",
        "current_level": 1,
        "max_level": len(levels_state),
        "status": "pending",       # pending | approved | rejected | cancelled
        "levels": levels_state,
        "meta": meta,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    await db.approval_requests.insert_one({"_id": request_id, **doc})
    return doc


# ─── Process action ───────────────────────────────────────────────────────────

# RBAC rantai approval (2026-08-07): role tahap ("manager"/"hr"/"owner"/"admin")
# dipetakan ke role nyata di sistem. Admin/owner/superadmin selalu boleh.
LEVEL_ROLE_ALIASES = {
    "manager": {"manager", "manager_produksi", "manager_keuangan", "manager_hr",
                "hr_manager", "manager_marketing", "supervisor", "supervisor_produksi",
                "spv_packing", "spv_cuting", "spv_aksesoris", "director"},
    "hr": {"hr", "hr_manager", "manager_hr", "staff_hr"},
    "owner": {"owner", "director"},
    "admin": {"admin", "admin_produksi", "admin_gudang", "admin_maklon",
              "admin_aksesoris", "admin_marketing"},
    "finance": {"accounting", "staff_keuangan", "manager_keuangan"},
}
LEVEL_SUPER_ROLES = {"superadmin", "admin", "owner"}
# 14 Nov 2026 (owner: centang = penentu): centang yang setara tiap level rantai — peran buatan owner yang dicentang
# boleh memutus level itu walau namanya tidak ada di LEVEL_ROLE_ALIASES. Level "owner" tetap direksi/owner.
LEVEL_PERMS = {
    "manager": ("mod.mgmt_approval.approve",),
    "admin": ("mod.mgmt_approval.approve",),
    "hr": ("hr.approve",),
    "finance": ("finance.approve",),
}


def _may_act_on_level(user: Dict, lv_entry: Dict) -> bool:
    role = (user.get("role") or "").lower()
    if role in LEVEL_SUPER_ROLES:
        return True
    want = str(lv_entry.get("role") or "").lower()
    if not want:
        return True          # rantai tanpa role → jangan blokir alur lama
    if role in LEVEL_ROLE_ALIASES.get(want, {want}):
        return True
    from routes.shared import has_perm
    return bool(LEVEL_PERMS.get(want)) and has_perm(user, *LEVEL_PERMS[want])


async def _is_own_request(db, user: Dict, doc: Dict) -> bool:
    """Pemohon = akun yang mengajukan (`requester_id`) ATAU akun milik karyawan yang diajukan
    (`meta.employee_id`, mis. cuti yang diketik HR atas nama karyawan itu) — tautan dua arah
    `utils.employee_identity.employee_user_ids` + `employee_id` di token."""
    uid = str(user.get("id") or user.get("_id") or "")
    if uid and uid == str(doc.get("requester_id") or ""):
        return True
    emp = str((doc.get("meta") or {}).get("employee_id") or "")
    if not emp or not uid:
        return False
    if emp == str(user.get("employee_id") or ""):
        return True
    try:
        from utils.employee_identity import employee_user_ids
        return uid in [str(x) for x in await employee_user_ids(db, emp)]
    except Exception:  # noqa: BLE001 — tautan karyawan tidak terbaca ⇒ cukup cek requester_id
        logger.warning("[approval] tautan karyawan %s tidak terbaca untuk cek ajuan sendiri", emp)
        return False


async def check_can_act(db, user: Dict, doc: Dict, action: str) -> None:
    """Gerbang aksi approve/reject di LAPISAN AKSI (2026-11-08, Asisten AI Tahap B — celah izin).

    Dulu `_may_act_on_level` tidak pernah dipanggil: siapa pun yang lolos gerbang modul bisa memutus level
    mana pun lewat API, termasuk menyetujui ajuannya sendiri (catatan QA AML-OBSERVASI-2). Sekarang:
      · peran harus cocok dengan peran level aktif (alias `LEVEL_ROLE_ALIASES`; admin/owner/superadmin
        tetap boleh semua level, seperti aturan RBAC rantai 2026-08-07);
      · pemohon TIDAK boleh menyetujui ajuannya sendiri — berlaku untuk semua peran (K25 pemisahan tugas).
        Menolak ajuan sendiri tetap boleh (tidak menguntungkan diri sendiri; menarik = tombol Batalkan).
    Melempar PermissionError (route → 403)."""
    lv_entry = next((lv for lv in doc.get("levels") or [] if lv.get("level") == doc.get("current_level")), None)
    if lv_entry is None:
        raise ValueError("Level entry tidak ditemukan.")
    if not _may_act_on_level(user, lv_entry):
        raise PermissionError(
            f"Level ini menunggu keputusan {lv_entry.get('label') or 'peran lain'}; peran Anda tidak berhak "
            "memutuskan level ini.")
    if action == "approve" and await _is_own_request(db, user, doc):
        raise PermissionError("Pemisahan tugas: Anda tidak boleh menyetujui ajuan Anda sendiri. "
                              "Minta penyetuju lain.")


async def process_action(
    db,
    request_id,      # int atau str — dihandle oleh _coerce
    action: str,       # "approve" | "reject"
    user: Dict,
    note: str = "",
) -> Dict:
    """Process approve/reject at current level. Returns updated request doc.

    2026-11-08: (1) gerbang peran level + larangan menyetujui ajuan sendiri (`check_can_act`);
    (2) badan fungsi dulu tertulis DUA KALI sehingga setiap keputusan menulis dua kali (QA AML-OBSERVASI-1)
    — kini satu kali; (3) tulis bersyarat (status + level yang dibaca) supaya dua klik bersamaan tidak
    memutus level yang sama dua kali (yang kalah → ValueError "baru saja diputuskan")."""
    _id = int(request_id) if str(request_id).isdigit() else request_id
    doc = await db.approval_requests.find_one({"id": _id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Approval request {request_id!r} tidak ditemukan.")
    if doc["status"] not in ("pending",):
        raise ValueError(f"Request sudah {doc['status']}, tidak bisa diubah.")
    if action not in ("approve", "reject"):
        raise ValueError("Aksi tidak dikenal.")
    if doc.get("type") in RETIRED_TYPES:
        raise ValueError("Cuti dan lembur diputus di menu Cuti & Lembur (atasan langsung lalu HR), "
                         "bukan di Persetujuan Bertingkat.")
    await check_can_act(db, user, doc, action)

    current_level = doc["current_level"]
    levels = doc["levels"]
    # Find current level entry
    lv_entry = next((lv for lv in levels if lv["level"] == current_level), None)
    if not lv_entry:
        raise ValueError("Level entry tidak ditemukan.")

    now = _now().isoformat()
    lv_entry["status"] = "approved" if action == "approve" else "rejected"
    lv_entry["approver_id"] = str(user.get("id") or user.get("_id") or "")
    lv_entry["approver_name"] = user.get("full_name") or user.get("name") or user.get("email") or ""
    lv_entry["note"] = note
    lv_entry["actioned_at"] = now

    if action == "reject":
        # Rejection cascades — mark remaining levels as skipped
        for lv in levels:
            if lv["level"] > current_level:
                lv["status"] = "skipped"
        new_status = "rejected"
        completed_at = now
    elif current_level >= doc["max_level"]:
        # Final level approved
        new_status = "approved"
        completed_at = now
    else:
        # Move to next level
        next_level = current_level + 1
        next_lv = next((lv for lv in levels if lv["level"] == next_level), None)
        if next_lv:
            next_lv["status"] = "pending"
        new_status = "pending"
        current_level = next_level
        completed_at = None

    update = {
        "status": new_status,
        "current_level": current_level,
        "levels": levels,
        "updated_at": now,
        "completed_at": completed_at if action == "reject" or new_status == "approved" else doc.get("completed_at"),
    }
    res = await db.approval_requests.update_one(
        {"id": _id, "status": "pending", "current_level": doc["current_level"]}, {"$set": update})
    if not getattr(res, "matched_count", 1):
        raise ValueError("Permintaan ini baru saja diputuskan pengguna lain. Muat ulang daftar.")
    return {**doc, **update}


# ─── Pending for user ─────────────────────────────────────────────────────────

async def get_pending_for_user(
    db,
    user_role: str,
    user_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    """Return pending approval requests that this user (by role) should action."""
    role = (user_role or "").lower()
    # Find all requests that are pending AND current level matches user's role
    all_pending = await db.approval_requests.find(
        {"status": "pending", "type": {"$nin": list(RETIRED_TYPES)}}, {"_id": 0}
    ).sort("created_at", -1).limit(200).to_list(200)

    result = []
    for req in all_pending:
        current_level = req.get("current_level", 1)
        levels = req.get("levels", [])
        lv = next((lv for lv in levels if lv["level"] == current_level), None)
        if not lv:
            continue
        required_role = (lv.get("role") or "").lower()
        # superadmin/owner can see everything
        if role in ("superadmin", "owner") or role == required_role:
            result.append(req)
        if len(result) >= limit:
            break
    return result
