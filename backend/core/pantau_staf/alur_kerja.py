"""Alur kerja harian — Pemantauan staf (permintaan owner 14 Nov 2026).

Owner: "aksinya masih sangat sedikit … dibuat seperti alur yang benar-benar menggambarkan alurnya, grouping aktivitas
per alur dan sesuai step by step-nya berurutan." Audit aktivitas 13 Nov dibuat tangan dari log aktivitas, jejak audit,
dan pembuat dokumen; modul ini menghasilkan hal yang sama otomatis untuk SATU hari (WIB):

  * per ALUR bisnis (produksi, pesanan marketplace, R&D, aksesoris, gudang barang jadi, SDM, keuangan) langkah-langkahnya
    BERURUTAN; tiap langkah: apa yang dikerjakan hari itu dan oleh siapa (bukti dari dokumen, bukan centang),
    apa yang SEKARANG menunggu di langkah itu (dan sejak kapan), serta catatan kejanggalan (hasil potong jauh di atas
    rencana, semua scan keluar dibatalkan, PO draf yang kirimannya sudah jalan, belum ada biaya iklan, …);
  * alur MACET di langkah pertama (menurut urutan) yang punya dokumen menunggu melewati batasnya;
  * per STAF: pekerjaan hari itu dalam kalimat staf ("Impor pesanan 6×, Buat order cutting 11×"), jam aktif, dan
    akun yang tidak melakukan apa pun.

Sumber dibaca dari koleksi resmi (pembuat/penyetuju di dokumen). Bila dokumen tidak menyimpan pelakunya (warna, varian,
BOM, mulai/selesai cutting), pelaku diambil dari log aktivitas (`activity_logs`) yang ditulis rute yang sama.
Status dokumen tidak didefinisikan ulang: cutting (`core.cutting_material_issue`), penerimaan CMT
(`core.cmt_receipt_status`), lembar scan keluar (`core.scan_out`), opname (`core.opname_engine`), mode input toko
(`core.marketing_input_mode`). Langkah yang sudah punya aturan kewajiban (`katalog.KATALOG`) menampilkan penanggung
jawab & batas waktunya dari aturan itu — satu sumber dengan Aturan Kewajiban.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Optional

from core.pantau_staf.katalog import CUTTING, OPNAME, SCAN_OUT, Konteks
from core.pantau_staf.waktu import hitung_tenggat, jam_wib, label_tenggat, ts
from utils.waktu import now_utc, to_wib

log = logging.getLogger(__name__)

BATAS = 5000
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


# ── bentuk data ────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Aksi:
    """Satu pekerjaan yang tercatat pada hari itu."""
    waktu: Optional[datetime]
    user_id: Optional[str] = None
    nama: Optional[str] = None          # nama pelaku bila akunnya tidak dikenali
    nomor: str = ""
    jumlah: float = 1
    keterangan: str = ""
    batal: bool = False                 # pekerjaan yang dibatalkan (mis. baris scan keluar): tercatat untuk orangnya,
                                        # tetapi bukan kemajuan langkah


@dataclass
class Tunggu:
    """Satu dokumen/toko yang SEKARANG menunggu langkah ini dikerjakan."""
    nomor: str
    sejak: Optional[datetime] = None
    user_id: Optional[str] = None       # pembuat dokumen / PIC (orang yang paling dekat dengan langkah ini)
    nama: Optional[str] = None
    keterangan: str = ""
    batas: Optional[datetime] = None    # batas khusus (mis. data toko kemarin: pukul 10.00 hari ini)


@dataclass
class Catatan:
    pesan: str
    nomor: str = ""
    nada: str = "warning"               # warning | danger


@dataclass
class Ktx(Konteks):
    tanggal: Optional[date] = None
    a: Optional[datetime] = None        # awal hari WIB (UTC)
    b: Optional[datetime] = None        # awal hari berikutnya WIB (UTC)


@dataclass(frozen=True)
class Langkah:
    id: str
    alur: str
    urutan: int
    nama: str                            # kalimat staf: "Konfirmasi PO"
    bagian: str                          # bagian yang biasanya mengerjakan: "Produksi"
    satuan: str                          # satuan hitungan pekerjaan: "PO", "pcs", "pesanan"
    kerja: Callable[[Ktx], Awaitable[list]]
    tunggu: Optional[Callable[[Ktx], Awaitable[list]]] = None
    catatan: Optional[Callable[[Ktx, list, list], Awaitable[list]]] = None
    kewajiban: tuple = ()                # titik aksi Aturan Kewajiban yang sama
    link_module: Optional[str] = None
    batas_hari_kerja: int = 1            # menunggu lebih dari ini = macet (bila aturan tidak mengatur lain)
    jumlah_satuan: str = ""              # satuan jumlah bila beda dari hitungan (mis. "pcs", "baris")
    batas_teks: str = ""                 # kalimat batas bila bukan "N hari kerja" (mis. lembar ditutup pukul 23.55)


ALUR = {
    "produksi": ("Produksi: order cutting sampai barang keluar",
                 "Order cutting → potong → PO → kirim ke CMT → terima & QC → stok barang jadi → scan keluar → tutup hari."),
    "marketplace": ("Pesanan marketplace (per toko)",
                    "Impor pesanan → rekap harian → biaya iklan → kesehatan akun → ulasan → retur & komplain → katalog toko."),
    "rnd": ("R&D produk", "Style baru → revisi desain → tech pack → warna → model & varian (SKU) → ubah varian → BOM."),
    "aksesoris": ("Aksesoris", "Permintaan aksesoris → disiapkan → diserahkan; opname aksesoris dihitung lalu disetujui."),
    "gudang": ("Gudang barang jadi: retur & opname",
               "Retur fisik diterima → diperiksa → diselesaikan; opname barang jadi dihitung lalu disetujui."),
    "sdm": ("SDM", "Absensi harian → pengajuan cuti → keputusan cuti → perubahan data karyawan."),
    "keuangan": ("Keuangan", "Kas & pengeluaran → bayar tagihan pemasok → jurnal umum."),
    "master": ("Perubahan data master", "Bahan & aksesoris → pemasok → peran & akses pengguna."),
}
ALUR_URUT = list(ALUR)


# ── bantu ─────────────────────────────────────────────────────────────────────────────────────────────────
def _rentang(f: str, a: datetime, b: datetime) -> dict:
    """`a <= f < b` untuk nilai bertipe datetime ATAU teks ISO (Mongo membandingkan per tipe)."""
    return {"$or": [{f: {"$gte": a, "$lt": b}}, {f: {"$gte": a.isoformat(), "$lt": b.isoformat()}}]}


def _rentang_salah_satu(fields: tuple, a: datetime, b: datetime) -> dict:
    return {"$or": [c for f in fields for c in _rentang(f, a, b)["$or"]]}


def _dalam(v, ctx: Ktx) -> bool:
    t = ts(v)
    return t is not None and ctx.a <= t < ctx.b


def _pertama(*nilai):
    for v in nilai:
        if v not in (None, ""):
            return v
    return None


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _layak_tampil(v) -> bool:
    s = str(v or "").strip()
    return bool(s) and not _UUID.match(s)


SISTEM = {"system", "sistem", "auto", "scheduler", "otomatis"}
NAMA_SISTEM = "Sistem (otomatis)"


def pelaku(ctx: Konteks, *nilai) -> tuple[Optional[str], Optional[str]]:
    """(id akun, nama tampilan) dari isian pelaku apa pun (id / email / nama). Nama ganda tidak ditebak.
    Isian "system" = dikerjakan otomatis oleh sistem (mis. sinkron master), bukan oleh staf."""
    for v in nilai:
        if isinstance(v, str) and (v.strip().lower() in SISTEM or v.strip().lower().startswith("migrasi")):
            return None, NAMA_SISTEM
    for v in nilai:
        if not v or not isinstance(v, str):
            continue
        uid = ctx.id_dari(v)
        if uid:
            u = ctx.users.get(uid) or {}
            return uid, u.get("name") or u.get("email") or v
    for v in nilai:
        if isinstance(v, str) and _layak_tampil(v):
            return None, v.split("@")[0] if "@" in v else v
    return None, None


def _aksi(ctx: Ktx, waktu, *siapa, **kw) -> Aksi:
    uid, nama = pelaku(ctx, *siapa)
    return Aksi(waktu=ts(waktu), user_id=uid, nama=nama, **kw)


def _tunggu(ctx: Ktx, nomor, sejak, *siapa, **kw) -> Tunggu:
    uid, nama = pelaku(ctx, *siapa)
    return Tunggu(nomor=str(nomor or ""), sejak=ts(sejak), user_id=uid, nama=nama, **kw)


_KATA_PERAN = {"pic": "PIC", "qc": "QC", "hr": "SDM", "rnd": "R&D", "spv": "supervisor", "cs": "CS", "kol": "KOL",
               "manager": "manajer", "staff": "staf", "sales": "penjualan", "ppic": "PPIC", "cuting": "cutting"}


def label_peran(kode) -> str:
    """Kode peran → nama untuk layar (`pic_toko` → "PIC toko"); peran buatan owner ("HR Generalist") apa adanya.
    Sama dengan `frontend/.../akses/labelPeran.js` untuk kata yang umum."""
    s = str(kode or "").strip()
    if not s or re.search(r"[A-Z\s&/]", s):
        return s or "—"
    kata = [_KATA_PERAN.get(w, w) for w in re.split(r"[_\-.]+", s.lower()) if w]
    t = " ".join(kata)
    return t[:1].upper() + t[1:]


def tgl_pendek(v) -> str:
    t = ts(v)
    if not t:
        return "—"
    w = to_wib(t)
    return f"{w.day} {BULAN[w.month - 1]}"


async def _cari(db, koleksi: str, q: dict, proj: dict | None = None, limit: int = BATAS) -> list:
    p = {"_id": 0, **(proj or {})} if proj else {"_id": 0}
    return await db[koleksi].find(q, p).to_list(limit)


async def _log(ctx: Ktx, modul: str, aksi: tuple) -> list:
    """Baris log aktivitas hari itu untuk (modul, aksi) — sekali per pindaian."""
    kunci = ("log", modul, aksi)
    if kunci not in ctx.cache:
        ctx.cache[kunci] = await _cari(ctx.db, "activity_logs", {
            "module": modul, "action": {"$in": list(aksi)}, **_rentang("timestamp", ctx.a, ctx.b)},
            {"user_id": 1, "user_name": 1, "details": 1, "timestamp": 1, "action": 1})
    return ctx.cache[kunci]


def _dari_log(ctx: Ktx, rows: list, *, unik: bool = False, nomor=None) -> list:
    """Log → Aksi. `unik` = satu dokumen dihitung sekali per orang per hari (mis. BOM yang disimpan berkali-kali)."""
    out, lihat = [], set()
    for r in rows:
        det = str(r.get("details") or "")
        if unik:
            k = (r.get("user_id"), det)
            if k in lihat:
                continue
            lihat.add(k)
        uid, nama = pelaku(ctx, r.get("user_id"), r.get("user_name"))
        no = nomor(r) if nomor else (det if _layak_tampil(det) and len(det) <= 40 else "")
        out.append(Aksi(waktu=ts(r.get("timestamp")), user_id=uid, nama=nama or r.get("user_name"), nomor=no or ""))
    return out


# ── A. Produksi ───────────────────────────────────────────────────────────────────────────────────────────
async def _potong_hari_ini(ctx: Ktx) -> list:
    if "potong" not in ctx.cache:
        ctx.cache["potong"] = await _cari(ctx.db, CUTTING, _rentang_salah_satu(
            ("created_at", "started_at", "completed_at"), ctx.a, ctx.b), {
            "id": 1, "number": 1, "status": 1, "created_at": 1, "created_by": 1, "created_by_name": 1,
            "started_at": 1, "completed_at": 1, "planned_output_qty": 1, "produced_qty": 1, "style_name": 1,
            "model_name": 1, "output_color": 1, "po_number": 1})
    return ctx.cache["potong"]


def _ket_potong(r: dict) -> str:
    return " · ".join(x for x in (r.get("style_name") or r.get("model_name"), r.get("output_color")) if x)


async def _k_order_cutting(ctx: Ktx) -> list:
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"), nomor=r.get("number") or "",
                  jumlah=_num(r.get("planned_output_qty")) or 1, keterangan=_ket_potong(r))
            for r in await _potong_hari_ini(ctx) if _dalam(r.get("created_at"), ctx) and r.get("status") != "cancelled"]


async def _k_mulai_cutting(ctx: Ktx) -> list:
    return _dari_log(ctx, await _log(ctx, "cutting.order", ("start",)))


async def _t_mulai_cutting(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, CUTTING, {"status": "draft"}, {"number": 1, "created_at": 1, "created_by": 1,
                                                                 "created_by_name": 1, "style_name": 1, "model_name": 1,
                                                                 "output_color": 1, "planned_output_qty": 1})
    return [_tunggu(ctx, r.get("number"), r.get("created_at"), r.get("created_by"), r.get("created_by_name"),
                    keterangan=f"{_ket_potong(r)} · rencana {_num(r.get('planned_output_qty')):g} pcs".strip(" ·"))
            for r in rows]


async def _k_catat_progres(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "cutting_progress", _rentang("created_at", ctx.a, ctx.b), {
        "cutting_number": 1, "created_at": 1, "created_by": 1, "created_by_name": 1, "output_qty": 1})
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"),
                  nomor=r.get("cutting_number") or "", jumlah=_num(r.get("output_qty")) or 1) for r in rows]


async def _k_selesai_cutting(ctx: Ktx) -> list:
    rows = await _potong_hari_ini(ctx)
    pelaku_log = {str(r.get("details") or ""): r for r in await _log(ctx, "cutting.order", ("complete",))}
    out = []
    for r in rows:
        if r.get("status") != "completed" or not _dalam(r.get("completed_at"), ctx):
            continue
        lg = pelaku_log.get(r.get("number") or "") or {}
        out.append(_aksi(ctx, r.get("completed_at"), lg.get("user_id"), lg.get("user_name"),
                         nomor=r.get("number") or "", jumlah=_num(r.get("produced_qty")),
                         keterangan=f"rencana {_num(r.get('planned_output_qty')):g} pcs, jadi "
                                    f"{_num(r.get('produced_qty')):g} pcs"))
    return out


async def _t_selesai_cutting(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, CUTTING, {"status": "in_progress"}, {
        "number": 1, "started_at": 1, "created_at": 1, "style_name": 1, "model_name": 1, "output_color": 1})
    mulai = {str(r.get("details") or ""): r for r in await _cari(ctx.db, "activity_logs", {
        "module": "cutting.order", "action": "start", "details": {"$in": [r.get("number") for r in rows if r.get("number")]}},
        {"details": 1, "user_id": 1, "user_name": 1})} if rows else {}
    return [_tunggu(ctx, r.get("number"), _pertama(r.get("started_at"), r.get("created_at")),
                    (mulai.get(r.get("number") or "") or {}).get("user_id"), keterangan=_ket_potong(r))
            for r in rows]


async def _c_selesai_cutting(ctx: Ktx, kerja: list, tunggu: list) -> list:
    out = []
    for r in await _potong_hari_ini(ctx):
        if r.get("status") != "completed" or not _dalam(r.get("completed_at"), ctx):
            continue
        rencana, jadi = _num(r.get("planned_output_qty")), _num(r.get("produced_qty"))
        if rencana > 0 and jadi > rencana * 1.2:
            out.append(Catatan(nomor=r.get("number") or "", nada="warning",
                               pesan=f"Hasil {jadi:g} pcs dari rencana {rencana:g} (+{round(100 * (jadi - rencana) / rencana)}%). "
                                     "Pastikan memang diminta sebanyak itu, bukan kain dipotong sampai habis."))
        elif rencana > 0 and jadi < rencana * 0.9:
            out.append(Catatan(nomor=r.get("number") or "", nada="warning",
                               pesan=f"Hasil {jadi:g} pcs, kurang dari rencana {rencana:g}."))
    return out


async def _po_hari_ini(ctx: Ktx) -> list:
    if "po" not in ctx.cache:
        ctx.cache["po"] = await _cari(ctx.db, "production_pos", {
            "opening_import": {"$exists": False}, **_rentang_salah_satu(("created_at", "confirmed_at"), ctx.a, ctx.b)}, {
            "id": 1, "po_number": 1, "business_type": 1, "status": 1, "created_at": 1, "created_by": 1,
            "confirmed_at": 1, "confirmed_by": 1, "vendor_name": 1, "customer_name": 1})
    return ctx.cache["po"]


def _jenis_po(r: dict) -> str:
    return "PO maklon" if (r.get("business_type") or "") == "maklon" else "PO internal"


def _ket_po(r: dict) -> str:
    return " · ".join(x for x in (_jenis_po(r), r.get("vendor_name") or r.get("customer_name")) if x)


async def _k_buat_po(ctx: Ktx) -> list:
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), nomor=r.get("po_number") or "", keterangan=_ket_po(r))
            for r in await _po_hari_ini(ctx) if _dalam(r.get("created_at"), ctx)]


async def _k_konfirmasi_po(ctx: Ktx) -> list:
    return [_aksi(ctx, r.get("confirmed_at"), r.get("confirmed_by"), nomor=r.get("po_number") or "",
                  keterangan=_ket_po(r))
            for r in await _po_hari_ini(ctx) if r.get("status") != "Draft" and _dalam(r.get("confirmed_at"), ctx)]


async def _po_draf(ctx: Ktx) -> list:
    if "po_draf" not in ctx.cache:
        ctx.cache["po_draf"] = await _cari(ctx.db, "production_pos", {
            "status": "Draft", "opening_import": {"$exists": False}}, {
            "id": 1, "po_number": 1, "business_type": 1, "created_at": 1, "created_by": 1, "vendor_name": 1,
            "customer_name": 1})
    return ctx.cache["po_draf"]


async def _t_konfirmasi_po(ctx: Ktx) -> list:
    return [_tunggu(ctx, r.get("po_number"), r.get("created_at"), r.get("created_by"), keterangan=_ket_po(r))
            for r in await _po_draf(ctx)]


async def _c_konfirmasi_po(ctx: Ktx, kerja: list, tunggu: list) -> list:
    draf = {r["id"]: r for r in await _po_draf(ctx)}
    if not draf:
        return []
    kirim = await _cari(ctx.db, "vendor_shipments", {"po_id": {"$in": list(draf)}, "opening": {"$ne": True},
                                                     "status": {"$in": ["Sent", "Received"]}},
                        {"po_id": 1, "shipment_number": 1, "vendor_name": 1})
    out, lihat = [], set()
    for s in kirim:
        p = draf.get(s.get("po_id"))
        if not p or p["id"] in lihat:
            continue
        lihat.add(p["id"])
        out.append(Catatan(nomor=p.get("po_number") or "", nada="danger",
                           pesan=f"Sudah dikirim ke {s.get('vendor_name') or 'CMT'} ({s.get('shipment_number') or 'kiriman'}) "
                                 "tetapi PO masih draf. Hasil CMT tidak bisa diterima sebelum PO dikonfirmasi."))
    return out


async def _k_kirim_cmt(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "vendor_shipments", {"opening": {"$ne": True}, **_rentang("created_at", ctx.a, ctx.b)}, {
        "shipment_number": 1, "created_at": 1, "created_by": 1, "entered_by_id": 1, "entered_by": 1, "vendor_name": 1,
        "po_number": 1, "status": 1})
    return [_aksi(ctx, r.get("created_at"), r.get("entered_by_id"), r.get("entered_by"), r.get("created_by"),
                  nomor=r.get("shipment_number") or "",
                  keterangan=" · ".join(x for x in (r.get("vendor_name"), f"PO {r['po_number']}" if r.get("po_number") else "")
                                        if x))
            for r in rows if r.get("status") != "Cancelled"]


async def _t_kirim_cmt(ctx: Ktx) -> list:
    """PO terkonfirmasi yang belum punya kiriman ke CMT sama sekali."""
    pos = await _cari(ctx.db, "production_pos", {"status": "Confirmed", "opening_import": {"$exists": False}}, {
        "id": 1, "po_number": 1, "business_type": 1, "confirmed_at": 1, "confirmed_by": 1, "vendor_name": 1})
    if not pos:
        return []
    ada = {s.get("po_id") for s in await _cari(ctx.db, "vendor_shipments", {
        "po_id": {"$in": [p["id"] for p in pos]}, "status": {"$in": ["Sent", "Received"]}}, {"po_id": 1})}
    return [_tunggu(ctx, p.get("po_number"), p.get("confirmed_at"), p.get("confirmed_by"), keterangan=_ket_po(p))
            for p in pos if p["id"] not in ada]


def _qc_selesai_at(r: dict):
    return _pertama(r.get("qc_completed_at"), r.get("approved_at"))


async def _qc_hari_ini(ctx: Ktx) -> list:
    if "qc" not in ctx.cache:
        from core.cmt_receipt_status import ST_DONE, canon_status
        rows = await _cari(ctx.db, "cmt_receipts", _rentang_salah_satu(("qc_completed_at", "approved_at"), ctx.a, ctx.b), {
            "id": 1, "receipt_code": 1, "po_number": 1, "status": 1, "qc_completed_at": 1, "qc_completed_by": 1,
            "approved_at": 1, "approved_by": 1, "cmt_name": 1, "total_actual": 1, "total_rejected": 1})
        ctx.cache["qc"] = [r for r in rows if canon_status(r.get("status")) == ST_DONE and _dalam(_qc_selesai_at(r), ctx)]
    return ctx.cache["qc"]


async def _k_terima_qc(ctx: Ktx) -> list:
    return [_aksi(ctx, _qc_selesai_at(r), r.get("qc_completed_by"), r.get("approved_by"),
                  nomor=r.get("receipt_code") or "", jumlah=_num(r.get("total_actual")) or 1,
                  keterangan=" · ".join(x for x in (r.get("cmt_name"), f"PO {r['po_number']}" if r.get("po_number") else "")
                                        if x))
            for r in await _qc_hari_ini(ctx)]


async def _t_terima_qc(ctx: Ktx) -> list:
    from core.cmt_receipt_status import ST_QC, canon_status
    rows = await _cari(ctx.db, "cmt_receipts", {"status": {"$in": ["on_qc", "draft", "Draft", "submitted", "Submitted"]}}, {
        "receipt_code": 1, "po_number": 1, "status": 1, "created_at": 1, "created_by": 1, "cmt_name": 1})
    return [_tunggu(ctx, r.get("receipt_code"), r.get("created_at"), r.get("created_by"),
                    keterangan=" · ".join(x for x in (r.get("cmt_name"), f"PO {r['po_number']}" if r.get("po_number") else "")
                                          if x))
            for r in rows if canon_status(r.get("status")) == ST_QC]


async def _k_stok_fg(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "cmt_receipt_lines", _rentang("fg_stock_posted_at", ctx.a, ctx.b), {
        "receipt_id": 1, "fg_stock_posted_at": 1, "fg_stock_posted_qty": 1, "fg_material_code": 1, "sku": 1})
    if not rows:
        return []
    rc = {r["id"]: r for r in await _cari(ctx.db, "cmt_receipts", {"id": {"$in": list({x.get("receipt_id") for x in rows})}},
                                          {"id": 1, "receipt_code": 1, "qc_completed_by": 1, "approved_by": 1})}
    per: dict = {}
    for ln in rows:
        r = rc.get(ln.get("receipt_id")) or {}
        k = r.get("id") or ln.get("receipt_id")
        cur = per.get(k)
        if cur is None:
            per[k] = cur = _aksi(ctx, ln.get("fg_stock_posted_at"), r.get("qc_completed_by"), r.get("approved_by"),
                                 nomor=r.get("receipt_code") or "", jumlah=0)
        cur.jumlah += _num(ln.get("fg_stock_posted_qty"))
    return list(per.values())


async def _scan_baris(ctx: Ktx) -> list:
    if "scan" not in ctx.cache:
        hari = ctx.tanggal.isoformat()
        ctx.cache["scan"] = await _cari(ctx.db, "wh_scan_out_lines", {"date": hari}, {
            "sheet_number": 1, "status": 1, "qty": 1, "sku": 1, "operator_id": 1, "operator_name": 1, "scanned_at": 1,
            "processed_at": 1, "voided_at": 1, "voided_by_id": 1, "voided_by": 1, "location_code": 1})
    return ctx.cache["scan"]


async def _k_scan_keluar(ctx: Ktx) -> list:
    out = []
    for r in await _scan_baris(ctx):
        if r.get("status") == "active":
            out.append(_aksi(ctx, _pertama(r.get("scanned_at"), r.get("processed_at")), r.get("operator_id"),
                             r.get("operator_name"), nomor=r.get("sku") or "", jumlah=_num(r.get("qty")) or 1))
        elif r.get("status") == "voided":
            out.append(_aksi(ctx, _pertama(r.get("voided_at"), r.get("scanned_at")), r.get("voided_by_id"),
                             r.get("voided_by"), nomor=r.get("sku") or "", jumlah=_num(r.get("qty")) or 1,
                             keterangan="dibatalkan", batal=True))
    return out


async def _c_scan_keluar(ctx: Ktx, kerja: list, tunggu: list) -> list:
    batal = [r for r in await _scan_baris(ctx) if r.get("status") == "voided"]
    if not batal:
        return []
    pcs = sum(_num(r.get("qty")) for r in batal)
    oleh = sorted({pelaku(ctx, r.get("voided_by_id"), r.get("voided_by"))[1] or "tidak tercatat" for r in batal})
    semua = not kerja
    return [Catatan(nada="danger" if semua else "warning",
                    pesan=(f"{'Semua ' if semua else ''}{len(batal)} baris scan keluar ({pcs:g} pcs) dibatalkan oleh "
                           f"{', '.join(oleh)}." + (" Barang yang benar-benar keluar hari ini belum tercatat; stok sistem "
                                                    "lebih besar dari fisik." if semua else "")))]


async def _k_tutup_hari(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, SCAN_OUT, {"date": ctx.tanggal.isoformat(), "status": "closed"}, {
        "number": 1, "closed_at": 1, "closed_by": 1, "closed_by_id": 1, "auto_closed": 1, "location_name": 1})
    return [_aksi(ctx, r.get("closed_at"), r.get("closed_by_id"), r.get("closed_by"), nomor=r.get("number") or "",
                  keterangan=r.get("location_name") or "")
            for r in rows if not r.get("auto_closed")]


async def _t_tutup_hari(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, SCAN_OUT, {"status": {"$in": ["open", "closing"]}}, {
        "number": 1, "date": 1, "created_at": 1, "created_by_id": 1, "created_by": 1, "location_name": 1})
    return [_tunggu(ctx, r.get("number") or r.get("date"), r.get("created_at"), r.get("created_by_id"), r.get("created_by"),
                    keterangan=f"{r.get('location_name') or ''} · lembar {tgl_pendek(r.get('date'))}".strip(" ·"),
                    batas=jam_wib(date.fromisoformat(str(r.get("date"))[:10]), "23:55") if r.get("date") else None)
            for r in rows]


async def _c_tutup_hari(ctx: Ktx, kerja: list, tunggu: list) -> list:
    rows = await _cari(ctx.db, SCAN_OUT, {"date": ctx.tanggal.isoformat(), "status": "closed", "auto_closed": True},
                       {"number": 1, "location_name": 1})
    return [Catatan(nomor=r.get("number") or "", pesan="Lembar ditutup otomatis oleh sistem pukul 23.55 — tidak ada yang "
                                                       "menutupnya.") for r in rows]


# ── B. Pesanan marketplace ───────────────────────────────────────────────────────────────────────────────
async def _toko(ctx: Ktx) -> list:
    if "toko" not in ctx.cache:
        from core import marketing_input_mode as _mode
        akun = await _cari(ctx.db, "marketing_platform_accounts", {"status": "active"}, None, 500)
        for a in akun:
            try:
                a["_impor"] = (await _mode.mode_toko(ctx.db, a)) == _mode.IMPOR
            except Exception:  # noqa: BLE001 — satu toko gagal tidak menghentikan layar
                a["_impor"] = False
        ctx.cache["toko"] = [a for a in akun if a.get("id")]
    return ctx.cache["toko"]


async def _data_toko_kemarin(ctx: Ktx) -> dict:
    """{account_id: [sumber data penjualan bertanggal KEMARIN dari hari yang dipilih]}."""
    if "toko_kemarin" not in ctx.cache:
        kemarin = (ctx.tanggal - timedelta(days=1)).isoformat()
        ada: dict = {}
        for r in await _cari(ctx.db, "marketing_sales_data", {"date": kemarin}, {"account_id": 1, "source": 1}):
            ada.setdefault(r.get("account_id"), []).append(r.get("source") or "")
        ctx.cache["toko_kemarin"] = ada
    return ctx.cache["toko_kemarin"]


def _nama_toko(a: dict) -> str:
    return a.get("account_name") or a.get("name") or a.get("id") or "Toko"


async def _t_toko(ctx: Ktx, *, impor: bool) -> list:
    kemarin = ctx.tanggal - timedelta(days=1)
    ada = await _data_toko_kemarin(ctx)
    out = []
    for a in await _toko(ctx):
        if bool(a.get("_impor")) != impor:
            continue
        sumber = ada.get(a["id"]) or []
        if (impor and "orders_auto" in sumber) or (not impor and sumber):
            continue
        out.append(_tunggu(ctx, _nama_toko(a), jam_wib(ctx.tanggal, "00:00"), a.get("pic_user_id"), a.get("pic_user_name"),
                           keterangan=(f"pesanan {tgl_pendek(kemarin.isoformat())} belum diimpor" if impor
                                       else f"rekap {tgl_pendek(kemarin.isoformat())} belum diisi"),
                           batas=jam_wib(ctx.tanggal, "10:00")))
    return out


async def _k_impor_pesanan(ctx: Ktx) -> list:
    from core.marketing_input_mode import IMPORT_TYPES
    rows = await _cari(ctx.db, "marketing_data_import_sessions", {
        "status": {"$in": ["committed", "rolled_back"]}, **_rentang("committed_at", ctx.a, ctx.b)}, {
        "account_name": 1, "committed_at": 1, "committed_by": 1, "created_by_id": 1, "created_by": 1,
        "committed_count": 1, "updated_count": 1, "source_type": 1, "target_collection": 1, "status": 1})
    return [_aksi(ctx, r.get("committed_at"), r.get("created_by_id"), r.get("committed_by"), r.get("created_by"),
                  nomor=r.get("account_name") or "", jumlah=_num(r.get("committed_count")),
                  keterangan=(f"{int(_num(r.get('committed_count')))} baris baru, {int(_num(r.get('updated_count')))} diperbarui"
                              + (" · kemudian dibatalkan" if r.get("status") == "rolled_back" else "")))
            for r in rows
            if r.get("target_collection") == "marketing_orders" or r.get("source_type") in IMPORT_TYPES]


async def _t_impor_pesanan(ctx: Ktx) -> list:
    return await _t_toko(ctx, impor=True)


async def _k_rekap_harian(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "marketing_sales_data", _rentang("created_at", ctx.a, ctx.b), {
        "account_name": 1, "date": 1, "created_at": 1, "created_by": 1, "rollup_by": 1, "source": 1})
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("rollup_by"), nomor=r.get("account_name") or "",
                  keterangan=f"penjualan {tgl_pendek(r.get('date'))}"
                             + (" · dari impor pesanan" if r.get("source") == "orders_auto" else ""))
            for r in rows]


async def _t_rekap_harian(ctx: Ktx) -> list:
    return await _t_toko(ctx, impor=False)


async def _k_biaya_iklan(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "marketing_spend_entries", {"category": "ads", **_rentang("created_at", ctx.a, ctx.b)}, {
        "account_id": 1, "amount": 1, "spend_date": 1, "created_at": 1, "created_by": 1})
    toko = {a["id"]: _nama_toko(a) for a in await _toko(ctx)}
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), nomor=toko.get(r.get("account_id"), ""),
                  jumlah=_num(r.get("amount")), keterangan=f"iklan {tgl_pendek(r.get('spend_date'))}")
            for r in rows]


async def _c_biaya_iklan(ctx: Ktx, kerja: list, tunggu: list) -> list:
    if kerja or not await _toko(ctx):
        return []
    total = await ctx.db.marketing_spend_entries.count_documents({"category": "ads"})
    return [Catatan(nada="warning", pesan="Belum ada biaya iklan yang dicatat hari ini"
                    + (" (dan belum pernah sama sekali)" if not total else "")
                    + ". Tanpa biaya iklan, ROAS dan marjin toko tidak bisa dihitung.")]


async def _k_kesehatan_akun(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "marketing_account_health", {"source": "manual", **_rentang("created_at", ctx.a, ctx.b)}, {
        "account_name": 1, "created_at": 1, "created_by": 1, "created_by_name": 1, "status": 1})
    label = {"healthy": "sehat", "warning": "perlu perhatian", "critical": "kritis"}
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"), nomor=r.get("account_name") or "",
                  keterangan=f"status {label.get(r.get('status'), r.get('status') or '-')}")
            for r in rows]


async def _k_ulasan(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "marketing_reviews", _rentang_salah_satu(("created_at", "response_date"), ctx.a, ctx.b), {
        "account_name": 1, "rating": 1, "created_at": 1, "created_by": 1, "response_date": 1, "status": 1})
    out = []
    for r in rows:
        if _dalam(r.get("created_at"), ctx):
            out.append(_aksi(ctx, r.get("created_at"), r.get("created_by"), nomor=r.get("account_name") or "",
                             keterangan=f"ulasan bintang {r.get('rating') or '-'}"
                                        + (" · sudah ditanggapi" if r.get("status") == "reviewed" else "")))
        elif _dalam(r.get("response_date"), ctx):
            out.append(_aksi(ctx, r.get("response_date"), r.get("created_by"), nomor=r.get("account_name") or "",
                             keterangan=f"tanggapan ulasan bintang {r.get('rating') or '-'}"))
    return out


async def _t_ulasan(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "marketing_reviews", {"status": "pending"}, {
        "account_name": 1, "account_id": 1, "rating": 1, "created_at": 1, "created_by": 1})
    pic = {a["id"]: a for a in await _toko(ctx)}
    return [_tunggu(ctx, r.get("account_name"), r.get("created_at"), (pic.get(r.get("account_id")) or {}).get("pic_user_id"),
                    r.get("created_by"), keterangan=f"ulasan bintang {r.get('rating') or '-'} belum ditanggapi")
            for r in rows]


async def _k_retur_komplain(ctx: Ktx) -> list:
    toko = {a["id"]: _nama_toko(a) for a in await _toko(ctx)}
    ret = await _cari(ctx.db, "marketing_returns", _rentang("created_at", ctx.a, ctx.b), {
        "order_id": 1, "account_id": 1, "created_at": 1, "created_by": 1, "qty": 1})
    kom = await _cari(ctx.db, "marketing_complaints", _rentang("created_at", ctx.a, ctx.b), {
        "complaint_number": 1, "account_id": 1, "created_at": 1, "created_by": 1})
    return ([_aksi(ctx, r.get("created_at"), r.get("created_by"), nomor=r.get("order_id") or "",
                   keterangan=" · ".join(x for x in ("retur", toko.get(r.get("account_id"), "")) if x)) for r in ret]
            + [_aksi(ctx, r.get("created_at"), r.get("created_by"), nomor=r.get("complaint_number") or "",
                     keterangan=" · ".join(x for x in ("komplain", toko.get(r.get("account_id"), "")) if x)) for r in kom])


async def _t_retur_komplain(ctx: Ktx) -> list:
    ret = await _cari(ctx.db, "marketing_returns", {"status": "pending"}, {"order_id": 1, "created_at": 1, "created_by": 1})
    return [_tunggu(ctx, r.get("order_id") or "Retur", r.get("created_at"), r.get("created_by"),
                    keterangan="retur belum diputuskan") for r in ret]


# ── C. R&D ────────────────────────────────────────────────────────────────────────────────────────────────
async def _k_style(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "dewi_rnd_styles", _rentang("created_at", ctx.a, ctx.b), {
        "style_code": 1, "style_name": 1, "created_at": 1, "created_by": 1, "created_by_name": 1})
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"), nomor=r.get("style_code") or "",
                  keterangan=r.get("style_name") or "") for r in rows]


async def _k_revisi(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "dewi_rnd_revisions", _rentang("created_at", ctx.a, ctx.b), {
        "style_code": 1, "revision_name": 1, "changes_summary": 1, "created_at": 1, "created_by": 1, "created_by_name": 1})
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"), nomor=r.get("style_code") or "",
                  keterangan=(r.get("revision_name") or r.get("changes_summary") or "")[:80]) for r in rows]


async def _k_tech_pack(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "dewi_rnd_tech_packs", _rentang_salah_satu(("created_at", "approved_at"), ctx.a, ctx.b), {
        "style_code": 1, "title": 1, "version": 1, "created_at": 1, "created_by": 1, "created_by_name": 1,
        "approved_at": 1, "approved_by": 1})
    out = []
    for r in rows:
        if _dalam(r.get("created_at"), ctx):
            out.append(_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"),
                             nomor=r.get("style_code") or "", keterangan=f"dibuat {r.get('version') or ''}".strip()))
        if _dalam(r.get("approved_at"), ctx):
            out.append(_aksi(ctx, r.get("approved_at"), r.get("approved_by"), nomor=r.get("style_code") or "",
                             keterangan="disetujui"))
    return out


async def _k_warna(ctx: Ktx) -> list:
    return _dari_log(ctx, await _log(ctx, "rahaza.color", ("create",)))


async def _k_varian(ctx: Ktx) -> list:
    out = _dari_log(ctx, await _log(ctx, "rahaza.variant", ("create",)))
    gen = await _log(ctx, "rahaza.model", ("generate_variants",))
    model_ids = list({str(r.get("details") or "") for r in gen if r.get("details")})
    if model_ids:
        models = {m["id"]: m for m in await _cari(ctx.db, "rahaza_models", {"id": {"$in": model_ids}},
                                                   {"id": 1, "code": 1, "name": 1})}
        sku = {}
        for v in await _cari(ctx.db, "rahaza_model_variants", {"model_id": {"$in": model_ids},
                                                               **_rentang("created_at", ctx.a, ctx.b)}, {"model_id": 1}):
            sku[v.get("model_id")] = sku.get(v.get("model_id"), 0) + 1
        lihat = set()
        for r in gen:
            mid = str(r.get("details") or "")
            if mid in lihat:
                continue
            lihat.add(mid)
            m = models.get(mid) or {}
            uid, nama = pelaku(ctx, r.get("user_id"), r.get("user_name"))
            out.append(Aksi(waktu=ts(r.get("timestamp")), user_id=uid, nama=nama, nomor=m.get("code") or "",
                            jumlah=sku.get(mid) or 1, keterangan=f"{sku.get(mid) or 0} SKU dibuat sekaligus"))
    return out


async def _k_bom(ctx: Ktx) -> list:
    rows = await _log(ctx, "rahaza.bom", ("create", "update", "copy", "activate_version"))
    ids = list({str(r.get("details") or "") for r in rows if _UUID.match(str(r.get("details") or ""))})
    nama = {}
    if ids:
        boms = await _cari(ctx.db, "rahaza_boms", {"id": {"$in": ids}}, {"id": 1, "model_id": 1})
        models = {m["id"]: m.get("code") or m.get("name") or "" for m in await _cari(
            ctx.db, "rahaza_models", {"id": {"$in": list({b.get("model_id") for b in boms if b.get("model_id")})}},
            {"id": 1, "code": 1, "name": 1})}
        nama = {b["id"]: models.get(b.get("model_id"), "") for b in boms}
    return _dari_log(ctx, rows, unik=True, nomor=lambda r: nama.get(str(r.get("details") or ""), ""))


_KATA_UBAH = {"create": "ditambah", "update": "diubah", "delete": "dihapus", "deactivate": "dinonaktifkan",
              "rebase_uom": "satuan diubah", "assign_from_master": "diisi dari master produk"}


def _k_log_unik(modul: str, aksi: tuple, *, koleksi: str | None = None, f_nomor: str = "code"):
    """Langkah dari log aktivitas: satu dokumen sekali per orang per hari; nomor dicari di koleksi bila isinya id."""
    async def f(ctx: Ktx) -> list:
        rows = await _log(ctx, modul, aksi)
        nomor = {}
        ids = list({str(r.get("details") or "") for r in rows if _UUID.match(str(r.get("details") or ""))})
        if koleksi and ids:
            nomor = {d["id"]: d.get(f_nomor) or d.get("name") or "" for d in await _cari(
                ctx.db, koleksi, {"id": {"$in": ids}}, {"id": 1, f_nomor: 1, "name": 1})}
        out, lihat = [], set()
        for r in rows:
            det = str(r.get("details") or "")
            k = (r.get("user_id"), det, r.get("action"))
            if k in lihat:
                continue
            lihat.add(k)
            uid, nama = pelaku(ctx, r.get("user_id"), r.get("user_name"))
            no = nomor.get(det) or (det.split(" ")[0] if _layak_tampil(det) and len(det) <= 40 else "")
            out.append(Aksi(waktu=ts(r.get("timestamp")), user_id=uid, nama=nama, nomor=no,
                            keterangan=_KATA_UBAH.get(r.get("action"), "")))
        return out
    return f


_k_ubah_varian = _k_log_unik("rahaza.variant", ("update", "deactivate", "delete"), koleksi="rahaza_model_variants",
                             f_nomor="sku")


# ── H. Perubahan data master ──────────────────────────────────────────────────────────────────────────────
_k_master_bahan = _k_log_unik("rahaza.material", ("create", "update", "delete", "rebase_uom", "deactivate"),
                              koleksi="rahaza_materials")
_k_master_pemasok = _k_log_unik("rahaza_suppliers", ("create", "update", "delete"), koleksi="rahaza_suppliers")
_k_data_karyawan = _k_log_unik("rahaza.employee", ("create", "update", "deactivate", "delete"),
                               koleksi="rahaza_employees", f_nomor="employee_code")
_k_katalog_toko = _k_log_unik("marketing_catalog_items", ("assign_from_master", "create", "update", "delete"))


async def _k_peran_akses(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "rahaza_audit_logs", {"entity_type": {"$in": ["role", "user"]},
                                                     **_rentang("timestamp", ctx.a, ctx.b)},
                       {"entity_type": 1, "action": 1, "user_id": 1, "user_name": 1, "timestamp": 1, "after": 1,
                        "before": 1})
    out = []
    for r in rows:
        uid, nama = pelaku(ctx, r.get("user_id"), r.get("user_name"))
        doc = r.get("after") or r.get("before") or {}
        label = (doc.get("name") or doc.get("description") or "") if isinstance(doc, dict) else ""
        peran = r.get("entity_type") == "role"
        out.append(Aksi(waktu=ts(r.get("timestamp")), user_id=uid, nama=nama,
                        nomor=label_peran(label) if peran and label else str(label or ""),
                        keterangan=f"{'peran' if peran else 'akun pengguna'} "
                                   f"{_KATA_UBAH.get(r.get('action'), r.get('action') or '')}".strip()))
    return out


# ── D. Aksesoris & opname (bersama) ───────────────────────────────────────────────────────────────────────
async def _permintaan_aks(ctx: Ktx, f_at: str) -> list:
    return await _cari(ctx.db, "dewi_accessory_requests", _rentang(f_at, ctx.a, ctx.b), {
        "request_code": 1, "request_type": 1, "divisi": 1, "status": 1, "submitted_at": 1, "requester_id": 1,
        "created_by_name": 1, "allocated_at": 1, "allocated_by": 1, "delivered_at": 1, "delivered_by": 1, "po_number": 1})


_JENIS_AKS = {"internal_issuance": "pemakaian internal", "rnd_sample": "sampel R&D", "vendor_additional": "tambahan CMT"}


def _ket_aks(r: dict) -> str:
    return " · ".join(x for x in (_JENIS_AKS.get(r.get("request_type") or "", ""), r.get("divisi"),
                                  f"PO {r['po_number']}" if r.get("po_number") else "") if x)


async def _k_ajukan_aks(ctx: Ktx) -> list:
    return [_aksi(ctx, r.get("submitted_at"), r.get("requester_id"), r.get("created_by_name"),
                  nomor=r.get("request_code") or "", keterangan=_ket_aks(r)) for r in await _permintaan_aks(ctx, "submitted_at")]


async def _k_siapkan_aks(ctx: Ktx) -> list:
    return [_aksi(ctx, r.get("allocated_at"), r.get("allocated_by"), nomor=r.get("request_code") or "",
                  keterangan=_ket_aks(r)) for r in await _permintaan_aks(ctx, "allocated_at")]


async def _k_serahkan_aks(ctx: Ktx) -> list:
    return [_aksi(ctx, r.get("delivered_at"), r.get("delivered_by"), nomor=r.get("request_code") or "",
                  keterangan=_ket_aks(r)) for r in await _permintaan_aks(ctx, "delivered_at")]


async def _t_aks(ctx: Ktx, status: str, f_sejak: str) -> list:
    rows = await _cari(ctx.db, "dewi_accessory_requests", {"status": status}, {
        "request_code": 1, "request_type": 1, "divisi": 1, "submitted_at": 1, "allocated_at": 1, "created_at": 1,
        "requester_id": 1, "created_by_name": 1, "po_number": 1})
    return [_tunggu(ctx, r.get("request_code"), _pertama(r.get(f_sejak), r.get("created_at")), r.get("requester_id"),
                    r.get("created_by_name"), keterangan=_ket_aks(r)) for r in rows]


def _opname_jenis(r: dict, jenis: str) -> bool:
    return jenis in (r.get("kinds") or []) or r.get("source") == jenis


_OP_PROJ = {"session_no": 1, "status": 1, "kinds": 1, "source": 1, "mode": 1, "created_at": 1, "created_by": 1,
            "created_by_name": 1, "submitted_at": 1, "submitted_by": 1, "submitted_by_name": 1, "approved_at": 1,
            "approved_by": 1, "approved_by_name": 1, "cancelled_at": 1, "cancelled_by": 1, "scope_label": 1}


async def _opname_hari_ini(ctx: Ktx) -> list:
    if "opname" not in ctx.cache:
        ctx.cache["opname"] = await _cari(ctx.db, OPNAME, _rentang_salah_satu(
            ("created_at", "submitted_at", "approved_at", "cancelled_at"), ctx.a, ctx.b), _OP_PROJ)
    return ctx.cache["opname"]


def _opname(jenis: str):
    async def hitung(ctx: Ktx) -> list:
        out = []
        for r in await _opname_hari_ini(ctx):
            if not _opname_jenis(r, jenis):
                continue
            if _dalam(r.get("created_at"), ctx):
                out.append(_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"),
                                 nomor=r.get("session_no") or "", keterangan="sesi dibuka"))
            if _dalam(r.get("submitted_at"), ctx):
                out.append(_aksi(ctx, r.get("submitted_at"), r.get("submitted_by"), r.get("submitted_by_name"),
                                 nomor=r.get("session_no") or "", keterangan="hasil hitung diajukan"))
        return out

    async def setujui(ctx: Ktx) -> list:
        return [_aksi(ctx, r.get("approved_at"), r.get("approved_by"), r.get("approved_by_name"),
                      nomor=r.get("session_no") or "", keterangan=r.get("scope_label") or "")
                for r in await _opname_hari_ini(ctx)
                if _opname_jenis(r, jenis) and r.get("status") == "approved" and _dalam(r.get("approved_at"), ctx)]

    async def t_hitung(ctx: Ktx) -> list:
        rows = await _cari(ctx.db, OPNAME, {"status": "counting"}, _OP_PROJ)
        return [_tunggu(ctx, r.get("session_no"), r.get("created_at"), r.get("created_by"), r.get("created_by_name"),
                        keterangan=r.get("scope_label") or "") for r in rows if _opname_jenis(r, jenis)]

    async def t_setujui(ctx: Ktx) -> list:
        rows = await _cari(ctx.db, OPNAME, {"status": {"$in": ["submitted", "approving"]}}, _OP_PROJ)
        return [_tunggu(ctx, r.get("session_no"), r.get("submitted_at"), r.get("submitted_by"), r.get("submitted_by_name"),
                        keterangan=r.get("scope_label") or "") for r in rows if _opname_jenis(r, jenis)]

    async def c_hitung(ctx: Ktx, kerja: list, tunggu: list) -> list:
        out = []
        for r in await _opname_hari_ini(ctx):
            if _opname_jenis(r, jenis) and r.get("status") == "cancelled" and _dalam(r.get("cancelled_at"), ctx):
                _, oleh = pelaku(ctx, r.get("cancelled_by"))
                out.append(Catatan(nomor=r.get("session_no") or "", nada="warning",
                                   pesan=f"Sesi opname dibatalkan{' oleh ' + oleh if oleh else ''}."))
        return out

    async def c_setujui(ctx: Ktx, kerja: list, tunggu: list) -> list:
        out = []
        for r in await _opname_hari_ini(ctx):
            if not (_opname_jenis(r, jenis) and r.get("status") == "approved" and _dalam(r.get("approved_at"), ctx)):
                continue
            hit, _ = pelaku(ctx, r.get("submitted_by"), r.get("submitted_by_name"))
            stj, nama = pelaku(ctx, r.get("approved_by"), r.get("approved_by_name"))
            if hit and stj and hit == stj and r.get("mode") != "opening":
                out.append(Catatan(nomor=r.get("session_no") or "", nada="warning",
                                   pesan=f"Dihitung dan disetujui oleh orang yang sama ({nama})."))
        return out

    return hitung, setujui, t_hitung, t_setujui, c_hitung, c_setujui


_OP_AKS = _opname("aksesoris")
_OP_FG = _opname("fg")


# ── E. Gudang barang jadi: retur fisik ────────────────────────────────────────────────────────────────────
async def _retur_gudang(ctx: Ktx, f_at: str, f_by: str, ket: str = "") -> list:
    rows = await _cari(ctx.db, "wh_returns", _rentang(f_at, ctx.a, ctx.b), {
        "return_code": 1, "order_number": 1, "qty": 1, "sku_code": 1, f_at: 1, f_by: 1, "status": 1})
    return [_aksi(ctx, r.get(f_at), r.get(f_by), nomor=r.get("return_code") or "", jumlah=_num(r.get("qty")) or 1,
                  keterangan=" · ".join(x for x in (r.get("sku_code"), ket) if x)) for r in rows]


async def _k_retur_terima(ctx: Ktx) -> list:
    return await _retur_gudang(ctx, "received_at", "received_by")


async def _k_retur_periksa(ctx: Ktx) -> list:
    return await _retur_gudang(ctx, "inspected_at", "inspected_by")


async def _k_retur_selesai(ctx: Ktx) -> list:
    return await _retur_gudang(ctx, "resolved_at", "resolved_by")


def _t_retur(status: str, f_sejak: str):
    async def f(ctx: Ktx) -> list:
        rows = await _cari(ctx.db, "wh_returns", {"status": status}, {
            "return_code": 1, "order_number": 1, "sku_code": 1, "created_at": 1, "created_by": 1, f_sejak: 1})
        return [_tunggu(ctx, r.get("return_code"), _pertama(r.get(f_sejak), r.get("created_at")), r.get("created_by"),
                        keterangan=" · ".join(x for x in (r.get("sku_code"), f"pesanan {r['order_number']}"
                                                          if r.get("order_number") else "") if x)) for r in rows]
    return f


# ── F. SDM ────────────────────────────────────────────────────────────────────────────────────────────────
async def _k_absensi(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "rahaza_attendance_events", {"date": ctx.tanggal.isoformat(), "source": {"$ne": "leave"}}, {
        "created_at": 1, "created_by": 1, "created_by_name": 1, "updated_by": 1, "status": 1, "source": 1})
    per: dict = {}
    for r in rows:
        a = _aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"), r.get("updated_by"))
        k = a.user_id or a.nama or "-"
        if k in per:
            per[k].jumlah += 1
        else:
            a.keterangan = "absen karyawan"
            per[k] = a
    return list(per.values())


async def _c_absensi(ctx: Ktx, kerja: list, tunggu: list) -> list:
    if kerja or not ctx.kal.kerja(ctx.tanggal):
        return []
    if ctx.tanggal == to_wib(ctx.kini).date() and to_wib(ctx.kini).hour < 10:
        return []
    return [Catatan(nada="warning", pesan="Belum ada absensi karyawan yang masuk sistem untuk hari kerja ini.")]


async def _k_ajukan_cuti(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "rahaza_leave_requests", _rentang_salah_satu(("submitted_at", "created_at"), ctx.a, ctx.b), {
        "request_type": 1, "leave_kind": 1, "from_date": 1, "duration_working_days": 1, "submitted_at": 1,
        "created_at": 1, "created_by": 1, "created_by_name": 1, "submitted_by": 1, "status": 1})
    return [_aksi(ctx, _pertama(r.get("submitted_at"), r.get("created_at")), r.get("submitted_by"), r.get("created_by"),
                  r.get("created_by_name"), nomor=r.get("leave_kind") or r.get("request_type") or "cuti",
                  jumlah=_num(r.get("duration_working_days")) or 1, keterangan=f"mulai {tgl_pendek(r.get('from_date'))}")
            for r in rows if _dalam(_pertama(r.get("submitted_at"), r.get("created_at")), ctx)]


async def _k_putus_cuti(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "rahaza_leave_requests", _rentang_salah_satu(("approved_at", "rejected_at"), ctx.a, ctx.b), {
        "leave_kind": 1, "request_type": 1, "approved_at": 1, "approved_by": 1, "approved_by_name": 1, "rejected_at": 1,
        "rejected_by": 1, "status": 1, "created_by_name": 1})
    out = []
    for r in rows:
        tolak = _dalam(r.get("rejected_at"), ctx)
        out.append(_aksi(ctx, r.get("rejected_at") if tolak else r.get("approved_at"),
                         r.get("rejected_by") if tolak else r.get("approved_by"), r.get("approved_by_name"),
                         nomor=r.get("leave_kind") or r.get("request_type") or "cuti",
                         keterangan=f"{'ditolak' if tolak else 'disetujui'} · {r.get('created_by_name') or ''}".strip(" ·")))
    return out


async def _t_putus_cuti(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "rahaza_leave_requests", {"status": {"$in": ["pending_approval", "submitted", "pending"]}}, {
        "leave_kind": 1, "request_type": 1, "submitted_at": 1, "created_at": 1, "created_by": 1, "created_by_name": 1,
        "from_date": 1})
    return [_tunggu(ctx, r.get("leave_kind") or r.get("request_type") or "cuti", _pertama(r.get("submitted_at"), r.get("created_at")),
                    keterangan=f"{r.get('created_by_name') or ''} · mulai {tgl_pendek(r.get('from_date'))}".strip(" ·"))
            for r in rows]


# ── G. Keuangan ───────────────────────────────────────────────────────────────────────────────────────────
async def _k_kas(ctx: Ktx) -> list:
    mv = await _cari(ctx.db, "rahaza_cash_movements", _rentang_salah_satu(("timestamp", "created_at"), ctx.a, ctx.b), {
        "account_name": 1, "amount": 1, "direction": 1, "category": 1, "timestamp": 1, "created_at": 1, "created_by": 1,
        "created_by_name": 1, "ref_label": 1})
    ex = await _cari(ctx.db, "rahaza_expenses", _rentang("created_at", ctx.a, ctx.b), {
        "amount": 1, "created_at": 1, "created_by": 1, "created_by_name": 1, "description": 1, "expense_number": 1})
    return ([_aksi(ctx, _pertama(r.get("timestamp"), r.get("created_at")), r.get("created_by"), r.get("created_by_name"),
                   nomor=r.get("ref_label") or r.get("account_name") or "", jumlah=_num(r.get("amount")),
                   keterangan=("kas masuk" if r.get("direction") == "in" else "kas keluar")) for r in mv]
            + [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"),
                     nomor=r.get("expense_number") or "", jumlah=_num(r.get("amount")),
                     keterangan=(r.get("description") or "pengeluaran")[:60]) for r in ex])


async def _k_bayar_tagihan(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "rahaza_ap_payments", _rentang("created_at", ctx.a, ctx.b), {
        "invoice_number": 1, "amount": 1, "created_at": 1, "created_by": 1, "created_by_name": 1, "supplier_name": 1})
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"), nomor=r.get("invoice_number") or "",
                  jumlah=_num(r.get("amount")), keterangan=r.get("supplier_name") or "") for r in rows]


async def _k_jurnal(ctx: Ktx) -> list:
    rows = await _cari(ctx.db, "rahaza_journal_entries", {
        "source_module": {"$in": ["manual", "manual_journal", "general", "adjustment"]},
        **_rentang("created_at", ctx.a, ctx.b)}, {
        "je_number": 1, "memo": 1, "total_debit": 1, "created_at": 1, "created_by": 1, "created_by_name": 1})
    return [_aksi(ctx, r.get("created_at"), r.get("created_by"), r.get("created_by_name"), nomor=r.get("je_number") or "",
                  jumlah=_num(r.get("total_debit")), keterangan=(r.get("memo") or "")[:60]) for r in rows]


# ── KATALOG LANGKAH ──────────────────────────────────────────────────────────────────────────────────────
L = Langkah
LANGKAH: list[Langkah] = [
    # A. Produksi — urutan contoh owner: order cutting → … → scan keluar → tutup hari
    L("order_cutting", "produksi", 1, "Buat order cutting", "Marketing (PIC toko)", "order", _k_order_cutting,
      kewajiban=("po_perintah_potong",), link_module="cutting-orders", jumlah_satuan="pcs rencana"),
    L("mulai_cutting", "produksi", 2, "Mulai cutting", "Cutting", "order", _k_mulai_cutting, _t_mulai_cutting,
      link_module="cutting-orders"),
    L("catat_progres", "produksi", 3, "Catat hasil potong", "Cutting", "catatan", _k_catat_progres,
      link_module="cutting-orders", jumlah_satuan="pcs"),
    L("selesai_cutting", "produksi", 4, "Selesaikan cutting", "Cutting", "order", _k_selesai_cutting, _t_selesai_cutting,
      _c_selesai_cutting, kewajiban=("po_selesai_potong",), link_module="cutting-orders", batas_hari_kerja=2,
      jumlah_satuan="pcs jadi"),
    L("buat_po", "produksi", 5, "Buat PO produksi", "Admin produksi", "PO", _k_buat_po, link_module="prod-pos-internal"),
    L("konfirmasi_po", "produksi", 6, "Konfirmasi PO", "Admin produksi", "PO", _k_konfirmasi_po, _t_konfirmasi_po,
      _c_konfirmasi_po, kewajiban=("po_konfirmasi",), link_module="prod-pos-internal"),
    L("kirim_cmt", "produksi", 7, "Kirim ke CMT", "Admin produksi", "kiriman", _k_kirim_cmt, _t_kirim_cmt,
      kewajiban=("po_kirim_cmt",), link_module="prod-shipments-vendor"),
    L("terima_qc", "produksi", 8, "Terima & QC hasil CMT", "QC / gudang", "penerimaan", _k_terima_qc, _t_terima_qc,
      kewajiban=("po_terima_qc",), link_module="da-cmt-receive", jumlah_satuan="pcs"),
    L("stok_fg", "produksi", 9, "Barang jadi masuk stok", "QC / gudang", "penerimaan", _k_stok_fg,
      link_module="da-cmt-receive", jumlah_satuan="pcs"),
    L("scan_keluar", "produksi", 10, "Scan barang keluar", "Packing", "baris", _k_scan_keluar, catatan=_c_scan_keluar,
      link_module="wh-scan-out", jumlah_satuan="pcs"),
    L("tutup_hari", "produksi", 11, "Tutup lembar scan keluar", "Packing", "lembar", _k_tutup_hari, _t_tutup_hari,
      _c_tutup_hari, kewajiban=("scan_out_tutup",), link_module="wh-scan-out", batas_teks="hari itu pukul 23.55"),
    # B. Pesanan marketplace (per toko)
    L("impor_pesanan", "marketplace", 1, "Impor pesanan marketplace", "Marketing (PIC toko)", "impor", _k_impor_pesanan,
      _t_impor_pesanan, kewajiban=("penjualan_toko",), link_module="marketing-import", jumlah_satuan="baris pesanan",
      batas_teks="data kemarin, pukul 10.00"),
    L("rekap_harian", "marketplace", 2, "Rekap penjualan harian", "Marketing (PIC toko)", "rekap", _k_rekap_harian,
      _t_rekap_harian, kewajiban=("penjualan_toko",), link_module="marketing-sales", batas_teks="data kemarin, pukul 10.00"),
    L("biaya_iklan", "marketplace", 3, "Catat biaya iklan", "Marketing (PIC toko)", "catatan", _k_biaya_iklan,
      catatan=_c_biaya_iklan, link_module="marketing-ads", jumlah_satuan="rupiah"),
    L("kesehatan_akun", "marketplace", 4, "Catat kesehatan akun toko", "Marketing (PIC toko)", "catatan",
      _k_kesehatan_akun, link_module="marketing-health"),
    L("ulasan", "marketplace", 5, "Catat & tanggapi ulasan", "Marketing (PIC toko)", "ulasan", _k_ulasan, _t_ulasan,
      link_module="marketing-reviews", batas_hari_kerja=2),
    L("retur_komplain", "marketplace", 6, "Catat retur & komplain", "Marketing (PIC toko)", "catatan", _k_retur_komplain,
      _t_retur_komplain, link_module="marketing-returns", batas_hari_kerja=2),
    L("katalog_toko", "marketplace", 7, "Isi katalog toko", "Marketing (PIC toko)", "kali", _k_katalog_toko,
      link_module="marketing-catalog"),
    # C. R&D
    L("style_baru", "rnd", 1, "Buat style baru", "R&D", "style", _k_style, link_module="rnd-styles"),
    L("revisi_desain", "rnd", 2, "Revisi desain", "R&D", "revisi", _k_revisi, link_module="rnd-styles"),
    L("tech_pack", "rnd", 3, "Susun & setujui tech pack", "R&D", "tech pack", _k_tech_pack, link_module="rnd-techpack"),
    L("warna", "rnd", 4, "Tambah warna", "R&D", "warna", _k_warna, link_module="rnd-colors"),
    L("varian", "rnd", 5, "Buat model & varian (SKU)", "R&D", "kali", _k_varian, link_module="rnd-sku-variants",
      jumlah_satuan="SKU"),
    L("ubah_varian", "rnd", 6, "Ubah atau nonaktifkan varian", "R&D", "varian", _k_ubah_varian,
      link_module="rnd-sku-variants"),
    L("bom", "rnd", 7, "Ubah BOM", "R&D", "BOM", _k_bom, link_module="rnd-bom"),
    # D. Aksesoris
    L("aks_ajukan", "aksesoris", 1, "Ajukan permintaan aksesoris", "Semua bagian", "permintaan", _k_ajukan_aks,
      link_module="accessories-internal-request"),
    L("aks_siapkan", "aksesoris", 2, "Siapkan aksesoris", "Admin aksesoris", "permintaan", _k_siapkan_aks,
      lambda ctx: _t_aks(ctx, "submitted", "submitted_at"), link_module="accessories-inbox"),
    L("aks_serahkan", "aksesoris", 3, "Serahkan aksesoris", "Admin aksesoris", "permintaan", _k_serahkan_aks,
      lambda ctx: _t_aks(ctx, "allocated", "allocated_at"), link_module="accessories-inbox"),
    L("aks_opname_hitung", "aksesoris", 4, "Hitung opname aksesoris", "Admin aksesoris", "langkah", _OP_AKS[0], _OP_AKS[2],
      _OP_AKS[4], kewajiban=("opname_hitung",), link_module="accessories-opname"),
    L("aks_opname_setujui", "aksesoris", 5, "Setujui opname aksesoris", "Penyetuju opname", "sesi", _OP_AKS[1],
      _OP_AKS[3], _OP_AKS[5], kewajiban=("opname_setujui",), link_module="accessories-opname"),
    # E. Gudang barang jadi: retur & opname
    L("retur_terima", "gudang", 1, "Terima retur fisik", "Gudang barang jadi", "retur", _k_retur_terima,
      _t_retur("Pending", "created_at"), link_module="wh-returns", jumlah_satuan="pcs"),
    L("retur_periksa", "gudang", 2, "Periksa barang retur", "Gudang barang jadi", "retur", _k_retur_periksa,
      _t_retur("Received", "received_at"), link_module="wh-returns", jumlah_satuan="pcs"),
    L("retur_selesai", "gudang", 3, "Selesaikan retur", "Gudang barang jadi", "retur", _k_retur_selesai,
      _t_retur("Inspected", "inspected_at"), kewajiban=("putuskan_retur",), link_module="wh-returns",
      jumlah_satuan="pcs"),
    L("fg_opname_hitung", "gudang", 4, "Hitung opname barang jadi", "Gudang barang jadi", "langkah", _OP_FG[0],
      _OP_FG[2], _OP_FG[4], kewajiban=("opname_hitung",), link_module="wms-stock-hub"),
    L("fg_opname_setujui", "gudang", 5, "Setujui opname barang jadi", "Penyetuju opname", "sesi", _OP_FG[1], _OP_FG[3],
      _OP_FG[5], kewajiban=("opname_setujui",), link_module="wms-stock-hub"),
    # F. SDM
    L("absensi", "sdm", 1, "Masukkan absensi harian", "SDM", "orang", _k_absensi, catatan=_c_absensi,
      kewajiban=("absensi_harian",), link_module="hr-attendance", jumlah_satuan="absen"),
    L("ajukan_cuti", "sdm", 2, "Ajukan cuti / izin", "Semua karyawan", "pengajuan", _k_ajukan_cuti,
      link_module="hr-leave", jumlah_satuan="hari kerja"),
    L("putus_cuti", "sdm", 3, "Putuskan cuti / izin", "Atasan & SDM", "keputusan", _k_putus_cuti, _t_putus_cuti,
      kewajiban=("setuju_sdm",), link_module="hr-inbox"),
    L("data_karyawan", "sdm", 4, "Perbarui data karyawan", "SDM", "karyawan", _k_data_karyawan,
      link_module="hr-employees"),
    # G. Keuangan
    L("kas", "keuangan", 1, "Catat kas & pengeluaran", "Keuangan", "catatan", _k_kas, kewajiban=("kas_harian",),
      link_module="fin-cash", jumlah_satuan="rupiah"),
    L("bayar_tagihan", "keuangan", 2, "Bayar tagihan pemasok", "Keuangan", "pembayaran", _k_bayar_tagihan,
      kewajiban=("bayar_tagihan",), link_module="fin-ap-hub", jumlah_satuan="rupiah"),
    L("jurnal_umum", "keuangan", 3, "Catat jurnal umum", "Akuntansi", "jurnal", _k_jurnal, link_module="fin-journal-hub",
      jumlah_satuan="rupiah"),
    # H. Perubahan data master (siapa mengubah apa — mis. bagian yang tidak lazim mengubah data kain)
    L("master_bahan", "master", 1, "Ubah master bahan & aksesoris", "Gudang / R&D / pengadaan", "bahan",
      _k_master_bahan, link_module="wh-materials"),
    L("master_pemasok", "master", 2, "Ubah data pemasok", "Pengadaan", "pemasok", _k_master_pemasok,
      link_module="proc-suppliers"),
    L("peran_akses", "master", 3, "Ubah peran & akses pengguna", "Admin", "perubahan", _k_peran_akses,
      link_module="mgmt-roles"),
]
LANGKAH_BY_ID = {x.id: x for x in LANGKAH}


# ── baca ──────────────────────────────────────────────────────────────────────────────────────────────────
MAKS_RINCI = 200


async def siapkan(db, tanggal: date, kini: datetime | None = None) -> Ktx:
    from core.pantau_staf.pemindai import siapkan_konteks
    base = await siapkan_konteks(db, kini)
    a = jam_wib(tanggal, "00:00")
    return Ktx(db=base.db, kini=base.kini, sejak=base.sejak, kal=base.kal, users=base.users,
               nama_ke_id=base.nama_ke_id, email_ke_id=base.email_ke_id, cache={}, tanggal=tanggal, a=a,
               b=a + timedelta(days=1))


def _nama_user(ctx: Ktx, uid: str | None, cadangan: str | None = None) -> str:
    if uid and uid in ctx.users:
        return ctx.users[uid].get("name") or ctx.users[uid].get("email") or cadangan or uid
    return cadangan or "tidak tercatat"


async def _aturan_map(db) -> dict:
    from core.pantau_staf.aturan import semua
    try:
        return {r["id"]: r for r in await semua(db, pasang=False)}
    except Exception:  # noqa: BLE001
        log.debug("[alur-kerja] aturan tidak terbaca", exc_info=True)
        return {}


def _penanggung_jawab(ctx: Ktx, langkah: Langkah, aturan: dict) -> dict:
    """Penanggung jawab & batas dari aturan kewajiban yang sama (bila aktif)."""
    from core.pantau_staf.katalog import KATALOG
    for tid in langkah.kewajiban:
        r = aturan.get(tid)
        if not r or not r.get("aktif"):
            continue
        p = r.get("pemegang") or {}
        if p.get("jenis") == "akun":
            nama = [_nama_user(ctx, i) for i in p.get("akun_ids") or []]
        elif p.get("jenis") == "peran":
            nama = [f"semua akun peran {label_peran(x)}" for x in p.get("peran") or []]
        else:
            t = KATALOG.get(tid)
            nama = [(t.pemegang or {}).get("label") or "dari dokumen"] if t else []
        return {"nama": nama, "tenggat": r.get("tenggat") or {}, "batas_label": label_tenggat(r.get("tenggat") or {})}
    if langkah.tunggu is None:
        return {"nama": [], "tenggat": {}, "batas_label": ""}
    return {"nama": [], "tenggat": {}, "batas_label": langkah.batas_teks or f"{langkah.batas_hari_kerja} hari kerja"}


def _batas(ctx: Ktx, t: Tunggu, tenggat: dict, langkah: Langkah) -> Optional[datetime]:
    if t.batas:
        return t.batas
    if not t.sejak:
        return None
    tg = tenggat if (tenggat or {}).get("jenis") in ("hari_kerja", "jam") else \
        {"jenis": "hari_kerja", "nilai": langkah.batas_hari_kerja}
    return hitung_tenggat(tg, kal=ctx.kal, mulai=t.sejak)


def _pelaku_ringkas(ctx: Ktx, aksi: list) -> list:
    per: dict = {}
    for x in aksi:
        k = x.user_id or (x.nama or "")
        cur = per.setdefault(k, {"user_id": x.user_id, "nama": _nama_user(ctx, x.user_id, x.nama), "kali": 0, "jumlah": 0.0})
        cur["kali"] += 1
        cur["jumlah"] += float(x.jumlah or 0)
    return sorted(per.values(), key=lambda p: (-p["kali"], p["nama"].lower()))


async def _jalankan(ctx: Ktx, fn, *args) -> tuple[list, Optional[str]]:
    if fn is None:
        return [], None
    try:
        return list(await fn(ctx, *args)), None
    except Exception:  # noqa: BLE001 — satu langkah gagal dibaca tidak mematikan layar
        log.warning("[alur-kerja] langkah gagal dibaca", exc_info=True)
        return [], "Data langkah ini gagal dibaca."


def _bentuk_aksi(ctx: Ktx, x: Aksi) -> dict:
    return {"waktu": x.waktu, "oleh": _nama_user(ctx, x.user_id, x.nama), "user_id": x.user_id, "nomor": x.nomor,
            "jumlah": x.jumlah, "keterangan": x.keterangan, "batal": x.batal}


def _bentuk_tunggu(ctx: Ktx, t: Tunggu, batas: Optional[datetime]) -> dict:
    lewat = bool(batas and ctx.kini > batas)
    return {"nomor": t.nomor, "sejak": t.sejak, "batas": batas, "lewat_batas": lewat,
            "terlambat_hari_kerja": ctx.kal.hari_kerja_lewat(batas, ctx.kini) if lewat else 0,
            "orang": _nama_user(ctx, t.user_id, t.nama) if (t.user_id or t.nama) else None, "keterangan": t.keterangan}


async def baca_langkah(ctx: Ktx, langkah: Langkah, aturan: dict) -> dict:
    semua_kerja, g1 = await _jalankan(ctx, langkah.kerja)
    semua_kerja.sort(key=lambda x: x.waktu or ctx.a)
    kerja = [x for x in semua_kerja if not x.batal]
    batal = [x for x in semua_kerja if x.batal]
    tunggu, g2 = await _jalankan(ctx, langkah.tunggu)
    catatan, g3 = await _jalankan(ctx, langkah.catatan, kerja, tunggu)
    pj = _penanggung_jawab(ctx, langkah, aturan)
    tunggu_b = [_bentuk_tunggu(ctx, t, _batas(ctx, t, pj["tenggat"], langkah)) for t in tunggu]
    tunggu_b.sort(key=lambda t: (not t["lewat_batas"], t["sejak"] or ctx.kini))
    macet = [t for t in tunggu_b if t["lewat_batas"]]
    if macet:
        keadaan = "macet"
    elif tunggu_b:
        keadaan = "menunggu"
    elif kerja:
        keadaan = "dikerjakan"
    else:
        keadaan = "kosong"
    return {
        "id": langkah.id, "urutan": langkah.urutan, "nama": langkah.nama, "bagian": langkah.bagian,
        "satuan": langkah.satuan, "jumlah_satuan": langkah.jumlah_satuan, "link_module": langkah.link_module,
        "keadaan": keadaan, "dikerjakan": len(kerja), "jumlah": round(sum(float(x.jumlah or 0) for x in kerja), 2),
        "pelaku": _pelaku_ringkas(ctx, kerja), "dibatalkan": len(batal), "pelaku_batal": _pelaku_ringkas(ctx, batal),
        "menunggu": len(tunggu_b), "lewat_batas": len(macet),
        "terlama_sejak": min((t["sejak"] for t in tunggu_b if t["sejak"]), default=None),
        "penanggung_jawab": pj["nama"], "batas_label": pj["batas_label"],
        "catatan": [{"nomor": c.nomor, "pesan": c.pesan, "nada": c.nada} for c in catatan],
        "rincian_kerja": [_bentuk_aksi(ctx, x) for x in semua_kerja[:MAKS_RINCI]],
        "rincian_tunggu": tunggu_b[:MAKS_RINCI],
        "galat": g1 or g2 or g3,
    }


def kalimat_alur(langkah: list) -> str:
    """Satu kalimat keadaan alur untuk layar & Asisten AI."""
    macet = next((x for x in langkah if x["keadaan"] == "macet"), None)
    jalan = sum(1 for x in langkah if x["dikerjakan"])
    if macet:
        return (f"Macet di langkah {macet['urutan']} ({macet['nama']}): {macet['lewat_batas']} {macet['satuan']} "
                f"lewat batas, terlama sejak {tgl_pendek(macet['terlama_sejak'])}.")
    tunggu = next((x for x in langkah if x["keadaan"] == "menunggu"), None)
    if tunggu:
        return (f"{jalan} dari {len(langkah)} langkah dikerjakan hari itu; langkah {tunggu['urutan']} "
                f"({tunggu['nama']}) menunggu {tunggu['menunggu']} {tunggu['satuan']}, belum lewat batas.")
    if jalan:
        return f"Lancar: {jalan} dari {len(langkah)} langkah dikerjakan hari itu, tidak ada yang tertahan."
    return "Tidak ada kegiatan yang tercatat hari itu."


async def alur_kerja(db, tanggal: date, *, alur: str | None = None, kini: datetime | None = None) -> dict:
    ctx = await siapkan(db, tanggal, kini)
    aturan = await _aturan_map(db)
    hasil = []
    for kode in ALUR_URUT:
        if alur and kode != alur:
            continue
        rows = [await baca_langkah(ctx, x, aturan) for x in sorted(
            (x for x in LANGKAH if x.alur == kode), key=lambda x: x.urutan)]
        macet = next((x for x in rows if x["keadaan"] == "macet"), None)
        hasil.append({
            "alur": kode, "label": ALUR[kode][0], "urutan_ringkas": ALUR[kode][1], "langkah": rows,
            "keadaan": "macet" if macet else ("menunggu" if any(x["menunggu"] for x in rows)
                                              else ("jalan" if any(x["dikerjakan"] for x in rows) else "kosong")),
            "macet_di": {"urutan": macet["urutan"], "nama": macet["nama"]} if macet else None,
            "kalimat": kalimat_alur(rows),
            "dikerjakan": sum(1 for x in rows if x["dikerjakan"]),
            "catatan": sum(len(x["catatan"]) for x in rows),
        })
    semua = [x for g in hasil for x in g["langkah"]]
    pelaku = {p["user_id"] or p["nama"] for x in semua for p in x["pelaku"]}
    return {
        "tanggal": tanggal.isoformat(), "alur": hasil,
        "ringkasan": {
            "alur_macet": sum(1 for g in hasil if g["keadaan"] == "macet"),
            "langkah_macet": sum(1 for x in semua if x["keadaan"] == "macet"),
            "menunggu": sum(x["menunggu"] for x in semua),
            "lewat_batas": sum(x["lewat_batas"] for x in semua),
            "catatan": sum(len(x["catatan"]) for x in semua),
            "pekerjaan": sum(x["dikerjakan"] for x in semua),
            "orang": len(pelaku),
        },
    }


# ── per staf (hari yang sama, dari langkah yang sama) ───────────────────────────────────────────────────
def angka(v: float) -> str:
    """1234.5 → "1.234,5" (format Indonesia, desimal hanya bila perlu)."""
    v = float(v or 0)
    s = f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.1f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def _frasa(n: int, langkah: dict, jumlah: float) -> str:
    teks = f"{langkah['nama']} {n}×"
    js = langkah.get("jumlah_satuan")
    if js == "rupiah" and jumlah:
        teks += f" (Rp {angka(jumlah)})"
    elif js and jumlah:
        teks += f" ({angka(jumlah)} {js})"
    return teks


async def aktivitas_staf(db, tanggal: date, *, kini: datetime | None = None, data_alur: dict | None = None) -> dict:
    from core.pantau_staf import meter
    from core.pantau_staf.ringkasan import TIDAK_DIPANTAU
    kini = kini or now_utc()
    data_alur = data_alur or await alur_kerja(db, tanggal, kini=kini)
    ctx = await siapkan(db, tanggal, kini)
    staf = [u for u in ctx.users.values() if (u.get("role") or "").lower() not in TIDAK_DIPANTAU]
    per: dict = {u["id"]: {"user_id": u["id"], "nama": u.get("name") or u.get("email"), "peran": u.get("role"),
                           "pekerjaan": [], "jumlah_pekerjaan": 0} for u in staf}
    for g in data_alur["alur"]:
        for x in g["langkah"]:
            for p in x["pelaku"]:
                row = per.get(p["user_id"])
                if row is None:
                    continue
                row["pekerjaan"].append({"alur": g["label"], "langkah": x["nama"], "kali": p["kali"],
                                         "jumlah": p["jumlah"], "kalimat": _frasa(p["kali"], x, p["jumlah"]),
                                         "link_module": x["link_module"]})
                row["jumlah_pekerjaan"] += p["kali"]
            for p in x.get("pelaku_batal") or []:
                row = per.get(p["user_id"])
                if row is None:
                    continue
                row["pekerjaan"].append({"alur": g["label"], "langkah": x["nama"], "kali": p["kali"],
                                         "jumlah": p["jumlah"], "batal": True, "link_module": x["link_module"],
                                         "kalimat": f"Membatalkan {x['nama'][:1].lower()}{x['nama'][1:]} {p['kali']}×"
                                                    + (f" ({angka(p['jumlah'])} {x['jumlah_satuan']})"
                                                       if x.get("jumlah_satuan") and p["jumlah"] else "")})
                row["jumlah_pekerjaan"] += p["kali"]
    hari = tanggal.isoformat()
    akt = {r["user_id"]: r for r in await meter.aktivitas(db, list(per), hari, hari)}
    masuk: dict = {}
    for r in await _cari(db, "activity_logs", {"module": "Auth", "action": "Login", **_rentang("timestamp", ctx.a, ctx.b)},
                         {"user_id": 1}):
        masuk[r.get("user_id")] = masuk.get(r.get("user_id"), 0) + 1
    tanya: dict = {}
    for r in await _cari(db, "rahaza_ai_usage_logs", _rentang("created_at", ctx.a, ctx.b), {"user_id": 1}):
        tanya[r.get("user_id")] = tanya.get(r.get("user_id"), 0) + 1
    items = []
    for uid, row in per.items():
        m = akt.get(uid) or {}
        row.update({"pertama": m.get("pertama"), "terakhir": m.get("terakhir"), "permintaan": int(m.get("jumlah") or 0),
                    "masuk": masuk.get(uid, 0), "tanya_asisten": tanya.get(uid, 0)})
        if row["jumlah_pekerjaan"]:
            row["keadaan"] = "bekerja"
        elif m or row["masuk"] or row["tanya_asisten"]:
            row["keadaan"] = "hanya_membuka"
        else:
            row["keadaan"] = "tidak_aktif"
        row["pekerjaan"].sort(key=lambda p: -p["kali"])
        items.append(row)
    urut = {"bekerja": 0, "hanya_membuka": 1, "tidak_aktif": 2}
    items.sort(key=lambda r: (urut[r["keadaan"]], -r["jumlah_pekerjaan"], (r["nama"] or "").lower()))
    return {"tanggal": hari, "items": items, "ringkasan": {
        "staf": len(items), "bekerja": sum(1 for r in items if r["keadaan"] == "bekerja"),
        "hanya_membuka": sum(1 for r in items if r["keadaan"] == "hanya_membuka"),
        "tidak_aktif": sum(1 for r in items if r["keadaan"] == "tidak_aktif")}}
