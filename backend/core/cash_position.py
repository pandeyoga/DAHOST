"""Posisi kas & arus kas dari BUKU BESAR — satu rumus untuk Beranda Keuangan & Prediksi Kas (2026-11-04).

Kenapa ada: Prediksi Kas membaca `rahaza_cash_movements` (catatan mutasi lama, tidak memuat jurnal manual,
impor jurnal, gaji, transfer) dan tidak tahu saldo kas sama sekali. Sejak K19 (2026-11-02) mutasi rekening
diturunkan dari baris jurnal akun kas/bank, jadi angka di sini sama dengan Rekening & Mutasi dan Arus Kas.

  · saldo      = Σ debit − Σ kredit semua baris jurnal akun kas/bank (`core.fin_statements.cash_account_codes`)
  · masuk/keluar periode = baris akun kas/bank pada rentang tanggal, TANPA transfer antar rekening dan
    jurnal saldo awal (uang tidak benar-benar masuk/keluar perusahaan).
"""
from __future__ import annotations

INTERNAL_MODULES = ("bank_transfer", "opening_balance")


async def cash_position(db, from_date: str | None = None, to_date: str | None = None) -> dict:
    from core.fin_statements import cash_account_codes
    codes = sorted(await cash_account_codes(db))
    if not codes:
        return {"balance": 0.0, "cash_in": 0.0, "cash_out": 0.0, "net": 0.0, "accounts": 0}
    bal_match: dict = {"account_code": {"$in": codes}}
    if to_date:
        bal_match["date"] = {"$lte": to_date}
    balance = 0.0
    async for r in db.rahaza_journal_lines.aggregate([
            {"$match": bal_match},
            {"$group": {"_id": None, "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}}]):
        balance = float(r.get("d") or 0) - float(r.get("c") or 0)
    flow_in = flow_out = 0.0
    if from_date:
        rng = {"$gte": from_date}
        if to_date:
            rng["$lte"] = to_date
        async for r in db.rahaza_journal_lines.aggregate([
                {"$match": {"account_code": {"$in": codes}, "date": rng,
                            "source_module": {"$nin": list(INTERNAL_MODULES)}}},
                {"$group": {"_id": None, "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}}]):
            flow_in, flow_out = float(r.get("d") or 0), float(r.get("c") or 0)
    return {"balance": round(balance, 2), "cash_in": round(flow_in, 2), "cash_out": round(flow_out, 2),
            "net": round(flow_in - flow_out, 2), "accounts": len(codes)}
