"""Alat TINDAKAN Asisten AI — operasi (Tahap B, 8 Nov 2026; agen operasi). Kontrak D.

Setiap alat = kelas dengan `siapkan` (BACA SAJA: periksa isian + baca nilai sekarang lewat `ctx.api` GET →
Rencana untuk kartu konfirmasi), `jalankan` (TULIS lewat `ctx.api` dengan token pengguna, endpoint yang SAMA
dengan layar), dan `batalkan` bila endpoint-nya memungkinkan. Tidak ada tulis langsung ke DB di sini.

  buat_pengingat        Portal Saya › Ruang Kerja › Pengingat (`/api/portal/reminders`), atau pengingat
                        produksi ke vendor CMT (`/api/reminders`, peran produksi).        Batal = hapus.
  buat_objektif_okr     OKR Tracker (`POST /api/management/okr/objectives`).            Batal = arsipkan.
  perbarui_key_result   OKR Tracker (`PATCH /api/management/okr/key-results/{id}`).     Batal = nilai lama.
  buat_draf_pr          Belanja Mingguan (`POST /api/rahaza/shopping-list/create-pr`) → PR berstatus DRAF,
                        TIDAK pernah diajukan.                                          Batal = hapus draf.
  jadwalkan_laporan     Jadwal rapor valuasi aksesoris bulanan (`/api/acc/valuation/report-schedule`) —
                        satu-satunya fitur jadwal laporan yang ada.                    Batal = setelan lama.
  kirim_notifikasi      Notifikasi dalam aplikasi ke pengguna/peran (`POST /api/collab/notifications`,
                        aturan penerima yang ada). Tidak bisa ditarik (endpoint hanya mengizinkan penerima
                        menghapus notifikasinya sendiri) ⇒ tanpa `batalkan`.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Optional

from core.asisten_ai.alat_base import AlatError, tindakan  # Kontrak D (versi inti)

log = logging.getLogger(__name__)


# ── Bantuan tampilan (string Indonesia untuk kartu) ─────────────────────────────────────────────────────
_HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
          "Oktober", "November", "Desember")
_KOSONG = "—"
_WAKTU_RX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$"
_TANGGAL_RX = r"^\d{4}-\d{2}-\d{2}$"
_MENU_RX = r"^[a-z0-9][a-z0-9-]{1,63}$"
_EMAIL_RX = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def _angka(v: Any, desimal: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return _KOSONG
    s = f"{x:,.{desimal}f}".rstrip("0").rstrip(".") if desimal else f"{x:,.0f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _rp(v: Any) -> str:
    try:
        return "Rp " + _angka(round(float(v)), 0)
    except (TypeError, ValueError):
        return _KOSONG


def _persen(v: Any) -> str:
    return f"{_angka(v, 1)}%"


def _tanggal(s: str) -> str:
    try:
        d = date.fromisoformat(str(s)[:10])
    except ValueError:
        return str(s or _KOSONG)
    return f"{_HARI[d.weekday()]}, {d.day} {_BULAN[d.month - 1]} {d.year}"


def _waktu(s: str) -> str:
    try:
        dt = datetime.strptime(str(s), "%Y-%m-%dT%H:%M")
    except ValueError:
        return str(s or _KOSONG)
    return f"{_tanggal(dt.date().isoformat())} pukul {dt:%H.%M} WIB"


def _teks(v: Any, batas: int = 160) -> str:
    t = " ".join(str(v or "").split())
    return t if len(t) <= batas else t[: batas - 1] + "…"


def _peran(ctx) -> str:
    return str((getattr(ctx, "user", None) or {}).get("role") or "").lower()


def _boleh(ctx, peran: list | tuple, izin: Optional[str] = None) -> bool:
    """Aturan peran yang SAMA dengan endpoint (`auth.check_role`)."""
    from auth import check_role
    return bool(check_role(getattr(ctx, "user", None) or {}, list(peran), izin))


def _hari_ini(ctx) -> date:
    t = getattr(ctx, "today", None)
    if isinstance(t, datetime):
        return t.date()
    if isinstance(t, date):
        return t
    from utils.waktu import today_wib
    return today_wib()


def _nama_cv(ctx) -> str:
    from core.entities import entity_short
    return entity_short(str(getattr(ctx, "cv", "") or "DA").upper())


def _bersih_args(args: dict) -> dict:
    return {k: v for k, v in (args or {}).items() if v is not None}


async def _gerbang_tulis(ctx, method: str, path: str) -> Optional[str]:
    """Nilai gerbang izin modul (`middleware.module_permission_gate.evaluate`) untuk TULIS yang akan datang,
    tanpa menulis apa pun. Return nama modul/portal bila DITOLAK, None bila lolos atau tidak bisa dinilai
    (endpoint tetap menegakkan aturannya sendiri saat `jalankan`). Dipakai supaya kartu tidak ditawarkan
    untuk tulis yang pasti ditolak, dan supaya pembatalan hanya ditawarkan bila memang bisa."""
    if not getattr(ctx, "_token", None):
        return None
    try:
        from data.module_catalog import PORTAL_LABELS
        from middleware.module_permission_gate import evaluate
        u = getattr(ctx, "user", None) or {}
        d = await evaluate(method.upper(), path, {"id": u.get("id"), "role": u.get("role")})
    except Exception:  # noqa: BLE001 — penilaian awal saja
        log.warning("Gerbang modul tidak bisa dinilai untuk %s %s", method, path)
        return None
    if not d:
        return None
    mod, _aksi, _alasan = d
    return f"modul {mod.get('label')} (Portal {PORTAL_LABELS.get(mod.get('portal'), mod.get('portal'))})"


async def _wajib_gerbang(ctx, method: str, path: str) -> None:
    modul = await _gerbang_tulis(ctx, method, path)
    if modul:
        raise AlatError(403, f"Akun ini tidak diberi hak menulis di {modul}. Minta admin mencentang izinnya di "
                             "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses, atau lakukan lewat akun yang "
                             "berhak.")


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1. Pengingat
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_ULANG = {"sekali": "once", "harian": "daily", "mingguan": "weekly"}
_ULANG_LABEL = {"sekali": "Sekali", "harian": "Setiap hari", "mingguan": "Setiap minggu"}
_PRIORITAS_VENDOR = {"rendah": "low", "biasa": "normal", "tinggi": "high", "mendesak": "urgent"}


def _waktu_sah(waktu: Optional[str]) -> datetime:
    if not waktu:
        raise AlatError(400, "Pengingat butuh waktu (jam dinding WIB, format YYYY-MM-DDTHH:MM).")
    try:
        return datetime.strptime(waktu, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise AlatError(400, "Waktu pengingat tidak sah (format YYYY-MM-DDTHH:MM, jam WIB).") from None


def _pesan_vendor(a: dict) -> str:
    return (a.get("keterangan") or "").strip() + f"\nMohon ditindaklanjuti sebelum {_waktu(a['waktu'])}."


async def _cari_vendor(ctx, kunci: str) -> dict:
    """Vendor CMT dari master (`GET /api/garments`, SSOT vendor_partners). Cocok id persis, lalu nama/kode."""
    rows = await ctx.api("GET", "/api/garments", params={"status": "active"})
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]
    k = str(kunci or "").strip()
    persis = [r for r in rows if r["id"] == k]
    if persis:
        return persis[0]
    kl = k.lower()
    sama = [r for r in rows if kl in ((r.get("garment_name") or "").lower(), (r.get("garment_code") or "").lower())]
    calon = sama or [r for r in rows if kl and (kl in (r.get("garment_name") or "").lower()
                                                 or kl in (r.get("garment_code") or "").lower())]
    if not calon:
        raise AlatError(404, f"Vendor CMT aktif '{_teks(k, 60)}' tidak ditemukan di master vendor.")
    if len(calon) > 1:
        daftar = "; ".join(f"{r.get('garment_name') or '?'} (id {r['id']})" for r in calon[:8])
        raise AlatError(409, f"Ada {len(calon)} vendor yang cocok dengan '{_teks(k, 60)}': {daftar}. "
                             "Panggil lagi dengan id vendor yang dimaksud.")
    return calon[0]


@tindakan(
    name="buat_pengingat",
    label="Menyiapkan pengingat",
    description=(
        "Menyiapkan kartu untuk MEMBUAT pengingat; tidak ada yang tersimpan sebelum pengguna menekan Setujui. "
        "Isian wajib: `judul` dan `waktu` (jam dinding WIB, format YYYY-MM-DDTHH:MM). "
        "jenis='pribadi' (bawaan): pengingat pribadi milik pengguna yang bertanya, sama dengan Portal Saya › Ruang "
        "Kerja › Pengingat; `waktu` = kapan diingatkan, `ulang` sekali/harian/mingguan. jenis='vendor': pengingat "
        "produksi ke vendor CMT (tampil di Portal CMT vendor itu), wajib juga `vendor` (id atau nama vendor CMT) "
        "dan `keterangan` (isi pesan); `waktu` = batas tindak lanjut yang ditulis di pesan; hanya untuk peran "
        "admin produksi/PPIC/supervisor produksi/admin. Pembatalan: pengingat pribadi dihapus; pengingat vendor "
        "hanya bisa ditarik admin. Satu panggilan = satu pengingat."),
    input_schema={
        "type": "object",
        "properties": {
            "jenis": {"type": "string", "enum": ["pribadi", "vendor"],
                      "description": "pribadi (bawaan) atau vendor (pengingat produksi ke vendor CMT)."},
            "judul": {"type": "string", "minLength": 2, "maxLength": 120, "description": "Judul singkat."},
            "keterangan": {"type": "string", "maxLength": 1000, "description": "Isi/rincian pengingat."},
            "waktu": {"type": "string", "pattern": _WAKTU_RX,
                      "description": "Jam dinding WIB YYYY-MM-DDTHH:MM. Pribadi: kapan diingatkan; vendor: batas "
                                     "tindak lanjut."},
            "ulang": {"type": "string", "enum": list(_ULANG), "description": "Pengingat pribadi: pengulangan."},
            "vendor": {"type": "string", "maxLength": 120, "description": "Pengingat vendor: id atau nama vendor CMT."},
            "nomor_po": {"type": "string", "maxLength": 60, "description": "Pengingat vendor: nomor PO terkait (opsional)."},
            "prioritas": {"type": "string", "enum": list(_PRIORITAS_VENDOR),
                          "description": "Pengingat vendor: prioritas (bawaan biasa)."},
        },
        "required": ["judul", "waktu"],
        "additionalProperties": False,
    },
    domain="umum",
    risiko="rendah",
    menu="portal-workspace",
)
class BuatPengingat:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        a = _bersih_args(args)
        jenis = a.get("jenis") or "pribadi"
        judul = _teks(a.get("judul"), 120)
        if len(judul) < 2:
            raise AlatError(400, "Judul pengingat wajib diisi.")
        if jenis == "vendor":
            return await BuatPengingat._siapkan_vendor(ctx, a, judul)
        for k in ("vendor", "nomor_po", "prioritas"):
            if k in a:
                raise AlatError(400, f"Isian '{k}' hanya untuk pengingat vendor (jenis='vendor').")
        waktu = a.get("waktu")
        dt = _waktu_sah(waktu)
        ulang = a.get("ulang") or "sekali"
        peringatan = []
        if dt.date() < _hari_ini(ctx):
            peringatan.append("Waktunya sudah lewat — pengingat akan langsung muncul sebagai jatuh tempo.")
        lama = await ctx.api("GET", "/api/portal/reminders", params={"limit": 200})
        kembar = [r for r in (lama or {}).get("items") or []
                  if _teks(r.get("title"), 120).lower() == judul.lower() and r.get("remind_at") == waktu]
        if kembar:
            peringatan.append("Sudah ada pengingat aktif dengan judul dan waktu yang sama.")
        perubahan = [{"label": "Pengingat", "sebelum": _KOSONG, "sesudah": judul},
                     {"label": "Waktu", "sebelum": _KOSONG, "sesudah": _waktu(waktu)},
                     {"label": "Pengulangan", "sebelum": _KOSONG, "sesudah": _ULANG_LABEL[ulang]}]
        if a.get("keterangan"):
            perubahan.append({"label": "Keterangan", "sebelum": _KOSONG, "sesudah": _teks(a["keterangan"], 200)})
        ubah = [{"kunci": "judul", "label": "Judul", "jenis": "teks", "nilai": judul},
                {"kunci": "waktu", "label": "Waktu (YYYY-MM-DDTHH:MM, WIB)", "jenis": "teks", "nilai": waktu}]
        if "ulang" in a:
            ubah.append({"kunci": "ulang", "label": "Pengulangan", "jenis": "pilihan", "nilai": ulang,
                         "pilihan": [{"nilai": k, "label": v} for k, v in _ULANG_LABEL.items()]})
        return {"judul": "Buat pengingat pribadi", "ringkas": f"{judul} — {_waktu(waktu)}.",
                "perubahan": perubahan,
                "catatan": ["Pengingat ini hanya terlihat oleh Anda di Portal Saya › Ruang Kerja."],
                "peringatan": peringatan, "ubah": ubah,
                "tautan": {"label": "Buka Ruang Kerja", "menu": "portal-workspace"}}

    @staticmethod
    async def _siapkan_vendor(ctx, a: dict, judul: str) -> dict:
        from routes.operations_reminders import VENDOR_REMINDER_DELETE_ROLES, VENDOR_REMINDER_WRITER_ROLES
        if "ulang" in a:
            raise AlatError(400, "Isian 'ulang' hanya untuk pengingat pribadi.")
        if not _boleh(ctx, VENDOR_REMINDER_WRITER_ROLES):
            raise AlatError(403, "Pengingat ke vendor CMT hanya boleh dikirim admin produksi, PPIC, supervisor "
                                 "produksi, atau admin. Akun ini tidak punya hak itu.")
        if not a.get("vendor"):
            raise AlatError(400, "Pengingat vendor butuh nama atau id vendor CMT.")
        if not (a.get("keterangan") or "").strip():
            raise AlatError(400, "Pengingat vendor butuh isi pesan (keterangan).")
        if _waktu_sah(a.get("waktu")).date() < _hari_ini(ctx):
            raise AlatError(400, "Batas tindak lanjut untuk vendor sudah lewat. Pakai waktu yang akan datang.")
        v = await _cari_vendor(ctx, a["vendor"])
        prio = a.get("prioritas") or "biasa"
        perubahan = [{"label": "Vendor CMT", "sebelum": _KOSONG, "sesudah": v.get("garment_name") or v["id"]},
                     {"label": "Judul", "sebelum": _KOSONG, "sesudah": judul},
                     {"label": "Pesan", "sebelum": _KOSONG, "sesudah": _teks(_pesan_vendor(a), 300)},
                     {"label": "Prioritas", "sebelum": _KOSONG, "sesudah": prio.capitalize()}]
        if a.get("nomor_po"):
            perubahan.append({"label": "PO terkait", "sebelum": _KOSONG, "sesudah": _teks(a["nomor_po"], 60)})
        catatan = ["Pengingat langsung tampil di Portal CMT vendor ini dan menunggu balasan vendor."]
        if not _boleh(ctx, VENDOR_REMINDER_DELETE_ROLES):
            catatan.append("Setelah terkirim, pengingat vendor hanya bisa ditarik admin.")
        return {"judul": "Kirim pengingat ke vendor CMT",
                "ringkas": f"{judul} → {v.get('garment_name') or 'vendor'}.",
                "perubahan": perubahan, "catatan": catatan, "peringatan": [],
                "ubah": [{"kunci": "judul", "label": "Judul", "jenis": "teks", "nilai": judul},
                         {"kunci": "keterangan", "label": "Pesan", "jenis": "teks", "nilai": a["keterangan"]},
                         {"kunci": "waktu", "label": "Batas tindak lanjut (YYYY-MM-DDTHH:MM, WIB)", "jenis": "teks",
                          "nilai": a["waktu"]}],
                "tautan": {"label": "Buka Portal CMT (mode staf)", "menu": "cmt-override-portal"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        a = _bersih_args(args)
        if (a.get("jenis") or "pribadi") == "vendor":
            from routes.operations_reminders import VENDOR_REMINDER_DELETE_ROLES
            v = await _cari_vendor(ctx, a["vendor"])
            out = await ctx.api("POST", "/api/reminders", json={
                "vendor_id": v["id"], "po_number": a.get("nomor_po") or "", "reminder_type": "general",
                "subject": _teks(a["judul"], 120), "message": _pesan_vendor(a),
                "priority": _PRIORITAS_VENDOR[a.get("prioritas") or "biasa"]})
            rid = (out or {}).get("id")
            if not rid:
                raise AlatError(502, "Sistem tidak mengembalikan nomor pengingat vendor. Periksa Portal CMT.")
            batal = {"jenis": "vendor", "id": rid} if _boleh(ctx, VENDOR_REMINDER_DELETE_ROLES) else None
            return {"ringkas": f"Pengingat terkirim ke vendor {v.get('garment_name') or ''}.".replace("  ", " "),
                    "hasil": {"pengingat_vendor_id": rid, "vendor_id": v["id"]}, "pembatalan": batal}
        out = await ctx.api("POST", "/api/portal/reminders", json={
            "title": _teks(a["judul"], 120), "description": a.get("keterangan") or "",
            "remind_at": a["waktu"], "recurrence": _ULANG[a.get("ulang") or "sekali"]})
        rid = (out or {}).get("id")
        if not rid:
            raise AlatError(502, "Sistem tidak mengembalikan nomor pengingat. Periksa Ruang Kerja.")
        return {"ringkas": f"Pengingat \"{_teks(a['judul'], 80)}\" tersimpan untuk {_waktu(a['waktu'])}.",
                "hasil": {"pengingat_id": rid}, "pembatalan": {"jenis": "pribadi", "id": rid}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        rid = str((pembatalan or {}).get("id") or "")
        if not rid:
            raise AlatError(400, "Data pembatalan pengingat tidak lengkap.")
        path = "/api/reminders/" if pembatalan.get("jenis") == "vendor" else "/api/portal/reminders/"
        try:
            await ctx.api("DELETE", path + rid)
        except AlatError as e:
            if e.status == 404:
                return {"ringkas": "Pengingat sudah tidak ada (sudah dihapus sebelumnya)."}
            if e.status == 403:
                raise AlatError(403, "Akun ini tidak boleh menghapus pengingat tersebut "
                                     "(pengingat vendor hanya bisa ditarik admin).") from None
            raise
        return {"ringkas": "Pengingat dihapus."}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 2–3. OKR
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_JENIS_KR = {"angka": "number", "persen": "percentage", "rupiah": "currency", "ya_tidak": "binary"}
_PRIORITAS_OKR = {"rendah": "low", "sedang": "medium", "tinggi": "high", "kritis": "critical"}
_OKR = "/api/management/okr"


def _nilai_kr(kr: dict, v: Any) -> str:
    mt = str(kr.get("metric_type") or "number")
    if mt == "currency":
        return _rp(v)
    if mt == "percentage":
        return _persen(v)
    if mt == "binary":
        try:
            return "Selesai" if float(v or 0) > 0 else "Belum"
        except (TypeError, ValueError):
            return _KOSONG
    sat = str(kr.get("unit") or "").strip()
    return f"{_angka(v)} {sat}".strip()


def _progres_kr(kr: dict, cur: Any = None) -> float:
    """Rumus yang SAMA dengan `routes.dewi_okr._kr_progress` (dipanggil langsung; murni, tanpa DB)."""
    from routes.dewi_okr import _kr_progress
    k = dict(kr)
    if cur is not None:
        k["current_value"] = cur
    return float(_kr_progress(k))


async def _cari_kr(ctx, kr_id: str, objective_id: Optional[str] = None) -> tuple[dict, dict]:
    kr_id = str(kr_id or "").strip()
    if objective_id:
        obj = ((await ctx.api("GET", f"{_OKR}/objectives/{objective_id}")) or {}).get("data") or {}
        objs = [obj] if obj else []
    else:
        objs = ((await ctx.api("GET", f"{_OKR}/objectives",
                               params={"include_key_results": True, "limit": 1000})) or {}).get("data") or []
    for o in objs:
        for kr in o.get("key_results") or []:
            if kr.get("id") == kr_id:
                return o, kr
    raise AlatError(404, "Key result tidak ditemukan di objektif yang aktif. Baca daftar OKR dulu "
                         "(alat daftar_okr) lalu pakai id key result yang benar.")


@tindakan(
    name="buat_objektif_okr",
    label="Menyiapkan objektif OKR",
    description=(
        "Menyiapkan kartu untuk MEMBUAT satu objektif OKR beserta key result-nya, sama dengan layar OKR Tracker "
        "(Portal Manajemen). Tidak ada yang tersimpan sebelum pengguna menekan Setujui. Hanya owner, manajer, "
        "admin, dan superadmin yang boleh membuat objektif. `periode` contoh 2026-Q4, 2026-H2, atau 2026. "
        "Setiap key result: judul, jenis (angka/persen/rupiah/ya_tidak), target, nilai_awal (bawaan 0), "
        "satuan (untuk angka, mis. pcs). Pembatalan = objektif diarsipkan (seperti tombol Arsipkan)."),
    input_schema={
        "type": "object",
        "properties": {
            "judul": {"type": "string", "minLength": 3, "maxLength": 160},
            "deskripsi": {"type": "string", "maxLength": 1000},
            "periode": {"type": "string", "pattern": r"^\d{4}(-Q[1-4]|-H[12])?$",
                        "description": "Periode OKR: YYYY-Q1..Q4, YYYY-H1/H2, atau YYYY."},
            "departemen": {"type": "string", "maxLength": 80},
            "pemilik": {"type": "string", "maxLength": 120,
                        "description": "Nama, email, atau id pengguna penanggung jawab (opsional)."},
            "prioritas": {"type": "string", "enum": list(_PRIORITAS_OKR)},
            "key_results": {
                "type": "array", "minItems": 1, "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "judul": {"type": "string", "minLength": 3, "maxLength": 160},
                        "jenis": {"type": "string", "enum": list(_JENIS_KR)},
                        "target": {"type": "number", "minimum": 0},
                        "nilai_awal": {"type": "number", "minimum": 0},
                        "satuan": {"type": "string", "maxLength": 20},
                    },
                    "required": ["judul", "jenis", "target"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["judul", "periode", "key_results"],
        "additionalProperties": False,
    },
    domain="umum",
    risiko="rendah",
    menu="mgmt-okr",
)
class BuatObjektifOkr:
    @staticmethod
    async def _pemilik(ctx, kunci: Optional[str]) -> Optional[dict]:
        if not kunci:
            return None
        return (await _cari_pengguna(ctx, [kunci]))[0]

    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        from routes.dewi_okr import can_write_objective
        a = _bersih_args(args)
        if not can_write_objective(getattr(ctx, "user", None)):
            raise AlatError(403, "Objektif OKR hanya boleh dibuat owner, manajer, atau admin. "
                                 "Akun ini tidak punya hak itu.")
        await _wajib_gerbang(ctx, "POST", f"{_OKR}/objectives")
        pemilik = await BuatObjektifOkr._pemilik(ctx, a.get("pemilik"))
        ada = ((await ctx.api("GET", f"{_OKR}/objectives",
                              params={"period": a["periode"], "include_key_results": False})) or {}).get("data") or []
        peringatan = []
        if any(_teks(o.get("title"), 160).lower() == _teks(a["judul"], 160).lower() for o in ada):
            peringatan.append(f"Sudah ada objektif berjudul sama di periode {a['periode']}.")
        perubahan = [{"label": "Objektif", "sebelum": _KOSONG, "sesudah": _teks(a["judul"], 160)},
                     {"label": "Periode", "sebelum": _KOSONG, "sesudah": a["periode"]},
                     {"label": "Prioritas", "sebelum": _KOSONG,
                      "sesudah": (a.get("prioritas") or "sedang").capitalize()}]
        if a.get("departemen"):
            perubahan.append({"label": "Departemen", "sebelum": _KOSONG, "sesudah": _teks(a["departemen"], 80)})
        if pemilik:
            perubahan.append({"label": "Penanggung jawab", "sebelum": _KOSONG, "sesudah": pemilik["name"]})
        for i, kr in enumerate(a["key_results"], 1):
            k = {"metric_type": _JENIS_KR[kr["jenis"]], "unit": kr.get("satuan")}
            if kr["jenis"] == "ya_tidak":
                tgt = "selesai/belum"
            else:
                tgt = f"target {_nilai_kr(k, kr['target'])}, awal {_nilai_kr(k, kr.get('nilai_awal') or 0)}"
            perubahan.append({"label": f"Key result {i}: {_teks(kr['judul'], 100)}", "sebelum": _KOSONG,
                              "sesudah": tgt})
        return {"judul": f"Buat objektif OKR {a['periode']}",
                "ringkas": f"{_teks(a['judul'], 120)} dengan {len(a['key_results'])} key result.",
                "perubahan": perubahan, "catatan": ["Progres objektif dihitung otomatis dari key result."],
                "peringatan": peringatan,
                "ubah": [{"kunci": "judul", "label": "Judul objektif", "jenis": "teks", "nilai": a["judul"]}]
                + [{"kunci": f"key_results.{i}.target", "label": f"Target key result {i + 1}",
                    "jenis": "rupiah" if kr["jenis"] == "rupiah" else "angka", "nilai": kr["target"]}
                   for i, kr in enumerate(a["key_results"]) if kr["jenis"] != "ya_tidak"],
                "tautan": {"label": "Buka OKR Tracker", "menu": "mgmt-okr"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        a = _bersih_args(args)
        pemilik = await BuatObjektifOkr._pemilik(ctx, a.get("pemilik"))
        body = {"title": a["judul"].strip(), "description": a.get("deskripsi"), "period": a["periode"],
                "department": a.get("departemen"), "priority": _PRIORITAS_OKR[a.get("prioritas") or "sedang"],
                "owner_id": (pemilik or {}).get("id"), "owner_name": (pemilik or {}).get("name"),
                "key_results": [{"title": kr["judul"].strip(), "metric_type": _JENIS_KR[kr["jenis"]],
                                 "target_value": float(kr["target"]),
                                 "current_value": float(kr.get("nilai_awal") or 0),
                                 "unit": kr.get("satuan")} for kr in a["key_results"]]}
        out = ((await ctx.api("POST", f"{_OKR}/objectives", json=body)) or {}).get("data") or {}
        oid = out.get("id")
        if not oid:
            raise AlatError(502, "Sistem tidak mengembalikan nomor objektif. Periksa OKR Tracker.")
        return {"ringkas": f"Objektif \"{_teks(a['judul'], 80)}\" ({a['periode']}) dibuat dengan "
                           f"{len(out.get('key_results') or [])} key result.",
                "hasil": {"objective_id": oid, "key_result_ids": [k.get("id") for k in out.get("key_results") or []]},
                "pembatalan": {"objective_id": oid}}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        oid = str((pembatalan or {}).get("objective_id") or "")
        if not oid:
            raise AlatError(400, "Data pembatalan objektif tidak lengkap.")
        await ctx.api("DELETE", f"{_OKR}/objectives/{oid}")
        return {"ringkas": "Objektif diarsipkan (tidak tampil lagi di OKR Tracker)."}


@tindakan(
    name="perbarui_key_result",
    label="Menyiapkan pembaruan key result",
    description=(
        "Menyiapkan kartu untuk MENGUBAH nilai capaian (current value) satu key result OKR, sama dengan layar OKR "
        "Tracker. Kartu menampilkan nilai lama → baru dan progres lama → baru. Tidak ada yang tersimpan sebelum "
        "pengguna menekan Setujui. Ambil `key_result_id` dari alat daftar_okr. Pembatalan = nilai lama dipasang "
        "kembali."),
    input_schema={
        "type": "object",
        "properties": {
            "key_result_id": {"type": "string", "minLength": 3, "maxLength": 64},
            "objective_id": {"type": "string", "maxLength": 64, "description": "Opsional, mempercepat pencarian."},
            "nilai": {"type": "number", "minimum": 0, "description": "Nilai capaian baru."},
            "catatan": {"type": "string", "maxLength": 500},
        },
        "required": ["key_result_id", "nilai"],
        "additionalProperties": False,
    },
    domain="umum",
    risiko="rendah",
    menu="mgmt-okr",
)
class PerbaruiKeyResult:
    @staticmethod
    def _perubahan(obj: dict, kr: dict, nilai: float, catatan: Optional[str]) -> list:
        from routes.dewi_okr import _objective_progress
        krs = obj.get("key_results") or []
        baru = [dict(k, current_value=nilai) if k.get("id") == kr.get("id") else k for k in krs]
        rows = [{"label": _teks(kr.get("title"), 120), "sebelum": _nilai_kr(kr, kr.get("current_value") or 0),
                 "sesudah": _nilai_kr(kr, nilai)},
                {"label": "Progres key result", "sebelum": _persen(_progres_kr(kr)),
                 "sesudah": _persen(_progres_kr(kr, nilai))},
                {"label": f"Progres objektif: {_teks(obj.get('title'), 80)}",
                 "sebelum": _persen(_objective_progress(krs)), "sesudah": _persen(_objective_progress(baru))}]
        if catatan is not None:
            rows.append({"label": "Catatan", "sebelum": _teks(kr.get("notes"), 200) or _KOSONG,
                         "sesudah": _teks(catatan, 200) or _KOSONG})
        return rows

    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        a = _bersih_args(args)
        obj, kr = await _cari_kr(ctx, a["key_result_id"], a.get("objective_id"))
        await _wajib_gerbang(ctx, "PATCH", f"{_OKR}/key-results/{kr['id']}")
        if obj.get("status") in ("archived", "completed"):
            raise AlatError(409, "Objektif ini sudah selesai/diarsipkan; key result-nya tidak diubah lewat AI.")
        nilai = float(a["nilai"])
        if abs(nilai - float(kr.get("current_value") or 0)) < 1e-9 and "catatan" not in a:
            raise AlatError(400, "Nilai baru sama dengan nilai sekarang; tidak ada yang perlu diubah.")
        target = float(kr.get("target_value") or 0)
        peringatan = []
        if target > 0 and nilai > target * 2:
            peringatan.append("Nilai baru lebih dari dua kali target — periksa lagi angkanya.")
        if nilai < float(kr.get("current_value") or 0):
            peringatan.append("Nilai baru LEBIH KECIL dari nilai sekarang (capaian turun).")
        return {"judul": "Perbarui capaian key result",
                "ringkas": f"{_teks(kr.get('title'), 100)}: {_nilai_kr(kr, kr.get('current_value') or 0)} → "
                           f"{_nilai_kr(kr, nilai)} (target {_nilai_kr(kr, target)}).",
                "perubahan": PerbaruiKeyResult._perubahan(obj, kr, nilai, a.get("catatan")),
                "catatan": [f"Periode {obj.get('period') or _KOSONG}."], "peringatan": peringatan,
                "ubah": [{"kunci": "nilai", "label": "Nilai capaian baru",
                          "jenis": "rupiah" if kr.get("metric_type") == "currency" else "angka", "nilai": nilai}],
                "tautan": {"label": "Buka OKR Tracker", "menu": "mgmt-okr"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        a = _bersih_args(args)
        obj, kr = await _cari_kr(ctx, a["key_result_id"], a.get("objective_id"))
        # Nilai yang ditampilkan di kartu harus masih nilai sekarang (orang lain bisa mengubahnya sejak kartu dibuat).
        di_kartu = next((p.get("sebelum") for p in (rencana or {}).get("perubahan") or []
                         if p.get("label") == _teks(kr.get("title"), 120)), None)
        sekarang = _nilai_kr(kr, kr.get("current_value") or 0)
        if di_kartu is not None and di_kartu != sekarang:
            raise AlatError(409, f"Nilai key result sudah berubah sejak kartu disiapkan ({di_kartu} → {sekarang}). "
                                 "Tidak ada yang diubah; minta kartu baru.")
        body = {"current_value": float(a["nilai"])}
        if "catatan" in a:
            body["notes"] = a["catatan"]
        await ctx.api("PATCH", f"{_OKR}/key-results/{kr['id']}", json=body)
        batal = {"key_result_id": kr["id"], "objective_id": obj.get("id"),
                 "current_value": float(kr.get("current_value") or 0)}
        if "catatan" in a:
            batal["notes"] = kr.get("notes") or ""
        return {"ringkas": f"Capaian \"{_teks(kr.get('title'), 80)}\" kini {_nilai_kr(kr, a['nilai'])} "
                           f"(progres {_persen(_progres_kr(kr, a['nilai']))}).",
                "hasil": {"key_result_id": kr["id"], "objective_id": obj.get("id")},
                "pembatalan": batal}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        p = pembatalan or {}
        if not p.get("key_result_id") or "current_value" not in p:
            raise AlatError(400, "Data pembatalan key result tidak lengkap.")
        body = {"current_value": float(p["current_value"])}
        if "notes" in p:
            # endpoint mengabaikan None; catatan lama yang kosong dipulihkan sebagai teks kosong
            body["notes"] = p["notes"] or ""
        await ctx.api("PATCH", f"{_OKR}/key-results/{p['key_result_id']}", json=body)
        return {"ringkas": f"Nilai key result dikembalikan ke {_angka(p['current_value'])}."}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 4. Draf permintaan pembelian dari Daftar Belanja Mingguan
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_PRIORITAS_PR = {"rendah": "low", "sedang": "medium", "tinggi": "high", "mendesak": "urgent"}
_BARIS_KARTU = 25


async def _baris_belanja(ctx, a: dict) -> tuple[list, list, dict]:
    """Baris Daftar Belanja Mingguan yang dipilih (angka SAMA dengan layar) + yang dilewati + ringkasan."""
    data = await ctx.api("GET", "/api/rahaza/shopping-list/weekly",
                         params={"type": a.get("kelompok") or "", "include_requested": True})
    rows = [r for r in (data or {}).get("rows") or [] if isinstance(r, dict) and r.get("material_id")]
    ids = [str(x) for x in a.get("material_ids") or []]
    kode = [str(x).strip().lower() for x in a.get("kode_barang") or []]
    if ids or kode:
        pilih, lewat = [], []
        by_id = {r["material_id"]: r for r in rows}
        by_kode = {str(r.get("code") or "").strip().lower(): r for r in rows if r.get("code")}
        for k in ids:
            if k in by_id:
                pilih.append(by_id[k])
            else:
                lewat.append(f"{k}: tidak ada di daftar belanja minggu ini")
        for k in kode:
            r = by_kode.get(k)
            if r is None:
                lewat.append(f"{k.upper()}: tidak ada di daftar belanja minggu ini")
            elif r not in pilih:
                pilih.append(r)
    else:
        pilih, lewat = list(rows), []
    hasil = []
    for r in pilih:
        if r.get("already_requested"):
            lbl = (r.get("pr") or {}).get("label") or "PR/PO terbuka"
            lewat.append(f"{r.get('code') or r['material_id']}: sudah ada {lbl} (anti dobel belanja)")
        else:
            hasil.append(r)
    return hasil, lewat, (data or {}).get("summary") or {}


@tindakan(
    name="buat_draf_pr",
    label="Menyiapkan draf permintaan pembelian",
    description=(
        "Menyiapkan kartu untuk membuat DRAF Permintaan Pengadaan (PR) dari Daftar Belanja Mingguan — jalur yang "
        "sama dengan tombol 'Jadikan PR' di layar Belanja Mingguan: qty beli, satuan beli, dan perkiraan harga "
        "diambil dari daftar itu (basis ambang minimum stok), barang yang sudah punya PR/PO terbuka dilewati. "
        "Tidak ada yang tersimpan sebelum pengguna menekan Setujui. PR berstatus DRAF dan TIDAK diajukan ke "
        "persetujuan; pengguna mengajukannya sendiri di Portal Pengadaan. "
        "Tanpa material_ids/kode_barang = semua barang yang perlu dibeli minggu ini (maks. 200). `kelompok` "
        "menyaring jenis: bahan, aksesoris. Pembatalan = draf dihapus (selama masih draf)."),
    input_schema={
        "type": "object",
        "properties": {
            "material_ids": {"type": "array", "maxItems": 200, "items": {"type": "string", "maxLength": 64}},
            "kode_barang": {"type": "array", "maxItems": 200, "items": {"type": "string", "maxLength": 64}},
            "kelompok": {"type": "string", "enum": ["bahan", "aksesoris"]},
            "judul": {"type": "string", "maxLength": 160},
            "catatan": {"type": "string", "maxLength": 1000},
            "dibutuhkan_tanggal": {"type": "string", "pattern": _TANGGAL_RX},
            "prioritas": {"type": "string", "enum": list(_PRIORITAS_PR)},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="stok",
    risiko="rendah",
    menu="wh-shopping-list",
)
class BuatDrafPr:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        a = _bersih_args(args)
        if str(getattr(ctx, "cv", "") or "").upper() == "ALL":
            # Kontrak inti: tulis dengan CV Gabungan dikirim tanpa X-CV → pembelian harus atas nama satu CV.
            raise AlatError(400, "Pilihan CV sedang Gabungan. Pilih CV Dewi Aditya (atau CV yang membeli) di "
                                 "pemilih CV, lalu minta draf PR lagi.")
        await _wajib_gerbang(ctx, "POST", "/api/rahaza/shopping-list/create-pr")
        baris, lewat, ring = await _baris_belanja(ctx, a)
        if not baris:
            alasan = ("; ".join(lewat[:5])) if lewat else "tidak ada barang yang menyentuh ambang minimum minggu ini"
            raise AlatError(409, f"Tidak ada barang yang bisa dimasukkan ke draf PR — {alasan}.")
        if len(baris) > 200:
            raise AlatError(400, f"Ada {len(baris)} barang; satu PR maksimal 200 barang. Saring dengan kelompok "
                                 "atau kode_barang.")
        if a.get("dibutuhkan_tanggal") and a["dibutuhkan_tanggal"] < _hari_ini(ctx).isoformat():
            raise AlatError(400, "Tanggal dibutuhkan sudah lewat.")
        total = sum(float(r.get("est_total") or 0) for r in baris if r.get("valued"))
        tanpa_harga = [r for r in baris if not r.get("valued")]
        perubahan = []
        for r in baris[:_BARIS_KARTU]:
            harga = _rp(r.get("est_total")) if r.get("valued") else "belum ada harga"
            perubahan.append({"label": _teks(f"{r.get('code') or ''} {r.get('name') or ''}".strip(), 90),
                              "sebelum": f"stok {_angka(r.get('onhand'))} {r.get('base_uom') or ''}".strip(),
                              "sesudah": f"beli {_angka(r.get('qty_buy'))} {r.get('purchase_uom') or ''} · {harga}"})
        if len(baris) > _BARIS_KARTU:
            sisa = baris[_BARIS_KARTU:]
            perubahan.append({"label": f"…dan {len(sisa)} barang lain", "sebelum": _KOSONG,
                              "sesudah": _rp(sum(float(r.get('est_total') or 0) for r in sisa if r.get("valued")))})
        perubahan.append({"label": "Perkiraan total", "sebelum": _KOSONG, "sesudah": _rp(total)})
        catatan = ["PR disimpan sebagai DRAF dan belum diajukan. Ajukan sendiri lewat Portal Pengadaan › "
                   "Permintaan Pengadaan setelah diperiksa.",
                   f"Minggu {ring.get('week_label') or ring.get('week') or 'ini'}; kebutuhan dari ambang minimum stok.",
                   f"Pilihan CV saat ini: {_nama_cv(ctx)}."]
        if await _gerbang_tulis(ctx, "DELETE", "/api/procurement/requests/x"):
            catatan.append("Akun ini tidak punya akses Portal Pengadaan, jadi draf tidak bisa dihapus lewat "
                           "Asisten AI; penghapusan lewat admin/owner.")
        if ring.get("without_threshold"):
            catatan.append(f"{ring['without_threshold']} barang belum punya ambang minimum, jadi tidak ikut dinilai.")
        peringatan = [f"{len(lewat)} barang dilewati: " + "; ".join(lewat[:4])] if lewat else []
        if tanpa_harga:
            peringatan.append(f"{len(tanpa_harga)} barang belum punya harga dan tidak dihitung ke perkiraan total.")
        ubah = []
        if "dibutuhkan_tanggal" in a:
            ubah.append({"kunci": "dibutuhkan_tanggal", "label": "Dibutuhkan tanggal", "jenis": "tanggal",
                         "nilai": a["dibutuhkan_tanggal"]})
        if "judul" in a:
            ubah.append({"kunci": "judul", "label": "Judul PR", "jenis": "teks", "nilai": a["judul"]})
        return {"judul": "Buat draf permintaan pembelian",
                "ringkas": f"{len(baris)} barang dari Daftar Belanja Mingguan, perkiraan {_rp(total)}.",
                "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
                "tautan": {"label": "Buka Belanja Mingguan", "menu": "wh-shopping-list"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        a = _bersih_args(args)
        baris, _lewat, _ring = await _baris_belanja(ctx, a)
        if not baris:
            raise AlatError(409, "Barang di kartu sudah tidak perlu dibeli (stok cukup atau sudah ada PR/PO). "
                                 "Tidak ada PR yang dibuat.")
        body = {"material_ids": [r["material_id"] for r in baris][:200],
                "priority": _PRIORITAS_PR[a.get("prioritas") or "sedang"]}
        if a.get("judul"):
            body["title"] = a["judul"]
        if a.get("catatan"):
            body["notes"] = a["catatan"]
        if a.get("dibutuhkan_tanggal"):
            body["needed_by"] = a["dibutuhkan_tanggal"]
        out = await ctx.api("POST", "/api/rahaza/shopping-list/create-pr", json=body)
        req = (out or {}).get("request") or {}
        if not req.get("id"):
            raise AlatError(502, "Sistem tidak mengembalikan nomor PR. Periksa Portal Pengadaan.")
        if req.get("status") != "draft":  # penjaga kontrak: alat ini TIDAK PERNAH mengajukan PR
            log.error("buat_draf_pr: PR %s lahir berstatus %r", req.get("request_number"), req.get("status"))
        n = len(req.get("items") or [])
        # Pembatalan = hapus draf; hanya ditawarkan bila gerbang modul Pengadaan mengizinkan akun ini menghapus.
        bisa_hapus = not await _gerbang_tulis(ctx, "DELETE", f"/api/procurement/requests/{req['id']}")
        return {"ringkas": f"Draf PR {req.get('request_number') or ''} dibuat ({n} barang, perkiraan "
                           f"{_rp(req.get('total_estimated'))}); belum diajukan.",
                "hasil": {"pr_id": req["id"], "nomor": req.get("request_number"), "jumlah_barang": n,
                          "dilewati": len((out or {}).get("skipped") or [])},
                "pembatalan": {"pr_id": req["id"], "nomor": req.get("request_number")} if bisa_hapus else None}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        pid = str((pembatalan or {}).get("pr_id") or "")
        if not pid:
            raise AlatError(400, "Data pembatalan PR tidak lengkap.")
        try:
            pr = await ctx.api("GET", f"/api/procurement/requests/{pid}")
        except AlatError as e:
            if e.status == 404:
                return {"ringkas": "Draf PR sudah tidak ada (sudah dihapus sebelumnya)."}
            raise
        if (pr or {}).get("status") != "draft":
            raise AlatError(409, f"PR {pembatalan.get('nomor') or ''} sudah tidak berstatus draf "
                                 f"({(pr or {}).get('status')}); batalkan lewat Portal Pengadaan.")
        await ctx.api("DELETE", f"/api/procurement/requests/{pid}")
        return {"ringkas": f"Draf PR {pembatalan.get('nomor') or ''} dihapus.".replace("  ", " ")}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 5. Jadwal laporan — satu-satunya fitur jadwal laporan yang ada: rapor valuasi aksesoris bulanan via email
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_JADWAL = "/api/acc/valuation/report-schedule"


def _email_bersih(daftar) -> list[str]:
    out = []
    for e in daftar or []:
        e = str(e or "").strip()
        if not _EMAIL_RX.match(e):
            raise AlatError(400, f"Alamat email tidak sah: {_teks(e, 80)}")
        if e.lower() not in [x.lower() for x in out]:
            out.append(e)
    return out


def _rencana_jadwal(cfg: dict, a: dict) -> tuple[bool, list[str], list[str]]:
    lama = list(cfg.get("extra_emails") or [])
    tambah = _email_bersih(a.get("email_tambah"))
    hapus = {e.lower() for e in _email_bersih(a.get("email_hapus"))}
    baru = [e for e in lama if e.lower() not in hapus]
    tambahan_baru = []
    for e in tambah:
        if e.lower() not in [x.lower() for x in baru]:
            baru.append(e)
            tambahan_baru.append(e)
    aktif = bool(a["aktif"]) if "aktif" in a else bool(cfg.get("enabled", True))
    return aktif, baru, tambahan_baru


@tindakan(
    name="jadwalkan_laporan",
    label="Menyiapkan jadwal laporan",
    description=(
        "Menyiapkan kartu untuk mengatur jadwal laporan otomatis yang ADA di sistem: rapor valuasi persediaan "
        "aksesoris bulanan (dikirim email setiap tanggal 1 pukul 06.00 WIB, lampiran Excel + PDF, ke akun "
        "keuangan + email tambahan) — sama dengan layar Aksesoris › Valuasi HPP › Otomasi. Bisa mengaktifkan/"
        "mematikan jadwal (`aktif`) dan menambah/menghapus email tambahan; tidak ada yang berubah sebelum "
        "pengguna menekan Setujui. Hanya Admin Gudang, Supervisor, "
        "Keuangan, atau Owner. Jadwal laporan lain (mis. laporan penjualan mingguan) BELUM ada di sistem — "
        "jangan janjikan. Pembatalan = setelan lama dipasang kembali."),
    input_schema={
        "type": "object",
        "properties": {
            "laporan": {"type": "string", "enum": ["valuasi_aksesoris_bulanan"]},
            "aktif": {"type": "boolean", "description": "true = kirim otomatis tiap bulan; false = berhenti."},
            "email_tambah": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 120}},
            "email_hapus": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 120}},
        },
        "required": ["laporan"],
        "additionalProperties": False,
    },
    domain="laporan",
    risiko="rendah",
    menu="wh-accessory",
)
class JadwalkanLaporan:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        from core.stock_rbac import SCRAP_ROLES
        a = _bersih_args(args)
        if not _boleh(ctx, SCRAP_ROLES, "inv.stock.manage"):
            raise AlatError(403, "Jadwal rapor valuasi hanya boleh diatur Admin Gudang, Supervisor, Keuangan, "
                                 "atau Owner. Akun ini tidak punya hak itu.")
        await _wajib_gerbang(ctx, "PUT", _JADWAL)
        if not any(k in a for k in ("aktif", "email_tambah", "email_hapus")):
            raise AlatError(400, "Sebutkan perubahannya: aktif/nonaktif, email_tambah, atau email_hapus.")
        cfg = await ctx.api("GET", _JADWAL) or {}
        aktif, baru, tambahan_baru = _rencana_jadwal(cfg, a)
        lama = list(cfg.get("extra_emails") or [])
        aktif_lama = bool(cfg.get("enabled", True))
        if aktif == aktif_lama and [e.lower() for e in baru] == [e.lower() for e in lama]:
            raise AlatError(400, "Setelan jadwal sudah seperti itu; tidak ada yang perlu diubah.")
        status = {True: "Aktif", False: "Nonaktif"}
        perubahan = [{"label": "Kirim rapor bulanan otomatis", "sebelum": status[aktif_lama], "sesudah": status[aktif]},
                     {"label": "Email tambahan", "sebelum": ", ".join(lama) or _KOSONG,
                      "sesudah": ", ".join(baru) or _KOSONG}]
        akun = sum(1 for r in cfg.get("recipients") or [] if r.get("source") == "role_keuangan")
        catatan = [f"{cfg.get('schedule_label') or 'Setiap tanggal 1 pukul 06:00'}; penerima tetap: {akun} akun "
                   "keuangan."]
        peringatan = []
        if tambahan_baru:
            peringatan.append("Rapor berisi nilai persediaan aksesoris dan akan dikirim ke alamat baru: "
                              + ", ".join(tambahan_baru) + ". Pastikan alamat ini milik tim Anda.")
        if aktif and not ((cfg.get("smtp") or {}).get("configured")):
            peringatan.append("Pengiriman email belum siap: SMTP belum diatur di Pengaturan Notifikasi.")
        return {"judul": "Atur jadwal rapor valuasi aksesoris",
                "ringkas": f"Jadwal {status[aktif].lower()}, {len(baru)} email tambahan.",
                "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": [],
                "tautan": {"label": "Buka Aksesoris", "menu": "wh-accessory"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        a = _bersih_args(args)
        cfg = await ctx.api("GET", _JADWAL) or {}
        aktif, baru, _t = _rencana_jadwal(cfg, a)
        batal = {"enabled": bool(cfg.get("enabled", True)), "extra_emails": list(cfg.get("extra_emails") or [])}
        out = await ctx.api("PUT", _JADWAL, json={"enabled": aktif, "extra_emails": baru}) or {}
        return {"ringkas": f"Jadwal rapor valuasi aksesoris {'aktif' if out.get('enabled', aktif) else 'nonaktif'}, "
                           f"{len(out.get('extra_emails') or baru)} email tambahan.",
                "hasil": {"aktif": out.get("enabled", aktif), "email_tambahan": len(out.get("extra_emails") or baru)},
                "pembatalan": batal}

    @staticmethod
    async def batalkan(ctx, pembatalan: dict) -> dict:
        p = pembatalan or {}
        if "enabled" not in p:
            raise AlatError(400, "Data pembatalan jadwal tidak lengkap.")
        await ctx.api("PUT", _JADWAL, json={"enabled": bool(p["enabled"]),
                                            "extra_emails": list(p.get("extra_emails") or [])})
        return {"ringkas": "Setelan jadwal rapor valuasi dikembalikan seperti semula."}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 6. Notifikasi dalam aplikasi
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
_BATAS_PENERIMA = 25


def _internal(u: dict) -> bool:
    from core.authz import EXTERNAL_ROLES
    return str(u.get("role") or "").lower() not in EXTERNAL_ROLES and (u.get("status") or "active") == "active"


async def _semua_pengguna(ctx) -> list[dict]:
    rows = await ctx.api("GET", "/api/auth/users", params={"limit": 2000})
    return [u for u in (rows or []) if isinstance(u, dict) and u.get("id") and _internal(u)]


async def _cari_pengguna(ctx, kunci: list, semua: Optional[list] = None) -> list[dict]:
    """Cocokkan id / email / nama (persis lalu sebagian). Ambigu → 409 dengan daftar calon (nama, peran, id)."""
    semua = semua if semua is not None else await _semua_pengguna(ctx)
    out = []
    for k in kunci:
        s = str(k or "").strip()
        sl = s.lower()
        calon = [u for u in semua if u["id"] == s] or \
                [u for u in semua if sl and sl in (str(u.get("email") or "").lower(), str(u.get("name") or "").lower())] or \
                [u for u in semua if sl and sl in str(u.get("name") or "").lower()]
        if not calon:
            raise AlatError(404, f"Pengguna aktif '{_teks(s, 60)}' tidak ditemukan.")
        if len(calon) > 1:
            daftar = "; ".join(f"{u.get('name')} ({u.get('role')}, id {u['id']})" for u in calon[:8])
            raise AlatError(409, f"'{_teks(s, 60)}' cocok dengan {len(calon)} pengguna: {daftar}. "
                                 "Panggil lagi dengan id pengguna yang dimaksud.")
        if calon[0] not in out:
            out.append(calon[0])
    return out


async def _penerima(ctx, a: dict) -> list[dict]:
    semua = await _semua_pengguna(ctx)
    out = await _cari_pengguna(ctx, a.get("penerima") or [], semua) if a.get("penerima") else []
    peran = str(a.get("peran") or "").strip().lower()
    if peran:
        anggota = [u for u in semua if str(u.get("role") or "").lower() == peran]
        if not anggota:
            raise AlatError(404, f"Tidak ada pengguna aktif berperan '{_teks(peran, 40)}'.")
        out += [u for u in anggota if u not in out]
    if not out:
        raise AlatError(400, "Sebutkan penerima (nama/id pengguna) atau peran.")
    if len(out) > _BATAS_PENERIMA:
        raise AlatError(400, f"Penerima {len(out)} orang; satu kartu maksimal {_BATAS_PENERIMA}. Persempit penerimanya.")
    return out


@tindakan(
    name="kirim_notifikasi",
    label="Menyiapkan notifikasi",
    description=(
        "Menyiapkan kartu untuk MENGIRIM notifikasi dalam aplikasi (lonceng ERP) ke pengguna tertentu dan/atau "
        "semua pengguna aktif satu peran; tidak terkirim sebelum pengguna menekan Setujui. Aturan sama dengan "
        "pembuatan notifikasi yang ada: hanya staf internal, penerima harus akun aktif internal, tautan hanya ke "
        "layar aplikasi (`menu` = id layar). Maksimal 25 penerima per kartu. Tidak mengirim WhatsApp/email. "
        "Notifikasi yang sudah terkirim TIDAK bisa ditarik."),
    input_schema={
        "type": "object",
        "properties": {
            "penerima": {"type": "array", "maxItems": 25, "items": {"type": "string", "minLength": 2, "maxLength": 120},
                         "description": "Nama, email, atau id pengguna."},
            "peran": {"type": "string", "maxLength": 40, "description": "Kode peran, mis. hr, manager, admin_gudang."},
            "judul": {"type": "string", "minLength": 3, "maxLength": 120},
            "isi": {"type": "string", "minLength": 3, "maxLength": 1000},
            "menu": {"type": "string", "pattern": _MENU_RX, "description": "Id layar tujuan saat notifikasi diklik."},
        },
        "required": ["judul", "isi"],
        "additionalProperties": False,
    },
    domain="umum",
    risiko="rendah",
)
class KirimNotifikasi:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        from core.authz import EXTERNAL_ROLES
        a = _bersih_args(args)
        if not _peran(ctx) or _peran(ctx) in EXTERNAL_ROLES:
            raise AlatError(403, "Peran akun ini tidak boleh membuat notifikasi.")
        await _wajib_gerbang(ctx, "POST", "/api/collab/notifications")
        orang = await _penerima(ctx, a)
        nama = ", ".join(f"{u.get('name')} ({u.get('role')})" for u in orang[:10])
        if len(orang) > 10:
            nama += f", dan {len(orang) - 10} lainnya"
        perubahan = [{"label": "Penerima", "sebelum": _KOSONG, "sesudah": f"{len(orang)} orang: {nama}"},
                     {"label": "Judul", "sebelum": _KOSONG, "sesudah": _teks(a["judul"], 120)},
                     {"label": "Isi", "sebelum": _KOSONG, "sesudah": _teks(a["isi"], 300)}]
        if a.get("menu"):
            perubahan.append({"label": "Tautan layar", "sebelum": _KOSONG, "sesudah": a["menu"]})
        return {"judul": "Kirim notifikasi dalam aplikasi",
                "ringkas": f"\"{_teks(a['judul'], 80)}\" ke {len(orang)} penerima.",
                "perubahan": perubahan,
                "catatan": ["Muncul di lonceng notifikasi penerima, dengan nama Anda sebagai pengirim."],
                "peringatan": ["Notifikasi yang sudah terkirim tidak bisa ditarik kembali."],
                "ubah": [{"kunci": "judul", "label": "Judul", "jenis": "teks", "nilai": a["judul"]},
                         {"kunci": "isi", "label": "Isi", "jenis": "teks", "nilai": a["isi"]}]}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        a = _bersih_args(args)
        orang = await _penerima(ctx, a)
        meta = {"via": "asisten-ai"}
        if a.get("menu"):
            meta["link_module"] = a["menu"]
        terkirim, gagal = [], []
        for u in orang:
            try:
                out = await ctx.api("POST", "/api/collab/notifications", json={
                    "notif_type": "system", "title": _teks(a["judul"], 120), "content": a["isi"],
                    "source_type": "asisten_ai", "source_url": f"#{a['menu']}" if a.get("menu") else "",
                    "target_user_id": u["id"], "metadata": meta})
                terkirim.append(((out or {}).get("notification") or {}).get("notification_id"))
            except AlatError as e:
                if not terkirim:
                    raise  # belum ada yang terkirim → gagal bersih, tidak ada yang berubah
                gagal.append(f"{u.get('name')}: {e.pesan}")
        ringkas = f"Notifikasi \"{_teks(a['judul'], 60)}\" terkirim ke {len(terkirim)} penerima."
        if gagal:
            ringkas = (f"Notifikasi terkirim ke {len(terkirim)} dari {len(orang)} penerima; gagal untuk "
                       + "; ".join(gagal[:3]) + ".")
        return {"ringkas": ringkas, "hasil": {"terkirim": len(terkirim), "gagal": len(gagal),
                                              "notification_ids": [x for x in terkirim if x]},
                "pembatalan": None}
