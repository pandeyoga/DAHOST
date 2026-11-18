"""Uji unit HERMETIK — laporan bulanan .xls mesin absen (18 Nov 2026, owner: berkas 001_2026_10_MON.XLS →
"Bisa diimpor di SDM").

Bentuk sheet "Log" disalin dari berkas nyata (nama diganti): baris "Periode : 2026/10/01 ~ 10/25", lalu per
karyawan tiga baris — deret tanggal 1.0 … 25.0 (angka float dari xlrd), "No : 2 · Nama : ADMIN 2 · Dept : Office",
dan sel jam "14:22\\n". Pembacaan .xls (xlrd) sendiri tidak diuji di sini — fungsi murninya yang diuji.

Jalankan:  cd backend && python -m pytest tests/unit/test_absen_xls_mesin.py -q
"""
import asyncio
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402
from core import fingerprint_import as fi  # noqa: E402

E = ""


def _blok(no, nama, hari, jam_per_kolom):
    kepala = [float(d) for d in hari]
    ident = ["No :", E, str(no), E, E, E, E, E, "Nama :", E, nama] + [E] * 7 + ["Dept :", E, "Office"] + [E] * 4
    jam = [jam_per_kolom.get(i, E) for i in range(len(hari))]
    return [kepala, ident, jam]


def _sheet(periode, hari, blok):
    rows = [["Data Log"] + [E] * 24, [E] * 25, ["Periode :", E, periode] + [E] * 22]
    for b in blok:
        rows += _blok(b[0], b[1], hari, b[2])
    return rows


def test_log_laporan_mesin_jadi_tabel_ketukan():
    hari = list(range(1, 26))
    rows = _sheet("2026/10/01 ~ 10/25", hari, [
        (1, "ADMIN", {}),
        (2, "ADMIN 2", {0: "14:22\n"}),
        (4, "Edy", {0: "07:59\n17:02\n", 13: "12:32\n"}),
    ])
    out = fi.log_report_rows(rows)
    assert out[0] == fi.LOG_HEADER
    assert out[1:] == [["2", "ADMIN 2", datetime(2026, 10, 1, 14, 22)],
                       ["4", "Edy", datetime(2026, 10, 1, 7, 59)],
                       ["4", "Edy", datetime(2026, 10, 1, 17, 2)],
                       ["4", "Edy", datetime(2026, 10, 14, 12, 32)]]
    header, body = fi.split_header(out, 0)
    punches, bad = fi.extract_punches(header, body, {"code": "No. ID", "datetime": "Waktu"})
    assert bad == 0 and [p["code"] for p in punches] == ["2", "4", "4", "4"]


def test_periode_lintas_bulan_tanggal_kolom_benar():
    hari = list(range(26, 32)) + list(range(1, 26))          # 26 Okt … 31 Okt, 1 Nov … 25 Nov
    rows = _sheet("2026/10/26 ~ 11/25", hari, [(7, "Pandu", {0: "08:00\n", 6: "08:05\n", 30: "16:00\n"})])
    tgl = [r[2] for r in fi.log_report_rows(rows)[1:]]
    assert tgl == [datetime(2026, 10, 26, 8, 0), datetime(2026, 11, 1, 8, 5), datetime(2026, 11, 25, 16, 0)]


def test_bukan_laporan_mesin_kosong():
    assert fi.log_report_rows([["No", "Nama", "Waktu"], ["1", "A", "2026-10-01 08:00"]]) == []


def test_nama_di_mesin_untuk_id_yang_belum_terhubung():
    from routes import rahaza_auto_attendance_zkteco as z
    names = z._names_by_code(fi.LOG_HEADER, [["007", "Pandu", None], ["2", "ADMIN 2", None]], {"code": "No. ID"})
    assert names == {fi._norm_code("007"): "Pandu", "2": "ADMIN 2"}
    assert z._names_by_code(["PIN", "Waktu"], [["1", "x"]], {"code": "PIN"}) == {}


def test_hubungkan_id_mesin_ke_karyawan(monkeypatch):
    from routes import rahaza_auto_attendance_zkteco as z
    db = fm.FakeDB()
    db.rahaza_employees.docs += [{"id": "e1", "name": "Edy"}, {"id": "e2", "name": "Pandu", "zkteco_user_id": "7"}]

    async def auth(req):
        return {"id": "hr", "name": "HR", "role": "superadmin"}
    monkeypatch.setattr(z, "require_auth", auth)
    monkeypatch.setattr(z, "_require_fp", lambda u: None)
    monkeypatch.setattr(z, "get_db", lambda: db)

    async def log(*a, **k):
        return None
    monkeypatch.setattr(z, "log_activity", log)
    out = asyncio.run(z.fingerprint_link(fm.FakeRequest({"links": [
        {"code": "4", "employee_id": "e1"}, {"code": "7", "employee_id": "e1"}, {"code": "9", "employee_id": "x"}]})))
    assert out["linked"] == 1 and db.rahaza_employees.docs[0]["zkteco_user_id"] == "4"
    assert any("sudah dipakai Pandu" in e for e in out["errors"]) and any("tidak ditemukan" in e for e in out["errors"])
    lookup = asyncio.run(fi.employee_lookup(db))
    assert lookup["4"]["id"] == "e1"
