# minutes_filter.py
import os
import re
from typing import Optional

from crawler.filter import BaseSaveFilter


MINUTES_KEYWORDS = (
    # Japanese
    "議事録", "会議録", "会議", "議題", "議事次第", "出席者", "配布資料", "決定事項", "アジェンダ",
    # English
    "meeting minutes", "minutes", "agenda", "attendees", "action items", "decisions",
)

MINUTES_KEYWORDS_LOWER = tuple(kw.lower() for kw in MINUTES_KEYWORDS)


def anchor_is_minutes_like(anchor_text: str) -> bool:
    """Anchor text only matching for minutes-like links."""
    t = (anchor_text or "").strip().lower()
    if not t:
        return False
    return any(k in t for k in MINUTES_KEYWORDS_LOWER)


def llm_is_minutes_like(text: str, url: str) -> Optional[bool]:
    if os.getenv("ENABLE_LLM_FILTER", "0") != "1":
        return None
    # Placeholder for LLM integration
    return None


class MinutesFilter(BaseSaveFilter):
    def should_save(
        self,
        url: str,
        content_type: str,
        text: Optional[str],
        raw: Optional[bytes],
    ) -> bool:
        # Interpret `text` as anchor text for the link to this URL
        if anchor_is_minutes_like(text or ""):
            return True
        llm = llm_is_minutes_like(text or "", url)
        return bool(llm) if llm is not None else False
