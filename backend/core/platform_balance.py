"""platform_balance — saldo toko di marketplace = piutang toko ke platform.

Dua tahap yang menjadi satu-satunya pintu Marketing → Finance (keputusan pemilik):
  1. `marketing_settlements`            — dana DILEPAS platform ke saldo toko
                                          (Dr Piutang Toko / Dr potongan / Cr Pendapatan)
  2. `marketing_platform_withdrawals`   — saldo DITARIK ke rekening bank
                                          (Dr Bank / Cr Piutang Toko)
Saldo yang bisa dicairkan = Σ dana dilepas − Σ penarikan. Omzet input Marketing
(sales harian / impor pesanan) TIDAK ikut ke sini — hanya laporan.

2026-11-02 (K3, keputusan owner) — saldo TERSEDIA UNTUK PENARIKAN hanya dihitung
dari dana dilepas yang jurnalnya SUDAH DIPOSTING (sudah ada di buku besar sub-akun
toko). Dulu pagar membaca saldo dokumen: penarikan Rp 300.000 lolos & diposting
padahal pencairannya belum dijurnal ⇒ GL 1-1303-TTK-01 = −300.000 (audit S-1).
"""
from __future__ import annotations

from typing import Iterable, Optional

SETTLEMENTS = "marketing_settlements"
WITHDRAWALS = "marketing_platform_withdrawals"


def receivable_code(account: dict) -> str:
    return ((account.get("ar_account_code") or account.get("coa_receivable_code") or "").strip())


async def _sum_by_account(db, coll: str, field: str, match: dict) -> dict:
    rows = await db[coll].aggregate([
        {"$match": match},
        {"$group": {"_id": "$account_id", "total": {"$sum": f"${field}"}, "count": {"$sum": 1}}},
    ]).to_list(2000)
    return {r["_id"]: r for r in rows if r.get("_id")}


async def platform_balances(db, account_ids: Optional[Iterable[str]] = None) -> list:
    aq = {} if account_ids is None else {"id": {"$in": list(account_ids)}}
    accounts = await db.marketing_platform_accounts.find(
        aq, {"_id": 0, "id": 1, "account_code": 1, "account_name": 1, "platform": 1, "status": 1,
             "ar_account_code": 1, "coa_receivable_code": 1, "coa_cash_code": 1,
             "coa_cash_source": 1}).to_list(2000)
    ids = [a["id"] for a in accounts]
    match = {"account_id": {"$in": ids}}
    released = await _sum_by_account(db, SETTLEMENTS, "net_payout", match)
    withdrawn = await _sum_by_account(db, WITHDRAWALS, "amount", match)

    codes = [c for c in (receivable_code(a) for a in accounts) if c]
    gl = {}
    if codes:
        for r in await db.rahaza_journal_lines.aggregate([
            {"$match": {"account_code": {"$in": codes}}},
            {"$group": {"_id": "$account_code",
                        "bal": {"$sum": {"$subtract": ["$debit", "$credit"]}}}},
        ]).to_list(2000):
            gl[r["_id"]] = round(float(r.get("bal") or 0), 2)

    out = []
    for a in accounts:
        rel = released.get(a["id"], {})
        wd = withdrawn.get(a["id"], {})
        code = receivable_code(a)
        rel_t = round(float(rel.get("total") or 0), 2)
        wd_t = round(float(wd.get("total") or 0), 2)
        # 2026-11-02 (K3) — bagian dana dilepas yang sudah diposting & saldo yang boleh ditarik
        split = await settlement_posting_split(db, a["id"])
        out.append({
            "account_id": a["id"], "account_code": a.get("account_code"),
            "account_name": a.get("account_name"), "platform": a.get("platform"),
            "status": a.get("status"),
            "receivable_code": code or None, "cash_code": (a.get("coa_cash_code") or "").strip() or None,
            "released_total": rel_t, "released_count": int(rel.get("count") or 0),
            "withdrawn_total": wd_t, "withdrawn_count": int(wd.get("count") or 0),
            "balance": round(rel_t - wd_t, 2),
            "released_posted_total": split["posted_total"],
            "released_unposted_total": split["unposted_total"],
            "released_unposted_count": len(split["unposted"]),
            "withdrawable_balance": round(split["posted_total"] - wd_t, 2),
            "gl_balance": gl.get(code, 0.0) if code else None,
            # 2026-11-02 (K4) — sumber rekening: `default` = bawaan 1-1201 belum diatur Finance
            "cash_source": a.get("coa_cash_source") or None,
        })
    out.sort(key=lambda x: -x["balance"])
    return out


async def available_balance(db, account_id: str, exclude_withdrawal_id: str = "") -> float:
    """Saldo DOKUMEN (Σ dana dilepas − Σ penarikan) — termasuk pencairan belum dijurnal.
    Untuk pagar penarikan pakai :func:`withdrawable_balance` (K3)."""
    rel = await _sum_by_account(db, SETTLEMENTS, "net_payout", {"account_id": account_id})
    wq: dict = {"account_id": account_id}
    if exclude_withdrawal_id:
        wq["id"] = {"$ne": exclude_withdrawal_id}
    wd = await _sum_by_account(db, WITHDRAWALS, "amount", wq)
    return round(float(rel.get(account_id, {}).get("total") or 0)
                 - float(wd.get(account_id, {}).get("total") or 0), 2)


async def _posted_je_ids(db, je_ids) -> set:
    ids = sorted({i for i in (je_ids or []) if i})
    if not ids:
        return set()
    rows = await db.rahaza_journal_entries.find(
        {"id": {"$in": ids}, "status": "posted"}, {"_id": 0, "id": 1}).to_list(len(ids) + 10)
    return {r["id"] for r in rows}


async def settlement_posting_split(db, account_id: str) -> dict:
    """Pecah dana dilepas satu toko: SUDAH diposting vs BELUM (belum dijurnal/draf/void).

    Status jurnal dibaca dari `rahaza_journal_entries` (bukan cap `je_status` di dokumen)
    karena jurnal bisa diposting/di-void dari layar Jurnal Umum tanpa memperbarui capnya.
    """
    rows = await db[SETTLEMENTS].find(
        {"account_id": account_id},
        {"_id": 0, "id": 1, "settlement_id": 1, "settlement_date": 1, "net_payout": 1,
         "je_id": 1, "je_number": 1}).to_list(20000)
    posted_ids = await _posted_je_ids(db, [r.get("je_id") for r in rows])
    posted, pending = 0.0, []
    for r in rows:
        amt = round(float(r.get("net_payout") or 0), 2)
        if r.get("je_id") and r["je_id"] in posted_ids:
            posted += amt
        elif amt:
            pending.append({"id": r.get("id"), "settlement_id": r.get("settlement_id"),
                            "settlement_date": r.get("settlement_date"), "net_payout": amt,
                            "je_number": r.get("je_number"),
                            "state": "draf" if r.get("je_id") else "belum dijurnal"})
    pending.sort(key=lambda x: str(x.get("settlement_date") or ""))
    return {"posted_total": round(posted, 2),
            "unposted_total": round(sum(p["net_payout"] for p in pending), 2),
            "unposted": pending}


async def withdrawable_balance(db, account_id: str, exclude_withdrawal_id: str = "") -> dict:
    """K3 — saldo yang BOLEH ditarik = Σ dana dilepas yang SUDAH DIPOSTING − Σ penarikan
    (semua penarikan tercatat, berjurnal atau belum, kecuali ``exclude_withdrawal_id``).

    → ``{"available", "document_available", "posted_total", "unposted_total",
         "unposted": [...], "withdrawn_total"}``
    """
    split = await settlement_posting_split(db, account_id)
    # saldo dokumen (Σ dana dilepas − Σ penarikan) DIKURANGI dana dilepas yang belum
    # diposting = Σ dana dilepas yang sudah diposting − Σ penarikan.
    doc_avail = await available_balance(db, account_id, exclude_withdrawal_id)
    return {"available": round(doc_avail - split["unposted_total"], 2),
            "document_available": round(doc_avail, 2),
            "withdrawn_total": round(split["posted_total"] + split["unposted_total"] - doc_avail, 2),
            **split}
