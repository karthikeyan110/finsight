"""Answer questions from the 10-K documents (RAG).

ask_docs(question, company=None) -> {"answer": str, "citations": [...], "years_searched": [...]}

Steps: embed the question -> find the 5 closest chunks in ChromaDB (filtered by
company, and by fiscal year if the question mentions a year) ->
ask Gemini to answer ONLY from those chunks -> return answer + where it came from.

Run:  python -m src.rag.ask "What risks does Apple mention about supply chains?" AAPL
"""
import re

from sentence_transformers import SentenceTransformer

from src import llm
from src.rag.ingest import EMBED_MODEL, get_collection

NOT_FOUND = "Not found in the documents."
TOP_K = 5

PROMPT = """Answer the question using ONLY the numbered excerpts from 10-K filings below.
Rules:
- Use only facts written in the excerpts. Do not use outside knowledge.
- Do not calculate anything; only quote numbers exactly as written.
- After each fact, cite the excerpt number like [1] or [2].
- If the excerpts do not contain the answer, reply with exactly: {not_found}

Excerpts:
{context}

Question: {question}
Answer:"""

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


def ask_docs(question: str, company: str | None = None) -> dict:
    """Answer `question` from the top 5 chunks.

    Filters: only `company`'s ticker if given, and only the matching 10-Ks if the
    question mentions a year. If no 10-K exists for those years, all years are searched.
    """
    collection = get_collection()
    vector = _embed(question)
    years = years_in_question(question)
    hits = collection.query(query_embeddings=[vector], n_results=TOP_K, where=_filter(company, years))
    if years and not hits["documents"][0]:
        years = []  # we have no 10-K for those years -> search all years instead
        hits = collection.query(query_embeddings=[vector], n_results=TOP_K, where=_filter(company, []))
    docs, metas = hits["documents"][0], hits["metadatas"][0]
    if not docs:
        return {"answer": NOT_FOUND, "citations": [], "years_searched": years}

    context = "\n\n".join(
        f"[{i}] ({m['filename']}, {_where(m)})\n{d}" for i, (d, m) in enumerate(zip(docs, metas), 1))

    # Shared client: cached, and falls back to another model if one is over its limit
    answer = llm.generate(PROMPT.format(not_found=NOT_FOUND, context=context, question=question))
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
