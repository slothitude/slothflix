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

## Architecture

**Docker stack (3 containers):**
- `transmission` — haugene/transmission-openvpn: OpenVPN tunnel (PureVPN NL2) + Transmission RPC. All other VPN-routed containers share its network namespace via `network_mode: service:transmission`.
- `slothflix` — Python Flask app (this repo). Shares transmission's network so all search/torrent/HTTP traffic goes through VPN.
- `searxng` — SearXNG meta-search engine. Shares transmission's network for poster/blurb lookups.

**Entry point:** `run.py` — starts Flask app on port 8180.

**Module breakdown:**
- `web/__init__.py` — Flask app factory, registers API and stream blueprints, initializes cache DB.
- `web/api.py` — REST API endpoints: catalog (top movies/TV), search, stream start/stop/status, poster, blurb, IP check.
- `web/stream.py` — Video file streaming with HTTP Range support and `/play/<id>` endpoint for browser playback (MP4 direct, MKV remuxed via ffmpeg to fragmented MP4).
- `web/templates/index.html` — Netflix-style SPA: nav bar, hero section, horizontal catalog carousels, detail panel, episode picker, embedded HTML5 video player, stream status bar.
- `search.py` — Torrent search via apibay.org JSON API with ThePirateBay HTML scraping fallback. Builds magnet URIs with tracker list. Fetches top-100 lists by category.
- `torrent.py` — libtorrent-based sequential download engine. Adds magnets, waits for metadata, enables sequential mode, buffers to 5%, returns file path. Also uses transmission-rpc for torrent management/cleanup.
- `cache.py` — SQLite with three tables: `catalog`, `posters`, `blurbs`. Paths parameterized via env vars (`CACHE_DB_PATH`, `SEARXNG_HOST`).

**Data flow:** Browser loads UI → catalog rows from cached top-100 lists → user clicks card → detail panel loads poster + blurb via SearXNG → user clicks Play → `torrent.start_torrent()` adds magnet, buffers to 5% → Flask `/play/<id>` serves file (MP4 direct or MKV remuxed via ffmpeg) → embedded HTML5 `<video>` player auto-plays in browser.

## Dependencies

```
flask>=3.0
requests>=2.31
beautifulsoup4>=4.12
transmission-rpc>=7.0
libtorrent
```

## Key Constants

- Transmission RPC: `127.0.0.1:9191`, user `admin`, password `adminadmin` (shared network namespace)
- SlothFlix Flask: `0.0.0.0:8180`
- SearXNG: `http://127.0.0.1:8890` (shared network namespace)
- Downloads dir: `/downloads/` (shared Docker volume)
- Buffer target: 5% of selected file before playback starts

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `TRANSMISSION_HOST` | `127.0.0.1` | Transmission RPC host |
| `TRANSMISSION_PORT` | `9191` | Transmission RPC port |
| `SEARXNG_HOST` | `http://127.0.0.1:8890` | SearXNG base URL |
| `DOWNLOAD_DIR` | `/downloads` | Torrent download path |
| `CACHE_DB_PATH` | `/app/data/cache.db` | SQLite database path |
| `FLASK_PORT` | `8180` | Flask server port |

## External Requirements

- Docker + Docker Compose
- PureVPN account credentials (in docker-compose.yml)
