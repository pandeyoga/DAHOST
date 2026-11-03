"""core/tax_status — SSOT status pajak perusahaan (PKP / non-PKP) untuk SEMUA hitungan PPN.

Keputusan owner 2026-11-03 ("Buat saklar PKP"): satu saklar status pajak di Pengaturan Perusahaan,
disimpan di `company_settings` (type `general`) field `tax_profile`.

* NON-PKP (bawaan; keputusan K11 "DA bukan PKP"):
    - dokumen penjualan (AR, Penjualan Langsung, tagihan maklon) TIDAK BOLEH memungut PPN;
    - PPN yang ditagih supplier PKP tidak dapat dikreditkan → bagian harga beli
      (`kapitalisasi`), BUKAN aset 1-1501 PPN Masukan.
* PKP:
    - PPN keluaran = 12% × DPP nilai lain 11/12 (PMK 131/2024, kode transaksi 04 → efektif 11%);
    - dokumen boleh ditandai tidak kena PPN (`kena_ppn=False`), nomor & tanggal faktur dicatat;
    - PPN masukan dikreditkan (`kredit` → 1-1501).

Perlakuan PPN masukan DIBEKUKAN di dokumen saat dibuat (`input_tax_treatment`) supaya posting jurnal
tidak berubah bila status perusahaan berganti di kemudian hari.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import HTTPException

PPN_RATE = 12.0
DPP_NUM, DPP_DEN = 11, 12
KODE_TRANSAKSI = "04"
TREAT_CREDIT = "kredit"            # PKP: PPN masukan dikreditkan (1-1501)
TREAT_CAPITALIZE = "kapitalisasi"  # non-PKP: PPN masukan = bagian harga beli

NON_PKP_SALES_MSG = ("Perusahaan berstatus NON-PKP — dokumen penjualan tidak boleh memungut PPN. "
                     "Ubah Status Pajak di Pengaturan Perusahaan setelah dikukuhkan sebagai PKP.")


def effective_pct() -> float:
    """Tarif efektif PPN atas DPP (12% × 11/12 = 11%)."""
    return round(PPN_RATE * DPP_NUM / DPP_DEN, 4)


def normalize_profile(raw: Optional[dict]) -> dict:
    raw = raw or {}
    return {
        "pkp": bool(raw.get("pkp")),
        "pkp_since": str(raw.get("pkp_since") or "")[:10],
        "ppn_rate": PPN_RATE,
        "dpp_ratio": f"{DPP_NUM}/{DPP_DEN}",
        "kode_transaksi": KODE_TRANSAKSI,
        "effective_pct": effective_pct(),
    }


async def get_tax_profile(db) -> dict:
    proj = {"_id": 0, "tax_profile": 1, "npwp": 1}
    doc = await db.company_settings.find_one({"type": "general"}, proj) or await db.company_settings.find_one({}, proj) or {}
    prof = normalize_profile(doc.get("tax_profile"))
    prof["npwp"] = doc.get("npwp") or ""
    return prof


def validate_profile_update(raw: Any, npwp: str) -> dict:
    """Validasi isian Status Pajak dari Pengaturan Perusahaan → dict siap simpan (400 bila tidak sah)."""
    if not isinstance(raw, dict):
        raise HTTPException(400, "tax_profile harus berupa objek {pkp, pkp_since}.")
    pkp = bool(raw.get("pkp"))
    since = str(raw.get("pkp_since") or "").strip()[:10]
    if pkp:
        if not (npwp or "").strip():
            raise HTTPException(400, "Isi NPWP perusahaan sebelum mengaktifkan status PKP.")
        try:
            date.fromisoformat(since)
        except ValueError:
            raise HTTPException(400, "Isi tanggal pengukuhan PKP (PKP sejak) dengan format YYYY-MM-DD.")
    return {"pkp": pkp, "pkp_since": since if pkp else ""}


def output_tax(profile: dict, dpp: float, *, apply: bool = True) -> dict:
    """PPN keluaran atas DPP (nilai setelah diskon). Non-PKP atau apply=False → 0."""
    if not profile.get("pkp") or not apply:
        return {"tax_pct": 0.0, "tax_amount": 0, "dpp_nilai_lain": 0.0, "ppn_rate": 0.0,
                "kode_transaksi": "", "kena_ppn": False}
    dpp = max(float(dpp or 0), 0.0)
    dpp_lain = round(dpp * DPP_NUM / DPP_DEN, 2)
    return {"tax_pct": effective_pct(), "tax_amount": round(dpp_lain * PPN_RATE / 100),
            "dpp_nilai_lain": dpp_lain, "ppn_rate": PPN_RATE, "kode_transaksi": KODE_TRANSAKSI, "kena_ppn": True}


def tax_for_stored(doc: dict, dpp: float, round_to: int = 0) -> float:
    """Hitung ulang PPN dokumen tersimpan: dokumen ber-`ppn_rate` (dibuat lewat SSOT) memakai DPP nilai
    lain; dokumen lama memakai persen yang tersimpan (perilaku lama tidak berubah)."""
    if doc.get("ppn_rate"):
        if doc.get("kena_ppn") is False:
            return 0
        dpp_lain = round(max(float(dpp or 0), 0.0) * DPP_NUM / DPP_DEN, 2)
        return round(dpp_lain * float(doc["ppn_rate"]) / 100)
    return round(max(float(dpp or 0), 0.0) * float(doc.get("tax_pct") or 0) / 100, round_to or None)


def wants_output_tax(profile: dict, tax_pct: Any = None, kena_ppn: Any = None) -> bool:
    """Apakah dokumen penjualan dikenai PPN. Non-PKP: permintaan PPN (kena_ppn=True / tax_pct>0) DITOLAK 400.
    PKP: `kena_ppn` menentukan; bila kosong, tax_pct>0 atau tax_pct kosong (bawaan) = kena PPN."""
    try:
        pct = float(tax_pct) if tax_pct not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "tax_pct harus angka.")
    if pct is not None and pct < 0:
        raise HTTPException(400, "tax_pct tidak boleh negatif.")
    asked = kena_ppn is True or (pct is not None and pct > 0)
    if not profile.get("pkp"):
        if asked:
            raise HTTPException(400, NON_PKP_SALES_MSG)
        return False
    if kena_ppn is not None:
        return bool(kena_ppn)
    return pct is None or pct > 0


def faktur_fields(body: dict) -> dict:
    """Nomor & tanggal faktur pajak (diisi setelah faktur terbit di Coretax; boleh kosong saat draft)."""
    num = str((body or {}).get("faktur_number") or "").strip()[:40]
    tgl = str((body or {}).get("faktur_date") or "").strip()[:10]
    if tgl:
        try:
            date.fromisoformat(tgl)
        except ValueError:
            raise HTTPException(400, "faktur_date tidak valid (YYYY-MM-DD).")
    return {"faktur_number": num, "faktur_date": tgl}


def input_tax_treatment(profile: dict) -> str:
    return TREAT_CREDIT if profile.get("pkp") else TREAT_CAPITALIZE
