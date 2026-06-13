"""Map Maker (auto-extract) — turn a URL, document, or image into a
mind/concept/system map via Claude. Output is Mermaid that renders in the tool,
the docs site, and the chat.

The deterministic outline→Mermaid mode is client-side (in the Astro page); THIS
endpoint is the LLM/vision path. Owner-only — it spends Anthropic tokens.
"""
from __future__ import annotations

import base64
from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import config
from auth import require_owner
from tools.word_art import extract_text  # reuse url / docx / pdf / txt extraction

router = APIRouter()

# model key -> (mermaid diagram keyword, human description)
MODELS = {
    "mind": ("mindmap", "a mind map — a radial brainstorm branching out from one center idea"),
    "concept": ("flowchart", "a concept map — nodes connected by LABELED relationship edges"),
    "system": ("flowchart", "a system map — components grouped into subgraphs with directed flow edges"),
}

SYNTAX = {
    "mind": (
        "Use Mermaid `mindmap` syntax: first line `mindmap`, then the root as "
        "`root((Center))`, then child nodes indented two spaces per level."
    ),
    "concept": (
        'Use Mermaid `flowchart TD` syntax. Declare nodes as `id["Label"]` and connect '
        "them with LABELED edges `a -->|relationship| b`. Every edge must carry a short "
        "relationship label (that is what makes it a concept map)."
    ),
    "system": (
        'Use Mermaid `flowchart TD` syntax. Group related components into '
        '`subgraph g1["Group"] ... end` blocks, then connect components with `a --> b` edges.'
    ),
}

MAX_INPUT_CHARS = 24000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _client() -> anthropic.Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(503, "map generation not configured (ANTHROPIC_API_KEY missing)")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _system_prompt(model: str) -> str:
    _, desc = MODELS[model]
    return (
        f"You convert the user's input into {desc}, expressed as Mermaid.\n"
        f"{SYNTAX[model]}\n"
        "Capture the important structure, not every detail: aim for ~10-25 nodes. "
        "Sanitize labels — no unescaped double quotes, brackets, or pipes inside them. "
        "Respond with ONLY the Mermaid source: no code fences, no preamble, no commentary."
    )


def _clean_mermaid(text: str, model: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # drop the opening fence (+ optional language tag) and any closing fence
        t = t[3:]
        if "\n" in t:
            first, rest = t.split("\n", 1)
            if first.strip().lower() in ("", "mermaid"):
                t = rest
        t = t.split("```", 1)[0].strip()
    if not t.lower().startswith(("mindmap", "flowchart", "graph")):
        kw = MODELS[model][0]
        t = f"{kw}\n{t}" if kw == "mindmap" else f"{kw} TD\n{t}"
    return t.strip()


def _generate(system: str, user_content) -> str:
    # Opus 4.8: no temperature/top_p (they 400); thinking omitted (simple transform).
    resp = _client().messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    if resp.stop_reason == "refusal":
        raise HTTPException(422, "the model declined to generate a map for this input")
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    if not text.strip():
        raise HTTPException(502, "empty response from model")
    return text


@router.post("/generate", dependencies=[Depends(require_owner)])
async def generate(
    model: str = Form("mind"),
    source_type: str = Form("text"),
    content: str = Form(""),
    url: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    if model not in MODELS:
        raise HTTPException(400, f"unknown model: {model}")
    system = _system_prompt(model)

    if source_type == "image":
        if file is None:
            raise HTTPException(400, "image file required")
        raw = file.file.read()
        media = file.content_type if file.content_type in IMAGE_TYPES else "image/png"
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": media,
                                          "data": base64.b64encode(raw).decode()}},
            {"type": "text", "text": "Convert the structure shown in this image into the requested Mermaid map."},
        ]
    else:
        text = extract_text(source_type, content=content, url=url, file=file)
        if not text.strip():
            raise HTTPException(400, "no text to convert")
        user_content = (
            "Convert the following into the requested Mermaid map:\n\n"
            + text[:MAX_INPUT_CHARS]
        )

    return {"mermaid": _clean_mermaid(_generate(system, user_content), model)}
