"""Keputusan owner 8 Nov 2026 (butir 6): waktu dari API selalu berzona.

Motor dibuka tanpa `tz_aware`, jadi datetime yang disimpan UTC kembali NAIF dan dulu dikirim tanpa zona
("2026-11-08T02:00:00") → layar di WIB menampilkan jam 7 jam lebih awal. Helper bersama `utils.waktu.mongo_utc`
menandai datetime naif dari Mongo sebagai UTC; STRING tidak pernah ditafsir ulang. Hermetik: Mongo palsu.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402

import routes.admin as adm  # noqa: E402
import routes.announcements as ann  # noqa: E402
import routes.dewi_system_config as cfg  # noqa: E402
from utils.waktu import mongo_utc  # noqa: E402

NAIF = datetime(2026, 11, 8, 2, 0, 0)            # 09.00 WIB, disimpan UTC, kembali naif dari Motor
WIB = timezone(timedelta(hours=7))


class _Req:
    def __init__(self, params=None):
        self.query_params = params or {}


async def _admin(_req):
    return {"id": "a", "name": "Admin", "role": "admin"}


def test_helper_hanya_datetime_naif():
    aware = datetime(2026, 11, 8, 2, 0, tzinfo=WIB)
    out = mongo_utc({"a": NAIF, "b": [NAIF, {"c": NAIF}], "s": "2026-11-08T02:00:00", "w": aware, "n": 5})
    assert out["a"].tzinfo is timezone.utc and out["a"].hour == 2
    assert out["b"][0].tzinfo is timezone.utc and out["b"][1]["c"].tzinfo is timezone.utc
    assert out["s"] == "2026-11-08T02:00:00"     # string tidak ditafsir ulang
    assert out["w"] is aware and out["n"] == 5
    assert ann._utc(NAIF).tzinfo is timezone.utc  # pengumuman memakai helper yang sama


def test_log_aktivitas_berzona(monkeypatch):
    db = FakeDB()
    db.activity_logs.docs = [{"id": "l1", "action": "create", "module": "po", "timestamp": NAIF, "details": "x"}]
    monkeypatch.setattr(adm, "require_auth", _admin)
    monkeypatch.setattr(adm, "get_db", lambda: db)
    out = asyncio.run(adm.get_activity_logs(_Req({"limit": "10"})))
    assert out[0]["timestamp"] == "2026-11-08T02:00:00+00:00"
    # dibaca di WIB = 09.00, bukan 02.00
    assert datetime.fromisoformat(out[0]["timestamp"]).astimezone(WIB).hour == 9


def test_pengguna_dan_audit_peran(monkeypatch):
    db = FakeDB()
    db.users.docs = [{"id": "u1", "email": "a@x", "password": "h", "created_at": NAIF, "last_login_at": NAIF}]
    db.rahaza_audit_logs.docs = [
        {"id": "r1", "entity_type": "role", "entity_id": "R", "timestamp": NAIF},
        {"id": "r2", "entity_type": "role", "entity_id": "R", "timestamp": "2026-11-08T02:00:00+00:00"},
        {"id": "r3", "entity_type": "role", "entity_id": "R", "timestamp": "2026-11-08T02:00:00"},
    ]
    monkeypatch.setattr(adm, "require_auth", _admin)
    monkeypatch.setattr(adm, "get_db", lambda: db)
    users = asyncio.run(adm.get_users(_Req()))
    assert users[0]["created_at"].endswith("+00:00") and users[0]["last_login_at"].endswith("+00:00")
    items = {r["id"]: r["timestamp"] for r in asyncio.run(adm.get_rbac_audit(_Req({"role_id": "R"})))["items"]}
    assert items == {"r1": "2026-11-08T02:00:00+00:00", "r2": "2026-11-08T02:00:00+00:00",
                     "r3": "2026-11-08T02:00:00"}   # string lama tanpa zona dibiarkan (makna tak bisa dipastikan)


def test_pengaturan_sistem(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cfg, "get_db", lambda: db)
    asyncio.run(cfg.ensure_defaults(db))
    for d in db.dewi_system_config.docs:          # seperti dibaca dari Motor: naif
        d["updated_at"] = NAIF
    rows = asyncio.run(cfg.list_configs(category=None, user={"role": "admin"}))
    assert rows and all(r["updated_at"].tzinfo is timezone.utc for r in rows)
    one = asyncio.run(cfg.get_config(rows[0]["key"], user={"role": "admin"}))
    assert one["updated_at"].tzinfo is timezone.utc
