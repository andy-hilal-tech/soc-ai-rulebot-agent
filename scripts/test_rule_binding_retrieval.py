import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from offense_parser import parse_offense_template
from azure_search_retriever import retrieve_rule_docs_for_offense_bindings


def main():
    if len(sys.argv) > 1:
        packet_path = Path(sys.argv[1])
    else:
        packet_path = PROJECT_ROOT / "tools" / "windows" / "output" / "RulebotPacket-462687.txt"

    text = packet_path.read_text(encoding="utf-8")
    offense_data = parse_offense_template(text)

    query = " ".join([
        str(offense_data.get("event_name", "")),
        str(offense_data.get("event_description", "")),
        str(offense_data.get("rule_id", "")),
        str(offense_data.get("resolved_rule_bindings", "")),
    ])

    results = retrieve_rule_docs_for_offense_bindings(
        offense_data=offense_data,
        query=query,
        top_k=6,
    )

    print("Result count:", len(results))

    for item in results:
        print("---")
        print("source:", item.get("source"))
        print("rule_doc_id:", item.get("rule_doc_id"))
        print("rule_id:", item.get("rule_id"))
        print("rule_name:", item.get("rule_name"))
        print("object_type:", item.get("object_type"))


if __name__ == "__main__":
    main()