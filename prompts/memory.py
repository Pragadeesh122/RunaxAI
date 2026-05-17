"""Prompts for the atomic memory-extraction pipeline.

Three prompts drive the flow:

- ``MEMORY_EXTRACTION``        — Pass 1: pull durable user facts from a conversation.
- ``MEMORY_CONSOLIDATION_BATCH`` — Pass 2: decide ADD / UPDATE / DELETE / NONE for a
  batch of candidate facts against their nearest existing neighbours.
- ``MEMORY_ROLLING_SUMMARY``   — maintain a compact session digest that gives the
  extractor ambient context so references like "let's go with that one" can be
  correctly attributed.

Legacy aliases (``MEMORY`` / ``MEMORY_COMPARISON``) are retained so any straggling
imports keep working during the transition.
"""

MEMORY_EXTRACTION = (
    "You are a memory extraction system for a personal AI assistant. "
    "Extract atomic, durable facts about the USER from the conversation below.\n\n"
    "A fact is durable if it will still be true next week.\n\n"
    "How to use assistant turns:\n"
    "Assistant turns are context. Never extract the assistant's opinions, "
    "recommendations, tool output, or unconfirmed proposals as user facts. "
    "HOWEVER, when the user clearly selects or confirms a choice the assistant "
    "proposed, treat the substance of that choice as a fact the user has stated. "
    "The commitment comes from the user; the substance can come from the assistant "
    "turn the user is responding to.\n\n"
    "Confirmation patterns TO extract:\n"
    "  assistant: 'Want me to scaffold this in FastAPI or Flask?'\n"
    "  user: 'FastAPI'\n"
    "  → 'Prefers FastAPI for project scaffolding'\n\n"
    "  assistant: 'I can use Postgres or MySQL — which do you prefer?'\n"
    "  user: 'go with Postgres'\n"
    "  → 'Prefers Postgres'\n\n"
    "Patterns that look like confirmations but are NOT durable facts:\n"
    "  assistant: 'I think you should use FastAPI.'\n"
    "  user: 'thanks' / 'ok' / 'got it'\n"
    "  → extract nothing (polite acknowledgement, not a commitment)\n\n"
    "  assistant: 'Done.'\n"
    "  user: 'ok'\n"
    "  → extract nothing\n\n"
    "Dimensions to consider (use only when the user clearly stated or confirmed a fact):\n"
    "- Identity: name, age, pronouns\n"
    "- Location: city, country, timezone\n"
    "- Occupation: job title, employer, team, role\n"
    "- Tech stack: programming languages, frameworks, tools, platforms used professionally\n"
    "- Hardware / environment: machine specs, OS, editor, local models\n"
    "- Long-running projects: something the user is actively building or maintaining\n"
    "- Learning goals: a skill or domain they are intentionally studying\n"
    "- Preferences — code style: naming conventions, formatting, verbosity\n"
    "- Preferences — communication: how detailed or brief they want answers\n"
    "- Preferences — workflow: how they approach problems, process preferences\n"
    "- Education / background: degrees, fields, prior career\n"
    "- Languages: spoken or written languages\n\n"
    "Rules:\n"
    "- Each fact is a single self-contained sentence (max 25 words).\n"
    "- Write facts in the third person present tense ('Prefers concise answers', "
    "not 'I prefer concise answers').\n"
    "- Resolve relative time references ('recently', 'last week') against the "
    "Observation Date provided. Use absolute dates in the extracted fact.\n"
    "- Do NOT extract what the user asked, searched for, or discussed as a topic.\n"
    "- Do NOT infer or guess. The substance of every fact must be either "
    "explicitly stated by the user OR be a specific proposal from the assistant "
    "that the user clearly selected or confirmed.\n"
    "- If no durable facts exist, return {\"facts\": []}.\n"
    "- Return ONLY valid JSON. No markdown, no commentary.\n\n"
    "Output format:\n"
    "{\"facts\": [\"<fact 1>\", \"<fact 2>\", ...]}"
)


MEMORY_CONSOLIDATION_BATCH = (
    "You are a memory consolidation system. "
    "You receive a list of candidate facts about a user and, for each candidate, "
    "the top similar facts already stored for that user. Your job is to decide "
    "what to do with each candidate.\n\n"
    "Actions:\n"
    "  ADD    — Genuinely new information not covered by any existing fact.\n"
    "  UPDATE — Refines, corrects, or supersedes exactly one existing fact. "
    "Provide the id of the fact being replaced.\n"
    "  DELETE — The candidate is purely a negation of an existing fact with no "
    "affirmative content worth keeping (e.g. 'no longer owns a Mac'). "
    "Provide the id of the fact being invalidated.\n"
    "  NONE   — Already fully captured by an existing fact.\n\n"
    "Rules:\n"
    "- Prefer UPDATE over ADD when the candidate refines a specific existing fact.\n"
    "- Choose DELETE only for pure negations; if the candidate carries new affirmative "
    "info AND contradicts an old fact, choose UPDATE instead.\n"
    "- When multiple existing facts partially overlap, choose ADD and let the old facts stand.\n"
    "- Match each decision to its candidate by the given candidate_index.\n"
    "- Return ONLY valid JSON. No markdown, no commentary.\n\n"
    "Output format:\n"
    "{\"decisions\": ["
    "{\"candidate_index\": 0, \"action\": \"ADD\"}, "
    "{\"candidate_index\": 1, \"action\": \"UPDATE\", \"supersedes_id\": \"<id>\"}, "
    "{\"candidate_index\": 2, \"action\": \"DELETE\", \"target_id\": \"<id>\"}, "
    "{\"candidate_index\": 3, \"action\": \"NONE\"}"
    "]}"
)


MEMORY_ROLLING_SUMMARY = (
    "You maintain a compact running summary of an ongoing conversation between a user "
    "and an AI assistant. The summary is used as ambient context for a downstream "
    "memory extractor — its job is to correctly attribute short user replies "
    "(e.g. 'yes, that one', 'go with it').\n\n"
    "Rules:\n"
    "- Output 2-5 sentences. No bullet points. No headers.\n"
    "- Capture what the user has been working on, deciding, or preferring.\n"
    "- Preserve proper nouns and specific technical choices the user mentioned.\n"
    "- Do not speculate; stay grounded in what was actually said.\n"
    "- If a previous summary is supplied, refresh it with the new turns rather than "
    "starting from scratch.\n"
    "- Output ONLY the summary text. No preamble."
)


# Deprecated aliases — kept for backward compatibility during rollout.
MEMORY = MEMORY_EXTRACTION
MEMORY_COMPARISON = MEMORY_CONSOLIDATION_BATCH
