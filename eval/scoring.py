"""Scoring rules for the FinSight evaluation (no LLM judge - saves free quota).

score(question, record) -> (correct: bool, reason: str)

  sql               every reference column has a matching column in the generated
                    result (same values, any order, any column name) and the row
                    counts are equal; extra generated columns are allowed
  docs              the answer contains every key fact AND cites an expected filing
  sql+docs          routed to both, SQL returned rows, docs gave a real answer
                    citing one of that company's 10-Ks, and no errors
  forecast/anomaly  right route, the tool returned a result, no errors
  refuse/oos        right route
"""
from datetime import date, datetime

NOT_ANSWERED = ("Not found in the documents.", "Daily free limit reached, try again tomorrow.",
                "The AI model is unavailable right now, please try again in a minute.")


def _norm_value(v):
    """Make values comparable: numbers to 6 significant digits, dates to YYYY-MM-DD, text upper."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(f"{float(v):.6g}")
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    s = str(v).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":  # "2025-03-31" or "2025-03-31T00:00:00"
        return s[:10]
    try:
        return float(f"{float(s):.6g}")
    except ValueError:
        return s.upper()


def _column(rows, i):
    return sorted((_norm_value(r[i]) for r in rows), key=lambda x: (x is None, str(type(x)), str(x)))


def sql_matches(expected: dict, got_columns: list, got_rows: list) -> tuple[bool, str]:
    """Compare results ignoring row order and column names."""
    exp_rows = expected["rows"]
    if not got_rows:
        return False, "generated SQL returned no rows"
    if len(got_rows) != len(exp_rows):
        return False, f"row count {len(got_rows)} != expected {len(exp_rows)}"
    got_cols = [_column(got_rows, j) for j in range(len(got_columns))]
    for i, name in enumerate(expected["columns"]):
        if _column(exp_rows, i) not in got_cols:
            return False, f"no generated column matches expected column '{name}'"
    return True, "result matches reference"


def _norm_text(s: str) -> str:
    return (s or "").lower().replace("’", "'").replace("&", "and")


def docs_matches(q: dict, answer: str, citations: list) -> tuple[bool, str]:
    text = _norm_text(answer)
    missing = [alts[0] for alts in q["key_facts"] if not any(_norm_text(a) in text for a in alts)]
    cited = {c["filename"] for c in citations}
    if answer in NOT_ANSWERED:
        return False, f"no answer: {answer}"
    if missing:
        return False, "missing key facts: " + ", ".join(missing)
    if not cited & set(q["expected_filings"]):
        return False, f"cited {sorted(cited) or 'nothing'}, expected one of {q['expected_filings']}"
    return True, "key facts present and right filing cited"


def score(q: dict, r: dict) -> tuple[bool, str]:
    cat = q["category"]
    if r["routes"] != q["expected_routes"]:
        return False, f"routed to {r['routes']}, expected {q['expected_routes']}"

    if cat == "sql":
        if r.get("table") is None:
            return False, "no SQL result: " + "; ".join(r.get("errors") or ["unknown"])
        return sql_matches(q["expected"], r["table"]["columns"], r["table"]["rows"])

    if cat == "docs":
        docs = r.get("docs") or {}
        return docs_matches(q, docs.get("answer", ""), docs.get("citations", []))

    if cat == "sql+docs":
        if r.get("errors"):
            return False, "errors: " + "; ".join(r["errors"])
        if not r.get("table") or not r["table"]["rows"]:
            return False, "SQL part returned no rows"
        docs = r.get("docs") or {}
        if docs.get("answer") in NOT_ANSWERED or not docs.get("answer"):
            return False, f"docs part: {docs.get('answer') or 'no answer'}"
        if not any(c["filename"].startswith(q["ticker"] + "_") for c in docs.get("citations", [])):
            return False, f"docs part cites no {q['ticker']} 10-K"
        return True, "numbers + explanation with a citation"

    if cat == "forecast/anomaly":
        if r.get("errors"):
            return False, "errors: " + "; ".join(r["errors"])
        if r["routes"] == ["forecast"] and not r.get("forecast_quarters"):
            return False, "no forecast returned"
        return True, "tool ran without errors"

    return True, "routed correctly"  # refuse / out_of_scope
