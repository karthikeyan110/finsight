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


def test_off_topic_question_not_found():
    from src.rag.ask import NOT_FOUND, ask_docs  # loads .env
    if not os.getenv("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set in .env")
    result = ask_docs("What is the capital of France?")
    assert result["answer"] == NOT_FOUND
    assert result["citations"] == []
