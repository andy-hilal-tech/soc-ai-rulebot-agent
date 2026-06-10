EXPECTED_OFFENSE_FIELDS = [
    "offense_id",
    "rule_id",
    "event_name",
    "event_description",
    "source_ip",
    "source_port",
    "destination_ip",
    "destination_port",
    "username",
    "log_source",
    "qid",
    "category",
    "magnitude",
    "start_time",
    "event_count",
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


def parse_offense_template(text: str) -> dict:
    result = {field: "" for field in EXPECTED_OFFENSE_FIELDS}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue

        line = line[1:].strip()

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
    lowered = text.lower()

    matched_fields = 0
    for field in EXPECTED_OFFENSE_FIELDS:
        needle = f"- {field}:"
        if needle in lowered:
            matched_fields += 1

    # treat it as a submitted template if several known fields appear
    return matched_fields >= 4