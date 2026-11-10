"""Uji unit HERMETIK — barang jadi keluar TANPA SCAN, cari + pilih banyak (permintaan owner 10 Nov 2026).

Keputusan owner (10 Nov): fitur di DUA layar (Scan Keluar Penjualan + "Keluarkan stok"), baris diberi tanda
"Tanpa scan" (tidak masuk daftar merah), hak sama dengan scan, aturan stok sama dengan scan (stok kurang
tetap diterima & merah; 1–500 pcs per barang).

Angka harapan DIHITUNG TANGAN (fixture `env` dari test_k15_scan_out):
  * FG1 stok 10 @WAC 111.396,10 (bahan 91.396,10 + upah 20.000) · FG2 tanpa stok @WAC 50.000.
  * scan biasa FG1 ×1 + pilih tanpa scan FG1 ×3 & FG2 ×1 → stok FG1 10 − 1 − 3 = 6, FG2 0 − 1 = −1 (merah).
      nilai = 4 × 111.396,10 + 50.000 = 495.584,40 → bahan 4 × 91.396,10 + 50.000 = 415.584,40 ·
      upah 4 × 20.000 = 80.000 → Tutup Hari SATU jurnal: Dr 5-1000 415.584,40 · Dr 5-2000 80.000 / Cr 1-1404.
  * pcs tanpa scan = 3 + 1 = 4 (2 baris).
"""
import asyncio
import os
import sys
import uuid

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB, FakeRequest  # noqa: E402
from core import fg_pick as fp  # noqa: E402
from core import scan_out as so  # noqa: E402
import test_k15_scan_out as k15  # noqa: E402

SPV, USER, W = k15.SPV, k15.USER, k15.W
env = k15.env          # fixture DB palsu + stok + posting dipakai ulang (bukan disalin)


def run(coro):
    return asyncio.run(coro)


def _pick(db, items, *, kind=so.KIND_SCAN, loc="LOC-FG", user=USER, account=""):
    return run(so.pick(db, location_id=loc, items=items, kind=kind, account_id=account, user=user))


def _item(mid, qty, csid=None):
    return {"material_id": mid, "qty": qty, "client_scan_id": csid or str(uuid.uuid4())}


# ══════════════════════════ 1. rumus murni ════════════════════════════════════
def test_search_words_filter_and_sort_rules():
    assert fp.search_words("  aisar  hitam m  ") == ["aisar", "hitam", "m"]
    assert len(fp.search_words("a b c d e f g")) == fp.MAX_WORDS
    flt = fp.fg_filter("kaos (L")
    assert flt["type"] == "fg" and flt["owner_type"] == {"$ne": "client"} and flt["active"] == {"$ne": False}
    assert len(flt["$and"]) == 2
    assert {"name": {"$regex": r"\(L", "$options": "i"}} in flt["$and"][1]["$or"]   # teks di-escape
    assert "$and" not in fp.fg_filter("") and fp.fg_filter("", ids=["A"])["id"] == {"$in": ["A"]}
    assert (fp.clamp_limit("x"), fp.clamp_limit(0), fp.clamp_limit(9999)) == (50, 1, 200)
    rows = [{"code": "B", "stok_lokasi": 0}, {"code": "C", "stok_lokasi": 2}, {"code": "A", "stok_lokasi": 9}]
    assert [r["code"] for r in fp.sort_items(rows, has_location=True, searching=True)] == ["A", "C", "B"]
    assert [r["code"] for r in fp.sort_items(rows, has_location=True, searching=False)] == ["A", "C", "B"]
    rows2 = [{"code": "B", "stok_total": 1}, {"code": "A", "stok_total": 1}, {"code": "C", "stok_total": 0}]
    assert [r["code"] for r in fp.sort_items(rows2, has_location=False, searching=True)] == ["A", "B", "C"]


def test_parse_pick_items_reports_every_error_at_once():
    ok = so.parse_pick_items([_item("FG1", "3", "a"), _item("FG2", 1, "b")])
    assert ok == [{"material_id": "FG1", "qty": 3, "client_scan_id": "a"},
                  {"material_id": "FG2", "qty": 1, "client_scan_id": "b"}]
    for bad in (None, [], "x"):
        with pytest.raises(so.ScanOutError) as e:
            so.parse_pick_items(bad)
        assert e.value.status == 400
    with pytest.raises(so.ScanOutError) as e:
        so.parse_pick_items([{"material_id": "", "qty": 1, "client_scan_id": "a"},
                             {**_item("FG1", 0, "b"), "code": "DA-1101-CRL"}, _item("FG2", 501, "c"),
                             _item("FG3", 1, "d"), _item("FG3", 2, "e"), _item("FG4", 1, "d"),
                             {"material_id": "FG5", "qty": 1}])
    msg = e.value.message
    assert "Baris 1" in msg and "DA-1101-CRL: jumlah" in msg and "Barang ke-3: jumlah" in msg
    assert "Barang ke-5: dipilih dua kali" in msg and "Barang ke-6: id pilihan kembar" in msg
    assert "Barang ke-7: id pilihan wajib" in msg and "FG" not in msg   # id mentah tidak tampil ke staf
    with pytest.raises(so.ScanOutError):
        so.parse_pick_items([_item(f"M{i}", 1) for i in range(so.MAX_PICK_ITEMS + 1)])


# ══════════════════════════ 2. daftar cari ════════════════════════════════════
def test_search_lists_stock_at_location_and_hides_client_goods(env):
    db = env["db"]
    db.rahaza_materials.docs.append({"id": "FG3", "code": "DA-3303-HTM-M", "name": "Aisar", "type": "fg",
                                     "color_name": "Hitam", "size_code": "M"})
    db.rahaza_materials.docs.append({"id": "FGX", "code": "DA-OLD", "name": "Kaos lama", "type": "fg", "active": False})
    db.rahaza_material_stock.docs.append({"id": "st-q", "material_id": "FG2", "location_id": "LOC-Q", "qty": 3.0,
                                          "inventory_category": "fg_internal", "ownership": "cv_da"})
    # tanpa kata cari + lokasi: hanya barang yang punya stok di lokasi itu
    r = run(fp.search(db, location_id="LOC-FG"))
    assert [i["id"] for i in r["items"]] == ["FG1"] and r["items"][0]["stok_lokasi"] == 10.0
    assert r["items"][0]["masalah"] is None and r["total"] == 1 and r["terpotong"] is False
    # cari "kaos": FG1 (ada stok) dulu, FG2 (stok 0 di sini) tetap muncul; klien maklon & nonaktif tidak
    r = run(fp.search(db, q="kaos", location_id="LOC-FG"))
    assert [i["id"] for i in r["items"]] == ["FG1", "FG2"] and r["items"][1]["stok_lokasi"] == 0.0
    assert [i["id"] for i in run(fp.search(db, q="kaos", location_id="LOC-FG", only_in_stock=True))["items"]] == ["FG1"]
    # setiap kata harus cocok (nama + warna + ukuran)
    r = run(fp.search(db, q="aisar hitam m"))
    assert [i["id"] for i in r["items"]] == ["FG3"] and (r["items"][0]["color"], r["items"][0]["size"]) == ("Hitam", "M")
    # lokasi karantina: stok terlihat tetapi diberi alasan yang sama dengan penolakan scan
    r = run(fp.search(db, q="nvy", location_id="LOC-Q"))
    assert r["items"][0]["stok_lokasi"] == 3.0 and "karantina" in r["items"][0]["masalah"]
    # tanpa lokasi: daftar lokasi berstok + total stok JUAL (karantina tidak dihitung)
    r = run(fp.search(db, q="kaos", only_in_stock=True))
    by = {i["id"]: i for i in r["items"]}
    assert by["FG1"]["stok_total"] == 10.0 and by["FG1"]["lokasi"][0]["location_id"] == "LOC-FG"
    assert by["FG2"]["stok_total"] == 0.0 and by["FG2"]["lokasi"] == [
        {"location_id": "LOC-Q", "code": "GD-L1-KARANTINA", "name": "Karantina", "qty": 3.0, "jual": False}]
    assert run(fp.search(db, q="kaos", limit=1))["terpotong"] is True


# ══════════════════════════ 3. Scan Keluar — pilih tanpa scan ═════════════════
def test_pick_uses_same_engine_sheet_and_journal(env):
    db, stock = env["db"], env["stock"]
    normal = run(so.scan(db, location_id="LOC-FG", raw_code="DA-1101-CRL", client_scan_id="n1", user=USER))
    out = _pick(db, [_item("FG1", 3, "p1"), _item("FG2", 1, "p2")])
    assert (out["accepted"], out["rejected"], out["failed"], out["pcs"]) == (2, 0, 0, 4)
    l1, l2 = (r["line"] for r in out["results"])
    assert l1["tanpa_scan"] is True and l1["via"] == so.VIA_PICK and l1["sku"] == "DA-1101-CRL"
    assert l1["qty"] == 3 and l1["value"] == round(3 * W, 2) and l1["flags"] == []          # bukan merah
    assert l1["sheet_id"] == normal["line"]["sheet_id"] == l2["sheet_id"]                    # lembar yang sama
    assert normal["line"]["tanpa_scan"] is False
    assert stock() == 6.0 and stock("FG2") == -1.0
    assert l2["negative_stock"] is True and l2["flags"] == ["stok_kurang"]                   # aturan stok = scan
    led = [d for d in db.rahaza_stock_ledger.docs if d["ref"].get("type") == so.REF_SCAN]
    assert len(led) == 3                                                                    # jalur ledger yang sama
    t = so.sum_lines(db.wh_scan_out_lines.docs)
    assert (t["pcs"], t["tanpa_scan_lines"], t["tanpa_scan_pcs"]) == (5, 2, 4)
    # Simpan terkirim dua kali (id pilihan sama) → tidak memotong stok lagi
    again = _pick(db, [_item("FG1", 3, "p1"), _item("FG2", 1, "p2")])
    assert all(r["duplicate"] for r in again["results"]) and stock() == 6.0
    assert len(db.wh_scan_out_lines.docs) == 3
    # Tutup Hari → SATU jurnal termasuk baris tanpa scan
    sheet = db.wh_scan_out_sheets.docs[0]
    run(so.close_sheet(db, sheet["id"], user=SPV))
    je = env["jes"][-1]
    assert len(env["jes"]) == 1
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("5-1000", 415584.40, 0), ("5-2000", 80000.0, 0), ("1-1404", 0, 495584.40)]


def test_pick_rejects_like_scan_and_validates_before_any_effect(env):
    db, stock = env["db"], env["stock"]
    out = _pick(db, [_item("FGM", 1), _item("TIDAK-ADA", 1), _item("FG1", 2)])
    assert (out["accepted"], out["rejected"]) == (1, 2)
    rej = [r["reject"] for r in out["results"] if r["result"] == "rejected"]
    assert rej[0]["reason_code"] == "maklon" and rej[0]["tanpa_scan"] is True
    assert rej[1]["reason_code"] == "unknown_code" and "master barang jadi" in rej[1]["reason"]
    assert stock() == 8.0
    before = len(db.wh_scan_out_lines.docs)
    for kw, items in (({"loc": ""}, [_item("FG1", 1)]), ({"loc": "LOC-Q"}, [_item("FG1", 1)]),
                      ({"kind": "lain"}, [_item("FG1", 1)]), ({"account": "TIDAK-ADA"}, [_item("FG1", 1)]),
                      ({}, [_item("FG1", 501)])):
        with pytest.raises(so.ScanOutError) as e:
            _pick(db, items, **kw)
        assert e.value.status == 400
    assert len(db.wh_scan_out_lines.docs) == before and stock() == 8.0


def test_pick_line_can_be_voided_and_cancel_mode_returns_stock(env):
    db, stock = env["db"], env["stock"]
    out = _pick(db, [_item("FG1", 4)])
    assert stock() == 6.0
    run(so.void_line(db, out["results"][0]["line"]["id"], user=USER, reason="salah pilih"))
    assert stock() == 10.0
    back = _pick(db, [_item("FG1", 2)], kind=so.KIND_CANCEL)
    ln = back["results"][0]["line"]
    assert ln["kind"] == so.KIND_CANCEL and ln["tanpa_scan"] is True and stock() == 12.0


def test_daily_report_counts_no_scan_per_operator(env):
    db = env["db"]
    run(so.scan(db, location_id="LOC-FG", raw_code="DA-1101-CRL", client_scan_id="n1", user=USER))
    _pick(db, [_item("FG1", 3)])
    rep = run(so.daily_report(db, day="2026-11-02", location_id="LOC-FG"))
    op = rep["per_operator"][0]
    assert (op["scans"], op["net"], op["tanpa_scan"], op["net_tanpa_scan"]) == (2, 4, 1, 3)
    assert [ln["qty"] for ln in rep["tanpa_scan"]] == [3] and rep["flagged"] == []
    assert (rep["summary"]["tanpa_scan_lines"], rep["summary"]["tanpa_scan_pcs"]) == (1, 3)


# ══════════════════════════ 4. Keluarkan stok — banyak produk ═════════════════
@pytest.fixture
def fg_env(monkeypatch):
    import routes.rahaza_inventory_fg as fgr
    from core import doc_number_policy, location_resolver, stock_service
    from routes import rahaza_posting as rp
    db = FakeDB(
        rahaza_materials=[{"id": "FG1", "code": "DA-1101-CRL", "name": "Kaos CRL", "type": "fg"},
                          {"id": "FG2", "code": "DA-2202-NVY", "name": "Kaos NVY", "type": "fg"},
                          {"id": "BHN", "code": "KAIN-01", "name": "Kain", "type": "fabric"}],
        rahaza_material_stock=[{"material_id": "FG1", "location_id": "LOC-FG", "qty": 10.0},
                               {"material_id": "FG2", "location_id": "LOC-FG", "qty": 5.0},
                               {"material_id": "FG2", "location_id": "LOC-2", "qty": 2.0}],
        rahaza_customers=[{"id": "C1", "name": "Toko Mitra"}])
    numbers, journals = [], []

    async def auth(_r):
        return {"id": "u-gd", "name": "Gudang", "role": "admin_gudang"}

    async def yes(*a, **k):
        return True

    async def num(*a, **k):
        numbers.append(f"FGI-{len(numbers) + 1}")
        return numbers[-1]

    async def issue(mid, loc, qty, **kw):
        row = next(d for d in db.rahaza_material_stock.docs if d["material_id"] == mid and d["location_id"] == loc)
        if row["qty"] < qty:
            raise stock_service.InsufficientStock(mid, loc, qty, row["qty"])
        row["qty"] -= qty

    async def cogs(_db, doc, _user):
        journals.append((doc["issue_number"], doc["fg_code"], doc["qty"]))
        return {"ok": True, "je_id": f"je-{len(journals)}", "je_number": f"JE-{len(journals)}",
                "cogs": doc["qty"] * 1000.0, "unit_cost": 1000.0, "debit_mapping": "fg_issue.debit_internal"}

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(fgr, "require_auth", auth)
    monkeypatch.setattr(fgr, "get_db", lambda: db)
    monkeypatch.setattr(fgr, "log_activity", noop)
    monkeypatch.setattr(location_resolver, "location_exists", yes)
    monkeypatch.setattr(doc_number_policy, "issue_number", num)
    monkeypatch.setattr(stock_service, "issue", issue)
    monkeypatch.setattr(rp, "post_fg_issue_cogs", cogs)

    def qty(mid, loc="LOC-FG"):
        return next(d for d in db.rahaza_material_stock.docs if d["material_id"] == mid and d["location_id"] == loc)["qty"]
    return {"fgr": fgr, "db": db, "numbers": numbers, "journals": journals, "qty": qty}


def test_parse_batch_lines_rules():
    from routes.rahaza_inventory_fg import parse_batch_lines
    assert parse_batch_lines([{"material_id": "FG1", "location_id": "L", "qty": "2", "code": "A"}]) == [
        {"material_id": "FG1", "location_id": "L", "qty": 2, "code": "A"}]
    with pytest.raises(HTTPException) as e:
        parse_batch_lines([{"material_id": "", "location_id": "L", "qty": 1},
                           {"material_id": "FG1", "location_id": "", "qty": 1, "code": "A"},
                           {"material_id": "FG2", "location_id": "L", "qty": 1.5, "code": "B"},
                           {"material_id": "FG3", "location_id": "L", "qty": 1, "code": "C"},
                           {"material_id": "FG3", "location_id": "L", "qty": 2, "code": "C"}])
    d = e.value.detail
    assert "Baris 1" in d and "A: pilih lokasi" in d and "B: jumlah" in d and "C: produk dan lokasi" in d
    with pytest.raises(HTTPException):
        parse_batch_lines([])


def test_batch_issue_one_number_same_path_per_line(fg_env):
    fgr, db = fg_env["fgr"], fg_env["db"]
    body = {"reason": "sample", "customer_id": "C1", "reference_number": "SJ-01", "notes": "contoh",
            "client_batch_id": "b-1",
            "items": [{"material_id": "FG1", "location_id": "LOC-FG", "qty": 2, "code": "DA-1101-CRL"},
                      {"material_id": "FG2", "location_id": "LOC-2", "qty": 2, "code": "DA-2202-NVY"}]}
    out = run(fgr.create_fg_issue_batch(FakeRequest(body)))
    assert out["ok"] and out["issue_number"] == "FGI-1" and out["failed"] == []
    docs = db.rahaza_fg_issues.docs
    assert [(d["issue_number"], d["fg_code"], d["qty"], d["line_no"], d["batch_lines"]) for d in docs] == [
        ("FGI-1", "DA-1101-CRL", 2, 1, 2), ("FGI-1", "DA-2202-NVY", 2, 2, 2)]
    assert all(d["batch_id"] == "b-1" and d["customer_name"] == "Toko Mitra" and d["gl_je_id"] for d in docs)
    assert (fg_env["qty"]("FG1"), fg_env["qty"]("FG2", "LOC-2"), fg_env["qty"]("FG2")) == (8.0, 0.0, 5.0)
    assert len(db.rahaza_fg_movements.docs) == 2 and len(fg_env["journals"]) == 2
    # Simpan terkirim dua kali → tidak ada pengeluaran kedua
    again = run(fgr.create_fg_issue_batch(FakeRequest(body)))
    assert again["duplicate"] and len(db.rahaza_fg_issues.docs) == 2 and fg_env["numbers"] == ["FGI-1"]


def test_batch_issue_all_or_nothing_when_a_line_is_short(fg_env):
    fgr, db = fg_env["fgr"], fg_env["db"]
    body = {"reason": "koreksi_stok",
            "items": [{"material_id": "FG1", "location_id": "LOC-FG", "qty": 2, "code": "DA-1101-CRL"},
                      {"material_id": "FG2", "location_id": "LOC-FG", "qty": 6, "code": "DA-2202-NVY"},
                      {"material_id": "BHN", "location_id": "LOC-FG", "qty": 1, "code": "KAIN-01"}]}
    with pytest.raises(HTTPException) as e:
        run(fgr.create_fg_issue_batch(FakeRequest(body)))
    d = e.value.detail
    assert d.startswith("Belum ada yang dikeluarkan.") and "DA-2202-NVY" in d and "Tersedia: 5.0" in d
    assert "KAIN-01" in d
    assert db.rahaza_fg_issues.docs == [] and fg_env["qty"]("FG1") == 10.0 and fg_env["numbers"] == []
    with pytest.raises(HTTPException) as e2:
        run(fgr.create_fg_issue_batch(FakeRequest({**body, "reason": "asal"})))
    assert e2.value.status_code == 400


def test_single_issue_still_uses_shared_path(fg_env):
    fgr, db = fg_env["fgr"], fg_env["db"]
    out = run(fgr.create_fg_issue(FakeRequest({"material_id": "FG1", "qty": 3, "reason": "retur",
                                               "location_id": "LOC-FG"})))
    assert out["ok"] and out["issue_number"] == "FGI-1" and "batch_id" not in out
    assert fg_env["qty"]("FG1") == 7.0 and len(fg_env["journals"]) == 1 and len(db.rahaza_fg_movements.docs) == 1
