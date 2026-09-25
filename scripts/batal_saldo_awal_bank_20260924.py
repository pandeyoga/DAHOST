"""Batalkan jurnal pembuka dari `saldo_awal_bank_20260924.py` dengan JURNAL PEMBALIK (nominal sama, D/K ditukar).

Jurnal asli tidak dihapus/di-void (jejak audit tetap ada, dan skrip saldo awal tidak akan memposting ulang).
Idempoten: bila jurnal pembalik sudah ada → dilewati.

VPS:
  docker compose --env-file .env exec -T backend python /app/scripts/batal_saldo_awal_bank_20260924.py            # pratinjau
  docker compose --env-file .env exec -T backend python /app/scripts/batal_saldo_awal_bank_20260924.py --terapkan # posting pembalik
"""
import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(".env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

SOURCE_REF = "saldo_erp.xlsx (owner, 2026-09-24)"
REV_MODULE = "opening_balance_reversal"


async def gl(db, codes):
    rows = await db.rahaza_journal_lines.aggregate([
        {"$match": {"account_code": {"$in": codes}}},
        {"$group": {"_id": "$account_code", "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}}]).to_list(None)
    return {r["_id"]: round(r["d"] - r["c"]) for r in rows}


async def main(apply: bool):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    je = await db.rahaza_journal_entries.find_one(
        {"source_module": "opening_balance", "source_ref": SOURCE_REF, "status": {"$ne": "voided"}}, {"_id": 0})
    if not je:
        print("Jurnal pembuka dari skrip saldo awal 2026-09-24 TIDAK ditemukan — tidak ada yang perlu dibalik.")
        return
    ref = f"reverse:{je['id']}"
    done = await db.rahaza_journal_entries.find_one(
        {"source_module": REV_MODULE, "source_ref": ref, "status": {"$ne": "voided"}}, {"_id": 0, "je_number": 1})
    codes = [ln["account_code"] for ln in je["lines"]]
    bal = await gl(db, codes)
    print(f"Jurnal asli: {je['je_number']} tgl {je['date']} total Rp {je['total_debit']:,.0f}")
    print(f"{'Akun':<10} {'Nama':<42} {'Dibalik D':>14} {'Dibalik K':>14} {'Saldo GL kini':>15} {'Setelah':>15}")
    for ln in je["lines"]:
        now = bal.get(ln["account_code"], 0)
        after = now - ln["debit"] + ln["credit"]
        print(f"{ln['account_code']:<10} {ln['account_name'][:42]:<42} {ln['credit']:>14,.0f} {ln['debit']:>14,.0f} "
              f"{now:>15,.0f} {after:>15,.0f}")
    if done:
        print(f"\nJurnal pembalik SUDAH ADA ({done['je_number']}) — dilewati.")
        return
    if not apply:
        print("\nPRATINJAU — belum ada yang ditulis. Jalankan dengan --terapkan untuk memposting jurnal pembalik.")
        return
    from routes.rahaza_posting import _create_posted_je
    user = await db.users.find_one({"role": {"$in": ["superadmin", "admin"]}, "active": {"$ne": False}},
                                   {"_id": 0, "id": 1, "name": 1}) or {"id": "system", "name": "batal_saldo_awal"}
    lines = [{"account_code": ln["account_code"], "debit": ln["credit"], "credit": ln["debit"],
              "description": f"Pembalik {je['je_number']}: {ln.get('description') or ''}".strip()} for ln in je["lines"]]
    res = await _create_posted_je(db, date.fromisoformat(je["date"]),
                                  f"Pembalik saldo awal ganda {je['je_number']} (skrip saldo_awal_bank_20260924)",
                                  REV_MODULE, ref, lines, user, allow_closed_period=True)
    if not res.get("ok"):
        print(f"GAGAL: {res.get('error')}")
        sys.exit(1)
    await db.rahaza_journal_entries.update_one({"id": je["id"]}, {"$set": {
        "flags.reversed": True, "reversed_by_je_id": res["je_id"], "reversed_by_je_number": res["je_number"]}})
    print(f"\n✓ Jurnal pembalik {res['je_number']} terposting (nominal sama, D/K ditukar).")


if __name__ == "__main__":
    asyncio.run(main("--terapkan" in sys.argv))
