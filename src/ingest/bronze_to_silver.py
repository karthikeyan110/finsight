"""Bronze -> Silver: clean the raw SEC EDGAR Financial Statement Data Sets.

Reads sub.txt (one row per filing) and num.txt (one row per reported number),
keeps only 10-K / 10-Q filings and USD values, removes duplicates, parses dates,
and writes Parquet files to data/silver/.

Run:  python src/ingest/bronze_to_silver.py
"""
from pathlib import Path

import pandas as pd

# Project root = two folders up from this file (src/ingest/ -> project root)
ROOT = Path(__file__).resolve().parents[2]
BRONZE = ROOT / "data" / "bronze"
SILVER = ROOT / "data" / "silver"

# Only the filing types we care about (annual and quarterly reports)
KEEP_FORMS = ["10-K", "10-Q"]

# Columns we actually need from each file (smaller = faster + less memory)
SUB_COLS = ["adsh", "cik", "name", "sic", "countryba", "form",
            "period", "fy", "fp", "filed", "accepted"]
NUM_COLS = ["adsh", "tag", "version", "ddate", "qtrs", "uom",
            "segments", "coreg", "value"]


def load_sub() -> pd.DataFrame:
    """Load filings, keep 10-K/10-Q, parse dates."""
    sub = pd.read_csv(BRONZE / "sub.txt", sep="\t", usecols=SUB_COLS,
                      dtype={"adsh": str, "cik": "int64", "sic": "Int64",
                             "form": str, "fp": str, "fy": "Int64"})
    sub = sub[sub["form"].isin(KEEP_FORMS)]
    sub = sub.drop_duplicates(subset="adsh")  # adsh = unique filing ID

    # Dates are stored as text like 20250930 -> convert to real dates
    sub["period"] = pd.to_datetime(sub["period"], format="%Y%m%d", errors="coerce")
    sub["filed"] = pd.to_datetime(sub["filed"], format="%Y%m%d", errors="coerce")
    sub["accepted"] = pd.to_datetime(sub["accepted"], errors="coerce")
    return sub.reset_index(drop=True)


def load_num(keep_adsh: set) -> pd.DataFrame:
    """Load numbers in chunks (the file is large), keep USD rows for kept filings."""
    parts = []
    reader = pd.read_csv(BRONZE / "num.txt", sep="\t", usecols=NUM_COLS,
                         dtype={"adsh": str, "tag": str, "version": str,
                                "ddate": str, "qtrs": "Int64", "uom": str,
                                "segments": str, "coreg": str, "value": "float64"},
                         chunksize=1_000_000)
    for chunk in reader:
        chunk = chunk[(chunk["uom"] == "USD") & chunk["adsh"].isin(keep_adsh)]
        parts.append(chunk)
    num = pd.concat(parts, ignore_index=True)

    num = num.dropna(subset=["value"])  # a number row without a value is useless
    num = num.drop_duplicates()
    num["ddate"] = pd.to_datetime(num["ddate"], format="%Y%m%d", errors="coerce")
    return num.reset_index(drop=True)


def main() -> None:
    SILVER.mkdir(parents=True, exist_ok=True)

    sub = load_sub()
    print(f"sub: {len(sub):,} 10-K/10-Q filings")

    num = load_num(set(sub["adsh"]))
    print(f"num: {len(num):,} USD values")

    sub.to_parquet(SILVER / "sub.parquet", index=False)
    num.to_parquet(SILVER / "num.parquet", index=False)
    print(f"Saved Parquet files to {SILVER}")


if __name__ == "__main__":
    main()
