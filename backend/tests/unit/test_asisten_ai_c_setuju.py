"""Uji agen SETUJU Asisten AI Tahap C (8 Nov 2026): alat persetujuan risiko menengah.

Hermetik: Mongo palsu + `ctx` perekam yang meneruskan setiap `ctx.api` ke FUNGSI ROUTE SUNGGUHAN (Kotak Masuk
SDM, mesin cuti `core.leave_engine`, lembur, Permintaan Pengadaan, Request Aksesoris, Purchase Order, Portal
Saya › Profil) sebagai pengguna ctx itu. HTTPException → AlatError dengan pesan ramah yang sama dengan
`AlatContext.api`. Jadi aturan siapa-boleh-memutus yang diuji di sini adalah aturan endpoint itu sendiri.

Yang dibuktikan: penyetuju sah berhasil; ajuan sendiri ditolak; peran salah ditolak; sudah diputus → 409; tahap
bergeser sejak kartu dibuat → 409; alasan kartu dikirim sebagai catatan/alasan penolakan; aturan CV (Gabungan
ditolak, CV lain diberi peringatan); `siapkan` hanya membaca; inti meneruskan alasan (`ctx.alasan`); perbaikan P9
Request Aksesoris (tulis bersyarat → 409); alat baca hanya menampilkan yang bisa diputus pengguna itu.
"""
from __future__ import annotations

import asyncio
import copy
import importlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

import auth  # noqa: E402
import database  # noqa: E402
from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai import tindakan as tdk  # noqa: E402
from core.asisten_ai.alat_base import AlatError  # noqa: E402
from core.asisten_ai.alat import tindakan_persetujuan as TP  # noqa: E402


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


import routes.hr_approval_inbox as inbox  # noqa: E402
import routes.rahaza_overtime as ot  # noqa: E402
import routes.dewi_procurement as dp  # noqa: E402
import routes.dewi_accessories_purchase as accp  # noqa: E402
import routes.rahaza_po as rpo  # noqa: E402

leave_mod = _import_needing_multipart("routes.rahaza_leave")
portal_hr = _import_needing_multipart("routes.dewi_portal_saya_hr")


def run(c):
    return asyncio.run(c)


def U(uid, role, **kw):
    return {"id": uid, "name": f"Uji {uid}", "email": f"{uid}@contoh.test", "role": role, **kw}


OWNER = U("u-own", "owner")
HR = U("u-hr", "hr")
HR2 = U("u-hr2", "hr")
MGR = U("u-mgr", "manager")
MGR2 = U("u-mgr2", "manager")
OPS = U("u-ops", "operator")
PACK = U("u-pack", "tim_packing")
GDG1 = U("u-gdg1", "admin_gudang")
GDG2 = U("u-gdg2", "admin_gudang")
FIN = U("u-fin", "accounting")
ALASAN = "Sudah dicek dengan jadwal tim, aman."

EMP = [
    {"id": "emp-a", "name": "Ani Contoh", "employee_code": "E01", "active": True, "user_id": "u-ops",
     "department": "Produksi"},
    {"id": "emp-h", "name": "Hana Contoh", "employee_code": "H01", "active": True, "user_id": "u-hr",
     "department": "SDM"},
    {"id": "emp-m", "name": "Mira Contoh", "employee_code": "M01", "active": True, "user_id": "u-mgr",
     "department": "Produksi"},
    {"id": "emp-p", "name": "Pandu Contoh", "employee_code": "P01", "active": True, "user_id": "u-pack",
     "department": "Gudang"},
    {"id": "emp-g1", "name": "Gita Contoh", "employee_code": "G01", "active": True, "user_id": "u-gdg1",
     "department": "Gudang"},
    {"id": "emp-g2", "name": "Galih Contoh", "employee_code": "G02", "active": True, "user_id": "u-gdg2",
     "department": "Gudang"},
    {"id": "emp-f", "name": "Fajar Contoh", "employee_code": "F01", "active": True, "user_id": "u-fin",
     "department": "Keuangan"},
]
LT_CUTI = {"id": "lt-ct", "code": "ANNUAL", "name": "Cuti tahunan", "quota_default": 12, "active": True,
           "unpaid": False, "request_type": "cuti"}
LT_IZIN = {"id": "lt-iz", "code": "PERSONAL", "name": "Izin pribadi", "quota_default": 3, "active": True,
           "unpaid": False, "request_type": "izin"}

AKTIF: dict = {"user": None}


class Req(FakeRequest):
    query_params: dict = {}


# ── ctx perekam → fungsi route sungguhan ─────────────────────────────────────────────────────────────────
def _rute():
    def appr(fn_ok, fn_no):
        return lambda c, m, p, j: (fn_ok if m[2] == "approve" else fn_no)(m[1], Req(j or {}))
    return [
        ("GET", r"/api/hr/inbox", lambda c, m, p, j: inbox.list_inbox(
            type_filter=p.get("type"), limit_per_type=int(p.get("limit_per_type") or 50), user=dict(c.user))),
        ("POST", r"/api/hr/inbox/(\w+)/([^/]+)/approve", lambda c, m, p, j: inbox.approve_request(
            m[1], m[2], inbox.ActionPayload(**(j or {})), user=dict(c.user))),
        ("POST", r"/api/hr/inbox/(\w+)/([^/]+)/reject", lambda c, m, p, j: inbox.reject_request(
            m[1], m[2], inbox.ActionPayload(**(j or {})), user=dict(c.user))),
        ("GET", r"/api/rahaza/leaves/([^/]+)/approval-preview",
         lambda c, m, p, j: leave_mod.leave_approval_preview(m[1], Req())),
        ("GET", r"/api/rahaza/leaves/([^/]+)", lambda c, m, p, j: leave_mod.get_leave(m[1], Req())),
        ("GET", r"/api/rahaza/overtime", lambda c, m, p, j: ot.list_overtime(
            Req(), status=None, employee_id=None, date_from=None, date_to=None, limit=int(p.get("limit") or 200))),
        ("GET", r"/api/portal/profile", lambda c, m, p, j: portal_hr.get_profile(Req())),
        ("GET", r"/api/procurement/inbox", lambda c, m, p, j: dp.get_approval_inbox(
            Req(), scope=p.get("scope") or "relevant", department=None)),
        ("GET", r"/api/procurement/requests", lambda c, m, p, j: dp.list_requests(
            Req(), page=1, limit=int(p.get("limit") or 20), status=None, my_only=False, search=p.get("search"),
            priority=None, sort_by="created_at", sort_dir="desc")),
        ("GET", r"/api/procurement/requests/([^/]+)", lambda c, m, p, j: dp.get_request(m[1], Req())),
        ("POST", r"/api/procurement/requests/([^/]+)/(approve|reject)", appr(dp.approve_request, dp.reject_request)),
        ("GET", r"/api/acc/purchase-requests", lambda c, m, p, j: accp.list_purchase_requests(Req())),
        ("GET", r"/api/acc/purchase-requests/([^/]+)", lambda c, m, p, j: accp.get_purchase_request(m[1], Req())),
        ("POST", r"/api/acc/purchase-requests/([^/]+)/(approve|reject)",
         appr(accp.approve_purchase_request, accp.reject_purchase_request)),
        ("GET", r"/api/rahaza/purchase-orders", lambda c, m, p, j: rpo.list_pos(
            Req(), status=None, vendor=None, supplier_id=None, search=p.get("search"), date_from=None, date_to=None,
            page=1, limit=50, paginate=False)),
        ("GET", r"/api/rahaza/purchase-orders/([^/]+)", lambda c, m, p, j: rpo.get_po(m[1], Req())),
        ("POST", r"/api/rahaza/purchase-orders/([^/]+)/(approve|reject)", appr(rpo.approve_po, rpo.reject_po)),
    ]


RUTE = _rute()


class RuteCtx:
    """`ctx` palsu: merekam panggilan `api` lalu menjalankan route sungguhan sebagai `self.user`."""

    def __init__(self, user, cv="DA", alasan="", baca_saja=False):
        self.user, self.cv, self.alasan, self.baca_saja = dict(user), cv, alasan, baca_saja
        self.today = date(2026, 11, 8)
        self.calls: list = []

    @property
    def tulis(self):
        return [c for c in self.calls if c[0] != "GET"]

    def mask(self, obj, **kw):
        return ab.AlatContext(user=self.user, cv=self.cv, today=self.today).mask(obj, **kw)

    async def api(self, method, path, params=None, json=None, **kw):
        method = method.upper()
        self.calls.append((method, path, dict(params or {}), copy.deepcopy(json)))
        if self.baca_saja and method != "GET":
            raise AssertionError(f"siapkan menulis: {method} {path}")
        for mth, rx, fn in RUTE:
            m = re.fullmatch(rx, path)
            if mth == method and m:
                AKTIF["user"] = dict(self.user)
                try:
                    out = await fn(self, m, dict(params or {}), json)
                except HTTPException as e:
                    raise AlatError(e.status_code, ab._pesan_status(e.status_code, {"detail": e.detail})) from None
                return jsonable_encoder(out)
        raise AssertionError(f"panggilan tak terduga {method} {path}")


async def _auth(_request=None, *a, **k):
    return dict(AKTIF["user"])


async def _noop(*_a, **_k):
    return None


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.rahaza_employees.docs = copy.deepcopy(EMP)
    d.users.docs = [{**u, "is_active": True, "status": "active"}
                    for u in (OWNER, HR, HR2, MGR, MGR2, OPS, PACK, GDG1, GDG2, FIN)]
    d.rahaza_leave_types.docs = [dict(LT_CUTI), dict(LT_IZIN)]
    for mod in (inbox, ot, dp, accp, rpo, leave_mod, portal_hr, auth, database):
        monkeypatch.setattr(mod, "get_db", lambda: d, raising=False)
    for mod in (ot, dp, accp, rpo, leave_mod, portal_hr, auth):
        monkeypatch.setattr(mod, "require_auth", _auth)
    for mod in (inbox, rpo, leave_mod):
        monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(dp, "_notify_procurement_event", _noop)   # kanal obrolan Pengadaan (bukan aturan)
    auth._rbac_cache.clear()
    return d


def K(nama):
    ab.muat_semua_alat()
    return ab._DAFTAR[nama].kelas


def A(nama):
    ab.muat_semua_alat()
    return ab._DAFTAR[nama]


def siapkan(nama, user, args, **kw):
    ctx = RuteCtx(user, baca_saja=True, **kw)
    r = run(K(nama).siapkan(ctx, dict(args)))
    assert not ctx.tulis
    return _cek_rencana(nama, r, args), ctx


def jalankan(nama, user, args, rencana, alasan=ALASAN, **kw):
    ctx = RuteCtx(user, alasan=alasan, **kw)
    return run(K(nama).jalankan(ctx, dict(args), rencana)), ctx


def galat(coro):
    with pytest.raises(AlatError) as e:
        run(coro)
    return e.value


def _cek_rencana(nama, r, args):
    """Rencana sah untuk kartu: diterima `rapikan_rencana` inti, ≤ 8k, tanpa istilah program."""
    out = tdk.rapikan_rencana(r, args, A(nama))
    assert out["judul"] and out["perubahan"] and out["catatan"]
    teks = json.dumps(out, ensure_ascii=False)
    assert len(teks) <= 8000 and "None" not in teks and "Traceback" not in teks
    for istilah in ("pending_approval", "pending_hr_approval", "dept_approved", "finance_approved", "approve",
                    "_id", "hr.approve"):
        assert istilah not in teks, istilah
    assert out["tautan"]["menu"] in (A(nama).menu, "proc-accessory-pr")
    return out


# ── data uji ─────────────────────────────────────────────────────────────────────────────────────────────
def _cuti(db, lid="lv1", emp="emp-a", lt="lt-ct", f="2026-11-09", t="2026-11-11", **kw):
    doc = {"id": lid, "employee_id": emp, "leave_type_id": lt, "from_date": f, "to_date": t,
           "status": "pending_approval", "approval_level_required": 1, "current_approval_level": 1,
           "reason": "Acara keluarga", "submitted_by": "u-ops", "created_by": "u-ops",
           "created_at": datetime(2026, 11, 7, 3, tzinfo=timezone.utc), "duration_days": 3,
           "duration_working_days": 3, **kw}
    db.rahaza_leave_requests.docs.append(doc)
    return doc


def _lembur(db, oid="ot1", emp="emp-a", by="u-ops", **kw):
    doc = {"id": oid, "employee_id": emp, "date": "2026-11-07", "start_time": "17:00", "end_time": "20:00",
           "hours": 3, "rate_multiplier": 1.5, "reason": "Kejar target kirim", "status": "pending",
           "submitted_by": by, "created_at": datetime(2026, 11, 7, 12, tzinfo=timezone.utc), **kw}
    db.rahaza_overtime_requests.docs.append(doc)
    return doc


def _pr(db, pid="pr1", total=5_000_000.0, chain=("dept", "finance"), **kw):
    doc = {"id": pid, "request_number": "PR-UJI-001", "title": "Kancing plastik 18 mm", "status": "submitted",
           "requested_by": "u-gdg1", "requested_by_name": "Gita Contoh", "department": "Gudang",
           "total_estimated": total, "approval_chain": list(chain), "current_approver_stage": "dept",
           "approval_steps": [{"id": "s0", "step": "submit", "stage": None, "actor_id": "u-gdg1",
                               "action": "submitted"}],
           "items": [{"id": "it1", "name": "Kancing plastik", "qty": 1000, "uom": "pcs", "total_price": total}],
           "submitted_at": "2026-11-07T03:00:00+00:00", "created_at": "2026-11-07T02:00:00+00:00", **kw}
    db.dewi_procurement_requests.docs.append(doc)
    return doc


def _acc(db, aid="acc1", **kw):
    doc = {"id": aid, "pr_number": "ACC-UJI-001", "purpose": "Benang jahit hitam", "status": "Submitted",
           "requested_by": "u-gdg1", "requested_by_name": "Gita Contoh", "department": "Gudang",
           "total_estimated": 300000.0, "approval_chain": ["dept"], "current_approver_stage": "dept",
           "approval_steps": [], "items": [{"acc_name": "Benang", "qty_requested": 10, "estimated_price": 30000}],
           "submitted_at": "2026-11-07T03:00:00+00:00", "created_at": "2026-11-07T02:00:00+00:00", **kw}
    db.acc_purchase_requests.docs.append(doc)
    return doc


def _po(db, pid="po1", total=500_000.0, chain=("dept",), **kw):
    doc = {"id": pid, "po_number": "PO-UJI-001", "vendor_name": "PT Pemasok Contoh", "status": "pending_approval",
           "created_by": "u-gdg1", "requested_by": "u-gdg1", "created_by_name": "Gita Contoh",
           "approval_chain": list(chain), "current_approver_stage": "dept", "po_date": "2026-11-07",
           "approval_steps": [{"id": "s0", "step": "submit", "stage": None, "actor_id": "u-gdg1",
                               "action": "submitted"}],
           "items": [{"id": "pi1", "description": "Kain katun", "qty_ordered": 10, "unit_cost": total / 10,
                      "uom": "m"}],
           "total_value": total, "submitted_at": "2026-11-07T04:00:00+00:00",
           "created_at": "2026-11-07T03:00:00+00:00", **kw}
    db.rahaza_purchase_orders.docs.append(doc)
    return doc


def _satu(db, coll, did):
    return next(d for d in db[coll].docs if d["id"] == did)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 0. Kontrak D
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
NAMA = ("putuskan_cuti", "putuskan_lembur", "putuskan_pr", "putuskan_po_pembelian")


def test_alat_terdaftar_risiko_menengah_tanpa_pembalikan():
    for n in NAMA:
        a = A(n)
        assert a.adalah_tindakan and a.risiko == "menengah" and a.menu, n
        assert not a.bisa_dibalikkan and not hasattr(a.kelas, "batalkan"), n
        assert a.input_schema["additionalProperties"] is False and "keputusan" in a.input_schema["required"]
        assert "Tidak bisa dibalikkan" in a.description and TP.__name__ in a.asal
        assert ab.AWALAN_MENENGAH in a.untuk_api()["description"]
    assert "maklon" in A("putuskan_po_pembelian").description.lower()
    baca = A("daftar_persetujuan_menunggu")
    assert baca.kind == "read" and not baca.adalah_tindakan
    nama_api = [t["name"] for t in ab.tools_untuk_api()]
    assert "daftar_persetujuan_menunggu" in nama_api and not set(NAMA) & set(nama_api)
    assert set(NAMA) <= {t["name"] for t in ab.tools_untuk_api(tindakan=True)}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1. Cuti
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_cuti_penyetuju_sah_alasan_jadi_catatan_dan_efek_terbaca_di_layar(db):
    _cuti(db)
    args = {"id": "lv1", "keputusan": "setujui", "pembayaran": "dibayar"}
    r, ctx = siapkan("putuskan_cuti", HR, args)
    teks = json.dumps(r, ensure_ascii=False)
    assert r["judul"] == "Setujui cuti Ani Contoh" and "3 hari kerja" in r["ringkas"]
    tabel = {p["label"]: (p["sebelum"], p["sesudah"]) for p in r["perubahan"]}
    assert tabel[TP.LABEL_TAHAP] == ("Menunggu atasan", "Disetujui")
    assert tabel["Saldo Cuti tahunan 2026"] == ("12 hari", "9 hari")
    assert tabel["Pembayaran"] == ("—", "Dibayar (usulan sistem)") and "9, 10, 11 Nov 2026" in teks
    assert r["ubah"][0]["kunci"] == "pembayaran" and "Acara keluarga" in teks
    assert {c[1] for c in ctx.calls} == {"/api/hr/inbox", "/api/portal/profile",
                                         "/api/rahaza/leaves/lv1/approval-preview"}
    out, ctx2 = jalankan("putuskan_cuti", HR, args, r)
    assert ctx2.tulis == [("POST", "/api/hr/inbox/leave/lv1/approve", {},
                           {"note": ALASAN, "pay_decision": "paid"})]
    assert out["pembatalan"] is None and "disetujui" in out["ringkas"] and "Ani" not in out["ringkas"]
    lv = _satu(db, "rahaza_leave_requests", "lv1")
    assert lv["status"] == "approved" and lv["approval_note"] == ALASAN and lv["approved_via"] == "kotak_masuk"
    assert lv["approval_step_1"]["notes"] == ALASAN and lv["approval_step_1"]["approver_id"] == "u-hr"
    assert db.rahaza_leave_balances.docs[0]["used"] == 3.0
    assert sorted(x["date"] for x in db.rahaza_attendance_events.docs) == ["2026-11-09", "2026-11-10", "2026-11-11"]
    # dibaca lewat endpoint layar biasa: hilang dari kotak masuk, detail = disetujui
    lihat = RuteCtx(HR)
    assert run(lihat.api("GET", "/api/hr/inbox", {"type": "leave"}))["items"] == []
    assert run(lihat.api("GET", "/api/rahaza/leaves/lv1"))["status"] == "approved"


def test_cuti_tolak_alasan_dikirim_sebagai_alasan_penolakan(db):
    _cuti(db)
    args = {"id": "lv1", "keputusan": "tolak"}
    r, _ = siapkan("putuskan_cuti", MGR, args)
    assert r["judul"].startswith("Tolak") and r["perubahan"][0]["sesudah"] == "Ditolak"
    assert any("MENOLAK" in c for c in r["catatan"])
    out, ctx = jalankan("putuskan_cuti", MGR, args, r, alasan="Kuota tim penuh minggu itu.")
    assert ctx.tulis[0][1:] == ("/api/hr/inbox/leave/lv1/reject", {}, {"reason": "Kuota tim penuh minggu itu."})
    lv = _satu(db, "rahaza_leave_requests", "lv1")
    assert lv["status"] == "rejected" and lv["rejected_reason"] == "Kuota tim penuh minggu itu."
    assert db.rahaza_leave_balances.docs == [] and db.rahaza_attendance_events.docs == []
    with pytest.raises(AlatError):
        run(K("putuskan_cuti").siapkan(RuteCtx(MGR), {"id": "lv1", "keputusan": "tolak", "pembayaran": "dibayar"}))


def test_cuti_ajuan_sendiri_ditolak_kartu_dan_endpoint(db):
    _cuti(db, emp="emp-h", submitted_by="u-hr")
    e = galat(K("putuskan_cuti").siapkan(RuteCtx(HR, baca_saja=True), {"id": "lv1", "keputusan": "setujui"}))
    assert e.status == 403 and "sendiri" in e.pesan
    # kartu dilewati (mis. siapkan versi lama): endpoint sendiri tetap menolak, tanpa tulisan
    e = galat(K("putuskan_cuti").jalankan(RuteCtx(HR, alasan=ALASAN), {"id": "lv1", "keputusan": "setujui"},
                                          {"perubahan": []}))
    assert e.status == 403 and "Pemisahan tugas" in e.pesan
    assert _satu(db, "rahaza_leave_requests", "lv1")["status"] == "pending_approval"


def test_cuti_peran_salah_ditolak(db):
    _cuti(db)
    for u in (PACK, OPS, FIN):
        e = galat(K("putuskan_cuti").siapkan(RuteCtx(u, baca_saja=True), {"id": "lv1", "keputusan": "setujui"}))
        assert e.status == 403 and "bukan penyetuju Kotak Masuk SDM" in e.pesan, u["role"]
        e = galat(K("putuskan_cuti").jalankan(RuteCtx(u, alasan=ALASAN), {"id": "lv1", "keputusan": "tolak"},
                                              {"perubahan": []}))
        assert e.status == 403
    assert _satu(db, "rahaza_leave_requests", "lv1")["status"] == "pending_approval"


def test_cuti_sudah_diputus_409_dan_kartu_basi_409(db):
    _cuti(db, status="approved")
    e = galat(K("putuskan_cuti").siapkan(RuteCtx(HR, baca_saja=True), {"id": "lv1", "keputusan": "setujui"}))
    assert e.status == 409 and "Disetujui" in e.pesan
    # kartu dibuat, lalu orang lain memutus lebih dulu → jalankan 409, tanpa tulis kedua
    _cuti(db, lid="lv2")
    args = {"id": "lv2", "keputusan": "setujui"}
    r, _ = siapkan("putuskan_cuti", HR, args)
    run(inbox.reject_request("leave", "lv2", inbox.ActionPayload(reason="Ditolak HR lain"), user=dict(HR2)))
    e = galat(K("putuskan_cuti").jalankan(RuteCtx(HR, alasan=ALASAN), args, r))
    assert e.status == 409 and "Ditolak" in e.pesan
    assert _satu(db, "rahaza_leave_requests", "lv2")["rejected_reason"] == "Ditolak HR lain"
    # tahap bergeser sejak kartu dibuat (tingkat 1 disetujui orang lain) → 409, tidak menyetujui tingkat 2
    _cuti(db, lid="lv3", t="2026-11-18", approval_level_required=2)
    args = {"id": "lv3", "keputusan": "setujui"}
    r, _ = siapkan("putuskan_cuti", MGR, args)
    run(inbox.approve_request("leave", "lv3", inbox.ActionPayload(note="ok"), user=dict(MGR2)))
    e = galat(K("putuskan_cuti").jalankan(RuteCtx(MGR, alasan=ALASAN), args, r))
    assert e.status == 409 and "berubah sejak kartu dibuat" in e.pesan
    assert _satu(db, "rahaza_leave_requests", "lv3")["status"] == "pending_hr_approval"


def test_cuti_dua_tingkat_tingkat_2_oleh_orang_lain(db):
    _cuti(db, t="2026-11-18", approval_level_required=2)       # 9 hari kerja → 2 tingkat
    args = {"id": "lv1", "keputusan": "setujui"}
    r, _ = siapkan("putuskan_cuti", MGR, args)
    assert r["perubahan"][0] == {"label": TP.LABEL_TAHAP, "sebelum": "Menunggu atasan (tingkat 1 dari 2)",
                                 "sesudah": "Menunggu SDM (tingkat 2 dari 2)"}
    assert not r["ubah"] and len(r["perubahan"]) == 1               # saldo & absensi belum disentuh
    e = galat(K("putuskan_cuti").siapkan(RuteCtx(MGR), {**args, "pembayaran": "dibayar"}))
    assert e.status == 400 and "tingkat 1" in e.pesan
    out, _ = jalankan("putuskan_cuti", MGR, args, r)
    assert "tingkat 1" in out["ringkas"] and out["hasil"]["status_baru"] == "Menunggu SDM"
    assert db.rahaza_leave_balances.docs == []
    # orang yang sama di tingkat 2 → ditolak di kartu (cermin aturan mesin) dan di endpoint
    e = galat(K("putuskan_cuti").siapkan(RuteCtx(MGR, baca_saja=True), args))
    assert e.status == 409 and "tingkat 2 harus oleh orang lain" in e.pesan
    e = galat(K("putuskan_cuti").jalankan(RuteCtx(MGR, alasan=ALASAN), args,
                                          {"perubahan": [{"label": TP.LABEL_TAHAP,
                                                          "sebelum": "Menunggu SDM (tingkat 2 dari 2)"}]}))
    assert e.status == 409 and "tingkat 2" in e.pesan
    args2 = {**args, "pembayaran": "tidak_dibayar"}
    r2, _ = siapkan("putuskan_cuti", HR, args2)
    assert {p["label"]: p["sesudah"] for p in r2["perubahan"]}["Pembayaran"] == "Tidak dibayar"
    jalankan("putuskan_cuti", HR, args2, r2)
    lv = _satu(db, "rahaza_leave_requests", "lv1")
    assert lv["status"] == "approved" and lv["pay_decision"] == "unpaid"
    assert lv["approval_step_1"]["approver_id"] == "u-mgr" and lv["approval_step_2"]["notes"] == ALASAN
    assert db.rahaza_leave_balances.docs == []                    # tidak dibayar → jatah tidak terpakai


def test_cuti_saldo_kurang_untuk_dibayar_ditolak_di_kartu(db):
    _cuti(db, lt="lt-iz", f="2026-11-09", t="2026-11-14", attachment_url="/api/uploads/x.pdf")  # 6 > jatah 3
    e = galat(K("putuskan_cuti").siapkan(RuteCtx(HR), {"id": "lv1", "keputusan": "setujui"}))
    assert e.status == 400 and "Sisa cuti tidak cukup" in e.pesan and "tidak_dibayar" in e.pesan
    r, _ = siapkan("putuskan_cuti", HR, {"id": "lv1", "keputusan": "setujui", "pembayaran": "tidak_dibayar"})
    assert not any(p["label"].startswith("Saldo") for p in r["perubahan"])


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 2. Lembur
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_lembur_setujui_tolak_ajuan_sendiri_peran_dan_409(db):
    _lembur(db)
    args = {"id": "ot1", "keputusan": "setujui"}
    r, _ = siapkan("putuskan_lembur", HR, args)
    assert r["judul"] == "Setujui lembur Ani Contoh" and "3 jam" in r["ringkas"] and "17:00–20:00" in r["ringkas"]
    assert {p["label"]: p["sesudah"] for p in r["perubahan"]}["Payroll"].startswith("3 jam lembur × pengali 1,5")
    out, ctx = jalankan("putuskan_lembur", HR, args, r)
    assert ctx.tulis == [("POST", "/api/hr/inbox/overtime/ot1/approve", {}, {"note": ALASAN})]
    o = _satu(db, "rahaza_overtime_requests", "ot1")
    assert o["status"] == "approved" and o["approval_note"] == ALASAN and o["approved_by"] == "u-hr"
    assert run(RuteCtx(HR).api("GET", "/api/rahaza/overtime"))["overtime"][0]["status"] == "approved"
    e = galat(K("putuskan_lembur").siapkan(RuteCtx(HR2), args))
    assert e.status == 409 and "Disetujui" in e.pesan
    e = galat(K("putuskan_lembur").jalankan(RuteCtx(HR2, alasan=ALASAN), args, r))
    assert e.status == 409
    # tolak → alasan penolakan
    _lembur(db, oid="ot2")
    a2 = {"id": "ot2", "keputusan": "tolak"}
    r2, _ = siapkan("putuskan_lembur", MGR, a2)
    jalankan("putuskan_lembur", MGR, a2, r2, alasan="Tidak ada order mendesak.")
    assert _satu(db, "rahaza_overtime_requests", "ot2")["rejected_reason"] == "Tidak ada order mendesak."
    # diajukan akun penyetuju sendiri (atas nama karyawan lain) → ditolak; peran salah → ditolak
    _lembur(db, oid="ot3", by="u-hr")
    e = galat(K("putuskan_lembur").siapkan(RuteCtx(HR), {"id": "ot3", "keputusan": "setujui"}))
    assert e.status == 403 and "sendiri" in e.pesan
    e = galat(K("putuskan_lembur").jalankan(RuteCtx(HR, alasan=ALASAN), {"id": "ot3", "keputusan": "setujui"}, {}))
    assert e.status == 403 and _satu(db, "rahaza_overtime_requests", "ot3")["status"] == "pending"
    e = galat(K("putuskan_lembur").siapkan(RuteCtx(PACK), {"id": "ot3", "keputusan": "setujui"}))
    assert e.status == 403 and "bukan penyetuju" in e.pesan


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 3. Permintaan pembelian
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_pr_dua_tahap_penyetuju_sah_alasan_jadi_komentar(db):
    _pr(db)
    args = {"nomor": "pr-uji-001", "keputusan": "setujui"}
    r, ctx = siapkan("putuskan_pr", GDG2, args)
    tabel = {p["label"]: (p["sebelum"], p["sesudah"]) for p in r["perubahan"]}
    assert tabel[TP.LABEL_TAHAP] == ("Persetujuan Departemen (tahap 1 dari 2)",
                                     "Persetujuan Keuangan (tahap 2 dari 2)")
    assert "Rp 5.000.000" in r["ringkas"] and not r["peringatan"]
    assert any("Kancing plastik 1.000 pcs (Rp 5.000.000)" in c for c in r["catatan"])
    out, ctx2 = jalankan("putuskan_pr", GDG2, args, r)
    assert ctx2.tulis == [("POST", "/api/procurement/requests/pr1/approve", {}, {"comment": ALASAN})]
    assert "diteruskan ke Persetujuan Keuangan" in out["ringkas"] and out["hasil"]["status_baru"] == "dept_approved"
    pr = _satu(db, "dewi_procurement_requests", "pr1")
    assert pr["status"] == "dept_approved" and pr["approval_steps"][-1]["comment"] == ALASAN
    # kartu yang sama ditekan lagi (tahap sudah bergeser) → 409 "berubah", bukan menyetujui tahap keuangan
    e = galat(K("putuskan_pr").jalankan(RuteCtx(GDG2, alasan=ALASAN), args, r))
    assert e.status == 409 and "berubah sejak kartu dibuat" in e.pesan and len(ctx2.tulis) == 1
    # tahap 2: penyetuju tahap 1 tidak boleh lagi (dua tahap / bukan peran keuangan); keuangan boleh
    e = galat(K("putuskan_pr").siapkan(RuteCtx(GDG2), {"id": "pr1", "keputusan": "setujui"}))
    assert e.status == 403 and ("dua tahap" in e.pesan or "keuangan" in e.pesan)
    r2, _ = siapkan("putuskan_pr", FIN, {"id": "pr1", "keputusan": "setujui"})
    assert r2["perubahan"][0]["sesudah"] == "Disetujui penuh"
    out2, _ = jalankan("putuskan_pr", FIN, {"id": "pr1", "keputusan": "setujui"}, r2)
    assert "disetujui penuh" in out2["ringkas"]
    assert run(RuteCtx(FIN).api("GET", "/api/procurement/requests/pr1"))["status"] == "approved"
    e = galat(K("putuskan_pr").siapkan(RuteCtx(FIN), {"id": "pr1", "keputusan": "tolak"}))
    assert e.status == 409 and "Disetujui" in e.pesan


def test_pr_ajuan_sendiri_peran_salah_departemen_ditolak_dan_override_owner_diberi_peringatan(db):
    _pr(db)
    a = {"id": "pr1", "keputusan": "setujui"}
    e = galat(K("putuskan_pr").siapkan(RuteCtx(GDG1), a))
    assert e.status == 403 and "pembuat" in e.pesan                                  # ajuan sendiri
    e = galat(K("putuskan_pr").jalankan(RuteCtx(GDG1, alasan=ALASAN), a, {}))
    assert e.status == 403
    e = galat(K("putuskan_pr").siapkan(RuteCtx(PACK), a))
    assert e.status == 403 and "berhak" in e.pesan                                    # bukan peran tahap
    e = galat(K("putuskan_pr").siapkan(RuteCtx(MGR), a))
    assert e.status == 403 and "departemen" in e.pesan                                # Produksi ≠ Gudang
    assert _satu(db, "dewi_procurement_requests", "pr1")["status"] == "submitted"
    r, _ = siapkan("putuskan_pr", OWNER, a)
    assert r["peringatan"] and "override" in r["peringatan"][0] and "bukan peran tahap" in r["peringatan"][0]
    out, _ = jalankan("putuskan_pr", OWNER, a, r)
    assert "override" in out["ringkas"] and out["hasil"]["override"] is True
    assert _satu(db, "dewi_procurement_requests", "pr1")["approval_steps"][-1]["override"] is True


def test_pr_tolak_tidak_ditemukan_dan_basi(db):
    _pr(db)
    a = {"id": "pr1", "keputusan": "tolak"}
    r, _ = siapkan("putuskan_pr", GDG2, a)
    jalankan("putuskan_pr", GDG2, a, r, alasan="Stok kancing masih cukup dua bulan.")
    pr = _satu(db, "dewi_procurement_requests", "pr1")
    assert pr["status"] == "rejected" and pr["rejection_reason"] == "Stok kancing masih cukup dua bulan."
    e = galat(K("putuskan_pr").jalankan(RuteCtx(GDG2, alasan=ALASAN), a, r))
    assert e.status == 409
    assert galat(K("putuskan_pr").siapkan(RuteCtx(GDG2), {"nomor": "PR-TIDAK-ADA", "keputusan": "tolak"})).status == 404
    assert galat(K("putuskan_pr").siapkan(RuteCtx(GDG2), {"keputusan": "tolak"})).status == 400


def test_request_aksesoris_lama_lewat_mesin_yang_sama(db):
    _acc(db)
    a = {"nomor": "ACC-UJI-001", "keputusan": "setujui"}
    r, _ = siapkan("putuskan_pr", GDG2, a)
    assert r["tautan"]["menu"] == "proc-accessory-pr" and r["perubahan"][0]["sesudah"] == "Disetujui penuh"
    out, ctx = jalankan("putuskan_pr", GDG2, a, r)
    assert ctx.tulis[0][1:] == ("/api/acc/purchase-requests/acc1/approve", {}, {"comment": ALASAN})
    d = _satu(db, "acc_purchase_requests", "acc1")
    assert d["status"] == "Approved" and d["approval_steps"][-1]["comment"] == ALASAN
    assert galat(K("putuskan_pr").siapkan(RuteCtx(GDG1), {"id": "acc1", "keputusan": "tolak"})).status == 409


def test_perbaikan_p9_request_aksesoris_tulis_bersyarat(db):
    """Setujui/tolak Request Aksesoris dulu menulis tanpa syarat: dokumen yang baru diputus pengguna lain
    di sela baca & tulis tetap ditimpa (tahap tercatat dua kali / penolakan tertimpa). Sekarang 409."""
    _acc(db)
    col = db.acc_purchase_requests
    asli = col.find_one
    st = {"sekali": False}

    async def basi(q=None, projection=None, **kw):     # bacaan handler = dokumen lama; lalu orang lain menolak
        d = await asli(q, projection, **kw)
        if not st["sekali"] and d:
            st["sekali"] = True
            await col.update_one({"id": "acc1"}, {"$set": {"status": "Rejected", "current_approver_stage": None}})
        return d
    col.find_one = basi
    AKTIF["user"] = dict(GDG2)
    with pytest.raises(HTTPException) as e:
        run(accp.approve_purchase_request("acc1", Req({"comment": "ok"})))
    assert e.value.status_code == 409
    d = _satu(db, "acc_purchase_requests", "acc1")
    assert d["status"] == "Rejected" and d["approval_steps"] == []
    st["sekali"] = False
    col.docs[0].update(status="Submitted", current_approver_stage="dept")
    with pytest.raises(HTTPException) as e:
        run(accp.reject_purchase_request("acc1", Req({"reason": "tidak perlu"})))
    assert e.value.status_code == 409 and _satu(db, "acc_purchase_requests", "acc1")["approval_steps"] == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 4. PO pembelian
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_po_setujui_tolak_ajuan_sendiri_peran_409_dan_bukan_maklon(db):
    _po(db)
    a = {"nomor": "PO-UJI-001", "keputusan": "setujui"}
    r, _ = siapkan("putuskan_po_pembelian", MGR, a)
    assert r["judul"] == "Setujui PO pembelian PO-UJI-001" and "PT Pemasok Contoh" in r["ringkas"]
    assert r["perubahan"][0] == {"label": TP.LABEL_TAHAP, "sebelum": "Persetujuan Pengadaan (tahap 1 dari 1)",
                                 "sesudah": "Disetujui penuh"}
    assert any("tidak membuat jurnal" in c for c in r["catatan"])
    out, ctx = jalankan("putuskan_po_pembelian", MGR, a, r)
    assert ctx.tulis == [("POST", "/api/rahaza/purchase-orders/po1/approve", {}, {"comment": ALASAN})]
    po = _satu(db, "rahaza_purchase_orders", "po1")
    assert po["status"] == "approved" and po["approval_steps"][-1]["comment"] == ALASAN
    assert run(RuteCtx(MGR).api("GET", "/api/rahaza/purchase-orders/po1"))["status"] == "approved"
    e = galat(K("putuskan_po_pembelian").siapkan(RuteCtx(MGR2), {"id": "po1", "keputusan": "setujui"}))
    assert e.status == 409 and "Disetujui" in e.pesan
    _po(db, pid="po2", po_number="PO-UJI-002")
    e = galat(K("putuskan_po_pembelian").siapkan(RuteCtx(GDG1), {"id": "po2", "keputusan": "setujui"}))
    assert e.status == 403 and "pembuat" in e.pesan
    e = galat(K("putuskan_po_pembelian").siapkan(RuteCtx(PACK), {"id": "po2", "keputusan": "tolak"}))
    assert e.status == 403
    r2, _ = siapkan("putuskan_po_pembelian", GDG2, {"id": "po2", "keputusan": "tolak"})
    jalankan("putuskan_po_pembelian", GDG2, {"id": "po2", "keputusan": "tolak"}, r2, alasan="Harga di atas pasar.")
    assert _satu(db, "rahaza_purchase_orders", "po2")["rejected_reason"] == "Harga di atas pasar."
    _po(db, pid="po3", po_number="PO-UJI-003", business_type="maklon")
    e = galat(K("putuskan_po_pembelian").siapkan(RuteCtx(OWNER), {"id": "po3", "keputusan": "setujui"}))
    assert e.status == 403 and "maklon" in e.pesan


def test_po_melebihi_pr_dan_tahap_bergeser(db):
    _po(db, total=5_000_000.0, chain=("dept", "finance"), exceeds_pr_value=True, pr_approved_value=800000,
        from_pr_number="PR-UJI-009")
    a = {"id": "po1", "keputusan": "setujui"}
    r, _ = siapkan("putuskan_po_pembelian", MGR, a)
    assert "melebihi nilai PR" in r["peringatan"][0] and "Rp 800.000" in r["peringatan"][0]
    assert r["perubahan"][0]["sesudah"] == "Persetujuan Keuangan (tahap 2 dari 2)"
    AKTIF["user"] = dict(GDG2)
    run(rpo.approve_po("po1", Req({"comment": "lebih dulu"})))      # orang lain menyetujui tahap 1 lebih dulu
    e = galat(K("putuskan_po_pembelian").jalankan(RuteCtx(FIN, alasan=ALASAN), a, r))
    assert e.status == 409 and "berubah sejak kartu dibuat" in e.pesan
    assert _satu(db, "rahaza_purchase_orders", "po1")["status"] == "pending_approval"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 5. Aturan CV, alasan, dan sambungan ke inti
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_cv_gabungan_ditolak_cv_lain_diberi_peringatan(db):
    _cuti(db)
    _lembur(db)
    _pr(db)
    _po(db)
    kasus = {"putuskan_cuti": {"id": "lv1"}, "putuskan_lembur": {"id": "ot1"}, "putuskan_pr": {"id": "pr1"},
             "putuskan_po_pembelian": {"id": "po1"}}
    for nama, a in kasus.items():
        for fn in (K(nama).siapkan(RuteCtx(OWNER, cv="ALL"), {**a, "keputusan": "setujui"}),
                   K(nama).jalankan(RuteCtx(OWNER, cv="ALL", alasan=ALASAN), {**a, "keputusan": "setujui"}, {})):
            e = galat(fn)
            assert e.status == 400 and "Gabungan" in e.pesan, nama
    r, _ = siapkan("putuskan_pr", GDG2, {"id": "pr1", "keputusan": "setujui"}, cv="SMU")
    assert any("CV Dewi Aditya" in p and "CV Sukma" in p for p in r["peringatan"])
    r, _ = siapkan("putuskan_po_pembelian", MGR, {"id": "po1", "keputusan": "setujui"}, cv="SMU")
    assert any("CV Dewi Aditya" in p for p in r["peringatan"])
    r, _ = siapkan("putuskan_po_pembelian", MGR, {"id": "po1", "keputusan": "setujui"}, cv="DA")
    assert not r["peringatan"]
    for p in (db.rahaza_leave_requests.docs[0], db.rahaza_overtime_requests.docs[0],
              db.dewi_procurement_requests.docs[0], db.rahaza_purchase_orders.docs[0]):
        assert p["status"] in ("pending_approval", "pending", "submitted")


def test_tanpa_alasan_jalankan_menolak(db):
    _lembur(db)
    r, _ = siapkan("putuskan_lembur", HR, {"id": "ot1", "keputusan": "setujui"})
    e = galat(K("putuskan_lembur").jalankan(RuteCtx(HR, alasan="  "), {"id": "ot1", "keputusan": "setujui"}, r))
    assert e.status == 400 and "Alasan" in e.pesan
    assert _satu(db, "rahaza_overtime_requests", "ot1")["status"] == "pending"


def test_inti_meneruskan_alasan_kartu_ke_alat(db):
    """`tdk.laksanakan` (jalur Setujui di kartu) mengisi `ctx.alasan`; alat mengirimnya sebagai catatan."""
    _lembur(db)
    a = A("putuskan_lembur")
    args = {"id": "ot1", "keputusan": "setujui"}
    rencana = tdk.rapikan_rencana(run(a.siapkan(RuteCtx(HR, baca_saja=True), dict(args))), args, a)
    doc = {"id": "t-1", "user_id": HR["id"], "nama": a.name, "label": a.label, "risiko": "menengah",
           "keadaan": "menunggu", "args": args, "rencana": rencana, "tool_use_id": "toolu_1",
           tdk.KUNCI: "kunci-1", f"{tdk.KUNCI}_at": datetime.now(timezone.utc)}
    db.ai_actions.docs.append(dict(doc))
    p = tdk.Putusan(doc=doc, alat=a, keputusan="setujui", kunci="kunci-1", alasan="Lembur sesuai target mingguan",
                    args=args, rencana=rencana)
    ctx = RuteCtx(HR)                       # alasan BELUM ada di ctx — inti yang mengisinya
    kabar: list = []
    akhir = run(tdk.laksanakan(db, p, ctx, user=HR, kirim=kabar.append))
    assert akhir["keadaan"] == "dijalankan" and [k["keadaan"] for k in kabar] == ["disetujui", "dijalankan"]
    assert ctx.tulis[0][3] == {"note": "Lembur sesuai target mingguan"}
    assert _satu(db, "rahaza_overtime_requests", "ot1")["approval_note"] == "Lembur sesuai target mingguan"
    rec = _satu(db, "ai_actions", "t-1")
    assert rec["keadaan"] == "dijalankan" and rec["alasan"] == "Lembur sesuai target mingguan"
    assert rec["bisa_dibalikkan"] is False and rec["pembatalan"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 6. Alat baca: daftar_persetujuan_menunggu
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
async def _daftar(user, **args):
    ctx = RuteCtx(user, baca_saja=True)
    out = await TP.daftar_persetujuan_menunggu(ctx, dict(args))
    assert not ctx.tulis and len(json.dumps(out, ensure_ascii=False, default=str)) <= ab.BATAS_HASIL
    return out


def test_daftar_hanya_yang_bisa_diputus_pengguna_ini(db):
    _cuti(db)                                                           # Ani — HR boleh
    _cuti(db, lid="lv-h", emp="emp-h", f="2026-11-20", t="2026-11-20", submitted_by="u-hr")   # milik HR sendiri
    _cuti(db, lid="lv-2", emp="emp-p", f="2026-11-09", t="2026-11-18", approval_level_required=2,
          current_approval_level=2, status="pending_hr_approval",
          approval_step_1={"approver_id": "u-hr", "approver_name": "Uji u-hr"})     # tingkat 1 oleh HR sendiri
    _lembur(db)
    _pr(db)
    _po(db)
    out = run(_daftar(HR))
    assert [c["id"] for c in out["cuti"]] == ["lv1"] and out["cuti"][0]["pemohon"] == "Ani Contoh"
    assert out["cuti"][0]["usulan_pembayaran"] == "dibayar" and out["cuti"][0]["alasan"] == "Acara keluarga"
    assert out["tidak_bisa_anda_putuskan"]["cuti"] == {"ajuan_sendiri": 1, "tingkat_1_sudah_anda_setujui": 1}
    assert [x["id"] for x in out["lembur"]] == ["ot1"] and out["jumlah"]["pr"] == 0 and out["jumlah"]["po"] == 0
    # manajer: nama disamarkan (K27), PO tahap pengadaan boleh, PR Gudang tidak (departemen Produksi)
    out = run(_daftar(MGR))
    assert out["cuti"][0]["pemohon"].startswith("KRY-") and "alasan" not in out["cuti"][0]
    assert {c["id"] for c in out["cuti"]} == {"lv1", "lv-h", "lv-2"} and "catatan_nama" in out
    assert out["jumlah"]["pr"] == 0 and [p["nomor"] for p in out["po"]] == ["PO-UJI-001"]
    # admin gudang lain: PR + PO; pembuatnya sendiri: tidak keduanya; staf packing: tidak ada apa pun
    out = run(_daftar(GDG2, jenis=["pr", "po"]))
    assert [p["nomor"] for p in out["pr"]] == ["PR-UJI-001"] and out["pr"][0]["nilai_rp"] == 5000000
    assert out["pr"][0]["tahap"] == "Persetujuan Departemen (tahap 1 dari 2)" and "override" not in out["pr"][0]
    out = run(_daftar(GDG1, jenis=["pr", "po"]))
    assert out["jumlah"] == {"pr": 0, "po": 0}
    out = run(_daftar(PACK))
    assert out["jumlah"] == {"pr": 0, "po": 0} and any("bukan penyetuju" in c for c in out["catatan"])
    # owner: semua, bertanda override bila menembus aturan
    out = run(_daftar(OWNER, jenis=["pr"]))
    assert out["pr"][0]["override"] and "bukan peran tahap" in out["pr"][0]["override"]
