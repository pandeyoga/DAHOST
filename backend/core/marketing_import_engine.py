"""core.marketing_import_engine — **mesin impor marketing yang BEKERJA TANPA AI**.

KENAPA DETERMINISTIK LEBIH DULU, AI BELAKANGAN
----------------------------------------------
Mesin lama (`routes/universal_import.py`) memanggil AI dua kali untuk setiap
impor: sekali untuk menebak jenis data & pemetaan kolom (`_ai_detect_schema`),
sekali lagi untuk menormalkan SETIAP batch baris (`_ai_normalize_rows`). Kalau
panggilan itu gagal — kuota habis, jaringan, atau model berubah perilaku — status
sesi jatuh ke ``queued`` lalu ``failed`` dan **tidak ada jalan lain**: staf tidak
bisa menyelesaikan pekerjaannya hari itu. Impor data adalah pekerjaan rutin harian
staf marketing; membuatnya bergantung pada layanan luar adalah keputusan yang
salah.

Karena itu urutannya dibalik di sini:

1. **Aturan pasti** (`exact`)   — header sama dengan nama/label kolom kanonik.
2. **Kamus sinonim** (`synonym`) — header lazim dari ekspor Shopee/TikTok/
   Tokopedia, ditulis di `marketing_import_schema.py`.
3. **Kemiripan teks** (`fuzzy`) — `difflib` ≥ 0.86 dipakai otomatis; 0.68–0.86
   hanya DIUSULKAN dan harus dikonfirmasi manusia. Ambang ini dipilih supaya
   "Harga Satuan" tidak pernah diam-diam dipetakan ke "Harga Coret".
4. **AI** — hanya kalau staf menekan tombolnya, dan hasilnya pun cuma *usulan*
   yang bisa ditolak. AI tidak pernah menjadi jalur wajib.

DUA CACAT LAIN YANG DIPERBAIKI DI SINI
--------------------------------------
* Mesin lama menulis ``**committed_data`` mentah ke koleksi
  (`universal_import.py:787-797`) — tanpa validasi tipe, tanpa ``account_id``.
  Hasilnya: baris impor tidak pernah muncul di layar yang difilter per toko.
  Di sini setiap nilai **dikonversi & divalidasi**, dan lingkup toko ditempel
  lewat SSOT `core.marketing_account_scope`.
* Mesin lama memetakan dua jenis ke koleksi yang tidak pernah dibaca layar
  (`marketing_discount_campaigns`, `marketing_sample_shipments`). Di sini tujuan
  koleksi hanya boleh berasal dari `marketing_import_schema.SOURCE_TYPES`.

CATATAN ANGKA (ini sumber salah hitung yang paling sering)
----------------------------------------------------------
File dari marketplace Indonesia menulis "Rp 1.250.000" sedangkan ekspor versi
Inggris menulis "1,250,000.50". Keduanya harus jadi 1250000 dan 1250000.5 — bukan
1.25 dan 1250000.50 yang tertukar. :func:`parse_number` memutuskan pemisah desimal
dari **pemisah terakhir** dan dari **panjang grup angka**, lalu menolak (bukan
menebak) kalau tetap ambigu.
"""
from __future__ import annotations

import io
import csv
import re
import difflib
import hashlib
import logging
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional, Tuple

from core.marketing_import_schema import Field, SourceType
from utils.waktu import now_wib

logger = logging.getLogger(__name__)

MAX_ROWS = 20_000
MAX_PREVIEW_ROWS = 500


class TooManyRows(ValueError):
    """Berkas punya baris data lebih dari :data:`MAX_ROWS`.

    2026-11-07 (Asisten AI, audit §3.C #10) — dulu pembaca BERHENTI diam-diam di baris
    ke-20.000: sisa berkas hilang, impor tampak berhasil, dan omzet terhitung kurang
    tanpa satu pun peringatan. Sekarang berkas ditolak dengan jalan keluarnya.
    """

    def __init__(self, filename: str = ""):
        super().__init__(
            f"Berkas{(' ' + filename) if filename else ''} berisi lebih dari "
            f"{MAX_ROWS:,} baris data".replace(",", ".")
            + ". Sistem tidak memotong berkas diam-diam. Pecah berkasnya (mis. ekspor per "
              "minggu atau per setengah bulan) lalu unggah satu per satu.")
FUZZY_AUTO = 0.86        # ≥ ini: dipetakan otomatis
FUZZY_SUGGEST = 0.68     # ≥ ini: hanya diusulkan, wajib konfirmasi


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BACA BERKAS
# ═══════════════════════════════════════════════════════════════════════════════
def _norm_header(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").strip().lower()).strip()


def _read_xlsx(raw: bytes, read_only: bool) -> Tuple[List[str], List[Dict[str, Any]]]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=read_only, data_only=True)
    ws = wb.active
    if read_only:
        # Berkas ekspor sering menyatakan dimensi yang salah (mis. `A1:A1` untuk
        # 65 kolom). Dalam mode read-only openpyxl mempercayai metadata itu.
        try:
            ws.reset_dimensions()
        except Exception as e:  # noqa: BLE001
            logger.debug("reset_dimensions tidak tersedia: %s", e)
    headers: List[str] = []
    rows: List[Dict[str, Any]] = []
    for values in ws.iter_rows(values_only=True):
        if not headers:
            if values is None or all(v in (None, "") for v in values):
                continue
            headers = [str(v).strip() if v is not None else f"kolom_{i+1}"
                       for i, v in enumerate(values)]
            continue
        if values is None or all(v in (None, "") for v in values):
            continue
        if len(rows) >= MAX_ROWS:
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
            raise TooManyRows()
        rows.append({headers[i]: values[i] if i < len(values) else None
                     for i in range(len(headers))})
    try:
        wb.close()
    except Exception as e:  # noqa: BLE001
        logger.debug("gagal menutup workbook: %s", e)
    return headers, rows


def parse_table(raw: bytes, filename: str,
                st: Optional[SourceType] = None, *,
                deteksi: bool = False) -> Tuple[List[str], List[Dict[str, Any]]]:
    """CSV/XLSX → (headers, rows). Baris kosong dibuang, header kosong diberi nama.

    F7.2 — bila `st` membawa `prenorm`, berkas dinormalkan lebih dulu oleh
    `core.marketing_import_prenorm` (memotong metadata/blok section, memilih baris
    header yang benar, menggabungkan sheet) dan hasilnya sudah berkolom kanonik.
    Tanpa jalur ini, ekspor KPI Seller Center terbaca 0 kolom terpetakan.

    ``deteksi=True`` (2026-11-09) — dipakai hanya untuk MENGENALI jenis berkas: penormal
    yang butuh isian staf (periode GMV Max) tidak menolak, sehingga jenisnya tetap bisa
    diusulkan sebelum staf mengisi periodenya.
    """
    if st is not None and getattr(st, "prenorm", ""):
        from core import marketing_import_prenorm as prenorm
        return prenorm.prenormalize(raw, filename, st.prenorm, deteksi=deteksi)

    name = (filename or "").lower()

    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            import openpyxl  # noqa: F401  (dipakai di _read_xlsx)
        except ImportError as e:
            raise ValueError("Server belum punya openpyxl untuk membaca Excel") from e
        headers, rows = _read_xlsx(raw, read_only=True)
        if len(headers) <= 1:
            # CACAT NYATA pada ekspor TikTok Seller Center (dibuktikan 2026-08-11):
            # setiap SEL dibungkus elemen `<row r="1">` sendiri, jadi pembaca aliran
            # (read-only) melihat 65 kolom sebagai 65 "baris" berisi 1 sel.
            # Mode biasa menyusun ulang lewat koordinat sel (`r="B1"`) sehingga
            # tabelnya benar. Tanpa jalur cadangan ini, seluruh berkas terbaca
            # "hanya 1 kolom" dan impor pesanan mustahil.
            logger.warning("xlsx '%s' terbaca 1 kolom di mode aliran — beralih ke "
                           "pembacaan penuh (berkas menulis 1 sel per <row>)", filename)
            headers, rows = _read_xlsx(raw, read_only=False)
        return headers, rows

    # CSV / TSV — deteksi pemisah, karena ekspor Indonesia sering pakai ';'
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except Exception:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    headers = [h.strip() for h in (reader.fieldnames or []) if h is not None]
    rows = []
    for r in reader:
        if all((v is None or str(v).strip() == "") for v in r.values()):
            continue
        if len(rows) >= MAX_ROWS:
            raise TooManyRows(filename or "")
        rows.append({(k or "").strip(): v for k, v in r.items() if k is not None})
    return headers, rows


# ── 2026-11-06 (Tahap 2) — BERKAS YANG DITOLAK PENORMAL TIDAK BOLEH BUNTU ─────
# Dulu bila penormal (ekspor KPI Seller Center) tidak mengenali bentuk berkas,
# unggahan berhenti dengan pesan galat dan staf tidak pernah sampai ke langkah
# pemetaan. Sekarang berkas dibaca APA ADANYA (baris pertama = header) dan
# disertai peringatan, sehingga kolomnya tetap bisa dipetakan manual. Kolom yang
# biasanya diisi penormal (kanal, sumber) diberi nilai tetap bila pasti.
PRENORM_FALLBACK_CONSTANTS: Dict[str, Dict[str, str]] = {
    "shopee_shop_stats": {"channel": "shop", "source": "shopee_shop_stats"},
    "shopee_content_kpi": {"source": "shopee_content_kpi"},
    "shopee_ads_cpc": {},
}


def parse_table_fallback(raw: bytes, filename: str,
                         st: Optional[SourceType]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Baca berkas tanpa penormal + kolom bernilai tetap (lihat di atas)."""
    headers, rows = parse_table(raw, filename, None)
    consts = PRENORM_FALLBACK_CONSTANTS.get(getattr(st, "prenorm", "") or "", {})
    for k, v in consts.items():
        if k not in headers:
            headers.append(k)
        for r in rows:
            r.setdefault(k, v)
    return headers, rows


def parse_table_lenient(raw: bytes, filename: str, st: Optional[SourceType]
                        ) -> Tuple[List[str], List[Dict[str, Any]], Optional[str]]:
    """:func:`parse_table`, tetapi penolakan PENORMAL menjadi peringatan.

    → ``(headers, rows, peringatan)``; ``peringatan`` None bila berkas dikenali.
    Galat baca berkas yang lain (bukan CSV/Excel, rusak) tetap dinaikkan.
    """
    from core.marketing_import_prenorm import PrenormBlocked
    try:
        headers, rows = parse_table(raw, filename, st)
        return headers, rows, None
    except (TooManyRows, PrenormBlocked):
        # bukan "bentuk belum dikenal": jangan dibaca ulang apa adanya. PrenormBlocked =
        # berkas dikenali tetapi isian wajib belum ada (mis. periode GMV Max).
        raise
    except ValueError as e:
        if st is None or not getattr(st, "prenorm", ""):
            raise
        reason = str(e)
    headers, rows = parse_table_fallback(raw, filename, st)
    if not headers or not rows:
        raise ValueError(reason)
    msg = (f"Bentuk berkas ini belum dikenali sebagai ekspor “{st.label}”: {reason} "
           "Supaya pekerjaan tidak berhenti, isi berkas ditampilkan apa adanya. Petakan "
           "kolomnya sendiri di bawah; baris judul atau ringkasan yang ikut terbaca akan "
           "ditolak di pratinjau. Laporkan berkas ini supaya bentuknya bisa dikenali otomatis.")
    return headers, rows, msg


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PEMETAAN KOLOM (tanpa AI)
# ═══════════════════════════════════════════════════════════════════════════════
def auto_map(headers: List[str], st: SourceType) -> List[dict]:
    """Petakan header berkas → field kanonik.

    Hasil per kolom: ``{column, field, field_label, method, score, candidates}``
    ``method``: ``exact`` · ``synonym`` · ``fuzzy`` · ``suggest`` · ``none``
    ``suggest`` berarti **belum** dipakai; layar harus meminta konfirmasi.
    """
    # 2026-11-09 (G5) — field `dihitung` (diturunkan sistem) tidak pernah dipetakan otomatis
    fields = [f for f in st.input_fields if not getattr(f, "dihitung", False)]
    # tabel pencarian
    exact: Dict[str, Field] = {}
    for f in fields:
        exact[_norm_header(f.name)] = f
        exact[_norm_header(f.label)] = f
    syn: Dict[str, Field] = {}
    for f in fields:
        for s in f.synonyms:
            syn.setdefault(_norm_header(s), f)

    pool = list(exact.keys()) + list(syn.keys())
    taken: Dict[str, str] = {}           # field.name -> column
    result: List[dict] = []

    for col in headers:
        n = _norm_header(col)
        chosen: Optional[Field] = None
        method = "none"
        score = 0.0
        candidates: List[dict] = []

        if n in exact:
            chosen, method, score = exact[n], "exact", 1.0
        elif n in syn:
            chosen, method, score = syn[n], "synonym", 0.98
        elif n:
            close = difflib.get_close_matches(n, pool, n=3, cutoff=FUZZY_SUGGEST)
            scored = []
            for c in close:
                f = exact.get(c) or syn.get(c)
                if not f:
                    continue
                r = difflib.SequenceMatcher(None, n, c).ratio()
                scored.append((r, f, c))
            scored.sort(key=lambda x: -x[0])
            # jangan usulkan field yang sama dua kali
            seen = set()
            for r, f, c in scored:
                if f.name in seen:
                    continue
                seen.add(f.name)
                candidates.append({"field": f.name, "field_label": f.label,
                                   "matched_on": c, "score": round(r, 3)})
            if candidates:
                top = candidates[0]
                f = st.field(top["field"])
                if top["score"] >= FUZZY_AUTO and f is not None:
                    chosen, method, score = f, "fuzzy", top["score"]
                else:
                    method, score = "suggest", top["score"]

        if chosen is not None and chosen.name in taken:
            # dua kolom menunjuk satu field: yang kedua jadi usulan, tidak dipakai
            candidates.insert(0, {"field": chosen.name, "field_label": chosen.label,
                                  "matched_on": n, "score": round(score, 3)})
            result.append({"column": col, "field": None, "field_label": None,
                           "method": "suggest", "score": round(score, 3),
                           "candidates": candidates[:3],
                           "note": f"kolom '{taken[chosen.name]}' sudah dipetakan "
                                   f"ke {chosen.label}"})
            continue

        if chosen is not None:
            taken[chosen.name] = col
        result.append({
            "column": col,
            "field": chosen.name if chosen else None,
            "field_label": chosen.label if chosen else None,
            "method": method,
            "score": round(score, 3),
            "candidates": _cand_list(chosen, n, score, candidates),
        })
    return result


def _cand_list(chosen: Optional[Field], norm_col: str, score: float,
               candidates: List[dict]) -> List[dict]:
    """Daftar usulan yang SELALU memuat pilihan mesin sebagai usulan #1.

    Tanpa ini, kolom yang dikenali ``exact``/``synonym`` punya ``candidates: []``
    — sehingga begitu staf melepas kolom itu (“— tidak dipakai —”) satu-satunya
    jalan kembali adalah menelusuri 40+ nama field di dropdown, atau mengunggah
    ulang berkasnya. Pilihan ``fuzzy`` sudah ada di dalam ``candidates``, jadi
    di-dedupe agar tidak muncul dua kali.
    """
    out: List[dict] = []
    seen: set = set()
    if chosen is not None:
        out.append({"field": chosen.name, "field_label": chosen.label,
                    "matched_on": norm_col, "score": round(score, 3)})
        seen.add(chosen.name)
    for c in candidates:
        if c.get("field") in seen:
            continue
        seen.add(c.get("field"))
        out.append(c)
    return out[:4]


def mapping_dict(mapping: List[dict]) -> Dict[str, str]:
    """``[{column, field}]`` → ``{column: field}`` (hanya yang benar-benar dipakai)."""
    out = {}
    for m in mapping or []:
        col, fld = m.get("column"), m.get("field")
        if col and fld and m.get("method") != "suggest":
            out[col] = fld
    return out


def mapping_report(mapping: List[dict], st: SourceType) -> dict:
    used = mapping_dict(mapping)
    mapped_fields = set(used.values())
    missing_required = [f.label for f in st.required_fields if f.name not in mapped_fields]
    unmapped_cols = [m["column"] for m in mapping if not m.get("field")
                     or m.get("method") == "suggest"]
    return {
        "mapped": len(used),
        "total_columns": len(mapping),
        "missing_required": missing_required,
        "unmapped_columns": unmapped_cols,
        "ready": len(missing_required) == 0,
        "methods": {k: sum(1 for m in mapping if m.get("method") == k)
                    for k in ("exact", "synonym", "fuzzy", "suggest", "none")},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. KONVERSI NILAI
# ═══════════════════════════════════════════════════════════════════════════════
_CURRENCY = re.compile(r"(?i)\b(rp|idr|rupiah)\b|[^\d,.\-+eE]")
# 2026-11-09 (riset G21) — teks bertanggal/berjam BUKAN angka. Dulu "01/08/2026" kehilangan
# garis miringnya dan terbaca 1.082.026, sehingga kolom tanggal ikut "kolom uang".
_TAMPAK_TANGGAL = re.compile(r"^\s*(\d{1,4}[/\-.]\d{1,2}[/\-.]\d{2,4}(\s|T|$)|\d{1,2}:\d{2}(:\d{2})?\s*$)")
_TEKS_KOSONG = {"-", "--", "–", "—", "n/a", "na", "tidak terbatas", "none", "null"}

# ── 2026-11-09 (riset G1) — GAYA ANGKA PER KOLOM ──────────────────────────────
# Satu nilai "260.768" mustahil diputuskan sendirian: Rp260.768 (titik ribuan, gaya
# ekspor pesanan Shopee) atau Rp260,768 (titik desimal 3 angka, gaya ekspor GMV Max
# TikTok). Dulu mesin SELALU memilih ribuan → biaya iklan TikTok terbaca 18× lebih
# besar pada berkas contoh (Σ Rp322.063 menjadi Rp5.852.211). Sekarang pemisah desimal
# diputuskan dari SELURUH isi kolom: satu saja nilai "40797.000" (4 angka sebelum titik)
# atau "0.768" membuktikan titik = desimal untuk kolom itu.
GAYA_TITIK_DESIMAL = "titik_desimal"     # "40797.000", "3.15", "1,250,000.50"
GAYA_KOMA_DESIMAL = "koma_desimal"       # "1.250.000", "94.344,64", "2,87"
GAYA_OTOMATIS = ""                        # per nilai (perilaku lama)
_ANGKA_POLOS = re.compile(r"^[\d.,]+$")


def _bersih_angka(s: str) -> str:
    s = s.strip().strip("()")
    s = re.sub(r"(?i)\b(rp|idr|rupiah)\b|%|\s", "", s)
    return s.lstrip("+-")


def _bukti_gaya(s: str) -> str:
    """Bukti gaya dari SATU teks angka: 'titik' | 'koma' | '' (ambigu/tidak ada)."""
    if not _ANGKA_POLOS.match(s) or not re.search(r"\d", s):
        return ""
    if "." in s and "," in s:
        return "titik" if s.rfind(".") > s.rfind(",") else "koma"
    for sep, other in ((".", "koma"), (",", "titik")):
        if sep in s:
            parts = s.split(sep)
            this = "titik" if sep == "." else "koma"
            if len(parts) > 2:
                return other                      # 1.250.000 → titik = ribuan → desimal koma
            head, tail = parts
            if len(tail) != 3:
                return this                       # 12.5 / 0.77 / 3,15 → pemisah = desimal
            if len(head) > 3 or head in ("", "0"):
                return this                       # 40797.000 / 0.768 → tidak mungkin ribuan
            return ""                             # ddd.ddd — ambigu
    return ""


def gaya_angka_kolom(values) -> str:
    """Gaya pemisah desimal satu kolom, diputuskan dari semua nilainya.

    → :data:`GAYA_TITIK_DESIMAL` / :data:`GAYA_KOMA_DESIMAL` bila buktinya searah,
    :data:`GAYA_OTOMATIS` bila tidak ada bukti atau buktinya bertentangan (nilai
    tetap dibaca satu per satu seperti dulu — tidak ada tebakan baru)."""
    titik = koma = 0
    for v in values:
        if v is None or isinstance(v, (bool, int, float)):
            continue
        s = _bersih_angka(str(v))
        b = _bukti_gaya(s)
        if b == "titik":
            titik += 1
        elif b == "koma":
            koma += 1
    if titik and not koma:
        return GAYA_TITIK_DESIMAL
    if koma and not titik:
        return GAYA_KOMA_DESIMAL
    return GAYA_OTOMATIS


def parse_number(raw: Any, gaya: str = GAYA_OTOMATIS) -> Tuple[Optional[float], Optional[str]]:
    """Angka dari teks apa pun yang lazim di ekspor marketplace.

    Menerima: ``1250000`` · ``"Rp 1.250.000"`` · ``"1,250,000.50"`` ·
    ``"1.250.000,50"`` · ``"(1.500)"`` (negatif akuntansi) · ``"12,5%"``.
    Menolak (bukan menebak) kalau pemisahnya tidak konsisten.

    ``gaya`` (2026-11-09, G1) = gaya pemisah desimal KOLOM ini (lihat
    :func:`gaya_angka_kolom`); kosong = diputuskan per nilai seperti dulu.
    """
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, bool):
        return (1.0 if raw else 0.0), None
    if isinstance(raw, (int, float)):
        return float(raw), None

    s = str(raw).strip()
    if s.lower() in _TEKS_KOSONG:
        return None, None
    if _TAMPAK_TANGGAL.match(s):
        return None, f"'{raw}' tampak seperti tanggal/jam, bukan angka"
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = _CURRENCY.sub("", s).strip()
    if s in ("", "-", "+"):
        return None, None
    if s.startswith("-"):
        neg = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    if gaya in (GAYA_TITIK_DESIMAL, GAYA_KOMA_DESIMAL) and re.fullmatch(r"[\d.,]+", s):
        dec, thou = (".", ",") if gaya == GAYA_TITIK_DESIMAL else (",", ".")
        if s.count(dec) > 1:
            return None, (f"format angka '{raw}' tidak cocok dengan kolomnya "
                          f"(pemisah desimal '{dec}' muncul lebih dari sekali)")
        t = s.replace(thou, "").replace(dec, ".")
        try:
            v = float(t)
        except ValueError:
            return None, f"'{raw}' bukan angka"
        return (-v if neg else v), None

    has_dot, has_com = "." in s, "," in s
    if has_dot and has_com:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        s = s.replace(thou, "").replace(dec, ".")
    elif has_com:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = s.replace(",", ".")                     # desimal
        elif all(len(p) == 3 for p in parts[1:]):
            s = s.replace(",", "")                      # ribuan
        else:
            return None, f"format angka '{raw}' ambigu (pemisah ',' tidak konsisten)"
    elif has_dot:
        parts = s.split(".")
        if len(parts) > 2 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")                      # 1.250.000
        elif len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
            s = s.replace(".", "")                      # 1.250 → 1250 (gaya Indonesia)
        # sisanya dianggap desimal biasa
    try:
        v = float(s)
    except ValueError:
        return None, f"'{raw}' bukan angka"
    return (-v if neg else v), None


_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    # 2026-11-09 (riset G22) — Statistik Toko/Live Shopee: "13-08-2026 00:00"
    "%d-%m-%Y %H:%M",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y",
)
# Penanda "tidak ada nilai" yang lazim di ekspor marketplace.
# 2026-11-09 (riset F20) — laporan iklan Shopee menulis "Tidak Terbatas" untuk kampanye
# tanpa tanggal selesai: itu KOSONG, bukan tanggal rusak.
_EMPTY_MARKS = ("-", "--", "–", "—", "Tidak Terbatas", "tidak terbatas", "N/A")
_RENTANG_TANGGAL = re.compile(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}.*\d{1,2}[-/]\d{1,2}[-/]\d{4}|"
                              r"\d{4}-\d{2}-\d{2}.+\d{4}-\d{2}-\d{2}")
_ID_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "agu": 8, "ags": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12,
}


def parse_date(raw: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """Tanggal dari teks/serial Excel → datetime (UTC, naive-aware)."""
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, datetime):
        return (raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)), None
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, tzinfo=timezone.utc), None
    if isinstance(raw, (int, float)) and 20000 < float(raw) < 60000:
        # serial Excel (1899-12-30 sebagai hari ke-0)
        from datetime import timedelta
        base = datetime(1899, 12, 30, tzinfo=timezone.utc)
        return base + timedelta(days=float(raw)), None

    s = str(raw).strip()
    if not s:
        return None, None
    # 2026-11-06 (Tahap 2) — ekspor Shopee menulis "-" untuk waktu yang belum ada
    # (mis. "Waktu Pembayaran Dilakukan" pada pesanan batal sebelum dibayar).
    # Itu berarti KOSONG, bukan tanggal rusak — dulu seluruh pesanan ditolak.
    if s in _EMPTY_MARKS:
        return None, None
    if _RENTANG_TANGGAL.search(s):
        # "13-08-2026-13-08-2026" = RENTANG, bukan satu tanggal — tidak dipotong diam-diam
        return None, f"'{raw}' berisi rentang tanggal, bukan satu tanggal"
    s = s.replace("Z", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s[:len(now_wib().strftime(fmt)) + 6], fmt)
            return d.replace(tzinfo=timezone.utc), None
        except Exception:
            pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc), None
        except Exception:
            continue
    # "12 Agustus 2026"
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", s)
    if m:
        mon = _ID_MONTHS.get(m.group(2).lower())
        if mon:
            return datetime(int(m.group(3)), mon, int(m.group(1)),
                            tzinfo=timezone.utc), None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc), None
    except Exception:
        pass
    return None, f"'{raw}' bukan tanggal yang dikenali (pakai YYYY-MM-DD atau DD/MM/YYYY)"


_TRUE = {"1", "true", "ya", "yes", "y", "aktif", "active", "benar", "ada"}
_FALSE = {"0", "false", "tidak", "no", "n", "nonaktif", "inactive", "salah", "-"}


def _norm_choice(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").strip().lower()).strip("_")


def value_key(raw: Any) -> str:
    """Kunci pemetaan NILAI pilihan staf (2026-11-06, Tahap 2).

    Angka di dalam teks disamakan, supaya satu pilihan berlaku untuk semua
    variasi tanggal: "… hingga 2026-10-12." dan "… hingga 2026-10-19." = satu kunci.
    """
    return _norm_choice(re.sub(r"\d+", "0", str(raw or "")))


_BERAT_RX = re.compile(r"^\s*([\d.,]+)\s*(kg|kilo|kilogram|g|gr|gram|grm)?\s*$", re.IGNORECASE)


def parse_berat_kg(raw: Any, gaya: str = GAYA_OTOMATIS) -> Tuple[Optional[float], Optional[str]]:
    """Berat → kilogram (2026-11-09, riset G13). "200 gr" → 0,2 · "0.6" → 0,6 · "1,2 kg" → 1,2.

    Angka tanpa satuan dianggap kilogram (kolom ber-label "(kg)" di ekspor TikTok)."""
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw), None
    s = str(raw).strip()
    if s.lower() in _TEKS_KOSONG:
        return None, None
    m = _BERAT_RX.match(s)
    if not m:
        return None, f"'{raw}' bukan berat (contoh yang dikenali: 200 gr, 0,6 kg)"
    v, err = parse_number(m.group(1), gaya)
    if err or v is None:
        return None, err
    unit = (m.group(2) or "kg").lower()
    return (round(v / 1000.0, 6) if unit.startswith("g") else v), None


_ID_ILMIAH = re.compile(r"^\s*\d+(?:[.,]\d+)?[eE][+]?\d+\s*$")


def _id_rusak(f: Field, raw: Any) -> Optional[str]:
    """Pesan galat bila NOMOR (id_teks) sudah rusak oleh Excel; None bila aman (G20)."""
    pesan = (f"{f.label}: '{raw}' sudah berubah menjadi angka ilmiah/bulat oleh Excel — digit "
             "terakhirnya hilang dan pesanan berbeda bisa tertukar. Ekspor ulang dari Seller "
             "Center dan unggah berkas aslinya TANPA dibuka-simpan di Excel.")
    if isinstance(raw, float):
        return pesan if (not raw.is_integer() or abs(raw) >= 1e15) else None
    if isinstance(raw, int) and not isinstance(raw, bool):
        return pesan if len(str(abs(raw))) >= 16 else None
    if isinstance(raw, str) and _ID_ILMIAH.match(raw):
        return pesan
    return None


def _prefix_hit(f: Field, s_norm: str) -> Optional[str]:
    for prefix, canon_v in f.value_prefix_map:
        p = _norm_choice(prefix)
        if p and s_norm.startswith(p):
            return canon_v
    return None


def coerce(f: Field, raw: Any,
           extra_map: Optional[Dict[str, str]] = None, *,
           gaya: str = GAYA_OTOMATIS,
           skala_pecahan: Optional[bool] = None) -> Tuple[Any, Optional[str], Optional[str]]:
    """Konversi satu sel. → ``(nilai, error, warning)``.

    ``extra_map`` (2026-11-06, Tahap 2) = pemetaan NILAI yang dipilih staf di
    langkah pemetaan (kunci :func:`value_key` → nilai kanonik). Pilihan manusia
    menang atas kamus; hanya berlaku untuk field ber-``choices``.

    2026-11-09 — profil KOLOM (lihat :func:`profil_kolom`):
    ``gaya`` = pemisah desimal kolom (G1); ``skala_pecahan`` = kolom persen yang
    SELURUHNYA berupa pecahan 0–1 tanpa tanda "%" (rasio 0.0359 → 3,59%). ``None`` =
    tidak ada profil (diputuskan per nilai seperti dulu).
    """
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if f.required:
            return None, f"{f.label} wajib diisi", None
        return None, None, None
    if f.id_teks:
        rusak = _id_rusak(f, raw)
        if rusak:
            return None, rusak, None
        if isinstance(raw, float) and raw.is_integer():
            raw = str(int(raw))
        elif isinstance(raw, int) and not isinstance(raw, bool):
            raw = str(raw)

    pre_warn: Optional[str] = None
    if extra_map and f.choices:
        chosen = extra_map.get(value_key(raw))
        if chosen in f.choices:
            # Nilai kanonik pilihan staf; kamus & tebakan dilewati sepenuhnya.
            return chosen, None, None
    # ── F1 — KAMUS NILAI (value_map): "Perlu dikirim" → paid ─────────────────
    # Ditulis, bukan ditebak. Nilai yang tidak ada di kamus:
    #   · field penting (status)      ⇒ baris DITOLAK, pesan memuat nilai aslinya
    #   · field keterangan (kurir/kanal, punya `value_map_fallback`) ⇒ jatuh ke
    #     nilai fallback + PERINGATAN, supaya nama kurir baru tidak menghapus omzet
    if f.value_map:
        vm = {_norm_choice(k): v for k, v in f.value_map}
        canon = {_norm_choice(c) for c in f.choices}
        s_norm = _norm_choice(raw)
        if s_norm in vm:
            raw = vm[s_norm]
        elif s_norm in canon:
            pass                                   # sudah kanonik (mis. hasil re-impor)
        elif _prefix_hit(f, s_norm):
            raw = _prefix_hit(f, s_norm)           # status bertanggal (awalan tertulis)
        else:
            close = difflib.get_close_matches(s_norm, list(vm.keys()), n=1, cutoff=0.88)
            if close:
                raw = vm[close[0]]
                pre_warn = (f"{f.label}: '{raw}' dipadankan dari nilai mirip "
                            f"'{close[0]}' — periksa sekali")
            elif f.value_map_fallback:
                pre_warn = (f"{f.label}: nilai '{raw}' belum ada di kamus, "
                            f"dicatat sebagai '{f.value_map_fallback}' (nilai asli tetap disimpan)")
                raw = f.value_map_fallback
            else:
                return None, (f"{f.label}: nilai '{raw}' tidak ada di kamus. "
                              f"Nilai yang dikenali: "
                              + ", ".join(sorted({k for k, _ in f.value_map})[:8])
                              + ". Pilih artinya di langkah pemetaan (bagian "
                                "“Arti nilai di berkas”) — jangan dipaksa masuk."), None

    k = f.kind
    if k in ("str", "list"):
        s = str(raw).strip()
        if k == "list":
            return [x.strip() for x in re.split(r"[;,]", s) if x.strip()], None, pre_warn
        return s, None, pre_warn

    if k == "bool":
        s = _norm_choice(raw)
        if s in _TRUE:
            return True, None, pre_warn
        if s in _FALSE:
            return False, None, pre_warn
        return None, f"{f.label}: '{raw}' bukan ya/tidak", None

    if k == "enum":
        s = _norm_choice(raw)
        allowed = {_norm_choice(c): c for c in f.choices}
        if s in allowed:
            return allowed[s], None, pre_warn
        # kecocokan longgar: "Flash Sale!" → flash_sale
        close = difflib.get_close_matches(s, list(allowed.keys()), n=1, cutoff=0.8)
        if close:
            return allowed[close[0]], None, (
                f"{f.label}: '{raw}' ditafsirkan sebagai '{allowed[close[0]]}'")
        return None, (f"{f.label}: '{raw}' tidak dikenali. Pilihan yang sah: "
                      + ", ".join(f.choices)), None

    if k in ("date", "datetime"):
        d, err = parse_date(raw)
        if err:
            return None, f"{f.label}: {err}", None
        if d is None:
            return None, None, pre_warn
        return (d.date().isoformat() if k == "date" else d), None, pre_warn

    if k == "kg":
        v, err = parse_berat_kg(raw, gaya)
        if err:
            return None, f"{f.label}: {err}", None
        return v, None, pre_warn

    v, err = parse_number(raw, gaya)
    if err:
        return None, f"{f.label}: {err}", None
    if v is None:
        return None, None, pre_warn
    if k == "int":
        if abs(v - round(v)) > 1e-6:
            return int(round(v)), None, f"{f.label}: {raw} dibulatkan ke {int(round(v))}"
        v = int(round(v))
    if k in ("money", "int", "num") and v < 0:
        return v, None, f"{f.label}: nilai negatif ({v}) — pastikan bukan salah tanda"
    if k == "pct":
        if v < 0:
            return None, f"{f.label}: persen tidak boleh negatif", None
        # 2026-11-09 (riset G2) — "0,50%" SUDAH persen (0,5%). Dulu setiap nilai ≤ 1
        # dikali 100, jadi konversi 0,50% tampil 50% dan CTR 0,77% tampil 77%. Skala
        # 0–1 → 0–100 hanya untuk nilai TANPA tanda "%" pada kolom pecahan.
        ada_persen = isinstance(raw, str) and "%" in raw
        if not ada_persen and v <= 1 and v != 0 and skala_pecahan is not False:
            return v * 100, None, (
                None if skala_pecahan else
                f"{f.label}: {raw} ditafsirkan {v*100:.4g}% (skala 0–1 → 0–100)")
        if v > 100:
            return v, None, f"{f.label}: {v} lebih dari 100% — periksa sekali"
    return v, None, pre_warn


# ═══════════════════════════════════════════════════════════════════════════════
# 4. BANGUN & VALIDASI BARIS
# ═══════════════════════════════════════════════════════════════════════════════
def strip_description_rows(rows: List[dict], mapping: List[dict],
                           st: SourceType) -> Tuple[List[dict], int]:
    """Buang baris DESKRIPSI KOLOM yang dipasang marketplace di baris pertama.

    Ekspor TikTok Seller Center menaruh keterangan kolom di baris ke-2 berkas
    ("Platform unique order ID.", "Current order status.", …). Tanpa ini, baris
    itu ikut dihitung sebagai data: 601 baris menjadi 602, dan satu "pesanan"
    palsu ber-`order_id` = teks keterangan lolos ke laporan.

    Aturan (sengaja ketat supaya baris data asli tidak pernah terbuang):
    baris PERTAMA dianggap deskripsi bila **≥60%** sel pada kolom bertipe
    ``money/int/num/date/datetime`` berisi teks yang **gagal** di-parse sebagai
    angka/tanggal **dan** panjang teksnya > 15 karakter.
    """
    if not rows:
        return rows, 0
    used = mapping_dict(mapping)
    checked = 0
    texty = 0
    first = rows[0]
    for col, fname in used.items():
        f = st.field(fname)
        if f is None or f.kind not in ("money", "int", "num", "date", "datetime"):
            continue
        checked += 1
        raw = first.get(col)
        if raw is None or str(raw).strip() == "":
            continue
        s = str(raw).strip()
        if f.kind in ("date", "datetime"):
            val, err = parse_date(s)
            failed = err is not None or val is None
        else:
            val, err = parse_number(s)
            failed = err is not None or val is None
        if failed and len(s) > 15:
            texty += 1
    if checked >= 3 and texty / checked >= 0.6:
        return rows[1:], 1
    return rows, 0


def format_fingerprint(headers: List[str]) -> str:
    """Sidik jari susunan kolom berkas — dipakai untuk MENGINGAT pemetaan.

    Fingerprint yang sama ⇒ pemetaan langsung dipakai (tanpa AI, tanpa tanya).
    Fingerprint baru ⇒ wizard MEMINTA konfirmasi; tidak pernah menebak diam-diam.
    """
    norm = [_norm_header(h) for h in (headers or []) if str(h or "").strip() != ""]
    return hashlib.sha1("|".join(norm).encode("utf-8")).hexdigest()


def mapping_value_overrides(mapping: List[dict]) -> Dict[str, Dict[str, str]]:
    """Pemetaan NILAI pilihan staf yang menempel di entri pemetaan kolom.

    Disimpan DI DALAM ``mapping`` (``{column, field, value_map: {kunci: kanonik}}``)
    supaya setiap pemakai pemetaan — pratinjau, rencana, commit, unduh galat —
    otomatis memakai keputusan yang sama tanpa parameter tambahan.
    """
    out: Dict[str, Dict[str, str]] = {}
    for m in mapping or []:
        vm = m.get("value_map") if isinstance(m, dict) else None
        if m.get("field") and m.get("method") != "suggest" and isinstance(vm, dict) and vm:
            out[m["field"]] = {str(k): str(v) for k, v in vm.items() if v}
    return out


# 2026-11-09 — catatan TINGKAT BERKAS dari penormal (mis. "berkas tepat 100.000 baris —
# mungkin terpotong"). Penormal hanya mengembalikan tabel, jadi catatan ditempel di setiap
# baris dengan kunci ini (bukan kolom header, tidak pernah dipetakan) dan mesin
# menjadikannya PERINGATAN baris supaya tampil di pratinjau yang sudah ada.
KOLOM_CATATAN = "Catatan sistem"
_JENIS_ANGKA = ("money", "int", "num", "pct", "kg")


def profil_kolom(rows: List[dict], used: Dict[str, str], st: SourceType) -> Dict[str, dict]:
    """Profil kolom angka yang terpetakan: ``{kolom: {gaya, skala_pecahan}}`` (G1/G2).

    Dihitung dari SELURUH baris berkas sekali, sehingga pratinjau (500 baris pertama) dan
    commit (semua baris) membaca angka dengan cara yang SAMA."""
    out: Dict[str, dict] = {}
    for col, fname in used.items():
        f = st.field(fname)
        if f is None or f.kind not in _JENIS_ANGKA:
            continue
        vals = [r.get(col) for r in rows]
        gaya = gaya_angka_kolom(vals)
        skala = None
        if f.kind == "pct":
            ada = [v for v in vals if v not in (None, "") and str(v).strip().lower() not in _TEKS_KOSONG]
            if ada:
                tanpa_persen = all(not (isinstance(v, str) and "%" in v) for v in ada)
                nilai = [parse_number(v, gaya)[0] for v in ada]
                nilai = [x for x in nilai if x is not None]
                skala = bool(tanpa_persen and nilai and all(0 <= x <= 1 for x in nilai)
                             and any(x != 0 for x in nilai))
        out[col] = {"gaya": gaya, "skala_pecahan": skala}
    return out


def _coerce_row(raw_row: dict, used: Dict[str, str], st: SourceType,
                overrides: Optional[Dict[str, Dict[str, str]]] = None,
                profil: Optional[Dict[str, dict]] = None
                ) -> Tuple[dict, List[str], List[str]]:
    """Satu baris berkas → (data kanonik, errors, warnings). Tanpa database."""
    data: Dict[str, Any] = {}
    errors: List[str] = []
    warnings: List[str] = []
    for col, fname in used.items():
        f = st.field(fname)
        if f is None:
            continue
        raw = raw_row.get(col)
        p = (profil or {}).get(col) or {}
        val, err, warn = coerce(f, raw, (overrides or {}).get(fname),
                                gaya=p.get("gaya", GAYA_OTOMATIS),
                                skala_pecahan=p.get("skala_pecahan") if profil is not None else None)
        if err:
            errors.append(err)
        if warn:
            warnings.append(warn)
        if val is not None:
            data[fname] = val
            if f.keep_raw and raw not in (None, ""):
                data[f"{fname}_raw"] = str(raw).strip()
    catatan = raw_row.get(KOLOM_CATATAN)
    if catatan:
        warnings.append(str(catatan))
    _pasca_baris(st, data, warnings)
    return data, errors, warnings


# ═══════════════════════════════════════════════════════════════════════════════
# 3b. ARTI GABUNGAN BEBERAPA KOLOM (2026-11-09) — ditulis, tidak ditebak
# ═══════════════════════════════════════════════════════════════════════════════
def _n(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def kanal_platform(v: Any) -> str:
    """Nama platform dari kolom "Purchase Channel", tanpa kata "aplikasi".

    2026-11-11 (berkas asli toko TikTok, owner) — ekspor Seller Center berbahasa Indonesia
    menulis "Aplikasi TikTok", versi Inggris "TikTok". Dulu "Aplikasi TikTok" tidak dikenali
    sebagai TikTok: penjaga platform menolak SELURUH berkas toko TikTok yang benar.
    """
    pc = _n(v)
    for awal in ("aplikasi ", "app "):
        if pc.startswith(awal):
            pc = pc[len(awal):].strip()
    if pc.endswith(" app"):
        pc = pc[:-4].strip()
    return pc


def _pasca_baris(st: SourceType, data: dict, warnings: List[str]) -> None:
    """Arti yang baru pasti bila DUA kolom dibaca bersama. Dipanggil per baris berkas."""
    from core import marketing_import_schema as S
    key = st.key
    if key in ("marketplace_orders", "marketplace_fulfillment"):
        # G16 — TikTok: status "Dikirim" + sub-status "Terkirim" = sudah diterima pembeli
        sub = _n(data.get("substatus_raw"))
        for st_from, sub_val, st_to in S.ORDER_SUBSTATUS_MAP:
            if data.get("status") == st_from and sub == sub_val:
                data["status"] = st_to
                break
    if key == "marketplace_orders":
        # G17 — ekspor terpadu TikTok–Tokopedia: kanal Tokopedia = sub-kanal toko TikTok
        pc = kanal_platform(data.get("purchase_channel"))
        if pc:
            if pc in ("tokopedia", "toped"):
                data["sales_channel"] = "tokopedia"
                data["purchase_channel"] = "TikTok"
            elif pc.startswith("tiktok"):
                data["sales_channel"] = "tiktok"
                # "Aplikasi TikTok" → "TikTok" (nilai asli tetap di purchase_channel_raw)
                data["purchase_channel"] = "TikTok"
    elif key == "returns":
        # G10 — sub-status yang memutuskan (permintaan dibatalkan pembeli)
        sub = _n(data.get("substatus_raw"))
        for sub_val, st_to in S.RETURN_SUBSTATUS_MAP:
            if sub == sub_val:
                data["status"] = st_to
                break
        # Keputusan owner 9 Nov — "Refund only" = barang TIDAK kembali (tidak restock)
        jenis = _n(data.get("refund_type_raw"))
        if jenis:
            if jenis in S.REFUND_ONLY_VALUES:
                data["goods_returned"] = False
            elif jenis in S.GOODS_RETURN_VALUES:
                data["goods_returned"] = True
    elif key == "tiktok_gmv_max":
        _turunan_iklan(data)


def _turunan_iklan(d: dict) -> None:
    """Angka turunan iklan GMV Max — dihitung DI SINI supaya tidak ada rumus kedua di layar."""
    spend = float(d.get("spend") or 0)
    clicks = float(d.get("clicks") or 0)
    impr = float(d.get("impressions") or 0)
    conv = float(d.get("conversions") or 0)
    rev = float(d.get("revenue") or 0)
    d["ctr"] = round(clicks / impr * 100, 2) if impr > 0 else 0.0
    d["cpa"] = round(spend / conv, 2) if conv > 0 else 0.0
    d["roas"] = round(rev / spend, 2) if spend > 0 else 0.0
    days = 1
    try:
        a = datetime.strptime(str(d.get("period_start"))[:10], "%Y-%m-%d")
        b = datetime.strptime(str(d.get("period_end"))[:10], "%Y-%m-%d")
        days = max(1, (b - a).days + 1)
    except ValueError:
        pass
    d["period_days"] = days
    d["spend_per_day_avg"] = round(spend / days, 2)
    d["source_report"] = "tiktok_gmv_max"
    d["ad_platform"] = "tiktok"
    d.setdefault("status", "active")


def omzet_basis_item(item: dict) -> Tuple[Optional[float], str, Optional[str]]:
    """Dasar OMZET satu baris SKU = sebelum diskon − diskon PENJUAL (riset G5, K1/K5).

    Diskon yang dibiayai PLATFORM (TikTok "SKU Platform Discount", Shopee "Diskon Dari
    Shopee") diganti platform ke penjual di pencairan, jadi IKUT omzet; nilainya tetap
    tercatat terpisah sebagai subsidi platform (``sku_platform_discount``).

    → ``(nilai, cara, peringatan)``. Urutan cara (yang pertama bisa dihitung dipakai):
      1. ``sebelum_dikurangi_diskon_penjual`` — subtotal sebelum diskon (atau harga awal ×
         jumlah) − diskon penjual;
      2. ``platform_ditambah_subsidi`` — subtotal platform (sesudah semua diskon) + diskon
         platform;
      3. ``dipetakan`` — kolom dasar omzet yang dipetakan staf sendiri;
      4. ``harga_setelah_diskon_x_jumlah`` — cadangan lama (harga satuan × jumlah).
    Peringatan diisi bila rumus platform (sesudah = sebelum − platform − penjual) tidak cocok.
    """
    def num(k):
        v = item.get(k)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    qty = num("quantity")
    before = num("sku_subtotal_before_discount")
    if before is None and num("sku_unit_original_price") is not None and qty is not None:
        before = round(num("sku_unit_original_price") * qty, 2)
    seller = num("sku_seller_discount")
    platform = num("sku_platform_discount")
    after_all = num("sku_subtotal_after_all_discount")
    if after_all is None and num("sku_unit_deal_price") is not None and qty is not None \
            and num("sku_subtotal_after_discount") is None:
        after_all = round(num("sku_unit_deal_price") * qty, 2)
    warn = None
    if None not in (before, seller, platform, after_all):
        if abs(before - platform - seller - after_all) > 1.0:
            warn = (f"Subtotal SKU tidak cocok rumus platform (sebelum {before:,.0f} − diskon "
                    f"platform {platform:,.0f} − diskon penjual {seller:,.0f} ≠ sesudah "
                    f"{after_all:,.0f}) — periksa pemetaan kolom diskon").replace(",", ".")
    if before is not None and seller is not None:
        return round(before - seller, 2), "sebelum_dikurangi_diskon_penjual", warn
    if after_all is not None:
        return round(after_all + (platform or 0.0), 2), "platform_ditambah_subsidi", warn
    if num("sku_subtotal_after_discount") is not None:
        return num("sku_subtotal_after_discount"), "dipetakan", warn
    if num("sku_unit_deal_price") is not None and qty is not None:
        return round(num("sku_unit_deal_price") * qty, 2), "harga_setelah_diskon_x_jumlah", warn
    return None, "", warn


def _pasca_item(st: SourceType, item: dict, warnings: List[str]) -> None:
    if st.key != "marketplace_orders":
        return
    # subtotal sebelum diskon dari harga awal × jumlah (ekspor Shopee tidak punya kolomnya)
    if item.get("sku_subtotal_before_discount") is None and \
            isinstance(item.get("sku_unit_original_price"), (int, float)) and \
            isinstance(item.get("quantity"), (int, float)):
        item["sku_subtotal_before_discount"] = round(
            float(item["sku_unit_original_price"]) * float(item["quantity"]), 2)
    explicit = item.get("sku_subtotal_after_discount")
    val, cara, warn = omzet_basis_item(item)
    if warn:
        warnings.append(warn)
    if val is None:
        return
    if explicit is not None and cara != "dipetakan" and abs(float(explicit) - val) > 1.0:
        warnings.append(
            f"Kolom dasar omzet yang dipetakan ({float(explicit):,.0f}) berbeda dengan hitungan "
            f"sebelum diskon − diskon penjual ({val:,.0f}); yang dipakai hitungan sistem"
            .replace(",", "."))
    item["sku_subtotal_after_discount"] = val
    item["omzet_basis_source"] = cara


def build_rows(rows: List[dict], mapping: List[dict], st: SourceType,
               limit: int = MAX_PREVIEW_ROWS) -> List[dict]:
    """Terapkan mapping + konversi + validasi. Tidak menyentuh database.

    Untuk jenis ber-``group_by`` (F1: pesanan marketplace), BANYAK baris berkas
    menjadi **satu** entri hasil ber-``items[]`` — lihat :func:`build_grouped_rows`.
    """
    used = mapping_dict(mapping)
    overrides = mapping_value_overrides(mapping)
    # 2026-11-09 (G1/G2) — gaya angka diputuskan dari SELURUH kolom, sekali, sebelum
    # baris mana pun dibaca (pratinjau & commit memakai profil yang sama).
    profil = profil_kolom(rows, used, st)
    if st.is_grouped:
        # Jenis berkelompok: 1 entri = 1 PESANAN, bukan 1 baris berkas. Batas
        # pratinjau per-baris tidak boleh memotong jumlah pesanan, kalau tidak
        # layar melaporkan "500 pesanan" untuk berkas 559 pesanan (dan staf
        # mengira 59 pesanan hilang). Baris sudah dibatasi MAX_ROWS saat dibaca.
        return build_grouped_rows(rows, used, st, limit=MAX_ROWS, overrides=overrides,
                                  profil=profil)
    out: List[dict] = []
    for i, raw_row in enumerate(rows[:limit]):
        data, errors, warnings = _coerce_row(raw_row, used, st, overrides, profil)
        # field wajib yang tidak terpetakan sama sekali
        for f in st.required_fields:
            if f.name not in data and f.label not in " ".join(errors):
                errors.append(f"{f.label} wajib diisi")
        out.append({
            "row_id": i,
            "original": {k: (v if not isinstance(v, (datetime, date)) else str(v))
                         for k, v in raw_row.items()},
            "data": data,
            "errors": errors,
            "warnings": warnings,
            "status": "error" if errors else ("warning" if warnings else "valid"),
        })
    return out


def build_grouped_rows(rows: List[dict], used: Dict[str, str], st: SourceType,
                       limit: int = MAX_PREVIEW_ROWS,
                       overrides: Optional[Dict[str, Dict[str, str]]] = None,
                       profil: Optional[Dict[str, dict]] = None) -> List[dict]:
    """Kelompokkan baris per ``st.group_by`` ⇒ 1 entri = 1 dokumen ber-``items[]``.

    KENAPA (SSOT_KONTRAK_DATA §2): ekspor memberi 1 baris per SKU. Kalau setiap
    baris disimpan sebagai dokumen sendiri, 41 pembaca yang menghitung
    ``$sum: 1`` sebagai "jumlah pesanan" dan ``$sum: '$total_payment'`` sebagai
    omzet akan **salah** (601 pesanan & omzet dobel, padahal 559 pesanan).

    Aturan:
    * field di ``item_fields``    → masuk ``items[]`` (1 elemen per baris)
    * field lain                 → header, nilai dari **baris pertama** pesanan;
                                   nilai berbeda antar baris ⇒ **peringatan**
                                   (bukan galat) dengan menyebut kedua nilainya
    * field di ``per_order_money`` → hanya dari baris pertama, **dilarang** dijumlah
    """
    groups: Dict[tuple, dict] = {}
    order: List[tuple] = []
    orphan: List[dict] = []
    item_required = [f for f in st.required_fields if f.name in st.item_fields]
    header_required = [f for f in st.required_fields if f.name not in st.item_fields]

    if profil is None:
        profil = profil_kolom(rows, used, st)
    for i, raw_row in enumerate(rows):
        data, errors, warnings = _coerce_row(raw_row, used, st, overrides, profil)
        key = tuple(str(data.get(g)) if data.get(g) is not None else "" for g in st.group_by)
        if any(k == "" for k in key):
            orphan.append({
                "row_id": i,
                "original": {k: (v if not isinstance(v, (datetime, date)) else str(v))
                             for k, v in raw_row.items()},
                "data": data,
                "errors": errors + [f"{', '.join(st.group_by)} kosong — baris tidak bisa "
                                    f"dikelompokkan ke pesanan mana pun"],
                "warnings": warnings,
                "status": "error",
            })
            continue

        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "row_id": i, "raw_row_ids": [], "header": {}, "items": [],
                "errors": [], "warnings": [], "first_original": {
                    k: (v if not isinstance(v, (datetime, date)) else str(v))
                    for k, v in raw_row.items()},
            }
            order.append(key)
        g["raw_row_ids"].append(i)
        g["errors"].extend(errors)
        g["warnings"].extend(warnings)

        # ── items[] ──────────────────────────────────────────────────────────
        item = {k: v for k, v in data.items()
                if k in st.item_fields or (k.endswith("_raw") and k[:-4] in st.item_fields)}
        for f in item_required:
            if f.name not in item:
                g["errors"].append(f"baris berkas ke-{i + 2}: {f.label} wajib diisi")
        _pasca_item(st, item, g["warnings"])
        item["line_no"] = len(g["items"]) + 1
        item["raw_row_id"] = i
        g["items"].append(item)

        # ── header (nilai baris pertama; beda ⇒ peringatan) ──────────────────
        for k, v in data.items():
            if k in st.item_fields or (k.endswith("_raw") and k[:-4] in st.item_fields):
                continue
            if k not in g["header"]:
                g["header"][k] = v
            elif g["header"][k] != v:
                fld = st.field(k)
                lbl = fld.label if fld else k
                note = "dipakai nilai baris pertama"
                if k in st.per_order_money:
                    note = "dipakai nilai baris pertama — uang per pesanan TIDAK dijumlah"
                g["warnings"].append(
                    f"{lbl} berbeda antar baris pesanan ini "
                    f"('{g['header'][k]}' vs '{v}') — {note}")

    out: List[dict] = list(orphan)
    for key in order[:limit]:
        g = groups[key]
        errors = list(dict.fromkeys(g["errors"]))
        warnings = list(dict.fromkeys(g["warnings"]))
        for f in header_required:
            if f.name not in g["header"] and f.label not in " ".join(errors):
                errors.append(f"{f.label} wajib diisi")
        data = dict(g["header"])
        # G6 — uang per SKU yang juga dibutuhkan sebagai total pesanan: DIJUMLAH
        for fname in st.item_sum_fields:
            vals = [float(it[fname]) for it in g["items"]
                    if isinstance(it.get(fname), (int, float)) and not isinstance(it.get(fname), bool)]
            if vals:
                data[fname] = round(sum(vals), 2)
        data["items"] = g["items"]
        data["raw_row_ids"] = g["raw_row_ids"]
        out.append({
            "row_id": g["row_id"],
            "group_key": " / ".join(key),
            "rows_in_group": len(g["raw_row_ids"]),
            "items_count": len(g["items"]),
            "original": g["first_original"],
            "data": data,
            "errors": errors,
            "warnings": warnings,
            "status": "error" if errors else ("warning" if warnings else "valid"),
        })
    out.sort(key=lambda r: r["row_id"])
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 4b. ARTI NILAI DI BERKAS (2026-11-06, Tahap 2)
# ═══════════════════════════════════════════════════════════════════════════════
# Kolom pilihan (status, kurir, kanal) dulu hanya bisa dipetakan KOLOMNYA. Nilai
# yang tidak ada di kamus — mis. "Telah Dikirim" — menolak seluruh pesanan, dan
# satu-satunya jalan keluar adalah meminta programmer menambah kamus. Laporan di
# bawah memperlihatkan setiap nilai berbeda di berkas beserta artinya menurut
# kamus, supaya staf bisa MEMILIH arti nilai yang belum dikenal (disimpan di
# entri pemetaan kolomnya, lihat :func:`mapping_value_overrides`).
VALUE_REPORT_MAX = 40
_VALUE_SCAN_MAX = 500


def _auto_meaning(f: Field, raw: Any) -> Tuple[Optional[str], str]:
    """(nilai kanonik, dasar) menurut kamus/tebakan mesin — TANPA pilihan staf."""
    val, err, warn = coerce(f, raw)
    if err or val is None:
        return None, "tidak_dikenal"
    s_norm = _norm_choice(raw)
    if f.value_map:
        if s_norm in {_norm_choice(k) for k, _ in f.value_map}:
            return val, "kamus"
        if s_norm in {_norm_choice(c) for c in f.choices}:
            return val, "baku"
        if _prefix_hit(f, s_norm):
            return val, "awalan"
        if f.value_map_fallback and val == f.value_map_fallback and warn and "kamus" in warn:
            return val, "cadangan"
        return val, "mirip"
    return val, ("baku" if s_norm in {_norm_choice(c) for c in f.choices} else "mirip")


def value_report(rows: List[dict], mapping: List[dict], st: SourceType,
                 max_values: int = VALUE_REPORT_MAX) -> List[dict]:
    """Nilai berbeda per kolom PILIHAN yang terpetakan + artinya. Tanpa database."""
    used = mapping_dict(mapping)
    overrides = mapping_value_overrides(mapping)
    out: List[dict] = []
    for col, fname in used.items():
        f = st.field(fname)
        if f is None or f.kind != "enum" or not f.choices:
            continue
        groups: Dict[str, dict] = {}
        scan_truncated = False
        for r in rows:
            raw = r.get(col)
            if raw is None or str(raw).strip() == "":
                continue
            k = value_key(raw)
            g = groups.get(k)
            if g is None:
                if len(groups) >= _VALUE_SCAN_MAX:
                    scan_truncated = True
                    continue
                g = groups[k] = {"key": k, "raw": str(raw).strip(), "count": 0, "_v": set()}
            g["count"] += 1
            if len(g["_v"]) < 100:
                g["_v"].add(str(raw).strip())
        chosen_map = overrides.get(fname, {})
        vals = []
        for g in groups.values():
            auto, how = _auto_meaning(f, g["raw"])
            chosen = chosen_map.get(g["key"])
            chosen = chosen if chosen in f.choices else None
            vals.append({
                "key": g["key"], "raw": g["raw"], "count": g["count"],
                "variants": len(g["_v"]),
                "auto": auto, "auto_label": f.choice_label(auto) if auto else "",
                "auto_how": how,
                "chosen": chosen, "chosen_label": f.choice_label(chosen) if chosen else "",
            })
        # nilai yang belum punya arti di atas, lalu yang paling sering muncul
        vals.sort(key=lambda v: (v["auto"] is not None or v["chosen"] is not None, -v["count"]))
        unknown = [v for v in vals if v["auto"] is None and not v["chosen"]]
        out.append({
            "field": fname, "label": f.label, "column": col, "required": f.required,
            "fallback": f.value_map_fallback,
            "fallback_label": f.choice_label(f.value_map_fallback) if f.value_map_fallback else "",
            "choices": [{"value": c, "label": f.choice_label(c)} for c in f.choices],
            "values": vals[:max_values],
            "distinct": len(vals),
            "unknown": len(unknown),
            "unknown_rows": sum(v["count"] for v in unknown),
            "truncated": scan_truncated or len(vals) > max_values,
        })
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TEMPLATE UNDUHAN
# ═══════════════════════════════════════════════════════════════════════════════
def build_template_csv(st: SourceType) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    fields = st.input_fields
    w.writerow([f.label for f in fields])
    w.writerow([f.example or "" for f in fields])
    return buf.getvalue().encode("utf-8-sig")


def build_template_xlsx(st: SourceType) -> bytes:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    fields = st.input_fields

    head_fill = PatternFill("solid", fgColor="1F2937")
    req_fill = PatternFill("solid", fgColor="B91C1C")
    for c, f in enumerate(fields, 1):
        cell = ws.cell(row=1, column=c, value=f.label + (" *" if f.required else ""))
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = req_fill if f.required else head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.cell(row=2, column=c, value=f.example or None)
        ws.column_dimensions[get_column_letter(c)].width = max(14, min(34, len(f.label) + 6))
    ws.freeze_panes = "A3"

    doc = wb.create_sheet("Petunjuk")
    doc.column_dimensions["A"].width = 30
    doc.column_dimensions["B"].width = 16
    doc.column_dimensions["C"].width = 10
    doc.column_dimensions["D"].width = 62
    doc["A1"] = f"TEMPLATE IMPOR — {st.label}"
    doc["A1"].font = Font(bold=True, size=13)
    doc["A2"] = st.describe
    doc["A3"] = f"Hasil impor tampil di menu: {st.module_hint}"
    doc["A4"] = ("Toko/akun TIDAK diisi di file ini — dipilih di layar sebelum upload, "
                 "supaya satu file tidak bisa tercampur antar toko.")
    for i, h in enumerate(["Kolom", "Jenis Isi", "Wajib", "Keterangan / Pilihan yang sah"], 1):
        c = doc.cell(row=6, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = head_fill
    r = 7
    kind_label = {"str": "teks", "date": "tanggal", "datetime": "tanggal",
                  "int": "bilangan bulat", "num": "angka", "money": "rupiah",
                  "pct": "persen (0-100)", "bool": "ya / tidak", "enum": "pilihan",
                  "list": "daftar (pisah koma)", "kg": "berat (kg atau gr)"}
    for f in fields:
        doc.cell(row=r, column=1, value=f.label)
        doc.cell(row=r, column=2, value=kind_label.get(f.kind, f.kind))
        doc.cell(row=r, column=3, value="WAJIB" if f.required else "opsional")
        note = f.note
        if f.choices:
            note = (note + " · " if note else "") + "pilihan: " + ", ".join(f.choices)
        if f.synonyms:
            note = (note + " · " if note else "") + "header lain yang dikenali: " + \
                   ", ".join(f.synonyms[:6])
        doc.cell(row=r, column=4, value=note or "-").alignment = Alignment(wrap_text=True)
        r += 1

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# 6. DETEKSI JENIS DATA & PLATFORM (sesi #34)
# ═══════════════════════════════════════════════════════════════════════════════
# KENAPA: staf memilih jenis data SENDIRI (aturan yang tetap dipertahankan — AI
# tidak boleh memutuskan tabel tujuan). Tetapi pilihan manusia BISA SALAH, dan
# salah pilih jenis berarti berkas "pesanan" masuk sebagai "penjualan harian".
# Modul ini tidak mengambil keputusan; ia MENGUKUR kecocokan header berkas
# terhadap SETIAP jenis dan melaporkannya, supaya layar bisa berkata:
#
#   "Anda memilih Penjualan Harian, tetapi 39 dari 50 kolom berkas ini cocok
#    dengan Pesanan Marketplace (dan hanya 3 kolom cocok dengan pilihan Anda)."
#
# Platform juga tidak ditebak dari nama berkas: ia dibaca dari SIDIK HEADER
# (kolom khas Shopee vs TikTok) dan dibandingkan dengan platform toko yang
# dipilih staf — inilah yang diminta pemilik: "platform apa seharusnya sudah
# terdeteksi oleh system ketika input akun tokonya".

# Sidik header per platform: header yang HANYA muncul di ekspor platform itu.
PLATFORM_FINGERPRINTS = {
    "shopee": (
        "no pesanan", "status pesanan", "sku induk", "nomor referensi sku",
        "no pengembalian", "username pembeli", "voucher ditanggung shopee",
        "diskon dari shopee", "waktu pesanan dibuat", "opsi pengiriman",
        "potongan koin shopee", "cashback koin", "no resi",
        "jumlah produk dikembalikan", "solusi pengembalian barang dana",
    ),
    "tiktok": (
        "order id", "order substatus", "seller sku", "sku id",
        "cancelation return type", "purchase channel", "warehouse name",
        "creator handle", "return order id", "buyer username",
        "nama kampanye", "id campaign", "akun tiktok", "pesanan sku",
        "pendapatan kotor", "jenis materi iklan",
    ),
    "tokopedia": ("tokopedia invoice number", "nomor invoice", "kode pesanan"),
}


def detect_platform(headers: List[str]) -> dict:
    """Platform dari SIDIK HEADER berkas (bukan dari nama berkas)."""
    norm = {_norm_header(h) for h in headers if h}
    hits = {}
    for plat, marks in PLATFORM_FINGERPRINTS.items():
        matched = [m for m in marks if _norm_header(m) in norm]
        if matched:
            hits[plat] = matched
    if not hits:
        return {"platform": "", "confidence": 0.0, "evidence": [], "candidates": {}}
    best = max(hits.items(), key=lambda kv: len(kv[1]))
    total = sum(len(v) for v in hits.values())
    return {
        "platform": best[0],
        "confidence": round(len(best[1]) / total, 3) if total else 0.0,
        "evidence": best[1][:6],
        "candidates": {k: len(v) for k, v in hits.items()},
    }


def score_headers(headers: List[str], st: SourceType) -> dict:
    """Seberapa cocok header berkas dengan satu jenis data. 0..1, dapat diperiksa."""
    mapping = auto_map(headers, st)
    mapped = [m for m in mapping if m.get("field")]
    mapped_names = {m["field"] for m in mapped}
    req = [f for f in st.input_fields if f.required]
    req_hit = [f for f in req if f.name in mapped_names]
    req_cover = (len(req_hit) / len(req)) if req else 1.0
    col_cover = (len(mapped) / len(headers)) if headers else 0.0
    return {
        "source_type": st.key, "label": st.label, "group": st.group,
        "mapped_columns": len(mapped), "total_columns": len(headers),
        "required_hit": len(req_hit), "required_total": len(req),
        "required_missing": [f.label for f in req if f.name not in mapped_names],
        "required_cover": round(req_cover, 3),
        "column_cover": round(col_cover, 3),
        # Kolom WAJIB menimbang paling berat: jenis yang kolom wajibnya tidak
        # lengkap TIDAK PERNAH boleh menang hanya karena banyak kolom nyasar.
        "score": round(req_cover * 0.7 + col_cover * 0.3, 4),
    }


def detect_source_type(raw: bytes, filename: str, catalog: List[SourceType],
                       *, top: int = 5) -> dict:
    """Urutkan SEMUA jenis data menurut kecocokan header berkas.

    Berkas dibaca sekali tanpa prenorm, lalu SEKALI LAGI untuk tiap penormal
    yang dipakai jenis-jenis ber-`prenorm` (ekspor Seller Center yang baris
    pertamanya bukan header). Tanpa itu, jenis ber-prenorm selalu tampak 0 kolom.
    """
    parses: Dict[str, Tuple[List[str], List[dict]]] = {}
    too_many = False
    try:
        parses[""] = parse_table(raw, filename, None)
    except TooManyRows:
        # 2026-11-09 (G4) — berkas besar (ekspor GMV Max 100.000 baris) tetap BISA dikenali:
        # header dibaca saja; penormal jenisnya yang membuang baris kosong biaya.
        too_many = True
        parses[""] = (baca_header(raw, filename), [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"berkas tidak bisa dibaca: {e}", "results": []}
    for st in catalog:
        key = getattr(st, "prenorm", "") or ""
        if key and key not in parses:
            try:
                parses[key] = parse_table(raw, filename, st, deteksi=True)
            except Exception:  # noqa: BLE001
                parses[key] = ([], [])

    results = []
    for st in catalog:
        headers, rows = parses.get(getattr(st, "prenorm", "") or "", ([], []))
        if not headers:
            continue
        r = score_headers(headers, st)
        r["prenorm"] = getattr(st, "prenorm", "") or ""
        r["rows_readable"] = len(rows)
        results.append(r)
    results.sort(key=lambda r: (-r["score"], -r["mapped_columns"]))
    base_headers, base_rows = parses.get("", ([], []))
    plat = detect_platform(base_headers)
    if not plat.get("platform"):
        # Jalan mundur yang JUJUR: ekspor yang baris pertamanya judul ("Semua
        # Laporan Iklan CPC - Shopee Indonesia") tidak punya sidik kolom sama
        # sekali. Nama platform di JUDUL/nama berkas dipakai, dan buktinya
        # disebut supaya staf bisa membantah.
        blob = " ".join([str(h) for h in base_headers[:5]] + [filename or ""]).lower()
        for plat_name in ("shopee", "tiktok", "tokopedia", "lazada"):
            if plat_name in blob:
                plat = {"platform": plat_name, "confidence": 0.5,
                        "evidence": [f"kata '{plat_name}' di judul/nama berkas"],
                        "candidates": {plat_name: 1}}
                break
        else:
            if results and results[0]["source_type"].startswith("shopee_"):
                plat = {"platform": "shopee", "confidence": 0.5,
                        "evidence": ["jenis data ini hanya ada di Seller Center Shopee"],
                        "candidates": {"shopee": 1}}
    return {
        "ok": True,
        "headers": base_headers,
        "row_count": len(base_rows),
        "too_many_rows": too_many,
        "platform": plat,
        "best": results[0] if results else None,
        "results": results[:top],
    }


def baca_header(raw: bytes, filename: str, scan: int = 25) -> List[str]:
    """Baris header pertama berkas (tanpa membaca seluruh isi) — untuk berkas besar."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            ws = wb.active
            try:
                ws.reset_dimensions()
            except Exception:  # noqa: BLE001
                pass
            for i, values in enumerate(ws.iter_rows(values_only=True)):
                if i >= scan:
                    break
                if values and any(v not in (None, "") for v in values):
                    return [str(v).strip() if v is not None else f"kolom_{j + 1}"
                            for j, v in enumerate(values)]
        finally:
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
        return []
    text = raw[:200_000].decode("utf-8-sig", errors="replace")
    for line in csv.reader(io.StringIO(text)):
        if any((c or "").strip() for c in line):
            return [c.strip() for c in line]
    return []
