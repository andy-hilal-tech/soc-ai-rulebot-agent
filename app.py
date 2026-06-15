# 15/6/26 11:30 MVP: backend working with reasoning, offense intake, and Teams-connected flow
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

from rule_loader import get_rule
from ai_client import analyze_rule
from reasoning import handle_reasoning_query
from retrieval import retrieve_context_with_sources

from botbuilder.core import TurnContext, MessageFactory, ActivityHandler
from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)

from handlers.rule_handler import handle_rule_id
from handlers.offense_handler import handle_offense_intake, handle_offense_analysis
from handlers.reasoning_handler import handle_natural_language



# ----------------------------
# Environment variables
# ----------------------------
PORT = int(os.getenv("PORT", "8001"))

MICROSOFT_APP_ID = os.getenv("MICROSOFT_APP_ID", "").strip()
MICROSOFT_APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD", "").strip()
MICROSOFT_APP_TYPE = os.getenv("MICROSOFT_APP_TYPE", "SingleTenant").strip()
MICROSOFT_APP_TENANT_ID = os.getenv("MICROSOFT_APP_TENANT_ID", "").strip()

BOTFRAMEWORK_CONFIG = {
    "MicrosoftAppId": MICROSOFT_APP_ID,
    "MicrosoftAppPassword": MICROSOFT_APP_PASSWORD,
    "MicrosoftAppType": MICROSOFT_APP_TYPE,
    "MicrosoftAppTenantId": MICROSOFT_APP_TENANT_ID,
}

bot_auth = ConfigurationBotFrameworkAuthentication(BOTFRAMEWORK_CONFIG)
adapter = CloudAdapter(bot_auth)


# ----------------------------
# Router
# ----------------------------
def classify_message(text: str) -> str:
    text = text.strip()
    lowered = text.lower()

    if re.fullmatch(r"\d+", text):
        return "rule_id"

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
# Shared internal message pipeline
# ----------------------------
async def message_internal(text: str):
    route = classify_message(text)

    if route == "rule_id":
        return await handle_rule_id(text)

    if route == "offense_intake":
        return await handle_offense_intake()

    if route == "offense_analysis":
        return await handle_offense_analysis(text)

    return await handle_natural_language(text)


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
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    rule_id = str(body.get("rule_id", "")).strip()

    if not rule_id:
        return web.json_response({"error": "rule_id is required"}, status=400)

    result, status = await handle_rule_id(rule_id)
    return web.json_response(result, status=status)


async def message(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    text = str(body.get("text", "")).strip()

    if not text:
        return web.json_response({"error": "text is required"}, status=400)

    result, status = await message_internal(text)
    return web.json_response(result, status=status)


# ----------------------------
# Bot Framework-compatible /api/messages
# ----------------------------
class TeamsRulebot(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext):
        text = (turn_context.activity.text or "").strip()

        result, _status = await message_internal(text)
        reply_text = result.get("reply") or result.get("message") or "No response."

        await turn_context.send_activity(MessageFactory.text(reply_text))


bot = TeamsRulebot()


async def on_error(context: TurnContext, error: Exception):
    print(f"[on_turn_error] {error}", flush=True)
    try:
        await context.send_activity("The bot encountered an internal error.")
    except Exception:
        pass


adapter.on_turn_error = on_error


async def teams_messages(request: web.Request) -> web.Response:
    invoke_response = await adapter.process(request, bot)

    if invoke_response:
        return invoke_response

    return web.Response(status=201)


# ----------------------------
# App routes
# ----------------------------
app = web.Application()
app.router.add_get("/", root)
app.router.add_get("/health", health)
app.router.add_post("/analyze_rule", analyze_rule_endpoint)
app.router.add_post("/message", message)
app.router.add_post("/api/messages", teams_messages)


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
