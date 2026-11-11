"""Checks for the Gold layer (data/gold/finsight.duckdb)."""
from pathlib import Path

import duckdb
import pytest

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "gold" / "finsight.duckdb"
TABLES = ["dim_company", "dim_date", "fact_financials"]


@pytest.fixture(scope="module")
def con():
    # Open read-only so the test can never change the data
    assert DB_PATH.exists(), "Run the Phase 1 scripts first"
    c = duckdb.connect(str(DB_PATH), read_only=True)
    yield c
    c.close()


@pytest.mark.parametrize("table", TABLES)
def test_table_exists_and_has_rows(con, table):
    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert count > 0


def test_fact_has_no_nulls(con):
    nulls = con.execute("""
        SELECT COUNT(*) FROM fact_financials
        WHERE cik IS NULL OR period_end IS NULL OR metric IS NULL OR value IS NULL
    """).fetchone()[0]
    assert nulls == 0
