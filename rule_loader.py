import json
from pathlib import Path


RULE_LOOKUP_DIRS = [
    Path("data/rules/current"),
    Path("data/building_blocks/current"),
    Path("data/rules"),
    Path("data/building_blocks"),
]


def get_rule(rule_id: str) -> dict | None:
    """
    Load a QRadar rule or building block JSON by rule_id.

    Supports both the new folder structure:
      data/rules/current/
      data/building_blocks/current/

    and the older fallback folders:
      data/rules/
      data/building_blocks/
    """
    rule_id = str(rule_id).strip()

    if not rule_id:
        return None

    for folder in RULE_LOOKUP_DIRS:
        candidate = folder / f"{rule_id}.json"

        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)

    return None