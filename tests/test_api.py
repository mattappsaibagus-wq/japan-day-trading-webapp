import pandas as pd
import pytest

from conftest import make_session_bars


class FakeProvider:
    name, delay_minutes, realtime = "fake", 0, False

    def history(self, symbol, interval="15m", period="30d"):
        df = make_session_bars(seed=hash(symbol) % 100)
        if interval == "1d":
            df = df.resample("1D").agg({"Open": "first", "High": "max", "Low": "min",
                                        "Close": "last", "Volume": "sum"}).dropna()
            df = pd.concat([df] * 4)
            df.index = pd.bdate_range("2025-10-01", periods=len(df)).tz_localize("Asia/Tokyo")
        return df

    def history_batch(self, symbols, interval="15m", period="30d"):
        if "^N225" in symbols:
            idx = pd.bdate_range("2026-10-13", periods=5).tz_localize("Asia/Tokyo")
            return {"^N225": pd.DataFrame({"Close": [50000, 50100, 50200, 50300, 50600.0]}, index=idx),
                    "JPY=X": pd.DataFrame({"Close": [150, 150.2, 150.1, 150.3, 150.7]}, index=idx)}
        return {s: self.history(s, interval, period) for s in symbols}

    def info(self, symbol):
        return {}


@pytest.fixture
def client(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "provider", FakeProvider())
    app_module.CACHE["macro"] = {"timestamp": 0, "data": None}
    app_module.CACHE["screener"] = {"timestamp": 0, "data": None}
    return app_module.app.test_client()


def test_screener(client):
    data = client.get("/api/screener").get_json()
    assert data["count"] == 33
    s = data["stocks"][0]
    assert {"score", "signal", "vwap_dev_pct", "gap_pct", "prob_up"} <= s.keys()
    assert all(abs(a["score"]) >= abs(b["score"]) for a, b in zip(data["stocks"], data["stocks"][1:]))


@pytest.mark.parametrize("interval", ["5m", "15m", "1d"])
def test_stock_detail(client, interval):
    data = client.get(f"/api/stock/7203?interval={interval}").get_json()
    assert data["success"], data
    assert data["candles"] and data["prediction"]["levels"]["limit_up"]
    assert bool(data["vwap"]) == (interval != "1d")


def test_rejects_bad_input(client):
    assert client.get("/api/stock/../../etc?interval=15m").status_code in (400, 404)
    assert client.get("/api/stock/7203?interval=1h").status_code == 400
    assert client.get("/api/position-size?account=x").status_code == 400


def test_position_size_endpoint(client):
    r = client.get("/api/position-size?account=3000000&risk_pct=1&entry=1000&stop=980").get_json()
    assert r["shares"] == 1500


def test_macro_no_fake_fallback(client, monkeypatch):
    import app as app_module

    class Broken(FakeProvider):
        def history_batch(self, *a, **k):
            raise RuntimeError("down")
    monkeypatch.setattr(app_module, "provider", Broken())
    data = client.get("/api/macro").get_json()
    assert data.get("error") and "nikkei" not in data
