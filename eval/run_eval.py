"""Run the FinSight evaluation (free tier friendly). Agent code is used as-is.

Part 1 - routing accuracy for all questions (router only, 0 LLM calls).
          Saved to eval/routing.json.
Part 2 - full answers via src.agent.agent.answer(), one question at a time:
          latency, LLM calls, the answer and a score (eval/scoring.py).
          Each result is saved to eval/results.jsonl as soon as it finishes, with a
          status: "pass", "fail" (a real wrong answer) or "error" (network/timeout:
          the agent never got to answer). Network errors are retried up to 2 times.
          On a re-run, passed and failed questions are skipped; "error" ones run again
          and their old line is replaced.
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
from eval.scoring import is_network_error, score, status_of

HERE = Path(__file__).parent
QUESTIONS = HERE / "questions.json"
ROUTING = HERE / "routing.json"
RESULTS = HERE / "results.jsonl"

# Questions with 0 expected LLM calls first, so they always finish
ORDER = ["refuse/out_of_scope", "forecast/anomaly", "sql", "docs", "sql+docs"]
MAX_UNAVAILABLE_IN_A_ROW = 3  # model overloaded / network problems -> stop for now
NETWORK_RETRIES = 2           # extra attempts for a question that hit a network/timeout error


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


def load_results() -> dict[str, dict]:
    """All saved results by question id (a later line for the same id wins)."""
    if not RESULTS.exists():
        return {}
    records = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["id"]: r for r in records}


def done_ids() -> set[str]:
    """Questions that are finished: passed or really failed. 'error' ones run again."""
    return {i for i, r in load_results().items() if status_of(r) != "error"}


def save_result(rec: dict) -> None:
    """Write one result, replacing an older line for the same question (e.g. an earlier error)."""
    results = load_results()
    results[rec["id"]] = rec
    RESULTS.write_text("".join(json.dumps(r) + "\n" for r in results.values()), encoding="utf-8")


def _network_error(out: dict) -> bool:
    """The question failed because of the network/timeouts, not because of the agent."""
    texts = list(out.get("errors", [])) + [(out.get("docs") or {}).get("answer", "")]
    # "Model unavailable" = every model timed out, was overloaded or lost the connection
    # (the 60 s request timeout in src/llm.py ends up here): also not the agent's fault
    return any(is_network_error(t) or llm.UNAVAILABLE_MESSAGE in t for t in texts)


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
    rec["status"] = "pass" if rec["correct"] else "fail"
    return rec


def _hit_limit(out: dict) -> bool:
    docs_answer = (out.get("docs") or {}).get("answer")
    return llm.LIMIT_MESSAGE in out.get("errors", []) or docs_answer == llm.LIMIT_MESSAGE


def run_answers(questions: list[dict]) -> None:
    done = done_ids()
    todo = sorted((q for q in questions if q["id"] not in done),
                  key=lambda q: ORDER.index(q["category"]))
    print(f"\nANSWERS: {len(done)} already done, {len(todo)} to go")
    unavailable_streak = 0

    for n, q in enumerate(todo, 1):
        # Up to 1 + NETWORK_RETRIES attempts while the network is the problem
        for attempt in range(1 + NETWORK_RETRIES):
            start = time.perf_counter()
            out = answer(q["question"])
            seconds = time.perf_counter() - start
            if not _network_error(out) or _hit_limit(out):
                break
            if attempt < NETWORK_RETRIES:
                print(f"  {q['id']}: network error, retrying ({attempt + 1}/{NETWORK_RETRIES})")

        if _hit_limit(out):
            remaining = len(todo) - n + 1
            print(f"\nDaily free limit reached at {q['id']}. Stopping cleanly.")
            print(f"{remaining} question(s) remain - run again tomorrow to continue.")
            return
        rec = _record(q, out, seconds)
        if _network_error(out):  # still a network/timeout problem after all retries
            rec["status"] = "error"
            rec["reason"] = (f"network/timeout error after {1 + NETWORK_RETRIES} attempts: "
                             + "; ".join(out.get("errors", []) or [(out.get("docs") or {}).get("answer", "")])[:200])
            unavailable_streak += 1
        else:
            unavailable_streak = 0
        save_result(rec)
        mark = {"pass": "OK  ", "fail": "FAIL", "error": "ERR "}[rec["status"]]
        print(f"  {mark} {q['id']:6} {rec['latency_s']:5.1f}s  LLM calls={rec['llm_calls']}  {rec['reason']}")
        if unavailable_streak >= MAX_UNAVAILABLE_IN_A_ROW:  # the network is down: stop for now
            print(f"\nNetwork/timeout errors on {unavailable_streak} questions in a row. Stopping; "
                  f"{len(todo) - n} more question(s) not tried yet.")
            return

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
