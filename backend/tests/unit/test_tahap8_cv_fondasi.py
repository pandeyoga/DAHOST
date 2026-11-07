"""Tahap 8 fase 1 — fondasi dua buku: CV Dewi Aditya (DA) & CV Sukma (SMU), hermetik (FakeDB, tanpa server).

Yang dikunci di sini:
  * aturan CV (core.entities): pembacaan pilihan CV dari query/body/header, saringan DA mencakup data lama,
    aturan kode "berlaku untuk", CV dokumen/modul sumber, PO tanpa jenis = internal (desain §9);
  * penjaga jurnal manual (akun/rekening CV lain → 400) vs jurnal otomatis (tidak diblokir, ditandai);
  * periode per CV, nomor jurnal per CV, idempotensi (modul, ref, CV);
  * migrasi 2026_11_08_entitas_cv (aturan murni + langkah tulis, idempoten);
  * profil/kop/pajak per CV, transfer antar CV ditolak, mode Gabungan hanya dilihat;
  * tarif jahit job dari po_items (SSOT) dengan nilai job sebagai cadangan.
"""
import asyncio
import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
import core.entities as ent  # noqa: E402
import routes.rahaza_journals as rj  # noqa: E402
import routes.rahaza_periods as rper  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import utils.counters as counters  # noqa: E402
from utils.waktu import today_wib  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
FE = BACKEND.parent / "frontend" / "src"
USER = {"id": "u-fin", "name": "Staf Keuangan Uji", "role": "accounting"}
TAG = "UJI-T8-cv"


def run(c):
    return asyncio.run(c)


class Req(fm.FakeRequest):
    """Request palsu dengan query & header (header dinormalkan huruf kecil seperti Starlette)."""

    def __init__(self, body=None, query=None, headers=None):
        super().__init__(body)
        self.query_params = dict(query or {})
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


def acc(code, type_="ASSET", name=None, parent=None, entities=None, group=False):
    d = {"id": f"id-{code}", "code": code, "name": name or f"Akun {code}", "type": type_, "is_group": group,
         "parent_code": parent, "active": True, "flags": {}, "normal_balance": "DEBIT"}
    if entities:
        d["entities"] = entities
    return d


async def _auth(_req):
    return dict(USER)


async def _noop(*_a, **_k):
    return None


@pytest.fixture
def db(monkeypatch):
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [
        acc("1-1201", name="Bank BCA DA", entities=["DA"]),
        acc("1-1213", name="Bank BCA Sukma", entities=["SMU"]),
        acc("1-1305", name="Piutang Maklon"),
        acc("4-1100", "REVENUE", "Penjualan Garment"),
        acc("4-1500", "REVENUE", "Pendapatan Maklon"),
        acc("6-2900", "EXPENSE", "Beban Umum"),
    ]
    d.rahaza_cash_accounts.docs += [
        {"id": "ca-da", "code": "BCA-DA", "name": "BCA DA", "gl_account_code": "1-1201", "active": True},
        {"id": "ca-smu", "code": "BCA-SMU", "name": "BCA Sukma", "gl_account_code": "1-1213", "active": True,
         "entity": "SMU"},
    ]
    for mod in (rj, rper):
        monkeypatch.setattr(mod, "get_db", lambda d=d: d)
        monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(rj, "_require_fin", _auth)
    monkeypatch.setattr(rper, "_require_fin_mgr", _auth)
    monkeypatch.setattr(rj, "require_auth", _auth)
    monkeypatch.setattr(rper, "require_auth", _auth)
    issued = []

    async def fake_gen(db_, coll, field, prefix, width=4, ctx=None, config_key=None):
        issued.append(prefix)
        return f"{prefix}{len(issued):0{width}d}"
    monkeypatch.setattr(counters, "gen_prefixed_number", fake_gen)
    counters.invalidate_format_cache()
    d._issued = issued
    return d


# ══════════════════════════════ aturan CV ══════════════════════════════════════════════
def test_normalisasi_kode_cv():
    assert ent.normalize_entity("smu") == "SMU" and ent.normalize_entity("Sukma") == "SMU"
    assert ent.normalize_entity("") is None and ent.normalize_entity(None, default="DA") == "DA"
    assert ent.normalize_entity("all", allow_all=True) == "ALL"
    with pytest.raises(ValueError, match="Gabungan"):
        ent.normalize_entity("ALL")
    with pytest.raises(ValueError, match="tidak dikenal"):
        ent.normalize_entity("PT-LAIN")
    assert ent.entity_of_value("rusak") == "DA" and ent.entity_of_value(None) == "DA"


def test_pilihan_cv_dari_query_body_header():
    r = Req(query={"entity": "SMU"}, headers={"X-CV": "DA"})
    assert ent.entity_from_request(r, {"entity": "DA"}) == "SMU"          # query menang
    assert ent.entity_from_request(Req(headers={"X-CV": "SMU"}), {"entity": "DA"}) == "DA"   # body > header
    assert ent.entity_from_request(Req(headers={"X-CV": "SMU"})) == "SMU"
    assert ent.entity_from_request(Req()) == "DA" and ent.explicit_entity(Req()) is None
    assert ent.entity_from_request(fm.FakeRequest()) == "DA"                # request tanpa query/header
    with pytest.raises(HTTPException) as e:
        ent.entity_from_request(Req(headers={"X-CV": "ALL"}))              # tulis + Gabungan
    assert e.value.status_code == 400 and "Gabungan" in e.value.detail
    assert ent.entity_from_request(Req(headers={"X-CV": "ALL"}), allow_all=True) == "ALL"
    with pytest.raises(HTTPException) as e:
        ent.entity_from_request(Req(query={"entity": "XX"}))
    assert e.value.status_code == 400 and "tidak dikenal" in e.value.detail


def test_saringan_da_mencakup_data_lama():
    docs = [{"id": 1, "entity": "DA"}, {"id": 2}, {"id": 3, "entity": "SMU"}]
    pick = lambda e: sorted(d["id"] for d in docs if fm.match(d, ent.entity_match(e)))  # noqa: E731
    assert pick("DA") == [1, 2] and pick("SMU") == [3] and pick("ALL") == [1, 2, 3]
    assert ent.matches_entity(None, "DA") and not ent.matches_entity(None, "SMU")


@pytest.mark.parametrize("code,anc,want", [
    ("1-1305", (), ["SMU"]), ("1-1305-KOH-01", (), ["SMU"]), ("4-1500", (), ["SMU"]), ("4-1500-003", (), ["SMU"]),
    ("4-1510", ("4-1500",), ["SMU"]), ("4-1590", (), ["SMU"]), ("2-1700", (), ["SMU"]), ("5-4200", (), ["SMU"]),
    ("1-1306", (), ["SMU"]),
    ("1-1303", (), ["DA"]), ("1-1303-SHP-01", (), ["DA"]), ("1-1304", (), ["DA"]), ("1-1401", (), ["DA"]),
    ("1-1405", (), ["DA"]), ("4-1111", (), ["DA"]), ("4-1200", (), ["DA"]), ("4-1300", (), ["DA"]),
    ("4-1400", (), ["DA"]), ("4-2300", (), ["DA"]), ("4-9200", (), ["DA"]), ("5-1100", (), ["DA"]),
    ("5-1900", (), ["DA"]), ("5-2100", (), ["DA"]), ("5-2200", (), ["DA"]), ("6-1110", (), ["DA"]),
    ("6-1210", (), ["DA"]), ("6-1300", (), ["DA"]), ("6-1410", (), ["DA"]), ("6-1510", (), ["DA"]),
    ("2-1150", (), ["DA"]), ("2-1120", (), ["DA"]), ("1-1630", (), ["DA"]), ("6-4300", (), ["DA"]),
    ("1-1201", (), ["DA", "SMU"]), ("2-1100", (), ["DA", "SMU"]), ("6-2900", (), ["DA", "SMU"]),
    ("2-1110-011", (), ["DA", "SMU"]), ("3-2000", (), ["DA", "SMU"]),
])
def test_aturan_kode_berlaku_untuk(code, anc, want):
    assert ent.code_rule_entities(code, anc) == want


def test_berlaku_untuk_tersimpan_dan_isian():
    assert ent.account_entities({"code": "6-2900", "entities": ["SMU"]}) == ["SMU"]       # isian menang
    assert ent.account_entities({"code": "4-1510", "parent_code": "4-1500"}) == ["SMU"]   # induk langsung
    assert ent.normalize_entities("keduanya") == ["DA", "SMU"] and ent.normalize_entities(["smu", "da"]) == ["DA", "SMU"]
    with pytest.raises(ValueError):
        ent.normalize_entities([])


def test_cv_modul_dan_dokumen_sumber():
    assert ent.entity_for_source_module("maklon_revenue") == "SMU"
    assert ent.entity_for_source_module("maklon_ar_invoice") == "SMU"
    assert ent.entity_for_source_module("expense") == "DA" and ent.entity_for_source_module(None) == "DA"
    assert ent.is_maklon_doc({"source_module": "maklon_po"}) and ent.is_maklon_doc({"linked_maklon_po_id": "p1"})
    assert not ent.is_maklon_doc({"cost_target": "maklon"})        # bahan maklon = stok DA (fase 2)
    assert ent.entity_of_doc({"entity": "smu"}) == "SMU" and ent.entity_of_doc({"source": "maklon"}) == "SMU"
    assert ent.entity_of_doc({}) == "DA"


def test_po_tanpa_jenis_internal_dan_akun_cmt(db):
    """Desain §9: PO tanpa business_type = INTERNAL (dulu `_cmt_expense_account` menganggapnya maklon)."""
    import routes.dewi_maklon_finance as dmf
    assert not ent.is_maklon_po({}) and ent.is_maklon_po({"business_type": "Maklon"})
    db.production_pos.docs += [{"id": "po-lama"}, {"id": "po-mkl", "business_type": "maklon"},
                               {"id": "po-int", "business_type": "internal"}]
    db.dewi_maklon_pos.docs += [{"id": "mp-1"}]
    mapping = {"debit_cmt_wip_internal": "1-1403", "debit_cmt_expense_maklon": "5-4200"}
    assert run(dmf._cmt_expense_account(db, {"po_id": "po-lama"}, mapping)) == ("1-1403", "internal")
    assert run(dmf._cmt_expense_account(db, {"po_id": "po-int"}, mapping)) == ("1-1403", "internal")
    assert run(dmf._cmt_expense_account(db, {"po_id": "po-mkl"}, mapping)) == ("5-4200", "maklon")
    assert run(dmf._cmt_expense_account(db, {"po_id": "mp-1"}, mapping)) == ("5-4200", "maklon")
    assert run(dmf.cmt_bill_entity(db, {"job_ids": ["j1"]})) == "DA"
    assert run(dmf.cmt_bill_entity(db, {"po_id": "po-mkl"})) == "SMU"


# ══════════════════════════════ jurnal manual (penjaga) ═══════════════════════════════
def _lines(dr, cr, amt=150_000):
    return [{"account_code": dr, "debit": amt, "credit": 0, "description": TAG},
            {"account_code": cr, "debit": 0, "credit": amt, "description": TAG}]


def test_jurnal_manual_sukma_menolak_akun_khusus_da(db):
    body = {"memo": TAG, "post": True, "lines": _lines("1-1213", "4-1100")}
    with pytest.raises(HTTPException) as e:
        run(rj.create_journal(Req(body, headers={"X-CV": "SMU"})))
    assert e.value.status_code == 400 and "4-1100" in e.value.detail and "CV Sukma" in e.value.detail


def test_jurnal_manual_menolak_rekening_cv_lain(db):
    body = {"memo": TAG, "post": True, "lines": _lines("1-1201", "4-1500")}
    with pytest.raises(HTTPException) as e:
        run(rj.create_journal(Req(body, headers={"X-CV": "SMU"})))
    assert "milik CV Dewi Aditya" in e.value.detail


def test_jurnal_manual_gabungan_ditolak(db):
    with pytest.raises(HTTPException) as e:
        run(rj.create_journal(Req({"memo": TAG, "lines": _lines("1-1213", "4-1500")}, headers={"X-CV": "ALL"})))
    assert e.value.status_code == 400 and "Gabungan" in e.value.detail


def test_jurnal_manual_sukma_bernomor_dan_berbuku_sukma(db):
    out = run(rj.create_journal(Req({"memo": TAG, "post": True, "lines": _lines("1-1213", "4-1500")},
                                    headers={"X-CV": "SMU"})))
    assert out["entity"] == "SMU" and out["je_number"].startswith("JE-SMU-")
    mirrored = db.rahaza_journal_lines.docs
    assert len(mirrored) == 2 and {m["entity"] for m in mirrored} == {"SMU"}
    da = run(rj.create_journal(Req({"memo": TAG, "post": True, "lines": _lines("1-1201", "4-1100")})))
    assert da["entity"] == "DA" and da["je_number"].startswith("JE-DA-")
    # daftar jurnal per CV: SMU hanya melihat jurnal SMU; DA juga melihat jurnal lama tanpa CV
    db.rahaza_journal_entries.docs.append({"id": "lama", "je_number": "JE-20260101-0001", "date": "2026-01-01",
                                           "status": "posted", "source_module": "manual"})
    kw = dict(from_date=None, to_date=None, status=None, source=None, limit=200, page=None, page_size=25,
              q=None, account_code=None)
    smu_rows = run(rj.list_journals(Req(headers={"X-CV": "SMU"}), **kw))
    da_rows = run(rj.list_journals(Req(headers={"X-CV": "DA"}), **kw))
    all_rows = run(rj.list_journals(Req(headers={"X-CV": "ALL"}), **kw))
    assert [r["entity"] for r in smu_rows] == ["SMU"]
    assert {r["id"] for r in da_rows} == {da["id"], "lama"} and len(all_rows) == 3


def test_nomor_jurnal_menyisipkan_cv_ke_format_owner(db):
    assert rp.je_prefix_with_entity("JE-20261107-", "SMU") == "JE-SMU-20261107-"
    assert rp.je_prefix_with_entity("JE-DA-20261107-", "DA") == "JE-DA-20261107-"
    assert rp.je_prefix_with_entity("X/2026/", "SMU") == "SMU-X/2026/"
    db.doc_number_configs.docs.append({"key": "rahaza_journal_entries.je_number", "active": True,
                                       "format": "JE-{YYYY}{MM}{DD}-{SEQ:4}", "mode": "auto"})
    counters.invalidate_format_cache()
    n = run(rp.gen_je_number(db, today_wib(), "SMU"))
    assert n.startswith(f"JE-SMU-{today_wib():%Y%m%d}-") and db._issued[-1].startswith("JE-SMU-")
    counters.invalidate_format_cache()


# ══════════════════════════════ jurnal otomatis ═══════════════════════════════════════
def test_jurnal_otomatis_maklon_masuk_sukma_dan_tidak_diblokir(db):
    res = run(rp._create_posted_je(db, today_wib(), f"{TAG} pendapatan", "maklon_revenue", "mk:1",
                                   _lines("1-1201", "4-1500"), USER))
    assert res["ok"] and res["entity"] == "SMU"
    je = db.rahaza_journal_entries.docs[-1]
    assert je["entity"] == "SMU" and "1-1201" in je["entity_warning"]          # rekening DA → ditandai saja
    assert {ln["entity"] for ln in db.rahaza_journal_lines.docs} == {"SMU"}
    res2 = run(rp._create_posted_je(db, today_wib(), TAG, "expense", "ex:1", _lines("6-2900", "1-1201"), USER))
    assert res2["entity"] == "DA" and "entity_warning" not in db.rahaza_journal_entries.docs[-1]
    res3 = run(rp._create_posted_je(db, today_wib(), TAG, "expense", "ex:2", _lines("6-2900", "1-1213"), USER,
                                    entity="SMU"))
    assert res3["entity"] == "SMU" and res3["je_number"].startswith("JE-SMU-")


def test_idempotensi_per_cv(db):
    run(rp._create_posted_je(db, today_wib(), TAG, "expense", "ref-x", _lines("6-2900", "1-1201"), USER))
    assert run(rp._find_existing_je(db, "expense", "ref-x", entity="SMU")) is None   # buku lain bebas (fase 2)
    assert run(rp._find_existing_je(db, "expense", "ref-x", entity="DA"))["entity"] == "DA"
    assert run(rp._find_existing_je(db, "expense", "ref-x")) is not None             # tanpa CV = perilaku lama
    db.rahaza_journal_entries.docs.append({"id": "old", "source_module": "ap_payment", "source_ref": "r-lama",
                                           "status": "posted"})
    assert run(rp._find_existing_je(db, "ap_payment", "r-lama", entity="DA"))["id"] == "old"


def test_indeks_idempotensi_berkunci_cv():
    src = (BACKEND / "migrations" / "ensure_indexes.py").read_text(encoding="utf-8")
    assert '[("source_module", 1), ("source_ref", 1), ("entity", 1)]' in src and "uniq_active_source_ref_entity" in src
    assert '[("entity", 1), ("period_code", 1)], unique=True' in src
    assert '_drop_index_if(db, "rahaza_periods", "period_code_1"' in src


# ══════════════════════════════ periode per CV ════════════════════════════════════════
def test_periode_per_cv(db):
    y = today_wib().year - 1
    db.rahaza_periods.docs += [{"id": f"da-{m}", "period_code": f"{y}-{m:02d}", "year": y, "month": m,
                                "status": "closed"} for m in range(1, 13)]           # data lama tanpa CV = DA
    assert run(rp.ensure_year_periods(db, y, "DA")) == 0
    assert run(rp.ensure_year_periods(db, y, "SMU")) == 12
    d = date(y, 6, 15)
    assert "sudah closed" in run(rp._ensure_period_open(db, d, entity="DA"))
    assert run(rp._ensure_period_open(db, d, entity="SMU")) is None
    code = f"{y}-06"
    out = run(rper.close_period(code, Req(headers={"X-CV": "SMU"})))
    assert out["entity"] == "SMU" and out["status"] == "closed"
    assert "CV Sukma" in run(rp._ensure_period_open(db, d, entity="SMU"))
    run(rper.reopen_period(code, Req(headers={"X-CV": "SMU"})))
    smu = [p for p in db.rahaza_periods.docs if p.get("entity") == "SMU" and p["period_code"] == code][0]
    assert smu["status"] == "open"
    rows = run(rper.list_periods(Req(headers={"X-CV": "SMU"}), year=y))
    assert len(rows) == 12 and {r["entity"] for r in rows} == {"SMU"}


# ══════════════════════════════ migrasi ═══════════════════════════════════════════════
def _migrasi():
    p = BACKEND / "scripts" / "migrations" / "2026_11_08_entitas_cv.py"
    spec = importlib.util.spec_from_file_location("mig_entitas_cv", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_migrasi_aturan_murni():
    m = _migrasi()
    assert m.cash_owner_rule({"gl_account_code": "1-1213"}) == "SMU"
    assert m.cash_owner_rule({"gl_account_code": "2-2103"}) == "SMU"
    assert m.cash_owner_rule({"gl_account_code": "1-1224", "name": "Bank BRI – CV Sukma Mitra Utama"}) == "SMU"
    assert m.cash_owner_rule({"gl_account_code": "1-1201", "name": "Bank BCA"}) == "DA"
    parent = {"4-1520": "4-1500", "4-1500": "4-1000"}
    assert m.coa_entities_for("4-1520", parent, {}) == ["SMU"]
    assert m.coa_entities_for("1-1201", {}, {"1-1201": "SMU"}) == ["SMU"]
    ents = {"4-1500": ["SMU"], "4-1100": ["DA"], "6-2900": ["DA", "SMU"]}
    je = lambda mod, *codes: {"source_module": mod, "lines": [{"account_code": c} for c in codes]}  # noqa: E731
    assert m.journal_entity(je("maklon_payment", "6-2900"), ents) == ("SMU", False)
    assert m.journal_entity(je("ar_payment", "6-2900", "4-1500"), ents) == ("SMU", False)
    assert m.journal_entity(je("expense", "6-2900"), ents) == ("DA", False)
    assert m.journal_entity(je("opening_balance", "4-1100", "4-1500"), ents) == ("DA", True)   # campur → DA


def test_migrasi_menulis_dan_idempoten():
    m = _migrasi()
    db = fm.FakeDB()
    db.rahaza_cash_accounts.docs += [{"id": "c1", "name": "BCA", "gl_account_code": "1-1201"},
                                     {"id": "c2", "name": "BCA Sukma Mitra", "gl_account_code": "1-1213"}]
    db.rahaza_coa_accounts.docs += [acc("1-1201"), acc("1-1213"), acc("4-1500", "REVENUE"),
                                    acc("4-1510", "REVENUE", parent="4-1500"), acc("4-1100", "REVENUE"),
                                    acc("6-2900", "EXPENSE")]
    db.rahaza_journal_entries.docs += [
        {"id": "j1", "source_module": "expense", "lines": [{"account_code": "6-2900"}, {"account_code": "1-1201"}]},
        {"id": "j2", "source_module": "manual", "lines": [{"account_code": "1-1213"}, {"account_code": "4-1510"}]},
        {"id": "j3", "source_module": "opening_balance",
         "lines": [{"account_code": "4-1100"}, {"account_code": "4-1500"}]},
    ]
    db.rahaza_journal_lines.docs += [{"id": "l1", "je_id": "j1"}, {"id": "l2", "je_id": "j2"},
                                     {"id": "l3", "je_id": "hilang"}]
    db.rahaza_periods.docs += [{"id": "p1", "period_code": "2026-10", "status": "closed"}]
    db.company_settings.docs += [{"id": "cs", "type": "general", "company_name": "CV Uji"}]
    db.rahaza_ar_invoices.docs += [{"id": "a1", "source_module": "maklon_po"}, {"id": "a2"}]

    async def steps(apply):
        ca = await m.step_cash_accounts(db, apply)
        co = await m.step_coa(db, apply, ca.pop("_owner_by_gl"))
        jr = await m.step_journals(db, apply, co.pop("_entities_by_code"))
        pr = await m.step_periods(db, apply)
        cs = await m.step_company(db, apply)
        iv = await m.step_invoices(db, apply)
        return ca, co, jr, pr, cs, iv
    ca, co, jr, pr, cs, iv = run(steps(False))
    assert (ca["to_DA"], ca["to_SMU"]) == (1, 1) and not any(d.get("entity") for d in db.rahaza_cash_accounts.docs)
    ca, co, jr, pr, cs, iv = run(steps(True))
    by = {d["id"]: d.get("entity") for d in db.rahaza_journal_entries.docs}
    assert by == {"j1": "DA", "j2": "SMU", "j3": "DA"} and jr["mixed"] == 1
    assert "entity_warning" in [d for d in db.rahaza_journal_entries.docs if d["id"] == "j3"][0]
    assert {d["id"]: d["entity"] for d in db.rahaza_journal_lines.docs} == {"l1": "DA", "l2": "SMU", "l3": "DA"}
    coa_by = {d["code"]: d["entities"] for d in db.rahaza_coa_accounts.docs}
    assert coa_by["1-1213"] == ["SMU"] and coa_by["1-1201"] == ["DA"] and coa_by["4-1510"] == ["SMU"]
    assert coa_by["6-2900"] == ["DA", "SMU"]
    assert sorted((p.get("entity"), p["status"]) for p in db.rahaza_periods.docs) == [("DA", "closed"), ("SMU", "closed")]
    smu = [d for d in db.company_settings.docs if d.get("entity") == "SMU"][0]
    assert smu["company_name"] == "CV Sukma Mitra Utama" and smu["npwp"] == "" and smu["tax_profile"]["pkp"] is False
    assert {d["id"]: d["entity"] for d in db.rahaza_ar_invoices.docs} == {"a1": "SMU", "a2": "DA"}
    # ulang = tidak ada yang berubah
    ca, co, jr, pr, cs, iv = run(steps(True))
    assert (ca["to_DA"], ca["to_SMU"], co["DA"] + co["SMU"] + co["both"], jr["journals_without_cv"],
            pr["copied_to_SMU"], cs["smu_created"]) == (0, 0, 0, 0, 0, 0)
    assert len(db.rahaza_periods.docs) == 2 and len(db.company_settings.docs) == 2


# ══════════════════════════════ profil, pajak, kop, transfer, Gabungan ═══════════════
def test_profil_pajak_dan_kop_per_cv():
    from core import pdf_template
    from core.tax_status import get_tax_profile
    db = fm.FakeDB()
    db.company_settings.docs += [{"type": "general", "company_name": "CV Dewi Aditya Official", "npwp": "1",
                                  "tax_profile": {"pkp": True, "pkp_since": "2026-01-01"}}]
    assert run(get_tax_profile(db))["pkp"] is True
    assert run(get_tax_profile(db, "SMU"))["pkp"] is False                 # Sukma belum ada profil: non-PKP
    prof = run(pdf_template.company_profile(db, "SMU"))
    assert prof["entity"] == "SMU" and prof["company_name"] == "CV Sukma Mitra Utama"
    hdr = {"company_name": "CV. Dewi Aditya", "address": "Alamat DA"}
    txt = pdf_template.effective_header_text(hdr, prof)
    assert txt["company_name"] == "CV Sukma Mitra Utama" and txt["address"] == ""   # identitas DA tidak bocor
    da = run(pdf_template.company_profile(db, "DA"))
    assert pdf_template.effective_header_text(hdr, da)["company_name"] == "CV. Dewi Aditya"
    db.company_settings.docs.append({"type": "cv_profile", "entity": "SMU", "company_name": "CV Sukma Uji",
                                     "npwp": "2", "tax_profile": {"pkp": True, "pkp_since": "2026-02-01"}})
    assert run(get_tax_profile(db, "SMU"))["pkp"] is True
    assert run(pdf_template.company_profile(db, "SMU"))["company_name"] == "CV Sukma Uji"


def test_pengaturan_perusahaan_per_cv(monkeypatch):
    import routes.admin as adm
    db = fm.FakeDB()
    db.company_settings.docs.append({"id": "g", "type": "general", "company_name": "CV DA Uji", "npwp": "9"})
    monkeypatch.setattr(adm, "get_db", lambda: db)
    monkeypatch.setattr(adm, "require_auth", _auth)
    monkeypatch.setattr(adm, "check_role", lambda u, roles: True)
    smu = run(adm.get_company_settings(Req(query={"entity": "SMU"})))
    assert smu["entity"] == "SMU" and smu["company_name"] == "CV Sukma Mitra Utama"
    run(adm.save_company_settings(Req({"company_name": f"CV Sukma {TAG}", "npwp": "01.234"}, query={"entity": "SMU"})))
    da = run(adm.get_company_settings(Req()))
    assert da["entity"] == "DA" and da["company_name"] == "CV DA Uji"           # profil DA tidak tersentuh
    assert run(adm.get_company_settings(Req(query={"entity": "SMU"})))["company_name"] == f"CV Sukma {TAG}"


def test_transfer_antar_cv_ditolak():
    import routes.rahaza_bank_transfers as bt
    db = fm.FakeDB()
    db.rahaza_cash_accounts.docs += [{"id": "a", "gl_account_code": "1-1201"},
                                     {"id": "b", "gl_account_code": "1-1213", "entity": "SMU"},
                                     {"id": "c", "gl_account_code": "1-1214", "entity": "SMU"}]
    with pytest.raises(HTTPException) as e:
        run(bt._owners_or_reject(db, "1-1201", "1-1213", None))
    assert "antar CV" in e.value.detail
    assert run(bt._owners_or_reject(db, "1-1213", "1-1214", None)) == "SMU"
    with pytest.raises(HTTPException):
        run(bt._owners_or_reject(db, "1-1213", "1-1214", "DA"))


def test_gabungan_hanya_dilihat_di_jaring_pengaman():
    from middleware.cv_readonly_guard import is_blocked
    assert is_blocked("POST", "/api/rahaza/journals", "ALL", None)
    assert is_blocked("DELETE", "/api/finance/bank-transfers/x", None, "all")
    assert not is_blocked("GET", "/api/rahaza/finance/reports/profit-loss", "ALL", None)
    assert not is_blocked("POST", "/api/rahaza/journals", "SMU", None)
    assert not is_blocked("POST", "/api/notifications/read", "ALL", None)


def test_laporan_laba_rugi_menyaring_buku(monkeypatch):
    import routes.rahaza_fin_reports as fr
    seen = []

    async def agg(_db, match):
        seen.append(match)
        return {}
    monkeypatch.setattr(fr, "_aggregate_by_account", agg)
    db = fm.FakeDB()
    for e in ("SMU", "DA", "ALL"):
        out = run(fr.compute_profit_loss(db, "2026-01-01", "2026-12-31", e))
        assert out["meta"]["entity"] == e
    assert seen[0]["entity"] == "SMU" and seen[1]["entity"] == {"$in": ["DA", None]} and "entity" not in seen[2]


def test_kas_bank_dan_hutang_per_cv():
    from core.payables import open_payable_rows
    db = fm.FakeDB()
    db.rahaza_ap_invoices.docs += [{"id": "ap1", "status": "sent", "total": 100, "balance": 100},
                                   {"id": "ap2", "status": "sent", "total": 50, "balance": 50, "entity": "SMU"}]
    db.production_pos.docs += [{"id": "pm", "business_type": "maklon"}, {"id": "pl"}]
    db.dewi_cmt_payments.docs += [{"id": "b1", "status": "posted", "net_amount": 70, "po_id": "pm"},
                                  {"id": "b2", "status": "posted", "net_amount": 30, "po_id": "pl"}]
    smu = run(open_payable_rows(db, entity="SMU"))
    da = run(open_payable_rows(db, entity="DA"))
    assert {r["id"] for r in smu} == {"ap2", "b1"} and {r["id"] for r in da} == {"ap1", "b2"}
    assert len(run(open_payable_rows(db))) == 4


# ══════════════════════════════ tarif jahit dari po_items ═════════════════════════════
def test_tarif_jahit_job_dari_po_items():
    db = fm.FakeDB()
    db.po_items.docs += [{"id": "pi1", "cmt_price_snapshot": 3000}, {"id": "pi2", "cmt_price_snapshot": 5000},
                         {"id": "pi0", "cmt_price_snapshot": 0}]
    assert run(rp.job_sewing_rate(db, {"id": "j1", "po_item_id": "pi1", "cmt_price_snapshot": 999})) == 3000
    db.production_job_items.docs += [{"job_id": "j2", "po_item_id": "pi1", "available_qty": 30},
                                     {"job_id": "j2", "po_item_id": "pi2", "available_qty": 10}]
    assert run(rp.job_sewing_rate(db, {"id": "j2"})) == 3500                     # tertimbang qty
    assert run(rp.job_sewing_rate(db, {"id": "j3", "po_item_id": "pi0", "cmt_price_snapshot": 1200})) == 1200
    assert run(rp.job_sewing_rate(db, {"id": "j4"})) == 0


# ══════════════════════════════ kontrak layar ═════════════════════════════════════════
def test_kontrak_layar_pemilih_cv():
    def src(rel):
        p = FE / rel
        if not p.exists():
            pytest.skip(f"berkas layar tidak ada: {rel}")
        return p.read_text(encoding="utf-8")
    lib = src("lib/entitas.js")
    assert "X-CV" in lib and "erp_keuangan_cv" in lib and "Gabungan (lihat saja)" in lib
    assert 'data-testid="cv-picker"' in src("components/erp/portal-shell/TopBar.jsx") or \
        "cv-picker" in src("components/erp/portal-shell/TopBar.jsx")
    assert "cv-readonly-hint" in src("components/erp/layout/PageLayout.jsx")
    assert "company-cv-switch" in src("components/erp/CompanySettingsModule.jsx")
    for rel in ("lib/entitas.js", "components/erp/layout/PageLayout.jsx", "components/erp/portal-shell/TopBar.jsx"):
        assert "<" + "select" not in src(rel)
