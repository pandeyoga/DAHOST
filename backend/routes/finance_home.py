"""Beranda Keuangan — `GET /api/finance/home` (2026-11-04, keputusan owner, audit Keuangan tahap 4).

Menggantikan dua layar: Dashboard Keuangan (kumpulan tautan + kartu yang angkanya dari sumber berbeda)
dan Rekap Keuangan (6 rumus hutang/piutang sendiri). Semua angka di sini DIPINJAM dari rumus yang
sudah dipakai laporan, tidak ada rumus baru:
  · kas & bank           → `core.cash_position` (buku besar, sama dengan Rekening & Mutasi / Arus Kas)
  · saldo toko           → saldo buku besar akun 1-1303-* (piutang channel per toko)
  · hutang               → `core.payables` (tagihan pemasok + CMT, sama dengan Umur Hutang)
  · piutang              → faktur penjualan terbuka (`rahaza_ar_invoices.balance`, sama dengan Umur Piutang)
  · laba bulan ini/lalu  → `compute_profit_loss` (sama dengan layar Laba Rugi)
  · dana marketplace     → `marketing_settlements` bulan ini (sama dengan menu Marketplace)
  · pekerjaan tertunda   → hitungan per dokumen + menu tujuan.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Request

from auth import require_auth, serialize_doc
from database import get_db
from utils.waktu import today_wib
from core.entities import DA, ALL, entity_from_request, entity_match, entity_short
from core.platform_balance import SETTLEMENTS  # 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)

router = APIRouter(prefix="/api/finance", tags=["finance-home"])

AR_OPEN = ("sent", "issued", "partial", "partial_paid", "overdue")
STORE_PREFIX = "1-1303"


def _month_bounds(d: date) -> tuple[str, str]:
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start.isoformat(), (nxt - timedelta(days=1)).isoformat()


async def _store_balances(db, entity: str = DA) -> dict:
    if entity not in (DA, ALL):
        return {"total": 0.0, "stores": []}   # Tahap 8: semua toko milik CV Dewi Aditya
    names = {a["code"]: a.get("name") or a["code"] async for a in db.rahaza_coa_accounts.find(
        {"code": {"$regex": f"^{STORE_PREFIX}"}}, {"_id": 0, "code": 1, "name": 1})}
    rows = []
    async for r in db.rahaza_journal_lines.aggregate([
            {"$match": {"account_code": {"$regex": f"^{STORE_PREFIX}-"}, **entity_match(entity)}},
            {"$group": {"_id": "$account_code", "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}}]):
        bal = round(float(r.get("d") or 0) - float(r.get("c") or 0), 2)
        if abs(bal) >= 0.5:
            name = str(names.get(r["_id"]) or r["_id"]).replace("Piutang Channel — ", "")
            rows.append({"code": r["_id"], "name": name, "balance": bal})
    rows.sort(key=lambda x: -x["balance"])
    return {"total": round(sum(r["balance"] for r in rows), 2), "stores": rows}


async def _receivables(db, today: date, entity: str = DA) -> dict:
    t, soon_to = today.isoformat(), (today + timedelta(days=7)).isoformat()
    total = overdue = due7 = 0.0
    n_open = n_overdue = n_due7 = 0
    async for inv in db.rahaza_ar_invoices.find({"status": {"$in": list(AR_OPEN)}, **entity_match(entity)},
                                                {"_id": 0, "balance": 1, "due_date": 1}):
        bal = float(inv.get("balance") or 0)
        if bal <= 0.5:
            continue
        due = str(inv.get("due_date") or "")[:10]
        total += bal
        n_open += 1
        if due and due < t:
            overdue += bal
            n_overdue += 1
        elif due and due <= soon_to:
            due7 += bal
            n_due7 += 1
    return {"total": round(total, 2), "count": n_open, "overdue": round(overdue, 2), "overdue_count": n_overdue,
            "due_7d": round(due7, 2), "due_7d_count": n_due7}


async def _payables(db, today: date, entity: str = DA) -> dict:
    from core.payables import aging, open_payable_rows
    ag = aging(await open_payable_rows(db, entity=entity), today)
    t, soon_to = today.isoformat(), (today + timedelta(days=7)).isoformat()
    det = ag["details"]
    over = [r for r in det if r["days_overdue"] > 0]
    soon = [r for r in det if t <= r["due_date"] <= soon_to]
    return {"total": ag["total"], "count": len(det), "overdue": ag["overdue"], "overdue_count": len(over),
            "due_7d": round(sum(r["balance"] for r in soon)), "due_7d_count": len(soon),
            "unposted_cmt": ag["unposted_total"], "unposted_cmt_count": len(ag["unposted"])}


async def _profit(db, today: date, entity: str = DA) -> dict:
    from routes.rahaza_fin_reports import compute_profit_loss
    m_from, _ = _month_bounds(today)
    last = today.replace(day=1) - timedelta(days=1)
    l_from, l_to = _month_bounds(last)
    cur = (await compute_profit_loss(db, m_from, today.isoformat(), entity))["totals"]
    prev = (await compute_profit_loss(db, l_from, l_to, entity))["totals"]
    pick = ("revenue", "gross_profit", "expense", "net_income")
    return {"this_month": {k: cur.get(k, 0) for k in pick}, "last_month": {k: prev.get(k, 0) for k in pick},
            "this_month_from": m_from, "last_month_from": l_from, "last_month_to": l_to}


async def _marketplace(db, today: date, entity: str = DA) -> dict:
    ym = today.strftime("%Y-%m")
    s = {}
    if entity not in (DA, ALL):   # Tahap 8: semua toko marketplace milik CV Dewi Aditya
        return {"month": ym, "count": 0, "gross_sales": 0.0, "deductions": 0.0, "net_payout": 0.0, "deduction_pct": 0.0}
    async for r in db[SETTLEMENTS].aggregate([
            {"$match": {"settlement_date": {"$regex": f"^{ym}"}}},
            {"$group": {"_id": None, "n": {"$sum": 1}, "gross": {"$sum": "$gross_sales"},
                        "ded": {"$sum": "$total_deductions"}, "net": {"$sum": "$net_payout"}}}]):
        s = r
    gross = float(s.get("gross") or 0)
    ded = float(s.get("ded") or 0)
    return {"month": ym, "count": int(s.get("n") or 0), "gross_sales": round(gross, 2),
            "deductions": round(ded, 2), "net_payout": round(float(s.get("net") or 0), 2),
            "deduction_pct": round(ded / gross * 100, 1) if gross else 0.0}


async def _todo(db, today: date, ar: dict, ap: dict, entity: str = DA) -> list[dict]:
    """Pekerjaan tertunda — hanya yang > 0, urut dari yang paling mendesak."""
    t = today.isoformat()
    last_month_end = (today.replace(day=1) - timedelta(days=1))
    last_period = last_month_end.strftime("%Y-%m")
    items: list[dict] = []

    def add(key, n, label, module, tab=None, amount=None, level="info"):
        if n:
            items.append({"key": key, "count": n, "label": label, "module": module, "tab": tab,
                          "amount": amount, "level": level})

    add("ap_overdue", ap["overdue_count"], "tagihan pemasok/CMT lewat jatuh tempo", "fin-ap-hub", "aging",
        ap["overdue"], "danger")
    add("ar_overdue", ar["overdue_count"], "faktur penjualan lewat jatuh tempo", "fin-ar-hub", "aging",
        ar["overdue"], "danger")
    add("ap_due7", ap["due_7d_count"], "tagihan jatuh tempo 7 hari ke depan", "fin-ap-hub", "aging", ap["due_7d"],
        "warning")
    add("cmt_unposted", ap["unposted_cmt_count"], "tagihan CMT belum dijurnal", "fin-ap-hub", "bills",
        ap["unposted_cmt"], "warning")
    add("settle_unverified", await db[SETTLEMENTS].count_documents({"math_verified": False}) if entity in (DA, ALL) else 0,
        "laporan dana marketplace masih ada selisih hitungan", "fin-marketplace-settlement", "settlements",
        level="warning")
    add("kasbon", await db.dewi_kasbon_requests.count_documents({"status": "hr_approved"}),
        "kasbon disetujui HR menunggu dicairkan", "fin-kasbon", "kasbon", level="warning")
    add("advance_overdue", await db.rahaza_petty_cash_txns.count_documents(
        {"txn_type": "advance", "open_amount": {"$gt": 0.009}, "due_date": {"$lt": t, "$ne": None}}),
        "uang muka karyawan lewat batas nota", "fin-kasbon", "advances", level="warning")
    add("travel", await db.employee_travel_settlements.count_documents({"status": "approved"}),
        "penyelesaian perjalanan dinas siap diposting", "fin-settlement-queue", level="info")
    add("edit_req", await db.invoice_edit_requests.count_documents({"status": "Pending"}),
        "permintaan perubahan faktur menunggu persetujuan", "fin-approval", level="info")
    add("je_draft", await db.rahaza_journal_entries.count_documents({"status": "draft", **entity_match(entity)}),
        "jurnal masih draf", "fin-journal-hub", "list", level="info")
    # rekonsiliasi bank bulan lalu: rekening bank aktif yang belum punya sesi disetujui
    banks = [a async for a in db.rahaza_cash_accounts.find({"type": "bank", "active": {"$ne": False}, **entity_match(entity)},
                                                          {"_id": 0, "id": 1})]
    if banks:
        done = set(await db.bank_recon_sessions.distinct(
            "cash_account_id", {"period": last_period, "status": "approved"}))
        add("recon", len([b for b in banks if b["id"] not in done]),
            f"rekening bank belum direkonsiliasi untuk {last_period}", "fin-bank-recon", level="info")
    add("period", await db.rahaza_periods.count_documents({"status": "open", "period_code": {"$lte": last_period},
                                                           **entity_match(entity)}),
        f"periode sampai {last_period} belum ditutup", "fin-acctg-adjust-hub", "periods", level="info")
    order = {"danger": 0, "warning": 1, "info": 2}
    items.sort(key=lambda x: order.get(x["level"], 3))
    return items


@router.get("/home")
async def finance_home(request: Request):
    await require_auth(request)
    db = get_db()
    from core.cash_position import cash_position
    ent = entity_from_request(request, allow_all=True)   # Tahap 8: DA | SMU | ALL (gabungan)
    today = today_wib()
    m_from, _ = _month_bounds(today)
    cash = await cash_position(db, m_from, today.isoformat(), entity=ent)
    ar = await _receivables(db, today, ent)
    ap = await _payables(db, today, ent)
    return serialize_doc({
        "today": today.isoformat(),
        "entity": ent, "entity_label": entity_short(ent),
        "cash": cash,
        "stores": await _store_balances(db, ent),
        "receivables": ar,
        "payables": ap,
        "profit": await _profit(db, today, ent),
        "marketplace": await _marketplace(db, today, ent),
        "todo": await _todo(db, today, ar, ap, ent),
    })
