from datetime import datetime, timedelta, timezone

from freshness import filter_fresh_news
from snapshot_collector import NewsItem

JST = timezone(timedelta(hours=9))


def _make_item(category: str = "us_macro", published_at: datetime | None = None) -> NewsItem:
    now = datetime.now(JST)
    return NewsItem(
        title="Test Article",
        url="https://example.com/article",
        canonical_url="https://example.com/article",
        source="example.com",
        published_at_jst=published_at,
        retrieved_at_jst=now,
        category=category,
    )


class TestFreshnessFilter:
    def test_fresh_item_passes(self):
        now = datetime.now(JST)
        item = _make_item(published_at=now - timedelta(hours=2))
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 1
        assert stats.passed == 1

    def test_stale_item_excluded(self):
        now = datetime.now(JST)
        item = _make_item(published_at=now - timedelta(hours=25))
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 0
        assert stats.excluded_stale == 1

    def test_exactly_24h_passes(self):
        """Item exactly at the cutoff boundary should pass.

        The filter uses strict less-than (published_at < cutoff), so an item
        published exactly 24 hours ago is NOT older than the cutoff and passes.
        """
        now = datetime.now(JST)
        item = _make_item(published_at=now - timedelta(hours=24))
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 1

    def test_jp_no_date_excluded(self):
        """JP news without published date should be excluded."""
        now = datetime.now(JST)
        item = _make_item(category="jp_market", published_at=None)
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 0
        assert stats.excluded_no_date_jp == 1

    def test_jp_fresh_passes(self):
        now = datetime.now(JST)
        item = _make_item(category="jp_market", published_at=now - timedelta(hours=5))
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 1

    def test_jp_stale_excluded(self):
        now = datetime.now(JST)
        item = _make_item(category="jp_stock", published_at=now - timedelta(hours=30))
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 0
        assert stats.excluded_stale == 1

    def test_global_no_date_passes(self):
        """Global news without published date should still pass."""
        now = datetime.now(JST)
        item = _make_item(category="us_macro", published_at=None)
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 1
        assert stats.passed == 1

    def test_mixed_items(self):
        now = datetime.now(JST)
        items = [
            _make_item(category="us_macro", published_at=now - timedelta(hours=2)),   # pass
            _make_item(category="us_macro", published_at=now - timedelta(hours=30)),  # stale
            _make_item(category="jp_market", published_at=None),                      # no date JP
            _make_item(category="jp_market", published_at=now - timedelta(hours=1)),  # pass
        ]
        fresh, stats = filter_fresh_news(items, now)
        assert len(fresh) == 2
        assert stats.excluded_stale == 1
        assert stats.excluded_no_date_jp == 1
        assert stats.total_input == 4

    def test_stats_excluded_items_recorded(self):
        now = datetime.now(JST)
        item = _make_item(category="jp_market", published_at=None)
        item.title = "Important News"
        item.source = "nikkei.com"
        _, stats = filter_fresh_news([item], now)
        assert len(stats.excluded_items) == 1
        assert stats.excluded_items[0]["reason"] == "no_date_jp"
        assert stats.excluded_items[0]["source"] == "nikkei.com"
