#!/usr/bin/env python3
"""Perbaikan massal tombol sesuai PANDUAN_UI G3 untuk satu portal (2026-11-04).

  python3 scripts/ui_audit/fix_buttons.py --portal finance          # pratinjau (jumlah perubahan per berkas)
  python3 scripts/ui_audit/fix_buttons.py --portal finance --apply  # tulis

Yang diubah pada elemen <Button …>…</Button>:
  1. variant="ghost" + className berisi `border` → variant="outline" (latar kartu), kelas garis/h-9 dibuang.
  2. Tombol berisi <RefreshCw/> + teks "Muat ulang/Refresh" → tombol ikon (size="icon", title & aria-label).
  3. Tinggi manual di className tanpa prop size: h-7/h-8 → size="sm"; h-9/h-10 dibuang (bawaan 36 px).
Pengurai tag menghitung kurung kurawal, jadi `onClick={() => …}` di dalam tag tidak memotong tag.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_ui import portal_files  # noqa: E402

LABELS = [("Export CSV", "Unduh CSV"), ("Export Excel", "Unduh Excel"), ("Ekspor Excel", "Unduh Excel"),
          ("Export", "Unduh"), ("Ekspor", "Unduh"), ("Import Excel", "Impor Excel"), ("Import", "Impor"),
          ("Reopen", "Buka lagi"), ("Muat Ulang", "Muat ulang")]
DROP_WITH_OUTLINE = {"border", "border-[var(--glass-border)]", "border-foreground/10", "border-border", "h-9"}


def find_elements(src: str):
    """Yield (start, tag_end, close_start, close_end) untuk setiap <Button …>…</Button> / <Button …/>."""
    i = 0
    while True:
        i = src.find("<Button", i)
        if i < 0:
            return
        if not re.match(r"<Button[\s>/]", src[i:i + 8]):
            i += 7
            continue
        depth, j, quote = 0, i + 7, None
        while j < len(src):
            ch = src[j]
            if quote:
                if ch == quote and src[j - 1] != "\\":
                    quote = None
            elif ch in "\"'`" and depth > 0:
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            j += 1
        tag_end = j + 1
        if src[j - 1] == "/":
            yield i, tag_end, tag_end, tag_end
        else:
            c = src.find("</Button>", tag_end)
            if c < 0:
                return
            yield i, tag_end, c, c + len("</Button>")
        i = tag_end


def fix_tag(tag: str, children: str) -> tuple[str, str, list[str]]:
    notes = []
    m = re.search(r'className="([^"]*)"', tag)
    classes = m.group(1).split() if m else []
    has_size = re.search(r"\bsize=", tag) is not None
    if 'variant="ghost"' in tag and any(c == "border" or c.startswith("border-[var") for c in classes):
        tag = tag.replace('variant="ghost"', 'variant="outline"', 1)
        classes = [c for c in classes if c not in DROP_WITH_OUTLINE]
        notes.append("ghost+garis→outline")
    if re.search(r"<RefreshCw\b", children) and re.search(r"(Muat [Uu]lang|Refresh)", children) and not has_size:
        children = re.sub(r"(?<=>)\s*(?:Muat [Uu]lang|Refresh)\s*(?=<|$)", "", children)
        children = re.sub(r'(<RefreshCw\b[^>]*?)\s(?:mr|ml)-1(?:\.5)?\b', r"\1", children)
        tag = re.sub(r"^<Button\b", '<Button size="icon"', tag)
        if "title=" not in tag:
            tag = re.sub(r"^<Button\b", '<Button title="Muat ulang" aria-label="Muat ulang"', tag)
        has_size = True
        classes = [c for c in classes if not re.fullmatch(r"h-\d+|px-\d+", c)]
        notes.append("muat ulang→ikon")
    # label tombol berbahasa Inggris / tidak baku (G11) — hanya teks di antara tag
    for old, new in LABELS:
        nc = re.sub(rf"(?<=>)(\s*){re.escape(old)}(\s*)(?=<|$)", rf"\g<1>{new}\g<2>", children)
        if nc != children:
            children = nc
            notes.append("label")
    if not has_size:
        hs = [c for c in classes if re.fullmatch(r"h-(7|8|9|10)", c)]
        if hs:
            classes = [c for c in classes if c not in hs]
            if hs[0] in ("h-7", "h-8"):
                tag = re.sub(r"^<Button\b", '<Button size="sm"', tag)
            notes.append(f"{hs[0]}→size")
    if m:
        new_cls = " ".join(classes)
        tag = tag.replace(m.group(0), f'className="{new_cls}"' if new_cls else "", 1)
        tag = re.sub(r"\s{2,}(?=[>/]|\w)", " ", tag) if not new_cls else tag
    return tag, children, notes


def process(path: Path, apply: bool) -> list[str]:
    src = path.read_text(encoding="utf-8")
    out, last, notes = [], 0, []
    for start, tag_end, cstart, cend in find_elements(src):
        tag = src[start:tag_end]
        children = src[tag_end:cstart]
        ntag, nchildren, n = fix_tag(tag, children)
        if n:
            out.append(src[last:start] + ntag + nchildren)
            last = cstart
            notes += n
    if notes and apply:
        out.append(src[last:])
        path.write_text("".join(out), encoding="utf-8", newline="")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", default="finance")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    _, files = portal_files(a.portal)
    total = 0
    for f in sorted(files):
        n = process(f, a.apply)
        if n:
            total += len(n)
            print(f"{len(n):3d}  {f.relative_to(Path(__file__).resolve().parents[2]).as_posix()}  ({', '.join(sorted(set(n)))})")
    print(f"{'diubah' if a.apply else 'akan diubah'}: {total} tombol")
    return 0


if __name__ == "__main__":
    sys.exit(main())
