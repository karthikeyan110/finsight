"""Ingest 10-K documents into a ChromaDB collection for RAG.

For every .htm / .pdf in data/docs/:
  1. extract the text (BeautifulSoup for HTML, pypdf for PDF)
  2. split it into ~800-character chunks with 100 characters of overlap
  3. embed each chunk with sentence-transformers all-MiniLM-L6-v2
  4. store chunk + embedding + metadata in ChromaDB (data/chroma_docs/)

Run:  python -m src.rag.ingest
"""
import re
from pathlib import Path

import chromadb
import duckdb
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

from src.rag.download_10k import COMPANIES

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "data" / "docs"
CHROMA_DIR = ROOT / "data" / "chroma_docs"
DB_PATH = ROOT / "data" / "gold" / "finsight.duckdb"
COLLECTION = "docs_10k"
EMBED_MODEL = "all-MiniLM-L6-v2"

CHUNK_SIZE = 800
OVERLAP = 100

# A real section heading looks like "Item 1A.  Risk Factors" (number AND title on one line).
# Table-of-contents lines are just "Item 1A." so they don't match.
HEADING = re.compile(r"^Item\s*\d+[A-C]?\.?\s+\S.{2,150}$", re.IGNORECASE)


def split_text(text: str) -> list[str]:
    """Split text into ~800-char chunks; each chunk repeats the last 100 chars of the previous one."""
    chunks, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):  # try to end at a space so words aren't cut in half
            space = text.rfind(" ", start + CHUNK_SIZE // 2, end)
            end = space if space != -1 else end
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - OVERLAP
    return [c for c in chunks if c]


def read_html(path: Path) -> list[tuple[str, dict]]:
    """Return (text, metadata) pieces, one per 10-K section ("Item ...")."""
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    for hidden in soup.find_all("ix:header"):  # hidden XBRL data, not readable text
        hidden.decompose()
    lines = [" ".join(l.split()) for l in soup.get_text("\n").split("\n")]
    lines = [l for l in lines if l]

    sections, current, buffer = [], "Cover page", []
    for line in lines:
        if HEADING.match(line):
            sections.append((current, buffer))
            current, buffer = line, []
        else:
            buffer.append(line)
    sections.append((current, buffer))
    return [(" ".join(buf), {"section": name}) for name, buf in sections if buf]


def read_pdf(path: Path) -> list[tuple[str, dict]]:
    """Return (text, metadata) pieces, one per PDF page."""
    reader = PdfReader(str(path))
    return [(" ".join((page.extract_text() or "").split()), {"page": i})
            for i, page in enumerate(reader.pages, start=1)]


def lookup_cik(ticker: str) -> int:
    """Find the company's cik and confirm it exists in dim_company.

    dim_company has no ticker column, so the ticker -> cik list in download_10k.py
    (taken from dim_company) is used, then checked against the table.
    """
    cik = COMPANIES.get(ticker)
    if cik is None:
        return -1  # unknown company
    con = duckdb.connect(str(DB_PATH), read_only=True)
    found = con.execute("SELECT COUNT(*) FROM dim_company WHERE cik = ?", [cik]).fetchone()[0]
    con.close()
    return cik if found else -1


def get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(COLLECTION)


def ingest() -> dict[str, int]:
    """Rebuild the collection from scratch. Returns {filename: number_of_chunks}."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)  # start fresh so re-runs don't duplicate
    collection = client.create_collection(COLLECTION)
    model = SentenceTransformer(EMBED_MODEL)

    counts = {}
    files = sorted(p for p in DOCS.iterdir() if p.suffix.lower() in (".htm", ".html", ".pdf"))
    for path in files:
        ticker = path.name.split("_")[0].upper()  # text before the first underscore
        base = {"ticker": ticker, "cik": lookup_cik(ticker), "filename": path.name}
        pieces = read_pdf(path) if path.suffix.lower() == ".pdf" else read_html(path)

        texts, metas = [], []
        for text, meta in pieces:
            for chunk in split_text(text):
                texts.append(chunk)
                metas.append({**base, **meta})

        embeddings = model.encode(texts, batch_size=64, show_progress_bar=False).tolist()
        ids = [f"{path.name}-{i}" for i in range(len(texts))]
        for s in range(0, len(texts), 2000):  # Chroma limits the batch size
            collection.add(ids=ids[s:s + 2000], documents=texts[s:s + 2000],
                           embeddings=embeddings[s:s + 2000], metadatas=metas[s:s + 2000])
        counts[path.name] = len(texts)
        print(f"{path.name:22} {len(texts):5} chunks")
    return counts


if __name__ == "__main__":
    ingest()
