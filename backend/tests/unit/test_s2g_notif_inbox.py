"""Uji unit HERMETIK paket S2-G — NOTIFIKASI "Perlu Tindakan" vs "Pemberitahuan" (2026-11-02).

Keputusan owner:
  · K30 — notifikasi ber-`kind` action/info; action membawa tombol aksi + sumber +
          aturan selesai; notifikasi lama diklasifikasikan dari subtype; action
          tertutup otomatis (SATU resolver generik) lalu pindah ke riwayat;
  · satu kotak masuk: bel + Approval Inbox digabung, lencana tanpa hitung dobel;
  · K31 — retensi `retention_days` (bawaan 90) di pengaturan yang sama; action
          terbuka tidak pernah dihapus; pembersihan duplikat lama ber-dry-run;
  · K37 — stok kritis → wh-stock; klaim → fin-expenses untuk Keuangan, layar SDM untuk HR;
  · K32 — HR tetap boleh membaca semua inbox.

Jalankan:  cd backend && python -m pytest tests/unit/test_s2g_notif_inbox.py -q
"""
import asyncio
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402
from utils import notif_unified as nu  # noqa: E402

FRONTEND = os.path.join(BACKEND, "..", "frontend", "src")
NOW = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def seed(db, coll, *docs):
    for d in docs:
        db[coll].docs.append(dict(d))


def notif(db, nid):
    return next(d for d in db.notifications.docs if d["id"] == nid)


def frontend_registry_ids():
    path = os.path.join(FRONTEND, "components", "erp", "moduleRegistry.js")
    if not os.path.exists(path):
        pytest.skip("frontend/src tidak tersedia di lingkungan uji ini")
    src = open(path, encoding="utf-8").read()
    return {m.group(1) for m in re.finditer(r"^\s*['\"]([\w\-:]+)['\"]\s*:", src, re.M)}


# ═══ K30 — KLASIFIKASI ═══════════════════════════════════════════════════════
@pytest.mark.parametrize("doc,kind", [
    ({"subtype": "procurement_approval", "source_id": "pr1", "meta": {"link_module": "proc-requests"}}, "action"),
    ({"subtype": "expense_claim_submitted", "source_id": "c1"}, "action"),
    ({"subtype": "leave_request_submitted", "source_id": "l1"}, "action"),
    ({"subtype": "attendance_permit_request", "source_id": "s1"}, "action"),
    ({"subtype": "salary_raise_hr_approval", "source_id": "a1"}, "action"),
    ({"subtype": "low_stock", "source_id": "m1"}, "action"),
    ({"subtype": "negative_stock_daily"}, "action"),           # kondisi global, tanpa id
    ({"subtype": "contract_expiry", "source_id": "e1"}, "action"),
    ({"subtype": "low_stock"}, "info"),                         # tanpa sumber → tak bisa ditutup → info
    ({"subtype": "birthday", "source_id": "e1"}, "info"),
    ({"subtype": "leave_approved", "source_id": "l1"}, "info"),
    ({"subtype": "rnd_weekly_decisions"}, "info"),
    ({"subtype": "sla_breach"}, "info"),
    ({"subtype": "low_stock", "source_id": "m1", "kind": "info"}, "info"),   # field tersimpan menang
])
def test_kind_from_legacy_subtype(doc, kind):
    assert nu.kind_of(doc) == kind


def test_insert_action_carries_action_source_and_rule():
    db = FakeDB()
    nid = run(nu.notif_insert(db, type="rahaza", subtype="expense_claim_submitted", body="x",
                              source_id="c1", target_roles=["hr"],
                              meta={"link_module": "hr-approval-inbox"}))
    d = notif(db, nid)
    assert d["kind"] == "action" and d["resolved_at"] is None
    assert d["source_collection"] == "rahaza_expense_claims"
    assert d["resolve_rule"]["open"] == ["submitted"]
    assert d["action"] == {"label": "Putuskan klaim", "target_menu": "hr-expense-approval", "record_id": "c1"}


def test_insert_info_and_explicit_action_without_rule_downgrades():
    db = FakeDB()
    a = run(nu.notif_insert(db, type="rahaza", subtype="birthday", body="x", target_roles=["hr"]))
    b = run(nu.notif_insert(db, type="rahaza", subtype="adhoc", body="x", kind="action", target_roles=["hr"]))
    assert notif(db, a)["kind"] == "info" and "action" not in notif(db, a)
    assert notif(db, b)["kind"] == "info"


def test_low_stock_action_targets_wh_stock_even_for_legacy_link():
    """K37 — stok kritis membuka Stok Gudang (wh-stock), juga notifikasi lama `prod-materials`."""
    legacy = {"subtype": "low_stock", "source_id": "m1", "meta": {"link_module": "prod-materials"}}
    assert nu.action_of(legacy)["target_menu"] == "wh-stock"
    from routes import rahaza_alerts as ra
    assert "wh-stock" in open(ra.__file__, encoding="utf-8").read()


# ═══ K37 — TUJUAN PER PERAN ══════════════════════════════════════════════════
@pytest.mark.parametrize("portals,target,tab", [
    (["hr", "finance", "self"], "hr-expense-approval", None),   # HR (punya keduanya) → layar SDM
    (["finance", "assets", "self"], "fin-expenses", "settlement"),
    (["collaboration", "procurement", "self"], "hr-expense-approval", None),   # tanpa keduanya → bawaan
    (None, "hr-expense-approval", None),
])
def test_claim_link_per_recipient_portal(portals, target, tab):
    assert nu.link_for_portals("hr-approval-inbox", portals) == (target, tab)
    a = nu.action_of({"subtype": "expense_claim_submitted", "source_id": "c1",
                      "meta": {"link_module": "hr-approval-inbox"}}, portals)
    assert a["target_menu"] == target
    assert (a.get("filter") or {}).get("tab") == tab


def test_role_aliases_and_group_targets_exist_in_frontend():
    reg = frontend_registry_ids()
    for src, opts in nu.ROLE_LINK_ALIASES.items():
        assert src in reg
        for _portal, target, _tab in opts:
            assert target in reg, target
    for mid in ("proc-requests", "fin-ap-aging", "hr-inbox", "hr-kasbon", "fin-kasbon",
                "hr-payroll-run", "prod-cmt-billing", "wh-returns", "wh-stock"):
        assert mid in reg, mid


# ═══ K30 — PENUTUPAN OTOMATIS (resolver generik) ═════════════════════════════
def test_decision_notification_closes_action_immediately():
    """Cuti diputuskan → kabar ke pemohon (source_id sama) menutup action approver."""
    db = FakeDB()
    seed(db, "rahaza_leave_requests", {"id": "L1", "status": "pending_approval"})
    act = run(nu.notif_insert(db, type="rahaza", subtype="leave_request_submitted", body="x",
                              source_id="L1", target_roles=["hr"], meta={"link_module": "hr-leave"}))
    assert notif(db, act)["resolved_at"] is None
    db.rahaza_leave_requests.docs[0]["status"] = "approved"
    run(nu.notif_insert(db, type="rahaza", subtype="leave_approved", body="ok", source_id="L1",
                        target_user_ids=["emp"]))
    d = notif(db, act)
    assert d["resolved_at"] is not None and d["resolved_reason"] == "status:approved"
    assert nu.resolved_label(d["resolved_reason"]) == "Selesai — status sumber kini 'approved'"


def test_resolve_for_source_keeps_open_while_pending_and_supports_stage_two():
    db = FakeDB()
    seed(db, "rahaza_leave_requests", {"id": "L2", "status": "pending_approval"})
    a1 = run(nu.notif_insert(db, type="rahaza", subtype="leave_request_submitted", body="x",
                             source_id="L2", target_roles=["manager"]))
    assert run(nu.resolve_for_source(db, source_id="L2")) == 0
    # tahap 1 disetujui → status pending_hr_approval: notifikasi tahap 2 lahir, tahap 1 tertutup
    db.rahaza_leave_requests.docs[0]["status"] = "pending_hr_approval"
    a2 = run(nu.notif_insert(db, type="rahaza", subtype="leave_hr_approval_needed", body="x",
                             source_id="L2", target_roles=["hr"]))
    assert notif(db, a1)["resolved_reason"] == "status:pending_hr_approval"
    assert notif(db, a2)["resolved_at"] is None


@pytest.fixture
def pr_db():
    db = FakeDB()
    seed(db, "dewi_procurement_requests", {"id": "PR1", "status": "submitted"})
    seed(db, "acc_purchase_requests", {"id": "AC1", "status": "Submitted"})   # tahap kosong = dept
    seed(db, "rahaza_purchase_orders", {"id": "PO1", "status": "pending_approval",
                                        "current_approver_stage": "dept"})
    return db


def _pr_notif(db, sid, module, stage):
    return run(nu.notif_insert(db, type="rahaza", subtype="procurement_approval", body="x",
                               source_id=sid, target_user_ids=["acc"],
                               meta={"link_module": module, "stage": stage}))


def test_procurement_stage_rule_for_pr_acc_and_po(pr_db):
    db = pr_db
    pr = _pr_notif(db, "PR1", "proc-requests", "dept")
    ac = _pr_notif(db, "AC1", "proc-accessory-pr", "dept")
    po = _pr_notif(db, "PO1", "proc-purchase-orders", "dept")
    assert notif(db, ac)["source_collection"] == "acc_purchase_requests"
    assert run(nu.run_action_resolver(db))["resolved"] == 0
    db.dewi_procurement_requests.docs[0]["status"] = "dept_approved"       # lanjut ke tahap keuangan
    db.acc_purchase_requests.docs[0]["status"] = "Rejected"
    db.rahaza_purchase_orders.docs[0]["current_approver_stage"] = "finance"
    assert run(nu.run_action_resolver(db))["resolved"] == 3
    assert notif(db, pr)["resolved_reason"] == "stage:finance"
    assert notif(db, ac)["resolved_reason"] == "status:Rejected"
    assert notif(db, po)["resolved_reason"] == "stage:finance"


def test_new_stage_supersedes_previous_stage_notification(pr_db):
    db = pr_db
    first = _pr_notif(db, "PR1", "proc-requests", "dept")
    db.dewi_procurement_requests.docs[0]["status"] = "dept_approved"
    second = _pr_notif(db, "PR1", "proc-requests", "finance")
    assert notif(db, first)["resolved_at"] is not None
    assert notif(db, second)["resolved_at"] is None


def test_stock_low_closes_when_stock_back_to_normal(monkeypatch):
    from core import stock_thresholds
    state = {"m1": "critical", "m2": "low"}

    async def fake_eval(db, material_ids=None, with_suggestion=False, **kw):
        return [{"material_id": m, "status": state[m]} for m in (material_ids or []) if m in state]
    monkeypatch.setattr(stock_thresholds, "evaluate", fake_eval)
    db = FakeDB()
    n1 = run(nu.notif_insert(db, type="rahaza", subtype="low_stock", body="x", source_id="m1",
                             target_roles=["admin_gudang"], meta={"link_module": "wh-stock"}))
    n2 = run(nu.notif_insert(db, type="rahaza", subtype="low_stock", body="x", source_id="m2",
                             target_roles=["admin_gudang"], meta={"link_module": "wh-stock"}))
    state["m1"] = "ok"
    res = run(nu.run_action_resolver(db))
    assert res["resolved"] == 1
    assert notif(db, n1)["resolved_reason"] == "condition:ok"
    assert notif(db, n2)["resolved_at"] is None


def test_stock_evaluation_failure_keeps_action_open(monkeypatch):
    from core import stock_thresholds

    async def boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(stock_thresholds, "evaluate", boom)
    db = FakeDB()
    n1 = run(nu.notif_insert(db, type="rahaza", subtype="low_stock", body="x", source_id="m1",
                             target_roles=["admin_gudang"]))
    assert run(nu.run_action_resolver(db))["resolved"] == 0
    assert notif(db, n1)["resolved_at"] is None


def test_negative_stock_reminder_closes_when_no_negative_rows():
    db = FakeDB()
    seed(db, "rahaza_material_stock", {"id": "s1", "qty": -3})
    n = run(nu.notif_insert(db, type="rahaza", subtype="negative_stock_daily", body="x",
                            source_type="rahaza_material_stock", target_roles=["admin_gudang"]))
    assert notif(db, n)["kind"] == "action"
    assert run(nu.run_action_resolver(db))["resolved"] == 0
    db.rahaza_material_stock.docs[0]["qty"] = 0
    assert run(nu.run_action_resolver(db))["resolved"] == 1


def test_attendance_permit_in_embedded_sessions():
    db = FakeDB()
    seed(db, "rahaza_attendance_events", {"id": "ev1", "sessions": [
        {"id": "S1", "approval_status": "pending"}, {"id": "S2", "approval_status": "pending"}]})
    a = run(nu.notif_insert(db, type="rahaza", subtype="attendance_permit_request", body="x",
                            source_id="S1", target_roles=["hr"]))
    b = run(nu.notif_insert(db, type="rahaza", subtype="attendance_permit_request", body="x",
                            source_id="S2", target_roles=["hr"]))
    db.rahaza_attendance_events.docs[0]["sessions"][0]["approval_status"] = "approved"
    run(nu.run_action_resolver(db))
    assert notif(db, a)["resolved_reason"] == "status:approved"
    assert notif(db, b)["resolved_at"] is None


def test_source_document_deleted_closes_action():
    db = FakeDB()
    n = run(nu.notif_insert(db, type="rahaza", subtype="expense_claim_submitted", body="x",
                            source_id="gone", target_roles=["hr"]))
    run(nu.run_action_resolver(db))
    assert notif(db, n)["resolved_reason"] == "source_missing"


@pytest.mark.parametrize("emp,open_,reason", [
    ({"active": True, "contract_type": "PKWT", "contract_end_date": "2026-11-20"}, True, ""),
    ({"active": True, "contract_type": "PKWT", "contract_end_date": "2027-11-20"}, False, "condition:renewed"),
    ({"active": True, "contract_type": "PKWT", "contract_end_date": "2026-10-20"}, False, "condition:ended"),
    ({"active": False, "contract_type": "PKWT", "contract_end_date": "2026-11-20"}, False, "condition:inactive"),
    ({"active": True, "contract_type": "PKWTT", "contract_end_date": "2026-11-20"}, False, "condition:contract_type"),
])
def test_contract_expiry_resolution(emp, open_, reason):
    n = {"subtype": "contract_expiry", "source_id": "E1", "kind": "action"}
    st, why = nu.evaluate_open(n, docs={("rahaza_employees", "E1"): {"id": "E1", **emp}},
                               fetched={"rahaza_employees"}, today=date(2026, 11, 2))
    assert (st, why) == (open_, reason)


def test_contract_daily_copy_supersedes_yesterday():
    db = FakeDB()
    a = run(nu.notif_insert(db, type="rahaza", subtype="contract_expiry", body="x", source_id="E1",
                            target_roles=["hr"], meta={"dedup_key": "contract_expiry:E1:2026-11-01"}))
    b = run(nu.notif_insert(db, type="rahaza", subtype="contract_expiry", body="x", source_id="E1",
                            target_roles=["hr"], meta={"dedup_key": "contract_expiry:E1:2026-11-02"}))
    assert notif(db, a)["resolved_reason"] == "superseded" and notif(db, b)["resolved_at"] is None


def test_unfetched_collection_is_unknown_not_resolved():
    n = {"subtype": "expense_claim_submitted", "source_id": "c1", "kind": "action"}
    assert nu.evaluate_open(n, docs={}, fetched=set()) == (None, "")


def test_backfill_classifies_legacy_documents():
    db = FakeDB()
    seed(db, "notifications",
         {"id": "a", "subtype": "procurement_approval", "source_id": "PR1",
          "meta": {"link_module": "proc-accessory-pr", "stage": "dept"}},
         {"id": "b", "subtype": "low_stock", "source_id": "m1"},
         {"id": "c", "subtype": "low_stock"},
         {"id": "d", "subtype": "birthday"})
    out = run(nu.backfill_kinds(db))
    kinds = {d["id"]: (d["kind"], d.get("source_collection")) for d in db.notifications.docs}
    assert kinds == {"a": ("action", "acc_purchase_requests"), "b": ("action", "rahaza_materials"),
                     "c": ("info", None), "d": ("info", None)}
    assert out == {"action": 2, "info": 2}
    assert run(nu.backfill_kinds(db)) == {"action": 0, "info": 0}      # idempoten


def test_dedup_ignores_resolved_notifications():
    db = FakeDB()
    seed(db, "notifications", {"id": "x", "type": "rahaza", "meta": {"dedup_key": "k"},
                               "created_at": datetime.now(timezone.utc), "kind": "action",
                               "resolved_at": datetime.now(timezone.utc)})
    assert run(nu.rahaza_check_dedup(db, dedup_key="k", within_minutes=1440)) is None
    db.notifications.docs[0]["resolved_at"] = None
    assert run(nu.rahaza_check_dedup(db, dedup_key="k", within_minutes=1440)) is not None


def test_unread_count_excludes_resolved_actions():
    db = FakeDB()
    seed(db, "notifications",
         {"id": "o", "kind": "action", "resolved_at": None, "meta": {"target_roles": ["hr"]}},
         {"id": "r", "kind": "action", "resolved_at": NOW, "meta": {"target_roles": ["hr"]}},
         {"id": "i", "kind": "info", "meta": {"target_roles": ["hr"]}})
    assert run(nu.notif_count_unread_for(db, {"id": "u", "role": "hr"})) == 2


# ═══ SATU KOTAK MASUK — lencana tanpa hitung dobel ═══════════════════════════
@pytest.fixture
def inbox(monkeypatch):
    from routes import notification_categories as nc
    from core import pr_approval
    db = FakeDB()
    user = {"id": "hr1", "role": "hr"}

    async def fake_auth(req):
        return dict(user)

    async def fake_pending(db_, u):
        return []
    monkeypatch.setattr(nc, "require_auth", fake_auth)
    monkeypatch.setattr(nc, "get_db", lambda: db)
    monkeypatch.setattr(pr_approval, "pending_for_user", fake_pending)

    class Req:
        query_params = {"latest": "3"}
    return nc, db, user, Req()


def test_badge_counts_open_actions_plus_documents_without_double_counting(inbox):
    nc, db, user, req = inbox
    seed(db, "rahaza_leave_requests", {"id": "L1", "status": "pending_approval"},
         {"id": "L2", "status": "pending_hr_approval"})
    seed(db, "rahaza_overtime_requests", {"id": "OT1", "status": "pending"},
         {"id": "OT2", "status": "approved"})
    seed(db, "dewi_kasbon_requests", {"id": "K1", "status": "submitted"})
    # L1 sudah diwakili notifikasi action terbuka; L9 = action tanpa dokumen di badge
    seed(db, "notifications",
         {"id": "n1", "type": "rahaza", "subtype": "leave_request_submitted", "source_id": "L1",
          "kind": "action", "resolved_at": None, "source_collection": "rahaza_leave_requests",
          "meta": {"target_roles": ["hr"], "link_module": "hr-leave"}, "created_at": NOW},
         {"id": "n2", "type": "rahaza", "subtype": "birthday", "kind": "info",
          "meta": {"target_roles": ["hr"], "link_module": "hr-employees"}, "created_at": NOW},
         {"id": "n3", "type": "rahaza", "subtype": "leave_request_submitted", "source_id": "L0",
          "kind": "action", "resolved_at": NOW, "resolved_reason": "status:approved",
          "meta": {"target_roles": ["hr"], "link_module": "hr-leave"}, "created_at": NOW})
    s = run(nc.list_categories(req))
    # dokumen: L1, L2, OT1 (grup SDM) + K1 (kasbon) = 4; L1 sudah diwakili n1 ⇒ 3 + notifikasi n1
    assert s["action_from_documents"] == 3 and s["action_notifications"] == 1
    assert s["action_open"] == 4
    assert s["info_unread"] == 1 and s["history_total"] == 1
    assert s["total_unread"] == 2            # n1 + n2; n3 (riwayat) tidak dihitung


def test_inbox_tabs_action_info_history(inbox):
    nc, db, user, req = inbox
    seed(db, "rahaza_expense_claims", {"id": "C1", "status": "submitted"})
    seed(db, "notifications",
         {"id": "a", "type": "rahaza", "subtype": "expense_claim_submitted", "source_id": "C1",
          "kind": "action", "resolved_at": None, "source_collection": "rahaza_expense_claims",
          "title": "Klaim", "meta": {"target_roles": ["hr"], "link_module": "hr-approval-inbox"},
          "created_at": NOW},
         {"id": "h", "type": "rahaza", "subtype": "expense_claim_submitted", "source_id": "C0",
          "kind": "action", "resolved_at": NOW, "resolved_reason": "status:approved",
          "meta": {"target_roles": ["hr"]}, "created_at": NOW - timedelta(hours=1)},
         {"id": "i", "type": "rahaza", "subtype": "birthday", "kind": "info",
          "meta": {"target_roles": ["hr"], "link_module": "hr-employees"}, "created_at": NOW})
    act = run(nc.unified_inbox(req, tab="action", category=None, limit=30, skip=0))
    assert [i["id"] for i in act["items"]] == ["a"]
    it = act["items"][0]
    assert it["kind"] == "action" and it["action"]["label"] == "Putuskan klaim"
    assert it["action"]["record_id"] == "C1" and it["link_module"] == it["action"]["target_menu"]
    info = run(nc.unified_inbox(req, tab="info", category=None, limit=30, skip=0))
    assert [i["id"] for i in info["items"]] == ["i"]
    hist = run(nc.unified_inbox(req, tab="history", category=None, limit=30, skip=0))
    assert [i["id"] for i in hist["items"]] == ["h"]
    assert hist["items"][0]["resolved_label"].startswith("Selesai")
    with pytest.raises(HTTPException):
        run(nc.unified_inbox(req, tab="semua", category=None, limit=30, skip=0))


def test_inbox_action_tab_refreshes_stale_actions(inbox):
    """Membuka tab Perlu Tindakan memeriksa ulang action milik user: yang selesai langsung pindah."""
    nc, db, user, req = inbox
    seed(db, "rahaza_expense_claims", {"id": "C1", "status": "approved"})
    seed(db, "notifications",
         {"id": "a", "type": "rahaza", "subtype": "expense_claim_submitted", "source_id": "C1",
          "kind": "action", "resolved_at": None, "source_collection": "rahaza_expense_claims",
          "meta": {"target_roles": ["hr"]}, "created_at": NOW})
    act = run(nc.unified_inbox(req, tab="action", category=None, limit=30, skip=0))
    assert act["items"] == [] and act["counts"]["history"] == 1


def test_approval_groups_roles_and_requester_exclusion():
    from routes import approval_badge as ab
    db = FakeDB()
    seed(db, "wh_returns", {"id": "R1", "status": "Pending"}, {"id": "R2", "status": "Resolved"})
    seed(db, "rahaza_payroll_runs", {"id": "P1", "cancel_request": {"status": "pending", "requested_by": "fin1"}})
    seed(db, "dewi_cmt_payments", {"id": "T1", "status": "posted", "variance_flagged": True},
         {"id": "T2", "status": "posted", "variance_flagged": False})
    seed(db, "rahaza_expense_claims", {"id": "X1", "status": "approved"}, {"id": "X2", "status": "posted"})

    def keys(user):
        return {g["key"]: g["count"] for g in run(ab.approval_groups(db, user))}
    assert keys({"id": "g1", "role": "admin_gudang"}).get("wh_return") == 1
    assert "wh_return" not in keys({"id": "t1", "role": "tim_packing"})
    fin = keys({"id": "fin2", "role": "accounting"})
    assert fin["payroll_cancel"] == 1 and fin["cmt_variance"] == 1 and fin["expense_disburse"] == 1
    assert "payroll_cancel" not in keys({"id": "fin1", "role": "accounting"})   # pengaju sendiri
    exp = next(g for g in run(ab.approval_groups(db, {"id": "fin2", "role": "accounting"}))
               if g["key"] == "expense_disburse")
    assert exp["module_id"] == "fin-expenses" and exp["tab"] == "settlement"   # K37
    assert "expense_disburse" not in keys({"id": "h", "role": "hr"})


def test_legacy_badge_endpoint_still_answers(monkeypatch):
    from routes import approval_badge as ab
    db = FakeDB()
    seed(db, "rahaza_ap_invoices", {"id": "AP1", "status": "sent"})

    async def fake_auth(req):
        return {"id": "a", "role": "accounting"}
    monkeypatch.setattr(ab, "require_auth", fake_auth)
    monkeypatch.setattr(ab, "get_db", lambda: db)
    out = run(ab.get_approval_badge(object()))
    assert out["ap_pending"] == 1 and out["total"] >= 1


# ═══ K31 — RETENSI ═══════════════════════════════════════════════════════════
def _ret_db():
    db = FakeDB()
    old = NOW - timedelta(days=120)
    seed(db, "users", {"id": "u1", "role": "hr", "status": "active"},
         {"id": "u2", "role": "hr", "status": "active"},
         {"id": "gone", "role": "hr", "status": "inactive"})
    seed(db, "notifications",
         # info personal: dibaca / belum
         {"id": "p_read", "type": "rahaza", "channel": "in_app", "kind": "info", "user_id": "u1",
          "read": True, "created_at": old},
         {"id": "p_unread", "type": "rahaza", "channel": "in_app", "kind": "info", "user_id": "u1",
          "read": False, "created_at": old},
         # info bersama: dibaca semua penerima aktif / sebagian
         {"id": "s_all", "type": "rahaza", "channel": "in_app", "kind": "info", "created_at": old,
          "meta": {"target_roles": ["hr"], "read_by": ["u1", "u2"]}},
         {"id": "s_part", "type": "rahaza", "channel": "in_app", "kind": "info", "created_at": old,
          "meta": {"target_roles": ["hr"], "read_by": ["u1"]}},
         # info baru (belum lewat retensi)
         {"id": "fresh", "type": "rahaza", "channel": "in_app", "kind": "info", "user_id": "u1",
          "read": True, "created_at": NOW - timedelta(days=5)},
         # action: tertutup lama / tertutup baru / TERBUKA sangat lama
         {"id": "a_res", "type": "rahaza", "channel": "in_app", "kind": "action", "created_at": old,
          "resolved_at": old + timedelta(days=1)},
         {"id": "a_res_new", "type": "rahaza", "channel": "in_app", "kind": "action", "created_at": old,
          "resolved_at": NOW - timedelta(days=3)},
         {"id": "a_open", "type": "rahaza", "channel": "in_app", "kind": "action", "created_at": old - timedelta(days=900),
          "resolved_at": None, "user_id": "u1", "read": True},
         # outbox WA klien maklon — bukan notifikasi in-app, tidak disentuh
         {"id": "wa", "type": "dewi", "channel": "whatsapp", "kind": "info", "created_at": old})
    return db


def test_retention_dry_run_counts_without_deleting():
    db = _ret_db()
    out = run(nu.purge_notifications(db, days=90, dry_run=True, now=NOW))
    assert out["action_resolved"] == 1 and out["info_read"] == 2 and out["deleted"] == 0
    assert len(db.notifications.docs) == 9


def test_retention_deletes_read_info_and_closed_actions_never_open_actions():
    db = _ret_db()
    out = run(nu.purge_notifications(db, days=90, dry_run=False, now=NOW))
    left = {d["id"] for d in db.notifications.docs}
    assert out["deleted"] == 3
    assert left == {"p_unread", "s_part", "fresh", "a_res_new", "a_open", "wa"}


def test_retention_days_from_existing_config_default_90():
    db = FakeDB()
    assert run(nu.retention_days(db)) == 90
    seed(db, "notif_category_config", {"id": "default", "matrix": {}, "retention_days": 30})
    assert run(nu.retention_days(db)) == 30
    assert nu.clamp_retention_days(1) == 7 and nu.clamp_retention_days("x") == 90


def test_category_config_saves_and_validates_retention(monkeypatch):
    from routes import notification_categories as nc
    from _fake_mongo import FakeRequest
    db = FakeDB()
    monkeypatch.setattr(nc, "get_db", lambda: db)

    async def admin(req):
        return {"id": "sa", "role": "superadmin", "name": "SA"}
    monkeypatch.setattr(nc, "require_auth", admin)
    got = run(nc.read_config(FakeRequest()))
    assert got["retention_days"] == 90
    out = run(nc.save_config(FakeRequest({"retention_days": 45})))     # retensi saja, matriks dipertahankan
    assert out["retention_days"] == 45 and out["matrix"]
    assert run(nc.read_config(FakeRequest()))["retention_days"] == 45
    with pytest.raises(HTTPException) as e:
        run(nc.save_config(FakeRequest({"retention_days": 2})))
    assert e.value.status_code == 400

    async def staff(req):
        return {"id": "t", "role": "tim_packing"}
    monkeypatch.setattr(nc, "require_auth", staff)
    with pytest.raises(HTTPException) as e:
        run(nc.save_config(FakeRequest({"retention_days": 45})))
    assert e.value.status_code == 403


def test_dedupe_legacy_copies_dry_run_then_apply():
    db = FakeDB()
    base = {"type": "rahaza", "user_id": None}
    seed(db, "notifications",
         {**base, "id": "c1", "subtype": "contract_expiry", "created_at": NOW - timedelta(minutes=20),
          "meta": {"dedup_key": "contract_expiry:E1:29", "read_by": ["u1"]}},
         {**base, "id": "c2", "subtype": "contract_expiry", "created_at": NOW - timedelta(minutes=10),
          "meta": {"dedup_key": "contract_expiry:E1:29", "read_by": ["u2"]}},
         {**base, "id": "c3", "subtype": "contract_expiry", "created_at": NOW,
          "meta": {"dedup_key": "contract_expiry:E1:29", "read_by": []}},
         {**base, "id": "s1", "subtype": "sla_breach", "created_at": NOW, "meta": {"dedup_key": "sla_breach_2026-11-01"}},
         {**base, "id": "s2", "subtype": "sla_breach", "created_at": NOW - timedelta(minutes=30),
          "meta": {"dedup_key": "sla_breach_2026-11-01"}},
         {**base, "id": "x1", "subtype": "expiring_discount", "created_at": NOW, "meta": {"dedup_key": "d"}},
         {**base, "id": "x2", "subtype": "expiring_discount", "created_at": NOW, "meta": {"dedup_key": "d"}})
    dry = run(nu.dedupe_legacy_copies(db, dry_run=True))
    assert dry["duplicates"] == 3 and dry["per_subtype"] == {"contract_expiry": 2, "sla_breach": 1}
    assert len(db.notifications.docs) == 7
    done = run(nu.dedupe_legacy_copies(db, dry_run=False))
    left = {d["id"]: d for d in db.notifications.docs}
    assert done["deleted"] == 3 and set(left) == {"c3", "s1", "x1", "x2"}
    assert sorted(left["c3"]["meta"]["read_by"]) == ["u1", "u2"]      # status baca dipertahankan


# ═══ K32 — HR TETAP BOLEH MEMBACA SEMUA INBOX ════════════════════════════════
def test_hr_may_still_read_all_inboxes(monkeypatch):
    from routes import notifications_unified as nun
    assert {"hr", "hr_manager", "manager_hr"} <= nun.ADMIN_VIEW_ROLES
    db = FakeDB()
    seed(db, "notifications", {"id": "n", "type": "rahaza", "user_id": "acc1", "kind": "info",
                               "created_at": NOW, "meta": {}})
    monkeypatch.setattr(nun, "get_db", lambda: db)

    async def as_role(role):
        async def _a(req):
            return {"id": "x", "role": role}
        monkeypatch.setattr(nun, "require_auth", _a)
    run(as_role("hr"))
    out = run(nun.list_unified(object(), type=None, severity=None, unread_only=False,
                               user_id="acc1", all_users=False, limit=50, skip=0))
    assert [i["id"] for i in out["items"]] == ["n"] and out["items"][0]["kind"] == "info"
    run(as_role("tim_packing"))
    with pytest.raises(HTTPException) as e:
        run(nun.list_unified(object(), type=None, severity=None, unread_only=False,
                             user_id="acc1", all_users=False, limit=50, skip=0))
    assert e.value.status_code == 403


def test_maintenance_endpoints_are_admin_only(monkeypatch):
    from routes import notifications_unified as nun

    async def staff(req):
        return {"id": "h", "role": "hr"}
    monkeypatch.setattr(nun, "require_auth", staff)
    for fn in (nun.maintenance_resolve(object()), nun.maintenance_purge(object(), dry_run=True, days=None),
               nun.maintenance_dedupe(object(), dry_run=True, subtypes=None)):
        with pytest.raises(HTTPException) as e:
            run(fn)
        assert e.value.status_code == 403


def test_scheduled_jobs_registered_as_new_entries():
    try:
        from utils.scheduler import JOB_REGISTRY
    except Exception:  # noqa: BLE001
        pytest.skip("apscheduler tidak tersedia")
    from routes import notifications_unified as nun
    assert nun.register_scheduler_jobs()
    assert JOB_REGISTRY["notif_resolve_actions"]["cron"] == {"minute": "*/5"}
    assert JOB_REGISTRY["notif_retention"]["cron"] == {"hour": 2, "minute": 30}


# ═══ FRONTEND — satu ikon, tab, retensi ══════════════════════════════════════
def _fe(path):
    p = os.path.join(FRONTEND, *path.split("/"))
    if not os.path.exists(p):
        pytest.skip("frontend/src tidak tersedia di lingkungan uji ini")
    return open(p, encoding="utf-8").read()


def test_topbar_has_single_inbox_icon():
    src = _fe("components/erp/portal-shell/TopBar.jsx")
    assert "ApprovalBadge" not in src.replace("(ApprovalBadge)", "")
    assert "<NotificationBell" in src
    assert not os.path.exists(os.path.join(FRONTEND, "components", "erp", "ApprovalBadge.jsx"))


def test_bell_uses_unified_inbox_tabs_and_badge():
    src = _fe("components/erp/NotificationBell.jsx")
    for needle in ("/api/notifications/inbox", "Perlu Tindakan", "Pemberitahuan", "action_open",
                   "info_unread", "inbox-tab-action", "inbox-action-btn"):
        assert needle in src, needle
    portal = _fe("components/erp/PortalSayaNotifikasi.jsx")
    assert "/api/notifications/inbox" in portal and "InboxRow" in portal


def test_settings_screen_has_retention_field():
    src = _fe("components/erp/NotificationSettingsModule.jsx")
    assert "retention_days" in src and "notif-retention-days" in src
