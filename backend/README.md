# tools API (backend)

FastAPI service for tools.sajivfrancis.com. V1 tools: **Word Art**, **Diff**.
Independent of the chat (`retrieve.py`) — own process, own `TOOLS_TOKEN`.

## Local dev (Mac)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill TOOLS_TOKEN + DO_SPACES_* (do NOT commit)
uvicorn main:app --reload --port 8000
# health: curl localhost:8000/api/health
```

## Deploy to the droplet (same pattern as retrieve.py — scp, no git on the box)

```bash
# 1. Copy code from the Mac
ssh root@164.92.104.226 'mkdir -p /opt/tools'
scp -r backend/* root@164.92.104.226:/opt/tools/

# 2. On the droplet: venv + deps (wordcloud/matplotlib pull in numpy/Pillow)
ssh root@164.92.104.226
cd /opt/tools
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

# 3. Secrets — chmod 600, never in the repo
umask 077
cat > /opt/tools/tools.env <<'EOF'
TOOLS_TOKEN=<openssl rand -hex 32>
DO_SPACES_KEY=<scoped key>
DO_SPACES_SECRET=<scoped secret>
DO_SPACES_BUCKET=sajivfrancis-tools
DO_SPACES_REGION=sfo3
DO_SPACES_ENDPOINT=https://sfo3.digitaloceanspaces.com
DO_SPACES_CDN_BASE=
ALLOWED_ORIGINS=https://tools.sajivfrancis.com
EOF
chmod 600 /opt/tools/tools.env
```

### systemd unit  `/etc/systemd/system/tools-api.service`
```ini
[Unit]
Description=tools.sajivfrancis.com API
After=network.target

[Service]
WorkingDirectory=/opt/tools
EnvironmentFile=/opt/tools/tools.env
ExecStart=/opt/tools/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=on-failure
# keep a heavy render from starving the chat
CPUWeight=50
MemoryMax=4G

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now tools-api
systemctl status tools-api
```

### Cloudflare Tunnel
Map `tools.sajivfrancis.com/api/*` → `http://localhost:8000` (same tunnel
mechanism as the retrieve API). No Cloudflare dashboard changes beyond the route.

## One-time bucket setup (DO control panel, not via the scoped key)
- **Lifecycle rule:** prefix `tools/`, expire objects after **7 days**.
- ACL: per-object `public-read` is set on upload (no bucket policy needed).
- CDN: enable on the Space; optionally set `DO_SPACES_CDN_BASE` to the CDN host.

## Endpoints
- `GET  /api/health`
- `POST /api/word-art/generate` — multipart: `source_type` (text|url|file), `content`/`url`/`file`, `shape`, `style`, `palette`, `width` → `{ url }`
- `POST /api/diff` — JSON: `{ original, modified, mode }` → `{ diff_output, stats }`
