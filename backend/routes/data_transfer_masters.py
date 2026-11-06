"""routes/data_transfer_masters.py — impor Excel untuk master yang belum punya impor (T4, 2026-11-06).

Dipasang di Data Transfer yang SUDAH ADA (`routes/data_transfer.py`): endpoint, pratinjau → terapkan,
template, hak akses, dan log aktivitas tetap milik Data Transfer. Berkas ini hanya berisi PENANGAN
per master (tanpa router sendiri):

  suppliers        → rahaza_suppliers            Master Supplier (+ sub-akun hutang lewat Auto Akun)
  supplier_prices  → rahaza_supplier_price_lists sumber `/api/procurement/price-lookup` (harga PO)
  customers        → rahaza_customers            Master Pelanggan (+ sub-akun piutang lewat Auto Akun)
  holidays         → rahaza_production_calendar  dibaca `core.workdays` (pembagi gaji, hari cuti)
  wh_bins          → wh_buildings / wh_zones / wh_racks / wh_positions — struktur yang dipakai put-away
                     (`routes/wms_putaway.py`) dan resolver lokasi (`core/location_resolver.py`)

Judul kolom = judul kolom template owner (`kelengkapan_master_data_2026-11-06.xlsx`, sheet SUPPLIER,
KATALOG_HARGA_SUPPLIER, PELANGGAN, KALENDER_LIBUR, LOKASI_BIN). Saat mencocokkan judul: tanda `*`,
keterangan dalam kurung, dan huruf besar/kecil diabaikan; kolom "(info)" yang tidak dikenal dilewati.

Aturan baris:
  * baris yang kolom pertamanya diawali `#` = baris contoh/catatan → dilewati;
  * kolom "Setuju? (owner)" berisi "Tidak" → dilewati (owner tidak menyetujui baris itu);
  * sel kosong pada baris yang memperbarui data lama = TIDAK mengubah field itu.

Setiap penangan punya `prepare` (validasi, tanpa menulis) dan `commit` (menjalankan ulang `prepare`
pada data terbaru lalu upsert idempoten), plus `export` (isi sekarang dalam format template, supaya
bisa diunduh, diubah, lalu diunggah lagi).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException

log = logging.getLogger(__name__)


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Judul kolom & nilai sel
# ─────────────────────────────────────────────────────────────────────────────
_PAREN_RX = re.compile(r"\([^)]*\)")


def norm_header(h) -> str:
    """'tanggal * (YYYY-MM-DD)' → 'tanggal'; 'Setuju? (owner)' → 'setuju'; 'nama *' → 'nama'."""
    s = _PAREN_RX.sub(" ", str(h or ""))
    return re.sub(r"[^0-9a-z]+", "_", s.lower()).strip("_")


def _key(s) -> str:
    """Kunci pencocokan teks pilihan: huruf kecil, tanpa spasi/tanda baca ('NET 14' → 'net14')."""
    return re.sub(r"[^0-9a-z]", "", str(s or "").lower())


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Ya" if v else "Tidak"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _to_num(v):
    """Angka dari sel. Sel angka Excel dipakai apa adanya. Teks: 'Rp 1.234.567', '1.234,5', '47,5'.
    Teks bertitik/berkoma tunggal dengan tepat 3 digit di belakang ('47.500', '47,500') AMBIGU
    (ribuan atau desimal?) → ValueError, supaya tidak salah baca diam-diam (pola P5)."""
    if isinstance(v, bool):
        raise ValueError("bukan angka")
    if isinstance(v, (int, float)):
        return float(v)
    s = _s(v).lower().replace("rp", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        sep = "," if "," in s else ("." if "." in s else "")
        if sep:
            parts = s.lstrip("-").split(sep)
            if len(parts) > 2:
                if not all(len(p) == 3 for p in parts[1:]):
                    raise ValueError("format angka tidak dikenal")
                s = s.replace(sep, "")
            elif len(parts[1]) == 3 and 1 <= len(parts[0]) <= 3:
                raise ValueError("ambigu")
            else:
                s = s.replace(",", ".")
    return float(s)


def _num(row: dict, col: str, label: str, errs: list, *, integer: bool = False, min_value: float = 0):
    v = row.get(col)
    if _blank(v):
        return None
    try:
        f = _to_num(v)
    except (TypeError, ValueError) as e:
        if str(e) == "ambigu":
            errs.append(f"'{label}': angka '{_s(v)}' ambigu — tulis tanpa titik ribuan (mis. 47500) "
                        "atau pakai koma untuk desimal (mis. 47,5)")
        else:
            errs.append(f"'{label}': '{_s(v)}' bukan angka")
        return None
    if f is None:
        return None
    if integer and not float(f).is_integer():
        errs.append(f"'{label}': harus bilangan bulat ('{_s(v)}')")
        return None
    if f < min_value:
        errs.append(f"'{label}': tidak boleh kurang dari {min_value:g}")
        return None
    return int(f) if integer else f


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")


def _date(row: dict, col: str, label: str, errs: list):
    v = row.get(col)
    if _blank(v):
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = _s(v)
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", s):
        s = s[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    errs.append(f"'{label}': tanggal '{s}' tidak dikenal (pakai TTTT-BB-HH, mis. 2026-12-25)")
    return None


def _bool(row: dict, col: str, label: str, errs: list):
    v = row.get(col)
    if _blank(v):
        return None
    if isinstance(v, bool):
        return v
    from routes.data_transfer import FALSE_SET, TRUE_SET
    low = _s(v).lower()
    if low in TRUE_SET:
        return True
    if low in FALSE_SET:
        return False
    errs.append(f"'{label}': isi Ya atau Tidak ('{_s(v)}')")
    return None


def _choice(value, table: dict):
    """Cocokkan teks pilihan ke nilai internal lewat `_key`. `table` = {kunci: nilai}."""
    return table.get(_key(value))


def C(name: str, header: str, *, required: bool = False, example="", help: str = "",
      choices=None, aliases=()) -> dict:
    """Satu kolom template. `header` = judul kolom persis seperti template owner."""
    return {"name": name, "header": header, "label": header, "type": "str", "required": required,
            "example": example, "help": help, "choices": list(choices or []), "aliases": list(aliases)}


def _short(c: dict) -> str:
    """Nama kolom pendek untuk pesan galat ('termin_bayar *' → 'termin_bayar')."""
    return norm_header(c["header"]) or c["name"]


def map_rows(raw_rows: list, columns: list) -> list:
    """Baris mentah (judul apa adanya) → baris berkunci nama kolom internal."""
    amap = {}
    for c in columns:
        amap[norm_header(c["header"])] = c["name"]
        for a in c["aliases"]:
            amap.setdefault(norm_header(a), c["name"])
    out = []
    for idx, raw in enumerate(raw_rows):
        row = {"__row__": raw.get("__row__") or idx + 2}
        for k, v in raw.items():
            if k == "__row__":
                continue
            n = amap.get(norm_header(k))
            if n and (n not in row or _blank(row[n])):
                row[n] = v
        out.append(row)
    return out


class Prepared:
    """Hasil `prepare`: baris sah (rencana + info pratinjau), baris galat, baris dilewati."""

    def __init__(self):
        self.valid: list = []      # [(plan, info)]
        self.invalid: list = []    # [info + errors]
        self.skipped: list = []    # [info + reason]

    def add(self, info: dict, errs: list, plan=None):
        if errs:
            info["errors"] = errs
            self.invalid.append(info)
        else:
            self.valid.append((plan, info))

    def reject(self, info: dict, errs: list):
        """Pindahkan baris yang sudah sah ke galat (pemeriksaan lintas-baris)."""
        self.valid = [(p, i) for p, i in self.valid if i is not info]
        info["errors"] = (info.get("errors") or []) + errs
        self.invalid.append(info)


def _skip_reason(row: dict, first_col: str):
    if _s(row.get(first_col)).startswith("#"):
        return "baris contoh/catatan (kolom pertama diawali #)"
    if _key(row.get("approve")) == "tidak":
        return "owner tidak menyetujui baris ini (Setuju? = Tidak)"
    return None


def _start(prep: Prepared, row: dict, first_col: str) -> dict | None:
    """Info pratinjau awal untuk satu baris; None bila baris dilewati."""
    info = {"row": row["__row__"], "data": {}}
    why = _skip_reason(row, first_col)
    if why:
        info["reason"] = why
        info["data"] = {"isi": _s(row.get(first_col))}
        prep.skipped.append(info)
        return None
    return info


_APPROVE = C("approve", "Setuju? (owner)", help="Isi Tidak untuk melewati baris ini.")


def _required(row: dict, columns: list, errs: list):
    for c in columns:
        if c["required"] and _blank(row.get(c["name"])):
            errs.append(f"'{_short(c)}' wajib diisi")


async def auto_subledger(db, entity_type: str, doc: dict, user: dict) -> None:
    """Sub-akun Buku Besar per entitas lewat Auto Akun yang SUDAH ADA (idempoten, tidak fatal).

    Dipakai impor generik dan impor master di berkas ini. 2026-08-07: dulu `pass` diam-diam;
    impor ratusan baris tanpa log = tidak bisa tahu entitas mana yang tak punya akun.
    """
    if not doc or not doc.get("id"):
        return
    try:
        from routes.coa_auto import ensure_subledger_for_entity
        res = await ensure_subledger_for_entity(db, entity_type, doc, user)
        if isinstance(res, dict) and not res.get("ok") and not res.get("skipped"):
            log.error("[coa] impor: subledger COA (%s) GAGAL untuk %s: %s",
                      entity_type, doc.get("name") or doc.get("id"), res.get("error"))
    except Exception as e:  # noqa: BLE001
        log.error("[coa] impor: subledger COA (%s) GAGAL untuk %s — entitas ini tidak punya akun "
                  "Buku Besar: %s", entity_type, doc.get("name") or doc.get("id"), e)


# ═════════════════════════════════════════════════════════════════════════════
# 1. MASTER SUPPLIER  (rahaza_suppliers)
# ═════════════════════════════════════════════════════════════════════════════
SUPPLIER_COLUMNS = [
    C("code", "kode (kosongkan = otomatis)", example="#CONTOH", aliases=("kode_supplier",),
      help="Kosongkan untuk supplier baru (sistem memberi SUP-0001 dst.). Isi kode lama untuk memperbarui."),
    C("name", "nama *", required=True, example="PT Contoh Tekstil", aliases=("nama_usaha", "nama_supplier")),
    C("tax_status", "status_pajak *", required=True, example="PKP", choices=["PKP", "non-PKP"],
      aliases=("status_pkp",)),
    C("npwp", "npwp"),
    C("tax_name", "nama_di_npwp"),
    C("address", "alamat"),
    C("city", "kota"),
    C("province", "provinsi"),
    C("postal_code", "kode_pos"),
    C("phone", "telepon"),
    C("email", "email"),
    C("contact_name", "kontak_nama", aliases=("kontak",)),
    C("contact_position", "kontak_jabatan"),
    C("contact_phone", "kontak_hp"),
    C("terms", "termin_bayar *", required=True, example="NET 30",
      choices=["COD", "CBD", "NET 7", "NET 14", "NET 30", "NET 45", "NET 60", "NET 90"],
      aliases=("termin", "termin_bayar_hari")),
    C("currency", "mata_uang", example="IDR"),
    C("bank_name", "bank"),
    C("account_number", "no_rekening"),
    C("account_holder", "atas_nama_rekening", aliases=("atas_nama",)),
    C("categories", "kategori_barang", example="Kain, Aksesoris",
      help="Pisahkan dengan koma. Pilihan: Benang, Kain, Aksesoris, Kemasan, Kimia / Pewarna, "
           "Suku Cadang Mesin, ATK / Kantor, Aset / Mesin, Jasa, Lainnya."),
    C("lead_time_days", "lama_kirim_hari"),
    C("min_order_value", "min_order_rp"),
    C("notes", "catatan"),
    C("active", "aktif", choices=["Ya", "Tidak"]),
]


def _term_label(v: str) -> str:
    v = str(v or "")
    return f"NET {v[3:]}" if v.startswith("net") else v.upper()


def _supplier_terms(value):
    from routes.procurement_suppliers import PAYMENT_TERMS, PAYMENT_TERM_DAYS
    k = _key(value).replace("hari", "")
    if k in PAYMENT_TERM_DAYS:
        return k
    if k.isdigit() and f"net{k}" in PAYMENT_TERM_DAYS:
        return f"net{k}"
    for t in PAYMENT_TERMS:
        if _key(t["label"]) == _key(value):
            return t["value"]
    return None


def _tax_type(value):
    k = _key(value)
    if k.startswith("non") or k in ("tidak", "bukanpkp", "tidakpkp"):
        return "non_ppn"
    if k in ("pkp", "ppn", "pkpkenappn", "kenappn"):
        return "ppn"
    return None


def _categories(value) -> tuple:
    from routes.procurement_suppliers import SUPPLIER_CATEGORIES
    lut = {}
    for c in SUPPLIER_CATEGORIES:
        lut[_key(c["value"])] = c["value"]
        lut[_key(c["label"])] = c["value"]
    out, bad = [], []
    for part in re.split(r"[,;|\n]+", _s(value)):
        p = part.strip()
        if not p:
            continue
        val = lut.get(_key(p))
        if val and val not in out:
            out.append(val)
        elif not val:
            bad.append(p)
    return out, bad


def _merge_primary(items, fields: dict) -> list:
    """Isi/ubah entri UTAMA (kontak / rekening) dengan field dari berkas; entri lain dibiarkan."""
    lst = [dict(x) for x in (items or []) if isinstance(x, dict)]
    prim = next((x for x in lst if x.get("is_primary")), lst[0] if lst else None)
    if prim is None:
        prim = {"is_primary": True}
        lst.insert(0, prim)
    prim.update(fields)
    return lst


async def _supplier_index(db) -> tuple:
    from routes.procurement_suppliers import name_key
    by_code, by_key = {}, {}
    async for s in db.rahaza_suppliers.find({}, {"_id": 0}):
        if s.get("code"):
            by_code[str(s["code"]).upper()] = s
        k = s.get("name_key") or name_key(s.get("name"))
        if k:
            by_key.setdefault(k, s)
    return by_code, by_key


async def prepare_suppliers(db, raw_rows: list, user: dict) -> Prepared:
    from routes.procurement_suppliers import CURRENCIES, _supplier_doc_from_body, name_key
    prep = Prepared()
    by_code, by_key = await _supplier_index(db)
    seen_code, seen_key = {}, {}
    for row in map_rows(raw_rows, SUPPLIER_COLUMNS):
        info = _start(prep, row, "code")
        if info is None:
            continue
        errs: list = []
        _required(row, SUPPLIER_COLUMNS, errs)
        name = _s(row.get("name"))
        code = _s(row.get("code")).upper()
        nk = name_key(name) if name else ""
        tax = _tax_type(row.get("tax_status")) if not _blank(row.get("tax_status")) else None
        if not _blank(row.get("tax_status")) and not tax:
            errs.append(f"'status_pajak': '{_s(row.get('tax_status'))}' tidak dikenal (isi PKP atau non-PKP)")
        terms = _supplier_terms(row.get("terms")) if not _blank(row.get("terms")) else None
        if not _blank(row.get("terms")) and not terms:
            errs.append(f"'termin_bayar': '{_s(row.get('terms'))}' tidak dikenal "
                        "(pilihan: COD, CBD, NET 7, NET 14, NET 30, NET 45, NET 60, NET 90)")
        currency = _s(row.get("currency")).upper()
        if currency and currency not in CURRENCIES:
            errs.append(f"'mata_uang': '{currency}' tidak dikenal (pilihan: {', '.join(CURRENCIES)})")
        email = _s(row.get("email")).lower()
        if email and "@" not in email:
            errs.append(f"'email': '{email}' bukan alamat email")
        lead = _num(row, "lead_time_days", "lama_kirim_hari", errs, integer=True)
        mov = _num(row, "min_order_value", "min_order_rp", errs)
        active = _bool(row, "active", "aktif", errs)
        cats, bad = _categories(row.get("categories")) if not _blank(row.get("categories")) else ([], [])
        if bad:
            errs.append(f"'kategori_barang': {', '.join(repr(b) for b in bad)} tidak dikenal (pilihan: Benang, "
                        "Kain, Aksesoris, Kemasan, Kimia / Pewarna, Suku Cadang Mesin, ATK / Kantor, "
                        "Aset / Mesin, Jasa, Lainnya)")

        # ── cocokkan: kode dulu, lalu nama ternormalisasi (SUP-2) ─────────────
        cur = None
        if code:
            cur = by_code.get(code)
            other = by_key.get(nk) if nk else None
            if other and (not cur or other.get("id") != cur.get("id")):
                errs.append(f"nama '{name}' sudah dipakai supplier {other.get('code')} ({other.get('name')}) — "
                            f"pakai kode {other.get('code')} atau kosongkan kolom kode")
        elif nk:
            cur = by_key.get(nk)
        for k, seen, what in ((code, seen_code, "kode"), (nk, seen_key, "nama")):
            if k and k in seen:
                errs.append(f"{what} '{code if what == 'kode' else name}' sudah ada di baris {seen[k]} berkas ini")
            elif k:
                seen[k] = info["row"]

        info["action"] = "update" if cur else "insert"
        info["data"] = {"kode": code or (cur or {}).get("code") or "(otomatis)", "nama": name,
                        "pajak": "PKP" if tax == "ppn" else ("non-PKP" if tax else ""),
                        "termin": _term_label(terms) if terms else ""}
        if errs:
            prep.add(info, errs)
            continue

        body: dict = {"name": name, "tax_type": tax, "payment_terms": terms}
        for fld in ("npwp", "tax_name", "address", "city", "province", "postal_code", "phone", "notes"):
            if not _blank(row.get(fld)):
                body[fld] = _s(row.get(fld))
        if email:
            body["email"] = email
        if currency:
            body["currency"] = currency
        if lead is not None:
            body["lead_time_days"] = lead
        if mov is not None:
            body["min_order_value"] = mov
        if cats:
            body["categories"] = cats
        contact = {k: _s(row.get(src)) for k, src in (("name", "contact_name"), ("position", "contact_position"),
                                                     ("phone", "contact_phone")) if not _blank(row.get(src))}
        if contact:
            body["contacts"] = _merge_primary((cur or {}).get("contacts"), contact)
        bank = {k: _s(row.get(src)) for k, src in (("bank_name", "bank_name"), ("account_number", "account_number"),
                                                  ("account_holder", "account_holder")) if not _blank(row.get(src))}
        if bank:
            body["bank_accounts"] = _merge_primary((cur or {}).get("bank_accounts"), bank)
        if active is not None:
            body["is_active"] = active
        doc = _supplier_doc_from_body(body, current=cur)
        prep.add(info, [], {"cur": cur, "doc": doc, "code": code})
    return prep


async def commit_suppliers(db, prep: Prepared, user: dict) -> tuple:
    from routes.procurement_suppliers import _gen_supplier_code, sync_po_vendor_name
    inserted = updated = 0
    for plan, _info in prep.valid:
        cur, doc = plan["cur"], dict(plan["doc"])
        doc["updated_at"] = _now()
        if cur:
            await db.rahaza_suppliers.update_one({"id": cur["id"]}, {"$set": doc})
            await sync_po_vendor_name(db, cur["id"], doc.get("name"), cur.get("name"))
            sid = cur["id"]
            updated += 1
        else:
            sid = _uid()
            await db.rahaza_suppliers.insert_one({
                "id": sid, "code": plan["code"] or await _gen_supplier_code(db), **doc,
                "is_active": doc.get("is_active", True), "source": "import",
                "created_at": _now(), "created_by": user.get("id"), "created_by_name": user.get("name", ""),
            })
            inserted += 1
        # Sub-akun hutang per supplier lewat Auto Akun — SESUDAH supplier tersimpan.
        await auto_subledger(db, "supplier", await db.rahaza_suppliers.find_one({"id": sid}, {"_id": 0}), user)
    return inserted, updated


async def export_suppliers(db) -> list:
    from routes.procurement_suppliers import SUPPLIER_CATEGORIES
    cat_label = {c["value"]: c["label"] for c in SUPPLIER_CATEGORIES}
    out = []
    async for s in db.rahaza_suppliers.find({}, {"_id": 0}).sort("code", 1):
        ct = next((c for c in s.get("contacts") or [] if c.get("is_primary")), (s.get("contacts") or [{}])[0])
        bk = next((b for b in s.get("bank_accounts") or [] if b.get("is_primary")),
                  (s.get("bank_accounts") or [{}])[0])
        out.append({
            "code": s.get("code"), "name": s.get("name"),
            "tax_status": "PKP" if s.get("tax_type", "ppn") == "ppn" else "non-PKP",
            "npwp": s.get("npwp"), "tax_name": s.get("tax_name"), "address": s.get("address"),
            "city": s.get("city"), "province": s.get("province"), "postal_code": s.get("postal_code"),
            "phone": s.get("phone"), "email": s.get("email"),
            "contact_name": ct.get("name"), "contact_position": ct.get("position"), "contact_phone": ct.get("phone"),
            "terms": _term_label(s.get("payment_terms")), "currency": s.get("currency"),
            "bank_name": bk.get("bank_name"), "account_number": bk.get("account_number"),
            "account_holder": bk.get("account_holder"),
            "categories": ", ".join(cat_label.get(c, c) for c in s.get("categories") or []),
            "lead_time_days": s.get("lead_time_days"), "min_order_value": s.get("min_order_value"),
            "notes": s.get("notes"), "active": "Tidak" if s.get("is_active") is False else "Ya",
        })
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 2. DAFTAR HARGA SUPPLIER  (rahaza_supplier_price_lists — sumber /procurement/price-lookup)
# ═════════════════════════════════════════════════════════════════════════════
PRICE_COLUMNS = [
    C("supplier", "nama_supplier *", required=True, example="#CONTOH",
      aliases=("supplier", "kode_supplier", "nama_atau_kode_supplier"),
      help="Nama atau kode supplier yang sudah ada di Master Supplier."),
    C("material_code", "kode_material *", required=True, example="KN-K20-BRG", aliases=("kode_bahan",)),
    C("uom", "satuan_beli *", required=True, example="kg",
      help="Harus salah satu satuan bahan itu (satuan dasar atau kemasannya)."),
    C("price", "harga_per_satuan_beli *", required=True, example="47500", aliases=("harga",)),
    C("factor", "isi_per_satuan_beli", example="1",
      help="Opsional. Isi 1 satuan beli dalam satuan dasar; harus sama dengan master bahan."),
    C("currency", "mata_uang", example="IDR"),
    C("moq", "moq"),
    C("lead_time_days", "lama_kirim_hari"),
    C("valid_from", "berlaku_mulai *", required=True, example="2026-11-01"),
    C("valid_to", "berlaku_sampai", help="Kosongkan bila berlaku seterusnya."),
    C("active", "aktif", example="Ya", choices=["Ya", "Tidak"]),
    C("notes", "catatan"),
]
_PRICE_ALL = PRICE_COLUMNS + [_APPROVE]


def _overlap(a: dict, b: dict) -> bool:
    end = "9999-12-31"
    return a["from"] <= (b["to"] or end) and b["from"] <= (a["to"] or end)


def _period(p: dict) -> str:
    return f"{p['from']} s.d. {p['to'] or 'seterusnya'}"


async def prepare_supplier_prices(db, raw_rows: list, user: dict) -> Prepared:
    from core import uom as uom_core
    from routes.procurement_suppliers import CURRENCIES, _price_row_from_body, name_key
    prep = Prepared()
    rows = map_rows(raw_rows, _PRICE_ALL)
    by_code, by_key = await _supplier_index(db)

    codes = {_s(r.get("material_code")) for r in rows if not _blank(r.get("material_code"))}
    mats: dict = {}
    if codes:
        async for m in db.rahaza_materials.find({"code": {"$in": sorted(codes | {c.upper() for c in codes})}},
                                                {"_id": 0}):
            mats.setdefault(str(m.get("code") or "").upper(), m)

    planned = []   # [(plan, info)] sebelum pemeriksaan periode
    for row in rows:
        info = _start(prep, row, "supplier")
        if info is None:
            continue
        errs: list = []
        _required(row, PRICE_COLUMNS, errs)
        sup_txt = _s(row.get("supplier"))
        sup = by_code.get(sup_txt.upper()) or by_key.get(name_key(sup_txt)) if sup_txt else None
        if sup_txt and not sup:
            errs.append(f"supplier '{sup_txt}' belum ada di Master Supplier — impor/isi supplier dulu")
        mcode = _s(row.get("material_code")).upper()
        mat = mats.get(mcode) if mcode else None
        if mcode and not mat:
            errs.append(f"kode material '{mcode}' tidak ada di master bahan")
        uom = uom_core.normalize_code(row.get("uom"))
        urow = uom_core.find_uom(mat, uom) if (mat and uom) else None
        if mat and uom and not urow:
            errs.append(f"satuan beli '{uom}' bukan satuan bahan {mcode} "
                        f"(tersedia: {', '.join(uom_core.uom_codes(mat))})")
        factor = _num(row, "factor", "isi_per_satuan_beli", errs, min_value=0)
        if urow and factor is not None and abs(float(factor) - float(urow["factor"])) > 1e-6:
            errs.append(f"'isi_per_satuan_beli' {factor:g} tidak sama dengan master bahan "
                        f"(1 {uom} = {urow['factor']:g} {uom_core.base_uom_of(mat)}); ubah satuan di master "
                        "bahan bila memang berbeda")
        price = _num(row, "price", "harga_per_satuan_beli", errs, min_value=0)
        currency = _s(row.get("currency")).upper()
        if currency and currency not in CURRENCIES:
            errs.append(f"'mata_uang': '{currency}' tidak dikenal (pilihan: {', '.join(CURRENCIES)})")
        moq = _num(row, "moq", "moq", errs)
        lead = _num(row, "lead_time_days", "lama_kirim_hari", errs, integer=True)
        vfrom = _date(row, "valid_from", "berlaku_mulai", errs)
        vto = _date(row, "valid_to", "berlaku_sampai", errs)
        if vfrom and vto and vto < vfrom:
            errs.append("'berlaku_sampai' lebih awal dari 'berlaku_mulai'")
        active = _bool(row, "active", "aktif", errs)
        info["data"] = {"supplier": (sup or {}).get("name") or sup_txt, "material": mcode, "satuan": uom,
                        "harga": price if price is not None else "",
                        "berlaku": f"{vfrom or '?'} s.d. {vto or 'seterusnya'}"}
        if errs:
            prep.add(info, errs)
            continue
        body = {"material_id": mat["id"], "uom": uom, "price": price, "valid_from": vfrom, "valid_to": vto,
                "is_active": True if active is None else active}
        for k, v in (("currency", currency), ("moq", moq), ("lead_time_days", lead)):
            if v not in (None, ""):
                body[k] = v
        if not _blank(row.get("notes")):
            body["notes"] = _s(row.get("notes"))
        planned.append(({"supplier": sup, "mat": mat, "body": body}, info))

    # ── baris lama: kunci (supplier, bahan, satuan, berlaku_mulai) → diperbarui, bukan digandakan ──
    mids = sorted({p["mat"]["id"] for p, _ in planned})
    existing: list = []
    if mids:
        async for r in db.rahaza_supplier_price_lists.find({"material_id": {"$in": mids}}, {"_id": 0}):
            existing.append(r)
    by_k4 = {(r.get("supplier_id"), r.get("material_id"), r.get("uom"), str(r.get("valid_from") or "")[:10]): r
             for r in existing}
    seen_k4: dict = {}
    for plan, info in planned:
        b = plan["body"]
        k4 = (plan["supplier"]["id"], b["material_id"], b["uom"], b["valid_from"])
        if k4 in seen_k4:
            prep.add(info, [f"harga supplier+bahan+satuan+berlaku_mulai yang sama sudah ada di baris {seen_k4[k4]}"])
            continue
        seen_k4[k4] = info["row"]
        cur = by_k4.get(k4)
        try:
            doc = await _price_row_from_body(db, plan["supplier"]["id"], b, cur)
        except HTTPException as e:
            prep.add(info, [str(e.detail)])
            continue
        plan.update({"cur": cur, "doc": doc, "k4": k4})
        info["action"] = "update" if cur else "insert"
        prep.add(info, [], plan)

    # ── periode tidak boleh tumpang-tindih (supplier + bahan + satuan), hasil SESUDAH impor ─────────
    replaced = {p["cur"]["id"] for p, _ in prep.valid if p.get("cur")}
    groups: dict = {}
    for r in existing:
        if r.get("is_active") and r.get("id") not in replaced:
            groups.setdefault((r.get("supplier_id"), r.get("material_id"), r.get("uom")), []).append(
                {"from": str(r.get("valid_from") or "")[:10], "to": (str(r.get("valid_to"))[:10]
                                                                    if r.get("valid_to") else None),
                 "row": None})
    for plan, info in list(prep.valid):
        d = plan["doc"]
        if not d.get("is_active"):
            continue
        me = {"from": d["valid_from"], "to": d.get("valid_to"), "row": info["row"], "info": info}
        bad = []
        for other in groups.setdefault(plan["k4"][:3], []):
            if _overlap(me, other):
                bad.append(f"periode {_period(me)} bentrok dengan "
                           + (f"baris {other['row']} ({_period(other)})" if other["row"]
                              else f"harga yang sudah ada ({_period(other)}) — isi 'berlaku_sampai' harga lama "
                                   "(sertakan barisnya di berkas ini) atau ubah 'berlaku_mulai'"))
        if bad:
            prep.reject(info, bad)
        else:
            groups[plan["k4"][:3]].append(me)
    return prep


async def commit_supplier_prices(db, prep: Prepared, user: dict) -> tuple:
    inserted = updated = 0
    for plan, _info in prep.valid:
        doc = dict(plan["doc"])
        if plan.get("cur"):
            await db.rahaza_supplier_price_lists.update_one({"id": plan["cur"]["id"]}, {"$set": doc})
            updated += 1
        else:
            doc.update({"id": _uid(), "created_at": _now(), "created_by": user.get("id"), "source": "import"})
            await db.rahaza_supplier_price_lists.insert_one(doc)
            inserted += 1
    return inserted, updated


async def export_supplier_prices(db) -> list:
    sups = {}
    async for s in db.rahaza_suppliers.find({}, {"_id": 0, "id": 1, "code": 1, "name": 1}):
        sups[s["id"]] = s
    out = []
    async for r in db.rahaza_supplier_price_lists.find({}, {"_id": 0}).sort("material_code", 1):
        out.append({
            "supplier": (sups.get(r.get("supplier_id")) or {}).get("name") or r.get("supplier_id"),
            "material_code": r.get("material_code"), "uom": r.get("uom"), "price": r.get("price"),
            "factor": r.get("factor_to_base"), "currency": r.get("currency"), "moq": r.get("moq"),
            "lead_time_days": r.get("lead_time_days"), "valid_from": r.get("valid_from"),
            "valid_to": r.get("valid_to"), "active": "Ya" if r.get("is_active") else "Tidak",
            "notes": r.get("notes"),
        })
    out.sort(key=lambda x: (str(x["supplier"] or ""), str(x["material_code"] or ""), str(x["valid_from"] or "")))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 3. MASTER PELANGGAN  (rahaza_customers — dipakai Penjualan Langsung & piutang AR)
# ═════════════════════════════════════════════════════════════════════════════
CUSTOMER_COLUMNS = [
    C("code", "kode (kosongkan = otomatis)", example="#CONTOH", aliases=("kode_pelanggan",),
      help="Kosongkan untuk pelanggan baru bila penomoran Kode Pelanggan otomatis."),
    C("name", "nama *", required=True, example="Toko Contoh Grosir", aliases=("nama_pelanggan",)),
    C("company_type", "jenis", example="badan usaha", choices=["perorangan", "badan usaha"]),
    C("npwp", "npwp"),
    C("phone", "telepon"),
    C("email", "email"),
    C("address", "alamat"),
    C("payment_terms", "termin", example="NET 14", choices=["tunai", "NET 7", "NET 14", "NET 30"],
      aliases=("termin_bayar",)),
    C("credit_limit", "batas_kredit_rp", example="5000000", aliases=("limit_kredit", "batas_kredit")),
    C("notes", "catatan"),
    C("active", "aktif", choices=["Ya", "Tidak"]),
]
_COMPANY_TYPES = {"perorangan": "personal", "personal": "personal", "pribadi": "personal",
                  "badanusaha": "company", "perusahaan": "company", "company": "company", "badan": "company"}


def _customer_terms(value):
    from routes.sales_direct import TERMS_DAYS
    k = _key(value).replace("hari", "").replace("tempo", "net")
    if k in ("tunai", "cash", "cod"):
        return "cash"
    if k.isdigit():
        k = f"net{k}"
    k = k.replace("net", "net_") if k.startswith("net") else k
    return k if k in TERMS_DAYS else None


def _customer_terms_label(v) -> str:
    return "tunai" if v == "cash" else (f"NET {str(v)[4:]}" if str(v or "").startswith("net_") else str(v or ""))


async def prepare_customers(db, raw_rows: list, user: dict) -> Prepared:
    from core.doc_number_policy import policy
    from routes.procurement_suppliers import name_key
    prep = Prepared()
    pol = await policy(db, "rahaza_customers.code")
    by_code, by_key = {}, {}
    async for c in db.rahaza_customers.find({}, {"_id": 0}):
        if c.get("code"):
            prev = by_code.get(str(c["code"]).upper())
            if not prev or c.get("active") is not False:
                by_code[str(c["code"]).upper()] = c
        k = name_key(c.get("name"))
        if k:
            by_key.setdefault(k, []).append(c)
    seen_code, seen_key = {}, {}
    for row in map_rows(raw_rows, CUSTOMER_COLUMNS):
        info = _start(prep, row, "code")
        if info is None:
            continue
        errs: list = []
        _required(row, CUSTOMER_COLUMNS, errs)
        name = _s(row.get("name"))
        code = _s(row.get("code")).upper()
        nk = name_key(name) if name else ""
        ctype = _choice(row.get("company_type"), _COMPANY_TYPES) if not _blank(row.get("company_type")) else None
        if not _blank(row.get("company_type")) and not ctype:
            errs.append(f"'jenis': '{_s(row.get('company_type'))}' tidak dikenal (isi perorangan atau badan usaha)")
        terms = _customer_terms(row.get("payment_terms")) if not _blank(row.get("payment_terms")) else None
        if not _blank(row.get("payment_terms")) and not terms:
            errs.append(f"'termin': '{_s(row.get('payment_terms'))}' tidak dikenal (pilihan: tunai, NET 7, NET 14, NET 30)")
        limit = _num(row, "credit_limit", "batas_kredit_rp", errs)
        email = _s(row.get("email"))
        if email and "@" not in email:
            errs.append(f"'email': '{email}' bukan alamat email")
        active = _bool(row, "active", "aktif", errs)

        cur = by_code.get(code) if code else None
        if not cur and not code and nk:
            same = by_key.get(nk) or []
            if len(same) > 1:
                errs.append(f"nama '{name}' cocok dengan {len(same)} pelanggan "
                            f"({', '.join(str(c.get('code')) for c in same)}) — isi kolom kode")
            elif same:
                cur = same[0]
        if not cur and code and nk and by_key.get(nk):
            other = by_key[nk][0]
            errs.append(f"nama '{name}' sudah dipakai pelanggan {other.get('code')} — pakai kode itu "
                        "atau kosongkan kolom kode")
        if not cur:
            # pelanggan BARU: nomor mengikuti kebijakan Penomoran Dokumen (sama dengan form)
            if code and pol["mode"] == "auto":
                errs.append("kode pelanggan baru harus dikosongkan: penomoran Kode Pelanggan disetel OTOMATIS "
                            "(ubah ke manual di Administrasi Sistem → Penomoran Dokumen bila ingin mengetik kode)")
            elif code and pol.get("error"):
                errs.append(f"format Kode Pelanggan tidak sah ({pol['error']}) — perbaiki di Penomoran Dokumen")
            elif code and not re.match(pol["pola"], code):
                errs.append(f"kode '{code}' tidak mengikuti pola {pol['format']} (contoh: {pol['contoh']})")
            elif not code and pol["mode"] == "manual":
                errs.append(f"kode wajib diisi: penomoran Kode Pelanggan disetel MANUAL (pola {pol['format']})")
        for k, seen, what in ((code, seen_code, "kode"), (nk, seen_key, "nama")):
            if k and k in seen:
                errs.append(f"{what} '{code if what == 'kode' else name}' sudah ada di baris {seen[k]} berkas ini")
            elif k:
                seen[k] = info["row"]

        info["action"] = "update" if cur else "insert"
        info["data"] = {"kode": code or (cur or {}).get("code") or "(otomatis)", "nama": name,
                        "termin": _customer_terms_label(terms) if terms else "",
                        "batas kredit": limit if limit is not None else ""}
        if errs:
            prep.add(info, errs)
            continue
        body = {"name": name}
        for fld in ("npwp", "phone", "address", "notes"):
            if not _blank(row.get(fld)):
                body[fld] = _s(row.get(fld))
        if email:
            body["email"] = email
        if ctype:
            body["company_type"] = ctype
        if terms:
            body["payment_terms"] = terms
        if limit is not None:
            body["credit_limit"] = limit
        if active is not None:
            body["active"] = active
        prep.add(info, [], {"cur": cur, "body": body, "code": code})
    return prep


async def commit_customers(db, prep: Prepared, user: dict) -> tuple:
    from core.doc_number_policy import issue_number
    from routes.sales_direct import CUSTOMER_EDIT_FIELDS, new_customer_doc
    inserted = updated = 0
    for plan, _info in prep.valid:
        cur, body = plan["cur"], plan["body"]
        if cur:
            upd = {k: body[k] for k in CUSTOMER_EDIT_FIELDS if k in body}
            if "credit_limit" in body:
                upd["credit_limit"] = float(body["credit_limit"])
            upd["updated_at"] = _now()
            await db.rahaza_customers.update_one({"id": cur["id"]}, {"$set": upd})
            cid = cur["id"]
            updated += 1
        else:
            code = await issue_number(db, "rahaza_customers.code", requested=plan["code"])
            doc = new_customer_doc(code, body["name"], body, user)
            await db.rahaza_customers.insert_one(doc)
            cid = doc["id"]
            inserted += 1
        await auto_subledger(db, "customer", await db.rahaza_customers.find_one({"id": cid}, {"_id": 0}), user)
    return inserted, updated


async def export_customers(db) -> list:
    out = []
    async for c in db.rahaza_customers.find({}, {"_id": 0}).sort("code", 1):
        out.append({
            "code": c.get("code"), "name": c.get("name"),
            "company_type": "badan usaha" if c.get("company_type") == "company" else "perorangan",
            "npwp": c.get("npwp"), "phone": c.get("phone"), "email": c.get("email"), "address": c.get("address"),
            "payment_terms": _customer_terms_label(c.get("payment_terms")), "credit_limit": c.get("credit_limit"),
            "notes": c.get("notes"), "active": "Tidak" if c.get("active") is False else "Ya",
        })
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 4. KALENDER LIBUR  (rahaza_production_calendar — `type: holiday` dibaca core.workdays)
# ═════════════════════════════════════════════════════════════════════════════
HOLIDAY_COLUMNS = [
    C("date", "tanggal * (YYYY-MM-DD)", required=True, example="#2026-12-25"),
    C("name", "nama *", required=True, example="Hari Raya Natal"),
    C("type", "jenis *", required=True, example="libur",
      choices=["libur", "libur nasional", "cuti bersama", "libur perusahaan", "hari kerja pengganti",
               "acara khusus"],
      help="Libur (libur nasional / cuti bersama / libur perusahaan) mengurangi hari kerja."),
    C("shifts", "shift_terdampak", help="Opsional. Kode shift, pisahkan dengan koma."),
    C("notes", "catatan"),
]
_HOLIDAY_ALL = HOLIDAY_COLUMNS + [_APPROVE]
_CAL_TYPES = {"libur": "holiday", "harilibur": "holiday", "liburnasional": "holiday", "cutibersama": "holiday",
              "liburperusahaan": "holiday", "holiday": "holiday",
              "harikerjapengganti": "exception", "pengecualian": "exception", "exception": "exception",
              "acarakhusus": "special", "catatankhusus": "special", "special": "special"}
_CAL_LABEL = {"holiday": "libur", "exception": "hari kerja pengganti", "special": "acara khusus"}


async def prepare_holidays(db, raw_rows: list, user: dict) -> Prepared:
    prep = Prepared()
    rows = map_rows(raw_rows, _HOLIDAY_ALL)
    shift_codes = set()
    async for s in db.rahaza_shifts.find({}, {"_id": 0, "code": 1}):
        if s.get("code"):
            shift_codes.add(str(s["code"]).upper())
    parsed = []
    for row in rows:
        info = _start(prep, row, "date")
        if info is None:
            continue
        errs: list = []
        _required(row, HOLIDAY_COLUMNS, errs)
        d = _date(row, "date", "tanggal", errs)
        name = _s(row.get("name"))
        typ = _choice(row.get("type"), _CAL_TYPES) if not _blank(row.get("type")) else None
        if not _blank(row.get("type")) and not typ:
            errs.append(f"'jenis': '{_s(row.get('type'))}' tidak dikenal (pilihan: libur, libur nasional, "
                        "cuti bersama, libur perusahaan, hari kerja pengganti, acara khusus)")
        shifts = [x.strip().upper() for x in re.split(r"[,;|]+", _s(row.get("shifts"))) if x.strip()]
        unknown = [x for x in shifts if x not in shift_codes]
        if unknown:
            errs.append(f"'shift_terdampak': kode shift {', '.join(unknown)} tidak ada di Master Shift")
        info["data"] = {"tanggal": d or _s(row.get("date")), "nama": name, "jenis": _CAL_LABEL.get(typ, "")}
        parsed.append((row, info, errs, d, name, typ, shifts))
    dates = sorted({p[3] for p in parsed if p[3]})
    existing = {}
    if dates:
        async for e in db.rahaza_production_calendar.find({"date": {"$in": dates}}, {"_id": 0}):
            existing.setdefault(e["date"], e)
    seen = {}
    for row, info, errs, d, name, typ, shifts in parsed:
        if d and d in seen:
            errs.append(f"tanggal {d} sudah ada di baris {seen[d]} berkas ini (satu tanggal = satu entri)")
        elif d:
            seen[d] = info["row"]
        cur = existing.get(d) if d else None
        info["action"] = "update" if cur else "insert"
        plan = {"cur": cur, "date": d, "name": name, "type": typ, "shifts": shifts,
                "notes": _s(row.get("notes")), "notes_given": not _blank(row.get("notes")),
                "shifts_given": not _blank(row.get("shifts"))}
        prep.add(info, errs, plan)
    return prep


async def commit_holidays(db, prep: Prepared, user: dict) -> tuple:
    from routes.rahaza_production_calendar import calendar_entry_doc
    inserted = updated = 0
    for plan, _info in prep.valid:
        if plan["cur"]:
            upd = {"name": plan["name"], "type": plan["type"],
                   "updated_at": _now().isoformat(), "updated_by": user.get("id")}
            if plan["notes_given"]:
                upd["notes"] = plan["notes"]
            if plan["shifts_given"]:
                upd["affects_shifts"] = plan["shifts"]
            await db.rahaza_production_calendar.update_one({"id": plan["cur"]["id"]}, {"$set": upd})
            updated += 1
        else:
            await db.rahaza_production_calendar.insert_one(calendar_entry_doc(
                plan["date"], plan["name"], plan["type"], notes=plan["notes"], affects_shifts=plan["shifts"],
                user=user))
            inserted += 1
    return inserted, updated


async def export_holidays(db) -> list:
    out = []
    async for e in db.rahaza_production_calendar.find({}, {"_id": 0}).sort("date", 1):
        out.append({"date": e.get("date"), "name": e.get("name"), "type": _CAL_LABEL.get(e.get("type"), e.get("type")),
                    "shifts": ", ".join(e.get("affects_shifts") or []), "notes": e.get("notes")})
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 5. RAK / BIN GUDANG  (wh_buildings → wh_zones → wh_racks → wh_positions)
# ═════════════════════════════════════════════════════════════════════════════
BIN_COLUMNS = [
    C("building_code", "kode_gedung *", required=True, example="#GD-L1"),
    C("building_name", "nama_gedung", example="Gudang Lantai 1"),
    C("zone_code", "kode_zona *", required=True, example="ZN-FG"),
    C("zone_name", "nama_zona", example="Zona Barang Jadi"),
    C("zone_type", "jenis_zona", example="barang jadi (fg)",
      choices=["bahan (rm)", "barang jadi (fg)", "proses (wip)", "umum (general)", "transit"]),
    C("rack_code", "kode_rak *", example="RK-01",
      help="Satu baris = satu rak. Kosongkan kode_rak, jumlah_susun, dan slot_per_susun bila baris "
           "hanya mendaftarkan gedung/zona."),
    C("rack_name", "nama_rak", example="Rak Utama"),
    C("num_shelves", "jumlah_susun *", example="4"),
    C("slots_per_shelf", "slot_per_susun *", example="6"),
    C("capacity_per_slot", "kapasitas_per_slot", example="50"),
    C("capacity_unit", "satuan", example="pcs"),
    C("location_code", "kode_lokasi (lokasi ERP)", example="GD-L1-RAK",
      aliases=("lokasi ERP terkait", "lokasi_erp", "lokasi"),
      help="Kode lokasi di Master Lokasi tempat zona ini berada (dipakai cakupan opname)."),
    C("notes", "catatan"),
    C("active", "aktif", choices=["Ya", "Tidak"], help="Tidak = nonaktifkan rak (ditolak bila masih berisi)."),
]
_ZONE_TYPES = {"rm": "rm", "bahan": "rm", "bahanrm": "rm", "material": "rm",
               "fg": "fg", "barangjadi": "fg", "barangjadifg": "fg",
               "wip": "wip", "proses": "wip", "proseswip": "wip",
               "general": "general", "umum": "general", "umumgeneral": "general",
               "transit": "transit"}
_ZONE_LABEL = {"rm": "bahan (rm)", "fg": "barang jadi (fg)", "wip": "proses (wip)", "general": "umum (general)",
               "transit": "transit"}


def _model_errors(model, header_of: dict, **kw) -> list:
    """Validasi lewat model Pydantic layar Struktur Gudang (batas panjang/angka yang SAMA)."""
    from pydantic import ValidationError
    try:
        model(**kw)
        return []
    except ValidationError as e:
        out = []
        for er in e.errors():
            fld = er["loc"][0] if er.get("loc") else ""
            col = header_of.get(fld, fld)
            ctx = er.get("ctx") or {}
            if "max_length" in ctx:
                out.append(f"'{col}': maksimal {ctx['max_length']} karakter")
            elif "ge" in ctx:
                out.append(f"'{col}': minimal {ctx['ge']}")
            elif "le" in ctx:
                out.append(f"'{col}': maksimal {ctx['le']}")
            else:
                out.append(f"'{col}': tidak valid")
        return out


async def prepare_bins(db, raw_rows: list, user: dict) -> Prepared:
    from routes.wms_structure import BuildingIn, RackIn, ZoneIn, assign_bin_prefix, bin_code
    prep = Prepared()
    blds, zones, racks, locs = {}, {}, {}, {}
    async for b in db.wh_buildings.find({}, {"_id": 0}):
        blds[str(b.get("code") or "").upper()] = b
    async for z in db.wh_zones.find({}, {"_id": 0}):
        zones[(z.get("building_id"), str(z.get("code") or "").upper())] = z
    async for k in db.wh_racks.find({}, {"_id": 0}):
        racks[(k.get("zone_id"), str(k.get("code") or "").upper())] = k
    async for loc in db.rahaza_locations.find({}, {"_id": 0}):
        if loc.get("active") is not False and loc.get("code"):
            locs[str(loc["code"]).upper()] = loc
    f_bld, f_zone, f_rack = {}, {}, {}
    taken: set = set()
    for row in map_rows(raw_rows, BIN_COLUMNS):
        info = _start(prep, row, "building_code")
        if info is None:
            continue
        errs: list = []
        _required(row, BIN_COLUMNS, errs)
        bcode, zcode = _s(row.get("building_code")).upper(), _s(row.get("zone_code")).upper()
        rcode = _s(row.get("rack_code")).upper()
        bname, zname, rname = _s(row.get("building_name")), _s(row.get("zone_name")), _s(row.get("rack_name"))
        ztype = None
        if not _blank(row.get("zone_type")):
            raw_t = _s(row.get("zone_type"))
            m = re.search(r"\(([^)]+)\)", raw_t)
            ztype = _choice(m.group(1), _ZONE_TYPES) if m else None
            ztype = ztype or _choice(raw_t, _ZONE_TYPES)
            if not ztype:
                errs.append(f"'jenis_zona': '{raw_t}' tidak dikenal "
                            "(pilihan: bahan (rm), barang jadi (fg), proses (wip), umum (general), transit)")
        shelves = _num(row, "num_shelves", "jumlah_susun", errs, integer=True)
        slots = _num(row, "slots_per_shelf", "slot_per_susun", errs, integer=True)
        cap = _num(row, "capacity_per_slot", "kapasitas_per_slot", errs)
        unit = _s(row.get("capacity_unit"))
        notes = _s(row.get("notes"))
        active = _bool(row, "active", "aktif", errs)
        loc = None
        if not _blank(row.get("location_code")):
            lcode = _PAREN_RX.sub("", _s(row.get("location_code"))).strip().upper()
            loc = locs.get(lcode)
            if not loc:
                errs.append(f"'kode_lokasi': lokasi '{lcode}' tidak ada / nonaktif di Master Lokasi")
        if rcode and (shelves is None or slots is None) and active is not False:
            errs.append("'jumlah_susun' dan 'slot_per_susun' wajib diisi bila 'kode_rak' diisi")
        if not rcode and (shelves is not None or slots is not None):
            errs.append("'kode_rak' wajib diisi bila 'jumlah_susun'/'slot_per_susun' diisi")
        if not rcode and active is False:
            errs.append("'aktif = Tidak' hanya untuk rak; nonaktifkan zona/gedung di layar Struktur Gudang")
        if bcode:
            errs += _model_errors(BuildingIn, {"code": "kode_gedung", "name": "nama_gedung"},
                                  code=bcode, name=bname or bcode)
        if zcode:
            errs += _model_errors(ZoneIn, {"code": "kode_zona", "name": "nama_zona"},
                                  building_id="-", code=zcode, name=zname or zcode, zone_type=ztype or "general")
        if rcode and shelves is not None and slots is not None:
            errs += _model_errors(RackIn, {"code": "kode_rak", "name": "nama_rak", "num_shelves": "jumlah_susun",
                                           "slots_per_shelf": "slot_per_susun",
                                           "capacity_per_slot": "kapasitas_per_slot"},
                                  zone_id="-", code=rcode, name=rname or rcode, num_shelves=shelves,
                                  slots_per_shelf=slots, capacity_per_slot=cap or 0)

        # ── isi yang berbeda untuk gedung/zona yang sama di baris lain ────────────
        for key, store, vals, what in ((bcode, f_bld, {"nama_gedung": bname}, f"gedung {bcode}"),
                                       ((bcode, zcode), f_zone,
                                        {"nama_zona": zname, "jenis_zona": ztype,
                                         "kode_lokasi": (loc or {}).get("code")}, f"zona {zcode}")):
            if not (bcode and (zcode or what.startswith("gedung"))):
                continue
            prev = store.setdefault(key, {"row": info["row"]})
            for k, v in vals.items():
                if not v:
                    continue
                if prev.get(k) and prev[k] != v:
                    errs.append(f"{what}: '{k}' berbeda dengan baris {prev['row']} ('{prev[k]}' vs '{v}')")
                prev.setdefault(k, v)
        if rcode:
            rk = (bcode, zcode, rcode)
            if rk in f_rack:
                errs.append(f"rak {rcode} di zona {zcode} sudah ada di baris {f_rack[rk]} berkas ini")
            f_rack[rk] = f_rack.get(rk, info["row"])

        b = blds.get(bcode) if bcode else None
        z = zones.get((b["id"], zcode)) if b and zcode else None
        k = racks.get((z["id"], rcode)) if z and rcode else None
        if b and b.get("active") is False:
            errs.append(f"gedung {bcode} nonaktif — aktifkan dulu di Struktur Gudang")
        if z and z.get("active") is False:
            errs.append(f"zona {zcode} nonaktif — aktifkan dulu di Struktur Gudang")
        deactivate = False
        if rcode and active is False:
            if not k or k.get("active") is False:
                errs.append(f"rak {rcode} belum ada / sudah nonaktif — baris 'aktif = Tidak' tidak perlu diimpor")
            else:
                occ = await db.wh_positions.count_documents({"rack_id": k["id"], "status": "occupied"})
                if occ:
                    errs.append(f"rak {rcode} masih punya {occ} posisi terisi — pindahkan barang dulu")
                deactivate = True
        elif k and k.get("active") is False:
            errs.append(f"rak {rcode} sudah dinonaktifkan; tidak bisa dihidupkan lewat impor")
        if k and not deactivate and shelves is not None and slots is not None and (
                shelves < int(k.get("num_shelves") or 0) or slots < int(k.get("slots_per_shelf") or 0)):
            errs.append(f"rak {rcode}: jumlah susun/slot tidak bisa dikurangi lewat impor "
                        f"(sekarang {k.get('num_shelves')}×{k.get('slots_per_shelf')}; posisi lama tidak dihapus)")

        prefix = None
        if rcode and not errs and not deactivate:
            stub = dict(k or {}, code=rcode, building_code=bcode, zone_code=zcode,
                        num_shelves=shelves, slots_per_shelf=slots)
            stub.setdefault("id", None)
            try:
                prefix = await assign_bin_prefix(db, stub, taken=taken)
                taken.add(prefix.upper())
            except HTTPException as e:
                errs.append(str(e.detail))
        info["action"] = "update" if (b and z and (k or not rcode)) else "insert"
        info["data"] = {"gedung": bcode, "zona": zcode, "rak": rcode or "(zona saja)",
                        "bin": ("nonaktifkan" if deactivate else
                                f"{shelves}×{slots} = {shelves * slots} bin, mis. {bin_code(prefix, 1, 1)}"
                                if prefix else "")}
        plan = {"bcode": bcode, "bname": bname, "zcode": zcode, "zname": zname, "ztype": ztype,
                "loc_id": (loc or {}).get("id"), "rcode": rcode, "rname": rname, "shelves": shelves,
                "slots": slots, "cap": cap, "unit": unit, "notes": notes, "deactivate": deactivate}
        prep.add(info, errs, plan)
    return prep


async def commit_bins(db, prep: Prepared, user: dict) -> tuple:
    from routes.wms_structure import (BuildingIn, RackIn, ZoneIn, _zone_location, add_missing_positions,
                                      building_doc, insert_rack, zone_doc)
    inserted = updated = 0
    for p, _info in prep.valid:
        created = False
        b = await db.wh_buildings.find_one({"code": p["bcode"]}, {"_id": 0})
        if not b:
            b = building_doc(BuildingIn(code=p["bcode"], name=p["bname"] or p["bcode"]), user)
            await db.wh_buildings.insert_one(dict(b))
            created = True
        elif p["bname"] and p["bname"] != b.get("name"):
            await db.wh_buildings.update_one({"id": b["id"]}, {"$set": {"name": p["bname"], "updated_at": _now()}})
            b["name"] = p["bname"]
        z = await db.wh_zones.find_one({"building_id": b["id"], "code": p["zcode"]}, {"_id": 0})
        loc_fields = await _zone_location(db, p["loc_id"]) if p["loc_id"] else None
        if not z:
            z = zone_doc(b, ZoneIn(building_id=b["id"], code=p["zcode"], name=p["zname"] or p["zcode"],
                                   zone_type=p["ztype"] or "general",
                                   description=None if p["rcode"] else (p["notes"] or None)),
                         loc_fields or await _zone_location(db, None), user)
            await db.wh_zones.insert_one(dict(z))
            created = True
        else:
            upd = {k: v for k, v in (("name", p["zname"]), ("zone_type", p["ztype"])) if v}
            if loc_fields:
                upd.update(loc_fields)
            if upd:
                upd["updated_at"] = _now()
                await db.wh_zones.update_one({"id": z["id"]}, {"$set": upd})
        if p["rcode"]:
            k = await db.wh_racks.find_one({"zone_id": z["id"], "code": p["rcode"]}, {"_id": 0})
            if p["deactivate"] and k:
                await db.wh_racks.update_one({"id": k["id"]}, {"$set": {"active": False, "updated_at": _now()}})
            elif not k:
                await insert_rack(db, z, b, RackIn(
                    zone_id=z["id"], code=p["rcode"], name=p["rname"] or p["rcode"], num_shelves=p["shelves"],
                    slots_per_shelf=p["slots"], capacity_per_slot=p["cap"] or 0, capacity_unit=p["unit"] or None,
                    description=p["notes"] or None), user)
                created = True
            else:
                upd = {"num_shelves": p["shelves"], "slots_per_shelf": p["slots"], "updated_at": _now()}
                for fld, v in (("name", p["rname"]), ("capacity_per_slot", p["cap"]),
                               ("capacity_unit", p["unit"]), ("description", p["notes"])):
                    if v not in (None, ""):
                        upd[fld] = v
                await db.wh_racks.update_one({"id": k["id"]}, {"$set": upd})
                if (p["shelves"], p["slots"]) != (k.get("num_shelves"), k.get("slots_per_shelf")):
                    await add_missing_positions(db, k["id"])
        if created:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


async def export_bins(db) -> list:
    blds, zones, locs = {}, {}, {}
    async for b in db.wh_buildings.find({"active": {"$ne": False}}, {"_id": 0}):
        blds[b["id"]] = b
    async for z in db.wh_zones.find({"active": {"$ne": False}}, {"_id": 0}):
        zones[z["id"]] = z
    async for loc in db.rahaza_locations.find({}, {"_id": 0, "id": 1, "code": 1}):
        locs[loc["id"]] = loc.get("code")

    def base(z: dict) -> dict:
        b = blds.get(z.get("building_id")) or {}
        return {"building_code": b.get("code") or z.get("building_code"), "building_name": b.get("name"),
                "zone_code": z.get("code"), "zone_name": z.get("name"),
                "zone_type": _ZONE_LABEL.get(z.get("zone_type"), z.get("zone_type")),
                "location_code": z.get("location_code") or locs.get(z.get("location_id"))}

    out, with_rack = [], set()
    async for k in db.wh_racks.find({"active": {"$ne": False}}, {"_id": 0}).sort("code", 1):
        z = zones.get(k.get("zone_id"))
        if not z:
            continue
        with_rack.add(z["id"])
        out.append({**base(z), "rack_code": k.get("code"), "rack_name": k.get("name"),
                    "num_shelves": k.get("num_shelves"), "slots_per_shelf": k.get("slots_per_shelf"),
                    "capacity_per_slot": k.get("capacity_per_slot"), "capacity_unit": k.get("capacity_unit"),
                    "notes": k.get("description"), "active": "Ya"})
    out += [{**base(z), "notes": z.get("description")} for zid, z in zones.items() if zid not in with_rack]
    out.sort(key=lambda r: (str(r["building_code"] or ""), str(r["zone_code"] or ""), str(r.get("rack_code") or "")))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Daftar penangan (dibaca REGISTRY Data Transfer)
# ═════════════════════════════════════════════════════════════════════════════
HANDLERS = {
    "suppliers": {"columns": SUPPLIER_COLUMNS, "sheet_names": ["SUPPLIER"],
                  "prepare": prepare_suppliers, "commit": commit_suppliers, "export": export_suppliers},
    "supplier_prices": {"columns": PRICE_COLUMNS, "sheet_names": ["KATALOG_HARGA_SUPPLIER", "DAFTAR_HARGA"],
                        "prepare": prepare_supplier_prices, "commit": commit_supplier_prices,
                        "export": export_supplier_prices},
    "customers": {"columns": CUSTOMER_COLUMNS, "sheet_names": ["PELANGGAN"],
                  "prepare": prepare_customers, "commit": commit_customers, "export": export_customers},
    "holidays": {"columns": HOLIDAY_COLUMNS, "sheet_names": ["KALENDER_LIBUR"],
                 "prepare": prepare_holidays, "commit": commit_holidays, "export": export_holidays},
    "wh_bins": {"columns": BIN_COLUMNS, "sheet_names": ["LOKASI_BIN"],
                "prepare": prepare_bins, "commit": commit_bins, "export": export_bins},
}


async def run_import(handler: str, db, raw_rows: list, user: dict, *, commit: bool) -> dict:
    """Pratinjau (commit=False) atau terapkan (commit=True). Terapkan selalu memvalidasi ulang dulu."""
    h = HANDLERS[handler]
    prep = await h["prepare"](db, raw_rows, user)
    out = {
        "total_rows": len(raw_rows), "valid": len(prep.valid), "invalid": len(prep.invalid),
        "skipped": len(prep.skipped),
        "would_insert": sum(1 for _, i in prep.valid if i.get("action") == "insert"),
        "would_update": sum(1 for _, i in prep.valid if i.get("action") == "update"),
        "preview_valid": [i for _, i in prep.valid][:100],
        "preview_invalid": sorted(prep.invalid, key=lambda i: i["row"])[:100],
        "preview_skipped": prep.skipped[:100],
    }
    if not commit:
        return out
    if prep.invalid:
        raise HTTPException(400, f"Ada {len(prep.invalid)} baris bermasalah. Perbaiki dulu sebelum impor "
                                 "(atau hapus baris itu dari berkas).")
    inserted, updated = await h["commit"](db, prep, user)
    out.update({"committed": True, "inserted": inserted, "updated": updated})
    return out
