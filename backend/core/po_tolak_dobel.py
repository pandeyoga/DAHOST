"""core.po_tolak_dobel — penjaga PO produksi DOBEL (keputusan owner 14 Nov 2026: "ya, perbaiki").

Kejadian 13 Nov 2026 (go-live): dari 17 PO baru, tujuh dobel.
  * Dua pasang PO kembar lahir dari SATU isian: selisih 1,1 detik dan 0,09 detik. Tombol "Buat PO" tidak
    terkunci selama menyimpan, dan server tidak menolak isi yang sama persis.
  * Lima PO memasukkan lagi batch potong (kode potongan DA-1869, DA-1874, AF-4044-1, …) yang sudah ada
    di PO lain. Layar hanya memberi PERINGATAN "nomor seri dobel — boleh lanjut".

Dua penjaga, satu tempat (dipakai `routes.production_pos` buat & ubah PO):

1. KODE POTONGAN — isian "No. seri / batch" di baris PO (`po_items.serial_number`). Satu kode potongan =
   satu batch potong = satu PO.
   * Kode yang sudah dipakai PO LAIN → DITOLAK (409).
   * Di dalam satu PO, satu kode boleh banyak baris (warna/ukuran dari batch yang sama). Kode + varian
     yang sama dua kali → baris kembar, DITOLAK.
   * Pemeriksa lintas PO = SSOT `services.cmt_intake.serial_lookup`, yang juga dipakai peringatan
     langsung di formulir.
   * Saat UBAH PO, hanya kode yang BARU masuk PO itu yang diperiksa. Dengan begitu PO lama yang kebetulan
     sudah bentrok tetap bisa diubah, misalnya untuk membetulkan kodenya.
2. KLIK GANDA — pembuatan PO lewat layar diserialkan dengan satu kunci proses (backend = satu proses
   uvicorn, lihat deploy/Dockerfile.backend). PO yang isinya sama persis (jenis, CMT, buyer, baris) dari
   pengguna yang sama dalam `JENDELA_DETIK` → DITOLAK. Ini juga menutup PO tanpa kode potongan.

Jalur impor/saldo awal/cermin maklon memanggil `create_po_internal` langsung dan tidak lewat penjaga ini.
Jalur itu dijalankan skrip yang sudah diperiksa sendiri.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from typing import Any, Iterable

from fastapi import HTTPException

from core.helpers import now
from services.cmt_intake import _norm as norm_kode
from services.cmt_intake import kode_dalam, serial_lookup

JENDELA_DETIK = 120
STATUS_BATAL = {"cancelled", "canceled", "dibatalkan", "batal"}

# Satu kunci untuk "periksa lalu tulis" pembuatan PO. Tanpa kunci, dua kiriman berselang 0,09 detik sama-sama
# lolos pemeriksaan sebelum salah satunya tersimpan. Kunci asyncio terikat pada satu event loop, jadi dibuat per
# loop yang berjalan (server: satu loop; uji: satu loop per kasus).
_KUNCI: dict[int, asyncio.Lock] = {}


def kunci_buat_po() -> asyncio.Lock:
    loop_id = id(asyncio.get_running_loop())
    kunci = _KUNCI.get(loop_id)
    if kunci is None:
        _KUNCI.clear()
        kunci = _KUNCI[loop_id] = asyncio.Lock()
    return kunci


def _kunci_varian(it: dict) -> str:
    """Identitas varian satu baris PO (internal: varian master; maklon: varian/artikel katalog buyer)."""
    for k in ("rahaza_variant_id", "maklon_variant_id"):
        if it.get(k):
            return f"{k}:{it[k]}"
    sku = " ".join(str(it.get("sku") or "").upper().split())
    if sku:
        return f"sku:{sku}"
    return "|".join(" ".join(str(it.get(k) or "").upper().split())
                    for k in ("model_id", "catalog_item_id", "product_name", "color", "size"))


def label_baris(it: dict) -> str:
    bagian = [str(it.get(k) or "").strip() for k in ("sku", "product_name", "color", "size")]
    teks = " ".join(b for b in bagian if b)
    return teks or "baris tanpa nama"


def _qty(v) -> str:
    try:
        return str(int(float(v or 0)))
    except (TypeError, ValueError):
        return str(v)


def sidik_isi(body: dict, user: dict) -> str:
    """Sidik isi PO dari layar. Sama persis = jenis, CMT, buyer, dan semua baris (varian, qty, kode) sama."""
    baris = sorted(
        (_kunci_varian(it), _qty(it.get("qty")), norm_kode(it.get("serial_number")))
        for it in (body.get("items") or []) if isinstance(it, dict))
    isi = {
        "jenis": body.get("business_type") or "internal",
        "cmt": str(body.get("vendor_id") or ""),
        "buyer": str(body.get("buyer_id") or ""),
        "oleh": str(user.get("id") or user.get("name") or ""),
        "baris": baris,
    }
    return hashlib.sha1(json.dumps(isi, sort_keys=True).encode("utf-8")).hexdigest()


async def tolak_kembar_baru(db, sidik: str) -> None:
    """409 bila PO dengan sidik sama dibuat dalam `JENDELA_DETIK` terakhir (klik ganda / kirim ulang)."""
    batas = now() - timedelta(seconds=JENDELA_DETIK)
    kembar = await db.production_pos.find_one({"sidik_isi": sidik, "created_at": {"$gte": batas}},
                                              {"_id": 0, "po_number": 1})
    if kembar:
        raise HTTPException(
            409, f"PO dengan isi sama persis baru saja dibuat ({kembar.get('po_number')}). PO tidak dibuat dua "
                 "kali. Buka daftar PO untuk melihatnya.")


def baris_kembar(items: Iterable[dict]) -> list[str]:
    """Baris dengan kode potongan + varian yang sama lebih dari sekali dalam SATU PO."""
    lihat: dict[tuple[str, str], int] = {}
    kembar: list[str] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        kode = norm_kode(it.get("serial_number"))
        if not kode:
            continue
        kunci = (kode, _kunci_varian(it))
        lihat[kunci] = lihat.get(kunci, 0) + 1
        if lihat[kunci] == 2:
            kembar.append(f"{kode} · {label_baris(it)}")
    return kembar


async def kode_terpakai(db, items: Iterable[dict], *, kecuali_po_id: str | None = None,
                        kode_lama: Iterable[str] = ()) -> list[dict]:
    """Kode potongan di `items` yang sudah dipakai PO lain. `kode_lama` (kode yang sudah ada di PO ini
    sebelum diubah) tidak diperiksa ulang."""
    lama = {t for k in kode_lama for t in kode_dalam(k)}
    kode = []
    for it in items or []:
        for k in (kode_dalam(it.get("serial_number")) if isinstance(it, dict) else []):
            if k not in lama and k not in kode:
                kode.append(k)
    temuan: list[dict] = []
    for k in kode:
        hasil = await serial_lookup(db, serial=k, exclude_po_id=kecuali_po_id, scope="all")
        pakai = [u for u in hasil.get("usages") or []
                 if str(u.get("po_status") or "").strip().lower() not in STATUS_BATAL]
        if not pakai:
            continue
        po_ids = sorted({u["po_id"] for u in pakai if u.get("po_id")})
        cmt = {p["id"]: p.get("vendor_name") or "" for p in await db.production_pos.find(
            {"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "vendor_name": 1}).to_list(None)}
        po = []
        for u in pakai:
            teks = u.get("po_number") or "PO tanpa nomor"
            if cmt.get(u.get("po_id")):
                teks += f" ({cmt[u['po_id']]})"
            if teks not in po:
                po.append(teks)
        temuan.append({"kode": k, "po": po})
    return temuan


def pesan_kode_terpakai(temuan: list[dict]) -> str:
    daftar = "; ".join(f"{t['kode']} sudah ada di {', '.join(t['po'])}" for t in temuan[:6])
    if len(temuan) > 6:
        daftar += f"; +{len(temuan) - 6} kode lain"
    return (f"Kode potongan sudah dipakai PO lain: {daftar}. Satu kode potongan hanya untuk satu PO, supaya "
            "batch yang sama tidak terhitung dua kali. Kalau PO lama itu salah, betulkan atau hapus PO itu "
            "dulu. Kalau ini batch potong lain, isi kode potongannya sendiri.")


async def periksa_kode(db, items: list[dict], *, kecuali_po_id: str | None = None,
                       kode_lama: Iterable[str] = ()) -> None:
    """Satu pintu pemeriksaan kode potongan untuk buat & ubah PO (409 bila dobel)."""
    kembar = baris_kembar(items)
    if kembar:
        raise HTTPException(
            409, "Baris kembar di PO ini (kode potongan dan varian sama): " + "; ".join(kembar[:6])
                 + ". Gabungkan jumlahnya di satu baris.")
    temuan = await kode_terpakai(db, items, kecuali_po_id=kecuali_po_id, kode_lama=kode_lama)
    if temuan:
        raise HTTPException(409, pesan_kode_terpakai(temuan))


def kode_di(items: Iterable[Any]) -> list[str]:
    return [k for i in items or [] if isinstance(i, dict) for k in kode_dalam(i.get("serial_number"))]
