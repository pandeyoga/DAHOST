"""
AI Cost Tracker — SATU-SATUNYA jalur ke Anthropic (Claude) di seluruh aplikasi.

2026-11-02 (keputusan owner No.60): provider AI hanya Anthropic lewat
`ANTHROPIC_API_KEY` (env atau layar Integrasi). Rantai panggilan:

    routes → services/ai (ai_text / ai_json_call / call_claude) → ai_cost_tracker → Anthropic

Fitur:
- Melacak setiap panggilan: fitur, user, model, token, latensi, sukses/gagal
  (TERMASUK panggilan yang gagal karena kunci belum diisi — agar Monitor AI jujur).
- Estimasi biaya dari token × tarif resmi model.
- Batas anggaran harian/bulanan/per fitur + master switch & toggle fitur (DB `ai_config`).
- Galat terkendali berkode (`error_code`) dengan pesan ramah berbahasa Indonesia;
  nama variabel env & isi exception mentah TIDAK PERNAH sampai ke pengguna.

Pemakaian:
    from ai_cost_tracker import tracked_llm_call
    res = await tracked_llm_call(feature="daily-summary", user_id=uid, model="standard",
                                 system_message="...", user_message="...")
    res.text / res.error (pesan ramah) / res.error_code

Koleksi log: rahaza_ai_usage_logs
"""
import base64
import binascii
import os
import re
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from dataclasses import dataclass
from database import get_db
from utils.waktu import today_wib

logger = logging.getLogger(__name__)
# 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)
USAGE_LOGS = "rahaza_ai_usage_logs"

# ── Tarif resmi per 1 jt token (USD) ─────────────────────────────────────────
# 2026-11-02: sumber skill `claude-api` (tabel "Current Models", cache 2026-10-06):
#   Claude Opus 5.5   `claude-opus-5-5`   $4 / $20
#   Claude Sonnet 5.5 `claude-sonnet-5-5` $2 / $10
# Tabel lama memakai tarif keliru (opus $15/$75, sonnet $3/$15) sehingga anggaran
# harian "habis" 1,5–3× lebih cepat dari kenyataan. Biaya di log dihitung saat
# panggilan, jadi entri OpenAI/Google lama tidak dibutuhkan lagi dan dibuang.
#
# 2026-11-07 (Asisten AI, Tahap A): tarif cache & pencarian web dari skill `claude-api`
# (shared/model-migration.md › Claude Opus 5.5 › Pricing; shared/prompt-caching.md › Economics):
#   Opus 5.5: baca cache $0,20/MTok (0,05× input), tulis cache 5 menit $5/MTok (1,25× input).
#   Model lain: baca 0,1× input, tulis 1,25× input (TTL 5 menit — satu-satunya TTL yang dipakai).
#   Pencarian web: $10 per 1.000 pencarian. Pengambilan halaman web tidak ditagih terpisah (hanya token).
MODEL_PRICING = {
    ("anthropic", "claude-opus-5-5"): {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
    ("anthropic", "claude-sonnet-5-5"): {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.5},
    # Model tak dikenal → tarif tertinggi yang dipakai (konservatif, tidak meremehkan biaya).
    ("default", "default"): {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
}
CACHE_READ_MULT = 0.1      # cadangan bila tabel model tidak menyebut `cache_read`
CACHE_WRITE_MULT = 1.25    # TTL 5 menit
WEB_SEARCH_USD_PER_REQUEST = 10.0 / 1000

# Budget limits (configurable via env, default values)
# 2026-11-07 (keputusan owner no. 3, Asisten AI): bawaan $10/hari, $150/bulan, $5/hari per fitur;
# peringatan di 80% (lihat `_check_budget`). Setelan Monitor AI (`ai_config`) tetap mengalahkan bawaan ini.
DEFAULT_DAILY_BUDGET_USD = float(os.environ.get("LLM_DAILY_BUDGET_USD", "10.0"))
DEFAULT_MONTHLY_BUDGET_USD = float(os.environ.get("LLM_MONTHLY_BUDGET_USD", "150.0"))
DEFAULT_PER_FEATURE_DAILY_USD = float(os.environ.get("LLM_PER_FEATURE_DAILY_USD", "5.0"))
BUDGET_WARN_RATIO = 0.8

# ── Tier → model ────────────────────────────────────────────────────────────
# 2026-11-07 (keputusan owner no. 5): SEMUA fitur AI memakai Claude Opus 5.5. Tier kini hanya
# menentukan effort: executive & standard = `medium`, light (tugas ringan) = `low`.
# Ini menggantikan aturan lama K29 ("Opus hanya untuk Laporan Eksekutif").
OPUS_MODEL = ("anthropic", "claude-opus-5-5")
TIER_MODELS = {
    "executive": OPUS_MODEL,
    "standard": OPUS_MODEL,
    "light": OPUS_MODEL,
}
# Effort diset EKSPLISIT (skill: default Opus 5.5 = medium).
# Thinking tidak bisa dimatikan di Opus 5.5 → kedalaman diatur lewat effort.
TIER_EFFORT = {"executive": "medium", "standard": "medium", "light": "low"}
DEFAULT_TIER = "standard"

# K29 (2026-11-02) dicabut 2026-11-07 (keputusan no. 5): tidak ada lagi penurunan tier.
# Daftar & `executive_allowed()` dibiarkan (tidak berbahaya) untuk pemanggil lama.
EXECUTIVE_FEATURES = ("executive-narrative",)

# 2026-11-02 (K29): SSOT grup fitur yang bisa di-on/off di Monitor AI (dulu hanya di
# routes/ai_usage_monitor.py). Label fitur di log dicocokkan per prefiks ke grup ini
# sehingga biaya per fitur selalu cocok dengan toggle-nya (`feature_group` di log).
AI_FEATURE_GROUPS = [
    # 2026-11-07 Tahap A. Asisten AI (proaktif): briefing/laporan otomatis dicatat `asisten-ai-proaktif` (grup
    # yang sama → toggle ini juga mematikan briefing; anggaran per fitur dihitung terpisah dari chat).
    {"key": "asisten-ai", "label": "Asisten AI (chat analis Portal Manajemen)"},
    {"key": "executive-narrative", "label": "Analisis Eksekutif AI"},
    {"key": "daily-summary", "label": "Ringkasan Bisnis Harian"},
    {"key": "revenue-forecast", "label": "Prediksi Pendapatan"},
    {"key": "cashflow", "label": "Prediksi Arus Kas"},
    {"key": "fraud-detect", "label": "Deteksi Anomali / Fraud"},
    {"key": "prod-optimize", "label": "Optimasi Produksi"},
    {"key": "marketing", "label": "AI Marketing & Insights"},
    {"key": "maklon", "label": "Estimasi Harga Maklon"},
    {"key": "wms", "label": "AI Gudang (WMS)"},
    {"key": "smart-import", "label": "Smart Import (mapping AI)"},
    {"key": "rahaza", "label": "Asisten AI Rahaza"},
    {"key": "career", "label": "Career Coach SDM"},
    {"key": "hr-ai", "label": "AI SDM (screening CV, attrition, coaching)"},
    {"key": "assistant-erp", "label": "Asisten ERP"},
    {"key": "analytics-ai", "label": "RCA Produksi/QC"},
    {"key": "predictive-maintenance", "label": "Saran Perawatan Mesin"},
]


def feature_group(feature: Optional[str]) -> Optional[str]:
    """Kunci grup Monitor AI untuk label fitur (exact / prefiks), atau None."""
    f = (feature or "").lower().strip().replace("_", "-")
    for g in sorted(AI_FEATURE_GROUPS, key=lambda g: -len(g["key"])):
        if f == g["key"] or f.startswith(g["key"] + "-"):
            return g["key"]
    return None


def executive_allowed(feature: Optional[str]) -> bool:
    """Sisa K29 (dicabut 2026-11-07): hanya informasi, TIDAK lagi dipakai untuk menurunkan tier."""
    f = (feature or "").lower().strip().replace("_", "-")
    return any(f == k or f.startswith(k + "-") for k in EXECUTIVE_FEATURES)

# max_tokens: thinking ikut memakai token output, jadi batas kecil (mis. 400) dari
# pemanggil lama akan memotong jawaban. Skill: non-streaming ≈16000.
MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "16000"))
MIN_OUTPUT_TOKENS = int(os.environ.get("LLM_MIN_OUTPUT_TOKENS", "8000"))

# 2026-11-02: timeout ±60 dtk & 1 retry (default SDK 10 menit & 2 retry membuat
# worker FastAPI/proxy menggantung). Total terburuk ≈ timeout × (retry + 1).
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "1"))

ANTHROPIC_KEY_NAME = "ANTHROPIC_API_KEY"

# ── Galat terkendali → pesan ramah (tanpa nama env / exception mentah) ───────
AI_ERROR_MESSAGES = {
    "not_configured": "Fitur AI belum aktif: kunci API Anthropic belum diisi admin.",
    "sdk_missing": "Fitur AI belum aktif: komponen AI belum terpasang di server. Hubungi admin.",
    "disabled": "Fitur AI sedang dimatikan oleh admin.",
    "feature_disabled": "Fitur AI ini sedang dimatikan oleh admin.",
    "over_budget": "Batas anggaran AI sudah tercapai. Coba lagi nanti atau hubungi admin.",
    "auth": "Kunci API Anthropic ditolak. Admin perlu memeriksa kunci di menu Integrasi.",
    "rate_limited": "Layanan AI sedang sibuk. Silakan coba lagi beberapa saat lagi.",
    "timeout": "Layanan AI terlalu lama merespons. Silakan coba lagi.",
    "connection": "Server tidak dapat terhubung ke layanan AI. Silakan coba lagi nanti.",
    "bad_request": "Permintaan ke layanan AI tidak dapat diproses.",
    "upstream": "Layanan AI sedang bermasalah. Silakan coba lagi nanti.",
    "truncated": "Jawaban AI terpotong karena terlalu panjang, sehingga tidak dipakai. Silakan coba lagi.",
    "refusal": "AI menolak memproses permintaan ini.",
    "empty": "AI tidak memberikan jawaban. Silakan coba lagi.",
    "bad_output": "Jawaban AI tidak dapat dibaca sistem. Silakan coba lagi.",
    "bad_image": "Format gambar tidak didukung. Gunakan foto JPG atau PNG.",
    "config": "Konfigurasi fitur AI tidak valid. Hubungi admin.",
    "internal": "Terjadi kesalahan saat memproses AI. Silakan coba lagi.",
}
# Kode yang berarti "AI tidak bisa dipakai sama sekali" (bukan galat sesaat).
UNAVAILABLE_CODES = ("not_configured", "sdk_missing", "disabled", "feature_disabled")

_HTTP_STATUS = {
    "not_configured": 503, "sdk_missing": 503, "disabled": 503, "feature_disabled": 503,
    "over_budget": 429, "rate_limited": 429, "timeout": 504, "connection": 503,
    "bad_image": 400, "config": 500, "internal": 500,
}


def friendly_error(code: Optional[str]) -> str:
    return AI_ERROR_MESSAGES.get(code or "internal", AI_ERROR_MESSAGES["internal"])


def http_status_for(code: Optional[str]) -> int:
    return _HTTP_STATUS.get(code or "internal", 502)


# ── WS-B(d): DB-driven AI settings (budget + feature toggles + master switch) ─
# Disimpan di koleksi `ai_config` doc id="global". Fallback ke default/env.
_AI_SETTINGS_CACHE = {"data": None, "ts": 0.0}
_AI_SETTINGS_TTL = 20.0  # detik


def _default_ai_settings() -> dict:
    return {
        "ai_enabled": True,
        "daily_budget_usd": DEFAULT_DAILY_BUDGET_USD,
        "monthly_budget_usd": DEFAULT_MONTHLY_BUDGET_USD,
        "per_feature_daily_usd": DEFAULT_PER_FEATURE_DAILY_USD,
        "default_tier": DEFAULT_TIER,
        "disabled_features": [],
        # Asisten AI (inti) — Tahap B: saklar "Tindakan AI aktif" + batas tindakan per pengguna per hari.
        "asisten_tindakan_aktif": True,
        "asisten_batas_tindakan_harian": 30,
        # ── akhir Asisten AI (inti) ──
        # Asisten AI (proaktif) — Tahap D (keputusan owner no. 12–13): ingatan AI + briefing pagi 07:00,
        # peringatan harian, laporan mingguan Senin. Penerima kosong = semua owner aktif. Jam = WIB "HH:MM".
        "asisten_ingatan_aktif": True,
        "asisten_briefing_aktif": True,
        "asisten_briefing_jam": "07:00",
        "asisten_briefing_penerima": [],
        "asisten_peringatan_aktif": True,
        "asisten_peringatan_jam": "07:00",
        "asisten_laporan_mingguan_aktif": True,
        "asisten_laporan_mingguan_jam": "07:30",
        # ── akhir Asisten AI (proaktif) ──
    }


async def get_ai_settings(db=None, force: bool = False) -> dict:
    """Ambil setting AI dari DB (cache 20s). Selalu mengembalikan dict lengkap."""
    now = time.time()
    if (not force) and _AI_SETTINGS_CACHE["data"] is not None and (now - _AI_SETTINGS_CACHE["ts"]) < _AI_SETTINGS_TTL:
        return _AI_SETTINGS_CACHE["data"]
    settings = _default_ai_settings()
    try:
        db = db if db is not None else get_db()
        doc = await db.ai_config.find_one({"id": "global"}, {"_id": 0})
        if doc:
            for k in list(settings.keys()):
                if k in doc and doc[k] is not None:
                    settings[k] = doc[k]
    except Exception as e:  # pragma: no cover
        logger.warning("get_ai_settings gagal, pakai default: %s", e)
    _AI_SETTINGS_CACHE["data"] = settings
    _AI_SETTINGS_CACHE["ts"] = now
    return settings


def invalidate_ai_settings_cache() -> None:
    _AI_SETTINGS_CACHE["data"] = None
    _AI_SETTINGS_CACHE["ts"] = 0.0


def _norm_feature_key(s: str) -> str:
    return (s or "").lower().strip().replace("_", "-")


def _feature_disabled(feature: str, disabled: list) -> bool:
    """True bila `feature` cocok (exact atau prefix-grup) dengan salah satu entri disabled.

    2026-11-02: '_' disamakan dengan '-' — label lama `maklon_ai_quote` dulu tidak
    pernah cocok dengan grup `maklon` sehingga toggle admin tidak berefek.
    """
    f = _norm_feature_key(feature)
    for d in (disabled or []):
        d = _norm_feature_key(d)
        if not d:
            continue
        if f == d or f.startswith(d + "-"):
            return True
    return False


def _normalize_feature(feature: Optional[str]) -> str:
    """Label fitur stabil: buang sufiks id/uuid (mis. `chat-1a2b3c4d`)."""
    base = (feature or "ai").strip() or "ai"
    return re.sub(r"[-_][0-9a-f]{6,}$", "", base) or "ai"


def resolve_model(tier) -> Tuple[str, str]:
    """HANYA menerima tier: 'executive' / 'standard' / 'light'.

    2026-11-02: tuple (provider, model) seperti ("openai", "gpt-5.1") DITOLAK —
    dulu diteruskan apa adanya ke Anthropic sehingga fitur maklon/perawatan mesin
    tidak pernah berhasil.
    """
    if isinstance(tier, str) and tier.strip().lower() in TIER_MODELS:
        return TIER_MODELS[tier.strip().lower()]
    raise ValueError(f"Tier AI tidak dikenal: {tier!r} (pakai executive/standard/light)")


def _tier_name(tier) -> str:
    return tier.strip().lower() if isinstance(tier, str) else DEFAULT_TIER


class AIError(Exception):
    """Kegagalan pemanggilan AI terpusat. `str(e)` SELALU pesan ramah."""

    def __init__(self, message: Optional[str] = None, over_budget: bool = False, code: Optional[str] = None):
        code = code or ("over_budget" if over_budget else "internal")
        super().__init__(message or friendly_error(code))
        self.code = code
        self.over_budget = over_budget or code == "over_budget"

    @property
    def status_code(self) -> int:
        return http_status_for(self.code)

    @property
    def user_message(self) -> str:
        return str(self)


@dataclass
class TrackedResult:
    text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    model: str = ""
    success: bool = False
    error: Optional[str] = None          # pesan ramah (aman ditampilkan)
    error_code: Optional[str] = None
    stop_reason: Optional[str] = None
    over_budget: bool = False
    budget_warning: Optional[str] = None


def _approx_tokens(text: str) -> int:
    """Rough heuristic: ~4 chars per token English, ~3 for Indonesian."""
    if not text:
        return 0
    return max(1, len(text) // 3)


def _calc_cost(model: Tuple[str, str], tokens_in: int, tokens_out: int, *,
               cache_read: int = 0, cache_write: int = 0, web_search: int = 0) -> float:
    """Biaya USD satu panggilan.

    `tokens_in` = token input TANPA cache (sisa di luar cache, sesuai `usage.input_tokens`);
    `cache_read` / `cache_write` = `cache_read_input_tokens` / `cache_creation_input_tokens`;
    `web_search` = jumlah pencarian web (`usage.server_tool_use.web_search_requests`).
    Model berlabel "fake" (mode uji) dihitung dengan tarif model yang ditiru.
    """
    key = tuple(model) if isinstance(model, (tuple, list)) else ("default", "default")
    if key and key[0] == "fake":
        key = ("anthropic", key[1])
    pricing = MODEL_PRICING.get(key, MODEL_PRICING[("default", "default")])
    p_read = pricing.get("cache_read", pricing["input"] * CACHE_READ_MULT)
    p_write = pricing.get("cache_write", pricing["input"] * CACHE_WRITE_MULT)
    token_cost = (int(tokens_in or 0) * pricing["input"] + int(tokens_out or 0) * pricing["output"]
                  + int(cache_read or 0) * p_read + int(cache_write or 0) * p_write) / 1_000_000
    return token_cost + int(web_search or 0) * WEB_SEARCH_USD_PER_REQUEST


def calc_cost(model: Tuple[str, str], tokens_in: int, tokens_out: int, *,
              cache_read: int = 0, cache_write: int = 0, web_search: int = 0) -> float:
    """Versi publik `_calc_cost` (dipakai loop Asisten AI)."""
    return _calc_cost(model, tokens_in, tokens_out, cache_read=cache_read, cache_write=cache_write,
                      web_search=web_search)


def _effective_max_tokens(requested: Optional[int]) -> int:
    try:
        req = int(requested or MAX_OUTPUT_TOKENS)
    except (TypeError, ValueError):
        req = MAX_OUTPUT_TOKENS
    return max(req, MIN_OUTPUT_TOKENS)


# ── Gambar: media_type dari ISI berkas, bukan dipatok image/png ──────────────
def detect_image_media_type(image_base64: str) -> Tuple[str, str]:
    """Return (media_type, base64_bersih). Raise ValueError bila bukan JPEG/PNG.

    2026-11-02: dulu selalu `image/png`, sehingga foto JPEG dari kamera HP dikirim
    dengan label salah. Prefix data-URL (`data:image/...;base64,`) dibuang.
    """
    raw = (image_base64 or "").strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    raw = re.sub(r"\s+", "", raw)
    if not raw:
        raise ValueError("gambar kosong")
    head_b64 = raw[:32]
    head_b64 += "=" * (-len(head_b64) % 4)
    try:
        head = base64.b64decode(head_b64, validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError("base64 gambar rusak") from e
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", raw
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", raw
    raise ValueError("format gambar bukan JPEG/PNG")


# ── Kunci & SDK ──────────────────────────────────────────────────────────────
_KEY_CACHE = {"value": None, "source": "none", "ts": 0.0}
_KEY_TTL = 30.0  # detik


def invalidate_api_key_cache() -> None:
    """Dipanggil layar Integrasi setelah kunci disimpan/dihapus."""
    _KEY_CACHE.update({"value": None, "source": "none", "ts": 0.0})


async def resolve_api_key(db=None, force: bool = False) -> Tuple[str, str]:
    """Return (kunci, sumber). Sumber: 'db' (layar Integrasi) → 'env' → 'none'.

    2026-11-02: env dibaca SAAT panggilan (dulu konstanta saat import), dan kunci
    yang disimpan admin di layar Integrasi kini juga dipakai semua fitur AI.
    """
    now = time.time()
    if (not force) and _KEY_CACHE["ts"] and (now - _KEY_CACHE["ts"]) < _KEY_TTL:
        return _KEY_CACHE["value"] or "", _KEY_CACHE["source"]
    value, source = "", "none"
    try:
        db = db if db is not None else get_db()
        doc = await db.rahaza_integration_settings.find_one(
            {"key_name": ANTHROPIC_KEY_NAME}, {"_id": 0, "value": 1})
        if doc and (doc.get("value") or "").strip():
            value, source = doc["value"].strip(), "db"
    except Exception as e:  # DB belum siap / uji hermetik
        logger.debug("resolve_api_key: DB tidak terbaca (%s)", type(e).__name__)
    if not value:
        env_val = (os.environ.get(ANTHROPIC_KEY_NAME) or "").strip()
        if env_val:
            value, source = env_val, "env"
    _KEY_CACHE.update({"value": value, "source": source, "ts": now})
    return value, source


def sdk_available() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def sdk_version() -> Optional[str]:
    try:
        import anthropic
        return getattr(anthropic, "__version__", None)
    except Exception:
        return None


async def ai_status(db=None) -> dict:
    """Status AI yang jujur untuk gerbang fitur & Monitor AI."""
    key, source = await resolve_api_key(db)
    sdk = sdk_available()
    if not sdk:
        code = "sdk_missing"
    elif not key:
        code = "not_configured"
    else:
        code = None
    return {
        "available": code is None,
        "code": code,
        "message": friendly_error(code) if code else "AI aktif.",
        "key_configured": bool(key),
        "key_source": source,
        "sdk_installed": sdk,
        "sdk_version": sdk_version() if sdk else None,
    }


async def ai_available(db=None) -> bool:
    """True bila kunci Anthropic ada (DB/env) DAN SDK `anthropic` bisa di-import.

    2026-11-02: pengganti tunggal semua gerbang lama `EMERGENT_LLM_KEY`.
    """
    return (await ai_status(db))["available"]


# Klien dipakai ulang (satu per kunci) — dulu dibuat baru di setiap panggilan.
_CLIENT_CACHE = {"key": None, "client": None}


def _make_client(api_key: str):
    import anthropic
    return anthropic.AsyncAnthropic(
        api_key=api_key,
        timeout=anthropic.Timeout(LLM_TIMEOUT_SECONDS, connect=5.0),
        max_retries=LLM_MAX_RETRIES,
    )


def _get_client(api_key: str):
    if _CLIENT_CACHE["client"] is None or _CLIENT_CACHE["key"] != api_key:
        _CLIENT_CACHE["client"] = _make_client(api_key)
        _CLIENT_CACHE["key"] = api_key
    return _CLIENT_CACHE["client"]


def reset_client_cache() -> None:
    _CLIENT_CACHE.update({"key": None, "client": None})


def _classify_exception(e: Exception) -> str:
    """Petakan exception SDK → kode galat (paling spesifik lebih dulu)."""
    try:
        import anthropic
    except Exception:
        return "internal"
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return "auth"
    if isinstance(e, anthropic.RateLimitError):
        return "rate_limited"
    if isinstance(e, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(e, anthropic.APIConnectionError):
        return "connection"
    if isinstance(e, (anthropic.BadRequestError, anthropic.NotFoundError,
                      anthropic.UnprocessableEntityError)):
        return "bad_request"
    if isinstance(e, anthropic.APIStatusError):
        return "upstream"
    return "internal"


async def sum_cost(db, match: dict) -> float:
    """Total `cost_usd` log pemakaian untuk filter `match` (satu agregasi)."""
    rows = await db.rahaza_ai_usage_logs.aggregate([
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
    ]).to_list(length=1)
    return float(rows[0].get("total") or 0.0) if rows else 0.0


async def month_to_date_cost(db) -> float:
    """Biaya AI bulan berjalan (UTC, sama dengan kunci `date` di log)."""
    month_start = today_wib().replace(day=1)
    return await sum_cost(db, {"date": {"$gte": month_start.isoformat()}})


async def _check_budget(db, feature: str, *, daily_budget=None, monthly_budget=None, per_feature_budget=None) -> Tuple[bool, Optional[str]]:
    """Check if we're approaching budget. Returns (over_budget, warning_message).

    Budget limits berasal dari setting DB (WS-B d); fallback ke default env.
    2026-11-02: biaya dihitung dari SEMUA log (jawaban terpotong/ditolak tetap
    ditagih Anthropic); percobaan yang diblok sebelum memanggil API biayanya 0.
    """
    daily_budget = DEFAULT_DAILY_BUDGET_USD if daily_budget is None else float(daily_budget)
    monthly_budget = DEFAULT_MONTHLY_BUDGET_USD if monthly_budget is None else float(monthly_budget)
    per_feature_budget = DEFAULT_PER_FEATURE_DAILY_USD if per_feature_budget is None else float(per_feature_budget)

    today = today_wib()

    daily_total = await sum_cost(db, {"date": today.isoformat()})
    if daily_total >= daily_budget:
        return True, f"Batas anggaran AI harian tercapai (${daily_total:.4f} dari ${daily_budget})."

    feat_total = await sum_cost(db, {"date": today.isoformat(), "feature": feature})
    if feat_total >= per_feature_budget:
        return True, f"Batas anggaran harian fitur AI ini tercapai (${feat_total:.4f} dari ${per_feature_budget})."

    # Bulanan — batas diatur di Monitor AI › Pengaturan (`ai_config.monthly_budget_usd`, K29).
    monthly_total = await month_to_date_cost(db)
    if monthly_total >= monthly_budget:
        return True, f"Batas anggaran AI bulanan tercapai (${monthly_total:.4f} dari ${monthly_budget})."

    # Peringatan 80% (keputusan owner no. 3, 2026-11-07: harian, bulanan, dan per fitur).
    if daily_total >= daily_budget * BUDGET_WARN_RATIO:
        return False, f"⚠️ Anggaran AI harian sudah 80%: ${daily_total:.4f} / ${daily_budget}"
    if monthly_total >= monthly_budget * BUDGET_WARN_RATIO:
        return False, f"⚠️ Anggaran AI bulanan sudah 80%: ${monthly_total:.4f} / ${monthly_budget}"
    if feat_total >= per_feature_budget * BUDGET_WARN_RATIO:
        return False, f"⚠️ Anggaran harian fitur AI ini sudah 80%: ${feat_total:.4f} / ${per_feature_budget}"

    return False, None


async def budget_snapshot(db, feature: Optional[str] = None) -> dict:
    """Pemakaian vs batas EFEKTIF (setelan Monitor AI → bawaan) untuk hari ini / bulan ini / satu fitur.

    Dipakai `GET /api/asisten-ai/status` (sisa anggaran). Angka USD dibulatkan 4 desimal.
    """
    s = await get_ai_settings(db)
    today = today_wib().isoformat()
    daily_budget = float(s.get("daily_budget_usd") or 0)
    monthly_budget = float(s.get("monthly_budget_usd") or 0)
    per_feature_budget = float(s.get("per_feature_daily_usd") or 0)
    daily_total = await sum_cost(db, {"date": today})
    monthly_total = await month_to_date_cost(db)
    feat_total = await sum_cost(db, {"date": today, "feature": _normalize_feature(feature)}) if feature else 0.0

    def _r(x):
        return round(float(x), 4)
    return {
        "harian_usd": _r(daily_budget), "terpakai_hari_ini_usd": _r(daily_total),
        "sisa_hari_ini_usd": _r(max(0.0, daily_budget - daily_total)),
        "bulanan_usd": _r(monthly_budget), "terpakai_bulan_ini_usd": _r(monthly_total),
        "sisa_bulan_ini_usd": _r(max(0.0, monthly_budget - monthly_total)),
        "fitur_harian_usd": _r(per_feature_budget), "terpakai_fitur_hari_ini_usd": _r(feat_total),
        "sisa_fitur_hari_ini_usd": _r(max(0.0, per_feature_budget - feat_total)),
    }


@dataclass
class GateResult:
    """Hasil gerbang sebelum memanggil Anthropic (kunci, saklar utama, toggle fitur, anggaran)."""
    ok: bool = False
    code: Optional[str] = None
    message: Optional[str] = None       # pesan ramah (aman ditampilkan)
    warning: Optional[str] = None       # peringatan 80% (bukan penolakan)
    api_key: str = ""
    over_budget: bool = False


async def check_gate(feature: str, user_id: Optional[str] = None, *, db=None, model=None,
                     require_key: bool = True, skip_budget_check: bool = False,
                     log_blocked: bool = True) -> GateResult:
    """SATU gerbang yang dipakai `tracked_llm_call` dan loop Asisten AI (2026-11-07).

    Urutan: SDK terpasang → kunci (layar Integrasi → env) → saklar utama → toggle fitur →
    anggaran harian/per fitur/bulanan. Penolakan dicatat ke log pemakaian (biaya 0) supaya
    Monitor AI jujur. `require_key=False` hanya untuk mode uji (`ASISTEN_AI_FAKE=1`).
    """
    feature = _normalize_feature(feature)
    model = model or TIER_MODELS[DEFAULT_TIER]
    db = db if db is not None else get_db()
    res = GateResult()

    async def _blocked(code: str, detail: Optional[str] = None, message: Optional[str] = None):
        res.ok = False
        res.code = code
        res.message = message or friendly_error(code)
        res.over_budget = code == "over_budget"
        if log_blocked:
            await log_usage(feature, user_id, model, 0, 0, 0.0, 0.0, False, res.message,
                            error_code=code, error_detail=detail)
        return res

    if require_key:
        if not sdk_available():
            return await _blocked("sdk_missing")
        api_key, _src = await resolve_api_key(db)
        if not api_key:
            return await _blocked("not_configured")
        res.api_key = api_key

    if not skip_budget_check:
        try:
            settings = await get_ai_settings(db)
        except Exception as e:  # pragma: no cover
            logger.warning(f"AI settings load failed (continuing): {e}")
            settings = _default_ai_settings()
        if not settings.get("ai_enabled", True):
            return await _blocked("disabled")
        if _feature_disabled(feature, settings.get("disabled_features")):
            return await _blocked("feature_disabled")
        try:
            over, warning = await _check_budget(
                db, feature,
                daily_budget=settings.get("daily_budget_usd"),
                monthly_budget=settings.get("monthly_budget_usd"),
                per_feature_budget=settings.get("per_feature_daily_usd"),
            )
            res.warning = warning
            if over:
                return await _blocked("over_budget", detail=warning, message=warning)
        except Exception as e:
            logger.warning(f"Budget check failed (continuing): {e}")

    res.ok = True
    return res


async def log_usage(
    feature: str,
    user_id: Optional[str],
    model: Tuple[str, str],
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    latency_ms: float,
    success: bool,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    error_detail: Optional[str] = None,
    stop_reason: Optional[str] = None,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    web_search_requests: int = 0,
    web_fetch_requests: int = 0,
    session_id: Optional[str] = None,
):
    """Insert usage log into rahaza_ai_usage_logs.

    `error` = pesan ramah; `error_detail` = ringkasan teknis (hanya untuk admin).
    2026-11-07: + token cache (baca/tulis) dan jumlah pencarian/pengambilan web per panggilan.
    `tokens_total` = input tanpa cache + output + baca cache + tulis cache (seluruh token yang diproses).
    """
    try:
        db = get_db()
        cr, cw = int(cache_read_tokens or 0), int(cache_write_tokens or 0)
        await db[USAGE_LOGS].insert_one({
            "id": str(uuid.uuid4()),
            "feature": feature,
            "feature_group": feature_group(feature),  # K29: cocok dengan toggle Monitor AI
            "user_id": user_id,
            "session_id": session_id,
            "model_provider": model[0] if isinstance(model, (tuple, list)) else "unknown",
            "model_name": model[1] if isinstance(model, (tuple, list)) else str(model),
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "cache_read_tokens": cr,
            "cache_write_tokens": cw,
            "web_search_requests": int(web_search_requests or 0),
            "web_fetch_requests": int(web_fetch_requests or 0),
            "tokens_total": int(tokens_in + tokens_out + cr + cw),
            "cost_usd": round(float(cost_usd), 6),
            "latency_ms": round(float(latency_ms), 2),
            "success": bool(success),
            "error": error,
            "error_code": error_code,
            "error_detail": (error_detail or None) and str(error_detail)[:300],
            "stop_reason": stop_reason,
            "date": today_wib().isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning(f"Failed to log AI usage: {e}")


async def record_ai_failure(feature: str, code: str, *, user_id: Optional[str] = None,
                            tier: str = DEFAULT_TIER, detail: Optional[str] = None) -> None:
    """Catat percobaan AI yang gagal sebelum sampai ke Anthropic (mis. kunci kosong)."""
    model = TIER_MODELS.get(_tier_name(tier), TIER_MODELS[DEFAULT_TIER])
    await log_usage(_normalize_feature(feature), user_id, model, 0, 0, 0.0, 0.0, False,
                    friendly_error(code), error_code=code, error_detail=detail)


def _fail(result: TrackedResult, code: str, message: Optional[str] = None) -> TrackedResult:
    result.success = False
    result.error_code = code
    result.error = message or friendly_error(code)
    return result


async def tracked_llm_call(
    feature: str,
    user_id: Optional[str],
    model,
    system_message: str,
    user_message: str,
    session_id: Optional[str] = None,
    skip_budget_check: bool = False,
    image_base64: Optional[str] = None,
    max_tokens: Optional[int] = None,
    history: Optional[list] = None,
) -> TrackedResult:
    """Wrapper terpusat yang melacak biaya LLM.

    `model` WAJIB tier string ('executive'/'standard'/'light'). Kunci diambil dari
    layar Integrasi (DB) lalu env `ANTHROPIC_API_KEY`. `image_base64` = JPEG/PNG.
    `history` (opsional) = giliran sebelumnya `[{"role": "user"|"assistant", "content": str}]`,
    dikirim apa adanya sebelum pesan baru (multi-giliran, mis. Asisten ERP).
    Return TrackedResult: `.text` saat sukses; `.error` (ramah) + `.error_code` saat gagal.
    """
    feature = _normalize_feature(feature)
    tier = _tier_name(model)
    try:
        resolved = resolve_model(model)
    except ValueError as e:
        res = _fail(TrackedResult(model="-"), "config")
        await log_usage(feature, user_id, ("config", str(model)[:40]), 0, 0, 0.0, 0.0, False,
                        res.error, error_code="config", error_detail=str(e))
        return res
    result = TrackedResult(model=f"{resolved[0]}/{resolved[1]}")
    db = get_db()

    async def _blocked(code: str, detail: Optional[str] = None, message: Optional[str] = None):
        _fail(result, code, message)
        await log_usage(feature, user_id, resolved, 0, 0, 0.0, 0.0, False, result.error,
                        error_code=code, error_detail=detail)
        return result

    # Satu gerbang (2026-11-07): SDK, kunci, saklar utama, toggle fitur, anggaran.
    gate = await check_gate(feature, user_id, db=db, model=resolved, skip_budget_check=skip_budget_check)
    result.budget_warning = gate.warning
    if not gate.ok:
        result.over_budget = gate.over_budget
        return _fail(result, gate.code, gate.message)
    api_key = gate.api_key

    # Konten pesan (teks / gambar + teks)
    if image_base64:
        try:
            media_type, clean_b64 = detect_image_media_type(image_base64)
        except ValueError as e:
            return await _blocked("bad_image", detail=str(e))
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": clean_b64}},
            {"type": "text", "text": user_message or ""},
        ]
    else:
        content = user_message or ""
    messages = _history_messages(history) + [{"role": "user", "content": content}]

    tokens_in_approx = _approx_tokens(system_message) + _approx_tokens(user_message)
    start = time.time()
    try:
        client = _get_client(api_key)
        msg = await client.messages.create(
            model=resolved[1],
            max_tokens=_effective_max_tokens(max_tokens),
            system=system_message or "",
            messages=messages,
            output_config={"effort": TIER_EFFORT.get(tier, "medium")},
        )
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        code = _classify_exception(e)
        _fail(result, code)
        result.latency_ms = elapsed_ms
        logger.warning("AI call gagal [%s] %s: %s", feature, code, type(e).__name__)
        await log_usage(feature, user_id, resolved, tokens_in_approx, 0, 0.0, elapsed_ms, False,
                        result.error, error_code=code,
                        error_detail=f"{type(e).__name__}: {str(e)[:200]}")
        return result

    elapsed_ms = (time.time() - start) * 1000
    usage = getattr(msg, "usage", None)
    text = "".join(
        (getattr(b, "text", "") or "")
        for b in (getattr(msg, "content", None) or [])
        if getattr(b, "type", None) == "text"
    )
    tokens_in = int(getattr(usage, "input_tokens", 0) or tokens_in_approx)
    tokens_out = int(getattr(usage, "output_tokens", 0) or _approx_tokens(text))
    cache_read = _int_attr(usage, "cache_read_input_tokens")
    cache_write = _int_attr(usage, "cache_creation_input_tokens")
    cost = _calc_cost(resolved, tokens_in, tokens_out, cache_read=cache_read, cache_write=cache_write)
    stop = getattr(msg, "stop_reason", None)
    cache_kw = {"cache_read_tokens": cache_read, "cache_write_tokens": cache_write}

    result.tokens_in = tokens_in
    result.tokens_out = tokens_out
    result.cost_usd = cost
    result.latency_ms = elapsed_ms
    result.stop_reason = stop

    # 2026-11-02: cek stop_reason SEBELUM memakai isi. Jawaban terpotong/ditolak
    # tidak boleh diperlakukan sebagai jawaban sah (mis. JSON terpotong → default palsu).
    code = None
    if stop == "refusal":
        code = "refusal"
    elif stop in ("max_tokens", "model_context_window_exceeded"):
        code = "truncated"
    elif not text.strip():
        code = "empty"
    if code:
        _fail(result, code)
        # Token tetap ditagih Anthropic → dicatat sebagai biaya, tetapi success=False.
        await log_usage(feature, user_id, resolved, tokens_in, tokens_out, cost, elapsed_ms, False,
                        result.error, error_code=code, stop_reason=stop, **cache_kw)
        return result

    result.text = text
    result.success = True
    await log_usage(feature, user_id, resolved, tokens_in, tokens_out, cost, elapsed_ms, True,
                    stop_reason=stop, **cache_kw)
    return result


def _int_attr(obj, name: str) -> int:
    try:
        return int(getattr(obj, name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _history_messages(history: Optional[list]) -> list:
    """Giliran lama yang sah untuk API: hanya peran user/assistant berisi teks, diawali `user`.

    Giliran kosong dibuang; giliran pertama yang bukan `user` dilewati (API mewajibkan pesan
    pertama dari pengguna). Giliran berperan sama yang berurutan boleh (API menggabungkannya).
    """
    out = []
    for h in history or []:
        role = (h or {}).get("role")
        text = (h or {}).get("content")
        if role not in ("user", "assistant") or not isinstance(text, str) or not text.strip():
            continue
        if not out and role != "user":
            continue
        out.append({"role": role, "content": text})
    return out


# ── WS-C: High-level helpers ─────────────────────────────────────────────────
async def ai_complete(
    feature: str,
    system_message: str,
    user_message: str,
    tier: str = DEFAULT_TIER,
    user_id: Optional[str] = None,
    image_base64: Optional[str] = None,
    max_tokens: Optional[int] = None,
    session_id: Optional[str] = None,
    raise_on_error: bool = True,
) -> str:
    """Panggil AI dan kembalikan teks. Raise AIError (pesan ramah) bila gagal (default)."""
    res = await tracked_llm_call(
        feature=feature, user_id=user_id, model=tier,
        system_message=system_message, user_message=user_message,
        image_base64=image_base64, max_tokens=max_tokens, session_id=session_id,
    )
    if not res.success:
        if raise_on_error:
            raise AIError(res.error, over_budget=res.over_budget, code=res.error_code)
        return ""
    return res.text


def _extract_json(text: str):
    """Strip markdown fence & ekstrak objek/array JSON pertama; return parsed atau raise."""
    import json as _json
    clean = (text or "").strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean[:4].lower() == "json":
            clean = clean[4:]
        clean = clean.strip()
    try:
        return _json.loads(clean)
    except Exception:
        m = re.search(r"(\{.*\}|\[.*\])", clean, re.S)
        if m:
            return _json.loads(m.group(1))
        raise


def extract_json(text: str):
    """Versi publik `_extract_json` (raise ValueError/JSONDecodeError bila gagal)."""
    return _extract_json(text)


async def ai_json(
    feature: str,
    system_message: str,
    user_message: str,
    tier: str = DEFAULT_TIER,
    user_id: Optional[str] = None,
    image_base64: Optional[str] = None,
    max_tokens: Optional[int] = None,
    default=None,
):
    """Structured output: minta JSON valid, parse robust. Return `default` bila gagal (jika diberikan), else raise AIError."""
    sys_json = (system_message or "").rstrip()
    if "json" not in sys_json.lower():
        sys_json += " Always respond with a single valid JSON value only — no prose, no markdown fences."
    res = await tracked_llm_call(
        feature=feature, user_id=user_id, model=tier,
        system_message=sys_json, user_message=user_message,
        image_base64=image_base64, max_tokens=max_tokens,
    )
    if not res.success:
        if default is not None:
            return default
        raise AIError(res.error, over_budget=res.over_budget, code=res.error_code)
    try:
        return _extract_json(res.text)
    except Exception:
        if default is not None:
            return default
        raise AIError(code="bad_output")


async def get_usage_summary(days: int = 7) -> dict:
    """Get aggregated usage stats for last N days."""
    db = get_db()
    cutoff = (today_wib() - timedelta(days=days)).isoformat()

    # 2026-11-07: token cache + pencarian web ikut dijumlah (nama field sama dengan di log).
    extra_sums = {
        "cache_read_tokens": {"$sum": {"$ifNull": ["$cache_read_tokens", 0]}},
        "cache_write_tokens": {"$sum": {"$ifNull": ["$cache_write_tokens", 0]}},
        "web_search_requests": {"$sum": {"$ifNull": ["$web_search_requests", 0]}},
    }
    extra_keys = {k: 1 for k in extra_sums}

    # Overall totals
    overall = await db.rahaza_ai_usage_logs.aggregate([
        {"$match": {"date": {"$gte": cutoff}}},
        {"$group": {
            "_id": None,
            "total_calls": {"$sum": 1},
            "successful_calls": {"$sum": {"$cond": ["$success", 1, 0]}},
            "failed_calls": {"$sum": {"$cond": ["$success", 0, 1]}},
            "total_cost_usd": {"$sum": "$cost_usd"},
            "total_tokens": {"$sum": "$tokens_total"},
            "avg_latency_ms": {"$avg": "$latency_ms"},
            **extra_sums,
        }},
    ]).to_list(length=1)

    overall_stats = overall[0] if overall else {
        "total_calls": 0, "successful_calls": 0, "failed_calls": 0,
        "total_cost_usd": 0, "total_tokens": 0, "avg_latency_ms": 0,
    }
    overall_stats.pop("_id", None)
    for k in extra_sums:
        overall_stats[k] = int(overall_stats.get(k) or 0)

    # By feature
    by_feature = await db.rahaza_ai_usage_logs.aggregate([
        {"$match": {"date": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$feature",
            "calls": {"$sum": 1},
            "successful": {"$sum": {"$cond": ["$success", 1, 0]}},
            "failed": {"$sum": {"$cond": ["$success", 0, 1]}},
            "cost_usd": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$tokens_total"},
            "avg_latency_ms": {"$avg": "$latency_ms"},
            **extra_sums,
        }},
        {"$project": {
            "_id": 0, "feature": "$_id", "calls": 1, "successful": 1, "failed": 1,
            "cost_usd": {"$round": ["$cost_usd", 4]},
            "tokens": 1,
            "avg_latency_ms": {"$round": ["$avg_latency_ms", 0]},
            **extra_keys,
        }},
        {"$sort": {"cost_usd": -1}},
    ]).to_list(length=100)

    # By day
    by_day = await db.rahaza_ai_usage_logs.aggregate([
        {"$match": {"date": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$date",
            "calls": {"$sum": 1},
            "cost_usd": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$tokens_total"},
            **extra_sums,
        }},
        {"$project": {
            "_id": 0, "date": "$_id", "calls": 1,
            "cost_usd": {"$round": ["$cost_usd", 4]},
            "tokens": 1,
            **extra_keys,
        }},
        {"$sort": {"date": 1}},
    ]).to_list(length=days + 5)

    # 2026-11-02 (K29): grup Monitor AI per fitur + anggaran EFEKTIF dari setelan
    # (dulu angka env bawaan → "Monthly $100" tetap tampil walau admin mengubahnya).
    for row in by_feature:
        row["group"] = feature_group(row.get("feature"))
    return {
        "period_days": days,
        "from_date": cutoff,
        "to_date": today_wib().isoformat(),
        "overall": {
            **overall_stats,
            "total_cost_usd": round(overall_stats.get("total_cost_usd", 0), 4),
            "avg_latency_ms": round(overall_stats.get("avg_latency_ms", 0) or 0, 0),
        },
        "by_feature": by_feature,
        "by_day": by_day,
        "budgets": await effective_budgets(db),
    }


async def effective_budgets(db=None) -> dict:
    """Anggaran yang BENAR-BENAR dipakai `_check_budget` (setelan DB → env) + pemakaian bulan ini."""
    db = db if db is not None else get_db()
    s = await get_ai_settings(db)
    month_cost = await month_to_date_cost(db)
    monthly = float(s.get("monthly_budget_usd") or 0)
    return {
        "daily_usd": float(s.get("daily_budget_usd") or 0),
        "monthly_usd": monthly,
        "per_feature_daily_usd": float(s.get("per_feature_daily_usd") or 0),
        "month_cost_usd": round(month_cost, 4),
        "monthly_used_pct": round(month_cost / monthly * 100, 1) if monthly > 0 else 0.0,
    }


async def get_recent_logs(limit: int = 50, feature: Optional[str] = None) -> list:
    """Get recent usage log entries."""
    db = get_db()
    q = {}
    if feature:
        q["feature"] = feature
    logs = await db.rahaza_ai_usage_logs.find(q).sort("created_at", -1).to_list(length=limit)
    for log in logs:
        log.pop("_id", None)
    return logs
