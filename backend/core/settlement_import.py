"""settlement_import — pembaca laporan pencairan Shopee/TikTok → draf angka form F9.

Aturan BD-2 (pemetaan kolom uang TIDAK BOLEH DITEBAK diam-diam) dipatuhi dengan cara:
  · hasil parse TIDAK disimpan — hanya PRATINJAU untuk mengisi form; staf yang menyimpan;
  · setiap field menyebut KOLOM SUMBER-nya, dan kolom angka yang tidak terpetakan
    DITAMPILKAN, supaya potongan yang belum dikenal tidak hilang tanpa nama.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from core.marketing_import_engine import parse_table, parse_number, parse_date, _norm_header

# field → (kata kunci header yang dikenal). Sumber: laporan "Penghasilan Saya" Shopee
# dan "Settlement / Statement" TikTok Shop. Kolom persentase/estimasi dikecualikan.
FIELD_KEYWORDS: Dict[str, List[str]] = {
    "gross_sales": ["harga asli produk", "total harga produk", "total revenue",
                    "subtotal before discount", "harga produk", "gross sales", "omzet bruto"],
    "refunds": ["pengembalian dana", "refund", "dana dikembalikan"],
    "seller_discount": ["diskon produk", "voucher ditanggung penjual", "seller discount",
                        "diskon penjual", "voucher penjual", "cashback koin ditanggung penjual"],
    "shipping_subsidy": ["subsidi ongkir", "shipping subsidy", "shipping fee subsidy",
                         "ongkir ditanggung platform", "platform shipping"],
    "platform_commission": ["biaya administrasi", "platform commission", "komisi platform",
                            "biaya komisi", "commission fee", "biaya admin"],
    "platform_service_fee": ["biaya layanan", "transaction fee", "service fee",
                             "biaya transaksi", "biaya proses pesanan", "biaya program"],
    "affiliate_commission": ["komisi ams", "affiliate commission", "komisi afiliasi",
                             "komisi affiliate", "ams"],
    "ads_deduction": ["iklan", "ads deduction", "biaya ads", "ads fee"],
    "other_deductions": ["biaya lainnya", "other fee", "potongan lain", "biaya lain",
                         "customer service fee", "other deduction"],
    "adjustments": ["adjustment", "penyesuaian", "kompensasi", "compensation"],
    "net_payout": ["total penghasilan", "total settlement amount", "settlement amount",
                   "jumlah dana dilepaskan", "jumlah pencairan", "net payout", "dana diterima",
                   "total penarikan"],
}
DATE_KEYWORDS = ["tanggal dana dilepaskan", "order settled time", "settlement date",
                 "tanggal pencairan", "statement date", "settled time", "waktu pencairan"]
PERIOD_KEYWORDS = ["waktu pesanan dibuat", "order created time", "tanggal pesanan",
                   "order create", "created time", "waktu pembayaran"]
ID_KEYWORDS = ["statement id", "settlement id", "no penarikan", "id pencairan",
               "nomor penarikan", "batch id", "id statement"]
EXCLUDE_TOKENS = ["persen", "%", "rate", "estimasi", "tarif", "qty", "jumlah produk", "kuantitas"]
ID_TOKENS = {"id", "no", "nomor", "sku", "kode"}
# Urutan cocok: yang lebih SPESIFIK dulu ("komisi AMS" = afiliasi, bukan komisi platform).
FIELD_PRIORITY = ["affiliate_commission", "ads_deduction", "net_payout", "refunds", "seller_discount",
                  "shipping_subsidy", "platform_service_fee", "platform_commission",
                  "other_deductions", "adjustments", "gross_sales"]

MAX_UNMAPPED = 30

# 2026-11-06 (Tahap 2) — laporan Penghasilan Shopee versi .xlsx (lihat di bawah).
# Grup kolom yang hanya INFORMASI, bukan komponen dana yang dilepas.
INFO_GROUP_TOKENS = ["buyer info", "informasi pembeli", "informasi referensi",
                     "rincian pengembalian"]
# Diskon yang dibiayai PLATFORM tidak boleh masuk "diskon penjual".
PLATFORM_FUNDED_TOKENS = ["dari shopee", "ditanggung shopee", "disponsori shopee",
                          "dari platform", "ditanggung platform"]
# Nama kolom versi .xlsx yang belum tercakup kata kunci di atas.
FIELD_KEYWORDS["seller_discount"] += ["voucher disponsor oleh penjual",
                                      "cashback koin disponsori penjual",
                                      "co fund disponsor oleh penjual",
                                      "co fund disponsori penjual"]
FIELD_KEYWORDS["ads_deduction"] += ["isi saldo otomatis"]
FIELD_KEYWORDS["platform_service_fee"] += ["biaya kampanye", "biaya gratis ongkir xtra"]
FIELD_KEYWORDS["other_deductions"] += ["premi", "fbs fee"]


# ── 2026-11-06 (Tahap 2) — laporan Penghasilan Shopee "sudah dilepas" (.xlsx) ──
# Bentuk nyata: sheet pertama "Summary" (ringkasan vertikal, bukan tabel), data
# per pesanan di sheet "Penghasilan" dengan TIGA baris kepala (grup kolom, sub-grup,
# lalu nama kolom sebenarnya), dan setiap pesanan muncul DUA kali: baris "Order"
# (angka pesanan) dan baris "Sku" (pecahan per produk yang jumlahnya SAMA dengan
# baris Order). Dulu hanya sheet pertama yang dibaca ⇒ tidak ada kolom uang ⇒ buntu.
HEADER_SCAN_ROWS = 12
ROW_KIND_HEADER = "lihat berdasarkan"      # kolom penanda baris Order / Sku
ROW_KIND_KEEP = "order"
MAX_ROWS = 20000


def _header_score(cells: List[Any]) -> int:
    """Berapa sel di satu baris yang tampak seperti nama kolom laporan pencairan."""
    kws = [k for ks in FIELD_KEYWORDS.values() for k in ks] + DATE_KEYWORDS + PERIOD_KEYWORDS + ID_KEYWORDS
    score = 0
    for c in cells:
        if c is None or isinstance(c, (int, float)):
            continue
        n = _norm_header(c)
        if n and _match(n, kws):
            score += 1
    return score


def _unique_headers(cells: List[Any]) -> List[str]:
    out: List[str] = []
    seen: Dict[str, int] = {}
    for i, c in enumerate(cells):
        h = str(c).strip() if c not in (None, "") else f"kolom_{i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        out.append(h)
    return out


def _read_workbook(raw: bytes, read_only: bool) -> Tuple[str, List[str], List[dict], Dict[str, str]]:
    """Sheet + baris kepala yang PALING mirip laporan pencairan → (sheet, header, baris)."""
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=read_only, data_only=True)
    best: Tuple[int, str, int, List[List[Any]]] = (0, "", -1, [])   # (skor, sheet, baris kepala, matriks)
    try:
        for ws in wb.worksheets:
            if read_only:
                try:
                    ws.reset_dimensions()
                except Exception:  # noqa: BLE001 — tidak semua versi punya
                    pass
            matrix: List[List[Any]] = []
            for values in ws.iter_rows(values_only=True):
                matrix.append(list(values or []))
                if len(matrix) > MAX_ROWS:
                    break
            for i, row in enumerate(matrix[:HEADER_SCAN_ROWS]):
                s = _header_score(row)
                if s > best[0]:
                    best = (s, ws.title, i, matrix)
    finally:
        try:
            wb.close()
        except Exception:  # noqa: BLE001
            pass
    score, sheet, hidx, matrix = best
    if hidx < 0:
        return "", [], [], {}
    header = _unique_headers(matrix[hidx])
    while header and header[-1].startswith("kolom_"):
        header.pop()
    groups = _column_groups(matrix[:hidx], header)
    rows: List[dict] = []
    for values in matrix[hidx + 1:]:
        if not values or all(v in (None, "") for v in values):
            continue
        rows.append({header[j]: (values[j] if j < len(values) else None) for j in range(len(header))})
    return sheet, header, rows, groups


def _column_groups(above: List[List[Any]], header: List[str]) -> Dict[str, str]:
    """Judul GRUP kolom dari baris-baris di atas baris kepala (sel gabungan Excel
    hanya berisi nilai di kolom pertamanya, jadi diisi ke kanan)."""
    out: Dict[str, List[str]] = {h: [] for h in header}
    for row in above:
        cur = ""
        for j, h in enumerate(header):
            v = row[j] if j < len(row) else None
            if v not in (None, ""):
                cur = str(v).strip()
            if cur:
                out[h].append(cur)
    return {h: " / ".join(g) for h, g in out.items() if g}


def read_report_table(raw: bytes, filename: str) -> Tuple[List[str], List[dict], List[str], Dict[str, str]]:
    """Berkas laporan → (header, baris, catatan, grup kolom). Excel: SEMUA sheet diperiksa."""
    notes: List[str] = []
    groups: Dict[str, str] = {}
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        sheet, headers, rows, groups = _read_workbook(raw, read_only=True)
        if len(headers) <= 1:
            # ekspor yang menulis 1 sel per <row> (lihat marketing_import_engine)
            sheet, headers, rows, groups = _read_workbook(raw, read_only=False)
        if sheet:
            notes.append(f"Data dibaca dari sheet “{sheet}”.")
        else:
            # tidak ada baris yang mirip kepala laporan: baca seperti dulu (sheet
            # aktif, baris pertama = kepala) supaya kolom angkanya tetap bisa
            # diarahkan manual — bukan buntu.
            headers, rows = parse_table(raw, filename)
            groups = {}
    else:
        headers, rows = parse_table(raw, filename)

    # Baris "Order" vs "Sku": angka baris Sku adalah PECAHAN baris Order-nya.
    kind_col = next((h for h in headers if _norm_header(h) == ROW_KIND_HEADER), None)
    if kind_col:
        kinds = [_norm_header(r.get(kind_col)) for r in rows]
        if ROW_KIND_KEEP in kinds:
            kept = [r for r, k in zip(rows, kinds) if k == ROW_KIND_KEEP]
            skipped = len(rows) - len(kept)
            if skipped:
                notes.append(f"{skipped} baris rincian per produk (Sku) dilewati — angkanya "
                             "sudah termasuk di baris pesanan (Order), kalau ikut dijumlah "
                             "nilainya menjadi dua kali.")
            rows = kept
    return headers, rows, notes, groups


def _is_id_column(norm: str) -> bool:
    return bool(ID_TOKENS & set(norm.split()))


def _match(norm: str, keywords: List[str]) -> bool:
    return any(_norm_header(k) in norm for k in keywords)


def _is_numeric_column(rows: List[dict], col: str) -> bool:
    seen = 0
    for r in rows[:50]:
        v = r.get(col)
        if v in (None, ""):
            continue
        n, err = parse_number(v)
        if err:
            return False
        if n is None:
            continue                   # "-" = kosong (2026-11-06), bukan teks
        seen += 1
    return seen > 0


def _sum_column(rows: List[dict], col: str) -> float:
    total = 0.0
    for r in rows:
        n, _ = parse_number(r.get(col))
        if n is not None:
            total += n
    return total


def _first_nonempty(rows: List[dict], col: str) -> Optional[str]:
    for r in rows:
        v = r.get(col)
        if v not in (None, ""):
            return str(v).strip()
    return None


def _date_range(rows: List[dict], col: str) -> Tuple[Optional[str], Optional[str]]:
    ds = []
    for r in rows:
        d, _ = parse_date(r.get(col))
        if d:
            ds.append(d.date().isoformat())
    return (min(ds), max(ds)) if ds else (None, None)


def _fingerprint(headers: List[str]) -> str:
    import hashlib
    key = "|".join(sorted(_norm_header(h) for h in headers if _norm_header(h)))
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def compute_values(mapping: Dict[str, List[str]], column_totals: Dict[str, float]) -> Dict[str, float]:
    """Angka per field dari peta kolom + total per kolom. Dipakai server DAN dapat
    ditiru layar (klien menerima `column_totals`) supaya editor pemetaan menghitung sama."""
    values: Dict[str, float] = {}
    for field in FIELD_KEYWORDS:
        total = sum(float(column_totals.get(c) or 0) for c in (mapping.get(field) or []))
        # Platform menulis potongan sebagai angka negatif; form F9 memakai nilai positif
        # dengan arah yang sudah baku — kecuali `adjustments` yang boleh minus.
        values[field] = round(total if field == "adjustments" else abs(total), 2)
    return values


def parse_settlement_report(raw: bytes, filename: str,
                            saved_mapping: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    headers, rows, notes, groups = read_report_table(raw, filename)
    if not headers:
        raise ValueError("Baris header tidak ditemukan di berkas")
    if not rows:
        raise ValueError("Berkas tidak punya baris data (hanya header)")

    mapping: Dict[str, List[str]] = {f: [] for f in FIELD_KEYWORDS}
    used: set = set()
    date_col = period_col = id_col = None
    numeric_cols: List[str] = []
    info_cols: List[str] = []

    for h in headers:
        norm = _norm_header(h)
        if not norm:
            continue
        if date_col is None and _match(norm, DATE_KEYWORDS):
            date_col = h; used.add(h); continue
        if period_col is None and _match(norm, PERIOD_KEYWORDS):
            period_col = h; used.add(h); continue
        if id_col is None and _match(norm, ID_KEYWORDS):
            id_col = h; used.add(h); continue
        if any(t in norm for t in EXCLUDE_TOKENS) or _is_id_column(norm):
            continue
        if not _is_numeric_column(rows, h):
            continue
        # 2026-11-06 (Tahap 2) — kolom di bawah grup INFORMASI (data pembeli,
        # referensi pengembalian) tidak termasuk perhitungan dana dilepas.
        # Contoh nyata: "Pengembalian Dana ke Pembeli" di grup "Informasi
        # Referensi" mengulang angka "Jumlah Pengembalian Dana ke Pembeli" ⇒ refund
        # terhitung dua kali bila ikut dipetakan.
        grp = _norm_header(groups.get(h, ""))
        if grp and any(_norm_header(t) in grp for t in INFO_GROUP_TOKENS):
            info_cols.append(h)
            continue
        numeric_cols.append(h)
        for field in FIELD_PRIORITY:
            if field == "seller_discount" and any(_norm_header(t) in norm for t in PLATFORM_FUNDED_TOKENS):
                continue           # diskon yang DIBIAYAI platform bukan potongan penjual
            if _match(norm, FIELD_KEYWORDS[field]):
                mapping[field].append(h); used.add(h)
                break
    if info_cols:
        notes.append(f"{len(info_cols)} kolom informasi (data pembeli / referensi) tidak ikut "
                     "dihitung: " + ", ".join(info_cols[:6]) + (" …" if len(info_cols) > 6 else ""))

    # Kolom "ads"/"iklan" mudah bertabrakan dengan komisi afiliasi — afiliasi menang.
    for h in list(mapping["ads_deduction"]):
        if h in mapping["affiliate_commission"]:
            mapping["ads_deduction"].remove(h)

    column_totals = {c: round(_sum_column(rows, c), 2) for c in numeric_cols}

    mapping_source = "auto"
    if saved_mapping:
        # Pemetaan yang sudah DIKONFIRMASI staf untuk format ini menang atas tebakan —
        # hanya kolom yang benar-benar ada di berkas yang dipakai.
        confirmed = {f: [c for c in cols if c in column_totals]
                     for f, cols in saved_mapping.items() if f in FIELD_KEYWORDS}
        if any(confirmed.values()):
            mapping = {f: confirmed.get(f, []) for f in FIELD_KEYWORDS}
            used = set(used) | {c for cols in mapping.values() for c in cols}
            mapping_source = "saved"

    values = compute_values(mapping, column_totals)
    unmapped = [c for c in numeric_cols
                if not any(c in cols for cols in mapping.values())][:MAX_UNMAPPED]

    settlement_date = None
    if date_col:
        _, settlement_date = _date_range(rows, date_col)
    period_from = period_to = None
    if period_col:
        period_from, period_to = _date_range(rows, period_col)

    return {
        "row_count": len(rows),
        "filename": filename,
        "values": values,
        "settlement_id": _first_nonempty(rows, id_col) if id_col else None,
        "settlement_date": settlement_date,
        "period_from": period_from,
        "period_to": period_to,
        "mapping": {f: cols for f, cols in mapping.items() if cols},
        "mapping_source": mapping_source,
        "fingerprint": _fingerprint(headers),
        "column_totals": column_totals,
        "numeric_columns": numeric_cols,
        "meta_columns": {"settlement_date": date_col, "period": period_col, "settlement_id": id_col},
        "unmapped_numeric_columns": unmapped,
        "headers": headers,
        # 2026-11-06 (Tahap 2) — keterangan cara berkas dibaca (sheet, baris dilewati)
        "notes": notes,
        "warnings": [],
    }


def guess_platform(headers: List[str]) -> str:
    joined = " ".join(_norm_header(h) for h in headers)
    if re.search(r"\b(settlement|statement|tiktok|affiliate commission)\b", joined):
        return "tiktokshop"
    if re.search(r"(penghasilan|dana dilepaskan|shopee|biaya administrasi)", joined):
        return "shopee"
    return ""
