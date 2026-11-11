"""Download the latest 10-K main document (HTML) for each company from SEC EDGAR.

Files are saved as data/docs/TICKER_10K_YEAR.htm (YEAR = year of the report period).

Run:  python -m src.rag.download_10k
"""
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "data" / "docs"

# SEC requires a User-Agent that identifies who is making the requests
HEADERS = {"User-Agent": "FinSight student project 110karthikeyan@gmail.com"}

# cik values come from dim_company in data/gold/finsight.duckdb
COMPANIES = {
    "AAPL": 320193, "MSFT": 789019, "AMZN": 1018724, "GOOGL": 1652044,
    "NVDA": 1045810, "TSLA": 1318605, "KO": 21344, "WMT": 104169,
    "JPM": 19617, "NKE": 320187,
}


def latest_10k(cik: int) -> tuple[str, str]:
    """Return (url, year) of the company's most recent 10-K main document."""
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    recent = requests.get(url, headers=HEADERS, timeout=30).json()["filings"]["recent"]
    for i, form in enumerate(recent["form"]):  # list is newest first
        if form == "10-K":
            accession = recent["accessionNumber"][i].replace("-", "")
            doc = recent["primaryDocument"][i]  # the main document, not exhibits
            year = recent["reportDate"][i][:4]
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}", year
    raise ValueError(f"No 10-K found for cik {cik}")


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for ticker, cik in COMPANIES.items():
        url, year = latest_10k(cik)
        time.sleep(0.2)  # SEC allows max 10 requests/second; stay well below
        html = requests.get(url, headers=HEADERS, timeout=60)
        html.raise_for_status()
        path = DOCS / f"{ticker}_10K_{year}.htm"
        path.write_bytes(html.content)
        print(f"{path.name:22} {len(html.content) / 1e6:6.2f} MB  {url}")
        time.sleep(0.2)


if __name__ == "__main__":
    main()
