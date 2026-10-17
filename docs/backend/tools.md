# Tool System

Tools are autonomous capabilities available to the general chat orchestrator. The LLM decides when and how to use them based on the user's query.

## Architecture

```mermaid
flowchart LR
    A[LLM requests tool calls] --> B[Tool Planner]
    B -->|selected| C[Tool Router]
    B -->|suppressed| D[Skip]
    C --> E{Cache hit?}
    E -->|yes| F[Return cached result]
    E -->|no| G[Execute function]
    G --> H[Cache result]
    H --> F
```

## Auto-Discovery

`functions/__init__.py` scans the `functions/` package at import time:

1. Iterates over all Python modules (skips `_`-prefixed and `tool_router`, `compare_kb`)
2. Looks for a `SCHEMA` dict (OpenAI function calling format)
3. Finds the function matching `schema["function"]["name"]`
4. Registers the function, schema, and optional `CACHEABLE` flag and `POLICY` dict

No manual registration — add a module with `SCHEMA` and a matching function.

## Built-in Tools

| Tool | Description | Cacheable | Execution mode |
|------|-------------|-----------|---------------|
| `search` | Web search via Tavily/Brave or opt-in Parallel Search MCP + LLM summarization | Yes | parallel_safe |
| `query_db` | Natural language → SQL → PostgreSQL (read-only user) | Yes | sequential_first |
| `browser_task` | Headless browser for interactive web pages | No | sequential_first |
| `crawl_website` | Extract and read web page content via Crawl4AI | No | sequential_first |
| `query_local_kb` | Search local FAISS knowledge base | Yes | sequential_first |
| `portfolio` | Portfolio-specific queries | Yes | sequential_first |

### Keyless web search with Parallel

To use [Parallel Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp)
for general chat's existing `search` tool, set this in the root `.env` file:

```dotenv
SEARCH_PROVIDER=parallel
```

Install the updated dependencies with `uv sync` and restart the API. With Docker
Compose, rebuild and recreate the API with `docker compose up -d --build api`.
Ask a current-information question in general chat, such as "What changed in the
latest Python release?", to let the orchestrator choose the search tool.

Parallel uses Streamable HTTP at `https://search.parallel.ai/mcp`. Anonymous
search is free, uses Fast mode, and requires no Parallel account or API key.
The existing LLM summarizer consumes the returned titles, URLs, and excerpts.
Search requests have a ten-second deadline. Service errors, including free-tier
limits, are reported as tool errors; this selection does not fall back to the
keyed providers. Existing semantic caching still applies.

Leave `SEARCH_PROVIDER` unset or blank to retain the existing Tavily-first,
Brave-second fallback chain, configured with `TAVILY_API_KEY` and `BRAVE_API_KEY`.

## Tool Schema Format

Each tool exports an OpenAI function calling schema:

```python
SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "What this tool does and when to use it",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
            },
            "required": ["query"],
        },
    },
}
```

## Tool Policies

Policies control how the tool planner handles each tool. Set a `POLICY` dict in the tool module:

```python
POLICY = {
    "execution_mode": "parallel_safe",    # or "sequential_first"
    "max_parallel_instances": 3,          # max concurrent calls
    "requires_fresh_input": False,        # needs prior tool results?
    "dedupe_key_fields": ("query",),      # fields for fingerprinting
    "verification_only_after_result": False,
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `execution_mode` | `sequential_first` | `parallel_safe` allows concurrent execution with other parallel-safe tools. `sequential_first` runs alone. |
| `max_parallel_instances` | 1 | Maximum concurrent calls of this tool per step |
| `requires_fresh_input` | `True` | If `True`, requires new tool evidence since last call before running in parallel |
| `dedupe_key_fields` | `()` | Which argument fields are used for fingerprinting (empty = all args) |

## Tool Planner

The planner (`utils/tool_planner.py`) sits between the LLM's requested tool calls and execution:

### Fingerprinting

Each tool call is fingerprinted as `SHA-256(tool_name + dedupe_key_fields)`. This creates a stable identifier for "the same call" regardless of argument ordering.

### Duplicate Suppression

Two types of duplicates are suppressed:

1. **In-batch duplicates** — the LLM requests the same call twice in one response
2. **Cross-step duplicates** — the same fingerprint was executed in a previous step, and no new tool evidence has arrived since

The `current_evidence_version` counter increments after each tool result. If a fingerprint's `last_evidence_version` matches the current version, it means no new information has arrived since that tool last ran, so repeating it is pointless.

### Parallel vs Sequential

The planner is intentionally conservative. In practice, only distinct `search` fan-out calls run in parallel in v1. Mixed batches and sequential-first tools fall back to executing only the first candidate, then the orchestrator asks the model again with the new result.

## Tool Router

`functions/tool_router.py` dispatches tool calls:

1. Parse arguments from the tool call JSON
2. Check if the tool is registered
3. For cacheable tools with a `query` argument, check the semantic cache
4. Execute the function
5. Cache the result if cacheable
6. Return a `{"role": "tool", "tool_call_id": ..., "content": ...}` message

Each execution is wrapped in an OpenTelemetry span and emits Prometheus metrics (duration, status, cache behavior).

## Caching

Tools marked with `CACHEABLE = True` use a Redis semantic cache (`memory/cache.py`). The cache is keyed on `(tool_name, query)` and checks for semantically similar queries before executing. This avoids redundant API calls (e.g., searching the web for the same query twice across sessions).

## Adding a New Tool

Create `functions/my_tool.py`:

```python
SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "Describe what this tool does and when the LLM should use it",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Parameter description",
                },
            },
            "required": ["query"],
        },
    },
}

# Optional: enable result caching
CACHEABLE = True

# Optional: execution policy
POLICY = {
    "execution_mode": "sequential_first",
    "max_parallel_instances": 1,
    "requires_fresh_input": True,
    "dedupe_key_fields": ("query",),
}


def my_tool(query: str) -> dict:
    """Function name must match SCHEMA function name."""
    # ... implementation ...
    return {"result": "..."}
```

The tool is auto-discovered on restart and immediately available to the orchestrator.
