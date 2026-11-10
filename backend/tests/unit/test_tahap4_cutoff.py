"""Tahap 4 · agen `cutoff` (2026-11-06) — T5 cutoff "hapus transaksi saja" + T6 impor PO berjalan.

T5  · setiap koleksi yang disebut kode / ada di basis data punya JENIS (konfigurasi/master/transaksi/log);
      koleksi tak dikenal → rencana ditolak; apply menghapus transaksi+log, master utuh, field turunan
      direset (unit_cost master TETAP), nomor dokumen dilanjutkan kecuali --reset-nomor (hanya
      penghitung transaksi); skrip: dry-run bawaan, --apply wajib --yes + ketik konfirmasi + mongodump dulu.
T6  · impor PO berjalan: pratinjau galat per baris, padanan kode (unggah + master), kelompok per
      (kode potongan, CMT), PO Dikonfirmasi lewat jalur resmi (jadwal piutang/hutang maklon), surat jalan
      saldo awal TANPA potong stok/jurnal, qty = sisa di CMT (hutang hanya untuk sisa), idempoten, hak akses.
"""
import asyncio
import copy
import csv
import importlib.util
import io
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeCollection, FakeDB, FakeRequest, _Result, _set_path, match  # noqa: E402
import auth  # noqa: E402
from core import collection_registry as cr  # noqa: E402
from core import cutoff_reset  # noqa: E402
from core import po_berjalan_import as pbi  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
ADMIN = {"id": "u1", "name": "Admin Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


class _Coll(FakeCollection):
    """Tambahan secukupnya untuk uji ini: `$unset` di update_many, `_id` counters, find_one_and_update."""

    async def update_many(self, q, upd):
        n = 0
        for d in self.docs:
            if match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    _set_path(d, k, copy.deepcopy(v))
                for k in (upd.get("$unset") or {}):
                    d.pop(k, None)
                n += 1
        return _Result(matched=n, modified=n)

    async def find_one_and_update(self, q, upd, upsert=False, return_document=None, **_k):
        for d in self.docs:
            if match(d, q):
                for k, v in (upd.get("$inc") or {}).items():
                    d[k] = d.get(k, 0) + v
                return copy.deepcopy(d)
        if upsert:
            d = {k: v for k, v in q.items() if not k.startswith("$")}
            d.update(upd.get("$setOnInsert") or {})
            for k, v in (upd.get("$inc") or {}).items():
                d[k] = d.get(k, 0) + v
            self.docs.append(d)
            return copy.deepcopy(d)
        return None


class _DB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _Coll(name)
        return self._cols[name]


# ══════════════════════════════════════════════════════════════════════════════
# T5 · klasifikasi
# ══════════════════════════════════════════════════════════════════════════════
_ATTR = re.compile(r"\bdb\s*\.\s*([a-z][a-z0-9_]*)\s*\.\s*([a-z_]+)\s*\(")
_LIT = re.compile(r"""\b(?:db|_db|database|mdb)\s*\[\s*['"]([a-z][a-z0-9_]*)['"]\s*\]""")
_GETC = re.compile(r"""get_collection\(\s*['"]([a-z][a-z0-9_]*)['"]""")
_CONST = re.compile(r"""^\s*([A-Z][A-Z0-9_]*)\s*(?::\s*str\s*)?=\s*['"]([a-z][a-z0-9_]+)['"]""", re.M)
_DBCONST = re.compile(r"""\b(?:db|_db)\s*\[\s*(?:[a-z_][a-z0-9_]*\.)*([A-Z][A-Z0-9_]*)\s*\]""")
_NOT = {"client", "command", "list_collection_names", "get_collection", "name", "db", "admin",
        "drop_database", "create_collection", "with_options", "codec_options", "read_preference",
        "write_concern", "watch", "aggregate", "dereference", "validate_collection", "drop_collection",
        "list_collections", "create_index"}


def _code_collections() -> dict:
    found, consts, used = {}, {}, {}
    for dp, _dirs, files in os.walk(BACKEND):
        parts = Path(dp).parts
        if "_archive" in parts or "__pycache__" in parts or "tests" in parts:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            p = Path(dp) / f
            src = p.read_text(encoding="utf-8", errors="ignore")
            for m in _ATTR.finditer(src):
                if m.group(1) not in _NOT:
                    found.setdefault(m.group(1), str(p))
            for rx in (_LIT, _GETC):
                for n in rx.findall(src):
                    found.setdefault(n, str(p))
            for k, v in _CONST.findall(src):
                consts.setdefault(k, set()).add(v)
            for c in _DBCONST.findall(src):
                used.setdefault(c, str(p))
    for c, where in used.items():
        for v in consts.get(c, ()):
            found.setdefault(v, where)
    return found


def test_semua_koleksi_kode_dan_registri_punya_jenis():
    code = _code_collections()
    assert len(code) > 300
    tanpa = {n: w for n, w in code.items() if cr.kind_of(n) is None}
    assert tanpa == {}, f"koleksi tanpa jenis (tambahkan di collection_registry KIND): {tanpa}"
    assert sorted(cr.all_known() - set(cr.KIND)) == []
    assert set(cr.KIND.values()) == set(cr.KINDS)


def test_klasifikasi_contoh_keputusan_owner():
    master = ("rahaza_materials rahaza_models rahaza_model_variants rahaza_boms rahaza_colors rahaza_sizes "
              "wh_unit_master rahaza_suppliers rahaza_supplier_price_lists rahaza_customers vendor_partners "
              "dewi_maklon_clients dewi_maklon_buyer_catalog rahaza_employees rahaza_payroll_profiles "
              "da_payroll_allowances rahaza_leave_types rahaza_shifts rahaza_production_calendar "
              "rahaza_locations wh_positions marketing_platform_accounts marketing_catalogs "
              "marketing_catalog_items marketing_sku_bridge rahaza_coa_accounts rahaza_cash_accounts "
              "rahaza_fixed_assets users").split()
    konfig = "rahaza_posting_profiles roles role_permissions doc_number_configs pdf_templates counters".split()
    transaksi = ("production_pos po_items rahaza_purchase_orders warehouse_receiving rahaza_material_stock "
                 "rahaza_stock_ledger rahaza_material_movements rahaza_material_issues wh_returns "
                 "wh_opname3_sessions production_jobs production_progress cutting_orders vendor_shipments "
                 "cmt_receipts dewi_cmt_payments rahaza_ar_invoices rahaza_ap_invoices rahaza_journal_entries "
                 "bank_recon_sessions rahaza_attendance_events rahaza_leave_requests rahaza_overtime_requests "
                 "rahaza_payroll_runs rahaza_payslips dewi_kasbon_requests rahaza_expenses marketing_orders "
                 "marketing_data_import_sessions marketing_settlements fg_cost_layers").split()
    for n in master:
        assert cr.kind_of(n) == "master", n
    for n in konfig:
        assert cr.kind_of(n) == "konfigurasi", n
    for n in transaksi:
        assert cr.kind_of(n) == "transaksi", n
    for n in ("notifications", "activity_logs", "login_attempts"):
        assert cr.kind_of(n) == "log", n
    # unit_cost master dipertahankan secara eksplisit
    mat = cr.derived_field_rules("rahaza_materials")[0]
    assert "unit_cost" in mat["keep"] and "unit_cost" not in mat.get("unset", [])


def test_jenis_penghitung_nomor():
    assert cr.counter_kind("autonum:production_pos:po_number:PO-INT-202611-") == "transaksi"
    assert cr.counter_kind("autonum:rahaza_suppliers:code:SUP-") == "master"
    assert cr.counter_kind("model_code_DA") == "master"
    assert cr.counter_kind("RCV") == "transaksi"
    assert cr.counter_kind("docnum:buyer_shipment_da:2026") == "transaksi"
    assert cr.counter_kind("approval_requests") == "transaksi"
    assert cr.counter_kind("hr_shift_assignments") == "master"
    assert cr.counter_kind("kunci_aneh") is None


# ══════════════════════════════════════════════════════════════════════════════
# T5 · rencana & eksekusi di basis data palsu
# ══════════════════════════════════════════════════════════════════════════════
def _cutoff_db():
    db = _DB()
    db.users.docs = [{"id": "sa", "email": "admin@garment.com", "role": "superadmin", "last_login_at": "x"},
                     {"id": "u2", "email": "staf@x", "role": "hr"}]
    db.roles.docs = [{"id": "r1", "name": "admin"}]
    db.rahaza_materials.docs = [
        {"id": "m1", "code": "KN-1", "unit_cost": 25000, "hpp": 25000, "last_receipt_unit_cost": 24000},
        {"id": "fg1", "code": "DA-1-A", "type": "fg", "unit_cost": 80000, "hpp_fifo_avg": 79000,
         "hpp_last_batch": 81000, "hpp_layer_qty": 3}]
    db.rahaza_models.docs = [{"id": "md1", "code": "DA-1", "hpp": 80000}]
    db.vendor_partners.docs = [{"id": "vp1", "code": "CMT-A", "name": "Penjahit"}]
    db.marketing_catalogs.docs = [{"id": "cat1", "item_count": 2, "total_stock": 9, "low_stock_count": 1,
                                   "out_of_stock_count": 0}]
    db.marketing_catalog_items.docs = [
        {"id": "ci1", "catalog_id": "cat1", "is_active": True, "stock_quantity": 9, "stock_status": "in_stock",
         "fg_onhand": 9, "fg_available": 9, "fg_reserved": 0, "hpp": 80000, "harga_jual": 150000,
         "hpp_fifo_avg": 1, "fg_material_id": "fg1"},
        {"id": "ci2", "catalog_id": "cat1", "is_active": True, "stock_quantity": 0, "stock_status": "out_of_stock"},
        {"id": "ci3", "catalog_id": "cat1", "is_active": False, "stock_quantity": 4}]
    db.rahaza_cash_accounts.docs = [{"id": "k1", "code": "BCA", "opening_balance": 5_000_000,
                                     "opening_balance_date": "2026-09-01", "opening_je_id": "je0",
                                     "opening_je_number": "JE-0"}]
    db.rahaza_leave_balances.docs = [{"id": "lb1", "employee_id": "e1", "allocated": 12, "used": 3,
                                      "adjustments": [{"delta": 1}]}]
    db.dewi_maklon_buyer_catalog.docs = [{"id": "bc1", "total_qty_produced": 300, "total_revenue": 4.5e6,
                                          "last_used_at": "2026-10-01", "default_cmt_price": 8500}]
    db.rahaza_periods.docs = [{"period_code": "2026-10", "status": "closed"}]
    # transaksi + log
    db.production_pos.docs = [{"id": "po1"}, {"id": "po2"}]
    db.po_items.docs = [{"id": "pi1", "po_id": "po1"}]
    db.rahaza_material_stock.docs = [{"id": "st1", "material_id": "m1", "qty": 4}]
    db.rahaza_journal_entries.docs = [{"id": "je0"}]
    db.fg_cost_layers.docs = [{"id": "ly1", "material_id": "fg1"}]
    db.notifications.docs = [{"id": "n1"}, {"id": "n2"}]
    db.activity_logs.docs = [{"id": "a1"}]
    db.counters.docs = [{"_id": "autonum:production_pos:po_number:PO-INT-202611-", "seq": 7},
                        {"_id": "autonum:rahaza_suppliers:code:SUP-", "seq": 3},
                        {"_id": "model_code_DA", "seq": 12}, {"_id": "RCV", "seq": 10}]
    return db


def test_rencana_menolak_koleksi_belum_diklasifikasi():
    db = _cutoff_db()
    db.koleksi_baru_tanpa_jenis.docs = [{"id": "x"}]
    plan = run(cutoff_reset.build_plan(db))
    assert [r["name"] for r in plan["unknown"]] == ["koleksi_baru_tanpa_jenis"]
    assert "koleksi_baru_tanpa_jenis" in cutoff_reset.refusal_reasons(plan)[0]
    with pytest.raises(cutoff_reset.CutoffRefused):
        run(cutoff_reset.apply_plan(db, plan))
    assert len(db.production_pos.docs) == 2          # tidak ada yang dihapus


def test_cutoff_hapus_transaksi_pertahankan_master_dan_reset_turunan():
    db = _cutoff_db()
    plan = run(cutoff_reset.build_plan(db))
    by_kind = {k: {r["name"]: r["count"] for r in rows} for k, rows in plan["classes"].items()}
    assert by_kind["transaksi"]["production_pos"] == 2 and by_kind["log"]["notifications"] == 2
    assert by_kind["master"]["rahaza_materials"] == 2 and by_kind["konfigurasi"]["roles"] == 1
    assert plan["totals"]["hapus"] == 2 + 1 + 1 + 1 + 1 + 2 + 1
    master_before = {n: len(db[n].docs) for n in ("users", "rahaza_materials", "rahaza_models", "vendor_partners",
                                                   "marketing_catalog_items", "rahaza_cash_accounts")}
    res = run(cutoff_reset.apply_plan(db, plan))
    assert res["deleted_total"] == plan["totals"]["hapus"]
    for n in ("production_pos", "po_items", "rahaza_material_stock", "rahaza_journal_entries", "fg_cost_layers",
              "notifications", "activity_logs"):
        assert db[n].docs == [], n
    assert {n: len(db[n].docs) for n in master_before} == master_before      # master utuh (termasuk SEMUA user)
    assert len(db.roles.docs) == 1 and len(db.counters.docs) == 4            # nomor dilanjutkan (bawaan)
    m1, fg = db.rahaza_materials.docs
    assert m1["unit_cost"] == 25000 and fg["unit_cost"] == 80000             # HPP master TETAP
    assert "last_receipt_unit_cost" not in m1 and "hpp_layer_qty" not in fg and "hpp_fifo_avg" not in fg
    ci1, ci2, ci3 = db.marketing_catalog_items.docs
    assert (ci1["stock_quantity"], ci1["stock_status"], ci1["fg_onhand"], ci1["fg_available"]) == (0, "out_of_stock", 0, 0)
    assert ci1["hpp"] == 80000 and ci1["harga_jual"] == 150000 and "hpp_fifo_avg" not in ci1
    assert ci3["stock_quantity"] == 0
    cat = db.marketing_catalogs.docs[0]
    assert (cat["item_count"], cat["total_stock"], cat["low_stock_count"], cat["out_of_stock_count"]) == (2, 0.0, 0, 2)
    k1 = db.rahaza_cash_accounts.docs[0]
    assert k1["opening_balance"] == 0.0 and k1["opening_je_id"] is None and k1["code"] == "BCA"
    lb = db.rahaza_leave_balances.docs[0]
    assert lb["used"] == 0 and lb["allocated"] == 12 and lb["adjustments"] == [{"delta": 1}]
    bc = db.dewi_maklon_buyer_catalog.docs[0]
    assert bc["total_qty_produced"] == 0 and bc["total_revenue"] == 0.0 and bc["default_cmt_price"] == 8500
    assert db.rahaza_periods.docs[0]["status"] == "closed"


def test_reset_nomor_hanya_penghitung_transaksi_dan_menolak_kunci_asing():
    db = _cutoff_db()
    plan = run(cutoff_reset.build_plan(db, reset_nomor=True))
    assert sorted(r["key"] for r in plan["counters"]["reset"]) == [
        "RCV", "autonum:production_pos:po_number:PO-INT-202611-"]
    run(cutoff_reset.apply_plan(db, plan))
    assert sorted(c["_id"] for c in db.counters.docs) == ["autonum:rahaza_suppliers:code:SUP-", "model_code_DA"]
    db2 = _cutoff_db()
    db2.counters.docs.append({"_id": "kunci_tak_dikenal", "seq": 1})
    p2 = run(cutoff_reset.build_plan(db2, reset_nomor=True))
    assert "kunci_tak_dikenal" in " ".join(cutoff_reset.refusal_reasons(p2))
    assert cutoff_reset.refusal_reasons(run(cutoff_reset.build_plan(db2))) == []   # tanpa --reset-nomor aman


def _load_script():
    spec = importlib.util.spec_from_file_location("reset_for_golive_uji", REPO / "scripts" / "reset_for_golive.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_skrip_transaksi_saja_dryrun_yes_konfirmasi_dan_backup_dulu(monkeypatch, capsys):
    import motor.motor_asyncio as mm
    db = _cutoff_db()

    class Client:
        def __init__(self, *_a, **_k):
            pass

        def __getitem__(self, _name):
            return db

        def close(self):
            pass
    monkeypatch.setattr(mm, "AsyncIOMotorClient", Client)
    mod = _load_script()
    dumps = []

    def fake_dump(uri, dbname, label="pre_golive"):
        dumps.append((label, len(db.production_pos.docs)))          # cadangan dibuat SEBELUM hapus
        return Path("/tmp/uji_backup")
    monkeypatch.setattr(mod, "mongodump", fake_dump)

    assert run(mod.main_transaksi_saja(False, False, False)) == 0      # dry-run
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "production_pos" in out and "DIHAPUS" in out and "DIPERTAHANKAN" in out
    assert len(db.production_pos.docs) == 2 and dumps == []
    assert run(mod.main_transaksi_saja(True, False, False)) == 1       # --apply tanpa --yes
    assert len(db.production_pos.docs) == 2 and dumps == []
    monkeypatch.setattr("builtins.input", lambda *_a: "hapus")
    assert run(mod.main_transaksi_saja(True, True, False)) == 1        # konfirmasi salah
    assert len(db.production_pos.docs) == 2 and dumps == []
    monkeypatch.setattr("builtins.input", lambda *_a: "HAPUS TRANSAKSI")
    assert run(mod.main_transaksi_saja(True, True, False)) == 0
    assert dumps == [("pre_cutoff", 2)] and db.production_pos.docs == [] and len(db.users.docs) == 2
    db.koleksi_aneh.docs = [{"id": 1}]
    assert run(mod.main_transaksi_saja(False, False, False)) == 2      # belum diklasifikasi → ditolak


# ══════════════════════════════════════════════════════════════════════════════
# T6 · impor PO berjalan
# ══════════════════════════════════════════════════════════════════════════════
MAPPING = {
    "maklon_ar_invoice": {"debit_ar": "1-1301", "credit_revenue_maklon": "4-1100", "credit_tax_output": "2-1400"},
    "cmt_ap_invoice": {"credit_ap": "2-1110", "debit_cmt_expense_maklon": "5-4200",
                       "debit_cmt_wip_internal": "1-1403"},
}
HEADER = ["Tanggal", "Kode potongan / No PO", "SKU", "Model", "Warna", "Ukuran", "CMT", "Qty potong",
          "Qty sudah diterima", "Sisa di CMT", "Upah CMT", "Harga ke klien", "Klien", "Jenis",
          "Tenggat produksi", "Tenggat kirim"]


def _csv(rows, header=HEADER) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def _rows(content: bytes) -> list:
    import routes.data_transfer as dt
    return dt._parse_upload("x.csv", content)


class Up:
    def __init__(self, name, data):
        self.filename, self._d = name, data

    async def read(self):
        return self._d


def _master_db():
    db = _DB()
    db.rahaza_models.docs = [{"id": "m1", "code": "DA-9507", "name": "Celana Uji", "active": True},
                             {"id": "m2", "code": "DA-9351", "name": "Blus Uji", "active": True,
                              "name_aliases": ["Blus Uji M"]}]
    db.rahaza_sizes.docs = [{"id": "s-all", "code": "ALLSIZE", "name": "ALL SIZE", "active": True},
                            {"id": "s-m", "code": "M", "name": "M", "active": True}]
    db.rahaza_colors.docs = [{"id": "c1", "code": "KTB", "name": "Kotak Besar"},
                             {"id": "c2", "code": "RDE", "name": "Red Elegant"},
                             {"id": "c3", "code": "RDX", "name": "Red Lama", "alias_of_code": "RDE"}]
    db.rahaza_model_variants.docs = [
        {"id": "v1", "sku": "DA-9507-KTB-ALLSIZE", "model_id": "m1", "model_code": "DA-9507", "model_name": "Celana Uji",
         "size_id": "s-all", "size_code": "ALLSIZE", "color_code": "KTB", "color_name": "Kotak Besar", "active": True},
        {"id": "v2", "sku": "DA-9351-RDE-M", "model_id": "m2", "model_code": "DA-9351", "model_name": "Blus Uji",
         "size_id": "s-m", "size_code": "M", "color_code": "RDE", "color_name": "Red Elegant", "active": True},
        {"id": "v0", "sku": "DA-9350-RDE-M", "merged_into_sku": "DA-9351-RDE-M", "active": False}]
    db.vendor_partners.docs = [{"id": "vp1", "code": "CMT-A", "name": "Penjahit Satu", "is_active": True},
                               {"id": "vp2", "code": "CMT-B", "name": "Penjahit Dua", "is_active": True},
                               {"id": "vp3", "code": "CMT-X", "name": "Penjahit Lama", "is_active": False}]
    db.dewi_maklon_clients.docs = [{"id": "cl1", "code": "KLN-01", "name": "PT Klien Satu", "status": "active"}]
    db.dewi_maklon_buyer_catalog.docs = [{"id": "bc1", "client_id": "cl1", "artikel_code": "9152",
                                          "buyer_ref_code": "BR-9152", "product_name": "DRESS UJI", "variants": []}]
    db.rahaza_periods.docs = [{"period_code": "2026-11", "status": "open"}]
    db.rahaza_coa_accounts.docs = [
        {"code": c, "name": n, "type": t, "is_group": g, "active": True}
        for c, n, t, g in (("1-1301", "Piutang Dagang", "ASSET", False), ("1-1305", "Piutang Maklon", "ASSET", False),
                           ("4-1500", "Pendapatan Maklon", "REVENUE", True), ("2-1110", "Hutang CMT", "LIABILITY", False),
                           ("1-1403", "WIP", "ASSET", False), ("5-4200", "Biaya CMT Maklon", "COGS", False))]
    return db


@pytest.fixture
def env(monkeypatch):
    import cascade_delete
    import routes.data_transfer as dt
    import routes.dewi_maklon_finance as dmf
    import routes.dewi_maklon_pos as dmpos
    import routes.production_internal_adapter as pia
    import routes.production_maklon_bridge as bridge
    import routes.production_pos as ppos
    import routes.rahaza_posting as rposting
    import routes.rahaza_posting_profiles as profiles
    import routes.vendor_shipment as vs
    import routes.coa_auto as coa_auto
    from core import doc_number_policy as dnp
    from core import material_issue_engine as mie
    from core import product_costing as pc
    from utils import counters as uc

    db = _master_db()
    jes, calls = [], {"explode": 0, "mi": 0}

    async def create_je(*_a, **_k):
        jes.append(_k or _a)
        return {"ok": True, "je_id": f"je{len(jes)}", "je_number": f"JE-{len(jes)}"}

    async def mapping(_db, et):
        return dict(MAPPING.get(et, {}))
    seq = {}

    async def issue_number(_db, key, *, ctx=None, requested=""):
        if requested:
            return requested
        seq[key] = seq.get(key, 0) + 1
        return f"{'PO' if key.startswith('production_pos') else 'SHP'}-UJI-{seq[key]:04d}"

    async def gen_number(_db, coll, field, prefix, width=4, *_a, **_k):
        seq[coll] = seq.get(coll, 0) + 1
        return f"{prefix}{seq[coll]:0{width}d}"
    inv = {"n": 0}

    async def inv_number(_db):
        inv["n"] += 1
        return f"INV-MKL-{inv['n']:04d}"

    async def explode(*_a, **_k):
        calls["explode"] += 1
        return {}

    async def mi(*_a, **_k):
        calls["mi"] += 1
        raise AssertionError("surat jalan saldo awal tidak boleh menerbitkan Material Issue")

    async def mcost(_db, model_id, size_id, **_k):
        return {"material_cost": 5000.0}

    async def noop(*_a, **_k):
        return None
    monkeypatch.setattr(dnp, "issue_number", issue_number)
    monkeypatch.setattr(uc, "gen_prefixed_number", gen_number)
    monkeypatch.setattr(dmf, "_create_posted_je", create_je)
    monkeypatch.setattr(rposting, "_create_posted_je", create_je)
    monkeypatch.setattr(dmf, "get_mapping", mapping)
    monkeypatch.setattr(profiles, "get_mapping", mapping)
    monkeypatch.setattr(dmpos, "_next_ar_invoice_number", inv_number)
    monkeypatch.setattr(pia, "explode_po_accessories_from_bom", explode)
    monkeypatch.setattr(mie, "issue_for_vendor_shipment", mi)
    monkeypatch.setattr(mie, "issue_for_maklon_shipment", mi)
    monkeypatch.setattr(pc, "compute_material_cost", mcost)
    import routes.production_execution as pe
    for mod in (ppos, vs, bridge, dt, coa_auto, dmf, pe):
        monkeypatch.setattr(mod, "log_activity", noop)
    monkeypatch.setattr(auth, "log_activity", noop)
    monkeypatch.setattr(cascade_delete, "get_db", lambda: db)
    monkeypatch.setattr(dt, "get_db", lambda: db)
    return {"db": db, "jes": jes, "calls": calls, "dt": dt}


GOOD = [
    ["2026-10-20", "CUT-01", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-A", "100", "60", "40", "12.000", "", "", "internal"],
    ["2026-10-20", "CUT-01", "", "Blus Uji M", "Red Lama", "M", "CMT-A", "30", "0", "", "10000", "", "", "internal"],
    ["2026-10-20", "CUT-01", "DA-9507-KTB-ALLSIZE", "", "", "", "Penjahit Dua", "20", "5", "15", "12000", "", "",
     "Internal"],
    ["2026-10-21", "", "9152", "", "Hitam", "M", "CMT-B", "50", "10", "40", "8.500", "15000", "KLN-01", "maklon"],
    ["2026-10-21", "CUT-02", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-A", "10", "10", "0", "12000", "", "", "internal"],
]


def test_pratinjau_galat_per_baris(env):
    db = env["db"]
    bad = [
        ["2026-10-20", "B1", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-Z", "10", "0", "10", "1000", "", "", "internal"],
        ["2026-10-20", "B2", "DA-9999-XXX-M", "", "", "", "CMT-A", "10", "0", "10", "1000", "", "", "internal"],
        ["2026-10-20", "B3", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-A", "10", "2", "5", "1000", "", "", "internal"],
        ["2026-10-20", "B4", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-A", "10", "0", "10", "", "", "", "internal"],
        ["2026-10-20", "B5", "9152", "", "", "M", "CMT-A", "10", "0", "10", "1000", "", "", "maklon"],
        ["2026-10-20", "B6", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-X", "10", "0", "10", "1000", "", "", "internal"],
        ["2026-10-20", "B7", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-A", "10", "0", "10", "1000", "", "", ""],
        ["32/13/2026", "B8", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-A", "10", "0", "10", "1000", "", "", "internal"],
    ]
    a = run(pbi.analyse(db, _rows(_csv(bad))))
    errs = {r["row"]: " ".join(r["errors"]) for r in a["preview_invalid"]}
    assert a["invalid"] == 8 and a["valid"] == 0 and a["_groups"] == []
    assert "CMT 'CMT-Z' tidak ada" in errs[2]
    assert "SKU 'DA-9999-XXX-M' tidak ada" in errs[3]
    assert "Qty tidak cocok" in errs[4]
    assert "Upah CMT wajib" in errs[5]
    assert "Klien wajib" in errs[6] and "Harga ke klien wajib" in errs[6]
    assert "nonaktif" in errs[7]
    assert "Jenis wajib" in errs[8]
    assert "tanggal '32/13/2026' tidak dikenali" in errs[9]
    assert db.production_pos.docs == []


def test_padanan_unggah_dan_master():
    al = pbi.parse_aliases(_rows(_csv([
        ["SKU", "DA-9001-PHT-XL", "DA-9507-KTB-ALLSIZE", "uji"],
        ["SKU (Contoh M → All Size)", "CELANA UJI · KOTAK BESAR · M", "DA-9507-KTB-ALLSIZE", "uji"],
        ["model", "JENNIFER UJI M (nama di Excel)", "DA-9351", "uji"],
        ["warna", "MERAH TUA (Excel: a, b) / merah tuaa (BOM)", "RDE", "uji"],
        ["model", "RUBY (DATA ERP) / RACHEL X (DATA ERP)", "Celana Uji / Blus Uji", ""],
        ["aksesoris (kode lama)", "A4 Label", "A-LBL-1", "abaikan"]],
        header=["jenis", "tertulis_di_excel", "kode_erp", "catatan"])))
    assert al["sku"]["da-9001-pht-xl"] == "DA-9507-KTB-ALLSIZE"
    assert al["sku"]["celana uji|kotak besar|m"] == "DA-9507-KTB-ALLSIZE"
    assert al["model"]["jennifer uji m"] == "DA-9351"
    assert al["warna"]["merah tua"] == "RDE" and al["warna"]["merah tuaa"] == "RDE"
    assert al["model"]["ruby"] == "Celana Uji" and al["model"]["rachel x"] == "Blus Uji"
    assert "a4 label" not in str(al)


def test_padanan_menyelesaikan_sku_dalam_impor(env):
    db = env["db"]
    alias = _rows(_csv([["SKU", "DA-9001-PHT-XL", "DA-9507-KTB-ALLSIZE", ""],
                        ["SKU", "CELANA UJI · KOTAK BESAR · M", "DA-9507-KTB-ALLSIZE", ""],
                        ["model", "JENNIFER UJI M (nama di Excel)", "DA-9351", ""],
                        ["warna", "merah tuaa (BOM)", "RDE", ""]],
                       header=["jenis", "tertulis_di_excel", "kode_erp", "catatan"]))
    rows = [
        ["", "A1", "DA-9001-PHT-XL", "", "", "", "CMT-A", "5", "0", "5", "1000", "", "", "internal"],
        ["", "A2", "", "Celana Uji", "Kotak Besar", "M", "CMT-A", "5", "0", "5", "1000", "", "", "internal"],
        ["", "A3", "", "JENNIFER UJI M", "merah tuaa", "M", "CMT-A", "5", "0", "5", "1000", "", "", "internal"],
        ["", "A4", "", "9507", "KTB", "ALL SIZE", "CMT-A", "5", "0", "5", "1000", "", "", "internal"],   # 9507 = DA-9507
        ["", "A5", "DA-9350-RDE-M", "", "", "", "CMT-A", "5", "0", "5", "1000", "", "", "internal"],     # varian digabung
    ]
    a = run(pbi.analyse(db, _rows(_csv(rows)), alias))
    assert a["invalid"] == 0, a["preview_invalid"]
    skus = {r["data"]["PO"]: r["data"]["Barang"] for r in a["preview_valid"]}
    assert skus == {"A1": "DA-9507-KTB-ALLSIZE", "A2": "DA-9507-KTB-ALLSIZE", "A3": "DA-9351-RDE-M",
                    "A4": "DA-9507-KTB-ALLSIZE", "A5": "DA-9351-RDE-M"}
    b = run(pbi.analyse(db, _rows(_csv(rows[:1]))))                  # tanpa padanan → galat jelas
    assert "SKU 'DA-9001-PHT-XL' tidak ada" in b["preview_invalid"][0]["errors"][0]


def test_impor_po_berjalan_lewat_jalur_resmi_dan_idempoten(env):
    db, dt = env["db"], env["dt"]

    async def admin(_r):
        return dict(ADMIN)
    import routes.data_transfer as dtm
    dtm_require = dtm.require_auth
    try:
        dtm.require_auth = admin
        prev = run(dt.import_table("po_berjalan", FakeRequest(), Up("po.csv", _csv(GOOD)), "dry_run", None))
        assert prev["invalid"] == 0 and prev["would_insert"] == 4 and prev["would_skip"] == 1
        assert len(prev["groups"]) == 3 and "_groups" not in prev
        t = prev["totals"]
        assert t["po_baru"] == 3 and t["pcs_sisa"] == 40 + 30 + 15 + 40
        assert t["hutang_cmt_terjadwal"] == 40 * 12000 + 30 * 10000 + 15 * 12000 + 40 * 8500
        assert t["piutang_maklon_terjadwal"] == 40 * 15000 and t["nilai_bahan_di_cmt"] == (40 + 30 + 15) * 5000
        assert db.production_pos.docs == []                               # pratinjau tidak menulis
        res = run(dt.import_table("po_berjalan", FakeRequest(), Up("po.csv", _csv(GOOD)), "commit", None))
    finally:
        dtm.require_auth = dtm_require
    assert res["committed"] and res["inserted"] == 3 and res["failed"] == []
    pos = {p["opening_import"]["key"]: p for p in db.production_pos.docs}
    # PO dibuat Dikonfirmasi; job otomatis (11 Nov 2026) lalu menaikkannya ke Produksi — sama dengan POST /production-jobs
    assert len(pos) == 3 and all(p["status"] == "In Production" for p in pos.values())
    assert all(h["status"] == "Confirmed" for p in pos.values() for h in (p.get("status_history") or [])[:1])
    a = pos["CUT-01|vp1"]
    items = [i for i in db.po_items.docs if i["po_id"] == a["id"]]
    assert sorted((i["sku"], i["qty"], i["cmt_price_snapshot"], i["opening_qty_cut"], i["opening_qty_received"])
                  for i in items) == [("DA-9351-RDE-M", 30, 10000.0, 30, 0), ("DA-9507-KTB-ALLSIZE", 40, 12000.0, 100, 60)]
    assert a["opening_import"]["qty_received_before"] == 60 and a["vendor_id"] == "vp1"
    ships = db.vendor_shipments.docs
    assert len(ships) == 3 and all(s["opening"] and s["status"] == "Received" and s["inspection_status"] == "Inspected"
                                   for s in ships)
    si = [x for x in db.vendor_shipment_items.docs if x["po_id"] == a["id"]]
    assert sorted(x["qty_sent"] for x in si) == [30, 40] and all(x["opening"] for x in si)
    # TANPA potong stok, tanpa MI, tanpa jurnal, tanpa ledakan BOM ulang
    assert env["calls"] == {"explode": 0, "mi": 0}
    assert db.rahaza_material_issues.docs == [] and db.rahaza_material_movements.docs == []
    assert env["jes"] == [] and db.po_accessories.docs == [] and db.dewi_maklon_bom.docs == []
    # maklon: piutang klien & hutang CMT TERJADWAL hanya untuk sisa di CMT
    mk = next(p for p in pos.values() if p["business_type"] == "maklon")
    assert mk["buyer_id"] == "cl1" and mk["customer_name"] == "PT Klien Satu"
    ar = next(x for x in db.rahaza_ar_invoices.docs if x.get("linked_maklon_po_id") == mk["id"])
    assert ar["schedule_mode"] == "v2" and ar["scheduled_total"] == 40 * 15000 and ar["billed_total"] == 0
    ap = [s for s in db.dewi_cmt_ap_schedules.docs if s["po_id"] == mk["id"] and s["status"] != "cancelled"]
    assert len(ap) == 1 and ap[0]["vendor_id"] == "vp2" and ap[0]["scheduled_amount"] == 40 * 8500
    # idempoten: berkas yang sama dilewati seluruhnya
    again = run(pbi.analyse(db, _rows(_csv(GOOD))))
    assert again["would_insert"] == 0 and again["would_skip"] == 5 and again["_groups"] == []
    assert run(pbi.commit(db, again, ADMIN))["created"] == []
    assert len(db.production_pos.docs) == 3
    # 11 Nov 2026 (owner): PO internal ber-Tujuan bawaan form, setiap kiriman awal langsung punya job
    assert sorted(p["customer_name"] for p in pos.values()) == ["Gudang FG Sendiri", "Gudang FG Sendiri", "PT Klien Satu"]
    jobs = db.production_jobs.docs
    assert len(jobs) == 3 and sorted(j["vendor_shipment_id"] for j in jobs) == sorted(s["id"] for s in ships)
    assert {c["job_number"] for c in res["created"]} == {j["job_number"] for j in jobs}
    ja = next(j for j in jobs if j["po_id"] == a["id"])
    assert ja["business_type"] == "internal" and ja["customer_name"] == "Gudang FG Sendiri" and ja["vendor_id"] == "vp1"
    assert sorted((i["sku"], i["shipment_qty"], i["available_qty"]) for i in db.production_job_items.docs
                  if i["job_id"] == ja["id"]) == [("DA-9351-RDE-M", 30, 30), ("DA-9507-KTB-ALLSIZE", 40, 40)]
    assert all(p["status"] == "In Production" for p in pos.values())          # sama dengan POST /production-jobs
    assert all(not s.get("job_lock") for s in ships)                           # kunci dilepas


def test_hutang_cmt_lahir_lewat_alur_biasa_hanya_untuk_sisa(env):
    """Penerimaan FG dari CMT sesudah cutoff → tagihan CMT = qty lolos × upah; qty yang sudah diterima
    sebelum cutoff (60 pcs) tidak pernah ditagih lagi."""
    import routes.production_maklon_bridge as bridge
    db = env["db"]
    a = run(pbi.analyse(db, _rows(_csv(GOOD[:1]))))
    run(pbi.commit(db, a, ADMIN))
    po = db.production_pos.docs[0]
    item = db.po_items.docs[0]
    db.cmt_receipts.docs.append({"id": "rc1", "receipt_code": "CMT-RCV-1", "po_id": po["id"],
                                 "po_number": po["po_number"], "cmt_vendor_id": "vp1", "cmt_name": "Penjahit Satu",
                                 "total_shipped_by_cmt": 40})
    db.cmt_receipt_lines.docs.append({"id": "ln1", "receipt_id": "rc1", "po_item_id": item["id"],
                                      "sku_code": item["sku"], "qty_actual": 40, "reject_qty": 0})
    out = run(bridge.mature_ap_from_cmt_receipt(db, "rc1", ADMIN))
    assert out["ok"] and out["amount"] == 40 * 12000 and out["total_pcs"] == 40


def test_kelompok_bermasalah_dan_barang_ganda(env):
    db = env["db"]
    rows = [GOOD[0], GOOD[0][:], ["2026-10-22", "CUT-01", "DA-9351-RDE-M", "", "", "", "CMT-A", "5", "0", "5",
                                  "1000", "", "", "internal"]]
    a = run(pbi.analyse(db, _rows(_csv(rows))))
    msgs = " ".join(" ".join(r["errors"]) for r in a["preview_invalid"])
    assert "gabungkan barisnya" in msgs and "harus satu tanggal" in msgs
    assert a["_groups"] == [] and a["would_insert"] == 0


def test_gagal_di_tengah_dibatalkan_lewat_jalur_hapus_po(env, monkeypatch):
    import routes.vendor_shipment as vs
    db = env["db"]

    async def boom(*_a, **_k):
        raise HTTPException(400, "surat jalan ditolak")
    monkeypatch.setattr(vs, "create_vendor_shipment_internal", boom)
    a = run(pbi.analyse(db, _rows(_csv(GOOD[:1]))))
    res = run(pbi.commit(db, a, ADMIN))
    assert res["created"] == [] and "surat jalan ditolak" in res["failed"][0]["error"]
    assert db.production_pos.docs == [] and db.po_items.docs == []


def test_hak_akses_dan_registri(env):
    dt = env["dt"]

    async def produksi(_r):
        return {"id": "p1", "name": "Staf", "role": "admin_produksi"}

    async def admin(_r):
        return dict(ADMIN)
    orig = dt.require_auth
    try:
        dt.require_auth = produksi
        with pytest.raises(HTTPException) as e:
            run(dt.import_table("po_berjalan", FakeRequest(), Up("po.csv", _csv(GOOD)), "dry_run", None))
        assert e.value.status_code == 403
        assert all(t["key"] != "po_berjalan" for t in run(dt.get_registry(FakeRequest()))["tables"])
        dt.require_auth = admin
        ent = next(t for t in run(dt.get_registry(FakeRequest()))["tables"] if t["key"] == "po_berjalan")
        assert ent["importable"] and ent["exportable"] is False and ent["accepts_alias"]
        assert ent["existing_rows"] == "skip"
        assert next(t for t in run(dt.get_registry(FakeRequest()))["tables"]
                    if t["key"] == "materials")["existing_rows"] == "update"   # entri lama tidak berubah
        with pytest.raises(HTTPException) as e:
            run(dt.export_table("po_berjalan", FakeRequest(), "xlsx"))
        assert e.value.status_code == 403
        tpl = run(dt.template_table("po_berjalan", FakeRequest(), "csv"))
        assert tpl.media_type == "text/csv"
    finally:
        dt.require_auth = orig
    assert [c["name"] for c in pbi.template_columns()] == HEADER


def test_impor_po_lama_dihentikan(monkeypatch):
    import routes.operations_import as oi

    async def admin(_r):
        return dict(ADMIN)
    monkeypatch.setattr(oi, "require_auth", admin)
    monkeypatch.setattr(oi, "get_db", lambda: _DB())
    with pytest.raises(HTTPException) as e:
        run(oi.import_data(FakeRequest({"type": "production-pos", "data": [{"po_number": "X"}]})))
    assert e.value.status_code == 410 and "po_berjalan" in str(e.value.detail)


def test_angka_dan_tanggal():
    assert pbi.angka("12.000") == (12000.0, None) and pbi.angka("Rp 8.500") == (8500.0, None)
    assert pbi.angka("1,5") == (1.5, None) and pbi.angka(15000) == (15000.0, None)
    assert pbi.angka("abc")[1] and pbi.angka("") == (None, None)
    assert pbi.tanggal("01/11/2026") == ("2026-11-01", None)
    assert pbi.tanggal("2026-11-01 00:00:00") == ("2026-11-01", None)
    assert pbi.normalize_row({"Sisa Potongan (pcs)": 3, "Penjahit": "A", "Nama Produk": "X"}) == {
        "sisa_di_cmt": 3, "cmt": "A", "model": "X"}


# ══════════════════════════════════════════════════════════════════════════════
# 11 Nov 2026 (owner) · impor PO berjalan lanjutan: tenggat, job otomatis, batal bila job gagal
# ══════════════════════════════════════════════════════════════════════════════
def test_tenggat_produksi_dan_kirim_masuk_po_dan_job(env):
    db = env["db"]
    rows = [GOOD[0] + ["2026-11-30", "2026-12-05"], GOOD[1] + ["", ""]]       # tenggat cukup di satu baris kelompok
    a = run(pbi.analyse(db, _rows(_csv(rows))))
    assert a["invalid"] == 0, a["preview_invalid"]
    res = run(pbi.commit(db, a, ADMIN))
    assert len(res["created"]) == 1 and res["created"][0]["job_number"]
    po = db.production_pos.docs[0]
    assert str(po["deadline"])[:10] == "2026-11-30" and str(po["delivery_deadline"])[:10] == "2026-12-05"
    job = db.production_jobs.docs[0]
    assert str(job["deadline"])[:10] == "2026-11-30" and str(job["delivery_deadline"])[:10] == "2026-12-05"


def test_tenggat_bertentangan_atau_kirim_sebelum_produksi_ditolak(env):
    db = env["db"]
    rows = [GOOD[0] + ["2026-11-30", ""], GOOD[1] + ["2026-12-01", ""],          # satu PO, dua tenggat
            ["2026-10-20", "CUT-09", "DA-9507-KTB-ALLSIZE", "", "", "", "CMT-A", "10", "0", "10", "1000", "", "",
             "internal", "2026-12-10", "2026-12-01"]]                               # kirim sebelum produksi
    a = run(pbi.analyse(db, _rows(_csv(rows))))
    msgs = " ".join(" ".join(r["errors"]) for r in a["preview_invalid"])
    assert "harus satu tenggat produksi" in msgs
    assert "Tenggat kirim (2026-12-01) lebih awal dari tenggat produksi (2026-12-10)" in msgs
    assert a["_groups"] == []


def test_job_gagal_membatalkan_po_dan_kiriman(env, monkeypatch):
    import routes.production_execution as pe
    db = env["db"]

    async def boom(*_a, **_k):
        raise HTTPException(409, "job sedang dibuat pengguna lain")
    monkeypatch.setattr(pe, "create_job_for_shipment_locked", boom)
    a = run(pbi.analyse(db, _rows(_csv(GOOD[:1]))))
    res = run(pbi.commit(db, a, ADMIN))
    assert res["created"] == [] and "sedang dibuat" in res["failed"][0]["error"]
    assert db.production_pos.docs == [] and db.vendor_shipments.docs == [] and db.production_jobs.docs == []


def test_job_dari_kiriman_tidak_dibuat_dua_kali(env):
    import routes.production_execution as pe
    db = env["db"]
    a = run(pbi.analyse(db, _rows(_csv(GOOD[:1]))))
    run(pbi.commit(db, a, ADMIN))
    ship = db.vendor_shipments.docs[0]
    with pytest.raises(HTTPException) as e:                                       # jalur yang sama dengan POST /production-jobs
        run(pe.create_job_for_shipment_locked(db, ship["id"], "vp1", ADMIN))
    assert e.value.status_code == 400 and "sudah ada" in str(e.value.detail)
    assert len(db.production_jobs.docs) == 1 and not db.vendor_shipments.docs[0].get("job_lock")
