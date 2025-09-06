import os
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import Binary

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


def _load_env():
    # Load .env if possible; fall back to manual parse
    if load_dotenv:
        # Load from project root (two levels up from this file)
        project_root = Path(__file__).resolve().parents[2]
        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    else:
        project_root = Path(__file__).resolve().parents[2]
        env_path = project_root / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)


def _dsn_from_env() -> str:
    # DATABASE_URL precedence
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # PG* variables
    pg_host = os.getenv("PGHOST", "localhost")
    pg_port = os.getenv("PGPORT", "5432")
    pg_user = os.getenv("PGUSER")
    pg_password = os.getenv("PGPASSWORD")
    pg_database = os.getenv("PGDATABASE")

    # Build DSN string
    parts = [
        f"host={pg_host}",
        f"port={pg_port}",
    ]
    if pg_user:
        parts.append(f"user={pg_user}")
    if pg_password:
        parts.append(f"password={pg_password}")
    if pg_database:
        parts.append(f"dbname={pg_database}")

    return " ".join(parts)


class PostgresPipeline:
    def __init__(self):
        _load_env()
        self.conn = None
        self.cur = None

    def open_spider(self, spider):
        dsn = _dsn_from_env()
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = False
        self.cur = self.conn.cursor()

    def close_spider(self, spider):
        try:
            if self.cur is not None:
                self.cur.close()
            if self.conn is not None:
                self.conn.commit()
                self.conn.close()
        finally:
            self.cur = None
            self.conn = None

    def process_item(self, item, spider):
        # Item fields expected:
        # url, referrer_anchor_text, status_code, content_type, content, html_title, depth
        sql = (
            "INSERT INTO crawled_pages (url, referrer_anchor_text, status_code, content_type, content, html_title, depth) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (url) DO NOTHING"
        )

        params = (
            item.get("url"),
            item.get("referrer_anchor_text"),
            item.get("status_code"),
            item.get("content_type"),
            Binary(item.get("content") or b""),
            item.get("html_title"),
            item.get("depth"),
        )

        self.cur.execute(sql, params)
        self.conn.commit()
        return item
