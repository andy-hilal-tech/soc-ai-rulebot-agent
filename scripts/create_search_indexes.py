from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SearchableField,
    SimpleField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticSearch,
    SemanticPrioritizedFields,
    SemanticField,
)
from config.search_config import (
    get_search_index_client,
    EMBEDDING_DIMENSIONS,
    OFFICIAL_INDEX_NAME,
    ANALYST_MEMORY_INDEX_NAME,
    RULES_INDEX_NAME,
)

VECTOR_PROFILE_NAME = "default-vector-profile"
VECTOR_ALGO_NAME = "default-hnsw"


def build_vector_search():
    return VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(name=VECTOR_ALGO_NAME),
        ],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE_NAME,
                algorithm_configuration_name=VECTOR_ALGO_NAME,
            )
        ],
    )


def build_semantic_search(title_field: str, content_field: str, keyword_fields=None):
    keyword_fields = keyword_fields or []
    return SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default-semantic-config",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name=title_field) if title_field else None,
                    content_fields=[SemanticField(field_name=content_field)],
                    keywords_fields=[SemanticField(field_name=f) for f in keyword_fields],
                ),
            )
        ]
    )


def create_or_update(index: SearchIndex):
    client = get_search_index_client()
    result = client.create_or_update_index(index)
    print(f"Index ready: {result.name}")


def official_docs_index():
    fields = [
        SimpleField(name="chunk_id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SimpleField(name="source_path", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="source_type", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="section_title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
        SearchField(
            name="tags",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SimpleField(name="product_area", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="last_ingested_utc", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SimpleField(name="chunk_order", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
    ]

    return SearchIndex(
        name=OFFICIAL_INDEX_NAME,
        fields=fields,
        vector_search=build_vector_search(),
        semantic_search=build_semantic_search("title", "content", ["section_title"]),
    )


def qradar_rules_index():
    fields = [
        SimpleField(name="rule_doc_id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="rule_id", type=SearchFieldDataType.String, filterable=True, facetable=True, sortable=True),

        SearchableField(name="rule_name", type=SearchFieldDataType.String),

        # NEW: distinguish rule vs building_block in the same index
        SearchableField(name="object_type", type=SearchFieldDataType.String, filterable=True, facetable=True),

        SimpleField(name="group_name", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="rule_category", type=SearchFieldDataType.String, filterable=True, facetable=True),

        # NOTE: your sync script sends "enabled", not "rule_enabled"
        SimpleField(name="enabled", type=SearchFieldDataType.Boolean, filterable=True, facetable=True),

        SearchableField(name="content", type=SearchFieldDataType.String),

        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),

        # Keep only fields that your sync script really sends
        SimpleField(name="last_indexed_utc", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
    ]

    return SearchIndex(
        name=RULES_INDEX_NAME,
        fields=fields,
        vector_search=build_vector_search(),
        semantic_search=build_semantic_search(
            "rule_name",
            "content",
            ["rule_id", "group_name", "rule_category", "object_type"]
        ),
    )

def analyst_memory_index():
    fields = [
        SimpleField(name="memory_doc_id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="source_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="client_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="author", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="note_id", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="case_uid", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SimpleField(name="rule_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="offense_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
        SimpleField(name="confidence_level", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="status", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="recommended_object_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="decision_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SearchField(
            name="tags",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SearchField(
            name="linked_rule_ids",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SearchField(
            name="linked_case_uids",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SimpleField(name="created_utc", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SimpleField(name="updated_utc", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
    ]

    return SearchIndex(
        name=ANALYST_MEMORY_INDEX_NAME,
        fields=fields,
        vector_search=build_vector_search(),
        semantic_search=build_semantic_search("title", "content", ["client_id", "rule_id", "author"]),
    )


if __name__ == "__main__":
    create_or_update(official_docs_index())
    create_or_update(qradar_rules_index())
    create_or_update(analyst_memory_index())
    print("All three indexes created/updated successfully.")