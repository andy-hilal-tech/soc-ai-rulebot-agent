from ai_client import analyze_rule
from prompts import GENERAL_REASONING_SYSTEM_PROMPT, build_reasoning_prompt


def handle_reasoning_query(text: str) -> dict:
    user_prompt = build_reasoning_prompt(text)
    result = analyze_rule(GENERAL_REASONING_SYSTEM_PROMPT, user_prompt)

    return {
        "status": "success",
        "route": "reasoning",
        "reply": result
    }