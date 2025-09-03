# filter_loader.py
import os
import importlib
from crawler.filter import BaseSaveFilter


def load_filter() -> BaseSaveFilter:
    """
    環境変数 SAVE_FILTER からフィルタクラスをロードしてインスタンスを返す。

    受け付ける形式:
      - 未設定/空: 既定で crawler.minutes_filter.MinutesFilter
      - クラス名のみ: 例 "MinutesFilter" は crawler.minutes_filter から解決
      - module.ClassName: 例 "crawler.minutes_filter.MinutesFilter"
    """
    filter_name = os.getenv("SAVE_FILTER")

    if not filter_name or not filter_name.strip():
        module_name, class_name = "crawler.minutes_filter", "MinutesFilter"
    elif "." in filter_name:
        module_name, class_name = filter_name.rsplit(".", 1)
    else:
        # 短縮名は minutes_filter から解決
        module_name, class_name = "crawler.minutes_filter", filter_name.strip()

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ImportError(
            f"Failed to import module '{module_name}' for SAVE_FILTER='{filter_name}': {e}"
        ) from e

    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise AttributeError(
            f"Module '{module_name}' has no class '{class_name}' (SAVE_FILTER='{filter_name}')"
        ) from e

    if not issubclass(cls, BaseSaveFilter):
        raise TypeError(f"{class_name} is not a subclass of BaseSaveFilter")

    return cls()
