"""
Fetches oil-relevant headlines from RSS feeds and keeps track of which
ones the agent has already seen, so it doesn't re-react to old news.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

import feedparser
import requests
import urllib.parse
from bs4 import BeautifulSoup

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


def fetch_full_article(url: str, max_chars: int = 3500) -> dict:
    """
    Scrapes and extracts the clean main text of an article given its URL.
    Returns: {"url": str, "title": str, "content": str, "char_count": int}
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Decompose non-content elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "figure"]):
            tag.decompose()

        title_tag = soup.find("title")
        page_title = title_tag.get_text().strip() if title_tag else ""

        # Locate central article container if present
        article = (
            soup.find("article")
            or soup.find("div", {"id": lambda x: x and ("article" in x.lower() or "content" in x.lower())})
            or soup.find("div", {"class": lambda x: x and ("article" in x.lower() or "entry-content" in x.lower() or "post-content" in x.lower())})
            or soup.body
            or soup
        )

        paragraphs = []
        seen_paras = set()
        promo_filters = [
            "click here", "subscribe to", "cookie policy", "privacy policy",
            "all rights reserved", "advertisement", "sign up for",
        ]

        for p in article.find_all(["p", "h2", "h3"]):
            txt = p.get_text().strip()
            if len(txt) > 35 and txt not in seen_paras:
                txt_lower = txt.lower()
                if not any(promo in txt_lower for promo in promo_filters):
                    seen_paras.add(txt)
                    paragraphs.append(txt)

        content = "\n\n".join(paragraphs)
        if not content:
            content = "Could not cleanly extract paragraph text from page."

        if len(content) > max_chars:
            content = content[:max_chars] + "... [truncated]"

        return {
            "url": url,
            "title": page_title,
            "content": content,
            "char_count": len(content),
        }
    except Exception as e:
        return {"url": url, "error": f"Failed to fetch article: {str(e)}"}


def search_oil_news(query: str, max_results: int = 5) -> list[dict]:
    """
    Searches real-time news and web sources for oil-related topics,
    verifications, or official statements.
    Uses ddgs first, with fallback to Google News RSS search.
    """
    results = []

    # Attempt 1: ddgs news search
    try:
        from ddgs import DDGS
        ddgs = DDGS()
        items = list(ddgs.news(query, max_results=max_results))
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "summary": item.get("body", ""),
                "link": item.get("url", ""),
                "source": item.get("source", "Web News"),
                "date": item.get("date", ""),
            })
    except Exception:
        # Fall back to general ddgs text search if news search returned nothing or errored
        try:
            from ddgs import DDGS
            ddgs = DDGS()
            items = list(ddgs.text(f"oil {query}", max_results=max_results))
            for item in items:
                results.append({
                    "title": item.get("title", ""),
                    "summary": item.get("body", ""),
                    "link": item.get("href", ""),
                    "source": "Web Search",
                    "date": "",
                })
        except Exception:
            pass

    # Attempt 2: Google News RSS fallback (zero-dependency, unblocked)
    if not results:
        try:
            encoded = urllib.parse.quote(query)
            feed_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:max_results]:
                results.append({
                    "title": getattr(entry, "title", ""),
                    "summary": getattr(entry, "summary", "")[:350],
                    "link": getattr(entry, "link", ""),
                    "source": parsed.feed.get("title", "Google News"),
                    "date": getattr(entry, "published", ""),
                })
        except Exception:
            pass

    return results[:max_results]


if __name__ == "__main__":
    for h in fetch_headlines(max_results=5):
        print(f"- [{h['source']}] {h['title']}")

