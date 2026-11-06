"""Uji HERMETIK Tahap 6 — agen `sdm-organisasi` (keputusan owner 7 Nov 2026). FakeDB in-memory.

  OR1 · satu daftar departemen (Struktur Organisasi):
        - kunci banding departemen yang sama untuk penyimpanan PR dan pencocokan penyetuju tahap departemen;
        - departemen penyetuju = departemen KARYAWAN yang ditautkan (bukan `users.department` yang kosong);
        - PR baru: departemen bawaan = departemen karyawan pemohon, disimpan dengan ejaan unit;
        - migrasi `2026_11_07_struktur_dari_karyawan`: idempoten, unit/jabatan yang ada dilewati, ejaan pasti
          diseragamkan, yang mirip hanya dilaporkan;
        - formulir (OKR, PR, aset, anggaran, pindah aset) memakai SATU pemilih bersama (`DepartmentSelect`).
  OR2 · karyawan baru tanpa jabatan → jabatan kosong (bukan "Operator").
  HR1 · Portal Saya › Profil: No. HP/alamat/kontak darurat → pengajuan → Kotak Masuk SDM (lama → baru);
        setujui = data karyawan (+ akun) berubah, tolak = tidak berubah; klaim atomik; status tampil di Profil.
  HR2 · Profil Gaji: tipe periode / hari mulai / tanggal mulai disembunyikan; nilai tersimpan tidak berubah.
"""
import asyncio
import importlib.util
import os
import re
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

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402


def run(coro):
    return asyncio.run(coro)


async def _noop(*a, **k):
    return None


def _frontend(rel):
    p = os.path.join(REPO, "frontend", "src", "components", "erp", rel)
    if not os.path.exists(p):
        pytest.skip("frontend/src tidak tersedia di lingkungan uji ini")
    return open(p, encoding="utf-8").read()


# ═════════════════════════════════════════════════════════════════════════════
# OR1 · kunci departemen & persetujuan tahap departemen PR
# ═════════════════════════════════════════════════════════════════════════════
class TestKunciDepartemen:
    def test_huruf_spasi_tanda_baca_diabaikan(self):
        from core.departments import department_key, same_department
        assert department_key("  Produksi ") == department_key("PRODUKSI") == "produksi"
        assert same_department("Finance/Accounting", "finance accounting")
        assert not same_department("Produksi", "Gudang")
        assert not same_department("", "")

    def test_ejaan_resmi_dari_unit(self):
        from core.departments import canonical_department
        db = FakeDB()
        db.dewi_org_units.docs = [{"unit_id": "u1", "name": "Produksi", "is_active": True, "level": 1}]
        assert run(canonical_department(db, " produksi ")) == "Produksi"
        assert run(canonical_department(db, "Divisi Baru")) == "Divisi Baru"   # data lama tidak hilang
        assert run(canonical_department(db, "")) == ""


def _db_pr():
    db = FakeDB()
    db.dewi_org_units.docs = [{"unit_id": "u1", "name": "Produksi", "is_active": True, "level": 1},
                              {"unit_id": "u2", "name": "Gudang", "is_active": True, "level": 1}]
    db.rahaza_employees.docs = [
        {"id": "e-req", "user_id": "req", "department": "Produksi", "active": True},
        {"id": "e-a", "user_id": "mgr-a", "department": "produksi ", "active": True},
        {"id": "e-b", "user_id": "mgr-b", "department": "Gudang", "active": True},
    ]
    db.users.docs = [
        {"id": "req", "role": "admin_gudang", "status": "active", "employee_id": "e-req", "department": ""},
        {"id": "mgr-a", "role": "manager_produksi", "status": "active", "employee_id": "e-a", "department": ""},
        # akun lama menyimpan departemen basi; data karyawan yang berlaku
        {"id": "mgr-b", "role": "manager_produksi", "status": "active", "department": "Produksi"},
    ]
    return db


class TestPersetujuanDepartemenPR:
    def test_departemen_penyetuju_dari_data_karyawan(self):
        from core.pr_approval import with_department
        db = _db_pr()
        assert run(with_department(db, {"id": "mgr-a", "employee_id": "e-a"}))["department"] == "produksi "
        # users.department = "Produksi" tetapi karyawannya di Gudang → Gudang
        assert run(with_department(db, {"id": "mgr-b", "department": "Produksi"}))["department"] == "Gudang"

    def test_kunci_sama_untuk_simpan_dan_cocok(self):
        from core.pr_approval import STAGE_DEPT, eval_approval
        doc = {"id": "pr1", "requested_by": "req", "status": "submitted", "department": "Produksi",
               "approval_steps": []}
        ok = eval_approval(doc, {"id": "mgr-a", "role": "manager_produksi", "department": "produksi "}, [STAGE_DEPT])
        assert ok["can_approve"] and "department" not in ok["override_reasons"]
        bad = eval_approval(doc, {"id": "mgr-b", "role": "manager_produksi", "department": "Gudang"}, [STAGE_DEPT])
        assert not bad["can_approve"] and "departemen Produksi" in bad["blocked_reason"]

    def test_penerima_notifikasi_tahap_departemen(self, monkeypatch):
        from core import pr_approval as pa

        async def perms(role, uid):
            return [], []
        monkeypatch.setattr(pa, "_load_perms", perms)
        db = _db_pr()
        doc = {"id": "pr1", "requested_by": "req", "status": "submitted", "department": "Produksi",
               "approval_steps": []}
        ids, override = run(pa.stage_approver_ids(db, doc, pa.STAGE_DEPT, [pa.STAGE_DEPT]))
        assert ids == ["mgr-a"] and override is False   # mgr-b (Gudang) tidak, pemohon tidak

    def test_pr_baru_departemen_bawaan_dan_ejaan_unit(self, monkeypatch):
        import routes.dewi_procurement as dp

        async def items(db, raw, **_kw):  # menerima reject_fg (PG1)
            return [{"name": "Benang", "qty": 1, "total_price": 1000.0}]

        async def number(db, requested=""):
            return "PR-UJI-1"
        monkeypatch.setattr(dp, "_norm_pr_items", items)
        monkeypatch.setattr(dp, "_gen_pr_number", number)
        db = _db_pr()
        req = {"id": "req", "name": "Pemohon", "employee_id": "e-req"}
        doc = run(dp.build_pr_doc(db, req, {"title": "Uji", "items": [{}]}))
        assert doc["department"] == "Produksi"          # bawaan = departemen karyawan pemohon
        doc2 = run(dp.build_pr_doc(db, req, {"title": "Uji", "items": [{}], "department": " gudang"}))
        assert doc2["department"] == "Gudang"            # disimpan dengan ejaan unit Struktur Organisasi
        # nilai tersimpan dan departemen penyetuju cocok lewat kunci yang sama
        from core.pr_approval import STAGE_DEPT, eval_approval, with_department
        appr = run(with_department(db, {"id": "mgr-a", "employee_id": "e-a", "role": "manager_produksi"}))
        assert eval_approval({**doc, "status": "submitted", "approval_steps": []}, appr, [STAGE_DEPT])["can_approve"]


# ═════════════════════════════════════════════════════════════════════════════
# OR1 · migrasi Struktur Organisasi dari data karyawan
# ═════════════════════════════════════════════════════════════════════════════
def _migrasi():
    p = os.path.join(BACKEND, "scripts", "migrations", "2026_11_07_struktur_dari_karyawan.py")
    spec = importlib.util.spec_from_file_location("mig_struktur_dari_karyawan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db_struktur():
    db = FakeDB()
    db.dewi_org_units.docs = [
        {"unit_id": "u0", "name": "PT Contoh", "type": "company", "parent_id": None, "level": 0, "is_active": True},
        {"unit_id": "u1", "name": "Gudang", "type": "department", "parent_id": "u0", "level": 1, "is_active": True},
    ]
    db.dewi_org_positions.docs = [{"position_id": "p1", "title": "Staf Gudang", "unit_id": "u1", "is_active": True}]
    e = lambda i, d, j, active=True: {"id": i, "department": d, "job_title": j, "active": active}  # noqa: E731
    db.rahaza_employees.docs = [
        e("e1", "Produksi", "Operator Jahit"), e("e2", "produksi ", "operator jahit"), e("e3", "PRODUKSI", "Supervisor"),
        e("e4", "gudang", "Staf Gudang"), e("e5", "Produkis", "Operator"), e("e6", "", "Admin"),
        e("e7", "Lama", "Operator", active=False), e("e8", "Marketing", "Lainnya"),
    ]
    return db


class TestMigrasiStruktur:
    def test_pratinjau_tidak_menulis(self):
        mig, db = _migrasi(), _db_struktur()
        res = run(mig.run_all(db, apply=False, out=lambda *_: None))
        assert res["units"] == 3            # Produksi, Produkis, Marketing (Gudang sudah ada)
        assert res["positions"] == 4        # Operator Jahit, Supervisor, Operator, Admin (umum)
        assert res["dept_renamed"] == 3 and res["title_renamed"] == 1
        assert res["skipped_positions"] == 1 and res["placeholders"] == 1 and res["inactive_only"] == 1
        assert res["similar"] >= 1          # Produksi ~ Produkis dilaporkan, tidak digabung
        assert len(db.dewi_org_units.docs) == 2 and db.rahaza_employees.docs[1]["department"] == "produksi "

    def test_tulis_lalu_idempoten(self):
        mig, db = _migrasi(), _db_struktur()
        res = run(mig.run_all(db, apply=True, out=lambda *_: None))
        assert (res["units"], res["positions"], res["dept_renamed"], res["title_renamed"]) == (3, 4, 3, 1)
        units = {u["name"]: u for u in db.dewi_org_units.docs}
        assert {"Produksi", "Produkis", "Marketing"} <= set(units)
        assert units["Produksi"]["parent_id"] == "u0" and units["Produksi"]["level"] == 1
        assert units["Produksi"]["type"] == "department" and units["Produksi"]["is_active"] is True
        emps = {x["id"]: x for x in db.rahaza_employees.docs}
        assert emps["e2"]["department"] == emps["e3"]["department"] == "Produksi"
        assert emps["e4"]["department"] == "Gudang"            # ejaan unit yang sudah ada
        assert emps["e5"]["department"] == "Produkis"          # mirip ≠ pasti: tidak diubah
        assert emps["e7"]["department"] == "Lama"              # nonaktif tanpa unit: tidak disentuh
        assert emps["e2"]["job_title"] == "Operator Jahit"
        pos = {(p["title"], p.get("unit_id")) for p in db.dewi_org_positions.docs}
        assert ("Operator Jahit", units["Produksi"]["unit_id"]) in pos and ("Admin", "") in pos
        assert not any(p["title"] == "Lainnya" for p in db.dewi_org_positions.docs)
        again = run(mig.run_all(db, apply=True, out=lambda *_: None))
        assert (again["units"], again["positions"], again["dept_renamed"], again["title_renamed"]) == (0, 0, 0, 0)
        assert len(db.dewi_org_units.docs) == 5

    def test_unit_yang_ada_dicocokkan_tanpa_peka_huruf(self):
        mig, db = _migrasi(), _db_struktur()
        db.dewi_org_units.docs.append({"unit_id": "u9", "name": "  produksi", "type": "department", "is_active": True})
        res = run(mig.run_all(db, apply=False, out=lambda *_: None))
        assert res["units"] == 2 and res["existing_units"] == 2


class TestFormMemakaiPemilihBersama:
    FILES = ["OKRTrackerModule.jsx", "ProcurementRequestModule.jsx", "BudgetModule.jsx",
             "asset/dialogs/CreateAssetDialog.jsx", "asset/dialogs/CreatePRDialog.jsx",
             "asset/dialogs/TransferAssetDialog.jsx", "hr/JobBoardModule.jsx", "hr/HRAttritionModule.jsx"]

    @pytest.mark.parametrize("rel", FILES)
    def test_departemen_dari_struktur(self, rel):
        src = _frontend(rel)
        assert "DepartmentSelect" in src and "hrPickers" in src
        # tidak ada lagi isian departemen teks bebas
        assert not re.search(r"<(?:Input|input|GlassInput)\b[^>]*value=\{[^}]*\b(?:to_)?department\}", src)

    def test_satu_pemilih_di_hrpickers(self):
        src = _frontend("hr/hrPickers.jsx")
        assert "export function DepartmentSelect" in src and "/api/dewi/org/units" in src
        assert src.count("export function DepartmentSelect") == 1

    def test_pr_bawaan_departemen_pemohon(self):
        assert "defaultToMine" in _frontend("ProcurementRequestModule.jsx")


# ═════════════════════════════════════════════════════════════════════════════
# OR2 · tanpa jabatan bawaan
# ═════════════════════════════════════════════════════════════════════════════
class TestTanpaJabatanBawaan:
    def _create(self, monkeypatch, body):
        import routes.rahaza_master as rm
        db = FakeDB()

        async def admin(request):
            return {"id": "hr", "name": "HR", "role": "hr"}
        monkeypatch.setattr(rm, "_require_admin", admin)
        monkeypatch.setattr(rm, "get_db", lambda: db)
        monkeypatch.setattr(rm, "log_activity", _noop)
        run(rm.create_employee(FakeRequest(body)))
        return db.rahaza_employees.docs[0]

    def test_kosong_bukan_operator(self, monkeypatch):
        doc = self._create(monkeypatch, {"employee_code": "uji-1", "name": "Karyawan Uji"})
        assert doc["job_title"] == ""

    def test_jabatan_diisi_tetap(self, monkeypatch):
        doc = self._create(monkeypatch, {"employee_code": "uji-2", "name": "Karyawan Uji", "job_title": " Penjahit "})
        assert doc["job_title"] == "Penjahit"


# ═════════════════════════════════════════════════════════════════════════════
# HR1 · perubahan data profil lewat persetujuan HR
# ═════════════════════════════════════════════════════════════════════════════
HR = {"id": "hr1", "name": "HR Uji", "role": "hr"}
STAF = {"id": "u-staf", "name": "Staf Uji", "role": "tim_packing", "employee_id": "e-staf"}


def _db_profil():
    db = FakeDB()
    db.users.docs = [{**STAF, "email": "staf@example.test", "no_hp": "", "kontak_darurat": None},
                     {**HR, "email": "hr@example.test"}]
    db.rahaza_employees.docs = [{"id": "e-staf", "user_id": "u-staf", "name": "Staf Uji", "employee_code": "UJI-1",
                                 "department": "Produksi", "active": True, "phone": "081111111111",
                                 "current_address": "Jl. Lama 1", "emergency_contact_name": "Ibu Uji",
                                 "emergency_relation": "Orang Tua", "emergency_phone": "082222222222"}]
    return db


@pytest.fixture
def profil(monkeypatch):
    import core.employee_data_change as edc
    import routes.dewi_portal_saya_hr as ps
    import routes.hr_approval_inbox as ib
    db = _db_profil()
    state = {"user": STAF}

    async def auth(request):
        return state["user"]
    monkeypatch.setattr(ps, "require_auth", auth)
    monkeypatch.setattr(ps, "get_db", lambda: db)
    monkeypatch.setattr(ib, "get_db", lambda: db)
    monkeypatch.setattr(ib, "log_activity", _noop)
    monkeypatch.setattr(ib, "_require_approver_role", lambda u: None)
    monkeypatch.setattr(edc, "_notify", _noop)
    monkeypatch.setattr(edc, "_notify_hr", _noop)
    return db, ps, ib, state


BARU = {"nama_panggilan": "Uji", "no_hp": "0813 3333 3333", "alamat": "Jl. Baru 2",
        "kontak_darurat": {"nama": "Ibu Uji", "hubungan": "Orang Tua", "no_hp": "082222222222"}}


class TestPerubahanDataProfil:
    def test_simpan_jadi_pengajuan_data_karyawan_belum_berubah(self, profil):
        db, ps, ib, _ = profil
        out = run(ps.update_profile(FakeRequest(BARU)))
        assert out["data_change"]["status"] == "pending"
        emp = db.rahaza_employees.docs[0]
        assert emp["phone"] == "081111111111" and emp["current_address"] == "Jl. Lama 1"
        assert db.users.docs[0]["nama_panggilan"] == "Uji"              # nama panggilan langsung ke akun
        chg = db.rahaza_employee_data_changes.docs[0]
        assert [c["field"] for c in chg["changes"]] == ["phone", "current_address"]   # hanya yang berbeda
        assert chg["changes"][0]["old"] == "081111111111" and chg["changes"][0]["new"] == "0813 3333 3333"
        # Profil menampilkan data karyawan + status menunggu
        prof = run(ps.get_profile(FakeRequest()))
        assert prof["no_hp"] == "081111111111" and prof["data_change"]["status"] == "pending"
        # pengajuan kedua selagi menunggu → 409
        with pytest.raises(HTTPException) as e:
            run(ps.update_profile(FakeRequest({**BARU, "alamat": "Jl. Lain 3"})))
        assert e.value.status_code == 409

    def test_tanpa_perubahan_tidak_ada_pengajuan(self, profil):
        db, ps, _, _ = profil
        out = run(ps.update_profile(FakeRequest({"no_hp": "081111111111", "nama_panggilan": "X"})))
        assert out["data_change"] is None and not db.rahaza_employee_data_changes.docs

    def test_kotak_masuk_lama_ke_baru_lalu_setujui(self, profil):
        db, ps, ib, _ = profil
        run(ps.update_profile(FakeRequest(BARU)))
        box = run(ib.list_inbox(type_filter="employee_data_change", limit_per_type=50, user=HR))
        assert box["counts"]["employee_data_change"] == 1
        item = box["items"][0]
        assert item["type"] == "employee_data_change" and item["requester_dept"] == "Produksi"
        assert {(c["field"], c["old"], c["new"]) for c in item["meta"]["changes"]} == {
            ("phone", "081111111111", "0813 3333 3333"), ("current_address", "Jl. Lama 1", "Jl. Baru 2")}
        assert run(ib.inbox_summary(user=HR))["employee_data_change"] == 1
        res = run(ib.approve_request("employee_data_change", item["id"], ib.ActionPayload(note=""), user=HR))
        assert res["new_status"] == "approved"
        emp = db.rahaza_employees.docs[0]
        assert emp["phone"] == "0813 3333 3333" and emp["current_address"] == "Jl. Baru 2"
        acc = db.users.docs[0]
        assert acc["no_hp"] == "0813 3333 3333" and acc["alamat"] == "Jl. Baru 2"     # akun ikut selaras
        chg = db.rahaza_employee_data_changes.docs[0]
        assert chg["status"] == "approved" and chg["decided_by"] == "hr1"
        # klik ganda → 409, data tidak ditulis ulang
        with pytest.raises(HTTPException) as e:
            run(ib.approve_request("employee_data_change", item["id"], ib.ActionPayload(note=""), user=HR))
        assert e.value.status_code == 409
        prof = run(ps.get_profile(FakeRequest()))
        assert prof["no_hp"] == "0813 3333 3333" and prof["data_change"]["status"] == "approved"

    def test_tolak_tidak_mengubah_apa_pun(self, profil):
        db, ps, ib, _ = profil
        run(ps.update_profile(FakeRequest(BARU)))
        rid = db.rahaza_employee_data_changes.docs[0]["id"]
        with pytest.raises(HTTPException):
            run(ib.reject_request("employee_data_change", rid, ib.ActionPayload(), user=HR))
        res = run(ib.reject_request("employee_data_change", rid, ib.ActionPayload(reason="Nomor salah"), user=HR))
        assert res["new_status"] == "rejected"
        assert db.rahaza_employees.docs[0]["phone"] == "081111111111"
        assert db.users.docs[0].get("no_hp") == ""
        prof = run(ps.get_profile(FakeRequest()))
        assert prof["data_change"]["status"] == "rejected" and prof["data_change"]["decision_note"] == "Nomor salah"

    def test_klaim_atomik_keputusan_bersamaan(self, profil):
        """Dua HR memutus bersamaan: yang kalah mendapat 409 dan data karyawan tidak ditulis."""
        db, ps, ib, _ = profil
        import core.employee_data_change as edc
        run(ps.update_profile(FakeRequest(BARU)))
        rid = db.rahaza_employee_data_changes.docs[0]["id"]
        real_find_one = db.rahaza_employee_data_changes.find_one

        async def stale_find_one(q=None, projection=None, **kw):
            doc = await real_find_one(q, projection, **kw)
            # HR lain menolak tepat sesudah dokumen dibaca
            db.rahaza_employee_data_changes.docs[0]["status"] = "rejected"
            return doc
        db.rahaza_employee_data_changes.find_one = stale_find_one
        with pytest.raises(HTTPException) as e:
            run(edc.decide(db, rid, HR, approve=True))
        assert e.value.status_code == 409
        assert db.rahaza_employees.docs[0]["phone"] == "081111111111"

    def test_gagal_tulis_status_kembali_menunggu(self, profil, monkeypatch):
        db, ps, ib, _ = profil
        import core.employee_data_change as edc
        run(ps.update_profile(FakeRequest(BARU)))
        rid = db.rahaza_employee_data_changes.docs[0]["id"]

        async def boom(*a, **k):
            raise RuntimeError("db mati")
        monkeypatch.setattr(db.rahaza_employees, "update_one", boom)
        with pytest.raises(RuntimeError):
            run(edc.decide(db, rid, HR, approve=True))
        assert db.rahaza_employee_data_changes.docs[0]["status"] == "pending"

    def test_tidak_boleh_menyetujui_data_sendiri(self, profil):
        db, ps, ib, _ = profil
        run(ps.update_profile(FakeRequest(BARU)))
        rid = db.rahaza_employee_data_changes.docs[0]["id"]
        with pytest.raises(HTTPException) as e:
            run(ib.approve_request("employee_data_change", rid, ib.ActionPayload(note=""),
                                   user={**STAF, "role": "hr"}))
        assert e.value.status_code == 403

    def test_tarik_pengajuan(self, profil):
        db, ps, _, _ = profil
        run(ps.update_profile(FakeRequest(BARU)))
        run(ps.cancel_profile_change(FakeRequest()))
        assert db.rahaza_employee_data_changes.docs[0]["status"] == "cancelled"
        with pytest.raises(HTTPException) as e:
            run(ps.cancel_profile_change(FakeRequest()))
        assert e.value.status_code == 409

    def test_nomor_tidak_valid_ditolak(self, profil):
        _, ps, _, _ = profil
        with pytest.raises(HTTPException) as e:
            run(ps.update_profile(FakeRequest({"no_hp": "abc"})))
        assert e.value.status_code == 400

    def test_akun_tanpa_karyawan_tetap_di_akun(self, profil):
        db, ps, _, state = profil
        db.users.docs.append({"id": "u-lepas", "name": "Lepas", "role": "admin"})
        state["user"] = {"id": "u-lepas", "name": "Lepas", "role": "admin"}
        out = run(ps.update_profile(FakeRequest({"no_hp": "0814 4444 4444"})))
        assert out["data_change"] is None and db.users.docs[-1]["no_hp"] == "0814 4444 4444"

    def test_isian_lama_di_akun_ditawarkan(self, profil):
        db, ps, _, _ = profil
        db.rahaza_employees.docs[0]["current_address"] = ""
        db.users.docs[0]["alamat"] = "Jl. Akun 9"
        prof = run(ps.get_profile(FakeRequest()))
        assert prof["alamat"] == "Jl. Akun 9" and prof["contact_from_account"] == ["alamat"]

    def test_koleksi_terdaftar(self):
        from core.collection_registry import KIND, is_registered
        assert is_registered("rahaza_employee_data_changes")
        assert KIND["rahaza_employee_data_changes"] == "transaksi"

    def test_notifikasi_hr_saat_diajukan(self, monkeypatch):
        import core.employee_data_change as edc
        import utils.notif_unified as nu
        seen = []

        async def fake_insert(db, **kw):
            seen.append(kw)
            return "n1"
        monkeypatch.setattr(nu, "notif_insert", fake_insert)
        db = _db_profil()
        run(edc.submit_change(db, STAF, db.rahaza_employees.docs[0], {"no_hp": "0815 5555 5555"}))
        assert seen and seen[0]["meta"]["link_module"] == "hr-inbox" and "u-staf" in seen[0]["exclude_user_ids"]


# ═════════════════════════════════════════════════════════════════════════════
# HR2 · Profil Gaji tanpa isian periode yang tidak dipakai
# ═════════════════════════════════════════════════════════════════════════════
class TestProfilGajiPeriode:
    def _upsert(self, monkeypatch, db, body):
        import routes.rahaza_payroll_profiles as rpp

        async def hr(request):
            return {"id": "hr1", "name": "HR", "role": "hr"}
        monkeypatch.setattr(rpp, "_require_hr", hr)
        monkeypatch.setattr(rpp, "get_db", lambda: db)
        monkeypatch.setattr(rpp, "log_activity", _noop)
        return run(rpp.upsert_profile(FakeRequest(body)))

    def test_nilai_tersimpan_tidak_berubah(self, monkeypatch):
        db = FakeDB()
        db.rahaza_employees.docs = [{"id": "e1", "employee_code": "UJI-1", "name": "Uji", "active": True}]
        db.rahaza_payroll_profiles.docs = [{"id": "pp1", "employee_id": "e1", "active": True, "pay_scheme": "weekly",
                                            "period_type": "weekly", "cutoff_config": {"week_start_day": 3},
                                            "base_rate": 100.0, "overtime_rate": 10.0}]
        self._upsert(monkeypatch, db, {"employee_id": "e1", "pay_scheme": "weekly", "base_rate": 120,
                                       "overtime_rate": 10})
        p = db.rahaza_payroll_profiles.docs[0]
        assert p["period_type"] == "weekly" and p["cutoff_config"] == {"week_start_day": 3}
        assert p["base_rate"] == 120.0

    def test_profil_baru_tetap_punya_bawaan(self, monkeypatch):
        db = FakeDB()
        db.rahaza_employees.docs = [{"id": "e2", "employee_code": "UJI-2", "name": "Uji", "active": True}]
        self._upsert(monkeypatch, db, {"employee_id": "e2", "pay_scheme": "monthly", "base_rate": 1})
        p = db.rahaza_payroll_profiles.docs[0]
        assert p["period_type"] == "monthly" and p["cutoff_config"] == {"start_day": 1}

    def test_isian_disembunyikan_di_layar(self):
        src = _frontend("RahazaPayrollProfilesModule.jsx")
        for gone in ("pp-edit-period", "pp-edit-weekday", "Tipe Periode", "Hari Mulai Minggu", "Tanggal Mulai Bulan",
                     "period_type: state.period_type", "cutoff_config: state.cutoff_config"):
            assert gone not in src
