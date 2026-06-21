from reasoning import handle_reasoning_query as _handle_reasoning_core
from handlers.response_formatters import build_reasoning_reply


async def handle_natural_language(text: str):
    try:
        result = _handle_reasoning_core(text)

        reply_text = build_reasoning_reply(
            reply_text=result.get("reply", ""),
            context_sources=result.get("context_sources", []),
        )

        result["reply"] = reply_text
        return result, 200

    except Exception as e:
        return {
            "status": "error",
            "route": "reasoning",
            "message": f"Reasoning failed: {str(e)}"
        }, 500