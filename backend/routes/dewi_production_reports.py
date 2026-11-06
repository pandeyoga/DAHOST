"""
CV. Dewi Aditya — Production Reports Export (CSV)
GAP #6: Laporan Produksi Komprehensif

Endpoints:
  - GET /api/dewi/reports/production/po/{po_id}/export.csv
  - GET /api/dewi/reports/maklon/client/{client_id}/export.csv
"""
# ruff: noqa: E402
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from database import get_db
from auth import require_auth
from routes._maklon_adapter import legacy_orders_view as _lmo
import uuid
import csv
import io
from datetime import datetime, timezone
from utils.waktu import now_wib

router = APIRouter(prefix="/api/dewi/reports", tags=["dewi-reports"])


def _uid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _fmt_date(d):
    """Format date untuk CSV"""
    if not d:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def _fmt_num(n):
    """Format number untuk CSV"""
    try:
        return f"{float(n or 0):,.0f}"
    except Exception:
        return "0"


NO_DATA = "belum ada data"


async def _wo_cost_row(db, wo: dict) -> dict:
    """Biaya satu WO untuk unduhan laporan PO — dari mesin HPP yang sama dengan layar
    (`rahaza_hpp._compute_hpp`: bahan keluar × biaya saat keluar, upah dari hasil
    produksi × tarif, overhead dari pengaturan).

    Tahap 1 (6 Nov 2026): dulu upah = jumlah event × Rp5.000 dan overhead = 15% dari
    bahan+upah — angka karangan."""
    from routes.rahaza_hpp import _compute_hpp
    model = await db.rahaza_models.find_one({"id": wo.get("model_id")}, {"_id": 0, "code": 1})
    size = await db.rahaza_sizes.find_one({"id": wo.get("size_id")}, {"_id": 0, "code": 1})
    hpp = await _compute_hpp(db, wo["id"])
    return {
        "model_code": (model or {}).get("code") or hpp.get("model_code") or "",
        "size_code": (size or {}).get("code") or hpp.get("size_code") or "",
        "completed_qty": int(wo.get("completed_qty") or 0),
        "material_cost": hpp.get("material_cost", 0),
        "labor_cost": hpp.get("labor_cost", 0),
        "overhead_cost": hpp.get("overhead_cost", 0),
        "total_cost": hpp.get("total_cost", 0),
    }


@router.get("/production/po/{po_id}/export.csv")
async def export_po_report_csv(po_id: str, request: Request):
    """
    Export laporan per PO ke CSV.
    Include: PO info, WO list, stage progress, HPP breakdown.
    """
    await require_auth(request)
    db = get_db()
    
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "Production PO tidak ditemukan.")
    
    # Get WOs via order_id or po_number
    # T-03 (FASE 3): SSOT production_jobs via core.wo_reader (job ter-anchor po_id).
    from core.wo_reader import load_wos
    wos = await load_wos(db, po_ids=[po_id], limit=500)
    
    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header Section
    writer.writerow(["Laporan Produksi per PO - CV. Dewi Aditya"])
    writer.writerow(["PO Number", po.get("po_number", "")])
    writer.writerow(["Customer", po.get("customer_name", "")])
    writer.writerow(["Status", po.get("status", "")])
    writer.writerow(["Created At", _fmt_date(po.get("created_at"))])
    writer.writerow([])
    
    # WO Table
    writer.writerow(["Work Orders"])
    writer.writerow([
        "WO Number", "Model", "Size", "Qty Order", "Qty Completed", 
        "Status", "Material Cost", "Labor Cost", "Overhead Cost", "Total Cost"
    ])
    
    # Tahap 1 (6 Nov 2026): biaya per WO dari mesin HPP yang sama dengan layar
    # (`rahaza_hpp._compute_hpp`) — lihat `_wo_cost_row`.
    for wo in wos:
        r = await _wo_cost_row(db, wo)
        model_code, size_code, completed_qty = r["model_code"], r["size_code"], r["completed_qty"]
        material_cost, labor_cost = r["material_cost"], r["labor_cost"]
        overhead_cost, total_cost = r["overhead_cost"], r["total_cost"]

        writer.writerow([
            wo.get("wo_number", ""),
            model_code,
            size_code,
            wo.get("qty", 0),
            completed_qty,
            wo.get("status", ""),
            _fmt_num(material_cost),
            _fmt_num(labor_cost),
            _fmt_num(overhead_cost),
            _fmt_num(total_cost),
        ])
    
    writer.writerow([])
    writer.writerow(["Generated at", _now().isoformat()])
    
    # Return CSV
    output.seek(0)
    filename = f"laporan_po_{po.get('po_number', 'unknown').replace('/', '_')}_{now_wib().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/maklon/client/{client_id}/export.csv")
async def export_maklon_client_report_csv(client_id: str, request: Request):
    """
    Export laporan per Klien Maklon ke CSV.
    Include: Client info, orders list, KPI summary.
    """
    await require_auth(request)
    db = get_db()
    
    client = await db.dewi_maklon_clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Klien maklon tidak ditemukan.")
    
    # Filters
    sp = request.query_params
    date_from = sp.get("date_from")
    date_to = sp.get("date_to")
    
    query = {"client_id": client_id}
    if date_from or date_to:
        query["order_date"] = {}
        if date_from:
            query["order_date"]["$gte"] = date_from
        if date_to:
            query["order_date"]["$lte"] = date_to
    
    orders = await _lmo(db).find(query, {"_id": 0}).to_list(500)
    
    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header Section
    writer.writerow(["Laporan per Klien Maklon - CV. Dewi Aditya"])
    writer.writerow(["Client Code", client.get("code", "")])
    writer.writerow(["Client Name", client.get("name", "")])
    writer.writerow(["Total Orders", len(orders)])
    writer.writerow([])
    
    # Summary KPIs
    # Tahap 1 (6 Nov 2026): angka per order dari `rahaza_hpp.maklon_order_figures` — dulu
    # HPP aktual = bahan +30% +15% dan HPP estimasi = pendapatan (angka karangan).
    from routes.rahaza_hpp import maklon_order_figures
    figs = {o["id"]: await maklon_order_figures(db, o) for o in orders}
    total_qty = 0
    total_revenue = 0
    total_material = 0
    on_time = 0
    late = 0

    for order in orders:
        fig = figs[order["id"]]
        total_qty += fig["qty"]
        total_revenue += fig["revenue"]
        total_material += fig["material_cost"]

        # On-time check
        if order.get("status") == "completed":
            deadline = order.get("deadline_date")
            completion = order.get("completion_date")
            if completion and deadline and completion <= deadline:
                on_time += 1
            else:
                late += 1
    
    on_time_rate = (on_time / (on_time + late) * 100) if (on_time + late) > 0 else 0

    writer.writerow(["KPI Summary"])
    writer.writerow(["Total Qty", _fmt_num(total_qty)])
    writer.writerow(["Total Revenue", _fmt_num(total_revenue)])
    writer.writerow(["Biaya bahan tercatat", _fmt_num(total_material)])
    writer.writerow(["Total HPP Estimated", NO_DATA])
    writer.writerow(["Total HPP Actual", NO_DATA])
    writer.writerow(["Margin", NO_DATA])
    writer.writerow(["Margin %", NO_DATA])
    writer.writerow(["On-Time Orders", on_time])
    writer.writerow(["Late Orders", late])
    writer.writerow(["On-Time Rate", f"{on_time_rate:.2f}%"])
    writer.writerow([])
    
    # Orders Table
    writer.writerow(["Order Details"])
    writer.writerow([
        "Order Code", "Product", "Qty", "Status", "Revenue", "Biaya bahan",
        "HPP Estimated", "HPP Actual", "Margin", "Deadline", "Completion", "On-Time"
    ])

    for order in orders:
        fig = figs[order["id"]]
        qty, revenue = fig["qty"], fig["revenue"]

        deadline = order.get("deadline_date", "")
        completion = order.get("completion_date", "")
        is_on_time = ""
        if order.get("status") == "completed":
            is_on_time = "Yes" if (completion and deadline and completion <= deadline) else "No"
        
        writer.writerow([
            order.get("order_code", ""),
            order.get("product_name", ""),
            qty,
            order.get("status", ""),
            _fmt_num(revenue),
            _fmt_num(fig["material_cost"]),
            NO_DATA,
            NO_DATA,
            NO_DATA,
            deadline,
            completion,
            is_on_time,
        ])
    
    writer.writerow([])
    writer.writerow(["Generated at", _now().isoformat()])
    
    # Return CSV
    output.seek(0)
    filename = f"laporan_client_{client.get('code', 'unknown')}_{now_wib().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )



# ══════════════════════════════════════════════════════════════════════════════
# Phase 3.4: Excel Export Endpoints
# ══════════════════════════════════════════════════════════════════════════════

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter


@router.get("/production/po/{po_id}/export.xlsx")
async def export_po_report_excel(po_id: str, request: Request):
    """
    Export laporan per PO ke Excel dengan formatting rapi.
    """
    await require_auth(request)
    db = get_db()
    
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "Production PO tidak ditemukan.")
    
    # Get WOs
    # T-03 (FASE 3): SSOT production_jobs via core.wo_reader (job ter-anchor po_id).
    from core.wo_reader import load_wos
    wos = await load_wos(db, po_ids=[po_id], limit=500)
    
    # Create Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan PO"
    
    # Header styling
    header_fill = PatternFill(start_color="1F4788", end_color="1F4788", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Title
    ws.merge_cells('A1:J1')
    ws['A1'] = "LAPORAN PRODUKSI PER PO - CV. Dewi Aditya"
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    
    # PO Info
    row = 3
    ws[f'A{row}'] = "PO Number:"
    ws[f'B{row}'] = po.get("po_number", "")
    ws[f'B{row}'].font = Font(bold=True)
    
    row += 1
    ws[f'A{row}'] = "Customer:"
    ws[f'B{row}'] = po.get("customer_name", "")
    
    row += 1
    ws[f'A{row}'] = "Status:"
    ws[f'B{row}'] = po.get("status", "")
    
    row += 1
    ws[f'A{row}'] = "Created:"
    ws[f'B{row}'] = _fmt_date(po.get("created_at"))
    
    # WO Table Header
    row += 2
    headers = ["WO Number", "Model", "Size", "Qty Order", "Qty Done", "Status", "Material Cost", "Labor Cost", "Overhead", "Total Cost"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = border
    
    # WO Data
    for wo in wos:
        row += 1
        r = await _wo_cost_row(db, wo)
        model_code, size_code, completed_qty = r["model_code"], r["size_code"], r["completed_qty"]
        material_cost, labor_cost = r["material_cost"], r["labor_cost"]
        overhead_cost, total_cost = r["overhead_cost"], r["total_cost"]

        # Write row
        data = [
            wo.get("wo_number", ""),
            model_code,
            size_code,
            wo.get("qty", 0),
            completed_qty,
            wo.get("status", ""),
            material_cost,
            labor_cost,
            overhead_cost,
            total_cost,
        ]
        
        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = border
            if col_idx >= 7:  # Currency columns
                cell.number_format = '#,##0'
            cell.alignment = Alignment(horizontal='right' if col_idx >= 4 else 'left')
    
    # Adjust column widths
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 15
    
    # Save to bytes
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"laporan_po_{po.get('po_number', 'unknown').replace('/', '_')}_{now_wib().strftime('%Y%m%d')}.xlsx"
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/maklon/client/{client_id}/export.xlsx")
async def export_maklon_client_report_excel(client_id: str, request: Request):
    """
    Export laporan per Klien Maklon ke Excel dengan formatting rapi.
    """
    await require_auth(request)
    db = get_db()
    
    client = await db.dewi_maklon_clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Klien maklon tidak ditemukan.")
    
    # Get orders
    sp = request.query_params
    date_from = sp.get("date_from")
    date_to = sp.get("date_to")
    
    query = {"client_id": client_id}
    if date_from or date_to:
        query["order_date"] = {}
        if date_from:
            query["order_date"]["$gte"] = date_from
        if date_to:
            query["order_date"]["$lte"] = date_to
    
    orders = await _lmo(db).find(query, {"_id": 0}).to_list(500)
    
    # Create Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan Client"
    
    # Styling
    header_fill = PatternFill(start_color="1F4788", end_color="1F4788", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    kpi_fill = PatternFill(start_color="E7F3FF", end_color="E7F3FF", fill_type="solid")
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Title
    ws.merge_cells('A1:L1')
    ws['A1'] = "LAPORAN PER KLIEN MAKLON - CV. Dewi Aditya"
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center')
    
    # Client Info
    row = 3
    ws[f'A{row}'] = "Client Code:"
    ws[f'B{row}'] = client.get("code", "")
    ws[f'B{row}'].font = Font(bold=True)
    
    row += 1
    ws[f'A{row}'] = "Client Name:"
    ws[f'B{row}'] = client.get("name", "")
    ws[f'B{row}'].font = Font(bold=True)
    
    row += 1
    ws[f'A{row}'] = "Total Orders:"
    ws[f'B{row}'] = len(orders)
    
    # KPI Summary
    total_qty = sum(int(o.get("qty_ordered") or 0) for o in orders)
    total_revenue = sum(int(o.get("qty_ordered") or 0) * float(o.get("price_per_pcs") or 0) for o in orders)
    
    row += 2
    ws[f'A{row}'] = "KPI SUMMARY"
    ws[f'A{row}'].font = Font(bold=True, size=12)
    
    row += 1
    kpi_data = [
        ("Total Qty:", total_qty),
        ("Total Revenue:", total_revenue),
    ]
    for label, value in kpi_data:
        ws[f'A{row}'] = label
        ws[f'B{row}'] = value
        ws[f'A{row}'].fill = kpi_fill
        ws[f'B{row}'].fill = kpi_fill
        if isinstance(value, (int, float)):
            ws[f'B{row}'].number_format = '#,##0'
        row += 1
    
    # Orders Table
    row += 1
    headers = ["Order Code", "Product", "Qty", "Status", "Revenue", "Biaya bahan", "HPP Est", "HPP Actual", "Margin", "Deadline", "Completion", "On-Time"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')
        cell.border = border
    
    # Order data — Tahap 1 (6 Nov 2026): angka nyata saja (`maklon_order_figures`);
    # dulu HPP aktual = bahan +30% +15% dan HPP estimasi = pendapatan.
    from routes.rahaza_hpp import maklon_order_figures
    for order in orders:
        row += 1
        fig = await maklon_order_figures(db, order)
        qty, revenue = fig["qty"], fig["revenue"]

        deadline = order.get("deadline_date", "")
        completion = order.get("completion_date", "")
        is_on_time = ""
        if order.get("status") == "completed":
            is_on_time = "Yes" if (completion and deadline and completion <= deadline) else "No"
        
        data = [
            order.get("order_code", ""),
            order.get("product_name", ""),
            qty,
            order.get("status", ""),
            revenue,
            fig["material_cost"],
            NO_DATA,
            NO_DATA,
            NO_DATA,
            deadline,
            completion,
            is_on_time,
        ]

        for col_idx, value in enumerate(data, 1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            cell.border = border
            if col_idx in [5, 6]:  # Currency
                cell.number_format = '#,##0'
            cell.alignment = Alignment(horizontal='right' if col_idx >= 3 else 'left')
    
    # Column widths
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 14
    
    # Save
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"laporan_client_{client.get('code', 'unknown')}_{now_wib().strftime('%Y%m%d')}.xlsx"
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
