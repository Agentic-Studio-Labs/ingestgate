from src.models import Paragraph
from src.parser import DocumentParser


def test_filter_pdf_noise_removes_copyright_and_page_numbers():
    parser = DocumentParser()
    paragraphs = [
        Paragraph(text="1", level=0, style="pdf-size-10.0", index=0),
        Paragraph(
            text="© 2016 by Junior Achievement USA. All rights reserved. Name:",
            level=0,
            style="pdf-size-9.0",
            index=1,
        ),
        Paragraph(text="Students will define SMART goals.", level=0, style="pdf-size-11.0", index=2),
    ]

    cleaned = parser._filter_pdf_noise(paragraphs)

    assert len(cleaned) == 1
    assert cleaned[0].text == "Students will define SMART goals."
    assert cleaned[0].index == 0


def test_merge_split_pdf_headings_joins_multiline_titles():
    paragraphs = [
        Paragraph(text="Anchor Chart: SMART Goals and Achieving", level=1, style="pdf-size-20.0", index=0),
        Paragraph(text="Your Dreams", level=1, style="pdf-size-20.0", index=1),
        Paragraph(text="Body text starts here.", level=0, style="pdf-size-11.0", index=2),
    ]

    merged = DocumentParser._merge_split_pdf_headings(paragraphs)

    assert merged[0].text == "Anchor Chart: SMART Goals and Achieving Your Dreams"
    assert merged[0].is_heading
    assert merged[1].text == "Body text starts here."


def test_pdf_body_merge_avoids_cross_cell_sentence_jam():
    paragraphs = [
        Paragraph(text="My goals are clearly stated.", level=0, style="pdf-size-11.0", index=0),
        Paragraph(text="My goals are stated, but are unclear.", level=0, style="pdf-size-11.0", index=1),
    ]

    merged = DocumentParser._merge_pdf_paragraphs(paragraphs)

    assert len(merged) == 2
