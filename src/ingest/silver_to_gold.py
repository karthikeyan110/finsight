"""Silver -> Gold: build a small star schema in data/gold/finsight.duckdb.

Tables:
  dim_company     (cik, name, sector, country)
  dim_date        (period_end, quarter, year)
  fact_financials (cik, period_end, metric, qtrs, value, source_tag, is_derived)

qtrs = how many quarters a value covers:
  0 = balance-sheet value on period_end (Assets, Liabilities, Cash)
  1 = one quarter (3 months)
  4 = full year (12 months)

Revenue: companies use different XBRL tags for revenue. They are all mapped to one
metric "Revenue" (the original tag is kept in source_tag).

Missing fiscal Q4 values of Revenue, NetIncomeLoss and OperatingIncomeLoss are derived
as annual - (Q1 + Q2 + Q3) and marked is_derived = true.

Reads every quarter's Parquet file in data/silver/ with DuckDB (fast, low memory).

Run:  python src/ingest/silver_to_gold.py
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SILVER = ROOT / "data" / "silver"
GOLD = ROOT / "data" / "gold"
DB_PATH = GOLD / "finsight.duckdb"

# Revenue tags, in priority order: if a company reports several for the same
# period, the first one in this list wins. All become metric "Revenue".
REVENUE_TAGS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "RevenuesNetOfInterestExpense",  # used by banks
]

# Other metrics we keep (metric name = tag name)
OTHER_METRICS = [
    "NetIncomeLoss",
    "OperatingIncomeLoss",
    "Assets",
    "Liabilities",
    "CashAndCashEquivalentsAtCarryingValue",
]

# A fiscal year's Q1-Q3 end between 350 and 20 days before the fiscal-year end;
# Q4 ends on (or within a few days of) the fiscal-year end itself.
Q1_TO_Q3_WINDOW = (20, 350)
Q4_TOLERANCE_DAYS = 10

# Metrics that get a derived Q4 when the company didn't report one
DERIVE_Q4_METRICS = ["Revenue", "NetIncomeLoss", "OperatingIncomeLoss"]

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


def derive_q4(fact: pd.DataFrame, metric: str = "Revenue") -> pd.DataFrame:
    """Return new rows for a missing fiscal Q4 of `metric`: Q4 = annual - (Q1 + Q2 + Q3).

    Fiscal years are matched by date, not calendar year, so it works for companies
    whose year ends in e.g. January (NVDA, WMT), May (NKE), June (MSFT) or September (AAPL):
      - the annual value (qtrs=4) ends on the fiscal-year end date E
      - Q1, Q2, Q3 (qtrs=1) are the quarters ending 20-350 days before E
      - Q4 would end on E (within a few days)
    """
    rows = fact[fact["metric"] == metric]
    annual = rows[rows["qtrs"] == 4]
    quarterly = rows[rows["qtrs"] == 1]

    # Pair every annual value with every quarterly value of the same company
    pairs = annual.merge(quarterly, on="cik", suffixes=("_year", "_q"))
    days_before = (pairs["period_end_year"] - pairs["period_end_q"]).dt.days

    # Fiscal years that already have a Q4 -> nothing to derive
    has_q4 = pairs[days_before.abs() <= Q4_TOLERANCE_DAYS][["cik", "period_end_year"]].drop_duplicates()

    # Q1-Q3 of each fiscal year (must use the same revenue tag as the annual value,
    # so we never subtract numbers that measure revenue differently)
    low, high = Q1_TO_Q3_WINDOW
    q123 = pairs[(days_before >= low) & (days_before <= high)
                 & (pairs["source_tag_q"] == pairs["source_tag_year"])]
    sums = (q123.groupby(["cik", "period_end_year", "value_year", "source_tag_year"])
                .agg(n_quarters=("value_q", "size"), q123_total=("value_q", "sum"))
                .reset_index())
    sums = sums[sums["n_quarters"] == 3]  # need exactly Q1, Q2 and Q3

    # Keep only years without a Q4, then compute it
    sums = sums.merge(has_q4, on=["cik", "period_end_year"], how="left", indicator=True)
    sums = sums[sums["_merge"] == "left_only"]
    return pd.DataFrame({
        "cik": sums["cik"],
        "period_end": sums["period_end_year"],
        "metric": metric,
        "qtrs": 1,
        "value": sums["value_year"] - sums["q123_total"],
        "source_tag": sums["source_tag_year"],
        "is_derived": True,
    })


def main() -> None:
    GOLD.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    # Views over all quarters' silver files (nothing is loaded into memory yet)
    con.execute(f"CREATE OR REPLACE TEMP VIEW sub AS SELECT * FROM read_parquet('{(SILVER / 'sub' / '*.parquet').as_posix()}')")
    con.execute(f"CREATE OR REPLACE TEMP VIEW num AS SELECT * FROM read_parquet('{(SILVER / 'num' / '*.parquet').as_posix()}')")

    # dim_company: one row per company, details from its most recent filing
    companies = con.execute("""
        SELECT cik, name, sic, countryba AS country
        FROM sub
        QUALIFY ROW_NUMBER() OVER (PARTITION BY cik ORDER BY filed DESC, accepted DESC) = 1
    """).df()
    companies["sector"] = companies["sic"].apply(sic_to_sector)
    companies = companies[["cik", "name", "sector", "country"]]
    con.register("companies_df", companies)
    con.execute("CREATE OR REPLACE TABLE dim_company AS SELECT * FROM companies_df ORDER BY cik")

    # fact_financials: one value per (company, period_end, metric, qtrs).
    # - only our tags, standard us-gaap, whole-company totals (no segments/co-registrants)
    # - qtrs 0 (balance), 1 (quarter) or 4 (year); 2- and 3-quarter year-to-date values are dropped
    # - revenue tags become metric 'Revenue'; if several exist for one period, the
    #   highest-priority tag (order of REVENUE_TAGS) wins
    # - the same value often appears in several filings (e.g. last year's number repeated
    #   as a comparison); we keep the one from the most recently filed report
    all_tags = ", ".join(f"'{t}'" for t in REVENUE_TAGS + OTHER_METRICS)
    rev_tags = ", ".join(f"'{t}'" for t in REVENUE_TAGS)
    priority = " ".join(f"WHEN '{t}' THEN {i}" for i, t in enumerate(REVENUE_TAGS, 1))
    fact = con.execute(f"""
        SELECT s.cik, CAST(n.ddate AS DATE) AS period_end,
               CASE WHEN n.tag IN ({rev_tags}) THEN 'Revenue' ELSE n.tag END AS metric,
               CAST(n.qtrs AS INTEGER) AS qtrs, n.value,
               n.tag AS source_tag, FALSE AS is_derived
        FROM num n JOIN sub s ON n.adsh = s.adsh
        WHERE n.tag IN ({all_tags})
          AND n.version LIKE 'us-gaap%'
          AND n.segments IS NULL AND n.coreg IS NULL
          AND n.qtrs IN (0, 1, 4)
          -- Full-year values (qtrs=4) only from 10-Ks, ending on the filing's fiscal-year
          -- end (same month; the 10-K's prior-year comparison columns qualify too).
          -- Many 10-Qs also report trailing-twelve-month totals as qtrs=4 at every
          -- quarter-end (e.g. Amazon); those are NOT fiscal years, so they are dropped.
          AND (n.qtrs <> 4 OR (s.form = '10-K' AND MONTH(n.ddate) = MONTH(s.period)))
          AND n.ddate IS NOT NULL AND n.value IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY s.cik, n.ddate, metric, n.qtrs
            ORDER BY CASE n.tag {priority} ELSE 0 END, s.filed DESC, s.accepted DESC) = 1
    """).df()
    fact["period_end"] = pd.to_datetime(fact["period_end"])

    # Add derived Q4 rows (a negative derived Q4 net/operating income can be a real loss)
    derived = [derive_q4(fact, m) for m in DERIVE_Q4_METRICS]
    for m, d in zip(DERIVE_Q4_METRICS, derived):
        print(f"derived Q4 {m} values: {len(d):,}")
    fact = pd.concat([fact, *derived], ignore_index=True)
    fact["period_end"] = fact["period_end"].dt.date
    con.register("fact_df", fact)
    con.execute("""
        CREATE OR REPLACE TABLE fact_financials AS
        SELECT * FROM fact_df ORDER BY cik, period_end, metric, qtrs
    """)

    # dim_date: one row per period_end used in the fact table (calendar quarter/year)
    con.execute("""
        CREATE OR REPLACE TABLE dim_date AS
        SELECT DISTINCT period_end, QUARTER(period_end) AS quarter, YEAR(period_end) AS year
        FROM fact_financials ORDER BY period_end
    """)

    for name in ["dim_company", "dim_date", "fact_financials"]:
        print(f"{name}: {con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]:,} rows")
    con.close()
    print(f"Saved {DB_PATH}")


if __name__ == "__main__":
    main()
