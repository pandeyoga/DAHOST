#!/usr/bin/env python3
"""Pemindai konsistensi UI per portal — bagian STATIS dari audit tampilan (2026-11-04).

Pasangannya: `scripts/ui_audit/dom_audit.js` (memeriksa layar yang benar-benar tampil di browser).
Aturan & alasannya ada di `docs/design/PANDUAN_UI.md`; kode aturan (mis. TOMBOL-TANPA-LATAR) sama
di dokumen, skrip ini, dan audit DOM. Cara memakai untuk portal lain: `docs/design/CARA_AUDIT_UI.md`.

Berkas yang diperiksa = layar yang dibuka dari menu portal (portalNav.js → moduleRegistry.js),
ditambah komponen lokal yang diimpornya (sampai 2 tingkat: hub → tab → sub-komponen).

Pakai:
  python3 scripts/ui_audit/scan_ui.py --portal finance                 # ringkasan di layar
  python3 scripts/ui_audit/scan_ui.py --portal finance --md out.md     # laporan rinci (file:baris)
  python3 scripts/ui_audit/scan_ui.py --portal finance --gate          # exit 1 bila jumlah > baseline
  python3 scripts/ui_audit/scan_ui.py --portal finance --set-baseline  # simpan jumlah sekarang
  python3 scripts/ui_audit/scan_ui.py --list-portals
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "frontend" / "src"
ERP = SRC / "components" / "erp"
REGISTRY = ERP / "moduleRegistry.js"
NAV = ERP / "portal-shell" / "portalNav.js"
BASELINE = Path(__file__).resolve().parent / "baseline.json"

# (kode, bagian panduan, keterangan, regex). Regex dijalankan per BERKAS (multiline) dan baris komentar
# dilewati. Heuristik — tujuannya menemukan kandidat; keputusan akhir tetap dilihat di layar.
RULES: list[tuple[str, str, str, str]] = [
    ("TOMBOL-TANPA-LATAR", "G3", 'Button variant="ghost" diberi garis (border) supaya tampak seperti tombol — '
     'hasilnya tombol tanpa latar di atas latar gradasi. Pakai variant="outline" (latar kartu).',
     r'variant="ghost"[^>]{0,240}?className="[^"]*\bborder\b'),
    ("TOMBOL-UKURAN-MANUAL", "G3", "Tinggi tombol diatur lewat className (h-7/h-8/h-10…), bukan prop size.",
     r'<Button\b[^>]{0,300}?className="[^"]*\bh-(?:7|8|10|11|12)\b'),
    ("TOMBOL-BUATAN", "G3", "<button> polos dengan kelas sendiri (padding + rounded) — pakai <Button>.",
     r'<button\b[^>]{0,400}?className=(?:"|\{`)[^"`]*\bpx-[1-6]\b[^"`]*\brounded'),
    ("TOMBOL-WARNA-MENTAH", "G3", "Tombol dengan warna palet langsung (bg-teal-600, bg-blue-600…) — pakai variant.",
     r'<(?:button|Button)\b[^>]{0,300}?className=(?:"|\{`)[^"`]*\bbg-(?:red|rose|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|amber|yellow|orange|pink)-[5-8]00\b'),
    ("MUAT-ULANG-BERTEKS", "G3", "Tombol muat ulang bertulisan — standar: ikon saja + title.",
     r'<RefreshCw\b[^>]*/>\s*(?:Muat [Uu]lang|Refresh)'),
    ("TAB-BUATAN", "G4", "Deret tab/penyaring buatan sendiri (array [kunci,label].map → tombol yang mengubah state tab, "
     "atau garis bawah border-b-2 -mb-px) — pakai komponen tab/segmen standar.",
     r"\[\s*(?:\[\s*['\"][\w-]*['\"]\s*,\s*['\"`][^'\"`]+['\"`][^\]]*\]\s*,?\s*){2,}\]\s*\.map\(|border-b-2[^\"]*-mb-px"
     r"|\.map\(\(?\s*\w+\s*\)?\s*=>\s*\(?\s*<button[^>]{0,200}onClick=\{\(\)\s*=>\s*set(?:Tab|ActiveTab|View|Status|Filter|Kind|Mode)\w*\("),
    ("TAB-DALAM-MODUL", "G4", "Tabs Radix di dalam modul — bila modul dibuka sebagai tab hub, jadi tab di dalam tab.",
     r'<TabsList\b'),
    ("JUDUL-BUATAN", "G2", "Judul halaman dibuat sendiri (<h1>/<h2> besar) — pakai PageHeader.",
     r'<h1\b|<h2 className="text-(?:lg|xl|2xl)\b'),
    ("BUNGKUS-SENDIRI", "G1", "Pembungkus halaman sendiri (max-w-* mx-auto / p-6) — lebar & jarak beda dari halaman lain.",
     r'className="[^"]*\bmax-w-(?:[3-7]xl|screen-\w+)\b[^"]*\bmx-auto\b'),
    ("KARTU-BUATAN", "G5", "Kartu dari <div> (rounded + border + latar) — pakai GlassCard / StatTile / DataCard.",
     r'<div\b[^>]{0,200}?className=(?:"|\{`)[^"`]*\brounded-(?:xl|2xl|lg|\[var\(--radius-[a-z]+\)\])\b[^"`]*\bborder\b[^"`]*\bbg-'),
    ("LATAR-WARNA-MENTAH", "G8", "Latar berwarna palet langsung (bg-emerald-100, bg-blue-50…) di kartu/badge — pakai token atau StatusBadge.",
     r'\bbg-(?:blue|amber|emerald|red|purple|violet|green|orange|rose|sky|teal)-(?:50|100|400/\d+|500/\d+)\b'),
    ("ANGKA-MONO", "G7", "font-mono untuk angka/uang — pakai tabular-nums (huruf sama dengan teks).",
     r'\bfont-mono\b'),
    ("WARNA-MENTAH", "G8", "Warna teks/garis palet langsung (text-emerald-300…) — pakai token success/warning/destructive/muted.",
     r'\b(?:text|border)-(?:red|rose|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|amber|yellow|orange|pink|lime)-\d{2,3}\b'),
    ("SELECT-POLOS", "G6", "<select> polos — pakai SmartNativeSelect (bisa dicari) atau Select.",
     r'<select\b'),
    ("TANGGAL-POLOS", "G6", 'Input type="date|month" polos — untuk periode pakai PeriodPicker; tanggal tunggal pakai GlassInput type="date".',
     r'<input\b[^>]{0,200}?type="(?:date|month)"'),
    ("DIALOG-BROWSER", "G9", "window.confirm/alert — pakai dialog konfirmasi aplikasi / toast.",
     r'(?<![\w.])(?:window\.)?(?:confirm|alert)\('),
    ("KOSONG-BUATAN", "G10", "Tampilan kosong berupa teks polos — pakai EmptyState (ikon + judul + langkah).",
     r'>\s*(?:Tidak ada data|Belum ada [^<{]{3,60}|Tidak ada [^<{]{3,60}ditemukan)\s*</(?:p|div|td|span)>'),
    ("TEKS-INGGRIS", "G11", "Label/tombol berbahasa Inggris.",
     r'(?:>|label[=:]\s*[\'"`]|title="|placeholder=")\s*(?:Export(?: CSV| Excel)?|Refresh|Settlement[^<"\'`]{0,20}|Outstanding[^<"\'`]{0,20}|Overview|Submit|Approve|Reject|Retry|Statement[^<"\'`]{0,15}|Invoice[^<"\'`]{0,15}|Print|Save|Cancel|Delete|Upload|Download|Unposted|Pending|Total (?:Pending|Budget|Outstanding)|Gross Profit|Operating Income|Net Income|Dashboard)\s*(?:<|[\'"`])'),
]
# 2026-11-04 (revisi 2 panduan) — aturan yang dihitung khusus (bukan satu pola baris):
#   CETAKAN-TIDAK-DIPAKAI  layar menu/tab tanpa PageLayout                (G1)
#   POPUP-DAFTAR           daftar/tabel di dalam Sheet/Dialog              (G13)
#   JARAK-BESAR            jarak/padding besar buatan sendiri              (G1)
SPECIAL_RULES = {
    "CETAKAN-TIDAK-DIPAKAI": ("G1", "Layar menu/tab tidak memakai cetakan PageLayout (erp/layout/PageLayout.jsx) — "
                              "kepala, toolbar, dan posisi tombol disusun sendiri."),
    "POPUP-DAFTAR": ("G13", "Daftar/tabel dibuka di popup (Sheet/Dialog) — detail dibuka di halaman: DetailPanel / RowDetail."),
    "JARAK-BESAR": ("G1", "Jarak/padding besar buatan sendiri (space-y-6+, py-10+, mb-8…) — jarak antarbagian dari cetakan (16 px)."),
}
BIG_SPACE_RX = re.compile(r'(?<![\w-])(?:space-y-(?:6|7|8|10|12)|gap-(?:8|10|12)|(?:p|py|pt|pb)-(?:10|12|14|16|20|24)'
                          r'|(?:m|my|mt|mb)-(?:8|10|12|16|20|24))(?![\w-])')
BIG_SPACE_SKIP = ("moduleAtoms.jsx", "/layout/", "EmptyState.jsx")
POPUP_BLOCK_RX = re.compile(r'<(SheetContent|DialogContent)\b')
LIST_IN_POPUP_RX = {"SheetContent": re.compile(r'<table\b|<Table\b|<DataTable\b|<StatementTable\b|\.map\('),
                    "DialogContent": re.compile(r'<table\b|<Table\b|<DataTable\b|<StatementTable\b')}

FILE_RULES = [
    ("KARTU-DUA-JENIS", "G5", "Satu berkas memakai dua jenis kartu (<Card> shadcn dan <GlassCard>).",
     lambda s: bool(re.search(r'<Card\b', s) and re.search(r'<GlassCard\b', s))),
    ("TABEL-TIGA-CARA", "G7", "Satu berkas memakai >1 cara membuat tabel (DataTable / <Table> / <table>).",
     lambda s: sum(bool(re.search(p, s)) for p in (r'<DataTable\b', r'<Table\b', r'<table\b')) > 1),
]

LAZY_RX = re.compile(r"lazyRetry\(\s*\(\)\s*=>\s*import\(\s*'([^']+)'\s*\)\s*\)")
LAZY_NAMED_RX = re.compile(r"const\s+(\w+)\s*=\s*lazyRetry\(\s*\(\)\s*=>\s*import\(\s*'([^']+)'\s*\)\s*\)")
STATIC_IMPORT_RX = re.compile(r"^import\s+[^;]*?from\s+'(\.{1,2}/[^']+)'", re.M)
ENTRY_RX = re.compile(r"^\s*'([\w-]+)'\s*:\s*(.+?),?\s*(?://.*)?$", re.M)
COMMENT_RX = re.compile(r"^\s*(?://|\*|/\*|\{/\*)")


def _resolve(base: Path, rel: str) -> Path | None:
    p = (base / rel).resolve()
    for cand in (p, p.with_suffix(".jsx"), p.with_suffix(".js"), p / "index.jsx", p / "index.js"):
        if cand.is_file():
            return cand
    return None


def portal_blocks(nav: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"^  (\w+): \{\n", nav, re.M):
        start = m.end()
        end = nav.find("\n  },\n", start)
        if end > 0 and "sections" in nav[start:end]:
            out[m.group(1)] = nav[start:end]
    return out


def _entry_file(expr: str, lazy: dict) -> Path | None:
    """Berkas modul untuk satu entri registri: `Nama`, `withProps(Nama, …)`, atau `lazyRetry(() => import('./x'))`."""
    inline = LAZY_RX.search(expr)
    if inline:
        return _resolve(ERP, inline.group(1))
    m = re.match(r"(?:withProps\()?(\w+)", expr)
    return lazy.get(m.group(1)) if m else None


def portal_screens(portal: str) -> set[Path]:
    """Berkas LAYAR: modul yang dibuka langsung dari menu, dan modul tiap tab bila menunya hub (HubTabs)."""
    reg = REGISTRY.read_text(encoding="utf-8")
    lazy = {name: _resolve(ERP, path) for name, path in LAZY_NAMED_RX.findall(reg)}
    entries = {mid: expr.strip() for mid, expr in ENTRY_RX.findall(reg)}
    blocks = portal_blocks(NAV.read_text(encoding="utf-8"))
    out: set[Path] = set()
    for mid in re.findall(r"\{\s*id:\s*'([\w-]+)'", blocks[portal]):
        f = _entry_file(entries.get(mid, ""), lazy)
        if not f:
            continue
        src = f.read_text(encoding="utf-8", errors="ignore")
        if "<HubTabs" in src:
            for rel in LAZY_RX.findall(src):
                sub = _resolve(f.parent, rel)
                if sub and sub.suffix in (".jsx", ".js"):
                    out.add(sub)
        else:
            out.add(f)
    return out


def scan_special(files: set[Path], screens: set[Path]) -> list[dict]:
    hits = []
    for f in sorted(files):
        src = f.read_text(encoding="utf-8", errors="ignore")
        lines = src.splitlines()
        rel = f.relative_to(ROOT).as_posix()
        if f in screens and "<PageLayout" not in src:
            hits.append({"rule": "CETAKAN-TIDAK-DIPAKAI", "sec": "G1", "file": rel, "line": 0, "text": ""})
        for mm in POPUP_BLOCK_RX.finditer(src):
            tag = mm.group(1)
            end = src.find(f"</{tag}>", mm.end())
            block = src[mm.end(): end if end > 0 else mm.end() + 6000]
            if LIST_IN_POPUP_RX[tag].search(block):
                ln = src.count("\n", 0, mm.start()) + 1
                hits.append({"rule": "POPUP-DAFTAR", "sec": "G13", "file": rel, "line": ln, "text": lines[ln - 1].strip()[:140]})
        if not any(s in rel for s in BIG_SPACE_SKIP):
            for mm in BIG_SPACE_RX.finditer(src):
                ln = src.count("\n", 0, mm.start()) + 1
                if COMMENT_RX.match(lines[ln - 1]):
                    continue
                hits.append({"rule": "JARAK-BESAR", "sec": "G1", "file": rel, "line": ln, "text": lines[ln - 1].strip()[:140]})
    return hits


def portal_files(portal: str) -> tuple[list[str], set[Path]]:
    reg = REGISTRY.read_text(encoding="utf-8")
    lazy = {name: _resolve(ERP, path) for name, path in LAZY_NAMED_RX.findall(reg)}
    entries = {mid: expr.strip() for mid, expr in ENTRY_RX.findall(reg)}
    blocks = portal_blocks(NAV.read_text(encoding="utf-8"))
    if portal not in blocks:
        raise SystemExit(f"Portal '{portal}' tidak ada. Pilihan: {', '.join(sorted(blocks))}")
    ids = re.findall(r"\{\s*id:\s*'([\w-]+)'", blocks[portal])
    files: set[Path] = set()

    def add(f: Path, depth: int):
        if f in files or "components/ui" in f.as_posix() or not f.is_relative_to(SRC):
            return
        files.add(f)
        if depth >= 2:
            return
        src = f.read_text(encoding="utf-8", errors="ignore")
        for rel in LAZY_RX.findall(src) + STATIC_IMPORT_RX.findall(src):
            sub = _resolve(f.parent, rel)
            if sub and sub.suffix in (".jsx", ".js") and "/lib/" not in sub.as_posix():
                add(sub, depth + 1)

    for mid in ids:
        f = _entry_file(entries.get(mid, ""), lazy)
        if f:
            add(f, 0)
    return ids, files


def scan(files: set[Path]) -> list[dict]:
    hits = []
    for f in sorted(files):
        src = f.read_text(encoding="utf-8", errors="ignore")
        lines = src.splitlines()
        rel = f.relative_to(ROOT).as_posix()
        for code, sec, why, rx in RULES:
            for mm in re.finditer(rx, src, re.S):
                ln = src.count("\n", 0, mm.start()) + 1
                if COMMENT_RX.match(lines[ln - 1]):
                    continue
                hits.append({"rule": code, "sec": sec, "file": rel, "line": ln,
                             "text": lines[ln - 1].strip()[:140]})
        for code, sec, why, fn in FILE_RULES:
            if fn(src):
                hits.append({"rule": code, "sec": sec, "file": rel, "line": 0, "text": ""})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", default="finance")
    ap.add_argument("--md", help="tulis laporan rinci markdown ke berkas ini")
    ap.add_argument("--json", help="tulis temuan mentah JSON ke berkas ini")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--set-baseline", action="store_true")
    ap.add_argument("--list-portals", action="store_true")
    ap.add_argument("--ids", action="store_true", help="cetak daftar id menu portal (untuk uiAuditMenus di dom_audit.js)")
    a = ap.parse_args()
    portals = sorted(portal_blocks(NAV.read_text(encoding="utf-8")))
    if a.list_portals:
        print("\n".join(portals))
        return 0
    if a.portal == "all":
        # 2026-11-04 — satu perintah untuk semua portal (dipakai CI): tiap portal dibandingkan baseline-nya.
        if a.ids or a.md or a.json:
            raise SystemExit("--ids/--md/--json hanya untuk satu portal")
        rc = 0
        for p in portals:
            sub = [sys.argv[0], "--portal", p] + (["--gate"] if a.gate else []) + (["--set-baseline"] if a.set_baseline else [])
            old = sys.argv
            sys.argv = sub
            try:
                rc |= main()
            finally:
                sys.argv = old
        return rc
    ids, files = portal_files(a.portal)
    if a.ids:
        print(json.dumps(ids))
        return 0
    hits = scan(files) + scan_special(files, portal_screens(a.portal))
    per_rule = Counter(h["rule"] for h in hits)
    meta = ({c: (s, w) for c, s, w, _ in RULES} | {c: (s, w) for c, s, w, _ in FILE_RULES}
            | {c: v for c, v in SPECIAL_RULES.items()})
    print(f"Portal {a.portal}: {len(ids)} menu, {len(files)} berkas diperiksa, {len(hits)} temuan")
    for code, n in per_rule.most_common():
        print(f"  {n:5d}  {code:22s} [{meta[code][0]}]")
    if a.md:
        per_file = defaultdict(list)
        for h in hits:
            per_file[h["rule"]].append(h)
        out = [f"# Audit UI statis — portal `{a.portal}`\n",
               f"{len(ids)} menu · {len(files)} berkas · {len(hits)} temuan. Aturan: docs/design/PANDUAN_UI.md\n",
               "| Kode | Bagian | Jumlah | Keterangan |", "|---|---|---:|---|"]
        out += [f"| {c} | {meta[c][0]} | {n} | {meta[c][1]} |" for c, n in per_rule.most_common()]
        for code, _ in per_rule.most_common():
            out.append(f"\n## {code}\n")
            by_file = Counter(h["file"] for h in per_file[code])
            for fname, n in by_file.most_common():
                lines = [str(h["line"]) for h in per_file[code] if h["file"] == fname and h["line"]]
                out.append(f"- `{fname}` ×{n}" + (f" — baris {', '.join(lines[:12])}{'…' if len(lines) > 12 else ''}" if lines else ""))
        Path(a.md).write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"laporan: {a.md}")
    if a.json:
        Path(a.json).write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    if a.set_baseline:
        base[a.portal] = dict(per_rule)
        BASELINE.write_text(json.dumps(base, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline {a.portal} disimpan")
    if a.gate:
        ref = base.get(a.portal)
        if ref is None:
            print(f"GAGAL: belum ada baseline untuk {a.portal} (jalankan --set-baseline)")
            return 1
        worse = {c: (ref.get(c, 0), n) for c, n in per_rule.items() if n > ref.get(c, 0)}
        if worse:
            for c, (b, n) in worse.items():
                print(f"GAGAL: {c} naik {b} → {n}")
            return 1
        print("OK: tidak ada aturan yang memburuk dibanding baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
