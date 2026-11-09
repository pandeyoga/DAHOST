"""withdrawal_import — pembaca laporan PENARIKAN saldo Shopee/TikTok → draf baris tahap 2.

Sama seperti impor dana dilepas: hasil parse hanya PRATINJAU. Setiap kolom yang dipakai
disebut namanya dan bisa diganti staf sebelum disimpan; baris yang statusnya bukan
"berhasil" ditandai, bukan dibuang diam-diam.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple

from core.marketing_import_engine import parse_table, parse_number, parse_date, _norm_header

ROLE_KEYWORDS: Dict[str, List[str]] = {
    "reference": ["id penarikan", "withdrawal id", "no penarikan", "nomor penarikan", "transaction id",
                  "id transaksi", "no referensi", "referensi", "reference", "statement id", "batch id"],
    "date": ["tanggal penarikan", "withdrawal date", "waktu penarikan", "tanggal transaksi",
             "transaction time", "tanggal", "date", "waktu", "time"],
    "amount": ["jumlah penarikan", "withdrawal amount", "jumlah", "amount", "nominal", "total", "penarikan"],
    "status": ["status"],
    "bank": ["rekening", "bank", "account"],
}
SUCCESS_TOKENS = ("berhasil", "success", "selesai", "completed", "sukses", "done", "paid", "dibayar")
FAIL_TOKENS = ("gagal", "failed", "batal", "cancel", "ditolak", "reject", "pending", "diproses", "processing")

# ── 2026-11-09 (riset G9, keputusan owner) — laporan SALDO, bukan hanya laporan penarikan ──
# Shopee tidak punya ekspor khusus penarikan: satu-satunya ekspor = laporan Saldo
# (Saldo Saya → Transaksi → Export) yang memuat SEMUA mutasi saldo (penghasilan pesanan,
# isi ulang saldo iklan, penarikan, pengembalian dana) dengan baris judul/ringkasan di atas
# header (header baris ~18). Dulu (a) header dianggap baris 1 → berkas gagal dibaca, dan
# (b) setiap baris dihitung sebagai penarikan → uji sintetis Rp100.000 terbaca Rp300.000.
# Sekarang baris header DICARI (≤ 25 baris) dan, bila ada kolom tipe transaksi, hanya baris
# bertipe penarikan yang dihitung; baris lain DITANDAI (bukan dibuang diam-diam).
HEADER_SCAN = 25
TYPE_KEYWORDS = ["tipe transaksi", "type", "transaction type", "jenis mutasi"]
WITHDRAWAL_TYPES = ("penarikan dana", "penarikan", "withdrawal", "withdraw", "pencairan dana")
DIRECTION_KEYWORDS = ["jenis transaksi", "direction", "arah transaksi"]
INCOMING_TOKENS = ("transaksi masuk", "masuk", "incoming", "in")


def _match(norm: str, keywords: List[str]) -> bool:
    return any(_norm_header(k) in norm for k in keywords)


def _numeric(rows: List[dict], col: str) -> bool:
    seen = 0
    for r in rows[:50]:
        v = r.get(col)
        if v in (None, ""):
            continue
        seen += 1
        if parse_number(v)[0] is None:
            return False
    return seen > 0


def _matrix(raw: bytes, filename: str) -> List[List[Any]]:
    """Seluruh sel berkas (CSV/XLSX sheet pertama yang punya header penarikan)."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            best: List[List[Any]] = []
            for ws in wb.worksheets:
                try:
                    ws.reset_dimensions()
                except Exception:  # noqa: BLE001
                    pass
                m = [list(v or []) for v in ws.iter_rows(values_only=True)]
                if _header_index(m) >= 0:
                    return m
                best = best or m
            return best
        finally:
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4000]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:  # noqa: BLE001
        delim = ";" if sample.count(";") > sample.count(",") else ","
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _header_index(matrix: List[List[Any]]) -> int:
    """Baris header = baris (≤ 25) yang memuat kolom nominal DAN kolom tanggal/tipe."""
    for i, row in enumerate(matrix[:HEADER_SCAN]):
        norms = [_norm_header(c) for c in row if c not in (None, "")]
        if len(norms) < 2:
            continue
        amount = any(n in ("jumlah", "amount", "nominal") or _match(n, ["jumlah penarikan", "withdrawal amount"])
                     for n in norms)
        other = any(_match(n, ROLE_KEYWORDS["date"]) or _match(n, TYPE_KEYWORDS) for n in norms)
        if amount and other:
            return i
    return -1


def read_table(raw: bytes, filename: str) -> Tuple[List[str], List[dict], int]:
    """(header, baris, nomor baris header) — header dicari, bukan dianggap baris pertama."""
    matrix = _matrix(raw, filename)
    hidx = _header_index(matrix)
    if hidx <= 0:
        headers, rows = parse_table(raw, filename)
        return headers, rows, 0
    seen: Dict[str, int] = {}
    header: List[str] = []
    for j, c in enumerate(matrix[hidx]):
        h = str(c).strip() if c not in (None, "") else f"kolom_{j + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        header.append(h)
    rows: List[dict] = []
    for values in matrix[hidx + 1:]:
        if not values or all(v in (None, "") for v in values):
            continue
        rows.append({header[j]: (values[j] if j < len(values) else None) for j in range(len(header))})
    return header, rows, hidx


def guess_mapping(headers: List[str], rows: List[dict]) -> Dict[str, Optional[str]]:
    mapping: Dict[str, Optional[str]] = {k: None for k in ROLE_KEYWORDS}
    mapping["type"] = None
    used: set = set()
    # tipe transaksi lebih dulu supaya kolom "Tipe Transaksi" tidak dimakan peran lain
    mapping["direction"] = None
    for h in headers:
        n = _norm_header(h)
        if mapping["type"] is None and n in [_norm_header(k) for k in TYPE_KEYWORDS]:
            mapping["type"] = h
            used.add(h)
        elif mapping["direction"] is None and n in [_norm_header(k) for k in DIRECTION_KEYWORDS]:
            mapping["direction"] = h
            used.add(h)
    for role in ("reference", "status", "bank", "date", "amount"):
        for h in headers:
            if h in used:
                continue
            n = _norm_header(h)
            if not _match(n, ROLE_KEYWORDS[role]):
                continue
            if role == "amount" and not _numeric(rows, h):
                continue
            if role == "date" and not any(parse_date(r.get(h))[0] for r in rows[:20] if r.get(h) not in (None, "")):
                continue
            mapping[role] = h
            used.add(h)
            break
    return mapping


def _is_withdrawal(type_val: str) -> bool:
    t = _norm_header(type_val)
    return any(t == w or t.startswith(w + " ") for w in WITHDRAWAL_TYPES)


def build_rows(rows: List[dict], mapping: Dict[str, Optional[str]]) -> List[dict]:
    out = []
    type_col = mapping.get("type")
    dir_col = mapping.get("direction")
    for i, r in enumerate(rows):
        d = parse_date(r.get(mapping.get("date") or ""))[0] if mapping.get("date") else None
        amt = parse_number(r.get(mapping.get("amount") or ""))[0] if mapping.get("amount") else None
        ref = str(r.get(mapping.get("reference") or "") or "").strip() if mapping.get("reference") else ""
        status = str(r.get(mapping.get("status") or "") or "").strip() if mapping.get("status") else ""
        bank = str(r.get(mapping.get("bank") or "") or "").strip() if mapping.get("bank") else ""
        s_norm = status.lower()
        tipe = str(r.get(type_col) or "").strip() if type_col else ""
        reason = None
        arah = _norm_header(r.get(dir_col)) if dir_col else ""
        if type_col and not _is_withdrawal(tipe):
            reason = (f"bukan penarikan dana (tipe: {tipe or 'kosong'}) — tidak dihitung "
                      "sebagai uang masuk rekening")
        elif arah and arah in INCOMING_TOKENS:
            reason = "mutasi MASUK ke saldo platform, bukan penarikan ke rekening"
        elif amt is None or abs(amt) < 0.01:
            reason = "nominal kosong/0"
        elif not d:
            reason = "tanggal tidak terbaca"
        elif s_norm and any(t in s_norm for t in FAIL_TOKENS) and not any(t in s_norm for t in SUCCESS_TOKENS):
            reason = f"status '{status}' bukan berhasil"
        out.append({
            "row": i + 1, "withdrawal_date": d.date().isoformat() if d else None,
            "amount": round(abs(amt), 2) if amt is not None else None,
            "reference": ref or None, "status": status or None, "bank": bank or None,
            "type": tipe or None,
            "ok": reason is None, "reason": reason,
        })
    return out


def parse_withdrawal_report(raw: bytes, filename: str,
                            mapping: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
    headers, rows, hidx = read_table(raw, filename)
    if not headers:
        raise ValueError("Baris header tidak ditemukan di berkas")
    if not rows:
        raise ValueError("Berkas tidak punya baris data (hanya header)")
    mp = guess_mapping(headers, rows)
    if mapping:
        mp.update({k: (v if v in headers else None) for k, v in mapping.items() if k in mp})
    if not mp.get("amount"):
        raise ValueError("Kolom nominal penarikan tidak dikenali — pilih kolomnya secara manual.")
    parsed = build_rows(rows, mp)
    joined = " ".join(_norm_header(h) for h in headers)
    platform = "shopee" if "shopee" in joined else "tiktok" if "tiktok" in joined else ""
    if not platform and "saldo akhir" in joined and "tipe transaksi" in joined:
        platform = "shopee"                      # laporan Saldo Shopee (bentuk resmi)
    notes: List[str] = []
    if hidx > 0:
        notes.append(f"Header tabel ada di baris ke-{hidx + 1}; {hidx} baris judul/ringkasan "
                     "di atasnya dilewati.")
    if mp.get("type"):
        bukan = sum(1 for r in parsed if r.get("type") and not _is_withdrawal(r["type"]))
        if bukan:
            notes.append(f"{bukan} baris bukan penarikan dana (mis. penghasilan pesanan, isi ulang "
                         "saldo iklan) ditandai dan TIDAK dihitung.")
    return {
        "filename": filename, "headers": headers, "row_count": len(rows),
        "mapping": mp, "platform_guess": platform, "rows": parsed,
        "sample": rows[:3], "header_row": hidx + 1, "notes": notes,
        "total_ok": round(sum(r["amount"] or 0 for r in parsed if r["ok"]), 2),
    }
