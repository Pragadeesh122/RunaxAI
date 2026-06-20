.PHONY: eval eval-retrieval eval-unit

# Full quality eval: retrieval metrics + answer generation + LLM judge.
# Requires the local stack (Postgres, Redis, MinIO) plus Pinecone + an LLM key.
eval:
	uv run python evals/run_eval.py --dataset $(or $(DATASET),smoke)

# Fast retrieval-only eval: no answer generation, no judge (no LLM judge cost).
eval-retrieval:
	uv run python evals/run_eval.py --dataset $(or $(DATASET),smoke) --retrieval-only

# Offline unit tests for the eval metrics + judge parsing (no stack, no network).
eval-unit:
	uv run pytest tests/test_eval_metrics.py tests/test_eval_judge.py -q
