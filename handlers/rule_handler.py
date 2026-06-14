import json
from rule_loader import get_rule
from ai_client import analyze_rule
from prompts import RULE_ANALYSIS_SYSTEM_PROMPT, build_rule_prompt


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
        recommendation = analysis.get("tuning_options", "No tuning options returned.")

        return {
            "status": "success",
            "route": "rule_id",
            "reply": (
                f"Rule {rule_id}\n"
                f"Classification: {classification}\n"
                f"Reasoning: {reasoning}\n"
                f"Tuning options: {recommendation}"
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