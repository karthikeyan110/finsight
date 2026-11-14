"""Hybrid retrieval for the 10-K chunks - all local, no API calls.

retrieve(question, company=None, mode="docs") -> list of hits (best first), each
  {"id", "text", "meta", "score"}; the first FINAL_K go to the LLM.

Steps:
  1. Candidates from two searches over the same filtered chunks (company, fiscal years):
       - embedding search (meaning)         all-MiniLM-L6-v2 via ChromaDB
       - BM25 keyword search (exact words)  "opioid", "State Aid", "$10.2 billion"
  2. Reciprocal rank fusion (RRF): each chunk scores 1/(60 + rank) per search; summed.
  3. The top 30 are scored by a cross-encoder, which reads question and chunk together.
     It does not decide alone: the final score blends it with the fusion rank,
     CE_WEIGHT * cross-encoder + (1 - CE_WEIGHT) * fusion, both scaled to 0-1
     (the cross-encoder alone over-rated chunks that merely repeat a word, e.g.
     "competitive labor market" for a question about competing carmakers).
  4. Near-duplicates are removed: the same paragraph repeated in several years' 10-Ks
     is kept once, from the newest filing, so the top 6 hold different passages.

mode="why" (questions about why a number changed):
  - the filing for the fiscal year named in the question is searched first
  - the query is expanded with the metric's other names and phrases that 10-Ks use to
    explain changes ("increased primarily due to", "driven by", "compared to")
  - MD&A chunks (Item 7, incl. JPMorgan's annual-report MD&A) get a boost
mode="docs": none of the above, so plain questions (risks, segments) are not pushed to MD&A.
"""
import math
import re
from collections import Counter
from functools import lru_cache

from src.rag.ingest import EMBED_MODEL, get_collection
from src.rag.sections import is_mda

RRF_K = 60            # standard RRF constant
POOL = 100            # candidates taken from each search
CANDIDATES = 30       # how many go to the cross-encoder
FINAL_K = 6           # how many go to the LLM
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CE_WEIGHT = 0.5       # final = CE_WEIGHT * cross-encoder + (1 - CE_WEIGHT) * fusion rank (both 0-1)
MDA_BOOST = 0.2       # added to the final score (0-1 scale) of MD&A chunks in "why" mode
DEDUP = True          # remove near-duplicate chunks before picking the top FINAL_K
DUP_JACCARD = 0.8     # share of 3-word phrases two chunks must have in common to be duplicates

# Other names for each metric, and how 10-Ks explain changes (query expansion, no LLM)
METRIC_WORDS = {
    "revenue": "revenue revenues net sales",
    "sales": "revenue revenues net sales",
    # net income = operating income - taxes (+/- other items), so its explanations
    # often sit in the tax discussion (e.g. a one-time income tax charge)
    "net income": "net income earnings net earnings provision for income taxes effective tax rate "
                  "operating income",
    "profit": "net income earnings operating income",
    "earnings": "net income earnings",
    "operating income": "operating income income from operations operating margin",
    "margin": "gross margin operating margin",
    "assets": "total assets",
    "liabilities": "total liabilities",
    "cash": "cash and cash equivalents",
}
CHANGE_PHRASES = ("increased decreased primarily due to driven by compared to "
                  "reflecting partially offset by lower higher")

STOPWORDS = set("the a an of and or to in on for by with at from as is are was were be been "
                "did do does what why how which that this its it our their".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


class BM25:
    """Okapi BM25 keyword scoring (k1 = 1.5, b = 0.75)."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = sum(self.lens) / max(len(self.lens), 1)
        df = Counter(word for tf in self.tfs for word in tf)
        n = len(docs)
        self.idf = {w: math.log((n - c + 0.5) / (c + 0.5) + 1) for w, c in df.items()}

    def scores(self, query: str) -> list[float]:
        words = tokenize(query)
        out = []
        for tf, length in zip(self.tfs, self.lens):
            s = 0.0
            for w in words:
                if w in tf:
                    f = tf[w]
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg))
            out.append(s)
        return out


def _where(company: str | None, years: list[int]) -> dict | None:
    parts = []
    if company:
        parts.append({"ticker": company.upper()})
    if years:
        parts.append({"fiscal_year": {"$in": sorted(years)}})
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"$and": parts}


@lru_cache(maxsize=64)
def _corpus(company: str | None, years: tuple):
    """All chunks for this filter + a BM25 index over them (cached per filter)."""
    got = get_collection().get(where=_where(company, list(years)), include=["documents", "metadatas"])
    return got["ids"], got["documents"], got["metadatas"], BM25(got["documents"])


_embedder = None
_reranker = None


def _embed(text: str) -> list[float]:
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder.encode([text]).tolist()[0]


def _rerank(query: str, texts: list[str]) -> list[float]:
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANK_MODEL)
    return [float(s) for s in _reranker.predict([(query, t) for t in texts])]


def named_years(question: str) -> list[int]:
    """Years written in the question: 'fiscal 2024' -> [2024]."""
    return sorted({int(y) for y in re.findall(r"\b(20\d{2})\b", question)})


def expand(question: str) -> str:
    """'why' query expansion: the metric's other names + change phrases."""
    low = question.lower()
    extra = [words for key, words in METRIC_WORDS.items() if key in low]
    return " ".join([question, *extra, CHANGE_PHRASES])


def _years_to_search(company: str | None, question: str, mode: str) -> list[int]:
    """Which fiscal years' 10-Ks to search.

    docs mode: each named year and the next one (a 10-K also describes the prior year).
    why mode: the named fiscal year's own 10-K first; if that filing does not exist,
    the next year's (e.g. Walmart's quarter ending Oct 2023 is in its fiscal 2024 10-K).
    """
    named = named_years(question)
    if not named:
        return []
    if mode != "why":
        return sorted(set(named) | {y + 1 for y in named})
    if _corpus(company, tuple(named))[0]:
        return named
    return sorted({y + 1 for y in named})


def retrieve(question: str, company: str | None = None, mode: str = "docs") -> list[dict]:
    """Best chunks for the question, best first (hybrid search + RRF + cross-encoder)."""
    years = _years_to_search(company, question, mode)
    ids, docs, metas, bm25 = _corpus(company, tuple(years))
    if not ids and years:  # no 10-K for those years: search all years instead
        years = []
        ids, docs, metas, bm25 = _corpus(company, ())
    if not ids:
        return []
    query = expand(question) if mode == "why" else question

    # 1) two searches over the same filtered chunks
    dense = get_collection().query(query_embeddings=[_embed(query)], n_results=min(POOL, len(ids)),
                                   where=_where(company, years))
    dense_ids = dense["ids"][0]
    kw = bm25.scores(query)
    kw_ids = [ids[i] for i in sorted(range(len(ids)), key=lambda i: -kw[i])[:POOL] if kw[i] > 0]

    # 2) reciprocal rank fusion
    fused = Counter()
    for ranked in (dense_ids, kw_ids):
        for rank, cid in enumerate(ranked, 1):
            fused[cid] += 1 / (RRF_K + rank)
    top = [cid for cid, _ in fused.most_common(CANDIDATES)]

    # 3) blend the cross-encoder with the fusion rank (+ MD&A boost for "why" questions)
    by_id = {cid: (doc, meta) for cid, doc, meta in zip(ids, docs, metas)}
    top = [cid for cid in top if cid in by_id]
    ce = _scale(_rerank(question if mode != "why" else expand(question), [by_id[c][0] for c in top]))
    # fusion rank scaled to 0-1: the best fused chunk = 1, the 30th = 0
    fusion = [1 - i / max(len(top) - 1, 1) for i in range(len(top))]
    hits = []
    for cid, c, f in zip(top, ce, fusion):
        doc, meta = by_id[cid]
        score = CE_WEIGHT * c + (1 - CE_WEIGHT) * f
        if mode == "why" and is_mda(meta.get("section", "")):
            score += MDA_BOOST
        hits.append({"id": cid, "text": doc, "meta": meta, "score": score})
    hits.sort(key=lambda h: -h["score"])

    # 4) the same paragraph from several years' 10-Ks counts once (newest filing kept)
    return dedupe(hits) if DEDUP else hits


def _scale(values: list[float]) -> list[float]:
    """Min-max scale to 0-1 (all equal -> all 0.5)."""
    lo, hi = min(values, default=0.0), max(values, default=0.0)
    return [0.5] * len(values) if hi == lo else [(v - lo) / (hi - lo) for v in values]


def _shingles(text: str) -> set:
    words = tokenize(text)
    return {" ".join(words[i:i + 3]) for i in range(max(len(words) - 2, 1))}


def near_duplicates(a: str, b: str) -> bool:
    """True if two chunks share at least DUP_JACCARD of their 3-word phrases."""
    sa, sb = _shingles(a), _shingles(b)
    return bool(sa and sb) and len(sa & sb) / len(sa | sb) >= DUP_JACCARD


def dedupe(hits: list[dict]) -> list[dict]:
    """Keep one chunk per group of near-duplicates: the newest filing's copy, placed
    where the group's best-ranked copy was. `hits` must be sorted best first."""
    groups: list[list[dict]] = []
    for h in hits:
        for g in groups:
            if near_duplicates(g[0]["text"], h["text"]):
                g.append(h)
                break
        else:
            groups.append([h])
    kept = []
    for g in groups:  # groups are already in order of their best copy
        newest = max(g, key=lambda h: (h["meta"].get("fiscal_year", 0), h["score"]))
        kept.append({**newest, "score": g[0]["score"]})
    return kept
