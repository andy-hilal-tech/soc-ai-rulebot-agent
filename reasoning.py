from ai_client import analyze_rule
from prompts import (
    GENERAL_REASONING_SYSTEM_PROMPT,
    build_grounded_reasoning_prompt,
)
from retrieval import retrieve_context_with_sources


def handle_reasoning_query(text: str) -> dict:
    retrieved = retrieve_context_with_sources(text)
    context_chunks = [item["text"] for item in retrieved]
    context_sources = [item["source"] for item in retrieved]

    user_prompt = build_grounded_reasoning_prompt(text, context_chunks)
    result = analyze_rule(GENERAL_REASONING_SYSTEM_PROMPT, user_prompt)

    return {
        "status": "success",
        "route": "reasoning",
        "reply": result,
        "context_used": context_chunks,
        "context_sources": context_sources,
    }