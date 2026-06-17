import os
import uuid
from pathlib import Path
from datetime import datetime, timezone
import re

from PyPDF2 import PdfReader
from config.search_config import (
    get_search_client,
    get_openai_client,
    OFFICIAL_INDEX_NAME,
    ANALYST_MEMORY_INDEX_NAME,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBED_BATCH_SIZE,
    AZURE_OPENAI_EMBED_DEPLOYMENT,
)

ROOT_QRADAR_DOCS = Path("knowledge/qradar_docs")
ROOT_INTERNAL_NOTES = Path("knowledge/internal_notes")
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".json"}

def make_safe_key(value: str) -> str:
    value = value.strip().replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9_=-]", "_", value)
    return value


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages).strip()
    except Exception:
        return ""


def read_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return read_pdf(path)
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def chunk_text(text: str):
    chunks = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + CHUNK_SIZE, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - CHUNK_OVERLAP)

    return chunks


def batched(items, size):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def embed_texts(texts: list[str]) -> list[list[float]]:
    client = get_openai_client()
    response = client.embeddings.create(
        model=AZURE_OPENAI_EMBED_DEPLOYMENT,
        input=texts,
    )
    return [d.embedding for d in response.data]


def ingest_qradar_docs():
    search_client = get_search_client(OFFICIAL_INDEX_NAME)

    docs_to_upload = []
    for file_path in ROOT_QRADAR_DOCS.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        text = read_text(file_path)
        if not text:
            continue

        doc_id = make_safe_key(file_path.stem)
        title = file_path.stem.replace("_", " ")
        product_area = make_safe_key(file_path.parent.name)
        chunks = chunk_text(text)

        for i, chunk in enumerate(chunks):
            docs_to_upload.append({
                "chunk_id": f"{doc_id}-{i}",
                "doc_id": doc_id,
                "title": title,
                "source_path": str(file_path).replace("\\\\", "/"),
                "source_type": "official_doc",
                "section_title": product_area,
                "content": chunk,
                "tags": [product_area],
                "product_area": product_area,
                "last_ingested_utc": utc_now(),
                "chunk_order": i,
            })


    if not docs_to_upload:
        print("No official docs found to ingest.")
        return

    for batch in batched(docs_to_upload, EMBED_BATCH_SIZE):
        vectors = embed_texts([d["content"] for d in batch])
        for d, v in zip(batch, vectors):
            d["content_vector"] = v
        search_client.upload_documents(documents=batch)

    print(f"Ingested official docs chunks: {len(docs_to_upload)}")


def ingest_internal_notes():
    search_client = get_search_client(ANALYST_MEMORY_INDEX_NAME)

    docs_to_upload = []
    for file_path in ROOT_INTERNAL_NOTES.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        text = read_text(file_path)
        if not text:
            continue

        note_id = make_safe_key(file_path.stem)
        title = file_path.stem.replace("_", " ")
        client_id = make_safe_key(file_path.parent.name) if file_path.parent != ROOT_INTERNAL_NOTES else "default"

        for i, chunk in enumerate(chunks):
            docs_to_upload.append({
                "memory_doc_id": f"{note_id}-{i}",
                "note_id": note_id,
                "case_uid": "",
                "rule_id": "",
                "offense_id": "",
                "client_id": client_id,
                "author": "unknown",
                "source_type": "internal_note",
                "title": title,
                "content": chunk,
                "confidence_level": "unrated",
                "status": "",
                "recommended_object_type": "",
                "decision_type": "",
                "tags": [client_id],
                "linked_rule_ids": [],
                "linked_case_uids": [],
                "created_utc": utc_now(),
                "updated_utc": utc_now(),
            })


    if not docs_to_upload:
        print("No internal notes found to ingest.")
        return

    for batch in batched(docs_to_upload, EMBED_BATCH_SIZE):
        vectors = embed_texts([d["content"] for d in batch])
        for d, v in zip(batch, vectors):
            d["content_vector"] = v
        search_client.upload_documents(documents=batch)

    print(f"Ingested internal knowledge chunks: {len(docs_to_upload)}")


if __name__ == "__main__":
    ingest_qradar_docs()
    ingest_internal_notes()
    print("Official docs + internal notes ingestion complete.")