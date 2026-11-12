"""Write eval/results.md from eval/routing.json and eval/results.jsonl.

Run:  python -m eval.report
"""
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "results.md"


from eval.scoring import status_of


def _pct(ok: int, n: int) -> str:
    return f"{ok}/{n} ({ok / n:.0%})" if n else "not run yet"


def _acc(records: list[dict]) -> str:
    """Accuracy over judged answers only: network/timeout errors say nothing about the agent."""
    judged = [r for r in records if status_of(r) != "error"]
    return _pct(sum(status_of(r) == "pass" for r in judged), len(judged))


def _errs(records: list[dict]) -> int:
    return sum(status_of(r) == "error" for r in records)


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
    judged = [r for r in results if status_of(r) != "error"]  # latency/calls of real answers only
    nj = len(judged)
    avg_latency = sum(r["latency_s"] for r in judged) / nj if nj else 0
    avg_calls = sum(r["llm_calls"] for r in judged) / nj if nj else 0
    zero_calls = sum(r["llm_calls"] == 0 for r in judged)
    n_err = _errs(results)
    total = {c: sum(q["category"] == c for q in questions) for c in {q["category"] for q in questions}}

    lines = [
        f"# FinSight evaluation ({date.today()})", "",
        f"Questions with a result: **{n}/{len(questions)}** "
        f"({nj} judged, {n_err} network/timeout error(s), {len(questions) - n} not run yet).", "",
        "Accuracy counts only judged answers: a network or timeout error means the agent never "
        "got to answer, so it is listed separately and retried on the next run.", "",
        "| Metric | Result | Network errors |", "|---|---|---|",
        f"| Routing accuracy (all questions, router only) | {_pct(n_route_ok, len(routing))} | - |",
        f"| SQL execution accuracy (of {total.get('sql', 0)}) | {_acc(sql)} | {_errs(sql)} |",
        f"| Docs accuracy: key facts + right filing (of {total.get('docs', 0)}) | {_acc(docs)} | {_errs(docs)} |",
        f"| SQL + docs \"why\" (of {total.get('sql+docs', 0)}) | {_acc(why)} | {_errs(why)} |",
        f"| Forecast / anomaly: route + no error (of {total.get('forecast/anomaly', 0)}) | {_acc(fa)} | {_errs(fa)} |",
        f"| Refuse / out of scope: route (of {total.get('refuse/out_of_scope', 0)}) | {_acc(ref)} | {_errs(ref)} |",
        f"| Average latency per judged question | {avg_latency:.1f} s | |",
        f"| Average LLM calls per judged question | {avg_calls:.2f} | |",
        f"| Judged answers with 0 LLM calls | {_pct(zero_calls, nj)} | |",
        "",
        "Scoring: SQL = same values as the reference result (any row order / column names); "
        "docs = all key facts present and an expected 10-K cited (keyword matching, no LLM judge).",
        "", "## Failures (wrong answers or wrong routes)", "",
    ]

    misrouted = [r for r in routing if not r["ok"]]
    failed = [r for r in results if status_of(r) == "fail"]
    errors = [r for r in results if status_of(r) == "error"]
    if not misrouted and not failed:
        lines.append("None so far.")
    for r in misrouted:
        lines.append(f"- **{r['id']}** (routing) {r['question']} - routed to {r['got']}, "
                     f"expected {r['expected']} ({r['method']}"
                     + (f", similarity {r['score']}" if r["score"] is not None else "") + ")")
    for r in failed:
        lines.append(f"- **{r['id']}** ({r['category']}) {r['question']} - {r['reason']}"
                     + (f"\n  - SQL: `{r['sql']}`" if r.get("sql") and r["category"] == "sql" else ""))

    lines += ["", "## Errors (network/timeout - not counted as failures, retried on the next run)", ""]
    if not errors:
        lines.append("None.")
    for r in errors:
        lines.append(f"- **{r['id']}** ({r['category']}) {r['question']} - {r['reason'][:220]}")

    remaining = sorted({q["id"] for q in questions} - {r["id"] for r in results})
    if remaining:
        lines += ["", "## Not answered yet", "", ", ".join(remaining)]

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
