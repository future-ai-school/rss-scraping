# -*- coding: utf-8 -*-
import os
import re
import json
import yaml
from urllib.parse import urlparse
from itertools import islice

import scrapy
from scrapy import Request
from scrapy.http import Response
from scrapy.exceptions import CloseSpider
from scrapy.linkextractors import LinkExtractor, IGNORED_EXTENSIONS
from scrapy_crawler.items import CrawledPageItem
from scrapy_crawler.llm import complete_text


# ------------------------------------------------------------
# ユーティリティ
# ------------------------------------------------------------
def _load_yaml_abs(path_abs: str) -> dict:
    if not os.path.isabs(path_abs):
        raise CloseSpider(f"'rules' は絶対パスのみ受け付けます: {path_abs}")
    if not os.path.exists(path_abs):
        raise CloseSpider(f"YAML ファイルが見つかりません: {path_abs}")
    with open(path_abs, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise CloseSpider("YAML のフォーマットが不正です（辞書が必要）")
    return data


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


# ------------------------------------------------------------
# Spider
# ------------------------------------------------------------
class MinutesSpider(scrapy.Spider):
    """
    方針（ユーザ指定）:
    - 省庁ごと単一 YAML（絶対パスのみ）を読み込む
    - YAML の start_url / depth_limit を使用（start_url 引数は廃止）
    - ページ個別ルールなし（ドメイン単位のみ）
    - follow_anchor_* でページ遷移、download_anchor_* で保存対象を判定
    - 同一ページの #fragments は LinkExtractor の process_value で除外
    - restrict_xpaths / allow_url_regex / deny_paths を YAML 直結
    - 保存アイテムは従来通り（本文含む）
    """

    name = "minutes"
    custom_settings = {
        # BFS寄せ（任意）
        "DEPTH_PRIORITY": 1,
        "SCHEDULER_DISK_QUEUE": "scrapy.squeues.PickleFifoDiskQueue",
        "SCHEDULER_MEMORY_QUEUE": "scrapy.squeues.FifoMemoryQueue",
        # エラーも拾いたい場合
        "HTTPERROR_ALLOW_ALL": True,
        "METAREFRESH_ENABLED": False,
        "AUTOTHROTTLE_ENABLED": True,
        "DOWNLOAD_DELAY": 0.5,
    }

    handle_httpstatus_all = True

    # --------------------------------------------------------
    # settings にアクセスできる from_crawler で初期化
    # --------------------------------------------------------
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        rules_path = kwargs.get("rules")
        if not rules_path:
            raise CloseSpider("rules (YAML 絶対パス) が必要です")

        # YAML ロード
        cfg = _load_yaml_abs(rules_path)

        # start_url を YAML から取得（必須）
        start_url = cfg.get("start_url")
        if not start_url:
            raise CloseSpider("YAML に start_url が必要です")

        # depth_limit → Scrapy 設定
        depth = cfg.get("depth_limit", 2)
        try:
            depth_int = int(depth)
        except Exception:
            raise CloseSpider(f"depth_limit は整数が必要です: {depth}")
        crawler.settings.set("DEPTH_LIMIT", depth_int, priority="spider")

        # インスタンス生成
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider._config = cfg
        spider._start_url = start_url

        # 既定値の補完
        spider._only_internal = bool(cfg.get("only_internal", True))
        spider._drop_fragments = bool(cfg.get("drop_fragments", True))

        # only_internal=True の場合は allowed_domains 制限
        if spider._only_internal:
            netloc = urlparse(spider._start_url).netloc
            spider.allowed_domains = [netloc]

        # 正規表現（許可/拒否）
        allow_patterns = cfg.get("allow_url_regex") or []
        deny_patterns = cfg.get("deny_paths") or []

        # XPath 制約
        restrict_xpaths = cfg.get("restrict_xpaths") or []

        # アンカーマッチ
        follow_exact_list = cfg.get("follow_anchor_exact") or []
        follow_regex_list = cfg.get("follow_anchor_regex") or []
        download_exact_list = cfg.get("download_anchor_exact") or []
        download_regex_list = cfg.get("download_anchor_regex") or []

        deny_ext = [ext for ext in IGNORED_EXTENSIONS if ext != "pdf"]
        spider._link_extractor = LinkExtractor(
            allow=tuple(allow_patterns) if allow_patterns else (),
            deny=tuple(deny_patterns) if deny_patterns else (),
            restrict_xpaths=tuple(restrict_xpaths) if restrict_xpaths else (),
            canonicalize=True,
            unique=True,
            deny_extensions=deny_ext,
        )

        # Optional LLM fallback configuration
        llm_cfg = cfg.get("llm_fallback") or {}
        spider._llm_enabled = bool(llm_cfg.get("enabled", True)) if llm_cfg else False
        spider._llm_prompt_template = (llm_cfg.get("prompt_template") or "").strip() if llm_cfg else ""
        spider._llm_provider = (llm_cfg.get("provider") or "openai") if llm_cfg else "openai"
        spider._llm_model = (llm_cfg.get("model") or None) if llm_cfg else None

        # 新しいアンカー判定関数（フォロー／ダウンロード）を設定
        def _is_follow_anchor(text: str) -> bool:
            t = _collapse_ws(text)
            for ex in follow_exact_list:
                if t == ex:
                    return True
            for rpat in follow_regex_list:
                try:
                    if re.search(rpat, t):
                        return True
                except re.error:
                    spider.logger.warning(f"無効な正規表現をスキップしました: {rpat!r}")
            return False

        def _is_download_anchor(text: str) -> bool:
            t = _collapse_ws(text)
            for ex in download_exact_list:
                if t == ex:
                    return True
            for rpat in download_regex_list:
                try:
                    if re.search(rpat, t):
                        return True
                except re.error:
                    spider.logger.warning(f"無効な正規表現をスキップしました: {rpat!r}")
            return False

        spider._is_follow_anchor = _is_follow_anchor
        spider._is_download_anchor = _is_download_anchor
        return spider

    # --------------------------------------------------------
    # __init__（YAMLで完結するため引数なし）
    # --------------------------------------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # allowed_domains は from_crawler で設定（_start_url 決定後）

    # --------------------------------------------------------
    # クロール開始
    # --------------------------------------------------------
    def start_requests(self):
        yield Request(
            url=self._start_url,
            callback=self.parse,
            meta={"referrer_anchor_text": None, "matched": False},
            dont_filter=True,
        )

    # --------------------------------------------------------
    # イテレータを size ごとに分割
    # --------------------------------------------------------
    @staticmethod
    def _chunked(iterable, size):
        it = iter(iterable)
        while True:
            chunk = list(islice(it, size))
            if not chunk:
                break
            yield chunk

    # --------------------------------------------------------
    # メインループ
    # --------------------------------------------------------
    def parse(self, response: Response, **kwargs):
        matched = bool(response.meta.get("matched", False))
        ref_anchor = response.meta.get("referrer_anchor_text")

        # --- 保存（matched=True のときのみ） ---
        if matched:
            item = CrawledPageItem()
            item["url"] = response.url
            item["referrer_anchor_text"] = ref_anchor
            item["status_code"] = response.status

            ctype = (response.headers.get(b"Content-Type") or b"").decode("latin-1")
            ctype = ctype.split(";")[0].strip().lower() if ctype else ""
            item["content_type"] = ctype

            body = response.body or b""
            item["content"] = bytes(body)

            if ctype == "text/html":
                title = response.css("title::text").get()
                item["html_title"] = _collapse_ws(title) if title else None
            else:
                item["html_title"] = None

            item["depth"] = response.meta.get("depth", 0)
            yield item

        # Content-Type を先に判定し、PDF は以降のリンク処理をスキップ
        ctype_header = (response.headers.get(b"Content-Type") or b"").decode("latin-1")
        ctype_header = ctype_header.split(";")[0].strip().lower() if ctype_header else ""
        if ctype_header.startswith("application/pdf") or response.url.lower().endswith(".pdf"):
            return

        # --- リンク抽出（LinkExtractor に寄せる） ---
        links = self._link_extractor.extract_links(response)

        # --- LLM による一括判定（任意） ---
        llm_dict = {}
        if self._llm_enabled and self._llm_prompt_template and links:
            title = _collapse_ws(response.css("title::text").get() or "")

            for chunk in _chunked(links, 50):
                links_text = "\n".join(
                    f"- anchor={_collapse_ws(link.text or '')}, url={link.url}" for link in chunk
                )
                prompt = self._llm_prompt_template.format(title=title, links=links_text)

                try:
                    llm_result = complete_text(
                        prompt,
                        provider=self._llm_provider,
                        model=self._llm_model,
                    )
                    if llm_result:
                        try:
                            part = json.loads(llm_result)
                            if isinstance(part, dict):
                                llm_dict.update(part)
                        except json.JSONDecodeError as e:
                            self.logger.warning(f"LLM応答のJSONパースに失敗しました（チャンク無視）: {e}")
                except Exception as e:
                    self.logger.warning(f"LLM一括判定に失敗しました（チャンク無視）: {e}")

        for link in links:
            text = _collapse_ws(link.text or "")
            will_follow = self._is_follow_anchor(text)

            # ルールにマッチしない場合は LLM の一括結果を参照
            if not will_follow:
                will_follow = bool(llm_dict.get(link.url, False))

            will_download = getattr(self, "_is_download_anchor")(text)

            if not will_follow:
                continue

            yield Request(
                url=link.url,
                callback=self.parse,
                meta={"referrer_anchor_text": text, "matched": will_download},
                # 従来通り: 通常はフィルタ有効。ダウンロード対象のみフィルタ無効。
                dont_filter=will_download,
            )
