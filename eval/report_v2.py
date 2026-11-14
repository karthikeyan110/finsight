"""Write eval/results_v2.md: v1 vs v2 on the 50 v1 questions, the 12 held-out questions
separately, the docs08 grading change, and the retrieval rank tables.

Inputs:
  v1        eval/results.jsonl + eval/routing.json            (v1 baseline, commit b3c146e)
  v2        eval/results_v2.jsonl + eval/routing_v2.json      (v2 code, same 50 questions)
  held-out  eval/results_heldout_v2.jsonl + eval/routing_heldout_v2.json
  ranks     eval/retrieval_check.md                           (python -m eval.retrieval_check)

Run:  python -m eval.report_v2
"""
import json
from datetime import date
from pathlib import Path

from eval.scoring import status_of

HERE = Path(__file__).parent
OUT = HERE / "results_v2.md"
CATEGORIES = [("sql", "SQL execution accuracy"), ("docs", "Docs: key facts + right filing"),
              ("sql+docs", "SQL + docs \"why\""), ("forecast/anomaly", "Forecast / anomaly"),
              ("refuse/out_of_scope", "Refuse / out of scope")]


def _load_jsonl(name: str) -> list[dict]:
    path = HERE / name
    if not path.exists():
        return []
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return list({r["id"]: r for r in records}.values())  # a later line for the same id wins


def _load_json(name: str):
    path = HERE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def summary(questions: list[dict], routing: list[dict], results: list[dict]) -> dict:
    """Per-category pass counts over judged answers (network errors left out)."""
    total = {c: sum(q["category"] == c for q in questions) for c, _ in CATEGORIES}
    out = {"routing": (sum(r["ok"] for r in routing), len(routing)) if routing else None}
    for cat, _ in CATEGORIES:
        judged = [r for r in results if r["category"] == cat and status_of(r) != "error"]
        out[cat] = (sum(status_of(r) == "pass" for r in judged), len(judged), total[cat])
    judged = [r for r in results if status_of(r) != "error"]
    n = len(judged)
    out["answered"] = (len(results), len(questions))
    out["errors"] = sum(status_of(r) == "error" for r in results)
    out["latency"] = sum(r["latency_s"] for r in judged) / n if n else None
    out["calls"] = sum(r["llm_calls"] for r in judged) / n if n else None
    return out


def _cell(t) -> str:
    if t is None:
        return "not run"
    ok, n = t[0], t[1]
    if n == 0:
        return "not run yet"
    extra = f" (of {t[2]})" if len(t) > 2 and t[2] != n else ""
    return f"{ok}/{n} ({ok / n:.0%}){extra}"


def failures(results: list[dict], routing: list[dict]) -> list[str]:
    lines = [f"- **{r['id']}** (routing) {r['question']} - routed to {r['got']}"
             for r in routing if not r["ok"]]
    lines += [f"- **{r['id']}** ({r['category']}) {r['question']} - {r['reason'][:220]}"
              for r in results if status_of(r) == "fail"]
    lines += [f"- **{r['id']}** ({r['category']}) network/timeout error, will be retried"
              for r in results if status_of(r) == "error"]
    return lines or ["None."]


def main() -> None:
    v1_q = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    ho_q = json.loads((HERE / "heldout_questions.json").read_text(encoding="utf-8"))
    v1 = summary(v1_q, _load_json("routing.json"), _load_jsonl("results.jsonl"))
    v2_results, v2_routing = _load_jsonl("results_v2.jsonl"), _load_json("routing_v2.json")
    v2 = summary(v1_q, v2_routing, v2_results)
    ho_results, ho_routing = _load_jsonl("results_heldout_v2.jsonl"), _load_json("routing_heldout_v2.json")
    ho = summary(ho_q, ho_routing, ho_results)

    def num(x, fmt):
        return "-" if x is None else fmt.format(x)

    lines = [f"# FinSight evaluation: v1 vs v2 ({date.today()})", "",
             f"v2 answered **{v2['answered'][0]}/{v2['answered'][1]}** v1 questions and "
             f"**{ho['answered'][0]}/{ho['answered'][1]}** held-out questions "
             f"({v2['errors'] + ho['errors']} network/timeout error(s), retried on the next run). "
             "Accuracy counts judged answers only.", "",
             "## v1 questions (50): v1 vs v2", "",
             "| Metric | v1 (baseline b3c146e) | v2 |", "|---|---|---|",
             f"| Routing accuracy (router only) | {_cell(v1['routing'])} | {_cell(v2['routing'])} |"]
    for cat, title in CATEGORIES:
        lines.append(f"| {title} | {_cell(v1[cat])} | {_cell(v2[cat])} |")
    lines += [f"| Average latency per judged question | {num(v1['latency'], '{:.1f} s')} | {num(v2['latency'], '{:.1f} s')} |",
              f"| Average LLM calls per judged question | {num(v1['calls'], '{:.2f}')} | {num(v2['calls'], '{:.2f}')} |",
              "",
              "**Grading change (v2):** docs08 (\"What drove Nvidia's Data Center revenue growth in "
              "fiscal year 2024?\") accepts the route [\"docs\"] or [\"sql\", \"docs\"], because it asks "
              "for a number and its explanation. In v1 only [\"docs\"] counted, so v1's docs08 result "
              "was graded under the stricter rule.",
              "",
              "v1 latency is inflated by a slow network during that run (one question took 478 s).",
              "",
              "## Held-out questions (12): v2 only", "",
              "Frozen before any v2 fix (commit 1dcdaf9) and never used for tuning.", "",
              "| Metric | v2 |", "|---|---|",
              f"| Routing accuracy (router only) | {_cell(ho['routing'])} |"]
    for cat, title in CATEGORIES:
        if ho[cat][2]:
            lines.append(f"| {title} | {_cell(ho[cat])} |")
    lines += [f"| Average latency per judged question | {num(ho['latency'], '{:.1f} s')} |",
              f"| Average LLM calls per judged question | {num(ho['calls'], '{:.2f}')} |",
              "",
              "## Retrieval rank tables (no Gemini, v1 questions only)", ""]
    ranks = HERE / "retrieval_check.md"
    lines.append(ranks.read_text(encoding="utf-8").strip() if ranks.exists()
                 else "Run python -m eval.retrieval_check > eval/retrieval_check.md")
    lines += ["", "## Failures: v1 questions, v2 run", ""] + failures(v2_results, v2_routing)
    lines += ["", "## Failures: held-out questions", ""] + failures(ho_results, ho_routing)

    not_run_v2 = sorted({q["id"] for q in v1_q} - {r["id"] for r in v2_results})
    not_run_ho = sorted({q["id"] for q in ho_q} - {r["id"] for r in ho_results})
    if not_run_v2 or not_run_ho:
        lines += ["", "## Not answered yet", "", ", ".join(not_run_v2 + not_run_ho)]

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
