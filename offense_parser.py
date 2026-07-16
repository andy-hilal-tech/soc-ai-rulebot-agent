import json


EXPECTED_OFFENSE_FIELDS = [
    "offense_id",
    "client_id",
    "evidence_mode",
    "evidence_summary",

    "rule_id",
    "rule_ids",
    "event_name",
    "event_description",

    "source_ip",
    "source_port",
    "destination_ip",
    "destination_port",
    "username",
    "log_source",
    "log_source_id",
    "qid",
    "category",

    "magnitude",
    "severity",
    "relevance",
    "credibility",
    "start_time",
    "event_count",

    "top_source_ips",
    "top_destination_ips",
    "top_qids",
    "top_usernames",
    "top_log_sources",
    "top_categories",
    "qid_logsource_category_distribution",
    "combined_distribution",
    "representative_events",
    "offense_rules_raw",
    "qradar_rule_api_metadata",
    "resolved_rule_bindings",

    "payload_summary",
    "why_false_positive",
    "desired_outcome",
    "analyst_notes",
]


JSON_OFFENSE_FIELDS = {
    "rule_ids",
    "top_source_ips",
    "top_destination_ips",
    "top_qids",
    "top_usernames",
    "top_log_sources",
    "top_categories",
    "qid_logsource_category_distribution",
    "combined_distribution",
    "representative_events",
    "offense_rules_raw",
    "qradar_rule_api_metadata",
    "resolved_rule_bindings",
}


REQUIRED_OFFENSE_FIELDS = [
    "rule_id",
    "why_false_positive",
    "desired_outcome",
]


def normalize_offense_template_text(text: str) -> str:
    lines = []

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("- "):
            stripped = stripped[2:].strip()

        lines.append(stripped)

    return "\n".join(lines)


def try_parse_json_value(key: str, value: str):
    if key not in JSON_OFFENSE_FIELDS:
        return value

    if not value:
        return []

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_offense_template(text: str) -> dict:
    text = normalize_offense_template_text(text)

    result = {field: "" for field in EXPECTED_OFFENSE_FIELDS}

    current_multiline_key = None
    multiline_values = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            continue

        # Handle indented evidence_summary lines as multiline content.
        if raw_line.startswith(" ") and current_multiline_key:
            multiline_values.append(line.strip())
            continue

        # Commit previous multiline field if needed.
        if current_multiline_key and multiline_values:
            result[current_multiline_key] = "\n".join(multiline_values)
            current_multiline_key = None
            multiline_values = []

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key not in result:
            continue

        if key == "evidence_summary" and not value:
            current_multiline_key = key
            multiline_values = []
            continue

        result[key] = try_parse_json_value(key, value)

    # Commit trailing multiline field.
    if current_multiline_key and multiline_values:
        result[current_multiline_key] = "\n".join(multiline_values)

    return result


def get_missing_required_fields(offense_data: dict) -> list[str]:
    
    for field in REQUIRED_OFFENSE_FIELDS:
        if not str(offense_data.get(field, "")).strip():
            missing.append(field)

    return missing


def looks_like_offense_template(text: str) -> bool:
    normalized = normalize_offense_template_text(text).lower()

    has_rule_id = "rule_id:" in normalized
    has_false_positive = "why_false_positive:" in normalized
    has_desired_outcome = "desired_outcome:" in normalized
    has_analyst_notes = "analyst_notes:" in normalized
    has_offense_id = "offense_id:" in normalized
    has_evidence_mode = "evidence_mode:" in normalized

    return (
        has_rule_id
        and (
            has_false_positive
            or has_desired_outcome
            or has_analyst_notes
            or has_offense_id
            or has_evidence_mode
        )
    )