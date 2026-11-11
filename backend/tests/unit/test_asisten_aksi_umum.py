"""Uji HERMETIK katalog aksi Asisten ERP — "semua aksi sistem" (keputusan owner K1–K10, 12 Nov 2026).

Isi:
  * SATU uji per baris katalog (±1.084 aksi): baris sah, pintu route-nya masih ada, kartu tersusun dengan tingkat &
    golongan yang benar, aksi terlarang ditolak, dan `jalankan` memanggil TEPAT pintu layar itu (metode + alamat);
  * aturan golongan/larangan/tingkat (aturan.py), saklar golongan per pengguna, batas nominal di pengaturan;
  * alat `cari_aksi` & `jalankan_aksi`: isian PUT lengkap, sidik nilai lama, kartu kelompok, hapus permanen ditolak,
    CV Gabungan ditolak untuk stok/uang, persetujuan kedua, pembalikan;
  * mesin kartu: risiko tinggi (alasan + ketik ulang), keadaan `menunggu_kedua`, persetujuan kedua owner.

Mongo = tiruan in-memory; endpoint aplikasi = ctx tiruan yang mencatat panggilan. Tanpa jaringan.
Jalankan:  cd backend && python -m pytest tests/unit/test_asisten_aksi_umum.py -n 0 -q
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
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ai_fakes  # noqa: E402,F401 — env uji + path backend
import _fake_mongo as fm  # noqa: E402

import ai_cost_tracker as t  # noqa: E402
from core.asisten_ai import akses_pengguna as akp  # noqa: E402
from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai import katalog_aksi as kat  # noqa: E402
from core.asisten_ai import tindakan as tdk  # noqa: E402
from core.asisten_ai.alat import aksi_umum as au  # noqa: E402
from core.asisten_ai.katalog_aksi import aturan  # noqa: E402

OWNER = {"id": "u-owner", "name": "Pemilik", "email": "owner@contoh.test", "role": "owner", "status": "active"}
SUPER = {"id": "u-super", "name": "Super", "email": "super@contoh.test", "role": "superadmin", "status": "active"}
ADMIN = {"id": "u-admin", "name": "Admin", "email": "admin@contoh.test", "role": "admin", "status": "active"}
STAF = {"id": "u-staf", "name": "Staf Keuangan", "email": "staf@contoh.test", "role": "finance_staff",
        "status": "active"}
SEMUA = {"A": True, "B": True, "C": True, "D": True}
DATA = kat.semua()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class Ctx:
    """ctx tiruan: GET → dokumen nilai lama; tulis dicatat; jawaban tulis = {"id": "baru-1"}."""

    def __init__(self, user=ADMIN, cv="DA", lama=None, gagal=None, alasan=""):
        self.user, self.cv, self.alasan = dict(user), cv, alasan
        self.today = date(2026, 11, 12)
        self.lama = lama if lama is not None else {"id": "x1", "status": "draft", "number": "DOC-1"}
        self.gagal = gagal or {}
        self.calls = []

    @property
    def peran(self):
        return str(self.user.get("role") or "").lower()

    @property
    def tulis(self):
        return [c for c in self.calls if c[0] != "GET"]

    def mask(self, obj, **_k):
        return obj

    async def api(self, method, path, params=None, json=None, **kw):
        self.calls.append((method.upper(), path, dict(params or {}), copy.deepcopy(json), kw))
        if path in self.gagal and method.upper() != "GET":
            raise ab.AlatError(*self.gagal[path])
        if method.upper() == "GET":     # bentuk detail ({data: …}) sekaligus daftar ({items: [...]})
            return {"data": copy.deepcopy(self.lama), "items": [copy.deepcopy(self.lama)]}
        return {"id": "baru-1", "status": "ok"}


@pytest.fixture
def env(monkeypatch):
    db = fm.FakeDB()
    st = {"gol": dict(SEMUA), "atur": {"aktif": True, "batas": 100, "batas_nominal_transaksi": 0,
                                       "batas_nominal_harian": 0}, "hari_ini": 0.0}

    async def _gol(_user):
        return dict(st["gol"])

    async def _atur():
        return dict(st["atur"])

    async def _nominal(*_a, **_k):
        return st["hari_ini"]

    monkeypatch.setattr(au, "_golongan_boleh", _gol)
    monkeypatch.setattr(au, "_db", lambda: db)
    monkeypatch.setattr(tdk, "pengaturan", _atur)
    monkeypatch.setattr(tdk, "nominal_hari_ini", _nominal)
    return SimpleNamespace(db=db, st=st)


def K():
    ab.muat_semua_alat()
    return ab._DAFTAR["jalankan_aksi"]


def _contoh(skema):
    t_ = skema.get("type")
    if "enum" in skema:
        return skema["enum"][0]
    t_ = t_[0] if isinstance(t_, list) else t_
    if t_ in ("integer", "number"):
        v = skema.get("minimum", 2)
        v = min(v, skema["maximum"]) if "maximum" in skema else v
        return int(v) if t_ == "integer" else float(v)
    if t_ == "string":
        if skema.get("format") == "date":
            return "2026-11-12"
        if skema.get("format") == "date-time":
            return "2026-11-12T08:00:00+07:00"
        return "baru" + "x" * max(0, int(skema.get("minLength") or 0) - 4)
    return {"boolean": True, "array": [], "object": {}}.get(t_, "baru")


def args_untuk(a: dict) -> dict:
    """Isian uji minimal yang sah untuk satu baris katalog."""
    args = {"aksi": a["id"]}
    if a["parameter_jalur"]:
        args["jalur"] = {p: f"x-{p}" for p in a["parameter_jalur"]}
    q = {x["nama"]: "1" for x in a["query"] if x["wajib"] and x["nama"] not in aturan.QUERY_HAPUS_PERMANEN}
    if q:
        args["query"] = q
    isi = a["isian"] or {}
    if isi.get("bentuk") == "bertipe":
        sk = isi.get("skema") or {}
        props = sk.get("properties") or {}
        wajib = sk.get("required") or list(props)[:1]
        args["isian"] = {k: _contoh(props.get(k) or {}) for k in wajib}
    elif isi.get("bentuk") == "bebas":
        args["isian"] = {(isi.get("kunci") or ["catatan_uji"])[0]: "baru"}
    elif isi.get("bentuk") == "berkas":
        args["lampiran_id"] = "lmp-1"
    return args


# ═══ Satu uji per baris katalog ══════════════════════════════════════════════
def test_katalog_lengkap_dan_kunci_unik():
    assert len(DATA) >= 1000, "katalog aksi menyusut — susun ulang dengan scripts/asisten_katalog/buat_katalog.py"
    ids = [a["id"] for a in DATA]
    assert len(ids) == len(set(ids))
    jalur = [(a["metode"], a["jalur"]) for a in DATA]
    assert len(jalur) == len(set(jalur))
    keluar = {(k["metode"], k["jalur"]) for k in kat.muat()["dikecualikan"]}
    assert not keluar & set(jalur)
    # K1: bukti diri & pengaturan Asisten tidak pernah masuk katalog
    assert not [a for a in DATA if aturan.di_luar_katalog(a["modul"])]


_ROUTER_CACHE: dict = {}


def _rute_modul(modul: str):
    if modul not in _ROUTER_CACHE:
        try:
            m = importlib.import_module("routes." + modul)
        except Exception as e:  # noqa: BLE001 — paket opsional tidak terpasang di job CI unit
            _ROUTER_CACHE[modul] = e
        else:
            from fastapi import APIRouter
            rs = []
            for v in vars(m).values():
                if isinstance(v, APIRouter):
                    rs.extend(v.routes)
            _ROUTER_CACHE[modul] = rs
    return _ROUTER_CACHE[modul]


@pytest.mark.parametrize("a", DATA, ids=[a["id"] for a in DATA])
def test_baris_katalog(a, env):
    # 1) bentuk baris sah
    assert re.fullmatch(r"[a-z0-9_]{3,130}", a["id"])
    assert a["metode"] in ("POST", "PUT", "PATCH", "DELETE") and a["jalur"].startswith("/api/")
    assert a["golongan"] in aturan.GOLONGAN_KUNCI
    assert a["golongan"] == aturan.golongan_untuk(a["modul"], a["jalur"])
    assert a["tingkat"] == aturan.tingkat_untuk(a["golongan"], a["jenis"])
    assert a["parameter_jalur"] == re.findall(r"\{(\w+)(?::[^}]*)?\}", a["jalur"])
    if aturan.larangan_untuk(a["metode"], a["jalur"]):
        assert a.get("larangan")
    if a["balik"]:
        assert a["golongan"] == "A"
    if a["baca"]:
        assert set(re.findall(r"\{(\w+)", a["baca"])) <= set(a["parameter_jalur"])
    if a["menu"]:
        assert ab._MENU_RX.match(a["menu"])
    # 2) pintu route-nya masih ada (tanpa impor server.py: cari di router modulnya)
    rs = _rute_modul(a["modul"])
    if isinstance(rs, Exception):
        pytest.skip(f"modul routes.{a['modul']} tidak bisa diimpor di lingkungan uji: {type(rs).__name__}")
    cocok = [r for r in rs if getattr(r, "endpoint", None) is not None and r.endpoint.__name__ == a["fungsi"]
             and a["metode"] in (r.methods or set()) and a["jalur"].endswith(r.path)]
    assert cocok, f"pintu {a['metode']} {a['jalur']} ({a['modul']}.{a['fungsi']}) tidak ada lagi — susun ulang katalog"
    # 3) kartu
    if a["isian"].get("bentuk") == "berkas":
        env.db.ai_lampiran.docs.append({"id": "lmp-1", "user_id": ADMIN["id"], "path": "ai_lampiran/x/y.xlsx",
                                        "nama": "data.xlsx", "mime": "application/vnd.ms-excel", "ukuran": 2048})
    args = args_untuk(a)
    errs = ab.periksa_skema(K().input_schema, args)
    assert not errs, errs
    lama = {"id": "x1", "status": "draft", "number": "DOC-1"}
    if a.get("baca_daftar"):
        lama["id"] = args["jalur"][a["baca_daftar"]["kunci"]]
    ctx = Ctx(lama=lama)
    if a.get("larangan"):
        with pytest.raises(ab.AlatError) as e:
            run(K().siapkan(ctx, copy.deepcopy(args)))
        assert e.value.status == 403
        return
    rencana = run(K().siapkan(ctx, copy.deepcopy(args)))
    assert not ctx.tulis, "siapkan tidak boleh menulis"
    out = tdk.rapikan_rencana(rencana, args, K())
    assert out["judul"] and out["perubahan"] and out["risiko"] == a["tingkat"] and out["golongan"] == a["golongan"]
    if a["tingkat"] == "tinggi":
        assert out["konfirmasi"]["teks"] and out["konfirmasi"]["petunjuk"]
    if a["golongan"] == "C":      # ADMIN bukan owner & batas nominal belum diisi → persetujuan kedua
        assert out["persetujuan_kedua"]["perlu"]
    # 4) jalankan memanggil TEPAT pintu layar
    ctx2 = Ctx(lama=lama, alasan="alasan uji yang cukup panjang")
    if a["isian"].get("bentuk") == "berkas":
        import object_storage
        object_storage_lama = object_storage.get_object
        object_storage.get_object = lambda _p: (b"isi", "application/octet-stream")
        try:
            hasil = run(K().jalankan(ctx2, copy.deepcopy(args), out))
        finally:
            object_storage.get_object = object_storage_lama
    else:
        hasil = run(K().jalankan(ctx2, copy.deepcopy(args), out))
    tulis = ctx2.tulis
    assert len(tulis) == 1
    harap = au._isi_jalur(a["jalur"], args.get("jalur") or {})
    assert (tulis[0][0], tulis[0][1]) == (a["metode"], harap)
    if a["isian"].get("bentuk") == "berkas":
        assert tulis[0][4].get("files")
    assert hasil["ringkas"]


# ═══ Aturan ══════════════════════════════════════════════════════════════════
def test_aturan_larangan_k5_sampai_k8():
    for m, j, kode in (("POST", "/api/wms/opname3/scan", "K5"), ("POST", "/api/wms/opname3/count", "K5"),
                       ("POST", "/api/wh/scan-out/scan", "K5"), ("POST", "/api/rahaza/periods/{period_code}/lock", "K6"),
                       ("POST", "/api/rahaza/year-end/close", "K6"), ("PUT", "/api/roles/{role_id}", "K7"),
                       ("POST", "/api/users", "K7"), ("POST", "/api/admin/backup/restore", "K7"),
                       ("PUT", "/api/ai/usage/settings", "K7"), ("POST", "/api/rahaza/coa/seed", "K7"),
                       ("DELETE", "/api/rahaza/coa/accounts/{aid}", "K8")):
        assert (aturan.larangan_untuk(m, j) or {}).get("kode") == kode, j
    # opname: dokumennya boleh (ajukan/setujui), hitung fisiknya tidak
    assert aturan.larangan_untuk("POST", "/api/wms/opname3/approve") is None
    assert aturan.larangan_untuk("POST", "/api/rahaza/ar-invoices/{iid}/send") is None
    # tidak ada baris katalog yang membuka larangan
    for a in DATA:
        if aturan.larangan_untuk(a["metode"], a["jalur"]):
            assert kat.larangan(a)


def test_aturan_golongan_tingkat_dan_saklar():
    assert aturan.golongan_untuk("rahaza_finance", "/api/rahaza/ar-invoices/{iid}/send") == "C"
    assert aturan.golongan_untuk("production_pos", "/api/production-pos/{po_id}/close") == "C"
    assert aturan.golongan_untuk("production_pos", "/api/production-pos/{po_id}") == "A"
    assert aturan.golongan_untuk("wms_receiving", "/api/wms/receiving") == "B"
    assert aturan.golongan_untuk("vendor_portal", "/api/vendor-portal/partners") == "A"
    assert aturan.golongan_untuk("vendor_portal", "/api/vendor-portal/accounts") == "D"
    assert [aturan.tingkat_untuk(g, j) for g, j in (("A", "buat"), ("A", "hapus"), ("B", "aksi"), ("C", "buat"),
                                                     ("D", "ubah"))] == ["rendah", "menengah", "menengah", "tinggi",
                                                                         "tinggi"]
    assert aturan.golongan_efektif("owner", None) == SEMUA
    assert aturan.golongan_efektif("superadmin", {"C": False}) == SEMUA
    assert aturan.golongan_efektif("finance_staff", None) == {"A": True, "B": False, "C": False, "D": False}
    assert aturan.golongan_efektif("finance_staff", {"C": True, "D": True}) == {"A": True, "B": False, "C": True,
                                                                               "D": False}
    assert aturan.golongan_efektif("admin", {"D": True})["D"] is True


def test_saklar_golongan_per_pengguna_validasi_dan_simpan():
    assert akp.rapikan_masukan({"golongan": {"B": True, "C": None}}, peran_target="staff_gudang") == {
        "golongan": {"B": True, "C": None}}
    for body, peran in (({"golongan": {"A": True}}, "staff"), ({"golongan": {"D": True}}, "finance_staff"),
                        ({"golongan": {"C": "ya"}}, "staff"), ({"golongan": {"C": True}}, "owner"),
                        ({"golongan": []}, "staff")):
        with pytest.raises(ValueError):
            akp.rapikan_masukan(body, peran_target=peran)
    assert akp.rapikan_masukan({"golongan": {"D": True}}, peran_target="admin")["golongan"] == {"D": True}
    db = fm.FakeDB()
    db.users.docs.append({"id": "u1", "role": "staff_gudang", "asisten_ai": {"aktif": True, "golongan": {"B": True}}})
    run(akp.simpan(db, "u1", {"golongan": {"C": True}}, oleh="owner"))
    run(akp.simpan(db, "u1", {"golongan": {"B": None}}, oleh="owner"))
    cfg = db.users.docs[0]["asisten_ai"]
    assert cfg["golongan"] == {"C": True} and cfg["aktif"] is True
    assert akp.golongan_tersimpan(cfg) == {"B": None, "C": True, "D": None}
    a = akp.aturan_dari(db.users.docs[0], "staff_gudang", {})
    assert a["golongan"] == {"A": True, "B": False, "C": True, "D": False}


def test_setelan_batas_nominal_hanya_owner(monkeypatch):
    from routes import ai_usage_monitor as mon
    db = fm.FakeDB()
    db.ai_config.docs.append({"id": "global"})
    setelan = {**t._default_ai_settings()}
    state = {"u": OWNER}

    async def _setelan(*_a, **_k):
        return dict(setelan)

    async def _auth(_r):
        return dict(state["u"])
    monkeypatch.setattr(mon, "get_ai_settings", _setelan)
    monkeypatch.setattr(mon, "get_db", lambda: db)
    monkeypatch.setattr(mon, "require_auth", _auth)
    monkeypatch.setattr(mon, "invalidate_ai_settings_cache", lambda: None, raising=False)
    run(mon.update_settings(SimpleNamespace(), payload={"asisten_batas_nominal_transaksi": 5_000_000,
                                                        "asisten_batas_nominal_harian": "20000000"}))
    assert db.ai_config.docs[0]["asisten_batas_nominal_transaksi"] == 5_000_000
    assert db.ai_config.docs[0]["asisten_batas_nominal_harian"] == 20_000_000
    for p in ({"asisten_batas_nominal_transaksi": -1}, {"asisten_batas_nominal_harian": "x"},
              {"asisten_batas_nominal_harian": True}):
        with pytest.raises(HTTPException) as e:
            run(mon.update_settings(SimpleNamespace(), payload=p))
        assert e.value.status_code == 400
    state["u"] = ADMIN
    with pytest.raises(HTTPException) as e:
        run(mon.update_settings(SimpleNamespace(), payload={"asisten_batas_nominal_transaksi": 1}))
    assert e.value.status_code == 403


# ═══ cari_aksi ═══════════════════════════════════════════════════════════════
def test_cari_aksi_menemukan_dan_menandai(env):
    ab.muat_semua_alat()
    cari = ab._DAFTAR["cari_aksi"].handler
    out = run(cari(Ctx(), {"kata": "kirim faktur piutang"}))["hasil"]
    assert out["aksi"][0]["aksi"] == "post_rahaza_ar_invoices_id_send"
    env.st["gol"] = {"A": True, "B": False, "C": False, "D": False}
    out = run(cari(Ctx(user=STAF), {"kata": "kirim faktur piutang"}))["hasil"]
    assert "tidak_diizinkan" in out["aksi"][0]
    out = run(cari(Ctx(), {"kata": "kunci periode", "portal": "Keuangan"}))["hasil"]
    kunci = [x for x in out["aksi"] if x["aksi"] == "post_rahaza_periods_id_lock"]
    assert kunci and "dilarang" in kunci[0]
    assert run(cari(Ctx(), {"kata": "zzzz qqqq"}))["hasil"]["jumlah"] == 0


# ═══ jalankan_aksi ═══════════════════════════════════════════════════════════
def _aksi(pred):
    return next(a for a in DATA if pred(a))


def test_put_mengirim_isian_lengkap_dan_bisa_dibalikkan(env):
    a = _aksi(lambda a: a["metode"] == "PUT" and a["golongan"] == "A" and a["balik"] and
              a["isian"].get("bentuk") == "bebas" and len(a["isian"].get("kunci") or []) >= 2)
    k1, k2 = a["isian"]["kunci"][:2]
    lama = {"id": "x1", "status": "aktif", k1: "lama-1", k2: "lama-2"}
    args = {"aksi": a["id"], "jalur": {p: "x1" for p in a["parameter_jalur"]}, "isian": {k1: "baru-1"}}
    r = tdk.rapikan_rencana(run(K().siapkan(Ctx(lama=lama), args)), args, K())
    assert [x["label"] for x in r["perubahan"]] == [au.label_isian(k1)]
    assert r["perubahan"][0]["sebelum"] == "lama-1" and r["perubahan"][0]["sesudah"] == "baru-1"
    ctx = Ctx(lama=lama)
    out = run(K().jalankan(ctx, args, r))
    assert ctx.tulis[0][3] == {k1: "baru-1", k2: "lama-2"}       # seperti formulir layar: nilai lama ikut
    langkah = out["pembatalan"]["langkah"][0]
    assert langkah["jenis"] == "kembalikan" and langkah["lama"][k1] == "lama-1"
    # balikkan: nilai sekarang = nilai baru → dikembalikan
    ctx3 = Ctx(lama={**lama, k1: "baru-1"})
    assert "dikembalikan" in run(K().batalkan(ctx3, out["pembatalan"]))["ringkas"]
    assert ctx3.tulis[0][3][k1] == "lama-1"
    # sudah diubah orang lain → tidak ditimpa
    with pytest.raises(ab.AlatError):
        run(K().batalkan(Ctx(lama={**lama, k1: "orang-lain"}), out["pembatalan"]))
    # tidak ada yang berubah → kartu ditolak
    with pytest.raises(ab.AlatError) as e:
        run(K().siapkan(Ctx(lama=lama), {**args, "isian": {k1: "lama-1"}}))
    assert "Tidak ada yang berubah" in e.value.pesan


def test_sidik_berubah_ditolak_saat_dijalankan(env):
    a = _aksi(lambda a: a["id"] == "post_rahaza_ar_invoices_id_send")
    args = {"aksi": a["id"], "jalur": {"iid": "INV-1"}}
    lama = {"id": "INV-1", "status": "draft", "invoice_number": "INV-1", "total": 1_250_000}
    r = tdk.rapikan_rencana(run(K().siapkan(Ctx(lama=lama), args)), args, K())
    assert r["risiko"] == "tinggi" and r["konfirmasi"]["teks"] == "1250000" and r["nominal"] == 1_250_000
    with pytest.raises(ab.AlatError) as e:
        run(K().jalankan(Ctx(lama={**lama, "status": "sent"}), args, r))
    assert e.value.status == 409


def test_kartu_kelompok_hasil_per_baris(env):
    a = _aksi(lambda a: a["id"] == "put_rahaza_overtime_id_approve")
    args = {"aksi": a["id"], "baris": [{"jalur": {p: f"ot-{i}" for p in a["parameter_jalur"]}} for i in range(3)]}
    r = tdk.rapikan_rencana(run(K().siapkan(Ctx(), args)), args, K())
    assert len(r["perubahan"]) == 3 and r["judul"].endswith("3 data")
    gagal = au._isi_jalur(a["jalur"], {p: "ot-1" for p in a["parameter_jalur"]})
    ctx = Ctx(gagal={gagal: (409, "Lembur sudah diputus.")})
    out = run(K().jalankan(ctx, args, r))
    assert "2 dari 3" in out["ringkas"] and "Lembur sudah diputus" in out["ringkas"]
    with pytest.raises(ab.AlatError):
        run(K().siapkan(Ctx(), {"aksi": a["id"], "baris": [{"jalur": {"x": "1"}}] * 51}))


def test_hapus_permanen_cv_gabungan_dan_golongan_mati_ditolak(env):
    hard = _aksi(lambda a: a["metode"] == "DELETE" and any(q["nama"] == "hard" for q in a["query"])
                 and not a.get("larangan"))
    args = {"aksi": hard["id"], "jalur": {p: "x1" for p in hard["parameter_jalur"]}, "query": {"hard": "true"}}
    with pytest.raises(ab.AlatError) as e:
        run(K().siapkan(Ctx(), args))
    assert e.value.status == 403 and "permanen" in e.value.pesan
    kirim = {"aksi": "post_rahaza_ar_invoices_id_send", "jalur": {"iid": "INV-1"}}
    with pytest.raises(ab.AlatError) as e:
        run(K().siapkan(Ctx(cv="ALL"), kirim))
    assert e.value.status == 400 and "CV" in e.value.pesan
    env.st["gol"] = {"A": True, "B": False, "C": False, "D": False}
    with pytest.raises(ab.AlatError) as e:
        run(K().siapkan(Ctx(user=STAF), kirim))
    assert e.value.status == 403 and "owner" in e.value.pesan
    with pytest.raises(ab.AlatError) as e:
        run(K().siapkan(Ctx(), {"aksi": "post_rahaza_periods_id_lock", "jalur": {"period_code": "2026-11"}}))
    assert e.value.status == 403
    with pytest.raises(ab.AlatError) as e:
        run(K().siapkan(Ctx(), {"aksi": "tidak_ada_aksinya"}))
    assert e.value.status == 404


def test_persetujuan_kedua_mengikuti_batas_nominal(env):
    kirim = {"aksi": "post_rahaza_ar_invoices_id_send", "jalur": {"iid": "INV-1"}}
    lama = {"id": "INV-1", "status": "draft", "total": 3_000_000}
    # owner tidak perlu persetujuan kedua
    assert "persetujuan_kedua" not in run(K().siapkan(Ctx(user=OWNER, lama=lama), kirim))
    env.st["atur"].update(batas_nominal_transaksi=5_000_000, batas_nominal_harian=10_000_000)
    assert "persetujuan_kedua" not in run(K().siapkan(Ctx(lama=lama), kirim))
    r = run(K().siapkan(Ctx(lama={**lama, "total": 6_000_000}), kirim))
    assert "per transaksi" in r["persetujuan_kedua"]["alasan"]
    env.st["hari_ini"] = 8_000_000
    assert "per hari" in run(K().siapkan(Ctx(lama=lama), kirim))["persetujuan_kedua"]["alasan"]


def test_alasan_kartu_diteruskan_ke_kolom_alasan(env):
    a = _aksi(lambda a: a["jenis"] == "aksi" and "reason" in (a["isian"].get("kunci") or []) and a["golongan"] == "A")
    args = {"aksi": a["id"], "jalur": {p: "x1" for p in a["parameter_jalur"]}}
    r = tdk.rapikan_rencana(run(K().siapkan(Ctx(), args)), args, K())
    ctx = Ctx(alasan="karena barang rusak saat diterima")
    run(K().jalankan(ctx, args, r))
    assert ctx.tulis[0][3]["reason"].startswith("karena barang rusak")


# ═══ Mesin kartu: risiko tinggi & persetujuan kedua ══════════════════════════
def test_label_isian_bahasa_indonesia():
    assert [au.label_isian(k) for k in ("code", "cash_account_id", "due_date", "unit_cost", "po_number", "is_active",
                                         "harga_coret")] == ["Kode", "Akun kas", "Tanggal jatuh tempo", "Biaya satuan",
                                                             "Nomor PO", "Aktif", "Harga coret"]


def test_konfirmasi_cocok():
    assert tdk.konfirmasi_cocok("Rp 1.250.000", "1250000")
    assert tdk.konfirmasi_cocok("1250000", "1250000")
    assert not tdk.konfirmasi_cocok("1.250.001", "1250000")
    assert tdk.konfirmasi_cocok(" inv-001 ", "INV-001")
    assert not tdk.konfirmasi_cocok("", "SETUJU")


def _kartu(db, **kw):
    doc = {"id": "k1", "user_id": STAF["id"], "pengguna": {"id": STAF["id"], "nama": STAF["name"]}, "sesi_id": "s1",
           "pesan_id": "p1", "tool_use_id": "tu1", "nama": "jalankan_aksi", "label": "Menjalankan aksi layar",
           "risiko": "tinggi", "golongan": "C", "nominal": 1_250_000, "cv": "DA", "keadaan": "menunggu",
           "args": {"aksi": "post_rahaza_ar_invoices_id_send", "jalur": {"iid": "INV-1"}},
           "rencana": {"judul": "Kirim faktur piutang: INV-1", "konfirmasi": {"teks": "1250000", "petunjuk": "Ketik"},
                       "persetujuan_kedua": {"perlu": True, "alasan": "batas nominal belum diisi"}, "perubahan": []},
           "kedaluwarsa_pada": "2099-01-01T00:00:00+00:00", "kunci_proses": None, "kunci_proses_at": None}
    doc.update(kw)
    db.ai_actions.docs.append(doc)
    return doc


def test_risiko_tinggi_wajib_alasan_dan_ketik_ulang(env, monkeypatch):
    db = fm.FakeDB()
    doc = _kartu(db)

    async def _atur():
        return {"aktif": True, "batas": 100, "batas_nominal_transaksi": 0, "batas_nominal_harian": 0}
    monkeypatch.setattr(tdk, "pengaturan", _atur)
    for alasan, k, pesan in (("", "1250000", tdk.LAYAR_ALASAN_TINGGI), ("alasan cukup panjang", "", tdk.LAYAR_KONFIRMASI),
                             ("alasan cukup panjang", "1.250.001", tdk.LAYAR_KONFIRMASI_SALAH)):
        with pytest.raises(tdk.GalatTindakan) as e:
            run(tdk.periksa_dan_kunci(db, STAF, doc, keputusan="setujui", ubahan=None, alasan=alasan,
                                      buat_ctx_baca=lambda d: None, konfirmasi=k))
        assert e.value.pesan == pesan
    p = run(tdk.periksa_dan_kunci(db, STAF, doc, keputusan="setujui", ubahan=None, alasan="alasan cukup panjang",
                                  buat_ctx_baca=lambda d: None, konfirmasi="Rp 1.250.000"))
    # staf: kartu uang di atas batas → menunggu persetujuan kedua, TIDAK dijalankan
    dipanggil = []

    class AlatPalsu:
        label = "x"
        bisa_dibalikkan = False

        @staticmethod
        async def jalankan(*_a):
            dipanggil.append(1)
            return {"ringkas": "x"}
    p.alat = AlatPalsu()
    ev = []
    hasil = run(tdk.laksanakan(db, p, SimpleNamespace(), user=STAF, kirim=ev.append))
    assert hasil["keadaan"] == "menunggu_kedua" and not dipanggil
    assert ev[-1]["keadaan"] == "menunggu_kedua"
    isi, err = tdk.teks_hasil(hasil)
    assert "BELUM dijalankan" in isi and not err
    assert db.ai_actions.docs[0]["keadaan"] == "menunggu_kedua"


def test_putuskan_kedua_owner_menjalankan_sebagai_pembuat(env, monkeypatch):
    db = fm.FakeDB()
    db.users.docs.extend([dict(OWNER), dict(STAF)])
    _kartu(db, keadaan="menunggu_kedua", alasan="pelanggan minta segera")

    async def _atur():
        return {"aktif": True, "batas": 100, "batas_nominal_transaksi": 0, "batas_nominal_harian": 0}
    monkeypatch.setattr(tdk, "pengaturan", _atur)
    terpakai = {}

    class AlatPalsu:
        label = "Menjalankan aksi layar"
        bisa_dibalikkan = False

        @staticmethod
        async def jalankan(ctx, args, rencana):
            terpakai.update(user=ctx.user["id"], alasan=ctx.alasan, args=args)
            return {"ringkas": "Kirim faktur piutang: berhasil."}
    monkeypatch.setattr(ab, "cari_tindakan", lambda _n: AlatPalsu())
    # hanya owner/superadmin, bukan pembuat, alasan wajib
    for u, alasan, kode in ((STAF, "alasan cukup panjang", 403), (ADMIN, "alasan cukup panjang", 403),
                            (OWNER, "pendek", 400)):
        with pytest.raises(tdk.GalatTindakan) as e:
            run(tdk.putuskan_kedua(db, u, "k1", keputusan="setujui", alasan=alasan))
        assert e.value.status == kode
    out = run(tdk.putuskan_kedua(db, OWNER, "k1", keputusan="setujui", alasan="sudah dicek dengan bank"))
    assert out["keadaan"] == "dijalankan" and terpakai["user"] == STAF["id"]
    assert "pelanggan minta segera" in terpakai["alasan"] and "sudah dicek" in terpakai["alasan"]
    d = db.ai_actions.docs[0]
    assert d["kedua_oleh"]["id"] == OWNER["id"] and d["tanggal_jalan"]
    kabar = run(tdk.kabar_dibalikkan(db, STAF["id"], "s1"))
    assert "persetujuan kedua" in kabar and "DIJALANKAN" in kabar
    assert run(tdk.kabar_dibalikkan(db, STAF["id"], "s1")) is None
    with pytest.raises(tdk.GalatTindakan):
        run(tdk.putuskan_kedua(db, OWNER, "k1", keputusan="setujui", alasan="sudah dicek dengan bank"))


def test_putuskan_kedua_tolak_dan_daftar_untuk_penyetuju(env, monkeypatch):
    db = fm.FakeDB()
    db.users.docs.extend([dict(OWNER), dict(STAF)])
    _kartu(db, keadaan="menunggu_kedua")
    out = run(tdk.putuskan_kedua(db, OWNER, "k1", keputusan="batal", alasan="nominal belum sesuai kontrak"))
    assert out["keadaan"] == "dibatalkan" and "Ditolak pada persetujuan kedua" in out["pesan"]
    _kartu(db, id="k2", tool_use_id="tu2", keadaan="menunggu_kedua")
    lihat = run(tdk.daftar(db, OWNER, status="menunggu_kedua"))
    assert [i["id"] for i in lihat["items"]] == ["k2"] and lihat["items"][0]["boleh_putuskan_kedua"]
    assert lihat["items"][0]["golongan"] == "C" and lihat["items"][0]["nominal"] == 1_250_000
    assert run(tdk.daftar(db, STAF, status="menunggu_kedua"))["items"][0]["boleh_putuskan_kedua"] is False


def test_rapikan_rencana_meneruskan_kunci_baru():
    a = K()
    r = tdk.rapikan_rencana({"judul": "J", "ringkas": "R", "perubahan": [{"label": "x", "sebelum": 1, "sesudah": 2}],
                             "risiko": "tinggi", "golongan": "C", "golongan_label": "Uang / buku besar",
                             "konfirmasi": {"teks": "1000", "petunjuk": "Ketik 1.000"}, "sidik": "ab" * 10,
                             "persetujuan_kedua": {"perlu": True, "alasan": "di atas batas"}, "nominal": 1000,
                             "tautan": {"menu": "fin-ar-hub", "label": "Buka"}}, {"aksi": "x"}, a)
    assert r["risiko"] == "tinggi" and r["golongan"] == "C" and r["konfirmasi"]["teks"] == "1000"
    assert r["persetujuan_kedua"]["perlu"] and r["sidik"] == "ab" * 10 and r["nominal"] == 1000
    r2 = tdk.rapikan_rencana({"judul": "J", "risiko": "aneh", "sidik": "BUKAN HEX", "nominal": -5}, {}, a)
    assert "risiko" not in r2 and "sidik" not in r2 and "nominal" not in r2
