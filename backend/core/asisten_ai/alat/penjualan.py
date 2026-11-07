"""Alat baca PENJUALAN toko online (Asisten AI, agen data).

Membungkus ``GET /api/marketing/analitik/penjualan`` lewat ``ctx.api`` — token, CV,
lingkup toko, dan izin modul pemakai berlaku apa adanya.
"""
from __future__ import annotations

from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat_base import alat

TANGGAL = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}

DESKRIPSI = (
    "Membaca omzet toko online (Shopee, TikTok, dan toko marketplace lain) dengan definisi baku perusahaan: "
    "omzet = penjualan produk setelah diskon penjual dan sebelum potongan platform, dalam Rupiah, diambil dari "
    "rekap harian; pesanan batal dan pesanan belum dibayar TIDAK dihitung; retur dilaporkan terpisah "
    "(omzet_setelah_retur = omzet - retur_nilai); data contoh dibuang. Tanggal = tanggal pesanan (WIB).\n"
    "Hasil: total {omzet (Rp), pesanan, unit (pcs), pembeli (jumlah pembeli unik), aov (Rp per pesanan), "
    "retur_nilai (Rp), retur_pesanan, omzet_setelah_retur (Rp), batal_pesanan, belum_bayar_pesanan} dan "
    "rincian per kelompok:\n"
    "- toko: per akun toko; platform: Shopee/TikTok/...;\n"
    "- kanal: ASAL pesanan di platform (live, video, kartu produk, iklan, afiliasi, kampanye, pencarian, "
    "organik, lainnya) — dibaca dari pesanan impor, disertai cakupan terhadap total;\n"
    "- produk: per model produk (semua warna/ukuran); sku: per SKU barang jadi lintas toko;\n"
    "- hari, minggu (Senin–Minggu), bulan: deret waktu.\n"
    "Opsional pembanding: periode_sebelumnya (rentang sama panjang tepat sebelumnya) atau tahun_lalu "
    "(tanggal sama setahun lalu) — memberi total pembanding, selisih nilai & persen, dan pembanding per baris. "
    "Mengikuti CV yang dipilih (toko online milik CV Dewi Aditya) dan hanya toko yang boleh dilihat pengguna. "
    "Tanpa tanggal = awal bulan berjalan s.d. hari ini. Biaya platform TIDAK ada di sini (pakai setoran_marketplace)."
)


@alat(
    name="ringkasan_penjualan",
    kind="read",
    label="Membaca ringkasan penjualan",
    description=DESKRIPSI,
    input_schema={
        "type": "object",
        "properties": {
            "dari": {**TANGGAL, "description": "Tanggal awal (YYYY-MM-DD), tanggal pesanan WIB."},
            "sampai": {**TANGGAL, "description": "Tanggal akhir (YYYY-MM-DD), inklusif. Rentang maks. 400 hari."},
            "kelompok": {"type": "string",
                         "enum": ["toko", "platform", "kanal", "produk", "sku", "hari", "minggu", "bulan"],
                         "description": "Cara merinci. Bawaan: toko."},
            "bandingkan": {"type": "string", "enum": ["periode_sebelumnya", "tahun_lalu", "tidak"],
                           "description": "Pembanding. Bawaan: tidak."},
            "toko_id": {"type": "string", "description": "Id satu toko bila hanya satu toko yang ditanyakan."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                      "description": "Banyak baris rincian (kelompok non-waktu). Bawaan 15."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="penjualan",
)
async def ringkasan_penjualan(ctx, args: dict) -> dict:
    args = args or {}
    dari, sampai = B.periode_bawaan(ctx, args)
    kelompok = args.get("kelompok") or "toko"
    waktu = kelompok in ("hari", "minggu", "bulan")
    data = await ctx.api("GET", "/api/marketing/analitik/penjualan", params=B.params(
        dari=dari, sampai=sampai, kelompok=kelompok, bandingkan=args.get("bandingkan") or "tidak",
        toko_id=args.get("toko_id"),
        limit=None if waktu else B.angka(args.get("limit"), 1, 50, 15)))
    return {"hasil": B.padatkan(data),
            "_sumber": "Rekap penjualan harian Marketing"}
