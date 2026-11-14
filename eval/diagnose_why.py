"""Retrieval check for the 6 failed v1 "why" questions - NO Gemini (read-only).

For each case it finds the explanation passage in the 10-K text and reports:
  - its section (src/rag/sections.py)
  - its rank BEFORE v2 (v1 retrieval on the v1 index, measured 2026-11-14 in step 1)
  - its rank AFTER v2 (src/rag/retrieve.py: hybrid search + RRF + cross-encoder, "why" mode),
    and whether it is in the top 6 chunks that go to the LLM
  - the section label stored on the chunk

Plus two label checks per company:
  - heading check (independent): in every filing, Items 1, 1A, 7 and 8 are found in order and
    each heading's own words match its title ("Business", "Risk", "Discussion", "Financial
    Statements"); JPMorgan's annual-report MD&A/financial statements included
  - label agreement: share of chunks whose stored label is the section their text sits in

Does not use eval/heldout_questions.json.

Run:  python -m eval.diagnose_why
"""
import re
from collections import defaultdict
from functools import lru_cache

from src.agent.router import find_company
from src.rag.ingest import DOCS, get_collection
from src.rag.retrieve import FINAL_K, retrieve
from src.rag.sections import COVER, find_headings, read_lines

# (id, question, filing that should explain it, regex for the explanation passage)
CASES = [
    ("why02", "Why did Apple's net income fall in fiscal 2024?", "AAPL_10K_2024.htm",
     r"one-time income tax charge of \$10\.2 billion"),
    ("why03", "Why did Walmart's operating income jump in the quarter ending October 2023?",
     "WMT_10K_2024.htm", r"operating income, primarily due to lapping charges associated with opioid"),
    ("why04", "Why did Microsoft's revenue grow in fiscal 2025?", "MSFT_10K_2025.htm",
     r"Revenue increased \$[\d.]+ billion or \d+% with growth across each of our segments"),
    ("why06", "Why did Tesla's operating income decline in 2024?", "TSLA_10K_2024.htm",
     r"primarily due to lower average selling price on our vehicles"),
    ("why07", "Why did Nike's revenue fall in fiscal 2025?", "NKE_10K_2025.htm",
     r"NIKE, Inc\. Revenues for fiscal 2025 were"),
    ("why08", "Why did JPMorgan's revenue rise in 2024?", "JPM_10K_2024.htm",
     r"net revenue was \$[\d.]+ billion, (up|an increase)"),
]
# Rank of the passage in the v1 retrieval (old index, embeddings only), from step 1
BEFORE = {"why02": 90, "why03": 46, "why04": 8, "why06": 29, "why07": 1, "why08": 47}

# Words each heading must contain (Microsoft splits words, so spaces are ignored)
HEADING_WORDS = {"1": ("business",), "1A": ("risk",), "7": ("discussion",),
                 "8": ("financial statements", "independent registered")}


def _norm(s: str) -> str:
    return " ".join(s.split())


@lru_cache(maxsize=None)
def parse(filename: str):
    """Full text (lines joined by spaces), section starts as (char offset, label), lines, heads."""
    lines = read_lines(DOCS / filename)
    heads = find_headings(lines)
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    starts = [(offsets[i], lab) for i, _, lab in heads]
    return " ".join(lines), starts, lines, heads


def section_at(filename: str, offset: int) -> str:
    _, starts, _, _ = parse(filename)
    current = COVER
    for pos, lab in starts:
        if pos <= offset:
            current = lab
        else:
            break
    return current


def chunks_of(filename: str) -> list:
    got = get_collection().get(where={"filename": filename}, include=["documents", "metadatas"])
    rows = list(zip(got["ids"], got["documents"], got["metadatas"]))
    return sorted(rows, key=lambda r: int(r[0].rsplit("-", 1)[1]))


def heading_check(filename: str) -> list[str]:
    """Problems found by the independent heading check (empty = OK)."""
    _, _, lines, heads = parse(filename)
    problems = []
    for item, words in HEADING_WORDS.items():
        found = [h for h in heads if h[1] == item]
        if not found:
            problems.append(f"no Item {item}")
        for i, _, lab in found:
            text = " ".join(lines[i:i + 3]).lower().replace(" ", "")
            if not any(w.replace(" ", "") in text for w in words):
                problems.append(f"{lab}: heading words do not match")
    return problems


def label_report() -> dict:
    """Per company: filings passing the heading check, and label agreement of chunks."""
    out = defaultdict(lambda: {"filings": 0, "ok_filings": 0, "agree": 0, "chunks": 0})
    for path in sorted(DOCS.glob("*.htm")):
        ticker = path.name.split("_")[0]
        r = out[ticker]
        r["filings"] += 1
        r["ok_filings"] += not heading_check(path.name)
        full, _, _, _ = parse(path.name)
        cursor = 0
        for _, doc, meta in chunks_of(path.name):
            head = _norm(doc)[:60]
            start = full.find(head, cursor)
            if start < 0:
                start = full.find(head)
            if start < 0:
                continue
            cursor = start + 1
            r["chunks"] += 1
            r["agree"] += meta.get("section") == section_at(path.name, start)
    return out


def check(case) -> dict:
    cid, question, filename, pattern = case
    full, _, _, _ = parse(filename)
    match = re.search(pattern, full, re.IGNORECASE)
    if not match:
        return {"id": cid, "found": False, "filing": filename}
    needle = _norm(full[match.start(): match.start() + 50]).lower()
    holders = {i: meta for i, doc, meta in chunks_of(filename) if needle in _norm(doc).lower()}
    hits = retrieve(question, find_company(question), mode="why")  # up to 30, best first
    ranks = [n for n, h in enumerate(hits, 1) if h["id"] in holders]
    return {"id": cid, "found": True, "filing": filename, "question": question,
            "section": section_at(filename, match.start()),
            "label": next(iter(holders.values())).get("section") if holders else "(no chunk)",
            "after": ranks[0] if ranks else None, "pool": len(hits)}


def main() -> None:
    print("| Question | Explanation section | Rank before (v1) | Rank after (v2) | In top 6 after? | Stored label |")
    print("|---|---|---|---|---|---|")
    for case in CASES:
        d = check(case)
        if not d["found"]:
            print(f"| {d['id']} | passage not found in {d['filing']} | | | | |")
            continue
        after = str(d["after"]) if d["after"] else f"not in top {d['pool']}"
        top = "yes" if d["after"] and d["after"] <= FINAL_K else "no"
        print(f"| {d['id']} | {d['section']} | {BEFORE[d['id']]} | {after} | {top} | {d['label']} |")

    print("\n| Company | Filings passing heading check | Chunks with correct label |")
    print("|---|---|---|")
    for ticker, r in sorted(label_report().items()):
        print(f"| {ticker} | {r['ok_filings']}/{r['filings']} | "
              f"{r['agree']}/{r['chunks']} ({r['agree'] / r['chunks']:.0%}) |")


if __name__ == "__main__":
    main()
