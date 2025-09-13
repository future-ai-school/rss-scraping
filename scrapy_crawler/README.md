# scrapy_crawler

Scrapy ベースのシンプルな BFS クローラです。リンクのアンカーテキストが特定の語（既定は「議事録」）に一致するページだけをたどり、取得したレスポンスを PostgreSQL に保存します。

主な構成:
- Spider: `minutes`（BFS、アンカーテキスト一致で辿る）
- Rules: クロール条件は YAML で指定（絶対パスを渡す）
- Pipeline: `crawled_pages` テーブルへ保存（URL を一意制約で重複回避）
- 設定: `.env` から UA/タイムアウトと DB 接続を読み込み

LLM を用いた判定（任意）:
- will_follow（ページ遷移）の判定に限り、ルールベースで除外されたリンクに対して LLM による「追判定」を行えます。
- will_download（保存対象の判定）は従来通りルールベースのみです。LLM は使いません。

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

# 任意: will_follow 用の LLM 追判定（ルールで除外された時のみ実行）
llm_fallback:
  enabled: true
  provider: openai
  model: gpt-4o-mini
  prompt_template: |
    あなたは厚生労働省のサイトをクロールしています。
    以下のリンクが厚生労働省の会議の議事録にアクセスできる可能性があるか判定してください。
    ページタイトル: "{title}"
    アンカーテキスト: "{anchor}"
    URL: {url}
    出力は Yes または No のみ。
```

キーの意味:
- start_url: 開始 URL（必須）
- depth_limit: クロールの深さ（整数）
- only_internal: 開始 URL と同一ドメインのみ辿る
- drop_fragments: `#...` 付きの同一ページ内リンクを無視
- allow_url_regex / deny_paths / restrict_xpaths: LinkExtractor 用のフィルタ
- follow_anchor_exact / follow_anchor_regex: ページ遷移のアンカーテキスト条件
- download_anchor_exact / download_anchor_regex: 保存対象（item 化）のアンカーテキスト条件

LLM 追判定（llm_fallback）のキー:
- enabled: 有効/無効（省略時は無効）
- provider: "openai" のみ対応
- model: 利用するモデル名（例: gpt-4o-mini）
- prompt_template: プロンプト本文（`{title}`, `{anchor}`, `{url}` を埋め込み可）
  - will_follow がルールで False の時にのみ LLM を呼び、Yes の時だけ追従します
  - will_download の判定には一切 LLM を使用しません

## 環境変数（.env）

リポジトリ直下の `.env` から読み込みます。以下のいずれかで DB 接続を指定します。
- `DATABASE_URL=postgresql://user:pass@host:5432/dbname`
- または `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`

任意設定:
- `CRAWLER_USER_AGENT` または `USER_AGENT`（UA）
- `CRAWLER_TIMEOUT` または `TIMEOUT`（秒）

LLM 用（任意、llm_fallback を使う場合のみ）:
- `OPENAI_API_KEY=...`
- `OPENAI_MODEL=gpt-4o-mini`（省略時の既定値）

`.env.example` も合わせて参照してください。

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
- 公開サイトへの負荷を避けるため、`DOWNLOAD_DELAY` と `AUTOTHROTTLE_ENABLED` を活用してください（既定で有効化）

## 開発背景
- 本ツールは「チームみらい」開発ボランティアによって作成されました。
- 「みらい会議」プロジェクトの 1 機能として、行政機関の会議ページ収集を支援します。

## 免責事項
- 本ツールの利用によって生じた一切の責任を負いません。
- 利用者は対象サイトの robots.txt・利用規約・関連法令を遵守してください。

## ライセンス
- MIT License（研究・教育目的での利用を推奨）
