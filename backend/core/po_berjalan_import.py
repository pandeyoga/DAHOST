"""core.po_berjalan_import — impor PO BERJALAN saat cutoff (T6, keputusan owner 2026-11-06).

Keputusan owner: upah jahit CMT untuk potongan yang MASIH di penjahit saat cutoff TIDAK dimasukkan
sebagai saldo awal hutang. PO produksi/maklon yang masih berjalan diimpor, lalu hutang lahir lewat
alur biasa: jadwal hutang CMT saat PO dikonfirmasi (maklon) dan tagihan matang saat barang lolos QC.

Satu baris berkas = satu SKU pada satu kiriman ke CMT. Baris dikelompokkan menjadi SATU PO per
(kode potongan, CMT). Untuk setiap kelompok baru, `commit()`:

  1. membuat PO berstatus Dikonfirmasi lewat jalur resmi `routes.production_pos.create_po_internal`
     (`opening=True`: BOM tidak diledakkan lagi). Qty baris PO = SISA DI CMT — qty yang sudah diterima
     sebelum cutoff dicatat sebagai riwayat (`opening_qty_cut`, `opening_qty_received`) sehingga
     hutang hanya lahir untuk sisa. PO maklon langsung mendapat jadwal piutang klien & hutang CMT.
  2. mencatat surat jalan saldo awal lewat `routes.vendor_shipment.create_vendor_shipment_internal`
     (`opening=True`: sudah diterima & diperiksa vendor, TANPA Material Issue — stok tidak dipotong
     lagi, tidak ada jurnal).
  3. menandai PO (`opening_import.key`) supaya impor ulang berkas yang sama DILEWATI (idempoten).
  4. (11 Nov 2026, owner) langsung membuat Production Job dari surat jalan saldo awal lewat jalur resmi
     `routes.production_execution.create_job_for_shipment_locked` (kunci + cek job ganda yang sama dengan
     `POST /production-jobs`). PO internal mendapat Tujuan "Gudang FG Sendiri" (bawaan form PO internal);
     kolom opsional "Tenggat produksi" / "Tenggat kirim" mengisi tenggat PO dan job.

Langkah berikutnya memakai alur biasa: staf/vendor tinggal lapor progres, kirim ke DA, Terima FG dari
CMT → QC → tagihan CMT matang (hutang) — tidak ada jalur kedua. Bahan yang sudah di penjahit saat cutoff
tidak dinilai (keputusan owner 11 Nov 2026, `core.fg_cost_layers`): barang dari PO ini dinilai upah jahit.

SKU dipetakan lewat tabel padanan (format `padanan_impor_*.csv` skrip master: jenis,
tertulis_di_excel, kode_erp) yang diunggah bersama berkas, ditambah padanan yang sudah tersimpan di
master (varian `merged_into_sku`, model `name_aliases`, warna `alias_of_code`).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)

KEY = "po_berjalan"
JENIS = ("internal", "maklon")
# Tujuan PO internal = bawaan form PO internal (`ProductionPOModule.openCreate`); kolom "Tujuan" daftar PO membacanya.
TUJUAN_INTERNAL = "Gudang FG Sendiri"
JOB_NOTE = "Job dari kiriman awal saldo cutoff (impor PO berjalan)"
SHIPMENT_NUMBER_KEY = "vendor_shipments.shipment_number"
PO_NUMBER_KEY = {"internal": "production_pos.po_number", "maklon": "production_pos.po_number_maklon"}

# (nama kanonik, judul kolom template, wajib, contoh)
COLUMNS: tuple[tuple[str, str, bool, str], ...] = (
    ("tanggal", "Tanggal", False, "2026-11-01"),
    ("kode_potongan", "Kode potongan / No PO", False, "CUT-2610-01"),
    ("sku", "SKU", False, "DA-1234-HTM-M"),
    ("model", "Model", False, "nama atau kode model"),
    ("warna", "Warna", False, "Hitam"),
    ("ukuran", "Ukuran", False, "M"),
    ("cmt", "CMT", True, "kode atau nama vendor CMT"),
    ("qty_potong", "Qty potong", False, "100"),
    ("qty_diterima", "Qty sudah diterima", False, "60"),
    ("sisa_di_cmt", "Sisa di CMT", False, "40"),
    ("upah_cmt", "Upah CMT", True, "12000"),
    ("harga_client", "Harga ke klien", False, ""),
    ("client", "Klien", False, ""),
    ("jenis", "Jenis", True, "internal"),
    ("tenggat_produksi", "Tenggat produksi", False, "2026-11-30"),
    ("tenggat_kirim", "Tenggat kirim", False, "2026-12-05"),
)

_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "tanggal": ("tanggal", "tgl", "tanggal potong", "date"),
    "kode_potongan": ("kode potongan", "kode potongan no po", "no po", "nomor po", "kode potong",
                      "kode po", "no potongan"),
    "sku": ("sku", "kode sku", "sku erp"),
    "model": ("model", "nama produk", "produk", "kode model", "artikel"),
    "warna": ("warna", "variasi", "color"),
    "ukuran": ("ukuran", "size"),
    "cmt": ("cmt", "penjahit", "vendor", "vendor cmt", "kode cmt", "nama cmt"),
    "qty_potong": ("qty potong", "hasil potong", "jumlah potong", "potong"),
    "qty_diterima": ("qty sudah diterima", "qty diterima", "sudah diterima", "qty lolos qc",
                     "qty sudah diterima lolos qc", "diterima"),
    "sisa_di_cmt": ("sisa di cmt", "sisa", "sisa potongan", "sisa potongan pcs", "qty sisa"),
    "upah_cmt": ("upah cmt", "upah", "harga ke cmt", "harga ke cmt upah", "upah jahit"),
    "harga_client": ("harga ke klien", "harga dari client", "harga client", "harga jasa",
                     "harga dari client maklon", "harga klien"),
    "client": ("klien", "client", "client maklon", "klien maklon"),
    "jenis": ("jenis", "tipe", "jenis internal maklon", "business type"),
    "tenggat_produksi": ("tenggat produksi", "tenggat", "deadline", "deadline produksi", "batas produksi"),
    "tenggat_kirim": ("tenggat kirim", "deadline kirim", "batas kirim", "tenggat pengiriman"),
}


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", str(h or "").lower())).strip()


_HEADER_MAP = {_norm_header(a): canon for canon, al in _HEADER_ALIASES.items() for a in al + (canon,)}
_HEADER_MAP.update({_norm_header(label): canon for canon, label, _r, _e in COLUMNS})


def template_columns() -> list[dict]:
    """Kolom template Data Transfer (bentuk `routes.data_transfer.col`)."""
    return [{"name": label, "type": "str", "required": req, "label": label, "example": ex}
            for _c, label, req, ex in COLUMNS]


def nk(s) -> str:
    """Kunci pencocokan teks: huruf kecil, spasi tunggal."""
    return re.sub(r"\s+", " ", str(s or "").strip().casefold())


def _combo_key(*parts) -> str:
    return "|".join(nk(p) for p in parts)


def angka(v):
    """(nilai, galat). Menerima angka Excel dan teks ber-ribuan Indonesia ('15.000', 'Rp 12.500')."""
    if v is None or isinstance(v, bool):
        return (None, None) if v is None else (None, f"'{v}' bukan angka")
    if isinstance(v, (int, float)):
        return float(v), None
    s = re.sub(r"(?i)rp|\s", "", str(v))
    if s == "":
        return None, None
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s), None
    except ValueError:
        return None, f"'{v}' bukan angka"


def tanggal(v):
    """(ISO yyyy-mm-dd, galat)."""
    if v in (None, ""):
        return None, None
    if isinstance(v, datetime):
        return v.date().isoformat(), None
    if isinstance(v, date):
        return v.isoformat(), None
    s = str(v).strip()
    for fmt, cut in (("%Y-%m-%d", 10), ("%d/%m/%Y", None), ("%d-%m-%Y", None), ("%d/%m/%y", None),
                     ("%Y/%m/%d", None), ("%d.%m.%Y", None)):
        try:
            return datetime.strptime(s[:cut] if cut else s, fmt).date().isoformat(), None
        except ValueError:
            continue
    return None, f"tanggal '{v}' tidak dikenali (pakai 2026-11-01 atau 01/11/2026)"


def normalize_row(raw: dict) -> dict:
    out: dict = {}
    for k, v in (raw or {}).items():
        canon = _HEADER_MAP.get(_norm_header(k))
        if canon and (canon not in out or out[canon] in (None, "")):
            out[canon] = v.strip() if isinstance(v, str) else v
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Tabel padanan (alias)
# ══════════════════════════════════════════════════════════════════════════════
def _strip_note(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", s or "").strip()


def parse_aliases(rows: list | None) -> dict:
    """Padanan dari berkas `padanan_impor_*.csv` → {'sku': {}, 'model': {}, 'warna': {}}.

    Kolom: `jenis` (SKU / model / warna; jenis lain diabaikan), `tertulis_di_excel`, `kode_erp`.
    Catatan dalam kurung dibuang; beberapa tulisan dipisah ' / ' (dipasangkan berurutan bila kode
    ERP-nya juga dipisah ' / '). Kunci 'MODEL · WARNA · UKURAN' memetakan kombinasi ke SKU."""
    out: dict = {"sku": {}, "model": {}, "warna": {}}
    for raw in rows or []:
        r = {_norm_header(k): (v if v is not None else "") for k, v in (raw or {}).items()}
        src = str(r.get("tertulis di excel") or r.get("tertulis") or r.get("dari") or r.get("alias") or "")
        dst = str(r.get("kode erp") or r.get("ke") or r.get("kode") or "")
        jenis = nk(r.get("jenis") or "sku")
        cat = "sku" if jenis.startswith("sku") else "model" if jenis.startswith("model") \
            else "warna" if jenis.startswith("warna") else None
        if not cat or not src.strip() or not dst.strip():
            continue
        srcs = [_strip_note(p) for p in src.split(" / ") if _strip_note(p)]
        dsts = [d.strip() for d in dst.split(" / ") if d.strip()]
        for i, s in enumerate(srcs):
            d = dsts[i] if len(dsts) == len(srcs) else dsts[0] if len(dsts) == 1 else None
            if not d:
                continue
            key = _combo_key(*re.split(r"\s*[·|]\s*", s)) if ("·" in s or "|" in s) else nk(s)
            out[cat][key] = d
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Penyelesaian master
# ══════════════════════════════════════════════════════════════════════════════
def _active(d: dict) -> bool:
    return d.get("active", True) is not False and d.get("is_active", True) is not False


class _Ctx:
    def __init__(self, db, aliases: dict):
        self.db, self.al = db, aliases
        self.vendors_code, self.vendors_name = {}, {}
        self.clients_code, self.clients_name = {}, {}
        self.models_code, self.models_name = {}, {}
        self.colors_code, self.colors_name = {}, {}
        self.sizes_code, self.sizes_name = {}, {}
        self.catalog: dict = {}
        self._vcache: dict = {}
        self.cost_cache: dict = {}

    async def load(self):
        db = self.db
        async for v in db.vendor_partners.find({}, {"_id": 0}):
            self.vendors_code.setdefault(str(v.get("code") or "").strip().upper(), []).append(v)
            self.vendors_name.setdefault(nk(v.get("name")), []).append(v)
        async for c in db.dewi_maklon_clients.find({}, {"_id": 0}):
            self.clients_code.setdefault(str(c.get("code") or "").strip().upper(), []).append(c)
            self.clients_name.setdefault(nk(c.get("name")), []).append(c)
        async for m in db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0}):
            self.models_code.setdefault(str(m.get("code") or "").strip().upper(), []).append(m)
            for n in [m.get("name")] + list(m.get("name_aliases") or []):
                if n:
                    self.models_name.setdefault(nk(n), []).append(m)
        async for c in db.rahaza_colors.find({}, {"_id": 0}):
            self.colors_code.setdefault(str(c.get("code") or "").strip().upper(), []).append(c)
            self.colors_name.setdefault(nk(c.get("name")), []).append(c)
        async for s in db.rahaza_sizes.find({"active": {"$ne": False}}, {"_id": 0}):
            self.sizes_code.setdefault(re.sub(r"\s+", "", str(s.get("code") or "")).upper(), []).append(s)
            self.sizes_name.setdefault(nk(s.get("name")), []).append(s)
        async for it in db.dewi_maklon_buyer_catalog.find({}, {"_id": 0}):
            self.catalog.setdefault(it.get("client_id"), []).append(it)

    @staticmethod
    def _one(cands: list, what: str, text: str):
        uniq = {d.get("id"): d for d in cands}
        if len(uniq) > 1:
            return None, f"{what} '{text}' cocok dengan {len(uniq)} data master — pakai kodenya"
        return (next(iter(uniq.values())), None) if uniq else (None, None)

    def vendor(self, text: str):
        d, err = self._one(self.vendors_code.get(str(text).strip().upper(), []), "CMT", text)
        if not d and not err:
            d, err = self._one(self.vendors_name.get(nk(text), []), "CMT", text)
        if err:
            return None, err
        if not d:
            return None, f"CMT '{text}' tidak ada di master vendor CMT"
        if not _active(d):
            return None, f"CMT '{text}' nonaktif di master vendor CMT"
        return d, None

    def client(self, text: str):
        d, err = self._one(self.clients_code.get(str(text).strip().upper(), []), "Klien", text)
        if not d and not err:
            d, err = self._one(self.clients_name.get(nk(text), []), "Klien", text)
        if err:
            return None, err
        if not d:
            return None, f"Klien '{text}' tidak ada di master klien maklon"
        return d, None

    def model(self, text: str):
        t = self.al["model"].get(nk(text), str(text).strip())
        d, err = self._one(self.models_code.get(t.upper(), []), "Model", text)
        # DATA ERP menulis kode model tanpa awalan perusahaan (keputusan owner 6 Nov: kode angka di
        # DATA ERP = kode master DA-<angka>) — angka murni dicoba sebagai DA-<angka>.
        if not d and not err and re.fullmatch(r"\d{3,5}", t):
            d, err = self._one(self.models_code.get(f"DA-{t}", []), "Model", text)
        if not d and not err:
            d, err = self._one(self.models_name.get(nk(t), []), "Model", text)
        if err:
            return None, err
        return (d, None) if d else (None, f"Model '{text}' tidak ada di master model")

    def color(self, text: str):
        t = self.al["warna"].get(nk(text), str(text).strip())
        d, err = self._one(self.colors_code.get(t.upper(), []), "Warna", text)
        if not d and not err:
            d, err = self._one(self.colors_name.get(nk(t), []), "Warna", text)
        if err:
            return None, err
        if not d:
            return None, f"Warna '{text}' tidak ada di master warna"
        return (d.get("alias_of_code") or d.get("code")), None

    def size(self, text: str):
        d, err = self._one(self.sizes_code.get(re.sub(r"\s+", "", str(text)).upper(), []), "Ukuran", text)
        if not d and not err:
            d, err = self._one(self.sizes_name.get(nk(text), []), "Ukuran", text)
        if err:
            return None, err
        return (d, None) if d else (None, f"Ukuran '{text}' tidak ada di master ukuran")

    async def variant_by_sku(self, sku: str):
        s = str(self.al["sku"].get(nk(sku), sku)).strip().upper()
        for _hop in range(4):
            if s in self._vcache:
                v = self._vcache[s]
            else:
                v = await self.db.rahaza_model_variants.find_one({"sku": s}, {"_id": 0})
                self._vcache[s] = v
            if not v:
                return None, f"SKU '{sku}' tidak ada di master varian" + (f" (padanan → {s})" if s != str(sku).strip().upper() else "")
            nxt = str(v.get("merged_into_sku") or "").strip().upper()
            if nxt and nxt != s:
                s = nxt
                continue
            if v.get("active") is False:
                return None, f"SKU '{s}' nonaktif di master varian"
            return v, None
        return None, f"SKU '{sku}' berputar di padanan gabungan varian"

    async def variant_by_parts(self, model: dict, color_code: str, size: dict):
        v = await self.db.rahaza_model_variants.find_one(
            {"model_id": model["id"], "size_id": size["id"], "color_code": color_code,
             "active": {"$ne": False}}, {"_id": 0})
        if not v:
            return None, (f"Varian {model.get('code')} warna {color_code} ukuran {size.get('code')} "
                          "belum ada di master varian")
        return v, None

    def catalog_item(self, client_id: str, sku: str, model_text: str):
        items = self.catalog.get(client_id) or []
        key = str(sku or "").strip().upper()
        if key:
            hit = [i for i in items if key in (str(i.get("artikel_code") or "").strip().upper(),
                                               str(i.get("buyer_ref_code") or "").strip().upper())]
            if hit:
                return self._one(hit, "Artikel", sku)
        if model_text:
            hit = [i for i in items if nk(i.get("product_name")) == nk(model_text)
                   or str(i.get("artikel_code") or "").strip().upper() == str(model_text).strip().upper()]
            if hit:
                return self._one(hit, "Artikel", model_text)
        return None, (f"Artikel '{sku or model_text}' tidak ada di Katalog Buyer klien ini "
                      "(kode artikel / kode buyer / nama produk)")

    async def material_cost(self, model_id: str, size_id: str, color_code: str) -> float:
        key = (model_id, size_id, color_code)
        if key not in self.cost_cache:
            try:
                from core import product_costing as pc
                mc = await pc.compute_material_cost(self.db, model_id, size_id, color=color_code)
                self.cost_cache[key] = float(mc.get("material_cost") or 0)
            except Exception:  # noqa: BLE001 — perkiraan saja; impor tetap sah
                logger.exception("perkiraan biaya bahan gagal (model=%s size=%s)", model_id, size_id)
                self.cost_cache[key] = 0.0
        return self.cost_cache[key]


def _int_qty(v, label: str, errors: list):
    n, err = angka(v)
    if err:
        errors.append(f"{label}: {err}")
        return None
    if n is None:
        return None
    if n < 0 or abs(n - round(n)) > 1e-9:
        errors.append(f"{label} harus bilangan bulat ≥ 0 (tertulis {v})")
        return None
    return int(round(n))


def _r2(v) -> float:
    return round(float(v or 0) + 1e-9, 2)


async def _resolve_row(ctx: _Ctx, idx: int, r: dict, today: str) -> dict:
    errors: list = []
    notes: list = []
    jenis = nk(r.get("jenis"))
    if jenis not in JENIS:
        errors.append("Jenis wajib 'internal' atau 'maklon'")
    tgl, err = tanggal(r.get("tanggal"))
    if err:
        errors.append(err)
    if not tgl and not err:
        tgl = today
        notes.append("tanggal kosong → tanggal hari ini")
    kode = str(r.get("kode_potongan") or "").strip()
    tenggat, err = tanggal(r.get("tenggat_produksi"))
    if err:
        errors.append(f"Tenggat produksi: {err}")
    tenggat_kirim, err = tanggal(r.get("tenggat_kirim"))
    if err:
        errors.append(f"Tenggat kirim: {err}")
    if tenggat and tenggat_kirim and tenggat_kirim < tenggat:
        errors.append(f"Tenggat kirim ({tenggat_kirim}) lebih awal dari tenggat produksi ({tenggat})")

    vendor = None
    if not str(r.get("cmt") or "").strip():
        errors.append("CMT wajib diisi (kode atau nama vendor CMT)")
    else:
        vendor, err = ctx.vendor(r["cmt"])
        if err:
            errors.append(err)

    potong = _int_qty(r.get("qty_potong"), "Qty potong", errors)
    terima = _int_qty(r.get("qty_diterima"), "Qty sudah diterima", errors)
    sisa = _int_qty(r.get("sisa_di_cmt"), "Sisa di CMT", errors)
    if sisa is None and potong is not None:
        sisa = potong - (terima or 0)
    if potong is None and sisa is not None:
        potong = sisa + (terima or 0)
    if potong is not None and sisa is not None and potong - (terima or 0) != sisa:
        errors.append(f"Qty tidak cocok: potong {potong} − sudah diterima {terima or 0} ≠ sisa {sisa}")
    if sisa is None:
        errors.append("Isi Sisa di CMT (atau Qty potong + Qty sudah diterima)")
    elif sisa < 0:
        errors.append(f"Qty sudah diterima ({terima}) melebihi qty potong ({potong})")

    upah, err = angka(r.get("upah_cmt"))
    if err:
        errors.append(f"Upah CMT: {err}")
    elif not upah or upah <= 0:
        errors.append("Upah CMT wajib diisi (> 0) — dasar hutang CMT saat barang lolos QC")
    harga, err = angka(r.get("harga_client"))
    if err:
        errors.append(f"Harga ke klien: {err}")

    out = {"row": idx, "errors": errors, "notes": notes, "jenis": jenis, "tanggal": tgl,
           "deadline": tenggat, "delivery_deadline": tenggat_kirim, "kode": kode, "vendor": vendor, "qty_potong": potong, "qty_diterima": terima or 0,
           "sisa": sisa, "upah": float(upah or 0), "harga": float(harga or 0), "client": None,
           "item": None, "label": "", "material_cost": 0.0}
    sku, model_t = str(r.get("sku") or "").strip(), str(r.get("model") or "").strip()
    warna_t, ukuran_t = str(r.get("warna") or "").strip(), str(r.get("ukuran") or "").strip()

    if jenis == "internal":
        if harga:
            notes.append("harga ke klien diabaikan untuk PO internal")
        variant = None
        if sku:
            variant, err = await ctx.variant_by_sku(sku)
            if err:
                errors.append(err)
        elif model_t and warna_t and ukuran_t:
            combo = ctx.al["sku"].get(_combo_key(model_t, warna_t, ukuran_t))
            if combo:
                variant, err = await ctx.variant_by_sku(combo)
                if err:
                    errors.append(err)
            else:
                model, e1 = ctx.model(model_t)
                ccode, e2 = ctx.color(warna_t)
                size, e3 = ctx.size(ukuran_t)
                for e in (e1, e2, e3):
                    if e:
                        errors.append(e)
                if model and ccode and size:
                    variant, err = await ctx.variant_by_parts(model, ccode, size)
                    if err:
                        errors.append(err)
        else:
            errors.append("Isi SKU, atau Model + Warna + Ukuran")
        if variant and model_t and sku:
            m, _e = ctx.model(model_t)
            if m and m.get("id") != variant.get("model_id"):
                errors.append(f"SKU {variant.get('sku')} bukan milik model '{model_t}'")
        if variant:
            out["item"] = {"rahaza_variant_id": variant["id"], "sku": variant.get("sku", ""),
                           "color_code": variant.get("color_code", ""), "product_name": variant.get("model_name", ""),
                           "size": variant.get("size_code", ""), "color": variant.get("color_name", "")}
            out["label"] = variant.get("sku", "")
            if sisa and not errors:
                out["material_cost"] = await ctx.material_cost(
                    variant.get("model_id"), variant.get("size_id"), variant.get("color_code", ""))
    elif jenis == "maklon":
        if not str(r.get("client") or "").strip():
            errors.append("Klien wajib diisi untuk PO maklon")
        else:
            client, err = ctx.client(r["client"])
            if err:
                errors.append(err)
            out["client"] = client
            if client:
                cat, err = ctx.catalog_item(client["id"], sku, model_t)
                if err:
                    errors.append(err)
                if cat:
                    mv = next((v for v in (cat.get("variants") or [])
                               if nk(v.get("size")) == nk(ukuran_t) and nk(v.get("color")) == nk(warna_t)), None)
                    out["item"] = {"catalog_item_id": cat["id"], "maklon_variant_id": (mv or {}).get("id"),
                                   "buyer_ref_code": cat.get("buyer_ref_code", ""),
                                   "product_name": cat.get("product_name", ""),
                                   "sku": sku or cat.get("artikel_code", ""), "size": ukuran_t, "color": warna_t}
                    out["label"] = " ".join(x for x in (out["item"]["sku"], ukuran_t, warna_t) if x)
        if not harga or harga <= 0:
            errors.append("Harga ke klien wajib diisi (> 0) untuk PO maklon — dasar piutang klien")
    return out


def _group_key(row: dict) -> str:
    vid = (row.get("vendor") or {}).get("id", "")
    if row["kode"]:
        return f"{row['kode'].upper()}|{vid}"
    item = row.get("item") or {}
    raw = "|".join([row["jenis"], vid, (row.get("client") or {}).get("id", ""), row["tanggal"] or "",
                    item.get("rahaza_variant_id") or item.get("catalog_item_id") or "",
                    item.get("size", ""), item.get("color", "")])
    return "AUTO-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12] + f"|{vid}"


async def analyse(db, raw_rows: list, alias_rows: list | None = None) -> dict:
    """Pratinjau: setiap baris diselesaikan ke master + galat per baris; kelompok PO; ringkasan.
    Tidak menulis apa pun."""
    from core.doc_number_policy import policy
    from utils.waktu import today_wib
    ctx = _Ctx(db, parse_aliases(alias_rows))
    await ctx.load()
    today = today_wib().isoformat()

    global_errors = []
    pol_ship = await policy(db, SHIPMENT_NUMBER_KEY)
    if pol_ship["mode"] == "manual":
        global_errors.append("Penomoran Shipment Vendor disetel MANUAL — ubah ke otomatis di Penomoran "
                             "Dokumen selama impor saldo awal.")
    pol_po = {j: await policy(db, k) for j, k in PO_NUMBER_KEY.items()}

    rows = []
    for idx, raw in enumerate(raw_rows or [], start=2):
        r = normalize_row(raw)
        if not any(v not in (None, "") for v in r.values()):
            continue
        rows.append(await _resolve_row(ctx, idx, r, today))

    groups: dict = {}
    for row in rows:
        if row["errors"]:
            continue
        if not row["sisa"]:
            row["skip_reason"] = "sisa di CMT 0 — tidak ada yang perlu diimpor"
            continue
        groups.setdefault(_group_key(row), []).append(row)

    out_groups = []
    for key, grows in groups.items():
        first = grows[0]
        for other in grows[1:]:
            for f, label in (("jenis", "jenis"), ("tanggal", "tanggal")):
                if other[f] != first[f]:
                    other["errors"].append(f"Satu kode potongan & CMT harus satu {label} (baris {first['row']})")
            if (other.get("client") or {}).get("id") != (first.get("client") or {}).get("id"):
                other["errors"].append(f"Satu kode potongan & CMT harus satu klien (baris {first['row']})")
        for f, label in (("deadline", "tenggat produksi"), ("delivery_deadline", "tenggat kirim")):
            # tenggat boleh hanya ditulis di satu baris kelompok; dua nilai berbeda = satu PO dengan dua tenggat
            filled = [gr for gr in grows if gr[f]]
            for gr in filled[1:]:
                if gr[f] != filled[0][f]:
                    gr["errors"].append(f"Satu kode potongan & CMT harus satu {label} (baris {filled[0]['row']})")
        seen = {}
        for gr in grows:
            ik = (gr["item"].get("rahaza_variant_id") or gr["item"].get("catalog_item_id"),
                  gr["item"].get("size", ""), gr["item"].get("color", ""))
            if ik in seen:
                gr["errors"].append(f"{gr['label']} sudah ada di baris {seen[ik]} pada kode potongan & CMT "
                                    "yang sama — gabungkan barisnya")
            seen.setdefault(ik, gr["row"])
        pol = pol_po.get(first["jenis"]) or {}
        if pol.get("mode") == "manual":
            if not first["kode"]:
                first["errors"].append(f"Penomoran {pol.get('label')} MANUAL: isi Kode potongan / No PO dengan "
                                       f"nomor PO berpola {pol.get('format')}")
            elif pol.get("pola") and not re.match(pol["pola"], first["kode"]):
                first["errors"].append(f"No PO '{first['kode']}' tidak mengikuti pola {pol.get('format')} "
                                       f"(penomoran PO disetel manual)")
        existing = await db.production_pos.find_one({"opening_import.key": key},
                                                    {"_id": 0, "id": 1, "po_number": 1})
        out_groups.append({"key": key, "rows": grows, "existing": existing})

    valid_rows, invalid_rows = [], []
    for row in rows:
        data = {"PO": row["kode"] or "(otomatis)", "Barang": row["label"] or "-",
                "CMT": (row.get("vendor") or {}).get("name", "-"), "Sisa": row["sisa"] if row["sisa"] is not None else "-"}
        if row["errors"]:
            invalid_rows.append({"row": row["row"], "errors": row["errors"], "data": data})
    bad_keys = {g["key"] for g in out_groups if any(r["errors"] for r in g["rows"])}
    totals = {"po_baru": 0, "po_sudah_ada": 0, "pcs_sisa": 0, "hutang_cmt_terjadwal": 0.0,
              "piutang_maklon_terjadwal": 0.0, "nilai_bahan_di_cmt": 0.0}
    summary_groups = []
    for g in out_groups:
        if g["key"] in bad_keys:
            for r in g["rows"]:
                if not r["errors"]:
                    r["errors"].append("Kelompok PO ini punya baris bermasalah — perbaiki dulu")
                    invalid_rows.append({"row": r["row"], "errors": r["errors"],
                                         "data": {"PO": r["kode"] or "(otomatis)", "Barang": r["label"]}})
            continue
        action = "skip" if g["existing"] else "insert"
        first = g["rows"][0]
        if action == "insert":
            totals["po_baru"] += 1
            for r in g["rows"]:
                totals["pcs_sisa"] += r["sisa"]
                totals["hutang_cmt_terjadwal"] += r["sisa"] * r["upah"]
                if r["jenis"] == "maklon":
                    totals["piutang_maklon_terjadwal"] += r["sisa"] * r["harga"]
                else:
                    totals["nilai_bahan_di_cmt"] += r["sisa"] * r["material_cost"]
        else:
            totals["po_sudah_ada"] += 1
        summary_groups.append({
            "key": g["key"], "kode_potongan": first["kode"], "jenis": first["jenis"],
            "cmt": (first.get("vendor") or {}).get("name", ""), "klien": (first.get("client") or {}).get("name", ""),
            "tanggal": first["tanggal"], "baris": len(g["rows"]), "sisa": sum(r["sisa"] for r in g["rows"]),
            "action": action, "po_number": (g["existing"] or {}).get("po_number")})
        for r in g["rows"]:
            note = "; ".join(r["notes"] + ([f"sudah diimpor ({g['existing'].get('po_number')})"]
                                           if g["existing"] else []))
            valid_rows.append({"row": r["row"], "action": action,
                               "data": {"PO": r["kode"] or "(otomatis)", "Barang": r["label"],
                                        "CMT": (r.get("vendor") or {}).get("name", ""), "Sisa": r["sisa"],
                                        **({"Catatan": note} if note else {})}})
    for row in rows:
        if not row["errors"] and row.get("skip_reason"):
            valid_rows.append({"row": row["row"], "action": "skip",
                               "data": {"PO": row["kode"] or "(otomatis)", "Barang": row["label"],
                                        "CMT": (row.get("vendor") or {}).get("name", ""), "Sisa": 0,
                                        "Catatan": row["skip_reason"]}})
    for e in global_errors:
        invalid_rows.insert(0, {"row": "-", "errors": [e], "data": {}})
    for k in ("hutang_cmt_terjadwal", "piutang_maklon_terjadwal", "nilai_bahan_di_cmt"):
        totals[k] = _r2(totals[k])
    valid_rows.sort(key=lambda x: x["row"])
    invalid_rows.sort(key=lambda x: (x["row"] != "-", x["row"] if isinstance(x["row"], int) else 0))
    return {
        "total_rows": len(rows), "valid": len(valid_rows), "invalid": len(invalid_rows),
        "would_insert": sum(1 for v in valid_rows if v["action"] == "insert"), "would_update": 0,
        "would_skip": sum(1 for v in valid_rows if v["action"] == "skip"),
        "preview_valid": valid_rows[:200], "preview_invalid": invalid_rows[:200],
        "groups": summary_groups, "totals": totals,
        "_groups": [g for g in out_groups if g["key"] not in bad_keys and not g["existing"]],
    }


async def commit(db, analysis: dict, user: dict) -> dict:
    """Buat PO + surat jalan saldo awal + Production Job untuk setiap kelompok BARU hasil `analyse` (yang tanpa
    galat). Kelompok yang gagal di tengah jalan dibatalkan lewat jalur hapus PO resmi; kelompok lain lanjut."""
    from routes.production_pos import create_po_internal
    from routes.vendor_shipment import create_vendor_shipment_internal
    from routes.production_maklon_bridge import try_sync_maklon_finance
    from routes.production_execution import create_job_for_shipment_locked
    from utils.waktu import now_wib
    created, failed = [], []
    batch = now_wib().strftime("%Y%m%d%H%M%S")
    for g in analysis.get("_groups") or []:
        rows = g["rows"]
        first = rows[0]
        vendor, client = first["vendor"], first.get("client") or {}
        note = ("Saldo awal cutoff — PO berjalan diimpor" + (f" (kode potongan {first['kode']})" if first["kode"] else "")
                + f". Qty = sisa di CMT; sudah diterima sebelum cutoff {sum(r['qty_diterima'] for r in rows)} pcs.")
        items = []
        for r in rows:
            items.append({**r["item"], "qty": r["sisa"], "cmt_price_snapshot": r["upah"],
                          "selling_price_snapshot": r["harga"] if r["jenis"] == "maklon" else 0})
        body = {"business_type": first["jenis"], "vendor_id": vendor["id"], "po_date": first["tanggal"],
                "status": "Confirmed", "notes": note, "items": items,
                "deadline": next((r["deadline"] for r in rows if r.get("deadline")), None),
                "delivery_deadline": next((r["delivery_deadline"] for r in rows if r.get("delivery_deadline")), None)}
        if first["jenis"] == "maklon":
            body.update({"buyer_id": client.get("id"), "customer_name": client.get("name", "")})
        else:
            body["customer_name"] = TUJUAN_INTERNAL
        from core.doc_number_policy import policy
        if (await policy(db, PO_NUMBER_KEY[first["jenis"]]))["mode"] == "manual":
            body["po_number"] = first["kode"]
        meta = {"key": g["key"], "kode_potongan": first["kode"], "batch": batch,
                "imported_at": now_wib().isoformat(), "imported_by": user.get("name", ""),
                "qty_cut": sum(r["qty_potong"] or 0 for r in rows),
                "qty_received_before": sum(r["qty_diterima"] for r in rows),
                "qty_open": sum(r["sisa"] for r in rows)}
        body["opening_import"] = meta
        po_id = None
        try:
            # cek ulang tepat sebelum membuat (impor kedua yang berjalan bersamaan); indeks unik
            # `opening_import.key` menolak sisanya
            dup = await db.production_pos.find_one({"opening_import.key": g["key"]}, {"_id": 0, "po_number": 1})
            if dup:
                raise ValueError(f"sudah diimpor sebagai {dup.get('po_number')}")
            po = await create_po_internal(db, body, user, opening=True)
            po_id = po["id"]
            ship_items = []
            for it, r in zip(po.get("items") or [], rows):
                await db.po_items.update_one({"id": it["id"]}, {"$set": {
                    "opening_import": True, "opening_qty_cut": r["qty_potong"] or 0,
                    "opening_qty_received": r["qty_diterima"]}})
                ship_items.append({"po_id": po_id, "po_number": po["po_number"], "po_item_id": it["id"],
                                   "qty_sent": r["sisa"], "opening_qty_cut": r["qty_potong"] or 0,
                                   "opening_qty_received": r["qty_diterima"]})
            ship = await create_vendor_shipment_internal(db, {
                "vendor_id": vendor["id"], "po_id": po_id, "po_number": po["po_number"],
                "shipment_date": first["tanggal"], "shipment_type": "NORMAL", "notes": note,
                "items": ship_items}, user, opening=True)
            if first["jenis"] == "maklon":
                # jadwal hutang CMT disegarkan dari surat jalan saldo awal (jalur sinkron biasa)
                await try_sync_maklon_finance(db, po_id, user)
            # job lewat jalur resmi (kunci + cek job ganda) — staf tinggal lapor progres & pengiriman
            job = await create_job_for_shipment_locked(db, ship["id"], vendor["id"], user, notes=JOB_NOTE)
            created.append({"key": g["key"], "po_id": po_id, "po_number": po["po_number"],
                            "shipment_number": ship.get("shipment_number"), "job_number": job.get("job_number"),
                            "baris": len(rows), "sisa": meta["qty_open"]})
        except Exception as e:  # noqa: BLE001 — dilaporkan per kelompok; PO setengah jadi dibatalkan
            detail = getattr(e, "detail", None) or str(e)
            logger.exception("impor PO berjalan gagal (kelompok %s)", g["key"])
            if po_id:
                await _rollback_po(db, po_id, user)
            failed.append({"key": g["key"], "kode_potongan": first["kode"], "baris": [r["row"] for r in rows],
                           "error": str(detail)})
    return {"created": created, "failed": failed, "batch": batch}


async def _rollback_po(db, po_id: str, user: dict) -> None:
    """Batalkan PO impor yang gagal di tengah — jalur hapus PO resmi (void jadwal maklon + kaskade)."""
    try:
        po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "business_type": 1, "po_number": 1})
        if (po or {}).get("business_type") == "maklon":
            from core import maklon_ledger
            await maklon_ledger.void_schedules(db, po_id, user, reason="impor PO berjalan dibatalkan")
        from cascade_delete import cascade_delete_po
        await cascade_delete_po(po_id)
    except Exception:  # noqa: BLE001
        logger.exception("pembatalan PO impor %s gagal — periksa manual", po_id)
