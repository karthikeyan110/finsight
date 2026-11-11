"""Write eval/results.md from eval/routing.json and eval/results.jsonl.

Run:  python -m eval.report
"""
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "results.md"


def _pct(ok: int, n: int) -> str:
    return f"{ok}/{n} ({ok / n:.0%})" if n else "not run yet"


def main() -> None:
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    routing = json.loads((HERE / "routing.json").read_text(encoding="utf-8"))
    results_file = HERE / "results.jsonl"
    results = ([json.loads(l) for l in results_file.read_text(encoding="utf-8").splitlines() if l.strip()]
               if results_file.exists() else [])
    by_cat = lambda cat: [r for r in results if r["category"] == cat]  # noqa: E731

    n_route_ok = sum(r["ok"] for r in routing)
    sql, docs, why = by_cat("sql"), by_cat("docs"), by_cat("sql+docs")
    fa, ref = by_cat("forecast/anomaly"), by_cat("refuse/out_of_scope")
    n = len(results)
    avg_latency = sum(r["latency_s"] for r in results) / n if n else 0
    avg_calls = sum(r["llm_calls"] for r in results) / n if n else 0
    zero_calls = sum(r["llm_calls"] == 0 for r in results)
    total = {c: sum(q["category"] == c for q in questions) for c in {q["category"] for q in questions}}

    lines = [
        f"# FinSight evaluation ({date.today()})", "",
        f"Questions answered so far: **{n}/{len(questions)}** "
        f"({len(questions) - n} remaining - the Gemini free tier allows a limited number of calls per day).", "",
        "| Metric | Result |", "|---|---|",
        f"| Routing accuracy (all questions, router only) | {_pct(n_route_ok, len(routing))} |",
        f"| SQL execution accuracy | {_pct(sum(r['correct'] for r in sql), len(sql))} of {total.get('sql', 0)} |",
        f"| Docs accuracy (key facts + right filing) | {_pct(sum(r['correct'] for r in docs), len(docs))} of {total.get('docs', 0)} |",
        f"| SQL + docs (\"why\") | {_pct(sum(r['correct'] for r in why), len(why))} of {total.get('sql+docs', 0)} |",
        f"| Forecast / anomaly (route + no error) | {_pct(sum(r['correct'] for r in fa), len(fa))} of {total.get('forecast/anomaly', 0)} |",
        f"| Refuse / out of scope (route) | {_pct(sum(r['correct'] for r in ref), len(ref))} of {total.get('refuse/out_of_scope', 0)} |",
        f"| Average latency per question | {avg_latency:.1f} s |",
        f"| Average LLM calls per question | {avg_calls:.2f} |",
        f"| Answered with 0 LLM calls | {_pct(zero_calls, n)} |",
        "",
        "Scoring: SQL = same values as the reference result (any row order / column names); "
        "docs = all key facts present and an expected 10-K cited (keyword matching, no LLM judge).",
        "", "## Failures", "",
    ]

    misrouted = [r for r in routing if not r["ok"]]
    failed = [r for r in results if not r["correct"]]
    if not misrouted and not failed:
        lines.append("None so far.")
    for r in misrouted:
        lines.append(f"- **{r['id']}** (routing) {r['question']} - routed to {r['got']}, "
                     f"expected {r['expected']} ({r['method']}"
                     + (f", similarity {r['score']}" if r["score"] is not None else "") + ")")
    for r in failed:
        lines.append(f"- **{r['id']}** ({r['category']}) {r['question']} - {r['reason']}"
                     + (f"\n  - SQL: `{r['sql']}`" if r.get("sql") and r["category"] == "sql" else ""))

    remaining = sorted({q["id"] for q in questions} - {r["id"] for r in results})
    if remaining:
        lines += ["", "## Not answered yet", "", ", ".join(remaining)]

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
