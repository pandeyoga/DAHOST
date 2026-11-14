"""routes/wh_scan_out.py — Gudang → OUTBOUND → "Scan Keluar Penjualan" (K15, 2026-11-02).

Lapisan HTTP tipis di atas `core/scan_out.py` (semua aturan & angka ada di sana).

  GET  /api/wh/scan-out/locations            lokasi asal (wajib dipilih) + pcs FG jual per lokasi
  GET  /api/wh/scan-out/stores               toko/platform (opsional per scan)
  GET  /api/wh/scan-out/today?location_id=   lembar hari ini + baris + daftar merah + lembar lain yang terbuka
  POST /api/wh/scan-out/scan                 {location_id, code, client_scan_id, multiplier?, kind?, account_id?}
  POST /api/wh/scan-out/pick                 {location_id, kind?, account_id?, items:[{material_id, qty, client_scan_id}]}
                                             "Pilih tanpa scan" (10 Nov 2026) — tiap barang lewat mesin scan
  POST /api/wh/scan-out/lines/{id}/void      {reason?} — salah scan sebelum Tutup Hari
  GET  /api/wh/scan-out/retry-queue          ?location_id=&sheet_id= antrean scan gagal di server (Tahap 2)
  POST /api/wh/scan-out/lines/{id}/retry     kirim ulang baris gagal (id sama → tidak dobel)
  POST /api/wh/scan-out/lines/{id}/discard   {reason?} batalkan baris gagal (langkah yang terjadi dibalik)
  POST /api/wh/scan-out/sheets/{id}/close    Tutup Hari (SPV) → satu jurnal HPP per lembar
  GET  /api/wh/scan-out/sheets               ?date=&location_id=&status=
  GET  /api/wh/scan-out/report               ?date=&location_id=  laporan harian
  GET  /api/wh/scan-out/control              ?date=&days=  pcs impor vs pcs scan
  POST /api/wh/scan-out/control/{date}/review {note?} — SPV: selisih sudah diperiksa
  GET/PUT /api/wh/scan-out/settings          ambang selisih kontrol
  GET  /api/wh/scan-out/langkah2             status penguncian Langkah 2
"""
from __future__ import annotations
from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from auth import log_activity, require_auth, serialize_doc
from core.authz import izin_atau_peran_lama  # 14 Nov 2026: centang owner = penentu
from core import scan_out as so
from database import get_db

router = APIRouter(prefix="/api/wh/scan-out", tags=["wh-scan-out"])

so.register_scheduler_jobs()


def _err(e: so.ScanOutError):
    return HTTPException(e.status, e.message)


async def _require(request: Request, roles: list, perm: str, what: str) -> dict:
    user = await require_auth(request)
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    if not izin_atau_peran_lama(user, roles, perm):
        from core.authz import pesan_centang
        raise HTTPException(403, pesan_centang(user, apa="Scan Keluar Penjualan"))
    return user


def _can_supervise(user: dict) -> bool:
    return izin_atau_peran_lama(user, so.SUPERVISE_ROLES, "warehouse.approve")


@router.get("/locations")
async def list_locations(request: Request, semua: bool = False):
    """Lokasi untuk Scan Keluar. 2026-11-09 (audit gudang G9): bawaan hanya lokasi berperan barang jadi
    + lokasi yang sedang memegang stok jual FG (dulu Ruang Aksesoris & gudang bahan ikut tampil; salah
    pilih ⇒ minus di lokasi itu sementara stok ada di lokasi lain). `semua=1` = semua lokasi simpan."""
    await require_auth(request)
    db = get_db()
    from core import location_resolver
    from core.catalog_stock import blocked_location_ids
    blocked = await blocked_location_ids(db)
    pcs: dict = {}
    # SATU aturan stok jual FG (sama dengan scan): baris hasil pindah tanpa kategori ikut terhitung.
    async for r in db.rahaza_material_stock.aggregate([
        {"$match": {**so.sellable_row_match(blocked), "material_id": {"$in": await so.fg_material_ids(db)}}},
        {"$group": {"_id": "$location_id", "qty": {"$sum": {"$ifNull": ["$qty", 0]}},
                    "skus": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$qty", 0]}, 0]}, 1, 0]}}}}]):
        if r.get("_id"):
            pcs[r["_id"]] = {"qty": float(r.get("qty") or 0), "skus": int(r.get("skus") or 0)}
    out, seen, hidden = [], set(), 0
    for loc in await location_resolver.list_storage_locations(db):
        if loc["id"] in blocked:
            continue
        seen.add(loc["id"])
        holds = pcs.get(loc["id"], {}).get("qty", 0.0) > 0
        if not semua and loc.get("role") != "fg" and not holds:
            hidden += 1
            continue
        out.append({**loc, "fg_qty": pcs.get(loc["id"], {}).get("qty", 0.0),
                    "fg_skus": pcs.get(loc["id"], {}).get("skus", 0)})
    if not semua and not out and hidden:
        return await list_locations(request, semua=True)   # belum ada lokasi berperan FG: jangan kosong
    extra = [i for i in pcs if i not in seen and i not in blocked and (semua or pcs[i]["qty"] > 0)]
    disp = await location_resolver.build_display_map(db, extra)
    for i in extra:
        d = disp.get(i) or {}
        out.append({"id": i, "code": d.get("code") or i[:8], "name": d.get("name") or "", "source": d.get("source"),
                    "role": None, "fg_qty": pcs[i]["qty"], "fg_skus": pcs[i]["skus"]})
    out.sort(key=lambda x: (-(x["fg_qty"] or 0), x.get("code") or ""))
    return out


@router.get("/stores")
async def list_stores(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.marketing_platform_accounts.find(
        {"status": {"$nin": ["inactive", "archived", "deleted"]}},
        {"_id": 0, "id": 1, "account_name": 1, "account_code": 1, "platform": 1}).sort("account_name", 1).to_list(500)
    return rows


@router.get("/today")
async def today(request: Request, location_id: Optional[str] = None):
    user = await require_auth(request)
    db = get_db()
    day = so.today_str()
    sheets, lines, rejects = [], [], []
    if location_id:
        sheets = await db[so.SHEETS].find({"date": day, "location_id": location_id}, {"_id": 0}
                                          ).sort("seq", 1).to_list(50)
        # 2026-11-06 (pola P7): SEMUA baris hari ini untuk total & per SKU (dulu to_list(2000) — hari ramai
        # memotong total scan diam-diam, padahal total ini dicocokkan dengan pesanan). Layar tetap 500 baris.
        lines = [ln async for ln in db[so.LINES].find({"date": day, "location_id": location_id}, {"_id": 0}
                                                      ).sort("scanned_at", -1)]
        rejects = await db[so.REJECTS].find({"date": day, "location_id": location_id}, {"_id": 0}
                                            ).sort("at", -1).to_list(300)
    open_sheet = next((s for s in sheets if s.get("status") != "closed"), None)
    active = [ln for ln in lines if ln.get("status") == "active"]
    totals = so.sum_lines(active)
    open_totals = so.sum_lines([ln for ln in active if open_sheet and ln.get("sheet_id") == open_sheet["id"]])
    per_sku: dict = {}
    for ln in active:
        r = per_sku.setdefault(ln["material_id"], {"sku": ln.get("sku"), "name": ln.get("name"), "net": 0})
        r["net"] += so.line_sign(ln) * int(ln.get("qty") or 0)
    # lembar TANGGAL LALU yang belum tertutup (biasanya jurnalnya gagal) — perlu tindakan SPV
    others = [s for s in await so.sheets_still_open(db) if (s.get("date") or "") < day]
    # 2026-11-06 (Tahap 2): antrean kirim ulang DI SERVER — baris gagal lokasi ini (lintas tanggal),
    # milik petugas yang login; SPV melihat semua petugas.
    retry = []
    if location_id:
        retry = await so.retry_queue(db, location_id=location_id,
                                     operator_id=None if _can_supervise(user) else str(user.get("id") or ""))
    return serialize_doc({
        "date": day, "location_id": location_id, "sheets": sheets, "open_sheet": open_sheet,
        "totals": totals, "open_totals": open_totals,
        "per_sku": sorted(per_sku.values(), key=lambda r: -r["net"]),
        "lines": [so.public_line(ln) for ln in lines[:500]], "rejects": rejects,
        "other_open_sheets": others,
        "retry_queue": retry,
        "can_supervise": _can_supervise(user),
        "can_scan": izin_atau_peran_lama(user, so.SCAN_ROLES, "warehouse.manage"),
        "me": {"id": str(user.get("id") or ""), "name": user.get("name")},
        "langkah2": await so.langkah2_status(db),
    })


@router.post("/scan")
async def post_scan(request: Request):
    user = await _require(request, so.SCAN_ROLES, "warehouse.manage", "hanya peran gudang/packing yang boleh scan")
    body = await request.json()
    db = get_db()
    try:
        out = await so.scan(db, location_id=body.get("location_id"), raw_code=body.get("code"),
                            client_scan_id=body.get("client_scan_id"), multiplier=body.get("multiplier", 1),
                            kind=body.get("kind") or so.KIND_SCAN, account_id=body.get("account_id") or "",
                            user=user)
    except so.ScanOutError as e:
        raise _err(e)
    return serialize_doc(out)


@router.post("/pick")
async def post_pick(request: Request):
    """2026-11-10 (owner): "Pilih tanpa scan" — banyak barang jadi sekaligus dari daftar cari.
    Hak sama dengan scan; setiap barang lewat mesin scan yang sama (`core.scan_out.pick`)."""
    user = await _require(request, so.SCAN_ROLES, "warehouse.manage", "hanya peran gudang/packing yang boleh scan")
    body = await request.json()
    try:
        out = await so.pick(get_db(), location_id=body.get("location_id"), items=body.get("items"),
                            kind=body.get("kind") or so.KIND_SCAN, account_id=body.get("account_id") or "",
                            user=user)
    except so.ScanOutError as e:
        raise _err(e)
    if out["accepted"]:
        await log_activity(user["id"], user.get("name", ""), "pick", "wh.scan_out",
                           f"tanpa scan: {out['accepted']} barang {out['pcs']} pcs "
                           f"({body.get('kind') or so.KIND_SCAN}); ditolak {out['rejected']}, gagal {out['failed']}")
    return serialize_doc(out)


@router.post("/lines/{line_id}/void")
async def void(line_id: str, request: Request):
    user = await _require(request, so.SCAN_ROLES, "warehouse.manage", "hanya peran gudang/packing")
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — badan kosong boleh
        body = {}
    db = get_db()
    try:
        out = await so.void_line(db, line_id, user=user, reason=(body or {}).get("reason") or "",
                                 may_void_others=_can_supervise(user))
    except so.ScanOutError as e:
        raise _err(e)
    ln = out.get("line") or {}
    await log_activity(user["id"], user.get("name", ""), "void", "wh.scan_out",
                       f"{ln.get('sheet_number')} {ln.get('sku')} ×{ln.get('qty')} ({ln.get('kind')})")
    return serialize_doc(out)


@router.get("/retry-queue")
async def retry_queue(request: Request, location_id: Optional[str] = None, sheet_id: Optional[str] = None):
    """2026-11-06 (Tahap 2): antrean scan gagal yang tersimpan di server (per lembar / petugas)."""
    user = await require_auth(request)
    rows = await so.retry_queue(get_db(), location_id=location_id or None, sheet_id=sheet_id or None,
                                operator_id=None if _can_supervise(user) else str(user.get("id") or ""))
    return serialize_doc(rows)


@router.post("/lines/{line_id}/retry")
async def retry(line_id: str, request: Request):
    """Kirim ulang satu baris dari antrean server (id baris yang sama → tidak dobel)."""
    user = await _require(request, so.SCAN_ROLES, "warehouse.manage", "hanya peran gudang/packing")
    try:
        out = await so.retry_line(get_db(), line_id, user=user, may_retry_others=_can_supervise(user))
    except so.ScanOutError as e:
        raise _err(e)
    return serialize_doc(out)


@router.post("/lines/{line_id}/discard")
async def discard(line_id: str, request: Request):
    """Batalkan baris yang gagal diproses (langkah yang sempat terjadi dibalik)."""
    user = await _require(request, so.SCAN_ROLES, "warehouse.manage", "hanya peran gudang/packing")
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — badan kosong boleh
        body = {}
    try:
        out = await so.discard_failed_line(get_db(), line_id, user=user, reason=(body or {}).get("reason") or "",
                                           may_void_others=_can_supervise(user))
    except so.ScanOutError as e:
        raise _err(e)
    ln = out.get("line") or {}
    await log_activity(user["id"], user.get("name", ""), "discard", "wh.scan_out",
                       f"{ln.get('sheet_number')} {ln.get('sku')} ×{ln.get('qty')} (scan gagal dibatalkan)")
    return serialize_doc(out)


@router.post("/sheets/{sheet_id}/close")
async def close(sheet_id: str, request: Request):
    user = await _require(request, so.SUPERVISE_ROLES, "warehouse.approve",
                          "Tutup Hari hanya untuk SPV Packing / Admin Gudang / Supervisor")
    db = get_db()
    try:
        out = await so.close_sheet(db, sheet_id, user=user)
    except so.ScanOutError as e:
        raise _err(e)
    sh = out.get("sheet") or {}
    await log_activity(user["id"], user.get("name", ""), "close", "wh.scan_out",
                       f"{sh.get('number')} je={(out.get('je') or {}).get('je_number')}")
    return serialize_doc(out)


@router.get("/sheets")
async def list_sheets(request: Request, date: Optional[str] = None, location_id: Optional[str] = None,
                      status: Optional[str] = None, limit: int = 100):
    await require_auth(request)
    db = get_db()
    q: dict = {}
    if date:
        q["date"] = date
    if location_id:
        q["location_id"] = location_id
    if status:
        q["status"] = status
    rows = await db[so.SHEETS].find(q, {"_id": 0}).sort([("date", -1), ("seq", -1)]).to_list(max(1, min(limit, 500)))
    return serialize_doc(rows)


@router.get("/report")
async def report(request: Request, date: Optional[str] = None, location_id: Optional[str] = None):
    await require_auth(request)
    try:
        out = await so.daily_report(get_db(), day=date, location_id=location_id or None)
    except ValueError:
        raise HTTPException(400, "Tanggal harus berformat YYYY-MM-DD.")
    return serialize_doc(out)


@router.get("/control")
async def control(request: Request, date: Optional[str] = None, days: Optional[int] = None,
                  sku_date: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    try:
        out = await so.control(db, end_day=date, days=days, sku_day=sku_date)
    except ValueError:
        raise HTTPException(400, "Tanggal harus berformat YYYY-MM-DD.")
    docs = await db[so.CONTROLS].find({"date": {"$in": [r["date"] for r in out["rows"]]}}, {"_id": 0}).to_list(100)
    by_day = {d["date"]: d for d in docs}
    for r in out["rows"]:
        d = by_day.get(r["date"]) or {}
        r["review"] = {k: d.get(k) for k in ("status", "reviewed_by", "reviewed_at", "review_note")} if d else None
    return serialize_doc(out)


@router.post("/control/{day}/review")
async def control_review(day: str, request: Request):
    user = await _require(request, so.SUPERVISE_ROLES, "warehouse.approve",
                          "hanya SPV/Admin Gudang yang menandai selisih kontrol")
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    try:
        out = await so.review_control(get_db(), day, user=user, note=(body or {}).get("note") or "")
    except ValueError:
        raise HTTPException(400, "Tanggal harus berformat YYYY-MM-DD.")
    return serialize_doc(out)


@router.get("/settings")
async def get_settings(request: Request):
    await require_auth(request)
    return await so.get_settings(get_db())


@router.put("/settings")
async def put_settings(request: Request):
    user = await _require(request, so.SUPERVISE_ROLES, "warehouse.approve", "hanya SPV/Admin Gudang")
    try:
        return await so.save_settings(get_db(), await request.json(), user)
    except so.ScanOutError as e:
        raise _err(e)


@router.get("/langkah2")
async def langkah2(request: Request):
    await require_auth(request)
    return await so.langkah2_status(get_db())
