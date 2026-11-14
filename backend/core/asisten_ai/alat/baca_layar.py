"""Bacaan layar Asisten ERP (12 Nov 2026, owner: "semuanya bisa dilakukan").

Supaya SEMUA aksi katalog bisa dipakai, Asisten harus bisa menemukan id/kode data yang dituju (PO, baris pekerjaan CMT,
faktur, akun bagan akun, retur, sesi opname, dst.). Dua alat BACA:
  * `cari_bacaan` — cari bacaan layar (GET yang dipanggil layar aktif) dengan kata biasa;
  * `baca_layar`  — baca satu alamat GET itu, persis seperti layar membukanya.

Pengaman:
  * hanya GET yang ada di katalog bacaan (dipakai layar aktif; tanpa rahasia/pengaturan sistem/Asisten, tanpa unduhan
    berkas — aturan.larangan_baca), dan selalu `ctx.api` GET dengan token pengguna sendiri (izin peran, cakupan toko,
    CV berlaku sama dengan layar);
  * hasil disamarkan `ctx.mask` (data pribadi pembeli/kontak; gaji per orang hanya untuk peran gaji);
  * daftar panjang dipangkas (paling banyak MAKS_BARIS baris per daftar) dengan catatan cara menyaring/halaman berikut;
  * mode atas nama vendor CMT (header `X-CMT-Override-Vendor`) hanya untuk bacaan yang memang mendukungnya dan peran
    yang dicentang modul Input atas nama Vendor CMT (`core.cmt_override.boleh_atas_nama`) — server tetap memeriksa ulang;
  * ruang AI SDM / Tanya Asisten hanya membaca bacaan portal ruangnya.
"""
from __future__ import annotations

from typing import Any

from core.asisten_ai import katalog_aksi as kat
from core.asisten_ai.alat_base import AlatError, alat
from core.asisten_ai.katalog_aksi import aturan

MAKS_BARIS = 300                  # baris per daftar untuk model (lalu dipangkas lagi menurut ukuran)
MAKS_BARIS_KODE = 3000            # dipanggil dari kode di ruang hitung (hasil tidak masuk konteks model)
BATAS_KARAKTER = 12_000           # target ukuran JSON hasil untuk model (inti memotong di 15.000)
HEADER_VENDOR = "X-CMT-Override-Vendor"
# kolom jejak sistem yang tidak membantu memilih data (dibuang supaya lebih banyak baris muat)
_KUNCI_BUANG = frozenset({"_id", "created_at", "updated_at", "created_by", "updated_by", "created_by_name",
                          "updated_by_name", "history", "audit_log", "logs", "riwayat_status", "kunci_proses",
                          "kunci_proses_at"})


def _bersihkan(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _bersihkan(x) for k, x in v.items() if k not in _KUNCI_BUANG}
    if isinstance(v, list):
        return [_bersihkan(x) for x in v]
    return v


def _ukuran(v: Any) -> int:
    import json
    return len(json.dumps(v, ensure_ascii=False, default=str))


def _pangkas(r: Any, catatan: list, maks: int = MAKS_BARIS, batas: int = BATAS_KARAKTER) -> Any:
    """Daftar terpanjang dipotong sampai muat `batas` karakter (paling banyak `maks` baris), dengan catatan."""
    r = _bersihkan(r)
    wadah = None
    if isinstance(r, list):
        daftar = r
    elif isinstance(r, dict):
        lists = [(k, v) for k, v in r.items() if isinstance(v, list)]
        if not lists:
            return r
        wadah, daftar = max(lists, key=lambda kv: len(kv[1]))
    else:
        return r
    total = len(daftar)
    n = min(total, maks)
    while n > 5 and _ukuran(daftar[:n]) > batas:
        n = int(n * 0.7)
    if n < total:
        catatan.append(f"Daftar berisi {total} baris; yang ditampilkan {n} pertama. Persempit dengan query "
                       "(cari/jenis/status/tanggal) atau halaman berikut.")
    if wadah is None:
        return daftar[:n]
    return {**r, wadah: daftar[:n]}


def periksa_vendor(ctx, vendor_id: str, method: str = "GET") -> None:
    """14 Nov 2026: aturan yang sama dengan header di server (centang Input atas nama Vendor CMT, bukan kode peran)."""
    from core.cmt_override import boleh_atas_nama, pesan_tolak
    if not boleh_atas_nama(ctx.user, method):
        raise AlatError(403, pesan_tolak(method))
    if not vendor_id or len(str(vendor_id)) > 80:
        raise AlatError(400, "Id vendor CMT tidak sah.")


@alat(name="cari_bacaan", kind="read", label="Mencari data di layar", domain="umum",
      description=("Cari alamat data (bacaan layar) dengan kata biasa, mis. 'baris pekerjaan CMT', 'bagan akun', "
                   "'daftar faktur hutang', 'sesi opname', 'retur gudang'. Hasil: alamat GET + parameter + query untuk "
                   "alat baca_layar. Pakai untuk menemukan id/kode data sebelum menyiapkan aksi dengan jalankan_aksi "
                   "(petunjuk `cari_id` dari cari_aksi biasanya sudah menyebut alamatnya)."),
      input_schema={"type": "object", "additionalProperties": False, "required": ["kata"], "properties": {
          "kata": {"type": "string", "minLength": 2, "maxLength": 200},
          "portal": {"type": "string", "maxLength": 40},
          "batas": {"type": "integer", "minimum": 1, "maximum": 15}}})
async def cari_bacaan(ctx, args: dict) -> dict:
    hasil = kat.cari_bacaan(args["kata"], portal=args.get("portal"), ruang=getattr(ctx, "ruang", "umum"),
                            batas=args.get("batas") or 8)
    return {"hasil": {"jumlah": len(hasil), "bacaan": [kat.ringkas_bacaan(b) for b in hasil],
                      "petunjuk": "Panggil baca_layar dengan `alamat` (parameter {…} diganti nilainya) dan `query`."}}


@alat(name="baca_layar", kind="read", label="Membaca data layar", domain="umum", kode=True,
      description=("Baca data persis seperti layar membukanya (GET alamat dari cari_bacaan / cari_id), dengan izin akun "
                   "pengguna sendiri; data pribadi disamarkan. Contoh: /api/production-job-items?job_id=… untuk baris "
                   "pekerjaan CMT, /api/rahaza/coa/accounts untuk bagan akun (rekomendasi akun jurnal), "
                   "/api/rahaza/journals/{je_id} untuk satu jurnal. Daftar panjang dipangkas 40 baris; persempit dengan "
                   "query. Isi `atas_nama_vendor` (id vendor) untuk melihat data seperti layar Input atas nama CMT."),
      input_schema={"type": "object", "additionalProperties": False, "required": ["alamat"], "properties": {
          "alamat": {"type": "string", "pattern": r"^/api/[^?#\s]{1,300}$",
                     "description": "Alamat GET konkret, parameter sudah diisi, tanpa query."},
          "query": {"type": "object", "additionalProperties": {"type": ["string", "integer", "number", "boolean"]}},
          "atas_nama_vendor": {"type": "string", "maxLength": 80}}})
async def baca_layar(ctx, args: dict) -> dict:
    alamat = str(args["alamat"]).rstrip("/")
    alasan = aturan.larangan_baca(alamat)          # diperiksa pada alamat KONKRET (mis. …/journals/export)
    if alasan:
        raise AlatError(403, alasan)
    ketemu = kat.bacaan_untuk(alamat)
    if ketemu is None:
        raise AlatError(404, "Alamat ini bukan bacaan layar yang dikenal. Cari dulu dengan cari_bacaan.")
    b, _param = ketemu
    if not aturan.di_ruang(b.get("portal") or [], getattr(ctx, "ruang", "umum")):
        raise AlatError(403, "Data ini bukan bagian dari ruang Asisten ini. Buka dari chat Asisten di Portal Manajemen.")
    # Query diteruskan apa adanya (banyak pintu membaca `request.query_params` sendiri, mis. ?job_id= di baris
    # pekerjaan CMT); pintu GET mengabaikan parameter yang tidak dikenalnya. Hanya nilai tunggal.
    query = {str(k): v for k, v in dict(args.get("query") or {}).items()}
    headers = None
    if args.get("atas_nama_vendor"):
        if not b.get("atas_nama_vendor"):
            raise AlatError(400, "Alamat ini tidak punya mode atas nama vendor CMT.")
        periksa_vendor(ctx, args["atas_nama_vendor"])
        headers = {HEADER_VENDOR: str(args["atas_nama_vendor"])}
    r = await ctx.api("GET", alamat, params=query or None, headers=headers)
    catatan: list = []
    if getattr(ctx, "pemanggil", "langsung") == "kode":
        out = _pangkas(r, catatan, maks=MAKS_BARIS_KODE, batas=1_500_000)
    else:
        out = _pangkas(r, catatan)
    hasil = {"data": ctx.mask(out)}
    if catatan:
        hasil["catatan"] = catatan[:3]
    sumber = f"Layar {b['layar']}" if b.get("layar") else "Data layar"
    return {"hasil": hasil, "_sumber": sumber}
