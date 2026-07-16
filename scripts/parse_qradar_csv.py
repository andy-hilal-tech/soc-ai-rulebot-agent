import os
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

# --------------------------
# CONFIG
# --------------------------

DOWNLOADS_DIR = Path.home() / "Downloads"

RULES_OUTPUT = Path("data/rules/current")
BB_OUTPUT = Path("data/building_blocks/current")

RULES_PATTERN = "Use-Case-Manager-Rules-Report"
BB_PATTERN = "Use-Case-Manager-Building-Blocks-Report"

# --------------------------
# HELPERS
# --------------------------

def find_latest_csv(pattern: str):
    files = list(DOWNLOADS_DIR.glob("*.csv"))

    print(f"Looking for CSV pattern: {pattern}")
    print(f"Downloads directory: {DOWNLOADS_DIR}")

    def normalize_name(value: str) -> str:
        return (
            value.lower()
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
        )


    normalized_pattern = normalize_name(pattern)

    matches = [
        file_path
        for file_path in files
        if normalized_pattern in normalize_name(file_path.name)
    ]

    if not matches:
        print("CSV files found in Downloads:")
        for file_path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
            print(f" - {file_path.name}")

        raise FileNotFoundError(f"No CSV found for pattern: {pattern}")

    latest = max(matches, key=lambda p: p.stat().st_mtime)

    print(f"Selected CSV: {latest}")

    return latest


def clean_value(val):
    if pd.isna(val):
        return ""
    if isinstance(val, str):
        return val.strip()
    return val


def build_rule_object(row, object_type):
    return {
        "rule_doc_id": str(clean_value(row.get("Rule ID"))),
        "rule_id": str(clean_value(row.get("Rule ID"))),
        "uuid": clean_value(row.get("uuid")),
        "rule_name": clean_value(row.get("Rule name")),
        "object_type": object_type,

        "group": clean_value(row.get("Group")),
        "rule_category": clean_value(row.get("Rule category")),
        "type": clean_value(row.get("Type")),
        "origin": clean_value(row.get("Origin")),
        "enabled": clean_value(row.get("Rule enabled")) == "true",

        "response": clean_value(row.get("Response")),
        "created": clean_value(row.get("Creation date")),
        "modified": clean_value(row.get("Modification date")),

        # placeholder for enrichment later
        "logic": None,
        "actions": None,
        "dependencies": [],
        "limiter": None,
        "mitre": None,

        "last_parsed_utc": datetime.utcnow().isoformat()
    }


def write_json(output_dir: Path, obj: dict):
    output_dir.mkdir(parents=True, exist_ok=True)

    rule_id = obj["rule_doc_id"]
    filename = output_dir / f"{rule_id}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def parse_csv(csv_path, output_dir, object_type):
    print(f"Processing: {csv_path.name}")

    df = pd.read_csv(csv_path)

    count = 0
    for _, row in df.iterrows():
        obj = build_rule_object(row, object_type)
        write_json(output_dir, obj)
        count += 1

    print(f"✅ {count} objects written to {output_dir}")


# --------------------------
# MAIN
# --------------------------

def main():
    print("🔍 Locating latest CSV exports...")

    rules_csv = find_latest_csv(RULES_PATTERN)
    bb_csv = find_latest_csv(BB_PATTERN)

    print(f"Rules CSV: {rules_csv}")
    print(f"BB CSV: {bb_csv}")

    print("\n📦 Parsing rules...")
    parse_csv(rules_csv, RULES_OUTPUT, "rule")

    print("\n📦 Parsing building blocks...")
    parse_csv(bb_csv, BB_OUTPUT, "building_block")

    print("\n✅ CSV parsing complete.")


if __name__ == "__main__":
    main()