"""Alat baca IKLAN: belanja, omzet atribusi, ROAS (Asisten AI, agen data).

Membungkus ``GET /api/marketing/analitik/iklan``.
"""
from __future__ import annotations

from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat_base import alat

TANGGAL = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}


@alat(
    name="kinerja_iklan",
    kind="read",
    label="Membaca kinerja iklan",
    description=(
        "Kinerja iklan toko online pada periode tanggal iklan: belanja (Rp), omzet_atribusi (Rp, omzet yang "
        "DILAPORKAN platform iklan — bukan omzet rekap toko), roas (omzet_atribusi ÷ belanja, kali), impresi, "
        "klik, konversi, ctr_persen, cpc (Rp per klik), biaya_per_konversi (Rp). Total juga memuat omzet_toko "
        "(omzet baku rekap harian) dan rasio_iklan_terhadap_omzet_persen (belanja ÷ omzet toko).\n"
        "kelompok: toko, kampanye, saluran (Shopee Ads, TikTok Ads, Meta, Google, afiliasi), hari, minggu, "
        "bulan. Laporan iklan yang mencakup beberapa hari dihitung pada tanggal awal laporannya. Data contoh "
        "dibuang. Tidak ada data = ROAS tidak bisa dihitung (bukan 0). Mengikuti CV dan toko yang boleh dilihat "
        "pengguna. Tanpa tanggal = awal bulan berjalan s.d. hari ini."),
    input_schema={
        "type": "object",
        "properties": {
            "dari": {**TANGGAL, "description": "Tanggal awal (YYYY-MM-DD)."},
            "sampai": {**TANGGAL, "description": "Tanggal akhir (YYYY-MM-DD), inklusif."},
            "kelompok": {"type": "string", "enum": ["toko", "kampanye", "saluran", "hari", "minggu", "bulan"],
                         "description": "Bawaan: toko."},
            "toko_id": {"type": "string", "description": "Id satu toko (opsional)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 40, "description": "Banyak baris. Bawaan 15."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="iklan",
)
async def kinerja_iklan(ctx, args: dict) -> dict:
    args = args or {}
    dari, sampai = B.periode_bawaan(ctx, args)
    kelompok = args.get("kelompok") or "toko"
    lim = 400 if kelompok in ("hari", "minggu", "bulan") else B.angka(args.get("limit"), 1, 40, 15)
    data = await ctx.api("GET", "/api/marketing/analitik/iklan", params=B.params(
        dari=dari, sampai=sampai, kelompok=kelompok, toko_id=args.get("toko_id"), limit=lim))
    return {"hasil": B.padatkan(data), "_sumber": "Data iklan Marketing"}
