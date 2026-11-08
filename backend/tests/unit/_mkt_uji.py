"""Alat uji HERMETIK paket MKT-INTI (audit Marketing 9 Nov 2026) — tanpa Mongo, tanpa server.

Meniru skenario uji audit s1–s4 (`scratchpad/audit_dalam/mkt/s*.py`) dengan memanggil route
ASLI (`routes.marketing_data_import` dst.) di atas Mongo palsu yang sedikit lebih lengkap dari
`_fake_mongo`: upsert + `$setOnInsert`, `find_one_and_update` (kunci dokumen), dan `aggregate`
sederhana ($match/$group/$sort/$limit) yang dipakai ringkasan iklan & skor kesehatan.

Semua baris yang dibuat di sini SINTETIS; satu-satunya berkas nyata yang dibaca adalah dua
ekspor contoh yang sudah ada di repo (`samples/marketplace_2026/`), dan yang dibandingkan
hanya total omzet per hari (tanpa nama/alamat pembeli).
"""
from __future__ import annotations

import asyncio
import copy
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402

SAMPLES = REPO / "samples" / "marketplace_2026"

SA = {"id": "u-sa", "email": "sa@uji.test", "role": "superadmin", "name": "SA Uji"}
SPV = {"id": "u-spv", "email": "spv@uji.test", "role": "spv_marketing", "name": "SPV Uji"}
PIC = {"id": "u-pic", "email": "pic@uji.test", "role": "pic_toko", "name": "PIC Uji"}


def run(coro):
    return asyncio.run(coro)


def _expr(doc, e):
    if isinstance(e, str) and e.startswith("$"):
        v = fm._get(doc, e[1:])
        return None if v is fm._MISSING else v
    if isinstance(e, dict) and "$ifNull" in e:
        a, b = e["$ifNull"]
        v = _expr(doc, a)
        return v if v is not None else _expr(doc, b)
    return e


class Coll(fm.FakeCollection):
    async def update_one(self, q, upd, upsert=False):
        res = await super().update_one(q, upd)
        if res.matched_count or not upsert:
            return res
        d = {k: copy.deepcopy(v) for k, v in q.items() if not k.startswith("$")
             and not isinstance(v, dict)}
        for k, v in (upd.get("$setOnInsert") or {}).items():
            fm._set_path(d, k, copy.deepcopy(v))
        for k, v in (upd.get("$set") or {}).items():
            fm._set_path(d, k, copy.deepcopy(v))
        self.docs.append(d)
        return fm._Result(matched=0, modified=0)

    async def find_one_and_update(self, q, upd, upsert=False, return_document=None, **_kw):
        for d in self.docs:
            if fm.match(d, q):
                break
        else:
            if not upsert:
                return None
            d = {k: v for k, v in q.items() if not k.startswith("$")}
            d.update(copy.deepcopy(upd.get("$setOnInsert") or {}))
            self.docs.append(d)
        for k, v in (upd.get("$set") or {}).items():
            fm._set_path(d, k, copy.deepcopy(v))
        for k, v in (upd.get("$inc") or {}).items():
            fm._set_path(d, k, (fm._get(d, k) if fm._get(d, k) is not fm._MISSING else 0) + v)
        return copy.deepcopy(d)

    async def distinct(self, key, q=None):
        out = []
        for d in self.docs:
            if fm.match(d, q or {}):
                v = fm._get(d, key)
                if v is not fm._MISSING and v not in out:
                    out.append(v)
        return out

    async def create_index(self, *_a, **_k):
        return "ok"

    def aggregate(self, pipeline):
        docs = [copy.deepcopy(d) for d in self.docs]
        for stage in pipeline:
            (op, arg), = stage.items()
            if op == "$match":
                docs = [d for d in docs if fm.match(d, arg)]
            elif op == "$group":
                groups: dict = {}
                for d in docs:
                    gid = arg["_id"]
                    key = (tuple((k, _expr(d, v)) for k, v in gid.items())
                           if isinstance(gid, dict) else _expr(d, gid))
                    g = groups.setdefault(str(key), {"_id": (
                        {k: _expr(d, v) for k, v in gid.items()} if isinstance(gid, dict) else key)})
                    for name, acc in arg.items():
                        if name == "_id":
                            continue
                        (aop, aexp), = acc.items()
                        if aop == "$sum":
                            val = 1 if aexp == 1 else (_expr(d, aexp) or 0)
                            g[name] = g.get(name, 0) + (val if isinstance(val, (int, float)) else 0)
                        elif aop == "$first":
                            g.setdefault(name, _expr(d, aexp))
                        elif aop == "$addToSet":
                            g.setdefault(name, [])
                            v = _expr(d, aexp)
                            if v not in g[name]:
                                g[name].append(v)
                docs = list(groups.values())
            elif op == "$sort":
                for k, direction in reversed(list(arg.items())):
                    docs.sort(key=lambda x: (fm._get(x, k) is fm._MISSING, fm._get(x, k)),
                              reverse=direction == -1)
            elif op == "$limit":
                docs = docs[:arg]
        return fm.FakeCursor(docs)


class DB(fm.FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = Coll(name)
        return self._cols[name]


def acc(aid, platform="tiktok", **kw):
    return {"id": aid, "account_code": aid, "account_name": f"Toko {aid}", "platform": platform,
            "status": "active", "revenue_basis": "produk_setelah_diskon", **kw}


def request_for(user):
    r = fm.FakeRequest()
    r.state.user = dict(user)
    return r


def patch_import(monkeypatch, db, user=SA):
    """Pasang route impor ASLI di atas `db` palsu. → modul `routes.marketing_data_import`."""
    import routes.marketing_data_import as md
    import routes.marketing_shared as msh

    store: dict = {}
    cur = {"user": dict(user)}

    async def _auth(req=None, *a, **k):
        if req is not None and getattr(req, "state", None) is not None:
            req.state.user = dict(cur["user"])
        return dict(cur["user"])

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(md, "get_db", lambda: db)
    monkeypatch.setattr(md, "require_auth", _auth)
    monkeypatch.setattr(md, "log_activity", _noop)
    monkeypatch.setattr(md, "_put_object", lambda path, raw, _ct: store.__setitem__(path, raw))
    monkeypatch.setattr(md, "_read_session_file", lambda p: store.get(p))
    monkeypatch.setattr(md, "_delete_object", lambda p: store.pop(p, None) is not None)
    monkeypatch.setattr(msh, "_recalculate_health_score", _noop)
    md._uji_user = cur
    return md


async def upload(md, raw: bytes, fname: str, source_type: str, account_id: str, user=None):
    from starlette.datastructures import UploadFile
    req = request_for(user or md._uji_user["user"])
    if user is not None:
        md._uji_user["user"] = dict(user)
    f = UploadFile(file=io.BytesIO(raw), filename=fname)
    return await md.upload(req, file=f, source_type=source_type, account_id=account_id,
                           host_id=None, creator_id=None, catalog_id=None, live_session_id=None)


async def commit(md, sid: str, on_duplicate="skip", user=None):
    if user is not None:
        md._uji_user["user"] = dict(user)
    return await md.commit(sid, request_for(md._uji_user["user"]),
                           md.CommitIn(on_duplicate=on_duplicate))


async def import_file(md, raw, fname, source_type, account_id, on_duplicate="skip", user=None):
    up = await upload(md, raw, fname, source_type, account_id, user=user)
    sid = up["session"]["id"]
    res = await commit(md, sid, on_duplicate=on_duplicate, user=user)
    return sid, res


def csv_bytes(rows):
    import csv
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().encode()


TIKTOK_HDR = ["Order ID", "Order Status", "SKU ID", "Seller SKU", "Product Name", "Variation",
              "Quantity", "SKU Subtotal After Discount", "Order Amount", "Created Time", "Paid Time",
              "Purchase Channel", "Order Channel"]


def tiktok_orders(status_by_id, *, created="03/08/2026 23:30:00", channel="Videos",
                  amount=100000):
    """Ekspor pesanan bergaya TikTok (sintetis): satu SKU per pesanan."""
    out = [TIKTOK_HDR]
    for i, (oid, stt) in enumerate(status_by_id.items()):
        out.append([oid, stt, f"SKU{i}", f"UJI-{i}", f"Barang uji {i}", "Hitam, M", 1, amount,
                    amount + 10000, created, created, "TikTok", channel])
    return csv_bytes(out)


async def rekap(db, aid, d, rtype="total"):
    x = await db.marketing_sales_data.find_one({"account_id": aid, "date": d, "revenue_type": rtype})
    if not x:
        return None
    m = x.get("metrics") or {}
    return {"omzet": m.get("revenue"), "pesanan": m.get("orders"), "src": x.get("source"),
            "doc": x}


class Req(fm.FakeRequest):
    """Request palsu + `query_params` (dipakai route yang membaca query sendiri)."""

    def __init__(self, user=None, query=None, body=None):
        super().__init__(body)
        self.state.user = dict(user or SA)
        self.query_params = dict(query or {})


def patch_route(monkeypatch, mod, db, user=SA):
    """Pasang route modul `mod` di atas `db` palsu dengan pemakai `user`."""
    async def _auth(req=None, *a, **k):
        if req is not None and getattr(req, "state", None) is not None:
            req.state.user = dict(user)
        return dict(user)

    async def _noop(*_a, **_k):
        return None
    for name, val in (("get_db", lambda: db), ("require_auth", _auth), ("log_activity", _noop),
                      ("refresh_stale_health_scores", _noop), ("_recalculate_health_score", _noop)):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, val)
    return mod


def rekap_doc(aid, date, revenue, orders=1, *, live=0.0, source="orders_auto", rtype="total",
              retur=0.0, **extra):
    """Satu dokumen rekap harian bentuk kanonik (sintetis)."""
    return {"id": f"rk-{aid}-{date}-{rtype}", "account_id": aid, "date": date, "revenue_type": rtype,
            "source": source, "metrics": {"revenue": revenue, "orders": orders,
                                          "revenue_product": revenue},
            "traffic": {"live": live}, "fulfillment": {"returned_revenue_product": retur},
            "revenue_basis": "produk_setelah_diskon", **extra}
