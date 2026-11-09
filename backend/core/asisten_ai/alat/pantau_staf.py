"""Alat BACA Asisten AI: Monitoring Staf ERP (10 Nov 2026, tahap 5 usulan owner).

Membaca layar Manajemen › Monitoring Staf lewat endpointnya sendiri (`/api/pantau-staf/*`) dengan token pengguna,
jadi aturan akses yang sama berlaku: hanya owner & admin (keputusan K3) — peran lain mendapat galat akses.
Angka = angka layar (satu sumber `core.pantau_staf.ringkasan`): kepatuhan %, kewajiban terlambat, aktivitas harian.
AI hanya membaca dan menjelaskan; aturan kewajiban diubah owner di layar Aturan Kewajiban.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat

_MAKS_STAF = 40
_MAKS_MACET = 40
_MAKS_HARI = 14
_POLA_TANGGAL = r"^\d{4}-\d{2}-\d{2}$"


def _ringkas_kejadian(k: dict) -> dict:
    return {k2: v for k2, v in {
        "langkah": k.get("nama"), "alur": k.get("alur_label"), "dokumen": k.get("nomor") or k.get("periode"),
        "keterangan": k.get("keterangan") or None, "status": k.get("status"), "menunggu": k.get("pemegang"),
        "sejak": k.get("mulai"), "batas": k.get("tenggat"), "terlambat_hari_kerja": k.get("terlambat_hari_kerja"),
        "langkah_sebelumnya": k.get("sebelumnya"), "dikerjakan_oleh": k.get("pelaku_nama"),
        "dikerjakan_orang_lain": k.get("oleh_orang_lain") or None, "selesai": k.get("selesai_at"),
    }.items() if v not in (None, "", [])}


@alat(
    name="pantau_staf",
    kind="read",
    label="Membaca monitoring staf",
    description=(
        "Monitoring staf ERP (Manajemen › Monitoring Staf): apakah tiap staf benar-benar memakai sistem. "
        "`bagian`: 'ringkasan' = per staf (hari aktif/hari kerja, aktif terakhir, kewajiban selesai/terlambat/"
        "menunggu, kepatuhan % = kewajiban selesai tepat waktu oleh pemegangnya ÷ kewajiban yang sudah jatuh tempo, "
        "nilai A–E pita KPI; bulan pertama = uji coba tanpa sanksi); 'macet' = kewajiban yang sedang terlambat: "
        "langkah apa, dokumen apa, menunggu siapa, sejak kapan, langkah sebelumnya oleh siapa; 'staf' = rincian "
        "satu staf (`user_id` dari ringkasan): kewajiban terbuka, riwayat, dan aktivitas per hari (menu yang dibuka, "
        "berapa kali simpan/setujui); 'alur' = per langkah alur (pemegang, jumlah menunggu/terlambat, rata-rata jam "
        "penyelesaian). Bukti selesai diambil dari data dokumen, bukan centang staf. Periode bawaan minggu berjalan."),
    input_schema={
        "type": "object",
        "properties": {
            "bagian": {"type": "string", "enum": ["ringkasan", "macet", "staf", "alur"]},
            "dari": {"type": "string", "pattern": _POLA_TANGGAL, "description": "Awal periode YYYY-MM-DD."},
            "sampai": {"type": "string", "pattern": _POLA_TANGGAL, "description": "Akhir periode YYYY-MM-DD."},
            "user_id": {"type": "string", "maxLength": 80, "description": "Wajib untuk bagian 'staf'."},
        },
        "required": ["bagian"],
        "additionalProperties": False,
    },
    domain="umum",
)
async def pantau_staf(ctx, args: dict) -> dict:
    bagian = args.get("bagian") or "ringkasan"
    params = {k: args[k] for k in ("dari", "sampai") if args.get(k)}
    if bagian == "macet":
        data = await ctx.api("GET", "/api/pantau-staf/macet") or {}
        items = data.get("items") or []
        hasil = {"jumlah_terlambat": len(items), "kewajiban": [_ringkas_kejadian(k) for k in items[:_MAKS_MACET]]}
        if len(items) > _MAKS_MACET:
            hasil["catatan"] = f"Hanya {_MAKS_MACET} yang paling lama terlambat yang ditampilkan."
        return {"hasil": hasil, "_sumber": "Monitoring Staf › Macet sekarang"}
    if bagian == "staf":
        uid = (args.get("user_id") or "").strip()
        if not uid:
            return {"hasil": {"galat": "Isi user_id dari bagian 'ringkasan' dulu."}, "_sumber": "Monitoring Staf"}
        d = await ctx.api("GET", f"/api/pantau-staf/staf/{uid}", params=params) or {}
        hari = d.get("aktivitas") or []
        return {"hasil": {
            "staf": d.get("user"), "skor": d.get("skor"), "masa_uji": d.get("masa_uji"),
            "kewajiban_terbuka": [_ringkas_kejadian(k) for k in (d.get("terbuka") or [])[:_MAKS_MACET]],
            "riwayat": [_ringkas_kejadian(k) for k in (d.get("riwayat") or [])[:_MAKS_MACET]],
            "membantu_orang_lain": d.get("membantu_orang_lain"),
            "aktivitas_per_hari": [{"tanggal": h.get("tanggal"), "pertama": h.get("pertama"),
                                    "terakhir": h.get("terakhir"),
                                    "menu": [{"menu": m.get("label"), "dilihat": m.get("lihat"),
                                              "simpan": m.get("simpan"), "setujui": m.get("setujui")}
                                             for m in (h.get("modul") or [])[:8]]}
                                   for h in hari[:_MAKS_HARI]],
        }, "_sumber": "Monitoring Staf › rincian staf"}
    if bagian == "alur":
        d = await ctx.api("GET", "/api/pantau-staf/alur", params=params) or {}
        out = []
        for g in d.get("alur") or []:
            langkah = [{"langkah": x.get("nama"), "aktif": x.get("aktif"), "pemegang": x.get("pemegang"),
                        "batas_waktu": x.get("tenggat_label"), "menunggu": x.get("menunggu"),
                        "terlambat": x.get("terlambat"), "rata_jam_selesai": x.get("rata_jam")}
                       for x in g.get("langkah") or []]
            out.append({"alur": g.get("label"), "langkah": langkah})
        return {"hasil": {"periode": [d.get("dari"), d.get("sampai")], "alur": out},
                "_sumber": "Monitoring Staf › Per alur"}
    d = await ctx.api("GET", "/api/pantau-staf/staf", params=params) or {}
    items = d.get("items") or []
    staf = [{"user_id": r.get("user_id"), "nama": r.get("nama"), "peran": r.get("peran"),
             "aktif_terakhir": r.get("aktif_terakhir"), "hari_aktif": r.get("hari_aktif"),
             "hari_kerja": r.get("hari_kerja"), "kewajiban_dinilai": r.get("dinilai"),
             "selesai_tepat_waktu": r.get("tepat"), "terlambat_sekarang": r.get("terlambat"),
             "menunggu": r.get("menunggu"), "dikerjakan_orang_lain": r.get("oleh_orang_lain"),
             "kepatuhan_persen": r.get("kepatuhan"), "nilai": (r.get("nilai") or {}).get("huruf")}
            for r in items[:_MAKS_STAF]]
    return {"hasil": {"periode": [d.get("dari"), d.get("sampai")], "masa_uji": d.get("masa_uji"), "staf": staf},
            "_sumber": "Monitoring Staf › Per staf"}
