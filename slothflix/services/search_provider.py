"""Torrent search via apibay.org + multi-provider fallback (async httpx)."""

import httpx
from urllib.parse import quote
from bs4 import BeautifulSoup

TRACKERS = [
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://tracker.opentrackr.org:1337",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://47.ip-51-68-199.eu:6969/announce",
]


def _human_size(bytes_str):
    try:
        size = int(bytes_str)
    except (ValueError, TypeError):
        return ""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _build_magnet(info_hash, name):
    encoded_name = quote(name, safe="")
    tracker_param = "&tr=".join(TRACKERS)
    return f"magnet:?xt=urn:btih:{info_hash}&dn={encoded_name}&tr={tracker_param}"


async def _search_apibay(client: httpx.AsyncClient, query: str):
    """Primary search via apibay.org JSON API."""
    resp = await client.get(
        "https://apibay.org/q.php",
        params={"q": query, "cat": 0},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data:
        if item.get("id") == "0" and not item.get("info_hash"):
            continue
        magnet = _build_magnet(item["info_hash"], item["name"])
        results.append({
            "title": item["name"],
            "magnet": magnet,
            "seeders": int(item.get("seeders", 0)),
            "leechers": int(item.get("leechers", 0)),
            "size": _human_size(item.get("size", "")),
            "source": "apibay",
        })
    return results


async def _search_piratebay(client: httpx.AsyncClient, query: str):
    """Fallback search via ThePirateBay HTML scraping."""
    resp = await client.get(
        "https://thepiratebay.org/search.php",
        params={"q": query},
        timeout=10,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    rows = soup.select("table#searchResult tr")
    for row in rows:
        magnet_tag = row.select_one('a[href^="magnet:"]')
        if not magnet_tag:
            continue
        magnet = magnet_tag["href"]
        title = magnet_tag.get_text(strip=True)
        cols = row.select("td")
        seeders = int(cols[1].get_text(strip=True)) if len(cols) > 1 else 0
        leechers = int(cols[2].get_text(strip=True)) if len(cols) > 2 else 0
        results.append({
            "title": title,
            "magnet": magnet,
            "seeders": seeders,
            "leechers": leechers,
            "size": "",
            "source": "thepiratebay",
        })
    return results


async def fetch_top(client: httpx.AsyncClient, category: int, limit: int = 100):
    """Fetch top torrents from apibay precompiled lists.

    category: 200=movies, 205=TV shows, 400=games, 0=all
    """
    url = f"https://apibay.org/precompiled/data_top100_{category}.json"
    resp = await client.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data[:limit]:
        if not item.get("info_hash"):
            continue
        magnet = _build_magnet(item["info_hash"], item["name"])
        results.append({
            "title": item["name"],
            "magnet": magnet,
            "seeders": int(item.get("seeders", 0)),
            "leechers": int(item.get("leechers", 0)),
            "size": _human_size(item.get("size", "")),
            "source": f"top-{category}",
        })
    return results


async def fetch_top_movies(client: httpx.AsyncClient):
    return await fetch_top(client, 200)


async def fetch_top_tv(client: httpx.AsyncClient):
    return await fetch_top(client, 205)


async def fetch_top_games(client: httpx.AsyncClient):
    """Fetch top game torrents (TPB category 400)."""
    return await fetch_top(client, 400)


async def search(client: httpx.AsyncClient, query: str):
    """Search for torrents across multiple providers."""
    results = []
    try:
        results = await _search_apibay(client, query)
    except Exception:
        pass

    # If apibay returned few results, also try piratebay and merge
    if len(results) <= 3:
        try:
            pb_results = await _search_piratebay(client, query)
            results = _merge_results(results, pb_results)
        except Exception:
            pass

    return results


def _merge_results(primary, secondary):
    """Merge two result lists, deduplicating by magnet link."""
    seen = set()
    merged = []
    for r in primary:
        mag = r.get("magnet", "")
        if mag not in seen:
            seen.add(mag)
            merged.append(r)
    for r in secondary:
        mag = r.get("magnet", "")
        if mag not in seen:
            seen.add(mag)
            merged.append(r)
    return merged
