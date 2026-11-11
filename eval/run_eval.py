"""Run the FinSight evaluation (free tier friendly). Agent code is used as-is.

Part 1 - routing accuracy for all questions (router only, 0 LLM calls).
          Saved to eval/routing.json.
Part 2 - full answers via src.agent.agent.answer(), one question at a time:
          latency, LLM calls, the answer and a score (eval/scoring.py).
          Each result is appended to eval/results.jsonl as soon as it finishes.
          On a re-run, questions already in results.jsonl are skipped.
          Stops cleanly when the Gemini daily limit is reached and says how many remain.
          Questions that need no LLM (forecast/anomaly, refuse/out_of_scope) run first.

Run:  python -m eval.run_eval              (routing + as many answers as the quota allows)
      python -m eval.run_eval --routing-only
"""
import json
import logging
import sys
import time
from pathlib import Path

from src import llm
from src.agent.agent import answer
from src.agent.router import route
from eval.scoring import score

HERE = Path(__file__).parent
QUESTIONS = HERE / "questions.json"
ROUTING = HERE / "routing.json"
RESULTS = HERE / "results.jsonl"

# Questions with 0 expected LLM calls first, so they always finish
ORDER = ["refuse/out_of_scope", "forecast/anomaly", "sql", "docs", "sql+docs"]
MAX_UNAVAILABLE_IN_A_ROW = 3  # model overloaded / network problems -> stop for now


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def run_routing(questions: list[dict]) -> list[dict]:
    rows = []
    for q in questions:
        r = route(q["question"])
        rows.append({"id": q["id"], "category": q["category"], "question": q["question"],
                     "expected": q["expected_routes"], "got": r.routes, "method": r.method,
                     "score": None if r.score is None else round(r.score, 3),
                     "ok": r.routes == q["expected_routes"]})
    ROUTING.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    ok = sum(r["ok"] for r in rows)
    print(f"\nROUTING ACCURACY: {ok}/{len(rows)} = {ok / len(rows):.0%}  (0 LLM calls)")
    for cat in ORDER:
        part = [r for r in rows if r["category"] == cat]
        print(f"  {cat:20} {sum(r['ok'] for r in part)}/{len(part)}")
    wrong = [r for r in rows if not r["ok"]]
    if wrong:
        print("  Misrouted:")
        for r in wrong:
            print(f"    {r['id']}: {r['question']!r} -> {r['got']} (expected {r['expected']}, {r['method']})")
    return rows


def done_ids() -> set[str]:
    if not RESULTS.exists():
        return set()
    return {json.loads(line)["id"] for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()}


def _record(q: dict, out: dict, seconds: float) -> dict:
    table = out.get("table")
    rec = {
        "id": q["id"], "category": q["category"], "question": q["question"],
        "routes": out["routes"], "llm_calls": out.get("llm_calls", 0),
        "latency_s": round(seconds, 2), "errors": out.get("errors", []),
        "sql": out.get("sql"),
        "table": None if table is None else {
            "columns": [str(c) for c in table.columns],
            "rows": json.loads(table.head(200).to_json(orient="values", date_format="iso"))},
        "docs": out.get("docs"),
        "forecast_quarters": None if not out.get("forecast") else len(out["forecast"]["forecast"]),
        "anomalies_found": None if out.get("anomalies") is None else len(out["anomalies"]),
    }
    rec["correct"], rec["reason"] = score(q, rec)
    return rec


def _hit_limit(out: dict) -> bool:
    docs_answer = (out.get("docs") or {}).get("answer")
    return llm.LIMIT_MESSAGE in out.get("errors", []) or docs_answer == llm.LIMIT_MESSAGE


def _unavailable(out: dict) -> bool:
    docs_answer = (out.get("docs") or {}).get("answer")
    text = " ".join(out.get("errors", []))
    return llm.UNAVAILABLE_MESSAGE in text or docs_answer == llm.UNAVAILABLE_MESSAGE


def run_answers(questions: list[dict]) -> None:
    done = done_ids()
    todo = sorted((q for q in questions if q["id"] not in done),
                  key=lambda q: ORDER.index(q["category"]))
    print(f"\nANSWERS: {len(done)} already done, {len(todo)} to go")
    unavailable_streak = 0

    for n, q in enumerate(todo, 1):
        start = time.perf_counter()
        out = answer(q["question"])
        seconds = time.perf_counter() - start

        if _hit_limit(out):
            remaining = len(todo) - n + 1
            print(f"\nDaily free limit reached at {q['id']}. Stopping cleanly.")
            print(f"{remaining} question(s) remain - run again tomorrow to continue.")
            return
        if _unavailable(out):  # temporary: don't save, try the next question
            unavailable_streak += 1
            print(f"  {q['id']}: model unavailable, will retry on the next run")
            if unavailable_streak >= MAX_UNAVAILABLE_IN_A_ROW:
                print(f"\nModels unavailable {unavailable_streak} times in a row. Stopping; "
                      f"{len(todo) - n} more question(s) not tried yet.")
                return
            continue
        unavailable_streak = 0

        rec = _record(q, out, seconds)
        with RESULTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        mark = "OK  " if rec["correct"] else "FAIL"
        print(f"  {mark} {q['id']:6} {rec['latency_s']:5.1f}s  LLM calls={rec['llm_calls']}  {rec['reason']}")

    print(f"\nAll {len(questions)} questions answered.")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
    for noisy in ("cmdstanpy", "prophet"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    questions = load_questions()
    run_routing(questions)
    if "--routing-only" not in sys.argv:
        run_answers(questions)


if __name__ == "__main__":
    main()
