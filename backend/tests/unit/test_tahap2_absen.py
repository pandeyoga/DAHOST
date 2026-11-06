"""Uji HERMETIK Tahap 2 — paket absen (2026-11-06). Tanpa server/Mongo (FakeDB in-memory).

Satu kelas per butir:
  1 satu fungsi persetujuan cuti (utama · massal · Kotak Masuk SDM · tingkat 2) · 2 hari cuti · 3 saldo hari kerja
  4 GPS segar · 5 selfie · 6 absen pulang lewat tengah malam · 7 lembur · 8 terlambat pakai Jadwal Shift
  9 % kehadiran · 10 file ekspor mesin sidik jari + sinkron langsung · 11 layar absen · 12 jejak & kunci payroll
  13 koreksi absen · 14 migrasi
"""
import asyncio
import importlib
import importlib.util
import io
import os
import sys
import types
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import _MISSING, FakeCollection, FakeCursor, FakeDB, FakeRequest, _get  # noqa: E402


def _import_needing_multipart(name):
    """Rute unggah (UploadFile/Form) memeriksa python-multipart saat impor — dilewati bila tidak terpasang."""
    try:
        return importlib.import_module(name)
    except RuntimeError:
        import fastapi.dependencies.utils as _fdu
        checks = {n: getattr(_fdu, n) for n in ("check_file_field", "ensure_multipart_is_installed")
                  if hasattr(_fdu, n)}
        for n in checks:
            setattr(_fdu, n, lambda *a, **k: None)
        try:
            return importlib.import_module(name)
        finally:
            for n, fn in checks.items():
                setattr(_fdu, n, fn)


import core.attendance_rules as ar  # noqa: E402
import core.fingerprint_import as fi  # noqa: E402
import core.leave_engine as le  # noqa: E402
import routes.hr_approval_inbox as inbox  # noqa: E402
import routes.rahaza_attendance as att  # noqa: E402
import routes.rahaza_auto_attendance_approvals as approvals  # noqa: E402
import routes.rahaza_auto_attendance_config as att_config  # noqa: E402
import routes.rahaza_hr_reports as hr_reports  # noqa: E402
import routes.rahaza_overtime as ot  # noqa: E402
import utils.attendance_policy as policy  # noqa: E402
import utils.employee_identity as ident  # noqa: E402

leave_mod = _import_needing_multipart("routes.rahaza_leave")
zk = _import_needing_multipart("routes.rahaza_auto_attendance_zkteco")
corr = _import_needing_multipart("routes.rahaza_attendance_corrections")
portal_hr = _import_needing_multipart("routes.dewi_portal_saya_hr")

run = asyncio.run
WIB = timezone(timedelta(hours=7))


# ── Mongo palsu + aggregate ($match/$group) — hanya di berkas ini ────────────
def _val(doc, expr):
    if isinstance(expr, str) and expr.startswith("$"):
        v = _get(doc, expr[1:])
        return None if v is _MISSING else v
    if isinstance(expr, dict) and "$cond" in expr:
        cond, yes, no = expr["$cond"]
        return yes if _val(doc, cond) else no
    return expr


class _AggCollection(FakeCollection):
    def aggregate(self, pipeline):
        docs = list(self.docs)
        out = None
        for stage in pipeline:
            if "$match" in stage:
                docs = list(self.find(stage["$match"])._docs)
            elif "$group" in stage:
                spec = dict(stage["$group"])
                id_spec = spec.pop("_id")
                groups: dict = {}
                for d in docs:
                    gid = {k: _val(d, v) for k, v in id_spec.items()}
                    key = tuple(sorted(gid.items(), key=lambda kv: kv[0]))
                    row = groups.setdefault(key, {"_id": gid, **{f: 0 for f in spec}})
                    for f, acc in spec.items():
                        row[f] += _val(d, acc["$sum"])
                out = docs = list(groups.values())
            else:  # pragma: no cover
                raise NotImplementedError(stage)
        return FakeCursor(docs if out is None else out)


class AggDB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _AggCollection(name)
        return self._cols[name]


HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}
HR2 = {"id": "u-hr2", "role": "hr", "name": "Citra HR", "email": "hr2@x"}
MGR = {"id": "u-mgr", "role": "manager", "name": "Manajer", "email": "m@x"}
OPS = {"id": "u-operator", "role": "operator", "name": "Ani", "email": "ani@x"}
LT_CUTI = {"id": "lt-ct", "code": "ANNUAL", "name": "Cuti tahunan", "quota_default": 12, "active": True,
           "unpaid": False, "request_type": "cuti"}
LT_SAKIT = {"id": "lt-sk", "code": "SICK", "name": "Izin sakit", "quota_default": 14, "active": True,
            "unpaid": False, "request_type": "sakit"}
LT_IZIN = {"id": "lt-iz", "code": "PERSONAL", "name": "Izin pribadi", "quota_default": 3, "active": True,
           "unpaid": False, "request_type": "izin"}
LT_LWOP = {"id": "lt-lw", "code": "LWOP", "name": "Cuti tanpa gaji", "quota_default": 30, "active": True,
           "unpaid": True, "request_type": "cuti"}


@pytest.fixture
def db(monkeypatch):
    d = AggDB()
    d.rahaza_employees.docs = [
        {"id": "emp-a", "name": "Ani", "employee_code": "E01", "active": True, "user_id": "u-operator"},
        {"id": "emp-b", "name": "Budi", "employee_code": "E02", "active": True, "user_id": "u-budi",
         "zkteco_user_id": "7"},
        {"id": "emp-h", "name": "Brenda", "employee_code": "H01", "active": True, "user_id": "u-hr"},
    ]
    d.rahaza_leave_types.docs = [dict(LT_CUTI), dict(LT_SAKIT), dict(LT_IZIN), dict(LT_LWOP)]

    async def noop(*a, **k):
        return None

    for mod in (att, approvals, att_config, hr_reports, ot, leave_mod, zk, corr, inbox, portal_hr):
        monkeypatch.setattr(mod, "get_db", lambda: d)
        if hasattr(mod, "log_activity"):
            monkeypatch.setattr(mod, "log_activity", noop)
    return d


def as_user(monkeypatch, user, *mods):
    async def _auth(_request=None, *a, **k):
        return dict(user)
    for m in mods or (att, approvals, att_config, hr_reports, ot, leave_mod, zk, corr, portal_hr):
        monkeypatch.setattr(m, "require_auth", _auth)


def _status(coro):
    try:
        run(coro)
        return 200
    except HTTPException as e:
        return e.status_code


def _src(*parts):
    p = os.path.join(REPO, *parts)
    if not os.path.exists(p):
        pytest.skip(f"sumber frontend tidak tersedia: {p}")
    return open(p, encoding="utf-8").read()


def _leave(db, lid="lv1", lt="lt-ct", f="2026-11-06", t="2026-11-09", **kw):
    doc = {"id": lid, "employee_id": "emp-a", "leave_type_id": lt, "from_date": f, "to_date": t,
           "status": "pending_approval", "approval_level_required": 1, "current_approval_level": 1,
           "reason": "Keperluan keluarga", "submitted_by": "u-operator", "created_by": "u-operator", **kw}
    db.rahaza_leave_requests.docs.append(doc)
    return doc


def _rows(db, emp="emp-a"):
    return sorted((r for r in db.rahaza_attendance_events.docs if r.get("employee_id") == emp),
                  key=lambda r: r["date"])


def _lock(db, emp="emp-a", f="2026-10-01", t="2026-10-31"):
    db.rahaza_payroll_runs.docs.append({"id": "run-okt", "run_number": "PR-OKT", "status": "finalized",
                                        "period_from": f, "period_to": t})
    db.rahaza_payslips.docs.append({"id": "slip-1", "run_id": "run-okt", "employee_id": emp})


# ═════════════════════════════════════════════════════════════════════════════
# 1 · Satu fungsi persetujuan
# ═════════════════════════════════════════════════════════════════════════════
class TestSatuFungsiPersetujuan:
    def _effects(self, db):
        bal = db.rahaza_leave_balances.docs[0]
        lv = db.rahaza_leave_requests.docs[0]
        return (lv["status"], lv["pay_decision"], bal["used"],
                [(r["date"], r["status"], r["paid_leave"]) for r in _rows(db)])

    def test_utama_massal_dan_kotak_masuk_berakibat_sama(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        results = []
        for path in ("utama", "massal", "kotak_masuk"):
            db.rahaza_leave_requests.docs.clear()
            db.rahaza_leave_balances.docs.clear()
            db.rahaza_attendance_events.docs.clear()
            _leave(db)
            if path == "utama":
                run(leave_mod.approve_leave("lv1", FakeRequest({})))
            elif path == "massal":
                out = run(leave_mod.bulk_approve_leaves(FakeRequest({"leave_ids": ["lv1"]})))
                assert out["approved"] == 1
            else:
                run(inbox.approve_request("leave", "lv1", inbox.ActionPayload(), user=dict(HR)))
            results.append(self._effects(db))
        assert results[0] == results[1] == results[2]
        # Jumat 6, Sabtu 7, Senin 9 Nov = 3 hari kerja (Minggu 8 tidak ditulis, tidak memotong saldo)
        assert results[0] == ("approved", "paid", 3.0,
                              [("2026-11-06", "cuti", True), ("2026-11-07", "cuti", True), ("2026-11-09", "cuti", True)])

    def test_kotak_masuk_ikut_tingkat_dua(self, db, monkeypatch):
        as_user(monkeypatch, MGR)
        _leave(db, approval_level_required=2)
        out = run(inbox.approve_request("leave", "lv1", inbox.ActionPayload(), user=dict(MGR)))
        assert out["new_status"] == "pending_hr_approval"
        assert db.rahaza_attendance_events.docs == [] and db.rahaza_leave_balances.docs == []
        items = run(inbox._fetch_leaves(db, "leave", 10))
        assert [i["id"] for i in items] == ["lv1"] and items[0]["meta"]["approval_level"] == "2/2"
        out = run(inbox.approve_request("leave", "lv1", inbox.ActionPayload(pay_decision="unpaid"), user=dict(HR)))
        assert out["new_status"] == "approved"
        lv = db.rahaza_leave_requests.docs[0]
        assert lv["pay_decision"] == "unpaid" and lv["approval_step_1"]["approver_id"] == "u-mgr"
        assert all(r["paid_leave"] is False for r in _rows(db))

    def test_massal_tolak_saldo_kurang_tanpa_menulis(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _leave(db, lt="lt-iz", f="2026-11-02", t="2026-11-07", attachment_url="/api/uploads/x.pdf")   # 6 > jatah 3
        out = run(leave_mod.bulk_approve_leaves(FakeRequest({})))
        assert out["approved"] == 0 and len(out["failed"]) == 1 and "Sisa cuti tidak cukup" in out["failed"][0]["reason"]
        assert db.rahaza_attendance_events.docs == [] and db.rahaza_leave_requests.docs[0]["status"] == "pending_approval"

    def test_dialog_persetujuan_memuat_alasan_lampiran_dan_usulan(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _leave(db, lt="lt-sk", attachment_url="/api/uploads/surat.pdf", reason="Demam")
        out = run(leave_mod.leave_approval_preview("lv1", FakeRequest()))
        assert out["reason"] == "Demam" and out["attachment_url"] == "/api/uploads/surat.pdf"
        assert out["suggestion"]["decision"] == "paid" and out["days"] == ["2026-11-06", "2026-11-07", "2026-11-09"]
        assert out["final_step"] is True and out["balance"]["remaining"] == 14

    def test_usulan_bayar(self):
        assert le.suggest_pay_decision({"attachment_url": "x"}, LT_SAKIT)["decision"] == "paid"
        assert le.suggest_pay_decision({}, LT_IZIN)["decision"] == "unpaid"
        assert le.suggest_pay_decision({"attachment_url": "x"}, LT_IZIN)["decision"] == "paid"
        assert le.suggest_pay_decision({}, LT_LWOP)["decision"] == "unpaid"
        assert le.suggest_pay_decision({}, LT_CUTI)["decision"] == "paid"

    def test_tidak_boleh_menyetujui_cuti_sendiri(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _leave(db)
        db.rahaza_leave_requests.docs[0]["employee_id"] = "emp-h"   # karyawan milik akun HR
        assert _status(leave_mod.approve_leave("lv1", FakeRequest({}))) == 403
        assert _status(inbox.approve_request("leave", "lv1", inbox.ActionPayload(), user=dict(HR))) == 403

    def test_kotak_masuk_tolak_lewat_mesin_yang_sama(self, db, monkeypatch):
        _leave(db)
        run(inbox.reject_request("leave", "lv1", inbox.ActionPayload(reason="Kuota tim penuh"), user=dict(HR)))
        lv = db.rahaza_leave_requests.docs[0]
        assert lv["status"] == "rejected" and lv["rejected_reason"] == "Kuota tim penuh"


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Hari cuti
# ═════════════════════════════════════════════════════════════════════════════
class TestHariCuti:
    def test_sakit_tetap_sakit_dan_libur_kalender_dilewati(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_production_calendar.docs = [{"date": "2026-11-09", "type": "holiday", "name": "Libur"}]
        _leave(db, lt="lt-sk", attachment_url="/api/uploads/surat.pdf")
        run(leave_mod.approve_leave("lv1", FakeRequest({})))
        assert [(r["date"], r["status"], r["leave_request_id"]) for r in _rows(db)] == [
            ("2026-11-06", "sakit", "lv1"), ("2026-11-07", "sakit", "lv1")]
        assert db.rahaza_leave_balances.docs[0]["used"] == 2

    def test_setengah_hari(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _leave(db, f="2026-11-05", t="2026-11-05", is_half_day=True)
        run(leave_mod.approve_leave("lv1", FakeRequest({})))
        (r,) = _rows(db)
        assert r["half_day"] is True and r["status"] == "cuti"
        assert db.rahaza_leave_balances.docs[0]["used"] == 0.5

    def test_jam_absen_yang_ada_tidak_ditimpa_dan_batal_mengembalikan(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        cin = datetime(2026, 11, 6, 0, 55, tzinfo=timezone.utc)
        db.rahaza_attendance_events.docs = [{"id": "ev-6", "employee_id": "emp-a", "date": "2026-11-06",
                                             "status": "hadir", "clock_in": cin, "notes": "pulang sakit jam 9"}]
        _leave(db, lt="lt-sk", attachment_url="/api/uploads/surat.pdf")
        run(leave_mod.approve_leave("lv1", FakeRequest({})))
        r6 = _rows(db)[0]
        assert r6["id"] == "ev-6" and r6["clock_in"] == cin and r6["status"] == "sakit"
        assert r6["pre_leave"]["status"] == "hadir"
        run(leave_mod.cancel_leave("lv1", FakeRequest({"reason": "Salah input"})))
        rows = _rows(db)
        assert [r["date"] for r in rows] == ["2026-11-06"]       # record buatan cuti (7 & 9 Nov) dihapus lagi
        assert rows[0]["status"] == "hadir" and rows[0]["clock_in"] == cin and rows[0]["leave_request_id"] is None
        assert rows[0]["notes"] == "pulang sakit jam 9"
        assert db.rahaza_leave_balances.docs[0]["used"] == 0
        assert db.rahaza_leave_requests.docs[0]["status"] == "cancelled"

    def test_absen_masuk_di_hari_cuti(self):
        with pytest.raises(HTTPException) as ei:
            policy.leave_status_for_clock_in({"leave_request_id": "lv1", "status": "cuti"})
        assert ei.value.status_code == 409
        assert policy.leave_status_for_clock_in({"leave_request_id": "lv1", "status": "izin", "half_day": True}) == "izin"
        assert policy.leave_status_for_clock_in(None) == "hadir"

    def test_pengajuan_wajib_alasan_dan_hari_kerja(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        base = {"employee_id": "emp-a", "leave_type_id": "lt-ct", "from_date": "2026-11-10", "to_date": "2026-11-10"}
        assert _status(leave_mod.request_leave(FakeRequest(base))) == 400                       # tanpa alasan
        assert _status(leave_mod.request_leave(FakeRequest({**base, "reason": "x", "from_date": "2026-11-08",
                                                            "to_date": "2026-11-08"}))) == 400  # Minggu
        assert _status(leave_mod.request_leave(FakeRequest({**base, "reason": "x", "is_half_day": True,
                                                            "to_date": "2026-11-11"}))) == 400  # setengah hari 2 tgl
        out = run(leave_mod.request_leave(FakeRequest({**base, "leave_type_id": "lt-sk", "reason": "Demam",
                                                       "to_date": "2026-11-12"})))
        assert out["leave_kind"] == "sakit" and out["duration_days"] == 3 and out["status"] == "pending_approval"

    def test_portal_saya_lewat_jalur_yang_sama(self, db, monkeypatch):
        as_user(monkeypatch, OPS)

        async def linked(_db, uid):
            return {"id": uid}, {"id": "emp-a", "name": "Ani"}
        monkeypatch.setattr(portal_hr, "_get_linked_employee", linked)
        out = run(portal_hr.create_leave(FakeRequest({"leave_type_id": "lt-ct", "from_date": "2026-11-10",
                                                      "reason": "Urusan keluarga"})))
        assert out["status"] == "pending_approval" and out["employee_id"] == "emp-a"


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Saldo hari kerja
# ═════════════════════════════════════════════════════════════════════════════
class TestSaldoHariKerja:
    def test_tidak_dibayar_tidak_memakai_jatah(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _leave(db, lt="lt-iz", f="2026-11-02", t="2026-11-07")   # 6 hari > jatah 3
        out = run(leave_mod.approve_leave("lv1", FakeRequest({"pay_decision": "unpaid"})))
        assert out["status"] == "approved" and out["balance_deducted_days"] == 0
        assert db.rahaza_leave_balances.docs == []
        assert {r["paid_leave"] for r in _rows(db)} == {False}

    def test_pratinjau_hari_kerja_enam_hari(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        out = run(leave_mod.working_days_preview(FakeRequest(), from_date="2026-11-02", to_date="2026-11-08"))
        assert out["working_days"] == 6 and out["weekend_days"] == 1 and out["calendar_days"] == 7

    def test_kunci_payroll_menolak_persetujuan(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _lock(db)
        _leave(db, f="2026-10-30", t="2026-10-30")
        with pytest.raises(HTTPException) as ei:
            run(leave_mod.approve_leave("lv1", FakeRequest({})))
        assert ei.value.status_code == 409 and "penggajian final" in ei.value.detail
        assert db.rahaza_attendance_events.docs == []


# ═════════════════════════════════════════════════════════════════════════════
# 4 · GPS segar saat tombol ditekan
# ═════════════════════════════════════════════════════════════════════════════
OFFICE = {"is_primary": True, "lat": -6.2, "lng": 106.8, "geofence_radius_m": 300, "require_geofence": True,
          "require_selfie": False}


class TestGpsSegar:
    def test_basi_dan_kurang_akurat_ditolak(self):
        office = {"gps_max_age_s": 60, "gps_max_accuracy_m": 100}
        with pytest.raises(HTTPException) as ei:
            policy.check_gps_fix({"gps_at": 1_000, "sent_at": 1_000 + 3_600_000, "accuracy": 10}, office)
        assert "basi" in ei.value.detail and "Coba lagi" in ei.value.detail
        with pytest.raises(HTTPException) as ei:
            policy.check_gps_fix({"gps_at": 1_000, "sent_at": 6_000, "accuracy": 450}, office)
        assert "kurang akurat" in ei.value.detail and "Coba lagi" in ei.value.detail
        assert policy.check_gps_fix({"gps_at": 1_000, "sent_at": 6_000, "accuracy": 20}, office)["age_s"] == 5

    def test_tanpa_data_kesegaran_ditolak_saat_geofence_wajib(self, db):
        db.rahaza_office_locations.docs = [dict(OFFICE)]
        with pytest.raises(HTTPException) as ei:
            run(policy.enforce_attendance_policy(db, photo_b64=None, lat=-6.2, lng=106.8, selfie_required=False))
        assert ei.value.status_code == 400 and "Coba lagi" in ei.value.detail
        fix = {"gps_at": 10_000, "sent_at": 12_000, "accuracy": 15}
        out = run(policy.enforce_attendance_policy(db, photo_b64=None, lat=-6.2, lng=106.8, selfie_required=False,
                                                   fix=fix))
        assert out["geo"]["status"] == "in_range" and out["geo"]["accuracy_m"] == 15


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Selfie: foto tampil di review HR, Portal Saya kamera saja
# ═════════════════════════════════════════════════════════════════════════════
class TestSelfie:
    def test_kotak_masuk_membawa_foto_selfie(self, db):
        db.rahaza_attendance_events.docs = [{"id": "ev-1", "employee_id": "emp-a", "date": "2026-11-05",
                                             "approval_status": "pending", "photo_selfie_url": "/api/uploads/s.jpg"}]
        (item,) = run(inbox._fetch_attendance(db, "attendance", 10))
        assert item["meta"]["photo_url"] == "/api/uploads/s.jpg"

    def test_tolak_selfie_menulis_alpa_dan_jejak(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [{"id": "ev-1", "employee_id": "emp-a", "date": "2026-11-05",
                                             "status": "hadir", "approval_status": "pending"}]
        run(approvals.reject_attendance("ev-1", FakeRequest({"notes": "Bukan wajah karyawan"})))
        ev = db.rahaza_attendance_events.docs[0]
        assert ev["status"] == "alpa" and ev["approval_status"] == "rejected"
        (a,) = db.rahaza_attendance_audit.docs
        assert a["source"] == "persetujuan_selfie" and a["before"]["status"] == "hadir" and a["after"]["status"] == "alpa"

    def test_layar_hr_menampilkan_foto_dan_portal_kamera_saja(self):
        hr = _src("frontend", "src", "components", "erp", "RahazaAttendanceApprovalModule.jsx")
        assert "photo_selfie_url" in hr and "photo_selfie_out_url" in hr
        me = _src("frontend", "src", "components", "erp", "PortalSayaAbsen.jsx")
        assert "Unggah Foto" not in me and 'type="file"' not in me and "FileReader" not in me
        assert "getUserMedia" in me and "Kamera tidak bisa dibuka" in me


# ═════════════════════════════════════════════════════════════════════════════
# 6 · Absen pulang lewat tengah malam
# ═════════════════════════════════════════════════════════════════════════════
class TestPulangLewatTengahMalam:
    def _seed(self, db, start, end, cin_local):
        db.rahaza_shifts.docs = [{"id": "sh-x", "code": "X", "start_time": start, "end_time": end}]
        db.rahaza_employees.docs[0]["shift_id"] = "sh-x"
        db.rahaza_attendance_events.docs = [{"id": "ev-y", "employee_id": "emp-a", "date": "2026-11-05",
                                             "clock_in": cin_local.astimezone(timezone.utc), "clock_out": None}]
        return db.rahaza_employees.docs[0]

    def test_shift_malam_menutup_record_kemarin(self, db):
        emp = self._seed(db, "22:00", "06:00", datetime(2026, 11, 5, 21, 58, tzinfo=WIB))
        now = datetime(2026, 11, 6, 6, 10, tzinfo=WIB)
        rec, why = run(ar.find_clock_out_record(db, emp, now))
        assert rec and rec["id"] == "ev-y" and not why

    def test_lembur_lewat_tengah_malam_dalam_jendela(self, db):
        emp = self._seed(db, "15:00", "23:00", datetime(2026, 11, 5, 14, 55, tzinfo=WIB))
        rec, _ = run(ar.find_clock_out_record(db, emp, datetime(2026, 11, 6, 1, 30, tzinfo=WIB)))
        assert rec and rec["id"] == "ev-y"
        db.rahaza_office_locations.docs = [{"is_primary": True, "clock_out_window_hours": 2}]
        rec, why = run(ar.find_clock_out_record(db, emp, datetime(2026, 11, 6, 1, 30, tzinfo=WIB)))
        assert rec is None and why == "Belum clock-in hari ini."

    def test_shift_siang_lupa_absen_pulang_tidak_ditutup_besok(self, db):
        emp = self._seed(db, "08:00", "17:00", datetime(2026, 11, 5, 7, 55, tzinfo=WIB))
        rec, _ = run(ar.find_clock_out_record(db, emp, datetime(2026, 11, 6, 7, 50, tzinfo=WIB)))
        assert rec is None

    def test_status_saya_menampilkan_record_kemarin_dan_jam_server(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        self._seed(db, "22:00", "06:00", datetime(2026, 11, 5, 21, 58, tzinfo=WIB))
        monkeypatch.setattr(att_config, "_today_iso", lambda: "2026-11-06")
        monkeypatch.setattr(ar, "_now", lambda: datetime(2026, 11, 6, 6, 10, tzinfo=WIB).astimezone(timezone.utc))
        out = run(att_config.get_my_attendance_status(FakeRequest()))
        assert out["open_previous"]["id"] == "ev-y" and out["server_time"]


# ═════════════════════════════════════════════════════════════════════════════
# 7 · Lembur
# ═════════════════════════════════════════════════════════════════════════════
class TestLembur:
    def test_pengali_dari_pengaturan_payroll_bukan_karyawan(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        db.rahaza_payroll_settings.docs = [{"key": "overtime", "first_hour_multiplier": 1.75}]
        assert _status(ot.create_request(FakeRequest({"date": "2026-11-05", "hours": 2}))) == 400   # tanpa alasan
        assert _status(ot.create_request(FakeRequest({"date": "2026-11-05", "reason": "x"}))) == 400  # tanpa jam
        out = run(ot.create_request(FakeRequest({"date": "2026-11-05", "hours": 2, "reason": "Kejar kirim",
                                                 "rate_multiplier": 3})))
        doc = db.rahaza_overtime_requests.docs[0]
        assert out["ok"] and doc["rate_multiplier"] == 1.75 and doc["hours"] == 2 and doc["employee_id"] == "emp-a"

    def test_penyetuju_tidak_boleh_menyetujui_lembur_sendiri(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_overtime_requests.docs = [{"id": "ot1", "employee_id": "emp-h", "date": "2026-11-05", "hours": 2,
                                             "status": "pending", "submitted_by": "u-hr"}]
        assert _status(ot.approve_request("ot1", FakeRequest())) == 403
        assert _status(inbox.approve_request("overtime", "ot1", inbox.ActionPayload(), user=dict(HR))) == 403
        as_user(monkeypatch, HR2)
        assert run(ot.approve_request("ot1", FakeRequest()))["overtime"]["status"] == "approved"

    def test_hr_menandai_lembur_dibayar(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [{"id": "ev-1", "employee_id": "emp-a", "date": "2026-11-05",
                                             "status": "hadir", "overtime_hours": 2}]
        run(corr.mark_overtime_paid("ev-1", FakeRequest({"paid": True, "note": "Disuruh supervisor"})))
        ev = db.rahaza_attendance_events.docs[0]
        assert ev["overtime_paid"] is True and ev["overtime_paid_by"] == "u-hr" and ev["overtime_paid_at"]
        assert db.rahaza_attendance_audit.docs[0]["after"] == {"overtime_paid": True}
        as_user(monkeypatch, OPS)
        assert _status(corr.mark_overtime_paid("ev-1", FakeRequest({"paid": False}))) == 403

    def test_grid_menampilkan_lembur_dan_tanda_bayar(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [{"id": "ev-1", "employee_id": "emp-a", "date": "2026-11-05",
                                             "status": "hadir", "overtime_hours": 2, "overtime_paid": True}]
        db.rahaza_overtime_requests.docs = [{"id": "o", "employee_id": "emp-b", "date": "2026-11-05",
                                             "status": "approved", "hours": 1.5}]
        rows = {r["employee_id"]: r for r in run(att.attendance_grid(FakeRequest(), date="2026-11-05"))["rows"]}
        assert rows["emp-a"]["overtime_paid"] is True and rows["emp-b"]["overtime_request_hours"] == 1.5


# ═════════════════════════════════════════════════════════════════════════════
# 8 · Terlambat memakai Jadwal Shift
# ═════════════════════════════════════════════════════════════════════════════
class TestTerlambatJadwalShift:
    CIN = datetime(2026, 11, 5, 8, 30, tzinfo=WIB).astimezone(timezone.utc)

    def _seed(self, db, sched_status="published"):
        db.rahaza_shifts.docs = [{"id": "sh-pagi", "code": "PAGI", "start_time": "07:00", "end_time": "15:00"},
                                 {"id": "sh-siang", "code": "SIANG", "start_time": "13:00", "end_time": "21:00"}]
        emp = dict(db.rahaza_employees.docs[0], shift_id="sh-pagi")
        db.rahaza_schedules.docs = [{"id": "jd1", "status": sched_status, "start_date": "2026-11-02",
                                     "end_date": "2026-11-08", "shifts": [
                                         {"employee_id": "emp-a", "date": "2026-11-05", "shift_name": "Pagi siang",
                                          "start_time": "09:00", "end_time": "17:00"}]}]
        return emp

    def test_jadwal_terbit_dipakai(self, db):
        emp = self._seed(db)
        out = run(ident.compute_late_minutes(db, emp, self.CIN))
        assert out["late_minutes"] == 0 and out["shift_start"] == "09:00" and out["shift_source"] == "jadwal"

    def test_jadwal_draf_diabaikan_pakai_shift_karyawan(self, db):
        emp = self._seed(db, "draft")
        out = run(ident.compute_late_minutes(db, emp, self.CIN))
        assert out["late_minutes"] == 85 and out["shift_source"] == "karyawan"

    def test_penugasan_shift_sebelum_shift_bawaan(self, db):
        emp = self._seed(db, "draft")
        db.hr_shift_assignments.docs = [{"id": 1, "employee_id": "emp-a", "shift_id": "sh-siang", "status": "active",
                                         "effective_from": "2026-11-01", "effective_until": None}]
        out = run(ident.compute_late_minutes(db, emp, self.CIN))
        assert out["shift_start"] == "13:00" and out["late_minutes"] == 0 and out["shift_source"] == "penugasan"


# ═════════════════════════════════════════════════════════════════════════════
# 9 · % kehadiran = hadir ÷ hari kerja
# ═════════════════════════════════════════════════════════════════════════════
class TestPersenKehadiran:
    def test_dibagi_hari_kerja_dan_setengah_hari(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        rows = [{"id": f"a{d}", "employee_id": "emp-a", "date": f"2026-11-0{d}", "status": "hadir"} for d in (2, 3, 4, 5, 6)]
        rows += [{"id": "a7", "employee_id": "emp-a", "date": "2026-11-07", "status": "cuti", "half_day": True},
                 {"id": "a8", "employee_id": "emp-a", "date": "2026-11-08", "status": "hadir"}]   # Minggu
        db.rahaza_attendance_events.docs = rows
        out = run(hr_reports.get_attendance_summary(FakeRequest(), from_date="2026-11-02", to_date="2026-11-08",
                                                    employee_id="emp-a"))
        (s,) = out["summary"]
        assert s["working_days"] == 6 and s["present_days"] == 5.5 and s["attendance_rate"] == 91.7
        assert s["total_days"] == 7 and out["aggregates"]["working_days"] == 6

    def test_alpa_kontrak_dan_alfa_lama_satu_kolom(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [
            {"id": "x1", "employee_id": "emp-a", "date": "2026-11-02", "status": "alpa"},
            {"id": "x2", "employee_id": "emp-a", "date": "2026-11-03", "status": "alfa"}]
        out = run(hr_reports.get_attendance_summary(FakeRequest(), from_date="2026-11-02", to_date="2026-11-08",
                                                    employee_id="emp-a"))
        assert out["summary"][0]["alfa"] == 2 and out["aggregates"]["total_alfa"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# 10 · File ekspor mesin sidik jari + sinkron langsung
# ═════════════════════════════════════════════════════════════════════════════
CSV = (b"No.,AC-No.,Nama,Waktu,Status\n"
       b"1,E01,Ani,05/11/2026 07:55:10,C/In\n"
       b"2,E01,Ani,05/11/2026 12:01:00,C/Out\n"
       b"3,E01,Ani,05/11/2026 17:05:00,C/Out\n"
       b"4,7,Budi,05/11/2026 08:10:00,C/In\n"
       b"5,7,Budi,05/11/2026 17:00:00,C/Out\n"
       b"6,X99,Asing,05/11/2026 08:00:00,C/In\n"
       b"7,E01,Ani,bukan tanggal,C/In\n")


class _Upload:
    def __init__(self, name, data):
        self.filename, self._data = name, data

    async def read(self):
        return self._data


def _fp(apply, mapping="", profile_id=""):
    fn = zk.fingerprint_import if apply else zk.fingerprint_preview
    return run(fn(FakeRequest(), file=_Upload("absen_nov.csv", CSV), mapping=mapping, profile_id=profile_id,
                  date_order="", header_row=None))


class TestFileMesinSidikJari:
    def test_pratinjau_usul_kolom_dan_hitungan(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        out = _fp(False)
        assert out["mapping"] == {"datetime": "Waktu", "code": "AC-No.", "direction": "Status"}
        st = out["stats"]
        assert (st["new"], st["updated"], st["employees"], st["unmatched_count"], st["invalid_rows"]) == (2, 0, 2, 1, 1)
        assert db.rahaza_attendance_events.docs == [] and db.rahaza_fingerprint_imports.docs == []

    def test_impor_gabung_per_hari_selfie_tetap_dan_idempoten(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        selfie_in = datetime(2026, 11, 5, 0, 50, tzinfo=timezone.utc)   # 07:50 WIB (selfie)
        db.rahaza_attendance_events.docs = [{"id": "ev-b", "employee_id": "emp-b", "date": "2026-11-05",
                                             "status": "hadir", "clock_in": selfie_in, "clock_out": None,
                                             "source": "selfie_geo_ai", "photo_selfie_url": "/s.jpg"}]
        out = _fp(True)
        assert (out["stats"]["new"], out["stats"]["updated"]) == (1, 1)
        a = next(r for r in db.rahaza_attendance_events.docs if r["employee_id"] == "emp-a")
        assert a["clock_in"] == datetime(2026, 11, 5, 0, 55, 10, tzinfo=timezone.utc)   # 07:55:10 WIB
        assert a["clock_out"] == datetime(2026, 11, 5, 10, 5, tzinfo=timezone.utc)      # ketukan pulang terakhir
        assert a["hours_worked"] == 9.16 and a["status"] == "hadir"
        b = next(r for r in db.rahaza_attendance_events.docs if r["employee_id"] == "emp-b")
        assert b["clock_in"] == selfie_in and b["photo_selfie_url"] == "/s.jpg"            # selfie tidak ditimpa
        assert b["clock_out"] == datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
        n_docs = len(db.rahaza_attendance_events.docs)
        again = _fp(True)
        assert (again["stats"]["new"], again["stats"]["updated"], again["stats"]["unchanged"]) == (0, 0, 2)
        assert len(db.rahaza_attendance_events.docs) == n_docs and again["previous_import_at"]

    def test_profil_pemetaan_dipakai_ulang(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        res = run(zk.save_fingerprint_profile(FakeRequest({"name": "Mesin lobi", "date_order": "dmy",
                                                           "mapping": {"code": "AC-No.", "datetime": "Waktu"}})))
        out = _fp(False, profile_id=res["profile"]["id"])
        assert out["mapping"] == {"code": "AC-No.", "datetime": "Waktu"}
        # tanpa kolom penanda: ketukan pertama = masuk, terakhir = pulang
        assert out["stats"]["new"] == 2
        assert _status(zk.save_fingerprint_profile(FakeRequest({"name": "x", "mapping": {"code": "AC-No."}}))) == 400

    def test_pemetaan_tanggal_dan_jam_terpisah(self):
        header = ["PIN", "Tanggal", "Jam"]
        rows = [["E01", "2026-11-05", "07:58"], ["E01", "2026-11-05", "16:59"]]
        p, bad = fi.extract_punches(header, rows, {"code": "PIN", "date": "Tanggal", "time": "Jam"})
        assert bad == 0 and [x["at"] for x in p] == [datetime(2026, 11, 5, 7, 58), datetime(2026, 11, 5, 16, 59)]
        with pytest.raises(HTTPException):
            fi.extract_punches(header, rows, {"code": "PIN", "date": "Tanggal"})

    def test_xlsx(self):
        openpyxl = pytest.importorskip("openpyxl")
        if not hasattr(openpyxl, "load_workbook"):
            pytest.skip("openpyxl tiruan")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["PIN", "Waktu"])
        ws.append(["7", datetime(2026, 11, 5, 8, 1)])
        buf = io.BytesIO()
        wb.save(buf)
        header, body = fi.split_header(fi.read_table("a.xlsx", buf.getvalue()))
        p, _ = fi.extract_punches(header, body, {"code": "PIN", "datetime": "Waktu"})
        assert p[0]["at"] == datetime(2026, 11, 5, 8, 1)

    class _Req:
        headers = {"content-type": "application/json"}

        async def json(self):
            return {}

        async def body(self):
            return b"{}"

    def _device(self, db):
        db.rahaza_zkteco_devices.docs = [{"id": "dev1", "name": "Lobi", "ip": "192.168.1.20", "port": 4370}]

    def test_sinkron_tanpa_pyzk_pesan_jelas(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        self._device(db)
        monkeypatch.setitem(sys.modules, "zk", None)
        with pytest.raises(HTTPException) as ei:
            run(zk.sync_zkteco_device("dev1", self._Req()))
        assert ei.value.status_code == 503 and "pyzk" in ei.value.detail and "Unggah file ekspor" in ei.value.detail
        assert db.rahaza_zkteco_devices.docs[0]["last_error_code"] == "pyzk_missing"

    def _fake_zk(self, monkeypatch, attendances=None, fail=False):
        mod = types.ModuleType("zk")

        class _Conn:
            def disable_device(self):
                pass

            def enable_device(self):
                pass

            def get_attendance(self):
                return attendances or []

            def disconnect(self):
                pass

        class ZK:
            def __init__(self, *a, **k):
                pass

            def connect(self):
                if fail:
                    raise OSError("timed out")
                return _Conn()
        mod.ZK = ZK
        monkeypatch.setitem(sys.modules, "zk", mod)

    def test_sinkron_mesin_tak_terjangkau(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        self._device(db)
        self._fake_zk(monkeypatch, fail=True)
        with pytest.raises(HTTPException) as ei:
            run(zk.sync_zkteco_device("dev1", self._Req()))
        assert "tidak bisa menjangkau mesin" in ei.value.detail and "Unggah file ekspor" in ei.value.detail

    def test_sinkron_banyak_ketukan_digabung_tanpa_bentrok(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        self._device(db)
        A = types.SimpleNamespace
        self._fake_zk(monkeypatch, [A(user_id=7, timestamp=datetime(2026, 11, 5, 8, 0), punch=0),
                                    A(user_id=7, timestamp=datetime(2026, 11, 5, 12, 0), punch=0),
                                    A(user_id=7, timestamp=datetime(2026, 11, 5, 17, 0), punch=0)])
        out = run(zk.sync_zkteco_device("dev1", self._Req()))
        (rec,) = db.rahaza_attendance_events.docs
        assert out["synced"] == 1 and rec["clock_in"].hour == 1 and rec["clock_out"].hour == 10
        again = run(zk.sync_zkteco_device("dev1", self._Req()))
        assert again["synced"] == 0 and len(db.rahaza_attendance_events.docs) == 1


# ═════════════════════════════════════════════════════════════════════════════
# 11 · Layar absen Portal Saya
# ═════════════════════════════════════════════════════════════════════════════
class TestLayarAbsen:
    def test_satu_menu_absen(self):
        nav = _src("frontend", "src", "components", "erp", "portal-shell", "portalNav.js")
        block = nav[nav.index("  self: {"):]
        block = block[:block.index("\n  },\n")]
        assert block.count("id: 'portal-absen'") == 1 and "id: 'self-dashboard'" not in block

    def test_cetakan_tombol_di_atas_coba_lagi_jam_server(self):
        s = _src("frontend", "src", "components", "erp", "PortalSayaAbsen.jsx")
        assert "<PageLayout" in s and "Coba lagi" in s and "server_time" in s
        assert s.index("absen-btn-clock-in") < s.index("absen-today-status")
        assert "maximumAge: 0" in s and "gps_sent_at" in s and "gps_at" in s


# ═════════════════════════════════════════════════════════════════════════════
# 12 · Jejak perubahan & kunci payroll
# ═════════════════════════════════════════════════════════════════════════════
class TestJejakDanKunci:
    def test_grid_mencatat_sebelum_sesudah(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [{"id": "ev-1", "employee_id": "emp-a", "date": "2026-11-05",
                                             "status": "hadir", "notes": ""}]
        run(att.bulk_attendance(FakeRequest({"date": "2026-11-05", "entries": [
            {"employee_id": "emp-a", "status": "alpa", "notes": "Tidak datang"}]})))
        (a,) = db.rahaza_attendance_audit.docs
        assert a["before"]["status"] == "hadir" and a["after"]["status"] == "alpa"
        assert a["changed_by"] == "u-hr" and a["source"] == "grid" and a["changed_at"]
        out = run(corr.attendance_audit(FakeRequest(), employee_id="emp-a", day="2026-11-05"))
        assert len(out["items"]) == 1

    def test_tanggal_terkunci_ditolak(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _lock(db)
        body = {"date": "2026-10-15", "entries": [{"employee_id": "emp-a", "status": "hadir"}]}
        with pytest.raises(HTTPException) as ei:
            run(att.bulk_attendance(FakeRequest(body)))
        assert ei.value.status_code == 409 and "Ajukan koreksi" in ei.value.detail and "Ani" in ei.value.detail
        assert _status(att.upsert_attendance(FakeRequest({"employee_id": "emp-a", "date": "2026-10-15"}))) == 409
        assert db.rahaza_attendance_events.docs == []
        # karyawan lain (tidak ada di slip run itu) tetap boleh
        assert run(att.bulk_attendance(FakeRequest({"date": "2026-10-15", "entries": [
            {"employee_id": "emp-b", "status": "hadir"}]})))["saved"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# 13 · Koreksi absen
# ═════════════════════════════════════════════════════════════════════════════
class TestKoreksiAbsen:
    def _ajukan(self, monkeypatch, day="2026-11-04"):
        as_user(monkeypatch, OPS)
        return run(corr.create_correction(FakeRequest({"date": day, "clock_in": "07:58", "clock_out": "17:02",
                                                       "reason": "Lupa absen, HP mati"})))

    def test_tanggal_terbuka_langsung_diterapkan(self, db, monkeypatch):
        db.rahaza_attendance_events.docs = [{"id": "ev-4", "employee_id": "emp-a", "date": "2026-11-04",
                                             "status": "alpa"}]
        c = self._ajukan(monkeypatch)
        assert c["status"] == "pending" and c["current"]["status"] == "alpa"
        as_user(monkeypatch, HR)
        out = run(corr.approve_correction(c["id"], FakeRequest({"note": "ok"})))
        assert out["correction"]["apply_mode"] == "langsung"
        ev = db.rahaza_attendance_events.docs[0]
        assert ev["clock_in"] == datetime(2026, 11, 4, 0, 58, tzinfo=timezone.utc) and ev["hours_worked"] == 9.07
        assert ev["status"] == "hadir"   # koreksi jam pada hari alpa = hadir
        assert db.rahaza_attendance_audit.docs[0]["source"] == "koreksi"

    def test_tanggal_terkunci_diteruskan_ke_payroll(self, db, monkeypatch):
        _lock(db)
        db.rahaza_attendance_events.docs = [{"id": "ev-x", "employee_id": "emp-a", "date": "2026-10-20",
                                             "status": "alpa"}]
        c = self._ajukan(monkeypatch, "2026-10-20")
        as_user(monkeypatch, HR)
        out = run(corr.approve_correction(c["id"], FakeRequest({})))
        doc = db.rahaza_attendance_corrections.docs[0]
        assert doc["apply_mode"] == "penyesuaian_payroll" and doc["payroll_adjustment"]["status"] == "pending"
        assert doc["locked_run_number"] == "PR-OKT" and "penyesuaian" in out["message"]
        assert db.rahaza_attendance_events.docs[0]["status"] == "alpa"      # absensi terkunci tidak diubah

    def test_validasi_dan_hak(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        assert _status(corr.create_correction(FakeRequest({"date": "2026-11-04", "clock_in": "08:00"}))) == 400
        assert _status(corr.create_correction(FakeRequest({"date": "2026-11-04", "status": "sakit",
                                                           "reason": "x"}))) == 400
        assert _status(corr.create_correction(FakeRequest({"date": "2026-11-04", "employee_id": "emp-b",
                                                           "clock_in": "08:00", "reason": "x"}))) == 403
        c = self._ajukan(monkeypatch)
        assert _status(corr.approve_correction(c["id"], FakeRequest({}))) == 403
        items = run(inbox._fetch_corrections(db, None, 10))
        assert items[0]["type"] == "attendance_correction" and items[0]["meta"]["requested"]["clock_in"] == "07:58"
        as_user(monkeypatch, HR)
        assert _status(corr.reject_correction(c["id"], FakeRequest({}))) == 400        # alasan wajib
        run(inbox.reject_request("attendance_correction", c["id"], inbox.ActionPayload(reason="Tidak ada bukti"),
                                 user=dict(HR)))
        assert db.rahaza_attendance_corrections.docs[0]["status"] == "rejected"


# ═════════════════════════════════════════════════════════════════════════════
# 14 · Migrasi
# ═════════════════════════════════════════════════════════════════════════════
def _migration():
    p = os.path.join(BACKEND, "scripts", "migrations", "2026_11_06_absen_cuti.py")
    spec = importlib.util.spec_from_file_location("absen_cuti_2026_11_06", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrasi:
    def _seed(self, db):
        # cuti lama: sakit 6–9 Nov, disetujui jalur utama, ditulis "cuti" tiap hari kalender, saldo dipotong 4
        db.rahaza_leave_requests.docs = [
            {"id": "old1", "employee_id": "emp-a", "leave_type_id": "lt-sk", "from_date": "2026-11-06",
             "to_date": "2026-11-09", "status": "approved", "duration_days": 4, "request_type": "sakit",
             "approval_step_1": {"action": "approved"}},
            {"id": "old2", "employee_id": "emp-b", "leave_type_id": "lt-ct", "from_date": "2026-11-02",
             "to_date": "2026-11-02", "status": "approved", "duration_days": 1}]       # lewat kotak masuk
        db.rahaza_attendance_events.docs = [
            {"id": f"r{d}", "employee_id": "emp-a", "date": f"2026-11-0{d}", "status": "cuti", "leave_request_id": "old1"}
            for d in (6, 7, 8, 9)]
        db.rahaza_attendance_events.docs[2]["clock_in"] = None
        db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "emp-a", "leave_type_id": "lt-sk", "year": 2026,
                                          "allocated": 14, "used": 4}]

    def test_rencana_murni(self):
        m = _migration()
        rows = [{"id": "a", "date": "2026-11-08", "status": "cuti", "leave_request_id": "L"},
                {"id": "b", "date": "2026-11-09", "status": "cuti", "leave_request_id": "L"},
                {"id": "c", "date": "2026-11-01", "status": "cuti", "leave_request_id": "L", "clock_in": "x"}]
        plan = m.plan_leave({"id": "L", "request_type": "izin", "duration_days": 3,
                             "approval_step_1": {"action": "approved"}}, LT_IZIN, rows,
                            {"2026-11-09", "2026-11-10"}, set())
        assert plan["to_libur"] == 1 and plan["to_kind"] == 1 and plan["skip_own_data"] == 1
        assert plan["missing_days"] == 1 and plan["balance_restore"] == 1.0

    def test_pratinjau_tidak_menulis_apply_idempoten(self, db):
        m = _migration()
        self._seed(db)
        before = [dict(r) for r in db.rahaza_attendance_events.docs]
        prev = run(m.run(False, db=db))
        assert prev["to_libur"] == 1 and prev["to_kind"] == 3 and prev["balance_restore_days"] == 1
        assert prev["balance_manual"] == 1
        assert db.rahaza_attendance_events.docs == before
        run(m.run(True, db=db))
        st = {r["date"]: r["status"] for r in db.rahaza_attendance_events.docs}
        assert st == {"2026-11-06": "sakit", "2026-11-07": "sakit", "2026-11-08": "libur", "2026-11-09": "sakit"}
        assert db.rahaza_leave_balances.docs[0]["used"] == 3
        assert db.rahaza_leave_requests.docs[0]["balance_deducted_days"] == 3
        again = run(m.run(True, db=db))
        assert again["leaves"] == 0 and db.rahaza_leave_balances.docs[0]["used"] == 3


def test_tanggal_uji_konsisten():
    assert date(2026, 11, 8).weekday() == 6 and date(2026, 11, 6).weekday() == 4
