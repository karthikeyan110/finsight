"""FinSight agent: answer(question) -> dict.

1. The router (no LLM) picks the route: sql, docs, sql+docs, forecast or anomaly.
2. Only the needed tools run:
     sql       ask_sql      - 1 LLM call (writes the SQL; numbers come from the database)
     docs      ask_docs     - 1 LLM call (answers from 10-K excerpts)
     forecast  Prophet      - 0 LLM calls
     anomaly   statistics   - 0 LLM calls
3. The final answer is built from a template (table summary + doc answer + citations),
   NOT by another LLM call, so the LLM never does arithmetic.
At most 2 LLM calls per question (src/llm.py enforces this).

Run:  python -m src.agent.agent "Forecast Walmart's revenue for the next 2 quarters"
"""
import logging

import pandas as pd

from src import llm
from src.agent.router import route as pick_route

log = logging.getLogger(__name__)

REFUSE_MESSAGE = "FinSight is read-only — I can only answer questions about the data, not change it."
COMPANY_NAMES = ("Apple (AAPL), Microsoft (MSFT), Amazon (AMZN), Alphabet/Google (GOOGL), "
                 "Nvidia (NVDA), Tesla (TSLA), Coca-Cola (KO), Walmart (WMT), "
                 "JPMorgan (JPM) and Nike (NKE)")
OUT_OF_SCOPE_MESSAGE = (
    f"I can answer questions about the financials and 10-K filings of: {COMPANY_NAMES}. "
    "Try e.g. \"What was Microsoft's quarterly revenue over the last 2 years?\" or "
    "\"What risks does Tesla mention about competition?\"")


def _money(x: float) -> str:
    """$1.23B style (formatting done by Python, not the LLM)."""
    for size, unit in [(1e12, "T"), (1e9, "B"), (1e6, "M")]:
        if abs(x) >= size:
            return f"${x / size:,.2f}{unit}"
    return f"${x:,.0f}"


# ---------- tools ----------

def _run_sql(question: str, out: dict) -> None:
    from src.agent.companies import ambiguity_message, resolve_companies, sql_hint
    from src.sql_agent.agent import ask_sql
    # Resolve company names to exact ciks first, so the SQL filters on f.cik, not ILIKE
    matches = resolve_companies(question)
    unclear = [m for m in matches if m.cik is None]
    if unclear:  # several companies share that name: ask instead of guessing (0 LLM calls)
        out["errors"].append(ambiguity_message(unclear[0]))
        return
    out["companies"] = [(m.cik, m.name) for m in matches]
    try:
        sql, df = ask_sql(question + sql_hint(matches))
        out["sql"], out["table"] = sql, df
    except llm.DailyLimitReached as e:
        out["errors"].append(str(e))
    except Exception as e:  # noqa: BLE001 - show the problem, don't crash the app
        out["errors"].append(f"Numbers (SQL): {e}")


def _run_docs(question: str, ticker: str | None, out: dict, mode: str = "docs") -> None:
    from src.rag.ask import ask_docs
    try:
        out["docs"] = ask_docs(question, ticker, mode)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"Documents: {e}")


def _run_forecast(cik: int | None, quarters: int, out: dict) -> None:
    from src.ml.forecast import forecast_revenue, load_quarterly_revenue
    if cik is None:
        return  # the router already added a note asking for a company
    try:
        result = forecast_revenue(cik, quarters=quarters)
        history = load_quarterly_revenue(cik)
        result["history"] = history[history["y"] >= 0][["ds", "y"]]
        out["forecast"] = result
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"Forecast: {e}")


def _run_anomaly(cik: int | None, out: dict) -> None:
    from src.ml.anomaly import find_anomalies
    from src.rag.download_10k import COMPANIES
    try:
        df = find_anomalies(cik)
        if cik is None:  # no company named -> our 10 companies
            df = df[df["cik"].isin(COMPANIES.values())]
        out["anomalies"] = df.head(10)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"Anomalies: {e}")


# ---------- answer template ----------

def _compose(out: dict) -> str:
    parts = []

    if out.get("table") is not None:
        parts.append(f"**Numbers from the database:** {len(out['table'])} row(s), shown in the table below.")

    if out.get("docs"):
        d = out["docs"]
        text = f"**From the 10-K filings:** {d['answer']}"
        if d["citations"]:
            text += "\n\n**Sources:** " + "; ".join(
                f"[{c['ref']}] {c['filename']} - {c['location']}" for c in d["citations"])
        parts.append(text)

    if out.get("forecast"):
        f = out["forecast"]
        sources = set(f["forecast"]["range_source"])
        basis = ("range based on backtest errors" if sources == {"backtest errors"}
                 else "Prophet's range" if sources == {"Prophet"}
                 else "range from backtest errors or Prophet, whichever is wider")
        lines = [f"**Revenue forecast for {out['ticker']}** (Prophet, 80% {basis}):"]
        for _, row in f["forecast"].iterrows():
            lines.append(f"- Quarter ending {row['ds'].date()}: **{_money(row['yhat'])}** "
                         f"(range {_money(row['yhat_lower'])} to {_money(row['yhat_upper'])})")
        if "backtest errors" in sources:
            lines.append(f"\nThe range is ±{f['interval_pct'] * 100:.1f}%, the 80th percentile of "
                         "how far off the 4 backtest forecasts were (Prophet's own range was narrower).")
        m = f["mape"]
        lines.append(f"\nBacktest on the last 4 known quarters (average % error): Prophet "
                     f"{m['prophet']:.1f}%, naive {m['naive']:.1f}%, seasonal naive "
                     f"{m['seasonal_naive']:.1f}%. Most accurate: {f['winner'].replace('_', ' ')}.")
        lines += [f"\nNote: {w}" for w in f["warnings"]]
        parts.append("\n".join(lines))

    if out.get("anomalies") is not None:
        a = out["anomalies"]
        if a.empty:
            parts.append("**Anomalies:** none flagged.")
        else:
            parts.append(f"**Anomalies ({len(a)} shown, most unusual first):**\n" + "\n".join(
                f"- {r['name']}, {pd.Timestamp(r['period_end']).date()}: {r['reason']}"
                for _, r in a.iterrows()))

    if out["errors"]:
        parts.append("\n".join(f"⚠️ {e}" for e in dict.fromkeys(out["errors"])))
    if not parts:
        parts.append("I couldn't answer that. Try naming one of our 10 companies.")
    return "\n\n".join(parts)


def answer(question: str) -> dict:
    """Answer a question. Returns routes, tool results, the answer text and llm_calls."""
    llm.reset_calls()
    r = pick_route(question)
    out = {"question": question, "routes": r.routes, "ticker": r.ticker,
           "route_method": r.method, "similar_to": r.similar_to,
           "sql": None, "table": None, "docs": None, "forecast": None,
           "anomalies": None, "errors": list(r.notes)}

    # Refused / off-topic questions: fixed reply, no tools, 0 LLM calls
    if r.routes in (["refuse"], ["out_of_scope"]):
        out["answer"] = REFUSE_MESSAGE if r.routes == ["refuse"] else OUT_OF_SCOPE_MESSAGE
        out["llm_calls"] = 0
        log.info("Question %r: route=%s, LLM calls used=0", question, r.routes[0])
        return out

    if "sql" in r.routes:
        _run_sql(question, out)
    if "docs" in r.routes:
        # sql+docs = a "why did this number change" question: search the named year's MD&A
        _run_docs(question, r.ticker, out, mode="why" if "sql" in r.routes else "docs")
    if "forecast" in r.routes:
        _run_forecast(r.cik, r.quarters, out)
    if "anomaly" in r.routes:
        _run_anomaly(r.cik, out)

    out["answer"] = _compose(out)
    out["llm_calls"] = llm.calls_used()
    log.info("Question %r: route=%s, LLM calls used=%d", question, "+".join(r.routes), out["llm_calls"])
    return out


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    q = " ".join(sys.argv[1:]) or "Forecast Walmart's revenue for the next 2 quarters"
    result = answer(q)
    print(f"Route: {'+'.join(result['routes'])} ({result['route_method']}) | "
          f"company: {result['ticker']} | LLM calls used: {result['llm_calls']}")
    if result["sql"]:
        print(result["sql"])
        print(result["table"].head(10).to_string(index=False))
    print(result["answer"])
