"""Tool 5 — Diff. Mostly a client-side concern; this endpoint covers large
inputs and `.diff` patch generation. Pure stdlib, no storage, no auth."""
from __future__ import annotations

import difflib

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()

# Public, unauthenticated endpoint. difflib.ndiff is ~O(n²) on the line count,
# so bound each side to keep a malicious payload from exhausting CPU/memory.
_MAX_DIFF_CHARS = 1_000_000  # 1 MB per side


class DiffRequest(BaseModel):
    original: str = Field(max_length=_MAX_DIFF_CHARS)
    modified: str = Field(max_length=_MAX_DIFF_CHARS)
    mode: str = "unified"  # unified | html
    context: int = Field(default=3, ge=0, le=100)


class DiffStats(BaseModel):
    added: int
    removed: int


def _stats(original: str, modified: str) -> DiffStats:
    added = removed = 0
    for line in difflib.ndiff(original.splitlines(), modified.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return DiffStats(added=added, removed=removed)


def compute_diff(original: str, modified: str, mode: str = "unified", context: int = 3) -> str:
    o, m = original.splitlines(), modified.splitlines()
    if mode == "html":
        return difflib.HtmlDiff().make_table(o, m, "Original", "Modified")
    return "\n".join(
        difflib.unified_diff(o, m, "original", "modified", lineterm="", n=context)
    )


@router.post("")
def diff(req: DiffRequest):
    return {
        "diff_output": compute_diff(req.original, req.modified, req.mode, req.context),
        "stats": _stats(req.original, req.modified).model_dump(),
    }
