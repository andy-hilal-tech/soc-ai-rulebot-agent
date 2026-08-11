"""
sync_qradar_rule_metadata.py

Fetch QRadar rule and building block metadata from the API, scan local
enriched/exported JSON files, compare API-visible objects against local
export coverage, and write coverage reports.

Output directory: data/qradar_rule_metadata/

Output files:
  - qradar_rules_api_v19_0.json              Rules API cache
  - qradar_building_blocks_api_v19_0.json    Building blocks API cache
  - exported_rule_index.json                  Local file index
  - rule_coverage_report.json                 Full comparison report
  - missing_exported_rules.csv                Analyst-friendly CSV
  - missing_exported_rules.md                 Human-readable summary

Usage:
  python scripts/sync_qradar_rule_metadata.py
  python scripts/sync_qradar_rule_metadata.py --skip-api
  python scripts/sync_qradar_rule_metadata.py --api-version 19.0 --base-url https://192.168.51.122
  python scripts/sync_qradar_rule_metadata.py --sample-rule-id 100067
  python scripts/sync_qradar_rule_metadata.py --sample-building-block-id 100002
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RULES_DIR = PROJECT_ROOT / "data" / "rules" / "current"
BUILDING_BLOCKS_DIR = PROJECT_ROOT / "data" / "building_blocks" / "current"

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "qradar_rule_metadata"

# ---------------------------------------------------------------------------
# QRadar API helpers
# ---------------------------------------------------------------------------

API_FIELDS = (
    "id,name,type,enabled,owner,origin,identifier,"
    "linked_rule_identifier,creation_date,modification_date,"
    "base_capacity,average_capacity,capacity_timestamp"
)

DEFAULT_RANGE_MAX = 9999


def resolve_qradar_token() -> str:
    """Resolve QRadar API token from environment variables."""
    candidates = [
        "QRADAR_BH_SEC_TOKEN",
        "QRADAR_TOKEN",
        "QRADAR_TOKEN_BH",
        "QRADAR_SEC_TOKEN",
        "QRADAR_API_TOKEN",
    ]
    for name in candidates:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError(
        "No QRadar token found. Expected one of: " + ", ".join(candidates)
    )


def fetch_collection(
    base_url: str,
    token: str,
    endpoint: str,
    fields: str,
    api_version: str = "19.0",
    verify: bool = False,
    timeout: int = 60,
) -> list[dict]:
    """
    Fetch a collection from a QRadar API endpoint using a single large Range request.

    Sends Range: items=0-{DEFAULT_RANGE_MAX} and returns the parsed JSON list.
    Prints endpoint, HTTP status, Content-Range header, and returned count.
    """
    import requests

    url = f"{base_url.rstrip('/')}{endpoint}"
    headers = {
        "SEC": token,
        "Version": api_version,
        "Accept": "application/json",
        "Range": f"items=0-{DEFAULT_RANGE_MAX}",
    }
    params = {"fields": fields}

    print(f"  GET {endpoint}")
    print(f"    Range: items=0-{DEFAULT_RANGE_MAX}")

    try:
        resp = requests.get(url, headers=headers, params=params, verify=verify, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        print(f"    [ERROR] Request failed: {exc}")
        return []

    content_range = resp.headers.get("Content-Range", "none")
    print(f"    Status: {resp.status_code}")
    print(f"    Content-Range: {content_range}")

    if resp.status_code not in (200, 206):
        print(f"    [ERROR] Unexpected status {resp.status_code}: {resp.text[:300]}")
        return []

    try:
        data = resp.json()
    except Exception as exc:
        print(f"    [ERROR] Failed to parse JSON: {exc}")
        return []

    if not isinstance(data, list):
        print(f"    [WARN] Response is not a list (type={type(data).__name__}), wrapping")
        data = [data]

    print(f"    Returned {len(data)} objects")
    return data


def fetch_rule_dependents(
    base_url: str,
    token: str,
    rule_id: int,
    api_version: str = "19.0",
    verify: bool = False,
    timeout: int = 30,
) -> list[dict]:
    """Fetch dependents for a single rule via /api/analytics/rules/{id}/dependents."""
    import requests

    headers = {
        "SEC": token,
        "Version": api_version,
        "Accept": "application/json",
    }

    url = f"{base_url.rstrip('/')}/api/analytics/rules/{rule_id}/dependents"

    try:
        resp = requests.get(url, headers=headers, verify=verify, timeout=timeout)
        if resp.status_code in (200, 206):
            data = resp.json()
            return data if isinstance(data, list) else [data]
    except requests.exceptions.RequestException as exc:
        print(f"  [WARN] Failed to fetch dependents for rule {rule_id}: {exc}")

    return []


# ---------------------------------------------------------------------------
# Local export scanning
# ---------------------------------------------------------------------------


def scan_exported_rules(rules_dir: Path, object_type: str) -> list[dict]:
    """Scan a directory of exported rule/building-block JSON files."""
    records: list[dict] = []

    if not rules_dir.exists():
        print(f"  [WARN] Directory not found: {rules_dir}")
        return records

    for file_path in sorted(rules_dir.glob("*.json")):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception as exc:
            print(f"  [WARN] Skipping unreadable {file_path.name}: {exc}")
            continue

        record = {
            "rule_doc_id": str(obj.get("rule_doc_id") or obj.get("rule_id") or ""),
            "rule_id": str(obj.get("rule_id") or obj.get("rule_doc_id") or ""),
            "uuid": str(obj.get("uuid") or ""),
            "rule_name": str(obj.get("rule_name") or ""),
            "object_type": str(obj.get("object_type") or object_type),
            "origin": str(obj.get("origin") or ""),
            "enabled": bool(obj.get("enabled", False)),
            "file_path": str(file_path.relative_to(PROJECT_ROOT)),
        }

        # Capture linked_rule_identifier if present in the export
        linked = obj.get("linked_rule_identifier")
        if linked:
            record["linked_rule_identifier"] = str(linked)

        records.append(record)

    return records


def build_exported_index(
    rules: list[dict], building_blocks: list[dict]
) -> dict:
    """Build a lookup index from exported records keyed by uuid and name."""
    all_records = rules + building_blocks

    by_uuid: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    by_normalized_name: dict[str, list[dict]] = {}

    for rec in all_records:
        uid = rec.get("uuid", "").strip()
        if uid:
            by_uuid[uid] = rec

        name = rec.get("rule_name", "").strip()
        if name:
            by_name[name] = rec

            norm = _normalize_name(name)
            if norm:
                by_normalized_name.setdefault(norm, []).append(rec)

    return {
        "built_at_utc": _utc_now(),
        "total_rules": len(rules),
        "total_building_blocks": len(building_blocks),
        "by_uuid": by_uuid,
        "by_name": by_name,
        "by_normalized_name": by_normalized_name,
    }


def _normalize_name(name: str) -> str:
    """Lowercase, strip whitespace, collapse internal whitespace."""
    import re

    return re.sub(r"\s+", " ", name.lower().strip())


# ---------------------------------------------------------------------------
# Comparison engine
# ---------------------------------------------------------------------------


def compare_coverage(
    api_objects: list[dict],
    exported_index: dict,
    *,
    object_type_label: str = "rule",
) -> dict:
    """
    Compare API objects (rules or building blocks) against the exported index.

    Parameters
    ----------
    api_objects : list[dict]
        Objects fetched from the QRadar API.
    exported_index : dict
        Index built from local export files (by_uuid, by_name, by_normalized_name).
    object_type_label : str
        "rule" or "building_block" — used for reporting.

    Returns a dict with matched, missing, and unmatched records plus totals.
    """
    by_uuid = exported_index.get("by_uuid", {})
    by_name = exported_index.get("by_name", {})
    by_normalized_name = exported_index.get("by_normalized_name", {})

    matched: list[dict] = []
    missing: list[dict] = []
    matched_local_uuids: set[str] = set()

    for api_obj in api_objects:
        api_id = api_obj.get("id")
        api_name = (api_obj.get("name") or "").strip()
        identifier = (api_obj.get("identifier") or "").strip()
        linked_id = (api_obj.get("linked_rule_identifier") or "").strip()

        match_status = "missing_from_export"
        context_level = "unknown"
        matched_local: dict | None = None
        notes = ""

        # 1. Try linked_rule_identifier match
        if not matched_local and linked_id and linked_id in by_uuid:
            matched_local = by_uuid[linked_id]
            match_status = "matched_by_linked_rule_identifier"
            context_level = "full_exported_logic"

        # 2. Try identifier match
        if not matched_local and identifier and identifier in by_uuid:
            matched_local = by_uuid[identifier]
            match_status = "matched_by_identifier"
            context_level = "full_exported_logic"

        # 3. Try exact name match
        if not matched_local and api_name and api_name in by_name:
            matched_local = by_name[api_name]
            match_status = "matched_by_exact_name"
            context_level = "full_exported_logic"

        # 4. Try normalized name match (weak)
        if not matched_local and api_name:
            norm = _normalize_name(api_name)
            candidates = by_normalized_name.get(norm, [])
            if len(candidates) == 1:
                matched_local = candidates[0]
                match_status = "matched_by_normalized_name"
                context_level = "full_exported_logic"
                notes = "Weak match via normalized name — verify manually"
            elif len(candidates) > 1:
                notes = (
                    f"Normalized name '{norm}' matched {len(candidates)} "
                    f"local records — cannot disambiguate"
                )

        record = {
            "qradar_object_id": api_id,
            "qradar_object_name": api_name,
            "type": api_obj.get("type", ""),
            "origin": api_obj.get("origin", ""),
            "enabled": bool(api_obj.get("enabled", False)),
            "identifier": identifier,
            "linked_rule_identifier": linked_id,
            "average_capacity": api_obj.get("average_capacity"),
            "base_capacity": api_obj.get("base_capacity"),
            "object_type_label": object_type_label,
            "match_status": match_status,
            "context_coverage_level": context_level,
            "notes": notes,
        }

        if matched_local:
            record["local_rule_doc_id"] = matched_local.get("rule_doc_id", "")
            record["local_rule_name"] = matched_local.get("rule_name", "")
            record["local_object_type"] = matched_local.get("object_type", "")
            record["local_file_path"] = matched_local.get("file_path", "")
            matched.append(record)

            local_uuid = matched_local.get("uuid", "").strip()
            if local_uuid:
                matched_local_uuids.add(local_uuid)
        else:
            missing.append(record)

    # Orphaned exports: local records whose UUID doesn't appear in any API object
    local_unmatched: list[dict] = []
    all_api_identifiers: set[str] = set()
    all_api_linked: set[str] = set()

    for api_obj in api_objects:
        id_val = (api_obj.get("identifier") or "").strip()
        if id_val:
            all_api_identifiers.add(id_val)
        linked_val = (api_obj.get("linked_rule_identifier") or "").strip()
        if linked_val:
            all_api_linked.add(linked_val)

    for uid, rec in by_uuid.items():
        if uid not in matched_local_uuids and uid not in all_api_identifiers and uid not in all_api_linked:
            local_unmatched.append(rec)

    # Summary
    total_api = len(api_objects)
    total_matched = len(matched)
    total_missing = len(missing)

    missing_system = [r for r in missing if r.get("origin") == "SYSTEM"]
    missing_enabled = [r for r in missing if r.get("enabled")]

    return {
        "object_type_label": object_type_label,
        "generated_at_utc": _utc_now(),
        "totals": {
            "api_total": total_api,
            "exported_total": exported_index.get("total_rules" if object_type_label == "rule" else "total_building_blocks", 0),
            "matched": total_matched,
            "missing": total_missing,
            "missing_system": len(missing_system),
            "missing_enabled": len(missing_enabled),
            "local_unmatched": len(local_unmatched),
        },
        "matched": matched,
        "missing": missing,
        "local_unmatched": local_unmatched,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  [OK] Wrote {path}")


def save_api_cache(
    objects: list[dict],
    output_path: Path,
    api_version: str,
    *,
    endpoint: str = "",
    content_range: str = "",
):
    cache = {
        "api_version": api_version,
        "endpoint": endpoint,
        "fetched_at_utc": _utc_now(),
        "content_range": content_range,
        "total_count": len(objects),
        "objects": objects,
    }
    save_json(cache, output_path)


def save_exported_index(index: dict, output_path: Path):
    # Strip lookup dicts for serialization — store as serializable structure
    serializable = {
        "built_at_utc": index["built_at_utc"],
        "total_rules": index["total_rules"],
        "total_building_blocks": index["total_building_blocks"],
        "by_uuid": {
            k: {
                "rule_doc_id": v.get("rule_doc_id", ""),
                "rule_id": v.get("rule_id", ""),
                "rule_name": v.get("rule_name", ""),
                "object_type": v.get("object_type", ""),
                "file_path": v.get("file_path", ""),
            }
            for k, v in index["by_uuid"].items()
        },
        "by_name": {
            k: {
                "rule_doc_id": v.get("rule_doc_id", ""),
                "uuid": v.get("uuid", ""),
            }
            for k, v in index["by_name"].items()
        },
    }
    save_json(serializable, output_path)


def save_coverage_report(report: dict, output_path: Path):
    save_json(report, output_path)


def save_missing_csv(missing_list: list[dict], output_path: Path):
    fieldnames = [
        "qradar_object_id",
        "qradar_object_name",
        "type",
        "origin",
        "enabled",
        "identifier",
        "linked_rule_identifier",
        "average_capacity",
        "base_capacity",
        "object_type_label",
        "match_status",
        "context_coverage_level",
        "notes",
    ]

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in missing_list:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"  [OK] Wrote {path}")


def save_missing_md(
    rule_report: dict | None,
    bb_report: dict | None,
    output_path: Path,
):
    """Write a human-readable Markdown summary of missing rules and building blocks."""
    lines = [
        "# Missing Exported Rules Report",
        "",
        f"Generated at: {_utc_now()}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]

    r_totals = rule_report["totals"] if rule_report else {}
    b_totals = bb_report["totals"] if bb_report else {}

    lines.append(f"| Total API rules | {r_totals.get('api_total', 'N/A')} |")
    lines.append(f"| Total API building blocks | {b_totals.get('api_total', 'N/A')} |")
    lines.append(f"| Total API objects | {r_totals.get('api_total', 0) + b_totals.get('api_total', 0)} |")
    lines.append(f"| Exported rules | {r_totals.get('exported_total', 'N/A')} |")
    lines.append(f"| Exported building blocks | {b_totals.get('exported_total', 'N/A')} |")
    lines.append(f"| Matched rules | {r_totals.get('matched', 'N/A')} |")
    lines.append(f"| Matched building blocks | {b_totals.get('matched', 'N/A')} |")
    lines.append(f"| Missing rules | {r_totals.get('missing', 'N/A')} |")
    lines.append(f"| Missing building blocks | {b_totals.get('missing', 'N/A')} |")
    lines.append(f"| Missing SYSTEM rules | {r_totals.get('missing_system', 'N/A')} |")
    lines.append(f"| Missing enabled rules | {r_totals.get('missing_enabled', 'N/A')} |")
    lines.append("")

    lines.extend([
        "## Why This Matters for Rulebot",
        "",
        "Rulebot relies on exported/enriched rule JSON files to provide condition-level",
        "tuning guidance. When a QRadar rule is visible in the API but has no matching",
        "exported JSON file, Rulebot can only provide metadata-level context (name,",
        "identifier, origin, type) rather than full condition-level tuning recommendations.",
        "",
        "Closing these gaps improves Rulebot's ability to generate accurate, actionable",
        "QRadar Rule Tuning Implementation Guides for every rule that fires in the SOC.",
        "",
    ])

    # --- Missing rules section ---
    if rule_report:
        missing_rules = rule_report.get("missing", [])
        missing_system = [r for r in missing_rules if r.get("origin") == "SYSTEM"]
        missing_enabled = [r for r in missing_rules if r.get("enabled")]

        top_by_capacity = sorted(
            [r for r in missing_rules if r.get("average_capacity") is not None],
            key=lambda r: float(r["average_capacity"]),
            reverse=True,
        )[:10]

        if missing_system:
            lines.extend([
                "## Missing SYSTEM Rules",
                "",
                f"**{len(missing_system)}** SYSTEM-origin rules are missing from the export set.",
                "These are typically built-in QRadar rules that were not included in the",
                "Use Case Manager export or the enrich-from-JS pipeline.",
                "",
            ])

        if missing_enabled:
            lines.extend([
                "## Missing Enabled Rules",
                "",
                f"**{len(missing_enabled)}** enabled rules are missing from the export set.",
                "Enabled rules that are not exported represent the highest-priority coverage gaps",
                "because they are actively generating offenses that Rulebot cannot fully analyze.",
                "",
            ])

        if top_by_capacity:
            lines.extend([
                "## Top Missing Rules by Average Capacity",
                "",
                "| Object ID | Name | Avg Capacity | Origin | Enabled |",
                "|-----------|------|-------------|--------|---------|",
            ])
            for r in top_by_capacity:
                lines.append(
                    f"| {r.get('qradar_object_id', '')} "
                    f"| {r.get('qradar_object_name', '')} "
                    f"| {r.get('average_capacity', '')} "
                    f"| {r.get('origin', '')} "
                    f"| {r.get('enabled', '')} |"
                )
            lines.append("")

        if missing_rules:
            lines.extend([
                "## All Missing Rules",
                "",
                "| Object ID | Name | Type | Origin | Enabled | Match Status |",
                "|-----------|------|------|--------|---------|-------------|",
            ])
            for r in missing_rules:
                lines.append(
                    f"| {r.get('qradar_object_id', '')} "
                    f"| {r.get('qradar_object_name', '')} "
                    f"| {r.get('type', '')} "
                    f"| {r.get('origin', '')} "
                    f"| {r.get('enabled', '')} "
                    f"| {r.get('match_status', '')} |"
                )
            lines.append("")

    # --- Missing building blocks section ---
    if bb_report:
        missing_bbs = bb_report.get("missing", [])
        if missing_bbs:
            lines.extend([
                "## Missing Building Blocks",
                "",
                "| Object ID | Name | Type | Origin | Enabled | Match Status |",
                "|-----------|------|------|--------|---------|-------------|",
            ])
            for r in missing_bbs:
                lines.append(
                    f"| {r.get('qradar_object_id', '')} "
                    f"| {r.get('qradar_object_name', '')} "
                    f"| {r.get('type', '')} "
                    f"| {r.get('origin', '')} "
                    f"| {r.get('enabled', '')} "
                    f"| {r.get('match_status', '')} |"
                )
            lines.append("")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [OK] Wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync QRadar rule metadata and compare export coverage."
    )
    parser.add_argument(
        "--api-version",
        default=os.getenv("QRADAR_API_VERSION", "19.0"),
        help="QRadar API version (default: 19.0, env: QRADAR_API_VERSION)",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("QRADAR_BASE_URL", "https://192.168.51.122"),
        help="QRadar console base URL (default: env QRADAR_BASE_URL or https://192.168.51.122)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Skip API fetch; use cached API data if available",
    )
    parser.add_argument(
        "--sample-rule-id",
        type=int,
        default=None,
        help="Fetch metadata for a single rule ID for testing (sample_mode=true)",
    )
    parser.add_argument(
        "--sample-building-block-id",
        type=int,
        default=None,
        help="Fetch metadata for a single building block ID for testing (sample_mode=true)",
    )
    parser.add_argument(
        "--include-dependents",
        action="store_true",
        help="Fetch dependents for missing rules or --sample-rule-id",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    api_version = args.api_version
    base_url = args.base_url

    sample_mode = (args.sample_rule_id is not None) or (args.sample_building_block_id is not None)

    # ------------------------------------------------------------------
    # Phase 1: Fetch API metadata (or load cached)
    # ------------------------------------------------------------------
    api_rules: list[dict] = []
    api_building_blocks: list[dict] = []

    rules_cache_path = output_dir / f"qradar_rules_api_v{api_version.replace('.', '_')}.json"
    bbs_cache_path = output_dir / f"qradar_building_blocks_api_v{api_version.replace('.', '_')}.json"

    if args.skip_api:
        # Load rules cache
        if rules_cache_path.exists():
            print(f"[LOAD] Loading cached rules from {rules_cache_path}")
            with open(rules_cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            api_rules = cached.get("objects", [])
            print(f"  Loaded {len(api_rules)} rules from cache")
        else:
            print(f"[WARN] --skip-api set but no rules cache at {rules_cache_path}")

        # Load building blocks cache
        if bbs_cache_path.exists():
            print(f"[LOAD] Loading cached building blocks from {bbs_cache_path}")
            with open(bbs_cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            api_building_blocks = cached.get("objects", [])
            print(f"  Loaded {len(api_building_blocks)} building blocks from cache")
        else:
            print(f"[WARN] --skip-api set but no building blocks cache at {bbs_cache_path}")

        if not api_rules and not api_building_blocks:
            print("  Running local-only mode (export indexing only, no comparison)")
    else:
        token = resolve_qradar_token()

        # --- Fetch rules ---
        print(f"\n[API] Fetching rules from {base_url} (API v{api_version})")
        api_rules = fetch_collection(
            base_url=base_url,
            token=token,
            endpoint="/api/analytics/rules",
            fields=API_FIELDS,
            api_version=api_version,
        )
        print(f"  Total rules fetched: {len(api_rules)}")

        # --- Fetch building blocks ---
        print(f"\n[API] Fetching building blocks from {base_url} (API v{api_version})")
        api_building_blocks = fetch_collection(
            base_url=base_url,
            token=token,
            endpoint="/api/analytics/building_blocks",
            fields=API_FIELDS,
            api_version=api_version,
        )
        print(f"  Total building blocks fetched: {len(api_building_blocks)}")

        # Save API caches
        save_api_cache(
            api_rules, rules_cache_path, api_version,
            endpoint="/api/analytics/rules",
        )
        save_api_cache(
            api_building_blocks, bbs_cache_path, api_version,
            endpoint="/api/analytics/building_blocks",
        )

        # --- Sample mode: filter rules ---
        if args.sample_rule_id is not None:
            sample = [r for r in api_rules if r.get("id") == args.sample_rule_id]
            if sample:
                print(f"\n[SAMPLE] Rule {args.sample_rule_id}:")
                print(json.dumps(sample[0], indent=2, default=str))
                api_rules = sample
            else:
                print(f"\n[SAMPLE] Rule {args.sample_rule_id} not found in API response")
                api_rules = []

        # --- Sample mode: filter building blocks ---
        if args.sample_building_block_id is not None:
            sample = [r for r in api_building_blocks if r.get("id") == args.sample_building_block_id]
            if sample:
                print(f"\n[SAMPLE] Building block {args.sample_building_block_id}:")
                print(json.dumps(sample[0], indent=2, default=str))
                api_building_blocks = sample
            else:
                print(f"\n[SAMPLE] Building block {args.sample_building_block_id} not found in API response")
                api_building_blocks = []

        # --- Dependents (optional, rules only) ---
        if args.include_dependents:
            target_ids: list[int] = []
            if args.sample_rule_id is not None:
                target_ids.append(args.sample_rule_id)
            elif api_rules:
                # Build index and compare to find missing rules
                exported_rules = scan_exported_rules(RULES_DIR, "rule")
                exported_bbs = scan_exported_rules(BUILDING_BLOCKS_DIR, "building_block")
                exported_index = build_exported_index(exported_rules, exported_bbs)
                rpt = compare_coverage(api_rules, exported_index, object_type_label="rule")
                target_ids = [
                    r["qradar_object_id"]
                    for r in rpt["missing"]
                    if r["qradar_object_id"] is not None
                ][:10]

            if target_ids:
                print(f"\n[DEPENDENTS] Fetching dependents for {len(target_ids)} rules...")
                dependents_path = output_dir / "rule_dependents.json"
                all_deps: dict[str, list[dict]] = {}
                for rid in target_ids:
                    deps = fetch_rule_dependents(
                        base_url=base_url,
                        token=token,
                        rule_id=rid,
                        api_version=api_version,
                    )
                    all_deps[str(rid)] = deps
                    print(f"  Rule {rid}: {len(deps)} dependents")
                save_json(all_deps, dependents_path)

    # ------------------------------------------------------------------
    # Phase 2: Scan local exports
    # ------------------------------------------------------------------
    print(f"\n[SCAN] Scanning local exported rules...")
    exported_rules = scan_exported_rules(RULES_DIR, "rule")
    exported_bbs = scan_exported_rules(BUILDING_BLOCKS_DIR, "building_block")
    print(f"  Found {len(exported_rules)} rules, {len(exported_bbs)} building blocks")

    exported_index = build_exported_index(exported_rules, exported_bbs)
    save_exported_index(exported_index, output_dir / "exported_rule_index.json")

    # ------------------------------------------------------------------
    # Phase 3: Compare coverage
    # ------------------------------------------------------------------
    rule_report: dict | None = None
    bb_report: dict | None = None

    if api_rules:
        print(f"\n[COMPARE] Comparing {len(api_rules)} API rules against local rule exports...")
        rule_report = compare_coverage(api_rules, exported_index, object_type_label="rule")
        rule_report["api_version"] = api_version
        rule_report["sample_mode"] = sample_mode and (args.sample_rule_id is not None)
    else:
        print(f"\n[SKIP] No API rules loaded — skipping rule coverage comparison")

    if api_building_blocks:
        print(f"\n[COMPARE] Comparing {len(api_building_blocks)} API building blocks against local BB exports...")
        bb_report = compare_coverage(api_building_blocks, exported_index, object_type_label="building_block")
        bb_report["api_version"] = api_version
        bb_report["sample_mode"] = sample_mode and (args.sample_building_block_id is not None)
    else:
        print(f"\n[SKIP] No API building blocks loaded — skipping BB coverage comparison")

    # Build combined report
    r_totals = rule_report["totals"] if rule_report else {}
    b_totals = bb_report["totals"] if bb_report else {}

    combined_report = {
        "api_version": api_version,
        "sample_mode": sample_mode,
        "generated_at_utc": _utc_now(),
        "totals": {
            "api_total_rules": r_totals.get("api_total", 0),
            "api_total_building_blocks": b_totals.get("api_total", 0),
            "api_total_objects": r_totals.get("api_total", 0) + b_totals.get("api_total", 0),
            "exported_total_rules": r_totals.get("exported_total", len(exported_rules)),
            "exported_total_building_blocks": b_totals.get("exported_total", len(exported_bbs)),
            "exported_total_objects": r_totals.get("exported_total", len(exported_rules)) + b_totals.get("exported_total", len(exported_bbs)),
            "matched_rules": r_totals.get("matched", 0),
            "matched_building_blocks": b_totals.get("matched", 0),
            "missing_rules": r_totals.get("missing", 0),
            "missing_building_blocks": b_totals.get("missing", 0),
            "missing_system_rules": r_totals.get("missing_system", 0),
            "missing_enabled_rules": r_totals.get("missing_enabled", 0),
            "local_unmatched_rule_exports": r_totals.get("local_unmatched", 0),
            "local_unmatched_building_block_exports": b_totals.get("local_unmatched", 0),
        },
        "rule_report": rule_report,
        "building_block_report": bb_report,
    }

    save_coverage_report(combined_report, output_dir / "rule_coverage_report.json")

    # Combined missing list for CSV
    all_missing: list[dict] = []
    if rule_report:
        all_missing.extend(rule_report.get("missing", []))
    if bb_report:
        all_missing.extend(bb_report.get("missing", []))
    save_missing_csv(all_missing, output_dir / "missing_exported_rules.csv")

    # Markdown report
    save_missing_md(rule_report, bb_report, output_dir / "missing_exported_rules.md")

    # ------------------------------------------------------------------
    # Debug summary
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("  DEBUG SUMMARY")
    print(f"{'='*60}")
    print(f"  API rules fetched:              {r_totals.get('api_total', 0)}")
    print(f"  API building blocks fetched:    {b_totals.get('api_total', 0)}")
    print(f"  Local rule exports indexed:     {r_totals.get('exported_total', len(exported_rules))}")
    print(f"  Local BB exports indexed:       {b_totals.get('exported_total', len(exported_bbs))}")
    print(f"  Matched rules:                  {r_totals.get('matched', 0)}")
    print(f"  Matched building blocks:        {b_totals.get('matched', 0)}")
    print(f"  Missing rules:                  {r_totals.get('missing', 0)}")
    print(f"  Missing building blocks:        {b_totals.get('missing', 0)}")
    print(f"{'='*60}")

    print(f"\n[DONE] All outputs written to {output_dir}/")


if __name__ == "__main__":
    main()