"""Retrieval check on the v1 questions - NO Gemini, never uses eval/heldout_questions.json.

Tables:
  1. The 6 failed v1 "why" questions: rank of the explanation passage before step 2 (v1),
     after step 2 (recorded) and now, and whether it reaches the top FINAL_K.
  2. The 12 v1 docs questions: rank of the expected passage (the best-ranked chunk from an
     expected filing that contains ALL the question's key facts):
       before step 2 - v1 retrieval: embeddings only (run on the current index)
       after step 2  - cross-encoder only, no duplicate removal (CE_WEIGHT = 1, DEDUP off)
       now           - the current settings in src/rag/retrieve.py
  3. docs03 (Tesla competition): rank of the "established and new automobile
     manufacturers" passage.

Run:  python -m eval.retrieval_check
"""
import json
from contextlib import contextmanager
from pathlib import Path

import src.rag.retrieve as R
from eval.diagnose_why import BEFORE, CASES, check
from src.agent.router import find_company
from src.rag.ask import _embed, _filter, years_in_question
from src.rag.ingest import get_collection

QUESTIONS = Path(__file__).with_name("questions.json")  # v1 only
AFTER_STEP2 = {"why02": 3, "why03": 9, "why04": 1, "why06": 6, "why07": 4, "why08": 1}  # commit 5d0beb4
V1_DEPTH = 100
TESLA_PASSAGE = "established and new automobile manufacturers"


def _norm(s: str) -> str:
    return (s or "").lower().replace("’", "'").replace("&", "and")


def has_facts(text: str, facts: list) -> bool:
    t = _norm(" ".join(text.split()))
    return all(any(_norm(a) in t for a in alts) for alts in facts)


@contextmanager
def settings(ce_weight: float, dedup: bool):
    """Temporarily change the retrieval settings (restored afterwards)."""
    old = (R.CE_WEIGHT, R.DEDUP)
    R.CE_WEIGHT, R.DEDUP = ce_weight, dedup
    try:
        yield
    finally:
        R.CE_WEIGHT, R.DEDUP = old


def first_rank(results: list[tuple[str, dict]], ok) -> int | None:
    """1-based rank of the first (text, meta) result that passes ok(text, meta)."""
    return next((n for n, (t, m) in enumerate(results, 1) if ok(t, m)), None)


def v1_results(question: str, ticker: str | None) -> list:
    hits = get_collection().query(query_embeddings=[_embed(question)], n_results=V1_DEPTH,
                                  where=_filter(ticker, years_in_question(question)))
    return list(zip(hits["documents"][0], hits["metadatas"][0]))


def v2_results(question: str, ticker: str | None) -> list:
    return [(h["text"], h["meta"]) for h in R.retrieve(question, ticker, mode="docs")]


def fmt(rank: int | None, depth: int) -> str:
    if rank is None:
        return f"not in top {depth}"
    return f"{rank}{' ✓' if rank <= R.FINAL_K else ''}"


def main() -> None:
    print(f"## 'Why' questions (top {R.FINAL_K} reach Gemini)\n")
    print("| Question | Before step 2 (v1) | After step 2 | Now (step 2b) | In top 6 now? |")
    print("|---|---|---|---|---|")
    for case in CASES:
        d = check(case)
        now = d["after"]
        print(f"| {d['id']} | {BEFORE[d['id']]} | {AFTER_STEP2[d['id']]} | {now or 'not in top 30'} "
              f"| {'yes' if now and now <= R.FINAL_K else 'no'} |")

    qs = [q for q in json.loads(QUESTIONS.read_text(encoding="utf-8")) if q["category"] == "docs"]
    print(f"\n## v1 docs questions: rank of the expected passage (✓ = in the top {R.FINAL_K})\n")
    print("| Question | Before step 2 (v1) | After step 2 | Now (step 2b) |")
    print("|---|---|---|---|")
    tesla = {}
    for q in qs:
        ticker = find_company(q["question"])
        ok = lambda t, m, q=q: m.get("filename") in q["expected_filings"] and has_facts(t, q["key_facts"])
        r1 = first_rank(v1_results(q["question"], ticker), ok)
        with settings(1.0, False):
            step2 = v2_results(q["question"], ticker)
        now = v2_results(q["question"], ticker)
        r2, r3 = first_rank(step2, ok), first_rank(now, ok)
        print(f"| {q['id']} {q['question'][:55]} | {fmt(r1, V1_DEPTH)} | {fmt(r2, len(step2))} "
              f"| {fmt(r3, len(now))} |")
        if q["id"] == "docs03":
            passage = lambda t, m: TESLA_PASSAGE in _norm(" ".join(t.split()))
            tesla = {"v1": first_rank(v1_results(q["question"], ticker), passage),
                     "step2": first_rank(step2, passage), "now": first_rank(now, passage),
                     "depth": len(now)}

    if tesla:
        print(f"\n## docs03: the \"{TESLA_PASSAGE}\" passage\n")
        print(f"before step 2: {fmt(tesla['v1'], V1_DEPTH)} | after step 2: "
              f"{fmt(tesla['step2'], 30)} | now: {fmt(tesla['now'], tesla['depth'])}")


if __name__ == "__main__":
    main()
