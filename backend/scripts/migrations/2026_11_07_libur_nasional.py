"""Migrasi 2026-11-07 (Tahap 4, pola P5) — betulkan baris libur nasional yang ditulis preset lama.

KENAPA: tombol "Isi libur nasional 2026" dulu menulis daftar `NATIONAL_HOLIDAYS_2026` berlabel "contoh" dengan
tanggal yang SALAH (Idul Fitri 6–7 Apr, cuti bersama 2–3 & 8–9 Apr, Nyepi 14 Mar, Isra Mikraj 27 Jan, Imlek 29 Jan,
Wafat Yesus 20 Mar, Waisak 24 Mei, Iduladha 13 Jun, 1 Muharam 3 Jul, Maulid 12 Sep). Baris itu bertipe `holiday`
sehingga mengurangi hari kerja payroll/cuti (`core.workdays`) di tanggal yang salah, dan libur yang benar
(mis. Idulfitri 21–22 Mar) tidak ada.

Preset baru: `core.national_holidays` (SKB 3 Menteri 2026 & 2027).

Yang dilakukan — HANYA baris buatan preset lama (`created_by='system'`, tanggal + nama = daftar lama):
  1. Tanggal lama yang juga ada di preset baru → nama/jenis/catatan diselaraskan dengan SKB.
  2. Tanggal lama yang TIDAK ada di preset baru (tanggal salah) → baris dihapus.
  3. Tahun yang pernah diisi preset lama → tanggal preset baru yang belum punya entri ditambahkan.
Entri buatan pengguna tidak pernah diubah atau dihapus; bila entri pengguna sudah ada di tanggal preset, tanggal
itu dilewati (dilaporkan).
Gaji yang sudah final TIDAK dihitung ulang (hanya kalender yang dibetulkan).

Sifat: idempoten, hanya mencetak hitungan. Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu).

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_libur_nasional.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_libur_nasional.py --apply
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import national_holidays as nh  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

# Salinan PERSIS daftar lama (routes/rahaza_production_calendar.py sebelum 2026-11-06) — tanda pengenal baris.
OLD_PRESET_2026 = {
    "2026-01-01": "Tahun Baru Masehi",
    "2026-01-27": "Isra Miraj Nabi Muhammad SAW",
    "2026-01-29": "Tahun Baru Imlek",
    "2026-03-14": "Hari Raya Nyepi",
    "2026-03-20": "Wafat Yesus Kristus",
    "2026-04-02": "Cuti Bersama Lebaran",
    "2026-04-03": "Cuti Bersama Lebaran",
    "2026-04-06": "Hari Raya Idul Fitri",
    "2026-04-07": "Hari Raya Idul Fitri",
    "2026-04-08": "Cuti Bersama Idul Fitri",
    "2026-04-09": "Cuti Bersama Idul Fitri",
    "2026-05-01": "Hari Buruh Internasional",
    "2026-05-14": "Kenaikan Yesus Kristus",
    "2026-05-24": "Hari Raya Waisak",
    "2026-06-01": "Hari Lahir Pancasila",
    "2026-06-13": "Hari Raya Idul Adha",
    "2026-07-03": "Tahun Baru Islam 1448 H",
    "2026-08-17": "Hari Kemerdekaan RI",
    "2026-09-12": "Maulid Nabi Muhammad SAW",
    "2026-12-25": "Hari Raya Natal",
}
SYNC_FIELDS = ("name", "kind", "perkiraan", "preset_source", "notes")


def is_old_preset_row(r: dict) -> bool:
    d = str(r.get("date") or "")[:10]
    return r.get("created_by") == "system" and OLD_PRESET_2026.get(d) == r.get("name")


def plan(rows: list) -> dict:
    """Rencana murni (tanpa DB). `rows` = semua entri kalender di tahun yang bersangkutan.

    Return {"update": [{id, set}], "delete": [id], "insert": [preset_row], "skip_manual": n, "years": [...]}."""
    out = {"update": [], "delete": [], "insert": [], "skip_manual": 0, "years": []}
    old = [r for r in rows if is_old_preset_row(r)]
    years = sorted({int(str(r["date"])[:4]) for r in old})
    out["years"] = years
    presets = {}
    for y in years:
        for h in nh.holidays_for(y) or []:
            presets[h["date"]] = h
    deleted = set()
    for r in old:
        d = str(r["date"])[:10]
        h = presets.get(d)
        if h is None:
            out["delete"].append(r["id"])
            deleted.add(r["id"])
            continue
        want = nh.calendar_doc(h, uid=r["id"], now_iso="")
        upd = {k: want[k] for k in SYNC_FIELDS if r.get(k) != want[k]}
        if upd:
            out["update"].append({"id": r["id"], "set": upd})
    taken = {str(r.get("date"))[:10]: r for r in rows if r.get("id") not in deleted}
    for d, h in sorted(presets.items()):
        r = taken.get(d)
        if r is None:
            out["insert"].append(h)
        elif r.get("created_by") != "system":
            out["skip_manual"] += 1
    return out


async def run(apply: bool, db=None) -> dict:
    if db is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[libur-nasional] DB={DB_NAME} · {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    old_years = sorted({int(d[:4]) for d in OLD_PRESET_2026})
    rows = [r async for r in db.rahaza_production_calendar.find(
        {"year": {"$in": old_years}}, {"_id": 0})]
    p = plan(rows)
    now = datetime.now(timezone.utc)
    if apply:
        for u in p["update"]:
            await db.rahaza_production_calendar.update_one(
                {"id": u["id"]}, {"$set": {**u["set"], "updated_at": now.isoformat(),
                                           "updated_by": "migrasi_libur_nasional_2026_11_07"}})
        for rid in p["delete"]:
            await db.rahaza_production_calendar.delete_one({"id": rid, "created_by": "system"})
        docs = [nh.calendar_doc(h, uid=str(uuid.uuid4()), now_iso=now.isoformat()) for h in p["insert"]]
        if docs:
            await db.rahaza_production_calendar.insert_many(docs)
    verb = "" if apply else "akan "
    totals = {"years": p["years"], "updated": len(p["update"]), "deleted": len(p["delete"]),
              "inserted": len(p["insert"]), "skip_manual": p["skip_manual"]}
    print(f"  tahun yang pernah diisi preset lama: {', '.join(map(str, p['years'])) or '-'}")
    print(f"  baris preset lama {verb}diselaraskan dengan SKB: {totals['updated']}")
    print(f"  baris preset lama bertanggal salah {verb}dihapus: {totals['deleted']}")
    print(f"  tanggal SKB yang belum ada {verb}ditambahkan: {totals['inserted']}")
    print(f"  tanggal SKB yang sudah berisi entri manual (dilewati): {totals['skip_manual']}")
    return totals


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    asyncio.run(run(ap.parse_args().apply))
    sys.exit(0)
