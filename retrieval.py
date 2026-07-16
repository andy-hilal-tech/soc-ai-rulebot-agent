from azure_search_retriever import (
    retrieve_reasoning_context,
    retrieve_offense_context,
)


def retrieve_context(user_text: str) -> list:
    items = retrieve_reasoning_context(user_text, top_k=5)
    return [item["text"] for item in items]


def retrieve_context_with_sources(
    user_text: str,
    route: str = "reasoning",
    rule_id: str | None = None,
    client_id: str | None = None,
    offense_data: dict | None = None,
) -> list:
    if route == "offense_analysis":
        return retrieve_offense_context(
            query=user_text,
            rule_id=rule_id,
            client_id=client_id,
            offense_data=offense_data,
            top_k=6,
        )

    return retrieve_reasoning_context(user_text, top_k=5)