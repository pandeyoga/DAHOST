"""routes.marketing_analitik — analitik Marketing BACA-SAJA (Asisten AI, Tahap A).

Semua endpoint di sini:

* hanya GET (tidak menulis apa pun);
* memakai SATU definisi omzet `core.ukuran_penjualan` — angka yang sama dengan
  dashboard, performa, laporan bulanan, dan target;
* berlingkup toko pemakai (`core.marketing_account_scope.visible_accounts`) dan
  pilihan CV (header ``X-CV``: DA | SMU | ALL; toko tanpa CV = DA);
* tidak pernah mengembalikan nama, nomor HP, atau alamat pembeli (pembeli hanya
  dihitung).

Dipakai alat Asisten AI (`core/asisten_ai/alat/*`) lewat panggilan dalam-proses
dengan token pemakai sendiri, jadi gerbang izin modul, lingkup toko, dan periode
berlaku persis seperti layar biasa. Peta izin: `data/module_catalog.py` (blok
"Asisten AI (data)").
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from auth import require_auth
from core import entities as _ent
from core import marketing_account_scope as _scope
from core import ukuran_penjualan as U
from database import get_db
from utils.waktu import today_wib

router = APIRouter(prefix="/api/marketing/analitik", tags=["marketing-analitik"])


async def _konteks(request: Request, toko_id: Optional[str]):
    user = await require_auth(request)
    db = get_db()
    cv = _ent.entity_from_request(request, allow_all=True)
    accounts = await U.toko_terlihat(db, user, cv=cv, toko_id=toko_id or None)
    return user, db, cv, accounts


def _periode(dari: Optional[str], sampai: Optional[str]):
    try:
        return U.periode(dari, sampai)
    except U.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None


def _bungkus(cv: str, accounts: list, user: dict, hasil: dict) -> dict:
    catatan = list(hasil.get("catatan") or [])
    if not accounts:
        catatan.insert(0, (_scope.NO_ACCOUNT_HINT if not _scope.sees_all_accounts(user)
                           else "Tidak ada toko pada pilihan CV ini."))
    hasil["catatan"] = catatan
    return {"ok": True, "cv": cv, "cv_label": _ent.entity_short(cv), **hasil}


@router.get("/penjualan")
async def analitik_penjualan(
    request: Request,
    dari: Optional[str] = Query(None, description="YYYY-MM-DD; kosong = awal bulan berjalan"),
    sampai: Optional[str] = Query(None, description="YYYY-MM-DD; kosong = hari ini (WIB)"),
    kelompok: str = Query("toko", description="toko|platform|kanal|produk|sku|hari|minggu|bulan"),
    bandingkan: str = Query("tidak", description="periode_sebelumnya|tahun_lalu|tidak"),
    toko_id: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=500),
):
    """Omzet, pesanan, unit, pembeli, AOV, retur, batal — total + per kelompok + pembanding."""
    user, db, cv, accounts = await _konteks(request, toko_id)
    d0, d1 = _periode(dari, sampai)
    try:
        hasil = await U.analitik_penjualan(db, accounts, d0, d1, kelompok=kelompok,
                                           bandingkan=bandingkan, limit=limit)
    except U.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None
    return _bungkus(cv, accounts, user, hasil)


@router.get("/produk")
async def analitik_produk(
    request: Request,
    dari: Optional[str] = Query(None),
    sampai: Optional[str] = Query(None),
    toko_id: Optional[str] = Query(None),
    urut: str = Query("teratas", description="teratas|terbawah"),
    cara: str = Query("produk", description="produk (model)|sku (barang jadi lintas toko)|katalog (item per toko)"),
    limit: int = Query(10, ge=1, le=100),
):
    """Produk teratas/terbawah menurut omzet + marjin kotor dari HPP snapshot."""
    user, db, cv, accounts = await _konteks(request, toko_id)
    d0, d1 = _periode(dari, sampai)
    try:
        hasil = await U.analitik_produk(db, accounts, d0, d1, urut=urut, cara=cara, limit=limit)
    except U.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None
    return _bungkus(cv, accounts, user, hasil)


@router.get("/target")
async def analitik_target(
    request: Request,
    dari_bulan: Optional[str] = Query(None, description="YYYY-MM; kosong = bulan berjalan"),
    sampai_bulan: Optional[str] = Query(None, description="YYYY-MM; kosong = sama dengan dari_bulan"),
    toko_id: Optional[str] = Query(None),
):
    """Target vs aktual per toko per bulan (`marketing_account_targets`), + proyeksi bulan berjalan."""
    user, db, cv, accounts = await _konteks(request, toko_id)
    from core import bulan_marketing as _bulan
    b0 = dari_bulan or sampai_bulan or _bulan.periode_dari(today_wib())   # bulan Marketing 26–25
    b1 = sampai_bulan or b0
    try:
        bulan = U.bulan_dalam(b0, b1)
        hasil = await U.analitik_target(db, accounts, bulan)
    except U.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None
    return _bungkus(cv, accounts, user, hasil)


@router.get("/iklan")
async def analitik_iklan(
    request: Request,
    dari: Optional[str] = Query(None),
    sampai: Optional[str] = Query(None),
    toko_id: Optional[str] = Query(None),
    kelompok: str = Query("toko", description="toko|kampanye|saluran|hari|minggu|bulan"),
    limit: int = Query(20, ge=1, le=400),
):
    """Belanja iklan, omzet atribusi, ROAS, klik, CTR per toko/kampanye/saluran/periode."""
    user, db, cv, accounts = await _konteks(request, toko_id)
    d0, d1 = _periode(dari, sampai)
    try:
        hasil = await U.analitik_iklan(db, accounts, d0, d1, kelompok=kelompok, limit=limit)
    except U.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None
    return _bungkus(cv, accounts, user, hasil)


@router.get("/live")
async def analitik_live(
    request: Request,
    dari: Optional[str] = Query(None),
    sampai: Optional[str] = Query(None),
    toko_id: Optional[str] = Query(None),
    kelompok: str = Query("host", description="host|toko|hari|minggu|bulan"),
    limit: int = Query(20, ge=1, le=400),
):
    """Sesi live: jumlah sesi, omzet, pesanan, jam live, penonton per host/toko/periode."""
    user, db, cv, accounts = await _konteks(request, toko_id)
    d0, d1 = _periode(dari, sampai)
    try:
        hasil = await U.analitik_live(db, accounts, d0, d1, kelompok=kelompok, limit=limit)
    except U.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None
    return _bungkus(cv, accounts, user, hasil)


@router.get("/setoran")
async def analitik_setoran(
    request: Request,
    dari: Optional[str] = Query(None, description="tanggal dana dilepas, YYYY-MM-DD"),
    sampai: Optional[str] = Query(None, description="tanggal dana dilepas, YYYY-MM-DD"),
    toko_id: Optional[str] = Query(None),
    kelompok: str = Query("toko", description="toko|platform|bulan"),
    limit: int = Query(50, ge=1, le=400),
):
    """Dana dilepas: bruto, biaya per jenis, neto diterima — menurut tanggal dana dilepas."""
    user, db, cv, accounts = await _konteks(request, toko_id)
    d0, d1 = _periode(dari, sampai)
    try:
        hasil = await U.analitik_setoran(db, accounts, d0, d1, kelompok=kelompok, limit=limit)
    except U.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None
    return _bungkus(cv, accounts, user, hasil)
