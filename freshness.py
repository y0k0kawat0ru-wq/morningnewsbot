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
    - If published_at_jst exists and older than max_age_hours → exclude
    - If published_at_jst is None → fall back to retrieved_at_jst for freshness check
    """
    stats = FreshnessStats(total_input=len(items))
    fresh: list[NewsItem] = []
    cutoff = now_jst - timedelta(hours=max_age_hours)

    for item in items:
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

        # No published date → use retrieved_at as fallback
        if item.published_at_jst is None and item.retrieved_at_jst < cutoff:
            stats.excluded_no_date_jp += 1
            stats.excluded_items.append({
                "title": item.title,
                "source": item.source,
                "reason": "no_date_stale_retrieval",
            })
            continue

        fresh.append(item)

    stats.passed = len(fresh)
    return fresh, stats
