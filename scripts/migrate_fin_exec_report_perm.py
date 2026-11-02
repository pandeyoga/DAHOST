"""K33 (keputusan owner 2026-11-02) — izin awal modul baru `fin_exec_report` (Laporan Eksekutif).

Modul ini dipisah dari `fin_dashboard`. Peran yang izin per modul Portal Keuangan-nya SUDAH diatur owner
(punya kunci `mod.fin_*`) dan sebelumnya bisa membuka Laporan Eksekutif lewat `mod.fin_dashboard.view`
akan kehilangan akses setelah pemisahan (aturan "fallback aman": portal granular → wajib centang).
Skrip ini memberi `mod.fin_exec_report.view` (+ `.export` bila punya `mod.fin_dashboard.export`) HANYA
untuk peran bawaan Manajemen + Keuangan (default izin awal owner) yang punya `mod.fin_dashboard.view`.
Peran lain tidak disentuh (owner mengatur lewat Manajemen Role). Idempoten.

Peran tanpa izin per modul Keuangan tidak perlu apa-apa (penjaga handler memberi akses bawaan ke peran
ber-Portal Manajemen/Keuangan).

VPS:
  docker compose --env-file .env exec -T backend python /app/scripts/migrate_fin_exec_report_perm.py             # pratinjau
  docker compose --env-file .env exec -T backend python /app/scripts/migrate_fin_exec_report_perm.py --terapkan
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(".env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def keys_to_add(role_name: str, keys: set, default_roles: set) -> list:
    """Kunci baru untuk satu peran (murni — diuji unit)."""
    if role_name not in default_roles or "mod.fin_dashboard.view" not in keys:
        return []
    want = ["mod.fin_exec_report.view"]
    if "mod.fin_dashboard.export" in keys:
        want.append("mod.fin_exec_report.export")
    return [k for k in want if k not in keys]


async def main(apply: bool):
    from routes.shared import PORTAL_ACCESS
    default_roles = set(PORTAL_ACCESS["management"]) | set(PORTAL_ACCESS["finance"])
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    total = 0
    async for role in db.roles.find({}, {"_id": 0, "id": 1, "name": 1}):
        keys = {r["permission_key"] async for r in db.role_permissions.find({"role_id": role["id"]},
                                                                            {"_id": 0, "permission_key": 1})}
        add = keys_to_add(role.get("name"), keys, default_roles)
        if not add:
            continue
        total += len(add)
        print(f"  {role['name']}: + {', '.join(add)}")
        if apply:
            await db.role_permissions.insert_many([{"id": str(uuid.uuid4()), "role_id": role["id"], "permission_key": k,
                                                    "created_at": datetime.now(timezone.utc),
                                                    "created_by": "migrate_fin_exec_report_perm"} for k in add])
    print(f"{'DITERAPKAN' if apply else 'PRATINJAU'}: {total} izin " + ("ditambahkan." if apply else "akan ditambahkan (--terapkan)."))


if __name__ == "__main__":
    asyncio.run(main("--terapkan" in sys.argv))
