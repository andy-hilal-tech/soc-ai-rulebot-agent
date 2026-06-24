import sys
from pathlib import Path

# Ensure repo root is in PYTHONPATH
sys.path.append(str(Path(__file__).resolve().parent.parent))

import json
from pathlib import Path
from datetime import datetime, timezone
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI

from config.azure_config import (
    SEARCH_ENDPOINT,
    SEARCH_ADMIN_KEY,
    SEARCH_INDEX_NAME,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_EMBED_DEPLOYMENT
)

# --------------------------
# PATHS
# --------------------------

RULES_DIR = Path("data/rules/current")
BB_DIR = Path("data/building_blocks/current")

# --------------------------
# CLIENTS
# --------------------------

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_ADMIN_KEY)
)

openai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2025-01-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# --------------------------
# CONTENT BUILDER
# --------------------------

def build_content(rule):
    lines = []

    lines.append(f"Name: {rule.get('rule_name')}")
    lines.append(f"Type: {rule.get('object_type')}")
    lines.append(f"Category: {rule.get('rule_category')}")
    lines.append(f"Group: {rule.get('group')}")
    lines.append(f"Enabled: {rule.get('enabled')}")

    # Logic
    if rule.get("logic"):
        lines.append("\nLogic:")
        for block in rule["logic"]:
            if isinstance(block, dict):
                tests = block.get("test", [])
                for t in tests:
                    text = t.get("text")
                    if text:
                        lines.extend(text)

    # Dependencies
    deps = rule.get("dependencies", [])
    if deps:
        lines.append("\nDependencies:")
        for d in deps:
            if isinstance(d, dict):
                lines.append(f"- {d.get('name')}")

    # MITRE (simplified)
    mitre = rule.get("mitre")
    if isinstance(mitre, dict):
        lines.append("\nMITRE Tactics:")
        for key in mitre.keys():
            lines.append(f"- {key}")

    return "\n".join(lines)


# --------------------------
# EMBEDDING
# --------------------------

def generate_embedding(text):
    response = openai_client.embeddings.create(
        input=text,
        model=AZURE_OPENAI_EMBED_DEPLOYMENT
    )
    return response.data[0].embedding


# --------------------------
# LOAD FILES
# --------------------------

def load_all_rules():
    all_rules = []

    for folder in [RULES_DIR, BB_DIR]:
        for file in folder.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    rule = json.load(f)
                    all_rules.append(rule)
            except Exception:
                continue

    return all_rules


def get_existing_ids():
    print("🔍 Fetching existing documents from Azure Search...")

    existing_ids = set()

    results = search_client.search(
        search_text="*",
        select="rule_doc_id",
        top=1000
    )

    # ✅ NEW SDK style iteration
    for r in results:
        existing_ids.add(r.get("rule_doc_id"))

    print(f"Found {len(existing_ids)} existing documents")
    return existing_ids


def get_local_ids(rules):
    return {r["rule_doc_id"] for r in rules}


def delete_removed_docs(existing_ids, local_ids):
    to_delete = existing_ids - local_ids

    print(f"\n🗑️ Deleting {len(to_delete)} removed rules...")

    if not to_delete:
        print("Nothing to delete ✅")
        return

    batch = [{"rule_doc_id": rid} for rid in to_delete]

    search_client.delete_documents(documents=batch)

    print("✅ Deletion complete")


# --------------------------
# MAIN
# --------------------------

def main():
    print("🚀 Loading rules from JSON...")

    rules = load_all_rules()
    print(f"Loaded {len(rules)} rules")

    
    local_ids = get_local_ids(rules)
    existing_ids = get_existing_ids()


    docs = []

    for i, rule in enumerate(rules, 1):
        content = build_content(rule)

        embedding = generate_embedding(content)

        doc = {
            "rule_doc_id": rule["rule_doc_id"],
            "rule_id": rule["rule_id"],
            "rule_name": rule["rule_name"],
            "object_type": rule["object_type"],
            "group_name": rule.get("group"),
            "rule_category": rule.get("rule_category"),
            "enabled": rule.get("enabled"),
            "content": content,
            "content_vector": embedding,
            "last_indexed_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


        }

        docs.append(doc)

        if i % 50 == 0:
            print(f"Processed {i}/{len(rules)}")

    print("\n📤 Uploading to Azure Search...")

    batch_size = 100
    for i in range(0, len(docs), batch_size):
        batch = docs[i:i + batch_size]
        search_client.upload_documents(documents=batch)

    if len(local_ids) < 100:
        print("⚠️ Suspiciously low rule count — skipping deletion")
    else:
        delete_removed_docs(existing_ids, local_ids)



    print("✅ Sync complete")

if __name__ == "__main__":
    main()