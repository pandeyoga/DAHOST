"""Kelola Akun toko (Portal Marketing) — simpan toko tidak boleh ditolak karena akun piutangnya sendiri.

Kasus 4 Nov 2026: mengubah toko TTK-03 gagal dengan pesan
"Akun Piutang Platform: '1-1303-TTK-03 — Piutang Channel — Tiktok Rayona' bukan akun piutang platform".
Akun itu subledger otomatis (anak 1-1303) yang dibuat tanpa flags `is_ar`, sementara form
mengirim ulang nilai tersimpan pada setiap simpan.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from routes import marketing_accounts as ma  # noqa: E402


class _Coll:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, q=None, proj=None, sort=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return dict(d)
        return None


class _DB:
    def __init__(self, coa):
        self.rahaza_coa_accounts = _Coll(coa)


COA = [
    {"code": "1-1303", "name": "Piutang Platform Online Shop", "type": "ASSET", "is_group": False,
     "active": True, "flags": {"is_ar": True}},
    {"code": "1-1303-TTK-03", "name": "Piutang Channel — Tiktok Rayona", "type": "ASSET",
     "parent_code": "1-1303", "is_group": False, "active": True,
     "flags": {"subledger": True, "subledger_entity_type": "channel", "subledger_parent": "1-1303"}},
    {"code": "1-1201", "name": "Bank BCA", "type": "ASSET", "is_group": False, "active": True,
     "flags": {"is_bank": True}},
    {"code": "1-1201-X", "name": "Sub bank", "type": "ASSET", "is_group": False, "active": True,
     "flags": {"subledger": True, "subledger_parent": "1-1201"}},
]


def run(coro):
    return asyncio.run(coro)


def test_subledger_piutang_toko_diterima():
    row = run(ma._validate_coa_role(_DB(COA), "coa_receivable_code", "1-1303-TTK-03"))
    assert row["code"] == "1-1303-TTK-03"


def test_akun_induk_piutang_tetap_diterima():
    assert run(ma._validate_coa_role(_DB(COA), "coa_receivable_code", "1-1303"))["code"] == "1-1303"


def test_subledger_dari_induk_yang_bukan_piutang_tetap_ditolak():
    with pytest.raises(HTTPException) as e:
        run(ma._validate_coa_role(_DB(COA), "coa_receivable_code", "1-1201-X"))
    assert "bukan akun piutang platform" in e.value.detail


def test_update_melewati_nilai_yang_tidak_berubah():
    src = open(ma.__file__, encoding="utf-8").read()
    upd = src[src.index("async def update_platform_account"):]
    upd = upd[:upd.index("@router.delete")]
    assert 'if (val or "").strip() == (account.get(fname) or "").strip():' in upd


def test_form_tidak_mengirim_kolom_piutang_warisan():
    p = os.path.join(os.path.dirname(ma.__file__), "..", "..", "frontend", "src", "components", "erp",
                     "AccountManagementModule.jsx")
    if not os.path.exists(p):
        pytest.skip("frontend tidak ada di lingkungan ini")
    src = open(p, encoding="utf-8").read()
    payload = src[src.index("const shared = {"):src.index("let res;")]
    assert "coa_receivable_code:" not in payload
