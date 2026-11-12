"""Peringatan harian Asisten AI (Tahap D2, keputusan owner no. 12) — BERBASIS ATURAN, tanpa panggilan AI.

Kondisi berikut diperiksa sekali sehari (jam `asisten_peringatan_jam`, bawaan 07:00 WIB):

  omzet   toko yang omzet bulan berjalannya tertinggal > 10% dari laju target (target × hari lewat / hari
          dalam bulan; data s.d. kemarin). Sumber: `core.ukuran_penjualan.analitik_target` (definisi omzet
          baku, sama dengan layar Target). Toko tanpa data penjualan bulan ini tidak dianggap "nol".
  stok    bahan di bawah titik pesan ulang / stok minimum (jumlah). Sumber: `core.stock_thresholds.
          low_stock_alerts` (SSOT "stok rendah" yang juga dipakai layar Alert & Reorder dan bel stok).
  po      PO produksi yang sudah melewati tenggat dan barangnya belum lengkap. Sumber:
          `services.management_alerts.scan_management_alerts(dry_run=True)` (aturan yang sama dengan
          peringatan manajemen 07:00).
  piutang invoice piutang yang jatuh tempo hari ini atau sudah lewat dan masih bersisa. Sumber yang sama.
  merchandiser (12 Nov 2026, keputusan owner K-M9) — sumber `core.merchandiser` (layar Analisa Merchandiser):
          setiap hari model LARIS yang akan habis (persediaan + WIP < batas laris) dan model yang stoknya habis padahal
          masih terjual; setiap SENIN ringkasan model lambat/mati (nilai stok HPP terbesar) + PO/PR sepekan terakhir
          yang lolos pengaman Merchandiser dengan alasan. Penerima: owner, superadmin, PPIC.

Penerima mengikuti aturan yang sudah ada: owner selalu; ditambah PIC toko (`pic_user_id`) untuk omzet tokonya
sendiri, peran Gudang untuk stok (sama dengan notifikasi stok rendah), peran Produksi untuk PO, peran
Keuangan untuk piutang. Setiap kondisi dikirim PALING BANYAK SEKALI per hari per kelompok penerima
(klaim di `ai_proaktif_runs`), jadi jadwal yang terpicu ganda atau tombol "Jalankan sekarang" tidak membuat
notifikasi kembar. Satu notifikasi ringkas per kondisi — rincian per dokumen tetap dikirim fitur lamanya.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)

BATAS_TERTINGGAL_PERSEN = 10.0
MAKS_RINCI = 5
KONDISI = ("omzet", "stok", "po", "piutang", "laris_habis", "merchandiser_senin")
LABEL_KONDISI = {"omzet": "Omzet di bawah laju target", "stok": "Stok di bawah titik pesan ulang",
                 "po": "PO produksi lewat tenggat", "piutang": "Piutang jatuh tempo",
                 "laris_habis": "Model laris akan habis", "merchandiser_senin": "Ringkasan Merchandiser mingguan"}
SUBTYPE = {"omzet": "asisten_ai_marketing_omzet", "stok": "asisten_ai_stock_alert",
           "po": "asisten_ai_production_po", "piutang": "asisten_ai_invoice_due",
           "laris_habis": "asisten_ai_merchandiser", "merchandiser_senin": "asisten_ai_merchandiser"}
MENU = {"omzet": "marketing-targets", "stok": "wh-stock", "po": "prod-monitoring", "piutang": "fin-ar-360",
        "laris_habis": "mgmt-merchandiser", "merchandiser_senin": "mgmt-merchandiser"}
PERAN_MERCHANDISER = ("owner", "superadmin", "ppic")       # K-M9: owner + superadmin + PPIC
_BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
_BULAN_PANJANG = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
                  "Oktober", "November", "Desember")


@dataclass
class Kabar:
    """Satu notifikasi ringkas untuk satu kelompok penerima."""
    kondisi: str
    penerima: str                 # kunci kelompok penerima ("umum" atau id PIC) — bagian kunci sekali-sehari
    judul: str
    isi: str
    jumlah: int
    target_roles: list = field(default_factory=list)
    target_user_ids: list = field(default_factory=list)
    severity: str = "warning"


# ── Format ───────────────────────────────────────────────────────────────────
def tgl(d: date) -> str:
    return f"{d.day} {_BULAN[d.month - 1]} {d.year}"


def rp(v: float) -> str:
    """Rupiah singkat ala prompt sistem: Rp 412,6 jt / Rp 1,25 M / Rp 850 rb."""
    v = float(v or 0)
    neg = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e9:
        s = f"{a / 1e9:.2f}".rstrip("0").rstrip(".") + " M"
    elif a >= 1e6:
        s = f"{a / 1e6:.1f}".rstrip("0").rstrip(".") + " jt"
    elif a >= 1e3:
        s = f"{a / 1e3:.0f} rb"
    else:
        s = f"{a:.0f}"
    return f"{neg}Rp {s.replace('.', ',')}"


def _persen(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + "%"


def _sisa(n: int) -> str:
    return f" dan {n} lainnya" if n > 0 else ""


def _peran_owner() -> list:
    return ["owner"]


def _peran_portal(portal: str) -> list:
    try:
        from utils.notif_unified import alert_roles_for_portal
        return list(alert_roles_for_portal(portal))
    except Exception:  # noqa: BLE001 — daftar peran gagal dibaca → owner saja
        log.warning("Peringatan Asisten AI: peran portal %s gagal dibaca", portal, exc_info=True)
        return []


def _peran_gudang() -> list:
    """Penerima yang sama dengan notifikasi stok rendah (routes/rahaza_alerts.check_low_stock)."""
    try:
        from utils.notif_unified import real_target_roles
        return list(real_target_roles(["warehouse_manager", "manager_production", "superadmin"], "warehouse"))
    except Exception:  # noqa: BLE001
        return _peran_portal("warehouse")


# ── Pemeriksa ────────────────────────────────────────────────────────────────
async def cek_omzet(db, tanggal: date) -> list[Kabar]:
    """Toko yang tertinggal > 10% dari laju target bulan berjalan (data s.d. kemarin)."""
    if tanggal.day == 1:
        return []                       # belum ada hari yang lengkap di bulan ini
    from core import ukuran_penjualan as U
    kemarin = tanggal - timedelta(days=1)
    accounts = await db.marketing_platform_accounts.find(
        {"status": "active"}, {**U.PROYEKSI_TOKO, "pic_user_id": 1}).to_list(1000)
    accounts = [a for a in accounts if a.get("id")]
    if not accounts:
        return []
    pic = {a["id"]: a.get("pic_user_id") for a in accounts}
    bulan = f"{kemarin.year:04d}-{kemarin.month:02d}"
    hasil = await U.analitik_target(db, accounts, [bulan], hari_ini=kemarin)
    lambat, tanpa_data = [], 0
    for r in hasil.get("baris") or []:
        tgt = float(r.get("target_omzet") or 0)
        if tgt <= 0:
            continue
        akt = float(r.get("aktual_omzet") or 0)
        if akt <= 0:
            tanpa_data += 1             # data kosong ≠ omzet nol (aturan Asisten AI)
            continue
        dim = int(r.get("hari_dalam_bulan") or calendar.monthrange(kemarin.year, kemarin.month)[1])
        harus = tgt * int(r.get("hari_berlalu") or kemarin.day) / dim
        if harus <= 0:
            continue
        kurang = (harus - akt) / harus * 100
        if kurang > BATAS_TERTINGGAL_PERSEN:
            lambat.append({"toko_id": r.get("toko_id"), "toko": r.get("toko") or "Toko", "kurang": kurang,
                           "aktual": akt, "harus": harus, "pic": pic.get(r.get("toko_id"))})
    if not lambat:
        return []
    lambat.sort(key=lambda x: -x["kurang"])
    label_bulan = f"{_BULAN_PANJANG[kemarin.month - 1]} {kemarin.year}"

    def _isi(rows: list, *, catat_tanpa_data: bool) -> str:
        rinci = "; ".join(f"{x['toko']} tertinggal {_persen(x['kurang'])} ({rp(x['aktual'])} dari seharusnya "
                          f"{rp(x['harus'])})" for x in rows[:MAKS_RINCI])
        teks = (f"{len(rows)} toko tertinggal lebih dari {int(BATAS_TERTINGGAL_PERSEN)}% dari laju target "
                f"{label_bulan} (data s.d. {tgl(kemarin)}): {rinci}{_sisa(len(rows) - MAKS_RINCI)}.")
        if catat_tanpa_data and tanpa_data:
            teks += f" {tanpa_data} toko bertarget belum punya data penjualan bulan ini."
        return teks

    out = [Kabar("omzet", "umum", LABEL_KONDISI["omzet"], _isi(lambat, catat_tanpa_data=True), len(lambat),
                 target_roles=_peran_owner())]
    per_pic: dict[str, list] = {}
    for x in lambat:
        if x["pic"]:
            per_pic.setdefault(str(x["pic"]), []).append(x)
    for uid, rows in sorted(per_pic.items()):
        out.append(Kabar("omzet", uid, "Omzet toko Anda di bawah laju target", _isi(rows, catat_tanpa_data=False),
                         len(rows), target_user_ids=[uid]))
    return out


async def cek_stok(db, tanggal: date) -> list[Kabar]:
    from core import stock_thresholds
    rows = await stock_thresholds.low_stock_alerts(db)
    if not rows:
        return []
    kritis = sum(1 for r in rows if r.get("severity") == "critical")
    nama = ", ".join(str(r.get("material_name") or r.get("code") or "-")[:40] for r in rows[:MAKS_RINCI])
    isi = (f"{len(rows)} bahan di bawah titik pesan ulang atau stok minimum"
           + (f" ({kritis} kritis)" if kritis else "") + f". Paling mendesak: {nama}{_sisa(len(rows) - MAKS_RINCI)}.")
    return [Kabar("stok", "umum", LABEL_KONDISI["stok"], isi, len(rows),
                  target_roles=sorted(set(_peran_owner()) | set(_peran_gudang())),
                  severity="error" if kritis else "warning")]


async def _pindai_manajemen(db) -> dict:
    from services.management_alerts import scan_management_alerts
    return await scan_management_alerts(db, dry_run=True)


async def cek_po_dan_piutang(db, tanggal: date, *, pindai: Optional[dict] = None) -> list[Kabar]:
    data = pindai if pindai is not None else await _pindai_manajemen(db)
    out = []
    po = [a for a in (data.get("po_alerts") or []) if int(a.get("days_left") or 0) < 0]
    if po:
        po.sort(key=lambda a: int(a.get("days_left") or 0))
        rinci = ", ".join(f"{a.get('po_number') or '-'} ({abs(int(a.get('days_left') or 0))} hari)"
                          for a in po[:MAKS_RINCI])
        out.append(Kabar("po", "umum", LABEL_KONDISI["po"],
                         f"{len(po)} PO produksi sudah melewati tenggat dan barangnya belum lengkap. Terlama: "
                         f"{rinci}{_sisa(len(po) - MAKS_RINCI)}.", len(po),
                         target_roles=sorted(set(_peran_owner()) | set(_peran_portal("production"))),
                         severity="error"))
    ar = [a for a in (data.get("ar_alerts") or []) if int(a.get("days_left") or 0) <= 0]
    if ar:
        ar.sort(key=lambda a: int(a.get("days_left") or 0))
        total = sum(float(a.get("outstanding") or 0) for a in ar)
        lewat = sum(1 for a in ar if int(a.get("days_left") or 0) < 0)
        rinci = ", ".join(f"{a.get('invoice_number') or '-'}"
                          + (f" ({abs(int(a.get('days_left') or 0))} hari lewat)" if int(a.get('days_left') or 0) < 0
                             else " (hari ini)") for a in ar[:MAKS_RINCI])
        out.append(Kabar("piutang", "umum", LABEL_KONDISI["piutang"],
                         f"{len(ar)} invoice piutang jatuh tempo hari ini atau sudah lewat ({lewat} lewat), sisa "
                         f"{rp(total)}. Terlama: {rinci}{_sisa(len(ar) - MAKS_RINCI)}.", len(ar),
                         target_roles=sorted(set(_peran_owner()) | set(_peran_portal("finance"))),
                         severity="error" if lewat else "warning"))
    return out


def _model(r: dict) -> str:
    return f"{r.get('kode') or '-'} {str(r.get('nama') or '')[:24]}".strip()


def _angka(v: float) -> str:
    return f"{float(v or 0):,.0f}".replace(",", ".")


async def cek_merchandiser(db, tanggal: date) -> list[Kabar]:
    """Harian: model laris akan habis + habis padahal masih terjual. Senin: ringkasan lambat/mati + PO/PR yang lolos
    pengaman dengan alasan (7 hari). Angka dari SATU sumber `core.merchandiser` (sama dengan layar)."""
    from datetime import datetime, time, timezone
    from core import merchandiser as mc
    a = await mc.analisa(db, hari_ini=tanggal)
    peran = list(PERAN_MERCHANDISER)
    out: list[Kabar] = []
    cak = a.get("cakupan") or {}
    catatan = (f" Cakupan: {cak.get('persen_pcs_tertaut')}% penjualan terhubung ke model; stok memakai perkiraan."
               if cak.get("persen_pcs_tertaut") is not None else "")
    laris = sorted([r for r in a["baris"] if r["kelas"] == "laris"], key=lambda r: r["minggu_persediaan"])
    habis = sorted([r for r in a["baris"] if r["kelas"] == "habis"], key=lambda r: -r["laju_mingguan"])
    if laris or habis:
        bagian = []
        if laris:
            bagian.append(f"{len(laris)} model laris persediaannya kurang dari {a['ambang']['laris']:g} minggu: "
                          + ", ".join(f"{_model(r)} ({r['minggu_persediaan']:g} mgg, {r['laju_mingguan']:g} pcs/mgg)"
                                      for r in laris[:MAKS_RINCI]) + _sisa(len(laris) - MAKS_RINCI) + ".")
        if habis:
            bagian.append(f"{len(habis)} model stoknya habis padahal masih terjual: "
                          + ", ".join(f"{_model(r)} ({r['laju_mingguan']:g} pcs/mgg)" for r in habis[:MAKS_RINCI])
                          + _sisa(len(habis) - MAKS_RINCI) + ".")
        out.append(Kabar("laris_habis", "umum", LABEL_KONDISI["laris_habis"],
                         " ".join(bagian) + " Cek bahan & jadwalkan PO produksi bila marginnya baik." + catatan,
                         len(laris) + len(habis), target_roles=peran, severity="warning"))
    if tanggal.weekday() == 0:
        rugi = sorted([r for r in a["baris"] if r["kelas"] in ("lambat", "mati")],
                      key=lambda r: -float(r.get("nilai_stok_hpp") or 0))
        mulai = datetime.combine(tanggal - timedelta(days=7), time.min, tzinfo=timezone.utc) - timedelta(hours=7)
        lolos = await mc.jejak_pengaman(db, sejak=mulai)
        if rugi or lolos:
            ring = a["ringkasan"]
            bagian = []
            if rugi:
                nilai = sum(float(r.get("nilai_stok_hpp") or 0) for r in rugi)
                bagian.append(
                    f"{ring['lambat']['baris']} model lambat dan {ring['mati']['baris']} model mati, stok "
                    f"{_angka(sum(r['stok_perkiraan'] for r in rugi))} pcs senilai {rp(nilai)} (HPP). Terbesar: "
                    + ", ".join(f"{_model(r)} ({_kelas(mc, r)}, {rp(r.get('nilai_stok_hpp'))})"
                                for r in rugi[:MAKS_RINCI]) + _sisa(len(rugi) - MAKS_RINCI)
                    + ". Saran: stop produksi & pembelian bahannya, dorong penjualan (promo, pindah toko, bundling).")
            if lolos:
                bagian.append(f"{len(lolos)} dokumen sepekan terakhir lolos pengaman dengan alasan: "
                              + "; ".join(f"{x['jenis']} {x['nomor'] or '-'} oleh {x['oleh'] or '-'} — "
                                          f"\"{str(x['alasan'])[:60]}\"" for x in lolos[:MAKS_RINCI])
                              + _sisa(len(lolos) - MAKS_RINCI) + ".")
            out.append(Kabar("merchandiser_senin", "umum", LABEL_KONDISI["merchandiser_senin"],
                             " ".join(bagian) + catatan, len(rugi) + len(lolos), target_roles=peran,
                             severity="warning"))
    return out


def _kelas(mc, r: dict) -> str:
    return str(mc.LABEL_KELAS.get(r["kelas"], r["kelas"])).lower()


PEMERIKSA: tuple[tuple[str, Callable[..., Awaitable[list]]], ...] = (
    ("omzet", cek_omzet),
    ("stok", cek_stok),
    ("po_piutang", cek_po_dan_piutang),
    ("merchandiser", cek_merchandiser),
)


async def periksa_semua(db, tanggal: date) -> tuple[list[Kabar], dict]:
    """(daftar kabar, {pemeriksa: "ok"|"gagal"}). Satu pemeriksa gagal tidak menghentikan yang lain."""
    kabar: list[Kabar] = []
    status: dict = {}
    for kode, fn in PEMERIKSA:
        try:
            kabar += await fn(db, tanggal)
            status[kode] = "ok"
        except Exception:  # noqa: BLE001 — data rusak di satu domain tidak boleh mematikan peringatan lain
            log.exception("Peringatan Asisten AI: pemeriksa %s gagal", kode)
            status[kode] = "gagal"
    return kabar, status
