from config.cosmos_config import get_case_records_container


def get_case(case_uid: str):
    container = get_case_records_container()
    try:
        # partition key is client_id in your design, so this direct read may fail
        # if you don't know client_id. We will improve this below.
        query = "SELECT * FROM c WHERE c.case_uid = @case_uid"
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@case_uid", "value": case_uid}],
            enable_cross_partition_query=True
        ))
        return items[0] if items else None
    except Exception:
        return None


def update_case_status(case_uid: str, new_status: str):
    container = get_case_records_container()

    try:
        query = "SELECT * FROM c WHERE c.case_uid = @case_uid"
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@case_uid", "value": case_uid}],
            enable_cross_partition_query=True
        ))

        if not items:
            return None

        case = items[0]
        case["implementation_status"] = new_status
        case["last_updated_at"] = case.get("last_updated_at") or case.get("created_at")

        container.upsert_item(case)
        return case

    except Exception:
        return None