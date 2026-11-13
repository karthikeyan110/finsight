"""Diagnose failed "why" questions WITHOUT Gemini (read-only; changes nothing).

For each case:
  (a) search the 10-K text directly for the explanation and report the TRUE section,
      found with a heading parser that also handles headings split over two lines
      ("Item 7." on one line, the title on the next - Amazon/Alphabet style)
  (b) the rank of that passage in the CURRENT retrieval (same query + filters as ask_docs)
  (c) the section label stored on that chunk
Plus: how many chunks per company carry the correct Item label.

Run:  python -m eval.diagnose_why            (diagnosis table)
      python -m eval.diagnose_why --explore  (print candidate passages)
"""
import re
import sys
from collections import defaultdict
from functools import lru_cache

from bs4 import BeautifulSoup

from src.agent.router import find_company
from src.rag.ask import _embed, _filter, years_in_question
from src.rag.ingest import DOCS, get_collection

ITEM = re.compile(r"^item\s*(\d+[a-c]?)\.?(\s+\S.*)?$", re.IGNORECASE)
# 10-K items in their fixed order; real headings always appear in this order
ORDER = ["1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8", "9", "9A", "9B", "9C",
         "10", "11", "12", "13", "14", "15", "16"]
NAMES = {"1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments",
         "1C": "Cybersecurity", "2": "Properties", "3": "Legal Proceedings", "5": "Market for Equity",
         "7": "MD&A", "7A": "Market Risk", "8": "Financial Statements", "9A": "Controls",
         "10": "Directors and Officers", "15": "Exhibits and Schedules"}


def _in_order(heads: list) -> list:
    """Keep the longest run of headings whose items go up in order (1, 1A, ..., 7, 7A, 8 ...).

    Drops cross-references and repeated page headers that look like headings
    (e.g. a line "Item 7" at the top of every MD&A page, or "Item 1A" quoted in the text).
    """
    heads = [h for h in heads if h[1] in ORDER]
    keys = [ORDER.index(h[1]) for h in heads]
    best = [1] * len(heads)
    prev = [-1] * len(heads)
    for i in range(len(heads)):
        for j in range(i):
            if keys[j] < keys[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    if not heads:
        return []
    i = max(range(len(heads)), key=lambda k: best[k])
    chain = []
    while i != -1:
        chain.append(heads[i])
        i = prev[i]
    return chain[::-1]
RANK_DEPTH = 200  # how deep to look in the current retrieval

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


def _norm(s: str) -> str:
    return " ".join(s.split())


@lru_cache(maxsize=None)
def parse(filename: str):
    """Full text (lines joined by spaces) + true section headings as (offset, item, name)."""
    soup = BeautifulSoup((DOCS / filename).read_bytes(), "lxml")
    for hidden in soup.find_all("ix:header"):
        hidden.decompose()
    lines = [_norm(l) for l in soup.get_text("\n").split("\n")]
    lines = [l for l in lines if l]

    heads, text, pos = [], [], 0
    for i, line in enumerate(lines):
        m = ITEM.match(line)
        if m and len(line) < 160:
            title = (m.group(2) or "").strip()
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if not title and len(nxt) < 120 and not ITEM.match(nxt):
                title = nxt  # heading split over two lines
            if title:
                item = m.group(1).upper()
                heads.append((pos, item, f"Item {item}. {NAMES.get(item, title[:40])}"))
        text.append(line)
        pos += len(line) + 1
    full = " ".join(text)

    # The table of contents lists every Item first; the body starts at the 2nd "Item 1"
    ones = [h for h in heads if h[1] == "1"]
    body_start = ones[1][0] if len(ones) > 1 else 0
    heads = _in_order([h for h in heads if h[0] >= body_start])
    return full, heads, body_start


def true_section(filename: str, offset: int) -> str:
    _, heads, body_start = parse(filename)
    current = "Cover page / contents"
    if offset < body_start:
        return current
    for pos, _, name in heads:
        if pos <= offset:
            current = name
        else:
            break
    return current


def _item_no(label: str):
    m = re.search(r"item\s*(\d+[a-c]?)", label or "", re.IGNORECASE)
    return m.group(1).upper() if m else None


def chunks_of(filename: str) -> list:
    got = get_collection().get(where={"filename": filename}, include=["documents", "metadatas"])
    rows = list(zip(got["ids"], got["documents"], got["metadatas"]))
    return sorted(rows, key=lambda r: int(r[0].rsplit("-", 1)[1]))


def label_accuracy() -> dict:
    """Per company: (chunks whose stored Item label matches the true section, chunks checked)."""
    per_company = defaultdict(lambda: [0, 0])
    for path in sorted(DOCS.glob("*.htm")):
        full, _, _ = parse(path.name)
        cursor = 0
        for _, doc, meta in chunks_of(path.name):
            head = _norm(doc)[:60]
            start = full.find(head, cursor)
            if start < 0:
                start = full.find(head)
            if start < 0:
                continue  # chunk text not located (rare); left out of the count
            cursor = start + 1
            truth = true_section(path.name, start)
            stored = meta.get("section", "")
            ok = (_item_no(stored) == _item_no(truth)) if _item_no(truth) else (_item_no(stored) is None)
            c = per_company[meta["ticker"]]
            c[0] += ok
            c[1] += 1
    return {k: tuple(v) for k, v in per_company.items()}


def diagnose(case) -> dict:
    cid, question, filename, pattern = case
    full, _, _ = parse(filename)
    match = re.search(pattern, full, re.IGNORECASE)
    if not match:
        return {"id": cid, "found": False, "filing": filename}
    snippet = full[match.start(): match.start() + 160]

    # The chunk(s) that hold the passage
    needle = _norm(full[match.start(): match.start() + 50]).lower()
    holders = [(i, meta) for i, doc, meta in chunks_of(filename) if needle in _norm(doc).lower()]

    # Current retrieval: same query and filters as ask_docs
    ticker = find_company(question)
    years = years_in_question(question)
    hits = get_collection().query(query_embeddings=[_embed(question)], n_results=RANK_DEPTH,
                                  where=_filter(ticker, years))
    ids = hits["ids"][0]
    ranks = [ids.index(h) + 1 for h, _ in holders if h in ids]
    return {"id": cid, "found": True, "filing": filename,
            "true_section": true_section(filename, match.start()), "snippet": snippet,
            "stored_label": holders[0][1].get("section") if holders else "(no chunk holds it)",
            "rank": min(ranks) if ranks else None, "ticker": ticker, "years": years,
            "pool": len(ids)}


def main() -> None:
    if "--explore" in sys.argv:
        for cid, _, filename, pattern in CASES:
            full, _, _ = parse(filename)
            print(f"\n== {cid} {filename} /{pattern}/")
            for m in list(re.finditer(pattern, full, re.IGNORECASE))[:3]:
                print(f"  [{true_section(filename, m.start())}] ...{full[m.start(): m.start() + 220]}")
        return

    print("| Question | Explanation in the 10-K? | True section | Rank in current retrieval | Stored label |")
    print("|---|---|---|---|---|")
    for case in CASES:
        d = diagnose(case)
        if not d["found"]:
            print(f"| {d['id']} | not found by the pattern in {d['filing']} | - | - | - |")
            continue
        rank = str(d["rank"]) if d["rank"] else f"not in top {d['pool']}"
        print(f"| {d['id']} | yes, {d['filing']}: \"{d['snippet'][:110]}...\" | {d['true_section']} "
              f"| {rank} (filter: {d['ticker']}, years {d['years']}) | {d['stored_label']} |")

    print("\nChunks with the correct Item label, per company:")
    for ticker, (ok, n) in sorted(label_accuracy().items()):
        print(f"  {ticker:5} {ok:5}/{n:<5} ({ok / n:.0%})")


if __name__ == "__main__":
    main()
