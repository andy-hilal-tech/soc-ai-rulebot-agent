import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config.search_config import (
    AZURE_OPENAI_EMBED_DEPLOYMENT,
    EMBEDDING_DIMENSIONS,
    EMBED_BATCH_SIZE,
    get_openai_client,
    get_search_client,
)


INDEX_CONFIG = {
    "analyst-memory-index": {
        "key_field": "memory_doc_id",
        "expected_count": 2,
    },
    "qradar-official-index": {
        "key_field": "chunk_id",
        "expected_count": 628,
    },
    "qradar-rules-index": {
        "key_field": "rule_doc_id",
        "expected_count": 1977,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def batched(items: list[dict], size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def load_export(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Expected a JSON object in {path}, "
            f"found {type(payload).__name__}"
        )

    documents = payload.get("value")

    if not isinstance(documents, list):
        raise RuntimeError(
            f"Expected {path} to contain a top-level 'value' array"
        )

    return documents


def prepare_documents(
    documents: list[dict],
    key_field: str,
    expected_count: int,
) -> list:
    if len(documents) != expected_count:
        raise RuntimeError(
            f"Source count mismatch: expected {expected_count}, "
            f"found {len(documents)}"
        )

    prepared = []
    keys = []

    for position, source_document in enumerate(documents):
        if not isinstance(source_document, dict):
            raise RuntimeError(
                f"Document at position {position} is not a JSON object"
            )

        document = dict(source_document)
        document.pop("@search.score", None)
        document.pop("@search.rerankerScore", None)
        document.pop("@search.highlights", None)
        document.pop("@search.captions", None)

        key_value = document.get(key_field)
        content = document.get("content")

        if key_value is None or str(key_value).strip() == "":
            raise RuntimeError(
                f"Document at position {position} is missing "
                f"required key field '{key_field}'"
            )

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                f"Document '{key_value}' has empty or invalid content"
            )

        document.pop("content_vector", None)

        keys.append(str(key_value))
        prepared.append(document)

    duplicate_keys = sorted(
        key for key in set(keys)
        if keys.count(key) > 1
    )

    if duplicate_keys:
        preview = duplicate_keys[:10]
        raise RuntimeError(
            f"Found {len(duplicate_keys)} duplicate keys. "
            f"First duplicates: {preview}"
        )

    return prepared


def embed_texts(
    client,
    texts: list[str],
    max_attempts: int = 5,
) -> list[list[float]]:
    delay_seconds = 5

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.embeddings.create(
                model=AZURE_OPENAI_EMBED_DEPLOYMENT,
                input=texts,
            )

            vectors = [item.embedding for item in response.data]

            if len(vectors) != len(texts):
                raise RuntimeError(
                    f"Embedding response count mismatch: submitted "
                    f"{len(texts)}, received {len(vectors)}"
                )

            for position, vector in enumerate(vectors):
                if len(vector) != EMBEDDING_DIMENSIONS:
                    raise RuntimeError(
                        f"Embedding at batch position {position} has "
                        f"{len(vector)} dimensions; expected "
                        f"{EMBEDDING_DIMENSIONS}"
                    )

            return vectors

        except Exception:
            if attempt == max_attempts:
                raise

            print(
                f"Embedding attempt {attempt} failed. "
                f"Retrying in {delay_seconds} seconds..."
            )
            time.sleep(delay_seconds)
            delay_seconds *= 2

    raise RuntimeError("Embedding retries exhausted")


def check_upload_results(results, key_field: str) -> None:
    failures = []

    for result in results:
        if not result.succeeded:
            failures.append({
                key_field: result.key,
                "status_code": result.status_code,
                "error_message": result.error_message,
            })

    if failures:
        preview = failures[:10]
        raise RuntimeError(
            f"{len(failures)} document uploads failed. "
            f"First failures: {json.dumps(preview, indent=2)}"
        )


def get_index_count(search_client) -> int:
    results = search_client.search(
        search_text="*",
        include_total_count=True,
        top=0,
    )

    count = results.get_count()

    if count is None:
        raise RuntimeError(
            "Azure AI Search did not return a document count"
        )

    return count

def wait_for_index_count(
    search_client,
    expected_count: int,
    timeout_seconds: int = 180,
    poll_interval_seconds: int = 5,
) -> int:
    started = time.monotonic()
    last_count = -1

    while time.monotonic() - started < timeout_seconds:
        last_count = get_index_count(search_client)

        print(
            f"Visible index count: {last_count}; "
            f"expected: {expected_count}"
        )

        if last_count == expected_count:
            return last_count

        time.sleep(poll_interval_seconds)

    raise RuntimeError(
        f"Timed out waiting for index count. "
        f"Expected {expected_count}, last observed {last_count}"
    )


def write_report(
    report_directory: Path,
    index_name: str,
    source_file: Path,
    expected_count: int,
    uploaded_count: int,
    final_count: int,
    started_utc: str,
) -> Path:
    report_directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    report_path = report_directory / (
        f"{index_name}-migration-{timestamp}.json"
    )

    report = {
        "index_name": index_name,
        "source_file": str(source_file.resolve()),
        "embedding_deployment": AZURE_OPENAI_EMBED_DEPLOYMENT,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "embedding_batch_size": EMBED_BATCH_SIZE,
        "expected_source_count": expected_count,
        "uploaded_count": uploaded_count,
        "final_index_count": final_count,
        "started_utc": started_utc,
        "completed_utc": utc_now(),
        "status": (
            "success"
            if final_count == expected_count
            else "count_mismatch"
        ),
    }

    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate embeddings and migrate an exported "
            "legacy Rulebot Azure AI Search index."
        )
    )

    parser.add_argument(
        "--index",
        required=True,
        choices=sorted(INDEX_CONFIG),
        help="Destination Azure AI Search index name",
    )

    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Search export JSON containing a top-level value array",
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
        help="Validate the export without embedding or uploading",
    )

    args = parser.parse_args()

    config = INDEX_CONFIG[args.index]
    key_field = config["key_field"]
    expected_count = config["expected_count"]
    started_utc = utc_now()

    if not args.source.is_file():
        raise RuntimeError(
            f"Source file does not exist: {args.source}"
        )

    print(f"Index: {args.index}")
    print(f"Source: {args.source}")
    print(f"Expected documents: {expected_count}")
    print(f"Key field: {key_field}")
    print(
        f"Embedding deployment: "
        f"{AZURE_OPENAI_EMBED_DEPLOYMENT}"
    )
    print(f"Embedding dimensions: {EMBEDDING_DIMENSIONS}")
    print(f"Embedding batch size: {EMBED_BATCH_SIZE}")

    source_documents = load_export(args.source)

    documents = prepare_documents(
        documents=source_documents,
        key_field=key_field,
        expected_count=expected_count,
    )

    print(
        f"Source validation passed for "
        f"{len(documents)} documents."
    )

    if args.dry_run:
        print("Dry run complete. No embeddings generated.")
        print("No documents uploaded.")
        return

    openai_client = get_openai_client()
    search_client = get_search_client(args.index)

    uploaded_count = 0
    total_batches = (
        len(documents) + EMBED_BATCH_SIZE - 1
    ) // EMBED_BATCH_SIZE

    for batch_number, batch in enumerate(
        batched(documents, EMBED_BATCH_SIZE),
        start=1,
    ):
        vectors = embed_texts(
            openai_client,
            [document["content"] for document in batch],
        )

        for document, vector in zip(batch, vectors):
            document["content_vector"] = vector

        results = search_client.merge_or_upload_documents(
            documents=batch
        )

        check_upload_results(results, key_field)

        uploaded_count += len(batch)

        print(
            f"Batch {batch_number}/{total_batches}: "
            f"uploaded {len(batch)} documents; "
            f"cumulative {uploaded_count}/{len(documents)}"
        )

    final_count = wait_for_index_count(
        search_client=search_client,
        expected_count=expected_count,
    )

    print(f"Final index count: {final_count}")

    report_path = write_report(
        report_directory=args.report_dir,
        index_name=args.index,
        source_file=args.source,
        expected_count=expected_count,
        uploaded_count=uploaded_count,
        final_count=final_count,
        started_utc=started_utc,
    )

    print(f"Migration report: {report_path}")

    if final_count != expected_count:
        raise RuntimeError(
            f"Final count mismatch for {args.index}: "
            f"expected {expected_count}, found {final_count}"
        )

    print(f"Migration completed successfully: {args.index}")


if __name__ == "__main__":
    main()