# SOC AI Rulebot MVP Build History

_Last updated: 2026-06-30_

## Executive Summary

The original Rulebot MVP validated that a Microsoft Teams user could:

- submit a QRadar rule ID
- receive structured rule analysis
- request an offense-analysis template
- submit offense-analysis requests
- receive QRadar-focused AI guidance

The project evolved through several architecture iterations before stabilizing on the current design.

---

## Final MVP Architecture

```text
Microsoft Teams
    ↓
Teams Frontend Runtime
    ↓ HTTPS
Rulebot Backend API
    ↓
Routing Layer
    ├── Rule Analysis
    ├── Offense Analysis
    ├── General Reasoning
    └── RAG Retrieval
```

---

## Why Multiple Paths Were Tried

Several approaches were evaluated before the current architecture was adopted.

### Early Lessons

- Legacy Bot Framework paths introduced excessive complexity.
- Teams approval alone did not guarantee runtime functionality.
- Frontend and backend responsibilities needed separation.
- Container Apps proved more reliable than earlier hosting attempts.
- Teams SDK + Container Apps produced the most stable solution.

---

## Original MVP Capabilities

### Rule Analysis

Analysts could submit a QRadar rule ID and receive:

- rule purpose
- tuning guidance
- reasoning
- recommendations

### Offense Analysis

Analysts could:

1. Request a new offense template.
2. Populate offense details.
3. Submit the offense to Rulebot.
4. Receive recommendations and analysis.

### Generic Reasoning

Rulebot could answer QRadar-focused questions using indexed documentation.

---

## Backend Repository

```text
soc-ai-rulebot-agent/
```

Responsibilities:

- prompts
- routing
- QRadar rule analysis
- offense analysis
- retrieval
- Azure integrations

---

## Frontend Repository

```text
soc-ai-rulebot-teams-frontend/
```

Responsibilities:

- Teams message handling
- forwarding requests to backend
- Teams packaging

---

## Major Evolution Since MVP

The MVP later gained:

- Azure AI Search
- Vector retrieval
- QRadar rule ingestion
- Building block ingestion
- Daily sync pipeline
- Case memory
- Similar-case retrieval
- PacketGenerator integration
- Structured tuning recommendations

These enhancements are documented in:

```text
docs/Rulebot_Deployment_Guide.md
docs/Rulebot_SOC_Quick_Start_Guide.md
```

---

## Historical Milestone

The MVP demonstrated that Rulebot could move beyond a proof-of-concept into an operational SOC assistant capable of supporting analysts with rule tuning and offense investigations.