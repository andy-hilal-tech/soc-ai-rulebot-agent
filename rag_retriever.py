import re
import json
from pathlib import Path
from PyPDF2 import PdfReader

KNOWLEDGE_DIRS = [
    Path("knowledge/qradar_docs"),
    Path("knowledge/internal_notes"),
]

SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".pdf"}
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def extract_text_from_pdf(file_path: Path) -> str:
    try:
        reader = PdfReader(str(file_path))
        pages = []

        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)

        return "\n".join(pages).strip()
    except Exception:
        return ""


def load_text_from_file(file_path: Path) -> str:
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".pdf":
            return extract_text_from_pdf(file_path)

        return file_path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def load_documents() -> list[dict]:
    docs = []

    for base_dir in KNOWLEDGE_DIRS:
        if not base_dir.exists():
            continue

        for file_path in base_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            text = load_text_from_file(file_path)

            if not text:
                continue

            docs.append({
                "source": str(file_path),
                "text": text
            })

    return docs


def chunk_text(text: str, source: str) -> list[dict]:
    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + CHUNK_SIZE, text_len)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append({
                "source": source,
                "text": chunk
            })

        if end == text_len:
            break

        start = max(0, end - CHUNK_OVERLAP)

    return chunks


def build_chunk_index() -> list[dict]:
    all_chunks = []

    for doc in load_documents():
        all_chunks.extend(chunk_text(doc["text"], doc["source"]))

    return all_chunks


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))


def score_chunk(query_tokens: set[str], chunk_text: str) -> int:
    chunk_tokens = tokenize(chunk_text)
    return len(query_tokens & chunk_tokens)


def retrieve_chunks(query: str, top_k: int = 5) -> list[dict]:
    chunks = build_chunk_index()

    if not chunks:
        return []

    query_tokens = tokenize(query)
    scored = []

    for chunk in chunks:
        score = score_chunk(query_tokens, chunk["text"])
        if score > 0:
            scored.append({
                "source": chunk["source"],
                "text": chunk["text"],
                "score": score
            })

    scored.sort(key=lambda x: x["score"], reverse=True)

    return scored[:top_k]