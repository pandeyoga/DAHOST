"""Alat baca PRODUK terlaris/terbawah + marjin (Asisten AI, agen data).

Membungkus ``GET /api/marketing/analitik/produk``.
"""
from __future__ import annotations

from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat_base import alat

TANGGAL = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}


@alat(
    name="analisis_produk",
    kind="read",
    label="Membaca penjualan per produk",
    description=(
        "Daftar produk toko online paling laku (teratas) atau paling sepi (terbawah) menurut omzet pada "
        "periode tanggal pesanan WIB. Omzet produk = subtotal baris SKU setelah diskon penjual, sebelum "
        "potongan platform (Rp); pesanan batal & belum dibayar tidak dihitung; data contoh dibuang.\n"
        "Setiap baris: label (nama produk), sku, unit (pcs), omzet (Rp), pesanan, toko (jumlah toko yang "
        "menjual), hpp (Rp total), laba_kotor (Rp), margin_persen, hpp_cakupan_persen. HPP per unit = HPP yang "
        "dibekukan di baris pesanan (hpp_snapshot), cadangan HPP katalog; marjin hanya untuk unit yang punya "
        "HPP — selalu sebut cakupan HPP bila di bawah 80%. Total memuat jumlah produk, unit, omzet, "
        "hpp_cakupan_persen, laba_kotor, margin_persen.\n"
        "cara: produk = per model (semua warna/ukuran & toko digabung); sku = per SKU barang jadi lintas toko; "
        "katalog = per item katalog per toko. Produk tanpa penjualan tidak muncul. Mengikuti CV dan toko yang "
        "boleh dilihat pengguna. Tanpa tanggal = awal bulan berjalan s.d. hari ini."),
    input_schema={
        "type": "object",
        "properties": {
            "dari": {**TANGGAL, "description": "Tanggal awal (YYYY-MM-DD)."},
            "sampai": {**TANGGAL, "description": "Tanggal akhir (YYYY-MM-DD), inklusif."},
            "urut": {"type": "string", "enum": ["teratas", "terbawah"], "description": "Bawaan: teratas."},
            "cara": {"type": "string", "enum": ["produk", "sku", "katalog"], "description": "Bawaan: produk."},
            "toko_id": {"type": "string", "description": "Id satu toko (opsional)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Banyak baris. Bawaan 10."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="penjualan",
)
async def analisis_produk(ctx, args: dict) -> dict:
    args = args or {}
    dari, sampai = B.periode_bawaan(ctx, args)
    data = await ctx.api("GET", "/api/marketing/analitik/produk", params=B.params(
        dari=dari, sampai=sampai, urut=args.get("urut") or "teratas", cara=args.get("cara") or "produk",
        toko_id=args.get("toko_id"), limit=B.angka(args.get("limit"), 1, 30, 10)))
    return {"hasil": B.padatkan(data), "_sumber": "Pesanan toko online & HPP produk"}
