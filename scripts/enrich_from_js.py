import json
import re
from pathlib import Path
from datetime import datetime, timezone


# --------------------------
# CONFIG
# --------------------------

DOWNLOADS_DIR = Path.home() / "Downloads"

RULES_DIR = Path("data/rules/current")
BB_DIR = Path("data/building_blocks/current")


# --------------------------
# FILE DISCOVERY
# --------------------------

def find_latest_js_file(kind: str) -> Path:
    """
    Locate the latest QRadar Rule-Data rules.js export under Downloads.

    kind:
      - "Rules"
      - "BB"

    This is intentionally forgiving because exported folders may be renamed manually.
    """

    candidates = []
    kind_lower = kind.lower()

    print(f"🔍 Searching for {kind} rules.js under: {DOWNLOADS_DIR}")

    for js_file in DOWNLOADS_DIR.rglob("rules.js"):
        folder_name = js_file.parent.name
        folder_name_lower = folder_name.lower().strip()

        is_rule_data_folder = (
            "rule-data" in folder_name_lower
            or "rule_data" in folder_name_lower
            or "rule data" in folder_name_lower
        )

        if not is_rule_data_folder:
            continue

        if kind_lower == "rules":
            # Accept names like:
            # Rule-Data_Report_... - Rules
            # Rule-Data_Report_... Rules
            #
            # But avoid BB/building block folders.
            if (
                "rules" in folder_name_lower
                and "bb" not in folder_name_lower
                and "building" not in folder_name_lower
            ):
                candidates.append(js_file)

        elif kind_lower == "bb":
            # Accept names like:
            # Rule-Data_Report_... - BB
            # Rule-Data_Report_... BB
            # Rule-Data_Report_... Building Blocks
            if "bb" in folder_name_lower or "building" in folder_name_lower:
                candidates.append(js_file)

        else:
            raise ValueError(f"Unsupported kind: {kind}")

    if not candidates:
        print("")
        print("DEBUG: Available rules.js files under Downloads:")
        for js_file in DOWNLOADS_DIR.rglob("rules.js"):
            print(f" - {js_file}")
        print("")
        raise FileNotFoundError(f"No rules.js found for kind: {kind}")

    latest = max(candidates, key=lambda f: f.stat().st_mtime)

    print(f"✅ Found {kind} JS: {latest}")
    return latest


# --------------------------
# ROBUST JS LOADER
# --------------------------

def load_rules_js(path: Path):
    print(f"Loading JS file: {path}")

    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = raw.replace("\ufeff", "").strip()

    # QRadar export usually looks like:
    # const rules = {"SYSTEM-1431": {...}, ...};
    #
    # Remove JS variable prefix.
    raw = re.sub(r"^\s*const\s+\w+\s*=\s*", "", raw)

    # Remove trailing semicolon.
    raw = raw.rstrip(";").strip()

    data = json.loads(raw)

    # Expected QRadar structure: dict keyed by UUID.
    if isinstance(data, dict):
        print(f"✅ Detected dict with {len(data)} entries — converting to list")
        return list(data.values())

    if isinstance(data, list):
        print(f"✅ Detected list with {len(data)} entries")
        return data

    raise ValueError(f"Unexpected rules.js structure in {path}")


# --------------------------
# SAFE EXTRACTION HELPERS
# --------------------------

def safe_get(d, keys, default=None):
    """Safely walk nested dicts."""
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
        safe_get(rule, ["rule_data", "rule", "actions"])
        or safe_get(rule, ["rule_data", "rule", "responses"])
    )


def extract_dependencies(rule):
    raw = rule.get("dependencies")
    clean = []

    if not isinstance(raw, list):
        return clean

    for dep in raw:
        if not isinstance(dep, dict):
            continue

        dep_uuid = dep.get("uuid")
        dep_name = dep.get("name")

        # Some QRadar exports nest the dependency object under uuid.
        if isinstance(dep_uuid, dict):
            clean.append({
                "uuid": dep_uuid.get("uuid", ""),
                "name": dep_uuid.get("name", ""),
            })
        else:
            clean.append({
                "uuid": dep_uuid or "",
                "name": dep_name or "",
            })

    return clean


def extract_limiter(rule):
    return safe_get(rule, ["rule_data", "rule", "limiter"]) or rule.get("limiter")


def simplify_mitre(mitre):
    """
    Keep MITRE as-is for now.

    The raw QRadar TAC structure is sometimes useful, although noisy.
    Flattening can be added later if needed.
    """
    if not mitre:
        return None

    return mitre


def extract_mitre(rule):
    return simplify_mitre(rule.get("TAC") or rule.get("mitre"))


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        "last_enriched_utc": utc_now(),
    }


def build_lookup(js_rules):
    lookup = {}

    for rule in js_rules:
        if not isinstance(rule, dict):
            continue

        rule_id = (
            rule.get("rule_id")
            or rule.get("ruleID")
            or rule.get("id")
            or safe_get(rule, ["rule_data", "rule", "id"])
        )

        if rule_id is None:
            continue

        lookup[str(rule_id).strip()] = extract_enrichment(rule)

    return lookup


# --------------------------
# MERGE INTO EXISTING JSON FILES
# --------------------------

def enrich_folder(folder: Path, lookup: dict):
    if not folder.exists():
        print(f"⚠️ Folder does not exist, skipping: {folder}")
        return

    print(f"\nEnriching: {folder}")

    total = 0
    updated = 0
    missing = 0

    for file in folder.glob("*.json"):
        total += 1

        try:
            with open(file, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to read {file}: {e}")
            continue

        rule_id = str(obj.get("rule_id", "")).strip()

        if rule_id in lookup:
            enrichment = lookup[rule_id]

            # Only overwrite enrichment fields.
            for key, value in enrichment.items():
                obj[key] = value

            with open(file, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2, ensure_ascii=False)

            updated += 1
        else:
            missing += 1

    print(f"Processed: {total}")
    print(f"Updated:   {updated}")
    print(f"Missing:   {missing}")


# --------------------------
# MAIN
# --------------------------

def main():
    print("🔍 Locating JS files...")

    rules_js_file = find_latest_js_file("Rules")
    bb_js_file = find_latest_js_file("BB")

    rules_js = load_rules_js(rules_js_file)
    bb_js = load_rules_js(bb_js_file)

    combined_js = rules_js + bb_js

    print(f"\nLoaded {len(rules_js)} entries from Rules JS")
    print(f"Loaded {len(bb_js)} entries from BB JS")
    print(f"Combined JS entries: {len(combined_js)}")

    lookup = build_lookup(combined_js)

    print(f"Lookup built for {len(lookup)} rule/building-block IDs")

    enrich_folder(RULES_DIR, lookup)
    enrich_folder(BB_DIR, lookup)

    print("\n✅ Enrichment complete")


if __name__ == "__main__":
    main()