"""Belum masuk jurnal — SATU daftar dokumen yang mengubah uang/stok tetapi jurnalnya gagal (Paket 1 audit 25 Nov 2026).

Sebelumnya kegagalan posting hanya tercatat di dokumen masing-masing (`post_error`): tidak ada daftar pusat dan sebagian
tidak punya tombol ulang (contoh nyata 25 Nov: 114 penyesuaian stok barang jadi tanpa HPP). Modul ini TIDAK membuat
aturan jurnal baru — "Posting ulang" memanggil fungsi posting RESMI dokumen itu (`routes.rahaza_posting` dll.), yang
idempoten: jurnal yang sudah ada tidak dibuat dua kali, dan hasilnya (jurnal / galat baru) disimpan di dokumen.

Jenis tanpa `ulang` hanya ditampilkan + tombol "Buka" ke layarnya (alur ulangnya ada di layar itu, mis. payroll).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException

log = logging.getLogger(__name__)

BATAS = 500                      # per jenis — daftar kerja, bukan laporan
ADA_GALAT = {"$nin": [None, ""]}
STATUS_MATI = ["draft", "cancelled", "canceled", "void", "voided", "batal", "dibatalkan"]


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _tgl(v) -> str:
    return (v.isoformat() if hasattr(v, "isoformat") else str(v or ""))[:10]


@dataclass
class Sumber:
    kode: str
    label: str
    koleksi: str
    filter: dict
    nama: Callable[[dict], str]
    tanggal: Callable[[dict], str]
    modul: str                                   # layar untuk tombol "Buka"
    nilai: Callable[[dict], Optional[float]] = lambda d: None
    tab: Optional[str] = None
    ulang: Optional[Callable[..., Awaitable[dict]]] = None
    galat: Callable[[dict], str] = lambda d: d.get("post_error") or ""


# ── fungsi posting ulang (semuanya memanggil poster resmi) ──────────────────────────────────────────────────────
async def _ulang_mutasi(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_inventory_adjust, post_inventory_receive
    if d.get("type") == "receive":
        return await post_inventory_receive(db, d, user)
    if d.get("type") == "adjust":
        return await post_inventory_adjust(db, d, user)
    return {"ok": False, "error": "Jenis mutasi ini tidak dijurnal dari sini."}


async def _ulang_pengeluaran_bahan(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_inventory_issue
    return await post_inventory_issue(db, d, user)


async def _ulang_faktur_penjualan(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_ar_invoice
    return await post_ar_invoice(db, d, user)


async def _ulang_faktur_pemasok(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_ap_invoice
    return await post_ap_invoice(db, d, user)


async def _ulang_nota_kredit(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_credit_note
    return await post_credit_note(db, d, user)


async def _ulang_pengeluaran(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_expense
    return await post_expense(db, d, user)


async def _simpan_hasil_bayar(db, koleksi: str, doc_id: str, res: dict) -> None:
    await db[koleksi].update_one({"id": doc_id}, {"$set": {
        "gl_je_id": res.get("je_id") if res.get("ok") else None,
        "gl_je_number": res.get("je_number") if res.get("ok") else None,
        "post_error": None if res.get("ok") else (res.get("error") or "Posting gagal")}})


async def _ulang_bayar_piutang(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_ar_invoice, post_ar_payment
    inv = await db.rahaza_ar_invoices.find_one({"id": d.get("invoice_id")}, {"_id": 0})
    if not inv:
        return {"ok": False, "error": "Faktur pembayaran ini tidak ditemukan."}
    if not inv.get("gl_je_id"):
        r = await post_ar_invoice(db, inv, user)
        if not r.get("ok"):
            return {"ok": False, "error": f"Faktur {inv.get('invoice_number') or ''} sendiri belum bisa dijurnal: "
                                          f"{r.get('error')}"}
        inv = await db.rahaza_ar_invoices.find_one({"id": d.get("invoice_id")}, {"_id": 0}) or inv
    res = await post_ar_payment(db, inv, _f(d.get("amount")), d.get("account_id"), _tgl(d.get("date")), user,
                                movement_id=d.get("movement_id") or d.get("id"))
    await _simpan_hasil_bayar(db, "rahaza_ar_payments", d["id"], res)
    return res


async def _ulang_bayar_hutang(db, d: dict, user: dict) -> dict:
    from routes.rahaza_posting import post_ap_payment
    inv = await db.rahaza_ap_invoices.find_one({"id": d.get("invoice_id")}, {"_id": 0})
    if not inv:
        return {"ok": False, "error": "Faktur pembayaran ini tidak ditemukan."}
    if not inv.get("gl_je_id"):
        return {"ok": False, "error": f"Faktur {inv.get('invoice_number') or ''} sendiri belum masuk jurnal — "
                                      "posting ulang fakturnya dulu."}
    bruto = _f(d.get("gross_amount")) or _f(d.get("amount"))
    res = await post_ap_payment(db, inv, bruto, d.get("account_id"), _tgl(d.get("date")), user,
                                movement_id=d.get("movement_id") or d.get("id"),
                                discount_taken=_f(d.get("discount_amount")))
    await _simpan_hasil_bayar(db, "rahaza_ap_payments", d["id"], res)
    return res


async def _ulang_tagihan_cmt(db, d: dict, user: dict) -> dict:
    from routes.dewi_maklon_finance import post_cmt_ap_invoice
    return await post_cmt_ap_invoice(db, d, user)


async def _ulang_bayar_cmt(db, d: dict, user: dict) -> dict:
    from routes.dewi_maklon_finance import cmt_bill_entity
    from routes.rahaza_posting import post_ap_payment
    bill = await db.dewi_cmt_payments.find_one({"id": d.get("payment_id")}, {"_id": 0})
    if not bill:
        return {"ok": False, "error": "Tagihan CMT pembayaran ini tidak ditemukan."}
    if not bill.get("gl_je_id"):
        return {"ok": False, "error": f"Tagihan {bill.get('payment_code') or ''} sendiri belum masuk jurnal — "
                                      "posting ulang tagihannya dulu."}
    pseudo = {"id": bill["id"], "invoice_number": bill.get("payment_code"), "vendor_name": bill.get("cmt_name"),
              "gl_ap_account_code": bill.get("gl_ap_account_code"), "entity": await cmt_bill_entity(db, bill)}
    res = await post_ap_payment(db, pseudo, _f(d.get("amount")), d.get("cash_account_id"), _tgl(d.get("payment_date")),
                                user, movement_id=d["id"])
    await _simpan_hasil_bayar(db, "dewi_cmt_disbursements", d["id"], res)
    return res


async def _ulang_kasbon(db, d: dict, user: dict) -> dict:
    from datetime import date
    from routes.dewi_kasbon import _gl_flags, _post_kasbon_gl
    try:
        tgl = date.fromisoformat(_tgl(d.get("disbursement_date")))
    except ValueError:
        return {"ok": False, "error": "Tanggal pencairan kasbon tidak terbaca."}
    res = await _post_kasbon_gl(
        db, "employee_loan_disbursement", f"kasbon-disburse-{d['id']}",
        f"Kasbon Cair — {d.get('employee_name', '')} — {d.get('request_number', '')}",
        _f(d.get("amount")), user, je_date=tgl, cash_code=d.get("disbursement_account_code"))
    await db.dewi_kasbon_requests.update_one({"id": d["id"]}, {"$set": _gl_flags(res)})
    return res


# ── daftar jenis ─────────────────────────────────────────────────────────────────────────────────────────────────
_JENIS_MUTASI = {"receive": "Barang masuk", "adjust": "Penyesuaian stok"}

SUMBER: list[Sumber] = [
    Sumber("mutasi-stok", "Mutasi stok", "rahaza_material_movements",
           {"post_error": ADA_GALAT, "type": {"$in": ["receive", "adjust"]}},
           nama=lambda d: f"{_JENIS_MUTASI.get(d.get('type'), 'Mutasi')} {d.get('_barang') or ''} "
                          f"({_f(d.get('qty')):,.0f})".replace(",", "."),
           tanggal=lambda d: _tgl(d.get("timestamp") or d.get("created_at")), modul="wh-fg", ulang=_ulang_mutasi),
    Sumber("pengeluaran-bahan", "Pengeluaran bahan", "rahaza_material_issues",
           {"post_error": ADA_GALAT, "ref_type": {"$ne": "cutting_issue"}, "source": {"$ne": "cutting"},
            "status": {"$nin": STATUS_MATI}},
           nama=lambda d: d.get("mi_number") or d.get("issue_number") or d.get("id", ""),
           tanggal=lambda d: _tgl(d.get("issue_date") or d.get("created_at")), modul="wh-material-issue",
           ulang=_ulang_pengeluaran_bahan),
    Sumber("faktur-penjualan", "Faktur penjualan", "rahaza_ar_invoices",
           {"post_error": ADA_GALAT, "status": {"$nin": STATUS_MATI + ["written_off"]}},
           nama=lambda d: f"{d.get('invoice_number') or ''} {d.get('customer_name') or ''}".strip(),
           tanggal=lambda d: _tgl(d.get("invoice_date") or d.get("created_at")), modul="fin-ar-hub",
           nilai=lambda d: _f(d.get("total")), ulang=_ulang_faktur_penjualan),
    Sumber("faktur-pemasok", "Faktur pemasok", "rahaza_ap_invoices",
           {"post_error": ADA_GALAT, "status": {"$nin": STATUS_MATI}},
           nama=lambda d: f"{d.get('invoice_number') or ''} {d.get('supplier_name') or d.get('vendor_name') or ''}".strip(),
           tanggal=lambda d: _tgl(d.get("invoice_date") or d.get("created_at")), modul="fin-ap-hub",
           nilai=lambda d: _f(d.get("total")), ulang=_ulang_faktur_pemasok),
    Sumber("bayar-piutang", "Pembayaran pelanggan", "rahaza_ar_payments",
           {"post_error": ADA_GALAT, "status": {"$nin": ["voided", "voiding"]}},
           nama=lambda d: d.get("invoice_number") or "", tanggal=lambda d: _tgl(d.get("date")), modul="fin-ar-hub",
           nilai=lambda d: _f(d.get("amount")), ulang=_ulang_bayar_piutang),
    Sumber("bayar-hutang", "Pembayaran pemasok", "rahaza_ap_payments",
           {"post_error": ADA_GALAT, "status": {"$nin": ["voided", "voiding"]}},
           nama=lambda d: d.get("invoice_number") or "", tanggal=lambda d: _tgl(d.get("date")), modul="fin-ap-hub",
           nilai=lambda d: _f(d.get("gross_amount")) or _f(d.get("amount")), ulang=_ulang_bayar_hutang),
    Sumber("tagihan-cmt", "Tagihan CMT", "dewi_cmt_payments",
           {"$or": [{"post_error": ADA_GALAT}, {"status": "draft"}], "status": {"$nin": ["cancelled", "void", "voided"]}},
           nama=lambda d: f"{d.get('payment_code') or ''} {d.get('cmt_name') or d.get('vendor_name') or ''}".strip(),
           tanggal=lambda d: _tgl(d.get("created_at")), modul="fin-ap-hub",
           nilai=lambda d: _f(d.get("net_amount") if d.get("net_amount") is not None else d.get("total_amount")),
           ulang=_ulang_tagihan_cmt,
           galat=lambda d: d.get("post_error") or "Tagihan masih draf: jurnalnya belum dibuat."),
    Sumber("bayar-cmt", "Pembayaran CMT", "dewi_cmt_disbursements",
           {"post_error": ADA_GALAT, "status": {"$nin": ["voided", "cancelled"]}},
           nama=lambda d: f"{d.get('payment_code') or ''} {d.get('cmt_name') or ''}".strip(),
           tanggal=lambda d: _tgl(d.get("payment_date")), modul="fin-ap-hub", nilai=lambda d: _f(d.get("amount")),
           ulang=_ulang_bayar_cmt),
    Sumber("nota-kredit", "Nota kredit", "rahaza_credit_notes",
           {"post_error": ADA_GALAT, "status": {"$nin": STATUS_MATI}},
           nama=lambda d: d.get("cn_number") or d.get("id", ""), tanggal=lambda d: _tgl(d.get("issue_date") or d.get("date") or d.get("created_at")),
           modul="fin-ar-hub", nilai=lambda d: _f(d.get("total") or d.get("amount")), ulang=_ulang_nota_kredit),
    Sumber("pengeluaran", "Pengeluaran / biaya", "rahaza_expenses",
           {"post_error": ADA_GALAT, "status": {"$nin": STATUS_MATI}},
           nama=lambda d: d.get("expense_number") or d.get("description") or d.get("id", ""),
           tanggal=lambda d: _tgl(d.get("date") or d.get("expense_date") or d.get("created_at")), modul="fin-expenses",
           nilai=lambda d: _f(d.get("amount") or d.get("total")), ulang=_ulang_pengeluaran),
    Sumber("kasbon", "Pencairan kasbon", "dewi_kasbon_requests",
           {"post_error": ADA_GALAT, "status": "disbursed", "gl_je_id": {"$in": [None, ""]}},
           nama=lambda d: f"{d.get('request_number') or ''} {d.get('employee_name') or ''}".strip(),
           tanggal=lambda d: _tgl(d.get("disbursement_date")), modul="fin-kasbon", tab="kasbon",
           nilai=lambda d: _f(d.get("amount")), ulang=_ulang_kasbon),
    # Hanya ditampilkan — alur ulangnya ada di layar masing-masing.
    Sumber("nota-langsung", "Nota penjualan langsung", "sales_direct_notes",
           {"$or": [{"ar_post_error": ADA_GALAT}, {"cogs_post_error": ADA_GALAT}]},
           nama=lambda d: d.get("note_number") or d.get("id", ""), tanggal=lambda d: _tgl(d.get("sale_date") or d.get("created_at")),
           modul="sales-direct", nilai=lambda d: _f(d.get("total")),
           galat=lambda d: d.get("ar_post_error") or d.get("cogs_post_error") or ""),
    Sumber("retur-nota", "Retur nota langsung", "sales_direct_returns",
           {"$or": [{"post_error": ADA_GALAT}, {"cn_post_error": ADA_GALAT}, {"cogs_post_error": ADA_GALAT}]},
           nama=lambda d: d.get("return_number") or d.get("id", ""), tanggal=lambda d: _tgl(d.get("return_date") or d.get("created_at")),
           modul="sales-direct", nilai=lambda d: _f(d.get("total")),
           galat=lambda d: d.get("post_error") or d.get("cn_post_error") or d.get("cogs_post_error") or ""),
    Sumber("nota-debit", "Nota debit pemasok", "rahaza_debit_notes", {"post_error": ADA_GALAT, "status": {"$ne": "cancelled"}},
           nama=lambda d: f"{d.get('dn_number') or ''} {d.get('supplier_name') or ''}".strip(),
           tanggal=lambda d: _tgl(d.get("dn_date") or d.get("date") or d.get("created_at")), modul="fin-debit-notes",
           nilai=lambda d: _f(d.get("total_amount") or d.get("ap_amount"))),
    Sumber("penggajian", "Penggajian", "rahaza_payroll_runs", {"post_error": ADA_GALAT, "status": {"$nin": STATUS_MATI}},
           nama=lambda d: d.get("run_number") or d.get("id", ""), tanggal=lambda d: _tgl(d.get("period_to") or d.get("created_at")),
           modul="hr-payroll-run"),
    Sumber("selisih-produksi", "Selisih produksi", "production_variances", {"post_error": ADA_GALAT},
           nama=lambda d: d.get("po_number") or d.get("id", ""), tanggal=lambda d: _tgl(d.get("created_at")),
           modul="prod-cmt-billing"),
]
_PER_KODE = {s.kode: s for s in SUMBER}


# ── kalimat galat untuk staf ─────────────────────────────────────────────────────────────────────────────────────
_KALIMAT = (
    ("Amount adjust = 0", "Barang ini belum punya HPP (harga pokok), jadi nilainya 0. Isi HPP-nya dulu, lalu posting ulang."),
    ("tidak ditemukan/aktif", "Akun buku besar yang dipakai tidak ada atau nonaktif. Periksa Profil Posting / bagan akun."),
    ("adalah header", "Akun yang dipakai adalah akun induk (header). Pilih akun rincian di Profil Posting."),
    ("mapping CoA missing", "Akun untuk jurnal ini belum diatur di Profil Posting."),
    ("belum lengkap", "Akun untuk jurnal ini belum lengkap di Profil Posting."),
    ("sudah closed", "Periode tanggal dokumen ini sudah ditutup. Buka periodenya atau ubah tanggal dokumen."),
    ("sudah locked", "Periode tanggal dokumen ini sudah dikunci."),
    ("terlalu jauh di masa depan", "Tanggal dokumen terlalu jauh di masa depan."),
)


def kalimat(galat: str) -> str:
    g = str(galat or "")
    for pola, teks in _KALIMAT:
        if pola in g:
            return teks
    return g


# ── API inti ─────────────────────────────────────────────────────────────────────────────────────────────────────
async def _nama_barang(db, docs: list) -> None:
    ids = sorted({d.get("material_id") for d in docs if d.get("material_id")})
    if not ids:
        return
    rows = await db.rahaza_materials.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(len(ids))
    nama = {r["id"]: (r.get("code") or r.get("name") or "") for r in rows}
    for d in docs:
        d["_barang"] = nama.get(d.get("material_id"), "")


def _baris(s: Sumber, d: dict) -> dict:
    g = s.galat(d)
    return {"jenis": s.kode, "label": s.label, "id": d.get("id"), "nama": (s.nama(d) or "").strip() or "—",
            "tanggal": s.tanggal(d), "nilai": s.nilai(d), "cv": d.get("entity") or "", "galat": kalimat(g),
            "galat_asli": g, "modul": s.modul, "tab": s.tab, "bisa_ulang": s.ulang is not None}


async def daftar(db) -> dict:
    """{data: [baris…], ringkas: {kode: jumlah}} — semua jenis, terbaru dulu per jenis."""
    data, ringkas = [], {}
    nama_koleksi = set(await db.list_collection_names())
    for s in SUMBER:
        if s.koleksi not in nama_koleksi:
            continue
        try:
            docs = await db[s.koleksi].find(s.filter, {"_id": 0}).sort("created_at", -1).to_list(BATAS)
        except Exception:  # noqa: BLE001 — satu koleksi bermasalah tidak menjatuhkan daftar
            log.exception("jurnal_tertunda: gagal membaca %s", s.kode)
            continue
        if s.koleksi == "rahaza_material_movements":
            await _nama_barang(db, docs)
        if docs:
            ringkas[s.kode] = len(docs)
        data.extend(_baris(s, d) for d in docs)
    return {"data": data, "ringkas": ringkas, "total": len(data)}


async def hitung(db) -> int:
    """Jumlah dokumen belum masuk jurnal (untuk Beranda Keuangan)."""
    n = 0
    nama_koleksi = set(await db.list_collection_names())
    for s in SUMBER:
        if s.koleksi in nama_koleksi:
            n += await db[s.koleksi].count_documents(s.filter)
    return n


async def ulang(db, kode: str, doc_id: str, user: dict) -> dict:
    s = _PER_KODE.get(kode)
    if not s:
        raise HTTPException(404, "Jenis dokumen tidak dikenal.")
    if not s.ulang:
        raise HTTPException(400, f"{s.label} diposting ulang dari layarnya sendiri.")
    d = await db[s.koleksi].find_one({"id": doc_id, **s.filter}, {"_id": 0})
    if not d:
        raise HTTPException(404, f"{s.label} ini tidak ada di daftar (mungkin sudah masuk jurnal).")
    try:
        res = await s.ulang(db, d, user) or {}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — galat posting dilaporkan sebagai kalimat, bukan 500
        log.exception("jurnal_tertunda: posting ulang %s %s gagal", kode, doc_id)
        res = {"ok": False, "error": str(e)}
    if not res.get("ok"):
        raise HTTPException(409, f"Masih gagal: {kalimat(res.get('error'))}")
    try:
        from auth import log_activity
        await log_activity(user.get("id") or "", user.get("name") or "", "posting_ulang", f"finance.{kode}",
                           f"Posting ulang {s.label} {doc_id}: {res.get('je_number') or 'jurnal sudah ada'}")
    except Exception:  # noqa: BLE001
        log.exception("log_activity posting_ulang gagal")
    return {"ok": True, "je_number": res.get("je_number"), "sudah_ada": bool(res.get("already_posted")),
            "pesan": f"{s.label} masuk jurnal" + (f" ({res['je_number']})." if res.get("je_number") else ".")}
