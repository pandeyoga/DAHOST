"""Pemindai kewajiban — tiap 15 menit (job `pantau_staf_pindai`), idempoten.

Untuk setiap aturan aktif: jalankan detektor titiknya → setiap objek yang SUDAH terpicu menjadi satu kejadian
(`kewajiban_kejadian`, id `<aturan>:<objek>`):

    menunggu   belum ada bukti selesai, batas waktu belum lewat
    terlambat  belum ada bukti selesai, batas waktu sudah lewat
    selesai    ada bukti di data; `tepat` = selesai sebelum batas; `oleh_orang_lain` = pelaku bukan pemegang (K8)
    terlewat   kewajiban berkala yang tidak bisa dikerjakan lagi (hari tanpa aktivitas, lembar ditutup sistem)
    batal      dokumen dibatalkan/dihapus/keluar saringan, atau aturan dinonaktifkan
    dimaafkan  dimaafkan owner/admin, atau pemegang cuti/izin tanpa cadangan (K7)

Kejadian yang sudah final tidak diubah lagi. Kejadian sebelum aturan berlaku (`berlaku_sejak`) tidak dibuat.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from core.pantau_staf import aturan as _aturan
from core.pantau_staf.katalog import ALUR_LABEL, KATALOG, Konteks, Temuan
from core.pantau_staf.waktu import hitung_tenggat, muat_kalender, tanggal_wib, ts
from utils.waktu import now_utc, to_wib

log = logging.getLogger(__name__)

KEJADIAN = "kewajiban_kejadian"
TERBUKA = ("menunggu", "terlambat")
FINAL = ("selesai", "batal", "dimaafkan", "terlewat")
EKSTERNAL = ("vendor", "cmt_vendor", "buyer", "klien_maklon")
JENDELA_HARI = 45
_KUNCI: dict = {}


def pengguna_aktif(u: dict | None) -> bool:
    """Aturan yang sama dengan `auth._load_live_user` (akun nonaktif/terblokir = tidak aktif)."""
    if not u:
        return False
    return not (u.get("is_active") is False or (u.get("status") not in (None, "active") and not u.get("active", True)))


async def akun_internal(db) -> list[dict]:
    rows = await db.users.find({"role": {"$nin": list(EKSTERNAL)}}, {
        "_id": 0, "id": 1, "name": 1, "email": 1, "role": 1, "employee_id": 1, "department": 1,
        "is_active": 1, "active": 1, "status": 1, "last_login_at": 1}).to_list(2000)
    return [u for u in rows if u.get("id") and pengguna_aktif(u)]


async def siapkan_konteks(db, kini: datetime | None = None, hari: int = JENDELA_HARI) -> Konteks:
    kini = kini or now_utc()
    users = {u["id"]: u for u in await akun_internal(db)}
    nama, email = {}, {}
    for uid, u in users.items():
        if u.get("name"):
            nama.setdefault(str(u["name"]).strip().lower(), []).append(uid)
        if u.get("email"):
            email[str(u["email"]).strip().lower()] = uid
    kal = await muat_kalender(db)
    return Konteks(db=db, kini=kini, sejak=kini - timedelta(days=hari), kal=kal, users=users,
                   nama_ke_id=nama, email_ke_id=email)


def cocok_saringan(aturan: dict, t: Temuan) -> bool:
    for k, v in (aturan.get("saringan") or {}).items():
        if v in (None, "", []):
            continue
        nilai = (t.lingkup or {}).get(k)
        if isinstance(v, list):
            if nilai not in v:
                return False
        elif nilai != v:
            return False
    return True


def pemegang(aturan: dict, t: Temuan, ctx: Konteks) -> list[str]:
    p = aturan.get("pemegang") or {}
    jenis = p.get("jenis")
    if jenis == "akun":
        ids = list(p.get("akun_ids") or [])
    elif jenis == "peran":
        peran = set(p.get("peran") or [])
        ids = [uid for uid, u in ctx.users.items() if (u.get("role") or "") in peran]
    else:
        ids = list(t.pemegang_data or [])
    ex = set(aturan.get("dikecualikan_ids") or [])
    return [i for i in dict.fromkeys(ids) if i in ctx.users and i not in ex]


async def akun_cuti_hari_ini(ctx: Konteks) -> set:
    """Akun yang hari ini (WIB) cuti disetujui atau absen izin/sakit — K7."""
    if "cuti" in ctx.cache:
        return ctx.cache["cuti"]
    hari = to_wib(ctx.kini).date().isoformat()
    emp = {u.get("employee_id"): uid for uid, u in ctx.users.items() if u.get("employee_id")}
    out = set()
    if emp:
        for lv in await ctx.db.rahaza_leave_requests.find(
                {"status": "approved", "employee_id": {"$in": list(emp)}, "from_date": {"$lte": hari},
                 "to_date": {"$gte": hari}}, {"_id": 0, "employee_id": 1}).to_list(2000):
            if lv.get("employee_id") in emp:
                out.add(emp[lv["employee_id"]])
        for ev in await ctx.db.rahaza_attendance_events.find(
                {"date": hari, "employee_id": {"$in": list(emp)}, "status": {"$in": ["izin", "sakit", "cuti"]}},
                {"_id": 0, "employee_id": 1}).to_list(2000):
            if ev.get("employee_id") in emp:
                out.add(emp[ev["employee_id"]])
    ctx.cache["cuti"] = out
    return out


def nilai_status(t: Temuan, tenggat: datetime | None, kini: datetime) -> tuple[str, bool | None]:
    if t.batal:
        return "batal", None
    if t.selesai_at:
        return "selesai", (tenggat is None or t.selesai_at <= tenggat)
    if t.terlewat:
        return "terlewat", False
    if tenggat is not None and kini > tenggat:
        return "terlambat", None
    return "menunggu", None


def _sebelum_berlaku(t: Temuan, berlaku: datetime) -> bool:
    """Objek yang sudah tuntas/dimulai sebelum aturan berlaku tidak dijadikan kewajiban."""
    if t.periode:
        d = tanggal_wib(t.periode)
        return d is not None and d < to_wib(berlaku).date()
    if t.selesai_at and t.selesai_at < berlaku:
        return True
    return False


def _dok(aturan: dict, t: Temuan, *, kini, mulai, tenggat, status, tepat, peg, dialihkan, maaf=None) -> dict:
    titik = KATALOG[aturan["titik"]]
    oleh_lain = bool(status == "selesai" and t.pelaku_id and peg and t.pelaku_id not in peg and not t.pelaku_vendor)
    d = {
        "aturan_id": aturan["id"], "titik": titik.id, "nama": titik.nama, "alur": titik.alur,
        "alur_label": ALUR_LABEL.get(titik.alur, titik.alur), "jenis": titik.jenis,
        "objek_id": t.objek_id, "nomor": t.nomor, "po_id": t.po_id, "periode": t.periode,
        "keterangan": t.keterangan, "link_module": t.link_module or titik.link_module,
        "link_params": t.link_params, "lingkup": t.lingkup or {},
        "pemegang_ids": peg, "dialihkan_ke_cadangan": dialihkan,
        "mulai": mulai, "tenggat": tenggat, "status": status, "tepat": tepat,
        "selesai_at": t.selesai_at if status == "selesai" else None,
        "pelaku_id": t.pelaku_id, "pelaku_nama": t.pelaku_nama, "pelaku_vendor": t.pelaku_vendor,
        "oleh_orang_lain": oleh_lain, "bobot": int(aturan.get("bobot") or 1),
        "tanpa_waktu": bool(titik.tanpa_waktu and t.mulai is None),
        "diperbarui_at": kini,
    }
    if maaf:
        d["dimaafkan"] = maaf
    return d


async def terapkan(db, ctx: Konteks, aturan: dict, temuan: list) -> dict:
    """Satukan temuan detektor dengan kejadian tersimpan untuk satu aturan. Mengembalikan hitungan."""
    titik = KATALOG[aturan["titik"]]
    kini = ctx.kini
    berlaku = ts(aturan.get("berlaku_sejak")) or kini
    temuan = [t for t in temuan if cocok_saringan(aturan, t)]
    objek = [t.objek_id for t in temuan]
    tersimpan = {}
    for i in range(0, len(objek), 1000):
        for k in await db[KEJADIAN].find({"aturan_id": aturan["id"], "objek_id": {"$in": objek[i:i + 1000]}},
                                         {"_id": 0, "objek_id": 1, "status": 1, "pertama_terlihat": 1,
                                          "mulai": 1}).to_list(1000):
            tersimpan[k["objek_id"]] = k
    terbuka_lama = {k["objek_id"]: k for k in await db[KEJADIAN].find(
        {"aturan_id": aturan["id"], "status": {"$in": list(TERBUKA)}}, {"_id": 0}).to_list(20000)}
    cuti = await akun_cuti_hari_ini(ctx)
    hari_ini = to_wib(kini).date()
    n = {"baru": 0, "diubah": 0, "ditutup": 0}

    async def simpan(t: Temuan, ada: dict | None):
        if ada and ada.get("status") in FINAL:
            return
        if ada is None and (t.batal or _sebelum_berlaku(t, berlaku)):
            return
        pertama = ts((ada or {}).get("pertama_terlihat")) or kini
        mulai = t.mulai or pertama
        if mulai < berlaku:
            mulai = berlaku
        tenggat = hitung_tenggat(aturan.get("tenggat") or titik.tenggat, kal=ctx.kal, mulai=mulai,
                                 periode=t.periode, tenggat_dokumen=t.tenggat_dokumen)
        if tenggat is None:
            tenggat = ctx.kal.tambah_hari_kerja(mulai, 1)
        status, tepat = nilai_status(t, tenggat, kini)
        peg = pemegang(aturan, t, ctx)
        dialihkan, maaf = False, None
        jatuh_tempo = status == "terlambat" or (status == "menunggu" and to_wib(tenggat).date() <= hari_ini)
        if jatuh_tempo and peg and all(u in cuti for u in peg):
            cad = [c for c in (aturan.get("cadangan_ids") or []) if c in ctx.users and c not in cuti]
            if cad:
                peg, dialihkan = cad, True
            else:
                status, maaf = "dimaafkan", {"oleh_id": None, "oleh_nama": "Sistem",
                                             "alasan": "Pemegang cuti/izin dan tidak ada cadangan", "at": kini}
        doc = _dok(aturan, t, kini=kini, mulai=mulai, tenggat=tenggat, status=status, tepat=tepat, peg=peg,
                   dialihkan=dialihkan, maaf=maaf)
        kid = f"{aturan['id']}:{t.objek_id}"
        await db[KEJADIAN].update_one({"id": kid}, {
            "$set": doc, "$setOnInsert": {"id": kid, "pertama_terlihat": pertama, "dibuat_at": kini}}, upsert=True)
        n["baru" if ada is None else "diubah"] += 1

    dilihat = set()
    for t in temuan:
        dilihat.add(t.objek_id)
        await simpan(t, tersimpan.get(t.objek_id))
    # kejadian terbuka yang objeknya tidak muncul lagi
    for oid, k in terbuka_lama.items():
        if oid in dilihat:
            continue
        akhir = None
        if titik.nasib:
            try:
                akhir = await titik.nasib(ctx, k)
            except Exception:  # noqa: BLE001
                log.debug("[pantau-staf] nasib %s gagal", oid, exc_info=True)
        if akhir is not None:
            status, tepat = nilai_status(akhir, ts(k.get("tenggat")), kini)
            peg = k.get("pemegang_ids") or []
            upd = {"status": status, "tepat": tepat, "diperbarui_at": kini,
                   "selesai_at": akhir.selesai_at if status == "selesai" else None,
                   "pelaku_id": akhir.pelaku_id, "pelaku_nama": akhir.pelaku_nama,
                   "oleh_orang_lain": bool(status == "selesai" and akhir.pelaku_id and peg
                                           and akhir.pelaku_id not in peg)}
        else:
            berkala = titik.jenis == "berkala"
            upd = {"status": "terlewat" if berkala else "batal", "tepat": False if berkala else None,
                   "diperbarui_at": kini,
                   "alasan_tutup": ("Tidak dikerjakan sampai melewati jendela pantauan" if berkala
                                    else "Tidak lagi menunggu (dibatalkan, dihapus, atau di luar saringan aturan)")}
        await db[KEJADIAN].update_one({"id": k["id"]}, {"$set": upd})
        n["ditutup"] += 1
    return n


async def tutup_aturan_nonaktif(db, aturan: dict, kini: datetime) -> int:
    res = await db[KEJADIAN].update_many(
        {"aturan_id": aturan["id"], "status": {"$in": list(TERBUKA)}},
        {"$set": {"status": "batal", "diperbarui_at": kini, "alasan_tutup": "Aturan dinonaktifkan"}})
    return getattr(res, "modified_count", 0) or 0


def _kunci_proses() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    k = _KUNCI.get(id(loop))
    if k is None:
        _KUNCI.clear()
        k = _KUNCI[id(loop)] = asyncio.Lock()
    return k


async def pindai(db, *, kini: datetime | None = None, hanya: list | None = None) -> dict:
    """Satu putaran pemindaian semua aturan aktif. Satu proses hanya menjalankan satu putaran sekaligus."""
    kunci = _kunci_proses()
    if kunci.locked():
        return {"status": "sedang_berjalan"}
    async with kunci:
        ctx = await siapkan_konteks(db, kini)
        hasil: dict = {"status": "ok", "mulai": ctx.kini, "aturan": {}}
        for a in await _aturan.semua(db, kini=ctx.kini):
            if hanya and a["id"] not in hanya:
                continue
            if not a.get("aktif"):
                ditutup = await tutup_aturan_nonaktif(db, a, ctx.kini)
                if ditutup:
                    hasil["aturan"][a["id"]] = {"ditutup": ditutup}
                continue
            titik = KATALOG[a["titik"]]
            kunci_det = f"det:{titik.id}"
            try:
                if kunci_det not in ctx.cache:
                    ctx.cache[kunci_det] = await titik.deteksi(ctx)
                hasil["aturan"][a["id"]] = await terapkan(db, ctx, a, ctx.cache[kunci_det])
            except Exception as e:  # noqa: BLE001 — satu titik gagal tidak menghentikan yang lain
                log.exception("[pantau-staf] titik %s gagal", titik.id)
                hasil["aturan"][a["id"]] = {"galat": str(e)[:200]}
        hasil["selesai"] = now_utc()
        return hasil


async def job_pindai() -> dict:
    """Dipanggil penjadwal tiap 15 menit; mencatat jalan ke `dewi_scheduler_runs`."""
    from database import get_db
    db = get_db()
    mulai = now_utc()
    run = await db.dewi_scheduler_runs.insert_one({"job_id": "pantau_staf_pindai", "started_at": mulai,
                                                   "status": "running"})
    try:
        hasil = await pindai(db)
        galat = sum(1 for v in hasil.get("aturan", {}).values() if "galat" in v)
        await db.dewi_scheduler_runs.update_one({"_id": run.inserted_id}, {"$set": {
            "status": "success" if not galat else "partial", "finished_at": now_utc(),
            "aturan": len(hasil.get("aturan", {})), "galat": galat}})
        return hasil
    except Exception as e:  # noqa: BLE001
        log.exception("[pantau-staf] pindai gagal")
        await db.dewi_scheduler_runs.update_one({"_id": run.inserted_id}, {"$set": {
            "status": "failed", "finished_at": now_utc(), "error": str(e)[:300]}})
        raise
