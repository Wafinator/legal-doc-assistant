from pathlib import Path

import pytest

from app.documents.sections import is_heading, split_sections


@pytest.mark.parametrize(
    "line",
    [
        "# Definitions",
        "ARTICLE IV",
        "Section 5.2",
        "1. TERM",
        "12.3 Payment Terms",
        "III. ARGUMENT",
        "A. Standard of Review",
        "STATEMENT OF FACTS",
    ],
)
def test_is_heading_true_for_supported_styles(line):
    assert is_heading(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "1. The Supplier shall deliver the goods.",
        "Section 4.2 shall survive termination.",
        "The Services;",
        "",
        "x" * 101,
    ],
)
def test_is_heading_false_for_sentence_like_or_invalid_lines(line):
    assert is_heading(line) is False


def test_split_sections_on_agreement():
    text = (Path(__file__).parent / "data" / "services_agreement.txt").read_text()

    sections = split_sections(text)
    headings = [section.heading for section in sections]

    assert headings == [
        "1. DEFINITIONS",
        "2. TERM",
        "3. Fees and Payment",
        "3.1 Fees",
        "3.2 Late Payment",
        "4. CONFIDENTIALITY",
        "5. LIMITATION OF LIABILITY",
        "8. TERMINATION",
        "9. GOVERNING LAW",
        "IN WITNESS WHEREOF",
    ]
    assert [section.level for section in sections if section.heading in {"3.1 Fees", "3.2 Late Payment"}] == [2, 2]

    confidentiality = next(section for section in sections if section.heading == "4. CONFIDENTIALITY")
    assert "Section 4.2 shall survive termination of this Agreement for five (5) years." in confidentiality.text


def test_split_sections_nests_motion_subsections_without_including_next_top_level_section():
    text = (Path(__file__).parent / "data" / "motion_to_dismiss.txt").read_text()

    sections = split_sections(text)
    argument = next(section for section in sections if section.heading == "III. ARGUMENT")

    assert "A. Standard of Review" in argument.text
    assert "B. Plaintiff Did Not Allow the Cure Period" in argument.text
    assert "IV. CONCLUSION" not in argument.text
