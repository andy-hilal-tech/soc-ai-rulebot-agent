# Rulebot Agent Instructions

This repository is the SOC Rulebot project.

Rulebot helps analysts review QRadar rules, understand rule noise, and generate safe rule tuning recommendations.

## Core Purpose

Rulebot should help analysts answer:

- What does this QRadar rule do?
- Why is this rule noisy?
- What evidence suggests the rule should be tuned?
- What safe tuning options exist?
- How should an approved analyst implement the tuning change in QRadar?
- How should the change be validated and rolled back?

## Non-Negotiable Constraints

- Do not modify QRadar rules directly.
- Do not generate instructions that imply the bot can deploy QRadar rule changes automatically.
- Do not invent QRadar field names, test names, reference sets, building blocks, or rule logic that are not present in the evidence.
- If exact QRadar implementation details are missing, clearly state what must be confirmed by a senior analyst.
- Always separate:
  - Observed evidence
  - Interpretation
  - Recommendation
  - Implementation guidance
  - Risks
  - Validation
  - Rollback
- Prefer safe, senior-analyst-reviewable recommendations.
- Do not recommend suppressing alerts without explaining the risk.
- Do not recommend excluding users, hosts, IPs, services, or events unless the evidence supports it.
- Do not remove or weaken security logic without documenting expected impact and rollback.
- Do not hardcode secrets, tokens, QRadar URLs, API keys, or credentials.
- Do not use `DATABASE_URL` unless the existing project already uses it.
- Do not introduce new dependencies unless explicitly requested.

## Required Rulebot Output Direction

Rulebot must evolve from generic tuning advice to actionable implementation guidance.

Every rule tuning output should eventually include:

1. Rule Summary
2. Current Noise / False Positive Drivers
3. Recommended Tuning Change
4. QRadar Rule Tuning Implementation Guide
5. Validation Plan
6. Rollback Plan
7. Risk / Analyst Approval Notes

## QRadar Rule Tuning Implementation Guide

## Known QRadar Rule Tuning UI Path

For this SOC environment, QRadar rule tuning is performed through:

1. Open QRadar Console.
2. Select the Offenses tab in the top navigation.
3. Select Rules in the left-hand Offenses menu.
4. Search by Rule Name. Do not assume the UI supports searching by Rule ID.
5. Double-click the matching rule.
6. The Rule Wizard opens in a separate window.
7. The top pane lists available rule tests or logical operations.
8. The centre pane contains the current rule logic.
9. Existing logic operations in the centre pane can be moved, removed, or edited.
10. Clickable or underlined values inside the rule logic are adjustable parameters.
11. The lower pane shows rule group membership and should only be changed if evidence supports it.
12. Save or finish the wizard and deploy according to the local QRadar change process.

Do not replace this with generic wording such as "Rules tab → Custom Rules" unless verified in the live environment.

## Implementation Guidance Style

The implementation guidance should be written so that a less experienced analyst can follow it after a senior analyst approves the recommendation.

Preferred style:

1. Open QRadar Console.
2. Navigate to the relevant rule or rule group.
3. Locate the relevant test or condition.
4. Add or modify the specified condition.
5. Save.
6. Deploy changes.
7. Monitor results.
8. Roll back if needed.

## Safety Requirements for Tuning

Every tuning recommendation must include:

- Why the change is recommended
- What evidence supports the change
- What could be missed if the change is wrong
- How to validate after deployment
- How to roll back

## Current Known SOC Need

The SOC team needs detailed QRadar tuning implementation guidance.

Generic advice like:

"Add a condition to match the Message field"

is not enough.

Rulebot should aim to produce operational SOP-style guidance such as:

- where to click
- what rule condition to add
- what values to insert
- what to validate
- what to monitor
- how to roll back

## Agent Behavior

- Make small, reviewable changes.
- Inspect relevant files before editing.
- Do not refactor unrelated code.
- Run only relevant tests.
- Summarize changed files and test results.
- Ask for clarification if the repository structure is ambiguous.