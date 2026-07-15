import json
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from config.search_config import (
    get_search_client,
    get_openai_client,
    RULES_INDEX_NAME,
    EMBED_BATCH_SIZE,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
)


CONTENT_ROOTS = [
    {
        "root": Path("data/rules"),
        "object_type": "rule",
        "doc_prefix": "rule-",
    },
    {
        "root": Path("data/building_blocks"),
        "object_type": "building_block",
        "doc_prefix": "bb-",
    },
]

STATE_DIR = Path("scripts/state")
STATE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = STATE_DIR / "rules_index_state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def batched(items, size):
    batch = []

    for item in items:
        batch.append(item)

        if len(batch) >= size:
            yield batch
            batch = []

    if batch:
        yield batch


def embed_texts(texts: list[str]) -> list[list[float]]:
    client = get_openai_client()

    response = client.embeddings.create(
        model=AZURE_OPENAI_EMBED_DEPLOYMENT,
        input=texts,
    )

    return [d.embedding for d in response.data]


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def first_nonempty(data: dict, *keys, default: Any = ""):
    for key in keys:
        value = data.get(key)

        if value not in (None, "", []):
            return value

    return default


def normalize_rule(rule_json: dict, object_type: str, doc_prefix: str) -> tuple[str, dict]:
    raw_id = str(
        first_nonempty(
            rule_json,
            "id",
            "rule_id",
            "rule_doc_id",
            "_id",
            default="unknown",
        )
    )

    doc_id = f"{doc_prefix}{raw_id}"

    rule_name = str(
        first_nonempty(
            rule_json,
            "name",
            "rule_name",
            default=f"{object_type}-{raw_id}",
        )
    )

    enabled = bool(
        first_nonempty(
            rule_json,
            "enabled",
            "rule_enabled",
            default=False,
        )
    )

    group_name = str(
        first_nonempty(
            rule_json,
            "group",
            "group_name",
            default="",
        )
    )

    rule_category = str(
        first_nonempty(
            rule_json,
            "rule_category",
            "category",
            "group",
            "group_name",
            default="",
        )
    )

    content = json.dumps(rule_json, indent=2, sort_keys=True)

    record = {
        "rule_doc_id": doc_id,
        "rule_id": raw_id,
        "rule_name": rule_name,
        "object_type": object_type,
        "group_name": group_name,
        "rule_category": rule_category,
        "enabled": enabled,
        "content": content,
        "last_indexed_utc": utc_now(),
        "version_hash": stable_hash(content),
    }

    return doc_id, record


def load_documents_from_content_roots() -> dict:
    docs_by_doc_id = {}

    for content_root in CONTENT_ROOTS:
        root = content_root["root"]
        object_type = content_root["object_type"]
        doc_prefix = content_root["doc_prefix"]

        if not root.exists():
            print(f"Skipping missing content root: {root}")
            continue

        print(f"Scanning {root} as {object_type}")

        for file_path in root.rglob("*.json"):
            try:
                rule_json = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"Skipping unreadable JSON file: {file_path} ({exc})")
                continue

            doc_id, record = normalize_rule(
                rule_json=rule_json,
                object_type=object_type,
                doc_prefix=doc_prefix,
            )

            docs_by_doc_id[doc_id] = record

    return docs_by_doc_id


def main():
    search_client = get_search_client(RULES_INDEX_NAME)

    previous_state = load_state()
    current_state = {}

    docs_by_doc_id = load_documents_from_content_roots()

    for doc_id, record in docs_by_doc_id.items():
        current_state[doc_id] = stable_hash(record["content"])

    to_upsert = []

    for doc_id, record in docs_by_doc_id.items():
        for doc_id, record in docs_by_doc_id.items():
            record_hash = stable_hash(record["content"])
            current_state[doc_id] = record_hash

            if previous_state.get(doc_id) != record_hash:
                to_upsert.append(record)

    removed_doc_ids = sorted(set(previous_state.keys()) - set(current_state.keys()))

    print(f"Documents discovered: {len(docs_by_doc_id)}")
    print(f"Changed/new documents to upsert: {len(to_upsert)}")
    print(f"Removed documents to delete: {len(removed_doc_ids)}")

    if to_upsert:
        for batch in batched(to_upsert, EMBED_BATCH_SIZE):
            vectors = embed_texts([doc["content"] for doc in batch])

            for doc, vector in zip(batch, vectors):
                doc["content_vector"] = vector

            search_client.merge_or_upload_documents(documents=batch)

        print(f"Upserted changed/new documents: {len(to_upsert)}")
    else:
        print("No changed/new documents to upsert.")

    if removed_doc_ids:
        delete_payload = [{"rule_doc_id": doc_id} for doc_id in removed_doc_ids]
        search_client.delete_documents(documents=delete_payload)

        print(f"Deleted removed documents: {len(removed_doc_ids)}")
    else:
        print("No removed documents to delete.")

    save_state(current_state)

    rules_count = sum(
        1 for doc in docs_by_doc_id.values()
        if doc.get("object_type") == "rule_json"
    )

    building_blocks_count = sum(
        1 for doc in docs_by_doc_id.values()
        if doc.get("object_type") == "building_block_json"
    )

    print("")
    print("Rules ingestion sync complete.")
    print(f"Indexed rule documents discovered: {rules_count}")
    print(f"Indexed building block documents discovered: {building_blocks_count}")


if __name__ == "__main__":
    main()