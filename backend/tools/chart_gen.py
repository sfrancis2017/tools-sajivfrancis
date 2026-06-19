"""Tool — Chart generator.

Render a chart spec (Plotly / Altair / Matplotlib / Seaborn) to inline HTML or a
static PNG/SVG, and return either the HTML string or a DO Spaces CDN URL.

Owner-only: the chat reaches /api/chart/render through the chat worker proxy
(browser → chat worker [CHAT_TOKEN] → here [TOOLS_TOKEN]). The token never reaches
the browser and there is no public compute endpoint — matplotlib/seaborn/kaleido
rendering is CPU/RAM-heavy and shares the droplet with the RAG retrieve service.

Library responsibilities (mirrors the chat's client-side split):
  - plotly / altair / chartjs  render CLIENT-SIDE in the chat (CDN). The backend
    still supports plotly/altair here for the tools page + PDF-export fallback.
  - matplotlib / seaborn  have no JS runtime — they MUST render server-side (PNG).

Lazy-imports each library inside its branch (like word_art does for docx/fitz) so
a missing/uninstalled engine fails ONLY that library, not the whole tools app.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config
import storage
from auth import require_owner

router = APIRouter()

# Renders run in a fresh one-shot SUBPROCESS (`python -m tools.chart_gen`), never in
# uvicorn's request path. matplotlib's Agg Figure.savefig inside uvicorn's sync-endpoint
# threadpool trips signal/threading machinery that gracefully shuts the whole server
# down — yet a standalone process renders identically with zero issues (verified). A
# subprocess is the clean, isolated path: no threadpool, and (unlike a spawn
# ProcessPoolExecutor) no re-import of uvicorn's entry module. ~2-3s/render is fine here.


def _render_dispatch(library: str, spec: dict, spec_str: str, output: str) -> dict:
    if library == "plotly":
        return _render_plotly(spec_str, output)
    if library == "altair":
        return _render_altair(spec, spec_str, output)
    if library in ("matplotlib", "seaborn"):
        return _render_matplotlib(spec, library, output)
    raise ValueError(f"unsupported library: {library!r}")

# Bound inputs even though the endpoint is owner-only: a runaway spec can OOM the
# shared droplet. Caps are generous for real charts, hostile to abuse.
MAX_SPEC_BYTES = 256_000        # serialized spec size ceiling
MAX_MPL_POINTS = 20_000         # total data points for matplotlib/seaborn builders

Library = Literal["plotly", "altair", "matplotlib", "seaborn"]
Output = Literal["html", "png", "svg"]


class ChartRequest(BaseModel):
    library: Library
    spec: dict[str, Any]
    output: Output = "png"
    title: Optional[str] = None


def _guard_spec_size(spec: dict[str, Any]) -> str:
    s = json.dumps(spec)
    if len(s.encode("utf-8")) > MAX_SPEC_BYTES:
        raise HTTPException(413, f"spec exceeds {MAX_SPEC_BYTES} bytes")
    return s


def _image_result(data: bytes, ext: str, content_type: str) -> dict:
    if not config.storage_configured():
        raise HTTPException(503, "storage not configured (DO_SPACES_* env missing)")
    return {"type": "image", "url": storage.upload_bytes(
        data, tool="charts", ext=ext, content_type=content_type)}


# ─── Plotly ──────────────────────────────────────────────────────────────────
def _render_plotly(spec_str: str, output: Output) -> dict:
    import plotly.io as pio  # lazy

    fig = pio.from_json(spec_str)
    if output == "html":
        html = pio.to_html(fig, full_html=False, include_plotlyjs="cdn")
        return {"type": "html", "content": html}
    if output == "svg":
        return _image_result(pio.to_image(fig, format="svg"), "svg", "image/svg+xml")
    return _image_result(pio.to_image(fig, format="png", scale=2), "png", "image/png")


# ─── Altair / Vega-Lite ──────────────────────────────────────────────────────
def _render_altair(spec: dict, spec_str: str, output: Output) -> dict:
    import altair as alt  # lazy

    chart = alt.Chart.from_dict(spec)
    if output == "html":
        return {"type": "html", "content": chart.to_html()}
    import vl_convert as vlc  # lazy (vl-convert-python)
    if output == "svg":
        return _image_result(vlc.vegalite_to_svg(spec_str).encode("utf-8"),
                             "svg", "image/svg+xml")
    return _image_result(vlc.vegalite_to_png(spec_str, scale=2.0), "png", "image/png")


# ─── Matplotlib / Seaborn (programmatic; PNG only) ───────────────────────────
def _count_points(data: dict) -> int:
    n = 0
    for v in data.values():
        if isinstance(v, list):
            n += sum(len(r) if isinstance(r, list) else 1 for r in v)
    return n


def _render_matplotlib(spec: dict, library: str, output: Output) -> dict:
    # THREAD-SAFE rendering: use the Figure API directly, NOT pyplot. FastAPI runs
    # sync endpoints in a threadpool, and pyplot's global figure manager is not
    # thread-safe — plt.subplots() off the main thread can hard-abort the whole
    # uvicorn worker (bypassing try/except, looking like a graceful restart).
    # Figure + the implicit Agg canvas use zero global state and are thread-safe.
    import matplotlib  # lazy — runs in the render child process's MAIN thread
    matplotlib.use("Agg")  # safe here: child main thread, not uvicorn's threadpool
    from matplotlib.figure import Figure

    chart_type = spec.get("chart_type")
    data = spec.get("data") or {}
    kwargs = spec.get("kwargs") or {}
    if _count_points(data) > MAX_MPL_POINTS:
        raise HTTPException(413, f"data exceeds {MAX_MPL_POINTS} points")

    if library == "seaborn":
        import seaborn as sns  # lazy — sets global rcParams (no figure ops)
        sns.set_theme(style=kwargs.get("style", "whitegrid"))

    figsize = kwargs.get("figsize", [8, 5])
    fig = Figure(figsize=(figsize[0], figsize[1]))
    ax = fig.subplots()

    if chart_type == "bar":
        x, y = data.get("x", []), data.get("y", [])
        if kwargs.get("horizontal"):
            ax.barh(x, y, color=kwargs.get("color"))
        else:
            ax.bar(x, y, color=kwargs.get("color"))
    elif chart_type == "line":
        series = data.get("series")
        if series:
            for s in series:
                ax.plot(s.get("x", []), s.get("y", []), label=s.get("name"))
            ax.legend()
        else:
            ax.plot(data.get("x", []), data.get("y", []), color=kwargs.get("color"))
    elif chart_type == "scatter":
        ax.scatter(data.get("x", []), data.get("y", []), color=kwargs.get("color"))
    elif chart_type == "heatmap":
        z = data.get("z") or data.get("matrix") or []
        xl, yl = data.get("x"), data.get("y")
        if library == "seaborn":
            import seaborn as sns
            sns.heatmap(z, ax=ax, cmap=kwargs.get("cmap", "viridis"),
                        xticklabels=xl or "auto", yticklabels=yl or "auto",
                        annot=kwargs.get("annot", False))
        else:
            im = ax.imshow(z, cmap=kwargs.get("cmap", "viridis"), aspect="auto")
            fig.colorbar(im, ax=ax)
            if xl:
                ax.set_xticks(range(len(xl))); ax.set_xticklabels(xl)
            if yl:
                ax.set_yticks(range(len(yl))); ax.set_yticklabels(yl)
    else:
        raise HTTPException(400, f"unsupported chart_type: {chart_type!r}")

    if kwargs.get("title") or spec.get("title"):
        ax.set_title(kwargs.get("title") or spec.get("title"))
    if kwargs.get("xlabel"):
        ax.set_xlabel(kwargs["xlabel"])
    if kwargs.get("ylabel"):
        ax.set_ylabel(kwargs["ylabel"])
    fig.tight_layout()

    buf = io.BytesIO()
    fmt = "svg" if output == "svg" else "png"
    fig.savefig(buf, format=fmt, dpi=150, bbox_inches="tight")
    ext = "svg" if output == "svg" else "png"
    ctype = "image/svg+xml" if output == "svg" else "image/png"
    return _image_result(buf.getvalue(), ext, ctype)


# ─── Routes ──────────────────────────────────────────────────────────────────
@router.post("/render")
async def render_chart(req: ChartRequest, _: bool = Depends(require_owner)):
    """Render a chart spec → {"type":"html","content":...} or {"type":"image","url":...}.
    Shelled out to a one-shot subprocess so the render never touches uvicorn's thread."""
    _guard_spec_size(req.spec)
    payload = json.dumps({"library": req.library, "spec": req.spec, "output": req.output})
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tools.chart_gen",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, errb = await asyncio.wait_for(proc.communicate(payload.encode()), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(504, "chart render timed out")
    if not out:
        raise HTTPException(400, f"render failed: {(errb or b'').decode()[:300] or 'no output'}")
    try:
        result = json.loads(out.decode())
    except Exception:
        raise HTTPException(400, f"render failed: {(errb or b'').decode()[:300] or 'bad output'}")
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(int(result.get("status", 400)), str(result["error"]))
    return result


@router.get("/types")
def chart_types():
    """Capability list for a picker UI. Public — no compute, no secrets."""
    return {
        "libraries": {
            "plotly": {"outputs": ["html", "png", "svg"],
                       "chart_types": ["bar", "line", "scatter", "pie", "sankey",
                                       "treemap", "heatmap", "box", "radar"],
                       "render": "client-or-server"},
            "altair": {"outputs": ["html", "png", "svg"],
                       "chart_types": ["bar", "line", "point", "area", "rect"],
                       "render": "client-or-server"},
            "matplotlib": {"outputs": ["png", "svg"],
                           "chart_types": ["bar", "line", "scatter", "heatmap"],
                           "render": "server"},
            "seaborn": {"outputs": ["png", "svg"],
                        "chart_types": ["bar", "line", "scatter", "heatmap"],
                        "render": "server"},
        }
    }


# ─── Subprocess entry ────────────────────────────────────────────────────────
# `python -m tools.chart_gen`: read a JSON request {library, spec, output} from stdin,
# render in this fresh process's main thread, write the result JSON to stdout. This is
# the isolated path the endpoint shells out to — guarded, so a normal import (uvicorn)
# never runs it.
if __name__ == "__main__":
    try:
        _body = json.loads(sys.stdin.read() or "{}")
        _spec = _body.get("spec") or {}
        _result = _render_dispatch(
            _body.get("library", ""), _spec, json.dumps(_spec), _body.get("output", "png"))
        sys.stdout.write(json.dumps(_result))
    except HTTPException as _e:
        sys.stdout.write(json.dumps({"error": str(_e.detail), "status": _e.status_code}))
    except Exception as _e:
        sys.stdout.write(json.dumps({"error": f"render failed: {_e}", "status": 400}))
