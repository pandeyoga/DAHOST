"""Uji unit HERMETIK paket P7 — NOTIFIKASI (2026-11-02). Tanpa server, tanpa Mongo.

Regresi dari audit notifikasi 2026-11-02:
  · dedup alert terjadwal (kontrak tiap 10 mnt, marketing 48×/hari);
  · penerima peran fiktif (warehouse_manager, manager_production, production_manager);
  · penerima notifikasi PR = mesin persetujuan (pemohon & penyetuju tahap lalu tidak);
  · id modul mati (prod-materials, hr-approval-inbox, …) → id hidup di frontend;
  · waktu tanpa zona → ISO ber-'Z';
  · angka bel terpotong 200 → jumlah sebenarnya + paginasi;
  · POST /api/collab/notifications & pratinjau kontrak;
  · kabar keputusan cuti/lembur ke pemohon; notifikasi backup (ImportError).

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import ast
import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from utils import notif_unified as nu  # noqa: E402
from routes.shared import PORTAL_ACCESS  # noqa: E402


# ─── Mongo palsu minimal (cukup untuk operator yang dipakai modul notifikasi) ───
def _get(doc, path):
    cur = [doc]
    for part in path.split("."):
        nxt = []
        for c in cur:
            if isinstance(c, dict) and part in c:
                v = c[part]
                nxt.extend(v if isinstance(v, list) and part != path.split(".")[-1] else [v])
        cur = nxt
    return cur


def _match_val(vals, cond):
    flat = []
    for v in vals:
        flat.extend(v if isinstance(v, list) else [v])
    if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$ne":
                if arg in flat or (arg is None and not vals):
                    return False
            elif op == "$in":
                present = flat or [None]
                if not any((a in present) or (a == [] and any(v == [] for v in vals)) for a in arg):
                    return False
            elif op == "$nin":
                if any(a in flat for a in arg):
                    return False
            elif op == "$gte":
                if not any(v is not None and v >= arg for v in flat):
                    return False
            elif op == "$exists":
                if bool(vals) != bool(arg):
                    return False
            else:
                raise NotImplementedError(op)
        return True
    if cond is None:
        return not flat or None in flat
    return cond in flat or cond in vals


def match(doc, flt):
    for k, cond in (flt or {}).items():
        if k == "$or":
            if not any(match(doc, sub) for sub in cond):
                return False
        elif not _match_val(_get(doc, k), cond):
            return False
    return True


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, key, direction=1):
        self.rows.sort(key=lambda r: r.get(key) or datetime.min.replace(tzinfo=timezone.utc),
                       reverse=direction == -1)
        return self

    def skip(self, n):
        self.rows = self.rows[n:]
        return self

    def limit(self, n):
        self.rows = self.rows[:n] if n else self.rows
        return self

    async def to_list(self, n=None):
        return list(self.rows if n is None else self.rows[:n])

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeColl:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, flt=None, proj=None):
        return FakeCursor([dict(r) for r in self.rows if match(r, flt)])

    async def find_one(self, flt=None, proj=None, **kw):
        for r in self.rows:
            if match(r, flt):
                return dict(r)
        return None

    async def insert_one(self, doc):
        self.rows.append(dict(doc))

    async def count_documents(self, flt):
        return sum(1 for r in self.rows if match(r, flt))


class FakeDB:
    def __init__(self, **colls):
        self._c = {k: FakeColl(v) for k, v in colls.items()}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, FakeColl())

    def __getitem__(self, name):
        return getattr(self, name)


def run(coro):
    return asyncio.run(coro)


def frontend_registry_ids():
    path = os.path.join(BACKEND, "..", "frontend", "src", "components", "erp", "moduleRegistry.js")
    if not os.path.exists(path):
        pytest.skip("frontend/src tidak tersedia di lingkungan uji ini")
    src = open(path, encoding="utf-8").read()
    return {m.group(1) for m in re.finditer(r"^\s*['\"]([\w\-:]+)['\"]\s*:", src, re.M)}


# ═══ 6. WAKTU BER-ZONA ═══════════════════════════════════════════════════════
def test_iso_utc_naive_is_treated_as_utc_and_has_z():
    naive = datetime(2026, 11, 1, 21, 33, 43, 861000)
    assert nu.iso_utc(naive) == "2026-11-01T21:33:43.861Z"
    wib = datetime(2026, 11, 2, 4, 33, 43, tzinfo=timezone(timedelta(hours=7)))
    assert nu.iso_utc(wib) == "2026-11-01T21:33:43.000Z"
    assert nu.iso_utc("x") == "x" and nu.iso_utc(None) is None


def test_serializers_never_emit_naive_timestamps():
    doc = {"id": "n1", "created_at": datetime(2026, 11, 1, 21, 0), "meta": {}}
    assert nu.serialize_notif(doc)["created_at"].endswith("Z")
    assert nu.reshape_as_rahaza(doc)["created_at"].endswith("Z")
    assert nu.reshape_as_collab(doc)["created_at"].endswith("Z")
    assert nu.notif_times_iso(doc)["created_at"].endswith("Z")


# ═══ 4. TAUTAN MATI ══════════════════════════════════════════════════════════
def test_link_aliases_point_to_live_frontend_modules():
    reg = frontend_registry_ids()
    for dead, live in nu.LINK_MODULE_ALIASES.items():
        assert dead not in reg, f"{dead} ternyata hidup — alias tidak perlu"
        assert live in reg, f"tujuan alias {dead}→{live} tidak ada di moduleRegistry.js"


def test_every_backend_link_module_literal_resolves_to_live_module():
    """Kontrak BE↔FE: setiap `link_module` literal yang ditulis backend harus
    mendarat di id MODULE_REGISTRY (langsung atau lewat alias)."""
    reg = frontend_registry_ids()
    pat = re.compile(r"""link_module["']?\s*[:=]\s*f?["']([^"'{}]+)["']""")
    bad = []
    for dirpath, _dirs, files in os.walk(BACKEND):
        if "/tests" in dirpath.replace("\\", "/") or "migrations" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            for i, line in enumerate(open(os.path.join(dirpath, fn), encoding="utf-8", errors="ignore"), 1):
                for m in pat.finditer(line):
                    if nu.normalize_link_module(m.group(1)) not in reg:
                        bad.append(f"{fn}:{i} {m.group(1)}")
    assert not bad, bad


def test_notif_insert_normalizes_dead_link_module():
    db = FakeDB()
    run(nu.notif_insert(db, type="rahaza", body="x", meta={"link_module": "prod-materials"}))
    assert db.notifications.rows[0]["meta"]["link_module"] == "wh-stock"


# ═══ 2. PERAN NYATA ══════════════════════════════════════════════════════════
@pytest.mark.parametrize("portal", ["warehouse", "production", "hr"])
def test_alert_roles_are_real_portal_roles(portal):
    roles = nu.alert_roles_for_portal(portal)
    assert roles, portal
    assert set(roles) <= set(PORTAL_ACCESS[portal])
    assert not set(roles) & nu.PHANTOM_ROLES


def test_real_target_roles_replaces_phantoms_and_keeps_superadmin():
    out = nu.real_target_roles(["warehouse_manager", "manager_production", "superadmin"], "warehouse")
    assert "admin_gudang" in out and "superadmin" in out
    assert not set(out) & nu.PHANTOM_ROLES
    # nilai lama di DB (rahaza_alert_settings) ikut dibersihkan
    prod = nu.real_target_roles(["superadmin", "manager_production", "supervisor"], "production")
    assert {"supervisor_produksi", "admin_produksi", "supervisor", "superadmin"} <= set(prod)
    assert "manager_production" not in prod


@pytest.mark.parametrize("roles,must", [
    # rahaza_inventory_shared (stok rendah mutasi) & wms_receiving (rak kritis)
    (["warehouse_manager", "production_manager", "superadmin"], {"admin_gudang", "supervisor_produksi"}),
    # rahaza_shipments
    (["superadmin", "finance", "production_manager"], {"accounting", "staff_keuangan", "admin_produksi"}),
])
def test_notif_insert_replaces_phantom_roles_from_any_writer(roles, must):
    db = FakeDB()
    run(nu.notif_insert(db, type="rahaza", body="x", target_roles=roles))
    got = set(db.notifications.rows[0]["meta"]["target_roles"])
    assert must <= got and "superadmin" in got
    assert not got & nu.PHANTOM_ROLES


def test_low_stock_alert_targets_warehouse_and_live_link(monkeypatch):
    from routes import rahaza_alerts as ra
    from core import stock_thresholds

    async def fake_eval(db, with_suggestion=False):
        return [{"status": "critical", "alert_at": 5.0, "onhand": 0.0, "unit": "m",
                 "code": "A-1", "material_id": "m1"}]
    monkeypatch.setattr(stock_thresholds, "evaluate", fake_eval)
    [a] = run(ra.check_low_stock(FakeDB(), dict(ra.DEFAULT_SETTINGS)))
    assert a["link_module"] == "wh-stock"
    assert "admin_gudang" in a["target_roles"] and not set(a["target_roles"]) & nu.PHANTOM_ROLES
    assert a["dedup_minutes"] == 1440


# ═══ 1. DEDUP ════════════════════════════════════════════════════════════════
def test_contract_expiry_once_per_day_per_employee_and_hr_only():
    from routes import rahaza_alerts as ra
    from utils.waktu import today_wib
    end = (today_wib() + timedelta(days=10)).isoformat()
    db = FakeDB(rahaza_employees=[{"id": "e1", "employee_code": "K1", "name": "Ani", "active": True,
                                   "contract_type": "PKWT", "contract_end_date": end}])
    [a] = run(ra.check_expiring_contracts(db))
    assert a["dedup_key"] == f"contract_expiry:e1:{today_wib().isoformat()}"
    assert a["dedup_minutes"] == 1440
    assert "manager" not in a["target_roles"] and "hr" in a["target_roles"]


def test_rule_engine_default_dedup_is_one_day(monkeypatch):
    from routes import rahaza_alerts as ra
    seen = []

    async def fake_pub(db, **kw):
        seen.append(kw)
        return {"id": "x"}

    async def one_rule(db, settings):
        return [{"type": "t", "severity": "info", "title": "t", "message": "m", "dedup_key": "k"}]
    monkeypatch.setattr(ra, "publish_notification", fake_pub)
    for name in ("check_behind_target", "check_qc_spike", "check_low_stock", "check_expiring_contracts"):
        monkeypatch.setattr(ra, name, one_rule)
    run(ra.evaluate_all_rules(FakeDB(), settings=dict(ra.DEFAULT_SETTINGS), publish=True))
    assert seen and all(k["dedup_minutes"] == 1440 for k in seen)


def _publish_calls(path):
    tree = ast.parse(open(os.path.join(BACKEND, path), encoding="utf-8").read())
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", "")) == "publish_notification"]


def test_marketing_alerts_dedup_one_day_for_every_publish():
    calls = _publish_calls("routes/marketing_alerts.py")
    assert len(calls) >= 5
    for c in calls:
        kws = {k.arg: k.value for k in c.keywords}
        assert "dedup_minutes" in kws, f"baris {c.lineno} tanpa dedup_minutes"
    from routes import marketing_alerts as ma
    assert ma.DEDUP_MINUTES == 1440


def test_marketing_alert_day_is_wib():
    from routes import marketing_alerts as ma
    from utils.waktu import today_wib
    assert ma._today() == today_wib()


def test_rahaza_check_dedup_respects_window():
    old = {"id": "a", "type": "rahaza", "meta": {"dedup_key": "k"},
           "created_at": datetime.now(timezone.utc) - timedelta(hours=5)}
    db = FakeDB(notifications=[old])
    assert run(nu.rahaza_check_dedup(db, dedup_key="k", within_minutes=10)) is None
    assert run(nu.rahaza_check_dedup(db, dedup_key="k", within_minutes=1440)) is not None


# ═══ 3. PENERIMA NOTIFIKASI PR = MESIN PERSETUJUAN ═══════════════════════════
def _pr_users():
    return [
        {"id": "req", "role": "admin_gudang", "status": "active"},
        {"id": "gud2", "role": "admin_gudang", "status": "active"},
        {"id": "acc", "role": "accounting", "status": "active"},
        {"id": "fin", "role": "staff_keuangan", "status": "active"},
        {"id": "sa", "role": "superadmin", "status": "active"},
        {"id": "vend", "role": "cmt_vendor", "status": "active"},
        {"id": "gone", "role": "accounting", "status": "inactive"},
    ]


# Izin dinamis seperti seed go-live: admin gudang TIDAK memegang izin approve PR,
# accounting memegang izin approve dept + keuangan.
_PERMS = {
    "admin_gudang": (["wh.view"], []),
    "accounting": (["proc.pr.approve", "finance.approve"], []),
    "staff_keuangan": (["finance.approve"], []),
    "superadmin": (["*"], []),
    "cmt_vendor": (["cmt.my_jobs.view"], []),
}


@pytest.fixture
def pr_engine(monkeypatch):
    from core import pr_approval as pa

    async def fake_perms(role, uid):
        return _PERMS.get(role, ([], []))
    monkeypatch.setattr(pa, "_load_perms", fake_perms)
    return pa


def test_pr_dept_recipients_are_inbox_approvers_not_requester(pr_engine):
    pa = pr_engine
    db = FakeDB(users=_pr_users())
    doc = {"id": "pr1", "requested_by": "req", "status": "submitted", "approval_steps": []}
    ids, override = run(pa.stage_approver_ids(db, doc, pa.STAGE_DEPT, [pa.STAGE_DEPT]))
    assert ids == ["acc"] and override is False   # bukan pemohon, bukan admin gudang tanpa izin
    for uid in ("req", "gud2", "vend", "gone", "sa"):
        assert uid not in ids


def test_pr_next_stage_skips_previous_approver(pr_engine):
    pa = pr_engine
    db = FakeDB(users=_pr_users())
    doc = {"id": "pr2", "requested_by": "req", "status": "dept_approved",
           "approval_steps": [{"action": "approved", "stage": "dept", "actor_id": "acc"}]}
    ids, override = run(pa.stage_approver_ids(db, doc, pa.STAGE_FINANCE,
                                              [pa.STAGE_DEPT, pa.STAGE_FINANCE]))
    assert ids == ["fin"] and override is False


def test_pr_final_stage_without_director_reaches_override_admin(pr_engine):
    pa = pr_engine
    db = FakeDB(users=_pr_users())
    chain = [pa.STAGE_DEPT, pa.STAGE_FINANCE, pa.STAGE_FINAL]
    doc = {"id": "pr3", "requested_by": "req", "status": "finance_approved",
           "approval_steps": [{"action": "approved", "stage": "dept", "actor_id": "acc"},
                              {"action": "approved", "stage": "finance", "actor_id": "fin"}]}
    ids, override = run(pa.stage_approver_ids(db, doc, pa.STAGE_FINAL, chain))
    assert ids == ["sa"] and override is True


def test_pr_notification_rereads_doc_and_targets_users(pr_engine):
    pa = pr_engine
    fresh = {"id": "pr4", "requested_by": "req", "status": "dept_approved",
             "total_estimated": 30_000_000,
             "approval_steps": [{"action": "approved", "stage": "dept", "actor_id": "acc"}]}
    db = FakeDB(users=_pr_users(), dewi_procurement_requests=[fresh])
    stale = {**fresh, "approval_steps": []}       # salinan lama dari pemanggil
    chain = [pa.STAGE_DEPT, pa.STAGE_FINANCE, pa.STAGE_FINAL]
    run(pa.notify_stage_approvers(db, stale, pa.STAGE_FINANCE, chain, module_id="proc-requests",
                                  number="PR-1", title="Mesin"))
    [n] = db.notifications.rows
    assert n["meta"]["target_user_ids"] == ["fin"]          # `acc` sudah menyetujui tahap dept
    assert "Rp 30.000.000" in n["body"] and n["meta"]["link_module"] == "proc-requests"


# ═══ 7. ANGKA BELUM DIBACA & PAGINASI ════════════════════════════════════════
def _many(n, role="superadmin"):
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return [{"id": f"n{i:04d}", "type": "rahaza", "subtype": "low_stock", "title": f"t{i}",
             "body": "b", "created_at": base + timedelta(minutes=i),
             "meta": {"target_roles": [role], "link_module": "prod-materials", "read_by": []}}
            for i in range(n)]


def test_unread_count_is_not_capped():
    db = FakeDB(notifications=_many(2500))
    assert run(nu.notif_count_unread_for(db, {"id": "u", "role": "superadmin"})) == 2500


def test_bell_counts_all_and_paginates(monkeypatch):
    from routes import notification_categories as nc
    db = FakeDB(notifications=_many(450), notif_category_config=[], notif_user_prefs=[])
    user = {"id": "u", "role": "superadmin"}

    async def fake_auth(req):
        return dict(user)
    monkeypatch.setattr(nc, "require_auth", fake_auth)
    monkeypatch.setattr(nc, "get_db", lambda: db)

    class Req:
        query_params = {"latest": "5"}
    summ = run(nc.list_categories(Req()))
    assert summ["total_unread"] == 450 and summ["total"] == 450
    assert len(summ["latest"]) == 5 and summ["latest"][0]["id"] == "n0449"
    p1 = run(nc.list_categorized(Req(), category=None, unread_only=False, limit=200, skip=0))
    p3 = run(nc.list_categorized(Req(), category=None, unread_only=False, limit=200, skip=400))
    assert p1["total"] == 450 and p1["has_more"] is True and len(p1["items"]) == 200
    assert len(p3["items"]) == 50 and p3["has_more"] is False
    it = p1["items"][0]
    assert it["link_module"] == "wh-stock" and it["created_at"].endswith("Z")


# ═══ 10. KEAMANAN ════════════════════════════════════════════════════════════
def _req(**kw):
    from routes.notifications import CreateNotifRequest
    return CreateNotifRequest(**{"title": "t", "content": "c", **kw})


@pytest.mark.parametrize("role", ["cmt_vendor", "vendor", "buyer", "klien_maklon", ""])
def test_manual_notification_rejects_external_roles(role):
    from routes.notifications import validate_manual_notification
    with pytest.raises(HTTPException) as e:
        validate_manual_notification({"role": role}, _req(), True)
    assert e.value.status_code == 403


@pytest.mark.parametrize("url", ["https://contoh-luar.invalid/login", "javascript:alert(1)",
                                 "//evil.example", "#//evil.example", "/api/x"])
def test_manual_notification_rejects_external_links(url):
    from routes.notifications import validate_manual_notification
    with pytest.raises(HTTPException) as e:
        validate_manual_notification({"role": "tim_packing"}, _req(source_url=url), True)
    assert e.value.status_code == 400


def test_manual_notification_requires_existing_target_and_allows_internal_hash():
    from routes.notifications import validate_manual_notification
    with pytest.raises(HTTPException) as e:
        validate_manual_notification({"role": "hr"}, _req(), False)
    assert e.value.status_code == 404
    assert validate_manual_notification({"role": "hr"}, _req(source_url="#hr-employees"), True) == "#hr-employees"
    assert validate_manual_notification({"role": "hr"}, _req(source_url="#/comm/channel/abc"), True)


def test_alert_preview_hides_contract_details_from_non_hr():
    from routes.rahaza_alerts import redact_preview
    res = {"counts": {"low_stock": 1, "contract_expiry": 1},
           "preview": [{"type": "low_stock"}, {"type": "contract_expiry", "message": "PKWT Ani"}]}
    out = redact_preview(res, {"role": "tim_packing"})
    assert [p["type"] for p in out["preview"]] == ["low_stock"] and "contract_expiry" not in out["counts"]
    assert redact_preview(res, {"role": "hr"}) is res


# ═══ 11/12. KABAR KE PEMOHON & NOTIFIKASI BACKUP ═════════════════════════════
def test_backup_send_notification_exists_and_is_personal():
    from routes import rahaza_notifications as rn
    db = FakeDB()
    nid = run(rn.send_notification(user_id="sa", title="✅ Backup Berhasil", message="ok",
                                   type="success", category="system", db=db))
    [n] = db.notifications.rows
    assert n["id"] == nid and n["user_id"] == "sa" and n["severity"] == "success"
    assert n["meta"]["link_module"] == "mgmt-backup-restore"


def _capture_publish(monkeypatch):
    from routes import rahaza_notifications as rn
    seen = []

    async def fake_pub(db, **kw):
        seen.append(kw)
        return {"id": "x"}
    monkeypatch.setattr(rn, "publish_notification", fake_pub)
    return seen


def test_leave_rejection_notifies_requester(monkeypatch):
    from routes import rahaza_leave as rl
    seen = _capture_publish(monkeypatch)
    db = FakeDB(users=[{"id": "u-emp", "employee_id": "e1", "status": "active"}],
                rahaza_leave_types=[{"id": "lt", "name": "Cuti Tahunan"}])
    leave = {"id": "lv1", "employee_id": "e1", "leave_type_id": "lt", "from_date": "2026-12-01",
             "to_date": "2026-12-01", "duration_days": 1, "submitted_by": "u-emp"}
    run(rl.notify_leave_decision(db, leave, approved=False, reason="kuota penuh"))
    [kw] = seen
    assert kw["type_"] == "leave_rejected" and kw["target_user_ids"] == ["u-emp"]
    assert kw["link_module"] == "portal-cuti" and "kuota penuh" in kw["message"]


def test_overtime_decision_notifies_requester(monkeypatch):
    from routes import rahaza_overtime as ro
    seen = _capture_publish(monkeypatch)
    db = FakeDB(users=[])   # karyawan belum tertaut akun → jatuh ke pengaju
    ot = {"id": "ot1", "employee_id": "e9", "date": "2026-12-10", "start_time": "17:00",
          "end_time": "19:00", "hours": 2, "submitted_by": "u-sub"}
    run(ro.notify_overtime_decision(db, ot, approved=True))
    run(ro.notify_overtime_decision(db, ot, approved=False, reason="tidak perlu"))
    assert [k["type_"] for k in seen] == ["overtime_approved", "overtime_rejected"]
    assert all(k["target_user_ids"] == ["u-sub"] and k["link_module"] == "portal-cuti" for k in seen)
