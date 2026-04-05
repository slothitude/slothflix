"""SQLite cache for SlothFlix — catalog, posters, OMDb data."""

import os
import re
import sqlite3
from datetime import datetime

import requests as req

DB_PATH = os.getenv("CACHE_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.db"))
SEARXNG = os.getenv("SEARXNG_HOST", "http://localhost:8888")


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _conn()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS catalog (
            title TEXT PRIMARY KEY,
            category TEXT,
            magnet TEXT,
            seeders INTEGER,
            leechers INTEGER,
            size TEXT,
            source TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS posters (
            title TEXT PRIMARY KEY,
            image_blob BLOB,
            width INTEGER,
            height INTEGER,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS blurbs (
            clean_title TEXT PRIMARY KEY,
            blurb TEXT,
            source_url TEXT,
            updated_at TEXT
        );
    """)
    con.close()


# --- catalog ---

def save_catalog(category, results):
    now = datetime.utcnow().isoformat()
    con = _conn()
    with con:
        con.execute("DELETE FROM catalog WHERE category = ?", (category,))
        for r in results:
            con.execute(
                "INSERT OR REPLACE INTO catalog (title, category, magnet, seeders, leechers, size, source, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (r["title"], category, r["magnet"], r.get("seeders", 0), r.get("leechers", 0),
                 r.get("size", ""), r.get("source", ""), now),
            )
    con.close()


def load_catalog(category):
    con = _conn()
    rows = con.execute(
        "SELECT title, category, magnet, seeders, leechers, size, source FROM catalog WHERE category = ?",
        (category,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# --- posters ---

def save_poster(title, blob, w, h):
    now = datetime.utcnow().isoformat()
    con = _conn()
    with con:
        con.execute(
            "INSERT OR REPLACE INTO posters (title, image_blob, width, height, updated_at) VALUES (?, ?, ?, ?, ?)",
            (title, blob, w, h, now),
        )
    con.close()


def load_poster(title):
    con = _conn()
    row = con.execute(
        "SELECT image_blob, width, height FROM posters WHERE title = ?", (title,)
    ).fetchone()
    con.close()
    if row:
        return bytes(row["image_blob"]), row["width"], row["height"]
    return None


# --- omdb ---

def clean_title(raw):
    """Strip S01E01, 720p, HDTV, x264, etc. to get a searchable title."""
    t = re.sub(r"[.\-_]", " ", raw)
    t = re.sub(r"\b(S\d{1,2}E\d{1,2}|S\d{1,2})\b.*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(720p|1080p|2160p|4K|HDTV|WEBRip|WEBDL|WEB-DL|BRRip|BDRip|BluRay|x264|x265|HEVC|H264|H265|AAC|DD5?\.?1| Atmos|10bit|HDR)\b.*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\[.*?\]|\(.*?\)", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    # remove trailing year-like patterns
    t = re.sub(r"\s+\d{4}\s*$", "", t)
    return t


def save_blurb(clean_t, blurb, source_url=""):
    now = datetime.utcnow().isoformat()
    con = _conn()
    with con:
        con.execute(
            "INSERT OR REPLACE INTO blurbs (clean_title, blurb, source_url, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (clean_t, blurb, source_url, now),
        )
    con.close()


def load_blurb(clean_t):
    con = _conn()
    row = con.execute(
        "SELECT blurb, source_url FROM blurbs WHERE clean_title = ?", (clean_t,)
    ).fetchone()
    con.close()
    if row and row["blurb"]:
        return row["blurb"]
    return None


def fetch_blurb(clean_t):
    """Fetch a description via SearXNG Wikipedia search. Returns blurb text or None."""
    try:
        resp = req.get(
            f"{SEARXNG}/search",
            params={"q": clean_t + " wikipedia", "format": "json", "categories": "general"},
            timeout=8,
        )
        data = resp.json()
        for res in data.get("results", []):
            url = res.get("url", "")
            if "wikipedia.org" in url:
                content = res.get("content", "").strip()
                if content:
                    save_blurb(clean_t, content, url)
                    return content
    except Exception:
        pass
    return None
