#!/usr/bin/env python3
"""FASE 3.1 (T-03/T-17): koleksi yang DIBACA kode wajib punya ≥1 PENULIS.

Membaca `db.<nama>.find/find_one/count_documents/aggregate/distinct` tanpa ada
`db.<nama>.insert_*/update_*/replace_one/bulk_write/find_one_and_update` di
`routes/ core/ services/ utils/` = koleksi hantu (dashboard/laporan selalu 0).

Pakai:
  python3 scripts/check_collection_writers.py            # laporan
  python3 scripts/check_collection_writers.py --gate     # exit 1 bila ada temuan di luar daftar putih
  python3 scripts/check_collection_writers.py --set-baseline
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
SCAN_DIRS = ("routes", "core", "services", "utils")
# Penulis juga sah bila berada di: server.py (seed/indeks), auth.py, migrations/, seed_*.py, scripts/
WRITER_EXTRA = ("server.py", "auth.py", "database.py", "migrations", "scripts")
BASELINE = os.path.join(ROOT, "scripts", "collection_writers_baseline.txt")

READ_RX = re.compile(r"\bdb\.([a-z][a-z0-9_]+)\.(find|find_one|count_documents|aggregate|distinct|estimated_document_count)\(")
WRITE_RX = re.compile(r"\bdb\.([a-z][a-z0-9_]+)\.(insert_one|insert_many|update_one|update_many|replace_one|bulk_write|find_one_and_update|find_one_and_replace|delete_one|delete_many)\(")
# penulis lewat nama literal: db["nama"] / db.get_collection("nama") / getattr(db, "nama")
LITERAL_COLL_RX = re.compile(r"""\bdb(?:\[|\.get_collection\(|,\s*)?\s*["']([a-z][a-z0-9_]+)["']""")
# nama koleksi yang ditulis lewat variabel/mesin deklaratif (impor Excel, registry, backup) → daftar putih
DYNAMIC_WRITER_RX = re.compile(r"\bdb\[[^\]]+\]\.(insert|update|replace|bulk)")

# Koleksi yang sah tanpa penulis statis (ditulis mesin impor deklaratif / migrasi / eksternal / registry).
WHITELIST = {
    "system_counters": "utils.counters lewat db[namespace]",
}


def _iter_py(base: str):
    for dirpath, _, files in os.walk(base):
        if "_archive" in dirpath or "__pycache__" in dirpath or ".pre-refactor" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def scan() -> tuple[dict, set]:
    readers: dict[str, set] = defaultdict(set)
    writers: set = set()
    files = []
    for d in SCAN_DIRS:
        files += list(_iter_py(os.path.join(BACKEND, d)))
    for extra in WRITER_EXTRA:
        p = os.path.join(BACKEND, extra)
        if os.path.isdir(p):
            files += list(_iter_py(p))
        elif os.path.isfile(p):
            files.append(p)
    for p in files:
        src = open(p, encoding="utf-8", errors="ignore").read()
        rel = os.path.relpath(p, BACKEND)
        if rel.split(os.sep)[0] in SCAN_DIRS:
            for m in READ_RX.finditer(src):
                readers[m.group(1)].add(rel)
        for m in WRITE_RX.finditer(src):
            writers.add(m.group(1))
    return readers, writers


def main() -> int:
    readers, writers = scan()
    orphans = sorted(c for c in readers if c not in writers and c not in WHITELIST)
    print(f"koleksi dibaca: {len(readers)} · punya penulis: {sum(1 for c in readers if c in writers)} · "
          f"DIBACA TANPA PENULIS: {len(orphans)}")
    for c in orphans:
        print(f"  {c:40s} ← {', '.join(sorted(readers[c])[:3])}{' …' if len(readers[c]) > 3 else ''}")
    if "--set-baseline" in sys.argv:
        open(BASELINE, "w").write(str(len(orphans)) + "\n")
        print("baseline disimpan:", len(orphans))
    if "--gate" in sys.argv:
        base = int(open(BASELINE).read().strip()) if os.path.exists(BASELINE) else 0
        if len(orphans) > base:
            print(f"GAGAL: koleksi hantu naik {base} → {len(orphans)}")
            return 1
        print(f"OK: {len(orphans)} ≤ baseline {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
