"""Grup toko = MEREK (keputusan pemilik 8 Nov 2026).

Isian "Grup" di Kelola Akun mengelompokkan toko per merek: Rayona · Daluna · Outfit Boutique · Lainnya.
(Sebelumnya daftar tetapnya jenis toko — Official Store/Reseller/Distributor — padahal data yang diisi staf
berisi nama merek.) Satu-satunya daftar di server; cermin layar:
`frontend/src/components/erp/AccountManagementModule.jsx` › `GROUPS` (diuji sama oleh test_keputusan_sdm_mkt).
"""
import re
from typing import Optional

# kode tersimpan → label layar. `other` = bawaan server saat toko dibuat.
GRUP_TOKO = {
    'rayona': 'Rayona',
    'daluna': 'Daluna',
    'outfit_boutique': 'Outfit Boutique',
    'other': 'Lainnya',
}
GRUP_BAWAAN = 'other'


def norm(raw) -> str:
    """Huruf kecil tanpa spasi/garis bawah/tanda hubung/titik ("Outfit-Boutique" → "outfitboutique")."""
    return re.sub(r'[\s_\-\.]+', '', str(raw).strip().lower())


_KENAL = {}
for _kode, _label in GRUP_TOKO.items():
    _KENAL[norm(_kode)] = _kode
    _KENAL[norm(_label)] = _kode
_KENAL.update({'lain': 'other', 'lainlain': 'other', 'others': 'other'})

_MEREK = {k: norm(v) for k, v in GRUP_TOKO.items() if k != GRUP_BAWAAN}


def kode_grup(raw) -> Optional[str]:
    """Nilai grup (kode / label / beda huruf-spasi) → kode daftar, atau None bila bukan nama di daftar."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _KENAL.get(norm(raw))


def tebak_merek(nama_toko) -> Optional[str]:
    """Merek dari nama toko bila TEPAT satu merek disebut ("TikTok Outfit Boutique" → outfit_boutique)."""
    n = norm(nama_toko or '')
    hit = [k for k, m in _MEREK.items() if m and m in n]
    return hit[0] if len(hit) == 1 else None
