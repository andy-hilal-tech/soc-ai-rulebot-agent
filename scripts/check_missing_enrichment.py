import json
from pathlib import Path

missing = []

for p in Path("data/rules/current").glob("*.json"):
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception as e:
        print(f"Failed to read {p}: {e}")
        continue

    logic = obj.get("logic")
    actions = obj.get("actions")
    dependencies = obj.get("dependencies") or []

    if logic is None and actions is None and len(dependencies) == 0:
        missing.append({
            "file": p.name,
            "rule_id": obj.get("rule_id"),
            "rule_name": obj.get("rule_name"),
            "uuid": obj.get("uuid"),
            "object_type": obj.get("object_type")
        })

print("Potential missing enrichment records:")
for item in missing:
    print(item)

print("Count:", len(missing))
