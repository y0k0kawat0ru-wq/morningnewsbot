from datetime import datetime, timedelta, timezone

from deduper import make_dedupe_key, normalize_title
from snapshot_collector import NewsItem

JST = timezone(timedelta(hours=9))


def _make_item(**kwargs) -> NewsItem:
    defaults = {
        "title": "Test Article",
        "url": "https://example.com/article",
        "canonical_url": "https://example.com/article",
        "source": "example.com",
        "retrieved_at_jst": datetime.now(JST),
    }
    defaults.update(kwargs)
    return NewsItem(**defaults)


class TestNormalizeTitle:
    def test_strip_and_collapse_whitespace(self):
        assert normalize_title("  日経平均　上昇  ") == "日経平均 上昇"

    def test_nfkc_fullwidth_to_halfwidth(self):
        assert normalize_title("ＴＥＳＴ") == "test"

    def test_remove_trailing_source_name(self):
        assert normalize_title("ニュース速報 - 日経新聞") == "ニュース速報"
        assert normalize_title("Breaking News | Reuters") == "breaking news"

    def test_empty_string(self):
        assert normalize_title("") == ""

    def test_consecutive_spaces(self):
        assert normalize_title("a   b    c") == "a b c"


class TestMakeDedupeKey:
    def test_same_url_different_retrieved_times(self):
        """Same URL with different retrieval times should produce the same key."""
        now = datetime.now(JST)
        item1 = _make_item(retrieved_at_jst=now)
        item2 = _make_item(retrieved_at_jst=now + timedelta(hours=1))
        assert make_dedupe_key(item1) == make_dedupe_key(item2)

    def test_same_url_different_titles(self):
        """Same canonical URL should produce the same key regardless of title."""
        item1 = _make_item(title="Title A")
        item2 = _make_item(title="Title B")
        assert make_dedupe_key(item1) == make_dedupe_key(item2)

    def test_different_urls_different_keys(self):
        item1 = _make_item(canonical_url="https://example.com/a")
        item2 = _make_item(canonical_url="https://example.com/b")
        assert make_dedupe_key(item1) != make_dedupe_key(item2)

    def test_no_canonical_url_uses_source_and_title(self):
        """When canonical_url is empty, use source + normalized title."""
        item1 = _make_item(
            canonical_url="",
            source="nikkei.com",
            title="日経平均が上昇 - 日経新聞",
        )
        item2 = _make_item(
            canonical_url="",
            source="nikkei.com",
            title="日経平均が上昇　- 日経新聞",  # full-width space
        )
        assert make_dedupe_key(item1) == make_dedupe_key(item2)

    def test_no_canonical_url_different_sources(self):
        """Different sources should produce different keys even with same title."""
        item1 = _make_item(canonical_url="", source="nikkei.com", title="Test")
        item2 = _make_item(canonical_url="", source="reuters.com", title="Test")
        assert make_dedupe_key(item1) != make_dedupe_key(item2)
