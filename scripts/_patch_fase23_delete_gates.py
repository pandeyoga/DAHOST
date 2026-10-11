#!/usr/bin/env python3
"""FASE 2.3 (T-01): pasang `dependencies=only(*ROLES)` pada dekorator DELETE tanpa gerbang fungsi.
Idempoten: dekorator yang sudah punya `dependencies=` dilewati. Jalankan sekali dari /app."""
import os
import re

ROUTES = os.path.join(os.path.dirname(__file__), "..", "backend", "routes")

# (router, path) -> nama konstanta peran (core.roles)
GATES = {
    ("dewi_accessory_requests", "/{request_id}"): "WAREHOUSE_ROLES",
    ("dewi_ai_actions", "/{action_id}"): "MGMT_ROLES",
    ("dewi_cmt_component_requests", "/{request_id}"): "PRODUCTION_ROLES",
    ("dewi_cmt_packing", "/cmt-receipts/{receipt_id}/lines/{line_id}"): "PRODUCTION_ROLES",
    ("dewi_job_board", "/jobs/{job_id}"): "HR_ROLES",
    ("dewi_kreator_requests", "/{request_id}"): "MARKETING_ROLES",
    ("dewi_lms", "/courses/{course_id}"): "HR_ROLES",
    ("dewi_lms", "/materials/{material_id}"): "HR_ROLES",
    ("dewi_maklon", "/clients/{client_id}"): "MAKLON_ROLES",
    ("dewi_maklon", "/orders/{order_id}/material-issues/{issue_id}"): "MAKLON_ROLES",
    ("dewi_maklon_billing", "/payments/{payment_id}"): "FINANCE_ROLES",
    ("dewi_maklon_bom_templates", "/bom-templates/{template_id}"): "MAKLON_ROLES",
    ("dewi_maklon_buyer_catalog", "/buyer-catalog/{catalog_id}"): "MAKLON_ROLES",
    ("dewi_maklon_qc", "/{qc_id}"): "MAKLON_ROLES",
    ("dewi_maklon_quote", "/{quote_id}"): "MAKLON_ROLES",
    ("dewi_maklon_samples", "/{sample_id}"): "MAKLON_ROLES",
    ("dewi_okr", "/key-results/{kr_id}"): "HR_ROLES",
    ("dewi_onboarding", "/templates/{template_id}/tasks/{task_id}"): "HR_ROLES",
    ("dewi_onboarding", "/templates/{template_id}"): "HR_ROLES",
    ("dewi_onboarding", "/checklists/{checklist_id}/tasks/{task_id}"): "HR_ROLES",
    ("dewi_onboarding", "/checklists/{checklist_id}"): "HR_ROLES",
    ("dewi_org", "/units/{unit_id}"): "HR_ROLES",
    ("dewi_org", "/positions/{position_id}"): "HR_ROLES",
    ("dewi_predictive_maintenance", "/maintenance-logs/{log_id}"): "PRODUCTION_ROLES",
    ("dewi_recruitment", "/jobs/{job_id}"): "HR_ROLES",
    ("dewi_recruitment", "/candidates/{candidate_id}"): "HR_ROLES",
    ("dewi_shift_scheduler", "/templates/{template_id}"): "HR_ROLES",
    ("dewi_shift_scheduler", "/schedules/{schedule_id}"): "HR_ROLES",
    ("dewi_toko", "/flashsales/{flashsale_id}"): "MARKETING_ROLES",
    ("dewi_wh_returns", "/returns/{return_id}"): "WAREHOUSE_ROLES",
    ("hr_shifts", "/assignments/{assignment_id}"): "HR_ROLES",
    ("marketing_accounts", "/accounts/{account_id}"): "MGMT_ROLES",
    ("marketing_ads_routes", "/campaigns/{entry_id}"): "MARKETING_ROLES",
    ("marketing_budget", "/spend/{sid}"): "MARKETING_ROLES",
    ("marketing_content_calendar_routes", "/{entry_id}"): "MARKETING_CS_ROLES",
    ("marketing_data_import", "/formats/{fingerprint}"): "MARKETING_ROLES",
    ("marketing_data_import", "/sessions/{session_id}"): "MARKETING_ROLES",
    ("marketing_discounts_routes", "/{disc_id}"): "MARKETING_ROLES",
    ("marketing_integration_settings_routes", "/{platform}"): "MGMT_ROLES",
    ("marketing_kol_incentive", "/creators/{creator_id}/incentive/entries/{entry_id}"): "MARKETING_ROLES",
    ("marketing_live_sessions_routes", "/sessions/{session_id}"): "MARKETING_ROLES",
    ("marketing_live_sessions_routes", "/sessions/{session_id}/products/{line_id}"): "MARKETING_ROLES",
    ("marketing_livehost_portal", "/{host_id}"): "MARKETING_ROLES",
    ("marketing_livehost_scripts", "/scripts/{script_id}"): "MARKETING_ROLES",
    ("marketing_livehost_shifts", "/shifts/{shift_id}"): "MARKETING_ROLES",
    ("marketing_livehost_training", "/training/{training_id}"): "MARKETING_ROLES",
    ("marketing_product_launches_routes", "/{launch_id}"): "MARKETING_ROLES",
    ("marketing_returns_routes", "/{return_id}"): "MARKETING_CS_ROLES",
    ("marketing_reviews_routes", "/{review_id}"): "MARKETING_CS_ROLES",
    ("marketing_samples_routes", "/{sample_id}"): "MARKETING_ROLES",
    ("marketing_task_templates", "/task-templates/{template_id}"): "MARKETING_ROLES",
    ("marketing_tasks", "/tasks/{task_id}"): "MARKETING_CS_ROLES",
    ("operations", "/accessories/{acc_id}"): "MGMT_ROLES",
    ("operations", "/accessory-shipments/{sid}"): "MGMT_ROLES",
    ("operations_pdf_configs", "/pdf-export-configs/{config_id}"): "MGMT_ROLES",
    ("production_material_returns", "/{return_id}"): "PRODUCTION_ROLES",
    ("rahaza_accruals", "/accruals/{accrual_id}"): "FINANCE_ROLES",
    ("rahaza_budget", "/budgets/{bid}"): "FINANCE_ROLES",
    ("rahaza_budget", "/budgets/{bid}/items/{iid}"): "FINANCE_ROLES",
    ("rahaza_downtime", "/downtime/{dt_id}"): "PRODUCTION_ROLES",
    ("rahaza_payroll_allowances", "/payroll-allowances/{allowance_id}"): "HR_ROLES",
    ("rahaza_production_calendar", "/production-calendar/{entry_id}"): "PRODUCTION_ROLES",
    ("rahaza_shift_handover", "/handover-templates/{template_id}"): "PRODUCTION_ROLES",
    ("rahaza_shipments", "/{sid}"): "WAREHOUSE_ROLES",
    ("sku_bridge", "/mappings/{platform_sku_id}"): "WAREHOUSE_ROLES + MARKETING_ROLES",
    ("warehouse", "/locations/{location_id}"): "WAREHOUSE_ROLES",
    ("warehouse", "/receiving/{receipt_id}"): "WAREHOUSE_ROLES",
    ("wms_legacy", "/locations/{location_id}"): "WAREHOUSE_ROLES",
    ("wms_legacy", "/receiving/{receipt_id}"): "WAREHOUSE_ROLES",
    ("wms_delivery_notes", "/{sj_id}"): "WAREHOUSE_ROLES",
    ("wms_fabric_rolls", "/{roll_id}"): "WAREHOUSE_ROLES",
    ("wms_picklist", "/{picklist_id}"): "WAREHOUSE_ROLES",
    ("wms_structure", "/buildings/{building_id}"): "WAREHOUSE_ROLES",
    ("wms_structure", "/zones/{zone_id}"): "WAREHOUSE_ROLES",
    ("wms_structure", "/racks/{rack_id}"): "WAREHOUSE_ROLES",
    ("wms_units", "/units/{unit_id}"): "WAREHOUSE_ROLES",
    ("wms_units", "/unit-conversions/{conv_id}"): "WAREHOUSE_ROLES",
}


def patch_file(router: str, items: list[tuple[str, str]]) -> int:
    p = os.path.join(ROUTES, router + ".py")
    src = open(p).read()
    n = 0
    consts = set()
    for path, const in items:
        rx = re.compile(r"^(@router\.delete\(\s*['\"]" + re.escape(path) + r"['\"])(.*)\)\s*$", re.M)
        m = rx.search(src)
        if not m:
            print("  ! tidak ditemukan", router, path)
            continue
        if "dependencies=" in m.group(2):
            continue
        expr = " + ".join(f"*{c.strip()}" for c in const.split("+"))
        expr = ", ".join(f"*{c.strip()}" for c in const.split("+"))
        src = src[:m.start()] + f"{m.group(1)}{m.group(2)}, dependencies=only({expr}))  # T-01 2.3" + src[m.end():]
        consts.update(c.strip() for c in const.split("+"))
        n += 1
    if n:
        imp = f"from core.authz import only  # T-01 2.3\nfrom core.roles import {', '.join(sorted(consts))}  # T-01 2.3\n"
        # sisipkan setelah baris import terakhir di blok header
        lines = src.split("\n")
        idx = 0
        for i, ln in enumerate(lines[:80]):
            if ln.startswith(("from ", "import ")) and not ln.startswith("from __future__"):
                idx = i + 1
        # lompati kelanjutan import multi-baris
        while idx < len(lines) and lines[idx - 1].rstrip().endswith(("(", ",", "\\")):
            idx += 1
        if "from core.authz import only" in src:
            # tambah konstanta yang belum di-import
            src = "\n".join(lines)
            m2 = re.search(r"^from core\.roles import ([^\n]+?)\s*# T-01 2\.3$", src, re.M)
            have = {c.strip() for c in m2.group(1).split(",")}
            src = src.replace(m2.group(0), f"from core.roles import {', '.join(sorted(have | consts))}  # T-01 2.3")
        else:
            lines.insert(idx, imp.rstrip("\n"))
            src = "\n".join(lines)
        open(p, "w").write(src)
    return n


def main():
    by_router: dict = {}
    for (router, path), const in GATES.items():
        by_router.setdefault(router, []).append((path, const))
    total = 0
    for router, items in sorted(by_router.items()):
        n = patch_file(router, items)
        total += n
        if n:
            print(f"  {router}: {n} DELETE diberi gerbang")
    print("total:", total)


if __name__ == "__main__":
    main()
