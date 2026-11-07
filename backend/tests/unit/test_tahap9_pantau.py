"""Uji unit HERMETIK Tahap 9 — agen PANTAU (Pantau Produksi, Laporan Selisih, Dashboard), 7 Nov 2026.

Skenario (angka DIHITUNG TANGAN, data uji tanpa nama/angka klien):

PO internal PO-INT-UJI (vendor V1), batas kirim kemarin:
  I1 A-M  dipesan 100 · potongan 100 (surat jalan berstatus `Received` = CMT terima BAHAN) · diterima CMT 100
          · diproduksi 100 · CMT menyetor 90 (selesai QC: lolos 85, reject 5 → permak 3 berhasil, 2 dibuang,
          baris mencatat 3 hasil permak) + 10 masih QC · serah terima ke gudang 60
          ⇒ di CMT 100 − 90 − 10 = 0 · lolos QC 85 + 3 = 88 · dikirim 60 (BUKAN 60 + deklarasi CMT→DA 90)
  I2 A-L  dipesan 50 · potongan 50 + pengganti 5 · diterima CMT 45 (kurang 5) · diproduksi 45 · disetor 45
          ⇒ di CMT 50 − 45 = 5 · lolos 45 · bahan kurang −5
  I3 A-S  dipesan 40 · job induk 24 + job TAMBAHAN 16 = 40 (per job: kurang 16; per baris PO: 0) · lolos 40
  I4 A-XL dipesan 20 · diproduksi 24 · lolos 24 (alasan lebih qty tercatat) ⇒ +4 lebih, ada alasan
  Total internal: dipesan 210 · di CMT 5 · sedang QC 10 · lolos 197 · dikirim 60.

PO maklon PO-MKL-UJI (vendor V1):
  M1 dipesan 80 · potongan 80 · diterima 80 · diproduksi 80 · lolos 78, reject 2 (permak terbuka)
     · kirim ke klien 50 (dikonfirmasi diterima 48, selisih 2 terbuka) + 20 BELUM dikonfirmasi
     ⇒ diterima klien 48 (dulu laporan menghitung 68) · belum dikonfirmasi 20 · dikirim 70.

Jalankan:  cd backend && python -m pytest tests/unit/test_tahap9_pantau.py -q
"""
import asyncio
import importlib.util
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeColl, FakeCursor, FakeDB, _get, match  # noqa: E402
from core import pantau_produksi as pp  # noqa: E402
from utils.waktu import today_wib  # noqa: E402

NOW = datetime.now(timezone.utc).isoformat()
TODAY = today_wib()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


def run(coro):
    return asyncio.run(coro)


class AggColl(FakeColl):
    """FakeColl + `aggregate` ($match/$group/$sum) + `distinct` secukupnya untuk endpoint lama."""

    def aggregate(self, pipeline):
        docs = list(self.docs)
        for st in pipeline:
            if "$match" in st:
                docs = [d for d in docs if match(d, st["$match"])]
            elif "$group" in st:
                g = st["$group"]
                key = g["_id"]
                out = {}
                for d in docs:
                    k = _get(d, key[1:]) if isinstance(key, str) and key.startswith("$") else None
                    row = out.setdefault(k, {"_id": k})
                    for f, expr in g.items():
                        if f == "_id" or not isinstance(expr, dict) or "$sum" not in expr:
                            continue
                        v = expr["$sum"]
                        val = _get(d, v[1:]) if isinstance(v, str) else v
                        row[f] = row.get(f, 0) + (val or 0)
                docs = list(out.values())
        return FakeCursor(docs)

    async def distinct(self, field, flt=None):
        return list({_get(d, field) for d in self._found(flt or {}) if _get(d, field) is not None})


class DB(FakeDB):
    def __init__(self, **colls):
        self._c = {k: AggColl(v) for k, v in colls.items()}

    def __getitem__(self, name):
        return self._c.setdefault(name, AggColl())


class Req:
    def __init__(self, qp=None, body=None):
        self.query_params = qp or {}
        self.headers = {}
        self._body = body or {}

    async def json(self):
        return self._body


def _item(iid, po, sku, size, qty, serial, price=5000):
    return {"id": iid, "po_id": po["id"], "po_number": po["po_number"], "sku": sku, "size": size, "color": "Hitam",
            "product_name": "Kaos uji", "qty": qty, "serial_number": serial, "cmt_price_snapshot": price}


def scenario():
    pi = {"id": "po-i", "po_number": "PO-INT-UJI", "business_type": "internal", "status": "In Production",
          "vendor_id": "V1", "vendor_name": "CMT Uji", "customer_name": "Gudang DA", "deadline": YESTERDAY,
          "created_at": NOW, "po_date": TODAY.isoformat(),
          "over_qty_events": [{"step": "terima_qc", "po_item_id": "I4", "over": 4, "reason": "Bonus potongan CMT",
                               "by": "Staf uji", "at": NOW}]}
    pm = {"id": "po-m", "po_number": "PO-MKL-UJI", "business_type": "maklon", "status": "In Production",
          "vendor_id": "V1", "vendor_name": "CMT Uji", "customer_name": "Klien Uji",
          "delivery_deadline": (TODAY + timedelta(days=10)).isoformat(), "created_at": NOW,
          "po_date": TODAY.isoformat()}
    items = [_item("I1", pi, "A-M", "M", 100, "SN-1"), _item("I2", pi, "A-L", "L", 50, "SN-DUP"),
             _item("I3", pi, "A-S", "S", 40, "SN-3"), _item("I4", pi, "A-XL", "XL", 20, "SN-4"),
             _item("M1", pm, "K-M", "M", 80, "SN-DUP")]
    vs = [
        {"id": "VS1", "shipment_number": "SJV-1", "po_id": "po-i", "po_number": "PO-INT-UJI", "vendor_id": "V1",
         "vendor_name": "CMT Uji", "shipment_type": "NORMAL", "status": "Received", "shipment_date": YESTERDAY,
         "business_type": "internal", "created_at": NOW},
        {"id": "VS2", "shipment_number": "SJV-1-A1", "po_id": "po-i", "po_number": "PO-INT-UJI", "vendor_id": "V1",
         "shipment_type": "REPLACEMENT", "parent_shipment_id": "VS1", "status": "Sent", "created_at": NOW},
        {"id": "VS3", "shipment_number": "SJV-2", "po_id": "po-m", "po_number": "PO-MKL-UJI", "vendor_id": "V1",
         "shipment_type": "NORMAL", "status": "Received", "business_type": "maklon", "created_at": NOW},
    ]
    vsi = [{"id": "VSI1", "shipment_id": "VS1", "po_item_id": "I1", "qty_sent": 100, "sku": "A-M"},
           {"id": "VSI2", "shipment_id": "VS1", "po_item_id": "I2", "qty_sent": 50, "sku": "A-L"},
           {"id": "VSI3", "shipment_id": "VS1", "po_item_id": "I3", "qty_sent": 40, "sku": "A-S"},
           {"id": "VSI4", "shipment_id": "VS1", "po_item_id": "I4", "qty_sent": 20, "sku": "A-XL"},
           {"id": "VSI5", "shipment_id": "VS2", "po_item_id": "I2", "qty_sent": 5, "sku": "A-L",
            "shipment_type": "REPLACEMENT", "parent_shipment_id": "VS1"},
           {"id": "VSI6", "shipment_id": "VS3", "po_item_id": "M1", "qty_sent": 80, "sku": "K-M"}]
    insp = [{"id": "IN1", "shipment_id": "VS1"}, {"id": "IN3", "shipment_id": "VS3"}]
    insp_items = [{"inspection_id": "IN1", "shipment_item_id": "VSI1", "received_qty": 100, "missing_qty": 0},
                  {"inspection_id": "IN1", "shipment_item_id": "VSI2", "received_qty": 45, "missing_qty": 5,
                   "condition_notes": "potongan L kurang 5"},
                  {"inspection_id": "IN1", "shipment_item_id": "VSI3", "received_qty": 40, "missing_qty": 0},
                  {"inspection_id": "IN1", "shipment_item_id": "VSI4", "received_qty": 20, "missing_qty": 0},
                  {"inspection_id": "IN3", "shipment_item_id": "VSI6", "received_qty": 80, "missing_qty": 0}]
    jobs = [{"id": "J1", "job_number": "JOB-1", "po_id": "po-i", "po_number": "PO-INT-UJI", "vendor_id": "V1",
             "vendor_name": "CMT Uji", "vendor_shipment_id": "VS1", "shipment_type": "NORMAL", "status": "In Progress",
             "business_type": "internal", "created_at": NOW, "parent_job_id": None},
            {"id": "J1A", "job_number": "JOB-1-A", "po_id": "po-i", "vendor_id": "V1", "parent_job_id": "J1",
             "vendor_shipment_id": "VS2", "shipment_type": "ADDITIONAL", "status": "Completed",
             "business_type": "internal", "created_at": NOW},
            {"id": "J2", "job_number": "JOB-2", "po_id": "po-m", "po_number": "PO-MKL-UJI", "vendor_id": "V1",
             "vendor_name": "CMT Uji", "vendor_shipment_id": "VS3", "shipment_type": "NORMAL", "status": "In Progress",
             "business_type": "maklon", "created_at": NOW, "parent_job_id": None}]
    jis = [{"id": "JI1", "job_id": "J1", "po_item_id": "I1", "ordered_qty": 100, "produced_qty": 100, "sku": "A-M"},
           {"id": "JI2", "job_id": "J1", "po_item_id": "I2", "ordered_qty": 50, "produced_qty": 45, "sku": "A-L"},
           {"id": "JI3", "job_id": "J1", "po_item_id": "I3", "ordered_qty": 40, "produced_qty": 24, "sku": "A-S"},
           {"id": "JI4", "job_id": "J1", "po_item_id": "I4", "ordered_qty": 20, "produced_qty": 24, "sku": "A-XL"},
           {"id": "JI5", "job_id": "J1A", "po_item_id": "I3", "ordered_qty": 16, "produced_qty": 16, "sku": "A-S"},
           {"id": "JI6", "job_id": "J2", "po_item_id": "M1", "ordered_qty": 80, "produced_qty": 80, "sku": "K-M"}]
    # deklarasi CMT → DA (BUKAN kiriman ke penerima akhir) + serah terima internal + kirim ke klien maklon
    bs = [{"id": "BS-DA", "po_id": "po-i", "receiver_type": "da", "vendor_id": "V1"},
          {"id": "BS-G", "po_id": "po-i", "receiver_type": "buyer", "vendor_id": "V1", "business_type": "internal"},
          {"id": "BS-K", "po_id": "po-m", "receiver_type": "buyer", "vendor_id": "V1", "business_type": "maklon",
           "customer_name": "Klien Uji"}]
    bsi = [{"id": "B1", "shipment_id": "BS-DA", "po_id": "po-i", "po_item_id": "I1", "job_item_id": "JI1", "qty_shipped": 90},
           {"id": "B2", "shipment_id": "BS-DA", "po_id": "po-i", "po_item_id": "I2", "job_item_id": "JI2", "qty_shipped": 45},
           {"id": "B3", "shipment_id": "BS-G", "po_id": "po-i", "po_item_id": "I1", "job_item_id": "JI1", "qty_shipped": 60,
            "dispatch_date": TODAY.isoformat()},
           {"id": "B4", "shipment_id": "BS-K", "po_id": "po-m", "po_item_id": "M1", "job_item_id": "JI6", "qty_shipped": 50,
            "qty_received": 48, "dispatch_date": TODAY.isoformat(), "sku": "K-M"},
           {"id": "B5", "shipment_id": "BS-K", "po_id": "po-m", "po_item_id": "M1", "job_item_id": "JI6", "qty_shipped": 20,
            "dispatch_date": TODAY.isoformat(), "sku": "K-M"}]
    rec = [{"id": "R1", "po_id": "po-i", "business_type": "internal", "status": "completed_qc", "cmt_vendor_id": "V1",
            "cmt_name": "CMT Uji", "qc_completed_at": NOW},
           {"id": "R2", "po_id": "po-i", "business_type": "internal", "status": "on_qc", "cmt_vendor_id": "V1",
            "cmt_name": "CMT Uji"},
           {"id": "R3", "po_id": "po-m", "business_type": "maklon", "status": "completed_qc", "cmt_vendor_id": "V1",
            "cmt_name": "CMT Uji", "qc_completed_at": NOW}]
    lines = [{"id": "L1", "receipt_id": "R1", "po_item_id": "I1", "qty_claimed_by_cmt": 90, "qty_actual": 85,
              "reject_qty": 5, "qty_reworked_ok": 3},
             {"id": "L2", "receipt_id": "R1", "po_item_id": "I2", "qty_claimed_by_cmt": 45, "qty_actual": 45, "reject_qty": 0},
             {"id": "L3", "receipt_id": "R1", "po_item_id": "I3", "qty_claimed_by_cmt": 40, "qty_actual": 40, "reject_qty": 0},
             {"id": "L4", "receipt_id": "R1", "po_item_id": "I4", "qty_claimed_by_cmt": 24, "qty_actual": 24, "reject_qty": 0},
             {"id": "L5", "receipt_id": "R2", "po_item_id": "I1", "qty_claimed_by_cmt": 10, "qty_actual": None, "reject_qty": 0},
             {"id": "L6", "receipt_id": "R3", "po_item_id": "M1", "qty_claimed_by_cmt": 80, "qty_actual": 78, "reject_qty": 2}]
    permak = [{"id": "P1", "po_id": "po-i", "po_item_id": "I1", "qty": 5, "status": "selesai_berhasil",
               "qty_fixed": 3, "qty_scrap": 2, "total_cost": 15000},
              {"id": "P2", "po_id": "po-m", "po_item_id": "M1", "qty": 2, "status": "open", "total_cost": 4000}]
    shorts = [{"id": "S1", "po_id": "po-m", "po_item_id": "M1", "qty_short": 2, "qty_resolved": 0, "status": "open",
               "short_number": "SEL-BYR-1"}]
    return DB(production_pos=[pi, pm], po_items=items, vendor_shipments=vs, vendor_shipment_items=vsi,
              vendor_material_inspections=insp, vendor_material_inspection_items=insp_items,
              production_jobs=jobs, production_job_items=jis, buyer_shipments=bs, buyer_shipment_items=bsi,
              cmt_receipts=rec, cmt_receipt_lines=lines, dewi_cmt_permak=permak, buyer_short_records=shorts,
              vendor_partners=[{"id": "V1", "name": "CMT Uji", "code": "CU", "capacity_pcs": 100, "is_active": True}],
              production_variances=[
                  {"id": "VR1", "po_id": "po-i", "po_number": "PO-INT-UJI", "job_id": "J1", "job_number": "JOB-1", "vendor_id": "V1",
                   "vendor_name": "CMT Uji", "variance_type": "UNDERPRODUCTION", "business_type": "internal",
                   "items": [{"job_item_id": "JI3", "variance_qty": 16}], "total_variance_qty": 16,
                   "reason": "Potongan S ditambah lewat job tambahan", "status": "Reported", "created_at": NOW},
                  {"id": "VR2", "po_id": "po-m", "po_number": "PO-MKL-UJI", "job_id": "J2", "job_number": "JOB-2", "vendor_id": "V1",
                   "variance_type": "OVERPRODUCTION", "business_type": "maklon", "items": [], "total_variance_qty": 1,
                   "status": "Reported", "created_at": NOW}])


def by_item(lines):
    return {ln["po_item_id"]: ln for ln in lines}


# ══════════════════════ angka per baris PO (satu sumber) ══════════════════════
def test_angka_per_baris_po_dan_di_vendor_cmt():
    db = scenario()
    pos = run(pp.load_pos(db, "internal"))
    lines = by_item(run(pp.po_lines(db, pos)))
    i1, i2, i3, i4 = lines["I1"], lines["I2"], lines["I3"], lines["I4"]
    # Di vendor CMT: surat jalan berstatus Received (CMT terima BAHAN) TIDAK mengurangi; setoran & QC yang mengurangi
    assert (i1["sent_cmt"], i1["returned"], i1["in_qc"], i1["di_cmt"]) == (100, 90, 10, 0)
    assert (i2["sent_cmt"], i2["sent_extra"], i2["di_cmt"]) == (50, 5, 5)
    assert (i2["material_received"], i2["material_missing"]) == (45, 5)
    # lolos QC = lolos langsung + hasil permak; reject terurai berhasil/dibuang
    assert (i1["good_from_cmt"], i1["accepted"], i1["reject"], i1["repaired"], i1["scrap"]) == (85, 88, 5, 3, 2)
    # dikirim = serah terima ke gudang SAJA (deklarasi CMT→DA 90 tidak ikut)
    assert (i1["dispatched"], i1["shippable"]) == (60, 28)
    # produksi per baris PO menjumlah job induk + job tambahan
    assert i3["produced"] == 40 and i3["state"] == "selesai"
    assert i4["final"] == 24 and i1["state"] == "jalan"
    t = pp.sum_lines(lines.values())
    assert (t["ordered"], t["di_cmt"], t["in_qc"], t["accepted"], t["dispatched"]) == (210, 5, 10, 197, 60)
    assert t["cmt_cost"] == 5000 * (85 + 45 + 40 + 24)


def test_maklon_diterima_klien_hanya_yang_dikonfirmasi():
    db = scenario()
    m1 = by_item(run(pp.po_lines(db, run(pp.load_pos(db, "maklon")))))["M1"]
    assert (m1["dispatched"], m1["received_confirmed"], m1["pending_confirm"], m1["final"]) == (68, 48, 20, 48)
    assert (m1["accepted"], m1["reject_open"], m1["buyer_short_open"]) == (78, 2, 2)


# ══════════════════════ saringan portal di SETIAP endpoint ══════════════════════
@pytest.fixture
def api(monkeypatch):
    import routes.pantau_produksi as rp
    import routes.production_execution as pe
    db = scenario()

    async def auth(_r):
        return {"id": "u1", "name": "Staf uji", "role": "admin"}

    async def enrich(_db, jobs):   # SSOT _enrich_jobs sudah diuji sendiri; di sini cukup bentuknya
        return [{**j, "total_ordered": 0, "total_produced": 0, "total_accepted": 0, "total_reject": 0,
                 "progress_entry_source": "staff" if j["id"] == "J1" else "none", "staff_entered_progress_qty": 7,
                 "child_jobs": []} for j in jobs]
    monkeypatch.setattr(rp, "get_db", lambda: db)
    monkeypatch.setattr(rp, "require_auth", auth)
    monkeypatch.setattr(rp, "deny_klien", lambda u: None)
    monkeypatch.setattr(rp, "is_vendor", lambda u: False)
    monkeypatch.setattr(pe, "_enrich_jobs", enrich)
    return rp, db


def _po_numbers(obj) -> set:
    found = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "po_number" and isinstance(v, str) and v:
                    found.add(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return found


def test_saringan_portal_semua_endpoint(api):
    rp, _ = api
    r = Req()
    calls = {
        "ringkasan": lambda bt: rp.get_ringkasan(r, business_type=bt, days=7),
        "vendor": lambda bt: rp.get_per_vendor(r, business_type=bt, scope="running"),
        "po": lambda bt: rp.get_per_po(r, business_type=bt, search="", status="", scope="running"),
        "kejar": lambda bt: rp.get_kejar(r, business_type=bt, scope="running", bucket=""),
        "kiriman": lambda bt: rp.get_kiriman(r, business_type=bt, po_id=""),
        "selisih": lambda bt: rp.get_selisih(r, business_type=bt, date_from="", date_to="", vendor_id="", po_id="",
                                             only_diff=False),
        "selisih_vendor": lambda bt: rp.get_selisih_vendor(r, business_type=bt, date_from="", date_to="",
                                                           vendor_id="", po_id=""),
        "selisih_klien": lambda bt: rp.get_selisih_klien(r, business_type=bt, date_from="", date_to="",
                                                         vendor_id="", po_id=""),
    }
    for name, fn in calls.items():
        internal, maklon = _po_numbers(run(fn("internal"))), _po_numbers(run(fn("maklon")))
        assert "PO-MKL-UJI" not in internal, name
        assert "PO-INT-UJI" not in maklon, name
        assert "PO-INT-UJI" in internal, name
        assert "PO-MKL-UJI" in maklon, name
    # kapasitas: beban dihitung dari SEMUA PO berjalan, dipisah internal / maklon
    kap = run(rp.get_kapasitas(r, business_type="internal", window_days=30))
    v1 = kap["vendors"][0]
    assert (v1["load_internal_pcs"], v1["load_maklon_pcs"], v1["current_load_pcs"]) == (5, 0, 5)


def test_ringkasan_alur_keseimbangan_telat_seri_dobel(api):
    rp, _ = api
    res = run(rp.get_ringkasan(Req(), business_type="internal", days=7))
    alur = {s["key"]: s["qty"] for s in res["alur"]}
    assert (alur["vendor"], alur["qc"], alur["kirim"], alur["siap"]) == (5, 10, 60, 28 + 45 + 40 + 24)
    assert res["kpi"]["di_cmt"] == 5 and res["kpi"]["in_qc"] == 10 and res["kpi"]["telat"] == 1
    assert [r["po_number"] for r in res["overdue"]] == ["PO-INT-UJI"]
    assert res["done"]["qc_today"] == 85 + 45 + 40 + 24
    assert res["duplicate_serials"]["count"] == 0          # SN-DUP dipakai PO maklon → beda portal
    assert res["biaya"]["biaya_permak"] == 15000            # permak maklon tidak ikut
    # I4 diproduksi 24 dari 20 potongan → "Potongan ke CMT = di CMT + QC + disetor" pecah, PO-nya disebut
    bad = {c["key"]: c for c in res["balance"]["checks"] if not c["ok"]}
    assert set(bad) == {"cmt"} and bad["cmt"]["offenders"] == [
        {"po_id": "po-i", "po_number": "PO-INT-UJI", "left": 210, "right": 214, "diff": -4}]
    allbt = run(pp.duplicate_serials(api[1], None))
    assert allbt["count"] == 1


def test_keseimbangan_menyebut_po_penyebab_setor_dobel():
    db = scenario()
    # setoran CMT dobel (pola PO-0001): deklarasi + penerimaan kedua 90 pcs untuk I1 yang hanya diproduksi 100
    db.cmt_receipts.docs.append({"id": "R9", "po_id": "po-i", "business_type": "internal", "status": "completed_qc"})
    db.cmt_receipt_lines.docs.append({"id": "L9", "receipt_id": "R9", "po_item_id": "I1", "qty_claimed_by_cmt": 90,
                                      "qty_actual": 90, "reject_qty": 0})
    res = run(pp.ringkasan(db, "internal"))
    bad = {c["key"]: c for c in res["balance"]["checks"] if not c["ok"]}
    assert set(bad) >= {"cmt", "produksi"}
    assert bad["cmt"]["offenders"][0]["po_number"] == "PO-INT-UJI"
    assert bad["produksi"]["offenders"][0]["left"] > bad["produksi"]["offenders"][0]["right"]


def test_per_po_cari_seri_sku_dan_status_qc(api):
    rp, _ = api
    res = run(rp.get_per_po(Req(), business_type="internal", search="a-s", status="", scope="running"))
    assert [r["po_number"] for r in res["rows"]] == ["PO-INT-UJI"]
    assert [ln["sku"] for ln in res["rows"][0]["lines"]] == ["A-S"]
    res = run(rp.get_per_po(Req(), business_type="internal", search="", status="selesai", scope="running"))
    assert res["rows"] == [] and res["counts"]["jalan"] == 1   # PO belum selesai QC penuh
    po = run(rp.get_per_po(Req(), business_type="internal", search="", status="", scope="running"))["rows"][0]
    states = {ln["sku"]: ln["state"] for ln in po["lines"]}
    assert states == {"A-L": "jalan", "A-M": "jalan", "A-S": "selesai", "A-XL": "selesai"}


def test_per_vendor_badge_staf_dan_po_tanpa_job(api):
    rp, db = api
    db.production_pos.docs.append({"id": "po-x", "po_number": "PO-INT-BARU", "business_type": "internal",
                                   "status": "Confirmed", "vendor_id": "V1", "vendor_name": "CMT Uji", "created_at": NOW})
    db.po_items.docs.append(_item("IX", {"id": "po-x", "po_number": "PO-INT-BARU"}, "B-M", "M", 30, "SN-X"))
    res = run(rp.get_per_vendor(Req(), business_type="internal", scope="running"))
    v = res["rows"][0]
    assert v["vendor_name"] == "CMT Uji" and v["di_cmt"] == 5 and v["ordered"] == 240
    assert v["entry_source"] == "staff" and [j["job_number"] for j in v["jobs"]] == ["JOB-1"]
    assert [p["po_number"] for p in v["pending_pos"]] == ["PO-INT-BARU"]


# ══════════════════════ Laporan Selisih per baris PO ══════════════════════
def test_laporan_selisih_per_baris_po_dengan_alasan():
    db = scenario()
    res = run(pp.selisih(db, "internal"))
    rows = by_item(res["rows"])
    i2 = {d["key"]: d for d in rows["I2"]["differences"]}
    assert i2["bahan_kurang"]["qty"] == -5 and "kurang 5" in i2["bahan_kurang"]["note"]
    # I3: per JOB kurang 16, per BARIS PO tidak ada selisih produksi (ditutup job tambahan)
    assert not any(d["key"] == "produksi_vs_pesan" for d in rows["I3"]["differences"])
    assert rows["I3"]["has_diff"] is False and rows["I3"]["reasons"][0]["kind"] == "laporan_vendor"
    # I4: lebih 4 dengan alasan lebih qty yang tercatat
    i4 = {d["key"]: d for d in rows["I4"]["differences"]}
    assert i4["akhir_vs_pesan"]["qty"] == 4 and i4["produksi_vs_pesan"]["qty"] == 4
    assert rows["I4"]["has_reason"] and rows["I4"]["reasons"][0]["reason"] == "Bonus potongan CMT"
    assert res["summary"]["lebih"] == 4
    # I1: 2 pcs dibuang → selisih, alasannya keputusan permak yang tercatat (bukan "tanpa alasan")
    assert [d["key"] for d in rows["I1"]["differences"]] == ["dibuang"]
    assert rows["I1"]["reasons"][0]["kind"] == "permak" and "dibuang 2" in rows["I1"]["reasons"][0]["reason"]
    # periode di luar PO → kosong; saringan PO & vendor
    assert run(pp.selisih(db, "internal", date_from="2000-01-01", date_to="2000-01-31"))["count"] == 0
    assert run(pp.selisih(db, "internal", po_id="po-m"))["count"] == 0
    assert run(pp.selisih(db, "internal", vendor_id="V-LAIN"))["count"] == 0


def test_laporan_selisih_maklon_belum_dikonfirmasi_bukan_diterima():
    db = scenario()
    m1 = run(pp.selisih(db, "maklon"))["rows"][0]
    keys = {d["key"]: d for d in m1["differences"]}
    assert m1["final"] == 48 and m1["pending_confirm"] == 20
    assert keys["belum_konfirmasi"]["kind"] == "tertunda" and keys["belum_konfirmasi"]["qty"] == -20
    assert "akhir_vs_pesan" not in keys          # masih ada yang belum dikonfirmasi / belum dikirim → bukan kurang
    klien = run(pp.buyer_receipt_rows(db, "maklon"))[0]
    assert (klien["total_shipped"], klien["total_received"], klien["total_unconfirmed"], klien["total_variance"]) \
        == (70, 48, 20, 2)
    assert klien["status"] == "belum_dikonfirmasi" and klien["qty_short_open"] == 2
    assert run(pp.buyer_receipt_rows(db, "internal"))[0]["po_number"] == "PO-INT-UJI"


def test_endpoint_lama_buyer_receipt_variance_didelegasikan(monkeypatch):
    import routes.buyer_shipment as bsr
    import core.cmt_override as ov
    db = scenario()

    async def auth(_r):
        return {"id": "u1", "name": "Staf", "role": "admin"}

    async def scope(*a, **k):
        return None
    monkeypatch.setattr(bsr, "require_auth", auth)
    monkeypatch.setattr(bsr, "deny_klien", lambda u: None)
    monkeypatch.setattr(bsr, "get_db", lambda: db)
    monkeypatch.setattr(ov, "apply_scope", scope)
    rows = run(bsr.buyer_receipt_variance(Req({"business_type": "maklon"})))
    assert [r["po_number"] for r in rows] == ["PO-MKL-UJI"] and rows[0]["total_received"] == 48
    assert rows[0]["items"][0]["unconfirmed"] == 20
    assert {r["po_number"] for r in run(bsr.buyer_receipt_variance(Req()))} == {"PO-MKL-UJI", "PO-INT-UJI"}


# ══════════════════════ endpoint lama: angka & nama isian yang dibaca layar ══════════════════════
def test_distribusi_kerja_nama_isian_dan_angka(monkeypatch):
    import routes.production_execution as pe
    db = scenario()

    async def auth(_r):
        return {"id": "u1", "name": "Staf", "role": "admin"}
    monkeypatch.setattr(pe, "require_auth", auth)
    monkeypatch.setattr(pe, "deny_klien", lambda u: None)
    monkeypatch.setattr(pe, "get_db", lambda: db)
    out = run(pe.distribusi_kerja(Req({"business_type": "internal"})))
    flat = {r["po_item_id"]: r for r in out["flat"]}
    assert flat["I1"]["shipped_to_buyer"] == 60 == flat["I1"]["shipped_to_buyer_qty"]   # dulu 150 (+deklarasi)
    assert flat["I1"]["defect_qty"] == 5 and flat["I2"]["missing_qty"] == 5
    assert flat["I2"]["remaining_production"] == 5 and flat["I1"]["deadline"] == YESTERDAY
    vend = out["hierarchy"][0]
    assert vend["total_shipped"] == vend["total_shipped_to_buyer"] == 60
    assert vend["total_missing"] == 5 and vend["total_defect"] == 5
    assert vend["pos"][0]["deadline"] == YESTERDAY
    assert {r["po_number"] for r in out["flat"]} == {"PO-INT-UJI"}


def test_dashboard_lama_di_vendor_dan_serah_terima(monkeypatch):
    import routes.production_dashboard as pd
    db = scenario()
    monkeypatch.setattr(pd, "get_db", lambda: db)
    out = run(pd.production_dashboard(business_type="internal", days=30, user={}))
    assert out["ringkasan"]["di_vendor"] == 5            # dulu 0: surat jalan `Received` dikurangkan
    assert out["handover"]["qty_total"] == 60           # dulu 150: deklarasi CMT→DA ikut
    assert out["qc"]["qty_diterima"] == 197 and out["qc"]["menunggu_qty"] == 10
    assert out["permak"]["terbuka"] == 0                # permak maklon tidak ikut
    mk = run(pd.production_dashboard(business_type="maklon", days=30, user={}))
    assert mk["handover"]["qty_total"] == 68 and mk["permak"]["terbuka"] == 1


# ══════════════════════ Kejar CMT & Kapasitas ikut PO internal ══════════════════════
def test_kejar_cmt_dan_kapasitas_ikut_po_internal():
    from services import cmt_kejar, cmt_belanja
    db = scenario()
    rows = {r["po_number"]: r for r in run(cmt_kejar.list_kejar(db, business_type="internal"))["rows"]}
    assert set(rows) == {"PO-INT-UJI"}
    r = rows["PO-INT-UJI"]
    assert (r["qty_outstanding_cmt"], r["qty_in_qc"], r["qty_sent_cmt"], r["qty_sent_extra"]) == (5, 10, 210, 5)
    assert r["qty_shipped_buyer"] == 60 and r["kali_setor"] == 1 and r["business_type"] == "internal"
    assert {x["po_number"] for x in run(cmt_kejar.list_kejar(db))["rows"]} == {"PO-MKL-UJI"}  # bawaan lama = maklon
    dash = run(cmt_kejar.owner_dashboard(db, business_type="internal"))
    assert dash["biaya_permak"] == 15000 and dash["balance"]["all_ok"] is False
    cmt = next(c for c in dash["balance"]["checks"] if c["key"] == "cmt")
    assert cmt["offenders"] == ["PO-INT-UJI"]      # bentuk lama layar Monitoring CMT: daftar nomor PO
    kap = run(cmt_belanja.capacity_overview(db))
    v = kap["vendors"][0]
    assert v["load_internal_pcs"] == 5 and v["current_load_pcs"] == 5 and v["status"] == "ok"
    assert v["daily_rate"] == round((85 + 45 + 40 + 24 + 78) / 30, 1)


def test_cek_order_baru_murni():
    cap = {"vendors": [{"vendor_id": "V1", "current_load_pcs": 50, "available_pcs": 50, "capacity_pcs": 100,
                        "daily_rate": 10.0},
                       {"vendor_id": "V2", "current_load_pcs": 0, "available_pcs": None, "capacity_pcs": 0,
                        "daily_rate": 0}]}
    ok = pp.check_new_order(cap, 40, 14)
    assert ok["feasible"] and ok["days_needed"] == 9 and ok["room_pcs"] == 50
    late = pp.check_new_order(cap, 40, 5)
    assert not late["feasible"] and any("melebihi target" in w for w in late["warnings"])
    full = pp.check_new_order(cap, 60, 30, "V1")
    assert not full["feasible"] and any("Sisa kapasitas" in w for w in full["warnings"])


def test_intake_cek_seri_cakupan_internal():
    from services import cmt_intake
    db = scenario()
    b = run(cmt_intake.intake_batches(db, scope="internal"))
    assert {x["po_number"] for x in b["batches"]} == {"PO-INT-UJI"}
    vs2 = next(x for x in b["batches"] if x["shipment_id"] == "VS2")
    assert vs2["kind"] == "REPLACEMENT" and vs2["total_received"] is None
    assert b["total_missing"] == 5
    assert {x["po_number"] for x in run(cmt_intake.intake_batches(db, scope="maklon"))["batches"]} == {"PO-MKL-UJI"}
    assert run(cmt_intake.cek_seri(db, scope="all"))["duplicate_count"] == 1


# ══════════════════════ jurnal OVER/UNDER dipensiunkan + migrasi ══════════════════════
def _load_migration():
    path = os.path.join(BACKEND, "scripts", "migrations", "2026_11_07_jurnal_selisih_produksi.py")
    spec = importlib.util.spec_from_file_location("mig_jurnal_selisih", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_jurnal_selisih_pratinjau_dan_tulis(monkeypatch):
    mod = _load_migration()
    p = mod.plan([{"id": "a"}, {"id": "b", "reversed_by_je_id": "x"}, {"id": "c", "status": "voided"}])
    assert [j["id"] for j in p["reverse"]] == ["a"] and (p["already"], p["voided"]) == (1, 1)
    db = DB(rahaza_journal_entries=[{"id": "je1", "je_number": "JE-1", "source_module": "production_variance",
                                     "status": "posted", "date": TODAY.isoformat()}],
            rahaza_journal_lines=[{"je_id": "je1", "account_code": "1-1404", "debit": 100, "credit": 0}],
            production_variances=[{"id": "v1"}])
    res = run(mod.run(db, apply=False))
    assert res["to_reverse"] == 1 and res["reversed"] == 0 and not db.production_variances.docs[0].get("gl_retired")
    import routes.rahaza_posting as rpost
    seen = []

    async def rev(_db, je, user, reason, source_module=""):
        seen.append((je["id"], len(je["lines"]), source_module))
        return {"ok": True, "je_number": "JE-2"}
    monkeypatch.setattr(rpost, "reverse_journal_entry", rev)
    res = run(mod.run(db, apply=True))
    assert res["reversed"] == 1 and seen == [("je1", 1, "production_variance_retired")]
    assert db.production_variances.docs[0]["gl_retired"] is True


# ══════════════════════ layar: cetakan, saringan portal, pendaftaran modul ══════════════════════
FE = os.path.join(REPO, "frontend", "src", "components", "erp")


def _src(*p):
    return open(os.path.join(FE, *p), encoding="utf-8").read()


def test_layar_pantau_memakai_cetakan_dan_tanpa_select_polos():
    pantau = os.path.join(FE, "pantau")
    tabs = [f for f in os.listdir(pantau) if f.endswith("Tab.jsx")] + ["DashboardAlurModule.jsx"]
    assert len(tabs) >= 12
    for f in tabs:
        s = _src("pantau", f)
        assert "<PageLayout" in s, f
        assert "<TabsList" not in s and "<table" not in s and "<h1" not in s, f
        assert not re.search(r"window\.confirm|\balert\(", s), f
    for f in os.listdir(pantau) + ["../MaklonDashboard.jsx", "../ProductionDashboardModule.jsx"]:
        s = _src("pantau", f)
        assert "<select" not in s, f
    assert "<PageLayout" in _src("ProductionDashboardModule.jsx")
    assert "<TabsList" not in _src("MaklonDashboard.jsx") and "<HubTabs" in _src("MaklonDashboard.jsx")


def test_layar_mengirim_business_type_dari_portal():
    shared = _src("pantau", "pantauShared.jsx")
    assert "portalId === 'maklon' ? 'maklon' : 'internal'" in shared
    for f in ("RingkasanTab.jsx", "PerVendorTab.jsx", "PerPOTab.jsx", "KejarCMTTab.jsx", "KirimanCMTTab.jsx",
              "KapasitasCMTTab.jsx", "DashboardAlurModule.jsx"):
        assert "business_type=${bt}" in _src("pantau", f), f
    assert "business_type=${bt}" in _src("pantau", "selisihShared.jsx")
    assert "portalBusinessType(props)" in _src("ProductionDashboardModule.jsx")


def test_registri_modul_baru_tahap9():
    reg = _src("moduleRegistry.js")
    block = reg[reg.index("// Tahap 9 (pantau)"):]
    assert "'pantau-produksi': lazyRetry(() => import('./pantau/PantauProduksiModule'))" in block
    assert "'laporan-selisih': lazyRetry(() => import('./pantau/LaporanSelisihModule'))" in block
    for old in ("prod-monitoring", "prod-work-orders", "maklon-tracking", "cmt-monitor", "prod-control-tower",
                "prod-variance", "prod-variance-report"):
        assert f"'{old}'" in reg.split("// Tahap 9 (pantau)")[0], old   # entri lama tidak diubah (wave 2)
    hub = _src("pantau", "PantauProduksiModule.jsx")
    for key in ("ringkasan", "vendor", "po", "kejar", "kiriman", "kapasitas"):
        assert f"key: '{key}'" in hub
    assert "key: 'recon'" not in hub and "stage-qty" not in hub
