"""core/akun_kreator.py — BANYAK akun per kreator (18 Nov 2026).

Owner: "creator juga bisa tambahkan akun lain seperti akun kreator yang di manage dll jadi tidak harus 1 toko 1 akun"
→ keputusan: "Banyak akun per kreator" + "sesi live boleh di akun kreator".

Dulu kreator hanya punya `platforms` = {platform: satu username} (form: satu Akun TikTok, satu Akun Shopee). Sekarang
`accounts` = daftar {id, platform, username, jenis, toko_ids}. `platforms` TETAP diisi (username pertama per platform)
supaya pembaca lama tidak berubah; pencocokan pesanan afiliasi memakai SEMUA akun lewat :func:`handles`.
Akun kreator BUKAN toko — tidak punya omzet/pembukuan sendiri; omzet tetap milik toko yang produknya terjual.
"""
from __future__ import annotations

import uuid
from typing import Iterable, Optional

from fastapi import HTTPException

JENIS = {"pribadi": "Akun pribadi kreator", "dikelola": "Akun kreator dikelola perusahaan",
         "afiliasi": "Akun afiliasi lain"}
PLATFORM = {"tiktok": "TikTok", "shopee": "Shopee", "instagram": "Instagram", "tokopedia": "Tokopedia",
            "lazada": "Lazada", "youtube": "YouTube", "lainnya": "Lainnya"}
_ALIAS = {"tiktokshop": "tiktok", "tiktok shop": "tiktok", "ig": "instagram", "yt": "youtube"}


def _norm(v) -> str:
    from core.marketing_account_scope import norm
    return norm(v)


def dari_platforms(platforms: Optional[dict]) -> list[dict]:
    """Akun dari data lama `platforms` (satu username per platform) — kreator yang belum pernah disimpan ulang."""
    out = []
    for p, u in (platforms or {}).items():
        if _norm(u):     # "-" / "—" (isian lama untuk "tidak ada") bukan akun
            plat = _ALIAS.get(str(p).lower(), str(p).lower())
            out.append({"id": f"lama-{plat}", "platform": plat if plat in PLATFORM else "lainnya",
                        "username": str(u).strip(), "jenis": "pribadi", "toko_ids": []})
    return out


def akun_of(creator: Optional[dict]) -> list[dict]:
    """Daftar akun kreator; kreator lama tanpa `accounts` dibaca dari `platforms`."""
    c = creator or {}
    return list(c.get("accounts")) if isinstance(c.get("accounts"), list) else dari_platforms(c.get("platforms"))


def lengkapi(creator: Optional[dict]) -> Optional[dict]:
    if creator is not None:
        creator["accounts"] = akun_of(creator)
    return creator


def normalisasi(daftar: Optional[Iterable], toko_valid: Optional[set] = None) -> list[dict]:
    """Rapikan isian layar → daftar akun bersih. Username kosong dilewati; platform/jenis tak dikenal → 400;
    akun kembar (platform + username sama) disatukan; toko di luar `toko_valid` dibuang."""
    out, seen = [], set()
    for a in daftar or []:
        if not isinstance(a, dict):
            continue
        user = str(a.get("username") or "").strip()
        if not _norm(user):          # kosong atau hanya tanda ("-", "—") = tidak ada akun
            continue
        plat = _ALIAS.get(str(a.get("platform") or "").strip().lower(), str(a.get("platform") or "").strip().lower())
        if plat not in PLATFORM:
            raise HTTPException(400, f"Platform akun '{user}' tidak dikenal: {a.get('platform')}.")
        jenis = str(a.get("jenis") or "pribadi").strip().lower()
        if jenis not in JENIS:
            raise HTTPException(400, f"Jenis akun '{user}' tidak dikenal: {a.get('jenis')}.")
        key = (plat, _norm(user))
        if key in seen:
            continue
        seen.add(key)
        toko = [t for t in dict.fromkeys(a.get("toko_ids") or []) if t and (toko_valid is None or t in toko_valid)]
        aid = str(a.get("id") or "")
        out.append({"id": aid if aid and not aid.startswith("lama-") else str(uuid.uuid4()),
                    "platform": plat, "username": user, "jenis": jenis, "toko_ids": toko})
    return out


def platforms_dari(akun: list[dict], lama: Optional[dict] = None) -> dict:
    """`platforms` lama = username PERTAMA per platform (dipakai pembaca lama & tampilan ringkas)."""
    out: dict = {}
    for a in akun:
        out.setdefault(a["platform"], a["username"])
    for p, u in (lama or {}).items():   # platform lama yang tidak ada di daftar baru dibiarkan kosong (dihapus staf)
        if p not in out and not akun:
            out[p] = u
    return out


def handles(creator: Optional[dict]) -> list[str]:
    """Semua username kreator (semua akun + `platforms` lama) — untuk mencocokkan 'Creator Handle' pesanan."""
    c = creator or {}
    hs = [a.get("username") for a in akun_of(c)] + list((c.get("platforms") or {}).values())
    return [h for h in dict.fromkeys(str(h).strip() for h in hs if h) if _norm(h)]


async def cek_bentrok(db, akun: list[dict], creator_id: Optional[str]) -> None:
    """Satu username (per platform) hanya milik satu kreator — supaya pesanan afiliasi tidak tercatat ganda."""
    if not akun:
        return
    mine = {(a["platform"], _norm(a["username"])) for a in akun if _norm(a["username"])}
    async for c in db.marketing_kol_creators.find({"id": {"$ne": creator_id or ""}},
                                                  {"_id": 0, "id": 1, "name": 1, "accounts": 1, "platforms": 1}):
        for a in akun_of(c):
            if (a.get("platform"), _norm(a.get("username"))) in mine:
                raise HTTPException(400, f"Akun {PLATFORM.get(a.get('platform'), a.get('platform'))} "
                                         f"'{a.get('username')}' sudah tercatat milik kreator {c.get('name')}.")


def label(a: dict) -> str:
    return f"{PLATFORM.get(a.get('platform'), a.get('platform'))} {a.get('username')} ({JENIS.get(a.get('jenis'), '')})"
