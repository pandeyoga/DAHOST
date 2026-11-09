"""Uji HERMETIK Tahap 7 — audit ujung-ke-ujung Portal Saya ↔ SDM (2026-11-07). Tanpa server/Mongo (FakeDB).

  1 gerbang modul: koreksi absen = swalayan        2 absen masuk/pulang ganda bersamaan
  3 keputusan selfie: pemisahan tugas, klaim atomik, kabar penolakan
  4 kabar keputusan koreksi absen                  5 batal cuti ganda + saldo atomik
  6 saldo Portal Saya = saldo pemeriksaan HR       7 kasbon: identitas SSOT, pembatalan milik sendiri
  8 baca data SDM orang lain (IDOR)                9 penerima kabar: tautan dua arah
"""
import asyncio
import copy
import importlib
import os
import sys

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

import _fake_mongo as fm  # noqa: E402
from _fake_mongo import FakeDB, FakeRequest  # noqa: E402


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


import core.leave_engine as le  # noqa: E402
import routes.dewi_kasbon as kas  # noqa: E402
import routes.hr_approval_inbox as inbox  # noqa: E402
import routes.rahaza_attendance as att  # noqa: E402
import routes.rahaza_auto_attendance_approvals as approvals  # noqa: E402
import routes.rahaza_auto_attendance_selfie as sf  # noqa: E402
import routes.rahaza_leave_balances as lb  # noqa: E402
import routes.rahaza_overtime as ot  # noqa: E402
import utils.employee_identity as ident  # noqa: E402
from data.module_catalog import is_self_service  # noqa: E402

leave_mod = _import_needing_multipart("routes.rahaza_leave")
corr = _import_needing_multipart("routes.rahaza_attendance_corrections")
portal_hr = _import_needing_multipart("routes.dewi_portal_saya_hr")
portal_ext = importlib.import_module("routes.dewi_portal_saya_ext")

run = asyncio.run

HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}
HR2 = {"id": "u-hr2", "role": "hr", "name": "Citra HR", "email": "hr2@x"}
OPS = {"id": "u-ani", "role": "tim_packing", "name": "Ani", "email": "ani@x"}          # tautan users.employee_id
OPS_B = {"id": "u-budi", "role": "operator", "name": "Budi", "email": "budi@x"}        # tautan employees.user_id saja
NOLINK = {"id": "u-x", "role": "operator", "name": "Tanpa Karyawan", "email": "x@x"}
LT_CUTI = {"id": "lt-ct", "code": "CT", "name": "Cuti tahunan", "quota_default": 12, "active": True,
           "unpaid": False, "request_type": "cuti"}
LT_IZIN = {"id": "lt-iz", "code": "IZ", "name": "Izin pribadi", "quota_default": 0, "active": True,
           "unpaid": True, "request_type": "izin"}
MODS = (att, approvals, sf, ot, leave_mod, corr, inbox, portal_hr, portal_ext, lb)


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.rahaza_employees.docs = [
        {"id": "emp-a", "name": "Ani", "employee_code": "E01", "active": True, "user_id": "u-ani", "email": "ani@x"},
        {"id": "emp-b", "name": "Budi", "employee_code": "E02", "active": True, "user_id": "u-budi",
         "email": "budi-lain@x"},
        {"id": "emp-h", "name": "Brenda", "employee_code": "H01", "active": True, "user_id": "u-hr"},
    ]
    d.users.docs = [
        {"id": "u-ani", "email": "ani@x", "role": "tim_packing", "employee_id": "emp-a", "status": "active"},
        {"id": "u-budi", "email": "budi@x", "role": "operator", "employee_id": None, "status": "active"},
        {"id": "u-hr", "email": "hr@x", "role": "hr", "employee_id": "emp-h", "status": "active"},
        {"id": "u-hr2", "email": "hr2@x", "role": "hr", "status": "active"},
    ]
    d.rahaza_leave_types.docs = [dict(LT_CUTI), dict(LT_IZIN)]

    async def noop(*a, **k):
        return None

    for mod in MODS:
        if hasattr(mod, "get_db"):
            monkeypatch.setattr(mod, "get_db", lambda: d)
        if hasattr(mod, "log_activity"):
            monkeypatch.setattr(mod, "log_activity", noop)
    return d


def as_user(monkeypatch, user):
    async def _auth(_request=None, *a, **k):
        return dict(user)
    for m in MODS:
        if hasattr(m, "require_auth"):
            monkeypatch.setattr(m, "require_auth", _auth)


def _status(coro):
    try:
        run(coro)
        return 200
    except HTTPException as e:
        return e.status_code


def stale(db, coll, **changes):
    """`find_one` BERIKUTNYA mengembalikan dokumen lama, lalu dokumen tersimpan diubah (pengguna lain menulis
    di sela baca & tulis handler)."""
    col = db[coll]
    orig = col.find_one
    st = {"done": False}

    async def fo(q=None, projection=None, **kw):
        doc = await orig(q, projection, **kw)
        if doc is not None and not st["done"]:
            st["done"] = True
            for d in col.docs:
                if fm.match(d, q):
                    d.update(copy.deepcopy(changes))
                    break
        return doc
    col.find_one = fo


def _notifs(db, uid):
    return [n for n in db.notifications.docs if n.get("user_id") == uid
            or uid in ((n.get("meta") or {}).get("target_user_ids") or [])]


# ═══ 1 · Gerbang modul ═════════════════════════════════════════════════════════
def test_koreksi_absen_swalayan_lolos_gerbang_modul():
    """Dulu POST koreksi absen ditolak gerbang ("tidak diberi akses Portal SDM") untuk 9 peran staf."""
    assert is_self_service("POST", "/api/rahaza/attendance/corrections")
    assert is_self_service("POST", "/api/rahaza/attendance/corrections/k1/cancel")
    assert not is_self_service("POST", "/api/rahaza/attendance/corrections/k1/approve")
    assert not is_self_service("POST", "/api/rahaza/attendance/corrections/k1/reject")


# ═══ 2 · Absen masuk / pulang ganda bersamaan ═══════════════════════════════════
@pytest.fixture
def selfie(db, monkeypatch):
    import utils.attendance_policy as pol

    async def _emp(db_, user, req=None):
        return {"id": "emp-a", "name": "Ani"}

    async def _late(*a, **k):
        return {"late_minutes": 0, "is_late": False}

    async def _policy(db_, **k):
        return {"office": {}, "geo": {"status": "in_range", "in_range": True, "distance_m": 3}}
    monkeypatch.setattr(ident, "resolve_employee_for", _emp)
    monkeypatch.setattr(ident, "compute_late_minutes", _late)
    monkeypatch.setattr(pol, "enforce_attendance_policy", _policy)
    monkeypatch.setattr(pol, "save_selfie", lambda *a, **k: "/uploads/s.jpg")
    as_user(monkeypatch, OPS)
    return db


def test_absen_masuk_kalah_balapan_tidak_menimpa_jam_masuk(selfie):
    selfie.rahaza_attendance_events.docs = [{"id": "ev1", "employee_id": "emp-a", "date": sf._today_iso(),
                                             "status": "hadir", "clock_in": None}]
    stale(selfie, "rahaza_attendance_events", clock_in="2026-11-07T00:01:00+00:00")   # HP lain lebih dulu
    with pytest.raises(HTTPException) as e:
        run(sf.selfie_clock_in(FakeRequest({"photo_base64": "x"})))
    assert e.value.status_code == 400
    assert selfie.rahaza_attendance_events.docs[0]["clock_in"] == "2026-11-07T00:01:00+00:00"


def test_absen_masuk_bersamaan_tanpa_record_400_bukan_500(selfie, monkeypatch):
    from pymongo.errors import DuplicateKeyError

    async def dup(_doc):
        raise DuplicateKeyError("E11000 duplicate key employee_id_1_date_1")
    monkeypatch.setattr(selfie.rahaza_attendance_events, "insert_one", dup)
    assert _status(sf.selfie_clock_in(FakeRequest({"photo_base64": "x"}))) == 400


def test_absen_pulang_ganda_tidak_menimpa_jam_pulang(selfie, monkeypatch):
    import core.attendance_rules as ar
    rec = {"id": "ev1", "employee_id": "emp-a", "date": sf._today_iso(), "status": "hadir",
           "clock_in": "2026-11-07T00:00:00+00:00", "clock_out": None}
    selfie.rahaza_attendance_events.docs = [dict(rec)]

    async def found(_db, _emp):   # permintaan kedua membaca record yang masih terbuka
        return dict(rec), ""
    monkeypatch.setattr(ar, "find_clock_out_record", found)
    run(sf.selfie_clock_out(FakeRequest({"photo_base64": "x"})))
    first = selfie.rahaza_attendance_events.docs[0]["clock_out"]
    assert _status(sf.selfie_clock_out(FakeRequest({"photo_base64": "x"}))) == 400
    assert selfie.rahaza_attendance_events.docs[0]["clock_out"] == first


# ═══ 3 · Keputusan selfie HR ═══════════════════════════════════════════════════
def _selfie_ev(db, emp="emp-a", status="pending"):
    db.rahaza_attendance_events.docs.append({"id": f"ev-{emp}", "employee_id": emp, "date": "2026-11-05",
                                             "status": "hadir", "approval_status": status})
    return f"ev-{emp}"


def test_hr_tidak_memutus_selfie_absennya_sendiri(db):
    ev = _selfie_ev(db, "emp-h")
    with pytest.raises(HTTPException) as e:
        run(approvals.decide_selfie(db, ev, HR, approve=True))
    assert e.value.status_code == 403 and db.rahaza_attendance_events.docs[0]["approval_status"] == "pending"
    run(approvals.decide_selfie(db, ev, HR2, approve=True))   # HR lain boleh
    assert db.rahaza_attendance_events.docs[0]["approval_status"] == "approved"


def test_selfie_yang_sudah_diputus_tidak_bisa_diputus_ulang(db):
    """Dulu Kotak Masuk SDM 'menolak' selfie yang sudah ditolak/disetujui (tanpa cek status)."""
    ev = _selfie_ev(db, status="rejected")
    assert _status(approvals.decide_selfie(db, ev, HR, approve=False, notes="x")) == 409
    assert _status(inbox.reject_request("attendance", ev, inbox.ActionPayload(reason="x"), user=HR)) == 409


def test_selfie_setuju_tolak_bersamaan_yang_kalah_409(db):
    ev = _selfie_ev(db)
    stale(db, "rahaza_attendance_events", approval_status="approved", status="hadir")   # HR lain lebih dulu
    assert _status(approvals.decide_selfie(db, ev, HR, approve=False, notes="x")) == 409
    assert db.rahaza_attendance_events.docs[0]["approval_status"] == "approved"


def test_selfie_ditolak_mengabari_karyawan(db):
    ev = _selfie_ev(db, "emp-b")   # Budi: tertaut lewat rahaza_employees.user_id saja
    run(approvals.decide_selfie(db, ev, HR, approve=False, notes="Wajah tidak jelas"))
    rec = db.rahaza_attendance_events.docs[0]
    assert rec["status"] == "alpa" and rec["approval_status"] == "rejected"
    (n,) = _notifs(db, "u-budi")
    assert "ditolak" in n["title"] and "Wajah tidak jelas" in n["body"]
    assert (n.get("meta") or {}).get("link_module") == "portal-absen"


def test_hr_tidak_menyetujui_penyesuaian_gajinya_sendiri(db):
    db.rahaza_salary_adjustments.docs = [{"id": "sa1", "employee_id": "emp-h", "status": "pending_hr",
                                          "old_value": 3000000, "new_value": 3500000}]
    assert _status(inbox.approve_request("salary_adjustment", "sa1", inbox.ActionPayload(), user=HR)) == 403
    assert db.rahaza_salary_adjustments.docs[0]["status"] == "pending_hr"


def test_cuti_tingkat1_yang_baru_ditolak_tidak_diteruskan_ke_hr(db):
    db.rahaza_leave_requests.docs = [{"id": "lv9", "employee_id": "emp-a", "leave_type_id": "lt-ct",
                                      "status": "pending_approval", "approval_level_required": 2,
                                      "current_approval_level": 1, "from_date": "2099-03-02", "to_date": "2099-03-12"}]
    stale(db, "rahaza_leave_requests", status="rejected")   # atasan lain menolak di sela baca & tulis
    assert _status(le.approve_leave_request(db, "lv9", HR2)) == 409
    assert db.rahaza_leave_requests.docs[0]["status"] == "rejected"
    assert not [n for n in db.notifications.docs if "Persetujuan HR" in (n.get("title") or "")]


# ═══ 4 · Kabar keputusan koreksi absen ══════════════════════════════════════════
def _corr(db, cid="k1", emp="emp-a"):
    db.rahaza_attendance_corrections.docs.append({
        "id": cid, "employee_id": emp, "date": "2026-11-04", "status": "pending", "created_by": "u-ani",
        "requested": {"status": None, "clock_in": "08:30", "clock_out": "16:00"}, "reason": "lupa absen"})


def test_koreksi_disetujui_dan_ditolak_mengabari_karyawan(db, monkeypatch):
    async def no_lock(*a, **k):
        return None
    monkeypatch.setattr(corr, "attendance_lock", no_lock)
    _corr(db, "k1")
    run(corr.decide_correction(db, "k1", HR, approve=True, note="ok"))
    _corr(db, "k2")
    run(corr.decide_correction(db, "k2", HR, approve=False, note="tanpa bukti"))
    titles = [n["title"] for n in _notifs(db, "u-ani")]
    assert any("disetujui" in t for t in titles) and any("ditolak" in t for t in titles)
    rej = next(n for n in _notifs(db, "u-ani") if "ditolak" in n["title"])
    assert "tanpa bukti" in rej["body"] and rej["meta"]["link_module"] == "portal-absen"


# ═══ 5 · Batal cuti ganda & saldo atomik ════════════════════════════════════════
def _approved_leave(db, lid="lv1", days=3.0):
    doc = {"id": lid, "employee_id": "emp-a", "leave_type_id": "lt-ct", "from_date": "2099-03-02",
           "to_date": "2099-03-04", "status": "approved", "duration_days": days, "balance_deducted_days": days}
    db.rahaza_leave_requests.docs.append(doc)
    return dict(doc)


def test_batal_cuti_ganda_saldo_dikembalikan_sekali(db):
    """Terbukti di DB salinan: cuti 3 hari dibatalkan 3x bersamaan → terpakai 5 → 0 (seharusnya 2)."""
    db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "emp-a", "leave_type_id": "lt-ct",
                                      "year": 2099, "allocated": 12, "used": 5.0}]
    leave = _approved_leave(db)
    run(le.cancel_approved_leave(db, leave, OPS, "batal", is_hr=False))
    with pytest.raises(HTTPException) as e:   # permintaan kedua membawa bacaan lama (status 'approved')
        run(le.cancel_approved_leave(db, leave, OPS, "batal", is_hr=False))
    assert e.value.status_code == 409
    assert db.rahaza_leave_balances.docs[0]["used"] == 2.0
    assert db.rahaza_leave_requests.docs[0]["status"] == "cancelled"
    assert not db.rahaza_leave_requests.docs[0].get("cancel_lock")


def test_batal_pengajuan_menunggu_yang_baru_diputus_409(db, monkeypatch):
    # rute membaca 'pending_approval', lalu HR menyetujui sebelum pembatalan ditulis
    read = {"id": "lv2", "employee_id": "emp-a", "status": "pending_approval", "leave_type_id": "lt-ct",
            "from_date": "2099-03-02", "to_date": "2099-03-02"}
    db.rahaza_leave_requests.docs = [dict(read, status="approved")]
    with pytest.raises(HTTPException) as e:
        run(leave_mod._cancel_pending_leave(db, read, OPS, "batal"))
    assert e.value.status_code == 409 and db.rahaza_leave_requests.docs[0]["status"] == "approved"


def test_potong_saldo_atomik_tidak_hilang_saat_bersamaan(db, monkeypatch):
    db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "emp-a", "leave_type_id": "lt-ct",
                                      "year": 2099, "allocated": 12, "used": 0}]
    orig = lb.get_or_create_balance
    st = {"n": 0}

    async def interleaved(*a, **k):
        doc = await orig(*a, **k)              # bacaan pertama: used = 0
        st["n"] += 1
        if st["n"] == 1:
            await lb.consume_balance(db, "emp-a", "lt-ct", 2099, 3)   # persetujuan lain selesai lebih dulu
        return doc
    monkeypatch.setattr(lb, "get_or_create_balance", interleaved)
    run(lb.consume_balance(db, "emp-a", "lt-ct", 2099, 2))
    assert db.rahaza_leave_balances.docs[0]["used"] == 5   # dulu 2 (potongan 3 hari hilang)


def test_kembalikan_saldo_tidak_minus(db):
    db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "emp-a", "leave_type_id": "lt-ct",
                                      "year": 2099, "allocated": 12, "used": 1}]
    run(lb.restore_balance(db, "emp-a", "lt-ct", 2099, 3))
    assert db.rahaza_leave_balances.docs[0]["used"] == 0


# ═══ 6 · Saldo Portal Saya = saldo pemeriksaan HR ═══════════════════════════════
def test_saldo_portal_tampil_sebelum_dokumen_saldo_ada(db, monkeypatch):
    as_user(monkeypatch, OPS)
    out = run(portal_ext.get_my_leave_balance(FakeRequest()))
    rows = {b["leave_type_id"]: b for b in out["balances"]}
    assert (rows["lt-ct"]["quota"], rows["lt-ct"]["used"], rows["lt-ct"]["remaining"]) == (12, 0, 12)
    assert not db.rahaza_leave_balances.docs          # tanpa menulis
    assert rows["lt-iz"]["unpaid"] and rows["lt-iz"]["remaining"] is None   # dulu "sisa −1,5"


def test_dashboard_sisa_cuti_baris_pertama_cuti_dibayar(db, monkeypatch):
    as_user(monkeypatch, OPS)
    db.rahaza_leave_types.docs.append({"id": "lt-sk", "code": "SK", "name": "A Sakit", "quota_default": 30,
                                       "active": True, "unpaid": False, "request_type": "sakit"})
    db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "emp-a", "leave_type_id": "lt-iz",
                                      "year": __import__("utils.waktu", fromlist=["x"]).today_wib().year,
                                      "allocated": 0, "used": 2}]
    out = run(portal_hr.get_dashboard(FakeRequest()))
    names = [b["type_name"] for b in out["leave_balance"]]
    assert names[0] == "Cuti tahunan" and "Izin pribadi" not in names


def test_jam_absen_dibaca_sebagai_utc_di_layar():
    """Server mengirim jam absen tanpa zona ("…T20:04:45" = UTC); layar dulu membacanya sebagai jam lokal HP →
    absen 03.04 WIB tampil 20.04 (Absen Saya, formulir koreksi, Approval Absen HR)."""
    for name in ("PortalSayaAbsen.jsx", "RahazaAttendanceApprovalModule.jsx"):
        p = os.path.join(REPO, "frontend", "src", "components", "erp", name)
        if not os.path.exists(p):
            pytest.skip("sumber frontend tidak tersedia")
        s = open(p, encoding="utf-8").read()
        fmt = s[s.index("const fmtTime"):][:400]
        assert "parseServerTime" in fmt and "new Date(v)" not in fmt and "new Date(ts)" not in fmt, name


def test_kartu_saldo_jenis_tak_dibayar_tanpa_sisa_di_layar():
    p = os.path.join(REPO, "frontend", "src", "components", "erp", "PortalSayaCuti.jsx")
    if not os.path.exists(p):
        pytest.skip("sumber frontend tidak tersedia")
    s = open(p, encoding="utf-8").read()
    # 2026-11-09 (Q7): jenis per bulan / per kejadian / sakit bersurat juga tanpa "sisa" (remaining = null)
    assert "b.unpaid || b.remaining == null ? b.used : b.remaining" in s and "tidak dibayar" in s


# ═══ 7 · Kasbon Portal Saya ═════════════════════════════════════════════════════
@pytest.fixture
def kasbon_env(db, monkeypatch):
    async def num(*a, **k):
        return "KSB-0001"

    async def no_limit(*a, **k):
        return {"ok": True, "errors": [], "warnings": []}

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(kas, "issue_number", num)
    monkeypatch.setattr(kas, "kasbon_limit_check", no_limit)
    monkeypatch.setattr(kas, "notify_kasbon_stage", noop)
    return db


def test_kasbon_karyawan_tertaut_dari_data_karyawan_tercatat_atas_karyawannya(kasbon_env):
    """Dulu: id AKUN (u-budi) tersimpan sebagai employee_id → potongan gaji tidak pernah menemukan kasbonnya."""
    out = run(kas.submit_kasbon_request(FakeRequest({"type": "kasbon", "amount": 300000}), db=kasbon_env, user=OPS_B))
    assert out["request"]["employee_id"] == "emp-b" and out["request"]["employee_name"] == "Budi"
    mine = run(kas.my_kasbon_requests(db=kasbon_env, user=OPS_B))["requests"]
    assert [r["employee_id"] for r in mine] == ["emp-b"]


def test_kasbon_akun_tanpa_karyawan_pesan_jelas(kasbon_env):
    with pytest.raises(HTTPException) as e:
        run(kas.submit_kasbon_request(FakeRequest({"type": "kasbon", "amount": 1000}), db=kasbon_env, user=NOLINK))
    assert e.value.status_code == 404 and "ditautkan" in e.value.detail
    assert not kasbon_env.dewi_kasbon_requests.docs


def test_kasbon_atas_nama_orang_lain_tetap_ditolak(kasbon_env):
    e = _status(kas.submit_kasbon_request(FakeRequest({"type": "kasbon", "amount": 1000, "employee_id": "emp-b"}),
                                          db=kasbon_env, user=OPS))
    assert e == 403


def test_kasbon_hanya_pemohon_atau_hr_yang_membatalkan(kasbon_env):
    kasbon_env.dewi_kasbon_requests.docs = [{"id": "kb", "employee_id": "emp-a", "status": "submitted",
                                             "submitted_by": "ani@x"}]
    assert _status(kas.cancel_kasbon("kb", FakeRequest({"reason": "x"}), db=kasbon_env, user=OPS_B)) == 403
    assert kasbon_env.dewi_kasbon_requests.docs[0]["status"] == "submitted"
    run(kas.cancel_kasbon("kb", FakeRequest({"reason": "x"}), db=kasbon_env, user=OPS))
    assert kasbon_env.dewi_kasbon_requests.docs[0]["status"] == "cancelled"


def test_kasbon_saya_tidak_mengambil_karyawan_lain_lewat_email(kasbon_env):
    kasbon_env.rahaza_employees.docs.append({"id": "emp-z", "name": "Orang lain", "active": True, "email": "budi@x"})
    kasbon_env.dewi_kasbon_requests.docs = [{"id": "kz", "employee_id": "emp-z", "status": "submitted"}]
    rows = run(kas.my_kasbon_requests(db=kasbon_env, user=OPS_B))["requests"]
    assert rows == []


# ═══ 8 · Membaca data SDM orang lain ════════════════════════════════════════════
@pytest.fixture
def hr_data(db):
    db.rahaza_attendance_events.docs = [
        {"id": "a1", "employee_id": "emp-a", "date": "2026-11-05", "status": "hadir"},
        {"id": "b1", "employee_id": "emp-b", "date": "2026-11-05", "status": "hadir",
         "clock_in_geo": {"lat": -6.2, "lng": 106.8}, "photo_selfie_url": "/uploads/b.jpg"}]
    db.rahaza_leave_requests.docs = [
        {"id": "la", "employee_id": "emp-a", "leave_type_id": "lt-ct", "status": "approved",
         "from_date": "2026-11-02", "to_date": "2026-11-02"},
        {"id": "lb", "employee_id": "emp-b", "leave_type_id": "lt-ct", "status": "approved", "reason": "sakit",
         "attachment_url": "/uploads/surat.pdf", "from_date": "2026-11-03", "to_date": "2026-11-03"}]
    db.rahaza_leave_balances.docs = [
        {"id": "x1", "employee_id": "emp-a", "leave_type_id": "lt-ct", "year": 2026, "allocated": 12, "used": 1},
        {"id": "x2", "employee_id": "emp-b", "leave_type_id": "lt-ct", "year": 2026, "allocated": 12, "used": 1}]
    db.rahaza_overtime_requests.docs = [{"id": "o1", "employee_id": "emp-b", "date": "2026-11-04",
                                         "status": "approved", "hours": 2}]
    return db


def test_staf_hanya_membaca_absensi_dan_cuti_milik_sendiri(hr_data, monkeypatch):
    as_user(monkeypatch, OPS)
    rows = run(att.list_attendance(FakeRequest(), date=None, employee_id=None, from_=None, to=None, status=None))
    assert [r["employee_id"] for r in rows["items"]] == ["emp-a"]
    assert run(att.list_attendance(FakeRequest(), date=None, employee_id="emp-b", from_=None, to=None,
                                   status=None))["items"] == []
    assert _status(att.attendance_grid(FakeRequest(), date="2026-11-05")) == 403
    assert _status(att.my_today(FakeRequest(), employee_id="emp-b")) == 403
    lv = run(leave_mod.list_leaves(FakeRequest(), status=None, employee_id=None, date_from=None, date_to=None))
    assert [r["id"] for r in lv["items"]] == ["la"]
    assert _status(leave_mod.get_leave("lb", FakeRequest())) == 403
    assert _status(leave_mod.get_leave("la", FakeRequest())) == 200
    assert _status(leave_mod.get_leave_balance(FakeRequest(), employee_id="emp-b")) == 403
    bals = run(lb.list_balances(FakeRequest(), employee_id=None, year=None, leave_type_id=None))["balances"]
    assert [b["employee_id"] for b in bals] == ["emp-a"]
    assert run(ot.summary(FakeRequest(), employee_id="emp-b"))["by_employee"] == {}


def test_hr_tetap_membaca_semua(hr_data, monkeypatch):
    as_user(monkeypatch, HR)
    rows = run(att.list_attendance(FakeRequest(), date=None, employee_id=None, from_=None, to=None, status=None))
    assert {r["employee_id"] for r in rows["items"]} == {"emp-a", "emp-b"}
    assert len(run(att.attendance_grid(FakeRequest(), date="2026-11-05"))["rows"]) == 3
    assert run(att.my_today(FakeRequest(), employee_id="emp-b"))["employee_id"] == "emp-b"
    assert _status(leave_mod.get_leave("lb", FakeRequest())) == 200
    assert "emp-b" in run(ot.summary(FakeRequest(), employee_id="emp-b"))["by_employee"]


def test_peran_dengan_portal_sdm_dari_owner_tetap_membaca(hr_data, monkeypatch):
    as_user(monkeypatch, dict(OPS, _portals=["hr"]))
    rows = run(att.list_attendance(FakeRequest(), date=None, employee_id=None, from_=None, to=None, status=None))
    assert len(rows["items"]) == 2


def test_cuti_tanpa_employee_id_untuk_diri_sendiri(db, monkeypatch):
    async def noop(*a, **k):
        return None
    import core.attendance_rules as ar
    monkeypatch.setattr(ar, "attendance_lock", noop)
    out = run(leave_mod.create_leave_request(db, OPS, {"leave_type_id": "lt-ct", "from_date": "2099-03-02",
                                                       "to_date": "2099-03-02", "reason": "urusan keluarga"}))
    assert out["employee_id"] == "emp-a"
    with pytest.raises(HTTPException) as e:
        run(leave_mod.create_leave_request(db, NOLINK, {"leave_type_id": "lt-ct", "from_date": "2099-03-03",
                                                        "to_date": "2099-03-03", "reason": "x"}))
    assert e.value.status_code == 404


# ═══ 9 · Penerima kabar: tautan dua arah ═══════════════════════════════════════
def test_penerima_kabar_dari_kedua_arah_tautan(db):
    assert run(ident.employee_user_ids(db, "emp-a")) == ["u-ani"]
    assert run(ident.employee_user_ids(db, "emp-b")) == ["u-budi"]          # hanya employees.user_id
    db.users.docs[1]["status"] = "inactive"
    assert run(ident.employee_user_ids(db, "emp-b")) == []
    assert run(leave_mod.leave_requester_user_ids(db, {"employee_id": "emp-b", "submitted_by": "u-hr"})) == ["u-hr"]
    db.users.docs[1]["status"] = "active"
    assert run(leave_mod.leave_requester_user_ids(db, {"employee_id": "emp-b", "submitted_by": "u-hr"})) == ["u-budi"]


# ═══════════════════════════════════════════════════════════════════════════════
# KEPUTUSAN OWNER Tahap 7 ("kerjakan semua" = rekomendasi)
#   K1 kasbon sendiri untuk peran marketing  K2 jadwal 8 hari di Absen Saya  K3 Batalkan kasbon/lembur menunggu
#   K4 kabar pencairan kasbon                K5 cuti lintas tahun per tahun + tingkat 2 oleh orang lain
# ═══════════════════════════════════════════════════════════════════════════════
async def _coro(v):
    return v


def test_k3_k2_endpoint_swalayan_lolos_gerbang():
    assert is_self_service("DELETE", "/api/rahaza/overtime/ot1")
    assert is_self_service("POST", "/api/dewi/kasbon/requests/kb1/cancel")
    assert is_self_service("GET", "/api/rahaza/attendance/my-schedule")
    assert not is_self_service("PATCH", "/api/dewi/kasbon/requests/kb1/hr-review")
    assert not is_self_service("PUT", "/api/rahaza/overtime/ot1/approve")


def test_k1_kasbon_peran_marketing_milik_sendiri(kasbon_env):
    mkt = {"id": "u-mkt", "role": "pic_toko", "name": "Mira", "email": "mira@x"}
    kasbon_env.rahaza_employees.docs.append({"id": "emp-m", "name": "Mira", "active": True, "user_id": "u-mkt"})
    out = run(kas.submit_kasbon_request(FakeRequest({"type": "kasbon", "amount": 200000}), db=kasbon_env, user=mkt))
    assert out["request"]["employee_id"] == "emp-m"
    kasbon_env.dewi_kasbon_requests.docs.append({"id": "kz", "employee_id": "emp-a", "status": "submitted"})
    rows = run(kas.list_kasbon_requests(db=kasbon_env, user=mkt, status=None, type=None, employee_id=None,
                                        department=None, page=1, limit=50))["requests"]
    assert [r["employee_id"] for r in rows] == ["emp-m"]   # bukan kasbon orang lain
    assert _status(kas.submit_kasbon_request(FakeRequest({"type": "kasbon", "amount": 1, "employee_id": "emp-a"}),
                                             db=kasbon_env, user=mkt)) == 403


# ── K2 · jadwal 8 hari ─────────────────────────────────────────────────────────
@pytest.fixture
def jadwal(db, monkeypatch):
    from datetime import date as _date
    import routes.rahaza_auto_attendance_config as cfg
    monkeypatch.setattr(cfg, "get_db", lambda: db)
    monkeypatch.setattr(cfg, "today_wib", lambda: _date(2026, 11, 14))          # Sabtu
    monkeypatch.setattr(cfg, "require_auth", lambda *_a, **_k: _coro(dict(OPS)))
    db.rahaza_shifts.docs = [{"id": "s-reg", "code": "REG", "name": "Reguler", "start_time": "08:00",
                              "end_time": "16:00"}]
    db.rahaza_employees.docs[0]["shift_id"] = "s-reg"
    db.rahaza_schedules.docs = [
        {"id": "j1", "status": "published", "start_date": "2026-11-16", "end_date": "2026-11-16",
         "published_at": "2026-11-10", "shifts": [{"employee_id": "emp-a", "date": "2026-11-16", "start_time": "07:00",
                                                   "end_time": "15:00", "shift_code": "S1", "shift_name": "Shift 1"}]},
        {"id": "j2", "status": "draft", "start_date": "2026-11-19", "end_date": "2026-11-19",
         "shifts": [{"employee_id": "emp-a", "date": "2026-11-19", "start_time": "13:00", "shift_code": "X"}]}]
    db.rahaza_production_calendar.docs = [{"date": "2026-11-17", "type": "holiday", "name": "Cuti bersama uji",
                                           "kind": "cuti_bersama"}]
    db.rahaza_attendance_events.docs = [{"id": "c1", "employee_id": "emp-a", "date": "2026-11-18", "status": "cuti",
                                         "leave_request_id": "lv", "leave_kind": "cuti", "leave_type_name": "Tahunan"}]
    return cfg


def test_k2_jadwal_dari_sumber_yang_sama_dengan_terlambat(jadwal, db):
    out = run(jadwal.get_my_schedule(FakeRequest()))
    days = {d["date"]: d for d in out["days"]}
    assert len(out["days"]) == 8 and out["days"][0]["today"] and out["work_days_per_week"] == 6
    assert days["2026-11-14"]["kind"] == "kerja" and days["2026-11-14"]["shift"]["code"] == "REG"   # Sabtu kerja
    assert days["2026-11-15"]["kind"] == "libur" and days["2026-11-15"]["label"] == "Libur mingguan"
    assert days["2026-11-15"]["shift"] is None
    assert days["2026-11-16"]["shift"]["start_time"] == "07:00" and days["2026-11-16"]["shift"]["source"] == "jadwal"
    assert days["2026-11-17"]["kind"] == "libur" and days["2026-11-17"]["label"] == "Cuti bersama"
    assert days["2026-11-17"]["note"] == "Cuti bersama uji"
    assert days["2026-11-18"]["kind"] == "cuti" and days["2026-11-18"]["shift"] is None
    assert days["2026-11-18"]["label"] == "Cuti" and days["2026-11-18"]["note"] == "Tahunan"
    assert days["2026-11-19"]["shift"]["code"] == "REG"            # jadwal DRAFT tidak berlaku
    # satu sumber: terlambat hari itu dihitung dari jam yang sama dengan kartu jadwal
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    late = run(ident.compute_late_minutes(db, {"id": "emp-a", "shift_id": "s-reg"},
                                          _dt(2026, 11, 16, 7, 30, tzinfo=_tz(_td(hours=7)))))
    assert late["shift_start"] == "07:00" and late["late_minutes"] == 25


def test_k2_jadwal_karyawan_lain_hanya_hr(jadwal, monkeypatch):
    assert _status(jadwal.get_my_schedule(FakeRequest(), employee_id="emp-b")) == 403
    monkeypatch.setattr(jadwal, "require_auth", lambda *_a, **_k: _coro(dict(HR)))
    assert run(jadwal.get_my_schedule(FakeRequest(), employee_id="emp-a"))["employee_id"] == "emp-a"


def test_k2_kartu_jadwal_di_absen_saya():
    p = os.path.join(REPO, "frontend", "src", "components", "erp", "PortalSayaAbsen.jsx")
    if not os.path.exists(p):
        pytest.skip("sumber frontend tidak tersedia")
    s = open(p, encoding="utf-8").read()
    assert "/api/rahaza/attendance/my-schedule" in s and 'data-testid="absen-schedule"' in s


# ── K3 · Batalkan lembur menunggu ─────────────────────────────────────────────
def test_k3_batalkan_lembur_milik_sendiri_yang_menunggu(db, monkeypatch):
    as_user(monkeypatch, OPS_B)   # Budi tertaut lewat rahaza_employees.user_id saja
    db.rahaza_overtime_requests.docs = [
        {"id": "o1", "employee_id": "emp-b", "status": "pending", "submitted_by": "u-hr"},   # diajukan HR atas namanya
        {"id": "o2", "employee_id": "emp-a", "status": "pending", "submitted_by": "u-ani"},
        {"id": "o3", "employee_id": "emp-b", "status": "approved", "submitted_by": "u-budi"}]
    run(ot.cancel_request("o1", FakeRequest()))
    assert db.rahaza_overtime_requests.docs[0]["status"] == "cancelled"
    assert _status(ot.cancel_request("o2", FakeRequest())) == 403
    assert _status(ot.cancel_request("o3", FakeRequest())) == 409
    db.rahaza_overtime_requests.docs.append({"id": "o4", "employee_id": "emp-b", "status": "pending",
                                             "submitted_by": "u-budi"})
    stale(db, "rahaza_overtime_requests", status="approved")   # HR menyetujui di sela baca & tulis
    assert _status(ot.cancel_request("o4", FakeRequest())) == 409
    assert db.rahaza_overtime_requests.docs[3]["status"] == "approved"


def test_k3_tombol_batalkan_di_layar():
    base = os.path.join(REPO, "frontend", "src", "components", "erp")
    if not os.path.exists(base):
        pytest.skip("sumber frontend tidak tersedia")
    cuti = open(os.path.join(base, "PortalSayaCuti.jsx"), encoding="utf-8").read()
    kasb = open(os.path.join(base, "KasbonStaffModule.jsx"), encoding="utf-8").read()
    assert "ot.status === 'pending'" in cuti and "/api/rahaza/overtime/${id}" in cuti and "cancelOT" in cuti
    assert "req.status === 'submitted'" in kasb and "/cancel" in kasb and "confirmDialog" in kasb


# ── K4 · kabar pencairan kasbon ───────────────────────────────────────────────
def test_k4_pencairan_kasbon_mengabari_karyawan(kasbon_env, monkeypatch):
    import routes.rahaza_posting_profiles as pp

    async def acc(*a, **k):
        return {"gl_code": "1-1101", "name": "Kas Kecil", "cash_account_id": "ca"}

    async def gl(*a, **k):
        return {"ok": True, "je_id": "je1", "je_number": "JE-1"}

    async def mapping(*a, **k):
        return {"credit_cash": "1-1101"}
    monkeypatch.setattr(kas, "resolve_payment_account", acc)
    monkeypatch.setattr(kas, "_post_kasbon_gl", gl)
    monkeypatch.setattr(pp, "get_mapping", mapping)
    kasbon_env.dewi_kasbon_requests.docs = [{"id": "kb", "request_number": "KSB-9", "employee_id": "emp-b",
                                             "status": "hr_approved", "amount": 500000.0, "type_label": "Kasbon",
                                             "installment_count": 1}]
    fin = {"id": "u-fin", "role": "accounting", "name": "Fina", "email": "fin@x"}
    run(kas.finance_disburse("kb", FakeRequest({"disbursement_date": "2026-11-05", "deduction_start_period": "2026-12"}),
                             db=kasbon_env, user=fin))
    (n,) = [x for x in _notifs(kasbon_env, "u-budi") if x.get("subtype") == "kasbon_disbursed"]
    assert n["title"] == "Kasbon dicairkan Rp 500.000, dipotong mulai periode Desember 2026"
    assert n["meta"]["link_module"] == "portal-kasbon"


def test_k4_label_periode():
    from utils.waktu import periode_label
    assert periode_label("2026-11") == "November 2026" and periode_label("2027-01-31") == "Januari 2027"
    assert periode_label("2026-00") == "2026-00" and periode_label(None) == "-"


# ── K5 · cuti lintas tahun & tingkat 2 ────────────────────────────────────────
def _cross_year_leave(db, lid="ly", **kw):
    doc = {"id": lid, "employee_id": "emp-a", "leave_type_id": "lt-ct", "from_date": "2026-12-30",
           "to_date": "2027-01-04", "status": "pending_approval", "approval_level_required": 1,
           "current_approval_level": 1, "reason": "liburan", "submitted_by": "u-ani", **kw}
    db.rahaza_leave_requests.docs.append(doc)
    return doc


def _used(db, year):
    b = next((x for x in db.rahaza_leave_balances.docs if x["year"] == year), None)
    return (b or {}).get("used")


def test_k5_cuti_lintas_tahun_memakai_saldo_per_tahun(db):
    db.rahaza_leave_balances.docs = [{"id": "b26", "employee_id": "emp-a", "leave_type_id": "lt-ct", "year": 2026,
                                      "allocated": 12, "used": 4}]
    _cross_year_leave(db)
    run(le.approve_leave_request(db, "ly", HR, pay_decision="paid"))
    lv = db.rahaza_leave_requests.docs[0]
    # 30 & 31 Des (2026) · 1, 2, 4 Jan (2027; 3 Jan Minggu)
    assert lv["balance_deducted_by_year"] == {"2026": 2.0, "2027": 3.0} and lv["balance_deducted_days"] == 5
    assert (_used(db, 2026), _used(db, 2027)) == (6, 3)
    run(le.cancel_approved_leave(db, lv, HR, "batal", is_hr=True))
    assert (_used(db, 2026), _used(db, 2027)) == (4, 0)


def test_k5_saldo_tahun_berikutnya_kurang_ditolak_dengan_tahunnya(db):
    db.rahaza_leave_balances.docs = [{"id": "b27", "employee_id": "emp-a", "leave_type_id": "lt-ct", "year": 2027,
                                      "allocated": 12, "used": 10}]
    _cross_year_leave(db)
    with pytest.raises(HTTPException) as e:
        run(le.approve_leave_request(db, "ly", HR, pay_decision="paid"))
    assert e.value.status_code == 400 and "tahun 2027" in e.value.detail and "tahun 2026" not in e.value.detail
    assert db.rahaza_leave_requests.docs[0]["status"] == "pending_approval"


def test_k5_tingkat2_tidak_boleh_penyetuju_tingkat1(db):
    _cross_year_leave(db, lid="l2", from_date="2099-03-02", to_date="2099-03-02", approval_level_required=2,
                      current_approval_level=2, status="pending_hr_approval",
                      approval_step_1={"step": 1, "approver_id": "u-hr", "action": "approved"})
    with pytest.raises(HTTPException) as e:
        run(le.approve_leave_request(db, "l2", HR, pay_decision="paid"))
    assert e.value.status_code == 409 and "tingkat 2" in e.value.detail
    run(le.approve_leave_request(db, "l2", HR2, pay_decision="paid"))
    assert db.rahaza_leave_requests.docs[0]["status"] == "approved"
