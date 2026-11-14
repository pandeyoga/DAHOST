"""core/kirim_sampel.py — Kirim Sample: satu kiriman banyak produk + alur gudang (keputusan owner 14 Nov 2026).

Permintaan PIC toko, diputus owner:
  1. SATU kiriman = tanggal, toko, kreator, jenis (live/video), kurir, SATU ongkir, catatan + ``lines`` (kreator live
     sering menerima sampai 6 produk sekaligus). HPP per baris ikut katalog/master dan tidak bisa diketik.
     Dokumen lama (satu produk di tingkat atas, 3 dokumen di produksi) DIBACA sebagai satu baris — tanpa migrasi.
  2. Status kirim (Belum dikirim / Dikirim / Sampai) dan tindak lanjut bebas maju-mundur.
  3. Stok ada ⇒ gudang mengeluarkan SENDIRI lewat "Keluarkan stok" (alasan Sampel) yang ditautkan ke baris kiriman
     (bukan otomatis). Baris tampil "Menunggu gudang" sampai pengeluarannya tercatat.
  4. Stok 0/kurang ⇒ draf PO "Sampel R&D" otomatis untuk kekurangannya (`core.po_sampel`).
  5. Biaya sampel di anggaran Marketing = Σ (HPP + ongkir) kiriman toko itu pada periodenya (`biaya_periode`).

Bentuk satu baris tersimpan::

    {id, catalog_item_id, sku, product, size, color, quantity, hpp, total_hpp,
     fg_material_id, fg_code, variant_sku, stok_bebas, qty_dari_stok, qty_produksi, rencana_at,
     po_id?, po_number?, po_catatan?, barang_keluar: [{issue_id, issue_number, qty, location_id, at, by}]}

Field hitungan (`qty_keluar`, `sisa_keluar`, `status_gudang`, `status_gudang_label`, `keterangan_gudang`,
`lama`) hanya ada di jawaban API dan dibuang sebelum disimpan (`bersihkan_baris`).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException

STATUS_KIRIM = {"pending": "Belum dikirim", "shipped": "Dikirim", "delivered": "Sampai"}
TINDAK_LANJUT = {"open": "Terbuka", "follow_up": "Ditindaklanjuti", "sold": "Terjual",
                 "no_response": "Tidak ada respons", "closed": "Ditutup"}
STATUS_BATAL = "cancelled"            # nilai lama; kiriman batal tidak dihitung biaya & tidak masuk antrean gudang
MAKS_BARIS = 20
ALASAN_FG = "sample"                  # `routes.rahaza_inventory_fg.FG_ISSUE_REASONS`
BARIS_LAMA_ID = "baris-1"
JENIS_PO = "kirim_sampel"

GUDANG_LABEL = {
    "menunggu_gudang": "Menunggu gudang",
    "keluar_sebagian": "Keluar sebagian",
    "sudah_keluar": "Sudah keluar gudang",
    "diproduksi": "Diproduksi",
    "perlu_po_manual": "Perlu PO manual",
}
_HITUNGAN = ("qty_keluar", "sisa_keluar", "status_gudang", "status_gudang_label", "keterangan_gudang", "lama",
             "stok_tersedia")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def baru_id() -> str:
    return str(uuid.uuid4())


def kode_kiriman(doc: dict) -> str:
    """Nomor rujukan kiriman (dipakai catatan PO & pemilih gudang): KS-YYYYMMDD-XXXXXX dari tanggal + id."""
    if doc.get("sample_code"):
        return doc["sample_code"]
    d = str(doc.get("date") or "")[:10].replace("-", "")
    return f"KS-{d or '00000000'}-{str(doc.get('id') or '')[:6].upper()}"


# ══════════════════════════════════════════════════════════════════════════════
# Baca: dokumen lama → baris, hitungan per baris
# ══════════════════════════════════════════════════════════════════════════════
def baris_lama(doc: dict) -> dict:
    """Dokumen satu produk (sebelum 14 Nov 2026) → satu baris. Tidak ditulis balik sampai kiriman diubah."""
    qty = _i(doc.get("quantity"))
    hpp = _f(doc.get("hpp"))
    cid = doc.get("catalog_item_id")
    if isinstance(cid, list):
        cid = cid[0] if cid else None
    total = doc.get("total_hpp")
    return {"id": BARIS_LAMA_ID, "catalog_item_id": cid, "sku": doc.get("sku") or "",
            "product": doc.get("product") or "", "size": doc.get("size") or "", "color": doc.get("color") or "",
            "quantity": qty, "hpp": hpp, "total_hpp": _f(total) if total is not None else hpp * qty,
            "barang_keluar": [], "lama": True}


def baris_tersimpan(doc: dict) -> list:
    lines = doc.get("lines")
    if isinstance(lines, list) and lines:
        return [dict(x) for x in lines if isinstance(x, dict)]
    return [baris_lama(doc)]


def qty_keluar(line: dict) -> int:
    return sum(_i(k.get("qty")) for k in (line.get("barang_keluar") or []) if isinstance(k, dict))


def hitung_baris(line: dict) -> dict:
    """Tambah hitungan status gudang pada satu baris (fungsi murni)."""
    out = dict(line)
    qty = _i(line.get("quantity"))
    keluar = qty_keluar(line)
    sisa = max(0, qty - keluar)
    po = line.get("po_number")
    dari_stok, produksi = _i(line.get("qty_dari_stok")), _i(line.get("qty_produksi"))
    if line.get("lama") or not line.get("rencana_at"):
        st, label, ket = None, "Dicatat sebelum alur gudang", ""
    elif sisa == 0:
        st, label, ket = "sudah_keluar", GUDANG_LABEL["sudah_keluar"], ""
    elif po:
        st, label = "diproduksi", f"Diproduksi · {po}"
        tunggu = max(0, dari_stok - keluar)
        ket = f"{tunggu} pcs dari stok menunggu gudang" if tunggu else ""
    elif produksi > 0:
        st, label = "perlu_po_manual", line.get("po_catatan") or "PO sampel perlu dibuat manual oleh admin produksi"
        ket = f"Stok kurang {produksi} pcs"
    elif keluar > 0:
        st, label, ket = "keluar_sebagian", f"Keluar sebagian · {keluar}/{qty} pcs", ""
    else:
        st, label, ket = "menunggu_gudang", GUDANG_LABEL["menunggu_gudang"], ""
    out.update({"qty_keluar": keluar, "sisa_keluar": sisa, "status_gudang": st, "status_gudang_label": label,
                "keterangan_gudang": ket})
    return out


def bersihkan_baris(line: dict) -> dict:
    return {k: v for k, v in line.items() if k not in _HITUNGAN}


def ringkas_gudang(lines: Iterable[dict]) -> str:
    """'2 menunggu gudang · 1 diproduksi' — satu kalimat untuk kolom tabel."""
    urut = ("menunggu_gudang", "keluar_sebagian", "diproduksi", "perlu_po_manual", "sudah_keluar")
    n = {k: 0 for k in urut}
    for ln in lines:
        if ln.get("status_gudang") in n:
            n[ln["status_gudang"]] += 1
    return " · ".join(f"{n[k]} {GUDANG_LABEL[k].lower()}" for k in urut if n[k])


def normalise(doc: dict) -> dict:
    """Dokumen kiriman → bentuk baku untuk layar (baris + hitungan). Dokumen lama → satu baris."""
    out = dict(doc)
    lines = [hitung_baris(x) for x in baris_tersimpan(doc)]
    out["lines"] = lines
    out["sample_code"] = kode_kiriman(doc)
    out["total_hpp"] = round(sum(_f(x.get("total_hpp")) for x in lines), 2)
    out["total_qty"] = sum(_i(x.get("quantity")) for x in lines)
    out["biaya_total"] = round(out["total_hpp"] + _f(doc.get("ongkir")), 2)
    out["catalog_item_ids"] = [x["catalog_item_id"] for x in lines if x.get("catalog_item_id")]
    out["catalog_item_id"] = out["catalog_item_ids"][0] if out["catalog_item_ids"] else None
    out["ringkas_gudang"] = ringkas_gudang(lines)
    out["status_kirim_label"] = STATUS_KIRIM.get(doc.get("shipment_status"), doc.get("shipment_status") or "")
    out["tindak_lanjut_label"] = TINDAK_LANJUT.get(doc.get("progress"), doc.get("progress") or "")
    return out


def turunan(lines: list) -> dict:
    """Field tingkat atas yang DITURUNKAN dari baris (ringkasan lama tetap terbaca pembaca lama).

    `catalog_item_id` disimpan sebagai DAFTAR id: penjaga hapus item katalog
    (`marketing_catalog_items.catalog_item_usage` — `{'catalog_item_id': {'$in': ids}}`) cocok ke elemen daftar
    (semantik Mongo), jadi item yang dipakai baris ke-2 dst. tetap tidak bisa dihapus."""
    first = lines[0] if lines else {}
    qty = sum(_i(x.get("quantity")) for x in lines)
    total = round(sum(_f(x.get("total_hpp")) for x in lines), 2)
    n = len(lines)
    return {"quantity": qty, "total_hpp": total, "jumlah_baris": n,
            "product": (first.get("product") or "") + (f" + {n - 1} produk lain" if n > 1 else ""),
            "sku": first.get("sku") or "", "size": first.get("size") or "", "color": first.get("color") or "",
            "hpp": _f(first.get("hpp")) if n == 1 else (round(total / qty, 2) if qty else 0.0),
            "catalog_item_id": [x["catalog_item_id"] for x in lines if x.get("catalog_item_id")]}


# ══════════════════════════════════════════════════════════════════════════════
# Tulis: susun baris dari formulir, gabung saat diubah
# ══════════════════════════════════════════════════════════════════════════════
async def susun_baris(db, masukan: dict, account_id: str, line_id: Optional[str] = None) -> dict:
    """Satu baris formulir → baris tersimpan. Produk WAJIB dari katalog toko yang sama; HPP ikut katalog."""
    qty = _i(masukan.get("quantity"))
    if qty <= 0:
        raise HTTPException(400, "Jumlah setiap produk minimal 1 pcs.")
    cid = str(masukan.get("catalog_item_id") or "").strip()
    if cid:
        item = await db.marketing_catalog_items.find_one({"id": cid}, {"_id": 0})
        if not item:
            raise HTTPException(404, "Item katalog tidak ditemukan")
        if item.get("account_id") and item.get("account_id") != account_id:
            raise HTTPException(400, f"Item katalog {item.get('sku') or item.get('name') or ''} milik toko lain. "
                                     "Pilih item dari katalog toko yang sama.")
        hpp = _f(item.get("hpp"))
        base = {"catalog_item_id": cid, "sku": item.get("sku") or "", "product": item.get("name") or "",
                "size": masukan.get("size") or item.get("fg_size") or "",
                "color": masukan.get("color") or item.get("fg_color") or ""}
    else:
        # jalur lama (impor / klien lama): produk tanpa katalog, HPP sesuai yang dikirim
        if not str(masukan.get("product") or "").strip():
            raise HTTPException(400, "Produk belum dipilih — pilih produk dari katalog toko.")
        hpp = _f(masukan.get("hpp"))
        base = {"catalog_item_id": None, "sku": masukan.get("sku") or "", "product": masukan["product"].strip(),
                "size": masukan.get("size") or "", "color": masukan.get("color") or ""}
    return {"id": line_id or baru_id(), **base, "quantity": qty, "hpp": hpp, "total_hpp": round(hpp * qty, 2),
            "barang_keluar": []}


def tolak_dobel(lines: list) -> None:
    seen, dobel = set(), []
    for ln in lines:
        cid = ln.get("catalog_item_id")
        if cid and cid in seen:
            dobel.append(ln.get("sku") or ln.get("product") or cid)
        seen.add(cid)
    if dobel:
        raise HTTPException(400, f"Produk {', '.join(dobel)} dipilih dua kali dalam satu kiriman — gabungkan jumlahnya.")
    if len(lines) > MAKS_BARIS:
        raise HTTPException(400, f"Paling banyak {MAKS_BARIS} produk per kiriman.")
    if not lines:
        raise HTTPException(400, "Pilih minimal satu produk.")


async def po_hidup(db, line: dict) -> bool:
    return bool(line.get("po_id")) and bool(
        await db.production_pos.find_one({"id": line["po_id"]}, {"_id": 0, "id": 1}))


async def alasan_terkunci(db, line: dict) -> str:
    """Kenapa produk/jumlah baris ini tidak boleh diubah lagi ('' = boleh)."""
    nama = line.get("sku") or line.get("product") or "Baris ini"
    if qty_keluar(line) > 0:
        return f"{nama} sudah keluar gudang — produk dan jumlahnya tidak bisa diubah atau dihapus."
    if await po_hidup(db, line):
        return (f"{nama} sudah dibuatkan draf PO sampel {line.get('po_number') or ''} — minta admin produksi "
                "menghapus draf PO itu dulu, atau tambahkan baris baru untuk jumlah tambahan.").replace("  ", " ")
    return ""


async def gabung_baris(db, lama_doc: dict, masukan: list, account_id: str) -> tuple:
    """Baris formulir saat kiriman DIUBAH → (baris baru, id baris yang perlu direncanakan ulang).

    Baris lama dicocokkan lewat `id`. Baris yang sudah keluar gudang / sudah ber-PO sampel terkunci: produk &
    jumlahnya tidak boleh berubah dan barisnya tidak boleh dihapus (pesan menyebut jalan keluarnya)."""
    lama = {x["id"]: x for x in baris_tersimpan(lama_doc) if x.get("id")}
    hasil, rencana, dipakai = [], set(), set()
    for m in masukan:
        lid = str(m.get("id") or "").strip()
        old = lama.get(lid)
        if old is None:
            ln = await susun_baris(db, m, account_id)
            hasil.append(ln)
            rencana.add(ln["id"])
            continue
        dipakai.add(lid)
        cid_baru = str(m.get("catalog_item_id") or old.get("catalog_item_id") or "") or None
        berubah = cid_baru != (old.get("catalog_item_id") or None) or _i(m.get("quantity")) != _i(old.get("quantity"))
        kunci = await alasan_terkunci(db, old)
        if not berubah:
            keep = dict(old)
            keep.pop("lama", None)
            if not kunci:
                keep["size"] = m.get("size") or keep.get("size") or ""
                keep["color"] = m.get("color") or keep.get("color") or ""
            hasil.append(keep)
            continue
        if kunci:
            raise HTTPException(400, kunci)
        ln = await susun_baris(db, {**m, "catalog_item_id": cid_baru}, account_id, line_id=lid)
        hasil.append(ln)
        rencana.add(lid)
    for lid, old in lama.items():
        if lid not in dipakai:
            kunci = await alasan_terkunci(db, old)
            if kunci:
                raise HTTPException(400, kunci)
    # akun berubah: baris lama yang dipertahankan tetap harus milik katalog toko yang (baru) dipilih
    for ln in hasil:
        if ln.get("catalog_item_id") and ln["id"] not in rencana:
            item = await db.marketing_catalog_items.find_one({"id": ln["catalog_item_id"]}, {"_id": 0, "account_id": 1,
                                                                                            "sku": 1, "name": 1})
            if item and item.get("account_id") and item["account_id"] != account_id:
                raise HTTPException(400, f"Item katalog {item.get('sku') or item.get('name') or ''} milik toko lain. "
                                         "Pilih item dari katalog toko yang sama.")
    tolak_dobel(hasil)
    return hasil, rencana


# ══════════════════════════════════════════════════════════════════════════════
# Stok & PO sampel (keputusan 3 + 4)
# ══════════════════════════════════════════════════════════════════════════════
async def terpesan(db, fg_material_id: str, kecuali: set) -> int:
    """Stok yang SUDAH diharapkan baris kiriman lain (dari stok, belum keluar gudang) — supaya dua kiriman tidak
    sama-sama mengandalkan pcs yang sama."""
    if not fg_material_id:
        return 0
    docs = await db.marketing_samples.find(
        {"lines.fg_material_id": fg_material_id, "shipment_status": {"$ne": STATUS_BATAL}},
        {"_id": 0, "id": 1, "lines": 1}).to_list(5000)
    total = 0
    for d in docs:
        for ln in d.get("lines") or []:
            if ln.get("fg_material_id") != fg_material_id or (d.get("id"), ln.get("id")) in kecuali:
                continue
            total += max(0, _i(ln.get("qty_dari_stok")) - qty_keluar(ln))
    return total


async def rencanakan_baris(db, sample: dict, line: dict, user: Optional[dict]) -> dict:
    """Cek stok barang jadi baris ini; kekurangan → draf PO "Sampel R&D" (sekali per baris)."""
    from core import catalog_stock as cs
    from core import po_sampel
    out = bersihkan_baris(line)
    item = None
    if out.get("catalog_item_id"):
        item = await db.marketing_catalog_items.find_one({"id": out["catalog_item_id"]}, {"_id": 0})
    fg_id, fg_code, vsku, vid, avail = None, "", out.get("sku") or "", "", 0.0
    blocked = await cs.blocked_location_ids(db)
    if item:
        res = await cs.item_sellable(db, item, blocked_locs=blocked)
        fg_id, fg_code = res.get("fg_material_id"), res.get("fg_code") or ""
        vsku = res.get("variant_sku") or item.get("sku") or vsku
        vid = item.get("variant_id") or ""
        avail = _f(res.get("available")) if fg_id else 0.0
    if not fg_id and vsku:
        fg = await cs.find_fg_by_sku(db, vsku)
        if fg.get("id"):
            fg_id, fg_code = fg["id"], fg.get("code") or fg.get("sku") or ""
            avail = _f((await cs.sellable_stock(db, fg_id, blocked_locs=blocked)).get("available"))
    dipakai = await terpesan(db, fg_id, {(sample.get("id"), out.get("id"))})
    bebas = max(0, int(avail) - dipakai)
    qty = _i(out.get("quantity"))
    dari_stok = min(qty, bebas)
    kurang = qty - dari_stok
    out.update({"fg_material_id": fg_id, "fg_code": fg_code, "variant_sku": vsku, "stok_bebas": bebas,
                "qty_dari_stok": dari_stok, "qty_produksi": kurang, "rencana_at": _now()})
    for k in ("po_id", "po_number", "po_catatan"):
        out.pop(k, None)
    if kurang > 0:
        hasil = await po_sampel.buat_draf(
            db, jenis=JENIS_PO, sumber_id=sample["id"], baris_id=out["id"], nomor=kode_kiriman(sample),
            qty=kurang, user=user, variant_id=vid, sku=vsku,
            catatan=f"Kirim sampel ke {sample.get('username') or sample.get('creator_name') or 'kreator'} "
                    f"({sample.get('account_name') or ''}) · {out.get('product') or ''}.")
        out.update({k: v for k, v in hasil.items() if k in ("po_id", "po_number", "po_catatan")})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Gudang: antrean + tautan pengeluaran "Keluarkan stok" (keputusan 3)
# ══════════════════════════════════════════════════════════════════════════════
def produk_cocok(line: dict, mat: dict) -> bool:
    if line.get("fg_material_id"):
        return line["fg_material_id"] == mat.get("id")
    sku = str(line.get("variant_sku") or line.get("sku") or "").strip().upper()
    return bool(sku) and sku in {str(mat.get("code") or "").upper(), str(mat.get("sku") or "").upper()}


async def periksa_keluar(db, reason: str, rows: list) -> None:
    """Baris pengeluaran yang DITAUTKAN ke kiriman sampel: alasan Sampel, produk sama, jumlah ≤ sisa baris.
    Semua galat sekaligus; satu saja salah ⇒ tidak ada yang dikeluarkan (pemanggil memeriksa SEBELUM posting)."""
    linked = [r for r in rows if r.get("marketing_sample_id") or r.get("sample_line_id")]
    if not linked:
        return
    if reason != ALASAN_FG:
        raise HTTPException(400, "Kiriman sampel hanya bisa ditautkan bila alasan pengeluaran 'Sampel / contoh'.")
    errs, per_baris, cache = [], {}, {}
    mats = {m["id"]: m for m in await db.rahaza_materials.find(
        {"id": {"$in": list({r.get("material_id") for r in linked})}}, {"_id": 0}).to_list(500)}
    for r in linked:
        label = r.get("code") or r.get("material_id") or "Baris"
        sid, lid = str(r.get("marketing_sample_id") or ""), str(r.get("sample_line_id") or "")
        if not sid or not lid:
            errs.append(f"{label}: pilih baris kiriman sampel.")
            continue
        if sid not in cache:
            cache[sid] = await db.marketing_samples.find_one({"id": sid}, {"_id": 0})
        doc = cache[sid]
        if not doc:
            errs.append(f"{label}: kiriman sampel tidak ditemukan.")
            continue
        line = next((x for x in normalise(doc)["lines"] if x.get("id") == lid), None)
        if not line or not line.get("status_gudang"):
            errs.append(f"{label}: baris kiriman sampel ini tidak menunggu gudang.")
            continue
        if not produk_cocok(line, mats.get(r.get("material_id")) or {}):
            errs.append(f"{label}: produk berbeda dengan baris kiriman sampel ({line.get('sku') or line.get('product')}).")
            continue
        key = (sid, lid)
        per_baris.setdefault(key, [label, 0, line["sisa_keluar"]])
        per_baris[key][1] += _i(r.get("qty"))
    for label, qty, sisa in per_baris.values():
        if qty > sisa:
            errs.append(f"{label}: melebihi sisa baris kiriman sampel ({sisa} pcs).")
    if errs:
        raise HTTPException(400, "Belum ada yang dikeluarkan. " + " ".join(errs))


async def catat_keluar(db, sample_id: str, line_id: str, issue_doc: dict, user: Optional[dict]) -> None:
    """Setelah pengeluaran barang jadi tercatat: baris kiriman ditandai (riwayat per pengeluaran)."""
    doc = await db.marketing_samples.find_one({"id": sample_id}, {"_id": 0, "lines": 1})
    line = next((x for x in (doc or {}).get("lines") or [] if x.get("id") == line_id), None)
    if line is None:
        return
    riwayat = list(line.get("barang_keluar") or []) + [{
        "issue_id": issue_doc.get("id"), "issue_number": issue_doc.get("issue_number"),
        "qty": _i(issue_doc.get("qty")), "location_id": issue_doc.get("location_id"),
        "at": _now(), "by": (user or {}).get("name") or (user or {}).get("email") or ""}]
    await db.marketing_samples.update_one(
        {"id": sample_id, "lines.id": line_id},
        {"$set": {"lines.$.barang_keluar": riwayat, "updated_at": _now()}})


async def antrean_gudang(db, limit: int = 300) -> list:
    """Baris kiriman sampel yang masih menunggu dikeluarkan gudang (tertua dulu) + stok jual saat ini."""
    from core import catalog_stock as cs
    docs = await db.marketing_samples.find(
        {"lines.rencana_at": {"$exists": True}, "shipment_status": {"$ne": STATUS_BATAL}},
        {"_id": 0}).sort("date", 1).to_list(3000)
    rows = []
    for d in docs:
        n = normalise(d)
        for ln in n["lines"]:
            if not ln.get("status_gudang") or ln["sisa_keluar"] <= 0:
                continue
            rows.append({"sample_id": d.get("id"), "sample_code": n["sample_code"], "line_id": ln.get("id"),
                         "date": d.get("date"), "account_id": d.get("account_id"),
                         "account_name": d.get("account_name") or "",
                         "kreator": d.get("username") or d.get("creator_name") or "",
                         "product": ln.get("product") or "", "sku": ln.get("sku") or "",
                         "size": ln.get("size") or "", "color": ln.get("color") or "",
                         "quantity": _i(ln.get("quantity")), "qty_keluar": ln["qty_keluar"],
                         "sisa": ln["sisa_keluar"], "fg_material_id": ln.get("fg_material_id"),
                         "fg_code": ln.get("fg_code") or "", "po_number": ln.get("po_number") or "",
                         "status_gudang": ln["status_gudang"], "status_gudang_label": ln["status_gudang_label"],
                         "shipment_status": d.get("shipment_status") or ""})
    rows = rows[:max(1, min(1000, int(limit or 300)))]
    stok = await cs.sellable_map(db, [r["fg_material_id"] for r in rows if r.get("fg_material_id")])
    for r in rows:
        r["stok_tersedia"] = _f((stok.get(r.get("fg_material_id")) or {}).get("available"))
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# Biaya sampel per periode (keputusan 5) — dipakai `core.marketing_cycle.auto_spend`
# ══════════════════════════════════════════════════════════════════════════════
async def biaya_periode(db, account_id: str, date_from: str, date_to: str) -> dict:
    """Σ (HPP baris + ongkir) kiriman toko itu yang TANGGAL kirimnya di [date_from, date_to] (inklusif)."""
    start = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    from datetime import timedelta
    end = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    docs = await db.marketing_samples.find({
        "account_id": account_id, "shipment_status": {"$ne": STATUS_BATAL},
        "$or": [{"date": {"$gte": date_from, "$lte": date_to + "T23:59:59"}},
                {"date": {"$gte": start, "$lt": end}}],
    }, {"_id": 0}).to_list(20000)
    hpp = ongkir = 0.0
    for d in docs:
        hpp += sum(_f(x.get("total_hpp")) for x in baris_tersimpan(d))
        ongkir += _f(d.get("ongkir"))
    return {"amount": round(hpp + ongkir, 2), "hpp": round(hpp, 2), "ongkir": round(ongkir, 2), "docs": len(docs)}
