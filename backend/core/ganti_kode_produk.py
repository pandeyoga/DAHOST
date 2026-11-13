"""core.ganti_kode_produk — ganti KODE / NAMA produk tanpa membuat produk kembar (13 Nov 2026).

Laporan staf R&D (owner: "dibenarkan"): di Style & Desain, ganti nama produk "tidak berubah" dan ganti kode
produk/SKU "malah menambah produk baru (dobel)". Akar: `core.master_sync` mencari style R&D lewat KODE, jadi kode
yang berbeda (diubah di R&D atau di Master Produk) membuat style kedua, dan nama style selalu ditimpa nama master.

Aturan yang dipegang modul ini (Master Produk = SSOT, keputusan owner 2026-09-12):
  1. Satu produk (`rahaza_models`) punya SATU style R&D utama, dicari lewat TAUTAN dulu
     (`model.rnd_style_id` / `style.promoted_to_model_id`), baru lewat kode — :func:`pilih_style_utama`.
  2. Kode & nama style utama selalu = kode & nama master (:func:`selaraskan_style_tertaut`). Perubahan dari R&D
     ditulis ke master lewat jalur resmi `routes.rahaza_production.ubah_model`, bukan ditimpa diam-diam.
  3. Ganti kode produk ikut mengganti SKU varian (`{KODE}-{WARNA}-{UKURAN}`), kode barang jadi (= SKU), kode
     potongan (`CUT-{KODE}-…`), kode potongan di baris BOM, dan SKU di varian R&D — SEMUA tertaut id, jadi tidak ada
     dokumen baru. Kode lama disimpan di `code_aliases` / `sku_aliases` (label lama tetap terbaca scanner).
  4. Ganti kode DITOLAK (409) bila SKU-nya sudah dipakai di luar master (stok, PO, cutting, katalog, pesanan,
     marketplace, …; daftar = `routes.rahaza_variants.cek_pemakaian_produk`). SKU yang sudah dipakai bisa sudah
     tercetak di label, terdaftar di Seller Center, atau tertulis di Excel/dokumen — menggantinya diam-diam membuat
     teks itu tidak cocok lagi dengan master. Mengganti SKU yang sudah dipakai = keputusan owner (lihat laporan PR).
  5. Ganti nama produk menyegarkan salinan nama milik produk itu sendiri (varian, barang jadi, potongan) — hanya
     nama yang memang dibentuk otomatis dari nama lama; nama ketikan khusus tidak disentuh. Nama item katalog
     toko tidak diubah (nama jualan per platform boleh berbeda, keputusan lama `propagate_master_changes`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from core.cut_panel_master import panel_code, panel_name, slug
from utils.variant_ssot import build_variant_sku, fg_display_name

# Pemakaian yang TIDAK menghalangi ganti kode: rujukan R&D ikut diganti modul ini, dan riwayat HPP/harga
# tertaut id (teks SKU di riwayat = apa yang tercatat saat itu, tidak dibaca ulang untuk mencari barang).
PEMAKAIAN_DIABAIKAN = frozenset({
    "style R&D asal produk", "varian R&D asal SKU", "riwayat penerapan HPP", "riwayat harga SKU",
})


def _now():
    return datetime.now(timezone.utc)


def _u(v) -> str:
    return str(v or "").strip().upper()


def ganti_awalan(teks: str, lama: str, baru: str) -> str | None:
    """'LAMA-HTM-M' → 'BARU-HTM-M' bila diawali `LAMA-` (tanpa beda huruf besar/kecil); selain itu None."""
    t, a = _u(teks), _u(lama)
    if not a or not t.startswith(a + "-"):
        return None
    return _u(baru) + t[len(a):]


# ══════════════════════════════ style R&D utama ══════════════════════════════

def style_tertaut(style: dict, model_id: str) -> bool:
    """Style boleh dipakai model ini: belum tertaut model lain dan bukan kembaran yang sudah digabung."""
    if not style or style.get("merged_into_style_id"):
        return False
    return style.get("promoted_to_model_id") in (None, "", model_id)


def pilih_style_utama(model: dict, kandidat: list) -> dict | None:
    """Style R&D utama sebuah model dari `kandidat` (fungsi murni).

    Urutan: `model.rnd_style_id` (bila style itu memang tertaut model ini) → style ber-`promoted_to_model_id`
    = model ini (kodenya sama dengan kode model dulu, lalu yang paling lama dibuat)."""
    mid = model.get("id")
    hidup = [s for s in kandidat if style_tertaut(s, mid)]
    rid = model.get("rnd_style_id")
    for s in hidup:
        if rid and s.get("id") == rid:
            return s
    milik = [s for s in hidup if s.get("promoted_to_model_id") == mid]
    if not milik:
        return None
    kode = _u(model.get("code"))
    milik.sort(key=lambda s: (_u(s.get("style_code")) != kode, str(s.get("created_at") or ""), str(s.get("id"))))
    return milik[0]


async def style_utama(db, model: dict) -> dict | None:
    """Style R&D utama model (lihat :func:`pilih_style_utama`) — dibaca dari DB."""
    syarat = [{"promoted_to_model_id": model["id"]}]
    if model.get("rnd_style_id"):
        syarat.append({"id": model["rnd_style_id"]})
    kandidat = await db.dewi_rnd_styles.find({"$or": syarat}, {"_id": 0}).to_list(50)
    return pilih_style_utama(model, kandidat)


def field_style_dari_model(model: dict) -> dict:
    """Isi style R&D yang MILIK master (sama persis dengan yang disalin `core.master_sync`)."""
    return {"style_name": model.get("name") or "",
            "category": model.get("category_name") or model.get("category") or "",
            "fabric_type": model.get("fabric_type", ""), "description": model.get("description", "")}


async def pemegang_kode_style(db, kode: str, kecuali_id: str | None = None) -> dict | None:
    """Style lain yang sudah memakai kode ini (kode style unik)."""
    q = {"style_code": _u(kode)}
    if kecuali_id:
        q["id"] = {"$ne": kecuali_id}
    return await db.dewi_rnd_styles.find_one(q, {"_id": 0, "id": 1, "style_code": 1, "style_name": 1})


async def selaraskan_style_tertaut(db, model: dict) -> dict:
    """Samakan style R&D utama dengan master: kode, nama, kategori, jenis kain, deskripsi (+ salinan di varian R&D).

    Dipanggil sesudah master berubah (`ubah_model`). Kode TIDAK dipindah bila kode itu sedang dipegang style lain
    (dilaporkan `konflik`) — `ubah_model` sudah menolaknya lebih dulu, ini hanya pengaman."""
    st = await style_utama(db, model)
    if not st:
        return {"style_id": None}
    kode, nama = _u(model.get("code")), model.get("name") or ""
    patch = {**field_style_dari_model(model), "promoted_to_model_id": model["id"], "updated_at": _now()}
    konflik = None
    if kode and _u(st.get("style_code")) != kode:
        lain = await pemegang_kode_style(db, kode, st["id"])
        if lain:
            konflik = f"kode {kode} dipegang style lain ({lain.get('style_name') or lain.get('id')})"
        else:
            patch["style_code"] = kode
    await db.dewi_rnd_styles.update_one({"id": st["id"]}, {"$set": patch})
    kode_st = patch.get("style_code") or st.get("style_code")
    await db.dewi_rnd_variants.update_many(
        {"style_id": st["id"], "$or": [{"style_code": {"$ne": kode_st}}, {"style_name": {"$ne": nama}}]},
        {"$set": {"style_code": kode_st, "style_name": nama, "updated_at": _now()}})
    if model.get("rnd_style_id") != st["id"] or _u(model.get("rnd_style_code")) != _u(kode_st):
        await db.rahaza_models.update_one({"id": model["id"]},
                                          {"$set": {"rnd_style_id": st["id"], "rnd_style_code": kode_st}})
    return {"style_id": st["id"], "style_code": kode_st, "konflik": konflik}


# ══════════════════════════════ ganti kode produk ══════════════════════════════

async def rencana_ganti_kode(db, model: dict, kode_baru: str) -> dict:
    """Rencana ganti kode (TANPA menulis): apa yang ikut berganti, pemakaian, dan bentrok kode."""
    from routes.rahaza_variants import pemakaian_produk   # impor lambat: modul rute mengimpor modul ini
    mid, lama, baru = model["id"], _u(model.get("code")), _u(kode_baru)
    variants = await db.rahaza_model_variants.find({"model_id": mid}, {"_id": 0}).to_list(5000)
    vids = [v["id"] for v in variants if v.get("id")]
    sku_lama = [_u(v.get("sku")) for v in variants if v.get("sku")]

    varian, belum = [], []
    for v in variants:
        old = _u(v.get("sku"))
        new = ganti_awalan(old, lama, baru)
        if not new and v.get("color_code") and v.get("size_code"):
            new = build_variant_sku(baru, v.get("color_code"), v.get("size_code"), v.get("option_code"))
        if not new:
            belum.append(old or v["id"])
            continue
        varian.append({"id": v["id"], "lama": old, "baru": new})
    sku_baru_vid = {r["id"]: r["baru"] for r in varian}
    sku_baru_teks = {r["lama"]: r["baru"] for r in varian if r["lama"]}

    fg_q = [{"model_id": mid}] + ([{"variant_id": {"$in": vids}}] if vids else []) + (
        [{"code": {"$in": sku_lama}}] if sku_lama else [])
    fgs = await db.rahaza_materials.find({"type": "fg", "$or": fg_q}, {"_id": 0}).to_list(5000)
    barang_jadi = []
    for f in fgs:
        old = _u(f.get("code"))
        new = sku_baru_vid.get(f.get("variant_id")) or sku_baru_teks.get(old) or ganti_awalan(old, lama, baru)
        if new and new != old:
            barang_jadi.append({"id": f["id"], "lama": old, "baru": new})

    panels = await db.rahaza_materials.find({"is_cut_panel": True, "model_id": mid}, {"_id": 0}).to_list(5000)
    potongan = []
    for p in panels:
        old = _u(p.get("code"))
        new = ganti_awalan(old, "CUT-" + slug(lama), "CUT-" + slug(baru)) or panel_code(
            baru, p.get("color_code") or "", p.get("size_code") or "")
        if new and new != old:
            potongan.append({"id": p["id"], "lama": old, "baru": new})

    fg_ids, panel_ids = [f["id"] for f in fgs], [p["id"] for p in panels]
    pakai = await pemakaian_produk(db, model_id=mid, variant_ids=vids, skus=sku_lama, fg_ids=fg_ids,
                                   material_ids=panel_ids)
    pakai = {k: n for k, n in pakai.items() if k not in PEMAKAIAN_DIABAIKAN}

    bentrok = []
    baru_sku = [r["baru"] for r in varian if r["baru"] != r["lama"]]
    if len(set(baru_sku)) != len(baru_sku):
        bentrok.append("dua varian akan mendapat SKU yang sama")
    if baru_sku:
        for v in await db.rahaza_model_variants.find(
                {"sku": {"$in": baru_sku}, "id": {"$nin": vids}}, {"_id": 0, "sku": 1}).to_list(20):
            bentrok.append(f"SKU {v.get('sku')} sudah dipakai varian produk lain")
    kode_barang = [r["baru"] for r in barang_jadi + potongan]
    if kode_barang:
        for m in await db.rahaza_materials.find(
                {"code": {"$in": kode_barang}, "id": {"$nin": fg_ids + panel_ids}},
                {"_id": 0, "code": 1, "name": 1}).to_list(20):
            bentrok.append(f"kode barang {m.get('code')} sudah dipakai {m.get('name') or 'barang lain'}")
    st = await style_utama(db, model)
    lain = await pemegang_kode_style(db, baru, (st or {}).get("id"))
    if lain:
        bentrok.append(f"kode {baru} sudah dipakai style R&D lain ({lain.get('style_name') or lain.get('style_code')})")
    return {"model_id": mid, "kode_lama": lama, "kode_baru": baru, "varian": varian, "barang_jadi": barang_jadi,
            "potongan": potongan, "sku_tidak_terbaca": belum, "pemakaian": pakai, "bentrok": bentrok}


def tolak_bila_tidak_aman(rencana: dict) -> None:
    """409 dengan kalimat staf bila SKU sudah dipakai atau kode baru bentrok (fungsi murni)."""
    from core.hapus_master import rincian_pemakaian
    lama, baru = rencana["kode_lama"], rencana["kode_baru"]
    if rencana["pemakaian"]:
        raise HTTPException(409, (
            f'Kode produk "{lama}" tidak bisa diganti menjadi "{baru}" karena SKU-nya sudah dipakai di '
            f'{rincian_pemakaian(rencana["pemakaian"])}. SKU yang sudah dipakai bisa sudah tercetak di label, '
            'terdaftar di marketplace, atau tertulis di dokumen, jadi tidak diganti otomatis. '
            'Bila kode memang salah, minta owner memutuskan penggantiannya.'))
    if rencana["bentrok"]:
        raise HTTPException(409, f'Kode produk "{lama}" tidak bisa diganti menjadi "{baru}": '
                                 + "; ".join(rencana["bentrok"][:5]) + ". Pilih kode lain.")
    if rencana["sku_tidak_terbaca"]:
        raise HTTPException(409, (
            f'Kode produk "{lama}" tidak bisa diganti: SKU {", ".join(rencana["sku_tidak_terbaca"][:5])} '
            'tidak berawalan kode produk dan warna/ukurannya kosong, jadi SKU barunya tidak bisa ditentukan. '
            'Lengkapi varian itu di Master Produk dulu.'))


async def terapkan_ganti_kode(db, rencana: dict) -> dict:
    """Tulis rencana yang sudah lolos :func:`tolak_bila_tidak_aman`. Semua tertaut id → tidak ada dokumen baru."""
    now, baru = _now(), rencana["kode_baru"]
    n_var = 0
    for r in rencana["varian"]:
        upd = {"$set": {"sku": r["baru"], "model_code": baru, "updated_at": now}}
        if r["lama"] and r["lama"] != r["baru"]:
            upd["$addToSet"] = {"sku_aliases": r["lama"]}
        await db.rahaza_model_variants.update_one({"id": r["id"]}, upd)
        n_var += 1
    await db.rahaza_model_variants.update_many({"model_id": rencana["model_id"], "model_code": {"$ne": baru}},
                                               {"$set": {"model_code": baru}})
    for r in rencana["barang_jadi"]:
        await db.rahaza_materials.update_one({"id": r["id"]}, {
            "$set": {"code": r["baru"], "sku": r["baru"], "model_code": baru, "updated_at": now},
            "$addToSet": {"code_aliases": r["lama"]}})
    for r in rencana["potongan"]:
        await db.rahaza_materials.update_one({"id": r["id"]}, {
            "$set": {"code": r["baru"], "model_code": baru, "style_sku": baru, "updated_at": now},
            "$addToSet": {"code_aliases": r["lama"]}})
    await db.rahaza_materials.update_many(
        {"model_id": rencana["model_id"], "$or": [{"type": "fg"}, {"is_cut_panel": True}], "model_code": {"$ne": baru}},
        {"$set": {"model_code": baru}})
    # salinan kode di baris stok bersaldo 0 (`core.stock_service.derive_identity`) — stok bersaldo sudah ditolak
    for r in rencana["barang_jadi"] + rencana["potongan"]:
        await db.rahaza_material_stock.update_many({"material_id": r["id"], "material_code": r["lama"]},
                                                   {"$set": {"material_code": r["baru"]}})
    # kode potongan di baris BOM (salinan teks; tautan = material_id)
    kode_panel = {r["id"]: r["baru"] for r in rencana["potongan"]}
    n_bom = 0
    if kode_panel:
        async for b in db.rahaza_boms.find({"model_id": rencana["model_id"]}, {"_id": 0, "id": 1, "materials": 1}):
            mats, ubah = [], False
            for ln in b.get("materials") or []:
                if isinstance(ln, dict) and ln.get("material_id") in kode_panel and ln.get("code") != kode_panel[ln["material_id"]]:
                    ln = {**ln, "code": kode_panel[ln["material_id"]]}
                    ubah = True
                mats.append(ln)
            if ubah:
                await db.rahaza_boms.update_one({"id": b["id"]}, {"$set": {"materials": mats, "updated_at": now}})
                n_bom += 1
    # SKU di varian R&D yang tertaut varian master (sizes[].variant_id) atau masih memakai teks SKU lama
    sku_vid = {r["id"]: r["baru"] for r in rencana["varian"]}
    sku_teks = {r["lama"]: r["baru"] for r in rencana["varian"] if r["lama"]}
    n_rnd = 0
    if sku_vid:
        q = {"$or": [{"sizes.variant_id": {"$in": list(sku_vid)}}, {"sizes.sku": {"$in": list(sku_teks)}}]}
        async for rv in db.dewi_rnd_variants.find(q, {"_id": 0, "id": 1, "sizes": 1}):
            sizes, ubah = [], False
            for s in rv.get("sizes") or []:
                if isinstance(s, dict):
                    nb = sku_vid.get(s.get("variant_id")) or sku_teks.get(_u(s.get("sku")))
                    if nb and _u(s.get("sku")) != nb:
                        s = {**s, "sku": nb}
                        ubah = True
                sizes.append(s)
            if ubah:
                await db.dewi_rnd_variants.update_one({"id": rv["id"]}, {"$set": {"sizes": sizes, "updated_at": now}})
                n_rnd += 1
    return {"kode_lama": rencana["kode_lama"], "kode_baru": baru, "varian": n_var,
            "barang_jadi": len(rencana["barang_jadi"]), "potongan": len(rencana["potongan"]),
            "bom": n_bom, "varian_rnd": n_rnd}


# ══════════════════════════════ ganti nama produk ══════════════════════════════

def nama_baru_turunan(nama: str, otomatis_lama: str, otomatis_baru: str, nama_lama: str, nama_baru: str,
                      awalan: str = "") -> str | None:
    """Nama turunan baru bila `nama` memang dibentuk dari nama lama; None = biarkan (fungsi murni).

    `otomatis_*` = nama bentukan otomatis (format resmi) dengan nama model lama/baru. Bila tidak sama persis,
    nama yang DIAWALI `awalan + nama_lama` diganti awalannya saja (nama dari impor Excel: "MELA DRESS MAROON M")."""
    if not nama or not nama_lama or nama_lama == nama_baru:
        return None
    if nama == otomatis_lama:
        return otomatis_baru
    if nama.startswith(awalan + nama_lama):
        return awalan + nama_baru + nama[len(awalan + nama_lama):]
    return None


async def segarkan_nama_turunan(db, model: dict, nama_lama: str) -> dict:
    """Nama model berubah → salinan nama di varian, barang jadi, dan potongan milik model ini ikut berubah."""
    mid, nama_baru, now = model["id"], model.get("name") or "", _now()
    if not nama_baru or nama_baru == nama_lama:
        return {"varian": 0, "barang_jadi": 0, "potongan": 0}
    r = await db.rahaza_model_variants.update_many({"model_id": mid, "model_name": {"$ne": nama_baru}},
                                                   {"$set": {"model_name": nama_baru, "updated_at": now}})
    n_fg = n_panel = 0
    async for f in db.rahaza_materials.find({"type": "fg", "model_id": mid}, {"_id": 0}):
        patch = {"model_name": nama_baru}
        nm = nama_baru_turunan(f.get("name") or "", fg_display_name({**f, "model_name": nama_lama}),
                               fg_display_name({**f, "model_name": nama_baru}), nama_lama, nama_baru)
        if nm:
            patch["name"] = nm
        if f.get("model_name") != nama_baru or nm:
            await db.rahaza_materials.update_one({"id": f["id"]}, {"$set": {**patch, "updated_at": now}})
            n_fg += 1
        if nm:   # salinan nama di baris stok (`core.stock_service.derive_identity`) yang masih nama lama
            await db.rahaza_material_stock.update_many({"material_id": f["id"], "material_name": f.get("name")},
                                                       {"$set": {"material_name": nm}})
    async for p in db.rahaza_materials.find({"is_cut_panel": True, "model_id": mid}, {"_id": 0}):
        patch = {"style_name": nama_baru}
        warna, ukuran = p.get("color") or p.get("color_code") or "", p.get("size_code") or ""
        nm = nama_baru_turunan(p.get("name") or "", panel_name(nama_lama, warna, ukuran),
                               panel_name(nama_baru, warna, ukuran), nama_lama, nama_baru, awalan="Potongan ")
        if nm:
            patch["name"] = nm
        if p.get("style_name") != nama_baru or nm:
            await db.rahaza_materials.update_one({"id": p["id"]}, {"$set": {**patch, "updated_at": now}})
            n_panel += 1
    return {"varian": r.modified_count, "barang_jadi": n_fg, "potongan": n_panel}
