"""Pengingat kewajiban (keputusan owner K5, 10 Nov 2026): staf diingatkan saat jatuh tempo, lalu yang terlambat
lebih dari 1 hari kerja masuk ringkasan harian owner/admin. Tanpa atasan.

Bel sudah banjir (7.723 notifikasi tidak dibaca di salinan VPS 9 Nov), jadi:
  * staf: SATU pesan ringkas per hari ("2 terlambat, 1 jatuh tempo hari ini: …"), bukan satu pesan per dokumen;
  * owner/admin: SATU ringkasan per hari;
  * tombol "Ingatkan" di layar: satu pesan per kejadian per hari.
Penulis notifikasi = `routes.rahaza_notifications.publish_notification` (SSOT `notifications`), dedup 24 jam.
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.pantau_staf.pemindai import KEJADIAN, TERBUKA, akun_internal
from core.pantau_staf.waktu import muat_kalender, ts
from utils.waktu import now_utc, to_wib, wib_date_str

log = logging.getLogger(__name__)

PENERIMA_RINGKASAN = ("owner", "superadmin", "admin")
MAKS_BARIS = 5
SEHARI_MENIT = 24 * 60


_BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def label_dokumen(k: dict) -> str:
    """Nomor dokumen, atau untuk kewajiban harian "Toko A · 9 Nov" (bukan "2026-11-09")."""
    nomor, periode = k.get("nomor") or "", k.get("periode") or ""
    if periode and len(periode) >= 10:
        try:
            tgl = f"{int(periode[8:10])} {_BULAN[int(periode[5:7]) - 1]}"
        except (ValueError, IndexError):
            tgl = periode
        return f"{nomor} · {tgl}" if nomor and nomor != periode else tgl
    return nomor


def _baris(k: dict) -> str:
    dok = label_dokumen(k)
    return f"• {k.get('nama')}" + (f" {dok}" if dok else "")


def susun_pesan_staf(items: list, hari_ini) -> tuple[str, str] | None:
    """(judul, isi) pesan harian satu staf — None bila tidak ada yang perlu diingatkan."""
    telat = [k for k in items if k.get("status") == "terlambat"]
    hari = [k for k in items if k.get("status") == "menunggu" and k.get("tenggat")
            and to_wib(ts(k["tenggat"])).date() <= hari_ini]
    if not telat and not hari:
        return None
    bagian = []
    if telat:
        bagian.append(f"{len(telat)} terlambat")
    if hari:
        bagian.append(f"{len(hari)} jatuh tempo hari ini")
    judul = "Kewajiban sistem Anda: " + ", ".join(bagian)
    daftar = [_baris(k) for k in (telat + hari)[:MAKS_BARIS]]
    sisa = len(telat) + len(hari) - len(daftar)
    isi = "\n".join(daftar + ([f"…dan {sisa} lainnya"] if sisa > 0 else [])) + \
        "\nBuka Portal Saya › Dashboard untuk melihat semuanya."
    return judul, isi


async def kirim_harian(db, *, kini: datetime | None = None) -> dict:
    from routes.rahaza_notifications import publish_notification
    kini = kini or now_utc()
    kal = await muat_kalender(db)
    hari_ini = to_wib(kini).date()
    if not kal.kerja(hari_ini):
        return {"dikirim": 0, "alasan": "hari libur"}
    tgl = wib_date_str(kini)
    users = {u["id"]: u for u in await akun_internal(db)}
    rows = await db[KEJADIAN].find({"status": {"$in": list(TERBUKA)}}, {"_id": 0}).to_list(20000)
    per: dict = {}
    for k in rows:
        for uid in k.get("pemegang_ids") or []:
            per.setdefault(uid, []).append(k)
    terkirim = 0
    for uid, items in per.items():
        if uid not in users:
            continue
        pesan = susun_pesan_staf(items, hari_ini)
        if not pesan:
            continue
        try:
            await publish_notification(
                db, type_="kewajiban_pengingat", severity="warning", title=pesan[0], message=pesan[1],
                link_module="portal-dashboard", target_user_ids=[uid], dedup_key=f"kewajiban_{uid}_{tgl}",
                dedup_minutes=SEHARI_MENIT)
            terkirim += 1
        except Exception:  # noqa: BLE001
            log.warning("[pantau-staf] pengingat ke %s gagal", uid, exc_info=True)
    # ringkasan owner/admin: terlambat > 1 hari kerja
    berat = [k for k in rows if k.get("status") == "terlambat" and ts(k.get("tenggat"))
             and kal.hari_kerja_lewat(ts(k["tenggat"]), kini) >= 1]
    tanpa = [k for k in rows if not k.get("pemegang_ids")]
    ringkas = 0
    if berat or tanpa:
        hitung: dict = {}
        for k in berat:
            for uid in k.get("pemegang_ids") or []:
                hitung[uid] = hitung.get(uid, 0) + 1
        teratas = sorted(hitung.items(), key=lambda x: -x[1])[:MAKS_BARIS]
        daftar = [f"• {(users.get(u) or {}).get('name') or u}: {n}" for u, n in teratas]
        if tanpa:
            daftar.append(f"• {len(tanpa)} kewajiban belum punya penanggung jawab")
        penerima = [uid for uid, u in users.items() if (u.get("role") or "").lower() in PENERIMA_RINGKASAN]
        if penerima:
            try:
                await publish_notification(
                    db, type_="kewajiban_ringkasan_owner", severity="warning",
                    title=f"{len(berat)} kewajiban staf terlambat lebih dari 1 hari kerja",
                    message="\n".join(daftar) + "\nBuka Manajemen › Pemantauan Staf.",
                    link_module="pantau-staf", target_user_ids=penerima, dedup_key=f"kewajiban_owner_{tgl}",
                    dedup_minutes=SEHARI_MENIT)
                ringkas = 1
            except Exception:  # noqa: BLE001
                log.warning("[pantau-staf] ringkasan owner gagal", exc_info=True)
    return {"dikirim": terkirim, "ringkasan_owner": ringkas, "tanggal": tgl}


async def ingatkan_satu(db, kejadian: dict, *, oleh: dict) -> int:
    """Tombol "Ingatkan" di layar Monitoring: satu pesan ke pemegang kejadian ini (sekali per hari)."""
    from routes.rahaza_notifications import publish_notification
    peg = kejadian.get("pemegang_ids") or []
    if not peg:
        return 0
    tgl = wib_date_str()
    dok = label_dokumen(kejadian)
    nomor = f" {dok}" if dok else ""
    await publish_notification(
        db, type_="kewajiban_pengingat", severity="warning",
        title=f"Mohon dikerjakan: {kejadian.get('nama')}{nomor}",
        message=(f"{oleh.get('name') or 'Manajemen'} mengingatkan langkah ini belum dikerjakan di sistem. "
                 "Buka Portal Saya › Dashboard untuk melihat kewajiban Anda."),
        link_module=kejadian.get("link_module") or "portal-dashboard", link_params=kejadian.get("link_params"),
        target_user_ids=peg, dedup_key=f"kewajiban_ingat_{kejadian.get('id')}_{tgl}", dedup_minutes=SEHARI_MENIT)
    await db[KEJADIAN].update_one({"id": kejadian["id"]}, {"$set": {"pengingat_terakhir": now_utc()}})
    return len(peg)


async def job_harian() -> dict:
    from database import get_db
    db = get_db()
    mulai = now_utc()
    run = await db.dewi_scheduler_runs.insert_one({"job_id": "pantau_staf_pengingat", "started_at": mulai,
                                                   "status": "running"})
    try:
        hasil = await kirim_harian(db)
        await db.dewi_scheduler_runs.update_one({"_id": run.inserted_id}, {"$set": {
            "status": "success", "finished_at": now_utc(), **{k: v for k, v in hasil.items() if k != "tanggal"}}})
        return hasil
    except Exception as e:  # noqa: BLE001
        log.exception("[pantau-staf] pengingat harian gagal")
        await db.dewi_scheduler_runs.update_one({"_id": run.inserted_id}, {"$set": {
            "status": "failed", "finished_at": now_utc(), "error": str(e)[:300]}})
        raise
