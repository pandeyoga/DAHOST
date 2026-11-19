"""core/kreator_per_toko.py — DATA KERJA SAMA kreator PER TOKO (keputusan owner 19 Nov 2026).

Kendala (Licha, 19 Nov): satu kreator dipakai beberapa toko; mengubah status/target kreator dari satu toko ikut
mengubah toko lain karena datanya hanya SATU. Keputusan owner: **status, tipe kerja sama, target omzet, dan catatan
dipisah per toko; identitas kreator (nama, kontak, akun) tetap satu.**

Bentuk tersimpan di `marketing_kol_creators`::

    per_toko: {<account_id>: {status, creator_type, kpi_targets, notes, updated_at, updated_by}}

Field lama di tingkat atas (`status`, `creator_type`, `kpi_targets`, `notes`) tetap ada sebagai NILAI AWAL: toko yang
belum punya data sendiri memakainya (dokumen lama terbaca tanpa migrasi). Begitu satu toko diubah, semua toko kreator
itu dibekukan ke datanya masing-masing (`pecah`), sehingga perubahan berikutnya tidak pernah merembet ke toko lain.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

FIELDS = ("status", "creator_type", "kpi_targets", "notes")
STATUS = ("active", "inactive")
TIPE = ("new", "kontrak", "continue")
TIPE_INSENTIF = ("kontrak", "continue")
KPI_KEYS = ("monthly_revenue", "monthly_sessions", "monthly_viewers")


def _num(v) -> float:
    try:
        return max(0.0, float(v or 0))
    except (TypeError, ValueError):
        return 0.0


def nilai_awal(creator: dict) -> dict:
    c = creator or {}
    return {"status": c.get("status") or "active", "creator_type": c.get("creator_type") or "new",
            "kpi_targets": dict(c.get("kpi_targets") or {}), "notes": c.get("notes") or ""}


def nilai_toko(creator: dict, account_id: str | None) -> dict:
    """Nilai kerja sama kreator di satu toko (data toko itu, atau nilai awal bila belum punya)."""
    base = nilai_awal(creator)
    own = ((creator or {}).get("per_toko") or {}).get(account_id) if account_id else None
    own = own if isinstance(own, dict) else {}
    out = {**base, **{k: own[k] for k in FIELDS if k in own and own[k] is not None}}
    out["sendiri"] = bool(own)
    return out


def toko_terlihat(creator: dict, visible) -> list:
    return [a for a in ((creator or {}).get("assigned_account_ids") or []) if visible is None or a in visible]


def toko_konteks(creator: dict, visible, account_id: str | None = None) -> str | None:
    """Toko yang nilainya ditampilkan di tingkat atas: toko penyaring, atau toko pertama yang dipegang pemakai."""
    terlihat = toko_terlihat(creator, visible)
    if account_id and account_id in terlihat:
        return account_id
    if visible is not None and terlihat:
        return terlihat[0]
    return None


def _kunci(v: dict) -> tuple:
    k = v.get("kpi_targets") or {}
    return (v.get("status"), v.get("creator_type"), tuple(_num(k.get(x)) for x in KPI_KEYS), v.get("notes") or "")


def terapkan(creator: dict, visible, account_id: str | None = None) -> dict:
    """Jawaban API: field kerja sama tingkat atas = nilai toko konteks; `per_toko` = nilai tiap toko yang boleh dilihat
    (toko rekan kerja disembunyikan); `beda_per_toko` bila nilainya tidak sama di semua toko itu."""
    if creator is None:
        return creator
    per = {a: nilai_toko(creator, a) for a in toko_terlihat(creator, visible)}
    ctx = toko_konteks(creator, visible, account_id)
    if ctx:
        for k in FIELDS:
            creator[k] = per[ctx][k]
    creator["toko_konteks"] = ctx
    creator["per_toko"] = per
    creator["beda_per_toko"] = len({_kunci(v) for v in per.values()}) > 1
    return creator


def bersihkan(isi: dict) -> dict:
    """Validasi isian kerja sama satu toko (field yang tidak dikirim tidak diubah)."""
    if not isinstance(isi, dict):
        raise HTTPException(400, "Data kerja sama per toko tidak valid.")
    out = {}
    if isi.get("status") is not None:
        if isi["status"] not in STATUS:
            raise HTTPException(400, "Status kreator harus Aktif atau Nonaktif.")
        out["status"] = isi["status"]
    if isi.get("creator_type") is not None:
        if isi["creator_type"] not in TIPE:
            raise HTTPException(400, "Tipe kreator harus Kreator baru, Kontrak, atau Lanjutan.")
        out["creator_type"] = isi["creator_type"]
    if isi.get("kpi_targets") is not None:
        if not isinstance(isi["kpi_targets"], dict):
            raise HTTPException(400, "Target KPI tidak valid.")
        out["kpi_targets"] = {k: _num(isi["kpi_targets"].get(k)) for k in KPI_KEYS}
    if isi.get("notes") is not None:
        out["notes"] = str(isi["notes"])
    return out


def pecah(creator: dict, ubah: dict, toko_semua: list, user: dict) -> dict:
    """`$set` untuk perubahan per toko. Toko kreator lain yang belum punya data sendiri ikut DIBEKUKAN ke nilai yang
    sedang berlaku, supaya nilai awal tidak lagi menjadi data bersama."""
    now = datetime.now(timezone.utc)
    oleh = (user or {}).get("name") or (user or {}).get("email") or ""
    out = {}
    for acc in toko_semua:
        cur = nilai_toko(creator, acc)
        if acc in ubah:
            cur = {**cur, **ubah[acc]}
        elif cur["sendiri"]:
            continue
        out[f"per_toko.{acc}"] = {**{k: cur[k] for k in FIELDS}, "updated_at": now, "updated_by": oleh}
    return out


def saring_status(status: str, stores: list) -> dict:
    """Kueri: kreator yang status di salah satu `stores` = `status` (data toko itu, atau nilai awal)."""
    ors = []
    for s in stores:
        ors.append({"assigned_account_ids": s, f"per_toko.{s}.status": status})
        ors.append({"assigned_account_ids": s, f"per_toko.{s}.status": {"$exists": False}, "status": status})
    return {"$or": ors} if ors else {"status": status}


def aktif_di(creator: dict, visible) -> bool:
    """Aktif di minimal satu toko yang boleh dilihat (tanpa toko: nilai awal)."""
    terlihat = toko_terlihat(creator, visible)
    if not terlihat:
        return nilai_awal(creator)["status"] == "active"
    return any(nilai_toko(creator, a)["status"] == "active" for a in terlihat)


def tipe_insentif(creator: dict) -> str:
    """Tipe untuk insentif: kontrak/lanjutan di salah satu toko berarti berhak insentif."""
    tipe = [nilai_toko(creator, a)["creator_type"] for a in (creator.get("assigned_account_ids") or [])]
    for t in TIPE_INSENTIF:
        if t in tipe:
            return t
    return nilai_awal(creator)["creator_type"] if not tipe else tipe[0]


def kpi_total(creator: dict) -> dict:
    """Target kreator di Portal Kreator (semua toko): jumlah target tiap toko bila datanya sudah dipisah per toko,
    selain itu nilai awal (tidak dikalikan jumlah toko)."""
    stores = (creator or {}).get("assigned_account_ids") or []
    per = (creator or {}).get("per_toko") or {}
    if not stores or not all(isinstance(per.get(a), dict) for a in stores):
        return nilai_awal(creator)["kpi_targets"]
    return {k: sum(_num((nilai_toko(creator, a)["kpi_targets"] or {}).get(k)) for a in stores) for k in KPI_KEYS}
