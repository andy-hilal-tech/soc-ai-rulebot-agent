from rag_retriever import retrieve_chunks


def retrieve_context(user_text: str) -> list[str]:
    chunks = retrieve_chunks(user_text, top_k=5)
    return [chunk["text"] for chunk in chunks]


def retrieve_context_with_sources(user_text: str) -> list[dict]:
    return retrieve_chunks(user_text, top_k=5)