"""Decide which tool(s) answer a question - WITHOUT the LLM (0 API calls).

Routes:
  ["sql"]          numbers from the database
  ["docs"]         explanations from the 10-K filings
  ["sql", "docs"]  "why" questions about numbers: the numbers AND the explanation
  ["forecast"]     revenue forecast for one of our 10 companies
  ["anomaly"]      unusual changes
  ["refuse"]       requests to change data (FinSight is read-only)
  ["out_of_scope"] questions that have nothing to do with company financials

How:
  0. Requests to change data (delete, drop, update, ...) are refused first.
  1. Keyword rules for clear cases (e.g. "forecast", "unusual", "why ... profit").
  2. If the keywords are unclear, compare the question with example questions
     (local sentence-transformers model, all-MiniLM-L6-v2) and use the route of
     the most similar example - unless even the best match is weak
     (score < OUT_OF_SCOPE_THRESHOLD) and no company is named: then it's out of scope.
"""
import re
from dataclasses import dataclass, field

from src.rag.download_10k import COMPANIES  # ticker -> cik

# Names people use for our 10 companies -> ticker
ALIASES = {
    "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN", "alphabet": "GOOGL",
    "google": "GOOGL", "nvidia": "NVDA", "tesla": "TSLA", "coca-cola": "KO",
    "coca cola": "KO", "coke": "KO", "walmart": "WMT", "wal-mart": "WMT",
    "jpmorgan": "JPM", "jp morgan": "JPM", "nike": "NKE",
}

FORECAST_WORDS = ["forecast", "predict", "projection", "next quarter", "next 2 quarters",
                  "next two quarters", "next 3 quarters", "next three quarters",
                  "next 4 quarters", "next four quarters", "coming quarter", "future revenue"]
ANOMALY_WORDS = ["anomal", "unusual", "outlier", "red flag", "abnormal", "suspicious",
                 "weird change", "strange change"]
WHY_WORDS = ["why", "what caused", "what drove", "reason for", "explain the"]
NUMBER_WORDS = ["revenue", "sales", "net income", "profit", "earnings", "operating income",
                "assets", "liabilities", "debt", "cash", "margin", "equity", "how much",
                "how many", "largest", "biggest", "highest", "lowest", "top 5", "top 10",
                "total", "average", "quarterly", "per quarter", "over the last", "trend"]
DOCS_WORDS = ["risk", "mention", "describe", "strategy", "competition", "competitor",
              "business model", "say about", "says about", "discuss", "supply chain",
              "lawsuit", "legal proceeding", "regulation", "employees", "what does",
              "products", "10-k",
              # v2: wording of docs questions that were misrouted in the v1 eval
              "segment", "tax charge", "state aid", "policy"]

# Example questions for the similarity fallback (route -> examples)
EXAMPLES = {
    "sql": [
        "What was Apple's net income last quarter?",
        "Which 10 companies have the largest total assets?",
        "Show Microsoft's quarterly revenue for the last two years",
        "How much cash does Nvidia hold?",
        "Compare the operating income of Walmart and Amazon",
        "Which sector has the highest average profit?",
        "List banks with more liabilities than assets",
    ],
    "docs": [
        "What risks does Apple mention about its supply chain?",
        "How does Tesla describe its competition?",
        "What is Coca-Cola's business strategy?",
        "What legal proceedings does JPMorgan disclose?",
        "Describe Nike's main products and markets",
        "What does Microsoft say about artificial intelligence?",
        "How many employees does Walmart have and how are they organised?",
    ],
    "sql+docs": [
        "Why did Alphabet's net income jump in Q2 2026?",
        "Why did Walmart's operating income fall?",
        "What caused Nvidia's revenue growth?",
        "Explain the drop in Nike's profit",
        "What drove Amazon's increase in total assets?",
    ],
    "forecast": [
        "Forecast Walmart's revenue for the next 2 quarters",
        "What will Apple's revenue be next quarter?",
        "Predict Tesla's sales for the coming quarters",
        "Revenue projection for Coca-Cola",
    ],
    "anomaly": [
        "Any unusual changes at Nvidia?",
        "Show anomalies in Microsoft's financials",
        "Which of our companies had strange jumps in their numbers?",
        "Are there red flags in Tesla's results?",
    ],
}

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8}

# ---- refuse: requests to change data ----
# A write verb counts if the question STARTS with it ("drop table ...") or also
# mentions data/tables ("please delete all data ..."). So a normal question like
# "Did Apple remove any products?" is not refused.
WRITE_VERBS = r"(delete|drop|update|insert|truncate|alter|remove|modify|overwrite|replace|" \
              r"wipe|erase|rename|grant|revoke|merge|upsert|create\s+table|create\s+view)"
DATA_WORDS = r"(data|database|table|tables|row|rows|record|records|column|columns|value|" \
             r"values|fact_\w+|dim_\w+|schema|everything)"

# ---- out of scope ----
# Chosen from measured scores (see tests/test_agent.py): off-topic questions such as
# "What is the capital of France?" or "Explain quantum physics" scored at most 0.25
# against our examples; in-scope questions that reach the similarity step scored at
# least 0.40 ("Show me retailers"). 0.32 sits roughly halfway, leaving a margin.
OUT_OF_SCOPE_THRESHOLD = 0.32


@dataclass
class Route:
    routes: list[str]
    ticker: str | None = None
    cik: int | None = None
    quarters: int = 2              # forecast horizon
    method: str = "keywords"       # "keywords" or "similarity"
    similar_to: str | None = None  # closest example question (similarity only)
    score: float | None = None     # cosine similarity of that example (0-1)
    notes: list[str] = field(default_factory=list)


def _has(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def find_company(question: str) -> str | None:
    """Ticker of the first of our 10 companies mentioned (name or capitalised ticker)."""
    low = question.lower()
    for name, ticker in ALIASES.items():
        if re.search(rf"\b{re.escape(name)}\b", low):
            return ticker
    for ticker in COMPANIES:
        if re.search(rf"\b{ticker}\b", question):
            return ticker
    return None


def find_quarters(question: str, default: int = 2) -> int:
    """'next 3 quarters' / 'next three quarters' -> 3."""
    m = re.search(r"next\s+(\d+|\w+)\s+quarters?", question.lower())
    if not m:
        return default
    word = m.group(1)
    return int(word) if word.isdigit() else WORD_NUMBERS.get(word, default)


def wants_to_change_data(question: str) -> bool:
    """True for requests like 'Delete all data from fact_financials' or 'drop table dim_company'."""
    low = question.lower().strip()
    if re.match(rf"^(please\s+|can you\s+|could you\s+)?{WRITE_VERBS}\b", low):
        return True
    return bool(re.search(rf"\b{WRITE_VERBS}\b", low) and re.search(rf"\b{DATA_WORDS}\b", low))


def keyword_route(question: str) -> list[str] | None:
    """Clear cases decided by keywords; None if unclear."""
    low = question.lower()
    if _has(low, FORECAST_WORDS):
        return ["forecast"]
    if _has(low, ANOMALY_WORDS):
        return ["anomaly"]
    numbers, docs, why = _has(low, NUMBER_WORDS), _has(low, DOCS_WORDS), _has(low, WHY_WORDS)
    if why and numbers:
        return ["sql", "docs"]
    if numbers and not docs:
        return ["sql"]
    if docs and not numbers:
        return ["docs"]
    return None  # both or neither -> let similarity decide


# ---------- similarity fallback ----------

_model = None
_example_vectors = None
_example_labels: list[tuple[str, str]] = []


def _load():
    """Load the local embedding model and embed the examples once."""
    global _model, _example_vectors, _example_labels
    if _model is None:
        from sentence_transformers import SentenceTransformer
        from src.rag.ingest import EMBED_MODEL
        _model = SentenceTransformer(EMBED_MODEL)
        _example_labels = [(route, q) for route, qs in EXAMPLES.items() for q in qs]
        _example_vectors = _model.encode([q for _, q in _example_labels],
                                         normalize_embeddings=True)
    return _model


def similarity_route(question: str) -> tuple[list[str], str, float]:
    """Route of the most similar example question (and that example + its score)."""
    model = _load()
    vec = model.encode([question], normalize_embeddings=True)[0]
    scores = _example_vectors @ vec  # cosine similarity (vectors are normalised)
    best = int(scores.argmax())
    label, example = _example_labels[best]
    return label.split("+"), example, float(scores[best])


def route(question: str) -> Route:
    """Pick the route(s) for a question (0 LLM calls)."""
    ticker = find_company(question)
    result = Route(routes=[], ticker=ticker, cik=COMPANIES.get(ticker),
                   quarters=find_quarters(question))

    # 0. Never change data - checked before anything else
    if wants_to_change_data(question):
        result.routes = ["refuse"]
        return result

    routes = keyword_route(question)
    if routes is None:
        routes, result.similar_to, result.score = similarity_route(question)
        result.method = "similarity"
        # Weak match + no company named -> not a question FinSight can answer
        if result.score < OUT_OF_SCOPE_THRESHOLD and ticker is None:
            routes = ["out_of_scope"]
    result.routes = routes

    if routes == ["forecast"] and ticker is None:
        result.notes.append("Forecasts need one of our 10 companies, e.g. "
                            "'Forecast Walmart's revenue for the next 2 quarters'.")
    return result
