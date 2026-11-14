"""Aksi umum Asisten ERP — SEMUA aksi layar lewat katalog (keputusan owner K1–K10, 12 Nov 2026).

Dua alat menggantikan ratusan alat khusus:
  * `cari_aksi` (baca)  — cari aksi di katalog (`core/asisten_ai/katalog_aksi`) dengan kata biasa;
  * `jalankan_aksi` (tindakan) — kartu konfirmasi; setelah Setujui memanggil pintu yang SAMA dengan tombol layar
    (`ctx.api`, token pengguna sendiri + CV aktif). Tidak pernah memanggil fungsi route langsung (nilai bawaan Query
    FastAPI hanya benar lewat HTTP) dan tidak pernah menulis database langsung.

Pengaman per kartu (aturan di `katalog_aksi/aturan.py`):
  * larangan K5–K8 ditolak (scan/hitung fisik, kunci periode & tutup tahun, pengguna/peran/cadangan/integrasi/
    pengaturan, hapus permanen);
  * golongan B/C/D hanya untuk akun yang dinyalakan owner (K3); D hanya owner/superadmin/admin;
  * stok & uang tidak boleh dengan pilihan Semua CV;
  * tingkat: A rendah (hapus menengah) · B menengah · C/D tinggi (alasan + ketik ulang nominal/nomor);
  * kartu uang (C) di atas batas nominal (atau batas belum diisi) → persetujuan kedua owner (K4);
  * nilai lama dibaca lewat GET resmi; sidiknya diperiksa ulang saat dijalankan (data diubah orang lain → ditolak);
  * PUT mengirim isian lengkap seperti formulir layar (nilai lama + perubahan), PATCH hanya perubahan;
  * pembalikan otomatis hanya golongan A (hapus data yang baru dibuat / kembalikan nilai lama); stok & uang dibalik
    lewat aksi resmi batal/void sebagai kartu baru;
  * kartu kelompok sampai 50 baris untuk aksi yang sama (K10).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
from typing import Any, Optional
from urllib.parse import quote

from core.asisten_ai import katalog_aksi as kat
from core.asisten_ai.alat.baca_layar import HEADER_VENDOR, _pangkas, periksa_vendor
from core.asisten_ai.alat_base import AlatError, alat, periksa_skema, tindakan
from core.asisten_ai.katalog_aksi import aturan

MAKS_BARIS = 50
_NILAI_JALUR_RX = re.compile(r"^[^/?#\s\\]{1,128}$")
_KUNCI_IDENTITAS = ("number", "nomor", "no", "doc_number", "document_number", "invoice_number", "po_number",
                    "pr_number", "code", "kode", "sku", "name", "nama", "title", "judul", "label")
_KUNCI_NOMINAL = ("amount", "total", "nominal", "jumlah", "grand_total", "total_amount", "nilai", "paid_amount",
                  "payment_amount", "amount_paid", "net_pay", "total_net", "jumlah_bayar", "subtotal", "debit",
                  "credit", "value")
_KUNCI_ALASAN = ("reason", "alasan", "notes", "note", "catatan", "comment", "comments", "rejection_reason",
                 "cancel_reason", "void_reason")
_KUNCI_ABAIKAN_SIDIK = ("updated_at", "last_viewed_at", "viewed_at", "_id")
_BENAR = (True, 1, "1", "true", "True", "ya", "yes", "on")


# ── pembantu umum ────────────────────────────────────────────────────────────
def _db():
    from database import get_db
    return get_db()


async def _golongan_boleh(user: dict) -> dict:
    from core.asisten_ai import akses_pengguna as akp
    return (await akp.aturan(_db(), user)).get("golongan") or {"A": True}


def _tampil(v: Any, batas: int = 120) -> str:
    from core.asisten_ai.tindakan import _tampil as tampil
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False, default=str)
        return s if len(s) <= batas else s[: batas - 1] + "…"
    s = tampil(v)
    return s if len(s) <= batas else s[: batas - 1] + "…"


def _sama(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _doc_dari(r: Any) -> dict:
    """Jawaban GET → satu dokumen (bungkus umum `data`/`item`/`result` dibuka)."""
    if isinstance(r, dict):
        for k in ("data", "item", "result", "doc"):
            if isinstance(r.get(k), dict):
                return r[k]
        return r
    return {}


# Label isian untuk kartu (bukan nama kolom program — AGENTS.md: istilah program tidak ditampilkan ke pengguna).
_KATA_ISIAN = {
    "id": "", "account": "akun", "name": "nama", "code": "kode", "date": "tanggal", "qty": "jumlah",
    "quantity": "jumlah", "unit": "satuan", "price": "harga", "cost": "biaya", "total": "total", "amount": "nominal",
    "notes": "catatan", "note": "catatan", "reason": "alasan", "status": "status", "type": "jenis",
    "category": "kategori", "description": "keterangan", "title": "judul", "start": "mulai", "end": "selesai",
    "due": "jatuh tempo", "employee": "karyawan", "employees": "karyawan", "vendor": "vendor", "supplier": "pemasok",
    "customer": "pelanggan", "order": "pesanan", "orders": "pesanan", "product": "produk", "products": "produk",
    "material": "bahan", "materials": "bahan", "color": "warna", "colors": "warna", "size": "ukuran",
    "sizes": "ukuran", "location": "lokasi", "period": "periode", "payment": "pembayaran", "method": "cara",
    "bank": "bank", "cash": "kas", "is": "", "active": "aktif", "enabled": "aktif", "priority": "prioritas",
    "department": "departemen", "email": "email", "phone": "telepon", "address": "alamat", "items": "rincian",
    "item": "butir", "lines": "baris", "line": "baris", "platform": "platform", "platforms": "platform",
    "session": "sesi", "shift": "shift", "style": "style", "model": "model", "time": "jam", "at": "waktu",
    "deadline": "tenggat", "month": "bulan", "year": "tahun", "user": "pengguna", "role": "peran", "rating": "nilai",
    "source": "sumber", "reference": "referensi", "ref": "referensi", "no": "nomor", "number": "nomor",
    "stock": "stok", "min": "minimum", "max": "maksimum", "threshold": "ambang", "sample": "sampel",
    "request": "permintaan", "tax": "pajak", "pct": "(%)", "file": "berkas", "url": "tautan", "photos": "foto",
    "images": "foto", "content": "isi", "message": "pesan", "subject": "perihal", "city": "kota", "level": "tingkat",
    "stage": "tahap", "job": "pekerjaan", "po": "PO", "pr": "PR", "sku": "SKU", "hpp": "HPP", "gl": "akun",
    "coa": "akun", "debit": "debit", "credit": "kredit", "revenue": "omzet", "viewers": "penonton",
    "terms": "syarat", "condition": "kondisi", "comments": "komentar", "comment": "komentar", "memo": "memo",
    "approval": "persetujuan", "admin": "admin", "buyer": "pembeli", "client": "klien", "host": "host",
    "creator": "kreator", "tracking": "resi", "courier": "kurir", "return": "retur", "needed": "dibutuhkan",
    "by": "", "effective": "berlaku", "from": "dari", "to": "ke", "original": "asli", "base": "dasar",
    "range": "rentang", "destination": "tujuan", "expense": "biaya", "per": "per", "pcs": "pcs", "default": "bawaan",
    "duration": "durasi", "minutes": "menit", "tags": "label", "label": "label", "purpose": "keperluan",
    "work": "kerja", "seq": "urutan", "business": "usaha", "gender": "jenis kelamin", "season": "musim",
    "action": "tindakan", "mode": "mode", "key": "kunci", "values": "nilai", "value": "nilai", "hex": "kode warna",
    "manager": "manajer", "contract": "kontrak", "template": "templat", "catalog": "katalog", "target": "target",
    "assigned": "ditugaskan", "username": "nama pengguna", "uom": "satuan", "input": "masukan",
    "harga": "harga", "jual": "jual", "coret": "coret", "catatan": "catatan", "setujui": "setujui",
}


def label_isian(kunci: str) -> str:
    """'cash_account_id' → 'Kas akun'; kunci yang tidak dikenal tetap terbaca (garis bawah → spasi)."""
    bag = [k for k in re.split(r"[_\-.]+", str(kunci).lower()) if k]
    kata = [_KATA_ISIAN.get(k, k) for k in bag]
    dikenal = [k for k in bag if k in _KATA_ISIAN and _KATA_ISIAN[k]]
    if len(dikenal) == 2 and len([k for k in kata if k]) == 2 and bag[0] not in ("harga", "catatan"):
        kata = [k for k in kata if k][::-1]       # susunan Inggris (penjelas-inti) → Indonesia (inti-penjelas)
    teks = " ".join(k for k in kata if k).strip() or str(kunci)
    return teks[:1].upper() + teks[1:]


def _identitas(doc: dict, cadangan: str = "") -> str:
    for k in _KUNCI_IDENTITAS:
        v = (doc or {}).get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v).strip()[:80]
    return cadangan


def _angka(v) -> Optional[float]:
    if isinstance(v, str):
        try:
            v = float(v.replace(",", "."))
        except ValueError:
            return None
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0:
        return float(v)
    return None


def _nominal_baris(rows: Any) -> Optional[float]:
    """Nominal dari daftar baris: jurnal (jumlah debit), atau rincian (amount/total, atau qty x harga)."""
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        return None
    debit = sum(_angka(r.get("debit")) or 0 for r in rows)
    if debit:
        return debit
    total = 0.0
    for r in rows:
        v = next((_angka(r.get(k)) for k in ("amount", "total", "subtotal", "nominal", "nilai") if _angka(r.get(k))),
                 None)
        if v is None:
            q = _angka(r.get("qty")) or _angka(r.get("quantity"))
            h = _angka(r.get("unit_price")) or _angka(r.get("price")) or _angka(r.get("harga"))
            v = q * h if q and h else None
        total += v or 0
    return total or None


def _nominal(isian: dict, doc: dict) -> Optional[float]:
    for sumber in (isian or {}, doc or {}):
        for k in _KUNCI_NOMINAL:
            v = _angka(sumber.get(k))
            if v:
                return v
        for k in ("lines", "items", "entries", "details", "rincian"):
            v = _nominal_baris(sumber.get(k))
            if v:
                return v
    return None


def _rupiah(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def _sidik(docs: list) -> str:
    bersih = [{k: v for k, v in (d or {}).items() if k not in _KUNCI_ABAIKAN_SIDIK} for d in docs]
    return hashlib.sha1(json.dumps(bersih, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:40]


def _kunci_isian(a: dict) -> list:
    isi = a.get("isian") or {}
    if isi.get("bentuk") == "bertipe":
        return sorted(((isi.get("skema") or {}).get("properties") or {}).keys())
    return list(isi.get("kunci") or [])


def _isi_jalur(pola: str, nilai: dict) -> str:
    def ganti(m):
        v = nilai.get(m.group(1))
        return quote(str(v), safe="") if v is not None else m.group(0)
    return re.sub(r"\{(\w+)(?::[^}]*)?\}", ganti, pola)


# ── pemeriksaan aksi ─────────────────────────────────────────────────────────
async def _aksi_sah(ctx, aksi_id: str) -> dict:
    a = kat.ambil(aksi_id)
    if a is None:
        raise AlatError(404, "Aksi tidak dikenal. Cari dulu dengan alat cari_aksi lalu pakai kode aksinya.")
    lar = kat.larangan(a)
    if lar:
        tempat = f" Lakukan langsung di layar {a['layar']}." if a.get("layar") else ""
        raise AlatError(403, f"{lar['alasan']}{tempat}")
    if not aturan.di_ruang(a.get("portal") or [], getattr(ctx, "ruang", "umum")):
        raise AlatError(403, "Aksi ini bukan bagian dari ruang Asisten ini. Siapkan dari chat Asisten di Portal "
                             "Manajemen.")
    gol = a.get("golongan") or "A"
    boleh = await _golongan_boleh(ctx.user)
    if not boleh.get(gol):
        nama = aturan.GOLONGAN.get(gol, gol).lower()
        tempat = f" di layar {a['layar']}" if a.get("layar") else " di layar terkait"
        raise AlatError(403, f"Akun ini belum diizinkan owner memakai Asisten untuk aksi {nama}. Lakukan langsung"
                             f"{tempat}, atau minta owner menyalakannya di Monitor AI › Pengaturan.")
    if gol in ("B", "C") and ctx.cv not in ("DA", "SMU"):
        raise AlatError(400, "Aksi stok dan uang harus untuk satu CV. Pilih CV DA atau Sukma di atas chat, lalu minta "
                             "Asisten menyiapkan kartunya lagi.")
    return a


def _baris_dari(args: dict) -> list:
    if args.get("baris"):
        if any(k in args for k in ("jalur", "query", "isian")):
            raise AlatError(400, "Isi `baris` ATAU `jalur`/`query`/`isian`, tidak keduanya.")
        rows = args["baris"]
        if len(rows) > MAKS_BARIS:
            raise AlatError(400, f"Satu kartu paling banyak {MAKS_BARIS} baris.")
        return [{"jalur": dict(r.get("jalur") or {}), "query": dict(r.get("query") or {}),
                 "isian": copy.deepcopy(r.get("isian")) if r.get("isian") is not None else None} for r in rows]
    return [{"jalur": dict(args.get("jalur") or {}), "query": dict(args.get("query") or {}),
             "isian": copy.deepcopy(args.get("isian")) if args.get("isian") is not None else None}]


def _periksa_baris(a: dict, row: dict, no: int) -> None:
    pre = f"Baris {no}: " if no else ""
    for p in a.get("parameter_jalur") or []:
        v = row["jalur"].get(p)
        if v is None or not _NILAI_JALUR_RX.match(str(v)):
            raise AlatError(400, f"{pre}parameter alamat `{p}` wajib diisi dengan kode/id yang sah (baca datanya dulu).")
    lebih = set(row["jalur"]) - set(a.get("parameter_jalur") or [])
    if lebih:
        raise AlatError(400, f"{pre}parameter alamat tidak dikenal: {', '.join(sorted(lebih))}.")
    qnama = {q["nama"]: q for q in a.get("query") or []}
    for k, v in row["query"].items():
        if k in aturan.QUERY_HAPUS_PERMANEN and v in _BENAR:
            raise AlatError(403, aturan.PESAN_HAPUS_PERMANEN)
        # parameter yang tidak tercatat tetap diteruskan (pintu yang membaca `request.query_params` sendiri);
        # yang menghapus permanen sudah ditolak di atas.
        if isinstance(v, (dict, list)):
            raise AlatError(400, f"{pre}parameter `{k}` harus satu nilai.")
    for q in qnama.values():
        if q.get("wajib") and q["nama"] not in row["query"] and q["nama"] not in aturan.QUERY_HAPUS_PERMANEN:
            raise AlatError(400, f"{pre}parameter `{q['nama']}` wajib diisi.")
    isi = a.get("isian") or {}
    if row["isian"] is not None and not isinstance(row["isian"], dict):
        raise AlatError(400, f"{pre}isian harus berupa objek.")
    if isi.get("bentuk") == "bertipe" and row["isian"] is not None:
        errs = periksa_skema({k: v for k, v in (isi.get("skema") or {}).items() if k != "required"}, row["isian"])
        if errs:
            raise AlatError(400, f"{pre}isian tidak sah: " + "; ".join(errs[:4]) + ".")


def _cari_di_daftar(r: Any, nilai: str) -> Optional[dict]:
    """Satu data dari jawaban daftar (list / {items|data|rows|results: [...]}) yang id/nomor/kodenya = nilai."""
    kandidat = []
    if isinstance(r, list):
        kandidat = r
    elif isinstance(r, dict):
        for k in ("items", "data", "rows", "results", "list"):
            if isinstance(r.get(k), list):
                kandidat = r[k]
                break
    for d in kandidat:
        if isinstance(d, dict) and any(str(d.get(k)) == nilai for k in ("id", "uuid", "number", "nomor", "code",
                                                                         "kode", "doc_number", "invoice_number")):
            return d
    return None


async def _baca_lama(ctx, a: dict, row: dict, headers: Optional[dict] = None) -> Optional[dict]:
    if not a.get("baca"):
        bd = a.get("baca_daftar")
        if not bd:
            return None
        nilai = str(row["jalur"].get(bd["kunci"]) or "")
        try:
            r = await ctx.api("GET", _isi_jalur(bd["jalur"], row["jalur"]), params={"search": nilai, "q": nilai},
                              headers=headers)
        except AlatError as e:
            if e.status in (401, 403):
                raise
            return None
        return _cari_di_daftar(r, nilai)
    try:
        return _doc_dari(await ctx.api("GET", _isi_jalur(a["baca"], row["jalur"]), headers=headers))
    except AlatError as e:
        if e.status == 404:
            raise AlatError(404, f"Data untuk aksi ini tidak ditemukan ({_isi_jalur(a['baca'], row['jalur'])}). "
                                 "Periksa kode/id-nya.") from None
        if e.status in (401, 403):
            raise
        return None


def _badan(a: dict, row: dict, lama: Optional[dict]) -> Optional[dict]:
    """Isian yang dikirim. PUT ubah: isian lengkap seperti formulir layar (nilai lama + perubahan)."""
    isian = row["isian"]
    if a.get("metode") == "PUT" and a.get("jenis") == "ubah" and lama:
        penuh = {k: copy.deepcopy(lama[k]) for k in _kunci_isian(a) if k in lama}
        penuh.update(isian or {})
        return penuh
    return isian


def _isi_alasan(a: dict, badan: Optional[dict], alasan: str) -> Optional[dict]:
    """Alasan kartu diteruskan ke kolom alasan/catatan yang dibaca pintu ini (bila kosong)."""
    if not alasan:
        return badan
    kunci = set(_kunci_isian(a))
    for k in _KUNCI_ALASAN:
        if k in kunci and not (badan or {}).get(k):
            badan = dict(badan or {})
            badan[k] = f"{alasan} (via Asisten AI)"[:1000]
            break
    return badan


async def _lampiran(ctx, a: dict, args: dict) -> tuple:
    """(nama berkas, bytes, mime) dari lampiran chat milik pengguna (K9)."""
    lid = str(args.get("lampiran_id") or "").strip()
    if not lid:
        raise AlatError(400, "Aksi ini butuh berkas: lampirkan berkasnya di chat lalu isi `lampiran_id`.")
    doc = await _db().ai_lampiran.find_one({"id": lid, "user_id": ctx.user.get("id"), "dihapus": {"$ne": True}},
                                           {"_id": 0})
    if not doc:
        raise AlatError(404, "Lampiran tidak ditemukan di percakapan Anda.")
    return doc


# ── kartu ────────────────────────────────────────────────────────────────────
async def _susun(ctx, args: dict) -> dict:
    a = await _aksi_sah(ctx, args["aksi"])
    rows = _baris_dari(args)
    for i, r in enumerate(rows):
        _periksa_baris(a, r, i + 1 if len(rows) > 1 else 0)
    if (a.get("isian") or {}).get("bentuk") == "berkas":
        if len(rows) > 1:
            raise AlatError(400, "Impor berkas satu kartu satu berkas.")
        lamp = await _lampiran(ctx, a, args)
    else:
        lamp = None
    vendor = await _vendor(ctx, a, args)
    headers = {HEADER_VENDOR: vendor["id"]} if vendor else None
    lama_semua, badan_semua = [], []
    for r in rows:
        lama = await _baca_lama(ctx, a, r, headers)
        lama_semua.append(lama)
        badan_semua.append(_badan(a, r, lama))
    return {"a": a, "rows": rows, "lama": lama_semua, "badan": badan_semua, "lampiran": lamp, "vendor": vendor,
            "headers": headers}


async def _vendor(ctx, a: dict, args: dict) -> Optional[dict]:
    """Mode atas nama vendor CMT (sama dengan layar Input atas nama CMT): {id, nama} atau None."""
    vid = str(args.get("atas_nama_vendor") or "").strip()
    if not vid:
        return None
    if not a.get("atas_nama_vendor"):
        raise AlatError(400, "Aksi ini tidak punya mode atas nama vendor CMT.")
    periksa_vendor(ctx, vid, a.get("metode") or "POST")
    nama = vid
    try:
        r = await ctx.api("GET", "/api/vendor-portal/partners")
    except AlatError:
        r = None
    if r is not None:
        rows = r if isinstance(r, list) else ((r.get("items") or r.get("data") or []) if isinstance(r, dict) else [])
        cocok = next((x for x in rows if isinstance(x, dict) and str(x.get("id")) == vid), None)
        if cocok is None:
            raise AlatError(404, "Vendor CMT tidak ditemukan di master vendor. Periksa id vendornya.")
        nama = str(cocok.get("name") or cocok.get("nama") or cocok.get("code") or vid)
    return {"id": vid, "nama": nama}


def _perubahan_satu(a: dict, row: dict, lama: Optional[dict], badan: Optional[dict]) -> list:
    jenis = a.get("jenis")
    out = []
    if jenis == "hapus":
        out.append({"label": "Data", "sebelum": _identitas(lama or {}, "ada"), "sesudah": "Dihapus / dinonaktifkan"})
    elif jenis in ("aksi", "hitung", "impor"):
        out.append({"label": "Tindakan", "sebelum": _tampil((lama or {}).get("status")) if lama else "—",
                    "sesudah": a.get("label")})
    for k, v in (row["isian"] or {}).items():
        if jenis == "ubah" and lama is not None and k in lama and _sama(lama.get(k), v):
            continue
        out.append({"label": label_isian(k), "sebelum": _tampil(lama.get(k)) if lama and k in lama else "—",
                    "sesudah": _tampil(v)})
    for k, v in (row["query"] or {}).items():
        out.append({"label": label_isian(k), "sebelum": "—", "sesudah": _tampil(v)})
    if jenis == "ubah" and not out and (a.get("isian") or {}).get("bentuk") in ("bertipe", "bebas"):
        raise AlatError(400, "Tidak ada yang berubah dibanding data sekarang.")
    if not out:
        out.append({"label": "Tindakan", "sebelum": "—", "sesudah": a.get("label")})
    return out


async def _persetujuan_kedua(ctx, gol: str, nominal: Optional[float]) -> Optional[dict]:
    if gol != "C" or ctx.peran in ("owner", "superadmin"):
        return None
    from core.asisten_ai import tindakan as tdk
    atur = await tdk.pengaturan()
    bt, bh = atur["batas_nominal_transaksi"], atur["batas_nominal_harian"]
    if not bt or not bh:
        return {"perlu": True, "alasan": "batas nominal Asisten belum diisi owner, jadi setiap kartu uang perlu "
                                         "persetujuan kedua"}
    if nominal is None:
        return {"perlu": True, "alasan": "nominal aksi ini tidak terbaca dari datanya"}
    if nominal > bt:
        return {"perlu": True, "alasan": f"nominal Rp {_rupiah(nominal)} di atas batas Rp {_rupiah(bt)} per transaksi"}
    sudah = await tdk.nominal_hari_ini(_db(), ctx.user.get("id"))
    if sudah + nominal > bh:
        return {"perlu": True, "alasan": f"jumlah hari ini Rp {_rupiah(sudah + nominal)} di atas batas "
                                         f"Rp {_rupiah(bh)} per hari"}
    return None


def _konfirmasi(tingkat: str, nominal: Optional[float], lama: list, rows: list) -> Optional[dict]:
    if tingkat != "tinggi":
        return None
    if nominal:
        return {"teks": str(int(round(nominal))), "petunjuk": f"Ketik ulang nominal {_rupiah(nominal)} untuk menyetujui."}
    if len(rows) == 1:
        nomor = _identitas(lama[0] or {})
        if nomor and re.fullmatch(r"[\w./ -]{2,40}", nomor):
            return {"teks": nomor, "petunjuk": f"Ketik ulang {nomor} untuk menyetujui."}
    return {"teks": "SETUJU", "petunjuk": "Ketik SETUJU untuk menyetujui."}


# ── alat baca: cari aksi ─────────────────────────────────────────────────────
@alat(name="cari_aksi", kind="read", label="Mencari aksi di sistem", domain="umum",
      description=("Cari aksi tulis apa pun di sistem (buat, ubah, hapus, setujui, tolak, kirim, tutup, posting, "
                   "impor, dll. — semua tombol layar) dengan kata biasa, mis. 'kirim faktur piutang', 'tutup PO', "
                   "'setujui retur'. Pakai bila tidak ada alat tindakan khusus untuk permintaan pengguna. Hasil: kode "
                   "aksi, layar asal, golongan risiko, parameter alamat, query, dan isian untuk alat jalankan_aksi. "
                   "Aksi yang dilarang atau belum diizinkan untuk akun ini ikut ditandai beserta alasannya."),
      input_schema={"type": "object", "additionalProperties": False, "required": ["kata"], "properties": {
          "kata": {"type": "string", "minLength": 2, "maxLength": 200,
                   "description": "Kata kunci aksi dalam bahasa sehari-hari (Indonesia/Inggris)."},
          "portal": {"type": "string", "maxLength": 40, "description": "Opsional: nama portal, mis. Keuangan."},
          "batas": {"type": "integer", "minimum": 1, "maximum": 15}}})
async def cari_aksi(ctx, args: dict) -> dict:
    boleh = await _golongan_boleh(ctx.user)
    hasil = kat.cari(args["kata"], portal=args.get("portal"), batas=args.get("batas") or 8,
                     ruang=getattr(ctx, "ruang", "umum"))
    rows = []
    for a in hasil:
        g = a.get("golongan") or "A"
        ok = bool(boleh.get(g))
        alasan = "" if ok else (f"Akun ini belum diizinkan owner memakai Asisten untuk aksi "
                                f"{aturan.GOLONGAN.get(g, g).lower()}; arahkan ke layar {a.get('layar') or 'terkait'}.")
        rows.append(kat.ringkas_untuk_model(a, boleh=ok, alasan_tidak=alasan))
    return {"hasil": {"jumlah": len(rows), "aksi": rows,
                      "petunjuk": ("Baca data yang dituju dulu dengan alat baca (cari_data/daftar_data atau alat "
                                   "domain) untuk mendapat id/kode, lalu panggil jalankan_aksi. Satu kartu boleh "
                                   f"memuat sampai {MAKS_BARIS} baris aksi yang sama (isi `baris`).")}}


# ── alat tindakan: jalankan aksi ─────────────────────────────────────────────
_SKEMA_BARIS = {"type": "object", "additionalProperties": False, "properties": {
    "jalur": {"type": "object", "description": "Nilai parameter alamat, mis. {\"iid\": \"INV-001\"}.",
              "additionalProperties": {"type": ["string", "integer"]}},
    "query": {"type": "object", "description": "Parameter query aksi (lihat cari_aksi).",
              "additionalProperties": {"type": ["string", "integer", "number", "boolean"]}},
    "isian": {"type": "object", "description": "Isian (badan) aksi sesuai daftar isian dari cari_aksi."}}}


@tindakan(name="jalankan_aksi", label="Menjalankan aksi layar", domain="umum", risiko="rendah",
          description=("Siapkan kartu untuk SATU aksi dari katalog (kode dari cari_aksi), dijalankan lewat tombol "
                       "layar yang sama dengan izin pengguna sendiri. Isi `jalur` (parameter alamat), `query`, dan "
                       "`isian` persis seperti hasil cari_aksi; untuk banyak data dengan aksi yang sama isi `baris` "
                       f"(≤ {MAKS_BARIS}). Untuk impor berkas isi `lampiran_id` dari lampiran chat. Kartu menunjukkan "
                       "nilai lama → baru; aksi stok/uang/pengaturan meminta alasan dan konfirmasi tambahan."),
          input_schema={"type": "object", "additionalProperties": False, "required": ["aksi"], "properties": {
              "aksi": {"type": "string", "pattern": r"^[a-z0-9_]{3,130}$", "description": "Kode aksi dari cari_aksi."},
              **_SKEMA_BARIS["properties"],
              "baris": {"type": "array", "minItems": 1, "maxItems": MAKS_BARIS, "items": _SKEMA_BARIS},
              "lampiran_id": {"type": "string", "maxLength": 64},
              "atas_nama_vendor": {"type": "string", "maxLength": 80,
                                   "description": "Id vendor CMT: isi data atas nama vendor (layar Input atas nama "
                                                  "CMT); hanya untuk aksi yang mendukungnya."},
              "maksud": {"type": "string", "maxLength": 300,
                         "description": "Satu kalimat maksud pengguna, ditampilkan di kartu."}}})
class JalankanAksi:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        s = await _susun(ctx, args)
        a, rows, lama = s["a"], s["rows"], s["lama"]
        gol = a.get("golongan") or "A"
        tingkat = a.get("tingkat") or aturan.tingkat_untuk(gol, a.get("jenis"))
        if len(rows) == 1:
            perubahan = _perubahan_satu(a, rows[0], lama[0], s["badan"][0])
            nama = _identitas(lama[0] or {}, " · ".join(str(v) for v in rows[0]["jalur"].values()))
        else:
            perubahan = []
            for r, l, b in zip(rows, lama, s["badan"]):
                ubah = [x for x in _perubahan_satu(a, r, l, b) if x["label"] != "Tindakan"]
                ket = "; ".join(f"{x['label']}: {x['sesudah']}" for x in ubah[:3]) or a.get("label")
                perubahan.append({"label": _identitas(l or {}, " · ".join(str(v) for v in r["jalur"].values()))
                                  or "Data baru", "sebelum": _tampil((l or {}).get("status")) if l else "—",
                                  "sesudah": ket})
            nama = f"{len(rows)} data"
        nominal = None
        if gol == "C":
            vals = [_nominal(r["isian"] or {}, l or {}) for r, l in zip(rows, lama)]
            nominal = sum(v for v in vals if v) or None
        catatan = [f"Dijalankan lewat tombol yang sama dengan layar {a.get('layar') or 'terkait'}"
                   f"{' (' + ', '.join(a.get('portal') or []) + ')' if a.get('portal') else ''}, dengan izin "
                   "akun Anda sendiri.",
                   f"Golongan: {aturan.GOLONGAN.get(gol, gol)}."]
        if gol in ("B", "C"):
            catatan.append(f"CV: {'DA' if ctx.cv == 'DA' else 'Sukma'}.")
        if args.get("maksud"):
            catatan.insert(0, str(args["maksud"]).strip()[:300])
        if s["vendor"]:
            catatan.append(f"Diisi atas nama vendor CMT {s['vendor']['nama']}: tercatat sebagai input staf atas nama "
                           "vendor, sama dengan layar Input atas nama CMT.")
        if s["lampiran"]:
            catatan.append(f"Berkas: {s['lampiran'].get('nama')} ({round((s['lampiran'].get('ukuran') or 0) / 1024)} KB).")
        peringatan = []
        if a.get("jenis") in ("ubah", "hapus", "aksi") and not any(lama):
            peringatan.append("Nilai lama tidak bisa dibaca otomatis untuk aksi ini; periksa datanya di layar.")
        if not a.get("balik"):
            peringatan.append("Tidak bisa dibalikkan otomatis. Bila keliru, perbaiki lewat aksi resmi (batal/void/"
                              "ubah) di layar atau minta kartu baru.")
        if gol == "C" and nominal:
            peringatan.append(f"Nominal: Rp {_rupiah(nominal)}.")
        pk = await _persetujuan_kedua(ctx, gol, nominal)   # ditampilkan layar dari `persetujuan_kedua`
        rencana = {
            "judul": f"{a.get('label')}: {nama}"[:160] if nama else a.get("label"),
            "ringkas": f"{a.get('label')} — {nama}" if nama else a.get("label"),
            "perubahan": perubahan[:MAKS_BARIS + 10],
            "catatan": catatan, "peringatan": peringatan,
            "risiko": tingkat, "golongan": gol, "golongan_label": aturan.GOLONGAN.get(gol, gol),
            "sidik": _sidik(lama),
        }
        if a.get("menu"):
            rencana["tautan"] = {"label": f"Buka {a.get('layar') or 'layar terkait'}", "menu": a["menu"]}
        k = _konfirmasi(tingkat, nominal, lama, rows)
        if k:
            rencana["konfirmasi"] = k
        if pk:
            rencana["persetujuan_kedua"] = pk
        if nominal is not None:
            rencana["nominal"] = nominal
        return rencana

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        s = await _susun(ctx, args)
        a, rows = s["a"], s["rows"]
        if rencana.get("sidik") and _sidik(s["lama"]) != rencana["sidik"]:
            raise AlatError(409, "Data sudah berubah sejak kartu dibuat, jadi aksi tidak dijalankan. Minta Asisten "
                                 "menyiapkan kartu baru dengan data terkini.")
        alasan = str(getattr(ctx, "alasan", "") or "").strip()
        hasil, pembatalan, gagal = [], [], []
        for i, (r, lama, badan) in enumerate(zip(rows, s["lama"], s["badan"])):
            jalur = _isi_jalur(a["jalur"], r["jalur"])
            if a.get("jenis") in ("aksi", "hapus"):
                badan = _isi_alasan(a, badan, alasan)
            try:
                if s["lampiran"]:
                    from object_storage import get_object
                    got = await asyncio.to_thread(get_object, s["lampiran"]["path"])
                    if not got:
                        raise AlatError(404, "Isi berkas lampiran tidak ditemukan di penyimpanan.")
                    kolom = ((a.get("isian") or {}).get("kolom_berkas") or ["file"])[0]
                    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                            for k, v in (r["isian"] or {}).items()}
                    out = await ctx.api(a["metode"], jalur, params=r["query"] or None, data=data or None,
                                        headers=s["headers"],
                                        files={kolom: (s["lampiran"].get("nama") or "berkas", got[0],
                                                       s["lampiran"].get("mime") or got[1])})
                else:
                    # tanpa isian: POST/PUT tetap mengirim {} seperti layar (banyak pintu membaca badan JSON)
                    kirim = badan if badan is not None else ({} if a["metode"] != "DELETE" else None)
                    out = await ctx.api(a["metode"], jalur, params=r["query"] or None, json=kirim,
                                        headers=s["headers"])
            except AlatError as e:
                if len(rows) == 1:
                    raise
                gagal.append(f"baris {i + 1}: {e.pesan}")
                continue
            if len(rows) == 1:
                # satu baris: jawaban pintu diteruskan (pratinjau impor, galat per baris, nomor dokumen …), dipangkas
                catat: list = []
                ringkas_out = _pangkas(out, catat, maks=60, batas=2500) if out is not None else None
                if catat and isinstance(ringkas_out, dict):
                    ringkas_out = {**ringkas_out, "_catatan": catat[0]}
            else:
                ringkas_out = out if not isinstance(out, dict) else {
                    k: out.get(k) for k in ("id", "number", "nomor", "code", "kode", "status", "message", "detail")
                    if out.get(k) is not None}
            hasil.append(ctx.mask(ringkas_out) if ringkas_out else "berhasil")
            b = a.get("balik") or {}
            if b.get("jenis") == "hapus_buatan":
                oid = None
                if isinstance(out, dict):
                    oid = out.get("id") or (_doc_dari(out) or {}).get("id")
                if oid:
                    pembatalan.append({"jenis": "hapus", "jalur": re.sub(r"\{\w+\}", quote(str(oid), safe=""),
                                                                         b["jalur"], count=1)})
            elif b.get("jenis") == "kembalikan" and lama is not None and isinstance(badan, dict):
                pembatalan.append({"jenis": "kembalikan", "metode": a["metode"], "jalur": jalur,
                                   "baca": _isi_jalur(a["baca"], r["jalur"]),
                                   "lama": {k: copy.deepcopy(lama.get(k)) for k in badan if k in lama},
                                   "baru": {k: copy.deepcopy(v) for k, v in badan.items() if k in lama}})
        if not hasil:
            raise AlatError(400, "Semua baris gagal: " + "; ".join(gagal[:3]))
        label = a.get("label")
        if len(rows) == 1:
            ringkas = f"{label}: berhasil."
        else:
            ringkas = f"{label}: {len(hasil)} dari {len(rows)} baris berhasil."
            if gagal:
                ringkas += " Gagal — " + "; ".join(gagal[:5])
        out = {"ringkas": ringkas[:500], "hasil": {"baris": hasil[:MAKS_BARIS]}}
        if pembatalan and (a.get("golongan") or "A") == "A":
            out["pembatalan"] = {"aksi": a["id"], "langkah": pembatalan}
        return out

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        a = kat.ambil((pembatalan or {}).get("aksi") or "")
        if a is None or (a.get("golongan") or "A") != "A":
            raise AlatError(409, "Aksi ini tidak bisa dibalikkan otomatis. Kembalikan lewat layar terkait.")
        ok, lewat = 0, []
        for lk in (pembatalan or {}).get("langkah") or []:
            try:
                if lk.get("jenis") == "hapus":
                    await ctx.api("DELETE", lk["jalur"])
                    ok += 1
                elif lk.get("jenis") == "kembalikan":
                    sekarang = _doc_dari(await ctx.api("GET", lk["baca"]))
                    if any(not _sama(sekarang.get(k), v) for k, v in (lk.get("baru") or {}).items()):
                        lewat.append("data sudah diubah lagi sesudah tindakan ini")
                        continue
                    await ctx.api(lk.get("metode") or "PUT", lk["jalur"], json=lk.get("lama") or {})
                    ok += 1
            except AlatError as e:
                lewat.append(e.pesan)
        if not ok:
            raise AlatError(409, "Tidak ada yang bisa dibalikkan: " + ("; ".join(lewat[:3]) or "tidak ada langkah."))
        teks = f"{ok} perubahan dikembalikan."
        if lewat:
            teks += " Dilewati: " + "; ".join(lewat[:3])
        return {"ringkas": teks}
