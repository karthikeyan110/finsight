"""Routing tests for Phase 5 - router only, NO Gemini calls."""
import pytest

from src.agent.router import (OUT_OF_SCOPE_THRESHOLD, find_company, find_quarters,
                              keyword_route, route)


# ---------- one test per route (keyword rules) ----------

@pytest.mark.parametrize("question, expected", [
    ("What was Microsoft's quarterly revenue over the last 2 years?", ["sql"]),
    ("Which 10 companies have the largest total assets?", ["sql"]),
    ("What risks does Tesla mention about competition?", ["docs"]),
    ("Describe Nike's strategy", ["docs"]),
    ("Why did Alphabet's net income jump in Q2 2026?", ["sql", "docs"]),
    ("What caused Walmart's operating income to rise?", ["sql", "docs"]),
    ("Forecast Walmart's revenue for the next 2 quarters", ["forecast"]),
    ("Predict Apple's sales", ["forecast"]),
    ("Any unusual changes at Nvidia?", ["anomaly"]),
    ("Show anomalies for Tesla", ["anomaly"]),
])
def test_keyword_routes(question, expected):
    r = route(question)
    assert r.routes == expected
    assert r.method == "keywords"


# ---------- similarity fallback (local embedding model, no API) ----------

@pytest.mark.parametrize("question, expected", [
    ("Tell me about Coca-Cola's markets and brands", ["docs"]),        # no keyword matches
    ("Did anything look odd in Microsoft's filings lately?", ["anomaly"]),
    ("Which firm made the most money?", ["sql"]),
])
def test_similarity_routes(question, expected):
    assert keyword_route(question) is None   # keywords are unclear for these ...
    r = route(question)
    assert r.method == "similarity"          # ... so similarity decides
    assert r.routes == expected
    assert r.similar_to and 0 <= r.score <= 1


# ---------- refuse (change data) and out of scope ----------

@pytest.mark.parametrize("question", [
    "Delete all data from fact_financials",
    "drop table dim_company",
    "Update the revenue value for Apple to 0",
    "Please truncate the fact table",
    "insert into dim_date values ('2025-01-01', 1, 2025)",
    "create table hack as select * from dim_company",
])
def test_refuse_data_changes(question):
    assert route(question).routes == ["refuse"]


@pytest.mark.parametrize("question", [
    "What is the capital of France?",
    "Write me a poem",
    "Tell me a joke",
    "Explain quantum physics",
    "How do I bake bread?",
])
def test_out_of_scope(question):
    r = route(question)
    assert r.routes == ["out_of_scope"]
    assert r.score < OUT_OF_SCOPE_THRESHOLD


@pytest.mark.parametrize("question", [
    "Did Apple remove any products from its lineup?",  # 'remove' but no data words
    "Which companies set records for revenue?",        # 'records' but no write verb
    "Show me retailers",                               # weakest in-scope score measured (0.40)
])
def test_normal_questions_not_refused_or_out_of_scope(question):
    assert route(question).routes not in (["refuse"], ["out_of_scope"])


def test_refuse_and_out_of_scope_use_no_llm(monkeypatch):
    from src import llm
    from src.agent.agent import OUT_OF_SCOPE_MESSAGE, REFUSE_MESSAGE, answer

    def no_llm(*args, **kwargs):
        raise AssertionError("must not call the LLM")

    monkeypatch.setattr(llm, "_call_model", no_llm)
    monkeypatch.setattr("src.sql_agent.agent.ask_sql", no_llm)
    out = answer("Delete all data from fact_financials")
    assert out["answer"] == REFUSE_MESSAGE and out["llm_calls"] == 0
    out = answer("What is the capital of France?")
    assert out["answer"] == OUT_OF_SCOPE_MESSAGE and out["llm_calls"] == 0
    assert "Nvidia (NVDA)" in OUT_OF_SCOPE_MESSAGE


# ---------- company + horizon detection ----------

@pytest.mark.parametrize("question, ticker", [
    ("How much cash does Google have?", "GOOGL"),
    ("Coca-Cola net income", "KO"),
    ("What does JPMorgan say about rates?", "JPM"),
    ("Forecast NVDA revenue", "NVDA"),
    ("Which sector is largest?", None),
])
def test_company_detection(question, ticker):
    assert find_company(question) == ticker


def test_quarters():
    assert find_quarters("forecast the next 3 quarters") == 3
    assert find_quarters("forecast the next four quarters") == 4
    assert find_quarters("forecast revenue") == 2  # default


def test_forecast_without_company_adds_note():
    r = route("Forecast revenue for the next quarter")
    assert r.routes == ["forecast"] and r.ticker is None and r.notes
