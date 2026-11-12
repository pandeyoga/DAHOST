"""Aturan katalog aksi Asisten ERP (keputusan owner K1–K10, 12 Nov 2026) — SATU sumber untuk pembuat katalog
(`scripts/asisten_katalog/buat_katalog.py`) dan alat `jalankan_aksi` (diperiksa ulang saat kartu dibuat & dijalankan).

Golongan risiko per aksi:
  A data biasa · B gerak stok · C uang / buku besar · D pengaturan / keamanan.
Golongan ditetapkan per MODUL route (daftar di bawah), dengan pengecualian per alamat (`PENGECUALIAN_GOLONGAN`).

Di luar katalog sama sekali (K1): aksi bukti diri (`MODUL_DIRI`), pengaturan Asisten sendiri (`MODUL_ASISTEN`),
pintu yang tidak dipanggil layar aktif.

Larangan (aksi ada di layar, tetapi TIDAK boleh lewat Asisten):
  K5 scan & hitung fisik gudang · K6 kunci/buka periode & tutup tahun · K7 pengguna, peran & izin, akun portal luar,
  cadangan & pemulihan, kunci integrasi, pengaturan sistem & Asisten, isi contoh/awal sistem · K8 hapus permanen.
"""
from __future__ import annotations

import re
from typing import Optional

GOLONGAN = {"A": "Data biasa", "B": "Gerak stok", "C": "Uang / buku besar", "D": "Pengaturan / keamanan"}
GOLONGAN_KUNCI = tuple(GOLONGAN)
GOLONGAN_SAKLAR = ("B", "C", "D")     # A menyala untuk setiap akun yang Asistennya aktif (K3)
PERAN_SEMUA_GOLONGAN = frozenset({"owner", "superadmin"})
PERAN_BOLEH_D = frozenset({"owner", "superadmin", "admin"})   # D hanya untuk peran ini (dan saklarnya menyala)

# ── K1: di luar katalog ──────────────────────────────────────────────────────
MODUL_ASISTEN = frozenset({"asisten_ai_routes", "portal_assistant_routes", "dewi_ai_actions",
                           "asisten_ai_berkas_routes", "asisten_ai_laporan_routes"})
MODUL_DIRI = frozenset({"auth_routes", "rahaza_auto_attendance_selfie", "rahaza_auto_attendance_webauthn",
                        "rahaza_attendance_sessions", "dewi_push_notifications", "lms_student", "study_groups"})

# ── golongan per modul route ─────────────────────────────────────────────────
MODUL_D = frozenset({
    "access_sync", "admin", "admin_backup", "ai_usage_monitor", "cron_jobs", "data_transfer", "dewi_client_admin",
    "dewi_system_config", "doc_numbering", "master_sync", "notification_categories", "operations_pdf_configs",
    "pdf_document_settings", "pdf_templates", "rahaza_admin", "rahaza_approval_delegation",
    "rahaza_auto_attendance_config", "rahaza_auto_attendance_zkteco", "rahaza_coa", "coa_auto",
    "rahaza_channel_gl_mapping", "employee_expense_gl_mapping", "rahaza_posting_profiles", "rahaza_hr_seed",
    "rahaza_integrations", "rahaza_periods", "rahaza_setup", "rahaza_year_end", "sync_audit",
    "marketing_integration_settings_routes", "marketing_webhooks", "dewi_scheduler", "operations_import",
    "rahaza_alerts", "marketing_alerts",
})
MODUL_C = frozenset({
    "dewi_bank_reconciliation", "dewi_kasbon", "dewi_maklon_billing", "dewi_maklon_finance",
    "dewi_accessories_valuation", "dewi_rnd_hpp", "employee_expense_claims", "employee_per_diem",
    "employee_travel_requests", "employee_travel_settlements", "invoice_edit_requests", "marketing_settlements",
    "marketing_withdrawals", "marketing_kol_incentive", "rahaza_accruals", "rahaza_ap_from_gr",
    "rahaza_bank_transfers", "rahaza_employee_loans", "rahaza_finance", "rahaza_fixed_assets", "rahaza_hpp",
    "rahaza_intercompany", "rahaza_journal_import", "rahaza_journals", "rahaza_opening_balance",
    "rahaza_payroll_allowances", "rahaza_payroll_payslips", "rahaza_payroll_profiles", "rahaza_payroll_runs",
    "rahaza_petty_cash", "rahaza_salary_adjustments", "rahaza_salary_grades", "rahaza_purchase_returns",
    "product_costing", "production_maklon_bridge", "asset.depreciation_batch", "asset.depreciation_per",
    "asset.disposal", "sales_direct", "dewi_accessories_purchase", "wh_scan_out", "rahaza_budget",
    "marketing_impor_paket", "dewi_maklon_pos",
})
MODUL_B = frozenset({
    "buyer_shipment", "cutting", "dewi_accessories_stock", "dewi_cmt_packing", "dewi_cmt_permak",
    "dewi_maklon_qc", "dewi_wh_returns", "dewi_warehouse_smart", "fulfillment", "kirim_cmt_routes",
    "marketing_catalog_stock", "marketing_returns_routes", "production_execution", "production_internal_adapter",
    "production_material_returns", "production_stage_tracking", "rahaza_aql", "rahaza_fg_matrix", "rahaza_grn_qc",
    "rahaza_inventory_fg", "rahaza_inventory_issues", "rahaza_inventory_materials", "rahaza_inventory_stock",
    "rahaza_inventory_workflow", "rahaza_shift_handover", "rahaza_shipments", "universal_scan", "vendor_shipment",
    "dewi_online_orders", "exceptions", "cmt_override_routes",
})
AWALAN_MODUL_B = ("wms_",)

# Aksi tertentu yang golongannya berbeda dari modulnya (urutan = prioritas).
PENGECUALIAN_GOLONGAN = (
    (r"^/api/production-pos/\{[^}]+\}/(close|close-short|quick-complete|sync-maklon-finance)$", "C"),  # denda/HPP
    (r"^/api/rahaza/purchase-orders/\{[^}]+\}/(create-gr|items/\{[^}]+\}/price)$", "C"),
    (r"^/api/dewi/maklon/pos/\{[^}]+\}/confirm$", "C"),        # piutang/hutang maklon terbit saat konfirmasi
    (r"^/api/dewi/maklon/(dispatches|material-receive)", "B"),
    (r"^/api/vendor-portal/accounts", "D"),                     # akun login vendor
    (r"^/api/vendor-portal/partners", "A"),                     # master vendor CMT
    (r"^/api/vendor-portal/my-jobs", "B"),
    (r"^/api/approvals/(chains|seed-missing-chains)", "D"),
    (r"^/api/(users|roles)(/|$)", "D"),
)

# ── larangan ─────────────────────────────────────────────────────────────────
# (kode keputusan, pola alamat, metode atau None = semua, alasan untuk pengguna)
LARANGAN = (
    ("K5", r"^/api/wms/opname3/(scan|count|line|scan-undo)$", None,
     "Hasil scan dan hitungan opname adalah bukti fisik di gudang, jadi diisi langsung di layar Opname."),
    ("K5", r"^/api/wh/scan-out/(scan|pick)$", None,
     "Scan keluar penjualan adalah bukti fisik barang keluar, jadi dilakukan langsung di layar Scan Keluar."),
    ("K5", r"^/api/wms/pending/\{[^}]+\}/(scan-in|scan-out)$", None,
     "Scan masuk/keluar barang adalah bukti fisik di gudang, jadi dilakukan langsung di layar gudang."),
    ("K5", r"^/api/assets/\{[^}]+\}/scan$", None,
     "Scan label aset adalah bukti fisik keberadaan aset, jadi dilakukan langsung di layar Aset."),
    ("K6", r"^/api/rahaza/periods/\{[^}]+\}/(close|lock|reopen)$", None,
     "Tutup, kunci, dan buka periode akuntansi hanya dilakukan langsung di layar Keuangan."),
    ("K6", r"^/api/rahaza/year-end/", None,
     "Tutup tahun dan pembalikannya hanya dilakukan langsung di layar Keuangan."),
    ("K7", r"^/api/(users|roles)(/|$)", None,
     "Pengguna, peran, dan izin hanya diatur langsung di layar Sistem."),
    ("K7", r"^/api/admin/access-sync", None, "Sinkron hak akses hanya dilakukan langsung di layar Sistem."),
    ("K7", r"^/api/rahaza/delegations", None,
     "Pelimpahan wewenang persetujuan hanya diatur langsung di layar terkait."),
    ("K7", r"^/api/dewi/maklon/clients/\{[^}]+\}/(portal-accounts|provision-portal)", None,
     "Akun login portal klien hanya diatur langsung di layar Maklon."),
    ("K7", r"^/api/vendor-portal/accounts", None, "Akun login portal vendor hanya diatur langsung di layar terkait."),
    ("K7", r"^/api/admin/backup", None, "Cadangan, pemulihan, dan pengosongan data hanya di layar Sistem."),
    ("K7", r"^/api/(rahaza|marketing)/integration-settings", None,
     "Kunci integrasi hanya diatur langsung di layar Pengaturan."),
    ("K7", r"^/api/marketing/webhooks/manual$", None, "Kiriman data platform tiruan hanya dari layar Integrasi."),
    ("K7", r"^/api/dewi/system/config", None,
     "Pengaturan sistem (termasuk kunci layanan) hanya diatur langsung di layar Sistem."),
    ("K7", r"^/api/ai/", None, "Pengaturan Asisten AI hanya diatur owner langsung di Monitor AI."),
    ("K7", r"^/api/asisten-ai/", None, "Pengaturan Asisten AI hanya diatur langsung di layarnya."),
    ("K7", r"(^|/)(seed|seed-[\w-]+|seed-all-accounting|seed-sample|seed-default|seed-missing-chains)$", None,
     "Isi contoh/awal sistem tidak dijalankan lewat Asisten."),
    ("K7", r"^/api/rahaza/hr-seed/", None, "Isi contoh/awal sistem tidak dijalankan lewat Asisten."),
    ("K8", r"^/api/rahaza/coa/accounts/\{[^}]+\}$", "DELETE",
     "Menghapus akun dari bagan akun bersifat permanen, jadi hanya dilakukan langsung di layar."),
)
_LARANGAN_RX = tuple((k, re.compile(p), m, a) for k, p, m, a in LARANGAN)

# K8: parameter yang menghapus PERMANEN; Asisten hanya boleh menonaktifkan / hapus biasa.
QUERY_HAPUS_PERMANEN = frozenset({"hard", "permanent", "permanen", "purge", "force_delete"})
PESAN_HAPUS_PERMANEN = ("Asisten hanya boleh menonaktifkan atau menghapus biasa. Hapus permanen hanya dilakukan "
                        "langsung di layar.")

TINGKAT = ("rendah", "menengah", "tinggi")

# ── Bacaan layar (12 Nov 2026, "semuanya bisa dilakukan") ────────────────────
# Asisten boleh membaca GET yang dipakai layar aktif (izin peran pengguna sendiri, data pribadi disamarkan), supaya
# bisa menemukan id/kode data yang dituju aksi. Tidak termasuk: rahasia/kunci, cadangan, pengaturan sistem & Asisten,
# serta unduhan berkas (PDF/Excel/gambar/label) dan aliran data.
LARANGAN_BACA = (
    r"^/api/admin/backup", r"^/api/(rahaza|marketing)/integration-settings", r"^/api/dewi/system/config",
    r"^/api/ai/", r"^/api/asisten-ai/", r"^/api/auth/", r"(^|/)(token|tokens|secret|secrets|api-keys?|password|passwords)(/|$)",
)
_LARANGAN_BACA_RX = tuple(re.compile(p) for p in LARANGAN_BACA)
_BERKAS_BACA_RX = re.compile(r"(^|/|-|_)(export|exports|download|downloads|unduh|pdf|xlsx|excel|csv|print|cetak|"
                             r"label|labels|barcode|qr|photo|photos|image|images|avatar|thumbnail|file|files|stream|"
                             r"sse|upload|uploads)(/|$|-|_|\.)", re.I)
# Ruang Asisten (alat_base.RUANG) → portal yang aksinya/bacaannya ditawarkan; umum = semua.
PORTAL_RUANG = {"sdm": ("SDM",), "saya": ("Portal Saya",)}


def larangan_baca(jalur: str) -> Optional[str]:
    """Alasan alamat GET ini tidak boleh dibaca Asisten, atau None."""
    if any(rx.search(jalur) for rx in _LARANGAN_BACA_RX):
        return "Data rahasia/pengaturan sistem tidak dibaca lewat Asisten."
    if _BERKAS_BACA_RX.search(jalur) or ":path}" in jalur:
        return "Unduhan berkas (PDF/Excel/gambar/label) dibuka langsung di layar."
    return None


def di_ruang(portal: list, ruang: Optional[str]) -> bool:
    """Aksi/bacaan dengan daftar portal ini ditawarkan di ruang Asisten tersebut?"""
    boleh = PORTAL_RUANG.get(str(ruang or "umum"))
    return True if boleh is None else any(p in boleh for p in (portal or []))


def golongan_untuk(modul: str, jalur: str) -> str:
    """Golongan A/B/C/D satu aksi (modul = nama modul route tanpa awalan `routes.`)."""
    for pola, g in PENGECUALIAN_GOLONGAN:
        if re.search(pola, jalur):
            return g
    if modul in MODUL_D:
        return "D"
    if modul in MODUL_C:
        return "C"
    if modul in MODUL_B or modul.startswith(AWALAN_MODUL_B):
        return "B"
    return "A"


def di_luar_katalog(modul: str) -> Optional[str]:
    """Alasan aksi TIDAK masuk katalog sama sekali (K1), atau None."""
    if modul in MODUL_ASISTEN or modul.startswith("asisten"):
        return "pengaturan Asisten sendiri"
    if modul in MODUL_DIRI:
        return "bukti diri (absen selfie/sidik jari/passkey, sandi, kuis belajar, langganan notifikasi)"
    return None


def larangan_untuk(metode: str, jalur: str) -> Optional[dict]:
    """{kode, alasan} bila aksi ini dilarang lewat Asisten (K5–K8), atau None."""
    for kode, rx, m, alasan in _LARANGAN_RX:
        if (m is None or m == metode) and rx.search(jalur):
            return {"kode": kode, "alasan": alasan}
    return None


def tingkat_untuk(golongan: str, jenis: str) -> str:
    """Tingkat risiko kartu: A buat/ubah/aksi rendah, A hapus menengah, B menengah, C/D tinggi."""
    if golongan in ("C", "D"):
        return "tinggi"
    if golongan == "B":
        return "menengah"
    return "menengah" if jenis == "hapus" else "rendah"


def golongan_efektif(peran: str, atur: Optional[dict]) -> dict:
    """{A..D: bool} golongan yang boleh dipakai satu akun (K3). Owner/superadmin selalu semua. B/C/D mati sampai
    owner menyalakan per orang; D hanya untuk owner/superadmin/admin."""
    peran = str(peran or "").lower()
    if peran in PERAN_SEMUA_GOLONGAN:
        return {g: True for g in GOLONGAN_KUNCI}
    atur = atur if isinstance(atur, dict) else {}
    out = {"A": True}
    for g in GOLONGAN_SAKLAR:
        out[g] = atur.get(g) is True
    if peran not in PERAN_BOLEH_D:
        out["D"] = False
    return out
