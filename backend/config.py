"""Environment config for the tools API. Loaded once at import."""
from __future__ import annotations

import os

from dotenv import load_dotenv

# On the droplet, systemd injects the env via EnvironmentFile=/opt/tools/tools.env.
# For local dev, fall back to a .env next to this file.
load_dotenv()

TOOLS_TOKEN: str = os.getenv("TOOLS_TOKEN", "")

# Claude — for the Map Maker auto-extract (text/url/doc/image → Mermaid). Same
# key the chat uses; set ANTHROPIC_MODEL=claude-sonnet-4-6 in tools.env to match
# the chat (default is the higher-quality/cost claude-opus-4-8).
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")

DO_SPACES_KEY: str = os.getenv("DO_SPACES_KEY", "")
DO_SPACES_SECRET: str = os.getenv("DO_SPACES_SECRET", "")
DO_SPACES_BUCKET: str = os.getenv("DO_SPACES_BUCKET", "sajivfrancis-tools")
DO_SPACES_REGION: str = os.getenv("DO_SPACES_REGION", "sfo3")
DO_SPACES_ENDPOINT: str = os.getenv(
    "DO_SPACES_ENDPOINT", f"https://{DO_SPACES_REGION}.digitaloceanspaces.com"
)
# Public base for returned URLs. Defaults to the origin; set to the CDN endpoint
# or a custom subdomain to serve cached.
DO_SPACES_CDN_BASE: str = os.getenv("DO_SPACES_CDN_BASE", "").rstrip("/")

ASSET_PREFIX: str = "tools"  # all objects land under tools/… (lifecycle-scoped)

# Publish-to-site (owner-only): commit a generated asset into the main site repo
# as a permanent, version-controlled banner. Fine-grained GitHub PAT scoped to
# ONLY the site repo with contents:write.
SITE_GITHUB_TOKEN: str = os.getenv("SITE_GITHUB_TOKEN", "")
SITE_REPO: str = os.getenv("SITE_REPO", "sfrancis2017/sajivfrancis.github.io")
SITE_BRANCH: str = os.getenv("SITE_BRANCH", "master")
BANNER_DIR: str = os.getenv("BANNER_DIR", "public/img/banners")


def github_configured() -> bool:
    return bool(SITE_GITHUB_TOKEN and SITE_REPO)

# Public tools (e.g. the Mermaid→draw.io converter) are called cross-origin from
# the chat and main-site front-ends, so those origins must be whitelisted here in
# addition to the tools site itself. Keep in sync with the chat worker's CORS
# allowlist (chat / sajivfrancis.com / www).
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://tools.sajivfrancis.com,"
        "https://chat.sajivfrancis.com,"
        "https://sajivfrancis.com,"
        "https://www.sajivfrancis.com,"
        "http://localhost:4321",
    ).split(",")
    if o.strip()
]


def storage_configured() -> bool:
    return bool(DO_SPACES_KEY and DO_SPACES_SECRET and DO_SPACES_BUCKET)
