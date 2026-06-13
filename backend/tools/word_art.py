"""Tool 1 — Word Art / Cloud generator.

Text (paste / URL / file) → styled word-cloud PNG → DO Spaces → public URL.
Synchronous in V1 (render is ~1-3s); the async/queue path arrives with the
video tool. Output feeds blog/whitepaper banners on sajivfrancis.com.
"""
from __future__ import annotations

import io
import re
from typing import Optional

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, ImageDraw
from wordcloud import STOPWORDS, WordCloud

import config
import storage

router = APIRouter()

STOP_WORDS = set(STOPWORDS) | {
    "the", "and", "for", "that", "this", "with", "from", "are", "was", "will",
    "https", "http", "www", "com",
}

PALETTE_MAP: dict[str, list[str]] = {
    "midnight": ["#0f172a", "#6366f1", "#a5b4fc", "#e0e7ff"],
    "carbon": ["#18181b", "#71717a", "#d4d4d8", "#f4f4f5"],
    "forest": ["#052e16", "#16a34a", "#86efac", "#f0fdf4"],
    "ember": ["#1c0a00", "#c2410c", "#fb923c", "#fff7ed"],
    "ocean": ["#0c1445", "#0369a1", "#38bdf8", "#f0f9ff"],
}

# Shape → aspect ratio (width / height), mirroring the frontend SHAPES.
ASPECT = {"rectangle": 2.4, "circle": 1.0, "arch": 1.6, "diamond": 1.0}

MAX_W = 2400  # safety clamp


# ─── Text extraction ─────────────────────────────────────────────────────────
def extract_text(source_type: str, *, content: str, url: str, file: Optional[UploadFile]) -> str:
    if source_type == "text":
        return content or ""
    if source_type == "url":
        if not url:
            raise HTTPException(400, "url required")
        import requests
        from bs4 import BeautifulSoup

        r = requests.get(url, timeout=15, headers={"User-Agent": "tools.sajivfrancis.com"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)
    if source_type == "file":
        if file is None:
            raise HTTPException(400, "file required")
        raw = file.file.read()
        name = (file.filename or "").lower()
        if name.endswith(".docx"):
            import docx  # python-docx

            d = docx.Document(io.BytesIO(raw))
            return "\n".join(p.text for p in d.paragraphs)
        if name.endswith(".pdf"):
            import fitz  # PyMuPDF

            doc = fitz.open(stream=raw, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        # .txt / .md / anything else → decode as text
        return raw.decode("utf-8", errors="ignore")
    raise HTTPException(400, f"unknown source_type: {source_type}")


# ─── Mask + render ───────────────────────────────────────────────────────────
def generate_mask(shape: str, width: int, height: int) -> np.ndarray | None:
    """White (255) = masked out, black (0) = drawable. Rectangle → None."""
    if shape == "rectangle":
        return None
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    pad = int(min(width, height) * 0.04)
    if shape == "circle":
        d.ellipse([pad, pad, width - pad, height - pad], fill=0)
    elif shape == "diamond":
        cx, cy = width / 2, height / 2
        d.polygon([(cx, pad), (width - pad, cy), (cx, height - pad), (pad, cy)], fill=0)
    elif shape == "arch":
        # rounded top + flat-ish bottom
        d.pieslice([pad, pad, width - pad, height + height], 180, 360, fill=0)
        d.rectangle([pad, height // 2, width - pad, height - pad], fill=0)
    return np.array(img)


def _color_func(palette_id: str):
    colors = PALETTE_MAP[palette_id][1:]  # drop background

    def fn(word, *args, **kwargs):
        return colors[hash(word) % len(colors)]

    return fn


def render(text: str, shape: str, style: str, palette: str,
           width: int = 1920, height: int | None = None) -> bytes:
    if palette not in PALETTE_MAP:
        raise HTTPException(400, f"unknown palette: {palette}")
    width = max(320, min(int(width), MAX_W))
    if height is None:
        height = round(width / ASPECT.get(shape, 2.4))
    height = max(240, min(int(height), MAX_W))

    if not text or not text.strip():
        raise HTTPException(400, "no text to render")

    wc = WordCloud(
        width=width,
        height=height,
        background_color=PALETTE_MAP[palette][0],
        mask=generate_mask(shape, width, height),
        color_func=_color_func(palette),
        prefer_horizontal=1.0 if style == "banner" else 0.72,
        max_words=60,
        collocations=False,
        stopwords=STOP_WORDS,
    ).generate(re.sub(r"\s+", " ", text))

    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    return buf.getvalue()


# ─── Route ───────────────────────────────────────────────────────────────────
@router.post("/generate")
async def generate(
    source_type: str = Form("text"),
    content: str = Form(""),
    url: str = Form(""),
    shape: str = Form("rectangle"),
    style: str = Form("cloud"),
    palette: str = Form("midnight"),
    width: int = Form(1920),
    file: Optional[UploadFile] = File(None),
):
    """Synchronous: extract → render → upload → return public URL."""
    text = extract_text(source_type, content=content, url=url, file=file)
    png = render(text, shape, style, palette, width=width)
    if not config.storage_configured():
        raise HTTPException(503, "storage not configured (DO_SPACES_* env missing)")
    return {"url": storage.upload_bytes(png, tool="word-art", ext="png",
                                        content_type="image/png")}
