"""Build eval/heldout_questions.json: 12 NEW held-out questions (same format as questions.json).

Frozen BEFORE any v2 fix, so v2 changes can be checked on questions they were not
tuned on. None of these are paraphrases of the 50 v1 questions:
  4 docs      new topics: business description, competition, legal proceedings, capital returns
  4 why       companies/years not in the v1 "why" set
  2 SQL       companies whose names overlap other companies (a naive ILIKE matches several)
  2 out of scope

Docs key facts were checked to appear in the listed 10-Ks; SQL answers are computed
from data/gold/finsight.duckdb now.

Run:  python -m eval.build_heldout
"""
import json
from pathlib import Path

import duckdb

from eval.build_questions import DB_PATH, _json_value, files, one

OUT = Path(__file__).with_name("heldout_questions.json")

JNJ, GM = 200406, 1467858  # Johnson & Johnson; General Motors Co

# 2 SQL: similar names (Johnson Outdoors / Johnson Controls; General Motors Financial)
SQL = [
    ("JNJ", "What was Johnson & Johnson's revenue in the quarter ending 2026-06-30?",
     one(JNJ, "Revenue", 1, "2026-06-30")),
    ("GM", "What was General Motors' net income in the quarter ending 2026-06-30?",
     one(GM, "NetIncomeLoss", 1, "2026-06-30")),
]

# 4 docs: (ticker, question, key facts (each = accepted spellings), expected filings, section)
DOCS = [
    ("TSLA", "What does Tesla say about its energy generation and storage business?",
     [["energy generation and storage"], ["megapack", "powerwall"]],
     files("TSLA", [2023, 2024, 2025]), "Item 1. Business"),
    ("WMT", "How does Walmart describe the competition it faces?",
     [["compet"], ["ecommerce", "omni-channel", "omnichannel"]],
     files("WMT", [2024, 2025, 2026]), "Item 1. Business / Item 1A. Risk Factors"),
    ("GOOGL", "What antitrust legal proceedings does Alphabet disclose?",
     [["antitrust"], ["department of justice", "doj"]],
     files("GOOGL", [2023, 2024, 2025]), "Item 3. Legal Proceedings / Item 8, legal matters note"),
    ("MSFT", "How does Microsoft return capital to its shareholders?",
     [["dividend"], ["repurchase"]],
     files("MSFT", [2024, 2025, 2026]), "Item 5 / Item 8, stockholders' equity note"),
]

# 4 why: companies/years not used in the v1 "why" questions
WHY = [
    ("KO", "Why did Coca-Cola's revenue grow in 2024?"),
    ("GOOGL", "Why did Alphabet's net income rise in 2024?"),
    ("AAPL", "Why did Apple's revenue increase in fiscal 2025?"),
    ("NKE", "Why did Nike's net income change in fiscal 2026?"),
]

# 2 out of scope
OUT_OF_SCOPE = [
    "Who painted the Mona Lisa?",
    "Give me a recipe for pancakes",
]


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    questions = []

    for i, (ticker, q, sql) in enumerate(SQL, 1):
        res = con.execute(sql)
        rows = [[_json_value(v) for v in row] for row in res.fetchall()]
        assert rows, f"reference SQL returned nothing: {q}"
        questions.append({"id": f"h_sql{i:02d}", "category": "sql", "ticker": ticker, "question": q,
                          "expected_routes": ["sql"], "reference_sql": sql,
                          "expected": {"columns": [d[0] for d in res.description], "rows": rows}})

    for i, (ticker, q, facts, filings, section) in enumerate(DOCS, 1):
        questions.append({"id": f"h_docs{i:02d}", "category": "docs", "ticker": ticker, "question": q,
                          "expected_routes": ["docs"], "key_facts": facts,
                          "expected_filings": filings, "expected_section": section})

    for i, (ticker, q) in enumerate(WHY, 1):
        questions.append({"id": f"h_why{i:02d}", "category": "sql+docs", "ticker": ticker, "question": q,
                          "expected_routes": ["sql", "docs"]})

    for i, q in enumerate(OUT_OF_SCOPE, 1):
        questions.append({"id": f"h_ref{i:02d}", "category": "refuse/out_of_scope", "ticker": "-",
                          "question": q, "expected_routes": ["out_of_scope"]})

    OUT.write_text(json.dumps(questions, indent=2), encoding="utf-8")
    print(f"Wrote {len(questions)} held-out questions to {OUT}")


if __name__ == "__main__":
    main()
