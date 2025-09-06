import re
from typing import Iterable

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


def _context_text_for(sel: scrapy.Selector) -> str:
    # nearest LI/P/DIV ancestor text for context judgement
    context = sel.xpath("ancestor::*[self::li or self::p or self::div][1]//text()").getall()
    if not context:
        # Fallback to parent text
        context = sel.xpath("parent::*//text()").getall()
    return _collapse_ws(" ".join([t.strip() for t in context if t.strip()]))


def is_minutes_exact(text: str) -> bool:
    return _collapse_ws(text) == _MINUTES_LABEL


def is_text_link_under_minutes(sel: scrapy.Selector) -> bool:
    text = _anchor_text(sel)
    if text.upper() != "TEXT":
        return False
    ctx = _context_text_for(sel)
    # Must look like 議事録(...) and must not be 会議録
    if "会議録" in ctx:
        return False
    return bool(re.search(r"議事録\s*[（(].*[）)]", ctx))


class MinutesSpider(scrapy.Spider):
    name = "minutes"
    custom_settings = {
        # Ensure BFS at spider-level too
        "DEPTH_PRIORITY": 1,
        "SCHEDULER_DISK_QUEUE": "scrapy.squeues.PickleFifoDiskQueue",
        "SCHEDULER_MEMORY_QUEUE": "scrapy.squeues.FifoMemoryQueue",
        # Capture all statuses for persistence
        "HTTPERROR_ALLOW_ALL": True,
    }

    handle_httpstatus_all = True

    def __init__(self, start_url: str, max_depth: int = 2, max_downloads: int = 100, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not start_url:
            raise CloseSpider("start_url is required")
        self.start_url = start_url
        try:
            self.max_depth = int(max_depth)
        except Exception:
            self.max_depth = 2
        try:
            self.max_downloads = int(max_downloads)
        except Exception:
            self.max_downloads = 100

        self.downloaded_count = 0

    def start_requests(self) -> Iterable[Request]:
        yield Request(
            url=self.start_url,
            callback=self.parse,
            meta={"depth": 0, "referrer_anchor_text": None, "matched": False},
            dont_filter=True,
        )

    def parse(self, response: Response, **kwargs):
        # If this response corresponds to a matched anchor, persist it
        current_depth = int(response.meta.get("depth", 0))
        matched = bool(response.meta.get("matched", False))
        ref_anchor = response.meta.get("referrer_anchor_text")

        if matched:
            item = CrawledPageItem()
            item["url"] = response.url
            item["referrer_anchor_text"] = ref_anchor
            item["status_code"] = response.status
            ctype = response.headers.get(b"Content-Type") or b""
            ctype_str = ctype.decode("latin-1").split(";")[0].strip().lower()
            item["content_type"] = ctype_str
            item["content"] = bytes(response.body or b"")
            if ctype_str == "text/html":
                title = response.css("title::text").get()
                item["html_title"] = title.strip() if title else None
            elif ctype_str in ("application/pdf", "application/x-pdf"):
                item["html_title"] = None
            else:
                item["html_title"] = None
            item["depth"] = current_depth

            self.downloaded_count += 1
            yield item

            if self.downloaded_count >= self.max_downloads:
                raise CloseSpider("max_downloads_reached")

        # Stop expanding if depth limit reached according to requested semantics:
        # start_url depth=0, to reach one level below use max_depth=2
        # Allow scheduling children only if current_depth + 1 < max_depth
        if (current_depth + 1) >= self.max_depth:
            return

        # Discover and queue matching links (BFS ensured by settings)
        for a in response.css("a"):
            href = a.xpath("@href").get()
            if not href:
                continue
            text = _anchor_text(a)

            # Case 1: exact 議事録
            if is_minutes_exact(text):
                yield response.follow(
                    href,
                    callback=self.parse,
                    meta={
                        "depth": current_depth + 1,
                        "referrer_anchor_text": text,
                        "matched": True,
                    },
                )
                continue

            # Case 2: TEXT link under 議事録(TEXT, PDF) context
            if is_text_link_under_minutes(a):
                yield response.follow(
                    href,
                    callback=self.parse,
                    meta={
                        "depth": current_depth + 1,
                        "referrer_anchor_text": text,
                        "matched": True,
                    },
                )
                continue

