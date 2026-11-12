"""Katalog aksi Asisten ERP (keputusan owner K1–K10, 12 Nov 2026).

Satu baris per aksi tulis yang dipanggil layar aktif (`data.json`, disusun `scripts/asisten_katalog/buat_katalog.py`
dari aplikasi + kode layar). Alat `cari_aksi` mencari di sini; alat `jalankan_aksi` menjalankan aksi lewat pintu
yang SAMA dengan tombol layarnya (`ctx.api`, token pengguna sendiri). Aturan golongan & larangan: `aturan.py`.

Bentuk satu aksi:
  {id, metode, jalur, modul, fungsi, label, keterangan, jenis (buat|ubah|hapus|aksi|hitung|impor),
   golongan (A|B|C|D), tingkat (rendah|menengah|tinggi), parameter_jalur [..], query [{nama, tipe, wajib, bawaan?}],
   isian {bentuk: bertipe|bebas|berkas, skema?, kunci?, kolom_berkas?}, baca (alamat GET nilai lama) | null,
   baca_daftar? {jalur, kunci} (cadangan: daftar GET koleksi, data dicari dengan nilai parameter `kunci`),
   balik {jenis: hapus_buatan|kembalikan, jalur?} | null, menu, layar, portal [..], larangan? {kode, alasan}}
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Optional

from core.asisten_ai.katalog_aksi import aturan

BERKAS = os.path.join(os.path.dirname(__file__), "data.json")
MAKS_HASIL = 15
_TOKEN_RX = re.compile(r"[a-z0-9]+")
# sinonim ringan kata sehari-hari → kata di label/alamat
SINONIM = {
    "hapus": ("hapus", "delete"), "ubah": ("ubah", "edit", "update"), "edit": ("ubah",), "buat": ("buat", "create"),
    "tambah": ("buat", "create"), "setujui": ("setujui", "approve"), "approve": ("setujui",), "tolak": ("tolak", "reject"),
    "batal": ("batalkan", "cancel", "void"), "batalkan": ("batalkan", "cancel", "void"), "kirim": ("kirim", "send"),
    "bayar": ("bayar", "pembayaran", "payment", "pay"), "pembayaran": ("payment", "pay"), "tutup": ("tutup", "close"),
    "faktur": ("faktur", "invoices"), "piutang": ("piutang", "ar"), "hutang": ("hutang", "ap"), "jurnal": ("jurnal", "journals"),
    "gaji": ("gaji", "payroll", "salary"), "cuti": ("cuti", "leaves", "leave"), "lembur": ("lembur", "overtime"),
    "karyawan": ("karyawan", "employees"), "stok": ("stok", "stock", "inventory"), "gudang": ("gudang", "wms", "wh"),
    "terima": ("terima", "receive", "receiving"), "retur": ("retur", "returns", "return"), "opname": ("opname", "opname3"),
    "pemasok": ("pemasok", "suppliers", "supplier"), "vendor": ("vendor", "partners"), "katalog": ("katalog", "catalogs"),
    "harga": ("harga", "price", "prices"), "promo": ("promo", "discounts"), "target": ("target", "targets"),
    "aset": ("aset", "assets"), "bahan": ("bahan", "materials", "material"), "kasbon": ("kasbon",),
    "klaim": ("klaim", "claims"), "posting": ("posting", "post"), "konfirmasi": ("konfirmasi", "confirm"),
}


@lru_cache(maxsize=1)
def muat() -> dict:
    with open(BERKAS, encoding="utf-8") as f:
        data = json.load(f)
    data["_per_id"] = {a["id"]: a for a in data.get("aksi") or []}
    pola = []
    for b in data.get("bacaan") or []:
        rx = "^" + re.sub(r"\\{(\w+)(?::[^}]*)?\\}", "([^/]+)", re.escape(b["jalur"].rstrip("/"))) + "$"
        pola.append((len(b.get("parameter_jalur") or []), re.compile(rx), b))
    data["_pola_bacaan"] = sorted(pola, key=lambda x: x[0])
    return data


def semua() -> list:
    return list(muat().get("aksi") or [])


def ambil(aksi_id: str) -> Optional[dict]:
    if not isinstance(aksi_id, str):
        return None
    return muat()["_per_id"].get(aksi_id.strip())


def semua_bacaan() -> list:
    return list(muat().get("bacaan") or [])


def bacaan_untuk(alamat: str) -> Optional[tuple]:
    """(baris bacaan, {parameter: nilai}) untuk alamat GET konkret, atau None bila bukan bacaan layar.
    Pola paling spesifik (parameter paling sedikit) menang."""
    path = str(alamat or "").split("?")[0].rstrip("/")
    for _n, rx, b in muat()["_pola_bacaan"]:
        m = rx.match(path)
        if m:
            return b, dict(zip(b.get("parameter_jalur") or [], m.groups()))
    return None


def cari_bacaan(kata: str, *, portal: Optional[str] = None, ruang: Optional[str] = None, batas: int = 8) -> list:
    """Bacaan layar paling cocok untuk kata kunci (skor sama dengan `cari`)."""
    return _cari(semua_bacaan(), kata, portal=portal, ruang=ruang, batas=batas)


def larangan(a: dict) -> Optional[dict]:
    """Larangan aksi — dari data DAN diperiksa ulang dengan aturan terkini (data basi tidak membuka larangan)."""
    return a.get("larangan") or aturan.larangan_untuk(a.get("metode", ""), a.get("jalur", ""))


def _token(teks: str) -> list:
    return _TOKEN_RX.findall(str(teks or "").lower())


def _teks_cari(a: dict) -> tuple:
    label = set(_token(a.get("label")))
    layar = set(_token(a.get("layar"))) | set(_token(" ".join(a.get("portal") or [])))
    lain = set(_token(a.get("jalur"))) | set(_token(a.get("keterangan"))) | set(_token(a.get("id")))
    return label, layar, lain


def cari(kata: str, *, golongan: Optional[list] = None, portal: Optional[str] = None,
         batas: int = 8, ruang: Optional[str] = None) -> list:
    """Aksi paling cocok untuk kata kunci (urut skor, lalu id). Kosong bila tidak ada yang cocok.
    `ruang` (umum | sdm | saya): hanya aksi dari portal ruang itu (aturan.PORTAL_RUANG)."""
    daftar = [a for a in semua() if not golongan or a.get("golongan") in golongan]
    return _cari(daftar, kata, portal=portal, ruang=ruang, batas=batas)


def _cari(daftar: list, kata: str, *, portal: Optional[str], ruang: Optional[str], batas: int) -> list:
    toks = _token(kata)
    if not toks:
        return []
    perluas = []
    for t in toks:
        perluas.append({t, *SINONIM.get(t, ())})
    pt = str(portal or "").strip().lower()
    hasil = []
    for a in daftar:
        if not aturan.di_ruang(a.get("portal") or [], ruang):
            continue
        if pt and not any(pt in p.lower() for p in a.get("portal") or []):
            continue
        label, layar, lain = _teks_cari(a)
        skor = 0
        for grup in perluas:
            s = 0
            for t in grup:
                if t in label:
                    s = max(s, 3)
                elif t in layar:
                    s = max(s, 2)
                elif t in lain:
                    s = max(s, 1)
                elif len(t) >= 4 and any(w.startswith(t) for w in label | layar | lain):
                    s = max(s, 1)
            skor += s
        if skor:
            hasil.append((skor, a))
    hasil.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [a for _s, a in hasil[:max(1, min(int(batas or 8), MAKS_HASIL))]]


def ringkas_untuk_model(a: dict, *, boleh: Optional[bool] = None, alasan_tidak: str = "") -> dict:
    """Baris katalog untuk model: cukup untuk mengisi `jalankan_aksi` tanpa istilah yang tidak perlu."""
    out = {"aksi": a["id"], "label": a.get("label"), "layar": a.get("layar") or None,
           "portal": a.get("portal") or [], "golongan": aturan.GOLONGAN.get(a.get("golongan"), a.get("golongan")),
           "tingkat": a.get("tingkat"), "jenis": a.get("jenis"), "alamat": f"{a.get('metode')} {a.get('jalur')}"}
    if a.get("keterangan"):
        out["keterangan"] = a["keterangan"][:240]
    if a.get("parameter_jalur"):
        out["parameter_jalur"] = a["parameter_jalur"]
    q = [x for x in a.get("query") or [] if x.get("nama") not in aturan.QUERY_HAPUS_PERMANEN]
    if q:
        out["query"] = q
    isian = a.get("isian") or {}
    if isian.get("bentuk") == "bertipe":
        out["isian"] = isian.get("skema")
    elif isian.get("bentuk") == "bebas":
        out["isian_kunci"] = isian.get("kunci") or []
        if isian.get("bersarang"):
            out["isian_bersarang"] = isian["bersarang"]     # mis. lines → [account_code, debit, credit, …]
        if isian.get("contoh_layar"):
            out["contoh_layar"] = isian["contoh_layar"]     # potongan kode layar yang mengirim isian ini
        out["isian_catatan"] = ("Isian bebas: kunci di atas dibaca pintu ini (isian_bersarang = kunci tiap butir "
                                "daftar; contoh_layar = cara layar mengirimnya). Isi dari data yang dibaca dulu "
                                "dengan baca_layar. Jangan menebak.")
    elif isian.get("bentuk") == "berkas":
        out["berkas"] = {"kolom_berkas": isian.get("kolom_berkas"), "isian_lain": isian.get("skema")}
        out["isian_catatan"] = "Butuh berkas: lampirkan di chat lalu isi `lampiran_id`."
    out["nilai_lama_dibaca"] = bool(a.get("baca") or a.get("baca_daftar"))
    out["bisa_dibalikkan"] = bool(a.get("balik"))
    if a.get("cari_id"):
        out["cari_id"] = a["cari_id"]        # {parameter/isian: [alamat GET untuk baca_layar]}
    if a.get("atas_nama_vendor"):
        out["atas_nama_vendor"] = ("Bisa diisi atas nama vendor CMT (isi `atas_nama_vendor` = id vendor), sama "
                                   "dengan layar Input atas nama CMT.")
    lar = larangan(a)
    if lar:
        out["dilarang"] = lar["alasan"]
    elif boleh is False:
        out["tidak_diizinkan"] = alasan_tidak
    return out


def ringkas_bacaan(b: dict) -> dict:
    """Baris bacaan untuk model (alat `baca_layar`)."""
    out = {"alamat": b["jalur"], "label": b.get("label"), "layar": b.get("layar") or None,
           "portal": b.get("portal") or []}
    if b.get("keterangan"):
        out["keterangan"] = b["keterangan"][:200]
    if b.get("parameter_jalur"):
        out["parameter_jalur"] = b["parameter_jalur"]
    if b.get("query"):
        out["query"] = [{k: v for k, v in q.items() if k in ("nama", "tipe", "wajib", "bawaan")} for q in b["query"]]
    if b.get("atas_nama_vendor"):
        out["atas_nama_vendor"] = True
    return out
