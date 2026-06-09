import json
import os

BASE_DIR = os.path.dirname(__file__)
RULES_PATH = os.path.join(BASE_DIR, "data", "rules")

rules = {}

for file in os.listdir(RULES_PATH):
    if file.endswith(".json"):
        with open(os.path.join(RULES_PATH, file), encoding="utf-8") as f:
            r = json.load(f)
            if r.get("id"):
                rules[str(r["id"])] = r


def get_rule(rule_id):
    return rules.get(str(rule_id))
