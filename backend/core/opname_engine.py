"""core.opname_engine — SATU mesin opname ("Sesi Opname") untuk kain, aksesoris, dan barang jadi.

2026-11-02 — keputusan owner K9 (desain g.md No.17 §5):
  * "setuju, tanpa kunci nanti bisa di sesuaikan" → TIDAK ada pembekuan. Transaksi tetap jalan;
    stok sistem sebuah baris pada saat dihitung = snapshot + Σ mutasi `rahaza_stock_ledger`
    (material, lokasi) yang terjadi di antara jam snapshot dan `counted_at` baris itu.
  * "tidak perlu ada ambang hitung ulang, hanya diberikan saja selisihnya" → selisih hanya
    ditampilkan; tidak ada toleransi / hitung ulang wajib.
  * "dipisahkan saja pakai mesin yang sama" → opname aksesoris tetap punya menu di Portal
    Aksesoris, tetapi memanggil mesin ini (routes/dewi_accessories_opname.py = pembungkus).

Dulu ada DUA mesin dengan aturan berbeda (g.md No.17 §2a/§2b):
  * opname3 WMS: stok sistem = ISI BIN (bukan saldo) → barang belum dirak dihitung dobel
    (Y 30 → 60 → 90), barang keluar dipotong dobel, bin tak di-scan = 0, FG tanpa jurnal,
    minus tidak bisa diperbaiki, `adjust_material` memotong baris karantina.
  * opname aksesoris: stok sistem = total SEMUA lokasi tetapi selisih ditulis ke satu lokasi,
    baris tak dihitung dilewati, satu jurnal per material.

Aturan mesin ini:
  1. Cakupan WAJIB satu lokasi `rahaza_locations` (+ zona `wh_*` yang tertaut ke lokasi itu lewat
     `wh_location_migration_map` / field `location_id`). Opsional sub-cakupan zona/rak/bin,
     filter jenis (bahan/aksesoris/fg), dan daftar material (cycle count).
  2. Level LOKASI: snapshot = saldo `rahaza_material_stock` per (material, lokasi). Semua barang
     di lokasi dihitung (sudah dirak maupun belum); hasilnya MENIMPA saldo (set absolut lewat
     `stock_service.adjust`, jadi baris minus otomatis hilang) dan sekaligus memperbarui
     penempatan bin. Level RAK (ada sub-cakupan): hanya memperbaiki PENEMPATAN bin.
  3. Hitung buta: selama status `counting` qty sistem tidak dikirim ke layar. Baris belum
     dihitung berstatus eksplisit "belum" (≠ 0); submit hitung penuh meminta konfirmasi
     "anggap 0".
  4. Approve: SATU jurnal per sesi, idempoten `opname:{id}`. Akun persediaan per jenis lewat
     jalur yang sudah ada (`rahaza_posting.inventory_account`, profil `inventory_adjust`:
     1-1401 / 1-1402 / 1-1404); lawannya profil `inventory_count_variance`
     (selisih 5-1950, baris beralasan "rusak" 6-4300). Nilai = selisih × WAC saat snapshot.
  5. Lokasi karantina adalah lokasi tersendiri: tidak bisa dipilih di sini, dan opname lokasi lain
     hanya menulis baris (material, lokasi-sesi) — baris karantina tidak tersentuh.
  6. Kontrak paket scan keluar (K15): approve DITOLAK (409) selama ada `wh_scan_out_sheets`
     `status='open'` di lokasi itu dengan `date` ≤ tanggal hitung (WIB). Dibaca langsung dari
     koleksinya; modul paket itu tidak diimpor.

Penyimpanan: koleksi yang sudah ada dipakai ulang (tanpa koleksi/nomor dokumen baru):
  `wh_opname3_sessions` (dokumen ber-`engine='k9'`; dokumen lama tanpa field ini = ARSIP
  baca-saja), `wh_opname3_counts` (hitungan per sesi × material × bin, bin '' = lantai/belum
  dirak). Sesi aksesoris lama (`wh_opname_sessions2`) juga arsip baca-saja.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from fastapi import HTTPException

from core import stock_service
from core import scan_resolver
from core import uom as _uom
from core import bom_uom as _bom_uom
from utils.waktu import fmt_wib, wib_date_str

log = logging.getLogger(__name__)

SESS = "wh_opname3_sessions"
CNT = "wh_opname3_counts"
LEGACY_ACC = "wh_opname_sessions2"
POS = "wh_positions"
SCAN_OUT = "wh_scan_out_sheets"          # milik paket scan keluar (K15) — hanya DIBACA
SCAN_OUT_LINES = "wh_scan_out_lines"     # 2026-11-06 (Tahap 2): baris gagal juga menahan approve
SCAN_CLAIM_STALE_SECONDS = 30            # = core.scan_out.CLAIM_STALE_SECONDS (modulnya tidak diimpor)


def _claim_stale(at) -> bool:
    """Klaim proses baris scan yang sudah putus (baris `pending` yang tidak sedang diproses)."""
    if isinstance(at, datetime) and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return not isinstance(at, datetime) or at < datetime.now(timezone.utc) - timedelta(seconds=SCAN_CLAIM_STALE_SECONDS)
ENGINE = "k9"

LEVEL_LOKASI, LEVEL_RAK = "lokasi", "rak"
SUB_TYPES = ("zone", "rack", "bin")
KINDS = ("bahan", "aksesoris", "fg")
KIND_LABELS = {"bahan": "Kain / Bahan", "aksesoris": "Aksesoris", "fg": "Barang Jadi"}
ST_BELUM, ST_DIHITUNG, ST_NOL = "belum", "dihitung", "nol"
REASONS = ("", "rusak")
RESOLUTIONS = ("pindah", "lebih")
# Operasi ledger yang TIDAK mengubah qty fisik (hanya reservasi) — tidak ikut "mutasi selama sesi".
NON_QTY_OPS = frozenset({"reserve", "release", "reserve_row", "release_material"})

# Profil posting lawan selisih opname (didaftarkan di core/coa_bindings.PROFILE_ROLE_TABLES).
VARIANCE_EVENT = "inventory_count_variance"
CONTRA_ROLES = {VARIANCE_EVENT: {"selisih": "adjustment_expense", "rusak": "debit_scrap_expense"}}

# Gabungan role penyetuju lama opname3 + opname aksesoris (selama izin role belum diatur owner).
APPROVE_ROLES = ["admin", "admin_gudang", "supervisor", "supervisor_produksi", "manajer", "manager",
                 "warehouse_manager", "superadmin", "owner"]

# ── 2026-11-09 — OPNAME STOK AWAL (klarifikasi owner C3-b, audit gudang G7★a) ─────────────────────
# Opname biasa menjurnal selisih lebih ke 5-1950 (akun HPP) ⇒ bila dipakai sebagai stok awal, SELURUH nilai
# stok awal menaikkan laba bulan berjalan. Mode "stok awal": lawan jurnal = akun ekuitas saldo awal yang
# SAMA dengan layar Saldo Awal (`core.opening_balance.retained_earnings_code`, bawaan 3-2000), hanya Keuangan/
# owner yang menyetujui, baris berstok tanpa harga DITOLAK (daftar dikembalikan), satu kali per barang×lokasi
# (penanda mutasi `type='opening'`, sama dengan impor Excel STOK_AWAL), dan ditolak bila Saldo Awal sudah
# mengisi akun persediaan jenis yang sama (dobel). FG dinilai WAC; bila belum ada, HPP standar master.
MODE_OPENING = "opening"
OPENING_EVENT = "inventory_opening_count"     # source_module jurnal opname stok awal
OPENING_APPROVE_PERMS = ("finance.manage", "finance.approve")


def is_opening(sess: Optional[dict]) -> bool:
    return (sess or {}).get("mode") == MODE_OPENING


def hpp_components(mat: Optional[dict]) -> Optional[dict]:
    """Komponen HPP standar per pcs dari `hpp_breakdown` master FG (bahan / upah CMT+internal / overhead)."""
    bd = (mat or {}).get("hpp_breakdown") or {}
    f = lambda k: float(bd.get(k) or 0)  # noqa: E731
    comps = {"material": f("material"), "labor": f("cmt") + f("internal_labor"), "overhead": f("overhead")}
    return comps if sum(comps.values()) > 0 else None


async def opening_unit_cost(db, mat: dict) -> tuple:
    """(harga per satuan dasar, sumber, komponen|None) untuk opname stok awal.

    FG: WAC bila sudah ada; selain itu HPP standar master (`hpp`, kalkulator BOM + upah) — keputusan G7★a.
    Bahan/aksesoris: harga master (`unit_cost`). Tanpa harga → (0, '', None) ⇒ approve ditolak."""
    if kind_of(mat) == "fg":
        wac = await _wac(db, mat)
        if wac > 0:
            return wac, "wac", None
        hpp = round(float((mat or {}).get("hpp") or 0), 4)
        return (hpp, "hpp_standar", hpp_components(mat)) if hpp > 0 else (0.0, "", None)
    uc = round(float((mat or {}).get("unit_cost") or 0), 4)
    return (uc, "harga_master", None) if uc > 0 else (0.0, "", None)


def opening_problems(lines: list, *, opened: set, client_ids: set) -> dict:
    """Pemeriksaan baris opname stok awal (fungsi murni, diuji unit) → {kunci: [baris]}.

    lines     : baris terevaluasi (`variance_qty`, `unit_cost`, `material_id`, …)
    opened    : material_id yang SUDAH punya stok awal di lokasi sesi
    client_ids: material_id barang jadi milik klien maklon"""
    out = {"tanpa_harga": [], "berkurang": [], "sudah_ada_stok_awal": [], "barang_klien": []}
    for x in lines:
        var = float(x.get("variance_qty") or 0)
        if not var:
            continue
        row = {"material_code": x.get("material_code"), "material_name": x.get("material_name"),
               "unit": x.get("unit"), "counted_qty": x.get("counted_qty"), "system_qty": x.get("system_qty"),
               "variance_qty": var}
        if x.get("material_id") in client_ids:
            out["barang_klien"].append(row)
        elif var < 0:
            out["berkurang"].append(row)
        elif x.get("material_id") in opened:
            out["sudah_ada_stok_awal"].append(row)
        elif float(x.get("unit_cost") or 0) <= 0:
            out["tanpa_harga"].append(row)
    return {k: v for k, v in out.items() if v}


OPENING_PROBLEM_TEXT = {
    "tanpa_harga": "barang berstok tanpa harga (isi harga master / HPP standar FG dulu — stok tanpa nilai membuat "
                   "HPP penjualan Rp 0 dan nilainya terhitung dua kali saat barang bernilai pertama masuk)",
    "berkurang": "hitungan lebih kecil dari stok sistem (opname stok awal hanya MENAMBAH stok yang belum tercatat — "
                 "pakai Sesi Opname biasa untuk koreksi)",
    "sudah_ada_stok_awal": "barang×lokasi ini sudah pernah dimuat stok awalnya (Excel STOK_AWAL atau opname stok "
                           "awal) — koreksi lewat Sesi Opname biasa",
    "barang_klien": "barang jadi milik klien maklon (titipan) — catat lewat Titipan Klien, bukan persediaan DA",
}

def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _r(v) -> float:
    return round(float(v or 0), 4)


# ═════════════════════════════ FUNGSI MURNI (diuji unit) ═════════════════════════════
def aware(dt) -> Optional[datetime]:
    """datetime → aware UTC. Motor mengembalikan datetime NAIF (UTC); string ISO juga diterima."""
    if dt is None or dt == "":
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def wib_date(dt) -> str:
    """Tanggal kalender WIB 'YYYY-MM-DD' (kontrak `wh_scan_out_sheets.date`) — delegasi ke SSOT utils.waktu."""
    return wib_date_str(aware(dt) or _now())


def effective_at(row: dict) -> Optional[datetime]:
    """Jam KEJADIAN mutasi ledger. Bawaan = `created_at`; penulis boleh memberi
    `ref.effective_at` (mis. scan susulan K15 yang dicatat setelah barangnya keluar)."""
    ref = row.get("ref") or {}
    for k in ("effective_at", "occurred_at", "scanned_at"):
        v = aware(ref.get(k)) if isinstance(ref, dict) else None
        if v:
            return v
    return aware(row.get("created_at"))


def system_qty_at(snapshot_qty: float, ledger_rows: Iterable[dict], snapshot_at, counted_at) -> tuple:
    """(stok sistem saat baris dihitung, Σ mutasi selama sesi) — tanpa kunci (K9).

    = snapshot + Σ delta ledger yang DICATAT setelah snapshot dan TERJADI ≤ `counted_at`.
    Reservasi (NON_QTY_OPS) tidak mengubah qty fisik → diabaikan."""
    t0, tc = aware(snapshot_at), aware(counted_at)
    mut = 0.0
    for row in ledger_rows:
        if row.get("op") in NON_QTY_OPS:
            continue
        created = aware(row.get("created_at"))
        if t0 is not None and created is not None and created <= t0:
            continue
        eff = effective_at(row)
        if tc is not None and eff is not None and eff > tc:
            continue
        mut += float(row.get("delta") or 0)
    return _r(float(snapshot_qty or 0) + mut), _r(mut)


def line_key(material_id: str, bin_id: str, level: str) -> str:
    """Kunci baris: level lokasi = per material; level rak = per (material, bin)."""
    return f"{material_id}@{bin_id or ''}" if level == LEVEL_RAK else material_id


def line_status(line: dict, n_entries: int) -> str:
    if line.get("status") == ST_NOL:
        return ST_NOL
    return ST_DIHITUNG if n_entries > 0 else ST_BELUM


def plan_stock_writes(rows: list, target: float, home_location_id: str) -> list:
    """Baris stok (dalam himpunan lokasi sesi) yang harus di-SET supaya Σ = `target`.

    Baris utama = baris lokasi sesi (bila ada), selain itu baris |qty| terbesar; ia menyerap
    selisih. Bila baris utama akan minus, baris lain di-nol-kan dan baris utama = target.
    Return [(location_id, qty_baru)] hanya untuk baris yang berubah."""
    target = _r(target)
    rows = [r for r in rows if r.get("location_id")]
    if not rows:
        return [(home_location_id, target)] if target != 0 else []
    primary = next((r for r in rows if r.get("location_id") == home_location_id), None) \
        or max(rows, key=lambda r: abs(float(r.get("qty") or 0)))
    others = [r for r in rows if r is not primary]
    rest = _r(sum(float(r.get("qty") or 0) for r in others))
    out = []
    if _r(target - rest) >= 0:
        new_primary = _r(target - rest)
    else:
        for r in others:
            if _r(r.get("qty")) != 0:
                out.append((r["location_id"], 0.0))
        new_primary = target
    if _r(primary.get("qty")) != new_primary:
        out.append((primary["location_id"], new_primary))
    return out


def plan_location_placement(positions: list, entries: list, totals: dict) -> tuple:
    """Penempatan bin setelah hitung LEVEL LOKASI.

    positions : bin di lokasi `[{id, material_id, qty}]`
    entries   : hitungan `[{material_id, bin_id, counted_qty}]` (bin '' = lantai/belum dirak)
    totals    : {material_id: saldo AKHIR} (hasil hitung + mutasi sesudah dihitung) — hanya barang
                yang dihitung di sesi ini.
    Aturan: bin yang di-scan → isi bin = hasil hitung (1 bin = 1 barang; bila >1 barang, yang
    terbanyak; sisanya dicatat `overflow` = belum dirak). Bin yang TIDAK di-scan tetapi berisi
    barang yang dihitung dipertahankan sejauh Σ penempatan ≤ saldo akhir; sisanya = belum dirak.
    Bila barang keluar SESUDAH dihitung membuat Σ bin ter-scan > saldo akhir, bin terbesar dikurangi.
    Return ({pos_id: (material_id|None, qty)} hanya bin yang berubah, overflow[])."""
    by_bin: dict = defaultdict(dict)
    for e in entries:
        mid, b = e.get("material_id"), e.get("bin_id") or ""
        if not b or mid not in totals:
            continue
        by_bin[b][mid] = _r(by_bin[b].get(mid, 0) + float(e.get("counted_qty") or 0))
    pos_by_id = {p["id"]: p for p in positions}
    assigned, overflow = {}, []
    placed: dict = defaultdict(float)
    for b, mats in by_bin.items():
        mid, q = max(mats.items(), key=lambda kv: (kv[1], kv[0]))
        assigned[b] = (mid, q) if q > 0 else (None, 0.0)
        placed[mid] = _r(placed[mid] + max(q, 0))
        for om, oq in mats.items():
            if om != mid and oq > 0:
                overflow.append({"bin_id": b, "material_id": om, "qty": oq})
    for mid in list(placed):
        excess = _r(placed[mid] - max(0.0, float(totals.get(mid) or 0)))
        for b in sorted((b for b, v in assigned.items() if v[0] == mid), key=lambda b: -assigned[b][1]):
            if excess <= 0:
                break
            cut = min(excess, assigned[b][1])
            q = _r(assigned[b][1] - cut)
            assigned[b] = (mid, q) if q > 0 else (None, 0.0)
            excess, placed[mid] = _r(excess - cut), _r(placed[mid] - cut)
    for p in sorted(positions, key=lambda x: -float(x.get("qty") or 0)):
        if p["id"] in assigned:
            continue
        mid = p.get("material_id")
        if not mid or mid not in totals:
            continue
        room = max(0.0, _r(totals[mid] - placed[mid]))
        keep = _r(min(float(p.get("qty") or 0), room))
        placed[mid] = _r(placed[mid] + keep)
        assigned[p["id"]] = (mid, keep) if keep > 0 else (None, 0.0)
    changes = {}
    for pid, (mid, q) in assigned.items():
        cur = pos_by_id.get(pid) or {}
        cur_mid = cur.get("material_id") if float(cur.get("qty") or 0) > 0 else None
        if (cur_mid, _r(cur.get("qty") if cur_mid else 0)) != (mid, _r(q)):
            changes[pid] = (mid, _r(q))
    return changes, overflow


def plan_rack_placement(lines: list, loc_positions: list, stock_by_mat: dict) -> tuple:
    """Penempatan bin setelah hitung LEVEL RAK (stok TIDAK berubah).

    lines         : baris terevaluasi `[{material_id, bin_id, counted_qty, in_snapshot, resolution}]`
    loc_positions : SEMUA bin di lokasi (untuk Σ penempatan per material)
    stock_by_mat  : {material_id: saldo stok di lokasi sesi}
    Baris "barang lebih" tidak ditempatkan (masuk selisih hanya lewat hitung penuh lokasi).
    Return (changes {pos_id: (material_id|None, qty)}, errors[], findings[])."""
    per_bin: dict = defaultdict(dict)
    findings = []
    for ln in lines:
        if not ln.get("in_snapshot") and ln.get("resolution") == "lebih":
            findings.append({"material_id": ln["material_id"], "bin_id": ln["bin_id"],
                             "qty": ln.get("counted_qty") or 0, "jenis": "barang_lebih"})
            continue
        per_bin[ln["bin_id"]][ln["material_id"]] = _r(ln.get("counted_qty") or 0)
    pos_by_id = {p["id"]: p for p in loc_positions}
    changes = {}
    for b, mats in per_bin.items():
        mid, q = max(mats.items(), key=lambda kv: (kv[1], kv[0]))
        new = (mid, q) if q > 0 else (None, 0.0)
        for om, oq in mats.items():
            if om != mid and oq > 0:
                findings.append({"material_id": om, "bin_id": b, "qty": oq, "jenis": "bin_penuh"})
        cur = pos_by_id.get(b) or {}
        cur_mid = cur.get("material_id") if float(cur.get("qty") or 0) > 0 else None
        if (cur_mid, _r(cur.get("qty") if cur_mid else 0)) != (new[0], _r(new[1])):
            changes[b] = (new[0], _r(new[1]))
    placed: dict = defaultdict(float)
    for p in loc_positions:
        mid, q = (p.get("material_id"), float(p.get("qty") or 0))
        if p["id"] in changes:
            mid, q = changes[p["id"]]
        if mid and q > 0:
            placed[mid] = _r(placed[mid] + q)
    errors = []
    touched = {m for (m, _q) in changes.values() if m}
    for mid in sorted(touched):
        if placed[mid] > _r(stock_by_mat.get(mid, 0)) + 1e-6:
            errors.append({"material_id": mid, "penempatan": placed[mid],
                           "stok_lokasi": _r(stock_by_mat.get(mid, 0))})
    return changes, errors, findings


def build_je_lines(valued: list, inv_code_of: dict, contra: dict, memo: str) -> list:
    """Baris jurnal SATU sesi. `valued` = [{kind, value (bertanda), reason}].

    Dikelompokkan per (akun persediaan, akun lawan, arah) — tidak di-netto antara selisih
    lebih & kurang supaya bruto tetap terbaca. Lebih: Dr persediaan / Cr lawan; kurang: kebalikan.
    Baris "rusak" yang kurang memakai lawan 6-4300 (beban scrap/rusak)."""
    groups: dict = {}
    for v in valued:
        val = round(float(v.get("value") or 0), 2)
        if val == 0:
            continue
        inv = inv_code_of[v["kind"]]
        c = contra["rusak"] if (v.get("reason") == "rusak" and val < 0) else contra["selisih"]
        key = (inv, c, 1 if val > 0 else -1)
        groups[key] = round(groups.get(key, 0.0) + abs(val), 2)
    lines = []
    for (inv, c, sign), amt in sorted(groups.items()):
        if amt <= 0:
            continue
        what = "lebih" if sign > 0 else ("rusak" if c == contra.get("rusak") and c != contra.get("selisih")
                                         else "kurang")
        desc = f"{memo} · selisih {what}"
        if sign > 0:
            lines += [{"account_code": inv, "debit": amt, "credit": 0, "description": desc},
                      {"account_code": c, "debit": 0, "credit": amt, "description": desc}]
        else:
            lines += [{"account_code": c, "debit": amt, "credit": 0, "description": desc},
                      {"account_code": inv, "debit": 0, "credit": amt, "description": desc}]
    return lines


def blocking_sheets(sheets: Iterable[dict], location_ids: Iterable[str], count_date: str) -> list:
    """Lembar scan keluar (K15) yang MENAHAN approve: belum `closed`, lokasi sesi, `date` ≤ tanggal hitung.

    2026-11-06 (Tahap 2): kontrak paket scan keluar = `status != 'closed'` (termasuk `closing` yang
    sedang ditutup); dulu hanya `open` yang dibaca sehingga lembar `closing` lolos."""
    locs = set(location_ids or [])
    return [s for s in (sheets or [])
            if s.get("status") != "closed" and s.get("location_id") in locs
            and str(s.get("date") or "") <= str(count_date or "")]


def scan_to_base(mat: dict, qty: float, input_uom: str) -> tuple:
    """Qty hitung (boleh per satuan kemasan) → satuan dasar. Kosong/sama = apa adanya."""
    code = (input_uom or "").strip().lower()
    if not code or not mat or code == _uom.base_uom_of(mat):
        return _r(qty), {}
    try:
        factor, source = _bom_uom.factor_to_base(mat, code)
    except _uom.UomError as e:
        raise HTTPException(400, str(e))
    return round(float(qty) * factor, 4), {"input_qty": qty, "input_uom": code,
                                           "uom_factor": factor, "uom_source": source}


def kind_of(mat: Optional[dict]) -> str:
    """'bahan' | 'aksesoris' | 'fg' — taksonomi yang sama dengan mesin posting."""
    from routes.rahaza_posting import inventory_kind
    return inventory_kind(mat)


# ═════════════════════════════ CAKUPAN LOKASI ═════════════════════════════
async def location_scope(db, location_id: str) -> dict:
    """Lokasi + zona/rak/bin `wh_*` yang tertaut. Zona tertaut = peta migrasi
    (`wh_location_migration_map.rahaza_location_id`) atau field `location_id`/`rahaza_location_id`
    di zona. `location_ids` = id yang boleh dipakai baris stok lokasi ini (lokasi + zona tertaut)."""
    loc = await db.rahaza_locations.find_one({"id": location_id}, {"_id": 0})
    if not loc:
        raise HTTPException(404, "Lokasi tidak ditemukan")
    zone_ids = set()
    async for e in db.wh_location_migration_map.find(
            {"rahaza_location_id": location_id, "active": {"$ne": False}}, {"_id": 0, "wh_zone_id": 1}):
        if e.get("wh_zone_id"):
            zone_ids.add(e["wh_zone_id"])
    async for z in db.wh_zones.find({"$or": [{"location_id": location_id},
                                             {"rahaza_location_id": location_id}]}, {"_id": 0, "id": 1}):
        zone_ids.add(z["id"])
    zones = await db.wh_zones.find({"id": {"$in": sorted(zone_ids)}}, {"_id": 0}).to_list(500) if zone_ids else []
    racks = await db.wh_racks.find({"zone_id": {"$in": sorted(zone_ids)}}, {"_id": 0}).to_list(2000) \
        if zone_ids else []
    positions = await db[POS].find({"zone_id": {"$in": sorted(zone_ids)}}, {"_id": 0}).to_list(20000) \
        if zone_ids else []
    return {"location": loc, "zones": zones, "racks": racks, "positions": positions,
            "location_ids": [location_id] + sorted(zone_ids)}


def _is_quarantine(loc: dict) -> bool:
    from core.location_resolver import role_of_location
    return role_of_location(loc) == "karantina"


def _pos_label(p: dict) -> str:
    return " / ".join(x for x in (p.get("building_code"), p.get("zone_code"), p.get("rack_code"),
                                  p.get("label")) if x) or p.get("barcode") or p.get("id") or ""


def _in_sub_scope(pos: dict, sub: Optional[dict]) -> bool:
    if not sub:
        return True
    key = {"zone": "zone_id", "rack": "rack_id", "bin": "id"}[sub["type"]]
    return pos.get(key) == sub["id"]


async def list_locations(db) -> list:
    """Pilihan lokasi untuk layar: lokasi aktif (karantina ditandai), zona/rak/bin tertautnya."""
    out = []
    async for loc in db.rahaza_locations.find({"active": {"$ne": False}}, {"_id": 0}).sort("code", 1):
        sc = await location_scope(db, loc["id"])
        out.append({
            "id": loc["id"], "code": loc.get("code"), "name": loc.get("name"), "type": loc.get("type"),
            "storage_role": loc.get("storage_role") or "", "quarantine": _is_quarantine(loc),
            "zones": [{"id": z["id"], "code": z.get("code"), "name": z.get("name")} for z in sc["zones"]],
            "racks": [{"id": r["id"], "code": r.get("code"), "name": r.get("name"), "zone_id": r.get("zone_id")}
                      for r in sc["racks"]],
            "bins": [{"id": p["id"], "barcode": p.get("barcode"), "label": _pos_label(p),
                      "rack_id": p.get("rack_id"), "zone_id": p.get("zone_id")} for p in sc["positions"]],
        })
    return out


# ═════════════════════════════ SESI ═════════════════════════════
async def _material_meta(db, mids: Iterable[str]) -> dict:
    ids = sorted({m for m in mids if m})
    if not ids:
        return {}
    return {m["id"]: m async for m in db.rahaza_materials.find({"id": {"$in": ids}}, {"_id": 0})}


async def _wac(db, mat: dict) -> float:
    """WAC saat snapshot: FG dari `core.fg_cost_layers` (tanpa menulis), lainnya `unit_cost`."""
    if kind_of(mat) == "fg":
        from core import fg_cost_layers as fcl
        return round(float((await fcl.wac_state(db, mat["id"], init=False))["unit_cost"] or 0), 4)
    return round(float(mat.get("unit_cost") or 0), 4)


async def _new_line(db, mat: dict, *, level: str, bin_id: str = "", bin_label: str = "",
                    snapshot_qty: float = 0.0, in_snapshot: bool = True, opening: bool = False) -> dict:
    ln = {
        "key": line_key(mat["id"], bin_id, level), "material_id": mat["id"],
        "material_code": mat.get("code") or "", "material_name": mat.get("name") or "",
        "unit": _uom.base_uom_of(mat) or mat.get("unit") or "pcs", "kind": kind_of(mat),
        "bin_id": bin_id if level == LEVEL_RAK else "", "bin_label": bin_label if level == LEVEL_RAK else "",
        "snapshot_qty": _r(snapshot_qty), "unit_cost": await _wac(db, mat),
        "in_snapshot": bool(in_snapshot), "status": ST_BELUM, "reason": "",
    }
    if opening:   # 2026-11-09: harga stok awal (FG tanpa WAC → HPP standar) + asal harganya
        uc, src, comps = await opening_unit_cost(db, mat)
        ln.update({"unit_cost": uc, "cost_source": src, "opening_components": comps})
    if level == LEVEL_RAK and not in_snapshot:
        ln["resolution"] = "pindah"
    return ln


async def resolve_materials_by_codes(db, codes: Iterable[str]) -> tuple:
    found, unknown = [], []
    for c in codes or []:
        c = scan_resolver.normalize_code(c)
        if not c:
            continue
        res = await scan_resolver.resolve_item(db, c)
        (found.append(res["id"]) if res else unknown.append(c))
    return found, unknown


async def create_session(db, user: dict, *, location_id: str, sub_type: str = "", sub_id: str = "",
                         kinds: Iterable[str] = (), material_ids: Iterable[str] = (),
                         material_codes: Iterable[str] = (), notes: str = "", source: str = "gudang",
                         opening: bool = False, extra: Optional[dict] = None) -> dict:
    from utils.counters import gen_prefixed_number
    if not location_id:
        raise HTTPException(400, "Lokasi wajib dipilih (Sesi Opname per lokasi)")
    if opening and sub_type:
        raise HTTPException(400, "Opname stok awal = hitung seluruh lokasi (tanpa sub-cakupan zona/rak/bin).")
    sc = await location_scope(db, location_id)
    loc = sc["location"]
    if _is_quarantine(loc):
        raise HTTPException(400, f"Lokasi {loc.get('code')} adalah lokasi KARANTINA — stoknya dikelola dokumen "
                                 "karantina (lepas/retur/musnah), tidak diopname di sini.")
    kinds = [k for k in (kinds or []) if k]
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise HTTPException(400, f"Jenis tidak dikenal: {bad} (pilihan: {', '.join(KINDS)})")
    mids = [m for m in (material_ids or []) if m]
    if material_codes:
        more, unknown = await resolve_materials_by_codes(db, material_codes)
        if unknown:
            raise HTTPException(400, f"Kode barang tidak dikenal: {', '.join(unknown[:10])}")
        mids += more
    mids = list(dict.fromkeys(mids))
    sub = None
    if sub_type:
        if sub_type not in SUB_TYPES or not sub_id:
            raise HTTPException(400, "Sub-cakupan harus zone/rack/bin beserta id-nya")
        pool = {"zone": sc["zones"], "rack": sc["racks"], "bin": sc["positions"]}[sub_type]
        doc = next((x for x in pool if x["id"] == sub_id), None)
        if not doc:
            raise HTTPException(400, f"{sub_type} itu tidak tertaut ke lokasi {loc.get('code')}")
        label = _pos_label(doc) if sub_type == "bin" else f"{doc.get('code', '')} - {doc.get('name', '')}".strip(" -")
        sub = {"type": sub_type, "id": sub_id, "label": label}
    level = LEVEL_RAK if sub else LEVEL_LOKASI
    snapshot_at = _now()
    lines = []
    if level == LEVEL_LOKASI:
        rows = await db[stock_service.STOCK].find(
            {"location_id": {"$in": sc["location_ids"]}}, {"_id": 0}).to_list(50000)
        by_mat: dict = defaultdict(float)
        for r in rows:
            if r.get("material_id"):
                by_mat[r["material_id"]] = _r(by_mat[r["material_id"]] + float(r.get("qty") or 0))
        cand = set(m for m, q in by_mat.items() if q != 0) | set(mids)
        if mids:
            cand &= set(mids)
        meta = await _material_meta(db, cand)
        for mid in sorted(cand, key=lambda m: (meta.get(m) or {}).get("code") or m):
            mat = meta.get(mid)
            if not mat or (kinds and kind_of(mat) not in kinds):
                continue
            lines.append(await _new_line(db, mat, level=level, snapshot_qty=by_mat.get(mid, 0.0), opening=opening))
    else:
        bins = [p for p in sc["positions"] if _in_sub_scope(p, sub)]
        meta = await _material_meta(db, [p.get("material_id") for p in bins])
        for p in bins:
            mat = meta.get(p.get("material_id"))
            if not mat or float(p.get("qty") or 0) <= 0:
                continue
            if (kinds and kind_of(mat) not in kinds) or (mids and mat["id"] not in mids):
                continue
            lines.append(await _new_line(db, mat, level=level, bin_id=p["id"], bin_label=_pos_label(p),
                                         snapshot_qty=float(p.get("qty") or 0)))
    session_no = await gen_prefixed_number(db, SESS, "session_no", f"OPN-{fmt_wib('%Y%m', _now())}-", 4)
    scope_label = (("Stok awal · " if opening else "") + f"{loc.get('code')} — {loc.get('name')}"
                   + (f" · {sub['label']}" if sub else ""))
    if kinds:
        scope_label += " · " + ", ".join(KIND_LABELS[k] for k in kinds)
    if mids:
        scope_label += f" · {len(mids)} barang (cycle count)"
    doc = {
        "id": _uid(), "session_no": session_no, "engine": ENGINE, "level": level,
        "mode": MODE_OPENING if opening else ("cycle" if (mids or kinds or sub) else "full"),
        "location_id": loc["id"], "location_code": loc.get("code"), "location_name": loc.get("name"),
        "location_ids": sc["location_ids"], "zone_ids": [z["id"] for z in sc["zones"]],
        "sub_scope": sub, "kinds": kinds, "material_ids": mids, "source": source or "gudang",
        "scope_label": scope_label, "status": "counting", "snapshot_at": snapshot_at,
        "lines": lines, "notes": notes or "",
        "created_by": user.get("id", ""), "created_by_name": user.get("name", ""), "created_at": snapshot_at,
        "submitted_at": None, "approved_at": None, "approved_by": None, "summary": None,
        **(extra or {}),
    }
    await db[SESS].insert_one(dict(doc))
    return doc


async def get_session(db, session_id: str, *, for_write: bool = False) -> dict:
    sess = await db[SESS].find_one({"id": session_id}, {"_id": 0})
    if not sess:
        if await db[LEGACY_ACC].find_one({"id": session_id}, {"_id": 0, "id": 1}):
            raise HTTPException(410, "Sesi opname aksesoris lama = arsip baca-saja. Buat Sesi Opname baru.")
        raise HTTPException(404, "Sesi opname tidak ditemukan")
    if for_write and sess.get("engine") != ENGINE:
        raise HTTPException(410, "Sesi opname lama (sebelum mesin tunggal K9) = arsip baca-saja. "
                                 "Buat Sesi Opname baru.")
    return sess


def _require_status(sess: dict, *allowed: str):
    if sess.get("status") not in allowed:
        raise HTTPException(400, f"Sesi {sess.get('session_no')} berstatus '{sess.get('status')}' — "
                                 f"aksi ini hanya untuk status {', '.join(allowed)}")


async def resolve_count_bin(db, sess: dict, *, bin_id: str = "", code: str = "") -> tuple:
    """(bin_id, label) konteks hitung. '' = lantai / belum dirak (hanya level lokasi).
    Bisa scan label LOKASI (kode lokasi) → konteks lantai lokasi itu."""
    rak = sess.get("level") == LEVEL_RAK
    pos = None
    if bin_id:
        pos = await db[POS].find_one({"id": bin_id}, {"_id": 0})
        if not pos:
            raise HTTPException(404, "Bin tidak ditemukan")
    elif code:
        res = await scan_resolver.resolve_bin(db, scan_resolver.normalize_code(code))
        if not res:
            raise HTTPException(404, f"Kode '{code}' bukan bin/lokasi yang dikenal")
        if res["subtipe"] == "lokasi":
            if res["id"] not in (sess.get("location_ids") or [sess.get("location_id")]):
                raise HTTPException(400, f"Lokasi {res['kode']} bukan lokasi sesi ini ({sess.get('location_code')})")
            if rak:
                raise HTTPException(400, "Hitung level rak: scan label BIN, bukan label lokasi")
            return "", f"{sess.get('location_code')} · lantai / belum dirak"
        pos = res["_doc"]
    if not pos:
        if rak:
            raise HTTPException(400, "Hitung level rak: bin wajib di-scan/dipilih")
        return "", f"{sess.get('location_code')} · lantai / belum dirak"
    if pos.get("zone_id") not in (sess.get("zone_ids") or []):
        raise HTTPException(400, f"Bin {pos.get('barcode')} bukan bagian lokasi {sess.get('location_code')}")
    if rak and not _in_sub_scope(pos, sess.get("sub_scope")):
        raise HTTPException(400, f"Bin {pos.get('barcode')} di luar cakupan {sess['sub_scope']['label']}")
    return pos["id"], _pos_label(pos)


async def resolve_item(db, *, material_id: str = "", code: str = "") -> Optional[dict]:
    if material_id:
        return await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0})
    res = await scan_resolver.resolve_item(db, code)
    return res["_doc"] if res else None


async def record_count(db, user: dict, sess: dict, *, mat: dict, bin_id: str, bin_label: str,
                       qty: float, input_uom: str = "", mode: str = "add") -> dict:
    """Catat hitungan. mode 'add' = tambah per scan (negatif = koreksi), 'set' = ketik jumlah."""
    _require_status(sess, "counting")
    level = sess.get("level") or LEVEL_LOKASI
    if level == LEVEL_RAK and not bin_id:
        raise HTTPException(400, "Hitung level rak: bin wajib")
    kinds, mids = sess.get("kinds") or [], sess.get("material_ids") or []
    if kinds and kind_of(mat) not in kinds:
        raise HTTPException(400, f"{mat.get('code')} berjenis {KIND_LABELS.get(kind_of(mat))} — di luar filter "
                                 "sesi ini")
    if mids and mat["id"] not in mids:
        raise HTTPException(400, f"{mat.get('code')} tidak ada di daftar cycle count sesi ini")
    base, trace = scan_to_base(mat, abs(float(qty)), input_uom)
    base = base if float(qty) >= 0 else -base
    key = line_key(mat["id"], bin_id, level)
    if not any(ln.get("key") == key for ln in sess.get("lines") or []):
        ln = await _new_line(db, mat, level=level, bin_id=bin_id, bin_label=bin_label,
                             snapshot_qty=0.0, in_snapshot=False, opening=is_opening(sess))
        await db[SESS].update_one({"id": sess["id"], "lines.key": {"$ne": key}}, {"$push": {"lines": ln}})
    ek = {"session_id": sess["id"], "material_id": mat["id"], "bin_id": bin_id or ""}
    cur = await db[CNT].find_one(ek, {"_id": 0})
    if mode == "set":
        if base < 0:
            raise HTTPException(400, "Jumlah hitung tidak boleh negatif")
        new_qty = base
    else:
        new_qty = _r(float((cur or {}).get("counted_qty") or 0) + base)
    now = _now()
    if mode != "set" and new_qty <= 0:
        await db[CNT].delete_one(ek)
        new_qty = 0.0
    else:
        await db[CNT].update_one(ek, {
            "$set": {"counted_qty": new_qty, "updated_at": now, "counted_at": now,
                     "counted_by": user.get("id", ""), "counted_by_name": user.get("name", ""),
                     "bin_label": bin_label, "material_code": mat.get("code"),
                     "material_name": mat.get("name"), "unit": _uom.base_uom_of(mat) or mat.get("unit"),
                     **({"last_" + k: v for k, v in trace.items()} if trace else {})},
            "$setOnInsert": {"id": _uid(), "engine": ENGINE}}, upsert=True)
    # baris yang pernah "anggap 0" lalu dihitung lagi: statusnya kembali diturunkan dari hitungan
    if any(ln.get("key") == key and ln.get("status") == ST_NOL for ln in sess.get("lines") or []):
        await db[SESS].update_one({"id": sess["id"]}, {"$set": {"lines.$[l].status": ST_BELUM}},
                                  array_filters=[{"l.key": key, "l.status": ST_NOL}])
    return {"ok": True, "material_id": mat["id"], "material_code": mat.get("code"),
            "material_name": mat.get("name"), "bin_id": bin_id, "bin_label": bin_label,
            "counted_qty": new_qty, "converted_qty": base, "base_uom": _uom.base_uom_of(mat),
            **({"uom": trace} if trace else {})}


async def set_line(db, sess: dict, *, key: str, reason: Optional[str] = None,
                   resolution: Optional[str] = None) -> dict:
    """Alasan baris ('' | 'rusak') dan pilihan barang tak tercatat di rak ('pindah' | 'lebih')."""
    _require_status(sess, "counting", "submitted")
    ln = next((x for x in sess.get("lines") or [] if x.get("key") == key), None)
    if not ln:
        raise HTTPException(404, "Baris opname tidak ditemukan")
    upd = {}
    if reason is not None:
        if reason not in REASONS:
            raise HTTPException(400, "Alasan baris hanya '' atau 'rusak'")
        upd["lines.$[l].reason"] = reason
    if resolution is not None:
        if sess.get("level") != LEVEL_RAK or ln.get("in_snapshot"):
            raise HTTPException(400, "Pilihan pindah/lebih hanya untuk barang tak tercatat di bin (hitung rak)")
        if resolution not in RESOLUTIONS:
            raise HTTPException(400, "Pilihan hanya 'pindah' (stok tetap) atau 'lebih' (barang lebih)")
        upd["lines.$[l].resolution"] = resolution
    if upd:
        await db[SESS].update_one({"id": sess["id"]}, {"$set": upd}, array_filters=[{"l.key": key}])
    return {"ok": True, "key": key, **{k.split(".")[-1]: v for k, v in upd.items()}}


# ═════════════════════════════ EVALUASI ═════════════════════════════
async def evaluate(db, sess: dict) -> dict:
    """Baris + stok sistem saat dihitung + selisih + nilai (WAC snapshot). Dihitung ULANG tiap
    dibaca sampai approve (mutasi yang dicatat terlambat, mis. scan susulan K15, ikut masuk)."""
    level = sess.get("level") or LEVEL_LOKASI
    entries = await db[CNT].find({"session_id": sess["id"]}, {"_id": 0}).to_list(100000)
    by_key: dict = defaultdict(list)
    for e in entries:
        by_key[line_key(e["material_id"], e.get("bin_id") or "", level)].append(e)
    lines = sess.get("lines") or []
    ledger: dict = defaultdict(list)
    if level == LEVEL_LOKASI and lines:
        q = {"material_id": {"$in": sorted({ln["material_id"] for ln in lines})},
             "location_id": {"$in": sess.get("location_ids") or [sess.get("location_id")]},
             "created_at": {"$gt": sess.get("snapshot_at")}}
        async for row in db[stock_service.LEDGER].find(q, {"_id": 0}):
            ledger[row["material_id"]].append(row)
    out, totals = [], {"lines": len(lines), "counted": 0, "belum": 0, "with_variance": 0,
                       "value_plus": 0.0, "value_minus": 0.0, "total_variance_value": 0.0, "uncosted": 0}
    for ln in lines:
        ents = by_key.get(ln["key"], [])
        st = line_status(ln, len(ents))
        counted = _r(sum(float(e.get("counted_qty") or 0) for e in ents))
        cts = [aware(e.get("counted_at") or e.get("updated_at")) for e in ents]
        counted_at = max([c for c in cts if c], default=None) or (aware(ln.get("zero_at")) if st == ST_NOL else None)
        ev = {**ln, "status": st, "counted_qty": counted if st != ST_BELUM else None,
              "counted_at": counted_at, "entries": [{"bin_id": e.get("bin_id") or "", "bin_label": e.get("bin_label"),
                                                     "counted_qty": e.get("counted_qty"),
                                                     "counted_at": e.get("counted_at")} for e in ents]}
        if level == LEVEL_LOKASI:
            at = counted_at or _now()
            system, mut = system_qty_at(ln.get("snapshot_qty"), ledger.get(ln["material_id"], []),
                                        sess.get("snapshot_at"), at)
        else:
            system, mut = _r(ln.get("snapshot_qty")), 0.0
        ev.update({"mutation_qty": mut, "system_qty": system})
        if st == ST_BELUM:
            ev.update({"variance_qty": None, "variance_value": None})
            totals["belum"] += 1
        else:
            var = _r(counted - system)
            val = round(var * float(ln.get("unit_cost") or 0), 2)
            ev.update({"variance_qty": var, "variance_value": val})
            totals["counted"] += 1
            if var != 0:
                totals["with_variance"] += 1
                if not float(ln.get("unit_cost") or 0):
                    totals["uncosted"] += 1
                totals["value_plus" if val > 0 else "value_minus"] = round(
                    totals["value_plus" if val > 0 else "value_minus"] + val, 2)
                totals["total_variance_value"] = round(totals["total_variance_value"] + val, 2)
        out.append(ev)
    out.sort(key=lambda x: (x["status"] != ST_BELUM, -(abs(x["variance_qty"] or 0)),
                            x.get("material_code") or "", x.get("bin_label") or ""))
    return {"lines": out, "totals": totals}


def count_date_of(sess: dict, ev_lines: list) -> str:
    """Tanggal hitung (WIB) = hari baris terakhir dihitung; cadangan = jam snapshot."""
    ts = [aware(x.get("counted_at")) for x in ev_lines if x.get("counted_at")]
    return wib_date(max(ts) if ts else sess.get("snapshot_at"))


_BLIND_FIELDS = ("snapshot_qty", "system_qty", "mutation_qty", "variance_qty", "variance_value", "unit_cost")


async def session_view(db, sess: dict) -> dict:
    """Detail sesi. Selama `counting` = HITUNG BUTA: qty sistem/selisih tidak dikirim."""
    from auth import serialize_doc
    if sess.get("engine") != ENGINE:
        counts = await db[CNT].find({"session_id": sess["id"]}, {"_id": 0}).to_list(50000)
        return {"session": serialize_doc({k: v for k, v in sess.items() if k != "snapshot"}),
                "archived": True, "snapshot": serialize_doc(sess.get("snapshot") or []),
                "counts": serialize_doc(counts)}
    if sess.get("status") == "approved" and sess.get("result"):
        lines, totals = sess["result"]["lines"], sess["result"]["totals"]
    else:
        ev = await evaluate(db, sess)
        lines, totals = ev["lines"], ev["totals"]
    blind = sess.get("status") == "counting"
    if blind:
        lines = [{k: v for k, v in ln.items() if k not in _BLIND_FIELDS} for ln in lines]
        totals = {k: totals[k] for k in ("lines", "counted", "belum")}
    s = {k: v for k, v in sess.items() if k not in ("lines", "result")}
    return {"session": serialize_doc(s), "blind": blind, "lines": serialize_doc(lines),
            "totals": totals, "archived": False,
            "result": serialize_doc({k: v for k, v in (sess.get("result") or {}).items() if k != "lines"})}


# ═════════════════════════════ ALUR STATUS ═════════════════════════════
async def submit(db, user: dict, sess: dict, *, confirm_zero: bool = False, notes: str = "") -> dict:
    _require_status(sess, "counting")
    ev = await evaluate(db, sess)
    belum = [x for x in ev["lines"] if x["status"] == ST_BELUM]
    if not any(x["status"] != ST_BELUM for x in ev["lines"]) and not confirm_zero:
        raise HTTPException(400, "Belum ada barang yang dihitung.")
    if belum and not confirm_zero:
        raise HTTPException(409, {
            "message": f"{len(belum)} baris BELUM dihitung (≠ 0). Hitung dulu, atau konfirmasi 'anggap 0'.",
            "code": "belum_dihitung",
            "belum_dihitung": [{"key": x["key"], "material_code": x.get("material_code"),
                                "material_name": x.get("material_name"), "bin_label": x.get("bin_label"),
                                "unit": x.get("unit")} for x in belum]})
    now = _now()
    if belum:
        await db[SESS].update_one({"id": sess["id"]},
                                  {"$set": {"lines.$[l].status": ST_NOL, "lines.$[l].zero_at": now,
                                            "lines.$[l].zero_by": user.get("id", "")}},
                                  array_filters=[{"l.key": {"$in": [x["key"] for x in belum]}}])
    sess = await get_session(db, sess["id"])
    ev = await evaluate(db, sess)
    res = await db[SESS].update_one({"id": sess["id"], "status": "counting"}, {"$set": {
        "status": "submitted", "submitted_at": now, "count_date": count_date_of(sess, ev["lines"]),
        "submitted_by": user.get("id", ""), "submitted_by_name": user.get("name", ""),
        "zero_confirmed": len(belum), "summary": ev["totals"], "notes": notes or sess.get("notes", "")}})
    if not res.matched_count:
        raise HTTPException(409, "Sesi sudah diajukan oleh pengguna lain")
    return await get_session(db, sess["id"])


async def _stock_rows(db, mids: list, loc_ids: list) -> dict:
    out: dict = defaultdict(list)
    if mids:
        async for r in db[stock_service.STOCK].find(
                {"material_id": {"$in": mids}, "location_id": {"$in": loc_ids}}, {"_id": 0}):
            out[r["material_id"]].append(r)
    return out


async def _write_positions(db, user: dict, sess: dict, changes: dict, meta: dict) -> int:
    n = 0
    for pid, (mid, q) in changes.items():
        mat = meta.get(mid) or {}
        upd = ({"material_id": mid, "material_code": mat.get("code"), "material_name": mat.get("name"),
                "unit": mat.get("unit") or "pcs", "qty": q, "status": "occupied"} if mid and q > 0 else
               {"qty": 0, "material_id": None, "material_code": None, "material_name": None, "status": "empty"})
        upd["last_updated"] = _now()
        before = await db[POS].find_one({"id": pid}, {"_id": 0, "material_id": 1, "qty": 1, "barcode": 1, "label": 1})
        await db[POS].update_one({"id": pid}, {"$set": upd})
        await db.wh_placement_movements.insert_one({
            "id": _uid(), "type": "opname", "session_id": sess["id"], "session_no": sess.get("session_no"),
            "position_id": pid, "position_barcode": (before or {}).get("barcode"),
            "position_label": (before or {}).get("label"),
            "material_id": mid or (before or {}).get("material_id"), "qty_before": (before or {}).get("qty"),
            "qty_after": upd["qty"], "created_at": _now(),
            "created_by": user.get("email") or user.get("name") or "system"})
        n += 1
    return n


async def check_scan_out_sheets(db, sess: dict, count_date: str):
    """KONTRAK K15: tolak approve selama lembar scan keluar lokasi ini masih terbuka."""
    loc_ids = sess.get("location_ids") or [sess.get("location_id")]
    sheets = await db[SCAN_OUT].find({"location_id": {"$in": loc_ids}, "status": {"$ne": "closed"}},
                                     {"_id": 0}).to_list(200)
    block = blocking_sheets(sheets, loc_ids, count_date)
    if block:
        names = ", ".join(sorted(str(s.get("number") or s.get("sheet_no") or s.get("code") or s.get("date")
                                     or s.get("id")) for s in block))
        raise HTTPException(409, f"Approve opname {sess.get('session_no')} ditahan: lembar scan keluar lokasi "
                                 f"{sess.get('location_code')} masih TERBUKA ({names}; tanggal ≤ tanggal hitung "
                                 f"{count_date}). Tutup lembar itu dulu supaya jurnal HPP mendahului jurnal selisih.")
    # 2026-11-06 (Tahap 2): baris scan GAGAL (antrean kirim ulang) juga menahan — stoknya belum pasti
    # terpotong, jadi hitungan fisik bisa dobel dengan kiriman ulang sesudah opname.
    failed = [ln for ln in await db[SCAN_OUT_LINES].find(
        {"location_id": {"$in": loc_ids}, "status": {"$in": ["failed", "pending"]}}, {"_id": 0}).to_list(200)
        if str(ln.get("date") or "") <= str(count_date or "")
        and (ln.get("status") == "failed" or _claim_stale(ln.get("claim_at")))]
    if failed:
        skus = ", ".join(sorted({str(ln.get("sku") or ln.get("code") or "-") for ln in failed})[:5])
        raise HTTPException(409, f"Approve opname {sess.get('session_no')} ditahan: {len(failed)} scan keluar di lokasi "
                                 f"{sess.get('location_code')} gagal diproses ({skus}). Kirim ulang atau batalkan "
                                 "di layar Scan Keluar Penjualan dulu.")


async def inventory_codes(db, kinds: Iterable[str]) -> tuple:
    """({jenis: kode akun persediaan}, galat) lewat profil `inventory_adjust` (1-1401/1-1402/1-1404)."""
    from routes import rahaza_posting as rp
    adj_map = await rp.get_mapping(db, "inventory_adjust")
    out = {}
    for kind in sorted(set(kinds)):
        code, err = rp.inventory_account(adj_map, "inventory_adjust", kind)
        if not code:
            return out, err
        out[kind] = code
    return out, ""


async def saldo_awal_inventory_lines(db, codes: Iterable[str], entity: str = "DA") -> list:
    """Baris jurnal Saldo Awal aktif (layar Saldo Awal) yang MENGISI akun persediaan `codes` — [{code, amount}]."""
    from core.opening_balance import existing_opening
    je = await existing_opening(db, entity)
    if not je:
        return []
    full = await db.rahaza_journal_entries.find_one({"id": je["id"]}, {"_id": 0, "lines": 1, "je_number": 1}) or {}
    want, out = set(codes), {}
    for ln in full.get("lines") or []:
        c = ln.get("account_code")
        if c in want:
            out[c] = round(out.get(c, 0.0) + float(ln.get("debit") or 0) - float(ln.get("credit") or 0), 2)
    return [{"account_code": c, "amount": v, "je_number": full.get("je_number") or je.get("je_number")}
            for c, v in sorted(out.items()) if abs(v) >= 0.01]


async def opened_materials(db, material_ids: Iterable[str], location_ids: Iterable[str]) -> set:
    """material_id yang SUDAH punya stok awal (mutasi `type='opening'`) di salah satu `location_ids`."""
    mids, locs = sorted(set(material_ids)), sorted(set(location_ids))
    if not mids or not locs:
        return set()
    return {m.get("material_id") async for m in db.rahaza_material_movements.find(
        {"type": "opening", "material_id": {"$in": mids}, "to_location_id": {"$in": locs}},
        {"_id": 0, "material_id": 1})}


async def check_opening(db, sess: dict, ev: dict) -> dict:
    """Gerbang approve opname stok awal. Melempar 409 (daftar per masalah) atau mengembalikan ringkasan."""
    lines = [x for x in ev["lines"] if x.get("variance_qty")]
    mids = [x["material_id"] for x in lines]
    opened = await opened_materials(db, mids, sess.get("location_ids") or [sess.get("location_id")])
    client_ids = {m["id"] async for m in db.rahaza_materials.find(
        {"id": {"$in": mids}, "owner_type": "client"}, {"_id": 0, "id": 1})} if mids else set()
    probs = opening_problems(lines, opened=opened, client_ids=client_ids)
    if probs:
        parts = [f"{len(v)} {OPENING_PROBLEM_TEXT[k]}" for k, v in probs.items()]
        raise HTTPException(409, {"code": "opname_awal_ditolak",
                                  "message": "Approve opname stok awal ditolak: " + "; ".join(parts) + ".",
                                  "problems": probs})
    codes, err = await inventory_codes(db, {x["kind"] for x in lines})
    if err:
        raise HTTPException(400, f"Approve ditolak: {err}")
    clash = await saldo_awal_inventory_lines(db, codes.values())
    if clash:
        what = ", ".join(f"{c['account_code']} Rp {c['amount']:,.0f}" for c in clash)
        raise HTTPException(409, {"code": "bentrok_saldo_awal", "message": (
            f"Approve opname stok awal ditolak: jurnal Saldo Awal ({clash[0]['je_number']}) sudah mengisi akun "
            f"persediaan {what}. Opname stok awal juga menjurnal nilai stok ke akun itu ⇒ persediaan DOBEL. "
            "Pilih satu jalur: kosongkan baris persediaan di Saldo Awal (void & posting ulang), atau muat stok "
            "lewat Excel STOK_AWAL (nilai dari Saldo Awal) — bukan keduanya."), "saldo_awal": clash})
    return {"inventory_codes": codes, "had_stock": [x.get("material_code") for x in lines
                                                    if float(x.get("system_qty") or 0) != 0]}


async def _post_session_je(db, user: dict, sess: dict, valued: list, je_date: str) -> dict:
    """SATU jurnal per sesi — idempoten `opname:{id}` (source_module `inventory_count_variance`).

    2026-11-09: sesi STOK AWAL → source_module `inventory_opening_count`, lawan = akun ekuitas saldo awal
    (`core.opening_balance.retained_earnings_code`, sama dengan layar Saldo Awal), bukan 5-1950."""
    from datetime import date as _date
    from routes import rahaza_posting as rp
    opening = is_opening(sess)
    event = OPENING_EVENT if opening else VARIANCE_EVENT
    ref = f"opname:{sess['id']}"
    existing = await rp._find_existing_je(db, event, ref)
    if existing:
        return {"ok": True, "je_id": existing["id"], "je_number": existing.get("je_number"), "already_posted": True}
    if not valued:
        return {"ok": True, "skipped": "tanpa selisih bernilai"}
    if opening:
        from core.opening_balance import retained_earnings_code
        eq = await retained_earnings_code(db)
        contra = {"selisih": eq, "rusak": eq}
        missing = [] if eq else ["subledger_opening_balance.credit_retained_earnings_balancing"]
    else:
        contra_map = await rp.get_mapping(db, VARIANCE_EVENT)
        roles = CONTRA_ROLES[VARIANCE_EVENT]
        contra = {k: str(contra_map.get(r) or "").strip() for k, r in roles.items()}
        missing = [f"{VARIANCE_EVENT}.{roles[k]}" for k, v in contra.items() if not v]
    inv_code_of, err = await inventory_codes(db, {v["kind"] for v in valued})
    if err:
        return {"ok": False, "error": err}
    if missing:
        return {"ok": False, "error": f"Mapping {', '.join(missing)} belum diisi — lengkapi di Profil Posting."}
    memo = (f"Opname stok awal {sess.get('session_no')} · {sess.get('location_code')}" if opening
            else f"Opname {sess.get('session_no')} · {sess.get('location_code')}")
    lines = build_je_lines(valued, inv_code_of, contra, memo)
    if opening:
        for ln in lines:
            ln["description"] = ln["description"].replace("selisih lebih", "stok awal")
    if not lines:
        return {"ok": True, "skipped": "nilai selisih 0"}
    return await rp._create_posted_je(db, _date.fromisoformat(je_date), memo, event, ref, lines, user)


async def approve(db, user: dict, sess: dict) -> dict:
    """GERBANG SUPERVISOR. Level lokasi: set saldo = hitung (+ mutasi sesudah dihitung), penempatan,
    satu jurnal. Level rak: penempatan saja. Aman diulang bila gagal di tengah (baris yang sudah
    diterapkan dicatat di `applied_keys`)."""
    _require_status(sess, "submitted", "approving")
    ev = await evaluate(db, sess)
    if any(x["status"] == ST_BELUM for x in ev["lines"]):
        raise HTTPException(409, "Masih ada baris belum dihitung — ajukan ulang dengan konfirmasi 'anggap 0'")
    count_date = sess.get("count_date") or count_date_of(sess, ev["lines"])
    await check_scan_out_sheets(db, sess, count_date)
    if is_opening(sess):
        await check_opening(db, sess, ev)
    level = sess.get("level") or LEVEL_LOKASI
    loc_ids = sess.get("location_ids") or [sess["location_id"]]
    mids = sorted({x["material_id"] for x in ev["lines"]})
    rows = await _stock_rows(db, mids, loc_ids)
    meta = await _material_meta(db, mids)
    sc = await location_scope(db, sess["location_id"])
    applied = set(sess.get("applied_keys") or [])
    plans, errors = [], []
    if level == LEVEL_LOKASI:
        final = {}       # saldo akhir per material = stok kini + selisih (= hitung + mutasi sesudah dihitung)
        for x in ev["lines"]:
            cur = _r(sum(float(r.get("qty") or 0) for r in rows.get(x["material_id"], [])))
            target = _r(cur + (x["variance_qty"] or 0)) if x["key"] not in applied else cur
            final[x["material_id"]] = target
            if x["key"] in applied or not x["variance_qty"]:
                continue
            if target < 0:
                errors.append(f"{x.get('material_code')}: stok kini {cur} + selisih {x['variance_qty']} = {target} < 0 "
                              "(barang keluar sesudah dihitung melebihi hasil hitung) — hitung ulang barang ini")
            plans.append((x, cur, target))
        place_changes, overflow = plan_location_placement(
            sc["positions"],
            [{"material_id": x["material_id"], "bin_id": e["bin_id"], "counted_qty": e["counted_qty"]}
             for x in ev["lines"] for e in x["entries"]], final)
        findings = [{**o, "jenis": "bin_penuh"} for o in overflow]
    else:
        stock_by_mat = {m: _r(sum(float(r.get("qty") or 0) for r in rs)) for m, rs in rows.items()}
        place_changes, perr, findings = plan_rack_placement(ev["lines"], sc["positions"], stock_by_mat)
        for e in perr:
            code = (meta.get(e["material_id"]) or {}).get("code") or e["material_id"]
            errors.append(f"{code}: penempatan {e['penempatan']} > stok lokasi {e['stok_lokasi']} — tandai "
                          "'barang lebih' (masuk selisih lewat hitung penuh lokasi) atau hitung penuh lokasi")
    if errors:
        raise HTTPException(409, "Approve ditolak: " + "; ".join(errors[:20]))
    # klaim atomik: hanya satu penyetuju; status 'approving' boleh diambil ulang bila macet ≥ 10 menit
    # (proses sebelumnya gagal di tengah) — baris yang sudah diterapkan dilewati lewat `applied_keys`.
    claim = await db[SESS].find_one_and_update(
        {"id": sess["id"], "$or": [{"status": "submitted"},
                                   {"status": "approving", "approving_at": {"$lt": _now() - timedelta(minutes=10)}}]},
        {"$set": {"status": "approving", "approving_at": _now(), "approving_by": user.get("id", "")}})
    if not claim:
        raise HTTPException(409, "Sesi sedang/sudah diproses pengguna lain")
    try:
        return await _apply_approval(db, user, sess, ev, level, rows, meta, sc, plans, place_changes,
                                     findings, count_date)
    except BaseException:
        # 2026-11-06 (Tahap 1): klaim dilepas bila gagal — sesi bisa disetujui ulang. Aman diulang:
        # baris yang sudah diterapkan tercatat di `applied_keys`, jurnal idempoten `opname:{id}`.
        await db[SESS].update_one({"id": sess["id"], "status": "approving"},
                                  {"$set": {"status": "submitted", "approving_at": None}})
        raise


async def _apply_approval(db, user: dict, sess: dict, ev: dict, level: str, rows: dict, meta: dict,
                          sc: dict, plans: list, place_changes: dict, findings: list, count_date: str) -> dict:
    actor = {"id": user.get("id", ""), "email": user.get("email", ""), "name": user.get("name", "")}
    ref = {"source": "opname", "type": "opname", "session_id": sess["id"], "session_no": sess.get("session_no")}
    from core.negative_stock import stock_meta
    writes, valued = [], []
    for x in ev["lines"]:
        if level == LEVEL_LOKASI and x["variance_qty"] and x.get("variance_value"):
            valued.append({"kind": x["kind"], "value": x["variance_value"], "reason": x.get("reason") or "",
                           "material_code": x.get("material_code")})
    # ── 2026-11-06 (Tahap 1): JURNAL DULU, STOK KEMUDIAN ─────────────────────
    # Dulu stok ditimpa lebih dulu, lalu jurnal diposting; bila jurnal gagal (periode tertutup, akun
    # belum dipetakan) sesi tetap 'approved' dengan stok sudah berubah dan tanpa jalan posting ulang
    # ⇒ stok ≠ buku besar. Sekarang jurnal gagal = approve ditolak, stok TIDAK berubah, sesi kembali
    # 'submitted' (bisa disetujui ulang setelah penyebabnya dibereskan).
    je = await _post_session_je(db, user, sess, valued, count_date) if level == LEVEL_LOKASI else \
        {"ok": True, "skipped": "hitung rak hanya memperbaiki penempatan"}
    if not je.get("ok"):
        raise HTTPException(400, f"Approve ditolak: jurnal selisih opname gagal — {je.get('error')}. "
                                 "Stok belum diubah; bereskan penyebabnya lalu setujui ulang.")
    for x, cur, target in plans:
        mat = meta.get(x["material_id"]) or {"id": x["material_id"]}
        m_meta = stock_meta(mat, sc["location"])
        if x["kind"] == "fg":
            m_meta.update({"inventory_category": "fg_internal", "ownership": "cv_da"})
        else:
            # 2026-11-09 (pola G8): baris bahan/aksesoris BARU hasil opname juga diberi identitas resmi
            # (raw_material/cv_da, sama dengan penerimaan barang); baris lama tetap ($ifNull di stock_service).
            ident = stock_service.derive_identity(mat, None)
            m_meta.update({k: ident[k] for k in ("inventory_category", "ownership") if ident.get(k)})
        row_qty = {r.get("location_id"): _r(r.get("qty")) for r in rows.get(x["material_id"], [])}
        for loc_id, q in plan_stock_writes(rows.get(x["material_id"], []), target, sess["location_id"]):
            # 2026-11-06 (Tahap 1): tulis SELISIH (hasil rencana − qty yang dibaca saat approve) secara
            # atomik, bukan qty absolut — mutasi transaksi lain di sela baca & tulis tidak terhapus.
            delta = _r(q - row_qty.get(loc_id, 0.0))
            if delta:
                await stock_service.adjust_by(x["material_id"], loc_id, delta, meta=m_meta, ref=ref,
                                              actor=actor, db=db)
            writes.append({"material_id": x["material_id"], "location_id": loc_id, "qty": q, "delta": delta})
        opening = is_opening(sess)
        if opening and x["kind"] == "fg" and float(x.get("unit_cost") or 0) > 0 and (x["variance_qty"] or 0) > 0:
            # 2026-11-09: WAC awal FG = harga stok awal (WAC berjalan / HPP standar); lapisan → jurnal sesi.
            from core import fg_cost_layers as fcl
            layer = await fcl.push_layer(
                db, material_id=x["material_id"], qty=int(round(x["variance_qty"])), actor=actor,
                unit_cost=float(x["unit_cost"]), components=x.get("opening_components"),
                ref={"type": "opening_count", "receipt_id": sess["id"], "receipt_code": sess.get("session_no")})
            if layer and je.get("je_id"):
                await db[fcl.LAYERS].update_one({"id": layer["id"]}, {"$set": {
                    "gl_je_id": je["je_id"], "gl_basis": "opname_stok_awal"}})
        await db.rahaza_material_movements.insert_one({
            # type 'opname' (bukan 'adjust'): jurnalnya SATU per sesi; tombol "post ulang" per mutasi
            # (`/material-movements/{id}/post-to-gl`) menolak tipe ini → tidak bisa terjurnal dobel.
            # 2026-11-09: sesi stok awal = type 'opening' (penanda "stok awal sekali per barang×lokasi", sama
            # dengan impor Excel STOK_AWAL; juga ditolak tombol post ulang).
            "id": _uid(), "type": "opening" if opening else "opname",
            "movement_type": "opening" if opening else "opname", "material_id": x["material_id"],
            "material_name": x.get("material_name"), "material_code": x.get("material_code"),
            "qty": x["variance_qty"], "qty_signed": x["variance_qty"], "unit_cost": x.get("unit_cost"),
            "adjustment_reason": x.get("reason") or "opname", "location_id": sess["location_id"],
            "to_location_id": sess["location_id"], "ref_type": "opname", "ref_id": sess["id"],
            "reference_type": "opname", "reference_id": sess["id"],
            "notes": f"Opname {sess.get('session_no')}: sistem {x['system_qty']} → hitung {x['counted_qty']}",
            "created_by": user.get("id", ""), "created_by_name": user.get("name", ""),
            "created_at": _now(), "timestamp": _now()})
        await db[SESS].update_one({"id": sess["id"]}, {"$addToSet": {"applied_keys": x["key"]}})
    n_pos = await _write_positions(db, user, sess, place_changes, meta)
    if je.get("je_id"):
        await db.rahaza_material_movements.update_many(
            {"ref_type": "opname", "ref_id": sess["id"]},
            {"$set": {"gl_je_id": je["je_id"], "gl_je_number": je.get("je_number"), "gl_posted_at": _now(),
                      "post_error": None}})
    uncosted = [x.get("material_code") for x in ev["lines"]
                if x.get("variance_qty") and not float(x.get("unit_cost") or 0)]
    summary = {**ev["totals"], "stock_writes": len(writes), "positions_updated": n_pos,
               "je_posted": 1 if je.get("je_id") else 0, "je_number": je.get("je_number"),
               "je_error": None if je.get("ok") else je.get("error"), "uncosted_items": uncosted[:50],
               "findings": findings[:200]}
    await db[SESS].update_one({"id": sess["id"]}, {"$set": {
        "status": "approved", "approved_at": _now(), "approved_by": user.get("id", ""),
        "approved_by_name": user.get("name", ""), "count_date": count_date, "summary": summary,
        "je_id": je.get("je_id"), "je_number": je.get("je_number"),
        "result": {"lines": ev["lines"], "totals": ev["totals"], "writes": writes,
                   "positions": {k: list(v) for k, v in place_changes.items()}, "je": je, "findings": findings}}})
    await _roll_import_hook(db, sess, "approved")
    return await get_session(db, sess["id"])


async def _roll_import_hook(db, sess: dict, status: str) -> None:
    """2026-11-09: sesi stok awal dari impor roll kain — roll ikut aktif (disetujui) / batal (ditolak)."""
    if not (sess or {}).get("roll_import_id"):
        return
    from core import fabric_roll_import as fri
    await fri.on_session_final(db, sess, status)


async def reject(db, user: dict, sess: dict, reason: str = "") -> dict:
    _require_status(sess, "submitted")
    await db[SESS].update_one({"id": sess["id"], "status": "submitted"}, {"$set": {
        "status": "rejected", "rejected_at": _now(), "rejected_by": user.get("id", ""),
        "rejected_by_name": user.get("name", ""), "reject_reason": reason or ""}})
    await _roll_import_hook(db, sess, "rejected")
    return {"ok": True, "status": "rejected"}


async def cancel(db, user: dict, sess: dict) -> dict:
    _require_status(sess, "counting", "submitted")
    await db[SESS].update_one({"id": sess["id"], "status": {"$in": ["counting", "submitted"]}}, {"$set": {
        "status": "cancelled", "cancelled_at": _now(), "cancelled_by": user.get("id", "")}})
    await _roll_import_hook(db, sess, "cancelled")
    return {"ok": True, "status": "cancelled"}


# ═════════════════════════════ DAFTAR (baru + arsip) ═════════════════════════════
def _legacy_acc_row(s: dict) -> dict:
    return {"id": s.get("id"), "session_no": s.get("session_no"), "engine": "acc_lama", "archived": True,
            "status": s.get("status"), "scope_label": s.get("scope_label") or "Aksesoris (semua lokasi)",
            "kinds": ["aksesoris"], "source": "aksesoris", "created_at": s.get("created_at"),
            "summary": s.get("summary"), "approved_at": s.get("approved_at")}


async def list_sessions(db, *, status: str = "", kind: str = "", limit: int = 100) -> list:
    """Sesi baru + arsip. `kind='aksesoris'` (menu Portal Aksesoris) = sesi berfilter/berasal aksesoris
    + arsip opname aksesoris lama; arsip opname3 lama (isi bin campuran) hanya tampil tanpa filter."""
    q: dict = {}
    if status:
        q["status"] = status
    rows = await db[SESS].find(q, {"_id": 0, "lines": 0, "snapshot": 0, "result": 0}) \
        .sort("created_at", -1).limit(int(limit)).to_list(500)
    out = []
    for s in rows:
        new = s.get("engine") == ENGINE
        if kind and (not new or (kind not in (s.get("kinds") or []) and s.get("source") != kind)):
            continue
        out.append({**s, "archived": not new, "engine": s.get("engine") or "opname3_lama"})
    if not kind or kind == "aksesoris":
        q2 = {"domain": "accessory"}
        if status:
            q2["status"] = status
        legacy = await db[LEGACY_ACC].find(q2, {"_id": 0, "count_items": 0}).sort("created_at", -1) \
            .limit(int(limit)).to_list(500)
        out += [_legacy_acc_row(s) for s in legacy]
    out.sort(key=lambda s: aware(s.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[: int(limit)]


async def legacy_acc_detail(db, session_id: str) -> Optional[dict]:
    s = await db[LEGACY_ACC].find_one({"id": session_id}, {"_id": 0})
    if not s:
        return None
    return {**_legacy_acc_row(s), "count_items": s.get("count_items") or []}
