"""Buat token masuk SEMENTARA untuk galeri layar (hanya lingkungan LOKAL).

Dijalankan di dalam container backend lokal; hasilnya JSON {token, user} ke stdout, yang langsung
dialihkan ke berkas sementara (jangan ditampilkan / ditempel ke mana pun, hapus setelah dipakai):

    docker exec -i dahost-local-backend-1 python - < scripts/ui_audit/buat_token_lokal.py > "%TEMP%/galeri_token.json"

Menolak berjalan bila konfigurasi menunjuk domain publik (VPS/produksi).
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/app/backend")
os.chdir("/app/backend")

LOCAL_HINTS = ("localhost", "127.0.0.1", ".localhost", ".test")


def _is_local() -> bool:
    vals = [os.environ.get(k, "") for k in ("BASE_URL", "CORS_ORIGINS", "WEBAUTHN_ORIGIN", "REACT_APP_BACKEND_URL")]
    vals = [v for v in vals if v]
    return bool(vals) and all(any(h in v for h in LOCAL_HINTS) for v in vals)


async def main() -> int:
    if not _is_local():
        print("DITOLAK: lingkungan ini bukan lokal (BASE_URL/CORS_ORIGINS bukan localhost).", file=sys.stderr)
        return 2
    from motor.motor_asyncio import AsyncIOMotorClient
    import auth
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    user = await db.users.find_one({"role": "superadmin", "is_active": {"$ne": False}},
                                   {"_id": 0, "password": 0, "password_hash": 0, "hashed_password": 0})
    if not user:
        print("Tidak ada pengguna superadmin di DB lokal.", file=sys.stderr)
        return 1
    safe_user = {k: user.get(k) for k in ("id", "email", "name", "role", "portals", "permissions") if k in user}
    print(json.dumps({"token": auth.create_token(user), "user": safe_user}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
