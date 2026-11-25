"""core.batal_setuju — SATU mesin "Batalkan persetujuan" untuk semua persetujuan di sistem.

Permintaan owner 24 Nov 2026 ("buat saja fitur batalkan persetujuan. ini berlaku untuk semua hal yang ada di
sistem"). Pemicunya: style R&D DA-0006 disetujui dengan catatan "Tidak pantas" (salah tekan), lalu tidak bisa
dihapus, diarsipkan, maupun ditolak — persetujuan tidak punya jalan mundur.

Aturan yang sama untuk semua jenis dokumen:
  1. Hanya dokumen yang statusnya DISETUJUI (status persis yang ditulis tombol Setujui) yang bisa dibatalkan.
  2. Yang boleh membatalkan = yang boleh menyetujui jenis itu (izin/centang yang sama dengan tombol Setujui).
  3. Alasan wajib (minimal 10 huruf). Siapa, kapan, status lama → baru, dan alasannya tersimpan di dokumen
     (`riwayat_persetujuan`) dan di Log Aktivitas. Keputusan lama TIDAK dihapus — hanya ditandai dibatalkan.
  4. Bila persetujuan itu SUDAH DIPAKAI langkah berikutnya (PO sudah diterima gudang, style sudah dipromosikan,
     gaji periode itu sudah final, faktur sudah dibayar, dst.), pembatalan DITOLAK (409) dengan kalimat yang
     menyebut langkah mana yang menahannya — urungkan langkah itu dulu lewat menunya sendiri.
  5. Efek yang muncul TEPAT saat disetujui (jurnal, saldo cuti, stok, dokumen turunan yang masih draf) dibalik
     oleh fungsi `balikkan` jenis itu — lewat jalur resmi yang sudah ada (jurnal pembalik, batal draf), bukan
     menghapus diam-diam.
  6. Status kembali ke status SEBELUM disetujui (menunggu persetujuan), sehingga dokumen bisa diputus ulang:
     disetujui lagi, ditolak, diubah, atau dihapus sesuai aturan menunya.
  7. Pemohon (dan penyetuju lama bila orang lain) mendapat notifikasi.

Setiap jenis didaftarkan sekali di `JENIS` (lihat `core.batal_setuju_jenis`) — layar memanggil satu endpoint
`POST /api/batal-setuju/{jenis}/{id}` dan satu komponen `BatalkanPersetujuan`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException

log = logging.getLogger(__name__)

MIN_ALASAN = 10
RIWAYAT = "riwayat_persetujuan"


def _now() -> datetime:
    return datetime.now(timezone.utc)


Hambatan = Callable[[object, dict], Awaitable[list]]        # (db, doc) -> ["kalimat penahan", ...]
Balikkan = Callable[[object, dict, dict, str], Awaitable[dict]]  # (db, doc, user, alasan) -> ringkasan


@dataclass
class Jenis:
    """Satu jenis persetujuan."""
    kode: str                       # kunci URL, mis. "rnd-style"
    label: str                      # untuk staf, mis. "Style R&D"
    portal: str                     # portal pemilik (untuk centang & tautan)
    koleksi: str                    # koleksi Mongo dokumen
    status_setuju: tuple            # status setelah tombol Setujui, mis. ("approved_for_launch",)
    kembali_ke: str | Callable[[dict], str]  # status sebelum disetujui
    izin: tuple = ()                # kunci izin yang dipakai tombol Setujui (assert_can_act)
    peran_lama: tuple = ()          # legacy_roles tombol Setujui
    field_status: str = "status"
    field_id: str = "id"
    hapus_field: tuple = ()         # field jejak persetujuan yang dikosongkan (nilai lama disalin ke riwayat)
    isi_field: dict | Callable[[dict], dict] = field(default_factory=dict)  # field yang diisi ulang (boleh fungsi(doc))
    nama: Callable[[dict], str] = lambda d: str(d.get("code") or d.get("number") or d.get("id") or "")
    pemohon: Callable[[dict], Optional[str]] = lambda d: d.get("created_by_id") or d.get("requested_by_id")
    penyetuju: Callable[[dict], Optional[str]] = lambda d: d.get("approved_by_id")
    waktu_setuju: str = "approved_at"   # untuk daftar "Sudah disetujui" di Pusat Persetujuan
    hambatan: Optional[Hambatan] = None
    balikkan: Optional[Balikkan] = None
    label_kembali: str = "menunggu persetujuan"
    modul: str = ""                 # id menu layar asal (untuk tautan dari Pusat Persetujuan)
    filter_tambahan: dict = field(default_factory=dict)  # mis. {"kind": "leave"} bila satu koleksi banyak jenis

    def status_kembali(self, doc: dict) -> str:
        return self.kembali_ke(doc) if callable(self.kembali_ke) else self.kembali_ke


JENIS: dict[str, Jenis] = {}


def daftar(j: Jenis) -> Jenis:
    if j.kode in JENIS:
        raise RuntimeError(f"Jenis batal-setuju ganda: {j.kode}")
    JENIS[j.kode] = j
    return j


def ambil_jenis(kode: str) -> Jenis:
    _muat()
    j = JENIS.get(kode)
    if not j:
        raise HTTPException(404, "Jenis persetujuan tidak dikenal.")
    return j


def _muat():
    # selalu impor (di-cache Python): modul domain bisa saja sudah terimpor lebih dulu sehingga JENIS tidak kosong
    from core import batal_setuju_jenis  # noqa: F401 — mengisi JENIS


def periksa_izin(j: Jenis, user: dict):
    from routes.shared import assert_can_act
    assert_can_act(user, *j.izin, portal=None, legacy_roles=j.peran_lama,
                   what=f"membatalkan persetujuan {j.label.lower()}")


async def _dok(db, j: Jenis, doc_id: str) -> dict:
    q = {j.field_id: doc_id, **j.filter_tambahan}
    doc = await db[j.koleksi].find_one(q, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"{j.label} tidak ditemukan.")
    return doc


async def _nama_karyawan(db, docs: list) -> dict:
    """{employee_id: nama} untuk dokumen yang hanya menyimpan employee_id (mis. pengajuan cuti lama)."""
    ids = sorted({d.get("employee_id") for d in docs if d.get("employee_id") and not d.get("employee_name")})
    if not ids:
        return {}
    try:
        rows = await db.rahaza_employees.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(len(ids))
    except Exception:  # noqa: BLE001 — nama hanya untuk tampilan
        log.exception("nama karyawan untuk batal_setuju gagal dimuat")
        return {}
    return {r["id"]: r["name"] for r in rows if r.get("id") and r.get("name")}


def _nama_dengan(j: Jenis, doc: dict, karyawan: dict) -> str:
    nm = karyawan.get(doc.get("employee_id")) if not doc.get("employee_name") else None
    return j.nama({**doc, "employee_name": nm} if nm else doc)


async def nama_tampil(db, j: Jenis, doc: dict) -> str:
    """Nama dokumen untuk layar, pesan, dan notifikasi (nama karyawan dilengkapi bila dokumen tidak menyimpannya)."""
    return _nama_dengan(j, doc, await _nama_karyawan(db, [doc]))


async def cek(db, j: Jenis, doc: dict) -> dict:
    """Bisa dibatalkan? → {boleh, hambatan[], status, kembali_ke}. Tidak mengubah apa pun."""
    status = doc.get(j.field_status)
    if status not in j.status_setuju:
        return {"boleh": False, "status": status, "kembali_ke": None,
                "hambatan": [f"{j.label} ini tidak berstatus disetujui, jadi tidak ada persetujuan yang bisa dibatalkan."]}
    hambatan = list(await j.hambatan(db, doc)) if j.hambatan else []
    return {"boleh": not hambatan, "status": status, "kembali_ke": j.status_kembali(doc), "hambatan": hambatan}


async def _pulihkan(db, j: Jenis, doc_id: str, doc: dict, status_baru: str, kunci: list) -> None:
    """Kembalikan dokumen ke keadaan sebelum `batalkan` bila langkah sesudah kunci gagal."""
    set_, unset_ = {"updated_at": _now()}, {}
    for k in kunci:
        if k == "updated_at":
            continue
        if k in doc:
            set_[k] = doc[k]
        else:
            unset_[k] = ""
    upd = {"$set": set_}
    if unset_:
        upd["$unset"] = unset_
    try:
        await db[j.koleksi].update_one({j.field_id: doc_id, j.field_status: status_baru, **j.filter_tambahan}, upd)
    except Exception:  # noqa: BLE001 — galat asli tetap yang dilaporkan
        log.exception("batal_setuju: gagal memulihkan %s %s", j.kode, doc_id)


async def batalkan(db, kode: str, doc_id: str, user: dict, alasan: str) -> dict:
    j = ambil_jenis(kode)
    periksa_izin(j, user)
    alasan = (alasan or "").strip()
    if len(alasan) < MIN_ALASAN:
        raise HTTPException(400, f"Alasan pembatalan wajib diisi (minimal {MIN_ALASAN} huruf).")
    doc = await _dok(db, j, doc_id)
    hasil_cek = await cek(db, j, doc)
    if not hasil_cek["boleh"]:
        raise HTTPException(409, "Persetujuan tidak bisa dibatalkan: " + " ".join(hasil_cek["hambatan"]))

    status_lama = doc.get(j.field_status)
    status_baru = j.status_kembali(doc)
    now = _now()
    oleh = user.get("name") or user.get("email") or ""
    jejak_lama = {f: doc.get(f) for f in j.hapus_field if doc.get(f) not in (None, "", [])}
    isi = j.isi_field(doc) if callable(j.isi_field) else dict(j.isi_field)
    set_ = {j.field_status: status_baru, "updated_at": now, "persetujuan_dibatalkan": True,
            "persetujuan_dibatalkan_oleh": oleh, "persetujuan_dibatalkan_at": now,
            "persetujuan_dibatalkan_alasan": alasan, **isi}
    unset_ = [f for f in j.hapus_field if f not in set_]
    upd = {"$set": set_}
    if unset_:
        upd["$unset"] = {f: "" for f in unset_}
    q = {j.field_id: doc_id, j.field_status: status_lama, **j.filter_tambahan}
    # 1) KUNCI DULU (Paket 1 audit 25 Nov): status pindah atomik SEBELUM efek dibalik — permintaan kedua, atau
    #    pembayaran/langkah lanjutan yang datang belakangan, melihat status baru. Dulu jurnal di-void lebih dulu,
    #    sehingga pembayaran yang masuk di antara cek dan update meninggalkan jurnal batal tanpa status berubah.
    res = await db[j.koleksi].update_one(q, upd)
    if not res.matched_count:
        raise HTTPException(409, f"{j.label} baru saja diubah orang lain. Muat ulang lalu coba lagi.")
    try:
        # 2) Cek ulang hambatan pada data terbaru (menutup celah "dipakai langkah berikutnya" di antara cek dan kunci).
        if j.hambatan:
            terbaru = await db[j.koleksi].find_one({j.field_id: doc_id, **j.filter_tambahan}, {"_id": 0}) or doc
            hambatan = list(await j.hambatan(db, {**terbaru, j.field_status: status_lama}))
            if hambatan:
                raise HTTPException(409, "Persetujuan tidak bisa dibatalkan: " + " ".join(hambatan))
        # 3) Balikkan efek persetujuan (jurnal, saldo, dll.).
        ringkas_balik = (await j.balikkan(db, doc, user, alasan) or {}) if j.balikkan else {}
    except BaseException:
        await _pulihkan(db, j, doc_id, doc, status_baru, list(set_) + unset_)
        raise

    entri = {
        "aksi": "batal_setuju", "oleh": oleh, "oleh_id": user.get("id") or "",
        "waktu": now, "alasan": alasan, "status_lama": status_lama, "status_baru": status_baru,
        "persetujuan_lama": jejak_lama, "dibalik": ringkas_balik,
    }
    await db[j.koleksi].update_one({j.field_id: doc_id, **j.filter_tambahan}, {"$push": {RIWAYAT: entri}})

    nama = await nama_tampil(db, j, doc)
    try:
        from auth import log_activity
        await log_activity(user.get("id") or "", user.get("name") or "", "batal_setuju", f"{j.portal}.{j.kode}",
                           f"{j.label} {nama}: {status_lama} → {status_baru}. Alasan: {alasan}")
    except Exception:  # noqa: BLE001 — log tidak boleh menggagalkan pembatalan yang sudah tersimpan
        log.exception("log_activity batal_setuju gagal")
    await _kabari(db, j, doc, user, nama, alasan, status_baru)
    return {"ok": True, "jenis": j.kode, "id": doc_id, "nama": nama, "status_lama": status_lama,
            "status_baru": status_baru, "dibalik": ringkas_balik,
            "pesan": f"Persetujuan {j.label.lower()} {nama} dibatalkan. Status kembali: {j.label_kembali}."}


async def _kabari(db, j: Jenis, doc: dict, user: dict, nama: str, alasan: str, status_baru: str):
    try:
        from routes.notifications import create_notification
    except Exception:  # noqa: BLE001
        return
    tujuan = {u for u in (j.pemohon(doc), j.penyetuju(doc)) if u and u != user.get("id")}
    for uid in tujuan:
        try:
            await create_notification(
                db, uid, "approval", f"Persetujuan dibatalkan: {j.label} {nama}",
                f"{user.get('name') or 'Atasan'} membatalkan persetujuan. Alasan: {alasan}. "
                f"Status kembali {j.label_kembali}.",
                source_type=j.kode, source_id=doc.get(j.field_id) or "", metadata={"status": status_baru})
        except Exception:  # noqa: BLE001
            log.exception("notifikasi batal_setuju gagal untuk %s", uid)


async def disetujui_terbaru(db, user: dict, hari: int = 30, batas: int = 300) -> list:
    """Dokumen yang disetujui dalam `hari` terakhir, dari SEMUA jenis yang boleh diputus pengguna ini."""
    from datetime import timedelta
    from routes.shared import can_act, lolos_centang
    _muat()
    sejak = _now() - timedelta(days=max(1, min(int(hari or 30), 366)))
    sejak_iso = sejak.isoformat()
    hasil = []
    for j in JENIS.values():
        if not (can_act(user, *j.izin, legacy_roles=j.peran_lama) or lolos_centang(user)):
            continue
        q = {j.field_status: {"$in": list(j.status_setuju)}, **j.filter_tambahan,
             "$or": [{j.waktu_setuju: {"$gte": sejak}}, {j.waktu_setuju: {"$gte": sejak_iso}}]}
        try:
            docs = await db[j.koleksi].find(q, {"_id": 0}).sort(j.waktu_setuju, -1).limit(batas).to_list(batas)
        except Exception:  # noqa: BLE001 — satu koleksi bermasalah tidak menjatuhkan daftar
            log.exception("disetujui_terbaru gagal untuk %s", j.kode)
            continue
        karyawan = await _nama_karyawan(db, docs)
        for d in docs:
            w = d.get(j.waktu_setuju)
            hasil.append({"jenis": j.kode, "label": j.label, "portal": j.portal, "modul": j.modul,
                          "id": d.get(j.field_id), "nama": _nama_dengan(j, d, karyawan), "status": d.get(j.field_status),
                          "disetujui_at": w.isoformat() if hasattr(w, "isoformat") else w,
                          "disetujui_oleh": d.get("approved_by_name") or d.get("approved_by") or d.get("owner_reviewed_by") or ""})
    hasil.sort(key=lambda r: str(r.get("disetujui_at") or ""), reverse=True)
    return hasil[:batas]
