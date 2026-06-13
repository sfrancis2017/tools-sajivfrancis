"""Owner-mode auth — a bearer token DISTINCT from the chat's CHAT_TOKEN.

Same mechanism as the chat: the frontend stores TOOLS_TOKEN in
localStorage['tools-access-token'] and sends `Authorization: Bearer <token>`.
The split keeps a tools compromise from touching the chat.

V1 tools (Word Art, Diff) are public-safe and don't require owner. `require_owner`
is here for the LLM/publish tools that come later.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

import config


def is_owner(authorization: str | None) -> bool:
    if not config.TOOLS_TOKEN or not authorization:
        return False
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    # Constant-time compare to avoid leaking the token via timing.
    return hmac.compare_digest(token, config.TOOLS_TOKEN)


def current_is_owner(authorization: str | None = Header(default=None)) -> bool:
    """FastAPI dependency: resolves owner/public without rejecting."""
    return is_owner(authorization)


def require_owner(authorization: str | None = Header(default=None)) -> bool:
    """FastAPI dependency: 401 unless a valid owner token is present."""
    if not is_owner(authorization):
        raise HTTPException(status_code=401, detail="owner token required")
    return True
