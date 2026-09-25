"""payout_banks — daftar rekening kas/bank/e-wallet tujuan penarikan saldo platform.

SSOT: `fin_statements.cash_account_codes` (leaf di bawah 1-1100/1-1200, flag is_cash/is_bank,
atau `gl_account_code` master Kas & Bank). Dulu pemilih hanya membaca COA ber-`flags`,
sehingga rekening turunan (BRI/BCA per entitas, Mandiri, e-wallet) tidak muncul.
"""
from __future__ import annotations

from core.fin_statements import cash_account_codes


async def bank_options(db) -> list:
    codes = await cash_account_codes(db)
    if not codes:
        return []
    coa = {a["code"]: a async for a in db.rahaza_coa_accounts.find(
        {"code": {"$in": list(codes)}},
        {"_id": 0, "code": 1, "name": 1, "is_group": 1, "active": 1, "parent_code": 1})}
    cash = {c["gl_account_code"]: c async for c in db.rahaza_cash_accounts.find(
        {"gl_account_code": {"$in": list(codes)}},
        {"_id": 0, "gl_account_code": 1, "name": 1, "bank_name": 1, "account_number": 1,
         "account_holder": 1, "active": 1})}
    out = []
    for code in sorted(codes):
        a = coa.get(code)
        if not a or a.get("is_group") or not a.get("active", True):
            continue
        c = cash.get(code) or {}
        if c and c.get("active") is False:
            continue
        out.append({
            "code": code, "name": a.get("name") or c.get("name") or code,
            "bank_name": c.get("bank_name") or "", "account_number": c.get("account_number") or "",
            "account_holder": c.get("account_holder") or "", "in_cash_master": bool(c),
        })
    return out


async def is_bank_code(db, code: str) -> bool:
    return any(o["code"] == code for o in await bank_options(db))
