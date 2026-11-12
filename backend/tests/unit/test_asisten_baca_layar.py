"""Uji HERMETIK bacaan layar Asisten ERP (12 Nov 2026, owner: "semuanya bisa dilakukan").

  * satu uji per baris bacaan (GET yang dipakai layar aktif): pintu route masih ada, tidak terlarang, polanya cocok;
  * alat `cari_bacaan` & `baca_layar`: alamat tak dikenal/terlarang ditolak, query diperiksa, daftar dipangkas,
    data disamarkan, mode atas nama vendor CMT hanya untuk bacaan/peran yang boleh, ruang SDM/Saya disaring;
  * `jalankan_aksi`: mode atas nama vendor (header ikut di baca & tulis), filter ruang, nominal dari baris jurnal;
  * lampiran chat menyebut `lampiran_id` (untuk impor berkas lewat kartu).
Jalankan:  cd backend && python -m pytest tests/unit/test_asisten_baca_layar.py -n 0 -q
"""
import asyncio
import copy
import importlib
import os
import re
import sys
from datetime import date
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ai_fakes  # noqa: E402,F401
import _fake_mongo as fm  # noqa: E402

from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai import katalog_aksi as kat  # noqa: E402
from core.asisten_ai import lampiran as lmp  # noqa: E402
from core.asisten_ai import tindakan as tdk  # noqa: E402
from core.asisten_ai.alat import aksi_umum as au  # noqa: E402
from core.asisten_ai.alat import baca_layar as bl  # noqa: E402
from core.asisten_ai.katalog_aksi import aturan  # noqa: E402

ADMIN = {"id": "u-admin", "name": "Admin", "email": "a@contoh.test", "role": "admin"}
PPIC = {"id": "u-ppic", "name": "PPIC", "email": "p@contoh.test", "role": "ppic"}
STAF = {"id": "u-staf", "name": "Staf", "email": "s@contoh.test", "role": "finance_staff"}
BACAAN = kat.semua_bacaan()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class Ctx:
    def __init__(self, user=ADMIN, cv="DA", ruang="umum", jawab=None, alasan=""):
        self.user, self.cv, self.ruang, self.alasan = dict(user), cv, ruang, alasan
        self.today = date(2026, 11, 12)
        self.jawab = jawab or {}
        self.calls = []

    @property
    def peran(self):
        return self.user["role"]

    def mask(self, obj, **_k):
        return {"_disamarkan": True, "isi": obj}

    async def api(self, method, path, params=None, json=None, headers=None, **kw):
        self.calls.append((method, path, dict(params or {}), copy.deepcopy(json), dict(headers or {})))
        for pola, isi in self.jawab.items():
            if re.fullmatch(pola, path):
                return copy.deepcopy(isi)
        return {"items": [{"id": "x1", "status": "draft"}], "data": {"id": "x1", "status": "draft"}}


@pytest.fixture
def env(monkeypatch):
    st = {"gol": {"A": True, "B": True, "C": True, "D": True}}

    async def _gol(_u):
        return dict(st["gol"])

    async def _atur():
        return {"aktif": True, "batas": 100, "batas_nominal_transaksi": 0, "batas_nominal_harian": 0}

    async def _nom(*_a, **_k):
        return 0.0
    monkeypatch.setattr(au, "_golongan_boleh", _gol)
    monkeypatch.setattr(au, "_db", lambda: fm.FakeDB())
    monkeypatch.setattr(tdk, "pengaturan", _atur)
    monkeypatch.setattr(tdk, "nominal_hari_ini", _nom)
    return st


def A(nama):
    ab.muat_semua_alat()
    return ab._DAFTAR[nama]


_ROUTER: dict = {}


def _rute(modul):
    if modul not in _ROUTER:
        try:
            m = importlib.import_module("routes." + modul)
        except Exception as e:  # noqa: BLE001
            _ROUTER[modul] = e
        else:
            from fastapi import APIRouter
            _ROUTER[modul] = [r for v in vars(m).values() if isinstance(v, APIRouter) for r in v.routes]
    return _ROUTER[modul]


# ═══ Satu uji per bacaan ═════════════════════════════════════════════════════
def test_bacaan_lengkap_unik_dan_tanpa_rahasia():
    assert len(BACAAN) >= 700
    assert len({b["jalur"] for b in BACAAN}) == len(BACAAN)
    assert len({b["id"] for b in BACAAN}) == len(BACAAN)
    for b in BACAAN:
        assert not aturan.larangan_baca(b["jalur"]), b["jalur"]
        assert not aturan.di_luar_katalog(b["modul"]), b["jalur"]


@pytest.mark.parametrize("b", BACAAN, ids=[b["id"] for b in BACAAN])
def test_baris_bacaan(b):
    assert b["jalur"].startswith("/api/")
    assert b["parameter_jalur"] == re.findall(r"\{(\w+)(?::[^}]*)?\}", b["jalur"])
    contoh = re.sub(r"\{(\w+)(?::[^}]*)?\}", "nilai-uji", b["jalur"])
    ketemu = kat.bacaan_untuk(contoh)
    assert ketemu is not None
    assert len(ketemu[0]["parameter_jalur"]) <= len(b["parameter_jalur"])
    if b.get("menu"):
        assert ab._MENU_RX.match(b["menu"])
    rs = _rute(b["modul"])
    if isinstance(rs, Exception):
        pytest.skip(f"routes.{b['modul']} tidak bisa diimpor di lingkungan uji")
    assert [r for r in rs if getattr(r, "endpoint", None) is not None and r.endpoint.__name__ == b["fungsi"]
            and "GET" in (r.methods or set()) and b["jalur"].endswith(r.path)], b["jalur"]


# ═══ Aturan bacaan ═══════════════════════════════════════════════════════════
def test_larangan_baca_dan_ruang():
    for j in ("/api/admin/backup/list", "/api/rahaza/integration-settings", "/api/dewi/system/config",
              "/api/ai/usage/settings", "/api/asisten-ai/sessions", "/api/rahaza/journals/export",
              "/api/wms/labels/print", "/api/marketing/orders/download.xlsx", "/api/x/api-keys"):
        assert aturan.larangan_baca(j), j
    assert aturan.larangan_baca("/api/uploads/{path:path}") and aturan.larangan_baca("/api/x/uploads")
    for j in ("/api/rahaza/coa/accounts", "/api/production-job-items", "/api/portal/profile", "/api/hr/profile"):
        assert aturan.larangan_baca(j) is None, j
    assert aturan.di_ruang(["Keuangan"], "umum") and not aturan.di_ruang(["Keuangan"], "sdm")
    assert aturan.di_ruang(["SDM", "Keuangan"], "sdm") and aturan.di_ruang(["Portal Saya"], "saya")
    assert not aturan.di_ruang([], "saya")


# ═══ cari_bacaan & baca_layar ════════════════════════════════════════════════
def test_cari_bacaan_menemukan_bagan_akun_dan_baris_pekerjaan(env):
    cari = A("cari_bacaan").handler
    out = run(cari(Ctx(), {"kata": "bagan akun"}))["hasil"]["bacaan"]
    assert "/api/rahaza/coa/accounts" in [x["alamat"] for x in out]
    out = run(cari(Ctx(), {"kata": "production job items"}))["hasil"]["bacaan"]
    assert "/api/production-job-items" in [x["alamat"] for x in out]


def test_baca_layar_aturan(env):
    baca = A("baca_layar").handler
    # daftar kecil (105 akun ringkas) muat utuh; kolom jejak sistem dibuang
    akun = [{"code": str(i), "name": f"Akun {i}", "type": "EXPENSE", "created_at": "2026-01-01"} for i in range(105)]
    ctx = Ctx(jawab={r"/api/rahaza/coa/accounts": akun})
    out = run(baca(ctx, {"alamat": "/api/rahaza/coa/accounts"}))
    data = out["hasil"]["data"]
    assert data["_disamarkan"] and len(data["isi"]) == 105 and "created_at" not in data["isi"][0]
    assert "catatan" not in out["hasil"] and ctx.calls[0][:2] == ("GET", "/api/rahaza/coa/accounts")
    # daftar besar dipangkas menurut ukuran, dengan catatan; dari kode (ruang hitung) jauh lebih longgar
    besar = {"items": [{"id": f"id-{i}", "keterangan": "x" * 200} for i in range(500)], "total": 500}
    ctx = Ctx(jawab={r"/api/rahaza/coa/accounts": besar})
    out = run(baca(ctx, {"alamat": "/api/rahaza/coa/accounts"}))
    n = len(out["hasil"]["data"]["isi"]["items"])
    assert 5 < n < 100 and "500 baris" in out["hasil"]["catatan"][0] and out["hasil"]["data"]["isi"]["total"] == 500
    ctx.pemanggil = "kode"
    assert len(run(baca(ctx, {"alamat": "/api/rahaza/coa/accounts"}))["hasil"]["data"]["isi"]["items"]) == 500
    for alamat, kode in (("/api/tidak/ada/sama/sekali", 404), ("/api/admin/backup/list", 403),
                         ("/api/rahaza/journals/export", 403)):
        with pytest.raises(ab.AlatError) as e:
            run(baca(Ctx(), {"alamat": alamat}))
        assert e.value.status == kode, alamat
    b = next(x for x in BACAAN if x["jalur"] == "/api/rahaza/coa/accounts")
    # query diteruskan apa adanya (pintu yang membaca request.query_params sendiri, mis. ?job_id=)
    ctx = Ctx()
    run(baca(ctx, {"alamat": "/api/rahaza/coa/accounts", "query": {"type": "EXPENSE", "job_id": "j1"}}))
    assert ctx.calls[-1][2] == {"type": "EXPENSE", "job_id": "j1"}
    pji = next(x for x in BACAAN if x["jalur"] == "/api/production-job-items")
    assert "job_id" in {q["nama"] for q in pji["query"]}     # dibaca manual oleh pintunya, tercatat di katalog
    # ruang SDM tidak membaca bacaan yang bukan portal SDM
    if "SDM" not in (b.get("portal") or []):
        with pytest.raises(ab.AlatError) as e:
            run(baca(Ctx(ruang="sdm"), {"alamat": "/api/rahaza/coa/accounts"}))
        assert e.value.status == 403


def test_baca_layar_atas_nama_vendor(env):
    baca = A("baca_layar").handler
    bv = next(b for b in BACAAN if b.get("atas_nama_vendor") and not b["parameter_jalur"])
    ctx = Ctx(user=PPIC)
    run(baca(ctx, {"alamat": bv["jalur"], "atas_nama_vendor": "ven-1"}))
    assert ctx.calls[-1][4] == {bl.HEADER_VENDOR: "ven-1"}
    with pytest.raises(ab.AlatError) as e:
        run(baca(Ctx(user=STAF), {"alamat": bv["jalur"], "atas_nama_vendor": "ven-1"}))
    assert e.value.status == 403
    tanpa = next(b for b in BACAAN if not b.get("atas_nama_vendor") and not b["parameter_jalur"])
    with pytest.raises(ab.AlatError) as e:
        run(baca(Ctx(user=PPIC), {"alamat": tanpa["jalur"], "atas_nama_vendor": "ven-1"}))
    assert e.value.status == 400


# ═══ jalankan_aksi: vendor, ruang, nominal jurnal, petunjuk ═══════════════════
def test_progres_cmt_atas_nama_vendor(env):
    a = kat.ambil("post_production_progress")
    assert a and a.get("atas_nama_vendor") and a["cari_id"]["job_item_id"] == ["/api/production-job-items"]
    K = A("jalankan_aksi").kelas
    args = {"aksi": a["id"], "isian": {"job_item_id": "ji-1", "completed_quantity": 50, "progress_date": "2026-11-12"},
            "atas_nama_vendor": "ven-1"}
    jawab = {r"/api/vendor-portal/partners": [{"id": "ven-1", "name": "CMT Maju"}]}
    r = tdk.rapikan_rencana(run(K.siapkan(Ctx(user=PPIC, jawab=jawab), copy.deepcopy(args))), args, A("jalankan_aksi"))
    assert any("CMT Maju" in c for c in r["catatan"])
    ctx = Ctx(user=PPIC, jawab=jawab, alasan="input dari rekap harian")
    run(K.jalankan(ctx, copy.deepcopy(args), r))
    tulis = [c for c in ctx.calls if c[0] != "GET"]
    assert tulis[0][:2] == ("POST", "/api/production-progress") and tulis[0][4] == {bl.HEADER_VENDOR: "ven-1"}
    # vendor tidak ada di master → ditolak; peran tak berhak → ditolak; aksi tanpa mode vendor → ditolak
    with pytest.raises(ab.AlatError) as e:
        run(K.siapkan(Ctx(user=PPIC, jawab={r"/api/vendor-portal/partners": []}), copy.deepcopy(args)))
    assert e.value.status == 404
    with pytest.raises(ab.AlatError) as e:
        run(K.siapkan(Ctx(user=STAF, jawab=jawab), copy.deepcopy(args)))
    assert e.value.status == 403
    with pytest.raises(ab.AlatError) as e:
        run(K.siapkan(Ctx(user=ADMIN), {"aksi": "post_procurement_suppliers", "isian": {"name": "x"},
                                        "atas_nama_vendor": "ven-1"}))
    assert e.value.status == 400


def test_jurnal_nominal_dari_baris_dan_petunjuk_isian(env):
    a = kat.ambil("post_rahaza_journals")
    m = kat.ringkas_untuk_model(a)
    assert {"account_code", "debit", "credit"} <= set(m["isian_bersarang"]["lines"])
    K = A("jalankan_aksi").kelas
    args = {"aksi": a["id"], "isian": {"date": "2026-11-12", "memo": "Biaya listrik November", "lines": [
        {"account_code": "6110", "debit": 1_250_000, "credit": 0, "description": "Listrik"},
        {"account_code": "1110", "debit": 0, "credit": 1_250_000, "description": "Kas"}]}}
    r = tdk.rapikan_rencana(run(K.siapkan(Ctx(), copy.deepcopy(args))), args, A("jalankan_aksi"))
    assert r["risiko"] == "tinggi" and r["nominal"] == 1_250_000 and r["konfirmasi"]["teks"] == "1250000"
    assert au._nominal_baris([{"qty": 2, "unit_price": 5000}, {"amount": 1000}]) == 11000
    assert au._nominal({"items": [{"qty": "3", "price": "1000"}]}, {}) == 3000


def test_ruang_menyaring_aksi(env):
    cari = A("cari_aksi").handler
    hasil = run(cari(Ctx(ruang="sdm"), {"kata": "kirim faktur piutang"}))["hasil"]["aksi"]
    assert all("SDM" in x["portal"] for x in hasil)
    with pytest.raises(ab.AlatError) as e:
        run(A("jalankan_aksi").kelas.siapkan(Ctx(ruang="saya"), {"aksi": "post_rahaza_ar_invoices_id_send",
                                                                 "jalur": {"iid": "INV-1"}}))
    assert e.value.status == 403
    # alat katalog ditawarkan di AI SDM & Tanya Asisten
    assert ab.alat_di_ruang(A("jalankan_aksi"), "saya") and ab.alat_di_ruang(A("baca_layar"), "sdm")


def test_lampiran_menyebut_id_untuk_impor():
    blok = lmp.blok_api([{"id": "lmp-9", "nama": "rekap.xlsx", "jenis": "tabel", "ukuran": 2048, "ext": ".xlsx",
                          "ringkasan_model": "Lembar 1: 3 kolom"}], kode=False)
    assert "lampiran_id: lmp-9" in blok[0]["text"]


def test_ctx_ruang_ikut_salinan_dan_kartu():
    c = ab.AlatContext(user=ADMIN, cv="DA", today=date(2026, 11, 12), ruang="sdm")
    assert c.untuk_alat("t1").ruang == "sdm" and c.untuk_tindakan("k1", tulis=False).ruang == "sdm"
    assert ab.AlatContext(user=ADMIN, cv="DA", today=date(2026, 11, 12), ruang="aneh").ruang == "umum"
    d = {"id": "k1", "cv": "DA", "tool_use_id": "t", "sesi_id": "s", "ruang": "saya"}
    assert tdk.buat_ctx(user=ADMIN, doc=d, token="x", tulis=False).ruang == "saya"
    db = fm.FakeDB()
    doc = run(tdk.buat(db, user=ADMIN, sesi_id="s", pesan_id=None, tool_use_id="t", alat=A("jalankan_aksi"),
                       args={"aksi": "x"}, rencana={"judul": "J"}, cv="DA", periode="2026-11", ruang="sdm"))
    assert doc["ruang"] == "sdm" and db.ai_actions.docs[0]["ruang"] == "sdm"


def test_cari_aksi_memberi_petunjuk_id(env):
    hasil = run(A("cari_aksi").handler(Ctx(), {"kata": "progress produksi"}))["hasil"]["aksi"]
    p = next((x for x in hasil if x["aksi"] == "post_production_progress"), None)
    assert p and p["cari_id"]["job_item_id"] and "atas_nama_vendor" in p and "contoh_layar" in p
    assert SimpleNamespace  # dipakai di modul lain uji ini
