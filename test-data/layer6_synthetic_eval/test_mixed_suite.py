from pathlib import Path

from src.corpus_analyzer import build_corpus_analysis
from src.export import build_manifest_data
from src.parser import DocumentParser, discover_files
from src.scorer import QualityScorer, generate_split_recommendations

CORPUS_DIR = Path(__file__).parent / "corpus"


def _load_docs():
    parser = DocumentParser()
    files = discover_files(str(CORPUS_DIR))
    docs = [parser.parse(path) for path in files]
    return {doc.metadata.filename: doc for doc in docs}


def test_synthetic_mixed_suite_exercises_expected_signals():
    docs_by_name = _load_docs()
    assert len(docs_by_name) == 5

    tracker = docs_by_name["04_sparse_tracker_template.pdf"]
    # Keep this test robust even if PDF byte size changes slightly across environments.
    tracker.metadata.file_size_bytes = max(tracker.metadata.file_size_bytes, 60_000)

    docs = list(docs_by_name.values())
    corpus_analysis = build_corpus_analysis(docs)
    scorer = QualityScorer(corpus_analysis=corpus_analysis)
    cards = [scorer.score(doc) for doc in docs]
    cards_by_name = {Path(card.file_path).name: card for card in cards}

    control = cards_by_name["01_clean_control.md"]
    assert control.overall_score >= 80

    fix_heavy = cards_by_name["02_fix_heavy_policy.md"]
    fix_issue_categories = {issue.category for issue in fix_heavy.all_issues}
    assert "self_containment" in fix_issue_categories
    assert "heading_quality" in fix_issue_categories
    assert "acronym_definitions" in fix_issue_categories

    docx_text = docs_by_name["03_table_layout_lesson.docx"].full_text
    assert "Students will bring home their Handout C and explain their goal." in docx_text

    tracker_card = cards_by_name["04_sparse_tracker_template.pdf"]
    tracker_structure_issues = [issue for issue in tracker_card.all_issues if issue.category == "structure"]
    assert any("template-like" in issue.message for issue in tracker_structure_issues)

    split_recommendations = generate_split_recommendations(docs, cards, corpus_analysis=corpus_analysis)
    assert any(rec.source_file == "05_topic_overlap_packet.md" for rec in split_recommendations)

    analyses = []
    for doc in docs:
        from src.models import ContentAnalysis

        analyses.append(ContentAnalysis(summary=f"Synthetic summary for {doc.metadata.filename}"))

    manifest = build_manifest_data(
        docs=docs,
        analyses=analyses,
        cards=cards,
        corpus_analysis=corpus_analysis,
        split_recommendations=split_recommendations,
    )

    assert "retrieval_mode_distribution" in manifest["corpus"]
    assert manifest["corpus"]["retrieval_mode_distribution"]
