import kronos_feed


def test_parse_keeps_only_kronos_forecasts():
    data = {
        "generated_at": "2026-10-19T08:14:06+00:00",
        "recommendations": [
            {"symbol": "6501.T", "details": [
                {"agent": "sector_agent", "forecast": None, "signals": []},
                {"agent": "kronos_agent", "signals": [{"type": "kronos_forecast_down"}],
                 "forecast": {"expected_move_pct": -1.1, "range_pct": [-2.0, 0.1], "path_agreement": 0.75,
                              "target_date": "2026-10-20", "last_bar_date": "2026-10-19",
                              "model": "NeoQuasar/Kronos-small"}},
            ]},
            {"symbol": "7203.T", "details": [{"agent": "trend_agent", "forecast": None}]},
        ],
    }
    feed = kronos_feed.parse(data)
    assert feed["generated_at"] == "2026-10-19T08:14:06+00:00"
    assert list(feed["forecasts"]) == ["6501.T"]
    fc = feed["forecasts"]["6501.T"]
    assert fc["direction"] == "down"
    assert fc["expected_move_pct"] == -1.1
    assert fc["target_date"] == "2026-10-20"


def test_fetch_failure_returns_empty_feed():
    feed = kronos_feed.fetch(url="http://127.0.0.1:9/nope.json", timeout=1)
    assert feed["forecasts"] == {}
    assert "error" in feed
