"""SSOT gambar label barcode — bahan (90×50 mm) & barang jadi (100×70 mm).

FASE H-3 (2026-08-16). Kenapa berkas ini ada — bukan kerapian:

1. Label bahan digambar DUA KALI dengan kode terpisah di `wms_material_labels.py`
   (sekali untuk PDF satu label, sekali lagi di dalam perulangan batch), dan hal
   yang sama berlaku untuk FG. Menu "Buat Barcode" akan menjadi definisi KETIGA.
   Dua definisi untuk satu label = dua cara sebuah kolom bisa hilang dari kertas
   tanpa ada yang tahu.

2. DUA CACAT NYATA yang ditemukan saat menulis ini dan ditutup di sini:
   * Batch label bahan memakai `COLS = 3` × 90 mm = **270 mm** pada A4 yang
     lebarnya **210 mm** ⇒ `MARGIN_X` NEGATIF dan kolom ketiga tercetak DI LUAR
     halaman (label ketiga hilang di setiap baris). Sekarang jumlah kolom/baris
     DIHITUNG dari ukuran halaman (`grid_geometry`) sehingga label mustahil
     keluar kertas — pelajaran yang sama dengan Fase F (lebar tabel PDF hardcode).
   * Satuan dibaca dari `material['uom']`. Field itu **TIDAK ADA** di
     `rahaza_materials` (namanya `unit`) ⇒ SEMUA label bahan mencetak "pcs",
     termasuk kain yang satuannya kg. Label yang salah satuan membuat orang
     gudang menimbang/menghitung barang dengan angka yang salah.

Nilai barcode SELALU kode master (`code`/`sku`). Tidak ada jalan mengetik kode
bebas: label yang kodenya dikarang akan discan menjadi item yang tidak ada.

PAKET 3a (2026-11-02) — SATU generator barcode untuk semua label gudang
(barang jadi, bahan, posisi rak/bin, roll kain). Yang ditutup:
  * Bin (`wms_labels.py`) dan roll (`wms_fabric_rolls.py`) punya generator Code128
    sendiri-sendiri. Sekarang ketiganya memakai `draw_code128()` di berkas ini.
  * Barcode dulu digambar sebagai PNG 300 dpi lalu DIPERKECIL/DIPERBESAR bebas
    ke kotak label ⇒ lebar modul jadi pecahan titik printer. Uji decode per label
    (rasterisasi 203 dpi = printer thermal umum, zxing-cpp): kode bahan terpanjang
    `CUT-DA-1101-BRG-ALLSIZE` 0/10 terbaca, kode posisi 25 karakter 0/24. Sekarang
    batang digambar VEKTOR (reportlab), X dipilih dari tangga titik printer
    (`X_STEPS_MM`), quiet zone 10X kiri-kanan, teks manusia di bawahnya → bahan
    10/10; posisi 25 karakter 10/24 (batas fisik label 65 mm — pakai kode rak pendek).
  * `code_of()` dulu mengembalikan "N/A" untuk dokumen tanpa kode ⇒ label
    ber-barcode "N/A" tercetak. Sekarang kode kosong/tak didukung Code128
    DITOLAK (`LabelCodeError`) sebelum PDF dibuat.

KEPUTUSAN BARCODE OWNER (2026-11-02):
  * Hangtag kecil barang jadi 70×40 mm (`fg_hangtag`) — pilihan ukuran di layar Buat Barcode.
    Batang dibuat hampir selebar label supaya SKU 19 karakter (264 modul) tetap X = 0,25 mm.
  * QR label barang jadi = SKU POLOS (bukan JSON). Resolver tetap menerima QR JSON label lama.
  * Label aset (`asset` 90×50, `asset_small` 50×25) — SATU generator untuk Portal Aset & Keuangan ›
    Aset Tetap; kode = kode registri induk `rahaza_fixed_assets.code` (`asset_label_doc`).
"""
from __future__ import annotations

import io
import logging

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.graphics.barcode.code128 import Code128 as _RLCode128
    import qrcode
    from PIL import Image as PILImage
    LABELS_OK = True
except ImportError:  # pragma: no cover — lingkungan tanpa reportlab
    LABELS_OK = False
    mm = 72 / 25.4
    A4 = (595.27, 841.89)

log = logging.getLogger(__name__)

MATERIAL_LABEL_MM = (90.0, 50.0)
FG_LABEL_MM = (100.0, 70.0)
FG_HANGTAG_MM = (70.0, 40.0)     # 2026-11-02: hangtag kecil barang jadi
ASSET_LABEL_MM = (90.0, 50.0)    # 2026-11-02: label aset (registri induk)
ASSET_SMALL_MM = (50.0, 25.0)    # 2026-11-02: stiker aset kecil
BIN_LABEL_MM = (65.0, 33.0)      # label posisi rak (dulu di wms_labels.py)
ROLL_LABEL_MM = (90.0, 50.0)     # label roll kain (dulu di wms_fabric_rolls.py)
# Grid tetap untuk label bin: lembar A4 3×8 (perilaku lama wms_labels) —
# jenis lain dihitung dari ukuran halaman (`grid_geometry`).
# 2026-11-02: hangtag 70 mm × 3 kolom = 210 mm → tanpa margin (batang kolom tepi terpotong printer);
# dibatasi 2 kolom × 7 baris supaya tepi kertas selalu bermargin.
FIXED_GRID = {"bin": (3, 8), "fg_hangtag": (2, 7)}

# Code128: lebar modul (X) dan quiet zone. X dipilih dari TANGGA yang pas dengan titik
# printer: 0,375 mm = 3 titik @203 dpi; 0,25 mm = 2 titik @203 dpi ≈ 3 titik @300 dpi.
# Lebar modul pecahan titik (mis. 0,27 mm = 2,2 titik) membuat batang 2/3 titik
# bergantian → uji decode 203 dpi gagal. Bila tidak ada anak tangga yang muat, X
# mengikuti ruang (kode sangat panjang) dan diberi peringatan di bawah 0,19 mm.
X_STEPS_MM = (0.375, 0.25)
X_MAX_MM = X_STEPS_MM[0]
X_WARN_MM = 0.19
QUIET_MODULES = 10
MAX_CODE_LEN = 40


class LabelCodeError(ValueError):
    """Kode yang tidak boleh dijadikan barcode (kosong / di luar ASCII cetak / terlalu panjang)."""


def label_size(kind: str):
    return {"fg": FG_LABEL_MM, "fg_hangtag": FG_HANGTAG_MM, "bin": BIN_LABEL_MM, "roll": ROLL_LABEL_MM,
            "asset": ASSET_LABEL_MM, "asset_small": ASSET_SMALL_MM}.get(kind, MATERIAL_LABEL_MM)


def grid_geometry(page_w: float, page_h: float, lw: float, lh: float):
    """Kolom/baris yang BENAR-BENAR muat di halaman + margin terpusat.

    Dihitung, tidak dihardcode: label yang tidak muat = label yang hilang.
    """
    cols = max(1, int(page_w // lw))
    rows = max(1, int(page_h // lh))
    return cols, rows, (page_w - cols * lw) / 2, (page_h - rows * lh) / 2


def validate_code(code) -> str:
    """Kode yang sah untuk Code128 set B: ASCII cetak (spasi..~), tanpa spasi tepi.

    Mengembalikan kode itu sendiri; melempar `LabelCodeError` bila tidak sah."""
    c = "" if code is None else str(code)
    if not c.strip():
        raise LabelCodeError("kode kosong")
    if c != c.strip():
        raise LabelCodeError(f"kode {c!r} diawali/diakhiri spasi")
    bad = sorted({ch for ch in c if not (" " <= ch <= "~")})
    if bad:
        raise LabelCodeError(f"kode {c!r} memuat karakter yang tidak didukung Code128: {bad}")
    if len(c) > MAX_CODE_LEN:
        raise LabelCodeError(f"kode {c!r} terlalu panjang ({len(c)} > {MAX_CODE_LEN} karakter)")
    return c


def code128_modules(code: str) -> int:
    """Jumlah modul batang Code128 (tanpa quiet zone) — encoder yang sama dengan label."""
    b = _RLCode128(code, barWidth=1, quiet=False)
    return int(round(b.width))


def code128_x_mm(code: str, avail_w_mm: float) -> float:
    """Lebar modul X (mm) bila kode digambar di ruang selebar `avail_w_mm` (termasuk quiet zone)."""
    fit = avail_w_mm / (code128_modules(code) + 2 * QUIET_MODULES)
    for step in X_STEPS_MM:
        if step <= fit + 1e-9:
            return step
    return fit


def draw_code128(c, code: str, x: float, y: float, w: float, h: float, *,
                 text: bool = True, font_size: float = 7, align: str = "left") -> float:
    """Gambar Code128 VEKTOR di kotak (x, y, w, h) — quiet zone 10X ada DI DALAM kotak.

    Mengembalikan X (mm) yang dipakai. Teks manusia (kode yang sama) di bawah batang.
    """
    code = validate_code(code)
    x_mm = code128_x_mm(code, w / mm)
    bw = x_mm * mm
    text_h = (font_size + 1.5) if text else 0
    bar_h = max(4 * mm, h - text_h)
    bc = _RLCode128(code, barWidth=bw, barHeight=bar_h, quiet=True,
                    lquiet=QUIET_MODULES * bw, rquiet=QUIET_MODULES * bw)
    total_w = bc.width
    x0 = x + (w - total_w) / 2 if align == "center" else x
    bc.drawOn(c, x0, y + text_h)
    if text:
        c.setFont("Helvetica", font_size)
        c.drawCentredString(x0 + total_w / 2, y + 0.6, _clip(c, code, "Helvetica", font_size, w))
    if x_mm < X_WARN_MM:
        log.warning("Barcode %s: lebar modul %.3f mm < %.2f mm (kode terlalu panjang untuk label)",
                    code, x_mm, X_WARN_MM)
    return x_mm


def qr_png(payload: str) -> io.BytesIO:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, "PNG")
    buf.seek(0)
    return buf


def _png_reader(buf: io.BytesIO) -> "ImageReader":
    img = PILImage.open(buf)
    out = io.BytesIO()
    img.save(out, "PNG")
    out.seek(0)
    return ImageReader(out)


def _clip(c, text: str, font: str, size: float, max_w: float) -> str:
    """Potong teks agar tidak menabrak tepi label (bukan hitungan huruf kasar)."""
    text = str(text or "")
    if not text:
        return ""
    if c.stringWidth(text, font, size) <= max_w:
        return text
    while text and c.stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return text + "…"


def unit_of(mat: dict) -> str:
    """Satuan dasar item. `rahaza_materials` memakai `unit`; `uom` hanya alias."""
    return str(mat.get("unit") or mat.get("uom") or "pcs")


def code_of(doc: dict, kind: str = "") -> str:
    """Nilai barcode sebuah label. Kosong bila dokumen tidak punya kode (TIDAK lagi "N/A")."""
    if kind == "bin":
        return str(doc.get("barcode") or "")
    if kind == "roll":
        return str(doc.get("roll_no") or "")
    if kind in ("asset", "asset_small"):
        return str(doc.get("label_code") or "")
    return str(doc.get("code") or doc.get("sku") or doc.get("sku_code")
               or doc.get("material_code") or "")


def check_codes(kind: str, docs) -> None:
    """Tolak SEBELUM menggambar: satu kode salah = tidak ada PDF yang setengah benar."""
    check_codes_mixed((kind, d) for d in docs)


def check_codes_mixed(entries) -> None:
    """`check_codes` untuk daftar campuran `(jenis, dokumen)` — mis. label bahan + label roll kain (10 Nov 2026)."""
    bad = []
    for kind, d in entries:
        try:
            validate_code(code_of(d, kind))
        except LabelCodeError as e:
            bad.append(f"{d.get('name') or d.get('label') or d.get('id') or '?'}: {e}")
    if bad:
        uniq = list(dict.fromkeys(bad))
        raise LabelCodeError("Label tidak dicetak — " + "; ".join(uniq[:10]))


def _draw_barcode(c, code, x, y, w, h, fallback_font=("Courier", 6), align="left"):
    try:
        draw_code128(c, code, x, y, w, h, align=align)
    except Exception as e:  # noqa: BLE001
        log.warning("Barcode gagal untuk %s: %s", code, e)
        c.setFont(*fallback_font)
        c.drawString(x, y + h / 2, str(code))


def draw_material_label(c, x, y, w, h, mat: dict, include_stock: bool = True,
                        border: bool = True):
    """Label bahan/aksesoris. Semua koordinat relatif (x, y) sudut kiri-bawah."""
    pad = 3 * mm
    inner = w - 2 * pad
    if border:
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.4)
        c.rect(x, y, w, h, stroke=1, fill=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)

    code = code_of(mat)
    unit = unit_of(mat)
    category = (mat.get("category") or mat.get("type") or "MATERIAL") or "MATERIAL"

    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + pad, y + h - 7 * mm, "CV. DEWI ADITYA")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + pad, y + h - 12 * mm, f"KODE: {_clip(c, code, 'Helvetica-Bold', 9, inner - 14 * mm)}")
    c.setFont("Helvetica", 7)
    c.drawString(x + pad, y + h - 17 * mm, _clip(c, mat.get("name") or "", "Helvetica", 7, inner))
    c.setFont("Helvetica", 6)
    c.drawString(x + pad, y + h - 21.5 * mm,
                 _clip(c, f"{str(category).upper()} · satuan: {unit}", "Helvetica", 6, inner))
    if include_stock and mat.get("stock_qty") is not None:
        c.drawString(x + pad, y + h - 25.5 * mm, _clip(
            c, f"Stok: {float(mat.get('stock_qty') or 0):,.2f} {unit} @ {mat.get('location') or '-'}",
            "Helvetica", 6, inner))
    _draw_barcode(c, code, x + pad, y + 4 * mm, inner, 16 * mm)


def draw_fg_label(c, x, y, w, h, fg: dict, border: bool = True):
    """Label barang jadi (SKU + QR + barcode)."""
    pad = 3 * mm
    inner = w - 2 * pad
    if border:
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.4)
        c.rect(x, y, w, h, stroke=1, fill=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)

    sku = code_of(fg)
    name = fg.get("product_name") or fg.get("name") or ""
    style = fg.get("style_code") or fg.get("model_code") or fg.get("model_name") or "-"
    color = fg.get("color_name") or fg.get("color") or "-"
    size = fg.get("size_code") or fg.get("size") or "-"

    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + pad, y + h - 8 * mm, "CV. DEWI ADITYA")
    c.setFont("Helvetica", 7)
    c.drawString(x + pad, y + h - 12.5 * mm, "BARANG JADI")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x + pad, y + h - 19 * mm, f"SKU: {_clip(c, sku, 'Helvetica-Bold', 11, inner - 12 * mm)}")
    c.setFont("Helvetica", 8)
    c.drawString(x + pad, y + h - 25 * mm, _clip(c, name, "Helvetica", 8, inner))
    c.setFont("Helvetica", 7)
    c.drawString(x + pad, y + h - 30 * mm,
                 _clip(c, f"Model: {style} · Warna: {color} · Ukuran: {size}", "Helvetica", 7, inner))
    batch = fg.get("batch_number") or ""
    if batch:
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + pad, y + h - 35 * mm, f"Batch: {batch}")

    qr_side = 22 * mm
    try:
        # 2026-11-02 (keputusan owner): isi QR = SKU POLOS — dulu JSON {type, sku, name, size, color, at}
        # (payload panjang = QR rapat, dan setiap cetak berbeda karena jam). Resolver tetap menerima JSON lama.
        payload = qr_payload_fg(sku)
        c.drawImage(_png_reader(qr_png(payload)), x + pad, y + 3 * mm,
                    width=qr_side, height=qr_side, preserveAspectRatio=True, anchor='sw')
    except Exception as e:  # noqa: BLE001
        log.warning("QR gagal untuk %s: %s", sku, e)
        qr_side = 0
    bx = x + pad + (qr_side + 3 * mm if qr_side else 0)
    _draw_barcode(c, sku, bx, y + 5 * mm, x + w - pad - bx, 18 * mm)


def qr_payload_fg(sku: str) -> str:
    """Isi QR label barang jadi = SKU polos (2026-11-02)."""
    return str(sku or "")


def draw_fg_hangtag(c, x, y, w, h, fg: dict, border: bool = True):
    """Hangtag kecil barang jadi (±70×40 mm): teks + QR (SKU polos) di atas, Code128 SKU selebar label."""
    pad = 2.5 * mm
    if border:
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.4)
        c.rect(x, y, w, h, stroke=1, fill=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    sku = code_of(fg)
    name = fg.get("product_name") or fg.get("name") or ""
    color = fg.get("color_name") or fg.get("color") or "-"
    size = fg.get("size_code") or fg.get("size") or "-"
    qr_side = 15 * mm
    text_w = w - 2 * pad - qr_side - 1.5 * mm
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x + pad, y + h - 5 * mm, "CV. DEWI ADITYA")
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + pad, y + h - 9.5 * mm, _clip(c, sku, "Helvetica-Bold", 8.5, text_w))
    c.setFont("Helvetica", 6.5)
    c.drawString(x + pad, y + h - 13.5 * mm, _clip(c, name, "Helvetica", 6.5, text_w))
    c.drawString(x + pad, y + h - 17 * mm, _clip(c, f"Warna: {color} · Ukuran: {size}", "Helvetica", 6.5, text_w))
    try:
        c.drawImage(_png_reader(qr_png(qr_payload_fg(sku))), x + w - pad - qr_side, y + h - 1.5 * mm - qr_side,
                    width=qr_side, height=qr_side, preserveAspectRatio=True, anchor="sw")
    except Exception as e:  # noqa: BLE001
        log.warning("QR hangtag gagal untuk %s: %s", sku, e)
    # Batang hampir selebar label (quiet zone 10X di dalam kotak): SKU 19 karakter = 264 modul
    # → X 0,25 mm (2 titik @203 dpi) baru muat bila kotak ≥ 66 mm.
    _draw_barcode(c, sku, x + 1 * mm, y + 1.5 * mm, w - 2 * mm, 20 * mm, align="center")


def draw_asset_label(c, x, y, w, h, a: dict, border: bool = True):
    """Label aset — kode registri induk (Keuangan › Aset Tetap). `asset_small` = stiker 50×25."""
    small = w < 60 * mm
    pad = (1.5 if small else 3) * mm
    inner = w - 2 * pad
    if border:
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.4)
        c.rect(x, y, w, h, stroke=1, fill=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    code = code_of(a, "asset")
    if small:
        c.setFont("Helvetica-Bold", 6)
        c.drawString(x + pad, y + h - 3.5 * mm, _clip(c, a.get("name") or "", "Helvetica-Bold", 6, inner))
        _draw_barcode(c, code, x + 0.5 * mm, y + 1 * mm, w - 1 * mm, h - 6 * mm, align="center")
        return
    qr_side = 18 * mm
    text_w = inner - qr_side - 2 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + pad, y + h - 6 * mm, "CV. DEWI ADITYA · ASET")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + pad, y + h - 11 * mm, _clip(c, code, "Helvetica-Bold", 10, text_w))
    c.setFont("Helvetica", 7)
    c.drawString(x + pad, y + h - 15.5 * mm, _clip(c, a.get("name") or "", "Helvetica", 7, text_w))
    c.setFont("Helvetica", 6)
    c.drawString(x + pad, y + h - 19 * mm, _clip(c, f"Kategori: {a.get('category') or '-'}", "Helvetica", 6, text_w))
    c.drawString(x + pad, y + h - 22 * mm, _clip(c, f"Lokasi: {a.get('location') or '-'}", "Helvetica", 6, text_w))
    try:
        c.drawImage(_png_reader(qr_png(code)), x + w - pad - qr_side, y + h - 2 * mm - qr_side,
                    width=qr_side, height=qr_side, preserveAspectRatio=True, anchor="sw")
    except Exception as e:  # noqa: BLE001
        log.warning("QR aset gagal untuk %s: %s", code, e)
    _draw_barcode(c, code, x + pad, y + 2 * mm, inner, 16 * mm, align="center")


async def asset_label_doc(db, *, asset_id: str = "", fixed_asset_id: str = "") -> dict:
    """Data label aset dari REGISTRI INDUK (`rahaza_fixed_assets`) + tampilan operasional tertaut
    (`dewi_assets`). Kode label = `rahaza_fixed_assets.code`. Aset Portal Aset yang BELUM tertaut ke
    registri ditolak (`LabelCodeError`) — tidak ada kode kedua yang dikarang di label."""
    op = None
    if asset_id:
        op = await db.dewi_assets.find_one({"id": asset_id}, {"_id": 0})
        if not op:
            raise LookupError("Aset tidak ditemukan.")
        fixed_asset_id = op.get("fixed_asset_id") or ""
        if not fixed_asset_id:
            raise LabelCodeError(f"Aset {op.get('asset_number')} belum tertaut ke registri Aset Tetap (Keuangan) — "
                                 "tautkan dulu; label aset memakai kode registri induk.")
    fa = await db.rahaza_fixed_assets.find_one({"id": fixed_asset_id}, {"_id": 0}) if fixed_asset_id else None
    if not fa:
        raise LookupError("Aset di registri Aset Tetap tidak ditemukan.")
    if op is None:
        op = await db.dewi_assets.find_one({"fixed_asset_id": fa["id"]}, {"_id": 0}) or {}
    return {"id": fa["id"], "label_code": fa.get("code") or "", "name": op.get("name") or fa.get("name") or "",
            "category": op.get("category_name") or fa.get("category") or "",
            "location": op.get("location") or fa.get("location") or "",
            "asset_number": op.get("asset_number") or "", "operational_id": op.get("id") or ""}


def draw_bin_label(c, x, y, w, h, pos: dict, border: bool = True):
    """Label posisi rak/bin (`wh_positions.barcode`). Dulu digambar di wms_labels.py."""
    if border:
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.4)
        c.rect(x, y, w, h, stroke=1, fill=0)
    pad = 3 * mm
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.setFont("Helvetica-Bold", 8)
    path = " / ".join(str(p) for p in (pos.get("building_code"), pos.get("zone_code"),
                                       pos.get("rack_code")) if p)
    c.drawString(x + pad, y + h - 5 * mm, _clip(c, path, "Helvetica-Bold", 8, w - 2 * pad))
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.45, 0.45, 0.45)
    c.drawString(x + pad, y + h - 9 * mm, _clip(c, pos.get("label") or "", "Helvetica", 7, w - 2 * pad))
    c.setFillColorRGB(0, 0, 0)
    # Batang hampir selebar label (quiet zone 10X ada DI DALAM kotak): kode posisi
    # `GD-ZN-RAK-Sxx-Pyy` panjang (±25 char = 310 modul) — tiap mm menaikkan X.
    _draw_barcode(c, code_of(pos, "bin"), x + 0.5 * mm, y + 1.5 * mm, w - 1 * mm, h - 12 * mm,
                  align="center")


def draw_roll_label(c, x, y, w, h, roll: dict, border: bool = True):
    """Label roll kain (`wh_fabric_rolls.roll_no`). Dulu digambar di wms_fabric_rolls.py."""
    pad = 3 * mm
    inner = w - 2 * pad
    if border:
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.4)
        c.rect(x, y, w, h, stroke=1, fill=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    roll_no = code_of(roll, "roll")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + pad, y + h - 7 * mm, "CV. DEWI ADITYA")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x + pad, y + h - 12 * mm, f"ROLL: {_clip(c, roll_no, 'Helvetica-Bold', 8, inner - 12 * mm)}")
    c.setFont("Helvetica", 7)
    c.drawString(x + pad, y + h - 17 * mm, _clip(
        c, f"{roll.get('material_code') or ''} {roll.get('material_name') or ''} | {roll.get('color') or ''}",
        "Helvetica", 7, inner))
    c.drawString(x + pad, y + h - 21.5 * mm, _clip(
        c, f"LOT: {roll.get('color_lot') or '-'} | {roll.get('supplier_name') or ''}", "Helvetica", 7, inner))
    c.drawString(x + pad, y + h - 26 * mm, _clip(c, roll.get("qty_text") or "", "Helvetica", 7, inner))
    _draw_barcode(c, roll_no, x + pad, y + 3 * mm, inner, 17 * mm)


def _draw(c, kind, x, y, lw, lh, doc, include_stock, border=True):
    if kind == "fg":
        draw_fg_label(c, x, y, lw, lh, doc, border=border)
    elif kind == "fg_hangtag":
        draw_fg_hangtag(c, x, y, lw, lh, doc, border=border)
    elif kind in ("asset", "asset_small"):
        draw_asset_label(c, x, y, lw, lh, doc, border=border)
    elif kind == "bin":
        draw_bin_label(c, x, y, lw, lh, doc, border=border)
    elif kind == "roll":
        draw_roll_label(c, x, y, lw, lh, doc, border=border)
    else:
        draw_material_label(c, x, y, lw, lh, doc, include_stock=include_stock, border=border)


def single_label_pdf(kind: str, doc: dict, include_stock: bool = True) -> io.BytesIO:
    """PDF satu label seukuran labelnya (untuk printer thermal)."""
    check_codes(kind, [doc])
    lw_mm, lh_mm = label_size(kind)
    lw, lh = lw_mm * mm, lh_mm * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(lw, lh))
    c.setTitle(f"Label {code_of(doc, kind)}")
    _draw(c, kind, 0, 0, lw, lh, doc, include_stock, border=False)
    c.save()
    buf.seek(0)
    return buf


def grid_labels_pdf(kind: str, docs, include_stock: bool = True,
                    title: str = "", footer: bool = False) -> io.BytesIO:
    """PDF A4 berisi banyak label. `docs` sudah DIKEMBANGKAN (1 elemen = 1 label)."""
    docs = list(docs)
    check_codes(kind, docs)
    return _grid_pdf([(kind, d) for d in docs], kind, include_stock,
                     title or f"Label batch ({len(docs)})", footer)


def grid_labels_pdf_mixed(entries, include_stock: bool = True,
                          title: str = "", footer: bool = False) -> io.BytesIO:
    """PDF A4 berisi label BEBERAPA JENIS yang SEUKURAN, mis. label bahan 90×50 + label roll kain 90×50.

    10 Nov 2026 (Buat Barcode › Dari penerimaan barang): satu penerimaan berisi aksesoris (label bahan) dan kain
    (label roll per gulungan) — satu PDF, satu kali cetak. `entries` = [(jenis, dokumen)], sudah DIKEMBANGKAN
    (1 elemen = 1 label). Jenis berbeda ukuran ditolak: grid dihitung dari SATU ukuran label.
    """
    entries = [(k, d) for k, d in entries]
    if not entries:
        raise ValueError("Tidak ada label untuk dicetak.")
    kinds = list(dict.fromkeys(k for k, _ in entries))
    if len({label_size(k) for k in kinds}) > 1:
        raise ValueError(f"Ukuran label berbeda tidak bisa dicampur dalam satu lembar: {', '.join(kinds)}")
    if len(kinds) > 1 and any(k in FIXED_GRID for k in kinds):
        raise ValueError(f"Label {', '.join(k for k in kinds if k in FIXED_GRID)} memakai grid tetap — cetak terpisah.")
    check_codes_mixed(entries)
    return _grid_pdf(entries, kinds[0], include_stock, title or f"Label batch ({len(entries)})", footer)


def _grid_pdf(entries, layout_kind: str, include_stock: bool, title: str, footer: bool) -> io.BytesIO:
    """Tata letak grid A4 (satu-satunya): ukuran & kolom/baris dari `layout_kind`, tiap label digambar sesuai jenisnya."""
    lw_mm, lh_mm = label_size(layout_kind)
    lw, lh = lw_mm * mm, lh_mm * mm
    page_w, page_h = A4
    cols, rows, mx, my = grid_geometry(page_w, page_h, lw, lh)
    if layout_kind in FIXED_GRID:
        cols, rows = FIXED_GRID[layout_kind]
        mx, my = (page_w - cols * lw) / 2, (page_h - rows * lh) / 2
    per_page = cols * rows

    def _footer(page_no: int, last: bool):
        if not footer:
            return
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        tail = f"  ·  {len(entries)} label" if last else ""
        c.drawString(mx, my / 2, f"{title}  ·  Hal {page_no}{tail}")
        c.setFillColorRGB(0, 0, 0)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    for idx, (kind, doc) in enumerate(entries):
        slot = idx % per_page
        col, row = slot % cols, slot // cols
        x = mx + col * lw
        y = page_h - my - (row + 1) * lh
        _draw(c, kind, x, y, lw, lh, doc, include_stock)
        if slot == per_page - 1 and idx + 1 < len(entries):
            _footer(idx // per_page + 1, False)
            c.showPage()
    _footer((len(entries) - 1) // per_page + 1 if entries else 1, True)
    c.save()
    buf.seek(0)
    return buf


async def attach_stock_info(db, mats) -> None:
    """Stok + lokasi utama per material (untuk label bahan yang mencetak stok).

    2026-11-02: satu salinan — dulu identik di wms_barcode.py & wms_material_labels.py.
    """
    ids = [m["id"] for m in mats if m.get("id")]
    if not ids:
        return
    per: dict = {}
    async for s in db.rahaza_material_stock.find(
            {"material_id": {"$in": ids}},
            {"_id": 0, "material_id": 1, "qty": 1, "location_id": 1}):
        per.setdefault(s["material_id"], []).append(s)
    loc_ids = list({s.get("location_id") for rows in per.values()
                    for s in rows if s.get("location_id")})
    loc_map: dict = {}
    if loc_ids:
        # RC-19: SSOT `rahaza_material_stock` memakai `location_id`; labelnya
        # bisa datang dari master lokasi ATAU posisi WMS.
        async for loc in db.rahaza_locations.find(
                {"id": {"$in": loc_ids}}, {"_id": 0, "id": 1, "code": 1, "name": 1}):
            loc_map[loc["id"]] = loc.get("code") or loc.get("name") or "-"
        async for pos in db.wh_positions.find(
                {"id": {"$in": loc_ids}}, {"_id": 0, "id": 1, "label": 1, "barcode": 1}):
            loc_map.setdefault(pos["id"], pos.get("label") or pos.get("barcode") or "-")
    for m in mats:
        rows = per.get(m.get("id")) or []
        if not rows:
            continue
        m["stock_qty"] = sum(float(s.get("qty") or 0) for s in rows)
        main = next((s.get("location_id") for s in rows
                     if float(s.get("qty") or 0) > 0 and s.get("location_id")), None)
        m["location"] = loc_map.get(main, "-")
