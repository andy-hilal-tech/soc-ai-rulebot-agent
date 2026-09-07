# 15/6/26 11:30 MVP: backend working with reasoning, offense intake, and Teams-connected flow
import os
import re
import json
from aiohttp import web
import traceback
import base64

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
from handlers.case_handler import get_case, update_case_status


# ----------------------------
# Environment variables
# ----------------------------
PORT = int(os.getenv("PORT", "8000"))

MICROSOFT_APP_ID = os.getenv("MICROSOFT_APP_ID", "").strip()
MICROSOFT_APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD", "").strip()
MICROSOFT_APP_TYPE = os.getenv("MICROSOFT_APP_TYPE", "SingleTenant").strip()
MICROSOFT_APP_TENANT_ID = os.getenv("MICROSOFT_APP_TENANT_ID", "").strip()



class BotFrameworkConfig:
    APP_ID = MICROSOFT_APP_ID
    APP_PASSWORD = MICROSOFT_APP_PASSWORD
    APP_TYPE = MICROSOFT_APP_TYPE
    APP_TENANTID = MICROSOFT_APP_TENANT_ID


BOTFRAMEWORK_CONFIG = BotFrameworkConfig()

print(
    "[bot_auth_config] "
    f"app_id={BOTFRAMEWORK_CONFIG.APP_ID} "
    f"app_type={BOTFRAMEWORK_CONFIG.APP_TYPE} "
    f"tenant_id={BOTFRAMEWORK_CONFIG.APP_TENANTID} "
    f"password_present={bool(BOTFRAMEWORK_CONFIG.APP_PASSWORD)} "
    f"password_length={len(BOTFRAMEWORK_CONFIG.APP_PASSWORD)}",
    flush=True,
)

bot_auth = ConfigurationBotFrameworkAuthentication(
    BOTFRAMEWORK_CONFIG
)

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
    text = text.strip()
    text_lower = text.lower()

    # ----------------------------
    # Case lookup command
    # Example:
    # case CASE-20260621-AB12CD34
    # ----------------------------
    if text_lower.startswith("case "):
        case_uid = text.split(" ", 1)[1].strip()
        case = get_case(case_uid)

        if not case:
            return {
                "status": "error",
                "route": "case_lookup",
                "message": f"Case {case_uid} not found"
            }, 404

        reply = f"""Case: {case_uid}

Rule: {case.get("rule_id", "")}
Event: {case.get("event_name", "")}
Status: {case.get("implementation_status", "")}

Summary:
{case.get("offense_summary", "")}

Recommended Action:
{case.get("recommended_tuning", {}).get("details", "")}

Last Updated:
{case.get("last_updated_at", "")}
"""

        return {
            "status": "success",
            "route": "case_lookup",
            "reply": reply
        }, 200

    # ----------------------------
    # Case update command
    # Example:
    # update case CASE-20260621-AB12CD34 implemented
    # ----------------------------
    if text_lower.startswith("update case"):
        parts = text.split()

        if len(parts) < 4:
            return {
                "status": "error",
                "route": "case_update",
                "message": "Invalid update command. Use: update case <CASE_ID> <status>"
            }, 400

        case_uid = parts[2].strip()
        new_status = parts[3].strip().lower()

        updated = update_case_status(case_uid, new_status)

        if not updated:
            return {
                "status": "error",
                "route": "case_update",
                "message": f"Case {case_uid} not found"
            }, 404

        return {
            "status": "success",
            "route": "case_update",
            "reply": f"Case {case_uid} updated to '{new_status}'"
        }, 200

    # ----------------------------
    # Existing routing logic
    # ----------------------------
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

        print(
            "[TeamsRulebot] message_received "
            f"channel_id={turn_context.activity.channel_id} "
            f"text_length={len(text)}",
            flush=True,
        )

        result, status = await message_internal(text)

        print(
            "[TeamsRulebot] message_processed "
            f"status={status} "
            f"result_status={result.get('status')}",
            flush=True,
        )

        reply_text = (
            result.get("reply")
            or result.get("message")
            or "No response."
        )

        await turn_context.send_activity(
            MessageFactory.text(reply_text)
        )

        print(
            "[TeamsRulebot] reply_sent",
            flush=True,
        )


bot = TeamsRulebot()


async def on_error(context: TurnContext, error: Exception):
    print(
        f"[on_turn_error] error_type={type(error).__name__} error={error}",
        flush=True,
    )
    traceback.print_exc()

    try:
        await context.send_activity(
            "The bot encountered an internal error."
        )
    except Exception as reply_error:
        print(
            "[on_turn_error] failed_to_send_error_reply "
            f"error_type={type(reply_error).__name__} "
            f"error={reply_error}",
            flush=True,
        )


adapter.on_turn_error = on_error

def get_safe_jwt_claims(auth_header: str) -> dict:
    if not auth_header.startswith("Bearer "):
        return {}

    token = auth_header.split(" ", 1)[1].strip()
    parts = token.split(".")

    if len(parts) != 3:
        return {
            "token_format": "invalid"
        }

    try:
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)

        decoded = base64.urlsafe_b64decode(
            payload.encode("ascii")
        )

        claims = json.loads(
            decoded.decode("utf-8")
        )

        return {
            "aud": claims.get("aud"),
            "iss": claims.get("iss"),
            "tid": claims.get("tid"),
            "appid": claims.get("appid"),
            "azp": claims.get("azp"),
            "ver": claims.get("ver"),
        }

    except Exception as exc:
        return {
            "claim_decode_error": type(exc).__name__
        }


async def teams_messages(request: web.Request) -> web.Response:
    auth_header = request.headers.get(
        "Authorization",
        "",
    )

    safe_claims = get_safe_jwt_claims(
        auth_header
    )

    print(
        "[teams_messages] request_received "
        f"method={request.method} "
        f"path={request.path} "
        f"content_type={request.content_type} "
        f"has_auth={bool(auth_header)} "
        f"safe_claims={safe_claims}",
        flush=True,
    )

    try:
        invoke_response = await adapter.process(
            request,
            bot,
        )

        print(
            "[teams_messages] adapter_processed "
            f"invoke_response={invoke_response is not None}",
            flush=True,
        )

        if invoke_response:
            return invoke_response

        return web.Response(status=201)

    except Exception as exc:
        print(
            "[teams_messages] adapter_failed "
            f"error_type={type(exc).__name__} "
            f"status={getattr(exc, 'status', None)} "
            f"reason={getattr(exc, 'reason', None)} "
            f"error={exc}",
            flush=True,
        )
        raise


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
