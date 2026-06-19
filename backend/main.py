"""tools.sajivfrancis.com API — FastAPI app.

Runs on the droplet (systemd: tools-api.service) on :8000, behind the same
Cloudflare Tunnel pattern as retrieve.py, routed at tools.sajivfrancis.com/api/*.
Independent of the chat service (retrieve.py) — separate process, separate token.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from tools import chart_gen, diff_tool, drawio, map_gen, publish, word_art

app = FastAPI(title="tools.sajivfrancis.com API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "storage": config.storage_configured()}


# V1 tools
app.include_router(word_art.router, prefix="/api/word-art", tags=["word-art"])
app.include_router(diff_tool.router, prefix="/api/diff", tags=["diff"])
# Owner-only: publish a generated asset into the site repo as a permanent banner
app.include_router(publish.router, prefix="/api/publish", tags=["publish"])
# Owner-only: turn a URL/document/image into a Mermaid mind/concept/system map
app.include_router(map_gen.router, prefix="/api/map", tags=["map"])
# Public: convert any Mermaid flowchart/mindmap into an editable .drawio file
app.include_router(drawio.router, prefix="/api/convert", tags=["convert"])
# Owner-only: render Plotly/Altair/Matplotlib/Seaborn specs → HTML or PNG/SVG.
# The chat reaches this via the chat worker proxy (CHAT_TOKEN→TOOLS_TOKEN), so the
# token never hits the browser and there's no public compute endpoint.
app.include_router(chart_gen.router, prefix="/api/chart", tags=["chart"])
