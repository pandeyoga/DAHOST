"""Pemantauan staf › Alur kerja harian (permintaan owner 14 Nov 2026) — uji unit hermetik (Mongo palsu).

Contoh nyata audit 13 Nov yang harus terlihat jelas di layar: PO dibuat tetapi masih draf (kiriman CMT dari PO draf =
merah), semua scan keluar dibatalkan, order cutting 50 → hasil 93, belum ada biaya iklan, dan akun tanpa aktivitas.
Mencakup juga: langkah berurutan, alur macet di langkah pertama yang lewat batas, pelaku dari dokumen / log aktivitas,
pekerjaan per staf dalam kalimat, rute (hanya owner & admin, tanggal tidak di masa depan), dan alat Asisten AI.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _fake_mongo import FakeDB  # noqa: E402
from core.pantau_staf import alur_kerja as AK  # noqa: E402

HARI = date(2026, 11, 13)          # Jumat


def run(coro):
    return asyncio.run(coro)


def wib(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc) - timedelta(hours=7)


KINI = wib(2026, 11, 13, 20, 0)


def _db():
    db = FakeDB()
    db.users.docs = [
        {"id": "u-admin", "name": "Admin Satu", "email": "a@x", "role": "admin"},
        {"id": "u-cut", "name": "Andi", "email": "f@x", "role": "spv_cutting"},
        {"id": "u-prod", "name": "Bunga", "email": "fa@x", "role": "admin_produksi"},
        {"id": "u-pic", "name": "Citra", "email": "n@x", "role": "pic_toko"},
        {"id": "u-pack", "name": "Eka", "email": "k@x", "role": "packing"},
        {"id": "u-gud", "name": "Gilang", "email": "i@x", "role": "spv_gudang"},
        {"id": "u-own", "name": "Owner", "email": "o@x", "role": "owner"},
        {"id": "u-mati", "name": "Lama", "email": "l@x", "role": "admin", "is_active": False},
        {"id": "v-1", "name": "Vendor", "email": "v@x", "role": "cmt_vendor"},
    ]
    # Cutting: CUT-20 dibuat PIC toko, dimulai & diselesaikan SPV cutting, hasil 93 dari rencana 50
    db.cutting_orders.docs = [
        {"id": "c20", "number": "CUT-T-0001", "status": "completed", "created_at": wib(2026, 11, 13, 9),
         "created_by": "u-pic", "created_by_name": "Citra", "started_at": wib(2026, 11, 13, 10),
         "completed_at": wib(2026, 11, 13, 15), "planned_output_qty": 50.0, "produced_qty": 93.0,
         "style_name": "Blouse A", "output_color": "Hitam"},
        {"id": "c31", "number": "CUT-T-0002", "status": "draft", "created_at": wib(2026, 11, 11, 9),
         "created_by": "u-pic", "created_by_name": "Citra", "planned_output_qty": 6.0, "style_name": "Setelan B"},
    ]
    db.cutting_progress.docs = [{"id": "p1", "cutting_number": "CUT-T-0001", "created_at": wib(2026, 11, 13, 14),
                                 "created_by": "u-cut", "created_by_name": "Andi", "output_qty": 93.0}]
    db.activity_logs.docs = [
        {"id": "l1", "module": "cutting.order", "action": "start", "details": "CUT-T-0001", "user_id": "u-cut",
         "user_name": "Andi", "timestamp": wib(2026, 11, 13, 10)},
        {"id": "l2", "module": "cutting.order", "action": "complete", "details": "CUT-T-0001", "user_id": "u-cut",
         "user_name": "Andi", "timestamp": wib(2026, 11, 13, 15)},
        {"id": "l3", "module": "rahaza.material", "action": "update", "details": "m-kain", "user_id": "u-gud",
         "user_name": "Gilang", "timestamp": wib(2026, 11, 12, 15)},     # kemarin: tidak dihitung hari ini
        {"id": "l4", "module": "Auth", "action": "Login", "details": "", "user_id": "u-admin",
         "timestamp": wib(2026, 11, 13, 8)},
    ]
    # PO: PO-MKL dibuat hari ini masih draf padahal kirimannya sudah jalan; PO-INT lama masih draf (lewat batas)
    db.production_pos.docs = [
        {"id": "po1", "po_number": "PO-MKL-T01", "status": "Draft", "business_type": "maklon",
         "created_at": wib(2026, 11, 13, 10), "created_by": "Bunga", "customer_name": "Klien A"},
        {"id": "po2", "po_number": "PO-INT-T02", "status": "Draft", "business_type": "internal",
         "created_at": wib(2026, 11, 10, 10), "created_by": "Bunga"},
        {"id": "po0", "po_number": "PO-INT-T00", "status": "Draft", "business_type": "internal",
         "created_at": wib(2026, 11, 1, 10), "created_by": "Bunga", "opening_import": {"batch": "x"}},
    ]
    db.vendor_shipments.docs = [{"id": "s1", "shipment_number": "SHP-T01", "po_id": "po1", "po_number": "PO-MKL-T01",
                                 "status": "Sent", "created_at": wib(2026, 11, 13, 11), "created_by": "Bunga",
                                 "vendor_name": "CMT Satu"}]
    # Scan keluar: semua baris dibatalkan, lembar ditutup otomatis sistem
    db.wh_scan_out_lines.docs = [
        {"id": f"sl{i}", "date": "2026-11-13", "status": "voided", "qty": 2, "sku": f"SKU-T-{i}",
         "operator_id": "u-pack", "voided_by_id": "u-pack", "voided_by": "Eka"} for i in range(3)]
    db.wh_scan_out_sheets.docs = [{"id": "sh1", "number": "SKP-20261113-GD", "date": "2026-11-13", "status": "closed",
                                   "auto_closed": True, "closed_at": wib(2026, 11, 13, 23, 55)}]
    # Marketplace: satu toko mode impor, impor pesanan oleh PIC toko; belum ada biaya iklan
    db.marketing_platform_accounts.docs = [{"id": "T1", "account_name": "Toko A", "status": "active",
                                            "pic_user_id": "u-pic", "sales_input_mode": "impor_pesanan"}]
    db.marketing_data_import_sessions.docs = [
        {"id": "i1", "status": "committed", "committed_at": wib(2026, 11, 13, 9, 30), "created_by_id": "u-pic",
         "committed_by": "Citra", "committed_count": 217, "updated_count": 0, "account_name": "Toko A",
         "target_collection": "marketing_orders", "source_type": "marketplace_orders"}]
    db.pantau_aktivitas_harian.docs = [{"id": "u-admin:2026-11-13", "user_id": "u-admin", "tanggal": "2026-11-13",
                                        "pertama": wib(2026, 11, 13, 8), "terakhir": wib(2026, 11, 13, 9), "jumlah": 4}]
    return db


def _langkah(data, alur, lid):
    g = [g for g in data["alur"] if g["alur"] == alur][0]
    return g, [x for x in g["langkah"] if x["id"] == lid][0]


def test_katalog_langkah_berurutan_dan_tautan_menu_ada():
    import re
    reg = open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src", "components", "erp",
                            "moduleRegistry.js"), encoding="utf-8").read()
    for kode in AK.ALUR:
        urut = [x.urutan for x in AK.LANGKAH if x.alur == kode]
        assert urut == sorted(urut) == list(range(1, len(urut) + 1)), kode
    assert len({x.id for x in AK.LANGKAH}) == len(AK.LANGKAH)
    for x in AK.LANGKAH:
        assert x.link_module and re.search(rf"^\s*'{re.escape(x.link_module)}':", reg, re.M), x.link_module
    # contoh owner: urutan produksi dari order cutting sampai tutup hari
    prod = [x.id for x in sorted((x for x in AK.LANGKAH if x.alur == "produksi"), key=lambda x: x.urutan)]
    assert prod == ["order_cutting", "mulai_cutting", "catat_progres", "selesai_cutting", "buat_po", "konfirmasi_po",
                    "kirim_cmt", "terima_qc", "stok_fg", "scan_keluar", "tutup_hari"]
    # kewajiban yang ditautkan memang ada di katalog Aturan Kewajiban
    from core.pantau_staf.katalog import KATALOG
    assert all(t in KATALOG for x in AK.LANGKAH for t in x.kewajiban)


def test_produksi_dikerjakan_siapa_menunggu_dan_macet():
    data = run(AK.alur_kerja(_db(), HARI, kini=KINI))
    g, oc = _langkah(data, "produksi", "order_cutting")
    assert oc["dikerjakan"] == 1 and oc["pelaku"][0]["nama"] == "Citra" and oc["jumlah"] == 50
    _, mulai = _langkah(data, "produksi", "mulai_cutting")
    assert mulai["pelaku"][0]["nama"] == "Andi" and mulai["menunggu"] == 1 and mulai["keadaan"] == "macet"
    assert mulai["rincian_tunggu"][0]["nomor"] == "CUT-T-0002" and mulai["rincian_tunggu"][0]["orang"] == "Citra"
    # alur macet di langkah PERTAMA (menurut urutan) yang lewat batas
    assert g["macet_di"] == {"urutan": 2, "nama": "Mulai cutting"} and g["kalimat"].startswith("Macet di langkah 2")
    _, sel = _langkah(data, "produksi", "selesai_cutting")
    assert sel["pelaku"][0]["nama"] == "Andi" and sel["jumlah"] == 93
    assert any("93 pcs dari rencana 50" in c["pesan"] and c["nomor"] == "CUT-T-0001" for c in sel["catatan"])
    _, prog = _langkah(data, "produksi", "catat_progres")
    assert prog["dikerjakan"] == 1 and prog["jumlah"] == 93


def test_po_draf_dan_kiriman_dari_po_draf_merah():
    data = run(AK.alur_kerja(_db(), HARI, kini=KINI))
    _, buat = _langkah(data, "produksi", "buat_po")
    assert buat["dikerjakan"] == 1 and buat["pelaku"][0]["nama"] == "Bunga"     # nama → akun
    _, konf = _langkah(data, "produksi", "konfirmasi_po")
    nomor = [t["nomor"] for t in konf["rincian_tunggu"]]
    assert "PO-INT-T00" not in nomor                       # PO saldo awal (impor) tidak dinilai
    assert konf["menunggu"] == 2 and konf["lewat_batas"] == 1 and nomor[0] == "PO-INT-T02"
    c = konf["catatan"][0]
    assert c["nada"] == "danger" and c["nomor"] == "PO-MKL-T01" and "CMT Satu" in c["pesan"]
    _, kirim = _langkah(data, "produksi", "kirim_cmt")
    assert kirim["dikerjakan"] == 1 and kirim["rincian_kerja"][0]["nomor"] == "SHP-T01"


def test_scan_keluar_dibatalkan_semua_dan_tutup_otomatis():
    data = run(AK.alur_kerja(_db(), HARI, kini=KINI))
    _, scan = _langkah(data, "produksi", "scan_keluar")
    assert scan["dikerjakan"] == 0 and scan["dibatalkan"] == 3 and scan["pelaku_batal"][0]["nama"] == "Eka"
    c = scan["catatan"][0]
    assert c["nada"] == "danger" and c["pesan"].startswith("Semua 3 baris scan keluar (6 pcs)") and "Eka" in c["pesan"]
    _, tutup = _langkah(data, "produksi", "tutup_hari")
    assert tutup["dikerjakan"] == 0 and "otomatis" in tutup["catatan"][0]["pesan"]


def test_marketplace_impor_dan_belum_ada_biaya_iklan():
    data = run(AK.alur_kerja(_db(), HARI, kini=KINI))
    _, imp = _langkah(data, "marketplace", "impor_pesanan")
    assert imp["dikerjakan"] == 1 and imp["jumlah"] == 217 and imp["pelaku"][0]["nama"] == "Citra"
    # data penjualan 12 Nov toko mode impor belum ada → menunggu PIC toko, batas pukul 10.00 hari itu (lewat)
    assert imp["menunggu"] == 1 and imp["rincian_tunggu"][0]["orang"] == "Citra" and imp["lewat_batas"] == 1
    _, iklan = _langkah(data, "marketplace", "biaya_iklan")
    assert iklan["dikerjakan"] == 0 and "belum pernah sama sekali" in iklan["catatan"][0]["pesan"]


def test_pelaku_sistem_dan_nama_tidak_dikenal():
    db = _db()
    db.dewi_rnd_styles.docs = [{"id": "st1", "style_code": "DA-1524", "created_at": wib(2026, 11, 13, 19, 56),
                                "created_by": "system", "created_by_name": "system"}]
    data = run(AK.alur_kerja(db, HARI, alur="rnd", kini=KINI))
    _, st = _langkah(data, "rnd", "style_baru")
    assert st["pelaku"][0]["nama"] == AK.NAMA_SISTEM and st["pelaku"][0]["user_id"] is None
    ctx = run(AK.siapkan(db, HARI, KINI))
    assert AK.pelaku(ctx, "migrasi-2026-11-13-centang") == (None, AK.NAMA_SISTEM)
    assert AK.pelaku(ctx, "f@x") == ("u-cut", "Andi")
    assert AK.pelaku(ctx, "2b1e6f0c-1111-2222-3333-444455556666") == (None, None)   # id asing tidak ditampilkan


def test_aktivitas_staf_kalimat_dan_tidak_aktif():
    out = run(AK.aktivitas_staf(_db(), HARI, kini=KINI))
    per = {r["user_id"]: r for r in out["items"]}
    assert "u-own" not in per and "u-mati" not in per and "v-1" not in per
    assert per["u-pic"]["keadaan"] == "bekerja"
    kalimat = [p["kalimat"] for p in per["u-pic"]["pekerjaan"]]
    assert "Impor pesanan marketplace 1× (217 baris pesanan)" in kalimat
    assert "Buat order cutting 1× (50 pcs rencana)" in kalimat
    assert per["u-admin"]["keadaan"] == "hanya_membuka" and per["u-admin"]["masuk"] == 1
    assert per["u-gud"]["keadaan"] == "tidak_aktif"            # ubahan kemarin tidak dihitung hari ini
    pack = [p["kalimat"] for p in per["u-pack"]["pekerjaan"]]
    assert per["u-pack"]["keadaan"] == "bekerja" and pack == ["Membatalkan scan barang keluar 3× (6 pcs)"]
    assert out["items"][0]["keadaan"] == "bekerja" and out["items"][-1]["keadaan"] == "tidak_aktif"
    assert out["ringkasan"]["tidak_aktif"] == 1 and out["ringkasan"]["staf"] == 6


def test_langkah_gagal_dibaca_tidak_mematikan_layar(monkeypatch):
    async def rusak(_ctx):
        raise RuntimeError("koleksi rusak")
    lk = AK.LANGKAH_BY_ID["buat_po"]
    monkeypatch.setattr(AK, "LANGKAH", [AK.Langkah(**{**lk.__dict__, "kerja": rusak}) if x is lk else x
                                        for x in AK.LANGKAH])
    data = run(AK.alur_kerja(_db(), HARI, alur="produksi", kini=KINI))
    _, buat = _langkah(data, "produksi", "buat_po")
    assert buat["galat"] and buat["dikerjakan"] == 0
    _, oc = _langkah(data, "produksi", "order_cutting")
    assert oc["dikerjakan"] == 1


def test_angka_dan_label_peran():
    assert AK.angka(1234.5) == "1.234,5" and AK.angka(404) == "404"
    assert AK.label_peran("pic_toko") == "PIC toko" and AK.label_peran("HR Generalist") == "HR Generalist"


# ── rute & Asisten AI ────────────────────────────────────────────────────────────────────────────────────
class _Req:
    def __init__(self, query=None):
        self.query_params = dict(query or {})
        self.headers = {}


def _rute(monkeypatch, db, user):
    from routes import pantau_staf as rt

    async def _auth(_req=None, *a, **k):
        return dict(user)
    monkeypatch.setattr(rt, "get_db", lambda: db)
    monkeypatch.setattr(rt, "require_auth", _auth)
    return rt


def test_rute_alur_dan_aktivitas(monkeypatch):
    from fastapi import HTTPException
    db = _db()
    rt = _rute(monkeypatch, db, {"id": "u-pic", "role": "pic_toko", "name": "Citra"})
    for coro in (rt.get_alur(_Req({"tanggal": "2026-11-13"})), rt.get_aktivitas(_Req({"tanggal": "2026-11-13"}))):
        with pytest.raises(HTTPException) as e:
            run(coro)
        assert e.value.status_code == 403
    rt = _rute(monkeypatch, db, {"id": "u-own", "role": "owner", "name": "Owner"})
    out = run(rt.get_alur(_Req({"tanggal": "2026-11-13", "alur": "produksi"})))
    assert out["tanggal"] == "2026-11-13" and [g["alur"] for g in out["alur"]] == ["produksi"]
    with pytest.raises(HTTPException) as e:
        run(rt.get_alur(_Req({"tanggal": "2026-11-13", "alur": "tidak_ada"})))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(rt.get_alur(_Req({"tanggal": "2999-01-01"})))
    assert e.value.status_code == 400 and "melewati hari ini" in e.value.detail
    akt = run(rt.get_aktivitas(_Req({"tanggal": "2026-11-13"})))
    assert akt["tanggal"] == "2026-11-13" and akt["items"]


class _CtxAI:
    def __init__(self, jawab):
        self.jawab, self.calls = jawab, []

    async def api(self, method, path, params=None, **_k):
        self.calls.append((method, path, params or {}))
        return self.jawab.get(path)


def test_alat_ai_membaca_alur_dan_aktivitas_dari_layar_yang_sama():
    from core.asisten_ai.alat import pantau_staf as alat_ps
    data = run(AK.alur_kerja(_db(), HARI, kini=KINI))
    akt = run(AK.aktivitas_staf(_db(), HARI, kini=KINI, data_alur=data))
    ctx = _CtxAI({"/api/pantau-staf/alur": data, "/api/pantau-staf/aktivitas": akt})
    out = run(alat_ps.pantau_staf(ctx, {"bagian": "alur", "tanggal": "2026-11-13"}))
    assert ctx.calls[0] == ("GET", "/api/pantau-staf/alur", {"tanggal": "2026-11-13"})
    prod = [g for g in out["hasil"]["alur"] if g["alur"].startswith("Produksi")][0]
    assert prod["keadaan"].startswith("Macet di langkah 2")
    konf = [x for x in prod["langkah"] if x["langkah"] == "Konfirmasi PO"][0]
    assert konf["menunggu_sekarang"] == 2 and any("CMT Satu" in c for c in konf["catatan"])
    out = run(alat_ps.pantau_staf(ctx, {"bagian": "aktivitas"}))
    citra = [r for r in out["hasil"]["staf"] if r["nama"] == "Citra"][0]
    assert citra["keadaan"] == "mencatat pekerjaan" and any("Impor pesanan" in k for k in citra["pekerjaan"])
    assert any(r["keadaan"] == "tidak aktif" for r in out["hasil"]["staf"])
