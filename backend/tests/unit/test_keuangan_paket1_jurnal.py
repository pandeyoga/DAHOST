"""Uji unit HERMETIK — Paket 1 audit keuangan 25 Nov 2026 (bagian jurnal inti).

* Batal jurnal di periode TERTUTUP → jurnal pembalik bertanggal hari ini (bukan gagal), kunci sumber dibebaskan.
* "Batalkan persetujuan": status dikunci DULU; bila pembalikan gagal / hambatan muncul belakangan → status dipulihkan.
Jalankan:  cd backend && python -m pytest tests/unit/test_keuangan_paket1_jurnal.py -q
"""
import asyncio
import os
import sys
from datetime import timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402

OWNER = {"id": "u-owner", "name": "Owner", "role": "owner"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _tanpa_log(monkeypatch):
    import auth

    async def _log(*a, **k):
        return None
    monkeypatch.setattr(auth, "log_activity", _log)


def _db_jurnal_bulan_lalu():
    """Satu jurnal faktur penjualan di bulan lalu yang periodenya sudah DITUTUP."""
    from routes.rahaza_posting import today_wib
    hari = today_wib()
    lalu = hari.replace(day=1) - timedelta(days=1)
    db = FakeDB()
    db.rahaza_coa_accounts.docs = [
        {"code": "1-1301", "name": "Piutang Usaha", "type": "ASSET", "active": True},
        {"code": "4-1100", "name": "Penjualan", "type": "REVENUE", "active": True},
    ]
    db.rahaza_periods.docs = [{"id": "p1", "entity": "DA", "period_code": lalu.strftime("%Y-%m"), "status": "closed",
                               "year": lalu.year, "month": lalu.month}]
    lines = [{"account_code": "1-1301", "debit": 100000.0, "credit": 0.0, "description": "INV-1"},
             {"account_code": "4-1100", "debit": 0.0, "credit": 100000.0, "description": "INV-1"}]
    db.rahaza_journal_entries.docs = [{
        "id": "je1", "je_number": "JE-DA-1", "entity": "DA", "date": lalu.isoformat(), "memo": "INV-1",
        "source_module": "ar_invoice", "source_ref": "ar:inv1", "status": "posted",
        "total_debit": 100000.0, "total_credit": 100000.0, "lines": lines}]
    db.rahaza_journal_lines.docs = [{"id": f"l{i}", "je_id": "je1", "entity": "DA", "date": lalu.isoformat(),
                                     "source_module": "ar_invoice", "source_ref": "ar:inv1", **ln}
                                    for i, ln in enumerate(lines)]
    return db, hari, lalu


def test_batal_jurnal_periode_tertutup_jadi_jurnal_pembalik_hari_ini():
    from routes.rahaza_posting import _find_existing_je, _void_je_by_source
    db, hari, lalu = _db_jurnal_bulan_lalu()
    res = run(_void_je_by_source(db, "ar_invoice", "ar:inv1", OWNER, "faktur dibatalkan"))
    assert res["ok"] and res.get("reversed") and not res.get("voided"), res
    asli = next(j for j in db.rahaza_journal_entries.docs if j["id"] == "je1")
    assert asli["status"] == "posted"                                   # laporan bulan tertutup tidak berubah
    assert asli["source_ref"].startswith("ar:inv1#dibalik:") and asli["source_ref_asli"] == "ar:inv1"
    assert len([ln for ln in db.rahaza_journal_lines.docs if ln["je_id"] == "je1"]) == 2   # baris asli tetap
    balik = next(j for j in db.rahaza_journal_entries.docs if j["id"] == res["reversal_je_id"])
    assert balik["date"] == hari.isoformat() and balik["status"] == "posted"
    dr = {ln["account_code"]: (ln["debit"], ln["credit"]) for ln in balik["lines"]}
    assert dr["1-1301"] == (0.0, 100000.0) and dr["4-1100"] == (100000.0, 0.0)          # debit ↔ kredit ditukar
    # kunci sumber bebas: dokumen yang sama bisa dijurnal ulang nanti
    assert run(_find_existing_je(db, "ar_invoice", "ar:inv1")) is None


def test_batal_jurnal_periode_tertutup_tanpa_izin_balik_tetap_ditolak():
    from routes.rahaza_posting import _void_je_by_source
    db, _, _ = _db_jurnal_bulan_lalu()
    res = run(_void_je_by_source(db, "ar_invoice", "ar:inv1", OWNER, "x", boleh_balik=False))
    assert not res["ok"] and "closed" in res["error"]
    assert next(j for j in db.rahaza_journal_entries.docs if j["id"] == "je1")["source_ref"] == "ar:inv1"


def test_batal_jurnal_periode_terbuka_tetap_void_di_tempat():
    from routes.rahaza_posting import _void_je_by_source
    db, _, _ = _db_jurnal_bulan_lalu()
    db.rahaza_periods.docs[0]["status"] = "open"
    res = run(_void_je_by_source(db, "ar_invoice", "ar:inv1", OWNER, "x"))
    assert res["ok"] and res["voided"] and not res.get("reversed")
    assert db.rahaza_journal_entries.docs[0]["status"] == "voided"
    assert not [ln for ln in db.rahaza_journal_lines.docs if ln["je_id"] == "je1"]


# ── Batalkan persetujuan: kunci dulu, pulihkan bila gagal ──
def _db_faktur_pemasok():
    db = FakeDB()
    db.rahaza_ap_invoices.docs = [{"id": "ap1", "invoice_number": "AP-1", "status": "sent", "paid_amount": 0,
                                   "gl_je_id": "je9", "gl_je_number": "JE-9", "gl_posted_at": "2026-11-20T01:00:00"}]
    return db


def test_batal_setuju_pembalikan_gagal_status_dan_jurnal_dipulihkan(monkeypatch):
    from core import batal_setuju as bs
    import routes.rahaza_posting as rp

    async def _void_gagal(db, invoice_id, user, reason=""):
        return {"ok": False, "error": "periode terkunci"}
    monkeypatch.setattr(rp, "void_ap_invoice_posting", _void_gagal)
    db = _db_faktur_pemasok()
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "fin-faktur-pemasok", "ap1", OWNER, "Nominal faktur salah ketik"))
    assert e.value.status_code == 409
    d = db.rahaza_ap_invoices.docs[0]
    assert d["status"] == "sent" and d["gl_je_id"] == "je9" and d["gl_je_number"] == "JE-9"
    assert "persetujuan_dibatalkan" not in d and "riwayat_persetujuan" not in d


def test_batal_setuju_hambatan_muncul_sesudah_cek_status_dipulihkan(monkeypatch):
    """Pembayaran masuk di antara cek pertama dan kunci → cek ulang menolak, status kembali."""
    from core import batal_setuju as bs
    bs._muat()
    j = bs.JENIS["fin-faktur-pemasok"]
    panggil = {"n": 0}

    async def _hambatan(db, d):
        panggil["n"] += 1
        return [] if panggil["n"] == 1 else ["Faktur ini sudah dibayar."]
    monkeypatch.setattr(j, "hambatan", _hambatan)
    db = _db_faktur_pemasok()
    with pytest.raises(HTTPException) as e:
        run(bs.batalkan(db, "fin-faktur-pemasok", "ap1", OWNER, "Nominal faktur salah ketik"))
    assert e.value.status_code == 409 and "dibayar" in e.value.detail
    assert db.rahaza_ap_invoices.docs[0]["status"] == "sent" and db.rahaza_ap_invoices.docs[0]["gl_je_id"] == "je9"


# ── Belum masuk jurnal: satu daftar + posting ulang lewat poster resmi ──
def _db_tertunda():
    db = FakeDB()
    db.rahaza_materials.docs = [{"id": "m1", "code": "DA-1101-MGT-ALLSIZE", "name": "Lyora"}]
    db.rahaza_material_movements.docs = [
        {"id": "mv1", "type": "adjust", "material_id": "m1", "qty": 29.0, "timestamp": "2026-11-18T10:26:13",
         "created_at": "2026-11-18T10:26:13", "post_error": "Amount adjust = 0 (set unit_cost material)."},
        {"id": "mv2", "type": "adjust", "material_id": "m1", "qty": 5.0, "created_at": "2026-11-18T10:00:00",
         "post_error": None, "gl_je_id": "je-ok"},
    ]
    db.rahaza_payroll_runs.docs = [{"id": "r1", "run_number": "PAY-1", "status": "finalized", "post_error": "x",
                                    "created_at": "2026-11-20T00:00:00"}]
    return db


def test_tertunda_daftar_hanya_yang_gagal_dengan_kalimat_staf():
    from core import jurnal_tertunda as jt
    db = _db_tertunda()
    out = run(jt.daftar(db))
    kode = {(r["jenis"], r["id"]) for r in out["data"]}
    assert ("mutasi-stok", "mv1") in kode and ("mutasi-stok", "mv2") not in kode and ("penggajian", "r1") in kode
    mv = next(r for r in out["data"] if r["id"] == "mv1")
    assert "DA-1101-MGT-ALLSIZE" in mv["nama"] and mv["bisa_ulang"] is True
    assert "belum punya HPP" in mv["galat"] and "Amount adjust" in mv["galat_asli"]
    assert next(r for r in out["data"] if r["id"] == "r1")["bisa_ulang"] is False
    assert run(jt.hitung(db)) == 2


def test_tertunda_posting_ulang_memakai_poster_resmi(monkeypatch):
    from core import jurnal_tertunda as jt
    import routes.rahaza_posting as rp
    dipanggil = []

    async def _post(db, mv, user):
        dipanggil.append(mv["id"])
        await db.rahaza_material_movements.update_one({"id": mv["id"]}, {"$set": {"post_error": None, "gl_je_id": "je-baru"}})
        return {"ok": True, "je_id": "je-baru", "je_number": "JE-DA-9"}
    monkeypatch.setattr(rp, "post_inventory_adjust", _post)
    db = _db_tertunda()
    out = run(jt.ulang(db, "mutasi-stok", "mv1", OWNER))
    assert out["ok"] and out["je_number"] == "JE-DA-9" and dipanggil == ["mv1"]
    assert ("mutasi-stok", "mv1") not in {(r["jenis"], r["id"]) for r in run(jt.daftar(db))["data"]}


def test_tertunda_posting_ulang_masih_gagal_409_dengan_kalimat(monkeypatch):
    from core import jurnal_tertunda as jt
    import routes.rahaza_posting as rp

    async def _post(db, mv, user):
        return {"ok": False, "error": "Amount adjust = 0 (set unit_cost material)."}
    monkeypatch.setattr(rp, "post_inventory_adjust", _post)
    with pytest.raises(HTTPException) as e:
        run(jt.ulang(_db_tertunda(), "mutasi-stok", "mv1", OWNER))
    assert e.value.status_code == 409 and "HPP" in e.value.detail


def test_tertunda_jenis_tanpa_ulang_dan_dokumen_bukan_tertunda_ditolak():
    from core import jurnal_tertunda as jt
    db = _db_tertunda()
    with pytest.raises(HTTPException) as e:
        run(jt.ulang(db, "penggajian", "r1", OWNER))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(jt.ulang(db, "mutasi-stok", "mv2", OWNER))          # sudah berjurnal → tidak ada di daftar
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        run(jt.ulang(db, "tidak-ada", "x", OWNER))
    assert e.value.status_code == 404
