"""Alat baca LIVE SELLING per host/toko (Asisten AI, agen data).

Membungkus ``GET /api/marketing/analitik/live``.
"""
from __future__ import annotations

from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat_base import alat

TANGGAL = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}


@alat(
    name="kinerja_live",
    kind="read",
    label="Membaca kinerja live",
    description=(
        "Kinerja sesi live selling pada periode tanggal sesi: sesi (jumlah sesi, tanpa yang batal), omzet (Rp, "
        "omzet sesi yang dicatat/diimpor per sesi — BAGIAN dari omzet toko, bukan tambahan), pesanan, jam_live, "
        "penonton, omzet_per_jam (Rp), konversi_persen (pesanan ÷ penonton).\n"
        "kelompok: host (per host live), toko, hari, minggu, bulan. Data contoh dibuang. Tidak memuat gaji atau "
        "bayaran host. Mengikuti CV dan toko yang boleh dilihat pengguna. Tanpa tanggal = awal bulan berjalan "
        "s.d. hari ini."),
    input_schema={
        "type": "object",
        "properties": {
            "dari": {**TANGGAL, "description": "Tanggal awal (YYYY-MM-DD)."},
            "sampai": {**TANGGAL, "description": "Tanggal akhir (YYYY-MM-DD), inklusif."},
            "kelompok": {"type": "string", "enum": ["host", "toko", "hari", "minggu", "bulan"],
                         "description": "Bawaan: host."},
            "toko_id": {"type": "string", "description": "Id satu toko (opsional)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 40, "description": "Banyak baris. Bawaan 15."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="live",
)
async def kinerja_live(ctx, args: dict) -> dict:
    args = args or {}
    dari, sampai = B.periode_bawaan(ctx, args)
    kelompok = args.get("kelompok") or "host"
    lim = 400 if kelompok in ("hari", "minggu", "bulan") else B.angka(args.get("limit"), 1, 40, 15)
    data = await ctx.api("GET", "/api/marketing/analitik/live", params=B.params(
        dari=dari, sampai=sampai, kelompok=kelompok, toko_id=args.get("toko_id"), limit=lim))
    return {"hasil": B.padatkan(data), "_sumber": "Sesi live Marketing"}
