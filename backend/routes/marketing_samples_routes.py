"""
Sample Delivery Tracking Module — Backend Routes
Phase 3 Week 13: Tracking pengiriman sample produk ke reseller/KOL

14 Nov 2026 (keputusan owner, permintaan PIC toko) — Kirim Sample:
  * SATU kiriman = banyak produk (`lines`) + SATU ongkir; dokumen lama dibaca sebagai satu baris.
  * Status kirim & tindak lanjut bebas maju-mundur: PUT /{id}/status (/ship, /deliver, /update-progress tetap).
  * Stok tiap baris diperiksa saat dicatat: cukup ⇒ "Menunggu gudang" (gudang mengeluarkan lewat Keluarkan stok
    alasan Sampel yang ditautkan ke baris); kurang ⇒ draf PO "Sampel R&D" otomatis. Aturan: `core.kirim_sampel`.
  * Lingkup toko: GET/PUT/DELETE/status satu kiriman memeriksa toko kiriman itu (toko lain = 404).
"""
import re
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel, Field
# F6 (sesi #10) — endpoint DAFTAR/RINGKAS wajib menyaring sendiri: jaring
# pengaman middleware hanya menolak permintaan yang MENYEBUT toko, ia tidak
# tahu isi jawaban. Tanpa ini staf pemegang satu toko membaca angka 9 toko.
from core import marketing_account_scope as _scope
from core import kirim_sampel as ks
from database import get_db
from auth import require_auth
from core.authz import only  # T-01 2.3
from core.roles import MARKETING_ROLES  # T-01 2.3

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/marketing/samples", tags=["marketing-samples"])

SAMPLE_TYPES = ["live", "video"]
PLATFORMS = ["tiktok", "instagram", "shopee", "tokopedia"]
COURIERS = ["jnt", "spx", "sicepat", "jne", "anteraja", "ninja", "grab", "gojek"]
SAMPLE_STATUSES = ["pending", "shipped", "delivered", "returned", "cancelled"]
PROGRESS_STATUSES = ["open", "follow_up", "sold", "no_response", "closed"]

# ── Helpers ───────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)

def serialize(obj):
    if isinstance(obj, list):
        return [serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

def _get_user(request: Request) -> dict:
    return getattr(request.state, "user", {}) or {}

# ── Seed ─────────────────────────────────────────────────────────────────────
async def seed_samples_if_empty():
    db = get_db()
    if await db.marketing_samples.count_documents({}) > 0:
        return

    import random
    
    products = [
        "Gamis Daluna Basic", "Khimar Syari Premium", "Tunik Busui Friendly",
        "Set Gamis + Khimar", "Outer Cardigan", "Rok Plisket Panjang",
        "Dress Casual", "Hijab Segiempat"
    ]
    
    # F14 — sample demo dulu memakai `username` teks bebas dan TIDAK punya
    # `account_id`/`creator_id` (35/35 kosong) ⇒ biaya sample tidak bisa dibebankan
    # ke toko mana pun, dan performa kreator tidak bisa dihitung.
    from core import marketing_account_scope as _scope
    from core.marketing_master_seed import ensure_demo_creators
    _accounts = await _scope.seed_account_pool(db)
    await ensure_demo_creators(db)
    _creators = await db.marketing_kol_creators.find(
        {}, {"_id": 0, "id": 1, "name": 1, "creator_code": 1, "platforms": 1,
             "assigned_account_ids": 1}).to_list(100)

    def _creator_handle(c):
        p = (c or {}).get("platforms") or {}
        return p.get("tiktok") or p.get("instagram") or (c or {}).get("creator_code") \
            or (c or {}).get("name") or ""

    usernames = [_creator_handle(c) for c in _creators] or [
        "@ayufashion", "@budihijab", "@citramuslimah", "@dinarmodest",
        "@evisyari", "@farahbusana", "@ginaootd", "@hanastyle"
    ]
    
    sizes = ["S", "M", "L", "XL", "XXL"]
    colors = ["Hitam", "Navy", "Maroon", "Olive", "Abu-abu", "Coklat"]
    couriers_list = ["jnt", "spx", "sicepat"]
    
    entries = []
    base = _now()
    
    for i in range(35):
        day_offset = random.randint(-45, 0)
        sample_date = base + timedelta(days=day_offset)
        
        quantity = random.randint(1, 3)
        hpp = random.randint(50000, 150000)
        ongkir = random.randint(15000, 35000)
        sample_type = random.choice(["live", "video", "video"])
        
        progress = random.choice(["open", "follow_up", "sold", "no_response", "closed"])
        shipment_status = "delivered" if progress in ["sold", "closed"] else "shipped" if progress == "follow_up" else "pending"
        
        _acc = random.choice(_accounts)
        _cand = [c for c in _creators
                 if _acc["id"] in (c.get("assigned_account_ids") or [])] or _creators
        _cr = random.choice(_cand) if _cand else None
        entries.append({
            "id": str(uuid.uuid4()),
            "date": sample_date.date().isoformat(),
            "account_id": _acc["id"],
            "account_name": _acc.get("account_name", ""),
            "creator_id": (_cr or {}).get("id"),
            "username": (_creator_handle(_cr) if _cr else random.choice(usernames)),
            "sample_type": sample_type,
            "sample_type_label": "Live Streaming" if sample_type == "live" else "Video Review",
            "platform": _acc.get("platform", "tiktok"),
            "product": random.choice(products),
            "size": random.choice(sizes),
            "color": random.choice(colors),
            "quantity": quantity,
            "hpp": hpp,
            "total_hpp": hpp * quantity,
            "ongkir": ongkir,
            "courier": random.choice(couriers_list),
            "video_link": f"https://vt.tiktok.com/ZS{random.randint(1000000, 9999999)}/" if sample_type == "video" else "",
            "screenshot_url": "",
            "shipment_status": shipment_status,
            "progress": progress,
            "sales_update": "Terjual 5 pcs" if progress == "sold" else "Sedang follow up" if progress == "follow_up" else "Belum ada respon" if progress == "no_response" else "",
            "notes": "",
            "_seed_origin": True,
            "created_by": "system",
            "created_at": _now(),
            "updated_at": _now(),
        })
    
    if entries:
        await db.marketing_samples.insert_many(entries)
    logger.info(f"[marketing_samples] seeded {len(entries)} entries")

# ── Models ───────────────────────────────────────────────────────────────────
# 14 Nov 2026 (keputusan owner, permintaan PIC toko) — SATU kiriman = banyak produk + SATU ongkir.
# Aturan baris, stok gudang, dan PO sampel ada di `core.kirim_sampel` (satu tempat). Dokumen lama (satu produk di
# tingkat atas) dibaca sebagai satu baris; field tunggal lama (`catalog_item_id`, `product`, `quantity`, …) masih
# diterima dari klien lama dan diubah menjadi satu baris.
class BarisIn(BaseModel):
    id: Optional[str] = None
    catalog_item_id: Optional[str] = None
    size: Optional[str] = ""
    color: Optional[str] = ""
    quantity: int = Field(default=1, ge=1)
    # hanya jalur lama tanpa katalog (impor / klien lama)
    product: Optional[str] = None
    sku: Optional[str] = None
    hpp: Optional[float] = Field(default=None, ge=0)


class SampleIn(BaseModel):
    # ── F14/F15 ───────────────────────────────────────────────────────────────
    # `account_id` dulu TIDAK ADA sama sekali (35/35 dokumen tanpa lingkup toko)
    # ⇒ biaya sample tidak bisa dibebankan ke toko mana pun.
    # `creator_id` menggantikan `username` sebagai identitas kreator: username
    # teks bebas membuat satu kreator pecah jadi beberapa baris laporan begitu
    # ejaannya beda satu karakter. `username` tetap disimpan sebagai TURUNAN.
    account_id: str
    creator_id: Optional[str] = None
    date: str
    username: Optional[str] = ""
    sample_type: str
    platform: Optional[str] = ""
    ongkir: float = Field(default=0, ge=0)
    courier: str
    tracking_number: Optional[str] = ""
    video_link: Optional[str] = ""
    notes: Optional[str] = ""
    lines: Optional[List[BarisIn]] = None
    # bentuk lama satu produk
    catalog_item_id: Optional[str] = None
    product: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    quantity: Optional[int] = Field(default=None, ge=0)
    hpp: Optional[float] = Field(default=None, ge=0)


class SampleUpdate(BaseModel):
    account_id: Optional[str] = None
    creator_id: Optional[str] = None
    date: Optional[str] = None
    username: Optional[str] = None
    sample_type: Optional[str] = None
    platform: Optional[str] = None
    ongkir: Optional[float] = Field(default=None, ge=0)
    courier: Optional[str] = None
    tracking_number: Optional[str] = None
    video_link: Optional[str] = None
    screenshot_url: Optional[str] = None
    shipment_status: Optional[str] = None
    progress: Optional[str] = None
    sales_update: Optional[str] = None
    notes: Optional[str] = None
    lines: Optional[List[BarisIn]] = None
    # bentuk lama satu produk
    catalog_item_id: Optional[str] = None
    product: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    quantity: Optional[int] = Field(default=None, ge=0)
    hpp: Optional[float] = Field(default=None, ge=0)


class StatusIn(BaseModel):
    shipment_status: Optional[str] = None
    progress: Optional[str] = None
    sales_update: Optional[str] = None


_LEGACY_LINE = ("catalog_item_id", "product", "size", "color", "quantity", "hpp")


def _type_label(t: str) -> str:
    return "Live Streaming" if t == "live" else "Video Review"


def _legacy_line(body, base: Optional[dict] = None) -> Optional[dict]:
    """Field tunggal lama → satu baris formulir (None bila klien tidak mengirim satu pun)."""
    given = {k: getattr(body, k) for k in _LEGACY_LINE if getattr(body, k, None) is not None}
    if not given:
        return None
    return {**(base or {}), **given}


def _out(doc: dict) -> dict:
    return serialize(ks.normalise(doc))


# ── Lingkup toko (keputusan 6) ────────────────────────────────────────────────
async def _ambil(db, user: dict, sample_id: str) -> dict:
    """Kiriman + periksa toko: kiriman toko yang bukan tanggung jawab pemakai = 404 (tidak membocorkan isinya)."""
    doc = await db.marketing_samples.find_one({"id": sample_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Kiriman sampel tidak ditemukan")
    try:
        await _scope.assert_account_visible(db, user, doc.get("account_id"))
    except HTTPException as e:
        if e.status_code == 403:
            raise HTTPException(404, "Kiriman sampel tidak ditemukan")
        raise
    if not doc.get("account_id") and await _scope.visible_account_ids(db, user) is not None:
        raise HTTPException(404, "Kiriman sampel tidak ditemukan")   # dokumen tanpa toko: hanya peran semua toko
    return doc


async def _kreator(db, creator_id: Optional[str], account_id: str, username: str) -> tuple:
    if not creator_id:
        return None, username or ""
    creator = await _scope.assert_creator_assigned(db, creator_id, account_id)
    _p = creator.get("platforms") or {}
    return creator, (_p.get("tiktok") or _p.get("instagram") or creator.get("creator_code")
                     or creator.get("name") or "")


def _riwayat(field: str, before, after, user: dict) -> dict:
    return {"field": field, "dari": before, "ke": after, "at": _now(),
            "by": user.get("name") or user.get("email") or ""}


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_summary(request: Request,
                      account_id: str = Query(default="")):
    user = await require_auth(request)
    # 2026-11-02 — seeder demo tidak lagi dipanggil saat GET (data fiktif terus muncul di data go-live).
    db = get_db()
    _sq = await _scope.scope_filter(
        db, user, {"account_id": account_id} if account_id else {})

    total = await db.marketing_samples.count_documents(dict(_sq))
    pending = await db.marketing_samples.count_documents({**_sq, "shipment_status": "pending"})
    shipped = await db.marketing_samples.count_documents({**_sq, "shipment_status": "shipped"})
    delivered = await db.marketing_samples.count_documents({**_sq, "shipment_status": "delivered"})

    # Progress summary
    open_count = await db.marketing_samples.count_documents({**_sq, "progress": "open"})
    sold_count = await db.marketing_samples.count_documents({**_sq, "progress": "sold"})
    follow_up = await db.marketing_samples.count_documents({**_sq, "progress": "follow_up"})
    no_response = await db.marketing_samples.count_documents({**_sq, "progress": "no_response"})

    # Total investment — `total_hpp` tingkat atas = Σ baris (dokumen lama: HPP produk tunggalnya)
    pipeline_cost = ([{"$match": dict(_sq)}] if _sq else []) + [
        {"$group": {"_id": None, "total_hpp": {"$sum": "$total_hpp"},
                    "total_ongkir": {"$sum": "$ongkir"}}}]
    cost_result = await db.marketing_samples.aggregate(pipeline_cost).to_list(1)
    total_hpp = cost_result[0]["total_hpp"] if cost_result else 0
    total_ongkir = cost_result[0]["total_ongkir"] if cost_result else 0
    total_investment = total_hpp + total_ongkir

    return {
        "success": True,
        "data": {
            "total": total,
            "pending": pending,
            "shipped": shipped,
            "delivered": delivered,
            "open": open_count,
            "sold": sold_count,
            "follow_up": follow_up,
            "no_response": no_response,
            "total_investment": total_investment,
            "total_hpp": total_hpp,
            "total_ongkir": total_ongkir,
        }
    }

@router.get("")
async def list_samples(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, le=100),
    account_id: str = Query(default="", description="F14 — filter per toko"),
    creator_id: str = Query(default=""),
    shipment_status: str = Query(default=""),
    progress: str = Query(default=""),
    platform: str = Query(default=""),
    sample_type: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    search: str = Query(default=""),
):
    user = await require_auth(request)
    # 2026-11-02 — seeder demo tidak lagi dipanggil saat GET (data fiktif terus muncul di data go-live).
    db = get_db()

    q = await _scope.scope_filter(
        db, user, {"account_id": account_id} if account_id else {})
    if creator_id:
        q["creator_id"] = creator_id
    if shipment_status:
        q["shipment_status"] = shipment_status
    if progress:
        q["progress"] = progress
    if platform:
        q["platform"] = platform
    if sample_type:
        q["sample_type"] = sample_type
    if date_from:
        q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        q.setdefault("date", {})["$lte"] = date_to
    if search:
        rx = {"$regex": re.escape(search), "$options": "i"}
        q["$or"] = [{"username": rx}, {"product": rx}, {"sales_update": rx},
                    {"lines.product": rx}, {"lines.sku": rx}]

    total = await db.marketing_samples.count_documents(q)
    skip = (page - 1) * page_size
    items = await db.marketing_samples.find(q, {"_id": 0})\
                    .sort("date", -1).skip(skip).limit(page_size).to_list(page_size)

    return {
        "success": True,
        "data": [_out(x) for x in items],
        "pagination": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    }

@router.get("/{sample_id}")
async def get_sample(sample_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    return {"success": True, "data": _out(await _ambil(db, user, sample_id))}

@router.post("")
async def create_sample(body: SampleIn, request: Request):
    user = await require_auth(request)
    db = get_db()

    # F14 — toko wajib & sah (dan dipegang pemakai ini); F15 — kreator wajib SUDAH di-assign ke toko itu.
    account = await _scope.require_account(db, body.account_id)
    await _scope.assert_account_visible(db, user, account["id"])
    creator, username = await _kreator(db, body.creator_id, account["id"], body.username or "")

    masukan = [b.model_dump() for b in body.lines] if body.lines else [x for x in [_legacy_line(body)] if x]
    if not masukan:
        raise HTTPException(400, "Pilih minimal satu produk.")
    lines = [await ks.susun_baris(db, m, account["id"]) for m in masukan]
    ks.tolak_dobel(lines)

    sample = {
        "id": str(uuid.uuid4()),
        "date": body.date,
        "creator_id": (creator or {}).get("id"),
        "creator_name": (creator or {}).get("name", ""),
        "username": username,
        "sample_type": body.sample_type,
        "sample_type_label": _type_label(body.sample_type),
        "platform": account.get("platform") or body.platform,
        "ongkir": body.ongkir,
        "courier": body.courier,
        "tracking_number": body.tracking_number or "",
        "video_link": body.video_link or "",
        "screenshot_url": "",
        "shipment_status": "pending",
        "progress": "open",
        "sales_update": "",
        "notes": body.notes or "",
        "created_by": user.get("email", "unknown"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    _scope.stamp_account(sample, account)
    sample["sample_code"] = ks.kode_kiriman(sample)
    # Keputusan 3 + 4: stok tiap baris diperiksa SEKARANG — cukup ⇒ "Menunggu gudang"; kurang ⇒ draf PO sampel.
    sample["lines"] = [await ks.rencanakan_baris(db, sample, ln, user) for ln in lines]
    sample.update(ks.turunan(sample["lines"]))
    await db.marketing_samples.insert_one(sample)
    return {"success": True, "data": _out(sample)}

@router.put("/{sample_id}")
async def update_sample(sample_id: str, body: SampleUpdate, request: Request):
    user = await require_auth(request)
    db = get_db()
    existing = await _ambil(db, user, sample_id)

    upd = {k: v for k, v in body.model_dump(exclude={"lines", *_LEGACY_LINE}).items() if v is not None}
    for f, allowed in (("shipment_status", ks.STATUS_KIRIM), ("progress", ks.TINDAK_LANJUT)):
        if f in upd and upd[f] not in allowed and upd[f] != existing.get(f):
            raise HTTPException(400, f"Nilai {f} tidak dikenal: {upd[f]}")
    account_id = upd.get("account_id") or existing.get("account_id")
    if upd.get("account_id") and upd["account_id"] != existing.get("account_id"):
        account = await _scope.require_account(db, upd["account_id"])
        await _scope.assert_account_visible(db, user, account["id"])
        _scope.stamp_account(upd, account)
    # Keputusan 6: kreator diperiksa ulang terhadap toko (yang baru) setiap kali kreator/toko dikirim.
    if "creator_id" in upd or "account_id" in upd:
        creator, username = await _kreator(db, upd.get("creator_id") or existing.get("creator_id"), account_id,
                                           upd.get("username") or existing.get("username") or "")
        if creator:
            upd.update({"creator_id": creator["id"], "creator_name": creator.get("name", ""), "username": username})

    if body.lines is not None:
        masukan = [b.model_dump() for b in body.lines]
    else:
        lama = ks.baris_tersimpan(existing)
        one = _legacy_line(body, base=lama[0] if len(lama) == 1 else None)
        if one is not None and len(lama) > 1:
            raise HTTPException(400, "Kiriman ini berisi banyak produk — ubah lewat daftar produknya.")
        masukan = [one] if one is not None else [dict(x) for x in lama]
    lines, rencana = await ks.gabung_baris(db, existing, masukan, account_id)
    doc_baru = {**existing, **upd}
    doc_baru["sample_code"] = ks.kode_kiriman(existing)
    upd["lines"] = [await ks.rencanakan_baris(db, doc_baru, ln, user) if ln["id"] in rencana
                    else ks.bersihkan_baris(ln) for ln in lines]
    upd.update(ks.turunan(upd["lines"]))
    upd["sample_code"] = doc_baru["sample_code"]
    if "sample_type" in upd:
        upd["sample_type_label"] = _type_label(upd["sample_type"])
    upd["updated_at"] = _now()

    await db.marketing_samples.update_one({"id": sample_id}, {"$set": upd})
    return {"success": True, "data": _out({**existing, **upd})}

@router.delete("/{sample_id}", dependencies=only(*MARKETING_ROLES, perm="toko.manage"))  # T-01 2.3
async def delete_sample(sample_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    existing = await _ambil(db, user, sample_id)
    for ln in ks.baris_tersimpan(existing):
        alasan = await ks.alasan_terkunci(db, ln)
        if alasan:
            raise HTTPException(400, f"Kiriman tidak bisa dihapus: {alasan}")
    res = await db.marketing_samples.delete_one({"id": sample_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Kiriman sampel tidak ditemukan")
    return {"success": True, "message": "Deleted"}


async def _atur_status(db, user: dict, existing: dict, *, shipment_status=None, progress=None,
                       sales_update=None) -> dict:
    """Keputusan 2: status kirim & tindak lanjut bebas maju-MUNDUR; tiap perubahan dicatat di `riwayat_status`."""
    upd, riwayat = {}, []
    if shipment_status is not None:
        if shipment_status not in ks.STATUS_KIRIM:
            raise HTTPException(400, "Status kirim harus Belum dikirim, Dikirim, atau Sampai.")
        if shipment_status != existing.get("shipment_status"):
            upd["shipment_status"] = shipment_status
            riwayat.append(_riwayat("shipment_status", existing.get("shipment_status"), shipment_status, user))
    if progress is not None:
        if progress not in ks.TINDAK_LANJUT:
            raise HTTPException(400, f"Tindak lanjut tidak dikenal: {progress}")
        if progress != existing.get("progress"):
            upd["progress"] = progress
            riwayat.append(_riwayat("progress", existing.get("progress"), progress, user))
    if sales_update is not None:
        upd["sales_update"] = sales_update
    upd["updated_at"] = _now()
    upd["riwayat_status"] = (list(existing.get("riwayat_status") or []) + riwayat)[-50:]
    await db.marketing_samples.update_one({"id": existing["id"]}, {"$set": upd})
    return {**existing, **upd}


@router.put("/{sample_id}/status")
async def set_status(sample_id: str, body: StatusIn, request: Request):
    """Pilihan status kirim / tindak lanjut di baris tabel — boleh kembali ke status sebelumnya."""
    user = await require_auth(request)
    db = get_db()
    existing = await _ambil(db, user, sample_id)
    if body.shipment_status is None and body.progress is None and body.sales_update is None:
        raise HTTPException(400, "Pilih status kirim atau tindak lanjut.")
    doc = await _atur_status(db, user, existing, shipment_status=body.shipment_status, progress=body.progress,
                             sales_update=body.sales_update)
    return {"success": True, "data": _out(doc)}


@router.post("/{sample_id}/ship")
async def ship_sample(sample_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    existing = await _ambil(db, user, sample_id)
    await _atur_status(db, user, existing, shipment_status="shipped")
    return {"success": True, "message": "Sample marked as shipped"}

@router.post("/{sample_id}/deliver")
async def deliver_sample(sample_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    existing = await _ambil(db, user, sample_id)
    await _atur_status(db, user, existing, shipment_status="delivered", progress="follow_up")
    return {"success": True, "message": "Sample marked as delivered"}

@router.post("/{sample_id}/update-progress")
async def update_progress(sample_id: str, request: Request):
    user = await require_auth(request)
    body = await request.json()
    progress = body.get("progress", "")
    sales_update = body.get("sales_update", "")

    if progress not in PROGRESS_STATUSES:
        raise HTTPException(400, f"Invalid progress: {progress}")

    db = get_db()
    existing = await _ambil(db, user, sample_id)
    await _atur_status(db, user, existing, progress=progress, sales_update=sales_update)
    return {"success": True, "message": "Progress updated"}
