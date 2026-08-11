import os
import requests
import urllib3

urllib3.disable_warnings()

BASE_URL = "https://192.168.51.122"
TOKEN = os.environ["QRADAR_BH_SEC_TOKEN"]

headers = {
    "SEC": TOKEN,
    "Version": "19.0",
    "Accept": "application/json",
}

for rng in [
    "items=0-0",
    "items=0-9",
    "items=0-99",
    "items=0-199",
    "items=0-1999",
]:
    h = headers.copy()
    h["Range"] = rng

    r = requests.get(
        f"{BASE_URL}/api/analytics/building_blocks",
        headers=h,
        params={"fields": "id,name"},
        verify=False,
        timeout=60,
    )

    print("\n" + "=" * 80)
    print("Requested Range:", rng)
    print("Status:", r.status_code)
    print("Content-Range:", r.headers.get("Content-Range"))

    try:
        data = r.json()
        print("Returned objects:", len(data))
    except Exception as e:
        print("JSON parse failed:", e)
        print(r.text[:500])