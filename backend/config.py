"""Environment config for the tools API. Loaded once at import."""
from __future__ import annotations

import os

from dotenv import load_dotenv

# On the droplet, systemd injects the env via EnvironmentFile=/opt/tools/tools.env.
# For local dev, fall back to a .env next to this file.
load_dotenv()

TOOLS_TOKEN: str = os.getenv("TOOLS_TOKEN", "")

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

ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://tools.sajivfrancis.com,http://localhost:4321",
    ).split(",")
    if o.strip()
]


def storage_configured() -> bool:
    return bool(DO_SPACES_KEY and DO_SPACES_SECRET and DO_SPACES_BUCKET)
