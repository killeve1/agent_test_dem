"""
Fetches oil-relevant headlines from RSS feeds and keeps track of which
ones the agent has already seen, so it doesn't re-react to old news.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

import feedparser

from config import RSS_FEEDS, OIL_KEYWORDS, SEEN_NEWS_PATH


def _headline_hash(title: str, link: str) -> str:
    return hashlib.sha256(f"{title}|{link}".encode("utf-8")).hexdigest()


def _load_seen() -> set:
    if not os.path.exists(SEEN_NEWS_PATH):
        return set()
    with open(SEEN_NEWS_PATH, "r") as f:
        return set(json.load(f))


def _save_seen(seen: set) -> None:
    os.makedirs(os.path.dirname(SEEN_NEWS_PATH), exist_ok=True)
    # Keep the seen-set from growing forever: retain the most recent 500 hashes
    trimmed = list(seen)[-500:]
    with open(SEEN_NEWS_PATH, "w") as f:
        json.dump(trimmed, f)


def _is_oil_relevant(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    return any(keyword in text for keyword in OIL_KEYWORDS)


def fetch_headlines(max_results: int = 10, only_new: bool = True) -> list[dict]:
    """
    Pull oil-relevant headlines from configured RSS feeds.

    Returns a list of dicts: {title, summary, link, source, published}
    ordered newest-first. If only_new is True, already-seen headlines
    (from previous runs) are excluded.
    """
    seen = _load_seen()
    results = []

    for feed_url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception:
            continue  # a single bad feed shouldn't kill the whole run

        for entry in parsed.entries:
            title = getattr(entry, "title", "").strip()
            summary = getattr(entry, "summary", "").strip()
            link = getattr(entry, "link", "").strip()
            if not title or not link:
                continue
            if not _is_oil_relevant(title, summary):
                continue

            h = _headline_hash(title, link)
            if only_new and h in seen:
                continue

            results.append({
                "title": title,
                "summary": summary[:400],
                "link": link,
                "source": parsed.feed.get("title", feed_url),
                "published": getattr(entry, "published", ""),
                "_hash": h,
            })

    # Mark everything returned as seen for next time
    for item in results:
        seen.add(item["_hash"])
    _save_seen(seen)

    # Strip internal hash field before returning to the agent/model
    for item in results:
        item.pop("_hash", None)

    return results[:max_results]


if __name__ == "__main__":
    for h in fetch_headlines(max_results=5):
        print(f"- [{h['source']}] {h['title']}")
