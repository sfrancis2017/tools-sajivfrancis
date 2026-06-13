# tools.sajivfrancis.com — Python Tool Suite (V1 design)

Status: **in build** (branch `feat/tools-v1-scaffold`)
Source brief: `Build Prompt: tools.sajivfrancis.com — Python Tool Suite` + `word-art-generator.jsx`

This doc records the **locked decisions** and how they differ from the build brief,
so the suite reuses the existing ecosystem instead of standing up parallel infra.

## Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Backend | One **FastAPI** service on the existing droplet (`164.92.104.226`), new port, behind the same **Cloudflare Tunnel** pattern as `retrieve.py`, routed at `tools.sajivfrancis.com/api/*` | Droplet is **16 GB / 4 vCPU** (resized; the `1gb` in the hostname is stale) — plenty for FastAPI + Postgres + video |
| Droplet | **Single droplet**, tools run as their **own systemd unit** | Service isolation: a tools crash/OOM never touches the chat (`retrieve.py`) |
| Auth | **Separate `TOOLS_TOKEN`** (same bearer mechanism as the chat, distinct secret; `localStorage['tools-access-token']`) | Blast-radius isolation — a tools leak must not compromise the chat; independent rotation |
| Storage | **DO Space `sajivfrancis-tools`** (sfo3), `tools/` prefix, **7-day lifecycle**, per-object `public-read`, **CDN on**. Scoped R/W key only | Isolated from `sajivfrancis-backups`; public assets embeddable |
| Queue | **None in V1** — Word Art + Diff are synchronous. Add **`rq` + Redis** only when the **video** tool lands | Avoid premature BullMQ/Redis |
| Frontend | **Astro islands** (matches docs + main site); React island only where needed (Word Art canvas) | Stack consistency; keep existing static tools intact |
| RAG chat (brief Tool 6) | **Reuse the existing `chat.sajivfrancis.com`** (already embedded via launcher) | Do not rebuild the `personal-chat` RAG stack |

## Architecture

```
Browser (tools.sajivfrancis.com, Astro)
  └─ owner mode: localStorage['tools-access-token'] → Authorization: Bearer
        │
        ▼  /api/*  (Cloudflare → Tunnel)
  FastAPI tools service (droplet :8000, systemd: tools-api.service)
        ├─ tools/word_art.py   → render PNG → DO Spaces → public URL
        ├─ tools/diff_tool.py  → difflib (sync)
        └─ storage.py (boto3 → DO Space sajivfrancis-tools)
```

The chat worker and `retrieve.py` are **untouched**.

## Output integration (writing / docs / whitepaper, owner mode)

Two asset tiers — durable embedded assets never depend on Spaces longevity:

- **Ephemeral** (previews, un-attached renders): DO Spaces, 7-day TTL.
- **Published** (a banner attached to a post/doc): **committed into the site repo**
  (`sajivfrancis.github.io` / `docs` `public/`) and served by the site's own Cloudflare.

Owner-mode "publish-to-site" (v2) extends the chat worker's existing publish-to-docs
GitHub pipeline. **Deferred past V1** — V1 returns a Spaces URL the owner pastes into
post frontmatter; the one-click commit comes later (needs a tools-scoped GitHub token,
separate from the chat's `DOCS_GITHUB_TOKEN`).

## V1 scope (this slice)

1. **Scaffold** — FastAPI skeleton, config, DO Spaces storage, `TOOLS_TOKEN` auth dep, systemd + tunnel notes. ✅ (backend/)
2. **Word Art** — backend render → Spaces → URL; Astro page + React island (reference component, single-word bug fixed: init offscreen canvas after mount, not in `useMemo`).
3. **Diff** — mostly client-side; backend endpoint for large inputs / `.diff` export.

Out of V1: video (Tool 3), whitepaper editor (Tool 2), graphviz (Tool 4), prompt-gen (Tool 7), publish-to-site one-click.

## Build / deploy notes

- Backend deploys to the droplet by **scp** (same as `retrieve.py`); runs under `systemd` (`tools-api.service`) with `EnvironmentFile=/opt/tools/tools.env` (chmod 600).
- Cloudflare Tunnel maps `tools.sajivfrancis.com/api/*` → `localhost:8000`.
- Secrets live ONLY in `/opt/tools/tools.env` on the droplet — never in the repo.
