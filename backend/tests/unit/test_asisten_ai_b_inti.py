"""Uji HERMETIK Asisten AI Tahap B (agen inti, 8 Nov 2026) — alat tindakan di balik kartu konfirmasi.

Alat tindakan TIRUAN didaftarkan DI DALAM uji ini saja (tidak pernah dikirim ke produksi). Klien Anthropic =
tiruan `core.asisten_ai.fake` (memeriksa: tool_choice paksa, prefill, tool_use tanpa tool_result, tanda tangan
thinking), Mongo = tiruan in-memory, endpoint aplikasi = klien HTTP tiruan yang mencatat permintaan.
Tidak ada panggilan API sungguhan.

Jalankan:  cd backend && python -m pytest tests/unit/test_asisten_ai_b_inti.py -n 0 -q
"""
import asyncio
import copy
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ai_fakes import FakeDB as TrackerDB, run  # noqa: E402
import _fake_mongo as fm  # noqa: E402

import ai_cost_tracker as t  # noqa: E402
from core import doc_lock  # noqa: E402
from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai import fake as fk  # noqa: E402
from core.asisten_ai import mesin  # noqa: E402
from core.asisten_ai import prompt as pr  # noqa: E402
from core.asisten_ai import simpan  # noqa: E402
from core.asisten_ai import tindakan as tdk  # noqa: E402

HARI_UJI = date(2026, 11, 8)
OWNER = {"id": "u-owner", "name": "Pemilik Uji", "role": "owner"}
SUPER = {"id": "u-super", "name": "Super Uji", "role": "superadmin"}
MGR = {"id": "u-mgr", "name": "Manajer Uji", "role": "manager_marketing"}
NAMA = "uji_tindakan_inti"
NAMA2 = "uji_tindakan_dua"

SKEMA = {"type": "object",
         "properties": {"periode": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
                        "target": {"type": "integer", "minimum": 0},
                        "catatan": {"type": "string"}},
         "required": ["periode", "target"], "additionalProperties": False}
CATAT = {"siapkan": [], "jalankan": [], "batalkan": []}


# ── perlengkapan ────────────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class HttpUji:
    """Pengganti klien ASGI: endpoint uji `/api/uji/nilai` (GET baca, POST pasang, PUT pulihkan)."""

    def __init__(self, gagal_post=None):
        self.calls = []
        self.nilai = 120_000_000
        self.gagal_post = gagal_post

    async def request(self, method, path, **kw):
        self.calls.append((method, path, kw))
        if path == "/api/uji/nilai":
            if method == "GET":
                return FakeResp(200, {"nilai": self.nilai})
            if method == "POST":
                if self.gagal_post:
                    return FakeResp(*self.gagal_post)
                lama, self.nilai = self.nilai, kw["json"]["target"]
                return FakeResp(200, {"id": "nilai-1", "lama": lama})
            if method == "PUT":
                self.nilai = kw["json"]["nilai"]
                return FakeResp(200, {"ok": True})
        return FakeResp(200, {"ok": True})

    async def aclose(self):
        pass

    def tulis(self):
        return [c for c in self.calls if c[0] != "GET"]


def _rp(v):
    return f"Rp {int(v):,}".replace(",", ".")


async def _siapkan(ctx, args):
    CATAT["siapkan"].append(copy.deepcopy(args))
    if args.get("catatan") == "tolak":
        raise ab.AlatError(409, "Periode ini sudah dikunci, nilai tidak bisa diubah.")
    data = await ctx.api("GET", "/api/uji/nilai")
    return {"judul": f"Pasang nilai uji {args['periode']}", "ringkas": "Satu nilai uji diubah.",
            "perubahan": [{"label": "Nilai uji", "sebelum": _rp(data["nilai"]), "sesudah": _rp(args["target"])},
                          {"label": "Catatan", "sebelum": None, "sesudah": args.get("catatan")}],
            "catatan": ["Periode masih terbuka."], "peringatan": [],
            "ubah": [{"kunci": "target", "label": "Target", "jenis": "rupiah", "nilai": args["target"]},
                     {"kunci": "tidak.ada", "label": "Hilang", "jenis": "teks"},
                     {"kunci": "periode", "label": "Periode", "jenis": "bentuk_aneh"}]}


async def _jalankan(ctx, args, rencana):
    CATAT["jalankan"].append(copy.deepcopy(args))
    out = await ctx.api("POST", "/api/uji/nilai", json={"target": args["target"]})
    return {"ringkas": f"Nilai uji {args['periode']} terpasang {_rp(args['target'])}.", "hasil": {"id": out["id"]},
            "pembatalan": {"nilai": out["lama"]}}


async def _batalkan(ctx, pembatalan):
    CATAT["batalkan"].append(copy.deepcopy(pembatalan))
    await ctx.api("PUT", "/api/uji/nilai", json={"nilai": pembatalan["nilai"]})
    return {"ringkas": "Nilai uji lama dipulihkan."}


def daftar_dummy(nama=NAMA, *, risiko="rendah", bisa_balik=True, label="Memasang nilai uji"):
    ns = {"siapkan": staticmethod(_siapkan), "jalankan": staticmethod(_jalankan)}
    if bisa_balik:
        ns["batalkan"] = staticmethod(_batalkan)
    cls = type(f"Dummy_{nama}", (), ns)
    return ab.tindakan(name=nama, label=label,
                       description="Tindakan UJI: memasang nilai uji lewat endpoint uji (hanya untuk uji unit).",
                       input_schema=SKEMA, domain="umum", risiko=risiko, menu="asisten-ai")(cls)


@pytest.fixture
def dummy():
    """Daftarkan alat tindakan tiruan; nama yang sudah dipakai modul asli dipulihkan sesudah uji."""
    ab.muat_semua_alat()
    simpanan = {}

    def _daftar(nama=NAMA, **kw):
        if nama not in simpanan:
            simpanan[nama] = ab._DAFTAR.pop(nama, None)
        return daftar_dummy(nama, **kw)
    for k in CATAT:
        CATAT[k].clear()
    yield _daftar
    for nama, lama in simpanan.items():
        ab._DAFTAR.pop(nama, None)
        if lama is not None:
            ab._DAFTAR[nama] = lama


def skrip_uji(k):
    """Skrip tiruan: alat baca + ui + tindakan dalam SATU giliran; sesudah diputuskan → teks dari hasilnya."""
    q = (k.pertanyaan or "").lower()
    nama_list = [NAMA, NAMA2] if "dua kartu" in q else [NAMA]
    if k.tool_choice == "none":
        return [fk._teks("Ringkasan akhir.")], "end_turn", {}
    if not any(x in q for x in ("nilai", "kartu", "gagal siapkan", "isian salah")):
        return [fk._pikir("Jawab biasa."), fk._teks("Jawaban biasa tanpa tindakan.")], "end_turn", {}
    if not any(k.sudah(n) for n in nama_list):
        args = {"periode": "2026-12", "target": 135_000_000}
        if "gagal siapkan" in q:
            args["catatan"] = "tolak"
        if "isian salah" in q:
            args = {"periode": "Desember"}
        blok = [fk._pikir("Siapkan kartu uji."), fk._teks("Saya siapkan kartunya."),
                fk._alat("tanggal_dan_periode", {}),
                fk._alat("tampilkan_tabel", {"judul": "Skenario uji", "kolom": ["Toko", "Target"],
                                             "baris": [["Toko A", 135_000_000]]})]
        blok += [fk._alat(n, dict(args)) for n in nama_list]
        return blok, "tool_use", {}
    hasil = [k.terakhir(n) for n in nama_list]
    return [fk._teks("Hasil kartu: " + " | ".join(str(h[2]) for h in hasil if h))], "end_turn", {}


@pytest.fixture
def env(monkeypatch):
    tdb = TrackerDB()
    monkeypatch.setattr(t, "get_db", lambda: tdb)
    monkeypatch.setattr(t, "sdk_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-uji-hermetik-0000")
    monkeypatch.delenv("ASISTEN_AI_FAKE", raising=False)
    t.invalidate_api_key_cache()
    t.invalidate_ai_settings_cache()
    mesin._FALLBACK["aktif"] = True
    mesin._AKTIF.clear()
    yield {"tdb": tdb, "db": fm.FakeDB(), "fake": fk.FakeAsyncAnthropic(skrip=skrip_uji, jeda=0), "http": HttpUji()}
    t.invalidate_api_key_cache()
    t.invalidate_ai_settings_cache()
    mesin._AKTIF.clear()


def _setel(env, **kw):
    env["tdb"].find_one_map["ai_config"] = {"id": "global", **kw}
    t.invalidate_ai_settings_cache()


def _sse(chunks):
    out = []
    for c in chunks:
        c = c if isinstance(c, str) else c.decode()
        m = re.match(r"event: (\w+)\ndata: (.*)\n\n$", c, re.S)
        assert m, c
        out.append((m.group(1), json.loads(m.group(2))))
    return out


async def _sesi_baru(env, user=OWNER):
    return (await simpan.buat_sesi(env["db"], user["id"]))["id"]


async def _kirim(env, user, sid, teks, *, klien=None):
    db = env["db"]
    sesi = await simpan.ambil_sesi(db, user["id"], sid)
    jalan, galat = await mesin.siapkan_jalan(db=db, user=user, sesi=sesi, teks=teks, cv="DA", periode="2026-11",
                                             today=HARI_UJI, token="tok-uji", klien=klien or env["fake"],
                                             klien_api=lambda: env["http"])
    if galat:
        return None, [("galat", galat)]
    task = mesin.mulai(jalan)
    chunks = [c async for c in mesin.aliran_sse(jalan)]
    await task
    return jalan, _sse(chunks)


async def _putus(env, user, tid, keputusan, *, ubahan=None, alasan="", klien=None):
    jalan = await mesin.siapkan_putusan(db=env["db"], user=user, tindakan_id=tid, keputusan=keputusan, ubahan=ubahan,
                                        alasan=alasan, today=HARI_UJI, token="tok-uji", klien=klien or env["fake"],
                                        klien_api=lambda: env["http"])
    task = mesin.mulai(jalan)
    chunks = [c async for c in mesin.aliran_sse(jalan)]
    await task
    return _sse(chunks)


def _kartu(ev):
    return [d for n, d in ev if n == "tindakan"]


def _aksi(env):
    return env["db"].ai_actions.docs


def _pesan(env, sid):
    return sorted([d for d in env["db"].ai_chat_messages.docs if d["sesi_id"] == sid], key=lambda d: d["urutan"])


async def _kartu_baru(env, teks="pasang nilai uji", user=OWNER):
    sid = await _sesi_baru(env, user)
    _j, ev = await _kirim(env, user, sid, teks)
    return sid, ev


def _cek_append_only(calls):
    for a, b in zip(calls, calls[1:]):
        pa, pb = a["messages"], b["messages"]
        assert json.dumps(pb[:len(pa)], ensure_ascii=False) == json.dumps(pa, ensure_ascii=False)


# ═══ Kerangka: dekorator, registri, ctx ══════════════════════════════════════
def test_dekorator_tindakan_registri_dan_deskripsi(dummy):
    cls = dummy()
    a = ab.cari_tindakan(NAMA)
    assert a is not None and a.adalah_tindakan and a.kelas is cls and cls._alat is a
    assert a.kind == "action" and a.risiko == "rendah" and a.menu == "asisten-ai" and a.bisa_dibalikkan
    assert ab.cari_alat(NAMA) is None  # bukan alat baca/ui
    tanpa = [x["name"] for x in ab.tools_untuk_api() if "input_schema" in x]
    dengan = ab.tools_untuk_api(tindakan=True)
    nama_dengan = [x["name"] for x in dengan if "input_schema" in x]
    assert NAMA not in tanpa and NAMA in nama_dengan and nama_dengan == sorted(nama_dengan)
    d = next(x for x in dengan if x.get("name") == NAMA)
    assert d["description"].startswith("[Tindakan]") and d["eager_input_streaming"] is True
    assert json.dumps(dengan) == json.dumps(ab.tools_untuk_api(tindakan=True))  # deterministik
    # risiko menengah: awalan alasan wajib; tanpa batalkan: tidak bisa dibalikkan
    dummy(NAMA2, risiko="menengah", bisa_balik=False)
    a2 = ab.cari_tindakan(NAMA2)
    assert not a2.bisa_dibalikkan and ab.AWALAN_MENENGAH in a2.untuk_api()["description"]
    # @alat(kind="action") biasa (tanpa siapkan/jalankan) TIDAK pernah dikirim ke model
    @ab.alat(name="uji_aksi_polos", kind="action", label="x", description="x", input_schema={"type": "object"})
    async def _polos(ctx, args):
        return {}
    try:
        assert "uji_aksi_polos" not in [x.get("name") for x in ab.tools_untuk_api(tindakan=True)]
        assert ab.cari_tindakan("uji_aksi_polos") is None
    finally:
        ab._DAFTAR.pop("uji_aksi_polos", None)
    with pytest.raises(ValueError):
        ab.tindakan(name="uji_salah_risiko", label="x", description="x", input_schema={"type": "object"},
                    risiko="tinggi")
    with pytest.raises(TypeError):
        ab.tindakan(name="uji_tanpa_jalankan", label="x", description="x",
                    input_schema={"type": "object"})(type("X", (), {"siapkan": staticmethod(_siapkan)}))
    with pytest.raises(ValueError):
        ab.tindakan(name="uji_menu_salah", label="x", description="x", input_schema={"type": "object"},
                    menu="Menu Salah")
    # domain tak dikenal tidak mematikan modul: dipakai "umum"
    c3 = ab.tindakan(name="uji_domain_baru", label="x", description="x", input_schema={"type": "object"},
                     domain="pemasaran")(type("Y", (), {"siapkan": staticmethod(_siapkan),
                                                        "jalankan": staticmethod(_jalankan)}))
    try:
        assert c3._alat.domain == "umum"
    finally:
        ab._DAFTAR.pop("uji_domain_baru", None)


def test_ctx_baca_saja_dan_header_via_asisten():
    http = HttpUji()
    baca = ab.AlatContext(user=OWNER, cv="DA", today=HARI_UJI, token="tok", klien_api=lambda: http, baca_saja=True)
    with pytest.raises(ab.AlatError) as ei:
        run(baca.api("POST", "/api/uji/nilai", json={"target": 1}))
    assert ei.value.status == 403 and http.calls == []
    run(baca.api("GET", "/api/uji/nilai"))
    assert "X-Via" not in http.calls[-1][2]["headers"]
    siap = baca.untuk_tindakan("akt-1", tulis=False)
    with pytest.raises(ab.AlatError):
        run(siap.api("PUT", "/api/uji/nilai", json={"nilai": 1}))
    tulis = baca.untuk_tindakan("akt-1", tulis=True)
    run(tulis.api("POST", "/api/uji/nilai", json={"target": 5}, headers={"X-Via": "palsu", "X-Lain": "1"}))
    h = http.calls[-1][2]["headers"]
    assert h["X-Via"] == "asisten-ai" and h["X-Asisten-Tindakan"] == "akt-1" and h["X-Lain"] == "1"
    assert h["Authorization"] == "Bearer tok" and h["X-CV"] == "DA"
    run(tulis.api("GET", "/api/uji/nilai"))
    assert "X-Via" not in http.calls[-1][2]["headers"]  # header jejak hanya pada tulisan
    # konteks lama (Tahap A, tanpa baca_saja) tetap seperti dulu
    lama = ab.AlatContext(user=OWNER, cv="DA", today=HARI_UJI, token="tok", klien_api=lambda: http)
    run(lama.api("POST", "/api/uji/lain", json={}))
    assert "X-Via" not in http.calls[-1][2]["headers"]


def test_ctx_header_via_lewat_asgi_sungguhan():
    pytest.importorskip("httpx")
    from fastapi import FastAPI, Request
    app = FastAPI()
    dilihat = []

    @app.post("/api/uji/gema")
    async def gema(request: Request):
        dilihat.append({k: request.headers.get(k) for k in ("x-via", "x-asisten-tindakan", "authorization")})
        return {"ok": True}

    async def _jalan():
        ctx = ab.AlatContext(user=OWNER, cv="DA", today=HARI_UJI, token="tok-asgi", app=app, baca_saja=True)
        c = ctx.untuk_tindakan("akt-9", tulis=True)
        try:
            await c.api("POST", "/api/uji/gema", json={})
        finally:
            await c.tutup()
    run(_jalan())
    assert dilihat == [{"x-via": "asisten-ai", "x-asisten-tindakan": "akt-9", "authorization": "Bearer tok-asgi"}]


def test_rencana_dirapikan_dan_dibatasi(dummy):
    dummy()
    a = ab.cari_tindakan(NAMA)
    args = {"periode": "2026-12", "target": 5}
    r = tdk.rapikan_rencana({"perubahan": [{"label": "A", "sebelum": "", "sesudah": 1500000}],
                             "ubah": [{"kunci": "target", "label": "Target", "jenis": "rupiah"},
                                      {"kunci": "periode", "jenis": "pilihan", "pilihan": []}]}, args, a)
    assert r["judul"] == a.label and r["perubahan"] == [{"label": "A", "sebelum": "—", "sesudah": "1.500.000"}]
    assert [u["kunci"] for u in r["ubah"]] == ["target"] and r["ubah"][0]["nilai"] == 5
    assert r["tautan"] == {"label": "Buka layar terkait", "menu": "asisten-ai"}
    with pytest.raises(ab.AlatError) as ei:
        tdk.rapikan_rencana({"perubahan": [{"label": "x" * 100, "sebelum": "y" * 300, "sesudah": "z" * 300}] * 40},
                            args, a)
    assert "terlalu besar" in ei.value.pesan
    with pytest.raises(ab.AlatError):
        tdk.rapikan_rencana(["bukan", "dict"], args, a)


# ═══ Siapkan → kartu, loop berhenti ═════════════════════════════════════════
def test_kartu_disiapkan_giliran_berhenti_tanpa_tulis(env, dummy):
    dummy()
    sid, ev = run(_kartu_baru(env))
    nama = [n for n, _ in ev]
    assert nama[0] == "mulai" and nama[-1] == "selesai" and "galat" not in nama
    (k,) = _kartu(ev)
    assert k["keadaan"] == "menunggu" and k["nama"] == NAMA and k["risiko"] == "rendah"
    assert k["rencana"]["judul"] == "Pasang nilai uji 2026-12" and k["rencana"]["perubahan"][0]["sebelum"] == "Rp 120.000.000"
    assert [u["kunci"] for u in k["rencana"]["ubah"]] == ["target"]  # isian ubah yang tidak sah dibuang
    assert nama.index("tabel") < nama.index("tindakan")
    assert ev[-1][1]["status"] == "menunggu_konfirmasi" and ev[-1][1]["tindakan_menunggu"] == [k["id"]]
    # TIDAK ada tulisan sebelum klik; hanya GET dari siapkan
    assert env["http"].tulis() == [] and [c[:2] for c in env["http"].calls] == [("GET", "/api/uji/nilai")]
    (d,) = _aksi(env)
    assert d["keadaan"] == "menunggu" and d["sesi_id"] == sid and d["pengguna"] == {"id": "u-owner", "nama": "Pemilik Uji"}
    dibuat = datetime.fromisoformat(d["dibuat"])
    assert datetime.fromisoformat(d["kedaluwarsa_pada"]) - dibuat == timedelta(hours=24)
    pa = _pesan(env, sid)[-1]
    assert pa["status"] == "menunggu_konfirmasi" and pa["tunda"]["keadaan"] == "menunggu"
    ekor = pa["api"][-1]
    ids = [b["id"] for b in ekor["content"] if b["type"] == "tool_use"]
    assert ekor["role"] == "assistant" and pa["tunda"]["urutan"] == ids and len(ids) == 3
    assert [b["tool_use_id"] for b in pa["tunda"]["hasil"]] == ids[:2] and d["tool_use_id"] == ids[2]
    assert len(env["fake"].panggilan) == 1  # loop berhenti, tidak ada panggilan kedua
    assert [b["jenis"] for b in pa["blok"]].count("tindakan") == 1
    # daftar sesi + tampilan riwayat membaca keadaan terkini
    assert run(tdk.sesi_menunggu(env["db"], OWNER["id"])) == {sid}
    view = run(simpan.ambil_pesan(env["db"], OWNER["id"], sid))
    assert run(tdk.segarkan_pesan(env["db"], OWNER["id"], sid, view)) is True
    bt = next(b for b in view[-1]["blok"] if b["jenis"] == "tindakan")
    assert bt["keadaan"] == "menunggu" and bt["bisa_dibalikkan"] is False


def test_siapkan_gagal_dan_isian_salah_kembali_ke_model(env, dummy):
    dummy()
    for teks, kata in (("gagal siapkan nilai", "sudah dikunci"), ("isian salah", "tidak sah")):
        sid, ev = run(_kartu_baru(env, teks))
        assert _kartu(ev) == [] and ev[-1][0] == "selesai" and "status" not in ev[-1][1]
        teks_akhir = "".join(d["delta"] for n, d in ev if n == "teks")
        assert kata in teks_akhir
        gagal = [d for n, d in ev if n == "alat" and d["nama"] == NAMA and d["keadaan"] == "gagal"]
        assert len(gagal) == 1
    assert _aksi(env) == [] and env["http"].tulis() == []


# ═══ Setujui → jalan sekali → lanjut ════════════════════════════════════════
def test_setujui_menjalankan_sekali_lalu_lanjut_riwayat_sah(env, dummy):
    dummy()

    async def _uji():
        sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        ev2 = await _putus(env, OWNER, tid, "setujui")
        # klik kedua / coba ulang: 409, tidak berjalan dua kali
        with pytest.raises(tdk.GalatTindakan) as e2:
            await _putus(env, OWNER, tid, "setujui")
        return sid, tid, ev2, e2.value
    sid, tid, ev, e2 = run(_uji())
    nama = [n for n, _ in ev]
    st = [d for n, d in ev if n == "tindakan_status"]
    assert [s["keadaan"] for s in st] == ["disetujui", "dijalankan"] and "terpasang Rp 135.000.000" in st[1]["ringkas"]
    assert nama.index("tindakan_status") < nama.index("mulai") and nama[-1] == "selesai" and "galat" not in nama
    assert "status" not in ev[-1][1]
    teks = "".join(d["delta"] for n, d in ev if n == "teks")
    assert teks.startswith("Hasil kartu: Disetujui dan dijalankan: Nilai uji 2026-12 terpasang")
    tulis = env["http"].tulis()
    assert len(tulis) == 1 and tulis[0][:2] == ("POST", "/api/uji/nilai") and len(CATAT["jalankan"]) == 1
    assert tulis[0][2]["headers"]["X-Via"] == "asisten-ai" and tulis[0][2]["headers"]["X-Asisten-Tindakan"] == tid
    assert e2.status == 409 and "sudah disetujui" in e2.pesan
    (d,) = _aksi(env)
    assert d["keadaan"] == "dijalankan" and d["hasil"] == {"id": "nilai-1"} and d["pembatalan"] == {"nilai": 120_000_000}
    assert d["bisa_dibalikkan"] is True and d["kunci_proses"] is None and d["diputuskan_oleh"]["id"] == "u-owner"
    assert d["sebelum"][0] == {"label": "Nilai uji", "nilai": "Rp 120.000.000"}
    assert run(tdk.jumlah_hari_ini(env["db"], OWNER["id"])) == 1
    # riwayat: permintaan lanjutan = permintaan pertama + giliran asisten + tool_result (append-only, sah)
    c1, c2 = env["fake"].panggilan
    _cek_append_only([c1, c2])
    u = c2["messages"][-1]
    assert u["role"] == "user" and [b["type"] for b in u["content"]] == ["tool_result"] * 3
    asst = c2["messages"][-2]
    assert [b["tool_use_id"] for b in u["content"]] == [b["id"] for b in asst["content"] if b["type"] == "tool_use"]
    assert u["content"][2]["content"].startswith("Disetujui dan dijalankan:") and "is_error" not in u["content"][2]
    assert asst["content"][0]["signature"] == fk.tanda_tangan(asst["content"][0]["thinking"])
    ps = _pesan(env, sid)
    assert [p["peran"] for p in ps] == ["user", "asisten", "asisten"]
    assert ps[1]["status"] == "selesai" and ps[1]["tunda"]["keadaan"] == "selesai" and ps[1]["tunda"]["ditutup"] == "putusan"
    assert ps[2]["lanjutan_dari"] == ps[1]["id"] and ps[2]["api"][0] == u and ps[2]["status"] == "selesai"
    hist = run(simpan.muat_riwayat_api(env["db"], OWNER["id"], sid))
    assert json.dumps(hist[:len(c2["messages"])]) == json.dumps(c2["messages"])
    # pesan berikutnya: riwayat valid diputar ulang (tiruan memeriksa setiap tool_use terjawab)
    _j, ev3 = run(_kirim(env, OWNER, sid, "halo lagi"))
    assert ev3[-1][0] == "selesai" and not any(n == "galat" for n, _ in ev3)
    _cek_append_only(env["fake"].panggilan)
    # GET sesi: kartu = keadaan terkini
    view = run(simpan.ambil_pesan(env["db"], OWNER["id"], sid))
    assert run(tdk.segarkan_pesan(env["db"], OWNER["id"], sid, view)) is False
    bt = next(b for p in view for b in p["blok"] if b["jenis"] == "tindakan")
    assert bt["keadaan"] == "dijalankan" and bt["bisa_dibalikkan"] is True and "terpasang" in bt["ringkas"]


def test_klik_ganda_bersamaan_hanya_satu_lolos(env, dummy):
    dummy()

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        j1 = await mesin.siapkan_putusan(db=env["db"], user=OWNER, tindakan_id=tid, keputusan="setujui",
                                         today=HARI_UJI, token="t", klien=env["fake"], klien_api=lambda: env["http"])
        with pytest.raises(tdk.GalatTindakan) as e:
            await mesin.siapkan_putusan(db=env["db"], user=OWNER, tindakan_id=tid, keputusan="setujui",
                                        today=HARI_UJI, token="t", klien=env["fake"], klien_api=lambda: env["http"])
        # klaim kedua di tingkat dokumen (proses lain / sesi lain) juga ditolak
        doc = await tdk.ambil(env["db"], tid)
        with pytest.raises(tdk.GalatTindakan) as e_kunci:
            await tdk.periksa_dan_kunci(env["db"], OWNER, doc, keputusan="setujui", ubahan=None, alasan="",
                                        buat_ctx_baca=lambda d: None)
        task = mesin.mulai(j1)
        [c async for c in mesin.aliran_sse(j1)]
        await task
        return e.value, e_kunci.value
    e, e_kunci = run(_uji())
    assert e.status == 409 and "masih berjalan" in e.pesan
    assert e_kunci.status == 409 and len(env["http"].tulis()) == 1 and len(CATAT["jalankan"]) == 1


def test_ubahan_kartu_menjalankan_ulang_siapkan(env, dummy):
    dummy()

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        galat = []
        for ub in ({"periode": "2027-01"}, {"target": "bukan angka"}, {"target": -5}):
            try:
                await _putus(env, OWNER, tid, "setujui", ubahan=ub)
            except tdk.GalatTindakan as e:
                galat.append((e.status, e.pesan))
        doc = await tdk.ambil(env["db"], tid)
        assert doc["keadaan"] == "menunggu" and doc["kunci_proses"] is None  # kunci dilepas sesudah galat
        ev2 = await _putus(env, OWNER, tid, "setujui", ubahan={"target": "Rp 150.000.000"})
        return tid, galat, ev2
    tid, galat, ev = run(_uji())
    assert [g[0] for g in galat] == [400, 400, 400]
    assert "tidak boleh diubah" in galat[0][1] and "angka" in galat[1][1] and "negatif" in galat[2][1]
    assert [a["target"] for a in CATAT["siapkan"]] == [135_000_000, 150_000_000]  # siapkan diulang sekali
    assert CATAT["jalankan"] == [{"periode": "2026-12", "target": 150_000_000}]
    (d,) = _aksi(env)
    assert d["args"]["target"] == 150_000_000 and d["args_awal"]["target"] == 135_000_000
    assert d["ubahan"] == {"target": 150_000_000} and d["rencana"]["perubahan"][0]["sesudah"] == "Rp 150.000.000"
    hasil = env["fake"].panggilan[-1]["messages"][-1]["content"][2]["content"]
    assert "Pengguna mengubah isian di kartu sebelum menyetujui: Target = 150.000.000" in hasil


def test_ubahan_yang_ditolak_siapkan_ulang(env, dummy):
    dummy()

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        doc = await tdk.ambil(env["db"], tid)
        doc["rencana"]["ubah"].append({"kunci": "catatan", "label": "Catatan", "jenis": "teks", "nilai": ""})
        env["db"].ai_actions.docs[0]["rencana"] = doc["rencana"]
        env["db"].ai_actions.docs[0]["args"]["catatan"] = "awal"
        with pytest.raises(tdk.GalatTindakan) as e:
            await _putus(env, OWNER, tid, "setujui", ubahan={"catatan": "tolak"})
        return tid, e.value
    tid, e = run(_uji())
    assert e.status == 400 and "sudah dikunci" in e.pesan
    d = env["db"].ai_actions.docs[0]
    assert d["keadaan"] == "menunggu" and d["kunci_proses"] is None and env["http"].tulis() == []


def test_jalankan_gagal_dicatat_dan_dikabarkan(env, dummy):
    dummy()
    env["http"].gagal_post = (403, {"detail": "Hanya PIC toko yang boleh mengubah target."})

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        return await _putus(env, OWNER, tid, "setujui")
    ev = run(_uji())
    st = [d for n, d in ev if n == "tindakan_status"]
    assert [s["keadaan"] for s in st] == ["disetujui", "gagal"] and "tidak punya akses" in st[1]["pesan"]
    hasil = env["fake"].panggilan[-1]["messages"][-1]["content"][2]
    assert hasil["is_error"] is True and hasil["content"].startswith("Gagal: Akun ini tidak punya akses")
    (d,) = _aksi(env)
    assert d["keadaan"] == "gagal" and d["kunci_proses"] is None and not d.get("bisa_dibalikkan")
    assert run(tdk.jumlah_hari_ini(env["db"], OWNER["id"])) == 0  # gagal tidak dihitung ke batas


# ═══ Batal, pesan baru, 24 jam ══════════════════════════════════════════════
def test_batal_tanpa_tulis_lalu_lanjut(env, dummy):
    dummy()

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        return await _putus(env, OWNER, tid, "batal", alasan="Belum perlu")
    ev = run(_uji())
    st = [d for n, d in ev if n == "tindakan_status"]
    assert [s["keadaan"] for s in st] == ["dibatalkan"]
    assert ev[-1][0] == "selesai" and "Dibatalkan pengguna" in "".join(d["delta"] for n, d in ev if n == "teks")
    assert env["http"].tulis() == [] and CATAT["jalankan"] == []
    (d,) = _aksi(env)
    assert d["keadaan"] == "dibatalkan" and d["alasan"] == "Belum perlu"
    hasil = env["fake"].panggilan[-1]["messages"][-1]["content"][2]
    assert hasil["content"] == tdk.HASIL_DIBATALKAN and "is_error" not in hasil


def test_pesan_baru_mengedaluwarsakan_kartu(env, dummy):
    dummy()

    async def _uji():
        sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        _j, ev2 = await _kirim(env, OWNER, sid, "lupakan, apa kabar?")
        with pytest.raises(tdk.GalatTindakan) as e:
            await _putus(env, OWNER, tid, "setujui")
        return sid, tid, ev2, e.value
    sid, tid, ev, e = run(_uji())
    assert ev[0][0] == "mulai" and ev[1] == ("tindakan_status", {"id": tid, "keadaan": "kedaluwarsa",
                                                                 "pesan": tdk.PESAN_KEDALUWARSA_PESAN})
    assert ev[-1][0] == "selesai" and not any(n == "galat" for n, _ in ev)
    c2 = env["fake"].panggilan[1]
    _cek_append_only(env["fake"].panggilan)
    u = c2["messages"][-1]["content"]
    assert [b["type"] for b in u] == ["tool_result"] * 3 + ["text", "text"]
    assert u[2]["content"] == tdk.HASIL_KEDALUWARSA and u[3]["text"].startswith("<konteks_sistem>")
    assert u[4]["text"] == "lupakan, apa kabar?"
    assert e.status == 409 and "kedaluwarsa" in e.pesan
    assert _aksi(env)[0]["keadaan"] == "kedaluwarsa" and env["http"].tulis() == []
    ps = _pesan(env, sid)
    assert ps[1]["tunda"]["keadaan"] == "selesai" and ps[1]["tunda"]["ditutup"] == "pesan_baru"
    assert run(tdk.sesi_menunggu(env["db"], OWNER["id"])) == set()


def test_kedaluwarsa_24_jam_dan_proses_basi(env, dummy):
    dummy()

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        lalu = datetime.now(timezone.utc) - timedelta(hours=25)
        env["db"].ai_actions.docs[0]["kedaluwarsa_pada"] = (lalu + timedelta(hours=24)).isoformat()
        with pytest.raises(tdk.GalatTindakan) as e:
            await _putus(env, OWNER, tid, "setujui")
        daftar = await tdk.daftar(env["db"], OWNER)
        return e.value, daftar
    e, daftar = run(_uji())
    assert e.status == 409 and "kedaluwarsa" in e.pesan and daftar["items"][0]["keadaan"] == "kedaluwarsa"
    assert daftar["items"][0]["ringkas"] == tdk.PESAN_KEDALUWARSA_WAKTU
    # proses mati di tengah `jalankan` (kunci basi) → gagal "tidak pasti", tidak pernah dijalankan ulang
    env["db"].ai_actions.docs.append({"id": "basi-1", "user_id": OWNER["id"], "sesi_id": "s", "keadaan": "disetujui",
                                      "kunci_proses": "tok", "kunci_proses_at": datetime.now(timezone.utc) - timedelta(hours=1)})
    d = run(tdk.ambil(env["db"], "basi-1"))
    assert d["keadaan"] == "gagal" and d["pesan"] == tdk.PESAN_PROSES_TERHENTI and d["kunci_proses"] is None


def test_kartu_yatim_saat_dihentikan_dikedaluwarsakan(env):
    env["db"].ai_actions.docs.append({"id": "y1", "pesan_id": "p1", "keadaan": "menunggu", "kunci_proses": None})
    run(tdk.kedaluwarsakan_pesan(env["db"], "p1"))
    assert env["db"].ai_actions.docs[0]["keadaan"] == "kedaluwarsa"


# ═══ Batas harian, saklar, peran ════════════════════════════════════════════
def test_batas_harian_saat_siapkan_dan_saat_setujui(env, dummy):
    dummy()
    _setel(env, asisten_batas_tindakan_harian=1)

    async def _uji():
        sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        # kartu kedua dibuat SEBELUM yang pertama dijalankan, lalu yang pertama dijalankan
        sid2, ev2 = await _kartu_baru(env)
        tid2 = _kartu(ev2)[0]["id"]
        await _putus(env, OWNER, tid, "setujui")
        with pytest.raises(tdk.GalatTindakan) as e:
            await _putus(env, OWNER, tid2, "setujui")
        sid3, ev3 = await _kartu_baru(env)
        return e.value, ev3
    e, ev3 = run(_uji())
    assert e.status == 409 and "Batas tindakan" in e.pesan and "1 tindakan" in e.pesan
    assert _kartu(ev3) == [] and "Batas tindakan Asisten AI" in "".join(d["delta"] for n, d in ev3 if n == "teks")
    assert len(CATAT["jalankan"]) == 1


def test_saklar_mati_alat_tidak_ditawarkan_dan_setujui_ditolak(env, dummy, monkeypatch):
    dummy()

    async def _uji():
        _sid, ev = await _kartu_baru(env)          # kartu dibuat saat saklar masih menyala
        tid = _kartu(ev)[0]["id"]
        _setel(env, asisten_tindakan_aktif=False)
        with pytest.raises(tdk.GalatTindakan) as e:
            await _putus(env, OWNER, tid, "setujui")
        n0 = len(env["fake"].panggilan)
        _sid2, ev2 = await _kartu_baru(env)        # model tetap mencoba memanggilnya
        tools2 = env["fake"].panggilan[n0]["tools"]
        ev_batal = await _putus(env, OWNER, tid, "batal")
        st = await mesin.status_siap()
        return e.value, ev2, tools2, ev_batal, st
    e, ev2, tools2, ev_batal, st = run(_uji())
    assert e.status == 409 and "dimatikan admin" in e.pesan
    assert NAMA not in [x.get("name") for x in tools2]
    assert _kartu(ev2) == [] and "dimatikan admin" in "".join(d["delta"] for n, d in ev2 if n == "teks")
    assert [d["keadaan"] for n, d in ev_batal if n == "tindakan_status"] == ["dibatalkan"]  # batal tetap boleh
    assert st["tindakan_aktif"] is False and env["http"].tulis() == []


def test_hanya_pemilik_sesi_boleh_memutuskan(env, dummy):
    dummy()

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        hasil = []
        for u in (SUPER, MGR):
            try:
                await _putus(env, u, tid, "setujui")
            except tdk.GalatTindakan as e:
                hasil.append(e.status)
        with pytest.raises(tdk.GalatTindakan) as e_tidak_ada:
            await _putus(env, OWNER, "tidak-ada", "setujui")
        det_super = await tdk.detail(env["db"], SUPER, tid)
        with pytest.raises(tdk.GalatTindakan) as e_mgr:
            await tdk.detail(env["db"], MGR, tid)
        semua_super = await tdk.daftar(env["db"], SUPER, semua=True)
        semua_mgr = await tdk.daftar(env["db"], MGR, semua=True)
        sendiri_super = await tdk.daftar(env["db"], SUPER)
        return tid, hasil, e_tidak_ada.value, det_super, e_mgr.value, semua_super, semua_mgr, sendiri_super
    tid, hasil, e0, det, e_mgr, semua_super, semua_mgr, sendiri_super = run(_uji())
    assert hasil == [404, 404] and e0.status == 404 and e_mgr.status == 404
    assert det["id"] == tid and det["milik_sendiri"] is False and det["args"]["target"] == 135_000_000
    assert semua_super["semua"] is True and [r["id"] for r in semua_super["items"]] == [tid]
    assert semua_mgr["semua"] is False and semua_mgr["items"] == [] and sendiri_super["items"] == []
    assert _aksi(env)[0]["keadaan"] == "menunggu" and env["http"].tulis() == []


def test_risiko_menengah_wajib_alasan(env, dummy):
    dummy(risiko="menengah")

    async def _uji():
        _sid, ev = await _kartu_baru(env)
        k = _kartu(ev)[0]
        galat = []
        for alasan in ("", "pendek"):
            try:
                await _putus(env, OWNER, k["id"], "setujui", alasan=alasan)
            except tdk.GalatTindakan as e:
                galat.append(e.status)
        ev2 = await _putus(env, OWNER, k["id"], "setujui", alasan="Sesuai rapat target bulanan")
        return k, galat, ev2
    k, galat, ev = run(_uji())
    assert k["risiko"] == "menengah" and galat == [400, 400]
    assert [d["keadaan"] for n, d in ev if n == "tindakan_status"] == ["disetujui", "dijalankan"]
    assert _aksi(env)[0]["alasan"] == "Sesuai rapat target bulanan"


# ═══ Dua kartu satu giliran ═════════════════════════════════════════════════
def test_dua_kartu_satu_giliran_lanjut_setelah_semua_diputuskan(env, dummy):
    dummy()
    dummy(NAMA2)

    async def _uji():
        sid, ev = await _kartu_baru(env, "dua kartu sekaligus")
        k1, k2 = _kartu(ev)
        ev_a = await _putus(env, OWNER, k1["id"], "setujui")
        tunggu = await tdk.sesi_menunggu(env["db"], OWNER["id"])
        ev_b = await _putus(env, OWNER, k2["id"], "batal")
        return sid, ev_a, tunggu, ev_b
    sid, ev_a, tunggu, ev_b = run(_uji())
    assert [n for n, _ in ev_a] == ["tindakan_status", "tindakan_status"]  # belum lengkap → tanpa `mulai`
    assert tunggu == {sid}
    assert [n for n, _ in ev_b][:2] == ["tindakan_status", "mulai"] and ev_b[-1][0] == "selesai"
    u = env["fake"].panggilan[-1]["messages"][-1]["content"]
    assert [b["type"] for b in u] == ["tool_result"] * 4
    assert u[2]["content"].startswith("Disetujui dan dijalankan") and u[3]["content"] == tdk.HASIL_DIBATALKAN
    _cek_append_only(env["fake"].panggilan)


# ═══ Pembalikan ═════════════════════════════════════════════════════════════
def test_balikkan_tindakan_dan_kabar_ke_model(env, dummy):
    dummy()

    async def _uji():
        sid, ev = await _kartu_baru(env)
        tid = _kartu(ev)[0]["id"]
        await _putus(env, OWNER, tid, "setujui")
        with pytest.raises(tdk.GalatTindakan) as e_mgr:
            await tdk.balikkan(env["db"], MGR, tid, alasan="", token="t", klien_api=lambda: env["http"])
        out = await tdk.balikkan(env["db"], OWNER, tid, alasan="Salah periode", token="t",
                                 klien_api=lambda: env["http"])
        with pytest.raises(tdk.GalatTindakan) as e2:
            await tdk.balikkan(env["db"], OWNER, tid, alasan="", token="t", klien_api=lambda: env["http"])
        _j, ev3 = await _kirim(env, OWNER, sid, "lanjut")
        return tid, e_mgr.value, out, e2.value
    tid, e_mgr, out, e2 = run(_uji())
    assert e_mgr.status == 404 and out == {"ok": True, "id": tid, "keadaan": "dibalikkan", "ringkas": "Nilai uji lama dipulihkan."}
    assert e2.status == 409
    put = [c for c in env["http"].tulis() if c[0] == "PUT"]
    assert len(put) == 1 and put[0][2]["json"] == {"nilai": 120_000_000}
    assert put[0][2]["headers"]["X-Via"] == "asisten-ai" and put[0][2]["headers"]["X-Asisten-Tindakan"] == tid
    d = _aksi(env)[0]
    assert d["keadaan"] == "dibalikkan" and d["alasan_balik"] == "Salah periode" and d["dibalikkan_oleh"]["id"] == "u-owner"
    assert d["dikabarkan_balik"] is True
    u = env["fake"].panggilan[-1]["messages"][-1]["content"]
    assert any("DIBALIKKAN" in b.get("text", "") for b in u if b["type"] == "text")
    assert run(tdk.daftar(env["db"], OWNER))["items"][0]["bisa_dibalikkan"] is False


def test_balikkan_oleh_owner_untuk_tindakan_pengguna_lain_dan_tanpa_batalkan(env, dummy):
    dummy(bisa_balik=False)

    async def _uji():
        _sid, ev = await _kartu_baru(env, user=MGR)
        tid = _kartu(ev)[0]["id"]
        await _putus(env, MGR, tid, "setujui")
        with pytest.raises(tdk.GalatTindakan) as e:
            await tdk.balikkan(env["db"], SUPER, tid, alasan="", token="t", klien_api=lambda: env["http"])
        return e.value
    e = run(_uji())
    assert e.status == 409 and "tidak bisa dibalikkan" in e.pesan
    assert _aksi(env)[0]["bisa_dibalikkan"] is False and _aksi(env)[0]["pembatalan"] is None


# ═══ Skrip tiruan Kontrak C (pengingat, target) ═════════════════════════════
def test_skrip_tiruan_pengingat_dan_target(env, dummy):
    env["fake"] = fk.FakeAsyncAnthropic(jeda=0)          # skrip bawaan
    dummy("buat_pengingat")                               # tiruan menggantikan alat asli selama uji
    dummy("pasang_target_toko")
    skenario_asli = ab._DAFTAR.pop("skenario_target", None)

    async def _uji():
        sid, ev = await _kartu_baru(env, "ingatkan saya: buat pengingat rapat besok")
        k = _kartu(ev)
        ev2 = await _putus(env, OWNER, k[0]["id"], "setujui")
        sid3, ev3 = await _kartu_baru(env, "berapa baiknya target bulan depan? pakai yang realistis")
        k3 = _kartu(ev3)
        ev4 = await _putus(env, OWNER, k3[0]["id"], "batal")
        return ev, ev2, ev3, ev4
    try:
        ev, ev2, ev3, ev4 = run(_uji())
    finally:
        if skenario_asli is not None:
            ab._DAFTAR["skenario_target"] = skenario_asli
    assert _kartu(ev)[0]["nama"] == "buat_pengingat"
    assert "Pengingat sudah dibuat." in "".join(d["delta"] for n, d in ev2 if n == "teks")
    assert any(n == "tabel" for n, _ in ev3) and _kartu(ev3)[0]["nama"] == "pasang_target_toko"
    assert "`skenario_target` belum terpasang" in "".join(d["delta"] for n, d in ev3 if n == "teks")
    assert "tidak jadi" in "".join(d["delta"] for n, d in ev4 if n == "teks")
    _cek_append_only(env["fake"].panggilan[-3:])


def test_skrip_tiruan_tanpa_alat_tindakan_dikatakan(env):
    env["fake"] = fk.FakeAsyncAnthropic(jeda=0)
    ab.muat_semua_alat()
    simpanan = {n: ab._DAFTAR.pop(n, None) for n in ("buat_pengingat", "pasang_target_toko", "skenario_target")}
    try:
        _s, ev = run(_kartu_baru(env, "buat pengingat"))
        _s, ev2 = run(_kartu_baru(env, "pasang target"))
    finally:
        for n, a in simpanan.items():
            if a is not None:
                ab._DAFTAR[n] = a
    assert "`buat_pengingat` belum terpasang" in "".join(d["delta"] for n, d in ev if n == "teks")
    teks2 = "".join(d["delta"] for n, d in ev2 if n == "teks")
    assert "`pasang_target_toko` belum terpasang" in teks2 and _kartu(ev2) == [] and ev2[-1][0] == "selesai"


def test_isian_tiruan_dari_skenario():
    k = fk.Keadaan({"messages": [{"role": "user", "content": [
        {"type": "text", "text": pr.konteks_giliran(today=HARI_UJI, cv="DA", periode="2026-11", peran="owner")},
        {"type": "text", "text": "target"}]}], "tools": []})
    assert k.hari_ini == HARI_UJI
    skema = {"type": "object", "required": ["periode", "skenario", "toko"],
             "properties": {"periode": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
                            "skenario": {"type": "string", "enum": ["konservatif", "realistis", "agresif"]},
                            "toko": {"type": "array", "items": {"type": "object", "required": ["akun_id", "target"],
                                                                "properties": {"akun_id": {"type": "string"},
                                                                               "target": {"type": "integer"}}}}}}
    baris, petunjuk = fk._baris_skenario(json.dumps({"periode": "2026-12", "toko": [
        {"akun_id": "a1", "nama": "Toko A", "konservatif": 1, "realistis": 145_000_000.4, "agresif": 3}]}))
    args = fk._isi_tindakan(skema, k, petunjuk, baris)
    assert args == {"periode": "2026-12", "skenario": "realistis", "toko": [{"akun_id": "a1", "target": 145_000_000}]}
    assert ab.periksa_skema(skema, args) == []
    s2 = {"type": "object", "required": ["judul", "waktu"],
          "properties": {"judul": {"type": "string"}, "waktu": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"}}}
    a2 = fk._isi_tindakan(s2, k, {"_jenis": "pengingat"})
    assert a2["waktu"] == "2026-11-09T09:00" and "mode uji" in a2["judul"]


# ═══ SDK anthropic SUNGGUHAN + transport tiruan: satu siklus jeda → lanjut ══
def _sse_wire(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _msg(mid, blocks, stop):
    ev = [{"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant",
                                                "model": "claude-opus-5-5", "content": [], "stop_reason": None,
                                                "stop_sequence": None,
                                                "usage": {"input_tokens": 30, "output_tokens": 1,
                                                          "cache_creation_input_tokens": 0,
                                                          "cache_read_input_tokens": 0}}}]
    for i, (awal, deltas) in enumerate(blocks):
        ev.append({"type": "content_block_start", "index": i, "content_block": awal})
        ev += [{"type": "content_block_delta", "index": i, "delta": d} for d in deltas]
        ev.append({"type": "content_block_stop", "index": i})
    ev += [{"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
            "usage": {"output_tokens": 20}}, {"type": "message_stop"}]
    return ev


def test_sdk_anthropic_sungguhan_jeda_lalu_lanjut(env, dummy):
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    dummy()
    permintaan = []
    r1 = _msg("msg_b1", [
        ({"type": "thinking", "thinking": "", "signature": ""},
         [{"type": "thinking_delta", "thinking": "Siapkan kartu."}, {"type": "signature_delta", "signature": "sig-b1"}]),
        ({"type": "text", "text": ""}, [{"type": "text_delta", "text": "Saya siapkan kartunya."}]),
        ({"type": "tool_use", "id": "toolu_b1", "name": NAMA, "input": {}},
         [{"type": "input_json_delta", "partial_json": '{"periode": "2026-12", '},
          {"type": "input_json_delta", "partial_json": '"target": 135000000}'}]),
    ], "tool_use")
    r2 = _msg("msg_b2", [({"type": "text", "text": ""}, [{"type": "text_delta", "text": "Nilai sudah terpasang."}])],
              "end_turn")

    def handler(request):
        permintaan.append(json.loads(request.content))
        ev = r1 if len(permintaan) == 1 else r2
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_sse_wire(ev))
    klien = anthropic.AsyncAnthropic(api_key="sk-ant-uji-tiruan", base_url="http://anthropic.test", max_retries=0,
                                     http_client=anthropic.DefaultAsyncHttpxClient(
                                         transport=httpx2.MockTransport(handler)))

    async def _uji():
        sid = await _sesi_baru(env)
        _j, ev = await _kirim(env, OWNER, sid, "pasang nilai uji", klien=klien)
        tid = _kartu(ev)[0]["id"]
        ev2 = await _putus(env, OWNER, tid, "setujui", klien=klien)
        return ev, ev2
    ev, ev2 = run(_uji())
    assert len(permintaan) == 2 and ev[-1][1]["status"] == "menunggu_konfirmasi"
    b1, b2 = permintaan
    assert NAMA in [x.get("name") for x in b1["tools"]] and b1["tools"] == b2["tools"] and b1["system"] == b2["system"]
    assert b2["messages"][:len(b1["messages"])] == b1["messages"]
    asst, user = b2["messages"][-2], b2["messages"][-1]
    assert asst["content"][0] == {"type": "thinking", "thinking": "Siapkan kartu.", "signature": "sig-b1"}
    assert asst["content"][2]["id"] == "toolu_b1" and asst["content"][2]["input"] == {"periode": "2026-12", "target": 135000000}
    assert user["content"][0]["tool_use_id"] == "toolu_b1"
    assert user["content"][0]["content"].startswith("Disetujui dan dijalankan:")
    assert "".join(d["delta"] for n, d in ev2 if n == "teks") == "Nilai sudah terpasang." and ev2[-1][0] == "selesai"


# ═══ Route (mode uji) + pengaturan + registri ═══════════════════════════════
class Req:
    def __init__(self, body=None, app=None):
        self._body = body or {}
        self.headers = {"Authorization": "Bearer tok-uji"}
        self.app = app

        class _S:
            pass
        self.state = _S()
        self.query_params = {}

    async def json(self):
        return self._body

    async def is_disconnected(self):
        return False


def _app_uji():
    from fastapi import FastAPI, Request
    app = FastAPI()
    keadaan = {"nilai": 120_000_000, "tulis": []}

    @app.get("/api/uji/nilai")
    async def baca():
        return {"nilai": keadaan["nilai"]}

    @app.post("/api/uji/nilai")
    async def pasang(request: Request):
        body = await request.json()
        keadaan["tulis"].append({"via": request.headers.get("x-via"), "id": request.headers.get("x-asisten-tindakan"),
                                 "auth": request.headers.get("authorization")})
        lama, keadaan["nilai"] = keadaan["nilai"], body["target"]
        return {"id": "nilai-1", "lama": lama}
    return app, keadaan


def test_route_tindakan_lengkap_lewat_asgi(env, dummy, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi import HTTPException
    from routes import asisten_ai_routes as r
    dummy()
    akun = {"u": OWNER}

    async def _auth(_req):
        return dict(akun["u"])
    monkeypatch.setattr(r, "require_auth", _auth)
    monkeypatch.setattr(r, "get_db", lambda: env["db"])
    monkeypatch.setenv("ASISTEN_AI_FAKE", "1")
    monkeypatch.setattr(fk, "_KLIEN", fk.FakeAsyncAnthropic(skrip=skrip_uji, jeda=0))
    app, keadaan = _app_uji()

    async def _baca(resp):
        return _sse([c async for c in resp.body_iterator])

    async def _tunggu(sid):
        for _ in range(100):
            if not mesin.sedang_berjalan(sid):
                return
            await asyncio.sleep(0.01)

    async def _uji():
        s = await r.buat_sesi(Req())
        ev = await _baca(await r.kirim_pesan(s["id"], Req({"teks": "pasang nilai uji", "cv": "DA"}, app=app)))
        await _tunggu(s["id"])
        tid = _kartu(ev)[0]["id"]
        sesi = await r.ambil_sesi(s["id"], Req())
        daftar_sesi = await r.daftar_sesi(Req())
        st = await r.status(Req())
        daftar = await r.daftar_tindakan(Req(), status="menunggu")
        det = await r.detail_tindakan(tid, Req())
        galat = []
        for body in ({"keputusan": "terserah"}, {"keputusan": "setujui", "cv": "PT"},
                     {"keputusan": "setujui", "ubahan": ["x"]}):
            try:
                await r.putuskan_tindakan(tid, Req(body, app=app))
            except HTTPException as e:
                galat.append(e.status_code)
        akun["u"] = SUPER
        try:
            await r.putuskan_tindakan(tid, Req({"keputusan": "setujui"}, app=app))
        except HTTPException as e:
            galat.append(e.status_code)
        akun["u"] = OWNER
        ev2 = await _baca(await r.putuskan_tindakan(tid, Req({"keputusan": "setujui", "cv": "DA"}, app=app)))
        await _tunggu(s["id"])
        try:
            await r.putuskan_tindakan(tid, Req({"keputusan": "batal"}, app=app))
        except HTTPException as e:
            galat.append(e.status_code)
        try:
            await r.daftar_tindakan(Req(), status="aneh")
        except HTTPException as e:
            galat.append(e.status_code)
        sesudah = await r.ambil_sesi(s["id"], Req())
        semua = await r.daftar_tindakan(Req(), semua="1")
        await r.hapus_sesi(s["id"], Req())
        return ev, sesi, daftar_sesi, st, daftar, det, galat, ev2, sesudah, semua
    ev, sesi, daftar_sesi, st, daftar, det, galat, ev2, sesudah, semua = run(_uji())
    assert ev[-1][1]["status"] == "menunggu_konfirmasi"
    assert sesi["ada_tindakan_menunggu"] is True and daftar_sesi[0]["ada_tindakan_menunggu"] is True
    assert next(b for p in sesi["pesan"] for b in p["blok"] if b["jenis"] == "tindakan")["keadaan"] == "menunggu"
    assert '"api"' not in json.dumps(sesi) and '"tunda"' not in json.dumps(sesi)
    assert st["tindakan_aktif"] is True and st["batas_tindakan_harian"] == 30 and st["tindakan_hari_ini"] == 0
    row = daftar["items"][0]
    assert daftar["total"] == 1 and set(row) == {"id", "dibuat", "pengguna", "sesi_id", "nama", "label", "judul",
                                                  "keadaan", "risiko", "ringkas", "bisa_dibalikkan"}
    assert row["judul"] == "Pasang nilai uji 2026-12" and row["pengguna"] == {"id": "u-owner", "nama": "Pemilik Uji"}
    assert det["rencana"]["judul"] == row["judul"] and "pembatalan" not in det and "kunci_proses" not in det
    assert galat == [400, 400, 400, 404, 409, 400]
    st2 = [d["keadaan"] for n, d in ev2 if n == "tindakan_status"]
    assert st2 == ["disetujui", "dijalankan"] and ev2[-1][0] == "selesai"
    assert keadaan["tulis"] == [{"via": "asisten-ai", "id": row["id"], "auth": "Bearer tok-uji"}]
    assert keadaan["nilai"] == 135_000_000
    assert sesudah["ada_tindakan_menunggu"] is False and [p["peran"] for p in sesudah["pesan"]] == ["user", "asisten", "asisten"]
    assert semua["semua"] is True and semua["items"][0]["keadaan"] == "dijalankan"


def test_pengaturan_monitor_ai_kunci_tindakan(monkeypatch):
    from fastapi import HTTPException
    from routes import ai_usage_monitor as mon
    db = fm.FakeDB()
    db.ai_config.docs.append({"id": "global"})
    monkeypatch.setattr(mon, "get_db", lambda: db)
    monkeypatch.setattr(t, "get_db", lambda: db)
    t.invalidate_ai_settings_cache()

    class R:
        def __init__(self, role):
            self.role = role

    async def _auth(req):
        return {"id": "u", "role": req.role, "email": "admin@uji.test"}
    monkeypatch.setattr(mon, "require_auth", _auth)
    bawaan = run(t.get_ai_settings(force=True))
    assert bawaan["asisten_tindakan_aktif"] is True and bawaan["asisten_batas_tindakan_harian"] == 30
    out = run(mon.update_settings(R("owner"), payload={"asisten_tindakan_aktif": False,
                                                      "asisten_batas_tindakan_harian": 5}))
    assert out["data"]["asisten_tindakan_aktif"] is False and out["data"]["asisten_batas_tindakan_harian"] == 5
    assert run(tdk.pengaturan()) == {"aktif": False, "batas": 5}
    got = run(mon.get_settings(R("manager")))
    assert got["data"]["asisten_tindakan_aktif"] is False
    for bad in ({"asisten_batas_tindakan_harian": -1}, {"asisten_batas_tindakan_harian": "banyak"},
                {"asisten_batas_tindakan_harian": 2.5}):
        with pytest.raises(HTTPException) as e:
            run(mon.update_settings(R("owner"), payload=bad))
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(mon.update_settings(R("manager"), payload={"asisten_tindakan_aktif": True}))
    assert e.value.status_code == 403
    t.invalidate_ai_settings_cache()


def test_prompt_sistem_stabil_dengan_aturan_tindakan():
    p = pr.PROMPT_SISTEM
    assert "## Tindakan (mengubah data)" in p and '"Disetujui dan dijalankan"' in p and "[Tindakan]" in p
    assert "belum bisa mengubah data" not in p
    assert not re.search(r"\d{4}-\d{2}-\d{2}", p) and "2026" not in p
    assert pr.SISTEM_API[-1]["cache_control"] == {"type": "ephemeral"}
    assert tdk.HASIL_DIJALANKAN.startswith("Disetujui dan dijalankan")


def test_koleksi_ai_actions_log_dan_katalog_modul():
    from core import collection_registry as cr
    from data import module_catalog as mc
    assert cr.is_registered("ai_actions") and cr.kind_of("ai_actions") == "log"
    for p in ("/api/asisten-ai/tindakan", "/api/asisten-ai/tindakan/abc/putuskan", "/api/asisten-ai/tindakan/abc/balikkan"):
        mod = mc.match_module(p)
        assert mod["id"] == "mgmt_asisten_ai" and "asisten-ai-tindakan" in mod["menus"]
    mod = mc.match_module("/api/asisten-ai/tindakan/abc/putuskan")
    assert mc.detect_action("POST", "/api/asisten-ai/tindakan/abc/putuskan", mod) == "view"
    assert doc_lock.STALE == timedelta(minutes=10)
