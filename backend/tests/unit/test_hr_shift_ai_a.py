"""Uji HERMETIK agen SHIFT-AI — Tahap A audit HR 9 Nov 2026 (butir 6, 7, 9). FakeDB in-memory.

  A6 (H7/P5)  · jadwal otomatis mencari karyawan `active: true` (dulu `status: "active"` → selalu 0 karyawan);
                pesan galat bahasa Indonesia.
  A7 (M10)    · penugasan shift SEMENTARA tidak menghapus penugasan tetap: penugasan lama dipotong sebelum masa
                sementara dan dilanjutkan sesudahnya; penugasan yang tidak beririsan tidak disentuh.
  A9 (P6)     · prediksi keluar: hitungan cuti 6 bulan memakai `from_date` (teks) — dulu `created_at` datetime
                dibandingkan teks (selalu 0); semua karyawan dianalisis per kelompok (dulu 10 pertama saja).
"""
import asyncio
import json
import os
import sys

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402


def run(c):
    return asyncio.run(c)


HR = {"id": "u-hr", "name": "HR Uji", "role": "hr"}
SHIFTS = [
    {"id": "sh-pagi", "code": "PAGI", "shift_code": "PAGI", "name": "Pagi", "shift_name": "Pagi",
     "start_time": "07:00", "end_time": "15:00", "active": True, "status": "active", "color": "#f59e0b"},
    {"id": "sh-siang", "code": "SIANG", "shift_code": "SIANG", "name": "Siang", "shift_name": "Siang",
     "start_time": "15:00", "end_time": "23:00", "active": True, "status": "active", "color": "#3b82f6"},
]


@pytest.fixture
def svc(monkeypatch):
    import services.hr_shift_service as hs
    db = FakeDB()
    db.rahaza_shifts.docs = [dict(s) for s in SHIFTS]
    db.rahaza_employees.docs = [{"id": "e1", "employee_code": "K01", "name": "Karyawan Satu", "active": True,
                                 "department": "Produksi"}]
    n = {"v": 0}

    async def ctr(_db, _key, **k):
        n["v"] += 1
        return n["v"]
    monkeypatch.setattr(hs, "next_counter", ctr)
    return hs, db


def _aktif(db):
    return sorted(((a["effective_from"], a.get("effective_until"), a["shift_id"])
                   for a in db.hr_shift_assignments.docs if a["status"] == "active"), key=lambda x: x[0])


class TestPenugasanSementara:
    def test_sementara_tidak_menghapus_tetap(self, svc):
        hs, db = svc
        run(hs.assign_shift(db, "e1", "sh-pagi", "2026-11-01", None, "HR"))
        run(hs.assign_shift(db, "e1", "sh-siang", "2026-11-10", "2026-11-15", "HR"))
        assert _aktif(db) == [("2026-11-01", "2026-11-09", "sh-pagi"),
                              ("2026-11-10", "2026-11-15", "sh-siang"),
                              ("2026-11-16", None, "sh-pagi")]
        assert run(hs.get_employee_shift(db, "e1", "2026-11-05"))["id"] == "sh-pagi"
        assert run(hs.get_employee_shift(db, "e1", "2026-11-12"))["id"] == "sh-siang"
        # dulu: sesudah masa sementara karyawan jatuh ke shift cadangan
        assert run(hs.get_employee_shift(db, "e1", "2026-11-20"))["id"] == "sh-pagi"

    def test_mulai_di_masa_depan_tidak_mengosongkan_hari_ini(self, svc):
        hs, db = svc
        run(hs.assign_shift(db, "e1", "sh-pagi", "2026-10-01", None, "HR"))
        run(hs.assign_shift(db, "e1", "sh-siang", "2026-12-01", None, "HR"))
        assert _aktif(db) == [("2026-10-01", "2026-11-30", "sh-pagi"), ("2026-12-01", None, "sh-siang")]
        assert run(hs.get_employee_shift(db, "e1", "2026-11-09"))["id"] == "sh-pagi"

    def test_tumpang_penuh_diganti(self, svc):
        hs, db = svc
        run(hs.assign_shift(db, "e1", "sh-pagi", "2026-11-10", "2026-11-12", "HR"))
        run(hs.assign_shift(db, "e1", "sh-siang", "2026-11-01", None, "HR"))
        assert _aktif(db) == [("2026-11-01", None, "sh-siang")]
        assert [a["status"] for a in db.hr_shift_assignments.docs if a["shift_id"] == "sh-pagi"] == ["superseded"]

    def test_tidak_beririsan_dibiarkan(self, svc):
        hs, db = svc
        run(hs.assign_shift(db, "e1", "sh-pagi", "2026-11-01", "2026-11-05", "HR"))
        run(hs.assign_shift(db, "e1", "sh-siang", "2026-11-10", "2026-11-12", "HR"))
        assert _aktif(db) == [("2026-11-01", "2026-11-05", "sh-pagi"), ("2026-11-10", "2026-11-12", "sh-siang")]

    def test_lanjutan_menyimpan_shift_dan_asal(self, svc):
        hs, db = svc
        run(hs.assign_shift(db, "e1", "sh-pagi", "2026-11-01", "2026-11-30", "HR"))
        run(hs.assign_shift(db, "e1", "sh-siang", "2026-11-10", "2026-11-12", "HR"))
        lanj = [a for a in db.hr_shift_assignments.docs if a.get("lanjutan_dari")]
        assert len(lanj) == 1 and lanj[0]["effective_from"] == "2026-11-13" and lanj[0]["effective_until"] == "2026-11-30"
        assert lanj[0]["shift_id"] == "sh-pagi" and lanj[0]["id"] != lanj[0]["lanjutan_dari"]


class TestPrediksiKeluar:
    @pytest.fixture
    def ai(self, monkeypatch):
        import routes.dewi_hr_ai as m
        db = FakeDB()
        db.rahaza_employees.docs = [{"id": f"e{i}", "name": f"Karyawan {i}", "active": True, "department": "Produksi"}
                                    for i in range(45)]
        from datetime import datetime, timedelta, timezone
        baru = (datetime.now(timezone.utc) - timedelta(days=20))
        db.rahaza_leave_requests.docs = [
            # datetime asli seperti data `create_leave_request` — dulu tidak pernah cocok dengan teks ISO
            {"id": "l1", "employee_id": "e0", "from_date": baru.strftime("%Y-%m-%d"), "status": "approved",
             "created_at": baru},
            {"id": "l2", "employee_id": "e0", "from_date": baru.strftime("%Y-%m-%d"), "status": "cancelled",
             "created_at": baru},
        ]
        panggil = []

        async def call(system, user_msg, tag, uid=None):
            rows = json.loads(user_msg.split(":\n", 1)[1])
            panggil.append(rows)
            return json.dumps({"employees": [{"ref": r["ref"], "risk_level": "low", "risk_score": 10} for r in rows],
                               "priority_actions": ["Cek jadwal"], "overall_insights": "Aman"})

        async def auth(_r):
            return HR
        monkeypatch.setattr(m, "get_db", lambda: db)
        monkeypatch.setattr(m, "require_auth", auth)
        monkeypatch.setattr(m, "_call_ai", call)
        return m, db, panggil

    def test_semua_karyawan_per_kelompok(self, ai):
        m, db, panggil = ai
        out = run(m.predict_attrition(FakeRequest(), department=None))
        assert [len(p) for p in panggil] == [40, 5]          # dulu: hanya 10 pertama
        emps = out["data"]["analysis"]["employees"]
        assert len(emps) == 45 and {e["employee_id"] for e in emps} == {f"e{i}" for i in range(45)}
        assert out["data"]["analysis"]["priority_actions"] == ["Cek jadwal"]

    def test_hitung_cuti_enam_bulan(self, ai):
        m, db, panggil = ai
        run(m.predict_attrition(FakeRequest(), department=None))
        semua = {r["ref"]: r for p in panggil for r in p}
        # e0 (KRY pertama) punya 1 cuti sah + 1 dibatalkan → 1
        assert sorted(r["leave_requests_6m"] for r in semua.values())[-1] == 1
        assert sum(r["leave_requests_6m"] for r in semua.values()) == 1

    def test_batches(self):
        import routes.dewi_hr_ai as m
        assert m.batches(list(range(5)), 2) == [[0, 1], [2, 3], [4]]
        assert m.batches([], 3) == []


class TestJadwalOtomatisFilter:
    def test_karyawan_active_true_ditemukan(self):
        """Penjadwal (kini `core.shift_roster.karyawan_lingkup`, Tahap C) memakai `active` ≠ false."""
        from core.shift_roster import karyawan_lingkup
        db = FakeDB()
        db.rahaza_employees.docs = [{"id": "e1", "name": "Satu", "active": True, "department": "Produksi"},
                                    {"id": "e2", "name": "Dua", "active": False, "department": "Produksi"},
                                    {"id": "e3", "name": "Tiga", "department": "Produksi", "status": "x"}]
        assert [e["id"] for e in run(karyawan_lingkup(db, departemen="Produksi"))] == ["e1", "e3"]
