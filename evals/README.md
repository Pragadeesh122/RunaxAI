# RAG Evaluation Harness

Make answer quality measurable so we can ship RAG/agent changes with
confidence. This harness scores the core document-chat + RAG flow — both
**retrieval relevance** and **answer quality** — against a fixed
question/document set.

## Quick start

One command runs the full eval against the local stack:

```bash
make eval                      # full eval on the `smoke` dataset
make eval DATASET=mydataset    # full eval on another dataset
make eval-retrieval            # retrieval metrics only (no answer gen, no judge cost)
make eval-unit                 # offline unit tests — no stack, no network
```

Or call the runner directly:

```bash
# Retrieval metrics only (no LLM judge, fast)
uv run python evals/run_eval.py --dataset smoke --retrieval-only

# Full evaluation with LLM-as-judge scoring
uv run python evals/run_eval.py --dataset smoke

# Use a specific judge model
uv run python evals/run_eval.py --dataset smoke --judge-model gpt-4o
```

## What it does

1. Creates an ephemeral user + project in the database
2. Uploads and ingests documents from the dataset into Pinecone
3. Runs each query through the retrieval pipeline
4. Computes retrieval metrics: Recall@k, MRR, NDCG@k, substring recall
5. (Optional) Generates answers via `project_chat_stream` and scores them with an LLM judge
6. Writes JSON + markdown reports to `evals/reports/`
7. Cleans up everything it created (Pinecone namespace, DB rows, MinIO objects)

## Prerequisites

- The local stack running: `docker compose up -d postgres redis minio minio-setup`
- DB schema applied: `uv run alembic upgrade head`
- Environment variables configured (`.env`), including `PINECONE_API_KEY`
- For judge evaluation: an LLM API key (`OPENAI_API_KEY`)

## Metrics

### Retrieval
- **Recall@k** — fraction of expected documents found in top-k results
- **MRR** — reciprocal rank of the first relevant result
- **NDCG@k** — normalized discounted cumulative gain
- **Substring Recall** — fraction of expected fact substrings found in retrieved chunks

> Filename-based metrics (recall@k, MRR, NDCG) compare against
> `expected_doc_filenames`. The harness maps each retrieved chunk's
> `document_id` back to its original dataset filename, so these are meaningful
> even though the vector store records `source` as an internal storage name.

### Answer Quality (LLM Judge, 1–5)
- **Faithfulness** — claims grounded in retrieved context
- **Completeness** — covers all expected `must_mention` items
- **Hallucination** — free of `must_not_mention` items and unsupported claims
- **Format Adherence** — matches the expected output format

> ⚠️ The `hallucination` dimension is negatively framed and the judge
> occasionally inverts its scale (scoring 1 while its reason says "no
> hallucinations present"). Read per-query `reason` fields in the JSON report
> rather than trusting the `hallucination` mean alone. See
> [`baselines/smoke.md`](baselines/smoke.md).

## Adding cases

**New query against an existing dataset** — append one JSON object per line to
`evals/datasets/<name>/queries.jsonl`:

```json
{"id": "q011", "query": "...", "expected_doc_filenames": ["xr7_datasheet.md"], "expected_chunk_substrings": ["..."], "expected_answer_traits": {"must_mention": ["..."], "must_not_mention": [], "format": "prose"}}
```

- `expected_doc_filenames` — drives recall@k / MRR / NDCG
- `expected_chunk_substrings` — drives substring_recall (case-insensitive)
- `expected_answer_traits.must_mention` / `must_not_mention` — feed the judge
- `expected_answer_traits.format` — e.g. `prose`, `list`, `json`

**New dataset** — create `evals/datasets/<name>/` with:
- `documents/` — files to ingest (md, txt, pdf, csv, docx)
- `queries.jsonl` — as above

Then run `make eval DATASET=<name>`.

## Reading results

Each run writes to `evals/reports/` (gitignored):
- `<run_id>.json` — structured data for programmatic analysis (all per-query
  metrics, answers, and judge reasons)
- `<run_id>.md` — human-readable summary with an aggregate table and per-query
  drill-down

The terminal prints the aggregate means/min/max at the end of the run.

## Baselines

Committed reference scores live in [`evals/baselines/`](baselines/). Compare a
run's aggregates against the matching baseline before/after changing retrieval,
chunking, prompts, or models. Current baseline: [`baselines/smoke.md`](baselines/smoke.md).

## CI

- **Always-on (PR gate):** the offline unit tests
  (`tests/test_eval_metrics.py`, `tests/test_eval_judge.py`) run as part of
  `uv run pytest` in `.github/workflows/pr.yml`. They need no stack or network
  and guard the metric + judge-parsing logic.
- **Advisory (manual + weekly):** `.github/workflows/eval.yml` runs the full
  end-to-end eval against an ephemeral stack + hosted Pinecone + an LLM key,
  uploads the reports as a build artifact, and writes the aggregate table to
  the job summary. It is `continue-on-error` (never blocks a merge) and
  requires the repo secrets `PINECONE_API_KEY` and `OPENAI_API_KEY`; without
  them it no-ops. Trigger it from the Actions tab ("Run workflow") or wait for
  the weekly schedule.
