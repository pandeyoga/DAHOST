"""Migrasi 2026-11-08: akun berperan bawaan kosong `operator_cuting` dipindah ke peran pemilik "Operator Cuting"."""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_mongo import FakeDB  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "mig_pindah_peran", ROOT / "scripts" / "migrations" / "2026_11_08_pindah_peran_kosong.py")
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def run(c):
    return asyncio.run(c)


def _db(asal_portal=None, asal_izin=False, tujuan_portal=("cutting", "warehouse")):
    db = FakeDB()
    db.roles.docs = [
        {"id": "r-asal", "name": "operator_cuting", "portals": list(asal_portal or [])},
        {"id": "r-tuju", "name": "Operator Cuting", "portals": list(tujuan_portal)},
        {"id": "r-lain", "name": "spv_cuting", "portals": ["cutting"]},
    ]
    db.role_permissions.docs = [{"role_id": "r-tuju", "permission_key": "cutting.view"}]
    if asal_izin:
        db.role_permissions.docs.append({"role_id": "r-asal", "permission_key": "cutting.view"})
    db.users.docs = [
        {"id": "u1", "role": "operator_cuting", "is_active": True},
        {"id": "u2", "role": "OPERATOR_CUTING", "is_active": False},
        {"id": "u3", "role": "spv_cuting", "is_active": True},
    ]
    return db


def test_pratinjau_tidak_menulis_lalu_apply_memindah_dan_idempoten():
    db = _db()
    pra = run(mig.run(db, apply=False))
    assert pra["pasangan"]["operator_cuting"]["akun"] == 2 and pra["dipindah"] == 0
    assert db.users.docs[0]["role"] == "operator_cuting"
    hasil = run(mig.run(db, apply=True))
    assert hasil["dipindah"] == 2
    u = {d["id"]: d for d in db.users.docs}
    assert u["u1"]["role"] == "Operator Cuting" and u["u1"]["role_id"] == "r-tuju"
    assert u["u3"]["role"] == "spv_cuting"                       # peran lain tidak disentuh
    assert run(mig.run(db, apply=True))["dipindah"] == 0         # idempoten


def test_peran_asal_tidak_kosong_atau_tujuan_tanpa_portal_dilewati():
    db = _db(asal_izin=True)
    hasil = run(mig.run(db, apply=True))
    assert hasil["dipindah"] == 0 and "tidak kosong" in hasil["pasangan"]["operator_cuting"]["alasan_lewat"]
    db = _db(tujuan_portal=())
    hasil = run(mig.run(db, apply=True))
    assert hasil["dipindah"] == 0 and "tidak punya portal" in hasil["pasangan"]["operator_cuting"]["alasan_lewat"]
