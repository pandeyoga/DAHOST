"""Kebutuhan lintas-agen dari cabang AI-impor (9 Nov 2026) — uji HERMETIK.

  1. ``POST /upload`` menerima isian ``period_start``/``period_end`` untuk GMV Max: wajib, tidak
     boleh menyeberang bulan, pesan Indonesia; diteruskan ke penormal lewat penanda nama berkas
     (staf tidak perlu mengganti nama berkasnya). Periode di nama berkas tetap diterima.
  2. GMV Max ikut ``REFRESH_ON_DUPLICATE`` (unggah ulang periode sama = diperbarui) dan pagar
     periode beririsan (``periode_iklan_bertindih``) per ``source_report``.
  3. ``completed_at`` ("Waktu Pesanan Selesai") ikut ``_FULFILLMENT_PATCH``.
  4. Retur "Refund only" (``goods_returned=False``) tidak dibuatkan Retur Fisik; alasannya dicatat.

Semua baris SINTETIS (header ekspor GMV Max nyata, tanpa data klien).
"""
import io

import openpyxl
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

import _fake_mongo as fm  # noqa: E402
from _mkt_uji import DB, SA, acc, commit, patch_import, request_for, run  # noqa: E402

from core import returns_bridge as rb  # noqa: E402
from core.marketing_import_schema import (PERIOD_INPUT_TYPES, get_source_type,  # noqa: E402
                                          source_type_catalog)

GMV_HEAD = ["Nama kampanye", "ID Campaign", "ID produk", "Jenis materi iklan", "Judul video", "ID video",
            "Akun TikTok", "Waktu posting", "Status", "Status sekunder penjelajahan", "Jenis otorisasi", "Biaya",
            "Pesanan SKU", "Biaya per pesanan", "Pendapatan kotor", "Impresi iklan produk",
            "Jumlah klik iklan produk", "Tingkat klik iklan produk", "Rasio konversi iklan", "Mata uang"]
GMV_ROWS = [
    ["K1", "1700000000000001", "1730000000000000001", "Video", "judul", "7600000000000000001", "akun_uji",
     "2024-06-01 10:00", "Dijelajahi", "Unggulan", "Resmi", "260.768", 1, "260.768", "50000.500", 100, 5, 0.05, 0.2, "IDR"],
    ["K1", "1700000000000001", "1730000000000000001", "Kartu produk", "-", "-", "-",
     "-", "Dijelajahi", "-", "N/A", "40797.000", 6, "6799.500", "1138382.100", 0, 0, 0.0, 0.0, "IDR"],
    ["K2", "1700000000000002", "1730000000000000002", "Video", "judul", "7600000000000000002", "akun_uji",
     "2025-01-01 10:00", "Tidak memenuhi syarat", "-", "N/A", "0.000", 0, "0.000", "0.000", 0, 0, 0.0, 0.0, "IDR"],
]


def _gmv_xlsx(rows=GMV_ROWS):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(GMV_HEAD)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


@pytest.fixture
def env(monkeypatch):
    db = DB()
    db.marketing_platform_accounts.docs.append(acc("TTK-01"))
    md = patch_import(monkeypatch, db)
    return db, md


def _unggah(md, fname, mulai=None, selesai=None, raw=None, **extra):
    f = UploadFile(file=io.BytesIO(raw or _gmv_xlsx()), filename=fname)
    kw = {"period_start": mulai, "period_end": selesai} if (mulai is not None or selesai is not None) else {}
    return run(md.upload(request_for(SA), file=f, source_type="tiktok_gmv_max", account_id="TTK-01",
                         host_id=None, creator_id=None, catalog_id=None, live_session_id=None, **kw, **extra))


# ═════════════════════════════ 1 — periode isian staf di /upload ═════════════════════════════════
def test_jenis_periode_isian_hanya_gmv_max_dan_ditandai_di_katalog():
    assert PERIOD_INPUT_TYPES == ("tiktok_gmv_max",)
    flag = {t["key"]: t["period_input"] for t in source_type_catalog()}
    assert flag["tiktok_gmv_max"] is True
    assert not any(v for k, v in flag.items() if k != "tiktok_gmv_max")


def test_upload_gmv_dengan_isian_periode_tanpa_ganti_nama_berkas_lalu_commit(env):
    db, md = env
    up = _unggah(md, "Ekspor GMV Max.xlsx", "2026-08-01", "2026-08-31")
    s = up["session"]
    assert s["original_filename"] == "Ekspor GMV Max.xlsx"
    assert s["filename"] == "periode_2026-08-01_2026-08-31__Ekspor GMV Max.xlsx"
    assert (s["period_start"], s["period_end"], s["period_source"]) == ("2026-08-01", "2026-08-31", "isian")
    assert s["total_rows"] == 2                               # baris berbiaya 0 dibuang penormal
    res = run(commit(md, s["id"]))
    assert res["inserted"] == 2
    rows = db.marketing_ads_data.docs
    assert {(r["period_start"], r["period_end"], r["date"]) for r in rows} == {
        ("2026-08-01", "2026-08-31", "2026-08-01")}
    assert all(r["source_report"] == "tiktok_gmv_max" for r in rows)


def test_upload_gmv_tanpa_periode_ditolak_dengan_pesan_indonesia(env):
    _db, md = env
    with pytest.raises(HTTPException) as e:
        _unggah(md, "gmvmax.xlsx")
    assert e.value.status_code == 400
    assert "Periode laporan wajib diisi" in e.value.detail and "Periode mulai" in e.value.detail


@pytest.mark.parametrize("mulai,selesai,potongan", [
    ("2026-07-15", "2026-08-14", "menyeberang bulan"),
    ("2026-08-31", "2026-08-01", "tidak boleh sesudah"),
    ("2026-08-01", "", "Isi kedua tanggal"),
    ("01/08/2026", "2026-08-31", "tidak sah"),
    ("2026-02-30", "2026-02-28", "tidak sah"),
])
def test_upload_gmv_isian_periode_salah_ditolak(env, mulai, selesai, potongan):
    db, md = env
    with pytest.raises(HTTPException) as e:
        _unggah(md, "gmvmax.xlsx", mulai, selesai)
    assert e.value.status_code == 400 and potongan in e.value.detail, e.value.detail
    assert db.marketing_data_import_sessions.docs == []       # tidak ada sesi setengah jadi


def test_upload_gmv_periode_di_nama_berkas_tetap_diterima(env):
    _db, md = env
    s = _unggah(md, "gmvmax_2026-09-01_2026-09-30.xlsx")["session"]
    assert s["filename"] == "gmvmax_2026-09-01_2026-09-30.xlsx"
    assert (s["period_start"], s["period_end"], s["period_source"]) == ("2026-09-01", "2026-09-30", "nama_berkas")
    with pytest.raises(HTTPException) as e:                    # nama berkas lintas bulan pun ditolak
        _unggah(md, "gmvmax_2026-09-20_2026-10-05.xlsx")
    assert "menyeberang bulan" in e.value.detail


def test_isian_periode_mengalahkan_periode_di_nama_berkas(env):
    _db, md = env
    s = _unggah(md, "gmvmax_2026-09-01_2026-09-30.xlsx", "2026-10-01", "2026-10-31")["session"]
    assert (s["period_start"], s["period_end"]) == ("2026-10-01", "2026-10-31")
    assert s["filename"].startswith("periode_2026-10-01_2026-10-31__")


def test_jenis_lain_mengabaikan_isian_periode_dan_bawaan_form_tidak_merusak(env):
    db, md = env
    raw = ("Tanggal,Nama Kampanye,Biaya Iklan,Impresi,Klik\n2026-08-03,Iklan A,10000,100,5\n").encode()
    f = UploadFile(file=io.BytesIO(raw), filename="iklan.csv")
    up = run(md.upload(request_for(SA), file=f, source_type="ads", account_id="TTK-01", host_id=None,
                       creator_id=None, catalog_id=None, live_session_id=None,
                       period_start="2026-07-15", period_end="2026-08-14"))
    assert up["session"]["filename"] == "iklan.csv" and "period_start" not in up["session"]
    # dipanggil langsung TANPA isian periode (impor paket lama/uji): bawaan Form(...) bukan teks
    s = _unggah(md, "gmvmax_2026-08-01_2026-08-31.xlsx")["session"]
    assert s["period_source"] == "nama_berkas"


# ═════════════════════════════ 2 — segarkan duplikat + pagar periode ═════════════════════════════
def test_gmv_unggah_ulang_periode_sama_diperbarui_beririsan_ditolak(env):
    db, md = env
    assert "tiktok_gmv_max" in md.REFRESH_ON_DUPLICATE
    s1 = _unggah(md, "gmv.xlsx", "2026-08-01", "2026-08-31")["session"]
    assert run(commit(md, s1["id"]))["inserted"] == 2
    # periode SAMA, mode bawaan "Lewati" ⇒ tetap disegarkan (angka terbaru platform)
    s2 = _unggah(md, "gmv-koreksi.xlsx", "2026-08-01", "2026-08-31")["session"]
    r2 = run(commit(md, s2["id"], on_duplicate="skip"))
    assert r2["inserted"] == 0 and r2["updated"] == 2 and len(db.marketing_ads_data.docs) == 2
    # periode BERIRISAN tetapi berbeda ⇒ biaya terhitung dua kali ⇒ ditolak
    s3 = _unggah(md, "gmv-pekan.xlsx", "2026-08-10", "2026-08-16")["session"]
    with pytest.raises(HTTPException) as e:
        run(commit(md, s3["id"]))
    assert e.value.status_code == 409 and "beririsan" in e.value.detail
    assert "2026-08-01..2026-08-31" in e.value.detail and len(db.marketing_ads_data.docs) == 2
    # periode lain yang TIDAK beririsan boleh
    s4 = _unggah(md, "gmv-sept.xlsx", "2026-09-01", "2026-09-30")["session"]
    assert run(commit(md, s4["id"]))["inserted"] == 2


def test_pagar_periode_per_jenis_laporan(env):
    """Laporan CPC Shopee berperiode di toko yang sama tidak menghalangi GMV Max (jenis lain)."""
    db, md = env
    db.marketing_ads_data.docs.append({"id": "cpc-1", "account_id": "TTK-01", "source_report": "shopee_ads_cpc",
                                       "campaign_name": "Lain", "period_start": "2026-08-05",
                                       "period_end": "2026-08-20", "date": "2026-08-05", "spend": 1})
    s = _unggah(md, "gmv.xlsx", "2026-08-01", "2026-08-31")["session"]
    assert run(commit(md, s["id"]))["inserted"] == 2


# ═════════════════════════════ 3 — completed_at di patch fulfillment ═════════════════════════════
def test_completed_at_ikut_patch_fulfillment_dan_bisa_dipulihkan(monkeypatch):
    import routes.marketing_data_import as md
    assert "completed_at" in md._FULFILLMENT_PATCH
    st = get_source_type("marketplace_fulfillment")
    existing = {"id": "o1", "order_id": "5800000000000001", "account_id": "TTK-01", "status": "completed"}
    doc = {"order_id": existing["order_id"], "completed_at": "2026-08-10T10:00:00"}
    act, _why, changes, _h = md._plan_fulfillment_row(st, doc, existing)
    assert act == "diperbarui" and [c["field"] for c in changes] == ["completed_at"]

    db = fm.FakeDB()
    db.marketing_orders.docs.append(dict(existing))
    act, _why, undo = run(md._apply_fulfillment_row(db, st, doc, dict(existing), SA, "sesi-1"))
    assert act == "diperbarui"
    assert db.marketing_orders.docs[0]["completed_at"] == "2026-08-10T10:00:00"
    assert "completed_at" in undo["before"] and undo["before"]["completed_at"] is None


# ═════════════════════════════ 4 — retur "Refund only" tanpa Retur Fisik ═════════════════════════
async def _kode(db):
    db._n = getattr(db, "_n", 0) + 1
    return f"RET-UJI-{db._n:03d}"


@pytest.fixture
def rdb(monkeypatch):
    monkeypatch.setattr(rb, "_next_code", _kode)
    return fm.FakeDB()


def _ret(rid, goods, **kw):
    r = {"id": rid, "order_id": f"P-{rid}", "status": "completed", "product": "Kaos", "qty": 1,
         "refund_amount": 50000, "refund_type_raw": "Refund only" if goods is False else "Return and refund", **kw}
    if goods is not None:
        r["goods_returned"] = goods
    return r


def test_refund_only_tidak_membuat_retur_fisik_dan_alasan_dicatat(rdb):
    ret = _ret("R1", False)
    rdb.marketing_returns.docs.append(dict(ret))
    out = run(rb.ensure_wh_return(rdb, ret, actor={"name": "uji"}))
    assert out["created"] is False and out["skipped"] is True and out["wh_return"] is None
    assert "Refund only" in out["reason"] and out["message"].startswith("Retur fisik tidak dibuat")
    assert rdb.wh_returns.docs == []
    stamped = rdb.marketing_returns.docs[0]
    assert "Refund only" in stamped["wh_skip_reason"] and stamped["wh_sync_ok"] is True
    assert not stamped.get("wh_return_id")


def test_barang_kembali_atau_tidak_diketahui_tetap_dibuatkan(rdb):
    for rid, goods in (("R2", True), ("R3", None)):
        ret = _ret(rid, goods)
        rdb.marketing_returns.docs.append(dict(ret))
        out = run(rb.ensure_wh_return(rdb, ret, actor={"name": "uji"}))
        assert out["created"] is True and not out.get("skipped"), rid
    assert len(rdb.wh_returns.docs) == 2


def test_pekerjaan_lama_tidak_disentuh_walau_kini_refund_only(rdb):
    ret = _ret("R4", True)
    rdb.marketing_returns.docs.append(dict(ret))
    first = run(rb.ensure_wh_return(rdb, ret))
    again = run(rb.ensure_wh_return(rdb, {**ret, "goods_returned": False}))
    assert again["created"] is False and not again.get("skipped")
    assert again["wh_return"]["id"] == first["wh_return"]["id"] and len(rdb.wh_returns.docs) == 1


def test_sync_all_melewati_refund_only(rdb):
    for r in (_ret("R5", False), _ret("R6", True)):
        rdb.marketing_returns.docs.append(r)
    dry = run(rb.sync_all(rdb, dry_run=True))
    assert dry["skipped"] >= 1 and any(d.get("skipped") and d["marketing_return_id"] == "R5" for d in dry["details"])
    assert rdb.wh_returns.docs == []
    real = run(rb.sync_all(rdb))
    assert real["created"] == 1 and [w["source_marketing_return_id"] for w in rdb.wh_returns.docs] == ["R6"]
    assert "Refund only" in next(r for r in rdb.marketing_returns.docs if r["id"] == "R5")["wh_skip_reason"]


def test_impor_retur_menghitung_refund_only_terpisah(rdb, monkeypatch):
    import routes.marketing_data_import as md
    from core import marketing_returns as mret

    async def _rekap(*_a, **_k):
        return {}
    monkeypatch.setattr(mret, "refresh_rekap_for_docs", _rekap)
    for r in (_ret("R7", False), _ret("R8", True), _ret("R9", True, status="rejected")):
        rdb.marketing_returns.docs.append({**r, "_import_session_id": "S1"})
    out = run(md._after_returns_import(rdb, "S1", SA))
    assert (out["wh_created"], out["wh_refund_only"], out["failed"]) == (1, 1, 0)
    assert [w["source_marketing_return_id"] for w in rdb.wh_returns.docs] == ["R8"]
