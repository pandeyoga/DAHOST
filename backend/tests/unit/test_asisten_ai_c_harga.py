"""Uji agen HARGA Asisten AI Tahap C (8 Nov 2026) — alat tindakan risiko MENENGAH + dua alat baca.

``ctx.api`` tiruan mencatat setiap panggilan lalu meneruskannya ke fungsi route ASLI di atas Mongo palsu, jadi
penjaga izin, lingkup toko, CV, kunci PO, kunci periode, dan riwayat harga endpoint ikut teruji:

1. ``ubah_harga_jual`` + ``riwayat_harga`` (katalog toko, margin vs HPP, riwayat harga di Jejak Perubahan);
2. ``atur_promo`` + ``daftar_promo`` (kampanye diskon: buat / ubah / akhiri);
3. ``ubah_tenggat_po_produksi`` dan ``buat_draf_po_produksi`` (PO produksi; tidak pernah konfirmasi);
4. ``ubah_titik_pesan_ulang`` (ambang stok; jumlah stok tidak pernah disentuh);
5. ``tutup_buka_bulan_marketing`` (kunci periode Siklus Marketing);
6. registri, skema, Gabungan ditolak, tidak ada jalur terlarang.
Hermetik: tanpa jaringan, tanpa API Anthropic.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402
from _fake_mongo import FakeCollection, FakeCursor, FakeDB  # noqa: E402

from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai.alat import tindakan_menengah as TM  # noqa: E402
from core.asisten_ai.alat_base import AlatError  # noqa: E402


def run(coro):
    return asyncio.run(coro)


HARI = date(2026, 11, 8)
OWNER = {"id": "u-owner", "role": "owner", "name": "Pemilik Uji", "email": "owner@uji"}
MGR = {"id": "u-mgr", "role": "manager_marketing", "name": "Manajer Uji", "email": "mgr@uji", "_role_perms": [], "_permissions": ["mod.mkt_targets.edit", "mod.mkt_targets.approve", "mod.mkt_accounts.edit"]}
SPV = {"id": "u-spv", "role": "spv_marketing", "name": "SPV Uji", "email": "spv@uji", "_role_perms": [], "_permissions": ["mod.mkt_targets.edit", "mod.mkt_targets.approve", "mod.mkt_accounts.edit"]}
STAF = {"id": "u-staf", "role": "staff_marketing", "name": "Staf Uji", "email": "staf@uji", "_role_perms": []}
CS = {"id": "u-cs", "role": "cs_staff", "name": "CS Uji", "email": "cs@uji", "_role_perms": []}
PROD = {"id": "u-prod", "role": "admin_produksi", "name": "Produksi Uji", "email": "prod@uji", "_role_perms": [],
        "_permissions": []}
GUDANG = {"id": "u-gdg", "role": "admin_gudang", "name": "Gudang Uji", "email": "gdg@uji", "_role_perms": [],
          "_permissions": []}
ALASAN = "uji agen harga: sesuai rapat"


# ══════════════════════════════════════════════════════════════════════════════
# Mongo palsu yang sedikit lebih lengkap (upsert, $push $each, distinct, aggregate kosong, regex terkompilasi)
# ══════════════════════════════════════════════════════════════════════════════
def _norm(q):
    if isinstance(q, re.Pattern):
        return {"$regex": q.pattern, "$options": "i" if q.flags & re.IGNORECASE else ""}
    if isinstance(q, dict):
        return {k: _norm(v) for k, v in q.items()}
    if isinstance(q, list):
        return [_norm(v) for v in q]
    return q


class Coll(FakeCollection):
    def find(self, q=None, projection=None):
        return super().find(_norm(q), projection)

    async def find_one(self, q=None, projection=None, **kw):
        return await super().find_one(_norm(q), projection, **kw)

    async def count_documents(self, q=None):
        return await super().count_documents(_norm(q))

    async def update_one(self, q, upd, upsert=False):
        upd = copy.deepcopy(upd)
        push = upd.pop("$push", None) or {}
        hit = next((d for d in self.docs if fm.match(d, q)), None)
        if hit is None and upsert:
            hit = {k: v for k, v in q.items() if not str(k).startswith("$") and not isinstance(v, dict)}
            hit.update(copy.deepcopy(upd.get("$setOnInsert") or {}))
            self.docs.append(hit)
        if hit is None:
            return fm._Result()
        r = await super().update_one(q, {k: v for k, v in upd.items() if k != "$setOnInsert"})
        for k, v in push.items():
            cur = list(hit.get(k) or [])
            cur += copy.deepcopy(v["$each"]) if isinstance(v, dict) and "$each" in v else [copy.deepcopy(v)]
            if isinstance(v, dict) and v.get("$slice"):
                cur = cur[v["$slice"]:] if v["$slice"] < 0 else cur[:v["$slice"]]
            hit[k] = cur
        return r if r.matched_count else fm._Result(matched=1, modified=1)

    async def distinct(self, field, q=None):
        return list(dict.fromkeys(d.get(field) for d in self.docs if fm.match(d, _norm(q or {}))))

    def aggregate(self, pipeline):
        return FakeCursor([])


class DB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = Coll(name)
        return self._cols[name]


def _akun(aid, nama, platform="shopee", **kw):
    return {"id": aid, "account_name": nama, "account_code": aid, "platform": platform, "status": "active", **kw}


def _rekap(aid, tanggal, omzet):
    return {"id": f"sd-{aid}-{tanggal}", "account_id": aid, "date": tanggal, "revenue_type": "total",
            "metrics": {"revenue": omzet, "revenue_product": omzet, "orders": 5, "units": 5, "buyers": 5},
            "fulfillment": {}, "revenue_basis": "produk_setelah_diskon", "updated_at": "2026-11-01T00:00:00"}


def _db():
    db = DB()
    db.marketing_platform_accounts.docs += [
        _akun("A1", "Shopee Uji Satu", pic_user_id="u-staf"),
        _akun("A2", "TikTok Uji Dua", "tiktok"),
        _akun("A3", "Shopee Sukma Uji", entity="SMU"),
    ]
    for aid in ("A1", "A2", "A3"):
        for d in range(1, 6):
            db.marketing_sales_data.docs.append(_rekap(aid, f"2026-11-{d:02d}", 1_000_000.0))
    db.users.docs += [dict(u, status="active") for u in (OWNER, MGR, SPV, STAF, PROD)]
    # katalog
    db.marketing_catalogs.docs += [{"id": "C1", "account_id": "A1", "account_name": "Shopee Uji Satu",
                                    "name": "Katalog Uji Satu"},
                                   {"id": "C2", "account_id": "A2", "account_name": "TikTok Uji Dua",
                                    "name": "Katalog Uji Dua"},
                                   {"id": "C3", "account_id": "A3", "account_name": "Shopee Sukma Uji",
                                    "name": "Katalog Sukma Uji"}]
    db.marketing_catalog_items.docs += [
        {"id": "I1", "catalog_id": "C1", "account_id": "A1", "sku": "SKU-UJI-1", "name": "Gamis Uji",
         "harga_jual": 100000.0, "price": 100000.0, "harga_coret": 130000.0, "original_price": 130000.0,
         "hpp": 55000.0, "fg_material_id": "FG1", "stock_quantity": 0, "is_active": True,
         "retail_price_master": 100000.0},
        {"id": "I2", "catalog_id": "C2", "account_id": "A2", "sku": "SKU-UJI-1", "name": "Gamis Uji",
         "harga_jual": 105000.0, "price": 105000.0, "hpp": 60000.0, "stock_quantity": 0, "is_active": True},
        {"id": "I3", "catalog_id": "C1", "account_id": "A1", "sku": "SKU-UJI-2", "name": "Kerudung Uji",
         "harga_jual": 50000.0, "price": 50000.0, "stock_quantity": 0, "is_active": False},
        {"id": "I4", "catalog_id": "C3", "account_id": "A3", "sku": "SKU-UJI-1", "name": "Gamis Uji",
         "harga_jual": 99000.0, "price": 99000.0, "hpp": 60000.0, "stock_quantity": 0},
    ]
    db.rahaza_materials.docs += [
        {"id": "FG1", "code": "FG-UJI-1", "name": "Gamis Uji FG", "type": "fg", "unit": "pcs", "hpp": 62000.0,
         "hpp_source": "bom", "active": True},
        {"id": "M-ACC1", "code": "ACC-UJI-1", "name": "Kancing Uji", "type": "accessory", "unit": "pcs",
         "min_stock": 50, "active": True},
        {"id": "M-KAIN1", "code": "KAIN-UJI-1", "name": "Kain Uji", "type": "fabric", "unit": "m",
         "min_stock_qty": 20, "reorder_point": 40, "active": True},
    ]
    db.rahaza_material_stock.docs += [{"material_id": "M-ACC1", "qty": 30}, {"material_id": "M-KAIN1", "qty": 45},
                                      {"material_id": "FG1", "qty": 12}]
    # produksi
    db.rahaza_models.docs = [{"id": "M1", "code": "GMS", "name": "Gamis Model", "active": True}]
    db.rahaza_sizes.docs = [{"id": "S-M", "code": "M", "active": True}, {"id": "S-L", "code": "L", "active": True}]
    db.rahaza_model_variants.docs = [
        {"id": "V1", "model_id": "M1", "size_id": "S-M", "size_code": "M", "color_name": "Hitam", "color_code": "HTM",
         "sku": "GMS-HTM-M", "active": True, "product_status": "best_seller"},
        {"id": "V2", "model_id": "M1", "size_id": "S-L", "size_code": "L", "color_name": "Hitam", "color_code": "HTM",
         "sku": "GMS-HTM-L", "active": True, "product_status": "stop"}]
    t = lambda d: datetime(2026, 11, d)  # noqa: E731
    db.production_pos.docs += [
        {"id": "P1", "po_number": "PO-INT-UJI-0001", "business_type": "internal", "status": "Confirmed",
         "deadline": t(20), "delivery_deadline": t(25), "customer_name": "Gudang FG Sendiri", "notes": "lama",
         "created_at": t(1), "updated_at": t(1)},
        {"id": "P2", "po_number": "PO-MKL-UJI-0001", "business_type": "maklon", "status": "Confirmed",
         "deadline": t(22), "created_at": t(1)},
        {"id": "P3", "po_number": "PO-MKL-UJI-0002", "business_type": "maklon", "status": "Draft",
         "deadline": None, "created_at": t(2)},
        {"id": "P4", "po_number": "PO-INT-UJI-0004", "business_type": "internal", "status": "Closed",
         "deadline": t(5), "created_at": t(1)},
    ]
    db.po_items.docs += [{"id": "pi1", "po_id": "P1", "po_number": "PO-INT-UJI-0001", "sku": "GMS-HTM-M", "qty": 100,
                          "model_id": "M1", "size_id": "S-M"}]
    # promo
    db.marketing_discounts.docs += [
        {"id": "D1", "account_id": "A1", "account_name": "Shopee Uji Satu", "platform": "shopee",
         "name": "Flash sale uji aktif", "discount_type": "flash_sale", "discount_value": 20, "discount_unit": "persen",
         "min_purchase": 0, "max_discount": 0, "start_date": "2026-11-05", "end_date": "2026-11-15",
         "description": "", "product_scope": "semua_produk", "status": "active"},
        {"id": "D2", "account_id": "A1", "account_name": "Shopee Uji Satu", "platform": "shopee",
         "name": "Voucher uji nanti", "discount_type": "voucher", "discount_value": 15000, "discount_unit": "nominal",
         "start_date": "2026-11-20", "end_date": "2026-11-22", "status": "upcoming"},
        {"id": "D3", "account_id": "A2", "account_name": "TikTok Uji Dua", "platform": "tiktok",
         "name": "Cashback uji lalu", "discount_type": "cashback", "discount_value": 10, "discount_unit": "persen",
         "start_date": "2026-10-01", "end_date": "2026-10-10", "status": "expired"},
        {"id": "D4", "account_id": "A3", "account_name": "Shopee Sukma Uji", "platform": "shopee",
         "name": "Promo Sukma uji", "discount_type": "diskon_persen", "discount_value": 5, "discount_unit": "persen",
         "start_date": "2026-11-01", "end_date": "2026-11-30"},
        {"id": "D5", "account_id": "A1", "account_name": "Shopee Uji Satu", "platform": "shopee",
         "name": "Contoh bawaan", "discount_type": "voucher", "discount_value": 5, "discount_unit": "persen",
         "start_date": "2026-11-01", "end_date": "2026-11-30", "_seed_origin": True},
    ]
    return db


class Req:
    """Request tiruan: state.user, headers (X-CV), query_params, json()."""

    def __init__(self, user, body=None, cv=None, params=None):
        class _S:
            pass
        self.state = _S()
        self.state.user = user
        self.headers = {"x-cv": cv} if cv else {}
        self.query_params = dict(params or {})
        self._body = body or {}

    async def json(self):
        return copy.deepcopy(self._body)


def _import_catalog_mgmt():
    """Modul katalog membuat folder unggahan /app saat diimpor (tidak bisa di CI/pengguna tanpa hak) — pola uji lain."""
    import pathlib
    orig = pathlib.Path.mkdir

    def _mkdir(self, *a, **k):
        try:
            return orig(self, *a, **k)
        except OSError:
            return None
    pathlib.Path.mkdir = _mkdir
    try:
        import routes.marketing_catalog_mgmt as cm
    finally:
        pathlib.Path.mkdir = orig
    return cm


@pytest.fixture
def env(monkeypatch):
    import auth
    import cascade_delete
    import core.doc_number_policy as dnp
    import middleware.module_permission_gate as mpg
    import routes.production_internal_adapter as pia
    from core import authz
    from routes import doc_numbering as dn
    from routes import marketing_accounts as acc
    from routes import marketing_analitik as ma
    from routes import marketing_budget as mb
    from routes import marketing_catalog_items as mci
    cm = _import_catalog_mgmt()
    from routes import marketing_catalog_search as mcs
    from routes import marketing_change_log as cl
    from routes import marketing_discounts_routes as dis
    from routes import production_pos as pp
    from routes import rahaza_inventory_shared as ris
    from routes import rahaza_inventory_thresholds as thr
    from routes import rahaza_variants as rv
    db = _db()
    mods = (acc, ma, mb, mci, cm, mcs, cl, dis, pp, dn, rv, thr, ris, cascade_delete)
    for m in mods:
        if hasattr(m, "get_db"):
            monkeypatch.setattr(m, "get_db", lambda: db)

    async def _diam(*a, **k):
        return None
    for m in (pp, thr, mci):
        if hasattr(m, "log_activity"):
            monkeypatch.setattr(m, "log_activity", _diam)
    monkeypatch.setattr(mci, "_refresh_catalog_stats", _diam)
    monkeypatch.setattr("utils.waktu.today_wib", lambda: HARI)
    monkeypatch.setattr(ma, "today_wib", lambda: HARI)
    monkeypatch.setattr(dis, "today_wib", lambda: HARI)
    nomor = {"n": 0}

    async def _nomor(_db, key, *, ctx=None, requested=""):
        if requested:
            return requested
        nomor["n"] += 1
        return f"PO-INT-UJI-{100 + nomor['n']}"
    monkeypatch.setattr(dnp, "issue_number", _nomor)

    async def _bom(*a, **k):
        return {"created": 2}
    monkeypatch.setattr(pia, "explode_po_accessories_from_bom", _bom)

    async def _gerbang(*a, **k):
        return None
    monkeypatch.setattr(mpg, "evaluate", _gerbang)
    peran = {"u": MGR}
    monkeypatch.setattr(authz, "_role_of", lambda request: (peran["u"].get("role") or "").lower())

    def pakai(user):
        peran["u"] = user

        async def _f(request=None, *a, **k):
            if request is not None and getattr(request, "state", None) is not None:
                request.state.user = user
            return user
        for m in mods + (auth,):
            if hasattr(m, "require_auth"):
                monkeypatch.setattr(m, "require_auth", _f)
    pakai(MGR)
    return {"db": db, "pakai": pakai, "acc": acc, "ma": ma, "mb": mb, "mci": mci, "cm": cm, "mcs": mcs, "cl": cl,
            "dis": dis, "pp": pp, "dn": dn, "rv": rv, "thr": thr, "authz": authz}


class Ctx:
    """ctx.api tiruan: mencatat panggilan, meneruskan ke fungsi route ASLI. `gagal` = {(metode, awalan path): ke-n}."""

    def __init__(self, env, user=MGR, cv="DA", today=HARI, tindakan_id="tdk-uji-c1", gagal=None):
        self.env, self.user, self.cv, self.today, self.tindakan_id = env, user, cv, today, tindakan_id
        self.calls = []
        self.gagal = dict(gagal or {})
        env["pakai"](user)

    @property
    def tulis(self):
        return [c for c in self.calls if c["method"] != "GET"]

    async def api(self, method, path, params=None, json=None, headers=None):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        self.calls.append({"method": method, "path": path, "params": dict(params), "json": copy.deepcopy(json),
                           "headers": dict(headers or {})})
        for (m, awal), n in list(self.gagal.items()):
            if m == method and path.startswith(awal):
                self.gagal[(m, awal)] = n - 1
                if n - 1 == 0:
                    raise AlatError(500, "Sistem sedang bermasalah (uji).")
        r = Req(self.user, json, cv=self.cv, params=params)
        try:
            out = await self._rute(method, path, params, json, r)
        except HTTPException as x:
            raise AlatError(x.status_code, ab._pesan_status(x.status_code, {"detail": x.detail})) from None
        return __import__("json").loads(__import__("json").dumps(out, default=str))

    async def _rute(self, method, path, p, body, r):
        e = self.env
        mci, dis, pp, mb, thr = e["mci"], e["dis"], e["pp"], e["mb"], e["thr"]
        if (method, path) == ("GET", "/api/marketing/analitik/target"):
            return await e["ma"].analitik_target(r, dari_bulan=p.get("dari_bulan"), sampai_bulan=p.get("sampai_bulan"),
                                                 toko_id=p.get("toko_id"))
        if method == "GET" and path.startswith("/api/marketing/accounts/"):
            return await e["acc"].get_platform_account(path.rsplit("/", 1)[1], r)
        if (method, path) == ("GET", "/api/marketing/catalog-items/search"):
            return await e["mcs"].search_catalog_items(r, q=p.get("q"), catalog_id=None, account_id=p.get("account_id"),
                                                       platform=None, category_id=None, only_sellable=False,
                                                       limit=int(p.get("limit", 25)))
        m = re.fullmatch(r"/api/marketing/catalogs/([^/]+)/items/([^/]+)", path)
        if m and method == "PUT":
            return await mci.update_catalog_item(m.group(1), m.group(2), mci.CatalogItemUpdate(**body), r)
        m = re.fullmatch(r"/api/marketing/catalogs/([^/]+)/items", path)
        if m and method == "GET":
            return await mci.list_catalog_items(m.group(1), r, limit=int(p.get("limit", 100)))
        if (method, path) == ("GET", "/api/marketing/catalogs"):
            return await e["cm"].list_catalogs(r, account_id=p.get("account_id"), platform=None, is_active=None,
                                               search=None)
        if (method, path) == ("GET", "/api/marketing/change-log"):
            return await e["cl"].list_change_log(
                r, account_id=p.get("account_id"), entity=p.get("entity"), action=p.get("action"), actor_id=None,
                period=None, date_from=p.get("date_from"), date_to=p.get("date_to"), q=None, only_permissions=False,
                page=int(p.get("page", 1)), page_size=int(p.get("page_size", 20)))
        if (method, path) == ("GET", "/api/marketing/discounts"):
            return await dis.list_discounts(r, page=int(p.get("page", 1)), page_size=int(p.get("page_size", 20)),
                                            account_id=p.get("account_id", ""), status=p.get("status", ""),
                                            platform="", discount_type="", account="", search=p.get("search", ""))
        if (method, path) == ("POST", "/api/marketing/discounts"):
            return await dis.create_discount(dis.DiscountIn(**body), r)
        m = re.fullmatch(r"/api/marketing/discounts/([^/]+)", path)
        if m and method == "PUT":
            return await dis.update_discount(m.group(1), dis.DiscountUpdate(**body), r)
        if m and method == "DELETE":
            from core.roles import MARKETING_ROLES
            await e["authz"].require_roles(*MARKETING_ROLES)(r)        # dependensi `only(*MARKETING_ROLES)` route
            return await dis.delete_discount(m.group(1), r)
        if (method, path) == ("GET", "/api/production-pos"):
            return await pp.get_pos(r)
        if (method, path) == ("GET", "/api/production-pos/permissions"):
            return await pp.po_permissions(r)
        if (method, path) == ("POST", "/api/production-pos"):
            res = await pp.create_po(r)
            return json.loads(res.body)
        m = re.fullmatch(r"/api/production-pos/([^/]+)", path)
        if m and method == "GET":
            return await pp.get_po(m.group(1), r)
        if m and method == "PUT":
            return await pp.update_po(m.group(1), r)
        if m and method == "DELETE":
            return await pp.delete_po(m.group(1), r)
        if (method, path) == ("GET", "/api/doc-number-policy"):
            return await e["dn"].get_number_policy(r, key=p["key"])
        if (method, path) == ("GET", "/api/rahaza/variants"):
            return await e["rv"].list_variants(r, model_id=None, include_inactive=False, product_status=None)
        if (method, path) == ("GET", "/api/rahaza/stock-thresholds"):
            return await thr.list_stock_thresholds(r, type="", search=p.get("search", ""), status="all",
                                                   limit=int(p.get("limit", 1000)))
        if (method, path) == ("POST", "/api/rahaza/stock-thresholds/bulk"):
            return await thr.save_stock_thresholds(r)
        if (method, path) == ("GET", "/api/marketing/periods/locks"):
            return await mb.list_period_locks(r, account_id=None)
        if (method, path) == ("POST", "/api/marketing/periods/lock"):
            return await mb.set_period_lock(mb.PeriodLockIn(**body), r)
        if (method, path) == ("GET", "/api/merchandiser/check"):      # 12 Nov 2026 (K-M2): pengaman Merchandiser
            from core import merchandiser as mcm
            from routes import merchandiser as mr
            items = mr._pasangan(p.get("model"), "model_id") + mr._pasangan(p.get("varian"), "rahaza_variant_id")
            t = await mcm.periksa(e["db"], hari_ini=HARI, per_model=await mcm.model_dari_item(e["db"], items))
            return {"perlu_alasan": bool(t), "temuan": t, "pesan": mcm.pesan(t, "po_produksi") if t else "",
                    "min_alasan": mcm.MIN_ALASAN}
        raise AlatError(404, f"rute uji tidak ada: {method} {path}")


def _galat(coro, status):
    with pytest.raises(AlatError) as ei:
        run(coro)
    assert ei.value.status == status, ei.value.pesan
    return ei.value.pesan


def _log(db, **kw):
    return [r for r in db.marketing_change_log.docs if all(r.get(k) == v for k, v in kw.items())]


def _item(db, iid):
    return next(d for d in db.marketing_catalog_items.docs if d["id"] == iid)


HDR = {"X-Via": "asisten-ai", "X-Asisten-Tindakan": "tdk-uji-c1"}


# ══════════════════════════════════════════════════════════════════════════════
# 1. HARGA JUAL + RIWAYAT HARGA
# ══════════════════════════════════════════════════════════════════════════════
def _harga(**kw):
    return {"item": [{"sku": "SKU-UJI-1", "harga_jual": 120000}], "alasan": ALASAN, **kw}


def test_harga_siapkan_hanya_membaca_kartu_lama_baru_dan_margin(env):
    ctx = Ctx(env)
    r = run(TM.UbahHargaJual.siapkan(ctx, _harga()))
    assert not ctx.tulis
    assert {c["path"] for c in ctx.calls} == {"/api/marketing/analitik/target", "/api/marketing/catalog-items/search"}
    # SKU yang sama di dua toko DA (A1, A2); toko Sukma (A3) tidak ikut karena CV DA
    assert r["perubahan"] == [
        {"label": "SKU-UJI-1 · Shopee Uji Satu", "sebelum": "Rp 100.000 · coret Rp 130.000 · margin 38,0%",
         "sesudah": "Rp 120.000 · coret Rp 130.000 · margin 48,3%"},
        {"label": "SKU-UJI-1 · TikTok Uji Dua", "sebelum": "Rp 105.000 · margin 42,9%",
         "sesudah": "Rp 120.000 · margin 50,0%"}]
    assert r["ringkas"] == "2 item katalog di 2 toko — 2 naik, 0 turun."
    assert any("Seller Center" in c for c in r["catatan"])
    assert any("harga resmi Rp 100.000" in c for c in r["catatan"])               # beda dengan harga resmi master
    assert any("estimasi" in c for c in r["catatan"])                              # HPP FG = kalkulator (estimasi)
    assert r["ubah"][0] == {"kunci": "alasan", "label": "Alasan (masuk jejak)", "jenis": "teks", "nilai": ALASAN}
    assert r["ubah"][1] == {"kunci": "item.0.harga_jual", "label": "Harga jual SKU-UJI-1", "jenis": "rupiah",
                            "nilai": 120000}
    assert r["tautan"] == {"label": "Buka layar Katalog", "menu": "marketing-catalog"}
    assert len(json.dumps(r, ensure_ascii=False)) <= 8000


def test_harga_jalankan_lewat_endpoint_riwayat_harga_lalu_batalkan(env):
    db = env["db"]
    ctx = Ctx(env)
    args = _harga(item=[{"sku": "SKU-UJI-1", "toko_id": "A1", "harga_jual": 95000, "harga_coret": 125000}])
    rencana = run(TM.UbahHargaJual.siapkan(ctx, args))
    hasil = run(TM.UbahHargaJual.jalankan(ctx, args, rencana))
    assert hasil["ringkas"] == "Harga 1 item katalog diubah (0 naik, 1 turun)."
    w = ctx.tulis
    assert [(c["method"], c["path"]) for c in w] == [("PUT", "/api/marketing/catalogs/C1/items/I1")]
    assert w[0]["json"] == {"harga_jual": 95000.0, "harga_coret": 125000.0, "reason": f"Asisten AI · {ALASAN}"}
    assert w[0]["headers"] == HDR
    i1 = _item(db, "I1")
    assert (i1["harga_jual"], i1["price"], i1["harga_coret"], i1["hpp"]) == (95000.0, 95000.0, 125000.0, 55000.0)
    assert _item(db, "I2")["harga_jual"] == 105000.0                                 # toko lain tidak tersentuh
    j = _log(db, entity="catalog_item", action="price_change")
    assert len(j) == 1 and j[0]["before"] == {"harga_jual": 100000.0, "harga_coret": 130000.0}
    assert j[0]["after"] == {"harga_jual": 95000.0, "harga_coret": 125000.0} and j[0]["actor_id"] == "u-mgr"
    # riwayat harga (alat baca) membaca jejak itu + harga sekarang
    rh = run(ab._DAFTAR["riwayat_harga"].handler(Ctx(env), {"sku": "SKU-UJI-1"}))
    assert rh["jumlah_perubahan"] == 1
    b = rh["riwayat"][0]
    assert (b["toko"], b["sku"], b["harga_jual"], b["harga_coret"], b["lewat_asisten_ai"]) == \
        ("Shopee Uji Satu", "SKU-UJI-1", "Rp 100.000 → Rp 95.000", "Rp 130.000 → Rp 125.000", True)
    assert {h["toko"] for h in rh["harga_sekarang"]} == {"Shopee Uji Satu", "TikTok Uji Dua"}
    # — balikkan —
    ctx2 = Ctx(env)
    out = run(TM.UbahHargaJual.batalkan(ctx2, json.loads(json.dumps(hasil["pembatalan"]))))
    assert out["ringkas"] == "Harga 1 item katalog dikembalikan seperti sebelum tindakan."
    assert ctx2.tulis[0]["json"] == {"harga_jual": 100000.0, "harga_coret": 130000.0,
                                     "reason": "Asisten AI · membalikkan tindakan"}
    assert (_item(db, "I1")["harga_jual"], _item(db, "I1")["harga_coret"]) == (100000.0, 130000.0)
    assert len(_log(db, action="price_change")) == 2
    # riwayat tanpa SKU: nama produk dari daftar item katalog
    rh2 = run(ab._DAFTAR["riwayat_harga"].handler(Ctx(env), {"toko_id": "A1", "batas": 1}))
    assert rh2["jumlah_perubahan"] == 2 and rh2["ditampilkan"] == 1 and rh2["riwayat"][0]["sku"] == "SKU-UJI-1"
    assert rh2["riwayat"][0]["produk"] == "Gamis Uji" and "catatan_daftar" in rh2


def test_harga_batalkan_ditolak_bila_sudah_diubah_orang_lain(env):
    db = env["db"]
    ctx = Ctx(env)
    args = _harga()
    hasil = run(TM.UbahHargaJual.jalankan(ctx, args, run(TM.UbahHargaJual.siapkan(ctx, args))))
    _item(db, "I2")["harga_jual"] = 111000.0
    ctx2 = Ctx(env)
    pesan = _galat(TM.UbahHargaJual.batalkan(ctx2, hasil["pembatalan"]), 409)
    assert "TikTok Uji Dua" in pesan and not ctx2.tulis
    assert _item(db, "I1")["harga_jual"] == 120000.0


def test_harga_gagal_di_tengah_dikembalikan_semua(env):
    db = env["db"]
    ctx = Ctx(env, gagal={("PUT", "/api/marketing/catalogs/C2/"): 1})
    args = _harga()
    rencana = run(TM.UbahHargaJual.siapkan(ctx, args))
    pesan = _galat(TM.UbahHargaJual.jalankan(ctx, args, rencana), 500)
    assert "tidak ada yang berubah" in pesan
    assert _item(db, "I1")["harga_jual"] == 100000.0 and _item(db, "I2")["harga_jual"] == 105000.0


def test_harga_penolakan_ramah_dan_peringatan(env):
    db = env["db"]
    pesan = _galat(TM.UbahHargaJual.siapkan(Ctx(env, user=GUDANG), _harga()), 403)
    assert "tim Marketing" in pesan
    assert "coret" in _galat(TM.UbahHargaJual.siapkan(Ctx(env), _harga(
        item=[{"sku": "SKU-UJI-1", "harga_jual": 120000, "harga_coret": 110000}])), 400)
    assert "SKU-TAK-ADA" in _galat(TM.UbahHargaJual.siapkan(Ctx(env), _harga(
        item=[{"sku": "SKU-TAK-ADA", "harga_jual": 1000}])), 404)
    assert "sudah sama persis" in _galat(TM.UbahHargaJual.siapkan(Ctx(env), _harga(
        item=[{"sku": "SKU-UJI-1", "toko_id": "A1", "harga_jual": 100000}])), 409)
    assert "alasan" in _galat(TM.UbahHargaJual.siapkan(Ctx(env), _harga(alasan="ok")), 400)
    # staf berlingkup: hanya tokonya (A1); toko lain ditolak 403
    staf = Ctx(env, user=STAF)
    r = run(TM.UbahHargaJual.siapkan(staf, _harga()))
    assert [p["label"] for p in r["perubahan"]] == ["SKU-UJI-1 · Shopee Uji Satu"]
    _galat(TM.UbahHargaJual.siapkan(Ctx(env, user=STAF), _harga(
        item=[{"sku": "SKU-UJI-1", "toko_id": "A2", "harga_jual": 1000}])), 403)
    # CV Sukma: hanya toko Sukma; di bawah HPP + berubah besar + item non-aktif = peringatan
    r = run(TM.UbahHargaJual.siapkan(Ctx(env, cv="SMU"), _harga(item=[{"sku": "SKU-UJI-1", "harga_jual": 50000}])))
    assert [p["label"] for p in r["perubahan"]] == ["SKU-UJI-1 · Shopee Sukma Uji"]
    assert any("DI BAWAH HPP" in x and "rugi Rp 10.000" in x for x in r["peringatan"])
    assert any("-49%" in x for x in r["peringatan"])
    r = run(TM.UbahHargaJual.siapkan(Ctx(env), _harga(item=[{"sku": "SKU-UJI-2", "harga_jual": 55000}])))
    assert any("dihentikan" in x for x in r["peringatan"])
    assert any("margin belum bisa diukur" in c for c in r["catatan"])
    assert not db.marketing_change_log.docs


# ══════════════════════════════════════════════════════════════════════════════
# 2. PROMO
# ══════════════════════════════════════════════════════════════════════════════
def _promo(**kw):
    return {"aksi": "buat", "toko_id": "A1", "nama": "Flash sale 12.12 uji", "jenis": "flash_sale", "nilai": 30,
            "satuan": "persen", "mulai": "2026-12-10", "berakhir": "2026-12-12", "alasan": ALASAN, **kw}


def _diskon(db, did):
    return next((d for d in db.marketing_discounts.docs if d["id"] == did), None)


def test_promo_buat_siapkan_jalankan_lalu_batalkan_hapus(env):
    db = env["db"]
    ctx = Ctx(env)
    r = run(TM.AturPromo.siapkan(ctx, _promo()))
    assert not ctx.tulis and r["judul"] == "Buat promo di Shopee Uji Satu"
    assert r["ringkas"] == "Flash sale 30%, 10 Desember 2026 – 12 Desember 2026."
    assert {"label": "Periode", "sebelum": "—", "sesudah": "10 Desember 2026 – 12 Desember 2026"} in r["perubahan"]
    assert r["tautan"]["menu"] == "marketing-discounts" and r["ubah"][0]["kunci"] == "alasan"
    hasil = run(TM.AturPromo.jalankan(ctx, _promo(), r))
    w = ctx.tulis
    assert [(c["method"], c["path"]) for c in w] == [("POST", "/api/marketing/discounts")] and w[0]["headers"] == HDR
    baru = _diskon(db, hasil["pembatalan"]["promo_id"])
    assert (baru["account_id"], baru["platform"], baru["discount_value"], baru["status"]) == ("A1", "shopee", 30, "upcoming")
    # manager_marketing tidak boleh MENGHAPUS promo (aturan layar) → belum mulai → 403 ramah, promo tetap
    pesan = _galat(TM.AturPromo.batalkan(Ctx(env), hasil["pembatalan"]), 403)
    assert "owner/manager/PIC toko" in pesan and _diskon(db, baru["id"])
    # owner boleh menghapus
    out = run(TM.AturPromo.batalkan(Ctx(env, user=OWNER), hasil["pembatalan"]))
    assert "dihapus" in out["ringkas"] and _diskon(db, baru["id"]) is None
    out = run(TM.AturPromo.batalkan(Ctx(env, user=OWNER), hasil["pembatalan"]))     # sudah tidak ada → tidak galat
    assert "sudah tidak ada" in out["ringkas"]


def test_promo_buat_hari_ini_dibalikkan_tanpa_hak_hapus_menjadi_berakhir(env):
    db = env["db"]
    ctx = Ctx(env)
    args = _promo(mulai="2026-11-08", berakhir="2026-11-11", jenis="diskon_persen")
    hasil = run(TM.AturPromo.jalankan(ctx, args, run(TM.AturPromo.siapkan(ctx, args))))
    out = run(TM.AturPromo.batalkan(Ctx(env), hasil["pembatalan"]))
    assert "diakhiri hari ini" in out["ringkas"]
    assert _diskon(db, hasil["pembatalan"]["promo_id"])["end_date"] == "2026-11-08"


def test_promo_ubah_dan_akhiri_lalu_batalkan(env):
    db = env["db"]
    ctx = Ctx(env)
    args = {"aksi": "ubah", "nama_promo": "Voucher uji nanti", "nilai": 20000, "berakhir": "2026-11-24", "alasan": ALASAN}
    r = run(TM.AturPromo.siapkan(ctx, args))
    assert r["perubahan"] == [{"label": "Nilai", "sebelum": "Rp 15.000", "sesudah": "Rp 20.000"},
                              {"label": "Berakhir", "sebelum": "22 November 2026", "sesudah": "24 November 2026"}]
    assert {u["kunci"]: u["jenis"] for u in r["ubah"]} == {"alasan": "teks", "nilai": "rupiah", "berakhir": "tanggal"}
    hasil = run(TM.AturPromo.jalankan(ctx, args, r))
    assert ctx.tulis[0]["json"] == {"discount_value": 20000.0, "end_date": "2026-11-24"}
    assert (_diskon(db, "D2")["discount_value"], _diskon(db, "D2")["end_date"]) == (20000.0, "2026-11-24")
    run(TM.AturPromo.batalkan(Ctx(env), hasil["pembatalan"]))
    assert (_diskon(db, "D2")["discount_value"], _diskon(db, "D2")["end_date"]) == (15000, "2026-11-22")
    # akhiri promo aktif → tanggal berakhir hari ini; dibalikkan bila belum diubah orang lain
    ctx = Ctx(env)
    a = {"aksi": "akhiri", "promo_id": "D1", "alasan": ALASAN}
    r = run(TM.AturPromo.siapkan(ctx, a))
    assert r["perubahan"] == [{"label": "Berakhir", "sebelum": "15 November 2026", "sesudah": "8 November 2026"}]
    hasil = run(TM.AturPromo.jalankan(ctx, a, r))
    assert _diskon(db, "D1")["end_date"] == "2026-11-08"
    _diskon(db, "D1")["end_date"] = "2026-11-09"                                      # diubah orang lain
    assert "sudah diubah lagi" in _galat(TM.AturPromo.batalkan(Ctx(env), hasil["pembatalan"]), 409)
    _diskon(db, "D1")["end_date"] = "2026-11-08"
    run(TM.AturPromo.batalkan(Ctx(env), hasil["pembatalan"]))
    assert _diskon(db, "D1")["end_date"] == "2026-11-15"


def test_promo_penolakan_ramah(env):
    db = env["db"]
    n = len(db.marketing_discounts.docs)
    assert "tim Marketing" in _galat(TM.AturPromo.siapkan(Ctx(env, user=CS), _promo()), 403)
    assert "100%" in _galat(TM.AturPromo.siapkan(Ctx(env), _promo(nilai=120)), 400)
    assert "sebelum tanggal mulainya" in _galat(TM.AturPromo.siapkan(Ctx(env), _promo(berakhir="2026-12-01")), 400)
    assert "sudah lewat" in _galat(TM.AturPromo.siapkan(Ctx(env), _promo(mulai="2026-11-01")), 400)
    assert "toko_id" in _galat(TM.AturPromo.siapkan(Ctx(env), {"aksi": "buat", "alasan": ALASAN}), 400)
    _galat(TM.AturPromo.siapkan(Ctx(env, user=STAF), _promo(toko_id="A2")), 403)              # toko staf lain
    _galat(TM.AturPromo.siapkan(Ctx(env), _promo(toko_id="A3")), 403)                         # toko CV Sukma
    assert "belum mulai" in _galat(TM.AturPromo.siapkan(Ctx(env), {"aksi": "akhiri", "promo_id": "D2",
                                                                   "alasan": ALASAN}), 409)
    assert "sudah berakhir" in _galat(TM.AturPromo.siapkan(Ctx(env), {"aksi": "akhiri", "promo_id": "D3",
                                                                      "alasan": ALASAN}), 409)
    assert "sudah berakhir" in _galat(TM.AturPromo.siapkan(Ctx(env), {"aksi": "ubah", "promo_id": "D3", "nilai": 5,
                                                                      "alasan": ALASAN}), 409)
    assert "Sebutkan apa yang diubah" in _galat(TM.AturPromo.siapkan(Ctx(env), {"aksi": "ubah", "promo_id": "D2",
                                                                                "alasan": ALASAN}), 400)
    _galat(TM.AturPromo.siapkan(Ctx(env), {"aksi": "akhiri", "promo_id": "D4", "alasan": ALASAN}), 404)  # Sukma
    r = run(TM.AturPromo.siapkan(Ctx(env), _promo(jenis="flash_sale", mulai="2026-11-10", berakhir="2026-11-12")))
    assert any("bertumpuk" in x and "Flash sale uji aktif" in x for x in r["peringatan"])
    assert len(db.marketing_discounts.docs) == n


def test_daftar_promo_tanpa_data_contoh_dan_ikut_cv(env):
    h = run(ab._DAFTAR["daftar_promo"].handler(Ctx(env), {}))
    assert {p["id"] for p in h["promo"]} == {"D1", "D2", "D3"}                 # D4 Sukma, D5 data contoh
    assert h["catatan"] == "1 promo data contoh tidak ditampilkan."
    d1 = next(p for p in h["promo"] if p["id"] == "D1")
    assert (d1["status"], d1["nilai"], d1["sisa_hari"]) == ("Aktif", "20%", 7)
    h = run(ab._DAFTAR["daftar_promo"].handler(Ctx(env), {"status": "akan_datang"}))
    assert [p["id"] for p in h["promo"]] == ["D2"]
    h = run(ab._DAFTAR["daftar_promo"].handler(Ctx(env, cv="ALL"), {}))
    assert "D4" in {p["id"] for p in h["promo"]}


# ══════════════════════════════════════════════════════════════════════════════
# 3. PO PRODUKSI
# ══════════════════════════════════════════════════════════════════════════════
def _tenggat(**kw):
    return {"po": [{"nomor_po": "PO-INT-UJI-0001", "tenggat_produksi": "2026-11-27"}], "alasan": ALASAN, **kw}


def _po(db, pid):
    return next((d for d in db.production_pos.docs if d["id"] == pid), None)


def test_tenggat_po_siapkan_jalankan_hanya_tanggal_lalu_batalkan(env):
    db = env["db"]
    ctx = Ctx(env, user=PROD)
    r = run(TM.UbahTenggatPoProduksi.siapkan(ctx, _tenggat()))
    assert not ctx.tulis
    assert r["perubahan"] == [{"label": "PO-INT-UJI-0001 · Tenggat produksi", "sebelum": "20 November 2026",
                               "sesudah": "27 November 2026 (+7 hari)"}]
    assert any("tenggat kirim" in x for x in r["peringatan"])          # kirim 25 Nov < produksi 27 Nov
    assert r["tautan"]["menu"] == "prod-pos-internal" and r["ubah"][1]["kunci"] == "po.0.tenggat_produksi"
    hasil = run(TM.UbahTenggatPoProduksi.jalankan(ctx, _tenggat(), r))
    w = ctx.tulis
    assert [(c["method"], c["path"], c["json"]) for c in w] == [("PUT", "/api/production-pos/P1",
                                                                 {"deadline": "2026-11-27"})]
    p1 = _po(db, "P1")
    assert (p1["deadline"], p1["status"], p1["notes"]) == (datetime(2026, 11, 27), "Confirmed", "lama")
    assert db.po_items.docs[0]["qty"] == 100                                           # baris tidak tersentuh
    assert hasil["ringkas"] == "Tenggat 1 PO diubah: PO-INT-UJI-0001 (produksi 27 November 2026)."
    run(TM.UbahTenggatPoProduksi.batalkan(Ctx(env, user=PROD), json.loads(json.dumps(hasil["pembatalan"]))))
    assert _po(db, "P1")["deadline"] == datetime(2026, 11, 20)
    # tenggat kosong sebelumnya (draf maklon) → dibalikkan menjadi kosong lagi
    a = {"po": [{"nomor_po": "PO-MKL-UJI-0002", "tenggat_kirim": "2026-12-01"}], "alasan": ALASAN}
    ctx = Ctx(env, user=PROD, cv="SMU")
    r = run(TM.UbahTenggatPoProduksi.siapkan(ctx, a))
    assert r["perubahan"][0]["sebelum"] == "—" and r["tautan"]["menu"] == "maklon-pos-engine"
    hasil = run(TM.UbahTenggatPoProduksi.jalankan(ctx, a, r))
    assert _po(db, "P3")["delivery_deadline"] == datetime(2026, 12, 1)
    _po(db, "P3")["delivery_deadline"] = datetime(2026, 12, 3)
    assert "sudah diubah lagi" in _galat(TM.UbahTenggatPoProduksi.batalkan(Ctx(env, user=PROD), hasil["pembatalan"]), 409)
    _po(db, "P3")["delivery_deadline"] = datetime(2026, 12, 1)
    run(TM.UbahTenggatPoProduksi.batalkan(Ctx(env, user=PROD), hasil["pembatalan"]))
    assert _po(db, "P3")["delivery_deadline"] is None


def test_tenggat_po_penolakan_ramah(env):
    pesan = _galat(TM.UbahTenggatPoProduksi.siapkan(Ctx(env, user=PROD), _tenggat(
        po=[{"nomor_po": "PO-MKL-UJI-0001", "tenggat_produksi": "2026-11-30"}])), 409)
    assert "piutang" in pesan                                              # PO maklon dikonfirmasi: bukan untuk AI
    assert "ditutup" in _galat(TM.UbahTenggatPoProduksi.siapkan(Ctx(env, user=PROD), _tenggat(
        po=[{"nomor_po": "PO-INT-UJI-0004", "tenggat_produksi": "2026-11-30"}])), 409)
    assert "sudah lewat" in _galat(TM.UbahTenggatPoProduksi.siapkan(Ctx(env, user=PROD), _tenggat(
        po=[{"nomor_po": "PO-INT-UJI-0001", "tenggat_produksi": "2026-11-01"}])), 400)
    _galat(TM.UbahTenggatPoProduksi.siapkan(Ctx(env, user=PROD), _tenggat(
        po=[{"nomor_po": "PO-TIDAK-ADA", "tenggat_produksi": "2026-11-30"}])), 404)
    assert "tidak boleh mengubah" in _galat(TM.UbahTenggatPoProduksi.siapkan(Ctx(env, user=STAF), _tenggat()), 403)
    assert "sudah sama persis" in _galat(TM.UbahTenggatPoProduksi.siapkan(Ctx(env, user=PROD), _tenggat(
        po=[{"nomor_po": "PO-INT-UJI-0001", "tenggat_produksi": "2026-11-20"}])), 409)
    _galat(TM.UbahTenggatPoProduksi.siapkan(Ctx(env, user=PROD), _tenggat(
        po=[{"nomor_po": "PO-INT-UJI-0001"}])), 400)


def _draf(**kw):
    return {"baris": [{"sku": "GMS-HTM-M", "qty": 120}, {"sku": "gms-htm-l", "qty": 30}],
            "tenggat_produksi": "2026-12-05", "alasan": ALASAN, **kw}


def test_draf_po_selalu_draf_lalu_batalkan_hanya_draf_utuh(env):
    db = env["db"]
    ctx = Ctx(env, user=PROD)
    r = run(TM.BuatDrafPoProduksi.siapkan(ctx, _draf()))
    assert not ctx.tulis and r["ringkas"] == "2 SKU, total 150 pcs, tenggat produksi 5 Desember 2026."
    assert r["perubahan"][0] == {"label": "GMS-HTM-M · Hitam M", "sebelum": "—", "sesudah": "120 pcs"}
    assert any("Stop" in x and "GMS-HTM-L" in x for x in r["peringatan"])
    assert any("DRAF" in c for c in r["catatan"]) and any("tidak pernah mengonfirmasi" in c for c in r["catatan"])
    hasil = run(TM.BuatDrafPoProduksi.jalankan(ctx, _draf(), r))
    w = ctx.tulis
    assert [(c["method"], c["path"]) for c in w] == [("POST", "/api/production-pos")]
    assert "status" not in w[0]["json"] and w[0]["json"]["business_type"] == "internal"
    po = _po(db, hasil["pembatalan"]["po_id"])
    assert (po["status"], po["business_type"], po["po_number"]) == ("Draft", "internal", "PO-INT-UJI-101")
    assert po["deadline"] == datetime(2026, 12, 5) and ALASAN in po["notes"]
    items = [i for i in db.po_items.docs if i["po_id"] == po["id"]]
    assert sorted((i["sku"], i["qty"], i["rahaza_variant_id"]) for i in items) == [("GMS-HTM-L", 30, "V2"),
                                                                                  ("GMS-HTM-M", 120, "V1")]
    assert hasil["hasil"]["aksesoris_dari_bom"] == {"created": 2}
    # admin produksi tidak boleh MENGHAPUS PO (bawaan owner/admin) → 403 ramah, draf tetap
    assert "owner/admin" in _galat(TM.BuatDrafPoProduksi.batalkan(Ctx(env, user=PROD), hasil["pembatalan"]), 403)
    assert _po(db, po["id"])
    # draf yang sudah dikonfirmasi orang lain tidak dihapus
    _po(db, po["id"])["status"] = "Confirmed"
    assert "dikonfirmasi" in _galat(TM.BuatDrafPoProduksi.batalkan(Ctx(env, user=OWNER), hasil["pembatalan"]), 409)
    _po(db, po["id"])["status"] = "Draft"
    # Mongo menyimpan milidetik tanpa zona; jawaban POST membawa mikrodetik +00:00 → tetap dianggap "belum diubah"
    # (cacat ini ketahuan di uji langsung: semua draf ditolak 409 sebelum perbandingan waktu diperbaiki)
    u = _po(db, po["id"])["updated_at"]
    _po(db, po["id"])["updated_at"] = u.astimezone(timezone.utc).replace(tzinfo=None, microsecond=u.microsecond // 1000 * 1000)
    out = run(TM.BuatDrafPoProduksi.batalkan(Ctx(env, user=OWNER), hasil["pembatalan"]))
    assert out["ringkas"] == "Draf PO PO-INT-UJI-101 dihapus." and _po(db, po["id"]) is None
    assert not [i for i in db.po_items.docs if i["po_id"] == po["id"]]


def test_draf_po_batalkan_ditolak_bila_draf_sudah_diubah(env):
    db = env["db"]
    ctx = Ctx(env, user=OWNER)
    hasil = run(TM.BuatDrafPoProduksi.jalankan(ctx, _draf(), run(TM.BuatDrafPoProduksi.siapkan(ctx, _draf()))))
    _po(db, hasil["pembatalan"]["po_id"])["updated_at"] = datetime(2026, 11, 9, 10)
    assert "sudah diubah" in _galat(TM.BuatDrafPoProduksi.batalkan(Ctx(env, user=OWNER), hasil["pembatalan"]), 409)


def test_draf_po_penolakan_dan_penomoran_manual(env):
    db = env["db"]
    n = len(db.production_pos.docs)
    assert "GMS-XXX" in _galat(TM.BuatDrafPoProduksi.siapkan(Ctx(env, user=PROD), _draf(
        baris=[{"sku": "GMS-XXX", "qty": 1}])), 404)
    assert "dua kali" in _galat(TM.BuatDrafPoProduksi.siapkan(Ctx(env, user=PROD), _draf(
        baris=[{"sku": "GMS-HTM-M", "qty": 1}, {"sku": "gms-htm-m", "qty": 2}])), 400)
    assert "tidak boleh membuat" in _galat(TM.BuatDrafPoProduksi.siapkan(Ctx(env, user=STAF), _draf()), 403)
    assert "sebelum tenggat produksi" in _galat(TM.BuatDrafPoProduksi.siapkan(Ctx(env, user=PROD), _draf(
        tenggat_kirim="2026-12-01")), 400)
    assert "OTOMATIS" in _galat(TM.BuatDrafPoProduksi.siapkan(Ctx(env, user=PROD), _draf(nomor_po="PO-INT-X")), 400)
    db.doc_number_configs.docs.append({"key": "production_pos.po_number", "mode": "manual"})
    assert "MANUAL" in _galat(TM.BuatDrafPoProduksi.siapkan(Ctx(env, user=PROD), _draf()), 400)
    r = run(TM.BuatDrafPoProduksi.siapkan(Ctx(env, user=PROD), _draf(nomor_po="PO-INT-202611-0099")))
    assert any("PO-INT-202611-0099" in c for c in r["catatan"])
    assert len(db.production_pos.docs) == n


# ══════════════════════════════════════════════════════════════════════════════
# 4. AMBANG STOK
# ══════════════════════════════════════════════════════════════════════════════
def _mat(db, mid):
    return next(d for d in db.rahaza_materials.docs if d["id"] == mid)


def test_ambang_siapkan_jalankan_tanpa_menyentuh_stok_lalu_batalkan(env):
    db = env["db"]
    stok_awal = copy.deepcopy(db.rahaza_material_stock.docs)
    ctx = Ctx(env, user=OWNER)
    args = {"barang": [{"kode": "kain-uji-1", "titik_pesan_ulang": 60},
                       {"kode": "ACC-UJI-1", "stok_minimum": 25, "titik_pesan_ulang": 40}], "alasan": ALASAN}
    r = run(TM.UbahTitikPesanUlang.siapkan(ctx, args))
    assert not ctx.tulis
    assert r["perubahan"] == [
        {"label": "KAIN-UJI-1 Kain Uji", "sebelum": "min 20 m · pesan ulang 40 m · stok 45 m (aman)",
         "sesudah": "min 20 m · pesan ulang 60 m · stok 45 m (menipis)"},
        {"label": "ACC-UJI-1 Kancing Uji", "sebelum": "min 50 pcs · pesan ulang — · stok 30 pcs (kritis)",
         "sesudah": "min 25 pcs · pesan ulang 40 pcs · stok 30 pcs (menipis)"}]
    assert r["catatan"][0].startswith("Hanya ambang yang berubah; jumlah stok TIDAK disentuh")
    assert r["tautan"]["menu"] == "wh-master"
    hasil = run(TM.UbahTitikPesanUlang.jalankan(ctx, args, r))
    w = ctx.tulis
    assert [(c["method"], c["path"]) for c in w] == [("POST", "/api/rahaza/stock-thresholds/bulk")]
    assert w[0]["json"] == {"items": [{"material_id": "M-KAIN1", "reorder_point": 60.0},
                                      {"material_id": "M-ACC1", "min_stock_qty": 25.0, "reorder_point": 40.0}]}
    assert (_mat(db, "M-KAIN1")["reorder_point"], _mat(db, "M-ACC1")["min_stock_qty"]) == (60.0, 25.0)
    assert _mat(db, "M-ACC1")["min_stock"] == 50                                    # angka lama aksesoris utuh
    assert db.rahaza_material_stock.docs == stok_awal                                # stok TIDAK berubah
    run(TM.UbahTitikPesanUlang.batalkan(Ctx(env, user=OWNER), json.loads(json.dumps(hasil["pembatalan"]))))
    assert (_mat(db, "M-KAIN1")["reorder_point"], _mat(db, "M-ACC1")["min_stock_qty"],
            _mat(db, "M-ACC1")["reorder_point"]) == (40.0, None, 0.0)
    assert db.rahaza_material_stock.docs == stok_awal


def test_ambang_penolakan_dan_batalkan_bila_diubah(env):
    db = env["db"]
    args = {"barang": [{"kode": "KAIN-UJI-1", "stok_minimum": 0}], "alasan": ALASAN}
    assert "izin kelola gudang" in _galat(TM.UbahTitikPesanUlang.siapkan(Ctx(env, user=GUDANG), args), 403)
    ok = run(TM.UbahTitikPesanUlang.siapkan(Ctx(env, user=dict(GUDANG, _permissions=["warehouse.manage"])), args))
    assert ok["perubahan"][0]["sesudah"].startswith("min — · pesan ulang 40 m")
    _galat(TM.UbahTitikPesanUlang.siapkan(Ctx(env, user=OWNER), {"barang": [{"kode": "TIDAK-ADA-X", "stok_minimum": 1}],
                                                                "alasan": ALASAN}), 404)
    _galat(TM.UbahTitikPesanUlang.siapkan(Ctx(env, user=OWNER), {"barang": [{"kode": "KAIN-UJI-1"}],
                                                                "alasan": ALASAN}), 400)
    assert "sudah sama persis" in _galat(TM.UbahTitikPesanUlang.siapkan(Ctx(env, user=OWNER), {
        "barang": [{"kode": "KAIN-UJI-1", "stok_minimum": 20}], "alasan": ALASAN}), 409)
    r = run(TM.UbahTitikPesanUlang.siapkan(Ctx(env, user=OWNER), {
        "barang": [{"kode": "KAIN-UJI-1", "titik_pesan_ulang": 10}], "alasan": ALASAN}))
    assert any("lebih kecil dari stok minimum" in x for x in r["peringatan"])
    ctx = Ctx(env, user=OWNER)
    a = {"barang": [{"kode": "KAIN-UJI-1", "titik_pesan_ulang": 55}], "alasan": ALASAN}
    hasil = run(TM.UbahTitikPesanUlang.jalankan(ctx, a, run(TM.UbahTitikPesanUlang.siapkan(ctx, a))))
    _mat(db, "M-KAIN1")["reorder_point"] = 70
    assert "sudah diubah lagi" in _galat(TM.UbahTitikPesanUlang.batalkan(Ctx(env, user=OWNER), hasil["pembatalan"]), 409)


# ══════════════════════════════════════════════════════════════════════════════
# 5. TUTUP / BUKA BULAN MARKETING
# ══════════════════════════════════════════════════════════════════════════════
def _kunci(db, aid, bulan):
    d = next((x for x in db.marketing_period_locks.docs if x.get("account_id") == aid and x.get("period") == bulan), None)
    return bool((d or {}).get("locked"))


def test_tutup_bulan_semua_toko_cv_lalu_batalkan(env):
    db = env["db"]
    ctx = Ctx(env, user=SPV)
    args = {"aksi": "tutup", "bulan": "2026-10", "alasan": ALASAN}
    r = run(TM.TutupBukaBulanMarketing.siapkan(ctx, args))
    assert not ctx.tulis and r["judul"] == "Tutup periode marketing Oktober 2026"
    assert r["perubahan"] == [{"label": "Shopee Uji Satu", "sebelum": "Oktober 2026: Terbuka",
                               "sesudah": "Oktober 2026: Ditutup"},
                              {"label": "TikTok Uji Dua", "sebelum": "Oktober 2026: Terbuka",
                               "sesudah": "Oktober 2026: Ditutup"}]            # A3 (Sukma) tidak ikut di CV DA
    hasil = run(TM.TutupBukaBulanMarketing.jalankan(ctx, args, r))
    assert [(c["method"], c["json"]["account_id"], c["json"]["action"]) for c in ctx.tulis] == [
        ("POST", "A1", "close"), ("POST", "A2", "close")]
    assert _kunci(db, "A1", "2026-10") and _kunci(db, "A2", "2026-10") and not _kunci(db, "A3", "2026-10")
    j = _log(db, entity="marketing_period_locks", action="period_close")
    assert len(j) == 2 and all(x["reason"] == f"Asisten AI · {ALASAN}" for x in j)
    assert "sudah ditutup semua" in _galat(TM.TutupBukaBulanMarketing.siapkan(Ctx(env, user=SPV), {
        **args, "toko_id": ["A1"]}), 409)
    run(TM.TutupBukaBulanMarketing.batalkan(Ctx(env, user=SPV), hasil["pembatalan"]))
    assert not _kunci(db, "A1", "2026-10") and not _kunci(db, "A2", "2026-10")
    assert len(_log(db, action="period_reopen")) == 2
    assert "sudah diubah lagi" in _galat(TM.TutupBukaBulanMarketing.batalkan(Ctx(env, user=SPV), hasil["pembatalan"]),
                                         409)


def test_buka_tutup_bulan_penolakan_dan_peringatan(env):
    db = env["db"]
    assert "Target & Anggaran" in _galat(TM.TutupBukaBulanMarketing.siapkan(Ctx(env, user=STAF), {
        "aksi": "tutup", "bulan": "2026-10", "alasan": ALASAN}), 403)
    assert "belum berjalan" in _galat(TM.TutupBukaBulanMarketing.siapkan(Ctx(env, user=SPV), {
        "aksi": "tutup", "bulan": "2026-12", "alasan": ALASAN}), 400)
    assert "terbuka semua" in _galat(TM.TutupBukaBulanMarketing.siapkan(Ctx(env, user=SPV), {
        "aksi": "buka", "bulan": "2026-10", "alasan": ALASAN}), 409)
    _galat(TM.TutupBukaBulanMarketing.siapkan(Ctx(env, user=SPV), {
        "aksi": "tutup", "bulan": "2026-10", "toko_id": ["A3"], "alasan": ALASAN}), 403)
    r = run(TM.TutupBukaBulanMarketing.siapkan(Ctx(env, user=SPV), {"aksi": "tutup", "bulan": "2026-11",
                                                                    "alasan": ALASAN}))
    assert any("masih berjalan" in x for x in r["peringatan"])
    db.marketing_period_locks.docs.append({"account_id": "A1", "period": "2026-09", "locked": True})
    r = run(TM.TutupBukaBulanMarketing.siapkan(Ctx(env, user=SPV), {"aksi": "buka", "bulan": "2026-09",
                                                                    "alasan": ALASAN}))
    assert [p["label"] for p in r["perubahan"]] == ["Shopee Uji Satu"]
    assert any("dilewati" in c and "TikTok Uji Dua" in c for c in r["catatan"])


# ══════════════════════════════════════════════════════════════════════════════
# 6. REGISTRI, SKEMA, GABUNGAN, JALUR TERLARANG
# ══════════════════════════════════════════════════════════════════════════════
CONTOH = {
    "ubah_harga_jual": (TM.UbahHargaJual, _harga()),
    "atur_promo": (TM.AturPromo, _promo()),
    "ubah_tenggat_po_produksi": (TM.UbahTenggatPoProduksi, _tenggat()),
    "buat_draf_po_produksi": (TM.BuatDrafPoProduksi, _draf()),
    "ubah_titik_pesan_ulang": (TM.UbahTitikPesanUlang, {"barang": [{"kode": "KAIN-UJI-1", "stok_minimum": 1}],
                                                        "alasan": ALASAN}),
    "tutup_buka_bulan_marketing": (TM.TutupBukaBulanMarketing, {"aksi": "tutup", "bulan": "2026-10",
                                                                "alasan": ALASAN}),
}


def test_semua_tindakan_menengah_terdaftar_dengan_skema_ketat():
    for nama, (kelas, isian) in CONTOH.items():
        a = ab._DAFTAR[nama]
        assert a.adalah_tindakan and a.kelas is kelas and a.risiko == "menengah" and a.menu, nama
        assert a.bisa_dibalikkan, nama
        assert ab.periksa_skema(a.input_schema, isian) == [], nama
        assert ab.periksa_skema(a.input_schema, {**isian, "liar": 1}), nama
        assert ab.periksa_skema(a.input_schema, {k: v for k, v in isian.items() if k != "alasan"}), nama
        d = a.untuk_api()["description"]
        assert d.startswith(ab.AWALAN_TINDAKAN + ab.AWALAN_MENENGAH), nama
    for nama in ("riwayat_harga", "daftar_promo"):
        assert ab._DAFTAR[nama].kind == "read"
    semua = json.dumps([ab._DAFTAR[n].untuk_api() for n in list(CONTOH) + ["riwayat_harga", "daftar_promo"]],
                       ensure_ascii=False)
    assert not re.search(r"\d{4}-\d{2}-\d{2}", semua) and "2026" not in semua


def test_semua_tindakan_menolak_mode_gabungan_tanpa_memanggil_api(env):
    for nama, (kelas, isian) in CONTOH.items():
        ctx = Ctx(env, user=OWNER, cv="ALL")
        pesan = _galat(kelas.siapkan(ctx, isian), 400)
        assert "Gabungan" in pesan and not ctx.calls, nama


def test_tidak_ada_jalur_terlarang_di_modul():
    """Hanya endpoint layar yang disebut; tidak ada konfirmasi/status PO, penyesuaian stok, jurnal, pembayaran."""
    src = Path(TM.__file__).read_text(encoding="utf-8")
    jalur = {j.rstrip("/") for j in re.findall(r'"(/api/[^"{]*)', src)}
    assert jalur <= {"/api/marketing/catalog-items/search", "/api/marketing/change-log", "/api/marketing/catalogs",
                     "/api/marketing/discounts", "/api/production-pos", "/api/rahaza/variants",
                     "/api/doc-number-policy", "/api/rahaza/stock-thresholds", "/api/marketing/periods/lock",
                     "/api/marketing/periods/locks",
                     "/api/merchandiser/check"}, jalur      # 12 Nov 2026 (K-M2): cek pengaman, baca saja
    for kata in ("/status", "confirm", "quick-complete", "close-short", "stock-adjust", "adjustment", "journal",
                 "payment", "/close"):
        assert kata not in src, kata
