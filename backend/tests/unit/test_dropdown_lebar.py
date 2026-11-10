"""Dropdown pilihan (SmartNativeSelect) cukup lebar & bisa dicari per kata (owner 10 Nov 2026, form PO:
"dropdownnya terlalu kecil jadi sulit untuk dicari")."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "ui"
       / "smart-native-select.jsx").read_text(encoding="utf-8")


def test_panel_daftar_dicari_selebar_isinya():
    assert 'width: "max-content"' in SRC and 'maxWidth: "min(40rem, calc(100vw - 16px))"' in SRC
    assert "max(var(--radix-popover-trigger-width), 18rem)" in SRC
    assert '"whitespace-normal break-words"' in SRC and "title={o.label}" in SRC   # nama tidak terpotong


def test_cari_per_kata_urutan_bebas():
    assert "split(/\s+/)" in SRC and "words.every((w) => hay.includes(w))" in SRC
