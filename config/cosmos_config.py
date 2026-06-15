import os
from azure.cosmos import CosmosClient


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


COSMOS_ENDPOINT = _require_env("COSMOS_ENDPOINT")
COSMOS_KEY = _require_env("COSMOS_KEY")

COSMOS_DATABASE_NAME = os.getenv("COSMOS_DATABASE_NAME", "rulebotdb").strip()
COSMOS_CASE_CONTAINER = os.getenv("COSMOS_CASE_CONTAINER", "case-records").strip()

# Recommended partition key for your use case
COSMOS_PARTITION_KEY = "/client_id"


def get_cosmos_client() -> CosmosClient:
    return CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)


def get_database():
    client = get_cosmos_client()
    return client.get_database_client(COSMOS_DATABASE_NAME)


def get_case_records_container():
    db = get_database()
    return db.get_container_client(COSMOS_CASE_CONTAINER)