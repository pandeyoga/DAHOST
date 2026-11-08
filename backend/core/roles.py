"""core.roles — SATU konstanta peran keuangan/approver (T-08).

Peran yang benar-benar di-seed di aplikasi ini: `accounting`, `staff_keuangan`,
`manager_keuangan` (bukan `finance`). Nama generik tetap dipertahankan untuk
kompatibilitas data lama.
"""
FINANCE_ROLES = ("superadmin", "admin", "owner", "accounting", "staff_keuangan",
                 "manager_keuangan", "finance", "finance_manager", "accountant")
APPROVER_ROLES = FINANCE_ROLES + ("hr", "hr_manager", "manager")

# 2026-11-08: izin PASANGAN daftar peran di atas untuk klaim biaya & perjalanan dinas. Gerbang memakai
# `auth.check_role(user, <daftar peran>, <izin>)` supaya peran buatan owner ("Accounting & Finance",
# "HR Generalist", …) lolos bila izinnya dicentang di Peran & Hak Akses. Kuncinya dari katalog izin:
#   hr.approve          "Setujui izin, cuti, lembur & klaim" (modul Klaim Dinas, aksi Approve)
#   finance.approve     persetujuan sisi Keuangan (menu Penyelesaian Perjalanan Dinas, aksi Approve)
#   finance.manage      "Kelola jurnal, COA & periode" (sama dengan `_require_fin` di rute keuangan)
#   fin.payment.manage  "Kelola pembayaran" (modul Kas & Bank) — tidak pernah tersirat dari modul SDM,
#                       jadi pemisahan tugas K25 (HR tidak membayar) tetap utuh.
EXPENSE_APPROVE_PERMS = ("hr.approve",)
SETTLEMENT_APPROVE_PERMS = ("hr.approve", "finance.approve")
FINANCE_PAY_PERMS = ("finance.manage", "fin.payment.manage")
FINANCE_BOOK_PERMS = ("finance.manage",)
# Kas & bank (transfer bank, kas kecil, uang muka dari rekening) — "Kelola kas & bank"; hanya tersirat dari
# modul Keuangan (Kas & Bank, Kas Kecil, Transfer Bank, Rekonsiliasi), tidak dari modul SDM.
FINANCE_CASH_PERMS = ("fin.cash.manage", "finance.manage")
# Melihat klaim / dinas / penyelesaian SEMUA karyawan = siapa pun yang berhak memutuskan atau membayarnya.
EXPENSE_VIEW_ALL_PERMS = EXPENSE_APPROVE_PERMS + FINANCE_PAY_PERMS
SETTLEMENT_VIEW_ALL_PERMS = SETTLEMENT_APPROVE_PERMS + FINANCE_PAY_PERMS

# FASE 2.3 (T-01): peran per domain untuk gerbang eksplisit endpoint DELETE.
# `core.authz.require_roles` selalu meloloskan superadmin/admin; owner/manager disebut eksplisit.
MGMT_ROLES = ("owner", "manager")
HR_ROLES = MGMT_ROLES + ("hr", "hr_manager", "staff_hr")
PRODUCTION_ROLES = MGMT_ROLES + ("admin_produksi", "supervisor_produksi", "spv_cuting", "supervisor")
WAREHOUSE_ROLES = MGMT_ROLES + ("admin_gudang", "spv_packing", "admin_aksesoris",
                                "admin_produksi", "supervisor_produksi")
RND_ROLES = MGMT_ROLES + ("rnd_staff",)
MAKLON_ROLES = MGMT_ROLES + ("admin_maklon",)
MARKETING_ROLES = MGMT_ROLES + ("marketing_kol", "pic_toko")
MARKETING_CS_ROLES = MARKETING_ROLES + ("cs_staff",)

# 2026-11-07 (Tahap 6, SY2 — keputusan owner): yang boleh MENGUBAH Pengaturan Sistem (dewi_system_config,
# termasuk kunci rahasia). Cermin layar: `frontend/src/lib/systemConfigRoles.js`.
SYSTEM_CONFIG_ROLES = ("superadmin", "admin", "owner")
