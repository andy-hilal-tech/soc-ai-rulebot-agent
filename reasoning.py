from ai_client import analyze_rule
from prompts import (
    GENERAL_REASONING_SYSTEM_PROMPT,
    build_grounded_reasoning_prompt,
)
from retrieval import retrieve_context


def handle_reasoning_query(text: str) -> dict:
    context_chunks = retrieve_context(text)
    user_prompt = build_grounded_reasoning_prompt(text, context_chunks)

    result = analyze_rule(GENERAL_REASONING_SYSTEM_PROMPT, user_prompt)

    return {
        "status": "success",
        "route": "reasoning",
        "reply": result,
        "context_used": context_chunks,
    }