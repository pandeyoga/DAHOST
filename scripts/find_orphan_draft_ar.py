#!/usr/bin/env python3
"""T-05 — laporkan AR draft `source_module=maklon_po` yang PO-nya sudah tidak ada.

Hanya MELAPORKAN. Hapus manual setelah konfirmasi owner:
    python scripts/find_orphan_draft_ar.py            # laporan
    python scripts/find_orphan_draft_ar.py --delete   # hapus yang dilaporkan
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))


async def main(delete: bool):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    drafts = await db.rahaza_ar_invoices.find(
        {"source_module": "maklon_po", "status": "draft", "linked_maklon_po_id": {"$ne": None}},
        {"_id": 0, "id": 1, "invoice_number": 1, "linked_maklon_po_id": 1, "total": 1, "grand_total": 1},
    ).to_list(100000)
    orphan = []
    for ar in drafts:
        pid = ar["linked_maklon_po_id"]
        if await db.dewi_maklon_pos.count_documents({"id": pid}) == 0 and \
           await db.production_pos.count_documents({"id": pid}) == 0:
            orphan.append(ar)
    print(f"AR draft maklon_po: {len(drafts)} · yatim (PO tidak ada): {len(orphan)}")
    for ar in orphan:
        print(f"  - {ar.get('invoice_number') or ar['id']}  po={ar['linked_maklon_po_id']}  "
              f"total={ar.get('grand_total') or ar.get('total')}")
    if delete and orphan:
        res = await db.rahaza_ar_invoices.delete_many({"id": {"$in": [a["id"] for a in orphan]}})
        print(f"dihapus: {res.deleted_count}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--delete" in sys.argv)))
