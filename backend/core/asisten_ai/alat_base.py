"""Kerangka alat Asisten AI (Kontrak A) — agen inti, Tahap A (7 Nov 2026).

Modul alat (di `core/asisten_ai/alat/`) mendaftar dengan dekorator:

    from core.asisten_ai.alat_base import alat, AlatError

    @alat(name="ringkasan_penjualan", kind="read", label="Membaca ringkasan penjualan",
          description="…", input_schema={...}, domain="penjualan")
    async def ringkasan_penjualan(ctx, args: dict) -> dict:
        data = await ctx.api("GET", "/api/marketing/analitik/penjualan", params={...})
        return {"hasil": data, "_sumber": "Rekap penjualan harian"}

Aturan inti yang dipegang di sini:
  * nama alat unik, snake_case; jenis `read` | `ui` | `action` (action = Tahap B, TIDAK dikirim
    ke model di Tahap A);
  * daftar alat untuk API selalu urut nama dan deterministik (tidak ada tanggal/acak) supaya
    prefix prompt bisa di-cache;
  * `ctx.api` = panggilan ASGI DALAM PROSES dengan token Bearer pengguna sendiri + header `X-CV`,
    sehingga middleware izin, cakupan toko, kunci periode, dan CV berlaku sama seperti di layar;
  * kunci `_sumber` / `_ui_events` dibuang dari hasil sebelum dikirim ke model, lalu dipancarkan
    sebagai event `sumber` / event UI;
  * hasil > 15.000 karakter dipotong dengan catatan jelas;
  * alat baca dalam satu giliran dijalankan bersamaan.

Tahap B (8 Nov 2026) — alat TINDAKAN (Kontrak D), didaftarkan dengan dekorator kelas `tindakan`:

    from core.asisten_ai.alat_base import tindakan, AlatError

    @tindakan(name="pasang_target_toko", label="Memasang target toko", description="…",
              input_schema={...}, domain="penjualan", risiko="rendah", menu="mkt-targets")
    class PasangTargetToko:
        @staticmethod
        async def siapkan(ctx, args) -> dict: ...          # BACA SAJA → Rencana (kartu)
        @staticmethod
        async def jalankan(ctx, args, rencana) -> dict: ... # TULIS lewat ctx.api → {ringkas, hasil, pembatalan}
        @staticmethod
        async def batalkan(ctx, pembatalan) -> dict: ...    # OPSIONAL → {ringkas}

  * panggilan model ke alat tindakan hanya MENJALANKAN `siapkan` lalu memunculkan kartu konfirmasi
    (lihat core/asisten_ai/tindakan.py); `jalankan` baru dipanggil setelah pemilik sesi menekan Setujui;
  * `ctx.api` di loop agen dan di `siapkan` = baca saja (POST/PUT/PATCH/DELETE ditolak); hanya konteks
    `jalankan`/`batalkan` yang boleh menulis, dan setiap tulisannya membawa header `X-Via: asisten-ai`
    + `X-Asisten-Tindakan: <id>`;
  * alat tindakan hanya dikirim ke model bila saklar "Tindakan AI aktif" menyala (`tools_untuk_api(tindakan=True)`);
    deskripsinya diberi awalan baku `[Tindakan]` supaya model tahu alat itu hanya menyiapkan kartu.

Tahap E (9 Nov 2026) — hitung dengan kode:
  * server tool `code_execution_20260120` ikut dikirim (ALAT_SERVER);
  * alat baca `@alat(..., kode=True)` diberi `allowed_callers` sehingga juga bisa dipanggil dari kode Python di ruang
    hitung (programmatic tool calling). Panggilan seperti itu dijalankan dengan salinan konteks ber-`pemanggil="kode"`
    dan hasilnya dibatasi `BATAS_HASIL_KODE` (hasil untuk kode tidak masuk konteks model); alat lain (ui/tindakan)
    yang dipanggil dari kode ditolak dengan galat ramah.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import math
import pkgutil
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

KIND_BACA = "read"
KIND_UI = "ui"
KIND_TINDAKAN = "action"
KINDS = (KIND_BACA, KIND_UI, KIND_TINDAKAN)
KINDS_TAHAP_A = (KIND_BACA, KIND_UI)
DOMAINS = ("penjualan", "iklan", "live", "setoran", "keuangan", "stok", "produksi", "sdm",
           "umum", "laporan", "ui", "saya")

# ── Ruang Asisten AI (audit HR Tahap D, 9 Nov 2026) ──────────────────────────
# Asisten AI dibuka di tiga tempat; tiap ruang menawarkan alat yang relevan saja (alat lain ditahan seperti alat
# ingatan yang dimatikan — tidak dikirim ke model dan ditolak bila tetap dipanggil):
#   umum — Portal Manajemen: semua alat (perilaku lama).
#   sdm  — Portal SDM › AI SDM: alat ber-domain `sdm` + alat bantu umum (tanggal, data fleksibel, grafik/tabel,
#          laporan, ingatan, daftar persetujuan, pengingat). Gaji per orang tetap mengikuti PERAN_GAJI.
#   saya — Portal Saya › Tanya Asisten: hanya alat ber-domain `saya` (data MILIK pengguna sendiri) + tanggal &
#          grafik/tabel. Tanpa data fleksibel lintas karyawan dan tanpa tindakan.
RUANG = ("umum", "sdm", "saya")
ALAT_BERSAMA_RUANG = {
    "sdm": frozenset({"tanggal_dan_periode", "daftar_data", "cari_data", "tampilkan_grafik", "tampilkan_tabel",
                      "simpan_ingatan", "lupakan_ingatan", "buat_laporan", "daftar_persetujuan_menunggu",
                      "buat_pengingat"}),
    "saya": frozenset({"tanggal_dan_periode", "tampilkan_grafik", "tampilkan_tabel"}),
}
DOMAIN_RUANG = {"sdm": frozenset({"sdm"}), "saya": frozenset({"saya"})}


def alat_di_ruang(a: "Alat", ruang: Optional[str]) -> bool:
    """True bila alat `a` ditawarkan di `ruang` (lihat RUANG)."""
    if ruang not in DOMAIN_RUANG:
        return True
    return a.domain in DOMAIN_RUANG[ruang] or a.name in ALAT_BERSAMA_RUANG[ruang]


def alat_luar_ruang(ruang: Optional[str]) -> frozenset:
    """Nama semua alat (baca, ui, tindakan) yang TIDAK ditawarkan di `ruang` — dipakai sebagai `kecuali`."""
    muat_semua_alat()
    return frozenset(n for n, a in _DAFTAR.items() if not alat_di_ruang(a, ruang))

BATAS_HASIL = 15_000          # karakter JSON hasil alat yang dikirim ke model (panggilan langsung)
# Tahap E: hasil untuk KODE di ruang hitung tidak masuk konteks model (hanya keluaran akhir kode yang masuk),
# jadi batasnya jauh lebih longgar — cukup sebagai pengaman memori/ukuran permintaan.
BATAS_HASIL_KODE = 2_000_000
BATAS_DETIK_ALAT = 45.0       # satu alat
BATAS_DETIK_API = 30.0        # satu panggilan ctx.api
_NAMA_RX = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
# Alat server: pencarian web + ruang hitung (code execution; nama sub-alatnya ikut dicadangkan).
NAMA_ALAT_KODE = ("code_execution", "bash_code_execution", "text_editor_code_execution")
NAMA_ALAT_SERVER = ("web_search", "web_fetch") + NAMA_ALAT_KODE
PEMANGGIL_KODE = "code_execution_20260120"   # nilai `allowed_callers` / `caller.type` programmatic tool calling
PEMANGGIL = ("langsung", "kode")

# Event yang boleh dipancarkan alat lewat ctx.emit / `_ui_events` (event lain milik inti).
# Tahap D (proaktif): `ingatan` = chip "Diingat: …" / "Dilupakan: …" dari alat simpan/lupakan ingatan.
EVENT_ALAT = ("status", "grafik", "tabel", "sumber", "laporan", "ingatan")

# Tahap B — alat tindakan (Kontrak D).
RISIKO = ("rendah", "menengah")          # menengah = alasan wajib + konfirmasi dua langkah (Tahap C)
METODE_BACA = ("GET", "HEAD", "OPTIONS")
_MENU_RX = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
AWALAN_TINDAKAN = ("[Tindakan] Alat ini hanya MENYIAPKAN kartu konfirmasi berisi rencana perubahan; data baru "
                   "berubah setelah pengguna menekan Setujui di kartu itu. ")
AWALAN_MENENGAH = "Risiko menengah: pengguna wajib menulis alasan sebelum menyetujui. "
PESAN_BACA_SAJA = ("Alat ini hanya boleh membaca data. Perubahan data hanya lewat kartu tindakan yang "
                   "disetujui pengguna.")

# Peran yang boleh melihat gaji per orang (keputusan owner no. 1).
PERAN_GAJI = frozenset({"owner", "superadmin", "hr", "hr_manager", "manager_hr", "staff_hr"})

# Server tools resmi. Keputusan owner no. 2: ≤5 pencarian + ≤3 pengambilan halaman per pertanyaan.
# Tahap E (9 Nov 2026, keputusan owner "hitung dengan kode"): ruang hitung `code_execution_20260120` (Python di
# kontainer Claude, tanpa internet; gratis karena web_search/web_fetch 20260209 selalu ikut dikirim). Versi ini
# yang mendukung programmatic tool calling (alat `kode=True` dipanggil dari kode, lihat tools_untuk_api).
ALAT_SERVER = (
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5,
     "user_location": {"type": "approximate", "country": "ID", "timezone": "Asia/Jakarta"}},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3, "max_content_tokens": 20000},
    {"type": "code_execution_20260120", "name": "code_execution"},
)


class AlatError(Exception):
    """Galat alat dengan pesan RAMAH berbahasa Indonesia (aman untuk model & layar).

    `status` meniru kode HTTP (400 isian salah, 403 tanpa akses, 404 tidak ada, 5xx sistem).
    """

    def __init__(self, status: int = 400, pesan: str = "Alat gagal dijalankan."):
        super().__init__(pesan)
        try:
            self.status = int(status)
        except (TypeError, ValueError):
            self.status = 500
        self.pesan = str(pesan or "Alat gagal dijalankan.")

    def __str__(self) -> str:
        return self.pesan


@dataclass(frozen=True)
class Alat:
    name: str
    kind: str
    label: str
    description: str
    input_schema: dict
    domain: str
    handler: Callable[..., Awaitable[Any]]
    asal: str  # modul.fungsi (untuk mendeteksi nama ganda)
    # Tahap B — hanya untuk alat tindakan yang didaftarkan lewat `@tindakan` (kelas siapkan/jalankan/batalkan).
    risiko: Optional[str] = None
    menu: Optional[str] = None
    kelas: Optional[type] = None
    # Tahap E (9 Nov 2026) — alat BACA yang boleh dipanggil dari kode di ruang hitung Claude (programmatic tool
    # calling). Pemancaran `allowed_callers` ke API diatur inti (lihat tools_untuk_api); handler membaca
    # `ctx.pemanggil` ("langsung" | "kode") untuk batas baris yang berbeda.
    kode: bool = False

    @property
    def adalah_tindakan(self) -> bool:
        """Alat tindakan SAH (punya kelas siapkan/jalankan). `@alat(kind="action")` biasa tidak dihitung."""
        return self.kind == KIND_TINDAKAN and self.kelas is not None

    @property
    def siapkan(self):
        return getattr(self.kelas, "siapkan", None) if self.kelas is not None else None

    @property
    def jalankan(self):
        return getattr(self.kelas, "jalankan", None) if self.kelas is not None else None

    @property
    def batalkan(self):
        return getattr(self.kelas, "batalkan", None) if self.kelas is not None else None

    @property
    def bisa_dibalikkan(self) -> bool:
        return self.batalkan is not None

    def untuk_api(self) -> dict:
        desc = self.description
        if self.adalah_tindakan:
            desc = AWALAN_TINDAKAN + (AWALAN_MENENGAH if self.risiko == "menengah" else "") + desc
        return {"name": self.name, "description": desc,
                "input_schema": kanonik(self.input_schema)}


_DAFTAR: dict[str, Alat] = {}
_GALAT_MUAT: dict[str, str] = {}
_SUDAH_MUAT = False


def kanonik(obj: Any) -> Any:
    """Salinan JSON dengan kunci terurut — serialisasi identik antar proses (cache prompt)."""
    return json.loads(json.dumps(obj, sort_keys=True, ensure_ascii=False))


def _periksa_dasar(name: str, label: str, description: str, input_schema: dict) -> None:
    if not isinstance(name, str) or not _NAMA_RX.match(name) or name in NAMA_ALAT_SERVER:
        raise ValueError(f"Nama alat tidak sah: {name!r} (snake_case, 3–64 huruf, bukan nama alat server)")
    if not (isinstance(label, str) and label.strip()) or not (isinstance(description, str) and description.strip()):
        raise ValueError(f"Alat {name}: label dan description wajib diisi")
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        raise ValueError(f"Alat {name}: input_schema wajib JSON Schema bertipe object")
    try:
        json.dumps(input_schema)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Alat {name}: input_schema tidak bisa diubah ke JSON") from e


def alat(*, name: str, kind: str, label: str, description: str, input_schema: dict,
         domain: str = "umum", kode: bool = False):
    """Dekorator pendaftaran alat (Kontrak A). Lihat docstring modul.
    `kode=True` (Tahap E): alat baca ini juga boleh dipanggil dari kode di ruang hitung Claude."""
    _periksa_dasar(name, label, description, input_schema)
    if kind not in KINDS:
        raise ValueError(f"Jenis alat {name}: {kind!r} bukan salah satu dari {KINDS}")
    if kode and kind != KIND_BACA:
        raise ValueError(f"Alat {name}: hanya alat baca yang boleh dipanggil dari kode (kode=True)")
    if domain not in DOMAINS:
        raise ValueError(f"Domain alat {name}: {domain!r} bukan salah satu dari {DOMAINS}")

    def _daftar(fn):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"Alat {name}: handler wajib `async def f(ctx, args)`")
        asal = f"{fn.__module__}.{fn.__qualname__}"
        lama = _DAFTAR.get(name)
        if lama is not None and lama.asal != asal:
            raise ValueError(f"Nama alat '{name}' sudah dipakai oleh {lama.asal}")
        _DAFTAR[name] = Alat(name=name, kind=kind, label=label.strip(), description=description.strip(),
                             input_schema=input_schema, domain=domain, handler=fn, asal=asal, kode=bool(kode))
        return fn

    return _daftar


def tindakan(*, name: str, label: str, description: str, input_schema: dict, domain: str = "umum",
             risiko: str = "rendah", menu: Optional[str] = None):
    """Dekorator KELAS alat tindakan (Kontrak D, Tahap B). Kelas wajib punya `async siapkan(ctx, args)` dan
    `async jalankan(ctx, args, rencana)`; `async batalkan(ctx, pembatalan)` opsional (tanpa itu = tidak bisa
    dibalikkan). Terdaftar di `_DAFTAR` sebagai `Alat(kind="action", kelas=<kelas>)`; kelas mendapat atribut
    `_alat` (objek Alat-nya)."""
    _periksa_dasar(name, label, description, input_schema)
    if risiko not in RISIKO:
        raise ValueError(f"Alat tindakan {name}: risiko {risiko!r} bukan salah satu dari {RISIKO}")
    if menu is not None and (not isinstance(menu, str) or not _MENU_RX.match(menu)):
        raise ValueError(f"Alat tindakan {name}: menu {menu!r} harus id modul layar (huruf kecil dan '-')")
    if domain not in DOMAINS:
        # Domain hanya label pengelompokan; jangan sampai satu label baru membuat modul alat gagal dimuat.
        log.warning("Alat tindakan %s: domain %r tidak dikenal, dipakai 'umum'", name, domain)
        domain = "umum"

    def _daftar(cls):
        if not isinstance(cls, type):
            raise TypeError(f"Alat tindakan {name}: dekorator `tindakan` dipasang pada KELAS")
        for wajib in ("siapkan", "jalankan"):
            if not inspect.iscoroutinefunction(getattr(cls, wajib, None)):
                raise TypeError(f"Alat tindakan {name}: kelas wajib punya `async def {wajib}(...)` (staticmethod)")
        btl = getattr(cls, "batalkan", None)
        if btl is not None and not inspect.iscoroutinefunction(btl):
            raise TypeError(f"Alat tindakan {name}: `batalkan` wajib `async def batalkan(ctx, pembatalan)`")
        asal = f"{cls.__module__}.{cls.__qualname__}"
        lama = _DAFTAR.get(name)
        if lama is not None and lama.asal != asal:
            raise ValueError(f"Nama alat '{name}' sudah dipakai oleh {lama.asal}")
        a = Alat(name=name, kind=KIND_TINDAKAN, label=label.strip(), description=description.strip(),
                 input_schema=input_schema, domain=domain, handler=getattr(cls, "siapkan"), asal=asal,
                 risiko=risiko, menu=menu, kelas=cls)
        _DAFTAR[name] = a
        cls._alat = a
        return cls

    return _daftar


def muat_semua_alat(paksa: bool = False) -> dict[str, str]:
    """Impor setiap modul di `core/asisten_ai/alat/` (urut nama). Return {modul: galat} yang gagal.

    Modul yang rusak dicatat dan dilewati supaya satu alat tidak mematikan seluruh chat.
    """
    global _SUDAH_MUAT
    if _SUDAH_MUAT and not paksa:
        return dict(_GALAT_MUAT)
    pkg = importlib.import_module("core.asisten_ai.alat")
    for m in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if m.name.startswith("_"):
            continue
        nama = f"{pkg.__name__}.{m.name}"
        try:
            importlib.import_module(nama)
            _GALAT_MUAT.pop(m.name, None)
        except Exception as e:  # noqa: BLE001 — modul alat pihak lain tidak boleh mematikan chat
            log.exception("Modul alat Asisten AI gagal dimuat: %s", nama)
            _GALAT_MUAT[m.name] = f"{type(e).__name__}: {str(e)[:200]}"
    _SUDAH_MUAT = True
    return dict(_GALAT_MUAT)


def daftar_alat(kinds=KINDS_TAHAP_A, *, tindakan: bool = False, kecuali=()) -> list[Alat]:
    """Alat jenis `kinds`, urut nama. `tindakan=True` menambah alat tindakan SAH (`@tindakan`).
    `kecuali` = nama alat yang tidak ditawarkan (Tahap D: alat ingatan saat ingatan dimatikan / briefing)."""
    muat_semua_alat()
    buang = set(kecuali or ())
    return sorted((a for a in _DAFTAR.values()
                   if a.name not in buang
                   and ((a.kind in kinds and a.kind != KIND_TINDAKAN) or (tindakan and a.adalah_tindakan))),
                  key=lambda a: a.name)


def cari_alat(name: str, kinds=KINDS_TAHAP_A) -> Optional[Alat]:
    muat_semua_alat()
    a = _DAFTAR.get(name)
    return a if a is not None and a.kind in kinds else None


def cari_tindakan(name: str) -> Optional[Alat]:
    """Alat tindakan SAH bernama `name` (None bila tidak ada / bukan `@tindakan`)."""
    muat_semua_alat()
    a = _DAFTAR.get(name)
    return a if a is not None and a.adalah_tindakan else None


def tools_untuk_api(kinds=KINDS_TAHAP_A, *, eager: bool = True, server: bool = True,
                    tindakan: bool = False, kecuali=(), kode: bool = True) -> list[dict]:
    """Daftar `tools` untuk Messages API: alat klien urut nama, lalu web_search & web_fetch.

    `eager_input_streaming` dipasang untuk alat klien (skill: aturan bawaan permintaan streaming);
    karena server tidak lagi memvalidasi isian, inti memvalidasi sendiri (`periksa_skema`).
    `tindakan=True` (saklar "Tindakan AI aktif" menyala) ikut mengirim alat tindakan.
    `kecuali` = nama alat yang tidak dikirim (Tahap D: alat ingatan).
    Tahap E: alat baca `kode=True` diberi `allowed_callers: ["direct", "code_execution_20260120"]` (boleh dipanggil
    langsung ATAU dari kode di ruang hitung); nilainya tetap → prefix cache tidak berubah antar permintaan.
    `kode=False` (jalur darurat: ruang hitung dimatikan / ditolak API): tanpa `code_execution`, tanpa
    `allowed_callers`, dan alat `kode=True` juga tanpa `eager_input_streaming` (bentuk alat Tahap D yang sudah teruji).
    """
    out = []
    for a in daftar_alat(kinds, tindakan=tindakan, kecuali=kecuali):
        d = a.untuk_api()
        alat_kode = a.kode and a.kind == KIND_BACA
        if eager and (kode or not alat_kode):
            d["eager_input_streaming"] = True
        if kode and alat_kode:
            d["allowed_callers"] = ["direct", PEMANGGIL_KODE]
        out.append(d)
    if server:
        out += [kanonik(s) for s in ALAT_SERVER if kode or not str(s.get("type", "")).startswith("code_execution")]
    return out


def label_alat(name: str) -> str:
    if name == "web_search":
        return "Mencari di web"
    if name == "web_fetch":
        return "Membuka halaman web"
    if name in ("code_execution", "bash_code_execution"):
        return "Menghitung dengan kode"
    if name == "text_editor_code_execution":
        return "Menyiapkan kode"
    a = _DAFTAR.get(name)
    return a.label if a else f"Menjalankan {name.replace('_', ' ')}"


# ── Validasi isian (subset JSON Schema yang dipakai alat) ────────────────────
_TIPE = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def periksa_skema(schema: dict, value: Any, path: str = "isian", _errs: Optional[list] = None) -> list[str]:
    """Validasi ringan (tanpa dependensi): type, enum, const, required, properties,
    additionalProperties, items, min/maxItems, min/maxLength, minimum/maximum, pattern, anyOf/oneOf.
    Return daftar galat (≤ 8) berbahasa Indonesia; kosong = sah."""
    errs = [] if _errs is None else _errs
    if len(errs) >= 8 or not isinstance(schema, dict):
        return errs
    for kunci in ("anyOf", "oneOf"):
        if kunci in schema:
            if not any(not periksa_skema(s, value, path) for s in schema[kunci]):
                errs.append(f"{path}: tidak cocok dengan pilihan bentuk yang sah")
            return errs
    t = schema.get("type")
    if t is not None:
        tipe = t if isinstance(t, list) else [t]
        if not any(_TIPE.get(x, lambda v: True)(value) for x in tipe):
            errs.append(f"{path}: harus bertipe {'/'.join(tipe)}")
            return errs
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: harus salah satu dari {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: harus {schema['const']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: minimal {schema['minLength']} karakter")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: maksimal {schema['maxLength']} karakter")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: format tidak sesuai")
    if _TIPE["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: minimal {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: maksimal {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: minimal {schema['minItems']} butir")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: maksimal {schema['maxItems']} butir")
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(value):
                periksa_skema(schema["items"], v, f"{path}[{i}]", errs)
                if len(errs) >= 8:
                    break
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for r in schema.get("required") or []:
            if r not in value:
                errs.append(f"{path}.{r}: wajib diisi")
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                periksa_skema(props[k], v, f"{path}.{k}", errs)
            elif extra is False:
                errs.append(f"{path}.{k}: tidak dikenal")
            elif isinstance(extra, dict):
                periksa_skema(extra, v, f"{path}.{k}", errs)
            if len(errs) >= 8:
                break
    return errs


# ── Konteks alat ─────────────────────────────────────────────────────────────
class _Selesai:
    """Nilai kembali `ctx.emit`: bisa dipanggil biasa ATAU di-`await` (keduanya aman)."""

    __slots__ = ()

    def __await__(self):
        return iter(())


_SELESAI = _Selesai()

_PII_KEY_RX = re.compile(
    r"(buyer|customer|pembeli|penerima|recipient|receiver|shipping_?name|nama_?kirim|alamat|address|"
    r"phone|telepon|telp|no_?hp|handphone|whatsapp|\bwa\b|email|\bnik\b|ktp|username)")


def _pesan_status(status: int, detail: Any) -> str:
    """Pesan ramah untuk respons non-2xx dari endpoint aplikasi (tanpa jejak teknis)."""
    teks = ""
    if isinstance(detail, str):
        teks = detail.strip()
    elif isinstance(detail, dict):
        teks = str(detail.get("detail") or detail.get("message") or detail.get("error") or "").strip()
    elif isinstance(detail, list) and status == 422:
        teks = ""
    aman = bool(teks) and len(teks) <= 240 and "Traceback" not in teks and "\n" not in teks
    # Detail bawaan FastAPI/Starlette berbahasa Inggris tidak diteruskan.
    if aman and re.match(r"^(not found|forbidden|unauthorized|method not allowed|internal server error)\b",
                         teks, re.IGNORECASE):
        aman = False
    if status == 401:
        return "Sesi login sudah berakhir. Muat ulang halaman lalu masuk lagi."
    if status == 403:
        return "Akun ini tidak punya akses ke data tersebut." + (f" ({teks})" if aman else "")
    if status == 404:
        return teks if aman else "Data yang diminta tidak ditemukan."
    if status in (400, 409, 422):
        return teks if aman else "Permintaan data tidak sah (periksa periode, toko, atau isian lain)."
    if status == 429:
        return "Sistem sedang sibuk. Coba lagi sebentar lagi."
    if status >= 500:
        return "Sistem sedang bermasalah saat membaca data ini."
    return teks if aman else f"Permintaan data gagal (kode {status})."


def _bersih_params(params: Optional[dict]) -> Optional[dict]:
    if not params:
        return None
    out = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


class AlatContext:
    """Konteks yang diterima setiap handler alat (`ctx`).

    Atribut: `user` (dict dari require_auth), `cv` ("DA" | "SMU" | "ALL"), `today` (tanggal WIB),
    `alat_id` (id panggilan alat saat ini, bila ada), `sesi_id`, `db`, `samaran` (Pseudonymizer bersama satu giliran),
    `tindakan_id` (id kartu tindakan, hanya di `siapkan`/`jalankan`/`batalkan`), `baca_saja`,
    `pesan_id` (Tahap D: id pesan asisten yang sedang dijawab; sumber ingatan).
    Metode: `api`, `emit`, `mask`.

    `baca_saja=True` (loop agen + `siapkan`): `ctx.api` menolak POST/PUT/PATCH/DELETE. Konteks `jalankan`/
    `batalkan` dibuat inti dengan `baca_saja=False` + `tindakan_id`, dan tulisannya membawa header
    `X-Via: asisten-ai` + `X-Asisten-Tindakan: <id>`.
    """

    def __init__(self, *, user: dict, cv: str, today: date, token: Optional[str] = None, app=None,
                 emit: Optional[Callable[[str, dict], None]] = None,
                 klien_api: Optional[Callable[[], Any]] = None, alat_id: Optional[str] = None,
                 sesi_id: Optional[str] = None, db=None, baca_saja: bool = False,
                 tindakan_id: Optional[str] = None, pesan_id: Optional[str] = None):
        self.user = dict(user or {})
        self.sesi_id = sesi_id
        # Tahap D: id pesan asisten yang sedang dijawab (sumber ingatan {sesi_id, pesan_id}).
        self.pesan_id = pesan_id
        self.db = db
        self.cv = cv
        self.today = today
        self.alat_id = alat_id
        self.baca_saja = bool(baca_saja)
        self.tindakan_id = tindakan_id
        # Tahap E: "langsung" (model memanggil) | "kode" (dipanggil dari kode di ruang hitung Claude). Diisi inti
        # per panggilan; handler alat `kode=True` boleh memberi batas baris lebih besar untuk "kode".
        self.pemanggil = "langsung"
        self._token = token
        self._app = app
        self._emit_fn = emit
        self._klien_api = klien_api
        self._bersama = {"klien": None}

    # — identitas —
    @property
    def peran(self) -> str:
        return str(self.user.get("role") or "").lower()

    @property
    def samaran(self):
        """Satu Pseudonymizer bersama untuk semua alat dalam satu giliran (kode samaran konsisten)."""
        ps = self._bersama.get("samaran")
        if ps is None:
            from services.ai.privacy import Pseudonymizer
            ps = self._bersama["samaran"] = Pseudonymizer()
        return ps

    @property
    def boleh_gaji(self) -> bool:
        return self.peran in PERAN_GAJI

    def untuk_alat(self, alat_id: Optional[str], pemanggil: Optional[str] = None) -> "AlatContext":
        """Salinan untuk satu panggilan alat (klien HTTP dipakai bersama; sifat baca-saja ikut).
        Tahap E: `pemanggil` per panggilan ("langsung" | "kode"); salinan per panggilan karena panggilan dari kode
        berjalan bersamaan dengan konteks induk yang sama."""
        c = AlatContext(user=self.user, cv=self.cv, today=self.today, token=self._token, app=self._app,
                        emit=self._emit_fn, klien_api=self._klien_api, alat_id=alat_id,
                        sesi_id=self.sesi_id, db=self.db, baca_saja=self.baca_saja,
                        tindakan_id=self.tindakan_id, pesan_id=self.pesan_id)
        c.pemanggil = pemanggil if pemanggil in PEMANGGIL else self.pemanggil
        c._bersama = self._bersama
        return c

    def untuk_tindakan(self, tindakan_id: str, *, tulis: bool, alat_id: Optional[str] = None) -> "AlatContext":
        """Salinan untuk `siapkan` (tulis=False) atau `jalankan`/`batalkan` (tulis=True) satu kartu tindakan."""
        c = self.untuk_alat(alat_id or self.alat_id)
        c.baca_saja = not tulis
        c.tindakan_id = tindakan_id
        return c

    # — panggilan endpoint aplikasi —
    def _klien(self):
        if self._bersama["klien"] is None:
            if self._klien_api is not None:
                self._bersama["klien"] = self._klien_api()
            else:
                if self._app is None:
                    raise AlatError(500, "Alat tidak bisa membaca data: aplikasi tidak tersedia.")
                import httpx  # lazy: CI tidak memasang httpx; image backend memasangnya
                self._bersama["klien"] = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self._app), base_url="http://asisten-ai.internal",
                    timeout=BATAS_DETIK_API)
        return self._bersama["klien"]

    async def api(self, method: str, path: str, params: Optional[dict] = None, json: Any = None, *,
                  headers: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
        """Panggil endpoint aplikasi SENDIRI dalam proses dengan token pengguna + header X-CV.

        Return JSON hasil parse. Respons non-2xx → `AlatError(status, pesan ramah)`.
        `X-CV: ALL` hanya dikirim untuk GET (penjaga CV menolak tulis dengan Gabungan).
        Konteks baca-saja menolak metode tulis (403). Tulisan dari konteks tindakan membawa
        `X-Via: asisten-ai` + `X-Asisten-Tindakan: <id>` (jejak "via Asisten AI" di endpoint tujuan).
        """
        method = (method or "GET").upper()
        if not isinstance(path, str) or not path.startswith("/api/"):
            raise AlatError(400, "Alat hanya boleh membaca endpoint aplikasi (/api/...).")
        tulis = method not in METODE_BACA
        if tulis and self.baca_saja:
            raise AlatError(403, PESAN_BACA_SAJA)
        if not self._token:
            raise AlatError(401, _pesan_status(401, None))
        hdr = {"Authorization": f"Bearer {self._token}", "Accept": "application/json",
               "X-Asisten-AI": "1"}
        if self.cv in ("DA", "SMU") or (self.cv == "ALL" and method == "GET"):
            hdr["X-CV"] = self.cv
        for k, v in (headers or {}).items():
            if str(k).lower() not in ("authorization", "x-cv", "cookie", "x-via", "x-asisten-tindakan"):
                hdr[k] = v
        if tulis and self.tindakan_id:
            hdr["X-Via"] = "asisten-ai"
            hdr["X-Asisten-Tindakan"] = str(self.tindakan_id)
        kw: dict = {"params": _bersih_params(params), "headers": hdr,
                    "timeout": timeout or BATAS_DETIK_API}
        if json is not None:
            kw["json"] = json
        try:
            resp = await self._klien().request(method, path, **kw)
        except AlatError:
            raise
        except asyncio.TimeoutError as e:
            raise AlatError(504, "Sistem terlalu lama menjawab permintaan data ini.") from e
        except Exception as e:  # noqa: BLE001 — galat transport/handler tidak boleh bocor mentah
            if "Timeout" in type(e).__name__:
                raise AlatError(504, "Sistem terlalu lama menjawab permintaan data ini.") from e
            log.warning("ctx.api %s %s gagal: %s", method, path, type(e).__name__)
            raise AlatError(502, "Sistem gagal membaca data ini.") from e
        status = int(getattr(resp, "status_code", 500))
        if status >= 400:
            try:
                detail = resp.json()
            except Exception:  # noqa: BLE001
                detail = None
            raise AlatError(status, _pesan_status(status, detail))
        if status == 204:
            return None
        try:
            return resp.json()
        except Exception as e:  # noqa: BLE001
            raise AlatError(502, "Jawaban sistem tidak bisa dibaca.") from e

    async def tutup(self) -> None:
        k = self._bersama.get("klien")
        self._bersama["klien"] = None
        if k is not None and hasattr(k, "aclose"):
            try:
                await k.aclose()
            except Exception:  # noqa: BLE001
                pass

    # — event UI —
    def emit(self, event: str, data: dict):
        """Pancarkan event UI (status | grafik | tabel | sumber | laporan). Boleh di-`await` atau tidak."""
        if event not in EVENT_ALAT:
            log.warning("ctx.emit: event %r tidak boleh dipancarkan alat (diabaikan)", event)
            return _SELESAI
        if self._emit_fn is not None:
            self._emit_fn(event, data if isinstance(data, dict) else {"data": data})
        return _SELESAI

    # — privasi —
    def mask(self, obj: Any, *, gaji: Optional[bool] = None, teks: bool = True) -> Any:
        """Samarkan data pribadi sebelum dikembalikan ke model (pakai `services/ai/privacy.py`).

        * kunci data pribadi pembeli (nama pembeli/penerima, HP, alamat, email, NIK) dibuang;
        * kunci gaji/upah/kasbon per orang dibuang KECUALI peran owner/superadmin/SDM
          (`gaji=True/False` memaksa);
        * `teks=True`: email, nomor HP, dan deret angka panjang di dalam teks disamarkan.
        """
        from services.ai.privacy import mask_pii, strip_sensitive
        boleh = self.boleh_gaji if gaji is None else bool(gaji)
        data = obj if boleh else strip_sensitive(obj)

        def _jalan(v):
            if isinstance(v, dict):
                return {k: _jalan(x) for k, x in v.items() if not _PII_KEY_RX.search(str(k).lower())}
            if isinstance(v, list):
                return [_jalan(x) for x in v]
            if isinstance(v, tuple):
                return [_jalan(x) for x in v]
            if teks and isinstance(v, str):
                return mask_pii(v)
            return v
        return _jalan(data)


# ── Eksekusi ─────────────────────────────────────────────────────────────────
@dataclass
class HasilAlat:
    tool_use_id: str
    nama: str
    isi: str                     # teks tool_result untuk model
    is_error: bool = False
    pesan: Optional[str] = None  # pesan ramah untuk event `alat` (gagal)
    sumber: list = field(default_factory=list)
    # Tahap B: kartu tindakan yang MENUNGGU keputusan (tool_result-nya baru dibuat setelah diputuskan).
    tindakan_id: Optional[str] = None
    kartu: Optional[dict] = None   # data event `tindakan`

    def untuk_api(self) -> dict:
        d = {"type": "tool_result", "tool_use_id": self.tool_use_id, "content": self.isi}
        if self.is_error:
            d["is_error"] = True
        return d


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


def serialisasi(hasil: Any) -> str:
    return json.dumps(hasil, ensure_ascii=False, default=_json_default, separators=(",", ":"))


def potong(teks: str, batas: int = BATAS_HASIL) -> str:
    if len(teks) <= batas:
        return teks
    catatan = (f"\n…[DIPOTONG: hasil alat ini {len(teks):,} karakter; hanya {batas:,} karakter pertama "
               "yang dikirim, jadi data di atas TIDAK lengkap. Persempit permintaan (periode, toko, "
               "atau kategori) bila butuh sisanya, dan jangan menebak bagian yang terpotong.]")
    return teks[: max(0, batas - len(catatan))] + catatan


def _sumber_dari(v: Any) -> list[dict]:
    out = []
    for x in (v if isinstance(v, list) else [v]):
        if isinstance(x, str) and x.strip():
            out.append({"jenis": "data", "label": x.strip()[:120]})
        elif isinstance(x, dict) and str(x.get("label") or "").strip():
            item = {"jenis": "web" if x.get("jenis") == "web" else "data",
                    "label": str(x["label"]).strip()[:120]}
            if x.get("url"):
                item["url"] = str(x["url"])
            out.append(item)
    return out


def batas_hasil(pemanggil: Optional[str]) -> int:
    """Batas karakter hasil: 15.000 untuk panggilan langsung (masuk konteks model), 2 juta untuk kode."""
    return BATAS_HASIL_KODE if pemanggil == "kode" else BATAS_HASIL


def olah_hasil(tool_use_id: str, nama: str, hasil: Any, ctx: AlatContext) -> HasilAlat:
    """Buang `_sumber`/`_ui_events`, pancarkan event-nya, serialisasi + potong hasil (batas menurut `ctx.pemanggil`)."""
    sumber: list = []
    if isinstance(hasil, dict):
        hasil = dict(hasil)
        sumber = _sumber_dari(hasil.pop("_sumber", None))
        events = hasil.pop("_ui_events", None) or []
        for ev in events if isinstance(events, list) else []:
            if isinstance(ev, dict) and ev.get("event") in EVENT_ALAT:
                ctx.emit(ev["event"], ev.get("data") or {})
            else:
                log.warning("Alat %s: _ui_events berisi event tidak sah (diabaikan)", nama)
    elif hasil is None:
        hasil = {"ok": True}
    else:
        hasil = {"hasil": hasil}
    if sumber:
        ctx.emit("sumber", {"item": sumber})
    teks = serialisasi(hasil)
    if getattr(ctx, "pemanggil", "langsung") == "kode" and len(teks) > BATAS_HASIL_KODE:
        # JSON yang dipotong tidak bisa di-`json.loads` oleh kode → galat jelas, bukan data rusak.
        return _gagal(tool_use_id, nama,
                      f"Hasil alat ini terlalu besar untuk dikirim ke kode ({len(teks):,} karakter; batas "
                      f"{BATAS_HASIL_KODE:,}). Persempit permintaan (periode, kelompok, agregasi, atau batas baris).",
                      "Hasil data terlalu besar")
    return HasilAlat(tool_use_id=tool_use_id, nama=nama,
                     isi=potong(teks, batas_hasil(getattr(ctx, "pemanggil", "langsung"))), sumber=sumber)


def _gagal(tool_use_id: str, nama: str, pesan: str, pesan_layar: Optional[str] = None) -> HasilAlat:
    return HasilAlat(tool_use_id=tool_use_id, nama=nama, isi=pesan, is_error=True,
                     pesan=pesan_layar or pesan)


PESAN_BUKAN_KODE = ("Alat ini tidak bisa dipanggil dari kode di ruang hitung. Panggil langsung (bukan dari kode), "
                    "atau pakai alat yang memang boleh dipanggil dari kode.")


async def jalankan_satu(tool_use_id: str, nama: str, args: Any, ctx: AlatContext, *,
                        batas_detik: float = BATAS_DETIK_ALAT, pemanggil: str = "langsung") -> HasilAlat:
    """Jalankan SATU alat klien dengan validasi isian dan galat yang ramah.
    Tahap E: `pemanggil="kode"` = dipanggil dari kode di ruang hitung — hanya alat baca `kode=True`; konteksnya
    salinan sendiri dengan `ctx.pemanggil = "kode"` dan hasilnya memakai batas `BATAS_HASIL_KODE`."""
    a = cari_alat(nama)
    if a is None:
        return _gagal(tool_use_id, nama,
                      f"Alat '{nama}' belum tersedia di sistem ini. Jawab tanpa alat ini dan beri tahu "
                      "pengguna bahwa data tersebut belum bisa dibaca Asisten AI.",
                      "Alat ini belum tersedia")
    if pemanggil == "kode" and not (a.kode and a.kind == KIND_BACA):
        return _gagal(tool_use_id, nama, PESAN_BUKAN_KODE, "Alat ini tidak bisa dipanggil dari kode")
    if not isinstance(args, dict):
        return _gagal(tool_use_id, nama, json.dumps({"INVALID_JSON": serialisasi(args)}, ensure_ascii=False),
                      "Isian alat tidak sah")
    errs = periksa_skema(a.input_schema, args)
    if errs:
        return _gagal(tool_use_id, nama, "Isian alat tidak sah: " + "; ".join(errs) + ". Perbaiki lalu coba lagi.",
                      "Isian alat tidak sah")
    c = ctx.untuk_alat(tool_use_id, pemanggil="kode" if pemanggil == "kode" else "langsung")
    try:
        hasil = await asyncio.wait_for(a.handler(c, args), timeout=batas_detik)
    except AlatError as e:
        return _gagal(tool_use_id, nama, e.pesan)
    except asyncio.TimeoutError:
        return _gagal(tool_use_id, nama, "Alat terlalu lama berjalan dan dihentikan. Persempit permintaan.",
                      "Alat terlalu lama berjalan")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("Alat Asisten AI %s gagal", nama)
        return _gagal(tool_use_id, nama, "Terjadi kesalahan saat menjalankan alat ini.")
    try:
        return olah_hasil(tool_use_id, nama, hasil, c)
    except Exception:  # noqa: BLE001
        log.exception("Hasil alat %s tidak bisa diolah", nama)
        return _gagal(tool_use_id, nama, "Hasil alat ini tidak bisa dibaca sistem.")


async def jalankan_banyak(panggilan: list[tuple], ctx: AlatContext, *,
                          saat_mulai: Optional[Callable[[str, str], None]] = None,
                          saat_selesai: Optional[Callable[[HasilAlat], None]] = None,
                          penangan_tindakan: Optional[Callable[[str, str, Any], Awaitable[HasilAlat]]] = None
                          ) -> list[HasilAlat]:
    """Jalankan panggilan alat satu giliran: alat `read` BERSAMAAN, alat `ui` dan tindakan berurutan
    sesudahnya (urutan grafik/tabel/kartu di layar = urutan panggilan model). Hasil sesuai urutan input.

    `panggilan` = [(tool_use_id, nama, isian)] atau [(tool_use_id, nama, isian, pemanggil)] (Tahap E: pemanggil
    "kode" untuk panggilan dari kode di ruang hitung; bawaan "langsung").
    Alat tindakan tidak pernah dijalankan di sini: panggilannya diserahkan ke `penangan_tindakan`
    (inti: `siapkan` → kartu konfirmasi). Tanpa penangan → galat "belum tersedia". Alat tindakan dari kode → galat."""
    hasil: dict[int, HasilAlat] = {}

    async def _satu(i, tid, nama, args, pemanggil):
        if saat_mulai:
            saat_mulai(tid, nama)
        a = _DAFTAR.get(nama)
        if pemanggil == "kode" and a is not None and a.adalah_tindakan:
            h = _gagal(tid, nama, PESAN_BUKAN_KODE, "Alat ini tidak bisa dipanggil dari kode")
        elif penangan_tindakan is not None and a is not None and a.adalah_tindakan:
            h = await penangan_tindakan(tid, nama, args)
        else:
            h = await jalankan_satu(tid, nama, args, ctx, pemanggil=pemanggil)
        hasil[i] = h
        if saat_selesai:
            saat_selesai(h)

    baca, lain = [], []
    for i, p in enumerate(panggilan):
        tid, nama, args = p[0], p[1], p[2]
        pemanggil = p[3] if len(p) > 3 and p[3] in PEMANGGIL else "langsung"
        a = cari_alat(nama)
        (baca if a is not None and a.kind == KIND_BACA else lain).append((i, tid, nama, args, pemanggil))
    if baca:
        await asyncio.gather(*(_satu(*p) for p in baca))
    for p in lain:
        await _satu(*p)
    return [hasil[i] for i in range(len(panggilan))]


def id_pendek(awalan: str) -> str:
    return f"{awalan}-{uuid.uuid4().hex[:10]}"
