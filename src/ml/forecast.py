"""Quarterly revenue forecasting: Prophet vs two simple baselines.

forecast_revenue(cik, quarters=2) returns a dict:
  cik, n_points           - company and how many quarterly values were used
  excluded                - dates of negative values that were left out
  mape                    - backtest error (%) for "prophet", "naive", "seasonal_naive"
  winner                  - the method with the lowest MAPE
  forecast                - DataFrame: ds, yhat, yhat_lower, yhat_upper (80% interval)
  warnings                - plain-English data warnings (e.g. mixed revenue tags)

Backtest: hide the last 4 quarters, train on the rest, compare predictions with
the real values using MAPE (Mean Absolute Percentage Error, lower = better).
"""
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from prophet import Prophet

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "gold" / "finsight.duckdb"

HOLDOUT = 4          # quarters hidden for the backtest
MIN_POINTS = 8       # fewer quarterly values than this -> don't forecast
SEASON_TOLERANCE_DAYS = 20  # "same quarter last year" = 1 year earlier, +/- 20 days

log = logging.getLogger(__name__)
# Prophet / cmdstanpy print lots of progress messages; keep only warnings
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)


class NotEnoughDataError(ValueError):
    """Raised when a company has too few quarterly revenue values."""


def load_quarterly_revenue(cik: int) -> pd.DataFrame:
    """Quarterly Revenue (qtrs=1, incl. derived Q4s) as columns ds, y, source_tag, is_derived."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("""
        SELECT period_end AS ds, value AS y, source_tag, is_derived
        FROM fact_financials
        WHERE cik = ? AND metric = 'Revenue' AND qtrs = 1
        ORDER BY period_end
    """, [cik]).df()
    con.close()
    df["ds"] = pd.to_datetime(df["ds"])
    return df


def mape(actual, predicted) -> float:
    """Mean Absolute Percentage Error in % (0 = perfect). Skips missing predictions."""
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    ok = ~np.isnan(predicted)
    if not ok.any():
        return float("nan")
    return float(np.mean(np.abs((actual[ok] - predicted[ok]) / actual[ok])) * 100)


def baseline_predictions(train: pd.DataFrame, test: pd.DataFrame) -> tuple[list, list]:
    """Return (naive, seasonal_naive) predictions for each date in `test`.

    naive:          every prediction = the last known quarter
    seasonal naive: prediction = the value of the same quarter one year earlier
                    (looked up by date, so gaps in the series can't shift it)
    """
    naive = [float(train["y"].iloc[-1])] * len(test)
    seasonal = []
    for ds in test["ds"]:
        target = ds - pd.DateOffset(years=1)
        gap = (train["ds"] - target).abs()
        match = train[gap <= pd.Timedelta(days=SEASON_TOLERANCE_DAYS)]
        seasonal.append(float(match["y"].iloc[0]) if len(match) else float("nan"))
    return naive, seasonal


def _fit_prophet(history: pd.DataFrame) -> Prophet:
    # Yearly seasonality with fourier order 2: quarterly data has only 4 points per year,
    # so a simple yearly pattern is all it can support. Weekly/daily make no sense here.
    model = Prophet(yearly_seasonality=2, weekly_seasonality=False,
                    daily_seasonality=False, interval_width=0.80)
    model.fit(history[["ds", "y"]])
    return model


def forecast_series(series: pd.DataFrame, quarters: int = 2) -> dict:
    """Backtest + forecast for a ds/y series (no database needed; used by tests too)."""
    if len(series) < MIN_POINTS:
        raise NotEnoughDataError(f"only {len(series)} quarterly values (need {MIN_POINTS})")

    # 1) Backtest on the last 4 quarters
    train, test = series.iloc[:-HOLDOUT], series.iloc[-HOLDOUT:]
    prophet_pred = _fit_prophet(train).predict(test[["ds"]])["yhat"]
    naive, seasonal = baseline_predictions(train, test)
    scores = {
        "prophet": mape(test["y"], prophet_pred),
        "naive": mape(test["y"], naive),
        "seasonal_naive": mape(test["y"], seasonal),
    }
    valid = {k: v for k, v in scores.items() if not np.isnan(v)}
    winner = min(valid, key=valid.get)

    # 2) Real forecast: train on everything, predict the next quarters (month-end dates)
    model = _fit_prophet(series)
    last = series["ds"].iloc[-1]
    future = pd.DataFrame({"ds": [last + pd.DateOffset(months=3 * k) + pd.offsets.MonthEnd(0)
                                  for k in range(1, quarters + 1)]})
    forecast = model.predict(future)[["ds", "yhat", "yhat_lower", "yhat_upper"]]

    return {"n_points": len(series), "mape": scores, "winner": winner, "forecast": forecast}


def forecast_revenue(cik: int, quarters: int = 2) -> dict:
    """Forecast the next `quarters` quarters of revenue for company `cik`."""
    data = load_quarterly_revenue(cik)
    warnings = []

    # Revenue can't really be negative; a negative (derived) value means bad data
    negative = data[data["y"] < 0]
    for ds in negative["ds"]:
        log.warning("cik %s: excluded negative revenue value on %s", cik, ds.date())
    if len(negative):
        warnings.append(f"Excluded {len(negative)} negative revenue value(s).")
    data = data[data["y"] >= 0].reset_index(drop=True)

    # Mixed revenue tags (e.g. GOOGL) may measure revenue slightly differently
    tags = sorted(data["source_tag"].unique())
    if len(tags) > 1:
        warnings.append("Series mixes revenue tags (" + ", ".join(tags) +
                        "), so values may not be fully comparable.")

    result = forecast_series(data, quarters)
    return {"cik": cik, "excluded": [d.date() for d in negative["ds"]],
            "warnings": warnings, **result}
