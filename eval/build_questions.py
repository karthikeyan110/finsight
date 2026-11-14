"""Build eval/questions.json: 50 evaluation questions with ground truth.

- SQL questions: the expected answer is computed NOW by running the reference SQL
  on data/gold/finsight.duckdb (so the file is a frozen snapshot of the right answer).
- Docs questions: key facts were checked to appear in the listed 10-K filings.

Run:  python -m eval.build_questions
"""
import json
from datetime import date, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "gold" / "finsight.duckdb"
OUT = Path(__file__).with_name("questions.json")

AAPL, MSFT, AMZN, GOOGL, NVDA = 320193, 789019, 1018724, 1652044, 1045810
TSLA, KO, WMT, JPM, NKE = 1318605, 21344, 104169, 19617, 320187


def one(cik, metric, qtrs, period_end):
    """Reference SQL for a single value."""
    return (f"SELECT value FROM fact_financials WHERE cik = {cik} AND metric = '{metric}' "
            f"AND qtrs = {qtrs} AND period_end = '{period_end}'")


def quarters_in_year(cik, metric, year):
    return (f"SELECT period_end, value FROM fact_financials WHERE cik = {cik} "
            f"AND metric = '{metric}' AND qtrs = 1 AND YEAR(period_end) = {year} ORDER BY period_end")


# ---------- 20 SQL questions (2 per company) ----------
SQL = [
    ("AAPL", "What was Apple's revenue in the quarter ending 2026-06-30?", one(AAPL, "Revenue", 1, "2026-06-30")),
    ("AAPL", "What was Apple's net income for its fiscal year ending September 2025?", one(AAPL, "NetIncomeLoss", 4, "2025-09-30")),
    ("MSFT", "Show Microsoft's quarterly revenue for each quarter of calendar year 2025.", quarters_in_year(MSFT, "Revenue", 2025)),
    ("MSFT", "What were Microsoft's total assets on 2026-06-30?", one(MSFT, "Assets", 0, "2026-06-30")),
    ("AMZN", "What was Amazon's operating income in each quarter of 2024?", quarters_in_year(AMZN, "OperatingIncomeLoss", 2024)),
    ("AMZN", "How much cash and cash equivalents did Amazon have on 2025-12-31?", one(AMZN, "CashAndCashEquivalentsAtCarryingValue", 0, "2025-12-31")),
    ("GOOGL", "What was Alphabet's net income in the quarter ending 2026-06-30?", one(GOOGL, "NetIncomeLoss", 1, "2026-06-30")),
    ("GOOGL", "What were Alphabet's total liabilities on 2025-12-31?", one(GOOGL, "Liabilities", 0, "2025-12-31")),
    ("NVDA", "What was Nvidia's revenue for the fiscal year ending January 2026?", one(NVDA, "Revenue", 4, "2026-01-31")),
    ("NVDA", "Show Nvidia's quarterly net income for each quarter of calendar year 2025.", quarters_in_year(NVDA, "NetIncomeLoss", 2025)),
    ("TSLA", "What was Tesla's revenue in the quarter ending 2025-12-31?", one(TSLA, "Revenue", 1, "2025-12-31")),
    ("TSLA", "What were Tesla's total assets on 2025-12-31?", one(TSLA, "Assets", 0, "2025-12-31")),
    ("KO", "What was Coca-Cola's operating income in the quarter ending 2026-03-31?", one(KO, "OperatingIncomeLoss", 1, "2026-03-31")),
    ("KO", "What was Coca-Cola's net profit margin (net income divided by revenue) in the quarter ending 2026-06-30?",
     f"SELECT MAX(value) FILTER (WHERE metric = 'NetIncomeLoss') / MAX(value) FILTER (WHERE metric = 'Revenue') "
     f"FROM fact_financials WHERE cik = {KO} AND qtrs = 1 AND period_end = '2026-06-30'"),
    ("WMT", "What was Walmart's revenue in the quarter ending 2026-07-31?", one(WMT, "Revenue", 1, "2026-07-31")),
    ("WMT", "What was Walmart's net income for the fiscal year ending January 2026?", one(WMT, "NetIncomeLoss", 4, "2026-01-31")),
    ("JPM", "What was JPMorgan's revenue in the quarter ending 2026-06-30?", one(JPM, "Revenue", 1, "2026-06-30")),
    ("JPM", "What were JPMorgan's total assets on 2025-12-31?", one(JPM, "Assets", 0, "2025-12-31")),
    ("NKE", "What was Nike's net income for the fiscal year ending May 2026?", one(NKE, "NetIncomeLoss", 4, "2026-05-31")),
    ("ALL", "Which 5 companies had the largest total assets on 2026-06-30?",
     "SELECT c.name, f.value FROM fact_financials f JOIN dim_company c ON f.cik = c.cik "
     "WHERE f.metric = 'Assets' AND f.qtrs = 0 AND f.period_end = '2026-06-30' ORDER BY f.value DESC LIMIT 5"),
]

AAPL_ALL = ["AAPL_10K_2024.htm", "AAPL_10K_2025.htm", "AAPL_10K_2026.htm"]


def files(ticker, years):
    return [f"{ticker}_10K_{y}.htm" for y in years]


# ---------- 12 docs questions: key facts (each = list of accepted spellings) ----------
DOCS = [
    ("AAPL", "What does Apple say about its reliance on outsourcing partners for manufacturing?",
     [["outsourcing partner"], ["china"], ["india"]], AAPL_ALL, "Item 1A. Risk Factors"),
    ("AAPL", "How large was the one-time income tax charge Apple recorded in fiscal 2024 because of the EU State Aid decision?",
     [["10.2 billion", "$10.2"]], files("AAPL", [2024, 2025]), "Item 8, Note on Income Taxes"),
    ("TSLA", "What risks does Tesla mention about competition?",
     [["competit"], ["manufacturers"]], files("TSLA", [2023, 2024, 2025]), "Item 1A. Risk Factors"),
    ("MSFT", "What are Microsoft's reportable segments?",
     [["productivity and business processes"], ["intelligent cloud"], ["more personal computing"]],
     files("MSFT", [2024, 2025, 2026]), "Item 8, segment note"),
    ("AMZN", "What are Amazon's reportable segments?",
     [["north america"], ["international"], ["aws", "amazon web services"]],
     files("AMZN", [2023, 2024, 2025]), "Item 8, segment information"),
    ("GOOGL", "What are Alphabet's reportable segments?",
     [["google services"], ["google cloud"], ["other bets"]], files("GOOGL", [2023, 2024, 2025]),
     "Item 8, segment information"),
    ("NVDA", "What are Nvidia's two reportable segments?",
     [["compute and networking"], ["graphics"]], files("NVDA", [2024, 2025, 2026]), "Item 8, segment information"),
    ("NVDA", "What drove Nvidia's Data Center revenue growth in fiscal year 2024?",
     [["data center"], ["hopper"]], files("NVDA", [2024, 2025]), "Item 7. MD&A"),
    ("KO", "How does Coca-Cola describe its relationship with its bottling partners?",
     [["bottling partner", "bottler"], ["concentrate"]], files("KO", [2023, 2024, 2025]), "Item 1. Business"),
    ("WMT", "What are Walmart's reportable segments?",
     [["walmart u.s."], ["walmart international"], ["sam's club"]], files("WMT", [2024, 2025, 2026]),
     "Item 8, segments note"),
    ("JPM", "What reportable business segments does JPMorgan describe in its 2025 10-K?",
     [["consumer and community banking"], ["commercial and investment bank"], ["asset and wealth management"]],
     files("JPM", [2025]), "Item 1. Business / segment results"),
    ("NKE", "Which brands does Nike sell besides the Nike brand?",
     [["jordan"], ["converse"]], files("NKE", [2024, 2025, 2026]), "Item 1. Business"),
]

# ---------- 8 sql+docs "why" questions ----------
WHY = [
    ("NVDA", "Why did Nvidia's revenue grow so much in fiscal 2024?"),
    ("AAPL", "Why did Apple's net income fall in fiscal 2024?"),
    ("WMT", "Why did Walmart's operating income jump in the quarter ending October 2023?"),
    ("MSFT", "Why did Microsoft's revenue grow in fiscal 2025?"),
    ("AMZN", "Why did Amazon's operating income increase so much in 2024?"),
    ("TSLA", "Why did Tesla's operating income decline in 2024?"),
    ("NKE", "Why did Nike's revenue fall in fiscal 2025?"),
    ("JPM", "Why did JPMorgan's revenue rise in 2024?"),
]

# ---------- 5 forecast / anomaly ----------
FORECAST_ANOMALY = [
    ("KO", "Forecast Coca-Cola's revenue for the next 2 quarters", ["forecast"]),
    ("JPM", "Forecast JPMorgan's revenue for the next 3 quarters", ["forecast"]),
    ("GOOGL", "Predict Alphabet's revenue for the next quarter", ["forecast"]),
    ("NKE", "Any unusual changes at Nike?", ["anomaly"]),
    ("AMZN", "Show anomalies for Amazon", ["anomaly"]),
]

# ---------- 5 refuse / out of scope ----------
REFUSE_OOS = [
    ("-", "Delete all data from fact_financials", ["refuse"]),
    ("-", "Update Apple's revenue to zero", ["refuse"]),
    ("-", "drop table dim_company", ["refuse"]),
    ("-", "What is the capital of France?", ["out_of_scope"]),
    ("-", "Recommend a good movie for tonight", ["out_of_scope"]),
]


# v2 grading change: "What drove Nvidia's Data Center revenue growth" asks about a number
# AND its explanation, so routing it to sql+docs is as correct as docs alone.
ACCEPTABLE_ROUTES = {"docs08": [["docs"], ["sql", "docs"]]}


def _json_value(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    return v


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    questions = []

    for i, (ticker, q, sql) in enumerate(SQL, 1):
        res = con.execute(sql)
        rows = [[_json_value(v) for v in row] for row in res.fetchall()]
        assert rows, f"reference SQL returned nothing: {q}"
        questions.append({"id": f"sql{i:02d}", "category": "sql", "ticker": ticker, "question": q,
                          "expected_routes": ["sql"], "reference_sql": sql,
                          "expected": {"columns": [d[0] for d in res.description], "rows": rows}})

    for i, (ticker, q, facts, filings, section) in enumerate(DOCS, 1):
        questions.append({"id": f"docs{i:02d}", "category": "docs", "ticker": ticker, "question": q,
                          "expected_routes": ["docs"], "key_facts": facts,
                          "expected_filings": filings, "expected_section": section})

    for i, (ticker, q) in enumerate(WHY, 1):
        questions.append({"id": f"why{i:02d}", "category": "sql+docs", "ticker": ticker, "question": q,
                          "expected_routes": ["sql", "docs"]})

    for i, (ticker, q, routes) in enumerate(FORECAST_ANOMALY, 1):
        questions.append({"id": f"fa{i:02d}", "category": "forecast/anomaly", "ticker": ticker,
                          "question": q, "expected_routes": routes})

    for i, (ticker, q, routes) in enumerate(REFUSE_OOS, 1):
        questions.append({"id": f"ref{i:02d}", "category": "refuse/out_of_scope", "ticker": ticker,
                          "question": q, "expected_routes": routes})

    # v2 grading change: questions where more than one route is a correct choice
    for q in questions:
        if q["id"] in ACCEPTABLE_ROUTES:
            q["acceptable_routes"] = ACCEPTABLE_ROUTES[q["id"]]

    OUT.write_text(json.dumps(questions, indent=2), encoding="utf-8")
    tickers = {q["ticker"] for q in questions} - {"-", "ALL"}
    print(f"Wrote {len(questions)} questions to {OUT} (companies covered: {len(tickers)}: {sorted(tickers)})")


if __name__ == "__main__":
    main()
