"""Skill Merchandiser untuk Asisten AI (keputusan owner K-M1..K-M10, 12 Nov 2026).

Membungkus `GET /api/merchandiser/analisa` dan `GET /api/merchandiser/cek-rencana` (SATU sumber angka:
`core.merchandiser`). Dipakai untuk pertanyaan seperti "model apa yang harus distop?", "boleh tambah PO Mave
500 pcs?", dan sebelum menyiapkan kartu PO produksi / PR bahan.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat

_SUMBER = "Analisa Merchandiser (penjualan marketplace, stok barang jadi, PO produksi internal)"


@alat(name="analisa_merchandiser", kind="read", label="Menganalisa laju jual & persediaan", domain="stok", kode=True,
      description=(
          "Skill MERCHANDISER: per model (atau per warna / varian) — laju jual mingguan (N minggu terakhir), stok "
          "barang jadi PERKIRAAN (stok sistem dikurangi penjualan yang belum tercatat scan keluar), WIP (sisa PO "
          "produksi internal yang masih berjalan), minggu persediaan = (stok + WIP) ÷ laju, sell-through, tren vs N "
          "minggu sebelumnya, kelas (mati / lambat > 16 mgg / perlu awas 8–16 / sehat 3–8 / laris < 3 / habis-masih-"
          "terjual), nilai stok (Rp HPP), toko terlaris, dan saran (stop, tahan, promo/markdown, pindah toko, tambah "
          "produksi). Hasil juga memuat cakupan data (penjualan yang belum terhubung ke model, penjualan yang belum "
          "scan keluar) — SELALU sebutkan cakupan dan bahwa stok adalah perkiraan bila ada penjualan belum scan "
          "keluar. Pakai untuk pertanyaan model mana yang tidak laku / harus distop / perlu ditambah, dan sebelum "
          "menyarankan PO produksi atau pembelian bahan."),
      input_schema={"type": "object", "additionalProperties": False, "properties": {
          "tingkat": {"type": "string", "enum": ["model", "warna", "varian"], "description": "Bawaan: model."},
          "minggu": {"type": "integer", "minimum": 1, "maximum": 26, "description": "Periode laju jual (bawaan 4)."},
          "toko_id": {"type": "string", "maxLength": 80, "description": "Satu toko (opsional)."},
          "model_id": {"type": "string", "maxLength": 80, "description": "Satu model (opsional)."},
          "kelas": {"type": "array", "items": {"type": "string",
                                                "enum": ["mati", "lambat", "awas", "sehat", "laris", "habis"]}},
          "batas": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Banyak baris (bawaan 40)."}}})
async def analisa_merchandiser(ctx, args: dict) -> dict:
    args = args or {}
    params = {"tingkat": args.get("tingkat") or "model"}
    for k_in, k_out in (("minggu", "minggu"), ("toko_id", "toko"), ("model_id", "model_id")):
        if args.get(k_in):
            params[k_out] = args[k_in]
    if args.get("kelas"):
        params["kelas"] = ",".join(args["kelas"])
    data = await ctx.api("GET", "/api/merchandiser/analisa", params=params)
    batas = int(args.get("batas") or (2000 if getattr(ctx, "pemanggil", "") == "kode" else 40))
    baris = list((data or {}).get("baris") or [])
    out = {**(data or {}), "baris": baris[:batas]}
    if len(baris) > batas:
        out["catatan_baris"] = f"{len(baris)} baris; ditampilkan {batas} teratas (urut risiko: mati, lambat, awas…)."
    return {"hasil": out, "_sumber": _SUMBER}


@alat(name="cek_rencana_produksi", kind="read", label="Memeriksa rencana produksi", domain="produksi",
      description=(
          "Periksa rencana produksi / pembelian bahan untuk SATU model (opsional satu varian) sebelum PO dibuat: "
          "persediaan sekarang vs sesudah tambahan `qty` pcs, kelas model, dan keputusan `aman` atau `perlu_alasan` "
          "beserta alasannya (model lambat/mati, atau persediaan sesudahnya melewati batas perlu awas). Pakai sebelum "
          "menyiapkan kartu PO produksi atau PR bahan, dan sampaikan hasilnya ke pengguna."),
      input_schema={"type": "object", "additionalProperties": False, "required": ["model_id", "qty"], "properties": {
          "model_id": {"type": "string", "maxLength": 80},
          "variant_id": {"type": "string", "maxLength": 80},
          "qty": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000000}}})
async def cek_rencana_produksi(ctx, args: dict) -> dict:
    params = {"model_id": args["model_id"], "qty": args["qty"]}
    if args.get("variant_id"):
        params["variant_id"] = args["variant_id"]
    data = await ctx.api("GET", "/api/merchandiser/cek-rencana", params=params)
    return {"hasil": data, "_sumber": _SUMBER}
