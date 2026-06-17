from typing import List, Dict
from azure.search.documents.models import VectorizedQuery
from config.search_config import (
    get_search_client,
    get_openai_client,
    OFFICIAL_INDEX_NAME,
    ANALYST_MEMORY_INDEX_NAME,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
)


def embed_query(query: str) -> List[float]:
    client = get_openai_client()
    response = client.embeddings.create(
        model=AZURE_OPENAI_EMBED_DEPLOYMENT,
        input=[query],
    )
    return response.data[0].embedding


def format_source_label(index_name: str, doc: dict) -> str:
    if index_name == OFFICIAL_INDEX_NAME:
        return doc.get("source_path", "") or doc.get("title", "official_doc")

    if index_name == ANALYST_MEMORY_INDEX_NAME:
        source_type = doc.get("source_type", "memory")
        title = doc.get("title", "") or doc.get("case_uid", "") or doc.get("note_id", "")
        client_id = doc.get("client_id", "")
        if client_id:
            return f"{source_type}:{client_id}:{title}"
        return f"{source_type}:{title}"

    return index_name


def hybrid_search_index(
    index_name: str,
    query: str,
    top_k: int = 5,
    filter_expr: str | None = None,
) -> List[Dict]:
    search_client = get_search_client(index_name)
    vector = embed_query(query)

    results = search_client.search(
        search_text=query,
        vector_queries=[
            VectorizedQuery(
                vector=vector,
                k_nearest_neighbors=max(top_k * 2, 10),
                fields="content_vector",
            )
        ],
        top=top_k,
        filter=filter_expr,
        query_type="semantic",
        semantic_configuration_name="default-semantic-config",
    )

    normalized = []
    for doc in results:
        source_label = format_source_label(index_name, doc)

        # both official and analyst-memory indexes use "content"
        text = doc.get("content", "") or doc.get("summary_text", "")
        if not text:
            continue

        normalized.append({
            "source": source_label,
            "source_type": doc.get("source_type", ""),
            "text": text,
            "score": doc.get("@search.score"),
            "reranker_score": doc.get("@search.reranker_score"),
        })

    return normalized


def dedupe_and_trim(results: List[Dict], top_k: int = 5) -> List[Dict]:
    deduped = []
    seen = set()

    for item in results:
        key = (item["source"], item["text"][:200])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= top_k:
            break

    return deduped


def retrieve_reasoning_context(query: str, top_k: int = 5) -> List[Dict]:
    try:
        official = hybrid_search_index(OFFICIAL_INDEX_NAME, query, top_k=3)
        analyst = hybrid_search_index(ANALYST_MEMORY_INDEX_NAME, query, top_k=3)

        combined = sorted(
            official + analyst,
            key=lambda x: (
                x.get("reranker_score") if x.get("reranker_score") is not None else -1,
                x.get("score") if x.get("score") is not None else -1,
            ),
            reverse=True,
        )
        return dedupe_and_trim(combined, top_k=top_k)

    except Exception as e:
        print(f"[retrieve_reasoning_context] Azure Search retrieval failed: {e}", flush=True)
        return []


def retrieve_offense_context(
    query: str,
    rule_id: str | None = None,
    client_id: str | None = None,
    top_k: int = 6,
) -> List[Dict]:
    try:
        official = hybrid_search_index(OFFICIAL_INDEX_NAME, query, top_k=3)

        analyst_filter = None
        if client_id:
            analyst_filter = f"client_id eq '{client_id}'"

        analyst = hybrid_search_index(
            ANALYST_MEMORY_INDEX_NAME,
            query,
            top_k=4,
            filter_expr=analyst_filter,
        )

        # if rule_id is known, bias toward analyst memory entries that match the same rule
        if rule_id:
            matching = [x for x in analyst if f":{rule_id}" in x["source"] or x["text"].find(rule_id) != -1]
            analyst = matching + analyst

        combined = sorted(
            official + analyst,
            key=lambda x: (
                x.get("reranker_score") if x.get("reranker_score") is not None else -1,
                x.get("score") if x.get("score") is not None else -1,
            ),
            reverse=True,
        )
        return dedupe_and_trim(combined, top_k=top_k)

    except Exception as e:
        print(f"[retrieve_offense_context] Azure Search retrieval failed: {e}", flush=True)
        return []