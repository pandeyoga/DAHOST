"""core.impor_paket — **"Perbarui semua dalam satu langkah"**: banyak berkas → banyak tabel (audit Marketing §7.4).

Permintaan owner (9 Nov 2026): unggah BANYAK ekspor Seller Center sekaligus (pesanan, iklan,
retur, KPI, …) → sistem mengenali jenis & toko tiap berkas → pratinjau gabungan → konfirmasi
sekali → semua tabel diperbarui. Modul ini memuat logika TANPA HTTP: analisis per berkas, bukti
toko, urutan simpan, dan ringkasan. Penyimpanan berjalan lewat jalur impor yang SUDAH ADA
(`routes/marketing_data_import.upload/commit/rollback`), sehingga semua penjaga (platform,
gudang toko, kunci periode, dedupe, jejak pembatalan, rekap harian) berlaku sama persis.

Aturan:
  * jenis berkas dari SIDIK isi berkas (`core.impor_sidik`), nama berkas hanya bukti lemah;
  * toko dari BUKTI di berkas (gudang platform, username/ID toko di metadata, nomor pesanan yang
    sudah dimiliki toko, berkas identik yang pernah diunggah) dan HANYA di antara toko yang
    boleh dilihat pengguna; tanpa bukti cukup, staf memilih sendiri;
  * laporan penghasilan & saldo TIDAK diimpor di sini — diarahkan ke Keuangan (draf Pencairan /
    Penarikan) karena jurnalnya milik Keuangan;
  * urutan simpan: pesanan → status pesanan → retur → komplain/ulasan → iklan → KPI → lainnya.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core import impor_sidik as sd
from core import marketing_import_engine as eng
from core.marketing_import_schema import SOURCE_TYPES, get_source_type

KOLEKSI = "marketing_impor_paket"
MAKS_BERKAS = 20
MAKS_MB_BERKAS = 15
MAKS_MB_PAKET = 60
EKSTENSI = (".csv", ".xlsx", ".xls", ".xlsm", ".tsv", ".txt")

# urutan simpan (makin kecil makin dulu). Pesanan harus ada sebelum kabar status/retur.
URUTAN = {
    "marketplace_orders": 10, "orders": 11, "sales_daily": 12,
    "marketplace_fulfillment": 20,
    "returns": 30, "complaints": 31, "reviews": 32,
    "shopee_ads_cpc": 40, "tiktok_gmv_max": 41, "ads": 42,
    "shopee_shop_kpi": 50, "shopee_content_kpi": 51, "content_performance": 52,
}
# jenis yang SELALU memperbarui baris lama (snapshot/laporan per periode)
SELALU_PERBARUI = ("shopee_shop_kpi", "shopee_content_kpi", "shopee_ads_cpc", "tiktok_gmv_max",
                   "content_performance")
# Status sesi impor yang TIDAK boleh di-commit ulang oleh paket (jalur impor MKT-INTI 9 Nov:
# `committing` = sedang/terhenti saat disimpan, `partial` = sebagian baris sudah tersimpan).
SESI_JANGAN_ULANG = ("committing", "partial", "committed")
PESAN_SESI = {
    "committing": "Sesi impor berkas ini sedang/terhenti saat disimpan — tunggu, lalu periksa Riwayat Impor. "
                  "Tidak disimpan ulang supaya baris tidak dobel.",
    "partial": "Simpan sebelumnya terhenti di tengah: SEBAGIAN baris sudah tersimpan. Tidak disimpan ulang — "
               "tekan Batalkan paket (atau Batalkan di Riwayat Impor) lalu periksa & simpan lagi.",
    "committed": "Sesi ini sudah tersimpan sebelumnya.",
}
# jenis impor yang butuh konteks tambahan (host/kreator/katalog/sesi) — tidak bisa lewat paket
BUTUH_KONTEKS = {k for k, st in SOURCE_TYPES.items() if st.context}

STATUS_LABEL = {
    "perlu_isian": "Perlu dilengkapi", "siap_diperiksa": "Siap diperiksa", "diperiksa": "Siap disimpan",
    "perlu_pemetaan": "Pemetaan belum lengkap", "ditolak": "Ditolak", "disimpan": "Tersimpan",
    "gagal": "Gagal disimpan", "dilewati": "Tidak diimpor", "dibatalkan": "Dibatalkan",
    "keuangan": "Diproses di Keuangan",
}


class GalatPaket(ValueError):
    def __init__(self, status: int, pesan: str):
        super().__init__(pesan)
        self.status = int(status)
        self.pesan = str(pesan)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BERKAS MASUK (banyak berkas / ZIP)
# ═══════════════════════════════════════════════════════════════════════════════
def urai_unggahan(berkas: Sequence[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    """Daftar (nama, isi). ZIP dibuka (hanya CSV/Excel di dalamnya). Batas jumlah & ukuran ditegakkan."""
    out: List[Tuple[str, bytes]] = []
    for nama, raw in berkas:
        nama = (nama or "berkas").replace("\\", "/").split("/")[-1]
        if nama.lower().endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(raw))
            except zipfile.BadZipFile:
                raise GalatPaket(400, f"Berkas ZIP '{nama}' rusak.") from None
            for info in z.infolist():
                if info.is_dir():
                    continue
                inner = info.filename.replace("\\", "/").split("/")[-1]
                if inner.startswith(".") or not inner.lower().endswith(EKSTENSI):
                    continue
                if info.file_size > MAKS_MB_BERKAS * 1024 * 1024:
                    raise GalatPaket(400, f"Berkas '{inner}' di dalam ZIP lebih dari {MAKS_MB_BERKAS} MB.")
                out.append((inner, z.read(info)))
            continue
        if not nama.lower().endswith(EKSTENSI):
            raise GalatPaket(400, f"'{nama}' bukan CSV/Excel. Unggah ekspor .xlsx/.csv atau satu .zip berisi ekspor.")
        if len(raw) > MAKS_MB_BERKAS * 1024 * 1024:
            raise GalatPaket(400, f"Berkas '{nama}' lebih dari {MAKS_MB_BERKAS} MB.")
        out.append((nama, raw))
    if not out:
        raise GalatPaket(400, "Tidak ada berkas CSV/Excel yang bisa dibaca.")
    if len(out) > MAKS_BERKAS:
        raise GalatPaket(400, f"Paling banyak {MAKS_BERKAS} berkas dalam satu paket.")
    if sum(len(r) for _, r in out) > MAKS_MB_PAKET * 1024 * 1024:
        raise GalatPaket(400, f"Total ukuran paket lebih dari {MAKS_MB_PAKET} MB.")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ANALISIS PER BERKAS (tanpa database)
# ═══════════════════════════════════════════════════════════════════════════════
def _periode_meta(meta: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    from core.marketing_import_prenorm import _date_range
    for k in ("periode", "period"):
        if meta.get(k):
            a, b = _date_range(meta[k])
            if a and b:
                return a, b
    return None, None


def bukti_toko_berkas(t: Optional[sd.Tabel]) -> dict:
    """Penanda toko di dalam berkas: gudang platform, username/ID/nama toko di metadata, nomor pesanan."""
    out: Dict[str, Any] = {"gudang": [], "username": "", "id_toko": "", "nama_toko": "", "nomor_pesanan": []}
    if t is None:
        return out
    h_norm = {eng._norm_header(h): h for h in t.headers}
    wh = h_norm.get("warehouse name")
    if wh:
        out["gudang"] = sorted({str(r.get(wh)).strip() for r in t.rows if r.get(wh) not in (None, "")})[:5]
    meta = t.meta or {}
    out["username"] = meta.get("username") or meta.get("username penjual") or ""
    out["id_toko"] = meta.get("id toko") or meta.get("shop id") or ""
    out["nama_toko"] = meta.get("nama toko") or meta.get("shop name") or ""
    for key in ("order id", "no pesanan"):
        c = h_norm.get(key)
        if c:
            ids = [str(r.get(c)).strip() for r in t.rows if r.get(c) not in (None, "")]
            out["nomor_pesanan"] = list(dict.fromkeys(i for i in ids if not i.endswith(".")))[:200]
            break
    return out


def analisa_berkas(nama: str, raw: bytes) -> dict:
    """Jenis, platform, versi, jalur, periode, banyak baris, peringatan, bukti toko — satu berkas."""
    hasil, t = sd.tabel_utama(raw, nama)
    st_key = hasil.get("source_type") or ""
    peringatan: List[str] = []
    if not hasil.get("dikenal"):
        # cadangan: kecocokan kolom dengan jenis impor (perilaku lama), hanya sebagai USULAN
        try:
            cat = [get_source_type(k) for k in SOURCE_TYPES if k not in BUTUH_KONTEKS]
            det = eng.detect_source_type(raw, nama, cat, top=3)
            best = det.get("best") or {}
            if best and best.get("required_cover", 0) >= 0.99 and best.get("score", 0) >= 0.6:
                st_key = best["source_type"]
                peringatan.append(f"Jenis laporan tidak dikenali dari tanda pengenalnya; kolomnya paling cocok "
                                  f"dengan “{best['label']}” ({best['mapped_columns']} kolom). Periksa sebelum menyimpan.")
        except Exception:  # noqa: BLE001
            pass
    if hasil.get("ragu"):
        lain = [k["label"] for k in hasil.get("kandidat", [])[1:3]]
        peringatan.append("Berkas juga mirip " + ", ".join(lain) + " — pastikan jenisnya benar.")
    p_from, p_to = (None, None)
    if t is not None:
        p_from, p_to = _periode_meta(t.meta)
    if not (p_from and p_to):
        from core.marketing_import_prenorm import periode_dari_nama
        p_from, p_to = periode_dari_nama(nama)
    tab = hasil.get("tabel") or {}
    butuh_periode = st_key == "tiktok_gmv_max"
    if butuh_periode and tab.get("terpotong"):
        peringatan.append("Berkas besar: hanya awal berkas yang dibaca untuk pratinjau; baris tanpa biaya dibuang "
                          "saat disimpan.")
    label_jenis = (SOURCE_TYPES[st_key].label if st_key in SOURCE_TYPES else "") or hasil.get("label")
    return {
        "nama": nama, "ukuran_kb": round(len(raw) / 1024, 1), "sha256": hashlib.sha256(raw).hexdigest(),
        "sidik": {k: hasil.get(k) for k in ("dikenal", "jenis", "label", "platform", "jalur", "jalur_label",
                                            "versi", "bukti", "ragu")},
        "jalur": hasil.get("jalur") or (sd.JALUR_IMPOR if st_key else ""),
        "source_type": st_key, "label_jenis": label_jenis or "Belum dikenali",
        "platform": hasil.get("platform") or "",
        "baris": tab.get("baris") or 0, "baris_perkiraan": bool(tab.get("terpotong")),
        "periode_mulai": p_from, "periode_selesai": p_to, "butuh_periode": butuh_periode,
        "bukti_toko": bukti_toko_berkas(t),
        "peringatan": peringatan,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BUKTI TOKO (database, berlingkup pengguna)
# ═══════════════════════════════════════════════════════════════════════════════
def _n(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


async def cari_toko(db, accounts: List[dict], analisis: dict) -> List[dict]:
    """Calon toko berperingkat + alasan. ``accounts`` = toko yang BOLEH dilihat pengguna."""
    from core import marketing_account_scope as scope
    plat = analisis.get("platform") or ""
    bukti = analisis.get("bukti_toko") or {}
    skor: Dict[str, Dict[str, Any]] = {}

    def tambah(acc, nilai, alasan):
        s = skor.setdefault(acc["id"], {"id": acc["id"], "nama": acc.get("account_name") or acc["id"],
                                        "kode": acc.get("account_code") or "", "platform": acc.get("platform") or "",
                                        "skor": 0.0, "alasan": []})
        s["skor"] = max(s["skor"], nilai)
        s["alasan"].append(alasan)

    cocok_plat = [a for a in accounts if not plat or scope.platform_family(a.get("platform")) == scope.platform_family(plat)]
    for a in cocok_plat:
        wh = _n(a.get("platform_warehouse_name"))
        if wh and any(_n(g) == wh for g in bukti.get("gudang") or []):
            tambah(a, 1.0, f"gudang platform di berkas = gudang toko ({a.get('platform_warehouse_name')})")
        for fld, lbl in (("username", "username"), ("platform_username", "username"), ("shop_username", "username"),
                         ("platform_shop_id", "ID toko"), ("shop_id", "ID toko")):
            v = _n(a.get(fld))
            if v and v in (_n(bukti.get("username")), _n(bukti.get("id_toko"))):
                tambah(a, 0.95, f"{lbl} toko di berkas cocok dengan master toko")
        if bukti.get("nama_toko") and _n(bukti["nama_toko"]) == _n(a.get("account_name")):
            tambah(a, 0.8, "nama toko di berkas sama dengan nama toko")
    ids = bukti.get("nomor_pesanan") or []
    if ids and accounts:
        allowed = [a["id"] for a in accounts]
        hit: Dict[str, int] = {}
        async for o in db.marketing_orders.find({"order_id": {"$in": ids}, "account_id": {"$in": allowed}},
                                                {"_id": 0, "account_id": 1}):
            hit[o["account_id"]] = hit.get(o["account_id"], 0) + 1
        for aid, n in hit.items():
            a = next(x for x in accounts if x["id"] == aid)
            tambah(a, min(0.9, 0.5 + n / max(1, len(ids))), f"{n} nomor pesanan di berkas sudah tercatat di toko ini")
    if analisis.get("sha256") and accounts:
        allowed = [a["id"] for a in accounts]
        async for s in db.marketing_data_import_sessions.find(
                {"content_sha256": analisis["sha256"], "account_id": {"$in": allowed}},
                {"_id": 0, "account_id": 1}).limit(5):
            a = next((x for x in accounts if x["id"] == s.get("account_id")), None)
            if a:
                tambah(a, 0.85, "berkas yang SAMA PERSIS pernah diunggah ke toko ini")
    if not skor and len(cocok_plat) == 1 and plat:
        tambah(cocok_plat[0], 0.5, f"satu-satunya toko {plat.upper()} yang bisa Anda akses")
    out = sorted(skor.values(), key=lambda s: -s["skor"])
    for s in out:
        s["alasan"] = list(dict.fromkeys(s["alasan"]))
    return out


def pilih_toko_otomatis(calon: List[dict]) -> Optional[str]:
    """Toko dipasang otomatis hanya bila buktinya kuat dan TIDAK bersaing."""
    if not calon:
        return None
    if calon[0]["skor"] >= 0.8 and (len(calon) == 1 or calon[1]["skor"] < 0.8):
        return calon[0]["id"]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STATUS & RINGKASAN
# ═══════════════════════════════════════════════════════════════════════════════
def kekurangan(b: dict) -> List[str]:
    """Isian yang masih kurang sebelum berkas bisa diperiksa."""
    out = []
    if not b.get("ikut", True):
        return out
    if b.get("jalur") != sd.JALUR_IMPOR:
        return out
    if not b.get("source_type"):
        out.append("Pilih jenis data berkas ini.")
    elif b["source_type"] in BUTUH_KONTEKS:
        out.append("Jenis ini butuh pilihan host/kreator/katalog — impor lewat menu Impor Data satu per satu.")
    if not b.get("account_id"):
        out.append("Pilih toko tujuan.")
    if b.get("source_type") == "tiktok_gmv_max" and not (b.get("periode_mulai") and b.get("periode_selesai")):
        out.append("Isi periode laporan GMV Max (tanggal mulai dan selesai saat mengekspor).")
    return out


def status_awal(b: dict) -> str:
    if not b.get("ikut", True):
        return "dilewati"
    if b.get("jalur") in (sd.JALUR_PENCAIRAN, sd.JALUR_PENARIKAN):
        return "keuangan"
    if b.get("jalur") == sd.JALUR_BELUM or not b.get("source_type") and b.get("jalur") != sd.JALUR_IMPOR:
        return "dilewati"
    return "perlu_isian" if kekurangan(b) else "siap_diperiksa"


def urutan_simpan(berkas: List[dict]) -> List[dict]:
    return sorted(berkas, key=lambda b: (URUTAN.get(b.get("source_type") or "", 90), b.get("idx", 0)))


def ringkas_paket(doc: dict) -> dict:
    n = {}
    for b in doc.get("berkas") or []:
        n[b.get("status")] = n.get(b.get("status"), 0) + 1
    hasil = [b.get("hasil") or {} for b in doc.get("berkas") or []]
    return {
        "berkas": len(doc.get("berkas") or []), "per_status": n,
        "baris_masuk": sum(int(h.get("inserted") or 0) for h in hasil),
        "baris_diperbarui": sum(int(h.get("updated") or 0) for h in hasil),
        "baris_ditolak": sum(int(h.get("rejected") or 0) for h in hasil),
        "baris_duplikat": sum(int(h.get("skipped_duplicates") or 0) for h in hasil),
    }
