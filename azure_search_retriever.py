from typing import List, Dict
from azure.search.documents.models import VectorizedQuery
from config.search_config import (
    get_search_client,
    get_openai_client,
    OFFICIAL_INDEX_NAME,
    RULES_INDEX_NAME,
    ANALYST_MEMORY_INDEX_NAME,
    CANONICAL_RULES_INDEX_NAME,
    CANONICAL_SEMANTIC_CONFIG,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
)


def embed_query(query: str) -> List[float]:
    client = get_openai_client()
    response = client.embeddings.create(
        model=AZURE_OPENAI_EMBED_DEPLOYMENT,
        input=[query],
    )
    return response.data[0].embedding


def format_source_label(
    index_name: str,
    doc: dict,
) -> str:
    if index_name == OFFICIAL_INDEX_NAME:
        return (
            doc.get("source_path", "")
            or doc.get("title", "official_doc")
        )

    if index_name in{
        RULES_INDEX_NAME,
        CANONICAL_RULES_INDEX_NAME,
    }:
        rule_id = (
            doc.get("primary_qradar_rule_id")
            or doc.get("rule_id")
            or ""
        )
        title = (
            doc.get("title")
            or doc.get("rule_name")
            or ""
        )

        canonical_uuid = doc.get("canonical_uuid", "",)

        rule_doc_id = (
            doc.get("id")
            or doc.get("rule_doc_id")
            or ""
        )

        identity = (
            canonical_uuid
            or rule_doc_id
            or str(rule_id)
        )


        return (
            f"rule:{rule_id}:"
            f"{identity}:"
            f"{title}"
        )

    if index_name == ANALYST_MEMORY_INDEX_NAME:
        source_type = doc.get(
            "source_type",
            "memory",
        )
        title = (
            doc.get("title", "")
            or doc.get("case_uid", "")
            or doc.get("note_id", "")
        )
        client_id = doc.get("client_id", "")

        if client_id:
            return (
                f"{source_type}:"
                f"{client_id}:"
                f"{title}"
            )

        return f"{source_type}:{title}"

    return index_name


def normalize_doc(
    index_name: str,
    doc: dict,
) -> dict | None:
    if index_name == CANONICAL_RULES_INDEX_NAME:
        text = doc.get("rag_text", "")

        if not text:
            return None

        qradar_rule_ids = (
            doc.get("qradar_rule_ids")
            or []
        )

        primary_rule_id = doc.get(
            "primary_qradar_rule_id"
        )

        if primary_rule_id is not None:
            rule_id = str(primary_rule_id)
        elif qradar_rule_ids:
            rule_id = str(qradar_rule_ids[0])
        else:
            rule_id = ""

        source_type = (
            doc.get("document_type")
            or doc.get("corpus_type")
            or ""
        )

        return {
            "source": format_source_label(
                index_name,
                doc,
            ),
            "source_type": source_type,
            "object_type": doc.get(
                "object_type",
                "",
            ),
            "text": text,
            "score": doc.get("@search.score"),
            "reranker_score": doc.get(
                "@search.reranker_score"
            ),
            "rule_doc_id": doc.get("id", ""),
            "rule_id": rule_id,
            "rule_name": doc.get("title", ""),
            "client_id": doc.get(
                "tenant_id",
                "",
            ),
            "title": doc.get("title", ""),
            "canonical_uuid": doc.get(
                "canonical_uuid",
                "",
            ),
            "qradar_rule_ids": qradar_rule_ids,
            "identifiers": (
                doc.get("identifiers")
                or []
            ),
            "linked_rule_identifiers": (
                doc.get(
                    "linked_rule_identifiers"
                )
                or []
            ),
            "dependency_count": doc.get(
                "dependency_count",
                0,
            ),
        }

    text = doc.get("content", "")

    if not text:
        return None

    return {
        "source": format_source_label(
            index_name,
            doc,
        ),
        "source_type": doc.get(
            "source_type",
            "",
        ),
        "object_type": doc.get(
            "object_type",
            "",
        ),
        "text": text,
        "score": doc.get("@search.score"),
        "reranker_score": doc.get(
            "@search.reranker_score"
        ),
        "rule_doc_id": doc.get(
            "rule_doc_id",
            "",
        ),
        "rule_id": doc.get("rule_id", ""),
        "rule_name": doc.get(
            "rule_name",
            "",
        ),
        "client_id": doc.get(
            "client_id",
            "",
        ),
        "title": doc.get("title", ""),
    }


def hybrid_search_index(
    index_name: str,
    query: str,
    top_k: int = 5,
    filter_expr: str | None = None,
) -> List:
    search_client = get_search_client(
        index_name
    )
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

def search_canonical_rules(
    query: str,
    top_k: int = 5,
    filter_expr: str | None = None,
    tenant_id: str = "hilal-internal",
    object_type: str | None = None,
) -> List[Dict]:
    """
    Search the canonical QRadar rule corpus.

    The caller can provide an additional canonical identity filter through
    filter_expr. Tenant and restrictions are combined with that
    filter using OData AND semantics.
    """
    search_client = get_search_client(
        CANONICAL_RULES_INDEX_NAME
    )

    filters: list[str] = []

    if tenant_id:
        safe_tenant_id = tenant_id.replace(
            "'",
            "''",
        )
        filters.append(
            f"tenant_id eq '{safe_tenant_id}'"
        )

    if object_type:
        safe_object_type = object_type.replace(
            "'",
            "''",
        )
        filters.append(
            f"object_type eq '{safe_object_type}'"
        )

    if filter_expr:
        filters.append(
            f"({filter_expr})"
        )

    filter_expression = (
        " and ".join(filters)
        if filters
        else None
    )

    results = search_client.search(
        search_text=query,
        query_type="semantic",
        semantic_configuration_name=(
            CANONICAL_SEMANTIC_CONFIG
        ),
        filter=filter_expression,
        top=top_k,
        select=[
            "id",
            "canonical_uuid",
            "title",
            "corpus_type",
            "document_type",
            "object_type",
            "tenant_id",
            "primary_qradar_rule_id",
            "qradar_rule_ids",
            "identifiers",
            "linked_rule_identifiers",
            "dependency_count",
            "rag_text",
        ],
    )

    normalized: list[dict] = []

    for result in results:
        item = normalize_doc(
            CANONICAL_RULES_INDEX_NAME,
            dict(result),
        )

        if item is not None:
            normalized.append(item)

    return normalized

def resolve_canonical_rule(
    rule_reference: str,
    tenant_id: str = "hilal-internal",
) -> list:
    reference = str(
        rule_reference or ""
    ).strip()

    if not reference:
        return []

    search_client = get_search_client(
        CANONICAL_RULES_INDEX_NAME
    )

    filters = []

    if tenant_id:
        safe_tenant_id = tenant_id.replace(
            "'",
            "''",
        )
        filters.append(
            f"tenant_id eq '{safe_tenant_id}'"
        )

    if reference.isdigit():
        numeric_id = int(reference)

        filters.append(
            "("
            f"primary_qradar_rule_id eq {numeric_id} "
            "or "
            "qradar_rule_ids/any("
            f"rule_id: rule_id eq {numeric_id}"
            ")"
            ")"
        )
    else:
        safe_reference = reference.replace(
            "'",
            "''",
        )

        filters.append(
            "("
            f"canonical_uuid eq '{safe_reference}' "
            "or "
            "identifiers/any("
            f"identifier: identifier eq '{safe_reference}'"
            ") "
            "or "
            "linked_rule_identifiers/any("
            f"identifier: identifier eq '{safe_reference}'"
            ")"
            ")"
        )

    filter_expression = " and ".join(filters)

    results = search_client.search(
        search_text="*",
        filter=filter_expression,
        top=10,
        select=[
            "id",
            "canonical_uuid",
            "title",
            "corpus_type",
            "document_type",
            "object_type",
            "tenant_id",
            "primary_qradar_rule_id",
            "qradar_rule_ids",
            "identifiers",
            "linked_rule_identifiers",
            "dependency_count",
            "rag_text",
        ],
    )

    normalized = []

    for result in results:
        item = normalize_doc(
            CANONICAL_RULES_INDEX_NAME,
            dict(result),
        )

        if item is not None:
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
        score = float(item.get("_combined_score", 0) or 0)

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
            score += 3.0

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

def escape_odata_string(value: str) -> str:
    return value.replace("'", "''")

def build_canonical_identity_filter(
    term: str,
) -> str:
    """
    Build an exact canonical identity filter.

    Numeric values are checked against the primary ID and the complete
    qradar_rule_ids collection.

    String values are checked against document ID, canonical UUID,
    identifiers, and linked identifiers.
    """
    clean_term = str(term).strip()
    escaped = escape_odata_string(clean_term)

    clauses = [
        f"id eq '{escaped}'",
        f"canonical_uuid eq '{escaped}'",
        (
            "identifiers/any("
            f"value: value eq '{escaped}'"
            ")"
        ),
        (
            "linked_rule_identifiers/any("
            f"value: value eq '{escaped}'"
            ")"
        ),
    ]

    try:
        numeric_id = int(clean_term)
    except (TypeError, ValueError):
        numeric_id = None

    if numeric_id is not None:
        clauses.extend(
            [
                (
                    "primary_qradar_rule_id "
                    f"eq {numeric_id}"
                ),
                (
                    "qradar_rule_ids/any("
                    f"value: value eq {numeric_id}"
                    ")"
                ),
            ]
        )

    return " or ".join(clauses)

def extract_rule_lookup_terms_from_offense(offense_data: dict) -> list[str]:
    terms: list[str] = []

    def add(value):
        if value is None:
            return

        value = str(value).strip()

        if value and value not in terms:
            terms.append(value)

    # Legacy QRadar offense rule ID.
    add(offense_data.get("rule_id"))

    # New deterministic binding fields from PacketGenerator v3.
    for binding in offense_data.get("resolved_rule_bindings") or []:
        if not isinstance(binding, dict):
            continue

        add(binding.get("exported_rule_doc_id"))
        add(binding.get("exported_uuid"))
        add(binding.get("exported_rule_name"))
        add(binding.get("linked_rule_identifier"))
        add(binding.get("qradar_rule_name"))
        add(binding.get("offense_rule_id"))

    # QRadar metadata fallback.
    for meta in offense_data.get("qradar_rule_api_metadata") or []:
        if not isinstance(meta, dict):
            continue

        add(meta.get("linked_rule_identifier"))
        add(meta.get("identifier"))
        add(meta.get("name"))
        add(meta.get("id"))

    return terms


def build_metadata_only_rule_context(offense_data: dict) -> dict | None:
    metadata = offense_data.get("qradar_rule_api_metadata") or []
    bindings = offense_data.get("resolved_rule_bindings") or []

    if not metadata and not bindings:
        return None

    text = (
        "QRadar offense-linked rule metadata was available, but no exported "
        "rule logic was found in the rule knowledge base.\n\n"
        f"qradar_rule_api_metadata:\n{metadata}\n\n"
        f"resolved_rule_bindings:\n{bindings}\n\n"
        "Important: This metadata identifies the offense-linked QRadar rules, "
        "but it may not include full CRE tests, thresholds, dependencies, or responses. "
        "Do not provide condition-level tuning unless full exported rule logic is available."
    )

    return {
        "source": "qradar_rule_metadata:fallback",
        "source_type": "qradar_rule_metadata",
        "object_type": "metadata_only",
        "text": text,
        "score": 0,
        "reranker_score": None,
        "rule_doc_id": "",
        "rule_id": str(offense_data.get("rule_id", "")),
        "rule_name": "",
        "client_id": str(offense_data.get("client_id", "")),
        "title": "QRadar rule metadata fallback",
        "_combined_score": 0,
    }


def retrieve_rule_docs_for_offense_bindings(
    offense_data: dict,
    query: str,
    top_k: int = 4,
    tenant_id: str = "hilal-internal",
) -> list[dict]:
    results: list[dict] = []
    exact_results: list[dict] = []

    lookup_terms = extract_rule_lookup_terms_from_offense(
        offense_data
    )

    # 1. Deterministic exact lookup against every canonical identity.
    for term in lookup_terms:
        try:
            identity_filter = build_canonical_identity_filter(
                term
            )

            docs = search_canonical_rules(
                query="*",
                top_k=5,
                filter_expr=identity_filter,
                tenant_id=tenant_id,
            )

            for item in docs:
                item["_combined_score"] = 100
                exact_results.append(item)

        except Exception as exc:
            print(
                "[retrieve_rule_docs_for_offense_bindings] "
                f"exact canonical lookup failed for {term}: "
                f"{exc}",
                flush=True,
            )

    if exact_results:
        return dedupe_and_trim(
            exact_results,
            top_k=top_k,
            max_per_source=1,
        )

    # 2. Semantic fallback for UUIDs, names, and unresolved terms.
    for term in lookup_terms:
        try:
            fallback = search_canonical_rules(
                query=term,
                top_k=2,
                tenant_id=tenant_id,
            )

            for item in fallback:
                item["_combined_score"] = (
                    item.get("_combined_score", 0)
                    + 25
                )
                results.append(item)

        except Exception as exc:
            print(
                "[retrieve_rule_docs_for_offense_bindings] "
                f"semantic canonical lookup failed for {term}: "
                f"{exc}",
                flush=True,
            )

    # 3. Final fallback using the main offense query.
    if not results and query.strip():
        try:
            results = search_canonical_rules(
                query=query,
                top_k=top_k,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            print(
                "[retrieve_rule_docs_for_offense_bindings] "
                f"main-query fallback failed: {exc}",
                flush=True,
            )

    return dedupe_and_trim(
        results,
        top_k=top_k,
        max_per_source=1,
    )

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
    offense_data: dict | None = None,
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

        # Rule retrieval from rule index.
        # Prefer resolved_rule_bindings from PacketGenerator v3 because QRadar offense
        # rule IDs do not always match exported rule document IDs.
        rule_related = []

        if offense_data:
            rule_related = retrieve_rule_docs_for_offense_bindings(
                offense_data=offense_data,
                query=query,
                top_k=4,
                tenant_id="hilal-internal",
            )

        if not rule_related and rule_id:
            identity_filter = build_canonical_identity_filter(
                str(rule_id)
            )

            rule_related = search_canonical_rules(
                query="*",
                top_k=2,
                filter_expr=identity_filter,
                tenant_id="hilal-internal",
            )

        if not rule_related and offense_data:
            metadata_fallback = build_metadata_only_rule_context(offense_data)

            if metadata_fallback:
                rule_related = [metadata_fallback]

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