"""Asisten AI, Tahap A (agen laporan) — 7 Nov 2026. Uji HERMETIK: Mongo palsu, ctx palsu, penyimpanan palsu.

Cakupan:
  1. validasi spesifikasi laporan (batas, pesan galat Indonesia);
  2. PDF jadi dan berhalaman (PyPDF2), teks Rupiah gaya Indonesia, kop Gabungan;
  3. Excel: lembar Ringkasan + lembar tabel + lembar grafik, format angka, teks "=..." tidak jadi rumus;
  4. grafik setiap jenis (batang, batang_horizontal, garis, area, pai) tergambar;
  5. hak unduh: pembuat & owner 200, pengguna lain 403;
  6. alat `buat_laporan` menyimpan berkas + metadata dan mengirim event `laporan`;
  7. alat baca memanggil endpoint yang benar dengan parameter CV/periode yang benar;
  8. aturan gaji & nama (K27, keputusan owner 1);
  9. perbaikan privasi: estimasi maklon tanpa nama klien, narasi eksekutif tanpa nominal gaji, regex "payroll".

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_asisten_ai_laporan.py -n 0 -q
"""
import asyncio
import copy
import io
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402
from core import laporan_ai as la  # noqa: E402
from core.asisten_ai import alat_base  # noqa: E402
from core.asisten_ai.alat_base import AlatError  # noqa: E402
from core.asisten_ai.alat import keuangan, laporan, produksi, sdm, stok  # noqa: E402,F401

# Daftar alat kerangka inti (`_DAFTAR`: nama → Alat) dalam bentuk {"handler": …} yang dipakai uji ini.
REGISTRY = {n: {"handler": a.handler, "kind": a.kind, "domain": a.domain, "label": a.label, "description": a.description,
                "input_schema": a.input_schema} for n, a in alat_base._DAFTAR.items()}

NAMA_KARYAWAN = "Karyawan Uji Satu"
NAMA_KLIEN = "Klien Uji Sentosa"
TODAY = date(2026, 11, 7)


def run(c):
    return asyncio.run(c)


class FakeCtx:
    """AlatContext palsu: merekam setiap panggilan `api` dan menjawab dari kamus path → respons."""

    def __init__(self, responses=None, *, role="owner", cv="DA", db=None, uid="u-pembuat"):
        self.responses = responses or {}
        self.calls = []
        self.user = {"id": uid, "role": role, "name": "Pengguna Uji"}
        self.cv = cv
        self.today = TODAY
        self.db = db
        self.events = []
        self.masked = 0

    async def api(self, method, path, params=None, json=None):
        self.calls.append((method, path, dict(params or {})))
        r = self.responses.get(path)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(params or {})
        if r is None:
            raise AlatError(404, "Data tidak ditemukan.")
        return copy.deepcopy(r)

    def emit(self, event, data):
        self.events.append((event, data))

    def mask(self, obj):
        self.masked += 1
        return obj

    def paths(self):
        return [c[1] for c in self.calls]


def spec_contoh(fmt=("pdf", "xlsx")):
    x = ["Toko A", "Toko B", "Toko C"]
    return {
        "judul": "Laporan Omzet Oktober 2026",
        "subjudul": "UJI-ASA-laporan",
        "periode_label": "Oktober 2026",
        "format": list(fmt),
        "bagian": [
            {"judul": "Ringkasan", "teks": "## Sorotan\nOmzet **naik 12%**.\n\n- poin satu\n- poin dua\n\n1. langkah"},
            {"judul": "Omzet per toko",
             "tabel": {"kolom": ["Toko", "Omzet (Rp)", "Pesanan", "Porsi %"],
                       "baris": [["Toko A", 142300000, 1200, 45.5], ["Toko B", 98000000, 800, 31.0],
                                 ["=1+1", 75500000, 600, 23.5]],
                       "catatan": "Omzet tanpa pesanan batal."},
             "grafik": {"jenis": "batang", "judul": "Omzet", "satuan": "Rp", "x": x,
                        "seri": [{"nama": "Okt", "nilai": [142300000, 98000000, 75500000]},
                                 {"nama": "Sep", "nilai": [120000000, 90000000, None]}]}},
        ],
    }


# ═══ 1. Validasi spesifikasi ═════════════════════════════════════════════════
def test_validasi_spek_bentuk_baku():
    s = la.validasi_spek({**spec_contoh(), "format": ["Excel", "pdf", "pdf"]})
    assert s["format"] == ["pdf", "xlsx"]
    assert s["bagian"][1]["tabel"]["baris"][0] == ["Toko A", 142300000, 1200, 45.5]
    assert s["bagian"][1]["grafik"]["seri"][1]["nilai"][2] is None
    # format kosong → pdf; baris pendek dilengkapi sel kosong
    s2 = la.validasi_spek({"judul": "X", "bagian": [{"tabel": {"kolom": ["A", "B"], "baris": [["satu"]]}}]})
    assert s2["format"] == ["pdf"] and s2["bagian"][0]["tabel"]["baris"] == [["satu", ""]]


@pytest.mark.parametrize("ubah, potongan", [
    (lambda s: s.pop("judul"), "Judul laporan wajib"),
    (lambda s: s.update(format=["docx"]), "tidak dikenal"),
    (lambda s: s.update(bagian=[]), "minimal satu bagian"),
    (lambda s: s.update(bagian=[{"judul": "kosong"}]), "kosong"),
    (lambda s: s.update(bagian=[{"teks": "a"}] * 31), "paling banyak 30 bagian"),
    (lambda s: s.update(bagian=[{"table": {}}]), "tidak dikenal"),
    (lambda s: s.update(lain=1), "tidak dikenal"),
    (lambda s: s["bagian"][1]["tabel"]["baris"].append([1, 2, 3, 4, 5]), "hanya ada 4 kolom"),
    (lambda s: s["bagian"][1]["tabel"].update(baris=[["a", 1, 1, 1]] * 301), "paling banyak 300 baris"),
    (lambda s: s["bagian"][1]["tabel"]["baris"].append(["x", float("nan"), 1, 1]), "angka biasa"),
    (lambda s: s["bagian"][1]["tabel"]["baris"].append(["x", {"a": 1}, 1, 1]), "teks atau angka"),
    (lambda s: s["bagian"][0].update(teks="a" * 6001), "terlalu panjang"),
    (lambda s: s["bagian"][1]["grafik"].update(jenis="donat"), "jenis harus"),
    (lambda s: s["bagian"][1]["grafik"].update(x=[str(i) for i in range(32)]), "31 titik"),
    (lambda s: s["bagian"][1]["grafik"]["seri"].extend([{"nama": "c", "nilai": [1, 2, 3]}] * 3), "4 seri"),
    (lambda s: s["bagian"][1]["grafik"]["seri"][0].update(nilai=[1, 2]), "sama dengan jumlah label"),
    (lambda s: s["bagian"][1]["grafik"]["seri"][0].update(nilai=["1", 2, 3]), "harus angka"),
    (lambda s: s["bagian"][1]["grafik"].update(jenis="pai"), "tepat satu seri"),
])
def test_validasi_spek_menolak_dengan_pesan_indonesia(ubah, potongan):
    s = spec_contoh()
    ubah(s)
    with pytest.raises(la.SpekLaporanError) as e:
        la.validasi_spek(s)
    assert potongan in e.value.pesan


def test_validasi_grafik_pai():
    ok = la.validasi_grafik({"jenis": "pai", "x": ["a", "b"], "seri": [{"nama": "s", "nilai": [3, 1]}]})
    assert ok["jenis"] == "pai"
    for nilai in ([1, -1], [0, 0], [1, None]):
        with pytest.raises(la.SpekLaporanError):
            la.validasi_grafik({"jenis": "pai", "x": ["a", "b"], "seri": [{"nama": "s", "nilai": nilai}]})


def test_format_angka_indonesia():
    assert la.format_rupiah(1500000) == "Rp 1.500.000"
    assert la.format_rupiah(-2500.4) == "-Rp 2.500"
    assert la.format_angka(1234.5) == "1.234,5" and la.format_angka(1000) == "1.000"
    assert la.format_persen(12.5) == "12,5%"
    assert la.singkat(1_250_000_000, "Rp") == "Rp 1,25 M" and la.singkat(750_000, "pcs") == "750.000"
    assert la.jenis_kolom("Omzet (Rp)", [1, 2]) == "rp" and la.jenis_kolom("Porsi %", [1.5]) == "persen"
    assert la.jenis_kolom("Pesanan", [3]) == "angka" and la.jenis_kolom("Toko", ["a"]) == "teks"
    assert la.jenis_kolom("Pesanan", [3], "Rp") == "rp"
    assert la.teks_pdf("≥ 5 → ok 😀") == ">= 5 -> ok "


def test_markdown_sederhana():
    blok = la.urai_markdown("# Judul\nbaris satu\nbaris dua\n\n- a\n- b\n1. x\n2) y")
    assert blok == [("judul", 1, "Judul"), ("paragraf", "baris satu baris dua"), ("poin", ["a", "b"]),
                    ("nomor", ["x", "y"])]
    assert la.inline_pdf("**tebal** <script> *miring*") == "<b>tebal</b> &lt;script&gt; <i>miring</i>"


# ═══ 2. PDF ══════════════════════════════════════════════════════════════════
def _teks_pdf(data: bytes) -> tuple:
    from PyPDF2 import PdfReader
    r = PdfReader(io.BytesIO(data))
    return len(r.pages), "\n".join(p.extract_text() or "" for p in r.pages)


def test_pdf_jadi_berhalaman_dan_angka_indonesia():
    s = la.validasi_spek(spec_contoh())
    data = la.buat_pdf(s, la.kop_bawaan("DA"), pembuat="Pengguna Uji")
    assert data[:5] == b"%PDF-"
    n, teks = _teks_pdf(data)
    assert n >= 1
    assert "Laporan Omzet Oktober 2026" in teks and "Rp 142.300.000" in teks and "45,5%" in teks
    assert "CV. Dewi Aditya" in teks and "Halaman 1" in teks and "WIB" in teks


def test_pdf_kop_gabungan_netral():
    s = la.validasi_spek(spec_contoh(("pdf",)))
    _, teks = _teks_pdf(la.buat_pdf(s, la.kop_bawaan("ALL")))
    assert "CV Dewi Aditya & CV Sukma" in teks and "Gabungan" in teks


def test_pdf_tabel_panjang_berpindah_halaman():
    s = la.validasi_spek({"judul": "Panjang", "bagian": [
        {"judul": "Data", "tabel": {"kolom": ["No", "Nilai (Rp)"], "baris": [[i, i * 1000] for i in range(300)]}}]})
    n, teks = _teks_pdf(la.buat_pdf(s, la.kop_bawaan("SMU")))
    assert n >= 4 and "Rp 299.000" in teks


@pytest.mark.parametrize("cv, nama", [("DA", "Profil DA Uji"), ("SMU", "Profil Sukma Uji")])
def test_kop_dari_template_dan_profil_cv(cv, nama):
    db = FakeDB()
    db.company_settings.docs = [{"type": "general", "company_name": "Profil DA Uji"},
                                {"type": "cv_profile", "entity": "SMU", "company_name": "Profil Sukma Uji"}]
    kop = run(la.siapkan_kop(db, cv))
    assert kop["cv"] == cv and kop["header"]["show"] is True
    s = la.validasi_spek(spec_contoh(("pdf",)))
    _, teks = _teks_pdf(la.buat_pdf(s, kop))
    assert nama in teks
    if cv == "SMU":   # kop CV Sukma tidak pernah memakai nama DA
        assert "Profil DA Uji" not in teks


# ═══ 3. Excel ════════════════════════════════════════════════════════════════
def test_excel_lembar_dan_format_angka():
    from openpyxl import load_workbook
    s = la.validasi_spek(spec_contoh())
    wb = load_workbook(io.BytesIO(la.buat_xlsx(s, la.kop_bawaan("DA"), pembuat="Pengguna Uji")))
    assert wb.sheetnames[0] == "Ringkasan"
    assert "Omzet per toko" in wb.sheetnames and any(n.startswith("Grafik") for n in wb.sheetnames)
    ws = wb["Omzet per toko"]
    assert [c.value for c in ws[1]] == ["Toko", "Omzet (Rp)", "Pesanan", "Porsi %"]
    assert ws["B2"].value == 142300000 and ws["B2"].number_format == la.FMT_RP
    assert ws["C2"].number_format == la.FMT_BULAT and ws["D2"].number_format == la.FMT_PERSEN
    assert ws["A4"].value == "=1+1" and ws["A4"].data_type == "s"      # teks, bukan rumus
    assert ws.freeze_panes == "A2"
    ringkas = "\n".join(str(c.value) for c in wb["Ringkasan"]["A"] if c.value)
    assert "Laporan Omzet Oktober 2026" in ringkas and "• poin satu" in ringkas and "**" not in ringkas
    wg = wb[[n for n in wb.sheetnames if n.startswith("Grafik")][0]]
    assert wg["B1"].value == "Okt" and len(wg._charts) == 1


def test_nama_lembar_unik_dan_sah():
    pakai = {"ringkasan"}
    assert la._nama_lembar("Omzet: Okt/Sep?", pakai) == "Omzet  Okt Sep"
    assert la._nama_lembar("Ringkasan", pakai) == "Ringkasan 2"
    assert len(la._nama_lembar("x" * 50, pakai)) <= 31


# ═══ 4. Grafik setiap jenis ══════════════════════════════════════════════════
@pytest.mark.parametrize("jenis", la.JENIS_GRAFIK)
def test_grafik_setiap_jenis_tergambar(jenis):
    from reportlab.graphics import renderPDF
    seri = [{"nama": "Okt", "nilai": [5, 3, 0, 2]}]
    if jenis != "pai":
        seri.append({"nama": "Sep", "nilai": [4, None, 1, 2]})
    g = la.validasi_grafik({"jenis": jenis, "judul": "Uji", "satuan": "Rp", "x": ["a", "b", "c", "d"], "seri": seri})
    d = la.gambar_grafik(g, lebar=500)
    assert d.width == 500 and d.height > 0 and d.contents
    assert renderPDF.drawToString(d)[:5] == b"%PDF-"


def test_grafik_pai_lebih_dari_delapan_digabung_lainnya():
    g = la.validasi_grafik({"jenis": "pai", "x": [f"T{i}" for i in range(10)] + ["Lainnya"],
                            "seri": [{"nama": "s", "nilai": list(range(10, 0, -1)) + [5]}]})
    d = la.gambar_grafik(g)
    pie = next(c for c in d.contents if c.__class__.__name__ == "Pie")
    assert len(pie.data) == 8 and sum(pie.data) == sum(range(1, 11)) + 5


# ═══ 5 & 6. Simpan, alat buat_laporan, hak unduh ═════════════════════════════
@pytest.fixture
def simpanan(monkeypatch):
    berkas = {}

    def put(path, data, ctype):
        berkas[path] = (data, ctype)
        return {"path": path, "size": len(data)}
    import object_storage
    monkeypatch.setattr(object_storage, "put_object", put)
    return berkas


def test_alat_buat_laporan_menyimpan_dan_mengirim_event(simpanan):
    db = FakeDB()
    ctx = FakeCtx(db=db, cv="SMU")
    hasil = run(REGISTRY["buat_laporan"]["handler"](ctx, spec_contoh()))
    assert hasil["judul"] == "Laporan Omzet Oktober 2026" and [b["format"] for b in hasil["berkas"]] == ["pdf", "xlsx"]
    lid = hasil["laporan_id"]
    ev = hasil["_ui_events"]
    assert [e["event"] for e in ev] == ["laporan", "laporan"]
    assert ev[0]["data"] == {"id": lid, "judul": hasil["judul"], "format": "pdf",
                             "url": f"/api/asisten-ai/laporan/{lid}?format=pdf"}
    doc = db.ai_reports.docs[0]
    assert doc["dibuat_oleh"] == "u-pembuat" and doc["cv"] == "SMU" and doc["spec"]["judul"] == hasil["judul"]
    assert all(b["path"].startswith(f"ai_reports/{lid}/") for b in doc["berkas"])
    assert all(p in simpanan for p in (b["path"] for b in doc["berkas"]))
    assert simpanan[doc["berkas"][0]["path"]][0][:5] == b"%PDF-"
    # path acak tidak pernah dikirim ke model / layar
    assert "ai_reports/" not in json.dumps({k: v for k, v in hasil.items()})


def test_alat_buat_laporan_spek_salah_jadi_alat_error(simpanan):
    ctx = FakeCtx(db=FakeDB())
    with pytest.raises(AlatError) as e:
        run(REGISTRY["buat_laporan"]["handler"](ctx, {"judul": "x", "format": ["pdf"], "bagian": []}))
    assert e.value.status == 400 and "Isi laporan belum benar" in e.value.pesan


@pytest.fixture
def klien_unduh(monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    import routes.asisten_ai_laporan_routes as rt

    db = FakeDB()
    db.ai_reports.docs = [{"id": "lap-1", "judul": "Uji", "dibuat_oleh": "u-pembuat", "cv": "DA",
                           "berkas": [{"format": "pdf", "path": "ai_reports/lap-1/a.pdf", "nama_berkas": "Uji-20261107.pdf"},
                                      {"format": "xlsx", "path": "ai_reports/lap-1/b.xlsx", "nama_berkas": "Uji.xlsx"}]}]
    pengguna = {"owner": {"id": "u-owner", "role": "owner"}, "pembuat": {"id": "u-pembuat", "role": "manager"},
                "lain": {"id": "u-lain", "role": "manager"}, "admin": {"id": "u-admin", "role": "admin"}}

    async def fake_auth(request):
        u = pengguna.get(request.headers.get("x-uji"))
        if not u:
            raise HTTPException(401, "Unauthorized")
        return dict(u)
    monkeypatch.setattr(rt, "require_auth", fake_auth)
    monkeypatch.setattr(rt, "get_db", lambda: db)
    monkeypatch.setattr(rt, "_ambil_berkas", lambda p: (b"%PDF-1.4 uji", "application/pdf") if p.endswith(".pdf")
                        else ((b"PK uji", "x") if p.endswith("b.xlsx") else None))
    app = FastAPI()
    app.include_router(rt.router)
    return TestClient(app)


def test_unduh_pemilik_dan_owner_boleh_lainnya_403(klien_unduh):
    c = klien_unduh
    r = c.get("/api/asisten-ai/laporan/lap-1?format=pdf", headers={"x-uji": "pembuat"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "private, no-store"
    assert c.get("/api/asisten-ai/laporan/lap-1?format=xlsx", headers={"x-uji": "owner"}).status_code == 200
    r = c.get("/api/asisten-ai/laporan/lap-1?format=pdf", headers={"x-uji": "lain"})
    assert r.status_code == 403 and "pengguna lain" in r.json()["detail"]
    # admin biasa BUKAN owner/superadmin → tidak boleh membuka laporan orang lain
    assert c.get("/api/asisten-ai/laporan/lap-1", headers={"x-uji": "admin"}).status_code == 403
    assert c.get("/api/asisten-ai/laporan/lap-1").status_code == 401
    assert c.get("/api/asisten-ai/laporan/tidak-ada", headers={"x-uji": "owner"}).status_code == 404
    assert c.get("/api/asisten-ai/laporan/lap-1?format=docx", headers={"x-uji": "owner"}).status_code == 422


def test_boleh_unduh_aturan():
    doc = {"dibuat_oleh": "u1"}
    assert la.boleh_unduh({"id": "u1", "role": "staff"}, doc)
    assert la.boleh_unduh({"id": "x", "role": "superadmin"}, doc)
    assert not la.boleh_unduh({"id": "x", "role": "manager"}, doc)
    assert not la.boleh_unduh({"id": None, "role": "staff"}, {"dibuat_oleh": None})


def test_server_mendaftarkan_rute_unduh_dengan_gerbang_management():
    src = (BACKEND / "server.py").read_text(encoding="utf-8")
    blok = src[src.index("# ── Asisten AI (laporan)"):src.index("# ── akhir Asisten AI (laporan)")]
    assert "asisten_ai_laporan_router" in blok and '_require_portal_dep("management")' in blok


def test_koleksi_ai_reports_terdaftar_sebagai_log():
    from core import collection_registry as cr
    assert cr.is_registered("ai_reports") and cr.kind_of("ai_reports") == "log"


# ═══ 7. Alat baca: endpoint & parameter ══════════════════════════════════════
def _lr(pend, hpp, beban):
    return {"totals": {"revenue": pend, "cogs": hpp, "gross_profit": pend - hpp, "expense": beban,
                       "operating_income": pend - hpp - beban, "other_income": 0, "other_expense": 0,
                       "net_income": pend - hpp - beban},
            "groups": {"revenue": {"accounts": [{"code": "4-1100", "name": "Penjualan", "amount": pend}]},
                       "cogs": {"accounts": [{"code": "5-1000", "name": "HPP", "amount": hpp}]},
                       "expense": {"accounts": [{"code": "6-1000", "name": "Beban", "amount": beban}]}}}


def test_laba_rugi_bulan_berjalan_dibanding_tanggal_sama_bulan_lalu():
    ctx = FakeCtx({keuangan.P_LABA_RUGI: lambda p: _lr(100e6 if p["from"] == "2026-11-01" else 80e6, 60e6, 10e6)})
    h = run(REGISTRY["laba_rugi"]["handler"](ctx, {}))
    assert ctx.calls == [("GET", keuangan.P_LABA_RUGI, {"entity": "DA", "from": "2026-11-01", "to": "2026-11-07"}),
                         ("GET", keuangan.P_LABA_RUGI, {"entity": "DA", "from": "2026-10-01", "to": "2026-10-07"})]
    assert h["ringkas"]["pendapatan"] == 100_000_000 and h["ringkas"]["laba_bersih"] == 30_000_000
    assert h["perubahan"]["pendapatan"] == {"selisih": 20_000_000, "persen": 25.0}
    assert h["ringkas"]["margin_kotor_pct"] == 40.0 and h["akun_terbesar"]["pendapatan"][0]["pembanding"] == 80_000_000


def test_laba_rugi_bulan_lampau_penuh_dan_gabungan_per_cv():
    ctx = FakeCtx({keuangan.P_LABA_RUGI: _lr(10, 5, 1)}, cv="ALL")
    h = run(REGISTRY["laba_rugi"]["handler"](ctx, {"bulan": "2026-02"}))
    assert ctx.calls[0][2] == {"entity": "ALL", "from": "2026-02-01", "to": "2026-02-28"}
    assert ctx.calls[1][2] == {"entity": "ALL", "from": "2026-01-01", "to": "2026-01-31"}
    assert [c[2]["entity"] for c in ctx.calls[2:]] == ["DA", "SMU"]
    assert set(h["per_cv"]) == {"CV Dewi Aditya", "CV Sukma"} and h["periode"] == "Februari 2026"


@pytest.mark.parametrize("args, pesan", [({"bulan": "2026-13"}, "TTTT-BB"), ({"bulan": "2027-01"}, "belum dimulai"),
                                         ({"dari": "2026-10-01"}, "bersamaan"),
                                         ({"dari": "2026-10-05", "sampai": "2026-10-01"}, "sebelum")])
def test_periode_salah_ditolak(args, pesan):
    with pytest.raises(AlatError) as e:
        run(REGISTRY["arus_kas"]["handler"](FakeCtx({}), args))
    assert e.value.status == 400 and pesan in e.value.pesan


def test_neraca_arus_kas_kas_bank():
    ctx = FakeCtx({
        keuangan.P_NERACA: {"totals": {"assets": 500, "liabilities": 200, "equity": 300, "liab_plus_equity": 500,
                                       "current_earnings": 50, "diff": 0}, "balanced": True,
                            "assets": {"accounts": [{"code": "1-1101", "name": "Kas", "amount": 100},
                                                    {"code": "1-1401", "name": "Bahan", "amount": 400}]},
                            "liabilities": {"accounts": [{"code": "2-1100", "name": "Hutang", "amount": 200}]},
                            "equity": {"accounts": []}},
        keuangan.P_ARUS_KAS: {"totals": {"operating": 10, "investing": -5, "financing": 0, "net_change_in_cash": 5,
                                         "opening_cash": 100, "closing_cash": 105},
                              "activities": {"operating": {"items": [{"label": "Penjualan", "inflow": 10, "outflow": 0,
                                                                      "net": 10}]}}},
        keuangan.P_REKENING: [{"name": "BCA Uji", "type": "bank", "bank_name": "BCA", "account_number": "1234567890",
                               "entity": "SMU", "balance": 2500000.4}],
    }, cv="SMU")
    n = run(REGISTRY["neraca_ringkas"]["handler"](ctx, {"per_tanggal": "2026-10-31"}))
    assert ctx.calls[-1] == ("GET", keuangan.P_NERACA, {"entity": "SMU", "as_of": "2026-10-31"})
    assert {"kelompok": "Persediaan", "nilai": 400} in n["aset_per_kelompok"] and n["seimbang"] is True
    a = run(REGISTRY["arus_kas"]["handler"](ctx, {"dari": "2026-10-01", "sampai": "2026-10-31"}))
    assert ctx.calls[-1][2] == {"entity": "SMU", "from": "2026-10-01", "to": "2026-10-31"}
    assert a["ringkas"]["kas_akhir"] == 105 and a["rincian"]["operasi"][0]["kategori"] == "Penjualan"
    k = run(REGISTRY["posisi_kas_bank"]["handler"](ctx, {}))
    assert ctx.calls[-1] == ("GET", keuangan.P_REKENING, {"entity": "SMU"})
    assert k["total"] == 2500000 and "1234567890" not in json.dumps(k)


def test_umur_piutang_hutang_tanpa_nama_pihak():
    ctx = FakeCtx({
        keuangan.P_PIUTANG: {"buckets": {"current": 100, "90_plus": 50}, "total": 150, "count": 2,
                             "details": [{"invoice_number": "INV-1", "customer_name": NAMA_KLIEN, "amount_due": 50,
                                          "days_overdue": 120, "due_date": "2026-07-01"},
                                         {"invoice_number": "INV-2", "customer_name": NAMA_KLIEN, "amount_due": 100,
                                          "days_overdue": 0}]},
        keuangan.P_HUTANG: {"buckets": {"1_30": 70}, "total": 70, "details": [
            {"number": "AP-1", "vendor_name": "Pemasok Uji", "balance": 70, "days_overdue": 10}],
            "unposted": [{}], "unposted_total": 30},
    })
    p = run(REGISTRY["umur_piutang"]["handler"](ctx, {}))
    assert ctx.calls[-1] == ("GET", keuangan.P_PIUTANG, {"entity": "DA"})
    assert NAMA_KLIEN not in json.dumps(p) and p["pihak_terbesar"] == [
        {"pihak": "PLG-001", "sisa": 150, "jumlah_faktur": 2, "telat_terlama_hari": 120}]
    assert p["faktur_terlama"][0]["nomor"] == "INV-1" and p["jatuh_tempo_lewat"] == 50
    h = run(REGISTRY["umur_hutang"]["handler"](ctx, {}))
    assert "Pemasok Uji" not in json.dumps(h) and h["pihak_terbesar"][0]["pihak"] == "VND-001"
    assert h["belum_dijurnal"]["nilai"] == 30


def test_stok_ringkasan_menipis_nilai():
    items = [{"code": "K1", "name": "Kain", "type": "fabric", "unit": "kg", "onhand": 10, "unit_cost": 50000,
              "status": "low"},
             {"code": "A1", "name": "Kancing", "type": "accessory", "unit": "pcs", "onhand": 100, "unit_cost": 0,
              "status": "ok"},
             {"code": "F1", "name": "Kaos", "type": "fg", "unit": "pcs", "onhand": -2, "unit_cost": 30000,
              "status": "critical"}]
    ctx = FakeCtx({
        stok.P_AMBANG: {"items": items, "summary": {"with_threshold": 2, "missing_threshold": 1, "low": 1, "critical": 1}},
        stok.P_MENIPIS: [{"code": "F1", "name": "Kaos", "type": "fg", "unit": "pcs", "current_qty": -2,
                          "alert_at": 5, "shortage": 7, "stock_status": "critical"}],
        stok.P_AMBANG_RINGKAS: {"missing_threshold": 1},
        stok.P_NERACA: {"assets": {"accounts": [{"code": "1-1402", "name": "Persediaan Aks", "amount": 900},
                                                {"code": "1-1404", "name": "Persediaan FG", "amount": 1100},
                                                {"code": "1-1101", "name": "Kas", "amount": 5}]}},
        stok.P_NILAI_AKSESORIS: {"totals": {"total_value": 1000, "valued_items": 3, "unvalued_items": 1}},
        stok.P_NILAI_FG: AlatError(403, "Anda tidak punya akses ke Portal Keuangan."),
    })
    r = run(REGISTRY["ringkasan_stok"]["handler"](ctx, {"kategori": "bahan", "cari": "kain"}))
    assert ctx.calls[-1] == ("GET", stok.P_AMBANG, {"limit": 5000, "type": "bahan", "search": "kain"})
    bahan = r["per_kategori"][0]
    assert bahan["kategori"] == "Bahan baku" and bahan["perkiraan_nilai"] == 500000 and bahan["di_bawah_ambang"] == 1
    assert r["per_kategori"][1]["item_tanpa_harga"] == 1 and r["per_kategori"][2]["stok_minus"] == 1
    m = run(REGISTRY["stok_menipis"]["handler"](ctx, {}))
    assert m["kritis"] == 1 and m["daftar"][0]["kurang"] == 7 and m["item_tanpa_ambang"] == 1
    n = run(REGISTRY["nilai_persediaan"]["handler"](ctx, {"per_tanggal": "2026-10-31"}))
    assert ("GET", stok.P_NERACA, {"entity": "DA", "as_of": "2026-10-31"}) in ctx.calls
    assert n["total_buku_besar"] == 2000 and n["buku_pembantu"]["aksesoris"]["selisih_vs_buku_besar"] == 100
    assert n["buku_pembantu"]["barang_jadi"] == {"galat": "Anda tidak punya akses ke Portal Keuangan."}


def _pantau(bt):
    return {"as_of": "2026-11-07", "kpi": {"po_berjalan": 2, "telat": 1}, "totals": {"accepted": 5},
            "alur": [{"label": "Di vendor CMT", "qty": 10, "docs": 1, "doc_label": "vendor"}],
            "balance": {"all_ok": True, "checks": []},
            "overdue": [{"po_number": f"PO-{bt}", "vendor_name": "Vendor CMT Uji", "customer_name": NAMA_KLIEN,
                         "risk": "telat", "days_to_deadline": -3, "progress_pct": 40}],
            "upcoming": [], "done": {}, "jobs": {}, "duplicate_serials": {"count": 0}, "biaya": {"ongkos_jahit": 9.6}}


@pytest.mark.parametrize("cv, jenis", [("DA", ["internal"]), ("SMU", ["maklon"]), ("ALL", ["internal", "maklon"])])
def test_pantau_produksi_mengikuti_cv(cv, jenis):
    ctx = FakeCtx({produksi.P_PANTAU: lambda p: _pantau(p["business_type"])}, cv=cv)
    h = run(REGISTRY["pantau_produksi_ringkas"]["handler"](ctx, {"hari": 14}))
    assert [c[2] for c in ctx.calls] == [{"business_type": j, "days": 14} for j in jenis]
    teks = json.dumps(h)
    assert "Vendor CMT Uji" not in teks and NAMA_KLIEN not in teks and "VND-001" in teks
    assert h[jenis[0]]["po_telat_atau_berisiko"][0]["po"] == f"PO-{jenis[0]}"


def test_hpp_per_po_daftar_dan_rincian():
    items = [{"po_id": "p1", "po_number": "PO-1", "business_type": "maklon", "vendor_name": "Vendor Uji",
              "client_name": NAMA_KLIEN, "total_hpp": 1000, "qty_accepted": 10, "hpp_per_pcs": 100, "revenue": 1500,
              "margin": 500, "margin_pct": 33.3, "cut_cost": 600, "accessory_cost": 100, "cmt_cost": 300,
              "permak_cost": 0}]
    ctx = FakeCtx({produksi.P_HPP: {"items": items, "summary": {"po_count": 1, "total_hpp": 1000, "qty_accepted": 10,
                                                                "hpp_per_pcs": 100, "revenue": 1500, "margin": 500,
                                                                "margin_pct": 33.3},
                                    "overhead": {"month": "2026-11", "overhead": 0, "pcs": 0, "per_pcs": None}},
                   f"{produksi.P_HPP}/p1": {**items[0], "components": [{"label": "Potongan", "amount": 600,
                                                                         "per_pcs": 60}], "gaps": []}}, cv="SMU")
    h = run(REGISTRY["hpp_per_po"]["handler"](ctx, {"nomor_po": "po-1", "status": "open"}))
    assert ctx.calls[0] == ("GET", produksi.P_HPP, {"business_type": "maklon", "per_page": 100, "page": 1,
                                                     "status": "open", "search": "po-1"})
    assert ctx.calls[1][1] == f"{produksi.P_HPP}/p1"
    assert h["ringkas"]["margin_maklon"] == 500 and h["rincian_po"]["komponen_per_pcs"][0]["per_pcs"] == 60
    assert NAMA_KLIEN not in json.dumps(h)
    with pytest.raises(AlatError):
        run(REGISTRY["hpp_per_po"]["handler"](ctx, {"nomor_po": "PO-404"}))


# ═══ 8. Aturan gaji & nama karyawan ══════════════════════════════════════════
def _respons_sdm():
    return {
        sdm.P_DASBOR: {"total_employees": 20, "dept_breakdown": [{"dept": "Jahit", "count": 15}],
                       "attendance_today": {"hadir": 18, "alfa": 1, "not_recorded": 1, "attendance_rate": 90.0},
                       "alfa_last_7d": 3, "latest_payroll_run": {"total_net": 99_000_000},
                       "recent_attendance": [{"employee_name": NAMA_KARYAWAN}]},
        sdm.P_PERGANTIAN: {"aggregates": {"new_hires_count": 1, "resignations_count": 0, "turnover_rate": 0}},
        sdm.P_GAJI: {"aggregates": {"total_employees": 20, "total_gross": 60_000_000, "total_deductions": 1_000_000,
                                    "total_net": 59_000_000},
                     "summary": [{"employee_name": NAMA_KARYAWAN, "net_salary": 4_321_000}],
                     "period": {"period_code": "2026-10", "run_id": "run-1"}},
        sdm.P_ABSENSI: {"aggregates": {"total_employees": 2, "total_alfa": 3, "avg_attendance_rate": 91.5},
                        "summary": [{"employee_name": NAMA_KARYAWAN, "department_name": "Jahit", "alfa": 3,
                                     "attendance_rate": 80.0, "late": 1}],
                        "chart_data": [{"date": "2026-11-03", "hadir": 1, "alfa": 1}]},
        sdm.P_CUTI: {"total": 2, "items": [{"status": "approved", "leave_type_name": "Cuti tahunan", "duration_days": 2},
                                           {"status": "pending_hr_approval", "leave_type_id": "lt1"}]},
        sdm.P_JENIS_CUTI: [{"id": "lt1", "name": "Sakit"}],
        sdm.P_LEMBUR: {"aggregates": {"total_ot_hours": 12, "total_employees_with_ot": 1, "avg_ot_per_emp": 12},
                       "summary": [{"employee_name": NAMA_KARYAWAN, "department_name": "Jahit", "total_ot_hours": 12,
                                    "ot_days": 3}]},
    }


@pytest.mark.parametrize("role", ["owner", "superadmin", "hr"])
def test_sdm_penuh_total_gaji_tanpa_per_orang(role):
    ctx = FakeCtx(_respons_sdm(), role=role)
    h = run(REGISTRY["jumlah_karyawan"]["handler"](ctx, {}))
    assert sdm.P_GAJI in ctx.paths()
    assert h["biaya_tenaga_kerja_terakhir"] == {"periode": "2026-10", "karyawan_dibayar": 20, "bruto": 60_000_000,
                                                "potongan": 1_000_000, "neto": 59_000_000}
    teks = json.dumps(h)
    assert "4321000" not in teks and "99000000" not in teks and NAMA_KARYAWAN not in teks
    a = run(REGISTRY["ringkasan_absensi"]["handler"](ctx, {}))
    assert a["alfa_terbanyak"][0]["karyawan"] == NAMA_KARYAWAN and ctx.masked == 0


@pytest.mark.parametrize("role", ["manager", "staff_keuangan", "admin"])
def test_sdm_bukan_hr_tanpa_gaji_dan_nama_disamarkan(role):
    ctx = FakeCtx(_respons_sdm(), role=role)
    h = run(REGISTRY["jumlah_karyawan"]["handler"](ctx, {}))
    assert sdm.P_GAJI not in ctx.paths() and "biaya_tenaga_kerja_terakhir" not in h
    assert "99000000" not in json.dumps(h)
    a = run(REGISTRY["ringkasan_absensi"]["handler"](ctx, {"bulan": "2026-10"}))
    assert ctx.calls[-1][2] == {"from_date": "2026-10-01", "to_date": "2026-10-31"}
    assert a["alfa_terbanyak"][0]["karyawan"] == "KRY-001" and NAMA_KARYAWAN not in json.dumps(a)
    c = run(REGISTRY["cuti_dan_lembur"]["handler"](ctx, {}))
    assert NAMA_KARYAWAN not in json.dumps(c) and c["lembur"]["jam_terbanyak"][0]["karyawan"] == "KRY-001"
    assert c["cuti"]["menunggu_persetujuan"] == 1 and c["cuti"]["total_hari_disetujui"] == 2
    assert {"jenis": "Sakit", "pengajuan": 1, "hari_disetujui": 0} in c["cuti"]["per_jenis"]
    assert ctx.masked >= 3


def test_sdm_lembur_tanpa_akses_tidak_menggagalkan_alat():
    r = _respons_sdm()
    r[sdm.P_LEMBUR] = AlatError(403, "Butuh akses SDM.")
    c = run(REGISTRY["cuti_dan_lembur"]["handler"](FakeCtx(r, role="hr"), {}))
    assert c["lembur"] == {"galat": "Butuh akses SDM."} and c["cuti"]["jumlah_pengajuan"] == 2


# ═══ Kontrak A: pendaftaran & ukuran hasil ═══════════════════════════════════
ALAT_AGEN = {"buat_laporan": "laporan", "laba_rugi": "keuangan", "neraca_ringkas": "keuangan", "arus_kas": "keuangan",
             "posisi_kas_bank": "keuangan", "umur_piutang": "keuangan", "umur_hutang": "keuangan",
             "ringkasan_stok": "stok", "stok_menipis": "stok", "nilai_persediaan": "stok",
             "pantau_produksi_ringkas": "produksi", "hpp_per_po": "produksi", "jumlah_karyawan": "sdm",
             "ringkasan_absensi": "sdm", "cuti_dan_lembur": "sdm"}


def test_semua_alat_terdaftar_baca_dengan_skema_tertutup():
    for nama, domain in ALAT_AGEN.items():
        a = REGISTRY[nama]
        assert a["kind"] == "read" and a["domain"] == domain and a["label"] and len(a["description"]) > 80
        assert a["input_schema"]["type"] == "object" and a["input_schema"]["additionalProperties"] is False


def test_hasil_besar_dipangkas_di_bawah_15rb_karakter():
    rows = [{"name": f"Rekening panjang nomor {i} " + "x" * 80, "type": "bank", "balance": i} for i in range(400)]
    h = run(REGISTRY["posisi_kas_bank"]["handler"](FakeCtx({keuangan.P_REKENING: rows}), {}))
    assert len(json.dumps(h, ensure_ascii=False)) <= 15000 and h["jumlah_rekening"] == 400
    items = [{"code": f"K{i}", "name": "Barang " + "y" * 60, "type": "fabric", "unit": "kg", "onhand": 1,
              "unit_cost": i} for i in range(3000)]
    s = run(REGISTRY["ringkasan_stok"]["handler"](FakeCtx({stok.P_AMBANG: {"items": items}}), {}))
    assert len(json.dumps(s, ensure_ascii=False)) <= 15000 and len(s["item_nilai_terbesar"]) == 10


# ═══ 9. Perbaikan privasi ════════════════════════════════════════════════════
def test_estimasi_maklon_tidak_mengirim_nama_klien():
    from routes.dewi_maklon_quote import QuoteRequestIn, quote_prompt_body
    p = QuoteRequestIn(product_name=f"Kaos {NAMA_KLIEN}", quantity=100, client_name=NAMA_KLIEN,
                       client_id="c1", additional_notes=f"Hubungi {NAMA_KLIEN} di 0812-3456-7890")
    teks = quote_prompt_body(p)
    assert NAMA_KLIEN not in teks and "Client:" not in teks and "[KLIEN]" in teks
    assert "0812-3456-7890" not in teks and "Quantity: 100" in teks


def test_estimasi_maklon_prompt_lengkap_lewat_llm_palsu(monkeypatch):
    import ai_cost_tracker
    import routes.dewi_maklon_quote as mq
    kirim = {}

    async def ai_available():
        return True

    async def tracked_llm_call(**kw):
        kirim.update(kw)
        from types import SimpleNamespace
        return SimpleNamespace(over_budget=False, success=False, error="uji", text="", cost_usd=0, latency_ms=0)
    monkeypatch.setattr(ai_cost_tracker, "ai_available", ai_available)
    monkeypatch.setattr(ai_cost_tracker, "tracked_llm_call", tracked_llm_call)
    p = mq.QuoteRequestIn(product_name="Kemeja", quantity=50, client_name=NAMA_KLIEN)
    run(mq._generate_ai_quote(p, user_id="u1"))
    assert kirim["feature"] == "maklon-ai-quote" and NAMA_KLIEN not in kirim["user_message"]
    assert NAMA_KLIEN not in kirim["system_message"]


def test_narasi_eksekutif_tanpa_nominal_gaji():
    from routes.dewi_executive_report import metrics_for_ai
    metrics = {"periode": "2026-10", "keuangan": {"revenue_rp": 1},
               "sdm": {"total_active_employees": 20, "payroll_total_rp": 123_456_789}}
    teks = metrics_for_ai(metrics)
    assert "123456789" not in teks and "payroll" not in teks
    assert json.loads(teks)["sdm"]["kisaran_biaya_tenaga_kerja"] == "Rp 100 juta–150 juta"
    assert metrics["sdm"]["payroll_total_rp"] == 123_456_789          # respons layar tidak berubah
    assert "kisaran_biaya_tenaga_kerja" not in json.loads(metrics_for_ai({"sdm": {"payroll_total_rp": 0}}))["sdm"]


def test_regex_gaji_mencakup_payroll_dan_kisaran():
    from services.ai import privacy as pv
    for k in ("payroll_total_rp", "total_payroll", "Payroll-Net"):
        assert pv.is_sensitive_key(k)
    assert not pv.is_sensitive_key("kisaran_biaya_tenaga_kerja")
    assert pv.strip_sensitive({"sdm": {"payroll_total_rp": 5, "hadir": 1}}) == {"sdm": {"hadir": 1}}
    assert pv.rupiah_band(7_800_000) == "Rp 7,5 juta–8 juta"
    assert pv.rupiah_band(980_000_000) == "Rp 950 juta–1 miliar"
    assert pv.rupiah_band(0) == "Rp 0" and pv.rupiah_band("x") == "tidak diketahui"


def test_sdm_owner_tanpa_run_gaji_diberi_catatan_bukan_nol():
    r = _respons_sdm()
    r[sdm.P_GAJI] = {"summary": [], "aggregates": {"total_employees": 0}, "period": None}
    h = run(REGISTRY["jumlah_karyawan"]["handler"](FakeCtx(r, role="owner"), {}))
    assert h["biaya_tenaga_kerja_terakhir"] == {"catatan": "Belum ada penggajian yang sudah final."}


def test_berkas_laporan_di_penyimpanan_wajib_login():
    from core import sensitive_files as sf
    assert sf.has_sensitive_prefix("ai_reports/lap-1/abc.pdf") and sf.has_sensitive_prefix("./ai_reports/x.xlsx")


def _lr_dengan_gaji():
    d = _lr(100, 40, 30)
    d["groups"]["expense"]["accounts"] = [{"code": "6-1100", "name": "Gaji Pimpinan / Direksi", "amount": 12},
                                          {"code": "6-1200", "name": "Tunjangan Karyawan", "amount": 8},
                                          {"code": "6-3000", "name": "Biaya Iklan", "amount": 10}]
    return d


@pytest.mark.parametrize("role, gabungan", [("owner", True), ("hr", True), ("manager", False),
                                            ("staff_keuangan", False)])
def test_akun_gaji_tidak_pernah_dirinci_per_akun(role, gabungan):
    ctx = FakeCtx({keuangan.P_LABA_RUGI: _lr_dengan_gaji(),
                   keuangan.P_ARUS_KAS: {"totals": {}, "activities": {"operating": {"items": [
                       {"label": "Pembayaran gaji", "inflow": 0, "outflow": 20, "net": -20},
                       {"label": "Penjualan", "inflow": 50, "outflow": 0, "net": 50}]}}},
                   keuangan.P_NERACA: {"totals": {}, "liabilities": {"accounts": [
                       {"code": "2-1200", "name": "Hutang Gaji & Upah", "amount": 7},
                       {"code": "2-1100", "name": "Hutang Usaha", "amount": 9}]}}}, role=role)
    lr = run(REGISTRY["laba_rugi"]["handler"](ctx, {"bandingkan": False}))
    ak = run(REGISTRY["arus_kas"]["handler"](ctx, {}))
    nr = run(REGISTRY["neraca_ringkas"]["handler"](ctx, {}))
    teks = json.dumps([lr, ak, nr])
    for nama in ("Gaji Pimpinan", "Tunjangan Karyawan", "Pembayaran gaji", "Hutang Gaji"):
        assert nama not in teks
    beban = lr["akun_terbesar"]["beban_operasional"]
    if gabungan:
        assert {"kode": "-", "akun": "Gaji & tunjangan karyawan (gabungan)", "nilai": 20} in beban
        assert {"kategori": "Gaji & tunjangan karyawan (gabungan)", "masuk": 0, "keluar": 20, "bersih": -20} \
            in ak["rincian"]["operasi"]
        assert "catatan_gaji" not in lr
    else:
        assert beban == [{"kode": "6-3000", "akun": "Biaya Iklan", "nilai": 10}]
        assert [r["kategori"] for r in ak["rincian"]["operasi"]] == ["Penjualan"]
        assert [r["akun"] for r in nr["liabilitas_terbesar"]] == ["Hutang Usaha"]
        assert "hanya owner dan SDM" in lr["catatan_gaji"] and "catatan_gaji" in ak and "catatan_gaji" in nr
    assert lr["ringkas"]["beban_operasional"] == 30          # total kelompok tetap utuh


def test_contoh_laporan_mode_uji_sah_dan_jadi_berkas():
    """Mode uji (ASISTEN_AI_FAKE) memanggil buat_laporan dengan spesifikasi contoh: harus lolos validasi."""
    from core.asisten_ai import fake
    spek = la.validasi_spek(fake._laporan_contoh("2026-11"))
    assert spek["format"] == ["pdf", "xlsx"] and len(spek["bagian"]) == 3
