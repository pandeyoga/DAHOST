"""Papan pengumuman — perbaikan data 8 Nov 2026 (uji ketajaman UI/UX).

Membuktikan:
  • tanggal yang dikirim ke layar BERZONA WAKTU (dulu naif → peramban membaca jam setempat, tampil mundur sehari);
  • ubah boleh mengosongkan tanggal (dulu null dibuang);
  • hapus menghilangkan pengumuman dari daftar & papan (dulu hanya nonaktif lalu muncul lagi);
  • tanggal berakhir < mulai ditolak; nama pembuat tersimpan; papan menyaring per portal.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402
from routes import announcements as A  # noqa: E402

HR = {"id": "u-hr", "role": "staff_hr", "name": "Staf SDM Uji"}
STAF = {"id": "u-gudang", "role": "admin_gudang", "name": "Admin Gudang Uji"}
WIB = timezone(timedelta(hours=7))


def run(c):
    return asyncio.run(c)


def buat(db, **kw):
    data = {"title": "Libur (UJI)", "content": "Kantor libur.", "type": "info", "priority": 3,
            "target_portals": ["all"], "is_active": True}
    data.update(kw)
    return run(A.create_announcement(None, A.AnnouncementCreate(**data), db=db, current_user=HR))


def test_tanggal_dikirim_berzona_dan_nama_pembuat_tersimpan():
    db = FakeDB()
    mulai = datetime(2026, 12, 1, 0, 0, tzinfo=WIB)
    akhir = datetime(2026, 12, 12, 23, 59, 59, tzinfo=WIB)
    a = buat(db, start_date=mulai, end_date=akhir)
    assert a["created_by_name"] == "Staf SDM Uji"
    # simulasikan data dari Mongo: datetime NAIF (UTC), seperti yang dikembalikan pymongo
    doc = db.announcements.docs[0]
    doc["start_date"] = mulai.astimezone(timezone.utc).replace(tzinfo=None)
    doc["end_date"] = akhir.astimezone(timezone.utc).replace(tzinfo=None)
    doc["created_at"] = doc["created_at"].replace(tzinfo=None)
    rows = run(A.get_all_announcements(None, skip=0, limit=100, is_active=None, db=db, current_user=HR))
    r = rows[0]
    assert r["start_date"].tzinfo is not None and r["end_date"].tzinfo is not None
    assert r["start_date"].astimezone(WIB).date().isoformat() == "2026-12-01"   # bukan 30 Nov
    assert r["end_date"].astimezone(WIB).date().isoformat() == "2026-12-12"


def test_ubah_boleh_mengosongkan_tanggal_dan_null_lain_diabaikan():
    db = FakeDB()
    a = buat(db, end_date=datetime(2026, 11, 10, 23, 59, 59, tzinfo=WIB), priority=5)
    upd = A.AnnouncementUpdate(end_date=None, priority=None)
    r = run(A.update_announcement(None, a["id"], upd, db=db, current_user=HR))
    assert r["end_date"] is None            # tanggal benar-benar kosong
    assert r["priority"] == 5               # null pada isian lain tidak menimpa


def test_tanggal_berakhir_sebelum_mulai_ditolak():
    db = FakeDB()
    with pytest.raises(HTTPException) as e:
        buat(db, start_date=datetime(2026, 12, 5, tzinfo=WIB), end_date=datetime(2026, 12, 1, tzinfo=WIB))
    assert e.value.status_code == 400 and "berakhir" in e.value.detail
    a = buat(db, start_date=datetime(2026, 12, 5, tzinfo=WIB))
    with pytest.raises(HTTPException):
        run(A.update_announcement(None, a["id"], A.AnnouncementUpdate(end_date=datetime(2026, 12, 1, tzinfo=WIB)),
                                  db=db, current_user=HR))


def test_hapus_menghilangkan_dari_daftar_dan_papan():
    db = FakeDB()
    a = buat(db)
    b = buat(db, title="Tetap (UJI)")
    run(A.delete_announcement(None, a["id"], db=db, current_user=HR))
    ids = [x["id"] for x in run(A.get_all_announcements(None, skip=0, limit=100, is_active=None, db=db, current_user=HR))]
    assert ids == [b["id"]]
    aktif = [x["id"] for x in run(A.get_active_announcements(None, portal=None, db=db, current_user=STAF))]
    assert a["id"] not in aktif
    with pytest.raises(HTTPException) as e:
        run(A.get_announcement(None, a["id"], db=db, current_user=HR))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):     # hapus dua kali → 404, tidak diam-diam "berhasil"
        run(A.delete_announcement(None, a["id"], db=db, current_user=HR))


def test_papan_saring_periode_dan_portal():
    db = FakeDB()
    lalu = datetime.now(timezone.utc) - timedelta(days=2)
    besok = datetime.now(timezone.utc) + timedelta(days=1)
    semua = buat(db, title="Semua (UJI)")
    gudang = buat(db, title="Gudang (UJI)", target_portals=["warehouse"])
    keuangan = buat(db, title="Keuangan (UJI)", target_portals=["finance"])
    terjadwal = buat(db, title="Nanti (UJI)", start_date=besok)
    berakhir = buat(db, title="Lewat (UJI)", end_date=lalu)
    nonaktif = buat(db, title="Mati (UJI)", is_active=False)
    tampil = {x["id"] for x in run(A.get_active_announcements(None, portal="warehouse", db=db, current_user=STAF))}
    assert tampil == {semua["id"], gudang["id"]}
    for x in (keuangan, terjadwal, berakhir, nonaktif):
        assert x["id"] not in tampil


def test_hanya_tim_sdm_yang_boleh_mengelola():
    db = FakeDB()
    with pytest.raises(HTTPException) as e:
        run(A.create_announcement(None, A.AnnouncementCreate(title="x", content="y"), db=db, current_user=STAF))
    assert e.value.status_code == 403 and "SDM" in e.value.detail
    with pytest.raises(HTTPException):
        buat(db, type="bencana")
