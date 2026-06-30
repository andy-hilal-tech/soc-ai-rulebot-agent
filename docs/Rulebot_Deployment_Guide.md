No worries — the file link didn’t render properly on that one. Try this first:

[Download Rulebot\_Deployment\_Guide.md](https://hilalcomputers-my.sharepoint.com/personal/andrew_middleton_pmgdn_com/Documents/Microsoft%20Copilot%20Chat%20Files/Generate-QRadarPacket.txt)

If that still doesn’t work, copy/paste the Markdown below into:

```text
soc-ai-rulebot-agent/docs/Rulebot_Deployment_Guide.md
```

This is based on the updated deployment guide generated from the earlier MVP document plus the recent Rulebot changes. [\[CodeInterpreter \| Undefined\]](https://fr-prod.asyncgw.teams.microsoft.com/v1/objects/0-frca-d4-c4ea4cdb8c19144aa6500547d2f6bdb5/views/original/Rulebot_Deployment_Guide.md), [\[Generate-Q...adarPacket \| Txt\]](https://hilalcomputers-my.sharepoint.com/personal/andrew_middleton_pmgdn_com/Documents/Microsoft%20Copilot%20Chat%20Files/Generate-QRadarPacket.txt)

````markdown
# SOC AI Rulebot — Deployment & Operations Guide

_Last updated: 2026-06-30_

## 1. Purpose

This guide documents the current end-to-end deployment and operations process for SOC AI Rulebot, including backend deployment, Azure AI Search setup, QRadar rule ingestion, Teams rollout considerations, and operational troubleshooting.

The earlier MVP guide documented the initial working architecture: a Teams SDK frontend calling an Azure Container Apps backend `/message` endpoint, with routing for rule lookup, reasoning, offense intake, and offense analysis. This document updates that baseline with recent changes: Azure AI Search-backed rule intelligence, enriched QRadar rule/building-block ingestion, case memory, improved offense analysis, and PacketGenerator support.

## 2. Current Architecture

```text
Microsoft Teams
   ↓
Teams frontend / Teams app runtime
   ↓ HTTPS POST
Azure Container Apps backend: soc-ai-rulebot-agent
   ↓
/message route dispatcher
   ├── Rule lookup
   ├── General QRadar reasoning
   ├── New offense template
   ├── Offense analysis
   ├── Case lookup/update
   └── RAG retrieval over Azure AI Search
````

## 3. Core Azure Resources

* Azure Container Apps backend: `soc-ai-rulebot-agent`
* Azure AI Search index for rules/building blocks: `qradar-rules-index`
* Azure AI Search indexes for official documents and analyst/case memory
* Azure OpenAI chat deployment
* Azure OpenAI embedding deployment
* Cosmos DB for case records / audit trail
* ACR image registry for backend image builds

## 4. Recommended Repository Structure

```text
soc-ai-rulebot-agent/
├── app.py
├── prompts.py
├── requirements.txt
├── config/
│   ├── __init__.py
│   ├── azure_config.py
│   ├── search_config.py
│   └── cosmos_config.py
├── handlers/
│   ├── offense_handler.py
│   ├── rule_handler.py
│   ├── reasoning_handler.py
│   ├── response_formatters.py
│   └── case_writer.py
├── data/
│   ├── rules/
│   │   ├── current/
│   │   ├── previous/
│   │   └── archive/
│   ├── building_blocks/
│   │   ├── current/
│   │   ├── previous/
│   │   └── archive/
│   ├── test_payloads/
│   └── logs/
├── scripts/
│   ├── create_search_indexes.py
│   ├── parse_qradar_csv.py
│   ├── enrich_from_js.py
│   ├── rotate_rule_snapshots.py
│   ├── sync_rule_base.py
│   └── sync_case_memory.py
└── docs/
    ├── Rulebot_Deployment_Guide.md
    ├── Rulebot_SOC_Quick_Start_Guide.md
    └── Generate-QRadarPacket.ps1
```

## 5. Environment Setup

### Python environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Required environment variables

```bash
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_CHAT_DEPLOYMENT=
AZURE_OPENAI_EMBED_DEPLOYMENT=
AZURE_OPENAI_API_VERSION=2025-01-01-preview
SEARCH_ENDPOINT=
SEARCH_ADMIN_KEY=
SEARCH_INDEX_NAME=qradar-rules-index
COSMOS_ENDPOINT=
COSMOS_KEY=
COSMOS_DATABASE_NAME=
COSMOS_CASE_CONTAINER_NAME=
PORT=8000
```

### Python import path issue

If scripts fail with:

```text
ModuleNotFoundError: No module named 'config'
```

run from repo root and set:

```bash
export PYTHONPATH=/home/vignesh/soc-ai-agents/soc-ai-rulebot-agent
```

or add this to standalone scripts:

```python
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
```

## 6. Azure AI Search Index Setup

Rules and building blocks are stored in one combined index:

```text
qradar-rules-index
```

Key document fields:

```text
rule_doc_id
rule_id
rule_name
object_type        # rule | building_block
group_name
rule_category
enabled
content
content_vector
last_indexed_utc
```

`object_type` is critical because Rulebot must distinguish QRadar correlation rules from building blocks while preserving unified retrieval.

After schema changes, recreate indexes using Python SDK scripts rather than Azure CLI index commands:

```bash
python scripts/delete_index.py
python scripts/create_search_indexes.py
python scripts/sync_rule_base.py
```

## 7. Daily QRadar Rule Ingestion Pipeline

### Source exports

Daily exports from QRadar Use Case Manager:

* Rules CSV export
* Building Blocks CSV export
* Rule-Data ZIP for Rules containing `rules.js`
* Rule-Data ZIP for Building Blocks containing `rules.js`

CSV exports provide clean metadata. `rules.js` exports provide logic, dependencies, actions, responses, limiter details, and MITRE mappings.

### Snapshot lifecycle

```text
previous -> archive/<timestamp>
current  -> previous
new export parse output -> current
```

Archive folders should be excluded from Git:

```gitignore
data/rules/archive/
data/building_blocks/archive/
data/logs/
```

### Daily run order

```bash
rulebotenv
python scripts/rotate_rule_snapshots.py
python scripts/parse_qradar_csv.py
python scripts/enrich_from_js.py
python scripts/sync_rule_base.py
```

Expected behavior:

* `parse_qradar_csv.py` writes individual JSON files to `current/`
* `enrich_from_js.py` adds logic, actions, dependencies, limiter, and MITRE fields
* `sync_rule_base.py` compares current vs previous, uploads new/changed/missing records, and deletes records removed from QRadar

## 8. Backend Deployment

### Build backend image

```bash
az acr build \
  --registry socairulebotacr \
  --image rulebot-agent:<tag> \
  .
```

### Update Container App

```bash
az containerapp update \
  --name soc-ai-rulebot-agent \
  --resource-group soc-ai-rg-agents \
  --image socairulebotacr.azurecr.io/rulebot-agent:<tag>
```

### Verify revisions

```bash
az containerapp revision list \
  -n soc-ai-rulebot-agent \
  -g soc-ai-rg-agents \
  -o table
```

If the latest healthy revision has traffic weight `0`, route traffic explicitly:

```bash
az containerapp ingress traffic set \
  --name soc-ai-rulebot-agent \
  --resource-group soc-ai-rg-agents \
  --revision-weight soc-ai-rulebot-agent--<revision>=100
```

Deactivate old revisions after confirming the new revision works:

```bash
az containerapp revision deactivate \
  --name soc-ai-rulebot-agent \
  --resource-group soc-ai-rg-agents \
  --revision soc-ai-rulebot-agent--<old-revision>
```

## 9. PacketGenerator Setup

Store the PacketGenerator script temporarily under:

```text
tools/windows/Generate-QRadarPacket.ps1
```

Before use, update QRadar instance configuration:

```powershell
$Instances = @{
    "BH" = @{
        Name = "BH"
        BaseUrl = "https://<BH-QRADAR-IP-OR-FQDN>"
        Token = $env:QRADAR_BH_SEC_TOKEN
        ClientId = "default"
    }
}
```

For the current PowerShell session:

```powershell
$env:QRADAR_BH_SEC_TOKEN = "<token>"
```

For persistent user-level storage:

```powershell
:SetEnvironmentVariable(
  "QRADAR_BH_SEC_TOKEN",
  "<token>",
  "User"
)
```

Restart PowerShell after setting the persistent variable.

Verify:

```powershell
$env:QRADAR_BH_SEC_TOKEN.Length
```

Do not commit API tokens to Git.

## 10. PacketGenerator Output Fields

The canonical offense template is:

```text
offense_id:
client_id:
rule_id:
event_name:
event_description:
source_ip:
source_port:
destination_ip:
destination_port:
username:
log_source:
qid:
category:
magnitude:
start_time:
event_count:
payload_summary:
why_false_positive:
desired_outcome:
analyst_notes:
```

Analysts fill:

```text
why_false_positive
desired_outcome
analyst_notes
```

## 11. QRadar Ariel Findings

Observed during PacketGenerator implementation:

* Ariel searches must be polled until completed before fetching results.
* `RangeHeader` / paging was not supported by the tested Ariel results endpoint.
* `LIMIT 1` after `LAST 24 HOURS` caused AQL syntax failure in the tested QRadar instance.
* `eventname` was not a valid field in the tested `events` catalog.
* Valid tested sample fields included `starttime`, `qid`, `username`, `sourceip`, `sourceport`, `destinationip`, `destinationport`, `logsourceid`, and `category`.

## 12. Functional Validation Tests

### Rule lookup

```bash
curl -s -X POST "https://<backend-url>/message" \
  -H "Content-Type: application/json" \
  -d '{"text":"124702"}' | jq -r '.reply'
```

### New offense template

```bash
curl -s -X POST "https://<backend-url>/message" \
  -H "Content-Type: application/json" \
  -d '{"text":"new offense"}' | jq -r '.reply'
```

### Offense analysis regression payload

```bash
mkdir -p data/test_payloads

cat > data/test_payloads/offense_454702.json <<'EOF'
{
  "text": "- offense_id: 454702\n- client_id: default\n- rule_id: 124702\n- qid:\n- event_name: Possible Shared Account containing API request successful\n- event_description: Possible Shared Account containing API request successful\n- payload_summary: Status=OPEN | Magnitude=6 | Severity=8 | Relevance=6 | Credibility=3 | EventCount=12 | LogSourceCount=2 | FrequencyLast1h=unknown\n- why_false_positive: Legitimate activity\n- desired_outcome: Only generate an alert there are 10 API request failure events within 15 minutes\n- analyst_notes: Testing the AI Bot for QRadar Rule Fine-tuning activity"
}
EOF
```

Run:

```bash
curl -s -X POST "http://127.0.0.1:8000/message" \
  -H "Content-Type: application/json" \
  --data @data/test_payloads/offense_454702.json | jq
```

Expected:

* offense analysis route succeeds
* rule is found under `data/rules/current/`
* recommendations are concrete
* no placeholder-only `Recommendation` lines appear

## 13. Troubleshooting Notes

### Rule not found in local rules database

Check:

```text
data/rules/current/<rule_id>.json
```

The rule loader should check:

```text
data/rules/current/
data/building_blocks/current/
data/rules/
data/building_blocks/
```

### Azure Search field does not exist

If Azure Search rejects a document field, update and recreate the index schema.

Example:

```text
object_type does not exist on type search.documentFields
```

### New revision healthy but not live

Check traffic weights and route traffic to the latest healthy revision.

### Placeholder recommendations

The formatter and output schema should prevent placeholder-only output such as:

```text
Recommendation
Recommendation
```

Expected behavior is concrete tuning options or a safe fallback.

## 14. Production Hardening Roadmap

Before full productization:

* move secrets to managed secret storage / Key Vault
* move exports and archives to corporate-controlled storage
* automate ingestion with scheduled jobs
* separate dev/test/prod Azure resources
* add structured logging and monitoring
* formalize image tags and release notes
* package PacketGenerator with signed/internal distribution process
* add Teams `/help` command or equivalent help menu

````

After you paste/save this one, you should have:

```text
docs/Rulebot_Deployment_Guide.md
docs/Rulebot_SOC_Quick_Start_Guide.md
docs/Generate-QRadarPacket.ps1
````
