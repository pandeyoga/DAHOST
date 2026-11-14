"""wms_opname3 — API "Sesi Opname" (mesin tunggal `core.opname_engine`, keputusan owner K9).

2026-11-02 (K9): berkas ini dulu memuat mesin opname3 sendiri (stok sistem = isi bin, bin tak
di-scan = 0, `adjust_material` lintas lokasi termasuk karantina, jurnal per material ke 6-2400).
Sekarang hanya PEMBUNGKUS HTTP mesin bersama; URL lama dipertahankan (`/sessions`, `/scan`,
`/scan-undo`, `/submit`, `/approve`, `/reject`, `/cancel`, `/resolve-bin`, `/resolve-item`).
Opname aksesoris (Portal Aksesoris, `/api/acc/opname`) memanggil mesin yang sama.

Endpoint baru: `GET /locations` (lokasi + zona/rak/bin tertaut), `POST /count` (ketik jumlah,
set absolut per bin), `POST /line` (alasan "rusak" / pilihan pindah-lebih di hitung rak).
Sesi lama (`wh_opname3_sessions` tanpa `engine`, `wh_opname_sessions2`) = arsip baca-saja.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from database import get_db
from auth import require_auth, serialize_doc, log_activity
from core.authz import izin_atau_peran_lama  # 14 Nov 2026: centang owner = penentu
from core import opname_engine as eng

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wms/opname3", tags=["wms-opname3"])

SESS = eng.SESS
CNT = eng.CNT
APPROVE_ROLES = eng.APPROVE_ROLES


def jenis_sesi(sess: Optional[dict]) -> str:
    """'aksesoris' = sesi dari Portal Aksesoris › Stok Opname (layar yang sama dengan `kind="aksesoris"` →
    `source="aksesoris"`; juga `/api/acc/opname`), selain itu 'gudang'. Penentu modul centang penyetujunya."""
    return "aksesoris" if str((sess or {}).get("source") or "").lower() == "aksesoris" else "gudang"


# Modul centang penyetuju per jenis sesi + izin lama yang tetap dihormati (hanya milik modul itu sendiri).
_SETUJU_PER_JENIS = {
    "gudang": ("wh_opname", ("mod.wh_opname.approve", "wh.opname.approve")),
    "aksesoris": ("acc_opname", ("mod.acc_opname.approve",)),
}
LETAK_CENTANG = "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses"


def assert_can_approve(user: dict, what: str = "menyetujui/menolak opname", sess: Optional[dict] = None):
    """Gerbang supervisor opname (gudang & aksesoris, mesin sama).

    2026-11-09: sesi OPNAME STOK AWAL (nilainya masuk ekuitas saldo awal) hanya Keuangan/owner.
    13 Nov 2026: HANYA centang "Setujui" modul opname (dulu "Setujui" Stok, wh.opname.manage, warehouse.approve ikut).
    14 Nov 2026 (temuan owner): DIPISAH per jenis sesi — sesi aksesoris = Aksesoris › Stok Opname Aksesoris › Setujui;
    sesi gudang (kain/bahan/barang jadi) = Gudang › Opname Stok Gudang › Setujui (atau izin lama wh.opname.approve).
    Dulu centang salah satunya meloloskan kedua jenis."""
    if eng.is_opening(sess):
        from core.roles import FINANCE_ROLES
        if not izin_atau_peran_lama(user, list(FINANCE_ROLES), eng.OPENING_APPROVE_PERMS):
            raise HTTPException(403, f"Opname stok awal: peran Anda belum dicentang izin Keuangan untuk {what} (nilai "
                                     "stok awal dibukukan ke ekuitas saldo awal). Minta owner mencentang \"Ubah\" pada "
                                     f"modul \"Pengaturan Keuangan\" (Portal Keuangan) di {LETAK_CENTANG}.")
        return
    from data.module_catalog import MODULE_BY_ID, PORTAL_LABELS
    from routes.shared import can_act
    modul_id, kunci = _SETUJU_PER_JENIS[jenis_sesi(sess)]
    if can_act(user, *kunci, legacy_roles=APPROVE_ROLES):
        return
    mod = MODULE_BY_ID[modul_id]
    raise HTTPException(403, f"Peran Anda belum dicentang \"Setujui\" pada modul \"{mod['label']}\" (Portal "
                             f"{PORTAL_LABELS.get(mod['portal'], mod['portal'])}), padahal itu diperlukan untuk {what}. "
                             f"Minta owner mencentangnya di {LETAK_CENTANG}.")


# ── kompat uji/pemanggil lama (resolusi lewat SSOT core.scan_resolver) ──────────
async def _resolve_item(db, material_id: str, barcode: str):
    return await eng.resolve_item(db, material_id=material_id, code=barcode)


async def _resolve_position(db, bin_id: str = "", barcode: str = ""):
    """Bin opname = `wh_positions` (per id, atau barcode lewat SSOT resolver)."""
    from core import scan_resolver
    if bin_id:
        return await db[eng.POS].find_one({"id": bin_id}, {"_id": 0})
    if barcode:
        return await scan_resolver.position_by_barcode(db, barcode)
    return None


# ─────────────────────────────────────────────────────────────────────────────
class SessionCreateIn(BaseModel):
    location_id: str = ""
    # 2026-11-10 (owner: cakupan opname bertingkat, bisa pilih beberapa rak): 'area' = beberapa zona anak gudang
    # (stok + penempatan); zone/rack/bin = beberapa zona/rak/bin rak (penempatan saja).
    sub_scope_type: str = Field("", description="'' (seluruh lokasi) | area | zone | rack | bin")
    sub_scope_id: str = Field("", description="kompat pemanggil lama: satu id")
    sub_scope_ids: List[str] = Field(default_factory=list, description="banyak zona/rak/bin sekaligus")
    with_areas: bool = Field(False, description="True = gudang beserta zona (lokasi anak) di bawahnya")
    kinds: List[str] = Field(default_factory=list, description="bahan | aksesoris | fg")
    material_ids: List[str] = Field(default_factory=list)
    material_codes: List[str] = Field(default_factory=list, description="cycle count: kode/SKU barang")
    notes: str = ""
    source: str = "gudang"
    # 2026-11-09: True = opname STOK AWAL (lawan jurnal ekuitas saldo awal, disetujui Keuangan/owner)
    opening: bool = False


class ScanIn(BaseModel):
    session_id: str
    bin_id: str = ""
    bin_barcode: str = ""
    item_material_id: str = ""
    item_barcode: str = ""
    # qty=0 berarti 1 (perilaku lama); negatif ditolak 422
    qty: float = Field(1, ge=0)
    input_uom: str = ""


class CountIn(BaseModel):
    session_id: str
    material_id: str = ""
    item_barcode: str = ""
    bin_id: str = ""
    bin_barcode: str = ""
    qty: float = Field(..., ge=0)
    input_uom: str = ""


class LineIn(BaseModel):
    session_id: str
    key: str
    reason: Optional[str] = None
    resolution: Optional[str] = None


class SessionRefIn(BaseModel):
    session_id: str
    notes: str = ""
    confirm_zero: bool = False


async def _ctx(db, session_id, bin_id, bin_barcode, material_id, item_barcode):
    sess = await eng.get_session(db, session_id, for_write=True)
    eng._require_status(sess, "counting")
    b_id, b_label = await eng.resolve_count_bin(db, sess, bin_id=bin_id, code=bin_barcode)
    mat = await eng.resolve_item(db, material_id=material_id, code=item_barcode)
    if not mat:
        raise HTTPException(404, f"Barang tidak dikenal (kode/SKU: '{item_barcode or material_id}')")
    return sess, b_id, b_label, mat


# ─────────────────────────────────────────────────────────────────────────────
@router.get("/locations")
async def list_locations(request: Request):
    await require_auth(request)
    return serialize_doc(await eng.list_locations(get_db()))


@router.post("/sessions")
async def create_session(data: SessionCreateIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    doc = await eng.create_session(db, user, location_id=data.location_id, sub_type=data.sub_scope_type,
                                   sub_id=data.sub_scope_id, sub_ids=data.sub_scope_ids, kinds=data.kinds,
                                   material_ids=data.material_ids, material_codes=data.material_codes,
                                   notes=data.notes, source=data.source, opening=data.opening,
                                   with_areas=data.with_areas)
    await log_activity(user.get("id", ""), user.get("name", ""), "opname_create", SESS,
                       f"Opname {doc['session_no']} {doc['scope_label']} ({len(doc['lines'])} baris, {doc['level']})")
    return {"id": doc["id"], "session_no": doc["session_no"], "level": doc["level"], "mode": doc["mode"],
            "scope_label": doc["scope_label"], "lines": len(doc["lines"]), "status": doc["status"]}


@router.get("/sessions")
async def list_sessions(request: Request, status: Optional[str] = None, kind: Optional[str] = None,
                        limit: int = 100):
    await require_auth(request)
    return serialize_doc(await eng.list_sessions(get_db(), status=status or "", kind=kind or "", limit=limit))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    legacy = await eng.legacy_acc_detail(db, session_id)
    if legacy:
        return {"session": serialize_doc(legacy), "archived": True, "lines": [], "totals": {}}
    return await eng.session_view(db, await eng.get_session(db, session_id))


@router.get("/resolve-bin")
async def resolve_bin(request: Request, barcode: str, session_id: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    if session_id:
        sess = await eng.get_session(db, session_id, for_write=True)
        b_id, label = await eng.resolve_count_bin(db, sess, code=barcode)
        return {"id": b_id, "bin_id": b_id, "label": label, "full_label": label, "floor": not b_id}
    pos = await _resolve_position(db, barcode=barcode)
    if not pos:
        raise HTTPException(404, "Bin tidak ditemukan")
    return serialize_doc(pos)


@router.get("/resolve-item")
async def resolve_item(request: Request, barcode: str):
    await require_auth(request)
    mat = await _resolve_item(get_db(), "", barcode)
    if not mat:
        raise HTTPException(404, f"Barang dengan kode/SKU '{barcode}' tidak ditemukan")
    return serialize_doc(mat)


@router.post("/scan")
async def scan(data: ScanIn, request: Request):
    """1 scan = +qty (bawaan 1) ke (sesi, bin/lantai, barang). Tanpa konfirmasi per scan."""
    user = await require_auth(request)
    db = get_db()
    sess, b_id, b_label, mat = await _ctx(db, data.session_id, data.bin_id, data.bin_barcode,
                                          data.item_material_id, data.item_barcode)
    return serialize_doc(await eng.record_count(db, user, sess, mat=mat, bin_id=b_id, bin_label=b_label,
                                                qty=float(data.qty or 1), input_uom=data.input_uom, mode="add"))


@router.post("/count")
async def count(data: CountIn, request: Request):
    """Ketik jumlah (set absolut) untuk (sesi, bin/lantai, barang)."""
    user = await require_auth(request)
    db = get_db()
    sess, b_id, b_label, mat = await _ctx(db, data.session_id, data.bin_id, data.bin_barcode,
                                          data.material_id, data.item_barcode)
    return serialize_doc(await eng.record_count(db, user, sess, mat=mat, bin_id=b_id, bin_label=b_label,
                                                qty=data.qty, input_uom=data.input_uom, mode="set"))


@router.post("/scan-undo")
async def scan_undo(data: ScanIn, request: Request):
    """Kurangi hitungan (floor 0 → kembali 'belum dihitung' bila tak ada hitungan lain)."""
    user = await require_auth(request)
    db = get_db()
    sess, b_id, b_label, mat = await _ctx(db, data.session_id, data.bin_id, data.bin_barcode,
                                          data.item_material_id, data.item_barcode)
    return serialize_doc(await eng.record_count(db, user, sess, mat=mat, bin_id=b_id, bin_label=b_label,
                                                qty=-float(data.qty or 1), input_uom=data.input_uom, mode="add"))


@router.post("/line")
async def set_line(data: LineIn, request: Request):
    await require_auth(request)
    db = get_db()
    sess = await eng.get_session(db, data.session_id, for_write=True)
    return await eng.set_line(db, sess, key=data.key, reason=data.reason, resolution=data.resolution)


@router.post("/submit")
async def submit_session(data: SessionRefIn, request: Request):
    """Selesai hitung → menunggu approval (stok belum berubah). Baris belum dihitung butuh
    konfirmasi `confirm_zero` (anggap 0)."""
    user = await require_auth(request)
    db = get_db()
    sess = await eng.get_session(db, data.session_id, for_write=True)
    sess = await eng.submit(db, user, sess, confirm_zero=data.confirm_zero, notes=data.notes)
    await log_activity(user.get("id", ""), user.get("name", ""), "opname_submit", SESS,
                       f"Opname {sess.get('session_no')} diajukan — {sess.get('summary')}")
    return await eng.session_view(db, sess)


@router.post("/approve")
async def approve_session(data: SessionRefIn, request: Request):
    """GERBANG SUPERVISOR: set saldo = hitung, penempatan bin, satu jurnal per sesi."""
    user = await require_auth(request)
    db = get_db()
    sess = await eng.get_session(db, data.session_id, for_write=True)
    assert_can_approve(user, "menyetujui opname", sess)
    sess = await eng.approve(db, user, sess)
    await log_activity(user.get("id", ""), user.get("name", ""), "opname_approve", SESS,
                       f"Opname {sess.get('session_no')} disetujui — {sess.get('summary')}")
    return await eng.session_view(db, sess)


@router.post("/reject")
async def reject_session(data: SessionRefIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    sess = await eng.get_session(db, data.session_id, for_write=True)
    assert_can_approve(user, "menolak opname", sess)
    return await eng.reject(db, user, sess, data.notes)


@router.post("/cancel")
async def cancel_session(data: SessionRefIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    sess = await eng.get_session(db, data.session_id, for_write=True)
    return await eng.cancel(db, user, sess)
