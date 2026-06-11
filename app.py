from email.mime import text
import os
import re
import json
from aiohttp import web


from prompts import (
    RULE_ANALYSIS_SYSTEM_PROMPT,
    build_rule_prompt,
    build_offense_input_message,
    OFFENSE_ANALYSIS_SYSTEM_PROMPT,
    build_offense_analysis_prompt,
)
from offense_parser import (
    parse_offense_template,
    get_missing_required_fields,
    looks_like_offense_template,
)
from prompts import build_offense_input_message
from rule_loader import get_rule
from ai_client import analyze_rule
from reasoning import handle_reasoning_query


PORT = int(os.getenv("PORT", "8001"))


# ----------------------------
# Deterministic analysis handler
# ----------------------------
async def handle_rule_id(rule_id: str):
    rule = get_rule(rule_id)

    if not rule:
        return {
            "status": "error",
            "route": "rule_id",
            "message": f"Rule {rule_id} not found"
        }, 404

    rule_text = json.dumps(rule, indent=2)
    user_prompt = build_rule_prompt(rule_text)

    try:
        result = analyze_rule(RULE_ANALYSIS_SYSTEM_PROMPT, user_prompt)

        try:
            result_json = json.loads(result)
        except Exception:
            result_json = {"raw_output": result}

        analysis = result_json
        classification = analysis.get("classification", "N/A")
        reasoning = analysis.get("reasoning", "No reasoning returned.")
        recommendation = analysis.get("recommendation", "No recommendation returned.")

        return {
            "status": "success",
            "route": "rule_id",
            "reply": (
                f"Rule {rule_id}\n"
                f"Classification: {classification}\n"
                f"Reasoning: {reasoning}\n"
                f"Recommendation: {recommendation}"
            ),
            "raw": {
                "rule_id": rule_id,
                "analysis": result_json
            }
        }, 200

    except Exception as e:
        return {
            "status": "error",
            "route": "rule_id",
            "message": f"Failed to analyze rule {rule_id}: {str(e)}"
        }, 500


# ----------------------------
# Reasoning handler
# ----------------------------
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

# ----------------------------
# offense intake handler
# ----------------------------
async def handle_offense_intake():
    return {
        "status": "ok",
        "route": "offense_intake",
        "reply": build_offense_input_message()
    }, 200


# ----------------------------
# offense analysis handler
# ----------------------------
async def handle_offense_analysis(text: str):    
    print("OFFENSE RAW TEXT:", repr(text), flush=True)

    offense_data = parse_offense_template(text)
    print("PARSED OFFENSE DATA:", offense_data, flush=True)

    missing = get_missing_required_fields(offense_data)
    print("MISSING FIELDS:", missing, flush=True)


    if missing:
        return {
            "status": "error",
            "route": "offense_analysis",
            "message": "Missing required offense fields",
            "missing_fields": missing,
            "reply": (
                "Please complete the required fields before analysis:\n"
                + "\n".join(f"- {field}" for field in missing)
            )

        }, 400

    rule_id = offense_data.get("rule_id", "").strip()
    rule = get_rule(rule_id)

    if not rule:
        return {
            "status": "error",
            "route": "offense_analysis",
            "message": f"Rule {rule_id} not found in local rules database"
        }, 404

    rule_text = json.dumps(rule, indent=2)

    # No RAG yet — placeholder empty context list
    user_prompt = build_offense_analysis_prompt(
        offense_data=offense_data,
        rule_text=rule_text,
        retrieved_context=[]
    )

    try:
        result = analyze_rule(OFFENSE_ANALYSIS_SYSTEM_PROMPT, user_prompt)

        try:
            result_json = json.loads(result)
        except Exception:
            result_json = {"raw_output": result}

        return {
            "status": "success",
            "route": "offense_analysis",
            "offense_data": offense_data,
            "raw": result_json
        }, 200

    except Exception as e:
        return {
            "status": "error",
            "route": "offense_analysis",
            "message": f"Failed to analyze offense: {str(e)}"
        }, 500


# ----------------------------
# Router
# ----------------------------
def classify_message(text: str) -> str:
    text = text.strip()
    lowered = text.lower()

    # Simple deterministic route for obvious numeric lookups
    if re.fullmatch(r"\d+", text):
        return "rule_id"

    # Offense / event intake trigger phrases
    offense_triggers = [
        "new offense",
        "new event",
        "new alert",
        "offense analysis",
        "analyze offense",
        "analyze event",
    ]

    if any(trigger in lowered for trigger in offense_triggers):
        return "offense_intake"
    
    if looks_like_offense_template(text):
        return "offense_analysis"

    return "reasoning"


# ----------------------------
# HTTP endpoints
# ----------------------------
async def root(request):
    return web.json_response({
        "message": "Rulebot modern local agent is running"
    })


async def health(request):
    return web.json_response({
        "status": "ok",
        "service": "rulebot-agent"
    })


async def analyze_rule_endpoint(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"},
            status=400
        )

    rule_id = str(body.get("rule_id", "")).strip()

    if not rule_id:
        return web.json_response(
            {"error": "rule_id is required"},
            status=400
        )

    result, status = await handle_rule_id(rule_id)
    return web.json_response(result, status=status)


async def message(request):
    body = await request.json()
    text = body.get("text", "").strip()

    result, status = await message_internal(text)
    return web.json_response(result, status=status)


async def message_internal(text: str):
    route = classify_message(text)

    if route == "rule_id":
        return await handle_rule_id(text)

    if route == "offense_intake":
        return await handle_offense_intake()

    if route == "offense_analysis":
        return await handle_offense_analysis(text)

    return await handle_natural_language(text)


async def teams_messages(request):
    body = await request.json()

    # Extract message text from Teams payload
    text = body.get("text", "").strip()

    if not text:
        return web.json_response({})

    # Reuse your existing message pipeline
    result, _ = await message_internal(text)

    reply_text = result.get("reply", result.get("message", "No response"))

    return web.json_response({
        "type": "message",
        "text": reply_text
    })


app = web.Application()
app.router.add_get("/", root)
app.router.add_get("/health", health)
app.router.add_post("/analyze_rule", analyze_rule_endpoint)
app.router.add_post("/message", message)
app.router.add_post("/api/messages", teams_messages)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
