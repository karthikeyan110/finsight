"""Find unusual financial changes.

Method (per company, per metric):
  1. Year-over-year (YoY) % change: each quarter vs the SAME quarter one year earlier,
     so normal seasonal peaks (e.g. Apple's December quarter) don't look unusual.
  2. Main test - robust z-score against the company's OWN history:
        z = 0.6745 * (change - median) / MAD
     (median and MAD = median absolute deviation of that company's YoY changes for
     that metric; 0.6745 makes it comparable to a normal z-score).
     Flagged when |z| > 4 AND the change is >= 15 percentage points from the usual change.
  3. Information only - Isolation Forest trained only on companies of a similar size
     (by latest total assets: <$1B, $1-50B, >$50B). Reported as agrees yes/no;
     it does not affect whether a row is flagged.

find_anomalies(cik=None) returns flagged rows:
  cik, name, metric, period_end, prev_value, value, pct_change, typical_change,
  z_score, size_bucket, if_agrees, category, reason

Categories:
  "unusual change"        - |z| > 4 and >= 15 points from the company's usual change
  "possible restatement"  - a derived Q4 revenue that came out negative
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "gold" / "finsight.duckdb"

# metric -> which qtrs value is "one quarter" for it
METRICS = {
    "Revenue": 1, "NetIncomeLoss": 1, "OperatingIncomeLoss": 1,  # 3-month values
    "Assets": 0, "Liabilities": 0,                               # balance on period_end
}
Z_THRESHOLD = 4.0          # flag only if |z| > 4 ...
MIN_DEVIATION = 0.15       # ... AND the change is >= 15 percentage points from the usual change
MIN_HISTORY = 6            # need at least 6 YoY changes to judge "normal" for a company
YEAR_TOLERANCE_DAYS = 20   # "one year earlier" = 365 days +/- 20 (month-end / 52-53 week years)
CONTAMINATION = 0.01       # Isolation Forest: ~1% of changes per size bucket are unusual

# (upper limit of total assets, bucket name)
SIZE_BUCKETS = [(1e9, "<$1B"), (50e9, "$1-50B"), (float("inf"), ">$50B")]


def _money(x: float) -> str:
    """Format dollars in a short readable way, e.g. $1.23B."""
    for size, unit in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(x) >= size:
            return f"${x / size:,.2f}{unit}"
    return f"${x:,.0f}"


def size_bucket(total_assets: float) -> str:
    """Put a company in a size group by total assets."""
    if pd.isna(total_assets):
        return "unknown"
    for limit, name in SIZE_BUCKETS:
        if total_assets < limit:
            return name
    return SIZE_BUCKETS[-1][1]


def yoy_changes(values: pd.DataFrame) -> pd.DataFrame:
    """Add YoY % change to rows with columns cik, metric, period_end, value.

    For each row, find the same company + metric about one year earlier.
    Rows without a matching year-earlier value (or where it was 0) are dropped.
    """
    df = values.copy()
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["year_ago"] = df["period_end"] - pd.DateOffset(years=1)

    earlier = df[["cik", "metric", "period_end", "value"]].rename(
        columns={"period_end": "prev_date", "value": "prev_value"})
    # merge_asof = "find the closest date", here: closest to exactly one year earlier
    df = pd.merge_asof(df.sort_values("year_ago"), earlier.sort_values("prev_date"),
                       left_on="year_ago", right_on="prev_date", by=["cik", "metric"],
                       direction="nearest", tolerance=pd.Timedelta(days=YEAR_TOLERANCE_DAYS))

    df = df.dropna(subset=["prev_value"])
    df = df[df["prev_value"] != 0].copy()
    df["pct_change"] = (df["value"] - df["prev_value"]) / df["prev_value"].abs()
    return (df.drop(columns=["year_ago", "prev_date"])
              .sort_values(["cik", "metric", "period_end"]).reset_index(drop=True))


def robust_z(changes: pd.DataFrame) -> pd.DataFrame:
    """Add typical_change (median) and z_score per company + metric."""
    df = changes.copy()
    grp = df.groupby(["cik", "metric"])["pct_change"]
    df["typical_change"] = grp.transform("median")
    mad = (df["pct_change"] - df["typical_change"]).abs().groupby([df["cik"], df["metric"]]).transform("median")
    n = grp.transform("size")
    z = 0.6745 * (df["pct_change"] - df["typical_change"]) / mad
    # Not enough history, or a (practically) constant history -> can't judge.
    # 1e-9 instead of 0: rounding noise in the computer's arithmetic makes "constant" values
    # differ by ~1e-17, which would otherwise create enormous fake z-scores.
    df["z_score"] = z.where((n >= MIN_HISTORY) & (mad > 1e-9))
    return df


def isolation_forest_opinion(changes: pd.DataFrame) -> pd.Series:
    """True where Isolation Forest (trained per size bucket + metric) calls a change unusual."""
    agrees = pd.Series(False, index=changes.index)
    for _, part in changes.groupby(["size_bucket", "metric"]):
        if len(part) < 20:  # too few rows to train a meaningful model
            continue
        # Signed log squashes huge % changes (e.g. +50,000%) so they don't dominate
        x = (np.sign(part["pct_change"]) * np.log1p(part["pct_change"].abs())).to_frame()
        model = IsolationForest(contamination=CONTAMINATION, random_state=42).fit(x)
        agrees.loc[part.index] = model.predict(x) == -1
    return agrees


# Plain-English names for the reasons
PLAIN_NAMES = {"Revenue": "Revenue", "NetIncomeLoss": "Net income",
               "OperatingIncomeLoss": "Operating income", "Assets": "Total assets",
               "Liabilities": "Total liabilities"}


def _reason(r) -> str:
    """Plain-English explanation of one flagged change."""
    direction = "rose" if r["pct_change"] > 0 else "fell"
    typical = round(r["typical_change"] * 100)  # round first so we never print "-0%"
    company = str(r["name"]).title()  # "WALMART INC." -> "Walmart Inc."
    second = (f"It is unusual both for {company} itself and compared with similar-size companies."
              if r["if_agrees"] else
              f"Compared with similar-size companies this change is common, "
              f"but it is unusual for {company} itself.")
    return (f"{PLAIN_NAMES.get(r['metric'], r['metric'])} {direction} "
            f"{abs(r['pct_change']) * 100:,.0f}% vs the same quarter last year "
            f"({_money(r['prev_value'])} -> {_money(r['value'])}). "
            f"Its usual year-over-year change is {typical:+,d}%, so this is far outside "
            f"its normal range (z = {r['z_score']:+.1f}). {second}")


def detect(changes: pd.DataFrame) -> pd.DataFrame:
    """Score YoY changes and return the flagged ones, most extreme first.

    Flagged = |z| > 4 AND at least 15 percentage points away from the usual change.
    The second rule stops very steady companies being flagged for tiny moves
    (e.g. +3% instead of the usual +5%). if_agrees (size peers) is information only.

    `changes` needs: cik, name, metric, period_end, prev_value, value, pct_change, size_bucket.
    """
    df = robust_z(changes)
    df["if_agrees"] = isolation_forest_opinion(df)
    big_z = df["z_score"].abs() > Z_THRESHOLD
    big_move = (df["pct_change"] - df["typical_change"]).abs() >= MIN_DEVIATION
    flagged = df[big_z & big_move].copy()
    flagged["category"] = "unusual change"
    # (an empty table can't use apply(), so only build reasons when there are rows)
    flagged["reason"] = flagged.apply(_reason, axis=1) if len(flagged) else pd.Series(dtype=str)
    return flagged.reindex(flagged["z_score"].abs().sort_values(ascending=False).index)


def load_changes(con) -> pd.DataFrame:
    """YoY changes for every company + metric, with the company's size bucket."""
    parts = []
    for metric, qtrs in METRICS.items():
        parts.append(con.execute("""
            SELECT f.cik, c.name, f.metric, f.period_end, f.value
            FROM fact_financials f JOIN dim_company c ON f.cik = c.cik
            WHERE f.metric = ? AND f.qtrs = ?
              -- negative derived Q4 REVENUE is handled as "possible restatement";
              -- negative derived Q4 income can be a real loss, so it stays in
              AND NOT (f.metric = 'Revenue' AND f.is_derived AND f.value < 0)
        """, [metric, qtrs]).df())
    changes = yoy_changes(pd.concat(parts, ignore_index=True))

    # Size bucket from each company's most recent total assets
    latest_assets = con.execute("""
        SELECT cik, value AS assets FROM fact_financials
        WHERE metric = 'Assets' AND qtrs = 0
        QUALIFY ROW_NUMBER() OVER (PARTITION BY cik ORDER BY period_end DESC) = 1
    """).df()
    changes = changes.merge(latest_assets, on="cik", how="left")
    changes["size_bucket"] = changes["assets"].apply(size_bucket)
    return changes.drop(columns=["assets"])


def load_restatements(con) -> pd.DataFrame:
    """Derived Q4 REVENUE below zero -> 'possible restatement'.

    Only revenue: a negative derived Q4 net or operating income can be a genuine loss.
    """
    df = con.execute("""
        SELECT f.cik, c.name, f.metric, f.period_end, f.value
        FROM fact_financials f JOIN dim_company c ON f.cik = c.cik
        WHERE f.metric = 'Revenue' AND f.is_derived AND f.value < 0
    """).df()
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["category"] = "possible restatement"
    df["reason"] = df["value"].apply(
        lambda v: f"Derived Q4 revenue is negative ({_money(v)}): the annual total is smaller "
                  "than Q1-Q3 combined, which usually means earlier quarters were restated.")
    return df


def find_anomalies(cik: int | None = None) -> pd.DataFrame:
    """Flagged rows for one company (cik) or all companies."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    unusual = detect(load_changes(con))
    restated = load_restatements(con)
    con.close()

    result = pd.concat([unusual, restated], ignore_index=True)
    if cik is not None:
        result = result[result["cik"] == cik]
    cols = ["cik", "name", "metric", "period_end", "prev_value", "value", "pct_change",
            "typical_change", "z_score", "size_bucket", "if_agrees", "category", "reason"]
    return result[cols].reset_index(drop=True)
