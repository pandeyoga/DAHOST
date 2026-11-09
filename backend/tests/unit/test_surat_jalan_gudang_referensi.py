"""Uji unit HERMETIK — Surat Jalan Gudang wajib berreferensi (owner, 10 Nov 2026).

Arahan owner: "surat jalan tidak bisa asal input, harus ada referensinya, dan jangan sampai double".
  * Jenis CMT / Maklon / Toko online TIDAK dibuat di Gudang → 400 berisi menu asalnya, tanpa nomor terbuang.
  * Retur ke pemasok WAJIB menunjuk Retur Pembelian yang sudah dikirim; penerima & baris diambil dari dokumen
    itu (ketikan diabaikan); satu retur = satu surat jalan aktif (409), boleh dibuat ulang sesudah dibatalkan.
  * Pindah antar lokasi: barang wajib dari master, qty ≤ stok tersedia di asal, penerima = lokasi tujuan.
  * Draf lama jenis lain tidak bisa diterbitkan/diubah (409); dokumennya tidak diubah.
  * Layar: form hanya menawarkan dua jenis, tanpa isian penerima/uraian bebas dan tanpa "Isi dari BOM".

Angka harapan dihitung tangan: retur RTP-1 = kain 4 kg + kancing 10 pcs (baris qty 0 dibuang); stok kain di L1 = 20.

Jalankan:  cd backend && python -m pytest tests/unit/test_surat_jalan_gudang_referensi.py -q
"""
import asyncio
import os
import re
import sys
from datetime import datetime, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core.stock_service import STOCK  # noqa: E402

WH = {"id": "u-gd", "name": "Gudang Uji", "email": "gd@x", "role": "admin_gudang"}
JSX = os.path.join(ROOT, "frontend", "src", "components", "erp", "WMSDeliveryNotesModule.jsx")


def run(coro):
    return asyncio.run(coro)


def _rtp(rid="R1", no="RTP-1", status="awaiting_settlement", settlement="debit_note", sent=True):
    return {"id": rid, "rtp_number": no, "status": status, "settlement": settlement,
            "sent_at": datetime(2026, 11, 9, tzinfo=timezone.utc) if sent else None,
            "supplier_id": "S1", "supplier_name": "PT Kain Jaya", "gr_number": "GR-9",
            "total_qty": 14.0, "created_at": datetime(2026, 11, 8, tzinfo=timezone.utc),
            "lines": [{"material_id": "M1", "material_code": "K-01", "material_name": "Kain Katun", "qty": 4.0,
                       "unit": "kg", "reason": "cacat tenun"},
                      {"material_id": "M2", "material_code": "A-KCG", "material_name": "Kancing", "qty": 10.0,
                       "unit": "pcs", "reason": "warna salah"},
                      {"material_id": "M3", "material_code": "X", "material_name": "Kosong", "qty": 0}]}


def _db():
    db = fm.FakeDB()
    db.rahaza_locations.docs += [{"id": "L1", "code": "GD-A", "name": "Gudang A", "storage_role": "bahan", "active": True},
                                 {"id": "L2", "code": "GD-B", "name": "Gudang B", "storage_role": "bahan", "active": True}]
    db.rahaza_materials.docs += [
        {"id": "M1", "code": "K-01", "name": "Kain Katun", "type": "fabric", "unit": "kg", "active": True},
        {"id": "M2", "code": "A-KCG", "name": "Kancing", "type": "accessory", "unit": "pcs", "active": True}]
    db[STOCK].docs += [
        {"id": "s1", "material_id": "M1", "location_id": "L1", "qty": 20.0, "reserved_quantity": 0.0},
        {"id": "s2", "material_id": "M2", "location_id": "L1", "qty": 100.0, "reserved_quantity": 0.0}]
    db.rahaza_suppliers.docs += [{"id": "S1", "name": "PT Kain Jaya", "address": "Jl. Tekstil 5", "city": "Bandung",
                                  "phone": "0812"}]
    db.rahaza_purchase_returns.docs += [
        _rtp(),
        _rtp("R2", "RTP-2", status="draft", sent=False),
        _rtp("R3", "RTP-3", status="settled", settlement="destroy"),
        _rtp("R4", "RTP-4", status="settled", settlement="accept_discount"),
        _rtp("R5", "RTP-5", status="cancelled", sent=False),
        _rtp("R6", "RTP-6", status="settled", settlement="exchange")]
    return db


@pytest.fixture
def env(monkeypatch):
    import routes.wms_delivery_notes as dn
    db = _db()
    nomor = []

    async def auth(_r):
        return WH

    async def num(db_, key, ctx=None, requested=""):
        nomor.append(ctx.get("TIPE"))
        return f"{ctx.get('TIPE')}/2026/11/{len(nomor):04d}"
    monkeypatch.setattr(dn, "require_auth", auth)
    monkeypatch.setattr(dn, "get_db", lambda: db)
    monkeypatch.setattr(dn, "issue_number", num)
    return dn, db, nomor


def _sup(dn, rid="R1", **kw):
    return dn.SJIn(sj_type="SJ-SUPPLIER", purchase_return_id=rid, **kw)


def _int(dn, lines=None, src="L1", dst="L2"):
    return dn.SJIn(sj_type="SJ-INTERNAL", from_location_id=src, to_location_id=dst,
                   lines=lines if lines is not None else [dn.SJLine(description="ketikan", qty=5, unit="kg",
                                                                    material_id="M1")])


def _gagal(coro):
    with pytest.raises(HTTPException) as e:
        run(coro)
    return e.value


# ═════════════ 1 · Jenis milik alur lain ditolak dengan menu asalnya ═════════════
@pytest.mark.parametrize("jenis,menu", [("SJ-CMT", "Produksi › Kirim ke CMT"),
                                        ("SJ-MAKLON", "Maklon/Produksi › Kirim hasil"),
                                        ("SJ-ONLINE", "Gudang › Scan Keluar Penjualan")])
def test_jenis_alur_lain_ditolak_tanpa_dokumen_dan_nomor(env, jenis, menu):
    dn, db, nomor = env
    body = dn.SJIn(sj_type=jenis, recipient_name="Siapa saja", recipient_address="Jl. X",
                   lines=[dn.SJLine(description="barang ketikan", qty=3)])
    e = _gagal(dn.create_sj(body, fm.FakeRequest()))
    assert e.status_code == 400 and menu in e.detail and "pindah antar lokasi dan retur ke pemasok" in e.detail
    assert db.wh_delivery_notes.docs == [] and nomor == []


def test_jenis_tak_dikenal_ditolak_tanpa_istilah_program(env):
    dn, db, _ = env
    e = _gagal(dn.create_sj(dn.SJIn(sj_type="SJ-APA"), fm.FakeRequest()))
    assert e.status_code == 400 and "tidak dikenal" in e.detail and "sj_type" not in e.detail


# ═════════════ 2 · Retur ke pemasok wajib Retur Pembelian yang sudah dikirim ═════════════
@pytest.mark.parametrize("rid,pesan", [("", "wajib memilih dokumen Retur Pembelian"),
                                       ("TIDAK-ADA", "tidak ditemukan"),
                                       ("R2", "belum dikirim"),
                                       ("R3", "dimusnahkan"),
                                       ("R4", "diterima dengan diskon"),
                                       ("R5", "dibatalkan")])
def test_supplier_tanpa_retur_sah_ditolak(env, rid, pesan):
    dn, db, nomor = env
    e = _gagal(dn.create_sj(_sup(dn, rid, recipient_name="Ketikan"), fm.FakeRequest()))
    assert e.status_code == 400 and pesan in e.detail, e.detail
    assert db.wh_delivery_notes.docs == [] and nomor == []


def test_supplier_penerima_dan_baris_dari_retur_bukan_ketikan(env):
    dn, db, _ = env
    body = _sup(dn, recipient_name="Penerima Ketikan", recipient_address="Alamat Ketikan",
                lines=[dn.SJLine(description="barang ketikan", qty=99)], shipper_name="Pak Budi", vehicle_no="D 1 AB")
    sj = run(dn.create_sj(body, fm.FakeRequest()))["sj"]
    assert sj["status"] == "draft" and sj["sj_type"] == "SJ-SUPPLIER"
    assert (sj["recipient_name"], sj["recipient_address"], sj["recipient_phone"]) == (
        "PT Kain Jaya", "Jl. Tekstil 5, Bandung", "0812")
    assert (sj["reference_type"], sj["reference_id"], sj["reference_no"]) == ("purchase_return", "R1", "RTP-1")
    assert [(ln["line_no"], ln["material_code"], ln["description"], ln["qty"], ln["unit"], ln["remarks"])
            for ln in sj["lines"]] == [(1, "K-01", "Kain Katun", 4.0, "kg", "cacat tenun"),
                                       (2, "A-KCG", "Kancing", 10.0, "pcs", "warna salah")]
    assert (sj["shipper_name"], sj["vehicle_no"]) == ("Pak Budi", "D 1 AB")
    # kunci retur dilepas sesudah selesai
    assert db.rahaza_purchase_returns.docs[0].get("sj_lock") is None
    # terbit = dokumen pengantar saja; stok sudah dikeluarkan Retur Pembelian
    out = run(dn.issue_sj(sj["id"], dn.IssueIn(), fm.FakeRequest()))
    assert out["stock_moved"] is False and out["sj"]["status"] == "issued"
    assert db[STOCK].docs[0]["qty"] == 20.0 and db[STOCK].docs[1]["qty"] == 100.0


def test_supplier_retur_ganda_409_dan_boleh_ulang_sesudah_batal(env):
    dn, db, nomor = env
    sj = run(dn.create_sj(_sup(dn), fm.FakeRequest()))["sj"]
    e = _gagal(dn.create_sj(_sup(dn), fm.FakeRequest()))
    assert e.status_code == 409 and "RTP-1" in e.detail and sj["sj_number"] in e.detail
    assert len(db.wh_delivery_notes.docs) == 1 and len(nomor) == 1          # nomor kedua tidak terbuang
    run(dn.issue_sj(sj["id"], dn.IssueIn(), fm.FakeRequest()))
    e = _gagal(dn.create_sj(_sup(dn), fm.FakeRequest()))                     # sudah terbit pun tetap ganda
    assert e.status_code == 409 and "terbit" in e.detail
    run(dn.cancel_sj(sj["id"], dn.CancelIn(reason="salah kendaraan"), fm.FakeRequest()))
    sj2 = run(dn.create_sj(_sup(dn), fm.FakeRequest()))["sj"]
    assert sj2["reference_id"] == "R1" and len(db.wh_delivery_notes.docs) == 2
    # retur lain (R6, tukar barang & selesai) tetap bisa dibuatkan surat jalannya sendiri
    assert run(dn.create_sj(_sup(dn, "R6"), fm.FakeRequest()))["sj"]["reference_no"] == "RTP-6"


def test_supplier_retur_sedang_dikunci_pengguna_lain_409(env):
    dn, db, nomor = env
    rtp = db.rahaza_purchase_returns.docs[0]
    rtp["sj_lock"], rtp["sj_lock_at"] = "token-orang-lain", datetime.now(timezone.utc)
    e = _gagal(dn.create_sj(_sup(dn), fm.FakeRequest()))
    assert e.status_code == 409 and "pengguna lain" in e.detail
    assert db.wh_delivery_notes.docs == [] and nomor == [] and rtp["sj_lock"] == "token-orang-lain"


def test_daftar_retur_untuk_form_hanya_yang_dikirim_dan_tandai_yang_sudah_ber_sj(env):
    dn, db, _ = env
    sj = run(dn.create_sj(_sup(dn), fm.FakeRequest()))["sj"]
    items = run(dn.list_supplier_returns(fm.FakeRequest()))["items"]
    assert sorted(x["rtp_number"] for x in items) == ["RTP-1", "RTP-6"]
    by = {x["rtp_number"]: x for x in items}
    assert by["RTP-1"]["sj_number"] == sj["sj_number"] and by["RTP-6"]["sj_number"] == ""
    assert [ln["qty"] for ln in by["RTP-1"]["lines"]] == [4.0, 10.0]


# ═════════════ 3 · Pindah antar lokasi: barang master, stok cukup, penerima = lokasi tujuan ═════════════
def test_internal_tanpa_barang_master_ditolak(env):
    dn, db, nomor = env
    e = _gagal(dn.create_sj(_int(dn, [dn.SJLine(description="barang ketikan", qty=1)]), fm.FakeRequest()))
    assert e.status_code == 400 and "dari master" in e.detail
    e = _gagal(dn.create_sj(_int(dn, dst="L1"), fm.FakeRequest()))
    assert e.status_code == 400 and "tidak boleh sama" in e.detail
    assert db.wh_delivery_notes.docs == [] and nomor == []


def test_internal_qty_melebihi_stok_asal_ditolak_saat_buat(env):
    dn, db, nomor = env
    e = _gagal(dn.create_sj(_int(dn, [dn.SJLine(description="k", qty=25, unit="kg", material_id="M1")]),
                            fm.FakeRequest()))
    assert e.status_code == 400 and "tidak cukup" in e.detail and db.wh_delivery_notes.docs == [] and nomor == []


def test_internal_penerima_lokasi_tujuan_dan_uraian_dari_master(env):
    dn, db, _ = env
    body = _int(dn)
    body.recipient_name, body.reference_no = "Penerima Ketikan", "ACUAN-KETIKAN"
    sj = run(dn.create_sj(body, fm.FakeRequest()))["sj"]
    assert sj["recipient_name"] == "Gudang B" and sj["reference_no"] == ""
    assert [(ln["material_id"], ln["description"], ln["qty_base"]) for ln in sj["lines"]] == [("M1", "Kain Katun", 5.0)]
    assert db[STOCK].docs[0]["qty"] == 20.0                                # draf belum memindah stok


# ═════════════ 4 · Data lama: tidak diubah, draf jenis lain tidak bisa diterbitkan/diubah ═════════════
def test_draf_lama_tidak_bisa_terbit_atau_diubah_tetapi_tetap_ada(env):
    dn, db, _ = env
    lama = [{"id": f"x{i}", "sj_number": f"SJ-LAMA-{i}", "sj_type": t, "status": "draft", "recipient_name": "Lama",
             "lines": [{"line_no": 1, "description": "barang", "qty": 1}]}
            for i, t in enumerate(["SJ-CMT", "SJ-MAKLON", "SJ-ONLINE", "SJ-SUPPLIER"])]
    db.wh_delivery_notes.docs += [dict(d) for d in lama]
    for d, menu in zip(lama, ["Kirim ke CMT", "Kirim hasil", "Scan Keluar Penjualan", "Retur Pembelian"]):
        e = _gagal(dn.issue_sj(d["id"], dn.IssueIn(), fm.FakeRequest()))
        assert e.status_code == 409 and menu in e.detail, e.detail
        e = _gagal(dn.update_sj(d["id"], {"recipient_name": "ubah"}, fm.FakeRequest()))
        assert e.status_code == 409
    assert [(d["status"], d["recipient_name"]) for d in db.wh_delivery_notes.docs] == [("draft", "Lama")] * 4
    # yang lama tetap bisa dibersihkan staf
    run(dn.delete_sj("x0", fm.FakeRequest()))
    assert [d["id"] for d in db.wh_delivery_notes.docs] == ["x1", "x2", "x3"]


def test_sj_cmt_terbit_dari_alur_kirim_ke_cmt_tetap_bisa_diterima(env):
    dn, db, _ = env
    db.wh_delivery_notes.docs.append({"id": "c1", "sj_number": "SJ-CMT/2026/11/0001", "sj_type": "SJ-CMT",
                                      "status": "issued", "recipient_name": "CMT A", "lines": [{"qty": 2}]})
    out = run(dn.receive_sj("c1", dn.ReceiveIn(), fm.FakeRequest()))
    assert out["sj"]["status"] == "received"
    rows = run(dn.list_sj_all_sources(fm.FakeRequest(), source="", q="", date_from="", date_to="", limit=50))
    assert [r["number"] for r in rows["items"]] == ["SJ-CMT/2026/11/0001"]


def test_update_supplier_hanya_data_pengantar(env):
    dn, db, _ = env
    sj = run(dn.create_sj(_sup(dn), fm.FakeRequest()))["sj"]
    run(dn.update_sj(sj["id"], {"recipient_name": "Ketikan", "lines": [{"description": "x", "qty": 9}],
                                "reference_id": "R6", "vehicle_no": "B 2 CD"}, fm.FakeRequest()))
    doc = db.wh_delivery_notes.docs[0]
    assert (doc["recipient_name"], doc["reference_id"], doc["vehicle_no"]) == ("PT Kain Jaya", "R1", "B 2 CD")
    assert [ln["qty"] for ln in doc["lines"]] == [4.0, 10.0]


# ═════════════ 5 · Sumber layar ═════════════
def _jsx():
    with open(JSX, encoding="utf-8") as fh:
        return fh.read()


def test_layar_form_hanya_dua_jenis_berreferensi():
    src = _jsx()
    assert "const JENIS_BUAT = ['SJ-INTERNAL', 'SJ-SUPPLIER'];" in src
    assert "JENIS_BUAT.map((k) => <option" in src and "Object.entries(SJ_TYPES).map" not in src
    # tidak ada isian bebas penerima/uraian, tidak ada "Isi dari BOM"
    for hilang in ("input-recipient-name", "input-recipient-address", "input-recipient-phone", "line-desc-",
                   "fill-from-bom-btn", "bom-material-lines", "Uraian barang"):
        assert hilang not in src, hilang
    # retur ke pemasok memilih dokumen Retur Pembelian dari daftar server; yang sudah ber-SJ tidak ditawarkan
    assert "/api/wms/delivery-notes/supplier-returns" in src and "purchase_return_id: retur.id" in src
    assert "returs.filter((x) => !x.sj_number)" in src
    # tombol buat hanya di tab SJ gudang (tab Semua sumber = rekap)
    assert src.count('data-testid="create-sj-btn"') == 1
    assert re.search(r"function TabSemuaSumber\(\{ token, onNavigate \}\)", src)
    # draf lama tidak ditawari tombol Terbitkan
    assert "n.status === 'draft' && drafSah(n)" in src and "viewDialog.status === 'draft' && drafSah(viewDialog)" in src
    for menu in ("Produksi › Kirim ke CMT", "Maklon/Produksi › Kirim hasil", "Gudang › Scan Keluar Penjualan"):
        assert menu in src
