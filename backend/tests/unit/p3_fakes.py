"""Fake Mongo (async) minimal untuk uji unit HERMETIK paket P3 (2026-11-02).

Hanya operator yang dipakai kode yang diuji: kesamaan, $in/$nin/$ne/$exists/$lt/$lte/
$gt/$gte/$regex, $or/$and, path bertitik, dan update $set/$inc/$push/$unset.
Update ber-pipeline (list) sengaja TIDAK didukung — uji yang menyentuh stock_service
memalsukan fungsi stock_service-nya.
"""
from __future__ import annotations

import copy
import re
import uuid


def _get(doc, path):
    cur = doc
    for p in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _cmp_ok(val, op, arg):
    if op == "$in":
        return (val in arg) or (isinstance(val, list) and any(v in arg for v in val))
    if op == "$nin":
        return val not in arg
    if op == "$ne":
        return val != arg
    if op == "$exists":
        return (val is not None) == bool(arg)
    if op == "$regex":
        return isinstance(val, str) and re.search(arg, val) is not None
    if op in ("$lt", "$lte", "$gt", "$gte"):
        if val is None:
            return False
        return {"$lt": val < arg, "$lte": val <= arg, "$gt": val > arg, "$gte": val >= arg}[op]
    if op == "$options":
        return True
    raise NotImplementedError(op)


def match(doc, flt):
    for k, v in (flt or {}).items():
        if k == "$or":
            if not any(match(doc, f) for f in v):
                return False
            continue
        if k == "$and":
            if not all(match(doc, f) for f in v):
                return False
            continue
        val = _get(doc, k)
        if isinstance(v, dict) and v and all(str(x).startswith("$") for x in v):
            if "$regex" in v and "i" in str(v.get("$options", "")):
                if not (isinstance(val, str) and re.search(v["$regex"], val, re.I)):
                    return False
                continue
            if not all(_cmp_ok(val, op, arg) for op, arg in v.items()):
                return False
        elif isinstance(val, list) and not isinstance(v, list):
            if v not in val:
                return False
        elif val != v:
            return False
    return True


def _set_path(doc, path, value):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def apply_update(doc, upd):
    if isinstance(upd, list):
        raise NotImplementedError("pipeline update tidak didukung FakeDB")
    for k, v in (upd.get("$set") or {}).items():
        _set_path(doc, k, v)
    for k, v in (upd.get("$inc") or {}).items():
        _set_path(doc, k, (_get(doc, k) or 0) + v)
    for k, v in (upd.get("$push") or {}).items():
        cur = _get(doc, k)
        if not isinstance(cur, list):
            cur = []
        cur.append(v)
        _set_path(doc, k, cur)
    for k in (upd.get("$unset") or {}):
        doc.pop(k, None)


class _Res:
    def __init__(self, matched=0, modified=0, upserted_id=None, inserted_id=None):
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = upserted_id
        self.inserted_id = inserted_id


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self.docs.sort(key=lambda x: (_get(x, k) is None, _get(x, k) if _get(x, k) is not None else 0),
                           reverse=d < 0)
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in (self.docs if not n else self.docs[:n])]

    def __aiter__(self):
        self._it = iter([copy.deepcopy(d) for d in self.docs])
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeColl:
    def __init__(self, docs=None):
        self.docs = [copy.deepcopy(d) for d in (docs or [])]
        self.updates = []          # jejak (filter, update) untuk asersi

    def _found(self, flt):
        return [d for d in self.docs if match(d, flt)]

    async def find_one(self, flt=None, proj=None, sort=None):
        rows = self._found(flt or {})
        if sort:
            rows = FakeCursor(rows).sort(sort).docs
        return copy.deepcopy(rows[0]) if rows else None

    def find(self, flt=None, proj=None):
        return FakeCursor(self._found(flt or {}))

    async def insert_one(self, doc):
        d = copy.deepcopy(doc)
        d.setdefault("_id", str(uuid.uuid4()))
        self.docs.append(d)
        doc.setdefault("_id", d["_id"])
        return _Res(inserted_id=d["_id"])

    async def update_one(self, flt, upd, upsert=False):
        self.updates.append((flt, upd))
        rows = self._found(flt)
        if not rows:
            return _Res()
        apply_update(rows[0], upd)
        return _Res(1, 1)

    async def update_many(self, flt, upd):
        self.updates.append((flt, upd))
        rows = self._found(flt)
        for r in rows:
            apply_update(r, upd)
        return _Res(len(rows), len(rows))

    async def count_documents(self, flt):
        return len(self._found(flt))


class FakeDB:
    def __init__(self, **colls):
        self._c = {k: FakeColl(v) for k, v in colls.items()}

    def __getitem__(self, name):
        return self._c.setdefault(name, FakeColl())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


class FakeRequest:
    def __init__(self, body=None):
        self._body = body or {}

    async def json(self):
        return self._body

    async def body(self):
        return b"{}" if self._body else b""
