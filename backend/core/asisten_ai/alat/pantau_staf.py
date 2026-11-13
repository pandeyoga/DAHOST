"""Alat BACA Asisten AI: Pemantauan Staf ERP (10 Nov 2026, tahap 5 usulan owner; alur kerja harian 14 Nov 2026).

Membaca layar Manajemen › Pemantauan staf lewat endpointnya sendiri (`/api/pantau-staf/*`) dengan token pengguna,
jadi aturan akses yang sama berlaku: hanya owner & admin (keputusan K3) — peran lain mendapat galat akses.
Angka = angka layar (satu sumber `core.pantau_staf.ringkasan` & `core.pantau_staf.alur_kerja`): kepatuhan %, kewajiban
terlambat, alur kerja per langkah (dikerjakan siapa, yang menunggu, di mana macet), pekerjaan tiap staf per hari.
AI hanya membaca dan menjelaskan; aturan kewajiban diubah owner di layar Aturan Kewajiban.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat

_MAKS_STAF = 40
_MAKS_MACET = 40
_MAKS_HARI = 14
_MAKS_RINCI = 8
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
    label="Membaca pemantauan staf",
    description=(
        "Pemantauan staf ERP (Manajemen › Pemantauan staf): apakah tiap staf benar-benar memakai sistem. "
        "`bagian`: 'alur' = alur kerja SATU HARI (`tanggal`, bawaan hari ini) per alur bisnis (produksi: order "
        "cutting → mulai cutting → catat hasil potong → selesai → buat PO → konfirmasi PO → kirim ke CMT → terima & QC "
        "→ stok barang jadi → scan keluar → tutup hari; pesanan marketplace per toko; R&D; aksesoris; gudang barang "
        "jadi; SDM; keuangan; perubahan data master), langkah berurutan: berapa dikerjakan & oleh siapa, yang "
        "menunggu sekarang (lewat batas = macet), catatan kejanggalan (hasil potong jauh di atas rencana, scan keluar "
        "dibatalkan semua, PO draf yang sudah dikirim ke CMT, belum ada biaya iklan), dan kalimat 'macet di langkah N'; "
        "'aktivitas' = pekerjaan tiap staf hari itu dalam kalimat staf + akun yang hanya membuka layar atau tidak aktif; "
        "'ringkasan' = kepatuhan per staf (hari aktif/hari kerja, aktif terakhir, kewajiban selesai/terlambat/"
        "menunggu, kepatuhan % = kewajiban selesai tepat waktu oleh pemegangnya ÷ kewajiban yang sudah jatuh tempo, "
        "nilai A–E pita KPI; bulan pertama = uji coba tanpa sanksi); 'macet' = kewajiban yang sedang terlambat: "
        "langkah apa, dokumen apa, menunggu siapa, sejak kapan, langkah sebelumnya oleh siapa; 'staf' = rincian "
        "satu staf (`user_id` dari ringkasan): kewajiban terbuka, riwayat, dan aktivitas per hari (menu yang dibuka, "
        "berapa kali simpan/setujui). Bukti selesai diambil dari data dokumen, bukan centang staf. Periode "
        "(`dari`/`sampai`) bawaan minggu berjalan; `tanggal` untuk 'alur' & 'aktivitas'."),
    input_schema={
        "type": "object",
        "properties": {
            "bagian": {"type": "string", "enum": ["ringkasan", "macet", "staf", "alur", "aktivitas"]},
            "tanggal": {"type": "string", "pattern": _POLA_TANGGAL,
                        "description": "Satu hari YYYY-MM-DD untuk 'alur' & 'aktivitas' (bawaan hari ini)."},
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
        return {"hasil": hasil, "_sumber": "Pemantauan staf › Kewajiban terlambat"}
    if bagian == "staf":
        uid = (args.get("user_id") or "").strip()
        if not uid:
            return {"hasil": {"galat": "Isi user_id dari bagian 'ringkasan' dulu."}, "_sumber": "Pemantauan staf"}
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
        }, "_sumber": "Pemantauan staf › rincian staf"}
    if bagian == "alur":
        p = {"tanggal": args["tanggal"]} if args.get("tanggal") else {}
        d = await ctx.api("GET", "/api/pantau-staf/alur", params=p) or {}
        out = []
        for g in d.get("alur") or []:
            langkah = []
            for x in g.get("langkah") or []:
                row = {"no": x.get("urutan"), "langkah": x.get("nama"), "keadaan": x.get("keadaan"),
                       "dikerjakan": x.get("dikerjakan"), "jumlah": x.get("jumlah") or None,
                       "satuan_jumlah": x.get("jumlah_satuan") or None,
                       "oleh": [f"{p_['nama']} {p_['kali']}×" for p_ in x.get("pelaku") or []],
                       "menunggu_sekarang": x.get("menunggu"), "lewat_batas": x.get("lewat_batas"),
                       "terlama_sejak": x.get("terlama_sejak"), "penanggung_jawab": x.get("penanggung_jawab") or None,
                       "catatan": [c.get("pesan") if not c.get("nomor") else f"{c['nomor']}: {c.get('pesan')}"
                                   for c in x.get("catatan") or []] or None,
                       "contoh_menunggu": [{"dokumen": t.get("nomor"), "sejak": t.get("sejak"),
                                            "lewat_batas": t.get("lewat_batas"), "keterangan": t.get("keterangan")}
                                           for t in (x.get("rincian_tunggu") or [])[:_MAKS_RINCI]] or None}
                langkah.append({k: v for k, v in row.items() if v not in (None, [], "")})
            out.append({"alur": g.get("label"), "keadaan": g.get("kalimat"), "langkah": langkah})
        return {"hasil": {"tanggal": d.get("tanggal"), "ringkasan": d.get("ringkasan"), "alur": out},
                "_sumber": "Pemantauan staf › Alur kerja"}
    if bagian == "aktivitas":
        p = {"tanggal": args["tanggal"]} if args.get("tanggal") else {}
        d = await ctx.api("GET", "/api/pantau-staf/aktivitas", params=p) or {}
        label = {"bekerja": "mencatat pekerjaan", "hanya_membuka": "hanya membuka sistem", "tidak_aktif": "tidak aktif"}
        staf = [{"nama": r.get("nama"), "peran": r.get("peran"), "keadaan": label.get(r.get("keadaan"), r.get("keadaan")),
                 "jam": [r.get("pertama"), r.get("terakhir")] if r.get("pertama") else None,
                 "pekerjaan": [p_.get("kalimat") for p_ in r.get("pekerjaan") or []] or None,
                 "tanya_asisten": r.get("tanya_asisten") or None}
                for r in (d.get("items") or [])[:_MAKS_STAF]]
        return {"hasil": {"tanggal": d.get("tanggal"), "ringkasan": d.get("ringkasan"),
                          "staf": [{k: v for k, v in r.items() if v is not None} for r in staf]},
                "_sumber": "Pemantauan staf › Aktivitas staf"}
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
            "_sumber": "Pemantauan staf › Kepatuhan"}
