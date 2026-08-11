import os
import requests

qradar_url = "https://192.168.51.122/api/analytics/rules/100067"

token = os.getenv("QRADAR_BH_SEC_TOKEN")
if not token:
    raise RuntimeError("QRADAR_BH_SEC_TOKEN environment variable is not set")

ca_cert_path = r"C:\Users\Administrator\OneDrive - Hilal Computers\Documents\SOC AI upgrade docs\soc-ai-rulebot-agent\certs\root-qradar-ca_ca.crt"

response = requests.get(
    qradar_url,
    headers={
        "SEC": token,
        "Version": "19.0",
        "Accept": "application/json",
    },
    verify=r"C:\Users\Administrator\OneDrive - Hilal Computers\Documents\SOC AI upgrade docs\soc-ai-rulebot-agent\certs\qradar_ca_bundle.crt",
    timeout=30,
)

print("Status:", response.status_code)
print("Response preview:", response.text[:500])