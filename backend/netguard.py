"""Network egress guard — SSRF protection for user-supplied URL fetches.

Public, unauthenticated endpoints (e.g. word-art "from URL") fetch arbitrary
user URLs. Without validation that is a server-side request forgery hole: an
attacker can target localhost, the cloud metadata endpoint (169.254.169.254),
or other internal services. `safe_get` resolves the host, rejects any
non-public address, refuses redirects (which could bounce to an internal host),
and caps the response size.

Residual caveat: a determined DNS-rebinding attacker could flip the record
between the validation resolve and the request resolve. For a low-value
personal tool the validate-then-no-redirect approach blocks the realistic
attacks (direct internal URLs, metadata endpoint, redirect bypass); pin to the
resolved IP if this ever guards something sensitive.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import requests
from fastapi import HTTPException

MAX_FETCH_BYTES = 5 * 1024 * 1024  # 5 MB cap on a fetched URL body


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local      # 169.254.0.0/16 — incl. cloud metadata
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> None:
    """Raise HTTPException unless `url` is an http(s) URL whose host resolves
    only to public IP addresses."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise HTTPException(400, "url must be http(s)")
    host = p.hostname
    if not host:
        raise HTTPException(400, "url has no host")
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise HTTPException(400, "url host did not resolve")
    addrs = {info[4][0] for info in infos}
    if not addrs or not all(_is_public_ip(a) for a in addrs):
        raise HTTPException(400, "url resolves to a non-public address")


def safe_get(url: str, *, timeout: int = 15, max_bytes: int = MAX_FETCH_BYTES,
             headers: dict | None = None) -> str:
    """SSRF-guarded GET. Validates the target, refuses redirects, and streams
    the body with a hard size cap. Returns decoded text."""
    validate_public_url(url)
    with requests.get(url, timeout=timeout, headers=headers, stream=True,
                      allow_redirects=False) as r:
        if 300 <= r.status_code < 400:
            # A redirect could point at an internal host — don't follow it.
            raise HTTPException(400, "url redirected; refusing to follow")
        r.raise_for_status()
        total = 0
        chunks: list[bytes] = []
        for chunk in r.iter_content(8192):
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(413, "fetched document too large")
            chunks.append(chunk)
        body = b"".join(chunks)
        encoding = r.encoding or "utf-8"
    return body.decode(encoding, errors="ignore")
