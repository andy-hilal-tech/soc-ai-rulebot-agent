import os
import requests

token = (
    os.getenv("QRADAR_BH_SEC_TOKEN")
    or os.getenv("QRADAR_TOKEN")
    or os.getenv("QRADAR_TOKEN_BH")
    or os.getenv("QRADAR_SEC_TOKEN")
    or os.getenv("QRADAR_API_TOKEN")
)

if not token:
    raise RuntimeError(
        "No QRadar token found. Expected one of: "
        "QRADAR_BH_SEC_TOKEN, QRADAR_TOKEN, QRADAR_TOKEN_BH, "
        "QRADAR_SEC_TOKEN, QRADAR_API_TOKEN"
    )

url = "https://192.168.51.122/api/siem/offenses/462687"

params = {
    "fields": "id,description,rules,log_sources"
}

headers = {
    "SEC": token
}

response = requests.get(
    url,
    headers=headers,
    params=params,
    verify=False,
    timeout=30,
)

print(response.status_code)
print(response.text)