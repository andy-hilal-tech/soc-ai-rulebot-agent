EXPECTED_OFFENSE_FIELDS = [
    # Core identifiers
    "offense_id",
    "client_id",
    "evidence_mode",

    # Human-readable evidence block / summary fields
    "evidence_summary",

    # Rule / offense metadata
    "rule_id",
    "rule_ids",
    "event_name",
    "event_description",

    # Legacy compatibility fields
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

    # New offense-linked evidence fields
    "top_source_ips",
    "top_destination_ips",
    "top_qids",
    "top_usernames",
    "top_log_sources",
    "top_categories",
    "qid_logsource_category_distribution",
    "combined_distribution",
    "representative_events",

    # Compact summary / analyst input
    "payload_summary",
    "why_false_positive",
    "desired_outcome",
    "analyst_notes",
]

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


def parse_offense_template(text: str) -> dict:
    text = normalize_offense_template_text(text)
    result = {field: "" for field in EXPECTED_OFFENSE_FIELDS}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key in result:
            result[key] = value

    return result

def get_missing_required_fields(offense_data: dict) -> list[str]:
    missing = []

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