# Claude Code Prompt: Fix Folder Recommendation Quality

## Context

kb-prep's folder recommender produces poor folder names and misassignments. Running `analyze` on a corpus of ~25 financial literacy lesson files (grades 4-5) produces output like:

```
4-5.FL.12 Handout B. Exploring My Dream Job.pdf  →  Financial Literacy Lesson 11
4-5.FL.10 Handout A. Risk Sorting Activity.docx  →  Handout A: Practicing For My First College Application
4-5.FL.5 Lesson - ...Saving for Now...           →  Handout A: Practicing For My First College Application
```

Problems visible in the output:
1. **Folder names are document titles** — "Handout A: Practicing For My First College Application" is a filename, not a topic category
2. **Wrong assignments** — Lesson 12 (careers/dream jobs) landed in "Financial Literacy Lesson 11" (insurance)
3. **Cluster labels use first entity name** — `get_file_clusters()` labels by `"{top_type}: {top_name}"` where `top_name = names[0]`, which is just the first entity alphabetically or by insertion order
4. **PDF/DOCX duplicates aren't handled** — the same lesson exists as both `.pdf` and `.docx` but they may end up in different folders
5. **Silhouette validation is never called** — `validate_assignments()` exists in `recommender.py` (line 276) but the CLI never calls it
6. **RECOMMEND_FOLDERS prompt says "for anam.ai"** — should be generic since folder recommendations run for all users

## What to Fix

### 1. Better cluster labeling in `graph_builder.py` → `get_file_clusters()`

**File:** `src/graph_builder.py`, around line 280-294

The current label is just the first entity name in the component. Instead, use PageRank to find the most important entity in the cluster and use that as the label. The graph already has PageRank available.

```python
# Current (bad):
top_name = names[0] if names else f"cluster-{idx}"

# Should use PageRank to pick the most representative entity name
```

Compute PageRank scores for the full graph once, then for each component pick the highest-PageRank entity name. This gives semantically meaningful labels like "Insurance" instead of whatever entity happened to be inserted first.

### 2. Improve the RECOMMEND_FOLDERS prompt

**File:** `src/prompts.py`, starting at line 57

Changes needed:
- Remove "anam.ai" reference from the prompt (make it generic)
- Add an explicit instruction: "Folder names must be SHORT TOPIC LABELS (2-4 words), never document titles or filenames"
- Add: "If a `graph_cluster` label is provided, use it as a hint for grouping but generate your own descriptive folder name"
- Add: "Documents that are clearly the same content in different formats (e.g., same title as .pdf and .docx) must go in the same folder"
- Add: "Never use a document's filename or title as a folder name"

### 3. Deduplicate PDF/DOCX pairs before clustering

**File:** `src/recommender.py`

Before building doc_summaries in `_graph_llm_recommend()` and `_llm_recommend()`, detect and flag duplicate file pairs (same stem, different extension). Include a `"duplicate_of"` field in the doc_summaries JSON so the LLM knows to assign them together. After getting assignments back, propagate assignments from the primary to duplicates.

Implementation approach:
```python
def _detect_format_duplicates(docs: list[ParsedDocument]) -> dict[str, str]:
    """Map duplicate filenames to their primary.

    Two files are duplicates if their stems match after normalizing
    punctuation and whitespace (e.g., "4-5.FL.10 Handout B. Types of Insurance.pdf"
    and "4-5.FL.10 Handout B. Types of Insurance.docx").
    """
    from pathlib import Path
    stem_to_files: dict[str, list[str]] = {}
    for doc in docs:
        stem = Path(doc.metadata.filename).stem.strip().lower()
        stem_to_files.setdefault(stem, []).append(doc.metadata.filename)

    duplicates = {}
    for stem, files in stem_to_files.items():
        if len(files) > 1:
            primary = files[0]
            for dup in files[1:]:
                duplicates[dup] = primary
    return duplicates
```

Then after getting assignments back, ensure duplicates go to the same folder:
```python
for dup, primary in duplicates.items():
    if primary in assignments:
        assignments[dup] = assignments[primary]
```

### 4. Wire up silhouette validation in the CLI

**File:** `src/cli.py`

In the `analyze` command (around line 215 after recommendation is generated), call `validate_assignments()` and display the results:

```python
# After recommendation is generated:
if corpus_analysis.similarity_matrix.size > 0:
    sil_score, misplaced = recommender.validate_assignments(
        recommendation.file_assignments,
        corpus_analysis.similarity_matrix,
        corpus_analysis.doc_labels,
    )
    if sil_score > 0:
        console.print(f"\n[dim]Folder coherence (silhouette): {sil_score:.2f}[/dim]")
    if misplaced:
        console.print(f"[yellow]⚠ {len(misplaced)} document(s) may be misplaced:[/yellow]")
        for filename, score in misplaced:
            console.print(f"  [yellow]{filename} (silhouette: {score:.2f})[/yellow]")
```

Also wire it up in the `fix` command (around line 380-400 after folder recommendation is shown there too).

### 5. Also add silhouette to the report

**File:** `src/cli.py`

In the `_report_recommendations()` function (find it), add a silhouette score section. The report should include the overall score and list any flagged misplacements.

### 6. Handle misplaced docs — optional reassignment

In `recommender.py`, add a `reassign_misplaced()` method:

```python
def reassign_misplaced(
    self,
    assignments: dict[str, str],
    misplaced: list[tuple[str, float]],
    similarity_matrix,
    doc_labels: list[str],
) -> dict[str, str]:
    """Reassign documents with negative silhouette scores to their nearest folder."""
    import numpy as np

    misplaced_files = {f for f, _ in misplaced}
    folder_centroids: dict[str, list[int]] = {}

    for i, label in enumerate(doc_labels):
        folder = assignments.get(label)
        if folder and label not in misplaced_files:
            folder_centroids.setdefault(folder, []).append(i)

    new_assignments = dict(assignments)
    for filename, _ in misplaced:
        if filename not in doc_labels:
            continue
        doc_idx = doc_labels.index(filename)
        best_folder = None
        best_sim = -1
        for folder, indices in folder_centroids.items():
            avg_sim = float(np.mean([similarity_matrix[doc_idx, j] for j in indices]))
            if avg_sim > best_sim:
                best_sim = avg_sim
                best_folder = folder
        if best_folder:
            new_assignments[filename] = best_folder

    return new_assignments
```

Call this from the CLI when silhouette flags misplacements, and show a "[reassigned]" note next to affected files in the output table.

## Files to Modify

| File | Changes |
|------|---------|
| `src/graph_builder.py` | Use PageRank for cluster labels instead of first entity name |
| `src/prompts.py` | Fix RECOMMEND_FOLDERS prompt — remove anam.ai, add folder naming rules |
| `src/recommender.py` | Add `_detect_format_duplicates()`, add `reassign_misplaced()`, propagate assignments to duplicates |
| `src/cli.py` | Wire up silhouette validation in `analyze` and `fix` commands, add to report |

## Tests to Add or Update

**File:** `tests/test_graph.py`
- Test that `get_file_clusters()` labels use the highest-PageRank entity, not the first entity
- Test with a graph where the first entity is generic but a later entity has higher PageRank

**File:** `tests/test_recommender.py` (new or append to existing)
- Test `_detect_format_duplicates()` with PDF/DOCX pairs, near-matches, and no duplicates
- Test that `reassign_misplaced()` moves a doc with negative silhouette to the nearest cluster
- Test that duplicate files always get the same folder assignment

**File:** `tests/test_integration.py`
- Test that silhouette validation runs end-to-end in the analyze pipeline without crashing

## Constraints

- Don't change the 4-tier priority in `recommend()` (graph+LLM > LLM > graph > heuristic)
- Don't add new dependencies
- Keep `validate_assignments()` signature compatible (it's already correct)
- Run `python3 -m pytest tests/ -v` — all 58+ tests must pass
- Run `ruff check .` — no lint errors
- The `upload` command should NOT be modified (folder recommendations flow through to it already)

## Verification

After changes, run `analyze` on a test corpus and confirm:
1. Folder names are short topic labels (2-4 words), not document titles
2. PDF/DOCX pairs of the same document go to the same folder
3. Silhouette score is displayed after the folder table
4. Any misplaced documents are flagged with a warning
5. All existing tests pass
