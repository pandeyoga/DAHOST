"""Uji unit HERMETIK — "Batalkan persetujuan" (permintaan owner 24 Nov 2026).

Kejadian: style R&D DA-0006 "Gamis bis" disetujui dengan catatan "Tidak pantas" (salah tekan), lalu tidak bisa
dihapus, diarsipkan, maupun ditolak. Sekarang persetujuan bisa dibatalkan selama belum dipakai langkah berikutnya.
Jalankan:  cd backend && python -m pytest tests/unit/test_batal_setuju.py -q
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402
from core import batal_setuju as bs  # noqa: E402

OWNER = {"id": "u-owner", "name": "Owner", "role": "owner"}
STAF = {"id": "u-staf", "name": "Staf Gudang", "role": "staff_gudang", "permissions": []}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _tanpa_log(monkeypatch):
    import auth
    log = []

    async def _log(*a, **k):
        log.append(a)
    monkeypatch.setattr(auth, "log_activity", _log)
    return log


def _db_style(**kw):
    db = FakeDB()
    db.dewi_rnd_styles.docs = [{
        "id": "s6", "style_code": "DA-0006", "style_name": "Gamis bis", "status": "approved_for_launch",
        "owner_review_result": "approved", "owner_reviewed_by": "Super Admin", "owner_reviewed_by_id": "u-owner",
        "owner_reviewed_at": "2026-11-24T06:21:57", "owner_review_notes": "Tidak pantas",
        "submitted_for_review_by_id": "u-ega", **kw}]
    return db


def test_style_salah_setuju_kembali_menunggu_owner_dan_jejak_tersimpan():
    db = _db_style()
    r = run(bs.batalkan(db, "rnd-style", "s6", OWNER, "Salah tekan, seharusnya ditolak"))
    assert r["ok"] and r["status_lama"] == "approved_for_launch" and r["status_baru"] == "pending_owner_review"
    d = db.dewi_rnd_styles.docs[0]
    assert d["status"] == "pending_owner_review"
    assert "owner_review_notes" not in d and "owner_review_result" not in d   # bisa diputus ulang
    ent = d["riwayat_persetujuan"][-1]
    assert ent["aksi"] == "batal_setuju" and ent["alasan"] == "Salah tekan, seharusnya ditolak"
    assert ent["persetujuan_lama"]["owner_review_notes"] == "Tidak pantas"     # keputusan lama tidak hilang
    assert d["persetujuan_dibatalkan_oleh"] == "Owner"


def test_style_sudah_dipromosikan_ditolak_dengan_kalimat():
    db = _db_style(promoted_to_model_id="m1")
    db.rahaza_models.docs = [{"id": "m1", "code": "DA-0006"}]
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "rnd-style", "s6", OWNER, "Salah tekan, seharusnya ditolak"))
    assert e.value.status_code == 409 and "dipromosikan" in e.value.detail and "Master Produk" in e.value.detail
    assert db.dewi_rnd_styles.docs[0]["status"] == "approved_for_launch"


def test_alasan_wajib_minimal_10_huruf():
    db = _db_style()
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "rnd-style", "s6", OWNER, "salah"))
    assert e.value.status_code == 400


def test_bukan_status_disetujui_ditolak():
    db = _db_style(status="draft")
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "rnd-style", "s6", OWNER, "Salah tekan, seharusnya ditolak"))
    assert e.value.status_code == 409


def test_staf_tanpa_izin_setuju_tidak_boleh_membatalkan():
    db = _db_style()
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "rnd-style", "s6", STAF, "Salah tekan, seharusnya ditolak"))
    assert e.value.status_code == 403


def test_jenis_tidak_dikenal_404():
    with pytest.raises(HTTPException) as e:
        bs.ambil_jenis("tidak-ada")
    assert e.value.status_code == 404


def test_semua_jenis_lengkap_dan_kodenya_unik():
    bs._muat()
    assert bs.JENIS, "daftar jenis kosong"
    for k, j in bs.JENIS.items():
        assert k == j.kode and j.koleksi and j.status_setuju and j.label
        assert j.status_kembali({}) not in j.status_setuju, f"{k}: status kembali sama dengan status disetujui"


def test_daftar_disetujui_untuk_pusat_persetujuan():
    db = _db_style()
    rows = run(bs.disetujui_terbaru(db, OWNER, hari=3650))
    assert any(r["jenis"] == "rnd-style" and r["nama"] == "DA-0006 Gamis bis" for r in rows)


# ── SDM ──
def _db_cuti(**kw):
    db = FakeDB()
    db.rahaza_leave_requests.docs = [{
        "id": "c1", "employee_id": "e1", "employee_name": "Ani", "leave_type_id": "lt1", "status": "approved",
        "from_date": "2026-12-01", "to_date": "2026-12-01", "leave_days": ["2026-12-01"], "approval_level_required": 1,
        "approval_step_1": {"approver_id": "u-owner"}, "approved_by": "u-owner", "approved_at": "2026-11-24T01:00:00",
        "balance_deducted_days": 1, "balance_deducted_by_year": {"2026": 1}, "pay_decision": "paid", **kw}]
    db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "e1", "leave_type_id": "lt1", "year": 2026, "used": 3}]
    db.rahaza_attendance_events.docs = [{"id": "a1", "employee_id": "e1", "date": "2026-12-01", "status": "cuti",
                                         "leave_request_id": "c1"}]
    return db


def test_cuti_dibatalkan_saldo_dan_absensi_kembali():
    db = _db_cuti()
    r = run(bs.batalkan(db, "hr-cuti", "c1", OWNER, "Salah setujui, tanggal belum pasti"))
    assert r["status_baru"] == "pending_approval"
    assert db.rahaza_leave_balances.docs[0]["used"] == 2                     # saldo 1 hari dikembalikan
    assert db.rahaza_attendance_events.docs == []                           # absensi buatan cuti dihapus
    d = db.rahaza_leave_requests.docs[0]
    assert "approval_step_1" not in d and "pay_decision" not in d and "balance_deducted_days" not in d


def test_cuti_tanggal_sudah_gaji_final_ditolak():
    db = _db_cuti()
    db.rahaza_payroll_runs.docs = [{"id": "r1", "status": "finalized", "run_number": "PAY-11",
                                    "period_from": "2026-11-26", "period_to": "2026-12-25"}]
    db.rahaza_payslips.docs = [{"id": "p1", "run_id": "r1", "employee_id": "e1"}]
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "hr-cuti", "c1", OWNER, "Salah setujui, tanggal belum pasti"))
    assert e.value.status_code == 409 and "gaji FINAL" in e.value.detail
    assert db.rahaza_leave_balances.docs[0]["used"] == 3                     # tidak ada yang berubah


def test_kasbon_nominal_kembali_ke_permintaan():
    db = FakeDB()
    db.dewi_kasbon_requests.docs = [{"id": "k1", "status": "hr_approved", "amount": 500000, "requested_amount": 1000000,
                                     "outstanding_balance": 500000, "installment_amount": 250000, "installment_count": 2,
                                     "hr_reviewed_by": "HR", "hr_reviewed_at": "2026-11-24T01:00:00"}]
    run(bs.batalkan(db, "hr-kasbon", "k1", OWNER, "Nominal salah, tinjau ulang"))
    d = db.dewi_kasbon_requests.docs[0]
    assert d["status"] == "submitted" and d["amount"] == 1000000 and d["installment_amount"] == 500000
    assert "requested_amount" not in d and "hr_reviewed_by" not in d


# ── Pengadaan ──
def test_po_sudah_diterima_gudang_ditolak():
    db = FakeDB()
    db.rahaza_purchase_orders.docs = [{"id": "po1", "po_number": "PO-1", "status": "approved", "items": [],
                                       "approval_steps": [{"stage": "finance", "action": "approved"}]}]
    db.warehouse_receiving.docs = [{"id": "gr1", "po_id": "po1"}]
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "pengadaan-po", "po1", OWNER, "Harga di PO salah ketik"))
    assert e.value.status_code == 409 and "diterima gudang" in e.value.detail


def test_po_belum_diterima_kembali_menunggu_tahap_terakhir():
    db = FakeDB()
    db.rahaza_purchase_orders.docs = [{"id": "po1", "po_number": "PO-1", "status": "approved", "items": [],
                                       "approved_by": "u-owner", "current_approver_stage": None,
                                       "approval_steps": [{"stage": "dept", "action": "approved"},
                                                          {"stage": "finance", "action": "approved"}]}]
    run(bs.batalkan(db, "pengadaan-po", "po1", OWNER, "Harga di PO salah ketik"))
    d = db.rahaza_purchase_orders.docs[0]
    assert d["status"] == "pending_approval" and d["current_approver_stage"] == "finance"
    assert d["approval_steps"][-1]["action"] == "approval_cancelled"


def test_persetujuan_bertingkat_tingkat_terakhir_dibuka_lagi():
    db = FakeDB()
    db.approval_requests.docs = [{"id": "m1", "subject": "Beli mesin", "status": "approved", "current_level": 2,
                                  "max_level": 2, "completed_at": "2026-11-24T01:00:00", "levels": [
                                      {"level": 1, "status": "approved", "approver_id": "a"},
                                      {"level": 2, "status": "approved", "approver_id": "b", "actioned_at": "x"}]}]
    run(bs.batalkan(db, "persetujuan-bertingkat", "m1", OWNER, "Anggaran belum final"))
    d = db.approval_requests.docs[0]
    assert d["status"] == "pending" and d["current_level"] == 2 and d["completed_at"] is None
    assert d["levels"][0]["status"] == "approved" and d["levels"][1]["status"] == "pending"
    assert "approver_id" not in d["levels"][1]


# ── Keuangan ──
def test_faktur_pemasok_sudah_dibayar_ditolak():
    db = FakeDB()
    db.rahaza_ap_invoices.docs = [{"id": "ap1", "invoice_number": "AP-1", "status": "sent", "paid_amount": 100000}]
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "fin-faktur-pemasok", "ap1", OWNER, "Nominal faktur salah"))
    assert e.value.status_code == 409 and "dibayar" in e.value.detail
