"""
WMS — Audit Trail for Stock Adjustments
Menampilkan history semua adjustment stok (saat ini: opname_adjustment)
dengan filter by operator, posisi, rak, gedung, dan tanggal.

Sumber data: rahaza_fg_movements where source in (opname_adjustment, ...)
            + (2026-11-02) sesi opname mesin baru K9 (`wh_opname3_sessions`, engine='k9', status
              'approved'): satu baris per material yang selisih (`result.lines`). Selisih K9 dihitung per
              LOKASI (bukan per bin), jadi baris ini tidak ikut saringan posisi/rak/gedung.

Routes:
  GET  /api/wms/audit/adjustments       — list + pagination + filters
  GET  /api/wms/audit/adjustments/stats — ringkasan statistik
  GET  /api/wms/audit/adjustments/export-csv — download CSV
"""

import io
import csv
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from database import get_db
from auth import require_auth, serialize_doc, verify_download_token

router = APIRouter(prefix="/api/wms/audit", tags=["wms-audit"])


# Sources that count as "stock adjustments" for the audit trail
ADJUSTMENT_SOURCES = ["opname_adjustment"]
K9_SOURCE = "opname_k9"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _aware(dt):
    if isinstance(dt, str):
        dt = _parse_iso(dt)
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def k9_adjustment_rows(sess: dict) -> list:
    """Baris audit dari satu sesi opname K9 yang sudah disetujui (fungsi murni, 2026-11-02)."""
    out = []
    lines = ((sess.get("result") or {}).get("lines")) or []
    for ln in lines:
        var = float(ln.get("variance_qty") or 0)
        if not var:
            continue
        out.append({
            "source": K9_SOURCE, "engine": "k9", "session_id": sess.get("id"),
            "session_ref": sess.get("session_no"), "timestamp": sess.get("approved_at"),
            "created_by": sess.get("approved_by_name") or sess.get("approved_by") or "",
            "position_id": None, "position_barcode": None,
            "location_code": sess.get("location_code"), "fg_code": ln.get("material_code"),
            "material_code": ln.get("material_code"), "material_name": ln.get("material_name"),
            "direction": "adjust_in" if var > 0 else "adjust_out", "qty": round(abs(var), 4),
            "value": ln.get("variance_value"), "reason": ln.get("reason") or "",
            "notes": (f"Opname {sess.get('session_no')} · {sess.get('location_code') or ''}: sistem "
                      f"{ln.get('system_qty')} → hitung {ln.get('counted_qty')}"),
        })
    return out


async def _k9_rows(db, *, operator=None, position_barcode=None, rack_id=None, building_id=None,
                   date_from=None, date_to=None, direction=None) -> list:
    """Baris audit sesi opname K9 dengan saringan yang sama dengan sumber lama."""
    if position_barcode or rack_id or building_id:
        return []                                  # selisih K9 per lokasi — tidak punya posisi bin
    q: dict = {"engine": "k9", "status": "approved"}
    df, dt = _parse_iso(date_from), _parse_iso(date_to)
    if df or dt:
        q["approved_at"] = {**({"$gte": df} if df else {}), **({"$lte": dt} if dt else {})}
    sessions = await db.wh_opname3_sessions.find(q, {"_id": 0, "snapshot": 0, "lines": 0}) \
        .sort("approved_at", -1).to_list(500)
    rows = [r for s in sessions for r in k9_adjustment_rows(s)]
    if operator:
        import re as _re
        rx = _re.compile(_re.escape(operator), _re.I)
        rows = [r for r in rows if rx.search(r.get("created_by") or "")]
    if direction in ("adjust_in", "adjust_out"):
        rows = [r for r in rows if r["direction"] == direction]
    return rows


def _sort_desc(rows: list) -> list:
    return sorted(rows, key=lambda r: _aware(r.get("timestamp")) or _EPOCH, reverse=True)


async def _auth_or_token(request: Request, token: Optional[str] = None):
    if token:
        user = verify_download_token(token)
        if user:
            return user
    return await require_auth(request)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept "YYYY-MM-DD" or full ISO
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


async def _build_query(db, *,
    operator: Optional[str] = None,
    position_barcode: Optional[str] = None,
    rack_id: Optional[str] = None,
    building_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    direction: Optional[str] = None,
) -> dict:
    q: dict = {"source": {"$in": ADJUSTMENT_SOURCES}}
    if operator:
        q["created_by"] = {"$regex": operator, "$options": "i"}
    if position_barcode:
        q["position_barcode"] = {"$regex": position_barcode, "$options": "i"}
    if direction in ("adjust_in", "adjust_out"):
        q["direction"] = direction

    # Scope by rack/building → resolve to position_ids first
    if rack_id or building_id:
        pos_q = {}
        if rack_id:
            pos_q["rack_id"] = rack_id
        if building_id:
            pos_q["building_id"] = building_id
        pos_ids = await db.wh_positions.distinct("id", pos_q)
        q["position_id"] = {"$in": pos_ids or ["__none__"]}

    # Date range
    df = _parse_iso(date_from)
    dt = _parse_iso(date_to)
    if df or dt:
        ts_q = {}
        if df:
            ts_q["$gte"] = df
        if dt:
            ts_q["$lte"] = dt
        q["timestamp"] = ts_q
    return q


@router.get("/adjustments")
async def list_adjustments(
    request: Request,
    operator: Optional[str] = None,
    position_barcode: Optional[str] = None,
    rack_id: Optional[str] = None,
    building_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = Query(100, le=500),
    skip: int = 0,
):
    """
    Daftar semua adjustment stok dengan filter.
    Response: {items: [...], total, limit, skip}
    """
    await require_auth(request)
    db = get_db()
    q = await _build_query(
        db, operator=operator, position_barcode=position_barcode,
        rack_id=rack_id, building_id=building_id,
        date_from=date_from, date_to=date_to, direction=direction,
    )
    k9 = await _k9_rows(db, operator=operator, position_barcode=position_barcode, rack_id=rack_id,
                        building_id=building_id, date_from=date_from, date_to=date_to, direction=direction)
    total = await db.rahaza_fg_movements.count_documents(q) + len(k9)
    legacy = await db.rahaza_fg_movements.find(q, {"_id": 0})\
        .sort("timestamp", -1).limit(skip + limit).to_list(skip + limit)
    rows = _sort_desc(legacy + k9)[skip:skip + limit]

    # Enrich position path (building/zone/rack)
    pos_ids = [r.get("position_id") for r in rows if r.get("position_id")]
    pos_map = {}
    if pos_ids:
        async for p in db.wh_positions.find({"id": {"$in": pos_ids}}, {"_id": 0}):
            pos_map[p["id"]] = p
    for r in rows:
        p = pos_map.get(r.get("position_id"))
        if p:
            r["position_label"] = p.get("label")
            r["rack_code"] = p.get("rack_code")
            r["zone_code"] = p.get("zone_code")
            r["building_code"] = p.get("building_code")

    return serialize_doc({
        "items": rows,
        "total": total, "limit": limit, "skip": skip,
    })


@router.get("/adjustments/stats")
async def adjustment_stats(
    request: Request,
    operator: Optional[str] = None,
    position_barcode: Optional[str] = None,
    rack_id: Optional[str] = None,
    building_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """
    Ringkasan: total adjustment, total surplus/shortage qty,
    breakdown by operator, by direction.
    """
    await require_auth(request)
    db = get_db()
    q = await _build_query(
        db, operator=operator, position_barcode=position_barcode,
        rack_id=rack_id, building_id=building_id,
        date_from=date_from, date_to=date_to,
    )
    # Overall stats
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$direction",
            "count": {"$sum": 1},
            "total_qty": {"$sum": "$qty"},
        }}
    ]
    dir_rows = await db.rahaza_fg_movements.aggregate(pipeline).to_list(500)
    surplus_count = 0
    surplus_qty = 0.0
    shortage_count = 0
    shortage_qty = 0.0
    for r in dir_rows:
        if r["_id"] == "adjust_in":
            surplus_count = r["count"]
            surplus_qty = round(r["total_qty"], 4)
        elif r["_id"] == "adjust_out":
            shortage_count = r["count"]
            shortage_qty = round(r["total_qty"], 4)

    # By operator (top 10)
    op_pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$created_by",
            "count": {"$sum": 1},
            "surplus_qty": {"$sum": {"$cond": [{"$eq": ["$direction", "adjust_in"]}, "$qty", 0]}},
            "shortage_qty": {"$sum": {"$cond": [{"$eq": ["$direction", "adjust_out"]}, "$qty", 0]}},
            "last_activity": {"$max": "$timestamp"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    by_operator = await db.rahaza_fg_movements.aggregate(op_pipeline).to_list(500)
    by_operator = [
        {
            "operator": r["_id"] or "unknown",
            "count": r["count"],
            "surplus_qty": round(r.get("surplus_qty", 0), 4),
            "shortage_qty": round(r.get("shortage_qty", 0), 4),
            "net_qty": round(r.get("surplus_qty", 0) - r.get("shortage_qty", 0), 4),
            "last_activity": r.get("last_activity").isoformat() if r.get("last_activity") else None,
        }
        for r in by_operator
    ]

    # By position (top 10 hotspots)
    pos_pipeline = [
        {"$match": q},
        {"$group": {
            "_id": "$position_barcode",
            "count": {"$sum": 1},
            "total_net": {"$sum": {"$cond": [{"$eq": ["$direction", "adjust_in"]}, "$qty", {"$multiply": ["$qty", -1]}]}},
        }},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    by_position = await db.rahaza_fg_movements.aggregate(pos_pipeline).to_list(500)
    by_position = [
        {"position_barcode": r["_id"], "count": r["count"], "net_qty": round(r.get("total_net", 0), 4)}
        for r in by_position
    ]

    # 2026-11-02: + selisih sesi opname K9 (per lokasi)
    k9 = await _k9_rows(db, operator=operator, position_barcode=position_barcode, rack_id=rack_id,
                        building_id=building_id, date_from=date_from, date_to=date_to)
    ops = {o["operator"]: o for o in by_operator}
    for r in k9:
        q_ = float(r["qty"] or 0)
        if r["direction"] == "adjust_in":
            surplus_count += 1
            surplus_qty = round(surplus_qty + q_, 4)
        else:
            shortage_count += 1
            shortage_qty = round(shortage_qty + q_, 4)
        o = ops.setdefault(r["created_by"] or "unknown", {
            "operator": r["created_by"] or "unknown", "count": 0, "surplus_qty": 0.0, "shortage_qty": 0.0,
            "net_qty": 0.0, "last_activity": None})
        o["count"] += 1
        o["surplus_qty" if r["direction"] == "adjust_in" else "shortage_qty"] = round(
            o["surplus_qty" if r["direction"] == "adjust_in" else "shortage_qty"] + q_, 4)
        o["net_qty"] = round(o["surplus_qty"] - o["shortage_qty"], 4)
        ts = _aware(r.get("timestamp"))
        if ts and (not o["last_activity"] or ts.isoformat() > str(o["last_activity"])):
            o["last_activity"] = ts.isoformat()
    by_operator = sorted(ops.values(), key=lambda o: -o["count"])[:10]

    total = surplus_count + shortage_count
    return serialize_doc({
        "total_adjustments": total,
        "surplus_count": surplus_count, "surplus_qty": surplus_qty,
        "shortage_count": shortage_count, "shortage_qty": shortage_qty,
        "net_qty": round(surplus_qty - shortage_qty, 4),
        "by_operator": by_operator,
        "by_position_hotspots": by_position,
    })


@router.get("/adjustments/export-csv")
async def export_adjustments_csv(
    request: Request,
    token: Optional[str] = Query(None),
    operator: Optional[str] = None,
    position_barcode: Optional[str] = None,
    rack_id: Optional[str] = None,
    building_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    direction: Optional[str] = None,
):
    """Download CSV for compliance / audit."""
    await _auth_or_token(request, token)
    db = get_db()
    q = await _build_query(
        db, operator=operator, position_barcode=position_barcode,
        rack_id=rack_id, building_id=building_id,
        date_from=date_from, date_to=date_to, direction=direction,
    )
    rows = await db.rahaza_fg_movements.find(q, {"_id": 0}).sort("timestamp", -1).to_list(500)
    rows = _sort_desc(rows + await _k9_rows(
        db, operator=operator, position_barcode=position_barcode, rack_id=rack_id, building_id=building_id,
        date_from=date_from, date_to=date_to, direction=direction))[:1000]

    # Enrich positions
    pos_ids = [r.get("position_id") for r in rows if r.get("position_id")]
    pos_map = {}
    if pos_ids:
        async for p in db.wh_positions.find({"id": {"$in": pos_ids}}, {"_id": 0}):
            pos_map[p["id"]] = p

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Timestamp", "Session Ref", "Operator", "Building", "Zone", "Rack",
        "Position Barcode", "Position Label", "Material Code", "Direction",
        "Qty", "Notes",
    ])
    for r in rows:
        p = pos_map.get(r.get("position_id"), {})
        writer.writerow([
            _aware(r.get("timestamp")).isoformat() if _aware(r.get("timestamp")) else "",
            r.get("session_ref", ""),
            r.get("created_by", ""),
            p.get("building_code", "") or r.get("location_code") or "",
            p.get("zone_code", ""),
            p.get("rack_code", ""),
            r.get("position_barcode", ""),
            p.get("label", ""),
            r.get("fg_code", ""),
            r.get("direction", ""),
            r.get("qty", 0),
            r.get("notes", ""),
        ])

    buf.seek(0)
    filename = f"wms_audit_adjustments_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _uid_for_audit():
    import uuid
    return uuid.uuid4()


# ══════════════════════════════════════════════════════════════════════════════
# AI ROOT-CAUSE ANALYSIS — untuk hotspot posisi dengan adjustment berulang
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/hotspot/{position_barcode}/rca")
async def hotspot_rca(position_barcode: str, request: Request):
    """
    AI Root-Cause Analysis untuk posisi hotspot.
    Ambil N adjustment terakhir → Claude analisis pola → rekomendasi action item.
    2026-11-02: kunci & model dikelola terpusat oleh services.ai (bukan env EMERGENT).
    """
    from services.ai import AIError, ai_http_error, ai_text, require_ai
    user = await require_auth(request)
    db = get_db()

    # Ambil last 30 adjustments untuk posisi ini
    rows = await db.rahaza_fg_movements.find(
        {"source": "opname_adjustment", "position_barcode": position_barcode},
        {"_id": 0}
    ).sort("timestamp", -1).limit(30).to_list(500)

    if len(rows) < 3:
        raise HTTPException(400, f"Posisi {position_barcode} belum punya cukup data (minimal 3 adjustment, ada {len(rows)}).")

    # Enrich position info — 2026-11-02: lewat resolver SSOT (kode bin lama/alias tetap dikenali)
    from core.scan_resolver import position_by_barcode
    pos = await position_by_barcode(db, position_barcode)
    pos_info = {
        "barcode": position_barcode,
        "label": pos.get("label") if pos else "",
        "building": pos.get("building_code") if pos else "",
        "zone": pos.get("zone_code") if pos else "",
        "rack": pos.get("rack_code") if pos else "",
        "current_material": pos.get("material_name") if pos else "",
        "current_qty": pos.get("qty") if pos else 0,
    }

    # Summarize data for LLM
    surplus_count = sum(1 for r in rows if r.get("direction") == "adjust_in")
    shortage_count = sum(1 for r in rows if r.get("direction") == "adjust_out")
    surplus_qty = sum(r.get("qty", 0) for r in rows if r.get("direction") == "adjust_in")
    shortage_qty = sum(r.get("qty", 0) for r in rows if r.get("direction") == "adjust_out")
    operators = list({r.get("created_by", "unknown") for r in rows})

    # Build timeline (last 10 to keep prompt concise)
    timeline = []
    for r in rows[:10]:
        timeline.append({
            "waktu": r.get("timestamp").isoformat() if r.get("timestamp") else "",
            "operator": r.get("created_by", ""),
            "arah": "Surplus" if r.get("direction") == "adjust_in" else "Shortage",
            "qty": r.get("qty"),
            "catatan": r.get("notes", ""),
            "session_ref": r.get("session_ref", ""),
        })

    # 2026-11-02: gerbang tunggal services.ai (dulu 503 "EMERGENT_LLM_KEY belum dikonfigurasi.").
    await require_ai("wms-audit-rca", user_id=user.get("id"), db=db, tier="standard")

    prompt = f"""Kamu adalah analis WMS (Warehouse Management System) yang sangat berpengalaman.
Analisis pola adjustment stok di posisi berikut dan berikan root-cause analysis + rekomendasi action.

POSISI:
- Barcode: {pos_info['barcode']}
- Lokasi: {pos_info['building']} / {pos_info['zone']} / {pos_info['rack']}
- Label rak: {pos_info['label']}
- Material saat ini: {pos_info['current_material']} ({pos_info['current_qty']} unit)

DATA {len(rows)} ADJUSTMENT TERAKHIR:
- Total Surplus: {surplus_count}x dengan qty {surplus_qty:.2f}
- Total Shortage: {shortage_count}x dengan qty {shortage_qty:.2f}
- Net discrepancy: {(surplus_qty - shortage_qty):+.2f}
- Operator terlibat: {', '.join(operators)}

TIMELINE 10 ADJUSTMENT TERAKHIR:
{chr(10).join([f"  {i+1}. {t['waktu'][:19]} · {t['operator']} · {t['arah']} {t['qty']} · {t['catatan'][:80]}" for i, t in enumerate(timeline)])}

TUGAS:
Berikan analisis Root-Cause (RCA) dengan format JSON berikut:
{{
  "root_cause_hypothesis": "hipotesis penyebab utama dalam 1 kalimat (pilih salah satu: 'shrinkage/kehilangan', 'miscounting operator', 'mis-placement barang', 'systematic mislabel', 'fluktuasi normal')",
  "confidence": "tinggi|sedang|rendah",
  "reasoning": "penjelasan singkat 2-3 kalimat kenapa hipotesis ini paling mungkin",
  "risk_level": "tinggi|sedang|rendah",
  "recommended_actions": [
    "aksi 1 dalam bahasa Indonesia (imperative)",
    "aksi 2",
    "aksi 3"
  ]
}}

Balas HANYA dengan JSON valid tanpa markdown code fence. Gunakan Bahasa Indonesia."""

    try:
        resp = await ai_text(
            "wms-audit-rca",
            "Kamu adalah analis WMS yang memberikan RCA singkat, akurat, actionable dalam format JSON.",
            prompt, tier="standard", user_id=user.get("id"),
        )
        raw = resp if isinstance(resp, str) else str(resp)
        # Strip any markdown fences just in case
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]
        import json as _json
        try:
            analysis = _json.loads(raw.strip())
        except Exception:
            # 2026-11-02: jangan mengarang "risiko sedang" bila jawaban tak terbaca.
            analysis = {
                "root_cause_hypothesis": "Tidak terdeteksi — jawaban AI tidak valid JSON",
                "confidence": "tidak dapat dinilai",
                "reasoning": "Analisis tidak dapat dinilai karena format jawaban AI tidak sesuai.",
                "risk_level": "tidak dapat dinilai",
                "recommended_actions": ["Jalankan ulang analisa AI", "Review manual riwayat adjustment"],
            }
    except AIError as e:
        raise ai_http_error(e)

    # Log audit
    await db.wh_rca_audit.insert_one({
        "id": str(_uid_for_audit()),
        "position_barcode": position_barcode,
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc),
    })

    return {
        "position": pos_info,
        "data_points": len(rows),
        "stats": {
            "surplus_count": surplus_count, "shortage_count": shortage_count,
            "surplus_qty": round(surplus_qty, 4), "shortage_qty": round(shortage_qty, 4),
            "net_qty": round(surplus_qty - shortage_qty, 4),
            "operators": operators,
        },
        "analysis": analysis,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _uid_for_audit():
    import uuid
    return uuid.uuid4()
