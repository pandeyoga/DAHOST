#!/usr/bin/env python3
"""Pembuat katalog aksi Asisten ERP (keputusan owner K1–K10, 12 Nov 2026).

Menyusun `backend/core/asisten_ai/katalog_aksi/data.json` dari:
  * daftar pintu TULIS aplikasi FastAPI (impor `server`, jadi jalankan di image backend), lengkap dengan awalan alamat,
    parameter alamat & query, dan skema isian dari OpenAPI (atau kunci isian yang dibaca fungsinya);
  * pemakaian di kode layar (`peta_layar.py`) — hanya pintu yang dipanggil layar aktif yang masuk katalog (K1);
  * aturan golongan & larangan `core/asisten_ai/katalog_aksi/aturan.py` (satu sumber dengan alat `jalankan_aksi`).

Pakai (dari akar repo, di image backend dengan repo terpasang di /app):
  docker run --rm -v "<repo>:/app" uji-tajam-be python /app/scripts/asisten_katalog/buat_katalog.py
  ... buat_katalog.py --periksa     # exit 1 bila data.json tidak sama dengan hasil susun ulang

Keluaran urut & deterministik (tanpa tanggal) supaya diff mudah dibaca.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND = os.path.join(ROOT, "backend")
OUT = os.path.join(BACKEND, "core", "asisten_ai", "katalog_aksi", "data.json")
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1")
os.environ.setdefault("DB_NAME", "katalog")
os.environ.setdefault("JWT_SECRET", "katalog-" + "x" * 32)

WRITE = ("POST", "PUT", "PATCH", "DELETE")
QUERY_ABAIKAN = frozenset({"page", "limit", "skip", "per_page", "page_size", "offset", "sort", "sort_by", "sort_dir",
                           "order", "token", "auth"})

KATA_KERJA = {
    "approve": "Setujui", "approve-hr": "Setujui (SDM)", "approve-manager": "Setujui (manajer)", "reject": "Tolak",
    "submit": "Ajukan", "cancel": "Batalkan", "close": "Tutup", "close-short": "Tutup walau kurang",
    "reopen": "Buka lagi", "confirm": "Konfirmasi", "send": "Kirim", "post": "Posting", "unpost": "Batalkan posting",
    "void": "Batalkan (void)", "reverse": "Balik", "pay": "Bayar", "payment": "Catat pembayaran",
    "payments": "Catat pembayaran", "receive": "Terima", "complete": "Selesaikan", "complete-qc": "Selesaikan QC",
    "start": "Mulai", "finish": "Selesaikan", "assign": "Tugaskan", "release": "Lepas", "archive": "Arsipkan",
    "restore": "Pulihkan", "activate": "Aktifkan", "deactivate": "Nonaktifkan", "toggle": "Ubah status aktif",
    "duplicate": "Salin", "clone": "Salin", "convert": "Konversi", "sync": "Sinkronkan", "generate": "Buat otomatis",
    "run": "Jalankan", "run-now": "Jalankan sekarang", "recalc": "Hitung ulang", "recompute": "Hitung ulang",
    "recalculate": "Hitung ulang", "import": "Impor", "upload": "Unggah", "export": "Ekspor", "resolve": "Selesaikan",
    "settle": "Selesaikan", "lock": "Kunci", "unlock": "Buka kunci", "forward": "Teruskan", "retry": "Coba lagi",
    "retry-posting": "Ulangi posting", "retry-post": "Ulangi posting", "preview": "Pratinjau", "status": "Ubah status",
    "dismiss": "Tutup", "skip": "Lewati", "evaluate": "Evaluasi", "test": "Uji", "publish": "Terbitkan",
    "ack": "Tandai dibaca", "acknowledge": "Tandai dibaca", "read": "Tandai dibaca", "mark-read": "Tandai dibaca",
    "mark-all-read": "Tandai semua dibaca", "accept": "Terima", "decline": "Tolak", "escalate": "Eskalasi",
    "apply": "Terapkan", "reprocess": "Proses ulang", "backfill": "Lengkapi", "write-off-bad-debt": "Hapus buku",
    "create-gr": "Buat penerimaan barang dari", "create-po": "Buat PO dari", "create-pr": "Buat PR dari",
    "create-request": "Ajukan permintaan untuk", "repost-journal": "Posting ulang jurnal", "potong": "Potong",
    "batal": "Batalkan", "kirim": "Kirim", "terapkan": "Terapkan", "tutup": "Tutup", "buka": "Buka",
    "setujui": "Setujui", "tolak": "Tolak", "bulk": "Simpan massal", "reorder": "Ubah urutan", "reset": "Atur ulang",
    "verify": "Verifikasi", "check": "Periksa", "calculate": "Hitung", "simulate": "Simulasikan",
    "pay-bpjs": "Bayar BPJS", "pay-pph21": "Bayar PPh 21", "void-payment": "Batalkan pembayaran",
    "void-obligation-payment": "Batalkan pembayaran kewajiban", "scan": "Scan", "pick": "Ambil", "count": "Hitung",
    "mark": "Tandai", "link": "Tautkan", "unlink": "Lepas tautan", "move": "Pindahkan", "transfer": "Pindahkan",
    "split": "Pecah", "merge": "Gabungkan", "rate-suggest": "Usulkan tarif", "sync-gl": "Sinkronkan ke buku besar",
}
KATA_BENDA = {
    "ar-invoices": "faktur piutang", "ap-invoices": "faktur hutang", "invoices": "faktur", "payments": "pembayaran",
    "journals": "jurnal", "accounts": "akun", "cash-accounts": "rekening kas/bank", "cost-centers": "pusat biaya",
    "expenses": "biaya", "claims": "klaim biaya", "travel": "perjalanan dinas", "settlements": "penyelesaian",
    "advances": "uang muka", "petty-cash": "kas kecil", "bank-transfers": "transfer bank", "bank-recon": "rekonsiliasi bank",
    "sessions": "sesi", "accruals": "akrual", "budgets": "anggaran", "budget": "anggaran", "fixed-assets": "aset tetap",
    "intercompany": "antar CV", "transactions": "transaksi", "payroll-runs": "penggajian", "payroll-profiles": "profil gaji",
    "payroll-allowances": "tunjangan", "salary-adjustments": "penyesuaian gaji", "salary-grades": "golongan gaji",
    "employees": "karyawan", "employee-loans": "pinjaman karyawan", "loans": "pinjaman", "kasbon": "kasbon",
    "requests": "permintaan", "leaves": "cuti", "leave-balances": "saldo cuti", "overtime": "lembur",
    "attendance": "absensi", "corrections": "koreksi absen", "permits": "izin", "shifts": "shift",
    "schedules": "jadwal", "resignation": "pengunduran diri", "clearance": "serah terima", "recruitment": "rekrutmen",
    "candidates": "kandidat", "jobs": "lowongan", "onboarding": "orientasi", "reviews": "ulasan", "kpi": "KPI",
    "purchase-orders": "PO pembelian", "purchase-requests": "PR aksesoris", "purchase-returns": "retur pembelian",
    "suppliers": "pemasok", "production-pos": "PO produksi", "po-accessories": "aksesoris PO", "pos": "PO",
    "material-issues": "pengeluaran bahan", "material-returns": "retur bahan", "material-requests": "permintaan bahan",
    "materials": "bahan", "boms": "BOM", "bom": "BOM", "models": "model produk", "variants": "varian",
    "colors": "warna", "sizes": "ukuran", "styles": "style", "samples": "sampel", "designs": "desain",
    "tech-packs": "techpack", "product-categories": "kategori produk", "catalogs": "katalog", "items": "item",
    "catalog-items": "item katalog", "targets": "target", "tasks": "tugas", "content-calendar": "kalender konten",
    "discounts": "promo", "live": "live", "returns": "retur", "complaints": "komplain", "orders": "pesanan",
    "withdrawals": "pencairan dana", "creators": "kreator", "kol": "KOL", "incentive": "insentif",
    "shipments": "kiriman", "dispatches": "dispatch", "delivery-notes": "surat jalan", "receiving": "penerimaan",
    "putaway": "penempatan", "picklist": "daftar ambil", "quarantine": "karantina", "fabric-rolls": "roll kain",
    "opname3": "opname", "units": "satuan", "locations": "lokasi", "structure": "struktur gudang", "labels": "label",
    "cmt-receipts": "penerimaan dari CMT", "short-shipments": "kekurangan kirim", "nota-aksesoris": "nota aksesoris",
    "kirim-cmt": "kirim ke CMT", "partners": "vendor", "my-jobs": "pekerjaan", "progress": "progres",
    "journal-import": "impor jurnal", "opening-balance": "saldo awal", "production-progress": "progres produksi",
    "production-job-items": "baris pekerjaan produksi", "production-jobs": "pekerjaan produksi",
    "clients": "klien", "quotes": "penawaran", "assets": "aset", "categories": "kategori",
    "disposal-requests": "permintaan pelepasan aset", "maintenance": "perawatan", "objectives": "objektif OKR",
    "key-results": "key result", "reminders": "pengingat", "notifications": "notifikasi", "todos": "daftar tugas",
    "notes": "catatan", "announcements": "pengumuman", "channels": "kanal", "messages": "pesan", "threads": "utas",
    "periods": "periode", "coa": "bagan akun", "doc-numbering": "penomoran dokumen", "pdf-templates": "template PDF",
    "customers": "pelanggan", "direct-sales": "penjualan langsung", "stock-thresholds": "stok minimum",
    "stock-adjustments": "penyesuaian stok", "scan-out": "scan keluar", "sheets": "lembar", "lines": "baris",
    "packing": "packing", "pack-batches": "batch packing", "permak": "permak", "qc": "QC", "cutting": "cutting",
    "hpp": "HPP", "valuation": "valuasi", "accessories": "aksesoris", "stock": "stok", "approvals": "persetujuan",
    "chains": "rantai persetujuan", "inbox": "kotak persetujuan", "okr": "OKR", "workspace": "ruang kerja",
    "pages": "halaman", "documents": "dokumen", "files": "berkas", "devices": "perangkat", "alerts": "peringatan",
    "settings": "pengaturan", "config": "pengaturan", "sku-prices": "harga SKU", "fg-matrix": "matriks barang jadi",
    "receivables": "piutang", "cmt-payments": "pembayaran CMT", "disbursements": "pencairan", "billing": "tagihan",
}
JUDUL_PORTAL_URUT = ("Keuangan", "Gudang", "Produksi", "Maklon", "SDM", "Marketing", "Pengadaan", "Aksesoris", "R&D",
                     "Aset", "Penjualan", "Manajemen", "Sistem", "Portal Saya", "Kolaborasi", "Cutting")


def _segs(p):
    return [x for x in p.split("/") if x]


def _humanis(seg: str) -> str:
    return KATA_BENDA.get(seg, seg.replace("-", " ").replace("_", " "))


def jenis_aksi(metode: str, jalur: str, berkas: bool) -> str:
    s = _segs(jalur)
    akhir = s[-1] if s else ""
    if berkas:
        return "impor"
    if metode == "DELETE":
        return "hapus"
    if not akhir.startswith("{") and akhir in KATA_KERJA and akhir not in ("status",):
        if akhir in ("preview", "simulate", "calculate", "check", "rate-suggest"):
            return "hitung"
        return "aksi"
    if metode in ("PUT", "PATCH"):
        return "ubah"
    if akhir.startswith("{"):
        return "ubah"
    if akhir == "status":
        return "aksi"
    if re.search(r"(preview|pratinjau|simulat|calculat|hitung|validate|lookup|suggest|search)", akhir):
        return "hitung"
    return "buat"


KATA_KERJA.update({
    "scrap": "Musnahkan", "issue": "Keluarkan", "return": "Kembalikan", "hold": "Tahan", "unhold": "Lepas tahanan",
    "block": "Blokir", "unblock": "Buka blokir", "approve-all": "Setujui semua", "reject-all": "Tolak semua",
    "photos": "Unggah foto", "upload-init": "Mulai unggah", "provision-portal": "Buat akun portal",
})


def _kata_kerja(seg: str):
    """Kata kerja Indonesia untuk satu potongan alamat, atau None. Menangani `bulk-x`, `create-x`, `x-all`."""
    if seg in KATA_KERJA:
        return KATA_KERJA[seg]
    if seg.startswith("bulk-"):
        k = _kata_kerja(seg[5:])
        return f"{k} massal" if k else "Simpan massal"
    if seg.startswith("create-"):
        return "Buat " + _humanis(seg[7:]) + " dari"
    if seg.startswith("generate-"):
        return "Buat otomatis " + _humanis(seg[9:]) + " untuk"
    if seg.startswith(("sync-", "mark-", "retry-", "recalc", "approve-", "reject-", "close-", "void-", "send-")):
        k = KATA_KERJA.get(seg.split("-")[0])
        if k:
            return f"{k} ({_humanis(seg.split('-', 1)[1])})"
    return None


def label_aksi(metode: str, jalur: str, jenis: str) -> str:
    s = [x for x in _segs(jalur) if x != "api"]
    lit = [x for x in s if not x.startswith("{")]
    akhir = s[-1] if s else ""
    # aksi pada satu data: …/{id}/<kata> → kata kerja + benda sebelum {id}
    pada_data = len(s) >= 2 and s[-2].startswith("{") and not akhir.startswith("{")
    kerja = _kata_kerja(akhir) if not akhir.startswith("{") else None
    benda = ""
    for x in reversed(lit):
        if x == akhir and (kerja or pada_data):
            continue
        if _kata_kerja(x) and x != lit[0]:
            continue
        benda = _humanis(x)
        break
    if jenis == "hapus":
        kata = "Hapus"
    elif kerja and jenis in ("aksi", "hitung", "buat", "impor"):
        kata = kerja
    elif pada_data and metode == "POST":
        kata = akhir.replace("-", " ").capitalize()
    elif jenis == "ubah":
        kata = "Ubah"
    elif jenis == "impor":
        kata = "Impor"
    else:
        kata = "Buat"
    return f"{kata} {benda}".strip()


def pilih_menu(menu: list, label: str, jalur: str) -> list:
    """Urutkan menu pemakai: yang labelnya paling mirip label aksi / kata di alamat lebih dulu (mis. aksi pemasok →
    menu "Pemasok", bukan menu lain yang kebetulan memakai komponen yang sama)."""
    kata = set(re.findall(r"[a-z0-9]+", label.lower()))
    for x in _segs(jalur):
        if not x.startswith("{"):
            kata |= set(re.findall(r"[a-z0-9]+", _humanis(x).lower())) | set(re.findall(r"[a-z0-9]+", x.lower()))
    kata -= {"api", "buat", "ubah", "hapus", "rahaza", "dewi", "id"}

    def skor(m):
        lab = set(re.findall(r"[a-z0-9]+", (m[1] or "").lower())) | set(re.findall(r"[a-z0-9]+", m[0].lower()))
        return (-len(kata & lab), not m[1], m[0])
    urut = sorted(menu, key=skor)
    if urut and not urut[0][1]:
        sama = [m for m in urut if m[1] and skor(m)[0] == skor(urut[0])[0]]
        if sama:
            urut.remove(sama[0])
            urut.insert(0, sama[0])
    return urut


def id_aksi(metode: str, jalur: str) -> str:
    bag = [("id" if x.startswith("{") else re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_"))
           for x in _segs(jalur) if x != "api"]
    return (metode.lower() + "_" + "_".join(b for b in bag if b))[:120]


# ── isian ────────────────────────────────────────────────────────────────────
def _deref(s, comps, depth=0):
    while isinstance(s, dict) and "$ref" in s:
        s = comps.get(s["$ref"].split("/")[-1], {})
    if not isinstance(s, dict):
        return {}
    for k in ("anyOf", "oneOf", "allOf"):
        if k in s:
            pilih = [x for x in (_deref(y, comps, depth) for y in s[k]) if x and x.get("type") != "null"]
            if len(pilih) == 1:
                s = {**{a: b for a, b in s.items() if a != k}, **pilih[0]}
            else:
                return {"type": [t for t in {x.get("type") for x in pilih} if isinstance(t, str)] or None}
    return s


def ringkas_skema(s, comps, depth=0) -> dict:
    """Skema JSON ringkas (tipe, enum, wajib, uraian ≤ 160) — sampai kedalaman 3."""
    s = _deref(s, comps)
    out: dict = {}
    t = s.get("type")
    if t:
        out["type"] = t
    for k in ("enum", "minimum", "maximum", "minLength", "maxLength", "format"):
        if k in s:
            out[k] = s[k]
    if s.get("description"):
        out["description"] = str(s["description"])[:160]
    if depth >= 3:
        return out
    if s.get("properties"):
        out["type"] = "object"
        out["properties"] = {k: ringkas_skema(v, comps, depth + 1) for k, v in sorted(s["properties"].items())}
        if s.get("required"):
            out["required"] = sorted(s["required"])
    if t == "array" and isinstance(s.get("items"), dict):
        out["items"] = ringkas_skema(s["items"], comps, depth + 1)
    if not out.get("type"):
        out.pop("type", None)
    return out


_BODY_VAR_RX = (
    re.compile(r"(\w+)\s*(?::\s*[\w\[\], |]+)?\s*=\s*await\s+\w+\.json\(\)"),
    re.compile(r"(\w+)\s*(?::\s*[\w\[\], |]+)?\s*=\s*await\s+_?\w*(?:body|json)\w*\(\s*request\s*\)"),
    re.compile(r"(\w+)\s*:\s*(?:dict|Dict\[[^\]]*\]|Optional\[dict\])\s*=\s*Body\("),
)


def kunci_dari_sumber(src: str) -> list:
    vars_ = set()
    for rx in _BODY_VAR_RX:
        vars_.update(rx.findall(src))
    m = re.search(r"def \w+\((.*?)\)\s*(?:->[^:]+)?:", src, re.S)
    if m:
        for v in re.findall(r"(\w+)\s*:\s*dict\b", m.group(1)):
            vars_.add(v)
    kunci = set()
    for v in vars_:
        for k in re.findall(rf"\b{re.escape(v)}\.get\(\s*['\"]([\w.-]+)['\"]", src):
            kunci.add(k)
        for k in re.findall(rf"\b{re.escape(v)}\[\s*['\"]([\w.-]+)['\"]\s*\]", src):
            kunci.add(k)
        for k in re.findall(rf"['\"]([\w.-]+)['\"]\s+(?:not\s+)?in\s+{re.escape(v)}\b", src):
            kunci.add(k)
    return sorted(k for k in kunci if not k.startswith("_"))[:60]


# ── bacaan layar & petunjuk id (12 Nov 2026) ─────────────────────────────────
OVERRIDE_RX = re.compile(r"resolve_override|apply_scope|get_override|effective_vendor_id")


def _query_manual(src: str, sudah: set) -> list:
    """Parameter query yang dibaca fungsi sendiri: `request.query_params.get("x")` / `query_params["x"]`."""
    nama = set(re.findall(r"query_params\.get\(\s*['\"](\w+)['\"]", src))
    nama |= set(re.findall(r"query_params\[\s*['\"](\w+)['\"]\s*\]", src))
    return [{"nama": n, "tipe": "str", "wajib": False, "manual": True} for n in sorted(nama - sudah)]


def _query_rute(r) -> list:
    out = []
    try:
        src = inspect.getsource(r.endpoint)
    except (OSError, TypeError):
        src = ""
    for q in r.dependant.query_params:
        fi = getattr(q, "field_info", None)
        ann = getattr(q, "type_", None) or getattr(fi, "annotation", None)
        item = {"nama": q.name, "tipe": getattr(ann, "__name__", str(ann)).replace("typing.", "")[:40],
                "wajib": bool(getattr(q, "required", False))}
        dflt = getattr(fi, "default", None)
        if isinstance(dflt, (str, int, float, bool)) and not isinstance(dflt, type):
            item["bawaan"] = dflt
        out.append(item)
    out += _query_manual(src, {q["nama"] for q in out})
    return sorted(out, key=lambda q: q["nama"])


def susun_bacaan(baca_rute: dict, peta, aturan) -> list:
    """GET yang dipanggil layar aktif dan aman dibaca Asisten (lihat aturan.larangan_baca)."""
    out = []
    for jalur, r in sorted(baca_rute.items()):
        fn = r.endpoint
        modul = (getattr(fn, "__module__", "") or "").replace("routes.", "", 1)
        if aturan.di_luar_katalog(modul) or aturan.larangan_baca(jalur):
            continue
        pakai = peta.pemakai(jalur)
        if not pakai["berkas"]:
            continue
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            src = ""
        s = [x for x in _segs(jalur) if x != "api"]
        benda = next((_humanis(x) for x in reversed(s) if not x.startswith("{")), "data")
        label = (f"Lihat {benda}" if s and s[-1].startswith("{") else
                 f"Daftar {benda}" if not any(x.startswith("{") for x in s) else f"Lihat {benda} per data")
        menu = pilih_menu(pakai["menu"], label, jalur)
        doc = (inspect.getdoc(fn) or "").strip()
        item = {"id": id_aksi("GET", jalur), "jalur": jalur, "modul": modul, "fungsi": fn.__name__, "label": label,
                "keterangan": paragraf_pertama(doc)[:200],
                "parameter_jalur": re.findall(r"\{(\w+)(?::[^}]*)?\}", jalur), "query": _query_rute(r),
                "menu": menu[0][0] if menu else None, "layar": menu[0][1] if menu else "", "portal": pakai["portal"]}
        if OVERRIDE_RX.search(src):
            item["atas_nama_vendor"] = True
        out.append(item)
    lihat: dict = {}
    for b in out:
        n = lihat.get(b["id"], 0)
        lihat[b["id"]] = n + 1
        if n:
            b["id"] = f"{b['id']}_{n + 1}"
    return out


def kunci_bersarang(src_modul: str, kunci: list) -> dict:
    """Kunci di dalam isian daftar (mis. `lines` → account_code, debit, credit) yang dibaca modul route lewat
    `for x in lines: x.get("…")` — termasuk di fungsi bantu (mis. `_validate_lines`)."""
    out = {}
    for k in kunci:
        pola = (rf"for\s+(?:\w+\s*,\s*)?(\w+)\s+in\s+(?:enumerate\()?(?:\(?\s*)?(?:\w+\.get\(\s*['\"]{re.escape(k)}['\"]"
                rf"[^)]*\)|\b{re.escape(k)}\b)")
        nama = set(re.findall(pola, src_modul))
        isi = set()
        for v in nama:
            if len(v) < 2 or v in ("k", "i", "_"):
                continue
            isi |= set(re.findall(rf"\b{re.escape(v)}\.get\(\s*['\"]([\w.-]+)['\"]", src_modul))
            isi |= set(re.findall(rf"\b{re.escape(v)}\[\s*['\"]([\w.-]+)['\"]\s*\]", src_modul))
        isi = sorted(x for x in isi if not x.startswith("_"))[:30]
        if isi:
            out[k] = isi
    return out


def paragraf_pertama(doc: str) -> str:
    """Paragraf pertama docstring dalam satu baris."""
    if not doc:
        return ""
    return " ".join(re.split(r"\n\s*\n", doc)[0].split())


def _akar(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def pasang_cari_id(aksi: list, bacaan: list, get_paths: set) -> None:
    """Petunjuk sumber id per aksi: parameter alamat → daftar koleksinya; isian `x_id` → daftar GET bernama x."""
    daftar = [b for b in bacaan if not b["parameter_jalur"]]
    ada = {b["jalur"] for b in bacaan}
    for a in aksi:
        petunjuk: dict = {}
        s = _segs(a["jalur"])
        for i, x in enumerate(s):
            if x.startswith("{"):
                induk = "/" + "/".join(s[:i])
                if induk in ada:
                    petunjuk[re.sub(r"[{}]|:.*", "", x)] = [induk]
        isi = a.get("isian") or {}
        if isi.get("bentuk") == "bertipe":
            kunci = list(((isi.get("skema") or {}).get("properties") or {}).keys())
        else:
            kunci = list(isi.get("kunci") or [])
        for k in kunci:
            if not k.endswith("_id") or k in petunjuk:
                continue
            akar = _akar(k[:-3])
            if len(akar) < 3:
                continue
            cocok = [b["jalur"] for b in daftar
                     if any(_akar(seg).rstrip("s").endswith(akar) or _akar(seg).endswith(akar + "es")
                            for seg in _segs(b["jalur"])[-1:])]
            if cocok:
                petunjuk[k] = sorted(cocok, key=len)[:3]
        if petunjuk:
            a["cari_id"] = petunjuk


# ── utama ────────────────────────────────────────────────────────────────────
def susun() -> dict:
    logging.disable(logging.CRITICAL)
    os.chdir(BACKEND)
    import server  # noqa: E402
    from fastapi.routing import APIRoute  # noqa: E402
    from core.asisten_ai.katalog_aksi import aturan  # noqa: E402
    from peta_layar import PetaLayar  # noqa: E402

    app = server.app
    spec = app.openapi()
    comps = spec.get("components", {}).get("schemas", {})
    peta = PetaLayar(ROOT)
    get_paths = set()
    tulis, baca_rute = {}, {}
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        ms = set(r.methods or [])
        if "GET" in ms:
            get_paths.add(r.path)
            baca_rute.setdefault(r.path, r)
        for m in sorted(ms & set(WRITE)):
            tulis[(m, r.path)] = r

    aksi, kecuali = [], []
    for (metode, jalur), r in sorted(tulis.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        fn = r.endpoint
        modul = (getattr(fn, "__module__", "") or "").replace("routes.", "", 1)
        luar = aturan.di_luar_katalog(modul)
        pakai = peta.pemakai(jalur)
        dasar = {"metode": metode, "jalur": jalur, "modul": modul, "fungsi": fn.__name__}
        if luar:
            kecuali.append({**dasar, "alasan": luar})
            continue
        if not pakai["berkas"]:
            kecuali.append({**dasar, "alasan": "tidak dipanggil layar aktif"})
            continue
        op = (spec.get("paths", {}).get(jalur, {}) or {}).get(metode.lower(), {}) or {}
        rb = (op.get("requestBody") or {}).get("content", {})
        berkas = bool(rb.get("multipart/form-data") or rb.get("application/x-www-form-urlencoded"))
        isian: dict = {}
        if berkas:
            sk = ringkas_skema((rb.get("multipart/form-data") or rb.get("application/x-www-form-urlencoded")
                                or {}).get("schema") or {}, comps)
            props = sk.get("properties") or {}
            isian = {"bentuk": "berkas",
                     "kolom_berkas": sorted(k for k, v in props.items() if (v.get("format") == "binary") or
                                            (v.get("type") == "array" and (v.get("items") or {}).get("format") ==
                                             "binary")) or ["file"],
                     "skema": {**sk, "properties": {k: v for k, v in props.items() if v.get("format") != "binary"}}}
        elif rb.get("application/json"):
            sk = ringkas_skema(rb["application/json"].get("schema") or {}, comps)
            if sk.get("properties"):
                isian = {"bentuk": "bertipe", "skema": sk}
            else:
                isian = {"bentuk": "bebas"}
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            src = ""
        if isian.get("bentuk") in (None, "bebas") and not berkas:
            k = kunci_dari_sumber(src)
            if k or isian.get("bentuk") == "bebas" or "request.json()" in src or "Body(" in src:
                isian = {"bentuk": "bebas", "kunci": k}
                try:
                    src_modul = inspect.getsource(inspect.getmodule(fn))
                except (OSError, TypeError):
                    src_modul = ""
                bersarang = kunci_bersarang(src_modul, k)
                if bersarang:
                    isian["bersarang"] = bersarang
                contoh = peta.cuplikan(jalur, metode)
                if contoh:
                    isian["contoh_layar"] = contoh
        query = []
        for q in r.dependant.query_params:
            if q.name in QUERY_ABAIKAN:
                continue
            fi = getattr(q, "field_info", None)
            ann = getattr(q, "type_", None) or getattr(fi, "annotation", None)
            tipe = getattr(ann, "__name__", str(ann)).replace("typing.", "")[:40]
            dflt = getattr(fi, "default", None)
            item = {"nama": q.name, "tipe": tipe, "wajib": bool(getattr(q, "required", False))}
            if isinstance(dflt, (str, int, float, bool)) and not isinstance(dflt, type):
                item["bawaan"] = dflt
            query.append(item)
        query += [q for q in _query_manual(src, {q["nama"] for q in query}) if q["nama"] not in QUERY_ABAIKAN]
        query.sort(key=lambda q: q["nama"])
        jenis = jenis_aksi(metode, jalur, berkas)
        gol = aturan.golongan_untuk(modul, jalur)
        doc = (inspect.getdoc(fn) or "").strip()
        paragraf = re.split(r"\n\s*\n", doc)[0].replace("\n", " ") if doc else ""
        larang = aturan.larangan_untuk(metode, jalur)
        if not larang and metode == "DELETE" and re.search(r"permanen|permanent", paragraf, re.I) \
                and not any(q["nama"] in aturan.QUERY_HAPUS_PERMANEN for q in query):
            larang = {"kode": "K8", "alasan": aturan.PESAN_HAPUS_PERMANEN}
        params = re.findall(r"\{(\w+)(?::[^}]*)?\}", jalur)
        # pembaca nilai lama: GET di alamat yang sama, atau alamat induk yang berakhir parameter
        baca = None
        if jalur in get_paths and (params or metode in ("PUT", "PATCH")):
            baca = jalur
        else:
            s = _segs(jalur)
            for i in range(len(s) - 1, 0, -1):
                if s[i - 1].startswith("{") and "/" + "/".join(s[:i]) in get_paths:
                    baca = "/" + "/".join(s[:i])
                    break
        # cadangan: daftar GET di alamat koleksi, data dicari dengan id-nya (mis. /ar-invoices/{iid}/send → /ar-invoices)
        baca_daftar = None
        if not baca and params:
            s = _segs(jalur)
            for i in range(len(s) - 1, 0, -1):
                if s[i].startswith("{"):
                    induk = "/" + "/".join(s[:i])
                    if induk in get_paths:
                        baca_daftar = {"jalur": induk, "kunci": re.sub(r"[{}]|:.*", "", s[i])}
                    break
        # pembalikan otomatis hanya untuk golongan A (B/C lewat aksi resmi batal/void sebagai kartu baru)
        balik = None
        if gol == "A" and not larang:
            if jenis == "buat" and not params:
                anak = [p for p in tulis if p[0] == "DELETE" and re.fullmatch(re.escape(jalur) + r"/\{\w+\}", p[1])]
                if anak:
                    balik = {"jenis": "hapus_buatan", "jalur": anak[0][1]}
            elif jenis == "ubah" and baca and isian.get("bentuk") in ("bertipe", "bebas"):
                balik = {"jenis": "kembalikan"}
        label = label_aksi(metode, jalur, jenis)
        atas_nama = bool(OVERRIDE_RX.search(src))
        menu = pilih_menu(pakai["menu"], label, jalur)
        portal = pakai["portal"]
        # menu & nama layar dari menu terbaik yang berlabel (bila menu terbaik tidak berlabel: tanpa nama layar)
        layar = menu[0][1] if menu else ""
        aksi.append({
            "id": id_aksi(metode, jalur), **dasar, "label": label, "keterangan": paragraf[:300],
            "jenis": jenis, "golongan": gol, "tingkat": aturan.tingkat_untuk(gol, jenis),
            "parameter_jalur": params, "query": query, "isian": isian, "baca": baca, "balik": balik,
            **({"baca_daftar": baca_daftar} if baca_daftar else {}),
            "menu": menu[0][0] if menu else None, "layar": layar, "portal": portal,
            **({"larangan": larang} if larang else {}),
            **({"atas_nama_vendor": True} if atas_nama else {}),
        })
    bacaan = susun_bacaan(baca_rute, peta, aturan)
    pasang_cari_id(aksi, bacaan, get_paths)
    # id unik
    lihat: dict = {}
    for a in aksi:
        n = lihat.get(a["id"], 0)
        lihat[a["id"]] = n + 1
        if n:
            a["id"] = f"{a['id']}_{n + 1}"
    aksi.sort(key=lambda a: a["id"])
    kecuali.sort(key=lambda k: (k["jalur"], k["metode"]))
    return {"versi": 2, "jumlah": len(aksi), "jumlah_bacaan": len(bacaan), "aksi": aksi, "bacaan": bacaan,
            "dikecualikan": kecuali}


def tulis_json(data: dict) -> str:
    """Satu aksi per baris (diff per aksi mudah dibaca), kunci terurut."""
    def baris(x):
        return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    daftar = ("aksi", "bacaan", "dikecualikan")
    kepala = {k: v for k, v in data.items() if k not in daftar}
    out = ["{"]
    for k, v in sorted(kepala.items()):
        out.append(f' "{k}": {baris(v)},')
    for j, nama in enumerate(daftar):
        isi = data.get(nama) or []
        out.append(f' "{nama}": [')
        out.extend(("  " + baris(x) + ("," if i < len(isi) - 1 else "")) for i, x in enumerate(isi))
        out.append(" ]," if j < len(daftar) - 1 else " ]")
    out.append("}")
    return "\n".join(out) + "\n"


def main() -> int:
    data = susun()
    teks = tulis_json(data)
    if "--periksa" in sys.argv:
        lama = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if lama != teks:
            print("Katalog aksi tidak sama dengan susunan ulang — jalankan buat_katalog.py lalu commit data.json.")
            return 1
        print(f"Katalog aksi cocok ({data['jumlah']} aksi).")
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(teks)
    from collections import Counter
    print(f"{data['jumlah']} aksi, {len(data['dikecualikan'])} dikecualikan → {OUT}")
    print("golongan", sorted(Counter(a["golongan"] for a in data["aksi"]).items()))
    print("jenis", sorted(Counter(a["jenis"] for a in data["aksi"]).items()))
    print("larangan", sorted(Counter(a["larangan"]["kode"] for a in data["aksi"] if a.get("larangan")).items()))
    print("isian", sorted(Counter(a["isian"].get("bentuk", "-") for a in data["aksi"]).items()))
    print("baca", sum(1 for a in data["aksi"] if a["baca"]), "baca_daftar",
          sum(1 for a in data["aksi"] if a.get("baca_daftar")), "balik", sum(1 for a in data["aksi"] if a["balik"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
