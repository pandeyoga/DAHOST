"""core.collection_registry — DAFTAR RESMI koleksi MongoDB yang boleh dipakai.

KENAPA BERKAS INI ADA (F0.1, 2026-08-12)
----------------------------------------
Forensik `scripts/_forensic_ssot_v3.py` mengukur: **386 koleksi** disebut kode
sementara hanya **192** ada di database, **13** ditulis-tak-pernah-dibaca,
**28** dibaca-tak-pernah-ditulis, dan **156** hanya disentuh SATU berkas.
Itu wujud teknis dari keluhan owner: *"fitur yang berdiri sendiri, lupa
hubungannya dengan api lain"* dan *"collection yang di panggil miss semua"*.

Mekanisme pencegahnya sederhana: **koleksi baru harus didaftarkan di sini**.
`scripts/gate_marketing_ssot.py` memeriksa seluruh `backend/routes|core|services`
dan MERAH bila ada koleksi yang tidak terdaftar — jadi menambah koleksi diam-diam
tidak lagi mungkin, dan setiap koleksi punya pemilik domain yang jelas.

Cara menambah koleksi baru (WAJIB, urutannya tidak boleh dibalik):
  1. tulis kontrak fieldnya di `memory/SSOT_KONTRAK_DATA_2026-08-12.md`;
  2. daftarkan namanya di `REGISTRY` di bawah beserta domainnya;
  3. baru tulis kodenya.
"""
from __future__ import annotations

# nama koleksi → domain pemilik
REGISTRY: dict[str, str] = {
    "acc_purchase_requests": "finance",
    "acc_valuation_report_runs": "finance",
    "accessory_shipment_items": "lain",
    "accessory_shipments": "lain",
    "activity_logs": "lain",
    # 2026-11-06 (T5 cutoff) — koleksi yang DIPAKAI kode/ada di basis data tetapi belum terdaftar.
    "bank_recon_matches": "finance",
    "cmt_delivery_notes": "produksi",
    "cron_runs": "lain",
    "dewi_cmt_ap_schedules": "maklon",
    "dewi_cmt_disbursements": "maklon",
    "fg_cost_consumptions": "inventory",
    "fg_cost_layers": "inventory",
    "legacy_drop_log": "lain",
    "legacy_loan_close_log": "lain",
    "marketing_budget_settings": "marketing",
    "marketing_creator_incentive_entries": "marketing",
    "marketing_creator_weekly_reports": "marketing",
    "marketing_platform_withdrawals": "marketing",
    "marketing_settlement_import_maps": "marketing",
    "marketing_sku_bridge": "marketing",
    "pdf_templates": "lain",
    "product_cost_snapshots": "produksi",
    "rahaza_attendance_audit": "hr",
    "rahaza_attendance_corrections": "hr",
    "rahaza_debit_notes": "finance",
    "rahaza_expense_categories": "finance",
    "rahaza_fingerprint_imports": "hr",
    "rahaza_fingerprint_profiles": "hr",
    "rahaza_inventory_revaluations": "inventory",
    "rahaza_intercompany_txns": "finance",   # Tahap 8 fase 2: Transaksi antar CV (dua jurnal berlabel)
    "rahaza_model_costing": "produksi",
    "rahaza_period_alerts": "finance",
    "rahaza_purchase_returns": "pengadaan",
    "rahaza_variant_options": "lain",
    "rahaza_year_end_closings": "finance",
    "sales_direct_notes": "penjualan",
    "sales_direct_returns": "penjualan",
    "sync_log": "lain",
    "wh_barcode_print_jobs": "gudang",
    "wh_scan_out_controls": "gudang",
    "wh_scan_out_lines": "gudang",
    "wh_scan_out_rejects": "gudang",
    "wh_scan_out_settings": "gudang",
    "wh_scan_out_sheets": "gudang",
    # Asisten AI (laporan): metadata laporan PDF/Excel buatan Asisten AI (berkasnya di penyimpanan unggahan).
    "ai_reports": "lain",
    "ai_business_summaries": "lain",
    # Asisten AI (inti) — 2026-11-07 Tahap A: percakapan chat analis (jenis `log`, lihat bawah)
    "ai_chat_sessions": "lain",
    "ai_chat_messages": "lain",
    # Tahap B (8 Nov 2026): kartu tindakan AI + keputusan/jejaknya (jenis `log`, lihat bawah)
    "ai_actions": "lain",
    # Tahap E (9 Nov 2026): lampiran pengguna + berkas keluaran "hitung dengan kode" (jenis `log`, lihat bawah)
    "ai_lampiran": "lain",
    "ai_berkas": "lain",
    # ── akhir Asisten AI (inti) ──
    # Asisten AI (proaktif) — Tahap D: ingatan AI per pengguna (preferensi = konfigurasi) + jejak jalan
    # briefing/peringatan/laporan mingguan (klaim sekali-sehari, jenis `log`).
    "ai_memories": "lain",
    "ai_proaktif_runs": "lain",
    # ── akhir Asisten AI (proaktif) ──
    "ai_config": "lain",
    "ai_rca_history": "lain",
    "ai_response_cache": "lain",
    "announcements": "lain",
    "approval_chains": "lain",
    "approval_requests": "lain",
    "assistant_chat_history": "lain",
    "attachments": "lain",
    "bank_recon_sessions": "lain",
    "bank_recon_txns": "lain",
    "buyer_shipment_items": "penjualan",
    "buyer_shipments": "penjualan",
    "buyer_short_records": "penjualan",
    "buyers": "lain",
    "capacity_config": "lain",
    "client_login_attempts": "lain",
    "cmt_receipt_lines": "lain",
    "cmt_receipts": "lain",
    "cmt_short_shipments": "lain",
    "comm_channels": "lain",
    "comm_conversations": "lain",
    "comm_messages": "lain",
    "comm_read_receipts": "lain",
    "company_settings": "lain",
    "counters": "lain",
    "cutting_orders": "lain",
    "cutting_progress": "lain",
    "da_asset_assignments": "lain",
    "da_assets": "lain",
    "da_kpi_badges": "lain",
    "da_kpi_goals": "lain",
    "da_kpi_perform": "lain",
    "da_kpi_periods": "lain",
    "da_kpi_questions": "lain",
    "da_kpi_results": "lain",
    "da_kpi_submissions": "lain",
    "da_payroll_allowances": "lain",
    "dewi_accessory_requests": "lain",
    "dewi_ai_actions": "lain",
    "dewi_asset_assignments": "lain",
    "dewi_asset_categories": "lain",
    "dewi_asset_depreciation": "lain",
    "dewi_asset_disposal_requests": "lain",
    "dewi_asset_loans": "lain",
    "dewi_asset_maintenance": "lain",
    "dewi_asset_pm_acknowledgments": "lain",
    "dewi_asset_scans": "lain",
    "dewi_asset_transfers": "lain",
    "dewi_assets": "lain",
    "dewi_client_users": "lain",
    "dewi_cmt_component_requests": "produksi",
    "dewi_cmt_deliveries": "produksi",
    "dewi_cmt_delivery_orders": "produksi",
    "dewi_cmt_jobs": "produksi",
    "dewi_cmt_partners": "produksi",
    "dewi_cmt_payments": "produksi",
    "dewi_cmt_permak": "produksi",
    "dewi_cmt_progress": "produksi",
    "dewi_cmt_progress_reports": "produksi",
    "dewi_cutting_batches": "lain",
    "dewi_cutting_requests": "lain",
    "dewi_delivery_orders": "lain",
    "dewi_hpp_snapshots_maklon": "lain",
    "dewi_hpp_snapshots_po": "lain",
    "dewi_kasbon_requests": "lain",
    "dewi_kreator_requests": "lain",
    "dewi_lms_attempts": "hr",
    "dewi_lms_courses": "hr",
    "dewi_lms_enrollments": "hr",
    "dewi_lms_materials": "hr",
    "dewi_lms_progress": "hr",
    "dewi_lms_quizzes": "hr",
    "dewi_lms_submissions": "hr",
    "dewi_maklon_advance_payments": "maklon",
    "dewi_maklon_bom": "maklon",
    "dewi_maklon_bom_templates": "maklon",
    "dewi_maklon_buyer_catalog": "maklon",
    "dewi_maklon_clients": "maklon",
    "dewi_maklon_credit_notes": "maklon",
    "dewi_maklon_dispatches": "maklon",
    "dewi_maklon_hpp": "maklon",
    "dewi_maklon_inventory": "maklon",
    "dewi_maklon_invoices": "maklon",
    "dewi_maklon_material_issues": "maklon",
    "dewi_maklon_material_receive": "maklon",
    "dewi_maklon_payments": "maklon",
    "dewi_maklon_pos": "maklon",
    "dewi_maklon_qc_checks": "maklon",
    "dewi_maklon_sample_revisions": "maklon",
    "dewi_maklon_samples": "maklon",
    # 2026-11-10 (owner): denda saat Tutup PO — klien→DA & DA→CMT (`core.denda_po`)
    "dewi_po_denda": "produksi",
    "dewi_material_issues": "lain",
    "dewi_mgmt_alert_config": "lain",
    "dewi_onboarding_checklists": "lain",
    "dewi_onboarding_templates": "lain",
    "dewi_org_positions": "lain",
    "dewi_org_units": "lain",
    "dewi_perf_assignments": "lain",
    "dewi_perf_cycles": "lain",
    "dewi_perf_kpis": "lain",
    "dewi_perf_reviews": "lain",
    "dewi_procurement_requests": "lain",
    "dewi_provider_config": "lain",
    "dewi_recruitment_candidates": "lain",
    "dewi_recruitment_jobs": "lain",
    "dewi_rnd_hpp": "rnd",
    "dewi_rnd_materials": "rnd",
    "dewi_rnd_patterns": "rnd",
    "dewi_rnd_revisions": "rnd",
    "dewi_rnd_sample_costing": "rnd",
    "dewi_rnd_sample_requests": "rnd",
    "dewi_rnd_styles": "rnd",
    "dewi_rnd_tech_packs": "rnd",
    "dewi_rnd_variants": "rnd",
    "dewi_scheduler_runs": "lain",
    "dewi_system_config": "lain",
    "dewi_toko_flashsales": "lain",
    "dewi_toko_orders": "lain",
    "dewi_toko_pack_batches": "lain",
    "dewi_toko_products": "lain",
    "dewi_toko_returns": "lain",
    "dewi_toko_reviews": "lain",
    "dewi_universal_scans": "lain",
    "doc_number_configs": "lain",
    "document_number_configs": "lain",
    "employee_documents": "lain",
    "employee_expense_categories": "lain",
    "employee_expense_gl_mappings": "lain",
    "employee_per_diem_rates": "lain",
    "employee_travel_requests": "lain",
    "employee_travel_settlements": "lain",
    "fx_rates": "lain",
    "fx_revaluation_runs": "lain",
    "garments": "lain",
    "hr_ai_results": "lain",
    "hr_issued_documents": "lain",
    "hr_shift_assignments": "lain",
    # 2026-11-09 (Tahap C audit HR): pola rotasi shift + permintaan ganti/tukar shift Portal Saya
    "hr_shift_pola": "hr",
    "hr_shift_requests": "hr",
    "hris_assignments": "hr",
    "hris_cycles": "hr",
    "hris_kpi_assignments": "hr",
    "hris_reviews": "hr",
    "hris_training_completions": "hr",
    "invoice_adjustments": "lain",
    "invoice_change_history": "lain",
    "invoice_edit_requests": "lain",
    "invoices": "lain",
    "login_attempts": "lain",
    "marketing_ab_experiments": "marketing",
    "marketing_account_health": "marketing",
    "marketing_account_targets": "marketing",
    "marketing_ads_data": "marketing",
    "marketing_ai_content_history": "marketing",
    "marketing_alert_runs": "marketing",
    "marketing_alert_settings": "marketing",
    "marketing_budgets": "marketing",
    "marketing_catalog_bulk_runs": "marketing",   # 2026-11-09 — jejak + batalkan aksi massal katalog
    "marketing_catalog_items": "marketing",
    "marketing_catalogs": "marketing",
    "marketing_churn_scores": "marketing",
    "marketing_complaints": "marketing",
    "marketing_content_calendar": "marketing",
    "marketing_creator_catalog": "marketing",
    "marketing_creator_item_requests": "marketing",
    "marketing_creator_sessions": "marketing",
    "marketing_creator_targets": "marketing",
    "marketing_data_import_sessions": "marketing",
    # F1 (2026-08-12) — ingatan susunan kolom ekspor: (source_type, fingerprint)
    # → pemetaan yang sudah dikonfirmasi manusia, supaya impor rutin tidak perlu
    # memetakan ulang dan tidak pernah menebak diam-diam.
    "marketing_data_import_formats": "marketing",
    # F3 (2026-08-14) — jejak PEMULIHAN impor `update_only` (Ekspor B/C).
    # Satu dokumen per pesanan yang diubah: nilai field sebelum diubah, status
    # sebelum diubah, dan `items[]` sebelum diubah (kalau retur per SKU ikut).
    # Dibaca HANYA oleh `POST /sessions/{id}/rollback`; tidak pernah dijumlah,
    # tidak pernah jadi sumber angka laporan.
    "marketing_data_import_undo": "marketing",
    "marketing_discounts": "marketing",
    "marketing_dynamic_pricing_events": "marketing",
    "marketing_dynamic_pricing_settings": "marketing",
    "marketing_dynamic_pricing_suggestions": "marketing",
    "marketing_integration_settings": "marketing",
    "marketing_kol_campaigns": "marketing",
    "marketing_kol_creators": "marketing",
    "marketing_kol_login_attempts": "marketing",
    "marketing_live_session_products": "marketing",
    "marketing_live_sessions": "marketing",
    "marketing_livehost_scripts": "marketing",
    "marketing_livehost_shifts": "marketing",
    "marketing_livehost_training": "marketing",
    "marketing_livehost_training_progress": "marketing",
    "marketing_livehosts": "marketing",
    "marketing_orders": "marketing",
    "marketing_platform_accounts": "marketing",
    "marketing_product_launches": "marketing",
    "marketing_returns": "marketing",
    "marketing_reviews": "marketing",
    "marketing_sales_data": "marketing",
    "marketing_samples": "marketing",
    "marketing_spend_entries": "marketing",
    "marketing_stock_syncs": "marketing",
    "marketing_task_templates": "marketing",
    "marketing_tasks": "marketing",
    "marketing_webhook_events": "marketing",
    "material_defect_reports": "lain",
    "material_request_items": "lain",
    "material_requests": "lain",
    "notif_category_config": "lain",
    "notif_user_prefs": "lain",
    "notifications": "lain",
    "payments": "lain",
    "payroll_automation_config": "lain",
    "payroll_automation_log": "lain",
    "payroll_entries": "lain",
    "payroll_runs": "lain",
    "payslips": "lain",
    "pdf_document_settings": "lain",
    "pdf_export_configs": "lain",
    "peer_feedbacks": "lain",
    "permissions": "lain",
    "po_accessories": "pengadaan",
    "po_items": "pengadaan",
    "portal_calendar_events": "lain",
    "portal_notes": "lain",
    "portal_quick_links": "lain",
    "portal_reminders": "lain",
    "portal_todos": "lain",
    "product_variants": "lain",
    "production_job_items": "produksi",
    "production_jobs": "produksi",
    "production_material_returns": "produksi",
    "production_pos": "produksi",
    "production_progress": "produksi",
    "production_return_items": "produksi",
    "production_returns": "produksi",
    "production_variances": "produksi",
    "products": "lain",
    "push_subscriptions": "lain",
    "rahaza_360_cycles": "lain",
    "rahaza_accruals": "lain",
    "rahaza_ai_audit_logs": "lain",
    "rahaza_ai_chat_history": "lain",
    "rahaza_ai_usage_logs": "lain",
    "rahaza_alert_settings": "lain",
    "rahaza_alerts": "lain",
    "rahaza_ap_invoices": "finance",
    "rahaza_ap_payments": "finance",
    "rahaza_approval_delegations": "finance",
    "rahaza_ar_invoices": "finance",
    "rahaza_ar_payments": "finance",
    "rahaza_attendance": "hr",
    "rahaza_attendance_events": "hr",
    "rahaza_audit_logs": "lain",
    "rahaza_bank_recon_adjustments": "lain",
    "rahaza_bank_transfers": "lain",
    "rahaza_boms": "lain",
    "rahaza_budget_items": "lain",
    "rahaza_budgets": "lain",
    "rahaza_bundles": "lain",
    "rahaza_career_chats": "lain",
    "rahaza_career_reports": "lain",
    "rahaza_cash_accounts": "lain",
    "rahaza_cash_movements": "lain",
    "rahaza_channel_gl_mapping": "lain",
    "rahaza_coa_accounts": "finance",
    "rahaza_coa_auto_settings": "finance",
    "rahaza_colors": "lain",
    "rahaza_cost_centers": "lain",
    "rahaza_costing_settings": "lain",
    "rahaza_credit_notes": "lain",
    "rahaza_customers": "lain",
    "rahaza_defect_codes": "lain",
    "rahaza_depr_schedules": "lain",
    "rahaza_downtime_events": "lain",
    "rahaza_employee_loan_repayments": "hr",
    "rahaza_employee_loans": "hr",
    # 2026-11-07 (HR1, Tahap 6): perubahan kontak karyawan dari Portal Saya menunggu persetujuan HR
    "rahaza_employee_data_changes": "hr",
    "rahaza_employees": "hr",
    "rahaza_expense_claims": "lain",
    "rahaza_expenses": "lain",
    "rahaza_fg_inventory": "lain",
    "rahaza_fg_issues": "lain",
    "rahaza_fg_matrix": "lain",
    "rahaza_fg_movements": "lain",
    "rahaza_fg_reservations": "lain",
    "rahaza_fixed_assets": "lain",
    "rahaza_grn_inspections": "lain",
    "rahaza_handover_templates": "lain",
    "rahaza_hpp_snapshots": "lain",
    "rahaza_integration_settings": "lain",
    "rahaza_job_applications": "lain",
    "rahaza_job_postings": "lain",
    "rahaza_journal_entries": "finance",
    "rahaza_journal_lines": "finance",
    "rahaza_leave_balances": "hr",
    "rahaza_leave_requests": "hr",
    "rahaza_leave_types": "hr",
    "rahaza_line_assignments": "lain",
    "rahaza_lines": "lain",
    "rahaza_locations": "lain",
    "rahaza_machine_downtime": "lain",
    "rahaza_machines": "lain",
    "rahaza_maintenance_logs": "lain",
    "rahaza_maintenance_predictions": "lain",
    "rahaza_maklon_quotes": "lain",
    "rahaza_material_categories": "inventory",
    "rahaza_material_cost_history": "inventory",
    "rahaza_sku_price_history": "inventory",   # 2026-11-09 — riwayat harga jual resmi per SKU
    "rahaza_material_issues": "inventory",
    "rahaza_material_movements": "inventory",
    "rahaza_material_reservations": "inventory",
    "rahaza_material_stock": "inventory",
    "rahaza_materials": "inventory",
    "rahaza_model_process_sop": "lain",
    "rahaza_model_variants": "lain",
    "rahaza_models": "lain",
    "rahaza_office_locations": "lain",
    "rahaza_okr_key_results": "lain",
    "rahaza_okr_objectives": "lain",
    "rahaza_orders": "lain",
    "rahaza_overtime_requests": "lain",
    "rahaza_payroll_profiles": "hr",
    "rahaza_payroll_runs": "hr",
    "rahaza_payroll_settings": "hr",
    "rahaza_payslips": "hr",
    "rahaza_periods": "lain",
    "rahaza_petty_cash_funds": "lain",
    "rahaza_petty_cash_txns": "lain",
    "rahaza_posting_profiles": "lain",
    "rahaza_processes": "lain",
    "rahaza_product_categories": "lain",
    "rahaza_production_calendar": "lain",
    "rahaza_purchase_orders": "lain",
    "rahaza_qc_events": "lain",
    "rahaza_racks": "lain",
    "rahaza_salary_adjustments": "lain",
    "rahaza_salary_grades": "lain",
    "rahaza_schedules": "lain",
    "rahaza_setup_state": "lain",
    "rahaza_shift_handovers": "lain",
    "rahaza_shift_templates": "lain",
    "rahaza_shifts": "lain",
    "rahaza_shipments": "lain",
    "rahaza_sizes": "lain",
    "rahaza_skill_analyses": "lain",
    "rahaza_skill_requirements": "lain",
    "rahaza_stock_ledger": "inventory",
    "rahaza_styles": "lain",
    "rahaza_supplier_price_lists": "lain",
    "rahaza_suppliers": "lain",
    "rahaza_webauthn_challenges": "lain",
    "rahaza_webauthn_credentials": "lain",
    "rahaza_wip_events": "lain",
    "rahaza_work_orders": "lain",
    "rahaza_zkteco_devices": "lain",
    "rate_limit_buckets": "lain",
    "reminders": "lain",
    "role_permissions": "lain",
    "roles": "lain",
    "study_groups": "lain",
    "users": "lain",
    "vendor_jobs": "vendor",
    "vendor_material_inspection_items": "vendor",
    "vendor_material_inspections": "vendor",
    "vendor_partners": "vendor",
    "vendor_progress_reports": "vendor",
    "vendor_shipment_items": "vendor",
    "vendor_shipments": "vendor",
    "warehouse_receiving": "lain",
    "wh_buildings": "gudang",
    "wh_cmt_dispatches": "gudang",
    "wh_delivery_notes": "gudang",
    "wh_fabric_roll_movements": "gudang",
    "wh_fabric_rolls": "gudang",
    # 2026-11-09: impor roll kain massal stok awal (core/fabric_roll_import) — satu dokumen per berkas
    "wh_fabric_roll_imports": "gudang",
    "wh_location_migration_map": "gudang",
    "wh_opname3_counts": "gudang",
    "wh_opname3_sessions": "gudang",
    "wh_opname_sessions2": "gudang",
    "wh_pending_movements": "gudang",
    "wh_picklists": "gudang",
    "wh_placement_movements": "gudang",
    "wh_positions": "gudang",
    "wh_quarantine_items": "gudang",
    "wh_rack_alerts": "gudang",
    "wh_racks": "gudang",
    "wh_rca_audit": "gudang",
    "wh_returns": "gudang",
    "wh_stock_schema_reconcile_log": "gudang",
    "wh_unit_conversions": "gudang",
    "wh_unit_master": "gudang",
    "wh_zones": "gudang",
    "wms_fabric_rolls": "gudang",
    "work_orders": "lain",
    "workspace_documents": "lain",
    "workspace_shares": "lain",
    "workspace_versions": "lain",
}

# Koleksi yang DIHAPUS di F0.6 (mesin impor lama) atau tujuan yang SALAH.
# Menyentuhnya dari kode = gate MERAH; pengganti yang benar ada di nilai dict.
DEPRECATED: dict[str, str] = {
    "marketing_import_sessions":     "marketing_data_import_sessions",
    "marketing_import_uploads":      "marketing_data_import_sessions",
    "marketing_import_templates":    "marketing_data_import_formats",
    "marketing_import_history":      "marketing_data_import_sessions",
    "marketing_discount_campaigns":  "marketing_discounts",
    "marketing_sample_shipments":    "marketing_samples",
}

# Koleksi BARU yang sudah disetujui rencana F0–F10 tetapi belum ditulis kodenya.
# Didaftarkan lebih dulu supaya gate tidak menghalangi saat fasenya dikerjakan.
PLANNED: dict[str, str] = {
    "marketing_settlements":            "marketing",   # F9 — pencairan marketplace
    "marketing_period_locks":           "marketing",   # F5/F6 — kunci periode
    "marketing_change_log":             "marketing",   # F6 — jejak nilai lama
    "marketing_data_import_formats":    "marketing",   # F1 — sidik format impor
    # F7.2 (2026-08-13) — KPI harian dari ekspor Seller Center (statistik toko,
    # Live/Video). SENGAJA dipisah dari `marketing_sales_data`: definisi angkanya
    # milik platform (pesanan dibuat/siap dikirim/dibayar) dan tidak boleh
    # dijumlah dengan omzet pesanan. Kontrak field: lihat
    # memory/SSOT_KONTRAK_DATA_2026-08-12.md §KPI PLATFORM.
    "marketing_platform_kpi_daily":     "marketing",
}


def all_allowed() -> set[str]:
    return set(REGISTRY) | set(PLANNED)


def is_registered(name: str) -> bool:
    return name in REGISTRY or name in PLANNED


def assert_registered(name: str) -> None:
    """Dipakai helper akses DB dinamis. Melempar ValueError yang menjelaskan langkahnya."""
    if name in DEPRECATED:
        raise ValueError(
            f"Koleksi '{name}' SUDAH DIHAPUS (F0.6). Pakai '{DEPRECATED[name]}'.")
    if not is_registered(name):
        raise ValueError(
            f"Koleksi '{name}' tidak terdaftar. Tulis kontraknya di "
            f"memory/SSOT_KONTRAK_DATA_2026-08-12.md, daftarkan di "
            f"core/collection_registry.py, baru pakai di kode.")


def domain_of(name: str) -> str:
    return REGISTRY.get(name) or PLANNED.get(name) or "tidak-terdaftar"


# ══════════════════════════════════════════════════════════════════════════════
# 2026-11-06 (T5 cutoff "hapus transaksi saja") — JENIS setiap koleksi.
#
# `scripts/reset_for_golive.py --transaksi-saja` MENGHAPUS isi koleksi berjenis
# `transaksi` dan `log`, dan MEMPERTAHANKAN `konfigurasi` serta `master`. Koleksi yang
# ada di basis data tetapi TIDAK tercantum di sini membuat skrip MENOLAK berjalan —
# tidak ada tebakan pola nama. Menambah koleksi baru = tambahkan juga jenisnya di sini
# (uji `test_tahap4_cutoff.py` memeriksa semua koleksi yang disebut kode).
#
#   konfigurasi  setelan sistem, hak akses, penomoran, profil jurnal, kunci periode
#   master       data induk yang tetap berlaku sesudah cutoff (barang, BOM, mitra,
#                karyawan, akun, lokasi, katalog, rencana/target) + riwayat harga master
#   transaksi    dokumen kejadian: PO, terima barang, stok & mutasi, produksi, piutang/
#                hutang, jurnal, absensi, gaji, pesanan marketplace, aktivitas marketing
#   log          jejak buatan sistem & cache: notifikasi, log, percobaan login, hasil AI
# ══════════════════════════════════════════════════════════════════════════════
KIND_KONFIGURASI = "konfigurasi"
KIND_MASTER = "master"
KIND_TRANSAKSI = "transaksi"
KIND_LOG = "log"
KINDS = (KIND_KONFIGURASI, KIND_MASTER, KIND_TRANSAKSI, KIND_LOG)
KIND_LABEL = {KIND_KONFIGURASI: "Konfigurasi", KIND_MASTER: "Master",
              KIND_TRANSAKSI: "Transaksi", KIND_LOG: "Log & cache"}
KINDS_DIHAPUS = (KIND_TRANSAKSI, KIND_LOG)

# Koleksi LAMA yang hanya disentuh skrip migrasi / skrip reset (bukan kode berjalan), atau
# nama di daftar pengaman lama. Tetap diberi jenis supaya basis data lama yang masih
# memuatnya tidak membuat skrip cutoff menolak berjalan.
LEGACY: dict[str, str] = {
    "acc_items": "inventory", "acc_loans": "inventory", "acc_opname_lines": "inventory",
    "acc_opname_sessions": "inventory", "acc_stock_movements": "inventory",
    "backup_config": "lain", "chart_of_accounts": "finance", "company_profile": "lain",
    "dewi_counters": "lain", "rahaza_counters": "lain", "system_counters": "lain",
    "dewi_maklon_orders": "maklon", "dewi_rnd_samples": "rnd",
    "dewi_toko_channel_syncs": "lain", "dewi_toko_channels": "lain",
    "marketing_targets": "marketing", "notification_categories": "lain",
    "notification_providers": "lain", "notification_settings": "lain", "notif_rules": "lain",
    "notif_settings": "lain", "portal_access": "lain", "rate_limits": "lain",
    "rahaza_goods_receipts": "pengadaan", "role_access_overrides": "lain",
    "warehouse_opname": "gudang", "wh_legacy_drop_log": "gudang", "wh_opname_lines": "gudang",
    "wh_opname_sessions": "gudang", "wh_stock_location_migration_log": "gudang",
}

_KONFIGURASI = """
ai_config approval_chains backup_config capacity_config company_profile company_settings counters
dewi_counters dewi_mgmt_alert_config dewi_provider_config dewi_system_config doc_number_configs
document_number_configs employee_expense_gl_mappings marketing_alert_settings
marketing_budget_settings marketing_data_import_formats marketing_dynamic_pricing_settings
marketing_integration_settings marketing_period_locks marketing_settlement_import_maps
notif_category_config notif_rules notif_settings notif_user_prefs notification_categories
notification_providers notification_settings payroll_automation_config pdf_document_settings
pdf_export_configs pdf_templates permissions portal_access portal_quick_links push_subscriptions
rahaza_alert_settings rahaza_approval_delegations rahaza_channel_gl_mapping rahaza_coa_auto_settings
rahaza_costing_settings rahaza_counters rahaza_integration_settings rahaza_payroll_settings
rahaza_periods rahaza_posting_profiles rahaza_setup_state rahaza_zkteco_devices role_access_overrides
role_permissions roles system_counters wh_location_migration_map wh_scan_out_settings
"""

# Pilihan yang tidak jelas dengan sendirinya:
#   * rahaza_material_cost_history & product_cost_snapshots = RIWAYAT HARGA/HPP MASTER (dipakai
#     skrip pemulihan HPP) — dipertahankan bersama `unit_cost`/`hpp` master.
#   * rahaza_depr_schedules & dewi_asset_depreciation = rencana + riwayat penyusutan per aset;
#     menghapusnya membuat aset tidak menyusut lagi dan nilai bukunya salah.
#   * rahaza_leave_balances = jatah cuti (master); kolom `used` direset (lihat DERIVED_FIELDS).
#   * attachments = lampiran berkas; di produksi semuanya milik master (karyawan, model, gaya RnD).
#   * workspace_* dan portal_* (catatan, tugas pribadi, kalender) = isian pengguna, bukan transaksi.
_MASTER = """
acc_items attachments buyers chart_of_accounts comm_channels da_assets da_kpi_goals da_kpi_periods
da_kpi_questions da_payroll_allowances dewi_asset_categories dewi_asset_depreciation dewi_assets
dewi_client_users dewi_cmt_partners dewi_lms_courses dewi_lms_materials dewi_lms_quizzes
dewi_maklon_bom_templates dewi_maklon_buyer_catalog dewi_maklon_clients dewi_onboarding_templates
dewi_org_positions dewi_org_units dewi_perf_cycles dewi_perf_kpis dewi_recruitment_jobs dewi_rnd_hpp
dewi_rnd_materials dewi_rnd_patterns dewi_rnd_revisions dewi_rnd_sample_costing dewi_rnd_styles
dewi_rnd_tech_packs dewi_rnd_variants dewi_toko_channels dewi_toko_products employee_documents
employee_expense_categories employee_per_diem_rates fx_rates garments hr_issued_documents
hr_shift_assignments hr_shift_pola hris_cycles hris_kpi_assignments marketing_account_targets marketing_budgets
marketing_catalog_items marketing_catalogs marketing_creator_catalog marketing_creator_targets
marketing_kol_creators marketing_livehost_scripts marketing_livehost_training marketing_livehosts
marketing_platform_accounts marketing_sku_bridge marketing_targets marketing_task_templates
portal_calendar_events portal_notes portal_reminders portal_todos product_cost_snapshots
product_variants products rahaza_360_cycles rahaza_boms rahaza_budget_items rahaza_budgets
rahaza_cash_accounts rahaza_coa_accounts rahaza_colors rahaza_cost_centers rahaza_customers
rahaza_defect_codes rahaza_depr_schedules rahaza_employees rahaza_expense_categories rahaza_fg_matrix
rahaza_fingerprint_profiles rahaza_fixed_assets rahaza_handover_templates rahaza_job_postings
rahaza_leave_balances rahaza_leave_types rahaza_line_assignments rahaza_lines rahaza_locations
rahaza_machines rahaza_material_categories rahaza_material_cost_history rahaza_materials rahaza_sku_price_history
rahaza_model_costing rahaza_model_process_sop rahaza_model_variants rahaza_models
rahaza_office_locations rahaza_okr_key_results rahaza_okr_objectives rahaza_payroll_profiles
rahaza_petty_cash_funds rahaza_processes rahaza_product_categories rahaza_production_calendar
rahaza_racks rahaza_salary_grades rahaza_schedules rahaza_shift_templates rahaza_shifts rahaza_sizes
rahaza_skill_requirements rahaza_styles rahaza_supplier_price_lists rahaza_suppliers
rahaza_variant_options rahaza_webauthn_credentials study_groups users vendor_partners wh_buildings
wh_positions wh_racks wh_unit_conversions wh_unit_master wh_zones workspace_documents
workspace_shares workspace_versions
"""

_TRANSAKSI = """
hr_shift_requests dewi_po_denda
acc_loans acc_opname_lines acc_opname_sessions acc_purchase_requests acc_stock_movements
accessory_shipment_items accessory_shipments approval_requests bank_recon_matches bank_recon_sessions
bank_recon_txns buyer_shipment_items buyer_shipments buyer_short_records cmt_delivery_notes
cmt_receipt_lines cmt_receipts cmt_short_shipments cutting_orders cutting_progress
da_asset_assignments da_kpi_badges da_kpi_perform da_kpi_results da_kpi_submissions
dewi_accessory_requests dewi_asset_assignments dewi_asset_disposal_requests dewi_asset_loans
dewi_asset_maintenance dewi_asset_pm_acknowledgments dewi_asset_transfers dewi_cmt_ap_schedules
dewi_cmt_component_requests dewi_cmt_deliveries dewi_cmt_delivery_orders dewi_cmt_disbursements
dewi_cmt_jobs dewi_cmt_payments dewi_cmt_permak dewi_cmt_progress dewi_cmt_progress_reports
dewi_cutting_batches dewi_cutting_requests dewi_delivery_orders dewi_hpp_snapshots_maklon
dewi_hpp_snapshots_po dewi_kasbon_requests dewi_kreator_requests dewi_lms_attempts
dewi_lms_enrollments dewi_lms_progress dewi_lms_submissions dewi_maklon_advance_payments
dewi_maklon_bom dewi_maklon_credit_notes dewi_maklon_dispatches dewi_maklon_hpp
dewi_maklon_inventory dewi_maklon_invoices dewi_maklon_material_issues dewi_maklon_material_receive
dewi_maklon_orders dewi_maklon_payments dewi_maklon_pos dewi_maklon_qc_checks
dewi_maklon_sample_revisions dewi_maklon_samples dewi_material_issues dewi_onboarding_checklists
dewi_perf_assignments dewi_perf_reviews dewi_procurement_requests dewi_recruitment_candidates
dewi_rnd_sample_requests dewi_rnd_samples dewi_toko_flashsales dewi_toko_orders
dewi_toko_pack_batches dewi_toko_returns dewi_toko_reviews employee_travel_requests
employee_travel_settlements fg_cost_consumptions fg_cost_layers fx_revaluation_runs hris_assignments
hris_reviews hris_training_completions invoice_adjustments invoice_change_history
invoice_edit_requests invoices marketing_ab_experiments marketing_ads_data marketing_complaints
marketing_content_calendar marketing_creator_incentive_entries marketing_creator_item_requests
marketing_creator_sessions marketing_creator_weekly_reports marketing_data_import_sessions
marketing_data_import_undo marketing_discount_campaigns marketing_discounts
marketing_dynamic_pricing_events marketing_import_history marketing_import_sessions
marketing_import_uploads marketing_kol_campaigns marketing_live_session_products
marketing_live_sessions marketing_livehost_shifts marketing_livehost_training_progress
marketing_orders marketing_platform_kpi_daily marketing_platform_withdrawals
marketing_product_launches marketing_returns marketing_reviews marketing_sales_data
marketing_sample_shipments marketing_samples marketing_settlements marketing_spend_entries
marketing_tasks material_defect_reports material_request_items material_requests payments
payroll_entries payroll_runs payslips peer_feedbacks po_accessories po_items production_job_items
production_jobs production_material_returns production_pos production_progress
production_return_items production_returns production_variances rahaza_accruals rahaza_ap_invoices
rahaza_ap_payments rahaza_ar_invoices rahaza_ar_payments rahaza_attendance rahaza_attendance_audit
rahaza_attendance_corrections rahaza_attendance_events rahaza_bank_recon_adjustments
rahaza_bank_transfers rahaza_bundles rahaza_cash_movements rahaza_credit_notes rahaza_debit_notes
rahaza_downtime_events rahaza_employee_data_changes rahaza_employee_loan_repayments rahaza_employee_loans
rahaza_expense_claims
rahaza_expenses rahaza_fg_inventory rahaza_fg_issues rahaza_fg_movements rahaza_fg_reservations
rahaza_fingerprint_imports rahaza_goods_receipts rahaza_grn_inspections rahaza_hpp_snapshots
rahaza_intercompany_txns rahaza_inventory_revaluations rahaza_job_applications rahaza_journal_entries rahaza_journal_lines
rahaza_leave_requests rahaza_machine_downtime rahaza_maintenance_logs rahaza_maklon_quotes
rahaza_material_issues rahaza_material_movements rahaza_material_reservations rahaza_material_stock
rahaza_orders rahaza_overtime_requests rahaza_payroll_runs rahaza_payslips rahaza_petty_cash_txns
rahaza_purchase_orders rahaza_purchase_returns rahaza_qc_events rahaza_salary_adjustments
rahaza_shift_handovers rahaza_shipments rahaza_stock_ledger rahaza_wip_events rahaza_work_orders
rahaza_year_end_closings sales_direct_notes sales_direct_returns vendor_jobs
vendor_material_inspection_items vendor_material_inspections vendor_progress_reports
vendor_shipment_items vendor_shipments warehouse_opname warehouse_receiving wh_cmt_dispatches
wh_delivery_notes wh_fabric_roll_imports wh_fabric_roll_movements wh_fabric_rolls wh_opname3_counts wh_opname3_sessions
wh_opname_lines wh_opname_sessions wh_opname_sessions2 wh_pending_movements wh_picklists
wh_placement_movements wh_quarantine_items wh_returns wh_scan_out_controls wh_scan_out_lines
wh_scan_out_rejects wh_scan_out_sheets wms_fabric_rolls work_orders
"""

_LOG = """
acc_valuation_report_runs activity_logs ai_business_summaries ai_rca_history ai_response_cache
announcements assistant_chat_history client_login_attempts comm_conversations comm_messages
comm_read_receipts cron_runs dewi_ai_actions dewi_asset_scans dewi_scheduler_runs
dewi_toko_channel_syncs dewi_universal_scans hr_ai_results legacy_drop_log legacy_loan_close_log
login_attempts marketing_account_health marketing_ai_content_history marketing_alert_runs
marketing_catalog_bulk_runs marketing_change_log marketing_churn_scores marketing_dynamic_pricing_suggestions
marketing_import_templates marketing_kol_login_attempts marketing_stock_syncs marketing_webhook_events
notifications payroll_automation_log rahaza_ai_audit_logs rahaza_ai_chat_history rahaza_ai_usage_logs
rahaza_alerts rahaza_audit_logs rahaza_career_chats rahaza_career_reports
rahaza_maintenance_predictions rahaza_period_alerts rahaza_skill_analyses rahaza_webauthn_challenges
rate_limit_buckets rate_limits reminders sync_log wh_barcode_print_jobs wh_legacy_drop_log
wh_rack_alerts wh_rca_audit wh_stock_location_migration_log wh_stock_schema_reconcile_log
"""

# Asisten AI (laporan): laporan buatan Asisten AI = log (boleh dihapus saat cutoff).
_LOG += " ai_reports "


# Asisten AI (inti) — 2026-11-07 Tahap A: percakapan Asisten AI = jejak/log (dihapus saat cutoff).
_LOG += """
ai_chat_messages ai_chat_sessions
"""
# Tahap B (8 Nov 2026): jejak tindakan AI (kartu konfirmasi, keputusan, hasil, pembalikan).
_LOG += " ai_actions "
# Tahap E (9 Nov 2026): metadata lampiran percakapan + berkas keluaran kode (berkasnya di penyimpanan unggahan).
_LOG += " ai_lampiran ai_berkas "
# ── akhir Asisten AI (inti) ──
# Asisten AI (proaktif) — Tahap D: ingatan = preferensi per pengguna, jenis sama dengan `notif_user_prefs`
# (konfigurasi: bertahan saat cutoff); jejak jalan proaktif = log (boleh dihapus saat cutoff).
_KONFIGURASI += " ai_memories "
_LOG += " ai_proaktif_runs "
# ── akhir Asisten AI (proaktif) ──
# 2026-11-09 (agen MKT-AI) — impor banyak berkas satu langkah, pemetaan kolom per toko yang
# dikonfirmasi staf (AI pemeta), dan paket fakta Laporan Marketing mode AI (penjaga angka).
REGISTRY.update({
    "marketing_impor_paket": "marketing",
    "marketing_impor_pemetaan_toko": "marketing",
    "ai_fakta_laporan_marketing": "lain",
})
_TRANSAKSI += " marketing_impor_paket "
_KONFIGURASI += " marketing_impor_pemetaan_toko "
_LOG += " ai_fakta_laporan_marketing "
# ── akhir MKT-AI ──
# 2026-11-10 — Monitoring Staf ERP (Portal Manajemen): aturan kewajiban = konfigurasi owner (bertahan saat cutoff);
# kejadian kewajiban = turunan dari dokumen transaksi (ikut dikosongkan bersama transaksi); meter aktivitas harian = log.
REGISTRY.update({
    "kewajiban_aturan": "lain",
    "kewajiban_kejadian": "lain",
    "pantau_aktivitas_harian": "lain",
})
_KONFIGURASI += " kewajiban_aturan "
_TRANSAKSI += " kewajiban_kejadian "
_LOG += " pantau_aktivitas_harian "
# ── akhir Monitoring Staf ──
# 2026-11-14 — Usulan AI di Jembatan SKU: usulan varian dari Asisten AI per kombinasi SKU + variasi (menunggu persetujuan
# staf). Turunan yang bisa diminta ulang ⇒ log (boleh dihapus saat cutoff; penautan yang disetujui ada di jembatan).
REGISTRY.update({"marketing_sku_usulan": "marketing"})
_LOG += " marketing_sku_usulan "
# ── akhir Usulan AI Jembatan SKU ──


def _kind_table() -> dict[str, str]:
    out: dict[str, str] = {}
    for kind, blob in ((KIND_KONFIGURASI, _KONFIGURASI), (KIND_MASTER, _MASTER),
                       (KIND_TRANSAKSI, _TRANSAKSI), (KIND_LOG, _LOG)):
        for name in blob.split():
            if name in out:
                raise RuntimeError(f"koleksi '{name}' terdaftar di dua jenis: {out[name]} & {kind}")
            out[name] = kind
    return out


KIND: dict[str, str] = _kind_table()


def kind_of(name: str) -> str | None:
    """Jenis koleksi (konfigurasi/master/transaksi/log) — None bila BELUM diklasifikasi."""
    return KIND.get(name)


def all_known() -> set[str]:
    return set(REGISTRY) | set(PLANNED) | set(DEPRECATED) | set(LEGACY)


# ── Penghitung nomor (`counters._id`) yang BUKAN pola `autonum:<koleksi>:…` ────────────
# `--reset-nomor` hanya mereset penghitung milik koleksi TRANSAKSI/LOG. Kunci yang tidak
# cocok dengan tabel ini (dan bukan nama koleksi) membuat skrip menolak `--reset-nomor`.
COUNTER_KEY_PREFIX_KIND: tuple[tuple[str, str], ...] = (
    ("docnum:", KIND_TRANSAKSI),         # utils.doc_numbering — nomor surat jalan buyer/DA
    ("lkp_", KIND_TRANSAKSI),            # nomor LKP produksi per tahun
    ("mi_number", KIND_TRANSAKSI),       # nomor Material Issue lama
    ("model_code_", KIND_MASTER),        # kode model baru — JANGAN direset (kode master bisa kembar)
)
COUNTER_KEY_EXACT_KIND: dict[str, str] = {
    "RCV": KIND_TRANSAKSI, "IRM": KIND_TRANSAKSI, "IFG": KIND_TRANSAKSI, "MOV": KIND_TRANSAKSI,
}


def counter_kind(key: str) -> str | None:
    """Jenis pemilik sebuah penghitung nomor — None bila tidak dikenal."""
    key = str(key or "")
    if key.startswith("autonum:"):
        parts = key.split(":")
        return kind_of(parts[1]) if len(parts) > 1 else None
    if key in COUNTER_KEY_EXACT_KIND:
        return COUNTER_KEY_EXACT_KIND[key]
    for prefix, kind in COUNTER_KEY_PREFIX_KIND:
        if key.startswith(prefix):
            return kind
    return kind_of(key)


# ── Field TURUNAN di koleksi master yang menyimpan keadaan transaksi ─────────────────────
# Keputusan per field. `reset` = nilai bersih pembukaan yang ditulis skrip cutoff (sama
# dengan nilai yang akan dihitung sistem bila transaksinya memang tidak ada); `unset` =
# field dihapus; `keep` = sengaja DIPERTAHANKAN (dicatat supaya keputusannya terbaca).
DERIVED_FIELDS: tuple[dict, ...] = (
    {"collection": "marketing_catalog_items",
     "reset": {"stock_quantity": 0, "stock_status": "out_of_stock", "fg_onhand": 0, "fg_reserved": 0,
               "fg_available": 0, "fg_excluded_onhand": 0, "stock_in_sync": True},
     "unset": ["hpp_fifo_avg", "hpp_last_batch"],
     "keep": ["hpp", "harga_jual", "harga_coret", "price", "catalog_status", "fg_material_id"],
     "alasan": "Cache stok jual (core.catalog_stock.cache_patch) berasal dari stok yang dihapus; "
               "nilai sesudah cutoff = 0 / habis. HPP & harga jual = master."},
    {"collection": "marketing_catalogs", "special": "catalog_stats",
     "alasan": "Rekap per katalog (total_stock, low_stock_count, out_of_stock_count) dihitung "
               "ulang dari item aktif sesudah stoknya nol."},
    {"collection": "rahaza_materials",
     "unset": ["hpp_fifo_avg", "hpp_last_batch", "hpp_layer_qty", "last_receipt_unit_cost"],
     "keep": ["unit_cost", "wac_components", "hpp", "hpp_breakdown", "cost_method", "cutting_order_id"],
     "alasan": "unit_cost (HPP master / harga rata-rata) DIPERTAHANKAN sebagai harga master. Sisa "
               "lapisan FIFO lama & harga penerimaan terakhir berasal dari lapisan/penerimaan yang "
               "dihapus. cutting_order_id panel potong = asal-usul master, tidak dibaca ulang."},
    {"collection": "dewi_maklon_buyer_catalog",
     "reset": {"total_qty_produced": 0, "total_revenue": 0.0, "last_used_at": None},
     "keep": ["default_cmt_price", "default_selling_price", "price_history"],
     "alasan": "Akumulasi produksi & pendapatan per artikel berasal dari PO yang dihapus."},
    {"collection": "rahaza_cash_accounts",
     "reset": {"opening_balance": 0.0, "opening_balance_date": None, "opening_je_id": None,
               "opening_je_number": None, "opening_post_error": None},
     "alasan": "Jurnal saldo awal ikut terhapus bersama jurnal; saldo awal kas/bank diisi ulang "
               "per tanggal cutoff (memposting jurnal pembukaan baru)."},
    {"collection": "rahaza_petty_cash_funds", "reset": {"current_balance": 0.0},
     "alasan": "Saldo kas kecil = akumulasi transaksi kas kecil yang dihapus."},
    {"collection": "rahaza_leave_balances", "reset": {"used": 0},
     "keep": ["allocated", "adjustments"],
     "alasan": "Cuti terpakai = jumlah pengajuan cuti yang dihapus; jatah & penyesuaian HR tetap."},
    {"collection": "dewi_lms_courses", "reset": {"enrollment_count": 0, "completion_count": 0},
     "alasan": "Hitungan peserta berasal dari pendaftaran kursus yang dihapus."},
    {"collection": "rahaza_job_postings", "reset": {"application_count": 0},
     "alasan": "Hitungan pelamar berasal dari lamaran yang dihapus."},
    {"collection": "dewi_recruitment_jobs", "reset": {"candidate_count": 0, "hired_count": 0},
     "alasan": "Hitungan kandidat berasal dari kandidat yang dihapus."},
    {"collection": "marketing_platform_accounts", "reset": {"health_score": None, "health_grade": None},
     "keep": ["coa_cash_code", "coa_receivable_code", "coa_revenue_code", "credentials"],
     "alasan": "Skor kesehatan toko dihitung dari potret harian yang dihapus (log)."},
    {"collection": "rahaza_fixed_assets",
     "keep": ["ap_invoice_id", "ap_invoice_number", "opening_accumulated_depr"],
     "alasan": "Aset = master. Tautan faktur perolehan & jadwal penyusutan dibiarkan sebagai riwayat; "
               "harga perolehan & akumulasi penyusutan per cutoff masuk jurnal pembukaan."},
    {"collection": "rahaza_periods", "keep": ["status", "closed_at", "locked_at"],
     "alasan": "Status buka/tutup periode akuntansi adalah keputusan Keuangan, bukan transaksi."},
    {"collection": "users", "keep": ["last_login_at", "password"],
     "alasan": "Semua pengguna & sandinya tetap (master)."},
)


def derived_field_rules(collection: str) -> list[dict]:
    return [r for r in DERIVED_FIELDS if r["collection"] == collection]
