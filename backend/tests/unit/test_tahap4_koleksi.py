"""Uji HERMETIK Tahap 4 — sapuan pola P2/P3/P4 (agen "koleksi", 2026-11-06). Tanpa server/Mongo.

P2 = kode membaca/menulis koleksi yang salah/lama · P3 = nama field penulis ≠ pembaca ·
P4 = proyeksi/saringan status membuang data yang dibutuhkan.
"""
import asyncio
import importlib
import importlib.util
import os
import sys
from datetime import datetime, timezone

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

from _fake_mongo import FakeCollection, FakeCursor, FakeDB, FakeRequest  # noqa: E402

run = asyncio.run
HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR"}
ADMIN = {"id": "u-adm", "role": "admin", "name": "Admin"}


def _import_needing_multipart(name):
    """Rute unggah memeriksa python-multipart saat impor — dilewati bila tidak terpasang."""
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


def _load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Mongo palsu + aggregate perekam (hanya di berkas ini; helper bersama tidak diubah) ─────────
class _RecColl(FakeCollection):
    def aggregate(self, pipeline):
        self.pipelines = getattr(self, "pipelines", []) + [pipeline]
        return FakeCursor([])


class RecDB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _RecColl(name)
        return self._cols[name]


async def _noop(*a, **k):
    return None


def _auth_as(user):
    async def _auth(*a, **k):
        return dict(user)
    return _auth


# ═════════════════════════════════════════════════════════════════════════════
# P2 — koleksi hantu
# ═════════════════════════════════════════════════════════════════════════════
class TestKoleksiHantu:
    def test_pemindai_penulis_koleksi_tinggal_satu_hantu(self):
        """21 koleksi "dibaca tanpa penulis" → tinggal `hr_issued_documents` (keputusan owner)."""
        chk = _load_file(os.path.join(REPO, "scripts", "check_collection_writers.py"), "_chk_writers")
        readers, writers = chk.scan()
        orphans = {c for c in readers if c not in writers and c not in chk.WHITELIST}
        assert orphans <= {"hr_issued_documents"}, sorted(orphans)

    def test_laporan_aksesoris_dari_vendor_shipments(self):
        from routes import operations_reports as orp
        db = FakeDB()
        db.vendor_shipments.docs += [
            {"id": "s1", "shipment_number": "SJ-1", "vendor_id": "v1", "vendor_name": "CMT A",
             "po_number": "PO-1", "status": "Received", "created_at": "2026-11-01"},
            {"id": "s2", "shipment_number": "SJ-2", "vendor_id": "v2", "vendor_name": "CMT B",
             "created_at": "2026-11-02"},
            {"id": "s3", "shipment_number": "SJ-3", "vendor_id": "v1", "created_at": "2026-11-03"},  # tanpa aksesoris
        ]
        db.accessory_shipment_items.docs += [
            {"id": "a1", "shipment_id": "s1", "accessory_name": "Kancing", "qty_sent": 10},
            {"id": "a2", "shipment_id": "s2", "accessory_name": "Label", "qty_sent": 5},
        ]
        rows = run(orp._accessory_shipments(db))
        assert [(h["id"], [i["id"] for i in its]) for h, its in rows] == [("s2", ["a2"]), ("s1", ["a1"])]
        only_v1 = run(orp._accessory_shipments(db, "v1"))
        assert [h["id"] for h, _ in only_v1] == ["s1"]
        assert run(orp._accessory_shipments(FakeDB())) == []

    def test_label_fg_hanya_dari_master_material(self):
        from routes import wms_fg_labels as fl
        db = FakeDB()
        db.rahaza_materials.docs += [{"id": "fg1", "type": "fg", "code": "DA-1-M"},
                                     {"id": "rm1", "type": "yarn", "code": "BNG-1"}]
        assert run(fl._find_fg(db, "DA-1-M"))["id"] == "fg1"
        assert run(fl._find_fg(db, "BNG-1")) is None
        assert [r["id"] for r in run(fl._find_fg_many(db, ["fg1", "rm1"]))] == ["fg1"]

    def test_okupansi_rak_dari_wh_racks_dan_wh_positions(self, monkeypatch):
        from routes import dewi_warehouse_smart as ws
        from routes import wms_receiving as wr
        db = FakeDB()
        db.wh_racks.docs += [{"id": "r1", "code": "R1", "num_shelves": 2, "slots_per_shelf": 2,
                              "building_code": "G1", "zone_code": "A"}]
        db.wh_positions.docs += [{"rack_id": "r1", "status": "occupied"} for _ in range(4)]
        assert run(wr.rack_occupancy(db, db.wh_racks.docs[0])) == (4, 4)
        assert run(wr.rack_occupancy(db, {"id": "x"})) == (0, 0)

        async def _no_low(_db):
            return []

        async def _summary(_db):
            return {"total_materials": 0, "with_threshold": 0, "missing_threshold": 0}
        from core import stock_thresholds
        monkeypatch.setattr(stock_thresholds, "low_stock_alerts", _no_low)
        monkeypatch.setattr(stock_thresholds, "summary", _summary)
        monkeypatch.setattr(ws, "get_db", lambda: db)
        monkeypatch.setattr(ws, "require_auth", _auth_as(ADMIN))
        out = run(ws.get_warehouse_alerts(FakeRequest(), threshold=90))
        alerts = out["data"] if isinstance(out, dict) and "data" in out else out
        assert alerts[0]["rack_code"] == "R1" and alerts[0]["occupancy_pct"] == 100
        assert alerts[0]["severity"] == "critical" and alerts[0]["location"] == "G1-A"

    def test_scan_nomor_surat_jalan_ditemukan(self):
        from core import scan_resolver as sr
        db = FakeDB()
        db.vendor_shipments.docs += [{"id": "s1", "shipment_number": "SJ-CMT-0001",
                                      "delivery_note_number": "DN-77", "vendor_name": "CMT A",
                                      "shipment_date": "2026-11-01T08:00:00", "po_number": "PO-9"}]
        db.buyer_shipments.docs += [{"id": "b1", "shipment_number": "SJB-0002", "customer_name": "Toko B"}]
        r = run(sr.resolve_document(db, "SJ-CMT-0001"))
        assert r and r["kode"] == "SJ-CMT-0001" and r["meta"]["Vendor"] == "CMT A"
        assert run(sr.resolve_document(db, "DN-77"))["kode"] == "DN-77"
        assert run(sr.resolve_document(db, "SJB-0002"))["meta"]["Customer"] == "Toko B"

    def test_kartu_stok_aksesoris_tanpa_cabang_pinjaman_hantu(self):
        mod = _import_needing_multipart("routes.dewi_accessories_stock")
        db = FakeDB()
        db.dewi_accessory_requests.docs += [{"id": "rq1", "request_code": "REQ-1", "divisi": "Jahit"}]
        mv = run(mod._enrich_movement(db, {"reference_type": "accessory_request", "reference_id": "rq1",
                                           "related_loan_id": "x"}))
        assert mv["related_request"] == {"request_number": "REQ-1", "division": "Jahit"}
        assert "related_loan" not in mv
        for name in ("dashboard", "items", "loans", "purchase", "requests"):
            m = _import_needing_multipart(f"routes.dewi_accessories_{name}")
            assert not hasattr(m, "_enrich_movement"), name

    def test_dasbor_lifecycle_cmt_tanpa_koleksi_lama(self):
        src = open(os.path.join(BACKEND, "routes", "dewi_cmt_lifecycle.py"), encoding="utf-8").read()
        assert "db.dewi_cmt_delivery_orders" not in src and "db.dewi_cmt_progress." not in src

    def test_permintaan_material_dan_picklist_tanpa_cadangan_hantu(self):
        for rel, ghost in (("routes/operations_reports.py", "material_request_items"),
                           ("routes/wms_picklist.py", "dewi_material_issues")):
            src = open(os.path.join(BACKEND, *rel.split("/")), encoding="utf-8").read()
            assert f"db.{ghost}." not in src, rel


# ═════════════════════════════════════════════════════════════════════════════
# P2 — Auto Akun: Supplier = rahaza_suppliers
# ═════════════════════════════════════════════════════════════════════════════
def _coa_db():
    db = FakeDB()
    db.rahaza_coa_accounts.docs += [
        {"id": "a1", "code": "2-1100", "name": "Hutang Usaha", "type": "LIABILITY", "is_group": False, "active": True},
        {"id": "a2", "code": "1-1305", "name": "Piutang Maklon", "type": "ASSET", "is_group": False, "active": True},
        {"id": "a3", "code": "4-1500", "name": "Pendapatan Maklon", "type": "REVENUE", "is_group": True, "active": True},
    ]
    return db


@pytest.fixture
def coa(monkeypatch):
    from routes import coa_auto
    monkeypatch.setattr(coa_auto, "log_activity", _noop)
    return coa_auto


class TestAutoAkunPemasok:
    def test_setelan_lama_rahaza_vendors_disembuhkan(self, coa):
        db = _coa_db()
        et = {k: dict(v) for k, v in coa.DEFAULT_ENTITY_TYPES.items()}
        et["supplier"] = {**et["supplier"], "collection": "rahaza_vendors", "parent_code": "2-1100", "enabled": True}
        db.rahaza_coa_auto_settings.docs.append({"id": "default", "entity_types": et})
        s = run(coa.get_auto_settings(db))
        assert s["entity_types"]["supplier"]["collection"] == "rahaza_suppliers"
        assert db.rahaza_coa_auto_settings.docs[0]["entity_types"]["supplier"]["collection"] == "rahaza_suppliers"
        # pilihan pengguna (induk & aktif) tidak disentuh
        assert s["entity_types"]["supplier"]["parent_code"] == "2-1100"

    def test_subledger_pemasok_dibuat_di_master_pemasok(self, coa):
        db = _coa_db()
        db.rahaza_suppliers.docs.append({"id": "sup1", "code": "SUP-1", "name": "PT Benang", "is_active": True})
        code = run(coa.resolve_subledger_account(db, "supplier", entity_id="sup1"))
        assert code == "2-1100-SUP-1"
        assert db.rahaza_suppliers.docs[0]["ap_account_code"] == "2-1100-SUP-1"
        assert run(coa.resolve_subledger_account(db, "supplier", entity_code="SUP-1")) == "2-1100-SUP-1"

    def test_posting_faktur_dari_gr_memakai_supplier_id(self, coa, monkeypatch):
        from routes import rahaza_posting as rp
        db = _coa_db()
        db.rahaza_suppliers.docs.append({"id": "sup1", "code": "SUP-1", "name": "PT Benang", "is_active": True})
        seen = {}

        async def _mapping(_db, event):
            return {"credit_ap": "2-1100"}          # tanpa akun debit → berhenti setelah resolusi hutang

        real = coa.resolve_subledger_account

        async def _spy(db_, et, **kw):
            seen.update(kw, et=et)
            return await real(db_, et, **kw)
        monkeypatch.setattr(rp, "get_mapping", _mapping)
        monkeypatch.setattr(coa, "resolve_subledger_account", _spy)
        inv = {"id": "ap1", "invoice_number": "AP-1", "supplier_id": "sup1", "supplier_code": "SUP-1",
               "vendor_code": "SUP-1", "vendor_name": "PT Benang", "total": 1000}
        res = run(rp.post_ap_invoice(db, inv, ADMIN))
        assert res["ok"] is False                       # mapping sengaja tidak lengkap
        assert seen["et"] == "supplier" and seen["entity_id"] == "sup1"
        assert db.rahaza_suppliers.docs[0]["ap_account_code"] == "2-1100-SUP-1"

    def test_sinkron_startup_melewati_pemasok_nonaktif(self, coa):
        from core import finance_sync as fs
        db = _coa_db()
        db.rahaza_suppliers.docs += [{"id": "s1", "code": "S1", "name": "Aktif", "is_active": True},
                                     {"id": "s2", "code": "S2", "name": "Mati", "is_active": False}]
        report = {}
        run(fs._backfill_subledgers(db, report, None))
        flagged = {a["flags"]["subledger_entity_id"] for a in db.rahaza_coa_accounts.docs
                   if (a.get("flags") or {}).get("subledger_entity_type") == "supplier"}
        assert flagged == {"s1"} and report["subledgers_created"]["supplier"] == 1

    def test_keterikatan_akun_membaca_master_pemasok(self):
        from core import coa_bindings as cb
        db = FakeDB()
        et = {"supplier": {"collection": "rahaza_vendors", "target_field": "ap_account_code"}}
        db.rahaza_coa_auto_settings.docs.append({"id": "default", "entity_types": et})
        got = run(cb._auto_settings(db))
        assert got["supplier"]["collection"] == "rahaza_suppliers"
        assert cb.ENTITY_SCREENS["rahaza_suppliers"]["module"] == "proc-suppliers"

    def test_impor_vendor_cmt_memetakan_master_ssot(self):
        src = open(os.path.join(BACKEND, "routes", "data_transfer.py"), encoding="utf-8").read()
        assert '"vendor_partners": "cmt_vendor"' in src and '"dewi_cmt_partners": "cmt_vendor"' not in src
        rec = open(os.path.join(BACKEND, "routes", "rahaza_payment_receipt.py"), encoding="utf-8").read()
        assert '("rahaza_suppliers", "supplier_id")' in rec

    def test_piutang_maklon_lama_ke_subledger_klien(self, coa, monkeypatch):
        from routes import dewi_maklon_finance as mf
        db = _coa_db()
        db.dewi_maklon_clients.docs.append({"id": "kl1", "code": "KL1", "name": "Klien Satu", "active": True})
        db.rahaza_ar_invoices.docs.append({"id": "ar1", "status": "issued", "total_amount": 1000.0,
                                           "tax_amount": 0, "customer_id": "kl1"})
        lines_seen = {}

        async def _mapping(_db, event):
            return {"debit_ar": "1-1305", "credit_revenue_maklon": "4-1500"}

        async def _post(db_, je_date, memo, source_module, source_ref, lines_raw, user, **_kw):
            lines_seen["lines"] = lines_raw
            return {"ok": True, "je_id": "je1", "je_number": "JE-1"}
        monkeypatch.setattr(mf, "get_mapping", _mapping)
        monkeypatch.setattr(mf, "_create_posted_je", _post)
        res = run(mf.post_maklon_ar_invoice(db, {"id": "po1", "ar_invoice_id": "ar1", "client_id": "kl1",
                                                 "po_number": "PO-1"}, ADMIN))
        assert res.get("ok")
        assert lines_seen["lines"][0]["account_code"] == "1-1305-KL1"

    def test_migrasi_pratinjau_lalu_tulis(self, coa):
        mig = _load_file(os.path.join(BACKEND, "scripts", "migrations", "2026_11_07_subledger_pemasok.py"),
                         "_mig_subledger_pemasok")
        # murni
        fixes = mig.settings_fixes({"supplier": {"collection": "rahaza_vendors", "target_field": "ap_account_code"}},
                                   coa.DEFAULT_ENTITY_TYPES)
        assert fixes == {"supplier": {"collection": ("rahaza_vendors", "rahaza_suppliers")}}
        todo = mig.suppliers_without_subledger(
            [{"id": "a"}, {"id": "b", "is_active": False}, {"id": "c"}, {"code": "tanpa-id"}], {"c"})
        assert [s["id"] for s in todo] == ["a"]
        # pratinjau: tidak menulis apa pun
        db = _coa_db()
        et = {k: dict(v) for k, v in coa.DEFAULT_ENTITY_TYPES.items()}
        et["supplier"]["collection"] = "rahaza_vendors"
        db.rahaza_coa_auto_settings.docs.append({"id": "default", "entity_types": et})
        db.rahaza_suppliers.docs.append({"id": "sup1", "code": "SUP-1", "name": "PT Benang", "is_active": True})
        n_acc = len(db.rahaza_coa_accounts.docs)
        out = run(mig.run(db, apply=False))
        assert out["settings"]["types_fixed"] == 1 and out["suppliers"]["without_subledger"] == 1
        assert len(db.rahaza_coa_accounts.docs) == n_acc
        assert db.rahaza_coa_auto_settings.docs[0]["entity_types"]["supplier"]["collection"] == "rahaza_vendors"
        # tulis + idempoten
        out = run(mig.run(db, apply=True))
        assert out["suppliers"]["created"] == 1
        assert db.rahaza_suppliers.docs[0]["ap_account_code"] == "2-1100-SUP-1"
        again = run(mig.run(db, apply=True))
        assert again["settings"]["types_fixed"] == 0 and again["suppliers"]["without_subledger"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# P3 — nama field penulis ≠ pembaca
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def inbox(monkeypatch):
    import routes.hr_approval_inbox as ib
    db = FakeDB()
    monkeypatch.setattr(ib, "get_db", lambda: db)
    monkeypatch.setattr(ib, "log_activity", _noop)
    monkeypatch.setattr(ib, "_require_approver_role", lambda user: None)
    ib._db = db
    return ib


class TestInboxHr:
    def _resigning(self, db):
        db.rahaza_employees.docs.append({
            "id": "e1", "name": "Ani", "employee_code": "E01", "job_title": "Operator Jahit", "active": True,
            "employee_status": "resigning", "resignation_date": "2026-11-30", "last_working_date": "2026-11-28",
            "reason_for_leaving": "Pindah kota", "resignation_submitted_at": datetime(2026, 11, 6, tzinfo=timezone.utc)})

    def test_resignasi_tampil_dengan_field_penulis(self, inbox):
        self._resigning(inbox._db)
        items = run(inbox._fetch_resignations(inbox._db, None, 10))
        assert len(items) == 1
        it = items[0]
        assert it["title"] == "Resignasi efektif 2026-11-30" and it["reason"] == "Pindah kota"
        assert it["meta"]["last_working_date"] == "2026-11-28" and it["meta"]["position"] == "Operator Jahit"
        assert run(inbox.inbox_summary(user=dict(HR)))["resignation"] == 1

    def test_setujui_resignasi_menonaktifkan_karyawan(self, inbox):
        self._resigning(inbox._db)
        run(inbox.approve_request("resignation", "e1", inbox.ActionPayload(note="ok"), user=dict(HR)))
        e = inbox._db.rahaza_employees.docs[0]
        assert e["employee_status"] == "resigned" and e["active"] is False
        assert e["resignation_accepted_by"] == "u-hr"
        with pytest.raises(HTTPException):
            run(inbox.approve_request("resignation", "e1", inbox.ActionPayload(), user=dict(HR)))

    def test_tolak_resignasi_karyawan_kembali_aktif(self, inbox):
        self._resigning(inbox._db)
        run(inbox.reject_request("resignation", "e1", inbox.ActionPayload(reason="batal"), user=dict(HR)))
        e = inbox._db.rahaza_employees.docs[0]
        assert e["employee_status"] == "active" and e["active"] is True
        assert run(inbox._fetch_resignations(inbox._db, None, 10)) == []

    def test_absen_pending_membaca_clock_in_hours_worked(self, inbox):
        db = inbox._db
        db.rahaza_employees.docs.append({"id": "e1", "name": "Ani"})
        db.rahaza_attendance_events.docs.append({
            "id": "ev1", "employee_id": "e1", "date": "2026-09-30", "approval_status": "pending",
            "clock_in": datetime(2026, 9, 30, 2, 35, tzinfo=timezone.utc), "clock_out": "2026-09-30T02:45:11.502Z",
            "hours_worked": 0.16, "attendance_method": "selfie_geo_ai", "notes": "di luar jam",
            "clock_in_geo": {"lat": -7.48, "lng": 110.95, "distance_m": 18}})
        it = run(inbox._fetch_attendance(db, None, 10))[0]
        assert it["title"] == "Absen 2026-09-30 — 09:35 → 09:45"
        m = it["meta"]
        assert m["work_hours"] == 0.16 and m["attendance_type"] == "Selfie" and m["geo_distance_m"] == 18
        assert m["location"] == "-7.48, 110.95" and it["reason"] == "di luar jam"


class TestFieldKaryawan:
    def test_jabatan_dari_job_title(self):
        from utils.employee_identity import job_title_of
        assert job_title_of({"job_title": "Admin"}) == "Admin"
        assert job_title_of({"position": "Lama"}) == "Lama"
        assert job_title_of(None) == ""

    def test_headcount_produksi_memakai_active(self):
        from routes import wms_capacity_planning as cp
        db = FakeDB()
        db.rahaza_employees.docs += [{"id": "1", "department": "Produksi", "active": True},
                                     {"id": "2", "department": "Produksi"},
                                     {"id": "3", "department": "Produksi", "active": False},
                                     {"id": "4", "department": "HRD", "active": True}]
        assert run(cp._employee_headcount(db)) == 2

    def test_rekan_portal_saya_memakai_active(self, monkeypatch):
        from routes import dewi_portal_saya_ext as ext
        db = FakeDB()
        db.rahaza_employees.docs += [{"id": "me", "name": "Saya", "active": True, "user_id": "u1"},
                                     {"id": "p1", "name": "Rekan", "active": True},
                                     {"id": "p2", "name": "Keluar", "active": False}]
        monkeypatch.setattr(ext, "get_db", lambda: db)
        monkeypatch.setattr(ext, "require_auth", _auth_as({"id": "u1", "role": "staff"}))

        async def _me(_db, _user):
            return db.rahaza_employees.docs[0]
        monkeypatch.setattr(ext, "_get_my_employee", _me)
        out = run(ext.get_peers_for_feedback(FakeRequest()))
        data = out.get("data") if isinstance(out, dict) else out
        assert [p["id"] for p in data] == ["p1"]

    def test_pencarian_karyawan_tanggal_masuk(self):
        from routes import unified_search as us
        db = FakeDB()
        db.rahaza_employees.docs.append({"_id": "x", "name": "Ani", "employee_code": "E01", "join_date": "2025-01-02",
                                         "active": False})
        r = run(us.search_employees(db, "Ani"))[0]
        assert r["metadata"]["hire_date"] == "2025-01-02" and r["metadata"]["status"] == "inactive"


class TestLaporanHr:
    @pytest.fixture
    def rep(self, monkeypatch):
        from routes import rahaza_hr_reports as hr
        db = FakeDB()
        monkeypatch.setattr(hr, "get_db", lambda: db)
        monkeypatch.setattr(hr, "require_auth", _auth_as(HR))
        hr._db = db
        return hr

    def test_turnover_menghitung_kedua_nama_tanggal_keluar_dan_departemen(self, rep):
        db = rep._db
        db.rahaza_employees.docs += [
            {"id": "a", "name": "A", "department": "Jahit", "active": False, "resign_date": "2026-03-05"},
            {"id": "b", "name": "B", "department": "Jahit", "active": False, "resignation_date": "2026-04-10"},
            {"id": "c", "name": "C", "department": "HRD", "active": False, "resignation_date": "2026-04-11"},
            {"id": "d", "name": "D", "department": "Jahit", "active": True, "join_date": "2026-02-01"},
        ]
        out = run(rep.get_turnover_report(FakeRequest(), "2026-01-01", "2026-06-30", "Jahit"))
        flat = str(out)
        assert "'b'" in flat or '"b"' in flat or "B" in flat
        months = {r["month"]: r for r in out["chart_data"]}
        assert months["2026-03"]["resignations"] == 1 and months["2026-04"]["resignations"] == 1
        assert months["2026-02"]["hires"] == 1

    def test_ringkasan_absen_saring_nama_departemen_dan_nama_shift(self, rep, monkeypatch):
        db = rep._db
        db.rahaza_shifts.docs.append({"id": "sh1", "code": "PAGI", "name": "Shift Pagi"})
        db.rahaza_employees.docs += [
            {"id": "a", "name": "A", "employee_code": "A1", "department": "Jahit", "shift_id": "sh1", "active": True},
            {"id": "b", "name": "B", "employee_code": "B1", "department": "HRD", "active": True}]

        async def _counts(*a, **k):
            return {}, {}

        async def _present(*a, **k):
            return {}

        async def _wd(*a, **k):
            return []
        monkeypatch.setattr(rep, "_attendance_counts", _counts)
        monkeypatch.setattr(rep, "_present_on_working_days", _present)
        monkeypatch.setattr(rep, "_work_days", _wd)
        out = run(rep.get_attendance_summary(FakeRequest(), "2026-11-01", "2026-11-05", "Jahit", None, None, None))
        assert [r["employee_id"] for r in out["summary"]] == ["a"]
        assert out["summary"][0]["department_name"] == "Jahit" and out["summary"][0]["shift_name"] == "Shift Pagi"

    def test_layar_departemen_tidak_lagi_diisi_lokasi(self):
        src = open(os.path.join(REPO, "frontend", "src", "components", "erp", "RahazaHRReportsModule.jsx"),
                   encoding="utf-8").read()
        assert "deptRes" not in src and "e.department" in src


class TestFieldLain:
    def test_harga_bawaan_nota_dari_item_katalog_tertaut(self, monkeypatch):
        from routes import sales_direct as sd
        db = FakeDB()
        db.rahaza_materials.docs.append({"id": "fg1", "code": "DA-1-M", "name": "Kaos", "type": "fg"})
        db.marketing_catalog_items.docs += [{"id": "c0", "fg_material_id": "fg1", "harga_jual": 0, "price": 0},
                                            {"id": "c1", "fg_material_id": "fg1", "harga_jual": 85000, "price": 85000}]

        async def _avail(_db, material_ids=None):
            return {"fg1": 4.0}
        monkeypatch.setattr(sd, "_fg_available_map", _avail)
        monkeypatch.setattr(sd, "get_db", lambda: db)
        monkeypatch.setattr(sd, "require_auth", _auth_as(ADMIN))
        rows = run(sd.fg_stock(FakeRequest()))
        assert rows[0]["default_price"] == 85000

    def test_kategori_klaim_coa_hanya_akun_aktif_bukan_grup(self, monkeypatch):
        from routes import employee_expense_claims as ec
        db = FakeDB()
        db.rahaza_coa_accounts.docs += [{"code": "6-3000", "name": "Grup", "is_group": True},
                                        {"code": "6-3100", "name": "Transport"},
                                        {"code": "6-3200", "name": "Mati", "active": False}]
        monkeypatch.setattr(ec, "get_db", lambda: db)
        out = run(ec.get_categories(user=dict(ADMIN)))
        assert out["source"] == "coa" and [c["code"] for c in out["categories"]] == ["6-3100"]

    def test_vendor_nonaktif_lewat_is_active_tampil_nonaktif(self, monkeypatch):
        from routes import master_data as md
        db = FakeDB()
        db.vendor_partners.docs += [{"id": "v1", "name": "A", "code": "A", "active": True, "is_active": False},
                                    {"id": "v2", "name": "B", "code": "B", "active": True, "is_active": True}]
        monkeypatch.setattr(md, "get_db", lambda: db)
        monkeypatch.setattr(md, "require_auth", _auth_as(ADMIN))
        req = FakeRequest()
        req.query_params = {}
        rows = run(md.get_garments(req))
        st = {r["id"]: r["status"] for r in rows}
        assert st == {"v1": "inactive", "v2": "active"}

    def test_viewer_produk_jumlah_baris_bom_dari_materials(self):
        src = open(os.path.join(BACKEND, "routes", "rnd_product_viewer.py"), encoding="utf-8").read()
        assert 'bom.get("materials") or bom.get("items")' in src

    def test_dasbor_produksi_qty_periode_dari_tanggal_baris_dan_pic_toko(self):
        src = open(os.path.join(BACKEND, "routes", "production_dashboard.py"), encoding="utf-8").read()
        assert 'for s in bs if str(s.get("shipment_date")' not in src and 'r.get("dispatch_date")' in src
        wk = open(os.path.join(BACKEND, "core", "marketing_weekly_report.py"), encoding="utf-8").read()
        assert 'acc.get("pic_user_name")' in wk
        mr = open(os.path.join(BACKEND, "routes", "marketing_reports.py"), encoding="utf-8").read()
        assert '"id": 1, "account_code": 1, "account_name": 1, "platform": 1' in mr

    def test_kalender_portal_saya_cuti_menunggu_dan_nama_jenis(self, monkeypatch):
        from routes import dewi_portal_saya_workspace as ws
        db = FakeDB()
        db.rahaza_leave_types.docs.append({"id": "lt1", "name": "Cuti tahunan"})
        db.rahaza_leave_requests.docs += [
            {"id": "l1", "employee_id": "e1", "leave_type_id": "lt1", "status": "pending_hr_approval",
             "from_date": "2026-11-10", "to_date": "2026-11-11"},
            {"id": "l2", "employee_id": "e1", "leave_type_id": "lt1", "status": "approved",
             "from_date": "2026-11-20", "to_date": "2026-11-20"},
            {"id": "l3", "employee_id": "e1", "leave_type_id": "lt1", "status": "rejected",
             "from_date": "2026-11-21", "to_date": "2026-11-21"}]
        monkeypatch.setattr(ws, "get_db", lambda: db)
        monkeypatch.setattr(ws, "require_auth", _auth_as({"id": "u1", "role": "staff"}))

        async def _linked(_db, uid):
            return None, {"id": "e1"}
        monkeypatch.setattr(ws, "_get_linked_employee", _linked)
        out = run(ws.combined_calendar(FakeRequest(), from_="2026-11-01", to="2026-11-30"))
        leaves = {e["id"]: e["title"] for e in out["events"] if e.get("type") == "leave"}
        assert leaves == {"l1": "Cuti tahunan: menunggu persetujuan", "l2": "Cuti tahunan: disetujui"}


# ═════════════════════════════════════════════════════════════════════════════
# P4 — saringan status yang melewatkan status penulis
# ═════════════════════════════════════════════════════════════════════════════
class TestSaringanStatus:
    def test_jenis_cuti_tidak_bisa_dimatikan_saat_menunggu_hr(self, monkeypatch):
        lv = _import_needing_multipart("routes.rahaza_leave")
        db = FakeDB()
        db.rahaza_leave_types.docs.append({"id": "lt1", "name": "Cuti", "active": True})
        db.rahaza_leave_requests.docs.append({"id": "r1", "leave_type_id": "lt1", "status": "pending_hr_approval"})
        monkeypatch.setattr(lv, "get_db", lambda: db)

        async def _hr(_req):
            return dict(HR)
        monkeypatch.setattr(lv, "_require_hr_admin", _hr)
        with pytest.raises(HTTPException) as e:
            run(lv.deactivate_leave_type("lt1", FakeRequest()))
        assert e.value.status_code == 409
        assert db.rahaza_leave_types.docs[0]["active"] is True

    def test_ringkasan_finance_hutang_termasuk_overdue(self, monkeypatch):
        from routes import rahaza_finance as rf
        db = RecDB()
        monkeypatch.setattr(rf, "get_db", lambda: db)
        monkeypatch.setattr(rf, "require_auth", _auth_as(ADMIN))

        async def _cash(_db, _q):
            return []
        monkeypatch.setattr(rf, "_cash_accounts_with_gl", _cash)
        try:
            run(rf.finance_summary(FakeRequest()))
        except Exception:  # noqa: BLE001 — sisa ringkasan tidak relevan; yang diuji saringan hutangnya
            pass
        match = db.rahaza_ap_invoices.pipelines[0][0]["$match"]["status"]["$in"]
        assert set(match) == {"sent", "partial_paid", "overdue"}

    def test_dasbor_gudang_gr_menunggu_termasuk_diproses(self, monkeypatch):
        from routes import warehouse as wh
        db = RecDB()
        db.warehouse_receiving.docs += [{"id": "g1", "status": "draft"}, {"id": "g2", "status": "processing"},
                                        {"id": "g3", "status": "received"}]
        monkeypatch.setattr(wh, "get_db", lambda: db)
        monkeypatch.setattr(wh, "require_auth", _auth_as(ADMIN))
        out = run(wh.warehouse_dashboard_kpi(FakeRequest()))
        assert out["pending_gr"] == 2
        src = open(os.path.join(BACKEND, "routes", "warehouse.py"), encoding="utf-8").read()
        assert '{"$in": ["draft", "inspecting"]}' not in src
