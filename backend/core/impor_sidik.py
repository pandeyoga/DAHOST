"""core.impor_sidik — **sidik jenis laporan Seller Center + profil nilai per kolom** (lapis deterministik).

KENAPA (9 Nov 2026, agen MKT-AI — riset_laporan_marketplace §7.1–7.3)
--------------------------------------------------------------------
Deteksi jenis lama (`marketing_import_engine.detect_source_type`) menilai berkas hanya dari
berapa kolom yang cocok dengan kamus SATU jenis impor. Itu tidak cukup untuk "unggah banyak
berkas sekaligus": berkas penghasilan dan berkas pesanan sama-sama punya "No. Pesanan", laporan
Saldo Shopee punya header di baris ke-18, laporan GMV Max 100.000 baris, dan ekspor TikTok
menaruh KALIMAT DESKRIPSI kolom di baris ke-2. Modul ini mengenali jenis laporan dari TANDA
PENGENAL yang ditulis (bukan ditebak):

* **wajib**   — header yang SEMUANYA harus ada (atau salah satu dari kelompok alternatif);
* **penguat** — header khas yang menaikkan keyakinan;
* **penolak** — header yang membuktikan berkas BUKAN jenis ini;
* **bentuk**  — nama sheet / baris header / metadata (mis. "Periode" laporan iklan CPC).

Hasilnya: jenis laporan + platform + versi + jalur sistem (jenis impor, Pencairan, Penarikan,
atau "belum ada pintu") beserta BUKTInya, supaya staf bisa membantah. Nama berkas hanya bukti
lemah dan tidak pernah memutuskan sendiri.

Modul ini juga membuat **profil nilai** tiap kolom (tipe, gaya angka, persen bertanda, "Rp",
negatif/kurung, pola tanggal & urutan hari-bulan, durasi, satuan berat, ID panjang, kolom
konstan, uang per pesanan vs per baris) — bahan bagi AI pemeta yang TIDAK pernah menerima
nilai mentah data pembeli (lihat `core.impor_ai_pemeta`).

Tanpa database, tanpa AI.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.marketing_import_engine import (
    _norm_header, gaya_angka_kolom, parse_date, parse_number, GAYA_OTOMATIS,
)

SCAN_BARIS = 25          # baris header Saldo Shopee = baris 18 → dicari sampai 25
SAMPEL_BARIS = 400       # baris data yang dibaca untuk profil (cukup untuk pola; berkas besar tidak dibaca penuh)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. TANDA PENGENAL JENIS LAPORAN (riset §7.2)
# ═══════════════════════════════════════════════════════════════════════════════
# Jalur sistem untuk setiap jenis laporan
JALUR_IMPOR = "impor"                # lewat mesin impor marketing (`source_type`)
JALUR_PENCAIRAN = "pencairan"        # laporan penghasilan → draf form Pencairan (Keuangan)
JALUR_PENARIKAN = "penarikan"        # laporan saldo/penarikan → draf Penarikan (Keuangan)
JALUR_BELUM = "belum_ada_pintu"      # jenis dikenal, sistem belum punya pintu impornya

# Wajib: daftar KELOMPOK; satu kelompok = tuple alternatif (salah satu cukup).
SIDIK: Tuple[dict, ...] = (
    {"jenis": "pesanan_shopee", "label": "Pesanan Shopee", "platform": "shopee",
     "jalur": JALUR_IMPOR, "source_type": "marketplace_orders",
     "wajib": (("no pesanan",), ("waktu pesanan dibuat",), ("subtotal pesanan",)),
     "penguat": ("harga setelah diskon", "diskon dari shopee", "voucher ditanggung shopee", "sku induk",
                 "nomor referensi sku", "status pesanan", "opsi pengiriman"),
     "penolak": ("no pengembalian", "total penghasilan"), "sheet": ("orders",)},
    {"jenis": "pesanan_tiktok", "label": "Pesanan TikTok Shop", "platform": "tiktok",
     "jalur": JALUR_IMPOR, "source_type": "marketplace_orders",
     "wajib": (("order id",), ("sku subtotal after discount",), ("order amount",)),
     "penguat": ("order substatus", "purchase channel", "warehouse name", "creator handle",
                 "sku platform discount", "buyer service fee"),
     "penolak": ("return order id", "total settlement amount"), "sheet": ("ordersku list", "orderskulist")},
    {"jenis": "penghasilan_shopee", "label": "Penghasilan Shopee (dana dilepas)", "platform": "shopee",
     "jalur": JALUR_PENCAIRAN, "source_type": "",
     "wajib": (("no pesanan", "order id"), ("total penghasilan",), ("tanggal dana dilepaskan", "payout completed date")),
     "penguat": ("biaya administrasi", "biaya layanan", "lihat berdasarkan", "view by", "harga asli produk",
                 "harga produk", "biaya komisi ams"),
     "penolak": ("subtotal pesanan",), "sheet": ("penghasilan", "income")},
    {"jenis": "penghasilan_tiktok", "label": "Penghasilan TikTok Shop", "platform": "tiktok",
     "jalur": JALUR_PENCAIRAN, "source_type": "",
     "wajib": (("order adjustment id", "id pesanan penyesuaian"),
               ("total settlement amount", "jumlah penyelesaian pembayaran")),
     "penguat": ("total revenue", "total pendapatan", "type", "jenis transaksi", "related order id",
                 "id pesanan terkait", "subtotal after seller discounts", "subtotal setelah diskon penjual"),
     "penolak": ("sku subtotal after discount",), "sheet": ()},
    {"jenis": "saldo_shopee", "label": "Saldo Penjual Shopee (mutasi saldo)", "platform": "shopee",
     "jalur": JALUR_PENARIKAN, "source_type": "",
     "wajib": (("tanggal transaksi",), ("tipe transaksi",), ("jumlah",), ("saldo akhir",)),
     "penguat": ("jenis transaksi", "deskripsi", "status"), "penolak": (), "sheet": ("transaction report",)},
    {"jenis": "penarikan_tiktok", "label": "Penarikan TikTok Shop", "platform": "tiktok",
     "jalur": JALUR_PENARIKAN, "source_type": "",
     "wajib": (("type",), ("amount",)), "penguat": ("status", "withdrawal id"),
     "penolak": ("order id", "total settlement amount", "sku id"), "sheet": ("withdrawal records",)},
    {"jenis": "iklan_cpc_shopee", "label": "Laporan Iklan CPC Shopee", "platform": "shopee",
     "jalur": JALUR_IMPOR, "source_type": "shopee_ads_cpc",
     "wajib": (("nama iklan",), ("biaya",), ("omzet penjualan", "penjualan")),
     "penguat": ("efektifitas iklan", "efektivitas iklan", "mode bidding", "kode produk", "penempatan iklan",
                 "persentase biaya iklan terhadap penjualan dari iklan acos"),
     "penolak": ("penonton",), "meta": ("periode",)},
    {"jenis": "iklan_live_shopee", "label": "Laporan Iklan Live Shopee", "platform": "shopee",
     "jalur": JALUR_BELUM, "source_type": "",
     "wajib": (("nama iklan",), ("penonton",), ("biaya",)),
     "penguat": ("modal", "waktu mulai harian"), "penolak": ("kode produk",)},
    {"jenis": "gmv_max_tiktok", "label": "Laporan Iklan TikTok GMV Max", "platform": "tiktok",
     "jalur": JALUR_IMPOR, "source_type": "tiktok_gmv_max",
     "wajib": (("nama kampanye", "campaign name"), ("id campaign", "campaign id"), ("biaya", "cost"),
               ("pendapatan kotor", "gross revenue")),
     "penguat": ("pesanan sku", "id video", "jenis materi iklan", "mata uang", "akun tiktok"),
     "penolak": (), "sheet": ("data",)},
    {"jenis": "statistik_toko_shopee", "label": "Statistik Toko Shopee", "platform": "shopee",
     "jalur": JALUR_IMPOR, "source_type": "shopee_shop_kpi",
     "wajib": (("tanggal",), ("total penjualan idr",), ("total pengunjung",)),
     "penguat": ("produk diklik", "tingkat konversi pesanan", "total pesanan"), "penolak": (),
     "sheet_wajib": ("pesanan dibuat",)},
    {"jenis": "live_video_shopee", "label": "KPI Live / Video Shopee", "platform": "shopee",
     "jalur": JALUR_IMPOR, "source_type": "shopee_content_kpi",
     "wajib": (("periode data",), ("user id",)),
     "penguat": ("penonton aktif", "jumlah livestream", "video dengan produk", "ditonton", "penonton"),
     "penolak": ()},
    {"jenis": "retur_shopee", "label": "Pengembalian / Pembatalan Shopee", "platform": "shopee",
     "jalur": JALUR_IMPOR, "source_type": "returns",
     "wajib": (("no pengembalian",), ("no pesanan",), ("solusi pengembalian barang dana",)),
     "penguat": ("alasan pengembalian", "total pengembalian dana", "status pembatalan pengembalian"),
     "penolak": ()},
    {"jenis": "retur_tiktok", "label": "Retur & Refund TikTok Shop", "platform": "tiktok",
     "jalur": JALUR_IMPOR, "source_type": "returns",
     "wajib": (("return order id",), ("order id",), ("return type",)),
     "penguat": ("return status", "return reason", "return sub status", "return unit price"), "penolak": ()},
    {"jenis": "afiliasi_shopee", "label": "Performa Affiliate Shopee (AMS)", "platform": "shopee",
     "jalur": JALUR_BELUM, "source_type": "",
     "wajib": (("id affiliates",), ("estimasi komisi rp",)),
     "penguat": ("username affiliate", "roi", "nama affiliate"), "penolak": ()},
)
JENIS_LABEL = {s["jenis"]: s["label"] for s in SIDIK}
JALUR_LABEL = {
    JALUR_IMPOR: "Diimpor ke data Marketing",
    JALUR_PENCAIRAN: "Laporan penghasilan — diproses di Keuangan › Pencairan (draf, disimpan staf Keuangan)",
    JALUR_PENARIKAN: "Laporan saldo/penarikan — diproses di Keuangan › Penarikan",
    JALUR_BELUM: "Jenis laporan dikenali, tetapi sistem belum punya pintu impornya",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PEMBACA TANGGUH — semua sheet, baris header dicari, judul grup, header kembar
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class Tabel:
    """Satu calon tabel di berkas (satu sheet / satu CSV)."""
    sheet: str
    baris_header: int                       # 0-based
    headers: List[str]                      # sudah diberi akhiran untuk header kembar
    rows: List[Dict[str, Any]] = field(default_factory=list)   # sampel baris data (≤ SAMPEL_BARIS)
    grup: Dict[str, str] = field(default_factory=dict)          # judul grup kolom (sel gabungan di atas header)
    deskripsi: Dict[str, str] = field(default_factory=dict)     # baris deskripsi kolom (TikTok baris ke-2)
    meta: Dict[str, str] = field(default_factory=dict)          # "Periode", "Username", … di atas header
    total_baris: int = 0                    # baris data yang terbaca (sampai batas pembacaan)
    terpotong: bool = False                 # pembacaan dihentikan di batas sampel


def _unik(cells: Sequence[Any]) -> List[str]:
    out, seen = [], {}
    for i, c in enumerate(cells):
        h = str(c).strip() if c not in (None, "") else f"Kolom {i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        out.append(h)
    while out and out[-1].startswith("Kolom ") and out[-1][6:].isdigit():
        out.pop()
    return out


_KATA_HEADER = None


def _semua_kata_header() -> set:
    global _KATA_HEADER
    if _KATA_HEADER is None:
        k = set()
        for s in SIDIK:
            for grp in s.get("wajib", ()):
                k.update(grp)
            k.update(s.get("penguat", ()))
        _KATA_HEADER = k
    return _KATA_HEADER


def _skor_header(row: Sequence[Any]) -> int:
    kata = _semua_kata_header()
    n = 0
    for c in row:
        if c is None or isinstance(c, (int, float)):
            continue
        if _norm_header(c) in kata:
            n += 1
    return n


def _kalimat(v: Any) -> bool:
    s = str(v or "").strip()
    return len(s) > 15 and " " in s and (s.endswith(".") or s.count(" ") >= 4)


def _bangun_tabel(sheet: str, matrix: List[List[Any]], total: int, terpotong: bool) -> Optional[Tabel]:
    best_i, best_s = -1, 0
    for i, row in enumerate(matrix[:SCAN_BARIS]):
        s = _skor_header(row)
        if s > best_s:
            best_i, best_s = i, s
    if best_i < 0:
        # tidak ada header yang dikenal: baris pertama yang terisi ≥ 2 sel
        best_i = next((i for i, r in enumerate(matrix[:SCAN_BARIS])
                       if sum(1 for c in r if c not in (None, "")) >= 2), -1)
        if best_i < 0:
            return None
    headers = _unik(matrix[best_i])
    if not headers:
        return None
    grup: Dict[str, List[str]] = {h: [] for h in headers}
    meta: Dict[str, str] = {}
    for row in matrix[:best_i]:
        filled = [j for j, c in enumerate(row) if c not in (None, "")]
        # metadata = pasangan "Label, nilai" di dua sel PERTAMA ("Username, toko"; "Periode, …")
        if filled == [0, 1] and isinstance(row[0], str):
            meta[_norm_header(row[0])] = str(row[1]).strip()
            continue
        if len(filled) < 2:
            continue                                   # judul laporan / baris kosong
        cur = ""
        for j, h in enumerate(headers):
            v = row[j] if j < len(row) else None
            if v not in (None, ""):
                cur = str(v).strip()
            if cur:
                grup[h].append(cur)
    data = matrix[best_i + 1:]
    deskripsi: Dict[str, str] = {}
    if data:
        first = data[0]
        sel = [first[j] if j < len(first) else None for j in range(len(headers))]
        isi = [v for v in sel if v not in (None, "")]
        if isi and sum(1 for v in isi if _kalimat(v)) / len(isi) >= 0.6:
            deskripsi = {h: str(sel[j]).strip() for j, h in enumerate(headers) if sel[j] not in (None, "")}
            data = data[1:]
    rows = []
    for vals in data:
        if not vals or all(v in (None, "") for v in vals):
            continue
        rows.append({h: (vals[j] if j < len(vals) else None) for j, h in enumerate(headers)})
    n = max(total - best_i - 1 - (1 if deskripsi else 0), len(rows)) if total else len(rows)
    return Tabel(sheet=sheet, baris_header=best_i, headers=headers, rows=rows[:SAMPEL_BARIS],
                 grup={h: " / ".join(dict.fromkeys(g)) for h, g in grup.items() if g},
                 deskripsi=deskripsi, meta=meta, total_baris=n, terpotong=terpotong)


def _matrix_xlsx(raw: bytes, batas: int) -> List[Tuple[str, List[List[Any]], int, bool]]:
    import openpyxl

    def _baca(read_only: bool):
        out = []
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=read_only, data_only=True)
        try:
            for ws in wb.worksheets:
                if read_only:
                    try:
                        ws.reset_dimensions()
                    except Exception:  # noqa: BLE001
                        pass
                m: List[List[Any]] = []
                total = 0
                terpotong = False
                for vals in ws.iter_rows(values_only=True):
                    total += 1
                    if len(m) < batas:
                        m.append(list(vals or []))
                    else:
                        terpotong = True
                        if total > batas * 4:          # cukup untuk menaksir besarnya berkas
                            break
                out.append((ws.title, m, total, terpotong))
        finally:
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
        return out

    hasil = _baca(True)
    # Ekspor TikTok menulis 1 sel per <row>: mode aliran melihat 1 kolom → baca ulang penuh
    if hasil and all(max((len(r) for r in m[:SCAN_BARIS]), default=0) <= 1 for _, m, _, _ in hasil) \
            and len(raw) < 8 * 1024 * 1024:
        hasil = _baca(False)
    return hasil


def _matrix_csv(raw: bytes, batas: int) -> List[Tuple[str, List[List[Any]], int, bool]]:
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4000]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:  # noqa: BLE001
        delim = ";" if sample.count(";") > sample.count(",") else ","
    m: List[List[Any]] = []
    total = 0
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        total += 1
        if len(m) < batas:
            m.append(row)
    return [("", m, total, total > batas)]


def baca_tabel(raw: bytes, filename: str, batas: int = SAMPEL_BARIS + SCAN_BARIS + 2) -> List[Tabel]:
    """Semua calon tabel di berkas (xlsx: per sheet; csv: satu). Berkas `.xls` yang isinya
    xlsx (zip) — bentuk nyata ekspor retur Shopee — dibaca sebagai xlsx."""
    is_zip = raw[:2] == b"PK"
    name = (filename or "").lower()
    if is_zip or name.endswith((".xlsx", ".xlsm")):
        mats = _matrix_xlsx(raw, batas)
    else:
        mats = _matrix_csv(raw, batas)
    out = []
    for sheet, m, total, cut in mats:
        t = _bangun_tabel(sheet, m, total, cut)
        if t is not None:
            out.append(t)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SIDIK — jenis laporan dari tanda pengenal
# ═══════════════════════════════════════════════════════════════════════════════
def _nilai_sidik(s: dict, t: Tabel, sheets: set) -> Optional[dict]:
    hset = {_norm_header(h) for h in t.headers}
    hset |= {_norm_header(re.sub(r"\s*\(\d+\)$", "", h)) for h in t.headers}
    for p in s.get("penolak", ()):
        if p in hset:
            return None
    cocok, kurang = [], []
    for grp in s.get("wajib", ()):
        hit = next((g for g in grp if g in hset), None)
        (cocok if hit else kurang).append(hit or " / ".join(grp))
    if kurang:
        return None
    if s.get("sheet_wajib") and not (set(s["sheet_wajib"]) & sheets):
        return None
    for m in s.get("meta", ()):
        if m not in t.meta:
            return None
    penguat = [p for p in s.get("penguat", ()) if p in hset]
    sheet_ok = bool(s.get("sheet")) and _norm_header(t.sheet) in s["sheet"]
    skor = len(cocok) * 3 + len(penguat) + (2 if sheet_ok else 0)
    return {"jenis": s["jenis"], "label": s["label"], "platform": s["platform"], "jalur": s["jalur"],
            "source_type": s["source_type"], "skor": skor, "wajib_cocok": cocok, "penguat": penguat,
            "sheet": t.sheet, "baris_header": t.baris_header + 1}


def _versi(jenis: str, t: Tabel) -> str:
    n = len(t.headers)
    if jenis == "pesanan_tiktok":
        return f"{n} kolom" + (" + baris deskripsi" if t.deskripsi else "")
    if jenis == "pesanan_shopee":
        return f"{n} kolom"
    if jenis == "penghasilan_shopee":
        return "format Okt 2026 (header baris 3)" if t.baris_header == 2 else (
            "format lama (header baris 6)" if t.baris_header == 5 else f"header baris {t.baris_header + 1}")
    if jenis == "saldo_shopee":
        return f"header baris {t.baris_header + 1}"
    return f"{n} kolom"


def kenali(raw: bytes, filename: str, tabel: Optional[List[Tabel]] = None) -> dict:
    """Jenis laporan berkas ini + bukti. Tidak pernah memakai nama berkas sebagai penentu.

    → ``{dikenal, jenis, label, platform, jalur, jalur_label, source_type, versi, bukti{...},
        kandidat[], tabel{sheet, baris_header, kolom, baris, deskripsi_kolom, judul_grup, meta}}``"""
    tabel = tabel if tabel is not None else baca_tabel(raw, filename)
    sheets = {_norm_header(t.sheet) for t in tabel}
    kandidat = []
    for t in tabel:
        for s in SIDIK:
            r = _nilai_sidik(s, t, sheets)
            if r:
                r["_t"] = t
                kandidat.append(r)
    kandidat.sort(key=lambda r: -r["skor"])
    if not kandidat:
        t0 = tabel[0] if tabel else None
        return {"dikenal": False, "jenis": "", "label": "Belum dikenali", "platform": _platform_lemah(filename),
                "jalur": "", "jalur_label": "Jenis laporan belum dikenali — pilih jenisnya sendiri",
                "source_type": "", "versi": "", "bukti": {"nama_berkas": filename}, "kandidat": [],
                "tabel": _ringkas_tabel(t0) if t0 else None}
    best = kandidat[0]
    t = best.pop("_t")
    for k in kandidat[1:]:
        k.pop("_t", None)
    dekat = [k for k in kandidat[1:] if k["skor"] >= best["skor"] - 1 and k["jenis"] != best["jenis"]]
    return {
        "dikenal": True, "jenis": best["jenis"], "label": best["label"], "platform": best["platform"],
        "jalur": best["jalur"], "jalur_label": JALUR_LABEL[best["jalur"]],
        "source_type": best["source_type"], "versi": _versi(best["jenis"], t),
        "bukti": {"kolom_wajib": best["wajib_cocok"], "kolom_penguat": best["penguat"],
                  "sheet": t.sheet, "baris_header": t.baris_header + 1},
        "ragu": bool(dekat), "kandidat": [{k: v for k, v in c.items()} for c in kandidat[:5]],
        "tabel": _ringkas_tabel(t),
    }


def _ringkas_tabel(t: Tabel) -> dict:
    return {"sheet": t.sheet, "baris_header": t.baris_header + 1, "kolom": len(t.headers),
            "baris": t.total_baris, "terpotong": t.terpotong,
            "ada_deskripsi_kolom": bool(t.deskripsi), "ada_judul_grup": bool(t.grup), "meta": dict(t.meta)}


def _platform_lemah(filename: str) -> str:
    n = (filename or "").lower()
    for p in ("shopee", "tiktok", "tokopedia", "lazada"):
        if p in n:
            return p
    return ""


def tabel_utama(raw: bytes, filename: str) -> Tuple[dict, Optional[Tabel]]:
    """(hasil `kenali`, tabel yang menang) — dipakai paket impor & AI pemeta."""
    tabel = baca_tabel(raw, filename)
    hasil = kenali(raw, filename, tabel)
    want = (hasil.get("tabel") or {}).get("sheet")
    t = next((x for x in tabel if x.sheet == want), tabel[0] if tabel else None)
    return hasil, t


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PROFIL NILAI PER KOLOM (riset §7.1 butir 4)
# ═══════════════════════════════════════════════════════════════════════════════
_RX_DURASI = re.compile(r"^(\d+j)?(\d+m)?(\d+d)$|^\d{1,2}:\d{2}:\d{2}$", re.IGNORECASE)
_RX_BERAT = re.compile(r"^\s*[\d.,]+\s*(gr|g|gram|kg)\s*$", re.IGNORECASE)
_RX_ID = re.compile(r"^\d{12,22}$")
_RX_TGL = re.compile(r"^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})")
_PII_HEADER = re.compile(
    r"pembeli|penerima|buyer|recipient|customer|pelanggan|username|telepon|telp|phone|no\.? ?hp|\bhp\b|"
    r"alamat|address|e-?mail|kode ?pos|zip|kecamatan|kelurahan|catatan|\bpesan\b|message|note|nama affiliate|"
    r"akun tiktok|creator|kreator|judul video|video title", re.IGNORECASE)


def kolom_pribadi(header: str) -> bool:
    """Header yang isinya data pribadi/teks bebas orang — nilainya TIDAK PERNAH dikirim ke AI."""
    return bool(_PII_HEADER.search(str(header or "")))


def pola(v: Any) -> str:
    """Bentuk nilai tanpa isinya: angka → 9, huruf → A ("Rp1.234" → "AA9.999")."""
    s = str(v if v is not None else "")[:24]
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", s))


def profil_nilai(headers: Sequence[str], rows: Sequence[dict], *,
                 kolom_pesanan: Optional[str] = None) -> Dict[str, dict]:
    """Profil tersamar tiap kolom. ``kolom_pesanan`` = kolom nomor pesanan (untuk menilai
    apakah uang suatu kolom PER PESANAN — sama di semua baris pesanan — atau per baris)."""
    out: Dict[str, dict] = {}
    for h in headers:
        vals = [r.get(h) for r in rows]
        isi = [v for v in vals if v not in (None, "") and str(v).strip() not in ("-", "N/A", "n/a")]
        p: Dict[str, Any] = {"terisi": len(isi), "kosong": len(vals) - len(isi),
                             "unik": len({str(v) for v in isi})}
        if not isi:
            p["tipe"] = "kosong"
            out[h] = p
            continue
        teks = [str(v).strip() for v in isi]
        n = len(isi)
        p["konstan"] = p["unik"] == 1
        p["persen_bertanda"] = round(sum(1 for s in teks if s.endswith("%")) / n, 3)
        p["awalan_rp"] = round(sum(1 for s in teks if s.lower().startswith("rp")) / n, 3)
        p["negatif"] = sum(1 for s in teks if s.startswith("-") or (s.startswith("(") and s.endswith(")")))
        tgl = [s for s in teks if _RX_TGL.match(s)]
        dur = [s for s in teks if _RX_DURASI.match(s)]
        brt = [s for s in teks if _RX_BERAT.match(s)]
        ids = [s for s in teks if _RX_ID.match(s)]
        angka = []
        gaya = gaya_angka_kolom(isi)
        for v in isi:
            x, err = parse_number(v, gaya)
            if x is not None and err is None:
                angka.append(x)
        if len(tgl) / n >= 0.8:
            p["tipe"] = "tanggal"
            hari_dulu = any(int(m.group(1)) > 12 for m in (_RX_TGL.match(s) for s in tgl) if len(m.group(1)) <= 2)
            tahun_dulu = all(len(_RX_TGL.match(s).group(1)) == 4 for s in tgl)
            p["urutan"] = "tahun-bulan-hari" if tahun_dulu else ("hari-bulan-tahun" if hari_dulu or not tahun_dulu else "")
            p["berjam"] = any(":" in s for s in tgl)
            ok = sum(1 for s in tgl[:50] if parse_date(s)[0] is not None)
            p["terbaca"] = round(ok / min(len(tgl), 50), 3)
        elif len(dur) / n >= 0.8:
            p["tipe"] = "durasi"
        elif len(brt) / n >= 0.8:
            p["tipe"] = "berat"
            p["satuan"] = sorted({re.sub(r"[\d.,\s]", "", s).lower() for s in brt})
        elif len(ids) / n >= 0.8:
            p["tipe"] = "id"
            p["panjang"] = sorted({len(s) for s in ids})[:3]
        elif len(angka) / n >= 0.9:
            p["tipe"] = "persen" if p["persen_bertanda"] >= 0.5 else "angka"
            p["gaya_angka"] = gaya or GAYA_OTOMATIS or "otomatis"
            p["min"], p["maks"] = round(min(angka), 4), round(max(angka), 4)
            p["bulat"] = all(abs(x - round(x)) < 1e-9 for x in angka)
            p["pecahan_0_1"] = all(0 <= x <= 1 for x in angka)
            desimal = {len(str(t).rsplit(".", 1)[1]) for t in teks if "." in t and gaya == "titik_desimal"}
            if desimal:
                p["desimal"] = sorted(desimal)[:3]
        else:
            p["tipe"] = "teks"
            p["panjang_rata"] = round(sum(len(s) for s in teks) / n, 1)
            if p["unik"] <= 12 and not kolom_pribadi(h):
                # kategori (status, kurir, kanal) aman dikirim sebagai contoh
                p["kategori"] = sorted({s[:40] for s in teks})[:8]
        p["contoh_pola"] = sorted({pola(v) for v in isi[:30]})[:3]
        out[h] = p
    if kolom_pesanan and kolom_pesanan in headers:
        grup: Dict[str, List[dict]] = {}
        for r in rows:
            k = str(r.get(kolom_pesanan) or "")
            if k:
                grup.setdefault(k, []).append(r)
        multi = [g for g in grup.values() if len(g) > 1]
        if multi:
            for h in headers:
                if h == kolom_pesanan or out.get(h, {}).get("tipe") not in ("angka", "persen"):
                    continue
                sama = sum(1 for g in multi if len({str(x.get(h)) for x in g}) == 1)
                out[h]["sama_dalam_pesanan"] = round(sama / len(multi), 3)
                out[h]["tingkat"] = "per_pesanan" if sama == len(multi) else "per_baris"
    return out


def profil_untuk_ai(profil: Dict[str, dict]) -> Dict[str, dict]:
    """Salinan profil yang AMAN dikirim ke AI: tanpa kategori untuk kolom pribadi, tanpa nilai mentah."""
    out = {}
    for h, p in profil.items():
        q = {k: v for k, v in p.items() if k != "kategori" or not kolom_pribadi(h)}
        out[h] = q
    return out


def kolom_angka(profil: Dict[str, dict]) -> List[str]:
    return [h for h, p in profil.items() if p.get("tipe") in ("angka", "persen")]


def daftar_sidik() -> List[dict]:
    """Katalog tanda pengenal (untuk layar bantuan & uji)."""
    return [{"jenis": s["jenis"], "label": s["label"], "platform": s["platform"], "jalur": s["jalur"],
             "source_type": s["source_type"]} for s in SIDIK]


def cocokkan_semua(berkas: Iterable[Tuple[bytes, str]]) -> List[dict]:
    return [kenali(raw, name) for raw, name in berkas]
