"""Uji unit HERMETIK paket W2-D Keuangan (2026-11-02) — keputusan owner K18, K19, K20, K33.

Tanpa server & tanpa Mongo: `_fake_mongo` (+ aggregate $match/$group/$sum & distinct di bawah) supaya jalur
kode ASLI ikut teruji.
  K18  satu registri aset tetap: validasi, Pembelian baru (sumber dana → jurnal ke akun kategori), Aset lama
       (akumulasi go-live, tanpa jurnal, jadwal mulai bulan go-live), jalur GR idempoten, Portal Aset tanpa jurnal.
  K19  mutasi Kas & Bank + arus kas per kategori diturunkan dari GL (transfer, kasbon, payroll, manual, impor).
  K20  Rekap: AR−AP tetap (label bukan laba), laba kotor GL, kas masuk + Penjualan Langsung.
  K33  Laporan Eksekutif: modul granular sendiri, penjaga izin, karyawan aktif, laba bersih rumus L/R.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import importlib.util
import os
import sys
from datetime import date

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
import core.recap_finance as rec  # noqa: E402
import routes.dewi_executive_report as ex  # noqa: E402
import routes.rahaza_fin_reports as frep  # noqa: E402
import routes.rahaza_fixed_assets as fa  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402
import routes.warehouse as wh  # noqa: E402
import routes.dewi_asset_management  # noqa: E402,F401  (mendaftarkan semua sub-modul Portal Aset)
import routes.asset.assets_core as pa_core  # noqa: E402
import routes.asset.dashboard as pa_dash  # noqa: E402
import routes.asset.depreciation_batch as pa_batch  # noqa: E402
import routes.asset.depreciation_per as pa_per  # noqa: E402
import routes.asset.disposal as pa_disp  # noqa: E402
from data.module_catalog import MODULE_BY_ID, match_module, menu_access  # noqa: E402


# ══════════════════════ FakeDB + aggregate secukupnya ═════════════════════════
def _ev(e, doc):
    if isinstance(e, str) and e.startswith("$"):
        v = fm._get(doc, e[1:])
        return None if v is fm._MISSING else v
    if isinstance(e, dict) and len(e) == 1 and next(iter(e)).startswith("$"):
        op, a = next(iter(e.items()))
        if op == "$ifNull":
            v = _ev(a[0], doc)
            return v if v is not None else _ev(a[1], doc)
        if op == "$subtract":
            return float(_ev(a[0], doc) or 0) - float(_ev(a[1], doc) or 0)
        if op == "$cond":
            return _ev(a[1], doc) if _ev(a[0], doc) else _ev(a[2], doc)
        if op == "$eq":
            return _ev(a[0], doc) == _ev(a[1], doc)
        if op == "$in":
            return _ev(a[0], doc) in _ev(a[1], doc)
    return e


class AggCollection(fm.FakeCollection):
    def aggregate(self, pipeline):
        rows = [dict(d) for d in self.docs]
        for st in pipeline:
            if "$match" in st:
                rows = [r for r in rows if fm.match(r, st["$match"])]
            elif "$group" in st:
                spec = dict(st["$group"])
                gid = spec.pop("_id")
                groups = {}
                for r in rows:
                    if isinstance(gid, dict) and not next(iter(gid)).startswith("$"):
                        kid = {k: _ev(v, r) for k, v in gid.items()}
                        key = tuple(sorted(kid.items()))
                    else:
                        kid = _ev(gid, r) if gid is not None else None
                        key = kid
                    g = groups.setdefault(key, {"_id": kid, **{f: 0 for f in spec}})
                    for f, acc in spec.items():
                        g[f] += float(_ev(acc["$sum"], r) or 0)
                rows = list(groups.values())
            elif "$sort" in st:
                for k, direction in reversed(list(st["$sort"].items())):
                    rows.sort(key=lambda r, k=k: r.get(k) or 0, reverse=direction < 0)
            elif "$limit" in st:
                rows = rows[:st["$limit"]]
        return fm.FakeCursor(rows)

    async def distinct(self, field, q=None):
        out = []
        for d in self.docs:
            if fm.match(d, q):
                v = fm._get(d, field)
                if v is not fm._MISSING and v is not None and v not in out:
                    out.append(v)
        return out


class DB(fm.FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = AggCollection(name)
        return self._cols[name]


def run(coro):
    return asyncio.run(coro)


USER = {"id": "u-adm", "name": "Admin Uji", "email": "adm@x", "role": "superadmin"}
FIN = {"id": "u-fin", "name": "Fin", "email": "fin@x", "role": "accounting", "_portals": ["finance"]}


@pytest.fixture
def db(monkeypatch):
    d = DB()
    for mod in (ex, frep, fa, wh, pa_core, pa_dash, pa_batch, pa_per, pa_disp):
        if hasattr(mod, "get_db"):
            monkeypatch.setattr(mod, "get_db", lambda d=d: d)
    return d


@pytest.fixture
def je_sink(monkeypatch):
    """_create_posted_je palsu: menulis kepala JE + cermin baris ke FakeDB, mencatat argumen."""
    calls = []

    async def fake_create(db_, je_date, memo, source_module, source_ref, lines_raw, user,
                          status="posted", allow_closed_period=False, **_kw):
        lines = [dict(ln) for ln in lines_raw if float(ln.get("debit") or 0) or float(ln.get("credit") or 0)]
        jid = f"je-{len(calls) + 1}"
        doc = {"id": jid, "je_number": f"JE-{len(calls) + 1:04d}", "date": je_date.isoformat(), "memo": memo,
               "source_module": source_module, "source_ref": source_ref, "status": status, "lines": lines}
        calls.append(doc)
        await db_.rahaza_journal_entries.insert_one(doc)
        for ln in lines:
            await db_.rahaza_journal_lines.insert_one({**ln, "je_id": jid, "date": doc["date"],
                                                       "source_module": source_module, "source_ref": source_ref})
        return {"ok": True, "je_id": jid, "je_number": doc["je_number"]}

    monkeypatch.setattr(rp, "_create_posted_je", fake_create)
    return calls


PROFILES = {"asset_acquisition": {"debit_fixed_asset": "1-2500", "credit_ap_clearing": "2-1150"},
            "depreciation": {"debit_depr_expense": "6-2700", "credit_accum_depr": "1-2501"},
            "asset_disposal": {"credit_fixed_asset": "1-2500", "debit_accum_depr": "1-2501", "debit_cash": "1-1201",
                               "debit_loss_on_disposal": "6-4200", "credit_gain_on_disposal": "4-2200"}}


@pytest.fixture
def asset_db(db, monkeypatch):
    for code in ("1-2100", "1-2200", "1-2201", "1-2300", "1-2301", "1-2400", "1-2401", "1-2500", "1-2501",
                 "6-2700", "6-2710", "6-2720", "6-2730", "1-1201", "2-1150", "6-2900"):
        db.rahaza_coa_accounts.docs.append({"id": f"id-{code}", "code": code, "name": code, "active": True, "is_group": False})
    db.rahaza_coa_accounts.docs.append({"id": "id-1-2000", "code": "1-2000", "active": True, "is_group": True})
    db.rahaza_cash_accounts.docs.append({"id": "ca-bca", "code": "1-1201", "name": "Bank BCA", "gl_account_code": "1-1201",
                                         "active": True})

    async def gm(db_, et):
        return dict(PROFILES.get(et, {}))
    monkeypatch.setattr(rp, "get_mapping", gm)
    monkeypatch.setattr(pp, "get_mapping", gm)
    return db


def _lines(je):
    return {(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]}


# ══════════════════════════════ K18 — aset tetap ═══════════════════════════════
BASE = {"name": "Mesin Jahit", "category": "mesin", "purchase_cost": 12_000_000, "useful_life_months": 120,
        "purchase_date": "2026-10-10", "acquisition_type": "purchase", "funding_source": "cash", "cash_account_id": "ca-bca"}


@pytest.mark.parametrize("patch,needle", [
    ({"purchase_cost": 0}, "Harga perolehan harus lebih dari 0"),
    ({"useful_life_months": 0}, "Masa manfaat"),
    ({"purchase_date": "2999-01-01"}, "melewati hari ini"),
    ({"acquisition_type": ""}, "jenis perolehan"),
    ({"funding_source": ""}, "sumber dana"),
    ({"funding_source": "grni"}, "sumber dana"),            # penanda jalur GR tidak boleh dari form
    ({"acquisition_type": "opening", "golive_date": "2026-10-01", "opening_accumulated_depr": 13_000_000,
      "purchase_date": "2024-01-05"}, "Akumulasi penyusutan awal"),
    ({"acquisition_type": "opening", "golive_date": "2026-09-01"}, "sebelum/sama dengan tanggal go-live"),
])
def test_k18_validasi_pendaftaran(asset_db, je_sink, patch, needle):
    with pytest.raises(HTTPException) as e:
        run(fa.register_fixed_asset(asset_db, {**BASE, **patch}, USER, code="FA-T"))
    assert e.value.status_code == 400 and needle in e.value.detail
    assert asset_db.rahaza_fixed_assets.docs == [] and je_sink == []


def test_k18_pembelian_tunai_jurnal_ke_akun_kategori(asset_db, je_sink):
    out = run(fa.register_fixed_asset(asset_db, dict(BASE), USER, code="FA-T1"))
    # Dr 1-2300 (kategori mesin) / Cr 1-1201 (rekening BCA yang dipilih) — dulu tanpa jurnal sama sekali
    assert _lines(je_sink[-1]) == {("1-2300", 12_000_000, 0), ("1-1201", 0, 12_000_000)}
    assert je_sink[-1]["source_ref"] == f"asset_acq:{out['id']}"
    assert out["account_id_asset"] == "id-1-2300" and out["account_id_accum_depr"] == "id-1-2301"
    assert out["account_id_depr_expense"] is None                  # mesin tanpa beban khusus → profil saat posting
    assert out["gl_je_number"] == "JE-0001" and out["_schedule_periods"] == 120
    sch = asset_db.rahaza_depr_schedules.docs
    assert sch[0]["period"] == "2026-10" and sch[0]["depr_amount"] == 100_000   # 12 jt / 120


def test_k18_pembelian_hutang_dan_faktur_pemasok(asset_db, je_sink):
    # Tahap 6 (KU2): hutang faktur menyusul wajib pemasok dari master
    asset_db.rahaza_suppliers.docs.append({"id": "sup-1", "code": "SUP-1", "name": "PT Pemasok Uji", "is_active": True})
    run(fa.register_fixed_asset(asset_db, {**BASE, "category": "kendaraan", "name": "Mobil", "purchase_cost": 60_000_000,
                                           "useful_life_months": 60, "funding_source": "payable", "supplier_id": "sup-1"},
                                USER, code="FA-T2"))
    assert _lines(je_sink[-1]) == {("1-2400", 60_000_000, 0), ("2-1150", 0, 60_000_000)}
    # faktur pemasok sudah menjurnal Dr 6-2900 / Cr 2-1100 → perolehan mereklas 6-2900 ke akun aset
    asset_db.rahaza_ap_invoices.docs.append({"id": "ap1", "invoice_number": "AP-1", "status": "sent", "subtotal": 5_000_000,
                                             "total": 5_550_000, "vendor_name": "PT A"})
    asset_db.rahaza_journal_entries.docs.append({"id": "je-ap", "je_number": "JE-AP", "source_module": "ap_invoice",
                                                 "source_ref": "ap:ap1", "status": "posted",
                                                 "lines": [{"account_code": "6-2900", "debit": 5_000_000, "credit": 0},
                                                           {"account_code": "1-1501", "debit": 550_000, "credit": 0},
                                                           {"account_code": "2-1100", "debit": 0, "credit": 5_550_000}]})
    body = {**BASE, "category": "it", "name": "Laptop", "purchase_cost": 4_000_000, "useful_life_months": 36,
            "funding_source": "ap_invoice", "ap_invoice_id": "ap1"}
    out = run(fa.register_fixed_asset(asset_db, body, USER, code="FA-T3"))
    assert _lines(je_sink[-1]) == {("1-2500", 4_000_000, 0), ("6-2900", 0, 4_000_000)}
    assert out["ap_invoice_number"] == "AP-1" and out["supplier"] == "PT A"
    with pytest.raises(HTTPException) as e:        # sisa DPP faktur 1.000.000 < 2.000.000
        run(fa.register_fixed_asset(asset_db, {**body, "purchase_cost": 2_000_000}, USER, code="FA-T4"))
    assert e.value.status_code == 400 and "melebihi sisa nilai faktur" in e.value.detail


def test_k18_jurnal_gagal_membatalkan_pendaftaran(asset_db, monkeypatch):
    async def gagal(*_a, **_k):
        return {"ok": False, "error": "Periode 2026-10 sudah ditutup."}
    monkeypatch.setattr(rp, "_create_posted_je", gagal)
    with pytest.raises(HTTPException) as e:
        run(fa.register_fixed_asset(asset_db, dict(BASE), USER, code="FA-T5"))
    assert "jurnal perolehan gagal" in e.value.detail and "ditutup" in e.value.detail
    assert asset_db.rahaza_fixed_assets.docs == [] and asset_db.rahaza_depr_schedules.docs == []


def test_k18_aset_lama_tanpa_jurnal_jadwal_mulai_golive(asset_db, je_sink):
    # Hitung tangan (contoh audit No.37): beli 2024-01, Rp24 jt, 48 bln, go-live 2026-10, akumulasi s.d. Sep 2026
    # = 33 × 500.000 = 16.500.000 → sisa 15 bulan × 500.000; nilai buku akhir Okt 2026 = 7.000.000.
    body = {"name": "Mesin Lama", "category": "mesin", "purchase_cost": 24_000_000, "useful_life_months": 48,
            "purchase_date": "2024-01-05", "acquisition_type": "opening", "golive_date": "2026-10-01",
            "opening_accumulated_depr": 16_500_000}
    out = run(fa.register_fixed_asset(asset_db, body, USER, code="FA-OLD"))
    assert je_sink == [] and out["_posting_result"] is None
    sch = sorted(asset_db.rahaza_depr_schedules.docs, key=lambda s: s["period"])
    assert (len(sch), sch[0]["period"], sch[-1]["period"]) == (15, "2026-10", "2027-12")
    assert {s["depr_amount"] for s in sch} == {500_000} and sch[-1]["book_value_end"] == 0
    asset_db.rahaza_depr_schedules.docs[0]["posted"] = True       # posting Okt 2026
    a = dict(out)
    run(fa._enrich_nbv(asset_db, a))
    assert a["accumulated_depreciation"] == 17_000_000 and a["book_value_current"] == 7_000_000


def test_k18_ringkasan_dan_pelepasan_memuat_akumulasi_awal(asset_db, je_sink, monkeypatch):
    asset_db.rahaza_fixed_assets.docs = [
        {"id": "a1", "status": "active", "purchase_cost": 24_000_000, "opening_accumulated_depr": 16_500_000},
        {"id": "a2", "status": "disposed", "purchase_cost": 5_000_000}]
    asset_db.rahaza_depr_schedules.docs = [
        {"asset_id": "a1", "period": "2026-10", "posted": True, "depr_amount": 500_000},
        {"asset_id": "a2", "period": "2026-01", "posted": True, "depr_amount": 2_000_000}]   # aset dilepas: tak dihitung
    monkeypatch.setattr(fa, "require_auth", lambda *_a, **_k: asyncio.sleep(0, USER))
    s = run(fa.fixed_assets_summary(fm.FakeRequest()))
    assert (s["total_cost"], s["total_accumulated_depr"], s["total_nbv"]) == (24_000_000, 17_000_000, 7_000_000)
    seen = {}

    async def disp(db_, asset, user):
        seen.update(asset)
        return {"ok": True, "je_id": "je-d", "je_number": "JE-D"}
    monkeypatch.setattr(rp, "post_asset_disposal", disp)
    out = run(fa.dispose_fixed_asset(asset_db, "a1", {"disposal_date": "2026-10-31", "disposal_value": 8_000_000}, USER))
    # NBV = 24 jt − (16,5 jt awal + 0,5 jt Okt) = 7 jt → laba 1 jt
    assert seen["accumulated_depr_at_disposal"] == 17_000_000 and out["nbv_at_disposal"] == 7_000_000
    assert out["gain_loss"] == 1_000_000


def test_k18_gr_aset_registri_sama_idempoten(asset_db, je_sink, monkeypatch):
    async def num(*_a, **_k):
        return "FA-GR1"
    monkeypatch.setattr(wh, "gen_prefixed_number", num)
    item = {"id": "it1", "item_type": "asset", "asset_category": "mesin", "product_name": "Obras", "received_qty": 1,
            "rejected_qty": 0, "unit_price": 3_000_000}
    grn = {"id": "gr1", "receipt_number": "GR-1", "supplier_name": "PT B"}
    a1 = run(wh._capitalize_assets_from_grn(asset_db, "gr1", grn, [item], USER))
    a2 = run(wh._capitalize_assets_from_grn(asset_db, "gr1", grn, [item], USER))   # terima ulang
    assert len(a1) == 1 and a2 == [] and len(asset_db.rahaza_fixed_assets.docs) == 1
    doc = asset_db.rahaza_fixed_assets.docs[0]
    assert doc["grn_item_id"] == "it1" and doc["acquisition_type"] == "purchase" and doc["funding_source"] == "grni"
    assert _lines(je_sink[-1]) == {("1-2300", 3_000_000, 0), ("2-1150", 0, 3_000_000)}    # dulu selalu 1-2500
    assert len(asset_db.rahaza_depr_schedules.docs) == 120                                 # dulu tanpa jadwal


def test_k18_form_tidak_boleh_menyamar_jalur_gr(asset_db, je_sink, monkeypatch):
    monkeypatch.setattr(fa, "require_auth", lambda *_a, **_k: asyncio.sleep(0, USER))
    with pytest.raises(HTTPException) as e:
        run(fa.create_fixed_asset(fm.FakeRequest({**BASE, "funding_source": "grni", "_system_gr": True})))
    assert e.value.status_code == 400


async def _ok_user(*_a, **_k):
    return dict(USER)


def test_k18_portal_aset_tanpa_jurnal_dan_nilai_dari_keuangan(asset_db, monkeypatch):
    asset_db.rahaza_fixed_assets.docs = [{"id": "fa1", "code": "FA-1", "name": "Mesin", "status": "active",
                                          "purchase_cost": 12_000_000, "purchase_date": "2026-01-10"}]
    asset_db.rahaza_depr_schedules.docs = [{"asset_id": "fa1", "period": "2026-01", "posted": True, "depr_amount": 100_000}]
    for mod in (pa_core, pa_batch, pa_per, pa_disp, pa_dash):
        monkeypatch.setattr(mod, "require_auth", _ok_user)

    async def num(*_a, **_k):
        return "AST-LN-2026-0001"
    monkeypatch.setattr(pa_core, "_gen_asset_number", num)
    out = run(pa_core.create_asset(fm.FakeRequest({"name": "Mesin (operasional)", "fixed_asset_id": "fa1",
                                                    "location": "Lantai 1"})))
    assert asset_db.rahaza_journal_entries.docs == [] and out["journal_purchase_id"] is None
    assert out["fixed_asset_code"] == "FA-1" and out["value_source"] == "finance_registry" and out["nbv"] == 11_900_000
    with pytest.raises(HTTPException) as e:          # satu aset Keuangan hanya untuk satu catatan Portal Aset
        run(pa_core.create_asset(fm.FakeRequest({"name": "Duplikat", "fixed_asset_id": "fa1"})))
    assert e.value.status_code == 409
    for call in (pa_batch.batch_depreciate("2026-10", fm.FakeRequest()),
                 pa_per.post_depreciation(out["id"], "2026-10", fm.FakeRequest())):
        with pytest.raises(HTTPException) as e:
            run(call)
        assert e.value.status_code == 410 and "registri Keuangan" in e.value.detail
    lst = run(pa_dash.finance_registry_lookup(fm.FakeRequest(), include_linked=True))
    assert lst[0]["linked_asset_number"] == "AST-LN-2026-0001" and lst[0]["book_value"] == 11_900_000


def test_k18_pelepasan_portal_aset_lewat_jalur_keuangan(asset_db, monkeypatch):
    asset_db.rahaza_fixed_assets.docs = [{"id": "fa1", "code": "FA-1", "name": "Mesin", "status": "active",
                                          "purchase_cost": 12_000_000}]
    asset_db.dewi_assets.docs = [{"id": "pa1", "asset_number": "AST-1", "name": "Mesin", "status": "active",
                                  "purchase_cost": 12_000_000, "fixed_asset_id": "fa1"},
                                 {"id": "pa2", "asset_number": "AST-2", "name": "Kursi", "status": "active",
                                  "purchase_cost": 500_000}]
    gudang = {"id": "u-g", "role": "admin_gudang", "name": "Gudang"}

    async def as_gudang(*_a, **_k):
        return dict(gudang)

    async def as_fin(*_a, **_k):
        return dict(FIN)
    called = []

    async def disp(db_, asset, user):
        called.append(asset["id"])
        return {"ok": True, "je_id": "je-d", "je_number": "JE-D"}
    monkeypatch.setattr(rp, "post_asset_disposal", disp)
    monkeypatch.setattr(pa_disp, "require_auth", as_gudang)
    with pytest.raises(HTTPException) as e:          # gudang tidak boleh memposting pelepasan aset Keuangan
        run(pa_disp.dispose_asset("pa1", fm.FakeRequest({"disposal_date": "2026-10-31"})))
    assert e.value.status_code == 403
    out = run(pa_disp.dispose_asset("pa2", fm.FakeRequest({"disposal_date": "2026-10-31"})))   # belum tertaut: tanpa jurnal
    assert out["journal_id"] is None and asset_db.rahaza_journal_entries.docs == []
    monkeypatch.setattr(pa_disp, "require_auth", as_fin)
    out = run(pa_disp.dispose_asset("pa1", fm.FakeRequest({"disposal_date": "2026-10-31", "disposal_value": 1_000})))
    assert called == ["fa1"] and out["journal_id"] == "je-d"
    assert asset_db.rahaza_fixed_assets.docs[0]["status"] == "disposed"


def _load_script(name):
    cwd = os.getcwd()
    try:
        path = os.path.join(BACKEND, "..", "scripts", f"{name}.py")
        spec = importlib.util.spec_from_file_location(f"_uji_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(cwd)


def test_k18_skrip_migrasi_tautan_portal_aset():
    m = _load_script("migrate_portal_aset_link_finance")
    fin = [{"id": "f1", "name": "Mesin Jahit", "purchase_cost": 6_000_000, "purchase_date": "2026-01-02", "serial_number": ""},
           {"id": "f2", "name": "Laptop", "purchase_cost": 9, "purchase_date": "2026-01-01", "serial_number": "SN-9"},
           {"id": "f3", "name": "Mesin Jahit", "purchase_cost": 6_000_000, "purchase_date": "2026-01-02", "status": "disposed"}]
    assert [c["id"] for c in m.match_candidates({"name": "mesin  jahit", "purchase_cost": 6e6, "purchase_date": "2026-01-02"}, fin, set())] == ["f1"]
    assert [c["id"] for c in m.match_candidates({"name": "x", "serial_number": "sn-9"}, fin, set())] == ["f2"]
    assert m.match_candidates({"name": "Mesin Jahit", "purchase_cost": 6e6, "purchase_date": "2026-01-02"}, fin, {"f1"}) == []


# ══════════════════════════ K19 — Kas & Bank dari GL ═══════════════════════════
def _gl(db, je, date_, src, debit, credit, code="1-1201", ref=""):
    db.rahaza_journal_lines.docs.append({"id": f"l-{je}-{code}", "je_id": je, "je_number": je.upper(), "date": date_,
                                         "account_code": code, "debit": debit, "credit": credit, "source_module": src,
                                         "source_ref": ref, "description": src})


@pytest.fixture
def cash_db(db):
    db.rahaza_coa_accounts.docs += [{"code": "1-1200", "is_group": True}, {"code": "1-1201", "parent_code": "1-1200"},
                                    {"code": "1-1202", "parent_code": "1-1200"},
                                    {"code": "4-1100", "type": "REVENUE"}, {"code": "6-2900", "type": "EXPENSE"},
                                    {"code": "1-2300", "type": "ASSET"}]
    db.rahaza_cash_accounts.docs += [{"id": "bca", "code": "1-1201", "name": "BCA", "gl_account_code": "1-1201", "active": True},
                                     {"id": "mdr", "code": "1-1202", "name": "Mandiri", "gl_account_code": "1-1202", "active": True},
                                     {"id": "kas", "code": "K-1", "name": "Kas lama", "active": True, "opening_balance": 100}]
    # Hitung tangan BCA: saldo awal 5.000.000 (go-live) + manual 2.000.000 − transfer 500.000 − kasbon 400.000
    #   + impor 250.000 − gaji 2.796.000 + pembayaran AR 1.110.000 = 4.664.000
    _gl(db, "ob", "2026-09-30", "opening_balance", 5_000_000, 0)
    _gl(db, "j1", "2026-10-03", "manual", 2_000_000, 0)
    _gl(db, "j2", "2026-10-05", "bank_transfer", 0, 500_000)
    _gl(db, "j2", "2026-10-05", "bank_transfer", 500_000, 0, code="1-1202")
    _gl(db, "j3", "2026-10-07", "employee_loan_disbursement", 0, 400_000)
    _gl(db, "j4", "2026-10-06", "journal_import", 250_000, 0)
    _gl(db, "j5", "2026-10-28", "payroll_payment", 0, 2_796_000)
    _gl(db, "j6", "2026-10-08", "ar_payment", 1_110_000, 0, ref="arpay:mv-1:1110000")
    db.rahaza_cash_movements.docs += [
        {"id": "mv-1", "account_id": "bca", "direction": "in", "amount": 1_110_000, "category": "ar_payment",
         "ref_label": "SL-001", "date": "2026-10-08"},
        {"id": "mv-k", "account_id": "kas", "direction": "in", "amount": 50, "category": "other", "date": "2026-10-01"}]
    return db


def test_k19_kategori_dari_source_module():
    assert {s: rp.cash_category(s) for s in ("bank_transfer", "employee_loan_disbursement", "payroll_payment",
                                             "bpjs_payment", "manual", "journal_import", "asset_acquisition", "modul_baru")} == {
        "bank_transfer": "transfer", "employee_loan_disbursement": "kasbon", "payroll_payment": "payroll",
        "bpjs_payment": "payroll", "manual": "manual_journal", "journal_import": "journal_import",
        "asset_acquisition": "asset_purchase", "modul_baru": "modul_baru"}


def test_k19_kolom_mutasi_kartu_sama_dengan_gl(cash_db):
    rows = {r["code"]: r for r in run(rp.cash_accounts_with_gl(cash_db, {"active": True}))}
    bca = rows["1-1201"]
    assert bca["balance"] == bca["balance_mutasi"] == 4_664_000 and bca["balance_diff"] == 0
    assert bca["mutation_count"] == 7 and bca["mutation_source"] == "gl"
    assert rows["1-1202"]["balance_mutasi"] == 500_000
    assert rows["K-1"]["balance_source"] == "movements" and rows["K-1"]["balance"] == 150   # tanpa GL: saldo awal + mutasi


def test_k19_daftar_mutasi_turunan_gl_semua_jalur(cash_db):
    out = run(rp.cash_mutations_from_gl(cash_db, "1-1201", "2026-10-01", "2026-10-31", account_id="bca"))
    assert {r["category"] for r in out["rows"]} == {"manual_journal", "transfer", "kasbon", "journal_import", "payroll",
                                                    "ar_payment"}
    assert out["opening"] == 5_000_000 and out["closing"] == 4_664_000 and out["count"] == 6
    assert (out["total_in"], out["total_out"]) == (3_360_000, 3_696_000)
    assert out["rows"][0]["date"] == "2026-10-28" and out["rows"][0]["running_balance"] == 4_664_000   # terbaru dulu
    ar = next(r for r in out["rows"] if r["category"] == "ar_payment")
    assert ar["ref_label"] == "SL-001" and ar["movement_id"] == "mv-1"                    # metadata mutasi lama


def test_mutasi_rekening_per_halaman_total_utuh_dan_saldo_bersambung(cash_db):
    """2026-11-04: dulu 2000 baris TERTUA → mutasi terbaru hilang & total hanya dari baris terbaca."""
    full = run(rp.cash_mutations_from_gl(cash_db, "1-1201", "2026-10-01", "2026-10-31", account_id="bca"))
    p1 = run(rp.cash_mutations_from_gl(cash_db, "1-1201", "2026-10-01", "2026-10-31", account_id="bca", page_size=4))
    p2 = run(rp.cash_mutations_from_gl(cash_db, "1-1201", "2026-10-01", "2026-10-31", account_id="bca", page=2, page_size=4))
    assert [r["running_balance"] for r in p1["rows"] + p2["rows"]] == [r["running_balance"] for r in full["rows"]]
    assert len(p1["rows"]) == 4 and len(p2["rows"]) == 2 and p2["count"] == 6
    assert (p2["total_in"], p2["total_out"], p2["closing"]) == (full["total_in"], full["total_out"], full["closing"])
    oldest = p2["rows"][-1]                     # saldo sesudah baris tertua = saldo awal + mutasinya
    assert oldest["running_balance"] == 5_000_000 + (oldest["amount"] if oldest["direction"] == "in" else -oldest["amount"])


def test_k19_arus_kas_kategori_dari_gl_kas_awal_sama_per_akun(cash_db):
    d = run(frep._cash_flow_data(cash_db, "2026-10-01", "2026-10-31"))
    t = d["totals"]
    # kas awal = saldo awal go-live 5.000.000 (dulu: saldo GL hari ini − Σ mutasi tercatat)
    # net = 2.000.000 + 0 (transfer BCA→Mandiri saling hapus) − 400.000 + 250.000 − 2.796.000 + 1.110.000 = 164.000
    assert (t["opening_cash"], t["net_change_in_cash"], t["closing_cash"]) == (5_000_000, 164_000, 5_164_000)
    items = {i["category"]: i["net"] for k in ("operating", "investing", "financing") for i in d["activities"][k]["items"]}
    assert items == {"manual_journal": 2_000_000, "transfer": 0, "kasbon": -400_000, "journal_import": 250_000,
                     "payroll": -2_796_000, "ar_payment": 1_110_000}
    ba = d["by_account"]["totals"]
    assert (ba["opening_cash_gl"], ba["closing_cash_gl"]) == (t["opening_cash"], t["closing_cash"])


def test_k19_endpoint_mutasi_rekening_tanpa_gl(cash_db, monkeypatch):
    monkeypatch.setattr(frep, "require_auth", _ok_user)
    with pytest.raises(HTTPException) as e:
        run(frep.cash_mutations(fm.FakeRequest(), account_id="kas", gl_account_code=None, from_date=None, to_date=None, page=1, page_size=50))
    assert e.value.status_code == 400
    out = run(frep.cash_mutations(fm.FakeRequest(), account_id="mdr", gl_account_code=None, from_date=None, to_date=None, page=1, page_size=50))
    assert out["count"] == 1 and out["rows"][0]["category"] == "transfer" and out["account"]["name"] == "Mandiri"


# ═══════════════════════════════ K20 — Rekap ══════════════════════════════════
@pytest.fixture
def recap_db(db):
    db.rahaza_coa_accounts.docs += [{"code": "4-1100", "name": "Penjualan", "type": "REVENUE", "is_group": False},
                                    {"code": "4-1111", "name": "Shopee", "type": "REVENUE", "is_group": False},
                                    {"code": "5-1000", "name": "HPP", "type": "COGS", "is_group": False}]
    db.rahaza_ar_invoices.docs += [
        {"id": "ar1", "status": "issued", "issue_date": "2026-10-08", "total": 1_110_000, "balance": 0, "source_module": "direct_sale"},
        {"id": "ar2", "status": "issued", "issue_date": "2026-10-09", "total": 555_000, "balance": 355_000},
        {"id": "ar3", "status": "draft", "issue_date": "2026-10-09", "total": 9_999_999, "balance": 9_999_999}]
    db.rahaza_ap_invoices.docs += [{"id": "ap1", "status": "sent", "issue_date": "2026-10-02", "total": 1_000_000, "balance": 1_000_000}]
    db.rahaza_ar_payments.docs += [{"id": "p1", "invoice_id": "ar2", "amount": 200_000, "date": "2026-10-10", "movement_id": "mv-2"}]
    db.rahaza_cash_movements.docs += [
        {"id": "mv-ds", "category": "ar_payment", "direction": "in", "ref_id": "ar1", "amount": 1_110_000, "date": "2026-10-08"},
        {"id": "mv-2", "category": "ar_payment", "direction": "in", "ref_id": "ar2", "amount": 200_000, "date": "2026-10-10"},
        {"id": "mv-ds-old", "category": "ar_payment", "direction": "in", "ref_id": "ar1", "amount": 7, "date": "2026-09-30"}]
    # GL Okt: pendapatan DPP 1.000.000 + 500.000 + pencairan marketplace 900.000 − retur 100.000; HPP 1.200.000
    for i, (code, d, c, dt) in enumerate([("4-1100", 0, 1_000_000, "2026-10-08"), ("4-1100", 0, 500_000, "2026-10-09"),
                                          ("4-1111", 0, 900_000, "2026-10-15"), ("4-1100", 100_000, 0, "2026-10-20"),
                                          ("5-1000", 1_200_000, 0, "2026-10-21"), ("4-1100", 0, 777, "2026-12-01")]):
        db.rahaza_journal_lines.docs.append({"id": f"r{i}", "account_code": code, "debit": d, "credit": c, "date": dt,
                                             "source_module": "x"})
    return db


def test_k20_kas_masuk_penjualan_langsung(recap_db):
    # mv-2 sudah tercatat di rahaza_ar_payments (tidak dobel); mv-ds-old di luar periode
    assert run(rec.sum_direct_sale_receipts(recap_db, {"$gte": "2026-10-01", "$lte": "2026-10-31"})) == 1_110_000


def test_k20_rekap_label_dan_laba_kotor_gl(recap_db):
    r = run(rec.compute_financial_recap(recap_db, "2026-10-01", "2026-10-31", date(2026, 11, 2), ["issued", "sent", "partial_paid"]))
    assert r["gross_margin"] == 1_665_000 - 1_000_000 == 665_000          # rumus T1 tetap (AR − AP, tanpa draft)
    assert "bukan laba" in r["gross_margin_label"]
    assert r["gl_revenue"] == 2_300_000 and r["gl_cogs"] == 1_200_000 and r["gl_gross_profit"] == 1_100_000
    assert r["total_cash_in"] == 1_310_000 and r["cash_in_breakdown"] == {"ar_payments": 200_000, "direct_sales": 1_110_000}
    oct_, nov = r["monthly_trend"][-2], r["monthly_trend"][-1]
    assert oct_["gl_gross_profit"] == 1_100_000 and oct_["cash_in"] == 1_310_000
    assert nov["gl_gross_profit"] == 0                                      # 1 Des tidak lagi masuk November


def test_rekap_hutang_per_vendor_terisi(recap_db):
    # dulu `garment_summary` selalu [] → kartu "Hutang Vendor" selalu "Tidak ada data"
    recap_db.rahaza_ap_invoices.docs[0]["vendor_name"] = "CMT Bu Lilis"
    recap_db.rahaza_ap_invoices.docs += [
        {"id": "ap2", "vendor_name": "ACSM", "status": "paid", "issue_date": "2026-10-03", "total": 4_000_000, "balance": 0},
        {"id": "ap3", "vendor_name": "ACSM", "status": "partial_paid", "issue_date": "2026-10-20", "total": 3_000_000, "balance": 1_200_000},
        {"id": "ap4", "vendor_name": "ACSM", "status": "draft", "issue_date": "2026-10-21", "total": 9_000_000, "balance": 9_000_000},
        {"id": "ap5", "vendor_name": "WAITEX", "status": "sent", "issue_date": "2026-09-30", "total": 5_000_000, "balance": 5_000_000}]
    r = run(rec.compute_financial_recap(recap_db, "2026-10-01", "2026-10-31", date(2026, 11, 2), ["issued", "sent", "partial_paid"]))
    rows = {g["vendor_name"]: g for g in r["garment_summary"]}
    assert set(rows) == {"ACSM", "CMT Bu Lilis"}                            # draft & di luar periode tidak ikut
    assert rows["ACSM"]["total_invoiced"] == 7_000_000 and rows["ACSM"]["outstanding"] == 1_200_000
    assert rows["CMT Bu Lilis"]["outstanding"] == 1_000_000 and rows["CMT Bu Lilis"]["garment_name"] == "CMT Bu Lilis"
    assert [g["vendor_name"] for g in r["garment_summary"]] == ["ACSM", "CMT Bu Lilis"]   # urut sisa terbesar


# ═════════════════════════ K33 — Laporan Eksekutif ═════════════════════════════
def test_k33_modul_granular_sendiri():
    assert match_module("/api/reports/executive/hr-snapshot")["id"] == "fin_exec_report"
    assert "fin-executive-report" not in MODULE_BY_ID["fin_dashboard"]["menus"]
    assert "/api/reports/executive" not in MODULE_BY_ID["mgmt_dashboard"]["paths"]
    hidden, _ = menu_access(["mod.fin_dashboard.view"])
    assert "fin-executive-report" in hidden                               # bisa disembunyikan sendiri
    hidden, access = menu_access(["mod.fin_dashboard.view", "mod.fin_exec_report.view"])
    assert "fin-executive-report" not in hidden and access["fin-executive-report"] == ["view"]


@pytest.fixture
def rbac_db(db):
    db.roles.docs += [{"id": "r-acc", "name": "accounting", "portals": ["finance", "self"]},
                      {"id": "r-op", "name": "operator"},
                      {"id": "r-cus", "name": "keuangan_terbatas", "portals": ["finance"]},
                      {"id": "r-hid", "name": "staff_keuangan", "portals": ["finance"], "hidden_modules": ["fin-executive-report"]}]
    db.role_permissions.docs += [{"role_id": "r-cus", "permission_key": "mod.fin_ar.view"}]
    for uid, role in (("u-acc", "accounting"), ("u-op", "operator"), ("u-op2", "operator"), ("u-cus", "keuangan_terbatas"),
                      ("u-hid", "staff_keuangan"), ("u-mp", "manager_produksi"), ("u-tp", "tim_packing")):
        db.users.docs.append({"id": uid, "role": role})
    db.users.docs[[u["id"] for u in db.users.docs].index("u-op2")]["extra_permissions"] = ["mod.fin_exec_report.view"]
    return db


@pytest.mark.parametrize("uid,role,perms,expected", [
    ("u-adm", "superadmin", ["*"], (True, "super")),
    # 13 Nov 2026: centang = satu-satunya penentu — peran Keuangan/Manajemen tanpa centang tidak lagi lolos "bawaan"
    # (peran yang dulu lolos dicentangkan migrasi 2026_11_13_centang_akses_penuh). Menu tanpa Lihat = tersembunyi.
    ("u-acc", "accounting", [], (False, "hidden")),
    ("u-mp", "manager_produksi", [], (False, "hidden")),
    ("u-op", "operator", [], (False, "hidden")),                         # dulu 200 → total gaji terbaca
    ("u-tp", "tim_packing", [], (False, "hidden")),
    ("u-cus", "keuangan_terbatas", ["mod.fin_ar.view"], (False, "hidden")),     # owner mengatur granular tanpa centang
    ("u-hid", "staff_keuangan", [], (False, "hidden")),                  # menu disembunyikan di Manajemen Role
    ("u-op2", "operator", ["mod.fin_exec_report.view"], (True, "permission")),  # owner mencentang izin → boleh
])
def test_k33_aturan_akses(rbac_db, uid, role, perms, expected):
    user = {"id": uid, "role": role, "_permissions": perms}
    assert run(ex.exec_report_access(rbac_db, user)) == expected


def test_k33_penjaga_router_403_untuk_operator(rbac_db, monkeypatch):
    async def as_op(*_a, **_k):
        return {"id": "u-op", "role": "operator", "_permissions": []}

    async def as_acc(*_a, **_k):
        return {"id": "u-acc", "role": "accounting", "_permissions": [], "_portals": ["finance", "self"]}
    monkeypatch.setattr(ex, "require_auth", as_op)
    with pytest.raises(HTTPException) as e:
        run(ex.require_exec_report(fm.FakeRequest()))
    # 14 Nov 2026: pesan tanpa kunci izin program; sebut modul & letak centangnya
    assert e.value.status_code == 403 and "\"Laporan Eksekutif\"" in e.value.detail and "mod." not in e.value.detail
    assert "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses" in e.value.detail
    # SEMUA endpoint router (summary, ai-narrative, kpi-comparison, *-snapshot, trend) memanggil penjaga
    from fastapi.routing import APIRoute
    routes = [r for r in ex.router.routes if isinstance(r, APIRoute)]
    assert len(routes) == 8
    for r in routes:
        with pytest.raises(HTTPException) as e:
            run(r.endpoint(fm.FakeRequest()))
        assert e.value.status_code == 403, r.path
    monkeypatch.setattr(ex, "require_auth", as_acc)
    with pytest.raises(HTTPException):                       # tanpa centang → ditolak walau peran Keuangan
        run(ex.require_exec_report(fm.FakeRequest()))

    async def as_op2(*_a, **_k):
        return {"id": "u-op2", "role": "operator", "_permissions": ["mod.fin_exec_report.view"]}
    monkeypatch.setattr(ex, "require_auth", as_op2)
    assert run(ex.require_exec_report(fm.FakeRequest()))["id"] == "u-op2"


def test_k33_karyawan_aktif_dan_laba_bersih_rumus_lr(db):
    db.rahaza_employees.docs += [{"id": "e1", "active": True}, {"id": "e2", "active": True}, {"id": "e3", "active": False}]
    assert run(ex._hr_kpis(db, 2026, 10))["total_active_employees"] == 2     # dulu employment_status → 0
    db.rahaza_coa_accounts.docs += [{"code": "4-1100", "name": "P", "type": "REVENUE", "is_group": False},
                                    {"code": "6-2900", "name": "B", "type": "EXPENSE", "is_group": False},
                                    {"code": "7-1000", "name": "PL", "type": "OTHER_INCOME", "is_group": False}]
    for i, (code, d, c) in enumerate([("4-1100", 0, 2_000_000), ("6-2900", 1_000_000, 0), ("6-2900", 0, 300_000),
                                      ("7-1000", 0, 50_000)]):
        db.rahaza_journal_lines.docs.append({"id": f"x{i}", "account_code": code, "account_type": "", "debit": d,
                                             "credit": c, "date": "2026-10-04", "source_module": "manual"})
    k = run(ex._finance_kpis(db, 2026, 10))
    # biaya = 1.000.000 − koreksi kredit 300.000 = 700.000 (dulu debit saja 1.000.000)
    assert k["total_expenses_rp"] == 700_000 and k["other_income_rp"] == 50_000
    assert k["net_income_rp"] == 2_000_000 + 50_000 - 700_000 == 1_350_000


def test_k33_skrip_izin_awal_peran_granular():
    m = _load_script("migrate_fin_exec_report_perm")
    roles = {"accounting", "manager_keuangan"}
    assert m.keys_to_add("accounting", {"mod.fin_dashboard.view", "mod.fin_dashboard.export"}, roles) == [
        "mod.fin_exec_report.view", "mod.fin_exec_report.export"]
    assert m.keys_to_add("operator", {"mod.fin_dashboard.view"}, roles) == []
    assert m.keys_to_add("accounting", {"mod.fin_ar.view"}, roles) == []
    assert m.keys_to_add("accounting", {"mod.fin_dashboard.view", "mod.fin_exec_report.view"}, roles) == []
