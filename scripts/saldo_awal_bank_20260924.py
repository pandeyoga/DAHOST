"""Saldo awal KAS & BANK per 2026-09-24 — dari berkas owner `saldo_erp.xlsx` (sheet saldo_awal).

Idempoten & aman untuk PRODUKSI:
  1. Bagan akun: ganti nama 1-1219 → "Bank BCA – CV Dewi Aditya Official"; nonaktifkan 1-1215
     (catatan owner: "Rek BCA Dewi Ratnasari tolong dihapus"); tambah 4 rekening baru saldo 0.
  2. Akun kas/bank (rahaza_cash_accounts): no. rekening, atas nama, bank, opening_balance.
  3. SATU jurnal pembuka `opening_balance` (Debit bank, Kredit 3-2000 Laba Ditahan) lewat
     mesin jurnal yang sama dengan Jurnal Umum. Bila sudah ada jurnal pembuka aktif → dilewati.

    cd /app/backend && python /app/scripts/saldo_awal_bank_20260924.py --dry-run
    cd /app/backend && python /app/scripts/saldo_awal_bank_20260924.py
"""
import asyncio, os, sys
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

OB_DATE = "2026-09-24"
SOURCE_REF = "saldo_erp.xlsx (owner, 2026-09-24)"

# kode, nama, bank, no_rekening, atas_nama, saldo_awal, parent
ROWS = [
    ("1-1101", "Kas Kecil", "", "", "", 0, "1-1100"),
    ("1-1102", "Kas Besar", "", "", "", 0, "1-1100"),
    ("1-1201", "Bank BCA", "Bank BCA", "", "", 0, "1-1200"),
    ("1-1202", "Bank Mandiri", "Bank Mandiri", "", "", 0, "1-1200"),
    ("1-1211", "Bank BCA – CV Dekka Karya Utama", "Bank BCA", "392-3344558", "CV Dekka Karya Utama", 1_008_975, "1-1210"),
    ("1-1212", "Bank BCA – CV Dzaki Karya Utama", "Bank BCA", "392-4667899", "CV Dzaki Karya Utama", 1_189_311, "1-1210"),
    ("1-1213", "Bank BCA – CV Sukma Mitra Utama", "Bank BCA", "392-1122789", "CV Sukma Mitra Utama", 1_292_663, "1-1210"),
    ("1-1214", "Bank BCA – Aditya Sulistyo DW (CMT)", "Bank BCA", "392-1555545", "Aditya Sulistyo Dwi Nugroho", 569_758_137, "1-1210"),
    ("1-1219", "Bank BCA – CV Dewi Aditya Official", "Bank BCA", "392-1555545", "CV Dewi Aditya Official", 3_033_088, "1-1210"),
    ("1-1221", "Bank BRI – CV DA Official", "Bank BRI", "6873-01-000033-56-1", "CV Dewi Aditya Official", 0, "1-1220"),
    ("1-1222", "Bank BRI – CV Dekka Karya Utama", "Bank BRI", "7472-01-000021-56-5", "CV Dekka Karya Utama", 3_430_401, "1-1220"),
    ("1-1223", "Bank BRI – CV Dzaki Karya Utama", "Bank BRI", "7472-01-000020-56-9", "CV Dzaki Karya Utama", 3_692_154, "1-1220"),
    ("1-1224", "Bank BRI – CV Sukma Mitra Utama", "Bank BRI", "6873-01-000036-56-9", "CV Sukma Mitra Utama", 1_441_280, "1-1220"),
    ("1-1225", "Bank BRI – Hadi Supardi KBB", "Bank BRI", "6883-0101-7767-53-6", "Hadi Supardi", 572_921, "1-1220"),
    ("1-1251", "GoPay", "GoPay", "", "", 0, "1-1250"),
    ("1-1252", "DANA", "DANA", "", "", 0, "1-1250"),
    ("1-1253", "DANA – Lain-lain", "DANA", "", "", 0, "1-1250"),
    ("1-1254", "ShopeePay", "ShopeePay", "", "", 0, "1-1250"),
    ("1-1255", "Flazz BCA", "Flazz BCA", "", "", 0, "1-1250"),
    # Tambahan (owner) — saldo 0
    ("1-1216", "Bank BCA – Imam Sudha Apriyanto", "Bank BCA", "077-0211981", "Imam Sudha Apriyanto", 0, "1-1210"),
    ("1-1217", "Bank BCA – Dhira Arkhani", "Bank BCA", "077-0211981", "Dhira Arkhani", 0, "1-1210"),
    ("1-1226", "Bank BRI – Tutut Nurul Fatonah", "Bank BRI", "6883-0101-7767-53-6", "Tutut Nurul Fatonah", 0, "1-1220"),
    ("1-1227", "Bank BRI – Basah Purba Kusuma", "Bank BRI", "6883-0101-7767-53-6", "Basah Purba Kusuma", 0, "1-1220"),
]
DEACTIVATE = [("1-1215", "catatan owner 2026-09-24: Rek BCA Dewi Ratnasari dihapus")]


def _now():
    return datetime.now(timezone.utc)


async def main(dry: bool):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    from core.opening_balance import existing_opening, post_opening, RETAINED_EARNINGS
    log = []

    # 1) bagan akun
    for code, name, bank, norek, holder, saldo, parent in ROWS:
        acc = await db.rahaza_coa_accounts.find_one({"code": code}, {"_id": 0})
        if acc:
            patch = {}
            if acc.get("name") != name:
                patch["name"] = name
            if acc.get("active") is False:
                patch["active"] = True
            if patch:
                log.append(f"COA {code}: ubah {patch}")
                if not dry:
                    await db.rahaza_coa_accounts.update_one({"code": code}, {"$set": {**patch, "updated_at": _now()}})
        else:
            par = await db.rahaza_coa_accounts.find_one({"code": parent}, {"_id": 0})
            doc = {"id": str(uuid4()), "code": code, "name": name, "type": "ASSET", "parent_code": parent,
                   "is_group": False, "normal_balance": "DEBIT", "flags": {"bank": True}, "active": True,
                   "cash_flow_group": (par or {}).get("cash_flow_group", "OPR"),
                   "created_at": _now(), "updated_at": _now(), "created_by": "system",
                   "created_by_name": "saldo_awal_bank_20260924"}
            log.append(f"COA {code}: BARU '{name}' (induk {parent})")
            if not dry:
                await db.rahaza_coa_accounts.insert_one(doc)
    for code, why in DEACTIVATE:
        acc = await db.rahaza_coa_accounts.find_one({"code": code}, {"_id": 0})
        if acc and acc.get("active") is not False:
            log.append(f"COA {code}: NONAKTIF ({why})")
            if not dry:
                await db.rahaza_coa_accounts.update_one({"code": code}, {"$set": {"active": False, "inactive_reason": why, "updated_at": _now()}})
                await db.rahaza_cash_accounts.update_many({"gl_account_code": code}, {"$set": {"active": False, "updated_at": _now()}})

    # 2) akun kas/bank
    for code, name, bank, norek, holder, saldo, parent in ROWS:
        ca = await db.rahaza_cash_accounts.find_one({"$or": [{"gl_account_code": code}, {"code": code}]}, {"_id": 0})
        patch = {"name": name, "bank_name": bank, "account_number": norek, "account_holder": holder,
                 "opening_balance": float(saldo), "opening_balance_date": OB_DATE, "active": True, "updated_at": _now()}
        if ca:
            changed = {k: v for k, v in patch.items() if k != "updated_at" and ca.get(k) != v}
            if changed:
                log.append(f"Kas/Bank {code}: ubah {list(changed)}")
                if not dry:
                    await db.rahaza_cash_accounts.update_one({"id": ca["id"]}, {"$set": patch})
        else:
            log.append(f"Kas/Bank {code}: BARU")
            if not dry:
                await db.rahaza_cash_accounts.insert_one({"id": str(uuid4()), "code": code, "gl_account_code": code,
                                                          "type": "bank" if bank else "cash", "notes": "dari saldo_erp.xlsx",
                                                          "created_at": _now(), "created_from": "saldo_awal_bank_20260924", **patch})

    # 3) jurnal pembuka
    ex = await existing_opening(db)
    if ex:
        log.append(f"Jurnal pembuka SUDAH ADA ({ex.get('je_number')} {ex.get('date')}) — dilewati")
    else:
        lines = []
        for code, name, bank, norek, holder, saldo, parent in ROWS:
            if saldo > 0:
                lines.append({"account_code": code, "account_name": name, "account_type": "ASSET",
                              "debit": float(saldo), "credit": 0.0, "description": f"Saldo awal {name} ({norek})"})
        total = sum(l["debit"] for l in lines)
        re_acc = await db.rahaza_coa_accounts.find_one({"code": RETAINED_EARNINGS}, {"_id": 0, "name": 1})
        lines.append({"account_code": RETAINED_EARNINGS, "account_name": (re_acc or {}).get("name", "Laba Ditahan"),
                      "account_type": "EQUITY", "debit": 0.0, "credit": float(total),
                      "description": "Penyeimbang saldo awal kas & bank → Laba Ditahan"})
        log.append(f"Jurnal pembuka {OB_DATE}: {len(lines) - 1} rekening, total Rp {total:,.0f} (D bank / K {RETAINED_EARNINGS})")
        if not dry:
            user = await db.users.find_one({"role": {"$in": ["superadmin", "admin"]}, "active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1}) \
                or {"id": "system", "name": "saldo_awal_bank_20260924"}
            je = await post_opening(db, user, OB_DATE, lines, SOURCE_REF)
            log.append(f"  → {je['je_number']} terposting (D {je['total_debit']:,.0f} = K {je['total_credit']:,.0f})")

    print(("DRY-RUN — tidak ada yang ditulis\n" if dry else "") + "\n".join(log))


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
