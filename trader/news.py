from __future__ import annotations

import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime


DEFAULT_FEEDS = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
)
POSITIVE = {"approval", "approved", "adoption", "partnership", "upgrade", "inflows", "record", "surge", "rally", "launch"}
NEGATIVE = {"hack", "hacked", "exploit", "lawsuit", "ban", "banned", "outflows", "fraud", "liquidation", "crash", "breach"}


@dataclass(frozen=True)
class NewsSignal:
    score: float
    positive_hits: int
    negative_hits: int
    fresh_headlines: int

    @property
    def blocks_new_positions(self) -> bool:
        return self.negative_hits >= 2 and self.score <= -0.35


class NewsMonitor:
    def __init__(self, feeds: tuple[str, ...] | None = None, cache_seconds: int = 600):
        configured = tuple(item.strip() for item in os.getenv("NEWS_RSS_FEEDS", "").split(",") if item.strip())
        self.feeds = feeds or configured or DEFAULT_FEEDS
        self.cache_seconds = cache_seconds
        self._cached_at = 0.0
        self._cached = NewsSignal(0.0, 0, 0, 0)

    def score(self) -> NewsSignal:
        now = time.time()
        if now - self._cached_at < self.cache_seconds:
            return self._cached
        titles: set[str] = set()
        for feed in self.feeds:
            try:
                request = urllib.request.Request(feed, headers={"User-Agent": "AI-Trading-App/1.0"})
                with urllib.request.urlopen(request, timeout=8) as response:
                    root = ET.fromstring(response.read())
                for item in root.findall(".//item")[:30]:
                    title = (item.findtext("title") or "").strip().lower()
                    published = item.findtext("pubDate")
                    if not title or not published:
                        continue
                    age = now - parsedate_to_datetime(published).timestamp()
                    if 0 <= age <= 21_600:
                        titles.add(title)
            except Exception:
                continue
        positive = sum(any(word in title for word in POSITIVE) for title in titles)
        negative = sum(any(word in title for word in NEGATIVE) for title in titles)
        total = positive + negative
        score = (positive - negative) / total if total else 0.0
        self._cached = NewsSignal(score, positive, negative, len(titles))
        self._cached_at = now
        return self._cached
