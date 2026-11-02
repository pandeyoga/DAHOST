"""AI service helpers — satu-satunya pintu route ke Claude (2026-11-02, No.60).

Public API (re-exports):
- ai_available(db=None) / ai_status(db=None) / require_ai(feature, ...)
- ai_text(feature, system, user, tier=...) / ai_json_call(...)   → raise AIError
- ai_http_error(err)   → HTTPException berpesan ramah
- call_claude(system, user, session_tag, db=None, tier=...)  → raise HTTPException
- cached_call_claude(db, ...)
- get_llm_key(db=None), LLMUnavailable, AIError
- SystemPrompts (constants)
"""
from services.ai.llm_client import (  # noqa: F401
    AIError,
    LLMUnavailable,
    ai_available,
    ai_status,
    require_ai,
    ai_http_error,
    ai_text,
    ai_json_call,
    call_claude,
    cached_call_claude,
    get_llm_key,
    friendly_error,
)
from services.ai.prompt_templates import SystemPrompts  # noqa: F401
