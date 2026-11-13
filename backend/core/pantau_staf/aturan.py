"""Aturan kewajiban (`kewajiban_aturan`) — konfigurasi owner di layar Aturan Kewajiban.

Satu aturan per titik aksi katalog (id aturan = id titik). Keputusan owner 10 Nov 2026:
  * K2 — pemegang awal TIDAK diisi dari draf: aturan yang pemegangnya akun/peran dikirim kosong & NONAKTIF sampai
    owner mengisi pemegangnya. Aturan yang pemegangnya DARI DATA (penyetuju, PIC toko, pembuat dokumen, akun itu
    sendiri) aktif sejak pertama dipasang.
  * K3 — hanya owner & admin yang mengubah (dijaga di rute).
`berlaku_sejak` = saat aturan pertama aktif; kewajiban sebelum itu tidak dibuat (tidak ada hukuman berlaku surut).
"""
from __future__ import annotations

from datetime import datetime

from core.pantau_staf.katalog import KATALOG, KATALOG_LIST, TitikAksi
from utils.waktu import now_utc

KOLEKSI = "kewajiban_aturan"
JENIS_PEMEGANG = ("akun", "peran", "data")
JENIS_TENGGAT = ("hari_kerja", "jam", "jam_tetap", "dokumen")
BATAS_BOBOT = (1, 5)


class AturanTidakSah(ValueError):
    """Isian aturan tidak sah — pesannya untuk layar (bahasa Indonesia)."""


def bawaan(t: TitikAksi, kini: datetime | None = None) -> dict:
    kini = kini or now_utc()
    dari_data = (t.pemegang or {}).get("jenis") == "data"
    return {
        "id": t.id, "titik": t.id, "aktif": dari_data,
        "pemegang": {"jenis": "data" if dari_data else "akun", "akun_ids": [], "peran": []},
        "cadangan_ids": [], "tenggat": dict(t.tenggat), "bobot": 1, "saringan": {}, "dikecualikan_ids": [],
        "berlaku_sejak": kini if dari_data else None,
        "dibuat_at": kini, "diubah_at": kini, "diubah_oleh": None, "diubah_oleh_nama": None,
    }


async def semua(db, *, kini: datetime | None = None, pasang: bool = True) -> list[dict]:
    """Semua aturan untuk titik yang ada di katalog; aturan yang belum tersimpan dipasang dari bawaan."""
    rows = await db[KOLEKSI].find({}, {"_id": 0}).to_list(1000)
    ada = {r.get("id") for r in rows}
    if pasang:
        for t in KATALOG_LIST:
            if t.id in ada:
                continue
            doc = bawaan(t, kini)
            await db[KOLEKSI].update_one({"id": t.id}, {"$setOnInsert": doc}, upsert=True)
            rows.append(doc)
    return [r for r in rows if r.get("titik") in KATALOG]


async def satu(db, aturan_id: str) -> dict | None:
    doc = await db[KOLEKSI].find_one({"id": aturan_id}, {"_id": 0})
    if doc:
        return doc
    t = KATALOG.get(aturan_id)
    return bawaan(t) if t else None


def _daftar_id(v, nama: str) -> list:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise AturanTidakSah(f"{nama} harus berupa daftar akun.")
    return list(dict.fromkeys(x.strip() for x in v))


def periksa_ubahan(lama: dict, body: dict, *, users: dict, peran_ada: set) -> dict:
    """Ubahan `$set` yang sah dari isian layar. `users` = {id: akun aktif}, `peran_ada` = kode peran yang ada."""
    t = KATALOG.get(lama.get("titik"))
    if t is None:
        raise AturanTidakSah("Langkah aturan ini tidak dikenal.")
    if not isinstance(body, dict) or not body:
        raise AturanTidakSah("Tidak ada perubahan.")
    upd: dict = {}
    if "pemegang" in body:
        p = body.get("pemegang") or {}
        jenis = p.get("jenis")
        if jenis not in JENIS_PEMEGANG:
            raise AturanTidakSah("Penanggung jawab harus akun tertentu, peran, atau dari data dokumen.")
        if jenis == "data" and (t.pemegang or {}).get("jenis") != "data":
            raise AturanTidakSah("Langkah ini tidak menyimpan penanggung jawab di dokumennya — pilih akun atau peran.")
        akun_ids = _daftar_id(p.get("akun_ids"), "Pemegang")
        tak_dikenal = [i for i in akun_ids if i not in users]
        if tak_dikenal:
            raise AturanTidakSah("Ada akun penanggung jawab yang tidak ditemukan atau sudah nonaktif.")
        peran = _daftar_id(p.get("peran"), "Peran")
        if any(r not in peran_ada for r in peran):
            raise AturanTidakSah("Ada peran yang tidak ditemukan.")
        upd["pemegang"] = {"jenis": jenis, "akun_ids": akun_ids if jenis == "akun" else [],
                           "peran": peran if jenis == "peran" else []}
    if "cadangan_ids" in body:
        cad = _daftar_id(body.get("cadangan_ids"), "Cadangan")
        if any(i not in users for i in cad):
            raise AturanTidakSah("Ada akun cadangan yang tidak ditemukan atau sudah nonaktif.")
        upd["cadangan_ids"] = cad
    if "dikecualikan_ids" in body:
        upd["dikecualikan_ids"] = _daftar_id(body.get("dikecualikan_ids"), "Pengecualian")
    if "tenggat" in body:
        tg = body.get("tenggat") or {}
        jenis = tg.get("jenis")
        if jenis not in JENIS_TENGGAT:
            raise AturanTidakSah("Bentuk batas waktu tidak dikenal.")
        if jenis == "dokumen" and t.tenggat.get("jenis") != "dokumen":
            raise AturanTidakSah("Langkah ini tidak punya tanggal jatuh tempo di dokumennya.")
        if jenis == "jam_tetap" and t.jenis != "berkala":
            raise AturanTidakSah("Batas jam tetap hanya untuk kewajiban harian/berkala.")
        if jenis in ("hari_kerja", "jam"):
            try:
                nilai = float(tg.get("nilai"))
            except (TypeError, ValueError):
                raise AturanTidakSah("Isi lama batas waktu dengan angka.")
            batas = (1, 30) if jenis == "hari_kerja" else (1, 240)
            if not (batas[0] <= nilai <= batas[1]):
                raise AturanTidakSah(f"Batas waktu harus {batas[0]}–{batas[1]} "
                                     f"{'hari kerja' if jenis == 'hari_kerja' else 'jam'}.")
            upd["tenggat"] = {"jenis": jenis, "nilai": int(nilai) if jenis == "hari_kerja" else nilai}
        elif jenis == "jam_tetap":
            jam = str(tg.get("jam") or "")
            hh, _, mm = jam.partition(":")
            if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise AturanTidakSah("Jam batas harus berbentuk JJ:MM, mis. 10:00.")
            try:
                hari = int(tg.get("hari") or 0)
            except (TypeError, ValueError):
                raise AturanTidakSah("Hari batas harus angka.")
            if not (0 <= hari <= 7):
                raise AturanTidakSah("Hari batas 0–7 hari kerja sesudah tanggalnya.")
            upd["tenggat"] = {"jenis": jenis, "hari": hari, "jam": f"{int(hh):02d}:{int(mm):02d}"}
        else:
            upd["tenggat"] = {"jenis": "dokumen"}
    if "bobot" in body:
        try:
            bobot = int(body.get("bobot"))
        except (TypeError, ValueError):
            raise AturanTidakSah("Bobot harus angka 1–5.")
        if not (BATAS_BOBOT[0] <= bobot <= BATAS_BOBOT[1]):
            raise AturanTidakSah("Bobot harus angka 1–5.")
        upd["bobot"] = bobot
    if "saringan" in body:
        s = body.get("saringan") or {}
        if not isinstance(s, dict):
            raise AturanTidakSah("Saringan tidak sah.")
        bersih = {}
        for k, v in s.items():
            if k not in t.saringan:
                raise AturanTidakSah("Langkah ini tidak bisa disaring seperti itu.")
            if k == "business_type":
                if v not in (None, "", "internal", "maklon"):
                    raise AturanTidakSah("Jenis PO harus internal atau maklon.")
                if v:
                    bersih[k] = v
            elif v:
                bersih[k] = _daftar_id(v if isinstance(v, list) else [v], "Saringan")
        upd["saringan"] = bersih
    if "aktif" in body:
        if not isinstance(body.get("aktif"), bool):
            raise AturanTidakSah("Isian aktif harus ya/tidak.")
        upd["aktif"] = body["aktif"]
    # aturan aktif wajib punya pemegang
    akhir = {**lama, **upd}
    if akhir.get("aktif"):
        p = akhir.get("pemegang") or {}
        if p.get("jenis") == "akun" and not p.get("akun_ids"):
            raise AturanTidakSah("Pilih minimal satu akun penanggung jawab sebelum mengaktifkan aturan ini.")
        if p.get("jenis") == "peran" and not p.get("peran"):
            raise AturanTidakSah("Pilih minimal satu peran penanggung jawab sebelum mengaktifkan aturan ini.")
    if not upd:
        raise AturanTidakSah("Tidak ada perubahan.")
    return upd


async def ubah(db, aturan_id: str, body: dict, *, oleh: dict, users: dict, peran_ada: set) -> dict:
    lama = await satu(db, aturan_id)
    if lama is None:
        raise LookupError("Aturan tidak ditemukan.")
    upd = periksa_ubahan(lama, body, users=users, peran_ada=peran_ada)
    kini = now_utc()
    if upd.get("aktif") and not lama.get("berlaku_sejak"):
        upd["berlaku_sejak"] = kini
    upd.update({"diubah_at": kini, "diubah_oleh": oleh.get("id"), "diubah_oleh_nama": oleh.get("name")})
    base = {k: v for k, v in bawaan(KATALOG[lama["titik"]], kini).items() if k not in upd}
    await db[KOLEKSI].update_one({"id": aturan_id}, {"$set": upd, "$setOnInsert": base}, upsert=True)
    return await satu(db, aturan_id)


def berlaku_untuk(aturan: dict, user: dict) -> str | None:
    """Mengapa aturan ini menunjuk akun `user` — None bila tidak. Untuk tampilan "Per akun"."""
    uid = user.get("id")
    if uid in (aturan.get("dikecualikan_ids") or []):
        return None
    p = aturan.get("pemegang") or {}
    if p.get("jenis") == "akun" and uid in (p.get("akun_ids") or []):
        return "langsung ke akun ini"
    if p.get("jenis") == "peran" and (user.get("role") or "") in (p.get("peran") or []):
        return "lewat peran"
    if uid in (aturan.get("cadangan_ids") or []):
        return "sebagai cadangan"
    if p.get("jenis") == "data":
        t = KATALOG.get(aturan.get("titik"))
        return f"bila menjadi {(t.pemegang or {}).get('label') or 'penanggung jawab di dokumen'}"
    return None
