"""Tests for the 10-K section reader (src/rag/sections.py). No files, no Gemini."""
from src.rag.sections import COVER, find_headings, is_mda, sections

TOC = ["Item 1.", "Business", "Item 1A.", "Risk Factors", "Item 7.", "Management's Discussion",
       "Item 8.", "Financial Statements"]


def items(lines):
    return [item for _, item, _ in find_headings(lines)]


def test_one_line_headings():
    lines = TOC + ["Item 1. Business", "We sell things.", "Item 1A. Risk Factors", "Risky.",
                   "Item 7. Management's Discussion and Analysis", "Revenue grew.",
                   "Item 8. Financial Statements", "Numbers."]
    assert items(lines) == ["1", "1A", "7", "8"]


def test_headings_split_over_two_lines():
    # Amazon/Alphabet style: "Item 7." then the title on the next line
    lines = TOC + ["Item 1.", "Business", "We sell things.", "Item 7.",
                   "Management's Discussion and Analysis", "Revenue grew."]
    assert items(lines) == ["1", "7"]


def test_item_number_split_from_its_letter():
    # "Item 1" + "C" on the next line = Item 1C, not a second Item 1
    lines = TOC + ["Item 1. Business", "Text.", "Item 1", "C", "Cybersecurity", "We protect data.",
                   "Item 2. Properties", "Offices."]
    assert items(lines) == ["1", "1C", "2"]


def test_page_headers_and_cross_references_are_ignored():
    # Microsoft repeats "Item 7" as a page header; Walmart quotes "Item 1A" in the text
    lines = TOC + ["Item 1. Business", "Text.", "Item 7. Management's Discussion", "Part 1.",
                   "Item 7", "Metrics", "Part 2.", "Item 1A", "Risk Factors", "see above.",
                   "Item 8. Financial Statements", "Numbers."]
    assert items(lines) == ["1", "7", "8"]


def test_text_before_the_body_is_cover():
    lines = ["Annual report cover"] + TOC + ["Item 1. Business", "We sell things."]
    labels = [label for label, _ in sections(lines)]
    assert labels[0] == COVER and labels[1] == "Item 1. Business"


def test_annual_report_mda_after_item_15():
    # JPMorgan style: the MD&A sits in the annual-report pages after "Item 15"
    lines = TOC + ["Item 1. Business", "Bank.", "Item 7. Management's Discussion", "See annual report.",
                   "Item 8. Financial Statements", "See annual report.",
                   "Item 15. Exhibits, Financial Statement Schedules", "Index.",
                   "Management's discussion and analysis", "The following is Management's discussion",
                   "Net revenue was $177.6 billion, up 12%.",
                   "Report of Independent Registered Public Accounting Firm", "Opinion."]
    by_label = {label: " ".join(text) for label, text in sections(lines)}
    mda = [lab for lab in by_label if "annual report" in lab and is_mda(lab)]
    assert mda and "Net revenue was $177.6 billion" in by_label[mda[0]]
    fs = [lab for lab in by_label if lab.startswith("Item 8.") and "annual report" in lab]
    assert fs and "Opinion." in by_label[fs[0]]
