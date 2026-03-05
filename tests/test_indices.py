from main import format_index_line
from snapshot_collector import IndexData


def _make_index(close: float, prev_close: float | None = None) -> IndexData:
    return IndexData(
        symbol="^spx",
        label="S&P500",
        date="2024-01-02",
        close=close,
        prev_date="2024-01-01" if prev_close is not None else None,
        prev_close=prev_close,
    )


class TestFormatIndexLine:
    def test_positive_diff(self):
        data = _make_index(close=5000.0, prev_close=4950.0)
        result = format_index_line("S&P500", data)
        assert "+50.00" in result
        assert "+1.01%" in result
        assert "5,000.00" in result

    def test_negative_diff(self):
        data = _make_index(close=4900.0, prev_close=5000.0)
        result = format_index_line("S&P500", data)
        assert "-100.00" in result
        assert "-2.00%" in result

    def test_no_change(self):
        data = _make_index(close=5000.0, prev_close=5000.0)
        result = format_index_line("S&P500", data)
        assert "+0.00" in result
        assert "+0.00%" in result

    def test_no_prev_close(self):
        data = _make_index(close=5000.0, prev_close=None)
        result = format_index_line("S&P500", data)
        assert "前日比取得不可" in result
        assert "5,000.00" in result

    def test_zero_prev_close_no_division_error(self):
        """prev_close=0 should show fallback, not crash."""
        data = _make_index(close=5000.0, prev_close=0.0)
        result = format_index_line("S&P500", data)
        assert "前日比取得不可" in result

    def test_large_values(self):
        data = _make_index(close=48739.41, prev_close=48619.06)
        result = format_index_line("Dow", data)
        assert "48,739.41" in result
        assert "+120.35" in result

    def test_small_fractional_change(self):
        data = _make_index(close=157.07, prev_close=156.62)
        result = format_index_line("ドル円", data)
        assert "157.07" in result
        assert "+0.45" in result
