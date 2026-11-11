"""Tests for the text-to-SQL agent (Phase 2)."""
import os

import pytest

from src.sql_agent.safety import UnsafeSQLError, make_safe


# ---------- Safety: no LLM needed ----------

@pytest.mark.parametrize("sql", [
    "DROP TABLE fact_financials",
    "DELETE FROM fact_financials",
    "UPDATE fact_financials SET value = 0",
    "INSERT INTO dim_date VALUES ('2025-01-01', 1, 2025)",
    "SELECT 1; DROP TABLE dim_company",  # sneaky second statement
])
def test_safety_rejects_non_select(sql):
    with pytest.raises(UnsafeSQLError):
        make_safe(sql)


def test_safety_adds_limit():
    assert "LIMIT 1000" in make_safe("SELECT * FROM dim_company")


def test_safety_keeps_existing_limit():
    safe = make_safe("SELECT * FROM dim_company LIMIT 5")
    assert "LIMIT 5" in safe and "LIMIT 1000" not in safe


# ---------- End-to-end: calls the LLM (needs LLM_API_KEY in .env) ----------

QUESTIONS = [
    "What is Apple's net income?",
    "Which 5 companies have the most total assets?",
    "How many companies are in the Mining sector?",
    "How much cash does Microsoft have?",
    "Which 3 sectors have the highest average net income?",
]


@pytest.mark.parametrize("question", QUESTIONS)
def test_ask_sql_returns_rows(question):
    from src.sql_agent.agent import ask_sql  # loads .env
    if not os.getenv("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set in .env")
    sql, df = ask_sql(question)
    print(f"\n{question}\n{sql}")
    assert sql.upper().startswith(("SELECT", "WITH"))
    assert not df.empty
