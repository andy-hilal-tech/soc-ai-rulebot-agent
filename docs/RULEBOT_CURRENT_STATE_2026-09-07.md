# Rulebot Current State

**Checkpoint date:** 2026-09-07  
**Purpose:** Record the restored Rulebot production state before development focus returns to L1 AnalystBot and OpenCTI evaluation.

---

## 1. Executive Summary

Rulebot has been restored as an operational legacy service in the Production Azure tenant.

The legacy Azure AI Search indexes and Cosmos DB case memory were exported from the Test tenant, recreated in Production, and successfully imported.

Rulebot is intentionally retained as a separate operational service for QRadar rule investigation and tuning assistance.

Rulebot has not been modernized or migrated to the L1 AnalystBot canonical corpus. The active Rulebot retrieval implementation uses the restored legacy Rulebot indexes.

The final Teams transport test remains pending while the Teams application deployment and access scope are corrected.

---

## 2. Migration Objective

The objective of this migration was:

- restore Rulebot with minimum redevelopment;
- preserve historical case memory;
- preserve legacy QRadar rule and documentation indexes;
- use Managed Identity for Azure resource access;
- avoid unnecessary modernization;
- retain Rulebot until equivalent functionality is proven in L1 AnalystBot.

The objective was not to redesign Rulebot or make the legacy corpus authoritative for future L1 AnalystBot development.

---

## 3. Azure Subscription Context

### Source Environment

- Subscription: Test
- Subscription ID: `4fe486e0-b98d-4574-be21-9412f4666474`
- Tenant ID: `5398f467-c183-4063-9eb7-e778e9ecbad9`

### Destination Environment

- Subscription: Production
- Subscription ID: `0fca259f-f050-41b1-bc33-15c71b08f4d3`
- Tenant ID: `6c26415f-aa6e-4d43-bee9-b5508d9955f7`

The tenants differ. Direct Azure resource transfer was therefore rejected in favour of deterministic export and import.

---

## 4. Production Rulebot Resources

### Azure AI Search

**Service:**
Indexes
analyst-memory-index
qradar-official-index
qradar-rules-index

Imported document counts:
analyst-memory-index:       2
qradar-official-index:    628
qradar-rules-index:     1,977

All three indexes use:
Vector field: content_vector
Vector type: Collection(Edm.Single)
Dimensions: 3072
Algorithm: HNSW
Metric: cosine
Profile: default-vector-profile
Stored: true
Retrievable: false

The original vectors could not be exported because the vector fields were non-retrievable.

Vectors were regenerated from the preserved content fields using the existing Azure OpenAI text-embedding-3-large deployment and uploaded with the migrated documents.

### Cosmos DB

Account:
soc-ai-rulebot-cosmos-prod

Database:


rulebotdb


Container:


case-records


Partition key:


/client_id


Imported historical case records:


34

5. Managed Identity

Rulebot Container App uses the following user-assigned Managed Identity:


Identity name: rulebot-mi
Client ID: 6c80762a-1f5d-4336-91db-fe6d728156b8
Principal ID: 595499ba-2ba1-4b76-93d2-a1ebb58c21a2

Azure AI Search access

The identity has Search data-plane access on:


soc-ai-rulebot-search-prod


Required runtime role:


Search Index Data Reader

Cosmos DB access

The identity has Cosmos DB native data-plane access scoped to:


/dbs/rulebotdb/colls/case-records

 


The current assignment permits Rulebot to read and update historical case memory.

Managed Identity is the intended Production authentication method.

Search admin keys and Cosmos account keys must not be added to the Production Container App unless required for a controlled emergency recovery operation.

6. Container App

Container App:
rulebot-vtemp

Resource group:
soc-ai-rg

Container registry:
socairulebotprod


The deployed application exposes:


GET /
GET /health
POST /analyze_rule
POST /message
POST /api/messages


The latest deployed revision was validated as healthy during the restoration process.

rulebot-vtemp--0000006
socairulebotprod.azurecr.io/rulebot-vtemp:bbd44ff

Use Azure CLI to retrieve the current revision rather than relying on this document:

Shell

az containerapp revision list \

--name rulebot-vtemp \

--resource-group soc-ai-rg \

--output table

7. Runtime Configuration

Rulebot is configured to use its own restored backends.

Search

SEARCH_ENDPOINT=https://soc-ai-rulebot-search-prod.search.windows.net

Cosmos

COSMOS_ENDPOINT=https://soc-ai-rulebot-cosmos-prod.documents.azure.com:443/

COSMOS_DATABASE_NAME=rulebotdb

COSMOS_CASE_CONTAINER=case-records

Managed Identity selection

AZURE_CLIENT_ID=6c80762a-1f5d-4336-91db-fe6d728156b8

Azure OpenAI

Rulebot currently uses an existing Azure OpenAI resource and deployments.

The embedding deployment is:


text-embedding-3-large


The shared Azure OpenAI resource is acceptable for the restored legacy service. A dedicated Rulebot reasoning deployment may be considered later if cost attribution or operational separation justifies it.

8. Local Development Environment

Rulebot now has a dedicated Python virtual environment:


/data/github/soc-ai-rulebot-agent/.venv

 


Do not run Rulebot from the L1 AnalystBot virtual environment.

Recommended session initialization
Shell

cd /data/github/soc-ai-rulebot-agent

source .venv/bin/activate

set -a
source .env
set +a


The Rulebot .env is repository-specific and must remain excluded from Git and Docker build context.

The .env contains local development settings. Production Container App variables are configured separately in Azure.

Build exclusions

The repository contains a .dockerignore that excludes:

.env;
.venv;
Git metadata;
Python caches;
Graphify output;
local logs and development artifacts.


9. Retrieval Architecture

The active Rulebot retrieval implementation uses the legacy indexes:


qradar-rules-index
qradar-official-index
analyst-memory-index


The previous attempt to migrate Rulebot retrieval to the L1 AnalystBot canonical corpus was not retained for the restored legacy service.

Rulebot and L1 AnalystBot therefore have deliberately separate Search backends and schemas.

Natural-language retrieval

Natural-language reasoning now includes:

official QRadar documentation;
analyst memory;
legacy QRadar rules.

If a natural-language query contains a numeric rule ID, the retriever performs an exact filtered lookup against the rule_id field and prioritizes the matching rule in the reasoning context.

Rule context is normalized to include:


Rule ID
Rule Name
Rule Content


This improves the consistency of grounded responses.

Direct rule lookup

An all-numeric /message request routes to the direct rule handler.

Example:

JSON
{
"text": "112002"
}


The /analyze_rule endpoint accepts:

JSON
{
"rule_id": "112002"
}

10. Validated Functional Tests

The following capabilities were successfully tested.

Health

GET /health


Returned a healthy Rulebot service response.

Direct rule lookup

Rule ID:


112002


Resolved to:


Process Launched from a Temp Directory

Natural-language exact rule lookup

A question asking what rule 112002 does returned a grounded explanation using the correct rule content.

Semantic rule discovery

A query for rules involving processes launched from temporary directories retrieved and reasoned over relevant legacy rules, including:


112002
112202
110352
112152
161102
 

Official-document reasoning

A question about QRadar Building Blocks returned a grounded response using the migrated official-document index.

Offense analysis

A full PacketGenerator Offense Template was posted to:


POST /message


Rulebot correctly routed it as:


offense_analysis


The workflow:

parsed the offense payload;
used INOFFENSE_ONLY evidence;
interpreted top distributions;
used representative events only as examples;
resolved available QRadar rule metadata;
queried rule context;
retrieved official documentation;
retrieved historical case memory;
produced a confidence-based assessment;
created a historical case record;
produced a tuning implementation section;
declined to invent unavailable rule logic.


11. Known Corpus Coverage Limitation

The restored Rulebot corpus is not fully synchronized with the current live QRadar rule set.

During the final offense test, live QRadar returned:


Offense rule ID: 100067

Rule name: Multiple Login Failures for Single Username

Linked rule identifier: d26624b0-2441-4a57-ba64-a057ada319b1

QRadar identifier: SYSTEM-1543


No matching exported rule document existed in the legacy Rulebot corpus.

The binding result was:


metadata_only_no_exported_match



Rulebot correctly avoided inventing threshold, time-window or condition-level tuning guidance.

This is a known and acceptable limitation for the restored legacy service.

The more complete L1 AnalystBot canonical corpus remains the future authoritative rule knowledge source.

12. Final Offense Test Outcome

The final offense test produced:


Classification: inconclusive
Confidence: low


The response correctly explained that:

five offense-linked events were observed;
four events used QID 5000475;
one event used QID 67500015;
the source and destination were 172.20.20.101;
the username was prepress3;
the complete CRE rule logic was unavailable;
no concrete tuning recommendation could safely be made;
further user, system-owner and raw-log validation was required.

This is considered valid safety behaviour and preferable to unsupported tuning advice.

13. Case Memory and Audit Trail

Rulebot retains historical cases in Cosmos DB.

The purpose of case memory includes:

retrieving similar historical investigations;
recording analyst decisions;
preserving tuning recommendations;
recording implementation status;
supporting future false-positive analysis;
enabling audit reconstruction;
documenting who made a decision, when it was made and why;
producing historical case reports when required.

The historical case model should remain append-friendly and auditable.

Future changes should preserve evidence snapshots and decision history rather than overwriting the reasoning behind earlier decisions.

14. Migration and Recovery Artifacts

Migration artifacts are stored outside the repository under:


/data/rulebot-migration

 


Artifacts include:

Cosmos export;
Search document exports;
individual Search schemas;
combined QRadar rule export;
Search migration reports;
Cosmos migration report;
previous image reference;
locally retained migration backup.

The migration scripts are retained in the repository:


scripts/migrate_search_export.py
scripts/migrate_cosmos_export.py


These scripts provide an auditable and reproducible recovery path.

Migration data, generated embeddings, reports and secrets must not be committed to Git.

15. Teams Integration Status

The Teams application was approved, but the initial approval appears to have allowed overly broad organization-level availability.

The intended access scope is the SOC team only.

The Teams application must not be broadly discoverable or installable by the full organization because unnecessary use would:

generate avoidable model and enrichment costs;
expose a specialist SOC tool outside its intended audience;
complicate support and governance;
increase accidental or irrelevant usage.

A later installation attempt returned:


Invalid Bot


This issue remains pending.

Potential areas to verify later include:

Teams app manifest;
bot application ID;
Microsoft Entra app registration;
tenant ID;
valid domains;
bot endpoint;
messaging endpoint;
SingleTenant configuration;
Container App /api/messages route;
Teams app permission and setup policies;
SOC-only access assignment;
client-secret validity and rotation.

No further Teams changes should be made until the intended SOC-only distribution model is confirmed.

16. Security Actions
Secrets

Do not store the following in Git:

Azure OpenAI API keys;
Search admin keys;
Cosmos keys;
Microsoft application passwords;
QRadar tokens;
connection strings.

If any Microsoft application password or other secret was exposed during diagnostics, rotate it before enabling production Teams traffic.

Production authentication

Preferred authentication:


Managed Identity


The Container App should use:


rulebot-mi


for Search and Cosmos access.

Least privilege

Review and reduce permissions after final Teams validation.

17. Deferred Work

Rulebot development is paused pending the Teams integration correction.

Deferred Rulebot work includes:

resolving the Teams Invalid Bot error;
restricting the app to SOC users;
final Teams end-to-end message test;
validating Teams identity and message transport;
periodically refreshing the legacy rule corpus if Rulebot remains long-lived;
deciding whether Rulebot should eventually query the canonical corpus through an adapter;
migrating proven Rulebot capabilities into L1 AnalystBot, if that remains the preferred architecture.

Rulebot is not currently scheduled for broad modernization.

18. Future Architecture Decision

The relationship between Rulebot and L1 AnalystBot remains open.

Possible options are:

Option A: Integrate Rulebot functionality into L1 AnalystBot

Advantages:

direct access to the canonical corpus;
fewer deployed applications;
shared queues, evidence and reporting;
simpler user experience.

Risks:

redevelopment effort;
migration risk;
tighter coupling;
possible loss of an already working specialist module.
Option B: Keep Rulebot as an external specialist module

L1 AnalystBot would invoke Rulebot when rule investigation or tuning is required.

Advantages:

modular architecture;
specialist boundaries;
independent deployment and testing;
existing Rulebot behavior can be retained;
similar module boundaries could be used for other investigation capabilities.

Risks:

cross-service authentication;
duplicate data models;
separate case and audit storage;
additional operational components;
legacy corpus synchronization.
Option C: Hybrid integration

Retain Rulebot as a specialist service while gradually replacing its data and retrieval dependencies with shared L1 AnalystBot services.

This decision should be made using:

operational usage;
maintenance cost;
analyst feedback;
corpus freshness requirements;
latency;
audit requirements;
reliability;
module reuse potential.

Do not rewrite Rulebot solely for architectural neatness.

19. Operational Status

At this checkpoint:


Search migration: COMPLETE
Cosmos migration: COMPLETE
Vector regeneration: COMPLETE
Managed Identity: COMPLETE
Container App deployment: COMPLETE
Health test: PASSED
Direct rule lookup: PASSED
Natural-language rule lookup: PASSED
Semantic rule discovery: PASSED
Official-document reasoning: PASSED
Offense analysis: PASSED
Case-memory retrieval: PASSED
Teams transport test: PENDING
Teams SOC-only restriction: PENDING


Rulebot is considered operational at the API layer.

Further work is paused until the Teams app configuration is ready for controlled SOC-only testing.

20. Next Project Focus

Development focus returns to:


/data/github/soc-ai-l1-analyst-bot


The next phase should:

incorporate analyst pain points and baseline handling times;
instrument investigation duration and user-value metrics;
define management and L2/L3 review dashboards;
evaluate OpenCTI as a threat-intelligence and relationship backbone;
determine which capabilities OpenCTI can provide versus what requires custom development;
preserve modular architecture options;
plan regular stop-and-revise product-value gates;
retain the Architect, Claim Extractor and Reviewer harness as the project expands;
prioritize authentication, IOC, identity, asset and false-positive workflows;
preserve historical investigation and audit reporting requirements.