import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from config.search_config import get_search_client, RULES_INDEX_NAME


def count_filter(client, filter_expr: str | None = None) -> int:
    results = client.search(
        search_text="*",
        filter=filter_expr,
        include_total_count=True,
        top=1,
    )

    return results.get_count()


def main():
    client = get_search_client(RULES_INDEX_NAME)

    total = client.get_document_count()
    rules = count_filter(client, "source_type eq 'rule_json'")
    building_blocks = count_filter(client, "source_type eq 'building_block_json'")

    print(f"Total documents: {total}")
    print(f"Rule documents: {rules}")
    print(f"Building block documents: {building_blocks}")


if __name__ == "__main__":
    main()