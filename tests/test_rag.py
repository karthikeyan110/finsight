"""Tests for document RAG (Phase 3)."""
import os

import pytest

from src.rag.ingest import DOCS, get_collection

DOC_FILES = sorted(p.name for p in DOCS.iterdir()
                   if p.suffix.lower() in (".htm", ".html", ".pdf"))


def test_docs_folder_has_files():
    assert DOC_FILES, "No documents in data/docs/ - run python -m src.rag.download_10k"


@pytest.mark.parametrize("filename", DOC_FILES)
def test_every_file_has_chunks(filename):
    # Checks the collection built by: python -m src.rag.ingest
    chunks = get_collection().get(where={"filename": filename}, include=["metadatas"])
    assert len(chunks["ids"]) > 0, f"No chunks for {filename}"
    meta = chunks["metadatas"][0]
    assert meta["ticker"] == filename.split("_")[0]
    assert meta["cik"] > 0  # found in dim_company
    assert "section" in meta or "page" in meta
    assert meta["fiscal_year"] == int(filename.split("_")[-1][:4])  # from the filename


def test_years_in_question():
    from src.rag.ask import years_in_question
    # a 10-K describes its own year, and the next year's 10-K compares against it
    assert years_in_question("Why did Nvidia's revenue grow so much in 2023?") == [2023, 2024]
    assert years_in_question("Compare 2023 and 2025") == [2023, 2024, 2025, 2026]
    assert years_in_question("What risks does Tesla mention?") == []


def test_filter_by_company_and_year():
    from src.rag.ask import _filter
    assert _filter(None, []) is None
    assert _filter("nvda", []) == {"ticker": "NVDA"}
    assert _filter("NVDA", [2023, 2024]) == {
        "$and": [{"ticker": "NVDA"}, {"fiscal_year": {"$in": [2023, 2024]}}]}


def test_year_filter_returns_only_those_10ks():
    # Retrieval only (no LLM): Nvidia + "2023" must search NVDA's 2023/2024 10-Ks only
    from src.rag.ask import _embed, _filter
    hits = get_collection().query(
        query_embeddings=[_embed("Why did Nvidia's revenue grow in 2023?")], n_results=5,
        where=_filter("NVDA", [2023, 2024]))
    files = {m["filename"] for m in hits["metadatas"][0]}
    assert files and files <= {"NVDA_10K_2023.htm", "NVDA_10K_2024.htm"}


def test_off_topic_question_not_found():
    from src.rag.ask import NOT_FOUND, ask_docs  # loads .env
    if not os.getenv("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set in .env")
    result = ask_docs("What is the capital of France?")
    assert result["answer"] == NOT_FOUND
    assert result["citations"] == []
