"""core/kain_master.py — kain di tech pack R&D SINKRON master (owner 21 Nov 2026, permintaan Ega R&D).

Owner: "harus singkron bukan dipilih bebas … pilih kain dulu dari master data … jika belum, buatkan master datanya
termasuk input satuan yang benar, harus ada info juga ke orang yang pegang roll kain … supaya satuan konversi dll
benar-benar terjaga."

Aturan:
* KELUARGA kain = kode tanpa akhiran warna (KN-RMT-LLG → KN-RMT). Daftar keluarga = master kain roll
  (`rahaza_materials` type fabric, satuan dari master) ∪ Riset Material (`dewi_rnd_materials`, katalog R&D).
  Satu keluarga = satu satuan (kg atau yard/meter) — satuan TIDAK dipilih di tech pack, selalu dari master.
* Baris kain tech pack menyimpan `kode` keluarga + nama kanonik master; kain + warna → master per warna
  `<kode>-<kode warna>`. Belum ada → dibuat dari keluarganya (satuan, kemasan, gramasi/lebar, kategori, harga
  keluarga sebagai harga awal) dan pemegang roll kain diberi tahu.
* Keluarga baru (belum ada sama sekali) didaftarkan di Riset Material dengan satuan wajib (kg / yard / meter).
* Pemakaian per ukuran mengikuti satuan kainnya: kain kg → berat (kg) per hasil pcs; kain yard/meter →
  panjang (cm) per hasil pcs.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from core import bom_uom

# Pemegang roll kain: SPV Cutting mengeluarkan roll untuk dipotong, SPV Gudang menerima kain pembelian.
PENERIMA_PERAN = ("spv_cuting", "spv_gudang")
KODE_DIKECUALIKAN = {"KN-TBD"}          # "KAIN BELUM DITENTUKAN" = penanda, bukan kain
SATUAN_SAH = {"kg": "kg", "yard": "yard", "m": "m", "meter": "m"}
POLA_KODE = re.compile(r"^[A-Z]{2,3}-[A-Z0-9]{2,6}$")


def _now():
    return datetime.now(timezone.utc)


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())


def kode_keluarga(code: str) -> str:
    c = str(code or "").strip().upper()
    return c.rsplit("-", 1)[0] if c.count("-") >= 2 else c


def _satuan(u) -> str:
    n = bom_uom.norm_unit(u or "") or ""
    return {"meter": "m", "mtr": "m", "yd": "yard", "yards": "yard", "kilogram": "kg", "kgs": "kg"}.get(n, n)


def satuan_dasar(m: dict) -> str:
    return _satuan((m or {}).get("base_uom") or (m or {}).get("unit") or "")


def satuan_pakai(satuan: str) -> str:
    """Cara mengisi pemakaian di tech pack: 'kg' (berat) untuk kain ber-satuan berat, selain itu 'cm' (panjang)."""
    return "kg" if bom_uom.norm_unit(satuan) in ("kg", "gram") else "cm"


async def daftar_keluarga(db) -> list:
    """[{kode, nama, satuan, satuan_pakai, warna:[{kode_warna, kode, material_id, nama_warna}], riset_id}]"""
    fam: dict = {}
    async for m in db.rahaza_materials.find(
            {"type": "fabric", "active": {"$ne": False}, "is_cut_panel": {"$ne": True}},
            {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "base_uom": 1, "color": 1, "gsm": 1, "width_cm": 1}):
        code = str(m.get("code") or "").upper()
        if not code or code.startswith("CUT-"):
            continue
        k = kode_keluarga(code)
        if k in KODE_DIKECUALIKAN:
            continue
        f = fam.setdefault(k, {"kode": k, "nama": m.get("name") or k, "satuan": satuan_dasar(m), "warna": [],
                               "gsm": m.get("gsm"), "lebar_cm": m.get("width_cm"), "riset_id": None})
        if code != k:
            f["warna"].append({"kode_warna": code.rsplit("-", 1)[1], "kode": code, "material_id": m.get("id"),
                               "nama_warna": m.get("color") or ""})
    async for r in db.dewi_rnd_materials.find({"status": {"$ne": "inactive"}}, {"_id": 0}):
        k = str(r.get("material_code") or "").strip().upper()
        if not k or k in KODE_DIKECUALIKAN:
            continue
        f = fam.setdefault(k, {"kode": k, "nama": r.get("material_name") or k,
                               "satuan": _satuan(r.get("unit") or r.get("price_unit") or ""),
                               "warna": [], "gsm": r.get("gsm"), "lebar_cm": r.get("width_cm"), "riset_id": None})
        f["riset_id"] = r.get("id")
    out = []
    for f in fam.values():
        f["satuan_pakai"] = satuan_pakai(f["satuan"])
        f["warna"].sort(key=lambda w: w["kode_warna"])
        out.append(f)
    return sorted(out, key=lambda f: _norm(f["nama"]))


def _pilih(keluarga: list, kode: str = "", nama: str = "") -> dict | None:
    k, n = str(kode or "").strip().upper(), _norm(nama)
    for f in keluarga:
        if (k and f["kode"] == k) or (not k and n and _norm(f["nama"]) == n):
            return f
    return None


async def cari_keluarga(db, kode: str = "", nama: str = "") -> dict | None:
    return _pilih(await daftar_keluarga(db), kode, nama)


async def _kabari_pemegang_roll(db, judul: str, isi: str, user: dict | None, ref: dict) -> None:
    try:
        from utils.notif_unified import notif_insert
        await notif_insert(db, type="rnd_kain_master", subtype="kain_master_baru", severity="info", title=judul,
                           body=isi, target_roles=list(PENERIMA_PERAN), source_type="rahaza_materials",
                           source_id=ref.get("id"), source_ref=ref.get("code"),
                           meta={"dibuat_oleh": (user or {}).get("name") or "", **ref})
    except Exception:  # noqa: BLE001 — pemberitahuan tidak boleh menggagalkan pembuatan master
        import logging
        logging.getLogger(__name__).warning("notifikasi kain master gagal untuk %s", ref.get("code"), exc_info=True)


async def pastikan_master_warna(db, kode: str, kode_warna: str, user: dict | None = None) -> dict:
    """Master kain roll `<kode keluarga>-<kode warna>`; dibuat dari keluarganya bila belum ada (+ kabari pemegang roll).
    Hasil: {material, dibuat}."""
    k, w = str(kode or "").strip().upper(), str(kode_warna or "").strip().upper()
    if not k or not w:
        raise HTTPException(400, "Pilih kain dan warnanya dulu.")
    code = f"{k}-{w}"
    ada = await db.rahaza_materials.find_one({"code": code, "active": {"$ne": False}}, {"_id": 0})
    if ada:
        return {"material": ada, "dibuat": False}
    warna = await db.rahaza_colors.find_one({"code": w}, {"_id": 0, "code": 1, "name": 1})
    if not warna:
        raise HTTPException(400, f"Warna {w} tidak ada di master warna.")
    keluarga = await cari_keluarga(db, kode=k)
    if not keluarga:
        raise HTTPException(400, f"Kain {k} belum terdaftar — daftarkan kain barunya dulu (nama, kode, satuan).")
    satuan = keluarga.get("satuan") or ""
    if satuan not in ("kg", "yard", "m"):
        raise HTTPException(400, f"Satuan kain {k} ('{satuan or '-'}') belum benar di master — perbaiki satuannya dulu.")
    contoh = await db.rahaza_materials.find_one(
        {"code": {"$regex": f"^{re.escape(k)}-"}, "type": "fabric", "active": {"$ne": False},
         "is_cut_panel": {"$ne": True}}, {"_id": 0})
    salin = ("type", "name", "unit", "base_uom", "uoms", "pack_unit", "pack_size", "display_in_packs",
             "purchase_uom", "issue_uom", "display_uom", "composition", "gsm", "width_cm", "category",
             "category_code", "category_id", "category_name", "min_stock")
    if contoh:
        doc = {kk: contoh[kk] for kk in salin if kk in contoh}
        harga = float(contoh.get("unit_cost") or 0)
    else:
        from core import uom
        cat = await db.rahaza_material_categories.find_one({"code": "FABRIC"}, {"_id": 0, "id": 1, "code": 1, "name": 1})
        doc = {"type": "fabric", "name": keluarga["nama"], "unit": satuan, **uom.apply_payload({"unit": satuan}),
               "gsm": keluarga.get("gsm"), "width_cm": keluarga.get("lebar_cm"),
               **({"category": cat["id"], "category_id": cat["id"], "category_code": cat["code"],
                   "category_name": cat.get("name") or "Kain"} if cat else {})}
        harga = 0.0
    doc.update({"id": str(uuid.uuid4()), "code": code, "color": warna.get("name") or w, "color_code": w,
                "unit_cost": harga, "cost_method": "salin_keluarga" if harga else "belum_ada",
                "active": True, "created_from": "techpack_rnd",
                "notes": "Dibuat dari tech pack R&D (warna baru keluarga " + k + ")",
                "created_by": (user or {}).get("id", "system"), "created_by_name": (user or {}).get("name", ""),
                "created_at": _now(), "updated_at": _now()})
    await db.rahaza_materials.insert_one(dict(doc))
    doc.pop("_id", None)
    await _kabari_pemegang_roll(
        db, f"Master kain baru: {code}",
        f"{(user or {}).get('name') or 'R&D'} membuat master kain {doc.get('name')} warna {doc['color']} ({code}, satuan "
        f"{satuan}) dari tech pack. Pastikan roll kain warna ini dicatat dengan kode {code} saat diterima/dipotong."
        + (f" Harga awal disalin dari keluarga: Rp {harga:,.0f}/{satuan}." if harga else " Harga belum ada."),
        user, {"id": doc["id"], "code": code})
    return {"material": doc, "dibuat": True}


async def daftar_keluarga_baru(db, *, nama: str, kode: str, satuan: str, gsm=None, lebar_cm=None,
                               user: dict | None = None) -> dict:
    """Kain yang belum ada sama sekali: didaftarkan di Riset Material dengan satuan yang benar (+ kabari)."""
    nama = str(nama or "").strip().upper()
    kode = str(kode or "").strip().upper()
    sat = SATUAN_SAH.get(str(satuan or "").strip().lower())
    if not nama:
        raise HTTPException(400, "Nama kain wajib diisi.")
    if not POLA_KODE.match(kode):
        raise HTTPException(400, "Kode kain berbentuk KN-XXX (huruf/angka 2–6), mis. KN-RMT.")
    if not sat:
        raise HTTPException(400, "Satuan kain wajib: kg, yard, atau meter.")
    if await cari_keluarga(db, kode=kode):
        raise HTTPException(409, f"Kode {kode} sudah dipakai kain lain.")
    sama = await cari_keluarga(db, nama=nama)
    if sama:
        raise HTTPException(409, f"Kain {nama} sudah ada dengan kode {sama['kode']} — pilih dari daftar.")
    from routes.dewi_rnd_materials import resolve_riset_masters
    masters = await resolve_riset_masters(db, {"category_code": "FABRIC"})

    def _f(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    doc = {"id": str(uuid.uuid4()), "material_code": kode, "material_name": nama, **masters,
           "composition": "", "weight": 0, "colors": [], "price_unit": sat, "price_per_unit": 0.0,
           "price_per_meter": 0.0, "unit": sat, "gsm": _f(gsm), "width_cm": _f(lebar_cm),
           "linked_material_id": "", "min_order_qty": 0, "test_results": "", "status": "active",
           "notes": "Didaftarkan dari tech pack R&D", "created_from": "techpack_rnd",
           "created_by": (user or {}).get("id", "system"), "created_by_name": (user or {}).get("name", ""),
           "created_at": _now(), "updated_at": _now()}
    await db.dewi_rnd_materials.insert_one(dict(doc))
    doc.pop("_id", None)
    await _kabari_pemegang_roll(
        db, f"Kain baru didaftarkan R&D: {nama} ({kode})",
        f"{(user or {}).get('name') or 'R&D'} mendaftarkan kain baru {nama} kode {kode}, satuan {sat}. Master per "
        f"warna dibuat saat warnanya dipilih di tech pack; roll kain ini nanti dicatat dengan kode {kode}-<warna>.",
        user, {"id": doc["id"], "code": kode})
    return doc


async def normalisasi_kain(db, rows: list) -> list:
    """Baris kain tech pack → harus menunjuk keluarga master (kode); nama & satuan ikut master. Baris kosong dibuang.
    Nama lama yang ejaannya beda (huruf/spasi) dicocokkan otomatis; yang tidak dikenal ditolak dengan pesan jelas."""
    out = []
    keluarga = await daftar_keluarga(db) if rows else []
    for r in rows or []:
        r = dict(r or {})
        if not str(r.get("kode") or r.get("name") or "").strip():
            continue
        f = _pilih(keluarga, kode=r.get("kode") or "", nama="" if r.get("kode") else r.get("name") or "")
        if not f:
            raise HTTPException(400, (f"Kain '{str(r.get('name') or r.get('kode')).strip()}' belum ada di master kain. "
                                      "Pilih dari daftar kain, atau daftarkan kain barunya dulu."))
        r.update({"kode": f["kode"], "name": f["nama"], "satuan": f["satuan"], "satuan_pakai": f["satuan_pakai"]})
        cc = str(r.get("color_code") or "").upper()
        w = next((x for x in f["warna"] if x["kode_warna"] == cc), None) if cc else None
        r["master_code"] = w["kode"] if w else ""
        r["master_id"] = w["material_id"] if w else ""
        out.append(r)
    return out


async def cocokkan_kain_longgar(db, rows: list) -> tuple:
    """Seperti `normalisasi_kain` tetapi TIDAK menolak (dipakai impor Excel): kain yang dikenal diikat ke master,
    yang tidak dikenal dibiarkan tanpa `kode` + dilaporkan, supaya R&D memilihnya di tab Bahan.
    Hasil: (rows, [nama kain tak dikenal])."""
    keluarga = await daftar_keluarga(db) if rows else []
    out, asing = [], []
    for r in rows or []:
        r = dict(r or {})
        if not str(r.get("kode") or r.get("name") or "").strip():
            continue
        f = _pilih(keluarga, kode=r.get("kode") or "", nama="" if r.get("kode") else r.get("name") or "")
        if not f:
            r["kode"] = ""
            nama = str(r.get("name") or "").strip()
            if nama and nama not in asing:
                asing.append(nama)
            out.append(r)
            continue
        r.update({"kode": f["kode"], "name": f["nama"], "satuan": f["satuan"], "satuan_pakai": f["satuan_pakai"]})
        cc = str(r.get("color_code") or "").upper()
        w = next((x for x in f["warna"] if x["kode_warna"] == cc), None) if cc else None
        r["master_code"] = w["kode"] if w else ""
        r["master_id"] = w["material_id"] if w else ""
        out.append(r)
    return out, asing


def satuan_pemakaian(cons: list, fabrics: list) -> list:
    """Satuan tiap baris pemakaian = satuan kain dengan peran yang sama (kg → berat, selain itu panjang)."""
    peran = {}
    for f in fabrics or []:
        peran.setdefault(f.get("role") or "main", f.get("satuan_pakai") or "cm")
    out = []
    for c in cons or []:
        c = dict(c or {})
        c["satuan"] = peran.get(c.get("fabric_role") or "main", "cm")
        out.append(c)
    return out
