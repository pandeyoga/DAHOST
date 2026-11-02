"""Alat bantu uji HERMETIK paket P6 (AI) — 2026-11-02.

Berisi Mongo palsu (cukup untuk pola find/aggregate/count/update yang dipakai route AI)
dan klien Anthropic PALSU. Tidak ada koneksi DB / panggilan API sungguhan.
"""
import os
import sys
from types import SimpleNamespace

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows or [])

    def sort(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def to_list(self, length=None):
        return list(self.rows)

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, name, db):
        self.name = name
        self.db = db
        self.calls = []

    def _of(self, kind):
        return [c for c in self.calls if c[0] == kind]

    def find(self, filt=None, proj=None, **kw):
        self.calls.append(("find", filt))
        return FakeCursor(self.db.find_rows.get(self.name, []))

    async def find_one(self, filt=None, proj=None, **kw):
        self.calls.append(("find_one", filt))
        v = self.db.find_one_map.get(self.name)
        return v(filt) if callable(v) else v

    async def count_documents(self, filt=None):
        self.calls.append(("count", filt))
        return self.db.counts.get(self.name, 0)

    def aggregate(self, pipeline):
        self.calls.append(("aggregate", pipeline))
        rows = self.db.agg_rows.get(self.name, [])
        return FakeCursor(rows(pipeline) if callable(rows) else rows)

    async def insert_one(self, doc):
        self.calls.append(("insert_one", doc))

    async def insert_many(self, docs):
        self.calls.append(("insert_many", docs))

    async def update_one(self, filt, upd, upsert=False):
        self.calls.append(("update_one", filt, upd))

    async def replace_one(self, filt, doc, upsert=False):
        self.calls.append(("replace_one", filt, doc))

    async def delete_one(self, filt):
        self.calls.append(("delete_one", filt))
        return SimpleNamespace(deleted_count=1)


class FakeDB:
    def __init__(self):
        self.cols = {}
        self.find_rows = {}
        self.find_one_map = {}
        self.counts = {}
        self.agg_rows = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self.cols.setdefault(name, FakeCollection(name, self))

    def __getitem__(self, name):
        return self.__getattr__(name)


# ── Klien Anthropic palsu ────────────────────────────────────────────────────
def fake_message(text="halo", stop_reason="end_turn", thinking=True, tin=120, tout=40):
    blocks = []
    if thinking:
        # Opus/Sonnet 5.5: blok thinking dengan teks kosong (display "omitted")
        blocks.append(SimpleNamespace(type="thinking", thinking=""))
    if text is not None:
        blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(content=blocks, stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=tin, output_tokens=tout))


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0) if self.responses else fake_message()
        if isinstance(r, BaseException):
            raise r
        return r


class FakeAnthropic:
    def __init__(self, responses=()):
        self.messages = FakeMessages(responses)


class FakeRequest:
    def __init__(self, body=None, user=None):
        self._body = body or {}
        self.state = SimpleNamespace(user=user or {})

    async def json(self):
        return self._body


def run(coro):
    import asyncio
    return asyncio.run(coro)
