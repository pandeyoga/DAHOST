"""Katalog TITIK AKSI — cara membaca data untuk tiap langkah alur & kewajiban berkala (Monitoring Staf).

Owner tidak menulis rumus: setiap titik di sini menyatakan
  * PEMICU  — kapan langkah menjadi kewajiban (stempel waktu dari dokumen),
  * BUKTI   — data apa yang membuktikan langkah sudah dikerjakan,
  * PELAKU  — field siapa yang mengerjakannya (id akun, atau nama → dicocokkan ke akun).
Siapa pemegangnya, batas waktunya, aktif/tidak = ATURAN (`core.pantau_staf.aturan`), diatur owner di layar.

Setiap detektor mengembalikan daftar `Temuan` untuk dokumen yang MASIH menunggu + yang selesai dalam jendela
peninjauan (`Konteks.sejak`), sehingga pemindai bisa menutup kejadian dengan waktu & pelaku nyata. Sumber dibaca
dari koleksi resmi (SSOT): `production_pos`, `cutting_orders`, `vendor_shipments`, `rahaza_material_issues`,
`cmt_receipts` (status lewat `core.cmt_receipt_status`), `dewi_cmt_permak`, persetujuan lewat
`routes.approval_badge.approval_groups` (definisi "masih menunggu" = `utils.notif_unified.SOURCE_RULES`), dst.
Tidak ada definisi status kedua di sini.

Pemetaan data → titik: usulan `private/audit/usulan_monitoring_staf_2026-11-10.md` bagian 4.3 (A, B, C, E).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Optional

from core.pantau_staf.waktu import Kalender, ts
from utils.waktu import to_wib

log = logging.getLogger(__name__)

BATAS_BARIS = 3000
# Nama koleksi dari modul PEMILIKNYA (satu definisi; bukan ketikan kedua di sini).
from core.cutting_material_issue import ORDERS as CUTTING  # noqa: E402
from core.opname_engine import SESS as OPNAME  # noqa: E402
from core.scan_out import SHEETS as SCAN_OUT  # noqa: E402


# ── bentuk data ────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Temuan:
    objek_id: str
    nomor: str
    mulai: Optional[datetime] = None            # None = tidak ada stempel → pemindai memakai "pertama terlihat"
    selesai_at: Optional[datetime] = None
    pelaku_id: Optional[str] = None
    pelaku_nama: Optional[str] = None
    pelaku_vendor: bool = False                 # dikerjakan vendor CMT (pengawas DA dianggap memenuhi)
    batal: bool = False
    terlewat: bool = False                      # tidak bisa dikerjakan lagi (mis. lembar ditutup sistem)
    pemegang_data: Optional[list] = None        # id akun bila pemegang diambil dari dokumen
    tenggat_dokumen: Optional[datetime] = None  # bila aturan bertenggat "tanggal dokumen"
    periode: Optional[str] = None               # kewajiban berkala: tanggal 'YYYY-MM-DD'
    po_id: Optional[str] = None                 # untuk rantai alur PO
    lingkup: dict = field(default_factory=dict)  # untuk saringan aturan (business_type, vendor_id, ...)
    keterangan: str = ""
    link_module: Optional[str] = None
    link_params: Optional[dict] = None


@dataclass
class Konteks:
    db: object
    kini: datetime
    sejak: datetime
    kal: Kalender
    users: dict = field(default_factory=dict)          # id → akun internal aktif
    nama_ke_id: dict = field(default_factory=dict)     # nama kecil → [id]
    email_ke_id: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)

    def id_dari(self, nilai) -> Optional[str]:
        """id akun dari id / email / nama tampilan (nama ganda → None, tidak ditebak)."""
        if not nilai:
            return None
        s = str(nilai).strip()
        if s in self.users:
            return s
        low = s.lower()
        if low in self.email_ke_id:
            return self.email_ke_id[low]
        ids = self.nama_ke_id.get(low) or []
        return ids[0] if len(ids) == 1 else None


@dataclass(frozen=True)
class TitikAksi:
    id: str
    nama: str
    alur: str
    urutan: int
    jenis: str                      # "alur" | "berkala"
    pemicu: str                     # kalimat untuk layar
    bukti: str                      # kalimat untuk layar
    pemegang: dict                  # bawaan: {"jenis": "akun"} | {"jenis": "data", "label": "..."}
    tenggat: dict                   # bawaan
    deteksi: Callable[[Konteks], Awaitable[list]]
    link_module: Optional[str] = None
    tanpa_waktu: bool = False       # pemicu tanpa stempel waktu sendiri → "pertama terlihat"
    saringan: tuple = ()            # kunci lingkup yang boleh disaring aturan
    nasib: Optional[Callable] = None  # (ctx, kejadian) → Temuan akhir saat objek tidak lagi menunggu


ALUR_LABEL = {
    "po": "Alur PO Produksi & Maklon",
    "persetujuan": "Persetujuan & pembayaran",
    "pengadaan": "Pengadaan",
    "gudang": "Gudang",
    "keuangan": "Keuangan",
    "sdm": "SDM",
    "marketing": "Marketing / Toko",
    "umum": "Semua akun",
}
ALUR_URUT = ["po", "persetujuan", "pengadaan", "gudang", "keuangan", "sdm", "marketing", "umum"]


# ── bantu ─────────────────────────────────────────────────────────────────────────────────────────────────
def _sejak_or(fieldname: str, sejak: datetime) -> dict:
    """Saringan `field >= sejak` untuk nilai bertipe datetime ATAU teks ISO (Mongo hanya membandingkan tipe sama)."""
    return {"$or": [{fieldname: {"$gte": sejak}}, {fieldname: {"$gte": sejak.isoformat()}}]}


def _po_link(bt: str | None) -> str:
    return "maklon-pos-engine" if (bt or "") == "maklon" else "prod-pos-internal"


def _pertama(*nilai):
    for v in nilai:
        if v:
            return v
    return None


async def _po_map(db, ids: list) -> dict:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    rows = await db.production_pos.find({"id": {"$in": ids}}, {
        "_id": 0, "id": 1, "po_number": 1, "business_type": 1, "status": 1, "vendor_id": 1,
    }).to_list(len(ids) + 5)
    return {r["id"]: r for r in rows}


# ── A. Alur PO Produksi & Maklon (`production_pos`, business_type internal|maklon) ─────────────────────────
PO_JALAN = ["Confirmed", "Distributed", "In Production", "Production Complete", "Variance Review",
            "Return Review", "Ready to Close"]
PO_TUTUP_MENUNGGU = ["Production Complete", "Variance Review", "Return Review", "Ready to Close"]
PO_SELESAI = ["Closed", "Closed Short", "Completed"]


async def _a1_konfirmasi(ctx: Konteks) -> list:
    db, out = ctx.db, []
    proj = {"_id": 0, "id": 1, "po_number": 1, "business_type": 1, "status": 1, "created_at": 1,
            "confirmed_at": 1, "confirmed_by": 1, "vendor_id": 1, "opening_import": 1}
    rows = await db.production_pos.find({"status": "Draft"}, proj).to_list(BATAS_BARIS)
    rows += await db.production_pos.find({"opening_import": {"$exists": False}, **_sejak_or("confirmed_at", ctx.sejak)},
                                          proj).to_list(BATAS_BARIS)
    seen = set()
    for r in rows:
        if r["id"] in seen or r.get("opening_import"):
            continue
        seen.add(r["id"])
        bt = r.get("business_type")
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("po_number") or "", mulai=ts(r.get("created_at")),
            selesai_at=ts(r.get("confirmed_at")) if r.get("status") != "Draft" else None,
            pelaku_id=ctx.id_dari(r.get("confirmed_by")), pelaku_nama=r.get("confirmed_by"),
            po_id=r["id"], lingkup={"business_type": bt, "vendor_id": r.get("vendor_id")},
            link_module=_po_link(bt), link_params={"po": r["id"]}))
    return out


async def _po_berjalan(ctx: Konteks) -> list:
    """PO terkonfirmasi yang masih dalam jendela (cache per pindaian)."""
    if "po_jalan" not in ctx.cache:
        proj = {"_id": 0, "id": 1, "po_number": 1, "business_type": 1, "status": 1, "confirmed_at": 1,
                "vendor_id": 1, "opening_import": 1, "status_history": 1, "closed_at": 1, "closed_by": 1}
        rows = await ctx.db.production_pos.find({"status": "Confirmed"}, proj).to_list(BATAS_BARIS)
        rows += await ctx.db.production_pos.find(
            {"status": {"$in": PO_JALAN + PO_SELESAI}, **_sejak_or("confirmed_at", ctx.sejak)}, proj).to_list(BATAS_BARIS)
        uniq = {}
        for r in rows:
            uniq.setdefault(r["id"], r)
        ctx.cache["po_jalan"] = list(uniq.values())
    return ctx.cache["po_jalan"]


async def _a2_perintah_potong(ctx: Konteks) -> list:
    pos = [p for p in await _po_berjalan(ctx) if not p.get("opening_import")]
    if not pos:
        return []
    ids = [p["id"] for p in pos]
    cuts = await ctx.db[CUTTING].find({"po_id": {"$in": ids}}, {
        "_id": 0, "po_id": 1, "created_at": 1, "created_by": 1, "created_by_name": 1, "status": 1}).to_list(BATAS_BARIS)
    pertama: dict = {}
    for c in cuts:
        if c.get("status") == "cancelled":
            continue
        cur = pertama.get(c["po_id"])
        if cur is None or (ts(c.get("created_at")) or ctx.kini) < (ts(cur.get("created_at")) or ctx.kini):
            pertama[c["po_id"]] = c
    out = []
    for p in pos:
        c = pertama.get(p["id"])
        if not c and p.get("status") != "Confirmed":
            continue                      # PO sudah lanjut tanpa cutting di DA → langkah ini tidak berlaku
        bt = p.get("business_type")
        out.append(Temuan(
            objek_id=p["id"], nomor=p.get("po_number") or "", mulai=ts(p.get("confirmed_at")),
            selesai_at=ts(c.get("created_at")) if c else None,
            pelaku_id=(c or {}).get("created_by"), pelaku_nama=(c or {}).get("created_by_name"),
            po_id=p["id"], lingkup={"business_type": bt, "vendor_id": p.get("vendor_id")},
            link_module="cutting-orders"))
    return out


async def _a3_selesai_potong(ctx: Konteks) -> list:
    proj = {"_id": 0, "id": 1, "number": 1, "order_number": 1, "po_id": 1, "status": 1, "started_at": 1,
            "completed_at": 1, "created_at": 1}
    rows = await ctx.db[CUTTING].find({"status": "in_progress"}, proj).to_list(BATAS_BARIS)
    rows += await ctx.db[CUTTING].find({"status": "completed", **_sejak_or("completed_at", ctx.sejak)},
                                             proj).to_list(BATAS_BARIS)
    pos = await _po_map(ctx.db, [r.get("po_id") for r in rows])
    out = []
    for r in rows:
        p = pos.get(r.get("po_id")) or {}
        out.append(Temuan(
            objek_id=r["id"], nomor=_pertama(r.get("number"), r.get("order_number"), r["id"][:8]),
            mulai=ts(_pertama(r.get("started_at"), r.get("created_at"))),
            selesai_at=ts(r.get("completed_at")) if r.get("status") == "completed" else None,
            po_id=r.get("po_id") or None,
            lingkup={"business_type": p.get("business_type"), "vendor_id": p.get("vendor_id")},
            keterangan=f"PO {p.get('po_number')}" if p.get("po_number") else "",
            link_module="cutting-orders"))
    return out


async def _a4_kirim_cmt(ctx: Konteks) -> list:
    pos = [p for p in await _po_berjalan(ctx) if not p.get("opening_import")]
    if not pos:
        return []
    ids = [p["id"] for p in pos]
    ships = await ctx.db.vendor_shipments.find(
        {"po_id": {"$in": ids}, "opening": {"$ne": True}, "status": {"$in": ["Sent", "Received"]}},
        {"_id": 0, "po_id": 1, "created_at": 1, "created_by": 1, "entered_by_id": 1, "entered_by": 1,
         "shipment_type": 1}).to_list(BATAS_BARIS)
    cuts = await ctx.db[CUTTING].find({"po_id": {"$in": ids}, "status": {"$ne": "cancelled"}},
                                            {"_id": 0, "po_id": 1, "status": 1, "completed_at": 1}).to_list(BATAS_BARIS)
    kirim: dict = {}
    for s in ships:
        cur = kirim.get(s["po_id"])
        if cur is None or (ts(s.get("created_at")) or ctx.kini) < (ts(cur.get("created_at")) or ctx.kini):
            kirim[s["po_id"]] = s
    potong: dict = {}
    for c in cuts:
        potong.setdefault(c["po_id"], []).append(c)
    out = []
    for p in pos:
        s = kirim.get(p["id"])
        mulai = ts(p.get("confirmed_at"))
        cs = potong.get(p["id"]) or []
        if cs:
            if not s and any(c.get("status") != "completed" for c in cs):
                continue                  # potong masih berjalan → kirim belum terpicu
            selesai_potong = [ts(c.get("completed_at")) for c in cs if c.get("completed_at")]
            if selesai_potong:
                mulai = max([m for m in selesai_potong if m] + ([mulai] if mulai else []))
        if not s and p.get("status") != "Confirmed":
            continue
        bt = p.get("business_type")
        pelaku = (s or {}).get("entered_by_id") or ctx.id_dari((s or {}).get("created_by"))
        out.append(Temuan(
            objek_id=p["id"], nomor=p.get("po_number") or "", mulai=mulai,
            selesai_at=ts(s.get("created_at")) if s else None,
            pelaku_id=pelaku, pelaku_nama=(s or {}).get("entered_by") or (s or {}).get("created_by"),
            po_id=p["id"], lingkup={"business_type": bt, "vendor_id": p.get("vendor_id")},
            link_module="prod-shipments-vendor"))
    return out


async def _a5_bahan_keluar(ctx: Konteks) -> list:
    proj = {"_id": 0, "id": 1, "mi_number": 1, "po_id": 1, "status": 1, "created_at": 1, "issued_at": 1,
            "issued_by": 1, "business_type": 1, "vendor_id": 1, "po_number_snapshot": 1}
    rows = await ctx.db.rahaza_material_issues.find({"status": "pending_approval"}, proj).to_list(BATAS_BARIS)
    rows += await ctx.db.rahaza_material_issues.find({"status": "issued", **_sejak_or("issued_at", ctx.sejak)},
                                                     proj).to_list(BATAS_BARIS)
    out = []
    for r in rows:
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("mi_number") or "", mulai=ts(r.get("created_at")),
            selesai_at=ts(r.get("issued_at")) if r.get("status") == "issued" else None,
            pelaku_id=ctx.id_dari(r.get("issued_by")), po_id=r.get("po_id") or None,
            lingkup={"business_type": r.get("business_type"), "vendor_id": r.get("vendor_id")},
            keterangan=f"PO {r.get('po_number_snapshot')}" if r.get("po_number_snapshot") else "",
            link_module="wh-material-issue"))
    return out


async def _kiriman_cmt(ctx: Konteks) -> list:
    if "kiriman" not in ctx.cache:
        proj = {"_id": 0, "id": 1, "shipment_number": 1, "po_id": 1, "po_number": 1, "status": 1, "created_at": 1,
                "received_at": 1, "inspection_status": 1, "inspected_at": 1, "vendor_id": 1, "vendor_name": 1,
                "business_type": 1, "entered_by_id": 1, "entered_by": 1, "opening": 1}
        rows = await ctx.db.vendor_shipments.find({"status": "Sent", "opening": {"$ne": True}}, proj).to_list(BATAS_BARIS)
        rows += await ctx.db.vendor_shipments.find(
            {"status": "Received", "opening": {"$ne": True},
             "$or": [{"inspection_status": {"$ne": "Inspected"}},
                     {"received_at": {"$gte": ctx.sejak}}, {"inspected_at": {"$gte": ctx.sejak}}]},
            proj).to_list(BATAS_BARIS)
        uniq = {}
        for r in rows:
            uniq.setdefault(r["id"], r)
        ctx.cache["kiriman"] = list(uniq.values())
    return ctx.cache["kiriman"]


async def _a6_cmt_terima(ctx: Konteks) -> list:
    out = []
    for r in await _kiriman_cmt(ctx):
        diterima = r.get("status") == "Received"
        staf = r.get("entered_by_id")
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("shipment_number") or "", mulai=ts(r.get("created_at")),
            selesai_at=ts(r.get("received_at")) if diterima else None,
            pelaku_id=staf, pelaku_nama=r.get("entered_by") or (r.get("vendor_name") if diterima else None),
            pelaku_vendor=bool(diterima and not staf), po_id=r.get("po_id") or None,
            lingkup={"business_type": r.get("business_type"), "vendor_id": r.get("vendor_id")},
            keterangan=f"{r.get('vendor_name') or 'Vendor'} · PO {r.get('po_number') or '-'}",
            link_module="cmt-override-portal"))
    return out


async def _a7_cmt_inspeksi(ctx: Konteks) -> list:
    out = []
    for r in await _kiriman_cmt(ctx):
        if r.get("status") != "Received":
            continue
        selesai = r.get("inspection_status") == "Inspected"
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("shipment_number") or "", mulai=ts(r.get("received_at")),
            selesai_at=ts(r.get("inspected_at")) if selesai else None,
            pelaku_vendor=selesai, pelaku_nama=r.get("vendor_name") if selesai else None,
            po_id=r.get("po_id") or None,
            lingkup={"business_type": r.get("business_type"), "vendor_id": r.get("vendor_id")},
            keterangan=f"{r.get('vendor_name') or 'Vendor'} · PO {r.get('po_number') or '-'}",
            link_module="cmt-override-portal"))
    return out


async def _a9_terima_qc(ctx: Konteks) -> list:
    from core.cmt_receipt_status import ST_DONE, ST_QC, canon_status
    proj = {"_id": 0, "id": 1, "receipt_code": 1, "po_id": 1, "po_number": 1, "status": 1, "created_at": 1,
            "qc_completed_at": 1, "qc_completed_by": 1, "approved_at": 1, "approved_by": 1, "business_type": 1,
            "cmt_vendor_id": 1, "cmt_name": 1}
    terbuka = ["on_qc", "draft", "Draft", "submitted", "Submitted"]
    rows = await ctx.db.cmt_receipts.find({"status": {"$in": terbuka}}, proj).to_list(BATAS_BARIS)
    rows += await ctx.db.cmt_receipts.find(_sejak_or("qc_completed_at", ctx.sejak), proj).to_list(BATAS_BARIS)
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        st = canon_status(r.get("status"))
        if st not in (ST_QC, ST_DONE):
            continue
        selesai = st == ST_DONE
        pelaku_nama = _pertama(r.get("qc_completed_by"), r.get("approved_by")) if selesai else None
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("receipt_code") or "", mulai=ts(r.get("created_at")),
            selesai_at=ts(_pertama(r.get("qc_completed_at"), r.get("approved_at"))) if selesai else None,
            pelaku_id=ctx.id_dari(pelaku_nama), pelaku_nama=pelaku_nama, po_id=r.get("po_id") or None,
            lingkup={"business_type": r.get("business_type"), "vendor_id": r.get("cmt_vendor_id")},
            keterangan=f"{r.get('cmt_name') or 'CMT'} · PO {r.get('po_number') or '-'}",
            link_module="da-cmt-receive"))
    return out


async def _a10_permak(ctx: Konteks) -> list:
    proj = {"_id": 0, "id": 1, "permak_number": 1, "po_id": 1, "po_number": 1, "status": 1, "created_at": 1,
            "updated_at": 1, "status_history": 1, "vendor_id": 1}
    rows = await ctx.db.dewi_cmt_permak.find({"status": {"$in": ["open", "in_progress"]}}, proj).to_list(BATAS_BARIS)
    rows += await ctx.db.dewi_cmt_permak.find(
        {"status": {"$in": ["selesai_berhasil", "gagal_buang"]}, **_sejak_or("updated_at", ctx.sejak)},
        proj).to_list(BATAS_BARIS)
    pos = await _po_map(ctx.db, [r.get("po_id") for r in rows])
    out = []
    for r in rows:
        selesai = r.get("status") in ("selesai_berhasil", "gagal_buang")
        akhir = None
        if selesai:
            for h in reversed(r.get("status_history") or []):
                if h.get("status") == r.get("status"):
                    akhir = h
                    break
        p = pos.get(r.get("po_id")) or {}
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("permak_number") or "", mulai=ts(r.get("created_at")),
            selesai_at=ts(_pertama((akhir or {}).get("at"), r.get("updated_at"))) if selesai else None,
            pelaku_id=ctx.id_dari((akhir or {}).get("by")), pelaku_nama=(akhir or {}).get("by"),
            po_id=r.get("po_id") or None,
            lingkup={"business_type": p.get("business_type"), "vendor_id": r.get("vendor_id")},
            keterangan=f"PO {r.get('po_number')}" if r.get("po_number") else "",
            link_module="cmt-permak"))
    return out


def _masuk_status(po: dict, statuses: list) -> Optional[datetime]:
    """Waktu PO PERTAMA masuk salah satu status (dari `status_history`, dicatat sejak 10 Nov 2026)."""
    for h in po.get("status_history") or []:
        if h.get("status") in statuses:
            return ts(h.get("at"))
    return None


async def _a13_tutup_po(ctx: Konteks) -> list:
    proj = {"_id": 0, "id": 1, "po_number": 1, "business_type": 1, "status": 1, "status_history": 1,
            "closed_at": 1, "closed_by": 1, "vendor_id": 1, "opening_import": 1}
    rows = await ctx.db.production_pos.find({"status": {"$in": PO_TUTUP_MENUNGGU}}, proj).to_list(BATAS_BARIS)
    rows += await ctx.db.production_pos.find({"status": {"$in": PO_SELESAI}, **_sejak_or("closed_at", ctx.sejak)},
                                             proj).to_list(BATAS_BARIS)
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        selesai = r.get("status") in PO_SELESAI
        mulai = _masuk_status(r, PO_TUTUP_MENUNGGU)
        if selesai and mulai is None:
            continue                       # selesai sebelum riwayat status dicatat → tidak dinilai
        bt = r.get("business_type")
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("po_number") or "", mulai=mulai,
            selesai_at=ts(r.get("closed_at")) if selesai else None,
            pelaku_id=ctx.id_dari(r.get("closed_by")), pelaku_nama=r.get("closed_by"),
            po_id=r["id"], lingkup={"business_type": bt, "vendor_id": r.get("vendor_id")},
            link_module="po-closure"))
    return out


# ── B. Persetujuan & pembayaran — SATU sumber dengan lencana "Perlu Tindakan" ─────────────────────────────
SUPER_PERAN = {"superadmin", "owner"}
PERSETUJUAN_GRUP = {
    # titik id: (kunci grup approval_groups, nama langkah, menu)
    "setuju_pembelian": ("pr", "Putuskan persetujuan pembelian (PR/PO)", "proc-requests"),
    "bayar_tagihan": ("ap", "Bayar tagihan pemasok", "fin-ap-aging"),
    "setuju_sdm": ("hr", "Putuskan cuti, lembur & penyesuaian gaji", "hr-inbox"),
    "tinjau_kasbon": ("kasbon_review", "Tinjau kasbon", "hr-kasbon"),
    "cairkan_klaim": ("expense_disburse", "Cairkan klaim biaya yang disetujui", "fin-expenses"),
    "cairkan_kasbon": ("kasbon_disburse", "Cairkan kasbon yang disetujui", "fin-kasbon"),
    "setuju_batal_payroll": ("payroll_cancel", "Putuskan pembatalan run gaji", "hr-payroll-run"),
    "periksa_selisih_cmt": ("cmt_variance", "Periksa tagihan CMT bertanda selisih", "prod-cmt-billing"),
    "putuskan_retur": ("wh_return", "Putuskan retur gudang", "wh-returns"),
}
_MULAI_FIELD = {
    "dewi_procurement_requests": ("submitted_at", "created_at"),
    "acc_purchase_requests": ("submitted_at", "created_at"),
    "rahaza_purchase_orders": ("submitted_at", "created_at"),
    "rahaza_ap_invoices": ("issue_date", "created_at"),
    "rahaza_leave_requests": ("created_at",),
    "rahaza_overtime_requests": ("created_at",),
    "rahaza_salary_adjustments": ("created_at",),
    "dewi_kasbon_requests": ("hr_approved_at", "submitted_at", "created_at"),
    "rahaza_expense_claims": ("approved_at", "submitted_at", "created_at"),
    "rahaza_payroll_runs": ("cancel_request.requested_at",),
    "dewi_cmt_payments": ("created_at",),
    "wh_returns": ("created_at",),
}
_NOMOR_FIELD = ("request_number", "po_number", "invoice_number", "kasbon_number", "claim_number", "return_number",
                "run_number", "number", "code", "payment_number", "title")
_KEPUTUSAN_AT = ("approved_at", "rejected_at", "decided_at", "paid_at", "disbursed_at", "cancelled_at",
                 "resolved_at", "finalized_at", "updated_at")
_KEPUTUSAN_BY = ("approved_by", "rejected_by", "decided_by", "paid_by", "disbursed_by", "cancelled_by",
                 "resolved_by", "updated_by")


def _ambil(doc: dict, dotted: str):
    cur = doc
    for p in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


async def _antrean_persetujuan(ctx: Konteks) -> dict:
    """{grup: {(koleksi, id): set(id akun penyetuju)}} — dihitung sekali per pindaian dari `approval_groups`
    (mesin yang sama dengan lencana bel; superadmin/owner bukan staf yang dinilai)."""
    if "antrean" in ctx.cache:
        return ctx.cache["antrean"]
    from auth import compute_permissions
    from routes.approval_badge import approval_groups
    antrean: dict = {}
    for uid, u in ctx.users.items():
        role = (u.get("role") or "").lower()
        if role in SUPER_PERAN:
            continue
        user = {"id": uid, "email": u.get("email"), "role": u.get("role"), "name": u.get("name"),
                "department": u.get("department", "")}
        try:
            user["_permissions"] = await compute_permissions(u.get("role") or "", uid)
            groups = await approval_groups(ctx.db, user, with_keys=True)
        except Exception:  # noqa: BLE001 — satu akun gagal tidak boleh menghentikan pindaian
            log.debug("[pantau-staf] approval_groups gagal untuk %s", uid, exc_info=True)
            continue
        for g in groups:
            for key in g.get("keys") or []:
                antrean.setdefault(g["key"], {}).setdefault(tuple(key), set()).add(uid)
    ctx.cache["antrean"] = antrean
    return antrean


def _pilih_pemegang(ctx: Konteks, ids: set) -> list:
    """Penyetuju yang bukan admin didahulukan; admin hanya bila tidak ada yang lain."""
    biasa = [i for i in ids if (ctx.users.get(i, {}).get("role") or "").lower() != "admin"]
    return sorted(biasa or ids)


def _persetujuan(titik_id: str):
    grup, _, menu = PERSETUJUAN_GRUP[titik_id]

    async def deteksi(ctx: Konteks) -> list:
        antrean = (await _antrean_persetujuan(ctx)).get(grup) or {}
        per_koleksi: dict = {}
        for coll, did in antrean:
            per_koleksi.setdefault(coll, []).append(did)
        out = []
        for coll, ids in per_koleksi.items():
            fields = {"_id": 0, "id": 1, "due_date": 1, "cancel_request": 1}
            for f in _MULAI_FIELD.get(coll, ("created_at",)) + _NOMOR_FIELD:
                fields[f.split(".")[0]] = 1
            docs = await ctx.db[coll].find({"id": {"$in": ids}}, fields).to_list(len(ids) + 5)
            for d in docs:
                mulai = None
                for f in _MULAI_FIELD.get(coll, ("created_at",)):
                    mulai = ts(_ambil(d, f))
                    if mulai:
                        break
                nomor = next((str(d[f]) for f in _NOMOR_FIELD if d.get(f)), d["id"][:8])
                out.append(Temuan(
                    objek_id=f"{coll}:{d['id']}", nomor=nomor, mulai=mulai,
                    pemegang_data=_pilih_pemegang(ctx, antrean.get((coll, d["id"])) or set()),
                    tenggat_dokumen=ts(d.get("due_date")) if coll == "rahaza_ap_invoices" else None,
                    link_module=menu))
        return out

    return deteksi


async def _nasib_persetujuan(ctx: Konteks, kejadian: dict) -> Optional[Temuan]:
    """Objek persetujuan keluar dari antrean: diputus (selesai, pelaku dari dokumen) atau hilang (batal)."""
    coll, _, did = (kejadian.get("objek_id") or "").partition(":")
    if not coll or not did:
        return None
    doc = await ctx.db[coll].find_one({"id": did}, {"_id": 0})
    if not doc:
        return Temuan(objek_id=kejadian["objek_id"], nomor=kejadian.get("nomor") or "", batal=True)
    status = str(doc.get("status") or "").lower()
    if status in ("cancelled", "canceled", "deleted", "void", "voided"):
        return Temuan(objek_id=kejadian["objek_id"], nomor=kejadian.get("nomor") or "", batal=True)
    at = next((ts(doc.get(f)) for f in _KEPUTUSAN_AT if doc.get(f)), None) or ctx.kini
    by = next((doc.get(f) for f in _KEPUTUSAN_BY if doc.get(f)), None)
    if isinstance(by, dict):
        by = by.get("id") or by.get("name")
    return Temuan(objek_id=kejadian["objek_id"], nomor=kejadian.get("nomor") or "", selesai_at=at,
                  pelaku_id=ctx.id_dari(by), pelaku_nama=str(by) if by else None)


# ── C. Pengadaan & Gudang ─────────────────────────────────────────────────────────────────────────────────
async def _c1_pr_ajukan(ctx: Konteks) -> list:
    proj = {"_id": 0, "id": 1, "request_number": 1, "status": 1, "created_at": 1, "submitted_at": 1,
            "requested_by": 1, "requested_by_name": 1, "title": 1}
    rows = await ctx.db.dewi_procurement_requests.find({"status": "draft"}, proj).to_list(BATAS_BARIS)
    rows += await ctx.db.dewi_procurement_requests.find(_sejak_or("submitted_at", ctx.sejak), proj).to_list(BATAS_BARIS)
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        selesai = r.get("status") != "draft" and r.get("submitted_at")
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("request_number") or "", mulai=ts(r.get("created_at")),
            selesai_at=ts(r.get("submitted_at")) if selesai else None,
            pelaku_id=r.get("requested_by") if selesai else None, pelaku_nama=r.get("requested_by_name"),
            pemegang_data=[r["requested_by"]] if r.get("requested_by") else [],
            keterangan=r.get("title") or "", link_module="proc-requests"))
    return out


async def _c2_pr_jadi_po(ctx: Konteks) -> list:
    proj = {"_id": 0, "id": 1, "request_number": 1, "status": 1, "approved_at": 1, "linked_po_id": 1, "title": 1}
    rows = await ctx.db.dewi_procurement_requests.find(
        {"status": "approved", "linked_po_id": {"$in": [None, ""]}}, proj).to_list(BATAS_BARIS)
    rows += await ctx.db.dewi_procurement_requests.find(
        {"linked_po_id": {"$nin": [None, ""]}, **_sejak_or("approved_at", ctx.sejak)}, proj).to_list(BATAS_BARIS)
    po_ids = [r["linked_po_id"] for r in rows if r.get("linked_po_id")]
    pos = {}
    if po_ids:
        for p in await ctx.db.rahaza_purchase_orders.find(
                {"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "created_at": 1, "created_by": 1}).to_list(len(po_ids) + 5):
            pos[p["id"]] = p
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        po = pos.get(r.get("linked_po_id") or "") or {}
        selesai = bool(r.get("linked_po_id"))
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("request_number") or "", mulai=ts(r.get("approved_at")),
            selesai_at=(ts(po.get("created_at")) or ctx.kini) if selesai else None,
            pelaku_id=ctx.id_dari(po.get("created_by")), keterangan=r.get("title") or "",
            link_module="proc-purchase-orders"))
    return out


_OPNAME_PROJ = {"_id": 0, "id": 1, "session_no": 1, "status": 1, "created_at": 1, "submitted_at": 1,
                "submitted_by": 1, "approved_at": 1, "approved_by": 1, "rejected_at": 1, "rejected_by": 1,
                "created_by": 1, "created_by_name": 1, "location_id": 1, "location_name": 1, "scope_label": 1}


async def _c9a_opname_hitung(ctx: Konteks) -> list:
    rows = await ctx.db[OPNAME].find({"status": "counting"}, _OPNAME_PROJ).to_list(BATAS_BARIS)
    rows += await ctx.db[OPNAME].find(_sejak_or("submitted_at", ctx.sejak), _OPNAME_PROJ).to_list(BATAS_BARIS)
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen or r.get("status") == "cancelled":
            continue
        seen.add(r["id"])
        selesai = r.get("status") != "counting" and r.get("submitted_at")
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("session_no") or "", mulai=ts(r.get("created_at")),
            selesai_at=ts(r.get("submitted_at")) if selesai else None,
            pelaku_id=ctx.id_dari(r.get("submitted_by")) if selesai else None,
            pemegang_data=[r["created_by"]] if r.get("created_by") else [],
            lingkup={"location_id": r.get("location_id")}, keterangan=r.get("scope_label") or "",
            link_module="wms-stock-hub", link_params={"tab": "opname"}))
    return out


async def _c9b_opname_setujui(ctx: Konteks) -> list:
    rows = await ctx.db[OPNAME].find({"status": {"$in": ["submitted", "approving"]}},
                                                 _OPNAME_PROJ).to_list(BATAS_BARIS)
    rows += await ctx.db[OPNAME].find(
        {"status": {"$in": ["approved", "rejected"]}, **_sejak_or("submitted_at", ctx.sejak)}, _OPNAME_PROJ).to_list(BATAS_BARIS)
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        selesai = r.get("status") in ("approved", "rejected")
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("session_no") or "", mulai=ts(r.get("submitted_at")),
            selesai_at=ts(_pertama(r.get("approved_at"), r.get("rejected_at"))) if selesai else None,
            pelaku_id=ctx.id_dari(_pertama(r.get("approved_by"), r.get("rejected_by"))) if selesai else None,
            lingkup={"location_id": r.get("location_id")}, keterangan=r.get("scope_label") or "",
            link_module="wms-stock-hub", link_params={"tab": "opname"}))
    return out


async def _e3_scan_out(ctx: Konteks) -> list:
    dari = to_wib(ctx.sejak).date().isoformat()
    proj = {"_id": 0, "id": 1, "number": 1, "date": 1, "location_id": 1, "location_name": 1, "status": 1,
            "auto_closed": 1, "closed_at": 1, "closed_by": 1, "closed_by_id": 1, "created_at": 1}
    rows = await ctx.db[SCAN_OUT].find({"date": {"$gte": dari}}, proj).to_list(BATAS_BARIS)
    out = []
    for r in rows:
        tutup = r.get("status") == "closed"
        otomatis = bool(r.get("auto_closed"))
        out.append(Temuan(
            objek_id=r["id"], nomor=r.get("number") or r.get("date") or "", mulai=ts(r.get("created_at")),
            periode=r.get("date"), selesai_at=ts(r.get("closed_at")) if (tutup and not otomatis) else None,
            terlewat=tutup and otomatis, pelaku_id=r.get("closed_by_id") if tutup and not otomatis else None,
            pelaku_nama=r.get("closed_by"), lingkup={"location_id": r.get("location_id")},
            keterangan=r.get("location_name") or "", link_module="wh-scan-out"))
    return out


# ── E. Kewajiban berkala harian ───────────────────────────────────────────────────────────────────────────
def _hari_hari(ctx: Konteks, *, hanya_kerja: bool, sampai_kemarin: bool = False, maks: int = 35) -> list[date]:
    akhir = to_wib(ctx.kini).date() - (timedelta(days=1) if sampai_kemarin else timedelta(0))
    awal = max(to_wib(ctx.sejak).date(), akhir - timedelta(days=maks))
    out, cur = [], awal
    while cur <= akhir:
        if not hanya_kerja or ctx.kal.kerja(cur):
            out.append(cur)
        cur += timedelta(days=1)
    return out


async def _bukti_per_tanggal(db, koleksi: str, hari: list[str], *, tambahan: dict | None = None,
                             waktu=("created_at", "timestamp"), oleh=("created_by",)) -> dict:
    """{tanggal: (waktu catat paling awal, pelaku)} dari dokumen ber-`date` = tanggal itu."""
    if not hari:
        return {}
    q = {"date": {"$in": hari}, **(tambahan or {})}
    proj = {"_id": 0, "date": 1, **{f: 1 for f in waktu + oleh}}
    out: dict = {}
    for r in await db[koleksi].find(q, proj).to_list(20000):
        d = str(r.get("date"))[:10]
        t = next((ts(r.get(f)) for f in waktu if r.get(f)), None)
        by = next((r.get(f) for f in oleh if r.get(f)), None)
        cur = out.get(d)
        if cur is None or (t and (cur[0] is None or t < cur[0])):
            out[d] = (t, by)
    return out


async def _e1_kas_harian(ctx: Konteks) -> list:
    hari = [d.isoformat() for d in _hari_hari(ctx, hanya_kerja=True)]
    a = await _bukti_per_tanggal(ctx.db, "rahaza_cash_movements", hari)
    b = await _bukti_per_tanggal(ctx.db, "rahaza_expenses", hari)
    out = []
    for d in hari:
        cands = [x for x in (a.get(d), b.get(d)) if x]
        bukti = min(cands, key=lambda x: x[0] or ctx.kini) if cands else None
        out.append(Temuan(
            objek_id=d, nomor=d, periode=d, mulai=ts(d),
            selesai_at=(bukti[0] or ctx.kini) if bukti else None,
            pelaku_id=ctx.id_dari(bukti[1]) if bukti else None, link_module="fin-cash"))
    return out


async def _e2_absensi(ctx: Konteks) -> list:
    hari = [d.isoformat() for d in _hari_hari(ctx, hanya_kerja=True)]
    bukti = await _bukti_per_tanggal(ctx.db, "rahaza_attendance_events", hari, oleh=("created_by", "updated_by"))
    return [Temuan(objek_id=d, nomor=d, periode=d, mulai=ts(d),
                   selesai_at=(bukti[d][0] or ctx.kini) if d in bukti else None,
                   pelaku_id=ctx.id_dari(bukti[d][1]) if d in bukti else None, link_module="hr-attendance")
            for d in hari]


async def _e4_penjualan_toko(ctx: Konteks) -> list:
    from core import marketing_input_mode as _mode
    hari = [d.isoformat() for d in _hari_hari(ctx, hanya_kerja=False, sampai_kemarin=True, maks=14)]
    if not hari:
        return []
    akun = await ctx.db.marketing_platform_accounts.find(
        {"status": "active"}, {"_id": 0}).to_list(500)
    out = []
    for acc in akun:
        aid = acc.get("id")
        if not aid:
            continue
        impor = (await _mode.mode_toko(ctx.db, acc)) == _mode.IMPOR
        q = {"account_id": aid, "date": {"$in": hari}}
        if impor:
            q["source"] = "orders_auto"
        ada: dict = {}
        for r in await ctx.db.marketing_sales_data.find(q, {"_id": 0, "date": 1, "created_at": 1, "updated_at": 1,
                                                            "created_by": 1}).to_list(len(hari) * 4 + 10):
            d = str(r.get("date"))[:10]
            t = ts(_pertama(r.get("created_at"), r.get("updated_at")))
            if d not in ada or (t and ada[d][0] and t < ada[d][0]):
                ada[d] = (t, r.get("created_by"))
        nama = acc.get("account_name") or acc.get("name") or aid
        for d in hari:
            b = ada.get(d)
            out.append(Temuan(
                objek_id=f"{aid}:{d}", nomor=nama, periode=d, mulai=ts(d),
                selesai_at=(b[0] or ctx.kini) if b else None, pelaku_id=ctx.id_dari(b[1]) if b else None,
                pemegang_data=[acc["pic_user_id"]] if acc.get("pic_user_id") else [],
                lingkup={"account_id": aid},
                keterangan="impor pesanan" if impor else "rekap harian",
                link_module="marketing-import" if impor else "marketing-sales"))
    return out


PORTAL_NON_KERJA = {"self", "collaboration"}


async def _portal_kerja(ctx: Konteks, uid: str) -> bool:
    key = ("portal_kerja", uid)
    if key not in ctx.cache:
        from routes.shared import get_user_portals, resolve_role_access
        u = dict(ctx.users.get(uid) or {})
        try:
            acc = await resolve_role_access(ctx.db, {"id": uid, "role": u.get("role")})
            portals = set(acc.get("portals") or []) | set(get_user_portals({**u, "_portals": acc.get("portals")}))
        except Exception:  # noqa: BLE001
            portals = set()
        ctx.cache[key] = bool(portals - PORTAL_NON_KERJA)
    return ctx.cache[key]


async def _e9_aktif_harian(ctx: Konteks) -> list:
    """Hari kerja yang sudah lewat: akun ber-portal kerja yang HADIR tetapi tidak membuka sistem sama sekali.
    Hadir = ada absen 'hadir' (akun tertaut karyawan). Cuti/izin/sakit tidak dihitung (K7). Belum ada data
    absen hari itu sama sekali → dianggap hadir (absen belum diimpor bukan salah staf ini)."""
    hari = [d.isoformat() for d in _hari_hari(ctx, hanya_kerja=True, sampai_kemarin=True, maks=21)]
    if not hari:
        return []
    from core.pantau_staf import meter
    akun = [uid for uid, u in ctx.users.items() if (u.get("role") or "").lower() not in SUPER_PERAN]
    akun = [uid for uid in akun if await _portal_kerja(ctx, uid)]
    if not akun:
        return []
    aktif = {(r["user_id"], r["tanggal"]): r for r in await meter.aktivitas(ctx.db, akun, hari[0], hari[-1])}
    emp = {uid: ctx.users[uid].get("employee_id") for uid in akun if ctx.users[uid].get("employee_id")}
    absen: dict = {}
    hari_ada_absen: set = set()
    if emp:
        for r in await ctx.db.rahaza_attendance_events.find(
                {"date": {"$in": hari}}, {"_id": 0, "employee_id": 1, "date": 1, "status": 1}).to_list(50000):
            hari_ada_absen.add(str(r.get("date"))[:10])
            absen[(r.get("employee_id"), str(r.get("date"))[:10])] = (r.get("status") or "").lower()
    cuti = set()
    if emp:
        for lv in await ctx.db.rahaza_leave_requests.find(
                {"status": "approved", "employee_id": {"$in": list(emp.values())}, "to_date": {"$gte": hari[0]}},
                {"_id": 0, "employee_id": 1, "from_date": 1, "to_date": 1}).to_list(5000):
            for d in hari:
                if str(lv.get("from_date") or "")[:10] <= d <= str(lv.get("to_date") or "")[:10]:
                    cuti.add((lv.get("employee_id"), d))
    out = []
    for uid in akun:
        e = emp.get(uid)
        for d in hari:
            if e:
                if (e, d) in cuti:
                    continue
                st = absen.get((e, d))
                if st and st != "hadir":
                    continue                       # izin/sakit/alfa: tidak dihitung
                if st is None and d in hari_ada_absen:
                    continue                       # absen hari itu sudah diimpor tetapi orang ini tidak hadir
            row = aktif.get((uid, d))
            out.append(Temuan(
                objek_id=f"{uid}:{d}", nomor=d, periode=d, mulai=ts(d),
                selesai_at=ts(row.get("pertama")) if row else None, pelaku_id=uid if row else None,
                terlewat=row is None, pemegang_data=[uid], link_module=None))
    return out


# ── KATALOG ───────────────────────────────────────────────────────────────────────────────────────────────
_AKUN = {"jenis": "akun"}
_HK1 = {"jenis": "hari_kerja", "nilai": 1}
_HK2 = {"jenis": "hari_kerja", "nilai": 2}
_HK3 = {"jenis": "hari_kerja", "nilai": 3}
_BT = ("business_type", "vendor_id")

KATALOG_LIST: list[TitikAksi] = [
    # A. alur PO
    TitikAksi("po_konfirmasi", "Konfirmasi PO", "po", 10, "alur",
              "PO draf dibuat", "status PO bukan Draf lagi (tanggal konfirmasi)", _AKUN, _HK1, _a1_konfirmasi,
              "prod-pos-internal", saringan=_BT),
    TitikAksi("po_perintah_potong", "Buat perintah potong untuk PO", "po", 20, "alur",
              "PO dikonfirmasi (berlaku bila bahan PO dipotong di DA)", "perintah potong tertaut PO dibuat",
              _AKUN, _HK1, _a2_perintah_potong, "cutting-orders", saringan=_BT),
    TitikAksi("po_selesai_potong", "Selesaikan potong", "po", 30, "alur",
              "perintah potong mulai dikerjakan", "perintah potong selesai", _AKUN, _HK2, _a3_selesai_potong,
              "cutting-orders", saringan=_BT),
    TitikAksi("po_kirim_cmt", "Kirim bahan ke CMT", "po", 40, "alur",
              "PO dikonfirmasi dan potong (bila ada) selesai", "surat jalan kirim ke CMT dibuat", _AKUN, _HK1,
              _a4_kirim_cmt, "prod-shipments-vendor", saringan=_BT),
    TitikAksi("po_bahan_keluar", "Setujui pengeluaran bahan kiriman CMT", "po", 50, "alur",
              "pengeluaran bahan otomatis dari kirim CMT menunggu persetujuan", "bahan tercatat keluar",
              _AKUN, {"jenis": "jam", "nilai": 8}, _a5_bahan_keluar, "wh-material-issue", saringan=_BT),
    TitikAksi("po_cmt_terima", "CMT menerima bahan (diawasi staf DA)", "po", 60, "alur",
              "kiriman ke CMT berstatus Dikirim", "kiriman ditandai diterima (oleh vendor atau diinput staf atas nama vendor)",
              _AKUN, _HK1, _a6_cmt_terima, "cmt-override-portal", saringan=_BT),
    TitikAksi("po_cmt_inspeksi", "Inspeksi bahan di CMT (diawasi staf DA)", "po", 70, "alur",
              "kiriman diterima CMT", "hasil inspeksi bahan dikirim", _AKUN, _HK1, _a7_cmt_inspeksi,
              "cmt-override-portal", saringan=_BT),
    TitikAksi("po_terima_qc", "Terima & QC hasil CMT", "po", 90, "alur",
              "CMT mengirim hasil ke DA (penerimaan Sedang QC)", "penerimaan Selesai QC", _AKUN, _HK1,
              _a9_terima_qc, "da-cmt-receive", saringan=_BT),
    TitikAksi("po_permak", "Selesaikan permak", "po", 100, "alur",
              "permak dibuka", "permak selesai atau dibuang", _AKUN, _HK3, _a10_permak, "cmt-permak", saringan=_BT),
    TitikAksi("po_tutup", "Tutup PO", "po", 130, "alur",
              "PO masuk status Produksi selesai / Tinjau selisih / Tinjau retur / Siap ditutup",
              "PO ditutup", _AKUN, _HK3, _a13_tutup_po, "po-closure", tanpa_waktu=True, saringan=_BT),
    # C. pengadaan
    TitikAksi("pr_ajukan", "Ajukan PR draf", "pengadaan", 10, "alur",
              "PR draf dibuat", "PR diajukan", {"jenis": "data", "label": "pembuat PR"}, _HK1, _c1_pr_ajukan,
              "proc-requests"),
    TitikAksi("pr_jadi_po", "Buat PO dari PR yang disetujui", "pengadaan", 20, "alur",
              "PR disetujui penuh", "PO pembelian tertaut dibuat", _AKUN, _HK2, _c2_pr_jadi_po,
              "proc-purchase-orders"),
    # C. gudang
    TitikAksi("opname_hitung", "Selesaikan hitung opname", "gudang", 10, "alur",
              "sesi opname dibuka", "hasil hitung diajukan", {"jenis": "data", "label": "pembuat sesi opname"},
              _HK1, _c9a_opname_hitung, "wms-stock-hub", saringan=("location_id",)),
    TitikAksi("opname_setujui", "Setujui hasil opname", "gudang", 20, "alur",
              "hasil hitung opname diajukan", "opname disetujui atau ditolak", _AKUN, _HK1, _c9b_opname_setujui,
              "wms-stock-hub", saringan=("location_id",)),
    TitikAksi("scan_out_tutup", "Tutup lembar scan-out harian", "gudang", 30, "berkala",
              "lembar scan-out hari itu dibuka",
              "lembar ditutup oleh orang (ditutup otomatis sistem pukul 23.55 = terlewat)", _AKUN,
              {"jenis": "jam_tetap", "hari": 0, "jam": "23:55"}, _e3_scan_out, "wh-scan-out",
              saringan=("location_id",)),
    # E. berkala
    TitikAksi("kas_harian", "Catat kas & biaya harian", "keuangan", 10, "berkala",
              "setiap hari kerja", "ada mutasi kas atau biaya bertanggal hari itu", _AKUN,
              {"jenis": "jam_tetap", "hari": 1, "jam": "10:00"}, _e1_kas_harian, "fin-cash"),
    TitikAksi("absensi_harian", "Absensi harian masuk sistem", "sdm", 10, "berkala",
              "setiap hari kerja", "ada catatan absen bertanggal hari itu", _AKUN,
              {"jenis": "jam_tetap", "hari": 1, "jam": "10:00"}, _e2_absensi, "hr-attendance"),
    TitikAksi("penjualan_toko", "Data penjualan toko kemarin", "marketing", 10, "berkala",
              "setiap hari, per toko aktif",
              "rekap harian toko itu ada (toko mode impor: pesanan hari itu sudah diimpor)",
              {"jenis": "data", "label": "PIC toko"}, {"jenis": "jam_tetap", "hari": 1, "jam": "10:00"},
              _e4_penjualan_toko, "marketing-import", saringan=("account_id",)),
    TitikAksi("aktif_harian", "Membuka sistem di hari kerja hadir", "umum", 10, "berkala",
              "hari kerja yang sudah lewat, staf hadir (cuti/izin/sakit tidak dihitung)",
              "ada aktivitas akun itu di sistem pada hari tersebut", {"jenis": "data", "label": "akun itu sendiri"},
              {"jenis": "jam_tetap", "hari": 0, "jam": "23:59"}, _e9_aktif_harian, None),
]
for _i, (_tid, (_g, _nama, _menu)) in enumerate(PERSETUJUAN_GRUP.items()):
    KATALOG_LIST.append(TitikAksi(
        _tid, _nama, "persetujuan", (_i + 1) * 10, "alur", "dokumen masuk antrean persetujuan/pembayaran",
        "dokumen diputus (setuju/tolak/bayar)", {"jenis": "data", "label": "penyetuju tahap itu"},
        {"jenis": "dokumen"} if _tid == "bayar_tagihan" else _HK1, _persetujuan(_tid), _menu,
        nasib=_nasib_persetujuan))

KATALOG: dict[str, TitikAksi] = {t.id: t for t in KATALOG_LIST}


def titik(tid: str) -> Optional[TitikAksi]:
    return KATALOG.get(tid)
