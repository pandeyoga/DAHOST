"""Keuangan › Hutang dan Piutang satu daftar tanpa tab (11 Nov 2026, owner).

Owner: "tagihan tidak usah beda tab … piutang langsung piutang kenapa malah faktur … lebih baik filter saja … nama
menunya hutang piutang saja". Kolom Umur seperti Excel owner: HIJAU 0–7 hari, KUNING 8–14 hari, MERAH > 14 hari sejak
tanggal kirim ke CMT (jadwal hutang CMT & piutang maklon terjadwal).

Yang diuji di sini (server):
  · core.umur_kirim — batas kelompok umur dan tanggal kirim paling awal per PO/vendor;
  · /production/cmt-billing/schedules membawa umur sejak kirim;
  · /dewi/maklon/receivables (sumber SAMA untuk Portal Maklon dan Keuangan) disaring CV Keuangan + umur;
  · /rahaza/ar-invoices: `limit` dan penanda `maklon`.
"""
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402

ADMIN = {"id": "u1", "name": "Admin Uji", "role": "admin"}
HARI_INI = date(2026, 11, 11)


def run(c):
    return asyncio.run(c)


class _Headers(dict):
    def get(self, k, d=None):
        return super().get(str(k).lower(), d)


class Req:
    def __init__(self, headers=None, query=None):
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.query_params = dict(query or {})
        self.cookies = {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# core.umur_kirim
# ══════════════════════════════════════════════════════════════════════════════
def test_kelompok_umur_seperti_excel_owner():
    from core.umur_kirim import kelompok_umur
    assert [kelompok_umur(h) for h in (-1, 0, 7, 8, 14, 15, 49)] == [
        "hijau", "hijau", "hijau", "kuning", "kuning", "merah", "merah"]
    assert kelompok_umur(None) is None


def test_umur_fields():
    from core.umur_kirim import umur_fields
    assert umur_fields("2026-10-13T08:00:00", HARI_INI) == {
        "kirim_pertama": "2026-10-13", "umur_kirim_hari": 29, "umur_kirim": "merah"}
    assert umur_fields(None, HARI_INI) == {"kirim_pertama": None, "umur_kirim_hari": None, "umur_kirim": None}


def _kirim_db():
    db = FakeDB()
    db.vendor_partners.docs = [{"id": "vp1", "name": "B Lilis"}, {"id": "vp2", "name": "P Nicho"}]
    db.po_items.docs = [{"id": "pi1", "po_id": "po-1"}, {"id": "pi2", "po_id": "po-1"}, {"id": "pi3", "po_id": "po-2"}]
    db.vendor_shipments.docs = [
        {"id": "s1", "vendor_id": "vp1", "shipment_type": "NORMAL", "shipment_date": "2026-10-29"},
        {"id": "s2", "vendor_id": "vp2", "shipment_type": "NORMAL", "shipment_date": "2026-11-05"},
        # tambahan/pengganti dan surat jalan batal tidak dihitung
        {"id": "s3", "vendor_id": "vp1", "shipment_type": "ADDITIONAL", "shipment_date": "2026-09-01"},
        {"id": "s4", "vendor_id": "vp2", "shipment_type": "NORMAL", "shipment_date": "2026-09-02", "status": "Cancelled"},
        {"id": "s5", "vendor_id": "vp1", "shipment_type": "NORMAL", "shipment_date": "2026-11-09"},
    ]
    db.vendor_shipment_items.docs = [
        {"id": "x1", "shipment_id": "s1", "po_id": "po-1", "po_item_id": "pi1"},
        {"id": "x2", "shipment_id": "s2", "po_id": "po-1", "po_item_id": "pi2"},
        {"id": "x3", "shipment_id": "s3", "po_id": "po-1", "po_item_id": "pi1"},
        {"id": "x4", "shipment_id": "s4", "po_id": "po-1", "po_item_id": "pi2"},
        {"id": "x5", "shipment_id": "s5", "po_item_id": "pi3"},          # baris lama tanpa po_id
    ]
    return db


def test_tanggal_kirim_paling_awal_per_po_dan_vendor():
    from core.umur_kirim import tanggal_kirim_cmt, tanggal_untuk
    k = run(tanggal_kirim_cmt(_kirim_db(), ["po-1", "po-2", None]))
    assert tanggal_untuk(k, "po-1") == date(2026, 10, 29)                 # paling awal PO
    assert tanggal_untuk(k, "po-1", "vp2") == date(2026, 11, 5)            # per vendor
    assert tanggal_untuk(k, "po-1", "vp-lain") == date(2026, 10, 29)       # vendor tak cocok → tanggal PO
    assert tanggal_untuk(k, "po-2") == date(2026, 11, 9)                   # dicocokkan lewat po_item_id
    assert tanggal_untuk(k, "po-tidak-ada") is None
    assert run(tanggal_kirim_cmt(FakeDB(), [])) == {}


# ══════════════════════════════════════════════════════════════════════════════
# Hutang: jadwal hutang CMT membawa umur sejak kirim
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def jadwal(monkeypatch):
    import routes.production_cmt_billing as cb
    import utils.waktu as waktu
    db = _kirim_db()
    db.production_pos.docs = [{"id": "po-1", "po_number": "PO-MKL-1", "business_type": "maklon", "status": "In Production"}]
    db.dewi_cmt_ap_schedules.docs = [
        {"id": "sch-1", "po_id": "po-1", "po_number": "PO-MKL-1", "vendor_id": "vp2", "vendor_name": "P Nicho",
         "scheduled_qty": 43, "scheduled_amount": 408500, "matured_amount": 0, "status": "terjadwal",
         "updated_at": "2026-11-10"}]

    async def auth(_r):
        return dict(ADMIN)
    monkeypatch.setattr(cb, "get_db", lambda: db)
    monkeypatch.setattr(cb, "require_auth", auth)
    monkeypatch.setattr(waktu, "today_wib", lambda: HARI_INI)
    return cb


def test_jadwal_hutang_cmt_membawa_umur_kirim(jadwal):
    out = run(jadwal.list_cmt_ap_schedules(Req(headers={"X-CV": "SMU"}, query={"perkiraan_internal": "1"})))
    r = out["items"][0]
    assert (r["remaining_amount"], r["kirim_pertama"], r["umur_kirim_hari"], r["umur_kirim"]) == (
        408500, "2026-11-05", 6, "hijau")


# ══════════════════════════════════════════════════════════════════════════════
# Piutang: piutang klien maklon — satu sumber Portal Maklon & Keuangan
# ══════════════════════════════════════════════════════════════════════════════
def _ar_maklon(id_, po_id, po_number, klien, sisa):
    return {"id": id_, "invoice_number": f"AR-{po_number}", "source_module": "maklon_po", "schedule_mode": "v2",
            "linked_maklon_po_id": po_id, "linked_maklon_po_number": po_number, "customer_name": klien,
            "status": "scheduled", "total_amount": 0, "amount_paid": 0, "amount_due": 0, "scheduled_total": sisa,
            "billed_total": 0, "scheduled_remaining": sisa, "outstanding_total": sisa, "entity": "SMU",
            "created_at": "2026-11-10"}


@pytest.fixture
def piutang_maklon(monkeypatch):
    import routes.dewi_maklon_billing as mb
    db = _kirim_db()
    db.rahaza_ar_invoices.docs = [
        _ar_maklon("ar-1", "po-1", "PO-MKL-1", "SnBM", 2702500),
        _ar_maklon("ar-2", "po-2", "PO-MKL-2", "Tuku Klambi", 580500),
        {"id": "ar-da", "invoice_number": "INV-1", "source_module": "direct_sale", "status": "issued", "total": 100,
         "balance": 100},
    ]
    monkeypatch.setattr(mb, "get_db", lambda: db)
    monkeypatch.setattr(mb, "today_wib", lambda: HARI_INI)
    return mb


def test_piutang_maklon_disaring_cv_keuangan_dan_membawa_umur(piutang_maklon):
    mb = piutang_maklon
    # Portal Maklon (tanpa X-CV) → semua piutang PO maklon, perilaku lama
    semua = run(mb.list_receivables(Req(), user=ADMIN))
    assert [r["po_number"] for r in semua["items"]] == ["PO-MKL-1", "PO-MKL-2"]
    assert semua["summary"]["scheduled_remaining"] == 3283000
    r1 = semua["items"][0]
    assert (r1["entity"], r1["status"], r1["outstanding_total"], r1["kirim_pertama"], r1["umur_kirim"]) == (
        "SMU", "scheduled", 2702500, "2026-10-29", "kuning")
    # Keuangan: CV Sukma / Gabungan = angka yang sama; CV Dewi Aditya = tidak ada piutang maklon
    smu = run(mb.list_receivables(Req(headers={"X-CV": "SMU"}), user=ADMIN))
    gab = run(mb.list_receivables(Req(headers={"X-CV": "ALL"}), user=ADMIN))
    da = run(mb.list_receivables(Req(headers={"X-CV": "DA"}), user=ADMIN))
    assert smu["summary"] == gab["summary"] == semua["summary"]
    assert da["items"] == [] and da["summary"]["scheduled_remaining"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Piutang: daftar faktur membawa penanda maklon + batas baris
# ══════════════════════════════════════════════════════════════════════════════
def test_daftar_faktur_piutang_penanda_maklon_dan_limit(monkeypatch):
    import routes.rahaza_finance as rf
    db = FakeDB()
    db.rahaza_ar_invoices.docs = [
        {"id": "a1", "invoice_number": "INV-1", "source_module": "direct_sale", "status": "issued",
         "issue_date": "2026-11-01"},
        {"id": "a2", "invoice_number": "AR-MKL", "source_module": "maklon_po", "status": "scheduled",
         "issue_date": "2026-11-02", "entity": "SMU"},
        {"id": "a3", "invoice_number": "NAC-1", "source_module": "cmt_accessory", "status": "issued",
         "issue_date": "2026-11-03", "entity": "DA"},
    ]

    async def auth(_r):
        return dict(ADMIN)
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "require_auth", auth)
    gab = run(rf.list_ar(Req(headers={"X-CV": "ALL"}), limit=5000))
    assert {r["invoice_number"]: (r["entity"], r["maklon"]) for r in gab} == {
        "INV-1": ("DA", False), "AR-MKL": ("SMU", True), "NAC-1": ("DA", False)}
    assert [r["invoice_number"] for r in run(rf.list_ar(Req(headers={"X-CV": "DA"}), limit=1))] == ["NAC-1"]
