"""Base agent definition for project-scoped RAG agents."""

from dataclasses import dataclass, field


@dataclass
class Agent:
    """A specialized agent with its own system prompt and retrieval config."""

    name: str
    description: str
    system_prompt: str

    # Retrieval overrides (None = use adaptive defaults)
    top_k_override: int | None = None
    alpha_override: float | None = None

    # Run a HyDE pass before embedding the query. Useful for agents that
    # take short, vague user prompts (e.g. reasoning) and less useful for
    # agents whose input is already concrete (e.g. summary of "this doc").
    use_hyde: bool = False

    # Whether output should be parsed as structured JSON
    structured_output: bool = False

    # JSON schema hint injected into the prompt for structured agents
    output_schema: str = ""

    # Extra instructions appended to the context block
    context_instructions: str = ""

    # Tool names this agent is allowed to call. Empty list = single-shot
    # answer with no tool loop. Names must match registered tools in
    # `functions/` (e.g. "search", "crawl_website").
    tool_names: list[str] = field(default_factory=list)
