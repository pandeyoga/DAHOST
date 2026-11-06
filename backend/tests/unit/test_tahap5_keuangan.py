"""Tahap 5 — audit form Keuangan, Aset, Penjualan (2026-11-07).

1. Pilihan rekening di Nota Penjualan berlabel "nama · kode akun": `GET /api/sales/cash-accounts` ikut mengirim
   kode rekening & kode akun buku besar, hanya rekening aktif, urut kode.
2. Kontrak daftar tetap (kelas D) layar ↔ server — supaya pilihan di form tidak lagi berbeda dengan validasi server:
   · Akrual: jenis = routes.rahaza_accruals.ACCRUAL_TYPES (dulu layar "Pendapatan/Beban" yang tidak dibaca server),
     kiriman memakai `accrual_type`/`expense_account`/`accrued_account`;
   · Aset tetap: metode penyusutan layar ⊆ server dan memuat "none" (tanah);
   · Termin pelanggan layar ⊆ routes.sales_direct.TERMS_DAYS.
"""
import asyncio
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402
import routes.sales_direct as sd  # noqa: E402
import routes.rahaza_accruals as acc  # noqa: E402
import routes.rahaza_fixed_assets as fa  # noqa: E402

FE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "erp"


def run(c):
    return asyncio.run(c)


def _fe(rel: str) -> str:
    p = FE / rel
    if not p.exists():
        pytest.skip(f"berkas layar tidak ada di checkout ini: {rel}")
    return p.read_text(encoding="utf-8")


def _block(src: str, start: str) -> str:
    i = src.index(start)
    j = src.index("];", i)
    return src[i:j]


# ── 1. rekening kas untuk form Nota Penjualan ────────────────────────────────
def test_rekening_nota_penjualan_ikut_kode_akun_aktif_urut_kode(monkeypatch):
    db = FakeDB()
    db.rahaza_cash_accounts.docs += [
        {"id": "b", "code": "1-1201", "name": "Bank BCA", "type": "bank", "gl_account_code": "1-1201", "active": True},
        {"id": "k", "code": "1-1101", "name": "Kas Kecil", "type": "cash", "gl_account_code": "1-1101", "active": True},
        {"id": "x", "code": "1-1299", "name": "Bank lama", "type": "bank", "gl_account_code": "1-1299", "active": False},
    ]

    async def _auth(_req):
        return {"id": "u", "role": "accounting"}

    monkeypatch.setattr(sd, "get_db", lambda: db)
    monkeypatch.setattr(sd, "require_auth", _auth)
    rows = run(sd.cash_accounts(object()))
    assert [r["id"] for r in rows] == ["k", "b"]              # rekening nonaktif tidak ditawarkan, urut kode
    assert sd.CASH_ACCOUNT_FIELDS.get("gl_account_code") == 1  # label "nama · kode akun" di layar
    assert sd.CASH_ACCOUNT_FIELDS.get("code") == 1
    assert sd.CASH_ACCOUNT_FIELDS.get("_id") == 0


# ── 2. kontrak daftar tetap layar ↔ server ───────────────────────────────────
def test_jenis_akrual_layar_sama_dengan_server():
    src = _fe("AccrualsModule.jsx")
    vals = re.findall(r"value: '([a-z_]+)'", _block(src, "export const ACCRUAL_TYPES"))
    assert vals == acc.ACCRUAL_TYPES
    # kiriman simpan memakai nama kolom server (dulu `type` + `account_id` yang tidak dibaca server)
    payload = src[src.index("export function accrualPayload"):src.index("export default function AccrualsModule")]
    for key in ("accrual_type", "expense_account", "accrued_account", "period", "amount"):
        assert f"{key}:" in payload
    assert "account_id" not in payload and "type:" not in payload.replace("accrual_type:", "")
    # status layar = status server
    for st in acc.ACCRUAL_STATUSES:
        assert f"{st}:" in src
    # penyaring daftar memakai parameter server
    assert "params.set('accrual_type'" in src


def test_metode_penyusutan_layar_bagian_dari_server_dan_memuat_tidak_disusutkan():
    src = _fe("FixedAssetsModule.jsx")
    vals = re.findall(r"value: '([a-z_]+)'", _block(src, "const DEPR_METHODS"))
    assert set(vals) <= set(fa.DEPR_METHODS)
    assert "none" in vals and "straight_line" in vals
    cats = re.findall(r"'([a-z-]+)'", _block(src, "const CATEGORIES").split("=", 1)[1])
    assert cats == fa.ASSET_CATEGORIES


def test_termin_pelanggan_layar_bagian_dari_server():
    src = _fe("sales/SalesCustomersModule.jsx")
    vals = re.findall(r"v: '([a-z0-9_]+)'", _block(src, "export const TERMS"))
    assert vals and set(vals) <= set(sd.TERMS_DAYS)
