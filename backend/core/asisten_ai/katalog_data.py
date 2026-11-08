"""core.asisten_ai.katalog_data — data fleksibel BACA SAJA untuk Asisten AI (Tahap E, kontrak K1, 9 Nov 2026).

Owner ingin Asisten AI bisa menyusun pertanyaannya sendiri atas data sistem, bukan hanya 27 ringkasan tetap.
Berkas ini memberi itu tanpa membuka pintu tulis atau pintu kueri bebas. Tiga lapis yang sengaja dipisah:

1. **Definisi** — :class:`Kolom`, :class:`Gabung`, :class:`Akses`, :class:`Dataset`. Ditulis per domain di
   ``core/asisten_ai/katalog/`` (setiap modul mengekspor ``DATASET``). Nama koleksi & field diverifikasi dari
   kode penulisnya; angka bisnis mengikuti pembaca resmi (mis. omzet = ``core.ukuran_penjualan``).
2. **Pembangun pipeline** — :func:`bangun_rencana`, fungsi MURNI (tanpa DB): isian model → pipeline aggregation
   yang ketat. Hanya kolom katalog; operator & fungsi dari daftar tetap; nilai hanya skalar / daftar skalar
   (objek dan tanda ``$`` ditolak); ``berisi`` = regex yang di-escape; selalu ada ``$limit``. Ekspresi Mongo
   hanya berasal dari katalog (dipercaya), tidak pernah dari isian.
3. **Akses & eksekusi** — :func:`akses_pengguna` (portal/izin/peran efektif: ``routes.shared.resolve_role_access``
   + ``auth.compute_permissions``; superadmin/admin/owner = semua), gerbang modul granular
   (``data.module_catalog``), :func:`saringan_akses` (CV ``core.entities.entity_match`` + izin CV pengguna,
   lingkup toko marketing ``core.ukuran_penjualan.toko_terlihat``, baris gaji), :func:`cari` (eksekusi dengan
   ``maxTimeMS`` + olah hasil: kolom gaji hanya ``PERAN_GAJI``, nama orang/vendor/pelanggan disamarkan).

Data contoh (``_seed_origin``) selalu dibuang; dok terhapus/batal dibuang lewat ``saringan_dasar`` dataset.
"""
from __future__ import annotations

import importlib
import json
import logging
import math
import pkgutil
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

from core.asisten_ai.alat_base import _PII_KEY_RX, PERAN_GAJI, AlatError

log = logging.getLogger(__name__)

# ── Kosakata kontrak K1 ─────────────────────────────────────────────────────
TIPE = ("teks", "angka", "uang", "tanggal", "waktu", "ya_tidak", "daftar")
# Cara field tanggal disimpan:
#   teks         = string "YYYY-MM-DD" / ISO (bagian tanggal dipakai apa adanya)
#   datetime     = BSON date; bagian tanggal dipakai APA ADANYA (jam dinding WIB berlabel UTC, atau tanggal
#                  tanpa jam hasil `parse_date` = tengah malam UTC) — sama dengan pembaca resmi
#   datetime_utc = BSON date instan UTC sungguhan (created_at, …) → dikonversi ke tanggal WIB
#   campur       = sebagian string, sebagian datetime (apa adanya)
SIMPAN = ("teks", "datetime", "datetime_utc", "campur")
OPS = ("=", "!=", ">", ">=", "<", "<=", "in", "not_in", "berisi", "kosong", "tidak_kosong")
FUNGSI = ("jumlah", "rata", "min", "maks", "hitung", "hitung_unik")
ARAH = ("naik", "turun")
DOMAIN_DATA = ("penjualan", "iklan", "setoran", "produk", "stok", "produksi", "pengadaan", "keuangan", "sdm",
               "maklon")
LABEL_DOMAIN = {"penjualan": "Penjualan marketplace", "iklan": "Iklan", "setoran": "Setoran marketplace",
                "produk": "Produk", "stok": "Stok", "produksi": "Produksi & CMT", "pengadaan": "Pengadaan",
                "keuangan": "Keuangan", "sdm": "SDM", "maklon": "Maklon (CV Sukma)"}
MODE_CV = ("tidak", "field", "tetap", "saringan", "rekening", "toko")
SAMARAN = ("karyawan", "vendor", "pelanggan")
KUNCI_ISIAN = frozenset({"dataset", "kolom", "filter", "periode", "kelompok", "agregasi", "urut", "batas"})

BATAS_LANGSUNG = 200          # baris paling banyak bila model memanggil langsung
BATAS_KODE = 5000             # baris paling banyak bila dipanggil dari kode di ruang hitung
BAWAAN_LANGSUNG = 100
MAKS_HARI = 1100              # rentang periode paling panjang (± 3 tahun)
MAKS_MS = 15_000              # maxTimeMS satu pencarian
BATAS_KARAKTER_LANGSUNG = 13_500   # ruang di bawah potongan 15.000 karakter inti
MAKS_KOLOM = 40
MAKS_FILTER = 20
MAKS_KELOMPOK = 6
MAKS_AGREGASI = 12
MAKS_URUT = 4
MAKS_DAFTAR_NILAI = 200
MAKS_TEKS = 200
TZ_WIB = "Asia/Jakarta"
GESER_WIB = timedelta(hours=7)

# Peran yang melihat NAMA ASLI karyawan (sama dengan alat SDM: `_bantu_laporan.PERAN_SDM_PENUH`).
from core.asisten_ai.alat._bantu_laporan import (  # noqa: E402 — satu definisi, dipakai ulang
    _RX_AKUN_GAJI, CATATAN_GAJI_DISEMBUNYIKAN, PERAN_SDM_PENUH, label_cv,
)

POLA_GAJI = _RX_AKUN_GAJI.pattern
TANPA_CONTOH = {"_seed_origin": {"$in": [None, False]}}

_NAMA_RX = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_ID_RX = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_KOLEKSI_RX = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_PATH_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_TGL_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WAKTU_RX = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")
_GAJI_KUNCI_RX = re.compile(
    r"(salary|gaji|base_rate|basic_pay|wage|upah|net_pay|gross_pay|take_home|kasbon|payroll|tunjangan)")
# Operator ekspresi yang tidak boleh ada di katalog (menjalankan kode / menulis).
_OP_TERLARANG = frozenset({"$where", "$function", "$accumulator", "$out", "$merge", "$jsonSchema"})
_OP_BANDING = {">": "$gt", ">=": "$gte", "<": "$lt", "<=": "$lte"}
LABEL_FUNGSI = {"jumlah": "Jumlah", "rata": "Rata-rata", "min": "Terkecil", "maks": "Terbesar",
                "hitung": "Banyaknya", "hitung_unik": "Banyaknya (berbeda)"}
TURUNAN = (("bulan", "bulan (TTTT-BB)"), ("minggu", "minggu ISO Senin–Minggu (TTTT-Wmm)"), ("tahun", "tahun"))


class IsianSalah(ValueError):
    """Isian `cari_data` tidak sah — pesannya sudah berbahasa Indonesia untuk model."""


# ══════════════════════════════════════════════════════════════════════════════
# 1. DEFINISI
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, eq=False)
class Akses:
    """Aturan akses SALAH SATU (any-of): portal efektif, izin, atau peran. `modul` = gerbang modul granular
    (`mod.<modul>.view`) yang berlaku SETELAH any-of lolos — lolos bila salah satu modul lolos."""
    portal: tuple = ()
    izin: tuple = ()
    peran: tuple = ()
    modul: tuple = ()


@dataclass(frozen=True, eq=False)
class Kolom:
    nama: str
    label: str
    tipe: str
    path: Optional[str] = None       # path Mongo (boleh lewat hasil gabung "_x.f" atau unwind "items.f")
    cadangan: tuple = ()             # path pengganti bila kosong (angka: null; teks/tanggal: null atau "")
    ekspr: Any = None                # ekspresi agregasi TETAP dari katalog (nilai mentah sebelum normalisasi)
    simpan: Optional[str] = None     # cara simpan untuk tipe tanggal/waktu (lihat SIMPAN)
    keterangan: str = ""
    nilai: tuple = ()                # nilai yang mungkin (untuk filter persis)
    rahasia: Optional[str] = None    # "gaji" → hanya PERAN_GAJI
    akses: Optional[Akses] = None    # aturan akses kolom (opsional)
    samaran: Optional[str] = None    # "karyawan" | "vendor" | "pelanggan" → nama diganti kode
    teks_bebas: bool = False         # teks bebas: nama terdaftar & kontak disamarkan
    gabung: tuple = ()               # gabung yang dibutuhkan ekspr (path "_x.…" terdeteksi otomatis)
    bawaan: bool = True              # ikut ditampilkan bila `kolom` tidak diisi
    dasar: Optional[str] = None      # internal: kolom turunan (bulan/minggu/tahun) dari kolom tanggal ini
    turunan: Optional[str] = None


@dataclass(frozen=True, eq=False)
class Gabung:
    """`$lookup` tetap dari katalog: `nama` = field hasil (awalan `_`)."""
    nama: str
    dari: str
    lokal: str
    asing: str = "id"
    ambil: tuple = ()
    banyak: bool = False             # True = daftar (untuk unwind baris); False = satu dokumen
    saringan: Optional[dict] = None  # saringan tambahan di koleksi asing
    setelah_unwind: bool = False


@dataclass(frozen=True, eq=False)
class Dataset:
    id: str
    label: str
    keterangan: str
    koleksi: str
    domain: str
    kolom: tuple
    akses: Akses
    kolom_tanggal: Optional[str] = None
    saringan_dasar: dict = field(default_factory=dict)
    unwind: Optional[str] = None
    unwind_kosong: bool = False      # dok tanpa baris tetap muncul sekali (kolom baris kosong)
    gabung: tuple = ()
    cv: dict = field(default_factory=lambda: {"mode": "tidak"})
    toko_field: Optional[str] = None
    baris_gaji: tuple = ()           # path teks yang menandai baris gaji (disembunyikan untuk non-PERAN_GAJI)
    catatan: tuple = ()              # cara membaca (definisi angka bisnis) — dikirim ke model
    buang_contoh: bool = True
    urut_bawaan: tuple = ()          # ((kolom, "naik"|"turun"), …)


# ── Pembantu ekspresi (dipakai modul katalog) ───────────────────────────────
def jalur(p: str) -> str:
    return "$" + p


def e_atau(*paths: str) -> Any:
    """Nilai pertama yang tidak null/tidak ada (meniru `x if x is not None else …`)."""
    ex: Any = jalur(paths[-1])
    for p in reversed(paths[:-1]):
        ex = {"$ifNull": [jalur(p), ex]}
    return ex


def e_atau_teks(*paths: str) -> Any:
    """Nilai pertama yang tidak null dan bukan "" (meniru `a or b` pada teks)."""
    ex: Any = jalur(paths[-1])
    for p in reversed(paths[:-1]):
        ex = {"$cond": [{"$eq": [{"$ifNull": [jalur(p), ""]}, ""]}, ex, jalur(p)]}
    return ex


def e_angka(ex: Any) -> dict:
    return {"$convert": {"input": ex, "to": "double", "onError": None, "onNull": None}}


def e_angka_atau(*paths: str) -> Any:
    """Angka pertama yang terbaca (null, "" dan teks rusak dilewati)."""
    ex: Any = e_angka(jalur(paths[-1]))
    for p in reversed(paths[:-1]):
        ex = {"$ifNull": [e_angka(jalur(p)), ex]}
    return ex


def e_teks(ex: Any) -> dict:
    return {"$convert": {"input": ex, "to": "string", "onError": None, "onNull": None}}


def e_tanggal(ex: Any, simpan: str, *, jam: bool = False) -> dict:
    """Nilai tanggal tersimpan → "YYYY-MM-DD" (atau "YYYY-MM-DD HH:MM"), tahan dua bentuk simpanan."""
    fmt = "%Y-%m-%d %H:%M" if jam else "%Y-%m-%d"
    dts: dict = {"format": fmt, "date": ex}
    if simpan == "datetime_utc":
        dts["timezone"] = TZ_WIB
    teks: Any = {"$substrCP": [ex, 0, 16 if jam else 10]}
    if jam:
        teks = {"$replaceOne": {"input": teks, "find": "T", "replacement": " "}}
    return {"$switch": {"branches": [
        {"case": {"$eq": [{"$type": ex}, "date"]}, "then": {"$dateToString": dts}},
        {"case": {"$eq": [{"$type": ex}, "string"]}, "then": {"$cond": [{"$eq": [ex, ""]}, None, teks]}},
    ], "default": None}}


def e_ya_tidak(ex: Any) -> dict:
    return {"$cond": [{"$eq": [ex, True]}, True, {"$cond": [{"$eq": [ex, False]}, False, None]}]}


def e_peta(ex: Any, peta: dict, bawaan: Any = None, *, kecil: bool = True) -> dict:
    """Peta nilai teks (huruf kecil bila `kecil`) → nilai baku. `peta` = {nilai_baku: [nilai_mentah, …]}."""
    src = {"$toLower": {"$ifNull": [e_teks(ex), ""]}} if kecil else ex
    return {"$switch": {"branches": [{"case": {"$in": [src, list(v)]}, "then": k} for k, v in peta.items()],
                        "default": bawaan}}


def saringan_periode_mentah(path: str, simpan: str, dari: Optional[str], sampai: Optional[str]) -> dict:
    """Saringan rentang pada field MENTAH (sebelum normalisasi) — memakai indeks; tahan dua bentuk simpanan."""
    teks: dict = {}
    waktu: dict = {}
    if dari:
        t0 = datetime.fromisoformat(dari).replace(tzinfo=timezone.utc)
        if simpan == "datetime_utc":
            t0 -= GESER_WIB
        teks["$gte"], waktu["$gte"] = dari, t0
    if sampai:
        t1 = datetime.fromisoformat(sampai).replace(tzinfo=timezone.utc) + timedelta(days=1)
        if simpan == "datetime_utc":
            t1 -= GESER_WIB
        teks["$lte"], waktu["$lt"] = sampai + "￿", t1
    if simpan == "teks":
        return {path: teks}
    if simpan in ("datetime", "datetime_utc"):
        return {path: waktu}
    return {"$or": [{path: waktu}, {path: teks}]}


# ── Kolom turunan & ekspresi kolom ──────────────────────────────────────────
_CACHE_KOLOM: dict = {}


def kolom_lengkap(ds: Dataset) -> dict:
    """{nama: Kolom} termasuk kolom turunan kolom tanggal utama: `<t>_bulan`, `<t>_minggu`, `<t>_tahun`."""
    hit = _CACHE_KOLOM.get(id(ds))
    if hit is not None and hit[0] is ds:
        return hit[1]
    out = {k.nama: k for k in ds.kolom}
    kt = out.get(ds.kolom_tanggal) if ds.kolom_tanggal else None
    if kt is not None:
        for tur, lab in TURUNAN:
            nama = f"{kt.nama}_{tur}"
            if nama not in out:
                out[nama] = Kolom(nama=nama, label=f"{kt.label} — {lab}", tipe="teks", bawaan=False,
                                  dasar=kt.nama, turunan=tur, gabung=gabung_kolom(ds, kt))
    _CACHE_KOLOM[id(ds)] = (ds, out)
    return out


def gabung_kolom(ds: Dataset, k: Kolom) -> tuple:
    """Nama gabung yang dibutuhkan kolom ini (path `_x.…` + isian `gabung`)."""
    nama_g = {g.nama for g in ds.gabung}
    out = list(k.gabung)
    for p in ([k.path] if k.path else []) + list(k.cadangan):
        akar = p.split(".")[0]
        if akar in nama_g and akar not in out:
            out.append(akar)
    return tuple(out)


def ekspr_kolom(k: Kolom) -> Any:
    """Ekspresi $project kolom: nilai mentah → normalisasi menurut tipe."""
    if k.ekspr is not None:
        mentah = k.ekspr
    elif k.cadangan:
        if k.tipe in ("angka", "uang"):
            return e_angka_atau(k.path, *k.cadangan)
        mentah = (e_atau_teks if k.tipe in ("teks", "tanggal", "waktu") else e_atau)(k.path, *k.cadangan)
    else:
        mentah = jalur(k.path)
    if k.tipe == "teks":
        return e_teks(mentah)
    if k.tipe in ("angka", "uang"):
        return e_angka(mentah)
    if k.tipe == "tanggal":
        return e_tanggal(mentah, k.simpan or "campur")
    if k.tipe == "waktu":
        return e_tanggal(mentah, k.simpan or "campur", jam=True)
    if k.tipe == "ya_tidak":
        return e_ya_tidak(mentah)
    return mentah  # daftar


def ekspr_turunan(k: Kolom) -> dict:
    src = jalur(k.dasar)
    if k.turunan in ("bulan", "tahun"):
        n = 7 if k.turunan == "bulan" else 4
        return {"$cond": [{"$eq": [{"$ifNull": [src, None]}, None]}, None, {"$substrCP": [src, 0, n]}]}
    return {"$let": {
        "vars": {"d": {"$dateFromString": {"dateString": {"$substrCP": [{"$ifNull": [src, ""]}, 0, 10]},
                                           "format": "%Y-%m-%d", "onError": None, "onNull": None}}},
        "in": {"$cond": [{"$eq": ["$$d", None]}, None, {"$dateToString": {"format": "%G-W%V", "date": "$$d"}}]},
    }}


# ── Validasi definisi dataset ────────────────────────────────────────────────
def _kunci_ekspr(obj: Any, out: set) -> set:
    if isinstance(obj, dict):
        for kk, v in obj.items():
            out.add(str(kk))
            _kunci_ekspr(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _kunci_ekspr(v, out)
    return out


def _periksa_akses(a: Any, tempat: str, errs: list) -> None:
    from data.module_catalog import MODULE_BY_ID
    from routes.shared import PORTAL_ACCESS
    if not isinstance(a, Akses):
        errs.append(f"{tempat}: akses wajib objek Akses")
        return
    if not (a.portal or a.izin or a.peran):
        errs.append(f"{tempat}: akses wajib punya portal, izin, atau peran")
    for p in a.portal:
        if p not in PORTAL_ACCESS:
            errs.append(f"{tempat}: portal {p!r} tidak dikenal")
    for m in a.modul:
        if m not in MODULE_BY_ID:
            errs.append(f"{tempat}: modul {m!r} tidak ada di data/module_catalog.py")


def periksa_dataset(ds: Dataset) -> list:
    """Daftar galat definisi (kosong = sah). Dipakai saat memuat katalog dan di uji."""
    errs: list = []
    t = f"dataset {getattr(ds, 'id', '?')!r}"
    if not isinstance(ds.id, str) or not _ID_RX.match(ds.id):
        errs.append(f"{t}: id harus snake_case 3–40 huruf")
    if not str(ds.label or "").strip() or not str(ds.keterangan or "").strip():
        errs.append(f"{t}: label dan keterangan wajib diisi")
    from core.collection_registry import is_registered
    if not isinstance(ds.koleksi, str) or not _KOLEKSI_RX.match(ds.koleksi):
        errs.append(f"{t}: nama koleksi tidak sah")
    elif not is_registered(ds.koleksi):
        errs.append(f"{t}: koleksi {ds.koleksi} tidak terdaftar di core/collection_registry.py")
    if ds.domain not in DOMAIN_DATA:
        errs.append(f"{t}: domain {ds.domain!r} bukan salah satu dari {DOMAIN_DATA}")
    _periksa_akses(ds.akses, t, errs)
    if not ds.kolom or len(ds.kolom) > 60:
        errs.append(f"{t}: kolom wajib 1–60")
    nama_g = {}
    for g in ds.gabung:
        if not isinstance(g, Gabung) or not re.match(r"^_[a-z][a-z0-9_]{0,30}$", str(g.nama)):
            errs.append(f"{t}: gabung harus objek Gabung bernama '_…'")
            continue
        if g.nama in nama_g:
            errs.append(f"{t}: gabung {g.nama} ganda")
        nama_g[g.nama] = g
        if not _KOLEKSI_RX.match(g.dari) or not _PATH_RX.match(g.lokal) or not _PATH_RX.match(g.asing):
            errs.append(f"{t}: gabung {g.nama}: koleksi/path tidak sah")
        elif not is_registered(g.dari):
            errs.append(f"{t}: gabung {g.nama}: koleksi {g.dari} tidak terdaftar")
        for a in g.ambil:
            if not _PATH_RX.match(a):
                errs.append(f"{t}: gabung {g.nama}: field ambil {a!r} tidak sah")
        if g.saringan is not None and (not isinstance(g.saringan, dict) or _kunci_ekspr(g.saringan, set()) & _OP_TERLARANG):
            errs.append(f"{t}: gabung {g.nama}: saringan tidak sah")
    nama_kolom: set = set()
    for k in ds.kolom:
        tk = f"{t} kolom {getattr(k, 'nama', '?')!r}"
        if not isinstance(k, Kolom) or not isinstance(k.nama, str) or not _NAMA_RX.match(k.nama):
            errs.append(f"{tk}: nama harus snake_case 2–40 huruf")
            continue
        if k.nama in nama_kolom:
            errs.append(f"{tk}: nama ganda")
        nama_kolom.add(k.nama)
        if not str(k.label or "").strip():
            errs.append(f"{tk}: label wajib")
        if k.tipe not in TIPE:
            errs.append(f"{tk}: tipe {k.tipe!r} bukan salah satu dari {TIPE}")
        if (k.path is None) == (k.ekspr is None):
            errs.append(f"{tk}: isi tepat satu dari path atau ekspr")
        for p in ([k.path] if k.path else []) + list(k.cadangan):
            if not isinstance(p, str) or not _PATH_RX.match(p):
                errs.append(f"{tk}: path {p!r} tidak sah")
            elif p.startswith("_") and p.split(".")[0] not in nama_g and not p.startswith("_seed"):
                errs.append(f"{tk}: path {p!r} memakai gabung yang tidak ada")
        if k.cadangan and not k.path:
            errs.append(f"{tk}: cadangan hanya bersama path")
        if k.ekspr is not None:
            if not (isinstance(k.ekspr, dict) or (isinstance(k.ekspr, str) and k.ekspr.startswith("$"))):
                errs.append(f"{tk}: ekspr harus objek ekspresi atau '$path'")
            if _kunci_ekspr(k.ekspr, set()) & _OP_TERLARANG:
                errs.append(f"{tk}: ekspr memakai operator terlarang")
        for g in k.gabung:
            if g not in nama_g:
                errs.append(f"{tk}: gabung {g!r} tidak ada")
        if k.tipe in ("tanggal", "waktu") and k.simpan not in SIMPAN:
            errs.append(f"{tk}: kolom tanggal/waktu wajib `simpan` salah satu dari {SIMPAN}")
        if k.samaran is not None and (k.samaran not in SAMARAN or k.tipe != "teks"):
            errs.append(f"{tk}: samaran harus {SAMARAN} pada kolom teks")
        if k.rahasia not in (None, "gaji"):
            errs.append(f"{tk}: rahasia hanya 'gaji'")
        if k.akses is not None:
            _periksa_akses(k.akses, tk, errs)
        if _PII_KEY_RX.search(k.nama):
            errs.append(f"{tk}: nama kolom tampak data pribadi (pembeli/alamat/kontak) — tidak boleh di katalog")
        if _GAJI_KUNCI_RX.search(k.nama) and k.rahasia != "gaji":
            errs.append(f"{tk}: kolom gaji wajib rahasia='gaji'")
        if not isinstance(k.nilai, tuple):
            errs.append(f"{tk}: nilai harus tuple")
    if ds.kolom_tanggal is not None:
        kt = next((k for k in ds.kolom if isinstance(k, Kolom) and k.nama == ds.kolom_tanggal), None)
        if kt is None or kt.tipe not in ("tanggal", "waktu"):
            errs.append(f"{t}: kolom_tanggal harus kolom bertipe tanggal/waktu")
        else:
            for tur, _ in TURUNAN:
                if f"{kt.nama}_{tur}" in nama_kolom:
                    errs.append(f"{t}: kolom {kt.nama}_{tur} bentrok dengan kolom turunan")
    if ds.unwind is not None:
        if not _PATH_RX.match(ds.unwind):
            errs.append(f"{t}: unwind tidak sah")
        elif ds.unwind.startswith("_") and not (ds.unwind in nama_g and nama_g[ds.unwind].banyak):
            errs.append(f"{t}: unwind lewat gabung wajib gabung banyak=True")
    if not isinstance(ds.saringan_dasar, dict) or _kunci_ekspr(ds.saringan_dasar, set()) & _OP_TERLARANG:
        errs.append(f"{t}: saringan_dasar tidak sah")
    cv = ds.cv if isinstance(ds.cv, dict) else {}
    mode = cv.get("mode")
    if mode not in MODE_CV:
        errs.append(f"{t}: mode CV {mode!r} bukan salah satu dari {MODE_CV}")
    if mode in ("field", "rekening") and not _PATH_RX.match(str(cv.get("field") or "")):
        errs.append(f"{t}: mode CV {mode} wajib `field`")
    if mode == "tetap" and cv.get("milik") not in ("DA", "SMU"):
        errs.append(f"{t}: mode CV tetap wajib `milik` DA/SMU")
    if mode == "saringan":
        if not isinstance(cv.get("DA"), dict) or not isinstance(cv.get("SMU"), dict):
            errs.append(f"{t}: mode CV saringan wajib saringan DA dan SMU")
        if cv.get("gabung") is not None and cv["gabung"] not in nama_g:
            errs.append(f"{t}: mode CV saringan memakai gabung yang tidak ada")
    if (mode == "toko") != bool(ds.toko_field):
        errs.append(f"{t}: mode CV toko wajib bersama toko_field (dan sebaliknya)")
    for p in ds.baris_gaji:
        if not _PATH_RX.match(p):
            errs.append(f"{t}: baris_gaji path {p!r} tidak sah")
    for u in ds.urut_bawaan:
        if not (isinstance(u, tuple) and len(u) == 2 and u[0] in nama_kolom and u[1] in ARAH):
            errs.append(f"{t}: urut_bawaan {u!r} tidak sah")
    if not all(isinstance(c, str) and c.strip() for c in ds.catatan):
        errs.append(f"{t}: catatan harus teks")
    return errs


# ── Daftar katalog ───────────────────────────────────────────────────────────
_DAFTAR: dict = {}
_GALAT: dict = {}
_SUDAH_MUAT = False


def muat_katalog(paksa: bool = False) -> dict:
    """Impor setiap modul di `core/asisten_ai/katalog/` (urut nama) dan daftarkan `DATASET`-nya.
    Dataset yang tidak sah dicatat dan dilewati (satu definisi rusak tidak mematikan alat). Return {sumber: galat}."""
    global _SUDAH_MUAT
    if _SUDAH_MUAT and not paksa:
        return dict(_GALAT)
    pkg = importlib.import_module("core.asisten_ai.katalog")
    baru: dict = {}
    galat: dict = {}
    for m in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if m.name.startswith("_"):
            continue
        nama = f"{pkg.__name__}.{m.name}"
        try:
            mod = importlib.import_module(nama)
        except Exception as e:  # noqa: BLE001
            log.exception("Modul katalog data gagal dimuat: %s", nama)
            galat[m.name] = f"{type(e).__name__}: {str(e)[:200]}"
            continue
        for ds in getattr(mod, "DATASET", ()) or ():
            errs = periksa_dataset(ds) if isinstance(ds, Dataset) else ["bukan Dataset"]
            if not errs and ds.id in baru:
                errs = [f"id {ds.id} sudah dipakai"]
            if errs:
                log.error("Dataset katalog %s.%s tidak sah: %s", m.name, getattr(ds, "id", "?"), "; ".join(errs))
                galat[f"{m.name}.{getattr(ds, 'id', '?')}"] = "; ".join(errs)[:500]
                continue
            baru[ds.id] = ds
    _DAFTAR.clear()
    _DAFTAR.update(baru)
    _GALAT.clear()
    _GALAT.update(galat)
    _SUDAH_MUAT = True
    return dict(galat)


def semua_dataset() -> list:
    muat_katalog()
    urutan = {d: i for i, d in enumerate(DOMAIN_DATA)}
    return sorted(_DAFTAR.values(), key=lambda d: (urutan.get(d.domain, 99), d.id))


def cari_dataset(ds_id: Any) -> Optional[Dataset]:
    muat_katalog()
    return _DAFTAR.get(ds_id) if isinstance(ds_id, str) else None


# ══════════════════════════════════════════════════════════════════════════════
# 2. PEMBANGUN PIPELINE (MURNI)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Rencana:
    dataset: Dataset
    pipeline: list
    kolom: list                  # [{nama, label, tipe}] kolom keluaran
    mode: str                    # "baris" | "kelompok"
    batas: int
    samaran: dict                # nama kolom keluaran → jenis samaran
    bebas: tuple                 # kolom keluaran teks bebas
    tipe: dict                   # nama kolom keluaran → tipe
    catatan: list


def _dan(daftar: list) -> dict:
    daftar = [d for d in daftar if d]
    if not daftar:
        return {}
    return daftar[0] if len(daftar) == 1 else {"$and": daftar}


def _ringkas(v: Any, n: int = 40) -> str:
    s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def _daftar_isian(v: Any, nama: str, maks: int) -> list:
    if v is None:
        return []
    if not isinstance(v, list):
        raise IsianSalah(f"Isian {nama} harus berupa daftar.")
    if len(v) > maks:
        raise IsianSalah(f"Isian {nama} paling banyak {maks} butir.")
    return v


def _tanggal_isian(v: Any, nama: str) -> Optional[str]:
    if v in (None, ""):
        return None
    s = str(v).strip()
    try:
        if not _TGL_RX.match(s):
            raise ValueError
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise IsianSalah(f"Periode {nama} '{_ringkas(v)}' bukan tanggal yang sah (format TTTT-BB-HH).") from None


def _nilai_skalar(k: Kolom, v: Any, pulihkan: Optional[Callable]) -> Any:
    """Satu nilai filter → nilai bertipe kolom. Objek, daftar bersarang, dan tanda `$` ditolak."""
    if isinstance(v, (dict, list, tuple, set)):
        raise IsianSalah(f"Nilai filter kolom {k.nama} harus teks, angka, atau ya/tidak — bukan objek/daftar.")
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if "$" in v:
            raise IsianSalah("Nilai filter tidak boleh memuat tanda $.")
        if len(v) > MAKS_TEKS:
            raise IsianSalah(f"Nilai filter paling panjang {MAKS_TEKS} karakter.")
    if k.tipe in ("angka", "uang"):
        if isinstance(v, bool):
            raise IsianSalah(f"Kolom {k.nama} berisi angka; nilai ya/tidak tidak bisa dibandingkan.")
        if isinstance(v, (int, float)):
            if not math.isfinite(v):
                raise IsianSalah(f"Nilai kolom {k.nama} bukan angka yang sah.")
            return float(v)
        try:
            f = float(str(v))
        except ValueError:
            raise IsianSalah(f"Kolom {k.nama} berisi angka; '{_ringkas(v)}' bukan angka (pakai titik desimal, "
                             "tanpa pemisah ribuan).") from None
        if not math.isfinite(f):
            raise IsianSalah(f"Nilai kolom {k.nama} bukan angka yang sah.")
        return f
    if k.tipe == "ya_tidak":
        if isinstance(v, bool):
            return v
        s = str(v).lower()
        if s in ("ya", "true", "1", "benar"):
            return True
        if s in ("tidak", "false", "0", "salah"):
            return False
        raise IsianSalah(f"Kolom {k.nama} berisi ya/tidak; pakai true atau false.")
    if k.tipe == "tanggal":
        return _tanggal_isian(v, f"filter {k.nama}")
    if k.tipe == "waktu":
        s = str(v).strip().replace("T", " ")[:16]
        if not _WAKTU_RX.match(s):
            raise IsianSalah(f"Kolom {k.nama} berisi waktu; pakai 'TTTT-BB-HH' atau 'TTTT-BB-HH JJ:MM' (WIB).")
        return s
    if isinstance(v, bool):
        raise IsianSalah(f"Kolom {k.nama} berisi teks; nilai ya/tidak tidak bisa dibandingkan.")
    s = str(v) if isinstance(v, (int, float)) else v
    if k.samaran and pulihkan is not None:
        asli = pulihkan(s)
        if asli:
            s = asli
    return s


def _saringan_kolom(k: Kolom, op: str, nilai: Any, pulihkan: Optional[Callable]) -> dict:
    n = k.nama
    if op in ("kosong", "tidak_kosong"):
        if nilai not in (None, "", True):
            raise IsianSalah(f"Operator {op} tidak memakai nilai.")
        kosong = [None, ""] + ([[]] if k.tipe == "daftar" else [])
        if op == "kosong":
            return {"$or": [{n: x} for x in kosong]}
        return {"$and": [{n: {"$ne": x}} for x in kosong]}
    if op in ("in", "not_in"):
        if not isinstance(nilai, list) or not nilai:
            raise IsianSalah(f"Operator {op} butuh daftar nilai, mis. [\"a\", \"b\"].")
        if len(nilai) > MAKS_DAFTAR_NILAI:
            raise IsianSalah(f"Daftar nilai paling banyak {MAKS_DAFTAR_NILAI} butir.")
        return {n: {"$in" if op == "in" else "$nin": [_nilai_skalar(k, v, pulihkan) for v in nilai]}}
    if op == "berisi":
        if k.tipe not in ("teks", "daftar"):
            raise IsianSalah(f"Operator berisi hanya untuk kolom teks; kolom {n} bertipe {k.tipe}.")
        if not isinstance(nilai, (str, int, float)) or isinstance(nilai, bool) or str(nilai).strip() == "":
            raise IsianSalah("Operator berisi butuh potongan teks.")
        s = _nilai_skalar(Kolom(nama=n, label=k.label, tipe="teks", path="x", samaran=k.samaran), nilai, pulihkan)
        return {n: {"$regex": re.escape(s), "$options": "i"}}
    if op in _OP_BANDING:
        if k.tipe in ("ya_tidak", "daftar"):
            raise IsianSalah(f"Operator {op} tidak bisa dipakai pada kolom {n} ({k.tipe}).")
        v = _nilai_skalar(k, nilai, pulihkan)
        if v is None:
            raise IsianSalah(f"Operator {op} butuh nilai.")
        return {n: {_OP_BANDING[op]: v}}
    v = _nilai_skalar(k, nilai, pulihkan)
    return {n: v} if op == "=" else {n: {"$ne": v}}


def _akumulator(fungsi: str, kol: Optional[str]) -> dict:
    if fungsi == "hitung":
        return {"$sum": 1} if kol is None else {
            "$sum": {"$cond": [{"$in": [{"$ifNull": [jalur(kol), None]}, [None, ""]]}, 0, 1]}}
    if fungsi == "hitung_unik":
        return {"$addToSet": jalur(kol)}
    return {{"jumlah": "$sum", "rata": "$avg", "min": "$min", "maks": "$max"}[fungsi]: jalur(kol)}


def bangun_rencana(ds: Dataset, isian: dict, *, kolom_boleh: Optional[Iterable[str]] = None,
                   batas_maks: int = BATAS_LANGSUNG, batas_bawaan: Optional[int] = None,
                   saringan_awal: Iterable[dict] = (), saringan_gabung: Iterable[dict] = (),
                   pulihkan: Optional[Callable[[str], Optional[str]]] = None) -> Rencana:
    """Isian `cari_data` → :class:`Rencana` (pipeline aggregation). FUNGSI MURNI — tidak menyentuh DB.

    `kolom_boleh` = kolom yang boleh dibaca pengguna (None = semua); `saringan_awal` = saringan akses pada field
    mentah (CV, toko, baris gaji); `saringan_gabung` = saringan akses yang memakai hasil gabung (CV lewat PO);
    `pulihkan(kode)` = kode samaran → nama asli untuk nilai filter kolom bersamaran. Galat → :class:`IsianSalah`.
    """
    if not isinstance(isian, dict):
        raise IsianSalah("Isian harus objek JSON.")
    asing = sorted(set(isian) - KUNCI_ISIAN)
    if asing:
        raise IsianSalah(f"Isian tidak dikenal: {', '.join(_ringkas(a) for a in asing)}. "
                         f"Yang boleh: {', '.join(sorted(KUNCI_ISIAN))}.")
    semua = kolom_lengkap(ds)
    boleh = set(semua) if kolom_boleh is None else set(kolom_boleh)
    catatan: list = []

    def _kol(nama: Any) -> Kolom:
        if not isinstance(nama, str) or nama not in semua:
            ada = ", ".join(n for n in semua if n in boleh)
            raise IsianSalah(f"Kolom '{_ringkas(nama)}' tidak ada di data '{ds.label}'. Kolom yang ada: {ada}.")
        if nama not in boleh:
            raise IsianSalah(f"Kolom '{nama}' tidak boleh dibaca dengan akun ini.")
        return semua[nama]

    pra: list = [dict(ds.saringan_dasar)] if ds.saringan_dasar else []
    if ds.buang_contoh:
        pra.append(dict(TANPA_CONTOH))
    pra += [dict(s) for s in saringan_awal if s]
    pasca: list = []
    butuh: list = []

    def _butuh(k: Kolom) -> None:
        if k.nama not in butuh:
            butuh.append(k.nama)

    # — periode —
    periode = isian.get("periode")
    if periode not in (None, {}):
        if not ds.kolom_tanggal:
            raise IsianSalah(f"Data '{ds.label}' tidak punya kolom tanggal; saring dengan filter.")
        if not isinstance(periode, dict) or set(periode) - {"dari", "sampai"}:
            raise IsianSalah("Periode harus {dari, sampai} berformat TTTT-BB-HH.")
        dari = _tanggal_isian(periode.get("dari"), "dari")
        sampai = _tanggal_isian(periode.get("sampai"), "sampai")
        if dari and sampai:
            if sampai < dari:
                raise IsianSalah("Tanggal 'sampai' lebih awal daripada 'dari'.")
            if (date.fromisoformat(sampai) - date.fromisoformat(dari)).days + 1 > MAKS_HARI:
                raise IsianSalah(f"Rentang periode paling panjang {MAKS_HARI} hari. Persempit periodenya.")
        if dari or sampai:
            kt = semua[ds.kolom_tanggal]
            if kt.nama not in boleh:
                raise IsianSalah(f"Kolom tanggal '{kt.nama}' tidak boleh dibaca dengan akun ini.")
            _butuh(kt)
            if kt.path and not kt.cadangan and kt.ekspr is None and not gabung_kolom(ds, kt):
                pra.append(saringan_periode_mentah(kt.path, kt.simpan or "campur", dari, sampai))
            rng: dict = {}
            if dari:
                rng["$gte"] = dari
            if sampai:
                rng["$lte"] = sampai + ("￿" if kt.tipe == "waktu" else "")
            pasca.append({kt.nama: rng})

    # — filter —
    for f in _daftar_isian(isian.get("filter"), "filter", MAKS_FILTER):
        if not isinstance(f, dict) or "kolom" not in f or "op" not in f or set(f) - {"kolom", "op", "nilai"}:
            raise IsianSalah("Setiap filter harus {kolom, op, nilai}.")
        k = _kol(f["kolom"])
        op = f["op"]
        if op not in OPS:
            raise IsianSalah(f"Operator '{_ringkas(op)}' tidak dikenal. Pilihan: {', '.join(OPS)}.")
        pasca.append(_saringan_kolom(k, op, f.get("nilai"), pulihkan))
        _butuh(k)

    # — kelompok & agregasi —
    kelompok: list = []
    for x in _daftar_isian(isian.get("kelompok"), "kelompok", MAKS_KELOMPOK):
        k = _kol(x)
        if k.tipe == "daftar":
            raise IsianSalah(f"Kolom {k.nama} berisi daftar; tidak bisa dipakai sebagai kelompok.")
        if k.nama in [g.nama for g in kelompok]:
            raise IsianSalah(f"Kolom {k.nama} disebut dua kali di kelompok.")
        kelompok.append(k)
        _butuh(k)
    agregasi: list = []   # (nama, fungsi, Kolom|None, label, tipe)
    for a in _daftar_isian(isian.get("agregasi"), "agregasi", MAKS_AGREGASI):
        if not isinstance(a, dict) or "fungsi" not in a or set(a) - {"fungsi", "kolom", "nama"}:
            raise IsianSalah("Setiap agregasi harus {fungsi, kolom?, nama?}.")
        fn = a["fungsi"]
        if fn not in FUNGSI:
            raise IsianSalah(f"Fungsi agregasi '{_ringkas(fn)}' tidak dikenal. Pilihan: {', '.join(FUNGSI)}.")
        k = _kol(a["kolom"]) if a.get("kolom") is not None else None
        if k is None and fn != "hitung":
            raise IsianSalah(f"Fungsi {fn} butuh kolom.")
        if k is not None:
            if fn in ("jumlah", "rata") and k.tipe not in ("angka", "uang"):
                raise IsianSalah(f"Fungsi {fn} hanya untuk kolom angka/uang; kolom {k.nama} bertipe {k.tipe}.")
            if fn in ("min", "maks") and k.tipe in ("ya_tidak", "daftar"):
                raise IsianSalah(f"Fungsi {fn} tidak bisa dipakai pada kolom {k.nama} ({k.tipe}).")
            if fn == "hitung_unik" and k.tipe == "daftar":
                raise IsianSalah(f"Fungsi hitung_unik tidak bisa dipakai pada kolom daftar {k.nama}.")
            _butuh(k)
        nama = a.get("nama") or ("jumlah_baris" if k is None else f"{fn}_{k.nama}")[:40]
        if not isinstance(nama, str) or not _NAMA_RX.match(nama):
            raise IsianSalah(f"Nama agregasi '{_ringkas(nama)}' harus snake_case huruf kecil (2–40).")
        if nama in [x[0] for x in agregasi] or nama in [g.nama for g in kelompok]:
            raise IsianSalah(f"Nama agregasi '{nama}' bentrok; beri nama lain.")
        label = (f"{LABEL_FUNGSI[fn]} baris" if k is None
                 else f"{LABEL_FUNGSI[fn]} {k.label[:1].lower() + k.label[1:]}")
        tipe = "angka" if fn in ("hitung", "hitung_unik") else k.tipe
        agregasi.append((nama, fn, k, label, tipe))
    mode = "kelompok" if (kelompok or agregasi) else "baris"
    if mode == "kelompok" and not agregasi:
        agregasi.append(("jumlah_baris", "hitung", None, "Banyaknya baris", "angka"))

    # — kolom keluaran (mode baris) —
    pilih: list = []
    if mode == "baris":
        for x in _daftar_isian(isian.get("kolom"), "kolom", MAKS_KOLOM):
            k = _kol(x)
            if k not in pilih:
                pilih.append(k)
        if not pilih:
            pilih = [k for k in semua.values() if k.bawaan and k.nama in boleh]
        for k in pilih:
            _butuh(k)
    elif isian.get("kolom"):
        catatan.append("Isian kolom diabaikan karena memakai kelompok/agregasi.")

    # — urut —
    keluar_nama = ([k.nama for k in pilih] if mode == "baris"
                   else [k.nama for k in kelompok] + [a[0] for a in agregasi])
    urut: dict = {}
    for u in _daftar_isian(isian.get("urut"), "urut", MAKS_URUT):
        if not isinstance(u, dict) or "kolom" not in u or set(u) - {"kolom", "arah"}:
            raise IsianSalah("Setiap urut harus {kolom, arah}.")
        arah = {"asc": "naik", "desc": "turun"}.get(u.get("arah"), u.get("arah") or "naik")
        if arah not in ARAH:
            raise IsianSalah("Arah urut harus 'naik' atau 'turun'.")
        if mode == "kelompok":
            if u["kolom"] not in keluar_nama:
                raise IsianSalah(f"Urut '{_ringkas(u['kolom'])}' harus salah satu kolom kelompok atau nama agregasi: "
                                 f"{', '.join(keluar_nama)}.")
            nm = u["kolom"]
        else:
            k = _kol(u["kolom"])
            _butuh(k)
            nm = k.nama
        urut[nm] = 1 if arah == "naik" else -1
    if not urut:
        if mode == "baris":
            for nm, arah in ds.urut_bawaan:
                if nm in boleh:
                    _butuh(semua[nm])
                    urut[nm] = 1 if arah == "naik" else -1
            if not urut and ds.kolom_tanggal and ds.kolom_tanggal in boleh:
                _butuh(semua[ds.kolom_tanggal])
                urut[ds.kolom_tanggal] = -1
        elif kelompok and (kelompok[0].tipe in ("tanggal", "waktu") or kelompok[0].turunan):
            urut = {k.nama: 1 for k in kelompok}
        else:
            urut = {agregasi[0][0]: -1}

    # — batas —
    b = isian.get("batas")
    if b is None:
        b = batas_bawaan or batas_maks
    if not isinstance(b, int) or isinstance(b, bool) or b < 1:
        raise IsianSalah("Batas harus bilangan bulat ≥ 1.")
    if b > batas_maks:
        catatan.append(f"Batas baris diturunkan ke {batas_maks} (paling banyak untuk panggilan ini).")
        b = batas_maks

    # — susun pipeline —
    pipe: list = []
    m0 = _dan(pra)
    if m0:
        pipe.append({"$match": m0})
    sg = [dict(s) for s in saringan_gabung if s]
    perlu: set = set()
    for nm in butuh:
        perlu.update(semua[nm].gabung if semua[nm].dasar else gabung_kolom(ds, semua[nm]))
    if ds.unwind and ds.unwind.split(".")[0] in {g.nama for g in ds.gabung}:
        perlu.add(ds.unwind.split(".")[0])
    if sg and ds.cv.get("gabung"):
        perlu.add(ds.cv["gabung"])

    def _lookup(g: Gabung) -> list:
        sub: list = []
        if g.saringan:
            sub.append({"$match": dict(g.saringan)})
        sub.append({"$project": {"_id": 0, **{a: 1 for a in (g.ambil or (g.asing,))}}})
        st = [{"$lookup": {"from": g.dari, "localField": g.lokal, "foreignField": g.asing, "pipeline": sub,
                           "as": g.nama}}]
        if not g.banyak:
            st.append({"$set": {g.nama: {"$arrayElemAt": [jalur(g.nama), 0]}}})
        return st

    for g in ds.gabung:
        if g.nama in perlu and not g.setelah_unwind:
            pipe += _lookup(g)
    if ds.unwind:
        pipe.append({"$unwind": {"path": jalur(ds.unwind), "preserveNullAndEmptyArrays": bool(ds.unwind_kosong)}})
    for g in ds.gabung:
        if g.nama in perlu and g.setelah_unwind:
            pipe += _lookup(g)
    if sg:
        pipe.append({"$match": _dan(sg)})
    dasar_perlu = [nm for nm in butuh if not semua[nm].dasar]
    for nm in butuh:
        if semua[nm].dasar and semua[nm].dasar not in dasar_perlu:
            dasar_perlu.append(semua[nm].dasar)
    proyeksi: dict = {"_id": 0}
    for k in ds.kolom:
        if k.nama in dasar_perlu:
            proyeksi[k.nama] = ekspr_kolom(k)
    pipe.append({"$project": proyeksi})
    tur = {nm: ekspr_turunan(semua[nm]) for nm in butuh if semua[nm].dasar}
    if tur:
        pipe.append({"$set": tur})
    if pasca:
        pipe.append({"$match": _dan(pasca)})
    if mode == "kelompok":
        grp: dict = {"_id": {k.nama: jalur(k.nama) for k in kelompok} if kelompok else None}
        proj2: dict = {"_id": 0, **{k.nama: jalur("_id." + k.nama) for k in kelompok}}
        for nama, fn, k, _, _ in agregasi:
            grp[nama] = _akumulator(fn, k.nama if k is not None else None)
            proj2[nama] = ({"$size": {"$setDifference": [jalur(nama), [None, ""]]}} if fn == "hitung_unik"
                           else jalur(nama))
        pipe += [{"$group": grp}, {"$project": proj2}]
    baris_st: list = []
    if urut:
        baris_st.append({"$sort": dict(urut)})
    baris_st.append({"$limit": b})
    if mode == "baris":
        baris_st.append({"$project": {"_id": 0, **{k.nama: 1 for k in pilih}}})
    pipe.append({"$facet": {"baris": baris_st, "total": [{"$count": "n"}]}})

    # — metadata keluaran —
    if mode == "baris":
        kolom_out = [{"nama": k.nama, "label": k.label, "tipe": k.tipe} for k in pilih]
        sam = {k.nama: k.samaran for k in pilih if k.samaran}
        bebas = tuple(k.nama for k in pilih if k.teks_bebas)
    else:
        kolom_out = [{"nama": k.nama, "label": k.label, "tipe": k.tipe} for k in kelompok]
        kolom_out += [{"nama": nama, "label": label, "tipe": tipe} for nama, _, _, label, tipe in agregasi]
        sam = {k.nama: k.samaran for k in kelompok if k.samaran}
        sam.update({nama: k.samaran for nama, fn, k, _, _ in agregasi
                    if k is not None and k.samaran and fn in ("min", "maks")})
        bebas = tuple(k.nama for k in kelompok if k.teks_bebas)
    return Rencana(dataset=ds, pipeline=pipe, kolom=kolom_out, mode=mode, batas=b, samaran=sam, bebas=bebas,
                   tipe={c["nama"]: c["tipe"] for c in kolom_out}, catatan=catatan)


# ══════════════════════════════════════════════════════════════════════════════
# 3. AKSES
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class AksesPengguna:
    user_id: str
    peran: str
    super_: bool
    portal: frozenset
    izin: frozenset
    cv_boleh: tuple
    boleh_gaji: bool
    sdm_penuh: bool


def akses_dari(*, peran: str, portal: Iterable[str] = (), izin: Iterable[str] = (), user_id: str = "",
               cv_boleh: Optional[Iterable[str]] = None) -> AksesPengguna:
    """Bangun :class:`AksesPengguna` dari nilai jadi (dipakai :func:`akses_pengguna` dan uji)."""
    from routes.shared import SUPER_ROLES
    p = str(peran or "").lower()
    iz = frozenset(x for x in (izin or ()) if x)
    return AksesPengguna(user_id=str(user_id or ""), peran=p, super_=(p in SUPER_ROLES or "*" in iz),
                         portal=frozenset(portal or ()), izin=iz,
                         cv_boleh=tuple(cv_boleh) if cv_boleh else ("DA", "SMU"),
                         boleh_gaji=p in PERAN_GAJI, sdm_penuh=p in PERAN_SDM_PENUH)


async def akses_pengguna(ctx, *, izin_fn: Optional[Callable] = None) -> AksesPengguna:
    """Akses efektif pengguna `ctx.user` (disimpan sekali per giliran di `ctx._bersama`).

    Portal = `routes.shared.resolve_role_access` (peran LIVE, roles.portals, extra_portals, izin Lihat per modul,
    bawaan PORTAL_ACCESS). Izin = `_permissions` dari `require_auth` bila ada, kalau tidak `auth.compute_permissions`.
    CV yang boleh = `users.allowed_entities` (`core.entities.allowed_of_user`)."""
    bersama = getattr(ctx, "_bersama", None)
    if isinstance(bersama, dict) and isinstance(bersama.get("akses_data"), AksesPengguna):
        return bersama["akses_data"]
    db = getattr(ctx, "db", None)
    if db is None:
        raise AlatError(500, "Alat data tidak bisa membaca basis data saat ini.")
    user = dict(getattr(ctx, "user", None) or {})
    uid = user.get("id")
    from core.entities import allowed_of_user
    from routes.shared import resolve_role_access
    acc = await resolve_role_access(db, dict(user))
    peran = acc.get("role") or str(user.get("role") or "").lower()
    izin = user.get("_permissions")
    if izin is None:
        try:
            if izin_fn is None:
                from auth import compute_permissions as izin_fn
            izin = await izin_fn(peran, uid)
        except Exception:  # noqa: BLE001 — izin gagal dibaca = tanpa izin tambahan (lebih sempit, aman)
            log.exception("Izin pengguna %s gagal dibaca untuk alat data", uid)
            izin = []
    udoc = await db.users.find_one({"id": uid}, {"_id": 0, "allowed_entities": 1}) if uid else None
    ak = akses_dari(peran=peran, portal=acc.get("portals") or (), izin=izin or (), user_id=uid or "",
                    cv_boleh=allowed_of_user(udoc))
    if acc.get("is_super") and not ak.super_:
        ak = replace(ak, super_=True)
    if isinstance(bersama, dict):
        bersama["akses_data"] = ak
    return ak


def _lolos_modul(modul: str, ak: AksesPengguna) -> bool:
    from data.module_catalog import MODULE_BY_ID, granular_portals, perm_key
    mod = MODULE_BY_ID.get(modul)
    if mod is None or mod.get("lookup"):
        return True
    if mod["portal"] not in granular_portals(ak.izin):
        return True   # portal belum diatur granular → penjaga peran/portal yang berlaku (fallback aman)
    return perm_key(modul, "view") in ak.izin


def boleh(aturan: Optional[Akses], ak: AksesPengguna, *, dengan_modul: bool = True) -> bool:
    """Apakah pengguna lolos aturan akses (super = selalu; any-of portal/izin/peran; lalu gerbang modul)."""
    if aturan is None or ak.super_:
        return True
    ok = (ak.peran in aturan.peran or bool(ak.izin & set(aturan.izin)) or bool(ak.portal & set(aturan.portal)))
    if not ok:
        return False
    if dengan_modul and aturan.modul:
        return any(_lolos_modul(m, ak) for m in aturan.modul)
    return True


def dataset_boleh(ds: Dataset, ak: AksesPengguna) -> bool:
    return boleh(ds.akses, ak)


def kolom_boleh(ds: Dataset, ak: AksesPengguna) -> set:
    out = set()
    for nm, k in kolom_lengkap(ds).items():
        asal = kolom_lengkap(ds).get(k.dasar) if k.dasar else k
        if asal.rahasia == "gaji" and not ak.boleh_gaji:
            continue
        if asal.akses is not None and not boleh(asal.akses, ak, dengan_modul=False):
            continue
        out.add(nm)
    return out


def alasan_ditolak(ds: Dataset, ak: AksesPengguna) -> str:
    from data.module_catalog import PORTAL_LABELS
    a = ds.akses
    portal = ", ".join(PORTAL_LABELS.get(p, p) for p in a.portal)
    teks = f"Akun ini tidak punya akses ke data '{ds.label}'"
    if portal:
        teks += f" (butuh akses Portal {portal} atau izin modulnya)"
    return teks + ". Minta admin menambahkan aksesnya di Peran & Hak Akses bila memang perlu."


def cv_aktif(ctx) -> str:
    cv = str(getattr(ctx, "cv", None) or "DA").upper()
    return cv if cv in ("DA", "SMU", "ALL") else "DA"


async def saringan_akses(ds: Dataset, ctx, ak: AksesPengguna) -> tuple:
    """(saringan field mentah, saringan setelah gabung, catatan) untuk CV, lingkup toko, dan baris gaji.
    Galat akses CV → AlatError 403 (pesan sama dengan penjaga CV)."""
    from core.entities import ALL, cv_access_problem, entity_match, entity_short
    db = ctx.db
    cv = cv_aktif(ctx)
    awal: list = []
    gabung: list = []
    catatan: list = []
    mode = ds.cv.get("mode", "tidak")
    if mode in ("field", "rekening") or ds.cv.get("periksa_izin"):
        masalah = cv_access_problem(list(ak.cv_boleh), cv)
        if masalah:
            raise AlatError(403, masalah)
    if mode == "field":
        f = entity_match(cv, ds.cv["field"])
        if f:
            awal.append(f)
    elif mode == "tetap":
        milik = ds.cv["milik"]
        if cv not in (milik, ALL):
            catatan.append(f"Data ini milik {entity_short(milik)}, jadi tidak disaring pilihan CV "
                           f"{entity_short(cv)} di layar.")
    elif mode == "saringan":
        f = ds.cv.get(cv) if cv != ALL else None
        if f:
            (gabung if ds.cv.get("gabung") else awal).append(dict(f))
    elif mode == "rekening":
        if cv != ALL:
            ids = [r["id"] async for r in db.rahaza_cash_accounts.find(entity_match(cv), {"_id": 0, "id": 1})
                   if r.get("id")]
            awal.append({ds.cv["field"]: {"$in": ids}})
    elif mode == "toko":
        from core import marketing_account_scope as _scope
        from core import ukuran_penjualan as U
        u = dict(getattr(ctx, "user", None) or {})
        u["_permissions"] = sorted(ak.izin)
        u["role"] = ak.peran or u.get("role")
        toko = await U.toko_terlihat(db, u, cv=cv)
        ids = [t["id"] for t in toko if t.get("id")]
        awal.append({ds.toko_field: {"$in": ids}})
        if not ids:
            catatan.append(_scope.NO_ACCOUNT_HINT if not _scope.sees_all_accounts(u)
                           else "Tidak ada toko pada pilihan CV ini.")
    if ds.baris_gaji and not ak.boleh_gaji:
        awal.append({"$and": [{p: {"$not": {"$regex": POLA_GAJI, "$options": "i"}}} for p in ds.baris_gaji]})
        catatan.append(CATATAN_GAJI_DISEMBUNYIKAN + " Baris gaji/tunjangan tidak ikut di hasil ini.")
    return awal, gabung, catatan


# ══════════════════════════════════════════════════════════════════════════════
# 4. EKSEKUSI & HASIL
# ══════════════════════════════════════════════════════════════════════════════
async def eksekusi(db, rencana: Rencana, *, maks_ms: int = MAKS_MS) -> tuple:
    """Jalankan pipeline → (baris, total_cocok). Galat Mongo → AlatError ramah (tanpa jejak teknis)."""
    try:
        cur = db[rencana.dataset.koleksi].aggregate(rencana.pipeline, maxTimeMS=int(maks_ms), allowDiskUse=True)
        hasil = await cur.to_list(1)
    except AlatError:
        raise
    except Exception as e:  # noqa: BLE001
        nama = type(e).__name__
        if "Timeout" in nama or "ExecutionTimeout" in nama or getattr(e, "code", None) == 50:
            raise AlatError(504, f"Pencarian data terlalu lama (lebih dari {maks_ms // 1000} detik). Persempit "
                                 "periode atau tambah filter.") from e
        log.exception("Pipeline katalog data %s gagal", rencana.dataset.id)
        raise AlatError(500, "Sistem gagal menjalankan pencarian data ini. Coba susun ulang permintaannya.") from e
    if not hasil:
        return [], 0
    h = hasil[0] or {}
    tot = (h.get("total") or [{}])
    return list(h.get("baris") or []), int((tot[0] or {}).get("n") or 0) if tot else 0


def _rapikan_angka(v: Any, tipe: str) -> Any:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return v
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if tipe == "uang":
        v = round(float(v), 2)
    elif isinstance(v, float):
        v = round(v, 4)
    return int(v) if isinstance(v, float) and v.is_integer() and abs(v) < 1e15 else v


def olah_baris(rencana: Rencana, baris: list, *, samaran=None, sdm_penuh: bool = False) -> list:
    """Rapikan angka, samarkan nama (vendor/pelanggan selalu; karyawan kecuali peran SDM penuh), saring teks bebas."""
    out = []
    for r in baris:
        row = {}
        for c in rencana.kolom:
            nm, tipe = c["nama"], c["tipe"]
            v = r.get(nm)
            if tipe in ("angka", "uang"):
                v = _rapikan_angka(v, tipe)
            jenis = rencana.samaran.get(nm)
            if jenis and isinstance(v, str) and v.strip() and samaran is not None \
                    and not (jenis == "karyawan" and sdm_penuh):
                v = samaran.code(v, jenis)
            if nm in rencana.bebas and isinstance(v, str) and v:
                if samaran is not None and hasattr(samaran, "scrub"):
                    v = samaran.scrub(v)
                else:
                    from services.ai.privacy import mask_pii
                    v = mask_pii(v)
            row[nm] = v
        out.append(row)
    return out


def _serial(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))


def muat_karakter(hasil: dict, batas: int = BATAS_KARAKTER_LANGSUNG) -> bool:
    """Potong `hasil["baris"]` dari bawah sampai muat `batas` karakter. True bila ada yang dibuang."""
    baris = hasil.get("baris") or []
    kepala = len(_serial({k: v for k, v in hasil.items() if k != "baris"})) + 200
    total = kepala
    for i, r in enumerate(baris):
        total += len(_serial(r)) + 1
        if total > batas:
            hasil["baris"] = baris[:i]
            return True
    return False


def ringkas_dataset(ds: Dataset, ak: AksesPengguna, *, rinci: bool = False) -> dict:
    """Bentuk dataset untuk `daftar_data` (hanya kolom yang boleh dibaca pengguna ini)."""
    boleh_k = kolom_boleh(ds, ak)
    kol = [k for k in kolom_lengkap(ds).values() if k.nama in boleh_k]
    out: dict = {"id": ds.id, "label": ds.label, "keterangan": ds.keterangan}
    if rinci:
        out["kelompok"] = LABEL_DOMAIN.get(ds.domain, ds.domain)
    if ds.kolom_tanggal and ds.kolom_tanggal in boleh_k:
        out["kolom_tanggal"] = ds.kolom_tanggal
    if rinci:
        rows = []
        for k in kol:
            d = {"nama": k.nama, "label": k.label, "tipe": k.tipe}
            if k.keterangan:
                d["keterangan"] = k.keterangan
            if k.nilai:
                d["nilai"] = list(k.nilai)
            if k.samaran and not (k.samaran == "karyawan" and ak.sdm_penuh):
                d["samaran"] = True
            rows.append(d)
        out["kolom"] = rows
    else:
        out["kolom"] = " ".join(f"{k.nama}:{k.tipe}" for k in kol if not k.dasar)
    if ds.catatan:
        out["catatan"] = list(ds.catatan)
    return out


async def cari(ctx, isian: dict) -> dict:
    """Isi alat `cari_data` (kontrak K1)."""
    ds_id = (isian or {}).get("dataset")
    ds = cari_dataset(ds_id)
    if ds is None:
        raise AlatError(404, f"Data '{_ringkas(ds_id)}' tidak ada di katalog. Panggil daftar_data untuk melihat "
                             "id data yang tersedia.")
    if getattr(ctx, "db", None) is None:
        raise AlatError(500, "Alat data tidak bisa membaca basis data saat ini.")
    ak = await akses_pengguna(ctx)
    if not dataset_boleh(ds, ak):
        raise AlatError(403, alasan_ditolak(ds, ak))
    kode = getattr(ctx, "pemanggil", "langsung") == "kode"
    batas_maks = BATAS_KODE if kode else BATAS_LANGSUNG
    awal, gabung, catatan = await saringan_akses(ds, ctx, ak)
    ps = getattr(ctx, "samaran", None)
    if ps is None or not callable(getattr(ps, "code", None)):
        from services.ai.privacy import Pseudonymizer
        ps = Pseudonymizer()   # tidak pernah lolos tanpa samaran
    pulihkan = getattr(ps, "real_name", None)
    try:
        r = bangun_rencana(ds, isian, kolom_boleh=kolom_boleh(ds, ak), batas_maks=batas_maks,
                           batas_bawaan=None if kode else BAWAAN_LANGSUNG, saringan_awal=awal,
                           saringan_gabung=gabung, pulihkan=pulihkan)
    except IsianSalah as e:
        raise AlatError(400, str(e)) from None
    baris, total = await eksekusi(ctx.db, r)
    baris = olah_baris(r, baris, samaran=ps, sdm_penuh=ak.sdm_penuh)
    hasil: dict = {"dataset": ds.id, "label": ds.label, "cv": label_cv(cv_aktif(ctx)), "kolom": r.kolom,
                   "baris": baris, "jumlah_baris": len(baris), "total_cocok": total,
                   "terpotong": total > len(baris)}
    catatan = list(catatan) + list(r.catatan)
    if any(j != "karyawan" or not ak.sdm_penuh for j in r.samaran.values()):
        catatan.append("Nama vendor/pelanggan" + ("" if ak.sdm_penuh else "/karyawan")
                       + " berupa kode samaran (mis. VND-001); kode yang sama berarti pihak yang sama.")
    if hasil["terpotong"]:
        catatan.append(f"Hanya {len(baris)} dari {total} baris yang dikirim. Pakai kelompok/agregasi supaya server "
                       "yang menghitung, atau panggil dari kode untuk batas yang lebih besar.")
    if catatan:
        hasil["catatan"] = catatan
    # Langsung: muat di bawah potongan 15.000 karakter inti. Kode: di bawah batas hasil untuk kode (inti menolak
    # JSON yang lebih besar, jadi lebih baik dipangkas rapi daripada gagal).
    from core.asisten_ai import alat_base as _ab
    batas_kar = (max(100_000, int(getattr(_ab, "BATAS_HASIL_KODE", 2_000_000)) - 50_000) if kode
                 else BATAS_KARAKTER_LANGSUNG)
    if muat_karakter(hasil, batas_kar):
        hasil["jumlah_baris"] = len(hasil["baris"])
        hasil["terpotong"] = True
        hasil.setdefault("catatan", []).append(
            f"Baris dipangkas menjadi {hasil['jumlah_baris']} supaya muat; persempit kolom, pakai agregasi"
            + ("." if kode else ", atau panggil dari kode."))
    hasil["_sumber"] = ds.label
    return hasil


async def daftar(ctx, isian: Optional[dict] = None) -> dict:
    """Isi alat `daftar_data`: dataset yang BOLEH dibaca pengguna ini."""
    ak = await akses_pengguna(ctx)
    pilih = (isian or {}).get("dataset")
    terlihat = [d for d in semua_dataset() if dataset_boleh(d, ak)]
    if pilih:
        ids = [pilih] if isinstance(pilih, str) else list(pilih)
        out = []
        for i in ids[:5]:
            d = cari_dataset(i)
            if d is None or d not in terlihat:
                raise AlatError(404, f"Data '{_ringkas(i)}' tidak ada atau tidak boleh dibaca akun ini.")
            out.append(ringkas_dataset(d, ak, rinci=True))
        return {"dataset": out, "_sumber": "Katalog data sistem"}
    return {
        "petunjuk": ("Pakai cari_data dengan id dataset di bawah. Panggil daftar_data {dataset: id} untuk label, "
                     "nilai, dan keterangan tiap kolom. op: " + ", ".join(OPS) + ". fungsi: " + ", ".join(FUNGSI)
                     + ". Periode memakai kolom_tanggal (TTTT-BB-HH, WIB); kolom turunan _bulan/_minggu/_tahun "
                       f"untuk tren. Batas baris: {BATAS_LANGSUNG} langsung, {BATAS_KODE} dari kode."),
        "cv": label_cv(cv_aktif(ctx)),
        "dataset": [ringkas_dataset(d, ak) for d in terlihat],
        "_sumber": "Katalog data sistem",
    }
