"""Task 12 — TF-IDF Matrix Consistency across layers."""

import pytest

pytestmark = [pytest.mark.cross_layer, pytest.mark.timeout(120)]


def test_task12_tfidf_dimensions_match(engine, newsgroups_data):
    """All layers should agree on document count."""
    texts = newsgroups_data["texts"][:500]
    tfidf_matrix, vectorizer = engine.compute_tfidf(texts)

    # Entropy should produce one value per document
    entropies = [engine.shannon_entropy_from_vector(tfidf_matrix[i]) for i in range(tfidf_matrix.shape[0])]
    assert len(entropies) == tfidf_matrix.shape[0]

    # Similarity matrix should be square with same dimension
    sim = engine.compute_similarity(tfidf_matrix)
    assert sim.shape == (tfidf_matrix.shape[0], tfidf_matrix.shape[0])

    # Clustering should assign one label per document
    clusters = engine.spectral_cluster(sim, k=5)
    assert len(clusters) == tfidf_matrix.shape[0]


def test_task12_modified_doc_propagates(engine):
    """Changing a document should change its BM25 score for related queries."""
    texts = [
        "Machine learning algorithms process data using neural networks and gradient descent optimization.",
        "Natural language processing understands text through tokenization parsing and semantic analysis.",
        "Computer vision analyzes images with convolutional filters and object detection methods.",
    ]

    # Doc 0 should have a positive BM25 score for an ML query
    scores1 = engine.bm25_scores("machine learning algorithms neural", texts)
    assert scores1[0] > 0, "Doc 0 should score > 0 for ML query"
    assert scores1[0] > scores1[2], "Doc 0 (ML) should outscore doc 2 (vision) for ML query"

    # Modify doc 0 to be about finance — its ML score should drop
    texts_modified = texts.copy()
    texts_modified[0] = (
        "Financial planning requires careful budgeting investment strategy and retirement savings accounts."
    )
    scores2 = engine.bm25_scores("machine learning algorithms neural", texts_modified)
    assert scores2[0] < scores1[0], (
        f"Modified doc should score lower for ML query: {scores2[0]:.4f} vs {scores1[0]:.4f}"
    )
