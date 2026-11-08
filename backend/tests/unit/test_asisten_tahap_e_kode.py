"""Uji HERMETIK Asisten AI Tahap E (9 Nov 2026) — hitung dengan kode (agen inti).

Ruang hitung (code execution_20260120), programmatic tool calling (alat `kode=True` dipanggil dari kode), kontainer per
sesi, blok hasil code execution di riwayat, berkas keluaran kode (Files API tiruan) + rute unduh berizin.
Klien Anthropic = tiruan `core.asisten_ai.fake` (+ satu uji SDK `anthropic` sungguhan lewat transport tiruan),
Mongo = tiruan in-memory. TIDAK ada panggilan API sungguhan.

Jalankan:  cd backend && python -m pytest tests/unit/test_asisten_tahap_e_kode.py -q
"""
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ai_fakes import FakeDB as TrackerDB, run  # noqa: E402
import _fake_mongo as fm  # noqa: E402

import ai_cost_tracker as t  # noqa: E402
from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai import berkas_kode as bk  # noqa: E402
from core.asisten_ai import fake as fk  # noqa: E402
from core.asisten_ai import mesin  # noqa: E402
from core.asisten_ai import simpan  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
HARI_UJI = date(2026, 11, 9)
OWNER = {"id": "u-owner", "name": "Pemilik Uji", "role": "owner"}
MGR = {"id": "u-mgr", "name": "Manajer Uji", "role": "manager_keuangan"}
NAMA_KODE = "uji_data_kode"
CATATAN: dict = {"pemanggil": [], "ctx": []}


async def _alat_uji_kode(ctx, args):
    CATATAN["pemanggil"].append(ctx.pemanggil)
    CATATAN["ctx"].append(id(ctx))
    await asyncio.sleep(0)
    n = int(args.get("n") or 3)
    return {"baris": [{"kelompok": f"K{i}", "nilai": i} for i in range(n)], "_sumber": "Data uji"}


def _daftarkan_alat_uji():
    ab.muat_semua_alat()
    ab.alat(name=NAMA_KODE, kind="read", label="Membaca data uji", description="Data uji untuk kode (hanya uji).",
            input_schema={"type": "object", "properties": {"n": {"type": "integer"}}}, domain="umum",
            kode=True)(_alat_uji_kode)


# ── perlengkapan ────────────────────────────────────────────────────────────
@pytest.fixture
def env(monkeypatch):
    tdb = TrackerDB()
    monkeypatch.setattr(t, "get_db", lambda: tdb)
    monkeypatch.setattr(t, "sdk_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-uji-hermetik-0000")
    monkeypatch.delenv("ASISTEN_AI_FAKE", raising=False)
    for k in ("ringkasan_penjualan", "buat_laporan"):
        monkeypatch.delitem(ab._DAFTAR, k, raising=False)
    # Alat kode milik agen lain (mis. `cari_data`) dilepas selama uji → skrip tiruan memakai alat uji di sini.
    ab.muat_semua_alat()
    for nama, a in list(ab._DAFTAR.items()):
        if a.kode:
            monkeypatch.delitem(ab._DAFTAR, nama)
    _daftarkan_alat_uji()
    import object_storage
    simpanan: dict = {}
    monkeypatch.setattr(object_storage, "put_object",
                        lambda path, data, ct="application/octet-stream": simpanan.__setitem__(path, (data, ct))
                        or {"path": path})
    monkeypatch.setattr(object_storage, "get_object", lambda path: simpanan.get(path))
    t.invalidate_api_key_cache()
    t.invalidate_ai_settings_cache()
    mesin._FALLBACK["aktif"] = True
    mesin._AKTIF.clear()
    CATATAN["pemanggil"].clear()
    CATATAN["ctx"].clear()
    yield {"tdb": tdb, "db": fm.FakeDB(), "fake": fk.FakeAsyncAnthropic(jeda=0), "simpanan": simpanan}
    ab._DAFTAR.pop(NAMA_KODE, None)
    t.invalidate_api_key_cache()
    t.invalidate_ai_settings_cache()


def _sse(chunks):
    out = []
    for c in chunks:
        m = re.match(r"event: (\w+)\ndata: (.*)\n\n$", c, re.S)
        assert m, c
        out.append((m.group(1), json.loads(m.group(2))))
    return out


class FakeHttp:
    async def request(self, method, path, **kw):
        raise AssertionError("alat uji tidak memanggil ctx.api")

    async def aclose(self):
        pass


async def _kirim(env, user, sesi_id, teks, *, klien=None, **kw):
    db = env["db"]
    sesi = await simpan.ambil_sesi(db, user["id"], sesi_id)
    jalan, galat = await mesin.siapkan_jalan(
        db=db, user=user, sesi=sesi, teks=teks, cv="DA", periode="2026-11", today=HARI_UJI, token="tok-uji",
        app=None, klien=klien or env["fake"], klien_api=lambda: FakeHttp(), **kw)
    if galat:
        return None, [("galat", galat)]
    task = mesin.mulai(jalan)
    chunks = [c async for c in mesin.aliran_sse(jalan)]
    await task
    return jalan, _sse(chunks)


def _pesan_asisten(env, sesi_id):
    return [d for d in env["db"].ai_chat_messages.docs if d["sesi_id"] == sesi_id and d["peran"] == "asisten"]


def _cek_riwayat_sah(api: list) -> None:
    """Setiap server_tool_use punya hasil, setiap tool_use dibalas di giliran berikutnya."""
    srv = {b["id"] for m in api for b in m["content"] if isinstance(b, dict) and b.get("type") == "server_tool_use"}
    hasil = {b.get("tool_use_id") for m in api for b in m["content"] if isinstance(b, dict)
             and b.get("type") in mesin.JENIS_HASIL_SERVER}
    assert srv <= hasil, srv - hasil
    for i, m in enumerate(api):
        ids = [b["id"] for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
        if ids:
            nxt = {b.get("tool_use_id") for b in api[i + 1]["content"] if b.get("type") == "tool_result"}
            assert set(ids) <= nxt


# ═══ 1. Daftar alat & kerangka ══════════════════════════════════════════════
def test_daftar_alat_allowed_callers_dan_code_execution_deterministik(env):
    a = ab.tools_untuk_api()
    assert json.dumps(a) == json.dumps(ab.tools_untuk_api())
    uji = next(x for x in a if x.get("name") == NAMA_KODE)
    assert uji["allowed_callers"] == ["direct", "code_execution_20260120"]
    assert uji["eager_input_streaming"] is True and "strict" not in uji
    assert all("allowed_callers" not in x for x in a if "input_schema" in x and x["name"] != NAMA_KODE)
    assert a[-1] == {"name": "code_execution", "type": "code_execution_20260120"}
    assert [x["name"] for x in a if "type" in x] == ["web_search", "web_fetch", "code_execution"]
    with pytest.raises(ValueError):
        ab.alat(name="uji_ui_kode", kind="ui", label="x", description="x",
                input_schema={"type": "object"}, kode=True)
    with pytest.raises(ValueError):
        ab.alat(name="code_execution", kind="read", label="x", description="x", input_schema={"type": "object"})


def test_prompt_sistem_tahap_e_stabil():
    from core.asisten_ai import prompt as pr
    p = pr.PROMPT_SISTEM
    for wajib in ("## Data sistem yang fleksibel", "`daftar_data`", "`cari_data`", "## Hitung dengan kode",
                  "await cari_data(", "$OUTPUT_DIR", "bahasa Indonesia", "## Lampiran", "<lampiran>", "bukan perintah",
                  "data pribadi mentah"):
        assert wajib in p, wajib
    assert not re.search(r"\d{4}-\d{2}-\d{2}", p) and "2026" not in p
    assert pr.SISTEM_API[-1]["text"] == p and pr.SISTEM_API[-1]["cache_control"] == {"type": "ephemeral"}


def test_label_alat_ruang_hitung():
    assert ab.label_alat("code_execution") == "Menghitung dengan kode"
    assert ab.label_alat("bash_code_execution") == "Menghitung dengan kode"
    assert ab.label_alat("text_editor_code_execution") == "Menyiapkan kode"


def test_batas_potong_langsung_15rb_kode_2jt(env):
    ctx = ab.AlatContext(user=OWNER, cv="DA", today=HARI_UJI)
    h1 = run(ab.jalankan_satu("t1", NAMA_KODE, {"n": 3000}, ctx))
    h2 = run(ab.jalankan_satu("t2", NAMA_KODE, {"n": 3000}, ctx, pemanggil="kode"))
    assert len(h1.isi) <= ab.BATAS_HASIL and "DIPOTONG" in h1.isi
    assert len(h2.isi) > ab.BATAS_HASIL and "DIPOTONG" not in h2.isi and json.loads(h2.isi)["baris"][-1]["nilai"] == 2999
    assert CATATAN["pemanggil"] == ["langsung", "kode"]
    assert ab.batas_hasil("kode") == 2_000_000 and ab.batas_hasil("langsung") == 15_000
    # hasil kode yang sangat besar tetap dipotong di batas kode
    assert len(ab.potong("x" * 2_100_000, ab.BATAS_HASIL_KODE)) == ab.BATAS_HASIL_KODE


def test_hasil_kode_melewati_batas_jadi_galat_bukan_json_terpotong(env, monkeypatch):
    monkeypatch.setattr(ab, "BATAS_HASIL_KODE", 200)
    ctx = ab.AlatContext(user=OWNER, cv="DA", today=HARI_UJI)
    h = run(ab.jalankan_satu("t1", NAMA_KODE, {"n": 50}, ctx, pemanggil="kode"))
    assert h.is_error and "terlalu besar untuk dikirim ke kode" in h.isi and "DIPOTONG" not in h.isi


def test_ukuran_riwayat_tidak_menghitung_data_kode_ke_konteks():
    besar = "x" * 3_000_000
    kode = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": NAMA_KODE, "input": {},
                                               "caller": {"type": "code_execution_20260120", "tool_id": "s"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": besar}]}]
    konteks, muatan = mesin.ukuran_riwayat(kode)
    assert konteks < 1000 and muatan > 3_000_000 and not mesin.riwayat_terlalu_panjang(kode)
    langsung = json.loads(json.dumps(kode))
    langsung[1]["content"][0]["caller"] = {"type": "direct"}
    assert mesin.riwayat_terlalu_panjang(langsung)
    assert mesin.riwayat_terlalu_panjang(kode * 6)          # muatan > 16 juta karakter


def test_jatah_data_kode_per_jawaban(env, monkeypatch):
    monkeypatch.setattr(mesin, "MAKS_DATA_KODE", 150)

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        return await _kirim(env, OWNER, sid, "hitung dengan kode rekapnya")
    _j, ev = run(_uji())
    hasil = env["fake"].panggilan[1]["messages"][-1]["content"]
    assert [bool(b.get("is_error")) for b in hasil] == [False, True]
    assert "terlalu besar" in hasil[1]["content"] and ev[-1][0] == "selesai"


def test_ctx_pemanggil_salinan_per_panggilan_bersamaan(env):
    ctx = ab.AlatContext(user=OWNER, cv="DA", today=HARI_UJI)
    calls = [("a", NAMA_KODE, {"n": 1}, "kode"), ("b", NAMA_KODE, {"n": 1}), ("c", NAMA_KODE, {"n": 1}, "kode")]
    hasil = run(ab.jalankan_banyak(calls, ctx))
    assert [h.tool_use_id for h in hasil] == ["a", "b", "c"] and not any(h.is_error for h in hasil)
    assert sorted(CATATAN["pemanggil"]) == ["kode", "kode", "langsung"]
    assert len(set(CATATAN["ctx"])) == 3 and id(ctx) not in CATATAN["ctx"]
    assert ctx.pemanggil == "langsung"


def test_alat_tanpa_kode_ditolak_bila_dipanggil_dari_kode(env):
    ctx = ab.AlatContext(user=OWNER, cv="DA", today=HARI_UJI)
    hasil = run(ab.jalankan_banyak([("a", "tanggal_dan_periode", {}, "kode"), ("b", "tampilkan_tabel", {}, "kode")],
                                   ctx))
    assert all(h.is_error and h.isi == ab.PESAN_BUKAN_KODE for h in hasil)


# ═══ 2. Blok code execution di riwayat ═══════════════════════════════════════
def test_blok_code_execution_dikenal_dan_aturan_fallback():
    for jenis in ("code_execution_tool_result", "bash_code_execution_tool_result",
                  "text_editor_code_execution_tool_result", "container_upload"):
        assert jenis in mesin._JENIS_BLOK_DIKENAL
    konten = [
        {"type": "server_tool_use", "id": "srv_a", "name": "code_execution", "input": {}},
        {"type": "code_execution_tool_result", "tool_use_id": "srv_a", "content": {"type": "code_execution_result"}},
        {"type": "server_tool_use", "id": "srv_b", "name": "bash_code_execution", "input": {}},
        {"type": "bash_code_execution_tool_result", "tool_use_id": "srv_b", "content": {}},
        {"type": "server_tool_use", "id": "srv_c", "name": "code_execution", "input": {}},   # tanpa hasil → dibuang
        {"type": "thinking", "thinking": "x", "signature": "s"},
        {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}},
        {"type": "text", "text": "ok"},
    ]
    out = mesin.rapikan_fallback(konten)
    assert [b.get("id") or b.get("tool_use_id") or b["type"] for b in out] == [
        "srv_a", "srv_a", "srv_b", "srv_b", "fallback", "text"]
    msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "content": konten[:2] + [konten[5]]}]
    assert mesin.tanpa_thinking(msgs)[1]["content"] == konten[:2]


def test_dari_kode_membaca_caller():
    assert mesin.dari_kode({"type": "tool_use", "caller": {"type": "code_execution_20260120", "tool_id": "s"}})
    assert not mesin.dari_kode({"type": "tool_use", "caller": {"type": "direct"}})
    assert not mesin.dari_kode({"type": "tool_use"})


# ═══ 3. Loop: programmatic tool calling + kontainer + berkas keluaran ═══════
def test_loop_ptc_giliran_hanya_tool_result_kontainer_dan_berkas(env):
    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        return sid, *(await _kirim(env, OWNER, sid, "Tolong hitung dengan kode total nilai per kelompok"))
    sid, jalan, ev = run(_uji())
    p = env["fake"].panggilan
    assert len(p) == 2
    assert "container" not in p[0]
    tools0 = {x.get("name"): x for x in p[0]["tools"]}
    assert tools0[NAMA_KODE]["allowed_callers"] == ["direct", "code_execution_20260120"]
    assert tools0["code_execution"]["type"] == "code_execution_20260120"
    # permintaan kedua: kontainer yang sama + giliran HANYA tool_result (dua panggilan dari kode)
    cid = p[1]["container"]
    assert cid.startswith("container_") and cid in env["fake"].kontainer
    akhir = p[1]["messages"][-1]
    assert akhir["role"] == "user" and [b["type"] for b in akhir["content"]] == ["tool_result", "tool_result"]
    assert all(isinstance(b["content"], str) and not b.get("is_error") for b in akhir["content"])
    assert "tool_choice" not in p[1]
    asst = p[1]["messages"][-2]["content"]
    assert [b["caller"]["type"] for b in asst if b["type"] == "tool_use"] == ["code_execution_20260120"] * 2
    assert CATATAN["pemanggil"] == ["kode", "kode"] and len(set(CATATAN["ctx"])) == 2
    # event layar
    nama = [e for e, _ in ev]
    assert nama[0] == "mulai" and nama[-1] == "selesai"
    alat_kode = [d for e, d in ev if e == "alat" and d["nama"] in ("code_execution", "bash_code_execution")]
    assert {d["label"] for d in alat_kode} == {"Menghitung dengan kode"}
    assert {d["keadaan"] for d in alat_kode} == {"mulai", "selesai"}
    (brk,) = [d for e, d in ev if e == "berkas"]
    assert brk["nama"] == fk.NAMA_BERKAS_CONTOH and brk["format"] == "xlsx" and brk["ukuran_kb"] > 0
    assert brk["url"] == f"/api/asisten-ai/berkas/{brk['id']}" and set(brk) == {"id", "nama", "format", "ukuran_kb",
                                                                                "url"}
    # metadata + salinan berkas (path acak di awalan sensitif; path tidak pernah ke layar)
    (doc,) = env["db"].ai_berkas.docs
    (pa,) = _pesan_asisten(env, sid)
    assert doc["id"] == brk["id"] and doc["dibuat_oleh"] == OWNER["id"] and doc["sesi_id"] == sid
    assert doc["pesan_id"] == pa["id"] and doc["file_id"] in env["fake"].files.berkas
    assert doc["path"].startswith(f"ai_berkas/{doc['id']}/") and doc["path"] in env["simpanan"]
    assert env["simpanan"][doc["path"]][0][:2] == b"PK"
    assert "ai_berkas/" not in json.dumps([d for _e, d in ev])
    # riwayat: blok berkas + api append-only berisi hasil code execution
    assert {"jenis": "berkas", **brk} in pa["blok"] and pa["status"] == "selesai"
    jenis_api = [b["type"] for m in pa["api"] for b in m["content"]]
    assert "code_execution_tool_result" in jenis_api and "bash_code_execution_tool_result" in jenis_api
    _cek_riwayat_sah(pa["api"])
    # kontainer tersimpan di sesi
    sesi = env["db"].ai_chat_sessions.docs[0]
    assert sesi["container_id"] == cid and sesi["container_dibuat"] and sesi["container_kedaluwarsa"]
    assert jalan.putaran_kode == 1 and jalan.putaran_alat == 0


def test_kontainer_dikirim_balik_pada_pesan_berikutnya(env):
    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        await _kirim(env, OWNER, sid, "hitung dengan kode rekapnya")
        _j, ev = await _kirim(env, OWNER, sid, "Apa kesimpulannya?")
        return sid, ev
    sid, ev = run(_uji())
    p = env["fake"].panggilan
    assert p[-1]["container"] == p[1]["container"] == env["db"].ai_chat_sessions.docs[0]["container_id"]
    assert ev[-1][0] == "selesai"


def test_kontainer_kedaluwarsa_diulang_tanpa_kontainer(env):
    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        await _kirim(env, OWNER, sid, "hitung dengan kode rekapnya")
        env["fake"].kedaluwarsakan_kontainer(env["db"].ai_chat_sessions.docs[0]["container_id"])
        n = len(env["fake"].panggilan)
        _j, ev = await _kirim(env, OWNER, sid, "Apa kesimpulannya?")
        return sid, n, ev
    sid, n, ev = run(_uji())
    p = env["fake"].panggilan[n:]
    # ditolak (kontainer kedaluwarsa) → diulang tanpa kontainer → tabel → teks
    assert len(p) == 3 and "container" in p[0] and all("container" not in x for x in p[1:])
    assert ev[-1][0] == "selesai" and not any(e == "galat" for e, _ in ev)
    assert "container_id" not in env["db"].ai_chat_sessions.docs[0]


def test_kontainer_terlalu_tua_tidak_dikirim():
    lama = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    baru = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert simpan.kontainer_sah({"container_id": "c1", "container_dibuat": lama}) is None
    assert simpan.kontainer_sah({"container_id": "c1", "container_dibuat": baru}) == "c1"
    assert simpan.kontainer_sah({"container_id": "c1"}) is None and simpan.kontainer_sah({}) is None


def _skrip_kode_terus(berhenti_saat_galat: bool):
    """Skrip: kode memanggil alat terus; selesai bila menerima tool_result is_error (bila diminta)."""
    def skrip(k):
        msgs = k.kw["messages"]
        sid = next((b["id"] for m in msgs[k.idx + 1:] if m["role"] == "assistant" for b in m["content"]
                    if b.get("type") == "server_tool_use"), None)
        caller = {"type": "code_execution_20260120", "tool_id": sid}
        if sid is None:
            sid = fk._bid("srvtoolu")
            return ([{"type": "server_tool_use", "id": sid, "name": "code_execution", "input": {"code": "x"}},
                     {**fk._alat(NAMA_KODE, {"n": 1}), "caller": {"type": "code_execution_20260120", "tool_id": sid}}],
                    "tool_use", {"kontainer": True})
        if berhenti_saat_galat and any(b.get("is_error") for b in msgs[-1]["content"]):
            return ([{"type": "code_execution_tool_result", "tool_use_id": sid,
                      "content": {"type": "code_execution_result", "stdout": "", "stderr": "batas", "return_code": 1,
                                  "content": []}},
                     fk._teks("Sebagian data tidak terbaca karena batas langkah.")], "end_turn", {})
        return [{**fk._alat(NAMA_KODE, {"n": 1}), "caller": caller}], "tool_use", {}
    return skrip


def test_batas_putaran_kode_terpisah_dan_tanpa_tool_choice_none(env):
    klien = fk.FakeAsyncAnthropic(skrip=_skrip_kode_terus(True), jeda=0)

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        return sid, *(await _kirim(env, OWNER, sid, "uji batas", klien=klien, maks_putaran=0, maks_putaran_kode=3))
    sid, jalan, ev = run(_uji())
    p = klien.panggilan
    # 1 + 3 putaran kode dijalankan + 1 balasan galat → respons akhir
    assert len(p) == 5 and len(CATATAN["pemanggil"]) == 3 and set(CATATAN["pemanggil"]) == {"kode"}
    # batas alat langsung (0) sudah tercapai: permintaan pertama tool_choice none, tetapi selagi kode tertunda
    # tool_choice TIDAK dipakai (tiruan menolak none saat ada panggilan dari kode yang tertunda)
    assert p[0]["tool_choice"] == {"type": "none"} and all("tool_choice" not in x for x in p[1:])
    galat = p[-1]["messages"][-1]["content"]
    assert [b["type"] for b in galat] == ["tool_result"] and galat[0]["is_error"] is True
    assert "Batas panggilan alat dari kode" in galat[0]["content"]
    assert jalan.putaran_alat == 0 and jalan.putaran_kode == 4 and ev[-1][0] == "selesai"
    (pa,) = _pesan_asisten(env, sid)
    _cek_riwayat_sah(pa["api"])


def test_kode_tak_berhenti_dihentikan_paksa_riwayat_tetap_sah(env):
    klien = fk.FakeAsyncAnthropic(skrip=_skrip_kode_terus(False), jeda=0)

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        _j, ev = await _kirim(env, OWNER, sid, "uji tanpa henti", klien=klien, maks_putaran_kode=1)
        # pesan berikutnya tetap bisa dikirim (riwayat sah menurut aturan API tiruan)
        _j2, ev2 = await _kirim(env, OWNER, sid, "halo lagi", klien=klien)
        return sid, ev, ev2
    sid, ev, ev2 = run(_uji())
    assert any(e == "teks" and "Perhitungan dengan kode dihentikan" in d["delta"] for e, d in ev)
    assert ev[-1][0] == "selesai" and ev2[-1][0] == "selesai"
    pa = _pesan_asisten(env, sid)[0]
    _cek_riwayat_sah(pa["api"])
    assert not any(b.get("type") == "server_tool_use" for m in pa["api"] for b in m["content"])
    assert any(b["jenis"] == "alat" and b["keadaan"] == "gagal" for b in pa["blok"])


def test_tindakan_ditolak_selagi_kode_tertunda(env):
    seen = {}

    def skrip(k):
        msgs = k.kw["messages"]
        if k.giliran_asisten == 0:
            sid = fk._bid("srvtoolu")
            return ([{"type": "server_tool_use", "id": sid, "name": "code_execution", "input": {}},
                     {**fk._alat(NAMA_KODE, {}), "caller": {"type": "code_execution_20260120", "tool_id": sid}},
                     {**fk._alat("uji_tindakan_e", {}), "caller": {"type": "direct"}}], "tool_use", {"kontainer": True})
        seen["hasil"] = msgs[-1]["content"]
        sid = msgs[-2]["content"][0]["id"]
        return ([{"type": "code_execution_tool_result", "tool_use_id": sid,
                  "content": {"type": "code_execution_result", "stdout": "", "stderr": "", "return_code": 0,
                              "content": []}}, fk._teks("ok")], "end_turn", {})

    @ab.tindakan(name="uji_tindakan_e", label="Uji tindakan", description="Uji.", input_schema={"type": "object"})
    class _T:
        @staticmethod
        async def siapkan(ctx, args):
            raise AssertionError("tidak boleh disiapkan")

        @staticmethod
        async def jalankan(ctx, args, rencana):
            return {}
    try:
        klien = fk.FakeAsyncAnthropic(skrip=skrip, jeda=0)

        async def _uji():
            sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
            return await _kirim(env, OWNER, sid, "uji", klien=klien)
        _j, ev = run(_uji())
    finally:
        ab._DAFTAR.pop("uji_tindakan_e", None)
    hasil = {b["tool_use_id"]: b for b in seen["hasil"]}
    assert len(hasil) == 2 and all(b["type"] == "tool_result" for b in seen["hasil"])
    assert sum(1 for b in hasil.values() if b.get("is_error") and "Tindakan tidak bisa" in b["content"]) == 1
    assert ev[-1][0] == "selesai" and not env["db"].ai_actions.docs


# ═══ 4. Berkas keluaran (Files API tiruan) ══════════════════════════════════
def test_file_id_keluaran_dari_semua_jenis_hasil():
    konten = [
        {"type": "bash_code_execution_tool_result", "tool_use_id": "a",
         "content": {"type": "bash_code_execution_result", "content": [{"type": "bash_code_execution_output",
                                                                         "file_id": "f1"}]}},
        {"type": "code_execution_tool_result", "tool_use_id": "b",
         "content": {"type": "encrypted_code_execution_result",
                     "content": [{"type": "code_execution_output", "file_id": "f2"},
                                 {"type": "code_execution_output", "file_id": "f1"}]}},
        {"type": "bash_code_execution_tool_result", "tool_use_id": "c",
         "content": {"type": "bash_code_execution_tool_result_error", "error_code": "unavailable"}},
    ]
    assert bk.file_id_keluaran(konten) == ["f1", "f2"]
    assert bk.galat_hasil(konten[2]) == "Ruang hitung sedang tidak tersedia." and bk.galat_hasil(konten[0]) is None


def test_unduh_berkas_nama_basename_dan_batas_ukuran(env, monkeypatch):
    f = env["fake"]
    fid = f.files.tambah_keluaran("../../rahasia/Rekap omzet.xlsx", b"PK isi", "application/x")
    doc = run(bk.unduh_dan_simpan(env["db"], f, fid, user=MGR, sesi_id="s1", pesan_id="p1"))
    assert doc["nama"] == "Rekap omzet.xlsx" and doc["format"] == "xlsx" and doc["ukuran"] == 6
    assert doc["path"].startswith(f"ai_berkas/{doc['id']}/") and ".." not in doc["path"]
    assert env["simpanan"][doc["path"]][1] == bk.CONTENT_TYPE["xlsx"]
    assert bk.nama_aman("..") == "hasil" and bk.nama_aman("a\\b\\c.csv") == "c.csv"
    assert bk.content_type_dari("html") == "application/octet-stream" and bk.content_type_dari("svg").endswith("stream")
    monkeypatch.setattr(bk, "MAKS_UKURAN", 3)
    with pytest.raises(bk.GalatBerkas):
        run(bk.unduh_dan_simpan(env["db"], f, fid, user=MGR, sesi_id="s1", pesan_id="p1"))
    with pytest.raises(bk.GalatBerkas):
        run(bk.unduh_dan_simpan(env["db"], f, "file_tidak_ada", user=MGR, sesi_id="s1", pesan_id="p1"))


def test_berkas_gagal_diambil_jadi_catatan_bukan_galat(env, monkeypatch):
    async def _gagal(*_a, **_k):
        raise bk.GalatBerkas("Berkas \"x\" gagal diambil dari ruang hitung.")
    monkeypatch.setattr(bk, "unduh_dan_simpan", _gagal)

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        return await _kirim(env, OWNER, sid, "hitung dengan kode rekapnya")
    _j, ev = run(_uji())
    assert ev[-1][0] == "selesai" and not any(e == "berkas" for e, _ in ev)
    assert any(e == "teks" and "gagal diambil" in d["delta"] for e, d in ev)


@pytest.fixture
def klien_unduh(monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    import routes.asisten_ai_berkas_routes as rt

    db = fm.FakeDB()
    db.ai_berkas.docs = [
        {"id": "b-1", "dibuat_oleh": "u-pembuat", "nama": "Rekap omzet November — final.xlsx", "format": "xlsx",
         "ukuran": 6, "path": "ai_berkas/b-1/a.xlsx", "file_id": "file_1"},
        {"id": "b-2", "dibuat_oleh": "u-pembuat", "nama": "halaman.html", "format": "html", "ukuran": 6,
         "path": "ai_berkas/b-2/a.html", "file_id": "file_2"},
        {"id": "b-3", "dibuat_oleh": "u-pembuat", "nama": "hilang.png", "format": "png", "ukuran": 6,
         "path": "ai_berkas/b-3/a.png", "file_id": "file_3"}]
    pengguna = {"owner": {"id": "u-owner", "role": "owner"}, "pembuat": {"id": "u-pembuat", "role": "manager"},
                "lain": {"id": "u-lain", "role": "manager"}, "admin": {"id": "u-admin", "role": "admin"},
                "super": {"id": "u-super", "role": "superadmin"}}

    async def fake_auth(request):
        u = pengguna.get(request.headers.get("x-uji"))
        if not u:
            raise HTTPException(401, "Unauthorized")
        return dict(u)
    monkeypatch.setattr(rt, "require_auth", fake_auth)
    monkeypatch.setattr(rt, "get_db", lambda: db)
    monkeypatch.setattr(rt, "_ambil_berkas", lambda p: None if "b-3" in p else (b"PK uji", "x"))
    app = FastAPI()
    app.include_router(rt.router)
    return TestClient(app)


def test_rute_unduh_berkas_hanya_pembuat_dan_owner(klien_unduh):
    c = klien_unduh
    r = c.get("/api/asisten-ai/berkas/b-1", headers={"x-uji": "pembuat"})
    assert r.status_code == 200 and r.content == b"PK uji"
    assert r.headers["content-type"] == bk.CONTENT_TYPE["xlsx"]
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment;") and "filename*=UTF-8''Rekap%20omzet%20November%20%E2%80%94%20final.xlsx" in cd
    assert r.headers["cache-control"] == "private, no-store" and r.headers["x-content-type-options"] == "nosniff"
    for siapa in ("owner", "super"):
        assert c.get("/api/asisten-ai/berkas/b-1", headers={"x-uji": siapa}).status_code == 200
    r = c.get("/api/asisten-ai/berkas/b-1", headers={"x-uji": "lain"})
    assert r.status_code == 403 and "pengguna lain" in r.json()["detail"]
    assert c.get("/api/asisten-ai/berkas/b-1", headers={"x-uji": "admin"}).status_code == 403
    assert c.get("/api/asisten-ai/berkas/b-1").status_code == 401
    assert c.get("/api/asisten-ai/berkas/tidak-ada", headers={"x-uji": "owner"}).status_code == 404
    assert c.get("/api/asisten-ai/berkas/b-3", headers={"x-uji": "owner"}).status_code == 404
    r = c.get("/api/asisten-ai/berkas/b-2", headers={"x-uji": "pembuat"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"


def test_server_mendaftarkan_rute_berkas_dengan_gerbang_management():
    src = (BACKEND / "server.py").read_text(encoding="utf-8")
    blok = src[src.index("# ── Asisten AI (berkas kode)"):src.index("# ── akhir Asisten AI (berkas kode)")]
    assert "asisten_ai_berkas_router" in blok and '_require_portal_dep("management")' in blok
    assert "_DENY_EXTERNAL" in blok


def test_koleksi_dan_awalan_sensitif_terdaftar():
    from core import collection_registry as cr
    from core import sensitive_files as sf
    for c in ("ai_berkas", "ai_lampiran"):
        assert cr.is_registered(c) and cr.kind_of(c) == "log"
    assert sf.has_sensitive_prefix("ai_berkas/x/y.xlsx") and sf.has_sensitive_prefix("ai_lampiran/x/y.pdf")


# ═══ 5. SDK anthropic SUNGGUHAN + transport tiruan: caller, container, tool_result saja ═══
def _wire(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _msg_start(mid):
    return {"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant",
                                                 "model": "claude-opus-5-5", "content": [], "stop_reason": None,
                                                 "stop_sequence": None,
                                                 "usage": {"input_tokens": 10, "output_tokens": 1}}}


def _ptc_1():
    return [
        _msg_start("msg_e1"),
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "server_tool_use", "id": "srvtoolu_e1", "name": "code_execution", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"code": "x = 1"}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "toolu_e1", "name": NAMA_KODE, "input": {},
                           "caller": {"type": "code_execution_20260120", "tool_id": "srvtoolu_e1"}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"n": 2}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None,
                                            "container": {"id": "container_sdk_1",
                                                          "expires_at": "2026-11-09T10:30:00Z"}},
         "usage": {"output_tokens": 40}},
        {"type": "message_stop"},
    ]


def _ptc_2():
    return [
        _msg_start("msg_e2"),
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "code_execution_tool_result", "tool_use_id": "srvtoolu_e1",
                           "content": {"type": "code_execution_result", "stdout": "2 baris", "stderr": "",
                                       "return_code": 0, "content": []}}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Ada 2 baris."}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None,
                                            "container": {"id": "container_sdk_1",
                                                          "expires_at": "2026-11-09T10:35:00Z"}},
         "usage": {"output_tokens": 10}},
        {"type": "message_stop"},
    ]


def test_ptc_dengan_sdk_anthropic_sungguhan(env):
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    permintaan = []

    def handler(request):
        permintaan.append(json.loads(request.content))
        ev = _ptc_1() if len(permintaan) == 1 else _ptc_2()
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_wire(ev))

    klien = anthropic.AsyncAnthropic(api_key="sk-ant-uji-tiruan", base_url="http://anthropic.test", max_retries=0,
                                     http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)))

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        return sid, *(await _kirim(env, OWNER, sid, "Hitung", klien=klien))
    sid, _j, ev = run(_uji())
    assert len(permintaan) == 2
    b1, b2 = permintaan
    assert any(x.get("type") == "code_execution_20260120" for x in b1["tools"]) and "container" not in b1
    assert next(x for x in b1["tools"] if x.get("name") == NAMA_KODE)["allowed_callers"] == [
        "direct", "code_execution_20260120"]
    assert b2["container"] == "container_sdk_1"
    asst, akhir = b2["messages"][-2], b2["messages"][-1]
    tu = next(b for b in asst["content"] if b["type"] == "tool_use")
    assert tu["caller"] == {"type": "code_execution_20260120", "tool_id": "srvtoolu_e1"} and tu["input"] == {"n": 2}
    assert [b["type"] for b in akhir["content"]] == ["tool_result"] and isinstance(akhir["content"][0]["content"], str)
    assert CATATAN["pemanggil"] == ["kode"]
    assert ev[-1][0] == "selesai"
    assert any(e == "alat" and d["id"] == "srvtoolu_e1" and d["keadaan"] == "selesai" for e, d in ev)
    sesi = env["db"].ai_chat_sessions.docs[0]
    assert sesi["container_id"] == "container_sdk_1" and sesi["container_kedaluwarsa"].startswith("2026-11-09T10:35")
    (pa,) = _pesan_asisten(env, sid)
    assert pa["api"][-1]["content"][0]["type"] == "code_execution_tool_result"
    _cek_riwayat_sah(pa["api"])
