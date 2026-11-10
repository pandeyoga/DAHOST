"""Denda saat Tutup PO, dua arah (permintaan owner 9–10 Nov 2026) — hermetik (FakeDB, tanpa server).

Kata owner: "denda … ketika tutup po … dihitung per qty dari pesanan PO dikalikan nominal denda per pcs. denda bisa
memotong bon yang ada atau menerbitkan baru jika tidak ada bon" dan "client juga bisa memberikan denda, misal klien
retur klien mendenda dan da mendenda juga cmt namun nominal atau qty nya bisa berbeda".

Yang dikunci:
  * jumlah = qty × nominal per pcs, terpisah untuk klien dan CMT (qty/nominal boleh beda), alasan wajib;
  * denda klien (PO maklon): Dr 4-1590 / Cr piutang klien; sisa tagihan PO turun; kelebihan → uang muka klien;
  * denda CMT: Dr hutang vendor / Cr biaya CMT (maklon 5-4200, internal 5-1960); memotong tagihan CMT terbuka
    (PO ini dulu, lalu tagihan lain vendor itu di CV yang sama); sisanya terbuka dan memotong tagihan berikutnya;
  * ditolak SEBELUM PO tertutup: klien pada PO internal, vendor tim CV sendiri, tanpa alasan, denda ganda;
  * profil posting `po_denda`, koleksi & nomor terdaftar, layar Tutup PO punya isian dua denda.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeRequest  # noqa: E402
import routes.coa_auto as coa_auto  # noqa: E402
import routes.production_pos as ppos  # noqa: E402
import routes.production_maklon_bridge as bridge  # noqa: E402
import utils.counters as counters  # noqa: E402
from core import denda_po  # noqa: E402
from core import maklon_ledger as ml  # noqa: E402
import test_tahap2_maklon as t2  # noqa: E402

# fikstur & pembantu dipakai ulang dari uji Tahap 2 maklon (FakeDB + jurnal palsu yang memeriksa keseimbangan)
env = t2.env
run, USER, FIN = t2.run, t2.USER, t2.FIN
_confirm, _ar, _dispatch, _je_lines, _to_production_complete = (
    t2._confirm, t2._ar, t2._dispatch, t2._je_lines, t2._to_production_complete)

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def denv(env, monkeypatch):
    db = env["db"]
    db.rahaza_coa_accounts.docs += [
        {"code": c, "name": n, "type": t, "is_group": False, "active": True}
        for c, n, t in (("4-1590", "Retur / Potongan Maklon", "REVENUE"), ("5-1960", "Selisih Produksi", "COGS"))]
    seq = {}

    async def nomor(_db, coll, field, prefix, width=4, ctx=None, config_key=None):
        seq[prefix] = seq.get(prefix, 0) + 1
        return f"{prefix}{seq[prefix]:0{width}d}"

    async def ap_cmt(_db, vid, name="", user=None):
        return "2-1110"

    monkeypatch.setattr(counters, "gen_prefixed_number", nomor)
    monkeypatch.setattr(coa_auto, "resolve_ap_account_for_cmt", ap_cmt)
    return env


def _siap_tutup(db):
    """PO maklon terkonfirmasi, 100 pcs terkirim & diterima klien (tertagih Rp 2.000.000), produksi selesai."""
    _confirm(db)
    _dispatch(db, "sj1", 1, "pi-s", 50, received=50)
    _dispatch(db, "sj1", 1, "pi-m", 50, received=50)
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    _to_production_complete(db)


def _bill(bid, po_id, net, paid=0, entity="SMU", created="2026-11-01"):
    return {"id": bid, "payment_code": f"PAY-CMT-{bid}", "po_id": po_id, "po_number": f"PO-{po_id}", "vendor_id": "v1",
            "subtotal": net, "net_amount": net, "total_amount": net, "paid_amount": paid, "status": "posted",
            "gl_je_id": "x", "entity": entity, "created_at": created}


def _denda_je(env, pihak):
    return next(j for j in env["jes"] if j["source_module"] == "po_denda" and pihak in j["memo"])


# ══════════════════════════════ hitungan murni ══════════════════════════════
def test_jumlah_qty_kali_nominal_dan_alasan_wajib():
    out = denda_po.parse_input({"denda": {"klien": {"qty": 20, "per_pcs": 5000, "alasan": "retur 20 pcs"},
                                          "cmt": {"qty": 100, "per_pcs": 1500.5, "alasan": "jahitan lepas"}}})
    assert out["klien"]["jumlah"] == 100000 and out["cmt"]["jumlah"] == 150050
    assert denda_po.parse_input({"denda": {"cmt": {"qty": 100, "per_pcs": 0, "alasan": ""}}}) == {}   # nominal 0 = tanpa denda
    for bad in ({"qty": 0, "per_pcs": 100, "alasan": "abc"}, {"qty": 5, "per_pcs": 100, "alasan": ""}):
        with pytest.raises(HTTPException) as e:
            denda_po.parse_input({"denda": {"cmt": bad}})
        assert e.value.status_code == 400 and "Denda ke CMT" in e.value.detail
    assert denda_po.qty_pesanan([{"qty": 50}, {"qty": 50}, {"qty": None}]) == 100
    assert denda_po.alokasi(700, [{"id": "a", "bisa": 500}, {"id": "b", "bisa": 0}, {"id": "c", "bisa": 300}]) == \
        [("a", 500), ("c", 200)]


# ══════════════════════════════ PO maklon: dua denda, nominal & qty berbeda ══════════════════════════════
def test_tutup_po_maklon_dengan_denda_klien_dan_cmt(denv):
    env = denv
    db = env["db"]
    _siap_tutup(db)
    db.production_pos.docs.append({"id": "po2", "po_number": "PO-MKL-2", "business_type": "maklon", "status": "Closed"})
    db.dewi_cmt_payments.docs = [_bill("b-lain", "po2", 300000, created="2026-10-01"),   # tagihan PO lain (lebih tua)
                                 _bill("b-po1", "po1", 600000, paid=100000)]
    out = run(ppos.close_po("po1", FakeRequest({"close_notes": "selesai", "denda": {
        "klien": {"qty": 20, "per_pcs": 5000, "alasan": "klien retur 20 pcs, denda Rp 5.000/pcs"},
        "cmt": {"qty": 100, "per_pcs": 6000, "alasan": "jahitan lepas, ikut retur klien"}}})))
    assert out["status"] == "Closed" and db.production_pos.docs[0]["status"] == "Closed"
    d = {x["pihak"]: x for x in out["denda"]}

    # klien → DA: Dr potongan maklon / Cr piutang klien; sisa tagihan PO turun
    assert d["klien"]["nomor"] == "DND-KLN-00001" and d["klien"]["jumlah"] == 100000
    assert _je_lines(_denda_je(env, "Denda dari klien")) == {("4-1590", "D"): 100000.0, ("1-1305-KOH-01", "C"): 100000.0}
    ar = _ar(db)
    assert ar["denda_credit"] == 100000 and ar["amount_due"] == 1_900_000
    assert d["klien"]["status"] == "lunas" and d["klien"]["jumlah_dipotong"] == 100000

    # DA → CMT: Dr hutang vendor / Cr biaya CMT maklon; tagihan PO ini dulu, lalu tagihan lain vendor itu
    assert d["cmt"]["nomor"] == "DND-CMT-00001" and d["cmt"]["jumlah"] == 600000
    assert _je_lines(_denda_je(env, "Denda ke CMT")) == {("2-1110", "D"): 600000.0, ("5-4200", "C"): 600000.0}
    bills = {b["id"]: b for b in db.dewi_cmt_payments.docs}
    assert bills["b-po1"]["net_amount"] == 100000 and ml.cmt_bill_payable(bills["b-po1"]) == 0
    assert bills["b-lain"]["net_amount"] == 200000 and bills["b-lain"]["outstanding_amount"] == 200000
    assert [p["jumlah"] for p in bills["b-po1"]["potongan_denda"]] == [500000]
    assert [(p["nomor"], p["jumlah"]) for p in d["cmt"]["potongan"]] == [("PAY-CMT-b-po1", 500000), ("PAY-CMT-b-lain", 100000)]
    assert d["cmt"]["status"] == "lunas" and d["cmt"]["sisa"] == 0
    rows = run(ppos.list_po_denda(FakeRequest(), po_id="po1"))
    assert {r["pihak"] for r in rows} == {"klien", "cmt"}


def test_denda_cmt_tanpa_bon_terbuka_lalu_memotong_tagihan_berikutnya(denv):
    env = denv
    db = env["db"]
    _siap_tutup(db)
    db.dewi_cmt_payments.docs = [_bill("b-dibayar", "po1", 200000, paid=200000),
                                 _bill("b-cv-lain", "po9", 900000, entity="DA")]          # CV lain: tidak dipotong
    out = run(ppos.close_po("po1", FakeRequest({"denda": {"cmt": {"qty": 100, "per_pcs": 1000, "alasan": "telat kirim"}}})))
    d = out["denda"][0]
    assert d["status"] == "terbuka" and d["sisa"] == 100000 and d["potongan"] == []
    assert db.dewi_cmt_payments.docs[1]["net_amount"] == 900000
    # tagihan baru vendor itu lahir (lolos QC PO lain di CV yang sama) → sisa denda memotongnya
    db.dewi_cmt_payments.docs.append(_bill("b-baru", "po3", 70000, created="2026-11-20"))
    hasil = run(denda_po.potong_tagihan_baru(db, "b-baru", USER))
    assert hasil == [{"nomor": "DND-CMT-00001", "dipotong": 70000}]
    doc = db.dewi_po_denda.docs[0]
    assert (doc["status"], doc["sisa"], doc["potongan"][-1]["saat"]) == ("sebagian", 30000, "tagihan_baru")
    assert db.dewi_cmt_payments.docs[-1]["net_amount"] == 0


def test_denda_klien_melebihi_sisa_tagihan_jadi_uang_muka_klien(denv):
    env = denv
    db = env["db"]
    _siap_tutup(db)
    run(ml.record_client_payment(db, _ar(db)["id"], amount=2_000_000, cash_account_id="kas1", payment_date=None, user=FIN))
    out = run(ppos.close_po("po1", FakeRequest({"denda": {"klien": {"qty": 30, "per_pcs": 10000, "alasan": "retur 30 pcs"}}})))
    d = out["denda"][0]
    assert d["jumlah"] == 300000 and d["jumlah_dipotong"] == 0 and d["kredit_klien"] == 300000
    assert d["status"] == "kredit_klien" and d["sisa"] == 0
    ar = _ar(db)
    assert ar["amount_due"] == 0 and ar["advance_balance"] == 300000          # kelebihan = kredit/uang muka klien
    balik = env["jes"][-1]
    assert _je_lines(balik) == {("1-1305-KOH-01", "D"): 300000.0, ("2-1700", "C"): 300000.0}


def test_denda_cmt_po_internal_ke_selisih_produksi(denv, monkeypatch):
    env = denv
    db = env["db"]
    db.production_pos.docs[0].update({"business_type": "internal", "status": "Production Complete"})
    db.dewi_cmt_payments.docs = [_bill("b1", "po1", 400000, entity="DA")]

    async def penuh(_db, _po_id):
        return {"qty_short": 0, "lines": [], "total_ordered": 100}
    monkeypatch.setattr(bridge, "compute_po_fulfillment", penuh)
    out = run(ppos.close_po("po1", FakeRequest({"denda": {"cmt": {"qty": 80, "per_pcs": 2500, "alasan": "reject final"}}})))
    d = out["denda"][0]
    assert d["entity"] == "DA" and d["jumlah"] == 200000 and d["status"] == "lunas"
    assert _je_lines(_denda_je(env, "Denda ke CMT")) == {("2-1110", "D"): 200000.0, ("5-1960", "C"): 200000.0}


@pytest.mark.parametrize("ubah,denda,pesan", [
    ({"business_type": "internal"}, {"klien": {"qty": 1, "per_pcs": 1000, "alasan": "retur"}}, "hanya untuk PO maklon"),
    ({}, {"cmt": {"qty": 1, "per_pcs": 1000, "alasan": ""}}, "alasan wajib"),
    ({"vendor_id": ""}, {"cmt": {"qty": 1, "per_pcs": 1000, "alasan": "telat"}}, "belum punya vendor CMT"),
])
def test_denda_ditolak_sebelum_po_tertutup(denv, monkeypatch, ubah, denda, pesan):
    db = denv["db"]
    _siap_tutup(db)
    db.production_pos.docs[0].update(ubah)

    async def penuh(_db, _po_id):
        return {"qty_short": 0, "lines": [], "total_ordered": 100}
    monkeypatch.setattr(bridge, "compute_po_fulfillment", penuh)
    with pytest.raises(HTTPException) as e:
        run(ppos.close_po("po1", FakeRequest({"denda": denda})))
    assert e.value.status_code == 400 and pesan in e.value.detail
    assert db.production_pos.docs[0]["status"] == "Production Complete" and not db.dewi_po_denda.docs


def test_denda_vendor_tim_cv_sendiri_dan_ganda_ditolak(denv):
    db = denv["db"]
    _siap_tutup(db)
    db.vendor_partners.docs[0]["owner_entity"] = "SMU"
    with pytest.raises(HTTPException) as e:
        run(ppos.close_po("po1", FakeRequest({"denda": {"cmt": {"qty": 5, "per_pcs": 1000, "alasan": "telat"}}})))
    assert "tim jahit CV sendiri" in e.value.detail and db.production_pos.docs[0]["status"] == "Production Complete"
    db.vendor_partners.docs[0]["owner_entity"] = None
    db.dewi_po_denda.docs = [{"id": "x", "po_id": "po1", "pihak": "cmt", "status": "terbuka", "nomor": "DND-CMT-00009"}]
    with pytest.raises(HTTPException) as e:
        run(ppos.close_po("po1", FakeRequest({"denda": {"cmt": {"qty": 5, "per_pcs": 1000, "alasan": "telat"}}})))
    assert "sudah tercatat" in e.value.detail


# ══════════════════════════════ registrasi & layar ══════════════════════════════
def test_profil_koleksi_nomor_terdaftar():
    from core.collection_registry import REGISTRY
    from data.doc_number_registry import REGISTRY_BY_KEY as K
    import routes.rahaza_posting_profiles as prof
    assert REGISTRY["dewi_po_denda"] == "produksi"
    assert K["dewi_po_denda.nomor_klien"]["default_format"].startswith("DND-KLN-")
    assert K["dewi_po_denda.nomor_cmt"]["default_format"].startswith("DND-CMT-")
    p = next(x for x in prof.DEFAULT_PROFILES if x["event_type"] == "po_denda")
    assert p["mapping"] == denda_po.DEFAULT_MAPPING
    assert prof.role_family("po_denda", "debit_denda_klien") == "revenue"
    assert prof.role_family("po_denda", "credit_denda_cmt_maklon") == "expense"


def test_layar_tutup_po_punya_dua_denda():
    erp = REPO / "frontend" / "src" / "components" / "erp"
    form = (erp / "engine" / "DendaTutupPO.jsx").read_text(encoding="utf-8")
    for frag in ("Denda dari klien", "Denda ke CMT", "per_pcs", "alasan", "qty"):
        assert frag in form, frag
    for f in ("engine/POClosureModule.jsx", "engine/ProductionPOModule.jsx"):
        src = (erp / f).read_text(encoding="utf-8")
        assert "DendaTutupPO" in src and "denda:" in src, f
