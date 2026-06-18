import json
from rule_loader import get_rule
from ai_client import analyze_rule
from prompts import RULE_ANALYSIS_SYSTEM_PROMPT, build_rule_prompt


def format_rule_analysis_reply(rule_id: str, analysis: dict) -> str:
    classification = analysis.get("classification", "N/A")

    reasoning = analysis.get("reasoning", "")
    tuning_options = analysis.get("tuning_options", [])

    lines = [
        f"Rule {rule_id}",
        f"Classification: {classification}",
        ""
    ]

    # Reasoning section
    if isinstance(reasoning, dict):
        detection = reasoning.get("detection")
        logic_breakdown = reasoning.get("logic_breakdown", {})
        trigger_conditions = reasoning.get("trigger_conditions")
        common_false_positives = reasoning.get("common_false_positives", [])

        lines.append("Reasoning:")
        if detection:
            lines.append(f"- Detection: {detection}")

        if isinstance(logic_breakdown, dict) and logic_breakdown:
            lines.append("- Logic breakdown:")
            for key, value in logic_breakdown.items():
                lines.append(f"  • {key}: {value}")

        if trigger_conditions:
            lines.append(f"- Trigger conditions: {trigger_conditions}")

        if isinstance(common_false_positives, list) and common_false_positives:
            lines.append("- Common false positives:")
            for item in common_false_positives:
                lines.append(f"  • {item}")

    elif isinstance(reasoning, str) and reasoning.strip():
        lines.append("Reasoning:")
        lines.append(reasoning)

    # Tuning options section
    if isinstance(tuning_options, list) and tuning_options:
        lines.append("")
        lines.append("Recommended tuning options:")

        for i, option in enumerate(tuning_options, start=1):
            if isinstance(option, dict):
                implement_as = option.get("implement_as", "Option")
                option_reasoning = option.get("reasoning", "")
                risks = option.get("risks_and_tradeoffs", "")
                compliance = option.get("compliance_implications", "")

                lines.append(f"{i}. {implement_as}")
                if option_reasoning:
                    lines.append(f"   - Why: {option_reasoning}")
                if risks:
                    lines.append(f"   - Risks/trade-offs: {risks}")
                if compliance:
                    lines.append(f"   - Compliance: {compliance}")
            else:
                lines.append(f"{i}. {str(option)}")

    return "\n".join(lines)


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

        reply_text = format_rule_analysis_reply(rule_id, result_json)

        return {
            "status": "success",
            "route": "rule_id",
            "reply": reply_text,
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