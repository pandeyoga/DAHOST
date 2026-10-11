"""Uji unit HERMETIK auth.verify_download_token (FASE 4 / T-22) — tanpa server, tanpa Mongo.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import jwt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import auth  # noqa: E402

USER = {"id": "u1", "email": "a@b.c", "role": "admin", "name": "A"}


def _session_token():
    return jwt.encode({**USER, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, auth.JWT_SECRET, algorithm="HS256")


def test_download_token_accepted_and_scoped():
    tok = auth.create_download_token(USER, resource="csv-a")
    assert auth.verify_download_token(tok)["id"] == "u1"
    assert auth.verify_download_token(tok, resource="csv-a") is not None
    assert auth.verify_download_token(tok, resource="csv-b") is None
    assert auth.verify_download_token(auth.create_download_token(USER), resource="apa-saja") is not None


def test_download_token_rejected_as_session():
    assert auth.verify_token_str(auth.create_download_token(USER)) is None


def test_session_token_in_query_follows_transition_flag(monkeypatch):
    tok = _session_token()
    monkeypatch.setenv("ALLOW_SESSION_TOKEN_IN_QUERY", "1")
    assert auth.verify_download_token(tok)["id"] == "u1"
    monkeypatch.setenv("ALLOW_SESSION_TOKEN_IN_QUERY", "0")
    assert auth.verify_download_token(tok) is None


def test_garbage_and_expired_tokens_rejected():
    assert auth.verify_download_token("bukan.token.sah") is None
    assert auth.verify_download_token("") is None
    expired = jwt.encode({**USER, "aud": "download", "resource": "*",
                          "exp": datetime.now(timezone.utc) - timedelta(seconds=5)}, auth.JWT_SECRET, algorithm="HS256")
    assert auth.verify_download_token(expired) is None
