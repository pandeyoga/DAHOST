"""Uji regresi HERMETIK lapisan provider AI (P6, 2026-11-02).

routes → services.ai → ai_cost_tracker → Anthropic. Klien Anthropic PALSU, Mongo PALSU;
tidak ada panggilan API sungguhan. Uji yang butuh kelas exception SDK asli memakai
`pytest.importorskip("anthropic")` (CI hanya memasang paket inti).

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ai_fakes import FakeAnthropic, FakeDB, fake_message, run  # noqa: E402

import ai_cost_tracker as t  # noqa: E402
from services import ai as sai  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
GIF = b"GIF89a" + b"\x00" * 40


@pytest.fixture
def env(monkeypatch):
    """Tracker dengan DB palsu, SDK 'terpasang', kunci di env, klien palsu."""
    db = FakeDB()
    monkeypatch.setattr(t, "get_db", lambda: db)
    monkeypatch.setattr(t, "sdk_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-uji-hermetik-0000")
    t.invalidate_api_key_cache()
    t.invalidate_ai_settings_cache()
    t.reset_client_cache()
    made = []
    fake = FakeAnthropic()

    def _make(key):
        made.append(key)
        return fake

    monkeypatch.setattr(t, "_make_client", _make)
    yield {"db": db, "fake": fake, "made": made}
    t.invalidate_api_key_cache()
    t.invalidate_ai_settings_cache()
    t.reset_client_cache()


def _logs(db):
    return [c[1] for c in db.rahaza_ai_usage_logs.calls if c[0] == "insert_one"]


# ── Model & harga (skill claude-api) ─────────────────────────────────────────
def test_tier_hanya_ke_model_anthropic_terbaru():
    assert t.resolve_model("executive") == ("anthropic", "claude-opus-5-5")
    assert t.resolve_model("standard") == ("anthropic", "claude-sonnet-5-5")
    assert t.resolve_model("light") == ("anthropic", "claude-sonnet-5-5")
    assert t.resolve_model(" Executive ") == ("anthropic", "claude-opus-5-5")


@pytest.mark.parametrize("bad", [("openai", "gpt-5.1"), ["openai", "gpt-4o"], "gpt-5.1", None, "opus"])
def test_resolve_model_menolak_tuple_dan_nama_model(bad):
    with pytest.raises(ValueError):
        t.resolve_model(bad)


def test_tabel_harga_sesuai_skill():
    assert t.MODEL_PRICING[("anthropic", "claude-opus-5-5")] == {"input": 4.0, "output": 20.0}
    assert t.MODEL_PRICING[("anthropic", "claude-sonnet-5-5")] == {"input": 2.0, "output": 10.0}
    assert not any(k[0] in ("openai", "google") for k in t.MODEL_PRICING)
    # 1 jt token input + 1 jt output Sonnet 5.5 = $12
    assert t._calc_cost(("anthropic", "claude-sonnet-5-5"), 1_000_000, 1_000_000) == pytest.approx(12.0)
    # model tak dikenal → tarif konservatif (Opus)
    assert t._calc_cost(("anthropic", "x"), 1_000_000, 0) == pytest.approx(4.0)


def test_pin_requirements_dan_dockerfile():
    root = os.path.dirname(t.__file__)
    req = open(os.path.join(root, "requirements.txt"), encoding="utf-8").read().splitlines()
    assert "anthropic==2.3.0" in req
    assert not any(l.lower().startswith(("emergentintegrations", "litellm")) for l in req)
    dockerfile = os.path.join(os.path.dirname(root), "deploy", "Dockerfile.backend")
    if os.path.exists(dockerfile):
        d = open(dockerfile, encoding="utf-8").read()
        assert 'import anthropic' in d
        assert "COPY deploy/emergent_stub" not in d  # stub sudah dihapus


# ── ai_available ─────────────────────────────────────────────────────────────
def test_ai_available_butuh_kunci_dan_sdk(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(t, "get_db", lambda: db)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t.invalidate_api_key_cache()
    monkeypatch.setattr(t, "sdk_available", lambda: True)
    assert run(t.ai_available()) is False
    st = run(t.ai_status())
    assert st["code"] == "not_configured" and "ANTHROPIC_API_KEY" not in st["message"]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x-0000000000")
    t.invalidate_api_key_cache()
    assert run(t.ai_available()) is True

    monkeypatch.setattr(t, "sdk_available", lambda: False)
    assert run(t.ai_available()) is False
    assert run(t.ai_status())["code"] == "sdk_missing"
    t.invalidate_api_key_cache()


def test_kunci_dari_layar_integrasi_diutamakan(monkeypatch):
    db = FakeDB()
    db.find_one_map["rahaza_integration_settings"] = {"value": "sk-ant-dari-db-1234"}
    monkeypatch.setattr(t, "get_db", lambda: db)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dari-env-9999")
    t.invalidate_api_key_cache()
    key, src = run(t.resolve_api_key(force=True))
    assert (key, src) == ("sk-ant-dari-db-1234", "db")
    t.invalidate_api_key_cache()


# ── tracked_llm_call ─────────────────────────────────────────────────────────
def test_panggilan_sukses_parameter_dan_teks(env):
    env["fake"].messages.responses = [fake_message("Ringkasan OK")]
    # K29 (2026-11-02): Opus hanya untuk Laporan Eksekutif → pakai label fitur itu.
    res = run(t.tracked_llm_call("executive-narrative-1a2b3c4d", "u1", "executive", "sys", "isi", max_tokens=400))
    assert res.success and res.text == "Ringkasan OK" and res.error is None
    kw = env["fake"].messages.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["system"] == "sys"
    assert kw["output_config"] == {"effort": t.TIER_EFFORT["executive"]}
    # thinking ikut memakai token output → batas kecil dinaikkan
    assert kw["max_tokens"] >= t.MIN_OUTPUT_TOKENS
    assert "temperature" not in kw and "thinking" not in kw
    log = _logs(env["db"])[-1]
    assert log["success"] is True and log["feature"] == "executive-narrative"
    assert log["model_name"] == "claude-opus-5-5"
    assert log["cost_usd"] == pytest.approx((120 * 4 + 40 * 20) / 1_000_000)


def test_klien_dipakai_ulang(env):
    env["fake"].messages.responses = [fake_message("a"), fake_message("b")]
    run(t.tracked_llm_call("f", None, "standard", "s", "u"))
    run(t.tracked_llm_call("f", None, "light", "s", "u"))
    assert env["made"] == ["sk-ant-uji-hermetik-0000"]  # satu klien untuk dua panggilan


@pytest.mark.parametrize("stop,code", [("max_tokens", "truncated"), ("refusal", "refusal"),
                                       ("model_context_window_exceeded", "truncated")])
def test_stop_reason_jadi_galat_terkendali(env, stop, code):
    env["fake"].messages.responses = [fake_message('{"risk_level": "lo', stop_reason=stop)]
    res = run(t.tracked_llm_call("fraud-detect", None, "standard", "s", "u"))
    assert res.success is False and res.error_code == code
    assert res.text == ""  # isi terpotong TIDAK diteruskan sebagai jawaban
    assert res.error == t.AI_ERROR_MESSAGES[code]
    log = _logs(env["db"])[-1]
    assert log["success"] is False and log["error_code"] == code and log["stop_reason"] == stop


def test_jawaban_kosong_ditolak(env):
    env["fake"].messages.responses = [fake_message(None)]
    res = run(t.tracked_llm_call("f", None, "standard", "s", "u"))
    assert res.error_code == "empty"


def test_tanpa_kunci_galat_ramah_dan_tercatat(monkeypatch, env):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t.invalidate_api_key_cache()
    res = run(t.tracked_llm_call("cashflow", "u9", "executive", "s", "u"))
    assert res.success is False and res.error_code == "not_configured"
    assert res.error == "Fitur AI belum aktif: kunci API Anthropic belum diisi admin."
    assert env["fake"].messages.calls == []  # tidak ada panggilan ke Anthropic
    log = _logs(env["db"])[-1]   # dulu TIDAK dicatat → Monitor AI tampil "healthy"
    assert log["success"] is False and log["error_code"] == "not_configured" and log["feature"] == "cashflow"


def test_master_switch_dan_toggle_fitur(env):
    env["db"].find_one_map["ai_config"] = {"id": "global", "ai_enabled": True,
                                           "disabled_features": ["maklon"]}
    t.invalidate_ai_settings_cache()
    res = run(t.tracked_llm_call("maklon_ai_quote", None, "standard", "s", "u"))
    # 2026-11-02: '_' disamakan dengan '-' → toggle grup "maklon" kini berlaku
    assert res.error_code == "feature_disabled"
    env["db"].find_one_map["ai_config"] = {"id": "global", "ai_enabled": False}
    t.invalidate_ai_settings_cache()
    res = run(t.tracked_llm_call("x", None, "standard", "s", "u"))
    assert res.error_code == "disabled"
    t.invalidate_ai_settings_cache()


def test_tuple_model_lama_ditolak_tanpa_memanggil_api(env):
    res = run(t.tracked_llm_call("maklon-ai-quote", None, ("openai", "gpt-5.1"), "s", "u"))
    assert res.success is False and res.error_code == "config"
    assert env["fake"].messages.calls == []


def test_exception_mentah_tidak_bocor(env):
    env["fake"].messages.responses = [RuntimeError("Traceback rahasia sk-ant-xyz ANTHROPIC_API_KEY")]
    res = run(t.tracked_llm_call("f", None, "standard", "s", "u"))
    assert res.success is False
    assert "rahasia" not in res.error and "ANTHROPIC_API_KEY" not in res.error
    assert res.error in t.AI_ERROR_MESSAGES.values()


def test_pemetaan_exception_sdk_asli():
    anthropic = pytest.importorskip("anthropic")
    import httpx2
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def status(cls, code):
        return cls("x", response=httpx2.Response(code, request=req), body=None)

    assert t._classify_exception(status(anthropic.RateLimitError, 429)) == "rate_limited"
    assert t._classify_exception(status(anthropic.AuthenticationError, 401)) == "auth"
    assert t._classify_exception(status(anthropic.InternalServerError, 500)) == "upstream"
    assert t._classify_exception(status(anthropic.BadRequestError, 400)) == "bad_request"
    assert t._classify_exception(anthropic.APITimeoutError(request=req)) == "timeout"
    assert t._classify_exception(anthropic.APIConnectionError(request=req)) == "connection"


def test_klien_asli_timeout_60_retry_1():
    pytest.importorskip("anthropic")
    c = t._make_client("sk-ant-uji-bukan-kunci")  # konstruksi saja, tanpa jaringan
    assert c.max_retries == 1
    assert c.timeout.read == pytest.approx(60.0)


# ── Gambar: media_type dari isi ──────────────────────────────────────────────
def test_media_type_dideteksi_dari_isi():
    assert t.detect_image_media_type(base64.b64encode(JPEG).decode())[0] == "image/jpeg"
    assert t.detect_image_media_type(base64.b64encode(PNG).decode())[0] == "image/png"
    mt, clean = t.detect_image_media_type("data:image/png;base64," + base64.b64encode(JPEG).decode())
    assert mt == "image/jpeg" and not clean.startswith("data:")  # label data-URL tidak dipercaya
    with pytest.raises(ValueError):
        t.detect_image_media_type(base64.b64encode(GIF).decode())


def test_gambar_jpeg_dikirim_dengan_label_jpeg(env):
    env["fake"].messages.responses = [fake_message('{"ok": true}')]
    res = run(t.tracked_llm_call("marketing-health-ocr", None, "standard", "s", "baca",
                                 image_base64=base64.b64encode(JPEG).decode()))
    assert res.success
    content = env["fake"].messages.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1] == {"type": "text", "text": "baca"}


def test_gambar_format_lain_galat_ramah(env):
    res = run(t.tracked_llm_call("ocr", None, "standard", "s", "u", image_base64=base64.b64encode(GIF).decode()))
    assert res.error_code == "bad_image" and env["fake"].messages.calls == []


# ── services.ai ──────────────────────────────────────────────────────────────
def test_ai_http_error_pesan_ramah_dan_status():
    from fastapi import HTTPException
    e = sai.ai_http_error(t.AIError(code="not_configured"))
    assert isinstance(e, sai.LLMUnavailable) and e.status_code == 503
    assert e.detail == "Fitur AI belum aktif: kunci API Anthropic belum diisi admin."
    assert sai.ai_http_error(t.AIError(code="over_budget")).status_code == 429
    assert sai.ai_http_error(t.AIError(code="timeout")).status_code == 504
    assert sai.ai_http_error(t.AIError(code="truncated")).status_code == 502
    assert isinstance(sai.ai_http_error(RuntimeError("x")), HTTPException)
    for msg in t.AI_ERROR_MESSAGES.values():
        assert "EMERGENT" not in msg and "_API_KEY" not in msg and "env" not in msg.lower()


def test_call_claude_tanpa_kunci_503_ramah(monkeypatch, env):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t.invalidate_api_key_cache()
    with pytest.raises(sai.LLMUnavailable) as ei:
        run(sai.call_claude("s", "u", session_tag="executive-narrative", tier="executive"))
    assert ei.value.status_code == 503 and "Anthropic" in ei.value.detail


def test_require_ai_mencatat_percobaan_gagal(monkeypatch, env):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t.invalidate_api_key_cache()
    with pytest.raises(sai.LLMUnavailable):
        run(sai.require_ai("hr-ai-coaching", user_id="u1"))
    log = _logs(env["db"])[-1]
    assert log["feature"] == "hr-ai-coaching" and log["error_code"] == "not_configured"


def test_ai_json_call_jawaban_tak_terbaca(env):
    env["fake"].messages.responses = [fake_message("bukan json sama sekali")]
    with pytest.raises(t.AIError) as ei:
        run(sai.ai_json_call("f", "s", "u"))
    assert ei.value.code == "bad_output"


def test_tidak_ada_jalur_ai_lama_di_backend():
    root = os.path.dirname(t.__file__)
    assert not os.path.exists(os.path.join(root, "ai_llm.py"))
    offenders = []
    for dp, _dn, fn in os.walk(os.path.join(root, "routes")):
        for f in fn:
            if not f.endswith(".py"):
                continue
            src = open(os.path.join(dp, f), encoding="utf-8").read()
            if "from ai_llm import" in src or "emergentintegrations" in src.replace(
                    "impor `emergentintegrations`", ""):
                offenders.append(f)
            if 'os.environ.get("EMERGENT_LLM_KEY"' in src and "if not EMERGENT_LLM_KEY" in src:
                offenders.append(f + " (gerbang EMK)")
    assert offenders == []
