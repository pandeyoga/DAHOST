"""core.roles — SATU konstanta peran keuangan/approver (T-08).

Peran yang benar-benar di-seed di aplikasi ini: `accounting`, `staff_keuangan`,
`manager_keuangan` (bukan `finance`). Nama generik tetap dipertahankan untuk
kompatibilitas data lama.
"""
FINANCE_ROLES = ("superadmin", "admin", "owner", "accounting", "staff_keuangan",
                 "manager_keuangan", "finance", "finance_manager", "accountant")
APPROVER_ROLES = FINANCE_ROLES + ("hr", "hr_manager", "manager")

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
