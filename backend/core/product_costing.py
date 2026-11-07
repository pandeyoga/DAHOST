"""core.product_costing — SSOT **HPP per potong** (per model + size).

MENGAPA MODUL INI ADA (grounded, 2026-08-23)
--------------------------------------------
Sejak sesi #30 harga bahan **lahir dari pembelian** (rata-rata bergerak ditulis ke
`rahaza_materials.unit_cost` oleh `core/accessory_valuation.apply_receipt_cost`).
Tetapi HPP **produk jadi** belum pernah lahir dari angka itu:

  * `rahaza_materials` type='fg' → **321 dokumen, SEMUANYA `hpp: 0` & `hpp_source: 'none'`**.
  * Satu-satunya sumber HPP model adalah `core/product_master.resolve_hpp` =
    `hpp_rnd` (kalkulator R&D) → `base_hpp` (**KETIKAN MANUAL**) → 0.
  * Akibatnya kolom **HPP & margin** di Katalog Marketing (`CatalogItemsView.jsx`)
    ada tetapi selalu 0 / "belum ada" ⇒ pemilik tidak bisa tahu margin sebelum
    harga jual ditetapkan.

Modul ini menutup celah itu: HPP/pcs dihitung dari **data yang sudah ada**, bukan
ketikan:

    HPP/pcs = biaya bahan (BOM × unit_cost hasil pembelian, SADAR SATUAN)
            + upah CMT/jahit per pcs

2026-11-06 (Tahap 2, keputusan owner): upah internal (cutting dll.) dan overhead pabrik
TIDAK masuk HPP — keduanya tetap beban bulanan (payroll sudah membukukannya ke 6-2100).
Upah internal tetap dihitung dan ditampilkan sebagai informasi berlabel "tidak masuk HPP".
HPP per potong per FG (warna/ukuran) adalah SATU-SATUNYA HPP standar; ia hanya ditulis ke
FG/model/katalog lewat `apply_model_cost` ("Terapkan").

ATURAN JUJUR (tidak boleh dilanggar)
------------------------------------
1. **Tidak pernah menebak.** Setiap komponen SELALU melaporkan `source` dan, bila
   kosong, muncul di `gaps[]` dengan `action` (layar tujuan perbaikan). Bahan tanpa
   harga TIDAK dihitung 0 diam-diam — ia menjadi gap `material_unvalued`.
2. **Satuan lewat SSOT** `core/bom_uom` (INV-UOM-1/2: `unit_cost` & stok selalu
   satuan dasar). Baris BOM "250 gram" tidak boleh dihitung sebagai 250 kg.
3. **Harga bahan hanya dari master** (`unit_cost`/legacy `hpp`) — yang isinya
   berasal dari penerimaan PO. Modul ini TIDAK PERNAH menulis harga bahan.
4. Upah yang dikunci pemilik disimpan di `rahaza_model_costing` (per model),
   lengkap dengan siapa & kapan menguncinya — bukan di master produk, supaya
   aturan "master tidak menyimpan harga ketikan" tetap berlaku untuk bahan.

KELUARAN
--------
`compute_model_cost()` → satu dokumen berisi rincian per size + `gaps` + margin +
usulan harga jual dari target margin. `apply_model_cost()` menuliskan hasilnya ke
master (`rahaza_models.hpp_bom`), FG per size (`rahaza_materials.hpp`,
`hpp_source='bom'`) dan item katalog Marketing, plus snapshot audit di
`product_cost_snapshots`.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from core import bom_uom
from core import cut_panel_master
from core import product_master as pm
from core.accessory_valuation import resolve_unit_cost

log = logging.getLogger(__name__)

SETTINGS_COLL = "rahaza_costing_settings"
SETTINGS_ID = "GLOBAL"
OVERRIDE_COLL = "rahaza_model_costing"       # upah yang dikunci pemilik (per model)
SNAPSHOT_COLL = "product_cost_snapshots"     # jejak audit tiap kali diterapkan

HPP_SOURCE_BOM = "bom"

# Proses yang UPAHNYA sudah terhitung sebagai "upah CMT/jahit" — dikeluarkan dari
# upah internal supaya tidak dihitung dua kali.
CMT_PROCESS_CODES = {"SEWING", "JAHIT", "CMT", "SEW"}

# Kelompok tampilan biaya bahan.
FABRIC_TYPES = {"fabric", "kain", "yarn", "benang", "interlining", "lining"}

DEFAULT_TARGET_MARGIN_PCT = 30.0


# ══════════════════════════════════════════════════════════════════════════════
# util
# ══════════════════════════════════════════════════════════════════════════════
def _f(v, d: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(d)
        return float(v)
    except (TypeError, ValueError):
        return float(d)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


def _r(v: float, nd: int = 2) -> float:
    return round(_f(v), nd)


def _gap(code: str, message: str, action: str = "", target: str = "", **extra) -> dict:
    """Satu kekurangan yang BISA DITINDAK (dipakai apa adanya oleh layar)."""
    g = {"code": code, "message": message, "action": action, "target": target}
    g.update(extra)
    return g


# ══════════════════════════════════════════════════════════════════════════════
# setelan
# ══════════════════════════════════════════════════════════════════════════════
async def get_settings(db) -> dict:
    doc = await db[SETTINGS_COLL].find_one({"id": SETTINGS_ID}, {"_id": 0}) or {}
    return {
        "overhead_rate_per_pcs": _f(doc.get("overhead_rate_per_pcs")),
        # 2026-11-06 (Tahap 2): overhead pabrik tidak masuk HPP (keputusan owner) — selalu False,
        # apa pun yang pernah tersimpan.
        "include_overhead_in_product_hpp": False,
        "target_margin_pct": _f(doc.get("target_margin_pct"), DEFAULT_TARGET_MARGIN_PCT),
        "labor_rate_fallback_per_pcs": _f(doc.get("labor_rate_fallback_per_pcs")),
        "process_rates": [r for r in (doc.get("process_rates") or []) if isinstance(r, dict)],
    }


async def save_settings(db, patch: dict, user: dict | None = None) -> dict:
    """Simpan setelan costing produk (hanya field milik modul ini)."""
    allowed_num = ("overhead_rate_per_pcs", "target_margin_pct", "labor_rate_fallback_per_pcs")
    up: dict = {}
    for k in allowed_num:
        if k in patch:
            v = _f(patch.get(k), -1)
            if v < 0:
                raise ValueError(f"{k} tidak boleh negatif.")
            up[k] = v
    if "target_margin_pct" in up and up["target_margin_pct"] >= 100:
        raise ValueError("Target margin harus di bawah 100% (margin dihitung atas harga jual).")
    if "include_overhead_in_product_hpp" in patch:
        # 2026-11-06 (Tahap 2): overhead tidak masuk HPP — saklar lama disimpan mati.
        up["include_overhead_in_product_hpp"] = False
    if "process_rates" in patch:
        rows = []
        for r in (patch.get("process_rates") or []):
            if not isinstance(r, dict) or not r.get("process_id"):
                continue
            rate = _f(r.get("rate_per_pcs"), -1)
            if rate < 0:
                raise ValueError("Tarif proses tidak boleh negatif.")
            rows.append({
                "process_id": str(r["process_id"]),
                "code": (r.get("code") or "").strip().upper(),
                "name": (r.get("name") or "").strip(),
                "rate_per_pcs": _r(rate),
            })
        up["process_rates"] = rows
    if not up:
        return await get_settings(db)
    up["updated_at"] = _now()
    if user:
        up["updated_by"] = user.get("id")
        up["updated_by_name"] = user.get("name") or ""
    await db[SETTINGS_COLL].update_one({"id": SETTINGS_ID}, {"$set": up}, upsert=True)
    return await get_settings(db)


# ══════════════════════════════════════════════════════════════════════════════
# upah yang dikunci pemilik (per model)
# ══════════════════════════════════════════════════════════════════════════════
async def get_override(db, model_id: str) -> dict:
    return await db[OVERRIDE_COLL].find_one({"model_id": model_id}, {"_id": 0}) or {}


async def save_override(db, model_id: str, patch: dict, user: dict | None = None) -> dict:
    up: dict = {"model_id": model_id, "updated_at": _now()}
    for k in ("cmt_rate_per_pcs", "internal_labor_per_pcs"):
        if k in patch:
            raw = patch.get(k)
            if raw in (None, ""):
                up[k] = None            # None = kembali ikut data nyata
                continue
            v = _f(raw, -1)
            if v < 0:
                raise ValueError(f"{k} tidak boleh negatif.")
            up[k] = _r(v)
    if "notes" in patch:
        up["notes"] = (patch.get("notes") or "").strip()
    if user:
        up["updated_by"] = user.get("id")
        up["updated_by_name"] = user.get("name") or ""
    await db[OVERRIDE_COLL].update_one({"model_id": model_id}, {"$set": up}, upsert=True)
    return await get_override(db, model_id)


# ══════════════════════════════════════════════════════════════════════════════
# BOM → biaya bahan per pcs
# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-02 (F1b) — BOM disimpan per model × ukuran × WARNA (keputusan owner
# 2026-09-12: "1 master per model×warna×ukuran"; 77 kombinasi model+ukuran punya
# >1 BOM aktif). Dulu resolver ini mengabaikan warna sehingga HPP warna CARAMEL
# DA-1101 memakai BOM BURGUNDY (32.175 vs 91.396,10). Sekarang warna dipakai bila
# diketahui; bila BOM warna itu belum ada, jatuh ke BOM umum (tanpa warna), lalu ke
# perilaku lama (BOM aktif mana pun) DENGAN penanda `other_color` supaya layar bisa
# memberi tahu — tidak diam-diam.
BOM_MATCH_EXACT = "exact"            # BOM warna itu sendiri
BOM_MATCH_GENERAL = "general"        # BOM umum (kolom warna kosong)
BOM_MATCH_OTHER = "other_color"      # BOM warna lain (fallback aman = perilaku lama)
BOM_MATCH_NONE = "none"              # warna tidak diminta (perilaku lama persis)

# Jembatan untuk pemanggil di berkas lain yang BELUM bisa meneruskan warna sendiri
# (mis. `core/fg_cost_layers.compute_batch_unit_cost`). Pemanggil yang tahu warnanya
# membungkus panggilannya dengan `bom_color_scope(warna)`; argumen `color` eksplisit
# selalu menang atas jembatan ini.
_BOM_COLOR_HINT: ContextVar[str | None] = ContextVar("bom_color_hint", default=None)


@contextmanager
def bom_color_scope(color: str | None):
    """Selama blok ini, `find_active_bom` tanpa argumen warna memakai `color`."""
    token = _BOM_COLOR_HINT.set((color or "").strip() or None)
    try:
        yield
    finally:
        _BOM_COLOR_HINT.reset(token)


def _color_key(v) -> str:
    return str(v or "").strip().upper()


def color_of(doc: dict | None) -> str:
    """Warna sebuah varian / item SPK / FG (kode dulu, lalu nama)."""
    d = doc or {}
    return (str(d.get("color_code") or "").strip()
            or str(d.get("color_name") or "").strip()
            or str(d.get("color") or "").strip())


def bom_matches_color(bom: dict, color: str | None) -> bool:
    """BOM ini milik warna `color`? (cocok ke nama ATAU kode warna, tanpa beda huruf)."""
    want = _color_key(color)
    if not want:
        return False
    return want in {_color_key(bom.get("color")), _color_key(bom.get("color_code"))} - {""}


def _bom_is_general(bom: dict) -> bool:
    return not _color_key(bom.get("color")) and not _color_key(bom.get("color_code"))


def pick_bom_for_color(cands: list[dict], color: str | None) -> tuple[dict | None, str]:
    """Pilih BOM untuk satu warna dari kandidat BOM aktif SATU model+ukuran (fungsi murni).

    `cands` sudah terurut prioritas (is_active dulu, versi terbaru dulu).
    Return (bom, match). `match == other_color` → pemanggil memakai BOM lama (fallback aman).
    """
    if not cands:
        return None, BOM_MATCH_NONE
    if not _color_key(color):
        return cands[0], BOM_MATCH_NONE
    exact = [b for b in cands if bom_matches_color(b, color)]
    if exact:
        return exact[0], BOM_MATCH_EXACT
    general = [b for b in cands if _bom_is_general(b)]
    if general:
        return general[0], BOM_MATCH_GENERAL
    return cands[0], BOM_MATCH_OTHER


def _bom_priority(b: dict):
    return (0 if b.get("is_active") is True else 1, -_f(b.get("version")))


async def _legacy_active_bom(db, model_id: str, size_id: str):
    """Perilaku lama (tanpa warna) — dipertahankan persis untuk pemanggil tanpa warna."""
    bom = await db.rahaza_boms.find_one(
        {"model_id": model_id, "size_id": size_id, "active": True, "is_active": True}, {"_id": 0})
    if bom:
        return bom
    cands = await db.rahaza_boms.find(
        {"model_id": model_id, "size_id": size_id, "active": True}, {"_id": 0}
    ).sort("version", -1).to_list(50)
    return cands[0] if cands else None


async def find_active_bom_ex(db, model_id: str, size_id: str, color: str | None = None):
    """(bom, match) untuk model+ukuran+warna. Lihat `pick_bom_for_color`."""
    if not model_id or not size_id:
        return None, BOM_MATCH_NONE
    if color is None:
        color = _BOM_COLOR_HINT.get()
    if not _color_key(color):
        return await _legacy_active_bom(db, model_id, size_id), BOM_MATCH_NONE
    cands = await db.rahaza_boms.find(
        {"model_id": model_id, "size_id": size_id, "active": True}, {"_id": 0}).to_list(200)
    cands.sort(key=_bom_priority)
    bom, match = pick_bom_for_color(cands, color)
    if match == BOM_MATCH_OTHER:
        # fallback aman: BOM yang SAMA dengan yang dipakai sebelum perbaikan ini
        bom = await _legacy_active_bom(db, model_id, size_id) or bom
    return bom, match


async def find_active_bom(db, model_id: str, size_id: str, color: str | None = None):
    """BOM aktif untuk (model_id, size_id[, warna]) — pola yang sama dengan MRP-lite."""
    bom, _match = await find_active_bom_ex(db, model_id, size_id, color)
    return bom


def _cost_source_of(mat: dict | None, unit_cost: float) -> str:
    """Dari mana harga bahan ini datang (label jujur untuk layar)."""
    if not mat or unit_cost <= 0:
        return "none"
    method = (mat.get("cost_method") or "").strip().lower()
    if method == "moving_average":
        return "purchase"          # lahir dari penerimaan PO (rata-rata bergerak)
    if method == "opening":
        return "opening"           # harga awal barang lama (belum pernah dibeli)
    return "master"                # nilai lama tanpa metode (peninggalan)


def _group_of(material_type: str) -> str:
    t = (material_type or "").strip().lower()
    if t in FABRIC_TYPES:
        return "fabric"
    if t in ("accessory", "aksesoris", "acc"):
        return "accessory"
    return "other"


async def _material_master(db, cache: dict, material_id: str | None, code: str | None):
    """Master bahan (cache per permintaan supaya daftar model tetap cepat)."""
    key = f"id:{material_id}" if material_id else (f"code:{(code or '').upper()}" if code else "")
    if not key:
        return None
    if key in cache:
        return cache[key]
    doc = None
    if material_id:
        doc = await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0})
    if not doc and code:
        doc = await db.rahaza_materials.find_one({"code": (code or "").strip().upper()}, {"_id": 0})
    cache[key] = doc
    return doc


async def compute_material_cost(db, model_id: str, size_id: str, *, cache: dict | None = None,
                                color: str | None = None, bom: dict | None = None,
                                bom_match: str | None = None) -> dict:
    """Biaya bahan per pcs untuk satu (model, size[, warna]). Tidak pernah menebak harga.

    2026-11-02 (F1b): `color` (kode/nama warna varian) memilih BOM warna itu. `bom`
    (+ `bom_match`) boleh dikirim langsung oleh pemanggil yang sudah memilihnya.
    """
    cache = cache if cache is not None else {}
    out = {
        "bom_id": None, "bom_version": None, "lines": [],
        "material_cost": 0.0, "fabric_cost": 0.0, "accessory_cost": 0.0, "other_cost": 0.0,
        "gaps": [], "uom_warnings": [], "line_count": 0, "unvalued_count": 0,
        "color_requested": (color or "").strip(), "bom_color": "", "bom_color_match": BOM_MATCH_NONE,
    }
    match = bom_match or BOM_MATCH_NONE
    if bom is None:
        bom, match = await find_active_bom_ex(db, model_id, size_id, color)
    if not bom:
        out["gaps"].append(_gap(
            "bom_missing",
            "BOM (resep bahan) untuk ukuran ini belum ada — biaya bahan tidak bisa dihitung.",
            "Buat BOM model + ukuran ini", "rnd-bom", size_id=size_id))
        return out

    mats, warns = await bom_uom.ensure_uom(db, bom)
    out["bom_id"] = bom.get("id")
    out["bom_version"] = bom.get("version")
    out["bom_color"] = bom.get("color") or bom.get("color_code") or ""
    out["bom_color_match"] = match
    if match == BOM_MATCH_OTHER:
        out["gaps"].append(_gap(
            "bom_color_missing",
            f"BOM warna {color} untuk ukuran ini belum ada — biaya bahan sementara memakai "
            f"BOM warna {out['bom_color'] or 'lain'} (perkiraan).",
            "Buat BOM untuk warna ini", "rnd-bom", size_id=size_id, color=color))
    out["uom_warnings"] = list(warns or [])
    if not mats:
        out["gaps"].append(_gap(
            "bom_empty", "BOM ada tetapi belum berisi satu baris bahan pun.",
            "Isi baris bahan pada BOM", "rnd-bom", bom_id=bom.get("id")))
        return out

    for m in mats:
        mat = await _material_master(db, cache, m.get("material_id"), m.get("code"))
        qty_base = bom_uom.qty_base_of(m)
        unit_base = bom_uom.base_unit_of(m)
        unit_cost = resolve_unit_cost(mat)
        cost_source = _cost_source_of(mat, unit_cost)
        amount = qty_base * unit_cost
        uom_status = m.get("uom_status") or ("base" if (m.get("unit") or "") == unit_base else "")
        status = "ok"
        if not mat:
            status = "unlinked"
        elif unit_cost <= 0:
            status = "unvalued"
        elif uom_status in ("mismatch", "unlinked"):
            status = "uom_unclear"

        line = {
            "material_id": m.get("material_id"),
            "code": m.get("code") or (mat or {}).get("code") or "",
            "name": m.get("name") or (mat or {}).get("name") or "",
            "material_type": m.get("material_type") or (mat or {}).get("type") or "",
            "category_name": m.get("category_name") or (mat or {}).get("category_name") or "",
            "group": _group_of(m.get("material_type") or (mat or {}).get("type")),
            "qty_input": _r(m.get("qty"), 4),
            "unit_input": m.get("unit") or "",
            "qty_base": _r(qty_base, 6),
            "unit_base": unit_base,
            "uom_status": uom_status,
            "uom_note": m.get("uom_note") or "",
            "unit_cost": _r(unit_cost),
            "cost_method": (mat or {}).get("cost_method") or "",
            "cost_source": cost_source,
            "amount": _r(amount),
            "status": status,
        }
        out["lines"].append(line)
        out["material_cost"] += amount
        out[f"{line['group']}_cost"] = _f(out.get(f"{line['group']}_cost")) + amount

        if status == "unvalued":
            out["unvalued_count"] += 1
            if cut_panel_master.is_panel_material(mat) or cut_panel_master.is_panel_line(m):
                out["gaps"].append(_gap(
                    "panel_unvalued",
                    f"Potongan {line['code']} belum punya biaya — belum ada hasil cutting nyata. "
                    f"Biaya potongan lahir di Portal Cutting: nilai kain roll yang dipotong ÷ pcs potongan jadi "
                    f"(rata-rata bergerak). HPP bahan JUJUR Rp 0 sampai cutting pertama selesai.",
                    "Jalankan Order Cutting untuk model · warna · ukuran ini", "cutting-orders",
                    material_id=line["material_id"], material_name=line["name"]))
                continue
            out["gaps"].append(_gap(
                "material_unvalued",
                f"Bahan {line['code'] or line['name']} belum punya harga — "
                f"harga lahir dari penerimaan PO (rata-rata bergerak).",
                "Catat Penerimaan Barang bernilai dari PO (harga ikut terbentuk)",
                "wh-receiving", material_id=line["material_id"], material_name=line["name"]))
        elif status == "unlinked":
            out["gaps"].append(_gap(
                "bom_line_unlinked",
                f"Baris BOM '{line['name']}' belum tertaut master bahan — harga & satuan "
                f"tidak bisa diverifikasi.",
                "Tautkan baris BOM ke master bahan", "rnd-bom", bom_id=bom.get("id")))
        elif status == "uom_unclear":
            out["gaps"].append(_gap(
                "bom_line_uom",
                f"Satuan baris '{line['name']}' ({line['unit_input']}) tidak bisa dikonversi ke "
                f"satuan dasar {line['unit_base']} — {line['uom_note'] or 'lengkapi kemasan/gsm & lebar di master'}.",
                "Lengkapi satuan/kemasan bahan di Master Item", "wh-master",
                material_id=line["material_id"]))

    out["line_count"] = len(out["lines"])
    for k in ("material_cost", "fabric_cost", "accessory_cost", "other_cost"):
        out[k] = _r(out.get(k))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# upah CMT / jahit per pcs
# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-06 (Tahap 2): jendela "SPK terbaru" untuk tarif jahit HPP per potong. Tarif dari 180 hari
# terakhir dipakai; bila tidak ada SPK dalam jendela itu, dipakai baris SPK terbaru (maks. 20) —
# tarif lama tidak membuat HPP basi, tetapi model yang jarang diproduksi tetap punya angka.
CMT_RATE_WINDOW_DAYS = 180
CMT_RATE_FALLBACK_ROWS = 20
CMT_RATE_SCAN_ROWS = 500
CANCELLED_PO_STATUSES = {"cancelled", "rejected", "void", "dibatalkan"}


def _as_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def po_business_type(po: dict | None) -> str:
    """Jenis usaha SPK — aturan yang sama dengan layar Biaya Jahit SPK dan form PO.

    2026-11-07 (K12): PO tanpa jenis = INTERNAL (sama dengan production_pos & desain dua CV §9). Dulu PO tanpa
    jenis yang ber-vendor dianggap maklon — padahal PO internal kini boleh punya vendor (penjahit)."""
    return (po or {}).get("business_type") or "internal"


def pick_cmt_rate_rows(rows: list, pos: dict, *, business_type: str = "internal", now=None,
                       window_days: int = CMT_RATE_WINDOW_DAYS,
                       fallback_rows: int = CMT_RATE_FALLBACK_ROWS) -> dict:
    """Pilih baris SPK untuk tarif jahit (fungsi murni). `rows` = po_items bertarif model ini,
    `pos` = {po_id: production_pos}. SPK yang tidak ditemukan, batal/ditolak, atau berbeda jenis
    usahanya DIKELUARKAN. Tarif = Σ tarif × qty ÷ Σ qty."""
    now = now or _now()
    excluded = {"cancelled": 0, "other_business_type": 0, "po_missing": 0}
    valid = []
    for r in rows or []:
        po = pos.get(r.get("po_id"))
        if not po:
            excluded["po_missing"] += 1
            continue
        if str(po.get("status") or "").strip().lower() in CANCELLED_PO_STATUSES:
            excluded["cancelled"] += 1
            continue
        if po_business_type(po) != business_type:
            excluded["other_business_type"] += 1
            continue
        if _f(r.get("qty")) <= 0:
            continue
        valid.append(r)
    valid.sort(key=lambda r: _as_dt(r.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
               reverse=True)
    cutoff = now - timedelta(days=window_days)
    recent = [r for r in valid if (_as_dt(r.get("created_at")) or cutoff) > cutoff]
    if recent:
        chosen, basis = recent, f"SPK {window_days} hari terakhir"
    else:
        chosen, basis = valid[:fallback_rows], f"{min(len(valid), fallback_rows)} baris SPK terbaru"
    qty = sum(_f(r.get("qty")) for r in chosen)
    rate = (sum(_f(r.get("cmt_price_snapshot")) * _f(r.get("qty")) for r in chosen) / qty) if qty else 0.0
    return {"rows": chosen, "qty": qty, "rate": _r(rate), "basis": basis, "excluded": excluded}


async def resolve_cmt_rate(db, model: dict, *, override: dict | None = None,
                           business_type: str = "internal") -> dict:
    """Upah CMT per pcs + ASAL ANGKANYA + kandidat nyata untuk dipilih pemilik."""
    model_id = model.get("id")
    res = {"rate": 0.0, "source": "none", "note": "", "candidates": [], "gaps": []}

    # kandidat dari data nyata (selalu dikirim supaya layar bisa menawarkan)
    cands: list[dict] = []
    for j in await db.dewi_cmt_jobs.find(
            {"sewing_rate_per_pcs": {"$gt": 0}}, {"_id": 0, "job_code": 1, "cmt_name": 1,
                                                 "product_model_name": 1, "model_id": 1,
                                                 "sewing_rate_per_pcs": 1, "qty_total": 1}).to_list(200):
        cands.append({
            "kind": "cmt_job", "label": f"{j.get('job_code','')} · {j.get('cmt_name','')}",
            "detail": j.get("product_model_name") or "", "rate": _r(j.get("sewing_rate_per_pcs")),
            "model_id": j.get("model_id") or "", "qty": _f(j.get("qty_total")),
        })
    for p in await db.dewi_cmt_partners.find(
            {"rate_per_pcs": {"$gt": 0}}, {"_id": 0, "name": 1, "code": 1, "rate_per_pcs": 1,
                                           "status": 1, "specialization": 1}).to_list(100):
        if (p.get("status") or "active") != "active":
            continue
        cands.append({
            "kind": "partner", "label": f"{p.get('name','')} ({p.get('code','')})",
            "detail": ", ".join(p.get("specialization") or []) or "tarif master partner CMT",
            "rate": _r(p.get("rate_per_pcs")),
        })
    res["candidates"] = sorted(cands, key=lambda c: c["rate"])[:12]

    # 1) dikunci pemilik
    ov = _f((override or {}).get("cmt_rate_per_pcs"))
    if ov > 0:
        res.update({
            "rate": _r(ov), "source": "owner",
            "note": (f"Dikunci oleh {(override or {}).get('updated_by_name') or 'pemilik'}"
                     f" pada {str((override or {}).get('updated_at') or '')[:10]}"),
        })
        return res

    # 2) tarif nyata dari SPK/PO produksi (sesi #34 — pintu input biaya jahit)
    #    Ini SUMBER UTAMA sejak layar "Biaya Jahit SPK" ada: yang diketik staf
    #    produksi per SKU per pcs, ditimbang qty. `dewi_cmt_jobs` di bawah tetap
    #    dipakai sebagai jalan mundur untuk data lama (koleksi itu diarsipkan).
    #    2026-11-06 (Tahap 2): dulu dicocokkan lewat model_id ATAU NAMA, ≤300 baris, tanpa
    #    saring status (SPK batal ikut) dan tanpa saring jenis usaha (tarif maklon ikut).
    #    Sekarang: model_id saja · SPK batal/ditolak dikeluarkan · jenis usaha sama (HPP per
    #    potong = produk internal) · ditimbang qty · SPK terbaru didahulukan (lihat
    #    `pick_cmt_rate_rows`).
    if model_id:
        po_rows = await db.po_items.find(
            {"model_id": model_id, "cmt_price_snapshot": {"$gt": 0}},
            {"_id": 0, "po_id": 1, "cmt_price_snapshot": 1, "qty": 1, "po_number": 1, "sku": 1,
             "created_at": 1}
        ).sort("created_at", -1).to_list(CMT_RATE_SCAN_ROWS)
        po_ids = list({r.get("po_id") for r in po_rows if r.get("po_id")})
        pos = {}
        if po_ids:
            async for p in db.production_pos.find(
                    {"id": {"$in": po_ids}},
                    {"_id": 0, "id": 1, "status": 1, "business_type": 1, "vendor_id": 1}):
                pos[p["id"]] = p
        picked = pick_cmt_rate_rows(po_rows, pos, business_type=business_type, now=_now())
        if picked["rows"] and picked["qty"] > 0:
            res.update({
                "rate": picked["rate"], "source": "spk_actual",
                "note": (f"Rata-rata tertimbang biaya jahit {len(picked['rows'])} baris SPK "
                         f"{business_type} model ini ({int(picked['qty'])} pcs, {picked['basis']}) — "
                         f"diisi di layar Biaya Jahit SPK."),
                "basis": picked["basis"], "excluded": picked["excluded"],
            })
            return res

    # 3) rata-rata TERTIMBANG dari job CMT model ini (data lama) — model_id saja (Tahap 2)
    if model_id:
        rows = await db.dewi_cmt_jobs.find(
            {"model_id": model_id, "sewing_rate_per_pcs": {"$gt": 0}}, {"_id": 0}).to_list(200)
        tot_q = sum(_f(r.get("qty_total")) for r in rows)
        if rows and tot_q > 0:
            rate = sum(_f(r.get("sewing_rate_per_pcs")) * _f(r.get("qty_total")) for r in rows) / tot_q
            res.update({
                "rate": _r(rate), "source": "cmt_job_actual",
                "note": f"Rata-rata tertimbang {len(rows)} job CMT model ini ({int(tot_q)} pcs).",
            })
            return res
        if rows:
            rate = sum(_f(r.get("sewing_rate_per_pcs")) for r in rows) / len(rows)
            res.update({"rate": _r(rate), "source": "cmt_job_actual",
                        "note": f"Rata-rata {len(rows)} job CMT model ini (qty belum diisi)."})
            return res

    res["gaps"].append(_gap(
        "cmt_rate_missing",
        "Upah CMT/jahit per pcs belum ada untuk produk ini.",
        "Isi Biaya Jahit per SKU di layar Biaya Jahit SPK (atau kunci upah CMT di layar HPP)",
        "prod-sewing-cost",
        candidates=len(res["candidates"])))
    return res


def _rx(s: str) -> str:
    import re
    return re.escape(s)


# ══════════════════════════════════════════════════════════════════════════════
# upah cutting / internal per pcs
# ══════════════════════════════════════════════════════════════════════════════
async def resolve_internal_labor(db, model: dict, *, override: dict | None = None,
                                 settings: dict | None = None) -> dict:
    """Upah cutting/internal per pcs dari data produksi nyata (bukan tebakan)."""
    settings = settings or {}
    model_id = model.get("id")
    res = {"rate": 0.0, "source": "none", "note": "", "processes": [], "candidates": [], "gaps": []}

    # 1) dikunci pemilik
    ov = _f((override or {}).get("internal_labor_per_pcs"))
    if ov > 0:
        res.update({"rate": _r(ov), "source": "owner",
                    "note": (f"Dikunci oleh {(override or {}).get('updated_by_name') or 'pemilik'}"
                             f" pada {str((override or {}).get('updated_at') or '')[:10]}")})
        return res

    # 2) AKTUAL dari cermin progres produksi (rahaza_wip_events)
    if model_id:
        rows = await db.rahaza_wip_events.find(
            {"model_id": model_id, "event_type": "complete"}, {"_id": 0}).to_list(5000)
        per_proc: dict = {}
        for ev in rows:
            code = (ev.get("process_code") or "").strip().upper()
            if code in CMT_PROCESS_CODES:
                continue                      # sudah dihitung sebagai upah CMT
            qty = _f(ev.get("qty_done") or ev.get("qty"))
            rate = _f(ev.get("rate_per_pcs"))
            if qty <= 0 or rate <= 0:
                continue
            slot = per_proc.setdefault(code or "(tanpa proses)", {"qty": 0.0, "amount": 0.0})
            slot["qty"] += qty
            slot["amount"] += qty * rate
        if per_proc:
            total = 0.0
            procs = []
            for code, v in sorted(per_proc.items()):
                avg = v["amount"] / v["qty"] if v["qty"] else 0.0
                total += avg
                procs.append({"process_code": code, "rate_per_pcs": _r(avg),
                              "qty_observed": _r(v["qty"], 0), "source": "wip_actual"})
            res.update({
                "rate": _r(total), "source": "wip_actual", "processes": procs,
                "note": (f"Rata-rata upah nyata dari laporan produksi "
                         f"({len(procs)} proses, proses jahit/CMT dikecualikan)."),
            })
            return res

    # 3) tarif standar per proses dari setelan
    rates = [r for r in (settings.get("process_rates") or [])
             if _f(r.get("rate_per_pcs")) > 0 and (r.get("code") or "").upper() not in CMT_PROCESS_CODES]
    if rates:
        total = sum(_f(r.get("rate_per_pcs")) for r in rates)
        res.update({
            "rate": _r(total), "source": "settings_process_rates",
            "processes": [{"process_code": (r.get("code") or ""), "rate_per_pcs": _r(r.get("rate_per_pcs")),
                           "qty_observed": 0, "source": "settings"} for r in rates],
            "note": f"Tarif standar {len(rates)} proses dari Setelan Upah (belum ada data produksi).",
        })
        return res

    # 4) tarif cadangan tunggal
    fb = _f(settings.get("labor_rate_fallback_per_pcs"))
    if fb > 0:
        res.update({"rate": _r(fb), "source": "settings_fallback",
                    "note": "Tarif cadangan per pcs dari Setelan Costing."})
        return res

    # kandidat dari profil payroll borongan (data nyata) untuk ditawarkan
    cands = []
    for p in await db.rahaza_payroll_profiles.find(
            {"pay_scheme": "pcs", "active": True}, {"_id": 0, "employee_id": 1, "base_rate": 1,
                                                    "pcs_process_rates": 1}).to_list(100):
        if _f(p.get("base_rate")) > 0:
            cands.append({"kind": "payroll_profile", "label": "Tarif borongan karyawan",
                          "detail": p.get("employee_id") or "", "rate": _r(p.get("base_rate"))})
        for r in (p.get("pcs_process_rates") or []):
            if _f(r.get("rate")) > 0:
                cands.append({"kind": "payroll_process", "label": "Tarif borongan per proses",
                              "detail": r.get("process_id") or "", "rate": _r(r.get("rate"))})
    res["candidates"] = sorted(cands, key=lambda c: c["rate"])[:12]
    res["gaps"].append(_gap(
        "internal_labor_missing",
        "Upah cutting/internal per pcs belum ada — belum ada laporan produksi bertarif "
        "maupun tarif standar proses.",
        "Isi tarif proses di Setelan Upah atau kunci upah internal produk ini",
        "fin-hpp-produk", candidates=len(res["candidates"])))
    return res


# ══════════════════════════════════════════════════════════════════════════════
# harga jual & margin
# ══════════════════════════════════════════════════════════════════════════════
def margin_of(price: float, hpp: float) -> dict:
    """Margin HANYA dihitung bila harga jual DAN HPP dua-duanya diketahui.

    2026-08-23 (temuan dari layar) — dulu `price - 0` untuk produk yang HPP-nya
    belum bisa dihitung menghasilkan **margin 100%**: layar terlihat sangat
    menguntungkan padahal biayanya belum diketahui sama sekali. Itu justru jenis
    kebohongan yang paling mahal, jadi margin dilaporkan `margin_known=False`
    dan layar menampilkan "—" + alasannya.

    2026-11-06 (Tahap 2): rumusnya kini SATU untuk seluruh aplikasi (`core.margin`).
    """
    from core import margin as _margin
    return _margin.margin_of(price, hpp)


def suggested_price(hpp: float, target_margin_pct: float) -> float:
    """Harga jual usulan agar margin (ATAS HARGA JUAL) = target (`core.margin`)."""
    from core import margin as _margin
    return _margin.price_for_margin(hpp, target_margin_pct)


async def _sizes_of_model(db, model_id: str) -> list[dict]:
    """Ukuran yang benar-benar dipakai model ini: varian master ∪ BOM ∪ FG."""
    seen: dict = {}
    async for v in db.rahaza_model_variants.find(
            {"model_id": model_id}, {"_id": 0, "size_id": 1, "size_code": 1, "active": 1}):
        sid = v.get("size_id")
        if not sid or v.get("active") is False:
            continue
        seen.setdefault(sid, {"size_id": sid, "size_code": v.get("size_code") or "", "from": "variant"})
    async for b in db.rahaza_boms.find({"model_id": model_id}, {"_id": 0, "size_id": 1, "size_code": 1}):
        sid = b.get("size_id")
        if sid and sid not in seen:
            seen[sid] = {"size_id": sid, "size_code": b.get("size_code") or "", "from": "bom"}
    async for f in db.rahaza_materials.find(
            {"type": "fg", "model_id": model_id}, {"_id": 0, "size_id": 1, "size_code": 1}):
        sid = f.get("size_id")
        if sid and sid not in seen:
            seen[sid] = {"size_id": sid, "size_code": f.get("size_code") or "", "from": "fg"}
    rows = list(seen.values())
    for r in rows:
        if not r["size_code"]:
            s = await db.rahaza_sizes.find_one({"id": r["size_id"]}, {"_id": 0, "code": 1})
            r["size_code"] = (s or {}).get("code") or ""
    rows.sort(key=lambda r: (r["size_code"] or "zzz"))
    return rows


async def _price_info(db, model: dict, size_id: str, fg_ids: list[str]) -> dict:
    """Harga jual yang BERLAKU untuk size ini (master retail + harga marketplace)."""
    out = {"retail_price": _r(model.get("retail_price")), "platform_prices": [],
           "best_price": 0.0, "price_source": "none"}
    q_or: list[dict] = []
    if fg_ids:
        q_or += [{"fg_material_id": {"$in": fg_ids}}, {"material_id": {"$in": fg_ids}}]
    if q_or:
        async for it in db.marketing_catalog_items.find(
                {"$and": [{"$or": q_or}, {"platform_price": {"$gt": 0}}]},
                {"_id": 0, "platform": 1, "platform_price": 1, "sku": 1, "is_active": 1}):
            if it.get("is_active") is False:
                continue
            out["platform_prices"].append({"platform": it.get("platform") or "",
                                           "sku": it.get("sku") or "",
                                           "price": _r(it.get("platform_price"))})
    if out["platform_prices"]:
        out["best_price"] = min(p["price"] for p in out["platform_prices"])
        out["price_source"] = "marketplace"
    elif out["retail_price"] > 0:
        out["best_price"] = out["retail_price"]
        out["price_source"] = "retail_master"
    return out


def _row_hpps(rows: list[dict]) -> list[float]:
    """HPP/pcs yang berlaku: per warna bila ada FG warna, selain itu angka per ukuran (F1b)."""
    out: list[float] = []
    for r in rows:
        cols = [c["hpp_unit"] for c in (r.get("colors") or []) if c.get("bom_id") and c["hpp_unit"] > 0]
        if cols:
            out.extend(cols)
        elif r.get("bom_id") and r.get("hpp_unit", 0) > 0:
            out.append(r["hpp_unit"])
    return out


def _bad_statuses(mc: dict) -> list[str]:
    return sorted({ln["status"] for ln in (mc.get("lines") or []) if ln.get("status") != "ok"})


async def _color_costs(db, model_id: str, size: dict, fg_rows: list[dict], size_mc: dict, *,
                       cmt_rate: float, labor_rate: float, overhead: float,
                       cache: dict) -> tuple[list[dict], list[dict]]:
    """2026-11-02 (F1b) — HPP tiap FG warna dari BOM warnanya sendiri.

    Satu BOM dihitung sekali (cache per bom_id). Warna tanpa BOM sendiri → BOM ukuran
    lama (= perilaku sebelum perbaikan) + gap `bom_color_missing`, tidak diam-diam.
    """
    if not fg_rows:
        return [], []
    cands = await db.rahaza_boms.find(
        {"model_id": model_id, "size_id": size["size_id"], "active": True}, {"_id": 0}).to_list(200)
    cands.sort(key=_bom_priority)
    by_bom: dict = {}
    if size_mc.get("bom_id"):
        by_bom[size_mc["bom_id"]] = size_mc
    out, gaps = [], []
    for f in fg_rows:
        col = color_of(f)
        bom, match = pick_bom_for_color(cands, col)
        if match in (BOM_MATCH_OTHER, BOM_MATCH_NONE) or not bom:
            mc = size_mc                       # perilaku lama, apa adanya
        else:
            mc = by_bom.get(bom.get("id"))
            if mc is None:
                mc = await compute_material_cost(db, model_id, size["size_id"], cache=cache,
                                                 color=col, bom=bom, bom_match=match)
                by_bom[bom.get("id")] = mc
                gaps.extend(mc.get("gaps") or [])
        if match == BOM_MATCH_OTHER:
            gaps.append(_gap(
                "bom_color_missing",
                f"Warna {col} ukuran {size.get('size_code') or size['size_id']} belum punya BOM "
                f"sendiri — HPP-nya memakai BOM warna {size_mc.get('bom_color') or 'lain'} (perkiraan).",
                "Buat BOM untuk warna ini", "rnd-bom", size_id=size["size_id"], color=col))
        computable = bool(mc.get("bom_id")) and bool(mc.get("lines")) and not _bad_statuses(mc)
        # 2026-11-06 (Tahap 2): HPP = bahan + upah CMT; upah internal & overhead tidak masuk HPP.
        unit = _r(_f(mc.get("material_cost")) + cmt_rate)
        out.append({
            "fg_id": f["id"], "code": f.get("code"), "color": col,
            "color_name": f.get("color_name") or f.get("color") or "",
            "bom_id": mc.get("bom_id"), "bom_version": mc.get("bom_version"),
            "bom_color": mc.get("bom_color") or "", "bom_color_match": match,
            "material_cost": _r(mc.get("material_cost")),
            "fabric_cost": _r(mc.get("fabric_cost")), "accessory_cost": _r(mc.get("accessory_cost")),
            "other_cost": _r(mc.get("other_cost")),
            "unvalued_count": mc.get("unvalued_count", 0),
            "bad_line_statuses": _bad_statuses(mc),
            "computable": computable,
            "hpp_unit": unit,
            "confidence": ("full" if (computable and cmt_rate > 0)
                           else ("partial" if mc.get("bom_id") else "none")),
            "hpp_current": _r(f.get("hpp")), "hpp_source_current": f.get("hpp_source") or "none",
        })
    return out, gaps


# ══════════════════════════════════════════════════════════════════════════════
# HPP per model (semua size)
# ══════════════════════════════════════════════════════════════════════════════
async def compute_model_cost(db, model_id: str, *, size_id: str | None = None,
                             include_overhead: bool | None = None,
                             target_margin_pct: float | None = None,
                             settings: dict | None = None, cache: dict | None = None,
                             with_candidates: bool = True) -> dict:
    """HPP/pcs per size untuk satu model + margin + kekurangan yang bisa ditindak."""
    model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0})
    if not model:
        raise LookupError("Model tidak ditemukan.")
    settings = settings if settings is not None else await get_settings(db)
    cache = cache if cache is not None else {}
    override = await get_override(db, model_id)
    # 2026-11-06 (Tahap 2, keputusan owner): overhead pabrik & upah internal TIDAK masuk HPP.
    # Parameter `include_overhead` tetap diterima (pemanggil lama) tetapi tidak berpengaruh.
    use_oh = False
    overhead = 0.0
    target = _f(target_margin_pct, settings["target_margin_pct"])

    cmt = await resolve_cmt_rate(db, model, override=override)
    labor = await resolve_internal_labor(db, model, override=override, settings=settings)
    if not with_candidates:
        cmt = {**cmt, "candidates": []}
        labor = {**labor, "candidates": []}

    sizes = await _sizes_of_model(db, model_id)
    if size_id:
        sizes = [s for s in sizes if s["size_id"] == size_id]

    rows = []
    # upah internal tidak masuk HPP ⇒ kekurangannya bukan kekurangan HPP (tidak dilaporkan sebagai gap)
    gaps: list[dict] = list(cmt["gaps"])
    for s in sizes:
        mc = await compute_material_cost(db, model_id, s["size_id"], cache=cache)
        fg_rows = await db.rahaza_materials.find(
            {"type": "fg", "model_id": model_id, "size_id": s["size_id"]},
            {"_id": 0, "id": 1, "code": 1, "name": 1, "hpp": 1, "hpp_source": 1,
             "color_name": 1, "color_code": 1, "color": 1, "variant_id": 1}).to_list(500)
        fg_ids = [f["id"] for f in fg_rows]
        price = await _price_info(db, model, s["size_id"], fg_ids)
        # T-04: baris `unlinked`/`uom_unclear` juga membuat HPP tidak bisa dipercaya.
        computable = bool(mc["bom_id"]) and bool(mc["lines"]) and all(
            ln["status"] == "ok" for ln in mc["lines"])
        hpp = _r(mc["material_cost"] + cmt["rate"])          # Tahap 2: tanpa upah internal & overhead
        marg = margin_of(price["best_price"], hpp)
        # 2026-11-02 (F1b) — HPP PER WARNA. Angka per ukuran di atas tetap dihitung
        # seperti dulu (kompatibilitas layar), tetapi tiap FG warna kini memakai BOM
        # warnanya sendiri; `apply_model_cost` menulis angka per warna ini.
        colors, color_gaps = await _color_costs(
            db, model_id, s, fg_rows, mc, cmt_rate=cmt["rate"], labor_rate=labor["rate"],
            overhead=overhead, cache=cache)
        gaps.extend(color_gaps)
        color_hpps = [c["hpp_unit"] for c in colors if c["bom_id"] and c["hpp_unit"] > 0]
        row = {
            "size_id": s["size_id"], "size_code": s["size_code"], "size_from": s["from"],
            "bom_id": mc["bom_id"], "bom_version": mc["bom_version"],
            "material_cost": mc["material_cost"],
            "fabric_cost": mc["fabric_cost"], "accessory_cost": mc["accessory_cost"],
            "other_cost": mc["other_cost"],
            "cmt_cost": _r(cmt["rate"]),
            # informasi saja — TIDAK masuk HPP (keputusan owner 6 Nov 2026)
            "internal_labor_cost": _r(labor["rate"]), "internal_labor_in_hpp": False,
            "overhead_cost": overhead,
            "hpp_unit": hpp,
            "lines": mc["lines"], "line_count": mc["line_count"],
            "unvalued_count": mc["unvalued_count"],
            "gaps": mc["gaps"],
            "uom_warnings": mc["uom_warnings"],
            "computable": computable,
            "confidence": ("full" if (computable and cmt["rate"] > 0)
                           else ("partial" if mc["bom_id"] else "none")),
            "fg_variants": [{"id": f["id"], "code": f.get("code"), "name": f.get("name"),
                             "color_name": f.get("color_name") or "",
                             "hpp_current": _r(f.get("hpp")),
                             "hpp_source_current": f.get("hpp_source") or "none"} for f in fg_rows],
            "colors": colors,
            "hpp_unit_min": _r(min(color_hpps)) if color_hpps else hpp,
            "hpp_unit_max": _r(max(color_hpps)) if color_hpps else hpp,
            "hpp_varies_by_color": bool(color_hpps) and (max(color_hpps) - min(color_hpps)) > 0.005,
            "price": price,
            "margin": marg["margin"], "margin_pct": marg["margin_pct"],
            "has_price": marg["has_price"], "margin_known": marg["margin_known"],
            "suggested_price": suggested_price(hpp, target),
        }
        rows.append(row)
        gaps.extend(mc["gaps"])
        if not marg["has_price"] and hpp > 0:
            gaps.append(_gap(
                "selling_price_missing",
                f"Ukuran {s['size_code'] or s['size_id']} belum punya harga jual — margin belum bisa dihitung.",
                "Tetapkan harga jual (usulan sudah dihitung dari target margin)",
                "marketing-catalog", size_id=s["size_id"]))

    computable_rows = [r for r in rows if r["bom_id"]]
    hpp_values = _row_hpps(computable_rows)
    model_hpp = _r(sum(hpp_values) / len(hpp_values)) if hpp_values else 0.0
    cur_hpp, cur_src = pm.resolve_hpp(model)

    # Jalan keluar tercepat yang NYATA: kalau satu ukuran sudah punya BOM, ukuran
    # lain bisa disalin darinya (endpoint `POST /boms/{id}/copy-to-sizes` sudah ada)
    # lalu disesuaikan — jauh lebih murah daripada mengetik ulang 7 BOM.
    missing_rows = [r for r in rows if not r["bom_id"]]
    if computable_rows and missing_rows:
        src = computable_rows[0]
        gaps.append(_gap(
            "bom_missing_other_sizes",
            (f"{len(missing_rows)} ukuran belum punya BOM "
             f"({', '.join(r['size_code'] or r['size_id'] for r in missing_rows)}), "
             f"padahal ukuran {src['size_code'] or '—'} sudah punya."),
            f"Salin BOM dari ukuran {src['size_code'] or '—'}", "fin-hpp-produk",
            copy_bom_id=src["bom_id"], copy_from_size=src["size_code"],
            target_size_ids=[r["size_id"] for r in missing_rows]))

    # Ukuran yang SUDAH bisa dihitung ditaruh di atas supaya layar tidak dibuka
    # dengan deretan "BOM belum ada" (produk 8 ukuran hanya punya 1 BOM = normal).
    rows.sort(key=lambda r: (0 if r["bom_id"] else 1, r["size_code"] or "zzz"))

    # Kekurangan DIRINGKAS per jenis: satu baris "BOM belum ada" yang menyebut
    # ukuran-ukurannya jauh lebih bisa ditindak daripada 7 baris identik.
    size_name = {r["size_id"]: (r["size_code"] or r["size_id"]) for r in rows}
    uniq: dict = {}
    for g in gaps:
        key = f"{g.get('code')}|{g.get('material_id') or ''}"
        slot = uniq.get(key)
        if not slot:
            slot = {**g, "count": 0, "sizes": []}
            uniq[key] = slot
        slot["count"] += 1
        sid = g.get("size_id")
        if sid:
            label = size_name.get(sid, sid)
            if label not in slot["sizes"]:
                slot["sizes"].append(label)
    for slot in uniq.values():
        if slot["count"] > 1 and slot["sizes"]:
            slot["message"] = (f"{slot['message']} Berlaku untuk {len(slot['sizes'])} ukuran: "
                               f"{', '.join(slot['sizes'])}.")

    return {
        "model": {"id": model.get("id"), "code": model.get("code"), "name": model.get("name"),
                  "category_name": model.get("category_name") or model.get("category") or "",
                  "retail_price": _r(model.get("retail_price")),
                  "hpp_current": _r(cur_hpp), "hpp_source_current": cur_src,
                  "hpp_bom_current": _r(model.get("hpp_bom")),
                  "hpp_bom_updated_at": model.get("hpp_bom_updated_at")},
        "sizes": rows,
        "size_count": len(rows),
        "sizes_with_bom": len(computable_rows),
        "cmt": {k: cmt[k] for k in ("rate", "source", "note", "candidates")},
        "internal_labor": {**{k: labor[k] for k in ("rate", "source", "note", "processes", "candidates")},
                           "in_hpp": False, "label": "tidak masuk HPP"},
        "overhead": {"rate": overhead, "included": use_oh, "in_hpp": False, "label": "tidak masuk HPP",
                     "rate_setting": _r(settings["overhead_rate_per_pcs"])},
        "override": {"cmt_rate_per_pcs": override.get("cmt_rate_per_pcs"),
                     "internal_labor_per_pcs": override.get("internal_labor_per_pcs"),
                     "notes": override.get("notes") or "",
                     "updated_by_name": override.get("updated_by_name") or "",
                     "updated_at": override.get("updated_at")},
        "target_margin_pct": _r(target),
        "hpp_model_avg": model_hpp,
        "suggested_price_model": suggested_price(model_hpp, target),
        "gaps": list(uniq.values()),
        "gap_count": len(uniq),
        "computed_at": _now().isoformat(),
    }


async def list_models_cost(db, *, q: str | None = None, only_gaps: bool = False,
                           include_overhead: bool | None = None,
                           target_margin_pct: float | None = None,
                           limit: int = 200) -> dict:
    """Ringkasan HPP semua model (untuk tabel layar 'HPP per Potong')."""
    settings = await get_settings(db)
    cache: dict = {}
    filt: dict = {"$or": [{"active": True}, {"active": {"$exists": False}}, {"status": "active"}]}
    if q:
        rx = {"$regex": _rx(q), "$options": "i"}
        filt = {"$and": [filt, {"$or": [{"code": rx}, {"name": rx}]}]}
    models = await db.rahaza_models.find(filt, {"_id": 0}).sort("code", 1).to_list(limit)
    # 2026-11-04 (audit Keuangan): layar memberi tahu bila model lebih banyak dari batas (dulu terpotong diam-diam)
    total_models = await db.rahaza_models.count_documents(filt) if len(models) >= limit else len(models)

    rows = []
    tot = {"models": 0, "ready": 0, "partial": 0, "no_bom": 0, "with_price": 0}
    for m in models:
        d = await compute_model_cost(db, m["id"], include_overhead=include_overhead,
                                     target_margin_pct=target_margin_pct,
                                     settings=settings, cache=cache, with_candidates=False)
        sizes = d["sizes"]
        hpps = _row_hpps([s for s in sizes if s["bom_id"]])
        prices = [s["price"]["best_price"] for s in sizes if s["price"]["best_price"] > 0]
        margins = [s["margin_pct"] for s in sizes if s.get("margin_known")]
        ready = any(s["confidence"] == "full" for s in sizes)
        no_bom = d["sizes_with_bom"] == 0
        status = "ready" if ready else ("no_bom" if no_bom else "partial")
        tot["models"] += 1
        tot["ready" if status == "ready" else status] = tot.get(status, 0) + 1
        if prices:
            tot["with_price"] += 1
        row = {
            "model_id": m["id"], "code": m.get("code"), "name": m.get("name"),
            "category_name": m.get("category_name") or m.get("category") or "",
            "size_count": d["size_count"], "sizes_with_bom": d["sizes_with_bom"],
            "hpp_min": _r(min(hpps)) if hpps else 0.0,
            "hpp_max": _r(max(hpps)) if hpps else 0.0,
            "hpp_avg": d["hpp_model_avg"],
            "material_cost_avg": _r(sum(s["material_cost"] for s in sizes) / len(sizes)) if sizes else 0.0,
            "cmt_cost": d["cmt"]["rate"], "cmt_source": d["cmt"]["source"],
            "internal_labor_cost": d["internal_labor"]["rate"],
            "internal_labor_source": d["internal_labor"]["source"],
            "overhead_cost": d["overhead"]["rate"],
            "price_best": _r(min(prices)) if prices else 0.0,
            "margin_pct": _r(sum(margins) / len(margins)) if margins else 0.0,
            "margin_known": bool(margins),
            "suggested_price": d["suggested_price_model"],
            "hpp_current": d["model"]["hpp_current"],
            "hpp_source_current": d["model"]["hpp_source_current"],
            "hpp_bom_current": d["model"]["hpp_bom_current"],
            "gap_count": d["gap_count"],
            "gap_codes": sorted({g["code"] for g in d["gaps"]}),
            "status": status,
        }
        if only_gaps and row["gap_count"] == 0:
            continue
        rows.append(row)

    return {"items": rows, "count": len(rows), "totals": tot, "total_models": total_models, "limit": limit,
            "settings": settings, "computed_at": _now().isoformat()}


# ══════════════════════════════════════════════════════════════════════════════
# terapkan → master + FG + item katalog + snapshot
# ══════════════════════════════════════════════════════════════════════════════
async def apply_model_cost(db, model_id: str, user: dict, *, size_ids: list[str] | None = None,
                           include_overhead: bool | None = None) -> dict:
    """Tulis HPP hasil hitung ke master produk, FG per size, dan item katalog.

    Idempoten: memanggil dua kali dengan data sama menghasilkan angka sama.
    Hanya size yang PUNYA BOM yang diterapkan (yang lain dilaporkan `skipped`).
    """
    d = await compute_model_cost(db, model_id, include_overhead=include_overhead,
                                 with_candidates=False)
    now = _now()
    applied, skipped = [], []
    fg_updated = 0
    item_updated = 0

    for s in d["sizes"]:
        if size_ids and s["size_id"] not in size_ids:
            continue
        # 2026-11-02 (F1b): tiap FG WARNA ditulis dengan HPP dari BOM warnanya sendiri
        # (dulu satu angka per ukuran ditimpakan ke semua warna). Ukuran tanpa FG varian
        # tetap diproses sebagai satu target (angka model saja), seperti dulu.
        targets = s.get("colors") or [None]
        for c in targets:
            src = c or s
            label = {"size_id": s["size_id"], "size_code": s["size_code"]}
            if c:
                label.update({"fg_id": c["fg_id"], "code": c["code"], "color": c["color"]})
            bad = src.get("bad_line_statuses") if c else _bad_statuses(s)
            if not src["bom_id"] or src["hpp_unit"] <= 0 or not src.get("computable"):
                if not src["bom_id"]:
                    reason = "BOM belum ada"
                elif not src.get("computable"):
                    reason = (f"baris BOM belum bisa dinilai ({', '.join(bad)}) — HPP tidak diterapkan")
                else:
                    reason = "HPP 0"
                skipped.append({**label, "reason": reason})
                continue
            breakdown = {
                "material": src["material_cost"], "fabric": src["fabric_cost"],
                "accessory": src["accessory_cost"], "other": src["other_cost"],
                # Tahap 2: upah internal & overhead tidak masuk HPP (0); angka info disimpan terpisah
                "cmt": s["cmt_cost"], "internal_labor": 0.0, "overhead": 0.0,
                "internal_labor_info": s["internal_labor_cost"], "confidence": src["confidence"],
                "unvalued_count": src["unvalued_count"], "bom_id": src["bom_id"],
                "bom_version": src["bom_version"],
            }
            if c:
                breakdown.update({"color": c["color"], "bom_color": c["bom_color"],
                                  "bom_color_match": c["bom_color_match"]})
                fg_filter = {"id": c["fg_id"]}
                fg_ids = [c["fg_id"]]
            else:
                fg_filter = {"type": "fg", "model_id": model_id, "size_id": s["size_id"]}
                fg_ids = [f["id"] for f in s["fg_variants"]]
            res_fg = await db.rahaza_materials.update_many(
                fg_filter,
                {"$set": {"hpp": src["hpp_unit"], "hpp_source": HPP_SOURCE_BOM,
                          "hpp_updated_at": now, "hpp_breakdown": breakdown,
                          "updated_at": now}})
            fg_updated += res_fg.modified_count
            # 2026-11-02 (owner No.26a): item katalog yang FG-nya SUDAH bernilai WAC memakai WAC itu
            # (`fcl._sync_catalog`); HPP kalkulator hanya estimasi dan tidak boleh menimpanya.
            # Satu definisi "sudah WAC" = `catalog_margin.effective_fg_cost` (sumber fg_wac).
            wac_ids = []
            if fg_ids:
                from core import catalog_margin as _cm
                async for m in db.rahaza_materials.find(
                        {"id": {"$in": fg_ids}}, {"_id": 0, "id": 1, "unit_cost": 1, "wac_components": 1}):
                    if _cm.effective_fg_cost(m)["source"] == _cm.SRC_WAC:
                        wac_ids.append(m["id"])
            cat_ids = [i for i in fg_ids if i not in wac_ids]
            if cat_ids:
                res_items = await db.marketing_catalog_items.update_many(
                    {"$or": [{"fg_material_id": {"$in": cat_ids}}, {"material_id": {"$in": cat_ids}}]},
                    {"$set": {"hpp": src["hpp_unit"], "hpp_source": HPP_SOURCE_BOM,
                              "hpp_updated_at": now, "updated_at": now}})
                item_updated += res_items.modified_count
            applied.append({**label, "hpp_unit": src["hpp_unit"], "fg_count": len(fg_ids),
                            "catalog_kept_wac": len(wac_ids),
                            "confidence": src["confidence"], "breakdown": breakdown})

    hpps = [a["hpp_unit"] for a in applied]
    model_hpp = _r(sum(hpps) / len(hpps)) if hpps else 0.0
    model_before = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0})
    hpp_before, src_before = pm.resolve_hpp(model_before or {})
    if applied:
        per_size: dict = {}
        for a in applied:
            per_size.setdefault(a["size_id"], []).append(a["hpp_unit"])
        by_size = {sid: _r(sum(v) / len(v)) for sid, v in per_size.items()}
        merged = {**(model_before or {}), "hpp_bom": model_hpp}
        merged.pop("hpp", None)
        eff_hpp, eff_src = pm.resolve_hpp(merged)
        await db.rahaza_models.update_one({"id": model_id}, {"$set": {
            "hpp_bom": model_hpp,
            "hpp_bom_by_size": {**(model_before or {}).get("hpp_bom_by_size", {}), **by_size},
            "hpp_bom_updated_at": now,
            "hpp_bom_updated_by": user.get("id"),
            "hpp_bom_updated_by_name": user.get("name") or "",
            "hpp": eff_hpp, "hpp_source": eff_src, "hpp_updated_at": now,
            "updated_at": now,
        }})

    snap = {
        "id": _uid(), "model_id": model_id,
        "model_code": d["model"]["code"], "model_name": d["model"]["name"],
        "hpp_model": model_hpp, "applied_sizes": applied, "skipped_sizes": skipped,
        "cmt": d["cmt"]["rate"], "cmt_source": d["cmt"]["source"],
        "internal_labor": d["internal_labor"]["rate"], "internal_labor_in_hpp": False,
        "internal_labor_source": d["internal_labor"]["source"],
        "overhead": d["overhead"]["rate"], "overhead_included": d["overhead"]["included"],
        "gaps": d["gaps"], "gap_count": d["gap_count"],
        "hpp_before": _r(hpp_before), "hpp_source_before": src_before,
        "fg_updated": fg_updated, "catalog_items_updated": item_updated,
        "created_at": now, "created_by": user.get("id"),
        "created_by_name": user.get("name") or "",
    }
    await db[SNAPSHOT_COLL].insert_one(dict(snap))
    snap.pop("_id", None)

    return {"ok": bool(applied), "model_id": model_id, "hpp_model": model_hpp,
            "applied": applied, "skipped": skipped,
            "fg_updated": fg_updated, "catalog_items_updated": item_updated,
            "hpp_before": _r(hpp_before), "hpp_source_before": src_before,
            "snapshot_id": snap["id"], "gaps": d["gaps"]}


async def list_snapshots(db, *, model_id: str | None = None, limit: int = 50) -> list[dict]:
    q = {"model_id": model_id} if model_id else {}
    return await db[SNAPSHOT_COLL].find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)


# ══════════════════════════════════════════════════════════════════════════════
# BOM → kebutuhan bahan untuk order cutting
# ══════════════════════════════════════════════════════════════════════════════
async def bom_requirement_for_cutting(db, *, model_id: str, size_id: str | None = None,
                                      variant_id: str | None = None, qty_pcs: float = 0.0,
                                      input_material_id: str | None = None,
                                      color: str | None = None) -> dict:
    """Kebutuhan bahan menurut BOM untuk rencana potongan N pcs.

    Dipakai dialog Order Cutting supaya rencana pemakaian kain **tidak ditebak**.
    Selalu jujur: BOM tidak ada / kain terpilih tidak ada di BOM / satuan tidak jelas.
    """
    qty_pcs = _f(qty_pcs)
    out = {
        "model_id": model_id, "size_id": size_id, "variant_id": variant_id,
        "qty_pcs": _r(qty_pcs, 4), "bom_id": None, "bom_version": None,
        "size_code": "", "model_code": "", "model_name": "",
        "fabric": None, "panel": None, "plan_manual": False, "plan_note": "", "accessories": [], "others": [],
        "has_bom": False, "gaps": [], "uom_warnings": [],
        "other_sizes_with_bom": [],
    }
    model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0}) if model_id else None
    if not model:
        out["gaps"].append(_gap("model_missing", "Model tidak ditemukan di Master Produk.",
                                "Pilih model dari master", "wh-master"))
        return out
    out["model_code"] = model.get("code") or ""
    out["model_name"] = model.get("name") or ""

    color = (color or "").strip()
    if variant_id:
        # 2026-11-02 (F1b): varian membawa WARNA — BOM dipilih per warna (bukan hanya ukuran).
        v = await db.rahaza_model_variants.find_one(
            {"id": variant_id, "model_id": model_id},
            {"_id": 0, "size_id": 1, "size_code": 1, "color_code": 1, "color_name": 1, "color": 1})
        if not size_id:
            size_id = (v or {}).get("size_id")
            out["size_id"] = size_id
            out["size_code"] = (v or {}).get("size_code") or ""
        color = color or color_of(v)
    out["color"] = color
    if size_id and not out["size_code"]:
        s = await db.rahaza_sizes.find_one({"id": size_id}, {"_id": 0, "code": 1})
        out["size_code"] = (s or {}).get("code") or ""

    # size mana saja yang PUNYA BOM (supaya layar bisa mengarahkan)
    async for b in db.rahaza_boms.find({"model_id": model_id, "active": True},
                                       {"_id": 0, "size_id": 1, "size_code": 1, "version": 1}):
        code = b.get("size_code") or ""
        if not code and b.get("size_id"):
            s = await db.rahaza_sizes.find_one({"id": b["size_id"]}, {"_id": 0, "code": 1})
            code = (s or {}).get("code") or ""
        out["other_sizes_with_bom"].append({"size_id": b.get("size_id"), "size_code": code})

    if not size_id:
        out["gaps"].append(_gap(
            "size_missing",
            "Ukuran belum dipilih — BOM disimpan per model + ukuran, jadi kebutuhan bahan "
            "hanya bisa dihitung setelah varian/ukuran dipilih.",
            "Pilih varian (warna · size)", "cutting-orders"))
        return out

    bom, bom_match = await find_active_bom_ex(db, model_id, size_id, color)
    if not bom:
        out["gaps"].append(_gap(
            "bom_missing",
            f"Model {model.get('code')} ukuran {out['size_code'] or size_id} belum punya BOM — "
            f"kebutuhan kain tidak bisa dihitung, isi rencana manual atau buat BOM-nya dulu.",
            "Buat BOM untuk model + ukuran ini", "rnd-bom", size_id=size_id))
        return out

    out["has_bom"] = True
    out["bom_id"] = bom.get("id")
    out["bom_version"] = bom.get("version")
    out["bom_color"] = bom.get("color") or bom.get("color_code") or ""
    out["bom_color_match"] = bom_match
    if bom_match == BOM_MATCH_OTHER:
        out["gaps"].append(_gap(
            "bom_color_missing",
            f"Warna {color} ukuran {out['size_code'] or size_id} belum punya BOM sendiri — "
            f"angka di bawah memakai BOM warna {out['bom_color'] or 'lain'}; periksa sebelum dipakai.",
            "Buat BOM untuk warna ini", "rnd-bom", size_id=size_id, color=color))
    mats, warns = await bom_uom.ensure_uom(db, bom)
    out["uom_warnings"] = list(warns or [])

    input_mat = None
    if input_material_id:
        input_mat = await db.rahaza_materials.find_one({"id": input_material_id}, {"_id": 0})

    cache: dict = {}
    fabric_candidates = []
    for m in mats:
        mat = await _material_master(db, cache, m.get("material_id"), m.get("code"))
        qty_base = bom_uom.qty_base_of(m)
        unit_base = bom_uom.base_unit_of(m)
        row = {
            "material_id": m.get("material_id"), "code": m.get("code") or "",
            "name": m.get("name") or "", "material_type": m.get("material_type") or "",
            "group": _group_of(m.get("material_type") or (mat or {}).get("type")),
            "qty_per_pcs": _r(qty_base, 6), "unit": unit_base,
            "qty_total": _r(qty_base * qty_pcs, 4) if qty_pcs > 0 else 0.0,
            "qty_input": _r(m.get("qty"), 4), "unit_input": m.get("unit") or "",
            "uom_status": m.get("uom_status") or "", "uom_note": m.get("uom_note") or "",
            "unit_cost": _r(resolve_unit_cost(mat)),
        }
        row["amount_total"] = _r(row["qty_total"] * row["unit_cost"])
        if cut_panel_master.is_panel_material(mat) or cut_panel_master.is_panel_line(m):
            out["panel"] = row          # potongan yang akan DIHASILKAN order ini
            continue
        if row["group"] == "fabric":
            fabric_candidates.append(row)
        elif row["group"] == "accessory":
            out["accessories"].append(row)
        else:
            out["others"].append(row)

    if input_mat and not fabric_candidates and out.get("panel"):
        # BOM potongan: kain roll mana pun boleh dipotong (yang dicatat = kain terpakai nyata).
        pass
    elif input_mat:
        match = next((r for r in fabric_candidates if r["material_id"] == input_mat["id"]), None)
        if not match:
            match = next((r for r in (out["accessories"] + out["others"])
                          if r["material_id"] == input_mat["id"]), None)
        if match:
            out["fabric"] = {**match, "matches_input": True}
        else:
            out["fabric"] = fabric_candidates[0] if fabric_candidates else None
            if out["fabric"]:
                out["fabric"]["matches_input"] = False
            out["gaps"].append(_gap(
                "input_not_in_bom",
                f"Kain terpilih ({input_mat.get('code')} — {input_mat.get('name')}) TIDAK ada di "
                f"BOM ukuran ini. Angka BOM di bawah milik kain lain, jadi jangan dipakai "
                f"begitu saja.",
                "Ganti kain sesuai BOM, atau perbarui BOM-nya", "rnd-bom",
                material_id=input_mat.get("id")))
    elif fabric_candidates:
        out["fabric"] = {**fabric_candidates[0], "matches_input": None}

    out["fabric_candidates"] = fabric_candidates
    if not fabric_candidates and out.get("panel"):
        # 2026-09-12 (keputusan owner): BOM menyebut POTONGAN, bukan kain roll. Rencana
        # pemakaian roll diisi manual oleh operator — ini keadaan yang diharapkan, bukan cacat.
        out["plan_manual"] = True
        out["plan_note"] = (f"BOM ukuran ini memakai potongan {out['panel']['code']} (1 pcs/pcs). "
                            f"Rencana pemakaian kain roll diisi manual; biaya potongan lahir dari "
                            f"kain yang benar-benar dipotong ÷ pcs jadi.")
    elif not fabric_candidates:
        out["gaps"].append(_gap(
            "bom_without_fabric",
            "BOM ukuran ini tidak berisi baris kain/potongan — kebutuhan kain tidak bisa diusulkan.",
            "Tambahkan baris potongan pada BOM", "rnd-bom", bom_id=bom.get("id")))
    if out["fabric"] and out["fabric"].get("uom_status") in ("mismatch", "unlinked"):
        out["gaps"].append(_gap(
            "fabric_uom_unclear",
            f"Satuan baris kain BOM ({out['fabric']['unit_input']}) belum bisa dikonversi ke "
            f"satuan dasar — {out['fabric']['uom_note'] or 'lengkapi kemasan/gsm & lebar di master bahan'}.",
            "Lengkapi satuan bahan di Master Item", "wh-master"))
    return out
