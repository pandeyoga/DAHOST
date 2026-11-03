"""Siapkan database DEMO (subdomain demo) sesudah data dipulihkan — HANYA untuk DB bernama *demo*.

Keputusan owner 2026-11-03: data demo = salinan data simulasi lokal APA ADANYA, dilindungi kata sandi
pintu (basic auth di Caddy) + SEMUA kata sandi akun diganti. Skrip ini:
  1. mengganti kata sandi semua akun `users` dengan DEMO_PASSWORD (dan mencabut wajib-ganti-sandi);
  2. mengosongkan percobaan login & kredensial WebAuthn (sidik jari/kunci perangkat dari salinan lama);
  3. mematikan notifikasi WhatsApp/email & mengosongkan kunci integrasi (tidak ada pesan ke orang asli).

    python /app/scripts/demo_prepare.py              → pratinjau (tidak menulis)
    DEMO_PASSWORD='...' python /app/scripts/demo_prepare.py --terapkan

Penjaga: menolak jalan bila DB_NAME tidak memuat kata "demo" — tidak mungkin mengenai database produksi.
"""
import os
import sys

from pymongo import MongoClient

sys.path.insert(0, "/app/backend")

APPLY = "--terapkan" in sys.argv
DB_NAME = os.environ.get("DB_NAME", "")
# kunci rahasia di Adm. Sistem (dewi_system_config) — nama persis, bukan pola, supaya angka/opsi lain tidak ikut kosong
SECRET_KEYS = ("notification_whatsapp_api_key", "notification_telegram_bot_token", "marketplace_tokopedia_client_secret",
               "smtp_password", "anthropic_api_key")


def main():
    if "demo" not in DB_NAME.lower():
        sys.exit(f"DITOLAK: DB_NAME '{DB_NAME}' bukan database demo. Skrip ini hanya untuk DB bernama *demo*.")
    db = MongoClient(os.environ["MONGO_URL"])[DB_NAME]
    pw = os.environ.get("DEMO_PASSWORD", "")
    n_users = db.users.count_documents({})
    cfg_off = list(db.dewi_system_config.find({"key": {"$regex": "notification_(whatsapp|email)_enabled"}},
                                              {"_id": 0, "key": 1, "value": 1}))
    cfg_secret = list(db.dewi_system_config.find({"key": {"$in": list(SECRET_KEYS)}, "value": {"$nin": ["", None]}},
                                                 {"_id": 0, "key": 1}))
    print(f"DB {DB_NAME}: {n_users} akun, {db.login_attempts.count_documents({})} percobaan login, "
          f"{db.rahaza_webauthn_credentials.count_documents({})} kredensial WebAuthn")
    print("notifikasi dimatikan:", [c["key"] for c in cfg_off] or "-", "| kunci dikosongkan:", [c["key"] for c in cfg_secret] or "-")
    if not APPLY:
        print("PRATINJAU — tidak ada yang ditulis. Jalankan ulang dengan DEMO_PASSWORD=... dan --terapkan.")
        return
    if len(pw) < 12:
        sys.exit("DEMO_PASSWORD wajib diisi, minimal 12 karakter.")
    from auth import hash_password
    hashed = hash_password(pw)
    r = db.users.update_many({}, {"$set": {"password": hashed, "must_change_password": False}})
    for coll in ("login_attempts", "client_login_attempts", "marketing_kol_login_attempts",
                 "rahaza_webauthn_credentials", "rahaza_webauthn_challenges"):
        db[coll].delete_many({})
    db.dewi_system_config.update_many({"key": {"$regex": "notification_(whatsapp|email)_enabled"}},
                                      {"$set": {"value": False}})
    db.dewi_system_config.update_many({"key": {"$in": list(SECRET_KEYS)}}, {"$set": {"value": ""}})
    print(f"SELESAI: kata sandi {r.modified_count} akun diganti; login lama, WebAuthn, notifikasi WA/email & kunci integrasi dikosongkan.")


if __name__ == "__main__":
    main()
