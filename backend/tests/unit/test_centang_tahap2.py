"""Akses tahap 2 (owner 13 Nov 2026: "bisa semuanya, jangan setengah-setengah") — penjaga di kode yang tersisa ikut centang.

  1. Penjaga helper (contoh: aset SDM `dewi_assets._require_hr`, dulu kode peran saja) lolos bila aksi endpoint dicentang.
  2. Pemeriksaan di dalam endpoint (Kirim CMT: setujui permintaan) lolos bila dicentang.
  3. Kondisi gabungan tetap benar: lepas karantina boleh untuk Keuangan ATAU peran pembuang ATAU centang.
  4. Pengecualian sengaja tetap aturan kode: gaji per orang (Q8, `rahaza_payroll_shared._require_hr`).
  5. "Input atas nama CMT" = centang sendiri; uang muka perjalanan dibayar = Pembayaran & Pencairan (K25).
  6. Migrasi tahap 2 hanya menambah centang untuk peran yang dulu boleh (kode peran OVERRIDE_ROLES).
Hermetik: tanpa Mongo.
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from data.module_catalog import request_key  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Url:
    def __init__(self, path):
        self.path = path


class _Req:
    def __init__(self, method, path):
        self.method, self.url = method, _Url(path)
        self.headers, self.query_params = {}, {}

        class _S:
            pass
        self.state = _S()


@pytest.fixture
def masuk(monkeypatch):
    state = {}

    async def _auth(req):
        u = dict(state["user"])
        u["_aksi_request"] = request_key(req.method, req.url.path)
        return u

    def _pakai(mod, role, perms, method, path):
        import auth
        state["user"] = {"id": f"u-{role}", "role": role, "_permissions": list(perms), "_role_perms": list(perms)}
        monkeypatch.setattr(auth, "require_auth", _auth)
        if hasattr(mod, "require_auth"):
            monkeypatch.setattr(mod, "require_auth", _auth)
        return _Req(method, path)
    return _pakai


def test_1_helper_aset_sdm_ikut_centang(masuk):
    import routes.dewi_assets as da
    req = masuk(da, "Finance & Purchase", ["mod.hr_assets.create"], "POST", "/api/dewi/assets")
    assert run(da._require_hr(req))["role"] == "Finance & Purchase"
    req = masuk(da, "Finance & Purchase", ["mod.hr_assets.view"], "POST", "/api/dewi/assets")
    with pytest.raises(HTTPException) as e:
        run(da._require_hr(req))
    assert e.value.status_code == 403


def test_2_kirim_cmt_setujui_permintaan_ikut_centang():
    import routes.kirim_cmt_routes as k
    src = inspect.getsource(k.kirim_request_approve)
    assert "lolos_centang(user)" in src                       # pemeriksaan kode peran ikut menerima centang
    assert request_key("POST", "/api/kirim-cmt/requests/acc/r1/approve") == "mod.prod_vendor_shipment.approve"
    assert request_key("GET", "/api/kirim-cmt/nota-aksesoris-berlaku") == "mod.acc_requests.view"
    assert request_key("POST", "/api/kirim-cmt/nota-aksesoris/n1/potong") == "mod.prod_cmt_billing.approve"
    assert request_key("PUT", "/api/kirim-cmt/po/p1/accessory-plan") == "mod.prod_po.edit"


def test_3_kondisi_gabungan_lepas_karantina_tetap_benar():
    import routes.wms_quarantine as wq
    src = inspect.getsource(wq.release_item)
    assert ("if not check_role(user, DISPOSE_ROLES) and not pr.is_finance(user) and not lolos_centang(user):"
            in src)


def test_4_gaji_per_orang_tetap_aturan_kode(masuk):
    import routes.rahaza_payroll_shared as ps
    assert "lolos_centang" not in inspect.getsource(ps._require_hr)          # Q8: tidak dibuka centang Lihat
    req = masuk(ps, "Finance & Purchase", ["mod.hr_payroll.view"], "GET", "/api/rahaza/payroll-runs/r1/slips")
    with pytest.raises(HTTPException):
        run(ps._require_hr(req))
    from routes.shared import require_portal
    assert "lolos_centang" not in inspect.getsource(require_portal)


def test_5_input_atas_nama_cmt_dan_uang_muka_perjalanan():
    from core.cmt_override import is_override_role
    assert is_override_role({"role": "Koordinator Packing", "_permissions": ["mod.prod_cmt_override.create"]})
    assert not is_override_role({"role": "admin_produksi", "_permissions": []})        # kode peran tidak cukup lagi
    assert is_override_role({"role": "owner", "_permissions": []})
    assert request_key("POST", "/api/cmt-override/x") == "mod.prod_cmt_override.create"
    assert request_key("POST", "/api/hr/expenses/travel/t1/advance-paid") == "mod.fin_pencairan.approve"


def _migrasi():
    path = BACKEND / "scripts" / "migrations" / "2026_11_14_centang_tahap2.py"
    spec = importlib.util.spec_from_file_location("centang_tahap2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_6_migrasi_tahap2_hanya_untuk_yang_dulu_boleh():
    m = _migrasi()
    assert set(m.usulan("admin_produksi", [])) == set(m.OVERRIDE_KEYS)
    assert m.usulan("admin_produksi", list(m.OVERRIDE_KEYS)) == []          # idempoten
    assert m.usulan("Koordinator Packing", ["mod.prod_vendor_cmt.create"]) == []
