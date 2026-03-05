from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from snapshot_collector import NewsItem

MAX_JP_FALLBACK = 5

JP_ALLOWLIST_DOMAINS = frozenset({
    "nikkei.com",
    "kabutan.jp",
    "reuters.com",
    "jp.reuters.com",
    "bloomberg.co.jp",
    "bloomberg.com",
    "nhk.or.jp",
    "tse.or.jp",
})


@dataclass
class FreshnessStats:
    total_input: int = 0
    passed: int = 0
    excluded_stale: int = 0
    excluded_no_date_jp: int = 0
    jp_fallback_used: bool = False
    jp_fallback_added: int = 0
    excluded_items: list[dict[str, str]] = field(default_factory=list)


def _is_jp(item: NewsItem) -> bool:
    return item.category.startswith("jp_")


def filter_fresh_news(
    items: list[NewsItem],
    now_jst: datetime,
    max_age_hours: int = 24,
) -> tuple[list[NewsItem], FreshnessStats]:
    """Filter news items by freshness with two-phase JP handling.

    Phase 1 (strict):
      - published_at_jst exists and within max_age_hours → pass
      - published_at_jst exists and older → exclude (stale)
      - published_at_jst is None, non-JP → pass if retrieved_at within cutoff
      - published_at_jst is None, JP → hold for Phase 2

    Phase 2 (JP fallback, only if Phase 1 yielded 0 JP articles):
      - Take JP items where published_at is None, retrieved_at within cutoff,
        and source is in the allowlist
      - Cap at MAX_JP_FALLBACK
    """
    stats = FreshnessStats(total_input=len(items))
    cutoff = now_jst - timedelta(hours=max_age_hours)

    fresh: list[NewsItem] = []
    jp_no_date_candidates: list[NewsItem] = []

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

        # No published date
        if item.published_at_jst is None:
            # retrieved_at too old → exclude regardless
            if item.retrieved_at_jst < cutoff:
                stats.excluded_no_date_jp += 1
                stats.excluded_items.append({
                    "title": item.title,
                    "source": item.source,
                    "reason": "no_date_stale_retrieval",
                })
                continue

            # JP + no date + recently retrieved → hold for Phase 2
            if _is_jp(item):
                jp_no_date_candidates.append(item)
                continue

        # Everything else passes Phase 1
        fresh.append(item)

    # Phase 2: JP fallback
    jp_in_phase1 = sum(1 for it in fresh if _is_jp(it))

    if jp_in_phase1 == 0 and jp_no_date_candidates:
        # Filter by allowlist
        allowed = [
            it for it in jp_no_date_candidates
            if it.source in JP_ALLOWLIST_DOMAINS
        ]
        rescued = allowed[:MAX_JP_FALLBACK]
        if rescued:
            fresh.extend(rescued)
            stats.jp_fallback_used = True
            stats.jp_fallback_added = len(rescued)
            print(f"[freshness] JP fallback activated: {len(rescued)} articles rescued")

        # Count remaining un-rescued candidates as excluded
        rescued_set = set(id(it) for it in rescued)
        for it in jp_no_date_candidates:
            if id(it) not in rescued_set:
                stats.excluded_no_date_jp += 1
                stats.excluded_items.append({
                    "title": it.title,
                    "source": it.source,
                    "reason": "no_date_jp_not_rescued",
                })
    else:
        # JP already has articles from Phase 1, or no candidates at all
        for it in jp_no_date_candidates:
            stats.excluded_no_date_jp += 1
            stats.excluded_items.append({
                "title": it.title,
                "source": it.source,
                "reason": "no_date_jp",
            })

    stats.passed = len(fresh)
    return fresh, stats
