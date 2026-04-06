# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlothFlix is a Dockerized torrent streaming app with a Netflix-style web UI. It runs as a Docker Compose stack where all outbound traffic routes through a VPN container — zero leaks. It searches for torrents, downloads them via libtorrent with sequential streaming, and serves video through a Flask HTTP server with Range request support.

## Running the App

```bash
# Start all containers
docker compose up --build

# Stop
docker compose down
```

- **SlothFlix UI:** http://localhost:8180 (direct) or https://slothitude.giize.com (via Traefik)
- **Transmission RPC:** http://localhost:9191
- **Traefik Dashboard:** http://localhost:8888

## Architecture

**Docker stack (4 containers):**
- `traefik` — Traefik v3 reverse proxy. Runs on host network. HTTPS termination with Let's Encrypt certs. Routes to slothflix via Docker labels on the transmission container (`slothflix` router → port 8180).
- `transmission` — haugene/transmission-openvpn: OpenVPN tunnel (PureVPN NL2) + Transmission RPC. All other VPN-routed containers share its network namespace via `network_mode: service:transmission`.
- `slothflix` — Python Flask app (this repo). Shares transmission's network so all search/torrent/HTTP traffic goes through VPN. Also runs the Telegram bot as a background process via `entrypoint.sh`.
- `searxng` — SearXNG meta-search engine. Shares transmission's network for poster/blurb lookups. Settings in `searxng-settings.yml` override port to 8890, but `SEARXNG_HOST` env var in docker-compose points to `http://127.0.0.1:8080` — this is a potential mismatch (SearXNG may ignore the settings file port). The `cache.py` default fallback is `http://localhost:8888` which is also wrong.

**Entry point:** `entrypoint.sh` → starts `bot.py` (if `TELEGRAM_BOT_TOKEN` is set) in background, then `run.py` (Flask app on port 8180).

**Module breakdown:**
- `web/__init__.py` — Flask app factory: registers API and stream blueprints, initializes cache DB, configures auth middleware (token cookie + HTTP Basic Auth), schedules daily trailer refresh.
- `web/api.py` — REST API (`/api/*`): catalog (top movies/TV), search, stream start/stop/status, torrent file listing, poster proxy, blurb lookup, trailers, IP check.
- `web/stream.py` — Video streaming (`/stream/<id>` with Range support, `/play/<id>` for browser playback). MP4 served directly; MKV/other formats remuxed via ffmpeg to fragmented MP4 on-the-fly. Chunk size: 256KB.
- `web/templates/index.html` — Netflix-style SPA (~830 lines, single file with inline CSS/JS, no build tools). Key JS patterns: `authFetch()` wrapper for authenticated API calls, IntersectionObserver for lazy poster loading (max 4 concurrent), YouTube IFrame Player API for trailer pre-roll.
- `search.py` — Torrent search via apibay.org JSON API with ThePirateBay HTML scraping fallback. Builds magnet URIs with tracker list. Fetches top-100 lists by category (200=movies, 205=TV).
- `torrent.py` — libtorrent-based sequential download engine. Manages a long-lived lt session. Adds magnets, waits for metadata, enables sequential mode, buffers to 10%, returns file path. Also uses transmission-rpc for management/cleanup. Only one torrent at a time; previous downloads are wiped on each new stream.
- `cache.py` — SQLite (WAL mode) with tables: `catalog`, `posters`, `blurbs`, `trailers`, `tokens`. Handles all persistence. `DB_PATH` set by Flask app factory from `CACHE_DB_PATH` env var.
- `bot.py` — Telegram bot for access token management. Users `/request` access → admin approves via inline button → bot sends auto-login URL with token. Tokens expire after `TOKEN_EXPIRY_DAYS`.
- `trailers.py` — Fetches latest YouTube trailer IDs via yt-dlp. Refreshed on startup and daily.

**Auth flow:** Two methods work in parallel:
1. **HTTP Basic Auth** — `AUTH_USER`/`AUTH_PASS` env vars. Browser requests without valid auth redirect to `/login` page.
2. **Token auth** — Telegram bot issues time-limited tokens. User visits `/?token=<token>` → cookie set → auto-logged-in.

**Playback flow:** Browser loads UI → catalog rows from cached top-100 lists → user clicks card → detail panel loads poster + blurb via SearXNG → user clicks Play → YouTube trailer plays as pre-roll (IFrame Player API) → while trailer plays, `torrent.start_torrent()` adds magnet and buffers to 10% → once buffered, translucent "play ready" overlay appears over trailer → user clicks overlay (or trailer ends) → Flask `/stream/<id>` serves file (MP4 direct or MKV remuxed via ffmpeg) → embedded HTML5 `<video>` player plays. For TV shows: when episode ends, Netflix-style auto-advance countdown appears and loads next episode.

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `TRANSMISSION_HOST` | `127.0.0.1` | Transmission RPC host |
| `TRANSMISSION_PORT` | `9191` | Transmission RPC port |
| `TRANSMISSION_RPC_USERNAME` | `admin` | Transmission RPC username |
| `TRANSMISSION_RPC_PASSWORD` | `adminadmin` | Transmission RPC password |
| `SEARXNG_HOST` | `http://127.0.0.1:8080` | SearXNG base URL (internal) |
| `DOWNLOAD_DIR` | `/downloads` | Torrent download path |
| `CACHE_DB_PATH` | `/app/data/cache.db` | SQLite database path |
| `FLASK_PORT` | `8180` | Flask server port |
| `AUTH_USER` | _(empty)_ | Basic auth username (enables auth when both set) |
| `AUTH_PASS` | _(empty)_ | Basic auth password |
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | Telegram bot token (enables bot when set) |
| `TELEGRAM_ADMIN_ID` | `5597932516` | Telegram user ID for admin approvals |
| `TOKEN_EXPIRY_DAYS` | `7` | Days until token auth expires |
| `APP_URL` | `http://localhost:8180` | Public URL for auto-login links |

## Development

No tests, linter, or CI. Manual testing only — build and visit the UI.

## Deployment (Oracle Cloud)

Deployed on Oracle Cloud free tier (1GB RAM, 1 vCPU, 4GB swap). Traefik v3 reverse proxy with auto-renewing Let's Encrypt wildcard certs via DNS-01 challenge (Dynu API). Dynu wildcard alias enabled — `*.slothitude.giize.com` resolves to server IP. New services need only Traefik Docker labels, No per-service DNS records needed.

```bash
# Remote rebuild
ssh -i ~/.oci/slothflix_ssh_key ubuntu@<server-ip> "cd /home/ubuntu/slothflix && docker compose up -d --build"

# Check containers
ssh -i ~/.oci/slothflix_ssh_key ubuntu@<server-ip> "docker ps --format '{{.Names}} {{.Status}}'"
```

## External Requirements

- Docker + Docker Compose
- PureVPN account credentials (in docker-compose.yml)
