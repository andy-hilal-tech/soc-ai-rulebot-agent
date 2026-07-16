def extract_rule_lookup_terms(offense_data: dict) -> listterms = []

    def add(value):
        if value is None:
            return

        value = str(value).strip()

        if value and value not in terms:
            terms.append(value)

    add(offense_data.get("rule_id"))

    for binding in offense_data.get("resolved_rule_bindings") or []:
        if not isinstance(binding, dict):
            continue

        add(binding.get("exported_rule_doc_id"))
        add(binding.get("exported_uuid"))
        add(binding.get("exported_rule_name"))
        add(binding.get("linked_rule_identifier"))
        add(binding.get("qradar_rule_name"))

    for meta in offense_data.get("qradar_rule_api_metadata") or []:
        if not isinstance(meta, dict):
            continue

        add(meta.get("linked_rule_identifier"))
        add(meta.get("identifier"))
        add(meta.get("name"))
        add(meta.get("id"))

    return terms
