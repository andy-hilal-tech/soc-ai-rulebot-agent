import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config.cosmos_config import get_cosmos_client


DATABASE_NAME = "rulebotdb"
CONTAINER_NAME = "case-records"
PARTITION_KEY_FIELD = "client_id"
EXPECTED_COUNT = 34


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_export(source_path: Path) -> list[dict]:
    with source_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise RuntimeError(
            "Expected the Cosmos export to contain a top-level JSON array"
        )

    return payload


def validate_documents(documents: list[dict]) -> None:
    if len(documents) != EXPECTED_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_COUNT} documents, found {len(documents)}"
        )

    document_ids = []

    for position, document in enumerate(documents):
        if not isinstance(document, dict):
            raise RuntimeError(
                f"Document at position {position} is not a JSON object"
            )

        document_id = document.get("id")
        client_id = document.get(PARTITION_KEY_FIELD)

        if document_id is None or str(document_id).strip() == "":
            raise RuntimeError(
                f"Document at position {position} has no valid id"
            )

        if client_id is None or str(client_id).strip() == "":
            raise RuntimeError(
                f"Document '{document_id}' has no valid client_id"
            )

        document_ids.append(str(document_id))

    unique_ids = set(document_ids)

    if len(unique_ids) != len(document_ids):
        duplicates = sorted(
            document_id
            for document_id in unique_ids
            if document_ids.count(document_id) > 1
        )

        raise RuntimeError(
            f"Duplicate document IDs found: {duplicates[:10]}"
        )


def count_documents(container) -> int:
    query = "SELECT VALUE COUNT(1) FROM c"

    results = list(
        container.query_items(
            query=query,
            enable_cross_partition_query=True,
        )
    )

    if len(results) != 1:
        raise RuntimeError(
            f"Unexpected Cosmos count response: {results}"
        )

    return int(results[0])


def wait_for_count(
    container,
    expected_count: int,
    timeout_seconds: int = 60,
    poll_interval_seconds: int = 3,
) -> int:
    started = time.monotonic()
    last_count = -1

    while time.monotonic() - started < timeout_seconds:
        last_count = count_documents(container)

        print(
            f"Visible Cosmos count: {last_count}; "
            f"expected: {expected_count}"
        )

        if last_count == expected_count:
            return last_count

        time.sleep(poll_interval_seconds)

    raise RuntimeError(
        f"Timed out waiting for Cosmos count. "
        f"Expected {expected_count}, last observed {last_count}"
    )


def write_report(
    report_directory: Path,
    source_path: Path,
    imported_count: int,
    final_count: int,
    client_ids: list[str],
    started_utc: str,
) -> Path:
    report_directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    report_path = report_directory / (
        f"case-records-cosmos-migration-{timestamp}.json"
    )

    report = {
        "cosmos_database": DATABASE_NAME,
        "cosmos_container": CONTAINER_NAME,
        "partition_key": f"/{PARTITION_KEY_FIELD}",
        "source_file": str(source_path.resolve()),
        "expected_count": EXPECTED_COUNT,
        "imported_count": imported_count,
        "final_count": final_count,
        "client_ids": sorted(set(client_ids)),
        "started_utc": started_utc,
        "completed_utc": utc_now(),
        "status": (
            "success"
            if final_count == EXPECTED_COUNT
            else "count_mismatch"
        ),
    }

    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and import the legacy Rulebot Cosmos "
            "case-records export."
        )
    )

    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Path to case-records-export.json",
    )

    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("/data/rulebot-migration/reports"),
        help="Directory for migration audit reports",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without connecting to or changing Cosmos DB",
    )

    args = parser.parse_args()
    started_utc = utc_now()

    if not args.source.is_file():
        raise RuntimeError(
            f"Source file does not exist: {args.source}"
        )

    documents = load_export(args.source)
    validate_documents(documents)

    client_ids = [
        str(document[PARTITION_KEY_FIELD])
        for document in documents
    ]

    print(f"Source: {args.source}")
    print(f"Database: {DATABASE_NAME}")
    print(f"Container: {CONTAINER_NAME}")
    print(f"Partition key: /{PARTITION_KEY_FIELD}")
    print(f"Documents validated: {len(documents)}")
    print(f"Distinct client_id values: {len(set(client_ids))}")

    if args.dry_run:
        print("Dry run complete.")
        print("No connection to Cosmos DB was made.")
        print("No documents were imported.")
        return

    cosmos_client = get_cosmos_client()

    database = cosmos_client.get_database_client(
        DATABASE_NAME
    )

    container = database.get_container_client(
        CONTAINER_NAME
    )

    imported_count = 0

    for position, document in enumerate(documents, start=1):
        container.upsert_item(body=document)
        imported_count += 1

        print(
            f"Upserted {position}/{len(documents)}: "
            f"{document['id']}"
        )

    final_count = wait_for_count(
        container=container,
        expected_count=EXPECTED_COUNT,
    )

    report_path = write_report(
        report_directory=args.report_dir,
        source_path=args.source,
        imported_count=imported_count,
        final_count=final_count,
        client_ids=client_ids,
        started_utc=started_utc,
    )

    print(f"Final Cosmos count: {final_count}")
    print(f"Migration report: {report_path}")

    if final_count != EXPECTED_COUNT:
        raise RuntimeError(
            f"Final count mismatch: expected {EXPECTED_COUNT}, "
            f"found {final_count}"
        )

    print("Cosmos migration completed successfully.")


if __name__ == "__main__":
    main()