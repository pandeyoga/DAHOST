"""AI service helpers — satu-satunya pintu route ke Claude (2026-11-02, No.60).

Public API (re-exports):
- ai_available(db=None) / ai_status(db=None) / require_ai(feature, ...)
- ai_text(feature, system, user, tier=...) / ai_json_call(...)   → raise AIError
- ai_http_error(err)   → HTTPException berpesan ramah
- call_claude(system, user, session_tag, db=None, tier=...)  → raise HTTPException
- cached_call_claude(db, ...)
- get_llm_key(db=None), LLMUnavailable, AIError
- SystemPrompts (constants)
- Privasi K27 / pembatas K28: Pseudonymizer, ai_json, strip_sensitive, mask_pii, redact,
  wrap_untrusted, with_untrusted_rule, pick_enum, clamp_number   (2026-11-02)
- Usulan AI K28: new_suggestion, decide_suggestion, SuggestionDecision, actor_label
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
from services.ai.privacy import (  # noqa: F401
    Pseudonymizer,
    ai_json,
    clamp_number,
    mask_pii,
    pick_enum,
    redact,
    strip_sensitive,
    with_untrusted_rule,
    wrap_untrusted,
)
from services.ai.suggestions import (  # noqa: F401
    SuggestionDecision,
    actor_label,
    decide_suggestion,
    new_suggestion,
)
