"""
PT Rahaza — Phase F1 Finance Reports
Currently: Trial Balance (per account, per period range).
(F2: P&L, Balance Sheet, Journal List; F3: Cash Flow)
"""
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import StreamingResponse
from database import get_db
from auth import require_auth, serialize_doc
from datetime import date
from typing import Optional
import io

from routes.shared import require_portal_dep  # FIN-04
from core.fin_statements import (
    compute_trial_balance, compute_worksheet, compute_profit_loss_monthly, compute_balance_sheet_monthly,
    compute_cash_flow_by_account, xlsx_profit_loss_monthly, xlsx_balance_sheet_monthly, xlsx_worksheet, xlsx_cash_flow,
)

router = APIRouter(prefix="/api/rahaza/finance/reports", tags=["rahaza-fin-reports"],
                   dependencies=[Depends(require_portal_dep("finance"))])  # FIN-04: laporan keuangan hanya portal keuangan


@router.get("/trial-balance")
async def trial_balance(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    as_of: Optional[str] = Query(None),
    show_zero: bool = False,
):
    """Aggregate posted journal lines per account within date range.
    Shows: account_code, account_name, type, total_debit, total_credit, net (debit - credit).
    Opening balance: sum of all lines BEFORE from_date (if provided), then add period movement.
    `as_of` = alias `to` (konsisten dgn neraca).
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not to_date:
        to_date = as_of or today
    return await compute_trial_balance(db, from_date, to_date, show_zero)


@router.get("/worksheet")
async def worksheet(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    show_zero: bool = False,
):
    """Neraca lajur: saldo awal · mutasi · saldo akhir · kolom Laba Rugi · kolom Neraca + baris laba bersih penyeimbang."""
    await require_auth(request)
    return await compute_worksheet(get_db(), from_date, to_date or date.today().isoformat(), show_zero)


@router.get("/profit-loss-monthly")
async def profit_loss_monthly(request: Request, year: int = Query(..., ge=2000, le=2100)):
    """Laba rugi 12 kolom bulan (Jan–Des) + total + akumulasi, ala sheet Laba-12."""
    await require_auth(request)
    return await compute_profit_loss_monthly(get_db(), year)


@router.get("/balance-sheet-monthly")
async def balance_sheet_monthly(request: Request, year: int = Query(..., ge=2000, le=2100)):
    """Neraca per akhir tiap bulan (12 kolom), ala sheet Neraca-12."""
    await require_auth(request)
    return await compute_balance_sheet_monthly(get_db(), year)


@router.get("/export-xlsx")
async def export_xlsx(
    request: Request,
    report: str = Query(..., pattern="^(profit-loss-monthly|balance-sheet-monthly|worksheet|cash-flow)$"),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    show_zero: bool = False,
):
    """Ekspor Excel memakai perhitungan yang SAMA dengan layar (core.fin_statements)."""
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if report in ("profit-loss-monthly", "balance-sheet-monthly"):
        y = year or int(today[:4])
        if report == "profit-loss-monthly":
            data, fname = xlsx_profit_loss_monthly(await compute_profit_loss_monthly(db, y)), f"laba-rugi-12-bulan-{y}.xlsx"
        else:
            data, fname = xlsx_balance_sheet_monthly(await compute_balance_sheet_monthly(db, y)), f"neraca-12-bulan-{y}.xlsx"
    elif report == "worksheet":
        to_ = to_date or today
        data, fname = xlsx_worksheet(await compute_worksheet(db, from_date, to_, show_zero)), f"neraca-lajur-{from_date or 'awal'}-{to_}.xlsx"
    else:
        to_ = to_date or today
        from_ = from_date or f"{today[:4]}-01-01"
        data, fname = xlsx_cash_flow(await _cash_flow_data(db, from_, to_)), f"arus-kas-{from_}-{to_}.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/general-ledger")
async def general_ledger(
    request: Request,
    account_code: str = Query(...),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """Return all lines for a specific account within a date range, with running balance."""
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not to_date:
        to_date = today
    acc = await db.rahaza_coa_accounts.find_one({"code": account_code}, {"_id": 0})
    if not acc:
        raise HTTPException(404, f"Akun '{account_code}' tidak ditemukan.")

    # opening balance
    opening_net = 0.0
    if from_date:
        pipe_op = [
            {"$match": {"account_code": account_code, "date": {"$lt": from_date}}},
            {"$group": {"_id": None, "debit": {"$sum": "$debit"}, "credit": {"$sum": "$credit"}}},
        ]
        async for r in db.rahaza_journal_lines.aggregate(pipe_op):
            opening_net = (r.get("debit", 0) or 0) - (r.get("credit", 0) or 0)

    q = {"account_code": account_code}
    if from_date and to_date:
        q["date"] = {"$gte": from_date, "$lte": to_date}
    elif to_date:
        q["date"] = {"$lte": to_date}

    rows_raw = await db.rahaza_journal_lines.find(q, {"_id": 0}).sort([("date", 1), ("created_at", 1)]).to_list(100000)

    running = opening_net
    lines = []
    for r in rows_raw:
        running = running + (r.get("debit", 0) or 0) - (r.get("credit", 0) or 0)
        # Convert running to display debit or credit based on normal balance
        if acc["normal_balance"] == "DEBIT":
            balance = running
        else:
            balance = -running
        lines.append({
            "date": r["date"],
            "je_number": r.get("je_number"),
            "description": r.get("description") or "",
            "source": r.get("source_module"),
            "debit": r.get("debit", 0),
            "credit": r.get("credit", 0),
            "balance": round(balance, 2),
        })
    end_balance = lines[-1]["balance"] if lines else (opening_net if acc["normal_balance"] == "DEBIT" else -opening_net)
    return {
        "account": {"code": acc["code"], "name": acc["name"], "type": acc["type"], "normal_balance": acc["normal_balance"]},
        "meta": {"from": from_date, "to": to_date},
        "opening_balance": round((opening_net if acc["normal_balance"] == "DEBIT" else -opening_net), 2),
        "lines": lines,
        "end_balance": round(end_balance, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# F2: PROFIT & LOSS / INCOME STATEMENT
# ═══════════════════════════════════════════════════════════════════════════
_BS_KNOWN = {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "COGS", "EXPENSE", "OTHER_INCOME", "OTHER_EXPENSE"}
_BS_LEGACY = {"CURRENT_ASSET": "ASSET", "FIXED_ASSET": "ASSET", "OTHER": "OTHER_INCOME",
              "INCOME": "REVENUE", "CURRENT_LIABILITY": "LIABILITY"}


def _bs_type(acc: dict) -> str:
    """Tipe laporan yang dikenal; tipe legacy/tak dikenal dipetakan (fallback prefix kode)."""
    t = (acc.get("type") or "").upper()
    if t in _BS_KNOWN:
        return t
    if t in _BS_LEGACY:
        return _BS_LEGACY[t]
    return {"1": "ASSET", "2": "LIABILITY", "3": "EQUITY", "4": "REVENUE", "5": "COGS"}.get(
        (acc.get("code") or "")[:1], "EXPENSE")


async def _aggregate_by_account(db, match: dict):
    """Return dict {account_code: {debit, credit}} from posted journal lines."""
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$account_code",
            "debit": {"$sum": "$debit"},
            "credit": {"$sum": "$credit"},
        }},
    ]
    rows = {r["_id"]: r async for r in db.rahaza_journal_lines.aggregate(pipeline)}
    return rows


@router.get("/profit-loss")
async def profit_loss(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """F2: Income Statement / Profit & Loss.
    Grouping: REVENUE, OTHER_INCOME (credit − debit = income positive)
              COGS, EXPENSE, OTHER_EXPENSE (debit − credit = expense positive)
    Net Income = (Revenue + Other Income) − (COGS + Expense + Other Expense)
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not to_date:
        to_date = today
    if not from_date:
        from_date = f"{today[:4]}-01-01"
    return await compute_profit_loss(db, from_date, to_date)


async def compute_profit_loss(db, from_date: Optional[str], to_date: Optional[str]) -> dict:
    """SATU rumus Laba/Rugi buku besar (2026-11-02, K20/K33): dipakai layar L/R, kartu
    "Laba kotor (buku besar)" di Rekap Keuangan, dan laba bersih Laporan Eksekutif supaya
    ketiganya tidak pernah beda angka. `from_date`/`to_date` None = tanpa batas sisi itu."""
    rng = {}
    if from_date:
        rng["$gte"] = from_date
    if to_date:
        rng["$lte"] = to_date
    match = {"source_module": {"$ne": "year_end_close"}}  # M-09: jurnal penutup bukan L/R
    if rng:
        match["date"] = rng
    per_acc = await _aggregate_by_account(db, match)

    # Get all leaf accounts for types of interest
    type_groups = {
        "REVENUE": {"label": "Pendapatan", "accounts": []},
        "OTHER_INCOME": {"label": "Pendapatan Lain-lain", "accounts": []},
        "COGS": {"label": "Harga Pokok Penjualan (HPP)", "accounts": []},
        "EXPENSE": {"label": "Beban Operasional", "accounts": []},
        "OTHER_EXPENSE": {"label": "Beban Lain-lain", "accounts": []},
    }
    accounts = await db.rahaza_coa_accounts.find(
        {"type": {"$in": list(type_groups.keys())}, "is_group": False},
        {"_id": 0},
    ).sort("code", 1).to_list(5000)  # B-13: akun nonaktif bersaldo tetap ikut (sama dgn neraca)

    total_revenue = 0.0
    total_other_income = 0.0
    total_cogs = 0.0
    total_expense = 0.0
    total_other_expense = 0.0

    for acc in accounts:
        code = acc["code"]
        agg = per_acc.get(code, {"debit": 0, "credit": 0})
        d = float(agg.get("debit") or 0)
        c = float(agg.get("credit") or 0)
        if acc["type"] in ("REVENUE", "OTHER_INCOME"):
            # income = credit - debit (revenue normal balance = credit)
            amount = round(c - d, 2)
            row = {
                "code": code, "name": acc["name"], "type": acc["type"],
                "amount": amount, "debit": round(d, 2), "credit": round(c, 2),
            }
            type_groups[acc["type"]]["accounts"].append(row)
            if acc["type"] == "REVENUE":
                total_revenue += amount
            else:
                total_other_income += amount
        else:
            # expense/cogs = debit - credit (normal balance = debit)
            amount = round(d - c, 2)
            row = {
                "code": code, "name": acc["name"], "type": acc["type"],
                "amount": amount, "debit": round(d, 2), "credit": round(c, 2),
            }
            type_groups[acc["type"]]["accounts"].append(row)
            if acc["type"] == "COGS":
                total_cogs += amount
            elif acc["type"] == "EXPENSE":
                total_expense += amount
            else:
                total_other_expense += amount

    gross_profit = round(total_revenue - total_cogs, 2)
    operating_income = round(gross_profit - total_expense, 2)
    net_income = round(operating_income + total_other_income - total_other_expense, 2)

    return {
        "meta": {"from": from_date, "to": to_date},
        "groups": {
            "revenue": {"label": type_groups["REVENUE"]["label"], "accounts": type_groups["REVENUE"]["accounts"], "total": round(total_revenue, 2)},
            "cogs": {"label": type_groups["COGS"]["label"], "accounts": type_groups["COGS"]["accounts"], "total": round(total_cogs, 2)},
            "expense": {"label": type_groups["EXPENSE"]["label"], "accounts": type_groups["EXPENSE"]["accounts"], "total": round(total_expense, 2)},
            "other_income": {"label": type_groups["OTHER_INCOME"]["label"], "accounts": type_groups["OTHER_INCOME"]["accounts"], "total": round(total_other_income, 2)},
            "other_expense": {"label": type_groups["OTHER_EXPENSE"]["label"], "accounts": type_groups["OTHER_EXPENSE"]["accounts"], "total": round(total_other_expense, 2)},
        },
        "totals": {
            "revenue": round(total_revenue, 2),
            "cogs": round(total_cogs, 2),
            "gross_profit": gross_profit,
            "expense": round(total_expense, 2),
            "operating_income": operating_income,
            "other_income": round(total_other_income, 2),
            "other_expense": round(total_other_expense, 2),
            "net_income": net_income,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# F2: BALANCE SHEET
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/balance-sheet")
async def balance_sheet(
    request: Request,
    as_of: Optional[str] = Query(None),
):
    """F2: Balance Sheet (as of date).
    Assets = Liabilities + Equity.
    Current year earnings derived from P&L net income (YTD up to as_of).
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    if not as_of:
        as_of = today

    # aggregate all posted lines up to as_of
    match = {"date": {"$lte": as_of}}
    per_acc = await _aggregate_by_account(db, match)

    # get leaf accounts for Balance Sheet types + revenue/expense for net income calc
    # C-04: akun NONAKTIF yang punya saldo tetap ikut (kalau tidak, neraca tak seimbang);
    # tipe legacy (CURRENT_ASSET/OTHER/...) dinormalisasi lewat _bs_type().
    accounts = await db.rahaza_coa_accounts.find(
        {"is_group": False},
        {"_id": 0},
    ).sort("code", 1).to_list(5000)

    assets = []
    liabilities = []
    equity = []
    total_assets = 0.0
    total_liabilities = 0.0
    total_equity = 0.0
    # compute net income (same as P&L within YTD)
    total_rev = 0.0
    total_cogs = 0.0
    total_exp = 0.0
    total_oi = 0.0
    total_oe = 0.0
    unknown_types = []

    for acc in accounts:
        code = acc["code"]
        agg = per_acc.get(code, {"debit": 0, "credit": 0})
        d = float(agg.get("debit") or 0)
        c = float(agg.get("credit") or 0)
        if not acc.get("active", True) and d == 0 and c == 0:
            continue
        acc_type = _bs_type(acc)
        if acc_type != (acc.get("type") or "").upper():
            unknown_types.append({"code": code, "type": acc.get("type"), "treated_as": acc_type})

        if acc_type == "ASSET":
            bal = round(d - c, 2)
            if bal != 0:
                assets.append({"code": code, "name": acc["name"], "amount": bal})
            total_assets += bal
        elif acc_type == "LIABILITY":
            bal = round(c - d, 2)
            if bal != 0:
                liabilities.append({"code": code, "name": acc["name"], "amount": bal})
            total_liabilities += bal
        elif acc_type == "EQUITY":
            bal = round(c - d, 2)
            if bal != 0:
                equity.append({"code": code, "name": acc["name"], "amount": bal})
            total_equity += bal
        elif acc_type == "REVENUE":
            total_rev += round(c - d, 2)
        elif acc_type == "COGS":
            total_cogs += round(d - c, 2)
        elif acc_type == "EXPENSE":
            total_exp += round(d - c, 2)
        elif acc_type == "OTHER_INCOME":
            total_oi += round(c - d, 2)
        elif acc_type == "OTHER_EXPENSE":
            total_oe += round(d - c, 2)

    current_earnings = round(total_rev - total_cogs - total_exp + total_oi - total_oe, 2)
    # add "Laba/Rugi Tahun Berjalan" as computed equity line (virtual, from P&L)
    if current_earnings != 0:
        equity.append({
            "code": "LABA_BERJALAN",
            "name": "Laba/Rugi Tahun Berjalan (Komputasi)",
            "amount": current_earnings,
            "computed": True,
        })
        total_equity += current_earnings

    total_liab_equity = round(total_liabilities + total_equity, 2)
    balanced = round(total_assets, 2) == total_liab_equity
    # Baris jurnal pada akun yang TIDAK ADA di COA (mis. sub-akun dihapus) → neraca diam-diam tak seimbang.
    known = {a["code"] for a in accounts}
    orphan_accounts = [{"code": code, "debit": round(float(v.get("debit") or 0), 2), "credit": round(float(v.get("credit") or 0), 2)}
                       for code, v in per_acc.items() if code not in known]

    return {
        "meta": {"as_of": as_of},
        "assets": {"accounts": assets, "total": round(total_assets, 2)},
        "liabilities": {"accounts": liabilities, "total": round(total_liabilities, 2)},
        "equity": {"accounts": equity, "total": round(total_equity, 2)},
        "totals": {
            "assets": round(total_assets, 2),
            "liabilities": round(total_liabilities, 2),
            "equity": round(total_equity, 2),
            "liab_plus_equity": total_liab_equity,
            "current_earnings": current_earnings,
            "diff": round(round(total_assets, 2) - total_liab_equity, 2),
        },
        "balanced": balanced,
        "type_warnings": unknown_types,
        "orphan_account_lines": orphan_accounts,
    }


# ═══════════════════════════════════════════════════════════════════════════
# F2: JOURNAL LIST (audit trail with filter)
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/journal-list")
async def journal_list(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    source: Optional[str] = None,
    status: Optional[str] = None,
    account_code: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
):
    """F2: filtered journal list (audit trail).
    Optionally filter by account_code: returns only JEs whose lines touch that account.
    """
    await require_auth(request)
    db = get_db()
    q = {}
    if from_date and to_date:
        q["date"] = {"$gte": from_date, "$lte": to_date}
    elif from_date:
        q["date"] = {"$gte": from_date}
    elif to_date:
        q["date"] = {"$lte": to_date}
    if source:
        q["source_module"] = source
    if status:
        q["status"] = status

    if account_code:
        # find JE ids that have line with account_code
        line_rows = await db.rahaza_journal_lines.find(
            {"account_code": account_code, **({"date": q["date"]} if "date" in q else {})},
            {"_id": 0, "je_id": 1},
        ).to_list(100000)
        je_ids = list({r["je_id"] for r in line_rows})
        if not je_ids:
            return {"meta": {"from": from_date, "to": to_date, "source": source, "status": status, "account_code": account_code}, "rows": [], "total_debit": 0, "total_credit": 0}
        q["id"] = {"$in": je_ids}

    rows = await db.rahaza_journal_entries.find(q, {"_id": 0}).sort([("date", -1), ("je_number", -1)]).limit(limit).to_list(limit)
    # summarize totals (only posted)
    total_debit = sum(float(r.get("total_debit") or 0) for r in rows if r.get("status") == "posted")
    total_credit = sum(float(r.get("total_credit") or 0) for r in rows if r.get("status") == "posted")

    return {
        "meta": {"from": from_date, "to": to_date, "source": source, "status": status, "account_code": account_code},
        "rows": serialize_doc(rows),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "count": len(rows),
    }


# ═══════════════════════════════════════════════════════════════════════════
# F3: CASH FLOW STATEMENT (direct method via cash_movements ledger)
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/cash-flow")
async def cash_flow(
    request: Request,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """F3: Cash Flow Statement (metode direct).
    2026-11-02 (K19): kedua tampilan dari buku besar — `activities` per kategori `source_module` jurnal
    yang menyentuh akun kas/bank (Operating/Investing/Financing), `by_account` per akun lawan dengan tag
    OPR/INV/PND akun (ala sheet Arus-K). Kas awal & akhir keduanya = saldo GL akun kas/bank.
    """
    await require_auth(request)
    db = get_db()
    today = date.today().isoformat()
    return await _cash_flow_data(db, from_date or f"{today[:4]}-01-01", to_date or today)


@router.get("/cash-mutations")
async def cash_mutations(
    request: Request,
    account_id: Optional[str] = Query(None),
    gl_account_code: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """2026-11-02 (K19): daftar mutasi rekening Kas & Bank DITURUNKAN DARI GL (baris jurnal akun
    rekening) — dipakai panel "Mutasi" di layar Kas & Bank. `rahaza_cash_movements` hanya metadata."""
    await require_auth(request)
    db = get_db()
    acc = None
    if account_id:
        acc = await db.rahaza_cash_accounts.find_one({"id": account_id}, {"_id": 0})
        if not acc:
            raise HTTPException(404, "Rekening tidak ditemukan.")
    code = (acc or {}).get("gl_account_code") or gl_account_code
    if not code:
        raise HTTPException(400, "Rekening belum tertaut akun GL — tekan 'Sinkron Bagan Akun & GL' dulu.")
    from routes.rahaza_posting import cash_mutations_from_gl
    out = await cash_mutations_from_gl(db, code, from_date, to_date, account_id=(acc or {}).get("id"))
    out["account"] = {"id": (acc or {}).get("id"), "code": (acc or {}).get("code") or code,
                      "name": (acc or {}).get("name")}
    return serialize_doc(out)


INVESTING_CATS = {"asset_purchase", "asset_sale", "investment"}
FINANCING_CATS = {"loan_proceeds", "loan_repayment", "owner_investment", "owner_withdrawal", "dividend", "opening_balance"}


def _bucket(cat: str) -> str:
    c = (cat or "").lower()
    if c in INVESTING_CATS:
        return "investing"
    if c in FINANCING_CATS:
        return "financing"
    return "operating"  # default: ar_payment, ap_payment, expense, payroll, …


async def _cash_flow_data(db, from_date: str, to_date: str) -> dict:
    """2026-11-02 (K19): tampilan "Per Kategori" DITURUNKAN DARI GL — baris buku besar akun kas/bank
    (`core.fin_statements.cash_account_codes`, sama dengan tampilan Per Akun), kategori dari
    `source_module` jurnal (routes.rahaza_posting.cash_category). Dulu Σ `rahaza_cash_movements`:
    transfer/kasbon/payroll/jurnal manual/impor tidak ada, kas awal = saldo GL HARI INI − Σ mutasi
    (audit No.46: kas awal 1.700.000 padahal riil 0). Kini kas awal/akhir = saldo GL per tanggal.
    Jurnal `opening_balance` (saldo awal go-live) = kas awal, bukan arus periode (sama dgn Per Akun)."""
    from core.fin_statements import cash_account_codes
    from routes.rahaza_posting import cash_accounts_with_gl, cash_category, cash_category_label
    codes = sorted(await cash_account_codes(db))
    activities = {"operating": {}, "investing": {}, "financing": {}}
    if codes:
        pipe = [{"$match": {"account_code": {"$in": codes}, "date": {"$gte": from_date, "$lte": to_date},
                            "source_module": {"$ne": "opening_balance"}}},
                {"$group": {"_id": {"$ifNull": ["$source_module", "other"]}, "debit": {"$sum": "$debit"},
                            "credit": {"$sum": "$credit"}, "count": {"$sum": 1}}}]
        async for r in db.rahaza_journal_lines.aggregate(pipe):
            cat = cash_category(r.get("_id"))
            slot = activities[_bucket(cat)].setdefault(cat, {"inflow": 0.0, "outflow": 0.0, "net": 0.0, "count": 0,
                                                              "sources": set()})
            d, c = float(r.get("debit") or 0), float(r.get("credit") or 0)
            slot["inflow"] += d
            slot["outflow"] += c
            slot["net"] += d - c
            slot["count"] += int(r.get("count") or 0)
            slot["sources"].add(r.get("_id") or "other")

    def _format_bucket(b):
        rows = [{"category": cat, "label": cash_category_label(cat), "inflow": round(s["inflow"], 2),
                 "outflow": round(s["outflow"], 2), "net": round(s["net"], 2), "count": s["count"],
                 "source_modules": sorted(s["sources"])} for cat, s in b.items()]
        rows.sort(key=lambda r: r["category"])
        return {"items": rows, "total": round(sum(r["net"] for r in rows), 2)}

    operating, investing, financing = (_format_bucket(activities[k]) for k in ("operating", "investing", "financing"))
    net_change = round(operating["total"] + investing["total"] + financing["total"], 2)

    # Kas awal = saldo GL akun kas sebelum from_date + jurnal saldo awal go-live s.d. to_date (rumus Per Akun)
    opening_cash = 0.0
    if codes:
        async for r in db.rahaza_journal_lines.aggregate([
            {"$match": {"account_code": {"$in": codes},
                        "$or": [{"date": {"$lt": from_date}}, {"source_module": "opening_balance", "date": {"$lte": to_date}}]}},
                {"$group": {"_id": None, "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}}]):
            opening_cash = round(float(r.get("d") or 0) - float(r.get("c") or 0), 2)
    closing_cash = round(opening_cash + net_change, 2)
    cash_accs = await cash_accounts_with_gl(db, {})

    by_account = await compute_cash_flow_by_account(db, from_date, to_date)

    return {
        "meta": {"from": from_date, "to": to_date, "method": "direct", "category_source": "gl_source_module"},
        "activities": {
            "operating": {"label": "Aktivitas Operasi", **operating},
            "investing": {"label": "Aktivitas Investasi", **investing},
            "financing": {"label": "Aktivitas Pendanaan", **financing},
        },
        "totals": {
            "operating": operating["total"],
            "investing": investing["total"],
            "financing": financing["total"],
            "net_change_in_cash": net_change,
            "opening_cash": round(opening_cash, 2),
            "closing_cash": closing_cash,
        },
        "cash_accounts": [
            {"id": a.get("id"), "code": a.get("code"), "name": a.get("name"), "type": a.get("type"), "balance": round(float(a.get("balance") or 0), 2)}
            for a in cash_accs
        ],
        "by_account": by_account,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# M-01 (Iter 116) — Nilai Persediaan Barang Jadi vs saldo GL 1-1404
# 2026-11-02 (owner No.26a): nilai = Σ stok bernilai × WAC (bukan lagi lapisan FIFO)
# ═══════════════════════════════════════════════════════════════════════════════
FG_INVENTORY_ACCOUNT = "1-1404"


@router.get("/fg-inventory-valuation")
async def fg_inventory_valuation(request: Request, as_of: Optional[str] = Query(None)):
    """Nilai persediaan FG per SKU = stok FG milik DA yang bernilai × WAC (core/fg_cost_layers),
    dibandingkan dengan saldo GL 1-1404 sampai `as_of` (default hari ini). Stok & WAC =
    posisi SAAT INI; GL = per tanggal. Selisih dijelaskan: penerimaan bernilai yang belum
    berjurnal (WIP→FG belum diposting) dan stok tanpa biaya (WAC 0 / penerimaan Rp 0)."""
    await require_auth(request)
    db = get_db()
    return await compute_fg_valuation(db, as_of or date.today().isoformat())


def fg_valuation_status(*, difference: float, unexplained: float, uncosted_qty: float) -> dict:
    """Status rekonsiliasi Nilai Persediaan FG (fungsi murni, 2026-11-02 / P-1).

    Dulu `reconciled`/`explained` hanya melihat selisih rupiah. Barang FG yang stoknya
    ada tetapi biayanya Rp 0 (`uncosted_qty` > 0) membuat nilai stok DAN GL sama-sama
    0 → selisih 0 → "aman", padahal nilainya macet di WIP dan HPP jualnya 0. Sekarang
    stok tanpa biaya = TIDAK beres dan tidak terjelaskan, supaya alarm harian menyala.
    """
    issues = []
    if uncosted_qty > 0:
        issues.append(f"{uncosted_qty:g} pcs FG tanpa biaya (WAC 0 atau penerimaan Rp 0) — nilainya belum "
                      "pindah dari WIP dan HPP penjualannya 0. Periksa BOM & biaya jahit SPK batch tersebut.")
    if abs(unexplained) >= 1:
        issues.append(f"Selisih Rp {unexplained:,.0f} antara Σ stok × WAC dan GL 1-1404 belum terjelaskan.")
    no_uncosted = not (uncosted_qty > 0)
    return {"reconciled": abs(difference) < 1 and no_uncosted,
            "explained": abs(unexplained) < 1 and no_uncosted,
            "issues": issues}


def fg_valuation_row(*, qty: float, wac: float, layers: list, wac_initialized: bool) -> dict:
    """Satu baris laporan (fungsi murni). `layers` = semua lapisan SKU ini (jejak batch).

    * nilai = qty bernilai × WAC (Σ stok × WAC, keputusan owner No.26a);
    * `unposted_value` = penerimaan bernilai tanpa JE 1-1404 (semua lapisan, termasuk yang
      jejaknya sudah habis — nilainya sudah masuk WAC tetapi tidak pernah masuk GL);
    * `uncosted_qty` = stok tanpa biaya: seluruh stok bila WAC 0, selain itu lapisan Rp 0
      yang masih tersisa (penerimaan Rp 0 tidak mengubah WAC — aturan bahan)."""
    open_rows = [ly for ly in layers if float(ly.get("qty_remaining") or 0) > 0]
    layer_qty = sum(float(ly.get("qty_remaining") or 0) for ly in open_rows)
    trail_value = sum(float(ly.get("qty_remaining") or 0) * float(ly.get("unit_cost") or 0) for ly in open_rows)
    zero_qty = sum(float(ly.get("qty_remaining") or 0) for ly in open_rows if float(ly.get("unit_cost") or 0) <= 0)
    unposted = [ly for ly in layers if not ly.get("gl_je_id") and float(ly.get("total_cost") or 0) > 0]
    if qty > 0 and wac <= 0:
        uncosted = qty
    else:
        uncosted = min(zero_qty, max(qty, 0.0))
    value = round(qty * wac, 2)
    return {"stock_qty": round(qty, 2), "wac_unit_cost": round(wac, 4), "value": value,
            "wac_initialized": wac_initialized,
            # nama lama dipertahankan untuk layar (RahazaFGValuationModule): nilainya kini WAC
            "avg_unit_cost": round(wac, 2), "layer_value": value,
            "layer_qty": round(layer_qty, 2), "qty_diff": round(qty - layer_qty, 2),
            "trail_value": round(trail_value, 2),
            "unposted_layers": len(unposted),
            "unposted_value": round(sum(float(ly.get("total_cost") or 0) for ly in unposted), 2),
            "uncosted_qty": round(uncosted, 2), "layers_open": len(open_rows)}


async def compute_fg_valuation(db, as_of_date: str) -> dict:
    """Inti laporan M-01 — dipakai endpoint di atas DAN cron `fg-valuation-check`."""
    from core import fg_cost_layers as fcl
    from core.catalog_stock import blocked_location_ids
    from core.stock_schema import read_qty
    layers = await db.fg_cost_layers.find({}, {"_id": 0}).to_list(50000)
    by_mat: dict = {}
    for ly in layers:
        by_mat.setdefault(ly.get("material_id") or "", []).append(ly)
    fg_ids = [m["id"] async for m in db.rahaza_materials.find({"type": "fg"}, {"_id": 0, "id": 1})]
    cat_ids = [r["_id"] for r in await db.rahaza_material_stock.aggregate([
        {"$match": {"inventory_category": "fg_internal"}}, {"$group": {"_id": "$material_id"}}]).to_list(50000)]
    ids = sorted({i for i in list(by_mat) + fg_ids + cat_ids if i})
    mats = {m["id"]: m async for m in db.rahaza_materials.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1, fcl.WAC_FIELD: 1, fcl.WAC_COMPONENTS: 1,
                               "wac_source": 1})}
    blocked = await blocked_location_ids(db)
    qty_by: dict = {}
    phys_by: dict = {}
    async for s in db.rahaza_material_stock.find({"material_id": {"$in": ids}}, {"_id": 0}):
        mid = s.get("material_id")
        phys_by[mid] = phys_by.get(mid, 0.0) + read_qty(s)
        if fcl.is_valued_row(s, blocked):
            qty_by[mid] = qty_by.get(mid, 0.0) + read_qty(s)

    rows = []
    for mid in ids:
        info = mats.get(mid) or {}
        ly = by_mat.get(mid) or []
        initialized = isinstance(info.get(fcl.WAC_COMPONENTS), dict)
        # FG yang belum pernah dinilai WAC: pratinjau WAC awal (rumus migrasi), tanpa menulis
        wac = (float(info.get(fcl.WAC_FIELD) or 0) if initialized
               else fcl.initial_wac_from_layers(ly)["unit_cost"])
        qty = float(qty_by.get(mid, 0.0))
        r = fg_valuation_row(qty=qty, wac=wac, layers=ly, wac_initialized=initialized)
        if not (r["stock_qty"] or r["layer_qty"] or r["unposted_value"]):
            continue
        r.update({"material_id": mid, "code": info.get("code") or (ly[0].get("sku") if ly else "") or mid[:8],
                  "name": info.get("name") or "", "sku": info.get("code") or "",
                  "physical_qty": round(phys_by.get(mid, 0.0), 2),
                  "wac_source": info.get("wac_source") or ("preview_from_layers" if ly else "none")})
        rows.append(r)
    rows.sort(key=lambda r: -abs(r["value"]))

    agg = await _aggregate_by_account(db, {"date": {"$lte": as_of_date}, "account_code": FG_INVENTORY_ACCOUNT})
    a = agg.get(FG_INVENTORY_ACCOUNT) or {}
    gl_balance = round(float(a.get("debit") or 0) - float(a.get("credit") or 0), 2)
    value = round(sum(r["value"] for r in rows), 2)
    unposted_value = round(sum(r["unposted_value"] for r in rows), 2)
    uncosted_qty = round(sum(r["uncosted_qty"] for r in rows), 2)
    difference = round(value - gl_balance, 2)
    explained = round(difference - unposted_value, 2)
    status = fg_valuation_status(difference=difference, unexplained=explained, uncosted_qty=uncosted_qty)
    return {
        "as_of": as_of_date, "gl_account": FG_INVENTORY_ACCOUNT, "basis": "wac",
        "rows": rows,
        "totals": {"stock_qty": round(sum(r["stock_qty"] for r in rows), 2),
                   "layer_qty": round(sum(r["layer_qty"] for r in rows), 2),
                   "value": value, "layer_value": value, "gl_balance": gl_balance, "difference": difference,
                   "unposted_layers": sum(r["unposted_layers"] for r in rows), "unposted_value": unposted_value,
                   "uncosted_qty": uncosted_qty, "unexplained_difference": explained,
                   "wac_not_initialized": sum(1 for r in rows if not r["wac_initialized"])},
        "reconciled": status["reconciled"],
        "explained": status["explained"],
        "issues": status["issues"],
        "notes": [
            "Nilai = Σ stok FG milik DA yang bernilai (semua lokasi kecuali karantina/terblokir) × WAC "
            "(rata-rata bergerak, keputusan owner No.26a). Kolom lama 'layer_value'/'avg_unit_cost' kini berisi angka WAC.",
            "Saldo GL = Dr − Cr akun 1-1404 sampai tanggal as_of.",
            "unposted_value = penerimaan bernilai yang belum punya JE WIP→FG (jalankan Backfill WIP→FG).",
            "uncosted_qty = stok tanpa biaya (WAC 0, atau penerimaan Rp 0 yang masih ada di jejak lapisan).",
            "layer_qty = sisa jejak lapisan batch (analitik, bukan dasar nilai); qty_diff = stok − jejak.",
        ],
    }
