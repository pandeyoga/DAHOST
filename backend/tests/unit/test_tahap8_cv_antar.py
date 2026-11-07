"""Tahap 8 fase 2 & 3 — transaksi ANTAR CV (CV Dewi Aditya ↔ CV Sukma), hermetik (FakeDB, tanpa server).

Yang dikunci di sini (keputusan owner 7 Nov 2026, desain §2/§3/§6/§8):
  * vendor tim jahit CV Sukma (`vendor_partners.owner_entity`) & lawan transaksi bertanda `intercompany_entity`
    dengan sub-ledger dari Auto Akun ("berlaku untuk" benar);
  * empat kemungkinan penjahit: PO internal + tim Sukma → hutang DA berlabel + piutang Sukma otomatis (idempoten);
    PO maklon + tim Sukma → tanpa tagihan & jadwal hutang; CMT luar → tidak berubah;
  * nota aksesoris DA → Sukma (HPP + margin setelan, 4-9300 khusus DA) + balikan saat retur;
  * pembayaran antar CV: pasangan otomatis, nilai sama (cicilan), batal bila pasangan gagal, void berpasangan;
  * Transaksi antar CV (talangan/pinjaman/uang nyasar/pelunasan): dua jurnal berlabel, akun antar CV otomatis;
  * Laporan Saldo antar CV & eliminasi Gabungan (saldo + margin persis; jasa jahit = catatan selisih);
  * seri kwitansi per CV, kop dokumen operasional ikut jenis PO, akses CV per pengguna, setelan margin;
  * migrasi 2026_11_08_antar_cv (pratinjau baca-saja, tulis idempoten).
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

import _fake_mongo as fm  # noqa: E402
import core.entities as ent  # noqa: E402
import core.intercompany as ic  # noqa: E402
import routes.coa_auto as coa_auto  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import utils.counters as counters  # noqa: E402
from utils.waktu import today_wib  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
FE = BACKEND.parent / "frontend" / "src"
USER = {"id": "u-fin", "name": "Staf Keuangan Uji", "role": "accounting"}
TODAY = today_wib()
VID = "v-tim-sukma"
EXT = "v-luar"


def run(c):
    return asyncio.run(c)


def acc(code, type_="ASSET", name=None, parent=None, entities=None, group=False):
    d = {"id": f"id-{code}", "code": code, "name": name or f"Akun {code}", "type": type_, "is_group": group,
         "parent_code": parent, "active": True, "flags": {}, "normal_balance": "DEBIT"}
    if entities:
        d["entities"] = entities
    return d


async def _noop(*_a, **_k):
    return None


PROFILES = {
    "cmt_ap_invoice": {"debit_cmt_wip_internal": "1-1403", "debit_cmt_expense_maklon": "5-4200", "credit_ap": "2-1110"},
    "inventory_issue": {"debit_wip": "1-1403", "credit_inventory_rm": "1-1401", "credit_inventory_accessory": "1-1402",
                        "debit_maklon_material": "5-4100"},
    "ap_payment": {"debit_ap": "2-1100", "credit_cash_default": "1-1201"},
    "ar_payment": {"debit_cash_default": "1-1201", "credit_ar": "1-1301"},
}


@pytest.fixture
def db(monkeypatch):
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [
        acc("1-1201", name="Bank DA"), acc("1-1213", name="Bank Sukma"),
        acc("1-1301", name="Piutang Usaha"), acc("1-1305", name="Piutang Maklon"),
        acc("1-1401", name="Persediaan Bahan"), acc("1-1402", name="Persediaan Aksesoris"),
        acc("1-1403", name="WIP"), acc("2-1100", "LIABILITY", "Hutang Usaha"),
        acc("2-1110", "LIABILITY", "Hutang CMT"), acc("4-1500", "REVENUE", "Pendapatan Maklon", group=True),
        acc("4-0000", "OTHER_INCOME", "Pendapatan lain (kelompok)", group=True),
        acc("5-4100", "COGS", "Biaya Bahan Maklon"), acc("5-4200", "COGS", "Biaya CMT Maklon"),
        acc("6-2900", "EXPENSE", "Beban Umum"),
    ]
    d.rahaza_cash_accounts.docs += [
        {"id": "ca-da", "name": "Bank DA", "gl_account_code": "1-1201", "active": True},
        {"id": "ca-smu", "name": "Bank Sukma", "gl_account_code": "1-1213", "active": True, "entity": "SMU"},
    ]
    d.vendor_partners.docs += [
        {"id": VID, "code": "SGX", "name": "Tim Jahit Uji", "owner_entity": "SMU", "is_active": True},
        {"id": EXT, "code": "LUAR", "name": "CMT Luar Uji", "is_active": True},
    ]
    d.production_pos.docs += [
        {"id": "po-int", "po_number": "PO-INT", "business_type": "internal", "status": "Confirmed", "vendor_id": VID},
        {"id": "po-mkl", "po_number": "PO-MKL", "business_type": "maklon", "status": "Confirmed", "vendor_id": VID},
        {"id": "po-ext", "po_number": "PO-EXT", "business_type": "internal", "status": "Confirmed", "vendor_id": EXT},
    ]
    d.rahaza_materials.docs.append({"id": "m1", "unit_cost": 1000, "type": "accessory"})
    for ev, m in PROFILES.items():
        d.rahaza_posting_profiles.docs.append({"id": ev, "event_type": ev, "mapping": dict(m), "active": True})
    monkeypatch.setattr(coa_auto, "log_activity", _noop)
    issued = []

    async def fake_gen(db_, coll, field, prefix, width=4, ctx=None, config_key=None):
        issued.append(prefix)
        return f"{prefix}{len(issued):0{width}d}"
    monkeypatch.setattr(counters, "gen_prefixed_number", fake_gen)
    counters.invalidate_format_cache()
    return d


def je_of(db, module, ref=None, entity=None):
    return [j for j in db.rahaza_journal_entries.docs if j.get("source_module") == module
            and (ref is None or j.get("source_ref") == ref) and (entity is None or j.get("entity") == entity)
            and j.get("status") != "voided"]


def lines_of(db, je):
    return {(ln["account_code"], ln.get("ic_kind")): (ln["debit"], ln["credit"])
            for ln in db.rahaza_journal_lines.docs if ln["je_id"] == je["id"]}


def bill(bid="b1", po="po-int", vendor=VID, amount=100000.0, **kw):
    return {"id": bid, "payment_code": f"PAY-{bid}", "po_id": po, "po_number": po.upper(), "vendor_id": vendor,
            "cmt_partner_id": vendor, "cmt_name": "Vendor", "subtotal": amount, "net_amount": amount,
            "total_amount": amount, "total_penalty": 0, "status": "draft", "invoice_date": TODAY.isoformat(),
            "breakdown": [{"sku_code": "SKU-1", "qty_billed": 20, "cmt_rate_per_pcs": amount / 20,
                           "line_amount": amount}], **kw}


# ══════════════════════════════ 1. vendor tim Sukma & lawan transaksi ══════════════════════════════
def test_pemilik_penjahit_hanya_luar_atau_sukma():
    assert ic.normalize_owner("") is None and ic.normalize_owner(None) is None and ic.normalize_owner("luar") is None
    assert ic.normalize_owner("smu") == "SMU" and ic.normalize_owner("Sukma") == "SMU"
    with pytest.raises(ValueError):
        ic.normalize_owner("DA")


def test_vendor_owner_dan_tim_sendiri(db):
    assert run(ic.vendor_owner(db, VID)) == "SMU"
    assert run(ic.vendor_owner(db, EXT)) is None and run(ic.vendor_owner(db, None)) is None
    assert run(ic.own_team_vendor(db))["id"] == VID


def test_lawan_transaksi_dibuat_sekali_dengan_berlaku_untuk_benar(db):
    prev = run(ic.ensure_counterparts(db, None, apply=False))
    assert all(v.get("would_create") for v in prev.values())
    assert not db.rahaza_customers.docs and not db.rahaza_suppliers.docs and not db.dewi_maklon_clients.docs
    out = run(ic.ensure_counterparts(db, USER))
    assert out["da_customer"]["accounts"]["ar"] == "1-1301-SMU"
    assert out["smu_client"]["accounts"] == {"ar": "1-1305-DA", "revenue": "4-1500-DA"}
    assert out["smu_supplier"]["accounts"]["ap"] == "2-1100-DA"
    ents = {a["code"]: a.get("entities") for a in db.rahaza_coa_accounts.docs}
    assert ents["1-1301-SMU"] == ["DA"] and ents["2-1100-DA"] == ["SMU"] and ents["1-1305-DA"] == ["SMU"]
    assert db.rahaza_customers.docs[0]["intercompany_entity"] == "SMU"
    assert db.dewi_maklon_clients.docs[0]["intercompany_entity"] == "DA"
    run(ic.ensure_counterparts(db, USER))   # idempoten
    assert len(db.rahaza_customers.docs) == 1 and len(db.rahaza_suppliers.docs) == 1
    accs = run(ic.ic_accounts(db, USER))
    assert accs["DA"]["ap"].startswith("2-1110-") and accs["vendor"]["id"] == VID


def test_kode_lawan_transaksi_tidak_menabrak_master_lama(db):
    db.rahaza_customers.docs.append({"id": "c-lama", "code": "SMU", "name": "Pelanggan lain"})
    run(ic.ensure_counterparts(db, USER))
    mine = [c for c in db.rahaza_customers.docs if c.get("intercompany_entity") == "SMU"][0]
    assert mine["code"] == "CV-SMU"


# ══════════════════════════════ 2. empat kemungkinan penjahit ══════════════════════════════
def test_po_internal_tim_sukma_hutang_da_dan_piutang_sukma_sama(db):
    from routes.dewi_maklon_finance import post_cmt_ap_invoice
    b = bill()
    db.dewi_cmt_payments.docs.append(dict(b))
    res = run(post_cmt_ap_invoice(db, b, USER))
    assert res["ok"] and res["intercompany"]["ok"]
    da = je_of(db, "cmt_ap_invoice", entity="DA")[0]
    assert da["intercompany"] is True and da["counterparty_entity"] == "SMU" and da["ic_kind"] == "sewing"
    smu = je_of(db, ic.SRC_SEWING_AR, entity="SMU")[0]
    assert lines_of(db, smu) == {("1-1305-DA", "sewing"): (100000.0, 0), ("4-1500-DA", "sewing"): (0, 100000.0)}
    assert all(ln.get("intercompany") for ln in db.rahaza_journal_lines.docs if ln["je_id"] in (da["id"], smu["id"]))
    ar = db.rahaza_ar_invoices.docs[0]
    assert ar["entity"] == "SMU" and ar["total"] == 100000 and ar["ic_bill_id"] == "b1" and ar["intercompany"]
    assert ar["invoice_number"].startswith("TJ-SMU-")
    stored = db.dewi_cmt_payments.docs[0]
    assert stored["intercompany"] and stored["ic_ar_invoice_id"] == ar["id"]
    # idempoten: posting ulang tidak membuat piutang/jurnal kedua
    run(post_cmt_ap_invoice(db, stored, USER))
    run(ic.post_sewing_mirror(db, stored, USER))
    assert len(db.rahaza_ar_invoices.docs) == 1 and len(je_of(db, ic.SRC_SEWING_AR)) == 1


def test_po_maklon_tim_sukma_tanpa_tagihan_cmt(db):
    from routes.production_maklon_bridge import mature_ap_from_cmt_receipt
    db.cmt_receipts.docs.append({"id": "r-mkl", "po_id": "po-mkl", "cmt_vendor_id": VID, "receipt_code": "R1"})
    db.cmt_receipt_lines.docs.append({"id": "l1", "receipt_id": "r-mkl", "qty_actual": 10, "po_item_id": "i1"})
    res = run(mature_ap_from_cmt_receipt(db, "r-mkl", USER))
    assert res["own_team"] and res["message"] == ic.OWN_TEAM_MSG
    assert not db.dewi_cmt_payments.docs
    assert db.cmt_receipts.docs[0]["cmt_bill_note"] == ic.OWN_TEAM_MSG
    from routes.dewi_maklon_finance import post_cmt_ap_invoice
    bad = run(post_cmt_ap_invoice(db, bill("b-old", po="po-mkl"), USER))
    assert not bad["ok"] and ic.OWN_TEAM_MSG in bad["error"]


def test_jadwal_hutang_cmt_melewati_tim_sukma(db):
    from core.maklon_ledger import refresh_ap_schedules
    db.po_items.docs.append({"id": "i1", "po_id": "po-mkl", "qty": 10, "cmt_price_snapshot": 5000})
    assert run(refresh_ap_schedules(db, "po-mkl", USER)) == []
    assert not db.dewi_cmt_ap_schedules.docs


def test_cmt_luar_tidak_berubah(db):
    from routes.dewi_maklon_finance import post_cmt_ap_invoice
    b = bill("b-ext", po="po-ext", vendor=EXT, amount=20000.0)
    db.dewi_cmt_payments.docs.append(dict(b))
    res = run(post_cmt_ap_invoice(db, b, USER))
    assert res["ok"] and "intercompany" not in res
    assert not je_of(db, "cmt_ap_invoice")[0].get("intercompany") and not db.rahaza_ar_invoices.docs


# ══════════════════════════════ 3. nota aksesoris ══════════════════════════════
def _mi(mid="mi1", qty=10, cost=1000.0):
    # material m1 = aksesoris (1-1402), ada di master lewat fixture `db`
    return {"id": mid, "mi_number": mid.upper(), "status": "issued", "cost_target": "maklon", "production_po_id": "po-mkl",
            "po_number_snapshot": "PO-MKL", "issued_at": TODAY.isoformat(),
            "items": [{"material_id": "m1", "qty_issued": qty, "unit_cost_applied": cost}]}


def test_harga_nota_aksesoris_murni():
    assert ic.price_split(1000, 0) == (1000.0, 0.0, 1000.0)
    assert ic.price_split(1540000, 10) == (1540000.0, 154000.0, 1694000.0)
    assert ic.parse_margin("") == 0 and ic.parse_margin(12.5) == 12.5
    for bad in (-1, 101, "abc"):
        with pytest.raises(ValueError):
            ic.parse_margin(bad)


def test_aksesoris_maklon_dijual_ke_sukma_seharga_pokok(db):
    db.rahaza_material_issues.docs.append(_mi())
    res = run(rp.post_inventory_issue(db, _mi(), USER))
    assert res["ok"] and res["intercompany"]["margin"] == 0
    da = je_of(db, "inventory_issue", "mi:mi1", "DA")[0]
    assert lines_of(db, da) == {("1-1301-SMU", "accessory"): (10000.0, 0), ("1-1402", "accessory"): (0, 10000.0)}
    smu = je_of(db, ic.SRC_ACCESSORY_AP, entity="SMU")[0]
    assert lines_of(db, smu) == {("5-4100", "accessory"): (10000.0, 0), ("2-1100-DA", "accessory"): (0, 10000.0)}
    ar, ap = run(ic.find_accessory_docs(db, "mi:mi1"))
    assert ar["entity"] == "DA" and ap["entity"] == "SMU" and ar["total"] == ap["total"] == 10000
    assert ar["ic_pair_doc_id"] == ap["id"] and ar["invoice_number"].startswith("NA-DA-")
    assert not any(a["code"] == "4-9300" for a in db.rahaza_coa_accounts.docs)   # dibuat hanya bila perlu
    run(rp.post_inventory_issue(db, _mi(), USER))   # idempoten
    assert len(je_of(db, ic.SRC_ACCESSORY_AP)) == 1 and len(db.rahaza_ar_invoices.docs) == 1


def test_aksesoris_dengan_margin_10_persen(db):
    db.dewi_system_config.docs.append({"key": ic.MARGIN_KEY, "value": 10.0})
    db.rahaza_material_issues.docs.append(_mi("mi2"))
    res = run(rp.post_inventory_issue(db, _mi("mi2"), USER))
    assert res["intercompany"]["margin"] == 1000.0 and res["intercompany"]["price"] == 11000.0
    m = [a for a in db.rahaza_coa_accounts.docs if a["code"] == "4-9300"][0]
    assert m["entities"] == ["DA"] and m["name"].startswith("Penjualan Aksesoris ke CV Sukma")
    da = je_of(db, "inventory_issue", "mi:mi2", "DA")[0]
    assert lines_of(db, da) == {("1-1301-SMU", "accessory"): (11000.0, 0), ("1-1402", "accessory"): (0, 10000.0),
                                ("4-9300", "accessory_margin"): (0, 1000.0)}
    smu = je_of(db, ic.SRC_ACCESSORY_AP, entity="SMU")[0]
    assert lines_of(db, smu) == {("5-4100", "accessory"): (10000.0, 0), ("5-4100", "accessory_margin"): (1000.0, 0),
                                 ("2-1100-DA", "accessory"): (0, 11000.0)}


def test_retur_bahan_membalik_nota_di_dua_buku(db):
    db.dewi_system_config.docs.append({"key": ic.MARGIN_KEY, "value": 10.0})
    db.rahaza_material_issues.docs.append(_mi())
    run(rp.post_inventory_issue(db, _mi(), USER))
    db.dewi_system_config.docs[0]["value"] = 50.0          # setelan berubah: balikan tetap pakai margin nota asal
    ret = {"id": "ret1", "ref_no": "RET-1", "material_issue_id": "mi1", "received_at": TODAY.isoformat()}
    res = run(rp.post_material_return(db, ret, [{"material_id": "m1", "qty": 4, "unit_cost": 1000, "kind": "aksesoris",
                                                  "cost_target": "maklon", "credit_account": "1-1301-SMU"}], USER))
    assert res["ok"] and res["intercompany"]["price"] == 4400.0
    da = je_of(db, "inventory_issue_return", "pmr:ret1", "DA")[0]
    got = lines_of(db, da)
    assert got[("1-1301-SMU", "accessory")] == (0, 4400.0) and got[("4-9300", "accessory_margin")] == (400.0, 0)
    smu = je_of(db, ic.SRC_ACCESSORY_AP, "icacc:pmr:ret1", "SMU")[0]
    assert lines_of(db, smu)[("2-1100-DA", "accessory")] == (4400.0, 0)
    ar, ap = run(ic.find_accessory_docs(db, "mi:mi1"))
    assert ar["total"] == ap["total"] == 6600.0 and ar["returned_amount"] == 4400.0


# ══════════════════════════════ 4. pembayaran antar CV ══════════════════════════════
def _posted_sewing(db, amount=100000.0):
    from routes.dewi_maklon_finance import post_cmt_ap_invoice
    b = bill(amount=amount)
    db.dewi_cmt_payments.docs.append(dict(b))
    run(post_cmt_ap_invoice(db, b, USER))
    return db.dewi_cmt_payments.docs[0]


def test_da_bayar_tim_sukma_dua_buku_terisi_sama(db):
    b = _posted_sewing(db)
    res = run(ic.settle(db, kind=ic.KIND_CMT, doc=b, amount=40000, cash_account_id="ca-da",
                        counter_cash_account_id="ca-smu", pay_date=TODAY.isoformat(), user=USER))
    assert res["origin"]["entity"] == "DA" and res["mirror"]["entity"] == "SMU" and res["amount"] == 40000
    assert db.dewi_cmt_payments.docs[0]["paid_amount"] == 40000 and db.dewi_cmt_payments.docs[0]["status"] == "partial_paid"
    ar = db.rahaza_ar_invoices.docs[0]
    assert ar["paid_amount"] == 40000 and ar["balance"] == 60000
    pay_da = je_of(db, "ap_payment", entity="DA")[0]
    pay_smu = je_of(db, "ar_payment", entity="SMU")[0]
    assert pay_da["ic_pair_id"] == pay_smu["ic_pair_id"] and pay_da["ic_kind"] == "payment"
    assert lines_of(db, pay_smu)[("1-1213", "payment")] == (40000.0, 0)
    assert lines_of(db, pay_smu)[("1-1305-DA", "payment")] == (0, 40000.0)
    rep = run(ic.balance_report(db, TODAY.isoformat()))
    assert rep["balanced"] and rep["pairs"][0]["left"]["balance"] == 60000.0


def test_pembayaran_antar_cv_ditolak_tanpa_rekening_cv_lain(db):
    b = _posted_sewing(db)
    with pytest.raises(ValueError, match="CV Sukma"):
        run(ic.settle(db, kind=ic.KIND_CMT, doc=b, amount=1000, cash_account_id="ca-da", counter_cash_account_id=None,
                      pay_date=None, user=USER))
    with pytest.raises(ValueError, match="harus milik CV Sukma"):
        run(ic.settle(db, kind=ic.KIND_CMT, doc=b, amount=1000, cash_account_id="ca-da", counter_cash_account_id="ca-da",
                      pay_date=None, user=USER))
    with pytest.raises(ValueError, match="paling banyak"):
        run(ic.settle(db, kind=ic.KIND_CMT, doc=b, amount=999999, cash_account_id="ca-da",
                      counter_cash_account_id="ca-smu", pay_date=None, user=USER))
    assert not db.rahaza_cash_movements.docs


def test_pasangan_gagal_sisi_asal_dibatalkan(db, monkeypatch):
    b = _posted_sewing(db)

    async def fail(*_a, **_k):
        return {"ok": False, "error": "uji gagal"}
    monkeypatch.setattr(rp, "post_ar_payment", fail)
    with pytest.raises(ValueError, match="dibatalkan"):
        run(ic.settle(db, kind=ic.KIND_CMT, doc=b, amount=40000, cash_account_id="ca-da",
                      counter_cash_account_id="ca-smu", pay_date=TODAY.isoformat(), user=USER))
    assert db.dewi_cmt_payments.docs[0].get("paid_amount", 0) == 0
    assert db.rahaza_ar_invoices.docs[0].get("paid_amount", 0) == 0
    assert not db.rahaza_cash_movements.docs and not je_of(db, "ap_payment")


def test_void_pembayaran_membatalkan_pasangan(db):
    b = _posted_sewing(db)
    res = run(ic.settle(db, kind=ic.KIND_CMT, doc=b, amount=40000, cash_account_id="ca-da",
                        counter_cash_account_id="ca-smu", pay_date=TODAY.isoformat(), user=USER))
    d = [x for x in db.dewi_cmt_disbursements.docs if x["id"] == res["origin"]["payment_id"]][0]
    out = run(ic.void_pair_of(db, d, USER))
    assert out["ok"] and not je_of(db, "ar_payment", entity="SMU")
    assert db.rahaza_ar_invoices.docs[0]["paid_amount"] == 0 and db.rahaza_ar_invoices.docs[0]["balance"] == 100000


def test_bayar_hutang_aksesoris_sukma_membuat_penerimaan_da(db):
    db.rahaza_material_issues.docs.append(_mi())
    run(rp.post_inventory_issue(db, _mi(), USER))
    _ar, ap = run(ic.find_accessory_docs(db, "mi:mi1"))
    res = run(ic.settle(db, kind=ic.KIND_AP, doc=ap, amount=2500, cash_account_id="ca-smu",
                        counter_cash_account_id="ca-da", pay_date=TODAY.isoformat(), user=USER))
    assert res["mirror"]["kind"] == "ar" and res["mirror"]["entity"] == "DA"
    ar2, ap2 = run(ic.find_accessory_docs(db, "mi:mi1"))
    assert ar2["paid_amount"] == ap2["paid_amount"] == 2500


# ══════════════════════════════ 5. transaksi antar CV ══════════════════════════════
@pytest.mark.parametrize("direction,src,oth", [
    ("give", [("AR-S", 5, 0), ("BANK-S", 0, 5)], [("X-O", 5, 0), ("AP-O", 0, 5)]),
    ("receive", [("BANK-S", 5, 0), ("AP-S", 0, 5)], [("AR-O", 5, 0), ("X-O", 0, 5)]),
    ("settle", [("AP-S", 5, 0), ("BANK-S", 0, 5)], [("X-O", 5, 0), ("AR-O", 0, 5)]),
    ("collect", [("BANK-S", 5, 0), ("AR-S", 0, 5)], [("AP-O", 5, 0), ("X-O", 0, 5)]),
])
def test_baris_transaksi_antar_cv_murni(direction, src, oth):
    a, b = ic.txn_lines(direction, amount=5, src_code="BANK-S", oth_code="X-O", src_ar="AR-S", src_ap="AP-S",
                        oth_ar="AR-O", oth_ap="AP-O", memo="m")
    assert [(x["account_code"], x["debit"], x["credit"]) for x in a] == src
    assert [(x["account_code"], x["debit"], x["credit"]) for x in b] == oth


def test_talangan_dua_jurnal_berlabel_dan_bisa_dibatalkan(db):
    run(ic.ensure_counterparts(db, USER))
    doc = run(ic.create_transaction(db, {"kind": "talangan", "amount": 250000, "date": TODAY.isoformat(),
                                         "description": "talangan listrik", "source_account_code": "1-1201",
                                         "other_account_code": "6-2900"}, "DA", USER))
    da = je_of(db, ic.SRC_TXN, f"ictx:{doc['id']}", "DA")[0]
    smu = je_of(db, ic.SRC_TXN, f"ictx:{doc['id']}", "SMU")[0]
    assert lines_of(db, da) == {("1-1301-SMU", "transaction"): (250000.0, 0), ("1-1201", "transaction"): (0, 250000.0)}
    ap = run(ic.ic_accounts(db, USER))["SMU"]["ap"]
    assert lines_of(db, smu) == {("6-2900", "transaction"): (250000.0, 0), (ap, "transaction"): (0, 250000.0)}
    assert da["counterparty_entity"] == "SMU" and smu["counterparty_entity"] == "DA"
    assert run(ic.balance_report(db, TODAY.isoformat()))["balanced"]
    run(ic.void_transaction(db, doc["id"], USER, "salah"))
    assert not je_of(db, ic.SRC_TXN)


def test_transaksi_menolak_akun_antar_cv_dan_akun_cv_lain(db):
    run(ic.ensure_counterparts(db, USER))
    body = {"kind": "pinjaman", "amount": 1000, "description": "pinjam kas", "source_account_code": "1-1301-SMU",
            "other_account_code": "1-1213"}
    with pytest.raises(ValueError, match="akun antar CV"):
        run(ic.create_transaction(db, body, "DA", USER))
    body["source_account_code"] = "1-1213"     # rekening milik CV Sukma dipakai di buku DA
    with pytest.raises(ValueError, match="milik CV Sukma"):
        run(ic.create_transaction(db, body, "DA", USER))
    with pytest.raises(ValueError, match="keterangan"):
        run(ic.create_transaction(db, {**body, "description": "x"}, "DA", USER))
    assert not db.rahaza_journal_entries.docs


def test_transfer_bank_beda_cv_diarahkan_ke_transaksi_antar_cv(db):
    import routes.rahaza_bank_transfers as bt
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        run(bt._owners_or_reject(db, "1-1201", "1-1213", None))
    assert "Transaksi antar CV" in e.value.detail


# ══════════════════════════════ 6. saldo & eliminasi Gabungan ══════════════════════════════
def test_eliminasi_saldo_dan_margin_gabungan(db):
    db.dewi_system_config.docs.append({"key": ic.MARGIN_KEY, "value": 10.0})
    _posted_sewing(db)
    db.rahaza_material_issues.docs.append(_mi())
    run(rp.post_inventory_issue(db, _mi(), USER))
    c = run(ic.consolidation(db, from_date=None, to_date=TODAY.isoformat()))
    el = c["lines"]
    accs = run(ic.ic_accounts(db, USER))
    assert el[accs["DA"]["ap"]] == {"debit": 100000.0, "credit": 0.0}       # hutang DA ke Sukma
    assert el["1-1305-DA"] == {"debit": 0.0, "credit": 100000.0}            # piutang Sukma atas DA
    assert el["1-1301-SMU"]["credit"] == 11000.0 and el["2-1100-DA"]["debit"] == 11000.0
    assert el["4-9300"] == {"debit": 1000.0, "credit": 0.0} and el["5-4100"] == {"debit": 0.0, "credit": 1000.0}
    assert round(sum(v["debit"] - v["credit"] for v in el.values()), 2) == 0          # neraca gabungan tetap seimbang
    notes = {n["key"]: n for n in c["notes"]}
    assert notes["sewing"]["label"] == "Selisih antar CV yang belum tereliminasi: Rp 100.000"
    assert "accessory_margin" not in notes


def test_selisih_saldo_ditampilkan_bukan_disembunyikan(db):
    _posted_sewing(db)
    smu_je = je_of(db, ic.SRC_SEWING_AR, entity="SMU")[0]
    db.rahaza_journal_lines.docs = [ln for ln in db.rahaza_journal_lines.docs if ln["je_id"] != smu_je["id"]]
    run(ic.post_sewing_mirror(db, db.dewi_cmt_payments.docs[0], USER))      # pasangan sudah ada → tidak ditulis ulang
    bs = run(ic.bs_elimination(db, TODAY.isoformat()))
    assert any("belum tereliminasi: Rp 100.000" in n["label"] for n in bs["notes"])
    assert all(abs(v["debit"]) + abs(v["credit"]) == 0 for v in bs["lines"].values()) or not bs["lines"]


def test_apply_elimination_murni():
    per = {"A": {"debit": 10, "credit": 0}}
    out = ic.apply_elimination(per, {"A": {"debit": 0, "credit": 4}, "B": {"debit": 4, "credit": 0}})
    assert out["A"] == {"debit": 10, "credit": 4} and out["B"]["debit"] == 4 and per["A"]["credit"] == 0
    assert ic.split_net(-5) == {"debit": 0.0, "credit": 5.0} and ic.net_of({"A": {"debit": 3, "credit": 1}}) == {"A": 2}


# ══════════════════════════════ 7. kwitansi, dokumen, akses CV, setelan ══════════════════════════════
def test_seri_kwitansi_per_cv(db):
    import routes.rahaza_payment_receipt as kw
    assert kw.receipt_prefix("ar", "SMU", "2026-11-07") == "KW-SMU-202611-"
    assert kw.receipt_prefix("ar", None, "2026-11-07") == "KW-DA-202611-"
    assert kw.receipt_prefix("ap", "DA", "2026-11-07") == "BP-DA-202611-"
    db.rahaza_ar_payments.docs.append({"id": "p1", "date": "2026-11-07"})
    n1 = run(kw.ensure_receipt_number(db, "ar", {"id": "p1", "date": "2026-11-07"}, "SMU"))
    n2 = run(kw.ensure_receipt_number(db, "ar", db.rahaza_ar_payments.docs[0], "SMU"))
    assert n1 == n2 and n1.startswith("KW-SMU-202611-") and db.rahaza_ar_payments.docs[0]["receipt_entity"] == "SMU"


def test_kop_dokumen_operasional_ikut_jenis_po(db, monkeypatch):
    import routes.operations_pdf as op

    async def prof(_db, e="DA"):
        return {"entity": e, "company_name": f"Kop {e}"}
    monkeypatch.setattr(op, "get_company_profile", prof)
    base = {"entity": "DA", "company_name": "Kop DA"}
    assert run(op._profile_for_pos(db, ["po-mkl"], base))["company_name"] == "Kop SMU"
    assert run(op._profile_for_pos(db, ["po-int", None], base)) is base
    assert run(op._profile_for_pos(db, [], base)) is base


def test_pdf_dokumen_antar_cv_berkop_penerbit():
    import routes.rahaza_intercompany as ri
    doc = {"invoice_number": "TJ-SMU-1", "ic_kind": "sewing", "customer_name": "CV Dewi Aditya Official",
           "issue_date": "2026-11-07", "total": 100000, "paid_amount": 0, "balance": 100000,
           "items": [{"description": "Jasa jahit", "qty": 20, "unit_price": 5000, "total": 100000}]}
    pdf = ri.build_ic_document_pdf(doc, {"company_name": "CV Sukma Mitra Utama", "entity": "SMU"}, {}, "uji")
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000


def test_akses_cv_per_pengguna():
    assert ent.normalize_allowed(None) is None and ent.normalize_allowed(["DA", "SMU"]) is None
    assert ent.normalize_allowed(["smu"]) == ["SMU"]
    with pytest.raises(ValueError):
        ent.normalize_allowed(["PT"])
    assert ent.allowed_of_user({}) == ["DA", "SMU"] and ent.allowed_of_user({"allowed_entities": ["SMU"]}) == ["SMU"]
    assert ent.allowed_of_user({"allowed_entities": "rusak!"}) == ["DA", "SMU"]
    assert ent.cv_access_problem(["SMU"], "SMU") is None
    assert "CV Sukma" in ent.cv_access_problem(["SMU"], "DA")
    assert ent.cv_access_problem(["SMU"], None)          # tanpa header = DA → ditolak
    assert ent.cv_access_problem(["SMU"], "ALL") and ent.cv_access_problem(["DA", "SMU"], "ALL") is None
    assert [o["code"] for o in ent.entity_options_for(["SMU"])] == ["SMU"]
    assert [o["code"] for o in ent.entity_options_for(None)] == ["DA", "SMU", "ALL"]


def test_middleware_akses_cv(monkeypatch):
    import auth
    import middleware.cv_readonly_guard as g
    import middleware.module_permission_gate as mg
    assert g.is_cv_scoped("/api/rahaza/intercompany/balances") and g.is_cv_scoped("/api/rahaza/ap-invoices")
    assert not g.is_cv_scoped("/api/prod/cmt-receipts")
    monkeypatch.setattr(mg, "_token_payload", lambda scope: {"id": "u1"})
    state = {"allowed": ["SMU"]}

    async def live(uid):
        return {"role": "accounting", "allowed_entities": state["allowed"]}
    monkeypatch.setattr(auth, "_load_live_user", live)
    deny = lambda p, h=None, q=None, m="GET": run(g.cv_access_denial({}, p, h, q, m))  # noqa: E731
    assert "hanya diberi akses" in deny("/api/rahaza/ap-invoices", "DA")
    assert deny("/api/rahaza/ap-invoices", "SMU") is None
    assert deny("/api/rahaza/ap-invoices", None, "smu") is None
    assert deny("/api/prod/cmt-receipts", "DA") is None                      # bukan rute keuangan
    state["allowed"] = None
    assert deny("/api/rahaza/ap-invoices", "DA") is None                     # bawaan: kedua CV


def test_setelan_margin_hanya_persen_sah():
    from routes.dewi_system_config import DEFAULT_CONFIGS, choice_error
    cfg = [c for c in DEFAULT_CONFIGS if c["key"] == ic.MARGIN_KEY][0]
    assert cfg["value"] == 0.0 and cfg["data_type"] == "number"
    assert choice_error(ic.MARGIN_KEY, 10) is None and "0 dan 100" in choice_error(ic.MARGIN_KEY, 150)


def test_vendor_master_menulis_pemilik_penjahit():
    src = (BACKEND / "routes" / "vendor_portal.py").read_text(encoding="utf-8")
    assert "owner_entity: str | None = None" in src and "_owner_entity_or_400(payload.owner_entity)" in src


# ══════════════════════════════ 8. migrasi 2026_11_08_antar_cv ══════════════════════════════
def _mig():
    p = BACKEND / "scripts" / "migrations" / "2026_11_08_antar_cv.py"
    spec = importlib.util.spec_from_file_location("mig_antar_cv", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_migrasi_pratinjau_baca_saja_lalu_tulis_idempoten(db, capsys):
    m = _mig()
    db.vendor_partners.docs[0].pop("owner_entity")
    db.vendor_partners.docs[0]["code"] = "SGO"
    db.dewi_cmt_payments.docs += [
        bill("b-int-unpaid"), bill("b-int-paid", paid_amount=100000.0),
        bill("b-mkl-unpaid", po="po-mkl"), bill("b-mkl-paid", po="po-mkl", paid_amount=50000.0)]
    for b in db.dewi_cmt_payments.docs:
        b["gl_je_id"] = f"je-{b['id']}"
    before = {k: len(v.docs) for k, v in db._cols.items()}
    out = run(m.run(db, apply=False, vendor_code="SGO"))
    assert {k: len(v.docs) for k, v in db._cols.items() if k in before} == before
    assert "owner_entity" not in db.vendor_partners.docs[0]
    assert out["internal_bills"]["bills"] == 2 and out["internal_bills"]["mirror_created"] == 1
    assert out["maklon_bills"]["unpaid"] == 1 and out["maklon_bills"]["paid_or_partial_kept"] == 1
    with pytest.raises(m.ReadOnlyError):
        run(m.ReadOnlyDB(db).vendor_partners.update_one({}, {"$set": {"x": 1}}))
    out = run(m.run(db, apply=True, vendor_code="SGO"))
    assert db.vendor_partners.docs[0]["owner_entity"] == "SMU"
    assert out["internal_bills"]["labelled"] == 2 and out["internal_bills"]["mirror_created"] == 1
    st = {b["id"]: b.get("status") for b in db.dewi_cmt_payments.docs}
    assert st["b-mkl-unpaid"] == "cancelled" and st["b-mkl-paid"] != "cancelled"
    assert len(db.rahaza_ar_invoices.docs) == 1 and db.rahaza_ar_invoices.docs[0]["ic_bill_id"] == "b-int-unpaid"
    again = run(m.run(db, apply=True, vendor_code="SGO"))
    assert again["internal_bills"]["mirror_created"] == 0 and again["internal_bills"]["mirror_exists"] == 1
    assert len(db.rahaza_ar_invoices.docs) == 1
    assert "Tim Jahit Uji" not in capsys.readouterr().out          # ringkasan tanpa nama


def test_migrasi_bucket_tagihan():
    m = _mig()
    assert m.bill_bucket({"net_amount": 100, "paid_amount": 0}) == "unpaid"
    assert m.bill_bucket({"net_amount": 100, "paid_amount": 40}) == "partial"
    assert m.bill_bucket({"net_amount": 100, "paid_amount": 100}) == "paid"


# ══════════════════════════════ 9. layar ══════════════════════════════
def test_layar_antar_cv_terdaftar_dan_tanpa_pilihan_polos():
    reg = (FE / "components" / "erp" / "moduleRegistry.js").read_text(encoding="utf-8")
    nav = (FE / "components" / "erp" / "portal-shell" / "portalNav.js").read_text(encoding="utf-8")
    for mid in ("fin-antar-cv", "fin-saldo-antar-cv"):
        assert f"'{mid}'" in reg and f"id: '{mid}'" in nav
    from data.module_catalog import match_module
    assert match_module("/api/rahaza/intercompany/transactions")["id"] == "fin_intercompany"
    files = ["finance/IntercompanyTransactionsModule.jsx", "finance/IntercompanyBalanceModule.jsx",
             "finance/IntercompanyNotes.jsx", "ProductionCMTBillingModule.jsx", "VendorAccountsAdminModule.jsx"]
    for f in files:
        s = (FE / "components" / "erp" / f).read_text(encoding="utf-8")
        assert "<" + "select" not in s, f
    pl = (FE / "components" / "erp" / "layout" / "PageLayout.jsx").read_text(encoding="utf-8")
    assert "ReadOnlyContent" in pl and "onClickCapture" in pl
    ent_js = (FE / "lib" / "entitas.js").read_text(encoding="utf-8")
    assert "rows.some((x) => x.code === fb.code)" in ent_js


def test_koleksi_transaksi_antar_cv_terdaftar():
    from core.collection_registry import KIND, REGISTRY
    assert REGISTRY.get(ic.TXN_COLL) == "finance" and KIND.get(ic.TXN_COLL) == "transaksi"


def test_tanggal_dokumen_cadangan():
    assert ic._to_date("2026-11-07") == date(2026, 11, 7) and isinstance(ic._to_date(None), date)
