from azure.search.documents.indexes import SearchIndexClient
from azure.core.credentials import AzureKeyCredential

from config.azure_config import SEARCH_ENDPOINT, SEARCH_ADMIN_KEY, SEARCH_INDEX_NAME

client = SearchIndexClient(
    endpoint=SEARCH_ENDPOINT,
    credential=AzureKeyCredential(SEARCH_ADMIN_KEY)
)

client.delete_index(SEARCH_INDEX_NAME)

print(f"✅ Index '{SEARCH_INDEX_NAME}' deleted")