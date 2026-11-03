"""Skrip penyiapan DEMO (scripts/demo_prepare.py) tidak boleh pernah jalan di database produksi (2026-11-03)."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "demo_prepare.py"


def _load(monkeypatch, db_name):
    monkeypatch.setenv("DB_NAME", db_name)
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:1")
    monkeypatch.setattr(sys, "argv", ["demo_prepare.py", "--terapkan"])
    spec = importlib.util.spec_from_file_location("demo_prepare_uji", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("db_name", ["dahost_erp", "", "produksi"])
def test_menolak_database_bukan_demo(monkeypatch, db_name):
    mod = _load(monkeypatch, db_name)
    with pytest.raises(SystemExit) as e:
        mod.main()
    assert "DITOLAK" in str(e.value)


def test_kunci_rahasia_nama_persis_bukan_pola():
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"$in": list(SECRET_KEYS)' in src and "$regex\": \"|\".join(SECRET_KEYS)" not in src
    assert os.path.basename(SCRIPT) == "demo_prepare.py"
