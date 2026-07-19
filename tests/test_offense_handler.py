import json
import os

os.environ.setdefault("SEARCH_ENDPOINT", "https://example.search.windows.net")
os.environ.setdefault("SEARCH_ADMIN_KEY", "test-key")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-key")
os.environ.setdefault("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding")
os.environ.setdefault("COSMOS_ENDPOINT", "https://example.documents.azure.com:443/")
os.environ.setdefault("COSMOS_KEY", "test-key")
os.environ.setdefault("COSMOS_DATABASE", "test-db")
os.environ.setdefault("COSMOS_CONTAINER", "test-container")

from handlers import offense_handler as oh


def test_get_candidate_rule_ids_returns_all_candidates():
    offense_data = {
        "resolved_rule_bindings": [
            {"exported_rule_doc_id": "rule-a"},
            {"exported_rule_doc_id": "rule-b"},
        ],
        "rule_id": "legacy-rule",
    }

    assert oh.get_candidate_rule_ids(offense_data) == ["rule-a", "rule-b", "legacy-rule"]


def test_handle_offense_analysis_includes_all_candidate_rule_details(monkeypatch):
    offense_data = {
        "rule_id": "legacy-rule",
        "resolved_rule_bindings": [
            {"exported_rule_doc_id": "rule-a"},
            {"exported_rule_doc_id": "rule-b"},
        ],
        "qradar_rule_api_metadata": [{"id": "meta-1"}],
        "event_name": "Suspicious event",
        "event_description": "A test offense",
        "why_false_positive": "False positive",
        "desired_outcome": "No action",
        "analyst_notes": "Notes",
        "payload_summary": "Payload",
        "top_qids": [],
        "combined_distribution": [],
    }

    captured = {}

    def fake_parse_offense_template(text):
        return offense_data

    def fake_missing_required_fields(data):
        return []

    def fake_get_rule(rule_id):
        return None

    def fake_retrieve_context_with_sources(*args, **kwargs):
        return []

    def fake_analyze_rule(system_prompt, user_prompt):
        captured["user_prompt"] = user_prompt
        return json.dumps({"summary": "ok"})

    def fake_build_case_record(**kwargs):
        return {}

    def fake_save_case_record(case_record):
        return {"case_uid": "case-123"}

    def fake_build_offense_reply(**kwargs):
        return "reply"

    monkeypatch.setattr(oh, "parse_offense_template", fake_parse_offense_template)
    monkeypatch.setattr(oh, "get_missing_required_fields", fake_missing_required_fields)
    monkeypatch.setattr(oh, "get_rule", fake_get_rule)
    monkeypatch.setattr(oh, "retrieve_context_with_sources", fake_retrieve_context_with_sources)
    monkeypatch.setattr(oh, "analyze_rule", fake_analyze_rule)
    monkeypatch.setattr(oh, "build_case_record", fake_build_case_record)
    monkeypatch.setattr(oh, "save_case_record", fake_save_case_record)
    monkeypatch.setattr(oh, "build_offense_reply", fake_build_offense_reply)

    import asyncio

    response, status = asyncio.run(oh.handle_offense_analysis("test text"))

    assert status == 200
    assert response["status"] == "success"
    assert '"resolved_rule_ids"' in captured["user_prompt"]
    assert '"resolved_rules"' in captured["user_prompt"]
    assert '"candidate_rule_ids"' in captured["user_prompt"]
    assert 'rule-a' in captured["user_prompt"]
    assert 'rule-b' in captured["user_prompt"]
    assert 'legacy-rule' in captured["user_prompt"]
