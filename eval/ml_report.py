"""Phase 4 report: revenue forecast backtest (MAPE) + top anomalies for our 10 companies.

Prints the report and saves the same text to eval/ml_results.md.

Run:  python -m eval.ml_report
"""
from datetime import date
from pathlib import Path

import duckdb

from src.ml.anomaly import DB_PATH, MIN_DEVIATION, Z_THRESHOLD, find_anomalies
from src.ml.forecast import NotEnoughDataError, forecast_revenue
from src.rag.download_10k import COMPANIES

OUT = Path(__file__).with_name("ml_results.md")
NAMES = {"prophet": "Prophet", "naive": "Naive", "seasonal_naive": "Seasonal naive"}


def ours_total_note() -> str:
    """Number of companies in the database (for the report text)."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    n = con.execute("SELECT COUNT(*) FROM dim_company").fetchone()[0]
    con.close()
    return f"{n:,}"


def pct(x: float) -> str:
    return "n/a" if x != x else f"{x:.1f}%"  # x != x is True only for NaN


def main() -> None:
    lines = [f"# FinSight ML report ({date.today()})", "",
             "## Revenue forecast backtest (last 4 quarters held out, MAPE - lower is better)", "",
             "| Ticker | Quarters | Prophet | Naive | Seasonal naive | Winner |",
             "|---|---|---|---|---|---|"]
    notes, skipped = [], []

    for ticker, cik in COMPANIES.items():
        try:
            r = forecast_revenue(cik)
        except NotEnoughDataError as e:
            skipped.append(f"- {ticker}: {e}")
            continue
        m = r["mape"]
        lines.append(f"| {ticker} | {r['n_points']} | {pct(m['prophet'])} | {pct(m['naive'])} "
                     f"| {pct(m['seasonal_naive'])} | {NAMES[r['winner']]} |")
        notes += [f"- {ticker}: {w}" for w in r["warnings"]]

    if skipped:
        lines += ["", "Skipped (not enough data):", *skipped]
    if notes:
        lines += ["", "Warnings:", *notes]

    # Anomalies: year-over-year change judged against each company's own history
    everyone = find_anomalies()
    ours = everyone[everyone["cik"].isin(COMPANIES.values())]
    tickers = {cik: t for t, cik in COMPANIES.items()}
    unusual = ours[ours["category"] == "unusual change"]
    restated = ours[ours["category"] == "possible restatement"]
    n_all = (everyone["category"] == "unusual change").sum()

    lines += ["", "## Anomalies for our 10 companies", "",
              "Method: year-over-year % change vs the company's own history. Flagged when "
              f"|z| > {Z_THRESHOLD:g} AND the change is at least {MIN_DEVIATION * 100:.0f} "
              "percentage points from its usual change. 'Size peers agree' (Isolation Forest "
              "per size bucket) is information only.",
              f"Flagged: {len(unusual)} for our 10 companies ({n_all:,} across all "
              f"{ours_total_note()} companies). Most extreme first.", "",
              "| Ticker | Metric | Period end | YoY change | Usual | z | Size peers agree | Reason |",
              "|---|---|---|---|---|---|---|---|"]
    for _, a in unusual.iterrows():
        lines.append(f"| {tickers[a['cik']]} | {a['metric']} | {a['period_end'].date()} "
                     f"| {a['pct_change'] * 100:+,.0f}% | {round(a['typical_change'] * 100):+d}% "
                     f"| {a['z_score']:+.1f} | {'yes' if a['if_agrees'] else 'no'} | {a['reason']} |")
    lines += ["", f"Possible restatements (negative derived Q4) among our 10 companies: {len(restated)}"]
    for _, a in restated.iterrows():
        lines.append(f"- {tickers[a['cik']]} {a['period_end'].date()}: {a['reason']}")

    text = "\n".join(lines)
    print(text)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main()
