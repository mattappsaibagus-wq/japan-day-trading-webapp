from backtest import run_backtest
from conftest import make_session_bars


def test_backtest_runs_and_closes_intraday():
    frames = {"TEST.T": make_session_bars(n_sessions=40, drift=0.0005, seed=7)}
    report, cal, trades = run_backtest(frames, {"TEST.T": {"topix500": False}}, horizon=4)
    assert report["overall"]["trades"] == len(trades) > 0
    for t in trades:
        assert t["entry_time"][:10] == t["exit_time"][:10], "positions must not be held overnight"
        assert t["entry_time"][11:16] <= "15:15"
    assert sum(b["n"] for b in cal["buckets"]) > 0
    assert all(b["p_up"] is None or 0 <= b["p_up"] <= 1 for b in cal["buckets"])


def test_calibration_feeds_engine(tmp_path, monkeypatch):
    import json
    import quant_engine
    path = tmp_path / "cal.json"
    path.write_text(json.dumps({"15m": {"horizon_bars": 4, "min_samples": 50, "buckets": [
        {"lo": -100, "hi": 0, "n": 500, "p_up": 0.45}, {"lo": 0, "hi": 100, "n": 500, "p_up": 0.56}]}}))
    monkeypatch.setattr(quant_engine, "CALIBRATION_PATH", str(path))
    assert quant_engine.calibrated_probability(30, "15m")["p_up"] == 0.56
    assert quant_engine.calibrated_probability(100, "15m")["p_up"] == 0.56
    assert quant_engine.calibrated_probability(-5, "15m")["p_up"] == 0.45
    assert quant_engine.calibrated_probability(10, "5m") is None
