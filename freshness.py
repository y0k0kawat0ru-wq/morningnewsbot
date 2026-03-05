from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from snapshot_collector import NewsItem


@dataclass
class FreshnessStats:
    total_input: int = 0
    passed: int = 0
    excluded_stale: int = 0
    excluded_no_date_jp: int = 0
    excluded_items: list[dict[str, str]] = field(default_factory=list)


def filter_fresh_news(
    items: list[NewsItem],
    now_jst: datetime,
    max_age_hours: int = 24,
) -> tuple[list[NewsItem], FreshnessStats]:
    """Filter news items by freshness.

    Rules:
    - JP news: published_at_jst is required; exclude if None
    - JP news: exclude if older than max_age_hours
    - Global news: exclude if published_at_jst exists and older than max_age_hours
    - Global news: keep if published_at_jst is None (cannot determine freshness)
    """
    stats = FreshnessStats(total_input=len(items))
    fresh: list[NewsItem] = []
    cutoff = now_jst - timedelta(hours=max_age_hours)

    for item in items:
        is_jp = item.category.startswith("jp_")

        # JP news with no published date → exclude
        if is_jp and item.published_at_jst is None:
            stats.excluded_no_date_jp += 1
            stats.excluded_items.append({
                "title": item.title,
                "source": item.source,
                "reason": "no_date_jp",
            })
            continue

        # Has published date and it's too old → exclude
        if item.published_at_jst is not None and item.published_at_jst < cutoff:
            stats.excluded_stale += 1
            stats.excluded_items.append({
                "title": item.title,
                "source": item.source,
                "reason": "stale",
                "published_at": item.published_at_jst.isoformat(),
            })
            continue

        fresh.append(item)

    stats.passed = len(fresh)
    return fresh, stats
