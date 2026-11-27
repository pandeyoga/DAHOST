"""Uang muka ke pemasok — bayar di muka (CBD) / DP di PO (owner 27 Nov 2026: "bagaimana jika pembayarannya CBD?").

Masalah: tagihan pemasok baru lahir saat barang diterima (`core.hutang_otomatis`), jadi uang yang dikirim SEBELUM barang
datang tidak punya tempat — satu-satunya jalan dulu jurnal manual (pola yang dulu mengacaukan pembayaran CMT).

Alur:
  1. Bayar di muka (PO disetujui / diterima sebagian): Dr Uang Muka Pembelian (1-1630) / Cr rekening + mutasi kas keluar.
     Total uang muka satu PO ≤ nilai PO (termasuk PPN).
  2. Barang diterima → tagihan otomatis langsung DIPOTONG uang muka PO-nya: Dr Hutang pemasok / Cr Uang Muka Pembelian;
     potongan tercatat sebagai pembayaran tagihan (`rahaza_ap_payments`, sumber `uang_muka`). Tertutup penuh → lunas.
     Sisa uang muka menunggu penerimaan berikutnya dari PO yang sama.
  3. Sisa uang muka yang tidak terpakai → "Kembalikan" (pemasok mengembalikan uang): Dr rekening / Cr Uang Muka Pembelian.
  4. "Batalkan" (salah catat) hanya bila belum terpakai / dikembalikan: jurnal dibatalkan, mutasi kas dihapus.
  PO yang masih punya sisa uang muka tidak bisa dibatalkan (routes.rahaza_po).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException

log = logging.getLogger(__name__)

COLL = "rahaza_ap_advances"
PROFILE = "ap_advance"
AKUN_BAWAAN = "1-1630"            # Uang Muka Pembelian Bahan (bagan akun kanonik)
SUMBER_BAYAR = "ap_advance"       # jurnal bayar di muka: source_ref apadv:<id>
SUMBER_POTONG = "ap_advance_apply"  # jurnal potong tagihan: apadvuse:<id pembayaran>
SUMBER_KEMBALI = "ap_advance_refund"  # jurnal pengembalian: apadvret:<id>
PO_BOLEH_BAYAR = ("approved", "partially_received")
AKTIF, HABIS, BATAL = "aktif", "habis", "batal"
MIN_ALASAN = 10


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def sisa(adv: dict) -> float:
    return round(_f(adv.get("amount")) - _f(adv.get("terpakai")) - _f(adv.get("dikembalikan")), 2)


def _tanggal(v) -> date:
    from utils.waktu import today_wib
    hari = today_wib()
    if not v:
        return hari
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, "Tanggal harus berformat YYYY-MM-DD.")
    if d > hari:
        raise HTTPException(400, f"Tanggal {d.isoformat()} belum terjadi — paling lambat hari ini.")
    return d


async def _akun_uang_muka(db) -> str:
    from routes.rahaza_posting_profiles import role_code
    return await role_code(db, PROFILE, "debit_supplier_advance", AKUN_BAWAAN)


async def _rekening(db, acc_id: str, entity: str, what: str) -> dict:
    if not acc_id:
        raise HTTPException(400, "Pilih rekening kas/bank.")
    acc = await db.rahaza_cash_accounts.find_one({"id": acc_id}, {"_id": 0})
    if not acc:
        raise HTTPException(400, "Rekening tidak ditemukan — pilih lagi dari daftar.")
    if acc.get("active") is False:
        raise HTTPException(400, f"Rekening {acc.get('name') or ''} sudah tidak aktif.")
    if not acc.get("gl_account_code"):
        raise HTTPException(400, f"Rekening {acc.get('name') or ''} belum punya akun buku besar — lengkapi dulu di "
                                 "Keuangan › Rekening & Mutasi.")
    from core.entities import validate_cash_account_owner
    await validate_cash_account_owner(db, acc_id, entity, what=what)
    return acc


def _entity_po(po: dict) -> str:
    from core.entities import entity_of_doc
    return entity_of_doc(po)


async def _jurnal(db, d: date, memo: str, sumber: str, ref: str, lines: list, user: dict, entity: str) -> dict:
    from routes.rahaza_posting import _create_posted_je, _find_existing_je
    ada = await _find_existing_je(db, sumber, ref)
    if ada:
        return {"ok": True, "je_id": ada["id"], "je_number": ada.get("je_number"), "already_posted": True}
    try:
        return await _create_posted_je(db, d, memo, sumber, ref, lines, user, entity=entity)
    except Exception as e:  # noqa: BLE001 — galat jurnal dicatat di dokumen (daftar Belum masuk jurnal)
        log.exception("jurnal uang muka %s %s gagal", sumber, ref)
        return {"ok": False, "error": str(e)}


def _hasil(res: dict) -> dict:
    return {"gl_je_id": res.get("je_id") if res.get("ok") else None,
            "gl_je_number": res.get("je_number") if res.get("ok") else None,
            "post_error": None if res.get("ok") else (res.get("error") or "Jurnal gagal")}


# ── baca ──────────────────────────────────────────────────────────────────────────────────────────────────────────
async def daftar(db, po_id: str) -> dict:
    rows = await db[COLL].find({"po_id": po_id}, {"_id": 0}).sort("created_at", 1).to_list(200)
    for r in rows:
        r["sisa"] = sisa(r) if r.get("status") != BATAL else 0.0
    aktif = [r for r in rows if r.get("status") != BATAL]
    return {"items": rows, "total": round(sum(_f(r.get("amount")) for r in aktif), 2),
            "sisa": round(sum(r["sisa"] for r in aktif), 2)}


async def sisa_po(db, po_id: str) -> float:
    return (await daftar(db, po_id))["sisa"]


# ── 1. bayar di muka ─────────────────────────────────────────────────────────────────────────────────────────────
async def bayar(db, po_id: str, body: dict, user: dict) -> dict:
    po = await db.rahaza_purchase_orders.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO tidak ditemukan.")
    if po.get("status") not in PO_BOLEH_BAYAR:
        raise HTTPException(400, "Uang muka hanya untuk PO yang sudah disetujui dan barangnya belum diterima penuh.")
    amount = round(_f(body.get("amount")), 2)
    if amount <= 0:
        raise HTTPException(400, "Nilai uang muka harus lebih dari 0.")
    entity = _entity_po(po)
    acc = await _rekening(db, body.get("cash_account_id"), entity, "Uang muka pemasok")
    d = _tanggal(body.get("date"))
    batas = round(_f(po.get("grand_total")) or _f(po.get("total_value")), 2)

    # pesan nilai di PO dulu (bandingkan-lalu-tulis) — dua klik bersamaan tidak bisa melewati nilai PO
    for _ in range(5):
        cur = await db.rahaza_purchase_orders.find_one({"id": po_id}, {"_id": 0, "uang_muka_total": 1, "status": 1}) or {}
        sudah = _f(cur.get("uang_muka_total"))
        if cur.get("status") not in PO_BOLEH_BAYAR:
            raise HTTPException(409, "Status PO baru saja berubah — muat ulang.")
        if sudah + amount - batas > 0.01:
            raise HTTPException(400, f"Uang muka melebihi nilai PO: sudah Rp {sudah:,.0f} + Rp {amount:,.0f} > "
                                     f"nilai PO Rp {batas:,.0f}.")
        res = await db.rahaza_purchase_orders.update_one(
            {"id": po_id, "uang_muka_total": cur.get("uang_muka_total")},
            {"$set": {"uang_muka_total": round(sudah + amount, 2), "updated_at": _now()}})
        if res.matched_count:
            break
    else:
        raise HTTPException(409, "PO sedang diproses pengguna lain — coba lagi sebentar.")

    adv_id = _uid()
    mv_id = _uid()
    nomor = f"UM-{po.get('po_number') or po_id[:8]}-{adv_id[:4].upper()}"
    adv = {"id": adv_id, "nomor": nomor, "po_id": po_id, "po_number": po.get("po_number"),
           "supplier_id": po.get("supplier_id"), "supplier_name": po.get("supplier_name") or po.get("vendor_name"),
           "entity": entity, "amount": amount, "terpakai": 0.0, "dikembalikan": 0.0, "status": AKTIF,
           "date": d.isoformat(), "cash_account_id": acc["id"], "cash_account_name": acc.get("name"),
           "movement_id": mv_id, "notes": (body.get("notes") or "").strip(), "pemakaian": [], "pengembalian": [],
           "created_at": _now(), "created_by": user.get("id"), "created_by_name": user.get("name", "")}
    await db[COLL].insert_one(dict(adv))
    await db.rahaza_cash_movements.insert_one({
        "id": mv_id, "account_id": acc["id"], "account_name": acc.get("name"), "direction": "out", "amount": amount,
        "category": "ap_advance", "ref_id": adv_id, "ref_label": nomor, "source_module": SUMBER_BAYAR,
        "date": d.isoformat(), "notes": f"Uang muka PO {po.get('po_number') or ''} ke {adv['supplier_name'] or ''}",
        "timestamp": _now(), "created_by": user.get("id"), "created_by_name": user.get("name", "")})
    akun = await _akun_uang_muka(db)
    memo = f"Uang muka PO {po.get('po_number') or ''} · {adv['supplier_name'] or ''}".strip()
    res = await _jurnal(db, d, memo, SUMBER_BAYAR, f"apadv:{adv_id}", [
        {"account_code": akun, "debit": amount, "credit": 0, "description": memo},
        {"account_code": acc["gl_account_code"], "debit": 0, "credit": amount, "description": memo}], user, entity)
    await db[COLL].update_one({"id": adv_id}, {"$set": _hasil(res)})
    await _catat(user, "uang_muka_bayar", f"{nomor} Rp {amount:,.0f} ke {adv['supplier_name'] or ''} via {acc.get('name')}")
    return await db[COLL].find_one({"id": adv_id}, {"_id": 0})


# ── 2. potong tagihan ────────────────────────────────────────────────────────────────────────────────────────────
async def terapkan_ke_tagihan(db, invoice_id: str, user: dict) -> dict:
    """Potong sisa uang muka PO-PO tagihan ini. Tidak pernah melempar (dipanggil dari alur penerimaan/persetujuan)."""
    try:
        return await _terapkan(db, invoice_id, user)
    except Exception as e:  # noqa: BLE001
        log.exception("potong uang muka untuk tagihan %s gagal", invoice_id)
        return {"ok": False, "error": str(e)}


async def _terapkan(db, invoice_id: str, user: dict) -> dict:
    from routes.rahaza_finance import ap_remaining
    from routes.rahaza_posting import _ap_account_for_invoice
    from routes.rahaza_posting_profiles import get_mapping

    inv = await db.rahaza_ap_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv or inv.get("status") in ("draft", "cancelled", "void", "written_off"):
        return {"ok": True, "dipakai": 0.0}
    po_ids = list(inv.get("po_ids") or [])
    if not po_ids:
        return {"ok": True, "dipakai": 0.0}
    advs = await db[COLL].find({"po_id": {"$in": po_ids}, "status": AKTIF}, {"_id": 0}).sort("created_at", 1).to_list(100)
    total = 0.0
    akun_um = await _akun_uang_muka(db)
    ap_code = await _ap_account_for_invoice(db, inv, (await get_mapping(db, "ap_payment")).get("debit_ap"))
    for adv in advs:
        inv = await db.rahaza_ap_invoices.find_one({"id": invoice_id}, {"_id": 0}) or inv
        buka = round(ap_remaining(inv), 2)
        if buka <= 0.009:
            break
        pakai = round(min(sisa(adv), buka), 2)
        if pakai <= 0.009:
            continue
        # klaim uang muka (bandingkan-lalu-tulis)
        baru = round(_f(adv.get("terpakai")) + pakai, 2)
        st = HABIS if round(_f(adv.get("amount")) - baru - _f(adv.get("dikembalikan")), 2) <= 0.009 else AKTIF
        r1 = await db[COLL].update_one({"id": adv["id"], "status": AKTIF, "terpakai": adv.get("terpakai")},
                                       {"$set": {"terpakai": baru, "status": st}})
        if not r1.matched_count:
            continue
        # tagihan: dibayar bertambah (bandingkan-lalu-tulis)
        paid = round(_f(inv.get("paid_amount")) + pakai, 2)
        sisa_tagihan = round(_f(inv.get("total")) - _f(inv.get("debit_note_amount")) - paid, 2)
        r2 = await db.rahaza_ap_invoices.update_one(
            {"id": invoice_id, "paid_amount": inv.get("paid_amount")},
            {"$set": {"paid_amount": paid, "balance": max(0.0, sisa_tagihan),
                      "status": "paid" if sisa_tagihan <= 0.01 else "partial_paid", "updated_at": _now()}})
        if not r2.matched_count:
            await db[COLL].update_one({"id": adv["id"], "terpakai": baru},
                                      {"$set": {"terpakai": adv.get("terpakai") or 0.0, "status": AKTIF}})
            continue
        pay_id = _uid()
        tgl = str(inv.get("issue_date") or "")[:10] or None
        try:
            d = date.fromisoformat(tgl) if tgl else _tanggal(None)
        except ValueError:
            d = _tanggal(None)
        await db.rahaza_ap_payments.insert_one({
            "id": pay_id, "invoice_id": invoice_id, "invoice_number": inv.get("invoice_number"), "amount": pakai,
            "gross_amount": pakai, "date": d.isoformat(), "account_id": None, "movement_id": None,
            "source": "uang_muka", "advance_id": adv["id"], "advance_nomor": adv.get("nomor"),
            "notes": f"Dipotong uang muka {adv.get('nomor') or ''}", "created_at": _now(),
            "created_by": (user or {}).get("id") or "system", "created_by_name": (user or {}).get("name", "")})
        memo = f"Potong uang muka {adv.get('nomor') or ''} ke tagihan {inv.get('invoice_number') or ''}"
        res = await _jurnal(db, d, memo, SUMBER_POTONG, f"apadvuse:{pay_id}", [
            {"account_code": ap_code, "debit": pakai, "credit": 0, "description": memo},
            {"account_code": akun_um, "debit": 0, "credit": pakai, "description": memo}], user,
            adv.get("entity") or "DA")
        await db.rahaza_ap_payments.update_one({"id": pay_id}, {"$set": _hasil(res)})
        await db[COLL].update_one({"id": adv["id"]}, {"$push": {"pemakaian": {
            "invoice_id": invoice_id, "invoice_number": inv.get("invoice_number"), "amount": pakai,
            "payment_id": pay_id, "at": _now()}}})
        total = round(total + pakai, 2)
    if total:
        await _catat(user, "uang_muka_potong", f"Tagihan {inv.get('invoice_number')} dipotong uang muka Rp {total:,.0f}")
    return {"ok": True, "dipakai": total}


# ── 3. kembalikan sisa ───────────────────────────────────────────────────────────────────────────────────────────
async def kembalikan(db, adv_id: str, body: dict, user: dict) -> dict:
    adv = await db[COLL].find_one({"id": adv_id}, {"_id": 0})
    if not adv or adv.get("status") == BATAL:
        raise HTTPException(404, "Uang muka tidak ditemukan.")
    amount = round(_f(body.get("amount")) or sisa(adv), 2)
    if amount <= 0 or amount - sisa(adv) > 0.01:
        raise HTTPException(400, f"Nilai pengembalian harus antara Rp 1 dan sisa uang muka Rp {sisa(adv):,.0f}.")
    acc = await _rekening(db, body.get("cash_account_id"), adv.get("entity") or "DA", "Pengembalian uang muka")
    d = _tanggal(body.get("date"))
    baru = round(_f(adv.get("dikembalikan")) + amount, 2)
    st = HABIS if round(_f(adv.get("amount")) - _f(adv.get("terpakai")) - baru, 2) <= 0.009 else AKTIF
    ret_id, mv_id = _uid(), _uid()
    r = await db[COLL].update_one({"id": adv_id, "status": AKTIF, "dikembalikan": adv.get("dikembalikan")},
                                  {"$set": {"dikembalikan": baru, "status": st},
                                   "$push": {"pengembalian": {"id": ret_id, "amount": amount, "date": d.isoformat(),
                                                              "cash_account_id": acc["id"], "movement_id": mv_id,
                                                              "notes": (body.get("notes") or "").strip(),
                                                              "at": _now(), "by": user.get("name", "")}}})
    if not r.matched_count:
        raise HTTPException(409, "Uang muka ini baru saja diubah pengguna lain — muat ulang.")
    await db.rahaza_cash_movements.insert_one({
        "id": mv_id, "account_id": acc["id"], "account_name": acc.get("name"), "direction": "in", "amount": amount,
        "category": "ap_advance_refund", "ref_id": adv_id, "ref_label": adv.get("nomor"),
        "source_module": SUMBER_KEMBALI, "date": d.isoformat(),
        "notes": f"Pengembalian uang muka {adv.get('nomor') or ''}", "timestamp": _now(),
        "created_by": user.get("id"), "created_by_name": user.get("name", "")})
    memo = f"Pengembalian uang muka {adv.get('nomor') or ''} · {adv.get('supplier_name') or ''}".strip()
    res = await _jurnal(db, d, memo, SUMBER_KEMBALI, f"apadvret:{ret_id}", [
        {"account_code": acc["gl_account_code"], "debit": amount, "credit": 0, "description": memo},
        {"account_code": await _akun_uang_muka(db), "debit": 0, "credit": amount, "description": memo}],
        user, adv.get("entity") or "DA")
    if not res.get("ok"):
        await db[COLL].update_one({"id": adv_id}, {"$set": {"post_error": res.get("error")}})
    await _catat(user, "uang_muka_kembali", f"{adv.get('nomor')} dikembalikan Rp {amount:,.0f}")
    return await db[COLL].find_one({"id": adv_id}, {"_id": 0})


# ── 4. batalkan (salah catat) ────────────────────────────────────────────────────────────────────────────────────
async def batalkan(db, adv_id: str, alasan: str, user: dict) -> dict:
    alasan = (alasan or "").strip()
    if len(alasan) < MIN_ALASAN:
        raise HTTPException(400, f"Alasan pembatalan wajib diisi (minimal {MIN_ALASAN} huruf).")
    adv = await db[COLL].find_one({"id": adv_id}, {"_id": 0})
    if not adv or adv.get("status") == BATAL:
        raise HTTPException(404, "Uang muka tidak ditemukan atau sudah dibatalkan.")
    if _f(adv.get("terpakai")) > 0.009 or _f(adv.get("dikembalikan")) > 0.009:
        raise HTTPException(409, "Uang muka ini sudah dipakai memotong tagihan atau sudah dikembalikan sebagian — "
                                 "tidak bisa dibatalkan. Kembalikan sisanya saja.")
    r = await db[COLL].update_one({"id": adv_id, "status": AKTIF, "terpakai": adv.get("terpakai"),
                                   "dikembalikan": adv.get("dikembalikan")}, {"$set": {"status": "membatalkan"}})
    if not r.matched_count:
        raise HTTPException(409, "Uang muka ini baru saja diubah pengguna lain — muat ulang.")
    from routes.rahaza_posting import _void_je_by_source
    v = await _void_je_by_source(db, SUMBER_BAYAR, f"apadv:{adv_id}", user, f"Uang muka dibatalkan: {alasan}")
    if not v.get("ok"):
        await db[COLL].update_one({"id": adv_id, "status": "membatalkan"}, {"$set": {"status": AKTIF}})
        raise HTTPException(409, f"Jurnal uang muka tidak bisa dibatalkan: {v.get('error')}")
    if adv.get("movement_id"):
        await db.rahaza_cash_movements.delete_one({"id": adv["movement_id"]})
    await db.rahaza_purchase_orders.update_one({"id": adv["po_id"]}, {"$inc": {"uang_muka_total": -_f(adv.get("amount"))}})
    await db[COLL].update_one({"id": adv_id}, {"$set": {
        "status": BATAL, "batal_alasan": alasan, "batal_at": _now(), "batal_oleh": user.get("name", "")}})
    await _catat(user, "uang_muka_batal", f"{adv.get('nomor')} dibatalkan: {alasan}")
    return await db[COLL].find_one({"id": adv_id}, {"_id": 0})


async def _catat(user: dict, aksi: str, teks: str) -> None:
    try:
        from auth import log_activity
        await log_activity((user or {}).get("id") or "", (user or {}).get("name") or "", aksi, COLL, teks)
    except Exception:  # noqa: BLE001
        log.exception("log_activity uang muka gagal")
