#!/usr/bin/env python3
"""
Simple breadth-first web crawler that:
- Starts from a URL and follows links up to --max-depth
- Stores each downloaded page in Postgres as bytea
- Saves URL and link text (anchor text)
- Skips downloading if the URL already exists in the DB
- Saves only pages akin to meeting minutes (rule-based + optional LLM)

Requirements:
  pip install requests beautifulsoup4 psycopg2-binary python-dotenv pdfminer.six

Database configuration via .env (loaded automatically):
  - DATABASE_URL=postgresql://user:pass@host:5432/dbname
  - Or PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

Optional LLM filtering (disabled unless enabled via env):
  - ENABLE_LLM_FILTER=1
  - OPENAI_API_KEY=...

Usage example:
  python -m crawler.crawler --start-url https://example.com --max-depth 2 --max-downloads 100

Notes:
  - Only HTTP/HTTPS links are considered.
  - HTML and PDF are downloaded; only HTML is parsed for link discovery.
  - Table creation is not handled here; run schema.sql separately.
"""

# ===== Default values (can be overridden via environment variables) =====
DEFAULT_REQUEST_TIMEOUT = 20
DEFAULT_USER_AGENT = "SimpleCrawler/1.0 (+https://example.local)"
# =======================================================================

from __future__ import annotations

import argparse
import os
import sys
from collections import deque
from dataclasses import dataclass
from typing import Optional, Set, Tuple

from urllib.parse import urljoin, urldefrag, urlparse

import requests
from bs4 import BeautifulSoup

import psycopg2
from psycopg2.extensions import connection as PGConnection

from dotenv import load_dotenv
import io
import re

from crawler.filter_loader import load_filter

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:
    pdf_extract_text = None


@dataclass
class QueueItem:
    url: str
    depth: int
    anchor_text: Optional[str]


def get_db_connection() -> PGConnection:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return psycopg2.connect(dsn)

    # Fallback to PG* env vars
    params = {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", ""),
        "dbname": os.getenv("PGDATABASE", os.getenv("PGDB", "postgres")),
    }
    return psycopg2.connect(**params)


def normalize_url(url: str) -> str:
    # Remove fragment and strip whitespace
    url, _frag = urldefrag(url.strip())
    return url


def is_http_url(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme in ("http", "https")


def url_exists(conn: PGConnection, url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM crawled_pages WHERE url = %s LIMIT 1", (url,))
        return cur.fetchone() is not None


def save_page(
    conn: PGConnection,
    *,
    url: str,
    anchor_text: Optional[str],
    status_code: Optional[int],
    content_type: Optional[str],
    content: Optional[bytes],
    html_title: Optional[str],
    depth: int,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crawled_pages
            (url, referrer_anchor_text, status_code, content_type, content, html_title, depth)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            """,
            (
                url,
                anchor_text,
                status_code,
                content_type,
                psycopg2.Binary(content) if content is not None else None,
                html_title,
                depth,
            ),
        )
        inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def extract_links(base_url: str, html: str) -> Tuple[Tuple[str, str], ...]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href").strip()
        # resolve relative -> absolute
        abs_url = urljoin(base_url, href)
        abs_url = normalize_url(abs_url)
        if not is_http_url(abs_url):
            continue
        text = (a.get_text(strip=True) or None)
        links.append((abs_url, text or ""))
    return tuple(links)


def guess_title_from_html(html: str) -> Optional[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        t = soup.find("title")
        return t.get_text(strip=True) if t else None
    except Exception:
        return None


def html_to_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style
        for tag in soup(["script", "style", "noscript"]):
            tag.extract()
        return soup.get_text(separator="\n", strip=True)
    except Exception:
        return html


def crawl(
    start_url: str,
    max_depth: int,
    request_timeout: Optional[int] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    save_filter=None,
    max_downloads: Optional[int] = None,
) -> None:
    filter_ = save_filter or load_filter()
    start_url = normalize_url(start_url)

    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"[DB] Connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    q: deque[QueueItem] = deque([QueueItem(start_url, 0, None)])
    seen_in_run: Set[str] = set()
    saved_count = 0

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    while q:
        item = q.popleft()
        url = normalize_url(item.url)

        if url in seen_in_run:
            continue
        seen_in_run.add(url)

        if url_exists(conn, url):
            # Already downloaded previously; skip downloading to avoid duplication.
            continue

        # Anchor-text based pre-filter: decide whether to download
        # Apply only to non-root items (depth > 0). Root is fetched to discover links.
        if item.depth > 0:
            try:
                should_fetch = filter_.should_save(
                    url=url,
                    content_type=None,
                    text=(item.anchor_text or ""),
                    raw=None,
                )
            except Exception:
                should_fetch = False
            if not should_fetch:
                continue

        status_code: Optional[int] = None
        content_type: Optional[str] = None
        html_title: Optional[str] = None
        body_bytes: Optional[bytes] = None
        links: Tuple[Tuple[str, str], ...] = tuple()
        html_text: Optional[str] = None

        try:
            resp = session.get(url, timeout=None if (request_timeout is None) else request_timeout, allow_redirects=True)
            status_code = resp.status_code
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip() or None
            body_bytes = resp.content

            # If HTML, parse and extract title and links
            if content_type and content_type.lower().startswith("text/html") and body_bytes:
                html_text = None
                try:
                    html_text = resp.text
                except Exception:
                    # Fallback decode to utf-8 errors ignored
                    try:
                        html_text = body_bytes.decode("utf-8", errors="ignore")
                    except Exception:
                        html_text = None

                if html_text:
                    html_title = guess_title_from_html(html_text)
                    if item.depth < max_depth:
                        links = extract_links(url, html_text)
            elif content_type and content_type.lower() in ("application/pdf", "application/x-pdf", "application/acrobat"):
                # keep body_bytes for filtering/saving; do not extract links
                pass
        except requests.RequestException as e:
            # Save a row indicating failure status if any
            status_code = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            content_type = None
            body_bytes = None
            html_title = None
            links = tuple()
            print(f"[HTTP] Failed {url}: {e}", file=sys.stderr)

        # Save page if it passed anchor pre-filter (depth > 0). Root (depth=0) is not saved.
        if item.depth > 0:
            try:
                inserted = save_page(
                    conn,
                    url=url,
                    anchor_text=item.anchor_text,
                    status_code=status_code,
                    content_type=content_type,
                    content=body_bytes,
                    html_title=html_title,
                    depth=item.depth,
                )
                if inserted:
                    saved_count += 1
                    if max_downloads is not None and saved_count >= max_downloads:
                        break
            except Exception as e:
                print(f"[DB] Failed to save {url}: {e}", file=sys.stderr)

        # Enqueue discovered links
        if links and item.depth < max_depth:
            for link_url, link_text in links:
                if link_url not in seen_in_run:
                    q.append(QueueItem(link_url, item.depth + 1, link_text or None))

    try:
        conn.close()
    except Exception:
        pass


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simple BFS web crawler with Postgres storage")
    p.add_argument("--start-url", required=True, help="Starting URL to crawl from")
    p.add_argument("--max-depth", type=int, default=1, help="Max depth to follow links (0 = only start URL)")
    p.add_argument("--max-downloads", type=int, default=None, help="Max number of pages to SAVE; stop when reached")
    return p.parse_args(argv)


def main() -> None:
    load_dotenv()
    args = parse_args()

    # 環境変数から設定（無ければデフォルトを使用）
    timeout = int(os.getenv("CRAWLER_TIMEOUT", str(DEFAULT_REQUEST_TIMEOUT)))
    user_agent = os.getenv("CRAWLER_USER_AGENT", DEFAULT_USER_AGENT)

    crawl(
        start_url=args.start_url,
        max_depth=args.max_depth,
        request_timeout=timeout,
        user_agent=user_agent,
        max_downloads=args.max_downloads,
    )


if __name__ == "__main__":
    main()
