from datetime import datetime, timedelta, timezone

from freshness import JP_ALLOWLIST_DOMAINS, MAX_JP_FALLBACK, filter_fresh_news
from snapshot_collector import NewsItem

JST = timezone(timedelta(hours=9))


def _make_item(
    category: str = "us_macro",
    published_at: datetime | None = None,
    source: str = "example.com",
    retrieved_at: datetime | None = None,
    title: str = "Test Article",
) -> NewsItem:
    now = datetime.now(JST)
    return NewsItem(
        title=title,
        url=f"https://{source}/article",
        canonical_url=f"https://{source}/article",
        source=source,
        published_at_jst=published_at,
        retrieved_at_jst=retrieved_at or now,
        category=category,
    )


# ======================================================================
# Phase 1 basic tests
# ======================================================================

class TestFreshnessPhase1:
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
        """The filter uses strict less-than (published_at < cutoff), so an item
        published exactly 24 hours ago is NOT older than the cutoff and passes.
        """
        now = datetime.now(JST)
        item = _make_item(published_at=now - timedelta(hours=24))
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 1

    def test_jp_fresh_passes(self):
        now = datetime.now(JST)
        item = _make_item(
            category="jp_market",
            published_at=now - timedelta(hours=5),
            source="nikkei.com",
        )
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 1

    def test_jp_stale_excluded(self):
        now = datetime.now(JST)
        item = _make_item(
            category="jp_stock",
            published_at=now - timedelta(hours=30),
            source="nikkei.com",
        )
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

    def test_no_date_old_retrieval_excluded(self):
        """News without published_at and old retrieved_at should be excluded."""
        now = datetime.now(JST)
        item = _make_item(
            category="jp_market",
            published_at=None,
            source="nikkei.com",
            retrieved_at=now - timedelta(hours=25),
        )
        fresh, stats = filter_fresh_news([item], now)
        assert len(fresh) == 0
        assert stats.excluded_no_date_jp == 1


# ======================================================================
# Phase 2 JP fallback tests
# ======================================================================

class TestJPFallback:
    def test_no_fallback_when_jp_has_published_at(self):
        """If Phase 1 already yields at least 1 JP article, fallback is NOT activated."""
        now = datetime.now(JST)
        items = [
            # JP with published_at → passes Phase 1
            _make_item(
                category="jp_market",
                published_at=now - timedelta(hours=3),
                source="nikkei.com",
                title="Fresh JP",
            ),
            # JP without published_at → should be excluded (not rescued)
            _make_item(
                category="jp_market",
                published_at=None,
                source="kabutan.jp",
                title="No date JP",
            ),
        ]
        fresh, stats = filter_fresh_news(items, now)
        assert stats.jp_fallback_used is False
        assert stats.jp_fallback_added == 0
        # Only the one with published_at passes
        jp_titles = [it.title for it in fresh if it.category.startswith("jp_")]
        assert jp_titles == ["Fresh JP"]
        assert stats.excluded_no_date_jp == 1

    def test_fallback_activates_when_jp_is_zero(self):
        """When Phase 1 yields 0 JP articles, fallback rescues allowlisted items."""
        now = datetime.now(JST)
        items = [
            _make_item(category="us_macro", published_at=now - timedelta(hours=1)),
            _make_item(
                category="jp_market",
                published_at=None,
                source="nikkei.com",
                title="Rescued JP",
            ),
        ]
        fresh, stats = filter_fresh_news(items, now)
        assert stats.jp_fallback_used is True
        assert stats.jp_fallback_added == 1
        jp_items = [it for it in fresh if it.category.startswith("jp_")]
        assert len(jp_items) == 1
        assert jp_items[0].title == "Rescued JP"

    def test_fallback_rejects_non_allowlist_domain(self):
        """JP items from non-allowlisted domains are not rescued."""
        now = datetime.now(JST)
        items = [
            _make_item(
                category="jp_market",
                published_at=None,
                source="unknown-blog.jp",
                title="Untrusted",
            ),
        ]
        fresh, stats = filter_fresh_news(items, now)
        assert stats.jp_fallback_used is False
        assert stats.jp_fallback_added == 0
        assert len(fresh) == 0
        assert stats.excluded_no_date_jp == 1

    def test_fallback_caps_at_max(self):
        """Fallback rescues at most MAX_JP_FALLBACK items."""
        now = datetime.now(JST)
        items = [
            _make_item(
                category="jp_market",
                published_at=None,
                source="nikkei.com",
                title=f"JP article {i}",
            )
            for i in range(MAX_JP_FALLBACK + 3)
        ]
        fresh, stats = filter_fresh_news(items, now)
        assert stats.jp_fallback_used is True
        assert stats.jp_fallback_added == MAX_JP_FALLBACK
        jp_items = [it for it in fresh if it.category.startswith("jp_")]
        assert len(jp_items) == MAX_JP_FALLBACK
        # Remaining items counted as excluded
        assert stats.excluded_no_date_jp == 3

    def test_fallback_mixed_allowlist_and_non(self):
        """Only allowlisted domains are rescued; others are excluded."""
        now = datetime.now(JST)
        items = [
            _make_item(
                category="jp_market",
                published_at=None,
                source="nikkei.com",
                title="Allowed 1",
            ),
            _make_item(
                category="jp_market",
                published_at=None,
                source="random-site.com",
                title="Not allowed",
            ),
            _make_item(
                category="jp_market",
                published_at=None,
                source="kabutan.jp",
                title="Allowed 2",
            ),
        ]
        fresh, stats = filter_fresh_news(items, now)
        assert stats.jp_fallback_used is True
        assert stats.jp_fallback_added == 2
        assert stats.excluded_no_date_jp == 1
        jp_sources = {it.source for it in fresh if it.category.startswith("jp_")}
        assert jp_sources == {"nikkei.com", "kabutan.jp"}


# ======================================================================
# Mixed / stats tests
# ======================================================================

class TestMixedAndStats:
    def test_mixed_items_with_fallback(self):
        now = datetime.now(JST)
        items = [
            _make_item(category="us_macro", published_at=now - timedelta(hours=2)),   # pass
            _make_item(category="us_macro", published_at=now - timedelta(hours=30)),  # stale
            _make_item(                                                                # JP fallback
                category="jp_market", published_at=None,
                source="nikkei.com", title="Fallback JP",
            ),
        ]
        fresh, stats = filter_fresh_news(items, now)
        assert len(fresh) == 2  # 1 global + 1 JP fallback
        assert stats.excluded_stale == 1
        assert stats.jp_fallback_used is True
        assert stats.jp_fallback_added == 1
        assert stats.total_input == 3

    def test_stats_excluded_items_recorded(self):
        now = datetime.now(JST)
        item = _make_item(
            category="jp_market",
            published_at=None,
            source="nikkei.com",
            retrieved_at=now - timedelta(hours=25),
            title="Important News",
        )
        _, stats = filter_fresh_news([item], now)
        assert len(stats.excluded_items) == 1
        assert stats.excluded_items[0]["reason"] == "no_date_stale_retrieval"
        assert stats.excluded_items[0]["source"] == "nikkei.com"
