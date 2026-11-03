"""Uji regresi HERMETIK route AI & Portal Manajemen (P6, 2026-11-02).

Mongo PALSU + auth palsu; tidak ada panggilan LLM. Mencakup: fraud "tidak dapat
dinilai", churn tanpa pelanggan fiktif, Apply harga, IDOR riwayat chat, absen selfie
→ review HR, layar Integrasi, Monitor AI jujur, konteks AI (karyawan aktif, stok,
AP jatuh tempo, faktur draft/batal, maklon ganda, live = estimasi), image generator
dihapus, dan bug render Dashboard Eksekutif.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ai_fakes import BACKEND, FakeDB, FakeRequest, run  # noqa: E402

REPO = os.path.dirname(BACKEND)
ADMIN = {"id": "u-admin", "name": "Admin Uji", "email": "a@x", "role": "superadmin"}
CS = {"id": "u-cs", "name": "CS Uji", "email": "cs@x", "role": "cs_staff", "_role_perms": []}
MKT = {"id": "u-mkt", "name": "Manajer Marketing", "email": "m@x", "role": "manager_marketing", "_role_perms": []}


def _auth(user):
    async def _f(_request=None, *a, **k):
        return user
    return _f


# ── Fraud: gagal/terpotong TIDAK boleh jadi "low" ───────────────────────────
def test_fraud_result_tidak_dapat_dinilai():
    from routes import dewi_ai_business as b
    sig = {"top_invoice_outliers": [{"id": "x"}]}
    for parsed in (None, {}, {"risk_level": ""}, {"risk_level": "aman banget"}):
        r = b._fraud_result(parsed, sig)
        assert r["risk_level"] == b.RISK_NOT_ASSESSED != "low"
        assert "tidak dapat dinilai" in r["overall_assessment"].lower()
    ok = b._fraud_result({"risk_level": "HIGH", "overall_assessment": "x"}, sig)
    assert ok["risk_level"] == "high"


def test_fraud_endpoint_jawaban_tak_terbaca_bukan_low(monkeypatch):
    from routes import dewi_ai_business as b
    monkeypatch.setattr(b, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(b, "get_db", lambda: FakeDB())

    async def _signals(db, **k):
        return {"invoice_stats": {"count": 1, "avg": 1, "std": 0}, "payment_count": 0,
                "top_invoice_outliers": [], "top_stock_adjustments": []}

    async def _claude(**k):
        return "Maaf saya tidak bisa membuat JSON"

    monkeypatch.setattr(b.fin_agg, "fraud_detection_signals", _signals)
    monkeypatch.setattr(b, "call_claude", _claude)
    out = run(b.fraud_detection(FakeRequest(), days=30))
    assert out["data"]["ai_analysis"]["risk_level"] == "tidak_dapat_dinilai"


def test_fraud_endpoint_terpotong_galat_bukan_low(monkeypatch):
    from routes import dewi_ai_business as b
    from services.ai import AIError, ai_http_error
    monkeypatch.setattr(b, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(b, "get_db", lambda: FakeDB())

    async def _signals(db, **k):
        return {"invoice_stats": {"count": 0, "avg": 0, "std": 0}, "payment_count": 0,
                "top_invoice_outliers": [], "top_stock_adjustments": []}

    async def _claude(**k):  # perilaku call_claude saat stop_reason=max_tokens
        raise ai_http_error(AIError(code="truncated"))

    monkeypatch.setattr(b.fin_agg, "fraud_detection_signals", _signals)
    monkeypatch.setattr(b, "call_claude", _claude)
    with pytest.raises(HTTPException) as ei:
        run(b.fraud_detection(FakeRequest(), days=30))
    assert ei.value.status_code == 502 and "terpotong" in ei.value.detail


# ── Churn: tanpa data → kosong jujur, tanpa pelanggan fiktif ────────────────
def test_churn_tanpa_order_hasil_kosong_tanpa_ai(monkeypatch):
    from routes import marketing_advanced_ai_routes as adv
    db = FakeDB()
    monkeypatch.setattr(adv, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(adv, "get_db", lambda: db)

    async def _no_ai(*a, **k):
        raise AssertionError("AI tidak boleh dipanggil tanpa data")

    monkeypatch.setattr(adv, "require_ai", _no_ai)
    monkeypatch.setattr(adv, "ai_text", _no_ai)
    out = run(adv.run_churn_analysis(FakeRequest()))
    assert out["data"]["customers"] == []
    assert out["data"]["summary"]["total_customers"] == 0 and out["data"]["summary"]["no_data"] is True
    assert db.marketing_churn_scores.calls == []          # tidak ada upsert pelanggan fiktif
    src = open(adv.__file__, encoding="utf-8").read()
    assert 'names = ["Ayu Sari"' not in src and "random.seed(42)" not in src  # generator fiktif dihapus


# ── Harga dinamis: Apply ─────────────────────────────────────────────────────
def _pricing_db(status):
    db = FakeDB()
    db.find_one_map["marketing_dynamic_pricing_settings"] = {"_type": "settings", "enabled": True}
    db.find_one_map["marketing_dynamic_pricing_suggestions"] = {
        "id": "s1", "product": "P", "current_price_rp": 107999, "suggested_price_rp": 1,
        "change_pct": -99.9, "status": status}
    return db


def test_apply_cs_staff_ditolak_seperti_approve(monkeypatch):
    import auth
    from routes import marketing_advanced_ai_routes as adv
    monkeypatch.setattr(auth, "require_auth", _auth(CS))
    db = _pricing_db("pending")
    monkeypatch.setattr(adv, "get_db", lambda: db)
    for fn in (adv.approve_suggestion, adv.apply_suggestion):
        with pytest.raises(HTTPException) as ei:
            run(fn("s1", FakeRequest()))
        assert ei.value.status_code == 403
    assert db.marketing_dynamic_pricing_suggestions.calls == []  # tidak ada status "applied"


def test_apply_butuh_approved_dan_tidak_menulis_applied(monkeypatch):
    import auth
    from routes import marketing_advanced_ai_routes as adv
    monkeypatch.setattr(auth, "require_auth", _auth(MKT))
    db = _pricing_db("pending")
    monkeypatch.setattr(adv, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        run(adv.apply_suggestion("s1", FakeRequest()))
    assert ei.value.status_code == 400  # pending tidak boleh langsung Apply

    db = _pricing_db("approved")
    monkeypatch.setattr(adv, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        run(adv.apply_suggestion("s1", FakeRequest()))
    assert ei.value.status_code == 409 and "katalog" in ei.value.detail
    writes = [c for c in db.marketing_dynamic_pricing_suggestions.calls if c[0] == "update_one"]
    assert writes == []                      # status palsu "applied" tidak ditulis
    assert db.marketing_dynamic_pricing_events.calls == []


def test_approve_mencatat_aktor_sebenarnya(monkeypatch):
    import auth
    from routes import marketing_advanced_ai_routes as adv
    monkeypatch.setattr(auth, "require_auth", _auth(MKT))
    db = _pricing_db("pending")
    monkeypatch.setattr(adv, "get_db", lambda: db)
    run(adv.approve_suggestion("s1", FakeRequest()))
    upd = [c for c in db.marketing_dynamic_pricing_suggestions.calls if c[0] == "update_one"][0][2]["$set"]
    assert upd["decided_by"] == "Manajer Marketing" and upd["decided_by_id"] == "u-mkt"
    ev = [c for c in db.marketing_dynamic_pricing_events.calls if c[0] == "insert_one"][0][1]
    assert ev["actor"] == "Manajer Marketing" and ev["actor"] != "admin"


# ── Riwayat chat AI: IDOR ────────────────────────────────────────────────────
def test_riwayat_chat_disaring_per_user(monkeypatch):
    from routes import rahaza_ai as ra
    db = FakeDB()
    monkeypatch.setattr(ra, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(ra, "get_db", lambda: db)
    run(ra.ai_history(FakeRequest(), session_id="chat-orang-lain-2026-11-02"))
    filt = db.rahaza_ai_chat_history.calls[0][1]
    assert filt == {"session_id": "chat-orang-lain-2026-11-02", "user_id": "u-admin"}


# ── Absen selfie: tanpa face-match AI, selalu review HR ──────────────────────
def test_selfie_clock_in_pending_review_hr_tanpa_llm(monkeypatch):
    import ai_cost_tracker
    import utils.attendance_policy as pol
    import utils.employee_identity as ident
    from routes import rahaza_auto_attendance_selfie as sf
    db = FakeDB()
    monkeypatch.setattr(sf, "require_auth", _auth({"id": "u-emp", "name": "Emp"}))
    monkeypatch.setattr(sf, "get_db", lambda: db)

    async def _noop(*a, **k):
        return None

    async def _emp(db_, user, req=None):
        return {"id": "e1", "photo_url": "/uploads/profil.jpg"}  # dulu memicu kirim foto ke LLM

    async def _late(*a, **k):
        return {"late_minutes": 0}

    async def _policy(db_, **k):
        return {"office": {"require_selfie": False, "require_geofence": False},
                "geo": {"status": "in_range", "in_range": True, "distance_m": 3}}

    async def _boom(*a, **k):
        raise AssertionError("foto selfie TIDAK boleh dikirim ke LLM")

    monkeypatch.setattr(sf, "log_activity", _noop)
    monkeypatch.setattr(ident, "resolve_employee_for", _emp)
    monkeypatch.setattr(ident, "compute_late_minutes", _late)
    monkeypatch.setattr(pol, "enforce_attendance_policy", _policy)
    monkeypatch.setattr(pol, "save_selfie", lambda *a, **k: "/uploads/selfie.jpg")
    monkeypatch.setattr(ai_cost_tracker, "tracked_llm_call", _boom)
    out = run(sf.selfie_clock_in(FakeRequest({"lat": 1, "lng": 2, "photo_base64": "x" * 100,
                                              "do_face_check": True})))
    # geo OK + selfie tidak diwajibkan → dulu "auto_approved"; sekarang SELALU review HR
    assert out["approval_status"] == "pending"
    assert out["approval_reason"] == "menunggu review HR"
    doc = [c for c in db.rahaza_attendance_events.calls if c[0] == "insert_one"][0][1]
    assert doc["approval_status"] == "pending" and doc["approval_reason"] == "menunggu review HR"
    assert doc["face_match_status"] == "disabled"
    assert not hasattr(sf, "_compare_faces")


# ── Layar Integrasi ──────────────────────────────────────────────────────────
def test_integrasi_hanya_anthropic_dan_nilai_tersamar(monkeypatch):
    from routes import rahaza_integrations as ri
    ai_keys = [k for k, v in ri.KNOWN_KEYS.items() if v["category"] == "ai"]
    assert ai_keys == ["ANTHROPIC_API_KEY"]
    secret = "sk-ant-api03-RAHASIA-SEKALI-abcdWXYZ"
    db = FakeDB()
    db.find_rows["rahaza_integration_settings"] = [
        {"key_name": "ANTHROPIC_API_KEY", "value": secret},
        {"key_name": "OPENAI_API_KEY", "value": "sk-openai-lama-1234"}]
    monkeypatch.setattr(ri, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(ri, "get_db", lambda: db)
    out = run(ri.list_settings(FakeRequest()))
    blob = repr(out)
    assert secret not in blob and "RAHASIA" not in blob and "sk-openai-lama" not in blob
    row = [r for r in out["data"] if r["key_name"] == "ANTHROPIC_API_KEY"][0]
    assert row["masked_value"] == "••••••••WXYZ" and row["is_configured"]
    old = [r for r in out["data"] if r["key_name"] == "OPENAI_API_KEY"][0]
    assert old["deprecated"] is True and old["category"] != "ai"


def test_integrasi_tolak_kunci_ai_lama(monkeypatch):
    from routes import rahaza_integrations as ri
    monkeypatch.setattr(ri, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(ri, "get_db", lambda: FakeDB())
    for body in ({"key_name": "EMERGENT_LLM_KEY", "value": "ek-1"},
                 {"key_name": "ANTHROPIC_API_KEY", "value": "bukan-format"}):
        with pytest.raises(HTTPException) as ei:
            run(ri.upsert_setting(FakeRequest(body)))
        assert ei.value.status_code == 400


# ── Monitor AI jujur ─────────────────────────────────────────────────────────
def test_health_label_tidak_healthy_saat_ai_mati():
    from routes.ai_usage_monitor import _health_label
    kw = dict(pct_daily=0, successful=0, failed=0)
    assert _health_label(ai_available=False, ai_enabled=True, **kw) == "offline"
    assert _health_label(ai_available=True, ai_enabled=False, **kw) == "disabled"
    assert _health_label(ai_available=True, ai_enabled=True, pct_daily=0, successful=0, failed=11) == "error"
    assert _health_label(ai_available=True, ai_enabled=True, **kw) == "healthy"


def test_monitor_today_menampilkan_ai_available_dan_galat(monkeypatch):
    from routes import ai_usage_monitor as mon
    db = FakeDB()

    def _agg(pipeline):
        m = pipeline[0]["$match"]
        if m.get("success") is False:
            return [{"_id": "not_configured", "n": 11, "last_at": "2026-11-02T01:00:00",
                     "message": "Fitur AI belum aktif: kunci API Anthropic belum diisi admin."}]
        if "$group" in pipeline[1] and pipeline[1]["$group"].get("_id") is None:
            return [{"_id": None, "calls": 11, "successful": 0, "failed": 11, "cost_usd": 0, "tokens": 0}]
        return []

    db.agg_rows["rahaza_ai_usage_logs"] = _agg

    async def _settings(db_=None, force=False):
        return {"ai_enabled": True, "daily_budget_usd": 5.0}

    async def _status(db_=None):
        return {"available": False, "code": "not_configured",
                "message": "Fitur AI belum aktif: kunci API Anthropic belum diisi admin.",
                "key_configured": False, "key_source": "none", "sdk_installed": True, "sdk_version": "2.3.0"}

    monkeypatch.setattr(mon, "_check_admin", _auth(ADMIN))
    monkeypatch.setattr(mon, "get_db", lambda: db)
    monkeypatch.setattr(mon, "get_ai_settings", _settings)
    monkeypatch.setattr(mon, "ai_status", _status)
    d = run(mon.today_status(FakeRequest()))["data"]
    assert d["health"] == "offline" and d["ai_available"] is False
    assert d["failed_calls"] == 11 and d["recent_error_count"] == 11
    assert d["ai_status"]["message"].startswith("Fitur AI belum aktif")


# ── Konteks data AI ──────────────────────────────────────────────────────────
def test_karyawan_aktif_pakai_active_true(monkeypatch):
    from services.ai_aggregates import hr_aggregates as hr
    db = FakeDB()
    run(hr.production_employee_count(db))
    for _k, filt in db.rahaza_employees.calls:
        assert filt.get("active") is True and "employment_status" not in filt

    from routes import dewi_hr_ai as h
    db2 = FakeDB()
    monkeypatch.setattr(h, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(h, "get_db", lambda: db2)
    run(h.list_employees_for_ai(FakeRequest()))
    run(h.predict_attrition(FakeRequest(), department=None))
    filts = [c[1] for c in db2.rahaza_employees.calls if c[0] == "find"]
    assert len(filts) == 2 and all(f.get("active") is True and "employment_status" not in f for f in filts)


def test_stok_rendah_kritis_pakai_stock_thresholds(monkeypatch):
    from core import stock_thresholds
    from services.ai_aggregates import wms_aggregates as wms

    async def _summary(db):
        return {"low": 0, "critical": 43, "alerts": 43, "missing_threshold": 1683}

    monkeypatch.setattr(stock_thresholds, "summary", _summary)
    db = FakeDB()
    assert run(wms.low_stock_count(db)) == 43
    assert run(wms.critical_materials_count(db)) == 43
    assert db.rahaza_materials.calls == []  # tidak lagi query field total_qty/reorder_point
    src = open(wms.__file__, encoding="utf-8").read().split("async def fabric_quality_breakdown")[0]
    assert "$total_qty" not in src


def test_ap_jatuh_tempo_sertakan_partial_paid_overdue(monkeypatch):
    """2026-11-04: hutang dari SSOT `core.payables` (pemasok + CMT); kas dari buku besar."""
    from routes import dewi_cashflow_ai as cf
    db = FakeDB()
    ctx = run(cf._build_context(db))
    ap_finds = [c[1] for c in db.rahaza_ap_invoices.calls if c[0] == "find"]
    assert ap_finds, "query hutang pemasok tidak ditemukan"
    st = ap_finds[-1]["status"]["$in"]
    assert "partial_paid" in st and "overdue" in st
    assert any(c[0] == "find" for c in db.dewi_cmt_payments.calls), "tagihan CMT tidak ikut dihitung"
    assert not db.rahaza_cash_movements.calls, "arus kas harus dari buku besar, bukan catatan mutasi lama"
    assert "cash_balance" in ctx


def test_cashflow_tanpa_kunci_pesan_ramah(monkeypatch):
    from routes import dewi_cashflow_ai as cf
    from services.ai import LLMUnavailable

    async def _req(*a, **k):
        raise LLMUnavailable()

    monkeypatch.setattr(cf, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(cf, "get_db", lambda: FakeDB())
    monkeypatch.setattr(cf, "require_ai", _req)
    with pytest.raises(HTTPException) as ei:
        run(cf.ai_cashflow_prediction(FakeRequest()))
    assert ei.value.status_code == 503 and "EMERGENT" not in ei.value.detail
    assert ei.value.detail == "Fitur AI belum aktif: kunci API Anthropic belum diisi admin."


def _first_match(pipeline):
    return pipeline[0]["$match"]


def test_agregat_keuangan_kecualikan_draft_batal_dan_live_estimasi():
    from services.ai_aggregates import finance_aggregates as fin
    db = FakeDB()
    db.agg_rows["rahaza_ar_invoices"] = [{"_id": "2026-11", "total": 1_300_000, "maklon": 300_000}]
    db.agg_rows["marketing_live_sessions"] = [{"_id": "2026-11", "total": 711_611_497}]
    since = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rows = run(fin.monthly_revenue_rollup(db, since_iso=since.isoformat(), lmo_adapter=None, since_datetime=since))
    assert rows == [{"month": "2026-11", "invoice_rp": 1_300_000, "maklon_rp": 300_000, "total_rp": 1_300_000,
                     "live_estimasi_rp": 711_611_497, "live_is_estimate": True}]
    # total akuntansi TIDAK menambah live (D1) dan TIDAK menambah maklon dua kali
    assert rows[0]["total_rp"] == rows[0]["invoice_rp"]
    ar_match = _first_match([c for c in db.rahaza_ar_invoices.calls if c[0] == "aggregate"][0][1])
    for st in ("draft", "cancelled"):
        assert st in ar_match["status"]["$nin"]
    run(fin.daily_finance_metrics(db, since_iso=since.isoformat()))
    run(fin.fraud_detection_signals(db, since_iso=since.isoformat(), since_dt=since))
    for c in db.rahaza_ar_invoices.calls:
        if c[0] == "aggregate":
            assert "draft" in _first_match(c[1])["status"]["$nin"]
    live = run(fin.daily_live_session_revenue(db, since=datetime.now(timezone.utc) - timedelta(days=30)))
    assert live["is_estimate"] is True and "ESTIMASI" in live["note"]
    # session_date datetime (data nyata) & string (skema lama) sama-sama tercakup
    lm = [c for c in db.marketing_live_sessions.calls if c[0] == "aggregate"][-1][1][0]["$match"]["$or"]
    assert any(isinstance(x["session_date"]["$gte"], datetime) for x in lm)
    assert any(isinstance(x["session_date"]["$gte"], str) for x in lm)


# ── Image generator (No.61a) & EMK ───────────────────────────────────────────
def test_image_generator_dihapus():
    from routes import marketing_ai_content_tools as ct
    paths = {getattr(r, "path", "") for r in ct.router.routes}
    assert "/api/marketing/ai-content/generate-image" not in paths
    assert "/api/marketing/ai-content/generate-caption" in paths
    src = open(ct.__file__, encoding="utf-8").read()
    assert "OpenAIImageGeneration" not in src and "from emergentintegrations" not in src
    assert not os.path.exists(os.path.join(REPO, "deploy", "emergent_stub"))


def test_tuple_openai_dihapus_dari_maklon_dan_perawatan():
    for f in ("dewi_maklon_quote.py", "dewi_predictive_maintenance.py", "dewi_hr_ai.py", "dewi_career_coach.py"):
        src = open(os.path.join(BACKEND, "routes", f), encoding="utf-8").read()
        assert '("openai", "gpt-5.1")' not in src, f
        assert "EMERGENT_LLM_KEY" not in src.replace('"EMERGENT_LLM_KEY ...")', ""), f


# ── Frontend (statis) ────────────────────────────────────────────────────────
FE = os.path.join(REPO, "frontend", "src", "components", "erp")


@pytest.mark.skipif(not os.path.isdir(FE), reason="frontend tidak tersedia")
def test_dashboard_eksekutif_tidak_navigasi_saat_render():
    src = open(os.path.join(FE, "ManagementDashboard.jsx"), encoding="utf-8").read()
    # `onClick={drill('x')()}` memanggil navigasi saat render → layar tak bisa dibuka
    assert not re.search(r"onClick=\{drill\([^)]*\)\(\)\}", src)
    assert "onClick={drill('ai-business-dashboard')}" in src


@pytest.mark.skipif(not os.path.isdir(FE), reason="frontend tidak tersedia")
def test_frontend_tab_image_generator_dicabut():
    hub = open(os.path.join(FE, "hubs", "MarketingAIHub.jsx"), encoding="utf-8").read()
    assert "label: 'Image Generator'" not in hub and "AIImageGeneratorModule" not in hub
    stub = open(os.path.join(FE, "marketing", "AIImageGeneratorModule.jsx"), encoding="utf-8").read()
    assert "apiFetch(" not in stub and "import " not in stub  # stub tanpa panggilan API
    absen = open(os.path.join(FE, "PortalSayaAbsen.jsx"), encoding="utf-8").read()
    assert "do_face_check: true" not in absen
