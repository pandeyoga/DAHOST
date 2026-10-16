"""module_catalog.py — izin GRANULAR per modul (Lihat/Tambah/Ubah/Hapus/Approve/Export).

SSOT lapisan izin per-modul untuk semua portal internal KECUALI Maklon, Administrasi
Sistem & Kolaborasi (yang tetap memakai katalog lama di `permission_catalog.py`).

Tiap modul:
  id      : dipakai di kunci izin `mod.<id>.<aksi>`
  portal  : portal pemilik (sesuai `routes/shared.PORTAL_ACCESS`)
  menus   : id pintu menu (`portalNav.js`) yang disembunyikan bila tidak punya `view`
  paths   : prefix API yang dijaga `middleware/module_permission_gate.py`
  actions : aksi yang tersedia untuk modul ini
  implies : aksi -> kunci izin lama yang ikut diberikan (supaya penjaga lama tetap lolos);
            'manage' berlaku untuk create/edit/delete
  extras  : izin khusus lama yang tetap ditampilkan di modul ini
  lookup  : True = GET boleh untuk semua staf internal (data acuan dropdown lintas portal)

MODEL PENEGAKAN (per portal, "fallback aman"):
  peran yang BELUM diberi satu pun izin `mod.*` pada portal X -> aturan lama berlaku;
  begitu owner mencentang izin granular di portal X, setiap modul portal X wajib izinnya.
"""
from __future__ import annotations

import re

ACTIONS = ("view", "create", "edit", "delete", "approve", "export")
ACTION_LABELS = {
    "view": "Lihat", "create": "Tambah", "edit": "Ubah",
    "delete": "Hapus", "approve": "Approve", "export": "Export",
}
_VE = ("view", "export")
_VAE = ("view", "approve", "export")
_ALL = ACTIONS
_CRUD = ("view", "create", "edit", "delete", "export")

PORTAL_LABELS = {
    "management": "Manajemen", "production": "Produksi", "cutting": "Cutting",
    "procurement": "Pengadaan", "warehouse": "Gudang", "accessories": "Aksesoris",
    "finance": "Keuangan", "sales": "Penjualan", "hr": "SDM / HRIS", "toko": "Marketing / Toko",
    "rnd": "RnD & Desain", "assets": "Manajemen Aset", "maklon": "Maklon",
}
GRANULAR_PORTALS = tuple(PORTAL_LABELS)


def _m(portal, mid, label, menus, paths=(), actions=_ALL, implies=None, extras=(), lookup=False):
    return {"portal": portal, "id": mid, "label": label, "menus": list(menus), "paths": list(paths),
            "actions": list(actions), "implies": implies or {}, "extras": list(extras), "lookup": lookup}


_TOKO = {"view": ["toko.view"], "manage": ["toko.manage"], "approve": ["toko.approve"]}
_MAKLON = {"view": ["maklon.view"], "manage": ["maklon.manage"], "approve": ["maklon.approve"]}

MODULES: list[dict] = [
    # ── MANAJEMEN ───────────────────────────────────────────────────────────
    _m("management", "mgmt_dashboard", "Dashboard & Ringkasan Eksekutif",
       ["management-dashboard", "mgmt-overview"],
       ["/api/rahaza/management", "/api/management", "/api/reports/executive", "/api/ai-business"], _VE,
       {"view": ["dashboard.view", "management.view"], "export": ["report.export"]}),
    _m("management", "mgmt_reports", "Pusat Laporan", ["reports-hub", "phase7-reports", "mgmt-reports", "rnd-dashboard"],
       ["/api/dewi/reports", "/api/rahaza/reports-hub", "/api/rahaza/reports"], _VE,
       {"view": ["report.view"], "export": ["report.export"]}),
    _m("management", "mgmt_approval", "Pusat Approval & Approval Bertingkat",
       ["unified-approval-hub", "approval-multilevel"], ["/api/approvals", "/api/approval-inbox"], _ALL,
       {"view": ["management.view"], "manage": ["management.manage"], "approve": ["hr.approve"]}),
    _m("management", "mgmt_okr", "OKR Tracker", ["mgmt-okr"], ["/api/management/okr"], _CRUD,
       {"manage": ["management.manage"]}),
    _m("management", "mgmt_marketing_cycle", "Siklus Marketing", ["mgmt-marketing-cycle"],
       ["/api/marketing/cycle"], ("view", "edit", "export")),
    _m("management", "mgmt_digest", "Digest Mingguan & Audit Manajemen", ["mgmt-tools"],
       ["/api/management/weekly-digest", "/api/management/audit"], _VE),
    _m("management", "mgmt_ai_usage", "Monitor AI", ["ai-usage-monitor"], ["/api/ai/usage"], _VE),

    # ── PRODUKSI ────────────────────────────────────────────────────────────
    _m("production", "prod_master_product", "Master Produk (Model & Varian)", ["prod-master-product-hub"],
       ["/api/rahaza/models", "/api/products", "/api/garments", "/api/product-variants",
        "/api/rahaza/variants", "/api/variant-onboarding"], _ALL,
       {"view": ["products.view"], "create": ["products.create"], "edit": ["products.edit"],
        "delete": ["products.delete"], "approve": ["production.approve"]}, lookup=True),
    _m("production", "prod_master_process", "Master Proses, Line & Mesin", ["prod-master-process-hub"],
       ["/api/rahaza/processes", "/api/rahaza/lines", "/api/rahaza/machines", "/api/rahaza/line-assignments",
        "/api/rahaza/production-calendar", "/api/rahaza/sop", "/api/rahaza/downtime",
        "/api/rahaza/shift-handovers", "/api/rahaza/handover-templates"], _CRUD,
       {"view": ["prod.line.view"], "manage": ["prod.master.manage", "prod.line.manage"]},
       extras=[("prod.process.input", "input", "Catat output per proses"),
               ("operator.view", "view", "Buka Layar Operator"),
               ("operator.input", "input", "Input output line (operator)")], lookup=True),
    _m("production", "prod_vendor_cmt", "Vendor CMT & Input Vendor", ["vendor-admin", "cmt-override-portal"],
       ["/api/vendor-portal/accounts", "/api/vendor-portal/partners", "/api/cmt-override"], _CRUD,
       {"view": ["cmt.view"], "manage": ["production.manage"]}),
    _m("production", "prod_po", "PO Produksi Internal", ["prod-pos-internal", "po-closure"],
       ["/api/production-pos", "/api/po-items", "/api/po-accessories", "/api/po-items-produced",
        "/api/rahaza/orders", "/api/rahaza/orders-statuses"], _ALL,
       {"view": ["orders.view"], "manage": ["orders.manage"], "approve": ["production.approve"]}),
    _m("production", "prod_vendor_shipment", "Kirim Material CMT", ["prod-shipments-vendor"],
       ["/api/vendor-shipments", "/api/vendor-material-inspections", "/api/material-requests",
        "/api/material-defect-reports"], _ALL,
       {"view": ["shipment.view"], "create": ["vendor_shipment.create", "shipment.create"],
        "edit": ["vendor_shipment.update", "shipment.update"],
        "delete": ["vendor_shipment.delete", "shipment.delete"], "approve": ["shipment.dispatch"]}),
    _m("production", "prod_cmt_receive", "Terima FG dari CMT", ["da-cmt-receive"],
       ["/api/prod/cmt-receipts", "/api/prod/cmt-reject-queue", "/api/prod/short-shipments",
        "/api/dewi/cmt-intake", "/api/dewi/cmt/lifecycle"], _ALL,
       {"view": ["cmt.view"], "manage": ["cmt.intake.manage"], "approve": ["cmt.approve"]}),
    _m("production", "prod_cmt_permak", "Permak / Perbaikan CMT", ["cmt-permak"], ["/api/dewi/cmt-permak"], _ALL,
       {"view": ["cmt.view"], "manage": ["cmt.permak.manage"], "approve": ["cmt.approve"]}),
    _m("production", "prod_cmt_monitor", "Monitoring CMT & Komponen Kurang",
       ["cmt-monitor", "cmt-component-requests"],
       ["/api/dewi/cmt-component-requests", "/api/dewi/cmt-kejar", "/api/dewi/cmt-recon"], _ALL,
       {"view": ["cmt.view"], "manage": ["cmt.kejar.manage"], "approve": ["cmt.approve"]}),
    _m("production", "prod_buyer_shipment", "Serah Terima FG / Dispatch", ["prod-shipments-buyer"],
       ["/api/buyer-shipments", "/api/buyer-shipment-items", "/api/buyer-shipment-dispatches",
        "/api/buyer-dispatch-capacity", "/api/buyer-dispatch-outstanding", "/api/buyer-receipt-variance",
        "/api/buyer-shorts", "/api/rahaza/shipments"], _ALL,
       {"view": ["shipment.view"], "create": ["shipment.create"], "edit": ["shipment.update", "shipment.manage"],
        "delete": ["shipment.delete"], "approve": ["shipment.dispatch"]}),
    _m("production", "prod_dashboard", "Dashboard & Pusat Kendali Produksi",
       ["production-dashboard", "prod-control-tower"],
       ["/api/prod/dashboard", "/api/prod/control-tower", "/api/rahaza/wip", "/api/rahaza/line-board",
        "/api/capacity", "/api/rahaza/supervisor", "/api/prod/display-rak", "/api/prod/material-summary-by-location"],
       _VE, {"view": ["prod.dashboard.view", "prod.wip.view", "prod.line.view"]}),
    _m("production", "prod_jobs", "Production Jobs & Tracking", ["prod-work-orders", "prod-monitoring"],
       ["/api/production-jobs", "/api/production-job-items", "/api/production-progress", "/api/production-tracking",
        "/api/work-orders", "/api/recalculate-jobs", "/api/production-returns"], _ALL,
       {"view": ["wo.view", "orders.view"], "manage": ["wo.manage"], "approve": ["production.approve"]}),
    _m("production", "prod_variance", "Laporan Variance", ["prod-variance", "prod-variance-report"],
       ["/api/production-variances"], ("view", "edit", "approve", "export"),
       {"view": ["orders.view"], "approve": ["production.approve"]}),
    _m("production", "prod_cmt_billing", "Invoice CMT & Belanja CMT", ["prod-cmt-billing"],
       ["/api/production/cmt-billing", "/api/dewi/cmt-belanja"], _ALL,
       {"view": ["cmt.view", "fin.ap.view"], "manage": ["cmt.belanja.manage"], "approve": ["cmt.approve"]}),
    _m("production", "prod_sewing_cost", "Biaya Jahit", ["prod-sewing-cost"], ["/api/production/sewing-cost"], _CRUD,
       {"view": ["hpp.view"], "manage": ["hpp.manage"]}),
    _m("production", "prod_material_req", "Kebutuhan & Retur Material", ["prod-material-requirements"],
       ["/api/rahaza/material-requirements", "/api/production/material-returns"], _ALL,
       {"view": ["bom.view"], "approve": ["inventory.approve"]}),
    _m("production", "prod_analytics", "Analitik & Estimasi AI Produksi", ["prod-analytics-hub", "prod-ai-insights"],
       ["/api/rahaza/ai", "/api/analytics/ai"], ("view", "create", "export"), {"view": ["prod.dashboard.view"]}),
    _m("production", "prod_maintenance", "Perawatan Mesin", ["prod-predictive-maintenance"],
       ["/api/production/predictive-maintenance"], _CRUD, {"manage": ["prod.master.manage"]}),

    # ── CUTTING ─────────────────────────────────────────────────────────────
    _m("cutting", "cut_dashboard", "Dashboard Cutting", ["cutting-dashboard"], ["/api/cutting/dashboard"], _VE,
       {"view": ["cutting.view"]}),
    _m("cutting", "cut_orders", "Order Cutting", ["cutting-orders"], ["/api/cutting"], _ALL,
       {"view": ["cutting.view"], "manage": ["cutting.manage"], "approve": ["cutting.approve"]},
       extras=[("cutting.input", "input", "Catat hasil / bundling cutting")]),
    _m("cutting", "cut_panels", "Master Potongan", ["cutting-panels"], ["/api/cutting/panels"], _CRUD,
       {"view": ["cutting.view"], "manage": ["cutting.manage"]}),

    # ── PENGADAAN ───────────────────────────────────────────────────────────
    _m("procurement", "proc_dashboard", "Dashboard, Penilaian & Analisis Belanja",
       ["proc-dashboard", "proc-scorecard", "proc-analytics"],
       ["/api/procurement/dashboard", "/api/procurement/overview", "/api/procurement/pipeline",
        "/api/procurement/spend-analysis", "/api/procurement/supplier-scorecard"], _VE,
       {"view": ["purchasing.view"]}),
    _m("procurement", "proc_suppliers", "Master Supplier & Daftar Harga", ["proc-suppliers"],
       ["/api/procurement/suppliers", "/api/procurement/price-lookup"], _ALL,
       {"view": ["proc.supplier.view"], "manage": ["proc.supplier.manage"]}, lookup=True),
    _m("procurement", "proc_requests", "Permintaan Pengadaan (PR)", ["proc-requests"],
       ["/api/procurement/requests", "/api/procurement/inbox", "/api/procurement/request-types"], _ALL,
       {"view": ["proc.pr.view"], "manage": ["proc.pr.manage"], "approve": ["proc.pr.approve"]},
       extras=[("proc.pr.final_approve", "approve", "Persetujuan FINAL PR bernilai besar (direksi)")]),
    _m("procurement", "proc_po", "Purchase Order", ["proc-purchase-orders"], ["/api/rahaza/purchase-orders"], _ALL,
       {"view": ["proc.po.view", "po.view"], "create": ["proc.po.manage", "po.create"],
        "edit": ["proc.po.manage", "po.edit", "purchasing.manage"], "delete": ["proc.po.manage", "po.delete"],
        "approve": ["proc.po.approve", "purchasing.approve"]}),
    _m("procurement", "proc_accessory_pr", "Request Aksesoris (Pembelian)", ["proc-accessory-pr"],
       ["/api/acc/purchase-requests"], _ALL,
       {"view": ["accessories.view"], "manage": ["wh.accessory.manage"], "approve": ["accessories.approve"]}),
    _m("procurement", "proc_match", "Rekonsiliasi 3-Arah & Faktur Supplier", ["proc-3way-match", "proc-ap-invoices"],
       ["/api/rahaza/3way-match", "/api/rahaza/ap-invoices"], _ALL,
       {"view": ["proc.match.view", "fin.ap.view"], "manage": ["proc.match.manage", "fin.ap.manage"],
        "approve": ["proc.match.approve"]}),
    _m("procurement", "proc_shopping_list", "Belanja Mingguan", ["wh-shopping-list"], ["/api/rahaza/shopping-list"],
       ("view", "create", "export"), {"view": ["inv.stock.view"], "create": ["proc.pr.manage"]}),

    # ── GUDANG ──────────────────────────────────────────────────────────────
    _m("warehouse", "wh_dashboard", "Dashboard, Alert & Reorder", ["warehouse-dashboard", "warehouse-smart"],
       ["/api/warehouse/dashboard", "/api/warehouse/dashboard-kpi", "/api/warehouse/alerts",
        "/api/warehouse/smart-reorder", "/api/wms/alerts", "/api/wms/rack-alerts", "/api/wms/ai"], _VE,
       {"view": ["warehouse.view", "inv.stock.view"]}),
    _m("warehouse", "wh_master", "Master Item & Riwayat Harga", ["wh-master", "wh-cost-history"],
       ["/api/rahaza/materials", "/api/rahaza/material-categories", "/api/rahaza/material-costs",
        "/api/wms/materials", "/api/rahaza/stock-thresholds"], _CRUD,
       {"view": ["inv.material.view"], "manage": ["inv.material.manage"]}, lookup=True),
    _m("warehouse", "wh_stock", "Stok, Opname & Akurasi", ["wms-stock-hub"],
       ["/api/wms/stock", "/api/warehouse/stock", "/api/warehouse/movements", "/api/warehouse/stock-adjustments",
        "/api/rahaza/material-stock", "/api/rahaza/material-movements", "/api/rahaza/material-adjust",
        "/api/rahaza/material-transfer", "/api/wms/opname3", "/api/rahaza/fg-matrix", "/api/rahaza/fg-movements",
        "/api/wms/fg", "/api/wms/stock-schema", "/api/wms/legacy", "/api/wms/search"], _ALL,
       {"view": ["inv.stock.view"], "manage": ["inv.stock.manage", "wh.opname.manage"],
        "approve": ["wh.opname.approve", "warehouse.approve"]}),
    _m("warehouse", "wh_receiving", "Penerimaan Barang & QC Masuk", ["wh-receiving"],
       ["/api/warehouse/receiving", "/api/rahaza/material-receive", "/api/rahaza/grn-qc", "/api/rahaza/grs",
        "/api/wms/pending"], _ALL,
       {"view": ["wh.receiving.view"], "manage": ["wh.receiving.manage"], "approve": ["warehouse.approve"]}),
    _m("warehouse", "wh_fabric_rolls", "Roll Kain", ["wms-fabric-rolls"], ["/api/wms/fabric-rolls"], _CRUD,
       {"view": ["inv.stock.view"], "manage": ["inv.stock.manage"]}),
    _m("warehouse", "wh_putaway", "Penyimpanan (Put-away)", ["wh-putaway"], ["/api/wms/putaway", "/api/wms/positions"],
       _CRUD, {"view": ["inv.stock.view"], "manage": ["wh.putaway.manage"]}),
    _m("warehouse", "wh_quarantine", "Karantina QC", ["wh-quarantine"], ["/api/wms/quarantine"], _ALL,
       {"view": ["wh.receiving.view"], "manage": ["wh.receiving.manage"], "approve": ["warehouse.approve"]}),
    _m("warehouse", "wh_material_issue", "Pengeluaran Material (MI)", ["wh-material-issue"],
       ["/api/rahaza/material-issues", "/api/rahaza/fg-issue", "/api/rahaza/fg-issues"], _ALL,
       {"view": ["inv.stock.view"], "manage": ["inv.material_issue.manage", "inventory.manage"],
        "approve": ["inventory.approve"]}),
    _m("warehouse", "wh_fulfillment", "Fulfillment & Pick List", ["fulfillment", "wh-picklist"],
       ["/api/fulfillment", "/api/wms/picklist"], _ALL,
       {"view": ["warehouse.view"], "manage": ["warehouse.manage"], "approve": ["warehouse.approve"]}),
    _m("warehouse", "wh_delivery_notes", "Surat Jalan", ["wms-delivery-notes"],
       ["/api/wms/delivery-notes", "/api/wms/cmt-dispatches"], _ALL,
       {"view": ["shipment.view"], "manage": ["shipment.manage"], "approve": ["shipment.dispatch"]}),
    _m("warehouse", "wh_returns", "Retur Fisik", ["wh-returns"], ["/api/wh/returns"], _ALL,
       {"view": ["warehouse.view"], "manage": ["warehouse.manage"], "approve": ["warehouse.approve"]}),
    _m("warehouse", "wh_sku_bridge", "Jembatan SKU", ["sku-bridge"], ["/api/sku-bridge"], _CRUD),
    _m("warehouse", "wh_tools", "Barcode, Struktur Gudang & Satuan", ["wh-barcode", "wh-structure", "wh-units"],
       ["/api/wms/barcode", "/api/wms/labels", "/api/wms/buildings", "/api/wms/zones", "/api/wms/racks",
        "/api/wms/structure", "/api/wms/map", "/api/wms/units", "/api/wms/unit-conversions",
        "/api/warehouse/locations", "/api/rahaza/locations", "/api/rahaza/storage-locations"], _CRUD,
       {"manage": ["wh.bin.manage"]}, lookup=True),
    _m("warehouse", "wh_audit", "Audit Trail Gudang", ["wh-audit"], ["/api/wms/audit"], _VE),

    # ── AKSESORIS ───────────────────────────────────────────────────────────
    _m("accessories", "acc_dashboard", "Dashboard, Valuasi & Laporan Aksesoris",
       ["accessories-dashboard", "accessories-reports"], ["/api/acc/dashboard", "/api/acc/valuation"],
       ("view", "edit", "export"), {"view": ["accessories.view"], "edit": ["inv.stock.manage"]}),
    _m("accessories", "acc_master", "Master & Stok Aksesoris", ["accessories-master-stock"],
       ["/api/acc/items", "/api/acc/stock", "/api/accessories"], _ALL,
       {"view": ["accessories.view"], "manage": ["wh.accessory.manage"], "approve": ["accessories.approve"]}),
    _m("accessories", "acc_opname", "Stok Opname Aksesoris", ["accessories-opname"], ["/api/acc/opname"], _ALL,
       {"view": ["accessories.view"], "manage": ["wh.accessory.manage"], "approve": ["accessories.approve"]}),
    _m("accessories", "acc_requests", "Request Internal & Inbox Approval",
       ["accessories-internal-request", "accessories-inbox", "rnd-accessory-requests"],
       ["/api/acc/internal-requests", "/api/acc/loans", "/api/dewi/accessory-requests", "/api/accessory-requests"],
       _ALL, {"view": ["accessories.view"], "manage": ["wh.accessory.manage"], "approve": ["accessories.approve"]}),

    # ── KEUANGAN ────────────────────────────────────────────────────────────
    _m("finance", "fin_dashboard", "Dashboard, Rekap & Laporan Keuangan",
       ["finance-dashboard", "fin-recap", "fin-reports-hub", "fin-executive-report"],
       ["/api/rahaza/finance-summary", "/api/financial-recap", "/api/rahaza/finance/reports"], _VE,
       {"view": ["finance.view", "fin.recap.view"], "export": ["report.export"]}),
    _m("finance", "fin_marketplace", "Saldo & Pencairan Marketplace", ["fin-marketplace-settlement"],
       ["/api/marketing/settlements", "/api/marketing/withdrawals"], _ALL,
       {"view": ["fin.ar.view"], "manage": ["fin.ar.manage"], "approve": ["finance.approve"]}),
    _m("finance", "fin_ar", "Piutang (AR) & Invoice", ["fin-ar-360"],
       ["/api/rahaza/ar-360", "/api/rahaza/ar-aging", "/api/rahaza/ar-invoices", "/api/rahaza/customer-statement"],
       _ALL, {"view": ["fin.ar.view", "fin.invoice.view"], "manage": ["fin.ar.manage", "fin.invoice.manage"],
              "approve": ["finance.approve"]}),
    _m("finance", "fin_channel_gl", "Peta Akun Channel", ["fin-channel-gl"], ["/api/rahaza/channel-gl-mapping"], _CRUD,
       {"view": ["finance.view"], "manage": ["finance.manage"]}),
    _m("finance", "fin_ap", "Aging Hutang (AP)", ["fin-ap-aging"], ["/api/rahaza/ap-aging"], _VE,
       {"view": ["fin.ap.view"]}),
    _m("finance", "fin_cash", "Kas & Bank, Prediksi Kas", ["fin-cash", "fin-ai-cashflow"],
       ["/api/rahaza/cash-accounts", "/api/rahaza/cash-movements", "/api/finance/ai-cashflow"], _ALL,
       {"view": ["fin.cash.view", "fin.payment.view"], "manage": ["fin.cash.manage", "fin.payment.manage"],
        "approve": ["finance.approve"]}, lookup=True),
    _m("finance", "fin_petty_cash", "Kas Kecil", ["fin-petty-cash"], ["/api/finance/petty-cash"], _ALL,
       {"view": ["fin.cash.view"], "manage": ["fin.cash.manage"], "approve": ["finance.approve"]}),
    _m("finance", "fin_bank_transfer", "Transfer Bank", ["fin-bank-transfer"], ["/api/finance/bank-transfers"], _ALL,
       {"view": ["fin.cash.view"], "manage": ["fin.cash.manage"], "approve": ["finance.approve"]}),
    _m("finance", "fin_bank_recon", "Rekonsiliasi Bank", ["fin-bank-recon"],
       ["/api/finance/bank-recon", "/api/rahaza/finance/bank-recon-adjustments"], _ALL,
       {"view": ["fin.cash.view"], "manage": ["fin.cash.manage"], "approve": ["finance.approve"]}),
    _m("finance", "fin_expenses", "Pengeluaran & Biaya", ["fin-expenses"], ["/api/rahaza/expenses"], _ALL,
       {"view": ["fin.expense.view"], "manage": ["fin.expense.manage"], "approve": ["finance.approve"]}),
    _m("finance", "fin_kasbon", "Kasbon & Pinjaman Karyawan", ["fin-kasbon"],
       ["/api/dewi/kasbon", "/api/rahaza/hr/employee-loans"], _ALL,
       {"view": ["fin.expense.view"], "manage": ["fin.expense.manage"], "approve": ["finance.approve", "hr.approve"]}),
    _m("finance", "fin_journal", "Jurnal, Periode & Penyesuaian", ["fin-journal-hub", "fin-acctg-adjust-hub"],
       ["/api/rahaza/journals", "/api/rahaza/periods", "/api/rahaza/year-end", "/api/rahaza/finance"], _ALL,
       {"view": ["finance.view", "fin.recap.view"], "manage": ["finance.manage"], "approve": ["finance.approve"]}),
    _m("finance", "fin_invoice_approval", "Persetujuan Perubahan Invoice", ["fin-approval"],
       ["/api/invoice-edit-requests"], ("view", "create", "approve", "export"),
       {"view": ["fin.invoice.view"], "approve": ["fin.approval.manage", "finance.approve"]}),
    _m("finance", "fin_master", "Master Akuntansi (COA & Posting)", ["fin-accounting-master-hub"],
       ["/api/rahaza/coa", "/api/rahaza/coa-auto", "/api/rahaza/posting-profiles", "/api/rahaza/integration-settings"],
       _CRUD, {"view": ["finance.view"], "manage": ["finance.manage"]}, lookup=True),
    _m("finance", "fin_budget", "Anggaran & Pusat Biaya", ["fin-budget", "fin-cost-centers"],
       ["/api/rahaza/cost-centers", "/api/rahaza/finance/budgets", "/api/rahaza/finance/budget-summary"], _ALL,
       {"view": ["finance.view"], "manage": ["fin.costcenter.manage", "finance.manage"],
        "approve": ["finance.approve"]}, lookup=True),
    _m("finance", "fin_hpp", "HPP & Costing", ["fin-hpp", "fin-hpp-produk"],
       ["/api/rahaza/hpp", "/api/costing", "/api/rahaza/costing-settings"], _ALL,
       {"view": ["hpp.view"], "manage": ["hpp.manage"], "approve": ["finance.approve"]}),
    _m("finance", "fin_fixed_assets", "Aset Tetap & Penyusutan", ["fin-fixed-assets"],
       ["/api/rahaza/finance/fixed-assets", "/api/rahaza/finance/fixed-assets-summary"], _ALL,
       {"view": ["finance.view"], "manage": ["finance.manage"], "approve": ["finance.approve"]}),

    # ── PENJUALAN ───────────────────────────────────────────────────────────
    _m("sales", "sales_dashboard", "Dashboard & Laporan Penjualan", ["sales-dashboard", "sales-report"],
       ["/api/sales/dashboard", "/api/sales/report", "/api/sales/fg-stock"], _VE),
    _m("sales", "sales_direct", "Nota Penjualan & Retur", ["sales-direct"],
       ["/api/sales/direct-sales", "/api/sales/returns", "/api/sales/cash-accounts"], _ALL),
    _m("sales", "sales_customers", "Master Pelanggan & Buyer", ["sales-customers"],
       ["/api/sales/customers", "/api/rahaza/customers", "/api/buyers"], _CRUD,
       {"view": ["customers.view"], "manage": ["customers.manage"]}, lookup=True),

    # ── SDM / HRIS ──────────────────────────────────────────────────────────
    _m("hr", "hr_employees", "Data Karyawan & Resign", ["hr-employees"],
       ["/api/rahaza/employees", "/api/rahaza/expiring-contracts", "/api/rahaza/resignation", "/api/rahaza/hr"], _ALL,
       {"view": ["hr.employee.view"], "manage": ["hr.employee.manage"], "approve": ["hr.approve"]}, lookup=True),
    _m("hr", "hr_attendance", "Absensi, Istirahat & Izin", ["hr-attendance-hub", "hr-attendance-sessions"],
       ["/api/rahaza/attendance", "/api/rahaza/devices"], _ALL,
       {"view": ["hr.employee.view"], "manage": ["hr.attendance.manage"], "approve": ["hr.approve"]}),
    _m("hr", "hr_leave", "Cuti & Lembur", ["hr-leave-hub"],
       ["/api/rahaza/leaves", "/api/rahaza/leave-types", "/api/rahaza/leave-balances", "/api/rahaza/overtime"], _ALL,
       {"view": ["hr.employee.view"], "manage": ["hr.attendance.manage"], "approve": ["hr.approve"]}),
    _m("hr", "hr_payroll", "Penggajian & Struktur Gaji", ["hr-payroll-hub"],
       ["/api/rahaza/payroll-runs", "/api/rahaza/payroll-profiles", "/api/rahaza/payroll-settings",
        "/api/rahaza/payroll-allowances", "/api/rahaza/payslips", "/api/rahaza/salary-grades",
        "/api/rahaza/salary-adjustments", "/api/payroll/automation"], _ALL,
       {"view": ["hr.payroll.view"], "manage": ["payroll.manage", "salary.manage"], "approve": ["hr.approve"]},
       extras=[("hr.payroll.run", "run", "Jalankan payroll (borongan/mingguan/bulanan)")]),
    # Pintu menu lintas-portal: modul tanpa path API (API-nya dijaga modul pemilik di portal lain).
    _m("finance", "fin_settlement", "Penyelesaian Perjalanan Dinas (menu Keuangan)", ["fin-settlement-queue"], (),
       _VAE, {"view": ["fin.expense.view"], "approve": ["finance.approve"]}),
    _m("hr", "hr_kasbon", "Kasbon Karyawan (menu SDM)", ["hr-kasbon"], (), _VAE,
       {"view": ["fin.expense.view"], "approve": ["hr.approve"]}),
    _m("hr", "hr_expense", "Klaim Dinas & Perjalanan", ["hr-expense-hub"],
       ["/api/hr/expenses"], _ALL,
       {"view": ["fin.expense.view"], "manage": ["fin.expense.manage"], "approve": ["hr.approve"]}),
    _m("hr", "hr_assets", "Aset Karyawan", ["hr-assets"], ["/api/dewi/assets"], _ALL,
       {"view": ["hr.employee.view"], "manage": ["hr.employee.manage"], "approve": ["hr.approve"]}),
    _m("hr", "hr_org", "Struktur Organisasi & Delegasi", ["hr-org-chart"], ["/api/dewi/org", "/api/rahaza/delegations"],
       _CRUD, {"view": ["hr.view"], "manage": ["hr.manage"]}),
    _m("hr", "hr_shift", "Shift & Penjadwalan", ["hr-shift-hub"],
       ["/api/hr/shifts", "/api/hr/shift-scheduler", "/api/rahaza/shifts"], _ALL,
       {"manage": ["hr.attendance.manage"], "approve": ["hr.approve"]}, lookup=True),
    _m("hr", "hr_recruitment", "Rekrutmen, Screening CV & Job Board",
       ["hr-recruitment", "hr-resume-screening", "hr-job-board"], ["/api/dewi/recruitment", "/api/hr/job-board"],
       _ALL, {"manage": ["hr.manage"], "approve": ["hr.approve"]}),
    _m("hr", "hr_onboarding", "Onboarding", ["hr-onboarding"], ["/api/dewi/onboarding"], _ALL,
       {"manage": ["hr.manage"], "approve": ["hr.approve"]}),
    _m("hr", "hr_announcements", "Papan Pengumuman", ["hr-announcements"], ["/api/announcements"], _CRUD,
       {"manage": ["hr.manage"]}, lookup=True),
    _m("hr", "hr_settings", "Pengaturan SDM", ["hr-admin"], ["/api/rahaza/hr-seed"], ("view", "edit"),
       {"view": ["hr.view"], "manage": ["hr.manage"]}),
    _m("hr", "hr_dashboard", "Dashboard, Laporan & Inbox SDM", ["hr-dashboard", "hr-reports", "hr-inbox"],
       ["/api/rahaza/hr/dashboard", "/api/rahaza/hr/reports", "/api/hr/inbox"], _VAE,
       {"view": ["hr.dashboard.view"], "approve": ["hr.approve"], "export": ["report.export"]}),
    _m("hr", "hr_performance", "Manajemen Kinerja (KPI & 360)", ["hr-performance-hub"],
       ["/api/dewi/kpi", "/api/dewi/hris/performance", "/api/rahaza/360-feedback"], _ALL,
       {"manage": ["hr.manage"], "approve": ["hr.approve"]}),
    _m("hr", "hr_lms", "Pembelajaran (LMS)", ["hr-lms"], ["/api/dewi/lms"], _CRUD, {"manage": ["hr.manage"]}),
    _m("hr", "hr_ai", "AI SDM & Skill Gap", ["hr-ai-hub"], ["/api/hr/ai", "/api/hr/skill-gap"],
       ("view", "create", "export")),

    # ── MARKETING / TOKO ────────────────────────────────────────────────────
    _m("toko", "mkt_dashboard", "Dashboard & Laporan Marketing", ["toko-dashboard", "marketing-reports"],
       ["/api/marketing/dashboard", "/api/marketing/reports", "/api/dewi/toko", "/api/marketing/performance",
        "/api/marketing/platform-kpi"], _VE, _TOKO),
    _m("toko", "mkt_accounts", "Akun Toko, Koreksi & Kesehatan Akun",
       ["marketing-accounts", "marketing-account-review", "marketing-health"],
       ["/api/marketing/accounts", "/api/marketing/account-assign", "/api/marketing/health", "/api/marketing/alerts"],
       _ALL, _TOKO),
    _m("toko", "mkt_sales", "Input Sales & Impor Data", ["marketing-sales", "marketing-import"],
       ["/api/marketing/sales", "/api/marketing/sales-data", "/api/marketing/data-import", "/api/marketing/periods"],
       _ALL, _TOKO),
    _m("toko", "mkt_orders", "Order Terpadu & Monitoring Kirim", ["marketing-orders", "marketing-fulfillment"],
       ["/api/marketing/orders"], _ALL, _TOKO),
    _m("toko", "mkt_catalog", "Manajemen Katalog", ["marketing-catalog"],
       ["/api/marketing/catalogs", "/api/marketing/catalog-items"], _ALL, _TOKO),
    _m("toko", "mkt_targets", "Target & Budget Marketing", ["marketing-targets"],
       ["/api/marketing/targets", "/api/marketing/budget"], _ALL, _TOKO),
    _m("toko", "mkt_content", "Kalender Konten, Diskon, Iklan & Peluncuran",
       ["marketing-content-calendar", "marketing-discounts", "marketing-product-launches"],
       ["/api/marketing/content-calendar", "/api/marketing/discounts", "/api/marketing/product-launches",
        "/api/marketing/ads"], _ALL, _TOKO),
    _m("toko", "mkt_kol", "KOL & Kreator", ["marketing-kol-hub"], ["/api/marketing/kol", "/api/marketing/kol-leaderboard"],
       _ALL, _TOKO),
    _m("toko", "mkt_live", "Live Selling & Host", ["marketing-live-hub"], ["/api/marketing/live", "/api/marketing/livehost"],
       _ALL, _TOKO),
    _m("toko", "mkt_ai", "AI Marketing & Penjadwal Otomasi", ["marketing-ai-hub", "marketing-scheduler"],
       ["/api/marketing/advanced-ai", "/api/marketing/ai-content", "/api/marketing/ai-insights",
        "/api/dewi/scheduler", "/api/marketing/auto-create-tasks"], ("view", "create", "edit", "export"), _TOKO),
    _m("toko", "mkt_changelog", "Jejak Perubahan Marketing", ["marketing-change-log", "mgmt-marketing-change-log"],
       ["/api/marketing/change-log"], _VE, _TOKO),
    _m("toko", "mkt_aftersales", "Komplain, Retur & Ulasan", ["marketing-after-sales", "marketing-reviews"],
       ["/api/marketing/complaints", "/api/marketing/returns", "/api/marketing/reviews"], _ALL, _TOKO),
    _m("toko", "mkt_samples", "Kirim Sample", ["marketing-samples"], ["/api/marketing/samples"], _ALL, _TOKO),
    _m("toko", "mkt_tasks", "Manajemen Tugas Marketing", ["marketing-task-hub"],
       ["/api/marketing/tasks", "/api/marketing/task-templates", "/api/marketing/tasks-stats"], _ALL, _TOKO),
    _m("toko", "mkt_integrations", "Integrasi API & Webhook", ["marketing-integration-settings", "marketing-webhooks"],
       ["/api/marketing/integration-settings", "/api/marketing/webhooks"], _CRUD, _TOKO),

    # ── RnD ─────────────────────────────────────────────────────────────────
    _m("rnd", "rnd_dashboard", "Dashboard & Analitik RnD", ["rnd-dashboard", "rnd-analytics"],
       ["/api/dewi/rnd/dashboard", "/api/dewi/rnd/analytics", "/api/dewi/rnd/reports", "/api/dewi/rnd/completeness",
        "/api/dewi/rnd/lifecycle"], _VE, {"view": ["rnd.view"]}),
    _m("rnd", "rnd_design", "Style, Pola & Tech Pack", ["rnd-design-hub"],
       ["/api/dewi/rnd/styles", "/api/dewi/rnd/patterns", "/api/dewi/rnd/tech-packs", "/api/dewi/rnd/techpack",
        "/api/dewi/rnd/revisions", "/api/rahaza/styles"], _ALL,
       {"view": ["rnd.view"], "manage": ["rnd.manage"], "approve": ["rnd.approve"]}),
    _m("rnd", "rnd_master_product", "Master Produk RnD (Kategori, Varian, BOM, Ukuran, Warna)",
       ["rnd-master-product-hub"],
       ["/api/rahaza/product-categories", "/api/rahaza/boms", "/api/rahaza/bom-material-units",
        "/api/rahaza/bom-uom-audit", "/api/rahaza/bom-uom-backfill", "/api/rahaza/master", "/api/rahaza/sizes",
        "/api/rahaza/colors", "/api/dewi/rnd/variants", "/api/dewi/rnd/size-mapping", "/api/dewi/rnd/color-options"],
       _ALL, {"view": ["bom.view", "rnd.view"], "manage": ["bom.manage", "rnd.manage"], "approve": ["rnd.approve"]},
       lookup=True),
    _m("rnd", "rnd_product_viewer", "Produk Final", ["rnd-product-viewer"], ["/api/rnd/product-viewer"], _VE,
       {"view": ["rnd.view"]}),
    _m("rnd", "rnd_samples", "Sample Request & Approval Sample", ["rnd-samples"],
       ["/api/dewi/rnd/sample-requests", "/api/dewi/rnd/approvals"], _ALL,
       {"view": ["rnd.view"], "manage": ["rnd.manage"], "approve": ["rnd.approve"]}),
    _m("rnd", "rnd_materials", "Riset Material", ["rnd-materials"],
       ["/api/dewi/rnd/materials", "/api/dewi/rnd/material-options", "/api/dewi/rnd/uom-options"], _CRUD,
       {"view": ["rnd.view"], "manage": ["rnd.manage"]}),
    _m("rnd", "rnd_costing", "Costing & HPP Sample", ["rnd-costing-hub"],
       ["/api/dewi/rnd/hpp", "/api/dewi/rnd/hpp-calculator", "/api/dewi/rnd/sample-costing"], _ALL,
       {"view": ["rnd.view", "hpp.view"], "manage": ["rnd.manage", "hpp.manage"], "approve": ["rnd.approve"]}),
    _m("rnd", "rnd_kreator", "Approval Kreator", ["rnd-kreator-requests"], ["/api/dewi/kreator-requests"], _VAE,
       {"view": ["rnd.view"], "approve": ["rnd.approve"]}),

    # ── ASET ────────────────────────────────────────────────────────────────
    _m("assets", "assets_main", "Manajemen Aset, Peminjaman & Pelepasan", ["asset-management"], ["/api/assets"], _ALL,
       {"view": ["assets.view"], "manage": ["assets.manage"], "approve": ["assets.manage"]}),

    # ── MAKLON (menu pintasan Produksi di portal ini mengikuti modul Produksi-nya) ──
    _m("maklon", "mak_clients", "Data Klien Maklon", ["maklon-clients"], ["/api/dewi/maklon/clients"], _CRUD,
       _MAKLON, lookup=True),
    _m("maklon", "mak_buyer_catalog", "Katalog Buyer & Template BOM", ["maklon-buyer-catalog"],
       ["/api/dewi/maklon/buyer-catalog", "/api/dewi/maklon/bom-templates"], _CRUD, _MAKLON, lookup=True),
    _m("maklon", "mak_po", "PO Maklon & Detail PO", ["maklon-pos-engine", "maklon-po-360"],
       ["/api/dewi/maklon/pos", "/api/dewi/maklon/pos-summary", "/api/dewi/maklon/orders", "/api/dewi/maklon/bom",
        "/api/dewi/maklon/material-receive", "/api/dewi/maklon/dispatches"], _ALL, _MAKLON),
    _m("maklon", "mak_samples", "Sampel & QC Maklon", ["maklon-samples"],
       ["/api/dewi/maklon/samples", "/api/dewi/maklon/qc"], _ALL, _MAKLON),
    _m("maklon", "mak_dashboard", "Dashboard, Alur Produksi & Tracking Maklon",
       ["maklon-dashboard", "maklon-alur-produksi", "maklon-tracking"],
       ["/api/dewi/maklon/summary", "/api/maklon/sla", "/api/maklon-client"], _VE,
       {"view": ["maklon.view"], "export": ["maklon.view"]}),
    _m("maklon", "mak_billing", "Invoice & Pembayaran Maklon", ["maklon-billing"],
       ["/api/dewi/maklon/invoices", "/api/dewi/maklon/payments", "/api/dewi/maklon/reports",
        "/api/dewi/maklon/finance"], _ALL, _MAKLON),
    _m("maklon", "mak_hpp", "HPP Jahit", ["maklon-hpp"], ["/api/dewi/maklon/hpp"], _CRUD, _MAKLON),
    _m("maklon", "mak_ai_quote", "Estimasi AI (Quote)", ["maklon-ai-quote"], ["/api/maklon/ai-quote"],
       ("view", "create", "approve", "export"), _MAKLON),
]

MODULE_BY_ID = {m["id"]: m for m in MODULES}

# Portal lain yang menampilkan menu modul ini (pintasan lintas-portal di portalNav.js).
# Dipakai gerbang akses-portal agar layar pintasan tetap jalan. Perbarui bila menu dipindah.
ALSO_PORTALS = {
    "mgmt_reports": ["rnd"], "mgmt_approval": ["hr"], "prod_vendor_cmt": ["maklon"], "prod_po": ["maklon"],
    "prod_vendor_shipment": ["maklon"], "prod_cmt_receive": ["maklon"], "prod_cmt_permak": ["maklon"],
    "prod_cmt_monitor": ["maklon"], "prod_buyer_shipment": ["maklon"], "prod_jobs": ["maklon"],
    "prod_variance": ["maklon"], "prod_cmt_billing": ["finance"], "proc_match": ["finance"],
    "proc_shopping_list": ["warehouse"], "wh_material_issue": ["production"], "wh_sku_bridge": ["toko"],
    "acc_requests": ["rnd"], "fin_hpp": ["production"], "mkt_changelog": ["management"],
    "rnd_dashboard": ["management"],
}
for _mod in MODULES:
    _mod["also_portals"] = ALSO_PORTALS.get(_mod["id"], [])

# prefix API -> modul, urut dari prefix terpanjang (longest-prefix-match)
_PATH_INDEX = sorted(((p.rstrip("/"), m) for m in MODULES for p in m["paths"]), key=lambda x: -len(x[0]))

_APPROVE_TOKENS = {"approve", "approval", "reject", "verify", "confirm", "post", "unpost", "close", "reopen",
                   "finalize", "lock", "unlock", "decide", "decision", "release", "sign", "dispatch"}
_EXPORT_TOKENS = {"export", "pdf", "excel", "xlsx", "csv", "download", "print", "label", "labels"}
_READ_TOKENS = {"preview", "simulate", "search", "calculate", "lookup", "suggest", "estimate", "check",
                "compute", "query", "filter", "resolve"}


def perm_key(module_id: str, action: str) -> str:
    return f"mod.{module_id}.{action}"


def match_module(path: str):
    p = (path or "").rstrip("/")
    for prefix, mod in _PATH_INDEX:
        if p == prefix or p.startswith(prefix + "/"):
            return mod
    return None


def detect_action(method: str, path: str, module: dict) -> str:
    """Tentukan aksi dari method + kata kunci path (mis. /approve, /export, /pdf)."""
    method = (method or "GET").upper()
    tokens = set(re.split(r"[/\-_.]+", (path or "").lower()))
    acts = module["actions"]
    if tokens & _EXPORT_TOKENS and "export" in acts:
        return "export"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "view"
    if tokens & _APPROVE_TOKENS and "approve" in acts:
        return "approve"
    if method == "POST" and tokens & _READ_TOKENS:
        return "view"
    action = {"POST": "create", "PUT": "edit", "PATCH": "edit", "DELETE": "delete"}.get(method, "edit")
    if action not in acts:
        action = "edit" if "edit" in acts else ("create" if "create" in acts else "view")
    return action


def _parse(key: str):
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "mod" and parts[1] in MODULE_BY_ID:
        return MODULE_BY_ID[parts[1]], parts[2]
    return None, None


def granular_portals(keys) -> set:
    """Portal yang sudah diatur owner secara granular untuk kumpulan izin ini."""
    out = set()
    for k in keys or ():
        mod, _ = _parse(k)
        if mod:
            out.add(mod["portal"])
    return out


def view_portals(keys) -> set:
    """Portal pemilik modul yang diberi izin `view` — portal ini ikut terbuka di pemilih portal."""
    out = set()
    for k in keys or ():
        mod, act = _parse(k)
        if mod and act == "view":
            out.add(mod["portal"])
    return out


def expand_permissions(keys) -> list:
    """Tambahkan izin lama yang tersirat dari izin granular (agar penjaga lama tetap konsisten)."""
    out = set(k for k in (keys or ()) if k)
    for k in list(out):
        mod, act = _parse(k)
        if not mod:
            continue
        imp = mod["implies"]
        out.update(imp.get(act, []))
        if act in ("create", "edit", "delete"):
            out.update(imp.get("manage", []))
    return sorted(out)


def menu_access(keys, is_super: bool = False) -> tuple[list, dict]:
    """(menu tersembunyi, {menu_id: [aksi]}) — hanya untuk portal yang sudah granular."""
    if is_super or "*" in (keys or ()):
        return [], {}
    keys = set(keys or ())
    gportals = granular_portals(keys)
    access: dict = {}
    for mod in MODULES:
        if mod["portal"] not in gportals:
            continue
        acts = [a for a in mod["actions"] if perm_key(mod["id"], a) in keys]
        for menu in mod["menus"]:
            prev = set(access.get(menu, []))
            access[menu] = sorted(prev | set(acts))
    hidden = sorted(m for m, acts in access.items() if "view" not in acts)
    # Menu pintasan modul portal lain (ALSO_PORTALS) di portal yang sudah granular: tanpa izin Lihat
    # modul pemiliknya → disembunyikan HANYA di portal pintasan itu (format "<portal>::<menu>").
    for mod in MODULES:
        if mod["portal"] in gportals or perm_key(mod["id"], "view") in keys:
            continue
        for p in set(mod["also_portals"]) & gportals:
            hidden += [f"{p}::{menu}" for menu in mod["menus"]]
    return hidden, access


def grouped_modules(portal: str) -> list[dict]:
    """Modul granular sebuah portal dalam bentuk katalog (dipakai permission_catalog)."""
    out = []
    for mod in MODULES:
        if mod["portal"] != portal:
            continue
        perms = [{
            "key": perm_key(mod["id"], a), "action": a,
            "description": f"{ACTION_LABELS[a]} — {mod['label']}",
        } for a in mod["actions"]]
        perms += [{"key": k, "action": act, "description": desc} for (k, act, desc) in mod["extras"]]
        out.append({"id": mod["id"], "label": mod["label"], "granular": True,
                    "menus": mod["menus"], "lookup": mod["lookup"], "perms": perms})
    return out


def all_granular_keys() -> set:
    return {perm_key(m["id"], a) for m in MODULES for a in m["actions"]}


def suggest_from_legacy(keys, portal: str, has_portal_access: bool) -> list:
    """Usulan izin `mod.*` untuk satu portal yang setara dengan izin lama + akses portal.

    Aksi dengan pemetaan `implies` diberikan bila SEMUA izin lama itu dimiliki; aksi tanpa
    pemetaan diberikan bila peran sudah bisa membuka portalnya (aturan lama = penjaga router).
    Aksi apa pun otomatis ikut memberi `view`.
    """
    keys = set(keys or ())
    out = []
    for mod in MODULES:
        if mod["portal"] != portal:
            continue
        imp = mod["implies"]
        granted = []
        for act in mod["actions"]:
            need = imp.get(act) or (imp.get("manage") if act in ("create", "edit", "delete") else None)
            ok = all(k in keys for k in need) if need else has_portal_access
            if ok:
                granted.append(act)
        if granted and "view" in mod["actions"] and "view" not in granted:
            granted.append("view")
        if not granted and has_portal_access and "view" in mod["actions"]:
            granted.append("view")
        out += [perm_key(mod["id"], a) for a in granted]
    return out
