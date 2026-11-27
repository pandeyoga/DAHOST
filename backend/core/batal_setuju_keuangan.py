"""core.batal_setuju_keuangan — jenis persetujuan Keuangan, klaim/dinas/kasbon, dan Marketing (lihat `core.batal_setuju`).

Faktur yang sudah berjurnal: jurnalnya di-VOID lewat helper resmi (`void_ap_invoice_posting` /
`void_ar_invoice_posting`, yang memeriksa periode terbuka dan ikut membalik HPP faktur dari penerimaan), lalu
`gl_je_id/number/posted_at` dikosongkan — tanpa itu persetujuan ulang tidak memposting jurnal lagi.

TIDAK didaftarkan (jalur resminya sudah ada):
  · Proses gaji final          → Penggajian › Batalkan run (dua langkah HR → Keuangan).
  · Jurnal manual / akrual     → Batalkan jurnal / Balik akrual di menunya.
  · Permintaan ubah faktur     → ajukan permintaan ubah faktur baru (nilai sebelum diubah tidak tersimpan utuh).
  · Tindakan Asisten AI        → Tindakan AI › Balikkan.
  · Anggaran                   → tombol Buka lagi di Anggaran (izinnya kini sama dengan Setujui).
  · Pelepasan aset             → belum ada jalur balik (jurnal pelepasan + jadwal penyusutan); usulan terpisah.
"""
from __future__ import annotations

from fastapi import HTTPException

from core.batal_setuju import Jenis, daftar

FIN_IZIN = ("finance.approve", "finance.manage")
FIN_PERAN = ("owner", "admin", "superadmin", "accounting", "manager_keuangan", "finance_manager", "staff_keuangan",
             "finance")
GL_FIELD = ("gl_je_id", "gl_je_number", "gl_posted_at", "post_error")


async def _periode_tertutup(db, sumber: str, ref: str) -> list:
    from datetime import date
    from routes.rahaza_posting import _ensure_period_open, _find_existing_je
    je = await _find_existing_je(db, sumber, ref)
    if not je:
        return []
    from core import entities as ent_mod
    err = await _ensure_period_open(db, date.fromisoformat(je["date"]), entity=ent_mod.entity_of_value(je.get("entity")))
    return [f"Jurnalnya ({je.get('je_number') or ''}, {je['date']}) ada di periode yang sudah ditutup: {err}"] if err else []


def _void_gagal(res: dict):
    if not (res or {}).get("ok", True):
        raise HTTPException(409, f"Jurnal tidak bisa dibatalkan: {res.get('error')}")


def _hasil_jurnal(res: dict) -> str:
    """Hasil pembatalan jurnal untuk ringkasan: dibatalkan di tempat, atau dibalik (periode asal sudah tertutup)."""
    if res.get("reversed"):
        return f"dibalik dengan {res.get('reversal_je_number') or 'jurnal pembalik'}"
    return "dibatalkan" if res.get("voided") else "tidak ada"


# ── Faktur pemasok (Setujui & catat ke buku besar) ──
async def _hambatan_ap(db, d: dict) -> list:
    if float(d.get("paid_amount") or 0) > 0 or await db.rahaza_ap_payments.count_documents(
            {"invoice_id": d.get("id"), "status": {"$nin": ["voided"]}}):
        return ["Faktur ini sudah dibayar (sebagian/penuh). Persetujuannya tidak bisa ditarik."]
    if d.get("antar_cv") or d.get("intercompany") or d.get("is_intercompany"):
        return ["Faktur antar CV dibatalkan lewat Transaksi antar CV."]
    if float(d.get("debit_note_amount") or 0) > 0.009:   # Paket 1: sisa faktur sudah dipotong nota debit retur
        return ["Faktur ini sudah dipotong nota debit retur pembelian. Persetujuannya tidak bisa ditarik."]
    return await _periode_tertutup(db, "ap_invoice", f"ap:{d.get('id')}")


async def _balik_ap(db, d: dict, user: dict, alasan: str) -> dict:
    from routes.rahaza_posting import void_ap_invoice_posting
    res = await void_ap_invoice_posting(db, d["id"], user, reason=f"Batal setuju: {alasan}")
    _void_gagal(res)
    return {"jurnal": _hasil_jurnal(res), "hpp": bool(res.get("hpp_reversal"))}


daftar(Jenis(
    kode="fin-faktur-pemasok", label="Faktur pemasok", portal="finance", koleksi="rahaza_ap_invoices",
    modul="fin-ap-hub", status_setuju=("sent", "approved"), kembali_ke="draft", label_kembali="draf",
    izin=FIN_IZIN, peran_lama=FIN_PERAN, hapus_field=GL_FIELD + ("gl_ap_account_code",),
    nama=lambda d: d.get("invoice_number") or d.get("number") or d.get("id") or "",
    waktu_setuju="gl_posted_at", hambatan=_hambatan_ap, balikkan=_balik_ap,
))


# ── Faktur penjualan / piutang (Terbitkan) — hanya faktur yang dibuat manual di Piutang ──
async def _hambatan_ar(db, d: dict) -> list:
    if float(d.get("paid_amount") or 0) > 0 or float(d.get("credited_amount") or 0) > 0:
        return ["Faktur ini sudah dibayar atau punya nota kredit. Persetujuannya tidak bisa ditarik."]
    if d.get("schedule_mode") == "v2" or (d.get("source") and d.get("source") != "manual"):
        return [f"Faktur ini dibuat otomatis dari dokumen lain ({d.get('source') or 'jadwal maklon'}). "
                "Batalkan lewat dokumen asalnya."]
    return await _periode_tertutup(db, "ar_invoice", f"ar:{d.get('id')}")


async def _balik_ar(db, d: dict, user: dict, alasan: str) -> dict:
    from routes.rahaza_posting import void_ar_invoice_posting
    res = await void_ar_invoice_posting(db, d["id"], user, reason=f"Batal setuju: {alasan}")
    _void_gagal(res)
    return {"jurnal": _hasil_jurnal(res)}


daftar(Jenis(
    kode="fin-faktur-penjualan", label="Faktur penjualan", portal="finance", koleksi="rahaza_ar_invoices",
    modul="fin-ar-hub", status_setuju=("issued", "sent", "overdue"), kembali_ke="draft", label_kembali="draf",
    izin=FIN_IZIN, peran_lama=FIN_PERAN, hapus_field=GL_FIELD + ("gl_ar_account_code",),
    nama=lambda d: d.get("invoice_number") or d.get("number") or d.get("id") or "",
    waktu_setuju="gl_posted_at", hambatan=_hambatan_ar, balikkan=_balik_ar,
))


# ── Rekonsiliasi bank ──
daftar(Jenis(
    kode="fin-rekon-bank", label="Rekonsiliasi bank", portal="finance", koleksi="bank_recon_sessions",
    modul="fin-bank-recon", status_setuju=("approved",), kembali_ke="in_progress", label_kembali="sedang dikerjakan",
    izin=FIN_IZIN, peran_lama=FIN_PERAN,
    hapus_field=("approved_at", "approved_by", "approved_by_name", "approved_summary", "approved_with_unexplained",
                 "approval_note"),
    nama=lambda d: f"{d.get('account_name') or d.get('bank_account_name') or ''} {d.get('period') or ''}".strip() or d.get("id"),
))


# ── Klaim biaya karyawan (belum dicairkan) ──
async def _hambatan_klaim(db, d: dict) -> list:
    if d.get("disburse_lock") or d.get("gl_je_id"):
        return ["Klaim ini sedang/sudah dicairkan Keuangan. Persetujuannya tidak bisa ditarik."]
    return []


KLAIM_PERAN = FIN_PERAN + ("hr", "hr_manager", "manager")

daftar(Jenis(
    kode="hr-klaim-biaya", label="Klaim biaya", portal="hr", koleksi="rahaza_expense_claims", modul="hr-expense-hub",
    status_setuju=("approved",), kembali_ke="submitted", label_kembali="menunggu persetujuan",
    izin=("hr.approve",), peran_lama=KLAIM_PERAN,
    hapus_field=("approved_by", "approved_by_name", "approved_at", "approval_note"),
    nama=lambda d: d.get("claim_number") or d.get("id") or "",
    pemohon=lambda d: d.get("user_id") or d.get("created_by"), hambatan=_hambatan_klaim,
))


# ── Perjalanan dinas — persetujuan menulis absensi "tugas luar" ──
async def _hambatan_dinas(db, d: dict) -> list:
    if d.get("advance_lock") or d.get("advance_je_id"):
        return ["Uang muka dinas ini sedang/sudah dibayar. Persetujuannya tidak bisa ditarik."]
    if await db.employee_travel_settlements.count_documents(
            {"travel_request_id": d.get("id"), "status": {"$ne": "rejected"}}):
        return ["Dinas ini sudah punya penyelesaian (laporan biaya). Batalkan penyelesaiannya dulu."]
    from core.batal_setuju_sdm import _hari_terkunci
    rows = await db.rahaza_attendance_events.find({"duty_travel_id": d.get("id")}, {"_id": 0, "date": 1}).to_list(400)
    return await _hari_terkunci(db, d.get("employee_id"), [r.get("date") for r in rows])


async def _balik_dinas(db, d: dict, user: dict, alasan: str) -> dict:
    from core.tugas_luar import restore_duty_days
    return {"absensi": await restore_duty_days(db, d, user)}


daftar(Jenis(
    kode="hr-dinas", label="Perjalanan dinas", portal="hr", koleksi="employee_travel_requests", modul="hr-expense-hub",
    status_setuju=("approved",), kembali_ke="submitted", label_kembali="menunggu persetujuan",
    izin=("hr.approve",), peran_lama=KLAIM_PERAN,
    hapus_field=("approved_by", "approved_by_name", "approved_at", "approval_note", "cash_advance_approved",
                 "cash_advance_decided", "attendance_written"),
    nama=lambda d: d.get("travel_number") or d.get("request_number") or d.get("id") or "",
    pemohon=lambda d: d.get("user_id") or d.get("created_by"), hambatan=_hambatan_dinas, balikkan=_balik_dinas,
))


# ── Penyelesaian dinas ──
async def _hambatan_selesai_dinas(db, d: dict) -> list:
    if d.get("post_lock") or d.get("gl_je_id"):
        return ["Penyelesaian ini sedang/sudah diposting Keuangan. Persetujuannya tidak bisa ditarik."]
    return []


daftar(Jenis(
    kode="hr-dinas-selesai", label="Penyelesaian dinas", portal="hr", koleksi="employee_travel_settlements",
    modul="hr-expense-hub", status_setuju=("approved",), kembali_ke="submitted", label_kembali="menunggu persetujuan",
    izin=("hr.approve", "finance.approve"), peran_lama=KLAIM_PERAN,
    hapus_field=("approved_by", "approved_by_name", "approved_at", "approval_note"),
    nama=lambda d: d.get("settlement_number") or d.get("id") or "",
    pemohon=lambda d: d.get("user_id") or d.get("created_by"), hambatan=_hambatan_selesai_dinas,
))


# ── Kasbon (disetujui SDM, belum dicairkan) ──
def _kasbon_isi(d: dict) -> dict:
    import math
    if d.get("requested_amount") is None:
        return {}
    awal = float(d.get("requested_amount") or 0)
    n = max(int(d.get("installment_count") or 1), 1)
    return {"amount": awal, "outstanding_balance": awal, "installment_amount": math.ceil(awal / n)}


async def _balik_kasbon(db, d: dict, user: dict, alasan: str) -> dict:
    await db.dewi_kasbon_requests.update_one({"id": d["id"]}, {"$unset": {"requested_amount": ""}})
    return {}


daftar(Jenis(
    kode="hr-kasbon", label="Kasbon", portal="hr", koleksi="dewi_kasbon_requests", modul="hr-kasbon",
    status_setuju=("hr_approved",), kembali_ke="submitted", label_kembali="menunggu tinjauan SDM", isi_field=_kasbon_isi,
    izin=("hr.approve",), peran_lama=("owner", "admin", "superadmin", "hr", "hr_manager", "staff_hr"),
    hapus_field=("hr_reviewed_by", "hr_reviewed_by_id", "hr_reviewed_at", "hr_notes"),
    nama=lambda d: d.get("kasbon_number") or d.get("employee_name") or d.get("id") or "",
    pemohon=lambda d: d.get("user_id") or d.get("created_by_id"), penyetuju=lambda d: d.get("hr_reviewed_by_id"),
    waktu_setuju="hr_reviewed_at", balikkan=_balik_kasbon,
))


# ── Marketing ──
MKT_IZIN = ("toko.approve", "toko.manage")
MKT_PERAN = ("manager_marketing", "pic_marketing", "pic_toko", "manager", "owner", "admin", "superadmin")


async def _hambatan_retur(db, d: dict) -> list:
    if d.get("credit_note_id") or d.get("status") == "completed":
        return ["Retur ini sudah diselesaikan dengan nota kredit. Persetujuannya tidak bisa ditarik."]
    if d.get("wh_return_id"):
        wh = await db.wh_returns.find_one({"id": d["wh_return_id"]}, {"_id": 0, "status": 1, "code": 1})
        if (wh or {}).get("status") == "Resolved":
            return [f"Gudang sudah memutus paket retur {(wh or {}).get('code') or ''}. Balik dulu keputusan gudangnya "
                    "di Retur Fisik."]
    return []


daftar(Jenis(
    kode="mkt-retur", label="Retur toko", portal="marketing", koleksi="marketing_returns", modul="marketing-after-sales",
    status_setuju=("approved",), kembali_ke="pending", label_kembali="menunggu persetujuan",
    isi_field=lambda d: {"appeal_status": "pending"} if d.get("appeal_status") == "accepted" else {},
    izin=MKT_IZIN, peran_lama=MKT_PERAN + ("cs_staff",), hapus_field=("appeal_result", "approved_by", "approved_at"),
    nama=lambda d: d.get("return_number") or d.get("order_id") or d.get("id") or "",
    hambatan=_hambatan_retur,
))

daftar(Jenis(
    kode="mkt-tugas", label="Tugas marketing", portal="marketing", koleksi="marketing_tasks", modul="marketing-task-hub",
    status_setuju=("done",), kembali_ke="pending_approval", label_kembali="menunggu persetujuan",
    filter_tambahan={"approval_status": "approved"}, isi_field={"approval_status": "pending"},
    izin=("mod.mkt_tasks.approve", "toko.approve"), peran_lama=MKT_PERAN,
    hapus_field=("approved_by", "approved_at"),
    nama=lambda d: d.get("title") or d.get("id") or "",
    pemohon=lambda d: d.get("assigned_to_id") or d.get("assigned_to"),
))

daftar(Jenis(
    kode="mkt-kol", label="Permintaan produk kreator", portal="marketing", koleksi="marketing_creator_item_requests",
    modul="marketing-kol-hub", status_setuju=("approved",), kembali_ke="pending", label_kembali="menunggu persetujuan",
    izin=MKT_IZIN, peran_lama=MKT_PERAN + ("marketing_kol",), hapus_field=("reviewed_at", "reviewed_by"),
    nama=lambda d: d.get("creator_name") or d.get("product_name") or d.get("id") or "", waktu_setuju="reviewed_at",
))

daftar(Jenis(
    kode="mkt-harga", label="Usulan harga AI", portal="marketing", koleksi="marketing_dynamic_pricing_suggestions",
    modul="marketing-ai-hub", status_setuju=("approved",), kembali_ke="pending", label_kembali="menunggu persetujuan",
    izin=MKT_IZIN + ("pricing.approve",), peran_lama=MKT_PERAN, hapus_field=("decided_by", "decided_by_id", "decided_at"),
    nama=lambda d: d.get("sku") or d.get("product_name") or d.get("id") or "", waktu_setuju="decided_at",
))
