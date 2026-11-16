"""utils.bukti_gabungan_pdf — PDF bukti pembayaran GABUNGAN (16 Nov 2026).

Satu lembar untuk satu pembayaran yang menutup beberapa dokumen: bukti bayar ke satu CMT (beberapa tagihan) dan
bukti terima dari satu klien maklon (beberapa PO). Kop, tanda tangan, kaki, dan gaya tabel mengikuti template PDF
pemilik (`core.pdf_template`) seperti kwitansi pembayaran (`routes.rahaza_payment_receipt`).
"""
from __future__ import annotations

import io
from datetime import date


def _rp(n) -> str:
    return "Rp " + f"{round(float(n or 0)):,}".replace(",", ".")


def _tgl(s) -> str:
    bulan = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
             "November", "Desember")
    try:
        d = date.fromisoformat(str(s)[:10])
        return f"{d.day:02d} {bulan[d.month - 1]} {d.year}"
    except (TypeError, ValueError):
        return str(s or "-")


def build_bukti_pdf(*, judul: str, doc: dict, pihak_label: str, kolom: list, baris: list, kanan: list,
                    ringkas: list, template: dict, profile: dict, printed_by: str) -> bytes:
    """`kolom` = judul kolom tabel rincian; `baris` = isi (teks siap cetak); `kanan` = indeks kolom angka;
    `ringkas` = [(label, nilai)] tambahan di bawah jumlah (mis. bagian uang muka)."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, Spacer, Table, TableStyle

    from core.pdf_template import footer_flowables, header_flowables, signature_flowables
    from routes.operations_pdf_helpers import CONTENT_W_PORTRAIT, _build_pdf, _pdf_data_table
    from routes.rahaza_payment_receipt import terbilang

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13, textColor=colors.HexColor("#1f2937"))
    muted = ParagraphStyle("muted", parent=body, fontSize=8.5, leading=11, textColor=colors.HexColor("#64748b"))
    big = ParagraphStyle("big", parent=body, fontSize=15, leading=19, textColor=colors.HexColor("#0f172a"))
    avail = CONTENT_W_PORTRAIT
    template = template or {}
    elems = header_flowables(template.get("header"), profile, judul, avail=avail,
                             info_pairs=[("No. Bukti", doc.get("bukti_number") or "-"),
                                         ("Tanggal", _tgl(doc.get("tanggal"))),
                                         ("Rekening", doc.get("cash_account_name") or "-")])
    jumlah = float(doc.get("amount") or 0)
    rows = [[Paragraph(f"<b>{pihak_label}</b>", body), Paragraph(doc.get("pihak_name") or "-", body)],
            [Paragraph("<b>Jumlah</b>", body), Paragraph(f"<b>{_rp(jumlah)}</b>", big)],
            [Paragraph("<b>Terbilang</b>", body),
             Paragraph(f"<i>{terbilang(round(jumlah)).capitalize()} rupiah</i>", body)]]
    for label, nilai in ringkas or []:
        rows.append([Paragraph(f"<b>{label}</b>", body), Paragraph(str(nilai), body)])
    if doc.get("reference_no") and doc.get("reference_no") != doc.get("bukti_number"):
        rows.append([Paragraph("<b>No. referensi</b>", body), Paragraph(str(doc["reference_no"]), body)])
    if doc.get("notes"):
        rows.append([Paragraph("<b>Catatan</b>", body), Paragraph(str(doc["notes"]), body)])
    t = Table(rows, colWidths=[avail * 0.28, avail * 0.72])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e2e8f0")),
                           ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f1f5f9"))]))
    elems += [Spacer(1, 3 * mm), t, Spacer(1, 4 * mm), Paragraph("<b>Rincian pembagian</b>", body), Spacer(1, 2 * mm)]
    elems.append(_pdf_data_table(kolom, baris, right_cols=kanan, total_row=True, style=template.get("table")))
    elems.append(Spacer(1, 4 * mm))
    elems.extend(signature_flowables(template.get("signatures"), {
        "customer_name": doc.get("pihak_name") or "", "invoice_number": doc.get("bukti_number") or "",
        "confirmed_by": doc.get("created_by_name") or "", "printed_by": printed_by}, avail=avail))
    elems += [Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#cbd5e1")),
              Paragraph(f"Dicetak oleh {printed_by or '-'} · satu bukti untuk beberapa dokumen; tiap baris punya "
                        "nomor jurnalnya sendiri.", muted)]
    elems.extend(footer_flowables(template.get("footer"), profile))
    return _build_pdf(io.BytesIO(), elems, page=template.get("page")).getvalue()
