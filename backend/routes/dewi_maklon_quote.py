"""
Session 18 — P2-19: AI Quote Generator (Maklon)

Generate quotation/penawaran maklon (RFQ) berdasarkan input client requirement
menggunakan Claude (Anthropic) lewat ai_cost_tracker. Hasil:
- Estimated unit cost (HPP)
- Recommended margin
- Lead time estimasi
- Quote summary text (untuk dikirim ke klien)
- Line items breakdown (material, labor, overhead, margin)

Endpoints (prefix: /api/maklon/ai-quote)
- POST   /generate                — generate quote from input
- GET    /history                 — list past quotes (auth, optional client_id filter)
- GET    /{id}                    — fetch single quote
- POST   /{id}/accept             — mark quote as accepted
- DELETE /{id}                    — soft-delete quote
"""
import re
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Query, Depends
from routes.production_rbac import deny_external_dep
from pydantic import BaseModel, Field
from database import get_db
from auth import require_auth
from core.authz import only  # T-01 2.3
from core.roles import MAKLON_ROLES  # T-01 2.3

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/maklon/ai-quote", tags=["maklon-ai-quote"], dependencies=[Depends(deny_external_dep)])
QUOTE_COL = "rahaza_maklon_quotes"
# 2026-11-02 (No.60): tuple ("openai","gpt-5.1") dihapus — dulu diteruskan apa adanya
# ke Anthropic sehingga estimasi AI tidak pernah berhasil. Pakai tier Claude.
LLM_TIER = "standard"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _serialize(obj):
    if isinstance(obj, dict):
        obj.pop("_id", None)
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


class QuoteRequestIn(BaseModel):
    product_name: str
    category: Optional[str] = None  # e.g. kaos, kemeja, hijab
    quantity: int = Field(..., gt=0)
    target_market: Optional[str] = None  # e.g. premium, mid, mass
    target_unit_price: Optional[float] = Field(default=None, ge=0)  # target harga jual klien (opsional)
    materials: Optional[str] = None  # deskripsi material
    finishing: Optional[str] = None  # printing, embroidery, dll
    required_lead_time_days: Optional[int] = None
    client_name: Optional[str] = None
    client_id: Optional[str] = None
    additional_notes: Optional[str] = None
    target_margin_pct: Optional[float] = 25  # default 25% (atas harga jual — core.margin)
    # 2026-11-06 (Tahap 2): siapa yang menyediakan bahan utama. Bawaan maklon = klien
    # (sama dengan `_maklon_adapter.fabric_provided_by`); bahan klien BUKAN biaya DA.
    fabric_provided_by: Optional[str] = "client"   # client | cv_da


def client_supplies_material(payload) -> bool:
    return (getattr(payload, "fabric_provided_by", None) or "client").strip().lower() != "cv_da"


def apply_owner_cost_rules(result: dict, payload) -> dict:
    """2026-11-06 (Tahap 2, keputusan owner) — dipasang pada hasil heuristik MAUPUN AI:
      * bahan yang disediakan klien tidak dihitung sebagai biaya (material = 0);
      * overhead pabrik tidak masuk HPP (overhead = 0);
      * harga = HPP ÷ (1 − margin) — margin atas harga jual (`core.margin`), bukan markup HPP."""
    from core.margin import margin_pct, price_for_margin
    out = dict(result or {})
    bd = {k: float(v or 0) for k, v in (out.get("hpp_breakdown") or {}).items()
          if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit()}
    excluded = {}
    if client_supplies_material(payload) and bd.get("material"):
        excluded["material_client"] = bd["material"]
        bd["material"] = 0.0
    if bd.get("overhead"):
        excluded["overhead"] = bd["overhead"]
        bd["overhead"] = 0.0
    hpp = round(sum(bd.values()), 2)
    target = float(getattr(payload, "target_margin_pct", None) or out.get("margin_pct") or 25)
    unit_price = price_for_margin(hpp, target) if hpp > 0 else float(out.get("estimated_unit_price") or 0)
    qty = int(getattr(payload, "quantity", 0) or 0)
    out.update({
        "hpp_breakdown": bd, "hpp_per_pcs": hpp, "excluded_from_hpp": excluded,
        "estimated_unit_price": round(unit_price), "estimated_total": round(unit_price) * qty,
        "margin_pct": margin_pct(unit_price, hpp, nd=1) if hpp > 0 else target,
        "margin_amount": round(unit_price - hpp) if hpp > 0 else out.get("margin_amount"),
        "material_supplied_by": "client" if client_supplies_material(payload) else "cv_da",
        "cost_rules": ("HPP = bahan milik DA + upah CMT/jahit + finishing. Bahan dari klien dan overhead "
                       "pabrik tidak dihitung. Margin dihitung atas harga jual."),
    })
    return out


def _extract_json_block(text: str):
    """Find first JSON object in text robustly."""
    if not text:
        return None
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
    # Try to find json block in markdown fence
    fenced = re.search(r"```(?:json)?\s*([\{\[].*?[\}\]])\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
    # Try greedy brace match
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
    return None


def _heuristic_quote(payload: QuoteRequestIn) -> dict:
    """Fallback heuristic quote if LLM unavailable."""
    category = (payload.category or "general").lower()
    qty = payload.quantity
    base_material = {
        "kaos": 28000,
        "kemeja": 55000,
        "hijab": 18000,
        "celana": 65000,
        "outerwear": 95000,
        "general": 45000,
    }.get(category, 45000)

    finishing_addon = 0
    if payload.finishing:
        f = payload.finishing.lower()
        if "embroidery" in f or "bordir" in f:
            finishing_addon += 8000
        if "print" in f or "sablon" in f:
            finishing_addon += 5000
    labor = int(base_material * 0.45)          # proksi upah CMT/jahit per pcs
    margin_pct = float(payload.target_margin_pct or 25)
    # 2026-11-06 (Tahap 2): bahan klien bukan biaya DA; overhead pabrik tidak masuk HPP;
    # harga = HPP ÷ (1 − margin) (margin atas harga jual, `core.margin`) — dulu HPP × (1 + margin).
    material = 0 if client_supplies_material(payload) else base_material
    overhead = 0

    from core import margin as _margin
    from core.margin import price_for_margin
    hpp = material + labor + overhead + finishing_addon
    unit_price = int(round(price_for_margin(hpp, margin_pct)))
    total = unit_price * qty

    # Adjust for volume
    if qty >= 5000:
        unit_price = int(unit_price * 0.92)
        total = unit_price * qty
    elif qty >= 2000:
        unit_price = int(unit_price * 0.96)
        total = unit_price * qty
    margin = unit_price - hpp

    lead_time = max(14, min(60, 14 + qty // 200))

    return {
        "estimated_unit_price": unit_price,
        "estimated_total": total,
        "hpp_breakdown": {
            "material": material,
            "labor": labor,
            "overhead": overhead,
            "finishing": finishing_addon,
        },
        "hpp_per_pcs": hpp,
        "margin_pct": _margin.margin_pct(unit_price, hpp, nd=1) if hpp > 0 else margin_pct,
        "margin_amount": margin,
        "estimated_lead_time_days": lead_time,
        "currency": "IDR",
        "summary": (
            f"Quote heuristik untuk {qty} pcs {payload.product_name}: "
            f"unit price Rp {unit_price:,} (margin {margin_pct:.0f}%), "
            f"total Rp {total:,}, lead time ±{lead_time} hari."
        ),
        "competitiveness": (
            "low" if payload.target_unit_price and unit_price > payload.target_unit_price * 1.15
            else "medium" if payload.target_unit_price and unit_price > payload.target_unit_price
            else "high"
        ) if payload.target_unit_price else "n/a",
        "risks": [],
        "recommendations": [
            "Konfirmasi spesifikasi material detail sebelum produksi",
            "Sample pre-production untuk QC standar",
            "Pembagian batch produksi jika qty > 3000",
        ],
    }


def quote_prompt_body(payload) -> str:
    """Isi permintaan estimasi untuk model — TANPA identitas klien (audit AI 7 Nov 2026).

    Nama klien tidak dibutuhkan untuk menghitung harga, jadi tidak dikirim. Bila nama itu tertulis di isian
    bebas (produk, bahan, catatan), diganti "[KLIEN]"; nomor HP/e-mail/nomor panjang ikut disamarkan."""
    from services.ai.privacy import redact
    names = [getattr(payload, "client_name", None)]

    def bebas(v):
        return redact(v, names, "[KLIEN]") if v else "-"

    return (
        f"Product: {bebas(payload.product_name)}\n"
        f"Category: {bebas(payload.category)}\n"
        f"Quantity: {payload.quantity}\n"
        f"Target market: {bebas(payload.target_market)}\n"
        f"Target unit price (jika ada): {payload.target_unit_price or '-'}\n"
        f"Materials: {bebas(payload.materials)}\n"
        f"Bahan utama disediakan oleh: {'klien' if client_supplies_material(payload) else 'CV. DA'}\n"
        f"Finishing: {bebas(payload.finishing)}\n"
        f"Required lead time: {payload.required_lead_time_days or '-'} hari\n"
        f"Target margin: {payload.target_margin_pct or 25}%\n"
        f"Notes: {bebas(payload.additional_notes)}\n\n"
    )


async def _generate_ai_quote(payload: QuoteRequestIn, user_id: Optional[str] = None) -> dict:
    """Use LLM to enrich the heuristic baseline."""
    base = _heuristic_quote(payload)
    from ai_cost_tracker import ai_available, friendly_error, tracked_llm_call
    if not await ai_available():
        base["source"] = "heuristic"
        return base
    try:
        system = (
            "Anda adalah expert costing & quotation maklon garment Indonesia. "
            "Tugas: hitung quotation lengkap dengan HPP breakdown, margin, lead time, "
            "competitiveness vs market, risks, dan recommendations. "
            "JAWABAN HARUS BERUPA JSON VALID dengan struktur persis:\n"
            "{\n"
            '  "estimated_unit_price": number (IDR),\n'
            '  "estimated_total": number,\n'
            '  "hpp_breakdown": {"material": number, "labor": number, "overhead": number, "finishing": number},\n'
            '  "margin_pct": number,\n'
            '  "margin_amount": number,\n'
            '  "estimated_lead_time_days": number,\n'
            '  "currency": "IDR",\n'
            '  "competitiveness": "low" | "medium" | "high" | "n/a",\n'
            '  "summary": string (1-2 paragraf Bahasa Indonesia),\n'
            '  "risks": string[] (1-4 item),\n'
            '  "recommendations": string[] (3-5 item, actionable)\n'
            "}\n"
            "Pastikan numerik realistis untuk pasar garment Indonesia 2026.\n"
            "ATURAN BIAYA (wajib): bahan yang disediakan klien TIDAK dihitung sebagai biaya "
            "(material = 0 bila bahan dari klien); overhead pabrik tidak masuk HPP (overhead = 0); "
            "labor = upah CMT/jahit per pcs; margin dihitung atas harga jual: "
            "harga = HPP ÷ (1 − margin)."
        )
        user_msg = quote_prompt_body(payload) + (
            f"Heuristik baseline (untuk referensi, silakan koreksi):\n"
            f"{json.dumps(base, indent=2, ensure_ascii=False)}\n\n"
            "Kembalikan JSON akhir saja."
        )

        tracked = await tracked_llm_call(
            feature="maklon-ai-quote",
            user_id=user_id,
            model=LLM_TIER,
            system_message=system,
            user_message=user_msg,
        )

        if tracked.over_budget:
            base["source"] = "heuristic_budget_exceeded"
            base["budget_warning"] = tracked.budget_warning
            return base

        if not tracked.success:
            logger.warning(f"AI quote generation failed: {tracked.error}")
            base["source"] = "heuristic_after_ai_error"
            base["error"] = tracked.error
            return base

        raw = tracked.text
        parsed = _extract_json_block(raw)
        if parsed and isinstance(parsed, dict):
            for k, v in base.items():
                parsed.setdefault(k, v)
            parsed["source"] = "ai"
            parsed["raw_response_excerpt"] = raw[:400]
            parsed["_cost_usd"] = round(tracked.cost_usd, 6)
            parsed["_latency_ms"] = round(tracked.latency_ms, 0)
            return parsed
        base["source"] = "heuristic_after_ai_parse_fail"
        base["ai_raw"] = raw[:400]
        return base
    except Exception as e:
        logger.warning(f"AI quote generation failed: {e}")
        base["source"] = "heuristic_after_ai_error"
        base["error"] = friendly_error("internal")  # 2026-11-02: tanpa exception mentah
        return base


# ═════════════════════════════════════════════════════════════════════
# Endpoints
# ═════════════════════════════════════════════════════════════════════
@router.post("/generate")
async def generate_quote(request: Request, payload: QuoteRequestIn):
    """Generate AI-assisted quote for a maklon client request."""
    await require_auth(request)
    user = request.state.user
    db = get_db()

    result = await _generate_ai_quote(payload, user_id=user.get("id"))
    if result.get("source") == "ai":
        # 2026-11-06 (Tahap 2): angka AI dirapikan dengan aturan biaya owner (bahan klien &
        # overhead bukan biaya, margin atas harga jual) — heuristik sudah mengikutinya.
        result = apply_owner_cost_rules(result, payload)
    record = {
        "id": str(uuid.uuid4()),
        "request": payload.dict(),
        "result": result,
        "status": "draft",
        "created_by": user.get("id"),
        "created_by_name": user.get("name"),
        "created_at": _now_iso(),
    }
    await db[QUOTE_COL].insert_one(record)
    record.pop("_id", None)
    return {"success": True, "data": record}


@router.get("/history")
async def list_quotes(
    request: Request,
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    await require_auth(request)
    db = get_db()
    q: dict = {"status": {"$ne": "deleted"}}
    if client_id:
        q["request.client_id"] = client_id
    if status:
        q["status"] = status
    quotes = await db[QUOTE_COL].find(q).sort("created_at", -1).to_list(length=limit)
    return {"success": True, "data": [_serialize(q) for q in quotes]}


@router.get("/{quote_id}")
async def get_quote(request: Request, quote_id: str):
    await require_auth(request)
    db = get_db()
    q = await db[QUOTE_COL].find_one({"id": quote_id})
    if not q:
        raise HTTPException(404, "Quote not found")
    return {"success": True, "data": _serialize(q)}


@router.post("/{quote_id}/accept")
async def accept_quote(request: Request, quote_id: str):
    await require_auth(request)
    db = get_db()
    res = await db[QUOTE_COL].update_one(
        {"id": quote_id}, {"$set": {"status": "accepted", "accepted_at": _now_iso()}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Quote not found")
    return {"success": True, "message": "Quote ditandai accepted"}


@router.delete("/{quote_id}", dependencies=only(*MAKLON_ROLES, perm="maklon.manage"))  # T-01 2.3
async def delete_quote(request: Request, quote_id: str):
    await require_auth(request)
    db = get_db()
    res = await db[QUOTE_COL].update_one(
        {"id": quote_id}, {"$set": {"status": "deleted", "deleted_at": _now_iso()}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Quote not found")
    return {"success": True, "message": "Quote dihapus"}
