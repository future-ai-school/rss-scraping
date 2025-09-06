# scrapy_crawler

Scrapy を用いたシンプルな BFS クローラです。リンクのアンカーテキストが特定のキーワード（例: 「議事録」「会議録」）にマッチするページのみをたどり、取得したレスポンスを Postgres に保存します。

主な構成:
- Spider: `minutes`（BFS、`-a start_url=... -a max_downloads=...` 対応、深さは Scrapy 標準の `DEPTH_LIMIT` で制御）
- Pipeline: Postgres へ保存（`crawled_pages` テーブル、URL 重複は `ON CONFLICT(url) DO NOTHING`）
- 設定: `.env` から USER_AGENT / TIMEOUT、DB 接続を読み込み（深さは `.env` ではなく Scrapy 設定）

## 環境変数と .env 運用

- `.env` 自体はコミットしません（秘匿情報を含むため）。
- 代わりに `.env.example` をコミットし、必要な環境変数キーのみを列挙します。値は空、またはコメントで例示するスタイルです。
- 実運用では `.env.example` をコピーして `.env` を作成し、値を設定してください。

`.env.example` の例:

```
# どちらか一方の方式を使用
# DATABASE_URL=postgresql://user:pass@host:5432/dbname

# または PG* で指定
PGHOST=
PGPORT=5432
PGUSER=
PGPASSWORD=
PGDATABASE=

# 任意: クローラの設定（UA/タイムアウト）
CRAWLER_USER_AGENT=SimpleCrawler/1.0
CRAWLER_TIMEOUT=30
# 深さは Scrapy の設定で指定（例: -s DEPTH_LIMIT=2）
```

Compose を使う場合は、このディレクトリの一つ上（リポジトリルート）に `.env` を置き、`docker-compose.yml` の `env_file: ../.env` から読み込みます。アプリ側でも `python-dotenv` 経由で `.env` をロードします。

## .env の例（Neon 等の外部 Postgres）

```
# DATABASE_URL=postgresql://user:pass@host:5432/dbname

PGHOST=your-neon-hostname
PGPORT=5432
PGUSER=your-user
PGPASSWORD=your-password
PGDATABASE=your-db

# 任意: クローラの設定
CRAWLER_USER_AGENT=SimpleCrawler/1.0
CRAWLER_TIMEOUT=30
# DEPTH_LIMIT は .env ではなく Scrapy の設定で渡します（例: -s DEPTH_LIMIT=2）
```

## DB スキーマ（例）

このディレクトリの `crawled_pages.sql` に定義があります。初回に DB で実行してください。

```
CREATE TABLE IF NOT EXISTS crawled_pages (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    referrer_anchor_text TEXT,
    status_code INTEGER,
    content_type TEXT,
    content BYTEA,
    html_title TEXT,
    depth INTEGER,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS crawled_pages_url_idx ON crawled_pages (url);
```

## ローカル実行（Docker を使わない場合）

1. 依存をインストール
   ```
   pip install -r requirements.txt
   ```
2. クローラ実行（`scrapy.cfg` はこのディレクトリ直下にあります）
   ```
   scrapy crawl minutes -a start_url=https://example.com -a max_downloads=100 -s DEPTH_LIMIT=2
   ```

## Docker でビルド

このディレクトリ（`scrapy_crawler/`）で実行します。

```
docker build -t scrapy_crawler:latest .
```

## Docker で実行（docker run）

`ENTRYPOINT` が `scrapy` なので、サブコマンドをそのまま渡せます。

```
docker run --rm \
  --env-file ../.env \
  -w /app \
  scrapy_crawler:latest \
  crawl minutes -a start_url=https://example.com -a max_downloads=100 -s DEPTH_LIMIT=2
```

## Docker Compose で実行

`docker-compose.yml` は `scrapy_crawler/` にあります。`command` は上書き可能で、既定では `--help` を表示します。

```
docker compose run --rm crawler crawl minutes \
  -a start_url=https://example.com -a max_downloads=100 -s DEPTH_LIMIT=2
```

TTY/STDIN を有効化しているため、対話型のオプション投入やログの見やすさに配慮しています。

## 備考

- BFS は Scrapy の FIFO キュー設定（`DEPTH_PRIORITY=1`, FIFO scheduler）で実現しています。
- Robots.txt は有効です（`ROBOTSTXT_OBEY=True`）。必要に応じて変更してください。
- 保存されるフィールド: `url, referrer_anchor_text, status_code, content_type, content(bytea), html_title`
- 実行例:
  ```
  scrapy crawl minutes -a start_url=https://example.com -a max_downloads=100 -s DEPTH_LIMIT=2
  ```
