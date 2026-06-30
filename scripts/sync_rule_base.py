import sys
from pathlib import Path

# Ensure repo root is importable when running as python scripts/sync_rule_base.py
sys.path.append(str(Path(__file__).resolve().parent.parent))

import json
import hashlib
import re
import html
from datetime import datetime, timezone

from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from openai import AzureOpenAI

from config.azure_config import (
    SEARCH_ENDPOINT,
    SEARCH_ADMIN_KEY,
    SEARCH_INDEX_NAME,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
)


RULES_CURRENT_DIR = Path("data/rules/current")
BB_CURRENT_DIR = Path("data/building_blocks/current")

RULES_PREVIOUS_DIR = Path("data/rules/previous")
BB_PREVIOUS_DIR = Path("data/building_blocks/previous")


search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_ADMIN_KEY),
)

openai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2025-01-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_logic_text(text: str) -> str:
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_content(rule: dict) -> str:
    lines = []

    lines.append(f"Rule ID: {rule.get('rule_id', '')}")
    lines.append(f"Name: {rule.get('rule_name', '')}")
    lines.append(f"Object Type: {rule.get('object_type', '')}")
    lines.append(f"Category: {rule.get('rule_category', '')}")
    lines.append(f"Group: {rule.get('group', '')}")
    lines.append(f"Enabled: {rule.get('enabled', '')}")
    lines.append(f"Origin: {rule.get('origin', '')}")
    lines.append(f"Response: {rule.get('response', '')}")

    logic = rule.get("logic")
    if logic:
        lines.append("")
        lines.append("Detection Logic:")

        for block in logic:
            if not isinstance(block, dict):
                continue

            tests = block.get("test", [])
            for test in tests:
                if not isinstance(test, dict):
                    continue

                test_meta = test.get("_$", {})
                test_name = test_meta.get("name", "")

                if test_name:
                    lines.append(f"- Test Type: {test_name}")

                for text in test.get("text", []) or []:
                    cleaned = clean_logic_text(text)
                    if cleaned:
                        lines.append(f"  Logic: {cleaned}")

                params = test.get("parameter", []) or []
                useful_params = []
                for param in params:
                    if not isinstance(param, dict):
                        continue

                    param_id = param.get("id", "")
                    method = param.get("method", "")
                    value = param.get("value", "")

                    if value:
                        if method:
                            useful_params.append(f"id={param_id}, method={method}, value={value}")
                        else:
                            useful_params.append(f"id={param_id}, value={value}")

                if useful_params:
                    lines.append("  Parameters:")
                    for p in useful_params:
                        lines.append(f"  - {p}")

    actions = rule.get("actions")
    if actions:
        lines.append("")
        lines.append("Actions:")
        lines.append(json.dumps(actions, ensure_ascii=False, indent=2))

    deps = rule.get("dependencies", [])
    if deps:
        lines.append("")
        lines.append("Dependencies:")
        for dep in deps:
            if isinstance(dep, dict):
                dep_name = dep.get("name", "")
                dep_uuid = dep.get("uuid", "")
                lines.append(f"- {dep_name} ({dep_uuid})")

    mitre = rule.get("mitre")
    if isinstance(mitre, dict) and mitre:
        lines.append("")
        lines.append("MITRE / Tactics:")
        for key in mitre.keys():
            lines.append(f"- {key}")

    return "\n".join(lines)


def generate_embedding(text: str):
    response = openai_client.embeddings.create(
        input=text,
        model=AZURE_OPENAI_EMBED_DEPLOYMENT,
    )
    return response.data[0].embedding


def load_rules_from_dirs(dirs: list[Path]) -> dict:
    items = {}

    for folder in dirs:
        if not folder.exists():
            continue

        for file in folder.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    obj = json.load(f)

                rule_doc_id = str(obj.get("rule_doc_id") or obj.get("rule_id") or "").strip()
                if not rule_doc_id:
                    continue

                items[rule_doc_id] = obj

            except Exception as e:
                print(f"⚠️ Failed to load {file}: {e}")

    return items


def normalize_for_hash(rule: dict) -> dict:
    excluded = {
        "last_parsed_utc",
        "last_enriched_utc",
        "last_indexed_utc",
        "content",
        "content_vector",
    }

    return {
        k: v
        for k, v in rule.items()
        if k not in excluded
    }


def hash_rule(rule: dict) -> str:
    normalized = normalize_for_hash(rule)
    canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_existing_ids() -> set[str]:
    print("🔍 Fetching existing documents from Azure Search...")

    existing_ids = set()

    try:
        results = search_client.search(
            search_text="*",
            select="rule_doc_id",
            top=1000,
        )

        for result in results:
            rule_doc_id = result.get("rule_doc_id")
            if rule_doc_id:
                existing_ids.add(rule_doc_id)

    except ResourceNotFoundError:
        print("⚠️ Index not found yet — assuming empty index")
        return set()

    print(f"Found {len(existing_ids)} existing documents in Azure Search")
    return existing_ids


def upload_documents(docs: list[dict], batch_size: int = 100):
    if not docs:
        print("Nothing to upload ✅")
        return

    print(f"\n📤 Uploading {len(docs)} documents to Azure Search...")

    for i in range(0, len(docs), batch_size):
        batch = docs[i:i + batch_size]
        search_client.upload_documents(documents=batch)
        print(f"Uploaded {min(i + batch_size, len(docs))}/{len(docs)}")

    print("✅ Upload complete")


def delete_removed_docs(existing_ids: set[str], local_ids: set[str]):
    if len(local_ids) < 100:
        print("⚠️ Suspiciously low local rule count — skipping deletion")
        return

    to_delete = sorted(existing_ids - local_ids)

    print(f"\n🗑️ Deleting {len(to_delete)} removed rules...")

    if not to_delete:
        print("Nothing to delete ✅")
        return

    batch_size = 100

    for i in range(0, len(to_delete), batch_size):
        batch_ids = to_delete[i:i + batch_size]
        batch = [{"rule_doc_id": rid} for rid in batch_ids]
        search_client.delete_documents(documents=batch)
        print(f"Deleted {min(i + batch_size, len(to_delete))}/{len(to_delete)}")

    print("✅ Deletion complete")


def build_search_doc(rule: dict) -> dict:
    content = build_content(rule)
    embedding = generate_embedding(content)

    return {
        "rule_doc_id": rule["rule_doc_id"],
        "rule_id": rule["rule_id"],
        "rule_name": rule["rule_name"],
        "object_type": rule["object_type"],
        "group_name": rule.get("group"),
        "rule_category": rule.get("rule_category"),
        "enabled": rule.get("enabled"),
        "content": content,
        "content_vector": embedding,
        "last_indexed_utc": utc_now(),
    }


def main():
    print("🚀 Loading current and previous rule snapshots...")

    current_rules = load_rules_from_dirs([RULES_CURRENT_DIR, BB_CURRENT_DIR])
    previous_rules = load_rules_from_dirs([RULES_PREVIOUS_DIR, BB_PREVIOUS_DIR])

    print(f"Current rules/building blocks:  {len(current_rules)}")
    print(f"Previous rules/building blocks: {len(previous_rules)}")

    if len(current_rules) < 100:
        raise RuntimeError("Current rule set is suspiciously small. Refusing to sync.")

    current_ids = set(current_rules.keys())
    previous_ids = set(previous_rules.keys())

    existing_ids = get_existing_ids()

    new_ids = current_ids - previous_ids
    removed_ids = previous_ids - current_ids
    common_ids = current_ids & previous_ids

    changed_ids = set()
    for rule_id in common_ids:
        if hash_rule(current_rules[rule_id]) != hash_rule(previous_rules[rule_id]):
            changed_ids.add(rule_id)

    missing_in_search_ids = current_ids - existing_ids

    upload_ids = sorted(new_ids | changed_ids | missing_in_search_ids)

    print("")
    print("📊 Diff summary")
    print(f"New:               {len(new_ids)}")
    print(f"Changed:           {len(changed_ids)}")
    print(f"Removed snapshot:  {len(removed_ids)}")
    print(f"Missing in Search: {len(missing_in_search_ids)}")
    print(f"To upload:         {len(upload_ids)}")

    docs = []

    for i, rule_doc_id in enumerate(upload_ids, start=1):
        rule = current_rules[rule_doc_id]
        docs.append(build_search_doc(rule))

        if i % 50 == 0:
            print(f"Prepared {i}/{len(upload_ids)}")

    upload_documents(docs)

    # Delete based on actual Search contents vs current local truth
    delete_removed_docs(existing_ids, current_ids)

    print("\n✅ Sync complete")


if __name__ == "__main__":
    main()