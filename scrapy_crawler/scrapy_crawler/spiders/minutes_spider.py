import re
import os
from typing import Iterable
from urllib.parse import urlparse

import scrapy
from scrapy import Request
from scrapy.http import Response
from scrapy.exceptions import CloseSpider

from scrapy_crawler.items import CrawledPageItem


_MINUTES_LABEL = "議事録"


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _anchor_text(sel: scrapy.Selector) -> str:
    return _collapse_ws(" ".join([t.strip() for t in sel.xpath('.//text()').getall() if t.strip()]))


def is_minutes_exact(text: str) -> bool:
    return _collapse_ws(text) == _MINUTES_LABEL


class MinutesSpider(scrapy.Spider):
    name = "minutes"
    custom_settings = {
        # BFS 寄せ
        "DEPTH_PRIORITY": 1,
        "SCHEDULER_DISK_QUEUE": "scrapy.squeues.PickleFifoDiskQueue",
        "SCHEDULER_MEMORY_QUEUE": "scrapy.squeues.FifoMemoryQueue",
        # 404なども拾って保存したい場合
        "HTTPERROR_ALLOW_ALL": True,
        # robots.txt を守りたくない場合は False に（必要なら）
        # "ROBOTSTXT_OBEY": False,
    }

    handle_httpstatus_all = True

    def __init__(self, start_url: str, max_depth: int = 2, max_downloads: int = 100, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not start_url:
            raise CloseSpider("start_url is required")
        self.start_url = start_url
        try:
            self.max_downloads = int(max_downloads)
        except Exception:
            self.max_downloads = 100

        # 外部サイトに暴走しないように allowed_domains を自動設定（任意）
        netloc = urlparse(self.start_url).netloc
        self.allowed_domains = [netloc]

        self.downloaded_count = 0

    def start_requests(self) -> Iterable[Request]:
        yield Request(
            url=self.start_url,
            callback=self.parse,
            meta={"referrer_anchor_text": None, "matched": False},
            dont_filter=True,
        )

    def parse(self, response: Response, **kwargs):
        matched = bool(response.meta.get("matched", False))
        ref_anchor = response.meta.get("referrer_anchor_text")

        # --- 保存処理（matched=True のとき） ---
        if matched:
            item = CrawledPageItem()
            item["url"] = response.url
            item["referrer_anchor_text"] = ref_anchor
            item["status_code"] = response.status
            ctype = response.headers.get(b"Content-Type") or b""
            ctype_str = ctype.decode("latin-1").split(";")[0].strip().lower()
            item["content_type"] = ctype_str
            item["content"] = bytes(response.body or b"")

            # HTML タイトルはあれば保存
            if ctype_str == "text/html":
                title = response.css("title::text").get()
                item["html_title"] = title.strip() if title else None
            else:
                item["html_title"] = None

            self.downloaded_count += 1
            yield item

            if self.downloaded_count >= self.max_downloads:
                raise CloseSpider("max_downloads_reached")

        for a in response.css("a[href]"):
            href = a.xpath("@href").get()
            if not href:
                continue

            parsed = urlparse(href)
            # http/https 以外は除外
            if parsed.scheme and parsed.scheme not in ("http", "https"):
                continue

            text = _anchor_text(a)
            will_match = is_minutes_exact(text)  # 「議事録」完全一致のみ保存対象化

            yield response.follow(
                href,
                callback=self.parse,
                meta={
                    "referrer_anchor_text": text,
                    "matched": will_match,
                },
            )
