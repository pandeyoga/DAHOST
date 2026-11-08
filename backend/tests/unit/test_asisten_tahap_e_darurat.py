"""Uji HERMETIK Asisten AI Tahap E (9 Nov 2026) — jalur darurat ruang hitung (agen inti).

Bila API menolak gabungan alat ruang hitung (galat 400 yang menyebut code_execution / allowed_callers /
eager_input_streaming / container_upload / container / caller), saklar proses `mesin._KODE` mati dan permintaan diulang
SEKALI tanpa ruang hitung. Env `ASISTEN_AI_KODE_AKTIF=0` mematikannya sejak awal. Klien = tiruan
`core.asisten_ai.fake` (`tolak_kode=True` meniru API yang menolak semua bentuk ruang hitung). Tanpa API sungguhan.

Jalankan:  cd backend && python -m pytest tests/unit/test_asisten_tahap_e_darurat.py -q
"""
import io
import json
import os
import re
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ai_fakes import FakeDB as TrackerDB, run  # noqa: E402
import _fake_mongo as fm  # noqa: E402

import ai_cost_tracker as t  # noqa: E402
from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai import fake as fk  # noqa: E402
from core.asisten_ai import lampiran as lmp  # noqa: E402
from core.asisten_ai import mesin  # noqa: E402
from core.asisten_ai import prompt as pr  # noqa: E402
from core.asisten_ai import simpan  # noqa: E402

HARI_UJI = date(2026, 11, 9)
OWNER = {"id": "u-owner", "name": "Pemilik Uji", "role": "owner"}
NAMA_KODE = "uji_data_kode_darurat"
CSV = "kelompok,nilai\nA,10\nB,20\n".encode()
KATA_KODE = ("code_execution", "allowed_callers", "container_upload")


async def _alat_uji(ctx, args):
    return {"baris": [{"kelompok": "A", "nilai": 1}]}


def _pdf() -> bytes:
    from PyPDF2 import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def env(monkeypatch):
    tdb = TrackerDB()
    monkeypatch.setattr(t, "get_db", lambda: tdb)
    monkeypatch.setattr(t, "sdk_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-uji-hermetik-0000")
    monkeypatch.delenv("ASISTEN_AI_FAKE", raising=False)
    monkeypatch.delenv("ASISTEN_AI_KODE_AKTIF", raising=False)
    monkeypatch.setitem(mesin._KODE, "aktif", True)        # dipulihkan otomatis sesudah uji
    for k in ("ringkasan_penjualan", "buat_laporan"):
        monkeypatch.delitem(ab._DAFTAR, k, raising=False)
    ab.muat_semua_alat()
    for nama, a in list(ab._DAFTAR.items()):
        if a.kode:
            monkeypatch.delitem(ab._DAFTAR, nama)
    ab.alat(name=NAMA_KODE, kind="read", label="Membaca data uji", description="Data uji (hanya uji).",
            input_schema={"type": "object", "properties": {}}, domain="umum", kode=True)(_alat_uji)
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
    yield {"db": fm.FakeDB(), "fake": fk.FakeAsyncAnthropic(jeda=0)}
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
        raise AssertionError("tidak ada ctx.api di uji ini")

    async def aclose(self):
        pass


async def _kirim(env, sesi_id, teks, *, klien=None, lampiran=None):
    db = env["db"]
    sesi = await simpan.ambil_sesi(db, OWNER["id"], sesi_id)
    jalan, galat = await mesin.siapkan_jalan(
        db=db, user=OWNER, sesi=sesi, teks=teks, cv="DA", periode="2026-11", today=HARI_UJI, token="tok-uji",
        app=None, klien=klien or env["fake"], klien_api=lambda: FakeHttp(), lampiran=lampiran)
    if galat:
        return None, [("galat", galat)]
    task = mesin.mulai(jalan)
    chunks = [c async for c in mesin.aliran_sse(jalan)]
    await task
    return jalan, _sse(chunks)


def _tanpa_kode(kw: dict) -> bool:
    teks = json.dumps({"tools": kw.get("tools"), "messages": kw.get("messages")}, ensure_ascii=False)
    return "container" not in kw and not any(k in teks for k in KATA_KODE)


# ═══ (a) 400 menyebut allowed_callers → saklar mati, diulang tanpa ruang hitung ═══
def test_galat_400_ruang_hitung_mematikan_kode_dan_diulang_sekali_tanpa_ruang_hitung(env):
    f = env["fake"]

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        await _kirim(env, sid, "hitung dengan kode rekapnya")              # riwayat: blok kode + caller + kontainer
        d1 = await lmp.unggah(env["db"], OWNER, "data.csv", CSV)
        await _kirim(env, sid, "Baca lampiran ini", lampiran=[d1["id"]])   # riwayat: container_upload
        f.tolak_kode = True
        n = len(f.panggilan)
        d2 = await lmp.unggah(env["db"], OWNER, "baru.csv", CSV)
        jalan, ev = await _kirim(env, sid, "Bandingkan keduanya", lampiran=[d2["id"]])
        status = await mesin.status_siap()
        n2 = len(f.panggilan)
        _j3, ev3 = await _kirim(env, sid, "Lanjutkan")                      # jawaban baru: tanpa ruang hitung sejak awal
        return sid, n, n2, jalan, ev, ev3, status
    sid, n, n2, jalan, ev, ev3, status = run(_uji())
    p = f.panggilan[n:n2]
    # permintaan pertama ditolak (masih membawa ruang hitung), diulang SEKALI tanpa ruang hitung, lalu lanjut biasa
    assert not _tanpa_kode(p[0]) and len(p) >= 2 and all(_tanpa_kode(x) for x in p[1:])
    assert mesin._KODE["aktif"] is False and mesin.kode_aktif() is False and jalan.kode is False
    assert status["kode_aktif"] is False
    assert ev[0][0] == "mulai" and ev[-1][0] == "selesai" and not any(e == "galat" for e, _ in ev)
    nama = [x["name"] for x in p[1]["tools"]]
    assert "code_execution" not in nama and NAMA_KODE in nama
    alat_uji = next(x for x in p[1]["tools"] if x["name"] == NAMA_KODE)
    assert "allowed_callers" not in alat_uji and "eager_input_streaming" not in alat_uji
    # giliran ini: container_upload → ringkasan lampiran + catatan ruang hitung mati di akhir giliran
    msgs = p[1]["messages"]
    giliran = msgs[jalan._idx_giliran]["content"]
    assert giliran[-1]["text"] == pr.TEKS_KODE_MATI
    assert any(b["type"] == "text" and b["text"].startswith("<lampiran>Lampiran tabel baru.csv:") for b in giliran)
    # riwayat lama: container_upload diganti teks, blok kode dibuang, caller kode dibuang
    teks = json.dumps(msgs, ensure_ascii=False)
    assert "Lampiran tabel data.csv:" in teks and "Keluaran perhitungan dengan kode sebelumnya" in teks
    # riwayat tersimpan TETAP apa adanya (append-only): giliran pengguna masih membawa container_upload
    pu = [d for d in env["db"].ai_chat_messages.docs if d["peran"] == "user"]
    assert any(b.get("type") == "container_upload" for b in pu[2]["api"][0]["content"])
    assert any(b.get("type") == "container_upload" for b in pu[1]["api"][0]["content"])
    # jawaban berikutnya langsung tanpa ruang hitung: tidak ada permintaan yang ditolak lagi
    p3 = f.panggilan[n2:]
    assert ev3[-1][0] == "selesai" and p3 and all(_tanpa_kode(x) for x in p3)
    assert pr.TEKS_KODE_MATI in json.dumps(pu[3]["api"][0]["content"], ensure_ascii=False)


# ═══ (b) env "0" → ruang hitung tidak pernah dikirim ═════════════════════════
def test_env_kode_mati_tidak_pernah_memancarkan_alat_kode(env, monkeypatch):
    monkeypatch.setenv("ASISTEN_AI_KODE_AKTIF", "0")
    f = fk.FakeAsyncAnthropic(jeda=0, tolak_kode=True)

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        d1 = await lmp.unggah(env["db"], OWNER, "data.csv", CSV)
        d2 = await lmp.unggah(env["db"], OWNER, "laporan.pdf", _pdf())
        jalan, ev = await _kirim(env, sid, "hitung dengan kode lampiran ini", klien=f, lampiran=[d1["id"], d2["id"]])
        return jalan, ev, await mesin.status_siap()
    jalan, ev, status = run(_uji())
    assert ev[-1][0] == "selesai" and not any(e == "galat" for e, _ in ev)
    assert f.panggilan and all(_tanpa_kode(x) for x in f.panggilan)
    assert mesin.kode_aktif() is False and mesin._KODE["aktif"] is True and status["kode_aktif"] is False
    isi = f.panggilan[0]["messages"][-1]["content"]
    assert isi[1]["text"] == pr.TEKS_KODE_MATI
    ringkas = next(b["text"] for b in isi if b["type"] == "text" and b["text"].startswith("<lampiran>"))
    assert "hanya cuplikan" in ringkas
    assert [b["type"] for b in isi if b["type"] != "text"] == ["document"]        # PDF tetap dibaca langsung
    lamp = {d["nama"]: d for d in env["db"].ai_lampiran.docs}
    assert "file_id_anthropic" not in lamp["data.csv"] and lamp["laporan.pdf"]["file_id_anthropic"]
    assert len(f.files.diunggah) == 1
    a = ab.tools_untuk_api(kode=False)
    assert not any("allowed_callers" in x for x in a) and "code_execution" not in json.dumps(a)
    assert "eager_input_streaming" not in next(x for x in a if x["name"] == NAMA_KODE)


# ═══ (c) 400 lain tidak mematikan saklar ═════════════════════════════════════
def _skrip_galat(pesan: str, *, kode_dulu: bool = False):
    def skrip(k):
        if kode_dulu and k.giliran_asisten == 0:
            sid = fk._bid("srvtoolu")
            return ([{"type": "server_tool_use", "id": sid, "name": "code_execution", "input": {}},
                     {**fk._alat(NAMA_KODE, {}), "caller": {"type": "code_execution_20260120", "tool_id": sid}}],
                    "tool_use", {"kontainer": True})
        raise fk.FakeAPIError(400, pesan)
    return skrip


def test_galat_400_tak_terkait_tidak_mematikan_kode(env):
    f = fk.FakeAsyncAnthropic(skrip=_skrip_galat("max_tokens: 64000 > 32000, which is the maximum allowed"), jeda=0)

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        return await _kirim(env, sid, "halo", klien=f)
    _j, ev = run(_uji())
    assert mesin._KODE["aktif"] is True and mesin.kode_aktif() is True
    assert len(f.panggilan) == 1 and ev[-1] == ("galat", {"kode": "permintaan_ditolak",
                                                          "pesan": mesin.PESAN_GALAT["permintaan_ditolak"]})


def test_galat_400_saat_kode_tertunda_tidak_diulang_tanpa_ruang_hitung(env):
    f = fk.FakeAsyncAnthropic(skrip=_skrip_galat("messages.2: invalid tool_result for caller", kode_dulu=True), jeda=0)

    async def _uji():
        sid = (await simpan.buat_sesi(env["db"], OWNER["id"]))["id"]
        return await _kirim(env, sid, "hitung", klien=f)
    _j, ev = run(_uji())
    assert mesin._KODE["aktif"] is True and len(f.panggilan) == 2
    assert any(e == "galat" for e, _ in ev)


# ═══ Fungsi transformasi ════════════════════════════════════════════════════
def test_tanpa_ruang_hitung_salinan_sah_untuk_satu_permintaan():
    asli = [
        {"role": "user", "content": "pertanyaan lama"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "x", "signature": "s"},
            {"type": "server_tool_use", "id": "srv1", "name": "code_execution", "input": {}},
            {"type": "tool_use", "id": "tu1", "name": NAMA_KODE, "input": {},
             "caller": {"type": "code_execution_20260120", "tool_id": "srv1"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "[]"}]},
        {"role": "assistant", "content": [
            {"type": "code_execution_tool_result", "tool_use_id": "srv1",
             "content": {"type": "code_execution_result", "stdout": "Total 3", "stderr": "", "return_code": 0,
                         "content": []}},
            {"type": "text", "text": "Selesai."}]},
        {"role": "user", "content": [{"type": "text", "text": "q"}, {"type": "container_upload", "file_id": "f1"}]},
    ]
    salinan = json.loads(json.dumps(asli))
    out, berubah = mesin.tanpa_ruang_hitung(asli, {"f1": {"nama": "a.csv", "jenis": "tabel", "ringkas": "CSV",
                                                         "ringkasan_model": "a | b"}}, sisip_catatan=4)
    assert asli == salinan and berubah                     # masukan tidak diubah
    teks = json.dumps(out, ensure_ascii=False)
    assert not any(k in teks for k in KATA_KODE) and '"caller"' not in teks
    assert out[0] == asli[0] and out[2] == asli[2]
    assert out[3]["content"][0]["text"] == "(Keluaran perhitungan dengan kode sebelumnya: Total 3)"
    assert out[4]["content"][1]["text"].startswith("<lampiran>Lampiran tabel a.csv: CSV") and "a | b" in teks
    assert out[4]["content"][-1]["text"] == pr.TEKS_KODE_MATI
    # tanpa blok kode di riwayat → giliran asisten tidak berubah (thinking tetap)
    out2, berubah2 = mesin.tanpa_ruang_hitung(asli[:1], {})
    assert out2 == asli[:1] and not berubah2
    assert "Lampiran berkas data" in lmp.teks_pengganti(None)
