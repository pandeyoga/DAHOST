"""Alat TINDAKAN Pemasaran (Asisten AI Tahap B, agen pemasaran — 8 Nov 2026). Kontrak D.

Lima tindakan berisiko rendah, semuanya lewat kartu konfirmasi (tidak ada yang tertulis sebelum
pengguna menekan Setujui):

* ``pasang_target_toko``         — target omzet/pesanan bulanan beberapa toko (= layar Target & Budget,
  ``POST /api/marketing/targets``); dibalikkan = nilai lama dipulihkan, target baru dihapus.
* ``rencana_anggaran_marketing`` — rencana anggaran per kategori (``PUT /api/marketing/budget``);
  dibalikkan = rencana lama dipulihkan (yang sebelumnya belum ada → Rp 0).
* ``buat_tugas_marketing``       — tugas marketing ber-PIC (``POST /api/marketing/tasks``); dibalikkan =
  tugas dibatalkan (status "cancelled", sama dengan hapus di layar).
* ``jadwalkan_konten``           — kalender konten (``POST /api/marketing/content-calendar``);
  dibalikkan = konten dibatalkan.
* ``jadwalkan_live``             — jadwal sesi live berstatus "scheduled"
  (``POST /api/marketing/live/sessions``); dibalikkan = sesi dibatalkan.

Aturan yang dipegang di sini (desain §4, Kontrak D):
  * ``siapkan`` HANYA MEMBACA (``ctx.api`` GET) lalu mengembalikan Rencana; penolakan = ``AlatError``
    berpesan ramah yang dikirim balik ke model;
  * SEMUA tulisan lewat ``ctx.api`` dengan token pengguna (jalur, izin, lingkup toko, CV, dan kunci periode
    yang SAMA dengan layar); tidak ada tulis langsung ke DB;
  * banyak tulisan dalam satu tindakan → bila satu gagal, yang sudah tertulis dikembalikan dulu
    (tidak ada setengah jadi), baru galatnya dilempar;
  * pembalikan menolak (409) bila datanya sudah diubah orang lain sesudah tindakan — perubahan orang lain
    tidak boleh tertimpa diam-diam.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core import ukuran_penjualan as U
from core.asisten_ai.alat import _bantu_marketing as B
from core.asisten_ai.alat.skenario_target import jarak_bulan
from core.asisten_ai.alat_base import AlatError, tindakan  # Kontrak D

WIB = timezone(timedelta(hours=7))
BULAN = {"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$"}
TANGGAL = {"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"}
JAM = {"type": "string", "pattern": r"^([01]\d|2[0-3]):[0-5]\d$"}
ALASAN = {"type": "string", "maxLength": 300,
          "description": "Alasan singkat dari percakapan (masuk jejak perubahan bersama tanda 'Asisten AI')."}
BATAS_RENCANA = 8_000
CV_LABEL = {"DA": "DA", "SMU": "Sukma", "ALL": "Gabungan"}


# ══════════════════════════════════════════════════════════════════════════════
# Pembantu bersama
# ══════════════════════════════════════════════════════════════════════════════
def rp(v: Any) -> str:
    if v is None:
        return "—"
    return "Rp " + f"{int(round(float(v))):,}".replace(",", ".")


def angka(v: Any) -> str:
    return f"{int(round(float(v or 0))):,}".replace(",", ".")


def label_tanggal(iso: str) -> str:
    return f"{int(iso[8:10])} {U.label_bulan(iso[:7])}"


def _hdr(ctx) -> dict:
    """Tanda jalur Asisten AI di setiap tulisan (endpoint yang punya jejak sendiri bisa mencatatnya)."""
    h = {"X-Via": "asisten-ai"}
    tid = getattr(ctx, "tindakan_id", None)
    if tid:
        h["X-Asisten-Tindakan"] = str(tid)
    return h


async def _tulis(ctx, method: str, path: str, *, params: Optional[dict] = None, json: Any = None):
    return await ctx.api(method, path, params=params, json=json, headers=_hdr(ctx))


def _jejak(*bagian: Optional[str]) -> str:
    isi = " · ".join(b.strip() for b in bagian if b and str(b).strip())
    return ("Asisten AI" + (f" · {isi}" if isi else ""))[:500]


def _tanggal_sah(iso: str, nama: str) -> date:
    try:
        return date.fromisoformat(iso)
    except (TypeError, ValueError):
        raise AlatError(400, f"{nama} '{iso}' bukan tanggal yang sah (format TTTT-BB-HH).") from None


def _cek_bulan(ctx, ym: str, apa: str) -> None:
    d = jarak_bulan(B.bulan_ini(ctx), ym)
    if d < 0:
        raise AlatError(400, f"{apa} hanya bisa untuk bulan berjalan atau sesudahnya; {U.label_bulan(ym)} sudah lewat.")
    if d > 12:
        raise AlatError(400, f"{apa} paling jauh 12 bulan dari sekarang.")


def _cek_tanggal_depan(ctx, iso: str, nama: str) -> date:
    d = _tanggal_sah(iso, nama)
    if d < B.hari_ini(ctx):
        raise AlatError(400, f"{nama} {label_tanggal(iso)} sudah lewat; pilih hari ini atau sesudahnya.")
    if d > B.hari_ini(ctx) + timedelta(days=366):
        raise AlatError(400, f"{nama} paling jauh setahun dari hari ini.")
    return d


def _cek_cv_tulis(ctx) -> None:
    """Gabungan = hanya untuk melihat (aturan dua CV, Tahap 8): tulisan tanpa CV yang jelas ditolak sejak kartu."""
    if str(getattr(ctx, "cv", "") or "").upper() == "ALL":
        raise AlatError(400, "Pilih CV DA atau Sukma dulu (pilihan CV di atas chat); mode Gabungan hanya untuk "
                             "melihat, tidak untuk mengubah data.")


def _cek_penulis_target(ctx, apa: str) -> None:
    """Pra-cek ramah (aturan yang SAMA dengan endpoint; endpoint tetap penjaga sebenarnya)."""
    from core.marketing_account_scope import can_write_target
    if not can_write_target(ctx.user):
        raise AlatError(403, f"Akun Anda tidak boleh menetapkan {apa}: itu keputusan SPV/Manager Marketing atau "
                             "owner. Asisten AI hanya bisa melakukan apa yang bisa Anda lakukan di layar.")


async def _toko_cv(ctx, bulan: Optional[str] = None) -> Dict[str, dict]:
    """Toko yang boleh dipakai pemakai ini pada CV terpilih → {id: baris analitik target bulan itu}.

    Lewat endpoint analitik (lingkup toko + CV = sama dengan layar), sekaligus memberi nama toko, target
    dan omzet bulan itu."""
    bulan = bulan or B.bulan_ini(ctx)
    data = await ctx.api("GET", "/api/marketing/analitik/target",
                         params={"dari_bulan": bulan, "sampai_bulan": bulan})
    return {r["toko_id"]: r for r in (data or {}).get("baris") or []
            if r.get("toko_id") and r.get("bulan", bulan) == bulan}


def _tolak_toko_luar(ctx, ids: Sequence[str], terlihat: Dict[str, dict]) -> None:
    luar = [i for i in dict.fromkeys(ids) if i not in terlihat]
    if luar:
        raise AlatError(403, f"Toko berikut tidak bisa dipakai dengan akun ini pada pilihan CV "
                             f"{CV_LABEL.get(ctx.cv, ctx.cv)}: {', '.join(luar[:8])}. Pastikan toko itu dipegang "
                             "Anda dan pilihan CV di atas chat sudah benar.")


async def _periode_terkunci(ctx, ids: Sequence[str], bulan: str) -> Tuple[List[str], bool]:
    """(toko yang periodenya DITUTUP, status terbaca?) — dari daftar kunci periode Marketing."""
    try:
        data = await ctx.api("GET", "/api/marketing/periods/locks")
    except AlatError:
        return [], False
    kunci = {(r.get("account_id"), r.get("period")) for r in (data or {}).get("locks") or [] if r.get("locked")}
    return [i for i in ids if (i, bulan) in kunci], True


def _batasi(rencana: dict) -> dict:
    """Rencana ≤ 8.000 karakter: kurangi isian 'ubah', lalu tolak (kartu terlalu panjang)."""
    def _n():
        return len(json.dumps(rencana, ensure_ascii=False, default=str))
    while _n() > BATAS_RENCANA and len(rencana.get("ubah") or []) > 4:
        rencana["ubah"] = rencana["ubah"][: max(4, len(rencana["ubah"]) // 2)]
    if _n() > BATAS_RENCANA:
        raise AlatError(400, "Perubahan ini terlalu banyak untuk satu kartu konfirmasi. Bagi menjadi beberapa "
                             "tindakan yang lebih kecil (mis. per kelompok toko).")
    return rencana


def _gagal_sebagian(apa: str, e: AlatError, gagal_balik: List[str]) -> AlatError:
    if gagal_balik:
        return AlatError(e.status if e.status >= 400 else 502,
                         f"{apa} gagal: {e.pesan} Sebagian yang sudah tersimpan GAGAL dikembalikan "
                         f"({'; '.join(gagal_balik[:5])}). Periksa layarnya dan rapikan manual.")
    return AlatError(e.status, f"{apa} gagal: {e.pesan} Yang sempat tersimpan sudah dikembalikan; tidak ada "
                               "yang berubah.")


async def _pengguna_toko(ctx, cache: dict) -> List[dict]:
    if "pengguna" not in cache:
        cache["pengguna"] = list(await ctx.api("GET", "/api/auth/users",
                                               params={"portal": "toko", "status": "active", "limit": 500}) or [])
    return cache["pengguna"]


def _cocokkan(daftar: List[dict], nilai: str, kunci_nama: str = "name") -> List[dict]:
    v = (nilai or "").strip().lower()
    if not v:
        return []
    persis = [u for u in daftar if u.get("id") == nilai or str(u.get(kunci_nama) or "").strip().lower() == v
              or str(u.get("email") or "").strip().lower() == v]
    if persis:
        return persis
    return [u for u in daftar if v in str(u.get(kunci_nama) or "").lower()]


async def _akun(ctx, toko_id: str, cache: dict) -> dict:
    akun = cache.setdefault("akun", {})
    if toko_id not in akun:
        akun[toko_id] = await ctx.api("GET", f"/api/marketing/accounts/{toko_id}") or {}
    return akun[toko_id]


# ══════════════════════════════════════════════════════════════════════════════
# 1. TARGET TOKO
# ══════════════════════════════════════════════════════════════════════════════
async def _target_bulan(ctx, bulan: str) -> Dict[str, dict]:
    rows = await ctx.api("GET", "/api/marketing/targets",
                         params={"year": int(bulan[:4]), "month": int(bulan[5:7])}) or []
    return {r["account_id"]: r for r in rows if isinstance(r, dict) and r.get("account_id")}


def _teks_target(rev: float, ords: int, tampil_pesanan: bool) -> str:
    return rp(rev) + (f" · {angka(ords)} pesanan" if tampil_pesanan else "")


def _isi_target(doc: Optional[dict], toko: dict) -> Tuple[float, int]:
    rev = float(toko["target_omzet"])
    ords = int(toko["target_pesanan"]) if toko.get("target_pesanan") is not None else int((doc or {}).get("orders_target") or 0)
    return rev, ords


def _body_target(account_id: str, bulan: str, rev: float, ords: int, doc: Optional[dict], reason: str) -> dict:
    hs = (doc or {}).get("health_score_target")
    return {"account_id": account_id, "year": int(bulan[:4]), "month": int(bulan[5:7]),
            "revenue_target": float(rev), "orders_target": int(ords),
            "health_score_target": int(hs) if hs is not None else 80,
            "notes": (doc or {}).get("notes"), "reason": reason}


async def _balikkan_target(ctx, bulan: str, entri: List[dict], alasan: str, *, periksa: bool) -> List[str]:
    """Pulihkan target lama / hapus target baru, urutan terbalik. Return daftar kegagalan."""
    lewati = set()
    if periksa:
        kini = await _target_bulan(ctx, bulan)
        beda = []
        for e in entri:
            d = kini.get(e["toko_id"])
            if d is None:
                if e["dibuat"]:
                    lewati.add(e["toko_id"])          # sudah tidak ada: tidak perlu dihapus lagi
                else:
                    beda.append(f"{e.get('toko') or e['toko_id']} (targetnya sudah dihapus)")
                continue
            s = e["sesudah"]
            if float(d.get("revenue_target") or 0) != float(s["revenue_target"]) or \
                    int(d.get("orders_target") or 0) != int(s["orders_target"]):
                beda.append(f"{e.get('toko') or e['toko_id']} (sekarang {rp(d.get('revenue_target'))})")
        if beda:
            raise AlatError(409, "Target toko berikut sudah diubah lagi sesudah tindakan ini: " + ", ".join(beda[:8])
                            + ". Pembalikan dibatalkan supaya perubahan itu tidak tertimpa; ubah manual di layar "
                              "Target bila perlu.")
    gagal = []
    for e in reversed(entri):
        if e["toko_id"] in lewati:
            continue
        try:
            if e["dibuat"]:
                if e.get("target_id"):
                    await _tulis(ctx, "DELETE", f"/api/marketing/targets/{e['target_id']}", params={"reason": alasan})
            else:
                s = e["sebelum"] or {}
                await _tulis(ctx, "POST", "/api/marketing/targets", json=_body_target(
                    e["toko_id"], bulan, float(s.get("revenue_target") or 0), int(s.get("orders_target") or 0),
                    s, alasan))
        except AlatError as x:
            gagal.append(f"{e.get('toko') or e['toko_id']}: {x.pesan}")
    return gagal


@tindakan(
    name="pasang_target_toko",
    label="Memasang target toko",
    description=(
        "MENYIAPKAN pemasangan target bulanan (omzet Rp dan, bila disebut, pesanan) untuk satu atau beberapa "
        "toko online — sama dengan mengisi layar Target & Budget Marketing. Alat ini hanya menyiapkan KARTU "
        "KONFIRMASI (target lama → baru per toko); tidak ada yang tersimpan sebelum pengguna menekan Setujui.\n"
        "Aturan: hanya SPV/Manager Marketing atau owner; hanya toko yang dipegang pengguna pada CV terpilih; "
        "bulan berjalan s.d. 12 bulan ke depan; periode yang sudah ditutup ditolak. Target pesanan yang tidak "
        "disebut, skor kesehatan, dan catatan target tetap seperti sekarang. Tercatat di Jejak Perubahan dengan "
        "tanda 'Asisten AI'. Bisa dibalikkan: target lama dipulihkan, target yang baru dibuat dihapus.\n"
        "Pakai SETELAH pengguna memilih angka (mis. dari skenario_target: isian_pasang_target). Satu panggilan "
        "untuk satu kumpulan perubahan; jangan mengaku sudah terpasang sebelum hasilnya 'Disetujui dan "
        "dijalankan'."),
    input_schema={
        "type": "object",
        "properties": {
            "bulan": {**BULAN, "description": "Bulan target (TTTT-BB)."},
            "toko": {"type": "array", "minItems": 1, "maxItems": 30, "description": "Target per toko.",
                     "items": {"type": "object", "properties": {
                         "toko_id": {"type": "string", "minLength": 1, "description": "Id toko."},
                         "target_omzet": {"type": "number", "minimum": 0, "maximum": 1e12,
                                          "description": "Target omzet bulan itu (Rp)."},
                         "target_pesanan": {"type": "integer", "minimum": 0, "maximum": 10_000_000,
                                            "description": "Target pesanan (opsional; kosong = tetap)."}},
                         "required": ["toko_id", "target_omzet"], "additionalProperties": False}},
            "skenario": {"type": "string", "enum": ["konservatif", "realistis", "agresif", "lainnya"],
                         "description": "Asal angka (untuk kartu & jejak)."},
            "alasan": ALASAN,
        },
        "required": ["bulan", "toko"],
        "additionalProperties": False,
    },
    domain="penjualan",
    risiko="rendah",
    menu="marketing-targets",
)
class PasangTargetToko:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _cek_cv_tulis(ctx)
        bulan, toko = args["bulan"], args["toko"]
        label = U.label_bulan(bulan)
        _cek_bulan(ctx, bulan, "Target")
        ids = [t["toko_id"] for t in toko]
        if len(set(ids)) != len(ids):
            raise AlatError(400, "Ada toko yang disebut dua kali; satukan dulu angkanya.")
        _cek_penulis_target(ctx, "target toko")
        terlihat = await _toko_cv(ctx, bulan)
        _tolak_toko_luar(ctx, ids, terlihat)
        lama = await _target_bulan(ctx, bulan)
        terkunci, terbaca = await _periode_terkunci(ctx, ids, bulan)
        if terkunci:
            raise AlatError(423, f"Periode {label} sudah DITUTUP untuk toko: "
                                 f"{', '.join(terlihat[i].get('toko') or i for i in terkunci)}. Minta SPV Marketing "
                                 "membuka periodenya di Siklus Marketing, atau keluarkan toko itu dari daftar.")
        perubahan, peringatan, ubah = [], [], []
        tot_lama = tot_baru = 0.0
        ada_lama = berubah = 0
        for i, t in enumerate(toko):
            row = terlihat[t["toko_id"]]
            nama = row.get("toko") or t["toko_id"]
            doc = lama.get(t["toko_id"])
            rev, ords = _isi_target(doc, t)
            pesanan_tampil = bool(ords) or t.get("target_pesanan") is not None
            if doc is not None:
                ada_lama += 1
                o_rev, o_ord = float(doc.get("revenue_target") or 0), int(doc.get("orders_target") or 0)
                tot_lama += o_rev
                sebelum = _teks_target(o_rev, o_ord, pesanan_tampil or bool(o_ord))
                if (o_rev, o_ord) != (rev, ords):
                    berubah += 1
                if o_rev and (rev > o_rev * 1.5 or rev < o_rev * 0.7):
                    peringatan.append(f"Target {nama} berubah {(rev / o_rev - 1) * 100:+.0f}% dari target lama.")
            else:
                sebelum = "—"
                berubah += 1
            tot_baru += rev
            perubahan.append({"label": nama, "sebelum": sebelum, "sesudah": _teks_target(rev, ords, pesanan_tampil)})
            aktual = float(row.get("aktual_omzet") or 0)
            if row.get("bulan_berjalan") and rev < aktual:
                peringatan.append(f"Target {nama} lebih kecil dari omzet yang sudah tercapai bulan ini ({rp(aktual)}).")
            if rev == 0:
                peringatan.append(f"Target omzet {nama} Rp 0 — capaian toko ini tidak akan bisa dinilai.")
            ubah.append({"kunci": f"toko.{i}.target_omzet", "label": f"Target omzet {nama}", "jenis": "rupiah",
                         "nilai": rev})
            if t.get("target_pesanan") is not None:
                ubah.append({"kunci": f"toko.{i}.target_pesanan", "label": f"Target pesanan {nama}",
                             "jenis": "angka", "nilai": ords})
        if not berubah:
            raise AlatError(409, "Target semua toko itu sudah sama persis dengan isian ini; tidak ada yang perlu "
                                 "diubah.")
        sk = args.get("skenario")
        catatan = [(f"Periode {label} masih terbuka untuk " + ("semua toko ini." if len(toko) > 1 else "toko ini."))
                   if terbaca else
                   "Status kunci periode tidak bisa dibaca dengan akun ini; bila periodenya sudah ditutup, "
                   "penyimpanan akan ditolak.",
                   "Disimpan lewat jalur yang sama dengan layar Target & Budget dan tercatat di Jejak Perubahan "
                   "dengan tanda 'Asisten AI'.",
                   "Target pesanan yang tidak disebut, skor kesehatan, dan catatan target tetap seperti sekarang."]
        return _batasi({
            "judul": f"Pasang target toko {label}",
            "ringkas": (f"{len(toko)} toko" + (f", skenario {sk}" if sk and sk != "lainnya" else "")
                        + f" — total {rp(tot_baru)}"
                        + (f" (sebelumnya {rp(tot_lama)} untuk {ada_lama} toko)." if ada_lama else
                           " (sebelumnya belum ada target).")),
            "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
            "tautan": {"label": "Buka layar Target", "menu": "marketing-targets"}})

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        bulan, toko = args["bulan"], args["toko"]
        nama = [p.get("label") for p in (rencana or {}).get("perubahan") or []]
        lama = await _target_bulan(ctx, bulan)
        alasan = _jejak(f"skenario {args['skenario']}" if args.get("skenario") else "", args.get("alasan"))
        selesai: List[dict] = []
        try:
            for i, t in enumerate(toko):
                doc = lama.get(t["toko_id"])
                rev, ords = _isi_target(doc, t)
                res = await _tulis(ctx, "POST", "/api/marketing/targets",
                                   json=_body_target(t["toko_id"], bulan, rev, ords, doc, alasan))
                tid = ((res or {}).get("target") or {}).get("id") or (doc or {}).get("id")
                selesai.append({"toko_id": t["toko_id"], "toko": nama[i] if i < len(nama) else t["toko_id"],
                                "target_id": tid, "dibuat": doc is None,
                                "sebelum": None if doc is None else {
                                    k: doc.get(k) for k in ("revenue_target", "orders_target",
                                                            "health_score_target", "notes")},
                                "sesudah": {"revenue_target": rev, "orders_target": ords}})
        except AlatError as e:
            gagal = await _balikkan_target(ctx, bulan, selesai, _jejak("dibatalkan otomatis: tindakan gagal"),
                                           periksa=False)
            raise _gagal_sebagian("Pemasangan target", e, gagal) from None
        total = sum(s["sesudah"]["revenue_target"] for s in selesai)
        return {"ringkas": f"Target {len(selesai)} toko {U.label_bulan(bulan)} terpasang (total {rp(total)}).",
                "hasil": {"bulan": bulan, "toko": [{"toko_id": s["toko_id"], "target_id": s["target_id"],
                                                    "dibuat": s["dibuat"]} for s in selesai]},
                "sebelum": [{"label": s["toko"], "nilai": "—" if s["sebelum"] is None else _teks_target(
                    float(s["sebelum"].get("revenue_target") or 0), int(s["sebelum"].get("orders_target") or 0), True)}
                            for s in selesai],
                "sesudah": [{"label": s["toko"], "nilai": _teks_target(s["sesudah"]["revenue_target"],
                                                                       s["sesudah"]["orders_target"], True)}
                            for s in selesai],
                "pembatalan": {"bulan": bulan, "toko": selesai}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        bulan, entri = pembatalan["bulan"], list(pembatalan.get("toko") or [])
        gagal = await _balikkan_target(ctx, bulan, entri, _jejak("membalikkan tindakan"), periksa=True)
        if gagal:
            raise AlatError(502, "Sebagian target gagal dikembalikan: " + "; ".join(gagal[:5])
                            + ". Toko lainnya sudah kembali seperti semula.")
        baru = sum(1 for e in entri if e["dibuat"])
        return {"ringkas": f"Target {len(entri)} toko {U.label_bulan(bulan)} dikembalikan seperti sebelum tindakan"
                           + (f" ({baru} target baru dihapus)." if baru else ".")}


# ══════════════════════════════════════════════════════════════════════════════
# 2. RENCANA ANGGARAN MARKETING
# ══════════════════════════════════════════════════════════════════════════════
KATEGORI = ("ads", "kol", "komisi", "livehost", "sample", "diskon")   # = core.marketing_cycle.CATEGORIES
LABEL_KATEGORI = {"ads": "Iklan", "kol": "KOL", "komisi": "Komisi kreator", "livehost": "Host live",
                  "sample": "Sampel", "diskon": "Diskon"}
PERIODE_ANGGARAN = {"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$"}


def _label_periode(p: str) -> str:
    if len(p) == 7:
        return U.label_bulan(p)
    d = date.fromisoformat(p)
    akhir = d + timedelta(days=6)
    return f"7 hari mulai {label_tanggal(p)} (s.d. {label_tanggal(akhir.isoformat())})"


def _bbc(doc: Optional[dict]) -> Dict[str, float]:
    b = (doc or {}).get("budget_by_category") or {}
    return {c: round(float(b.get(c) or 0), 2) for c in KATEGORI}


async def _anggaran(ctx, toko_id: str, periode: str) -> dict:
    return await ctx.api("GET", "/api/marketing/budget", params={"account_id": toko_id, "period": periode}) or {}


async def _balikkan_anggaran(ctx, periode: str, entri: List[dict], alasan: str, *, periksa: bool) -> List[str]:
    if periksa:
        beda = []
        for e in entri:
            kini = _bbc(await _anggaran(ctx, e["toko_id"], periode))
            if kini != {c: round(float(e["sesudah"].get(c) or 0), 2) for c in KATEGORI}:
                beda.append(e.get("toko") or e["toko_id"])
        if beda:
            raise AlatError(409, "Rencana anggaran toko berikut sudah diubah lagi sesudah tindakan ini: "
                            + ", ".join(beda[:8]) + ". Pembalikan dibatalkan supaya perubahan itu tidak tertimpa.")
    gagal = []
    for e in reversed(entri):
        try:
            await _tulis(ctx, "PUT", "/api/marketing/budget", json={
                "account_id": e["toko_id"], "period": periode, "budget_by_category": e["sebelum"],
                "notes": e.get("catatan_lama") or "", "reason": alasan})
        except AlatError as x:
            gagal.append(f"{e.get('toko') or e['toko_id']}: {x.pesan}")
    return gagal


@tindakan(
    name="rencana_anggaran_marketing",
    label="Menyusun rencana anggaran marketing",
    description=(
        "MENYIAPKAN rencana anggaran marketing per kategori (iklan=ads, KOL=kol, komisi kreator=komisi, host "
        "live=livehost, sampel=sample, diskon=diskon; Rupiah) untuk satu atau beberapa toko pada satu periode — "
        "sama dengan layar Target & Budget (tab Budget). Hanya menyiapkan KARTU KONFIRMASI (lama → baru per "
        "kategori); tidak ada yang tersimpan sebelum pengguna menekan Setujui.\n"
        "Periode TTTT-BB (bulanan) atau TTTT-BB-HH (periode 7 hari mulai tanggal itu, bawaan layar). Kategori "
        "yang tidak disebut tetap seperti sekarang. Aturan: hanya SPV/Manager Marketing atau owner; toko dalam "
        "lingkup pengguna & CV terpilih; periode yang sudah ditutup ditolak. Ini RENCANA, bukan biaya: tidak "
        "membuat pengeluaran atau jurnal apa pun. Bisa dibalikkan (rencana lama dipulihkan)."),
    input_schema={
        "type": "object",
        "properties": {
            "periode": {**PERIODE_ANGGARAN, "description": "TTTT-BB atau TTTT-BB-HH (mulai periode 7 hari)."},
            "toko": {"type": "array", "minItems": 1, "maxItems": 20,
                     "items": {"type": "object", "properties": {
                         "toko_id": {"type": "string", "minLength": 1},
                         "anggaran": {"type": "object", "description": "Rp per kategori yang diubah.",
                                      "properties": {c: {"type": "number", "minimum": 0, "maximum": 1e11,
                                                         "description": LABEL_KATEGORI[c]} for c in KATEGORI},
                                      "additionalProperties": False},
                         "catatan": {"type": "string", "maxLength": 500,
                                     "description": "Catatan rencana (opsional; kosong = catatan lama tetap)."}},
                         "required": ["toko_id", "anggaran"], "additionalProperties": False}},
            "alasan": ALASAN,
        },
        "required": ["periode", "toko"],
        "additionalProperties": False,
    },
    domain="iklan",
    risiko="rendah",
    menu="marketing-targets",
)
class RencanaAnggaranMarketing:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _cek_cv_tulis(ctx)
        periode, toko = args["periode"], args["toko"]
        if len(periode) == 10:
            _tanggal_sah(periode, "Tanggal mulai periode")
        bulan = periode[:7]
        _cek_bulan(ctx, bulan, "Rencana anggaran")
        ids = [t["toko_id"] for t in toko]
        if len(set(ids)) != len(ids):
            raise AlatError(400, "Ada toko yang disebut dua kali; satukan dulu anggarannya.")
        kosong = [t["toko_id"] for t in toko if not t.get("anggaran")]
        if kosong:
            raise AlatError(400, "Sebutkan minimal satu kategori anggaran untuk setiap toko.")
        _cek_penulis_target(ctx, "rencana anggaran")
        terlihat = await _toko_cv(ctx, bulan)
        _tolak_toko_luar(ctx, ids, terlihat)
        terkunci, terbaca = await _periode_terkunci(ctx, ids, bulan)
        if terkunci:
            raise AlatError(423, f"Periode {U.label_bulan(bulan)} sudah DITUTUP untuk toko: "
                                 f"{', '.join(terlihat[i].get('toko') or i for i in terkunci)}. Minta SPV Marketing "
                                 "membuka periodenya, atau keluarkan toko itu dari daftar.")
        peringatan: List[str] = []
        try:
            ps = await ctx.api("GET", "/api/marketing/budget/period-settings") or {}
            mode = (ps.get("settings") or ps).get("period_mode")
        except AlatError:
            mode = None
        if mode == "weekly" and len(periode) == 7:
            peringatan.append("Layar anggaran saat ini memakai periode 7 hari; rencana BULANAN ini tetap tersimpan, "
                              "tetapi baru tampil bila layar dipindah ke periode bulanan.")
        if mode == "monthly" and len(periode) == 10:
            peringatan.append("Layar anggaran saat ini memakai periode bulanan; rencana 7 hari ini tetap tersimpan, "
                              "tetapi baru tampil bila layar dipindah ke periode 7 hari.")
        perubahan, ubah = [], []
        berubah = 0
        tot_lama = tot_baru = 0.0
        for i, t in enumerate(toko):
            nama = terlihat[t["toko_id"]].get("toko") or t["toko_id"]
            doc = await _anggaran(ctx, t["toko_id"], periode)
            lama, ada = _bbc(doc), bool(doc.get("exists"))
            baru = {**lama, **{c: round(float(v), 2) for c, v in t["anggaran"].items()}}
            for c in KATEGORI:
                if c in t["anggaran"]:
                    perubahan.append({"label": f"{nama} · {LABEL_KATEGORI[c]}",
                                      "sebelum": rp(lama[c]) if ada else "—", "sesudah": rp(baru[c])})
                    ubah.append({"kunci": f"toko.{i}.anggaran.{c}", "label": f"{LABEL_KATEGORI[c]} {nama}",
                                 "jenis": "rupiah", "nilai": baru[c]})
            perubahan.append({"label": f"{nama} · Total", "sebelum": rp(sum(lama.values())) if ada else "—",
                              "sesudah": rp(sum(baru.values()))})
            berubah += int(baru != lama or not ada)
            tot_lama += sum(lama.values())
            tot_baru += sum(baru.values())
        if not berubah:
            raise AlatError(409, "Rencana anggaran itu sudah sama persis dengan isian ini; tidak ada yang perlu diubah.")
        catatan = [f"Periode anggaran: {_label_periode(periode)}.",
                   (f"Periode {U.label_bulan(bulan)} masih terbuka." if terbaca else
                    "Status kunci periode tidak bisa dibaca; bila periodenya sudah ditutup, penyimpanan akan ditolak."),
                   "Kategori yang tidak disebut tetap seperti sekarang. Ini rencana, bukan pengeluaran: tidak ada "
                   "biaya atau jurnal yang dibuat.",
                   "Tercatat di Jejak Perubahan dengan tanda 'Asisten AI'."]
        return _batasi({
            "judul": f"Rencana anggaran marketing {_label_periode(periode)}",
            "ringkas": f"{len(toko)} toko — total rencana {rp(tot_baru)} (sebelumnya {rp(tot_lama)}).",
            "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
            "tautan": {"label": "Buka layar Target & Budget", "menu": "marketing-targets"}})

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        periode, toko = args["periode"], args["toko"]
        alasan = _jejak(args.get("alasan"))
        nama = [p["label"][: -len(" · Total")] for p in (rencana or {}).get("perubahan") or []
                if str(p.get("label") or "").endswith(" · Total")]
        selesai: List[dict] = []
        try:
            for i, t in enumerate(toko):
                doc = await _anggaran(ctx, t["toko_id"], periode)
                lama = _bbc(doc)
                baru = {**lama, **{c: round(float(v), 2) for c, v in t["anggaran"].items()}}
                catatan_lama = doc.get("notes") or ""
                await _tulis(ctx, "PUT", "/api/marketing/budget", json={
                    "account_id": t["toko_id"], "period": periode, "budget_by_category": baru,
                    "notes": t.get("catatan") if t.get("catatan") is not None else catatan_lama, "reason": alasan})
                selesai.append({"toko_id": t["toko_id"],
                                "toko": nama[i] if i < len(nama) else (doc.get("account_name") or t["toko_id"]),
                                "ada_sebelumnya": bool(doc.get("exists")), "sebelum": lama,
                                "catatan_lama": catatan_lama, "sesudah": baru})
        except AlatError as e:
            gagal = await _balikkan_anggaran(ctx, periode, selesai, _jejak("dibatalkan otomatis: tindakan gagal"),
                                             periksa=False)
            raise _gagal_sebagian("Penyimpanan rencana anggaran", e, gagal) from None
        total = sum(sum(s["sesudah"].values()) for s in selesai)

        def _rinci(bbc: dict) -> str:
            return ", ".join(f"{LABEL_KATEGORI[c]} {rp(v)}" for c, v in bbc.items() if v) or "Rp 0"
        return {"ringkas": f"Rencana anggaran {len(selesai)} toko ({_label_periode(periode)}) tersimpan, total {rp(total)}.",
                "hasil": {"periode": periode, "toko": [s["toko_id"] for s in selesai]},
                "sebelum": [{"label": s["toko"], "nilai": _rinci(s["sebelum"]) if s["ada_sebelumnya"] else "—"}
                            for s in selesai],
                "sesudah": [{"label": s["toko"], "nilai": _rinci(s["sesudah"])} for s in selesai],
                "pembatalan": {"periode": periode, "toko": selesai}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        periode, entri = pembatalan["periode"], list(pembatalan.get("toko") or [])
        gagal = await _balikkan_anggaran(ctx, periode, entri, _jejak("membalikkan tindakan"), periksa=True)
        if gagal:
            raise AlatError(502, "Sebagian rencana gagal dikembalikan: " + "; ".join(gagal[:5]) + ".")
        baru = sum(1 for e in entri if not e.get("ada_sebelumnya"))
        return {"ringkas": f"Rencana anggaran {len(entri)} toko ({_label_periode(periode)}) dikembalikan seperti "
                           "sebelum tindakan" + (f"; {baru} toko yang sebelumnya belum punya rencana kini Rp 0."
                                                 if baru else ".")}


# ══════════════════════════════════════════════════════════════════════════════
# 3. TUGAS MARKETING
# ══════════════════════════════════════════════════════════════════════════════
JENIS_TUGAS = {"operational": "Operasional", "data_entry": "Input data", "review": "Tinjauan",
               "analysis": "Analisis", "reporting": "Laporan"}
PRIORITAS = {"high": "Tinggi", "medium": "Sedang", "low": "Rendah"}


async def _penanggung_jawab(ctx, nilai: Optional[str], akun: Optional[dict], cache: dict) -> Tuple[Optional[str], str]:
    """(user id | None, nama tampilan). Bawaan: PIC toko itu (Manajemen Akun)."""
    v = (nilai or "").strip()
    if not v or v.lower() == "pic_toko":
        pic = (akun or {}).get("pic_user_id")
        if not pic:
            if v:
                raise AlatError(400, "Toko itu belum punya PIC (atur di Manajemen Akun), jadi tugas tidak bisa "
                                     "ditujukan ke PIC toko. Sebutkan nama penanggung jawabnya.")
            return None, "belum ditugaskan"
        cocok = [u for u in await _pengguna_toko(ctx, cache) if u.get("id") == pic]
        return pic, (cocok[0].get("name") if cocok else "PIC toko")
    cocok = _cocokkan(await _pengguna_toko(ctx, cache), v)
    if not cocok:
        raise AlatError(400, f"Pengguna '{v}' tidak ditemukan di tim Marketing yang aktif. Sebutkan nama lengkapnya.")
    if len(cocok) > 1:
        raise AlatError(400, f"'{v}' cocok dengan beberapa orang: "
                             f"{', '.join(str(u.get('name')) for u in cocok[:6])}. Sebutkan yang mana.")
    return cocok[0]["id"], str(cocok[0].get("name") or v)


def _tenggat_iso(tgl: Optional[str], jam: Optional[str]) -> Optional[str]:
    """Sama dengan layar (`fromWIBLocalInput`): jam dinding WIB → ISO UTC."""
    if not tgl:
        return None
    dt = datetime.fromisoformat(f"{tgl}T{jam or '17:00'}:00").replace(tzinfo=WIB).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _persiapan_tugas(ctx, tugas: List[dict], cache: dict) -> List[dict]:
    from routes.marketing_shared import TASK_CREATE_DENIED, can_create_task
    ids = [t["toko_id"] for t in tugas if t.get("toko_id")]
    terlihat = await _toko_cv(ctx) if ids else {}
    _tolak_toko_luar(ctx, ids, terlihat)
    out = []
    for t in tugas:
        jenis = t.get("jenis") or "operational"
        if jenis == "data_entry" and not t.get("toko_id"):
            raise AlatError(400, f"Tugas '{t['judul']}' berjenis Input data wajib menyebut tokonya.")
        if t.get("tenggat"):
            _cek_tanggal_depan(ctx, t["tenggat"], "Tenggat")
        akun = await _akun(ctx, t["toko_id"], cache) if t.get("toko_id") else None
        if not can_create_task(ctx.user, akun):
            raise AlatError(403, TASK_CREATE_DENIED)
        uid, nama = await _penanggung_jawab(ctx, t.get("ditugaskan_ke"), akun, cache)
        out.append({"t": t, "jenis": jenis, "prioritas": t.get("prioritas") or "medium", "akun": akun,
                    "toko": (terlihat.get(t.get("toko_id")) or {}).get("toko") or (akun or {}).get("account_name"),
                    "uid": uid, "nama": nama})
    return out


async def _batalkan_tugas(ctx, ids: List[str]) -> List[str]:
    gagal = []
    for tid in reversed(ids):
        try:
            await _tulis(ctx, "PUT", f"/api/marketing/tasks/{tid}", json={"status": "cancelled"})
        except AlatError as x:
            gagal.append(f"{tid}: {x.pesan}")
    return gagal


@tindakan(
    name="buat_tugas_marketing",
    label="Membuat tugas marketing",
    description=(
        "MENYIAPKAN satu atau beberapa tugas marketing (judul, keterangan, jenis, prioritas, toko, penanggung "
        "jawab, tenggat, daftar periksa) — sama dengan tombol Buat Task di layar Tugas Marketing. Hanya "
        "menyiapkan KARTU KONFIRMASI; tidak ada yang tersimpan sebelum pengguna menekan Setujui.\n"
        "Penanggung jawab: kosong atau 'pic_toko' = PIC toko itu (dipilih di Manajemen Akun); selain itu nama "
        "atau email anggota tim Marketing yang aktif. Aturan pembuat: PIC Marketing, PIC toko itu, SPV/Manager "
        "Marketing, atau owner; toko harus dipegang pengguna pada CV terpilih; tenggat tidak boleh lewat. Jenis: "
        "operational (bawaan), data_entry (wajib toko), review, analysis, reporting. Bisa dibalikkan: tugas "
        "dibatalkan selama belum mulai dikerjakan."),
    input_schema={
        "type": "object",
        "properties": {
            "tugas": {"type": "array", "minItems": 1, "maxItems": 10, "items": {
                "type": "object", "properties": {
                    "judul": {"type": "string", "minLength": 3, "maxLength": 300},
                    "keterangan": {"type": "string", "maxLength": 2000},
                    "jenis": {"type": "string", "enum": list(JENIS_TUGAS)},
                    "prioritas": {"type": "string", "enum": list(PRIORITAS)},
                    "toko_id": {"type": "string", "minLength": 1, "description": "Id toko (opsional)."},
                    "ditugaskan_ke": {"type": "string", "maxLength": 120,
                                      "description": "'pic_toko', nama, atau email penanggung jawab."},
                    "tenggat": {**TANGGAL, "description": "Tenggat (TTTT-BB-HH)."},
                    "jam_tenggat": {**JAM, "description": "Jam tenggat WIB (JJ:MM). Bawaan 17:00."},
                    "daftar_periksa": {"type": "array", "maxItems": 20,
                                       "items": {"type": "string", "minLength": 1, "maxLength": 200}}},
                "required": ["judul"], "additionalProperties": False}},
        },
        "required": ["tugas"],
        "additionalProperties": False,
    },
    domain="umum",
    risiko="rendah",
    menu="marketing-task-hub",
)
class BuatTugasMarketing:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _cek_cv_tulis(ctx)
        siap = await _persiapan_tugas(ctx, args["tugas"], {})
        perubahan, ubah, peringatan = [], [], []
        for i, s in enumerate(siap):
            t = s["t"]
            tgl = label_tanggal(t["tenggat"]) + f" {t.get('jam_tenggat') or '17:00'}" if t.get("tenggat") else "tanpa tenggat"
            perubahan.append({"label": t["judul"][:80], "sebelum": "—", "sesudah": (
                f"{JENIS_TUGAS[s['jenis']]} · prioritas {PRIORITAS[s['prioritas']].lower()} · "
                f"{s['toko'] or 'tanpa toko'} · untuk {s['nama']} · {tgl}")})
            if not s["uid"]:
                peringatan.append(f"Tugas '{t['judul'][:60]}' belum punya penanggung jawab (toko tanpa PIC).")
            ubah.append({"kunci": f"tugas.{i}.judul", "label": f"Judul tugas {i + 1}", "jenis": "teks",
                         "nilai": t["judul"]})
            if t.get("tenggat"):
                ubah.append({"kunci": f"tugas.{i}.tenggat", "label": f"Tenggat tugas {i + 1}", "jenis": "tanggal",
                             "nilai": t["tenggat"]})
            ubah.append({"kunci": f"tugas.{i}.prioritas", "label": f"Prioritas tugas {i + 1}", "jenis": "pilihan",
                         "nilai": s["prioritas"],
                         "pilihan": [{"nilai": k, "label": v} for k, v in PRIORITAS.items()]})
        n = len(siap)
        return _batasi({
            "judul": "Buat tugas marketing" if n == 1 else f"Buat {n} tugas marketing",
            "ringkas": (f"Tugas untuk {siap[0]['nama']}." if n == 1 else
                        f"{n} tugas untuk {len({s['nama'] for s in siap})} penanggung jawab."),
            "perubahan": perubahan,
            "catatan": ["Tugas dibuat berstatus 'To do' lewat jalur yang sama dengan layar Tugas Marketing; "
                        "penanggung jawab melihatnya di daftar tugasnya."],
            "peringatan": peringatan, "ubah": ubah,
            "tautan": {"label": "Buka layar Tugas Marketing", "menu": "marketing-task-hub"}})

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        siap = await _persiapan_tugas(ctx, args["tugas"], {})
        dibuat: List[dict] = []
        try:
            for s in siap:
                t = s["t"]
                res = await _tulis(ctx, "POST", "/api/marketing/tasks", json={
                    "title": t["judul"], "description": t.get("keterangan") or None, "task_type": s["jenis"],
                    "priority": s["prioritas"], "assigned_to": s["uid"], "account_id": t.get("toko_id") or None,
                    "due_date": _tenggat_iso(t.get("tenggat"), t.get("jam_tenggat")),
                    "checklist": [{"item": x, "completed": False} for x in t.get("daftar_periksa") or []],
                    "recurrence": "one-time"})
                task = (res or {}).get("task") or {}
                dibuat.append({"id": task.get("id"), "kode": task.get("task_code"), "judul": t["judul"]})
        except AlatError as e:
            gagal = await _batalkan_tugas(ctx, [d["id"] for d in dibuat if d["id"]])
            raise _gagal_sebagian("Pembuatan tugas", e, gagal) from None
        return {"ringkas": (f"Tugas '{dibuat[0]['judul'][:60]}' dibuat untuk {siap[0]['nama']}." if len(dibuat) == 1
                            else f"{len(dibuat)} tugas marketing dibuat."),
                "hasil": {"tugas": dibuat}, "pembatalan": {"tugas": dibuat}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        entri = list(pembatalan.get("tugas") or [])
        jalan, sudah = [], []
        for e in entri:
            task = await ctx.api("GET", f"/api/marketing/tasks/{e['id']}") or {}
            st = task.get("status")
            if st == "cancelled":
                sudah.append(e["id"])
            elif st != "to_do":
                jalan.append(f"'{e['judul'][:50]}' ({st})")
        if jalan:
            raise AlatError(409, "Tugas berikut sudah mulai dikerjakan, jadi tidak dibatalkan otomatis: "
                            + ", ".join(jalan[:6]) + ". Batalkan manual di layar Tugas bila memang perlu.")
        gagal = await _batalkan_tugas(ctx, [e["id"] for e in entri if e["id"] not in sudah])
        if gagal:
            raise AlatError(502, "Sebagian tugas gagal dibatalkan: " + "; ".join(gagal[:5]) + ".")
        return {"ringkas": f"{len(entri)} tugas marketing dibatalkan."}


# ══════════════════════════════════════════════════════════════════════════════
# 4. KALENDER KONTEN
# ══════════════════════════════════════════════════════════════════════════════
def _jenis_konten() -> Dict[str, str]:
    from routes.marketing_content_calendar_routes import CONTENT_TYPE_LABELS
    return dict(CONTENT_TYPE_LABELS)


def _platform_konten(platform: Any) -> str:
    from core.marketing_account_scope import platform_family
    return platform_family(platform) or "shopee"


async def _persiapan_konten(ctx, args: dict, cache: dict) -> List[dict]:
    jenis = _jenis_konten()
    items = args["konten"]
    terlihat = await _toko_cv(ctx)
    _tolak_toko_luar(ctx, [k["toko_id"] for k in items], terlihat)
    out = []
    for k in items:
        if k["jenis"] not in jenis:
            raise AlatError(400, f"Jenis konten '{k['jenis']}' tidak dikenal. Pilihan: "
                                 + ", ".join(f"{c} ({v})" for c, v in jenis.items()) + ".")
        _cek_tanggal_depan(ctx, k["tanggal"], "Tanggal konten")
        akun = await _akun(ctx, k["toko_id"], cache)
        out.append({"k": k, "akun": akun, "jenis_label": jenis[k["jenis"]],
                    "toko": terlihat[k["toko_id"]].get("toko") or akun.get("account_name") or k["toko_id"]})
    return out


async def _batalkan_konten(ctx, ids: List[str]) -> List[str]:
    gagal = []
    for cid in reversed(ids):
        try:
            await _tulis(ctx, "POST", f"/api/marketing/content-calendar/{cid}/status", json={"status": "cancelled"})
        except AlatError as x:
            gagal.append(f"{cid}: {x.pesan}")
    return gagal


@tindakan(
    name="jadwalkan_konten",
    label="Menjadwalkan konten",
    description=(
        "MENYIAPKAN satu atau beberapa rencana konten di Kalender Konten Marketing (toko, tanggal, jam tayang, "
        "jenis konten, judul, keterangan, CTA, brief, hook, kreator, SKU) — sama dengan tombol Tambah di layar "
        "Kalender Konten. Hanya menyiapkan KARTU KONFIRMASI; tidak ada yang tersimpan sebelum Setujui.\n"
        "Jenis konten (kode): foto_produk, video_produk, reels_tiktok, live_streaming, story, promo_flash_sale, "
        "konten_edukasi, behind_scenes, testimonial, unboxing, kolaborasi_kol. Status 'scheduled' (bawaan) atau "
        "'draft'; tidak bisa langsung 'Tayang' (butuh link terbit). Toko harus dipegang pengguna pada CV "
        "terpilih; tanggal hari ini atau sesudahnya. Bisa dibalikkan: konten dibatalkan selama belum tayang."),
    input_schema={
        "type": "object",
        "properties": {
            "konten": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
                "type": "object", "properties": {
                    "toko_id": {"type": "string", "minLength": 1},
                    "tanggal": {**TANGGAL, "description": "Tanggal tayang (TTTT-BB-HH)."},
                    "jam": {**JAM, "description": "Jam tayang WIB (JJ:MM), opsional."},
                    "jenis": {"type": "string", "minLength": 2, "maxLength": 40, "description": "Kode jenis konten."},
                    "judul": {"type": "string", "minLength": 3, "maxLength": 200},
                    "keterangan": {"type": "string", "maxLength": 2000},
                    "cta": {"type": "string", "maxLength": 200},
                    "brief": {"type": "string", "maxLength": 2000},
                    "hook": {"type": "string", "maxLength": 300},
                    "kreator_id": {"type": "string", "minLength": 1, "description": "Id kreator (opsional)."},
                    "sku": {"type": "string", "maxLength": 60}},
                "required": ["toko_id", "tanggal", "jenis", "judul"], "additionalProperties": False}},
            "status": {"type": "string", "enum": ["scheduled", "draft"], "description": "Bawaan scheduled."},
        },
        "required": ["konten"],
        "additionalProperties": False,
    },
    domain="umum",
    risiko="rendah",
    menu="marketing-content-calendar",
)
class JadwalkanKonten:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _cek_cv_tulis(ctx)
        siap = await _persiapan_konten(ctx, args, {})
        perubahan, ubah = [], []
        for i, s in enumerate(siap):
            k = s["k"]
            perubahan.append({"label": f"{s['toko']} · {label_tanggal(k['tanggal'])}" + (f" {k['jam']}" if k.get("jam") else ""),
                              "sebelum": "—", "sesudah": f"{s['jenis_label']}: {k['judul']}"})
            ubah.append({"kunci": f"konten.{i}.tanggal", "label": f"Tanggal konten {i + 1}", "jenis": "tanggal",
                         "nilai": k["tanggal"]})
            ubah.append({"kunci": f"konten.{i}.judul", "label": f"Judul konten {i + 1}", "jenis": "teks",
                         "nilai": k["judul"]})
        st = args.get("status") or "scheduled"
        return _batasi({
            "judul": f"Jadwalkan {len(siap)} konten",
            "ringkas": f"{len(siap)} konten di {len({s['toko'] for s in siap})} toko, status "
                       + ("terjadwal." if st == "scheduled" else "draf."),
            "perubahan": perubahan,
            "catatan": ["Disimpan di Kalender Konten lewat jalur yang sama dengan layar; KPI konten diisi "
                        "setelah tayang."],
            "peringatan": [], "ubah": ubah,
            "tautan": {"label": "Buka Kalender Konten", "menu": "marketing-content-calendar"}})

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        siap = await _persiapan_konten(ctx, args, {})
        st = args.get("status") or "scheduled"
        dibuat: List[dict] = []
        try:
            for s in siap:
                k, akun = s["k"], s["akun"]
                res = await _tulis(ctx, "POST", "/api/marketing/content-calendar", json={
                    "account_id": k["toko_id"], "account_name": akun.get("account_name") or s["toko"],
                    "platform": _platform_konten(akun.get("platform")), "date": k["tanggal"],
                    "content_type": k["jenis"], "title": k["judul"], "description": k.get("keterangan") or "",
                    "cta": k.get("cta") or "", "post_time": k.get("jam") or "", "status": st,
                    "creator_id": k.get("kreator_id") or None, "sku": k.get("sku") or "",
                    "brief": k.get("brief") or "", "hook": k.get("hook") or ""})
                d = (res or {}).get("data") or {}
                dibuat.append({"id": d.get("id"), "judul": k["judul"], "toko_id": k["toko_id"], "tanggal": k["tanggal"]})
        except AlatError as e:
            gagal = await _batalkan_konten(ctx, [d["id"] for d in dibuat if d["id"]])
            raise _gagal_sebagian("Penjadwalan konten", e, gagal) from None
        return {"ringkas": f"{len(dibuat)} konten terjadwal di Kalender Konten.",
                "hasil": {"konten": dibuat}, "pembatalan": {"konten": dibuat}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        entri = list(pembatalan.get("konten") or [])
        tayang, sudah = [], set()
        for e in entri:
            data = await ctx.api("GET", "/api/marketing/content-calendar", params={
                "account_id": e["toko_id"], "date_from": e["tanggal"], "date_to": e["tanggal"], "page_size": 100}) or {}
            cocok = [x for x in data.get("data") or [] if x.get("id") == e["id"]]
            st = (cocok[0] if cocok else {}).get("status")
            if not cocok or st == "cancelled":
                sudah.add(e["id"])
            elif st == "posted":
                tayang.append(f"'{e['judul'][:50]}'")
        if tayang:
            raise AlatError(409, "Konten berikut sudah TAYANG, jadi tidak dibatalkan otomatis: " + ", ".join(tayang[:6])
                            + ". Ubah manual di Kalender Konten bila perlu.")
        gagal = await _batalkan_konten(ctx, [e["id"] for e in entri if e["id"] not in sudah])
        if gagal:
            raise AlatError(502, "Sebagian konten gagal dibatalkan: " + "; ".join(gagal[:5]) + ".")
        return {"ringkas": f"{len(entri)} konten di Kalender Konten dibatalkan."}


# ══════════════════════════════════════════════════════════════════════════════
# 5. JADWAL LIVE
# ══════════════════════════════════════════════════════════════════════════════
async def _persiapan_live(ctx, args: dict, cache: dict) -> List[dict]:
    sesi = args["sesi"]
    terlihat = await _toko_cv(ctx)
    _tolak_toko_luar(ctx, [s["toko_id"] for s in sesi], terlihat)
    if "host" not in cache:
        cache["host"] = list(await ctx.api("GET", "/api/marketing/livehost", params={"status": "active"}) or [])
    out = []
    for s in sesi:
        _cek_tanggal_depan(ctx, s["tanggal"], "Tanggal live")
        toko = terlihat[s["toko_id"]].get("toko") or s["toko_id"]
        cocok = _cocokkan(cache["host"], s["host"])
        if not cocok:
            raise AlatError(400, f"Host live '{s['host']}' tidak ditemukan di daftar host aktif yang boleh Anda lihat.")
        if len(cocok) > 1:
            raise AlatError(400, f"'{s['host']}' cocok dengan beberapa host: "
                                 f"{', '.join(str(h.get('name')) for h in cocok[:6])}. Sebutkan yang mana.")
        host = cocok[0]
        if s["toko_id"] not in (host.get("assigned_account_ids") or []):
            raise AlatError(400, f"Host {host.get('name')} belum di-assign ke toko {toko}. Assign dulu di Live Selling "
                                 "→ Host, supaya jam kerja & bayarannya tidak dibebankan ke toko lain.")
        out.append({"s": s, "toko": toko, "host_id": host["id"], "host": host.get("name") or s["host"],
                    "durasi": int(s.get("durasi_menit") or 120)})
    return out


async def _batalkan_live(ctx, ids: List[str]) -> List[str]:
    gagal = []
    for sid in reversed(ids):
        try:
            await _tulis(ctx, "PUT", f"/api/marketing/live/sessions/{sid}", json={"status": "cancelled"})
        except AlatError as x:
            gagal.append(f"{sid}: {x.pesan}")
    return gagal


@tindakan(
    name="jadwalkan_live",
    label="Menjadwalkan sesi live",
    description=(
        "MENYIAPKAN satu atau beberapa jadwal sesi live selling (toko, host, tanggal, jam mulai, durasi, judul) "
        "berstatus 'Terjadwal' — sama dengan menambah sesi di layar Live Selling. Hanya menyiapkan KARTU "
        "KONFIRMASI; tidak ada yang tersimpan sebelum Setujui.\n"
        "Host = nama atau id host live aktif yang SUDAH di-assign ke toko itu (aturan layar). Toko harus "
        "dipegang pengguna pada CV terpilih; tanggal hari ini atau sesudahnya. Angka hasil live (penonton, "
        "pesanan, omzet) diisi setelah sesi selesai, bukan di sini. Tidak membuat shift atau bayaran host. "
        "Bisa dibalikkan: sesi dibatalkan selama masih terjadwal."),
    input_schema={
        "type": "object",
        "properties": {
            "sesi": {"type": "array", "minItems": 1, "maxItems": 10, "items": {
                "type": "object", "properties": {
                    "toko_id": {"type": "string", "minLength": 1},
                    "host": {"type": "string", "minLength": 2, "maxLength": 120, "description": "Nama atau id host."},
                    "tanggal": {**TANGGAL, "description": "Tanggal live (TTTT-BB-HH)."},
                    "jam_mulai": {**JAM, "description": "Jam mulai WIB (JJ:MM)."},
                    "durasi_menit": {"type": "integer", "minimum": 15, "maximum": 720,
                                     "description": "Durasi rencana (menit). Bawaan 120."},
                    "judul": {"type": "string", "minLength": 3, "maxLength": 200},
                    "catatan": {"type": "string", "maxLength": 1000}},
                "required": ["toko_id", "host", "tanggal", "jam_mulai", "judul"], "additionalProperties": False}},
        },
        "required": ["sesi"],
        "additionalProperties": False,
    },
    domain="live",
    risiko="rendah",
    menu="marketing-live-hub",
)
class JadwalkanLive:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _cek_cv_tulis(ctx)
        siap = await _persiapan_live(ctx, args, {})
        perubahan, ubah = [], []
        for i, x in enumerate(siap):
            s = x["s"]
            perubahan.append({"label": f"{x['toko']} · {label_tanggal(s['tanggal'])} {s['jam_mulai']}", "sebelum": "—",
                              "sesudah": f"{s['judul']} · host {x['host']} · {x['durasi']} menit"})
            ubah.append({"kunci": f"sesi.{i}.tanggal", "label": f"Tanggal sesi {i + 1}", "jenis": "tanggal",
                         "nilai": s["tanggal"]})
            ubah.append({"kunci": f"sesi.{i}.jam_mulai", "label": f"Jam mulai sesi {i + 1}", "jenis": "teks",
                         "nilai": s["jam_mulai"]})
        return _batasi({
            "judul": f"Jadwalkan {len(siap)} sesi live",
            "ringkas": f"{len(siap)} sesi live terjadwal dengan {len({x['host'] for x in siap})} host.",
            "perubahan": perubahan,
            "catatan": ["Sesi disimpan berstatus Terjadwal lewat jalur yang sama dengan layar Live Selling; "
                        "angka hasil live diisi setelah sesi selesai."],
            "peringatan": [], "ubah": ubah,
            "tautan": {"label": "Buka Live Selling", "menu": "marketing-live-hub"}})

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        siap = await _persiapan_live(ctx, args, {})
        dibuat: List[dict] = []
        try:
            for x in siap:
                s = x["s"]
                res = await _tulis(ctx, "POST", "/api/marketing/live/sessions", json={
                    "account_id": s["toko_id"], "host_id": x["host_id"], "session_date": s["tanggal"],
                    "title": s["judul"], "start_time": s["jam_mulai"], "duration_minutes": x["durasi"],
                    "status": "scheduled", "notes_text": s.get("catatan") or ""})
                d = (res or {}).get("data") or {}
                dibuat.append({"id": d.get("id"), "judul": s["judul"]})
        except AlatError as e:
            gagal = await _batalkan_live(ctx, [d["id"] for d in dibuat if d["id"]])
            raise _gagal_sebagian("Penjadwalan live", e, gagal) from None
        return {"ringkas": f"{len(dibuat)} sesi live terjadwal.", "hasil": {"sesi": dibuat},
                "pembatalan": {"sesi": dibuat}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        entri = list(pembatalan.get("sesi") or [])
        jalan, sudah = [], set()
        for e in entri:
            res = await ctx.api("GET", f"/api/marketing/live/sessions/{e['id']}") or {}
            st = ((res.get("data") if isinstance(res.get("data"), dict) else res) or {}).get("status")
            if st == "cancelled":
                sudah.add(e["id"])
            elif st != "scheduled":
                jalan.append(f"'{e['judul'][:50]}' ({st})")
        if jalan:
            raise AlatError(409, "Sesi berikut sudah berjalan/selesai, jadi tidak dibatalkan otomatis: "
                            + ", ".join(jalan[:6]) + ".")
        gagal = await _batalkan_live(ctx, [e["id"] for e in entri if e["id"] not in sudah])
        if gagal:
            raise AlatError(502, "Sebagian sesi gagal dibatalkan: " + "; ".join(gagal[:5]) + ".")
        return {"ringkas": f"{len(entri)} sesi live dibatalkan."}


__all__ = ["PasangTargetToko", "RencanaAnggaranMarketing", "BuatTugasMarketing", "JadwalkanKonten", "JadwalkanLive"]
