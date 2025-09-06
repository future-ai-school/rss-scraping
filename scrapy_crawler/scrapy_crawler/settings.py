# Scrapy settings for scrapy_crawler project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://docs.scrapy.org/en/latest/topics/settings.html
#     https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://docs.scrapy.org/en/latest/topics/spider-middleware.html

import os
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


def _load_env():
    if load_dotenv:
        project_root = Path(__file__).resolve().parents[2]
        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path)


_load_env()

BOT_NAME = "scrapy_crawler"

SPIDER_MODULES = ["scrapy_crawler.spiders"]
NEWSPIDER_MODULE = "scrapy_crawler.spiders"

ADDONS = {}

# User agent and depth from env with defaults
USER_AGENT = os.getenv("USER_AGENT", os.getenv("CRAWLER_USER_AGENT", "ScrapyCrawler/1.0"))
DEPTH_LIMIT = int(os.getenv("DEPTH_LIMIT", "2"))
DOWNLOAD_TIMEOUT = int(os.getenv("TIMEOUT", os.getenv("CRAWLER_TIMEOUT", "20")))

# BFS scheduling
DEPTH_PRIORITY = 1
SCHEDULER_DISK_QUEUE = "scrapy.squeues.PickleFifoDiskQueue"
SCHEDULER_MEMORY_QUEUE = "scrapy.squeues.FifoMemoryQueue"

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# Concurrency and throttling (conservative defaults)
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1

# Pipelines
ITEM_PIPELINES = {
    "scrapy_crawler.pipelines.PostgresPipeline": 300,
}

FEED_EXPORT_ENCODING = "utf-8"
