"""Download SEC EDGAR Financial Statement Data Sets (one zip per quarter).

Each quarter is unzipped into data/bronze/YYYYqN/ (sub.txt, num.txt, tag.txt, pre.txt).
Quarters that already have sub.txt and num.txt are skipped.

Run:  python -m src.ingest.download_fsds
"""
import io
import time
import zipfile
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
BRONZE = ROOT / "data" / "bronze"
URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{q}.zip"
HEADERS = {"User-Agent": "FinSight student project 110karthikeyan@gmail.com"}
N_QUARTERS = 12


def quarters_back_from_today(n: int) -> list[str]:
    """Quarter names like '2026q3', newest first, starting with the current quarter."""
    today = date.today()
    year, q = today.year, (today.month - 1) // 3 + 1
    names = []
    for _ in range(n):
        names.append(f"{year}q{q}")
        year, q = (year - 1, 4) if q == 1 else (year, q - 1)
    return names


def is_published(quarter: str) -> bool:
    """The SEC publishes a quarter only after it ends, so the newest may not exist yet."""
    r = requests.head(URL.format(q=quarter), headers=HEADERS, timeout=30)
    return r.status_code == 200


def main() -> None:
    # Find the last 12 quarters the SEC has actually published
    candidates = quarters_back_from_today(N_QUARTERS + 2)
    available = []
    for q in candidates:
        if len(available) == N_QUARTERS:
            break
        time.sleep(0.2)  # stay under SEC's 10 requests/second limit
        if is_published(q):
            available.append(q)
    print("Quarters:", ", ".join(sorted(available)))

    for q in sorted(available):
        folder = BRONZE / q
        if (folder / "sub.txt").exists() and (folder / "num.txt").exists():
            print(f"{q}: already downloaded, skipping")
            continue
        time.sleep(0.2)
        resp = requests.get(URL.format(q=q), headers=HEADERS, timeout=600)
        resp.raise_for_status()
        folder.mkdir(parents=True, exist_ok=True)
        # Unzip straight from memory (no zip file left on disk)
        zipfile.ZipFile(io.BytesIO(resp.content)).extractall(folder)
        print(f"{q}: downloaded {len(resp.content) / 1e6:.0f} MB zip")


if __name__ == "__main__":
    main()
