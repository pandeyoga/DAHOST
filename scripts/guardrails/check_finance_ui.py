#!/usr/bin/env python3
"""FIN-UI — penjaga menu & tampilan Portal Keuangan (2026-11-04, audit Keuangan tahap 2).

Tanpa Node/esbuild (beda dengan check_nav_map.py), jadi bisa jalan di job backend CI. Memeriksa:
  1. setiap menu Portal Keuangan di portalNav.js terdaftar di moduleRegistry.js;
  2. setiap `makeRedirect('<id>', '<tab>')` menunjuk id yang terdaftar, dan bila id itu hub ber-tab,
     tab-nya benar-benar ada (redirect ke tab yang sudah diganti namanya = tautan lama mati diam-diam);
  3. layar yang dibuka dari menu Keuangan tidak memuat lagi teks yang sudah dibersihkan
     (label "Portal Finance ·", istilah Inggris yang diganti) — supaya tidak kembali lewat salin-tempel.

Pakai:  python3 scripts/guardrails/check_finance_ui.py      (exit 1 bila ada pelanggaran)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Guard  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
ERP = ROOT / "frontend" / "src" / "components" / "erp"
REGISTRY = ERP / "moduleRegistry.js"
NAV = ERP / "portal-shell" / "portalNav.js"

# teks yang sudah diganti di layar Keuangan — jangan muncul lagi
BANNED = [
    (r'eyebrow="Portal Finance', 'label kecil "Portal Finance ·" di atas judul'),
    (r'eyebrow="SDM / Finance', 'label kecil "SDM / Finance ·" di atas judul'),
    (r'Rahaza Finance', 'nama lama "Rahaza Finance"'),
    (r'Cash & Bank Accounts', 'judul Inggris (pakai "Rekening & Mutasi")'),
    (r'AR 360° Dashboard', 'judul Inggris (pakai "Umur Piutang")'),
    (r'Invoice Edit Approval', 'judul Inggris (pakai "Persetujuan Perubahan Faktur")'),
    (r'AI Cash Flow Prediction', 'judul Inggris (pakai "Perkiraan Arus Kas")'),
    (r'Outstanding Balance|Avg Days Overdue|Unique Debtors|DSO Estimate', 'label KPI Inggris di Umur Piutang'),
    (r'Revenue Terbayar', 'label rancu (pakai "Faktur reseller sudah dibayar")'),
    (r'Seed Default Mapping|>\s*Pasang bawaan\s*<', 'tombol perawatan — tempatnya Adm. Sistem › Perawatan Data Keuangan'),
]
LAZY_RX = re.compile(r"const\s+(\w+)\s*=\s*lazyRetry\(\s*\(\)\s*=>\s*import\(\s*'([^']+)'\s*\)\s*\)")
ENTRY_RX = re.compile(r"^\s*'([\w-]+)'\s*:\s*(.+?),?\s*(?://.*)?$", re.M)
REDIRECT_RX = re.compile(r"makeRedirect\(\s*'([\w-]+)'(?:\s*,\s*'([\w-]+)')?\s*\)")
TAB_KEY_RX = re.compile(r"\{\s*key:\s*'([\w-]+)'")


def _resolve(base: Path, rel: str) -> Path | None:
    p = (base / rel).resolve()
    for cand in (p, p.with_suffix(".jsx"), p.with_suffix(".js"), p / "index.jsx", p / "index.js"):
        if cand.is_file():
            return cand
    return None


def main() -> int:
    g = Guard("FIN-UI", "Menu & tampilan Portal Keuangan")
    reg = REGISTRY.read_text(encoding="utf-8")
    lazy = {name: _resolve(ERP, path) for name, path in LAZY_RX.findall(reg)}
    entries = {mid: expr.strip() for mid, expr in ENTRY_RX.findall(reg)}

    # 1. menu Portal Keuangan → registry
    nav = NAV.read_text(encoding="utf-8")
    fin_block = nav[nav.index("  finance: {"):]
    fin_block = fin_block[:fin_block.index("\n  },\n")]
    fin_ids = re.findall(r"\{\s*id:\s*'([\w-]+)'", fin_block)
    for mid in fin_ids:
        g.bump()
        if mid not in entries:
            g.add(f"menu Keuangan '{mid}' tidak ada di moduleRegistry.js")

    # 2. redirect → id & tab yang ada
    def hub_tabs(mid: str) -> set[str] | None:
        expr = entries.get(mid, "")
        m = re.match(r"(?:withProps\()?(\w+)", expr)
        f = lazy.get(m.group(1)) if m else None
        if not f:
            return None
        keys = set(TAB_KEY_RX.findall(f.read_text(encoding="utf-8")))
        return keys if ("HubTabs" in f.read_text(encoding="utf-8") and keys) else None

    for target, tab in REDIRECT_RX.findall(reg):
        if not target.startswith(("fin-", "finance-")):
            continue   # penjaga ini hanya untuk Portal Keuangan
        g.bump()
        if target not in entries:
            g.add(f"makeRedirect('{target}') menunjuk id yang tidak terdaftar")
            continue
        tabs = hub_tabs(target)
        if tab and tabs is not None and tab not in tabs:
            g.add(f"makeRedirect('{target}', '{tab}') — tab '{tab}' tidak ada di hub (ada: {', '.join(sorted(tabs))})")

    # 3. teks terlarang di layar yang dibuka dari menu Keuangan (+ tab hub-nya, satu tingkat)
    files: set[Path] = set()
    for mid in fin_ids:
        m = re.match(r"(?:withProps\()?(\w+)", entries.get(mid, ""))
        f = lazy.get(m.group(1)) if m else None
        if not f:
            continue
        files.add(f)
        for _, rel in LAZY_RX.findall(f.read_text(encoding="utf-8")):
            sub = _resolve(f.parent, rel)
            if sub:
                files.add(sub)
    for f in sorted(files):
        src = f.read_text(encoding="utf-8")
        g.bump()
        for rx, why in BANNED:
            for mm in re.finditer(rx, src):
                line = src.count("\n", 0, mm.start()) + 1
                if src.splitlines()[line - 1].strip().startswith(("*", "/*", "//")):
                    continue   # komentar riwayat boleh menyebut nama lama
                g.add(f"{f.relative_to(ROOT).as_posix()}:{line} — {why}")
    return g.finish()


if __name__ == "__main__":
    sys.exit(main())
