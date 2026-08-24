import os

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )

    return value


COSMOS_ENDPOINT = _require_env(
    "COSMOS_ENDPOINT"
)

COSMOS_DATABASE_NAME = os.getenv(
    "COSMOS_DATABASE_NAME",
    "rulebotdb",
).strip()

COSMOS_CASE_CONTAINER = os.getenv(
    "COSMOS_CASE_CONTAINER",
    "case-records",
).strip()


_credential = DefaultAzureCredential()


def get_cosmos_client() -> CosmosClient:
    return CosmosClient(
        COSMOS_ENDPOINT,
        credential=_credential,
    )


def get_cosmos_database():
    client = get_cosmos_client()

    return client.get_database_client(
        COSMOS_DATABASE_NAME
    )


def get_case_records_container():
    database = get_cosmos_database()

    return database.get_container_client(
        COSMOS_CASE_CONTAINER
    )