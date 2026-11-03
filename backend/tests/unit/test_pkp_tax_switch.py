"""Saklar status pajak PKP / non-PKP (keputusan owner 2026-11-03) — SSOT `core.tax_status`.

Non-PKP (bawaan, K11): dokumen penjualan tidak boleh memungut PPN; PPN supplier = bagian harga beli.
PKP: PPN = 12% × DPP nilai lain 11/12 (kode 04); PPN masukan dikreditkan (1-1501).
"""
import asyncio
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # pragma: no cover - CI memasang openpyxl; stub hanya untuk lingkungan tanpa paket itu
    import openpyxl  # noqa: F401
except ImportError:  # pragma: no cover
    _op, _st, _ut = (types.ModuleType(n) for n in ("openpyxl", "openpyxl.styles", "openpyxl.utils"))
    for _n in ("Font", "PatternFill", "Alignment", "Border", "Side"):
        setattr(_st, _n, object)
    _ut.get_column_letter = lambda i: "A"
    _op.styles, _op.utils, _op.Workbook = _st, _ut, object
    sys.modules.update({"openpyxl": _op, "openpyxl.styles": _st, "openpyxl.utils": _ut})

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
import core.tax_status as ts  # noqa: E402
import routes.admin as adm  # noqa: E402
import routes.dewi_maklon_billing as mb  # noqa: E402
import routes.dewi_system_config as cfg  # noqa: E402
import routes.rahaza_finance as rf  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.sales_direct as sd  # noqa: E402

USER = {"id": "u1", "name": "Uji", "role": "superadmin"}
NON_PKP = ts.normalize_profile({"pkp": False})
PKP = ts.normalize_profile({"pkp": True, "pkp_since": "2026-11-01"})


def run(c):
    return asyncio.run(c)


def _db(pkp: bool):
    db = FakeDB()
    db.company_settings.docs = [{"id": "cs", "type": "general", "npwp": "01.234.567.8-901.000" if pkp else "",
                                 "tax_profile": {"pkp": pkp, "pkp_since": "2026-11-01" if pkp else ""}}]
    return db


# ── SSOT ─────────────────────────────────────────────────────────────────────
def test_non_pkp_tidak_ada_ppn_dan_permintaan_ppn_ditolak():
    assert ts.output_tax(NON_PKP, 1_000_000)["tax_amount"] == 0
    assert ts.wants_output_tax(NON_PKP, 0, None) is False
    assert ts.wants_output_tax(NON_PKP, None, None) is False
    for pct, kena in ((11, None), (12, None), (None, True)):
        with pytest.raises(HTTPException) as e:
            ts.wants_output_tax(NON_PKP, pct, kena)
        assert e.value.status_code == 400 and "NON-PKP" in e.value.detail


def test_pkp_dpp_nilai_lain_11_per_12_kode_04():
    t = ts.output_tax(PKP, 1_000_000)
    assert t["dpp_nilai_lain"] == 916_666.67 and t["tax_amount"] == 110_000
    assert t["ppn_rate"] == 12.0 and t["kode_transaksi"] == "04" and t["tax_pct"] == 11.0 and t["kena_ppn"] is True
    assert ts.output_tax(PKP, 1_000_000, apply=False)["tax_amount"] == 0
    assert ts.wants_output_tax(PKP, None, None) is True        # bawaan PKP = kena PPN
    assert ts.wants_output_tax(PKP, 0, None) is False          # tax_pct 0 = tidak kena
    assert ts.wants_output_tax(PKP, 11, False) is False        # penanda eksplisit menang


def test_hitung_ulang_dokumen_lama_tetap_persen_lama():
    assert ts.tax_for_stored({"tax_pct": 11}, 1_000_000, round_to=2) == 110_000.0     # dokumen lama
    assert ts.tax_for_stored({"tax_pct": 11.0, "ppn_rate": 12.0, "kena_ppn": True}, 999_999) == 110_000
    assert ts.tax_for_stored({"tax_pct": 0, "ppn_rate": 12.0, "kena_ppn": False}, 999_999) == 0


def test_aktifkan_pkp_wajib_npwp_dan_tanggal():
    with pytest.raises(HTTPException):
        ts.validate_profile_update({"pkp": True, "pkp_since": "2026-11-01"}, "")
    with pytest.raises(HTTPException):
        ts.validate_profile_update({"pkp": True, "pkp_since": ""}, "01.2")
    assert ts.validate_profile_update({"pkp": False, "pkp_since": "2026-01-01"}, "") == {"pkp": False, "pkp_since": ""}


# ── Pengaturan Perusahaan ────────────────────────────────────────────────────
def _admin(monkeypatch, db):
    async def _auth(*_a, **_k):
        return dict(USER)
    monkeypatch.setattr(adm, "get_db", lambda: db)
    monkeypatch.setattr(adm, "require_auth", _auth)
    monkeypatch.setattr(adm, "check_role", lambda u, roles: True)


def test_simpan_pengaturan_tidak_menghapus_npwp_dan_mencatat_riwayat_pkp(monkeypatch):
    db = _db(False)
    db.company_settings.docs[0].update({"npwp": "01.234.567.8-901.000", "company_tagline": "Rapi"})
    _admin(monkeypatch, db)
    run(adm.save_company_settings(FakeRequest({"company_name": "CV. Dewi Aditya"})))   # form lama tanpa npwp
    doc = db.company_settings.docs[0]
    assert doc["npwp"] == "01.234.567.8-901.000" and doc["company_tagline"] == "Rapi"   # dulu jadi ''
    run(adm.save_company_settings(FakeRequest({"tax_profile": {"pkp": True, "pkp_since": "2026-11-01"}})))
    doc = db.company_settings.docs[0]
    assert doc["tax_profile"] == {"pkp": True, "pkp_since": "2026-11-01"}
    assert doc["tax_profile_history"][-1]["to_pkp"] is True and doc["tax_profile_history"][-1]["from_pkp"] is False
    prof = run(adm.get_tax_profile_endpoint(FakeRequest()))
    assert prof["pkp"] is True and prof["effective_pct"] == 11.0 and prof["npwp"]


def test_pkp_tanpa_npwp_ditolak(monkeypatch):
    db = _db(False)
    _admin(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(adm.save_company_settings(FakeRequest({"tax_profile": {"pkp": True, "pkp_since": "2026-11-01"}})))
    assert "NPWP" in e.value.detail


# ── AR manual ────────────────────────────────────────────────────────────────
def _ar_env(monkeypatch, db):
    async def _auth(*_a, **_k):
        return dict(USER)

    async def _num(*_a, **_k):
        return "AR-UJI-0001"

    async def _ok(*_a, **_k):
        return None
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "_require_fin", _auth)
    monkeypatch.setattr(rf, "_gen_number", _num)
    monkeypatch.setattr(rf, "_reject_marketplace_ar", _ok)
    db.rahaza_customers.docs = [{"id": "c1", "name": "Pelanggan Uji"}]


AR_BODY = {"customer_id": "c1", "items": [{"description": "Gamis", "qty": 10, "price": 100_000}], "discount_amount": 0}


def test_ar_non_pkp_menolak_ppn_dan_tanpa_ppn_lolos(monkeypatch):
    db = _db(False)
    _ar_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(rf.create_ar(FakeRequest({**AR_BODY, "tax_pct": 11})))
    assert e.value.status_code == 400
    inv = run(rf.create_ar(FakeRequest({**AR_BODY, "tax_pct": 0})))
    assert inv["tax_amount"] == 0 and inv["total"] == 1_000_000 and inv["kena_ppn"] is False


def test_ar_pkp_ppn_dpp_11_per_12_dan_nomor_faktur(monkeypatch):
    db = _db(True)
    _ar_env(monkeypatch, db)
    inv = run(rf.create_ar(FakeRequest({**AR_BODY, "kena_ppn": True, "faktur_number": "04002600000001", "faktur_date": "2026-11-03"})))
    assert inv["tax_amount"] == 110_000 and inv["total"] == 1_110_000
    assert inv["ppn_rate"] == 12.0 and inv["kode_transaksi"] == "04" and inv["faktur_number"] == "04002600000001"


# ── Penjualan langsung ───────────────────────────────────────────────────────
def test_penjualan_langsung_ikut_status_pajak():
    items = [{"amount": 500_000}, {"amount": 500_000}]
    sub, t, total = sd._calc(items, 100_000, NON_PKP, False)
    assert (sub, t["tax_amount"], total) == (1_000_000, 0, 900_000)
    sub, t, total = sd._calc(items, 100_000, PKP, True)
    assert t["tax_amount"] == 99_000 and total == 999_000          # 900.000 × 11/12 × 12%


# ── Maklon: konfigurasi 11% pensiun, ubah PPN lewat saklar ───────────────────
def test_konfigurasi_ppn_maklon_pensiun_dan_disembunyikan(monkeypatch):
    db = FakeDB()
    db.dewi_system_config.docs = [{"key": "maklon_tax_pct", "value": 11.0, "category": "maklon"},
                                  {"key": "maklon_invoice_prefix", "value": "INV-MKL", "category": "maklon"}]
    monkeypatch.setattr(cfg, "get_db", lambda: db)
    out = run(cfg.list_configs(category=None, user=dict(USER)))
    keys = {o["key"] for o in out}
    assert "maklon_tax_pct" not in keys and "maklon_invoice_prefix" in keys
    assert "maklon_tax_pct" not in {c["key"] for c in cfg.DEFAULT_CONFIGS}
    src = Path(mb.__file__).read_text(encoding="utf-8")
    assert "get_config_value(db, 'maklon_tax_pct'" not in src


def test_ubah_invoice_maklon_non_pkp_tolak_ppn(monkeypatch):
    db = _db(False)
    db.dewi_maklon_invoices.docs = [{"id": "m1", "status": "issued", "lines": [{"line_total": 1_000_000}],
                                     "tax_pct": 0, "discount_amount": 0}]
    monkeypatch.setattr(mb, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(mb.update_invoice("m1", mb.InvoiceUpdateIn(tax_pct=11), user=dict(USER)))
    assert e.value.status_code == 400


# ── Jurnal tagihan supplier ──────────────────────────────────────────────────
MAP = {"credit_ap": "2-1100", "debit_expense_default": "6-2900", "debit_grni": "2-1150",
       "debit_tax_input": "1-1501", "debit_price_variance": "5-1900"}


def _post(monkeypatch, db, inv):
    calls = []

    async def fake_create(db_, je_date, memo, source_module, source_ref, lines, user, **k):
        calls.append(lines)
        return {"ok": True, "je_id": "je1", "je_number": "JE-1"}

    async def fake_map(db_, ev):
        return dict(MAP)

    async def _none(*_a, **_k):
        return None

    async def _save(*_a, **_k):
        return None
    monkeypatch.setattr(rp, "_create_posted_je", fake_create)
    monkeypatch.setattr(rp, "get_mapping", fake_map)
    monkeypatch.setattr(rp, "_find_existing_je", _none)
    monkeypatch.setattr(rp, "_save_source_posting_result", _save)
    db.rahaza_ap_invoices.docs = [dict(inv)]
    res = run(rp.post_ap_invoice(db, inv, dict(USER)))
    assert res["ok"], res
    lines = calls[0]
    assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2)
    dr = {}
    for ln in lines:
        if ln["debit"]:
            dr[ln["account_code"]] = round(dr.get(ln["account_code"], 0) + ln["debit"], 2)
    return dr


AP_GR = {"id": "ap1", "invoice_number": "AP-1", "source": "gr", "gr_ids": ["g1"], "gl_debit_code": "2-1150",
         "subtotal": 1_000_000, "tax_amount": 110_000, "total": 1_110_000, "gl_price_variance": 0}


def test_ap_non_pkp_ppn_supplier_jadi_harga_beli_bukan_ppn_masukan(monkeypatch):
    dr = _post(monkeypatch, _db(False), {**AP_GR, "input_tax_treatment": "kapitalisasi"})
    assert "1-1501" not in dr and dr["5-1900"] == 110_000 and dr["2-1150"] == 1_000_000


def test_ap_biaya_non_pkp_ppn_masuk_ke_akun_beban(monkeypatch):
    inv = {"id": "ap2", "invoice_number": "AP-2", "subtotal": 500_000, "tax_amount": 55_000, "total": 555_000,
           "input_tax_treatment": "kapitalisasi"}
    dr = _post(monkeypatch, _db(False), inv)
    assert dr == {"6-2900": 555_000}                       # beban = harga + PPN supplier


def test_ap_pkp_ppn_masukan_dikreditkan(monkeypatch):
    dr = _post(monkeypatch, _db(True), {**AP_GR, "input_tax_treatment": "kredit"})
    assert dr["1-1501"] == 110_000 and "5-1900" not in dr


def test_ap_lama_tanpa_penanda_ikut_status_saat_posting(monkeypatch):
    dr = _post(monkeypatch, _db(False), dict(AP_GR))
    assert "1-1501" not in dr and dr["5-1900"] == 110_000
