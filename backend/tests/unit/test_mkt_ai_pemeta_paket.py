"""AI pemeta kolom (lapis terakhir) + impor banyak berkas satu langkah + analisis impor.

Tanpa API Anthropic sungguhan: mode tiruan (`ASISTEN_AI_FAKE=1`) atau klien tiruan Asisten AI
(`core.asisten_ai.fake.FakeAsyncAnthropic`) dengan skrip yang menjawab JSON. Basis data palsu
(`_fake_mongo`). Berkas contoh asli di `samples/` dipakai untuk sidik & rumus; tidak ada data
pembeli yang dicetak.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
os.environ.setdefault("ASISTEN_AI_FAKE", "1")

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from starlette.datastructures import UploadFile  # noqa: E402

from core import impor_ai_pemeta as ap  # noqa: E402
from core import impor_analisis as an  # noqa: E402
from core import impor_sidik as sd  # noqa: E402
from core import laporan_marketing as lm  # noqa: E402
from core import marketing_import_engine as eng  # noqa: E402
from core.asisten_ai import fake as fake_mod  # noqa: E402
from core.asisten_ai import mesin  # noqa: E402
from core.marketing_import_schema import get_source_type  # noqa: E402
import routes.marketing_data_import as md  # noqa: E402
import routes.marketing_impor_paket as pr  # noqa: E402

MO = get_source_type("marketplace_orders")
TT = REPO / "samples" / "marketplace_2026" / "pesanan_tiktok.xlsx"
CPC = REPO / "samples" / "shopee" / "shopee_ads_cpc_contoh.csv"


class _Gerbang:
    ok = True
    api_key = ""
    warning = None
    code = None
    message = ""


@pytest.fixture(autouse=True)
def _tanpa_api(monkeypatch):
    async def gerbang(uid, **kw):
        return _Gerbang()

    async def catat(*a, **k):
        return 0.0
    monkeypatch.setattr(mesin, "gerbang", gerbang)
    monkeypatch.setattr(ap, "_catat", catat)


def _tiktok(unmap=()):
    if not TT.exists():
        pytest.skip("contoh pesanan TikTok tidak ada")
    raw = TT.read_bytes()
    h, rows = eng.parse_table(raw, TT.name, MO)
    m = eng.auto_map(h, MO)
    rows, _ = eng.strip_description_rows(rows, m, MO)
    m = [dict(x, field=None, field_label=None, method="none") if x["column"] in unmap else x for x in m]
    _hasil, tabel = sd.tabel_utama(raw, TT.name)
    return raw, rows, m, tabel


# ═══ AI pemeta ═════════════════════════════════════════════════════════════════
def test_masukan_ai_tanpa_nilai_mentah_dan_membawa_deskripsi():
    raw, rows, m, tabel = _tiktok(unmap=("Buyer Username", "SKU Seller Discount", "Recipient"))
    masukan = ap.siapkan_masukan(MO, rows, m, tabel)
    teks = json.dumps(masukan, ensure_ascii=False)
    kolom = {k["kolom"]: k for k in masukan["kolom"]}
    assert set(kolom) == {"Buyer Username", "SKU Seller Discount", "Recipient"}
    assert kolom["SKU Seller Discount"]["deskripsi"]                    # kalimat baris ke-2 TikTok
    assert "kategori" not in kolom["Buyer Username"]["profil"]
    for r in rows[:40]:                                                  # nilai pribadi tidak terkirim
        for c in ("Buyer Username", "Recipient"):
            v = str(r.get(c) or "").strip()
            if len(v) >= 4:
                assert v not in teks
    # field yang sudah dipakai / dihitung sistem tidak ditawarkan
    nama = {f["field"] for f in masukan["field"]}
    assert "order_id" not in nama and "sku_subtotal_after_discount" not in nama


def test_tiruan_mengusulkan_dan_uang_lolos_rumus():
    raw, rows, m, tabel = _tiktok(unmap=("SKU Seller Discount", "Shipping Fee After Discount"))
    out = asyncio.run(ap.usulkan(MO, rows, m, user_id="u1", tabel=tabel))
    assert out["sumber"] == "tiruan" and out["kolom_dikirim"] == 2
    u = {x["kolom"]: x for x in out["usulan"]}
    assert u["SKU Seller Discount"]["field"] == "sku_seller_discount" and u["SKU Seller Discount"]["diterima"]
    assert u["SKU Seller Discount"]["uang"] and "Lolos uji rumus" in u["SKU Seller Discount"]["catatan"]


def _klien_json(jawab):
    def skrip(k):
        return [{"type": "text", "text": json.dumps(jawab, ensure_ascii=False), "citations": None}], "end_turn", {}
    return fake_mod.FakeAsyncAnthropic(skrip=skrip, jeda=0)


def test_klien_ai_usulan_uang_salah_ditolak_hakim_dan_tidak_menimpa():
    raw, rows, m, tabel = _tiktok(unmap=("SKU Subtotal Before Discount", "Shipping Fee After Discount"))
    jawab = [
        {"kolom": "Shipping Fee After Discount", "field": "sku_subtotal_before_discount", "keyakinan": 0.9,
         "alasan": "tebakan"},
        {"kolom": "SKU Subtotal Before Discount", "field": "shipping_fee_after_discount", "keyakinan": 0.8,
         "alasan": "tebakan"},
        {"kolom": "Order ID", "field": "tracking_number", "keyakinan": 1, "alasan": "mencoba menimpa"},
    ]
    klien = _klien_json(jawab)
    out = asyncio.run(ap.usulkan(MO, rows, m, user_id="u1", tabel=tabel, klien=klien))
    assert out["sumber"] == "ai"
    u = {x["kolom"]: x for x in out["usulan"]}
    assert "Order ID" not in u                                        # kolom pasti tidak pernah disentuh
    assert u["Shipping Fee After Discount"]["diterima"] is False
    assert u["SKU Subtotal Before Discount"]["diterima"] is False
    kw = klien.panggilan[0]
    assert kw["thinking"] == {"type": "adaptive"} and kw["model"] == mesin.MODEL
    isi = kw["messages"][0]["content"][0]["text"]
    assert "Shipping Fee After Discount" in isi and "</data_pihak_luar>" in isi


def test_klien_ai_jawaban_rusak_pesan_ramah():
    raw, rows, m, tabel = _tiktok(unmap=("SKU Seller Discount",))

    def skrip(k):
        return [{"type": "text", "text": "maaf, saya tidak tahu", "citations": None}], "end_turn", {}
    with pytest.raises(ap.GalatPemeta) as e:
        asyncio.run(ap.usulkan(MO, rows, m, user_id="u1", klien=fake_mod.FakeAsyncAnthropic(skrip=skrip, jeda=0)))
    assert "manual tetap bisa dipakai" in e.value.pesan


def test_gerbang_ai_menolak_pesan_ramah(monkeypatch):
    class G(_Gerbang):
        ok = False
        code = "not_configured"

    async def gerbang(uid, **kw):
        return G()
    monkeypatch.setattr(mesin, "gerbang", gerbang)
    raw, rows, m, tabel = _tiktok(unmap=("SKU Seller Discount",))
    with pytest.raises(ap.GalatPemeta) as e:
        asyncio.run(ap.usulkan(MO, rows, m, user_id="u1"))
    assert "kunci API" in e.value.pesan


def test_pemetaan_toko_disimpan_lalu_dipakai_untuk_kolom_sisa():
    db = FakeDB()
    raw, rows, m, tabel = _tiktok(unmap=("SKU Seller Discount",))
    baru = ap.terapkan(m, {"SKU Seller Discount": "sku_seller_discount"}, MO)
    h = [x["column"] for x in m]
    asyncio.run(ap.simpan_pemetaan(db, account_id="acc-tt", st=MO, headers=h, mapping=baru,
                                   user={"email": "spv@uji"}, sumber="ai_dikonfirmasi_staf"))
    t = asyncio.run(ap.ambil_pemetaan(db, "acc-tt", MO, h))
    assert t and t["sumber"] == "ai_dikonfirmasi_staf"
    m2, terisi = ap.gabung_tersimpan(m, t, MO)
    assert terisi == ["SKU Seller Discount"]
    assert next(x for x in m2 if x["column"] == "SKU Seller Discount")["method"] == "toko"
    assert asyncio.run(ap.ambil_pemetaan(db, "acc-lain", MO, h)) is None       # per toko


# ═══ Paket banyak berkas ═══════════════════════════════════════════════════════
GMV_HEAD = ["Nama kampanye", "ID Campaign", "ID produk", "Jenis materi iklan", "ID video", "Biaya", "Pesanan SKU",
            "Biaya per pesanan", "Pendapatan kotor", "Impresi iklan produk", "Jumlah klik iklan produk", "Mata uang"]


def _gmv():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(GMV_HEAD)
    ws.append(["K1", "1700000000000001", "1730000000000000001", "Video", "7600000000000000001", "260.768", 1,
               "260.768", "50000.500", 100, 5, "IDR"])
    ws.append(["K1", "1700000000000001", "1730000000000000002", "Video", "7600000000000000002", "40797.000", 6,
               "6799.500", "1138382.100", 300, 20, "IDR"])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _income_tiktok():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Order/adjustment ID", "Type", "Order settled time", "Total settlement amount", "Total revenue",
               "Subtotal after seller discounts"])
    ws.append(["T1", "Order", "10/08/2026", 90000, 100000, 100000])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _setup(monkeypatch, db, store):
    user = {"id": "u-spv", "email": "spv@uji", "name": "SPV", "role": "superadmin"}

    async def auth(_req):
        return user

    async def ctx(_db, st, account_id, c):
        return {"account": await db.marketing_platform_accounts.find_one({"id": account_id})}

    async def same(_db, _st, _s, built):
        return built

    async def nodup(*_a, **_k):
        return {}

    async def plan(sid, request, **kw):
        return {"counts": {"baru": 1}, "blockers": [], "warnings": []}

    async def noop(*a, **k):
        return None
    for mod in (md, pr):
        monkeypatch.setattr(mod, "require_auth", auth)
        monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(md, "_validate_context", ctx)
    monkeypatch.setattr(md, "_annotate_master_links", same)
    monkeypatch.setattr(md, "_annotate_existing", nodup)
    monkeypatch.setattr(md, "_put_object", lambda p, raw, ct: store.__setitem__(p, raw))
    monkeypatch.setattr(md, "_read_session_file", lambda p: store.get(p))
    monkeypatch.setattr(md, "plan", plan)
    monkeypatch.setattr(pr, "_put_object", lambda p, raw, ct: store.__setitem__(p, raw))
    monkeypatch.setattr(pr, "_get_object", lambda p: (store[p], "x") if p in store else None)
    monkeypatch.setattr(pr, "log_activity", noop)
    monkeypatch.setattr(pr, "_req_latar", lambda r: r)
    req = FakeRequest()
    req.state.user = user
    return req


def _nilai_header(raw, name, header):
    _h, t = sd.tabel_utama(raw, name)
    return next(str(r[header]).strip() for r in t.rows if r.get(header))


def test_paket_dari_unggah_sampai_simpan_berurutan_dan_batal(monkeypatch):
    if not (TT.exists() and CPC.exists()):
        pytest.skip("berkas contoh tidak ada")
    db, store = FakeDB(), {}
    req = _setup(monkeypatch, db, store)
    tt_raw, cpc_raw = TT.read_bytes(), CPC.read_bytes()
    gudang = _nilai_header(tt_raw, TT.name, "Warehouse Name")
    _h, t = sd.tabel_utama(cpc_raw, CPC.name)
    db.marketing_platform_accounts.docs += [
        {"id": "acc-tt", "account_name": "Toko TikTok Uji", "platform": "tiktok", "platform_warehouse_name": gudang,
         "status": "active"},
        {"id": "acc-tt2", "account_name": "Toko TikTok Lain", "platform": "tiktok", "status": "active"},
        {"id": "acc-sp", "account_name": "Toko Shopee Uji", "platform": "shopee", "username": t.meta["username"],
         "status": "active"},
    ]
    files = [UploadFile(file=io.BytesIO(r), filename=n) for n, r in (
        ("pesanan.xlsx", tt_raw), ("iklan.csv", cpc_raw), ("gmvmax.xlsx", _gmv()),
        ("income.xlsx", _income_tiktok()), ("entah.csv", b"Kolom A,Kolom B\n1,2\n"))]
    out = asyncio.run(pr.buat_paket(req, files=files))
    b = {x["nama"]: x for x in out["paket"]["berkas"]}
    assert b["pesanan.xlsx"]["source_type"] == "marketplace_orders" and b["pesanan.xlsx"]["account_id"] == "acc-tt"
    assert "gudang platform" in b["pesanan.xlsx"]["toko_calon"][0]["alasan"][0]
    assert b["iklan.csv"]["source_type"] == "shopee_ads_cpc" and b["iklan.csv"]["account_id"] == "acc-sp"
    assert b["gmvmax.xlsx"]["source_type"] == "tiktok_gmv_max" and b["gmvmax.xlsx"]["status"] == "perlu_isian"
    assert any("periode" in k.lower() for k in b["gmvmax.xlsx"]["kekurangan"])
    assert b["income.xlsx"]["status"] == "keuangan" and b["income.xlsx"]["jalur"] == sd.JALUR_PENCAIRAN
    assert b["entah.csv"]["status"] == "dilewati"
    pid = out["paket"]["id"]

    # staf melengkapi GMV Max: toko + periode
    gi = b["gmvmax.xlsx"]["idx"]
    asyncio.run(pr.ubah_berkas(pid, gi, pr.BerkasIn(account_id="acc-tt2", periode_mulai="2026-08-01",
                                                    periode_selesai="2026-08-31"), req))
    p2 = asyncio.run(pr.periksa_paket(pid, req))["paket"]
    b2 = {x["nama"]: x for x in p2["berkas"]}
    for n in ("pesanan.xlsx", "iklan.csv", "gmvmax.xlsx"):
        assert b2[n]["status"] == "diperiksa", (n, b2[n].get("galat"), b2[n].get("periksa"))
        assert b2[n]["sesi_id"]
    assert b2["pesanan.xlsx"]["periksa"]["invarian"]["status"] == "lolos"
    dampak = b2["pesanan.xlsx"]["periksa"]["dampak_omzet"]
    assert dampak and dampak["total_berkas"] > 0 and dampak["hari"]
    # sesi GMV Max menyimpan periode lewat nama berkas — commit membaca ulang dengan periode yang sama
    sg = next(s for s in db.marketing_data_import_sessions.docs if s["source_type"] == "tiktok_gmv_max")
    assert sg["filename"].startswith("periode_2026-08-01_2026-08-31__")

    urutan, mode = [], {}

    async def commit(sid, request, body):
        s = next(x for x in db.marketing_data_import_sessions.docs if x["id"] == sid)
        urutan.append(s["source_type"])
        mode[s["source_type"]] = body.on_duplicate
        s["status"] = "committed"
        return {"inserted": 1, "updated": 0, "skipped_duplicates": 0, "rejected": 0, "message": "ok"}
    monkeypatch.setattr(md, "commit", commit)
    res = asyncio.run(_simpan_dan_tunggu(pid, req, pr.SimpanIn(on_duplicate="skip")))
    assert urutan == ["marketplace_orders", "shopee_ads_cpc", "tiktok_gmv_max"]
    assert mode == {"marketplace_orders": "skip", "shopee_ads_cpc": "update", "tiktok_gmv_max": "update"}
    assert res["status"] == "selesai" and res["ringkas"]["baris_masuk"] == 3

    batal = []

    async def rollback(sid, request):
        batal.append(next(x for x in db.marketing_data_import_sessions.docs if x["id"] == sid)["source_type"])
        return {"message": "dibatalkan"}
    monkeypatch.setattr(md, "rollback", rollback)
    out3 = asyncio.run(pr.batalkan_paket(pid, req))
    assert batal == ["tiktok_gmv_max", "shopee_ads_cpc", "marketplace_orders"]
    assert out3["paket"]["status"] == "dibatalkan"


async def _simpan_dan_tunggu(pid, req, opsi):
    await pr.simpan_paket(pid, req, opsi)
    await asyncio.gather(*list(pr._TUGAS))
    return await pr.get_db().marketing_impor_paket.find_one({"id": pid})


def test_paket_tidak_menyimpan_ulang_sesi_partial(monkeypatch):
    db, store = FakeDB(), {}
    req = _setup(monkeypatch, db, store)
    db.marketing_impor_paket.docs.append({
        "id": "p1", "status": "diperiksa", "dibuat_oleh_id": "u-spv", "berkas": [
            {"idx": 0, "nama": "a.xlsx", "status": "diperiksa", "sesi_id": "s1", "source_type": "marketplace_orders",
             "account_id": "acc-tt", "ikut": True, "jalur": "impor"}]})
    db.marketing_data_import_sessions.docs.append({"id": "s1", "status": "partial", "source_type": "marketplace_orders"})

    async def commit(*a, **k):
        raise AssertionError("sesi partial tidak boleh di-commit ulang")
    monkeypatch.setattr(md, "commit", commit)
    res = asyncio.run(_simpan_dan_tunggu("p1", req, pr.SimpanIn()))
    assert res["berkas"][0]["status"] == "gagal" and "SEBAGIAN" in res["berkas"][0]["galat"]


def test_unggah_paket_menolak_berkas_asing_dan_zip_dibuka():
    from core import impor_paket as pk
    with pytest.raises(pk.GalatPaket):
        pk.urai_unggahan([("foto.png", b"x")])
    import zipfile
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("ekspor/a.csv", "Kolom A\n1\n")
        z.writestr("__MACOSX/._a.csv", "x")
        z.writestr("catatan.txt", "abc")
    out = pk.urai_unggahan([("semua.zip", zb.getvalue())])
    assert [n for n, _ in out] == ["a.csv", "catatan.txt"]


# ═══ Analisis impor ════════════════════════════════════════════════════════════
def test_analisis_impor_temuan_berangka():
    db = FakeDB()
    db.marketing_data_import_sessions.docs += [
        {"id": "s-o", "source_type": "marketplace_orders", "source_label": "Pesanan", "account_id": "a1",
         "account_name": "Toko A", "status": "committed", "total_rows": 10, "rejected_count": 2,
         "row_notes": [{"action": "ditolak", "why": ["Status Pesanan: nilai 'X' tidak ada di kamus"]}] * 2},
        {"id": "s-i", "source_type": "tiktok_gmv_max", "source_label": "GMV Max", "account_id": "a1",
         "account_name": "Toko A", "status": "committed", "total_rows": 3, "rejected_count": 0}]
    db.marketing_orders.docs += [
        {"_import_session_id": "s-o", "order_date": "2026-10-05", "status": "completed", "revenue_product": 100000,
         "platform_discount_total": 2000, "items": [{"catalog_item_id": None, "sku_subtotal_after_discount": 100000}]},
        {"_import_session_id": "s-o", "order_date": "2026-10-05", "status": "completed", "revenue_product": 50000,
         "platform_discount_total": 0, "items": [{"catalog_item_id": "k1", "sku_subtotal_after_discount": 50000}]}]
    db.marketing_ads_data.docs += [
        {"_import_session_id": "s-i", "campaign_name": "Rugi", "spend": 90000, "revenue": 0, "conversions": 0,
         "period_start": "2026-10-01", "period_end": "2026-10-31"},
        {"_import_session_id": "s-i", "campaign_name": "Untung", "spend": 10000, "revenue": 200000, "conversions": 4,
         "period_start": "2026-10-01", "period_end": "2026-10-31"}]
    out = asyncio.run(an.analisis_sesi(db, ["s-o", "s-i"]))
    jenis = {t["jenis"] for t in out["temuan"]}
    assert {"sku_belum_tertaut", "subsidi_platform", "iklan_boros", "baris_ditolak"} <= jenis
    t = next(x for x in out["temuan"] if x["jenis"] == "sku_belum_tertaut")
    assert t["angka"] == {"baris": 1, "dari_baris": 2, "persen": 50.0, "omzet": 100000}
    rugi = next(x for x in out["temuan"] if x["jenis"] == "iklan_boros")
    assert rugi["tingkat"] == "tinggi" and rugi["angka"]["biaya"] == 90000
    assert out["temuan"][0]["tingkat"] == "tinggi"                   # urut menurut keparahan
    assert "Toko A" in {s["toko"] for s in out["sesi"]}


# ═══ Penjaga angka Laporan Marketing ═══════════════════════════════════════════
def test_penjaga_angka_menolak_angka_karangan():
    fakta = {"kpi": {"omzet": 6855287, "persen_batal": 22.6, "pesanan": 72, "tacos_persen": 4.1},
             "per_toko": [{"toko": "A", "omzet": 1374206}]}
    ok = {"judul": "Laporan Marketing 3–9 Nov 2026", "format": ["pdf"], "bagian": [
        {"teks": "Omzet **Rp6.855.287** (≈ Rp6,9 jt) dari 72 pesanan; batal 22,6%; TACoS 4,1%. Toko A Rp1.374.206.",
         "tabel": {"kolom": ["Toko", "Omzet"], "baris": [["A", 1374206]]}}]}
    assert lm.periksa_angka(ok, fakta) == []
    karang = {"judul": "x", "format": ["pdf"], "bagian": [
        {"teks": "Omzet naik 12,5% menjadi Rp7.100.000.", "grafik": {"jenis": "batang", "x": ["a"],
                                                                     "seri": [{"nama": "s", "nilai": [999999]}]}}]}
    assert set(lm.periksa_angka(karang, fakta)) == {"12,5%", "Rp7.100.000", "999999"}


def test_periode_laporan_bawaan():
    from datetime import date
    assert lm.periode_laporan("mingguan", date(2026, 11, 9))[:2] == ("2026-11-02", "2026-11-08")
    a, b, label = lm.periode_laporan("bulanan", date(2026, 11, 9))
    assert (a, b, label) == ("2026-10-01", "2026-10-31", "Oktober 2026")
    with pytest.raises(lm.GalatLaporan):
        lm.periode_laporan("rentang", date(2026, 11, 9), "2026-01-01", "2026-12-31")


# ═══ Paket fakta Laporan Marketing & alat penjaga angka ════════════════════════
def _db_laporan():
    db = FakeDB()
    acc = {"id": "a1", "account_name": "Toko A", "platform": "tiktok", "status": "active"}
    db.marketing_platform_accounts.docs.append(acc)
    for d, rev in (("2026-11-02", 100000), ("2026-11-03", 120000), ("2026-10-27", 90000)):
        db.marketing_sales_data.docs.append({"id": d, "account_id": "a1", "date": d, "revenue_type": "total",
                                             "metrics": {"revenue": rev, "revenue_product": rev, "orders": 3},
                                             "source": "orders_auto"})
    db.marketing_ads_data.docs.append({"account_id": "a1", "date": "2026-11-02", "campaign_name": "K",
                                       "spend": 50000, "revenue": 20000})
    return db, acc


def test_paket_fakta_dari_pembaca_resmi_dengan_pembanding_dan_anomali():
    db, acc = _db_laporan()
    f = asyncio.run(lm.paket_fakta(db, [acc], jenis="mingguan", dari="2026-11-02", sampai="2026-11-08", label="x"))
    k = f["kpi"]
    assert (k["omzet"], k["pesanan"], k["belanja_iklan"], k["tacos_persen"], k["roas_iklan"]) == (220000, 6, 50000, 22.7, 0.4)
    p = f["pembanding"]["periode_sebelumnya"]
    assert p["omzet"] == 90000 and p["selisih_omzet_persen"] == 144.4
    jenis = {a["jenis"] for a in f["anomali"]}
    assert {"toko_tanpa_data", "kampanye_rugi"} <= jenis
    assert f["per_toko"][0]["hari_ada_data"] == 2 and f["kualitas_data"]["toko_tanpa_setoran"] == ["Toko A"]
    assert f["versi"] == lm.VERSI and "omzet" in f["definisi"]


def test_alat_buat_laporan_marketing_menolak_angka_di_luar_fakta():
    from datetime import date
    from core.asisten_ai import alat_base as ab
    db, acc = _db_laporan()
    f = asyncio.run(lm.paket_fakta(db, [acc], jenis="mingguan", dari="2026-11-02", sampai="2026-11-08", label="x"))
    user = {"id": "u1", "role": "owner"}
    fid = asyncio.run(lm.simpan_fakta(db, f, user))
    ctx = ab.AlatContext(user=user, cv="DA", today=date(2026, 11, 9), db=db)
    spec = {"fakta_id": fid, "judul": "Laporan Marketing", "format": ["pdf"],
            "bagian": [{"teks": "Omzet Rp220.000, naik 144,4%; iklan Rp50.000 (TACoS 22,7%). Proyeksi Rp1.000.000."}]}
    h = asyncio.run(ab.jalankan_satu("t1", "buat_laporan_marketing", spec, ctx))
    assert h.is_error and "Rp1.000.000" in h.isi and "Rp220.000" not in h.isi
    h2 = asyncio.run(ab.jalankan_satu("t2", "buat_laporan_marketing", {**spec, "fakta_id": "fakta-tidak-ada"}, ctx))
    assert h2.is_error and "paket_laporan_marketing" in h2.isi
    assert ab.cari_alat("analisis_impor") and ab.cari_alat("paket_laporan_marketing").kode


# ═══ Migrasi dasar omzet pesanan tersimpan (G5) ════════════════════════════════
def _migrasi():
    import importlib.util
    p = ROOT / "scripts" / "migrations" / "2026_11_09_omzet_basis_penjual.py"
    spec = importlib.util.spec_from_file_location("mig_2026_11_09_omzet", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_omzet_basis_penjual_idempoten_dan_pratinjau_tidak_menulis():
    mig = _migrasi()
    o = {"id": "o1", "_import_source_type": "marketplace_orders", "revenue_product": 90000, "items": [
        {"quantity": 1, "sku_subtotal_before_discount": 100000, "sku_platform_discount": 2000,
         "sku_seller_discount": 8000, "sku_subtotal_after_discount": 90000}]}
    upd, d = mig.perbaiki_pesanan(o)
    assert upd["revenue_product"] == 92000 and d == 2000
    assert upd["items"][0]["sku_subtotal_after_all_discount"] == 90000
    assert mig.perbaiki_pesanan({**o, **upd}) == (None, 0.0)                # sudah dasar baru
    db = FakeDB()
    db.marketing_orders.docs.append(dict(o))
    out = asyncio.run(mig.run(False, db=db))
    assert out == {"pesanan": 1, "naik": 1, "selisih": 2000.0}
    assert db.marketing_orders.docs[0]["revenue_product"] == 90000           # pratinjau tidak menulis
