#!/usr/bin/env python3
"""Perbaikan massal WARNA & ANGKA sesuai PANDUAN_UI G7/G8 untuk satu portal (2026-11-05).

  python3 scripts/ui_audit/fix_tokens.py --portal production          # pratinjau (jumlah per berkas)
  python3 scripts/ui_audit/fix_tokens.py --portal production --apply  # tulis

Yang diubah (hanya kelas Tailwind; tata letak, menu, dan logika tidak disentuh):
  1. Warna palet langsung → token (G8). Keluarga warna:
       emerald/green/teal/lime → success · red/rose → destructive · amber/yellow/orange → warning
       blue/sky/indigo/violet/purple/cyan/fuchsia/pink → primary
     · text-/fill-/stroke-<warna>-<n>      → text-[hsl(var(--token))]         (opasitas /x dipertahankan)
     · bg-<warna>-50|100|200|300           → bg-[hsl(var(--token)/0.1|0.15|0.2|0.3)]   (latar lembut)
     · bg-<warna>-400..950                 → bg-[hsl(var(--token))]           (latar penuh, mis. tombol)
     · border-/ring-/divide-/outline-<warna>-<n> → …-[hsl(var(--token)/0.35)]
     · from-/via-/to-<warna>-<n> (gradasi) → …-[hsl(var(--token)/0.1)]
     · semua awalan varian (hover:, focus:, group-hover:, md:, …) ikut dipertahankan;
     · kelas `dark:<warna>` DIBUANG — token sudah punya nilai terang & gelap.
  2. `font-mono` → `tabular-nums` (G7: angka pakai huruf yang sama dengan teks, lebar angka seragam).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_ui import ROOT, portal_files  # noqa: E402

FAMILY = {}
for t, names in {
    "success": ("emerald", "green", "teal", "lime"),
    "destructive": ("red", "rose"),
    "warning": ("amber", "yellow", "orange"),
    "primary": ("blue", "sky", "indigo", "violet", "purple", "cyan", "fuchsia", "pink"),
}.items():
    for n in names:
        FAMILY[n] = t
COLORS = "|".join(sorted(FAMILY, key=len, reverse=True))
VARIANT = r"(?:[a-z0-9-]+:)*"            # hover: dark: md: group-hover: …
CLS = re.compile(
    rf"(?<![\w\[/-])(?P<var>{VARIANT})(?P<util>text|bg|border|ring|divide|outline|fill|stroke|from|via|to|"
    rf"border-[trblxy]|ring-offset)-(?P<color>{COLORS})-(?P<shade>50|[1-9]00|950)(?:/(?P<op>\d{{1,3}}))?(?![\w-])")
SOFT_BG = {"50": "0.1", "100": "0.15", "200": "0.2", "300": "0.3"}


def _alpha(op: str | None, default: str | None) -> str:
    if op:
        v = int(op) / 100
        return f"/{v:g}"
    return f"/{default}" if default else ""


def _replace(m: re.Match) -> str:
    var, util, color, shade, op = m["var"], m["util"], m["color"], m["shade"], m["op"]
    if "dark:" in var:
        return ""                         # token sudah gelap/terang sendiri
    tok = FAMILY[color]
    if util in ("text", "fill", "stroke"):
        val = f"hsl(var(--{tok}){_alpha(op, None)})"
    elif util == "bg":
        soft = SOFT_BG.get(shade)
        if not soft and not op and "hover:" in var:
            soft = "0.9"                  # hover tombol penuh tetap terlihat berubah
        val = f"hsl(var(--{tok}){_alpha(op, soft)})"
    elif util in ("from", "via", "to"):
        val = f"hsl(var(--{tok}){_alpha(op, '0.1')})"
    else:                                  # border / ring / divide / outline
        val = f"hsl(var(--{tok}){_alpha(op, '0.35')})"
    return f"{var}{util}-[{val}]"


MONO = re.compile(r"(?<![\w-])font-mono(?![\w-])")


def fix_text(src: str) -> tuple[str, int]:
    n = 0

    def rep(m):
        nonlocal n
        n += 1
        return _replace(m)
    out = CLS.sub(rep, src)
    out, k = MONO.subn("tabular-nums", out)
    n += k
    # rapikan spasi ganda yang tertinggal di dalam string kelas (hanya di antara kata kelas)
    out = re.sub(r'(className="[^"]*?)  +', lambda mm: mm.group(1) + " ", out)
    out = re.sub(r'className=" +', 'className="', out)
    return out, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--files", nargs="*", help="batasi ke berkas tertentu (path relatif repo)")
    a = ap.parse_args()
    _, files = portal_files(a.portal)
    if a.files:
        want = {str((ROOT / f).resolve()) for f in a.files}
        files = {f for f in files if str(f.resolve()) in want}
    total = 0
    for f in sorted(files):
        if f.suffix not in (".jsx", ".js"):
            continue
        src = f.read_text(encoding="utf-8")
        out, n = fix_text(src)
        if n and out != src:
            total += n
            print(f"{n:5d}  {f.relative_to(ROOT).as_posix()}")
            if a.apply:
                f.write_text(out, encoding="utf-8", newline="")
    print(f"total perubahan: {total}{'' if a.apply else ' (pratinjau — tambahkan --apply untuk menulis)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
