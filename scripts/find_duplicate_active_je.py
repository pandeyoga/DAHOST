#!/usr/bin/env python3
"""T-10 — laporkan JE aktif (posted/draft) yang berbagi (source_module, source_ref).

Harus 0 sebelum indeks unique `uniq_active_source_ref` bisa dibuat. Hanya melaporkan.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    dups = await db.rahaza_journal_entries.aggregate([
        {"$match": {"status": {"$in": ["posted", "draft"]}, "source_ref": {"$type": "string"}}},
        {"$group": {"_id": {"m": "$source_module", "r": "$source_ref"}, "n": {"$sum": 1},
                    "je": {"$push": {"id": "$id", "no": "$je_number", "st": "$status", "d": "$date"}}}},
        {"$match": {"n": {"$gt": 1}}},
    ]).to_list(10000)
    print(f"JE aktif duplikat per sumber: {len(dups)}")
    for d in dups:
        print(f"  - {d['_id']['m']} / {d['_id']['r']} ×{d['n']}: " +
              ", ".join(f"{j['no']}({j['st']},{j['d']})" for j in d["je"]))
    idx = await db.rahaza_journal_entries.index_information()
    print("indeks uniq_active_source_ref:", "ADA" if "uniq_active_source_ref" in idx else "BELUM")
    return 1 if dups else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
