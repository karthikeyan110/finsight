"""Answer questions from the 10-K documents (RAG).

ask_docs(question, company=None, mode="docs")
  -> {"answer": str, "citations": [...], "years_searched": [...]}

Steps: find the 6 best chunks with hybrid local search (src/rag/retrieve.py:
embeddings + BM25 keywords, fused, re-ranked by a cross-encoder) -> ask Gemini to
answer ONLY from those chunks -> return the answer + where it came from.
mode="why" is used for "why did <number> change" questions: the search prefers the
named year's MD&A, and the prompt asks for the drivers of the change.

Run:  python -m src.rag.ask "What risks does Apple mention about supply chains?" AAPL
"""
import re

from sentence_transformers import SentenceTransformer

from src import llm
from src.rag.ingest import EMBED_MODEL, get_collection
from src.rag.retrieve import FINAL_K, retrieve

NOT_FOUND = "Not found in the documents."
TOP_K = FINAL_K  # chunks sent to the LLM

PROMPT = """Answer the question using ONLY the numbered excerpts from 10-K filings below.
Rules:
- Use only facts written in the excerpts. Do not use outside knowledge.
- Do not calculate anything; only quote numbers exactly as written.
- After each fact, cite the excerpt number like [1] or [2].
{why_rule}- If the excerpts do not contain the answer, reply with exactly: {not_found}

Excerpts:
{context}

Question: {question}
Answer:"""

# Extra rule for "why" questions: drivers of a change ARE the explanation
WHY_RULE = """- This question asks WHY a number changed. If the excerpts describe what drove or made up
  the change (segments, products, channels, prices, volumes, costs, one-time charges or gains),
  summarise those drivers as the explanation, with citations. Reply "{not_found}" only when
  nothing related to the change is present.
"""

_model = None  # embedding model, loaded once


def _embed(text: str) -> list[float]:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model.encode([text]).tolist()[0]


def _where(meta: dict) -> str:
    """Human-readable location: section for HTML, page for PDF."""
    return f"page {meta['page']}" if "page" in meta else meta.get("section", "")


def years_in_question(question: str) -> list[int]:
    """Fiscal years of the 10-Ks to search for the years a question mentions.

    'in 2023' -> [2023, 2024]: the 2023 10-K, and the 2024 10-K because a 10-K
    describes and compares against the previous year (and for companies whose
    fiscal year ends early in the year, e.g. Nvidia in January, calendar 2023 is
    mostly fiscal 2024).
    """
    years = {int(y) for y in re.findall(r"\b(20\d{2})\b", question)}
    return sorted(years | {y + 1 for y in years})


def _filter(company: str | None, years: list[int]) -> dict | None:
    """Build the ChromaDB metadata filter (company and/or fiscal years)."""
    parts = []
    if company:
        parts.append({"ticker": company.upper()})
    if years:
        parts.append({"fiscal_year": {"$in": years}})
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"$and": parts}


def ask_docs(question: str, company: str | None = None, mode: str = "docs") -> dict:
    """Answer `question` from the 6 best chunks (only `company`'s 10-Ks if given).

    mode="why": prefer the named year's MD&A and explain the drivers of a change.
    """
    hits = retrieve(question, company, mode)[:TOP_K]
    years = sorted({h["meta"].get("fiscal_year") for h in hits})
    docs, metas = [h["text"] for h in hits], [h["meta"] for h in hits]
    if not docs:
        return {"answer": NOT_FOUND, "citations": [], "years_searched": years}

    context = "\n\n".join(
        f"[{i}] ({m['filename']}, {_where(m)})\n{d}" for i, (d, m) in enumerate(zip(docs, metas), 1))

    # Shared client: cached, and falls back to another model if one is over its limit
    why_rule = WHY_RULE.format(not_found=NOT_FOUND) if mode == "why" else ""
    answer = llm.generate(PROMPT.format(not_found=NOT_FOUND, context=context, question=question,
                                        why_rule=why_rule))
    if answer in (llm.LIMIT_MESSAGE, llm.UNAVAILABLE_MESSAGE):
        return {"answer": answer, "citations": [], "years_searched": years}  # nothing to cite

    if NOT_FOUND.rstrip(".").lower() in answer.lower():
        return {"answer": NOT_FOUND, "citations": [], "years_searched": years}

    # Citations = only the excerpts the answer refers to with [n]
    used = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    citations = [{"ref": i, "filename": m["filename"], "location": _where(m)}
                 for i, m in enumerate(metas, 1) if i in used]
    return {"answer": answer, "citations": citations, "years_searched": years}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "What risks does Apple mention about supply chains?"
    c = sys.argv[2] if len(sys.argv) > 2 else None
    result = ask_docs(q, c)
    print(result["answer"], "\n")
    for cite in result["citations"]:
        print(f"[{cite['ref']}] {cite['filename']} - {cite['location']}")
