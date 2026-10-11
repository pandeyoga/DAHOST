"""migrations/ensure_indexes.py — SATU tempat semua indeks MongoDB (FASE 4 / T-24, T-12).

Dulu 416 `create_index` hidup di `server.py` dan dijalankan setiap boot. Sekarang:
  · dipanggil saat startup HANYA bila env `ENSURE_INDEXES` != "0" (bawaan: jalan, aman untuk preview/dev);
  · di produksi (`deploy/update.sh`) dijalankan eksplisit sekali per deploy:
        docker compose exec -T backend python migrations/ensure_indexes.py
    lalu set `ENSURE_INDEXES=0` di compose agar boot cepat.
Idempoten: create_index tidak mengubah indeks yang sudah ada.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from database import get_db  # noqa: E402

logger = logging.getLogger("ensure_indexes")


async def _ensure_unique_index(db, coll: str, keys: list, *, name: str,
                               partial: dict | None = None,
                               drop_conflicting: list | None = None):
    """Pasang indeks UNIK dengan aman pada koleksi yang mungkin sudah punya
    indeks non-unik untuk pola kunci yang sama (F0.5, 2026-08-12).

    MongoDB menolak dua indeks dengan pola kunci sama tetapi opsi berbeda
    (`IndexOptionsConflict`, code 85). Jadi: buang indeks lama yang disebutkan,
    lalu buat yang unik. Bila masih gagal karena **data duplikat**
    (`DuplicateKeyError`, code 11000), indeks TIDAK dipasang dan alasannya
    dicatat jelas — jalankan `backend/migrations/2026_08_12_sales_data_nested.py`
    untuk menggabungkan duplikat, lalu restart.
    """
    kwargs = {"unique": True, "name": name}
    if partial:
        kwargs["partialFilterExpression"] = partial
    for attempt in (1, 2):
        try:
            await db[coll].create_index(keys, **kwargs)
            return True
        except Exception as e:
            code = getattr(e, "code", None)
            if attempt == 1 and code in (85, 86):
                for old in (drop_conflicting or []):
                    try:
                        await db[coll].drop_index(old)
                        logger.info("[index] %s: indeks lama '%s' dibuang untuk "
                                    "digantikan indeks UNIK '%s'", coll, old, name)
                    except Exception:
                        pass
                continue
            if code == 11000:
                logger.error("[index] %s: indeks UNIK '%s' TIDAK dipasang — masih ada "
                             "DATA DUPLIKAT. Jalankan migrasi penggabung duplikat "
                             "lalu restart backend. Detail: %s", coll, name, e)
            else:
                logger.warning("[index] %s: gagal memasang '%s': %s", coll, name, e)
            return False


async def create_indexes():
    """Create MongoDB indexes for active collections only (PT Rahaza)."""
    db = get_db()
    try:
        # Auth / RBAC
        await db.users.create_index("email", unique=True)
        await db.roles.create_index("name", unique=True)
        await db.permissions.create_index("key", unique=True)
        await db.activity_logs.create_index([("timestamp", -1)])

        # MongoDB-backed Rate Limiter — TTL index for auto-cleanup
        await db.rate_limit_buckets.create_index("key")
        await db.rate_limit_buckets.create_index("ts")
        await db.rate_limit_buckets.create_index("expire_at", expireAfterSeconds=0)

        # Warehouse (reused) — only `warehouse_receiving` index retained.
        # `warehouse_locations`, `warehouse_stock`, `warehouse_movements`,
        # `warehouse_opname` indexes REMOVED in Session #11.16 Phase A
        # along with the collections themselves (SSOT successors:
        # wh_positions / rahaza_material_stock / rahaza_material_movements /
        # wh_opname_sessions2). See FORENSIC_04 Cluster 3.
        await db.warehouse_receiving.create_index("receipt_number", unique=True)
        await db.warehouse_receiving.create_index("status")
        await db.warehouse_receiving.create_index("created_at")

        # Accessories master index REMOVED in Session #11.16 Phase A
        # (`accessories` dropped — SSOT: rahaza_materials with type='accessory').
        # See FORENSIC_04 Cluster 1.

        # PT Rahaza master data — unique code on active records only
        # (use partial index so deactivated codes can be reused)
        pfe_active = {"partialFilterExpression": {"active": True}}
        # Drop old non-partial unique indexes if they exist
        for col in ["rahaza_locations", "rahaza_processes", "rahaza_shifts", "rahaza_machines", "rahaza_lines"]:
            try:
                await db[col].drop_index("code_1")
            except Exception:
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
        try:
            await db["rahaza_employees"].drop_index("employee_code_1")
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

        await db.rahaza_locations.create_index("code", unique=True, **pfe_active)
        await db.rahaza_processes.create_index("code", unique=True)  # process seeded, no soft-delete reuse
        await db.rahaza_shifts.create_index("code", unique=True, **pfe_active)
        await db.rahaza_machines.create_index("code", unique=True, **pfe_active)
        # FASE 4: index rahaza_lines & rahaza_line_assignments dihapus (koleksi DELETE E10)
        await db.rahaza_employees.create_index("employee_code", unique=True, **pfe_active)

        # Rahaza production execution (Fase 4)
        await db.rahaza_models.create_index("code", unique=True, **pfe_active)
        await db.rahaza_sizes.create_index("code", unique=True, **pfe_active)
        await db.rahaza_wip_events.create_index([("line_id", 1), ("timestamp", -1)])
        await db.rahaza_wip_events.create_index([("process_id", 1), ("timestamp", -1)])
        await db.rahaza_wip_events.create_index("timestamp")
        await db.rahaza_wip_events.create_index([("event_date", -1)])                     # FIX: reports query
        await db.rahaza_wip_events.create_index([("event_type", 1), ("event_date", -1)])  # FIX: compound
        await db.rahaza_wip_events.create_index("process_code")                           # FIX: Pareto
        await db.rahaza_wip_events.create_index("operator_id")                            # FIX: payroll PCS

        # Rahaza orders (Fase 5)
        await db.rahaza_customers.create_index("code", unique=True, **pfe_active)
        await db.rahaza_orders.create_index("order_number", unique=True)
        await db.rahaza_orders.create_index("status")
        await db.rahaza_orders.create_index("order_date")
        await db.rahaza_orders.create_index("customer_id")

        # Rahaza BOM — unique (model_id, size_id, color) hanya untuk versi is_active=True.
        # Fase 1: color ditambahkan ke key agar BOM bisa PER-VARIAN (warna beda → BOM beda).
        # color kosong/null = BOM umum (berlaku semua warna).
        for idx_name in ("model_size_active_unique", "model_size_is_active_unique", "model_size_color_active_unique"):
            try:
                await db.rahaza_boms.drop_index(idx_name)
            except Exception:
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
        await db.rahaza_boms.create_index(
            [("model_id", 1), ("size_id", 1), ("color", 1)],
            unique=True,
            name="model_size_color_active_unique",
            partialFilterExpression={"active": True, "is_active": True},
        )
        await db.rahaza_boms.create_index("model_id")

        # Fase 2 — Colors master + Model Variants (SKU unik per warna×size)
        await db.rahaza_colors.create_index("code", unique=True, **pfe_active)
        # SKU unik hanya untuk varian aktif (soft-deleted boleh reuse SKU)
        await db.rahaza_model_variants.create_index("sku", unique=True, **pfe_active)
        # Kombinasi (model, size, color) unik per varian aktif
        await db.rahaza_model_variants.create_index(
            [("model_id", 1), ("size_id", 1), ("color_id", 1)],
            unique=True, name="model_size_color_variant_unique",
            partialFilterExpression={"active": True},
        )
        await db.rahaza_model_variants.create_index("model_id")

        # FASE 4 (E10): index rahaza_work_orders dihapus (koleksi DELETE).
        # wip_events re-anchor job_id (E10) — index job_id utk payroll/HPP per job.
        await db.rahaza_wip_events.create_index("job_id")

        # Rahaza inventory (Fase 7)
        await db.rahaza_materials.create_index("code", unique=True, **pfe_active)
        await db.rahaza_materials.create_index("type")
        await db.rahaza_materials.create_index([("type", 1), ("active", 1)])          # Sprint 3.5: filter by type+active
        await db.rahaza_materials.create_index("min_stock_qty")                         # Sprint 3.5: low-stock queries
        await db.rahaza_material_stock.create_index([("material_id", 1), ("location_id", 1)], unique=True)
        await db.rahaza_material_stock.create_index("location_id")
        await db.rahaza_material_stock.create_index("material_id")                      # Sprint 3.5: stock lookups
        await db.rahaza_material_movements.create_index([("timestamp", -1)])
        await db.rahaza_material_movements.create_index("material_id")
        await db.rahaza_material_issues.create_index("mi_number", unique=True)
        await db.rahaza_material_issues.create_index("job_id")  # FASE 4 (E10): re-anchor job_id
        await db.rahaza_material_issues.create_index("status")

        # Rahaza attendance (Fase 8a)
        await db.rahaza_attendance_events.create_index([("employee_id", 1), ("date", 1)], unique=True)
        await db.rahaza_attendance_events.create_index("date")
        await db.rahaza_attendance_events.create_index("status")
        await db.rahaza_attendance_events.create_index("approval_status")  # Sprint 42 approval queue

        # Sprint 42 — Smart Auto-Attendance indexes
        await db.rahaza_webauthn_credentials.create_index("employee_id")
        await db.rahaza_webauthn_credentials.create_index("credential_id")
        await db.rahaza_webauthn_challenges.create_index("employee_id")
        await db.rahaza_webauthn_challenges.create_index("expires_at")
        await db.rahaza_zkteco_devices.create_index("ip")

        # Rahaza payroll (Fase 8b + 8c)
        await db.rahaza_payroll_profiles.create_index([("employee_id", 1), ("active", 1)])
        await db.rahaza_payroll_profiles.create_index("pay_scheme")
        await db.rahaza_payroll_runs.create_index("run_number", unique=True)
        await db.rahaza_payroll_runs.create_index([("period_from", 1), ("period_to", 1)])
        await db.rahaza_payroll_runs.create_index("status")
        await db.rahaza_payslips.create_index([("run_id", 1), ("employee_id", 1)])
        await db.rahaza_payslips.create_index("employee_id")

        # Sprint 42 — Salary Adjustments (Raise) with Dual Approval
        await db.rahaza_salary_adjustments.create_index("employee_id")
        await db.rahaza_salary_adjustments.create_index("manager_id")
        await db.rahaza_salary_adjustments.create_index("status")
        await db.rahaza_salary_adjustments.create_index([("created_at", -1)])
        await db.rahaza_salary_adjustments.create_index([("kpi_period_id", 1), ("employee_id", 1)])
        # P3 TD-010 Phase B (Session #11.12): notifications now SSOT-only — indexes
        # live alongside other SSOT indexes (see "Notifications SSOT" block below).

        # Rahaza finance (Fase 8.5)
        await db.rahaza_cost_centers.create_index([("code", 1), ("active", 1)])
        await db.rahaza_ar_invoices.create_index("invoice_number", unique=True)
        await db.rahaza_ar_invoices.create_index("status")
        await db.rahaza_ar_invoices.create_index("customer_id")
        await db.rahaza_ap_invoices.create_index("invoice_number", unique=True)
        await db.rahaza_ap_invoices.create_index("status")
        await db.rahaza_cash_accounts.create_index([("code", 1), ("active", 1)])
        await db.rahaza_cash_movements.create_index([("timestamp", -1)])
        await db.rahaza_cash_movements.create_index("account_id")
        await db.rahaza_expenses.create_index([("date", -1)])
        await db.rahaza_expenses.create_index("cost_center_id")

        # Rahaza costing / HPP (Fase 9)
        await db.rahaza_costing_settings.create_index("id", unique=True)
        # FASE 4 (E10): snapshot per-job — index unik lama work_order_id (non-partial)
        # bentrok dgn dokumen job-anchored (field null duplikat) → ganti partial unique.
        try:
            await db.rahaza_hpp_snapshots.drop_index("work_order_id_1")
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
        await db.rahaza_hpp_snapshots.create_index(
            "job_id", unique=True, name="hpp_job_id_unique",
            partialFilterExpression={"job_id": {"$exists": True}})
        await db.rahaza_hpp_snapshots.create_index(
            "work_order_id", unique=True, name="hpp_wo_id_unique",
            partialFilterExpression={"work_order_id": {"$exists": True}})

        # FASE 4 (E10 DELETE): index rahaza_bundles & rahaza_andon_events dihapus.

        # Rahaza SOP (Phase 18D)
        await db.rahaza_model_process_sop.create_index([("model_id", 1), ("process_id", 1)])
        await db.rahaza_model_process_sop.create_index("active")

        # Rahaza Accounting Core (Phase F1)
        await db.rahaza_coa_accounts.create_index("code", unique=True)
        await db.rahaza_coa_accounts.create_index("type")
        await db.rahaza_coa_accounts.create_index("parent_code")
        await db.rahaza_coa_accounts.create_index("active")
        await db.rahaza_journal_entries.create_index("je_number", unique=True)
        await db.rahaza_journal_entries.create_index([("date", -1)])
        await db.rahaza_journal_entries.create_index("status")
        await db.rahaza_journal_entries.create_index("source_module")
        await db.rahaza_journal_lines.create_index("je_id")
        await db.rahaza_journal_lines.create_index([("account_code", 1), ("date", 1)])
        await db.rahaza_journal_lines.create_index("period_code")
        await db.rahaza_periods.create_index("period_code", unique=True)
        await db.rahaza_periods.create_index("year")

        # Rahaza Accounting Core (Phase F2 — Auto-posting)
        await db.rahaza_posting_profiles.create_index("event_type", unique=True)
        await db.rahaza_posting_profiles.create_index("active")
        # Idempotency: (source_module, source_ref) → exactly one active JE
        await db.rahaza_journal_entries.create_index([("source_module", 1), ("source_ref", 1), ("status", 1)])
        # T-10: tepat SATU JE aktif per sumber (ditegakkan DB, bukan read-then-write).
        # Migrasi `scripts/find_duplicate_active_je.py` melaporkan duplikat lama lebih dulu.
        try:
            await db.rahaza_journal_entries.create_index(
                [("source_module", 1), ("source_ref", 1)], unique=True, name="uniq_active_source_ref",
                partialFilterExpression={"status": {"$in": ["posted", "draft"]},
                                         "source_ref": {"$type": "string"}})
        except Exception as _e:  # duplikat lama masih ada → laporkan, jangan gagalkan boot
            logging.getLogger(__name__).error("INDEX uniq_active_source_ref gagal dibuat: %s", _e)
        await db.rahaza_journal_lines.create_index("source_module")
        await db.rahaza_journal_lines.create_index("account_type")

        # Phase 21 — QC v2 + Downtime
        # FASE 4 (E10 DELETE): index rahaza_defect_codes & rahaza_qc_events dihapus (QC-2 BUANG).
        await db.rahaza_machine_downtime.create_index([("start_at", -1)])
        await db.rahaza_machine_downtime.create_index("machine_id")
        await db.rahaza_machine_downtime.create_index("status")
        # Phase 20C — AI
        await db.rahaza_ai_chat_history.create_index([("session_id", 1), ("created_at", 1)])
        await db.rahaza_ai_audit_logs.create_index([("created_at", -1)])
        await db.assistant_chat_history.create_index([("session_id", 1), ("created_at", 1)])
        
        # Phase 22A — Material Reservations & Shift Handovers
        # FASE 4 (E10 DELETE): index rahaza_material_reservations dihapus (per-WO).
        await db.rahaza_shift_handovers.create_index([("date", -1), ("shift_id", 1)])
        await db.rahaza_shift_handovers.create_index("shift_id")
        await db.rahaza_shift_handovers.create_index("supervisor_id")
        await db.rahaza_handover_templates.create_index("active")

        # M5: LKP indexes (race-condition safety + query performance)
        # FASE 4 (E10 DELETE): index rahaza_lkp dihapus (LKP per-WO).

        # Sprint 2.1: Purchase Orders (W-2)
        await db.rahaza_purchase_orders.create_index("po_number", unique=True)
        await db.rahaza_purchase_orders.create_index("status")
        await db.rahaza_purchase_orders.create_index("vendor_name")
        await db.rahaza_purchase_orders.create_index("supplier_id")
        await db.rahaza_purchase_orders.create_index("po_date")
        await db.rahaza_purchase_orders.create_index("created_at")

        # Portal Pengadaan (2026-08-06) — Master Supplier SSOT + price list
        await db.rahaza_suppliers.create_index("code", unique=True)
        await db.rahaza_suppliers.create_index("name_key", unique=True)
        await db.rahaza_suppliers.create_index("is_active")
        await db.rahaza_suppliers.create_index("categories")
        await db.rahaza_supplier_price_lists.create_index(
            [("supplier_id", 1), ("material_id", 1), ("uom", 1), ("is_active", 1)])
        await db.rahaza_supplier_price_lists.create_index("material_id")
        await db.rahaza_grn_inspections.create_index("supplier_id")

        # Sprint 2.3: Leave Management (HR-3)
        await db.rahaza_leave_types.create_index("code", unique=True, **pfe_active)
        await db.rahaza_leave_requests.create_index("employee_id")
        await db.rahaza_leave_requests.create_index("leave_type_id")
        await db.rahaza_leave_requests.create_index("status")
        await db.rahaza_leave_requests.create_index([("from_date", 1), ("to_date", 1)])
        await db.rahaza_leave_requests.create_index("created_at")

        # Sprint 3.1: HR Reports — fast attendance & payroll analytics
        await db.rahaza_attendance_events.create_index([("employee_id", 1), ("date", 1), ("status", 1)])
        await db.rahaza_attendance_events.create_index([("date", 1), ("status", 1)])
        await db.rahaza_payslips.create_index([("run_id", 1), ("status", 1)])
        await db.rahaza_payslips.create_index([("pay_period_from", 1), ("pay_period_to", 1)])

        # Sprint 3.4: Low stock — fast threshold queries
        await db.rahaza_materials.create_index([("type", 1), ("active", 1)])
        await db.rahaza_material_stock.create_index([("material_id", 1), ("quantity", 1)])

        # Phase 4: Maklon Client Portal (external auth)
        await db.dewi_client_users.create_index("email", unique=True)
        await db.dewi_client_users.create_index("client_id")
        await db.dewi_client_users.create_index([("client_id", 1), ("status", 1)])

        # ─── CV. Dewi Aditya — Maklon collections (Phase 2/3) ────────────────
        # Cutting & CMT
        # FASE 4 (E10 DELETE): index dewi_cutting_requests/batches dihapus (cutting engine lama).
        await db.dewi_cmt_partners.create_index("code", unique=True)
        await db.dewi_cmt_jobs.create_index("job_code", unique=True)
        await db.dewi_cmt_jobs.create_index([("partner_id", 1), ("status", 1)])

        # Maklon — clients, orders
        # P1.B cleanup (2026-05-23): dewi_maklon_orders dropped, SSOT is dewi_maklon_pos
        await db.dewi_maklon_clients.create_index("code", unique=True)
        await db.dewi_maklon_clients.create_index("status")

        # Maklon — samples
        await db.dewi_maklon_samples.create_index("sample_code", unique=True)
        await db.dewi_maklon_samples.create_index([("order_id", 1), ("status", 1)])
        await db.dewi_maklon_samples.create_index([("client_id", 1), ("status", 1)])
        await db.dewi_maklon_sample_revisions.create_index([("sample_id", 1), ("created_at", -1)])

        # Maklon — QC
        await db.dewi_maklon_qc_checks.create_index([("order_id", 1), ("created_at", -1)])
        await db.dewi_maklon_qc_checks.create_index([("stage", 1), ("created_at", -1)])

        # Maklon — billing
        await db.dewi_maklon_invoices.create_index("invoice_number", unique=True)
        await db.dewi_maklon_invoices.create_index([("client_id", 1), ("status", 1)])
        await db.dewi_maklon_invoices.create_index("status")
        await db.dewi_maklon_invoices.create_index("issue_date")
        await db.dewi_maklon_invoices.create_index("due_date")
        await db.dewi_maklon_payments.create_index([("invoice_id", 1), ("payment_date", -1)])
        await db.dewi_maklon_hpp.create_index("order_id", unique=True)

        # System config
        await db.dewi_system_config.create_index("key", unique=True)
        await db.dewi_system_config.create_index("category")

        # ── Production-Maklon Overhaul Indexes (New Collections) ──────────────
        # Maklon PO (New)
        await db.dewi_maklon_pos.create_index("po_number", unique=True)
        await db.dewi_maklon_pos.create_index([("client_id", 1), ("status", 1)])
        await db.dewi_maklon_pos.create_index("status")
        await db.dewi_maklon_pos.create_index([("created_at", -1)])
        await db.dewi_maklon_pos.create_index("ar_invoice_id")

        # Maklon Dispatches (New)
        await db.dewi_maklon_dispatches.create_index("dispatch_number", unique=True)
        await db.dewi_maklon_dispatches.create_index([("po_id", 1), ("status", 1)])
        await db.dewi_maklon_dispatches.create_index("client_id")
        await db.dewi_maklon_dispatches.create_index([("created_at", -1)])

        # Maklon Material Receive (New)
        await db.dewi_maklon_material_receive.create_index("po_id")
        await db.dewi_maklon_material_receive.create_index([("created_at", -1)])

        # Maklon BOM (New)
        await db.dewi_maklon_bom.create_index("po_id", unique=True)

        # ── Phase M1: Buyer Catalog (Master Artikel Buyer Maklon) ─────────────
        await db.dewi_maklon_buyer_catalog.create_index("client_id")
        await db.dewi_maklon_buyer_catalog.create_index("status")
        await db.dewi_maklon_buyer_catalog.create_index(
            [("client_id", 1), ("artikel_code", 1)], unique=True
        )
        await db.dewi_maklon_buyer_catalog.create_index("buyer_ref_code")
        await db.dewi_maklon_buyer_catalog.create_index([("updated_at", -1)])

        # ── Phase M2.1: Sample → Buyer Catalog link ───────────────────────────
        await db.dewi_maklon_samples.create_index("buyer_catalog_id")

        # ── Phase M2.2: BOM Template (versioned) ──────────────────────────────
        await db.dewi_maklon_bom_templates.create_index("buyer_catalog_id")
        await db.dewi_maklon_bom_templates.create_index(
            [("buyer_catalog_id", 1), ("version", 1)], unique=True
        )
        await db.dewi_maklon_bom_templates.create_index(
            [("buyer_catalog_id", 1), ("is_active", 1)]
        )

        # Maklon Inventory (material milik klien)
        await db.dewi_maklon_inventory.create_index("maklon_po_ref")
        await db.dewi_maklon_inventory.create_index("maklon_client_id")
        await db.dewi_maklon_inventory.create_index([("created_at", -1)])

        # Maklon Advance Payments
        await db.dewi_maklon_advance_payments.create_index("po_id")
        await db.dewi_maklon_advance_payments.create_index([("created_at", -1)])

        # CMT Progress Reports (New)
        await db.dewi_cmt_progress_reports.create_index([("cmt_job_id", 1), ("report_date", -1)])
        await db.dewi_cmt_progress_reports.create_index([("cmt_partner_id", 1), ("report_date", -1)])
        await db.dewi_cmt_progress_reports.create_index("report_date")
        await db.dewi_cmt_progress_reports.create_index("process_step")

        # CMT Delivery Orders (New)
        await db.dewi_cmt_delivery_orders.create_index("do_number", unique=True)
        await db.dewi_cmt_delivery_orders.create_index([("cmt_job_id", 1), ("status", 1)])
        await db.dewi_cmt_delivery_orders.create_index("cmt_partner_id")
        await db.dewi_cmt_delivery_orders.create_index([("created_at", -1)])

        # Inventory ownership fields (extend existing)
        await db.rahaza_material_stock.create_index("ownership")
        await db.rahaza_material_stock.create_index("inventory_category")
        await db.rahaza_material_stock.create_index("maklon_client_id")

        # P3 TD-010 Phase B (Session #11.12): Notifications SSOT — all 4 legacy
        # domains (dewi/rahaza/collab/marketing_livehost) now write to `notifications`
        # via utils.notif_unified.notif_insert. Indexes consolidated here.
        await db.notifications.create_index([("type", 1), ("created_at", -1)])
        await db.notifications.create_index([("type", 1), ("status", 1), ("created_at", -1)])
        await db.notifications.create_index([("type", 1), ("user_id", 1), ("read", 1)])
        await db.notifications.create_index([("type", 1), ("host_id", 1), ("created_at", -1)])
        await db.notifications.create_index([("type", 1), ("subtype", 1), ("source_ref", 1)])
        await db.notifications.create_index([("type", 1), ("client_id", 1), ("created_at", -1)])
        await db.notifications.create_index([("type", 1), ("channel", 1)])
        await db.notifications.create_index([("type", 1), ("meta.dismissed", 1), ("meta.read_by", 1)])
        await db.notifications.create_index([("type", 1), ("meta.dedup_key", 1), ("created_at", -1)])
        await db.notifications.create_index("id", unique=True, sparse=True)
        # FASE 14 — dedup alarm/digest "belum dinilai" kini PER PENERIMA
        # (`distinct('user_id', …)`). Tanpa index ini query dedup memindai seluruh
        # koleksi `notifications` setiap mutasi aksesoris tanpa harga.
        await db.notifications.create_index(
            [("subtype", 1), ("meta.unvalued_material_id", 1), ("created_at", -1)])
        await db.notifications.create_index(
            [("meta.digest_kind", 1), ("meta.digest_date", 1), ("user_id", 1)])

        # P2 Consolidation #12 (Session #11.14): Shipping SSOT indexes
        # `wh_delivery_notes` (SSOT for Customer Shipping outbound)
        # `wh_cmt_dispatches` (SSOT for CMT vendor outbound)
        # Both supersede `rahaza_shipments` and `dewi_cmt_delivery_orders` (legacy).
        await db.wh_delivery_notes.create_index("id", unique=True, sparse=True)
        await db.wh_delivery_notes.create_index("sj_number", unique=True, sparse=True)
        await db.wh_delivery_notes.create_index("status")
        await db.wh_delivery_notes.create_index([("created_at", -1)])
        await db.wh_delivery_notes.create_index("customer_id")
        await db.wh_cmt_dispatches.create_index("id", unique=True, sparse=True)
        await db.wh_cmt_dispatches.create_index("dispatch_no", unique=True, sparse=True)
        await db.wh_cmt_dispatches.create_index("status")
        await db.wh_cmt_dispatches.create_index([("created_at", -1)])
        await db.wh_cmt_dispatches.create_index("cmt_partner_id")

        # Scheduler audit log
        await db.dewi_scheduler_runs.create_index([("job_id", 1), ("started_at", -1)])
        await db.dewi_scheduler_runs.create_index([("started_at", -1)])

        # Phase 5 Sprint 32 — Toko Online (catalog + channels)
        # P1.D cleanup (2026-05-23): legacy collections dropped. Indexes moved to marketing_* SSOT.
        # Preserved: dewi_toko_flashsales, dewi_toko_pack_batches (no marketing equivalent yet).

        # Phase 5B — Toko Online: preserved collections only
        await db.dewi_toko_pack_batches.create_index("batch_code", unique=True)
        await db.dewi_toko_pack_batches.create_index([("status", 1), ("created_at", -1)])
        await db.dewi_toko_flashsales.create_index([("status", 1), ("start_at", -1)])
        await db.dewi_toko_flashsales.create_index("channel_code")
        # Dewi-KOL legacy indexes REMOVED in Session #11.16 Phase C \u2014
        # collections `dewi_kol_creators` + `dewi_kol_deals` + `dewi_kol_samples`
        # DROPPED. SSOTs: marketing_kol_creators + marketing_kol_sessions +
        # marketing_creator_item_requests. See FORENSIC_04 Cluster 6.

        # Phase 6.2 — LMS
        await db.dewi_lms_courses.create_index("course_id", unique=True)
        await db.dewi_lms_courses.create_index([("status", 1), ("category", 1)])
        await db.dewi_lms_materials.create_index([("course_id", 1), ("order", 1)])
        await db.dewi_lms_enrollments.create_index([("course_id", 1), ("employee_id", 1)], unique=True)
        await db.dewi_lms_enrollments.create_index("employee_id")
        await db.dewi_lms_enrollments.create_index([("status", 1), ("enrolled_at", -1)])

        # Phase 6.3 — Onboarding
        await db.dewi_onboarding_templates.create_index("template_id", unique=True)
        await db.dewi_onboarding_checklists.create_index("checklist_id", unique=True)
        await db.dewi_onboarding_checklists.create_index("employee_id")
        await db.dewi_onboarding_checklists.create_index([("status", 1), ("start_date", -1)])

        # Phase 12 — Kasbon & Pinjaman Karyawan
        await db.dewi_kasbon_requests.create_index("id", unique=True)
        await db.dewi_kasbon_requests.create_index([("employee_id", 1), ("status", 1)])
        await db.dewi_kasbon_requests.create_index([("status", 1), ("created_at", -1)])
        await db.rahaza_channel_gl_mapping.create_index("id", unique=True)
        await db.rahaza_channel_gl_mapping.create_index("channel_key", unique=True)
        await db.rahaza_channel_gl_mapping.create_index([("platform", 1), ("active", 1)])
        await db.dewi_kasbon_requests.create_index("request_number", unique=True)

        # Phase 6.4 — Recruitment / ATS
        await db.dewi_recruitment_jobs.create_index("job_id", unique=True)
        await db.dewi_recruitment_jobs.create_index([("status", 1), ("created_at", -1)])
        await db.dewi_recruitment_candidates.create_index("candidate_id", unique=True)
        await db.dewi_recruitment_candidates.create_index([("job_id", 1), ("stage", 1)])
        await db.dewi_recruitment_candidates.create_index([("stage", 1), ("applied_at", -1)])

        # Phase 6.5 — Org Chart
        await db.dewi_org_units.create_index("unit_id", unique=True)
        await db.dewi_org_units.create_index("parent_id")
        await db.dewi_org_units.create_index([("level", 1), ("is_active", 1)])
        await db.dewi_org_positions.create_index("position_id", unique=True)
        await db.dewi_org_positions.create_index("unit_id")
        
        # Phase 8 — DA KPI System
        await db.da_kpi_periods.create_index("period_id", unique=True)
        await db.da_kpi_periods.create_index([("status", 1), ("created_at", -1)])
        await db.da_kpi_questions.create_index("question_id", unique=True)
        await db.da_kpi_questions.create_index([("eval_type", 1), ("order", 1)])
        await db.da_kpi_submissions.create_index("submission_id", unique=True)
        await db.da_kpi_submissions.create_index([("period_id", 1), ("evaluator_id", 1), ("eval_type", 1)])
        await db.da_kpi_submissions.create_index([("period_id", 1), ("evaluatee_id", 1), ("eval_type", 1)])
        await db.da_kpi_perform.create_index([("period_id", 1), ("employee_id", 1)], unique=True)
        await db.da_kpi_results.create_index("result_id", unique=True)
        await db.da_kpi_results.create_index([("period_id", 1), ("employee_id", 1)], unique=True)
        await db.da_kpi_results.create_index([("employee_id", 1), ("publish_status", 1)])

        # Phase 8.5 — DA Assets + Payroll Allowances
        await db.da_assets.create_index("asset_id", unique=True)
        await db.da_assets.create_index([("category", 1), ("status", 1)])
        await db.da_assets.create_index("asset_code", unique=True)
        await db.da_asset_assignments.create_index("assignment_id", unique=True)
        await db.da_asset_assignments.create_index([("asset_id", 1), ("status", 1)])
        await db.da_asset_assignments.create_index([("employee_id", 1), ("status", 1)])
        await db.da_payroll_allowances.create_index("allowance_id", unique=True)

        # Phase 7 — RnD & Style Master
        await db.dewi_rnd_styles.create_index("style_code", unique=True)
        await db.dewi_rnd_styles.create_index([("status", 1), ("created_at", -1)])
        await db.dewi_rnd_styles.create_index("category")
        await db.dewi_rnd_styles.create_index("buyer")
        await db.dewi_rnd_sample_requests.create_index("sample_code", unique=True)
        await db.dewi_rnd_sample_requests.create_index([("style_id", 1), ("created_at", -1)])
        await db.dewi_rnd_sample_requests.create_index([("status", 1), ("due_date", 1)])
        await db.dewi_rnd_revisions.create_index([("style_id", 1), ("revision_number", -1)])
        await db.dewi_rnd_materials.create_index("material_code", unique=True)
        await db.dewi_rnd_materials.create_index([("category", 1), ("status", 1)])
        await db.dewi_rnd_sample_costing.create_index([("sample_request_id", 1)])

        # ── Session 27 — GAP P0 SOP Indexes ──────────────────────────────────
        await db.dewi_accessory_requests.create_index("request_code", unique=True)
        await db.dewi_accessory_requests.create_index([("status", 1), ("created_at", -1)])
        await db.dewi_accessory_requests.create_index("sample_request_id")
        await db.dewi_accessory_requests.create_index("style_id")
        await db.dewi_accessory_requests.create_index([("urgent", 1), ("status", 1)])

        await db.dewi_kreator_requests.create_index("request_code", unique=True)
        await db.dewi_kreator_requests.create_index([("status", 1), ("created_at", -1)])
        await db.dewi_kreator_requests.create_index("kreator_type")
        await db.dewi_kreator_requests.create_index("kreator_id")
        await db.dewi_kreator_requests.create_index("style_id")

        await db.dewi_cmt_component_requests.create_index("request_code", unique=True)
        await db.dewi_cmt_component_requests.create_index([("status", 1), ("created_at", -1)])
        await db.dewi_cmt_component_requests.create_index("cmt_partner_id")
        await db.dewi_cmt_component_requests.create_index("work_order_id")
        await db.dewi_cmt_component_requests.create_index([("request_type", 1), ("status", 1)])
        await db.dewi_cmt_component_requests.create_index([("urgent", 1), ("status", 1)])

        # ── Marketing Portal (Phase 1–5) ──────────────────────────────────────
        # Indexes kritis untuk query performance (audit: 50-80% improvement)
        await db.marketing_platform_accounts.create_index("id", unique=True)
        await db.marketing_platform_accounts.create_index([("platform", 1), ("status", 1)])
        await db.marketing_platform_accounts.create_index("status")

        # ── F0.5 (2026-08-12) — KUNCI ALAMI dipagari indeks UNIK ─────────────
        # Sebelum ini `sales_account_date_type` hanya indeks biasa, sehingga satu
        # (toko, tanggal, jenis) bisa punya BANYAK dokumen ⇒ omzet bulanan bisa
        # terhitung dua kali tanpa satu pun galat. Migrasi
        # `2026_08_12_sales_data_nested.py` menggabungkan duplikat lebih dulu.
        await _ensure_unique_index(
            db, "marketing_sales_data",
            [("account_id", 1), ("date", 1), ("revenue_type", 1)],
            name="uniq_sales_account_date_type",
            drop_conflicting=["sales_account_date_type"],
        )
        # indeks lama non-unik dengan pola kunci nyaris sama: redundan setelah
        # indeks unik di atas terpasang (hemat memori & tulis).
        try:
            await db.marketing_sales_data.drop_index("sales_account_date_type")
        except Exception:
            pass
        await db.marketing_sales_data.create_index([("date", -1)])
        await db.marketing_sales_data.create_index("account_id")
        await db.marketing_sales_data.create_index("source")

        # Pesanan marketplace: 1 dokumen = 1 pesanan (SSOT §2)
        await _ensure_unique_index(
            db, "marketing_orders",
            [("account_id", 1), ("platform", 1), ("order_id", 1)],
            name="uniq_order_account_platform_orderid",
            partial={"order_id": {"$exists": True}},
        )
        await db.marketing_orders.create_index("account_id")
        await db.marketing_orders.create_index("items.platform_sku_id", sparse=True)
        await db.marketing_orders.create_index("order_channel", sparse=True)
        await db.marketing_orders.create_index("creator_handle", sparse=True)

        # Target & anggaran: satu baris per (toko, periode)
        await _ensure_unique_index(
            db, "marketing_account_targets",
            [("account_id", 1), ("year", 1), ("month", 1)],
            name="uniq_target_account_year_month")
        await _ensure_unique_index(
            db, "marketing_creator_targets",
            [("creator_id", 1), ("year", 1), ("month", 1)],
            name="uniq_creator_target_year_month")
        await _ensure_unique_index(
            db, "marketing_budgets",
            [("account_id", 1), ("period", 1)],
            name="uniq_budget_account_period")

        await db.marketing_kol_creators.create_index("id", unique=True)
        await db.marketing_kol_creators.create_index("login_email", sparse=True)
        await db.marketing_kol_creators.create_index("status")

        # Brute-force login attempt tracking (Creator Portal)
        await db.marketing_kol_login_attempts.create_index("identifier", unique=True)
        await db.marketing_kol_login_attempts.create_index("locked_until")

        await db.marketing_creator_sessions.create_index([("creator_id", 1), ("session_date", -1)])
        await db.marketing_creator_sessions.create_index("creator_id")

        await db.marketing_creator_item_requests.create_index([("creator_id", 1), ("status", 1)])
        await db.marketing_creator_item_requests.create_index("status")

        # LiveHost Management indexes
        await db.marketing_livehosts.create_index("id", unique=True)
        await db.marketing_livehosts.create_index("email", sparse=True)
        await db.marketing_livehosts.create_index("status")
        
        await db.marketing_livehost_shifts.create_index("id", unique=True)
        await db.marketing_livehost_shifts.create_index([("date", -1)])
        await db.marketing_livehost_shifts.create_index([("host_id", 1), ("date", -1)])
        await db.marketing_livehost_shifts.create_index("account_id")
        await db.marketing_livehost_shifts.create_index("attendance_status")
        await db.marketing_livehost_shifts.create_index("payment_status")
        
        # Marketing Webhook Events (Phase 1/2)
        await db.marketing_webhook_events.create_index("id", unique=True)
        await db.marketing_webhook_events.create_index("idempotency_key", unique=True)
        await db.marketing_webhook_events.create_index([("received_at", -1)])
        await db.marketing_webhook_events.create_index("platform")
        await db.marketing_webhook_events.create_index("processed")
        await db.marketing_webhook_events.create_index("event_type")
        
        await db.marketing_livehost_scripts.create_index("id", unique=True)
        await db.marketing_livehost_scripts.create_index("category")
        await db.marketing_livehost_scripts.create_index("is_active")
        
        await db.marketing_livehost_training.create_index("id", unique=True)
        await db.marketing_livehost_training.create_index("category")
        await db.marketing_livehost_training.create_index("is_active")
        
        await db.marketing_livehost_training_progress.create_index("id", unique=True)
        await db.marketing_livehost_training_progress.create_index([("host_id", 1), ("training_id", 1)])
        await db.marketing_livehost_training_progress.create_index("status")
        
        # Payroll entries (for Finance sync)
        await db.payroll_entries.create_index("id", unique=True)
        await db.payroll_entries.create_index([("month", 1), ("employee_id", 1)])
        await db.payroll_entries.create_index("type")
        await db.payroll_entries.create_index("status")

        # Phase 4: LiveHost portal notifications now live in the unified SSOT
        # `notifications` collection (P3 TD-010 Phase B, Session #11.12). Indexes
        # for SSOT are declared in the "Notifications SSOT" block above. The
        # legacy `marketing_livehost_notifications` collection is empty and
        # scheduled for drop after 1-week monitor.

        # Session 28 — Multi-currency FX rates
        await db.fx_rates.create_index("id", unique=True)
        await db.fx_rates.create_index([("currency", 1), ("effective_date", -1)])
        await db.fx_revaluation_runs.create_index("id", unique=True)
        await db.fx_revaluation_runs.create_index([("run_date", -1)])

        await db.marketing_tasks.create_index([("status", 1), ("created_at", -1)])
        await db.marketing_tasks.create_index([("assigned_to", 1), ("status", 1)])
        await db.marketing_tasks.create_index("due_date")

        await db.marketing_catalogs.create_index([("account_id", 1), ("is_active", 1)])
        await db.marketing_catalogs.create_index("id", unique=True)

        await db.marketing_catalog_items.create_index(
            [("catalog_id", 1), ("sku", 1)],
            name="catalog_sku_compound"
        )
        await db.marketing_catalog_items.create_index("catalog_id")
        await db.marketing_catalog_items.create_index("material_id", sparse=True)
        await db.marketing_catalog_items.create_index([("catalog_id", 1), ("stock_status", 1)])

        await db.marketing_stock_syncs.create_index([("catalog_id", 1), ("synced_at", -1)])

        # ── Session 7: Performance indexes for high-traffic collections ─────────
        # Production Jobs — critical for production-jobs list (filter+sort)
        await db.production_jobs.create_index([("created_at", -1)])
        await db.production_jobs.create_index("status")
        await db.production_jobs.create_index("vendor_id")
        await db.production_jobs.create_index("parent_job_id")
        await db.production_jobs.create_index([("parent_job_id", 1), ("created_at", -1)])  # compound filter+sort

        # Production Job Items — used in batch prefetch (job_id $in query)
        await db.production_job_items.create_index("job_id")
        await db.production_job_items.create_index("po_item_id")

        # Buyer Shipment Items — used in batch prefetch (job_id + job_item_id + po_item_id)
        await db.buyer_shipment_items.create_index("job_id")
        await db.buyer_shipment_items.create_index("job_item_id")
        await db.buyer_shipment_items.create_index("po_item_id")
        await db.buyer_shipment_items.create_index("po_id")
        await db.buyer_shipment_items.create_index("shipment_id")

        # Production POs — critical for production-pos list
        await db.production_pos.create_index([("created_at", -1)])
        await db.production_pos.create_index("status")
        await db.production_pos.create_index("vendor_id")

        # PO Items — used in batch prefetch
        await db.po_items.create_index("po_id")
        await db.po_items.create_index("vendor_id")
        await db.po_items.create_index("serial_number")

        # Attachments — queried by (entity_type, entity_id)
        await db.attachments.create_index([("entity_type", 1), ("entity_id", 1)])
        await db.attachments.create_index([("uploaded_at", -1)])

        # Accessories shipments (kept).
        # `accessories` + `accessory_requests` indexes REMOVED in Session #11.16
        # Phase A — collections dropped (SSOTs: rahaza_materials + dewi_accessory_requests).
        # W3 de-dup: accessory_inspections + accessory_defects index REMOVED — route
        # /api/accessory-inspections + /api/accessory-defects DEPRECATED-NOOP (operations.py:
        # GET→[] , POST→410, tidak pernah menyentuh koleksi). Koleksi di-drop. See FORENSIC_04 Cluster 1.
        await db.accessory_shipments.create_index([("created_at", -1)])
        await db.accessory_shipments.create_index("vendor_id")
        await db.accessory_shipments.create_index("po_id")
        await db.accessory_shipment_items.create_index("shipment_id")

        # Invoices / Payments (legacy generic) indexes REMOVED in Session #11.16
        # Phase B \u2014 collections DROPPED (SSOTs: rahaza_ar_invoices +
        # rahaza_ap_invoices + dewi_maklon_invoices for invoices; per-domain
        # payment ledgers for payments). See FORENSIC_04 Cluster 5.

        # Shipments (rahaza_shipments) — list endpoint
        await db.rahaza_shipments.create_index([("shipment_date", -1)])
        await db.rahaza_shipments.create_index("status")
        await db.rahaza_shipments.create_index("customer_id")
        await db.rahaza_shipments.create_index("order_id")

        # DA KPI — paginated list endpoints
        await db.da_kpi_perform.create_index("period_id")
        # NOTE: da_kpi_perform already has unique (period_id, employee_id) index - skip duplicate
        await db.da_kpi_results.create_index("period_id")

        # Portal Kolaborasi Phase 3: Communication Hub + Study Groups
        await db.comm_channels.create_index([("members", 1), ("archived", 1)])
        await db.comm_channels.create_index([("type", 1), ("archived", 1)])
        await db.comm_messages.create_index([("channel_id", 1), ("created_at", -1)])
        await db.comm_messages.create_index([("conversation_id", 1), ("created_at", -1)])
        # Session 28 — thread replies
        await db.comm_messages.create_index([("thread_root_id", 1), ("created_at", 1)])
        await db.comm_conversations.create_index("participants")
        await db.comm_read_receipts.create_index([("user_id", 1), ("ref_id", 1)], unique=True)
        
        # Study Groups indexes (Phase 3.8)
        await db.study_groups.create_index([("members", 1), ("created_at", -1)])
        await db.study_groups.create_index("course_id")
        await db.study_groups.create_index("created_by")

        logger.info("Session 7: Performance indexes created for high-traffic collections")

        # ── Session 8: Push Notification indexes ─────────────────────────────
        await db.push_subscriptions.create_index([("user_id", 1)])
        await db.push_subscriptions.create_index("endpoint", unique=True)
        await db.portal_quick_links.create_index([("user_id", 1), ("order_seq", 1)])

        # ── Impor Data Marketing (jalur resmi tanpa AI) ──────────────────────
        # F0.6 (2026-08-12): `routes/universal_import_indexes.py` dihapus bersama
        # mesin impor AI lama. Indeks yang MASIH berguna dipindah ke sini:
        # `id` unik + `_import_session_id` pada koleksi tujuan impor, plus indeks
        # sesi impor jalur resmi.
        await db.marketing_data_import_sessions.create_index("id", unique=True)
        await db.marketing_data_import_sessions.create_index("status")
        await db.marketing_data_import_sessions.create_index("source_type")
        await db.marketing_data_import_sessions.create_index("file_hash")
        await db.marketing_data_import_sessions.create_index([("created_at", -1)])
        # F3 (2026-08-14) — jejak PEMULIHAN impor `update_only` (Ekspor B/C).
        # `session_id` dibaca setiap kali tombol "Batalkan impor" ditekan; tanpa
        # indeks, satu berkas 20.000 baris membuat pembatalan memindai seluruh
        # koleksi. `doc_id` dipakai audit "pesanan ini pernah diubah impor mana".
        await db.marketing_data_import_undo.create_index("id", unique=True)
        await db.marketing_data_import_undo.create_index([("session_id", 1),
                                                          ("restored_at", 1)])
        await db.marketing_data_import_undo.create_index("doc_id")
        # ── Sesi #20 — Jembatan SKU (marketing_sku_bridge) ────────────────────
        # `platform_sku_id` unik: satu SKU platform tidak boleh punya dua master
        # (kalau boleh, gudang akan mengirim barang yang berbeda untuk pesanan
        # yang sama tergantung dokumen mana yang terbaca lebih dulu).
        # `items.platform_sku_id` pada pesanan: backfill tautan memindai koleksi
        # ini setiap kali satu SKU dipetakan.
        try:
            from core import sku_bridge as _bridge
            await _bridge.ensure_indexes(db)
        except Exception as _e:
            logger.warning("[startup] indeks jembatan SKU gagal: %s", _e)
        # Indeks pesanan dibuat SATU PER SATU: `items.platform_sku_id` sudah ada
        # sebagai index SPARSE dari sesi lama, dan MongoDB menolak permintaan
        # dengan nama sama tetapi opsi beda. Kalau ketiganya dalam satu `try`,
        # penolakan yang tidak berbahaya itu ikut membatalkan dua indeks lain.
        for _spec in ("items.platform_sku_id", "items.fg_material_id", "fulfillment_status"):
            try:
                await db.marketing_orders.create_index(_spec)
            except Exception as _e:
                logger.debug("[startup] indeks marketing_orders.%s dilewati: %s", _spec, _e)
        for _coll in ["marketing_orders", "marketing_complaints", "marketing_reviews",
                      "marketing_ads_data", "marketing_account_health",
                      "marketing_live_sessions", "marketing_content_calendar",
                      "marketing_product_launches", "marketing_sales_data",
                      "marketing_samples", "marketing_returns", "marketing_discounts",
                      "marketing_catalog_items", "marketing_livehost_shifts",
                      "marketing_live_session_products", "marketing_kol_creators"]:
            # TANPA `sparse`/nama khusus: beberapa koleksi sudah punya `id_1` &
            # `_import_session_id_1` non-sparse; meminta opsi berbeda dengan nama
            # otomatis yang sama menimbulkan IndexKeySpecsConflict (code 86).
            try:
                await db[_coll].create_index("id", unique=True)
                await db[_coll].create_index("_import_session_id")
            except Exception as _e:
                logger.debug("[index] %s: %s", _coll, _e)

        # FASE IA-4 — Portal Cutting: pastikan koleksi cutting selalu ada
        # (syarat agar ikut ter-backup oleh mongodump, lihat routes/cutting.py).
        from routes.cutting import ensure_cutting_indexes
        await ensure_cutting_indexes()

        # UOM — pastikan master satuan & aturan konversi selalu ada.
        # Tanpa ini, setelah wipe DB layar "Satuan & Konversi" kosong dan
        # kalkulator konversi melempar 404 (BUG-3 audit 2026-07-27).
        from routes.wms_units import ensure_unit_master
        _uom_seed = await ensure_unit_master(db)
        if _uom_seed.get("units_created") or _uom_seed.get("conversions_created"):
            logger.info(f"[uom] master satuan disiapkan: {_uom_seed}")
        # Note: APScheduler retry_queued_imports job moved to startup() after start_scheduler()
        # in Session #11.17 to fix "scheduler not running" warning.

        # Brute-force protection indexes (Portal Saya)
        from routes.auth_routes import _ensure_brute_force_index
        await _ensure_brute_force_index(db)

        # Brute-force protection indexes (Maklon Client Portal)
        from routes.dewi_client_portal import _ensure_client_bf_index
        await _ensure_client_bf_index(db)

    except Exception as e:
        logger.warning(f"Index creation warning: {e}")

    # ── JARING PENGAMAN NOMOR DOKUMEN (2026-08-07) ───────────────────────────
    # SENGAJA di blok try SENDIRI: bila digabung dengan blok di atas, satu index
    # yang gagal akan MELEWATI semua index sesudahnya tanpa jejak yang jelas.
    # Fungsi ini tidak pernah melempar; ia melaporkan koleksi yang masih memuat
    # nomor dokumen kembar beserta nomornya agar bisa ditindak.
    try:
        from utils.counters import ensure_unique_number_indexes
        await ensure_unique_number_indexes(db, logger)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[nomor-dokumen] gagal memasang index unik: {e}")

    # ── TEMPLATE PDF: MIGRASI SETELAN LAMA (SESI #19) ────────────────────────
    # Dua koleksi setelan PDF lama (`pdf_document_settings` untuk kop & tanda tangan,
    # `pdf_export_configs` untuk kolom) disatukan ke `pdf_templates`. Migrasi
    # IDEMPOTEN dan tidak pernah menimpa setelan yang sudah dibuat di layar baru,
    # sehingga aman dijalankan tiap startup. Blok try SENDIRI: setelan PDF tidak
    # boleh bisa menggagalkan startup — dokumen tetap tercetak dengan bawaan.
    try:
        from core.pdf_template import migrate_legacy as _migrate_pdf_tpl
        await _migrate_pdf_tpl(db, logger)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[pdf-template] migrasi setelan PDF lama dilewati: {e}")


async def create_fase4_indexes(db):
    """T-12 (FASE 4.1): indeks yang selama ini hilang pada koleksi produksi/gudang aktif."""
    specs = [
        ("vendor_shipment_items", "shipment_id"), ("vendor_shipment_items", "po_item_id"),
        ("buyer_shipments", "po_id"), ("vendor_shipments", "po_id"),
        ("cmt_receipts", "status"), ("cmt_receipts", "po_id"), ("cmt_receipts", "receipt_date"),
        ("cmt_receipt_lines", "receipt_id"),
        ("wh_positions", "rack_id"), ("wh_positions", "status"), ("wh_positions", "barcode"),
        ("wh_pending_movements", [("type", 1), ("status", 1)]),
        ("wh_pending_movements", [("source_type", 1), ("source_id", 1)]),
        ("rahaza_boms", "active"), ("rahaza_employees", "active"),
        ("rahaza_locations", "active"), ("rahaza_leave_types", "active"),
        ("production_jobs", "status"), ("production_jobs", "po_id"),
    ]
    for coll, keys in specs:
        try:
            await db[coll].create_index(keys)
        except Exception as e:  # noqa: BLE001
            logger.debug("[index] %s %s: %s", coll, keys, e)


async def ensure_all_indexes() -> None:
    await create_indexes()
    await create_fase4_indexes(get_db())


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(ensure_all_indexes())
    print("indeks selesai dipasang")
