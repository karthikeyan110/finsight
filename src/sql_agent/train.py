"""Train (teach) the Vanna agent about our database.

In Vanna 2.x, "training" means saving memories in the agent's memory store
(ChromaDB here):
  - text memories: table DDL + glossary (always shown to the LLM)
  - tool memories: example question -> SQL pairs (the 5 most similar are shown)

Run (re-run after editing training_examples.json):
  python -m src.sql_agent.train
"""
import asyncio
import json
from pathlib import Path

import duckdb

from src.sql_agent.agent import DB_PATH, build_memory, make_context

EXAMPLES_PATH = Path(__file__).with_name("training_examples.json")

# Plain-English meaning of words people use in questions
GLOSSARY = [
    "Money values in fact_financials.value are in US dollars (not thousands or millions).",
    "revenue / sales = metric 'Revenue' (always use metric = 'Revenue' for revenue questions; "
    "source_tag shows which original XBRL tag it came from).",
    "is_derived = true marks a fiscal Q4 value (Revenue, NetIncomeLoss or OperatingIncomeLoss) "
    "computed as annual minus Q1+Q2+Q3 (the company did not report Q4 on its own).",
    "profit / net income / earnings = metric 'NetIncomeLoss' (negative value = net loss).",
    "operating income / operating profit = metric 'OperatingIncomeLoss'.",
    "total assets = metric 'Assets'. total liabilities / debts = metric 'Liabilities'.",
    "cash = metric 'CashAndCashEquivalentsAtCarryingValue'.",
    "equity = Assets minus Liabilities for the same cik and period_end.",
    "margin = income metric divided by 'Revenue' for the same cik and period_end.",
    "quarterly values use qtrs=1, annual values use qtrs=4",
    "fact_financials.qtrs = number of quarters a value covers: 0 = balance on period_end (Assets, Liabilities, cash), "
    "1 = one quarter (3 months), 4 = full year. Always filter income metrics (Revenue, NetIncomeLoss, "
    "OperatingIncomeLoss) on qtrs, and never add qtrs=1 and qtrs=4 values together.",
    "dim_date.quarter and dim_date.year are the CALENDAR quarter/year of period_end. A company's fiscal quarter "
    "can differ (e.g. Apple's fiscal year ends in September, so period_end 2025-09-30 is Apple's fiscal Q4 / full year).",
    "'latest' means the row with the highest period_end for that company.",
    "When the question ends with 'Company: <name> (cik N)', ALWAYS filter with f.cik = N "
    "(or f.cik IN (...) for several companies) and never match names with ILIKE: several "
    "companies can share part of a name (e.g. Coca-Cola and Coca-Cola Consolidated).",
    "Find companies with name ILIKE '%name%' on dim_company.name only when no cik is given "
    "(names are upper case, e.g. 'APPLE INC').",
    "To put several metrics side by side use MAX(value) FILTER (WHERE metric = '...') grouped by company and period_end.",
    "sector values: Manufacturing; Finance, Insurance & Real Estate; Services; "
    "Transportation, Communications & Utilities; Retail Trade; Mining; Wholesale Trade; Construction; "
    "Agriculture, Forestry & Fishing; Unknown. country is a 2-letter code like 'US'.",
]


def get_ddl() -> list[str]:
    """Read the CREATE TABLE statements straight from the DuckDB file."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.execute("SELECT sql FROM duckdb_tables() ORDER BY table_name").fetchall()
    con.close()
    return [r[0] for r in rows]


async def train() -> None:
    memory = build_memory()
    ctx = make_context(memory)

    # Start fresh so re-running doesn't create duplicates
    await memory.clear_memories(ctx)

    for ddl in get_ddl():
        await memory.save_text_memory("DDL: " + ddl, ctx)
    for note in GLOSSARY:
        await memory.save_text_memory("Glossary: " + note, ctx)

    examples = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    for ex in examples:
        await memory.save_tool_usage(ex["question"], "run_sql", {"sql": ex["sql"]}, ctx)

    print(f"Trained: {len(get_ddl())} DDL, {len(GLOSSARY)} glossary notes, {len(examples)} examples")


if __name__ == "__main__":
    asyncio.run(train())
