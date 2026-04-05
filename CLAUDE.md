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

- **SlothFlix UI:** http://localhost:8180
- **Transmission RPC:** http://localhost:9191
- **SearXNG:** http://localhost:8890

## Architecture

**Docker stack (3 containers):**
- `transmission` — haugene/transmission-openvpn: OpenVPN tunnel (PureVPN NL2) + Transmission RPC. All other VPN-routed containers share its network namespace via `network_mode: service:transmission`.
- `slothflix` — Python Flask app (this repo). Shares transmission's network so all search/torrent/HTTP traffic goes through VPN. Also runs the Telegram bot as a background process via `entrypoint.sh`.
- `searxng` — SearXNG meta-search engine. Shares transmission's network for poster/blurb lookups. Internal port is 8890 (mapped from 8080 in searxng-settings.yml).

**Entry point:** `entrypoint.sh` → starts `bot.py` (if `TELEGRAM_BOT_TOKEN` is set) in background, then `run.py` (Flask app on port 8180).

**Module breakdown:**
- `web/__init__.py` — Flask app factory: registers API and stream blueprints, initializes cache DB, configures auth middleware (token cookie + HTTP Basic Auth), schedules daily trailer refresh.
- `web/api.py` — REST API (`/api/*`): catalog (top movies/TV), search, stream start/stop/status, torrent file listing, poster proxy, blurb lookup, trailers, IP check.
- `web/stream.py` — Video streaming (`/stream/<id>` with Range support, `/play/<id>` for browser playback). MP4 served directly; MKV/other formats remuxed via ffmpeg to fragmented MP4 on-the-fly.
- `web/templates/index.html` — Netflix-style SPA: nav bar, hero section, horizontal catalog carousels, detail panel, episode picker, embedded HTML5 video player, stream status bar.
- `search.py` — Torrent search via apibay.org JSON API with ThePirateBay HTML scraping fallback. Builds magnet URIs with tracker list. Fetches top-100 lists by category (200=movies, 205=TV).
- `torrent.py` — libtorrent-based sequential download engine. Manages a long-lived lt session. Adds magnets, waits for metadata, enables sequential mode, buffers to 5%, returns file path. Also uses transmission-rpc for management/cleanup. Only one torrent at a time; previous downloads are wiped on each new stream.
- `cache.py` — SQLite (WAL mode) with tables: `catalog`, `posters`, `blurbs`, `trailers`, `tokens`. Handles all persistence. `DB_PATH` set by Flask app factory from `CACHE_DB_PATH` env var.
- `bot.py` — Telegram bot for access token management. Users `/request` access → admin approves via inline button → bot sends auto-login URL with token. Tokens expire after `TOKEN_EXPIRY_DAYS`.
- `trailers.py` — Fetches latest YouTube trailer IDs via yt-dlp. Refreshed on startup and daily.

**Auth flow:** Two methods work in parallel:
1. **HTTP Basic Auth** — `AUTH_USER`/`AUTH_PASS` env vars. Browser requests without valid auth redirect to `/login` page.
2. **Token auth** — Telegram bot issues time-limited tokens. User visits `/?token=<token>` → cookie set → auto-logged-in.

**Data flow:** Browser loads UI → catalog rows from cached top-100 lists → user clicks card → detail panel loads poster + blurb via SearXNG → user clicks Play → `torrent.start_torrent()` adds magnet, buffers to 5% → Flask `/play/<id>` serves file (MP4 direct or MKV remuxed via ffmpeg) → embedded HTML5 `<video>` player auto-plays in browser.

## Key Constants

- Transmission RPC: `127.0.0.1:9191`, user `admin`, password `adminadmin` (shared network namespace)
- SlothFlix Flask: `0.0.0.0:8180`
- SearXNG (internal): `http://127.0.0.1:8080` (SearXNG listens on 8080 inside shared network; `SEARXNG_HOST` env var should point here)
- Downloads dir: `/downloads/` (shared Docker volume)
- Buffer target: 5% of selected file before playback starts
- Stream chunk size: 256KB

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

## Deployment (Oracle Cloud)

Deployed on Oracle Cloud free tier (1GB RAM, 1 vCPU). `setup-oracle.sh` adds 2GB swap and opens firewall ports. The server uses Traefik as reverse proxy with HTTPS (Let's Encrypt via acme.sh + Dynu DNS challenge).

```bash
# Remote rebuild
ssh -i ~/.oci/slothflix_ssh_key ubuntu@<server-ip> "cd /home/ubuntu/slothflix && docker compose up -d --build"

# Check containers
ssh -i ~/.oci/slothflix_ssh_key ubuntu@<server-ip> "docker compose -f /home/ubuntu/slothflix/docker-compose.yml ps"
```

## External Requirements

- Docker + Docker Compose
- PureVPN account credentials (in docker-compose.yml)
