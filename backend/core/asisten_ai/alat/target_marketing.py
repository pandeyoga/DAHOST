"""Alat baca TARGET toko vs aktual (Asisten AI, agen data).

Membungkus ``GET /api/marketing/analitik/target``.
"""
from __future__ import annotations

from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat_base import alat

BULAN = {"type": "string", "pattern": r"^\d{4}-\d{2}$"}


@alat(
    name="target_toko",
    kind="read",
    label="Membaca target toko",
    description=(
        "Target bulanan toko online vs aktual, per toko per bulan. Target dari layar Target & Budget "
        "Marketing (target omzet Rp dan target pesanan); aktual memakai definisi omzet baku (penjualan produk "
        "setelah diskon penjual, sebelum potongan platform; batal & belum dibayar tidak dihitung; retur tidak "
        "dikurangkan).\n"
        "Setiap baris: toko, bulan, target_omzet, aktual_omzet, capaian_omzet_persen, target_pesanan, "
        "aktual_pesanan, capaian_pesanan_persen, status (sesuai_jalur ≥90%, waspada 70–89%, tertinggal <70%, "
        "tanpa_target). Untuk bulan berjalan juga hari_berlalu, proyeksi_omzet_akhir_bulan (laju harian × hari "
        "dalam bulan) dan proyeksi_capaian_persen; statusnya dinilai terhadap target yang seharusnya sudah "
        "tercapai sampai hari ini. Total semua toko ikut. Maks. 24 bulan. Tanpa bulan = bulan berjalan. "
        "Hanya MEMBACA; tidak bisa memasang target."),
    input_schema={
        "type": "object",
        "properties": {
            "dari_bulan": {**BULAN, "description": "Bulan awal (YYYY-MM)."},
            "sampai_bulan": {**BULAN, "description": "Bulan akhir (YYYY-MM), inklusif."},
            "toko_id": {"type": "string", "description": "Id satu toko (opsional)."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="penjualan",
)
async def target_toko(ctx, args: dict) -> dict:
    args = args or {}
    b0 = args.get("dari_bulan") or args.get("sampai_bulan") or B.bulan_ini(ctx)
    b1 = args.get("sampai_bulan") or b0
    data = await ctx.api("GET", "/api/marketing/analitik/target", params=B.params(
        dari_bulan=b0, sampai_bulan=b1, toko_id=args.get("toko_id")))
    return {"hasil": B.padatkan(data), "_sumber": "Target toko & rekap penjualan harian"}
