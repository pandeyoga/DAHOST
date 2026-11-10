"""/api/assets/categories — list / create / update / delete asset categories."""
from fastapi import Request, HTTPException

from database import get_db
from auth import require_auth
from ._helpers import router, _now, _ser, _uid, _ensure_default_categories
from core.reference_dedup import assert_unique_ref


@router.get("/categories")
async def list_categories(request: Request):
    await require_auth(request)
    db = get_db()
    await _ensure_default_categories(db)
    # 2026-11-06 (pola P8): kategori kembar yang sudah digabung (nonaktif) tidak ditawarkan lagi
    cats = await db.dewi_asset_categories.find({"active": {"$ne": False}}, {"_id": 0}).sort("name", 1).to_list(100)
    return [_ser(c) for c in cats]


@router.get("/categories/{cat_id}")
async def get_category(cat_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    cat = await db.dewi_asset_categories.find_one({"id": cat_id}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "Kategori tidak ditemukan.")
    return _ser(cat)


@router.post("/categories")
async def create_category(request: Request):
    await require_auth(request)
    db = get_db()
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nama kategori wajib diisi.")
    code = (body.get("code") or name[:2].upper()).strip().upper()
    # 2026-11-06 (pola P8): dulu tanpa cek apa pun — nama/kode yang sama bisa dibuat berkali-kali
    await assert_unique_ref(db, "dewi_asset_categories", name=name, label="Kategori aset")
    if await db.dewi_asset_categories.find_one({"code": code, "active": {"$ne": False}}, {"_id": 0, "id": 1}):
        raise HTTPException(409, f"Kode kategori aset '{code}' sudah dipakai. Gunakan kode lain.")
    doc = {
        "id": _uid(),
        "name": name,
        "code": code,
        "active": True,
        "useful_life_years": int(body.get("useful_life_years") or 5),
        "depr_method": body.get("depr_method", "straight_line"),
        "coa_asset_account": (body.get("coa_asset_account") or "").strip(),
        "coa_depreciation_account": (body.get("coa_depreciation_account") or "").strip(),
        "created_at": _now(),
    }
    await db.dewi_asset_categories.insert_one(doc)
    return _ser(doc)


@router.put("/categories/{cat_id}")
async def update_category(cat_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    body = await request.json()
    update = {}
    if "name" in body:
        await assert_unique_ref(db, "dewi_asset_categories", name=body["name"], label="Kategori aset",
                                exclude_id=cat_id)  # 2026-11-06 (pola P8)
        update["name"] = body["name"]
    if "code" in body:
        update["code"] = body["code"].upper()
    if "useful_life_years" in body:
        update["useful_life_years"] = int(body["useful_life_years"])
    if "depr_method" in body:
        update["depr_method"] = body["depr_method"]
    if "coa_asset_account" in body:
        update["coa_asset_account"] = (body["coa_asset_account"] or "").strip()
    if "coa_depreciation_account" in body:
        update["coa_depreciation_account"] = (body["coa_depreciation_account"] or "").strip()
    if update:
        await db.dewi_asset_categories.update_one({"id": cat_id}, {"$set": update})
    return {"ok": True}


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, request: Request):
    from routes.shared import require_perm
    await require_perm(request, 'assets.manage', legacy_roles=('accounting', 'manager_keuangan', 'staff_keuangan',
                       'admin_gudang', 'owner', 'admin', 'superadmin'),
                       message='Akses ditolak: Anda tidak berhak menghapus kategori aset.')  # T-01 2.3
    db = get_db()
    # 10 Nov 2026 (permintaan owner "master data bisa dihapus"): kalimat & kode penolakan diseragamkan lewat
    # core.hapus_master (dulu 400 "ada {n} aset"). Perilaku tetap: hapus permanen bila belum dipakai aset.
    from core.hapus_master import hitung_pemakaian, tolak_bila_dipakai
    cat = await db.dewi_asset_categories.find_one({"id": cat_id}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "Kategori tidak ditemukan.")
    pakai = await hitung_pemakaian(db, [("aset", "dewi_assets", {"category_id": cat_id})])
    tolak_bila_dipakai("Kategori aset", cat.get("name") or cat.get("code") or "", pakai,
                       "Pindahkan aset itu ke kategori lain dulu.")
    await db.dewi_asset_categories.delete_one({"id": cat_id})
    return {"ok": True}
