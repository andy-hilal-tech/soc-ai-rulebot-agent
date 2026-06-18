from datetime import datetime, timezone
from uuid import uuid4
from config.cosmos_config import get_case_records_container


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_case_uid() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    short_id = str(uuid4())[:8].upper()
    return f"CASE-{timestamp}-{short_id}"


def build_case_record(
    offense_data: dict,
    analysis: dict,
    created_by: str = "rulebot",
) -> dict:
    case_uid = generate_case_uid()

    recommended_tuning = {}
    tuning_options = analysis.get("tuning_options", [])
    if isinstance(tuning_options, list) and tuning_options:
        first = tuning_options[0]
        if isinstance(first, dict):
            recommended_tuning = {
                "type": first.get("implement_as", ""),
                "details": first.get("reasoning", ""),
            }

    record = {
        "id": case_uid,
        "case_uid": case_uid,
        "client_id": offense_data.get("client_id", "default") or "default",
        "created_at": utc_now(),
        "created_by": created_by,
        "status": "proposed",
        "offense_id": offense_data.get("offense_id", ""),
        "rule_id": offense_data.get("rule_id", ""),
        "qid": offense_data.get("qid", ""),
        "event_name": offense_data.get("event_name", ""),
        "offense_summary": offense_data.get("payload_summary", "") or offense_data.get("event_description", ""),
        "why_false_positive": offense_data.get("why_false_positive", ""),
        "desired_outcome": offense_data.get("desired_outcome", ""),
        "analyst_notes": offense_data.get("analyst_notes", ""),
        "recommended_tuning": recommended_tuning,
        "compliance_notes": analysis.get("compliance_notes", ""),
        "validation_steps": analysis.get("validation_steps", []),
        "implementation_status": "not_implemented",
        "linked_rule_ids": [offense_data.get("rule_id", "")] if offense_data.get("rule_id") else [],
        "linked_case_uids": [],
        "rollback_notes": "",
        "change_ticket": "",
        "last_updated_at": utc_now(),
    }

    return record


def save_case_record(record: dict) -> dict:
    container = get_case_records_container()
    return container.upsert_item(record)