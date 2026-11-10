"""Nota aksesoris ke vendor CMT (permintaan owner 10–11 Nov 2026) — hermetik (FakeDB, jurnal palsu yang seimbang).

Kata owner: "aksesoris yang dikirimkan ke CMT itu dibeli oleh cmt, jadi tolong buatkan nota invoicenya. untuk
nominalnya harganya berapa bisa diinputkan saja langsung di portal produksi dan maklon. pembayaranya bisa potong
hutang atau dibayar langsung." Keputusan 11 Nov: semua aksesoris ke CMT luar masuk nota, harga diketik tiap kiriman
(0 = gratis, tidak terisi otomatis, HPP tampil sebagai acuan), penerbit selalu CV Dewi Aditya, aksesoris tetap di HPP
PO, nilai nota = pendapatan lain-lain.

Yang dikunci:
  * harga per satuan serah × qty serah; HPP per satuan serah = nilai stok × isi kemasan (acuan, tidak dijurnal);
  * terbit: Dr Piutang Vendor CMT (sub-ledger vendor) / Cr 4-9400 di buku DA; nota = dokumen piutang biasa;
  * potong tagihan: tagihan DA → Dr hutang CMT / Cr piutang CMT; tagihan CV Sukma → pasangan antar CV;
    tanpa tagihan → menunggu dan memotong tagihan berikutnya yang lahir (sesudah denda);
  * tim jahit CV sendiri tidak dibuatkan nota; semua harga 0 → tidak ada nota (kiriman ditandai gratis);
  * batal hanya bila belum dibayar/dipotong; harga kosong ditolak SEBELUM stok dipotong;
  * profil posting, sub-ledger, nomor, layar Produksi = Maklon (satu form), portal vendor & Keuangan.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402
from core import denda_po  # noqa: E402
from core import intercompany as ic  # noqa: E402
from core import nota_aksesoris_cmt as nac  # noqa: E402

REPO = HERE.parents[2]
USER = {"id": "u-nac", "name": "Admin UJI-NAC", "role": "admin"}
AR_SUB, AP_SUB = "1-1307-CMT01", "2-1110-CMT01"
IC_DA_AR, IC_SMU_AP = "1-1301-SMU", "2-1100-DA"


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def _db():
    d = FakeDB()
    d.vendor_partners.docs = [{"id": "v1", "code": "CMT01", "name": "CMT Sejahtera", "active": True},
                              {"id": "vsgo", "code": "SGO", "name": "Sukma Garmindo", "active": True,
                               "owner_entity": "SMU"}]
    d.production_pos.docs = [{"id": "PO1", "po_number": "PO-UJI-1", "business_type": "internal", "vendor_id": "v1"},
                             {"id": "PO2", "po_number": "PO-UJI-2", "business_type": "maklon", "vendor_id": "v1"}]
    d.rahaza_coa_accounts.docs = [{"code": c, "name": c, "type": t, "is_group": g, "active": True} for c, t, g in (
        ("1-1300", "ASSET", True), ("4-0000", "OTHER_INCOME", True), (AR_SUB, "ASSET", False),
        (AP_SUB, "LIABILITY", False), (IC_DA_AR, "ASSET", False), (IC_SMU_AP, "LIABILITY", False))]
    return d


@pytest.fixture
def env(monkeypatch):
    import auth
    import routes.coa_auto as coa_auto
    import routes.rahaza_posting as rp
    import routes.rahaza_posting_profiles as profiles
    import utils.counters as counters
    db = _db()
    jes = []

    async def create_je(_db, je_date=None, memo="", source_module="", source_ref="", lines_raw=None, user=None,
                        entity=None, labels=None, **_k):
        codes = {a["code"]: a for a in db.rahaza_coa_accounts.docs}
        for ln in lines_raw:
            acc = codes.get(ln["account_code"])
            if not acc or acc.get("is_group"):
                return {"ok": False, "error": f"akun {ln['account_code']} tidak sah"}
        d = round(sum(float(x.get("debit") or 0) for x in lines_raw), 2)
        c = round(sum(float(x.get("credit") or 0) for x in lines_raw), 2)
        assert d == c, (d, c, lines_raw)
        je = {"id": f"je{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1:04d}", "source_module": source_module,
              "source_ref": source_ref, "status": "posted", "entity": entity, "labels": labels or {}, "memo": memo,
              "lines": lines_raw}
        jes.append(je)
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}

    async def void_je(_db, module, ref, user, reason="", entity=None):
        hit = [j for j in jes if j["source_module"] == module and j["source_ref"] == ref and j["status"] == "posted"
               and (entity is None or j["entity"] == entity)]
        for j in hit:
            j["status"] = "voided"
        return {"ok": True, "voided": bool(hit)}

    async def mapping(_db, et):
        return {}

    async def sub(_db, et, entity_id=None, entity_name=None, user=None, **_k):
        assert et == nac.SUBLEDGER_TYPE
        return AR_SUB if entity_id == "v1" else None

    async def ap(_db, vid, name="", user=None):
        return AP_SUB

    seq = {}

    async def nomor(_db, coll, field, prefix, width=4, ctx=None, config_key=None):
        seq[prefix] = seq.get(prefix, 0) + 1
        return f"{prefix}{seq[prefix]:0{width}d}"

    async def ic_accs(_db, user=None, **_k):
        return {"DA": {"ar": IC_DA_AR, "ap": None}, "SMU": {"ar": None, "ap": IC_SMU_AP}}

    async def no_close(*_a, **_k):
        return None

    monkeypatch.setattr(rp, "_create_posted_je", create_je)
    monkeypatch.setattr(rp, "_void_je_by_source", void_je)
    monkeypatch.setattr(profiles, "get_mapping", mapping)
    monkeypatch.setattr(coa_auto, "resolve_subledger_account", sub)
    monkeypatch.setattr(coa_auto, "resolve_ap_account_for_cmt", ap)
    monkeypatch.setattr(counters, "gen_prefixed_number", nomor)
    monkeypatch.setattr(ic, "ic_accounts", ic_accs)
    monkeypatch.setattr(ic, "precheck_period", no_close)
    monkeypatch.setattr(auth, "log_activity", _noop)
    return {"db": db, "jes": jes}


def _lines(je):
    out = {}
    for ln in je["lines"]:
        if float(ln.get("debit") or 0):
            out[(ln["account_code"], "D")] = float(ln["debit"])
        if float(ln.get("credit") or 0):
            out[(ln["account_code"], "C")] = float(ln["credit"])
    return out


def _ship(db, sid="SJ1", po="PO1", vendor="v1"):
    s = {"id": sid, "shipment_number": f"SHP-{sid}", "po_id": po, "po_number": f"PO-UJI-{po[-1]}", "vendor_id": vendor,
         "vendor_name": "CMT Sejahtera", "shipment_type": "NORMAL", "business_type": "internal"}
    db.vendor_shipments.docs.append(dict(s))
    return s


def _bill(bid, po_id, net, entity="DA", paid=0, created="2026-11-12"):
    return {"id": bid, "payment_code": f"PAY-CMT-{bid}", "po_id": po_id, "po_number": f"PO-{po_id}", "vendor_id": "v1",
            "subtotal": net, "net_amount": net, "total_amount": net, "paid_amount": paid, "status": "posted",
            "entity": entity, "created_at": created}


# hitungan kiriman: kancing 3 gross (isi 144, nilai stok Rp 50/pcs) + renda 2 roll (isi 50 m, Rp 1.000/m)
CALC_AKS = [
    {"key": "KCG", "material_id": "KCG", "code": "A-KCG", "name": "Kancing", "qty_handover": 3, "handover_uom": "gross",
     "handover_label": "gross isi 144 pcs", "handover_factor": 144, "unit_cost": 50.0, "qty_base": 432, "usage_unit": "pcs"},
    {"key": "REN", "material_id": "REN", "code": "A-REN", "name": "Renda", "qty_handover": 2, "handover_uom": "roll",
     "handover_label": "roll isi 50 m", "handover_factor": 50, "unit_cost": 1000.0, "qty_base": 100, "usage_unit": "m"},
    {"key": "LBL", "material_id": "LBL", "code": "A-LBL", "name": "Label", "qty_handover": 0, "handover_label": "pcs",
     "handover_factor": 1, "unit_cost": 100.0},
]


def _harga(kcg=8000, ren=55000, cara="langsung"):
    return nac.parse_input({"cara_bayar": cara, "harga": [{"key": "KCG", "harga": kcg}, {"key": "REN", "harga": ren}]})


# ══════════════════════════════ hitungan murni ══════════════════════════════
def test_harga_diketik_per_satuan_serah_dan_hpp_hanya_acuan():
    inp = _harga()
    assert inp == {"cara_bayar": "langsung", "harga": {"KCG": 8000.0, "REN": 55000.0}}
    lines = nac.baris_dari_hitungan(CALC_AKS, inp["harga"])
    assert [(x["name"], x["qty"], x["unit_label"], x["harga"], x["jumlah"], x["hpp_satuan"]) for x in lines] == [
        ("Kancing", 3.0, "gross isi 144 pcs", 8000.0, 24000.0, 7200.0),      # HPP 50 × 144 = 7.200 per gross
        ("Renda", 2.0, "roll isi 50 m", 55000.0, 110000.0, 50000.0)]          # baris qty 0 tidak masuk nota
    # harga tidak terisi otomatis: baris tanpa harga dilaporkan namanya; 0 = gratis (sah)
    assert nac.belum_berharga(CALC_AKS, {"KCG": 0.0}) == ["Renda"]
    assert nac.belum_berharga(CALC_AKS, inp["harga"]) == []
    assert nac.parse_input(None) is None                                      # klien lama: tanpa nota
    for bad in ({"cara_bayar": "kredit"}, {"harga": [{"key": "KCG", "harga": -1}]}, {"harga": [{"key": "K", "harga": "x"}]}):
        with pytest.raises(HTTPException):
            nac.parse_input(bad)
    assert nac.parse_input({"harga": [{"key": "KCG", "harga": ""}]})["harga"] == {}   # kosong = belum diisi
    assert nac.status_bayar(100, 0) == "issued" and nac.status_bayar(100, 40) == "partial_paid"
    assert nac.status_bayar(100, 100) == "paid"


# ══════════════════════════════ terbit ══════════════════════════════
def test_nota_terbit_piutang_cmt_dan_pendapatan_lain_buku_da(env):
    db, jes = env["db"], env["jes"]
    s = _ship(db)
    doc = run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                       cara_bayar="langsung", user=USER))
    assert doc["invoice_number"] == "NAC-00001" and doc["total"] == 134000.0 and doc["balance"] == 134000.0
    assert (doc["entity"], doc["source_module"], doc["vendor_id"], doc["customer_name"]) == ("DA", "cmt_accessory", "v1",
                                                                                           "CMT Sejahtera")
    assert doc["status"] == "issued" and doc["gl_ar_account_code"] == AR_SUB and doc["po_number"] == "PO-UJI-1"
    assert len(jes) == 1 and jes[0]["entity"] == "DA" and jes[0]["source_module"] == "cmt_accessory_note"
    assert _lines(jes[0]) == {(AR_SUB, "D"): 134000.0, ("4-9400", "C"): 134000.0}
    # nota = dokumen piutang biasa (tampil di Keuangan › Piutang) + jejak di kiriman
    assert db.rahaza_ar_invoices.docs[0]["id"] == doc["id"]
    ship = db.vendor_shipments.docs[0]
    assert ship["nota_aksesoris_number"] == "NAC-00001" and ship["nota_aksesoris_status"] == "terbit"
    # akun 1-1307 & 4-9400 dibuat bila belum ada (buku DA)
    made = {a["code"]: a for a in db.rahaza_coa_accounts.docs}
    assert made["1-1307"]["type"] == "ASSET" and made["4-9400"]["type"] == "OTHER_INCOME"
    assert made["4-9400"]["entities"] == ["DA"]
    with pytest.raises(HTTPException) as e:                                   # satu nota aktif per kiriman
        run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                     cara_bayar="langsung", user=USER))
    assert "sudah punya nota" in e.value.detail


def test_semua_gratis_tidak_ada_nota_dan_tim_sendiri_tidak_dijual(env):
    db, jes = env["db"], env["jes"]
    s = _ship(db)
    assert run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, {"KCG": 0, "REN": 0}),
                        cara_bayar="langsung", user=USER)) is None
    assert jes == [] and db.vendor_shipments.docs[0]["nota_aksesoris_status"] == "gratis"
    b = run(nac.berlaku(db, vendor_id="vsgo"))
    assert not b["berlaku"] and "tim jahit CV sendiri" in b["alasan"]
    s2 = _ship(db, "SJ2", vendor="vsgo")
    with pytest.raises(HTTPException):
        run(nac.buat(db, shipment=s2, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                     cara_bayar="langsung", user=USER))
    assert not run(nac.berlaku(db, vendor_id="v1", shipment={"opening": True}))["berlaku"]   # saldo awal cutoff


# ══════════════════════════════ potong tagihan jahit ══════════════════════════════
def test_potong_tagihan_da_po_ini_dulu_lalu_terlama(env):
    db, jes = env["db"], env["jes"]
    db.dewi_cmt_payments.docs = [_bill("lama", "POX", 100000, created="2026-11-01"),
                                 _bill("po1", "PO1", 60000, created="2026-11-10")]
    s = _ship(db)
    doc = run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                       cara_bayar="potong_tagihan", user=USER))
    # 134.000 → tagihan PO ini 60.000 dulu, lalu tagihan terlama 74.000
    assert [(p["nomor"], p["jumlah"], p["entity"]) for p in doc["potongan"]] == [
        ("PAY-CMT-po1", 60000.0, "DA"), ("PAY-CMT-lama", 74000.0, "DA")]
    assert (doc["paid_amount"], doc["balance"], doc["status"], doc["jumlah_dipotong"]) == (134000.0, 0.0, "paid", 134000.0)
    offs = [j for j in jes if j["source_module"] == "cmt_accessory_offset"]
    assert [_lines(j) for j in offs] == [{(AP_SUB, "D"): 60000.0, (AR_SUB, "C"): 60000.0},
                                        {(AP_SUB, "D"): 74000.0, (AR_SUB, "C"): 74000.0}]
    bills = {b["id"]: b for b in db.dewi_cmt_payments.docs}
    assert bills["po1"]["net_amount"] == 0.0 and bills["lama"]["net_amount"] == 26000.0
    assert bills["lama"]["nota_aksesoris_dipotong"] == 74000.0 and "denda_dipotong" not in bills["lama"]
    assert bills["lama"]["potongan_nota_aksesoris"][0]["nomor"] == "NAC-00001"
    assert bills["lama"]["subtotal"] == 100000                              # HPP PO membaca subtotal: tidak berubah
    with pytest.raises(HTTPException):                                      # sudah memotong → tidak bisa dibatalkan
        run(nac.batal(db, doc["id"], USER, "salah harga"))


def test_tagihan_cv_sukma_dipotong_lewat_pasangan_antar_cv(env):
    db, jes = env["db"], env["jes"]
    db.dewi_cmt_payments.docs = [_bill("mk", "PO2", 500000, entity="SMU")]
    s = _ship(db, po="PO2")
    doc = run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                       cara_bayar="potong_tagihan", user=USER))
    assert doc["entity"] == "DA" and doc["status"] == "paid" and doc["potongan"][0]["antar_cv"] is True
    smu, da = [j for j in jes if j["source_module"] == "cmt_accessory_offset"]
    assert smu["entity"] == "SMU" and _lines(smu) == {(AP_SUB, "D"): 134000.0, (IC_SMU_AP, "C"): 134000.0}
    assert da["entity"] == "DA" and _lines(da) == {(IC_DA_AR, "D"): 134000.0, (AR_SUB, "C"): 134000.0}
    for j, lawan in ((smu, "DA"), (da, "SMU")):
        assert j["labels"]["intercompany"] and j["labels"]["counterparty_entity"] == lawan
        assert j["labels"]["ic_kind"] == ic.KIND_CMT_ACCESSORY_OFFSET
    assert db.dewi_cmt_payments.docs[0]["net_amount"] == 366000.0


def test_tanpa_tagihan_menunggu_lalu_memotong_tagihan_berikutnya(env):
    db, jes = env["db"], env["jes"]
    s = _ship(db)
    doc = run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                       cara_bayar="potong_tagihan", user=USER))
    assert doc["status"] == "issued" and doc["potongan"] == [] and len(jes) == 1
    # nota "dibayar langsung" tidak ikut dipotong otomatis
    s2 = _ship(db, "SJ2")
    tunai = run(nac.buat(db, shipment=s2, lines=nac.baris_dari_hitungan(CALC_AKS, {"KCG": 1000, "REN": 0}),
                         cara_bayar="langsung", user=USER))
    db.dewi_cmt_payments.docs = [_bill("baru", "PO1", 100000)]
    hasil = run(nac.potong_tagihan_baru(db, "baru", USER))
    assert hasil == [{"nomor": "NAC-00001", "dipotong": 100000.0}]
    n1 = next(x for x in db.rahaza_ar_invoices.docs if x["id"] == doc["id"])
    assert (n1["paid_amount"], n1["balance"], n1["status"]) == (100000.0, 34000.0, "partial_paid")
    assert next(x for x in db.rahaza_ar_invoices.docs if x["id"] == tunai["id"])["paid_amount"] == 0.0
    assert db.dewi_cmt_payments.docs[0]["net_amount"] == 0.0
    # tagihan berikutnya memotong sisanya; nota tunai bisa dipotong manual ("Potong dari tagihan jahit")
    db.dewi_cmt_payments.docs.append(_bill("baru2", "PO1", 50000))
    run(nac.potong_tagihan_baru(db, "baru2", USER))
    assert next(x for x in db.rahaza_ar_invoices.docs if x["id"] == doc["id"])["status"] == "paid"
    t2 = run(nac.potong_sekarang(db, tunai["id"], USER))
    assert t2["status"] == "paid" and t2["cara_bayar"] == "potong_tagihan" and t2["potongan"][0]["jumlah"] == 3000.0
    assert db.dewi_cmt_payments.docs[1]["net_amount"] == 50000 - 34000 - 3000


def test_tagihan_baru_dipotong_denda_dulu_lalu_nota(env, monkeypatch):
    db = env["db"]
    s = _ship(db)
    run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                 cara_bayar="potong_tagihan", user=USER))
    db.dewi_cmt_payments.docs = [_bill("b", "PO1", 150000)]
    db.dewi_po_denda.docs = [{"id": "d1", "nomor": "DND-CMT-00001", "pihak": "cmt", "pihak_id": "v1", "entity": "DA",
                              "jumlah": 30000.0, "jumlah_dipotong": 0.0, "sisa": 30000.0, "potongan": [],
                              "status": "terbuka", "created_at": "2026-11-11"}]
    run(denda_po.potong_tagihan_baru(db, "b", USER))
    run(nac.potong_tagihan_baru(db, "b", USER))
    b = db.dewi_cmt_payments.docs[0]
    assert (b["denda_dipotong"], b["nota_aksesoris_dipotong"], b["net_amount"]) == (30000.0, 120000.0, 0.0)
    assert len(b["potongan_denda"]) == 1 and len(b["potongan_nota_aksesoris"]) == 1
    # pemanggil pematangan tagihan memanggil keduanya, denda dulu
    src = (REPO / "backend" / "routes" / "production_maklon_bridge.py").read_text(encoding="utf-8")
    assert src.index("denda_po.potong_tagihan_baru") < src.index("nota_aksesoris_cmt.potong_tagihan_baru")


def test_batal_membalik_jurnal_dan_kiriman_bisa_dibuatkan_lagi(env):
    db, jes = env["db"], env["jes"]
    s = _ship(db)
    doc = run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga()["harga"]),
                       cara_bayar="langsung", user=USER))
    with pytest.raises(HTTPException):
        run(nac.batal(db, doc["id"], USER, ""))                              # alasan wajib
    out = run(nac.batal(db, doc["id"], USER, "harga renda salah ketik"))
    assert out["status"] == "cancelled" and jes[0]["status"] == "voided"
    ship = db.vendor_shipments.docs[0]
    assert ship["nota_aksesoris_status"] == "batal" and "nota_aksesoris_id" not in ship
    assert run(nac.nota_kiriman(db, "SJ1")) is None
    again = run(nac.buat(db, shipment=s, lines=nac.baris_dari_hitungan(CALC_AKS, _harga(ren=50000)["harga"]),
                         cara_bayar="langsung", user=USER))
    assert again["invoice_number"] == "NAC-00002" and again["total"] == 124000.0


def test_baris_buat_nota_dari_rincian_kiriman():
    aks = [{"material_id": "KCG", "code": "A-KCG", "name": "Kancing", "qty_handover": 3,
            "handover_label": "gross isi 144 pcs", "qty_base": 432, "usage_unit": "pcs", "value": 21600},
           {"material_id": "X", "code": "X", "name": "Kosong", "qty_handover": 0, "value": 0}]
    rows = nac.baris_kiriman(aks)
    assert [(r["key"], r["qty_handover"], r["hpp_satuan"]) for r in rows] == [("KCG", 3.0, 7200.0)]
    lines = nac.baris_dari_kiriman(aks, {"KCG": 9000})
    assert lines[0]["jumlah"] == 27000.0 and lines[0]["unit_label"] == "gross isi 144 pcs"


# ══════════════════════════════ jalur Kirim ke CMT ══════════════════════════════
def _route_env(monkeypatch):
    import core.doc_number_policy as dnp
    import core.material_issue_engine as mie
    import routes.production_maklon_bridge as bridge
    import routes.vendor_shipment as vs
    calls = {"issued": 0}

    async def number(*_a, **_k):
        return "SJ-UJI-1"

    async def release(*_a, **_k):
        return True

    async def issue(_db, shipment, items, user, **_k):
        calls["issued"] += 1
        return {"ok": True, "mi": {"mi_number": "MI-1"}, "kirim": {"aksesoris": CALC_AKS}, "accessory_lines": 2}

    async def sync(*_a, **_k):
        return None
    monkeypatch.setattr(dnp, "issue_number", number)
    monkeypatch.setattr(dnp, "release_number", release)
    monkeypatch.setattr(mie, "issue_for_vendor_shipment", issue)
    monkeypatch.setattr(mie, "issue_for_maklon_shipment", issue)
    monkeypatch.setattr(bridge, "try_sync_maklon_finance", sync)
    monkeypatch.setattr(vs, "log_activity", _noop)
    return vs, calls


def _body(harga, vendor="v1"):
    return {"vendor_id": vendor, "shipment_type": "NORMAL", "po_id": "PO1", "po_number": "PO-UJI-1",
            "items": [{"po_id": "PO1", "po_number": "PO-UJI-1", "po_item_id": "i1", "qty_sent": 4}],
            "accessory_items": [{"key": a["key"], "material_id": a["material_id"], "name": a["name"],
                                 "qty_handover": a["qty_handover"]} for a in CALC_AKS],
            "nota_aksesoris": {"cara_bayar": "langsung", "harga": harga}}


def test_kirim_ke_cmt_menolak_harga_kosong_sebelum_stok_dipotong_lalu_menerbitkan_nota(env, monkeypatch):
    vs, calls = _route_env(monkeypatch)
    db = env["db"]
    db.po_items.docs = [{"id": "i1", "po_id": "PO1", "qty": 10, "sku": "S1", "cmt_price_snapshot": 9000}]
    with pytest.raises(HTTPException) as e:
        run(vs.create_vendor_shipment_internal(db, _body([{"key": "KCG", "harga": 8000}]), USER))
    assert "Renda" in e.value.detail and calls["issued"] == 0 and db.vendor_shipments.docs == []
    out = run(vs.create_vendor_shipment_internal(
        db, _body([{"key": "KCG", "harga": 8000}, {"key": "REN", "harga": 55000}]), USER))
    assert calls["issued"] == 1 and out["nota_aksesoris"]["invoice_number"] == "NAC-00001"
    assert out["nota_aksesoris"]["total"] == 134000.0 and out["nota_aksesoris_error"] == ""
    # tim jahit CV sendiri: isian nota diabaikan, kiriman tetap jalan
    db.production_pos.docs[0]["vendor_id"] = "vsgo"
    out2 = run(vs.create_vendor_shipment_internal(db, _body([], vendor="vsgo"), USER))
    assert "nota_aksesoris" not in out2 and len(db.rahaza_ar_invoices.docs) == 1


# ══════════════════════════════ pendaftaran & layar ══════════════════════════════
def test_profil_subledger_nomor_dan_penjaga_keuangan_terdaftar():
    import routes.coa_auto as coa_auto
    import routes.rahaza_posting_profiles as prof
    from data.doc_number_registry import REGISTRY_BY_KEY as K
    p = next(x for x in prof.DEFAULT_PROFILES if x["event_type"] == nac.PROFILE)
    assert p["mapping"] == nac.DEFAULT_MAPPING
    assert prof.role_family(nac.PROFILE, "debit_ar") == "receivable"
    assert prof.role_family(nac.PROFILE, "credit_other_income") == "revenue"
    assert coa_auto.DEFAULT_ENTITY_TYPES[nac.SUBLEDGER_TYPE]["parent_code"] == "1-1307"
    assert K[nac.NUMBER_KEY]["default_format"].startswith("NAC-")
    fin = (REPO / "backend" / "routes" / "rahaza_finance.py").read_text(encoding="utf-8")
    assert fin.count("_reject_cmt_accessory_doc(inv)") == 3                  # status · terbitkan · posting ulang
    post = (REPO / "backend" / "routes" / "rahaza_posting.py").read_text(encoding="utf-8")
    assert 'invoice.get("source_module") == "cmt_accessory"' in post


def test_layar_satu_form_produksi_maklon_portal_vendor_dan_keuangan():
    erp = REPO / "frontend" / "src" / "components" / "erp"
    isian = (erp / "engine" / "kirim" / "NotaAksesorisIsian.jsx").read_text(encoding="utf-8")
    for frag in ("HPP", "Harga jual", "Potong tagihan jahit", "Dibayar langsung", "isi 0 bila gratis"):
        assert frag in isian, frag
    form = (erp / "engine" / "kirim" / "KirimanForm.jsx").read_text(encoding="utf-8")
    assert "NotaAksesorisIsian" in form and "nota_aksesoris" in form
    detail = (erp / "engine" / "kirim" / "KirimanDetail.jsx").read_text(encoding="utf-8")
    assert "NotaAksesorisKiriman" in detail
    vendor = (erp / "engine" / "VendorPortalApp.jsx").read_text(encoding="utf-8")
    assert "VendorNotaAksesoris" in vendor and "Nota Aksesoris" in vendor
    ar = (erp / "RahazaARInvoicesModule.jsx").read_text(encoding="utf-8")
    assert "cmt_accessory" in ar
    bill = (erp / "ProductionCMTBillingModule.jsx").read_text(encoding="utf-8")
    assert "potongan_nota_aksesoris" in bill
