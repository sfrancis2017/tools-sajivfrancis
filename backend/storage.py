"""DO Spaces (S3-compatible) upload helper. Returns public, embeddable URLs.

Objects are written under the `tools/` prefix with `public-read` ACL so they can
be referenced directly from <img>/<video>. A 7-day lifecycle rule on the bucket
(configured once in the DO control panel) expires the ephemeral ones.
"""
from __future__ import annotations

import io
import uuid

import boto3
from botocore.client import Config

import config

_client = None


def _s3():
    global _client
    if _client is None:
        _client = boto3.session.Session().client(
            "s3",
            region_name=config.DO_SPACES_REGION,
            endpoint_url=config.DO_SPACES_ENDPOINT,
            aws_access_key_id=config.DO_SPACES_KEY,
            aws_secret_access_key=config.DO_SPACES_SECRET,
            config=Config(s3={"addressing_style": "virtual"}),
        )
    return _client


def public_url(key: str) -> str:
    if config.DO_SPACES_CDN_BASE:
        return f"{config.DO_SPACES_CDN_BASE}/{key}"
    # Virtual-hosted origin URL: https://<bucket>.<region>.digitaloceanspaces.com/<key>
    host = config.DO_SPACES_ENDPOINT.replace("https://", "")
    return f"https://{config.DO_SPACES_BUCKET}.{host}/{key}"


def upload_bytes(
    data: bytes,
    *,
    tool: str,
    ext: str,
    content_type: str,
) -> str:
    """Upload bytes under tools/<tool>/<uuid>.<ext>; return the public URL."""
    key = f"{config.ASSET_PREFIX}/{tool}/{uuid.uuid4().hex}.{ext.lstrip('.')}"
    _s3().upload_fileobj(
        io.BytesIO(data),
        config.DO_SPACES_BUCKET,
        key,
        ExtraArgs={"ACL": "public-read", "ContentType": content_type},
    )
    return public_url(key)
