import json
import asyncio
from prompts import (
    build_offense_input_message,
    OFFENSE_ANALYSIS_SYSTEM_PROMPT,
    build_offense_analysis_prompt,
)
from offense_parser import (
    parse_offense_template,
    get_missing_required_fields,
)
from rule_loader import get_rule
from retrieval import retrieve_context_with_sources
from ai_client import analyze_rule
from handlers.case_writer import build_case_record, save_case_record
from handlers.response_formatters import build_offense_reply


async def handle_offense_intake():
    return {
        "status": "ok",
        "route": "offense_intake",
        "reply": build_offense_input_message()
    }, 200


async def handle_offense_analysis(text: str):
    offense_data = parse_offense_template(text)
    missing = get_missing_required_fields(offense_data)

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

    retrieval_query = " ".join([
        f"rule id {rule_id}",
        offense_data.get("event_name", ""),
        offense_data.get("event_description", ""),
        offense_data.get("why_false_positive", ""),
        offense_data.get("desired_outcome", ""),
        offense_data.get("analyst_notes", ""),
        offense_data.get("payload_summary", ""),
        rule_text,
    ]).strip()

    retrieved = retrieve_context_with_sources(
        retrieval_query,
        route="offense_analysis",
        rule_id=rule_id,
        client_id=offense_data.get("client_id", "") or None,
    )
    context_chunks = [item["text"] for item in retrieved]
    context_sources = [item["source"] for item in retrieved]

    user_prompt = build_offense_analysis_prompt(
        offense_data=offense_data,
        rule_text=rule_text,
        retrieved_context=context_chunks
    )

    try:
        result = analyze_rule(OFFENSE_ANALYSIS_SYSTEM_PROMPT, user_prompt)

        try:
            result_json = json.loads(result)
        except Exception:
            result_json = {"raw_output": result}


        case_uid = None
        case_warning = None

        try:
            case_record = build_case_record(
                offense_data=offense_data,
                analysis=result_json,
                created_by="rulebot",
            )

            saved_case = await asyncio.wait_for(
                asyncio.to_thread(save_case_record, case_record),
                timeout=10,
            )
            case_uid = saved_case.get("case_uid")

        except Exception as case_error:
            case_warning = f"Case record could not be saved: {str(case_error)}"

        reply_text = build_offense_reply(
            case_uid=case_uid,
            offense_data=offense_data,
            analysis=result_json,
            context_sources=context_sources,
            case_warning=case_warning,
        )

        return {
            "status": "success",
            "route": "offense_analysis",
            "case_uid": case_uid,
            "case_warning": case_warning,
            "reply": reply_text,
            "offense_data": offense_data,
            "context_used": context_chunks,
            "context_sources": context_sources,
            "raw": result_json
        }, 200

    except Exception as e:
        return {
            "status": "error",
            "route": "offense_analysis",
            "message": f"Failed to analyze offense: {str(e)}"
        }, 500