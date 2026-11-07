"""Alat baca SETORAN marketplace (dana dilepas) & biaya platform (Asisten AI, agen data).

Membungkus ``GET /api/marketing/analitik/setoran``.
"""
from __future__ import annotations

from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat_base import alat

TANGGAL = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}


@alat(
    name="setoran_marketplace",
    kind="read",
    label="Membaca setoran marketplace",
    description=(
        "Laporan dana dilepas (setoran/pencairan) marketplace per periode TANGGAL DANA DILEPAS (bukan tanggal "
        "pesanan) — satu-satunya sumber biaya platform. Per baris dan total: setoran (jumlah laporan), bruto "
        "(Rp penjualan kotor menurut platform), refund, diskon_penjual, subsidi_ongkir, penyesuaian, biaya per "
        "jenis {Komisi platform, Biaya layanan, Komisi afiliasi, Potongan iklan, Potongan lain} (Rp), "
        "total_biaya, biaya_persen_dari_bruto, neto_diterima (Rp yang masuk saldo toko).\n"
        "kelompok: toko, platform, bulan. Data contoh dibuang. Mengikuti CV dan toko yang boleh dilihat "
        "pengguna. Tanpa tanggal = awal bulan berjalan s.d. hari ini. Angka ini berbeda dari omzet toko karena "
        "pencairan tertinggal beberapa hari dan sudah dipotong."),
    input_schema={
        "type": "object",
        "properties": {
            "dari": {**TANGGAL, "description": "Tanggal dana dilepas awal (YYYY-MM-DD)."},
            "sampai": {**TANGGAL, "description": "Tanggal dana dilepas akhir (YYYY-MM-DD), inklusif."},
            "kelompok": {"type": "string", "enum": ["toko", "platform", "bulan"], "description": "Bawaan: toko."},
            "toko_id": {"type": "string", "description": "Id satu toko (opsional)."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="setoran",
)
async def setoran_marketplace(ctx, args: dict) -> dict:
    args = args or {}
    dari, sampai = B.periode_bawaan(ctx, args)
    data = await ctx.api("GET", "/api/marketing/analitik/setoran", params=B.params(
        dari=dari, sampai=sampai, kelompok=args.get("kelompok") or "toko", toko_id=args.get("toko_id"),
        limit=50))
    return {"hasil": B.padatkan(data), "_sumber": "Laporan dana dilepas marketplace"}
