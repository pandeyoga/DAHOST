#!/usr/bin/env python3
"""FASE 4.5 (T-21): `to_list(None)` / `to_list(length=None)` di backend/routes tidak boleh BERTAMBAH.

Pakai:
  python3 scripts/check_unbounded_queries.py            # laporan per berkas
  python3 scripts/check_unbounded_queries.py --gate     # exit 1 bila jumlah > baseline
  python3 scripts/check_unbounded_queries.py --set-baseline
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES = os.path.join(ROOT, "backend", "routes")
BASELINE = os.path.join(ROOT, "scripts", "unbounded_queries_baseline.txt")
RX = re.compile(r"\.to_list\(\s*(?:None|length\s*=\s*None)\s*\)")


def scan() -> Counter:
    hits: Counter = Counter()
    for dirpath, _, files in os.walk(ROUTES):
        if "_archive" in dirpath or "__pycache__" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(dirpath, f)
                n = len(RX.findall(open(p, encoding="utf-8", errors="ignore").read()))
                if n:
                    hits[os.path.relpath(p, ROOT)] = n
    return hits


def main() -> int:
    hits = scan()
    total = sum(hits.values())
    print(f"to_list(None) di routes: {total} pemanggilan di {len(hits)} berkas")
    for p, n in hits.most_common(10):
        print(f"  {n:4d}  {p}")
    if "--set-baseline" in sys.argv:
        open(BASELINE, "w").write(f"{total}\n")
        print("baseline disimpan:", total)
    if "--gate" in sys.argv:
        base = int(open(BASELINE).read().strip()) if os.path.exists(BASELINE) else total
        if total > base:
            print(f"GAGAL: to_list(None) naik {base} → {total}")
            return 1
        print(f"OK: {total} ≤ baseline {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
