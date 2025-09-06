# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class CrawledPageItem(scrapy.Item):
    url = scrapy.Field()
    referrer_anchor_text = scrapy.Field()
    status_code = scrapy.Field()
    content_type = scrapy.Field()
    content = scrapy.Field()
    html_title = scrapy.Field()
    depth = scrapy.Field()
