"""Monitoring Staf ERP (keputusan owner 10 Nov 2026) — uji unit hermetik (Mongo palsu).

Mencakup: hari kerja & batas waktu, meter aktivitas, aturan (K2: akun/peran kosong & nonaktif, dari data aktif),
pemindai (menunggu → terlambat → selesai; dikerjakan orang lain K8; cuti → cadangan / dimaafkan K7; aturan
nonaktif), persetujuan (sumber approval_groups), kewajiban harian toko (K9) & aktif harian, skor, pengingat (K5),
riwayat status PO, dan skrip penutup tugas Marketing lama.
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
from core.pantau_staf import aturan as A  # noqa: E402
from core.pantau_staf import katalog as K  # noqa: E402
from core.pantau_staf import meter as M  # noqa: E402
from core.pantau_staf import pemindai as P  # noqa: E402
from core.pantau_staf import pengingat as G  # noqa: E402
from core.pantau_staf import ringkasan as R  # noqa: E402
from core.pantau_staf.waktu import Kalender, hitung_tenggat, jam_wib, ts  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def wib(y, m, d, hh=0, mm=0):
    return utc(y, m, d, hh, mm) - timedelta(hours=7)


# Senin 9 Nov 2026 — kerja 6 hari (Minggu libur)
SEN = date(2026, 11, 9)
BERLAKU = wib(2026, 11, 1, 0, 0)


def _db():
    db = FakeDB()
    db.users.docs = [
        {"id": "u-admin", "name": "Admin Satu", "email": "a@x", "role": "admin"},
        {"id": "u-andi", "name": "Andi", "email": "f@x", "role": "PIC CMT/Adm. Gudang", "employee_id": "e-andi"},
        {"id": "u-bunga", "name": "Bunga", "email": "fa@x", "role": "admin"},
        {"id": "u-pic", "name": "Citra", "email": "n@x", "role": "pic_toko", "employee_id": "e-pic"},
        {"id": "u-hr", "name": "Dina", "email": "b@x", "role": "HR Generalist"},
        {"id": "u-own", "name": "Owner", "email": "o@x", "role": "owner"},
        {"id": "u-mati", "name": "Lama", "email": "l@x", "role": "admin", "is_active": False},
        {"id": "v-1", "name": "Vendor", "email": "v@x", "role": "cmt_vendor"},
    ]
    return db


def _aktifkan(db, aid, **upd):
    """Pasang aturan bawaan, lalu HANYA aturan `aid` yang aktif (uji terpisah per titik)."""
    run(A.semua(db, kini=BERLAKU))
    for d in db.kewajiban_aturan.docs:
        d["aktif"] = False
        if d["id"] == aid:
            d.update({"aktif": True, "berlaku_sejak": BERLAKU, **upd})
    return db


# ── waktu ────────────────────────────────────────────────────────────────────────────────────────────────
def test_hari_kerja_melewati_minggu_dan_libur():
    kal = Kalender(off_weekdays=frozenset({6}), libur={"2026-11-10"})
    # Sabtu 7 Nov 15:00 WIB + 1 hari kerja → Minggu libur, Senin 9 → 15:00 Senin
    t = kal.tambah_hari_kerja(wib(2026, 11, 7, 15), 1)
    assert t == wib(2026, 11, 9, 15)
    # Senin + 1 hari kerja → Selasa libur → Rabu
    assert kal.tambah_hari_kerja(wib(2026, 11, 9, 9), 1) == wib(2026, 11, 11, 9)
    # jam tetap: periode Sabtu 7 Nov, hari kerja berikutnya pukul 10.00 → Senin 10.00
    assert hitung_tenggat({"jenis": "jam_tetap", "hari": 1, "jam": "10:00"}, kal=kal, mulai=None,
                          periode="2026-11-07") == wib(2026, 11, 9, 10)
    assert kal.hari_kerja_lewat(wib(2026, 11, 7, 10), wib(2026, 11, 11, 10)) == 2   # Senin + Rabu (Selasa libur)


def test_ts_menormalkan_tipe_campur():
    assert ts("2026-11-09") == wib(2026, 11, 9)
    assert ts("2026-11-09T03:00:00Z") == utc(2026, 11, 9, 3)
    assert ts("2026-11-09T03:00:00") == utc(2026, 11, 9, 3)
    assert ts(datetime(2026, 11, 9, 3)) == utc(2026, 11, 9, 3)
    assert ts("") is None and ts("bukan tanggal") is None


# ── meter ────────────────────────────────────────────────────────────────────────────────────────────────
def test_meter_aturan_catat():
    mod = {"id": "prod_po", "lookup": False}
    lookup = {"id": "prod_master_product", "lookup": True}
    ok = dict(user_id="u1", role="admin", status=200)
    assert M.perlu_dicatat(method="GET", module=mod, action="view", **ok)
    assert not M.perlu_dicatat(method="GET", module=None, action=None, **ok)          # bel/lencana/profil
    assert M.perlu_dicatat(method="POST", module=None, action=None, **ok)             # tulisan di luar katalog
    assert not M.perlu_dicatat(method="GET", module=lookup, action="view", **ok)      # data acuan dropdown
    assert M.perlu_dicatat(method="POST", module=lookup, action="create", **ok)
    assert not M.perlu_dicatat(method="GET", module=mod, action="view", user_id="v", role="cmt_vendor", status=200)
    assert not M.perlu_dicatat(method="POST", module=mod, action="create", user_id="u1", role="admin", status=403)


def test_meter_upsert_dan_jeda_lihat():
    db = FakeDB()
    M._TERAKHIR.clear()
    mod = {"id": "prod_po", "lookup": False}
    assert run(M.catat(db, user_id="u1", role="admin", method="GET", status=200, module=mod, action="view"))
    assert not run(M.catat(db, user_id="u1", role="admin", method="GET", status=200, module=mod, action="view"))
    assert run(M.catat(db, user_id="u1", role="admin", method="POST", status=201, module=mod, action="create"))
    assert run(M.catat(db, user_id="u1", role="admin", method="POST", status=201, module=mod, action="create"))
    doc = db.pantau_aktivitas_harian.docs[0]
    assert doc["modul"]["prod_po"] == {"view": 1, "create": 2} and doc["jumlah"] == 3
    assert doc["pertama"] <= doc["terakhir"] and doc["id"].startswith("u1:")


def test_middleware_memetakan_modul_yang_sama_dengan_gerbang():
    from data.module_catalog import detect_action, is_self_service, match_module
    mod = match_module("/api/pantau-staf/staf")
    assert mod and mod["id"] == "mgmt_pantau_staf" and detect_action("GET", "/api/pantau-staf/staf", mod) == "view"
    assert is_self_service("GET", "/api/pantau-staf/saya")


# ── aturan ───────────────────────────────────────────────────────────────────────────────────────────────
def test_aturan_bawaan_K2():
    db = _db()
    rows = {r["id"]: r for r in run(A.semua(db))}
    assert set(K.KATALOG) <= set(rows)
    assert rows["po_konfirmasi"]["aktif"] is False and rows["po_konfirmasi"]["pemegang"]["akun_ids"] == []
    for aid in ("penjualan_toko", "aktif_harian", "pr_ajukan", "setuju_sdm", "opname_hitung"):
        assert rows[aid]["aktif"] is True and rows[aid]["pemegang"]["jenis"] == "data" and rows[aid]["berlaku_sejak"]
    # dipanggil lagi tidak menggandakan
    run(A.semua(db))
    assert len(db.kewajiban_aturan.docs) == len(K.KATALOG)


def test_aturan_validasi():
    users = {"u-andi": {}, "u-bunga": {}}
    lama = A.bawaan(K.KATALOG["po_konfirmasi"])
    with pytest.raises(A.AturanTidakSah, match="minimal satu akun"):
        A.periksa_ubahan(lama, {"aktif": True}, users=users, peran_ada=set())
    with pytest.raises(A.AturanTidakSah, match="tidak ditemukan"):
        A.periksa_ubahan(lama, {"pemegang": {"jenis": "akun", "akun_ids": ["u-x"]}}, users=users, peran_ada=set())
    with pytest.raises(A.AturanTidakSah, match="tidak menyimpan pemegang"):
        A.periksa_ubahan(lama, {"pemegang": {"jenis": "data"}}, users=users, peran_ada=set())
    with pytest.raises(A.AturanTidakSah, match="1–30"):
        A.periksa_ubahan(lama, {"tenggat": {"jenis": "hari_kerja", "nilai": 40}}, users=users, peran_ada=set())
    with pytest.raises(A.AturanTidakSah, match="harian/berkala"):
        A.periksa_ubahan(lama, {"tenggat": {"jenis": "jam_tetap", "jam": "10:00"}}, users=users, peran_ada=set())
    upd = A.periksa_ubahan(lama, {"pemegang": {"jenis": "akun", "akun_ids": ["u-andi"]}, "aktif": True,
                                  "saringan": {"business_type": "maklon"}, "bobot": 2},
                           users=users, peran_ada=set())
    assert upd["aktif"] and upd["pemegang"]["akun_ids"] == ["u-andi"] and upd["saringan"] == {"business_type": "maklon"}


def test_ubah_mengisi_berlaku_sejak_saat_pertama_aktif():
    db = _db()
    run(A.semua(db))
    users = {u["id"]: u for u in db.users.docs}
    doc = run(A.ubah(db, "po_konfirmasi", {"pemegang": {"jenis": "akun", "akun_ids": ["u-andi"]}, "aktif": True},
                     oleh={"id": "u-own", "name": "Owner"}, users=users, peran_ada=set()))
    assert doc["aktif"] and doc["berlaku_sejak"] and doc["diubah_oleh_nama"] == "Owner"


# ── pemindai: alur PO ────────────────────────────────────────────────────────────────────────────────────
def test_alur_po_konfirmasi_menunggu_terlambat_selesai_dan_orang_lain():
    db = _aktifkan(_db(), "po_konfirmasi", pemegang={"jenis": "akun", "akun_ids": ["u-andi"], "peran": []})
    t0 = wib(2026, 11, 9, 9)
    db.production_pos.docs = [
        {"id": "po1", "po_number": "PO-1", "status": "Draft", "created_at": t0, "business_type": "internal"},
        {"id": "po2", "po_number": "PO-2", "status": "Draft", "created_at": t0, "business_type": "maklon"},
    ]
    run(P.pindai(db, kini=t0 + timedelta(hours=1)))
    k = {d["objek_id"]: d for d in db.kewajiban_kejadian.docs}
    assert k["po1"]["status"] == "menunggu" and k["po1"]["pemegang_ids"] == ["u-andi"]
    assert k["po1"]["tenggat"] == wib(2026, 11, 10, 9) and k["po1"]["link_module"] == "prod-pos-internal"
    assert k["po2"]["link_module"] == "maklon-pos-engine"
    # lewat tenggat → terlambat
    run(P.pindai(db, kini=wib(2026, 11, 11, 9)))
    k = {d["objek_id"]: d for d in db.kewajiban_kejadian.docs}
    assert k["po1"]["status"] == "terlambat"
    # po1 dikonfirmasi Andi (terlambat), po2 dikonfirmasi Bunga (bukan pemegang)
    db.production_pos.docs[0].update(status="Confirmed", confirmed_at=wib(2026, 11, 11, 10), confirmed_by="Andi")
    db.production_pos.docs[1].update(status="Confirmed", confirmed_at=wib(2026, 11, 11, 10), confirmed_by="Bunga")
    run(P.pindai(db, kini=wib(2026, 11, 11, 11)))
    k = {d["objek_id"]: d for d in db.kewajiban_kejadian.docs}
    assert k["po1"]["status"] == "selesai" and k["po1"]["tepat"] is False and not k["po1"]["oleh_orang_lain"]
    assert k["po1"]["pelaku_id"] == "u-andi"
    assert k["po2"]["status"] == "selesai" and k["po2"]["oleh_orang_lain"] is True
    # kejadian final tidak diubah lagi
    db.production_pos.docs[0]["status"] = "Cancelled"
    run(P.pindai(db, kini=wib(2026, 11, 12, 11)))
    assert {d["objek_id"]: d for d in db.kewajiban_kejadian.docs}["po1"]["status"] == "selesai"


def test_saringan_dan_aturan_nonaktif_menutup_kejadian():
    db = _aktifkan(_db(), "po_konfirmasi", pemegang={"jenis": "akun", "akun_ids": ["u-andi"], "peran": []},
                   saringan={"business_type": "maklon"})
    t0 = wib(2026, 11, 9, 9)
    db.production_pos.docs = [
        {"id": "po1", "po_number": "PO-1", "status": "Draft", "created_at": t0, "business_type": "internal"},
        {"id": "po2", "po_number": "PO-2", "status": "Draft", "created_at": t0, "business_type": "maklon"},
    ]
    run(P.pindai(db, kini=t0 + timedelta(hours=1)))
    assert [d["objek_id"] for d in db.kewajiban_kejadian.docs] == ["po2"]
    for d in db.kewajiban_aturan.docs:
        if d["id"] == "po_konfirmasi":
            d["aktif"] = False
    run(P.pindai(db, kini=t0 + timedelta(hours=2)))
    assert db.kewajiban_kejadian.docs[0]["status"] == "batal"
    assert db.kewajiban_kejadian.docs[0]["alasan_tutup"] == "Aturan dinonaktifkan"


def test_objek_selesai_sebelum_aturan_berlaku_tidak_dinilai():
    db = _aktifkan(_db(), "po_konfirmasi", pemegang={"jenis": "akun", "akun_ids": ["u-andi"], "peran": []})
    db.production_pos.docs = [{"id": "po0", "po_number": "PO-0", "status": "Confirmed", "business_type": "internal",
                               "created_at": wib(2026, 10, 20, 9), "confirmed_at": wib(2026, 10, 25, 9),
                               "confirmed_by": "Andi"}]
    run(P.pindai(db, kini=wib(2026, 11, 9, 9)))
    assert db.kewajiban_kejadian.docs == []


def test_cuti_pindah_ke_cadangan_atau_dimaafkan():
    t0 = wib(2026, 11, 9, 9)
    hari = "2026-11-11"
    for cad, harap in ((["u-bunga"], "terlambat"), ([], "dimaafkan")):
        db = _aktifkan(_db(), "po_konfirmasi", pemegang={"jenis": "akun", "akun_ids": ["u-andi"], "peran": []},
                       cadangan_ids=cad)
        db.production_pos.docs = [{"id": "po1", "po_number": "PO-1", "status": "Draft", "created_at": t0,
                                   "business_type": "internal"}]
        db.rahaza_leave_requests.docs = [{"employee_id": "e-andi", "status": "approved", "from_date": hari,
                                          "to_date": hari}]
        run(P.pindai(db, kini=wib(2026, 11, 11, 12)))
        k = db.kewajiban_kejadian.docs[0]
        assert k["status"] == harap
        if cad:
            assert k["pemegang_ids"] == ["u-bunga"] and k["dialihkan_ke_cadangan"] is True
        else:
            assert k["dimaafkan"]["alasan"].startswith("Pemegang cuti")


def test_tutup_po_memakai_riwayat_status_atau_pertama_terlihat():
    db = _aktifkan(_db(), "po_tutup", pemegang={"jenis": "akun", "akun_ids": ["u-admin"], "peran": []})
    db.production_pos.docs = [
        {"id": "po1", "po_number": "PO-1", "status": "Production Complete", "business_type": "internal",
         "status_history": [{"status": "Confirmed", "at": wib(2026, 11, 2, 9)},
                            {"status": "Production Complete", "at": wib(2026, 11, 9, 9)}]},
        {"id": "po2", "po_number": "PO-2", "status": "Ready to Close", "business_type": "internal"},
    ]
    kini = wib(2026, 11, 9, 12)
    run(P.pindai(db, kini=kini))
    k = {d["objek_id"]: d for d in db.kewajiban_kejadian.docs}
    assert k["po1"]["mulai"] == wib(2026, 11, 9, 9) and not k["po1"]["tanpa_waktu"]
    assert k["po2"]["mulai"] == kini and k["po2"]["tanpa_waktu"] is True


def test_riwayat_status_po():
    from routes.production_pos import riwayat_status
    r = riwayat_status("Closed", {"id": "u1", "name": "Andi"})
    assert r["status"] == "Closed" and r["by_id"] == "u1" and r["by_name"] == "Andi" and r["at"]
    assert riwayat_status("Completed", None)["by_name"] == "Sistem"


# ── persetujuan: sumber approval_groups ──────────────────────────────────────────────────────────────────
def test_persetujuan_dari_antrean_dan_nasib(monkeypatch):
    db = _aktifkan(_db(), "setuju_sdm")
    db.rahaza_leave_requests.docs = [{"id": "L1", "status": "pending_approval", "created_at": wib(2026, 11, 9, 8)}]
    antrean = {"hr": {("rahaza_leave_requests", "L1"): {"u-hr", "u-admin"}}}

    async def _antre(ctx):
        return antrean
    monkeypatch.setattr(K, "_antrean_persetujuan", _antre)
    run(P.pindai(db, kini=wib(2026, 11, 9, 10)))
    k = [d for d in db.kewajiban_kejadian.docs if d["aturan_id"] == "setuju_sdm"]
    assert len(k) == 1 and k[0]["pemegang_ids"] == ["u-hr"] and k[0]["status"] == "menunggu"   # admin cadangan
    antrean.clear()
    db.rahaza_leave_requests.docs[0].update(status="approved", approved_at=wib(2026, 11, 9, 11), approved_by="u-hr")
    run(P.pindai(db, kini=wib(2026, 11, 9, 12)))
    k = [d for d in db.kewajiban_kejadian.docs if d["aturan_id"] == "setuju_sdm"][0]
    assert k["status"] == "selesai" and k["tepat"] is True and k["pelaku_id"] == "u-hr" and not k["oleh_orang_lain"]


def test_approval_groups_bisa_mengembalikan_kunci():
    from routes import approval_badge as ab
    db = FakeDB()
    db.rahaza_ap_invoices.docs = [{"id": "ap1", "status": "sent"}]

    async def _kosong(_db, _u):
        return []
    import core.pr_approval as pra
    old = pra.pending_for_user
    pra.pending_for_user = _kosong
    try:
        g = run(ab.approval_groups(db, {"id": "u1", "role": "accounting"}, with_keys=True))
        g0 = run(ab.approval_groups(db, {"id": "u1", "role": "accounting"}))
    finally:
        pra.pending_for_user = old
    ap = [x for x in g if x["key"] == "ap"][0]
    assert ap["keys"] == [["rahaza_ap_invoices", "ap1"]]
    assert "keys" not in [x for x in g0 if x["key"] == "ap"][0]


# ── kewajiban harian ─────────────────────────────────────────────────────────────────────────────────────
def test_penjualan_toko_dari_data_K9():
    db = _aktifkan(_db(), "penjualan_toko")
    db.marketing_platform_accounts.docs = [{"id": "T1", "account_name": "Toko A", "status": "active",
                                            "pic_user_id": "u-pic", "sales_input_mode": "rekap_manual"}]
    db.marketing_sales_data.docs = [{"account_id": "T1", "date": "2026-11-07", "created_at": wib(2026, 11, 8, 9),
                                     "created_by": "n@x"}]
    run(P.pindai(db, kini=wib(2026, 11, 9, 11)))
    k = {d["periode"]: d for d in db.kewajiban_kejadian.docs if d["aturan_id"] == "penjualan_toko"}
    assert k["2026-11-07"]["status"] == "selesai" and k["2026-11-07"]["tepat"] is True
    assert k["2026-11-07"]["pelaku_id"] == "u-pic"
    # Minggu 8 Nov → batas Senin 10.00 → sudah lewat pukul 11.00
    assert k["2026-11-08"]["status"] == "terlambat" and k["2026-11-08"]["pemegang_ids"] == ["u-pic"]


def test_aktif_harian_hadir_tanpa_aktivitas_terlewat(monkeypatch):
    db = _aktifkan(_db(), "aktif_harian")

    async def _kerja(ctx, uid):
        return uid in ("u-andi", "u-pic")
    monkeypatch.setattr(K, "_portal_kerja", _kerja)
    db.rahaza_attendance_events.docs = [
        {"employee_id": "e-andi", "date": "2026-11-05", "status": "hadir"},
        {"employee_id": "e-andi", "date": "2026-11-06", "status": "izin"},
        {"employee_id": "e-andi", "date": "2026-11-07", "status": "hadir"},
        {"employee_id": "e-pic", "date": "2026-11-05", "status": "hadir"},
    ]
    db.pantau_aktivitas_harian.docs = [{"id": "u-andi:2026-11-05", "user_id": "u-andi", "tanggal": "2026-11-05",
                                        "pertama": wib(2026, 11, 5, 8), "terakhir": wib(2026, 11, 5, 16)}]
    run(P.pindai(db, kini=wib(2026, 11, 9, 9)))
    k = {(d["pemegang_ids"][0], d["periode"]): d["status"] for d in db.kewajiban_kejadian.docs
         if d["aturan_id"] == "aktif_harian"}
    assert k[("u-andi", "2026-11-05")] == "selesai"
    assert ("u-andi", "2026-11-06") not in k                     # izin tidak dihitung (K7)
    assert k[("u-andi", "2026-11-07")] == "terlewat"
    assert ("u-pic", "2026-11-06") not in k                      # absen hari itu ada, Citra tidak tercatat hadir
    assert not [x for x in k if x[0] in ("u-own", "u-admin")]    # bukan portal kerja / owner tidak dipantau


# ── skor & ringkasan ────────────────────────────────────────────────────────────────────────────────────
def test_skor_kepatuhan():
    a, b = wib(2026, 11, 9), wib(2026, 11, 15, 23, 59)
    kini = wib(2026, 11, 14, 12)
    t = wib(2026, 11, 10, 9)
    ks = [
        {"status": "selesai", "tepat": True, "tenggat": t, "bobot": 2, "selesai_at": t},
        {"status": "selesai", "tepat": True, "oleh_orang_lain": True, "tenggat": t, "bobot": 1, "selesai_at": t},
        {"status": "selesai", "tepat": False, "tenggat": t, "bobot": 1, "selesai_at": t},
        {"status": "terlambat", "tenggat": t, "bobot": 1},
        {"status": "batal", "tenggat": t, "bobot": 5},
        {"status": "dimaafkan", "tenggat": t, "bobot": 5},
        {"status": "menunggu", "tenggat": wib(2026, 11, 15, 9), "bobot": 3},     # belum jatuh tempo
        {"status": "terlewat", "tenggat": t, "bobot": 1, "tepat": False},
    ]
    s = R.skor_dari(ks, a, b, kini)
    assert s["dinilai"] == 5 and s["tepat"] == 1
    assert s["kepatuhan"] == round(100 * 2 / 6, 1) and s["nilai"]["huruf"] == "E"
    assert s["terlambat"] == 1 and s["menunggu"] == 1 and s["oleh_orang_lain"] == 1 and s["terlewat"] == 1
    assert R.skor_dari([], a, b, kini)["kepatuhan"] is None


def test_per_staf_dan_macet_dan_saya():
    db = _aktifkan(_db(), "po_konfirmasi", pemegang={"jenis": "akun", "akun_ids": ["u-andi"], "peran": []})
    t0 = wib(2026, 11, 9, 9)
    db.production_pos.docs = [{"id": "po1", "po_number": "PO-1", "status": "Draft", "created_at": t0,
                               "business_type": "internal"}]
    kini = wib(2026, 11, 11, 9)
    run(P.pindai(db, kini=kini))
    data = run(R.per_staf(db, "2026-11-09", "2026-11-11", kini=kini))
    ids = [r["user_id"] for r in data["items"]]
    assert "u-own" not in ids and "u-mati" not in ids and "v-1" not in ids
    andi = [r for r in data["items"] if r["user_id"] == "u-andi"][0]
    assert andi["terlambat"] == 1 and andi["kepatuhan"] == 0.0 and data["items"][0]["user_id"] == "u-andi"
    m = run(R.macet(db, kini=kini))
    assert m["jumlah"] == 1 and m["items"][0]["pemegang"] == ["Andi"] and m["items"][0]["terlambat_hari_kerja"] == 1
    s = run(R.saya(db, "u-andi", kini=kini))
    assert s["terlambat"] == 1 and "pemegang_ids" not in s["items"][0] and "kepatuhan" not in s
    alur = run(R.per_alur(db, "2026-11-09", "2026-11-11", kini=kini))
    po = [g for g in alur["alur"] if g["alur"] == "po"][0]
    langkah = [x for x in po["langkah"] if x["aturan_id"] == "po_konfirmasi"][0]
    assert langkah["terlambat"] == 1 and langkah["pemegang"] == ["Andi"]


# ── pengingat ───────────────────────────────────────────────────────────────────────────────────────────
def test_pesan_staf_ringkas():
    hari = date(2026, 11, 11)
    items = [{"status": "terlambat", "nama": "Kirim bahan ke CMT", "nomor": "PO-1"},
             {"status": "menunggu", "nama": "Terima & QC", "nomor": "R-1", "tenggat": wib(2026, 11, 11, 15)},
             {"status": "menunggu", "nama": "Tutup PO", "nomor": "PO-2", "tenggat": wib(2026, 11, 13, 9)}]
    judul, isi = G.susun_pesan_staf(items, hari)
    assert judul == "Kewajiban sistem Anda: 1 terlambat, 1 jatuh tempo hari ini"
    assert "PO-1" in isi and "R-1" in isi and "PO-2" not in isi
    assert G.susun_pesan_staf(items[2:], hari) is None


def test_kirim_harian_satu_pesan_per_staf_dan_ringkasan_owner(monkeypatch):
    import routes.rahaza_notifications as rn
    sent = []

    async def _pub(_db, **kw):
        sent.append(kw)
    monkeypatch.setattr(rn, "publish_notification", _pub)
    db = _db()
    t = wib(2026, 11, 9, 9)
    db.kewajiban_kejadian.docs = [
        {"id": "a:1", "status": "terlambat", "nama": "Kirim bahan ke CMT", "nomor": "PO-1", "tenggat": t,
         "pemegang_ids": ["u-andi"]},
        {"id": "a:2", "status": "terlambat", "nama": "Tutup PO", "nomor": "PO-2", "tenggat": t,
         "pemegang_ids": ["u-andi"]},
        {"id": "a:3", "status": "terlambat", "nama": "Catat kas", "nomor": "9 Nov", "tenggat": t, "pemegang_ids": []},
    ]
    out = run(G.kirim_harian(db, kini=wib(2026, 11, 11, 8)))
    staf = [s for s in sent if s["type_"] == "kewajiban_pengingat"]
    assert out["dikirim"] == 1 and len(staf) == 1 and staf[0]["target_user_ids"] == ["u-andi"]
    own = [s for s in sent if s["type_"] == "kewajiban_ringkasan_owner"][0]
    assert set(own["target_user_ids"]) == {"u-admin", "u-bunga", "u-own"}          # owner + admin (K5), bukan atasan
    assert "belum punya pemegang" in own["message"]
    sent.clear()
    assert run(G.kirim_harian(db, kini=wib(2026, 11, 15, 8)))["alasan"] == "hari libur"   # Minggu


# ── migrasi K9 ──────────────────────────────────────────────────────────────────────────────────────────
def test_migrasi_tutup_tugas_input_sales():
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "scripts", "migrations", "2026_11_10_tutup_tugas_input_sales.py")
    spec = importlib.util.spec_from_file_location("mig_k9", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    db = FakeDB()
    db.marketing_tasks.docs = [
        {"id": "t1", "source": "auto_generated", "related_entity": "sales_data", "status": "to_do"},
        {"id": "t2", "source": "auto_generated", "related_entity": "sales_data", "status": "done"},
        {"id": "t3", "source": "auto_generated_health_alert", "related_entity": "manual_check", "status": "to_do"},
        {"id": "t4", "source": "manual", "related_entity": "sales_data", "status": "to_do"},
    ]
    assert run(mig.jalankan(db, apply=False)) == {"terbuka": 1, "ditutup": 0}
    assert db.marketing_tasks.docs[0]["status"] == "to_do"
    assert run(mig.jalankan(db, apply=True))["ditutup"] == 1
    st = {d["id"]: d["status"] for d in db.marketing_tasks.docs}
    assert st == {"t1": "cancelled", "t2": "done", "t3": "to_do", "t4": "to_do"}
    assert run(mig.jalankan(db, apply=True)) == {"terbuka": 0, "ditutup": 0}


def test_katalog_lengkap_dan_konsisten():
    ids = [t.id for t in K.KATALOG_LIST]
    assert len(ids) == len(set(ids))
    for t in K.KATALOG_LIST:
        assert t.alur in K.ALUR_LABEL and t.jenis in ("alur", "berkala")
        assert (t.pemegang or {}).get("jenis") in ("akun", "data")
        assert jam_wib(SEN, "10:00").tzinfo is not None


def test_pindai_semua_aturan_bawaan_tanpa_galat(monkeypatch):
    """Semua titik dengan aturan bawaan + semua aturan akun diaktifkan berjalan di data kosong tanpa galat
    (termasuk persetujuan lewat approval_groups asli dan portal kerja lewat resolve_role_access asli)."""
    import auth
    db = _db()
    monkeypatch.setattr(auth, "get_db", lambda: db)      # izin peran dibaca auth dari db (tanpa Mongo asli)
    auth._rbac_cache.clear()
    run(A.semua(db, kini=BERLAKU))
    for d in db.kewajiban_aturan.docs:
        d.update({"aktif": True, "berlaku_sejak": BERLAKU,
                  "pemegang": d["pemegang"] if d["pemegang"]["jenis"] == "data"
                  else {"jenis": "akun", "akun_ids": ["u-andi"], "peran": []}})
    hasil = run(P.pindai(db, kini=wib(2026, 11, 9, 9)))
    assert hasil["status"] == "ok" and set(hasil["aturan"]) == set(K.KATALOG)
    assert not [k for k, v in hasil["aturan"].items() if "galat" in v]


# ── Asisten AI: alat baca pantau_staf ───────────────────────────────────────────────────────────────────
class _CtxAI:
    def __init__(self, jawab):
        self.jawab, self.calls = jawab, []

    async def api(self, method, path, params=None, **_k):
        self.calls.append((method, path, params or {}))
        return self.jawab.get(path)


def test_alat_ai_pantau_staf_membaca_layar_yang_sama():
    from core.asisten_ai.alat import pantau_staf as alat_ps
    ctx = _CtxAI({
        "/api/pantau-staf/staf": {"dari": "2026-11-09", "sampai": "2026-11-11", "masa_uji": {"aktif": True},
                                  "items": [{"user_id": "u-andi", "nama": "Andi", "peran": "x", "kepatuhan": 50.0,
                                             "nilai": {"huruf": "D"}, "terlambat": 2, "tepat": 1, "dinilai": 2}]},
        "/api/pantau-staf/macet": {"items": [{"nama": "Kirim bahan ke CMT", "nomor": "PO-1", "status": "terlambat",
                                              "pemegang": ["Andi"], "terlambat_hari_kerja": 2,
                                              "sebelumnya": {"nama": "Selesaikan potong", "oleh": "Andi"}}]},
    })
    out = run(alat_ps.pantau_staf(ctx, {"bagian": "ringkasan", "dari": "2026-11-09"}))
    assert ctx.calls[0] == ("GET", "/api/pantau-staf/staf", {"dari": "2026-11-09"})
    assert out["hasil"]["staf"][0]["kepatuhan_persen"] == 50.0 and out["hasil"]["staf"][0]["nilai"] == "D"
    out = run(alat_ps.pantau_staf(ctx, {"bagian": "macet"}))
    k = out["hasil"]["kewajiban"][0]
    assert k["menunggu"] == ["Andi"] and k["terlambat_hari_kerja"] == 2 and k["dokumen"] == "PO-1"
    assert "galat" in run(alat_ps.pantau_staf(ctx, {"bagian": "staf"}))["hasil"]


# ── rute: akses (K3/K4) ─────────────────────────────────────────────────────────────────────────────────
class _Req:
    def __init__(self, query=None, body=None):
        self.query_params = dict(query or {})
        self._body = body
        self.headers = {}

    async def json(self):
        if self._body is None:
            raise ValueError("kosong")
        return self._body


def _rute(monkeypatch, db, user):
    from routes import pantau_staf as rt

    async def _auth(_req=None, *a, **k):
        return dict(user)

    async def _noop(*_a, **_k):
        return None
    monkeypatch.setattr(rt, "get_db", lambda: db)
    monkeypatch.setattr(rt, "require_auth", _auth)
    monkeypatch.setattr(rt, "log_activity", _noop)
    return rt


def test_rute_hanya_owner_admin_dan_saya_untuk_semua(monkeypatch):
    from fastapi import HTTPException
    db = _aktifkan(_db(), "po_konfirmasi", pemegang={"jenis": "akun", "akun_ids": ["u-andi"], "peran": []})
    rt = _rute(monkeypatch, db, {"id": "u-hr", "role": "HR Generalist", "name": "Dina"})
    for coro in (rt.get_staf(_Req()), rt.get_macet(_Req()), rt.get_aturan(_Req()), rt.post_pindai(_Req())):
        with pytest.raises(HTTPException) as e:
            run(coro)
        assert e.value.status_code == 403
    assert run(rt.get_saya(_Req()))["items"] == []                       # Portal Saya: milik sendiri, tanpa skor
    rt = _rute(monkeypatch, db, {"id": "u-own", "role": "owner", "name": "Owner"})
    out = run(rt.get_aturan(_Req()))
    assert {a["id"] for a in out["items"]} == set(K.KATALOG) and out["pilihan"]["akun"]
    with pytest.raises(HTTPException) as e:
        run(rt.put_aturan("po_tutup", _Req(body={"aktif": True})))
    assert e.value.status_code == 400 and "minimal satu akun" in e.value.detail
    doc = run(rt.put_aturan("po_tutup", _Req(body={"pemegang": {"jenis": "akun", "akun_ids": ["u-admin"]}, "aktif": True})))
    assert doc["aktif"] and doc["pemegang_nama"] == ["Admin Satu"]


def test_rute_maafkan_dan_ingatkan(monkeypatch):
    from fastapi import HTTPException
    import routes.rahaza_notifications as rn
    sent = []

    async def _pub(_db, **kw):
        sent.append(kw)
    monkeypatch.setattr(rn, "publish_notification", _pub)
    db = _db()
    db.kewajiban_kejadian.docs = [{"id": "a:1", "status": "terlambat", "nama": "Tutup PO", "nomor": "PO-1",
                                   "pemegang_ids": ["u-andi"]},
                                  {"id": "a:2", "status": "terlambat", "nama": "Catat kas", "pemegang_ids": []}]
    rt = _rute(monkeypatch, db, {"id": "u-own", "role": "owner", "name": "Owner"})
    assert run(rt.post_ingatkan("a:1", _Req()))["penerima"] == 1 and sent[0]["target_user_ids"] == ["u-andi"]
    with pytest.raises(HTTPException) as e:
        run(rt.post_ingatkan("a:2", _Req()))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        run(rt.post_maafkan("a:1", _Req()))
    assert e.value.status_code == 400
    run(rt.post_maafkan("a:1", _Req(body={"alasan": "menunggu bahan pemasok"})))
    k = db.kewajiban_kejadian.docs[0]
    assert k["status"] == "dimaafkan" and k["dimaafkan"]["oleh_nama"] == "Owner"


def test_label_dokumen_harian_tanpa_tanggal_mentah():
    assert G.label_dokumen({"nomor": "Shopee GHS", "periode": "2026-11-09"}) == "Shopee GHS · 9 Nov"
    assert G.label_dokumen({"nomor": "2026-11-09", "periode": "2026-11-09"}) == "9 Nov"
    assert G.label_dokumen({"nomor": "PO-1"}) == "PO-1"


def test_macet_harian_digabung_per_pemegang_dan_toko():
    items = [
        {"id": "p:T1:2026-11-02", "aturan_id": "penjualan_toko", "jenis": "berkala", "nomor": "Toko A",
         "periode": "2026-11-02", "pemegang_ids": ["u1"], "status": "terlambat", "terlambat_hari_kerja": 6},
        {"id": "p:T1:2026-11-01", "aturan_id": "penjualan_toko", "jenis": "berkala", "nomor": "Toko A",
         "periode": "2026-11-01", "pemegang_ids": ["u1"], "status": "terlambat", "terlambat_hari_kerja": 7},
        {"id": "p:T2:2026-11-01", "aturan_id": "penjualan_toko", "jenis": "berkala", "nomor": "Toko B",
         "periode": "2026-11-01", "pemegang_ids": ["u1"], "status": "menunggu"},
        {"id": "k:2026-11-01", "aturan_id": "kas_harian", "jenis": "berkala", "nomor": "2026-11-01",
         "periode": "2026-11-01", "pemegang_ids": ["u2"], "status": "terlambat", "terlambat_hari_kerja": 7},
        {"id": "k:2026-11-02", "aturan_id": "kas_harian", "jenis": "berkala", "nomor": "2026-11-02",
         "periode": "2026-11-02", "pemegang_ids": ["u2"], "status": "terlambat", "terlambat_hari_kerja": 6},
        {"id": "po:1", "aturan_id": "po_tutup", "jenis": "alur", "nomor": "PO-1", "status": "terlambat"},
    ]
    out = R.gabung_harian(items)
    assert len(out) == 4
    a = [x for x in out if x.get("nomor") == "Toko A"][0]
    assert a["gabungan"] == 2 and a["periode_awal"] == "2026-11-01" and a["periode_akhir"] == "2026-11-02"
    assert a["terlambat_hari_kerja"] == 7 and a["ids"] == ["p:T1:2026-11-01", "p:T1:2026-11-02"]
    kas = [x for x in out if x["aturan_id"] == "kas_harian"][0]
    assert kas["gabungan"] == 2
