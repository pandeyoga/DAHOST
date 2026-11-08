#!/usr/bin/env python3
"""scripts/reset_for_golive.py — KOSONGKAN data lama sebelum impor data nyata.

    python3 scripts/reset_for_golive.py                 # DRY-RUN: hanya melaporkan rencana
    python3 scripts/reset_for_golive.py --apply         # mongodump dulu, lalu hapus
    python3 scripts/reset_for_golive.py --apply --yes   # tanpa konfirmasi interaktif

Keputusan owner (2026-09): SEMUA koleksi dikosongkan KECUALI konfigurasi sistem:
  users (hanya superadmin dipertahankan), roles, role_permissions, COA + posting profiles,
  company_settings, master satuan gudang, penomoran dokumen, template PDF, konfigurasi
  notifikasi. Superadmin `admin@garment.com` tidak disentuh (sandi tetap).

Pengaman:
  * Dry-run bawaan; `--apply` WAJIB didahului mongodump ke /app/backups/pre_golive_<waktu>/
    (gagal backup = berhenti). Restore: `mongorestore --uri "$MONGO_URL" --db "$DB_NAME" <folder>`.
  * Koleksi yang dipertahankan dicetak eksplisit; tidak ada pola regex "kira-kira".

MODE CUTOFF "HAPUS TRANSAKSI SAJA" (keputusan owner 2026-11-06, T5):

    python3 scripts/reset_for_golive.py --transaksi-saja                  # DRY-RUN per jenis koleksi
    python3 scripts/reset_for_golive.py --transaksi-saja --reset-nomor    # + nomor dokumen mulai dari 1
    python3 scripts/reset_for_golive.py --transaksi-saja --apply --yes    # mongodump, lalu ketik HAPUS TRANSAKSI

  * Jenis tiap koleksi (konfigurasi / master / transaksi / log) dibaca dari
    `backend/core/collection_registry.py` (KIND). Transaksi + log DIHAPUS; konfigurasi + master
    (termasuk SEMUA pengguna) dipertahankan. Koleksi yang belum diklasifikasi = skrip MENOLAK jalan.
  * Field turunan di master (cache stok katalog, saldo awal kas, cuti terpakai, ...) dikembalikan ke
    keadaan pembukaan sesuai `DERIVED_FIELDS`; `unit_cost` / HPP master TIDAK disentuh.
  * Nomor dokumen DILANJUTKAN, kecuali `--reset-nomor` (hanya penghitung milik koleksi transaksi/log).
  * `--apply` di mode ini WAJIB `--yes` DAN konfirmasi ketik `HAPUS TRANSAKSI` (boleh lewat stdin),
    serta mongodump ke backups/pre_cutoff_<waktu>/ lebih dulu.
  * `--cakupan operasional` (keputusan owner 2026-11-07): HANYA transaksi produksi, gudang/stok, pembelian,
    dan keuangan yang dihapus; Marketing, SDM, aset, RnD, dan semua log DIPERTAHANKAN
    (`core.cutoff_reset.deleted_in_scope`). `--reset-nomor` tidak berlaku di cakupan ini.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = ROOT / "backups"

KEEP_COLLECTIONS = (
    "roles", "role_permissions", "role_access_overrides",
    "rahaza_coa_accounts", "rahaza_posting_profiles", "chart_of_accounts",
    "company_settings", "company_profile",
    "wh_unit_master", "wh_unit_conversions",
    "doc_number_configs", "pdf_templates",
    "notif_category_config", "notification_settings", "notification_providers",
    "backup_config",
)
SUPERADMIN_EMAIL = os.environ.get("SUPERADMIN_EMAIL", "admin@garment.com")
G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m"


async def plan(db) -> tuple[list[tuple[str, int]], list[tuple[str, int]], int]:
    names = sorted(n for n in await db.list_collection_names() if not n.startswith("system."))
    wipe, keep = [], []
    for n in names:
        c = await db[n].count_documents({})
        (keep if n in KEEP_COLLECTIONS else wipe).append((n, c))
    other_users = await db.users.count_documents({"email": {"$ne": SUPERADMIN_EMAIL}})
    wipe = [(n, c) for n, c in wipe if n != "users"]
    return wipe, keep, other_users


def mongodump(uri: str, dbname: str, label: str = "pre_golive") -> Path:
    dest = BACKUP_ROOT / f"{label}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["mongodump", f"--uri={uri}", f"--db={dbname}", f"--out={dest}", "--gzip", "--quiet"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if res.returncode != 0 or not any((dest / dbname).glob("*.bson*")):
        raise SystemExit(f"{R}mongodump GAGAL — reset dibatalkan.{X}\n{res.stderr[-800:]}")
    return dest


CUTOFF_CONFIRM = "HAPUS TRANSAKSI"


def print_cutoff_plan(p: dict, dbname: str, apply: bool) -> None:
    """Tabel rencana cutoff per jenis koleksi: nama, jumlah dokumen, nasibnya."""
    from core import collection_registry as cr
    print(f"{B}Basis data :{X} {dbname}\n{B}Mode       :{X} HAPUS TRANSAKSI SAJA — "
          + (f"{R}EKSEKUSI (--apply){X}" if apply else f"{G}DRY-RUN (rencana saja){X}"))
    for kind in cr.KINDS:
        rows = p["classes"][kind]
        hapus = kind in cr.KINDS_DIHAPUS
        nasib = f"{R}DIHAPUS{X}" if hapus else f"{G}DIPERTAHANKAN{X}"
        isi = sum(r["count"] for r in rows)
        print(f"\n{B}{cr.KIND_LABEL[kind].upper()}{X} — {nasib} · {len(rows)} koleksi · {isi} dokumen")
        for r in rows:
            if r["count"] or not hapus:
                print(f"  {r['name']:40s} {r['count']:8d}")
    keep_scope = p["classes"].get("dipertahankan") or []
    if p.get("scope") and p["scope"] != "semua":
        from core.cutoff_reset import SCOPE_LABEL
        isi = sum(r["count"] for r in keep_scope)
        print(f"\n{B}CAKUPAN{X}: {SCOPE_LABEL.get(p['scope'], p['scope'])}")
        print(f"{B}TRANSAKSI & LOG DI LUAR CAKUPAN{X} — {G}DIPERTAHANKAN{X} · {len(keep_scope)} koleksi · {isi} dokumen")
        for r in keep_scope:
            if r["count"]:
                print(f"  {r['name']:40s} {r['count']:8d}  ({cr.KIND_LABEL.get(r['kind'], r['kind'])})")
    if p["unknown"]:
        print(f"\n{R}{B}BELUM DIKLASIFIKASI{X} ({len(p['unknown'])} koleksi) — skrip menolak berjalan:")
        for r in p["unknown"]:
            print(f"  {r['name']:40s} {r['count']:8d}")
    print(f"\n{B}FIELD TURUNAN DI MASTER{X}")
    for d in p["derived"]:
        what = ((d["special"] or ", ".join(d["fields"])) if d["action"] == "reset"
                else "tetap: " + ", ".join(d["keep"]))
        tag = f"{Y}reset{X}" if d["action"] == "reset" else "tetap"
        print(f"  {d['collection']:32s} {d['docs']:6d} dok · {tag} · {what}")
    c = p["counters"]
    print(f"\n{B}NOMOR DOKUMEN{X} — " + (
        f"{Y}--reset-nomor: {len(c['reset'])} penghitung transaksi dihapus{X}, {len(c['keep'])} tetap"
        if p["reset_nomor"] else f"dilanjutkan ({len(c['keep']) + len(c['unknown'])} penghitung tidak disentuh)"))
    if p["reset_nomor"] and c["unknown"]:
        print(f"  {R}penghitung tidak dikenal:{X} " + ", ".join(r["key"] for r in c["unknown"][:20]))
    t = p["totals"]
    print(f"\n  Dokumen dihapus: {B}{t['hapus']}{X} · dipertahankan: {B}{t['pertahankan']}{X} "
          f"· koleksi: {t['koleksi']}")


async def main_transaksi_saja(apply: bool, yes: bool, reset_nomor: bool, scope: str = "semua") -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
    sys.path.insert(0, str(ROOT / "backend"))
    from core import cutoff_reset
    from motor.motor_asyncio import AsyncIOMotorClient
    uri, dbname = os.environ["MONGO_URL"], os.environ["DB_NAME"]
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
    try:
        db = client[dbname]
        p = await cutoff_reset.build_plan(db, reset_nomor=reset_nomor, scope=scope)
        print_cutoff_plan(p, dbname, apply)
        reasons = cutoff_reset.refusal_reasons(p)
        if reasons:
            print(f"\n{R}DITOLAK:{X} " + "\n  ".join(reasons))
            return 2
        if not apply:
            print(f"\n{G}Dry-run selesai — tidak ada yang diubah.{X} Jalankan dengan --apply --yes untuk mengeksekusi.")
            return 0
        if not yes:
            print(f"\n{R}--apply di mode transaksi-saja wajib disertai --yes.{X}")
            return 1
        ans = input(f"\nKetik {B}{CUTOFF_CONFIRM}{X} untuk melanjutkan (mongodump dibuat lebih dulu): ").strip()
        if ans != CUTOFF_CONFIRM:
            print("Dibatalkan.")
            return 1
        dest = mongodump(uri, dbname, label="pre_cutoff")
        print(f"{G}Backup mongodump:{X} {dest}")
        # rencana dihitung ulang sesudah backup — yang dihapus = yang ada di cadangan
        p = await cutoff_reset.build_plan(db, reset_nomor=reset_nomor, scope=scope)
        res = await cutoff_reset.apply_plan(db, p)
        print(f"\n{G}{B}CUTOFF SELESAI.{X} {res['deleted_total']} dokumen transaksi/log dihapus dari "
              f"{len(res['deleted'])} koleksi; field turunan direset di {len(res['derived'])} koleksi; "
              f"{res['counters_reset']} penghitung nomor direset.")
        print(f"Pulihkan bila perlu: mongorestore --uri \"$MONGO_URL\" --gzip --nsInclude '{dbname}.*' "
              f"--drop {dest}")
        print(f"{Y}Restart backend sesudah cutoff, lalu isi saldo awal (kas/bank, persediaan, WIP, "
              f"piutang/hutang) dan impor PO berjalan.{X}")
        return 0
    finally:
        client.close()


async def main(apply: bool, yes: bool) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
    from motor.motor_asyncio import AsyncIOMotorClient
    uri, dbname = os.environ["MONGO_URL"], os.environ["DB_NAME"]
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
    try:
        db = client[dbname]
        sa = await db.users.find_one({"email": SUPERADMIN_EMAIL}, {"_id": 0, "role": 1})
        if not sa or sa.get("role") != "superadmin":
            print(f"{R}Superadmin '{SUPERADMIN_EMAIL}' tidak ditemukan/bukan superadmin — reset ditolak "
                  f"agar sistem tidak kehilangan akses.{X}")
            return 1
        wipe, keep, other_users = await plan(db)
        print(f"{B}Basis data :{X} {dbname}\n{B}Mode       :{X} "
              + (f"{R}HAPUS (--apply){X}" if apply else f"{G}DRY-RUN (rencana saja){X}"))
        print(f"\n{B}DIPERTAHANKAN{X} ({len(keep)} koleksi)")
        for n, c in keep:
            print(f"  {n:36s} {c:7d}")
        print(f"  {'users (hanya superadmin)':36s} {1:7d}")
        print(f"\n{B}DIKOSONGKAN{X} ({len(wipe)} koleksi + {other_users} user non-superadmin)")
        total = other_users
        for n, c in wipe:
            total += c
            if c:
                print(f"  {n:36s} {c:7d}")
        print(f"\n  Total dokumen yang akan dihapus: {B}{total}{X}")
        if not apply:
            print(f"\n{G}Dry-run selesai — tidak ada yang diubah.{X} Jalankan dengan --apply untuk mengeksekusi.")
            return 0
        if not yes:
            ans = input(f"\nKetik {B}HAPUS{X} untuk melanjutkan (mongodump dibuat lebih dulu): ").strip()
            if ans != "HAPUS":
                print("Dibatalkan.")
                return 1
        dest = mongodump(uri, dbname)
        print(f"{G}Backup mongodump:{X} {dest}")
        removed = 0
        for n, c in wipe:
            if c:
                removed += (await db[n].delete_many({})).deleted_count
        removed += (await db.users.delete_many({"email": {"$ne": SUPERADMIN_EMAIL}})).deleted_count
        await db.login_attempts.delete_many({})
        print(f"\n{G}{B}RESET SELESAI.{X} {removed} dokumen dihapus. Koleksi konfigurasi dan superadmin utuh.")
        print(f"Pulihkan bila perlu: mongorestore --uri \"$MONGO_URL\" --gzip --nsInclude '{dbname}.*' "
              f"--drop {dest}")
        print(f"{Y}Restart backend setelah reset supaya seed startup (COA/roles/proses) berjalan ulang.{X}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true", help="lewati konfirmasi interaktif")
    ap.add_argument("--transaksi-saja", action="store_true",
                    help="cutoff: hapus transaksi & log saja, pertahankan konfigurasi & master")
    ap.add_argument("--reset-nomor", action="store_true",
                    help="(dengan --transaksi-saja) nomor dokumen transaksi mulai dari 1 lagi")
    ap.add_argument("--cakupan", choices=("semua", "operasional"), default="semua",
                    help="(dengan --transaksi-saja) operasional = produksi, gudang/stok, pembelian & keuangan saja")
    a = ap.parse_args()
    if a.reset_nomor and not a.transaksi_saja:
        ap.error("--reset-nomor hanya berlaku bersama --transaksi-saja")
    if a.cakupan != "semua" and not a.transaksi_saja:
        ap.error("--cakupan hanya berlaku bersama --transaksi-saja")
    if a.cakupan == "operasional" and a.reset_nomor:
        ap.error("--reset-nomor tidak berlaku untuk --cakupan operasional (nomor dokumen dilanjutkan)")
    if a.transaksi_saja:
        sys.exit(asyncio.run(main_transaksi_saja(a.apply, a.yes, a.reset_nomor, a.cakupan)))
    sys.exit(asyncio.run(main(a.apply, a.yes)))
