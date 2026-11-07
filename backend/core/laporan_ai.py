"""core/laporan_ai.py — pembuat laporan PDF & Excel Asisten AI (Tahap A, 7 Nov 2026).

Dipakai alat `buat_laporan` (`core/asisten_ai/alat/laporan.py`) dan rute unduh
`GET /api/asisten-ai/laporan/{id}` (`routes/asisten_ai_laporan_routes.py`).

Isi laporan datang dari model sebagai SPESIFIKASI (bukan HTML/markdown bebas):
    {judul, subjudul?, periode_label?, format: ["pdf"|"xlsx"...],
     bagian: [{judul?, teks? (markdown sederhana), tabel? {kolom, baris, catatan?, satuan?},
               grafik? (spesifikasi grafik Kontrak B)}]}
Spesifikasi DIVALIDASI dulu (`validasi_spek`) dengan batas jumlah bagian, baris, sel, dan karakter;
pesan galatnya berbahasa Indonesia supaya model bisa memperbaiki isiannya sendiri.

PDF  : reportlab A4, kop surat dari template PDF pemilik (`core.pdf_template.resolve` + profil CV),
       angka gaya Indonesia (Rp, titik ribuan), tanggal WIB, grafik `reportlab.graphics`
       (batang, batang horizontal, garis, area, pai) dari spesifikasi yang SAMA dengan layar.
Excel: openpyxl — lembar "Ringkasan" berisi teks, satu lembar per tabel (kolom uang berformat Rp),
       data grafik di lembar sendiri lengkap dengan grafik Excel.
Simpan: berkas lewat `object_storage.put_object` (penyimpanan unggahan yang sama, lokal di server),
       di bawah awalan `ai_reports/<laporan_id>/<acak>.<ext>`; metadata di koleksi `ai_reports` (jenis log).
       Berkas TIDAK pernah ditautkan langsung: unduhan hanya lewat rute yang memeriksa pemilik.
"""
from __future__ import annotations

import asyncio
import io
import logging
import math
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

COLL = "ai_reports"
DOC_KEY = "laporan-asisten-ai"          # kunci template PDF (tidak terdaftar → template GLOBAL dipakai)
FORMAT_SAH = ("pdf", "xlsx")
JENIS_GRAFIK = ("batang", "batang_horizontal", "garis", "area", "pai")
NAMA_GABUNGAN = "CV Dewi Aditya & CV Sukma"
PERAN_UNDUH_SEMUA = ("owner", "superadmin")
CONTENT_TYPE = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Batas isi laporan. Laporan Asisten AI = ringkasan analisis, bukan ekspor data mentah.
BATAS = {
    "judul": 160, "subjudul": 240, "periode_label": 80,
    "bagian": 30, "judul_bagian": 160, "teks_bagian": 6000, "teks_total": 40000,
    "kolom": 12, "nama_kolom": 60, "baris": 300, "sel_total": 15000, "teks_sel": 200,
    "catatan": 500, "satuan": 16,
    "seri": 4, "titik": 31, "label_x": 60, "nama_seri": 60, "catatan_grafik": 300,
}
MAKS_UKURAN_BERKAS = 8 * 1024 * 1024

# Palet kategori (urutan tetap, tidak diputar) — palet rujukan dataviz, mode terang (cetak).
PALET = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GARIS_KISI = "#e2e2de"


class SpekLaporanError(ValueError):
    """Isi laporan tidak sah. `pesan` = kalimat Indonesia untuk model/pengguna."""

    def __init__(self, pesan: str):
        super().__init__(pesan)
        self.pesan = pesan


# ═══════════════════════════════════════════════════════════════════════════════
# FORMAT ANGKA & TANGGAL (gaya Indonesia)
# ═══════════════════════════════════════════════════════════════════════════════
def _ribuan(n: float, desimal: int = 0) -> str:
    s = f"{abs(n):,.{desimal}f}".replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")
    if desimal and "," in s:
        s = s.rstrip("0").rstrip(",")
    return ("-" if n < 0 and s not in ("0",) else "") + s


def format_rupiah(v) -> str:
    """1500000 → 'Rp 1.500.000'; -2500 → '-Rp 2.500'."""
    try:
        n = round(float(v))
    except (TypeError, ValueError):
        return "-"
    return ("-" if n < 0 else "") + "Rp " + _ribuan(abs(n))


def format_angka(v, desimal: int = 2) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if n == int(n):
        return _ribuan(int(n))
    return _ribuan(n, desimal)


def format_persen(v) -> str:
    """12.5 → '12,5%'; 3 → '3,0%' (selalu satu desimal supaya kolom persen rata)."""
    try:
        return f"{float(v):,.1f}".replace(",", "\u0000").replace(".", ",").replace("\u0000", ".") + "%"
    except (TypeError, ValueError):
        return str(v)


def singkat(v: float, satuan: str = "") -> str:
    """Label sumbu ringkas: 1.250.000.000 → '1,25 M'; 250.000 → '250.000'; satuan 'Rp' → 'Rp 1,25 M'."""
    n = float(v or 0)
    a = abs(n)
    for batas, akhiran in ((1e12, " T"), (1e9, " M"), (1e6, " jt")):
        if a >= batas:
            teks = _ribuan(n / batas, 2) + akhiran
            break
    else:
        teks = _ribuan(n, 2)
    s = (satuan or "").strip()
    if s.lower() == "rp":
        return "Rp " + teks
    if s == "%":
        return teks + "%"
    return teks


BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
         "Oktober", "November", "Desember")


def tanggal_wib(dt: Optional[datetime] = None, *, jam: bool = True) -> str:
    """'7 November 2026 14.05 WIB'."""
    from utils.waktu import now_wib, to_wib
    w = to_wib(dt) if dt else now_wib()
    s = f"{w.day} {BULAN[w.month - 1]} {w.year}"
    return f"{s} {w.hour:02d}.{w.minute:02d} WIB" if jam else s


def label_cv(cv: str) -> str:
    if cv == "ALL":
        return f"Gabungan ({NAMA_GABUNGAN})"
    from core.entities import entity_short
    return entity_short(cv)


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDASI SPESIFIKASI
# ═══════════════════════════════════════════════════════════════════════════════
_KUNCI_ATAS = {"judul", "subjudul", "periode_label", "format", "bagian"}
_KUNCI_BAGIAN = {"judul", "teks", "tabel", "grafik"}
_KUNCI_TABEL = {"kolom", "baris", "catatan", "satuan", "judul"}
_KUNCI_GRAFIK = {"jenis", "judul", "satuan", "x", "seri", "catatan"}
_KTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _bersih(s) -> str:
    return _KTRL.sub("", str(s)).strip()


def _teks(v, nama: str, batas: int, *, wajib: bool = False) -> str:
    if v is None or (isinstance(v, str) and not v.strip()):
        if wajib:
            raise SpekLaporanError(f"{nama} wajib diisi.")
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise SpekLaporanError(f"{nama} harus berupa teks.")
    s = _bersih(v)
    if len(s) > batas:
        raise SpekLaporanError(f"{nama} terlalu panjang ({len(s)} karakter, paling banyak {batas}).")
    return s


def _angka(v, tempat: str):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SpekLaporanError(f"{tempat}: nilai harus angka (atau kosong), bukan teks.")
    if not math.isfinite(float(v)):
        raise SpekLaporanError(f"{tempat}: nilai harus angka biasa (bukan tak hingga).")
    return v


def _kunci_asing(d: dict, sah: set, tempat: str):
    asing = sorted(set(d) - sah)
    if asing:
        raise SpekLaporanError(
            f"{tempat}: kunci {', '.join(asing)} tidak dikenal. Gunakan: {', '.join(sorted(sah))}.")


def validasi_grafik(g, tempat: str = "Grafik") -> dict:
    """Spesifikasi grafik Kontrak B → bentuk baku. ≤4 seri, ≤31 titik x, pai tepat 1 seri."""
    if not isinstance(g, dict):
        raise SpekLaporanError(f"{tempat} harus berupa objek.")
    _kunci_asing(g, _KUNCI_GRAFIK, tempat)
    jenis = str(g.get("jenis") or "").strip().lower()
    if jenis not in JENIS_GRAFIK:
        raise SpekLaporanError(f"{tempat}: jenis harus salah satu dari {', '.join(JENIS_GRAFIK)}.")
    x = g.get("x")
    if not isinstance(x, list) or not x:
        raise SpekLaporanError(f"{tempat}: daftar x (label sumbu) wajib diisi.")
    if len(x) > BATAS["titik"]:
        raise SpekLaporanError(f"{tempat}: paling banyak {BATAS['titik']} titik pada sumbu x (ada {len(x)}).")
    xs = [_teks(v, f"{tempat}: label x ke-{i + 1}", BATAS["label_x"], wajib=True) for i, v in enumerate(x)]
    seri = g.get("seri")
    if not isinstance(seri, list) or not seri:
        raise SpekLaporanError(f"{tempat}: seri wajib berisi minimal satu seri.")
    if len(seri) > BATAS["seri"]:
        raise SpekLaporanError(f"{tempat}: paling banyak {BATAS['seri']} seri (ada {len(seri)}).")
    if jenis == "pai" and len(seri) != 1:
        raise SpekLaporanError(f"{tempat}: grafik pai harus tepat satu seri.")
    out_seri = []
    for i, s in enumerate(seri):
        ts = f"{tempat}, seri ke-{i + 1}"
        if not isinstance(s, dict):
            raise SpekLaporanError(f"{ts} harus berupa objek {{nama, nilai}}.")
        _kunci_asing(s, {"nama", "nilai"}, ts)
        nama = _teks(s.get("nama"), f"{ts}: nama", BATAS["nama_seri"], wajib=True)
        nilai = s.get("nilai")
        if not isinstance(nilai, list) or len(nilai) != len(xs):
            raise SpekLaporanError(f"{ts}: jumlah nilai harus sama dengan jumlah label x ({len(xs)}).")
        vals = [_angka(v, f"{ts}, titik ke-{j + 1}") for j, v in enumerate(nilai)]
        out_seri.append({"nama": nama, "nilai": vals})
    if jenis == "pai":
        vals = out_seri[0]["nilai"]
        if any(v is None or v < 0 for v in vals):
            raise SpekLaporanError(f"{tempat}: nilai grafik pai harus angka nol atau positif.")
        if not sum(vals) > 0:
            raise SpekLaporanError(f"{tempat}: total nilai grafik pai harus lebih dari nol.")
    return {
        "jenis": jenis,
        "judul": _teks(g.get("judul"), f"{tempat}: judul", BATAS["judul_bagian"]),
        "satuan": _teks(g.get("satuan"), f"{tempat}: satuan", BATAS["satuan"]),
        "x": xs,
        "seri": out_seri,
        "catatan": _teks(g.get("catatan"), f"{tempat}: catatan", BATAS["catatan_grafik"]),
    }


def _validasi_tabel(t, tempat: str) -> dict:
    if not isinstance(t, dict):
        raise SpekLaporanError(f"{tempat} harus berupa objek {{kolom, baris}}.")
    _kunci_asing(t, _KUNCI_TABEL, tempat)
    kolom = t.get("kolom")
    if not isinstance(kolom, list) or not kolom:
        raise SpekLaporanError(f"{tempat}: kolom wajib berisi minimal satu nama kolom.")
    if len(kolom) > BATAS["kolom"]:
        raise SpekLaporanError(f"{tempat}: paling banyak {BATAS['kolom']} kolom (ada {len(kolom)}).")
    kol = [_teks(k, f"{tempat}: nama kolom ke-{i + 1}", BATAS["nama_kolom"], wajib=True)
           for i, k in enumerate(kolom)]
    baris = t.get("baris")
    if baris is None:
        baris = []
    if not isinstance(baris, list):
        raise SpekLaporanError(f"{tempat}: baris harus berupa daftar baris.")
    if len(baris) > BATAS["baris"]:
        raise SpekLaporanError(
            f"{tempat}: paling banyak {BATAS['baris']} baris (ada {len(baris)}). Ringkas atau kelompokkan datanya.")
    rows = []
    for i, r in enumerate(baris):
        tb = f"{tempat}, baris ke-{i + 1}"
        if not isinstance(r, list):
            raise SpekLaporanError(f"{tb} harus berupa daftar sel.")
        if len(r) > len(kol):
            raise SpekLaporanError(f"{tb} berisi {len(r)} sel, padahal hanya ada {len(kol)} kolom.")
        row = []
        for j, c in enumerate(r):
            if c is None:
                row.append("")
            elif isinstance(c, bool):
                row.append("Ya" if c else "Tidak")
            elif isinstance(c, (int, float)):
                row.append(_angka(c, f"{tb}, kolom ke-{j + 1}"))
            elif isinstance(c, str):
                s = _bersih(c)
                row.append(s if len(s) <= BATAS["teks_sel"] else s[:BATAS["teks_sel"] - 1] + "…")
            else:
                raise SpekLaporanError(f"{tb}, kolom ke-{j + 1}: isi sel harus teks atau angka.")
        row.extend([""] * (len(kol) - len(row)))
        rows.append(row)
    satuan = t.get("satuan")
    if satuan is not None:
        if not isinstance(satuan, list) or len(satuan) != len(kol):
            raise SpekLaporanError(f"{tempat}: satuan harus daftar sepanjang jumlah kolom ({len(kol)}).")
        satuan = [_teks(s, f"{tempat}: satuan kolom ke-{i + 1}", BATAS["satuan"]) for i, s in enumerate(satuan)]
    return {"kolom": kol, "baris": rows,
            "catatan": _teks(t.get("catatan"), f"{tempat}: catatan", BATAS["catatan"]),
            "satuan": satuan}


def validasi_spek(raw) -> dict:
    """Spesifikasi laporan dari model → bentuk baku. Melempar `SpekLaporanError` (pesan Indonesia)."""
    if not isinstance(raw, dict):
        raise SpekLaporanError("Isi laporan harus berupa objek {judul, format, bagian}.")
    _kunci_asing(raw, _KUNCI_ATAS, "Laporan")
    judul = _teks(raw.get("judul"), "Judul laporan", BATAS["judul"], wajib=True)
    fmt = raw.get("format") if raw.get("format") is not None else ["pdf"]
    if isinstance(fmt, str):
        fmt = [fmt]
    if not isinstance(fmt, list) or not fmt:
        raise SpekLaporanError("Format laporan harus [\"pdf\"], [\"xlsx\"], atau [\"pdf\", \"xlsx\"].")
    fmts = []
    for f in fmt:
        v = str(f or "").strip().lower().lstrip(".")
        v = {"excel": "xlsx", "xls": "xlsx"}.get(v, v)
        if v not in FORMAT_SAH:
            raise SpekLaporanError(f"Format '{f}' tidak dikenal. Pilih pdf dan/atau xlsx.")
        if v not in fmts:
            fmts.append(v)
    fmts.sort(key=FORMAT_SAH.index)
    bagian = raw.get("bagian")
    if not isinstance(bagian, list) or not bagian:
        raise SpekLaporanError("Laporan wajib punya minimal satu bagian (teks, tabel, atau grafik).")
    if len(bagian) > BATAS["bagian"]:
        raise SpekLaporanError(f"Laporan paling banyak {BATAS['bagian']} bagian (ada {len(bagian)}).")
    out, total_teks, total_sel = [], 0, 0
    for i, b in enumerate(bagian):
        tempat = f"Bagian ke-{i + 1}"
        if not isinstance(b, dict):
            raise SpekLaporanError(f"{tempat} harus berupa objek {{judul, teks, tabel, grafik}}.")
        _kunci_asing(b, _KUNCI_BAGIAN, tempat)
        nb = {"judul": _teks(b.get("judul"), f"{tempat}: judul", BATAS["judul_bagian"]),
              "teks": "", "tabel": None, "grafik": None}
        if b.get("teks") not in (None, ""):
            if not isinstance(b["teks"], str):
                raise SpekLaporanError(f"{tempat}: teks harus berupa teks markdown.")
            t = _KTRL.sub("", b["teks"]).strip()
            if len(t) > BATAS["teks_bagian"]:
                raise SpekLaporanError(
                    f"{tempat}: teks terlalu panjang ({len(t)} karakter, paling banyak {BATAS['teks_bagian']}).")
            nb["teks"] = t
            total_teks += len(t)
        if b.get("tabel") is not None:
            nb["tabel"] = _validasi_tabel(b["tabel"], f"{tempat}, tabel")
            total_sel += len(nb["tabel"]["baris"]) * len(nb["tabel"]["kolom"])
        if b.get("grafik") is not None:
            nb["grafik"] = validasi_grafik(b["grafik"], f"{tempat}, grafik")
        if not (nb["teks"] or nb["tabel"] or nb["grafik"]):
            raise SpekLaporanError(f"{tempat} kosong: isi minimal salah satu dari teks, tabel, atau grafik.")
        out.append(nb)
    if total_teks > BATAS["teks_total"]:
        raise SpekLaporanError(
            f"Total teks laporan {total_teks} karakter, paling banyak {BATAS['teks_total']}. Ringkas isinya.")
    if total_sel > BATAS["sel_total"]:
        raise SpekLaporanError(
            f"Total sel tabel {total_sel}, paling banyak {BATAS['sel_total']}. Ringkas atau kelompokkan datanya.")
    return {
        "judul": judul,
        "subjudul": _teks(raw.get("subjudul"), "Subjudul", BATAS["subjudul"]),
        "periode_label": _teks(raw.get("periode_label"), "Label periode", BATAS["periode_label"]),
        "format": fmts,
        "bagian": out,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# JENIS KOLOM TABEL (uang / persen / angka / teks)
# ═══════════════════════════════════════════════════════════════════════════════
_KATA_UANG = re.compile(
    r"(\brp\b|rupiah|omzet|nilai|harga|biaya|laba|rugi|pendapatan|beban|piutang|hutang|\butang|"
    r"\bkas\b|saldo|\bhpp\b|ongkos|upah|modal|aset|aktiva|pasiva|ekuitas|setoran|pengeluaran|pemasukan)",
    re.IGNORECASE)


def jenis_kolom(nama: str, nilai: list, satuan: str = "") -> str:
    """'rp' | 'persen' | 'angka' | 'teks'. Satuan dari spesifikasi menang; lainnya ditebak dari nama kolom."""
    isi = [v for v in nilai if v not in ("", None)]
    if not isi or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in isi):
        return "teks"
    s = (satuan or "").strip().lower()
    if s in ("rp", "idr", "rupiah"):
        return "rp"
    if s == "%":
        return "persen"
    if s:
        return "angka"
    if "%" in nama or re.search(r"\bpersen", nama, re.IGNORECASE):
        return "persen"
    if _KATA_UANG.search(nama):
        return "rp"
    return "angka"


def format_sel(v, jenis: str) -> str:
    if v in ("", None):
        return ""
    if isinstance(v, str):
        return v
    if jenis == "rp":
        return format_rupiah(v)
    if jenis == "persen":
        return format_persen(v)
    return format_angka(v)


def jenis_kolom_tabel(tabel: dict) -> list:
    sat = tabel.get("satuan") or [""] * len(tabel["kolom"])
    return [jenis_kolom(k, [r[i] for r in tabel["baris"]], sat[i]) for i, k in enumerate(tabel["kolom"])]


# ═══════════════════════════════════════════════════════════════════════════════
# MARKDOWN SEDERHANA → blok
# ═══════════════════════════════════════════════════════════════════════════════
_RX_JUDUL = re.compile(r"^(#{1,4})\s+(.*)$")
_RX_POIN = re.compile(r"^\s*[-*•]\s+(.*)$")
_RX_NOMOR = re.compile(r"^\s*(\d{1,3})[.)]\s+(.*)$")


def urai_markdown(teks: str) -> list:
    """Markdown sederhana → [('judul', level, isi) | ('paragraf', isi) | ('poin', [isi]) | ('nomor', [isi])]."""
    blok: list = []
    para: list = []

    def tutup_para():
        if para:
            blok.append(("paragraf", " ".join(para)))
            para.clear()

    for baris in (teks or "").splitlines():
        b = baris.rstrip()
        if not b.strip():
            tutup_para()
            continue
        m = _RX_JUDUL.match(b.strip())
        if m:
            tutup_para()
            blok.append(("judul", len(m.group(1)), m.group(2).strip().strip("#").strip()))
            continue
        m = _RX_POIN.match(b)
        if m:
            tutup_para()
            if blok and blok[-1][0] == "poin":
                blok[-1][1].append(m.group(1).strip())
            else:
                blok.append(("poin", [m.group(1).strip()]))
            continue
        m = _RX_NOMOR.match(b)
        if m:
            tutup_para()
            if blok and blok[-1][0] == "nomor":
                blok[-1][1].append(m.group(2).strip())
            else:
                blok.append(("nomor", [m.group(2).strip()]))
            continue
        para.append(b.strip())
    tutup_para()
    return blok


def teks_polos(md: str) -> str:
    """Markdown inline → teks polos (untuk Excel)."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", md or "")
    s = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", s)
    return s.replace("`", "")


# ── teks aman untuk font standar PDF (WinAnsi) ───────────────────────────────
_GANTI_HURUF = {"≤": "<=", "≥": ">=", "→": "->", "←": "<-", "↑": "naik", "↓": "turun", "−": "-",
                "✓": "v", "✔": "v", "✗": "x", "✘": "x", "≈": "~", "≠": "!=", " ": " "}


def teks_pdf(s) -> str:
    out = []
    for ch in str(s or ""):
        if ch in _GANTI_HURUF:
            out.append(_GANTI_HURUF[ch])
            continue
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            continue     # emoji / huruf di luar font standar dibuang, bukan kotak hitam
    return "".join(out)


def _esc(s) -> str:
    return teks_pdf(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline_pdf(md: str) -> str:
    """Escape dulu, baru **tebal** / *miring* → tag reportlab (teks model tidak bisa menyisipkan tag)."""
    s = _esc(md)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return s.replace("`", "")


# ═══════════════════════════════════════════════════════════════════════════════
# GRAFIK (reportlab.graphics) — spesifikasi Kontrak B
# ═══════════════════════════════════════════════════════════════════════════════
def _warna(hexs: str, alpha: float = 1.0):
    from reportlab.lib import colors
    c = colors.HexColor(hexs)
    return colors.Color(c.red, c.green, c.blue, alpha=alpha) if alpha < 1 else c


def _potong(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def _legenda(seri_nama: list, x0: float, y0: float, lebar: float):
    from reportlab.graphics.charts.legends import Legend
    lg = Legend()
    lg.x, lg.y = x0, y0
    lg.fontName, lg.fontSize = "Helvetica", 7.5
    lg.fillColor = _warna(TINTA_2)
    lg.dx, lg.dy, lg.dxTextSpace = 8, 8, 4
    lg.alignment = "right"
    lg.boxAnchor = "sw"
    lg.strokeWidth = 0
    names = [teks_pdf(_potong(n, 28)) for n in seri_nama]
    lg.columnMaximum = 1                       # satu baris mendatar di bawah grafik
    lg.deltax = min(lebar / max(1, len(names)), 5.2 * max(len(n) for n in names) + 34)
    lg.deltay = 11
    lg.colorNamePairs = [(_warna(PALET[i % len(PALET)]), n) for i, n in enumerate(names)]
    return lg


def _gaya_sumbu(ax, *, nilai: bool):
    ax.strokeColor = _warna(GARIS_KISI if nilai else TINTA_2)
    ax.strokeWidth = 0.5
    ax.labels.fontName = "Helvetica"
    ax.labels.fontSize = 7
    ax.labels.fillColor = _warna(TINTA_2)
    if nilai:
        ax.visibleGrid = True
        ax.gridStrokeColor = _warna(GARIS_KISI)
        ax.gridStrokeWidth = 0.4
        ax.visibleAxis = False
        ax.visibleTicks = False


def _rentang(seri: list) -> tuple:
    vals = [v for s in seri for v in s["nilai"] if v is not None]
    lo, hi = (min(vals), max(vals)) if vals else (0, 1)
    lo, hi = min(0, lo), max(0, hi)
    if lo == hi:
        hi = lo + 1
    return lo, hi


def _kelas_garis():
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    return HorizontalLineChart


class _GrafikGaris(_kelas_garis()):
    pass


class _GrafikArea(_kelas_garis()):
    """Garis + bidang transparan dari titik pertama sampai titik terakhir ke garis nol.

    `inFill` bawaan reportlab menutup bidang sampai UJUNG sumbu (segitiga palsu di kiri-kanan),
    jadi bidangnya digambar sendiri dari posisi titik yang sudah dihitung grafik."""

    def makeLines(self):
        from reportlab.graphics.shapes import Group, Polygon
        g = Group()
        nol = self.valueAxis.scale(0 if (self.valueAxis._valueMin or 0) <= 0 else self.valueAxis._valueMin)
        for i, row in enumerate(self._positions):
            titik = [(px, py) for px, py in row if py is not None]
            if len(titik) < 2:
                continue
            pts = [titik[0][0], nol]
            for px, py in titik:
                pts += [px, py]
            pts += [titik[-1][0], nol]
            g.add(Polygon(pts, fillColor=_warna(PALET[i % len(PALET)], 0.16), strokeColor=None, strokeWidth=0))
        g.add(super().makeLines())
        return g


def _skala(ax, lo: float, hi: float):
    """Sumbu nilai berawal di nol (atau minimum negatif) dan berakhir di angka bulat ("ceiling")."""
    ax.valueMin = lo
    ax.valueMax = None if hi > 0 else hi
    ax.rangeRound = "ceiling"
    ax.avoidBoundFrac = 0
    ax.forceZero = 1


def gambar_grafik(spec: dict, lebar: float = 520, tinggi: float = 210):
    """Spesifikasi grafik (sudah divalidasi) → `Drawing` reportlab."""
    from reportlab.graphics.shapes import Drawing, String

    jenis = spec["jenis"]
    seri = spec["seri"]
    x = [teks_pdf(v) for v in spec["x"]]
    satuan = spec.get("satuan") or ""

    def fmt(v):
        return singkat(v, satuan)
    banyak_seri = len(seri) > 1

    if jenis == "pai":
        return _gambar_pai(spec, lebar, tinggi)

    if jenis == "batang_horizontal":
        from reportlab.graphics.charts.barcharts import HorizontalBarChart
        n = len(x) * len(seri)
        tinggi = max(150, min(560, 16 * n + 14 * len(x) + 70))
        kiri = min(150, max(50, 5.2 * max(len(_potong(s, 26)) for s in x) + 10))
        d = Drawing(lebar, tinggi)
        ch = HorizontalBarChart()
        ch.x, ch.y = kiri, 40 if banyak_seri else 26
        ch.width, ch.height = lebar - kiri - 20, tinggi - ch.y - 12
        ch.data = [[(v if v is not None else 0) for v in reversed(s["nilai"])] for s in seri]
        ch.categoryAxis.categoryNames = [_potong(s, 26) for s in reversed(x)]
        _gaya_sumbu(ch.categoryAxis, nilai=False)
        _gaya_sumbu(ch.valueAxis, nilai=True)
        ch.valueAxis.labelTextFormat = fmt
        lo, hi = _rentang(seri)
        _skala(ch.valueAxis, lo, hi)
        ch.barSpacing, ch.groupSpacing = 1.5, 6
        for i in range(len(seri)):
            ch.bars[i].fillColor = _warna(PALET[i])
            ch.bars[i].strokeColor = None
        ch.categoryAxis.labels.boxAnchor = "e"
        ch.categoryAxis.labels.dx = -4
        d.add(ch)
        if banyak_seri:
            d.add(_legenda([s["nama"] for s in seri], kiri, 4, lebar - kiri))
        return d

    d = Drawing(lebar, tinggi)
    # label sumbu x diputar hanya bila tidak muat mendatar (lebar huruf Helvetica 7 pt ≈ 3,9 pt)
    lebar_kat = (lebar - 68) / max(1, len(x))
    putar = max(len(_potong(s, 18)) for s in x) * 3.9 > lebar_kat - 4
    bawah = (58 if putar else 30) + (16 if banyak_seri else 0)
    if jenis == "batang":
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        ch = VerticalBarChart()
        ch.data = [[(v if v is not None else 0) for v in s["nilai"]] for s in seri]
        for i in range(len(seri)):
            ch.bars[i].fillColor = _warna(PALET[i])
            ch.bars[i].strokeColor = None
        ch.barSpacing, ch.groupSpacing = 1.5, max(4, 40 / max(1, len(x)))
    else:   # garis / area
        from reportlab.graphics.widgets.markers import makeMarker
        ch = _GrafikGaris() if jenis == "garis" else _GrafikArea()
        ch.data = [list(s["nilai"]) for s in seri]
        ch.joinedLines = 1
        for i in range(len(seri)):
            ch.lines[i].strokeColor = _warna(PALET[i])
            ch.lines[i].strokeWidth = 2
            if len(x) <= 16:
                ch.lines[i].symbol = makeMarker("FilledCircle", size=4)
                ch.lines[i].symbol.fillColor = _warna(PALET[i])
                ch.lines[i].symbol.strokeColor = _warna("#ffffff")
                ch.lines[i].symbol.strokeWidth = 0.6
    lo, hi = _rentang(seri)
    ch.x, ch.y = 54, bawah
    ch.width, ch.height = lebar - 54 - 14, tinggi - bawah - 10
    ch.categoryAxis.categoryNames = [_potong(s, 18) for s in x]
    _gaya_sumbu(ch.categoryAxis, nilai=False)
    _gaya_sumbu(ch.valueAxis, nilai=True)
    ch.valueAxis.labelTextFormat = fmt
    _skala(ch.valueAxis, lo, hi)
    if putar:
        ch.categoryAxis.labels.angle = 35
        ch.categoryAxis.labels.boxAnchor = "ne"
        ch.categoryAxis.labels.dx, ch.categoryAxis.labels.dy = 2, -4
    d.add(ch)
    if banyak_seri:
        d.add(_legenda([s["nama"] for s in seri], 54, 4, lebar - 54))
    if not any(v is not None for s in seri for v in s["nilai"]):
        d.add(String(lebar / 2, tinggi / 2, "Tidak ada data", textAnchor="middle",
                     fontName="Helvetica", fontSize=9, fillColor=_warna(TINTA_2)))
    return d


def _gambar_pai(spec: dict, lebar: float, tinggi: float):
    """Pai: paling banyak 8 irisan (sisanya digabung "Lainnya"); keterangan nilai & persen di samping."""
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing

    pasang = list(zip(spec["x"], spec["seri"][0]["nilai"]))
    pasang.sort(key=lambda p: -p[1])
    if len(pasang) > 8:
        # irisan "Lainnya" yang sudah ada ikut digabung, supaya tidak muncul dua kali
        ada = [p for p in pasang if p[0].strip().lower() != "lainnya"]
        sisa = sum(v for n, v in pasang if n.strip().lower() == "lainnya") + sum(v for _, v in ada[7:])
        pasang = ada[:7] + [("Lainnya", sisa)]
    total = sum(v for _, v in pasang) or 1
    satuan = spec.get("satuan") or ""
    d = Drawing(lebar, tinggi)
    p = Pie()
    ukuran = min(tinggi - 30, lebar * 0.42)
    p.x, p.y = 16, (tinggi - ukuran) / 2
    p.width = p.height = ukuran
    p.data = [v for _, v in pasang]
    p.labels = None
    p.simpleLabels = 1
    p.slices.strokeColor = _warna("#ffffff")
    p.slices.strokeWidth = 1.2
    for i in range(len(pasang)):
        p.slices[i].fillColor = _warna(PALET[i])
    d.add(p)
    lg = Legend()
    lg.x, lg.y = p.x + ukuran + 24, tinggi / 2 + 6.5 * len(pasang)
    lg.boxAnchor = "nw"
    lg.alignment = "right"
    lg.fontName, lg.fontSize = "Helvetica", 7.5
    lg.fillColor = _warna(TINTA_2)
    lg.dx, lg.dy, lg.dxTextSpace = 8, 8, 5
    lg.deltay = 13
    lg.columnMaximum = 8
    lg.strokeWidth = 0
    lg.colorNamePairs = [
        (_warna(PALET[i]),
         teks_pdf(f"{_potong(str(n), 30)} — {singkat(v, satuan)} ({format_persen(v / total * 100)})"))
        for i, (n, v) in enumerate(pasang)]
    d.add(lg)
    return d


# ═══════════════════════════════════════════════════════════════════════════════
# KOP SURAT
# ═══════════════════════════════════════════════════════════════════════════════
def kop_bawaan(cv: str = "DA") -> dict:
    """Kop tanpa basis data (uji / cadangan bila template gagal dibaca)."""
    from core.pdf_template import DEFAULT_FOOTER, DEFAULT_HEADER, DEFAULT_TABLE
    nama = NAMA_GABUNGAN if cv == "ALL" else ("CV Sukma Mitra Utama" if cv == "SMU" else "CV. Dewi Aditya")
    return {"cv": cv, "cv_label": label_cv(cv), "header": dict(DEFAULT_HEADER), "footer": dict(DEFAULT_FOOTER),
            "table": dict(DEFAULT_TABLE),
            "profile": {"entity": cv if cv in ("DA", "SMU") else "ALL", "company_name": nama}}


async def siapkan_kop(db, cv: str) -> dict:
    """Template PDF pemilik (kop/footer/gaya tabel GLOBAL) + profil CV. ALL = kop netral dua CV tanpa logo."""
    from core.pdf_template import company_profile, resolve
    kop = kop_bawaan(cv)
    try:
        tpl = await resolve(db, DOC_KEY)
        kop.update({"header": tpl.get("header") or kop["header"], "footer": tpl.get("footer") or kop["footer"],
                    "table": tpl.get("table") or kop["table"]})
    except Exception as e:  # noqa: BLE001 — kop rusak tidak boleh menggagalkan laporan
        log.warning("[laporan-ai] template PDF tidak terbaca, memakai bawaan: %s", e)
    if cv == "ALL":
        # effective_header_text: profil selain DA dipakai apa adanya dan logo template DA tidak dipakai.
        kop["profile"] = {"entity": "ALL", "company_name": NAMA_GABUNGAN, "address": "", "phone": "",
                          "email": "", "website": "", "npwp": "", "logo_url": ""}
    else:
        try:
            kop["profile"] = await company_profile(db, cv)
        except Exception as e:  # noqa: BLE001
            log.warning("[laporan-ai] profil CV %s tidak terbaca: %s", cv, e)
    return kop


# ═══════════════════════════════════════════════════════════════════════════════
# PDF
# ═══════════════════════════════════════════════════════════════════════════════
def _gaya_pdf():
    from reportlab.lib.styles import ParagraphStyle
    # `leading` = 1,44 × ukuran font — aturan penjaga tumpang-tindih (INV-F17) yang sama dengan template.
    return {
        "h1": ParagraphStyle("laH1", fontName="Helvetica-Bold", fontSize=11.5, leading=16.6,
                             textColor=_warna(TINTA), spaceBefore=8, spaceAfter=4),
        "h2": ParagraphStyle("laH2", fontName="Helvetica-Bold", fontSize=10, leading=14.4,
                             textColor=_warna(TINTA), spaceBefore=6, spaceAfter=3),
        "h3": ParagraphStyle("laH3", fontName="Helvetica-Bold", fontSize=9, leading=13,
                             textColor=_warna(TINTA), spaceBefore=4, spaceAfter=2),
        "p": ParagraphStyle("laP", fontName="Helvetica", fontSize=9, leading=13, textColor=_warna(TINTA),
                            spaceAfter=4),
        "li": ParagraphStyle("laLi", fontName="Helvetica", fontSize=9, leading=13, textColor=_warna(TINTA)),
        "kecil": ParagraphStyle("laKecil", fontName="Helvetica-Oblique", fontSize=7.5, leading=10.8,
                                textColor=_warna(TINTA_2), spaceBefore=2, spaceAfter=6),
        "judul_grafik": ParagraphStyle("laJG", fontName="Helvetica-Bold", fontSize=8.5, leading=12.3,
                                       textColor=_warna(TINTA), spaceBefore=4, spaceAfter=2),
    }


def _md_flowables(md: str, g: dict) -> list:
    from reportlab.platypus import ListFlowable, ListItem, Paragraph
    out = []
    for b in urai_markdown(md):
        if b[0] == "judul":
            out.append(Paragraph(inline_pdf(b[2]), g["h2"] if b[1] <= 2 else g["h3"]))
        elif b[0] == "paragraf":
            out.append(Paragraph(inline_pdf(b[1]), g["p"]))
        else:
            items = [ListItem(Paragraph(inline_pdf(t), g["li"]), leftIndent=14) for t in b[1]]
            if b[0] == "poin":
                out.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=14,
                                        bulletFontSize=8, spaceAfter=4))
            else:
                out.append(ListFlowable(items, bulletType="1", leftIndent=16, bulletFontSize=8.5,
                                        bulletFormat="%s.", spaceAfter=4))
    return out


def _tabel_flowable(tabel: dict, kop: dict, avail: float):
    from routes.operations_pdf_helpers import _pdf_data_table
    jenis = jenis_kolom_tabel(tabel)
    kolom = [teks_pdf(k) for k in tabel["kolom"]]
    if not tabel["baris"]:
        rows = [["Tidak ada data"] + [""] * (len(kolom) - 1)]
    else:
        rows = [[teks_pdf(format_sel(v, jenis[i])) for i, v in enumerate(r)] for r in tabel["baris"]]
    # bobot lebar: teks lebih lebar dari angka; batas atas supaya satu kolom tidak memakan halaman
    bobot = []
    for i, k in enumerate(kolom):
        panjang = max([len(k)] + [len(str(r[i])) for r in rows[:60]])
        bobot.append(max(0.8, min(4.0, panjang / 9)))
    kanan = [i for i, j in enumerate(jenis) if j != "teks"]
    return _pdf_data_table(kolom, rows, weights=bobot, right_cols=kanan, style=kop.get("table"))


def _nomor_halaman(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_warna(TINTA_2))
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 18,
                           f"Laporan Asisten AI · Halaman {canvas.getPageNumber()}")
    canvas.restoreState()


def buat_pdf(spec: dict, kop: dict, *, dibuat: Optional[datetime] = None, pembuat: str = "") -> bytes:
    """Spesifikasi (sudah divalidasi) + kop → bytes PDF A4 potret."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

    from core.pdf_template import CONTENT_W_PORTRAIT, footer_flowables, header_flowables
    g = _gaya_pdf()
    avail = CONTENT_W_PORTRAIT
    info = [("Periode", spec.get("periode_label") or "-"), ("CV", kop.get("cv_label") or label_cv(kop.get("cv"))),
            ("Dibuat", tanggal_wib(dibuat)), ("Oleh", f"{pembuat or '-'} lewat Asisten AI")]
    el = header_flowables(kop.get("header"), kop.get("profile"), teks_pdf(spec["judul"]),
                          subtitle=teks_pdf(spec.get("subjudul") or ""),
                          info_pairs=[(a, teks_pdf(b)) for a, b in info], avail=avail)
    for b in spec["bagian"]:
        # Satuan isi (daftar flowable). Satuan pertama disatukan dengan judul bagian supaya judul tidak
        # tertinggal sendirian di dasar halaman; KeepTogether TIDAK bersarang (bersarang = loncat halaman).
        satuan = []
        if b.get("teks"):
            satuan.extend([f] for f in _md_flowables(b["teks"], g))
        if b.get("tabel"):
            tb = [Spacer(1, 1.5 * mm), _tabel_flowable(b["tabel"], kop, avail)]
            tb.append(Paragraph(_esc(b["tabel"]["catatan"]), g["kecil"]) if b["tabel"].get("catatan")
                      else Spacer(1, 3 * mm))
            satuan.append(tb)
        if b.get("grafik"):
            gr = b["grafik"]
            blok = []
            if gr.get("judul"):
                blok.append(Paragraph(_esc(gr["judul"]) + (f" ({_esc(gr['satuan'])})" if gr.get("satuan") else ""),
                                      g["judul_grafik"]))
            blok.append(gambar_grafik(gr, lebar=avail))
            if gr.get("catatan"):
                blok.append(Paragraph(_esc(gr["catatan"]), g["kecil"]))
            blok.append(Spacer(1, 3 * mm))
            satuan.append(blok)
        if b.get("judul"):
            satuan[0] = [Paragraph(inline_pdf(b["judul"]), g["h1"])] + satuan[0]
        for s in satuan:
            # tabel panjang boleh terpotong antarhalaman (baris kepala diulang); blok lain dijaga utuh
            panjang = any(getattr(f, "_cellvalues", None) is not None and len(f._cellvalues) > 25 for f in s)
            if len(s) == 1 or panjang:
                el.extend(s)
            else:
                el.append(KeepTogether(s))
    el.append(Spacer(1, 4 * mm))
    el.append(Paragraph("Laporan ini disusun Asisten AI dari data sistem sesuai hak akses pembuatnya. "
                        "Periksa kembali angka penting sebelum dipakai untuk keputusan.", g["kecil"]))
    el.extend(footer_flowables(kop.get("footer"), kop.get("profile")))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=teks_pdf(spec["judul"]), author="Asisten AI DAHOST",
                            subject=teks_pdf(spec.get("subjudul") or ""))
    doc.build(el, onFirstPage=_nomor_halaman, onLaterPages=_nomor_halaman)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# EXCEL
# ═══════════════════════════════════════════════════════════════════════════════
FMT_RP = '"Rp" #,##0;[Red]-"Rp" #,##0;"-"'
FMT_PERSEN = '0.0"%"'
FMT_BULAT = '#,##0'
FMT_DESIMAL = '#,##0.00'
_HURUF_LEMBAR_TERLARANG = re.compile(r"[\[\]:*?/\\]")


def _nama_lembar(nama: str, terpakai: set) -> str:
    dasar = _HURUF_LEMBAR_TERLARANG.sub(" ", nama).strip().strip("'")
    if len(dasar) > 28:      # potong di batas kata (nama lembar Excel maks 31 karakter)
        dasar = (dasar[:28].rsplit(" ", 1)[0] if " " in dasar[:28] else dasar[:28]).rstrip()
    dasar = dasar or "Tabel"
    kandidat, n = dasar, 2
    while kandidat.lower() in terpakai:
        kandidat = f"{dasar[:25]} {n}"
        n += 1
    terpakai.add(kandidat.lower())
    return kandidat


def _isi_sel(cell, v):
    if isinstance(v, str) and v.startswith("="):
        cell.value = v
        cell.data_type = "s"     # teks dari model/web tidak boleh menjadi rumus Excel
    else:
        cell.value = v


def format_angka_excel(jenis: str, nilai: list) -> Optional[str]:
    if jenis == "rp":
        return FMT_RP
    if jenis == "persen":
        return FMT_PERSEN
    if jenis == "angka":
        bulat = all(float(v).is_integer() for v in nilai if isinstance(v, (int, float)))
        return FMT_BULAT if bulat else FMT_DESIMAL
    return None


def buat_xlsx(spec: dict, kop: dict, *, dibuat: Optional[datetime] = None, pembuat: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import AreaChart, BarChart, LineChart, PieChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Ringkasan"
    terpakai = {"ringkasan"}
    tebal = Font(bold=True)
    kepala = Font(bold=True, color="FFFFFF")
    isi_kepala = PatternFill("solid", fgColor="334155")
    bungkus = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 110
    baris = 1

    def tulis(teks, font=None):
        nonlocal baris
        c = ws.cell(row=baris, column=1)
        _isi_sel(c, teks)
        c.alignment = bungkus
        if font:
            c.font = font
        baris += 1

    tulis(spec["judul"], Font(bold=True, size=14))
    if spec.get("subjudul"):
        tulis(spec["subjudul"], Font(italic=True, color="52514E"))
    tulis(f"CV: {kop.get('cv_label') or label_cv(kop.get('cv'))}")
    if spec.get("periode_label"):
        tulis(f"Periode: {spec['periode_label']}")
    tulis(f"Dibuat: {tanggal_wib(dibuat)} oleh {pembuat or '-'} lewat Asisten AI")
    baris += 1
    daftar_lembar = []
    for i, b in enumerate(spec["bagian"]):
        if b.get("judul"):
            tulis(teks_polos(b["judul"]), Font(bold=True, size=12))
        for blk in urai_markdown(b.get("teks") or ""):
            if blk[0] == "judul":
                tulis(teks_polos(blk[2]), tebal)
            elif blk[0] == "paragraf":
                tulis(teks_polos(blk[1]))
            else:
                for n, t in enumerate(blk[1], 1):
                    tulis(("• " if blk[0] == "poin" else f"{n}. ") + teks_polos(t))
        nama_dasar = b.get("judul") or f"Bagian {i + 1}"
        if b.get("tabel"):
            t = b["tabel"]
            nama = _nama_lembar(t.get("judul") or nama_dasar, terpakai)
            daftar_lembar.append(nama)
            tulis(f"Tabel: lihat lembar \"{nama}\".", Font(italic=True, color="52514E"))
            wt = wb.create_sheet(nama)
            jenis = jenis_kolom_tabel(t)
            for j, k in enumerate(t["kolom"], 1):
                c = wt.cell(row=1, column=j, value=k)
                c.font, c.fill = kepala, isi_kepala
                c.alignment = Alignment(wrap_text=True, vertical="center",
                                        horizontal="right" if jenis[j - 1] != "teks" else "left")
            for r_i, r in enumerate(t["baris"], 2):
                for j, v in enumerate(r, 1):
                    c = wt.cell(row=r_i, column=j)
                    _isi_sel(c, v if v != "" else None)
                    fmt = format_angka_excel(jenis[j - 1], [x[j - 1] for x in t["baris"]])
                    if fmt and isinstance(v, (int, float)):
                        c.number_format = fmt
            for j, k in enumerate(t["kolom"], 1):
                panjang = max([len(k)] + [len(format_sel(r[j - 1], jenis[j - 1])) for r in t["baris"][:200]])
                wt.column_dimensions[get_column_letter(j)].width = max(10, min(50, panjang + 2))
            wt.freeze_panes = "A2"
            if t["baris"]:
                wt.auto_filter.ref = f"A1:{get_column_letter(len(t['kolom']))}{len(t['baris']) + 1}"
            if t.get("catatan"):
                wt.cell(row=len(t["baris"]) + 3, column=1, value=t["catatan"]).font = Font(italic=True)
        if b.get("grafik"):
            gr = b["grafik"]
            nama = _nama_lembar(f"Grafik {gr.get('judul') or nama_dasar}", terpakai)
            daftar_lembar.append(nama)
            tulis(f"Grafik: data dan grafik di lembar \"{nama}\".", Font(italic=True, color="52514E"))
            wg = wb.create_sheet(nama)
            wg.cell(row=1, column=1, value="Label").font = tebal
            for j, s in enumerate(gr["seri"], 2):
                wg.cell(row=1, column=j, value=s["nama"]).font = tebal
            for r_i, lbl in enumerate(gr["x"], 2):
                _isi_sel(wg.cell(row=r_i, column=1), lbl)
                for j, s in enumerate(gr["seri"], 2):
                    c = wg.cell(row=r_i, column=j, value=s["nilai"][r_i - 2])
                    c.number_format = FMT_RP if (gr.get("satuan") or "").lower() == "rp" else (
                        FMT_PERSEN if gr.get("satuan") == "%" else FMT_BULAT)
            wg.column_dimensions["A"].width = 28
            for j in range(2, len(gr["seri"]) + 2):
                wg.column_dimensions[get_column_letter(j)].width = 18
            n = len(gr["x"])
            data = Reference(wg, min_col=2, max_col=len(gr["seri"]) + 1, min_row=1, max_row=n + 1)
            cats = Reference(wg, min_col=1, min_row=2, max_row=n + 1)
            if gr["jenis"] == "pai":
                chart = PieChart()
            elif gr["jenis"] == "garis":
                chart = LineChart()
            elif gr["jenis"] == "area":
                chart = AreaChart()
                chart.grouping = "standard"
            else:
                chart = BarChart()
                chart.type = "bar" if gr["jenis"] == "batang_horizontal" else "col"
            chart.title = gr.get("judul") or None
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(cats)
            chart.width, chart.height = 22, 11
            wg.add_chart(chart, f"{get_column_letter(len(gr['seri']) + 3)}2")
        baris += 1
    if daftar_lembar:
        baris += 1
        tulis("Lembar lain di berkas ini: " + ", ".join(daftar_lembar), Font(italic=True, color="52514E"))
    tulis("Laporan ini disusun Asisten AI dari data sistem sesuai hak akses pembuatnya. "
          "Periksa kembali angka penting sebelum dipakai untuk keputusan.", Font(italic=True, color="52514E"))
    wb.properties.title = spec["judul"]
    wb.properties.creator = "Asisten AI DAHOST"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# SIMPAN, BACA, HAK UNDUH
# ═══════════════════════════════════════════════════════════════════════════════
def nama_berkas(judul: str, fmt: str, dibuat: Optional[datetime] = None) -> str:
    from utils.waktu import now_wib, to_wib
    w = to_wib(dibuat) if dibuat else now_wib()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", judul).strip("-")[:60] or "Laporan"
    return f"{slug}-{w.strftime('%Y%m%d')}.{fmt}"


def url_unduh(laporan_id: str, fmt: str) -> str:
    return f"/api/asisten-ai/laporan/{laporan_id}?format={fmt}"


def boleh_unduh(user: dict, doc: dict) -> bool:
    """Hanya pembuat laporan, ditambah owner/superadmin."""
    role = (user.get("role") or "").lower()
    return bool(doc) and (role in PERAN_UNDUH_SEMUA or (user.get("id") and user.get("id") == doc.get("dibuat_oleh")))


async def buat_dan_simpan(db, spec_mentah: dict, *, user: dict, cv: str, sesi_id: Optional[str] = None,
                          put_object=None) -> dict:
    """Validasi → buat berkas → simpan berkas + metadata. Mengembalikan dokumen `ai_reports` (tanpa _id)."""
    spec = validasi_spek(spec_mentah)
    cv = cv if cv in ("DA", "SMU", "ALL") else "DA"
    if put_object is None:
        from object_storage import put_object
    kop = await siapkan_kop(db, cv)
    sekarang = datetime.now(timezone.utc)
    pembuat = user.get("name") or user.get("email") or ""
    laporan_id = str(uuid.uuid4())
    berkas = []
    for fmt in spec["format"]:
        pembuat_berkas = buat_pdf if fmt == "pdf" else buat_xlsx
        data = await asyncio.to_thread(pembuat_berkas, spec, kop, dibuat=sekarang, pembuat=pembuat)
        if len(data) > MAKS_UKURAN_BERKAS:
            raise SpekLaporanError("Berkas laporan terlalu besar. Kurangi jumlah tabel atau baris.")
        path = f"ai_reports/{laporan_id}/{secrets.token_hex(16)}.{fmt}"
        res = await asyncio.to_thread(put_object, path, data, CONTENT_TYPE[fmt])
        berkas.append({"format": fmt, "path": (res or {}).get("path") or path, "ukuran": len(data),
                       "nama_berkas": nama_berkas(spec["judul"], fmt, sekarang),
                       "url": url_unduh(laporan_id, fmt)})
    doc = {
        "id": laporan_id, "judul": spec["judul"], "subjudul": spec["subjudul"],
        "periode_label": spec["periode_label"], "cv": cv, "format": spec["format"], "berkas": berkas,
        "jumlah_bagian": len(spec["bagian"]), "spec": spec,
        "dibuat_oleh": user.get("id"), "dibuat_oleh_nama": pembuat, "peran": user.get("role") or "",
        "sesi_id": sesi_id, "created_at": sekarang,
    }
    await db[COLL].insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


def berkas_dari(doc: dict, fmt: Optional[str]) -> Optional[dict]:
    daftar = doc.get("berkas") or []
    if not fmt:
        return daftar[0] if daftar else None
    return next((b for b in daftar if b.get("format") == fmt), None)


def ringkas_untuk_ui(doc: dict) -> list:
    """Event `laporan` Kontrak B per berkas: {id, judul, format, url}."""
    return [{"id": doc["id"], "judul": doc["judul"], "format": b["format"], "url": b["url"]}
            for b in doc.get("berkas") or []]
