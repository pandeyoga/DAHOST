# ruff: noqa: F401
"""
rahaza_payroll_payslips.py — Payslip Management & PDF
Extracted from rahaza_payroll.py (1539 LOC monolith)

Refactored: Session #11.19 Phase 3.2 Batch #4
Endpoints: GET /payslips, GET /payslips/{id}, PUT /payslips/{id}, GET /payslips/{id}/pdf
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from routes.rahaza_payroll_shared import (
    _uid, _now, VALID_SCHEMES, VALID_PERIOD_TYPES, VALID_RUN_STATUS,
    _get_applicable_allowances, _require_hr,
    _payslip_totals, _recompute_run_totals,
)
from routes.rahaza_posting import post_payroll_run
from utils.saga import SagaExecutor
from utils.pdf_common import get_company_profile, get_doc_settings, resolve_signature_name
import uuid
import io
import csv
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional
from utils.waktu import fmt_wib

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-payroll-payslips"])

# ─── PDF helpers ────────────────────────────────────────────────────────────────

def _idr(n):
    """Format angka ke Rupiah Indonesia, contoh: 1500000 → Rp 1.500.000"""
    try:
        n = int(round(float(n or 0)))
    except Exception:
        n = 0
    return f"Rp {n:,}".replace(",", ".")


def _build_payslip_pdf(slip: dict, run: dict, profile: dict = None, doc_settings: dict = None) -> io.BytesIO:
    """
    Generate satu halaman slip gaji (A5) untuk satu karyawan.
    Mengembalikan BytesIO berisi PDF.
    profile/doc_settings (opsional) → branding perusahaan + konfigurasi tanda tangan.
    """
    profile = profile or {}
    doc_settings = doc_settings or {}
    _company_name = (profile.get("company_name") or "CV. DEWI ADITYA")
    _company_sub = (profile.get("tagline") or profile.get("address") or "Industri Garmen")
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A5,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    W = A5[0] - 24 * mm  # usable width

    # ── styles ────────────────────────────────────────────────────────────────
    getSampleStyleSheet()
    NAVY   = colors.HexColor("#1a2a4a")
    TEAL   = colors.HexColor("#0f6b8e")
    LIGHT  = colors.HexColor("#f0f6fa")
    GREY   = colors.HexColor("#6b7280")
    BLACK  = colors.black
    WHITE  = colors.white
    GREEN  = colors.HexColor("#1a7a4a")
    RED    = colors.HexColor("#b91c1c")

    h1  = ParagraphStyle("h1",  fontSize=13, fontName="Helvetica-Bold",  textColor=NAVY,  leading=16)
    ParagraphStyle("h2",  fontSize=9,  fontName="Helvetica",       textColor=TEAL,  leading=12)
    h3  = ParagraphStyle("h3",  fontSize=7,  fontName="Helvetica",       textColor=GREY,  leading=9)
    lbl = ParagraphStyle("lbl", fontSize=7.5, fontName="Helvetica-Bold", textColor=NAVY,  leading=10)
    val = ParagraphStyle("val", fontSize=7.5, fontName="Helvetica",      textColor=BLACK, leading=10)
    mono= ParagraphStyle("mono",fontSize=7.5, fontName="Courier",        textColor=BLACK, leading=10)
    ParagraphStyle("rgt", fontSize=7.5, fontName="Helvetica",      textColor=BLACK, leading=10, alignment=TA_RIGHT)
    net_style = ParagraphStyle("net", fontSize=11, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT, leading=14)
    net_lbl   = ParagraphStyle("netl",fontSize=9,  fontName="Helvetica-Bold", textColor=WHITE, leading=12)

    # ── header: company logo + slip info ─────────────────────────────────────
    # Get company config (optional)
    company_tbl = Table(
        [[
            Paragraph(f"<b>{_company_name}</b>", h1),
            Paragraph(f"<b>SLIP GAJI</b><br/><font size='7' color='#6b7280'>{run.get('run_number', '')}</font>", ParagraphStyle("sr", fontSize=9, fontName="Helvetica-Bold", textColor=TEAL, alignment=TA_RIGHT, leading=12)),
        ]],
        colWidths=[W * 0.6, W * 0.4],
    )
    company_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    sub_tbl = Table(
        [[
            Paragraph(_company_sub, h3),
            Paragraph(
                f"Periode: {slip.get('period_from', '')} s/d {slip.get('period_to', '')}",
                ParagraphStyle("pd", fontSize=7, fontName="Helvetica", textColor=GREY, alignment=TA_RIGHT, leading=9)
            ),
        ]],
        colWidths=[W * 0.6, W * 0.4],
    )
    sub_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    # ── employee info box ──────────────────────────────────────────────────────
    scheme_labels = {"pcs": "Borongan Pcs", "hourly": "Borongan Jam", "weekly": "Mingguan", "monthly": "Bulanan"}
    scheme = scheme_labels.get(slip.get("pay_scheme", ""), slip.get("pay_scheme", "-"))
    emp_rows = [
        ["Nama Karyawan", slip.get("employee_name", "-"), "Kode", slip.get("employee_code", "-")],
        ["Skema Gaji",    scheme,                          "Hadir", f"{slip.get('days_hadir', 0)} hari"],
        ["Jam Kerja",     f"{slip.get('total_hours_worked', 0)} jam", "Lembur", f"{slip.get('overtime_hours', 0)} jam"],
    ]
    emp_tbl = Table(
        [
            [Paragraph(r[0], lbl), Paragraph(str(r[1]), val), Paragraph(r[2], lbl), Paragraph(str(r[3]), val)]
            for r in emp_rows
        ],
        colWidths=[W * 0.22, W * 0.33, W * 0.16, W * 0.29],
    )
    emp_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), LIGHT),
        ("ROWBACKGROUND",(0, 0), (-1, 0),  colors.HexColor("#dbeaf4")),
        ("BOX",          (0, 0), (-1, -1), 0.5, TEAL),
        ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#c0d8e8")),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))

    # ── earnings table ──────────────────────────────────────────────────────────
    earn_header = [
        Paragraph("Uraian Pendapatan", lbl),
        Paragraph("Qty", ParagraphStyle("lbl_c", fontSize=7.5, fontName="Helvetica-Bold", textColor=NAVY, alignment=TA_RIGHT, leading=10)),
        Paragraph("Satuan", ParagraphStyle("lbl_c2", fontSize=7.5, fontName="Helvetica-Bold", textColor=NAVY, alignment=TA_RIGHT, leading=10)),
        Paragraph("Jumlah", ParagraphStyle("lbl_r", fontSize=7.5, fontName="Helvetica-Bold", textColor=NAVY, alignment=TA_RIGHT, leading=10)),
    ]
    earn_rows = [earn_header]
    for e in (slip.get("earnings") or []):
        earn_rows.append([
            Paragraph(e.get("label", ""), val),
            Paragraph(str(e.get("qty", "")), mono),
            Paragraph(str(e.get("unit", "")), mono),
            Paragraph(_idr(e.get("amount", 0)), ParagraphStyle("am_r", fontSize=7.5, fontName="Courier", textColor=BLACK, alignment=TA_RIGHT, leading=10)),
        ])
    # overtime row
    if slip.get("overtime_amount", 0) > 0:
        # 2026-11-02 (K24): tarif cadangan 1/173 × upah tetap → tampilkan dasar per jamnya, bukan "× tarif".
        ot_lbl = (f"Uang Lembur ({slip.get('overtime_hours', 0)} jam, 1/173 upah tetap = "
                  f"{_idr(slip.get('overtime_base_hourly', 0))}/jam)"
                  if slip.get("overtime_basis") == "upah_tetap_div_173"
                  else f"Uang Lembur ({slip.get('overtime_hours', 0)} jam × {_idr(slip.get('overtime_rate', 0))})")
        earn_rows.append([
            Paragraph(ot_lbl, val),
            Paragraph("", val),
            Paragraph("", val),
            Paragraph(_idr(slip.get("overtime_amount", 0)), ParagraphStyle("am_r2", fontSize=7.5, fontName="Courier", textColor=BLACK, alignment=TA_RIGHT, leading=10)),
        ])
    # 2026-11-02 (K34): penyesuaian pendapatan (±) oleh HR — bruto sudah termasuk nilai ini.
    if round(float(slip.get("manual_addition") or 0)):
        earn_rows.append([
            Paragraph(f"Penyesuaian pendapatan ({slip.get('adjustment_notes') or '-'})", val),
            Paragraph("", val),
            Paragraph("", val),
            Paragraph(_idr(slip.get("manual_addition", 0)), ParagraphStyle("am_r3", fontSize=7.5, fontName="Courier", textColor=BLACK, alignment=TA_RIGHT, leading=10)),
        ])
    earn_tbl = Table(earn_rows, colWidths=[W * 0.47, W * 0.13, W * 0.14, W * 0.26])
    earn_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  TEAL),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  WHITE),
        ("ROWBACKGROUND",(0, 1), (-1, -1), None),
        ("ROWBACKGROUND",(0, 1), (-1, -1), LIGHT),
        ("ROWBACKGROUND",(0, 2), (-1, -2), WHITE),
        ("BOX",          (0, 0), (-1, -1), 0.5, TEAL),
        ("LINEBELOW",    (0, 0), (-1, 0),  0.5, TEAL),
        ("GRID",         (0, 1), (-1, -1), 0.2, colors.HexColor("#d1e4ed")),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))

    # earnings subtotal row
    earn_sub = Table(
        [[
            Paragraph("Total Pendapatan", ParagraphStyle("sub_l", fontSize=8, fontName="Helvetica-Bold", textColor=TEAL, leading=10)),
            Paragraph(_idr(slip.get("gross_pay", 0)), ParagraphStyle("sub_r", fontSize=8, fontName="Courier-Bold", textColor=TEAL, alignment=TA_RIGHT, leading=10)),
        ]],
        colWidths=[W * 0.74, W * 0.26],
    )
    earn_sub.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#dbeaf4")),
        ("BOX",          (0, 0), (-1, -1), 0.5, TEAL),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))

    # ── allowances table (DA tunjangan tetap) ──────────────────────────────────
    allowance_items_data = slip.get("allowances") or []
    allowance_elements = []
    if allowance_items_data:
        alw_header = [
            Paragraph("Tunjangan", ParagraphStyle("ah_l", fontSize=7.5, fontName="Helvetica-Bold", textColor=WHITE, leading=10)),
            Paragraph("Jumlah", ParagraphStyle("ah_r", fontSize=7.5, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT, leading=10)),
        ]
        alw_rows = [alw_header]
        for alw in allowance_items_data:
            alw_rows.append([
                Paragraph(alw.get("label", ""), val),
                Paragraph(_idr(alw.get("amount", 0)), ParagraphStyle("alw_r", fontSize=7.5, fontName="Courier", textColor=GREEN, alignment=TA_RIGHT, leading=10)),
            ])
        alw_tbl = Table(alw_rows, colWidths=[W * 0.74, W * 0.26])
        alw_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#1a7a4a")),
            ("ROWBACKGROUND",(0, 1), (-1, -1), colors.HexColor("#f0faf5")),
            ("BOX",          (0, 0), (-1, -1), 0.5, colors.HexColor("#1a7a4a")),
            ("GRID",         (0, 1), (-1, -1), 0.2, colors.HexColor("#b0e0c0")),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
            ("LEFTPADDING",  (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        allowance_elements = [Spacer(1, 3 * mm), alw_tbl]

    # ── deductions table ────────────────────────────────────────────────────────
    ded_rows_data = [d for d in (slip.get("deductions") or []) if float(d.get("amount") or 0) or d.get("adjusted")]
    # 2026-11-02 (K34): potongan penyesuaian manual ikut tercetak (dulu masuk total tetapi tidak tampil).
    if round(float(slip.get("manual_deduction") or 0)):
        ded_rows_data = ded_rows_data + [{"label": f"Potongan penyesuaian ({slip.get('adjustment_notes') or '-'})",
                                          "amount": slip.get("manual_deduction")}]
    ded_elements = []
    if ded_rows_data:
        ded_header = [
            Paragraph("Potongan", ParagraphStyle("dh_l", fontSize=7.5, fontName="Helvetica-Bold", textColor=WHITE, leading=10)),
            Paragraph("Jumlah", ParagraphStyle("dh_r", fontSize=7.5, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT, leading=10)),
        ]
        ded_rows = [ded_header]
        for d in ded_rows_data:
            ded_rows.append([
                Paragraph(d.get("label", ""), val),
                Paragraph(_idr(d.get("amount", 0)), ParagraphStyle("dr_r", fontSize=7.5, fontName="Courier", textColor=RED, alignment=TA_RIGHT, leading=10)),
            ])
        ded_tbl = Table(ded_rows, colWidths=[W * 0.74, W * 0.26])
        ded_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#c0392b")),
            ("ROWBACKGROUND",(0, 1), (-1, -1), colors.HexColor("#fff5f5")),
            ("BOX",          (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")),
            ("GRID",         (0, 1), (-1, -1), 0.2, colors.HexColor("#fcc")),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
            ("LEFTPADDING",  (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        ded_elements = [Spacer(1, 3 * mm), ded_tbl]

    # ── net pay box ─────────────────────────────────────────────────────────────
    net_tbl = Table(
        [[
            Paragraph("GAJI BERSIH", net_lbl),
            Paragraph(_idr(slip.get("net_pay", 0)), net_style),
        ]],
        colWidths=[W * 0.45, W * 0.55],
    )
    net_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), NAVY),
        ("BOX",          (0, 0), (-1, -1), 0,   NAVY),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [3]),
    ]))

    # ── attendance summary bar ──────────────────────────────────────────────────
    att_cells = [
        [Paragraph("Hadir", h3), Paragraph(str(slip.get("days_hadir", 0)), lbl)],
        [Paragraph("Jam Kerja", h3), Paragraph(f"{slip.get('total_hours_worked', 0)} j", lbl)],
        [Paragraph("Lembur", h3), Paragraph(f"{slip.get('overtime_hours', 0)} j", lbl)],
    ]
    att_bar = Table(
        [list(sum(att_cells, []))],
        colWidths=[W / 6] * 6,
    )
    att_bar.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#f0f6fa")),
        ("BOX",          (0, 0), (-1, -1), 0.3, TEAL),
        ("GRID",         (0, 0), (-1, -1), 0.2, colors.HexColor("#c0d8e8")),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ]))

    # ── notes ───────────────────────────────────────────────────────────────────
    notes_el = []
    if slip.get("notes"):
        notes_el = [
            Spacer(1, 2 * mm),
            Paragraph(f"<i>Catatan: {slip['notes']}</i>", h3),
        ]

    # ── signature section (configurable — P1d) ──────────────────────────────────
    sig_context = {
        "employee_name": slip.get("employee_name", ""),
        "employee_code": slip.get("employee_code", ""),
        "run_number": run.get("run_number", ""),
        "approved_by": run.get("approved_by_name") or run.get("posted_by_name", ""),
    }
    sig_defs = doc_settings.get("signatures") or [
        {"label": "Disetujui oleh", "name_source": "custom", "custom_name": "", "role_label": "Manager / HRD"},
        {"label": "Diterima oleh", "name_source": "field", "field_key": "employee_name", "role_label": "Karyawan"},
    ]
    show_sig = doc_settings.get("show_signatures", True)
    sig_style = ParagraphStyle("sig", fontSize=7, fontName="Helvetica", textColor=GREY, alignment=TA_CENTER, leading=9)
    header_cells, name_cells = [], []
    for sd in sig_defs:
        nm = resolve_signature_name(sd, sig_context) or "________________"
        role = sd.get("role_label", "")
        header_cells.append(Paragraph(f"{sd.get('label','')},", h3))
        name_cells.append(Paragraph(f"({nm})<br/><font size='6'>{role}</font>", sig_style))
    ncol = max(len(sig_defs), 1)
    sig_tbl = Table(
        [header_cells, [Spacer(1, 12 * mm)] * ncol, name_cells],
        colWidths=[W / ncol] * ncol,
    )
    sig_tbl.setStyle(TableStyle([
        ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))

    # ── assemble ────────────────────────────────────────────────────────────────
    # SESI #19 — kop memakai TEMPLATE PDF pemilik bila ada (logo, telepon, NPWP,
    # tata letak). Kop lama (nama + tagline + garis tebal) TETAP dipakai sebagai
    # cadangan supaya slip gaji tidak pernah gagal cetak hanya karena template
    # belum diatur. Sisa tata letak A5 (kotak karyawan, blok gaji bersih,
    # watermark RAHASIA) sengaja TIDAK diubah: itu bagian yang sudah baik.
    _tpl = (doc_settings or {}).get("_template") or {}
    kop_els = []
    if _tpl.get("header"):
        try:
            from core.pdf_template import header_flowables
            kop_els = header_flowables(
                _tpl["header"], profile, "SLIP GAJI",
                info_pairs=[
                    ("No. Run", run.get("run_number", "")),
                    ("Periode", f"{slip.get('period_from', '')} s/d {slip.get('period_to', '')}"),
                ], avail=W)
        except Exception as e:  # noqa: BLE001
            log.warning("[payslip] kop template gagal dipakai, memakai kop lama: %s", e)
            kop_els = []

    story = [
        *(kop_els if kop_els else [
            company_tbl,
            sub_tbl,
            HRFlowable(width="100%", thickness=1.5, color=TEAL, spaceAfter=4),
        ]),
        emp_tbl,
        Spacer(1, 3 * mm),
        earn_tbl,
        earn_sub,
        *allowance_elements,
        *ded_elements,
        Spacer(1, 3 * mm),
        net_tbl,
        Spacer(1, 3 * mm),
        att_bar,
        *notes_el,
        Spacer(1, 5 * mm),
        *([HRFlowable(width="100%", thickness=0.5, color=GREY, spaceAfter=4), sig_tbl] if show_sig else []),
        Spacer(1, 2 * mm),
        Paragraph(
            f"<i>Slip ini dicetak secara otomatis oleh Sistem ERP CV. Dewi Aditya · {fmt_wib('%d/%m/%Y %H:%M')}</i>",
            ParagraphStyle("foot", fontSize=5.5, fontName="Helvetica-Oblique", textColor=GREY, alignment=TA_CENTER, leading=7)
        ),
    ]

    # ── watermark NAMA PERUSAHAAN + label RAHASIA (diagonal, abu muda) ────────
    # FASE 15 (permintaan user 2026-07-26): watermark harus menampilkan nama
    # perusahaan ("CV. DEWI ADITYA"), bukan hanya kata "RAHASIA". Nama diambil
    # dari profil perusahaan supaya ikut berubah bila perusahaan ganti nama.
    _wm_text = (_company_name or "CV. DEWI ADITYA").upper()
    # BUG-3: slip dari run yang MASIH DRAFT harus terlihat jelas belum final —
    # angkanya masih bisa berubah saat run difinalisasi.
    _is_draft = str(run.get("status", "")).lower() in ("", "draft")

    def _rahasia_watermark(canvas, _doc):
        canvas.saveState()
        try:
            canvas.setFillColorRGB(0.82, 0.82, 0.82, alpha=0.30)
        except TypeError:
            # older reportlab — no alpha param
            canvas.setFillColorRGB(0.88, 0.88, 0.88)
        canvas.translate(A5[0] / 2, A5[1] / 2)
        canvas.rotate(45)
        # Ukuran huruf disesuaikan panjang nama supaya tidak terpotong di A5.
        size = 46 if len(_wm_text) <= 16 else max(22, int(740 / len(_wm_text)))
        canvas.setFont("Helvetica-Bold", size)
        canvas.drawCentredString(0, 6 * mm, _wm_text)
        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawCentredString(0, -10 * mm, "RAHASIA")
        if _is_draft:
            canvas.setFont("Helvetica-Bold", 14)
            canvas.drawCentredString(0, -24 * mm, "DRAFT - BELUM FINAL")
        canvas.restoreState()

    doc.build(story, onFirstPage=_rahasia_watermark, onLaterPages=_rahasia_watermark)
    buf.seek(0)
    return buf


@router.get("/payslips/{pid}/pdf")
async def export_payslip_pdf(pid: str, request: Request):
    """Unduh PDF satu slip gaji.

    BUG-3 (2026-07-26):
      · Karyawan TIDAK BISA mengunduh slip gajinya sendiri — endpoint menolak
        403 dengan pesan "Hubungi HR untuk salinan resmi", dan Portal Saya sama
        sekali tidak punya tombol unduh. Padahal slip gaji adalah dokumen milik
        karyawan (dipakai untuk pengajuan kredit, dsb).
      · Kepemilikan diperiksa lewat `user.get("employee_id")` MENTAH dari JWT
        (umur 24 jam) ⇒ karyawan yang baru ditautkan HR tetap ditolak.
    Sekarang: HR/Admin/Manager boleh semua slip; karyawan boleh slip MILIKNYA,
    dengan identitas dari SSOT `utils/employee_identity`.
    """
    user = await require_auth(request)
    db = get_db()
    slip = await db.rahaza_payslips.find_one({"id": pid}, {"_id": 0})
    if not slip:
        raise HTTPException(404, "Payslip tidak ditemukan.")

    # 2026-11-02 (audit T3 lanjutan): aturan SAMA dengan GET /payslips — HR/Keuangan/Manajemen
    # (`_can_view_all_payslips`) boleh semua slip termasuk draft (ber-watermark); karyawan hanya
    # slip MILIKNYA dan hanya dari run final/dibayar. Dulu PDF slip run DRAFT tetap bisa diunduh
    # karyawan padahal JSON-nya disembunyikan (angka draft masih bisa berubah).
    if not await _can_view_all_payslips(request, user):
        from utils.employee_identity import resolve_my_employee
        emp = await resolve_my_employee(db, user)
        if not emp or emp.get("id") != slip.get("employee_id"):
            raise HTTPException(
                403, "Anda hanya bisa mengunduh slip gaji milik Anda sendiri.")
        if not await only_published_slips(db, [slip]):
            raise HTTPException(404, "Slip gaji ini belum difinalisasi HR.")

    run = await db.rahaza_payroll_runs.find_one({"id": slip.get("run_id", "")}, {"_id": 0}) or {}
    profile = await get_company_profile(db)
    doc_settings = await get_doc_settings(db, "payslip")
    try:
        buf = _build_payslip_pdf(dict(slip), dict(run), profile=profile, doc_settings=doc_settings)
    except Exception as e:
        log.error(f"PDF generation error: {e}", exc_info=True)
        raise HTTPException(500, f"Gagal generate PDF: {e}")
    fname = f"slip_{slip.get('employee_code', 'EMP')}_{slip.get('period_from', '')}_{slip.get('period_to', '')}.pdf"
    fname = fname.replace(" ", "_")
    preview = request.query_params.get("preview") in ("1", "true", "yes")
    disposition = "inline" if preview else "attachment"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{fname}"'},
    )


@router.get("/payroll-runs/{run_id}/pdf")
async def export_run_pdf(run_id: str, request: Request):
    """Download PDF bundle berisi SEMUA slip gaji dalam satu run (1 halaman per karyawan)."""
    user = await require_auth(request)
    # 2026-11-02 (audit T3) — dulu hanya `require_auth`: operator mengunduh slip 25 karyawan.
    # Kini hanya peran yang boleh melihat SEMUA slip (aturan sama dengan GET /payslips).
    if not await _can_view_all_payslips(request, user):
        raise HTTPException(403, "Forbidden: unduh slip satu run khusus HR/Keuangan/Manajemen.")
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    payslips = await db.rahaza_payslips.find(
        {"run_id": run_id}, {"_id": 0}
    ).sort("employee_code", 1).to_list(500)
    if not payslips:
        raise HTTPException(404, "Tidak ada payslip dalam run ini.")

    profile = await get_company_profile(db)
    doc_settings = await get_doc_settings(db, "payslip")
    try:
        from PyPDF2 import PdfWriter, PdfReader
        writer = PdfWriter()
        for slip in payslips:
            single_buf = _build_payslip_pdf(dict(slip), dict(run), profile=profile, doc_settings=doc_settings)
            reader = PdfReader(single_buf)
            for page in reader.pages:
                writer.add_page(page)
        out_buf = io.BytesIO()
        writer.write(out_buf)
        out_buf.seek(0)
    except ImportError:
        # Fallback: merge via concatenation into one buffer per-slip
        # Generate each slip separately and concatenate raw PDF bytes as ZIP
        import zipfile
        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for slip in payslips:
                single_buf = _build_payslip_pdf(dict(slip), dict(run), profile=profile, doc_settings=doc_settings)
                fname = f"slip_{slip.get('employee_code', 'EMP')}.pdf"
                zf.writestr(fname, single_buf.read())
        out_buf.seek(0)
        run_num = run.get("run_number", run_id[:8])
        return StreamingResponse(
            out_buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="payroll_{run_num}_slips.zip"'},
        )

    run_num = run.get("run_number", run_id[:8])
    fname = f"payroll_{run_num}_all_slips.pdf"
    return StreamingResponse(
        out_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── AKSES BACA SLIP (2026-11-02, audit T3) ────────────────────────────────────
# Dulu GET /payslips & /payslips/{pid} hanya `require_auth`: akun karyawan mana pun
# (mis. tim_packing) membaca 50 slip milik 25 karyawan. Sekarang:
#   · peran payroll `_require_hr` (sama dengan unduh PDF) dan pemegang portal
#     SDM/Keuangan/Manajemen (SSOT `routes.shared.require_portal`, sama dengan
#     gerbang router payroll-runs) → semua slip;
#   · selain itu → hanya slip miliknya (karyawan tertaut, SSOT employee_identity)
#     dan hanya dari run final/dibayar; akun tanpa karyawan tertaut → 403.
_PAYSLIP_ALL_ROLES = ("superadmin", "admin", "owner", "hr", "manager")
_PAYSLIP_ALL_PORTALS = ("hr", "finance", "management")
# Status run yang slipnya boleh dilihat karyawan: "finalized" (VALID_RUN_STATUS)
# + "paid" (dipakai payroll_automation). Draft masih bisa berubah; cancelled bukan gaji.
PUBLISHED_RUN_STATUSES = ("finalized", "paid")


async def only_published_slips(db, slips: list) -> list:
    """Saring slip: hanya yang run-nya berstatus final/dibayar (dipakai juga Portal Saya)."""
    run_ids = list({s.get("run_id") for s in slips if s.get("run_id")})
    if not run_ids:
        return []
    runs = await db.rahaza_payroll_runs.find(
        {"id": {"$in": run_ids}, "status": {"$in": list(PUBLISHED_RUN_STATUSES)}},
        {"_id": 0, "id": 1},
    ).to_list(len(run_ids))
    ok = {r.get("id") for r in runs}
    return [s for s in slips if s.get("run_id") in ok]


async def _can_view_all_payslips(request: Request, user: dict) -> bool:
    role = (user.get("role") or "").lower()
    if role in _PAYSLIP_ALL_ROLES:
        return True
    perms = user.get("_permissions") or []
    if "*" in perms or "hr.manage" in perms or "payroll.manage" in perms:
        return True
    from routes.shared import require_portal
    try:
        await require_portal(request, *_PAYSLIP_ALL_PORTALS, allow_perms=("payroll.manage",))
        return True
    except HTTPException as e:
        if e.status_code == 403:
            return False
        raise


async def _payslip_scope(request: Request):
    """(user, emp). `emp` None = boleh semua slip; selain itu hanya slip karyawan `emp`."""
    user = await require_auth(request)
    if await _can_view_all_payslips(request, user):
        return user, None
    from utils.employee_identity import resolve_my_employee
    emp = await resolve_my_employee(get_db(), user)
    if not emp or not emp.get("id"):
        raise HTTPException(
            403, "Anda hanya bisa melihat slip gaji milik Anda sendiri, tetapi akun Anda "
                 "belum tertaut ke data karyawan. Hubungi HR.")
    return user, emp


# ── PAYSLIPS ──────────────────────────────────────────────────────────────────
@router.get("/payslips")
async def list_payslips(request: Request, run_id: Optional[str] = None, employee_id: Optional[str] = None, employee_code: Optional[str] = None):
    _, my_emp = await _payslip_scope(request)
    db = get_db()
    q = {}
    if run_id:
        q["run_id"] = run_id
    if employee_id:
        q["employee_id"] = employee_id
    if employee_code:
        q["employee_code"] = employee_code
    if my_emp is not None:
        # 2026-11-02 — karyawan biasa: filter ke orang lain ditolak, bukan diam-diam diabaikan.
        if (employee_id and employee_id != my_emp["id"]) or \
                (employee_code and employee_code != my_emp.get("employee_code")):
            raise HTTPException(403, "Anda hanya bisa melihat slip gaji milik Anda sendiri.")
        q["employee_id"] = my_emp["id"]
    rows = await db.rahaza_payslips.find(q, {"_id": 0}).sort("employee_code", 1).to_list(500)
    if my_emp is not None:
        rows = await only_published_slips(db, rows)
    return serialize_doc(rows)


@router.get("/payslips/{pid}")
async def get_payslip(pid: str, request: Request):
    _, my_emp = await _payslip_scope(request)
    db = get_db()
    row = await db.rahaza_payslips.find_one({"id": pid}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Payslip tidak ditemukan.")
    if my_emp is not None:
        if row.get("employee_id") != my_emp["id"]:
            raise HTTPException(403, "Anda hanya bisa melihat slip gaji milik Anda sendiri.")
        if not await only_published_slips(db, [row]):
            raise HTTPException(404, "Slip gaji ini belum difinalisasi HR.")
    return serialize_doc(row)


@router.put("/payslips/{pid}")
async def update_payslip(pid: str, request: Request):
    """Update deductions & notes saja (untuk adjust manual). Hanya jika run masih draft."""
    user = await _require_hr(request)
    db = get_db()
    slip = await db.rahaza_payslips.find_one({"id": pid}, {"_id": 0})
    if not slip:
        raise HTTPException(404, "Payslip tidak ditemukan.")
    run = await db.rahaza_payroll_runs.find_one({"id": slip["run_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run induk tidak ditemukan.")
    if run.get("status") != "draft":
        raise HTTPException(400, "Run sudah di-finalize — slip tidak bisa diubah.")

    body = await request.json()
    deductions = body.get("deductions") or []
    norm_ded = []
    for d in deductions:
        label = (d.get("label") or "").strip()
        amount = float(d.get("amount") or 0)
        if not label or amount <= 0:
            continue
        # Iter 119: pertahankan `type`/`kasbon_id` — dipakai agregator H-02 (PPh21/BPJS/kasbon) & pemangkas kasbon.
        row = {"label": label, "amount": round(amount)}
        if d.get("type"):
            row["type"] = str(d["type"]).lower()
        if d.get("kasbon_id"):
            row["kasbon_id"] = d["kasbon_id"]
        norm_ded.append(row)
    ded_total, net = _payslip_totals(slip, deductions=norm_ded)
    await db.rahaza_payslips.update_one({"id": pid}, {"$set": {
        "deductions": norm_ded,
        "deductions_total": ded_total,
        "net_pay": net,
        "notes": body.get("notes") or slip.get("notes", ""),
        "updated_at": _now(),
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    }})
    # FASE 20 — WAJIB: `post_payroll_run()` menyusun jurnal GL dari HEADER run,
    # bukan dari payslip. Sebelum ini slip diubah tanpa menyinkronkan header,
    # sehingga `total_net`/`total_deductions` di header (yang dipakai jurnal,
    # export Excel, dan kartu ringkasan) menyimpang dari jumlah slip sebenarnya.
    await _recompute_run_totals(db, slip["run_id"])
    out = await db.rahaza_payslips.find_one({"id": pid}, {"_id": 0})
    return serialize_doc(out)


# ─── PENYESUAIAN MANUAL PAYSLIP ──────────────────────────────────────────────
# FASE 20 — endpoint ini DIPANGGIL FE (`RahazaPayrollRunModule` → tombol "Adj")
# tetapi TIDAK PERNAH ADA di backend: `manual_deduction` & `adjustment_notes`
# nol hasil pencarian di seluruh `backend/`. Jadi kolom "Adj" selalu menampilkan
# 0 dan setiap penyimpanan hilang tanpa pesan error (404 senyap, FE tidak
# memeriksa `res.ok`).
#
# Sengaja TIDAK dialihkan ke `PUT /payslips/{pid}` yang sudah ada, karena
# semantiknya beda: PUT MENGGANTI seluruh array `deductions` (akan menghapus
# BPJS/PPh21/kasbon hasil hitungan sistem) dan menulis ke `notes`, sementara FE
# menampilkan `manual_deduction` + `adjustment_notes`.
# 2026-11-02 (K34, keputusan owner): sebelum finalisasi HR boleh MENAMBAH/MENGURANGI PENDAPATAN maupun
# POTONGAN dengan alasan, lewat endpoint yang SAMA (tombol "Adj"):
#   earning_adjustment  (± Rp)  → penyesuaian pendapatan; bruto = bruto sistem + nilai ini (≥ 0)
#   deduction           (≥ 0)   → potongan penyesuaian manual (perilaku lama; jurnal Cr credit_other_deduction)
#   deduction_overrides [{index, amount}] → KURANGI baris potongan sistem (terlambat/LWOP/kasbon),
#                         0 ≤ amount ≤ nilai asli. BPJS & PPh21 tidak diubah manual (ubah kepesertaan/
#                         setelan lalu buat ulang run draft).
#   notes / reason      → WAJIB bila ada penyesuaian ≠ 0.
# BPJS/PPh21 TIDAK dihitung ulang atas penyesuaian pendapatan (dicatat di respons sebagai peringatan).
STATUTORY_DEDUCTION_PREFIXES = ("bpjs", "pph21")


def _num_or_400(raw, field: str) -> float:
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} harus berupa angka.")


@router.post("/payroll-runs/{run_id}/payslips/{slip_id}/adjust")
async def adjust_payslip(run_id: str, slip_id: str, request: Request):
    """Set penyesuaian manual pada satu payslip (lihat blok K34 di atas).

    Idempoten: mengirim nilai yang sama dua kali menghasilkan angka yang sama —
    nilai penyesuaian DIGANTI, bukan ditambahkan.
    """
    user = await _require_hr(request)
    db = get_db()

    slip = await db.rahaza_payslips.find_one({"id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(404, "Payslip tidak ditemukan.")
    # Slip harus benar-benar milik run di URL — kalau tidak, satu run bisa
    # dipakai untuk mengubah slip run lain (IDOR + total header jadi salah).
    if slip.get("run_id") != run_id:
        raise HTTPException(404, "Payslip tidak ada di payroll run tersebut.")

    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") != "draft":
        raise HTTPException(400, "Run sudah di-finalize — slip tidak bisa diubah.")

    body = await request.json()
    # ── potongan penyesuaian manual (≥ 0) — tidak dikirim = nilai sekarang
    if "deduction" in body or "manual_deduction" in body:
        deduction = _num_or_400(body.get("deduction", body.get("manual_deduction")), "Nilai penyesuaian")
    else:
        deduction = float(slip.get("manual_deduction") or 0)
    if deduction < 0:
        raise HTTPException(400, "Potongan penyesuaian tidak boleh negatif — untuk MENGURANGI potongan sistem "
                                 "pakai deduction_overrides, untuk menambah gaji pakai earning_adjustment.")
    # ── penyesuaian pendapatan (±)
    if "earning_adjustment" in body or "manual_addition" in body:
        addition = _num_or_400(body.get("earning_adjustment", body.get("manual_addition")), "Penyesuaian pendapatan")
    else:
        addition = float(slip.get("manual_addition") or 0)
    gross_base = float(slip.get("gross_before_adjustment")
                       if slip.get("gross_before_adjustment") is not None
                       else float(slip.get("gross_pay") or 0) - float(slip.get("manual_addition") or 0))
    new_gross = round(gross_base + round(addition))
    if new_gross < 0:
        raise HTTPException(400, f"Pengurangan pendapatan {addition:,.0f} melebihi bruto {gross_base:,.0f}.".replace(",", "."))

    # ── kurangi baris potongan sistem (bukan BPJS/PPh21)
    lines = [dict(d) for d in (slip.get("deductions") or [])]
    overrides = body.get("deduction_overrides") or []
    if not isinstance(overrides, list):
        raise HTTPException(400, "deduction_overrides harus daftar [{index, amount}].")
    for ov in overrides:
        try:
            idx = int(ov.get("index"))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(400, "deduction_overrides: index tidak valid.")
        if idx < 0 or idx >= len(lines):
            raise HTTPException(400, f"deduction_overrides: baris potongan #{idx} tidak ada.")
        ln = lines[idx]
        typ = str(ln.get("type") or "").lower()
        if typ.startswith(STATUTORY_DEDUCTION_PREFIXES):
            raise HTTPException(400, f"Potongan wajib '{ln.get('label')}' (BPJS/PPh21) tidak diubah manual — ubah "
                                     "kepesertaan/pengaturan lalu hapus & buat ulang run draft.")
        original = float(ln.get("original_amount") if ln.get("original_amount") is not None else ln.get("amount") or 0)
        amt = _num_or_400(ov.get("amount"), "deduction_overrides.amount")
        if amt < 0 or amt > original + 0.01:
            raise HTTPException(400, (f"Potongan '{ln.get('label')}' hanya boleh DIKURANGI: 0 s/d {original:,.0f} "
                                      "(untuk menambah potongan pakai potongan penyesuaian).").replace(",", "."))
        ln["original_amount"] = original
        ln["amount"] = round(amt)
        ln["adjusted"] = abs(round(amt) - original) > 0.01

    notes = (body.get("notes") or body.get("reason") or "").strip()
    changed = round(deduction) != 0 or round(addition) != 0 or any(ln.get("adjusted") for ln in lines)
    if changed and not notes:
        raise HTTPException(400, "Alasan penyesuaian wajib diisi.")

    adj_slip = {**slip, "gross_pay": new_gross}
    ded_total, net = _payslip_totals(adj_slip, deductions=lines, manual_deduction=deduction)
    # Batas atas: total potongan tidak boleh melebihi bruto (net negatif =
    # karyawan berutang ke perusahaan lewat payroll — bukan alur yang didukung).
    if ded_total > new_gross:
        raise HTTPException(
            400,
            f"Penyesuaian terlalu besar: total potongan {ded_total:,.0f} melebihi bruto {new_gross:,.0f}.".replace(",", "."),
        )

    log_entry = {"at": _now(), "by": user["id"], "by_name": user.get("name", ""), "reason": notes,
                 "manual_deduction": round(deduction), "manual_addition": round(addition),
                 "overrides": [{"index": int(o.get("index")), "amount": round(float(o.get("amount") or 0))}
                               for o in overrides]}
    await db.rahaza_payslips.update_one({"id": slip_id}, {"$set": {
        "manual_deduction": round(deduction),
        "manual_addition": round(addition),
        "gross_before_adjustment": gross_base,
        "gross_pay": new_gross,
        "deductions": lines,
        "adjustment_notes": notes,
        "deductions_total": ded_total,
        "net_pay": net,
        "updated_at": _now(),
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    }, "$push": {"adjustments_log": log_entry}})
    totals = await _recompute_run_totals(db, run_id)
    await log_activity(user["id"], user.get("name", ""), "adjust", "rahaza.payslip",
                       f"{slip.get('employee_code', slip_id)} pendapatan {round(addition)} potongan {round(deduction)}"
                       f" baris {len(overrides)} — {notes}")
    out = await db.rahaza_payslips.find_one({"id": slip_id}, {"_id": 0})
    warn = ("BPJS & PPh21 tidak dihitung ulang atas penyesuaian pendapatan." if round(addition) else None)
    return {"ok": True, "payslip": serialize_doc(out), "run_totals": serialize_doc(totals), "warning": warn}
