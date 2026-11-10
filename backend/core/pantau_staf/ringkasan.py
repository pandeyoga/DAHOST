"""Bacaan layar Monitoring Staf — SATU sumber angka untuk kartu, tabel, rincian, Asisten AI, dan pengingat.

Skor kepatuhan (keputusan owner 10 Nov 2026):
  kepatuhan % = bobot kewajiban SELESAI TEPAT WAKTU oleh pemegangnya sendiri ÷ bobot kewajiban yang SUDAH JATUH
  TEMPO di periode itu (batal & dimaafkan tidak dihitung; selesai oleh orang lain = tidak dinilai untuk pemegang, K8).
  Kewajiban yang masih menunggu dan belum jatuh tempo tidak dihitung. Pita nilai = pita KPI yang sudah ada
  (`routes.dewi_kpi_shared._grade`). Bulan pertama sejak aturan berlaku = "uji coba" (K6: pantauan tanpa sanksi).
  Skor hanya untuk owner & admin (K3); staf hanya melihat daftar kewajibannya sendiri (K4).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from core.pantau_staf import meter
from core.pantau_staf.katalog import ALUR_LABEL, ALUR_URUT, KATALOG_LIST
from core.pantau_staf.pemindai import FINAL, KEJADIAN, TERBUKA, akun_internal
from core.pantau_staf.waktu import Kalender, jam_wib, label_tenggat, muat_kalender, ts
from utils.waktu import now_utc, to_wib

TIDAK_DIPANTAU = {"superadmin", "owner"}
MASA_UJI_HARI = 30
BATAS_KEJADIAN = 50000


def nilai_huruf(skor: float | None) -> dict | None:
    if skor is None:
        return None
    from routes.dewi_kpi_shared import _grade
    g = _grade(skor)
    return {"huruf": g["grade"], "label": g["label"]}


def _hari(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def periode_bawaan(kini: datetime | None = None) -> tuple[str, str]:
    """Minggu berjalan (Senin s.d. hari ini, WIB)."""
    hari = to_wib(kini or now_utc()).date()
    return (hari - timedelta(days=hari.weekday())).isoformat(), hari.isoformat()


def _rentang(dari: str, sampai: str) -> tuple[datetime, datetime]:
    return jam_wib(_hari(dari), "00:00"), jam_wib(_hari(sampai), "23:59") + timedelta(seconds=59)


def _jatuh_tempo_di(k: dict, a: datetime, b: datetime, kini: datetime) -> bool:
    t = ts(k.get("tenggat"))
    return t is not None and a <= t <= b and t <= kini


def _selesai_di(k: dict, a: datetime, b: datetime) -> bool:
    t = ts(k.get("selesai_at"))
    return t is not None and a <= t <= b


def dinilai_tepat(k: dict) -> bool:
    return k.get("status") == "selesai" and bool(k.get("tepat")) and not k.get("oleh_orang_lain")


def skor_dari(kejadian: list, a: datetime, b: datetime, kini: datetime) -> dict:
    """Hitung kepatuhan satu kumpulan kejadian (milik satu pemegang) pada rentang [a, b]."""
    dinilai = [k for k in kejadian if k.get("status") not in ("batal", "dimaafkan") and _jatuh_tempo_di(k, a, b, kini)]
    total = sum(int(k.get("bobot") or 1) for k in dinilai)
    tepat = sum(int(k.get("bobot") or 1) for k in dinilai if dinilai_tepat(k))
    skor = round(100.0 * tepat / total, 1) if total else None
    return {
        "dinilai": len(dinilai), "tepat": sum(1 for k in dinilai if dinilai_tepat(k)),
        "selesai": sum(1 for k in kejadian if k.get("status") == "selesai" and _selesai_di(k, a, b)),
        "oleh_orang_lain": sum(1 for k in dinilai if k.get("oleh_orang_lain")),
        "terlewat": sum(1 for k in dinilai if k.get("status") == "terlewat"),
        "terlambat": sum(1 for k in kejadian if k.get("status") == "terlambat"),
        "menunggu": sum(1 for k in kejadian if k.get("status") == "menunggu"),
        "kepatuhan": skor, "nilai": nilai_huruf(skor),
    }


async def _kejadian_rentang(db, a: datetime, b: datetime) -> list:
    """Kejadian yang relevan untuk rentang: terbuka sekarang ATAU bertenggat/selesai di rentang."""
    q = {"$or": [{"status": {"$in": list(TERBUKA)}}, {"tenggat": {"$gte": a, "$lte": b}},
                 {"selesai_at": {"$gte": a, "$lte": b}}]}
    return await db[KEJADIAN].find(q, {"_id": 0}).to_list(BATAS_KEJADIAN)


async def masa_uji(db) -> dict:
    from core.pantau_staf.aturan import KOLEKSI as ATURAN
    rows = await db[ATURAN].find({"aktif": True}, {"_id": 0, "berlaku_sejak": 1}).to_list(500)
    awal = min((ts(r.get("berlaku_sejak")) for r in rows if r.get("berlaku_sejak")), default=None)
    if not awal:
        return {"aktif": True, "sampai": None}
    sampai = awal + timedelta(days=MASA_UJI_HARI)
    return {"aktif": now_utc() < sampai, "sampai": sampai}


async def _staf(db) -> list[dict]:
    return [u for u in await akun_internal(db) if (u.get("role") or "").lower() not in TIDAK_DIPANTAU]


def _hari_kerja(kal: Kalender, dari: str, sampai: str, kini: datetime) -> list[str]:
    akhir = min(_hari(sampai), to_wib(kini).date())
    cur, out = _hari(dari), []
    while cur <= akhir:
        if kal.kerja(cur):
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


async def per_staf(db, dari: str, sampai: str, *, kini: datetime | None = None) -> dict:
    kini = kini or now_utc()
    a, b = _rentang(dari, sampai)
    staf = await _staf(db)
    kal = await muat_kalender(db)
    hk = _hari_kerja(kal, dari, sampai, kini)
    semua = await _kejadian_rentang(db, a, b)
    milik: dict = {}
    for k in semua:
        for uid in k.get("pemegang_ids") or []:
            milik.setdefault(uid, []).append(k)
    akt = await meter.aktivitas(db, [u["id"] for u in staf], dari, sampai)
    akt_terakhir = await db[meter.KOLEKSI].find(
        {"user_id": {"$in": [u["id"] for u in staf]}}, {"_id": 0, "user_id": 1, "terakhir": 1, "tanggal": 1}
    ).sort("tanggal", -1).to_list(5000)
    terakhir = {}
    for r in akt_terakhir:
        terakhir.setdefault(r["user_id"], r.get("terakhir"))
    hari_aktif: dict = {}
    for r in akt:
        if r.get("tanggal") in hk:
            hari_aktif.setdefault(r["user_id"], set()).add(r["tanggal"])
    rows = []
    for u in staf:
        s = skor_dari(milik.get(u["id"], []), a, b, kini)
        rows.append({
            "user_id": u["id"], "nama": u.get("name") or u.get("email"), "peran": u.get("role"),
            "login_terakhir": u.get("last_login_at"), "aktif_terakhir": terakhir.get(u["id"]),
            "hari_aktif": len(hari_aktif.get(u["id"], set())), "hari_kerja": len(hk), **s,
        })
    rows.sort(key=lambda r: (-(r["terlambat"] or 0), r["kepatuhan"] if r["kepatuhan"] is not None else 101,
                             (r["nama"] or "").lower()))
    return {"dari": dari, "sampai": sampai, "hari_kerja": len(hk), "items": rows, "masa_uji": await masa_uji(db)}


async def kartu(db, dari: str, sampai: str, *, kini: datetime | None = None) -> dict:
    """Empat kartu angka di kepala layar — dari baris `per_staf` yang sama (tidak dihitung ulang)."""
    kini = kini or now_utc()
    data = await per_staf(db, dari, sampai, kini=kini)
    kal = await muat_kalender(db)
    hari_ini = to_wib(kini).date().isoformat()
    akt_hari_ini = {r["user_id"] for r in await meter.aktivitas(db, [r["user_id"] for r in data["items"]],
                                                              hari_ini, hari_ini)}
    # tidak aktif ≥ 3 hari kerja: aktivitas terakhir lebih tua dari 3 hari kerja (atau belum pernah)
    tiga = to_wib(kini).date()
    n = 0
    while n < 3:
        tiga -= timedelta(days=1)
        if kal.kerja(tiga):
            n += 1
    ambang = jam_wib(tiga, "00:00")
    tidak_aktif = [r for r in data["items"] if not r["aktif_terakhir"] or ts(r["aktif_terakhir"]) < ambang]
    dinilai = sum(r["dinilai"] for r in data["items"])
    tepat = sum(r["tepat"] for r in data["items"])
    return {
        "staf_total": len(data["items"]), "aktif_hari_ini": len(akt_hari_ini),
        "terlambat_sekarang": await db[KEJADIAN].count_documents({"status": "terlambat"}),
        "tepat_waktu": round(100.0 * tepat / dinilai, 1) if dinilai else None, "dinilai": dinilai,
        "tidak_aktif_3_hari": len(tidak_aktif), "masa_uji": data["masa_uji"],
    }


def _nama(users: dict, ids) -> list[str]:
    return [users[i].get("name") or users[i].get("email") or i for i in (ids or []) if i in users]


def bentuk_kejadian(k: dict, users: dict, kal: Kalender | None = None, kini: datetime | None = None) -> dict:
    kini = kini or now_utc()
    out = {key: k.get(key) for key in (
        "id", "aturan_id", "titik", "nama", "alur", "alur_label", "jenis", "objek_id", "nomor", "po_id", "periode",
        "keterangan", "link_module", "link_params", "pemegang_ids", "dialihkan_ke_cadangan", "mulai", "tenggat",
        "status", "tepat", "selesai_at", "pelaku_id", "pelaku_nama", "pelaku_vendor", "oleh_orang_lain",
        "tanpa_waktu", "dimaafkan", "alasan_tutup", "pengingat_terakhir")}
    out["pemegang"] = _nama(users, k.get("pemegang_ids"))
    if k.get("pelaku_id") in users:
        out["pelaku_nama"] = users[k["pelaku_id"]].get("name") or out.get("pelaku_nama")
    t = ts(k.get("tenggat"))
    if kal and t and k.get("status") == "terlambat":
        out["terlambat_hari_kerja"] = kal.hari_kerja_lewat(t, kini)
        out["terlambat_jam"] = round(max((kini - t).total_seconds(), 0) / 3600, 1)
    return out


def gabung_harian(items: list) -> list:
    """Kewajiban harian yang sama (langkah + toko/lokasi + pemegang) digabung jadi satu baris "N hari" —
    supaya 7 toko × 10 hari tidak menjadi 70 baris. Langkah alur (dokumen) tidak digabung."""
    out, grup = [], {}
    for it in items:
        if it.get("jenis") != "berkala" or not it.get("periode"):
            out.append(it)
            continue
        nomor = it.get("nomor") if it.get("nomor") != it.get("periode") else ""
        key = (it.get("aturan_id"), nomor, tuple(it.get("pemegang_ids") or []))
        g = grup.get(key)
        if g is None:
            g = grup[key] = {**it, "anggota": [], "gabungan": 0}
            out.append(g)
        g["anggota"].append({"id": it["id"], "periode": it["periode"], "status": it["status"],
                             "tenggat": it.get("tenggat"), "terlambat_hari_kerja": it.get("terlambat_hari_kerja")})
        g["gabungan"] += 1
    for g in grup.values():
        g["anggota"].sort(key=lambda a: a["periode"])
        g["periode_awal"], g["periode_akhir"] = g["anggota"][0]["periode"], g["anggota"][-1]["periode"]
        telat = [a for a in g["anggota"] if a["status"] == "terlambat"]
        g["status"] = "terlambat" if telat else g["status"]
        g["terlambat_hari_kerja"] = max((a.get("terlambat_hari_kerja") or 0 for a in telat), default=None)
        g["ids"] = [a["id"] for a in g["anggota"]]
    return out


async def macet(db, *, termasuk_menunggu: bool = False, alur: str | None = None, uid: str | None = None,
                kini: datetime | None = None, gabung: bool = True) -> dict:
    kini = kini or now_utc()
    q: dict = {"status": {"$in": ["terlambat", "menunggu"] if termasuk_menunggu else ["terlambat"]}}
    if alur:
        q["alur"] = alur
    if uid:
        q["pemegang_ids"] = uid
    rows = await db[KEJADIAN].find(q, {"_id": 0}).sort("tenggat", 1).to_list(5000)
    users = {u["id"]: u for u in await akun_internal(db)}
    kal = await muat_kalender(db)
    items = [bentuk_kejadian(k, users, kal, kini) for k in rows]
    # langkah sebelumnya pada rantai PO yang sama (siapa menyelesaikan, kapan)
    po_ids = list({k["po_id"] for k in rows if k.get("po_id")})
    if po_ids:
        sebelum: dict = {}
        for k in await db[KEJADIAN].find({"po_id": {"$in": po_ids}, "status": "selesai"},
                                         {"_id": 0}).to_list(20000):
            sebelum.setdefault(k["po_id"], []).append(k)
        urut = {t.id: t.urutan for t in KATALOG_LIST}
        for it in items:
            if not it.get("po_id"):
                continue
            kand = [k for k in sebelum.get(it["po_id"], [])
                    if urut.get(k.get("titik"), 0) < urut.get(it.get("titik"), 0)]
            if kand:
                k = max(kand, key=lambda x: urut.get(x.get("titik"), 0))
                it["sebelumnya"] = {"nama": k.get("nama"), "oleh": (users.get(k.get("pelaku_id")) or {}).get("name")
                                    or k.get("pelaku_nama"), "selesai_at": k.get("selesai_at")}
    jumlah = len(items)
    if gabung:
        items = gabung_harian(items)
    return {"items": items, "jumlah": jumlah, "baris": len(items)}


async def per_alur(db, dari: str, sampai: str, *, kini: datetime | None = None) -> dict:
    from core.pantau_staf.aturan import semua as semua_aturan
    kini = kini or now_utc()
    a, b = _rentang(dari, sampai)
    users = {u["id"]: u for u in await akun_internal(db)}
    aturan = {r["id"]: r for r in await semua_aturan(db)}
    kej = await _kejadian_rentang(db, a, b)
    per: dict = {}
    for k in kej:
        per.setdefault(k.get("aturan_id"), []).append(k)
    groups = []
    for alur in ALUR_URUT:
        langkah = []
        for t in sorted([t for t in KATALOG_LIST if t.alur == alur], key=lambda t: t.urutan):
            r = aturan.get(t.id) or {}
            ks = per.get(t.id, [])
            terbuka = [k for k in ks if k.get("status") in TERBUKA]
            durasi = [max((ts(k["selesai_at"]) - ts(k["mulai"])).total_seconds() / 3600, 0.0) for k in ks
                      if k.get("status") == "selesai" and k.get("selesai_at") and k.get("mulai")
                      and a <= ts(k["selesai_at"]) <= b and t.id != "aktif_harian"]
            p = r.get("pemegang") or {}
            if p.get("jenis") == "akun":
                peg = _nama(users, p.get("akun_ids"))
            elif p.get("jenis") == "peran":
                peg = [f"peran {x}" for x in p.get("peran") or []]
            else:
                peg = [f"dari data: {(t.pemegang or {}).get('label') or 'dokumen'}"]
            langkah.append({
                "aturan_id": t.id, "nama": t.nama, "jenis": t.jenis, "aktif": bool(r.get("aktif")),
                "pemegang": peg, "tenggat_label": label_tenggat(r.get("tenggat") or t.tenggat),
                "menunggu": sum(1 for k in terbuka if k.get("status") == "menunggu"),
                "terlambat": sum(1 for k in terbuka if k.get("status") == "terlambat"),
                "terlama_sejak": min((k.get("mulai") for k in terbuka if k.get("mulai")), default=None),
                "selesai": len(durasi),
                "rata_jam": round(sum(durasi) / len(durasi), 1) if durasi else None,
            })
        groups.append({"alur": alur, "label": ALUR_LABEL[alur], "langkah": langkah})
    return {"dari": dari, "sampai": sampai, "alur": groups}


async def rincian_staf(db, uid: str, dari: str, sampai: str, *, kini: datetime | None = None) -> dict | None:
    from data.module_catalog import MODULE_BY_ID, PORTAL_LABELS
    kini = kini or now_utc()
    a, b = _rentang(dari, sampai)
    users = {u["id"]: u for u in await akun_internal(db)}
    u = users.get(uid) or await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
                                                                "last_login_at": 1})
    if not u:
        return None
    kal = await muat_kalender(db)
    kej = [k for k in await _kejadian_rentang(db, a, b) if uid in (k.get("pemegang_ids") or [])]
    terbuka = [bentuk_kejadian(k, users, kal, kini) for k in kej if k.get("status") in TERBUKA]
    riwayat = [bentuk_kejadian(k, users, kal, kini) for k in kej
               if k.get("status") in FINAL and (_jatuh_tempo_di(k, a, b, kini) or _selesai_di(k, a, b))]
    terbuka.sort(key=lambda k: str(k.get("tenggat") or ""))
    riwayat.sort(key=lambda k: str(k.get("tenggat") or ""), reverse=True)
    # dikerjakan untuk orang lain (K8): pelaku = akun ini, pemegang orang lain
    bantu = await db[KEJADIAN].count_documents({"pelaku_id": uid, "oleh_orang_lain": True,
                                                "selesai_at": {"$gte": a, "$lte": b}})
    hari = []
    for r in await meter.aktivitas(db, [uid], dari, sampai):
        modul = []
        for mid, aksi in (r.get("modul") or {}).items():
            m = MODULE_BY_ID.get(mid) or {}
            modul.append({"id": mid, "label": m.get("label") or ("Lainnya" if mid == "_lain" else mid),
                          "portal": PORTAL_LABELS.get(m.get("portal"), "") if m else "",
                          "lihat": int(aksi.get("view") or 0),
                          "simpan": int(sum(int(aksi.get(x) or 0) for x in ("create", "edit", "delete"))),
                          "setujui": int(aksi.get("approve") or 0), "unduh": int(aksi.get("export") or 0)})
        modul.sort(key=lambda m: (-(m["simpan"] + m["setujui"]), -m["lihat"]))
        hari.append({"tanggal": r["tanggal"], "pertama": r.get("pertama"), "terakhir": r.get("terakhir"),
                     "jumlah": r.get("jumlah"), "modul": modul})
    hari.sort(key=lambda h: h["tanggal"], reverse=True)
    return {"user": {"id": u["id"], "nama": u.get("name") or u.get("email"), "peran": u.get("role"),
                     "login_terakhir": u.get("last_login_at")},
            "skor": skor_dari(kej, a, b, kini), "terbuka": terbuka, "riwayat": riwayat[:300],
            "membantu_orang_lain": bantu, "aktivitas": hari, "masa_uji": await masa_uji(db)}


async def rantai(db, kejadian_id: str) -> dict | None:
    k = await db[KEJADIAN].find_one({"id": kejadian_id}, {"_id": 0})
    if not k:
        return None
    users = {u["id"]: u for u in await akun_internal(db)}
    kal = await muat_kalender(db)
    if k.get("po_id"):
        rows = await db[KEJADIAN].find({"po_id": k["po_id"]}, {"_id": 0}).to_list(500)
    else:
        rows = [k]
    urut = {t.id: t.urutan for t in KATALOG_LIST}
    rows.sort(key=lambda x: (urut.get(x.get("titik"), 999), str(x.get("mulai") or "")))
    return {"kejadian": bentuk_kejadian(k, users, kal), "rantai": [bentuk_kejadian(x, users, kal) for x in rows]}


async def saya(db, uid: str, *, kini: datetime | None = None) -> dict:
    """Portal Saya: daftar kewajiban akun sendiri (tanpa skor — K4)."""
    kini = kini or now_utc()
    users = {u["id"]: u for u in await akun_internal(db)}
    kal = await muat_kalender(db)
    rows = await db[KEJADIAN].find({"pemegang_ids": uid, "status": {"$in": list(TERBUKA)}},
                                   {"_id": 0}).sort("tenggat", 1).to_list(500)
    items = [bentuk_kejadian(k, users, kal, kini) for k in rows]
    hari_ini = to_wib(kini).date()
    terlambat = sum(1 for i in items if i["status"] == "terlambat")
    jatuh = sum(1 for i in items if i["status"] == "menunggu" and i.get("tenggat")
                and to_wib(ts(i["tenggat"])).date() <= hari_ini)
    items = gabung_harian(items)                 # kewajiban harian yang sama → satu baris "N hari"
    for it in items:
        it.pop("pemegang_ids", None)
    return {"items": items, "terlambat": terlambat, "hari_ini": jatuh}


def katalog_publik() -> list[dict]:
    return [{"id": t.id, "nama": t.nama, "alur": t.alur, "alur_label": ALUR_LABEL[t.alur], "urutan": t.urutan,
             "jenis": t.jenis, "pemicu": t.pemicu, "bukti": t.bukti, "pemegang_bawaan": t.pemegang,
             "tenggat_bawaan": t.tenggat, "saringan": list(t.saringan), "tanpa_waktu": t.tanpa_waktu,
             "link_module": t.link_module} for t in KATALOG_LIST]
