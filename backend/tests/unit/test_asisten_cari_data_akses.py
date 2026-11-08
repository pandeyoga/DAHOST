"""Uji katalog data Asisten AI (Tahap E, K1) — akses pengguna, CV, lingkup toko, gaji, eksekusi, alat.

Hermetik: Mongo palsu (`_fake_mongo.FakeDB`) untuk pengguna/peran/toko/rekening; eksekusi aggregate memakai stub
yang merekam pipeline (`_fake_mongo` tidak punya aggregate). Tanpa API Anthropic.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[2]
for p in (str(BACKEND), os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402

from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai import katalog_data as K  # noqa: E402
from core.asisten_ai.alat_base import AlatError  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Kursor:
    def __init__(self, hasil):
        self._hasil = hasil

    async def to_list(self, n=None):
        if isinstance(self._hasil, Exception):
            raise self._hasil
        return self._hasil


class _KoleksiStub:
    def __init__(self, db, nama):
        self.db, self.nama = db, nama

    def aggregate(self, pipeline, **kw):
        self.db.panggilan.append((self.nama, pipeline, kw))
        return _Kursor(self.db.hasil)


class DBStub(fm.FakeDB):
    """FakeDB + aggregate perekam: hasil = [{"baris": [...], "total": [{"n": N}]}] atau Exception."""

    def __init__(self, baris=(), total=None, galat=None):
        super().__init__()
        self.panggilan = []
        self.hasil = galat if galat is not None else [
            {"baris": list(baris), "total": [{"n": len(baris) if total is None else total}]}]
        self._agg = {}

    def __getitem__(self, name):
        if name in self._stubbed():
            return self._agg.setdefault(name, _KoleksiStub(self, name))
        return super().__getitem__(name)

    @staticmethod
    def _stubbed():
        return {d.koleksi for d in K.semua_dataset()} - {"rahaza_cash_accounts", "marketing_platform_accounts"}


def ctx_untuk(db, *, peran="owner", izin=("*",), cv="DA", pemanggil="langsung", uid="u1"):
    c = SimpleNamespace(db=db, user={"id": uid, "role": peran, "_permissions": list(izin)}, cv=cv,
                        today=date(2026, 11, 9), pemanggil=pemanggil, _bersama={})
    from services.ai.privacy import Pseudonymizer
    c.samaran = Pseudonymizer()
    return c


def akses(peran, portal=(), izin=(), cv_boleh=None):
    return K.akses_dari(peran=peran, portal=portal, izin=izin, cv_boleh=cv_boleh)


# ══════════════════════════════════════════════════════════════════════════════
# Aturan akses dataset
# ══════════════════════════════════════════════════════════════════════════════
def test_super_melihat_semua_dataset_dan_kolom():
    for peran in ("owner", "superadmin", "admin"):
        ak = akses(peran)
        assert all(K.dataset_boleh(d, ak) for d in K.semua_dataset())
    assert "gaji_pokok" in K.kolom_boleh(K.cari_dataset("karyawan"), akses("owner"))
    assert "gaji_pokok" not in K.kolom_boleh(K.cari_dataset("karyawan"), akses("admin"))   # admin bukan PERAN_GAJI
    assert K.dataset_boleh(K.cari_dataset("baris_jurnal"), akses("staf_x", izin=("*",)))


def test_peran_tanpa_portal_atau_izin_ditolak():
    ak = akses("manager_produksi", portal=("management", "procurement", "rnd"))
    boleh = {d.id for d in K.semua_dataset() if K.dataset_boleh(d, ak)}
    assert {"po_produksi", "kiriman_cmt", "terima_qc_cmt", "tagihan_cmt", "po_pembelian", "produk_varian"} <= boleh
    assert not {"baris_jurnal", "mutasi_kas_bank", "karyawan", "absensi", "penjualan_harian_toko"} & boleh
    kosong = akses("operator_x", portal=("self",))
    assert not any(K.dataset_boleh(d, kosong) for d in K.semua_dataset())
    keu = akses("staff_keuangan", portal=("finance", "management"))
    assert K.dataset_boleh(K.cari_dataset("baris_jurnal"), keu)
    assert not K.dataset_boleh(K.cari_dataset("karyawan"), keu)
    mkt = akses("pic_toko", portal=("toko",))
    assert K.dataset_boleh(K.cari_dataset("pesanan_marketplace"), mkt)
    assert not K.dataset_boleh(K.cari_dataset("faktur_pemasok"), mkt)


def test_gerbang_modul_granular():
    d = K.cari_dataset("baris_jurnal")
    # portal Keuangan sudah granular (ada izin mod.fin_*), tapi tanpa Lihat jurnal/laporan → ditolak
    tanpa = akses("staff_keuangan", portal=("finance",), izin=("mod.fin_cash.view",))
    assert not K.dataset_boleh(d, tanpa)
    assert K.dataset_boleh(K.cari_dataset("mutasi_kas_bank"), tanpa)
    dengan = akses("staff_keuangan", portal=("finance",), izin=("mod.fin_cash.view", "mod.fin_journal.view"))
    assert K.dataset_boleh(d, dengan)
    # portal belum granular → penjaga portal yang berlaku
    assert K.dataset_boleh(d, akses("staff_keuangan", portal=("finance",)))


def test_gaji_tersembunyi_bagi_non_hr():
    d = K.cari_dataset("karyawan")
    for peran in ("hr", "hr_manager", "manager_hr", "staff_hr", "owner", "superadmin"):
        assert {"gaji_pokok", "skema_gaji", "tarif_lembur"} <= K.kolom_boleh(d, akses(peran, portal=("hr",)))
    lain = K.kolom_boleh(d, akses("kepala_unit", portal=("hr",)))
    assert not {"gaji_pokok", "skema_gaji", "tarif_lembur"} & lain and "nama" in lain


def test_akses_pengguna_dari_db_dan_cache():
    db = fm.FakeDB()
    db.roles.docs.append({"id": "r1", "name": "kepala_gudang", "portals": ["warehouse"]})
    db.users.docs.append({"id": "u9", "role": "kepala_gudang", "allowed_entities": ["DA"]})
    dipanggil = []

    async def izin_fn(peran, uid):
        dipanggil.append((peran, uid))
        return ["mod.wh_stock.view"]
    c = SimpleNamespace(db=db, user={"id": "u9", "role": "kepala_gudang"}, cv="DA", _bersama={})
    ak = run(K.akses_pengguna(c, izin_fn=izin_fn))
    assert "warehouse" in ak.portal and "mod.wh_stock.view" in ak.izin and ak.cv_boleh == ("DA",)
    assert not ak.super_ and not ak.boleh_gaji
    assert K.dataset_boleh(K.cari_dataset("mutasi_stok"), ak)
    assert not K.dataset_boleh(K.cari_dataset("baris_jurnal"), ak)
    run(K.akses_pengguna(c, izin_fn=izin_fn))
    assert dipanggil == [("kepala_gudang", "u9")]            # sekali per giliran (`ctx._bersama`)


# ══════════════════════════════════════════════════════════════════════════════
# CV, lingkup toko, baris gaji
# ══════════════════════════════════════════════════════════════════════════════
def test_cv_field_da_mencakup_dok_tanpa_field():
    db = fm.FakeDB()
    d = K.cari_dataset("faktur_pemasok")
    for cv, cocok, tolak in (("DA", [{"entity": "DA"}, {}], [{"entity": "SMU"}]),
                             ("SMU", [{"entity": "SMU"}], [{"entity": "DA"}, {}]),
                             ("ALL", [{"entity": "DA"}, {}, {"entity": "SMU"}], [])):
        awal, gabung, _ = run(K.saringan_akses(d, ctx_untuk(db, cv=cv), akses("owner")))
        m0 = K.bangun_rencana(d, {"dataset": d.id}, saringan_awal=awal).pipeline[0]["$match"]
        for doc in cocok:
            assert fm.match({**doc, "status": "sent"}, m0), (cv, doc)
        for doc in tolak:
            assert not fm.match({**doc, "status": "sent"}, m0), (cv, doc)


def test_izin_cv_pengguna_ditegakkan():
    db = fm.FakeDB()
    ak = akses("staff_keuangan", portal=("finance",), cv_boleh=["DA"])
    with pytest.raises(AlatError) as e:
        run(K.saringan_akses(K.cari_dataset("baris_jurnal"), ctx_untuk(db, cv="SMU"), ak))
    assert e.value.status == 403
    with pytest.raises(AlatError):
        run(K.saringan_akses(K.cari_dataset("baris_jurnal"), ctx_untuk(db, cv="ALL"), ak))
    run(K.saringan_akses(K.cari_dataset("baris_jurnal"), ctx_untuk(db, cv="DA"), ak))


def test_cv_rekening_kas_dan_cv_tetap():
    db = fm.FakeDB()
    db.rahaza_cash_accounts.docs += [{"id": "k1", "entity": "DA"}, {"id": "k2", "entity": "SMU"}, {"id": "k3"}]
    awal, _, _ = run(K.saringan_akses(K.cari_dataset("mutasi_kas_bank"), ctx_untuk(db, cv="DA"), akses("owner")))
    assert awal == [{"account_id": {"$in": ["k1", "k3"]}}]
    awal, _, _ = run(K.saringan_akses(K.cari_dataset("mutasi_kas_bank"), ctx_untuk(db, cv="ALL"), akses("owner")))
    assert awal == []
    awal, _, cat = run(K.saringan_akses(K.cari_dataset("posisi_stok"), ctx_untuk(db, cv="SMU"), akses("owner")))
    assert awal == [] and "milik CV Dewi Aditya" in cat[0]
    awal, gab, _ = run(K.saringan_akses(K.cari_dataset("tagihan_cmt"), ctx_untuk(db, cv="SMU"), akses("owner")))
    assert awal == [] and gab == [K.cari_dataset("tagihan_cmt").cv["SMU"]]


def test_lingkup_toko_marketing_dan_cv_toko():
    db = fm.FakeDB()
    db.marketing_platform_accounts.docs += [
        {"id": "t1", "account_code": "A", "pic_user_id": "staf1"},
        {"id": "t2", "account_code": "B", "assigned_staff": ["staf2"]},
        {"id": "t3", "account_code": "C", "entity": "SMU", "pic_user_id": "staf1"}]
    d = K.cari_dataset("pesanan_marketplace")
    ak_staf = akses("staff_marketing", portal=("toko",))
    awal, _, _ = run(K.saringan_akses(d, ctx_untuk(db, peran="staff_marketing", izin=(), uid="staf1"), ak_staf))
    assert awal == [{"account_id": {"$in": ["t1"]}}]                      # hanya toko DA yang dipegangnya
    awal, _, _ = run(K.saringan_akses(d, ctx_untuk(db, peran="staff_marketing", izin=(), uid="staf1", cv="SMU"),
                                      ak_staf))
    assert awal == [{"account_id": {"$in": ["t3"]}}]
    awal, _, cat = run(K.saringan_akses(d, ctx_untuk(db, peran="staff_marketing", izin=(), uid="orang_lain"),
                                        ak_staf))
    assert awal == [{"account_id": {"$in": []}}] and "Belum ada toko" in cat[0]
    awal, _, _ = run(K.saringan_akses(d, ctx_untuk(db, cv="ALL"), akses("owner")))
    assert sorted(awal[0]["account_id"]["$in"]) == ["t1", "t2", "t3"]


def test_baris_gaji_disembunyikan_bagi_non_peran_gaji():
    db = fm.FakeDB()
    d = K.cari_dataset("baris_jurnal")
    awal, _, cat = run(K.saringan_akses(d, ctx_untuk(db), akses("staff_keuangan", portal=("finance",))))
    m0 = K.bangun_rencana(d, {"dataset": d.id}, saringan_awal=awal).pipeline[0]["$match"]
    assert fm.match({"account_name": "Beban Listrik", "description": "Tagihan PLN"}, m0)
    assert not fm.match({"account_name": "Beban Gaji Produksi", "description": "x"}, m0)
    assert not fm.match({"account_name": "Bank BCA", "description": "Bayar gaji Oktober"}, m0)
    assert any("gaji" in c.lower() for c in cat)
    awal, _, cat = run(K.saringan_akses(d, ctx_untuk(db), akses("owner")))
    assert awal == [{"entity": {"$in": ["DA", None]}}] and cat == []     # hanya saringan CV, tanpa sembunyi gaji


# ══════════════════════════════════════════════════════════════════════════════
# Eksekusi (stub aggregate) + olah hasil
# ══════════════════════════════════════════════════════════════════════════════
def _limit(pipeline):
    return next(s["$limit"] for s in pipeline[-1]["$facet"]["baris"] if "$limit" in s)


def test_batas_baris_langsung_dan_kode():
    db = DBStub()
    run(K.cari(ctx_untuk(db), {"dataset": "baris_jurnal"}))
    run(K.cari(ctx_untuk(db), {"dataset": "baris_jurnal", "batas": 5000}))
    run(K.cari(ctx_untuk(db, pemanggil="kode"), {"dataset": "baris_jurnal"}))
    run(K.cari(ctx_untuk(db, pemanggil="kode"), {"dataset": "baris_jurnal", "batas": 9999}))
    lim = [_limit(p) for _, p, _ in db.panggilan]
    assert lim == [K.BAWAAN_LANGSUNG, K.BATAS_LANGSUNG, K.BATAS_KODE, K.BATAS_KODE]
    assert all(kw.get("maxTimeMS") == K.MAKS_MS and kw.get("allowDiskUse") for _, _, kw in db.panggilan)
    assert {nama for nama, _, _ in db.panggilan} == {"rahaza_journal_lines"}


def test_bentuk_hasil_dan_sumber():
    db = DBStub(baris=[{"tanggal": "2026-10-01", "kode_akun": "1-1100", "debit": 1500000.0, "kredit": 0.0}], total=3)
    h = run(K.cari(ctx_untuk(db), {"dataset": "baris_jurnal", "kolom": ["tanggal", "kode_akun", "debit", "kredit"],
                                   "batas": 1}))
    assert h["dataset"] == "baris_jurnal" and h["label"] and h["_sumber"] == h["label"]
    assert [c["nama"] for c in h["kolom"]] == ["tanggal", "kode_akun", "debit", "kredit"]
    assert h["baris"] == [{"tanggal": "2026-10-01", "kode_akun": "1-1100", "debit": 1500000, "kredit": 0}]
    assert h["jumlah_baris"] == 1 and h["total_cocok"] == 3 and h["terpotong"] is True
    assert any("1 dari 3" in c for c in h["catatan"])
    assert h["cv"] == "CV Dewi Aditya"


def test_samaran_vendor_selalu_dan_karyawan_kecuali_sdm():
    db = DBStub(baris=[{"vendor": "CV Jahit Maju", "nilai_tagihan": 10.0}, {"vendor": "CV Jahit Maju"},
                       {"vendor": "Konveksi Lain"}])
    h = run(K.cari(ctx_untuk(db), {"dataset": "tagihan_cmt", "kolom": ["vendor", "nilai_tagihan"]}))
    v = [r["vendor"] for r in h["baris"]]
    assert v[0] == v[1] != v[2] and all(x.startswith("VND-") for x in v)
    assert "Jahit" not in json.dumps(h)
    db = DBStub(baris=[{"kode_karyawan": "K1", "nama": "Budi Santoso"}])
    db.roles.docs.append({"id": "r", "name": "kepala_unit", "portals": ["hr"]})
    h = run(K.cari(ctx_untuk(db, peran="owner"), {"dataset": "karyawan", "kolom": ["kode_karyawan", "nama"]}))
    assert h["baris"][0]["nama"] == "Budi Santoso"
    h = run(K.cari(ctx_untuk(db, peran="kepala_unit", izin=()), {"dataset": "karyawan",
                                                                 "kolom": ["kode_karyawan", "nama"]}))
    assert h["baris"][0]["nama"].startswith("KRY-")


def test_samaran_filter_memakai_kode_dari_giliran_yang_sama():
    db = DBStub(baris=[{"vendor": "CV Jahit Maju"}])
    c = ctx_untuk(db)
    kode = run(K.cari(c, {"dataset": "tagihan_cmt", "kolom": ["vendor"]}))["baris"][0]["vendor"]
    run(K.cari(c, {"dataset": "tagihan_cmt", "kolom": ["vendor"], "filter": [{"kolom": "vendor", "op": "=",
                                                                                "nilai": kode}]}))
    pipe = db.panggilan[-1][1]
    assert {"vendor": "CV Jahit Maju"} in [s["$match"] for s in pipe if "$match" in s]


def test_teks_bebas_disamarkan():
    db = DBStub(baris=[{"keterangan": "Transfer ke 081234567890 a.n. kontak@contoh.id"}])
    h = run(K.cari(ctx_untuk(db), {"dataset": "baris_jurnal", "kolom": ["keterangan"]}))
    assert "081234567890" not in h["baris"][0]["keterangan"] and "@" not in h["baris"][0]["keterangan"]


def test_pemangkasan_karakter_hanya_untuk_langsung():
    baris = [{"keterangan": "x" * 180, "no_jurnal": f"JE-{i}"} for i in range(200)]
    h = run(K.cari(ctx_untuk(DBStub(baris=baris)), {"dataset": "baris_jurnal", "kolom": ["no_jurnal", "keterangan"],
                                                     "batas": 200}))
    assert h["terpotong"] and h["jumlah_baris"] < 200
    assert len(ab.serialisasi({k: v for k, v in h.items() if k != "_sumber"})) <= ab.BATAS_HASIL
    h = run(K.cari(ctx_untuk(DBStub(baris=baris), pemanggil="kode"),
                   {"dataset": "baris_jurnal", "kolom": ["no_jurnal", "keterangan"], "batas": 200}))
    assert h["jumlah_baris"] == 200 and not h["terpotong"]


def test_galat_eksekusi_dan_akses_ramah():
    class ExecutionTimeout(Exception):
        pass
    with pytest.raises(AlatError) as e:
        run(K.cari(ctx_untuk(DBStub(galat=ExecutionTimeout("operation exceeded time limit"))),
                   {"dataset": "baris_jurnal"}))
    assert e.value.status == 504 and "Persempit" in e.value.pesan
    with pytest.raises(AlatError) as e:
        run(K.cari(ctx_untuk(DBStub(galat=RuntimeError("boom $where"))), {"dataset": "baris_jurnal"}))
    assert e.value.status == 500 and "boom" not in e.value.pesan
    with pytest.raises(AlatError) as e:
        run(K.cari(ctx_untuk(DBStub()), {"dataset": "tidak_ada"}))
    assert e.value.status == 404 and "daftar_data" in e.value.pesan
    with pytest.raises(AlatError) as e:
        run(K.cari(ctx_untuk(DBStub(), peran="manager_produksi", izin=()), {"dataset": "baris_jurnal"}))
    assert e.value.status == 403
    db = DBStub()
    with pytest.raises(AlatError) as e:
        run(K.cari(ctx_untuk(db), {"dataset": "baris_jurnal", "kolom": ["$where"]}))
    assert e.value.status == 400 and db.panggilan == []       # isian salah tidak pernah sampai ke basis data


def test_daftar_data_hanya_yang_boleh_dan_muat():
    db = DBStub()
    h = run(K.daftar(ctx_untuk(db), {}))
    assert len(h["dataset"]) == len(K.semua_dataset())
    assert len(ab.serialisasi(h)) < ab.BATAS_HASIL
    assert all(isinstance(d["kolom"], str) for d in h["dataset"])
    h = run(K.daftar(ctx_untuk(db, peran="kepala_unit", izin=()), {}))
    assert h["dataset"] == []
    db.roles.docs.append({"id": "r", "name": "kepala_hr", "portals": ["hr"]})
    h = run(K.daftar(ctx_untuk(db, peran="kepala_hr", izin=()), {}))
    assert {d["id"] for d in h["dataset"]} == {"karyawan", "absensi"}
    kar = next(d for d in h["dataset"] if d["id"] == "karyawan")
    assert "gaji" not in kar["kolom"]
    rinci = run(K.daftar(ctx_untuk(db, peran="kepala_hr", izin=()), {"dataset": "karyawan"}))["dataset"][0]
    nama = {k["nama"]: k for k in rinci["kolom"]}
    assert "gaji_pokok" not in nama and nama["nama"].get("samaran") is True
    assert "karyawan_bulan" not in nama and "tanggal_masuk_bulan" in nama
    with pytest.raises(AlatError):
        run(K.daftar(ctx_untuk(db, peran="kepala_hr", izin=()), {"dataset": "baris_jurnal"}))


# ══════════════════════════════════════════════════════════════════════════════
# Pendaftaran alat
# ══════════════════════════════════════════════════════════════════════════════
def test_alat_terdaftar_sesuai_kontrak():
    import importlib
    importlib.import_module("core.asisten_ai.alat.cari_data")
    cari, daftar = ab._DAFTAR["cari_data"], ab._DAFTAR["daftar_data"]
    assert cari.kind == "read" and cari.kode is True and cari.label.startswith("Mencari data")
    assert daftar.kind == "read" and daftar.kode is False
    assert "daftar_data" in cari.description and "kode" in cari.description
    isian = {"dataset": "baris_jurnal", "kolom": ["tanggal"], "periode": {"dari": "2026-10-01", "sampai": "2026-10-31"},
             "filter": [{"kolom": "kode_akun", "op": "in", "nilai": ["1-1100", "1-1200"]},
                        {"kolom": "keterangan", "op": "kosong"}],
             "kelompok": ["tanggal_bulan"], "agregasi": [{"fungsi": "jumlah", "kolom": "debit", "nama": "total_debit"}],
             "urut": [{"kolom": "total_debit", "arah": "turun"}], "batas": 50}
    assert ab.periksa_skema(cari.input_schema, isian) == []
    assert ab.periksa_skema(cari.input_schema, {"dataset": "x", "filter": [{"kolom": "a", "op": "$gt"}]})
    assert ab.periksa_skema(cari.input_schema, {"dataset": "x", "filter": [{"kolom": "a", "op": "=",
                                                                            "nilai": {"$gt": 1}}]})
    assert ab.periksa_skema(daftar.input_schema, {}) == []
    db = DBStub(baris=[{"tanggal_bulan": "2026-10", "total_debit": 5.0}])
    h = run(cari.handler(ctx_untuk(db), isian))
    assert h["baris"] == [{"tanggal_bulan": "2026-10", "total_debit": 5}]
