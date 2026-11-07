"""Transaksi & saldo ANTAR CV (Tahap 8 fase 2) — Portal Keuangan.

    GET  /api/rahaza/intercompany/status                 akun lawan transaksi, vendor tim Sukma, margin aksesoris
    POST /api/rahaza/intercompany/setup                  siapkan master & akun lawan transaksi (idempoten)
    GET  /api/rahaza/intercompany/transactions           daftar Transaksi antar CV (CV terpilih / Gabungan)
    POST /api/rahaza/intercompany/transactions           talangan / pinjaman / uang nyasar / pelunasan → 2 jurnal
    POST /api/rahaza/intercompany/transactions/{id}/void batalkan (dua jurnal di-void)
    GET  /api/rahaza/intercompany/balances?as_of=        Laporan Saldo antar CV (dua sisi + selisih + rincian)
    GET  /api/rahaza/intercompany/documents              tagihan jasa jahit & nota aksesoris (dua buku)
    GET  /api/rahaza/intercompany/documents/{id}/pdf     PDF "Tagihan Jasa Jahit" (kop CV Sukma) / "Nota Aksesoris"
                                                         (kop CV Dewi Aditya)

Aturan bisnisnya di `core.intercompany` (satu sumber). Penulisan ditolak di mode Gabungan
(`entity_from_request` + `middleware.cv_readonly_guard`).
"""
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from auth import log_activity, require_auth, serialize_doc
from core import intercompany as ic
from core.entities import ALL, DA, SMU, entity_from_request, entity_short
from database import get_db
from routes.rahaza_finance import _require_fin
from routes.shared import require_portal_dep
from utils.waktu import today_wib

router = APIRouter(prefix="/api/rahaza/intercompany", tags=["rahaza-intercompany"],
                   dependencies=[Depends(require_portal_dep("finance"))])


@router.get("/status")
async def ic_status(request: Request):
    await require_auth(request)
    db = get_db()
    accs = await ic.ic_accounts(db, create=False)
    return {"accounts": {DA: accs[DA], SMU: accs[SMU]}, "records": accs["records"], "vendor": accs["vendor"],
            "margin_pct": await ic.margin_pct(db), "margin_key": ic.MARGIN_KEY,
            "kinds": [{"value": k, "label": v["label"], "direction": v["dir"], "source_hint": v["src_hint"],
                       "other_hint": v["oth_hint"]} for k, v in ic.TXN_KINDS.items()],
            "missing": ic.missing_accounts_message(accs, [(DA, "ar"), (DA, "ap"), (SMU, "ar"), (SMU, "ap")])}


@router.post("/setup")
async def ic_setup(request: Request):
    user = await _require_fin(request)
    db = get_db()
    info = await ic.ensure_counterparts(db, user, apply=True)
    accs = await ic.ic_accounts(db, user, create=True)
    await log_activity(user["id"], user.get("name", ""), "setup", "intercompany", "Siapkan akun antar CV")
    return {"counterparts": info, "accounts": {DA: accs[DA], SMU: accs[SMU]}, "vendor": accs["vendor"]}


@router.get("/transactions")
async def list_transactions(request: Request, limit: int = Query(200, ge=1, le=2000)):
    await require_auth(request)
    db = get_db()
    ent = entity_from_request(request, allow_all=True)
    q = {} if ent == ALL else {"$or": [{"source_entity": ent}, {"other_entity": ent}]}
    rows = await db[ic.TXN_COLL].find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": serialize_doc(rows), "total": len(rows)}


@router.post("/transactions")
async def create_transaction(request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    src = entity_from_request(request, body)   # CV asal = CV terpilih (Gabungan ditolak)
    try:
        doc = await ic.create_transaction(db, body, src, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not doc.get("already"):
        await log_activity(user["id"], user.get("name", ""), "create", "intercompany",
                           f"{doc['number']} {doc['kind']} {entity_short(doc['source_entity'])} → "
                           f"{entity_short(doc['other_entity'])} Rp {doc['amount']:,.0f}")
    return serialize_doc(doc)


@router.post("/transactions/{tid}/void")
async def void_transaction(tid: str, request: Request):
    user = await _require_fin(request)
    db = get_db()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — badan kosong
        body = {}
    try:
        doc = await ic.void_transaction(db, tid, user, str((body or {}).get("reason") or "dibatalkan").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    await log_activity(user["id"], user.get("name", ""), "void", "intercompany", doc.get("number") or tid)
    return serialize_doc(doc)


@router.get("/balances")
async def balances(request: Request, as_of: str = Query(None)):
    await require_auth(request)
    return await ic.balance_report(get_db(), (as_of or today_wib().isoformat())[:10])


@router.get("/documents")
async def documents(request: Request, limit: int = Query(300, ge=1, le=2000)):
    """Tagihan jasa jahit (CV Sukma) & nota aksesoris (CV Dewi Aditya) — dokumen berlabel antar CV."""
    await require_auth(request)
    db = get_db()
    ent = entity_from_request(request, allow_all=True)
    q = {"intercompany": True, "source_module": {"$in": [ic.DOC_SEWING, ic.DOC_ACCESSORY]}}
    if ent != ALL:
        q["entity"] = ent
    rows = await db.rahaza_ar_invoices.find(q, {"_id": 0}).sort("issue_date", -1).limit(limit).to_list(limit)
    out = [{k: r.get(k) for k in ("id", "invoice_number", "entity", "ic_kind", "customer_name", "issue_date", "total",
                                  "paid_amount", "balance", "status", "po_number", "ic_bill_code", "margin_amount",
                                  "margin_pct", "gl_je_number")} for r in rows]
    return {"items": serialize_doc(out), "total": len(out)}


def _fmt_d(s) -> str:
    try:
        return date.fromisoformat(str(s)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(s or "-")


def build_ic_document_pdf(doc: dict, profile: dict, template: dict, printed_by: str) -> bytes:
    """PDF dokumen antar CV: Tagihan Jasa Jahit (kop CV Sukma) atau Nota Aksesoris (kop CV Dewi Aditya)."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    from core.pdf_template import footer_flowables, header_flowables, signature_flowables
    from routes.operations_pdf_helpers import CONTENT_W_PORTRAIT, _build_pdf
    from routes.rahaza_payment_receipt import terbilang

    sewing = doc.get("ic_kind") == ic.KIND_SEWING
    title = "TAGIHAN JASA JAHIT" if sewing else "NOTA AKSESORIS"
    to_name = doc.get("customer_name") or "-"
    body = ParagraphStyle("b", parent=getSampleStyleSheet()["Normal"], fontSize=9, leading=12)
    avail = CONTENT_W_PORTRAIT
    info = [("No. Dokumen", doc.get("invoice_number") or "-"), ("Tanggal", _fmt_d(doc.get("issue_date"))),
            ("Kepada", to_name), ("Jatuh tempo", _fmt_d(doc.get("due_date"))),
            ("No. PO", doc.get("po_number") or "-")]
    if sewing:
        info.append(("Tagihan CMT", doc.get("ic_bill_code") or "-"))
    elems = header_flowables(template.get("header"), profile, title, avail=avail, info_pairs=info)
    rows = [["No", "Uraian", "Qty", "Harga", "Jumlah"]]
    items = doc.get("items") or []
    for i, it in enumerate(items, start=1):
        qty = float(it.get("qty") or 0)
        price = float(it.get("unit_price") or it.get("unit_cost") or 0)
        amt = float(it.get("total") or qty * price)
        rows.append([str(i), Paragraph(str(it.get("description") or it.get("name") or it.get("material_id") or "-"), body),
                     f"{qty:,.2f}".rstrip("0").rstrip(".").replace(",", "."), ic.fmt_rp(price), ic.fmt_rp(amt)])
    if not sewing and float(doc.get("margin_amount") or 0) > 0:
        rows.append(["", Paragraph(f"Margin {float(doc.get('margin_pct') or 0):g}% dari harga pokok", body), "", "",
                     ic.fmt_rp(doc.get("margin_amount"))])
    rows.append(["", Paragraph("<b>Total</b>", body), "", "", ic.fmt_rp(doc.get("total"))])
    t = Table(rows, colWidths=[avail * 0.06, avail * 0.48, avail * 0.12, avail * 0.16, avail * 0.18], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                           ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elems += [Spacer(1, 3 * mm), t, Spacer(1, 3 * mm),
              Paragraph(f"<i>Terbilang: {terbilang(round(float(doc.get('total') or 0))).capitalize()} rupiah</i>", body),
              Paragraph(f"Dokumen {ic.IC_LABEL} — dicatat otomatis di dua buku. Dibayar: {ic.fmt_rp(doc.get('paid_amount'))}"
                        f" · sisa {ic.fmt_rp(doc.get('balance'))}.", body), Spacer(1, 4 * mm)]
    elems.extend(signature_flowables(template.get("signatures"), {
        "customer_name": to_name, "invoice_number": doc.get("invoice_number") or "", "printed_by": printed_by},
        avail=avail))
    elems.extend(footer_flowables(template.get("footer"), profile))
    return _build_pdf(io.BytesIO(), elems, page=template.get("page")).getvalue()


@router.get("/documents/{doc_id}/pdf")
async def document_pdf(doc_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    doc = await db.rahaza_ar_invoices.find_one({"id": doc_id, "intercompany": True}, {"_id": 0})
    if not doc:
        ap = await db.rahaza_ap_invoices.find_one({"id": doc_id, "intercompany": True}, {"_id": 0})
        if ap and ap.get("ic_pair_doc_id"):
            doc = await db.rahaza_ar_invoices.find_one({"id": ap["ic_pair_doc_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Dokumen antar CV tidak ditemukan.")
    from core import pdf_template
    # Penerbit dokumen = buku piutangnya: tagihan jasa jahit → CV Sukma, nota aksesoris → CV Dewi Aditya.
    issuer = SMU if doc.get("ic_kind") == ic.KIND_SEWING else DA
    profile = await pdf_template.company_profile(db, issuer)
    template = await pdf_template.resolve(db, "sales-note")
    pdf = build_ic_document_pdf(doc, profile, template, user.get("name") or "")
    prefix = "Tagihan-Jasa-Jahit" if issuer == SMU else "Nota-Aksesoris"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{prefix}_{doc.get("invoice_number", doc_id)}.pdf"'})
