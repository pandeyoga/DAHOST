#!/usr/bin/env python3
"""Akun uji per peran (`uji.{role}@dewiaditya.id` / `Dewi@123`) — untuk matriks RBAC testing agent.

Idempoten; TIDAK menyentuh akun karyawan nyata. Jalankan ulang setelah restore seed:
    cd /app/backend && python ../scripts/seed_test_accounts.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from auth import hash_password  # noqa: E402

ROLES = ("accounting", "staff_keuangan", "hr", "hr_manager", "manager", "owner", "admin",
         "admin_produksi", "supervisor_produksi", "admin_gudang", "rnd_staff", "operator",
         "admin_maklon", "klien_maklon", "cmt_vendor", "vendor", "buyer", "pic_toko",
         "marketing_kol", "cs_staff")
PASSWORD = "Dewi@123"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)
    pw = hash_password(PASSWORD)
    for role in ROLES:
        email = f"uji.{role}@dewiaditya.id"
        await db.users.update_one({"email": email}, {"$set": {
            "email": email, "name": f"Akun Uji {role}", "role": role, "status": "active",
            "is_active": True, "password": pw, "must_change_password": False,
            "is_test_account": True, "updated_at": now,
        }, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}}, upsert=True)
        print("ok", email, role)


if __name__ == "__main__":
    asyncio.run(main())
