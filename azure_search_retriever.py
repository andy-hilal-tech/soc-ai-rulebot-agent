from typing import List, Dict
from azure.search.documents.models import VectorizedQuery
from config.search_config import (
    get_search_client,
    get_openai_client,
    OFFICIAL_INDEX_NAME,
    RULES_INDEX_NAME,
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

    if index_name == RULES_INDEX_NAME:
        return f"rule:{doc.get('rule_id', '')}:{doc.get('rule_name', '')}"

    if index_name == ANALYST_MEMORY_INDEX_NAME:
        source_type = doc.get("source_type", "memory")
        title = doc.get("title", "") or doc.get("case_uid", "") or doc.get("note_id", "")
        client_id = doc.get("client_id", "")
        if client_id:
            return f"{source_type}:{client_id}:{title}"
        return f"{source_type}:{title}"

    return index_name


def normalize_doc(index_name: str, doc: dict) -> dict | None:
    if index_name == OFFICIAL_INDEX_NAME:
        text = doc.get("content", "")
    elif index_name == RULES_INDEX_NAME:
        text = doc.get("content", "")
    elif index_name == ANALYST_MEMORY_INDEX_NAME:
        text = doc.get("content", "")
    else:
        text = doc.get("content", "")

    if not text:
        return None

    return {
        "source": format_source_label(index_name, doc),
        "source_type": doc.get("source_type", ""),
        "text": text,
        "score": doc.get("@search.score"),
        "reranker_score": doc.get("@search.reranker_score"),
        "rule_id": doc.get("rule_id", ""),
        "client_id": doc.get("client_id", ""),
        "title": doc.get("title", ""),
    }


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
                k_nearest_neighbors=max(top_k * 3, 12),
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
        item = normalize_doc(index_name, doc)
        if item:
            normalized.append(item)

    return normalized


def rerank_combined_results(
    results: List[Dict],
    query: str,
    rule_id: str | None = None,
    client_id: str | None = None,
) -> List[Dict]:
    query_lower = query.lower()
    reranked = []

    for item in results:
        score = 0.0

        if item.get("reranker_score") is not None:
            score += float(item["reranker_score"]) * 10

        if item.get("score") is not None:
            score += float(item["score"])

        text_lower = item["text"].lower()
        source_type = item.get("source_type", "")

        # official docs slightly preferred for general reasoning
        if source_type == "official_doc":
            score += 2.0

        # case-memory remains very useful, but slightly below official
        if source_type == "case_memory":
            score += 1.5

        # internal note still valuable, but don't let it dominate too easily
        if source_type == "internal_note":
            score += 1.0

        # exact phrase bias
        important_phrases = [
            "building block",
            "false positive",
            "correlation rule",
            "offense",
            "tuning",
        ]
        for phrase in important_phrases:
            if phrase in query_lower and phrase in text_lower:
                score += 2.0

        # rule_id bias
        if rule_id:
            if str(rule_id) == str(item.get("rule_id", "")):
                score += 5.0
            elif str(rule_id) in text_lower:
                score += 3.0

        # client bias
        if client_id and client_id == item.get("client_id", ""):
            score += 3.0

        # title/source slight bonus if query terms appear
        if item.get("title"):
            title_lower = item["title"].lower()
            if any(term in title_lower for term in query_lower.split()):
                score += 0.75

        item["_combined_score"] = score
        reranked.append(item)

    reranked.sort(key=lambda x: x["_combined_score"], reverse=True)
    return reranked


def dedupe_and_trim(
    results: List[Dict],
    top_k: int = 5,
    max_per_source: int = 2,
) -> List[Dict]:
    deduped = []
    seen = set()
    per_source = {}

    for item in results:
        source = item["source"]
        text_key = item["text"][:250].strip().lower()

        key = (source, text_key)
        if key in seen:
            continue

        if per_source.get(source, 0) >= max_per_source:
            continue

        seen.add(key)
        per_source[source] = per_source.get(source, 0) + 1
        deduped.append(item)

        if len(deduped) >= top_k:
            break

    return deduped


def retrieve_reasoning_context(query: str, top_k: int = 5) -> List[Dict]:
    try:
        official = hybrid_search_index(OFFICIAL_INDEX_NAME, query, top_k=4)
        analyst = hybrid_search_index(ANALYST_MEMORY_INDEX_NAME, query, top_k=4)

        combined = rerank_combined_results(
            official + analyst,
            query=query,
        )

        return dedupe_and_trim(combined, top_k=top_k, max_per_source=2)

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
        official = hybrid_search_index(OFFICIAL_INDEX_NAME, query, top_k=4)

        analyst_filter = None
        if client_id:
            analyst_filter = f"client_id eq '{client_id}'"

        analyst = hybrid_search_index(
            ANALYST_MEMORY_INDEX_NAME,
            query,
            top_k=5,
            filter_expr=analyst_filter,
        )

        # rule exact retrieval from rule index
        rule_related = []
        if rule_id:
            rule_filter = f"rule_id eq '{rule_id}'"
            rule_related = hybrid_search_index(
                RULES_INDEX_NAME,
                query,
                top_k=2,
                filter_expr=rule_filter,
            )

        combined = rerank_combined_results(
            official + analyst + rule_related,
            query=query,
            rule_id=rule_id,
            client_id=client_id,
        )

        return dedupe_and_trim(combined, top_k=top_k, max_per_source=2)

    except Exception as e:
        print(f"[retrieve_offense_context] Azure Search retrieval failed: {e}", flush=True)
        return []