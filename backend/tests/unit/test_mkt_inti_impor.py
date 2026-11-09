"""MKT-INTI · impor Marketing (audit Marketing 9 Nov 2026) — uji regresi skenario s1 & s4.

  s1  Manual lebih dulu lalu impor pesanan TikTok ASLI: rekap = hitungan tangan (Rp6.855.287 /
      72 pesanan), tidak dobel, angka manual lama disimpan (`previous_metrics`, Q-5); entri manual
      sesudah impor pada tanggal turunan ditolak 409.
  M-01 PIC toko A tidak bisa mengunggah/merencanakan/menyimpan/membatalkan impor toko B (403).
  M-02 Penjadwal tidak menghapus berkas sesi yang masih dipakai (kunci relatif ≠ path absolut).
  M-03 Impor ulang mode "Lewati" tetap memajukan status batal → omzet turun (s4 #2).
  M-15 Berkas campur toko: baris yang nomornya milik toko lain DITOLAK (s4 #6b, Q-7).
  M-18 Username/ID toko di kepala laporan iklan CPC dibandingkan dengan master toko;
       berkas identik yang sedang menunggu di toko lain diperingatkan.
  M-24 Rekap impor `sales_daily` baris `live` ditolak (s4 #8).
  M-11 Commit yang terhenti di tengah meninggalkan sesi `partial` yang bisa dibatalkan.
  G15 Pesan impor tidak lagi menyuruh ke Fulfillment.
"""
import collections
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from _mkt_uji import (DB, PIC, SA, SAMPLES, SPV, acc, commit, csv_bytes, import_file,  # noqa: E402
                      patch_import, rekap, request_for, run, tiktok_orders, upload)


# ── hitungan TANGAN dari berkas asli (aturan resmi: Σ subtotal SKU sesudah diskon per pesanan,
#    batal & belum bayar keluar, dikelompokkan tanggal pesanan dibuat) ────────────────────────
def _num(v):
    s = str(v or "0").replace("IDR", "").replace("Rp", "").replace(".", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _harapan_tiktok(path):
    import openpyxl
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    ix = {k: i for i, k in enumerate(rows[0])}
    per = {}
    for r in rows[1:]:
        oid = str(r[ix["Order ID"]] or "").strip()
        if not oid.isdigit():
            continue
        o = per.setdefault(oid, {"st": r[ix["Order Status"]], "c": str(r[ix["Created Time"]]),
                                 "paid": r[ix["Paid Time"]], "sub": 0.0})
        o["sub"] += _num(r[ix["SKU Subtotal After Discount"]])
    by = collections.defaultdict(lambda: [0.0, 0])
    for o in per.values():
        st = str(o["st"] or "")
        if st in ("Dibatalkan", "Cancelled", "Canceled", "Batal"):
            continue
        if st in ("Belum dibayar", "Unpaid") and not o["paid"]:
            continue
        c = o["c"]
        day = f"{c[6:10]}-{c[3:5]}-{c[0:2]}" if c[2] == "/" else c[:10]
        by[day][0] += o["sub"]
        by[day][1] += 1
    return dict(by)


TIKTOK = SAMPLES / "pesanan_tiktok.xlsx"
SHOPEE = SAMPLES / "order_pesanan_shopee.xlsx"


@pytest.fixture
def env(monkeypatch):
    db = DB()
    for a in (acc("TTK-01"), acc("TTK-02"), acc("TTK-03"), acc("SHP-01", platform="shopee")):
        db.marketing_platform_accounts.docs.append(a)
    md = patch_import(monkeypatch, db)
    return db, md


# ═════════════════════════════ s1 — manual lalu impor (berkas ASLI) ═════════════════════════════
@pytest.mark.skipif(not TIKTOK.exists(), reason="berkas contoh TikTok tidak ada")
def test_s1_manual_lalu_impor_tiktok_asli_tidak_dobel_dan_jejak_manual_disimpan(env, monkeypatch):
    db, md = env
    import routes.marketing_sales as ms
    from routes.marketing_shared import SalesDataEntry
    monkeypatch.setattr(ms, "get_db", lambda: db)

    async def _auth(req=None, *a, **k):
        req.state.user = dict(SA)
        return dict(SA)

    async def _noop(*_a, **_k):
        return None
    monkeypatch.setattr(ms, "require_auth", _auth)
    monkeypatch.setattr(ms, "log_activity", _noop)
    monkeypatch.setattr(ms, "_recalculate_health_score", _noop)

    harapan = _harapan_tiktok(TIKTOK)
    assert round(sum(v[0] for v in harapan.values())) == 6855287          # angka audit §1
    assert sum(v[1] for v in harapan.values()) == 72
    hari = sorted(harapan)[0]

    # B. manual lebih dulu (Rp1 jt / 10 pesanan)
    run(ms.create_sales_data(SalesDataEntry(account_id="TTK-01", date=hari, revenue_type="total",
                                            revenue=1_000_000, orders=10), request_for(SA),
                             override=False, override_reason=None))
    # C. impor pesanan ASLI
    sid, res = run(import_file(md, TIKTOK.read_bytes(), "pesanan_tiktok.xlsx",
                               "marketplace_orders", "TTK-01"))
    assert res["inserted"] == 93
    r = run(rekap(db, "TTK-01", hari))
    assert r["src"] == "orders_auto"
    assert round(r["omzet"]) == round(harapan[hari][0]) and r["pesanan"] == harapan[hari][1]
    # Q-5 — angka manual lama TIDAK hilang tanpa jejak
    assert r["doc"]["previous_source"] == "manual"
    assert r["doc"]["previous_metrics"]["revenue"] == 1_000_000
    # total semua hari = hitungan tangan (tidak dobel dengan manual)
    tot = sum((d.get("metrics") or {}).get("revenue", 0) for d in db.marketing_sales_data.docs
              if d["account_id"] == "TTK-01" and d["revenue_type"] == "total")
    assert round(tot) == 6855287
    # D. manual sesudah impor pada tanggal turunan → 409
    with pytest.raises(HTTPException) as e:
        run(ms.create_sales_data(SalesDataEntry(account_id="TTK-01", date=hari,
                                                revenue_type="total", revenue=777, orders=1),
                                 request_for(SA), override=False, override_reason=None))
    assert e.value.status_code == 409


@pytest.mark.skipif(not SHOPEE.exists(), reason="berkas contoh Shopee tidak ada")
def test_s2_impor_shopee_asli_rekap_agustus_sama_dengan_hitungan_tangan(env):
    import openpyxl
    db, md = env
    ws = openpyxl.load_workbook(SHOPEE, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    ix = {k: i for i, k in enumerate(rows[0])}
    per = {}
    for r in rows[1:]:
        o = per.setdefault(str(r[ix["No. Pesanan"]]).strip(),
                           {"st": r[ix["Status Pesanan"]], "d": str(r[ix["Waktu Pesanan Dibuat"]])[:10],
                            "sub": 0.0})
        o["sub"] += _num(r[ix["Subtotal Pesanan"]])
    aug = sum(o["sub"] for o in per.values() if o["st"] != "Batal" and o["d"].startswith("2026-08"))
    assert round(aug) == 4871855                                           # angka audit §1
    run(import_file(md, SHOPEE.read_bytes(), "order_pesanan_shopee.xlsx", "marketplace_orders",
                    "SHP-01"))
    got = sum((d.get("metrics") or {}).get("revenue", 0) for d in db.marketing_sales_data.docs
              if d["account_id"] == "SHP-01" and d["revenue_type"] == "total"
              and d["date"].startswith("2026-08"))
    assert round(got) == 4871855


# ═════════════════════════════ M-01 — lingkup toko di semua pintu impor ═════════════════════════
def test_m01_pic_tidak_bisa_impor_ke_toko_yang_bukan_miliknya(env):
    db, md = env
    db.marketing_platform_accounts.docs[2]["pic_user_id"] = PIC["id"]       # PIC memegang TTK-03
    raw = tiktok_orders({"PIC000000000000001": "Perlu dikirim"})
    with pytest.raises(HTTPException) as e:
        run(upload(md, raw, "pic.csv", "marketplace_orders", "TTK-02", user=PIC))
    assert e.value.status_code == 403
    # toko miliknya sendiri tetap boleh
    up = run(upload(md, raw, "pic.csv", "marketplace_orders", "TTK-03", user=PIC))
    assert up["session"]["account_id"] == "TTK-03"
    # sesi toko lain (dibuat SPV) tidak bisa dibuka/disimpan/dibatalkan/dihapus PIC
    sid = run(upload(md, raw, "spv.csv", "marketplace_orders", "TTK-02", user=SPV))["session"]["id"]
    md._uji_user["user"] = dict(PIC)
    for coro in (md.get_session(sid, request_for(PIC), page=1, page_size=50, only=None),
                 md.plan(sid, request_for(PIC), on_duplicate="skip", skip_warnings=False, only=None,
                         q=None, page=1, page_size=50),
                 md.commit(sid, request_for(PIC), md.CommitIn()),
                 md.rollback(sid, request_for(PIC)),
                 md.delete_session(sid, request_for(PIC))):
        with pytest.raises(HTTPException) as e:
            run(coro)
        assert e.value.status_code == 403
    assert not [d for d in db.marketing_orders.docs if d["account_id"] == "TTK-02"]


def test_m01_usulan_toko_dan_pilihan_toko_wizard_hanya_toko_sendiri(env):
    db, md = env
    db.marketing_platform_accounts.docs[2]["pic_user_id"] = PIC["id"]
    md._uji_user["user"] = dict(PIC)
    out = run(md.context_options(request_for(PIC), source_type="marketplace_orders", account_id=None))
    assert [a["id"] for a in out["accounts"]] == ["TTK-03"]


# ═════════════════════════════ M-02 — penjadwal pembersih berkas ═════════════════════════════════
def test_m02_penjadwal_membandingkan_kunci_relatif_bukan_path_absolut(monkeypatch, tmp_path):
    import object_storage as obj
    from utils import scheduler as sch
    monkeypatch.setattr(obj, "UPLOAD_ROOT", tmp_path)
    d = tmp_path / "marketing-data-import"
    d.mkdir()
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    for name in ("dipakai.xlsx", "yatim.xlsx", "lama_abs.xlsx"):
        p = d / name
        p.write_bytes(b"x")
        os_t = old.timestamp()
        import os
        os.utime(p, (os_t, os_t))
    db = DB()
    db.marketing_data_import_sessions.docs += [
        {"id": "s1", "file_path": "marketing-data-import/dipakai.xlsx", "status": "ready",
         "created_at": datetime.now(timezone.utc) - timedelta(days=1)},
        {"id": "s2", "file_path": "/app/uploads/marketing-data-import/lama_abs.xlsx",
         "status": "committed", "created_at": datetime.now(timezone.utc) - timedelta(days=2)},
    ]
    monkeypatch.setattr(sch, "get_db", lambda: db)
    run(sch.job_cleanup_old_marketing_uploads())
    assert (d / "dipakai.xlsx").exists()            # dulu terhapus → commit esok hari 410
    assert (d / "lama_abs.xlsx").exists()           # path lama absolut tetap dikenali
    assert not (d / "yatim.xlsx").exists()          # yatim sungguhan tetap dibersihkan


def test_m02_fungsi_murni_yatim():
    from utils import scheduler as sch
    now = datetime.now(timezone.utc)
    ref = sch._upload_key_variants("marketing-data-import/a.xlsx")
    assert not sch.marketing_upload_is_orphan("marketing-data-import/a.xlsx", ref,
                                              mtime=now - timedelta(hours=3), now=now)
    assert sch.marketing_upload_is_orphan("marketing-data-import/b.xlsx", ref,
                                          mtime=now - timedelta(hours=3), now=now)
    assert not sch.marketing_upload_is_orphan("marketing-data-import/b.xlsx", None,
                                              mtime=now - timedelta(hours=3), now=now)
    assert not sch.marketing_upload_is_orphan("marketing-data-import/b.xlsx", ref,
                                              mtime=now, now=now)


# ═════════════════════════════ M-03 — Lewati tetap memajukan status ══════════════════════════════
def test_m03_impor_ulang_lewati_membawa_kabar_batal_dan_omzet_turun(env):
    db, md = env
    ids = {f"UJI{n:015d}": "Perlu dikirim" for n in range(1, 6)}          # 5 × Rp100.000, 3 Agt
    run(import_file(md, tiktok_orders(ids), "a.csv", "marketplace_orders", "TTK-02"))
    assert run(rekap(db, "TTK-02", "2026-08-03"))["omzet"] == 500000
    ids2 = dict(ids)
    ids2["UJI000000000000001"] = "Dibatalkan"
    ids2["UJI000000000000002"] = "Dibatalkan"
    # rencana (pratinjau) menyebut perubahan status walau mode Lewati
    up = run(upload(md, tiktok_orders(ids2), "a_baru.csv", "marketplace_orders", "TTK-02"))
    sid = up["session"]["id"]
    pl = run(md.plan(sid, request_for(SA), on_duplicate="skip", skip_warnings=False, only=None,
                     q=None, page=1, page_size=50))
    assert pl["counts"]["diperbarui"] == 2 and pl["counts"]["dilewati"] == 3
    res = run(commit(md, sid, on_duplicate="skip"))
    assert res["updated"] == 2 and res["skipped_duplicates"] == 3
    r = run(rekap(db, "TTK-02", "2026-08-03"))
    assert r["omzet"] == 300000 and r["pesanan"] == 3                      # dulu tetap 500.000
    st = {d["order_id"]: d["status"] for d in db.marketing_orders.docs}
    assert st["UJI000000000000001"] == "cancelled"
    # status MUNDUR tetap ditolak (berkas lama diunggah lagi)
    _sid, res = run(import_file(md, tiktok_orders(ids), "lama.csv", "marketplace_orders", "TTK-02"))
    assert res["updated"] == 0
    assert {d["order_id"]: d["status"] for d in db.marketing_orders.docs}["UJI000000000000001"] == "cancelled"
    # rollback sesi "Lewati" memulihkan statusnya lewat jejak UNDO (sejauh aturan status mengizinkan)
    assert db.marketing_data_import_undo.docs and all(
        u["status_before"] for u in db.marketing_data_import_undo.docs if u["session_id"] == sid)


# ═════════════════════════════ M-15 / Q-7 — berkas campur toko ═══════════════════════════════════
def test_m15_berkas_campur_baris_milik_toko_lain_ditolak(env):
    db, md = env
    ids = {f"UJI{n:015d}": "Perlu dikirim" for n in range(1, 6)}
    run(import_file(md, tiktok_orders(ids), "a.csv", "marketplace_orders", "TTK-02"))
    # berkas SAMA ke toko lain → penghalang (mayoritas milik toko lain)
    with pytest.raises(HTTPException) as e:
        run(import_file(md, tiktok_orders(ids), "a.csv", "marketplace_orders", "TTK-03"))
    assert e.value.status_code == 409
    mix = {**dict(list(ids.items())[:2]), **{f"BARU{n:014d}": "Perlu dikirim" for n in range(1, 6)}}
    up = run(upload(md, tiktok_orders(mix), "campur.csv", "marketplace_orders", "TTK-03"))
    pl = run(md.plan(up["session"]["id"], request_for(SA), on_duplicate="skip", skip_warnings=False,
                     only=None, q=None, page=1, page_size=50))
    assert pl["counts"]["ditolak"] == 2 and pl["counts"]["baru"] == 5
    res = run(commit(md, up["session"]["id"]))
    assert res["inserted"] == 5 and res["rejected"] == 2
    assert sum(1 for d in db.marketing_orders.docs if d["order_id"] == "UJI000000000000001") == 1
    assert any("sudah tercatat di toko" in " ".join(n["why"]) for n in res["row_notes"])


# ═════════════════════════════ M-18 — identitas toko di kepala laporan iklan ═════════════════════
def _cpc(username, shop_id):
    return ("\n".join([
        "Laporan Iklan CPC Shopee", f"Username,{username}", "Nama Toko,Toko Uji",
        f"ID Toko,{shop_id}", "Periode,01/08/2026 - 31/08/2026", "",
        "Nama Iklan,Status,Biaya,Omzet Penjualan,Dilihat,Jumlah Klik",
        "Iklan A,Berjalan,100000,400000,1000,50",
    ]) + "\n").encode()


def test_m18_username_toko_di_berkas_cpc_dibandingkan_master(env):
    db, md = env
    db.marketing_platform_accounts.docs[3].update({"username": "toko_shp01", "platform_shop_id": "111"})
    db.marketing_platform_accounts.docs.append(acc("SHP-02", platform="shopee", username="toko_shp02",
                                                   platform_shop_id="222"))
    with pytest.raises(HTTPException) as e:
        run(import_file(md, _cpc("toko_shp02", "222"), "iklan.csv", "shopee_ads_cpc", "SHP-01"))
    assert e.value.status_code == 409 and "username toko" in e.value.detail
    _sid, res = run(import_file(md, _cpc("toko_shp01", "111"), "iklan.csv", "shopee_ads_cpc", "SHP-01"))
    assert res["inserted"] == 1


def test_m18_berkas_identik_menunggu_di_toko_lain_diperingatkan(env):
    db, md = env
    raw = tiktok_orders({"SAMA00000000000001": "Perlu dikirim"})
    run(upload(md, raw, "x.csv", "marketplace_orders", "TTK-02"))          # belum disimpan
    up = run(upload(md, raw, "x.csv", "marketplace_orders", "TTK-03"))
    pl = run(md.plan(up["session"]["id"], request_for(SA), on_duplicate="skip", skip_warnings=False,
                     only=None, q=None, page=1, page_size=50))
    assert any(w["code"] == "berkas_sama_menunggu_di_toko_lain" for w in pl["warnings"])


# ═════════════════════════════ M-24 — rekap impor baris live ═════════════════════════════════════
def test_m24_rekap_impor_baris_live_ditolak(env):
    db, md = env
    sd = csv_bytes([["date", "revenue_type", "revenue", "orders"],
                    ["2026-08-04", "total", 1234567, 12],
                    ["2026-08-04", "live", 5555555, 55]])
    _sid, res = run(import_file(md, sd, "rekap.csv", "sales_daily", "TTK-02", on_duplicate="update"))
    assert res["inserted"] == 1 and res["rejected"] == 1
    assert run(rekap(db, "TTK-02", "2026-08-04", "live")) is None
    assert run(rekap(db, "TTK-02", "2026-08-04"))["omzet"] == 1234567


# ═════════════════════════════ M-11 — commit terhenti di tengah ══════════════════════════════════
def test_m11_commit_terhenti_meninggalkan_sesi_partial_yang_bisa_dibatalkan(env, monkeypatch):
    db, md = env
    ids = {f"PRT{n:015d}": "Perlu dikirim" for n in range(1, 5)}
    up = run(upload(md, tiktok_orders(ids), "p.csv", "marketplace_orders", "TTK-02"))
    sid = up["session"]["id"]
    coll = db.marketing_orders
    orig = coll.insert_one
    n = {"i": 0}

    async def flaky(doc):
        n["i"] += 1
        if n["i"] == 3:
            raise RuntimeError("koneksi putus")
        return await orig(doc)
    monkeypatch.setattr(coll, "insert_one", flaky)
    with pytest.raises(HTTPException) as e:
        run(commit(md, sid))
    assert e.value.status_code == 500 and "Batalkan impor" in e.value.detail
    s = db.marketing_data_import_sessions.docs[-1]
    assert s["status"] == "partial" and len(s["committed_ids"]) == 2
    monkeypatch.setattr(coll, "insert_one", orig)
    with pytest.raises(HTTPException) as e:                                 # tidak boleh diulang
        run(commit(md, sid))
    assert e.value.status_code == 409
    run(md.rollback(sid, request_for(SA)))
    assert not [d for d in coll.docs if d.get("_import_session_id") == sid]
    assert run(rekap(db, "TTK-02", "2026-08-03")) is None


# ═════════════════════════════ G15 — pesan usang Fulfillment ═════════════════════════════════════
def test_g15_pesan_impor_mengarah_ke_scan_keluar():
    from pathlib import Path
    src = Path(__file__).resolve().parents[2].joinpath("routes", "marketing_data_import.py").read_text(
        encoding="utf-8")
    assert "alokasikan di Fulfillment" not in src
    assert "Scan Keluar Penjualan" in src


def test_m18_username_sama_di_platform_lain_tidak_menghalangi(env):
    """Data VPS: 'rayonagrosirsolo' dipakai Shopee Rayona DAN TikTok Rayona — bukan bentrok."""
    db, md = env
    db.marketing_platform_accounts.docs[0]["username"] = "toko_tiktok"          # TTK-01 (TikTok)
    _sid, res = run(import_file(md, _cpc("toko_tiktok", "9"), "iklan.csv", "shopee_ads_cpc", "SHP-01"))
    assert res["inserted"] == 1
