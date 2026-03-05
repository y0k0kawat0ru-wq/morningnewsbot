from __future__ import annotations

import re
import unicodedata
from hashlib import sha256
from typing import Any

from snapshot_collector import NewsItem


def normalize_title(title: str) -> str:
    """Normalize a title for dedup comparison.

    - NFKC normalization (full-width → half-width)
    - Strip leading/trailing whitespace
    - Collapse consecutive whitespace
    - Remove trailing source name noise (e.g. " - 日経新聞", " | Reuters")
    - Lowercase
    """
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)
    t = t.strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*[\-|–—]\s*[^\-|–—]{2,30}$", "", t)
    return t.lower()


def make_dedupe_key(item: NewsItem) -> str:
    """Generate a stable dedup key for a news item.

    Priority: canonical_url > source + normalized_title.
    """
    if item.canonical_url:
        base = item.canonical_url
    else:
        base = f"{item.source}|{normalize_title(item.title)}"
    return sha256(base.encode("utf-8")).hexdigest()


def compute_diff_from_previous(
    news_items: list[NewsItem],
    prev_state: dict[str, Any],
) -> dict[str, Any]:
    """Compare current news items against previous state to find new items."""
    current_keys: list[str] = []
    new_items: list[NewsItem] = []
    prev_keys = set(prev_state.get("last_keys", []))

    for item in news_items:
        key = make_dedupe_key(item)
        current_keys.append(key)
        if key not in prev_keys:
            new_items.append(item)

    repeated_count = max(0, len(news_items) - len(new_items))

    return {
        "currentKeys": current_keys,
        "newItems": new_items,
        "repeatedCount": repeated_count,
    }
