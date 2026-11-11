"""Silver -> Gold: build a small star schema in data/gold/finsight.duckdb.

Tables:
  dim_company     (cik, name, sector, country)
  dim_date        (period_end, quarter, year)
  fact_financials (cik, period_end, metric, value)

Run:  python src/ingest/silver_to_gold.py
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SILVER = ROOT / "data" / "silver"
GOLD = ROOT / "data" / "gold"
DB_PATH = GOLD / "finsight.duckdb"

# The only metrics (XBRL tags) we keep
METRICS = [
    "Revenues",
    "NetIncomeLoss",
    "OperatingIncomeLoss",
    "Assets",
    "Liabilities",
    "CashAndCashEquivalentsAtCarryingValue",
]

# Standard SIC "divisions": (first code, last code, sector name)
SIC_SECTORS = [
    (100, 999, "Agriculture, Forestry & Fishing"),
    (1000, 1499, "Mining"),
    (1500, 1799, "Construction"),
    (2000, 3999, "Manufacturing"),
    (4000, 4999, "Transportation, Communications & Utilities"),
    (5000, 5199, "Wholesale Trade"),
    (5200, 5999, "Retail Trade"),
    (6000, 6799, "Finance, Insurance & Real Estate"),
    (7000, 8999, "Services"),
    (9100, 9729, "Public Administration"),
    (9900, 9999, "Nonclassifiable"),
]


def sic_to_sector(sic) -> str:
    """Turn a 4-digit SIC code into a broad sector name."""
    if pd.isna(sic):
        return "Unknown"
    for low, high, sector in SIC_SECTORS:
        if low <= int(sic) <= high:
            return sector
    return "Unknown"


def build_dim_company(sub: pd.DataFrame) -> pd.DataFrame:
    """One row per company, using details from its most recent filing."""
    latest = sub.sort_values("filed").drop_duplicates("cik", keep="last")
    dim = latest[["cik", "name", "sic", "countryba"]].rename(columns={"countryba": "country"})
    dim["sector"] = dim["sic"].apply(sic_to_sector)
    return dim[["cik", "name", "sector", "country"]].reset_index(drop=True)


def build_fact(sub: pd.DataFrame, num: pd.DataFrame) -> pd.DataFrame:
    """One value per (company, period_end, metric)."""
    # Keep only our metrics, standard US-GAAP tags (not company-made custom tags),
    # and whole-company totals (no segment breakdowns, no co-registrants).
    df = num[num["tag"].isin(METRICS)
             & num["version"].str.startswith("us-gaap")
             & num["segments"].isna()
             & num["coreg"].isna()]

    # Attach filing info (company, form, report period, filing date)
    df = df.merge(sub[["adsh", "cik", "form", "period", "filed"]], on="adsh")

    # Keep only the filing's own period (drop prior-year comparison columns)
    df = df[df["ddate"] == df["period"]]

    # Pick the right time span:
    #   balance-sheet items (Assets, Liabilities, Cash) are a point in time -> qtrs = 0
    #   income items in a 10-Q -> the 3-month quarter (qtrs = 1)
    #   income items in a 10-K -> the full year (qtrs = 4)
    wanted_qtrs = df["form"].map({"10-Q": 1, "10-K": 4})
    df = df[(df["qtrs"] == 0) | (df["qtrs"] == wanted_qtrs)]

    # If a company filed more than once for the same period, keep the latest filing
    df = df.sort_values("filed").drop_duplicates(["cik", "ddate", "tag"], keep="last")

    fact = df.rename(columns={"ddate": "period_end", "tag": "metric"})
    fact = fact[["cik", "period_end", "metric", "value"]].dropna()
    return fact.reset_index(drop=True)


def build_dim_date(fact: pd.DataFrame) -> pd.DataFrame:
    """One row per period_end date that appears in the fact table."""
    dates = pd.DataFrame({"period_end": fact["period_end"].drop_duplicates().sort_values()})
    dates["quarter"] = dates["period_end"].dt.quarter  # calendar quarter 1-4
    dates["year"] = dates["period_end"].dt.year
    return dates.reset_index(drop=True)


def main() -> None:
    GOLD.mkdir(parents=True, exist_ok=True)
    sub = pd.read_parquet(SILVER / "sub.parquet")
    num = pd.read_parquet(SILVER / "num.parquet")

    dim_company = build_dim_company(sub)
    fact = build_fact(sub, num)
    dim_date = build_dim_date(fact)
    # Convert timestamps to plain dates so DuckDB stores them as DATE
    fact["period_end"] = fact["period_end"].dt.date
    dim_date["period_end"] = dim_date["period_end"].dt.date

    # Write each DataFrame into DuckDB (replacing old tables on re-run)
    con = duckdb.connect(str(DB_PATH))
    for name, df in [("dim_company", dim_company), ("dim_date", dim_date),
                     ("fact_financials", fact)]:
        con.register("tmp_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")
        print(f"{name}: {len(df):,} rows")
    con.close()
    print(f"Saved {DB_PATH}")


if __name__ == "__main__":
    main()
