"""core.doc_lock — klaim atomik dokumen sebelum efek samping (pola P9, 2026-11-06).

Masalah yang ditutup: handler membaca dokumen, memeriksa status di Python, lalu menulis stok /
jurnal / uang / dokumen turunan. Klik ganda atau dua pengguna sama-sama lolos pemeriksaan itu dan
efeknya terjadi dua kali. Dua cara yang dipakai Tahap 1 disatukan di sini:

* ``require_matched`` — status yang diharapkan ikut di FILTER penulisan; penulisan yang tidak
  mengenai dokumen berarti pengguna lain sudah lebih dulu → HTTP 409.
* ``claim`` / ``release`` — bila status baru boleh ditulis SESUDAH efek samping selesai (mis. jurnal
  dulu), dokumen dikunci dengan token (``<field>``, ``<field>_at``). Permintaan kedua tidak lolos
  klaim → 409. Kunci dilepas sesudah selesai/gagal; kunci basi (proses mati) lepas sendiri
  sesudah ``STALE``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

STALE = timedelta(minutes=10)
BUSY = "Dokumen ini sedang/baru saja diproses pengguna lain. Muat ulang halaman lalu periksa hasilnya."


def _now():
    return datetime.now(timezone.utc)


def lock_free(field: str = "proc_lock") -> dict:
    """Filter "tidak sedang dikunci" (kunci kosong atau basi) — dipakai penulis lain (batal/tolak)
    supaya tidak menyalip proses yang sedang berjalan."""
    return {"$or": [{field: None}, {f"{field}_at": {"$lt": _now() - STALE}}]}


def require_matched(res, message: str = BUSY) -> None:
    """Penulisan bersyarat status tidak mengenai dokumen → pengguna lain sudah lebih dulu (409)."""
    if not getattr(res, "matched_count", 0):
        raise HTTPException(409, message)


async def claim(db, coll: str, doc_id, *, field: str = "proc_lock", extra: dict | None = None,
                busy: str = BUSY, not_found: str = "Dokumen tidak ditemukan.",
                actor: dict | None = None, key: str = "id") -> str:
    """Kunci dokumen untuk satu proses. Return token; 404 bila dokumen tidak ada, 409 bila
    sedang dipegang proses lain atau tidak lagi memenuhi ``extra`` (mis. status sudah berubah)."""
    token = uuid.uuid4().hex
    now = _now()
    q = {key: doc_id, "$and": [lock_free(field)] + ([extra] if extra else [])}
    res = await db[coll].update_one(q, {"$set": {field: token, f"{field}_at": now,
                                                 f"{field}_by": (actor or {}).get("id")}})
    if not res.matched_count:
        if not await db[coll].find_one({key: doc_id}, {"_id": 1}):
            raise HTTPException(404, not_found)
        raise HTTPException(409, busy)
    return token


async def release(db, coll: str, doc_id, token: str, *, field: str = "proc_lock", key: str = "id") -> None:
    """Lepas kunci milik token ini (kunci orang lain tidak disentuh)."""
    await db[coll].update_one({key: doc_id, field: token},
                              {"$set": {field: None, f"{field}_at": None}})
