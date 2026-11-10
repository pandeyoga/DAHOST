"""core.accessory_issue — pengeluaran (issue) aksesoris KANONIK.

KENAPA ADA (FASE 10 / prasyarat drop `accessory_legacy`)
Logika "keluarkan stok aksesoris" selama ini HANYA hidup di dalam route
`POST /api/acc/stock/issue`. Akibatnya jalur permintaan internal SSOT
(`POST /api/dewi/accessory-requests/{id}/deliver`) tidak bisa memakainya —
dan itulah alasan endpoint SSOT belum bisa menggantikan endpoint legacy
`PUT /api/acc/internal-requests/{id}` (yang memotong stok). Selama endpoint
legacy masih jadi satu-satunya jalur yang memotong stok, koleksi
`acc_internal_requests` tidak akan pernah bisa di-drop.

Modul ini mengangkat logika itu menjadi FUNGSI yang bisa dipakai siapa saja:
  * `check_availability` — validasi SEMUA baris SEBELUM ada stok yang dipotong
    (mencegah pengeluaran separuh jalan saat satu item kurang).
  * `issue_accessory`    — potong stok + kartu stok bernilai + jurnal pemakaian
    + alarm "belum dinilai" (persis perilaku route lama, satu sumber kebenaran).

Catatan impor: helper pencatat kartu stok (`_log_movement`) ada di modul route.
Untuk menghindari impor siklik, modul itu diimpor MALAS (di dalam fungsi).
"""
from __future__ import annotations

import logging

from core import accessory_valuation
from core import uom as _uom          # SSOT konversi satuan (input_unit boleh kode satuan)
from core.accessory_stock import (
    add_stock as _add_stock,
    get_accessory_location_id as _get_accessory_location_id,
    stock_qty as _stock_qty,
    usable_qty as _usable_qty,   # tanpa stok karantina (Tahap 1, 2026-11-06)
)

_log = logging.getLogger(__name__)


class IssueError(ValueError):
    """Kesalahan yang layak ditampilkan ke user (bukan bug)."""

    def __init__(self, message: str, *, status: int = 400, code: str = "", data: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code          # 2026-11-06 (Tahap 2): mis. "over_issue" → layar meminta alasan
        self.data = data or {}


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-06 (Tahap 2) — AKUN BEBAN PER DIVISI PEMOHON / PER PO (keputusan owner)
# ═════════════════════════════════════════════════════════════════════════════
# Dulu setiap pengeluaran aksesoris dijurnal Dr WIP 1-1403, termasuk ATK kantor dan bahan promosi.
# Sekarang tujuan biaya (cost target) menentukan PERAN profil posting `inventory_issue`
# (diubah Finance di Pengaturan Keuangan › Pemetaan akun otomatis — tidak ada kode akun di sini):
#   * terikat PO  → jenis PO: maklon = biaya bahan pesanan maklon (K42), internal = WIP;
#   * sampel R&D  → peran sampel R&D;
#   * selain itu  → divisi pemohon (daftar tunggal di bawah, dipakai layar lewat /api/acc/divisions).
COST_WIP = "wip"
COST_MAKLON = "maklon"
COST_OFFICE = "kantor"
COST_MARKETING = "pemasaran"
COST_OTHER = "lainnya"
COST_RND = "sampel_rnd"
# Tahap 9 (keputusan owner 7 Nov No. 5): bahan pembantu (benang dsb.) — beban produksi langsung (5-3400) saat
# dikeluarkan, BUKAN WIP. Pengecualian aturan 6 Nov "divisi Produksi → 1-1403". Penanda bahan pembantu = master
# kategori material (`core.hpp_aktual.category_is_aux`), bukan daftar baru di sini.
COST_AUX = "bahan_pembantu"

# SATU daftar divisi pemohon (dulu tersalin di AccessoryModule.jsx & dewi_accessories_stock.py).
DIVISIONS = (
    {"value": "Produksi", "cost_target": COST_WIP},
    {"value": "Cutting", "cost_target": COST_WIP},
    {"value": "CMT", "cost_target": COST_WIP},
    {"value": "Gudang", "cost_target": COST_OFFICE},
    {"value": "Kantor", "cost_target": COST_OFFICE},
    {"value": "SDM", "cost_target": COST_OFFICE},
    {"value": "QC", "cost_target": COST_WIP},
    {"value": "Packing", "cost_target": COST_WIP},
    {"value": "Marketing", "cost_target": COST_MARKETING},
    {"value": "Lainnya", "cost_target": COST_OTHER},
)
DIVISION_NAMES = tuple(d["value"] for d in DIVISIONS)

# Peran profil posting per tujuan biaya. Bentuk {event: {tujuan: peran}} supaya dibaca registri
# keterikatan akun (`core.coa_bindings.PROFILE_ROLE_TABLES`) tanpa disalin.
PROFILE_ROLES = {
    "inventory_issue": {
        COST_WIP: "debit_wip",
        COST_MAKLON: "debit_maklon_material",
        COST_OFFICE: "debit_accessory_office",
        COST_MARKETING: "debit_accessory_marketing",
        COST_OTHER: "debit_accessory_other",
        COST_RND: "debit_accessory_rnd_sample",
        COST_AUX: "debit_production_supplies",
    },
}
COST_TARGET_LABELS = {
    COST_WIP: "Barang dalam proses (produksi)",
    COST_MAKLON: "Biaya bahan pesanan maklon",
    COST_OFFICE: "Beban ATK & perlengkapan",
    COST_MARKETING: "Beban pemasaran",
    COST_OTHER: "Beban umum",
    COST_RND: "Beban sampel R&D",
    COST_AUX: "Bahan pembantu produksi (beban, tidak masuk HPP)",
}
# Tujuan biaya yang berubah menjadi bahan pembantu bila barangnya bahan pembantu (PO maklon tetap nota antar CV;
# divisi kantor/pemasaran tetap beban divisinya).
AUX_REPLACES = (COST_WIP,)


async def aux_cost_target(db, material: dict | None, cost_target: str) -> str:
    """Tujuan biaya akhir satu barang: bahan pembantu menggantikan WIP (keputusan No. 5)."""
    if (cost_target or COST_WIP) not in AUX_REPLACES:
        return cost_target or COST_WIP
    from core.hpp_aktual import is_bahan_pembantu
    return COST_AUX if await is_bahan_pembantu(db, material) else (cost_target or COST_WIP)
VENDOR_REQUEST_TYPES = ("vendor_additional", "vendor_replacement")
# Pemilik barang "stok DA" & status MI yang tidak dihitung — definisi milik mesin Material Issue
from core.material_issue_engine import MAKLON_DA_OWNERSHIP as DA_OWNERSHIP  # noqa: E402
from core.material_issue_engine import _MI_NOT_COUNTED  # noqa: E402


def normalize_division(divisi) -> str:
    """Nama divisi kanonik dari daftar tunggal ('' bila tidak dikenal)."""
    key = str(divisi or "").strip().lower()
    return next((d for d in DIVISION_NAMES if d.lower() == key), "")


def division_cost_target(divisi) -> str:
    name = normalize_division(divisi)
    return next((d["cost_target"] for d in DIVISIONS if d["value"] == name), "")


def debit_role(cost_target: str) -> str:
    """Peran profil `inventory_issue` untuk satu tujuan biaya (bawaan: WIP, perilaku lama)."""
    roles = PROFILE_ROLES["inventory_issue"]
    return roles.get(cost_target or COST_WIP) or roles[COST_WIP]


async def resolve_cost_target(db, *, divisi: str = "", po_id: str = "",
                              request_type: str = "") -> dict:
    """Tujuan biaya satu pengeluaran → {cost_target, divisi, po_id, po_number, business_type}.

    Urutan: PO (jenis PO menang atas divisi) → sampel R&D → tambahan/pengganti vendor tanpa PO (WIP,
    barangnya untuk produksi CMT) → divisi pemohon. Divisi tidak dikenal ⇒ IssueError (akun tak bisa
    ditentukan; lebih baik ditanyakan daripada diam-diam dibebankan ke WIP)."""
    out = {"divisi": normalize_division(divisi), "po_id": "", "po_number": "", "business_type": ""}
    if po_id:
        po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "id": 1, "po_number": 1,
                                                              "business_type": 1})
        if not po:
            raise IssueError("PO produksi yang terkait permintaan ini tidak ditemukan.", status=404)
        bt = (po.get("business_type") or "internal").strip().lower()
        out.update(po_id=po["id"], po_number=po.get("po_number") or "", business_type=bt,
                   cost_target=COST_MAKLON if bt == "maklon" else COST_WIP)
        return out
    if request_type == "rnd_sample":
        return {**out, "cost_target": COST_RND}
    if request_type in VENDOR_REQUEST_TYPES:
        return {**out, "cost_target": COST_WIP}
    target = division_cost_target(divisi)
    if not target:
        raise IssueError("Pilih divisi pemohon dulu — divisi menentukan akun beban pemakaian aksesoris. "
                         f"Pilihan: {', '.join(DIVISION_NAMES)}.")
    return {**out, "cost_target": target}


# ── satu kebutuhan per PO: kebutuhan vs yang sudah keluar (jalur permintaan + Kirim Material CMT) ──
def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def po_need_by_material(db, po: dict) -> dict:
    """{material_id: qty} kebutuhan aksesoris MILIK DA untuk satu PO (`po_accessories`, satuan dasar).

    PO maklon: hanya baris milik DA — baris disediakan klien (atau tanpa keterangan pemilik) bukan
    stok DA, jadi kebutuhannya 0 di sini."""
    maklon = (po.get("business_type") or "") == "maklon"
    need: dict = {}
    async for r in db.po_accessories.find({"po_id": po.get("id")}, {"_id": 0}):
        mid = r.get("accessory_id")
        if not mid:
            continue
        if maklon and (r.get("ownership") or "") not in DA_OWNERSHIP:
            continue
        need[mid] = need.get(mid, 0.0) + _f(r.get("qty_needed"))
    return need


async def request_issued_for_po(db, po_id: str) -> dict:
    """{material_id: qty} aksesoris yang SUDAH keluar untuk PO lewat jalur permintaan / Keluar manual.

    Sumber: baris kartu stok `movement_type='issue'` ber-`po_id` (sejak Tahap 2) + permintaan lama
    ber-PO yang sudah menyerahkan barang sebelum baris kartu stok membawa `po_id`."""
    out: dict = {}
    if not po_id:
        return out
    async for mv in db.rahaza_material_movements.find(
            {"po_id": po_id, "movement_type": "issue"}, {"_id": 0, "material_id": 1, "qty": 1, "qty_signed": 1}):
        q = abs(_f(mv.get("qty_signed") if mv.get("qty_signed") is not None else mv.get("qty")))
        out[mv.get("material_id")] = out.get(mv.get("material_id"), 0.0) + q
    async for req in db.dewi_accessory_requests.find(
            {"po_id": po_id, "stock_issued": True, "issue_linked_po": {"$ne": True}},
            {"_id": 0, "stock_issue_results": 1}):
        for r in req.get("stock_issue_results") or []:
            out[r.get("material_id")] = out.get(r.get("material_id"), 0.0) + _f(r.get("qty"))
    return out


async def mi_issued_for_po(db, po_id: str) -> dict:
    """{material_id: qty} yang sudah keluar untuk PO lewat dokumen Material Issue (Kirim Material CMT)."""
    out: dict = {}
    if not po_id:
        return out
    async for mi in db.rahaza_material_issues.find(
            {"production_po_id": po_id, "status": {"$nin": list(_MI_NOT_COUNTED)}}, {"_id": 0, "items": 1}):
        for it in mi.get("items") or []:
            out[it.get("material_id")] = out.get(it.get("material_id"), 0.0) + _f(it.get("qty_issued"))
    return out


async def request_credit_for_po(db, po_id: str) -> dict:
    """{material_id: qty} pengeluaran lewat permintaan untuk PO INTERNAL yang belum diperhitungkan
    Kirim Material CMT. Yang sudah diperhitungkan dicatat per surat jalan
    (`vendor_shipments.accessory_request_offsets`), jadi tidak dipakai dua kali."""
    issued = await request_issued_for_po(db, po_id)
    if not issued:
        return {}
    used: dict = {}
    async for s in db.vendor_shipments.find({"po_id": po_id}, {"_id": 0, "accessory_request_offsets": 1}):
        for o in s.get("accessory_request_offsets") or []:
            used[o.get("material_id")] = used.get(o.get("material_id"), 0.0) + _f(o.get("qty"))
    return {mid: round(q - used.get(mid, 0.0), 4) for mid, q in issued.items()
            if q - used.get(mid, 0.0) > 1e-9}


async def po_issued_by_material(db, po_id: str) -> dict:
    """Total keluar per material untuk satu PO = jalur permintaan + Material Issue."""
    out = await mi_issued_for_po(db, po_id)
    for mid, q in (await request_issued_for_po(db, po_id)).items():
        out[mid] = out.get(mid, 0.0) + q
    return out


def over_issue_lines(rows: list, need: dict, issued: dict) -> list:
    """Fungsi murni: baris yang membuat total keluar melebihi kebutuhan PO.

    `rows` = [{material, qty}] hasil `check_availability`. Return [{material_id, code, name, need,
    issued, qty, over}] — kosong bila semua masih dalam kebutuhan."""
    out, running = [], dict(issued)
    for r in rows:
        mid = r["material"]["id"]
        before = _f(running.get(mid))
        after = before + _f(r["qty"])
        running[mid] = after
        n = _f(need.get(mid))
        if after > n + 1e-6:
            out.append({"material_id": mid, "code": r["material"].get("code", ""),
                        "name": r["material"].get("name", ""), "need": round(n, 4),
                        "issued": round(before, 4), "qty": round(_f(r["qty"]), 4),
                        "over": round(after - max(n, before), 4)})
    return out


async def guard_po_over_issue(db, target: dict, rows: list, reason: str = "") -> list:
    """Aturan owner (lebih dari kebutuhan boleh, WAJIB beralasan): pengeluaran ber-PO yang membuat
    total keluar untuk PO itu (jalur permintaan + Kirim Material CMT) melebihi kebutuhan PO ditolak
    tanpa alasan. Return baris kelebihan (untuk disimpan bersama alasannya)."""
    po_id = (target or {}).get("po_id")
    if not po_id:
        return []
    # Tahap 9: bahan pembantu (benang) bukan kebutuhan per PO — tidak dibandingkan dengan kebutuhan PO
    from core.hpp_aktual import aux_category_keys, material_is_aux
    aux_keys = await aux_category_keys(db)
    rows = [r for r in rows if not material_is_aux(r.get("material"), aux_keys)]
    if not rows:
        return []
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "id": 1, "business_type": 1})
    lines = over_issue_lines(rows, await po_need_by_material(db, po or {"id": po_id}),
                             await po_issued_by_material(db, po_id))
    if lines and not str(reason or "").strip():
        detail = "; ".join(f"{ln['code'] or ln['name']}: kebutuhan PO {ln['need']:g}, sudah keluar "
                           f"{ln['issued']:g}, diminta {ln['qty']:g}" for ln in lines)
        raise IssueError(
            f"Pengeluaran melebihi kebutuhan PO {target.get('po_number') or ''} — {detail}. "
            "Isi alasan kelebihan supaya bisa diteruskan.",
            code="over_issue", data={"lines": lines, "po_number": target.get("po_number") or ""})
    return lines


async def resolve_material(db, *, acc_id: str = "", code: str = "") -> dict | None:
    """Cari master aksesoris berdasarkan id, atau kode (fallback data lama)."""
    if acc_id:
        mat = await db.rahaza_materials.find_one(
            {"id": acc_id, "type": "accessory", "active": True})
        if mat:
            return mat
    if code:
        return await db.rahaza_materials.find_one(
            {"code": code, "type": "accessory", "active": True})
    return None


async def check_availability(db, items: list[dict]) -> list[dict]:
    """Validasi baris permintaan SEBELUM stok dipotong.

    `items`: [{material_id?, material_code?, qty, unit?, ...}]
    Return: daftar baris tervalidasi [{material, qty, unit}] — melempar `IssueError`
    dengan pesan yang bisa langsung dibaca user bila ada yang tidak lolos.
    """
    if not items:
        raise IssueError("Permintaan tidak punya baris item.")
    resolved: list[dict] = []
    problems: list[str] = []
    needed: dict[str, float] = {}
    for it in items:
        qty = float(it.get("qty") or it.get("qty_requested") or 0)
        mat = await resolve_material(
            db, acc_id=str(it.get("material_id") or it.get("acc_id") or ""),
            code=str(it.get("material_code") or it.get("acc_code") or ""))
        label = (it.get("material_code") or it.get("material_name")
                 or it.get("acc_name") or "(tanpa nama)")
        if not mat:
            problems.append(f"{label}: master aksesoris tidak ditemukan/nonaktif")
            continue
        if qty <= 0:
            problems.append(f"{mat.get('code') or label}: qty harus lebih dari 0")
            continue
        needed[mat["id"]] = needed.get(mat["id"], 0) + qty
        resolved.append({"material": mat, "qty": qty,
                         "unit": it.get("unit") or mat.get("unit", "pcs")})
    mats = {r["material"]["id"]: r["material"] for r in resolved}
    short = await _short_rows(db, needed, mats)
    for s in short:
        problems.append(
            f"{s['material_code'] or s['material_name']}: stok tidak cukup "
            f"(butuh {s['needed']:g}, bisa dipakai {s['usable']:g}; stok karantina tidak ikut)")
    if problems:
        # 2026-11-10: baris kurang stok ikut dikirim (`data.short_lines`) supaya layar serah bisa
        # menawarkan draf pembelian untuk kekurangannya. Tanpa `code` → pemanggil lain tetap
        # menampilkan pesan teks seperti dulu.
        raise IssueError("Tidak bisa mengeluarkan stok — " + "; ".join(problems),
                         data={"short_lines": short, "other_problems": len(problems) - len(short)})
    return resolved


async def _short_rows(db, needed: dict, mats: dict) -> list[dict]:
    """{material_id: qty dibutuhkan} → baris yang stoknya (tanpa karantina) tidak cukup."""
    out = []
    for mat_id, total in needed.items():
        have = await _usable_qty(db, mat_id)
        if have < total:
            mat = mats.get(mat_id) or {}
            usable = round(max(float(have or 0), 0.0), 4)
            out.append({
                "material_id": mat_id,
                "material_code": mat.get("code") or "",
                "material_name": mat.get("name") or "",
                "unit": mat.get("unit") or "pcs",
                "needed": round(total, 4),
                "usable": usable,
                "short": round(total - usable, 4),
                "unit_cost": float(mat.get("unit_cost") or mat.get("hpp") or 0),
            })
    return out


async def shortage_lines(db, items: list[dict]) -> dict:
    """Kekurangan stok untuk baris permintaan yang SUDAH tertaut master (2026-11-10).

    Dipakai tombol "Buat draf pembelian" di serah permintaan: hitungan sama dengan
    `check_availability` (qty per material dijumlah, stok karantina tidak ikut).
    Return {lines: [...], unlinked: jumlah baris tanpa master}."""
    needed: dict[str, float] = {}
    mats: dict[str, dict] = {}
    unlinked = 0
    for it in items or []:
        mat = await resolve_material(
            db, acc_id=str(it.get("material_id") or it.get("acc_id") or ""),
            code=str(it.get("material_code") or it.get("acc_code") or ""))
        if not mat:
            unlinked += 1
            continue
        qty = float(it.get("qty") or it.get("qty_requested") or 0)
        if qty <= 0:
            continue
        needed[mat["id"]] = needed.get(mat["id"], 0) + qty
        mats[mat["id"]] = mat
    return {"lines": await _short_rows(db, needed, mats), "unlinked": unlinked}


async def issue_accessory(db, user: dict, *, acc_id: str, qty: float,
                          input_unit: str = "base", notes: str = "",
                          ref_type: str = "manual", ref_id: str = "",
                          target: dict | None = None, over_issue_reason: str = "",
                          guard_po: bool = False) -> dict:
    """Keluarkan stok aksesoris (bernilai + berjurnal). Melempar `IssueError` bila tidak valid.

    2026-11-06 (Tahap 2): `target` = hasil `resolve_cost_target` (tujuan biaya + PO/divisi). Dibawa ke
    baris kartu stok supaya jurnal memakai akun yang benar dan Kirim Material CMT tahu apa yang sudah
    keluar untuk PO yang sama. Tanpa `target` → WIP (perilaku lama)."""
    from routes.dewi_accessories_stock import _log_movement  # lazy: hindari impor siklik
    from routes.rahaza_posting import post_accessory_issue  # lazy: modul berat

    try:
        qty = float(qty)
    except (TypeError, ValueError):
        raise IssueError("qty harus angka")
    if not acc_id or qty <= 0:
        raise IssueError("acc_id dan qty > 0 wajib diisi")

    item = await db.rahaza_materials.find_one(
        {"id": acc_id, "type": "accessory", "active": True})
    if not item:
        raise IssueError("Aksesoris tidak ditemukan", status=404)

    pack_size = float(item.get("pack_size") or 1) or 1
    # 2026-08-05 — `input_unit` boleh: "base" | "pack" (legacy) | KODE SATUAN dari
    # SSOT UoM (mis. "box", "lusin", "gram"). Perilaku legacy tidak berubah.
    _u = str(input_unit or "base").strip().lower()
    if _u == "pack":
        qty_base = qty * pack_size
    elif _u in ("", "base"):
        qty_base = qty
    else:
        try:
            from core import bom_uom as _bom_uom   # cakupan lebar (kemasan + global)
            _f, _src = _bom_uom.factor_to_base(item, _u)
            qty_base = round(qty * _f, 4)
        except _uom.UomError as e:
            raise IssueError(str(e))

    current = await _usable_qty(db, acc_id)
    if current < qty_base:
        raise IssueError(f"Stok tidak cukup. Stok yang bisa dipakai: {current:g} "
                         f"(stok di lokasi karantina tidak ikut).")
    tgt = dict(target or {})
    cost_target = await aux_cost_target(db, item, tgt.get("cost_target") or COST_WIP)
    if guard_po and tgt.get("po_id") and cost_target != COST_AUX:
        # satu kebutuhan per PO: kelebihan dari kebutuhan PO wajib beralasan (sebelum stok dipotong)
        await guard_po_over_issue(db, target, [{"material": item, "qty": qty_base}], over_issue_reason)

    loc_id = await _get_accessory_location_id(db)
    await _add_stock(db, acc_id, loc_id, -qty_base)

    unit_cost = accessory_valuation.resolve_unit_cost(item)
    extra = {"cost_target": cost_target}
    for k in ("divisi", "po_id", "po_number"):
        if tgt.get(k):
            extra[k] = tgt[k]
    if over_issue_reason:
        extra["over_issue_reason"] = over_issue_reason
    mv = await _log_movement(
        db, user, material_id=acc_id, mv_type="issue", qty=-qty_base,
        related_type=ref_type, related_ref=ref_id, notes=notes, unit_cost=unit_cost,
        extra=extra,
    )
    je = {"posted": False,
          "error": "Harga satuan belum diisi — jurnal pemakaian tidak dibuat."}
    if unit_cost <= 0:
        await accessory_valuation.notify_unvalued(
            db, material=item, movement_type="issue", qty=qty_base, actor=user)
    elif mv:
        try:
            res = await post_accessory_issue(db, mv, user)
            je = {"posted": bool(res.get("ok")), "je_id": res.get("je_id"),
                  "je_number": res.get("je_number"), "error": res.get("error"),
                  "amount": res.get("amount")}
        except Exception as e:  # noqa: BLE001 — jurnal gagal tidak membatalkan stok
            _log.warning("[acc-issue] posting jurnal gagal: %s", e)
            je = {"posted": False, "error": str(e)}

    new_qty = await _stock_qty(db, acc_id)
    return {
        "ok": True,
        "material_id": acc_id,
        "material_code": item.get("code", ""),
        "material_name": item.get("name", ""),
        "new_qty": new_qty,
        "qty_issued": qty_base,
        "unit": item.get("unit", "pcs"),
        "unit_cost": round(unit_cost, 4),
        "value": round(qty_base * unit_cost, 2),
        "stock_value": round(new_qty * unit_cost, 2),
        "movement_id": (mv or {}).get("id", ""),
        "cost_target": cost_target,
        "je": je,
    }
