#!/usr/bin/env python3
"""Gate CI: layanan lintas modul yang TIDAK tertutup (14 Nov 2026).

Pasangan (menu, layanan) dihitung bila layanan yang dipanggil layar menu (peta `backend/data/peta_menu_layanan.json`)
ter-resolve ke modul N yang BUKAN pemilik menu itu, bukan "Lihat" pada modul data acuan (`lookup`), bukan swalayan
Portal Saya, dan TIDAK tertutup `module_catalog.modul_setara` — baik `MODUL_SETARA` manual maupun layanan
ikut-otomatis. Sisanya = pasangan yang tetap butuh centang di modul lain: kotak centang sendiri (keputusan owner,
`module_catalog.sebab_terpisah`) atau aksi yang tidak dimiliki modul pemilik menu (tombol milik modul lain).

Pakai (dari akar repo):
  python3 scripts/akses/gate_layanan_lintas_modul.py                 # ringkasan + 10 contoh
  python3 scripts/akses/gate_layanan_lintas_modul.py --detail        # semua pasangan (otomatis + sisa)
  python3 scripts/akses/gate_layanan_lintas_modul.py --gate          # exit 1 bila sisa > baseline
  python3 scripts/akses/gate_layanan_lintas_modul.py --set-baseline  # simpan jumlah sisa sekarang
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline_layanan_lintas_modul.txt")

from data import module_catalog as mc  # noqa: E402


def hitung() -> dict:
    otomatis, manual, sisa = [], [], []
    for menu in sorted(mc.MENU_PEMILIK):
        pemilik = {m["id"] for m in mc.MENU_PEMILIK[menu]}
        for method, path in mc.layanan_menu(menu):
            mod, act = mc.resolve(method, path)
            if not mod or mod["id"] in pemilik or mc.is_self_service(method, path):
                continue
            if act == "view" and mod["lookup"]:
                continue
            baris = (menu, method, path, mod["id"], act)
            if any(a["id"] in pemilik for a in mc.modul_setara(method, path, otomatis=False)):
                manual.append(baris)
            elif any(a["id"] in pemilik for a in mc.modul_setara(method, path)):
                otomatis.append(baris)
            else:
                sebab = next((s for s in (mc.sebab_terpisah(method, path, p) for p in sorted(pemilik)) if s), "")
                sisa.append(baris + (sebab or "aksi ini tidak ada di modul pemilik menu",))
    return {"otomatis": otomatis, "manual": manual, "sisa": sisa}


def _cetak(judul: str, rows: list, batas: int | None) -> None:
    print(f"\n{judul} ({len(rows)}):")
    for r in rows[:batas] if batas else rows:
        menu, method, path, mod, act = r[:5]
        sebab = f"  [{r[5]}]" if len(r) > 5 else ""
        print(f"  {menu:28s} {method:6s} {path:58s} -> mod.{mod}.{act}{sebab}")


def main(argv: list[str]) -> int:
    h = hitung()
    sisa = h["sisa"]
    terpisah = [r for r in sisa if not r[5].startswith("aksi ini tidak ada")]
    print(f"layanan lintas modul: ikut otomatis {len(h['otomatis'])} · setara manual {len(h['manual'])} · "
          f"TIDAK TERTUTUP {len(sisa)} (kotak centang sendiri {len(terpisah)}, aksi tidak dimiliki modul menu "
          f"{len(sisa) - len(terpisah)})")
    batas = None if "--detail" in argv else 10
    if "--detail" in argv:
        _cetak("Ikut terbuka otomatis", h["otomatis"], None)
        _cetak("Setara manual (MODUL_SETARA)", h["manual"], None)
    _cetak("Tidak tertutup", sisa, batas)
    if "--set-baseline" in argv:
        with open(BASELINE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{len(sisa)}\n")
        print("baseline disimpan:", len(sisa))
    if "--gate" in argv:
        base = int(open(BASELINE, encoding="utf-8").read().strip()) if os.path.exists(BASELINE) else len(sisa)
        if len(sisa) > base:
            print(f"GAGAL: layanan lintas modul yang tidak tertutup NAIK {base} -> {len(sisa)}. Layar baru memanggil "
                  "layanan yang tidak ikut terbuka otomatis: periksa daftar di atas (kotak centang sendiri disengaja?).")
            return 1
        print(f"OK: {len(sisa)} <= baseline {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
