"""Master SDM & Keuangan (+ Lokasi gudang) bisa diubah & dihapus (permintaan owner 10 Nov 2026) — hermetik (FakeDB).

Kata owner: "klien tidak bisa di edit tidak bisa dihapus jangan seperti ini, harus bisa, jadi lihat semua yang seperti
ini pastikan table table master data bisa dihapus."

Pola (sama dengan `test_hapus_master.py`): `DELETE …?hard=true` menghapus permanen bila master BELUM dipakai,
menolak 409 + kalimat "sudah dipakai di …" bila sudah (layar menawarkan Nonaktifkan lewat lib/hapusMaster), tanpa
`hard` perilaku lama (menonaktifkan) tidak berubah. Endpoint yang dulu sudah hapus permanen TANPA cek (unit & jabatan
organisasi, tunjangan) kini memeriksa pemakaian. Jalur hapus permanen master yang menonaktifkannya boleh semua staf
(lokasi, lini, mesin, shift, karyawan) dijaga peran pengelola modulnya.

Tambahan keputusan owner 10 Nov: lokasi KANTOR (lokasi kerja karyawan) memakai master `rahaza_locations` yang sama
tetapi dikelola di SDM › Lokasi kerja — layar Lokasi gudang menyaringnya keluar; kantor boleh punya induk kantor dan
tidak boleh punya peran gudang.
"""
import asyncio
import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
FE = REPO / "frontend" / "src"
ADMIN = {"id": "u-admin", "name": "Admin Uji", "role": "admin"}
HR = {"id": "u-hr", "name": "HR Uji", "role": "hr"}
GUDANG = {"id": "u-gd", "name": "Gudang Uji", "role": "admin_gudang"}
OPERATOR = {"id": "u-op", "name": "Operator Uji", "role": "operator"}


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def _as(user):
    async def _f(*_a, **_k):
        return dict(user)
    return _f


def fe(rel: str) -> str:
    return (FE / rel).read_text(encoding="utf-8")


def _import(name):
    """Rute unggah memeriksa python-multipart saat impor — dilewati bila tidak terpasang (pola test_tahap4_koleksi)."""
    try:
        return importlib.import_module(name)
    except RuntimeError:
        import fastapi.dependencies.utils as _fdu
        checks = {n: getattr(_fdu, n) for n in ("check_file_field", "ensure_multipart_is_installed") if hasattr(_fdu, n)}
        for n in checks:
            setattr(_fdu, n, lambda *a, **k: None)
        try:
            return importlib.import_module(name)
        finally:
            for n, fn in checks.items():
                setattr(_fdu, n, fn)


def _409(coro, *frasa):
    with pytest.raises(HTTPException) as e:
        run(coro)
    assert e.value.status_code == 409, e.value.detail
    for f in frasa:
        assert f in e.value.detail, (f, e.value.detail)
    assert "Nonaktifkan" in e.value.detail
    return e.value.detail


def _status(coro):
    try:
        run(coro)
    except HTTPException as e:
        return e.status_code
    return 200


# ══════════════════════════════ rahaza_master: lokasi, lini, mesin, shift, karyawan ══════════════════════════════
@pytest.fixture
def master(monkeypatch):
    import routes.rahaza_master as mod
    db = fm.FakeDB()
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    user = {"u": dict(ADMIN)}

    async def _req(_request):
        return dict(user["u"])
    monkeypatch.setattr(mod, "_require_admin", _req)
    return mod, db, user


# ── Lokasi gudang ──
def _lokasi(db):
    db.rahaza_locations.docs = [{"id": "L1", "code": "ZNA-KAIN", "name": "Area Kain", "type": "zona", "active": True}]


def test_lokasi_belum_dipakai_dihapus(master):
    mod, db, _u = master
    _lokasi(db)
    out = run(mod.deactivate_location("L1", fm.FakeRequest(), hard=True))
    assert out["deleted"] is True and db.rahaza_locations.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_material_stock", {"id": "s1", "material_id": "m1", "location_id": "L1", "qty": 0}, "baris stok bahan"),
    ("rahaza_material_movements", {"id": "mv1", "to_location_id": "L1"}, "mutasi stok"),
    ("rahaza_stock_ledger", {"id": "k1", "location_id": "L1"}, "kartu stok"),
    ("rahaza_fg_movements", {"id": "f1", "from_location_id": "L1"}, "mutasi barang jadi"),
    ("rahaza_material_issues", {"id": "i1", "items": [{"location_id": "x"}, {"location_id": "L1"}]}, "permintaan bahan"),
    ("rahaza_locations", {"id": "L2", "code": "RAK-1", "name": "Rak 1", "parent_id": "L1"}, "zona/lokasi anak"),
    ("rahaza_employees", {"id": "e1", "name": "Ani", "location_id": "L1"}, "karyawan"),
    ("rahaza_schedules", {"id": "j1", "location_id": "L1", "shifts": []}, "jadwal shift"),
])
def test_lokasi_dipakai_ditolak_409(master, koleksi, doc, label):
    mod, db, _u = master
    _lokasi(db)
    getattr(db, koleksi).docs.append(doc)
    _409(mod.deactivate_location("L1", fm.FakeRequest(), hard=True), label, "Area Kain")
    assert any(d["id"] == "L1" for d in db.rahaza_locations.docs)


def test_lokasi_tanpa_hard_tetap_nonaktifkan(master):
    mod, db, _u = master
    _lokasi(db)
    run(mod.deactivate_location("L1", fm.FakeRequest()))
    assert db.rahaza_locations.docs[0]["active"] is False


def test_lokasi_hapus_permanen_hanya_pengelola(master):
    mod, db, user = master
    _lokasi(db)
    db.rahaza_locations.docs.append({"id": "K1", "code": "KTR-PST", "name": "Kantor Pusat", "type": "kantor", "active": True})
    user["u"] = dict(OPERATOR)
    assert _status(mod.deactivate_location("L1", fm.FakeRequest(), hard=True)) == 403
    run(mod.deactivate_location("L1", fm.FakeRequest()))          # menonaktifkan tetap boleh semua staf
    user["u"] = dict(HR)                                           # gedung/zona = pengelola gudang
    assert _status(mod.deactivate_location("L1", fm.FakeRequest(), hard=True)) == 403
    user["u"] = dict(GUDANG)                                       # kantor (lokasi kerja) = SDM
    assert _status(mod.deactivate_location("K1", fm.FakeRequest(), hard=True)) == 403
    assert _status(mod.deactivate_location("L1", fm.FakeRequest(), hard=True)) == 200
    user["u"] = dict(HR)
    assert _status(mod.deactivate_location("K1", fm.FakeRequest(), hard=True)) == 200
    assert db.rahaza_locations.docs == []


def test_lokasi_kantor_dipakai_karyawan_ditolak(master):
    mod, db, _u = master
    db.rahaza_locations.docs = [{"id": "K1", "code": "KTR-PST", "name": "Kantor Pusat", "type": "kantor", "active": True}]
    db.rahaza_employees.docs = [{"id": "e1", "name": "Ani", "location_id": "K1"}]
    _409(mod.deactivate_location("K1", fm.FakeRequest(), hard=True), "1 karyawan", "Kantor Pusat")


def test_lokasi_kantor_boleh_dibuat_dengan_induk_tanpa_peran_gudang(master):
    mod, db, _u = master
    db.rahaza_locations.docs = [{"id": "K1", "code": "KTR-PST", "name": "Kantor Pusat", "type": "kantor", "active": True}]
    out = run(mod.create_location(fm.FakeRequest({"code": "ktr-adm", "name": "Ruang Admin", "type": "kantor",
                                                  "parent_id": "K1"})))
    assert out["type"] == "kantor" and out["parent_id"] == "K1" and out["storage_role"] is None
    with pytest.raises(HTTPException) as e:
        run(mod.create_location(fm.FakeRequest({"code": "KTR-X", "name": "Ruang X", "type": "kantor",
                                                "storage_role": "fg"})))
    assert e.value.status_code == 400 and "peran gudang" in e.value.detail
    # gedung tetap tanpa induk; jenis lain ditolak dengan kalimat staf
    g = run(mod.create_location(fm.FakeRequest({"code": "GED-C", "name": "Gedung C", "type": "gedung", "parent_id": "K1"})))
    assert g["parent_id"] is None
    with pytest.raises(HTTPException) as e:
        run(mod.create_location(fm.FakeRequest({"code": "X", "name": "X", "type": "pabrik"})))
    assert e.value.status_code == 400 and "gedung, zona, atau kantor" in e.value.detail


def test_lokasi_kantor_tidak_bisa_diberi_peran_gudang_lewat_ubah(master):
    mod, db, _u = master
    db.rahaza_locations.docs = [{"id": "K1", "code": "KTR-PST", "name": "Kantor Pusat", "type": "kantor", "active": True},
                                {"id": "Z1", "code": "ZNA-FG", "name": "Area FG", "type": "zona", "storage_role": "fg"}]
    with pytest.raises(HTTPException) as e:
        run(mod.update_location("K1", fm.FakeRequest({"storage_role": "fg"})))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:   # zona berperan gudang diganti jadi kantor → ditolak
        run(mod.update_location("Z1", fm.FakeRequest({"type": "kantor"})))
    assert e.value.status_code == 400
    run(mod.update_location("K1", fm.FakeRequest({"name": "Kantor Pusat Sragen", "type": "kantor"})))
    assert db.rahaza_locations.docs[0]["name"] == "Kantor Pusat Sragen"


# ── Lini & mesin ──
def test_lini_dan_mesin(master):
    mod, db, user = master
    db.rahaza_lines.docs = [{"id": "LN1", "code": "L1", "name": "Line 1", "active": True},
                            {"id": "LN2", "code": "L2", "name": "Line 2", "active": True}]
    db.rahaza_machines.docs = [{"id": "M1", "code": "MS1", "name": "Mesin 1", "active": True},
                               {"id": "M2", "code": "MS2", "name": "Mesin 2", "active": True}]
    db.rahaza_line_assignments.docs = [{"id": "a1", "line_id": "LN1"}]
    db.rahaza_machine_downtime.docs = [{"id": "d1", "machine_id": "M1"}]
    _409(mod.deactivate_line("LN1", fm.FakeRequest(), hard=True), "penugasan lini", "Line 1")
    _409(mod.deactivate_machine("M1", fm.FakeRequest(), hard=True), "catatan mesin berhenti", "Mesin 1")
    user["u"] = dict(GUDANG)
    assert _status(mod.deactivate_line("LN2", fm.FakeRequest(), hard=True)) == 403
    user["u"] = {"id": "u-p", "name": "Spv", "role": "supervisor_produksi"}
    run(mod.deactivate_line("LN2", fm.FakeRequest(), hard=True))
    run(mod.deactivate_machine("M2", fm.FakeRequest(), hard=True))
    assert [x["id"] for x in db.rahaza_lines.docs] == ["LN1"] and [x["id"] for x in db.rahaza_machines.docs] == ["M1"]
    run(mod.deactivate_line("LN1", fm.FakeRequest()))
    run(mod.deactivate_machine("M1", fm.FakeRequest()))
    assert db.rahaza_lines.docs[0]["active"] is False and db.rahaza_machines.docs[0]["active"] is False


def test_proses_nonaktifkan_tanpa_hapus_permanen(master):
    """Tombol Nonaktifkan layar Proses Produksi dulu memanggil DELETE yang tidak ada (405)."""
    mod, db, _u = master
    db.rahaza_processes.docs = [{"id": "P1", "code": "QC", "name": "QC Final", "active": True}]
    assert run(mod.deactivate_process("P1", fm.FakeRequest()))["status"] == "deactivated"
    assert db.rahaza_processes.docs[0]["active"] is False
    assert "hard" not in mod.deactivate_process.__code__.co_varnames


# ── Shift (satu master untuk /rahaza/shifts dan /hr/shifts) ──
def _shift(db):
    db.rahaza_shifts.docs = [{"id": "S1", "code": "PAGI", "name": "Shift Pagi", "shift_code": "PAGI",
                              "shift_name": "Shift Pagi", "active": True, "status": "active"}]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_employees", {"id": "e1", "shift_id": "S1"}, "karyawan (shift utama)"),
    ("hr_shift_assignments", {"id": 7, "shift_id": "S1"}, "penugasan shift"),
    ("rahaza_schedules", {"id": "j1", "shifts": [{"employee_id": "e1", "shift_id": "S1"}]}, "jadwal shift"),
    ("hr_shift_pola", {"id": "p1", "urutan": [None, "S1", None, None, None, None, None]}, "pola rotasi"),
    ("rahaza_attendance_events", {"id": "at1", "shift_id": "S1"}, "absensi"),
    ("hr_shift_requests", {"id": "r1", "shift_diminta": {"id": "S1"}}, "permintaan tukar/ganti shift"),
])
def test_shift_dipakai_ditolak_di_dua_layar(master, monkeypatch, koleksi, doc, label):
    mod, db, _u = master
    _shift(db)
    getattr(db, koleksi).docs.append(doc)
    _409(mod.deactivate_shift("S1", fm.FakeRequest(), hard=True), label, "Shift Pagi")
    import routes.hr_shifts as hs
    monkeypatch.setattr(hs, "get_db", lambda: db)
    monkeypatch.setattr(hs, "require_auth", _as(ADMIN))
    monkeypatch.setattr(hs, "log_activity", _noop)
    _409(hs.delete_shift(fm.FakeRequest(), "S1", hard=True), label)
    assert len(db.rahaza_shifts.docs) == 1


def test_shift_belum_dipakai_dihapus_dan_gerbang(master, monkeypatch):
    mod, db, user = master
    _shift(db)
    user["u"] = dict(GUDANG)
    assert _status(mod.deactivate_shift("S1", fm.FakeRequest(), hard=True)) == 403
    user["u"] = dict(HR)
    run(mod.deactivate_shift("S1", fm.FakeRequest(), hard=True))
    assert db.rahaza_shifts.docs == []
    # layar SDM (/hr/shifts): gerbang lama (admin/owner) dipertahankan untuk dua jalur
    import routes.hr_shifts as hs
    _shift(db)
    monkeypatch.setattr(hs, "get_db", lambda: db)
    monkeypatch.setattr(hs, "log_activity", _noop)
    monkeypatch.setattr(hs, "require_auth", _as(OPERATOR))
    assert _status(hs.delete_shift(fm.FakeRequest(), "S1", hard=True)) == 403
    monkeypatch.setattr(hs, "require_auth", _as(ADMIN))
    run(hs.delete_shift(fm.FakeRequest(), "S1"))
    assert db.rahaza_shifts.docs[0]["active"] is False            # tanpa hard = nonaktifkan
    out = run(hs.delete_shift(fm.FakeRequest(), "S1", hard=True))
    assert out["deleted"] is True and db.rahaza_shifts.docs == []


# ── Karyawan ──
def _karyawan(db):
    db.rahaza_employees.docs = [{"id": "e1", "employee_code": "E001", "name": "Budi", "active": True}]
    db.rahaza_payroll_profiles.docs = [{"id": "pp1", "employee_id": "e1", "active": True}]
    db.rahaza_leave_balances.docs = [{"id": "lb1", "employee_id": "e1", "leave_type_id": "lt1", "used": 0}]
    db.hr_shift_assignments.docs = [{"id": 3, "employee_id": "e1", "shift_id": "S1"}]


def test_karyawan_tanpa_riwayat_dihapus_beserta_konfigurasinya(master):
    mod, db, _u = master
    _karyawan(db)
    db.rahaza_payroll_profiles.docs.append({"id": "pp2", "employee_id": "lain"})
    out = run(mod.deactivate_employee("e1", fm.FakeRequest(), hard=True))
    assert out["deleted"] is True and db.rahaza_employees.docs == []
    assert [p["id"] for p in db.rahaza_payroll_profiles.docs] == ["pp2"]
    assert db.rahaza_leave_balances.docs == [] and db.hr_shift_assignments.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_attendance_events", {"id": "a1", "employee_id": "e1"}, "absensi"),
    ("rahaza_payslips", {"id": "s1", "employee_id": "e1"}, "slip gaji"),
    ("rahaza_employee_loans", {"id": "k1", "employee_id": "e1"}, "kasbon"),
    ("rahaza_expense_claims", {"id": "c1", "employee_id": "e1"}, "klaim biaya"),
    ("rahaza_leave_requests", {"id": "l1", "employee_id": "e1"}, "pengajuan cuti"),
    ("rahaza_overtime_requests", {"id": "o1", "employee_id": "e1"}, "lembur"),
    ("rahaza_leave_balances", {"id": "lb2", "employee_id": "e1", "used": 2}, "saldo cuti terpakai"),
    ("rahaza_schedules", {"id": "j1", "shifts": [{"employee_id": "e1", "shift_id": "S1"}]}, "jadwal shift"),
    ("rahaza_wip_events", {"id": "w1", "operator_id": "e1"}, "catatan produksi"),
    ("users", {"id": "u9", "employee_id": "e1"}, "akun login tertaut"),
    ("rahaza_employees", {"id": "e2", "name": "Cici", "manager_id": "e1"}, "karyawan bawahan"),
])
def test_karyawan_punya_riwayat_ditolak_409(master, koleksi, doc, label):
    mod, db, _u = master
    _karyawan(db)
    getattr(db, koleksi).docs.append(doc)
    _409(mod.deactivate_employee("e1", fm.FakeRequest(), hard=True), label, "Budi")
    assert any(e["id"] == "e1" for e in db.rahaza_employees.docs)
    assert len(db.rahaza_payroll_profiles.docs) == 1                 # konfigurasi tidak tersentuh


def test_karyawan_akun_tertaut_lewat_user_id_ditolak(master):
    mod, db, _u = master
    _karyawan(db)
    db.rahaza_employees.docs[0]["user_id"] = "u5"
    db.users.docs = [{"id": "u5", "email": "budi@x.id"}]
    _409(mod.deactivate_employee("e1", fm.FakeRequest(), hard=True), "akun login tertaut")


def test_karyawan_tanpa_hard_tetap_nonaktifkan_dan_gerbang(master):
    mod, db, user = master
    _karyawan(db)
    user["u"] = dict(GUDANG)
    assert _status(mod.deactivate_employee("e1", fm.FakeRequest(), hard=True)) == 403
    run(mod.deactivate_employee("e1", fm.FakeRequest()))
    assert db.rahaza_employees.docs[0]["active"] is False and len(db.rahaza_payroll_profiles.docs) == 1


# ══════════════════════════════ Struktur organisasi: unit & jabatan ══════════════════════════════
@pytest.fixture
def org(monkeypatch):
    import routes.dewi_org as mod
    db = fm.FakeDB()
    db.dewi_org_units.docs = [{"unit_id": "u1", "name": "Produksi", "is_active": True},
                              {"unit_id": "u2", "name": "Gudang", "is_active": True}]
    db.dewi_org_positions.docs = [{"position_id": "p1", "title": "Operator Jahit", "unit_id": "u2", "unit_name": "Gudang"}]
    monkeypatch.setattr(mod, "log_activity", _noop)
    return mod, db


@pytest.mark.parametrize("koleksi,doc,label", [
    ("dewi_org_units", {"unit_id": "u3", "name": "Cutting", "parent_id": "u1"}, "unit anak"),
    ("dewi_org_positions", {"position_id": "p9", "title": "Kepala", "unit_id": "u1"}, "jabatan"),
    ("rahaza_employees", {"id": "e1", "name": "Ani", "department": " produksi "}, "karyawan"),
])
def test_unit_dipakai_ditolak_409(org, koleksi, doc, label):
    mod, db = org
    getattr(db, koleksi).docs.append(doc)
    _409(mod.delete_unit("u1", db=db, user=dict(HR)), label, "Produksi")
    assert any(u["unit_id"] == "u1" for u in db.dewi_org_units.docs)


def test_unit_belum_dipakai_dihapus(org):
    mod, db = org
    db.rahaza_employees.docs = [{"id": "e1", "department": "Produksi Jahit"}]   # beda unit, nama mirip
    assert run(mod.delete_unit("u1", db=db, user=dict(HR)))["deleted"] is True
    assert [u["unit_id"] for u in db.dewi_org_units.docs] == ["u2"]


def test_jabatan_dipakai_karyawan_ditolak_dan_bebas_dihapus(org):
    mod, db = org
    db.rahaza_employees.docs = [{"id": "e1", "job_title": "operator jahit", "department": "Gudang"}]
    _409(mod.delete_position("p1", db=db, user=dict(HR)), "1 karyawan", "Operator Jahit")
    # jabatan bernama sama di unit lain tidak menghalangi
    db.rahaza_employees.docs = [{"id": "e1", "job_title": "Operator Jahit", "department": "Produksi"}]
    assert run(mod.delete_position("p1", db=db, user=dict(HR)))["deleted"] is True
    assert db.dewi_org_positions.docs == []


def test_jabatan_atasan_jabatan_lain_ditolak(org):
    mod, db = org
    db.dewi_org_positions.docs.append({"position_id": "p2", "title": "Staf", "reports_to_position_id": "p1"})
    _409(mod.delete_position("p1", db=db, user=dict(HR)), "jabatan bawahan")


# ══════════════════════════════ Pola rotasi ══════════════════════════════
def test_pola_rotasi(monkeypatch):
    import routes.dewi_shift_scheduler as mod
    db = fm.FakeDB()
    db.hr_shift_pola.docs = [{"id": "po1", "nama": "Pagi-Siang", "aktif": True, "urutan": ["S1"] * 7},
                             {"id": "po2", "nama": "Malam", "aktif": True, "urutan": ["S2"] * 7}]
    db.rahaza_schedules.docs = [{"id": "j1", "pola_id": "po1", "shifts": []}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "require_auth", _as(OPERATOR))
    assert _status(mod.hapus_pola(fm.FakeRequest(), "po2", hard=True)) == 403
    monkeypatch.setattr(mod, "require_auth", _as(HR))
    _409(mod.hapus_pola(fm.FakeRequest(), "po1", hard=True), "jadwal shift", "Pagi-Siang")
    assert run(mod.hapus_pola(fm.FakeRequest(), "po2", hard=True))["deleted"] is True
    run(mod.hapus_pola(fm.FakeRequest(), "po1"))
    assert [p["id"] for p in db.hr_shift_pola.docs] == ["po1"] and db.hr_shift_pola.docs[0]["aktif"] is False


# ══════════════════════════════ Penggajian: profil, tunjangan, golongan ══════════════════════════════
def test_profil_gaji(monkeypatch):
    import routes.rahaza_payroll_profiles as mod
    db = fm.FakeDB()
    db.rahaza_employees.docs = [{"id": "e1", "employee_code": "E1", "name": "Ani"}, {"id": "e2", "name": "Budi"}]
    db.rahaza_payroll_profiles.docs = [{"id": "p1", "employee_id": "e1", "active": True},
                                       {"id": "p2", "employee_id": "e2", "active": True}]
    db.rahaza_payslips.docs = [{"id": "s1", "employee_id": "e1", "run_id": "r1"}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "_require_hr", _as(HR))
    _409(mod.delete_profile("p1", fm.FakeRequest(), hard=True), "1 slip gaji", "Ani")
    assert run(mod.delete_profile("p2", fm.FakeRequest(), hard=True))["deleted"] is True
    run(mod.delete_profile("p1", fm.FakeRequest()))
    assert [p["id"] for p in db.rahaza_payroll_profiles.docs] == ["p1"] and db.rahaza_payroll_profiles.docs[0]["active"] is False


def test_tunjangan_sudah_di_slip_ditolak(monkeypatch):
    import routes.rahaza_payroll_allowances as mod
    db = fm.FakeDB()
    db.da_payroll_allowances.docs = [{"allowance_id": "a1", "name": "Tunjangan Jabatan", "is_active": True},
                                     {"allowance_id": "a2", "name": "Insentif Makan", "is_active": True}]
    db.rahaza_payslips.docs = [{"id": "s1", "allowances": [{"allowance_id": "a1", "amount": 1}]}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "_require_hr", _as(HR))
    _409(mod.delete_allowance("a1", fm.FakeRequest()), "1 slip gaji", "Tunjangan Jabatan")
    assert run(mod.delete_allowance("a2", fm.FakeRequest()))["deleted"] is True
    assert [a["allowance_id"] for a in db.da_payroll_allowances.docs] == ["a1"]


def test_golongan_gaji(monkeypatch):
    import routes.rahaza_salary_grades as mod
    db = fm.FakeDB()
    db.rahaza_salary_grades.docs = [{"id": "g1", "grade_code": "G1", "grade_name": "Operator Dasar", "is_active": True},
                                    {"id": "g2", "grade_code": "G2", "grade_name": "Senior", "is_active": True},
                                    {"id": "g3", "grade_code": "G3", "grade_name": "Supervisor", "is_active": True}]
    db.rahaza_employees.docs = [{"id": "e1", "salary_grade_id": "g1"}]
    db.dewi_org_positions.docs = [{"position_id": "p1", "title": "Spv", "salary_grade": "G2"}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "_require_admin", _as(HR))
    _409(mod.delete_grade("g1", fm.FakeRequest(), hard=True), "1 karyawan", "Operator Dasar")
    _409(mod.delete_grade("g2", fm.FakeRequest(), hard=True), "1 jabatan")
    assert run(mod.delete_grade("g3", fm.FakeRequest(), hard=True))["deleted"] is True
    run(mod.delete_grade("g1", fm.FakeRequest()))
    assert [g["id"] for g in db.rahaza_salary_grades.docs] == ["g1", "g2"] and db.rahaza_salary_grades.docs[0]["is_active"] is False


# ══════════════════════════════ Jenis cuti ══════════════════════════════
def test_jenis_cuti(monkeypatch):
    mod = _import("routes.rahaza_leave")
    db = fm.FakeDB()
    db.rahaza_leave_types.docs = [{"id": "lt1", "code": "CT", "name": "Cuti Tahunan", "active": True},
                                  {"id": "lt2", "code": "CK", "name": "Cuti Khusus", "active": True},
                                  {"id": "lt3", "code": "CX", "name": "Cuti Baru", "active": True}]
    db.rahaza_leave_requests.docs = [{"id": "r1", "leave_type_id": "lt1", "status": "approved"}]
    db.rahaza_leave_balances.docs = [{"id": "b1", "leave_type_id": "lt2", "employee_id": "e1", "used": 1.5},
                                     {"id": "b2", "leave_type_id": "lt3", "employee_id": "e1", "used": 0}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "_require_hr_admin", _as(HR))
    _409(mod.deactivate_leave_type("lt1", fm.FakeRequest(), hard=True), "1 pengajuan cuti", "Cuti Tahunan")
    _409(mod.deactivate_leave_type("lt2", fm.FakeRequest(), hard=True), "saldo cuti terpakai")
    assert run(mod.deactivate_leave_type("lt3", fm.FakeRequest(), hard=True))["deleted"] is True
    assert [b["id"] for b in db.rahaza_leave_balances.docs] == ["b1"]      # saldo kosong ikut terhapus
    run(mod.deactivate_leave_type("lt1", fm.FakeRequest()))                 # tanpa hard: nonaktifkan
    assert db.rahaza_leave_types.docs[0]["active"] is False


# ══════════════════════════════ Klaim dinas: tarif harian & kategori ══════════════════════════════
def test_tarif_uang_harian(monkeypatch):
    import routes.employee_per_diem as mod
    db = fm.FakeDB()
    db.employee_per_diem_rates.docs = [{"id": "r1", "destination_type": "luar_kota", "daily_rate": 300000, "is_active": True},
                                       {"id": "r2", "destination_type": "dalam_kota", "daily_rate": 100000, "is_active": True}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    assert _status(mod.delete_per_diem_rate("r1", hard=True, user=dict(OPERATOR))) == 403
    run(mod.delete_per_diem_rate("r2", user=dict(ADMIN)))
    assert db.employee_per_diem_rates.docs[1]["is_active"] is False
    assert run(mod.delete_per_diem_rate("r1", hard=True, user=dict(ADMIN)))["hard"] is True
    assert [r["id"] for r in db.employee_per_diem_rates.docs] == ["r2"]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_expense_claims", {"id": "c1", "items": [{"category": "Bensin", "amount": 1}]}, "klaim biaya"),
    ("employee_travel_settlements", {"id": "t1", "actual_items": [{"category": "Bensin"}]}, "penyelesaian perjalanan dinas"),
    ("employee_expense_gl_mappings", {"id": "g1", "category": "Bensin"}, "pemetaan akun"),
])
def test_kategori_klaim_dipakai_ditolak(monkeypatch, koleksi, doc, label):
    import routes.employee_expense_category_master as mod
    db = fm.FakeDB()
    db.employee_expense_categories.docs = [{"id": "k1", "name": "Bensin", "is_active": True}]
    getattr(db, koleksi).docs.append(doc)
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    _409(mod.delete_master_category("k1", hard=True, user=dict(ADMIN)), label, "Bensin")
    assert len(db.employee_expense_categories.docs) == 1


def test_kategori_klaim_bebas_dihapus_tanpa_hard_nonaktif(monkeypatch):
    import routes.employee_expense_category_master as mod
    db = fm.FakeDB()
    db.employee_expense_categories.docs = [{"id": "k1", "name": "Bensin", "is_active": True},
                                           {"id": "k2", "name": "Parkir", "is_active": True}]
    db.rahaza_expense_claims.docs = [{"id": "c1", "items": [{"category": "Parkir"}]}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    assert run(mod.delete_master_category("k1", hard=True, user=dict(ADMIN)))["deleted"] is True
    run(mod.delete_master_category("k2", user=dict(ADMIN)))
    assert [c["id"] for c in db.employee_expense_categories.docs] == ["k2"]
    assert db.employee_expense_categories.docs[0]["is_active"] is False


# ══════════════════════════════ Keuangan: pusat biaya & rekening kas/bank ══════════════════════════════
@pytest.fixture
def fin(monkeypatch):
    import routes.rahaza_finance as mod
    db = fm.FakeDB()
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "_require_fin", _as(ADMIN))
    return mod, db


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_journal_lines", {"id": "jl1", "cost_center_id": "cc1"}, "baris jurnal"),
    ("rahaza_expenses", {"id": "x1", "cost_center_id": "cc1"}, "pengeluaran"),
    ("rahaza_ap_invoices", {"id": "ap1", "cost_center_id": "cc1"}, "faktur pemasok"),
    ("rahaza_budget_items", {"id": "bi1", "cost_center_id": "cc1"}, "baris anggaran"),
])
def test_pusat_biaya_dipakai_ditolak(fin, koleksi, doc, label):
    mod, db = fin
    db.rahaza_cost_centers.docs = [{"id": "cc1", "code": "PRD", "name": "Produksi", "active": True}]
    getattr(db, koleksi).docs.append(doc)
    _409(mod.delete_cost_center("cc1", fm.FakeRequest(), hard=True), label, "Produksi")


def test_pusat_biaya_bebas_dihapus_tanpa_hard_nonaktif(fin):
    mod, db = fin
    db.rahaza_cost_centers.docs = [{"id": "cc1", "code": "PRD", "name": "Produksi", "active": True},
                                   {"id": "cc2", "code": "GDG", "name": "Gudang", "active": True}]
    assert run(mod.delete_cost_center("cc1", fm.FakeRequest(), hard=True))["deleted"] is True
    run(mod.delete_cost_center("cc2", fm.FakeRequest()))
    assert [c["id"] for c in db.rahaza_cost_centers.docs] == ["cc2"] and db.rahaza_cost_centers.docs[0]["active"] is False


def _rekening(db, **kw):
    db.rahaza_cash_accounts.docs = [{"id": "ca1", "code": "BCA2", "name": "BCA Operasional", "gl_account_code": "1-1201-BCA2",
                                     "opening_balance": 0, "active": True, **kw}]
    db.rahaza_coa_accounts.docs = [
        {"id": "a1", "code": "1-1201-BCA2", "flags": {"subledger_entity_type": "bank", "subledger_entity_id": "ca1"}},
        {"id": "a2", "code": "1-1100", "flags": {}},
    ]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_cash_movements", {"id": "m1", "account_id": "ca1"}, "mutasi kas"),
    ("rahaza_journal_lines", {"id": "jl1", "account_code": "1-1201-BCA2"}, "baris jurnal"),
    ("rahaza_bank_transfers", {"id": "t1", "to_account_code": "1-1201-BCA2"}, "transfer bank"),
    ("bank_recon_sessions", {"id": "bs1", "cash_account_id": "ca1"}, "sesi rekonsiliasi bank"),
])
def test_rekening_dipakai_ditolak(fin, koleksi, doc, label):
    mod, db = fin
    _rekening(db)
    getattr(db, koleksi).docs.append(doc)
    _409(mod.delete_cash_account("ca1", fm.FakeRequest(), hard=True), label, "BCA Operasional")
    assert len(db.rahaza_cash_accounts.docs) == 1 and len(db.rahaza_coa_accounts.docs) == 2


def test_rekening_bersaldo_awal_ditolak(fin):
    mod, db = fin
    _rekening(db, opening_balance=1_500_000)
    _409(mod.delete_cash_account("ca1", fm.FakeRequest(), hard=True), "saldo awal")


def test_rekening_bebas_dihapus_beserta_akun_otomatis_tanpa_hard_nonaktif(fin):
    mod, db = fin
    _rekening(db)
    assert run(mod.delete_cash_account("ca1", fm.FakeRequest(), hard=True))["deleted"] is True
    assert db.rahaza_cash_accounts.docs == [] and [a["code"] for a in db.rahaza_coa_accounts.docs] == ["1-1100"]
    _rekening(db)
    run(mod.delete_cash_account("ca1", fm.FakeRequest()))
    assert db.rahaza_cash_accounts.docs[0]["active"] is False and len(db.rahaza_coa_accounts.docs) == 2


# ══════════════════════════════ gerbang peran rute ══════════════════════════════
def _deps(router, method, path):
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return [getattr(getattr(d, "dependency", None) or getattr(d, "call", None), "__name__", "") for d in r.dependencies]
    raise AssertionError(f"rute {method} {path} tidak ada")


@pytest.mark.parametrize("modname,path,perm", [
    ("routes.dewi_org", "/api/dewi/org/units/{unit_id}", "hr.manage"),
    ("routes.dewi_org", "/api/dewi/org/positions/{position_id}", "hr.manage"),
    ("routes.rahaza_payroll_allowances", "/api/rahaza/payroll-allowances/{allowance_id}", "payroll.manage"),
])
def test_endpoint_hapus_dijaga_peran(modname, path, perm):
    mod = importlib.import_module(modname)
    assert any(n.startswith("require_roles[") and perm in n for n in _deps(mod.router, "DELETE", path))


def test_jalur_hard_di_endpoint_semua_staf_dijaga_di_badan_fungsi():
    import inspect
    import routes.rahaza_master as mod
    for fn, kunci in ((mod.deactivate_location, "lokasi"), (mod.deactivate_line, "produksi"),
                      (mod.deactivate_machine, "produksi"), (mod.deactivate_shift, "shift"),
                      (mod.deactivate_employee, "karyawan")):
        src = inspect.getsource(fn)
        assert "if hard:" in src and "_wajib_pengelola(user, " in src and f'"{kunci}"' in src, fn.__name__
    assert '"lokasi_kerja" if' in inspect.getsource(mod.deactivate_location)


# ══════════════════════════════ layar ══════════════════════════════
@pytest.mark.parametrize("rel,frags", [
    ("components/erp/HREmployeeModule.jsx", ("hapusMaster", "employees/${emp.id}?hard=true", "employee-delete-", "label: 'Aksi'")),
    ("components/erp/HROrgChartModule.jsx", ("hapusMaster", "org-unit-delete-", "org-pos-edit-", "org-pos-delete-",
                                             "/positions/${editPos.position_id}", "is_active: false")),
    ("components/erp/HRShiftManagementModule.jsx", ("hapusMaster", "shifts/${s.id}?hard=true", "shift-delete-")),
    ("components/erp/hr/ShiftPolaModule.jsx", ("hapusMaster", "?hard=true", "pola-delete-")),
    ("components/erp/RahazaPayrollProfilesModule.jsx", ("hapusMaster", "payroll-profiles/${p.id}?hard=true", "pp-del-", "pp-off-")),
    ("components/erp/RahazaPayrollAllowancesModule.jsx", ("hapusMaster", "?hard=true", "is_active: false")),
    ("components/erp/RahazaLeaveModule.jsx", ("hapusMaster", "leave-types/${lt.id}?hard=true", "leave-type-delete-")),
    ("components/erp/HRAdminModule.jsx", ("hapusMaster", "salary-grades/${g.id}?hard=true", "grade-delete-")),
    ("components/erp/EmployeePerDiemAdminModule.jsx", ("hapusMaster", "per-diem-rates/${r.id}?hard=true", "per-diem-delete-")),
    ("components/erp/EmployeeExpenseCategoryMasterModule.jsx", ("hapusMaster", "master-categories/${cat.id}?hard=true",
                                                                "category-delete-")),
    ("components/erp/RahazaCostCentersModule.jsx", ("hapusMaster", "cost-centers/${r.id}?hard=true", "cc-delete-", "cc-deactivate-")),
    ("components/erp/RahazaCashAccountsModule.jsx", ("hapusMaster", "cash-accounts/${a.id}?hard=true", "ca-delete-", ">Aksi<")),
])
def test_layar_punya_ubah_dan_hapus_aman(rel, frags):
    src = fe(rel)
    for f in frags:
        assert f in src, (rel, f)
    assert "window.confirm(" not in src


def test_layar_kategori_tidak_lagi_memakai_alertdialog_sendiri():
    src = fe("components/erp/EmployeeExpenseCategoryMasterModule.jsx")
    assert "AlertDialog" not in src and "deleteTarget" not in src


def test_layar_master_produksi_dan_lokasi_menyalakan_hapus_permanen():
    for rel, jenis in (("RahazaLocationsModule.jsx", "lokasi"), ("RahazaEmployeesModule.jsx", "karyawan"),
                       ("RahazaLinesModule.jsx", "lini produksi"), ("RahazaMachinesModule.jsx", "mesin"),
                       ("RahazaShiftsModule.jsx", "shift")):
        src = fe(f"components/erp/{rel}")
        assert "hapusPermanen" in src and f'jenis="{jenis}"' in src, rel
    # proses = daftar tetap: hanya nonaktif, tanpa hapus permanen
    assert "hapusPermanen" not in fe("components/erp/RahazaProcessesModule.jsx")


def test_layar_lokasi_gudang_tanpa_kantor():
    src = fe("components/erp/RahazaLocationsModule.jsx")
    assert "saringBaris={bukanKantor}" in src and "r.type !== 'kantor'" in src
    assert "SDM › Lokasi kerja" in src
    assert "{ value: 'gedung', label: 'Gedung' }, { value: 'zona', label: 'Zona' }" in src   # pilihan jenis tetap



# ══ 10 Nov 2026 (keputusan owner): foto & dokumen karyawan bukan riwayat — ikut terhapus ══
def test_karyawan_hanya_punya_dokumen_tetap_terhapus(master):
    mod, db = master[0], master[1]
    _karyawan(db)
    db.attachments.docs.append({"id": "f1", "entity_type": "employee", "entity_id": "e1"})
    out = run(mod.deactivate_employee("e1", fm.FakeRequest(), hard=True))
    assert out["deleted"] is True and not any(e["id"] == "e1" for e in db.rahaza_employees.docs)
    assert db.attachments.docs[0]["is_deleted"] is True
