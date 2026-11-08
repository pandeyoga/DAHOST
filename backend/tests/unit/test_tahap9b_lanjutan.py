"""Uji unit HERMETIK Tahap 9 lanjutan — keputusan owner 7 Nov (malam):

  1. Ongkos permak DITANGGUNG DA dan masuk HPP PO: permak PO internal selesai → Dr WIP 1-1403 / Cr hutang biaya
     permak (profil `production_permak_cost`); PO maklon & ongkos 0 dilewati; sisa WIP PO menelusuri jurnalnya.
  2. Pengeluaran Material (Portal Gudang) khusus non-CMT: pembuatan MI dari job produksi tidak dibuka lagi.
  3. Isian kemasan gudang → master satuan aksesoris lewat aturan `core.uom.apply_payload` (satuan dasar & stok
     tidak pernah diubah).
Data uji fiktif.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import pytest  # noqa: E402

from p3_fakes import FakeDB  # noqa: E402
from core import po_wip  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

U = {"id": "u1", "name": "Uji", "role": "admin"}
DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def posting(monkeypatch):
    jes = []

    async def mapping(db, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2)
        jes.append({"source_module": mod, "source_ref": ref, "memo": memo, "lines": lines})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes)}"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    return jes


def _db():
    db = FakeDB()
    db.production_pos.docs = [
        {"id": "po-int", "po_number": "PO-INT-UJI-1", "business_type": "internal"},
        {"id": "po-mkl", "po_number": "PO-MKL-UJI-1", "business_type": "maklon"},
    ]
    return db


# ═══════════════════════════ 1. ongkos permak → WIP PO ═══════════════════════════
def test_profil_permak_bawaan_wip_dan_hutang_biaya():
    m = DEFAULT_MAP["production_permak_cost"]
    assert m == {"debit_wip": "1-1403", "credit_accrued": "2-1600"}
    assert pp.ROLE_FAMILY["credit_accrued"] == "liability" and pp.ROLE_FAMILY["debit_wip"] == "asset"


def test_permak_po_internal_berongkos_didebit_ke_wip(posting):
    db = _db()
    pm = {"id": "pm1", "po_id": "po-int", "total_cost": 50000, "permak_number": "PMK/UJI/1",
          "vendor_permak_name": "Workshop DA sendiri"}
    db.dewi_cmt_permak.docs = [dict(pm)]
    res = run(rp.post_permak_cost(db, pm, U))
    assert res["ok"] and len(posting) == 1
    je = posting[0]
    assert je["source_module"] == "permak_cost" and je["source_ref"] == "permak:pm1"
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("1-1403", 50000, 0), ("2-1600", 0, 50000)]
    assert db.dewi_cmt_permak.docs[0]["gl_je_id"] == "je-1"


def test_permak_maklon_dan_tanpa_ongkos_dilewati(posting):
    db = _db()
    assert run(rp.post_permak_cost(db, {"id": "a", "po_id": "po-mkl", "total_cost": 9000}, U))["skipped"] == "po_maklon"
    assert run(rp.post_permak_cost(db, {"id": "b", "po_id": "po-int", "total_cost": 0}, U))["skipped"] == "tanpa_ongkos"
    assert posting == []


def test_permak_sudah_berjurnal_tidak_dobel(monkeypatch, posting):
    db = _db()

    async def existing(*a, **k):
        return {"id": "je-lama", "je_number": "JE-LAMA"}
    monkeypatch.setattr(rp, "_find_existing_je", existing)
    res = run(rp.post_permak_cost(db, {"id": "pm1", "po_id": "po-int", "total_cost": 1000}, U))
    assert res["already_posted"] and posting == []


def test_sisa_wip_po_menelusuri_jurnal_permak():
    db = _db()
    db.dewi_cmt_permak.docs = [{"id": "pm1", "po_id": "po-int", "gl_je_id": "je-permak"},
                               {"id": "pm2", "po_id": "po-int", "gl_je_id": None}]
    src = run(po_wip._je_sources(db, "po-int"))
    assert src.get("je-permak") == "permak"
    assert po_wip.SRC_LABEL["permak"] == "Ongkos permak"


def test_status_permak_selesai_memanggil_jurnal():
    src = Path(BACKEND, "routes", "dewi_cmt_permak.py").read_text(encoding="utf-8")
    i = src.index("async def change_status")
    body = src[i:src.index("@router.delete", i)]
    assert "post_permak_cost" in body and "if new in TERMINAL" in body


# ═══════════════════════════ 2. Pengeluaran Material = non-CMT ═══════════════════════════
def test_layar_pengeluaran_material_khusus_non_cmt():
    src = Path(ROOT, "frontend", "src", "components", "erp", "RahazaMaterialIssueModule.jsx").read_text(encoding="utf-8")
    assert "mi-create-tab-job" not in src and "setCreateTab" not in src
    assert "useState('manual')" in src and "mi-create-non-cmt-note" in src
    assert "di luar CMT" in src


# ═══════════════════════════ 3. isian kemasan gudang ═══════════════════════════
def _mig():
    p = Path(BACKEND, "scripts", "migrations", "2026_11_07_isi_kemasan_aksesoris.py")
    spec = importlib.util.spec_from_file_location("isi_kemasan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MAT_GROSS = {"code": "K-UJI", "unit": "pcs", "base_uom": "pcs",
             "uoms": [{"code": "pcs", "factor": 1, "is_base": True}, {"code": "gross", "factor": 1440}]}


def test_angka_isian_gaya_indonesia():
    m = _mig()
    assert m._num("1.440") == 1440 and m._num("2,5") == 2.5 and m._num(144) == 144 and m._num("") is None


def test_isi_gross_dikoreksi_dan_jadi_satuan_serah():
    m = _mig()
    p = m.plan_entry(MAT_GROSS, {"code": "K-UJI", "pack": "gross", "qty": "1.440"})
    assert p["status"] == "akan_diubah"           # isi sama, tetapi belum jadi satuan pakai
    assert p["payload"]["issue_uom"] == "gross" and p["payload"]["base_uom"] == "pcs"
    p2 = m.plan_entry(MAT_GROSS, {"code": "K-UJI", "pack": "gross", "qty": "144"})
    gross = next(r for r in p2["payload"]["uoms"] if r["code"] == "gross")
    assert gross["factor"] == 144 and gross.get("is_issue_default")


def test_kemasan_baru_ditambah_tanpa_mengubah_dasar():
    m = _mig()
    mat = {"code": "R-UJI", "unit": "cm", "base_uom": "cm", "uoms": [{"code": "cm", "factor": 1, "is_base": True}]}
    p = m.plan_entry(mat, {"code": "R-UJI", "pack": "roll", "qty": "2240"})
    assert p["status"] == "akan_diubah"
    codes = {r["code"]: r["factor"] for r in p["payload"]["uoms"]}
    assert codes == {"cm": 1, "roll": 2240} and p["payload"]["base_uom"] == "cm"
    assert p["payload"]["issue_uom"] == "roll" and p["payload"]["unit"] == "cm"
    done = {**mat, **p["payload"]}
    assert m.plan_entry(done, {"code": "R-UJI", "pack": "roll", "qty": 2240})["status"] == "sudah_sesuai"


def test_baris_bermasalah_dilaporkan_bukan_ditebak():
    m = _mig()
    assert m.plan_entry(None, {"code": "X", "pack": "roll", "qty": "5"})["status"] == "kode_tidak_ada"
    assert m.plan_entry(MAT_GROSS, {"code": "K-UJI", "pack": "", "qty": ""})["status"] == "kosong"
    assert m.plan_entry(MAT_GROSS, {"code": "K-UJI", "pack": "roll", "qty": "0"})["status"] == "isian_tidak_lengkap"
    assert m.plan_entry(MAT_GROSS, {"code": "K-UJI", "pack": "pcs", "qty": "10"})["status"] == "sama_dengan_dasar"
    full = {"code": "F", "unit": "pcs", "base_uom": "pcs", "uoms": [
        {"code": "pcs", "factor": 1, "is_base": True}, {"code": "bks", "factor": 12}, {"code": "ktn", "factor": 144}]}
    assert m.plan_entry(full, {"code": "F", "pack": "roll", "qty": "50"})["status"] == "tidak_valid"


# ═══════════════════════════ 4. cutoff cakupan "operasional" (keputusan owner 7 Nov malam) ═══════════════════════════
# Kosongkan HANYA produksi/maklon/CMT, gudang/stok, pembelian, keuangan (+ pencairan marketplace yang berjurnal);
# Marketing, SDM, aset, RnD, dan SEMUA log dipertahankan; nomor dokumen dilanjutkan.
import subprocess  # noqa: E402

from core import collection_registry as cr  # noqa: E402
from core import cutoff_reset  # noqa: E402


def test_cakupan_operasional_daftar_eksplisit():
    op = cutoff_reset.SCOPE_OPERASIONAL
    hapus = ("production_pos", "po_items", "cmt_receipts", "cmt_receipt_lines", "vendor_shipments", "cutting_orders",
             "rahaza_material_stock", "rahaza_stock_ledger", "fg_cost_layers", "rahaza_fg_movements",
             "rahaza_purchase_orders", "warehouse_receiving", "rahaza_journal_entries", "rahaza_journal_lines",
             "rahaza_ar_invoices", "dewi_cmt_payments", "rahaza_cash_movements", "marketing_settlements",
             "marketing_platform_withdrawals")
    tetap = ("marketing_tasks", "marketing_content_calendar", "marketing_live_sessions", "marketing_reviews",
             "marketing_samples", "marketing_complaints", "marketing_orders", "rahaza_attendance_events",
             "rahaza_leave_requests", "rahaza_payroll_runs", "dewi_kasbon_requests", "dewi_asset_loans",
             "notifications", "activity_logs", "dewi_scheduler_runs")
    for n in hapus:
        assert cutoff_reset.deleted_in_scope(n, cr.kind_of(n), op), n
    for n in tetap:
        assert not cutoff_reset.deleted_in_scope(n, cr.kind_of(n), op), n
    # cakupan semua = perilaku T5 semula; master/konfigurasi tidak pernah dihapus
    assert cutoff_reset.deleted_in_scope("marketing_tasks", "transaksi", cutoff_reset.SCOPE_SEMUA)
    assert cutoff_reset.deleted_in_scope("notifications", "log", cutoff_reset.SCOPE_SEMUA)
    assert not cutoff_reset.deleted_in_scope("rahaza_materials", "master", op)
    assert not cutoff_reset.deleted_in_scope("roles", "konfigurasi", cutoff_reset.SCOPE_SEMUA)
    # setiap nama di daftar eksplisit memang koleksi transaksi (bukan master yang salah masuk)
    for n in cutoff_reset.OPERASIONAL_NAMES:
        assert cr.kind_of(n) in (cr.KIND_TRANSAKSI, None), n


def test_cakupan_operasional_hapus_operasional_pertahankan_marketing_sdm_log():
    from test_tahap4_cutoff import _cutoff_db
    db = _cutoff_db()
    db.marketing_tasks.docs = [{"id": "t1"}, {"id": "t2"}]
    db.rahaza_attendance_events.docs = [{"id": "at1"}]
    db.marketing_settlements.docs = [{"id": "st1"}]
    db.cmt_receipts.docs = [{"id": "rc1"}]
    plan = run(cutoff_reset.build_plan(db, reset_nomor=True, scope=cutoff_reset.SCOPE_OPERASIONAL))
    assert plan["scope"] == "operasional" and plan["reset_nomor"] is False and plan["counters"]["reset"] == []
    kept = {r["name"] for r in plan["classes"]["dipertahankan"]}
    assert {"marketing_tasks", "rahaza_attendance_events", "notifications", "activity_logs"} <= kept
    assert plan["classes"]["log"] == []
    res = run(cutoff_reset.apply_plan(db, plan))
    for n in ("production_pos", "po_items", "rahaza_material_stock", "rahaza_journal_entries", "fg_cost_layers",
              "marketing_settlements", "cmt_receipts"):
        assert db[n].docs == [], n
    assert len(db.marketing_tasks.docs) == 2 and len(db.rahaza_attendance_events.docs) == 1
    assert len(db.notifications.docs) == 2 and len(db.activity_logs.docs) == 1
    assert res["deleted_total"] == plan["totals"]["hapus"]
    assert len(db.counters.docs) == 4                                   # nomor dokumen dilanjutkan
    assert db.rahaza_leave_balances.docs[0]["used"] == 3               # SDM: cuti terpakai TIDAK direset
    assert db.rahaza_cash_accounts.docs[0]["opening_balance"] == 0.0   # keuangan: saldo awal kas direset
    assert db.marketing_catalog_items.docs[0]["stock_quantity"] == 0   # stok dikosongkan → cache katalog nol
    assert "hpp_fifo_avg" not in db.rahaza_materials.docs[1]


def test_cakupan_tidak_dikenal_ditolak():
    from test_tahap4_cutoff import _cutoff_db
    with pytest.raises(cutoff_reset.CutoffRefused):
        run(cutoff_reset.build_plan(_cutoff_db(), scope="sebagian"))


def test_skrip_cakupan_operasional_menolak_kombinasi_salah():
    script = Path(ROOT, "scripts", "reset_for_golive.py")
    r1 = subprocess.run([sys.executable, str(script), "--cakupan", "operasional"], capture_output=True, text=True)
    assert r1.returncode == 2 and "--cakupan hanya berlaku" in r1.stderr
    r2 = subprocess.run([sys.executable, str(script), "--transaksi-saja", "--cakupan", "operasional", "--reset-nomor"],
                        capture_output=True, text=True)
    assert r2.returncode == 2 and "tidak berlaku untuk --cakupan operasional" in r2.stderr
    src = script.read_text(encoding="utf-8")
    assert "scope=scope" in src and src.count("build_plan(db, reset_nomor=reset_nomor, scope=scope)") == 2
