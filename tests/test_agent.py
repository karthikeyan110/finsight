"""Routing tests for Phase 5 - router only, NO Gemini calls."""
import pytest

from src.agent.router import find_company, find_quarters, keyword_route, route


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
