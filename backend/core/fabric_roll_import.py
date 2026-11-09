"""core/fabric_roll_import.py — IMPOR ROLL KAIN MASSAL untuk stok awal (2026-11-09, klarifikasi owner C5).

KEADAAN SEBELUM BERKAS INI: roll (`wh_fabric_rolls`) hanya bisa dibuat satu per satu atau dari penerimaan
barang; stok kain (`rahaza_material_stock`, kg/yard) dan roll adalah dua catatan terpisah. Cutting MENOLAK
kain tanpa roll bersisa, jadi stok awal kain tanpa roll = cutting berhenti; sebaliknya memuat roll dan stok
dari dua angka berbeda = sisa roll ≠ stok.

ATURAN (satu jalur):
  * Satu baris Excel = satu kelompok roll: kode kain, lokasi, lot, jumlah roll, isi per roll (kg untuk kain
    ber-kg, yard untuk kain ber-yard). Isi kosong ⇒ rata-rata owner 25 kg / 115 yard (kain ber-meter 115 yard =
    105,16 m) dan roll DITANDAI "rata-rata" supaya bisa ditimbang ulang.
  * Pratinjau dulu (tanpa menulis). Terapkan = roll dibuat (nomor otomatis, status `pending_opening` — belum
    bisa dipotong) + SATU sesi "Opname stok awal" per lokasi berisi Σ isi roll per kain, langsung diajukan.
  * Stok & nilainya hanya lahir lewat persetujuan Keuangan/owner atas sesi itu (`core.opname_engine`, mode
    stok awal: lawan ekuitas saldo awal, tolak barang tanpa harga, sekali per barang×lokasi). Disetujui ⇒ roll
    menjadi `in_stock`; ditolak/dibatalkan ⇒ roll `cancelled`.
  * Idempoten: berkas yang sama (isi baris identik) tidak membuat roll/sesi kedua; kain×lokasi yang sudah punya
    stok awal / stok / impor roll yang menunggu persetujuan ditolak di pratinjau.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from core import fabric_roll_engine as fre

log = logging.getLogger(__name__)

IMPORTS = "wh_fabric_roll_imports"
SHEET = "ROLL_KAIN"
COLS = ["kode_kain", "nama_kain", "satuan", "lokasi_kode", "lot", "jumlah_roll", "isi_per_roll", "catatan"]
# Rata-rata owner (klarifikasi C5): 1 roll = 25 kg atau 115 yard.
AVERAGE_PER_ROLL = {"kg": 25.0, "yard": 115.0, "meter": round(115 * 0.9144, 2)}
MAX_ROLLS_PER_ROW = 500
PENDING = "pending_opening"
ST_AWAITING, ST_DONE, ST_CANCELLED, ST_PARTIAL = "menunggu_persetujuan", "selesai", "dibatalkan", "sebagian"


def _now():
    return datetime.now(timezone.utc)


def _num(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def per_roll_qty(raw, uom: str) -> tuple:
    """(isi per roll, rata-rata?) — fungsi murni. Kosong ⇒ rata-rata owner; ValueError bila tidak sah."""
    v = _num(raw)
    if v is None:
        if uom not in AVERAGE_PER_ROLL:
            raise ValueError(f"kain bersatuan {uom} tidak punya rata-rata per roll — isi isi_per_roll")
        return AVERAGE_PER_ROLL[uom], True
    if v <= 0:
        raise ValueError("isi_per_roll harus lebih dari 0 (kosongkan untuk rata-rata 25 kg / 115 yard)")
    return round(v, 3), False


def batch_key(rows: list) -> str:
    """Sidik isi berkas (baris yang dinormalkan) — kunci idempoten impor."""
    norm = sorted((r["material_id"], r["location_id"], r["lot"], r["rolls"], r["per_roll"], r["average"])
                  for r in rows)
    return hashlib.sha256(json.dumps(norm, default=str).encode()).hexdigest()


async def build_template(db) -> bytes:
    """Template berisi kain aktif yang dilacak per roll (kode, nama, satuan) + lokasi bahan bawaan."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from core.location_resolver import legacy_location_for_role
    loc = await legacy_location_for_role(db, "bahan") or {}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PETUNJUK"
    for t in ("IMPOR ROLL KAIN — stok awal kain per roll (Gudang → Roll Kain → Impor roll)",
              "Isi sheet ROLL_KAIN: satu baris = satu kelompok roll dengan isi sama (atau satu baris per roll bila ditimbang).",
              "lokasi_kode = lokasi simpan kain (lihat REF_LOKASI). lot = lot/warna celup (boleh kosong).",
              "jumlah_roll = berapa gulungan. isi_per_roll = berat (kg) untuk kain ber-kg, panjang (yard) untuk kain ber-yard.",
              "isi_per_roll KOSONG = rata-rata 25 kg / 115 yard per roll; roll ditandai 'rata-rata' supaya ditimbang ulang.",
              "Baris yang jumlah_roll-nya kosong/0 dilewati. Pratinjau dulu; Terapkan membuat roll + SATU sesi 'Opname stok awal'",
              "per lokasi yang disetujui Keuangan/owner. Stok kain & nilainya baru masuk setelah disetujui (roll baru bisa dipotong).",
              "Kain harus sudah berharga di master (stok awal tanpa harga ditolak). Kain×lokasi hanya sekali dimuat stok awalnya."):
        ws.append([t])
    ws.column_dimensions["A"].width = 120
    ws = wb.create_sheet(SHEET)
    ws.append(COLS)
    hdr = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F4E78")
    for c in ws[1]:
        c.font, c.fill = hdr, fill
    async for m in db.rahaza_materials.find({"active": {"$ne": False}, "type": {"$ne": "fg"}},
                                            {"_id": 0, "code": 1, "name": 1, "unit": 1, "type": 1,
                                             "is_cut_panel": 1}).sort("code", 1):
        if fre.is_roll_material(m):
            ws.append([m.get("code"), m.get("name"), fre.roll_uom(m.get("unit")), loc.get("code") or "", None, None,
                       None, None])
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for i in (3, 4, 5, 6):
            row[i].fill = yellow
    for i, w in enumerate((18, 40, 8, 14, 14, 12, 14, 30)):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
    ws.freeze_panes = "B2"
    ws = wb.create_sheet("REF_LOKASI")
    ws.append(["lokasi_kode", "nama", "peran"])
    async for lo in db.rahaza_locations.find({"active": {"$ne": False}}, {"_id": 0, "code": 1, "name": 1,
                                                                          "storage_role": 1}).sort("code", 1):
        ws.append([lo.get("code"), lo.get("name"), lo.get("storage_role") or ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def parse(db, data: bytes) -> dict:
    """Baca berkas → {ok, errors, warnings, rows, groups, totals, batch_key}. TIDAK menulis apa pun."""
    import openpyxl
    from core import scan_resolver as sr
    from core.catalog_stock import blocked_location_ids
    from core.opname_engine import opened_materials
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errors": [f"Berkas bukan Excel .xlsx yang valid: {e}"], "warnings": [], "rows": [],
                "groups": [], "totals": {}}
    if SHEET not in wb.sheetnames:
        return {"ok": False, "errors": [f"Sheet {SHEET} tidak ditemukan — pakai template dari layar Roll Kain."],
                "warnings": [], "rows": [], "groups": [], "totals": {}}
    blocked = await blocked_location_ids(db)
    locs = {lo["code"].upper(): lo for lo in await db.rahaza_locations.find(
        {}, {"_id": 0, "id": 1, "code": 1, "name": 1, "active": 1}).to_list(2000) if lo.get("code")}
    errors, warnings, rows = [], [], []
    idx = {c: i for i, c in enumerate(COLS)}
    for n, r in enumerate(wb[SHEET].iter_rows(values_only=True, min_row=2), start=2):
        r = tuple(r or ()) + (None,) * (len(COLS) - len(r or ()))
        code = str(r[idx["kode_kain"]] or "").strip()
        if not code:
            continue
        try:
            rolls = _num(r[idx["jumlah_roll"]])
        except ValueError:
            errors.append(f"baris {n}: jumlah_roll bukan angka")
            continue
        if not rolls:
            continue
        if rolls < 0 or int(rolls) != rolls or rolls > MAX_ROLLS_PER_ROW:
            errors.append(f"baris {n}: jumlah_roll harus bilangan bulat 1–{MAX_ROLLS_PER_ROW}")
            continue
        res = await sr.resolve_material(db, sr.normalize_code(code))
        if not res:
            errors.append(f"baris {n}: kode kain {code} tidak ada di master")
            continue
        mat = res["_doc"]
        if not res.get("aktif", True):
            errors.append(f"baris {n}: {res['kode']} NONAKTIF di master — aktifkan dulu atau pakai kode penggantinya")
            continue
        if not fre.is_roll_material(mat):
            errors.append(f"baris {n}: {res['kode']} bukan kain yang dilacak per roll (satuan {mat.get('unit')})")
            continue
        if res["kode"].upper() != code.upper():
            warnings.append(f"baris {n}: kode {code} dibaca sebagai {res['kode']} ({res.get('via')})")
        uom = fre.roll_uom(mat.get("unit"))
        try:
            per, avg = per_roll_qty(r[idx["isi_per_roll"]], uom)
        except ValueError as e:
            errors.append(f"baris {n}: {res['kode']} {e}")
            continue
        loc_code = str(r[idx["lokasi_kode"]] or "").strip().upper()
        loc = locs.get(loc_code)
        if not loc or loc.get("active") is False:
            errors.append(f"baris {n}: lokasi_kode '{loc_code}' tidak ada / nonaktif (lihat REF_LOKASI)")
            continue
        if loc["id"] in blocked:
            errors.append(f"baris {n}: lokasi {loc_code} lokasi karantina/terblokir — kain stok awal masuk lokasi simpan")
            continue
        cost = float(mat.get("unit_cost") or 0)
        if cost <= 0:
            errors.append(f"baris {n}: {res['kode']} belum berharga di master — isi harga kain dulu (stok awal tanpa "
                          "harga ditolak saat disetujui)")
            continue
        rows.append({"row": n, "material_id": mat["id"], "code": res["kode"], "name": mat.get("name") or "",
                     "uom": uom, "location_id": loc["id"], "location_code": loc.get("code"),
                     "location_name": loc.get("name") or "", "lot": str(r[idx["lot"]] or "").strip(),
                     "rolls": int(rolls), "per_roll": per, "average": avg,
                     "qty": round(per * int(rolls), 3), "unit_cost": cost,
                     "notes": str(r[idx["catatan"]] or "").strip()})
    groups: dict = {}
    for x in rows:
        g = groups.setdefault((x["material_id"], x["location_id"]), {
            "material_id": x["material_id"], "code": x["code"], "name": x["name"], "uom": x["uom"],
            "location_id": x["location_id"], "location_code": x["location_code"], "rolls": 0, "qty": 0.0,
            "average_rolls": 0, "unit_cost": x["unit_cost"], "value": 0.0})
        g["rolls"] += x["rolls"]
        g["qty"] = round(g["qty"] + x["qty"], 3)
        g["average_rolls"] += x["rolls"] if x["average"] else 0
        g["value"] = round(g["qty"] * g["unit_cost"], 2)
    # kain×lokasi yang sudah punya stok awal / stok / impor roll yang masih menunggu ⇒ tolak (jangan dobel)
    for (mid, lid), g in groups.items():
        if mid in await opened_materials(db, [mid], [lid]):
            errors.append(f"{g['code']} @ {g['location_code']}: sudah punya stok awal — koreksi lewat Sesi Opname / "
                          "adjust roll, bukan impor ulang")
            continue
        st = await db.rahaza_material_stock.find_one({"material_id": mid, "location_id": lid}, {"_id": 0, "qty": 1})
        if st and abs(float(st.get("qty") or 0)) > 1e-9:
            errors.append(f"{g['code']} @ {g['location_code']}: sudah ada stok {float(st['qty']):g} {g['uom']} di lokasi "
                          "itu — impor roll stok awal hanya untuk kain yang belum tercatat (pakai Sesi Opname)")
            continue
        if await db[IMPORTS].find_one({"status": ST_AWAITING, "groups": {"$elemMatch": {
                "material_id": mid, "location_id": lid}}}, {"_id": 0, "id": 1}):
            errors.append(f"{g['code']} @ {g['location_code']}: impor roll lain untuk kain ini masih menunggu "
                          "persetujuan Keuangan")
    avg_rolls = sum(g["average_rolls"] for g in groups.values())
    if avg_rolls:
        warnings.append(f"{avg_rolls} roll memakai rata-rata (25 kg / 115 yard) — timbang/ukur ulang lalu koreksi "
                        "lewat adjust roll bila berbeda.")
    totals = {"rows": len(rows), "rolls": sum(x["rolls"] for x in rows), "groups": len(groups),
              "locations": len({lid for _m, lid in groups}), "average_rolls": avg_rolls,
              "value": round(sum(g["value"] for g in groups.values()), 2)}
    return {"ok": not errors and bool(rows), "errors": errors + ([] if rows else ["Tidak ada baris roll yang diisi."]),
            "warnings": warnings, "rows": rows, "groups": list(groups.values()), "totals": totals,
            "batch_key": batch_key(rows) if rows else ""}


async def apply(db, user: dict, data: bytes, filename: str = "") -> dict:
    """Terapkan impor (idempoten per isi berkas): roll `pending_opening` + sesi opname stok awal per lokasi."""
    from core import opname_engine as eng
    parsed = await parse(db, data)
    # idempoten DULU: berkas yang sama (yang barisnya kini ditolak karena "sudah menunggu persetujuan" /
    # "sudah punya stok awal") dijawab dengan impor lamanya, bukan galat.
    key = parsed.get("batch_key") or ""
    prev = await db[IMPORTS].find_one({"batch_key": key, "status": {"$ne": ST_CANCELLED}}, {"_id": 0}) if key else None
    if prev:
        return {"already": True, "import": prev, "message": f"Berkas yang sama sudah diimpor ({prev.get('import_no')})."}
    if not parsed["ok"]:
        raise HTTPException(400, {"message": "Berkas belum lolos pemeriksaan.", "errors": parsed["errors"]})
    imp_id = str(uuid.uuid4())
    from utils.counters import gen_prefixed_number
    imp_no = await gen_prefixed_number(db, IMPORTS, "import_no", f"IMR-{_now():%Y%m}-", 3)
    doc = {"id": imp_id, "import_no": imp_no, "batch_key": key, "status": "memproses", "filename": filename or "",
           "groups": [{k: g[k] for k in ("material_id", "code", "location_id", "location_code", "rolls", "qty",
                                         "average_rolls", "value")} for g in parsed["groups"]],
           "totals": parsed["totals"], "session_ids": [], "created_at": _now(),
           "created_by": user.get("id"), "created_by_name": user.get("name") or ""}
    await db[IMPORTS].insert_one(dict(doc))
    actor_name = user.get("name") or user.get("id")
    sessions, n_rolls = [], 0
    by_loc: dict = {}
    for g in parsed["groups"]:
        by_loc.setdefault(g["location_id"], []).append(g)
    for lid, gs in by_loc.items():
        sess = await eng.create_session(
            db, user, location_id=lid, material_ids=[g["material_id"] for g in gs], opening=True,
            source="impor_roll", notes=f"Impor roll kain {imp_no} ({filename or 'Excel'})",
            extra={"roll_import_id": imp_id, "roll_import_no": imp_no})
        sess = await eng.get_session(db, sess["id"], for_write=True)
        for g in gs:
            mat = await db.rahaza_materials.find_one({"id": g["material_id"]}, {"_id": 0})
            await eng.record_count(db, user, sess, mat=mat, bin_id="", bin_label=f"{g['location_code']} · impor roll",
                                   qty=g["qty"], mode="set")
            sess = await eng.get_session(db, sess["id"], for_write=True)
        sess = await eng.submit(db, user, sess, notes=f"Diajukan otomatis dari impor roll {imp_no}")
        sessions.append({"id": sess["id"], "session_no": sess.get("session_no"), "location_code": gs[0]["location_code"]})
        for x in [r for r in parsed["rows"] if r["location_id"] == lid]:
            for _ in range(x["rolls"]):
                roll_no = await fre.next_roll_no(db)
                w = fre.is_weight_uom(x["uom"])
                roll = {
                    "id": str(uuid.uuid4()), "roll_no": roll_no, "material_id": x["material_id"],
                    "material_code": x["code"], "material_name": x["name"], "color": "", "color_lot": x["lot"],
                    "supplier_name": "", "uom": x["uom"],
                    "length_m": 0.0 if w else x["per_roll"], "weight_kg": x["per_roll"] if w else 0.0,
                    "remaining_m": 0.0 if w else x["per_roll"], "remaining_kg": x["per_roll"] if w else 0.0,
                    "received_date": _now().date().isoformat(), "po_no": "", "qc_status": "pass",
                    "status": PENDING, "is_average": x["average"],
                    "position_id": "", "position_barcode": "", "location_id": x["location_id"],
                    "location_name": x["location_name"] or x["location_code"], "unit_cost": x["unit_cost"],
                    "notes": ("rata-rata · " if x["average"] else "") + (x["notes"] or f"Stok awal impor {imp_no}"),
                    "opening_import_id": imp_id, "opening_import_no": imp_no, "opening_session_id": sess["id"],
                    "created_at": _now(), "created_by": actor_name, "updated_at": _now(), "updated_by": actor_name}
                await db[fre.ROLLS].insert_one(dict(roll))
                await db[fre.ROLL_MOVES].insert_one({
                    "id": str(uuid.uuid4()), "roll_id": roll["id"], "roll_no": roll_no, "movement_type": "receive",
                    "qty": x["per_roll"], "unit": x["uom"], "reference_type": "opening_import",
                    "reference_id": imp_id, "reference_no": imp_no, "to_location": x["location_code"],
                    "notes": f"Stok awal impor roll {imp_no}" + (" (rata-rata)" if x["average"] else ""),
                    "created_at": _now(), "created_by": actor_name})
                n_rolls += 1
    await db[IMPORTS].update_one({"id": imp_id}, {"$set": {
        "status": ST_AWAITING, "session_ids": [s["id"] for s in sessions], "sessions": sessions,
        "rolls_created": n_rolls, "updated_at": _now()}})
    return {"already": False, "import": await db[IMPORTS].find_one({"id": imp_id}, {"_id": 0}),
            "message": (f"{n_rolls} roll dibuat (menunggu persetujuan stok awal) dan {len(sessions)} sesi Opname stok "
                        "awal diajukan ke Keuangan.")}


async def on_session_final(db, sess: dict, status: str) -> dict:
    """Dipanggil mesin opname saat sesi impor roll disetujui / ditolak / dibatalkan."""
    imp_id = (sess or {}).get("roll_import_id")
    if not imp_id:
        return {}
    new = "in_stock" if status == "approved" else "cancelled"
    res = await db[fre.ROLLS].update_many({"opening_session_id": sess["id"], "status": PENDING},
                                         {"$set": {"status": new, "updated_at": _now(),
                                                   **({} if new == "in_stock" else {"remaining_m": 0.0,
                                                                                    "remaining_kg": 0.0})}})
    imp = await db[IMPORTS].find_one({"id": imp_id}, {"_id": 0}) or {}
    done = dict(imp.get("session_status") or {})
    done[sess["id"]] = status
    ids = imp.get("session_ids") or []
    if ids and all(done.get(i) for i in ids):
        vals = {done[i] for i in ids}
        st = ST_DONE if vals == {"approved"} else (ST_CANCELLED if "approved" not in vals else ST_PARTIAL)
    else:
        st = imp.get("status") or ST_AWAITING
    await db[IMPORTS].update_one({"id": imp_id}, {"$set": {"session_status": done, "status": st, "updated_at": _now()}})
    return {"rolls": res.modified_count, "status": st}
