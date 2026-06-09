def retrieve_context(user_text: str) -> list[str]:
    """
    Placeholder retrieval layer.

    For now, returns static context examples.
    Later, this becomes:
    - Azure AI Search retrieval
    - QRadar docs grounding
    - internal knowledge retrieval
    """

    lowered = user_text.lower()

    context_chunks = []

    if "building block" in lowered:
        context_chunks.append(
            "QRadar Building Blocks are test-only logic objects that do not generate offenses directly. "
            "They are typically reused inside rules to centralize logic."
        )

    if "correlation rule" in lowered or "qradar rule" in lowered:
        context_chunks.append(
            "QRadar correlation rules detect conditions by evaluating event and/or flow patterns over time. "
            "Tuning often involves thresholds, scope restrictions, exclusions, or moving logic into reusable building blocks."
        )

    if "false positive" in lowered or "tuning" in lowered:
        context_chunks.append(
            "False-positive reduction should usually preserve visibility where possible and prefer reversible, auditable tuning changes."
        )

    return context_chunks
