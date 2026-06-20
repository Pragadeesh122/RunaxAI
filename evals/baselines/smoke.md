# Baseline — `smoke` dataset

Reference scores for the core document-chat + RAG flow on the `smoke` dataset
(4 documents, 10 queries). Re-run `make eval` and compare against this table
before/after changing retrieval, chunking, prompts, or models.

## Provenance

| Field | Value |
|-------|-------|
| Date | 2026-06-19 |
| Dataset | `smoke` (4 docs, 10 queries) |
| Generation model | `gpt-5.4` (whatever `project_chat_stream` routes to) |
| Judge model | `gpt-4o-mini` |
| Retrieval | hybrid dense+sparse, rerank on, `top_k=20`, HyDE off |
| Command | `uv run python evals/run_eval.py --dataset smoke` |

## Scores

### Retrieval (0–1, higher is better)

| Metric | Mean | Min | Max |
|--------|------|-----|-----|
| recall@5 | 1.000 | 1.000 | 1.000 |
| recall@10 | 1.000 | 1.000 | 1.000 |
| recall@20 | 1.000 | 1.000 | 1.000 |
| ndcg@5 | 0.605 | 0.431 | 1.000 |
| mrr | 0.475 | 0.250 | 1.000 |
| substring_recall | 1.000 | 1.000 | 1.000 |

The expected document is always retrieved within the top 5 (recall@5 = 1.0) and
every expected fact substring appears in the retrieved chunks
(substring_recall = 1.0). NDCG/MRR are lower because the *correct* document is
often not ranked first — there is headroom in result ordering, not coverage.

### Answer quality — LLM judge (1–5, higher is better)

| Dimension | Mean | Min | Max |
|-----------|------|-----|-----|
| faithfulness | 5.00 | 5 | 5 |
| completeness | 5.00 | 5 | 5 |
| hallucination | 4.60 | 1 | 5 |
| format_adherence | 4.30 | 4 | 5 |

Answers are fully grounded and complete across the set. `format_adherence`
dips because some answers add markdown (bold/headers) where plain prose was
expected.

## Known caveats

- **`hallucination` dimension polarity is fragile.** On one query (q009) the
  judge returned `score: 1` while its own reason said "there are no
  hallucinations present" — i.e. it inverted the negatively-framed scale. This
  drags the mean down to 4.60 despite no real hallucination. Treat the
  `hallucination` mean as noisy until the rubric is reworded (candidate
  follow-up: rename to `groundedness` with an explicit "5 = fully grounded"
  anchor). Per-query reasons in the JSON report are the source of truth.
- Judge scores are model-dependent. Pin `--judge-model` when comparing runs.
- Numbers are from a 10-query smoke set; treat as directional, not precise.
