"""Uji HERMETIK agen SHIFT-AI — Tahap D audit HR 9 Nov 2026 (AI SDM lewat Asisten AI). FakeDB in-memory.

  * ruang Asisten AI: umum (Portal Manajemen) · sdm (Portal SDM) · saya (Portal Saya) — alat di luar ruang ditahan
    (tidak dikirim ke model), ruang dicek per peran di rute, riwayat & saran per ruang, konteks giliran per ruang;
  * rekap absensi & pengecualian deterministik (lupa pulang, terlambat biasa / hari libur / cuti ½ pagi, alpa padahal
    dinas, tanpa catatan, tanpa catatan padahal dinas, lembur tanpa absen) + alat bacanya (nama disamarkan non-SDM);
  * tindakan `terapkan_koreksi_absen` memakai JALUR KOREKSI YANG ADA (buat atas nama → setujui) — absensi berubah,
    tanggal yang sudah digaji final menjadi penyesuaian payroll; bukan SDM → ditolak;
  * tindakan `susun_draf_shift` → DRAF (bukan terbit), bisa dibalikkan;
  * cek payroll sebelum finalisasi: anomali deterministik; hanya PERAN_GAJI;
  * alat Portal Saya hanya data sendiri (gaji sendiri tampil);
  * kesiapan fitur AI SDM lama; skrip tiruan (ASISTEN_AI_FAKE) memakai alat SDM.
"""
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timezone

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

from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai.alat_base import AlatContext, AlatError  # noqa: E402


def run(c):
    return asyncio.run(c)


async def _noop(*a, **k):
    return None


HARI = date(2026, 11, 9)   # Senin
OWNER = {"id": "u-own", "name": "Owner", "role": "owner"}
HR = {"id": "u-hr", "name": "HR Uji", "role": "hr"}
SPV = {"id": "u-spv", "name": "Spv", "role": "supervisor"}
STAF = {"id": "u-staf", "name": "Staf", "role": "tim_packing", "employee_id": "e-ani"}
SHIFT = {"id": "sh-p", "code": "PAGI", "shift_code": "PAGI", "name": "Pagi", "shift_name": "Pagi", "start_time": "07:00",
         "end_time": "15:00", "active": True, "status": "active", "color": "#f59e0b",
         "days_active": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]}


def _utc(iso_day: str, hhmm: str) -> str:
    from utils.waktu import WIB
    h, m = (int(x) for x in hhmm.split(":"))
    d = date.fromisoformat(iso_day)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB).astimezone(timezone.utc).isoformat()


def _db():
    db = FakeDB()
    db.rahaza_shifts.docs = [dict(SHIFT)]
    db.rahaza_employees.docs = [
        {"id": "e-ani", "employee_code": "K01", "name": "Ani Contoh", "active": True, "department": "Gudang",
         "shift_id": "sh-p", "user_id": "u-staf"},
        {"id": "e-budi", "employee_code": "K02", "name": "Budi Contoh", "active": True, "department": "Gudang",
         "shift_id": "sh-p", "user_id": "u-budi"},
    ]
    db.users.docs = [{"id": "u-staf", "employee_id": "e-ani", "role": "tim_packing"},
                     {"id": "u-budi", "employee_id": "e-budi", "role": "tim_packing"}]
    db.rahaza_production_calendar.docs = [{"date": "2026-11-03", "type": "holiday", "name": "Libur uji"}]
    E = db.rahaza_attendance_events.docs
    # Senin 2 Nov: Ani masuk tanpa pulang; Budi tepat waktu
    E.append({"id": "a1", "employee_id": "e-ani", "date": "2026-11-02", "status": "hadir",
              "clock_in": _utc("2026-11-02", "07:02"), "late_minutes": 0})
    E.append({"id": "b1", "employee_id": "e-budi", "date": "2026-11-02", "status": "hadir",
              "clock_in": _utc("2026-11-02", "07:00"), "clock_out": _utc("2026-11-02", "15:00"), "late_minutes": 0})
    # Selasa 3 Nov (libur kalender): Ani lembur, tercatat terlambat 115 menit
    E.append({"id": "a2", "employee_id": "e-ani", "date": "2026-11-03", "status": "hadir",
              "clock_in": _utc("2026-11-03", "09:00"), "clock_out": _utc("2026-11-03", "12:00"), "late_minutes": 115})
    # Rabu 4 Nov: Ani terlambat biasa 30 menit; Budi tidak ada catatan
    E.append({"id": "a3", "employee_id": "e-ani", "date": "2026-11-04", "status": "hadir",
              "clock_in": _utc("2026-11-04", "07:30"), "clock_out": _utc("2026-11-04", "15:00"), "late_minutes": 25})
    # Kamis 5 Nov: Budi alpa padahal dinas; Ani cuti ½ hari pagi + terlambat 265
    E.append({"id": "b5", "employee_id": "e-budi", "date": "2026-11-05", "status": "alpa"})
    E.append({"id": "a5", "employee_id": "e-ani", "date": "2026-11-05", "status": "hadir",
              "clock_in": _utc("2026-11-05", "12:30"), "clock_out": _utc("2026-11-05", "15:00"), "late_minutes": 265})
    db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "e-ani", "status": "approved", "from_date": "2026-11-05",
                                      "to_date": "2026-11-05", "is_half_day": True, "half_day_period": "AM",
                                      "leave_kind": "cuti"}]
    # Dinas Budi 5–6 Nov (pengajuan dinas menyimpan ID AKUN)
    db.employee_travel_requests.docs = [{"id": "t1", "employee_id": "u-budi", "status": "approved",
                                         "start_date": "2026-11-05", "end_date": "2026-11-06"}]
    # Sabtu 7 Nov: pengajuan lembur Ani disetujui tanpa absen
    db.rahaza_overtime_requests.docs = [{"id": "ot1", "employee_id": "e-ani", "date": "2026-11-07", "status": "approved",
                                         "hours": 2}]
    return db


# ═══ 1. Ruang ═══════════════════════════════════════════════════════════════════════════════════════════
class TestRuang:
    def test_alat_per_ruang(self):
        sdm = {t["name"] for t in ab.tools_untuk_api(tindakan=True, kecuali=ab.alat_luar_ruang("sdm"), server=False)}
        assert {"rekap_absensi_pengecualian", "cakupan_shift", "cek_payroll_sebelum_finalisasi", "terapkan_koreksi_absen",
                "susun_draf_shift", "putuskan_cuti", "ringkasan_absensi", "cari_data", "tampilkan_tabel"} <= sdm
        assert not {"ringkasan_penjualan", "ubah_harga_jual", "laba_rugi", "absen_saya"} & sdm
        saya = {t["name"] for t in ab.tools_untuk_api(tindakan=True, kecuali=ab.alat_luar_ruang("saya"), server=False)}
        assert saya == {"absen_saya", "cuti_saya", "slip_gaji_saya", "jadwal_shift_saya", "tanggal_dan_periode",
                        "tampilkan_grafik", "tampilkan_tabel"}
        umum = {t["name"] for t in ab.tools_untuk_api(tindakan=True, server=False)}
        assert saya | sdm <= umum and ab.alat_luar_ruang("umum") == frozenset()

    def test_jalan_menahan_alat_luar_ruang_dan_konteks(self):
        from core.asisten_ai import mesin
        from core.asisten_ai import prompt as pr
        j = mesin.Jalan(db=FakeDB(), user=STAF, sesi={"id": "s1", "ruang": "saya"}, teks="halo", cv="DA",
                        periode="2026-11", today=HARI, klien=object(), tindakan_aktif=True)
        nama = {t["name"] for t in j.tools if "input_schema" in t}
        assert "cari_data" not in nama and "absen_saya" in nama and "ringkasan_penjualan" in j.alat_ditahan
        assert j.ruang == "saya"
        teks = pr.konteks_giliran(today=HARI, cv="DA", periode="2026-11", peran="tim_packing", ruang="saya")
        assert "Ruang: Portal Saya" in teks and teks.endswith("</konteks_sistem>")
        assert "Ruang:" not in pr.konteks_giliran(today=HARI, cv="DA", periode="2026-11", peran="owner")
        j2 = mesin.Jalan(db=FakeDB(), user=OWNER, sesi={"id": "s2"}, teks="x", cv="DA", periode="2026-11", today=HARI,
                         klien=object())
        assert j2.ruang == "umum" and "ringkasan_penjualan" not in j2.alat_ditahan

    def test_rute_ruang_per_peran(self, monkeypatch):
        import routes.asisten_ai_routes as r
        db = FakeDB()
        state = {"u": STAF}

        async def auth(_q):
            return dict(state["u"])
        monkeypatch.setattr(r, "require_auth", auth)
        monkeypatch.setattr(r, "get_db", lambda: db)
        assert r.ruang_diizinkan(OWNER) == ["umum", "sdm", "saya"]
        assert r.ruang_diizinkan(HR) == ["sdm", "saya"]
        assert r.ruang_diizinkan(STAF) == ["saya"]
        s = run(r.buat_sesi(FakeRequest({"judul": "Cuti saya"})))
        assert s["ruang"] == "saya"
        with pytest.raises(HTTPException) as e:
            run(r.buat_sesi(FakeRequest({"ruang": "sdm"})))
        assert e.value.status_code == 403
        state["u"] = HR
        s2 = run(r.buat_sesi(FakeRequest({})))
        assert s2["ruang"] == "sdm"
        assert [x["id"] for x in run(r.daftar_sesi(FakeRequest(), ruang="sdm"))] == [s2["id"]]
        assert run(r.daftar_sesi(FakeRequest(), ruang="saya")) == []
        with pytest.raises(HTTPException):
            run(r.buat_sesi(FakeRequest({"ruang": "umum"})))
        sar = run(r.daftar_saran(FakeRequest(), peran="hr", ruang="sdm"))
        assert any("pengecualian" in x["teks"].lower() for x in sar)
        assert any("slip" in x["teks"].lower() for x in run(r.daftar_saran(FakeRequest(), ruang="saya")))
        # percakapan Portal Manajemen milik akun yang kini tanpa akses Manajemen → 403 saat mengirim pesan
        db.ai_chat_sessions.docs.append({"id": "lama", "user_id": "u-hr", "ruang": "umum", "dihapus": False})
        with pytest.raises(HTTPException) as e:
            run(r.kirim_pesan("lama", FakeRequest({"teks": "halo"})))
        assert e.value.status_code == 403

    def test_saran_staf_hr_tanpa_payroll(self):
        from core.asisten_ai.saran import saran_untuk
        assert not any("payroll" in s["teks"].lower() for s in saran_untuk("staff_hr", "sdm"))
        assert any("payroll" in s["teks"].lower() for s in saran_untuk("hr", "sdm"))
        assert saran_untuk("owner")[0]["teks"] == "Ringkasan hari ini"   # perilaku lama tetap


# ═══ 2. Rekap absensi & pengecualian ═══════════════════════════════════════════════════════════════════
class TestPengecualian:
    def test_aturan_deterministik(self):
        from core import absensi_pengecualian as ap
        db = _db()
        out = run(ap.rekap(db, dari="2026-11-02", sampai="2026-11-07", today=HARI))
        kat = {(r["employee_id"], r["tanggal"], r["kategori"]) for r in out["pengecualian"]}
        assert ("e-ani", "2026-11-02", "lupa_absen_pulang") in kat
        assert ("e-ani", "2026-11-03", "terlambat_hari_libur") in kat
        assert ("e-ani", "2026-11-04", "terlambat") in kat
        assert ("e-ani", "2026-11-05", "terlambat_cuti_setengah") in kat
        assert ("e-budi", "2026-11-05", "alpa_padahal_dinas") in kat
        assert ("e-budi", "2026-11-06", "tanpa_catatan_dinas") in kat
        assert ("e-budi", "2026-11-04", "tanpa_catatan") in kat
        assert ("e-ani", "2026-11-07", "lembur_tanpa_absen") in kat
        # libur kalender (3 Nov) bukan "tanpa catatan"
        assert ("e-budi", "2026-11-03", "tanpa_catatan") not in kat
        sar = {(r["employee_id"], r["tanggal"]): r.get("saran_koreksi") for r in out["pengecualian"]}
        assert sar[("e-ani", "2026-11-02")] == {"clock_out": "15:00", "catatan": "Jam pulang shift PAGI"}
        assert sar[("e-budi", "2026-11-05")]["status"] == "hadir"
        assert sar[("e-ani", "2026-11-05")]["clock_in"] == "12:30"
        assert out["pengecualian"][0]["tingkat"] == "perlu_tindakan"
        assert {x["kategori"] for x in out["ringkas"]} >= {"lupa_absen_pulang", "tanpa_catatan"}

    def test_alat_baca_dan_privasi(self, monkeypatch):
        import routes.hr_absensi_pengecualian as rap
        from core.asisten_ai.alat import sdm_absensi_shift as S
        db = _db()
        state = {"u": HR}

        async def auth(_q):
            return dict(state["u"])
        monkeypatch.setattr(rap, "require_auth", auth)
        monkeypatch.setattr(rap, "get_db", lambda: db)
        monkeypatch.setattr(rap, "today_wib", lambda: HARI)

        def ctx_untuk(user):
            c = AlatContext(user=user, cv="DA", today=HARI)

            async def api(method, path, params=None, json=None, **kw):
                assert method == "GET" and path == S.P_PENGECUALIAN
                state["u"] = user
                try:
                    return await rap.pengecualian(FakeRequest(), **params)
                except HTTPException as e:
                    raise AlatError(e.status_code, e.detail)
            c.api = api
            return c
        out = run(S.rekap_absensi_pengecualian(ctx_untuk(HR), {"dari": "2026-11-02", "sampai": "2026-11-07"}))
        assert out["bisa_dikoreksi"] >= 4 and any(r["karyawan"] == "Ani Contoh" for r in out["pengecualian"])
        sp = run(S.rekap_absensi_pengecualian(ctx_untuk(SPV), {"dari": "2026-11-02", "sampai": "2026-11-07",
                                                                "kategori": ["lupa_absen_pulang"]}))
        assert [r["kategori"] for r in sp["pengecualian"]] == ["lupa_absen_pulang"]
        assert "Ani" not in json.dumps(sp) and sp["pengecualian"][0]["employee_id"] == "e-ani"
        with pytest.raises(AlatError) as e:
            run(S.rekap_absensi_pengecualian(ctx_untuk(STAF), {}))
        assert e.value.status == 403


# ═══ 3. Tindakan koreksi absen (jalur koreksi yang ada) ═══════════════════════════════════════════════
@pytest.fixture
def koreksi_env(monkeypatch):
    import routes.hr_shifts as hs
    import routes.rahaza_attendance as ra
    import routes.rahaza_attendance_corrections as rac
    from core.asisten_ai.alat import sdm_absensi_shift as S
    db = _db()
    state = {"u": HR}

    async def auth(_q):
        return dict(state["u"])
    for m in (rac, ra, hs):
        monkeypatch.setattr(m, "require_auth", auth)
        monkeypatch.setattr(m, "get_db", lambda: db)
    monkeypatch.setattr(rac, "log_activity", _noop)
    monkeypatch.setattr(rac, "notify_correction_decision", _noop)
    monkeypatch.setattr(rac, "today_wib", lambda: HARI)
    tulis = []

    def ctx_untuk(user, *, baca_saja):
        c = AlatContext(user=user, cv="DA", today=HARI, db=db, baca_saja=baca_saja)

        async def api(method, path, params=None, json=None, **kw):
            state["u"] = user
            params = params or {}
            try:
                if method != "GET":
                    if baca_saja:
                        raise AlatError(403, ab.PESAN_BACA_SAJA)
                    tulis.append((method, path))
                if method == "GET" and path == S.P_KOREKSI:
                    return await rac.list_corrections(FakeRequest(), status=params.get("status"), limit=1)
                if method == "GET" and path == S.P_ABSEN:
                    return await ra.list_attendance(FakeRequest(), date=params.get("date"),
                                                    employee_id=params.get("employee_id"), limit=1)
                if method == "GET" and path == "/api/hr/shifts/penugasan-karyawan":
                    return await hs.penugasan_per_karyawan(FakeRequest())
                if method == "POST" and path == S.P_KOREKSI:
                    return await rac.create_correction(FakeRequest(json))
                m = re.match(r"^/api/rahaza/attendance/corrections/([^/]+)/approve$", path)
                if method == "POST" and m:
                    return await rac.approve_correction(m[1], FakeRequest(json))
            except HTTPException as e:
                raise AlatError(e.status_code, e.detail if isinstance(e.detail, str) else "galat")
            raise AssertionError(f"rute tak terduga {method} {path}")
        c.api = api
        return c
    return db, S, ctx_untuk, tulis, state


class TestKoreksiAbsen:
    ARGS = {"koreksi": [{"employee_id": "e-ani", "tanggal": "2026-11-02", "jam_pulang": "15:00"},
                        {"employee_id": "e-budi", "tanggal": "2026-11-06", "status": "hadir", "catatan": "Dinas"}]}

    def test_siapkan_baca_saja_lalu_jalankan_lewat_koreksi(self, koreksi_env):
        db, S, ctx_untuk, tulis, _ = koreksi_env
        a = ab.cari_tindakan("terapkan_koreksi_absen")
        assert a.risiko == "menengah" and not a.bisa_dibalikkan and a.domain == "sdm"
        rencana = run(S.TerapkanKoreksiAbsen.siapkan(ctx_untuk(HR, baca_saja=True), self.ARGS))
        assert tulis == [] and len(rencana["perubahan"]) == 2
        assert rencana["perubahan"][0]["label"].startswith("Ani Contoh") and "pulang —" in rencana["perubahan"][0]["sebelum"]
        assert rencana["perubahan"][1]["sebelum"] == "tidak ada catatan"
        c = ctx_untuk(HR, baca_saja=False)
        c.alasan = "Dicek dengan mandor dan surat tugas"
        out = run(S.TerapkanKoreksiAbsen.jalankan(c, self.ARGS, rencana))
        assert out["hasil"]["langsung"] == 2 and out["hasil"]["gagal"] == []
        ani = next(e for e in db.rahaza_attendance_events.docs if e["id"] == "a1")
        assert ani.get("clock_out") and ani.get("correction_id")
        budi = next(e for e in db.rahaza_attendance_events.docs if e["employee_id"] == "e-budi" and e["date"] == "2026-11-06")
        assert budi["status"] == "hadir"
        kor = db.rahaza_attendance_corrections.docs
        assert len(kor) == 2 and all(k["status"] == "approved" and k["reason"].startswith("Lewat Asisten AI") for k in kor)

    def test_tanggal_final_jadi_penyesuaian_dan_bukan_sdm_ditolak(self, koreksi_env):
        db, S, ctx_untuk, tulis, _ = koreksi_env
        db.rahaza_payroll_runs.docs = [{"id": "run1", "run_number": "PR-1", "status": "finalized",
                                        "period_from": "2026-10-26", "period_to": "2026-11-25"}]
        db.rahaza_payslips.docs = [{"id": "ps1", "run_id": "run1", "employee_id": "e-ani"}]
        args = {"koreksi": [{"employee_id": "e-ani", "tanggal": "2026-11-02", "jam_pulang": "15:00"}]}
        rencana = run(S.TerapkanKoreksiAbsen.siapkan(ctx_untuk(HR, baca_saja=True), args))
        assert any("gaji final" in p for p in rencana["peringatan"])
        c = ctx_untuk(HR, baca_saja=False)
        c.alasan = "Lupa absen pulang, dicek CCTV"
        out = run(S.TerapkanKoreksiAbsen.jalankan(c, args, rencana))
        assert out["hasil"]["penyesuaian_gaji"] == 1
        assert not next(e for e in db.rahaza_attendance_events.docs if e["id"] == "a1").get("clock_out")
        with pytest.raises(AlatError) as e:
            run(S.TerapkanKoreksiAbsen.siapkan(ctx_untuk(SPV, baca_saja=True), args))
        assert e.value.status == 403

    def test_validasi_isian(self, koreksi_env):
        _db_, S, ctx_untuk, _, _ = koreksi_env
        for args, kata in (({"koreksi": [{"employee_id": "e-ani", "tanggal": "2026-11-02"}]}, "isi status"),
                           ({"koreksi": [{"employee_id": "e-ani", "tanggal": "2026-12-01", "status": "hadir"}]}, "belum terjadi"),
                           ({"koreksi": [{"employee_id": "e-ani", "tanggal": "2026-11-02", "status": "hadir"}] * 2}, "dua baris")):
            with pytest.raises(AlatError) as e:
                run(S.TerapkanKoreksiAbsen.siapkan(ctx_untuk(HR, baca_saja=True), args))
            assert kata in e.value.pesan
        errs = ab.periksa_skema(ab.cari_tindakan("terapkan_koreksi_absen").input_schema,
                                {"koreksi": [{"employee_id": "e-ani", "tanggal": "2026-11-02", "status": "cuti"}]})
        assert errs   # cuti/izin/sakit tidak lewat koreksi


# ═══ 4. Tindakan susun draf shift ══════════════════════════════════════════════════════════════════════
class TestDrafShift:
    def test_pratinjau_kartu_lalu_draf_dan_batal(self, monkeypatch):
        import routes.dewi_shift_scheduler as sch
        import routes.hr_shifts as hs
        from core.asisten_ai.alat import sdm_absensi_shift as S
        db = _db()

        async def auth(_q):
            return dict(HR)
        for m in (sch, hs):
            monkeypatch.setattr(m, "require_auth", auth)
            monkeypatch.setattr(m, "get_db", lambda: db)
        monkeypatch.setattr(sch, "log_activity", _noop)

        def ctx_untuk(baca_saja):
            c = AlatContext(user=HR, cv="DA", today=HARI, db=db, baca_saja=baca_saja)

            async def api(method, path, params=None, json=None, **kw):
                params = params or {}
                if method != "GET" and baca_saja:
                    raise AlatError(403, ab.PESAN_BACA_SAJA)
                if path == S.P_SHIFT:
                    return await hs.list_shifts(FakeRequest(), status="active", include_default=False)
                if path == S.P_PRATINJAU:
                    return await sch.pratinjau_jadwal(FakeRequest(), **params)
                if method == "POST" and path == S.P_JADWAL:
                    return await sch.buat_jadwal(FakeRequest(), sch.JadwalBaruModel(**json))
                if method == "DELETE" and path.startswith(S.P_JADWAL + "/"):
                    return await sch.delete_schedule(FakeRequest(), path.rsplit("/", 1)[1])
                raise AssertionError(path)
            c.api = api
            return c
        args = {"mulai": "2026-11-16", "selesai": "2026-11-21", "cara": "shift", "shift": "PAGI", "departemen": "Gudang"}
        rencana = run(S.SusunDrafShift.siapkan(ctx_untuk(True), args))
        assert db.rahaza_schedules.docs == []
        assert {"label": "Shift PAGI", "sebelum": "—", "sesudah": "12 hari-orang"} in rencana["perubahan"]
        assert any("DRAF" in c for c in rencana["catatan"])
        out = run(S.SusunDrafShift.jalankan(ctx_untuk(False), args, rencana))
        doc = db.rahaza_schedules.docs[0]
        assert doc["status"] == "draft" and out["hasil"]["status"] == "draf" and out["pembatalan"]["jadwal_id"] == doc["id"]
        assert all(e.get("shift_id") == "sh-p" for e in doc["shifts"])
        assert run(S.SusunDrafShift.batalkan(ctx_untuk(False), out["pembatalan"]))["ringkas"] == "Draf jadwal dihapus."
        assert db.rahaza_schedules.docs == []
        with pytest.raises(AlatError) as e:
            run(S.SusunDrafShift.siapkan(ctx_untuk(True), {**args, "shift": "MALAM"}))
        assert "tidak ditemukan" in e.value.pesan


# ═══ 5. Cek payroll ════════════════════════════════════════════════════════════════════════════════════
def _slip(eid, nama, **kw):
    s = {"employee_id": eid, "employee_name": nama, "pay_scheme": "monthly", "gross_pay": 3_000_000, "net_pay": 2_800_000,
         "deductions": [{"type": "pph21", "amount": 0}], "allowances": [], "overtime_entries": [],
         "source_refs": {"attendance_event_count": 20}, "attendance_summary": {}, "warnings": []}
    s.update(kw)
    return s


class TestPayroll:
    def test_anomali(self):
        from core.asisten_ai.alat._bantu_sdm import anomali_payroll, ringkas_anomali
        kini = [
            _slip("e1", "Ani", net_pay=-5000),
            _slip("e2", "Budi", source_refs={"attendance_event_count": 0}, attendance_summary={"tanpa_catatan": 22},
                  allowances=[{"name": "Bonus kehadiran", "forfeited": True, "rate": 100000,
                               "forfeit_reasons": ["tidak ada hari hadir"]}]),
            _slip("e3", "Cici", gross_pay=4_200_000, deductions=[{"type": "pph21", "amount": 300_000}]),
            _slip("e4", "Dedi", overtime_entries=[{"date": "2026-11-02", "hours": 6, "paid_hours": 6, "day_type": "hari kerja"},
                                                  {"date": "2026-11-03", "hours": 5, "paid_hours": 5, "day_type": "hari kerja"},
                                                  {"date": "2026-11-04", "hours": 5, "paid_hours": 5, "day_type": "hari kerja"},
                                                  {"date": "2026-11-05", "hours": 4, "paid_hours": 4, "day_type": "hari kerja"}]),
            _slip("e5", "Eka", manual_addition=6_000_000, warnings=[{"type": "attendance_missing", "message": "2 hari tanpa catatan"}]),
        ]
        lalu = [_slip("e3", "Cici", gross_pay=3_000_000, deductions=[{"type": "pph21", "amount": 45_000}])]
        a = anomali_payroll(kini, lalu)
        jenis = {(x["employee_id"], x["jenis"]) for x in a}
        assert {("e1", "gaji_minus"), ("e2", "tanpa_absen"), ("e2", "bonus_hangus_tanpa_catatan"), ("e3", "bruto_berubah"),
                ("e3", "pph21_lompat"), ("e4", "lembur_lebih_4_jam"), ("e4", "lembur_lebih_18_jam_minggu"),
                ("e5", "penyesuaian_manual"), ("e5", "peringatan_sistem")} <= jenis
        assert [x for x in a if x["jenis"] == "lembur_lebih_4_jam"].__len__() == 3
        assert a[0]["jenis"] == "gaji_minus" and ringkas_anomali(a)[0]["jumlah"] == 1

    def test_alat_hanya_peran_gaji_dan_run_draf(self):
        from core.asisten_ai.alat import sdm_absensi_shift as S
        c = AlatContext(user=SPV, cv="DA", today=HARI)
        with pytest.raises(AlatError) as e:
            run(S.cek_payroll_sebelum_finalisasi(c, {}))
        assert e.value.status == 403
        c = AlatContext(user=HR, cv="DA", today=HARI)

        async def api(method, path, params=None, json=None, **kw):
            if path == S.P_RUN:
                return [{"id": "r2", "status": "draft", "run_number": "PR-2", "period_from": "2026-11-26", "period_to": "2026-12-25"},
                        {"id": "r1", "status": "finalized", "run_number": "PR-1", "period_from": "2026-10-26", "period_to": "2026-11-25"}]
            if path == f"{S.P_RUN}/r2":
                return {"run": {"id": "r2", "status": "draft", "run_number": "PR-2", "period_from": "2026-11-26",
                                "period_to": "2026-12-25"}, "payslips": [_slip("e3", "Cici", gross_pay=4_500_000)]}
            if path == f"{S.P_RUN}/r1":
                return {"run": {"id": "r1"}, "payslips": [_slip("e3", "Cici")]}
            raise AssertionError(path)
        c.api = api
        out = run(S.cek_payroll_sebelum_finalisasi(c, {}))
        assert out["run"]["nomor"] == "PR-2" and out["pembanding"]["nomor"] == "PR-1"
        assert out["ringkas"] == [{"jenis": "bruto_berubah", "label": "Bruto berubah besar dibanding run sebelumnya", "jumlah": 1}]


# ═══ 6. Portal Saya ════════════════════════════════════════════════════════════════════════════════════
class TestDataSaya:
    def test_slip_gaji_sendiri_tampil_dan_rinci(self):
        from core.asisten_ai.alat import saya as SY
        c = AlatContext(user=STAF, cv="DA", today=HARI)
        assert not c.boleh_gaji

        async def api(method, path, params=None, json=None, **kw):
            assert path == SY.P_SLIP
            return {"payslips": [
                {"period_from": "2026-10-01", "period_to": "2026-10-31", "gross_pay": 3_100_000, "deductions_total": 100_000,
                 "net_pay": 3_000_000, "earnings": [{"label": "Gaji pokok", "amount": 3_000_000}],
                 "allowances": [{"name": "Bonus kehadiran", "amount": 0, "forfeited": True, "forfeit_reasons": ["terlambat 4 hari"]}],
                 "deductions": [{"label": "Potongan terlambat", "amount": 100_000}], "warnings": []}]}
        c.api = api
        out = run(SY.slip_gaji_saya(c, {}))
        assert out["daftar"][0]["bersih"] == 3_000_000           # gaji milik sendiri TIDAK disembunyikan
        assert out["rincian"]["tunjangan"][0]["alasan_hangus"] == ["terlambat 4 hari"]
        assert out["rincian"]["potongan"][0]["jumlah"] == 100_000

    def test_absen_dan_cuti_saya(self):
        from core.asisten_ai.alat import saya as SY
        c = AlatContext(user=STAF, cv="DA", today=HARI)

        async def api(method, path, params=None, json=None, **kw):
            if path == SY.P_ABSEN:
                assert set(params) == {"from", "to", "limit"}     # tidak ada id karyawan: endpoint memakai akun sendiri
                return {"summary": {"hadir": 2}, "total_hours_worked": 16, "records": [
                    {"date": "2026-11-02", "status": "hadir", "clock_in": _utc("2026-11-02", "07:20"), "late_minutes": 15}]}
            if path == SY.P_KOREKSI:
                return {"items": [{"date": "2026-11-02", "status": "pending", "reason": "Lupa"}]}
            if path == SY.P_SALDO:
                return {"year": 2026, "balances": [{"leave_type_name": "Cuti tahunan", "quota": 12, "used": 2, "remaining": 10}]}
            if path == SY.P_CUTI:
                return {"items": [{"from_date": "2026-11-20", "to_date": "2026-11-20", "status": "pending_approval",
                                   "request_type": "cuti", "duration_days": 1}]}
            raise AssertionError(path)
        c.api = api
        a = run(SY.absen_saya(c, {"bulan": "2026-11"}))
        assert a["rekap"]["menit_terlambat"] == 15 and a["per_hari"][0]["masuk"] == "07:20"
        assert a["koreksi_absen"][0]["status"] == "Menunggu SDM"
        k = run(SY.cuti_saya(c, {}))
        assert k["saldo"][0]["sisa"] == 10 and k["pengajuan"][0]["status"] == "Menunggu atasan"


# ═══ 7. Kesiapan fitur AI SDM lama & skrip tiruan ══════════════════════════════════════════════════════
class TestKesiapanDanTiruan:
    def test_kesiapan(self, monkeypatch):
        import routes.dewi_hr_ai as m
        db = FakeDB()
        db.rahaza_employees.docs = [{"id": f"e{i}", "active": True} for i in range(6)]

        async def auth(_q):
            return dict(HR)
        monkeypatch.setattr(m, "require_auth", auth)
        monkeypatch.setattr(m, "get_db", lambda: db)
        out = run(m.kesiapan_ai_sdm(FakeRequest()))
        assert not out["attrition"]["siap"] and not out["skill-gap"]["siap"] and not out["coaching"]["siap"]
        hari = date.today().isoformat()
        db.rahaza_attendance_events.docs = [{"id": f"a{i}", "date": hari} for i in range(60)]
        db.dewi_lms_enrollments.docs = [{"id": "l1"}]
        out = run(m.kesiapan_ai_sdm(FakeRequest()))
        assert out["attrition"]["siap"] and out["coaching"]["siap"]

    def test_skrip_tiruan_alat_sdm(self):
        from core.asisten_ai import fake as fk
        tools = [{"name": n, "description": "x", "input_schema": {"type": "object", "properties": {}}}
                 for n in ("rekap_absensi_pengecualian", "terapkan_koreksi_absen", "cakupan_shift", "susun_draf_shift")]
        kw = {"tools": tools, "messages": [{"role": "user", "content": [
            {"type": "text", "text": "<konteks_sistem>x</konteks_sistem>"},
            {"type": "text", "text": "Rekap absensi & pengecualian minggu ini lalu terapkan koreksinya"}]}]}
        blok, stop, _ = fk.skrip_bawaan(fk.Keadaan(kw))
        assert stop == "tool_use" and [b["name"] for b in blok if b["type"] == "tool_use"] == ["rekap_absensi_pengecualian"]
        kw["messages"][0]["content"][1]["text"] = "Lihat slip gaji saya"
        blok, stop, _ = fk.skrip_bawaan(fk.Keadaan(kw))
        assert stop == "end_turn" and "slip_gaji_saya" in json.dumps(blok)
