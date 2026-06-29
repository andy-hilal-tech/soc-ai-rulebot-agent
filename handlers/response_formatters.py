import json
from pathlib import Path

def sanitize_tuning_options(options):
    if not options:
        return []

    cleaned = []

    for item in options:
        if not item:
            continue

        # Handle dict-style tuning options from structured output
        if isinstance(item, dict):
            option_type = str(item.get("type", "")).strip()
            details = str(item.get("details", "")).strip()

            # Skip placeholders / empty values
            if not details:
                continue
            if details.lower() in {"recommendation", "tuning option", "n/a", "none", "-"}:
                continue

            if option_type:
                cleaned.append(f"{option_type}: {details}")
            else:
                cleaned.append(details)
            continue

        # Handle plain string fallback
        text = str(item).strip()
        if not text:
            continue
        if text.lower() in {"recommendation", "tuning option", "n/a", "none", "-"}:
            continue

        cleaned.append(text)

    return cleaned



def compact_source_label(source: str) -> str:
    if not source:
        return "Unknown source"

    # Official docs path
    if "/" in source or "\\" in source:
        return Path(source).name

    # internal_note:client-a:title
    if source.startswith("internal_note:"):
        parts = source.split(":", 2)
        if len(parts) == 3:
            _, client_id, title = parts
            return f"Internal note ({client_id}): {title}"
        return source

    # case_memory:client-a:CASE-...
    if source.startswith("case_memory:"):
        parts = source.split(":", 2)
        if len(parts) == 3:
            _, client_id, title = parts
            return f"Case memory ({client_id}): {title}"
        return source

    # rule:165072:Some Rule Name
    if source.startswith("rule:"):
        parts = source.split(":", 2)
        if len(parts) == 3:
            _, rule_id, rule_name = parts
            return f"Rule {rule_id}: {rule_name}"
        return source

    return source


def build_sources_footer(context_sources: list, max_items: int = 3) -> str:
    if not context_sources:
        return ""

    seen = []
    for src in context_sources:
        label = compact_source_label(src)
        if label not in seen:
            seen.append(label)

    if not seen:
        return ""

    lines = ["", "Sources used:"]
    for label in seen[:max_items]:
        lines.append(f"- {label}")

    if len(seen) > max_items:
        lines.append(f"- +{len(seen) - max_items} more")

    return "\n".join(lines)


def _safe_string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def _extract_assessment_text(analysis: dict) -> str:
    candidates = [
        analysis.get("assessment"),
        analysis.get("summary"),
        analysis.get("verdict"),
        analysis.get("recommendation_summary"),
        analysis.get("recommendation"),
        analysis.get("reasoning"),
    ]

    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()

        if isinstance(item, dict):
            # Try common useful keys first
            for key in [
                "detection",
                "summary",
                "assessment",
                "conclusion",
                "verdict",
                "reasoning",
            ]:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            # fallback
            return json.dumps(item, ensure_ascii=False)

    return "No high-level assessment returned."


def _format_tuning_options(analysis: dict, max_items: int = 3) -> str:
    tuning_options = analysis.get("tuning_options", [])

    if not isinstance(tuning_options, list) or not tuning_options:
        return "- No tuning options returned."

    lines = []
    for i, option in enumerate(tuning_options[:max_items], start=1):
        if isinstance(option, dict):
            label = (
                _safe_string(option.get("type"))
                or _safe_string(option.get("implement_as"))
                or _safe_string(option.get("action"))
                or "Recommendation"
            )

            detail = (
                _safe_string(option.get("details"))
                or _safe_string(option.get("reasoning"))
                or _safe_string(option.get("recommendation"))
            )

            risks = _safe_string(option.get("risks_and_tradeoffs"))
            compliance = _safe_string(option.get("compliance_implications"))

            lines.append(f"{i}. {label}")

            if detail:
                lines.append(f"   - Details: {detail}")

            if risks:
                lines.append(f"   - Risks: {risks}")

            if compliance:
                lines.append(f"   - Compliance: {compliance}")

        else:
            lines.append(f"{i}. {_safe_string(option)}")

    return "\n".join(lines)



def build_offense_reply(
    case_uid: str | None,
    offense_data: dict,
    analysis: dict,
    context_sources: list | None = None,
    case_warning: str | None = None,
) -> str:
    event_name = _safe_string(offense_data.get("event_name")) or "Unknown event"
    rule_id = _safe_string(offense_data.get("rule_id")) or "Unknown rule"
    why_fp = _safe_string(offense_data.get("why_false_positive"))
    desired = _safe_string(offense_data.get("desired_outcome"))
    analyst_notes = _safe_string(offense_data.get("analyst_notes"))

    assessment = _extract_assessment_text(analysis)
    classification = _safe_string(analysis.get("classification"))
    confidence = _safe_string(analysis.get("confidence"))

    tuning_options = analysis.get("tuning_options", [])
    recommendations = sanitize_tuning_options(tuning_options)

    similar_cases = []
    for src in context_sources or []:
        if src.startswith("case_memory:"):
            similar_cases.append(compact_source_label(src))

    
    lines = [
        "Offense Analysis Summary",
        "",
        f"Event: {event_name}",
        f"Rule ID: {rule_id}",
    ]


    if classification:
        lines.append(f"Classification: {classification}")

    if confidence:
        lines.append(f"Confidence: {confidence}")

    if case_uid:
        lines.append(f"Case ID: {case_uid}")

    lines.extend([
        "",
        "Assessment:",
        assessment,
    ])

    if similar_cases:
        lines.extend([
            "",
            "Similar historical case(s) found:",
        ])
        for case_ref in similar_cases[:2]:
            lines.append(f"- {case_ref}")

    if why_fp:
        lines.extend([
            "",
            "False-positive rationale provided:",
            why_fp,
        ])

    if desired:
        lines.extend([
            "",
            "Desired outcome:",
            desired,
        ])

    if analyst_notes:
        lines.extend([
            "",
            "Analyst notes:",
            analyst_notes,
        ])

    lines.extend([
        "",
        "Recommended tuning options:",
    ])

    if recommendations:
        for rec in recommendations:
            lines.append(f"- {rec}")
    else:
        lines.append("- No concrete tuning recommendation could be generated from the provided context.")

    if case_warning:
        lines.extend([
            "",
            f"Warning: {case_warning}",
        ])

    sources_footer = build_sources_footer(context_sources or [], max_items=3)
    if sources_footer:
        lines.append(sources_footer)

    return "\n".join(lines)


def build_reasoning_reply(reply_text: str, context_sources: list | None = None) -> str:
    reply_text = _safe_string(reply_text)

    sources_footer = build_sources_footer(context_sources or [], max_items=3)
    if sources_footer:
        return f"{reply_text}\n{sources_footer}"

    return reply_text