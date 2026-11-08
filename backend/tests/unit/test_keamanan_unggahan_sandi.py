"""Keamanan 2026-11-07 — berkas unggahan sensitif & sandi teks biasa. Uji HERMETIK (Mongo & penyimpanan palsu).

1. `GET /api/uploads/{path}` (`routes/uploads_serve.py`) dulu melayani SEMUA berkas tanpa login, termasuk selfie
   absen, surat dokter cuti, foto profil, dan KTP/KK/BPJS karyawan. Kini berkas sensitif
   (`core/sensitive_files.py`) wajib token Bearer / `?auth=` (`auth.verify_download_token`); foto produk & logo
   tetap terbuka.
2. Impor vendor (`routes/operations_import.py`) dulu menyimpan `garments.vendor_password_plain`. Kini sandi awal
   hanya dikembalikan sekali di respons; migrasi `2026_11_07_hapus_sandi_teks.py` membersihkan data lama.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import importlib.util
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
import auth  # noqa: E402
import routes.operations_import as oi  # noqa: E402
import routes.uploads_serve as us  # noqa: E402
from core import sensitive_files as sf  # noqa: E402

USER = {"id": "u-uji", "name": "Staf Uji", "email": "uji@contoh.test", "role": "admin"}


def run(c):
    return asyncio.run(c)


def _session_token():
    return jwt.encode({**USER, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                      auth.JWT_SECRET, algorithm="HS256")


def _request(path, bearer=None):
    headers = [(b"authorization", f"Bearer {bearer}".encode())] if bearer else []
    return Request({"type": "http", "method": "GET", "path": f"/api/uploads/{path}",
                    "headers": headers, "query_string": b""})


@pytest.fixture
def env(monkeypatch):
    """Penyimpanan berkas palsu + Mongo palsu dipasang ke rute."""
    monkeypatch.setenv("ALLOW_SESSION_TOKEN_IN_QUERY", "1")
    files = {
        "attendance/emp-1/2026-11-07_in_ab12cd34.jpg": (b"SELFIE", "image/jpeg"),
        "leave_docs/surat-dokter.pdf": (b"SURAT", "application/pdf"),
        "profile/u-1/20261107_foto.jpg": (b"PROFIL", "image/jpeg"),
        "products/p-1/foto.jpg": (b"PRODUK", "image/jpeg"),
        "u-hr/20260914104107_KTP.pdf": (b"KTP", "application/pdf"),
        "u-hr/20260914104999_logo.png": (b"LOGO", "image/png"),
    }
    db = FakeDB()
    db.attachments.docs = [
        {"id": "a1", "storage_path": "u-hr/20260914104107_KTP.pdf", "entity_type": "employee",
         "entity_id": "emp-1", "is_deleted": False},
        {"id": "a2", "storage_path": "u-hr/20260914104999_logo.png", "entity_type": "company_logo",
         "entity_id": "general", "is_deleted": False},
    ]
    asked = []

    def _get_object(path):
        asked.append(path)
        return files.get(path)

    monkeypatch.setattr(us._objstore, "get_object", _get_object)
    monkeypatch.setattr(us, "get_db", lambda: db)
    return {"db": db, "files": files, "asked": asked}


def _serve(path, auth_q=None, bearer=None):
    return run(us.serve_upload(path, _request(path, bearer), auth=auth_q))


def _status(path, **kw):
    try:
        return _serve(path, **kw).status_code
    except HTTPException as e:
        return e.status_code


# ══════════════════════════════════════════════════════════════════════════════
# 1 · GET /api/uploads/{path}
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", ["attendance/emp-1/2026-11-07_in_ab12cd34.jpg", "leave_docs/surat-dokter.pdf",
                                  "profile/u-1/20261107_foto.jpg"])
def test_awalan_sensitif_tanpa_token_401(env, path):
    assert _status(path) == 401
    assert _status(path, auth_q="token-palsu") == 401
    assert env["asked"] == []          # berkas tidak dibaca sama sekali


@pytest.mark.parametrize("path", ["attendance/emp-1/2026-11-07_in_ab12cd34.jpg", "leave_docs/surat-dokter.pdf",
                                  "profile/u-1/20261107_foto.jpg"])
def test_awalan_sensitif_dengan_token_sah_200(env, path):
    r = _serve(path, auth_q=_session_token())
    assert r.status_code == 200 and r.body == env["files"][path][0]
    assert "no-store" in r.headers.get("cache-control", "")
    assert _serve(path, bearer=_session_token()).status_code == 200                  # header Bearer
    assert _serve(path, auth_q=auth.create_download_token(USER)).status_code == 200  # token unduh 5 menit


def test_berkas_publik_tanpa_token_200(env):
    r = _serve("products/p-1/foto.jpg")
    assert r.status_code == 200 and r.body == b"PRODUK"
    assert "cache-control" not in r.headers
    # lampiran terdaftar yang BUKAN HR (logo perusahaan) tetap terbuka
    assert _serve("u-hr/20260914104999_logo.png").status_code == 200
    # token kedaluwarsa/palsu tidak membuat berkas publik ditolak
    assert _serve("products/p-1/foto.jpg", auth_q="token-palsu").status_code == 200


def test_lampiran_karyawan_terdaftar_tanpa_token_401(env):
    assert _status("u-hr/20260914104107_KTP.pdf") == 401
    assert _serve("u-hr/20260914104107_KTP.pdf", auth_q=_session_token()).body == b"KTP"


def test_lampiran_karyawan_yang_dihapus_tetap_dijaga(env):
    env["db"].attachments.docs[0]["is_deleted"] = True
    assert _status("u-hr/20260914104107_KTP.pdf") == 401


def test_penulisan_path_lain_tidak_melewati_penjagaan(env):
    for p in ("./attendance/emp-1/2026-11-07_in_ab12cd34.jpg", "/leave_docs/surat-dokter.pdf",
              "profile/./u-1/20261107_foto.jpg", "attendance//emp-1/2026-11-07_in_ab12cd34.jpg"):
        assert _status(p) == 401, p
    assert _status("leave_docs/../products/p-1/foto.jpg") == 400
    assert _status("tidak/ada.jpg") == 404


def test_daftar_sensitif_satu_sumber():
    # Asisten AI (laporan), 7 Nov 2026: + "ai_reports/" (laporan PDF/Excel buatan Asisten AI).
    # Asisten AI Tahap E, 9 Nov 2026: + "ai_lampiran/" (lampiran percakapan) + "ai_berkas/" (berkas keluaran kode).
    assert set(sf.SENSITIVE_UPLOAD_PREFIXES) == {"attendance/", "leave_docs/", "profile/", "ai_reports/",
                                                 "ai_lampiran/", "ai_berkas/"}
    assert "employee" in sf.SENSITIVE_ATTACHMENT_TYPES
    # jenis lampiran non-HR yang dipakai layar tetap publik
    for t in ("company_logo", "rahaza_model", "rnd_style", "production_po", "buyer_shipment", "style"):
        assert not sf.is_sensitive_attachment_type(t)
    # awalan sama dengan path yang ditulis modul pengunggah
    src = {
        "attendance/": (BACKEND / "utils" / "attendance_policy.py").read_text(encoding="utf-8"),
        "leave_docs/": (BACKEND / "routes" / "rahaza_leave.py").read_text(encoding="utf-8"),
        "profile/": (BACKEND / "routes" / "dewi_portal_saya_hr.py").read_text(encoding="utf-8"),
        "ai_reports/": (BACKEND / "core" / "laporan_ai.py").read_text(encoding="utf-8"),
        "ai_lampiran/": (BACKEND / "core" / "asisten_ai" / "lampiran.py").read_text(encoding="utf-8"),
        "ai_berkas/": (BACKEND / "core" / "asisten_ai" / "berkas_kode.py").read_text(encoding="utf-8"),
    }
    for prefix, text in src.items():
        assert f'f"{prefix}' in text, prefix
    server = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert "app.include_router(uploads_serve_router)" in server
    assert "@app.get('/api/uploads/" not in server


def test_files_dan_uploads_memakai_pemeriksa_token_yang_sama():
    import inspect
    import routes.file_storage as fs
    assert "file_request_user(request, auth)" in inspect.getsource(fs.download_file)
    assert "file_request_user(request, auth)" in inspect.getsource(us.serve_upload)


# ── layar: semua tautan/gambar berkas sensitif memakai withFileAuth ───────────
FE = REPO / "frontend" / "src"


def _jsx(rel):
    p = FE / rel
    if not p.is_file():
        pytest.skip("frontend/src tidak tersedia")
    return re.sub(r"(?m)(^|\s)//.*$", r"\1", p.read_text(encoding="utf-8"))


def test_helper_withFileAuth_satu_tempat():
    src = _jsx("lib/fileUrl.js")
    assert "export function withFileAuth" in src
    assert "'/api/uploads/'" in src and "'/api/files/'" in src
    assert "localStorage.getItem('erp_token')" in src and "try" in src and "catch" in src


@pytest.mark.parametrize("rel,pattern", [
    ("components/erp/RahazaAttendanceApprovalModule.jsx", r"withFileAuth\(`\$\{BACKEND\}\$\{rec\.photo_selfie_url\}`\)"),
    ("components/erp/RahazaAttendanceApprovalModule.jsx", r"const src = withFileAuth\("),
    ("components/erp/HRApprovalInboxModule.jsx", r"src=\{withFileAuth\(`\$\{API\}\$\{u\}`\)\}"),
    ("components/erp/HRApprovalInboxModule.jsx", r"withFileAuth\(`\$\{API\}\$\{item\.meta\.attachment_url\}`\)"),
    ("components/erp/RahazaLeaveModule.jsx", r"withFileAuth\(`\$\{API\}\$\{selectedLeave\.attachment_url\}`\)"),
    ("components/erp/RahazaLeaveModule.jsx", r"withFileAuth\(`\$\{API\}\$\{approveModal\.attachment_url\}`\)"),
    ("components/erp/PortalSayaCuti.jsx", r"withFileAuth\(`\$\{API\}\$\{lv\.attachment_url\}`\)"),
    ("components/erp/PortalSayaProfile.jsx", r"withFileAuth\(previewUrl"),
    ("components/erp/HREmployeeModule.jsx", r"withFileAuth\(`\$\{API\}/api/files/\$\{d\.storage_path\}`\)"),
    ("components/erp/portal/MyDocumentsModule.jsx", r"window\.open\(withFileAuth\(doc\.file_url\)"),
])
def test_layar_mengirim_token_untuk_berkas_sensitif(rel, pattern):
    src = _jsx(rel)
    assert "from '@/lib/fileUrl'" in src
    assert re.search(pattern, src), pattern


def test_tidak_ada_tautan_lampiran_cuti_atau_selfie_tanpa_token():
    for rel in ("components/erp/HRApprovalInboxModule.jsx", "components/erp/RahazaLeaveModule.jsx",
                "components/erp/PortalSayaCuti.jsx", "components/erp/RahazaAttendanceApprovalModule.jsx"):
        src = _jsx(rel)
        bare = re.findall(r"(?:href|src)=\{`\$\{(?:API|BACKEND)\}\$\{[^}]*(?:attachment_url|selfie|value\.url|\bu\b)[^}]*\}`\}", src)
        assert not bare, (rel, bare)


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Sandi teks biasa
# ══════════════════════════════════════════════════════════════════════════════
def test_impor_vendor_tidak_menyimpan_sandi_teks(monkeypatch):
    db = FakeDB()

    async def _auth(_r):
        return USER

    async def _log(*_a, **_k):
        return None

    monkeypatch.setattr(oi, "get_db", lambda: db)
    monkeypatch.setattr(oi, "require_auth", _auth)
    monkeypatch.setattr(oi, "log_activity", _log)
    req = FakeRequest({"type": "garments", "data": [
        {"garment_code": "VND-01", "garment_name": "PT Garmen Uji", "phone": "0812"},
        {"garment_code": "VND-02", "garment_name": "CV Jahit", "vendor_password_plain": "bocor"},
    ]})
    out = run(oi.import_data(req))
    assert out["imported"] == 2 and out["errors"] == []
    # sandi awal dikembalikan SEKALI di respons (dibaca layar ImportExportPanel: garment_name/email/password)
    accs = out["vendor_accounts"]
    assert [a["email"] for a in accs] == ["vendor.vnd01@garment.com", "vendor.vnd02@garment.com"]
    assert all(a["password"] and a["garment_name"] for a in accs)
    # ... dan TIDAK tersimpan di mana pun dalam bentuk teks
    for g in db.garments.docs:
        assert not any("password" in k for k in g), g.keys()
    for u, a in zip(db.users.docs, accs):
        assert u["password"] != a["password"] and auth.verify_password(a["password"], u["password"])
    panel = _jsx("components/erp/engine/ImportExportPanel.jsx")
    assert "importResult.vendor_accounts" in panel and "acc.password" in panel and "acc.garment_name" in panel


def test_tidak_ada_kode_backend_yang_menulis_sandi_teks():
    rx = re.compile(r"['\"](\w*password_plain|plain_password)['\"]\s*:")
    hits = []
    for p in (BACKEND / "routes").rglob("*.py"):
        if rx.search(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append(str(p.relative_to(BACKEND)))
    for d in ("core", "utils", "services"):
        for p in (BACKEND / d).rglob("*.py"):
            if rx.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p.relative_to(BACKEND)))
    assert hits == []


def _migration():
    p = BACKEND / "scripts" / "migrations" / "2026_11_07_hapus_sandi_teks.py"
    spec = importlib.util.spec_from_file_location("hapus_sandi_teks", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_hapus_sandi_teks_pratinjau_tulis_idempoten(capsys):
    mig = _migration()
    db = FakeDB()
    db.garments.docs = [
        {"id": "g1", "garment_name": "A", "login_email": "vendor.a@garment.com", "vendor_password_plain": "rahasia1"},
        {"id": "g2", "garment_name": "B", "login_email": "vendor.b@garment.com"},
        {"id": "g3", "garment_name": "C", "vendor_password_plain": "rahasia3", "password_plain": "x"},
    ]
    db.buyers.docs = [{"id": "b1", "buyer_name": "Buyer", "buyer_password_plain": "rahasia2"}]
    db.users.docs = [{"id": "u1", "email": "vendor.a@garment.com", "password": "$2b$12$hash"}]

    pre = run(mig.run(db, apply=False))
    assert pre["garments"]["docs"] == 2 and pre["garments"]["fields"] == {"vendor_password_plain": 2, "password_plain": 1}
    assert pre["buyers"]["docs"] == 1 and pre["users"]["docs"] == 0 and pre["total"] == 3
    assert db.garments.docs[0]["vendor_password_plain"] == "rahasia1"        # pratinjau tidak menulis

    done = run(mig.run(db, apply=True))
    assert done["garments"]["cleaned"] == 2 and done["buyers"]["cleaned"] == 1
    for coll in (db.garments, db.buyers):
        for d in coll.docs:
            assert not any(f in d for f in mig.PLAINTEXT_FIELDS)
    assert db.garments.docs[0]["login_email"] == "vendor.a@garment.com"      # kolom lain utuh
    assert db.users.docs[0]["password"] == "$2b$12$hash"                     # hash login tidak disentuh

    again = run(mig.run(db, apply=True))
    assert again["total"] == 0 and again["garments"]["cleaned"] == 0
    printed = capsys.readouterr().out
    assert "rahasia" not in printed                                          # hanya hitungan yang dicetak
