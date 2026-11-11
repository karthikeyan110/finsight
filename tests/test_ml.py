"""Tests for Phase 4 (forecasting + anomaly detection). No Gemini calls."""
import numpy as np
import pandas as pd
import pytest

from src.ml.anomaly import detect, robust_z, size_bucket, yoy_changes
from src.ml.forecast import baseline_predictions, forecast_revenue, forecast_series, mape


def quarterly(values, start="2022-03-31"):
    """Small helper: turn a list of numbers into a quarterly ds/y series."""
    return pd.DataFrame({"ds": pd.date_range(start, periods=len(values), freq="QE"),
                         "y": [float(v) for v in values]})


# ---------- forecasting ----------

@pytest.mark.parametrize("quarters", [1, 2, 4])
def test_forecast_returns_requested_quarters(quarters):
    series = quarterly([100, 120, 110, 140, 105, 125, 115, 145, 110, 130, 120, 150])
    result = forecast_series(series, quarters=quarters)
    fc = result["forecast"]
    assert len(fc) == quarters
    assert (fc["ds"] > series["ds"].iloc[-1]).all()              # all in the future
    assert (fc["yhat_lower"] <= fc["yhat"]).all() and (fc["yhat"] <= fc["yhat_upper"]).all()
    assert set(result["mape"]) == {"prophet", "naive", "seasonal_naive"}


def test_range_is_at_least_backtest_width():
    # A noisy series, so the backtest errors are clearly bigger than Prophet's own range
    rng = np.random.default_rng(3)
    values = [100 * (1.03 ** i) * (1 + rng.normal(0, 0.08)) for i in range(14)]
    result = forecast_series(quarterly(values), quarters=3)
    q = np.quantile(result["backtest_abs_pct_errors"], 0.8)
    assert result["interval_pct"] == pytest.approx(q)
    fc = result["forecast"]
    # final range is at least as wide as yhat +/- q on both sides ...
    assert (fc["yhat_upper"] >= fc["yhat"] * (1 + q) - 1e-9).all()
    assert (fc["yhat_lower"] <= fc["yhat"] * (1 - q) + 1e-9).all()
    # ... and never narrower than Prophet's own range
    assert (fc["yhat_upper"] >= fc["prophet_upper"]).all()
    assert (fc["yhat_lower"] <= fc["prophet_lower"]).all()


def test_calibrate_keeps_prophet_range_when_wider():
    from src.ml.forecast import calibrate_interval
    fc = pd.DataFrame({"ds": [pd.Timestamp("2026-03-31")], "yhat": [100.0],
                       "yhat_lower": [50.0], "yhat_upper": [150.0]})  # Prophet: +/-50%
    out, q = calibrate_interval(fc, [0.05, 0.05, 0.05, 0.05])       # backtest: 5%
    assert out.loc[0, "yhat_lower"] == 50.0 and out.loc[0, "yhat_upper"] == 150.0
    assert out.loc[0, "range_source"] == "Prophet"


def test_forecast_revenue_real_company():
    result = forecast_revenue(1045810, quarters=2)  # NVIDIA
    assert len(result["forecast"]) == 2


def test_baselines_on_hand_made_series():
    # Train: two years with a clear pattern; test: the next 4 quarters
    train = quarterly([10, 20, 30, 40, 11, 21, 31, 41])
    test = quarterly([12, 22, 32, 42], start="2024-03-31")
    naive, seasonal = baseline_predictions(train, test)
    assert naive == [41, 41, 41, 41]          # last known quarter
    assert seasonal == [11, 21, 31, 41]       # same quarter, one year earlier


def test_mape():
    assert mape([100, 200], [110, 180]) == pytest.approx(10.0)  # (10% + 10%) / 2


# ---------- anomaly detection ----------

def company_rows(values, metric="Revenue", start="2022-03-31"):
    """One company's quarterly values as rows for yoy_changes()."""
    return pd.DataFrame({"cik": 1, "name": "TEST CO", "metric": metric,
                         "period_end": pd.date_range(start, periods=len(values), freq="QE"),
                         "value": [float(v) for v in values]})


def test_yoy_compares_same_quarter_last_year():
    # Strong seasonal pattern (Q4 peak) that grows 10% every year
    year1 = [10, 20, 30, 100]
    values = year1 + [v * 1.1 for v in year1] + [v * 1.21 for v in year1]
    changes = yoy_changes(company_rows(values))
    assert len(changes) == 8                                   # years 2 and 3 have a year-ago value
    assert np.allclose(changes["pct_change"], 0.10)            # always +10%, peak or not
    changes["size_bucket"] = ">$50B"
    assert detect(changes).empty                               # seasonal peaks are NOT flagged


def test_robust_z_flags_injected_outlier():
    rng = np.random.default_rng(0)
    pct = list(rng.normal(0.05, 0.01, 12))   # normally about +5% a year (+/- 1%)
    pct[7] = 0.80                            # injected outlier: +80%
    changes = pd.DataFrame({
        "cik": 1, "name": "TEST CO", "metric": "Revenue",
        "period_end": pd.date_range("2023-03-31", periods=12, freq="QE"),
        "prev_value": 100.0, "pct_change": pct, "size_bucket": "$1-50B"})
    changes["value"] = changes["prev_value"] * (1 + changes["pct_change"])

    flagged = detect(changes)
    assert len(flagged) == 1                          # only the outlier
    top = flagged.iloc[0]
    assert top["period_end"] == changes.loc[7, "period_end"]
    assert top["z_score"] > 4
    assert "Revenue rose 80% vs the same quarter last year" in top["reason"]


def test_small_move_at_steady_company_not_flagged():
    # Very steady company: always about +5% a year (+/- 0.1%), then one +3% quarter.
    # Its z-score is huge, but it's only 2 percentage points off -> must NOT be flagged.
    rng = np.random.default_rng(1)
    pct = list(rng.normal(0.05, 0.001, 12))
    pct[7] = 0.03
    changes = pd.DataFrame({
        "cik": 1, "name": "STEADY CO", "metric": "Revenue",
        "period_end": pd.date_range("2023-03-31", periods=12, freq="QE"),
        "prev_value": 100.0, "pct_change": pct, "size_bucket": "$1-50B"})
    changes["value"] = changes["prev_value"] * (1 + changes["pct_change"])
    scored = robust_z(changes)
    assert abs(scored.loc[7, "z_score"]) > 4      # statistically extreme ...
    assert detect(changes).empty                 # ... but too small a move to flag


def test_size_buckets():
    assert size_bucket(5e8) == "<$1B"
    assert size_bucket(1e10) == "$1-50B"
    assert size_bucket(2e11) == ">$50B"
    assert size_bucket(float("nan")) == "unknown"
