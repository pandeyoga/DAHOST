"""Mongo palsu in-memory (secukupnya) untuk uji unit HERMETIK paket P5 (2026-11-02).

Mendukung operasi yang dipakai route payroll/kasbon/dinas/klaim: find/find_one/count_documents/
insert_one/insert_many/update_one/delete_one/delete_many + kursor sort/skip/limit/to_list/async-for.
Operator kueri: kesetaraan (termasuk elemen array), $in $nin $ne $lt $lte $gt $gte $exists $regex
$or $and $not $elemMatch. Operator update: $set $push $inc $addToSet.
"""
from __future__ import annotations

import copy
import re


def _get(doc, dotted):
    cur = doc
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


class _Missing:
    def __repr__(self):
        return "<missing>"


_MISSING = _Missing()


def _cmp_ok(v, op, arg):
    if v is _MISSING or v is None:
        return False
    try:
        return {"$lt": v < arg, "$lte": v <= arg, "$gt": v > arg, "$gte": v >= arg}[op]
    except TypeError:
        return False


def _match_value(v, cond):
    if isinstance(cond, dict) and cond and all(str(k).startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$in":
                vals = v if isinstance(v, list) else [None if v is _MISSING else v]
                if not any(x in arg for x in vals):
                    return False
            elif op == "$nin":
                vals = v if isinstance(v, list) else [None if v is _MISSING else v]
                if any(x in arg for x in vals):
                    return False
            elif op == "$ne":
                if isinstance(v, list):
                    if arg in v:
                        return False
                elif (None if v is _MISSING else v) == arg:
                    return False
            elif op in ("$lt", "$lte", "$gt", "$gte"):
                if not _cmp_ok(v, op, arg):
                    return False
            elif op == "$exists":
                if (v is not _MISSING) != bool(arg):
                    return False
            elif op == "$regex":
                if v is _MISSING or not re.search(arg, str(v), re.I if "i" in cond.get("$options", "") else 0):
                    return False
            elif op == "$options":
                continue
            elif op == "$not":
                if _match_value(v, arg):
                    return False
            elif op == "$elemMatch":
                if not isinstance(v, list) or not any(isinstance(x, dict) and match(x, arg) for x in v):
                    return False
            else:
                raise NotImplementedError(op)
        return True
    if isinstance(v, list) and not isinstance(cond, list):
        return cond in v
    return (None if v is _MISSING else v) == cond


def match(doc, q):
    for k, cond in (q or {}).items():
        if k == "$or":
            if not any(match(doc, sub) for sub in cond):
                return False
        elif k == "$and":
            if not all(match(doc, sub) for sub in cond):
                return False
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


def _set_path(doc, dotted, value):
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


class _Result:
    def __init__(self, matched=0, modified=0, deleted=0, inserted_id=None):
        self.matched_count = matched
        self.modified_count = modified
        self.deleted_count = deleted
        self.inserted_id = inserted_id


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        if isinstance(key, list):
            for k, d in reversed(key):
                self.sort(k, d)
            return self
        self._docs.sort(key=lambda d: (_get(d, key) is _MISSING, str(_get(d, key))), reverse=direction == -1)
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        if n:
            self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return [copy.deepcopy(d) for d in (self._docs if not length else self._docs[:length])]

    def __aiter__(self):
        self._it = iter([copy.deepcopy(d) for d in self._docs])
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs: list = []

    def find(self, q=None, projection=None):
        return FakeCursor([d for d in self.docs if match(d, q)])

    async def find_one(self, q=None, projection=None, **kw):
        for d in self.docs:
            if match(d, q):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, q=None):
        return sum(1 for d in self.docs if match(d, q))

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))
        return _Result(inserted_id=doc.get("id"))

    async def insert_many(self, docs):
        for d in docs:
            self.docs.append(copy.deepcopy(d))
        return _Result()

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    _set_path(d, k, copy.deepcopy(v))
                for k, v in (upd.get("$inc") or {}).items():
                    _set_path(d, k, (_get(d, k) if _get(d, k) is not _MISSING else 0) + v)
                for k, v in (upd.get("$push") or {}).items():
                    cur = _get(d, k)
                    _set_path(d, k, (cur if isinstance(cur, list) else []) + [copy.deepcopy(v)])
                for k, v in (upd.get("$addToSet") or {}).items():
                    cur = _get(d, k)
                    cur = cur if isinstance(cur, list) else []
                    if v not in cur:
                        cur = cur + [v]
                    _set_path(d, k, cur)
                return _Result(matched=1, modified=1)
        return _Result()

    async def update_many(self, q, upd):
        n = 0
        for d in self.docs:
            if match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    _set_path(d, k, copy.deepcopy(v))
                n += 1
        return _Result(matched=n, modified=n)

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if match(d, q):
                del self.docs[i]
                return _Result(deleted=1)
        return _Result()

    async def delete_many(self, q):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not match(d, q)]
        return _Result(deleted=before - len(self.docs))


class FakeDB:
    def __init__(self):
        self._cols: dict = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = FakeCollection(name)
        return self._cols[name]


class FakeRequest:
    """Request FastAPI palsu: hanya `await request.json()` dan `request.state`."""

    def __init__(self, body=None):
        self._body = body or {}

        class _S:
            pass

        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._body)
