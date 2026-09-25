"""Cek rekening yang terbaca di pemilih Rekening Pencairan (Finance). Read-only.

VPS: docker compose --env-file .env exec -T backend python /app/scripts/cek_rekening_pencairan.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from core.payout_banks import bank_options  # noqa: E402


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    opts = await bank_options(db)
    shown = {o["code"] for o in opts}
    print(f"TERBACA di pemilih rekening: {len(opts)}")
    for o in opts:
        print(f"  ✓ {o['code']:<18} {o['name']:<45} {o['account_number']}")
    missing = [c async for c in db.rahaza_cash_accounts.find({}, {"_id": 0})
               if c.get("gl_account_code") not in shown]
    if missing:
        print(f"\nTIDAK terbaca dari master Kas & Bank: {len(missing)}")
        for c in missing:
            why = ("nonaktif" if c.get("active") is False else
                   "belum ditautkan ke akun GL/COA" if not c.get("gl_account_code") else
                   "akun GL nonaktif / grup / bukan akun kas-bank")
            print(f"  ✗ {c.get('code'):<18} {c.get('name'):<45} → {why}")
    stores = [s async for s in db.marketing_platform_accounts.find(
        {}, {"_id": 0, "account_name": 1, "coa_cash_code": 1})]
    print("\nRekening pencairan per toko:")
    for s in stores:
        c = s.get("coa_cash_code")
        print(f"  {'✓' if c in shown else '✗'} {s.get('account_name'):<30} {c or '(belum ditautkan)'}")


asyncio.run(main())
