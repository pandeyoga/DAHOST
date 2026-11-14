"""
Universal Export / Import — generic, registry-driven data transfer.

- Export any whitelisted collection to CSV / XLSX.
- Download a blank import TEMPLATE (headers only).
- Import (upsert-by-key) with a DRY-RUN preview step (valid/invalid rows + errors)
  then a COMMIT step.

Design:
- REGISTRY is the single source of truth for what is exportable/importable, the
  column schema (for validation/coercion), the natural key (for upsert), and RBAC.
- Master tables => import + export.  Transaction tables => export only.
- Nested/complex columns are carried as JSON strings in a single cell.

Endpoints (prefix /api/data-transfer):
  GET  /registry                      -> tables the current user may use
  GET  /export/{key}?format=csv|xlsx  -> file download
  GET  /template/{key}?format=csv|xlsx-> blank template (headers [+ 1 example])
  POST /import/{key}?mode=dry_run|commit (multipart file) -> preview / apply
"""
# ruff: noqa: E402
import io
import logging
import csv
import importlib
import json
import uuid
from datetime import datetime, timezone, date

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse

from database import get_db
from auth import require_auth, log_activity, hash_password
from core.roles import HR_ROLES, PRODUCTION_ROLES, WAREHOUSE_ROLES
from routes import data_transfer_masters as dtm

import openpyxl
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from utils.waktu import now_wib
from core import po_berjalan_import as po_berjalan

router = APIRouter(prefix="/api/data-transfer", tags=["data-transfer"])

ADMIN_ROLES = {"superadmin", "admin", "owner"}
# 2026-11-06 (T4): peran impor master baru = peran master itu sendiri (+ admin/owner).
_CALENDAR_ROLES = sorted(ADMIN_ROLES | set(PRODUCTION_ROLES) | set(HR_ROLES))
_WAREHOUSE_ROLES = sorted(ADMIN_ROLES | set(WAREHOUSE_ROLES))


def _uid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


# ── column helper ────────────────────────────────────────────────────────────
def col(name, type="str", required=False, label=None, example=""):
    return {"name": name, "type": type, "required": required, "label": label or name, "example": example}


# ── REGISTRY ─────────────────────────────────────────────────────────────────
# type: str | num | bool | date | json
REGISTRY = {
    # ===== GROUP A — MASTER (export + import) =====
    "materials": {
        "collection": "rahaza_materials", "label": "Bahan / Material", "group": "Master Produksi",
        "key": ["code"], "importable": True, "export_roles": ["spv", "gudang", "manager", "produksi"],
        "columns": [
            col("code", "str", True, example="MAT-001"), col("name", "str", True, example="Kain Katun"),
            col("type", "str", example="yarn"), col("unit", "str", example="kg"),
            col("composition", "str"), col("color", "str"), col("min_stock", "num", example="0"),
            col("unit_cost", "num", example="0"), col("active", "bool", example="true"),
            # ── Kemasan / multi-satuan (INV-UOM-4) ──
            col("base_uom", "str", label="satuan dasar", example="pcs"),
            col("pack_unit", "str", label="satuan kemasan", example="pack"),
            col("pack_size", "num", label="isi per kemasan", example="12"),
            col("display_in_packs", "bool", label="tampilkan per kemasan", example="true"),
        ],
    },
    "models": {
        "collection": "rahaza_models", "label": "Model / Artikel", "group": "Master Produksi",
        "key": ["code"], "importable": True, "export_roles": ["spv", "produksi", "manager"],
        "columns": [col("code", "str", True, example="MDL-001"), col("name", "str", True), col("description", "str"), col("active", "bool", example="true")],
    },
    "sizes": {
        "collection": "rahaza_sizes", "label": "Ukuran", "group": "Master Produksi",
        "key": ["code"], "importable": True, "export_roles": ["spv", "produksi"],
        "columns": [col("code", "str", True, example="S"), col("name", "str", True), col("order_seq", "num", example="1"), col("active", "bool", example="true")],
    },
    "processes": {
        "collection": "rahaza_processes", "label": "Proses Produksi", "group": "Master Produksi",
        "key": ["code"], "importable": True, "export_roles": ["spv", "produksi"],
        "columns": [col("code", "str", True), col("name", "str", True), col("order_seq", "num", example="1"), col("is_rework", "bool", example="false"), col("description", "str"), col("active", "bool", example="true")],
    },
    "lines": {
        "collection": "rahaza_lines", "label": "Lini Produksi", "group": "Master Produksi",
        "key": ["code"], "importable": True, "export_roles": ["spv", "produksi"],
        "columns": [col("code", "str", True), col("name", "str", True), col("location_id", "str"), col("process_id", "str"), col("capacity_per_hour", "num", example="0"), col("active", "bool", example="true")],
    },
    "locations": {
        "collection": "rahaza_locations", "label": "Lokasi / Gudang", "group": "Master Gudang",
        "key": ["code"], "importable": True, "export_roles": ["gudang", "spv"],
        "columns": [col("code", "str", True, example="GDG-A1"), col("name", "str", True), col("type", "str", example="rack"), col("parent_id", "str"), col("active", "bool", example="true")],
    },
    "shifts": {
        "collection": "rahaza_shifts", "label": "Shift", "group": "Master Produksi",
        "key": ["code"], "importable": True, "export_roles": ["spv", "hr"],
        "columns": [col("code", "str", True), col("name", "str", True), col("start_time", "str", example="08:00"), col("end_time", "str", example="16:00"), col("active", "bool", example="true")],
    },
    "coa_accounts": {
        "collection": "rahaza_coa_accounts", "label": "Chart of Accounts (COA)", "group": "Finance",
        "key": ["code"], "importable": True, "export_roles": ["finance"],
        "columns": [
            col("code", "str", True, example="1-1101"), col("name", "str", True, example="Kas"),
            col("type", "str", True, example="ASSET"), col("parent_code", "str", example="1-1100"),
            col("is_group", "bool", example="false"), col("normal_balance", "str", example="DEBIT"),
            col("active", "bool", example="true"), col("flags", "json", example="{}"),
        ],
    },
    "employees": {
        "collection": "rahaza_employees", "label": "Karyawan", "group": "HR / SDM",
        "key": ["employee_code"], "importable": True, "export_roles": ["hr", "spv"],
        "columns": [col("employee_code", "str", True, example="DA-001"), col("name", "str", True), col("role_hint", "str"), col("phone", "str"), col("join_date", "date", example="2025-01-01"), col("active", "bool", example="true")],
    },
    "salary_grades": {
        "collection": "rahaza_salary_grades", "label": "Grade Gaji", "group": "HR / SDM",
        "key": ["grade_code"], "importable": True, "export_roles": ["hr"],
        "columns": [col("grade_code", "str", True), col("grade_name", "str", True), col("level", "num", example="1"), col("min_salary", "num"), col("mid_salary", "num"), col("max_salary", "num"), col("currency", "str", example="IDR"), col("is_active", "bool", example="true")],
    },
    "leave_types": {
        "collection": "rahaza_leave_types", "label": "Jenis Cuti", "group": "HR / SDM",
        "key": ["code"], "importable": True, "export_roles": ["hr"],
        "columns": [col("code", "str", True), col("name", "str", True), col("quota_default", "num", example="12"), col("unpaid", "bool", example="false"), col("request_type", "str", example="leave"), col("requires_document", "bool", example="false"), col("active", "bool", example="true")],
    },
    "cmt_partners": {
        "collection": "dewi_cmt_partners", "label": "Vendor CMT", "group": "Partner",
        "key": ["code"], "importable": True, "export_roles": ["maklon", "spv", "finance"],
        "columns": [
            col("code", "str", True, example="CMT-001"), col("name", "str", True), col("owner_name", "str"),
            col("phone", "str"), col("address", "str"), col("city", "str"), col("specialization", "str"),
            col("rate_per_pcs", "num"), col("capacity_per_week", "num"), col("bank_name", "str"),
            col("bank_account", "str"), col("bank_holder", "str"), col("rating", "num"),
            col("status", "str", example="active"), col("penalty_per_day", "num"), col("notes", "str"),
        ],
    },
    "vendor_partners": {
        "collection": "vendor_partners", "label": "Vendor CMT (Partner)", "group": "Partner",
        "key": ["code"], "importable": True, "export_roles": ["maklon", "spv", "produksi", "manager", "finance"],
        "columns": [
            col("code", "str", True, example="CMT-001"), col("name", "str", True, example="CMT Berkah Jaya"),
            col("contact_name", "str"), col("contact_phone", "str"), col("address", "str"),
            col("notes", "str"), col("is_active", "bool", example="true"),
        ],
    },
    "maklon_clients": {
        "collection": "dewi_maklon_clients", "label": "Klien Maklon", "group": "Partner",
        "key": ["code"], "importable": True, "export_roles": ["maklon", "marketing"],
        "columns": [col("code", "str", True, example="CL-001"), col("name", "str", True), col("contact_name", "str"), col("contact_phone", "str"), col("address", "str"), col("notes", "str"), col("active", "bool", example="true")],
    },
    "platform_accounts": {
        "collection": "marketing_platform_accounts", "label": "Akun Toko / Channel", "group": "Partner",
        "key": ["account_code"], "importable": True, "export_roles": ["marketing"],
        "columns": [col("account_code", "str", True, example="SHP-01"), col("account_name", "str", True), col("platform", "str", example="shopee"), col("username", "str"), col("status", "str", example="active"), col("group", "str")],
    },
    "users": {
        "collection": "users", "label": "Pengguna Sistem", "group": "Admin",
        "key": ["email"], "importable": True, "export_roles": [],  # admin only
        "import_roles": list(ADMIN_ROLES),
        "exclude_export": ["password"],
        "import_defaults": {"password": "Dewi@123", "status": "active"},
        "columns": [col("name", "str", True), col("email", "str", True, example="user@dewiaditya.id"), col("role", "str", example="staff"), col("status", "str", example="active")],
    },

    # ===== GROUP B — MASTER advanced (nested → JSON) =====
    "posting_profiles": {
        "collection": "rahaza_posting_profiles", "label": "Profil Posting GL", "group": "Finance",
        "key": ["event_type"], "importable": True, "export_roles": ["finance"],
        "columns": [col("event_type", "str", True, example="cmt_ap_invoice"), col("description", "str"), col("mapping", "json", True, example='{"debit":"...","credit":"..."}'), col("active", "bool", example="true")],
    },

    # ===== GROUP A2 — MASTER dengan penangan khusus (2026-11-06, T4; routes/data_transfer_masters.py) =====
    # Judul kolom = template owner. Hak akses = penjaga/peran master itu sendiri.
    "suppliers": {
        "collection": "rahaza_suppliers", "label": "Master Supplier", "group": "Pengadaan",
        "key": ["kode atau nama"], "importable": True, "handler": "suppliers",
        "import_guard": "routes.procurement_suppliers:_require_procurement",
        "export_guard": "routes.procurement_suppliers:_require_procurement_read",
        "columns": dtm.SUPPLIER_COLUMNS,
    },
    "supplier_prices": {
        "collection": "rahaza_supplier_price_lists", "label": "Daftar Harga Supplier", "group": "Pengadaan",
        "key": ["supplier + kode material + satuan beli + berlaku mulai"], "importable": True,
        "handler": "supplier_prices",
        "import_guard": "routes.procurement_suppliers:_require_procurement",
        "export_guard": "routes.procurement_suppliers:_require_procurement_read",
        "columns": dtm.PRICE_COLUMNS,
    },
    "customers": {
        "collection": "rahaza_customers", "label": "Master Pelanggan", "group": "Penjualan",
        "key": ["kode atau nama"], "importable": True, "handler": "customers",
        "import_guard": "routes.sales_direct:_require_write",
        "export_guard": "routes.sales_direct:_require_write",
        "columns": dtm.CUSTOMER_COLUMNS,
    },
    "holidays": {
        "collection": "rahaza_production_calendar", "label": "Kalender Libur", "group": "HR / SDM",  # Tahap 9: pindah ke SDM
        "key": ["tanggal"], "importable": True, "handler": "holidays",
        "import_roles": _CALENDAR_ROLES, "export_roles": _CALENDAR_ROLES,
        "columns": dtm.HOLIDAY_COLUMNS,
    },
    "wh_bins": {
        "collection": "wh_racks", "label": "Rak & Bin Gudang", "group": "Master Gudang",
        "key": ["kode gedung + kode zona + kode rak"], "importable": True, "handler": "wh_bins",
        "import_roles": _WAREHOUSE_ROLES, "export_roles": _WAREHOUSE_ROLES,
        "columns": dtm.BIN_COLUMNS,
    },
    "payroll_profiles": {
        "collection": "rahaza_payroll_profiles", "label": "Profil Payroll", "group": "HR / SDM",
        "key": ["employee_id"], "importable": True, "export_roles": ["hr"],
        "columns": [col("employee_id", "str", True), col("pay_scheme", "str", example="monthly"), col("period_type", "str"), col("base_rate", "num"), col("overtime_rate", "num"), col("pcs_process_rates", "json", example="{}"), col("notes", "str"), col("active", "bool", example="true")],
    },
    "boms": {
        "collection": "rahaza_boms", "label": "BOM (Bill of Materials)", "group": "Master Produksi",
        "key": ["model_id", "size_id", "color"], "importable": True, "export_roles": ["spv", "produksi"],
        "columns": [col("model_id", "str", True), col("size_id", "str", True), col("color", "str"), col("materials", "json", example="[]"), col("notes", "str"), col("active", "bool", example="true")],
    },

    # ===== GROUP C — TRANSACTIONS (export only; columns=None => all fields) =====
    "maklon_pos": {"collection": "dewi_maklon_pos", "label": "PO Maklon", "group": "Transaksi", "importable": False, "export_roles": ["maklon", "spv"], "columns": None},
    "production_pos": {"collection": "production_pos", "label": "PO Produksi", "group": "Transaksi", "importable": False, "export_roles": ["spv", "produksi"], "columns": None},
    "cutting_requests": {"collection": "dewi_cutting_requests", "label": "Permintaan Cutting", "group": "Transaksi", "importable": False, "export_roles": ["spv", "produksi"], "columns": None},
    "cmt_jobs": {"collection": "dewi_cmt_jobs", "label": "Job CMT", "group": "Transaksi", "importable": False, "export_roles": ["maklon", "spv"], "columns": None},
    "ar_invoices": {"collection": "rahaza_ar_invoices", "label": "Invoice AR", "group": "Transaksi", "importable": False, "export_roles": ["finance"], "columns": None},
    "maklon_invoices": {"collection": "dewi_maklon_invoices", "label": "Invoice Maklon", "group": "Transaksi", "importable": False, "export_roles": ["finance", "maklon"], "columns": None},
    "material_issues": {"collection": "rahaza_material_issues", "label": "Pengeluaran Material", "group": "Transaksi", "importable": False, "export_roles": ["gudang", "spv"], "columns": None},
    "material_stock": {"collection": "rahaza_material_stock", "label": "Stok Material", "group": "Transaksi", "importable": False, "export_roles": ["gudang", "spv"], "columns": None},
    "attendance_events": {"collection": "rahaza_attendance_events", "label": "Absensi", "group": "Transaksi", "importable": False, "export_roles": ["hr", "spv"], "columns": None},
    "activity_logs": {"collection": "activity_logs", "label": "Log Aktivitas", "group": "Transaksi", "importable": False, "export_roles": [], "columns": None},
    "buyer_shipments": {"collection": "buyer_shipments", "label": "Pengiriman Buyer", "group": "Transaksi", "importable": False, "export_roles": ["spv", "produksi"], "columns": None},

    # ===== GROUP D — IMPOR SALDO AWAL CUTOFF (impor saja, mesin khusus) =====
    # 2026-11-06 (T6): PO produksi/maklon yang masih berjalan saat cutoff → PO Dikonfirmasi + surat
    # jalan saldo awal lewat jalur PO & kirim CMT resmi (core.po_berjalan_import). Bukan upsert generik.
    "po_berjalan": {"collection": "production_pos", "label": "PO berjalan saat cutoff", "group": "Saldo Awal",
                    "importable": True, "exportable": False, "import_roles": sorted(ADMIN_ROLES),
                    "handler": "po_berjalan", "accepts_alias": True, "existing_rows": "skip",
                    "key": ["Kode potongan / No PO", "CMT"], "columns": po_berjalan.template_columns()},
}

# 14 Nov 2026 (owner: centang = penentu): hak Unduh/Impor per tabel = centang modul pemilik datanya (Unduh = aksi
# "Unduh", impor = aksi "Tambah"). `export_roles`/`import_roles` di atas hanya berlaku selama owner belum mengatur
# centang peran itu. Tabel tanpa pasangan centang (pengguna, log aktivitas, impor saldo awal, impor master generik
# yang dulu khusus admin) tetap khusus owner/admin — Administrasi Sistem.
_CENTANG_TABEL = {
    "maklon_clients": (None, "mod.mak_clients.export"),
    "platform_accounts": (None, "mod.mkt_accounts.export"),
    "posting_profiles": (None, "mod.fin_master.export"),
    "holidays": ("mod.hr_holiday_calendar.create", "mod.hr_holiday_calendar.export"),
    "wh_bins": ("mod.wh_tools.create", "mod.wh_tools.export"),
    "payroll_profiles": (None, "mod.hr_payroll.export"),
    "boms": (None, "mod.rnd_master_product.export"),
    "maklon_pos": (None, "mod.mak_po.export"),
    "production_pos": (None, "mod.prod_po.export"),
    "cutting_requests": (None, "mod.cut_orders.export"),
    "cmt_jobs": (None, "mod.prod_jobs.export"),
    "ar_invoices": (None, "mod.fin_ar.export"),
    "maklon_invoices": (None, "mod.mak_billing.export"),
    "material_issues": (None, "mod.wh_material_issue.export"),
    "material_stock": (None, "mod.wh_stock.export"),
    "attendance_events": (None, "mod.hr_attendance.export"),
    "buyer_shipments": (None, "mod.prod_buyer_shipment.export"),
}
for _k, (_imp, _exp) in _CENTANG_TABEL.items():
    if _k in REGISTRY:
        REGISTRY[_k]["import_perm"], REGISTRY[_k]["export_perm"] = _imp, _exp


# ── RBAC helpers ─────────────────────────────────────────────────────────────
def _role(user):
    return (user.get("role") or "").lower()


def _can_export(user, entry):
    from core.authz import izin_atau_peran_lama
    if entry.get("exportable") is False:
        return False
    if _role(user) in ADMIN_ROLES:
        return True
    roles = entry.get("export_roles") or []
    if "*" in roles:
        return True
    return izin_atau_peran_lama(user, roles, tuple(k for k in (entry.get("export_perm"),) if k))


def _can_import(user, entry):
    from core.authz import izin_atau_peran_lama
    if not entry.get("importable"):
        return False
    if _role(user) in ADMIN_ROLES:
        return True
    roles = entry.get("import_roles") or sorted(ADMIN_ROLES)
    return izin_atau_peran_lama(user, roles, tuple(k for k in (entry.get("import_perm"),) if k))


async def _may(request, user, entry, kind: str) -> bool:
    """Boleh `kind` ('import'|'export')? 2026-11-06 (T4): master yang punya penjaga sendiri
    (Supplier: pengadaan; Pelanggan: penjualan) memakai PENJAGA ITU (peran + izin), bukan daftar kedua."""
    if kind == "import" and not entry.get("importable"):
        return False
    guard = entry.get(f"{kind}_guard")
    if not guard:
        return _can_import(user, entry) if kind == "import" else _can_export(user, entry)
    mod, fn = guard.split(":")
    try:
        await getattr(importlib.import_module(mod), fn)(request)
        return True
    except HTTPException:
        return False
    except Exception:  # noqa: BLE001 — penjaga galat = TIDAK boleh (gagal tertutup), dicatat
        logging.getLogger(__name__).exception("penjaga akses %s gagal dijalankan", guard)
        return False


def _get_entry(key):
    entry = REGISTRY.get(key)
    if not entry:
        raise HTTPException(404, f"Tabel '{key}' tidak terdaftar untuk export/import")
    return entry


# ── value (de)serialization ──────────────────────────────────────────────────
def _to_cell(value, ctype=None):
    """Convert a stored value into a flat cell string for export."""
    if value is None:
        return ""
    if ctype == "json" or isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


TRUE_SET = {"true", "1", "yes", "ya", "y", "t", "aktif", "active"}
FALSE_SET = {"false", "0", "no", "tidak", "n", "f", "nonaktif", "inactive", ""}


def _coerce(raw, ctype, colname):
    """Coerce a raw cell (string) into the target type. Returns (value, error)."""
    if raw is None:
        return None, None
    s = str(raw).strip()
    if s == "":
        return None, None
    try:
        if ctype == "num":
            s2 = s.replace(",", "") if s.count(",") and "." in s else s.replace(",", ".")
            f = float(s2)
            return (int(f) if f.is_integer() else f), None
        if ctype == "bool":
            low = s.lower()
            if low in TRUE_SET:
                return True, None
            if low in FALSE_SET:
                return False, None
            return None, f"'{colname}': nilai boolean tidak valid ('{s}')"
        if ctype == "json":
            return json.loads(s), None
        if ctype == "date":
            # keep as ISO string; validate it parses
            datetime.fromisoformat(s.replace("Z", "+00:00"))
            return s, None
        return s, None  # str
    except Exception as e:
        return None, f"'{colname}': gagal parse ({ctype}) — {e}"


# ── column resolution (dynamic for columns=None) ─────────────────────────────
async def _resolve_columns(db, entry):
    if entry["columns"]:
        return entry["columns"], [c["name"] for c in entry["columns"]]
    # dynamic: union of keys from a sample of documents
    cursor = db[entry["collection"]].find({}, limit=200)
    keys = []
    seen = set()
    async for d in cursor:
        for k in d.keys():
            if k in ("_id",) or k in seen:
                continue
            seen.add(k)
            keys.append(k)
    # stable, friendly ordering
    priority = ["id", "code", "po_number", "invoice_number", "job_code", "request_code", "name"]
    keys.sort(key=lambda k: (priority.index(k) if k in priority else 999, k))
    cols = [{"name": k, "type": "auto", "required": False, "label": k, "example": ""} for k in keys]
    return cols, keys


# ── ENDPOINTS ────────────────────────────────────────────────────────────────
@router.get("/registry")
async def get_registry(request: Request):
    user = await require_auth(request)
    out = []
    for key, entry in REGISTRY.items():
        exportable = await _may(request, user, entry, "export")
        importable = await _may(request, user, entry, "import")
        # 2026-11-06 (T6): entri impor-saja (exportable=False) tampil bagi yang boleh mengimpor
        if not exportable and not (entry.get("exportable") is False and importable):
            continue
        out.append({
            "key": key,
            "label": entry["label"],
            "group": entry["group"],
            "importable": importable,
            "exportable": exportable,
            "accepts_alias": bool(entry.get("accepts_alias")),
            "existing_rows": entry.get("existing_rows", "update"),
            "key_fields": entry.get("key", []),
        })
    out.sort(key=lambda x: (x["group"], x["label"]))
    return {"tables": out, "count": len(out)}


@router.get("/export/{key}")
async def export_table(key: str, request: Request, format: str = Query("xlsx")):
    user = await require_auth(request)
    entry = _get_entry(key)
    if not await _may(request, user, entry, "export"):
        raise HTTPException(403, "Anda tidak punya akses export tabel ini")
    db = get_db()
    if entry.get("handler"):
        # 2026-11-06 (T4): isi sekarang dalam format template impor (judul kolom owner) → bisa diunggah lagi
        cols = entry["columns"]
        colnames = [c["name"] for c in cols]
        headers = [c["header"] for c in cols]
        rows = await dtm.HANDLERS[entry["handler"]]["export"](db)
    else:
        cols, colnames = await _resolve_columns(db, entry)
        exclude = set(entry.get("exclude_export") or [])
        colnames = [c for c in colnames if c not in exclude]
        cols = [c for c in cols if c["name"] not in exclude]
        headers = colnames

        rows = []
        async for doc in db[entry["collection"]].find({}):
            rows.append(doc)

    ctype_map = {c["name"]: c["type"] for c in cols}
    fname_base = f"{key}_{now_wib().strftime('%Y%m%d_%H%M')}"

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(headers)
        for doc in rows:
            w.writerow([_to_cell(doc.get(cn), ctype_map.get(cn)) for cn in colnames])
        data = buf.getvalue().encode("utf-8-sig")
        return StreamingResponse(io.BytesIO(data), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{fname_base}.csv"'})
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = key[:31]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = openpyxl.styles.Font(bold=True)
        for doc in rows:
            ws.append([_to_cell(doc.get(cn), ctype_map.get(cn)) for cn in colnames])
        for i, cn in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(max(len(cn) + 2, 12), 40)
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{fname_base}.xlsx"'})


@router.get("/template/{key}")
async def template_table(key: str, request: Request, format: str = Query("xlsx")):
    user = await require_auth(request)
    entry = _get_entry(key)
    if not entry.get("importable"):
        raise HTTPException(400, "Tabel ini tidak mendukung import (export-only)")
    if not await _may(request, user, entry, "import"):
        raise HTTPException(403, "Anda tidak punya akses import tabel ini")
    cols = entry["columns"]
    headers = [c.get("header") or c["name"] for c in cols]
    examples = [c.get("example", "") for c in cols]

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(headers)
        w.writerow(examples)
        data = buf.getvalue().encode("utf-8-sig")
        return StreamingResponse(io.BytesIO(data), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="template_{key}.csv"'})
    wb = openpyxl.Workbook()
    ws = wb.active
    # 2026-11-06 (T4): nama sheet = nama sheet template owner (mis. SUPPLIER) supaya sama dengan berkasnya
    ws.title = (dtm.HANDLERS[entry["handler"]]["sheet_names"][0] if entry.get("handler") else key)[:31]
    ws.append(headers)
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=1, column=j)
        cell.font = openpyxl.styles.Font(bold=True)
        req = " *" if c.get("required") else ""
        ws.column_dimensions[get_column_letter(j)].width = min(max(len(headers[j - 1]) + len(req) + 2, 12), 40)
        # 2026-11-06 (T4): petunjuk & daftar pilihan di template (seperti template owner)
        tips = [c["help"]] if c.get("help") else []
        if c.get("choices"):
            tips.append("Pilihan: " + ", ".join(c["choices"]))
            dv = DataValidation(type="list", formula1='"' + ",".join(c["choices"]) + '"', allow_blank=True,
                                showErrorMessage=False)
            dv.add(f"{get_column_letter(j)}2:{get_column_letter(j)}1000")
            ws.add_data_validation(dv)
        if j == 1 and entry.get("handler"):
            tips.append("Baris yang kolom pertamanya diawali # (seperti baris contoh) dilewati.")
        if tips:
            cell.comment = Comment("\n".join(tips), "DAHOST")
    ws.append(examples)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="template_{key}.xlsx"'})


async def _material_uom_fields(db, doc: dict, existing: dict | None):
    """Susun field UOM (`uoms` + cermin lama) untuk satu baris impor material.

    Kembalian: (fields_to_set, errors). Kolom kemasan yang KOSONG = tidak
    menyentuh konfigurasi satuan yang sudah ada (perilaku impor lama).
    Mengganti SATUAN DASAR item yang masih berstok DITOLAK — harus lewat
    endpoint rebase resmi supaya angka stok ikut dikonversi (INV-UOM-3).
    """
    from core import uom as _uom
    from core import stock_service

    given = {k: doc[k] for k in ("unit", "base_uom", "pack_unit", "pack_size", "display_in_packs")
             if k in doc and doc[k] not in (None, "")}
    if not given:
        return {}, []

    cur = existing or {}
    cur_base = _uom.base_uom_of(cur) if existing else ""
    # 2026-11-06 (pola P8): ejaan resmi (rol/gulung → roll, pak → pack) supaya impor tidak melahirkan
    # satuan kembar di samping data yang sudah ada
    base = _uom.canonical_unit(given.get("base_uom") or given.get("unit") or cur_base or _uom.DEFAULT_BASE)

    if existing and cur_base and base != cur_base:
        onhand = await stock_service.get_onhand(existing.get("id"), db=db)
        if abs(float(onhand or 0)) > 1e-9:
            return {}, [f"satuan dasar '{cur_base}' → '{base}' ditolak: stok masih {onhand:g} {cur_base}. "
                        f"Pakai tombol 'Ubah Satuan Dasar' di form material (rebase)."]
        # 2026-11-06 (Tahap 2): PO/GR/daftar harga/karantina yang masih terbuka memakai satuan lama
        from core import procurement_guards
        docs = await procurement_guards.check_base_unit_change(db, existing, base)
        if docs:
            return {}, [procurement_guards.open_documents_message(existing, base, docs)]

    pack_unit = _uom.canonical_unit(given.get("pack_unit"))
    pack_size = float(given.get("pack_size") or 0)
    if pack_unit == base:
        pack_unit, pack_size = "", 0.0
    if pack_unit and pack_size <= 1:
        return {}, [f"'pack_size' harus lebih besar dari 1 bila 'pack_unit' diisi ('{pack_unit}')"]
    if pack_size > 1 and not pack_unit:
        return {}, ["'pack_unit' wajib diisi bila 'pack_size' diisi"]

    rows = [{"code": base, "factor": 1, "is_base": True}]
    if existing and base == cur_base:
        # pertahankan tingkat kemasan lain (mis. karton) yang tidak disebut di file
        for r in _uom.resolve_uoms(cur):
            code = _uom.normalize_code(r.get("code"))
            if code in (base, pack_unit) or float(r.get("factor") or 0) <= 1:
                continue
            rows.append(dict(r))
    if pack_unit:
        rows.append({"code": pack_unit, "factor": pack_size, "parent": base,
                     "is_purchase_default": True,
                     "is_display_default": bool(given.get("display_in_packs"))})

    body = {"base_uom": base, "uoms": rows}
    if pack_unit:
        # dibeli per kemasan, dipakai per satuan dasar — inti kasus owner
        body["purchase_uom"] = pack_unit
        body["issue_uom"] = base
        body["display_uom"] = pack_unit if given.get("display_in_packs") else base
    if "display_in_packs" in given:
        body["display_in_packs"] = bool(given["display_in_packs"])
    try:
        return _uom.apply_payload(body, cur), []
    except _uom.UomError as e:
        return {}, [str(e)]


async def _material_cost_guard(db, doc: dict, existing: dict | None) -> str | None:
    """2026-11-06 (Tahap 2): impor TIDAK boleh menimpa harga (HPP) barang yang masih berstok.

    Dulu kolom `unit_cost` menimpa master langsung — tanpa jurnal — sehingga nilai stok ≠ buku besar.
    Harga lewat impor hanya untuk barang baru / barang tanpa stok (harga awal). Koreksi harga barang
    berstok = Set HPP (revaluasi berjurnal dengan alasan). Return pesan galat atau None."""
    if not existing or doc.get("unit_cost") in (None, ""):
        return None
    from core.accessory_valuation import resolve_unit_cost
    from core import stock_service
    new_cost = float(doc.get("unit_cost") or 0)
    if abs(new_cost - resolve_unit_cost(existing)) <= 1e-6:
        return None
    onhand = float(await stock_service.get_onhand(existing.get("id"), db=db) or 0)
    if abs(onhand) <= 1e-9:
        return None
    return (f"harga {existing.get('code') or ''} tidak bisa diubah lewat impor: barang masih berstok {onhand:g}. "
            "Kosongkan kolom unit_cost untuk baris ini; koreksi harga barang berstok lewat Set HPP "
            "(revaluasi berjurnal dengan alasan).")


async def _record_material_cost(db, doc: dict, existing: dict | None, user: dict) -> None:
    """Riwayat harga (ber-`material_id`) untuk harga awal yang masuk lewat impor."""
    if doc.get("unit_cost") in (None, ""):
        return
    from core.accessory_valuation import _record_history, resolve_unit_cost
    old = resolve_unit_cost(existing) if existing else 0.0
    new = float(doc.get("unit_cost") or 0)
    mid = (existing or {}).get("id") or doc.get("id")
    if not mid or abs(new - old) <= 1e-6:
        return
    await _record_history(db, material_id=mid, old_cost=old, new_cost=new, qty_before=0, qty_in=0, cost_in=new,
                          source="opening", actor={"id": user.get("id"), "name": user.get("name", "")},
                          notes="Harga awal dari impor data (stok masih kosong)")


# 2026-11-06 (pola P8): master referensi yang diimpor → field nama + lingkup banding (aturan `core.reference_dedup`)
_REF_NAME_FIELDS = {
    "rahaza_sizes": ("name", None), "rahaza_processes": ("name", None), "rahaza_lines": ("name", None),
    "rahaza_locations": ("name", "parent_id"), "rahaza_shifts": ("name", None),
    "rahaza_salary_grades": ("grade_name", None), "rahaza_leave_types": ("name", None),
}


async def _ref_name_clash(db, coll: str, doc: dict, seen: dict) -> str | None:
    """Pesan galat bila baris baru menggandakan master aktif (atau baris lain di berkas yang sama)."""
    spec = _REF_NAME_FIELDS.get(coll)
    if not spec or not doc.get(spec[0]):
        return None
    from core.reference_dedup import find_duplicate_ref, process_class, ref_key
    field, scope_f = spec
    scope = {scope_f: doc.get(scope_f)} if scope_f else None
    pcode = doc.get("code") if coll == "rahaza_processes" else None
    dup = await find_duplicate_ref(db, coll, name=doc[field], name_field=field, scope=scope, process_code=pcode)
    if dup:
        return (f"'{doc[field]}' setara dengan master yang sudah ada '{dup.get(field)}'"
                + (f" (kode {dup.get('code')})" if dup.get("code") else "")
                + " — pakai kode yang sudah ada supaya tidak tercatat dua kali")
    k = (coll, ref_key(doc[field]), process_class(pcode) if pcode else "", str(scope or ""))
    if k in seen:
        return f"'{doc[field]}' setara dengan baris lain di berkas ini ('{seen[k]}')"
    seen[k] = doc[field]
    return None


def _merged_row_note(coll: str, existing: dict) -> str | None:
    if coll in _REF_NAME_FIELDS and existing.get("duplicate_of"):
        return (f"kode '{existing.get('code')}' sudah digabung ke kode '{existing.get('duplicate_of_code')}'"
                " (data tercatat dua kali) — pakai kode itu")
    return None


def _parse_upload(filename, content, sheet_names=()):
    """Return list[dict] rows from CSV or XLSX bytes.

    2026-11-06 (T4): `__row__` = nomor baris ASLI di berkas (baris kosong di tengah tidak menggeser
    nomor di pesan galat). `sheet_names`: bila workbook punya sheet bernama itu (mis. SUPPLIER di
    template kelengkapan master owner), sheet itulah yang dibaca — bukan sheet yang kebetulan aktif.
    """
    name = (filename or "").lower()
    if name.endswith(".csv") or (b"," in content[:200] and not content[:4] == b"PK\x03\x04"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        out = []
        for r in reader:
            if all(v is None or str(v).strip() == "" for v in r.values()):
                continue
            out.append({**dict(r), "__row__": reader.line_num})
        return out
    # xlsx
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    wanted = {s.upper() for s in sheet_names or ()}
    for sn in wb.sheetnames:
        if sn.strip().upper() in wanted:
            ws = wb[sn]
            break
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for n, r in enumerate(rows[1:], start=2):
        if all(c is None or str(c).strip() == "" for c in r):
            continue
        out.append({**{headers[i]: r[i] for i in range(min(len(headers), len(r)))}, "__row__": n})
    return out


async def _import_po_berjalan(db, user, entry, raw_rows, alias_file, mode):
    """2026-11-06 (T6): pratinjau / eksekusi impor PO berjalan saat cutoff (core.po_berjalan_import)."""
    alias_rows = []
    if alias_file is not None:
        try:
            alias_rows = _parse_upload(alias_file.filename, await alias_file.read())
        except Exception as e:
            raise HTTPException(400, f"Gagal membaca tabel padanan: {e}")
    analysis = await po_berjalan.analyse(db, raw_rows, alias_rows)
    groups = analysis.pop("_groups")
    summary = {"key": "po_berjalan", "label": entry["label"], "mode": mode,
               "alias_rows": len(alias_rows), **analysis}
    if mode != "commit":
        return summary
    if analysis["invalid"]:
        raise HTTPException(400, f"Ada {analysis['invalid']} baris bermasalah. Perbaiki dulu sebelum impor.")
    res = await po_berjalan.commit(db, {"_groups": groups}, user)
    await log_activity(user.get("id"), user.get("name"), "import", "data-transfer:po_berjalan",
                       f"PO berjalan: {len(res['created'])} PO dibuat, {len(res['failed'])} gagal")
    summary.update({"committed": True, "inserted": len(res["created"]), "updated": 0,
                    "created": res["created"], "failed": res["failed"]})
    return summary


@router.post("/import/{key}")
async def import_table(key: str, request: Request, file: UploadFile = File(...), mode: str = Query("dry_run"),
                       alias_file: UploadFile | None = File(None)):
    user = await require_auth(request)
    entry = _get_entry(key)
    if not entry.get("importable"):
        raise HTTPException(400, "Tabel ini tidak mendukung import (export-only)")
    if not await _may(request, user, entry, "import"):
        raise HTTPException(403, "Anda tidak punya akses impor tabel ini")
    db = get_db()
    content = await file.read()
    handler = entry.get("handler")
    try:
        raw_rows = _parse_upload(file.filename, content,
                                 (dtm.HANDLERS.get(handler) or {}).get("sheet_names", ()) if handler else ())
    except Exception as e:
        raise HTTPException(400, f"Gagal membaca file: {e}")
    if entry.get("handler") == "po_berjalan":
        return await _import_po_berjalan(db, user, entry, raw_rows, alias_file, mode)

    if handler:
        # 2026-11-06 (T4): master dengan penangan khusus — pratinjau → terapkan (validasi ulang), upsert idempoten
        res = await dtm.run_import(handler, db, raw_rows, user, commit=(mode == "commit"))
        summary = {"key": key, "label": entry["label"], "mode": mode, **res}
        if summary.get("committed"):
            await log_activity(user.get("id"), user.get("name"), "import", f"data-transfer:{key}",
                               f"impor {summary['inserted']} baru, {summary['updated']} diperbarui, "
                               f"{summary['skipped']} dilewati")
        return summary

    cols = entry["columns"]
    keyf = entry["key"]
    defaults = entry.get("import_defaults") or {}
    colnames = {c["name"]: c for c in cols}

    valid, invalid = [], []
    for idx, raw in enumerate(raw_rows):
        errors = []
        doc = {}
        for c in cols:
            cn = c["name"]
            v, err = _coerce(raw.get(cn, raw.get(c.get("label"))), c["type"], cn)
            if err:
                errors.append(err)
            if v is not None:
                doc[cn] = v
        # per-collection normalization (before key/validation so upsert is consistent)
        if entry["collection"] == "users" and doc.get("email"):
            doc["email"] = str(doc["email"]).strip().lower()
        # required checks
        for c in cols:
            if c.get("required") and (doc.get(c["name"]) in (None, "")):
                errors.append(f"'{c['name']}' wajib diisi")
        # key present
        for kf in keyf:
            if doc.get(kf) in (None, ""):
                errors.append(f"key '{kf}' kosong")
        row_info = {"row": raw.get("__row__") or idx + 2, "data": {k: _to_cell(v, colnames.get(k, {}).get("type")) for k, v in doc.items()}}
        if errors:
            row_info["errors"] = errors
            invalid.append(row_info)
        else:
            valid.append((doc, row_info))

    # 2026-11-02 (S2-H, T8): baris Bagan Akun melewati penjaga yang SAMA dengan layar (PUT/POST
    # /api/rahaza/coa/accounts): grup/rinci, nonaktif, induk, tipe, kode, dan penanda di-MERGE.
    # Dulu `$set` seluruh baris → akun berjurnal bisa jadi grup/beda tipe, penanda toko terhapus.
    if entry["collection"] == "rahaza_coa_accounts" and valid:
        from routes.rahaza_coa import prepare_coa_import
        prepared = await prepare_coa_import(db, [d for d, _ in valid])
        coa_valid = []
        for (doc, info), (prep, errs) in zip(valid, prepared):
            if errs:
                info["errors"] = errs
                invalid.append(info)
                continue
            doc.clear()
            doc.update(prep)
            coa_valid.append((doc, info))
        valid = coa_valid

    # detect insert vs update for preview
    would_insert = would_update = 0
    still_valid = []
    seen_ref: dict = {}
    for doc, info in valid:
        q = {kf: doc[kf] for kf in keyf}
        existing = await db[entry["collection"]].find_one(q)
        # 2026-11-06 (pola P8): baris BARU yang namanya setara dengan master aktif lain (kode beda) ditolak —
        # begitulah "Jahit / Sewing" (JAHIT) lahir di samping "Jahit (CMT)" (SEWING).
        # Baris lama yang SUDAH digabung (`duplicate_of`) juga tidak boleh dihidupkan lagi lewat impor.
        ref_err = (await _ref_name_clash(db, entry["collection"], doc, seen_ref) if not existing
                   else _merged_row_note(entry["collection"], existing))
        if ref_err:
            info["errors"] = [ref_err]
            invalid.append(info)
            continue
        if entry["collection"] == "rahaza_materials":
            uom_fields, uom_errs = await _material_uom_fields(db, doc, existing)
            if uom_errs:
                info["errors"] = uom_errs
                invalid.append(info)
                continue
            if uom_fields:
                doc.update(uom_fields)
                info["data"].update({
                    "base_uom": uom_fields.get("base_uom"),
                    "pack_unit": uom_fields.get("pack_unit"),
                    "pack_size": uom_fields.get("pack_size"),
                    "satuan": " · ".join(f"{r['code']}×{r['factor']:g}" for r in uom_fields.get("uoms", [])),
                })
            cost_err = await _material_cost_guard(db, doc, existing)
            if cost_err:
                info["errors"] = [cost_err]
                invalid.append(info)
                continue
        if existing:
            info["action"] = "update"
            would_update += 1
        else:
            info["action"] = "insert"
            would_insert += 1
        still_valid.append((doc, info))
    valid = still_valid

    summary = {
        "key": key, "label": entry["label"], "mode": mode,
        "total_rows": len(raw_rows), "valid": len(valid), "invalid": len(invalid),
        "would_insert": would_insert, "would_update": would_update,
        "preview_valid": [i for _, i in valid][:100],
        "preview_invalid": invalid[:100],
    }

    if mode != "commit":
        return summary

    if invalid:
        raise HTTPException(400, f"Ada {len(invalid)} baris invalid. Perbaiki dulu sebelum commit (atau hapus baris invalid).")

    inserted = updated = 0
    for doc, info in valid:
        q = {kf: doc[kf] for kf in keyf}
        existing = await db[entry["collection"]].find_one(q)
        if existing:
            doc["updated_at"] = _now()
            await db[entry["collection"]].update_one({"_id": existing["_id"]}, {"$set": doc})
            updated += 1
            if entry["collection"] == "rahaza_materials":
                await _record_material_cost(db, doc, existing, user)
        else:
            for dk, dv in defaults.items():
                doc.setdefault(dk, dv)
            # per-collection insert hooks (e.g. hash user passwords so imported logins work)
            if entry["collection"] == "users":
                doc["password"] = hash_password(str(doc.get("password") or "Dewi@123"))
                doc.setdefault("permissions", [])
            doc.setdefault("id", _uid())
            doc.setdefault("active", True)
            doc["created_at"] = _now()
            doc["updated_at"] = _now()
            doc["created_by"] = user.get("id")
            doc["created_by_name"] = user.get("name")
            await db[entry["collection"]].insert_one(doc)
            inserted += 1
            if entry["collection"] == "rahaza_materials":
                await _record_material_cost(db, doc, None, user)

        # Phase 5/6: auto-create COA subledger on import (idempotent, non-fatal)
        # 2026-11-06 (pola P2): kunci = koleksi master yang dibaca Auto Akun (cmt_vendor →
        # vendor_partners; supplier → rahaza_suppliers). Dulu `dewi_cmt_partners` (master lama) →
        # sub-ledger ditandai id lama & kodenya ditulis ke dokumen vendor_partners yang tidak ada.
        _COA_AUTO_COLLECTIONS = {
            "vendor_partners": "cmt_vendor",
            "rahaza_suppliers": "supplier",
            "rahaza_customers": "customer",
            "marketing_platform_accounts": "channel",
            "rahaza_cash_accounts": "bank",
        }
        _et = _COA_AUTO_COLLECTIONS.get(entry["collection"])
        if _et:
            # 2026-11-06 (T4): satu helper (juga dipakai impor Supplier/Pelanggan) — log bila gagal
            await dtm.auto_subledger(db, _et, doc, user)

    await log_activity(user.get("id"), user.get("name"), "import",
                       f"data-transfer:{key}", f"import {inserted} baru, {updated} update")
    summary.update({"committed": True, "inserted": inserted, "updated": updated})
    return summary
