from snapshot_collector import IndexData, _parse_yahoo_chart_payload


class TestParseYahooChartPayload:
    def test_returns_current_and_previous_close(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1710460800, 1710547200, 1710633600],
                        "indicators": {
                            "quote": [
                                {
                                    "close": [5100.25, 5150.5, 5200.75],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }

        data, error = _parse_yahoo_chart_payload("S&P500", "^GSPC", payload)

        assert error is None
        assert isinstance(data, IndexData)
        assert data.close == 5200.75
        assert data.prev_close == 5150.5
        assert data.date == "2024-03-17"
        assert data.prev_date == "2024-03-16"

    def test_skips_null_close_and_uses_latest_valid_points(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1710460800, 1710547200, 1710633600, 1710719999],
                        "indicators": {
                            "quote": [
                                {
                                    "close": [157.2, 157.8, None, 158.1],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }

        data, error = _parse_yahoo_chart_payload("USDJPY", "USDJPY=X", payload)

        assert error is None
        assert isinstance(data, IndexData)
        assert data.close == 158.1
        assert data.prev_close == 157.8

    def test_returns_error_when_no_valid_rows_exist(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [1710460800, 1710547200],
                        "indicators": {"quote": [{"close": [None, None]}]},
                    }
                ],
                "error": None,
            }
        }

        data, error = _parse_yahoo_chart_payload("VIX", "^VIX", payload)

        assert data is None
        assert error == "no rows for ^VIX"
