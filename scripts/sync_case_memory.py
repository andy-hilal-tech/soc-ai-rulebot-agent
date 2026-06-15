from datetime import datetime, timezone

from config.search_config import (
    get_search_client,
    get_openai_client,
    CASE_MEMORY_INDEX_NAME,
    EMBED_BATCH_SIZE,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
)
from config.cosmos_config import get_case_records_container


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


def listify(value):
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [str(value)]


def build_case_summary(record: dict) -> str:
    parts = [
        f"Case UID: {record.get('case_uid', '')}",
        f"Client ID: {record.get('client_id', '')}",
        f"Rule ID: {record.get('rule_id', '')}",
        f"Offense ID: {record.get('offense_id', '')}",
        f"Event Name: {record.get('event_name', '')}",
        f"Offense Summary: {record.get('offense_summary', '')}",
        f"Why False Positive: {record.get('why_false_positive', '')}",
        f"Desired Outcome: {record.get('desired_outcome', '')}",
        f"Analyst Notes: {record.get('analyst_notes', '')}",
        f"Implementation Status: {record.get('implementation_status', '')}",
    ]

    recommended = record.get("recommended_tuning", {})
    if isinstance(recommended, dict):
        parts.append(f"Recommended Tuning Type: {recommended.get('type', '')}")
        parts.append(f"Recommended Tuning Details: {recommended.get('details', '')}")

    return "\n".join(p for p in parts if p.strip())


def main():
    container = get_case_records_container()
    search_client = get_search_client(CASE_MEMORY_INDEX_NAME)

    query = "SELECT * FROM c"
    records = list(container.query_items(query=query, enable_cross_partition_query=True))

    if not records:
        print("No Cosmos case records found.")
        return

    docs = []
    for record in records:
        case_uid = record.get("case_uid") or record.get("id")
        summary_text = build_case_summary(record)

        docs.append({
            "memory_doc_id": str(case_uid),
            "case_uid": str(case_uid),
            "client_id": str(record.get("client_id", "default")),
            "rule_id": str(record.get("rule_id", "")),
            "offense_id": str(record.get("offense_id", "")),
            "source_type": "case_memory",
            "summary_text": summary_text,
            "status": str(record.get("status", "")),
            "recommended_object_type": str(record.get("recommended_tuning", {}).get("type", "")),
            "decision_type": "rule_tuning",
            "created_utc": record.get("created_at") or utc_now(),
            "updated_utc": record.get("last_updated_at") or utc_now(),
            "linked_rule_ids": listify(record.get("linked_rule_ids")),
            "linked_case_uids": listify(record.get("linked_case_uids")),
        })

    for batch in batched(docs, EMBED_BATCH_SIZE):
        vectors = embed_texts([d["summary_text"] for d in batch])
        for d, v in zip(batch, vectors):
            d["content_vector"] = v
        search_client.merge_or_upload_documents(documents=batch)

    print(f"Synced case-memory documents: {len(docs)}")


if __name__ == "__main__":
    main()