"""core/po_sampel.py — DRAF PO produksi "Sampel R&D" (keputusan owner 14 Nov 2026).

Owner: bila stok barang jadi untuk sampel KOSONG atau KURANG, sistem membuat sendiri draf PO produksi berlabel
"Sampel R&D" — supaya kain & aksesorisnya kelak keluar lewat alur produksi biasa (BOM, kirim CMT, QC terima),
bukan diambil diam-diam. Berlaku untuk dua sumber:

  * Marketing › Kirim Sample — satu baris kiriman yang stoknya kurang (``jenis = kirim_sampel``, per baris).
  * R&D › Sample Request — saat request disetujui dan variannya sudah diketahui (``jenis = sample_request``).

Aturan (satu tempat untuk kedua sumber):
  1. SATU jalur pembuatan PO: ``routes.production_pos.create_po_internal`` (internal, status Draf). Pengaman
     Merchandiser (`core.merchandiser.jaga`) hanya untuk tombol Buat PO di layar — tidak menahan PO sampel.
     Penjaga kode potongan (`core.po_tolak_dobel`) tidak relevan (sampel tidak berkode potongan); kuncinya tetap
     dipakai supaya "periksa lalu tulis" tidak lolos dua kali.
  2. TIDAK DOBEL: PO dicari dulu lewat ``sumber`` (jenis + id + baris). Ada ⇒ PO itu yang dikembalikan.
  3. Penomoran: bila PO produksi internal disetel MANUAL (nomor wajib diketik), sistem tidak bisa menerbitkan
     nomor ⇒ TIDAK ada yang dibuat; hasilnya catatan "PO sampel perlu dibuat manual oleh admin produksi".
  4. Varian wajib ada di Master Produk (`rahaza_model_variants` aktif, lewat SKU atau id). Tidak ada ⇒ catatan.
  5. Gagal apa pun di sini tidak pernah menggagalkan kiriman/persetujuan sampel — hasilnya catatan yang jelas.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

LABEL = "sampel_rnd"
LABEL_TAMPIL = "Sampel R&D"
KUNCI_NOMOR = "production_pos.po_number"
PELANGGAN = "Gudang FG Sendiri"          # = isian bawaan layar PO internal
CATATAN_MANUAL = "PO sampel perlu dibuat manual oleh admin produksi"


async def cari_varian(db, *, variant_id: str = "", sku: str = "") -> Optional[dict]:
    """Varian aktif Master Produk lewat id atau SKU (tidak peka huruf besar/kecil)."""
    if variant_id:
        v = await db.rahaza_model_variants.find_one({"id": variant_id, "active": {"$ne": False}}, {"_id": 0})
        if v:
            return v
    sku = str(sku or "").strip().upper()
    if not sku:
        return None
    return await db.rahaza_model_variants.find_one({"sku": sku, "active": {"$ne": False}}, {"_id": 0})


def kueri_sumber(jenis: str, sumber_id: str, baris_id: Optional[str] = None) -> dict:
    return {"label": LABEL, "sumber.jenis": jenis, "sumber.id": sumber_id, "sumber.baris_id": baris_id}


async def po_ada(db, jenis: str, sumber_id: str, baris_id: Optional[str] = None) -> Optional[dict]:
    """PO sampel yang SUDAH dibuat untuk sumber ini (aturan 2)."""
    return await db.production_pos.find_one(kueri_sumber(jenis, sumber_id, baris_id),
                                            {"_id": 0, "id": 1, "po_number": 1, "status": 1})


async def penomoran_manual(db) -> bool:
    from core import doc_number_policy as dnp
    try:
        return (await dnp.policy(db, KUNCI_NOMOR)).get("mode") == "manual"
    except Exception:  # noqa: BLE001 — kebijakan tak terbaca: biarkan create_po_internal yang menolak
        return False


def _pemakai(user: Optional[dict]) -> dict:
    u = dict(user or {})
    u["id"] = str(u.get("id") or u.get("sub") or "")
    u["name"] = u.get("name") or u.get("email") or "Sistem"
    return u


async def buat_draf(db, *, jenis: str, sumber_id: str, nomor: str, qty: int, user: Optional[dict],
                    variant: Optional[dict] = None, variant_id: str = "", sku: str = "",
                    baris_id: Optional[str] = None, catatan: str = "") -> dict:
    """Buat (atau kembalikan) draf PO "Sampel R&D" untuk satu sumber.

    Return selalu dict:
      ``{"po_id", "po_number", "baru": bool}``  — PO ada / baru dibuat
      ``{"po_catatan": "..."}``                 — tidak dibuat, beserta alasannya (aturan 3–5)
    """
    qty = int(qty or 0)
    if qty <= 0:
        return {"po_catatan": "Jumlah sampel 0 — tidak ada PO yang perlu dibuat."}
    ada = await po_ada(db, jenis, sumber_id, baris_id)
    if ada:
        return {"po_id": ada["id"], "po_number": ada.get("po_number"), "baru": False}
    if await penomoran_manual(db):
        return {"po_catatan": f"{CATATAN_MANUAL} (penomoran PO produksi internal disetel manual)."}
    v = variant or await cari_varian(db, variant_id=variant_id, sku=sku)
    if not v:
        label = sku or variant_id or "produk ini"
        return {"po_catatan": f"Varian {label} tidak ada di Master Produk — {CATATAN_MANUAL}."}

    from core import po_tolak_dobel as ptd
    from routes.production_pos import create_po_internal
    body = {
        "business_type": "internal", "customer_name": PELANGGAN, "status": "Draft",
        "notes": (f"{LABEL_TAMPIL} — dibuat otomatis dari {nomor}. {catatan}".strip())[:1000],
        "items": [{"rahaza_variant_id": v["id"], "sku": v.get("sku"), "qty": qty}],
    }
    tanda = {"label": LABEL, "sumber": {"jenis": jenis, "id": sumber_id, "nomor": nomor, "baris_id": baris_id}}
    try:
        async with ptd.kunci_buat_po():
            ada = await po_ada(db, jenis, sumber_id, baris_id)       # periksa lagi di dalam kunci
            if ada:
                return {"po_id": ada["id"], "po_number": ada.get("po_number"), "baru": False}
            po = await create_po_internal(db, body, _pemakai(user), tanda=tanda)
    except Exception as e:  # noqa: BLE001 — aturan 5
        detail = getattr(e, "detail", None) or str(e)
        logger.warning("[po-sampel] %s %s gagal: %s", jenis, sumber_id, detail)
        return {"po_catatan": f"PO sampel belum bisa dibuat otomatis ({detail}) — {CATATAN_MANUAL}."}
    return {"po_id": po.get("id"), "po_number": po.get("po_number"), "baru": True}
