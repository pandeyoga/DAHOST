"""routes.marketing_impor_paket — **Impor banyak berkas, satu langkah** + AI pemeta + analisis impor.

Alur (audit Marketing §7.4, keputusan owner 9 Nov 2026 "sesuai rekomendasi"):

  ``POST /api/marketing/impor-paket``                 unggah banyak berkas / ZIP → jenis + toko per berkas
  ``PUT  /{paket}/berkas/{idx}``                      staf membetulkan jenis / toko / periode / ikut-tidak
  ``POST /{paket}/periksa``                           buat sesi impor per berkas (jalur impor yang ada) →
                                                      pratinjau gabungan (baris, pemetaan, rencana, rumus,
                                                      dampak omzet per hari)
  ``POST /{paket}/simpan``                            simpan BERURUTAN di latar (pesanan → status → retur →
                                                      iklan → KPI) lewat ``commit`` jalur impor yang ada
  ``POST /{paket}/batalkan``                          batalkan semua sesi paket (urutan terbalik)
  ``GET  /{paket}/analisis`` · ``/sesi/{id}/analisis`` temuan berangka untuk AI analis
  ``POST /{paket}/tanya-ai``                          buka percakapan Asisten AI tentang impor ini
  ``POST /sesi/{id}/ai-pemeta`` · ``/terapkan-pemetaan``  AI pemeta kolom sisa (lapis terakhir)

Setiap berkas tetap menjadi SATU sesi di `marketing_data_import_sessions` yang dibuat oleh
handler `routes.marketing_data_import.upload` — penjaga platform, gudang toko, kunci periode,
dedupe, rollback 72 jam, jejak pembatalan, dan rekap harian berlaku sama seperti impor satu berkas.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from starlette.datastructures import UploadFile as _UploadFile
from starlette.requests import Request as _Request

from auth import log_activity, require_auth
from core import impor_ai_pemeta as ap
from core import impor_analisis as an
from core import impor_invarian as iv
from core import impor_paket as pk
from core import impor_sidik as sd
from core import marketing_account_scope as scope
from core import marketing_import_engine as eng
from core import ukuran_penjualan as U
from core.marketing_import_prenorm import penanda_periode
from core.marketing_import_schema import DEPRECATED_SOURCE_TYPES, SOURCE_TYPES, get_source_type
from database import get_db
from object_storage import get_object as _get_object, put_object as _put_object

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/marketing/impor-paket", tags=["marketing-impor-paket"])

KOLEKSI = pk.KOLEKSI
SESI = "marketing_data_import_sessions"
PREFIX = "marketing-impor-paket"
_TUGAS: set = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ser(o: Any) -> Any:
    if isinstance(o, list):
        return [_ser(x) for x in o]
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items() if k != "_id"}
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return o


def _md():
    import routes.marketing_data_import as md
    return md


def _req_latar(request: Request) -> _Request:
    """Salinan permintaan untuk tugas LATAR (header & token sama, state baru)."""
    sc = dict(request.scope)
    sc["state"] = {}
    return _Request(sc)


def _detail(e: HTTPException) -> str:
    d = e.detail
    return d if isinstance(d, str) else str(d)


async def _toko(db, user) -> List[dict]:
    return await scope.visible_accounts(
        db, user, base={"status": {"$ne": "inactive"}},
        projection={"_id": 0, "id": 1, "account_name": 1, "account_code": 1, "platform": 1,
                    "platform_warehouse_name": 1, "username": 1, "platform_username": 1, "shop_username": 1,
                    "platform_shop_id": 1, "shop_id": 1})


async def _muat(db, user: dict, paket_id: str) -> dict:
    doc = await db[KOLEKSI].find_one({"id": paket_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Paket impor tidak ditemukan.")
    if doc.get("dibuat_oleh_id") != user.get("id") and not scope.sees_all_accounts(user):
        # staf berlingkup hanya melihat paket miliknya sendiri
        raise HTTPException(404, "Paket impor tidak ditemukan.")
    return doc


async def _simpan_doc(db, doc: dict) -> None:
    doc["updated_at"] = _now()
    doc["ringkas"] = pk.ringkas_paket(doc)
    await db[KOLEKSI].update_one({"id": doc["id"]}, {"$set": {k: v for k, v in doc.items() if k != "_id"}})


def _berkas(doc: dict, idx: int) -> dict:
    for b in doc.get("berkas") or []:
        if b.get("idx") == idx:
            return b
    raise HTTPException(404, "Berkas tidak ada di paket ini.")


def _baca_berkas(b: dict) -> bytes:
    found = _get_object(b["path"])
    if not found:
        raise HTTPException(410, f"Berkas '{b.get('nama')}' sudah tidak ada di server — unggah ulang paketnya.")
    return found[0]


def _nama_unggah(b: dict) -> str:
    if b.get("source_type") == "tiktok_gmv_max" and b.get("periode_mulai") and b.get("periode_selesai"):
        return penanda_periode(b["periode_mulai"], b["periode_selesai"], b["nama"])
    return b["nama"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. UNGGAH PAKET
# ═══════════════════════════════════════════════════════════════════════════════
@router.post("")
async def buat_paket(request: Request, files: List[UploadFile] = File(...)):
    """Unggah banyak berkas ekspor (atau satu ZIP). Tidak ada data yang disimpan ke tabel tujuan."""
    user = await require_auth(request)
    db = get_db()
    masuk = []
    for f in files or []:
        masuk.append((f.filename or "berkas", await f.read()))
    try:
        daftar = pk.urai_unggahan(masuk)
    except pk.GalatPaket as e:
        raise HTTPException(e.status, e.pesan) from None
    toko = await _toko(db, user)
    paket_id = str(uuid.uuid4())
    berkas = []
    for i, (nama, raw) in enumerate(daftar):
        ext = os.path.splitext(nama)[1].lower() or ".csv"
        path = f"{PREFIX}/{paket_id}/{i}{ext}"
        try:
            a = pk.analisa_berkas(nama, raw)
        except Exception as e:  # noqa: BLE001 — satu berkas rusak tidak menggagalkan paket
            log.warning("paket impor: berkas %s gagal dianalisis: %s", nama, e)
            a = {"nama": nama, "ukuran_kb": round(len(raw) / 1024, 1), "sidik": {"dikenal": False},
                 "jalur": "", "source_type": "", "label_jenis": "Tidak bisa dibaca", "platform": "",
                 "baris": 0, "peringatan": [f"Berkas tidak bisa dibaca: {e}"], "bukti_toko": {}}
        calon = await pk.cari_toko(db, toko, a)
        auto = pk.pilih_toko_otomatis(calon)
        _put_object(path, raw, "application/octet-stream")
        bt = a.pop("bukti_toko", {}) or {}
        b = {**a, "idx": i, "path": path, "ikut": True,
             "bukti_toko": {k: v for k, v in bt.items() if k != "nomor_pesanan"},
             "nomor_pesanan_dicek": len(bt.get("nomor_pesanan") or []),
             "toko_calon": calon[:5], "account_id": auto,
             "account_name": next((c["nama"] for c in calon if c["id"] == auto), None),
             "toko_otomatis": bool(auto), "sesi_id": None, "sesi_lama": [], "periksa": None, "hasil": None}
        b["kekurangan"] = pk.kekurangan(b)
        b["status"] = pk.status_awal(b)
        berkas.append(b)
    dup = {}
    for b in berkas:
        dup.setdefault(b.get("sha256"), []).append(b["nama"])
    for b in berkas:
        sama = [n for n in dup.get(b.get("sha256"), []) if n != b["nama"]]
        if sama:
            b["peringatan"].append(f"Isinya SAMA PERSIS dengan {', '.join(sama)} di paket ini.")
    doc = {"id": paket_id, "status": "pratinjau", "berkas": berkas,
           "dibuat_oleh_id": user.get("id"), "dibuat_oleh": user.get("email") or user.get("name") or "",
           "created_at": _now(), "updated_at": _now(), "progres": None}
    doc["ringkas"] = pk.ringkas_paket(doc)
    await db[KOLEKSI].insert_one(dict(doc))
    doc.pop("_id", None)
    await log_activity(user.get("id", ""), user.get("name", ""),
                       f"Unggah paket impor ({len(berkas)} berkas)", "marketing-impor-paket", paket_id)
    return {"ok": True, "paket": _ser(doc)}


@router.get("")
async def daftar_paket(request: Request, limit: int = 20):
    user = await require_auth(request)
    db = get_db()
    q = {} if scope.sees_all_accounts(user) else {"dibuat_oleh_id": user.get("id")}
    rows = await db[KOLEKSI].find(q, {"_id": 0, "berkas.path": 0}).sort("created_at", -1).to_list(max(1, min(limit, 50)))
    return {"ok": True, "paket": _ser(rows)}


@router.get("/{paket_id}")
async def ambil_paket(paket_id: str, request: Request):
    user = await require_auth(request)
    return {"ok": True, "paket": _ser(await _muat(get_db(), user, paket_id))}


class BerkasIn(BaseModel):
    source_type: Optional[str] = None
    account_id: Optional[str] = None
    periode_mulai: Optional[str] = None
    periode_selesai: Optional[str] = None
    ikut: Optional[bool] = None


@router.put("/{paket_id}/berkas/{idx}")
async def ubah_berkas(paket_id: str, idx: int, body: BerkasIn, request: Request):
    """Staf membetulkan jenis / toko / periode / ikut. Sesi lama (bila ada) ditinggalkan."""
    user = await require_auth(request)
    db = get_db()
    doc = await _muat(db, user, paket_id)
    if doc.get("status") in ("menyimpan", "selesai", "sebagian"):
        raise HTTPException(409, "Paket ini sudah disimpan — buat paket baru untuk mengubahnya.")
    b = _berkas(doc, idx)
    berubah = False
    if body.source_type is not None:
        key = body.source_type.strip()
        if key and (key not in SOURCE_TYPES or key in DEPRECATED_SOURCE_TYPES):
            raise HTTPException(400, "Jenis data tidak dikenal.")
        if key in pk.BUTUH_KONTEKS:
            raise HTTPException(400, "Jenis ini butuh pilihan host/kreator/katalog — impor lewat menu Impor Data.")
        b["source_type"] = key
        b["label_jenis"] = SOURCE_TYPES[key].label if key else "Belum dikenali"
        b["jalur"] = sd.JALUR_IMPOR if key else b.get("jalur")
        b["butuh_periode"] = key == "tiktok_gmv_max"
        berubah = True
    if body.account_id is not None:
        if body.account_id:
            await scope.assert_account_visible(db, user, body.account_id)
            acc = await db[scope.ACCOUNTS].find_one({"id": body.account_id}, {"_id": 0, "account_name": 1})
            if not acc:
                raise HTTPException(404, "Toko tidak ditemukan.")
            b["account_name"] = acc.get("account_name")
        b["account_id"] = body.account_id or None
        b["toko_otomatis"] = False
        berubah = True
    for k in ("periode_mulai", "periode_selesai"):
        v = getattr(body, k)
        if v is not None:
            if v and U.kunci_tanggal(v) != v:
                raise HTTPException(400, "Tanggal periode harus berformat TTTT-BB-HH.")
            b[k] = v or None
            berubah = True
    if b.get("periode_mulai") and b.get("periode_selesai") and b["periode_mulai"] > b["periode_selesai"]:
        raise HTTPException(400, "Tanggal mulai periode tidak boleh sesudah tanggal selesai.")
    if body.ikut is not None:
        b["ikut"] = bool(body.ikut)
        berubah = True
    if berubah and b.get("sesi_id"):
        b["sesi_lama"] = (b.get("sesi_lama") or []) + [b["sesi_id"]]
        b["sesi_id"], b["periksa"] = None, None
    b["kekurangan"] = pk.kekurangan(b)
    b["status"] = pk.status_awal(b)
    doc["status"] = "pratinjau"
    await _simpan_doc(db, doc)
    return {"ok": True, "paket": _ser(doc)}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PERIKSA (buat sesi impor per berkas → pratinjau gabungan)
# ═══════════════════════════════════════════════════════════════════════════════
async def _dampak_omzet(db, st, raw: bytes, fname: str, mapping: List[dict], account_id: str) -> Optional[dict]:
    """Omzet berkas per hari (aturan resmi) vs rekap yang sudah tersimpan untuk tanggal yang sama."""
    if st.key != "marketplace_orders":
        return None
    headers, rows = eng.parse_table(raw, fname, st)
    rows, _ = eng.strip_description_rows(rows, mapping, st)
    per: Dict[str, Dict[str, float]] = {}
    for b in eng.build_rows(rows, mapping, st):
        if b["status"] == "error":
            continue
        d = b["data"]
        if not U.dihitung_omzet({"status": d.get("status"), "paid_at": d.get("paid_at")}):
            continue
        k = U.kunci_tanggal(d.get("order_date"))
        if not k:
            continue
        p = per.setdefault(k, {"omzet": 0.0, "pesanan": 0})
        p["omzet"] += sum(float(it.get("sku_subtotal_after_discount") or 0) for it in d.get("items") or [])
        p["pesanan"] += 1
    if not per:
        return None
    tgl = sorted(per)
    rek, _ = await U.baca_rekap(db, [account_id], tgl[0], tgl[-1])
    by = {r["date"]: r for r in rek}
    hari = [{"tanggal": k, "omzet_berkas": round(per[k]["omzet"]), "pesanan_berkas": per[k]["pesanan"],
             "rekap_tersimpan": round(by[k]["omzet"]) if k in by else None} for k in tgl]
    return {"hari": hari[-62:], "total_berkas": round(sum(p["omzet"] for p in per.values())),
            "total_rekap": round(sum(r["omzet"] for r in rek)), "dari": tgl[0], "sampai": tgl[-1]}


async def _periksa_satu(db, request: Request, user: dict, b: dict) -> None:
    md = _md()
    st = get_source_type(b["source_type"])
    raw = _baca_berkas(b)
    fname = _nama_unggah(b)
    uf = _UploadFile(file=io.BytesIO(raw), filename=fname)
    try:
        res = await md.upload(request, file=uf, source_type=st.key, account_id=b["account_id"],
                              host_id=None, creator_id=None, catalog_id=None, live_session_id=None)
    except HTTPException as e:
        b.update({"status": "ditolak", "galat": _detail(e), "sesi_id": None, "periksa": None})
        return
    s = res["session"]
    sid = s["id"]
    mapping = s.get("mapping") or []
    terisi: List[str] = []
    summary, dup, value_report = res.get("summary") or {}, res.get("duplicates") or {}, res.get("value_report") or []
    report = s.get("mapping_report") or {}
    tersimpan = await ap.ambil_pemetaan(db, b["account_id"], st, s.get("headers") or [])
    if tersimpan:
        mapping2, terisi = ap.gabung_tersimpan(mapping, tersimpan, st)
        if terisi:
            out = await md.update_mapping(sid, md.MappingIn(mapping=mapping2), request)
            mapping, report = out["mapping"], out["mapping_report"]
            summary, dup, value_report = out.get("summary") or summary, out.get("duplicates") or dup, \
                out.get("value_report") or value_report
    on_dup = "update"
    try:
        plan = await md.plan(sid, request, on_duplicate=on_dup, skip_warnings=False, only=None, q=None,
                             page=1, page_size=1)
    except HTTPException as e:
        plan = {"counts": {}, "blockers": [{"message": _detail(e)}], "warnings": []}
    inv = None
    if not st.prenorm:
        try:
            headers, rows = eng.parse_table(raw, fname, st)
            rows, _ = eng.strip_description_rows(rows, mapping, st)
            inv = iv.ringkas(iv.uji(st, rows, mapping))
        except Exception as e:  # noqa: BLE001
            log.debug("uji rumus paket dilewati: %s", e)
    dampak = None
    try:
        dampak = await _dampak_omzet(db, st, raw, fname, mapping, b["account_id"])
    except Exception as e:  # noqa: BLE001
        log.debug("dampak omzet dilewati: %s", e)
    det = s.get("detection") or {}
    peringatan = []
    if s.get("parse_warning"):
        peringatan.append(s["parse_warning"])
    if (det.get("type_mismatch") or {}).get("message"):
        peringatan.append(det["type_mismatch"]["message"])
    if det.get("platform_mismatch"):
        peringatan.append(det["platform_mismatch"])
    if s.get("shop_guard_hint"):
        peringatan.append(s["shop_guard_hint"])
    if st.mapping_unverified:
        peringatan.append(st.mapping_unverified)
    for w in plan.get("warnings") or []:
        peringatan.append(w.get("message") if isinstance(w, dict) else str(w))
    unknown = sum(int(v.get("unknown") or 0) for v in value_report)
    b["sesi_id"] = sid
    b["periksa"] = {
        "baris": summary, "duplikat": dup if isinstance(dup, dict) else {},
        "pemetaan": {"siap": bool(report.get("ready")), "kolom_wajib_kurang": report.get("missing_required") or [],
                     "kolom_belum_terpetakan": (report.get("unmapped_columns") or [])[:40],
                     "terpetakan": report.get("mapped"), "total_kolom": report.get("total_columns"),
                     "dari_pemetaan_toko": terisi, "ingatan_format": bool(s.get("format_known"))},
        "nilai_belum_dikenal": unknown,
        "rencana": plan.get("counts") or {},
        "penghalang": [x.get("message") for x in plan.get("blockers") or [] if isinstance(x, dict)],
        "peringatan": [p for p in peringatan if p][:8],
        "invarian": inv, "dampak_omzet": dampak, "sekali_perbarui": st.key in pk.SELALU_PERBARUI,
    }
    b["galat"] = None
    if not report.get("ready") or unknown:
        b["status"] = "perlu_pemetaan"
    elif b["periksa"]["penghalang"]:
        b["status"] = "ditolak"
        b["galat"] = b["periksa"]["penghalang"][0]
    else:
        b["status"] = "diperiksa"


@router.post("/{paket_id}/periksa")
async def periksa_paket(paket_id: str, request: Request):
    """Buat (ulang) sesi impor untuk setiap berkas yang lengkap → pratinjau gabungan. Belum ada yang disimpan."""
    user = await require_auth(request)
    db = get_db()
    doc = await _muat(db, user, paket_id)
    if doc.get("status") in ("menyimpan", "selesai", "sebagian"):
        raise HTTPException(409, "Paket ini sudah disimpan.")
    for b in doc["berkas"]:
        if not b.get("ikut", True) or b.get("jalur") != sd.JALUR_IMPOR:
            continue
        b["kekurangan"] = pk.kekurangan(b)
        if b["kekurangan"]:
            b["status"] = "perlu_isian"
            continue
        await scope.assert_account_visible(db, user, b["account_id"])
        if b.get("sesi_id") and b.get("status") in ("diperiksa", "perlu_pemetaan"):
            # sesi sudah ada: segarkan dengan pemetaan terakhir (staf mungkin sudah memetakan)
            b["sesi_lama"] = (b.get("sesi_lama") or []) + [b["sesi_id"]]
            b["sesi_id"] = None
        await _periksa_satu(db, request, user, b)
    doc["status"] = "diperiksa" if any(b.get("status") == "diperiksa" for b in doc["berkas"]) else "pratinjau"
    await _simpan_doc(db, doc)
    return {"ok": True, "paket": _ser(doc)}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SIMPAN SEMUA (latar, berurutan) & BATALKAN
# ═══════════════════════════════════════════════════════════════════════════════
class SimpanIn(BaseModel):
    on_duplicate: str = "update"          # update | skip
    lewati_peringatan: bool = False


async def _jalankan_simpan(paket_id: str, request: _Request, opsi: SimpanIn) -> None:
    md = _md()
    db = get_db()
    doc = await db[KOLEKSI].find_one({"id": paket_id}, {"_id": 0})
    if not doc:
        return
    antre = [b for b in pk.urutan_simpan(doc["berkas"]) if b.get("status") == "diperiksa" and b.get("sesi_id")]
    doc["progres"] = {"total": len(antre), "selesai": 0, "sedang": None}
    for b in antre:
        doc["progres"]["sedang"] = b["nama"]
        await _simpan_doc(db, doc)
        od = "update" if b.get("source_type") in pk.SELALU_PERBARUI else opsi.on_duplicate
        s_now = await db[SESI].find_one({"id": b["sesi_id"]}, {"_id": 0, "status": 1})
        st_sesi = (s_now or {}).get("status")
        if st_sesi in pk.SESI_JANGAN_ULANG:
            # status `committing`/`partial` (jalur impor MKT-INTI): sesi pernah mulai disimpan dan terhenti —
            # TIDAK disimpan ulang (baris yang sudah masuk bisa dobel); dipulihkan lewat Batalkan/Riwayat Impor.
            b["status"] = "gagal" if st_sesi != "committed" else "disimpan"
            b["galat"] = pk.PESAN_SESI.get(st_sesi)
            doc["progres"]["selesai"] += 1
            continue
        try:
            res = await md.commit(b["sesi_id"], request,
                                  md.CommitIn(on_duplicate=od, skip_warnings=opsi.lewati_peringatan))
            b["hasil"] = {k: res.get(k) for k in ("inserted", "updated", "skipped_duplicates", "rejected",
                                                   "message", "daily_rollup", "undo_count")}
            b["status"], b["galat"] = "disimpan", None
        except HTTPException as e:
            b["status"], b["galat"] = "gagal", _detail(e)
        except Exception as e:  # noqa: BLE001 — satu berkas gagal tidak menghentikan berkas lain
            log.exception("paket impor %s: commit berkas %s gagal", paket_id, b.get("nama"))
            b["status"], b["galat"] = "gagal", f"Gagal disimpan: {type(e).__name__}"
        doc["progres"]["selesai"] += 1
    doc["progres"]["sedang"] = None
    gagal = sum(1 for b in antre if b["status"] == "gagal")
    doc["status"] = "selesai" if not gagal else ("sebagian" if gagal < len(antre) else "gagal")
    doc["disimpan_at"] = _now()
    await _simpan_doc(db, doc)


@router.post("/{paket_id}/simpan")
async def simpan_paket(paket_id: str, request: Request, body: Optional[SimpanIn] = None):
    """Simpan SEMUA berkas berstatus "Siap disimpan" berurutan di latar. Jawab segera; layar memantau progres."""
    user = await require_auth(request)
    db = get_db()
    doc = await _muat(db, user, paket_id)
    if doc.get("status") == "menyimpan":
        raise HTTPException(409, "Paket ini sedang disimpan.")
    if doc.get("status") in ("selesai", "sebagian"):
        raise HTTPException(409, "Paket ini sudah disimpan.")
    siap = [b for b in doc["berkas"] if b.get("status") == "diperiksa" and b.get("sesi_id")]
    if not siap:
        raise HTTPException(400, "Belum ada berkas yang siap disimpan. Tekan Periksa dulu dan lengkapi berkas yang kurang.")
    for b in siap:
        await scope.assert_account_visible(db, user, b.get("account_id"))
    opsi = body or SimpanIn()
    if opsi.on_duplicate not in ("update", "skip"):
        raise HTTPException(400, "Pilihan duplikat harus update atau skip.")
    doc["status"] = "menyimpan"
    doc["progres"] = {"total": len(siap), "selesai": 0, "sedang": None}
    await _simpan_doc(db, doc)
    task = asyncio.ensure_future(_jalankan_simpan(paket_id, _req_latar(request), opsi))
    _TUGAS.add(task)
    task.add_done_callback(_TUGAS.discard)
    await log_activity(user.get("id", ""), user.get("name", ""),
                       f"Simpan paket impor ({len(siap)} berkas)", "marketing-impor-paket", paket_id)
    return {"ok": True, "paket": _ser(doc),
            "pesan": f"{len(siap)} berkas sedang disimpan berurutan. Halaman ini memperbarui progresnya."}


@router.post("/{paket_id}/batalkan")
async def batalkan_paket(paket_id: str, request: Request):
    """Batalkan semua berkas yang sudah tersimpan (urutan terbalik) lewat pembatalan jalur impor."""
    md = _md()
    user = await require_auth(request)
    db = get_db()
    doc = await _muat(db, user, paket_id)
    if doc.get("status") == "menyimpan":
        raise HTTPException(409, "Paket ini sedang disimpan — tunggu sampai selesai.")
    hasil = []
    ids = [x["sesi_id"] for x in doc["berkas"] if x.get("sesi_id")]
    st_sesi = {s["id"]: s.get("status") for s in await db[SESI].find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "status": 1}).to_list(len(ids) + 1)} if ids else {}
    bisa = [x for x in doc["berkas"] if x.get("sesi_id")
            and (x.get("status") == "disimpan" or st_sesi.get(x["sesi_id"]) in ("committed", "partial"))]
    for b in reversed(pk.urutan_simpan(bisa)):
        await scope.assert_account_visible(db, user, b.get("account_id"))
        try:
            r = await md.rollback(b["sesi_id"], request)
            b["status"] = "dibatalkan"
            hasil.append({"nama": b["nama"], "ok": True, "pesan": r.get("message") if isinstance(r, dict) else ""})
        except HTTPException as e:
            hasil.append({"nama": b["nama"], "ok": False, "pesan": _detail(e)})
    if hasil and all(h["ok"] for h in hasil):
        doc["status"] = "dibatalkan"
    await _simpan_doc(db, doc)
    return {"ok": True, "hasil": hasil, "paket": _ser(doc)}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. AI PEMETA (sesi mana pun: paket atau impor satu berkas)
# ═══════════════════════════════════════════════════════════════════════════════
async def _sesi_dan_baris(db, user: dict, session_id: str):
    s = await db[SESI].find_one({"id": session_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Sesi impor tidak ditemukan.")
    await scope.assert_account_visible(db, user, s.get("account_id"))
    st = get_source_type(s["source_type"])
    path = s.get("file_path")
    if path and os.path.isabs(path):
        try:
            raw = open(path, "rb").read()
        except OSError:
            raw = None
    else:
        found = _get_object(path) if path else None
        raw = found[0] if found else None
    if raw is None:
        raise HTTPException(410, "Berkas sesi ini sudah tidak ada di server. Unggah ulang berkasnya.")
    fname = s.get("filename") or "data.csv"
    if s.get("prenorm_fallback"):
        _h, rows = eng.parse_table_fallback(raw, fname, st)
    else:
        _h, rows = eng.parse_table(raw, fname, st)
    rows, _ = eng.strip_description_rows(rows, s.get("mapping") or [], st)
    tabel = None
    if not st.prenorm:
        try:
            _hasil, tabel = sd.tabel_utama(raw, fname)
        except Exception:  # noqa: BLE001
            tabel = None
    return s, st, rows, tabel


@router.post("/sesi/{session_id}/ai-pemeta")
async def ai_pemeta(session_id: str, request: Request):
    """Usulan AI untuk kolom yang BELUM terpetakan. Tidak mengubah apa pun; kolom uang diuji rumus."""
    user = await require_auth(request)
    db = get_db()
    s, st, rows, tabel = await _sesi_dan_baris(db, user, session_id)
    try:
        out = await ap.usulkan(st, rows, s.get("mapping") or [], user_id=user.get("id"), tabel=tabel)
    except ap.GalatPemeta as e:
        raise HTTPException(e.status, e.pesan) from None
    await db[SESI].update_one({"id": session_id}, {"$set": {
        "ai_used": True, "ai_suggestion": out["usulan"], "updated_at": _now()}})
    return {"ok": True, **out}


class TerapkanIn(BaseModel):
    pilihan: Dict[str, str]                 # kolom → field (yang disetujui staf)
    simpan_untuk_toko: bool = True


@router.post("/sesi/{session_id}/terapkan-pemetaan")
async def terapkan_pemetaan(session_id: str, body: TerapkanIn, request: Request):
    """Terapkan usulan yang DISETUJUI staf. Kolom uang diuji rumus lagi; pemetaan disimpan per toko + jenis."""
    md = _md()
    user = await require_auth(request)
    db = get_db()
    s, st, rows, _t = await _sesi_dan_baris(db, user, session_id)
    if s.get("status") == "committed":
        raise HTTPException(400, "Sesi sudah disimpan; buat sesi baru untuk mengubah pemetaan.")
    mapping = s.get("mapping") or []
    sisa = set(ap.kolom_sisa(mapping))
    pilihan = {c: f for c, f in (body.pilihan or {}).items() if c in sisa and f}
    if not pilihan:
        raise HTTPException(400, "Tidak ada usulan yang dipilih untuk kolom yang belum terpetakan.")
    uang = {c: f for c, f in pilihan.items() if iv.field_uang(st, f)}
    if uang:
        putusan = iv.hakim_usulan(st, rows, mapping, uang)
        tolak = {c: p["alasan"] for c, p in putusan.items() if not p["diterima"]}
        if tolak:
            c, alasan = next(iter(tolak.items()))
            raise HTTPException(409, f"Kolom “{c}” tidak lolos uji rumus: {alasan}")
    baru = ap.terapkan(mapping, pilihan, st, metode="ai")
    out = await md.update_mapping(session_id, md.MappingIn(mapping=baru), request)
    if body.simpan_untuk_toko and s.get("account_id"):
        await ap.simpan_pemetaan(db, account_id=s["account_id"], st=st, headers=s.get("headers") or [],
                                 mapping=out["mapping"], user=user, sumber="ai_dikonfirmasi_staf")
    return {"ok": True, **_ser(out)}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ANALISIS IMPOR (bahan AI analis) & TANYA AI
# ═══════════════════════════════════════════════════════════════════════════════
@router.get("/sesi/{session_id}/analisis")
async def analisis_sesi(session_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    s = await db[SESI].find_one({"id": session_id}, {"_id": 0, "account_id": 1})
    if not s:
        raise HTTPException(404, "Sesi impor tidak ditemukan.")
    await scope.assert_account_visible(db, user, s.get("account_id"))
    return {"ok": True, **(await an.analisis_sesi(db, [session_id]))}


@router.get("/{paket_id}/analisis")
async def analisis_paket(paket_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    doc = await _muat(db, user, paket_id)
    ids = [b["sesi_id"] for b in doc["berkas"] if b.get("sesi_id")]
    for b in doc["berkas"]:
        if b.get("sesi_id"):
            await scope.assert_account_visible(db, user, b.get("account_id"))
    out = await an.analisis_sesi(db, ids)
    out["paket"] = {"id": paket_id, "status": doc.get("status"), "ringkas": doc.get("ringkas"),
                    "berkas": [{"nama": b["nama"], "jenis": b.get("label_jenis"), "toko": b.get("account_name"),
                                "status": pk.STATUS_LABEL.get(b.get("status"), b.get("status")),
                                "galat": b.get("galat"), "hasil": b.get("hasil")} for b in doc["berkas"]]}
    return {"ok": True, **_ser(out)}


@router.post("/{paket_id}/tanya-ai")
async def tanya_ai(paket_id: str, request: Request):
    """Buka percakapan Asisten AI yang langsung menganalisis paket ini (angka dari alat `analisis_impor`)."""
    from core import laporan_marketing as lm
    user = await require_auth(request)
    db = get_db()
    doc = await _muat(db, user, paket_id)
    for b in doc["berkas"]:
        if b.get("sesi_id"):
            await scope.assert_account_visible(db, user, b.get("account_id"))
    jenis = ", ".join(sorted({b.get("label_jenis") or "-" for b in doc["berkas"] if b.get("ikut", True)}))
    teks = (f"Analisis hasil impor paket ini ({len(doc['berkas'])} berkas: {jenis}). Panggil alat analisis_impor "
            f"dengan paket_id \"{paket_id}\", lalu jelaskan singkat: apa yang masuk, temuan terpenting (omzet naik/"
            "turun tajam, pesanan batal melonjak, biaya iklan aneh, SKU belum tertaut, selisih dengan laporan "
            "penghasilan, baris ditolak) beserta angkanya, dan langkah yang perlu dilakukan staf. Pakai hanya angka "
            "dari alat. Jangan mengubah data apa pun.")
    return await lm.mulai_percakapan(request, user, judul=f"Analisis impor {doc['created_at']:%d %b %Y}"
                                     if isinstance(doc.get("created_at"), datetime) else "Analisis impor", teks=teks)
