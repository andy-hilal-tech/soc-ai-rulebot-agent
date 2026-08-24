import os
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# ----------------------------
# Azure AI Search
# ----------------------------
SEARCH_ENDPOINT = _require_env("SEARCH_ENDPOINT")

SEARCH_ADMIN_KEY = os.getenv(
    "SEARCH_ADMIN_KEY",
    "",
).strip()

CANONICAL_RULES_INDEX_NAME = os.getenv(
    "CANONICAL_RULES_INDEX_NAME",
    "qradar-rule-corpus-v1",
).strip()

CANONICAL_SEMANTIC_CONFIG = os.getenv(
    "CANONICAL_SEMANTIC_CONFIG",
    "canonical-semantic-config",
).strip()

# ----------------------------
# Azure OpenAI embeddings
# ----------------------------
AZURE_OPENAI_ENDPOINT = _require_env("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = _require_env("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview").strip()
AZURE_OPENAI_EMBED_DEPLOYMENT = _require_env("AZURE_OPENAI_EMBED_DEPLOYMENT")

# ----------------------------
# Search index names
# ----------------------------
OFFICIAL_INDEX_NAME = "qradar-official-index"
RULES_INDEX_NAME = "qradar-rules-index"
ANALYST_MEMORY_INDEX_NAME = "analyst-memory-index"

# text-embedding-3-large default dimension
EMBEDDING_DIMENSIONS = 3072

# Chunking defaults
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Embedding batch size
EMBED_BATCH_SIZE = 16

def _get_search_credential():
    if SEARCH_ADMIN_KEY:
        return AzureKeyCredential(
            SEARCH_ADMIN_KEY
        )

    return DefaultAzureCredential()


def get_search_client(
    index_name: str,
) -> SearchClient:
    return SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=index_name,
        credential=_get_search_credential(),
    )


def get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
    )