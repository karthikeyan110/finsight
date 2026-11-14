"""Resolve the companies named in a question to exact ciks - before any SQL is written.

Why: the SQL agent used to match names with ILIKE '%coca%cola%', which also matched
Coca-Cola Consolidated (a separate bottler), so answers had 2 rows instead of 1.

resolve_companies(question) -> list of Match (one per company mentioned)
  Match.cik            the single cik, or None when the name is ambiguous
  Match.candidates     [(cik, name), ...] - several when ambiguous (ask the user)

How:
  1. Alias table for our 10 companies ("Google" -> Alphabet, "Coke" -> Coca-Cola).
  2. Every company's core name (its name without Inc, Corp, Co, ...) from dim_company.
  3. The longest name found in the question wins ("Coca-Cola Consolidated" beats
     "Coca-Cola"; "Johnson & Johnson" beats "Johnson"). Two companies with the SAME
     core name (e.g. two "TechTarget" filers) = ambiguous.
  4. A one-word name must be written with a capital letter ("Target", not "target
     price"), so ordinary words in a question are not mistaken for companies.
"""
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import duckdb

from src.agent.router import ALIASES
from src.rag.download_10k import COMPANIES

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "gold" / "finsight.duckdb"

# Legal-form words that are not part of a company's real name
SUFFIX_WORDS = {"inc", "incorporated", "corp", "corporation", "co", "company", "plc", "ltd",
                "limited", "llc", "lp", "l", "p", "nv", "n", "v", "sa", "s", "a", "ag", "se",
                "the", "de", "del", "lllp", "llp", "&"}
# One-word names that are also common question words (never treated as companies)
COMMON_WORDS = {"what", "which", "show", "list", "total", "revenue", "income", "assets", "cash",
                "sector", "company", "companies", "quarter", "year", "fiscal", "growth", "profit",
                "net", "operating", "largest", "biggest", "highest", "lowest", "compare", "between",
                "first", "last", "next", "most", "best", "united", "american", "national", "general",
                "global", "first", "new", "capital", "energy", "health", "financial", "bank"}


@dataclass
class Match:
    text: str                       # the words found in the question
    cik: int | None                 # exact cik, or None when ambiguous
    name: str | None
    candidates: list = field(default_factory=list)  # [(cik, name)] when ambiguous


def normalize(text: str) -> str:
    """Lower case, '&' kept, other punctuation -> spaces ("Apple's" -> "apple s")."""
    return " ".join(re.sub(r"[^a-z0-9&]+", " ", text.lower()).split())


def core_name(name: str) -> str:
    """'COCA COLA CO' -> 'coca cola'; 'JOHNSON & JOHNSON' -> 'johnson & johnson'."""
    words = normalize(name).split()
    while words and words[-1] in SUFFIX_WORDS:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


@lru_cache(maxsize=1)
def _index() -> dict[str, dict[int, str]]:
    """core name -> {cik: official name}, for every company + our aliases."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.execute("SELECT cik, name FROM dim_company").fetchall()
    con.close()
    names = {cik: name for cik, name in rows}
    index: dict[str, dict[int, str]] = {}
    for cik, name in rows:
        core = core_name(name)
        if len(core) >= 3:
            index.setdefault(core, {})[cik] = name
    for alias, ticker in ALIASES.items():  # our 10 companies' everyday names
        cik = COMPANIES[ticker]
        index.setdefault(normalize(alias), {})[cik] = names.get(cik, ticker)
    return index


def _capitalised(word: str, question: str) -> bool:
    """True if the word appears in the question starting with a capital letter."""
    return any(m.group(0)[0].isupper() for m in re.finditer(rf"\b{re.escape(word)}\b", question, re.I))


def resolve_companies(question: str) -> list[Match]:
    """All companies named in the question (longest names first, no overlaps)."""
    q = f" {normalize(question)} "
    found = []  # (start, end, core)
    for core in _index():
        one_word = " " not in core
        if one_word and (core in COMMON_WORDS or len(core) < 4):
            continue
        start = q.find(f" {core} ")
        if start < 0:
            continue
        if one_word and not _capitalised(core, question):
            continue
        found.append((start, start + len(core) + 1, core))

    # Longest names win; skip names inside a longer match ("coca cola" inside
    # "coca cola consolidated")
    matches, taken = [], []
    for start, end, core in sorted(found, key=lambda f: -(f[1] - f[0])):
        if any(start < e and end > s for s, e in taken):
            continue
        taken.append((start, end))
        ciks = _index()[core]
        if len(ciks) == 1:
            cik, name = next(iter(ciks.items()))
            matches.append(Match(core, cik, name))
        else:
            matches.append(Match(core, None, None, sorted(ciks.items())))
    return sorted(matches, key=lambda m: q.find(f" {m.text} "))


def sql_hint(matches: list[Match]) -> str:
    """Text added to the SQL question so the SQL filters on exact ciks, not names."""
    exact = [m for m in matches if m.cik is not None]
    if not exact:
        return ""
    listed = ", ".join(f"{m.name} (cik {m.cik})" for m in exact)
    ciks = ", ".join(str(m.cik) for m in exact)
    rule = (f"f.cik = {exact[0].cik}" if len(exact) == 1 else f"f.cik IN ({ciks})")
    return (f"\n\nCompany: {listed}. Filter with {rule}; "
            "do not match company names with ILIKE.")


def ambiguity_message(match: Match) -> str:
    """Ask the user which company they mean (no LLM call)."""
    options = "; ".join(f"{name} (cik {cik})" for cik, name in match.candidates[:6])
    return (f"Several companies match \"{match.text}\": {options}. "
            "Which one do you mean? Please ask again with the full company name.")
