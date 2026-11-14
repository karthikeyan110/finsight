"""Find the 10-K section ("Item 1. Business", "Item 7. MD&A", ...) for every line of a filing.

Why this exists: companies format their headings differently.
  - Apple:   "Item 7.    Management's Discussion ..."  (number + title on one line)
  - Amazon:  "Item 7."  then the title on the NEXT line  (heading split over two lines)
  - Microsoft repeats "Item 7" as a page header on every MD&A page
  - Walmart quotes "Item 1A" / "Item 3" in the text (cross-references)
  - JPMorgan puts its MD&A inside the annual-report pages after "Item 15"

Rules:
  1. A heading is a short line "Item N." + a title, on the same line or the next one.
  2. The table of contents lists every Item first; the body starts at the 2nd "Item 1".
  3. Real headings always go up in order (1, 1A, ..., 7, 7A, 8, ...): keep the longest
     such run, which drops page headers and cross-references.
  4. JPMorgan-style annual reports: after "Item 15", "Management's discussion and analysis"
     starts the MD&A (labelled Item 7) and "Report of Independent Registered Public
     Accounting Firm" starts the financial statements (labelled Item 8).
"""
import re
from pathlib import Path

from bs4 import BeautifulSoup

ITEM = re.compile(r"^item\s*(\d+[a-c]?)\.?(\s+\S.*)?$", re.IGNORECASE)
COVER = "Cover page / contents"

# 10-K items in their fixed order
ORDER = ["1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8", "9", "9A", "9B", "9C",
         "10", "11", "12", "13", "14", "15", "16"]
NAMES = {"1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments",
         "1C": "Cybersecurity", "2": "Properties", "3": "Legal Proceedings",
         "4": "Mine Safety Disclosures", "5": "Market for Equity", "6": "Reserved",
         "7": "MD&A", "7A": "Market Risk", "8": "Financial Statements",
         "9": "Changes in Accountants", "9A": "Controls and Procedures", "9B": "Other Information",
         "9C": "Foreign Jurisdictions", "10": "Directors and Officers",
         "11": "Executive Compensation", "12": "Security Ownership", "13": "Relationships",
         "14": "Accountant Fees", "15": "Exhibits and Schedules", "16": "10-K Summary"}
MDA_ITEM = "7"

# JPMorgan-style annual-report markers (only used after "Item 15")
AR_MDA = re.compile(r"^management.s discussion and analysis$", re.IGNORECASE)
AR_FS = re.compile(r"^report of independent registered public accounting firm$", re.IGNORECASE)


def label(item: str, note: str = "") -> str:
    """'7' -> 'Item 7. MD&A'."""
    return f"Item {item}. {NAMES.get(item, '')}{note}".strip()


def read_lines(path: Path) -> list[str]:
    """The filing's visible text, one cleaned line per text block."""
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    for hidden in soup.find_all("ix:header"):  # hidden XBRL data, not readable text
        hidden.decompose()
    lines = [" ".join(l.split()) for l in soup.get_text("\n").split("\n")]
    return [l for l in lines if l]


def _in_order(heads: list) -> list:
    """Longest run of headings whose items go up in order (drops page headers/cross-refs)."""
    if not heads:
        return []
    keys = [ORDER.index(h[1]) for h in heads]
    best, prev = [1] * len(heads), [-1] * len(heads)
    for i in range(len(heads)):
        for j in range(i):
            if keys[j] < keys[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(len(heads)), key=lambda k: best[k])
    chain = []
    while i != -1:
        chain.append(heads[i])
        i = prev[i]
    return chain[::-1]


def find_headings(lines: list[str]) -> list[tuple[int, str, str]]:
    """Section starts as (line index, item, label), in document order."""
    heads = []
    for i, line in enumerate(lines):
        m = ITEM.match(line)
        if not m or len(line) >= 160:
            continue
        item = m.group(1).upper()
        title = (m.group(2) or "").strip()
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        nxt2 = lines[i + 2] if i + 2 < len(lines) else ""
        # "Item 1" + "C" on the next line = Item 1C (the HTML split the item number)
        if not title and re.fullmatch(r"[A-Ca-c]\.?", nxt) and item[-1].isdigit():
            item, nxt = item + nxt[0].upper(), nxt2
        if item not in ORDER:
            continue
        if not title and len(nxt) < 120 and not ITEM.match(nxt):
            title = nxt  # heading split over two lines
        if title:
            heads.append((i, item))

    # Rule 2: skip the table of contents (body starts at the 2nd "Item 1")
    ones = [h for h in heads if h[1] == "1"]
    body = ones[1][0] if len(ones) > 1 else 0
    chain = _in_order([h for h in heads if h[0] >= body])
    result = [(i, item, label(item)) for i, item in chain]

    # Rule 4: annual-report MD&A and financial statements after "Item 15"
    item15 = next((i for i, item in chain if item == "15"), None)
    if item15 is not None:
        mda = next((i for i in range(item15, len(lines) - 1)
                    if AR_MDA.match(lines[i]) and lines[i + 1].lower().startswith("the following")), None)
        if mda is not None:
            result.append((mda, MDA_ITEM, label(MDA_ITEM, " (annual report)")))
            fs = next((i for i in range(mda, len(lines)) if AR_FS.match(lines[i])), None)
            if fs is not None:
                result.append((fs, "8", label("8", " (annual report)")))
            result.sort()
    return result


def sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split a filing into (section label, its lines). Heading lines are left out."""
    starts = find_headings(lines)
    heading_lines = {i for i, _, _ in starts}
    out, current, buf = [], COVER, []
    pending = dict((i, lab) for i, _, lab in starts)
    for i, line in enumerate(lines):
        if i in pending:
            if buf:
                out.append((current, buf))
            current, buf = pending[i], []
        if i not in heading_lines:
            buf.append(line)
    if buf:
        out.append((current, buf))
    return out


def is_mda(section_label: str) -> bool:
    """True for Item 7 (MD&A), including JPMorgan's annual-report MD&A."""
    return section_label.startswith(f"Item {MDA_ITEM}. ")
