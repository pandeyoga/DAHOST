"""Pembantu bersama alat baca Marketing (agen data) — bukan alat, tidak didaftarkan.

* :func:`periode_bawaan` — rentang bawaan bila model tidak menyebut tanggal
  (awal bulan berjalan s.d. hari ini, WIB, dari ``ctx.today``).
* :func:`padatkan` — hasil endpoint dipadatkan ≤ 15.000 karakter: baris rincian
  dipotong dari bawah (sudah terurut menurut kepentingan) dan potongan itu DISEBUT.
* :func:`params` — buang isian kosong sebelum dikirim sebagai query.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Optional, Tuple

MAKS_KARAKTER = 15_000
_RUANG = 600                     # cadangan untuk pembungkus {"hasil": …, "_sumber": …}

DEFINISI_SINGKAT = (
    "Omzet = penjualan produk setelah diskon penjual, sebelum potongan platform (Rp), dari rekap "
    "harian; pesanan batal & belum dibayar tidak dihitung; retur terpisah; data contoh dibuang.")


def hari_ini(ctx) -> date:
    t = getattr(ctx, "today", None)
    if isinstance(t, date):
        return t
    try:
        return date.fromisoformat(str(t)[:10])
    except ValueError:
        from utils.waktu import today_wib
        return today_wib()


def periode_bawaan(ctx, args: Dict[str, Any]) -> Tuple[str, str]:
    dari, sampai = (args.get("dari") or "").strip(), (args.get("sampai") or "").strip()
    if dari or sampai:
        return dari or sampai, sampai or dari
    t = hari_ini(ctx)
    return t.replace(day=1).isoformat(), t.isoformat()


def params(**kw) -> Dict[str, Any]:
    return {k: v for k, v in kw.items() if v not in (None, "", [])}


def _panjang(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str))


def padatkan(data: Dict[str, Any], *, maks: int = MAKS_KARAKTER - _RUANG) -> Dict[str, Any]:
    """Salinan ringkas: teks panjang yang sudah diketahui model diganti, lalu daftar
    rincian (daftar berisi objek, sampai dua tingkat) dipotong dari bawah — urutannya
    sudah menurut kepentingan — sampai muat. Potongan itu DISEBUT di hasil."""
    out = json.loads(json.dumps(data, ensure_ascii=False, default=str))
    out.pop("ok", None)
    if "definisi" in out:
        out["definisi"] = DEFINISI_SINGKAT

    def _lists():
        for v in out.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                yield v
            elif isinstance(v, dict):
                for w in v.values():
                    if isinstance(w, list) and w and isinstance(w[0], dict):
                        yield w

    dibuang = 0
    while _panjang(out) > maks:
        target = max(_lists(), key=len, default=None)
        if not target:
            break
        cut = max(1, len(target) // 5)
        del target[-cut:]
        dibuang += cut
    if dibuang:
        out["dipotong_untuk_ai"] = (f"{dibuang} baris rincian terbawah tidak ditampilkan supaya ringkas; "
                                    "persempit periode atau pakai kelompok lain untuk melihatnya.")
    return out


def bulan_ini(ctx) -> str:
    """Bulan Marketing berjalan ``YYYY-MM`` — tanggal 26–25 (owner 11 Nov 2026): 26 Nov sudah Desember."""
    from core import bulan_marketing as _bulan
    return _bulan.periode_dari(hari_ini(ctx))


def angka(v: Optional[Any], lo: int, hi: int, bawaan: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return bawaan
