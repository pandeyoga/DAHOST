"""core/scan_out.py — SCAN KELUAR PENJUALAN harian (keputusan owner K15, 2026-11-02).

Gudang men-scan setiap pcs barang jadi yang keluar untuk pembeli marketplace. Scan TIDAK
ditautkan ke nomor pesanan. Modul ini tipis: semua mesin yang dipakai SUDAH ADA.

  * kode → master FG       : `core.scan_resolver.resolve(expect=("fg",))` (barcode = SKU, QR label FG)
  * tanpa scan (10 Nov)    : `pick()` — barang dipilih dari daftar cari (`core.fg_pick.search`), tiap
                             barang lewat `scan(material_id=…)`; baris bertanda `tanpa_scan` (bukan merah)
  * stok keluar/kembali    : `core.stock_service.issue/add` (atomik, ledger `ref.type=mp_scan_out*`)
  * nilai keluar           : `core.fg_cost_layers.issue_wac` (qty × WAC saat scan, komponen dibekukan)
  * nilai kembali (batal)  : `core.fg_cost_layers.push_layer` / `reverse_receipt` (rumus WAC yang sama)
  * jurnal HPP             : `routes.rahaza_posting._create_posted_je` dengan pola HPP penjualan
                             langsung (Dr 5-1000/5-2000/5-3500 per komponen / Cr 1-1404), profil
                             posting `cogs_marketplace_scan` (bisa dipetakan ulang Keuangan)
  * notifikasi             : `utils.notif_unified.notif_insert` (kind "Perlu Tindakan")
  * jadwal                 : `utils.scheduler.JOB_REGISTRY` (tutup otomatis 23:55 WIB)

KONTRAK bersama paket opname (K9) — koleksi `wh_scan_out_sheets`:
    {id, date: 'YYYY-MM-DD' (WIB), location_id, status: 'open' | 'closed', ...}
Opname suatu lokasi tidak boleh disetujui selama ada lembar `status != 'closed'` untuk
lokasi & tanggal itu (lihat :func:`sheets_still_open`). Status antara `closing` dipakai
sesaat ketika Tutup Hari berjalan — pembaca kontrak cukup memeriksa `!= 'closed'`.
2026-11-06 (Tahap 2): kontrak ditambah — baris `wh_scan_out_lines` berstatus `failed` / `pending`
(antrean kirim ulang, lihat :func:`retry_queue`) di lokasi itu dengan `date` ≤ tanggal hitung juga
menahan approve opname, karena stoknya belum pasti terpotong.

Aturan yang dipegang:
  1. Satu lembar per (tanggal WIB, lokasi); dibuat otomatis saat scan pertama hari itu.
     Scan setelah lembar ditutup membuka lembar ke-2 hari yang sama (`seq`).
  2. Setiap scan punya `client_scan_id` (UUID perangkat) yang UNIK → kirim ulang jaringan /
     klik dobel tidak pernah memotong stok dua kali. Tiap langkah (stok, nilai) juga
     dicek ulang dari jejaknya (ledger / konsumsi / lapisan) sehingga proses yang terputus
     bisa dilanjutkan tanpa dobel.
  3. Stok kurang TETAP DITERIMA (jawaban owner) → baris bertanda merah `negative_stock`;
     baris stok minus ikut pengingat harian stok minus (`core.negative_stock_reminder`).
  4. Kode tak dikenal / barang klien maklon / baris karantina → DITOLAK tanpa efek stok,
     dicatat di daftar merah (`wh_scan_out_rejects`).
  5. Jurnal HPP baru lahir saat Tutup Hari: SATU jurnal per lembar, idempoten
     (`source_ref = skp:<id lembar>`), nilai = Σ WAC baris aktif (scan − batal kirim).
  6. Nota Portal Penjualan TIDAK di-scan ulang dan TIDAK dihitung di angka scan; laporan
     menampilkannya terpisah sebagai pembanding.
  7. Langkah 2 (potong stok otomatis dari impor Seller Center) tidak boleh menyala
     bersama scan keluar (stok terpotong dua kali) — :func:`langkah2_guard`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from core.stock_rbac import DISPOSE_ROLES
from utils.waktu import wib_date_str

logger = logging.getLogger(__name__)

# ── koleksi ──────────────────────────────────────────────────────────────────
SHEETS = "wh_scan_out_sheets"        # KONTRAK bersama paket opname (K9)
LINES = "wh_scan_out_lines"
REJECTS = "wh_scan_out_rejects"
CONTROLS = "wh_scan_out_controls"
SETTINGS = "wh_scan_out_settings"

# ── jejak (ref.type di ledger stok, konsumsi WAC, lapisan biaya) ─────────────
REF_SCAN = "mp_scan_out"                     # scan keluar
REF_SCAN_VOID = "mp_scan_out_void"           # batal baris scan (stok kembali)
REF_CANCEL = "mp_scan_out_batal_kirim"       # paket batal sebelum diambil kurir (stok kembali)
REF_CANCEL_VOID = "mp_scan_out_batal_void"   # batal baris "batal kirim" (stok keluar lagi)

KIND_SCAN = "scan"
KIND_CANCEL = "batal_kirim"
KINDS = (KIND_SCAN, KIND_CANCEL)
KIND_LABELS = {KIND_SCAN: "Keluar", KIND_CANCEL: "Batal kirim"}

# 2026-11-10 (owner) — barang DIPILIH dari daftar cari, bukan di-scan (`scan(material_id=…)`, `pick`).
VIA_PICK = "tanpa_scan"
MAX_PICK_ITEMS = 100                # produk per sekali simpan "Pilih tanpa scan"

# ── posting ─────────────────────────────────────────────────────────────────
POSTING_EVENT = "cogs_marketplace_scan"
# Peran profil yang dibaca mesin ini (didaftarkan di core/coa_bindings.PROFILE_ROLE_TABLES).
PROFILE_ROLES = {POSTING_EVENT: {"material": "debit_cogs_material", "labor": "debit_cogs_labor",
                                 "overhead": "debit_cogs_overhead", "fg": "credit_fg_inventory"}}
COMP_LABELS = (("material", "Bahan"), ("labor", "Upah"), ("overhead", "Overhead"))

# ── peran (SSOT core/stock_rbac — tidak disalin) ─────────────────────────────
SCAN_ROLES = list(DISPOSE_ROLES)
# Tutup Hari & batalkan baris orang lain: penanggung jawab packing/gudang (bukan tim packing).
SUPERVISE_ROLES = [r for r in DISPOSE_ROLES if r not in ("tim_packing", "admin_aksesoris")]

FG_META = {"inventory_category": "fg_internal", "ownership": "cv_da", "material_type": "fg", "unit": "pcs"}
SELLABLE_CATEGORIES = (None, "", "fg_internal", "finished_goods")
MAX_MULTIPLIER = 500
CLAIM_STALE_SECONDS = 30            # klaim proses baris dianggap putus setelah ini
CLOSING_STALE_SECONDS = 300         # status `closing` yang tertinggal (proses mati) boleh diambil alih
DEFAULT_SETTINGS = {"control_gap_pcs": 5, "control_gap_pct": 5.0, "control_days": 7}

# ── Langkah 2 (potong stok otomatis dari impor) ─────────────────────────────
# 2026-11-02 — DIUKUR: tidak ada setelan/toggle "Langkah 2" di kode. Impor Seller Center
# selalu `stock_reserved=False` (routes/marketing_data_import.py) dan Fulfillment menolak
# pesanan impor (K6). Kunci setelan di bawah adalah nama yang DICADANGKAN: penulisan setelan
# ini ke ON ditolak (routes/dewi_system_config.py) dan implementasi Langkah 2 kelak WAJIB
# memanggil :func:`langkah2_guard` sebelum memotong stok.
LANGKAH2_CONFIG_KEY = "marketplace_import_stock_deduct"
LANGKAH2_BLOCK_MSG = (
    "Langkah 2 (potong stok otomatis dari impor Seller Center) TIDAK BOLEH dinyalakan: barang "
    "marketplace sudah dipotong stoknya lewat Scan Keluar Penjualan oleh gudang (keputusan owner "
    "K15). Menyalakan keduanya memotong stok dan HPP dua kali. Impor tetap rekap omzet + kontrol "
    "pcs (Gudang → Scan Keluar Penjualan → Kontrol vs Impor).")


class ScanOutError(Exception):
    """Kesalahan yang ditampilkan apa adanya ke layar (status HTTP + pesan)."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


def _f(v, d: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else float(d)
    except (TypeError, ValueError):
        return float(d)


def _r2(v) -> float:
    return round(_f(v), 2)


def _actor(user: Optional[dict]) -> dict:
    u = user or {}
    return {"id": str(u.get("id") or ""), "name": u.get("name") or u.get("email") or "system",
            "email": u.get("email") or "", "role": (u.get("role") or "").lower()}


def _aware(dt):
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def today_str() -> str:
    return wib_date_str()   # tanggal kalender WIB (SSOT utils.waktu)


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on", "ya")
    return bool(v)


# ══════════════════════════════════════════════════════════════════════════════
# LANGKAH 2 — saling meniadakan dengan scan keluar
# ══════════════════════════════════════════════════════════════════════════════
def langkah2_guard(key: str, value) -> Optional[str]:
    """Pesan penolakan bila penulisan setelan menyalakan Langkah 2; None bila boleh."""
    if str(key or "").strip() == LANGKAH2_CONFIG_KEY and _truthy(value):
        return LANGKAH2_BLOCK_MSG
    return None


async def langkah2_status(db) -> dict:
    """Untuk banner layar: apakah kunci Langkah 2 entah bagaimana tersimpan ON di DB."""
    doc = await db.dewi_system_config.find_one({"key": LANGKAH2_CONFIG_KEY}, {"_id": 0, "value": 1})
    on = bool(doc) and _truthy(doc.get("value"))
    return {"key": LANGKAH2_CONFIG_KEY, "enabled_in_db": on, "blocked": True,
            "message": LANGKAH2_BLOCK_MSG}


# ══════════════════════════════════════════════════════════════════════════════
# INDEKS
# ══════════════════════════════════════════════════════════════════════════════
_INDEXED: set = set()


async def ensure_indexes(db) -> None:
    """Indeks unik penjaga idempoten (sekali per proses per DB)."""
    key = id(db)
    if key in _INDEXED:
        return
    try:
        await db[SHEETS].create_index([("date", 1), ("location_id", 1), ("seq", 1)], unique=True,
                                      name="uniq_date_loc_seq")
        await db[SHEETS].create_index([("location_id", 1), ("status", 1), ("date", 1)])
        await db[SHEETS].create_index("id", unique=True)
        await db[LINES].create_index("client_scan_id", unique=True, name="uniq_client_scan_id")
        await db[LINES].create_index("id", unique=True)
        await db[LINES].create_index([("sheet_id", 1), ("status", 1)])
        await db[LINES].create_index([("date", 1), ("location_id", 1)])
        await db[LINES].create_index([("material_id", 1), ("location_id", 1), ("date", 1)])
        await db[REJECTS].create_index("client_scan_id", unique=True, name="uniq_reject_client_scan_id")
        await db[REJECTS].create_index([("date", 1), ("location_id", 1)])
        await db[CONTROLS].create_index("date", unique=True)
    except AttributeError:
        pass                              # DB palsu uji unit tanpa create_index
    except Exception:  # noqa: BLE001 — indeks gagal tidak boleh mematikan scan
        logger.exception("[scan-out] gagal membuat indeks")
        return
    _INDEXED.add(key)


# ══════════════════════════════════════════════════════════════════════════════
# LOKASI, TOKO, LEMBAR
# ══════════════════════════════════════════════════════════════════════════════
async def location_info(db, location_id: str, *, blocked: Optional[set] = None) -> dict:
    """Lokasi asal WAJIB dipilih (No.18a), harus ada, dan bukan lokasi karantina."""
    from core import location_resolver
    from core.catalog_stock import blocked_location_ids
    loc_id = (location_id or "").strip()
    if not loc_id:
        raise ScanOutError(400, "Pilih lokasi asal barang dulu (lokasi wajib dipilih).")
    if not await location_resolver.location_exists(db, loc_id):
        raise ScanOutError(400, "Lokasi asal tidak ditemukan di Struktur Gudang.")
    if loc_id in (blocked if blocked is not None else await blocked_location_ids(db)):
        raise ScanOutError(400, "Lokasi ini lokasi karantina/terblokir — barangnya bukan stok jual.")
    disp = (await location_resolver.build_display_map(db, [loc_id])).get(loc_id) or {}
    return {"id": loc_id, "code": disp.get("code") or loc_id[:8], "name": disp.get("name") or ""}


async def store_info(db, account_id: str) -> Optional[dict]:
    """Toko/platform OPSIONAL per baris (hanya untuk analisis; jurnal tidak dipecah per toko)."""
    aid = (account_id or "").strip()
    if not aid:
        return None
    acc = await db.marketing_platform_accounts.find_one({"id": aid}, {"_id": 0})
    if not acc:
        raise ScanOutError(400, "Toko yang dipilih tidak ditemukan — pilih ulang atau kosongkan toko.")
    return {"account_id": aid, "account_name": acc.get("account_name") or acc.get("name") or "",
            "platform": acc.get("platform") or ""}


def sheet_number(day: str, loc_code: str, seq: int) -> str:
    base = f"SKP-{day.replace('-', '')}-{(loc_code or 'LOK').upper()}"
    return base if int(seq or 1) <= 1 else f"{base}-{int(seq)}"


# 2026-11-02: format nomor lembar terdaftar di katalog Penomoran Dokumen (tanpa nomor urut —
# tanggal lembar + kode lokasi sudah unik). Token tanggal = TANGGAL LEMBAR (WIB), bukan jam server.
SHEET_NUMBER_KEY = "wh_scan_out_sheets.number"


async def sheet_number_for(db, day: str, loc_code: str, seq: int) -> str:
    """Nomor lembar memakai format owner bila ada (cadangan = `sheet_number`); akhiran -n untuk seq > 1."""
    from utils.counters import resolve_master_code
    code = (loc_code or "LOK").upper()
    ctx = {"YYYY": day[:4], "YY": day[2:4], "MM": day[5:7], "DD": day[8:10], "LOKASI": code}
    base = await resolve_master_code(db, SHEET_NUMBER_KEY, ctx, sheet_number(day, code, 1))
    return base if int(seq or 1) <= 1 else f"{base}-{int(seq)}"


async def open_sheet(db, *, day: str, location: dict, actor: dict) -> dict:
    """Lembar TERBUKA (tanggal, lokasi); dibuat bila belum ada. Aman dari balapan (indeks unik)."""
    q = {"date": day, "location_id": location["id"], "status": "open"}
    for _ in range(4):
        cur = await db[SHEETS].find_one(q, {"_id": 0})
        if cur:
            return cur
        seq = await db[SHEETS].count_documents({"date": day, "location_id": location["id"]}) + 1
        doc = {"id": _uid(), "number": await sheet_number_for(db, day, location.get("code"), seq), "seq": seq,
               "date": day, "location_id": location["id"], "location_code": location.get("code") or "",
               "location_name": location.get("name") or "", "status": "open", "auto_closed": False,
               "totals": None, "je_id": None, "je_number": None, "post_error": None,
               "created_at": _now(), "created_by": actor.get("name"), "created_by_id": actor.get("id")}
        try:
            await db[SHEETS].insert_one(doc)
            doc.pop("_id", None)
            return doc
        except DuplicateKeyError:
            continue                      # permintaan lain baru saja membuatnya → baca ulang
    raise ScanOutError(409, "Lembar hari ini sedang dibuat oleh perangkat lain — scan ulang.")


async def sheets_still_open(db, *, location_ids=None, up_to_date: Optional[str] = None) -> list:
    """KONTRAK opname (K9): lembar yang BELUM ditutup (status != closed) — opname lokasi itu
    tidak boleh disetujui sebelum daftar ini kosong untuk tanggal hitungnya."""
    q: dict = {"status": {"$ne": "closed"}}
    if location_ids:
        q["location_id"] = {"$in": list(location_ids)}
    if up_to_date:
        q["date"] = {"$lte": up_to_date}
    return await db[SHEETS].find(q, {"_id": 0}).sort("date", 1).to_list(500)


# ══════════════════════════════════════════════════════════════════════════════
# RUMUS MURNI (diuji tanpa DB)
# ══════════════════════════════════════════════════════════════════════════════
def row_problem(row: Optional[dict], blocked_locs: set) -> Optional[str]:
    """Alasan baris stok lokasi ini BUKAN stok jual DA; None bila boleh dipotong.
    Baris yang belum ada = boleh (stok 0 → scan tetap diterima sebagai minus, jawaban owner)."""
    if not row:
        return None
    from core.fg_cost_layers import DA_OWNERSHIP
    if row.get("blocked") is True or row.get("quarantine") is True or row.get("location_id") in blocked_locs:
        return "baris stok di lokasi ini dikarantina/diblokir — bukan stok jual"
    if row.get("ownership") not in DA_OWNERSHIP:
        return "baris stok di lokasi ini milik pihak lain (titipan maklon), bukan stok DA"
    if row.get("inventory_category") not in SELLABLE_CATEGORIES:
        return f"kategori stok '{row.get('inventory_category')}' di lokasi ini bukan stok jual barang jadi"
    return None


def sellable_row_match(blocked_locs: set) -> dict:
    """Penyaring Mongo yang SAMA dengan ``row_problem(row) is None`` (2026-11-09, audit gudang G8).

    SATU aturan stok jual barang jadi DA untuk semua pembaca (Portal Penjualan, Fulfillment, daftar
    lokasi Scan Keluar, pengeluaran FG): bukan karantina/terblokir, milik DA, kategori kosong atau FG.
    Dulu pembaca lain menyaring `inventory_category == 'fg_internal'` saja ⇒ stok hasil pindah/Excel
    tanpa kategori tidak terlihat, sementara scan keluar tetap boleh memotongnya. Pemanggil membatasi
    ke material bertipe fg (baris tanpa kategori bisa milik bahan)."""
    from core.fg_cost_layers import DA_OWNERSHIP
    return {"blocked": {"$ne": True}, "quarantine": {"$ne": True},
            "location_id": {"$nin": sorted(blocked_locs or [])},
            "ownership": {"$in": list(DA_OWNERSHIP)},
            "inventory_category": {"$in": list(SELLABLE_CATEGORIES)}}


async def fg_material_ids(db, material_ids: Optional[list] = None) -> list:
    """id master barang jadi milik DA (bukan barang klien maklon, K14; dibatasi `material_ids` bila
    diberikan) — pasangan :func:`sellable_row_match`."""
    q: dict = {"type": "fg", "owner_type": {"$ne": "client"}}
    if material_ids is not None:
        q["id"] = {"$in": list(material_ids)}
    return [m["id"] async for m in db.rahaza_materials.find(q, {"_id": 0, "id": 1})]


def parse_multiplier(v) -> int:
    try:
        m = int(float(v if v not in (None, "") else 1))
    except (TypeError, ValueError):
        raise ScanOutError(400, "Pengali harus angka bulat (mis. 1, 6, 12).")
    if m < 1 or m > MAX_MULTIPLIER:
        raise ScanOutError(400, f"Pengali harus 1–{MAX_MULTIPLIER} pcs per scan.")
    return m


def line_sign(line: dict) -> int:
    return -1 if line.get("kind") == KIND_CANCEL else 1


def sum_lines(lines: list) -> dict:
    """Total neto baris AKTIF (scan − batal kirim) per komponen; Σ komponen = nilai."""
    out = {"pcs_out": 0, "pcs_cancel": 0, "pcs": 0, "lines": 0, "material": 0.0, "labor": 0.0,
           "overhead": 0.0, "value": 0.0, "uncosted_qty": 0, "negative_lines": 0, "skus": 0,
           "tanpa_scan_lines": 0, "tanpa_scan_pcs": 0}
    skus = set()
    for ln in lines or []:
        if ln.get("status") != "active":
            continue
        s, q = line_sign(ln), int(_f(ln.get("qty")))
        out["lines"] += 1
        if ln.get("tanpa_scan"):          # 2026-11-10: dipilih dari daftar cari (pcs neto, tanda audit)
            out["tanpa_scan_lines"] += 1
            out["tanpa_scan_pcs"] += s * q
        if s > 0:
            out["pcs_out"] += q
        else:
            out["pcs_cancel"] += q
        comps = ln.get("components") or {}
        for k in ("material", "labor", "overhead"):
            out[k] += s * _f(comps.get(k))
        out["uncosted_qty"] += s * int(_f(ln.get("uncosted_qty")))
        out["negative_lines"] += 1 if ln.get("negative_stock") else 0
        skus.add(ln.get("material_id"))
    out["pcs"] = out["pcs_out"] - out["pcs_cancel"]
    for k in ("material", "labor", "overhead"):
        out[k] = round(out[k], 2)
    out["value"] = round(out["material"] + out["labor"] + out["overhead"], 2)
    out["skus"] = len(skus - {None})
    return out


def build_cogs_lines(totals: dict, codes: dict, memo: str) -> list:
    """Baris jurnal HPP satu lembar — pola HPP penjualan langsung (komponen WAC):
    nilai neto positif ⇒ Dr HPP per komponen / Cr persediaan FG; neto negatif (batal kirim >
    scan) ⇒ arah sebaliknya. Seimbang karena kredit/debit FG = Σ komponen yang sudah dibulatkan."""
    lines = []
    for comp, label in COMP_LABELS:
        a = _r2(totals.get(comp))
        if a > 0:
            lines.append({"account_code": codes[comp], "debit": a, "credit": 0,
                          "description": f"{memo} - {label}"})
        elif a < 0:
            lines.append({"account_code": codes[comp], "debit": 0, "credit": -a,
                          "description": f"{memo} - {label} (batal kirim)"})
    v = round(sum(_r2(totals.get(c)) for c, _ in COMP_LABELS), 2)
    if v > 0:
        lines.append({"account_code": codes["fg"], "debit": 0, "credit": v,
                      "description": f"{memo} - Persediaan Barang Jadi"})
    elif v < 0:
        lines.append({"account_code": codes["fg"], "debit": -v, "credit": 0,
                      "description": f"{memo} - Persediaan Barang Jadi (batal kirim)"})
    return lines


BASIS_SHIP, BASIS_RTS, BASIS_ORDER = "kirim", "siap_kirim", "pesanan"
# Status pesanan yang BELUM diatur kirim (Shopee "Perlu Dikirim" = paid). Tanpa tanggal kirim/siap kirim
# pesanan ini belum tentu keluar gudang hari itu → tidak ikut kontrol (2026-11-09, audit gudang G12).
NOT_ARRANGED_STATUSES = ("new", "paid", "unpaid", "pending")


def order_day(order: dict) -> tuple:
    """(tanggal 'YYYY-MM-DD', basis) satu pesanan impor untuk kontrol pcs.

    2026-11-09 (audit gudang G12, keputusan ★): tanggal KIRIM (`shipped_at`, Impor B/C) → "Waktu
    Pengiriman Diatur" (`rts_at`, ekspor Shopee — paket siap diambil kurir) → tanggal pesanan. Dulu
    ekspor Shopee yang tidak punya tanggal kirim selalu jatuh ke tanggal pesanan ⇒ pesanan malam yang
    dikirim besok membuat selisih harian semu. Semua jam dinding WIB platform → tanggalnya apa adanya
    (`core.marketing_daily_rollup.order_date_key`, aturan rekap harian)."""
    from core.marketing_daily_rollup import order_date_key
    k = order_date_key(order.get("shipped_at"))
    if k:
        return k, BASIS_SHIP
    k = order_date_key(order.get("rts_at"))
    if k:
        return k, BASIS_RTS
    return order_date_key(order.get("order_date")), BASIS_ORDER


def order_counts(order: dict) -> bool:
    """Pesanan ikut kontrol? Batal TIDAK, kecuali batal SETELAH dikirim (paketnya sempat keluar
    gudang dan sudah di-scan; kembalinya lewat retur K1). 2026-11-09 (G12): pesanan yang belum diatur
    kirim (baru/perlu dikirim tanpa tanggal kirim/siap kirim) TIDAK dihitung."""
    st = (order.get("status") or "").lower()
    if st == "cancelled":
        return bool(order.get("shipped_at"))
    if st in NOT_ARRANGED_STATUSES and not (order.get("shipped_at") or order.get("rts_at")):
        return False
    return True


def is_manual_order(order: dict) -> bool:
    """Pesanan input layar (Order Terpadu), bukan hasil impor Seller Center (aturan `fulfillment.is_imported_order`)."""
    return not (order or {}).get("_import_session_id")


def order_pcs(order: dict) -> tuple:
    """(total pcs, {fg_material_id: pcs}, pcs item tak tertaut master FG)."""
    items = order.get("items") or []
    if not items:
        q = int(_f(order.get("quantity")))
        return q, {}, q
    total, by_mat, unlinked = 0, {}, 0
    for it in items:
        q = int(_f(it.get("quantity")))
        total += q
        mid = it.get("fg_material_id")
        if mid:
            by_mat[mid] = by_mat.get(mid, 0) + q
        else:
            unlinked += q
    return total, by_mat, unlinked


def gap_flag(import_pcs: float, scan_pcs: float, settings: dict) -> bool:
    """Selisih kontrol BESAR? |impor − scan| ≥ maks(ambang pcs, ambang % × pcs impor)."""
    gap = abs(_f(import_pcs) - _f(scan_pcs))
    lim = max(_f(settings.get("control_gap_pcs"), 5),
              _f(settings.get("control_gap_pct"), 5) / 100.0 * abs(_f(import_pcs)))
    return gap >= lim and gap > 0


def _days(end_day: str, n: int) -> list:
    end = date.fromisoformat(end_day)
    return [(end - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


# ══════════════════════════════════════════════════════════════════════════════
# SCAN
# ══════════════════════════════════════════════════════════════════════════════
def public_line(ln: Optional[dict]) -> Optional[dict]:
    if not ln:
        return ln
    return {k: v for k, v in ln.items() if k not in ("_id", "claim_at", "lock_id")}


async def _reject(db, *, csid: str, day: str, location: dict, raw: str, code: str, reason_code: str,
                  reason: str, actor: dict, multiplier: int, kind: str, store: Optional[dict],
                  tanpa_scan: bool = False) -> dict:
    doc = {"id": _uid(), "client_scan_id": csid, "date": day, "location_id": location["id"],
           "location_code": location.get("code"), "raw_code": str(raw or "")[:200], "code": code,
           "reason_code": reason_code, "reason": reason, "multiplier": multiplier, "kind": kind,
           "store": store, "operator_id": actor.get("id"), "operator_name": actor.get("name"),
           "at": _now(), "tanpa_scan": bool(tanpa_scan)}
    try:
        await db[REJECTS].insert_one(doc)
        doc.pop("_id", None)
    except DuplicateKeyError:
        doc = await db[REJECTS].find_one({"client_scan_id": csid}, {"_id": 0}) or doc
        return {"result": "rejected", "duplicate": True, "reject": doc}
    return {"result": "rejected", "duplicate": False, "reject": doc}


async def _resolve_picked(db, material_id: str) -> Optional[dict]:
    """Barang jadi yang DIPILIH dari daftar cari (tanpa scan) → bentuk hasil resolver yang sama.
    Hanya master barang jadi; master lain/tak dikenal = None (ditolak seperti kode tak dikenal)."""
    mat = await db.rahaza_materials.find_one({"id": material_id, "type": "fg"}, {"_id": 0})
    if not mat:
        return None
    code = mat.get("code") or mat.get("sku") or ""
    return {"tipe": "fg", "id": mat["id"], "kode": code, "sku": code, "via": VIA_PICK, "_doc": mat}


async def scan(db, *, location_id: str, raw_code: str, client_scan_id: str, multiplier=1,
               kind: str = KIND_SCAN, account_id: str = "", user: Optional[dict] = None,
               material_id: str = "") -> dict:
    """Satu scan: resolve kode → potong stok (atau kembalikan, untuk batal kirim) → nilai WAC.

    Idempoten per `client_scan_id`: scan yang sama dikirim ulang mengembalikan baris yang sama
    (`duplicate=True`) tanpa efek stok kedua.

    2026-11-10 (owner, "tanpa scan bisa dicari dan pilih banyak"): `material_id` diisi = barang
    DIPILIH dari daftar cari, bukan di-scan. Sesudah resolusi, jalurnya IDENTIK dengan scan (aturan
    tolak, lembar, stok, WAC, batal baris, Tutup Hari); barisnya hanya diberi tanda `tanpa_scan`
    (bukan `flags` — tidak masuk daftar merah, keputusan owner)."""
    await ensure_indexes(db)
    actor = _actor(user)
    csid = str(client_scan_id or "").strip()
    if not csid or len(csid) > 80:
        raise ScanOutError(400, "client_scan_id wajib (UUID dari perangkat, maks. 80 karakter).")
    prev = await db[LINES].find_one({"client_scan_id": csid}, {"_id": 0})
    if prev:
        return await _resume(db, prev, actor)
    prev_rej = await db[REJECTS].find_one({"client_scan_id": csid}, {"_id": 0})
    if prev_rej:
        return {"result": "rejected", "duplicate": True, "reject": prev_rej}
    if kind not in KINDS:
        raise ScanOutError(400, f"Jenis scan harus salah satu: {', '.join(KINDS)}.")
    qty = parse_multiplier(multiplier)
    from core.scan_resolver import normalize_code, resolve
    from core.production_qty_ledger import client_owner_of_material
    from core.catalog_stock import blocked_location_ids
    blocked = await blocked_location_ids(db)
    location = await location_info(db, location_id, blocked=blocked)
    store = await store_info(db, account_id)
    day = today_str()
    picked_id = str(material_id or "").strip()
    rej = None
    if picked_id:
        res = await _resolve_picked(db, picked_id)
        code = (res or {}).get("kode") or picked_id[:60]
        raw_code = raw_code or code
    else:
        code = normalize_code(raw_code)
        res = await resolve(db, raw_code, expect=("fg",)) if code else None
    if not code:
        rej = ("empty", "Kode kosong.")
    elif not res:
        rej = ("unknown_code", "Barang yang dipilih tidak ditemukan di master barang jadi." if picked_id
               else f"Kode '{code[:60]}' tidak dikenal sebagai SKU barang jadi.")
    else:
        mat = res["_doc"]
        if await client_owner_of_material(db, mat["id"]):
            rej = ("maklon", f"{res['kode']} barang milik klien maklon — bukan stok jual DA.")
        else:
            row = await db.rahaza_material_stock.find_one(
                {"material_id": mat["id"], "location_id": location["id"]}, {"_id": 0})
            why = row_problem(row, blocked)
            if why:
                rej = ("not_sellable_row", f"{res['kode']}: {why}.")
    if rej:
        return await _reject(db, csid=csid, day=day, location=location, raw=raw_code, code=code,
                             reason_code=rej[0], reason=rej[1], actor=actor, multiplier=qty,
                             kind=kind, store=store, tanpa_scan=bool(picked_id))

    mat = res["_doc"]
    sheet = await open_sheet(db, day=day, location=location, actor=actor)
    line = {"id": _uid(), "client_scan_id": csid, "sheet_id": sheet["id"], "sheet_number": sheet["number"],
            "date": day, "location_id": location["id"], "location_code": location.get("code"),
            "kind": kind, "qty": qty, "multiplier": qty, "raw_code": str(raw_code or "")[:200],
            "code": code, "via": res.get("via"), "material_id": mat["id"],
            "sku": mat.get("code") or mat.get("sku") or code, "name": mat.get("name") or "",
            "store": store, "operator_id": actor.get("id"), "operator_name": actor.get("name"),
            "scanned_at": _now(), "status": "pending", "claim_at": _now(), "flags": [],
            "negative_stock": False, "locked": False, "tanpa_scan": bool(picked_id)}
    try:
        await db[LINES].insert_one(line)
        line.pop("_id", None)
    except DuplicateKeyError:
        prev = await db[LINES].find_one({"client_scan_id": csid}, {"_id": 0})
        return await _resume(db, prev, actor)
    line = await _process(db, line, actor)
    line = await _rehome_if_closed(db, line, location, actor)
    return {"result": "accepted", "duplicate": False, "line": public_line(line)}


def parse_pick_items(items) -> list:
    """Isi "Pilih tanpa scan" → [{material_id, qty, client_scan_id}] (fungsi murni, semua galat sekaligus).

    Setiap produk membawa `client_scan_id` sendiri (dibuat layar saat produk dicentang) sehingga
    Simpan yang terkirim dua kali tidak memotong stok dua kali — aturan idempoten scan yang sama."""
    if not isinstance(items, list) or not items:
        raise ScanOutError(400, "Pilih minimal satu barang.")
    if len(items) > MAX_PICK_ITEMS:
        raise ScanOutError(400, f"Paling banyak {MAX_PICK_ITEMS} barang per sekali simpan — simpan bertahap.")
    out, errs, seen_csid, seen_mat = [], [], set(), set()
    for i, it in enumerate(items, start=1):
        it = it if isinstance(it, dict) else {}
        mid = str(it.get("material_id") or "").strip()
        csid = str(it.get("client_scan_id") or "").strip()
        label = str(it.get("code") or f"Barang ke-{i}")[:60]     # id mentah tidak pernah tampil ke staf
        if not mid:
            errs.append(f"Baris {i}: barang belum dipilih.")
            continue
        if mid in seen_mat:
            errs.append(f"{label}: dipilih dua kali — gabungkan jumlahnya di satu baris.")
            continue
        if not csid or len(csid) > 80:
            errs.append(f"{label}: id pilihan wajib (maks. 80 karakter) — muat ulang layar lalu pilih lagi.")
            continue
        if csid in seen_csid:
            errs.append(f"{label}: id pilihan kembar — muat ulang layar lalu pilih lagi.")
            continue
        try:
            qty = parse_multiplier(it.get("qty"))
        except ScanOutError:
            errs.append(f"{label}: jumlah harus angka bulat 1–{MAX_MULTIPLIER} pcs.")
            continue
        seen_mat.add(mid)
        seen_csid.add(csid)
        out.append({"material_id": mid, "qty": qty, "client_scan_id": csid})
    if errs:
        raise ScanOutError(400, " ".join(errs))
    return out


async def pick(db, *, location_id: str, items, kind: str = KIND_SCAN, account_id: str = "",
               user: Optional[dict] = None) -> dict:
    """"Pilih tanpa scan": banyak barang jadi sekaligus, SETIAP barang lewat :func:`scan` (jalur stok,
    nilai, dan lembar yang sama dengan scan). Lokasi/toko/jenis diperiksa sekali di depan; hasil per
    barang dikembalikan apa adanya (diterima / ditolak / gagal diproses → antrean kirim ulang server)."""
    await ensure_indexes(db)
    if kind not in KINDS:
        raise ScanOutError(400, f"Jenis scan harus salah satu: {', '.join(KINDS)}.")
    rows = parse_pick_items(items)
    await location_info(db, location_id)
    await store_info(db, account_id)
    results, accepted, rejected, failed = [], 0, 0, 0
    for it in rows:
        try:
            out = await scan(db, location_id=location_id, raw_code="", client_scan_id=it["client_scan_id"],
                             multiplier=it["qty"], kind=kind, account_id=account_id, user=user,
                             material_id=it["material_id"])
        except ScanOutError as e:
            failed += 1
            results.append({"result": "failed", "material_id": it["material_id"], "qty": it["qty"],
                            "client_scan_id": it["client_scan_id"], "error": e.message})
            continue
        if out.get("result") == "rejected":
            rejected += 1
        elif out.get("result") == "accepted":
            accepted += 1
        results.append({**out, "material_id": it["material_id"], "client_scan_id": it["client_scan_id"]})
    pcs = sum(int(_f((r.get("line") or {}).get("qty"))) for r in results if r.get("result") == "accepted")
    return {"accepted": accepted, "rejected": rejected, "failed": failed, "pcs": pcs, "results": results}


async def _claim(db, line: dict, from_status: str, to_status: str) -> bool:
    """Ambil hak memproses baris (atomik). Klaim yang lebih tua dari CLAIM_STALE boleh diambil alih."""
    stale = _now() - timedelta(seconds=CLAIM_STALE_SECONDS)
    q = {"id": line["id"], "status": from_status,
         "$or": [{"claim_at": None}, {"claim_at": {"$lt": stale}}]}
    res = await db[LINES].update_one(q, {"$set": {"status": to_status, "claim_at": _now()}})
    return bool(res.matched_count)


async def _resume(db, prev: dict, actor: dict) -> dict:
    """Scan dengan client_scan_id yang sudah tercatat (kirim ulang). Proses yang terputus
    (pending/failed) dilanjutkan dengan pengecekan jejak per langkah — tidak pernah dobel."""
    st = prev.get("status")
    if st in ("pending", "failed"):
        if await _claim(db, prev, st, "pending"):
            prev = await db[LINES].find_one({"id": prev["id"]}, {"_id": 0})
            line = await _process(db, prev, actor)
            loc = {"id": line["location_id"], "code": line.get("location_code"), "name": ""}
            line = await _rehome_if_closed(db, line, loc, actor)
            return {"result": "accepted", "duplicate": True, "resumed": True, "line": public_line(line)}
        return {"result": "processing", "duplicate": True, "line": public_line(prev)}
    return {"result": "accepted", "duplicate": True, "line": public_line(prev)}


def effective_at_of(line: dict, ref_type: str):
    """Jam KEJADIAN mutasi ledger (`ref.effective_at`, dibaca mesin opname K9 untuk hitung tanpa-kunci).

    2026-11-02: scan/batal-kirim = jam scan (`scanned_at`) — baris yang diproses ULANG (lanjutan setelah
    gagal) tetap memakai jam scan aslinya, bukan jam pemrosesan; pembatalan baris = jam batal (`voided_at`)."""
    if ref_type in (REF_SCAN_VOID, REF_CANCEL_VOID):
        return line.get("voided_at") or _now()
    return line.get("scanned_at") or _now()


async def _ledger_of(db, ref_type: str, line_id: str) -> Optional[dict]:
    return await db.rahaza_stock_ledger.find_one({"ref.type": ref_type, "ref.line_id": line_id}, {"_id": 0})


async def _stock_step(db, line: dict, *, ref_type: str, out: bool, actor: dict) -> float:
    """Mutasi stok baris (sekali saja — jejak ledger dicek dulu). Return qty baris stok sesudahnya."""
    from core import stock_service
    from core.stock_schema import read_qty
    led = await _ledger_of(db, ref_type, line["id"])
    if led:
        return _f(led.get("qty_after"))
    ref = {"type": ref_type, "line_id": line["id"], "sheet_id": line.get("sheet_id"),
           "client_scan_id": line.get("client_scan_id"), "sheet_number": line.get("sheet_number"),
           "effective_at": effective_at_of(line, ref_type)}
    meta = {**FG_META, "material_code": line.get("sku"), "material_name": line.get("name"),
            "location_code": line.get("location_code")}
    act = {"id": actor.get("id"), "name": actor.get("name"), "email": actor.get("email")}
    if out:
        row = await stock_service.issue(line["material_id"], line["location_id"], int(line["qty"]), ref=ref,
                                        actor=act, allow_negative=True, db=db, meta=meta)
    else:
        row = await stock_service.add(line["material_id"], line["location_id"], int(line["qty"]), meta=meta,
                                      ref=ref, actor=act, db=db)
    return read_qty(row)


async def _value_scan(db, line: dict, actor: dict) -> dict:
    """Nilai scan keluar = qty × WAC saat itu (`issue_wac`, sekali saja — jejak konsumsi dicek)."""
    from core import fg_cost_layers as fcl
    cons = await db[fcl.CONSUMPTIONS].find_one({"ref.type": REF_SCAN, "ref.line_id": line["id"]}, {"_id": 0})
    if cons:
        return {"cogs": _f(cons.get("cogs")), "unit_cost": _f(cons.get("unit_cost")),
                "components": cons.get("components") or {}, "uncosted_qty": int(_f(cons.get("uncosted_qty")))}
    return await fcl.issue_wac(db, material_id=line["material_id"], qty=int(line["qty"]),
                               ref={"type": REF_SCAN, "line_id": line["id"], "sheet_id": line.get("sheet_id"),
                                    "sku": line.get("sku")}, actor=actor)


async def _value_cancel(db, line: dict, actor: dict) -> dict:
    """Batal kirim: barang kembali ke stok jual senilai WAC SAAT INI (WAC tidak bergeser),
    lewat `push_layer` (rumus barang masuk yang sama dengan retur). Sekali saja."""
    from core import fg_cost_layers as fcl
    if line.get("value_frozen"):
        val = line["value_frozen"]
    else:
        st = await fcl.wac_state(db, line["material_id"], actor=actor)
        v = fcl.value_issue(int(line["qty"]), st["unit_cost"], st["components"])
        val = {"cogs": v["cogs"], "unit_cost": st["unit_cost"], "components": v["components"],
               "uncosted_qty": v["uncosted_qty"]}
        await db[LINES].update_one({"id": line["id"]}, {"$set": {"value_frozen": val}})
    done = await db[fcl.LAYERS].find_one({"batch.source": REF_CANCEL, "batch.receipt_id": line["id"]},
                                         {"_id": 0, "id": 1})
    if not done:
        await fcl.push_layer(db, material_id=line["material_id"], qty=int(line["qty"]),
                             unit_cost=val["unit_cost"], components=val["components"] or None,
                             ref={"type": REF_CANCEL, "receipt_id": line["id"],
                                  "receipt_code": line.get("sheet_number")}, actor=actor)
    return val


async def _prior_net_scans(db, line: dict, days: int = 7) -> int:
    """Pcs neto SKU ini yang keluar lewat scan di lokasi yang sama dalam N hari terakhir."""
    since = (date.fromisoformat(line["date"]) - timedelta(days=days)).isoformat()
    rows = await db[LINES].find({"material_id": line["material_id"], "location_id": line["location_id"],
                                 "status": "active", "date": {"$gte": since}}, {"_id": 0}).to_list(5000)
    return sum(line_sign(r) * int(_f(r.get("qty"))) for r in rows if r.get("id") != line["id"])


async def stock_elsewhere(db, material_id: str, location_id: str, limit: int = 5) -> list:
    """Lokasi LAIN yang masih memegang stok jual SKU ini (qty > 0), terbanyak dulu — [{location_id, code, qty}].
    Hanya informasi: tidak pernah melempar galat (scan sudah memotong stok saat fungsi ini dipanggil)."""
    try:
        from core import location_resolver
        from core.catalog_stock import blocked_location_ids
        blocked = await blocked_location_ids(db)
        rows = await db.rahaza_material_stock.find(
            {"material_id": material_id, "location_id": {"$ne": location_id}}, {"_id": 0}).to_list(200)
        rows = [r for r in rows if _f(r.get("qty")) > 0 and row_problem(r, blocked) is None]
        rows.sort(key=lambda r: -_f(r.get("qty")))
        rows = rows[:limit]
        disp = await location_resolver.build_display_map(db, [r["location_id"] for r in rows]) if rows else {}
        return [{"location_id": r["location_id"],
                 "code": (disp.get(r["location_id"]) or {}).get("code") or r.get("location_code") or "",
                 "name": (disp.get(r["location_id"]) or {}).get("name") or "", "qty": _f(r.get("qty"))}
                for r in rows]
    except Exception:  # noqa: BLE001
        logger.warning("[scan-out] cek stok lokasi lain gagal (%s)", material_id, exc_info=True)
        return []


def elsewhere_warning(line: dict, elsewhere: list) -> str:
    """Kalimat peringatan untuk petugas (fungsi murni)."""
    where = ", ".join(f"{e.get('code') or e.get('name') or '-'} ({e['qty']:g} pcs)" for e in elsewhere)
    return (f"Stok {line.get('sku') or ''} di lokasi ini kurang, tetapi ada di {where}. Scan tetap dicatat; "
            "bila barang diambil dari lokasi itu, batalkan baris ini lalu scan ulang dengan lokasi yang benar.")


async def _process(db, line: dict, actor: dict) -> dict:
    """Langkah efek satu baris (stok → nilai → aktif). Setiap langkah dicek dari jejaknya."""
    out = line.get("kind") != KIND_CANCEL
    try:
        stock_after = await _stock_step(db, line, ref_type=REF_SCAN if out else REF_CANCEL, out=out, actor=actor)
        val = await (_value_scan(db, line, actor) if out else _value_cancel(db, line, actor))
    except Exception as e:  # noqa: BLE001 — baris ditandai gagal; kirim ulang melanjutkan dari jejak
        logger.exception("[scan-out] baris %s gagal diproses", line.get("id"))
        await db[LINES].update_one({"id": line["id"], "status": "pending"},
                                   {"$set": {"status": "failed", "error": str(e)[:300], "claim_at": None}})
        raise ScanOutError(500, f"Scan gagal diproses: {e}. Scan ulang kode yang sama — tidak akan dobel.")
    flags = []
    negative = out and stock_after < 0
    elsewhere = []
    if negative:
        flags.append("stok_kurang")
        # 2026-11-09 (audit gudang G9, keputusan ★a): scan TETAP diterima (Stok Boleh Minus), tetapi petugas
        # diberi tahu bila SKU ini ada di lokasi lain — kemungkinan besar lokasi scan yang dipilih salah.
        elsewhere = await stock_elsewhere(db, line["material_id"], line["location_id"])
        if elsewhere:
            flags.append("stok_di_lokasi_lain")
    if int(_f(val.get("uncosted_qty"))) > 0:
        flags.append("tanpa_wac")
    if not out and await _prior_net_scans(db, line) < int(line["qty"]):
        flags.append("batal_tanpa_scan")
    comps = {k: _r2((val.get("components") or {}).get(k)) for k in ("material", "labor", "overhead")}
    upd = {"status": "active", "unit_cost": round(_f(val.get("unit_cost")), 4), "components": comps,
           "value": _r2(val.get("cogs")), "signed_value": _r2(val.get("cogs")) * (1 if out else -1),
           "uncosted_qty": int(_f(val.get("uncosted_qty"))), "basis": "wac", "stock_after": stock_after,
           "negative_stock": bool(negative), "flags": flags, "claim_at": None, "error": None,
           "processed_at": _now(), "stock_elsewhere": elsewhere,
           "warning": elsewhere_warning(line, elsewhere) if elsewhere else None}
    await db[LINES].update_one({"id": line["id"]}, {"$set": upd})
    line.update(upd)
    return line


async def _rehome_if_closed(db, line: dict, location: dict, actor: dict) -> dict:
    """Baris yang masuk SAAT lembarnya ditutup (tidak ikut jurnal) dipindah ke lembar terbuka
    berikutnya (tanggal sama) supaya nilainya tetap dibukukan di penutupan berikutnya.
    Lembar yang masih `closing` dibiarkan: penutupnya memindahkan baris tak terkunci sesudah
    status `closed` (atau, bila jurnal gagal, lembar kembali `open` bersama barisnya)."""
    cur = await db[LINES].find_one({"id": line["id"]}, {"_id": 0}) or line
    if cur.get("locked"):
        return cur
    sheet = await db[SHEETS].find_one({"id": cur.get("sheet_id")}, {"_id": 0, "status": 1})
    if (sheet or {}).get("status") != "closed":
        return cur
    if not location.get("code"):
        location = {**location, "code": cur.get("location_code") or ""}
    nxt = await open_sheet(db, day=cur["date"], location=location, actor=actor)
    await db[LINES].update_one({"id": cur["id"], "sheet_id": cur["sheet_id"], "locked": {"$ne": True}},
                               {"$set": {"sheet_id": nxt["id"], "sheet_number": nxt["number"],
                                         "rehomed_from": cur["sheet_id"]}})
    return await db[LINES].find_one({"id": cur["id"]}, {"_id": 0}) or cur


# ══════════════════════════════════════════════════════════════════════════════
# KOREKSI — batalkan baris sebelum Tutup Hari
# ══════════════════════════════════════════════════════════════════════════════
async def void_line(db, line_id: str, *, user: Optional[dict], reason: str = "",
                    may_void_others: bool = False) -> dict:
    """Salah scan sebelum tutup: stok kembali ke lokasi yang sama dan WAC kembali seperti
    sebelum scan (barang masuk senilai WAC baris itu). Baris "batal kirim" dibatalkan
    dengan mengeluarkan stoknya lagi (pembalik penerimaan, `reverse_receipt`)."""
    from core import fg_cost_layers as fcl
    actor = _actor(user)
    line = await db[LINES].find_one({"id": line_id}, {"_id": 0})
    if not line:
        raise ScanOutError(404, "Baris scan tidak ditemukan.")
    if line.get("status") == "voided":
        return {"ok": True, "already_voided": True, "line": public_line(line)}
    if line.get("status") not in ("active", "voiding"):
        raise ScanOutError(409, f"Baris berstatus '{line.get('status')}' tidak bisa dibatalkan.")
    if not may_void_others and line.get("operator_id") and line.get("operator_id") != actor.get("id"):
        raise ScanOutError(403, "Baris ini di-scan petugas lain — minta SPV/Admin Gudang membatalkannya.")
    sheet = await db[SHEETS].find_one({"id": line.get("sheet_id")}, {"_id": 0}) or {}
    if line.get("locked") or sheet.get("status") != "open":
        raise ScanOutError(409, "Lembar sudah ditutup (HPP sudah dijurnal) — baris tidak bisa dibatalkan. "
                                "Selisihnya dibereskan lewat opname.")
    if line.get("status") == "active":
        q = {"id": line_id, "status": "active", "locked": {"$ne": True}}
        res = await db[LINES].update_one(q, {"$set": {
            "status": "voiding", "claim_at": _now(), "void_reason": (reason or "").strip()[:200] or "salah scan",
            "voided_by": actor.get("name"), "voided_by_id": actor.get("id"), "voided_at": _now()}})
        if not res.matched_count:
            cur = await db[LINES].find_one({"id": line_id}, {"_id": 0}) or {}
            if cur.get("status") == "voided":
                return {"ok": True, "already_voided": True, "line": public_line(cur)}
            raise ScanOutError(409, "Lembar sedang ditutup / baris sedang diproses — muat ulang lalu coba lagi.")
    elif not await _claim(db, line, "voiding", "voiding"):
        raise ScanOutError(409, "Pembatalan baris ini sedang diproses perangkat lain.")
    line = await db[LINES].find_one({"id": line_id}, {"_id": 0})
    out = line.get("kind") != KIND_CANCEL
    try:
        # balik efek stok: scan → stok kembali; batal kirim → stok keluar lagi
        await _stock_step(db, line, ref_type=REF_SCAN_VOID if out else REF_CANCEL_VOID, out=not out, actor=actor)
        if out:
            done = await db[fcl.LAYERS].find_one({"batch.source": REF_SCAN_VOID, "batch.receipt_id": line_id},
                                                 {"_id": 0, "id": 1})
            if not done:
                await fcl.push_layer(db, material_id=line["material_id"], qty=int(line["qty"]),
                                     unit_cost=_f(line.get("unit_cost")),
                                     components=line.get("components") or None,
                                     ref={"type": REF_SCAN_VOID, "receipt_id": line_id,
                                          "receipt_code": line.get("sheet_number")}, actor=actor)
        elif not line.get("void_wac_done"):
            await fcl.reverse_receipt(db, material_id=line["material_id"], qty=int(line["qty"]),
                                      unit_cost=_f(line.get("unit_cost")),
                                      ref={"type": REF_CANCEL_VOID, "id": line_id}, actor=actor)
            await db[LINES].update_one({"id": line_id}, {"$set": {"void_wac_done": True}})
    except Exception as e:  # noqa: BLE001
        logger.exception("[scan-out] pembatalan baris %s gagal", line_id)
        await db[LINES].update_one({"id": line_id}, {"$set": {"claim_at": None, "error": str(e)[:300]}})
        raise ScanOutError(500, f"Pembatalan gagal: {e}. Ulangi — langkah yang sudah jalan tidak diulang.")
    await db[LINES].update_one({"id": line_id}, {"$set": {"status": "voided", "claim_at": None, "error": None}})
    return {"ok": True, "line": public_line(await db[LINES].find_one({"id": line_id}, {"_id": 0}))}


# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-06 (Tahap 2) — ANTREAN SCAN GAGAL DI SERVER (per lembar / petugas)
# ══════════════════════════════════════════════════════════════════════════════
# Dulu antrean "Kirim ulang" hanya hidup di memori layar: muat ulang / ganti HP = hilang, dan
# baris gagal di server (status `failed`) tidak terlihat siapa pun. Baris gagal SUDAH tersimpan
# di `wh_scan_out_lines`; sekarang itulah antreannya — dibaca per lembar & petugas, dikirim ulang
# memakai id barisnya (bukan ingatan layar), atau dibatalkan dengan membalik langkah yang sudah
# terjadi. Baris gagal TIDAK lagi dipindah ke lembar baru saat Tutup Hari (dulu setiap tutup
# melahirkan lembar terbuka baru berisi baris gagal itu ⇒ opname lokasi terkunci selamanya).
FAILED_STATUSES = ("failed", "pending")


def _is_stuck(line: dict) -> bool:
    """Baris gagal, atau `pending` yang klaim prosesnya sudah putus (> CLAIM_STALE_SECONDS)."""
    st = line.get("status")
    if st == "failed":
        return True
    if st != "pending":
        return False
    at = _aware(line.get("claim_at"))
    return not isinstance(at, datetime) or at < _now() - timedelta(seconds=CLAIM_STALE_SECONDS)


async def retry_queue(db, *, location_id: Optional[str] = None, operator_id: Optional[str] = None,
                      sheet_id: Optional[str] = None) -> list:
    """Baris scan yang gagal/terputus (antrean kirim ulang di server), lintas tanggal."""
    q: dict = {"status": {"$in": list(FAILED_STATUSES)}}
    if location_id:
        q["location_id"] = location_id
    if operator_id:
        q["operator_id"] = operator_id
    if sheet_id:
        q["sheet_id"] = sheet_id
    rows = await db[LINES].find(q, {"_id": 0}).sort("scanned_at", 1).to_list(500)
    return [public_line(r) for r in rows if _is_stuck(r)]


async def retry_line(db, line_id: str, *, user: Optional[dict] = None,
                     may_retry_others: bool = False) -> dict:
    """Kirim ulang SATU baris dari antrean server (langkah yang sudah jalan tidak diulang)."""
    actor = _actor(user)
    line = await db[LINES].find_one({"id": line_id}, {"_id": 0})
    if not line:
        raise ScanOutError(404, "Baris scan tidak ditemukan.")
    if not may_retry_others and line.get("operator_id") and line.get("operator_id") != actor.get("id"):
        raise ScanOutError(403, "Baris ini di-scan petugas lain — minta SPV/Admin Gudang mengirim ulang.")
    if line.get("status") not in FAILED_STATUSES:
        return {"result": "accepted", "duplicate": True, "line": public_line(line)}
    return await _resume(db, line, actor)


async def discard_failed_line(db, line_id: str, *, user: Optional[dict], reason: str = "",
                              may_void_others: bool = False) -> dict:
    """Batalkan baris GAGAL: langkah yang sempat terjadi dibalik (stok kembali / nilai WAC kembali),
    lalu baris berstatus `voided`. Dipakai bila kode itu memang salah scan atau gagal terus."""
    from core import fg_cost_layers as fcl
    actor = _actor(user)
    line = await db[LINES].find_one({"id": line_id}, {"_id": 0})
    if not line:
        raise ScanOutError(404, "Baris scan tidak ditemukan.")
    if line.get("status") == "voided":
        return {"ok": True, "already_voided": True, "line": public_line(line)}
    if not _is_stuck(line):
        raise ScanOutError(409, "Hanya baris yang gagal diproses yang bisa dibatalkan di sini.")
    if not may_void_others and line.get("operator_id") and line.get("operator_id") != actor.get("id"):
        raise ScanOutError(403, "Baris ini di-scan petugas lain — minta SPV/Admin Gudang membatalkannya.")
    if not await _claim(db, line, line["status"], "voiding"):
        raise ScanOutError(409, "Baris ini sedang diproses perangkat lain — coba lagi sebentar.")
    out = line.get("kind") != KIND_CANCEL
    try:
        if out:
            if await _ledger_of(db, REF_SCAN, line_id):
                await _stock_step(db, line, ref_type=REF_SCAN_VOID, out=False, actor=actor)
            cons = await db[fcl.CONSUMPTIONS].find_one({"ref.type": REF_SCAN, "ref.line_id": line_id}, {"_id": 0})
            done = await db[fcl.LAYERS].find_one({"batch.source": REF_SCAN_VOID, "batch.receipt_id": line_id},
                                                 {"_id": 0, "id": 1})
            if cons and not done:
                await fcl.push_layer(db, material_id=line["material_id"], qty=int(line["qty"]),
                                     unit_cost=_f(cons.get("unit_cost")), components=cons.get("components") or None,
                                     ref={"type": REF_SCAN_VOID, "receipt_id": line_id,
                                          "receipt_code": line.get("sheet_number")}, actor=actor)
        else:
            if await _ledger_of(db, REF_CANCEL, line_id):
                await _stock_step(db, line, ref_type=REF_CANCEL_VOID, out=True, actor=actor)
            layer = await db[fcl.LAYERS].find_one({"batch.source": REF_CANCEL, "batch.receipt_id": line_id},
                                                  {"_id": 0})
            if layer and not line.get("void_wac_done"):
                await fcl.reverse_receipt(db, material_id=line["material_id"], qty=int(line["qty"]),
                                          unit_cost=_f((line.get("value_frozen") or {}).get("unit_cost")),
                                          ref={"type": REF_CANCEL_VOID, "id": line_id}, actor=actor)
                await db[LINES].update_one({"id": line_id}, {"$set": {"void_wac_done": True}})
    except Exception as e:  # noqa: BLE001
        logger.exception("[scan-out] pembatalan baris gagal %s gagal", line_id)
        await db[LINES].update_one({"id": line_id}, {"$set": {"status": "failed", "claim_at": None,
                                                              "error": str(e)[:300]}})
        raise ScanOutError(500, f"Pembatalan gagal: {e}. Ulangi — langkah yang sudah jalan tidak diulang.")
    await db[LINES].update_one({"id": line_id}, {"$set": {
        "status": "voided", "claim_at": None, "error": None,
        "void_reason": (reason or "").strip()[:200] or "scan gagal dibatalkan",
        "voided_by": actor.get("name"), "voided_by_id": actor.get("id"), "voided_at": _now()}})
    return {"ok": True, "line": public_line(await db[LINES].find_one({"id": line_id}, {"_id": 0}))}


async def _retry_stuck_on_sheet(db, sheet_id: str, actor: dict) -> int:
    """Sebelum Tutup Hari: coba proses ulang baris gagal lembar ini (best-effort). Return sisa gagal."""
    left = 0
    for ln in await db[LINES].find({"sheet_id": sheet_id, "status": {"$in": list(FAILED_STATUSES)}},
                                   {"_id": 0}).to_list(1000):
        if not _is_stuck(ln):
            continue
        try:
            if await _claim(db, ln, ln["status"], "pending"):
                cur = await db[LINES].find_one({"id": ln["id"]}, {"_id": 0})
                await _process(db, cur, actor)
                continue
        except Exception:  # noqa: BLE001 — tetap gagal: kembali ke antrean, tutup hari jalan terus
            await db[LINES].update_one({"id": ln["id"], "status": "pending"},
                                       {"$set": {"status": "failed", "claim_at": None}})
        left += 1
    return left


# ══════════════════════════════════════════════════════════════════════════════
# TUTUP HARI — satu jurnal HPP per lembar
# ══════════════════════════════════════════════════════════════════════════════
async def post_sheet_cogs(db, sheet: dict, totals: dict, user: dict) -> dict:
    """Jurnal HPP satu lembar (idempoten `skp:<id>`). Akun dari profil `cogs_marketplace_scan`."""
    from routes.rahaza_posting import _create_posted_je, _find_existing_je, cogs_basis_label, get_mapping
    source_ref = f"skp:{sheet['id']}"
    existing = await _find_existing_je(db, POSTING_EVENT, source_ref)
    if existing:
        return {"ok": True, "je_id": existing["id"], "je_number": existing.get("je_number"), "already_posted": True}
    mapping = await get_mapping(db, POSTING_EVENT)
    roles = PROFILE_ROLES[POSTING_EVENT]
    codes = {k: mapping.get(r) for k, r in roles.items()}
    missing = [f"{POSTING_EVENT}.{r}" for k, r in roles.items() if not codes[k]]
    if missing:
        return {"ok": False, "reason": "mapping_missing",
                "error": f"Profil posting belum lengkap ({', '.join(missing)}) — lengkapi di Keuangan → Profil Posting."}
    memo = (f"HPP Penjualan Marketplace (scan) {sheet['number']} · {totals['pcs']} pcs · "
            f"basis {cogs_basis_label('wac')}")
    lines = build_cogs_lines(totals, codes, memo)
    return await _create_posted_je(db, date.fromisoformat(sheet["date"]), memo[:200], POSTING_EVENT,
                                   source_ref, lines, user or {})


async def close_sheet(db, sheet_id: str, *, user: Optional[dict] = None, auto: bool = False) -> dict:
    """Tutup Hari: kunci baris aktif → satu jurnal HPP → lembar `closed`. Idempoten.
    Jurnal gagal (periode tutup / profil kosong) ⇒ lembar & baris kembali terbuka + alasan dicatat."""
    from utils.notif_unified import resolve_for_source
    actor = _actor(user)
    sheet = await db[SHEETS].find_one({"id": sheet_id}, {"_id": 0})
    if not sheet:
        raise ScanOutError(404, "Lembar scan tidak ditemukan.")
    if sheet.get("status") == "closed":
        return {"ok": True, "already_closed": True, "sheet": sheet}
    token = _uid()
    res = await db[SHEETS].update_one({"id": sheet_id, "status": "open"}, {"$set": {
        "status": "closing", "closing_token": token, "closing_at": _now()}})
    if not res.matched_count:
        stale = _now() - timedelta(seconds=CLOSING_STALE_SECONDS)
        res = await db[SHEETS].update_one(
            {"id": sheet_id, "status": "closing", "closing_at": {"$lt": stale}},
            {"$set": {"closing_token": token, "closing_at": _now()}})
        if not res.matched_count:
            cur = await db[SHEETS].find_one({"id": sheet_id}, {"_id": 0}) or {}
            if cur.get("status") == "closed":
                return {"ok": True, "already_closed": True, "sheet": cur}
            raise ScanOutError(409, "Lembar ini sedang ditutup oleh proses lain — tunggu sebentar lalu muat ulang.")
    # 2026-11-06 (Tahap 2): baris gagal lembar ini dicoba ulang dulu supaya ikut jurnal hari ini;
    # yang tetap gagal TINGGAL di lembar ini sebagai antrean kirim ulang (tidak dipindah).
    still_failed = await _retry_stuck_on_sheet(db, sheet_id, actor)
    # kunci baris aktif: sesudah ini batal baris ditolak dan scan baru masuk lembar berikutnya
    await db[LINES].update_many({"sheet_id": sheet_id, "status": "active", "locked": {"$ne": True}},
                                {"$set": {"locked": True, "lock_id": token}})
    lines = await db[LINES].find({"sheet_id": sheet_id, "status": "active", "locked": True},
                                 {"_id": 0}).to_list(100000)
    totals = sum_lines(lines)
    je = {"ok": True, "je_id": None, "je_number": None, "skipped": "nilai 0 — tanpa jurnal"}
    if abs(totals["value"]) >= 0.01:
        try:
            je = await post_sheet_cogs(db, sheet, totals, actor)
        except Exception as e:  # noqa: BLE001
            logger.exception("[scan-out] jurnal lembar %s gagal", sheet_id)
            je = {"ok": False, "error": str(e)}
    if not je.get("ok"):
        err = je.get("error") or je.get("reason") or "jurnal gagal"
        # semua baris terkunci lembar ini dibuka lagi (termasuk kunci penutup lama yang mati)
        await db[LINES].update_many({"sheet_id": sheet_id, "locked": True},
                                    {"$set": {"locked": False, "lock_id": None}})
        await db[SHEETS].update_one({"id": sheet_id, "closing_token": token}, {"$set": {
            "status": "open", "post_error": err, "post_error_at": _now(), "closing_token": None}})
        raise ScanOutError(409, f"Tutup Hari {sheet['number']} gagal: {err}")
    upd = {"status": "closed", "totals": totals, "je_id": je.get("je_id"), "je_number": je.get("je_number"),
           "je_note": je.get("skipped"), "auto_closed": bool(auto), "closed_at": _now(),
           "closed_by": "sistem (otomatis 23:55 WIB)" if auto else actor.get("name"),
           "closed_by_id": None if auto else actor.get("id"), "post_error": None, "closing_token": None}
    await db[SHEETS].update_one({"id": sheet_id}, {"$set": upd})
    sheet.update(upd)
    # baris yang lolos masuk saat penutupan (tidak terkunci) → lembar berikutnya.
    # 2026-11-06 (Tahap 2): baris GAGAL tidak ikut dipindah (dulu tiap tutup melahirkan lembar
    # terbuka baru berisi baris gagal ⇒ opname lokasi terkunci selamanya). Baris gagal tetap di
    # antrean server; begitu berhasil dikirim ulang, ia pindah ke lembar terbuka berikutnya.
    loc = {"id": sheet["location_id"], "code": sheet.get("location_code"), "name": sheet.get("location_name")}
    strays = [ln for ln in await db[LINES].find(
        {"sheet_id": sheet_id, "locked": {"$ne": True}, "status": {"$in": ["pending", "active"]}},
        {"_id": 0}).to_list(1000) if not _is_stuck(ln)]
    for ln in strays:
        await _rehome_if_closed(db, ln, loc, actor)
    if still_failed:
        await db[SHEETS].update_one({"id": sheet_id}, {"$set": {"failed_lines": still_failed}})
        sheet["failed_lines"] = still_failed
    try:
        await resolve_for_source(db, source_id=sheet_id)
    except Exception:  # noqa: BLE001
        logger.warning("[scan-out] penutupan notifikasi lembar %s gagal", sheet_id, exc_info=True)
    return {"ok": True, "sheet": sheet, "je": je, "moved_lines": len(strays), "failed_lines": still_failed}


async def auto_close(db, *, up_to: Optional[str] = None, before: Optional[str] = None) -> dict:
    """Tutup otomatis semua lembar terbuka bertanggal ≤ `up_to` (job 23:55 WIB) atau < `before`
    (job pagi: susulan bila 23:55 terlewat). Kegagalan per lembar dicatat, tidak menghentikan lainnya."""
    q: dict = {"status": "open"}
    if up_to:
        q["date"] = {"$lte": up_to}
    if before:
        q["date"] = {"$lt": before}
    out = {"closed": [], "failed": []}
    for sh in await db[SHEETS].find(q, {"_id": 0}).sort("date", 1).to_list(1000):
        try:
            r = await close_sheet(db, sh["id"], user=None, auto=True)
            out["closed"].append({"number": sh["number"], "je_number": (r.get("je") or {}).get("je_number")})
        except ScanOutError as e:
            out["failed"].append({"number": sh["number"], "error": e.message})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# LAPORAN HARIAN & KONTROL VS IMPOR
# ══════════════════════════════════════════════════════════════════════════════
async def get_settings(db) -> dict:
    doc = await db[SETTINGS].find_one({"id": "default"}, {"_id": 0}) or {}
    return {**DEFAULT_SETTINGS, **{k: doc[k] for k in DEFAULT_SETTINGS if doc.get(k) is not None}}


async def save_settings(db, body: dict, user: Optional[dict]) -> dict:
    cur = await get_settings(db)
    try:
        pcs = int(_f(body.get("control_gap_pcs"), cur["control_gap_pcs"]))
        pct = round(_f(body.get("control_gap_pct"), cur["control_gap_pct"]), 2)
    except (TypeError, ValueError):
        raise ScanOutError(400, "Ambang harus angka.")
    if pcs < 1 or pcs > 100000 or pct < 0 or pct > 100:
        raise ScanOutError(400, "Ambang pcs minimal 1; ambang persen 0–100.")
    new = {"control_gap_pcs": pcs, "control_gap_pct": pct, "control_days": cur["control_days"]}
    if await db[SETTINGS].find_one({"id": "default"}, {"_id": 0, "id": 1}):
        await db[SETTINGS].update_one({"id": "default"}, {"$set": {
            **new, "updated_at": _now(), "updated_by": _actor(user).get("name")}})
    else:
        await db[SETTINGS].insert_one({"id": "default", **new, "updated_at": _now(),
                                       "updated_by": _actor(user).get("name")})
    return new


async def _import_orders(db, first: str, last: str) -> list:
    """Pesanan impor yang tanggal kirimnya (atau tanggal pesanannya, bila belum ada tanggal
    kirim) jatuh di [first, last]. Dua bentuk tanggal (datetime jam dinding & teks lama)."""
    d0 = datetime.fromisoformat(first).replace(tzinfo=timezone.utc)
    d1 = datetime.fromisoformat(last).replace(tzinfo=timezone.utc) + timedelta(days=1)
    s0, s1 = first, (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    no_ship = {"$in": [None, ""]}
    # 2026-11-09 (G12): basis kirim → siap kirim (`rts_at`) → pesanan (cermin :func:`order_day`)
    q = {"$or": [{"shipped_at": {"$gte": d0, "$lt": d1}}, {"shipped_at": {"$gte": s0, "$lt": s1}},
                 {"shipped_at": no_ship, "rts_at": {"$gte": d0, "$lt": d1}},
                 {"shipped_at": no_ship, "rts_at": {"$gte": s0, "$lt": s1}},
                 {"shipped_at": no_ship, "rts_at": no_ship, "order_date": {"$gte": d0, "$lt": d1}},
                 {"shipped_at": no_ship, "rts_at": no_ship, "order_date": {"$gte": s0, "$lt": s1}}]}
    proj = {"_id": 0, "id": 1, "order_id": 1, "status": 1, "shipped_at": 1, "rts_at": 1, "order_date": 1,
            "quantity": 1, "items.quantity": 1, "items.fg_material_id": 1, "account_id": 1,
            "account_name": 1, "platform": 1, "_import_session_id": 1}
    return await db.marketing_orders.find(q, proj).to_list(100000)


async def control(db, *, end_day: Optional[str] = None, days: Optional[int] = None,
                  sku_day: Optional[str] = None) -> dict:
    """Kontrol pcs: pesanan impor (tanggal kirim) vs pcs scan neto, per hari + kumulatif N hari.
    Tidak memotong stok dan tidak menjurnal — hanya pemicu tindakan (scan susulan / batal
    kirim / periksa sebelum opname). Nota Portal Penjualan TIDAK ikut kedua sisi."""
    settings = await get_settings(db)
    n = int(days or settings.get("control_days") or 7)
    n = max(1, min(n, 62))
    end_day = end_day or today_str()
    span = _days(end_day, n)
    sku_day = sku_day or end_day
    rows = {d: {"date": d, "import_pcs": 0, "import_pcs_ship": 0, "import_pcs_rts": 0, "import_pcs_order": 0,
                "import_orders": 0, "manual_pcs": 0, "unlinked_pcs": 0, "scan_out": 0, "scan_cancel": 0,
                "scan_pcs": 0} for d in span}
    imp_sku: dict = {}
    for o in await _import_orders(db, span[0], span[-1]):
        if not order_counts(o):
            continue
        d, basis = order_day(o)
        if d not in rows:
            continue
        total, by_mat, unl = order_pcs(o)
        r = rows[d]
        r["import_pcs"] += total
        r[{BASIS_SHIP: "import_pcs_ship", BASIS_RTS: "import_pcs_rts"}.get(basis, "import_pcs_order")] += total
        if is_manual_order(o):
            r["manual_pcs"] += total      # pesanan input layar (K15: ikut keluar lewat Scan Keluar)
        r["import_orders"] += 1
        r["unlinked_pcs"] += unl
        if d == sku_day:
            for mid, q in by_mat.items():
                imp_sku[mid] = imp_sku.get(mid, 0) + q
    scan_sku: dict = {}
    lines = await db[LINES].find({"date": {"$gte": span[0], "$lte": span[-1]}, "status": "active"},
                                 {"_id": 0}).to_list(200000)
    names: dict = {}
    for ln in lines:
        r = rows.get(ln.get("date"))
        if not r:
            continue
        q, s = int(_f(ln.get("qty"))), line_sign(ln)
        r["scan_out" if s > 0 else "scan_cancel"] += q
        if ln.get("date") == sku_day:
            scan_sku[ln["material_id"]] = scan_sku.get(ln["material_id"], 0) + s * q
            names[ln["material_id"]] = (ln.get("sku"), ln.get("name"))
    cum_imp = cum_scan = 0
    out_rows = []
    for d in span:
        r = rows[d]
        r["scan_pcs"] = r["scan_out"] - r["scan_cancel"]
        r["gap"] = r["import_pcs"] - r["scan_pcs"]
        cum_imp += r["import_pcs"]
        cum_scan += r["scan_pcs"]
        r["cum_import_pcs"], r["cum_scan_pcs"], r["cum_gap"] = cum_imp, cum_scan, cum_imp - cum_scan
        r["flag"] = gap_flag(r["import_pcs"], r["scan_pcs"], settings)
        out_rows.append(r)
    missing = [m for m in imp_sku if m not in names]
    if missing:
        for m in await db.rahaza_materials.find({"id": {"$in": missing}}, {"_id": 0, "id": 1, "code": 1,
                                                                              "name": 1}).to_list(5000):
            names[m["id"]] = (m.get("code"), m.get("name"))
    per_sku = []
    for mid in set(imp_sku) | set(scan_sku):
        sku, nm = names.get(mid, ("", ""))
        i, s = imp_sku.get(mid, 0), scan_sku.get(mid, 0)
        per_sku.append({"material_id": mid, "sku": sku or mid, "name": nm or "", "import_pcs": i,
                        "scan_pcs": s, "gap": i - s})
    per_sku.sort(key=lambda x: (-abs(x["gap"]), x["sku"]))
    last = out_rows[-1]
    cum_flag = gap_flag(last["cum_import_pcs"], last["cum_scan_pcs"], settings)
    return {"end_day": end_day, "days": n, "settings": settings, "rows": out_rows,
            "cumulative": {"import_pcs": last["cum_import_pcs"], "scan_pcs": last["cum_scan_pcs"],
                           "gap": last["cum_gap"], "flag": cum_flag},
            "sku_day": sku_day, "per_sku": per_sku,
            "data_notes": [
                "Pcs pesanan = Σ jumlah item pesanan menurut TANGGAL KIRIM (Impor B/C); bila belum ada, tanggal "
                "'Waktu Pengiriman Diatur' (siap kirim, ekspor Shopee); bila keduanya kosong, tanggal pesanan "
                "(kolom 'basis pesanan'). Pesanan input layar (manual) ikut dihitung dan ditandai terpisah.",
                "Pesanan batal tidak dihitung, kecuali batal setelah dikirim (paketnya sempat keluar). Pesanan "
                "yang belum diatur kirim (Baru / Perlu Dikirim tanpa tanggal kirim atau siap kirim) belum dihitung.",
                "Pcs scan = scan keluar − batal kirim (baris aktif). Nota Portal Penjualan tidak ikut kedua sisi.",
                "Selisih per SKU hanya untuk item impor yang tertaut master FG; sisanya 'tak tertaut'.",
                f"Ditandai merah bila |selisih| ≥ maks({settings['control_gap_pcs']} pcs, "
                f"{settings['control_gap_pct']}% pcs impor)."]}


async def _direct_sales_out(db, day: str) -> dict:
    """Nota Portal Penjualan yang keluar hari itu — PEMBANDING, tidak di-scan & tidak dijumlah
    ke pcs scan (nota sudah memotong stok & menjurnal HPP sendiri saat Konfirmasi)."""
    notes = await db.sales_direct_notes.find(
        {"sale_date": day, "status": {"$in": ["confirmed", "paid"]}}, {"_id": 0}).to_list(5000)
    per_sku: dict = {}
    for n in notes:
        for it in n.get("items") or []:
            k = it.get("material_id") or it.get("sku")
            row = per_sku.setdefault(k, {"material_id": it.get("material_id"), "sku": it.get("sku"),
                                         "name": it.get("name"), "pcs": 0, "notes": []})
            row["pcs"] += int(_f(it.get("qty")))
            if n.get("note_number") not in row["notes"]:
                row["notes"].append(n.get("note_number"))
    return {"notes": [{"note_number": n.get("note_number"), "customer_name": n.get("customer_name"),
                       "pcs": sum(int(_f(i.get("qty"))) for i in n.get("items") or []),
                       "cogs_total": n.get("cogs_total"), "cogs_je_number": n.get("cogs_je_number")}
                      for n in notes],
            "per_sku": sorted(per_sku.values(), key=lambda r: r["sku"] or ""),
            "pcs": sum(r["pcs"] for r in per_sku.values())}


async def _returns_received(db, day: str) -> list:
    """Retur yang DIPUTUSKAN gudang hari itu (alur K1) — stok kembali & HPP dibalik di sana."""
    from utils.waktu import to_wib, wib_day_bounds_utc
    lo, hi = wib_day_bounds_utc(date.fromisoformat(day))
    rows = await db.wh_returns.find({"status": {"$in": ["Resolved", "Reversed"]},
                                     "$or": [{"resolved_at": {"$gte": lo, "$lt": hi}},
                                             {"resolved_at": {"$gte": lo.isoformat(), "$lt": hi.isoformat()}}]},
                                    {"_id": 0}).to_list(5000)
    out = []
    for r in rows:
        at = r.get("resolved_at")
        if isinstance(at, str):
            try:
                at = datetime.fromisoformat(at.replace("Z", "+00:00"))
            except ValueError:
                at = None
        if not at or to_wib(at).date().isoformat() != day:
            continue
        out.append({"return_code": r.get("return_code"), "sku": r.get("sku_code"),
                    "name": r.get("product_name"), "qty": r.get("qty"), "action": r.get("action_taken"),
                    "restock_qty": r.get("restock_qty"), "condition": r.get("item_condition"),
                    "location": r.get("restock_location_code"), "status": r.get("status")})
    return out


async def daily_report(db, *, day: Optional[str] = None, location_id: Optional[str] = None) -> dict:
    """Laporan harian: per SKU, toko, petugas; pengecualian; nota Portal Penjualan & retur
    (pembanding); kontrol pcs impor vs scan (hari itu + kumulatif)."""
    day = day or today_str()
    q: dict = {"date": day}
    if location_id:
        q["location_id"] = location_id
    sheets = await db[SHEETS].find(q, {"_id": 0}).sort("seq", 1).to_list(200)
    lines = await db[LINES].find(q, {"_id": 0}).sort("scanned_at", 1).to_list(200000)
    active = [ln for ln in lines if ln.get("status") == "active"]
    totals = sum_lines(active)
    per_sku: dict = {}
    per_store: dict = {}
    per_op: dict = {}
    for ln in active:
        s, qty, val = line_sign(ln), int(_f(ln.get("qty"))), _f(ln.get("value"))
        k = ln["material_id"]
        r = per_sku.setdefault(k, {"material_id": k, "sku": ln.get("sku"), "name": ln.get("name"),
                                   "out": 0, "cancel": 0, "net": 0, "value": 0.0, "negative_lines": 0})
        r["out" if s > 0 else "cancel"] += qty
        r["net"] += s * qty
        r["value"] = round(r["value"] + s * val, 2)
        r["negative_lines"] += 1 if ln.get("negative_stock") else 0
        st = ln.get("store") or {}
        sk = st.get("account_id") or ""
        r2 = per_store.setdefault(sk, {"account_id": sk, "account_name": st.get("account_name") or "(tanpa toko)",
                                       "platform": st.get("platform") or "", "net": 0, "value": 0.0})
        r2["net"] += s * qty
        r2["value"] = round(r2["value"] + s * val, 2)
        ok = ln.get("operator_id") or ln.get("operator_name") or ""
        r3 = per_op.setdefault(ok, {"operator": ln.get("operator_name") or "-", "scans": 0, "net": 0,
                                    "tanpa_scan": 0, "net_tanpa_scan": 0})
        r3["scans"] += 1
        r3["net"] += s * qty
        if ln.get("tanpa_scan"):
            r3["tanpa_scan"] += 1
            r3["net_tanpa_scan"] += s * qty
    rejects = await db[REJECTS].find(q, {"_id": 0}).sort("at", 1).to_list(5000)
    nota = await _direct_sales_out(db, day)
    scanned = {r["material_id"] for r in per_sku.values() if r["out"] > 0}
    overlap = [r for r in nota["per_sku"] if r.get("material_id") in scanned]
    ctl = await control(db, end_day=day, sku_day=day)
    return {"date": day, "location_id": location_id or None,
            "sheets": [{k: s.get(k) for k in ("id", "number", "location_id", "location_code", "location_name",
                                              "status", "totals", "je_id", "je_number", "je_note", "auto_closed",
                                              "closed_at", "closed_by", "post_error")} for s in sheets],
            "summary": totals,
            "per_sku": sorted(per_sku.values(), key=lambda r: (-r["net"], r["sku"] or "")),
            "per_store": sorted(per_store.values(), key=lambda r: -r["net"]),
            "per_operator": sorted(per_op.values(), key=lambda r: -r["net"]),
            "voided": [public_line(ln) for ln in lines if ln.get("status") in ("voided", "voiding")],
            "negative": [public_line(ln) for ln in active if ln.get("negative_stock")],
            "flagged": [public_line(ln) for ln in active if ln.get("flags")],
            "tanpa_scan": [public_line(ln) for ln in active if ln.get("tanpa_scan")],
            "rejects": rejects,
            "direct_sales": {**nota, "overlap_with_scan": overlap,
                             "note": "Nota Portal Penjualan sudah memotong stok & menjurnal HPP sendiri — "
                                     "TIDAK di-scan dan TIDAK dijumlah ke pcs scan di atas."},
            "returns_received": await _returns_received(db, day),
            "control": {"today": ctl["rows"][-1], "cumulative": ctl["cumulative"], "days": ctl["days"],
                        "per_sku": ctl["per_sku"], "settings": ctl["settings"]}}


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFIKASI "PERLU TINDAKAN" & JOB TERJADWAL
# ══════════════════════════════════════════════════════════════════════════════
LINK_MODULE = "wh-scan-out"
SUBTYPE_OPEN = "wh_scan_out_sheet_open"
SUBTYPE_GAP = "wh_scan_out_control_gap"


def _target_roles() -> list:
    from utils.notif_unified import decider_roles
    return decider_roles("warehouse", SUPERVISE_ROLES)


async def _notified(db, ref: str) -> bool:
    return bool(await db.notifications.find_one({"source_ref": ref, "resolved_at": None}, {"_id": 0, "id": 1}))


async def notify_sheet_open(db, sheet: dict) -> Optional[str]:
    """Lembar tanggal lalu yang belum tertutup (biasanya karena jurnalnya gagal)."""
    from utils.notif_unified import notif_insert
    ref = f"skp_open:{sheet['id']}"
    if await _notified(db, ref):
        return None
    why = f" Alasan gagal terakhir: {sheet['post_error']}." if sheet.get("post_error") else ""
    return await notif_insert(
        db, type="rahaza", subtype=SUBTYPE_OPEN, severity="warning",
        title=f"Lembar scan keluar {sheet['number']} belum ditutup",
        body=(f"Lembar Scan Keluar Penjualan {sheet['number']} ({sheet['date']}, lokasi "
              f"{sheet.get('location_code') or '-'}) masih terbuka, jadi HPP hari itu belum dijurnal dan "
              f"opname lokasi ini belum bisa disetujui.{why} Buka Gudang → Scan Keluar Penjualan lalu Tutup Hari."),
        target_roles=_target_roles(), source_type=SHEETS, source_id=sheet["id"], source_ref=ref,
        kind="action", source_collection=SHEETS,
        resolve={"collection": SHEETS, "field": "status", "open": ["open", "closing"]},
        action={"label": "Tutup lembar", "target_menu": LINK_MODULE},
        meta={"link_module": LINK_MODULE, "date": sheet["date"], "sheet_number": sheet["number"]})


async def check_control(db, day: str) -> dict:
    """Simpan kontrol satu tanggal; selisih besar ⇒ notifikasi "Perlu Tindakan" sampai SPV
    menandainya sudah diperiksa (atau selisihnya hilang)."""
    from utils.notif_unified import notif_insert
    ctl = await control(db, end_day=day)
    row, cum = ctl["rows"][-1], ctl["cumulative"]
    flagged = bool(row["flag"] or cum["flag"])
    cur = await db[CONTROLS].find_one({"date": day}, {"_id": 0})
    snap = {"import_pcs": row["import_pcs"], "scan_pcs": row["scan_pcs"], "gap": row["gap"],
            "cum_import_pcs": cum["import_pcs"], "cum_scan_pcs": cum["scan_pcs"], "cum_gap": cum["gap"],
            "days": ctl["days"], "flag_day": row["flag"], "flag_cum": cum["flag"], "checked_at": _now()}
    status = "gap" if flagged else "ok"
    if cur and cur.get("status") == "reviewed" and abs(row["gap"]) <= abs(_f(cur.get("reviewed_gap"))) \
            and abs(cum["gap"]) <= abs(_f(cur.get("reviewed_cum_gap"))):
        status = "reviewed"
    if cur:
        await db[CONTROLS].update_one({"date": day}, {"$set": {**snap, "status": status}})
        cid = cur["id"]
    else:
        cid = _uid()
        await db[CONTROLS].insert_one({"id": cid, "date": day, **snap, "status": status})
    nid = None
    if status == "gap":
        ref = f"skp_gap:{cid}"
        if not await _notified(db, ref):
            nid = await notif_insert(
                db, type="rahaza", subtype=SUBTYPE_GAP, severity="warning",
                title=f"Selisih kontrol scan keluar {day}: {row['gap']:+d} pcs",
                body=(f"Pesanan impor (tanggal kirim {day}) {row['import_pcs']} pcs vs scan keluar "
                      f"{row['scan_pcs']} pcs → selisih {row['gap']:+d} pcs; kumulatif {ctl['days']} hari "
                      f"{cum['gap']:+d} pcs. Impor > scan = indikasi barang keluar tanpa scan (scan susulan "
                      "sebelum opname); scan > impor = scan dobel / paket batal tanpa 'Batal kirim'."),
                target_roles=_target_roles(), source_type=CONTROLS, source_id=cid, source_ref=ref,
                kind="action", source_collection=CONTROLS,
                resolve={"collection": CONTROLS, "field": "status", "open": ["gap"]},
                action={"label": "Periksa kontrol", "target_menu": LINK_MODULE, "filter": {"tab": "control"}},
                meta={"link_module": LINK_MODULE, "hub_tab": "control", "date": day})
    else:
        try:
            from utils.notif_unified import resolve_for_source
            await resolve_for_source(db, source_id=cid)
        except Exception:  # noqa: BLE001
            logger.warning("[scan-out] penutupan notifikasi kontrol %s gagal", day, exc_info=True)
    return {"date": day, "status": status, "notification_id": nid, **snap}


async def review_control(db, day: str, *, user: Optional[dict], note: str = "") -> dict:
    """SPV menandai selisih kontrol sudah diperiksa (notifikasinya tertutup)."""
    from utils.notif_unified import resolve_for_source
    cur = await db[CONTROLS].find_one({"date": day}, {"_id": 0})
    if not cur:
        cur = await check_control(db, day)
        cur = await db[CONTROLS].find_one({"date": day}, {"_id": 0})
    actor = _actor(user)
    await db[CONTROLS].update_one({"date": day}, {"$set": {
        "status": "reviewed", "reviewed_by": actor.get("name"), "reviewed_at": _now(),
        "review_note": (note or "").strip()[:300], "reviewed_gap": cur.get("gap"),
        "reviewed_cum_gap": cur.get("cum_gap")}})
    try:
        await resolve_for_source(db, source_id=cur["id"])
    except Exception:  # noqa: BLE001
        logger.warning("[scan-out] penutupan notifikasi kontrol %s gagal", day, exc_info=True)
    return await db[CONTROLS].find_one({"date": day}, {"_id": 0})


async def daily_check(db, *, today: Optional[str] = None) -> dict:
    """Job pagi: (1) tutup susulan lembar tanggal lalu (bila 23:55 terlewat), (2) "Perlu
    Tindakan" untuk lembar yang tetap terbuka, (3) kontrol pcs kemarin vs impor."""
    today = today or today_str()
    closed = await auto_close(db, before=today)
    notified = []
    for sh in await db[SHEETS].find({"status": {"$ne": "closed"}, "date": {"$lt": today}},
                                    {"_id": 0}).to_list(500):
        nid = await notify_sheet_open(db, sh)
        if nid:
            notified.append(sh["number"])
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    ctl = await check_control(db, yesterday)
    return {"today": today, "auto_closed": closed, "open_notified": notified, "control": ctl}


JOB_CLOSE = "wh_scan_out_auto_close"
JOB_CHECK = "wh_scan_out_daily_check"


async def job_auto_close():
    from routes.notifications_unified import _record_run

    async def _run(db):
        return await auto_close(db, up_to=today_str())
    return await _record_run(JOB_CLOSE, _run)


async def job_daily_check():
    from routes.notifications_unified import _record_run
    return await _record_run(JOB_CHECK, daily_check)


def register_scheduler_jobs() -> bool:
    """Daftarkan job ke `utils.scheduler.JOB_REGISTRY` (idempoten; dipanggil saat rute dimuat,
    sebelum `start_scheduler()`) — berkas penjadwal tidak diubah."""
    try:
        from utils.scheduler import JOB_REGISTRY
    except Exception:  # noqa: BLE001 — penjadwal opsional (uji unit tanpa apscheduler)
        logger.debug("utils.scheduler tidak tersedia — job scan keluar tidak dijadwalkan", exc_info=True)
        return False
    JOB_REGISTRY.setdefault(JOB_CLOSE, {
        "fn": job_auto_close,
        "description": ("Tutup otomatis lembar Scan Keluar Penjualan yang lupa ditutup (K15): satu jurnal "
                        "HPP per lembar (Dr HPP per komponen / Cr Persediaan Barang Jadi). Idempoten."),
        "cron": {"hour": 23, "minute": 55},
        "cron_label": "Setiap hari pukul 23:55 WIB",
    })
    JOB_REGISTRY.setdefault(JOB_CHECK, {
        "fn": job_daily_check,
        "description": ("Pemeriksaan pagi Scan Keluar Penjualan: tutup susulan lembar tanggal lalu, "
                        "\"Perlu Tindakan\" bila lembar kemarin belum tertutup atau selisih pcs scan vs "
                        "pesanan impor besar."),
        "cron": {"hour": 7, "minute": 40},
        "cron_label": "Setiap hari pukul 07:40 WIB",
    })
    return True
