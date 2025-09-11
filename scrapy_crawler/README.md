# scrapy_crawler

Scrapy ベースのシンプルな BFS クローラです。リンクのアンカーテキストが特定の語（既定は「議事録」）に一致するページだけをたどり、取得したレスポンスを PostgreSQL に保存します。

主な構成:
- Spider: `minutes`（BFS、アンカーテキスト一致で辿る）
- Rules: クロール条件は YAML で指定（絶対パスを渡す）
- Pipeline: `crawled_pages` テーブルへ保存（URL を一意制約で重複回避）
- 設定: `.env` から UA/タイムアウトと DB 接続を読み込み

## 使い方（ローカル）

1) 依存をインストール
```
pip install -r requirements.txt
```

2) ルール YAML を用意（例: `scrapy_crawler/rules/test.yml`）。この Spider は YAML を必須とし、`-a rules=絶対パス` で受け取ります。

3) 実行
```
scrapy crawl minutes -a rules="C:\\abs\\path\\to\\scrapy_crawler\\rules\\test.yml"
```
補足:
- `depth_limit` は YAML で設定され、Spider 側で `DEPTH_LIMIT` に反映されます（`-s DEPTH_LIMIT=...` は不要）。
- ドメイン外リンクを辿らない `only_internal` は既定で true。`#fragment` を落とす `drop_fragments` も既定で true。

## ルール YAML の例

```
start_url: https://example.com/start
depth_limit: 2
only_internal: true
drop_fragments: true
allow_url_regex: ["/allowed/path/"]
deny_paths: ["/search", "/print"]
# restrict_xpaths: ["//main"]
follow_anchor_exact: ["社会保険部会", "医療部会"]
follow_anchor_regex: []
download_anchor_exact: ["議事録", "配布資料"]
download_anchor_regex: []
```

キーの意味:
- start_url: 開始 URL（必須）
- depth_limit: クロールの深さ（整数）
- only_internal: 開始 URL と同一ドメインのみ辿る
- drop_fragments: `#...` 付きの同一ページ内リンクを無視
- allow_url_regex / deny_paths / restrict_xpaths: LinkExtractor 用のフィルタ
- follow_anchor_exact / follow_anchor_regex: ページ遷移のアンカーテキスト条件
- download_anchor_exact / download_anchor_regex: 保存対象（item 化）のアンカーテキスト条件

## 環境変数（.env）

リポジトリ直下の `.env` から読み込みます。以下のいずれかで DB 接続を指定します。
- `DATABASE_URL=postgresql://user:pass@host:5432/dbname`
- または `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`

任意設定:
- `CRAWLER_USER_AGENT` または `USER_AGENT`（UA）
- `CRAWLER_TIMEOUT` または `TIMEOUT`（秒）

## DB スキーマ

`scrapy_crawler/crawled_pages.sql` を DB に適用してください。
- 保存カラム: `url, referrer_anchor_text, status_code, content_type, content(bytea), html_title, depth`
- URL は一意制約で重複保存を防止

## Docker

ビルド（`scrapy_crawler/` で実行）
```
docker build -t scrapy_crawler:latest .
```

実行（ENTRYPOINT は `scrapy`）
```
docker run --rm \
  --env-file ../.env \
  -w /app \
  scrapy_crawler:latest \
  crawl minutes -a rules=/abs/path/to/scrapy_crawler/rules/test.yml
```

Docker Compose（`scrapy_crawler/docker-compose.yml`）
```
docker compose run --rm crawler crawl minutes \
  -a rules=/abs/path/to/scrapy_crawler/rules/test.yml
```

## 備考
- BFS は `DEPTH_PRIORITY=1` と FIFO キューで実現
- robots.txt は既定で遵守（`ROBOTSTXT_OBEY=True`）
- すべての HTTP ステータスを受理して保存判定（`HTTPERROR_ALLOW_ALL`）
