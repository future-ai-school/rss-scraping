# filter.py
from typing import Optional

class BaseSaveFilter:
    def should_save(
        self,
        url: str,
        content_type: str,
        text: Optional[str],
        raw: Optional[bytes],
    ) -> bool:
        raise NotImplementedError
