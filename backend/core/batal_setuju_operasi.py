"""core.batal_setuju_operasi — jenis persetujuan R&D, produksi, gudang, dan pengadaan (lihat `core.batal_setuju`).

TIDAK didaftarkan (sudah punya jalur koreksi resmi yang membalik stok & jurnal dengan benar):
  · Terima & QC selesai          → tombol Koreksi hasil QC per baris (stok barang jadi, hutang CMT, jurnal ikut).
  · Permintaan tambahan Kirim CMT → Retur Material, lalu batalkan nota aksesoris dan kirimannya.
  · Pengeluaran Material terbit  → Retur Material.
  · Opname gudang / aksesoris    → opname koreksi berikutnya.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.batal_setuju import Jenis, daftar

RND_PERAN = ("rnd_staff", "manager_produksi", "supervisor_produksi", "manager", "owner", "admin", "superadmin")
ATASAN = ("owner", "admin", "superadmin")


def _now():
    return datetime.now(timezone.utc)


def _langkah_setuju_terakhir(d: dict, kunci: str = "approval_steps") -> dict:
    for s in reversed(d.get(kunci) or []):
        if (s or {}).get("action") == "approved":
            return s
    return {}


async def _catat_langkah(db, koleksi: str, d: dict, user: dict, alasan: str, kunci: str = "approval_steps"):
    await db[koleksi].update_one({"id": d["id"]}, {"$push": {kunci: {
        "action": "approval_cancelled", "action_label": "Persetujuan dibatalkan", "actor_id": user.get("id"),
        "actor_name": user.get("name") or "", "comment": alasan, "timestamp": _now().isoformat()}}})


# ── Pola & marker ──
daftar(Jenis(
    kode="rnd-pola", label="Pola & marker", portal="rnd", koleksi="dewi_rnd_patterns", modul="rnd-design-hub",
    status_setuju=("approved",), kembali_ke="draft", label_kembali="draf",
    izin=("rnd.approve",), peran_lama=RND_PERAN, hapus_field=("approved_by", "approved_at"),
    nama=lambda d: d.get("pattern_code") or d.get("name") or d.get("style_code") or d.get("id") or "",
))


# ── Tech pack ──
async def _hambatan_techpack(db, d: dict) -> list:
    m = await db.rahaza_models.find_one({"techpack.tech_pack_id": d.get("id")}, {"_id": 0, "code": 1})
    if m:
        return [f"Tech pack ini sudah dipakai produk {m.get('code') or ''} di Master Produk (BOM dibuat darinya). "
                "Ubah BOM produknya di Master Produk › BOM."]
    return []


daftar(Jenis(
    kode="rnd-techpack", label="Tech pack", portal="rnd", koleksi="dewi_rnd_tech_packs", modul="rnd-design-hub",
    status_setuju=("approved",), kembali_ke="draft", label_kembali="draf",
    izin=("rnd.approve",), peran_lama=RND_PERAN, hapus_field=("approved_by", "approved_at"),
    nama=lambda d: f"{d.get('style_code') or d.get('name') or ''} v{str(d.get('version') or 1).lstrip('vV') or 1}".strip(),
    hambatan=_hambatan_techpack,
))


# ── Permintaan sampel R&D — persetujuan membuat draf PO "Sampel R&D" ──
async def _hambatan_sampel(db, d: dict) -> list:
    po_id = d.get("po_id")
    if not po_id:
        return []
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "status": 1, "po_number": 1})
    if po and (po.get("status") or "Draft") != "Draft":
        return [f"PO sampel {po.get('po_number') or ''} sudah {po.get('status')}. Selesaikan atau tutup PO-nya di "
                "Produksi, persetujuan sampel tidak bisa ditarik lagi."]
    from cascade_delete import alasan_tolak_hapus_po
    alasan = await alasan_tolak_hapus_po(db, po_id) if po else []
    if alasan:
        return [f"PO sampel {(po or {}).get('po_number') or ''} sudah berjalan: {'; '.join(alasan)}."]
    return []


async def _balik_sampel(db, d: dict, user: dict, alasan: str) -> dict:
    po_id = d.get("po_id")
    if not po_id:
        return {}
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "status": 1, "po_number": 1})
    if po and (po.get("status") or "Draft") == "Draft":
        from cascade_delete import cascade_delete_po
        await cascade_delete_po(po_id)
        return {"po_sampel": f"draf {po.get('po_number') or ''} dihapus"}
    return {}


daftar(Jenis(
    kode="rnd-sampel", label="Permintaan sampel R&D", portal="rnd", koleksi="dewi_rnd_sample_requests",
    modul="rnd-samples", status_setuju=("approved",), kembali_ke="submitted", label_kembali="menunggu persetujuan",
    izin=("rnd.approve",), peran_lama=RND_PERAN,
    hapus_field=("approval_status", "approved_by", "approved_by_name", "approved_at", "approval_notes", "po_id",
                 "po_number", "po_catatan"),
    nama=lambda d: d.get("request_number") or d.get("style_code") or d.get("id") or "",
    pemohon=lambda d: d.get("requested_by_id") or d.get("created_by_id") or d.get("created_by"),
    penyetuju=lambda d: d.get("approved_by"), hambatan=_hambatan_sampel, balikkan=_balik_sampel,
))


# ── Permintaan produk kreator (persetujuan R&D) ──
daftar(Jenis(
    kode="rnd-kreator", label="Permintaan kreator", portal="rnd", koleksi="dewi_kreator_requests",
    modul="rnd-kreator-requests", status_setuju=("approved_by_rnd",), kembali_ke="submitted",
    label_kembali="menunggu persetujuan R&D", izin=("rnd.approve", "rnd.manage"), peran_lama=RND_PERAN,
    hapus_field=("approved_by", "approved_at", "approval_notes"),
    nama=lambda d: d.get("request_number") or d.get("creator_name") or d.get("id") or "",
))


# ── Sampel maklon (disetujui staf maklon atau klien di Portal Klien) ──
daftar(Jenis(
    kode="maklon-sampel", label="Sampel maklon", portal="maklon", koleksi="dewi_maklon_samples",
    modul="maklon-pos-engine", status_setuju=("approved",), kembali_ke="submitted",
    label_kembali="menunggu persetujuan", izin=("maklon.approve", "maklon.manage"),
    peran_lama=("admin_maklon", "manager_maklon", "manager", "owner", "admin", "superadmin"),
    hapus_field=("approved_by_name", "approved_at", "approval_feedback"),
    nama=lambda d: d.get("sample_number") or d.get("sample_code") or d.get("id") or "",
))


# ── Retur material (disetujui, belum diterima gudang) ──
daftar(Jenis(
    kode="retur-material", label="Retur material", portal="production", koleksi="production_material_returns",
    modul="prod-material-returns", status_setuju=("approved",), kembali_ke="submitted",
    label_kembali="menunggu persetujuan",
    izin=("inventory.approve", "production.approve"), peran_lama=("manager", "owner", "admin", "superadmin"),
    hapus_field=("approved_by", "approved_by_id", "approved_at", "approve_note"),
    nama=lambda d: d.get("return_number") or d.get("id") or "",
    pemohon=lambda d: d.get("created_by_id") or d.get("requested_by_id"), penyetuju=lambda d: d.get("approved_by_id"),
))


# ── Permintaan Pengadaan (PR) — bertahap; yang dibatalkan = tahap terakhir yang disetujui ──
async def _hambatan_pr(db, d: dict) -> list:
    if d.get("linked_po_id"):
        po = await db.rahaza_purchase_orders.find_one({"id": d["linked_po_id"]}, {"_id": 0, "po_number": 1})
        return [f"PR ini sudah dibuatkan PO pembelian {(po or {}).get('po_number') or ''}. Batalkan PO itu dulu."]
    return []


async def _balik_pr(db, d: dict, user: dict, alasan: str) -> dict:
    await _catat_langkah(db, "dewi_procurement_requests", d, user, alasan)
    return {}


def _pr_isi(d: dict) -> dict:
    s = _langkah_setuju_terakhir(d)
    return {"current_approver_stage": s.get("stage"), "current_approver_role": s.get("stage")} if s.get("stage") else {}


daftar(Jenis(
    kode="pengadaan-pr", label="Permintaan pengadaan", portal="procurement", koleksi="dewi_procurement_requests",
    modul="proc-requests", status_setuju=("dept_approved", "finance_approved", "approved"),
    kembali_ke=lambda d: _langkah_setuju_terakhir(d).get("step") or "submitted",
    label_kembali="menunggu persetujuan tahap terakhir", isi_field=_pr_isi,
    izin=("procurement.approve", "finance.approve", "management.manage"),
    peran_lama=ATASAN + ("director", "cfo", "ceo", "manager"), hapus_field=("approved_at",),
    nama=lambda d: d.get("pr_number") or d.get("request_number") or d.get("id") or "",
    pemohon=lambda d: d.get("requester_id") or d.get("created_by_id") or d.get("created_by"),
    penyetuju=lambda d: _langkah_setuju_terakhir(d).get("actor_id"),
    hambatan=_hambatan_pr, balikkan=_balik_pr,
))


# ── Purchase Order pembelian ──
async def _hambatan_po(db, d: dict) -> list:
    pid = d.get("id")
    if await db.warehouse_receiving.count_documents({"po_id": pid}) or any(
            float((it or {}).get("qty_received") or 0) > 0 for it in d.get("items") or []):
        return ["Barang dari PO ini sudah diterima gudang. Persetujuannya tidak bisa ditarik; pakai retur pembelian."]
    if await db.rahaza_ap_invoices.count_documents({"po_id": pid, "status": {"$ne": "cancelled"}}):
        return ["PO ini sudah punya faktur pemasok. Batalkan fakturnya dulu."]
    return []


async def _balik_po(db, d: dict, user: dict, alasan: str) -> dict:
    await _catat_langkah(db, "rahaza_purchase_orders", d, user, alasan)
    return {}


def _po_isi(d: dict) -> dict:
    s = _langkah_setuju_terakhir(d) or ((d.get("approval_steps") or [{}])[-1])
    return {"current_approver_stage": s.get("stage")} if s.get("stage") else {}


daftar(Jenis(
    kode="pengadaan-po", label="PO pembelian", portal="procurement", koleksi="rahaza_purchase_orders",
    modul="proc-purchase-orders", status_setuju=("approved",), kembali_ke="pending_approval",
    label_kembali="menunggu persetujuan tahap terakhir", isi_field=_po_isi,
    izin=("procurement.approve", "finance.approve", "management.manage"),
    peran_lama=ATASAN + ("director", "cfo", "ceo", "manager"), hapus_field=("approved_at", "approved_by"),
    nama=lambda d: d.get("po_number") or d.get("id") or "",
    pemohon=lambda d: d.get("created_by_id") or d.get("created_by"), penyetuju=lambda d: d.get("approved_by"),
    hambatan=_hambatan_po, balikkan=_balik_po,
))


# ── Request Aksesoris (jalur lama yang masih disetujui di sini) ──
async def _hambatan_acc_pr(db, d: dict) -> list:
    if d.get("procurement_pr_id"):
        return ["Request ini sudah diteruskan menjadi Permintaan Pengadaan. Batalkan di Permintaan Pengadaan."]
    return []


async def _balik_acc_pr(db, d: dict, user: dict, alasan: str) -> dict:
    await _catat_langkah(db, "acc_purchase_requests", d, user, alasan)
    return {}


daftar(Jenis(
    kode="pengadaan-aksesoris", label="Request aksesoris", portal="procurement", koleksi="acc_purchase_requests",
    modul="proc-accessory-pr", status_setuju=("Approved",), kembali_ke="Submitted",
    label_kembali="menunggu persetujuan tahap terakhir", isi_field=_pr_isi,
    izin=("procurement.approve", "finance.approve", "management.manage"),
    peran_lama=ATASAN + ("director", "cfo", "ceo", "manager"), hapus_field=("approved_by", "approved_at"),
    nama=lambda d: d.get("pr_number") or d.get("request_number") or d.get("id") or "",
    hambatan=_hambatan_acc_pr, balikkan=_balik_acc_pr,
))


# ── Persetujuan bertingkat (Manajemen) ──
def _ml_isi(d: dict) -> dict:
    levels = [dict(lv) for lv in d.get("levels") or []]
    disetujui = [lv for lv in levels if lv.get("status") == "approved"]
    if not disetujui:
        return {}
    akhir = max(disetujui, key=lambda lv: int(lv.get("level") or 0))
    for lv in levels:
        if lv.get("level") == akhir.get("level"):
            for k in ("approver_id", "approver_name", "note", "actioned_at"):
                lv.pop(k, None)
            lv["status"] = "pending"
    return {"levels": levels, "current_level": akhir.get("level"), "completed_at": None}


daftar(Jenis(
    kode="persetujuan-bertingkat", label="Persetujuan bertingkat", portal="management", koleksi="approval_requests",
    modul="approval-multilevel", status_setuju=("approved",), kembali_ke="pending",
    label_kembali="menunggu persetujuan tingkat terakhir", isi_field=_ml_isi,
    filter_tambahan={"levels": {"$exists": True}},
    izin=("mod.mgmt_approval.approve", "management.manage"), peran_lama=ATASAN + ("manager",),
    nama=lambda d: d.get("subject") or d.get("ref_code") or d.get("id") or "",
    pemohon=lambda d: d.get("requester_id"), waktu_setuju="completed_at",
))
