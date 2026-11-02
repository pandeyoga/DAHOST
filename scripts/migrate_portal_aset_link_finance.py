"""K18 (keputusan owner 2026-11-02) — tautkan Portal Aset (`dewi_assets`) ke registri induk Keuangan
(`rahaza_fixed_assets`) dan bereskan jurnal lama Portal Aset.

Bawaan = PRATINJAU (tidak menulis apa pun). Yang dilakukan dengan --terapkan:
  1. Catatan Portal Aset yang belum tertaut → ditaut bila ada TEPAT SATU aset Keuangan yang cocok
     (no. seri sama; atau nama + harga + tanggal beli sama) dan belum ditaut catatan lain.
  2. Jurnal DRAFT dari Portal Aset (`source_module=asset_management`: pembelian Cr 1-1201, penyusutan
     6200/1590, pelepasan) → di-void (draft tidak pernah masuk buku besar, jadi saldo GL tidak berubah).
  3. Opsional --buat-saldo-awal --golive YYYY-MM-DD: catatan tanpa pasangan didaftarkan di Keuangan
     sebagai "Aset lama (saldo awal)" (akumulasi = akumulasi Portal Aset, TANPA jurnal perolehan) lalu ditaut.
Jurnal Portal Aset yang SUDAH POSTED hanya dilaporkan (perlu jurnal pembalik manual oleh Keuangan).

VPS:
  docker compose --env-file .env exec -T backend python /app/scripts/migrate_portal_aset_link_finance.py
  docker compose --env-file .env exec -T backend python /app/scripts/migrate_portal_aset_link_finance.py --terapkan
  docker compose --env-file .env exec -T backend python /app/scripts/migrate_portal_aset_link_finance.py \
      --terapkan --buat-saldo-awal --golive 2026-10-01
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(".env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# kategori Portal Aset (kode) → kategori registri Keuangan
CATEGORY_MAP = {"IT": "it", "MP": "mesin", "KD": "kendaraan", "BG": "bangunan", "PM": "furnitur",
                "AP": "peralatan", "LN": "lain-lain"}


def _norm(s):
    return " ".join(str(s or "").lower().split())


def match_candidates(asset: dict, finance: list, taken: set) -> list:
    """Kandidat aset Keuangan untuk satu catatan Portal Aset (murni — diuji unit)."""
    free = [f for f in finance if f["id"] not in taken and f.get("status") != "disposed"]
    sn = _norm(asset.get("serial_number"))
    if sn:
        by_sn = [f for f in free if _norm(f.get("serial_number")) == sn]
        if by_sn:
            return by_sn
    return [f for f in free
            if _norm(f.get("name")) == _norm(asset.get("name"))
            and round(float(f.get("purchase_cost") or 0), 2) == round(float(asset.get("purchase_cost") or 0), 2)
            and str(f.get("purchase_date") or "")[:10] == str(asset.get("purchase_date") or "")[:10]]


async def main(apply: bool, create_opening: bool, golive: str):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    finance = await db.rahaza_fixed_assets.find({}, {"_id": 0}).to_list(20000)
    linked = {a["fixed_asset_id"] async for a in db.dewi_assets.find({"fixed_asset_id": {"$nin": [None, ""]}},
                                                                     {"_id": 0, "fixed_asset_id": 1})}
    todo = await db.dewi_assets.find({"fixed_asset_id": {"$in": [None, ""]}}, {"_id": 0}).to_list(20000)
    cats = {c["id"]: c async for c in db.dewi_asset_categories.find({}, {"_id": 0})}
    print(f"DB {os.environ['DB_NAME']}: registri Keuangan {len(finance)} aset · Portal Aset belum tertaut {len(todo)} "
          f"· sudah tertaut {len(linked)}")
    plan_link, unmatched, ambiguous = [], [], []
    for a in todo:
        cand = match_candidates(a, finance, linked)
        if len(cand) == 1:
            plan_link.append((a, cand[0]))
            linked.add(cand[0]["id"])
        elif cand:
            ambiguous.append((a, cand))
        else:
            unmatched.append(a)
    for a, f in plan_link:
        print(f"  TAUT   {a.get('asset_number')} '{a.get('name')}' → {f.get('code')} '{f.get('name')}'")
    for a, cand in ambiguous:
        print(f"  RAGU   {a.get('asset_number')} '{a.get('name')}' → {len(cand)} kandidat: "
              f"{', '.join(c.get('code') for c in cand)} (taut manual di Portal Aset › edit aset)")
    for a in unmatched:
        print(f"  TANPA  {a.get('asset_number')} '{a.get('name')}' Rp {float(a.get('purchase_cost') or 0):,.0f} "
              f"akum {float(a.get('accumulated_depreciation') or 0):,.0f}"
              + (" → dibuat 'Aset lama (saldo awal)'" if create_opening else " → daftarkan di Keuangan › Aset Tetap"))

    drafts = await db.rahaza_journal_entries.find({"source_module": "asset_management", "status": "draft"},
                                                  {"_id": 0, "id": 1, "je_number": 1, "memo": 1, "total_debit": 1}).to_list(20000)
    posted = await db.rahaza_journal_entries.find({"source_module": "asset_management", "status": "posted"},
                                                  {"_id": 0, "je_number": 1, "memo": 1, "total_debit": 1}).to_list(20000)
    print(f"\nJurnal Portal Aset: draft {len(drafts)} (akan di-void) · POSTED {len(posted)} (perlu pembalik manual)")
    for je in posted:
        print(f"  POSTED {je.get('je_number')} Rp {float(je.get('total_debit') or 0):,.0f} — {je.get('memo')}")

    if not apply:
        print("\nPRATINJAU — belum ada yang ditulis. Jalankan dengan --terapkan untuk menerapkan.")
        return
    now = datetime.now(timezone.utc)
    for a, f in plan_link:
        await db.dewi_assets.update_one({"id": a["id"]}, {"$set": {
            "fixed_asset_id": f["id"], "fixed_asset_code": f.get("code"), "updated_at": now,
            "linked_by_migration": "migrate_portal_aset_link_finance"}})
    if drafts:
        await db.rahaza_journal_entries.update_many(
            {"id": {"$in": [d["id"] for d in drafts]}, "status": "draft"},
            {"$set": {"status": "voided", "voided_at": now, "voided_by": "migration",
                      "void_reason": "K18: Portal Aset tidak lagi membuat jurnal (registri induk = Keuangan)"}})
    created = 0
    if create_opening and unmatched:
        if not golive:
            print("--buat-saldo-awal butuh --golive YYYY-MM-DD; langkah 3 dilewati.")
        else:
            from routes.rahaza_fixed_assets import register_fixed_asset
            user = await db.users.find_one({"role": {"$in": ["superadmin", "admin"]}}, {"_id": 0, "id": 1, "email": 1}) \
                or {"id": "migration", "email": "migration"}
            for a in unmatched:
                cat = CATEGORY_MAP.get((cats.get(a.get("category_id")) or {}).get("code"), "lain-lain")
                body = {"name": a.get("name"), "category": cat, "acquisition_type": "opening", "golive_date": golive,
                        "purchase_date": a.get("purchase_date"), "purchase_cost": a.get("purchase_cost"),
                        "residual_value": a.get("residual_value") or 0,
                        "useful_life_months": a.get("useful_life_months") or 60,
                        "depreciation_method": a.get("depreciation_method") or "straight_line",
                        "opening_accumulated_depr": a.get("accumulated_depreciation") or 0,
                        "serial_number": a.get("serial_number"), "location": a.get("location"),
                        "notes": f"Migrasi dari Portal Aset {a.get('asset_number')}"}
                try:
                    fa = await register_fixed_asset(db, body, user)
                except Exception as e:  # noqa: BLE001 — laporkan & lanjut
                    print(f"  GAGAL  {a.get('asset_number')}: {getattr(e, 'detail', e)}")
                    continue
                await db.dewi_assets.update_one({"id": a["id"]}, {"$set": {
                    "fixed_asset_id": fa["id"], "fixed_asset_code": fa.get("code"), "updated_at": now,
                    "linked_by_migration": "migrate_portal_aset_link_finance"}})
                created += 1
    print(f"\nDITERAPKAN: tertaut {len(plan_link)} · draft di-void {len(drafts)} · aset lama dibuat {created}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--terapkan", action="store_true")
    ap.add_argument("--buat-saldo-awal", action="store_true")
    ap.add_argument("--golive", default="")
    a = ap.parse_args()
    asyncio.run(main(a.terapkan, a.buat_saldo_awal, a.golive))
