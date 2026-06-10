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

    print("PARSER INPUT REPR:", repr(text), flush=True)

    for raw_line in text.splitlines():
        print("RAW LINE:", repr(raw_line), flush=True)

        line = raw_line.strip()
        print("STRIPPED LINE:", repr(line), flush=True)

        if not line.startswith("-"):
            print("SKIP: does not start with '-'", flush=True)
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

    # Strong indicators that this is a filled offense template
    has_rule_id = "- rule_id:" in lowered
    has_false_positive = "- why_false_positive:" in lowered
    has_desired_outcome = "- desired_outcome:" in lowered
    has_analyst_notes = "- analyst_notes:" in lowered

    # Treat as offense template if rule_id is present and at least
    # one of the key analyst context fields is also present
    return has_rule_id and (
        has_false_positive or has_desired_outcome or has_analyst_notes
    )