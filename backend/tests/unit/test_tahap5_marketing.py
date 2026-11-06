"""Tahap 5 (audit form) — portal Toko/Marketing, Administrasi Sistem, Manajemen.

Yang dijaga (temuan uji layar 7 Nov 2026):
  1. Pemilih produk (FG/katalog) membawa WARNA & UKURAN dari master, dan pencarian FG tidak 500
     pada teks berkarakter regex serta ikut mencari warna/ukuran.
  2. Tambah User dengan sandi dikosongkan → sandi bawaan User@123, bukan sandi KOSONG.
  3. Setelan sistem berkode tetap (termin maklon, penyedia WA) menolak nilai di luar pilihan.
  4. Ubah-status cepat Kalender Konten tidak boleh melewati aturan "Tayang wajib link terbit".
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

ADMIN = {"id": "u-sa", "name": "Super", "role": "superadmin", "email": "sa@x.test"}


def _patch(monkeypatch, mod, db, user=ADMIN):
    async def _auth(_req):
        return user
    if hasattr(mod, "require_auth"):
        monkeypatch.setattr(mod, "require_auth", _auth)
    monkeypatch.setattr(mod, "get_db", lambda: db)


# ── 1. identitas varian di pemilih produk ────────────────────────────────────
def test_variant_identity_fields_from_fg_master():
    from routes.marketing_catalog_items import variant_identity_fields
    row = {"sku": "DA-2101-MHG-ALLSIZE", "fg_color": "MAHOGANY"}
    fg = {"color": "Mahogany (master)", "size_code": "ALLSIZE"}
    out = variant_identity_fields(row, fg)
    assert out == {"fg_color": "MAHOGANY", "fg_size": "ALLSIZE"}
    # item lama tanpa fg_color → warna dari master; tanpa tautan → kosong, bukan None
    assert variant_identity_fields({}, {"color": "HITAM", "size_code": "XL"}) == {"fg_color": "HITAM", "fg_size": "XL"}
    assert variant_identity_fields({}, None) == {"fg_color": "", "fg_size": ""}


def _fg_db():
    db = FakeDB()
    db.rahaza_materials.docs = [
        {"id": "f1", "type": "fg", "active": True, "code": "DA-2101-HTM-M", "name": "Aisar", "color": "HITAM", "size_code": "M"},
        {"id": "f2", "type": "fg", "active": True, "code": "DA-2101-MHG-L", "name": "Aisar", "color": "MAHOGANY", "size_code": "L"},
        {"id": "f3", "type": "fg", "active": True, "code": "DA-2103-HTM-XL", "name": "Anna", "color": "HITAM", "size_code": "XL"},
        {"id": "f4", "type": "fg", "active": False, "code": "DA-2101-HTM-S", "name": "Aisar", "color": "HITAM", "size_code": "S"},
    ]
    return db


def _fg_search(monkeypatch, q):
    # modul membuat folder unggahan /app/uploads saat di-impor — di CI (read-only) dilewati
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: None)
    import routes.marketing_catalog_mgmt as mgmt
    db = _fg_db()
    _patch(monkeypatch, mgmt, db)
    return asyncio.run(mgmt.search_fg_products(FakeRequest(), q=q, limit=50))


def test_fg_products_search_matches_colour_and_size_words(monkeypatch):
    ids = [d["id"] for d in _fg_search(monkeypatch, "aisar hitam")["data"]]
    assert ids == ["f1"]                      # nama + warna; FG nonaktif tidak ikut
    ids = [d["id"] for d in _fg_search(monkeypatch, "hitam xl")["data"]]
    assert ids == ["f3"]                      # warna + ukuran
    row = _fg_search(monkeypatch, "DA-2101-MHG")["data"][0]
    assert row["size_code"] == "L" and row["color"] == "MAHOGANY"


def test_fg_products_search_escapes_regex_characters(monkeypatch):
    # dulu: re.error "missing ), unterminated subpattern" → 500
    assert _fg_search(monkeypatch, "Aisar (")["data"] == []
    assert _fg_search(monkeypatch, "+")["data"] == []


# ── 2. sandi akun baru ───────────────────────────────────────────────────────
def test_default_password_never_empty():
    from routes.admin import default_password, DEFAULT_USER_PASSWORD
    assert default_password("") == DEFAULT_USER_PASSWORD
    assert default_password("   ") == DEFAULT_USER_PASSWORD
    assert default_password(None) == DEFAULT_USER_PASSWORD
    assert default_password("Rahasia#1") == "Rahasia#1"


def test_create_user_with_blank_password_gets_default(monkeypatch):
    import routes.admin as admin
    from auth import verify_password
    db = FakeDB()
    db.roles.docs = [{"id": "r-pic", "name": "pic_toko"}]
    _patch(monkeypatch, admin, db)
    monkeypatch.setattr(admin, "bump_rbac_cache", lambda: None)
    body = {"name": "Uji", "email": "Uji@X.test", "password": "", "role": "pic_toko", "status": "active"}
    resp = asyncio.run(admin.create_user(FakeRequest(body)))
    assert resp.status_code == 201
    saved = db.users.docs[0]
    assert saved["email"] == "uji@x.test" and saved["role_id"] == "r-pic"
    assert not verify_password("", saved["password"])          # dulu: True (masuk tanpa sandi)
    assert verify_password(admin.DEFAULT_USER_PASSWORD, saved["password"])


# ── 3. setelan sistem berpilihan ─────────────────────────────────────────────
def test_config_choices_match_code_that_reads_them():
    from routes.dewi_system_config import CONFIG_CHOICES, DEFAULT_CONFIGS, choice_error
    from core.maklon_ledger import TERM_DAYS
    terms = {c["value"] for c in CONFIG_CHOICES["maklon_payment_terms_default"]}
    assert terms == set(TERM_DAYS)
    defaults = {c["key"]: c["value"] for c in DEFAULT_CONFIGS}
    for key, choices in CONFIG_CHOICES.items():
        assert defaults[key] in {c["value"] for c in choices}, key   # nilai bawaan harus sah
    assert choice_error("maklon_payment_terms_default", "net_30") is None
    assert "30 hari" in (choice_error("maklon_payment_terms_default", "30 hari") or "")
    assert choice_error("hpp_profit_margin_pct", 25) is None        # setelan tanpa pilihan bebas


def _cfg_db():
    db = FakeDB()
    db.dewi_system_config.docs = [
        {"key": "maklon_payment_terms_default", "value": "net_30", "data_type": "string",
         "label": "Payment Terms Default", "category": "maklon"},
        {"key": "notification_whatsapp_provider", "value": "twilio", "data_type": "string",
         "label": "WhatsApp Provider", "category": "notification"},
    ]
    return db


def test_config_update_rejects_value_outside_choices(monkeypatch):
    import routes.dewi_system_config as cfg
    db = _cfg_db()
    _patch(monkeypatch, cfg, db)
    with pytest.raises(HTTPException) as e:
        asyncio.run(cfg.update_config("maklon_payment_terms_default", cfg.ConfigUpdate(value="30 hari"), user=ADMIN))
    assert e.value.status_code == 400
    asyncio.run(cfg.update_config("maklon_payment_terms_default", cfg.ConfigUpdate(value="net_14"), user=ADMIN))
    assert db.dewi_system_config.docs[0]["value"] == "net_14"

    out = asyncio.run(cfg.bulk_update(cfg.BulkUpdateIn(**{"maklon_payment_terms_default": "60 hari",
                                                           "notification_whatsapp_provider": "fonnte"}), user=ADMIN))
    assert out["updated"] == 1 and len(out["errors"]) == 1          # termin ditolak; setelan tanpa pilihan bebas
    assert db.dewi_system_config.docs[0]["value"] == "net_14"
    assert db.dewi_system_config.docs[1]["value"] == "fonnte"


def test_config_list_sends_choices_and_readable_description(monkeypatch):
    import routes.dewi_system_config as cfg
    db = _cfg_db()
    db.dewi_system_config.docs[0]["description"] = "Termin pembayaran default: net_7 | net_14 | net_30 | net_60"
    _patch(monkeypatch, cfg, db)

    async def _no_defaults(_db):
        return 0
    monkeypatch.setattr(cfg, "ensure_defaults", _no_defaults)
    rows = {r["key"]: r for r in asyncio.run(cfg.list_configs(category=None, user=ADMIN))}
    term = rows["maklon_payment_terms_default"]
    assert [c["value"] for c in term["choices"]] == ["net_7", "net_14", "net_30", "net_60"]
    assert "net_7" not in term["description"]


# ── 4. Kalender Konten: Tayang wajib link terbit di SEMUA pintu ───────────────
def test_content_quick_status_posted_requires_published_url(monkeypatch):
    import routes.marketing_content_calendar_routes as cc
    db = FakeDB()
    db.marketing_content_calendar.docs = [
        {"id": "c1", "title": "Konten", "status": "scheduled", "published_url": ""},
        {"id": "c2", "title": "Konten", "status": "scheduled", "published_url": "https://vt.tiktok.com/abc"},
    ]
    _patch(monkeypatch, cc, db)
    with pytest.raises(HTTPException) as e:
        asyncio.run(cc.update_status("c1", FakeRequest({"status": "posted"})))
    assert e.value.status_code == 400 and "link terbit" in e.value.detail
    assert db.marketing_content_calendar.docs[0]["status"] == "scheduled"
    asyncio.run(cc.update_status("c2", FakeRequest({"status": "posted"})))
    assert db.marketing_content_calendar.docs[1]["status"] == "posted"
    asyncio.run(cc.update_status("c1", FakeRequest({"status": "cancelled"})))   # status lain tetap bebas
    assert db.marketing_content_calendar.docs[0]["status"] == "cancelled"
