"""core/entities — SATU sumber kebenaran pembukuan dua CV (Tahap 8 fase 1, keputusan owner 7 Nov 2026).

Satu aplikasi memegang DUA buku besar terpisah:
  * ``DA``  = CV Dewi Aditya Official — produk sendiri, toko online, stok, pembelian, HR;
  * ``SMU`` = CV Sukma Mitra Utama ("CV Sukma") — maklon (Portal Maklon) dan jasa jahit.

Aturan yang dipegang modul ini (dipakai backend, migrasi, dan uji):
  * setiap jurnal milik TEPAT SATU CV (field ``entity`` di kepala jurnal dan setiap baris cermin);
  * dokumen/jurnal lama tanpa ``entity`` = DA (kompatibel ke belakang), lihat ``entity_match``;
  * pilihan CV dari layar dibaca dari query ``entity``, body ``entity``, lalu header ``X-CV``
    (dikirim cangkang Portal Keuangan) — ``entity_from_request``;
  * ``ALL`` (Gabungan) hanya untuk DILIHAT: laporan menjumlah dua buku (fase 1 belum mengeliminasi
    transaksi antar CV; itu fase 3);
  * akun bagan berlaku untuk CV tertentu (field ``entities``); bila belum diisi dipakai aturan kode
    ``code_rule_entities`` (aturan yang sama dipakai migrasi ``2026_11_08_entitas_cv``);
  * rekening kas/bank punya pemilik (field ``entity`` di ``rahaza_cash_accounts``).

``flags.subledger_entity_*`` di bagan akun berarti LAWAN TRANSAKSI (klien/pemasok), BUKAN CV — sengaja
tidak dipakai di sini.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

from fastapi import HTTPException

log = logging.getLogger(__name__)

DA = "DA"
SMU = "SMU"
ALL = "ALL"
DEFAULT_ENTITY = DA
ENTITY_CODES = (DA, SMU)

ENTITIES = {
    DA: {"code": DA, "name": "CV Dewi Aditya Official", "short": "CV Dewi Aditya"},
    SMU: {"code": SMU, "name": "CV Sukma Mitra Utama", "short": "CV Sukma"},
}
ALL_LABEL = "Gabungan (lihat saja)"

# Header yang dikirim cangkang Portal Keuangan (frontend `lib/entitas.js`). Huruf kecil: Starlette
# menormalkan nama header.
ENTITY_HEADER = "x-cv"

READONLY_ALL_MSG = ("Mode Gabungan hanya untuk dilihat. Pilih CV Dewi Aditya atau CV Sukma dulu "
                    "untuk menambah atau mengubah data.")
_ALIASES = {"SUKMA": SMU, "CV SUKMA": SMU, "DEWI": DA, "DEWI ADITYA": DA, "CV DEWI ADITYA": DA,
            "GABUNGAN": ALL, "SEMUA": ALL}


def entity_short(code: Optional[str]) -> str:
    if code == ALL:
        return "Gabungan"
    return ENTITIES.get(code or DEFAULT_ENTITY, ENTITIES[DEFAULT_ENTITY])["short"]


def entity_name(code: Optional[str]) -> str:
    return ENTITIES.get(code or DEFAULT_ENTITY, ENTITIES[DEFAULT_ENTITY])["name"]


def entity_options() -> list:
    """Pilihan CV untuk layar (urutan tetap: DA, SMU, Gabungan)."""
    return [{"code": c, "name": ENTITIES[c]["name"], "short": ENTITIES[c]["short"]} for c in ENTITY_CODES] + [
        {"code": ALL, "name": ALL_LABEL, "short": "Gabungan", "read_only": True}]


def normalize_entity(value, *, allow_all: bool = False, default: Optional[str] = None) -> Optional[str]:
    """Kode CV sah dari isian apa pun. Kosong → ``default``. Tidak dikenal → ValueError (pesan Indonesia)."""
    if value is None or str(value).strip() == "":
        return default
    v = str(value).strip().upper()
    v = _ALIASES.get(v, v)
    if v == ALL:
        if allow_all:
            return ALL
        raise ValueError(READONLY_ALL_MSG)
    if v in ENTITY_CODES:
        return v
    raise ValueError(f"CV '{str(value).strip()}' tidak dikenal. Pilih DA (CV Dewi Aditya) atau SMU (CV Sukma).")


def entity_of_value(value) -> str:
    """Kode CV dari field tersimpan; kosong/rusak = DA (data lama sebelum Tahap 8)."""
    try:
        v = normalize_entity(value, default=DEFAULT_ENTITY)
    except ValueError:
        return DEFAULT_ENTITY
    return v or DEFAULT_ENTITY


def _raw_from_request(request, body=None):
    raw = None
    if request is not None:
        try:
            raw = request.query_params.get("entity")
        except Exception:  # noqa: BLE001 — objek request tiruan di uji
            raw = None
    if (raw is None or str(raw).strip() == "") and isinstance(body, dict):
        raw = body.get("entity")
    if (raw is None or str(raw).strip() == "") and request is not None:
        try:
            raw = request.headers.get(ENTITY_HEADER)
        except Exception:  # noqa: BLE001
            raw = None
    return raw


def entity_from_request(request, body=None, *, allow_all: bool = False,
                        default: Optional[str] = DEFAULT_ENTITY) -> Optional[str]:
    """CV yang dipilih layar: query ``entity`` → body ``entity`` → header ``X-CV`` → ``default``.

    ``allow_all`` hanya untuk endpoint BACA (laporan/daftar). Endpoint tulis memakai bawaan
    (``allow_all=False``) sehingga Gabungan ditolak 400 dengan pesan yang jelas."""
    try:
        return normalize_entity(_raw_from_request(request, body), allow_all=allow_all, default=default)
    except ValueError as e:
        raise HTTPException(400, str(e))


def explicit_entity(request, body=None) -> Optional[str]:
    """CV yang DIKIRIM layar, atau None bila tidak dikirim (pemanggil memakai pemilik rekening)."""
    return entity_from_request(request, body, default=None)


def require_single(ent: Optional[str]) -> str:
    if ent == ALL:
        raise HTTPException(400, READONLY_ALL_MSG)
    return ent or DEFAULT_ENTITY


def entity_match(ent: Optional[str], field: str = "entity") -> dict:
    """Saringan Mongo untuk satu buku. DA ikut mencakup dokumen lama tanpa field (``None`` = tidak ada).
    ``ALL``/kosong → tanpa saringan (Gabungan = jumlah dua buku)."""
    if not ent or ent == ALL:
        return {}
    if ent == DA:
        return {field: {"$in": [DA, None]}}
    return {field: ent}


def matches_entity(doc_entity, ent: Optional[str]) -> bool:
    """Versi Python dari ``entity_match`` (untuk daftar yang disaring di memori)."""
    if not ent or ent == ALL:
        return True
    return entity_of_value(doc_entity) == ent


# ── CV jurnal otomatis per modul sumber (desain §4) ─────────────────────────────
# Semua jurnal Portal Maklon → SMU. Modul lain (toko, penjualan langsung, retur, stok, pembelian,
# produksi internal, HPP, gaji & uang karyawan) → DA. Modul "umum" (pengeluaran, kas kecil, transfer,
# aset, akrual, jurnal manual, saldo awal, tutup tahun) memakai CV yang dikirim layar / pemilik
# rekening — pemanggilnya meneruskan ``entity`` secara eksplisit.
MAKLON_SOURCE_MODULES = frozenset({
    "maklon_ar_invoice", "maklon_revenue", "maklon_payment", "maklon_advance_payment",
    "maklon_advance_apply", "maklon_reclass", "maklon_po", "maklon_billing", "maklon_invoice",
})


def entity_for_source_module(source_module: Optional[str]) -> str:
    return SMU if (source_module or "") in MAKLON_SOURCE_MODULES else DA


def is_maklon_po(po: Optional[dict]) -> bool:
    """PO maklon HANYA bila ``business_type == 'maklon'``. Tanpa jenis = internal (desain §9)."""
    return str((po or {}).get("business_type") or "").strip().lower() == "maklon"


def po_business_type(po: Optional[dict]) -> str:
    return "maklon" if is_maklon_po(po) else "internal"


def entity_for_business_type(business_type: Optional[str]) -> str:
    return SMU if str(business_type or "").strip().lower() == "maklon" else DA


def is_maklon_doc(doc: Optional[dict]) -> bool:
    """Dokumen milik alur maklon klien (piutang/tagihan/pembayaran maklon).

    ``cost_target == 'maklon'`` pada pengeluaran bahan/aksesoris SENGAJA tidak dihitung: barang itu
    stok DA, jadi jurnalnya tetap di buku DA sampai fase 2 membuat pasangan antar CV."""
    d = doc or {}
    if (d.get("source_module") or "") in MAKLON_SOURCE_MODULES:
        return True
    if d.get("linked_maklon_po_id"):
        return True
    if str(d.get("source") or "").lower() == "maklon":
        return True
    return is_maklon_po(d) if "business_type" in d else False


def entity_of_doc(doc: Optional[dict], default: str = DEFAULT_ENTITY) -> str:
    """CV dokumen sumber: field ``entity`` → penanda maklon → ``default``."""
    d = doc or {}
    if d.get("entity"):
        try:
            v = normalize_entity(d.get("entity"))
            if v:
                return v
        except ValueError:
            log.warning("entity dokumen tidak sah: %r", d.get("entity"))
    if is_maklon_doc(d):
        return SMU
    return default


async def entity_of_po_id(db, po_id: Optional[str]) -> str:
    """CV PO produksi: ``production_pos.business_type`` (maklon → SMU, lain/kosong → DA).
    PO yang hanya ada di ``dewi_maklon_pos`` (Portal Maklon) = SMU."""
    if not po_id:
        return DA
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "business_type": 1})
    if po is not None:
        return SMU if is_maklon_po(po) else DA
    if await db.dewi_maklon_pos.find_one({"id": po_id}, {"_id": 1}):
        return SMU
    return DA


async def cash_account_entity(db, *, account_id: Optional[str] = None,
                              gl_code: Optional[str] = None) -> Optional[str]:
    """Pemilik rekening kas/bank (None bila rekening tidak ditemukan)."""
    q = None
    if account_id:
        q = {"id": account_id}
    elif gl_code:
        q = {"gl_account_code": gl_code}
    if not q:
        return None
    acc = await db.rahaza_cash_accounts.find_one(q, {"_id": 0, "entity": 1})
    return entity_of_value(acc.get("entity")) if acc is not None else None


async def entity_for_posting(db, doc: Optional[dict], *, cash_account_id: Optional[str] = None,
                             cash_gl_code: Optional[str] = None, default: str = DEFAULT_ENTITY) -> str:
    """CV jurnal otomatis untuk dokumen UMUM: ``entity`` dokumen → penanda maklon → pemilik rekening → DA."""
    d = doc or {}
    if d.get("entity") or is_maklon_doc(d):
        return entity_of_doc(d, default)
    owner = await cash_account_entity(db, account_id=cash_account_id, gl_code=cash_gl_code)
    return owner or default


# ── Bagan akun: "berlaku untuk" (desain K10) ────────────────────────────────────
# Aturan kode (disetujui owner, BUKAN dari berkas privat). "Pohon" = kode itu sendiri, anak bernomor
# ``<kode>-…``, atau keturunan lewat ``parent_code``.
SMU_ONLY_TREES = ("1-1305", "4-1500", "1-1306")
SMU_ONLY_EXACT = ("4-1590", "2-1700")
SMU_ONLY_PATTERNS = (re.compile(r"^5-4\d{3}"),)
DA_ONLY_TREES = ("1-1303",)
DA_ONLY_EXACT = ("1-1304", "4-1200", "4-1300", "4-1400", "4-2300", "4-9200", "5-2100", "5-2200",
                 "6-1300", "2-1150", "2-1120", "1-1630", "6-4300")
DA_ONLY_PATTERNS = tuple(re.compile(p) for p in (r"^1-14\d\d", r"^4-11\d\d", r"^5-1\d{3}", r"^6-11\d\d",
                                                  r"^6-12\d\d", r"^6-14\d\d", r"^6-15\d\d"))
BOTH = [DA, SMU]


def _in_tree(code: str, roots: Iterable[str]) -> bool:
    return any(code == r or code.startswith(r + "-") for r in roots)


def code_rule_entities(code: Optional[str], ancestors: Iterable[Optional[str]] = ()) -> list:
    """CV yang boleh memakai akun menurut ATURAN KODE. ``ancestors`` = kode induk (pohon)."""
    c = str(code or "").strip()
    chain = [c] + [str(a).strip() for a in (ancestors or ()) if a]
    if any(_in_tree(x, SMU_ONLY_TREES) for x in chain) or c in SMU_ONLY_EXACT \
            or any(p.match(c) for p in SMU_ONLY_PATTERNS):
        return [SMU]
    if any(_in_tree(x, DA_ONLY_TREES) for x in chain) or c in DA_ONLY_EXACT \
            or any(p.match(c) for p in DA_ONLY_PATTERNS):
        return [DA]
    return list(BOTH)


def normalize_entities(value) -> list:
    """Isian "berlaku untuk" → daftar kode urut (DA, SMU). ValueError bila kosong/tidak dikenal."""
    if isinstance(value, str):
        v = value.strip().upper()
        if v in ("", "BOTH", "KEDUANYA", ALL, "GABUNGAN"):
            value = list(BOTH) if v else []
        else:
            value = [x for x in re.split(r"[,\s/]+", v) if x]
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("Isian 'berlaku untuk' harus daftar CV, mis. ['DA'] atau ['DA','SMU'].")
    out = set()
    for x in value:
        n = normalize_entity(x, allow_all=True)
        if n == ALL:
            out.update(BOTH)
        elif n:
            out.add(n)
    if not out:
        raise ValueError("Akun harus berlaku untuk minimal satu CV.")
    return [c for c in ENTITY_CODES if c in out]


def account_entities(acc: Optional[dict]) -> list:
    """CV yang boleh memakai akun: field ``entities`` (bila sah) → aturan kode (+ induk langsung)."""
    a = acc or {}
    raw = a.get("entities")
    if raw:
        try:
            return normalize_entities(raw)
        except ValueError:
            log.warning("entities akun %s tidak sah: %r", a.get("code"), raw)
    return code_rule_entities(a.get("code"), (a.get("parent_code"),))


def account_allowed(acc: Optional[dict], ent: str) -> bool:
    return ent in account_entities(acc)


async def inherited_entities(db, parent_code: Optional[str], code: Optional[str] = None) -> list:
    """"Berlaku untuk" akun BARU: ikut induk; tanpa induk → aturan kode."""
    if parent_code:
        parent = await db.rahaza_coa_accounts.find_one({"code": parent_code}, {"_id": 0})
        if parent is not None:
            return account_entities(parent)
    return code_rule_entities(code, (parent_code,))


async def entity_line_problems(db, lines: list, ent: str, accounts: Optional[dict] = None) -> list:
    """Alasan baris jurnal tidak cocok dengan CV ``ent`` (kosong = cocok).

    Dua pemeriksaan: (1) rekening kas/bank milik CV lain; (2) akun tidak berlaku untuk CV itu."""
    codes = sorted({str(ln.get("account_code") or "").strip() for ln in (lines or []) if ln.get("account_code")})
    if not codes or not ent or ent == ALL:
        return []
    accs = dict(accounts or {})
    missing = [c for c in codes if c not in accs]
    if missing:
        async for a in db.rahaza_coa_accounts.find({"code": {"$in": missing}},
                                                   {"_id": 0, "code": 1, "name": 1, "entities": 1, "parent_code": 1}):
            accs[a["code"]] = a
    owners = {}
    async for c in db.rahaza_cash_accounts.find({"gl_account_code": {"$in": codes}},
                                                {"_id": 0, "gl_account_code": 1, "entity": 1, "name": 1}):
        owners[c["gl_account_code"]] = (entity_of_value(c.get("entity")), c.get("name") or c["gl_account_code"])
    problems = []
    for code in codes:
        acc = accs.get(code) or {"code": code}
        own = owners.get(code)
        if own and own[0] != ent:
            problems.append(f"Rekening {own[1]} ({code}) milik {entity_short(own[0])}, bukan {entity_short(ent)}.")
        elif not own and not account_allowed(acc, ent):
            problems.append(f"Akun {code} {acc.get('name') or ''}".rstrip()
                            + f" tidak berlaku untuk {entity_short(ent)}.")
    return problems


def _problems_message(prefix: str, problems: list) -> str:
    head = " ".join(problems[:4])
    more = f" (dan {len(problems) - 4} lainnya)" if len(problems) > 4 else ""
    return f"{prefix} {head}{more}".strip()


async def validate_manual_lines(db, lines: list, ent: str, *, what: str = "Jurnal") -> None:
    """Penjaga isian MANUAL (jurnal, pengeluaran, faktur, transfer…): 400 bila akun/rekening tidak cocok."""
    problems = await entity_line_problems(db, lines, ent)
    if problems:
        raise HTTPException(400, _problems_message(f"{what} ditolak untuk {entity_short(ent)}:", problems))


async def validate_cash_account_owner(db, account_id: Optional[str], ent: str, *, what: str = "Transaksi") -> None:
    """400 bila rekening yang dipilih milik CV lain."""
    if not account_id or not ent or ent == ALL:
        return
    acc = await db.rahaza_cash_accounts.find_one({"id": account_id}, {"_id": 0, "entity": 1, "name": 1})
    if acc is None:
        return
    owner = entity_of_value(acc.get("entity"))
    if owner != ent:
        raise HTTPException(400, f"{what} ditolak: rekening {acc.get('name') or ''} milik {entity_short(owner)}, "
                                 f"bukan {entity_short(ent)}. Pilih rekening milik {entity_short(ent)}.")


def warning_text(problems: list) -> str:
    return _problems_message("Tidak cocok dengan CV jurnal:", problems)


# ── Profil perusahaan per CV (desain §5) ───────────────────────────────────────
# DA memakai dokumen lama `company_settings{type:'general'}` (supaya semua pembaca lama tetap DA);
# CV lain memakai `company_settings{type:'cv_profile', entity:<kode>}`.
PROFILE_TYPE = "cv_profile"
DEFAULT_PROFILE_NAMES = {DA: "CV. Dewi Aditya", SMU: "CV Sukma Mitra Utama"}


def profile_query(ent: Optional[str]) -> dict:
    e = entity_of_value(ent)
    return {"type": "general"} if e == DA else {"type": PROFILE_TYPE, "entity": e}


async def company_settings_doc(db, ent: Optional[str] = DEFAULT_ENTITY, projection: Optional[dict] = None) -> dict:
    """Dokumen pengaturan perusahaan CV ``ent`` (dict kosong bila belum ada)."""
    proj = projection or {"_id": 0}
    e = entity_of_value(ent)
    doc = await db.company_settings.find_one(profile_query(e), proj)
    if doc is None and e == DA:
        # Drift lama: dokumen tanpa `type`. Jangan sampai mengambil profil CV lain.
        doc = await db.company_settings.find_one({"type": {"$exists": False}}, proj)
    return doc or {}


# ── Akses CV per pengguna (Tahap 8 fase 3, opsional) ──────────────────────────
# `users.allowed_entities` = daftar CV yang boleh dibuka di Portal Keuangan. Kosong/tidak ada = KEDUA CV (bawaan,
# pengguna lama tidak berubah). Gabungan hanya untuk pengguna yang boleh kedua CV.
CV_ACCESS_DENIED_MSG = "Akses ditolak: akun Anda hanya diberi akses keuangan {allowed}. Pilih CV yang diizinkan."


def normalize_allowed(value) -> Optional[list]:
    """Isian akses CV pengguna → daftar urut (DA, SMU) atau None (= kedua CV). ValueError bila kode tidak dikenal."""
    if value in (None, "", [], "both", "BOTH", "KEDUANYA", "ALL"):
        return None
    vals = normalize_entities(value)
    return None if set(vals) == set(ENTITY_CODES) else vals


def allowed_of_user(user_doc: Optional[dict]) -> list:
    """CV yang boleh dibuka pengguna (selalu ≥ 1). Nilai rusak = kedua CV (tidak mengunci orang keluar)."""
    raw = (user_doc or {}).get("allowed_entities")
    try:
        vals = normalize_allowed(raw)
    except ValueError:
        log.warning("allowed_entities pengguna tidak sah: %r", raw)
        vals = None
    return list(vals) if vals else list(ENTITY_CODES)


def cv_access_problem(allowed: list, requested: Optional[str]) -> Optional[str]:
    """Pesan bila CV yang diminta (``requested``; kosong = DA) tidak boleh dibuka. Gabungan butuh kedua CV."""
    allowed = list(allowed or ENTITY_CODES)
    try:
        req = normalize_entity(requested, allow_all=True, default=DEFAULT_ENTITY)
    except ValueError:
        return None   # nilai tak dikenal ditangani endpoint (400)
    if req == ALL:
        ok = set(ENTITY_CODES) <= set(allowed)
    else:
        ok = req in allowed
    if ok:
        return None
    return CV_ACCESS_DENIED_MSG.format(allowed=" & ".join(entity_short(c) for c in allowed))


def entity_options_for(allowed: Optional[list] = None) -> list:
    """Pilihan CV untuk pengguna: hanya CV yang diizinkan; Gabungan bila kedua CV boleh."""
    allowed = list(allowed or ENTITY_CODES)
    opts = [o for o in entity_options() if o["code"] in allowed or (o["code"] == ALL and set(ENTITY_CODES) <= set(allowed))]
    return opts
