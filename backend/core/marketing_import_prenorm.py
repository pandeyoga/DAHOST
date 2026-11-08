"""core.marketing_import_prenorm — **penormal berkas ekspor Seller Center**.

KENAPA BERKAS INI ADA (F7.2, 2026-08-13)
----------------------------------------
Mesin impor (`core/marketing_import_engine.parse_table`) menganggap baris pertama
berkas adalah header — asumsi yang benar untuk ekspor pesanan, tetapi **salah untuk
seluruh berkas KPI Shopee**. Diukur pada 5 berkas contoh yang diunggah owner
(13 Agu 2026):

| berkas | bentuk nyata | akibat bila dibaca apa adanya |
|---|---|---|
| `export-sc__1d_*.csv` (Live harian) | baris 0 = **judul grup kolom** (`Data Utama`, `Konversi`…), baris 1 = header sebenarnya | seluruh kolom bernama `Data Utama`/kosong ⇒ 0 kolom terpetakan |
| `overview-v2_*.csv` (Live ringkas) | idem + **blok section** `Kunjungan - Sumber Penonton - …` di bawah baris data | baris section ikut terbaca sebagai data ⇒ angka sampah |
| `video-overview-v3_*.csv` | idem, header duplikat (`Penonton` 2×, `Persentase Klik` 2×) | kolom saling menimpa ⇒ angka tertukar |
| `Data+Keseluruhan+Iklan+Shopee-*.csv` | **6 baris metadata** (Username, Nama Toko, ID Toko, Periode) lalu tabel | header terbaca `Semua Laporan Iklan CPC` ⇒ impor mustahil |
| `*.shopee-shop-stats.*.xlsx` | 12 sheet; ringkasan rentang + rincian per jam + kontribusi kanal | hanya sheet pertama terbaca, tanggal berbentuk rentang `13-08-2026-13-08-2026` |

Karena itu berkas ini **menormalkan dulu**: memotong metadata, memilih baris header
yang benar, membuang baris section, menggabungkan sheet, lalu mengeluarkan tabel
dengan **nama kolom kanonik** (sama dengan `Field.name` di
`core/marketing_import_schema.py`). Setelah itu mesin impor lama bekerja seperti
biasa: coerce tipe, validasi, dedupe, commit, rollback.

ATURAN YANG DIPEGANG
--------------------
1. **Tanpa AI, tanpa tebakan.** Semua pemetaan kolom tertulis di modul ini. Header
   yang tidak dikenal dibiarkan (tidak dipetakan) — tidak pernah "dipaksa cocok".
2. **Header duplikat: dipakai yang PERTAMA.** Pada ekspor Shopee, blok pertama
   (`Kunjungan - Performa`) adalah angka utuh, blok berikutnya adalah rincian
   sumber penonton/alur konversi. Mengambil yang terakhir berarti melaporkan
   sebagian sebagai keseluruhan.
3. **Rentang tanggal tidak pernah dijadikan satu tanggal.** Kalau ekspor mencakup
   >1 hari, angka harian diambil dari baris RINCIAN per hari; kalau rincian yang
   tersedia hanya per JAM (ekspor 1 hari), pengunjung/klik diambil dari baris
   RINGKASAN — menjumlah pengunjung per jam menghitung orang yang sama berulang.
4. **GMV KPI bukan omzet pesanan.** Berkas ini tidak pernah menulis ke
   `marketing_sales_data`; hasilnya masuk `marketing_platform_kpi_daily`
   (KPI platform) atau `marketing_ads_data` (biaya iklan).
"""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_ROWS = 20000


class PrenormBlocked(ValueError):
    """Berkas DIKENALI, tetapi isian wajib dari staf belum ada (mis. periode GMV Max).

    Bukan "bentuk berkas belum dikenal": `parse_table_lenient` TIDAK membaca ulang
    berkas apa adanya, dan pesannya diteruskan ke staf apa adanya (2026-11-09)."""


# ═══════════════════════════════════════════════════════════════════════════════
# Pembantu
# ═══════════════════════════════════════════════════════════════════════════════
def _norm(s: Any) -> str:
    """Normalkan nama kolom: huruf kecil, tanpa tanda baca, spasi tunggal."""
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").strip().lower()).strip()


def _cells(raw: bytes) -> List[List[str]]:
    """CSV apa pun → matriks teks (delimiter dideteksi, BOM dibuang)."""
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4000]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:  # noqa: BLE001 — berkas 1 kolom / campur; jatuh ke heuristik
        delim = ";" if sample.count(";") > sample.count(",") else ","
    out: List[List[str]] = []
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        out.append([("" if c is None else str(c).strip()) for c in row])
        if len(out) > MAX_ROWS + 50:          # +50 baris judul/metadata ekspor KPI
            # 2026-11-07 (audit §3.C #10) — tidak lagi dipotong diam-diam.
            from core.marketing_import_engine import TooManyRows
            raise TooManyRows()
    return out


def _blank(row: List[str]) -> bool:
    return all((c or "").strip() == "" for c in row)


_DUR_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([a-z:]+)", re.I)


def duration_seconds(raw: Any) -> Optional[float]:
    """Durasi gaya Shopee → detik.

    Bentuk nyata pada berkas contoh: ``"10j50m8d"`` (10 jam 50 menit 8 detik),
    ``"54d"``, ``"5d"``, dan ``"00:01:19"`` (hh:mm:ss). Tanpa pembaca ini,
    "durasi tonton" tersimpan sebagai teks dan tidak pernah bisa dijumlah.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-"):
        return None
    if ":" in s:
        parts = [p.strip() for p in s.split(":")]
        try:
            nums = [float(p.replace(",", ".")) for p in parts]
        except ValueError:
            return None
        while len(nums) < 3:
            nums.insert(0, 0.0)
        return nums[-3] * 3600 + nums[-2] * 60 + nums[-1]
    total = 0.0
    found = False
    for num, unit in _DUR_RE.findall(s):
        try:
            v = float(num.replace(",", "."))
        except ValueError:
            continue
        u = unit.lower()
        mult = {"j": 3600, "h": 3600, "jam": 3600,
                "m": 60, "menit": 60, "min": 60,
                "d": 1, "s": 1, "detik": 1, "sec": 1}.get(u)
        if mult is None:
            continue
        total += v * mult
        found = True
    return total if found else None


def _date_head(raw: Any) -> Optional[str]:
    """Ambil tanggal (YYYY-MM-DD) dari sel seperti ``13-08-2026``,
    ``13-08-2026 01:00``, ``13-08-2026-13-08-2026`` (rentang), atau ``13/08/2026``."""
    s = str(raw or "").strip()
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _date_range(raw: Any) -> Tuple[Optional[str], Optional[str]]:
    """``13-08-2026-13-08-2026`` / ``07/08/2026 - 13/08/2026`` → (mulai, selesai)."""
    s = str(raw or "").strip()
    hits = re.findall(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if not hits:
        iso = re.findall(r"(\d{4})-(\d{2})-(\d{2})", s)
        if iso:
            vals = [f"{a}-{b}-{c}" for a, b, c in iso]
            return vals[0], vals[-1]
        return None, None
    vals = [f"{int(y):04d}-{int(mo):02d}-{int(d):02d}" for d, mo, y in hits]
    return vals[0], vals[-1]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. KPI KONTEN SHOPEE (Live harian · Live ringkas · Video ringkas)
# ═══════════════════════════════════════════════════════════════════════════════
# Peta kolom DITULIS, bukan ditebak. Kunci = header apa adanya (dinormalkan),
# nilai = nama field kanonik di `marketing_import_schema`.
_CONTENT_MAP: Dict[str, str] = {
    "periode data": "date",
    "user id": "platform_user_id",
    "penjualan pesanan dibuat": "gmv_created",
    "penjualan pesanan siap dikirim": "gmv_ready",
    "pesanan pesanan dibuat": "orders_created",
    "pesanan pesanan siap dikirim": "orders_ready",
    "produk terjual pesanan dibuat": "products_sold",
    "pembeli pesanan dibuat": "buyers",
    "tambah ke keranjang": "add_to_cart",
    "persentase klik": "ctr",
    "suka": "likes",
    "share": "shares",
    "komentar": "comments",
    "pengikut baru dari livestream": "new_followers",
    "pengikut baru dari video": "new_followers",
    # ── Live ────────────────────────────────────────────────────────────────
    "jumlah livestream": "live_sessions",
    "jumlah durasi livestream": "live_duration_raw",
    "penonton": "viewers",
    "penonton aktif": "active_viewers",
    "dilihat": "views",
    "penonton tertinggi": "peak_viewers",
    "rata rata durasi ditonton": "avg_watch_raw",
    # ── Video ───────────────────────────────────────────────────────────────
    "durasi rata rata menonton jumlah video": "avg_watch_raw",
    "ditonton": "views",
    "penonton efektif menonton 3 detik": "effective_viewers",
    "video dengan produk": "videos_with_product",
    "tingkat video selesai ditonton": "completion_rate",
    # ── Voucher / promosi (dibawa apa adanya untuk jejak) ────────────────────
    "voucher toko diklaim": "voucher_shop_claimed",
    "voucher spesial live diklaim": "voucher_live_claimed",
    "koin diklaim": "coin_claimed",
}

_VIDEO_MARKERS = ("video dengan produk", "pengikut baru dari video",
                  "rasio video ditonton", "durasi rata rata menonton jumlah video",
                  "video berpendapatan pesanan dibuat")
_LIVE_MARKERS = ("jumlah livestream", "pengikut baru dari livestream",
                 "rasio live ditonton", "penonton tertinggi", "penonton aktif")


def _header_row_index(cells: List[List[str]], must_have: str,
                      also: str = "", limit: int = 12) -> int:
    """Cari baris header SEBENARNYA.

    Ekspor Shopee menaruh **judul grup kolom** di baris 0 (`Periode Data`, `Data
    Utama`, `Konversi`…) dan header sebenarnya di baris 1. Kalau kita berhenti di
    kecocokan pertama, seluruh kolom terbaca dari baris judul grup dan tidak ada
    satu pun kolom yang terpetakan. Karena itu baris header dipilih yang memuat
    **dua** penanda sekaligus (mis. `Periode Data` + `User Id`).
    """
    if also:
        for i, row in enumerate(cells[:limit]):
            hn = [_norm(c) for c in row]
            if must_have in hn and also in hn:
                return i
    for i, row in enumerate(cells[:limit]):
        if any(_norm(c) == must_have for c in row):
            return i
    return -1


def _detect_channel(headers_norm: List[str], filename: str) -> Tuple[str, str]:
    """→ (channel, source). Diputuskan dari HEADER, bukan dari nama berkas.

    Nama berkas boleh diubah staf (dan pasti diubah saat diunduh berulang), jadi
    ia bukan bukti apa pun. Yang membedakan kedua ekspor Live: ekspor RINGKAS
    (`overview`) membawa kolom `Jumlah Livestream` & `Jumlah Durasi Livestream`,
    sedangkan ekspor HARIAN (`export-sc`, banyak tanggal) tidak.
    """
    hset = set(headers_norm)
    if hset & set(_VIDEO_MARKERS):
        return "video", "shopee_video_overview"
    if hset & set(_LIVE_MARKERS):
        src = ("shopee_live_overview" if "jumlah livestream" in hset
               else "shopee_live_1d")
        return "live", src
    raise ValueError(
        "Berkas ini tidak dikenali sebagai KPI Live maupun Video Shopee "
        "(tidak ada kolom penanda seperti 'Jumlah Livestream', 'Penonton Aktif', "
        "atau 'Video dengan Produk'). Pastikan berkas diekspor dari Seller Center → "
        "Bisnis Saya → Live/Video, tanpa diubah kolomnya.")


def prenorm_shopee_content_kpi(raw: bytes, filename: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Ekspor Live/Video Shopee (CSV) → tabel KPI harian per kanal."""
    cells = _cells(raw)
    hidx = _header_row_index(cells, "periode data", also="user id")
    if hidx < 0:
        raise ValueError(
            "Kolom 'Periode Data' tidak ditemukan di 12 baris pertama. Berkas KPI "
            "Live/Video Shopee selalu memuatnya — sepertinya ini berkas jenis lain.")
    header = cells[hidx]
    hnorm = [_norm(c) for c in header]
    channel, source = _detect_channel(hnorm, filename)

    # header duplikat: dipakai yang PERTAMA (lihat aturan #2 di docstring)
    col_of: Dict[str, int] = {}
    for i, hn in enumerate(hnorm):
        canon = _CONTENT_MAP.get(hn)
        if canon and canon not in col_of:
            col_of[canon] = i

    rows: List[Dict[str, Any]] = []
    for row in cells[hidx + 1:]:
        if _blank(row):
            break                      # blok section di bawahnya bukan data harian
        d = _date_head(row[0] if row else "")
        if not d:
            break                      # baris judul section ("Kunjungan - Sumber …")
        rec: Dict[str, Any] = {"date": d, "channel": channel, "source": source}
        for canon, idx in col_of.items():
            if canon == "date":
                continue
            rec[canon] = row[idx] if idx < len(row) else ""
        # durasi teks → detik/menit (angka yang bisa dijumlah)
        secs = duration_seconds(rec.pop("avg_watch_raw", None))
        if secs is not None:
            rec["avg_watch_seconds"] = secs
        live_secs = duration_seconds(rec.pop("live_duration_raw", None))
        if live_secs is not None:
            rec["live_minutes"] = round(live_secs / 60.0, 2)
        rows.append(rec)

    if not rows:
        raise ValueError(
            "Tidak ada baris tanggal yang terbaca. Ekspor Live/Video Shopee harus "
            "memuat minimal satu baris 'Periode Data' berisi tanggal.")
    headers = sorted({k for r in rows for k in r})
    return headers, rows


# ═══════════════════════════════════════════════════════════════════════════════
# 2. STATISTIK TOKO SHOPEE (XLSX multi-sheet)
# ═══════════════════════════════════════════════════════════════════════════════
_BASIS_SHEETS = {
    "pesanan dibuat": "created",
    "pesanan siap dikirim": "ready",
    "pesanan dibayar": "paid",
}
_CHANNEL_SPLIT = {
    "penjualan dari halaman produk": "gmv_product_page",
    "penjualan dari live penjual": "gmv_live",
    "penjualan dari video penjual": "gmv_video",
    "penjualan dari affiliate": "gmv_affiliate",
    "penjualan dari iklan shopee": "gmv_ads",
}


def _sheet_matrix(ws) -> List[List[Any]]:
    out: List[List[Any]] = []
    for values in ws.iter_rows(values_only=True):
        out.append(list(values or []))
        if len(out) > 5000:
            break
    return out


def _rows_after(matrix: List[List[Any]], first_cell: str) -> Tuple[List[str], List[List[Any]]]:
    """Ambil (header, baris) dari blok yang dimulai baris ber-sel-pertama `first_cell`."""
    for i, row in enumerate(matrix):
        if row and _norm(row[0]) == first_cell:
            header = [_norm(c) for c in row]
            body: List[List[Any]] = []
            for r in matrix[i + 1:]:
                if not r or all(c in (None, "") for c in r):
                    break
                body.append(list(r))
            return header, body
    return [], []


def _blocks(matrix: List[List[Any]], first_cells: Tuple[str, ...]) -> List[Tuple[List[str], List[List[Any]]]]:
    """SEMUA blok (header, baris) yang sel pertama header-nya salah satu `first_cells`.

    2026-11-06 (Tahap 2) — ekspor Statistik Toko versi baru menulis DUA blok yang
    sama-sama diawali "Tanggal": ringkasan rentang lalu rincian per hari. Versi
    lama menulis rincian dengan header "Waktu". `_rows_after` hanya mengambil blok
    pertama, jadi rincian versi baru tidak pernah terbaca dan berkasnya ditolak.
    """
    out: List[Tuple[List[str], List[List[Any]]]] = []
    i, n = 0, len(matrix)
    while i < n:
        row = matrix[i]
        if row and _norm(row[0]) in first_cells:
            header = [_norm(c) for c in row]
            body: List[List[Any]] = []
            j = i + 1
            while j < n:
                r = matrix[j]
                if not r or all(c in (None, "") for c in r):
                    break
                body.append(list(r))
                j += 1
            out.append((header, body))
            i = j
            continue
        i += 1
    return out


def _is_range_cell(raw: Any) -> bool:
    """Sel berisi DUA tanggal (rentang ringkasan), mis. ``01-10-2026-31-10-2026``."""
    s = str(raw or "")
    return len(re.findall(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}", s)) >= 2 or \
        len(re.findall(r"\d{4}-\d{2}-\d{2}", s)) >= 2


def _summary_and_detail(matrix: List[List[Any]]):
    """→ ((header, baris) ringkasan, (header, baris) rincian) — keduanya boleh kosong.

    Ringkasan = blok yang baris pertamanya RENTANG tanggal; rincian = blok lain
    yang barisnya bertanggal tunggal (per hari) atau berjam (per jam).
    """
    summary: Tuple[List[str], List[List[Any]]] = ([], [])
    detail: Tuple[List[str], List[List[Any]]] = ([], [])
    for head, body in _blocks(matrix, ("tanggal", "waktu")):
        if not body:
            continue
        first = body[0][0] if body[0] else ""
        if not summary[1] and _is_range_cell(first):
            summary = (head, body)
        elif not detail[1] and _date_head(first) and not _is_range_cell(first):
            detail = (head, body)
    if not detail[1]:
        # perilaku lama dipertahankan: blok "Waktu" dipakai apa pun isi sel pertamanya
        detail = _rows_after(matrix, "waktu")
    return summary, detail


def prenorm_shopee_shop_stats(raw: bytes, filename: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """XLSX `*.shopee-shop-stats.*` → satu baris KPI per TANGGAL (kanal `shop`)."""
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover — dependency inti
        raise ValueError("Server belum punya openpyxl untuk membaca Excel") from e
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    per_date: Dict[str, Dict[str, Any]] = {}
    single_date: Optional[str] = None
    notes: List[str] = []

    def _rec(d: str) -> Dict[str, Any]:
        return per_date.setdefault(d, {"date": d, "channel": "shop",
                                       "source": "shopee_shop_stats"})

    for ws in wb.worksheets:
        title_n = _norm(ws.title)
        basis = _BASIS_SHEETS.get(title_n)
        if not basis:
            continue
        matrix = _sheet_matrix(ws)
        # ── ringkasan (rentang) + rincian (per jam untuk ekspor 1 hari, per hari
        #    untuk rentang). Header rincian bisa "Waktu" (versi lama) atau
        #    "Tanggal" (versi 2026-11) — dibedakan dari ISI baris, bukan judulnya.
        (sum_head, sum_body), (det_head, det_body) = _summary_and_detail(matrix)
        rng_from = rng_to = None
        summary: Dict[str, Any] = {}
        if sum_body:
            rng_from, rng_to = _date_range(sum_body[0][0] if sum_body[0] else "")
            summary = {sum_head[i]: sum_body[0][i] if i < len(sum_body[0]) else None
                       for i in range(len(sum_head))}

        if rng_from and rng_to and rng_from == rng_to:
            # Ekspor 1 hari: pengunjung & klik dari RINGKASAN (menjumlah per jam
            # akan menghitung pengunjung yang sama berkali-kali).
            single_date = rng_from
            rec = _rec(rng_from)
            rec[f"gmv_{basis}"] = summary.get("total penjualan idr")
            rec[f"orders_{basis}"] = summary.get("total pesanan")
            rec.setdefault("visitors", summary.get("total pengunjung"))
            rec.setdefault("product_clicks", summary.get("produk diklik"))
            if basis == "created":
                rec["conversion_rate"] = summary.get("tingkat konversi pesanan")
        elif det_body:
            for r in det_body:
                d = _date_head(r[0] if r else "")
                if not d:
                    continue
                rec = _rec(d)
                gm = det_head.index("total penjualan idr") if "total penjualan idr" in det_head else -1
                od = det_head.index("total pesanan") if "total pesanan" in det_head else -1
                vs = det_head.index("total pengunjung") if "total pengunjung" in det_head else -1
                pc = det_head.index("produk diklik") if "produk diklik" in det_head else -1
                if gm >= 0:
                    rec[f"gmv_{basis}"] = r[gm] if gm < len(r) else None
                if od >= 0:
                    rec[f"orders_{basis}"] = r[od] if od < len(r) else None
                if basis == "created":
                    if vs >= 0:
                        rec["visitors"] = r[vs] if vs < len(r) else None
                    if pc >= 0:
                        rec["product_clicks"] = r[pc] if pc < len(r) else None
                    # rincian PER HARI (bukan per jam) sah membawa konversi harian
                    cv = (det_head.index("tingkat konversi pesanan")
                          if "tingkat konversi pesanan" in det_head else -1)
                    if cv >= 0 and _date_head(r[0]) and ":" not in str(r[0]):
                        rec["conversion_rate"] = r[cv] if cv < len(r) else None
        else:
            notes.append(f"sheet '{ws.title}' tidak punya blok tanggal/waktu")

    # ── kontribusi kanal (hanya sah bila ekspornya 1 hari) ────────────────────
    for ws in wb.worksheets:
        head, body = _rows_after(_sheet_matrix(ws), "tanggal")
        if not body or not head:
            continue
        if not any(h in _CHANNEL_SPLIT for h in head):
            continue
        row0 = body[0]
        status = str(row0[1] if len(row0) > 1 else "").strip().lower()
        if "dibuat" not in status:          # pakai basis 'Pesanan Dibuat' saja
            continue
        f, t = _date_range(row0[0] if row0 else "")
        if not f or f != t:
            notes.append("kontribusi kanal dilewati: ekspor mencakup lebih dari 1 hari")
            break
        rec = _rec(f)
        for i, h in enumerate(head):
            canon = _CHANNEL_SPLIT.get(h)
            if canon and i < len(row0):
                rec[canon] = row0[i]
        break

    try:
        wb.close()
    except Exception as e:  # noqa: BLE001
        logger.debug("gagal menutup workbook statistik toko: %s", e)

    if not per_date:
        raise ValueError(
            "Tidak ada sheet 'Pesanan Dibuat' / 'Pesanan Siap Dikirim' / "
            "'Pesanan Dibayar' yang bisa dibaca. Unggah berkas asli ekspor "
            "Seller Center → Data Bisnis → Statistik Toko (.xlsx), tanpa diedit.")
    rows = [per_date[k] for k in sorted(per_date)]
    if notes:
        logger.info("[prenorm shop_stats] %s (tanggal tunggal=%s)",
                    "; ".join(notes), single_date)
    headers = sorted({k for r in rows for k in r})
    return headers, rows


# ═══════════════════════════════════════════════════════════════════════════════
# 3. LAPORAN IKLAN CPC SHOPEE
# ═══════════════════════════════════════════════════════════════════════════════
_ADS_MAP: Dict[str, str] = {
    "nama iklan": "campaign_name",
    "status": "status",
    "jenis iklan": "ad_type",
    "kode produk": "product_code",
    "mode bidding": "bidding_mode",
    "penempatan iklan": "placement",
    "tanggal mulai": "campaign_started",
    "dilihat": "impressions",
    "jumlah klik": "clicks",
    "persentase klik": "ctr_platform",
    "tambah ke keranjang": "add_to_cart",
    "konversi": "conversions",
    "konversi langsung": "direct_conversions",
    "produk terjual": "products_sold",
    "terjual langsung": "direct_products_sold",
    "omzet penjualan": "revenue",
    "penjualan langsung gmv langsung": "direct_revenue",
    "biaya": "spend",
    "efektifitas iklan": "roas_platform",
    "efektivitas langsung": "direct_roas_platform",
    "persentase biaya iklan terhadap penjualan dari iklan acos": "acos",
    # ── 2026-11-09 (riset G24) — ejaan lain di ekspor nyata (repo pihak ketiga):
    # "Efektivitas Iklan" (tanpa salah eja), "Add to Cart" (UI campuran), dan sejak
    # 16 Jan 2026 "GMV" diganti "Penjualan".
    "efektivitas iklan": "roas_platform",
    "efektifitas langsung": "direct_roas_platform",
    "add to cart": "add_to_cart",
    "penjualan": "revenue",
    "penjualan langsung": "direct_revenue",
}
_ADS_META = {
    "username": "shop_username",
    "nama toko": "shop_name",
    "id toko": "platform_shop_id",
    "periode": "_period",
}


def prenorm_shopee_ads_cpc(raw: bytes, filename: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """CSV `Data Keseluruhan Iklan Shopee` → satu baris per iklan + periode."""
    cells = _cells(raw)
    meta: Dict[str, Any] = {}
    hidx = -1
    for i, row in enumerate(cells[:30]):
        if not row:
            continue
        key = _norm(row[0])
        if key in _ADS_META and len(row) > 1:
            meta[_ADS_META[key]] = row[1].strip()
        if any(_norm(c) == "nama iklan" for c in row):
            hidx = i
            break
    if hidx < 0:
        raise ValueError(
            "Baris header 'Nama Iklan' tidak ditemukan. Unggah berkas asli "
            "Seller Center → Iklan Saya → Laporan Iklan (Semua Laporan Iklan CPC), "
            "tanpa mengubah baris judulnya.")
    p_from, p_to = _date_range(meta.pop("_period", ""))
    if not p_from or not p_to:
        raise ValueError(
            "Periode laporan tidak terbaca dari baris 'Periode' di kepala berkas. "
            "Tanpa periode, biaya iklan tidak bisa ditempatkan pada bulan yang benar.")
    if p_from[:7] != p_to[:7]:
        raise ValueError(
            f"Laporan ini mencakup dua bulan ({p_from} s/d {p_to}). Biaya iklan "
            "dipakai untuk realisasi anggaran BULANAN, jadi ekspor harus dibatasi "
            "dalam satu bulan — ekspor ulang per bulan lalu unggah masing-masing.")

    header = [_norm(c) for c in cells[hidx]]
    col_of: Dict[str, int] = {}
    for i, hn in enumerate(header):
        canon = _ADS_MAP.get(hn)
        if canon and canon not in col_of:
            col_of[canon] = i

    rows: List[Dict[str, Any]] = []
    for row in cells[hidx + 1:]:
        if _blank(row):
            continue
        name_i = col_of.get("campaign_name")
        if name_i is None or name_i >= len(row) or not row[name_i].strip():
            continue
        rec: Dict[str, Any] = {"date": p_from, "period_start": p_from, "period_end": p_to}
        rec.update(meta)
        for canon, idx in col_of.items():
            v = row[idx] if idx < len(row) else ""
            rec[canon] = "" if str(v).strip() == "-" else v
        rows.append(rec)

    if not rows:
        raise ValueError("Tidak ada baris iklan di bawah header — berkas kosong?")
    headers = sorted({k for r in rows for k in r})
    return headers, rows


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LAPORAN IKLAN TIKTOK GMV MAX (2026-11-09, riset G1/G3/G4)
# ═══════════════════════════════════════════════════════════════════════════════
# Bentuk nyata (berkas contoh owner): sheet `Data`, 26 kolom berbahasa Indonesia,
# 100.000 baris TEPAT dengan hanya 67 baris berbiaya > 0, uang berupa TEKS dengan titik
# sebagai DESIMAL ("40797.000"), rasio pecahan 0–1, "-"/"N/A" untuk materi kartu produk,
# dan TIDAK ADA kolom tanggal belanja ("Waktu posting" = tanggal unggah video).
_GMV_MAP: Dict[str, str] = {
    # bahasa Indonesia (berkas asli)
    "nama kampanye": "campaign_name", "id campaign": "campaign_id", "id kampanye": "campaign_id",
    "id produk": "product_id", "jenis materi iklan": "ad_type", "judul video": "video_title",
    "id video": "video_id", "akun tiktok": "creator_handle", "waktu posting": "video_posted_at",
    "status": "status_raw", "status sekunder penjelajahan": "notes",
    "jenis otorisasi": "authorization_type", "biaya": "spend",
    "pesanan sku": "conversions", "pesanan": "conversions",
    "biaya per pesanan": "cost_per_order", "pendapatan kotor": "revenue",
    "impresi iklan produk": "impressions", "jumlah klik iklan produk": "clicks",
    "tingkat klik iklan produk": "ctr_platform", "rasio klik iklan produk": "ctr_platform",
    "rasio konversi iklan": "conversion_rate", "tingkat konversi iklan": "conversion_rate",
    "mata uang": "currency",
    # bahasa Inggris (Seller Center ber-UI Inggris; nama dari Pusat Bantuan TikTok Ads)
    "campaign name": "campaign_name", "campaign id": "campaign_id", "product id": "product_id",
    "creative type": "ad_type", "video title": "video_title", "video id": "video_id",
    "tiktok account": "creator_handle", "post time": "video_posted_at", "cost": "spend",
    "orders sku": "conversions", "sku orders": "conversions", "cost per order": "cost_per_order",
    "gross revenue": "revenue", "product ad impressions": "impressions",
    "product ad clicks": "clicks", "product ad click rate": "ctr_platform",
    "ad conversion rate": "conversion_rate", "currency": "currency",
}
_GMV_UANG = ("spend", "cost_per_order", "revenue")
_GMV_JUMLAH = ("conversions", "impressions", "clicks")
_GMV_RASIO = ("ctr_platform", "conversion_rate")
GMV_BATAS_EKSPOR = 100_000          # bilangan bulat yang mencurigakan: kemungkinan batas ekspor
_KOSONG = {"", "-", "--", "n/a", "na", "none", "null"}

# Periode di nama berkas. Penanda baku `periode_YYYY-MM-DD_YYYY-MM-DD` ditulis oleh layar
# "Impor banyak berkas" dari isian staf; pola lain = nama ekspor yang lazim.
_PERIODE_NAMA = (
    re.compile(r"periode[_\s-]*(\d{4}-\d{2}-\d{2})[_\s]*(?:s\.?d\.?|sd|-|_|sampai)?[_\s]*(\d{4}-\d{2}-\d{2})",
               re.IGNORECASE),
    re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})\s*(?:_|~|–|-|to|s\.?d\.?|sampai)\s*(\d{4}-\d{2}-\d{2})(?!\d)",
               re.IGNORECASE),
    re.compile(r"(?<!\d)(20\d{6})\s*[_~–-]\s*(20\d{6})(?!\d)"),
)


def periode_dari_nama(filename: str) -> Tuple[Optional[str], Optional[str]]:
    """(mulai, selesai) ISO dari nama berkas, atau (None, None). Tanggal tidak sah → None."""
    from datetime import date as _date
    name = str(filename or "")
    for rx in _PERIODE_NAMA:
        m = rx.search(name)
        if not m:
            continue
        out = []
        for g in m.groups():
            s = g.replace("-", "")
            try:
                d = _date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            except ValueError:
                out = []
                break
            out.append(d.isoformat())
        if len(out) == 2 and out[0] <= out[1]:
            return out[0], out[1]
    return None, None


def penanda_periode(mulai: str, selesai: str, filename: str) -> str:
    """Nama berkas baru yang MEMBAWA periode isian staf (dibaca ulang saat commit)."""
    base = re.sub(r"periode_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}__", "", str(filename or "berkas.xlsx"))
    return f"periode_{mulai}_{selesai}__{base}"


def _gmv_matrix(raw: bytes, filename: str):
    """Iterator baris (list nilai) dari xlsx (sheet `Data` bila ada) atau csv."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            ws = wb["Data"] if "Data" in wb.sheetnames else wb.active
            try:
                ws.reset_dimensions()
            except Exception:  # noqa: BLE001
                pass
            for values in ws.iter_rows(values_only=True):
                yield list(values or [])
        finally:
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
        return
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4000]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:  # noqa: BLE001
        delim = ";" if sample.count(";") > sample.count(",") else ","
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        yield list(row)


def _nol(v: Any) -> bool:
    """True bila sel biaya kosong/nol APA PUN gaya angkanya ("0", "0.000", "0,00", "-")."""
    if v is None:
        return True
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) == 0.0
    s = str(v).strip().lower()
    if s in _KOSONG:
        return True
    return bool(re.fullmatch(r"[0.,\s]+", s)) and not re.search(r"[1-9]", s)


GMV_SAMPEL_DETEKSI = 3000            # deteksi jenis cukup membaca awal berkas


def prenorm_tiktok_gmv_max(raw: bytes, filename: str, deteksi: bool = False, lengkap: bool = False
                           ) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Ekspor GMV Max → satu baris per (kampanye, produk, materi) BERBIAYA untuk satu periode.

    ``deteksi=True``: periode boleh kosong; tanpa ``lengkap`` hanya awal berkas yang dibaca
    (cukup untuk mengenali jenisnya)."""
    from core.marketing_import_engine import gaya_angka_kolom, parse_number, KOLOM_CATATAN, TooManyRows
    rows_iter = _gmv_matrix(raw, filename)
    header: List[str] = []
    col_of: Dict[str, int] = {}
    for i, row in enumerate(rows_iter):
        hn = [_norm(c) for c in row]
        if "biaya" in hn or "cost" in hn:
            if ("nama kampanye" in hn or "campaign name" in hn):
                header = [str(c or "").strip() for c in row]
                for j, h in enumerate(hn):
                    canon = _GMV_MAP.get(h)
                    if canon and canon not in col_of:
                        col_of[canon] = j
                break
        if i >= 25:
            break
    if not header:
        raise ValueError(
            "Kolom 'Nama kampanye' dan 'Biaya' tidak ditemukan di 25 baris pertama. Unggah berkas "
            "asli ekspor GMV Max dari TikTok Seller Center (Iklan → GMV Max → Ekspor).")

    total = 0
    kept: List[List[Any]] = []
    i_spend = col_of.get("spend")
    for row in rows_iter:
        if not row or all(c in (None, "") for c in row):
            continue
        total += 1
        if deteksi and not lengkap and total > GMV_SAMPEL_DETEKSI:
            break
        v = row[i_spend] if i_spend is not None and i_spend < len(row) else None
        if _nol(v):
            continue                                   # baris tanpa biaya dibuang (G4)
        kept.append(row)
        if len(kept) > MAX_ROWS:
            raise TooManyRows(filename or "")

    # G1 — gaya angka per kolom dari baris yang DIPAKAI; ekspor GMV Max memakai titik
    # desimal, jadi bila kolom ambigu (semua "ddd.ddd") gaya itu yang dipakai.
    gaya: Dict[str, str] = {}
    for canon in _GMV_UANG + _GMV_JUMLAH + _GMV_RASIO:
        j = col_of.get(canon)
        if j is None:
            continue
        g = gaya_angka_kolom([r[j] if j < len(r) else None for r in kept])
        gaya[canon] = g or "titik_desimal"

    p_from, p_to = periode_dari_nama(filename)
    catatan: List[str] = []
    if not (p_from and p_to):
        if not deteksi:
            raise PrenormBlocked(
                "Periode laporan GMV Max wajib diisi. Berkas ekspor GMV Max tidak memuat tanggal "
                "belanja — angkanya total untuk rentang yang Anda pilih saat mengekspor. Isi "
                "periodenya di layar unggah (Impor banyak berkas), atau tulis di nama berkas, "
                "mis. 'gmvmax_2026-08-01_2026-08-31.xlsx'.")
        p_from = p_to = ""
    elif p_from[:7] != p_to[:7] and not deteksi:
        raise PrenormBlocked(
            f"Periode {p_from} s/d {p_to} menyeberang bulan. Biaya iklan dipakai untuk realisasi "
            "anggaran BULANAN — ekspor ulang GMV Max per bulan, lalu unggah masing-masing.")
    if total == GMV_BATAS_EKSPOR:
        catatan.append(
            f"Berkas berisi tepat {GMV_BATAS_EKSPOR:,} baris — kemungkinan ekspor TikTok "
            "terpotong di batas maksimum. Ekspor ulang per kampanye atau per rentang yang lebih "
            "pendek, lalu bandingkan total biayanya.".replace(",", "."))

    def _num(canon, row):
        j = col_of.get(canon)
        if j is None or j >= len(row):
            return None
        v = row[j]
        if v is None or (isinstance(v, str) and v.strip().lower() in _KOSONG):
            return None
        n, err = parse_number(v, gaya.get(canon, ""))
        return None if err else n

    def _teks(canon, row):
        j = col_of.get(canon)
        if j is None or j >= len(row) or row[j] is None:
            return ""
        s = str(row[j]).strip()
        return "" if s.lower() in ("n/a", "na") else s

    agg: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    dobel = 0
    for row in kept:
        vid = _teks("video_id", row) or "-"
        key = (_teks("campaign_id", row), _teks("product_id", row), vid)
        rec = agg.get(key)
        if rec is None:
            rec = agg[key] = {
                "date": p_from, "period_start": p_from, "period_end": p_to,
                "campaign_name": _teks("campaign_name", row), "campaign_id": key[0],
                "product_id": key[1], "video_id": vid,
                "ad_type": _teks("ad_type", row), "video_title": _teks("video_title", row),
                "creator_handle": _teks("creator_handle", row),
                "video_posted_at": _teks("video_posted_at", row),
                "authorization_type": _teks("authorization_type", row),
                "status_raw": _teks("status_raw", row), "notes": _teks("notes", row),
                "currency": _teks("currency", row) or "IDR",
            }
            for c in _GMV_UANG + _GMV_JUMLAH:
                rec[c] = 0.0
            for c in _GMV_RASIO:
                n = _num(c, row)
                if n is not None:
                    rec[c] = n
        else:
            dobel += 1
        for c in ("spend", "revenue") + _GMV_JUMLAH:
            n = _num(c, row)
            if n is not None:
                rec[c] = float(rec.get(c) or 0) + n
    if dobel:
        catatan.append(f"{dobel} baris berkunci sama (kampanye, produk, materi) dijumlahkan "
                       "menjadi satu baris.")
    rows: List[Dict[str, Any]] = []
    for rec in agg.values():
        conv = float(rec.get("conversions") or 0)
        rec["cost_per_order"] = round(float(rec["spend"]) / conv, 3) if conv else ""
        for c in ("spend", "revenue"):
            rec[c] = round(float(rec[c]), 3)
        for c in _GMV_JUMLAH:
            rec[c] = int(round(float(rec[c] or 0)))
        if catatan:
            rec[KOLOM_CATATAN] = " · ".join(catatan)
        rows.append(rec)
    if not rows and not deteksi:
        raise ValueError(
            f"Tidak ada baris berbiaya di berkas ini ({total} baris, semuanya biaya 0). Pastikan "
            "rentang ekspor GMV Max mencakup hari kampanye berjalan.")
    headers = sorted({k for r in rows for k in r if k != KOLOM_CATATAN}) or sorted(
        set(col_of) | {"date", "period_start", "period_end"})
    return headers, rows


def ringkas_gmv_max(raw: bytes, filename: str) -> Dict[str, Any]:
    """Ringkasan berkas GMV Max untuk layar paket impor: baris, berbiaya, total biaya."""
    try:
        headers, rows = prenorm_tiktok_gmv_max(raw, filename, deteksi=True, lengkap=True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "baris_berbiaya": len(rows),
            "total_biaya": round(sum(float(r.get("spend") or 0) for r in rows), 2),
            "catatan": (rows[0].get("Catatan sistem") if rows else "") or ""}


# ═══════════════════════════════════════════════════════════════════════════════
# Titik masuk
# ═══════════════════════════════════════════════════════════════════════════════
PRENORMALIZERS = {
    "shopee_content_kpi": prenorm_shopee_content_kpi,
    "shopee_shop_stats": prenorm_shopee_shop_stats,
    "shopee_ads_cpc": prenorm_shopee_ads_cpc,
    "tiktok_gmv_max": prenorm_tiktok_gmv_max,
}
# Penormal yang menerima `deteksi=True` (butuh isian staf yang belum ada saat deteksi).
_DENGAN_DETEKSI = {"tiktok_gmv_max"}


def prenormalize(raw: bytes, filename: str, key: str, *,
                 deteksi: bool = False) -> Tuple[List[str], List[Dict[str, Any]]]:
    fn = PRENORMALIZERS.get(key)
    if fn is None:
        raise ValueError(f"Penormal berkas '{key}' tidak dikenali")
    if key in _DENGAN_DETEKSI:
        return fn(raw, filename, deteksi=deteksi)
    return fn(raw, filename)
