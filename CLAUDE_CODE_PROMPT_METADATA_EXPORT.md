# Claude Code Prompt: Metadata Export (Sidecar JSON + Corpus Manifest)

## Context

kb-prep runs LLM analysis that extracts rich metadata per document (domain, topics, audience, content_type, key_concepts, suggested_tags, summary, entities, relationships) plus corpus-level data (scores, folder assignments, knowledge graph, similarity matrix). Currently this metadata is **only** output as Rich terminal text and a human-readable Markdown report. There is no machine-readable export that a downstream RAG pipeline (LlamaIndex, LangChain, Pinecone, Weaviate, etc.) can consume.

This prompt adds two complementary export formats:
- **Sidecar JSON files** — one `.meta.json` per document, written alongside the fixed Markdown
- **Corpus manifest** — a single `manifest.json` at the output directory root with everything

## Data Available for Export

### Per-document (from `ContentAnalysis` in `src/models.py`):
- `domain` (str)
- `topics` (list[str])
- `audience` (str)
- `content_type` (str)
- `key_concepts` (list[str])
- `suggested_tags` (list[str])
- `summary` (str)
- `entities` (list of {name, type, description})
- `relationships` (list of {source, target, type, context})

### Per-document (from `ScoreCard` in `src/models.py`):
- `overall_score` (float, 0-100)
- `readiness` (EXCELLENT/GOOD/FAIR/POOR)
- Per-criterion scores and issues

### Per-document (from `DocMetrics` in `src/models.py`):
- `entropy` (float, 0-1)
- `coherence` (float, 0-1)
- `readability_grade` (float, Flesch-Kincaid)
- `self_retrieval_score` (float, 0-1)
- `info_density` (list[float])
- `topic_boundaries` (list[int])

### Per-document (from folder recommendation):
- `folder_assignment` (str — the recommended folder path)

### Corpus-level:
- `folder_structure` (the full FolderRecommendation tree)
- `knowledge_graph` (entities, relationships, clusters, cross-doc edges)
- `similarity_matrix` (doc × doc cosine similarity)
- `corpus_stats` (total docs, avg score, entity counts, etc.)

## What to Build

### 1. Add a serialization module: `src/export.py`

Create a new file `src/export.py` with these functions:

```python
"""Export analysis results as machine-readable JSON.

Produces two formats:
- Sidecar files: one .meta.json per document, co-located with the fixed Markdown
- Corpus manifest: a single manifest.json with all documents, scores, graph, and folder structure
"""

import json
from pathlib import Path
from typing import Optional

from .models import (
    ContentAnalysis,
    CorpusAnalysis,
    DocMetrics,
    FolderRecommendation,
    ScoreCard,
    ParsedDocument,
)
from .graph_builder import KnowledgeGraph


def write_sidecar(
    output_dir: str,
    filename_stem: str,
    doc: ParsedDocument,
    analysis: ContentAnalysis,
    card: ScoreCard,
    metrics: Optional[DocMetrics],
    folder: str,
) -> str:
    """Write a .meta.json sidecar file alongside the fixed Markdown.

    Returns the path to the written file.
    """
    ...


def write_manifest(
    output_dir: str,
    docs: list[ParsedDocument],
    analyses: list[ContentAnalysis],
    cards: list[ScoreCard],
    corpus_analysis: CorpusAnalysis,
    recommendation: FolderRecommendation,
    graph: Optional[KnowledgeGraph],
) -> str:
    """Write a corpus-level manifest.json to the output directory root.

    Returns the path to the written file.
    """
    ...
```

### 2. Sidecar file format

Each sidecar is named `{stem}.meta.json` and placed in the same subfolder as its Markdown file. Example: if the fixed file is `Insurance Concepts/insurance-types.md`, the sidecar is `Insurance Concepts/insurance-types.meta.json`.

Schema:

```json
{
  "kb_prep_version": "0.1.0",
  "source_file": "4-5.FL.10 Handout B. Types of Insurance.docx",
  "output_file": "insurance-types.md",
  "analysis": {
    "domain": "education",
    "topics": ["insurance", "financial literacy", "risk management"],
    "audience": "students, grades 4-5",
    "content_type": "lesson handout",
    "key_concepts": ["health insurance", "auto insurance", "premiums"],
    "suggested_tags": ["insurance", "financial-literacy", "grade-4-5"],
    "summary": "Handout describing different types of insurance..."
  },
  "scores": {
    "overall": 72.5,
    "readiness": "GOOD",
    "criteria": {
      "self_containment": {"score": 88.0, "weight": 0.20, "issues": 1},
      "retrieval_aware": {"score": 65.0, "weight": 0.20, "issues": 1},
      "heading_quality": {"score": 84.0, "weight": 0.15, "issues": 2}
    }
  },
  "metrics": {
    "entropy": 0.42,
    "coherence": 0.71,
    "readability_grade": 6.2,
    "self_retrieval_score": 0.65,
    "info_density": [0.31, 0.45, 0.28],
    "topic_boundaries": [4, 12]
  },
  "entities": [
    {"name": "Health Insurance", "type": "concept", "description": "Coverage for medical expenses"}
  ],
  "relationships": [
    {"source": "Health Insurance", "target": "Insurance Premium", "type": "related_to", "context": "..."}
  ],
  "folder": "Insurance Concepts"
}
```

Implementation notes:
- Entities and relationships come from `ContentAnalysis.entities` and `ContentAnalysis.relationships` — serialize using their dataclass fields
- Scores criteria dict: iterate `card.results`, use `category` as key, include `score`, `weight`, and `len(issues)`
- Metrics: pull from `corpus_analysis.doc_metrics[doc.metadata.filename]` — may be None if corpus analysis wasn't run
- Use `json.dumps(data, indent=2, ensure_ascii=False)` for readable output with Unicode preserved

### 3. Manifest file format

A single `manifest.json` in the output directory root. Schema:

```json
{
  "kb_prep_version": "0.1.0",
  "generated_at": "2026-03-25T14:30:00Z",
  "corpus": {
    "total_documents": 25,
    "avg_score": 68.4,
    "readiness_distribution": {"EXCELLENT": 3, "GOOD": 10, "FAIR": 8, "POOR": 4},
    "total_entities": 142,
    "total_relationships": 87,
    "cross_document_edges": 34
  },
  "documents": [
    {
      "source_file": "4-5.FL.10 Handout B. Types of Insurance.docx",
      "output_file": "Insurance Concepts/insurance-types.md",
      "sidecar_file": "Insurance Concepts/insurance-types.meta.json",
      "folder": "Insurance Concepts",
      "overall_score": 72.5,
      "readiness": "GOOD",
      "domain": "education",
      "topics": ["insurance", "financial literacy"],
      "entity_count": 5,
      "relationship_count": 3
    }
  ],
  "folders": [
    {
      "name": "Insurance Concepts",
      "description": "Documents about types of insurance and risk management",
      "document_count": 8,
      "children": []
    }
  ],
  "knowledge_graph": {
    "entities": [
      {"name": "Health Insurance", "type": "concept", "source_file": "...", "description": "..."}
    ],
    "relationships": [
      {"source": "Health Insurance", "target": "Premium", "type": "related_to", "source_file": "...", "context": "..."}
    ],
    "clusters": [
      {"label": "Insurance", "entities": ["Health Insurance", "Auto Insurance", "Premium"]},
      {"label": "Saving", "entities": ["Budget", "Savings Account", "Goal Setting"]}
    ]
  },
  "similarity_matrix": {
    "labels": ["file1.docx", "file2.docx"],
    "matrix": [[1.0, 0.42], [0.42, 1.0]]
  }
}
```

Implementation notes:
- `generated_at`: use `datetime.now(timezone.utc).isoformat()`
- `folders`: recursively serialize `FolderRecommendation.root.children` — each `FolderNode` has `name`, `description`, `children`, `document_files`
- `knowledge_graph.entities`: iterate `graph._entities.values()`, serialize each Entity's fields
- `knowledge_graph.relationships`: iterate `graph._relationships`, serialize each Relationship's fields
- `knowledge_graph.clusters`: use `graph.find_clusters()` which returns `list[list[str]]` — generate labels from the cluster's highest-PageRank entity (if the PageRank labeling from the folder prompt has been implemented) or just use `"Cluster 1"`, `"Cluster 2"`, etc.
- `similarity_matrix`: convert `corpus_analysis.similarity_matrix` (numpy ndarray) to nested lists via `.tolist()`. For large corpora (>100 docs) skip this field or truncate to save space — add a threshold check
- `readiness_distribution`: count from `card.readiness` values

### 4. Wire into the `fix` command in `src/cli.py`

Add a `--export-meta` flag (default: True, disable with `--no-export-meta`) to the `fix` command.

In the file-writing loop (around line 385-406 in cli.py), after writing each Markdown file to its subfolder, also write the sidecar:

```python
# After writing the .md file to target_path:
if export_meta:
    doc_metrics = corpus_analysis.doc_metrics.get(doc.metadata.filename)
    folder_name = _norm_assignments.get(_normalize_quotes(filename), "General")
    # Find the matching analysis and card for this doc
    doc_idx = docs.index(doc)
    write_sidecar(
        output_dir=target_dir,
        filename_stem=fixed_stem,
        doc=doc,
        analysis=analyses[doc_idx],
        card=cards[doc_idx],
        metrics=doc_metrics,
        folder=folder_name,
    )
```

After the file-writing loop completes, write the manifest:

```python
if export_meta:
    manifest_path = write_manifest(
        output_dir=output,
        docs=docs,
        analyses=analyses,
        cards=cards,
        corpus_analysis=corpus_analysis,
        recommendation=recommendation,
        graph=graph,
    )
    console.print(f"[green]Metadata:[/green] {manifest_path} + {len(docs)} sidecar files")
```

### 5. Also wire into the `analyze` command

The `analyze` command doesn't write fixed files, but it still has all the metadata. Add a `--export-meta` / `--no-export-meta` flag. When enabled, write:
- The manifest to the source directory (or a specified output path)
- Sidecar files next to the original source documents (in a `.kb-prep/` subdirectory to avoid polluting the source folder)

For analyze, the output location should be `{source_path}/.kb-prep/`:
```python
if export_meta:
    meta_dir = os.path.join(path, ".kb-prep")
    os.makedirs(meta_dir, exist_ok=True)
    # Write sidecars into .kb-prep/
    for doc, analysis, card in zip(docs, analyses, cards):
        doc_metrics = corpus_analysis.doc_metrics.get(doc.metadata.filename)
        folder_name = recommendation.file_assignments.get(doc.metadata.filename, "")
        write_sidecar(meta_dir, doc.metadata.stem, doc, analysis, card, doc_metrics, folder_name)
    # Write manifest
    manifest_path = write_manifest(meta_dir, docs, analyses, cards, corpus_analysis, recommendation, graph)
    console.print(f"[green]Metadata exported:[/green] {meta_dir}/")
```

### 6. Add `--json-output` to the `analyze` command

Currently `--json-output` only exists on `score`. Add it to `analyze` as well. When enabled, print the full manifest JSON to stdout instead of the Rich terminal output. This lets users pipe it: `python -m src.cli analyze ./docs/ --llm-key KEY --json-output | jq .corpus`.

## Files to Modify

| File | Changes |
|------|---------|
| `src/export.py` | **New file** — `write_sidecar()` and `write_manifest()` |
| `src/cli.py` | Add `--export-meta`/`--no-export-meta` flag to `fix` and `analyze`; add `--json-output` to `analyze`; call export functions after pipeline completes |
| `src/models.py` | No changes needed — existing dataclasses have all the fields |
| `src/graph_builder.py` | May need a `to_dict()` or `serialize()` method on `KnowledgeGraph` for clean manifest export (optional — could also do it in export.py) |

## Tests to Add

**File:** `tests/test_export.py` (new)

```python
def test_write_sidecar_creates_file():
    """Sidecar JSON is written with correct schema."""
    # Create a temp dir, a fake doc/analysis/card, call write_sidecar
    # Assert file exists, parse JSON, check required keys

def test_sidecar_schema_keys():
    """Sidecar contains all required top-level keys."""
    # Check: kb_prep_version, source_file, output_file, analysis, scores, metrics, entities, relationships, folder

def test_write_manifest_creates_file():
    """Manifest JSON is written with correct schema."""
    # Create temp dir, fake data, call write_manifest
    # Assert file exists, parse JSON, check required keys

def test_manifest_corpus_stats():
    """Manifest corpus section has correct counts."""
    # Verify total_documents, avg_score, readiness_distribution match input data

def test_manifest_similarity_matrix_skipped_for_large_corpus():
    """Similarity matrix is omitted when corpus exceeds 100 documents."""
    # Create 101 fake docs, verify similarity_matrix is absent or null

def test_sidecar_handles_missing_metrics():
    """Sidecar handles None metrics gracefully."""
    # Pass metrics=None, verify metrics field is null or empty dict

def test_manifest_knowledge_graph_section():
    """Manifest includes entities and relationships from the graph."""
    # Build a small graph, serialize, verify entity/relationship counts match

def test_sidecar_unicode_preserved():
    """Unicode in topics/entities is preserved (not escaped to ASCII)."""
    # Use topics with accented characters, verify they appear unescaped in JSON
```

## Constraints

- No new dependencies (just `json`, `datetime`, `pathlib` from stdlib)
- Sidecars must be valid JSON parseable by `json.loads()`
- Manifest must be valid JSON parseable by `json.loads()`
- Numpy arrays must be converted via `.tolist()` before serialization (numpy types are not JSON-serializable)
- Entity/Relationship serialization: use dataclass fields directly, not `dataclasses.asdict()` (which would recurse into nested objects and could break on non-serializable types)
- Don't modify the Markdown output content — sidecars are purely alongside, not embedded
- Run `python3 -m pytest tests/ -v` — all tests must pass
- Run `ruff check .` — no lint errors

## Verification

After implementation:
1. Run `python -m src.cli fix ./test-docs/ --llm-key KEY` and confirm:
   - Each subfolder has both `.md` and `.meta.json` files
   - `manifest.json` exists at the output root
   - Both parse cleanly with `python -c "import json; json.load(open('manifest.json'))"`
2. Run `python -m src.cli analyze ./test-docs/ --llm-key KEY --export-meta` and confirm:
   - `.kb-prep/` directory created in source folder
   - Sidecar files and manifest present
3. Run `python -m src.cli analyze ./test-docs/ --llm-key KEY --json-output` and confirm:
   - JSON printed to stdout (no Rich formatting mixed in)
   - Pipeable: `... --json-output | jq .corpus.total_documents`
4. All existing tests pass
5. New tests in `test_export.py` pass
