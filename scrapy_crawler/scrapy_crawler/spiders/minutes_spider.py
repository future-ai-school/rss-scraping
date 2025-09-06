import re
from typing import Iterable, Optional

import scrapy
from scrapy import Request
from scrapy.http import Response
from scrapy.exceptions import CloseSpider

from scrapy_crawler.items import CrawledPageItem


# Download target keywords (anchor text)
TARGET_KEYWORDS = [
    "議事録",
    "会議録",
]


def _normalize_anchor_text(text: str) -> str:
    # Remove bracket contents: (...) or （...） and collapse whitespace
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def anchor_matches(text: Optional[str]) -> bool:
    if not text:
        return False
    norm = _normalize_anchor_text(text)
    for kw in TARGET_KEYWORDS:
        if kw in norm:
            return True
    return False


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
            item["content_type"] = ctype.decode("latin-1").split(";")[0].strip()
            item["content"] = bytes(response.body or b"")
            title = response.css("title::text").get()
            item["html_title"] = title.strip() if title else None
            item["depth"] = current_depth

            self.downloaded_count += 1
            yield item

            if self.downloaded_count >= self.max_downloads:
                raise CloseSpider("max_downloads_reached")

        # Stop expanding if depth limit reached
        if current_depth >= self.max_depth:
            return

        # Discover and queue matching links (BFS ensured by settings)
        for a in response.css("a"):
            href = a.xpath("@href").get()
            if not href:
                continue
            text = " ".join([t.strip() for t in a.xpath(".//text()").getall() if t.strip()])
            if not anchor_matches(text):
                continue

            yield response.follow(
                href,
                callback=self.parse,
                meta={
                    "depth": current_depth + 1,
                    "referrer_anchor_text": text,
                    "matched": True,
                },
            )
