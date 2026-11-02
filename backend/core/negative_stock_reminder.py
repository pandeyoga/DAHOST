"""core/negative_stock_reminder.py — PENGINGAT HARIAN stok minus (2026-11-02).

Keputusan owner No.29(a): "Stok Boleh Minus" tetap ON, tetapi minus dijadikan
PENGINGAT yang tidak memblokir. Sebelum ini 0 notifikasi: tab "Stok Minus" (Gudang →
Stok & Akurasi) hanya pasif, harus dibuka sendiri, sehingga minus menumpuk tanpa
pemilik dan setiap GR berikutnya menggeser rata-rata HPP.

Modul ini TIDAK mengubah aturan stok apa pun. Ia hanya:
  * membaca baris `rahaza_material_stock` ber-qty < 0;
  * mengirim SATU notifikasi per hari (dedup `source_ref = negstock:<tanggal WIB>`) ke
    peran gudang yang nyata — `PORTAL_ACCESS["warehouse"]` (routes/shared.py);
  * menautkan notifikasi ke tab "Stok Minus" (`#wms-stock-hub=negative`).
Dijadwalkan harian lewat `register_scheduler_job()` (dipanggil saat modul rute stok
dimuat) — tanpa mengubah berkas penjadwal/notifikasi milik paket lain.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SUBTYPE = "negative_stock_daily"
WAREHOUSE_PORTAL = "warehouse"
LINK_MODULE = "wms-stock-hub"     # portalNav.js: Gudang → "Stok & Akurasi"
LINK_TAB = "negative"             # hubs/WMSStockHub.jsx: tab "Stok Minus"
MAX_LINES = 15
JOB_ID = "daily_negative_stock_reminder"


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def dedup_ref(day: str) -> str:
    return f"negstock:{day}"


def build_digest(rows: list[dict], *, max_lines: int = MAX_LINES) -> dict:
    """Ringkasan baris minus (fungsi murni). `rows` = {code, name, unit, location_code, qty, unit_cost}."""
    neg = [r for r in rows if _f(r.get("qty")) < 0]
    neg.sort(key=lambda r: _f(r.get("qty")) * max(_f(r.get("unit_cost")), 1e-9))
    total_value = round(sum(abs(_f(r.get("qty"))) * _f(r.get("unit_cost")) for r in neg), 2)
    materials = len({r.get("material_id") or r.get("code") for r in neg})
    lines = []
    for r in neg[:max_lines]:
        val = abs(_f(r.get("qty"))) * _f(r.get("unit_cost"))
        lines.append(f"• {r.get('code') or '-'} {r.get('name') or ''} @ {r.get('location_code') or '-'}: "
                     f"{_f(r.get('qty')):g} {r.get('unit') or ''}"
                     + (f" (≈ Rp {val:,.0f})" if val > 0 else " (HPP 0)"))
    more = len(neg) - len(lines)
    body = (f"{len(neg)} baris stok minus ({materials} material), nilai ≈ Rp {total_value:,.0f}. "
            "Stok tetap boleh minus (tidak diblokir) — bereskan dengan mencatat penerimaan barang "
            "atau opname lokasi tersebut.\n" + "\n".join(lines)
            + (f"\n… dan {more} baris lain — buka Gudang → Stok & Akurasi → Stok Minus." if more > 0 else ""))
    return {"count": len(neg), "materials": materials, "total_value": total_value,
            "lines": lines, "body": body}


async def warehouse_roles(db) -> list[str]:
    """Peran penerima = peran portal gudang di SSOT `routes/shared.PORTAL_ACCESS`.

    Sengaja TIDAK ikut `roles.portals`: di seed go-live peran seperti `hr` & `operator_cuting`
    juga diberi portal gudang (akses baca), padahal bukan penanggung jawab stok.
    """
    from routes.shared import PORTAL_ACCESS
    return sorted({str(r).lower() for r in PORTAL_ACCESS.get(WAREHOUSE_PORTAL, []) if r})


async def negative_rows(db) -> list[dict]:
    """Baris stok ber-qty < 0 lengkap dengan identitas barang & lokasi."""
    from core import location_resolver
    from core.accessory_valuation import resolve_unit_cost
    stocks = await db.rahaza_material_stock.find({"qty": {"$lt": 0}}, {"_id": 0}).to_list(5000)
    if not stocks:
        return []
    m_ids = list({s.get("material_id") for s in stocks if s.get("material_id")})
    mats = {m["id"]: m async for m in db.rahaza_materials.find({"id": {"$in": m_ids}}, {"_id": 0})}
    l_map = await location_resolver.build_display_map(db, [s.get("location_id") for s in stocks])
    out = []
    for s in stocks:
        m = mats.get(s.get("material_id")) or {}
        loc = l_map.get(s.get("location_id")) or {}
        out.append({
            "material_id": s.get("material_id"), "code": m.get("code") or s.get("material_code"),
            "name": m.get("name") or s.get("material_name") or "", "unit": m.get("unit") or s.get("unit") or "",
            "location_id": s.get("location_id"),
            "location_code": loc.get("code") or s.get("location_code") or "",
            "qty": _f(s.get("qty")), "unit_cost": _f(resolve_unit_cost(m)) if m else 0.0,
        })
    return out


async def send_daily_reminder(db, *, day: str | None = None, force: bool = False) -> dict:
    """Kirim pengingat harian. Idempoten per tanggal WIB (kecuali `force`)."""
    from utils.notif_unified import notif_insert
    from utils.waktu import today_wib
    day = day or today_wib().isoformat()
    ref = dedup_ref(day)
    if not force and await db.notifications.find_one({"source_ref": ref, "subtype": SUBTYPE}, {"_id": 0, "id": 1}):
        return {"date": day, "sent": False, "skipped": "sudah dikirim hari ini"}
    rows = await negative_rows(db)
    digest = build_digest(rows)
    if digest["count"] == 0:
        return {"date": day, "sent": False, "skipped": "tidak ada stok minus", "count": 0}
    roles = await warehouse_roles(db)
    nid = await notif_insert(
        db, type="rahaza", subtype=SUBTYPE, severity="warning",
        title=f"Pengingat stok minus: {digest['count']} baris",
        body=digest["body"], target_roles=roles,
        source_type="rahaza_material_stock", source_url=f"#{LINK_MODULE}={LINK_TAB}", source_ref=ref,
        meta={"link_module": LINK_MODULE, "hub_tab": LINK_TAB, "date": day,
              "count": digest["count"], "materials": digest["materials"],
              "total_value": digest["total_value"], "dedup_key": ref})
    return {"date": day, "sent": True, "notification_id": nid, "roles": roles,
            "count": digest["count"], "materials": digest["materials"],
            "total_value": digest["total_value"]}


async def job_daily_negative_stock_reminder() -> dict:
    """Entry point penjadwal (07:15 WIB). Mencatat run di `dewi_scheduler_runs`."""
    from database import get_db
    db = get_db()
    started = datetime.now(timezone.utc)
    res = await db.dewi_scheduler_runs.insert_one({"job_id": JOB_ID, "started_at": started, "status": "running"})
    try:
        out = await send_daily_reminder(db)
        await db.dewi_scheduler_runs.update_one({"_id": res.inserted_id}, {"$set": {
            "status": "success", "finished_at": datetime.now(timezone.utc), **{k: out.get(k) for k in
                                                                              ("date", "sent", "skipped", "count")}}})
        return out
    except Exception as e:  # noqa: BLE001
        logger.exception("[scheduler] %s gagal", JOB_ID)
        await db.dewi_scheduler_runs.update_one({"_id": res.inserted_id}, {"$set": {
            "status": "failed", "finished_at": datetime.now(timezone.utc), "error": str(e)}})
        raise


def register_scheduler_job() -> bool:
    """Daftarkan job harian ke registri penjadwal (idempoten, tidak menimpa entri yang ada).
    Harus dipanggil sebelum `start_scheduler()` (startup) — dipanggil saat rute stok dimuat."""
    try:
        from utils.scheduler import JOB_REGISTRY
    except Exception:  # noqa: BLE001 — penjadwal opsional (mis. uji unit tanpa apscheduler)
        logger.debug("utils.scheduler tidak tersedia — pengingat stok minus tidak dijadwalkan", exc_info=True)
        return False
    JOB_REGISTRY.setdefault(JOB_ID, {
        "fn": job_daily_negative_stock_reminder,
        "description": ("Pengingat harian stok minus (No.29a): satu notifikasi ke peran gudang berisi "
                        "daftar material ber-stok minus + tautan ke tab Stok Minus. Tidak memblokir."),
        "cron": {"hour": 7, "minute": 15},
        "cron_label": "Setiap hari pukul 07:15 WIB",
    })
    return True
