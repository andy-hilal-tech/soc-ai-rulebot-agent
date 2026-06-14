from reasoning import handle_reasoning_query


async def handle_natural_language(text: str):
    try:
        result = handle_reasoning_query(text)
        return result, 200
    except Exception as e:
        return {
            "status": "error",
            "route": "reasoning",
            "message": f"Reasoning failed: {str(e)}"
        }, 500