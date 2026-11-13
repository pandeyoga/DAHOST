"""Pemantauan Staf ERP — Portal Manajemen (keputusan owner 10 Nov 2026; alur kerja harian 14 Nov 2026).

Layar "Pemantauan staf" & "Aturan kewajiban": HANYA owner, admin, superadmin (K3 — skor tidak untuk atasan/staf).
Portal Saya: `GET /api/pantau-staf/saya` = daftar kewajiban milik sendiri, tanpa skor (K4) — swalayan.

Mesin: `core/pantau_staf/*` (meter aktivitas, katalog titik aksi, aturan, pemindai, ringkasan, pengingat,
alur kerja harian `alur_kerja`).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request

from auth import log_activity, require_auth
from core.pantau_staf import alur_kerja as _alur
from core.pantau_staf import aturan as _aturan
from core.pantau_staf import pemindai, pengingat, ringkasan
from core.pantau_staf.katalog import ALUR_LABEL, KATALOG
from core.pantau_staf.waktu import label_tenggat
from database import get_db
from utils.query_guards import q_date
from utils.waktu import mongo_utc, now_utc

router = APIRouter(prefix="/api/pantau-staf", tags=["pantau-staf"])

PERAN_PEMANTAU = ("superadmin", "admin", "owner")


async def _pemantau(request: Request) -> dict:
    user = await require_auth(request)
    if (user.get("role") or "").lower() not in PERAN_PEMANTAU:
        raise HTTPException(403, "Pemantauan staf hanya untuk owner dan admin.")
    return user


def _periode(request: Request) -> tuple[str, str]:
    sp = request.query_params
    bawaan_dari, bawaan_sampai = ringkasan.periode_bawaan()
    dari = q_date(sp.get("dari"), name="dari")
    sampai = q_date(sp.get("sampai"), name="sampai")
    dari_s = dari.isoformat() if dari else bawaan_dari
    sampai_s = sampai.isoformat() if sampai else bawaan_sampai
    if dari_s > sampai_s:
        raise HTTPException(400, "Tanggal awal periode harus sebelum tanggal akhir.")
    return dari_s, sampai_s


def _out(obj):
    return mongo_utc(obj)


@router.get("/kartu")
async def get_kartu(request: Request):
    await _pemantau(request)
    dari, sampai = _periode(request)
    return _out(await ringkasan.kartu(get_db(), dari, sampai))


@router.get("/staf")
async def get_staf(request: Request):
    await _pemantau(request)
    dari, sampai = _periode(request)
    return _out(await ringkasan.per_staf(get_db(), dari, sampai))


@router.get("/staf/{uid}")
async def get_rincian_staf(uid: str, request: Request):
    await _pemantau(request)
    dari, sampai = _periode(request)
    out = await ringkasan.rincian_staf(get_db(), uid, dari, sampai)
    if out is None:
        raise HTTPException(404, "Akun tidak ditemukan.")
    return _out(out)


@router.get("/macet")
async def get_macet(request: Request):
    await _pemantau(request)
    sp = request.query_params
    alur = sp.get("alur") or None
    if alur and alur not in ALUR_LABEL:
        raise HTTPException(400, "Alur tidak dikenal.")
    return _out(await ringkasan.macet(get_db(), termasuk_menunggu=sp.get("menunggu") in ("1", "true"), alur=alur,
                                      uid=sp.get("user_id") or None, gabung=sp.get("rinci") not in ("1", "true")))


def _tanggal(request: Request):
    """Satu hari WIB (bawaan: hari ini). Tidak boleh di masa depan."""
    from utils.waktu import today_wib
    d = q_date(request.query_params.get("tanggal"), name="tanggal") or today_wib()
    if d > today_wib():
        raise HTTPException(400, "Tanggal tidak boleh melewati hari ini.")
    return d


@router.get("/alur")
async def get_alur(request: Request):
    """Alur kerja satu hari: per alur bisnis, langkah berurutan — dikerjakan siapa, yang menunggu, di mana macet."""
    await _pemantau(request)
    alur = request.query_params.get("alur") or None
    if alur and alur not in _alur.ALUR:
        raise HTTPException(400, "Alur tidak dikenal.")
    return _out(await _alur.alur_kerja(get_db(), _tanggal(request), alur=alur))


@router.get("/aktivitas")
async def get_aktivitas(request: Request):
    """Pekerjaan tiap staf pada satu hari (kalimat staf, dari langkah alur yang sama) + akun yang tidak aktif."""
    await _pemantau(request)
    return _out(await _alur.aktivitas_staf(get_db(), _tanggal(request)))


@router.get("/kejadian/{kid}")
async def get_kejadian(kid: str, request: Request):
    await _pemantau(request)
    out = await ringkasan.rantai(get_db(), kid)
    if out is None:
        raise HTTPException(404, "Kewajiban tidak ditemukan.")
    return _out(out)


@router.post("/kejadian/{kid}/ingatkan")
async def post_ingatkan(kid: str, request: Request):
    user = await _pemantau(request)
    db = get_db()
    k = await db[pemindai.KEJADIAN].find_one({"id": kid}, {"_id": 0})
    if not k:
        raise HTTPException(404, "Kewajiban tidak ditemukan.")
    if k.get("status") not in pemindai.TERBUKA:
        raise HTTPException(409, "Kewajiban ini sudah tidak menunggu.")
    if not k.get("pemegang_ids"):
        raise HTTPException(409, "Kewajiban ini belum punya penanggung jawab. Isi di menu Aturan kewajiban.")
    n = await pengingat.ingatkan_satu(db, k, oleh=user)
    return {"ok": True, "penerima": n, "pesan": "Pengingat terkirim ke penanggung jawab."}


@router.post("/kejadian/{kid}/maafkan")
async def post_maafkan(kid: str, request: Request):
    user = await _pemantau(request)
    db = get_db()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — badan kosong/tidak sah = tanpa alasan
        body = {}
    alasan = str((body or {}).get("alasan") or "").strip() if isinstance(body, dict) else ""
    if len(alasan) < 3:
        raise HTTPException(400, "Tulis alasan memaafkan (minimal 3 huruf).")
    k = await db[pemindai.KEJADIAN].find_one({"id": kid}, {"_id": 0})
    if not k:
        raise HTTPException(404, "Kewajiban tidak ditemukan.")
    if k.get("status") not in pemindai.TERBUKA + ("terlewat",):
        raise HTTPException(409, "Hanya kewajiban yang masih menunggu, terlambat, atau terlewat yang bisa dimaafkan.")
    kini = now_utc()
    await db[pemindai.KEJADIAN].update_one({"id": kid}, {"$set": {
        "status": "dimaafkan", "diperbarui_at": kini,
        "dimaafkan": {"oleh_id": user.get("id"), "oleh_nama": user.get("name"), "alasan": alasan[:300], "at": kini}}})
    await log_activity(user.get("id"), user.get("name"), "maafkan", "pantau_staf",
                       f"{k.get('nama')} {k.get('nomor') or ''}: {alasan[:120]}")
    return {"ok": True}


async def _pilihan(db) -> dict:
    akun = [{"id": u["id"], "nama": u.get("name") or u.get("email"), "peran": u.get("role")}
            for u in await pemindai.akun_internal(db)]
    akun.sort(key=lambda a: (a["nama"] or "").lower())
    peran = sorted({a["peran"] for a in akun if a.get("peran")})
    lokasi = [{"id": r["id"], "nama": r.get("name") or r.get("code") or r["id"]}
              for r in await db.rahaza_locations.find({}, {"_id": 0, "id": 1, "name": 1, "code": 1}).to_list(500)
              if r.get("id")]
    toko = [{"id": r["id"], "nama": r.get("account_name") or r["id"]}
            for r in await db.marketing_platform_accounts.find({"status": "active"},
                                                               {"_id": 0, "id": 1, "account_name": 1}).to_list(500)
            if r.get("id")]
    return {"akun": akun, "peran": peran, "lokasi": lokasi, "toko": toko}


def _bentuk_aturan(a: dict, users: dict) -> dict:
    t = KATALOG[a["titik"]]
    p = a.get("pemegang") or {}
    return {
        **a, "nama": t.nama, "alur": t.alur, "alur_label": ALUR_LABEL[t.alur], "urutan": t.urutan,
        "jenis": t.jenis, "pemicu": t.pemicu, "bukti": t.bukti, "saringan_boleh": list(t.saringan),
        "pemegang_bawaan": t.pemegang, "tenggat_label": label_tenggat(a.get("tenggat") or t.tenggat),
        "tenggat_bawaan": t.tenggat, "tanpa_waktu": t.tanpa_waktu, "link_module": t.link_module,
        "pemegang_nama": [users[i].get("name") or i for i in (p.get("akun_ids") or []) if i in users],
        "cadangan_nama": [users[i].get("name") or i for i in (a.get("cadangan_ids") or []) if i in users],
        "dikecualikan_nama": [users[i].get("name") or i for i in (a.get("dikecualikan_ids") or []) if i in users],
    }


@router.get("/aturan")
async def get_aturan(request: Request):
    await _pemantau(request)
    db = get_db()
    users = {u["id"]: u for u in await pemindai.akun_internal(db)}
    items = [_bentuk_aturan(a, users) for a in await _aturan.semua(db)]
    terbuka: dict = {}
    for k in await db[pemindai.KEJADIAN].find({"status": {"$in": list(pemindai.TERBUKA)}},
                                             {"_id": 0, "aturan_id": 1, "status": 1}).to_list(50000):
        x = terbuka.setdefault(k["aturan_id"], {"menunggu": 0, "terlambat": 0})
        x[k["status"]] += 1
    for it in items:
        it.update(terbuka.get(it["id"], {"menunggu": 0, "terlambat": 0}))
    items.sort(key=lambda r: (list(ALUR_LABEL).index(r["alur"]), r["urutan"]))
    return _out({"items": items, "pilihan": await _pilihan(db), "alur": ALUR_LABEL})


@router.put("/aturan/{aid}")
async def put_aturan(aid: str, request: Request):
    user = await _pemantau(request)
    db = get_db()
    if aid not in KATALOG:
        raise HTTPException(404, "Aturan tidak ditemukan.")
    body = await request.json()
    users = {u["id"]: u for u in await pemindai.akun_internal(db)}
    peran_ada = {u.get("role") for u in users.values() if u.get("role")}
    peran_ada |= {r.get("name") or r.get("id") for r in await db.roles.find({}, {"_id": 0, "name": 1, "id": 1}).to_list(500)}
    try:
        doc = await _aturan.ubah(db, aid, body, oleh=user, users=users, peran_ada=peran_ada)
    except _aturan.AturanTidakSah as e:
        raise HTTPException(400, str(e))
    await log_activity(user.get("id"), user.get("name"), "ubah_aturan", "pantau_staf", KATALOG[aid].nama)
    return _out(_bentuk_aturan(doc, users))


@router.get("/akun/{uid}/kewajiban")
async def get_kewajiban_akun(uid: str, request: Request):
    """Tampilan "Per akun": semua aturan yang menunjuk akun ini (to-do list per akun)."""
    await _pemantau(request)
    db = get_db()
    users = {u["id"]: u for u in await pemindai.akun_internal(db)}
    u = users.get(uid)
    if not u:
        raise HTTPException(404, "Akun tidak ditemukan atau nonaktif.")
    terbuka: dict = {}
    for k in await db[pemindai.KEJADIAN].find({"pemegang_ids": uid, "status": {"$in": list(pemindai.TERBUKA)}},
                                             {"_id": 0, "aturan_id": 1, "status": 1}).to_list(5000):
        x = terbuka.setdefault(k["aturan_id"], {"menunggu": 0, "terlambat": 0})
        x[k["status"]] += 1
    # aturan "dari data" hanya relevan bila akun ini pernah benar-benar menjadi pemegangnya (45 hari terakhir)
    pernah = {k["aturan_id"] for k in await db[pemindai.KEJADIAN].find(
        {"pemegang_ids": uid, "dibuat_at": {"$gte": now_utc() - timedelta(days=45)}},
        {"_id": 0, "aturan_id": 1}).to_list(20000)}
    items = []
    for a in await _aturan.semua(db):
        p = a.get("pemegang") or {}
        dikecualikan = uid in (a.get("dikecualikan_ids") or [])
        if dikecualikan:
            relevan = (p.get("jenis") == "data" or (p.get("jenis") == "peran" and u.get("role") in (p.get("peran") or []))
                       or uid in (p.get("akun_ids") or []))
            alasan = "dikecualikan untuk akun ini"
        else:
            alasan = _aturan.berlaku_untuk(a, u)
            relevan = alasan is not None and (p.get("jenis") != "data" or a["id"] in pernah or a["id"] == "aktif_harian")
        if not relevan:
            continue
        row = _bentuk_aturan(a, users)
        row.update({"alasan": alasan, "dikecualikan": dikecualikan,
                    **terbuka.get(a["id"], {"menunggu": 0, "terlambat": 0})})
        items.append(row)
    items.sort(key=lambda r: (list(ALUR_LABEL).index(r["alur"]), r["urutan"]))
    return _out({"user": {"id": uid, "nama": u.get("name"), "peran": u.get("role")}, "items": items})


@router.put("/akun/{uid}/pengecualian")
async def put_pengecualian(uid: str, request: Request):
    """Kecualikan / ikutkan lagi satu akun dari satu aturan (aturan peran atau dari data)."""
    user = await _pemantau(request)
    db = get_db()
    body = await request.json()
    aid, ya = body.get("aturan_id"), body.get("dikecualikan")
    if aid not in KATALOG or not isinstance(ya, bool):
        raise HTTPException(400, "Pilih aturan dan isi dikecualikan ya/tidak.")
    a = await _aturan.satu(db, aid)
    ids = [i for i in (a.get("dikecualikan_ids") or []) if i != uid] + ([uid] if ya else [])
    users = {u["id"]: u for u in await pemindai.akun_internal(db)}
    peran_ada = {u.get("role") for u in users.values() if u.get("role")}
    try:
        await _aturan.ubah(db, aid, {"dikecualikan_ids": ids}, oleh=user, users=users, peran_ada=peran_ada)
    except _aturan.AturanTidakSah as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/pindai")
async def post_pindai(request: Request):
    """Jalankan pemindaian sekarang (tanpa menunggu jadwal 15 menit)."""
    await _pemantau(request)
    hasil = await pemindai.pindai(get_db())
    if hasil.get("status") == "sedang_berjalan":
        raise HTTPException(409, "Pemindaian sedang berjalan. Coba lagi sebentar lagi.")
    galat = [k for k, v in hasil.get("aturan", {}).items() if "galat" in v]
    return {"ok": True, "aturan": len(hasil.get("aturan", {})), "galat": galat}


@router.get("/katalog")
async def get_katalog(request: Request):
    await _pemantau(request)
    return {"items": ringkasan.katalog_publik(), "alur": ALUR_LABEL}


@router.get("/saya")
async def get_saya(request: Request):
    """Portal Saya › Dashboard: kewajiban milik sendiri (tanpa skor, K4)."""
    user = await require_auth(request)
    return _out(await ringkasan.saya(get_db(), user.get("id")))
