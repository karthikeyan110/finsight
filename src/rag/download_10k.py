"""Download the latest 10-Ks (main document, HTML) for each company from SEC EDGAR.

By default the 3 most recent 10-Ks: the latest plus the two previous fiscal years.
Files are saved as data/docs/TICKER_10K_YEAR.htm (YEAR = year of the report period,
i.e. the fiscal year). Files that already exist are skipped.

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


N_10K = 3  # latest + two previous fiscal years


def _10ks_in(block: dict, cik: int) -> list[tuple[str, str]]:
    """(url, year) of every 10-K in one block of the SEC filing list."""
    found = []
    for i, form in enumerate(block["form"]):  # newest first
        if form == "10-K":
            accession = block["accessionNumber"][i].replace("-", "")
            doc = block["primaryDocument"][i]  # the main document, not exhibits
            year = block["reportDate"][i][:4]
            found.append((f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}", year))
    return found


def recent_10ks(cik: int, n: int = N_10K) -> list[tuple[str, str]]:
    """Return (url, year) of the company's n most recent 10-K main documents, newest first.

    The SEC's "recent" list only holds a company's latest ~1,000 filings. Big filers
    (e.g. JPMorgan) file so much that older 10-Ks are in extra pages, so we read
    those pages too when needed.
    """
    data = requests.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                        headers=HEADERS, timeout=30).json()
    found = _10ks_in(data["filings"]["recent"], cik)
    for extra in data["filings"].get("files", []):
        if len(found) >= n:
            break
        time.sleep(0.2)
        page = requests.get(f"https://data.sec.gov/submissions/{extra['name']}",
                            headers=HEADERS, timeout=30).json()
        found += _10ks_in(page, cik)
    if not found:
        raise ValueError(f"No 10-K found for cik {cik}")
    return found[:n]


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for ticker, cik in COMPANIES.items():
        time.sleep(0.2)  # SEC allows max 10 requests/second; stay well below
        for url, year in recent_10ks(cik):
            path = DOCS / f"{ticker}_10K_{year}.htm"
            if path.exists():
                print(f"{path.name:22} already downloaded, skipping")
                continue
            time.sleep(0.2)
            html = requests.get(url, headers=HEADERS, timeout=60)
            html.raise_for_status()
            path.write_bytes(html.content)
            print(f"{path.name:22} {len(html.content) / 1e6:6.2f} MB  {url}")


if __name__ == "__main__":
    main()
