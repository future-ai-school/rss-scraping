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
  python crawler.py --start-url https://example.com --max-depth 2 --timeout 30 --max-downloads 100
  python crawler.py --start-url https://example.com --max-depth 1 --no-timeout

Notes:
  - Only HTTP/HTTPS links are considered.
  - HTML and PDF are downloaded; only HTML is parsed for link discovery.
  - Table creation is not handled here; run schema.sql separately.
"""

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

try:
    # Optional PDF text extraction
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:  # pragma: no cover
    pdf_extract_text = None


@dataclass
class QueueItem:
    url: str
    depth: int
    anchor_text: Optional[str]
    # referrer_url removed per requirements


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


MINUTES_KEYWORDS = (
    # Japanese
    "議事録", "会議録", "会議", "議題", "議事次第", "出席者", "配布資料", "決定事項", "アジェンダ",
    # English
    "meeting minutes", "minutes", "agenda", "attendees", "action items", "decisions",
)


def rule_based_is_minutes_like(text: str, url: str) -> bool:
    t = (text or "")[:200000].lower()
    # simple heuristics: require at least one keyword and some structure-like cues
    if not any(k in t for k in [kw.lower() for kw in MINUTES_KEYWORDS]):
        return False
    # extra signals: dates, numbering, time
    signals = 0
    if re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", t):
        signals += 1
    if re.search(r"\b(\d{1,2}:\d{2})\b", t):
        signals += 1
    if re.search(r"\b(agenda|議題)\b", t):
        signals += 1
    return signals >= 1


def extract_text_from_pdf_bytes(data: bytes) -> Optional[str]:
    if not data:
        return None
    if pdf_extract_text is None:
        return None
    try:
        with io.BytesIO(data) as f:
            return pdf_extract_text(f) or None
    except Exception:
        return None


def llm_is_minutes_like(text: str, url: str) -> Optional[bool]:  # Optional LLM check
    if os.getenv("ENABLE_LLM_FILTER", "0") != "1":
        return None
    # Placeholder for LLM integration; implement with your preferred provider.
    # For example, using OpenAI if OPENAI_API_KEY is set.
    # To keep this script provider-agnostic and offline-friendly, return None here.
    return None


def should_save(content_type: Optional[str], url: str, *, html_text: Optional[str], pdf_bytes: Optional[bytes]) -> bool:
    text: Optional[str] = None
    if content_type:
        ct = content_type.lower()
    else:
        ct = ""
    if ct.startswith("text/html") and html_text:
        text = html_to_text(html_text)
    elif ct in ("application/pdf", "application/x-pdf", "application/acrobat") and pdf_bytes:
        text = extract_text_from_pdf_bytes(pdf_bytes)

    # If no text available (e.g., PDF extractor not installed), fall back to URL-based heuristic
    if not text:
        text = url.lower()

    if rule_based_is_minutes_like(text, url):
        return True

    llm = llm_is_minutes_like(text, url)
    if llm is not None:
        return bool(llm)

    return False


def crawl(
    start_url: str,
    max_depth: int,
    *,
    request_timeout: Optional[int] = 20,
    user_agent: str = "SimpleCrawler/1.0 (+https://example.local)",
    max_downloads: Optional[int] = None,
) -> None:
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

        status_code: Optional[int] = None
        content_type: Optional[str] = None
        html_title: Optional[str] = None
        body_bytes: Optional[bytes] = None
        links: Tuple[Tuple[str, str], ...] = tuple()

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

        # Decide whether to save (HTML/PDF minutes-like only)
        keep = False
        try:
            keep = should_save(content_type, url, html_text=resp.text if (content_type and content_type.lower().startswith("text/html")) else None, pdf_bytes=body_bytes if (content_type and content_type.lower() in ("application/pdf", "application/x-pdf", "application/acrobat")) else None)
        except Exception:
            keep = False

        if keep:
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
    p.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds (ignored if --no-timeout)")
    p.add_argument("--no-timeout", action="store_true", help="Disable request timeout (infinite)")
    p.add_argument(
        "--user-agent",
        default=os.getenv("CRAWLER_USER_AGENT", "SimpleCrawler/1.0 (+https://example.local)"),
        help="User-Agent header (or set CRAWLER_USER_AGENT)"
    )
    p.add_argument("--max-downloads", type=int, default=None, help="Max number of pages to SAVE; stop when reached")
    return p.parse_args(argv)


def main() -> None:
    # Load .env first
    load_dotenv()
    args = parse_args()
    crawl(
        start_url=args.start_url,
        max_depth=args.max_depth,
        request_timeout=None if args.no_timeout else args.timeout,
        user_agent=args.user_agent,
        max_downloads=args.max_downloads,
    )


if __name__ == "__main__":
    main()
