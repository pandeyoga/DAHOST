"""Keputusan owner 8 Nov 2026: "Line Produksi" bukan syarat setup lagi (produksi lewat vendor CMT)."""
import asyncio
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
import routes.rahaza_next_actions as na  # noqa: E402


def _db_lengkap_tanpa_line():
    db = FakeDB()
    db.rahaza_locations.docs = [{"id": "l1", "active": True}]
    db.rahaza_processes.docs = [{"id": "p1"}]
    db.rahaza_employees.docs = [{"id": "e1", "active": True}]
    db.rahaza_models.docs = [{"id": "m1", "active": True}]
    db.rahaza_sizes.docs = [{"id": "s1", "active": True}]
    return db


def test_tanpa_line_tidak_ada_peringatan_setup():
    assert asyncio.run(na.rule_setup_empty(_db_lengkap_tanpa_line(), "management")) is None


def test_data_lain_kosong_tetap_diperingatkan_tanpa_menyebut_line():
    db = _db_lengkap_tanpa_line()
    db.rahaza_employees.docs = []
    kartu = asyncio.run(na.rule_setup_empty(db, "management"))
    assert kartu and kartu["id"] == "setup-empty"
    assert kartu["cta_params"]["missing"] == ["Karyawan"]
    assert "Line" not in kartu["description"]


def test_status_setup_line_opsional():
    src = (ROOT / "routes" / "rahaza_setup.py").read_text(encoding="utf-8")
    assert '"key": "lines", "label": "Line Produksi", "done": lines > 0, "count": lines, "required": False' in src
    assert "lines > 0 and emps" not in src
