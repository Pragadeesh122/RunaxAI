# AgenticRag Project Instructions

This project is a tool-augmented document chat application (RunaxAI) that combines RAG with autonomous tool use.

## Architecture Guidelines

- **Backend:** FastAPI for API and `arq` for background workers.
- **Frontend:** Next.js 16 (App Router) with React 19 and Tailwind CSS 4.
- **Storage:** PostgreSQL (durable history), Redis (active session state/cache), Pinecone (hybrid search), MinIO (file storage).
- **LLM Layer:** Provider-agnostic abstraction in `llm/` supporting OpenAI, Anthropic, Gemini, Grok, and Ollama.
- **Memory:** Atomic fact-based user memory system with extraction and consolidation background tasks.

## Content & Blogs

The project maintains a technical blog in `frontend/content/blog/` covering core system architectures:
- `introducing-runaxai.mdx`: Project overview and mission.
- `rag-pipeline.mdx`: Adaptive retrieval, Hybrid Search, and Reranking.
- `memory-architecture.mdx`: Atomic fact extraction and pgvector consolidation.
- `caching-and-redis.mdx`: Session management and semantic tool caching.
- `llm-orchestration.mdx`: Tool planning loops, deduplication, and budgets.

## Conventions

- Always include automated tests for new features.
- Prioritize observability with OpenTelemetry spans and Prometheus metrics.
- Keep tool logic isolated in `functions/` and planning logic in `utils/tool_planner.py`.
