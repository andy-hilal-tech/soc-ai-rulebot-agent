import json
import re
from pathlib import Path
from datetime import datetime

# --------------------------
# CONFIG
# --------------------------

DOWNLOADS_DIR = Path.home() / "Downloads"


def find_latest_js_folder(suffix):
    folders = list(DOWNLOADS_DIR.glob(f"Rule-Data_Report*{suffix}"))

    if not folders:
        raise FileNotFoundError(f"No folder found with suffix: {suffix}")

    latest = max(folders, key=lambda f: f.stat().st_mtime)
    return latest / "rules.js"


RULES_JS_FILE = find_latest_js_folder(" - Rules")
BB_JS_FILE = find_latest_js_folder(" - BB")

RULES_DIR = Path("data/rules/current")
BB_DIR = Path("data/building_blocks/current")

# --------------------------
# ROBUST JS LOADER (parser.py-style)
# --------------------------

def load_rules_js(path: Path):
    print(f"Loading JS file: {path}")

    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = raw.replace("\ufeff", "")

    # Remove "const rules =" prefix safely
    raw = re.sub(r"^\s*const\s+\w+\s*=\s*", "", raw)

    # Remove trailing semicolon if present
    raw = raw.strip().rstrip(";")

    # Parse JSON object
    data = json.loads(raw)

    # ✅ CRITICAL FIX — convert dict → list
    if isinstance(data, dict):
        print(f"✅ Detected dict with {len(data)} entries — converting to list")
        return list(data.values())

    if isinstance(data, list):
        return data

    raise ValueError("Unexpected rules.js structure")


# --------------------------
# SAFE EXTRACTION HELPERS
# --------------------------

def safe_get(d, keys, default=None):
    """Safely walk nested dicts"""
    val = d
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val


def extract_logic(rule):
    return safe_get(rule, ["rule_data", "rule", "testDefinitions"])


def extract_actions(rule):
    return (
        safe_get(rule, ["rule_data", "rule", "actions"]) or
        safe_get(rule, ["rule_data", "rule", "responses"])
    )


def extract_dependencies(rule):
    raw = rule.get("dependencies")
    clean = []

    if isinstance(raw, list):
        for d in raw:
            if isinstance(d.get("uuid"), dict):
                clean.append({
                    "uuid": d["uuid"].get("uuid"),
                    "name": d["uuid"].get("name")
                })
            else:
                clean.append({
                    "uuid": d.get("uuid"),
                    "name": d.get("name")
                })

    return clean


def extract_limiter(rule):
    return rule.get("limiter")


def simplify_mitre(mitre):
    if not mitre:
        return None

    tactics = []

    for key, value in mitre.items():
        for layer in value:
            for entry in layer:
                tactic = entry.get("TAC")
                if tactic and tactic not in tactics:
                    tactics.append(tactic)

    return {"tactics": tactics}


def extract_mitre(rule):
    return rule.get("TAC") or rule.get("mitre")

# --------------------------
# ENRICHMENT BUILDER
# --------------------------

def extract_enrichment(rule):
    return {
        "logic": extract_logic(rule),
        "actions": extract_actions(rule),
        "dependencies": extract_dependencies(rule),
        "limiter": extract_limiter(rule),
        "mitre": extract_mitre(rule),
        "last_enriched_utc": datetime.utcnow().isoformat()
    }


def build_lookup(js_rules):
    lookup = {}

    for rule in js_rules:

        rule_id = (
            rule.get("rule_id")
            or rule.get("ruleID")
            or rule.get("id")   # ⭐ THIS is the real field in your data
        )

        if rule_id is None:
            continue

        lookup[str(rule_id)] = extract_enrichment(rule)

    return lookup

# --------------------------
# MERGE INTO EXISTING JSON FILES
# --------------------------

def enrich_folder(folder: Path, lookup: dict):
    if not folder.exists():
        return

    print(f"\nEnriching: {folder}")

    total = 0
    updated = 0

    for file in folder.glob("*.json"):
        total += 1

        try:
            with open(file, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue

        rule_id = str(obj.get("rule_id"))

        if rule_id in lookup:
            enrichment = lookup[rule_id]

            # only overwrite enrichment fields, don't destroy base structure
            for k, v in enrichment.items():
                obj[k] = v

            updated += 1

            with open(file, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2, ensure_ascii=False)

    print(f"Processed: {total}")
    print(f"Updated:   {updated}")

# --------------------------
# MAIN
# --------------------------

def main():
    print("🔍 Locating JS files...")

    rules_js = load_rules_js(RULES_JS_FILE)
    bb_js = load_rules_js(BB_JS_FILE)

    print(f"Rules JS: {RULES_JS_FILE}")
    print(f"BB JS: {BB_JS_FILE}")

    combined_js = rules_js + bb_js

    print(f"Loaded {len(combined_js)} entries from rules.js")

    lookup = build_lookup(combined_js)
    print(f"Lookup built for {len(lookup)} rules")

    enrich_folder(RULES_DIR, lookup)
    enrich_folder(BB_DIR, lookup)

    print("\n✅ Enrichment complete")

if __name__ == "__main__":
    main()