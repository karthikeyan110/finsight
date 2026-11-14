"""Tests for the v2 fixes: router keywords, company resolution, BM25, eval grading. No Gemini."""
import pytest

from src.agent.companies import ambiguity_message, resolve_companies, sql_hint
from src.agent.router import route
from src.rag.retrieve import BM25, expand, named_years
from eval.scoring import acceptable_routes, route_ok, score


# ---------- router: new docs keywords ----------

@pytest.mark.parametrize("question", [
    "What are Microsoft's reportable segments?",
    "How large was the one-time income tax charge Apple recorded because of the State Aid decision?",
    "What is Walmart's dividend policy?",
    "What legal proceedings does Alphabet describe?",
])
def test_docs_keywords(question):
    assert route(question).routes == ["docs"]


def test_why_question_still_goes_to_sql_and_docs():
    assert route("Why did Apple's net income fall in fiscal 2024?").routes == ["sql", "docs"]


# ---------- company resolution (exact cik, no ILIKE) ----------

@pytest.mark.parametrize("question, cik", [
    ("What was Coca-Cola's operating income in the quarter ending 2026-03-31?", 21344),
    ("What was Coca-Cola Consolidated's revenue?", 317540),        # longer name wins
    ("What was Johnson & Johnson's revenue?", 200406),             # not Johnson Outdoors/Controls
    ("What was General Motors' net income?", 1467858),             # not GM Financial
    ("How much cash does Google have?", 1652044),                  # alias
    ("What was Apple Hospitality REIT's revenue?", 1418121),       # not Apple Inc
])
def test_resolves_exact_company(question, cik):
    matches = resolve_companies(question)
    assert [m.cik for m in matches] == [cik]


def test_several_companies_in_one_question():
    ciks = [m.cik for m in resolve_companies("Compare Apple and Microsoft revenue")]
    assert ciks == [320193, 789019]
    assert "f.cik IN (320193, 789019)" in sql_hint(resolve_companies("Compare Apple and Microsoft revenue"))


def test_no_company_in_general_questions():
    assert resolve_companies("Which 5 companies had the largest total assets on 2026-06-30?") == []
    assert resolve_companies("How many companies are in the Mining sector?") == []


def test_same_name_twice_is_ambiguous():
    matches = resolve_companies("What was TechTarget's revenue?")
    assert matches[0].cik is None and len(matches[0].candidates) == 2
    assert "Which one do you mean" in ambiguity_message(matches[0])


def test_sql_hint_filters_on_cik():
    hint = sql_hint(resolve_companies("What was Coca-Cola's revenue?"))
    assert "f.cik = 21344" in hint and "ILIKE" in hint


# ---------- retrieval helpers ----------

def test_bm25_prefers_exact_rare_words():
    docs = ["revenue grew because of higher prices",
            "operating income rose, lapping opioid legal charges from last year",
            "the company has many employees"]
    scores = BM25(docs).scores("operating income opioid charges")
    assert scores.index(max(scores)) == 1


# A realistic chunk-length paragraph (~800 characters, like the real 10-K chunks)
RISK = ("We face strong competition for our products and services from other automobile "
        "manufacturers and technology companies. A significant and growing number of established "
        "and new automobile manufacturers, as well as other companies, have entered, or are reported "
        "to have plans to enter, the market for electric and other alternative fuel vehicles, "
        "including hybrid, plug-in hybrid and fully electric vehicles, as well as the market for "
        "self-driving technology and other vehicle applications and software platforms. In some "
        "cases, our competitors offer or will offer electric vehicles in important markets such as "
        "China and Europe, and have announced an intention to produce electric vehicles exclusively "
        "at some point in the future. Many of our competitors have significantly more or "
        "better-established resources than we do to devote to the design, development, "
        "manufacturing, distribution, promotion, sale and support of their products.")


def test_near_duplicates_across_years():
    from src.rag.retrieve import near_duplicates
    assert near_duplicates(RISK, RISK.replace("have entered", "has entered"))
    assert not near_duplicates(RISK, "Revenue grew because of higher prices for our vehicles.")


def test_dedupe_keeps_newest_filing_at_best_rank():
    from src.rag.retrieve import dedupe
    hits = [{"id": "a", "text": RISK, "meta": {"fiscal_year": 2023}, "score": 0.9},
            {"id": "b", "text": "Something different about energy storage.", "meta": {"fiscal_year": 2024}, "score": 0.8},
            {"id": "c", "text": RISK, "meta": {"fiscal_year": 2025}, "score": 0.7}]
    kept = dedupe(hits)
    assert [h["id"] for h in kept] == ["c", "b"]   # the 2025 copy, placed where the best copy was
    assert kept[0]["score"] == 0.9


def test_scale():
    from src.rag.retrieve import _scale
    assert _scale([2.0, 4.0, 3.0]) == [0.0, 1.0, 0.5]
    assert _scale([1.0, 1.0]) == [0.5, 0.5]


def test_why_query_expansion():
    q = expand("Why did Tesla's operating income decline in 2024?")
    assert "income from operations" in q and "primarily due to" in q


def test_named_years():
    assert named_years("Why did Apple's net income fall in fiscal 2024?") == [2024]
    assert named_years("What risks does Tesla mention?") == []


# ---------- eval grading: acceptable routes ----------

def test_acceptable_routes():
    q = {"category": "docs", "expected_routes": ["docs"],
         "acceptable_routes": [["docs"], ["sql", "docs"]]}
    assert route_ok(q, ["docs"]) and route_ok(q, ["sql", "docs"]) and not route_ok(q, ["sql"])
    plain = {"category": "docs", "expected_routes": ["docs"]}
    assert acceptable_routes(plain) == [["docs"]]
    ok, reason = score({**plain, "key_facts": [], "expected_filings": []}, {"routes": ["sql"]})
    assert not ok and reason.startswith("routed to")
