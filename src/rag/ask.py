"""Answer questions from the 10-K documents (RAG).

ask_docs(question, company=None) -> {"answer": str, "citations": [ {filename, section|page}, ... ]}

Steps: embed the question -> find the 5 closest chunks in ChromaDB ->
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


def ask_docs(question: str, company: str | None = None) -> dict:
    """Answer `question` from the top 5 chunks (only `company`'s ticker if given)."""
    collection = get_collection()
    where = {"ticker": company.upper()} if company else None
    hits = collection.query(query_embeddings=[_embed(question)], n_results=TOP_K, where=where)
    docs, metas = hits["documents"][0], hits["metadatas"][0]
    if not docs:
        return {"answer": NOT_FOUND, "citations": []}

    context = "\n\n".join(
        f"[{i}] ({m['filename']}, {_where(m)})\n{d}" for i, (d, m) in enumerate(zip(docs, metas), 1))

    # Shared client: cached, and falls back to another model if one is over its limit
    answer = llm.generate(PROMPT.format(not_found=NOT_FOUND, context=context, question=question))
    if answer in (llm.LIMIT_MESSAGE, llm.UNAVAILABLE_MESSAGE):
        return {"answer": answer, "citations": []}  # no LLM answer -> nothing to cite

    if NOT_FOUND.rstrip(".").lower() in answer.lower():
        return {"answer": NOT_FOUND, "citations": []}

    # Citations = only the excerpts the answer refers to with [n]
    used = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    citations = [{"ref": i, "filename": m["filename"], "location": _where(m)}
                 for i, m in enumerate(metas, 1) if i in used]
    return {"answer": answer, "citations": citations}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "What risks does Apple mention about supply chains?"
    c = sys.argv[2] if len(sys.argv) > 2 else None
    result = ask_docs(q, c)
    print(result["answer"], "\n")
    for cite in result["citations"]:
        print(f"[{cite['ref']}] {cite['filename']} - {cite['location']}")
