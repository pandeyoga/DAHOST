"""Alat Asisten AI Marketing (agen MKT-AI, 9 Nov 2026): analisis impor & Laporan Marketing mode AI.

* `analisis_impor`          — temuan berangka hasil impor (paket banyak berkas atau satu sesi impor):
                              omzet naik/turun tajam, batal melonjak, iklan aneh, SKU belum tertaut,
                              selisih vs laporan penghasilan, baris ditolak. Angka dihitung server
                              (`GET /api/marketing/impor-paket/.../analisis`).
* `paket_laporan_marketing` — paket fakta laporan mingguan/bulanan (KPI, pembanding, per toko/
                              platform/kanal/produk, iklan, live, setoran, komplain, anomali,
                              kualitas data) dari pembaca resmi (`GET /api/marketing/laporan-ai/fakta`).
* `buat_laporan_marketing`  — berkas PDF/Excel lewat `core.laporan_ai`, SETELAH penjaga angka
                              memastikan setiap angka di laporan ada di paket fakta.

Semua lewat `ctx.api` (token, CV, lingkup toko, izin modul pengguna berlaku apa adanya).
"""
from __future__ import annotations

from core import laporan_ai as la
from core import laporan_marketing as lm
from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat.laporan import SKEMA as SKEMA_LAPORAN
from core.asisten_ai.alat_base import AlatError, alat

TANGGAL = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}


@alat(
    name="analisis_impor",
    kind="read",
    label="Menganalisis hasil impor data marketing",
    description=(
        "Membaca TEMUAN BERANGKA dari hasil impor data Marketing (ekspor Seller Center yang diunggah staf): "
        "omzet harian di luar ±2 simpangan baku 28 hari sebelumnya, lonjakan pesanan batal, SKU belum tertaut "
        "katalog (omzet tetap masuk, HPP/stok belum), diskon yang dibiayai platform, kampanye iklan rugi / biaya "
        "per pesanan tidak wajar / biaya berubah tajam, selisih omzet pesanan vs laporan penghasilan, dan baris "
        "ditolak beserta alasannya. Isi paket_id (impor banyak berkas) ATAU sesi_id (impor satu berkas); kosong = "
        "paket impor terbaru pengguna. Semua angka dihitung server — sebut angkanya apa adanya."),
    input_schema={
        "type": "object",
        "properties": {
            "paket_id": {"type": "string", "description": "Id paket impor banyak berkas."},
            "sesi_id": {"type": "string", "description": "Id sesi impor satu berkas."},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="penjualan",
)
async def analisis_impor(ctx, args: dict) -> dict:
    args = args or {}
    if args.get("sesi_id"):
        data = await ctx.api("GET", f"/api/marketing/impor-paket/sesi/{args['sesi_id']}/analisis")
        return {"hasil": B.padatkan(data), "_sumber": "Analisis hasil impor (sesi)"}
    pid = args.get("paket_id")
    if not pid:
        daftar = await ctx.api("GET", "/api/marketing/impor-paket", params={"limit": 1})
        rows = (daftar or {}).get("paket") or []
        if not rows:
            raise AlatError(404, "Belum ada paket impor yang bisa dianalisis.")
        pid = rows[0]["id"]
    data = await ctx.api("GET", f"/api/marketing/impor-paket/{pid}/analisis")
    return {"hasil": B.padatkan(data), "_sumber": "Analisis hasil impor (paket banyak berkas)"}


@alat(
    name="paket_laporan_marketing",
    kind="read",
    label="Mengumpulkan angka Laporan Marketing",
    description=(
        "Paket FAKTA untuk Laporan Marketing mingguan/bulanan — semua angka dihitung kode dari pembaca resmi: "
        "KPI (omzet, pesanan, AOV, unit, pembeli, % batal, % retur, omzet setelah retur, belanja iklan, ROAS iklan "
        "atribusi, TACoS = iklan ÷ omzet, biaya platform % dari laporan dana dilepas, neto), pembanding periode "
        "sebelumnya (dan tahun lalu untuk bulanan), per toko (porsi, selisih, hari berdata, TACoS), per platform & "
        "kanal, omzet harian, produk teratas & terbawah, kampanye iklan, live per host, setoran per toko, target, "
        "komplain, ANOMALI (hari di luar ±2σ, toko tanpa data, batal melonjak, kampanye rugi, selisih setoran), "
        "dan kualitas data. Jenis: mingguan (bawaan pekan lalu Senin–Minggu), bulanan (bawaan bulan lalu), atau "
        "rentang (isi dari & sampai). Mengembalikan fakta_id yang WAJIB dipakai buat_laporan_marketing."),
    input_schema={
        "type": "object",
        "properties": {
            "jenis": {"type": "string", "enum": ["mingguan", "bulanan", "rentang"]},
            "dari": {**TANGGAL, "description": "Awal periode (YYYY-MM-DD), opsional."},
            "sampai": {**TANGGAL, "description": "Akhir periode (YYYY-MM-DD), opsional."},
            "toko_id": {"type": "string", "description": "Id satu toko bila laporan hanya untuk satu toko."},
        },
        "required": ["jenis"],
        "additionalProperties": False,
    },
    domain="penjualan",
    kode=True,
)
async def paket_laporan_marketing(ctx, args: dict) -> dict:
    data = await ctx.api("GET", "/api/marketing/laporan-ai/fakta", params=B.params(
        jenis=args.get("jenis") or "mingguan", dari=args.get("dari"), sampai=args.get("sampai"),
        toko_id=args.get("toko_id")))
    out = dict(data or {})
    out.pop("ok", None)
    return {"hasil": B.padatkan(out) if getattr(ctx, "pemanggil", "langsung") != "kode" else out,
            "_sumber": "Paket fakta Laporan Marketing (pembaca resmi)"}


SKEMA = {**SKEMA_LAPORAN,
         "properties": {**SKEMA_LAPORAN["properties"],
                        "fakta_id": {"type": "string", "description": "fakta_id dari paket_laporan_marketing."}},
         "required": ["fakta_id"] + list(SKEMA_LAPORAN["required"])}


@alat(
    name="buat_laporan_marketing",
    kind="read",
    label="Menyusun Laporan Marketing PDF/Excel",
    description=(
        "Membuat berkas Laporan Marketing (PDF A4 berkop dan/atau Excel) dari spesifikasi yang sama dengan "
        "buat_laporan, ditambah fakta_id dari paket_laporan_marketing. SEBELUM berkas dibuat, setiap angka rupiah/"
        "persen/jumlah di judul, teks, tabel, dan grafik diperiksa terhadap paket fakta (toleransi pembulatan): "
        "angka yang tidak ada di paket fakta membuat laporan DITOLAK beserta daftar angkanya — perbaiki lalu panggil "
        "lagi. Bilangan kecil ≤ 31 (urutan, jumlah hari) dan tahun boleh. Tulis uang sebagai angka rupiah utuh atau "
        "'Rp1,2 jt'; persen dengan koma ('17,5%')."),
    input_schema=SKEMA,
    domain="laporan",
)
async def buat_laporan_marketing(ctx, args: dict) -> dict:
    db = getattr(ctx, "db", None)
    if db is None:
        from database import get_db
        db = get_db()
    args = dict(args or {})
    fid = args.pop("fakta_id", "")
    fakta = await lm.ambil_fakta(db, fid, ctx.user or {})
    if not fakta:
        raise AlatError(404, "Paket fakta tidak ditemukan — panggil paket_laporan_marketing dulu dan pakai fakta_id-nya.")
    asing = lm.periksa_angka(args, fakta)
    if asing:
        raise AlatError(400, "Laporan DITOLAK penjaga angka: angka berikut tidak ada di paket fakta: "
                             + ", ".join(asing) + ". Ganti dengan angka dari paket fakta (atau hapus), lalu panggil lagi.")
    try:
        doc = await la.buat_dan_simpan(db, args, user=ctx.user or {}, cv=getattr(ctx, "cv", "DA") or "DA",
                                       sesi_id=getattr(ctx, "sesi_id", None))
    except la.SpekLaporanError as e:
        raise AlatError(400, f"Isi laporan belum benar: {e.pesan}") from None
    berkas = [{"format": b["format"], "nama_berkas": b["nama_berkas"], "ukuran_kb": round(b["ukuran"] / 1024, 1)}
              for b in doc["berkas"]]
    return {"laporan_id": doc["id"], "judul": doc["judul"], "berkas": berkas, "cv": la.label_cv(doc["cv"]),
            "penjaga_angka": "lolos — semua angka ada di paket fakta",
            "_sumber": "Laporan Marketing (angka dari paket fakta)",
            "_ui_events": [{"event": "laporan", "data": d} for d in la.ringkas_untuk_ui(doc)]}
