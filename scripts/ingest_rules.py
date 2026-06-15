import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from config.search_config import (
    get_search_client,
    get_openai_client,
    RULES_INDEX_NAME,
    EMBED_BATCH_SIZE,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
)

RULES_ROOT = Path("data/rules")
STATE_DIR = Path("scripts/state")
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "rules_index_state.json"


def utc_now():
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


def first_nonempty(data: dict, *keys, default=""):
    for k in keys:
        value = data.get(k)
        if value not in (None, "", []):
            return value
    return default


def normalize_rule(rule_json: dict) -> tuple[str, dict]:
    rule_id = str(first_nonempty(rule_json, "id", "rule_id", "_id", default="unknown"))
    rule_name = str(first_nonempty(rule_json, "name", "rule_name", default=f"rule-{rule_id}"))
    rule_enabled = bool(first_nonempty(rule_json, "enabled", "rule_enabled", default=False))
    group_name = str(first_nonempty(rule_json, "group", "group_name", default=""))
    severity = str(first_nonempty(rule_json, "severity", "magnitude", default=""))

    content = json.dumps(rule_json, indent=2, sort_keys=True)

    record = {
        "rule_doc_id": rule_id,
        "rule_id": rule_id,
        "rule_name": rule_name,
        "source_type": "rule_json",
        "content": content,
        "rule_enabled": rule_enabled,
        "group_name": group_name,
        "severity": severity,
        "last_source_export_utc": utc_now(),
        "last_indexed_utc": utc_now(),
        "version_hash": stable_hash(content),
    }
    return rule_id, record


def main():
    search_client = get_search_client(RULES_INDEX_NAME)
    previous_state = load_state()
    current_state = {}

    docs_by_rule = {}
    for file_path in RULES_ROOT.rglob("*.json"):
        try:
            rule_json = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        rule_id, record = normalize_rule(rule_json)
        current_state[rule_id] = record["version_hash"]
        docs_by_rule[rule_id] = record

    to_upsert = []
    for rule_id, record in docs_by_rule.items():
        if previous_state.get(rule_id) != record["version_hash"]:
            to_upsert.append(record)

    removed_rule_ids = sorted(set(previous_state.keys()) - set(current_state.keys()))

    if to_upsert:
        for batch in batched(to_upsert, EMBED_BATCH_SIZE):
            vectors = embed_texts([d["content"] for d in batch])
            for d, v in zip(batch, vectors):
                d["content_vector"] = v
            search_client.merge_or_upload_documents(documents=batch)
        print(f"Upserted changed/new rules: {len(to_upsert)}")
    else:
        print("No changed/new rules to upsert.")

    if removed_rule_ids:
        delete_payload = [{"rule_doc_id": rid} for rid in removed_rule_ids]
        search_client.delete_documents(documents=delete_payload)
        print(f"Deleted removed rules: {len(removed_rule_ids)}")
    else:
        print("No removed rules to delete.")

    save_state(current_state)
    print("Rules ingestion sync complete.")


if __name__ == "__main__":
    main()